"""EPUB, OpenDocument (ODT, ODS, ODP) and RTF as Markdown with the standard library alone (2026-11-20).

pandoc - pypandoc_binary, 41 MB of --setup's download and 226 MB on disk - read EPUB, ODT and RTF
and nothing else here; measured against it on 52 files, these readers lose nothing it kept and
keep what it lost. They need nothing but the standard library: an EPUB's XHTML goes through
html.parser, which expands no entity a DTD declares; an OpenDocument file's XML through
ElementTree, a DOCTYPE refused first; an RTF through a tokenizer of our own. A spreadsheet's sheets
and a presentation's slides are read as a text's body is (2026-11-21: they were plain paragraphs
in readpage's own process).

readpage.py runs them in a process of their own (`python docreaders.py KIND PATH UNTIL KILL`, see
main()), killed at the converter's time and held to MEMORY where the OS can hold it (RLIMIT_AS on
Linux, a Job Object on Windows: _limit_memory): a reader stops itself at `until`, and the kill is
the backstop for what it does not foresee. What
they build is bounded by the document, not by its elements: a table's grid by CELLS and all of a
document's tables by DOC_CELLS, whatever its cells span or repeat (a 1 KB EPUB took 1.4 GB and a
4.5 KB ODT 40 s, because a cap held per cell and multiplied across cells); a sheet's by the cells it
stores (SHEET_CELLS), what its repeats copy by CELLS. No scan runs back over
what it has passed: a tag is TAG_MAX characters at most and holds no "<", a rule that closes an
element looks up where it is open, a list or a paragraph is joined once.

Each reader returns (markdown, note): note is "" or what it could not do - the time ran out after
chapter 12 of 40, a part over the size limit, XML that breaks somewhere (what came before is kept),
a part or an element that broke (the others are read), a table cut at its cap. A picture is
![alt](its path in the archive), so readpage's doc_pictures() puts its marker where the picture
stands; a footnote is [^n] where it is called and "[^n]: its text" (an EPUB: where the book keeps
its notes; ODT, RTF: at the end); a table is a Markdown table whose merged cells leave their other
places empty. The document's own text is escaped for Markdown, so its literal ![x](y), [a] or *b*
stay text. An archive's part is read up to PART_BYTES and all of them together up to TOTAL_BYTES
unpacked, whatever their headers claim - but an OpenDocument file's content.xml is read as it
unpacks, and a spreadsheet's up to SHEET_BYTES, its rows dropped as they are read (_Body); `until`
(a time.time() to stop by, None for no limit) is checked between chapters and every few hundred
elements."""
import bisect
import codecs
import html
import json
import os
import posixpath
import re
import sys
import time
import urllib.parse
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
from xml.parsers import expat

PART_BYTES = 32 * 1024 * 1024      # one part of an archive, unpacked
TOTAL_BYTES = 128 * 1024 * 1024    # every part one reader takes from one archive
RTF_BYTES = 128 * 1024 * 1024      # an RTF's own bytes (pictures make the big ones)
DEPTH = 100                        # nesting a renderer follows; what is deeper comes as plain text
OPEN = 2000                        # elements the tree builder keeps open; deeper start tags become siblings
NODES = 500000                     # elements of one part (a part that unpacks to 1 GB of <p>a</p>
                                   # built 4 million of them, 2 GB, 2026-11-20)
ROWS = 20000                       # rows of one table (a text's; a sheet's are what SHEET_CELLS leaves room for)
WIDTH = 1024                       # columns of one table: a row's cells past it join its last cell
CELLS = 250000                     # one table's grid, rows x columns, its spans and repeats included; of a
                                   # sheet, the cells with text that only a repeat makes (copies)
DOC_CELLS = 1000000                # the grids of all of one document's tables; of a workbook, its sheets' copies
SHEET_CELLS = 2000000              # one sheet's grid, rows x columns: what it stores itself, a cell a time
DOC_SHEET_CELLS = 4000000          # the grids of all of one workbook's sheets
HELD = 100000                      # elements a spreadsheet's tree holds at once past its styles: its open row's cells
                                   # (WIDTH of them, the rest's text kept apart) and its other parts (_Body)
SHEET_BYTES = 512 * 1024 * 1024    # a spreadsheet's content.xml, read as it unpacks and its rows dropped as
                                   # they are read (_Body): it costs time, not memory
TABLE_BYTES = PART_BYTES           # the text of one table's cells, a repeated cell's as often as it is repeated
DOC_TABLE_BYTES = TOTAL_BYTES      # ... of all of one document's tables
TAG_MAX = 8192                     # characters of one tag: a "<" no ">" closes within them is text
RUNS = 50000                       # runs of one look in an RTF paragraph; past them its rest is plain
CELLX = 256                        # cell borders of one RTF row definition
SPACES = 1000000                   # spaces an ODT's text:s may add to one document
FINISH = 1.0                       # seconds past `until` for writing what was read
MEMORY = 2 << 30                   # the readers' process: its address space where the OS limits it
PROMISE = 300                      # "--download reads it whole" when the whole would take this at most
PICTURES = 1000                    # pictures an RTF gives up to; their bytes are TOTAL_BYTES at most
PICTURE_BYTES = PART_BYTES         # one picture of an RTF


class Late(Exception):
    """The time given to a reader ran out."""


class _Clock(object):
    """The time a reader has, and what it may still build for one document (table cells, spaces);
    what a cap cut is counted, to be said once in the note."""
    __slots__ = ("until", "finish", "n", "t0", "cells", "spaces", "cuts", "table_bytes", "sheet_cells", "copies")

    def __init__(self, until, finish=None):
        self.until, self.n, self.t0 = until, 0, time.time()
        self.finish = finish if finish is not None or until is None else until + FINISH
        self.cells, self.spaces, self.cuts, self.table_bytes = 0, 0, {}, 0
        self.sheet_cells, self.copies = 0, 0

    def tick(self):
        if self.until is not None:
            self.n += 1
            if not self.n & 255 and time.time() > self.until:
                raise Late()

    def late(self):
        return self.until is not None and time.time() > self.until

    def finishing(self):
        """The reading is over: what was read is written by `finish`, a little later."""
        self.until = self.finish

    def cut(self, what, n=1):
        self.cuts[what] = self.cuts.get(what, 0) + n

    def said(self):
        return "; ".join("%s: %d" % (what, n) if n > 1 else what for what, n in self.cuts.items())

    def more(self, done):
        """"; --download reads it whole" when, at the pace so far, the whole would take PROMISE
        seconds at most: a read its time cut, not one that would not end with all the time there is
        (it was said of a book read 0 parts of 1 in 91 s)."""
        spent = time.time() - self.t0
        return "; --download reads it whole" if 0 < done and spent / done <= PROMISE else ""


LOST = "lost in the cut"     # tabs.STATE["cut"], which this module, the standard library alone, does not import
SHEET_ROWS = 1048576         # a sheet's rows at most: past it no row is lost
LOST_SHEETS = 50             # a cut workbook's lost sheets named one by one, then how many more (_cut_lost)
SHEETS_AT_MOST = 10000       # a workbook's sheets at most (LibreOffice's own limit): a count past it is not believed


def lost_marker(kind, name, *props):
    """What a cut archive lost, where it was lost, in the grammar of every marker (tabs.marker): its type, its
    state, what more there is to say, its name last - `[rows · lost in the cut · 54-? · Third]`."""
    name = re.sub(r"\s+", " ", (name or "").replace("[", "(").replace("]", ")").replace("·", "-")).strip()
    name = name if len(name) <= 200 else name[:199].rstrip() + "…"
    return "[%s]" % " · ".join([kind, LOST] + [p for p in props if p] + ([name] if name else []))


def read(path, kind, until=None, finish=None, pictures=None):
    """(markdown, note) of an EPUB, an OpenDocument file (ODT, ODS, ODP) or an RTF file; ("", why)
    when it gives no text. A part or an element that breaks loses that part, and the note names it;
    a reader that breaks as a whole leaves the document's plain text (its words in order, no
    tables), and says so. `pictures`: a folder an RTF's pictures are written to (rtf_md). KIND "ods+cut":
    the copy of an archive cut in its content.xml, whose break is the cut (odt_md names what it lost)."""
    kind, _plus, how = kind.partition("+")
    try:
        if kind == "epub":
            return epub_md(path, until, finish)
        if kind in ("odt", "ods", "odp"):
            return odt_md(path, until, finish, cut=how == "cut")
        if kind == "rtf":
            with open(path, "rb") as fh:            # read(n) sets n bytes aside first: no more than the file has
                data = fh.read(min(os.fstat(fh.fileno()).st_size, RTF_BYTES) + 1)
            md, note = rtf_md(data[:RTF_BYTES], until, finish, pictures)
            if len(data) > RTF_BYTES:
                note = _join(note, "the file was read up to %d MB" % (RTF_BYTES >> 20))
            return md, note
    except Late:
        return "", "the time ran out"
    except zipfile.BadZipFile as e:
        return "", "not a whole archive (%s): the file is cut or damaged" % str(e)[:80]
    except Exception as e:                                     # noqa: BLE001
        # a MemoryError has no message: "the reader failed: MemoryError: " said nothing
        why = ("the reader failed: it ran out of memory" if isinstance(e, MemoryError) else
               "the reader failed: %s: %s" % (type(e).__name__, str(e)[:120]))
        try:
            md, note = plain(path, kind, until if until is None else max(until, time.time() + FINISH))
        except Exception:                                      # noqa: BLE001
            return "", why
        return md, _join(why, "the plain text instead" + (": " + note if note else "")) if md.strip() else why
    return "", "the reader failed: it does not know %s" % kind


def _join(*notes):
    return "; ".join(n for n in notes if n)


def _int(s, default=0):
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- Markdown

_WS = re.compile(r"[ \t\n\r\f]+")
_EXTERNAL = re.compile(r"(?i)^(?:https?|ftps?|mailto|news|tel|doi|urn):")
_LIST_LINE = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?: |$)")
# a picture as _pic() writes it: its alt and path hold no "[" (escaped, percent-encoded), so a scan
# from one "![" never runs past the next one (a run of them was quadratic)
_PIC = r"!\[(?:\\.|[^\[\]\\\n]){0,%d}\]\([^()\s\[\]]{0,%d}\)" % (TAG_MAX, TAG_MAX)
# what Markdown would take for its own in a document's text: a backslash before punctuation, `,
# *, [ and ], and _ unless a letter or digit stands on both sides of it (snake_case stays as it is)
_MD_CHARS = re.compile(r"\\(?=[!-/:-@\[-`{-~])|[`*\[\]]|(?<![^\W_])_|_(?![^\W_])")
_MD_UNESC = re.compile(r"\\([!-/:-@\[-`{-~])")


def _esc(s):
    """A document's own text as Markdown text: its ![x](y), [a](b), *b*, `c` and _d_ stay what they
    say (a book's literal ![x](y) became a picture link, a Calc guide's ***** emphasis)."""
    return _MD_CHARS.sub(r"\\\g<0>", s) if s else s


def _unesc(s):
    """_esc() undone: code is what it is, with no escapes."""
    return _MD_UNESC.sub(r"\1", s) if "\\" in s else s


def _space(s):
    return _WS.sub(" ", s)


def _one_line(s):
    """Every run of white space that holds a line end as one space, the ends trimmed. Split, not a
    pattern: `\\s*\\n` scanned back over a long run of spaces with no line end from each of them."""
    if "\n" not in s:
        return s.strip()
    return " ".join(t for t in (p.strip() for p in s.split("\n")) if t)


def _lines(s):
    """Lines trimmed, empty ones at the ends dropped and never two in a row."""
    out = []
    for ln in s.split("\n"):
        ln = ln.strip(" \t") if ln.strip() else ""         # a line of no-break spaces is empty too
        if ln or (out and out[-1]):
            out.append(ln)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def _para(s):
    """Inline text as a paragraph: _lines(), a line Markdown would take for a heading, a list item,
    a quote or a setext underline escaped, a picture kept apart from the words around it."""
    return _escape(_lines(s))


def _escape(t):
    if not t:
        return ""
    t = re.sub(r"(?m)^(#{1,6})(?=[ \t]|$)", r"\\\1", t)
    t = re.sub(r"(?m)^([-+*])(?=[ \t])", r"\\\1", t)
    t = re.sub(r"(?m)^(\d{1,9})([.)])(?=[ \t])", r"\1\\\2", t)
    t = re.sub(r"(?m)^([=-]+)[ \t]*$", r"\\\1", t)
    t = re.sub(r"(?m)^>", r"\\>", t)
    if "![" not in t:
        return t
    t = re.sub(r"(%s)(?=\w)" % _PIC, r"\1 ", t)
    return re.sub(r"(?<=\w)(%s)" % _PIC, r" \1", t)


def _heading(level, text):
    """A heading line, its tabs and runs of spaces one space; emphasis around the whole of it
    dropped (a heading is bold already)."""
    t = re.sub(r"[ \t]+", " ", _marks(_one_line(text)))
    m = re.match(r"^((?:[\w.()-]{1,12} )?)(\*{1,3})(.+)\2$", t)       # after a number (2.1.) too
    if m and m.group(3).strip() and m.group(2) not in m.group(3):
        t = m.group(1) + m.group(3).strip()
    return ("#" * min(max(level, 1), 6) + " " + t) if t else ""


# Emphasis is written as \x0e<mark>\x0f ... \x0e/<mark>\x0f until a text is whole, then _marks()
# makes it Markdown: two runs of one look side by side are one run. Written at once, a word in
# three bold spans came out as **Extras****→****Optionen** (an ODT, 2026-11-20).
_MARK_TOKEN = re.compile("(\x0e/?[*~]+\x0f)")
_MARK = re.compile("\x0e/?([*~]+)\x0f")


def _marks(t):
    """In one pass: a closing mark followed at once by an opening one of the same look cancel out,
    and the ones that meet then too (it was a pass per level of nesting: 5.5 s for 64 MB)."""
    if "\x0e" not in t:
        return t
    out = []
    for i, piece in enumerate(_MARK_TOKEN.split(t)):
        if not i % 2:
            if piece:
                out.append(piece)
        elif piece[1] != "/" and out and out[-1] == "\x0e/" + piece[1:]:
            out.pop()
        else:
            out.append(piece)
    return _MARK.sub(r"\1", "".join(out))


def _emph(s, mark):
    """`mark` around the words of s, the spaces at its ends left outside (CommonMark's rule)."""
    core = s.strip(" \n\t")
    if not core or "![" in core:          # a picture becomes a marker: no mark is left hanging by it
        return s
    i = len(s) - len(s.lstrip(" \n\t"))
    j = len(s.rstrip(" \n\t"))
    return s[:i] + "\x0e" + mark + "\x0f" + core + "\x0e/" + mark + "\x0f" + s[j:]


def _bi(t, bold, italic):
    """Bold and italic as two marks, italic outside: a bold-italic run and an italic one side by
    side share their italic (one mark of three stars left ***drug****. behind)."""
    if bold:
        t = _emph(t, "**")
    return _emph(t, "*") if italic else t


def _code(s):
    s = _MARK.sub("", s).replace("\n", " ")
    if not s.strip():
        return s
    tick = "`" * (max([0] + [len(r) for r in re.findall(r"`+", s)]) + 1)
    pad = " " if s[:1] == "`" or s[-1:] == "`" else ""
    return tick + pad + s + pad + tick


def _fence(code, lang=""):
    code = code.strip("\n")
    if not code.strip():
        return ""
    tick = "`" * max([3] + [len(r) + 1 for r in re.findall(r"`{3,}", code)])
    return "%s%s\n%s\n%s" % (tick, lang, code, tick)


def _link(text, href):
    """[text](href) for an address outside the document; its words alone for one inside it. A link
    that is a picture alone is [![alt](path)](href): the picture pass keeps its address after the
    marker; words and a picture together keep it after them."""
    core = text.strip()
    href = (href or "").strip()
    if not core or not _EXTERNAL.match(href):
        return text
    if re.search(r"[\s()<>\[\]]", href):
        href = "<%s>" % re.sub(r"\s+", "%20", href).replace("<", "%3C").replace(">", "%3E")
    if "![" in core:
        return "[%s](%s)" % (core, href) if re.match(r"^%s$" % _PIC, core) else "%s (%s)" % (text, href)
    i = len(text) - len(text.lstrip())
    j = len(text.rstrip())
    return text[:i] + "[%s](%s)" % (_one_line(core), href) + text[j:]


def _pic(alt, path):
    """![alt](path): the path of a picture inside the archive, percent-encoded so the picture
    pass (pictures.IMG_LINK) takes it whole; doc_pictures() decodes it to find the file."""
    if not path:
        return ""
    alt = _one_line(alt or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    if _EXTERNAL.match(path):
        return "![%s](%s)" % (alt, re.sub(r"[\s()<>\[\]]", lambda m: "%%%02X" % ord(m.group(0)), path))
    return "![%s](%s)" % (alt, urllib.parse.quote(path, safe="/"))


def _indent(text, first, rest):
    lines = text.split("\n")
    return "\n".join([first + lines[0]] + [(rest + ln) if ln.strip() else "" for ln in lines[1:]])


def _quote(blocks):
    body = "\n\n".join(b for b in blocks if b)
    return "\n".join(("> " + ln) if ln.strip() else ">" for ln in body.split("\n"))


def _note_def(label, blocks):
    body = "\n\n".join(b for b in blocks if b)
    return _indent(body, "[^%s]: " % label, "    ") if body else ""


def _is_list(block):
    return bool(_LIST_LINE.match(block or ""))


def _list(items):
    """[(marker, [blocks])] as one Markdown list: tight while no item has two paragraphs."""
    items = [(m, [b for b in blocks if b]) for m, blocks in items]
    items = [(m, blocks) for m, blocks in items if blocks]
    if not items:
        return ""
    tight = all(sum(1 for b in blocks if not _is_list(b)) <= 1 for _m, blocks in items)
    sep = "\n" if tight else "\n\n"
    return sep.join(_indent(sep.join(blocks), m, " " * len(m)) for m, blocks in items)


def md_table(rows, clock=None):
    """Rows of cell texts as a Markdown table, the first row its head; None when fewer than two
    columns have text (such rows read better as paragraphs), "" when nothing is left."""
    out = []
    for r in rows:
        if clock is not None:
            clock.tick()
        line = [_one_line(c or "").replace("|", "\\|") for c in r]
        if any(line):
            out.append(line)
    if not out:
        return ""
    width = max(len(r) for r in out)
    keep = [j for j in range(width) if any(j < len(r) and r[j] for r in out)]
    if len(keep) < 2:
        return None
    lines = ["| " + " | ".join(r[j] if j < len(r) else "" for j in keep) + " |" for r in out]
    return "\n".join([lines[0], "|" + " --- |" * len(keep)] + lines[1:])


def _table_blocks(rows, clock=None):
    md = md_table(rows, clock)
    if md is None:                     # one column: its cells as paragraphs
        return [p for p in (_para(c) for r in rows for c in r) if p]
    return [md] if md else []


def _grid_room(clock, rows, width, cells=CELLS, doc=DOC_CELLS, spent=None):
    """How many more rows of `width` cells a table holding `rows` may take: `cells` for one table,
    what `doc` has left for the document (`spent`: what its other tables took, clock.cells)."""
    width = max(1, width)
    return min(cells // width, (doc - (clock.cells if spent is None else spent)) // width) - rows


# ---------------------------------------------------------------- archives

# A member's name is UTF-8 when its flag says so (bit 11); zipfile reads any other as CP437. Windows'
# own zipper and many Chinese tools write the local code page and no flag: GBK names came out as
# "╦╡├≈.txt", and an EPUB whose OPF names its chapters in UTF-8 lost them. The archive's names are read
# in the code page whose reading of them reads as names (names_codec): UTF-8 (macOS and Linux zippers
# with no flag), a CJK code page, CP437's Latin letters, an OEM code page's Cyrillic or Greek. Measured
# 2026-11-22 on 185 names of seven scripts, alone and an archive of each script's together, under eight
# machines' code pages: 1 458 of 1 536 read right (703 of 960 under the five the rules knew before). What is
# left is what the bytes cannot tell: without its code page on the machine a Korean name of Hangul alone
# decodes as GBK too (its bytes are GB2312's common characters), a Shift-JIS name of kanji alone whose
# CP437 reading is Latin letters stays CP437 (仕様書 is "ÄdùlÅæ"), and on a CJK machine a Latin name
# whose accented letter and the letter after it are one character of the machine's code page is read
# in it (Öl.txt is 冤.txt on a Japanese one).
CJK_CODECS = {936: "gb18030", 950: "big5", 932: "cp932", 949: "cp949"}


def _cjk_ok(t, codec):
    """Is every character of `t` past ASCII one a name in `codec` is made of?"""
    for c in t:
        o = ord(c)
        if (o < 0x80 or 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF
                or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF or 0x2010 <= o <= 0x2027 or o in (0xB7, 0xD7)
                or (codec == "cp932" and 0x3040 <= o <= 0x30FF)
                or (codec == "cp949" and (0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F))
                or (codec == "big5" and 0x3100 <= o <= 0x312F)):
            continue
        return False
    return True


def _gb2312(t):
    """Is every character of `t` past ASCII one of GB2312's (GBK's rows A1-F7): the ones names are made of,
    where a Japanese or Big5 name read as GBK takes the rare ones of its extension."""
    for c in t:
        if ord(c) >= 0x80:
            try:
                b = c.encode("gbk")
            except UnicodeEncodeError:
                return False
            if len(b) != 2 or not (0xA1 <= b[0] <= 0xF7 and 0xA1 <= b[1] <= 0xFE):
                return False
    return True


def machine_cjk():
    """The CJK code page of this machine, or "": Windows' ANSI code page (the one its zipper writes),
    else the locale's language."""
    if os.name == "nt":
        try:
            import ctypes
            return CJK_CODECS.get(ctypes.windll.kernel32.GetACP(), "")
        except Exception:                                      # noqa: BLE001
            return ""
    lang = (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE") or os.environ.get("LANG") or "").lower()
    if lang.startswith(("zh_tw", "zh_hk", "zh_mo")):
        return "big5"
    return {"zh": "gb18030", "ja": "cp932", "ko": "cp949"}.get(lang[:2], "")


def _intl():
    """intl, of this folder and of the standard library alone: this process, started with -I, does not have the
    folder on its path by itself (a bare `import intl` failed every EPUB whose parts declare their encoding).
    None where it cannot be imported."""
    try:
        import intl
    except ImportError:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.append(here)
        try:
            import intl
        except ImportError:
            return None
    return intl


def _common_share(text, codec):
    """(the share of `text`'s non-ASCII characters that are the common ones of `codec`'s script, how many there
    are): intl.native_share, the measure a page's encoding is guessed by. None where intl cannot be imported."""
    intl = _intl()
    return None if intl is None else intl.native_share(text, {"big5": "big5hkscs"}.get(codec, codec))


# Windows' own zipper writes a name with no UTF-8 flag in the machine's OEM code page: CP437 on an American
# machine, CP850 on a Western European one, CP866 on a Russian one, CP737 on a Greek one (a CJK machine's is its
# ANSI code page, machine_cjk()). A one-byte code page's reading is a name's when every character past ASCII
# is a letter of its script, and a Cyrillic or Greek word is lower case, Capitalised or UPPER, its letters
# never mixed with ASCII ones (a Shift-JIS name read as CP866 is "ГfБ[Г^"), and has a vowel when it has
# three letters or more. A CJK reading is a name's when every character past ASCII is one of its script's
# own - an ideograph, kana for Shift-JIS, Hangul for Korean, bopomofo for Big5, the script's punctuation;
# never a half-width kana or a fullwidth letter, which the bytes of another script make - and when no run of
# them stands between two ASCII letters, and none of one character is glued to one: a Latin name read as
# Shift-JIS is "M〕ler", "Gr批e", "始derungen", its accented letter and the letter after it one character.
OEM_CODECS = dict((n, "cp%d" % n) for n in (437, 737, 775, 850, 852, 855, 857, 858, 860, 861, 862, 863, 865, 866, 869))
_OEM_BY_LANG = {"ru": "cp866", "uk": "cp866", "be": "cp866", "bg": "cp866", "kk": "cp866", "el": "cp737",
                "pl": "cp852", "cs": "cp852", "sk": "cp852", "hu": "cp852", "sl": "cp852", "hr": "cp852",
                "ro": "cp852", "tr": "cp857", "he": "cp862"}
_OEM_SCRIPT = {"cp866": "CYRILLIC", "cp855": "CYRILLIC", "cp737": "GREEK", "cp869": "GREEK", "cp862": "HEBREW"}
_VOWELS = {"CYRILLIC": "аеёиоуыэюяіїєў", "GREEK": "αεηιουωάέήίόύώϊϋΐΰ"}
_WORDS = re.compile(r"[^\W\d_]+")
_HIGH_RUN = re.compile(r"[^\x00-\x7f]+")
_TRAIL_BACKSLASH = re.compile(rb"[\x81-\xfc]\x5c")       # a double-byte character whose second byte is "\"


def machine_oem():
    """The OEM code page of this machine, or "": Windows' (GetOEMCP), else the one of the locale's language
    (Russian CP866, Greek CP737...; a Western European or an English one is "": CP437 and CP850 read the
    common letters alike). A CJK machine's is its ANSI code page: machine_cjk()."""
    if os.name == "nt":
        try:
            import ctypes
            return OEM_CODECS.get(ctypes.windll.kernel32.GetOEMCP(), "")
        except Exception:                                      # noqa: BLE001
            return ""
    lang = (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE") or os.environ.get("LANG") or "").lower()
    return _OEM_BY_LANG.get(lang[:2], "")


def _one_byte(raws, codec):
    """Do the names read in this one-byte code page as names of its script (see above)?"""
    import unicodedata
    script = _OEM_SCRIPT.get(codec, "LATIN")
    for r in raws:
        t = r.decode(codec, "replace")
        for c in t:
            if ord(c) >= 0x80 and not unicodedata.name(c, "").startswith(script + " "):
                return False
        if script == "LATIN":
            continue
        for w in _WORDS.findall(t):
            if not any(ord(c) >= 0x80 for c in w):
                continue
            if any(ord(c) < 0x80 for c in w) or not (w.islower() or w.isupper() or w[1:].islower()):
                return False
            vowels = sum(1 for c in w.lower() if c in _VOWELS.get(script, ""))
            if script in _VOWELS and len(w) >= 3 and (not vowels or len(w) >= 4 and vowels * 4 < len(w)):
                return False                       # a word has its vowels (Russian ones are four in ten)
            if re.search(r"(.)\1\1", w.lower()) or script == "GREEK" and not _greek_word(w):
                return False
    return True


def _cjk_name(t, codec):
    """Does this CJK reading read as names (see above)? A Korean name is Hangul: the bytes of another
    script read as Korean make Hanja among its syllables."""
    own = False
    for c in t:
        o = ord(c)
        if o < 0x80:
            continue
        if (codec != "cp949" and (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF)) or \
                (codec == "cp932" and 0x3041 <= o <= 0x30FF) or (codec == "cp949" and 0xAC00 <= o <= 0xD7A3) or \
                (codec == "big5" and 0x3105 <= o <= 0x312F):
            own = True
        elif not (0x3000 <= o <= 0x303F or 0xFF01 <= o <= 0xFF20 or 0xFF3B <= o <= 0xFF40 or 0xFF5B <= o <= 0xFF65
                  or 0x2010 <= o <= 0x2027 or o in (0xB7, 0xD7)):
            return False
    if not own:
        return False
    for m in _HIGH_RUN.finditer(t):
        a, b = m.start(), m.end()
        # an ASCII letter glued to the run, and whether it is a letter alone (a word of one letter)
        left = a > 0 and t[a - 1].isalpha()
        right = b < len(t) and t[b].isalpha()
        lone = (left and not (a > 1 and t[a - 2].isalpha())) or (right and not (b + 1 < len(t) and t[b + 1].isalpha()))
        if (left and right) or ((left or right) and (b - a == 1 or lone)):
            return False
    return True


def _greek_word(w):
    """A Greek word as Greek writes one: a final sigma at its end alone, one accent at most."""
    if "ς" in w[:-1] or w.endswith("σ"):
        return False
    return sum(1 for c in w if c in "άέήίόύώΐΰΆΈΉΊΌΎΏ") <= 1


def _utf8_names(raws):
    """The UTF-8 reading of the names when every one decodes and they read as names of one script - a
    Latin or Cyrillic name a macOS zipper wrote with no flag, a Chinese one - else None: GBK's 图片
    decodes as UTF-8 too, to a Greek and a Latin letter side by side ("ͼƬ"), and 目录 to "Ŀ¼"."""
    try:
        texts = [r.decode("utf-8") for r in raws]
    except UnicodeDecodeError:
        return None
    import unicodedata
    scripts = set()
    for c in "".join(texts):
        o = ord(c)
        if o < 0x80 or c.isspace():
            continue
        if 0x3000 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFFEF:
            scripts.add("CJK")
        elif unicodedata.category(c).startswith("L"):
            scripts.add(unicodedata.name(c, "").split(" ")[0])
        elif not unicodedata.category(c).startswith("P"):
            return None                                    # a number, a symbol, a control, a mark: no name's
    return texts if len(scripts) <= 1 else None


def names_codec(raws, prior=None, oem=None):
    """The code page of an archive's names given the raw bytes of those with no UTF-8 flag: "utf-8", a
    CJK code page, a one-byte one ("cp866"), or "" - they are CP437, as zipfile reads them. `prior`: the
    machine's CJK code page (machine_cjk() when None); `oem`: its OEM code page (machine_oem() when None).
    In order: UTF-8 that reads as names; Shift-JIS that does (its kana, or kanji with no other CJK code page
    on the machine) - a Shift-JIS name is CP437's Latin letters to a rule about them (データ.csv was
    "âfü[â^.csv", 表.txt "ò\\.txt", on a Japanese machine too); the CJK reading that is plainly the common
    characters of its script; the machine's CJK code page, its OEM one; CP437's Latin letters; CP866's
    Cyrillic, CP737's Greek (they were read as Korean); then which CJK code page the characters point to."""
    raws = [r for r in raws if any(b > 0x7F for b in bytearray(r))]
    if not raws:
        return ""
    if _utf8_names(raws) is not None:
        return "utf-8"
    clean, named = {}, {}
    for codec in ("gb18030", "big5", "cp932", "cp949"):
        try:
            texts = [r.decode(codec) for r in raws]
        except UnicodeDecodeError:
            continue
        if all(_cjk_ok(t, codec) for t in texts):
            clean[codec] = "".join(texts)
            named[codec] = all(_cjk_name(t, codec) for t in texts)
    prior = machine_cjk() if prior is None else prior
    if named.get("cp932") and any(0x3041 <= ord(c) <= 0x30FF for c in clean["cp932"]):
        # the bytes of a Chinese or Korean name make half-width kana when read as Shift-JIS, and a Latin
        # name's make one character of an accented letter and the next: a reading of kana and kanji is Japanese
        return "cp932"
    shares = dict((c, _common_share(t, c)) for c, t in clean.items())
    known = all(v is not None for v in shares.values())
    if len(clean) > 1 and known:
        # one reading that is plainly the common characters of its script, the others rare ones, wins - over the
        # machine's code page too (GBK names read as Big5 on a Taiwanese machine: "佽隴.txt"; Korean ones as GBK:
        # "焊绊辑.txt"); a close call goes on to the machine's code page and the rules below
        ranked = sorted(clean, key=lambda c: -shares[c][0])
        best, second = shares[ranked[0]], shares[ranked[1]]
        if best[1] >= 2 and best[0] - second[0] >= 0.4 and named.get(ranked[0]):
            return ranked[0]
    latin = _one_byte(raws, "cp437")
    if named.get("cp932") and (prior == "cp932" or not named.get(prior) and (
            not latin or any(_TRAIL_BACKSLASH.search(r) for r in raws))):
        # kanji alone: Japanese on a Japanese machine; elsewhere when the CP437 reading is no Latin name, or
        # puts a backslash right after an accented letter (表's second byte is one: "ò\\.txt")
        return "cp932"
    oem = machine_oem() if oem is None else oem
    one = ([oem] if _OEM_SCRIPT.get(oem) else []) + [c for c in ("cp866", "cp737") if c != oem]
    common = known and any(named.get(c) and shares[c][0] >= 0.5 for c in clean)
    for codec in one if not common else ():
        if _one_byte(raws, codec):
            return codec                                   # Cyrillic, Greek: one script's letters, as its words are
    if named.get(prior):
        return prior
    if oem in OEM_CODECS.values() and oem != "cp437" and _one_byte(raws, oem):
        return oem                                         # a Latin OEM code page (CP850, CP852...)
    if latin:
        return ""
    if prior in clean:
        return prior
    if "cp932" in clean and any(0x3040 <= ord(c) <= 0x30FF for c in clean["cp932"]):
        return "cp932"
    if "gb18030" in clean and _gb2312(clean["gb18030"]):
        return "gb18030"
    if "big5" in clean:
        return "big5"
    if "cp949" in clean and any(0xAC00 <= ord(c) <= 0xD7A3 for c in clean["cp949"]):
        return "cp949"
    return next((c for c in ("cp932", "gb18030", "cp949") if c in clean), "")


def zip_name(raw, codec):
    """A member's name from its raw bytes read in `codec`, as zipfile makes a name: cut at a NUL, and a
    backslash a "/" (a name decoded here kept them, so a folder `文件夹\\` was no folder; zipfile on
    Windows turns them, and on other systems the same name now reads the same)."""
    return bytes(raw).split(b"\x00", 1)[0].decode(codec or "cp437", "replace").replace("\\", "/")


def fix_zip_names(z, prior=None, oem=None):
    """The names of zipfile `z`'s members with no UTF-8 flag read in the code page they were written
    in (names_codec; `prior` and `oem` are its), cut at a NUL and with "/" for a backslash (zip_name):
    each ZipInfo's `filename`, and the name `z` finds it by, become that reading; its `orig_filename`,
    which zipfile checks against the member's own header, stays. Returns the code page, "" when the
    names are CP437, as zipfile read them."""
    raws = {}
    for i in z.infolist():
        if not i.flag_bits & 0x800:
            try:
                raws[id(i)] = i.orig_filename.encode("cp437")
            except UnicodeEncodeError:
                continue
    codec = names_codec(list(raws.values()), prior, oem)
    taken = set(z.NameToInfo)
    for i in z.infolist():
        raw = raws.get(id(i))
        if codec and raw is not None and any(b > 0x7F for b in bytearray(raw)):
            name = zip_name(raw, codec)
        else:
            name = i.filename.replace("\\", "/")              # zipfile cut it at a NUL itself
        if name == i.filename or name in taken:
            continue
        if z.NameToInfo.get(i.filename) is i:
            del z.NameToInfo[i.filename]
        i.filename = name
        z.NameToInfo[name] = i
        taken.add(name)
    return codec


class _Zip(object):
    """An archive's parts, each read up to its limit and all of them up to TOTAL_BYTES; what was
    cut or could not be read is named in `cut` and `bad`. Its names are read in the code page they
    were written in (fix_zip_names)."""

    def __init__(self, z):
        fix_zip_names(z)
        self.z = z
        self.names = z.namelist()
        self.exact = set(self.names)
        self.lower = {}
        for n in self.names:
            self.lower.setdefault(n.lower(), n)
        self.total, self.cut, self.bad = 0, [], []

    def name(self, n):
        n = (n or "").lstrip("/")
        return n if n in self.exact else self.lower.get(n.lower())   # books made on Windows

    def read(self, name, limit=PART_BYTES):
        real = self.name(name)
        if real is None:
            return None
        cap = min(limit, TOTAL_BYTES - self.total)
        if cap <= 0:
            self.cut.append(real)
            return None
        try:
            with self.z.open(real) as fh:
                data = fh.read(cap + 1)
        except Exception:                                      # noqa: BLE001  (cut, encrypted, bad CRC)
            self.bad.append(real)
            return None
        if len(data) > cap:
            self.cut.append(real)
            data = data[:cap]
        self.total += len(data)
        return data

    def chunks(self, name, size=1 << 20):
        """The part `name` as it unpacks, `size` bytes at a time, none of it held here (TOTAL_BYTES is
        not spent on it): its reader says where it stopped (_feed). A part that stops unpacking is
        named in `bad`, after what came before it. Nothing when the archive has no such part."""
        real = self.name(name)
        if real is None:
            return
        try:
            with self.z.open(real) as fh:
                while True:
                    data = fh.read(size)
                    if not data:
                        return
                    yield data
        except GeneratorExit:
            raise
        except Exception:                                      # noqa: BLE001  (cut, encrypted, bad CRC)
            self.bad.append(real)

    def note(self):
        out = []
        if self.cut:
            out.append("%d part(s) over the size limit read in part or not at all (%s)"
                       % (len(self.cut), ", ".join(self.cut[:3])))
        if self.bad:
            out.append("%d part(s) could not be unpacked (%s)" % (len(self.bad), ", ".join(self.bad[:3])))
        return "; ".join(out)


# codecs a part may not name for itself: not a character set, and punycode's decoder is quadratic
_NOT_CHARSETS = frozenset(("idna", "punycode", "unicode_escape", "raw_unicode_escape", "undefined"))


def _charset(name):
    try:
        info = codecs.lookup(name)
    except LookupError:
        return None
    if not getattr(info, "_is_text_encoding", True) or info.name in _NOT_CHARSETS:
        return None
    return info.name


def _decode(data):
    """An XML or HTML part as text: its BOM, its XML declaration, its meta charset, else UTF-8. A declared label is
    read as a browser reads it (intl.codec_of: gb2312 as gb18030, big5 as Big5-HKSCS ...), a character it does not
    hold replaced, not the whole part: one character outside GB2312 (镕, 〇) made a part U+FFFD throughout."""
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", "replace")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    head = data[:2048]
    m = re.match(rb"""\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._:-]+)""", head) or \
        re.search(rb"""(?i)<meta\b[^>]*?charset\s*=\s*["']?([A-Za-z0-9._:-]+)""", head)
    label = m.group(1).decode("ascii") if m else ""
    if label:
        intl = _intl()
        enc = (_charset(intl.codec_of(label)) if intl else None) or _charset(label)
        if enc and enc not in ("utf_8", "utf-8"):
            try:
                return data.decode(enc)
            except (LookupError, UnicodeError, ValueError):
                try:
                    data.decode("utf-8")                     # a label that lies: the part is UTF-8
                except UnicodeDecodeError:
                    return data.decode(enc, "replace")
    try:
        return data.decode("utf-8")
    except UnicodeError:
        return data.decode("utf-8", "replace")


_ATTR = re.compile(r"""(?<![\w:.-])([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _attrs(tag):
    return {k.lower(): html.unescape(a or b) for k, a, b in _ATTR.findall(tag)}


class _Stop(Exception):
    pass


_CUT = "{urn:read-page}cut"            # an element of ours where a part's XML broke: no reader reads it


def _doctype(data):
    """Does an XML part declare a DOCTYPE? expat reads its prolog alone, up to the first element, so
    a BOM, UTF-16, an encoding or a line end before it change nothing (a newline after
    <?xml ...?> let one through, and expat's own limit was all that stopped the bomb)."""
    p = expat.ParserCreate()
    seen = []

    def doctype(*_a):
        seen.append(1)
        raise _Stop()

    def element(*_a):
        raise _Stop()
    p.StartDoctypeDeclHandler = doctype
    p.EntityDeclHandler = doctype
    p.StartElementHandler = element
    try:
        for i in range(0, len(data), 1 << 16):
            p.Parse(data[i:i + (1 << 16)], False)
        p.Parse(b"", True)
    except _Stop:
        pass
    except expat.ExpatError:
        pass                                                   # XML that breaks: ElementTree says how
    return bool(seen)


def _xml(data, clock):
    """ElementTree of an XML part: (root, why). XML that breaks somewhere gives what came before
    that point and says so; a DOCTYPE is refused - no OpenDocument file has one, and its entities
    are the way to a billion laughs on a Python whose expat has no limit of its own."""
    if not data:
        return None, "it is empty"
    if _doctype(data):
        return None, "it declares a DOCTYPE"
    tb = ET.TreeBuilder()
    parser = ET.XMLParser(target=tb)
    try:
        for i in range(0, len(data), 1 << 20):
            parser.feed(data[i:i + (1 << 20)])
            if clock.late():
                raise Late()
        return parser.close(), ""
    except ET.ParseError as e:
        why = "its XML breaks (%s): what comes after that point is missing" % str(e)[:60]
    try:
        tb.start(_CUT, {})              # the text of an element still open goes to it (a part cut at
        tb.end(_CUT)                    # its size limit kept no word of its last paragraph)
        return tb.close(), why
    except Exception:                                          # noqa: BLE001
        return None, why


# ---------------------------------------------------------------- EPUB

_VOID = frozenset(("area", "base", "basefont", "br", "col", "embed", "frame", "hr", "img", "input", "isindex",
                   "keygen", "link", "meta", "param", "source", "track", "wbr", "image"))
_SKIP = frozenset(("head", "script", "style", "template", "title", "iframe", "video", "audio", "canvas", "map",
                   "select", "textarea", "input", "button", "datalist", "option", "optgroup", "frameset",
                   "noframes", "case"))
_BLOCK = frozenset(("address", "article", "aside", "blockquote", "body", "caption", "center", "dd", "details",
                    "dialog", "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1",
                    "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "html", "legend", "li", "listing",
                    "main", "menu", "nav", "ol", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot",
                    "th", "thead", "tr", "ul", "xmp", "plaintext", "switch", "default", "noscript", "colgroup",
                    "col"))
_CLOSES_P = frozenset(("address", "article", "aside", "blockquote", "details", "dialog", "dir", "div", "dl",
                       "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
                       "header", "hgroup", "hr", "main", "menu", "nav", "ol", "p", "pre", "section", "table", "ul"))
_P_SCOPE = ("table", "td", "th", "caption", "object", "template", "button", "svg", "math")


class _El(object):
    __slots__ = ("tag", "attrs", "kids")

    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.kids = tag, attrs, []


class _Full(Exception):
    """A part holds more elements than NODES."""


# Elements html.parser reads as raw text, to their end tag: script and style on every Python, and
# since 2025's fixes (3.9.25, 3.12.14, 3.13.18) xmp, iframe, noembed, noframes, title and textarea
_RAW_START = re.compile(r"(?i)<(script|style|title|textarea|iframe|noembed|noframes|xmp)(?=[\s/>])")
_RAW_END = dict((n, re.compile(r"(?i)</%s(?=[\s/>])" % n))
                for n in ("script", "style", "title", "textarea", "iframe", "noembed", "noframes", "xmp"))


def _markup(t):
    """A part's markup as html.parser reads it in linear time, the same on every Python. html.parser
    ran from every unclosed construct to the end of the part - at the end of input on Pythons
    without 2025's fix (CVE-2025-6069: 12 KB of "<a " took 4.8 s on 3.13.2) and again at each 64 KB
    it is fed, on all of them (one 4 MB tag: 2.5 s on 3.13.18, 19.7 s on 3.9.25). So:
    - a comment or a CDATA section goes (none of their words is read), to the end of the part when
      it never ends, as a browser has it;
    - a raw-text element (script, style, title, textarea, iframe, noembed, noframes) keeps its tags
      and loses its contents, none of which is read either; one that never ends, the rest of the
      part; `<script/>` is closed at once (the 2025 parsers would open it);
    - an xmp is a pre with its text escaped (raw text on the 2025 parsers, markup before them);
    - a "<" that no ">" closes within TAG_MAX characters is text."""
    if "<" not in t:
        return t
    out, pos, start, gt, n = [], 0, 0, -1, len(t)
    while True:
        i = t.find("<", start)
        if i < 0:
            break
        if t.startswith("<!--", i) or t.startswith("<![CDATA[", i):
            out.append(t[pos:i])
            j = t.find("-->" if t[i + 2] == "-" else "]]>", i + 4)
            pos = start = n if j < 0 else j + 3
            continue
        if gt < i:
            gt = t.find(">", i)
            if gt < 0:
                gt = n + TAG_MAX                # no ">" after here: every "<" left is text
        if gt - i > TAG_MAX:
            out.append(t[pos:i])
            out.append("&lt;")
            pos = start = i + 1
            continue
        m = _RAW_START.match(t, i)
        if m:
            name = m.group(1).lower()
            if t[gt - 1] == "/":
                out.append(t[pos:gt - 1] + "></%s>" % name)
                pos = start = gt + 1
                continue
            e = _RAW_END[name].search(t, gt + 1)
            end = e.start() if e else n
            if name == "xmp":
                out.append(t[pos:i] + "<pre>" + t[gt + 1:end].replace("&", "&amp;").replace("<", "&lt;") + "</pre>")
                k = t.find(">", end)
                pos = start = n if e is None or k < 0 else k + 1
            else:
                out.append(t[pos:gt + 1])
                pos = start = end
            continue
        start = i + 1
    out.append(t[pos:])
    return "".join(out)


class _Tree(HTMLParser):
    """XHTML (or tag soup) as a tree of _El; the HTML rules that close a <p> or an <li> nobody
    closed, so a sloppy EPUB 2 book still nests the way a browser would show it. Where each tag is
    open is kept (`at`: its stack positions), so a rule or an end tag finds its element in one look
    (a <p> left open under a <button> made each tag that closes a <p> walk the whole stack);
    text is gathered and joined once (300 000 stray end tags copied it at each); OPEN elements at
    most are open, the clock is read every 4096 elements, and the tree stops at NODES."""

    def __init__(self, clock):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = _El("#root", {})
        self.stack, self.at, self.clock, self.nodes, self.buf = [self.root], {}, clock, 0, []

    def flush(self):
        if self.buf:
            self.stack[-1].kids.append("".join(self.buf))
            self.buf = []

    def _pop(self, k):
        self.flush()
        for el in self.stack[k:]:
            self.at[el.tag].pop()
        del self.stack[k:]

    def _top(self, names):
        top = -1
        for n in names:
            s = self.at.get(n)
            if s and s[-1] > top:
                top = s[-1]
        return top

    def _close(self, names, stop):
        k = self._top(names)
        if k > 0 and self._top(stop) < k:
            self._pop(k)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def _start(self, tag, attrs, empty):
        self.nodes += 1
        if not self.nodes & 4095:
            if self.clock.late():
                raise Late()
            if self.nodes > NODES:
                raise _Full()
        tag = tag.rsplit(":", 1)[-1]
        if tag in _CLOSES_P:
            self._close(("p",), _P_SCOPE)
        if tag == "li":
            self._close(("li",), ("ul", "ol", "menu", "dir", "table"))
        elif tag in ("dt", "dd"):
            self._close(("dt", "dd"), ("dl", "table"))
        elif tag == "tr":
            self._close(("tr",), ("table",))
        elif tag in ("td", "th"):
            self._close(("td", "th"), ("tr", "table"))
        elif tag in ("thead", "tbody", "tfoot"):
            self._close(("thead", "tbody", "tfoot"), ("table",))
        self.flush()
        el = _El(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].kids.append(el)
        if not empty and tag not in _VOID and len(self.stack) <= OPEN:
            self.at.setdefault(tag, []).append(len(self.stack))
            self.stack.append(el)

    def handle_endtag(self, tag):
        s = self.at.get(tag.rsplit(":", 1)[-1])
        if s:                                          # else nothing of the kind is open: a stray end tag
            self._pop(s[-1])

    def handle_data(self, data):
        self.buf.append(data)

    def parse_html_declaration(self, i):
        try:
            return HTMLParser.parse_html_declaration(self, i)
        except (AssertionError, NotImplementedError):
            # a declaration html.parser has no rule for (<![bogus[ before 2025's fix: AssertionError on
            # 3.13.2, NotImplementedError on 3.8, and the book was lost): a bogus comment, to its ">"
            j = self.rawdata.find(">", i + 2)
            return j + 1 if j >= 0 else -1


def _html_tree(text, clock):
    """(root, how): "whole", "full" when the part had more than NODES elements and the tree holds
    the ones before, "broke" when its markup broke the parser and the tree holds what came before."""
    t = _Tree(clock)
    how = "whole"
    try:
        for i in range(0, len(text), 1 << 16):
            t.feed(text[i:i + (1 << 16)])
            if clock.late():
                raise Late()
        t.close()
    except _Full:
        how = "full"
    except (Late, MemoryError):
        raise
    except Exception:                                          # noqa: BLE001
        how = "broke"
    t.flush()
    return t.root, how


def _text(el):
    """Every word under el, <br> as a line end, without recursion (a nesting bomb is flat here)."""
    out, stack = [], [el]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            out.append(x)
        elif x.tag == "br":
            out.append("\n")
        elif x.tag not in _SKIP:
            stack.extend(reversed(x.kids))
    return "".join(out)


def _find(el, tag):
    stack = [el]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            continue
        if x.tag == tag:
            return x
        stack.extend(reversed(x.kids))
    return None


def _target(doc, href):
    """(document, id) a link inside the book points at, or None."""
    href = (href or "").strip()
    if not href or _EXTERNAL.match(href) or "#" not in href:
        return None
    path, _, frag = href.partition("#")
    if not frag:
        return None
    if path:
        doc = posixpath.normpath(posixpath.join(posixpath.dirname(doc), urllib.parse.unquote(path)))
    return doc, urllib.parse.unquote(frag)


# tags as _markup() leaves them: TAG_MAX characters at most, no "<" inside (`[^>]*` ran to the
# end of the part from every <a, <item or <rootfile that never closed)
_A_TAG = re.compile(r"(?i)<a\b[^<>]{0,%d}>" % TAG_MAX)
_NOTE_KIND = re.compile(r"""(?i)\b(?:epub:type|role)\s*=\s*["'][^"'<>]*noteref""")
_HREF = re.compile(r"""(?is)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_ROOTFILE = re.compile(r"(?i)<rootfile\b[^<>]{0,%d}>" % TAG_MAX)
_OPF_ITEM = re.compile(r"(?i)<(?:\w{1,32}:)?item\b[^<>]{0,%d}>" % TAG_MAX)
_OPF_ITEMREF = re.compile(r"(?i)<(?:\w{1,32}:)?itemref\b[^<>]{0,%d}>" % TAG_MAX)


class _Book(object):
    """What the parts of one book share: the notes it calls by epub:type or role "noteref", each
    with its number in the order the book first calls it; which of them got their text; what the
    book showed at each call (put back where a note's text was never found)."""

    def __init__(self):
        self.notes, self.defined, self.refs = {}, set(), {}

    def scan(self, doc, text, clock):
        for m in _A_TAG.finditer(text):
            clock.tick()
            tag = m.group(0)
            if "noteref" not in tag.lower() or not _NOTE_KIND.search(tag):
                continue
            h = _HREF.search(tag)
            key = _target(doc, html.unescape(h.group(1) or h.group(2))) if h else None
            if key and key not in self.notes:
                self.notes[key] = str(len(self.notes) + 1)


class _Html(object):
    """One XHTML part of a book as Markdown blocks."""

    def __init__(self, doc, book, clock):
        self.doc, self.dir, self.book, self.clock = doc, posixpath.dirname(doc), book, clock
        self.skip = set()                 # anchors that were a note's own number

    def note_label(self, el):
        i = el.attrs.get("id")
        return self.book.notes.get((self.doc, i)) if i else None

    def anchor_label(self, el):
        """A note whose call points at an anchor that opens a paragraph (<p><a id="n1">1</a> The
        note.</p>): the paragraph is the note, and the anchor its number."""
        k = el
        for _depth in range(3):
            first = next((x for x in k.kids if not (isinstance(x, str) and not x.strip())), None)
            if first is None or isinstance(first, str) or first.tag in _BLOCK:
                return None, None                  # an anchor is inline; a list's item is its own note
            lab = self.note_label(first)
            if lab:
                return lab, first
            k = first
        return None, None

    def noteref(self, el):
        kind = (el.attrs.get("epub:type", "") + " " + el.attrs.get("role", "")).lower()
        if "noteref" not in kind:
            return None
        return self.book.notes.get(_target(self.doc, el.attrs.get("href", "")))

    def flat(self, el):
        """What is past DEPTH: its words as one paragraph."""
        t = _para(_esc(_space(_text(el))))
        return [t] if t else []

    # -- blocks
    def blocks(self, el, depth=0):
        if depth > DEPTH:
            return self.flat(el)
        out, run = [], []

        def flush():
            if run:
                p = _para("".join(run))
                del run[:]
                if p:
                    out.append(p)
        for k in el.kids:
            if isinstance(k, str):
                run.append(_esc(_space(k)))
                continue
            self.clock.tick()
            if k.tag in _SKIP or "hidden" in k.attrs:
                continue
            if k.tag in _BLOCK or self.note_label(k):
                flush()
                out.extend(self.block(k, depth + 1))
            else:
                run.append(self.inline_el(k, depth + 1))
        flush()
        return out

    def block(self, el, depth):
        t = el.tag
        lab, anchor = self.note_label(el), None
        if not lab and t in ("p", "li", "div", "aside", "dd", "section", "blockquote"):
            lab, anchor = self.anchor_label(el)
        if lab and lab not in self.book.defined:
            self.book.defined.add(lab)
            if anchor is not None:
                self.skip.add(id(anchor))
            d = _note_def(lab, self.blocks(el, depth))
            return [d] if d else []
        if t in ("h1", "h2", "h3", "h4", "h5", "h6"):
            h = _heading(int(t[1]), self.inline(el, depth))
            return [h] if h else []
        if t == "p":
            if any(not isinstance(k, str) and k.tag in _BLOCK for k in el.kids):
                return self.blocks(el, depth)
            p = _para(self.inline(el, depth))
            return [p] if p else []
        if t in ("pre", "listing", "xmp", "plaintext"):
            f = _fence(_text(el), self.lang(el))
            return [f] if f else []
        if t == "blockquote":
            inner = self.blocks(el, depth)
            return [_quote(inner)] if inner else []
        if t in ("ul", "ol", "menu", "dir"):
            return self.list(el, depth)
        if t == "dl":
            return self.dl(el, depth)
        if t == "table":
            return self.table(el, depth)
        if t == "hr":
            return ["* * *"]
        if t == "nav" and re.search(r"toc|landmarks|page-?list",
                                    (el.attrs.get("epub:type", "") + " " + el.attrs.get("role", "")).lower()):
            return []                          # a table of contents in a page: the nav document again
        if t == "li":
            items = _list([("- ", self.blocks(el, depth))])
            return [items] if items else []
        if t == "switch":
            for k in el.kids:
                if not isinstance(k, str) and k.tag == "default":
                    return self.blocks(k, depth)
            return []
        if t == "dt":
            s = _one_line(self.inline(el, depth))
            return [_emph(s, "**")] if s else []
        return self.blocks(el, depth)

    def lang(self, el):
        for x in [el] + [k for k in el.kids if not isinstance(k, str) and k.tag == "code"][:1]:
            lang = x.attrs.get("data-lang") or ""
            m = re.search(r"(?:^|\s)(?:language|lang)-([\w+#.-]+)", x.attrs.get("class", ""))
            if lang or m:
                return re.sub(r"[^\w+#.-]", "", lang or m.group(1))
        return ""

    def list(self, el, depth):
        if depth > DEPTH:
            return self.flat(el)
        ordered = el.tag == "ol"
        n = _int(el.attrs.get("start"), 1)
        items, out = [], []

        def close():
            if items:
                out.append(_list(items))
                del items[:]
        for k in el.kids:
            if isinstance(k, str):
                s = _para(_esc(_space(k)))
                if s:
                    if items:
                        items[-1][1].append(s)
                    else:
                        out.append(s)
                continue
            self.clock.tick()
            if k.tag in _SKIP or "hidden" in k.attrs:
                continue
            lab = self.note_label(k) or (self.anchor_label(k)[0] if k.tag == "li" else None)
            if lab and lab not in self.book.defined:
                close()                        # a note kept in a list (endnotes): a definition of its own
                out.extend(self.block(k, depth + 1))
                continue
            if k.tag in ("ul", "ol", "menu", "dir"):
                sub = self.list(k, depth + 1)
                if items:
                    items[-1][1].extend(sub)
                else:
                    out.extend(sub)
                continue
            if k.tag != "li":
                blocks = self.block(k, depth + 1) if k.tag in _BLOCK else \
                    [p for p in [_para(self.inline_el(k, depth + 1))] if p]
                if items:
                    items[-1][1].extend(blocks)
                else:
                    out.extend(blocks)
                continue
            if "value" in k.attrs:
                n = _int(k.attrs["value"], n)
            blocks = self.blocks(k, depth + 1)
            if not blocks:
                continue
            if _is_list(blocks[0]) and items:          # an item that is only a deeper list
                items[-1][1].extend(blocks)
                continue
            items.append(("%d. " % n if ordered else "- ", blocks))
            n += 1
        close()
        return [o for o in out if o]

    def dl(self, el, depth):
        out = []
        for k in el.kids:
            if isinstance(k, str):
                s = _para(_esc(_space(k)))
                if s:
                    out.append(s)
            elif k.tag in _SKIP:
                continue
            elif k.tag == "dd":
                out.extend(self.blocks(k, depth + 1))
            elif k.tag in _BLOCK:
                out.extend(self.block(k, depth + 1))
            else:
                s = _para(self.inline_el(k, depth + 1))
                if s:
                    out.append(s)
        return out

    def table(self, el, depth):
        """A table's grid: a merged cell leaves its other places empty. The grid holds CELLS at most
        (DOC_CELLS with the document's other tables), a row WIDTH columns, a span 64 columns and
        the table's own rows: past them the table is cut, and the note says so (spans of
        512 x 64 per cell, multiplied across 300 cells, took 1.4 GB from 1 KB)."""
        caption, rows = [], []

        def walk(x, d):
            for k in x.kids:
                if isinstance(k, str) or k.tag in _SKIP:
                    continue
                if k.tag == "caption":
                    c = _para(self.inline(k, depth + 1))
                    if c:
                        caption.append(c)
                elif k.tag == "tr":
                    rows.append(k)
                elif k.tag not in ("colgroup", "col", "table", "td", "th") and d < DEPTH:
                    walk(k, d + 1)             # thead, tbody, tfoot, or a form around the rows
        walk(el, 0)
        if not rows:                           # no row at all: what it holds, as blocks
            return caption + self.blocks(el, depth)
        n = min(len(rows), ROWS)
        grid, cells, busy, width = [], [], [], 0       # busy[col]: the last row a span above covers
        for r, tr in enumerate(rows[:n]):
            self.clock.tick()
            line, col = [], 0
            for c in tr.kids:
                if isinstance(c, str) or c.tag not in ("td", "th"):
                    continue
                cells.append(c)
                while col < len(busy) and busy[col] >= r:
                    line.append("")
                    col += 1
                text = _one_line(self.inline(c, depth + 1))
                if col >= WIDTH:
                    if text:
                        line[-1] = (line[-1] + " " + text).strip()
                    continue
                cs = min(max(_int(c.attrs.get("colspan"), 1), 1), 64, WIDTH - col)
                rs = min(max(_int(c.attrs.get("rowspan"), 1), 1), 512, n - r)
                line.append(text)
                line.extend([""] * (cs - 1))
                if rs > 1:
                    if len(busy) < col + cs:
                        busy.extend([-1] * (col + cs - len(busy)))
                    for dc in range(cs):
                        busy[col + dc] = max(busy[col + dc], r + rs - 1)
                col += cs
            while col < len(busy) and busy[col] >= r:
                line.append("")
                col += 1
            width = max(width, len(line))
            if _grid_room(self.clock, len(grid), width) < 1:
                self.clock.cut("table(s) cut at %d cells" % CELLS)
                break
            grid.append(line)
        self.clock.cells += len(grid) * width
        if md_table(grid, self.clock) is None:
            # one column: a table that lays a page out (a title page in a cell); its cells as the
            # blocks they hold, headings and all
            return caption + [b for c in cells for b in self.blocks(c, depth + 1)]
        return caption + _table_blocks(grid, self.clock)

    # -- inline
    def inline(self, el, depth):
        parts = []
        for k in el.kids:
            parts.append(_esc(_space(k)) if isinstance(k, str) else self.inline_el(k, depth + 1))
        return "".join(parts)

    def inline_el(self, el, depth):
        self.clock.tick()
        t, a = el.tag, el.attrs
        if t in _SKIP or "hidden" in a or id(el) in self.skip:
            return ""
        if depth > DEPTH:
            return _esc(_space(_text(el)))
        if t == "br":
            return "\n"
        if t == "img":
            return self.pic(a.get("src", ""), a.get("alt", ""))
        if t == "image":
            return self.pic(a.get("xlink:href") or a.get("href", ""), "")
        if t == "svg":
            stack, pics = [el], []
            while stack:
                x = stack.pop()
                if not isinstance(x, str):
                    if x.tag == "image":
                        pics.append(self.pic(x.attrs.get("xlink:href") or x.attrs.get("href", ""), ""))
                    stack.extend(reversed(x.kids))
            return " ".join(p for p in pics if p)
        if t == "a":
            kind = (a.get("epub:type", "") + " " + a.get("role", "")).lower()
            if "backlink" in kind:
                return ""
            lab = self.noteref(el)
            if lab:
                self.book.refs.setdefault(lab, _one_line(self.inline(el, depth)))
                return "[^%s]" % lab
            return _link(self.inline(el, depth), a.get("href", ""))
        if t in ("em", "i", "cite", "dfn", "var"):
            return _emph(self.inline(el, depth), "*")
        if t in ("strong", "b"):
            return _emph(self.inline(el, depth), "**")
        if t in ("s", "strike", "del"):
            return _emph(self.inline(el, depth), "~~")
        if t in ("code", "kbd", "samp", "tt"):
            return _code(_space(_text(el)))
        if t == "q":
            return "\u201c" + self.inline(el, depth) + "\u201d"
        if t == "math":
            m = _space(a.get("alttext") or _text(el)).strip()
            return " %s " % _esc(m) if m else ""
        if t == "rt":
            s = _one_line(self.inline(el, depth))
            return "(%s)" % s if s else ""
        if t == "rp":
            return ""
        if t == "switch":
            for k in el.kids:
                if not isinstance(k, str) and k.tag == "default":
                    return self.inline(k, depth)
            return ""
        if t in _BLOCK:                       # a block inside a line: its words, set apart
            return " " + self.inline(el, depth) + " "
        return self.inline(el, depth)

    def pic(self, src, alt):
        src = (src or "").strip()
        if not src or src.startswith("data:"):
            return ""
        if _EXTERNAL.match(src):
            return _pic(alt, src)
        rel = urllib.parse.unquote(src.split("#")[0].split("?")[0])
        return _pic(alt, posixpath.normpath(posixpath.join(self.dir, rel)))


def _epub_parts(zf, clock):
    """The book's reading order: [(path, media type)], the navigation document left out (it
    repeats the headings as links). No package document: every (X)HTML part by name."""
    opf_path = None
    c = zf.read("META-INF/container.xml", 1 << 20)
    if c:
        for m in _ROOTFILE.finditer(_decode(c)):
            clock.tick()
            a = _attrs(m.group(0))
            if a.get("full-path") and (not a.get("media-type") or "oebps-package" in a.get("media-type", "")):
                opf_path = a["full-path"]
                break
    if not opf_path:
        opf_path = next((n for n in zf.names if n.lower().endswith(".opf")), None)
    opf = zf.read(opf_path, 16 << 20) if opf_path else None
    parts, seen = [], set()
    if opf:
        t, base = _decode(opf), posixpath.dirname(opf_path.lstrip("/"))
        items = {}
        for m in _OPF_ITEM.finditer(t):
            clock.tick()
            a = _attrs(m.group(0))
            if a.get("id") and a.get("href"):
                path = posixpath.normpath(posixpath.join(base, urllib.parse.unquote(a["href"].split("#")[0])))
                items[a["id"]] = (path, a.get("media-type", "").lower(), a.get("properties", "").lower().split())
        for m in _OPF_ITEMREF.finditer(t):
            clock.tick()
            it = items.get(_attrs(m.group(0)).get("idref"))
            if it and "nav" not in it[2] and (it[0], it[1]) not in seen:
                seen.add((it[0], it[1]))
                parts.append((it[0], it[1]))
    if not parts:
        parts = [(n, "") for n in sorted(zf.names) if re.search(r"(?i)\.x?html?$", n)]
    return parts


def epub_md(path, until=None, finish=None):
    """An EPUB 2 or 3 as Markdown: its spine in order, each part's XHTML as blocks. A part whose
    reading breaks is named, and the parts around it are read."""
    clock = _Clock(until, finish)
    with zipfile.ZipFile(path) as z:
        zf = _Zip(z)
        parts = _epub_parts(zf, clock)
        book, texts, late = _Book(), [], False
        for doc, media in parts:
            if clock.late():                    # the clock is read here too
                late = True
                break
            if "svg" in media or doc.lower().endswith(".svg"):
                texts.append((doc, None))
                continue
            data = zf.read(doc)
            if data is None:
                continue
            t = _markup(_decode(data))
            texts.append((doc, t))
            book.scan(doc, t, clock)
        out, done, big, broke, size = [], 0, [], [], sum(len(t) for _d, t in texts if t)
        read_chars = 0
        for i, (doc, t) in enumerate(texts):
            if late or clock.late():
                late = True
                break
            if t is None:
                out.append(_pic("", doc))       # a page that is a picture (a cover in SVG)
                done += 1
                continue
            try:
                root, how = _html_tree(t, clock)
                if how == "full":
                    big.append(doc)
                elif how == "broke":
                    broke.append("%s (its markup)" % doc)
                blocks = _Html(doc, book, clock).blocks(_find(root, "body") or root)
            except Late:
                late = True
                break
            except MemoryError:
                raise
            except Exception as e:              # noqa: BLE001  (this part, not the book)
                broke.append("%s (%s)" % (doc, type(e).__name__))
                blocks = []
            read_chars += len(t)
            texts[i] = (doc, None)
            out.append("\n\n".join(b for b in blocks if b))
            done += 1
        clock.finishing()
        md = _marks("\n\n".join(o for o in out if o.strip()))
        dangling = {lab for lab in book.refs if lab not in book.defined}
        if dangling:                    # a call whose note was never found: what the book showed there
            md = re.sub(r"\[\^(\d+)\]", lambda m: book.refs.get(m.group(1), "") if m.group(1) in dangling
                        else m.group(0), md)
        note = _join(zf.note(), clock.said())
        if big:
            note = _join("%d part(s) read up to their first %d elements (%s)" % (len(big), NODES, ", ".join(big[:3])),
                         note)
        if broke:
            note = _join("%d part(s) could not be read whole, what came before the fault kept (%s)"
                         % (len(broke), ", ".join(broke[:3])), note)
        if late:
            note = _join("the time ran out: %d of the book's %d parts read%s"
                         % (done, len(parts), clock.more(float(read_chars) / size if size else 0)), note)
        return md, note


# ---------------------------------------------------------------- ODT

_ODF = {"office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
        "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
        "xlink": "http://www.w3.org/1999/xlink",
        "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
        "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"}


def _o(name):
    prefix, local = name.split(":")
    return "{%s}%s" % (_ODF[prefix], local)


O_P, O_H, O_SPAN, O_A, O_S, O_TAB, O_LB = (_o("text:" + x) for x in ("p", "h", "span", "a", "s", "tab", "line-break"))
O_LIST, O_ITEM, O_LHEAD = _o("text:list"), _o("text:list-item"), _o("text:list-header")
O_NOTE, O_NBODY = _o("text:note"), _o("text:note-body")
O_TABLE, O_ROW, O_CELL, O_COVERED = (_o("table:" + x) for x in ("table", "table-row", "table-cell",
                                                                  "covered-table-cell"))
O_ROWS = (_o("table:table-header-rows"), _o("table:table-rows"), _o("table:table-row-group"))
O_FRAME, O_IMAGE, O_TEXTBOX, O_DRAW_A = (_o("draw:" + x) for x in ("frame", "image", "text-box", "a"))
O_OBJECT, O_OBJECT_OLE = _o("draw:object"), _o("draw:object-ole")
O_TITLE, O_DESC = _o("svg:title"), _o("svg:desc")
O_STYLE_NAME, O_HREF = _o("text:style-name"), _o("xlink:href")
O_RUBY, O_RUBY_BASE, O_RUBY_TEXT = _o("text:ruby"), _o("text:ruby-base"), _o("text:ruby-text")
O_NOTE_CITATION = _o("text:note-citation")
O_TEXT_BODY, O_SHEET_BODY, O_SLIDE_BODY = _o("office:text"), _o("office:spreadsheet"), _o("office:presentation")
O_PAGE, O_SLIDE_NOTES, O_TABLE_NAME = _o("draw:page"), _o("presentation:notes"), _o("table:name")
O_BODY, O_ANNOTATION, O_SHAPES = _o("office:body"), _o("office:annotation"), _o("table:shapes")
O_TABLE_SOURCE, O_TABLE_STYLE = _o("table:table-source"), _o("table:style-name")
O_STYLE_BOXES = (_o("office:font-face-decls"), _o("office:styles"), _o("office:automatic-styles"))
_ODF_SKIP = frozenset(_o(x) for x in (
    "office:annotation", "office:annotation-end", "text:tracked-changes", "text:soft-page-break",
    "text:bookmark", "text:bookmark-start", "text:bookmark-end", "text:reference-mark",
    "text:reference-mark-start", "text:reference-mark-end", "text:toc-mark", "text:toc-mark-start",
    "text:toc-mark-end", "text:alphabetical-index-mark", "text:alphabetical-index-mark-start",
    "text:alphabetical-index-mark-end", "text:user-index-mark", "text:user-index-mark-start",
    "text:user-index-mark-end", "text:change", "text:change-start", "text:change-end",
    "text:sequence-decls", "text:variable-decls", "text:user-field-decls", "text:dde-connection-decls",
    "office:forms", "draw:object", "draw:object-ole", "draw:control", "svg:title", "svg:desc",
    "text:note-citation"))
_DRAW = _ODF["draw"]


def _mathml(el):
    """MathML as a line of text: a fraction (a)/(b), a power a^b, an index a_b, a root √(a)."""
    tag = el.tag.rsplit("}", 1)[-1]
    kids = [_mathml(k) for k in el if k.tag.rsplit("}", 1)[-1] not in ("annotation", "annotation-xml")]
    if tag == "mfrac" and len(kids) == 2:
        return "(%s)/(%s)" % tuple(kids)
    if tag in ("msup", "msub") and len(kids) == 2:
        return ("%s^%s" if tag == "msup" else "%s_%s") % tuple(kids)
    if tag == "msubsup" and len(kids) == 3:
        return "%s_%s^%s" % tuple(kids)
    if tag == "msqrt":
        return "√(%s)" % " ".join(kids)
    if tag == "mroot" and len(kids) == 2:
        return "root(%s, %s)" % (kids[1], kids[0])
    return " ".join([(el.text or "").strip()] + kids).strip()


# ---------------------------------------------------------------- Office Math (OMML), a DOCX's formulas
# python-docx's paragraphs hold no m:oMath, so a DOCX's formulas were lost (a DOCX that is one formula
# read as nothing, KNOWN-ISSUES 165). A formula is read as one line, as an ODT's MathML is (_mathml):
# a fraction a/b and (a+b)/(c-d), a power x^2 and e^(-x^2), an index x_i and C_(ij), a root √x,
# √(x+1) and root(3, x), an n-ary operator with its limits ∑_(i=1)^n x_i, a matrix by its rows [a, b;
# c, d] (in its delimiter's brackets when it stands alone in one), an accent on one letter as its
# combining mark (x̂), else hat(...). A group of more than one character is in parentheses, so the
# line says what the formula does. Works on ElementTree and lxml elements alike.
M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
OMML_DEPTH = 100
_ACCENTS = {"̂": "hat", "^": "hat", "ˆ": "hat", "̃": "tilde", "~": "tilde", "˜": "tilde",
            "̄": "bar", "̅": "bar", "¯": "bar", "‾": "bar", "⃗": "vec", "→": "vec",
            "̇": "dot", "˙": "dot", "̈": "ddot", "¨": "ddot", "⃛": "dddot",
            "̌": "check", "ˇ": "check", "̆": "breve", "˘": "breve", "́": "acute",
            "´": "acute", "̀": "grave", "`": "grave"}
_COMBINING = {"hat": "̂", "tilde": "̃", "bar": "̅", "vec": "⃗", "dot": "̇",
              "ddot": "̈", "dddot": "⃛", "check": "̌", "breve": "̆", "acute": "́",
              "grave": "̀"}
_BRACES = {"⏟": "underbrace", "⏞": "overbrace", "⏝": "underparen", "⏜": "overparen",
           "⎵": "underbracket", "⎴": "overbracket"}
_FUNCTIONS = frozenset("sin cos tan cot sec csc sinh cosh tanh coth arcsin arccos arctan log ln lg exp lim "
                       "liminf limsup max min sup inf det dim ker arg deg gcd lcm hom mod Pr tr".split())
_SCRIPTS = frozenset(("sSub", "sSup", "sSubSup", "limLow", "limUpp", "func", "nary"))
_DOUBLE = dict(zip("CHNPQRZ", "ℂℍℕℙℚℝℤ"))      # ℂℍℕℙℚℝℤ
_INVISIBLE = {0x200B: None, 0x2061: " ", 0x2062: None, 0x2063: None, 0x2064: None}
_ONE = re.compile(r"^.[̀-ͯ⃐-⃿]*$|^\d{1,40}(?:[.,]\d{1,40})?$", re.S)
_WORD = re.compile(r"^[^\W\d_]{2,64}$")
_CALL = re.compile(r"^[^\W\d_]{1,64}(?=[(\[])")
_PAIRS = {"(": ")", "[": "]", "{": "}", "⟨": "⟩"}


def _mname(el):
    t = el.tag
    return t.rsplit("}", 1)[-1] if isinstance(t, str) else ""


def _mkid(el, name):
    for k in el:
        if _mname(k) == name:
            return k
    return None


def _mval(el, prop, default=None):
    """The m:val of property `prop` in `el`'s properties (its m:xxxPr child)."""
    pr = next((k for k in el if _mname(k).endswith("Pr")), None)
    p = _mkid(pr, prop) if pr is not None else None
    v = p.get(M_NS + "val") if p is not None else None
    return default if v is None else v


def _mon(v):
    return v is not None and v.lower() not in ("0", "off", "false")


def _bracketed(s):
    """Is all of s one bracket pair, with the brackets inside it balanced (one pass)? A group past
    4 096 characters is taken for one that is not, and gets parentheses of its own: each level of a
    formula asks this of its parts, and the work is then the formula's size, not times its depth."""
    if len(s) > 4096:
        return False
    if len(s) >= 2 and s[0] == s[-1] == "|":
        return "|" not in s[1:-1]
    if len(s) < 2 or s[0] not in _PAIRS or s[-1] != _PAIRS[s[0]]:
        return False
    depth, close = 0, _PAIRS[s[0]]
    for i, c in enumerate(s):
        if c == s[0]:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0 and i < len(s) - 1:
                return False
    return True


def _call(s):
    m = _CALL.match(s)
    return bool(m) and _bracketed(s[m.end():])


def _mg(s):
    """A script or a limit as one group: one character, a number, or bracketed whole as it is."""
    s = s.strip()
    return s if not s or _ONE.match(s) or _bracketed(s) else "(%s)" % s


def _mgf(s):
    """A fraction's part: as _mg(), and a call f(x) as it is."""
    s = s.strip()
    return s if _call(s) else _mg(s)


def _mgb(s):
    """A base: as _mg(), and a word (sin, lim) or a call f(x) as it is."""
    s = s.strip()
    return s if not s or _ONE.match(s) or _bracketed(s) or _WORD.match(s) or _call(s) else "(%s)" % s


def _mrun(el):
    """A math run's text; a double-struck letter as its own character (ℝ)."""
    t = "".join(k.text or "" for k in el if _mname(k) == "t").translate(_INVISIBLE)
    pr = _mkid(el, "rPr")
    scr = _mkid(pr, "scr") if pr is not None else None
    if scr is not None and scr.get(M_NS + "val") == "double-struck":
        t = "".join(_DOUBLE.get(c, chr(0x1D538 + ord(c) - 65) if "A" <= c <= "Z" else c) for c in t)
    return t


def _mword(el, s):
    """Is this run a function's name, which the next letter must not touch (sin x, not sinx)?"""
    if s in _FUNCTIONS:
        return True
    pr = _mkid(el, "rPr")
    sty = _mkid(pr, "sty") if pr is not None else None
    return bool(_WORD.match(s)) and sty is not None and sty.get(M_NS + "val") == "p"


def _mseq(el, d):
    """Children in order; a space where a script, an operator or a function's name meets a letter or
    a digit (sin x, A_(ik) B_(kj)), and where a fraction meets one or a bracket."""
    out, prev = [], ""
    for k in el:
        if not isinstance(k.tag, str):
            continue
        s = omml_text(k, d)
        if not s:
            continue
        if out and prev and not out[-1][-1:].isspace() and (s[:1].isalnum() or (prev == "f" and s[:1] in "([")):
            out.append(" ")
        out.append(s)
        n = _mname(k)
        prev = "f" if n == "f" else "x" if n in _SCRIPTS or (n == "r" and _mword(k, s.strip())) else ""
    return "".join(out)


def _malone(e, name):
    kids = [k for k in e if isinstance(k.tag, str) and not _mname(k).endswith("Pr")]
    return len(kids) == 1 and _mname(kids[0]) == name


def _mmatrix(el, d, beg, end):
    rows = [", ".join(omml_text(c, d + 1).strip() for c in r if _mname(c) == "e") for r in el if _mname(r) == "mr"]
    return "%s%s%s" % (beg, "; ".join(rows), end)


def omml_text(el, depth=0):
    """An m:oMath - or any element of one - as one line of text (see above). Past OMML_DEPTH levels
    of nesting, its text as it stands."""
    if depth > OMML_DEPTH:
        return " ".join("".join(el.itertext()).split())
    n = _mname(el)
    d = depth + 1

    def part(name):
        k = _mkid(el, name)
        return omml_text(k, d) if k is not None else ""

    if n == "r":
        return _mrun(el) if el.tag == M_NS + "r" else "".join(k.text or "" for k in el if k.tag == _W_NS + "t")
    if n.endswith("Pr"):
        return ""
    if n == "f":
        num, den = part("num"), part("den")
        if _mval(el, "type", "bar") == "noBar":
            return "%s; %s" % (num.strip(), den.strip())
        return "%s/%s" % (_mgf(num), _mgf(den))
    if n == "sSup":
        return "%s^%s" % (_mgb(part("e")), _mg(part("sup")))
    if n == "sSub":
        return "%s_%s" % (_mgb(part("e")), _mg(part("sub")))
    if n == "sSubSup":
        return "%s_%s^%s" % (_mgb(part("e")), _mg(part("sub")), _mg(part("sup")))
    if n == "sPre":
        sub, sup = part("sub").strip(), part("sup").strip()
        return "%s%s %s" % ("_" + _mg(sub) if sub else "", "^" + _mg(sup) if sup else "", _mgb(part("e")))
    if n == "rad":
        base, deg = part("e"), part("deg").strip()
        if _mon(_mval(el, "degHide")) or not deg:
            return "√" + _mg(base)
        return "root(%s, %s)" % (deg, base.strip())
    if n == "nary":
        op = _mval(el, "chr", "∫")                     # no m:chr: an integral
        sub = "" if _mon(_mval(el, "subHide")) else part("sub").strip()
        sup = "" if _mon(_mval(el, "supHide")) else part("sup").strip()
        body = part("e").strip()
        head = op + ("_" + _mg(sub) if sub else "") + ("^" + _mg(sup) if sup else "")
        # a body past 4 096 characters is not searched for an operator at each level (a 10 MB run
        # 99 operators deep was searched 99 times): it gets parentheses, as _bracketed() says
        if body and (len(body) > 4096 or re.search(r"[+\-−=<>≤≥≠±,;]", body)) and not _bracketed(body):
            body = "(%s)" % body
        return (head + " " + body).strip()
    if n == "d":
        beg = _mval(el, "begChr", "(").replace("∣", "|")
        end = _mval(el, "endChr", ")").replace("∣", "|")
        sep = _mval(el, "sepChr", "|")
        kids = [k for k in el if _mname(k) == "e"]
        if len(kids) == 1 and _malone(kids[0], "m"):
            return _mmatrix(_mkid(kids[0], "m"), d, beg, end or ("}" if beg == "{" else ""))
        if len(kids) == 1 and _malone(kids[0], "f") and _mval(_mkid(kids[0], "f"), "type") == "noBar" and beg == "(":
            f = _mkid(kids[0], "f")
            return "binom(%s, %s)" % (omml_text(_mkid(f, "num"), d + 1).strip(),
                                      omml_text(_mkid(f, "den"), d + 1).strip())
        return "%s%s%s" % (beg, sep.join(omml_text(k, d).strip() for k in kids), end)
    if n == "m":
        return _mmatrix(el, d, "[", "]")
    if n == "eqArr":                                        # its rows; "&" marks where they align
        return "; ".join(t for t in (omml_text(k, d).replace("&", "").strip() for k in el if _mname(k) == "e") if t)
    if n == "acc":
        base, c = part("e").strip(), _mval(el, "chr", "̂")
        name = _ACCENTS.get(c, "")
        if not name:
            return base + c
        return base + _COMBINING[name] if len(base) == 1 else "%s(%s)" % (name, base)
    if n == "bar":
        base, top = part("e").strip(), _mval(el, "pos", "top") != "bot"
        return base + "̅" if top and len(base) == 1 else "%s(%s)" % ("overline" if top else "underline", base)
    if n == "groupChr":
        c = _mval(el, "chr", "⏟")
        return "%s(%s)" % (_BRACES[c], part("e").strip()) if c in _BRACES else part("e") + c
    if n in ("limLow", "limUpp"):
        lim, e = part("lim").strip(), _mkid(el, "e")
        inner = [k for k in e if isinstance(k.tag, str) and not _mname(k).endswith("Pr")] if e is not None else []
        if len(inner) == 1 and _mname(inner[0]) in ("limLow", "limUpp") and _mname(inner[0]) != n:
            # an operator with a limit under it and one over it: ⋃_(i=1)^n, whichever stands outside
            o = inner[0]
            other = omml_text(_mkid(o, "lim"), d + 1).strip() if _mkid(o, "lim") is not None else ""
            under, over = (lim, other) if n == "limLow" else (other, lim)
            base = omml_text(_mkid(o, "e"), d + 1) if _mkid(o, "e") is not None else ""
            return "%s_%s^%s" % (_mgb(base), _mg(under), _mg(over))
        base = part("e").strip()
        if lim in _BRACES:                                  # a brace written as a limit (pandoc's)
            return "%s(%s)" % (_BRACES[lim], base)
        return "%s%s%s" % (_mgb(base), "_" if n == "limLow" else "^", _mg(lim))
    if n == "func":
        fname, arg = part("fName").strip(), part("e").strip()
        return fname + (arg if arg[:1] in "([" else " " + arg) if arg else fname
    if n == "phant":
        return part("e") if _mon(_mval(el, "show", "on")) else ""
    return _mseq(el, d)


def _flat_text(el):
    """An element's text with its spaces, tabs and line breaks, without recursion: text:s a space,
    text:tab a tab, text:line-break a line end."""
    out, stack = [el.text or ""], [(None, iter(el))]
    while stack:
        owner, it = stack[-1]
        ch = next(it, None)
        if ch is None:
            stack.pop()
            if owner is not None:
                out.append(owner.tail or "")
            continue
        tag = ch.tag.rsplit("}", 1)[-1] if isinstance(ch.tag, str) else ""
        if tag in ("s", "tab", "line-break"):
            out.append(" " if tag == "s" else "\t" if tag == "tab" else "\n")
            out.append(ch.tail or "")
            continue
        out.append(ch.text or "")
        stack.append((ch, iter(ch)))
    return "".join(out)


class _OdfStyles(object):
    """What the styles say: a paragraph style's outline level (a heading), bold and italic of
    paragraph and text styles through their parents, which list styles number their levels, which
    fonts are of fixed pitch (code), and which sheets are hidden."""

    def __init__(self):
        self.st, self.lists, self.fixed = {}, {}, set()

    def load(self, root):
        if root is None:
            return
        for box in root:
            self.load_box(box)

    def load_box(self, box):
        """One of a part's style boxes: its font faces, its styles or its automatic styles."""
        if box.tag == _o("office:font-face-decls"):
            for ff in box:
                if ff.get(_o("style:font-pitch")) == "fixed":
                    self.fixed.add(ff.get(_o("style:name")))
        elif box.tag in (_o("office:styles"), _o("office:automatic-styles")):
            for s in box:
                if s.tag == _o("style:style"):
                    self.style(s)
                elif s.tag == _o("text:list-style"):
                    self.list_style(s)

    def style(self, s):
        name = s.get(_o("style:name"))
        d = {"parent": s.get(_o("style:parent-style-name")), "display": s.get(_o("style:display-name")) or name}
        lvl = s.get(_o("style:default-outline-level"))
        if lvl and lvl.isdigit() and int(lvl) > 0:
            d["outline"] = int(lvl)
        for p in s:
            if p.tag == _o("style:text-properties"):
                w, it = p.get(_o("fo:font-weight")), p.get(_o("fo:font-style"))
                if w:
                    d["bold"] = w in ("bold", "600", "700", "800", "900")
                if it:
                    d["italic"] = it in ("italic", "oblique")
                if p.get(_o("style:font-name")):
                    d["font"] = p.get(_o("style:font-name"))
            elif p.tag == _o("style:table-properties") and p.get(_o("table:display")) == "false":
                d["hidden"] = True                     # a sheet no one opening the workbook sees
        self.st[(s.get(_o("style:family")), name)] = d

    def list_style(self, s):
        levels = {}
        for lv in s:
            n = _int(lv.get(_o("text:level")), 0)
            if lv.tag == _o("text:list-level-style-number"):
                levels[n] = bool(lv.get(_o("style:num-format")))
            elif n:
                levels[n] = False
        self.lists[s.get(_o("style:name"))] = levels

    def get(self, family, name, key):
        for _ in range(20):
            d = self.st.get((family, name)) if name else None
            if d is None:
                return None
            if d.get(key) is not None:
                return d[key]
            name = d.get("parent")
        return None

    def code(self, name):
        for _ in range(20):
            d = self.st.get(("paragraph", name)) if name else None
            if d is None:
                return False
            if re.search(r"(?i)preformatted|source.?(?:text|code)|\bcode\b|listing|verbatim", d.get("display") or ""):
                return True
            name = d.get("parent")
        return False


class _Odt(object):
    """The body of an OpenDocument text as Markdown blocks; notes at the end. An element whose
    reading breaks is left out and counted (`broke`), and the elements around it are read."""

    def __init__(self, styles, clock, zf=None):
        self.s, self.clock, self.zf = styles, clock, zf
        self.notes = []                   # [(label, blocks)]
        self.labels = 0                   # the notes' and the comments' labels given so far
        self.counts = {}                  # (list style, level) -> the last number it gave
        self.broke = {}                   # the kind of fault -> how many elements it cost
        self.done, self.of = 0, 0         # top-level elements read, of how many
        self.out = []                     # a workbook's blocks, its sheets' as each one ends (_Body)
        self.sheet_no = 0                 # sheets read so far

    def label(self):
        self.labels += 1
        return str(self.labels)

    def doc(self, root):
        """The body, whichever it is: a text's blocks; a spreadsheet's sheets, each a heading, its shapes
        and its table, then its comments (sheet_blocks; content.xml's own reading reads them as they
        come, _Body); a presentation's slides, each "## Slide N", its frames' text, tables and pictures
        in order, then its notes."""
        body = root.find(_o("office:body"))
        box = next((k for k in body if k.tag in (O_TEXT_BODY, O_SHEET_BODY, O_SLIDE_BODY)), None) \
            if body is not None else None
        if box is None:
            return "", False
        out, late = [], False
        kids = list(box)
        self.of = len(kids)
        try:
            slide = 0
            for ch in kids:
                if box.tag == O_TEXT_BODY:
                    out.extend(self.blocks_of([ch], 1))
                elif box.tag == O_SHEET_BODY and ch.tag == O_TABLE:
                    sheet = _Sheet(self, ch)
                    for k in ch:
                        sheet.child(k)
                    out.extend(self.sheet_blocks(sheet))
                elif box.tag == O_SLIDE_BODY and ch.tag == O_PAGE:
                    slide += 1
                    out.append("## Slide %d" % slide)
                    out.extend(self.blocks_of([k for k in ch if k.tag != O_SLIDE_NOTES], 1))
                    for notes in (k for k in ch if k.tag == O_SLIDE_NOTES):
                        said = " ".join(_one_line(b) for b in self.blocks_of(list(notes), 2) if b)
                        if said:
                            out.append("notes: " + said)
                self.done += 1
        except Late:
            late = True
        return self.finish(out, late)

    def finish(self, out, late):
        """The blocks read as one Markdown text, the notes after them: (markdown, late)."""
        self.clock.finishing()
        md = "\n\n".join(b for b in out if b)
        notes = [d for d in (_note_def(lab, blocks) for lab, blocks in self.notes) if d]
        if notes:
            md = md + "\n\n" + "\n\n".join(notes)
        return _marks(md), late

    def sheet_blocks(self, sheet, finishing=False):
        """A sheet as blocks: its name a heading, its shapes' text and pictures, its table, then its
        comments, each a note of its cell; nothing for a sheet with none of them, or an external
        link's cache. `finishing`: the time is up, its table is written with no clock."""
        self.sheet_no += 1
        if sheet.cache():
            return []
        try:
            rows = sheet.grid.blocks(finishing)
        except (Late, MemoryError):
            raise
        except Exception as e:             # noqa: BLE001  (this sheet, not the others)
            self.broke[type(e).__name__] = self.broke.get(type(e).__name__, 0) + 1
            rows = []
        said = [_note_def(label, [text]) for label, text in sheet.comments]
        body = [b for b in sheet.shapes + rows + said if b]
        if not body:
            return []
        return [_heading(2, _esc(_one_line(sheet.name or "Sheet %d" % self.sheet_no)))] + body

    def plain(self, el):
        """What is past DEPTH: its words as one paragraph."""
        t = _para(_esc(_space(_flat_text(el))))
        return [t] if t else []

    def blocks_of(self, els, depth):
        out, code = [], []

        def flush_code():
            if code:
                f = _fence(_unesc("\n".join(code)))
                del code[:]
                if f:
                    out.append(f)
        for ch in els:
            self.clock.tick()
            if depth > DEPTH:
                out.extend(self.plain(ch))
                continue
            try:
                self.block(ch, depth, out, code, flush_code)
            except (Late, MemoryError):
                raise
            except Exception as e:             # noqa: BLE001  (this element, not the document)
                name = type(e).__name__
                self.broke[name] = self.broke.get(name, 0) + 1
        flush_code()
        return out

    def block(self, ch, depth, out, code, flush_code):
        tag = ch.tag
        if tag in (O_P, O_H):
            pend = []
            kind, text = self.para(ch, pend, depth)
            if kind == "code":
                code.append(text)
                return
            flush_code()
            if text:
                out.append(text)
            out.extend(pend)
            return
        flush_code()
        if tag == O_LIST:
            out.extend(self.list(ch, 0, None, depth + 1))
        elif tag == O_TABLE:
            out.extend(self.table(ch, depth + 1))
        elif isinstance(tag, str) and tag.startswith("{%s}" % _DRAW):
            pend = []
            s = _para(self.draw(ch, pend, depth + 1))
            if s:
                out.append(s)
            out.extend(pend)
        elif tag in _ODF_SKIP or not isinstance(tag, str):
            return
        else:                              # a section, an index's body, any other wrapper
            out.extend(self.blocks_of(list(ch), depth + 1))

    def para(self, el, pend, depth):
        # a heading is a text:h; a text:p in a heading's style is one its author took out of the
        # outline (a copyright page's "Authors", the title over a table of contents): it stays a
        # paragraph, bold when its style is
        style = el.get(O_STYLE_NAME)
        lvl = (_int(el.get(_o("text:outline-level")), 1) or 1) if el.tag == O_H else 0
        if not lvl and self.s.code(style):
            return "code", self.inline(el, pend, (True, True, ""), depth).rstrip()
        base = (bool(self.s.get("paragraph", style, "bold")), bool(self.s.get("paragraph", style, "italic")),
                self.s.get("paragraph", style, "font") or "")
        text = self.inline(el, pend, base, depth)
        if lvl:
            return "h", _heading(lvl, text)
        p = _para(text)
        if p and (base[0] or base[1]):
            p = "\n".join(_bi(ln, base[0], base[1]) for ln in p.split("\n"))
        return "p", p

    def inline(self, el, pend, base, depth):
        parts = [_esc(_space(el.text or ""))]
        for ch in el:
            parts.append(self.inline_el(ch, pend, base, depth + 1))
            if ch.tail:
                parts.append(_esc(_space(ch.tail)))
        return "".join(parts)

    def inline_el(self, ch, pend, base, depth):
        self.clock.tick()
        tag = ch.tag
        if not isinstance(tag, str):                      # a comment or a processing instruction
            return ""
        if depth > DEPTH:
            return _esc(_space(_flat_text(ch)))
        if tag == O_SPAN:
            st = ch.get(O_STYLE_NAME)
            b, i = self.s.get("text", st, "bold"), self.s.get("text", st, "italic")
            b = base[0] if b is None else b
            i = base[1] if i is None else i
            font = self.s.get("text", st, "font") or base[2]
            inner = self.inline(ch, pend, (b, i, font), depth)
            if font != base[2] and font in self.s.fixed and base[2] not in self.s.fixed:
                return _code(_unesc(inner))
            if (b and not base[0]) or (i and not base[1]):
                return _bi(inner, b and not base[0], i and not base[1])
            return inner
        if tag == O_S:
            n = min(max(_int(ch.get(_o("text:c")), 1), 1), 200)
            self.clock.spaces += n
            if self.clock.spaces > SPACES:              # the document's spaces are spent: one more
                return " "
            return " " * n
        if tag == O_TAB:
            return "\t"
        if tag == O_LB:
            return "\n"
        if tag == O_A:
            return _link(self.inline(ch, pend, base, depth), ch.get(O_HREF) or "")
        if tag == O_NOTE:
            label, k = self.label(), len(self.notes)
            self.notes.append((label, []))
            body = ch.find(O_NBODY)
            self.notes[k] = (label, self.blocks_of(list(body), depth + 1) if body is not None else [])
            return "[^%s]" % label
        if tag.startswith("{%s}" % _DRAW):
            return self.draw(ch, pend, depth)
        if tag in _ODF_SKIP:
            return ""
        if tag == O_RUBY:
            b, r = ch.find(O_RUBY_BASE), ch.find(O_RUBY_TEXT)
            rb = self.inline(b, pend, base, depth) if b is not None else ""
            rt = _esc(_one_line(_flat_text(r))) if r is not None else ""
            return rb + ("(%s)" % rt if rt else "")
        if ch.get(_o("text:is-hidden")) == "true":
            return ""
        return self.inline(ch, pend, base, depth)

    def draw(self, el, pend, depth):
        """A frame: its picture where it stands; a text box's or a shape's paragraphs after the
        paragraph that holds it."""
        if depth > DEPTH:
            return _esc(_space(_flat_text(el)))
        if el.tag == O_DRAW_A:
            return " ".join(p for p in (self.draw(k, pend, depth + 1) for k in el) if p)
        if el.tag != O_FRAME:
            pend.extend(self.blocks_of([k for k in el if k.tag not in _ODF_SKIP], depth + 1))
            return ""
        alt, pic = "", ""
        for k in el:
            if k.tag in (O_TITLE, O_DESC) and not alt:
                alt = _one_line(_flat_text(k))
            elif k.tag in (O_OBJECT, O_OBJECT_OLE) and not pic:
                # an embedded object: a formula as its text; a chart or a sheet is left out, and
                # with it the picture that stands in for it (ObjectReplacements/, no extension)
                pic = self.formula(k.get(O_HREF) or "") if k.tag == O_OBJECT else ""
                pic = pic or "\x00"
        for k in el:
            if k.tag == O_IMAGE and not pic:
                href = (k.get(O_HREF) or "").strip()
                if href and not href.startswith("data:"):
                    pic = _pic(alt, href if _EXTERNAL.match(href) else
                               posixpath.normpath(urllib.parse.unquote(re.sub(r"^\./", "", href))))
            elif k.tag == O_TEXTBOX:
                pend.extend(self.blocks_of(list(k), depth + 1))
            elif k.tag == O_TABLE:                  # a slide's table stands in a frame of its own
                pend.extend(self.table(k, depth + 1))
        return pic.replace("\x00", "")

    def formula(self, href):
        """An embedded formula (LibreOffice Math) as inline code: its StarMath source, else what
        its MathML says."""
        name = posixpath.normpath(urllib.parse.unquote(re.sub(r"^\./", "", href.strip())))
        data = self.zf.read(name + "/content.xml", 4 << 20) if self.zf is not None and name else None
        root, why = _xml(data, self.clock) if data else (None, "")
        if root is None:
            if why and why != "it is empty":
                self.clock.cut("formula(s) left out: %s" % why)
            return ""
        if not root.tag.endswith("}math"):
            return ""
        for a in root.iter():
            if a.tag.endswith("}annotation") and "starmath" in (a.get("encoding") or "").lower():
                t = _one_line(a.text or "")
                if t:
                    return " %s " % _code(t)
        try:
            t = _one_line(_mathml(root))
        except RecursionError:
            t = " ".join("".join(root.itertext()).split())
        return " %s " % _code(t) if t else ""

    def list(self, el, lvl, style, depth):
        if depth > DEPTH:
            return self.plain(el)
        style = el.get(O_STYLE_NAME) or style
        if any(x.tag == O_H for x in el.iter()):
            return self.flat(el, depth)        # numbered headings: they stay headings
        lvl += 1
        levels = self.s.lists.get(style) or {}
        ordered = levels.get(lvl, levels.get(1, False)) if levels else False
        cont = el.get(_o("text:continue-numbering")) == "true" or el.get(_o("text:continue-list"))
        n = self.counts.get((style, lvl), 0) + 1 if cont else 1
        items = []
        for it in el:
            if it.tag not in (O_ITEM, O_LHEAD):
                continue
            n = _int(it.get(_o("text:start-value")), n)
            blocks = []
            for ch in it:
                if ch.tag == O_LIST:
                    blocks.extend(self.list(ch, lvl, style, depth + 1))
                else:
                    blocks.extend(self.blocks_of([ch], depth + 1))
            blocks = [b for b in blocks if b]
            if not blocks:
                continue
            if (_is_list(blocks[0]) or it.tag == O_LHEAD) and items:
                items[-1][1].extend(blocks)          # only a deeper list, or a header: the item before's
                continue
            items.append(("%d. " % n if ordered else "- ", blocks))
            if ordered:
                n += 1
        self.counts[(style, lvl)] = n - 1
        md = _list(items)
        return [md] if md else []

    def flat(self, el, depth):
        if depth > DEPTH:
            return self.plain(el)
        out = []
        for it in el:
            for ch in it:
                if ch.tag == O_LIST:
                    out.extend(self.flat(ch, depth + 1))
                else:
                    out.extend(self.blocks_of([ch], depth + 1))
        return out

    def table(self, el, depth, repeat=64):
        """A text's or a slide's table (_Grid): its rows and cells repeated `repeat` times each at most."""
        grid = _Grid(self, depth, repeat)
        grid.walk(el)
        return grid.blocks()

    def cell(self, c, depth, sheet=None):
        """A cell's text as one line. A sheet's cell (`sheet`, its _Sheet) keeps its comment apart, a
        note of the cell's ("1997 [^1]", the comment after the sheet's table), and its shapes too - a
        text box or a picture anchored to the cell is the sheet's, before its table: such a box's
        paragraphs were glued into the cell ("addressesProjects")."""
        if depth > DEPTH:
            return _one_line(_esc(_space(_flat_text(c))))
        parts, marks = [], []
        for ch in c:
            tag = ch.tag
            if tag in (O_P, O_H):
                pend = []
                style = ch.get(O_STYLE_NAME)
                base = (bool(self.s.get("paragraph", style, "bold")), bool(self.s.get("paragraph", style, "italic")),
                        self.s.get("paragraph", style, "font") or "")
                t = _bi(_one_line(self.inline(ch, pend, base, depth)), base[0], base[1])
                parts.append(t)
                parts.extend(_one_line(b) for b in pend)
            elif tag in (O_LIST, O_ITEM, O_LHEAD, O_TABLE, O_ROW, O_CELL) + O_ROWS or tag == _o("text:section"):
                parts.append(self.cell(ch, depth + 1))
            elif sheet is not None and tag == O_ANNOTATION:
                said = " ".join(_one_line(b) for b in self.blocks_of(
                    [k for k in ch if k.tag in (O_P, O_H, O_LIST)], depth + 1) if b)
                if said:
                    label = self.label()
                    sheet.comments.append((label, said))
                    marks.append("[^%s]" % label)
            elif isinstance(tag, str) and tag.startswith("{%s}" % _DRAW):
                blocks = self.blocks_of([ch], depth + 1)
                if sheet is not None:
                    sheet.shapes.extend(blocks)
                else:
                    parts.extend(_one_line(b) for b in blocks)
            elif isinstance(tag, str) and tag not in _ODF_SKIP:
                parts.append(_one_line(_esc(_space(_flat_text(ch)))))
        return " ".join(p for p in parts + marks if p)


class _Grid(object):
    """A table's rows as they come: repeated rows and cells `repeat` times each at most (None: as
    often as the caps leave room for - a sheet's), a row WIDTH columns. A text's or a slide's table
    holds ROWS rows and its grid CELLS cells (DOC_CELLS with the document's other tables). A sheet's
    grid holds SHEET_CELLS (DOC_SHEET_CELLS with the workbook's other sheets) - what it stores, a
    cell at a time - and of the cells with text that only a repeat makes, CELLS (DOC_CELLS): a real
    sheet stores its cells (one of 441 377 was cut at 250 000, 2026-11-26), while a repeat makes a
    file of 1 KB a grid of millions (313 rows of 32 cells, each repeated 64 times both ways, took 40
    s and gave 164 MB). Past a cap the table is cut and the note says so. The text the grid holds is
    capped too, a repeated cell's counted as often as it is repeated: TABLE_BYTES a table,
    DOC_TABLE_BYTES a document (a 64 KB cell repeated in 1 024 columns and 1 000 rows, 1 KB of file,
    was 16 GB of text). A row with no text is left out, and a row's empty cells at its end."""
    __slots__ = ("odt", "depth", "rows", "width", "cut", "bytes", "copies", "cap", "sheet")

    def __init__(self, odt, depth, repeat=64, sheet=None):
        self.odt, self.depth, self.sheet = odt, depth, sheet
        self.rows, self.width, self.cut, self.bytes, self.copies = [], 0, False, 0, 0
        self.cap = repeat or (1 << 62)

    def walk(self, box, d=0):
        for r in box:
            if self.cut:
                return
            if r.tag in O_ROWS:
                if d < DEPTH:
                    self.walk(r, d + 1)
            elif r.tag == O_ROW:
                if self.sheet is not None:
                    self.sheet.row(r)
                else:
                    self.row(r)

    def row(self, r, extra=None):
        """One row. `extra`: the text of a sheet row's cells past WIDTH, which _Body did not keep in the tree."""
        clock = self.odt.clock
        if self.cut:
            return
        if self.sheet is None and len(self.rows) >= ROWS:
            self.cut = True
            clock.cut("table(s) cut at %d rows" % ROWS)  # it was cut there with nothing said
            return
        clock.tick()
        cells, size, copies, filled = [], 0, 0, 0
        for c in r:
            if c.tag not in (O_CELL, O_COVERED):
                continue
            rep = min(max(_int(c.get(_o("table:number-columns-repeated")), 1), 1), self.cap)
            text = self.odt.cell(c, self.depth + 1, self.sheet) if c.tag == O_CELL else ""
            room = WIDTH - len(cells)
            if room <= 0:
                if text:
                    cells[-1] = (cells[-1] + " " + text).strip()
                    size += len(text) + 1
                continue
            n = min(rep, room)
            cells.extend([text] * n)
            size += len(text) * n
            if text:
                filled += n
                copies += n - 1
        if extra:
            joined = " ".join(extra)                 # its cells past WIDTH join its last one, as above
            if cells:
                cells[-1] = (cells[-1] + " " + joined).strip()
            else:
                cells.append(joined)
            size += len(joined) + 1
        while cells and not cells[-1]:
            cells.pop()
        if not cells:
            return
        rep = min(max(_int(r.get(_o("table:number-rows-repeated")), 1), 1), self.cap)
        width = max(self.width, len(cells))
        if self.sheet is None:
            rep = min(rep, ROWS - len(self.rows))
            fit, why = _grid_room(clock, len(self.rows), width), "table(s) cut at %d cells" % CELLS
        else:
            fit, why = (_grid_room(clock, len(self.rows), width, SHEET_CELLS, DOC_SHEET_CELLS, clock.sheet_cells),
                        "sheet(s) cut at %d cells" % SHEET_CELLS)
            # k repeats of this row copy copies * k cells, and filled * (k - 1) more
            left = min(CELLS - self.copies, DOC_CELLS - clock.copies - self.copies)
            if copies + filled and (left + filled) // (copies + filled) < fit:
                fit, why = (left + filled) // (copies + filled), "sheet(s) cut at %d cells its repeats copy" % CELLS
        left = min(TABLE_BYTES - self.bytes, DOC_TABLE_BYTES - clock.table_bytes - self.bytes)
        if size and left // size < fit:
            fit, why = left // size, "table(s) cut at %d MB of text" % (TABLE_BYTES >> 20)
        if fit < rep:
            rep = max(0, fit)
            self.cut = True
            clock.cut(why)
        if rep:
            self.width = width
            self.bytes += size * rep
            self.copies += copies * rep + filled * (rep - 1)
            self.rows.extend([cells] * rep)

    def blocks(self, finishing=False):
        """The table's blocks (`finishing`: written with no clock, the time being up)."""
        clock = self.odt.clock
        if self.sheet is None:
            clock.cells += len(self.rows) * self.width
        else:
            clock.sheet_cells += len(self.rows) * self.width
            clock.copies += self.copies
        clock.table_bytes += self.bytes
        return _table_blocks(self.rows, None if finishing else clock)


class _Sheet(object):
    """One sheet as it is read: its name; whether it is hidden; whether it is an external link's cache
    - a hidden sheet with a table:table-source, a copy of another file's sheet that no one opening the
    workbook sees (LibreOffice writes their cells, and such a sheet read as one of the workbook's,
    named "'file:///C:/...'#$Sheet1"; Excel's hold values alone, 556 of them in one workbook); its
    grid; its shapes' blocks, a text box's paragraphs, a shape's text and a picture, whether on its
    page (table:shapes) or in a cell; its comments, each with its label."""
    __slots__ = ("odt", "el", "name", "hidden", "linked", "grid", "shapes", "comments", "at", "open_at")

    def __init__(self, odt, el):
        self.odt, self.el = odt, el
        self.name = el.get(O_TABLE_NAME) or ""
        self.hidden = bool(odt.s.get("table", el.get(O_TABLE_STYLE), "hidden"))
        self.linked = False
        self.grid = _Grid(odt, 1, None, self)
        self.shapes, self.comments = [], []
        # the rows that ended, their repeats counted (the row a cut came in: `open_at`): a cut sheet says
        # from which row it lost them (odt_md)
        self.at, self.open_at = 0, 0

    def cache(self):
        return self.linked and self.hidden

    def child(self, ch):
        """One of the sheet's own elements: a row, rows, its shapes, its link to another file."""
        tag = ch.tag
        if tag == O_TABLE_SOURCE:
            self.linked = True
        elif self.cache():
            return
        elif tag == O_ROW:
            self.row(ch)
        elif tag in O_ROWS:
            self.grid.walk(ch, 1)
        elif tag == O_SHAPES:
            self.shapes.extend(self.odt.blocks_of(list(ch), 2))

    def row(self, r, extra=None):
        self.at += min(max(_int(r.get(_o("table:number-rows-repeated")), 1), 1), SHEET_ROWS)
        if self.cache():
            return
        try:
            self.grid.row(r, extra)
        except (Late, MemoryError):
            raise
        except Exception as e:                                 # noqa: BLE001  (this row, not the sheet)
            name = type(e).__name__
            self.odt.broke[name] = self.odt.broke.get(name, 0) + 1


class _Body(ET.TreeBuilder):
    """content.xml's tree as it is parsed (_feed): a spreadsheet's rows are read as each one ends and
    dropped, its sheets' other parts as they end, so a workbook costs what its rows hold, not what its
    XML holds - Excel writes a cell to ODS in 120 bytes: of 17 workbooks from government sites
    (2026-11-26), one of 2.7 MB had a content.xml of 142 MB and one of 1.8 MB of 41 MB, both cut at 32
    MB, the first's tree of 32 MB taking 205 MB. A text's or a presentation's body is built whole,
    for _Odt.doc()."""

    def __init__(self, odt):
        ET.TreeBuilder.__init__(self)
        self.odt, self.stack, self.sheet, self.sheets, self.root = odt, [], None, False, None
        self.begun = []                        # the sheets begun: a cut names the others as lost (_cut_lost)
        # what the tree holds now, and each open element's count with what ended under it (0: not in the tree); past
        # HELD a spreadsheet's tree keeps no more (KNOWN-ISSUES 312): what was open was built whole until it ended - a
        # row of 800 000 cells, 68 MB of XML in a 225 KB file, took 365 MB, and up to SHEET_BYTES 2.4-2.7 GB
        self.held, self.sizes, self.detached = 0, [], 0
        # the open row's cells so far, repeats counted, and the text of those past WIDTH, which leave the tree
        self.row_cells, self.overflow, self.overflow_bytes = 0, [], 0

    def _sheet_row(self, k):
        """Is stack[k] a row of the sheet being read (under its table, in row groups alone)?"""
        st = self.stack
        return (self.sheet is not None and k >= 4 and st[k].tag == O_ROW and k - 4 <= DEPTH
                and all(e.tag in O_ROWS for e in st[4:k]))

    def start(self, tag, attrs):
        el = ET.TreeBuilder.start(self, tag, attrs)
        st = self.stack
        st.append(el)
        parent_out = len(self.sizes) > 0 and self.sizes[-1] == 0
        self.sizes.append(1)
        if self.sheets:                        # (what comes before the body - its styles - is held, never counted)
            if len(st) > 1 and (parent_out or self.held >= HELD):
                del st[-2][-1]                 # past what the tree holds: neither it nor what it holds is kept (it is
                                               # its parent's last child: remove() searched 100 000 for each)
                self.sizes[-1] = 0
                self.detached += 1
            else:
                self.held += 1
        if len(st) == 1:
            self.root = el
        elif len(st) == 3 and tag == O_SHEET_BODY and st[1].tag == O_BODY:
            self.sheets = True
        elif len(st) == 4 and self.sheets and tag == O_TABLE and st[2].tag == O_SHEET_BODY:
            self.sheet = _Sheet(self.odt, el)
            self.begun.append(self.sheet)
        elif tag == O_ROW and self._sheet_row(len(st) - 1):
            self.row_cells, self.overflow, self.overflow_bytes = 0, [], 0
        return el

    def end(self, tag):
        el = ET.TreeBuilder.end(self, tag)
        st = self.stack
        st.pop()
        size = self.sizes.pop()
        n = len(st)
        drop = False
        if n == 1 and tag in O_STYLE_BOXES:
            self.odt.s.load_box(el)            # content.xml's own styles, before its body
        elif self.sheets and n == 3:
            if self.sheet is not None and el is self.sheet.el:
                self.sheet_done()
            drop = True                        # a sheet read, or the workbook's other parts
        elif self.sheet is not None and n == 4 and tag != O_ROW:
            self.sheet.child(el)
            drop = True
        elif tag == O_ROW and self.sheet is not None and n >= 4 and n - 4 <= DEPTH and all(
                e.tag in O_ROWS for e in st[4:]):
            self.sheet.row(el, self.overflow)          # (a row of the table's own, or in its row groups)
            self.overflow, self.overflow_bytes = [], 0
            drop = True
        elif tag in (O_CELL, O_COVERED) and n >= 5 and self._sheet_row(n - 1):
            # a cell of the sheet's open row: past WIDTH columns its text is kept and the cell leaves the tree
            if self.row_cells >= WIDTH:
                text = self.odt.cell(el, 2, self.sheet) if tag == O_CELL else ""
                if text and self.overflow_bytes < TABLE_BYTES:
                    self.overflow.append(text)
                    self.overflow_bytes += len(text) + 1
                elif text:
                    self.odt.clock.cut("a row's cells past %d columns cut at %d MB of their text" % (
                        WIDTH, TABLE_BYTES >> 20))
                drop = True
            else:
                self.row_cells += min(max(_int(el.get(_o("table:number-columns-repeated")), 1), 1), 1 << 62)
        if drop:
            if size:
                parent = st[-1]
                if len(parent) and parent[-1] is el:
                    del parent[-1]             # an element that ends is its parent's last child: no search
                else:
                    parent.remove(el)
                self.held -= size
        elif self.sizes and size:
            self.sizes[-1] += size             # (what ended under an element stays in the tree with it)
        return el

    def sheet_done(self, finishing=False):
        """The sheet read: its blocks. The time running out while they are written, they are written
        with no clock, and the reading stops (Late)."""
        sheet, odt = self.sheet, self.odt
        try:
            odt.out.extend(odt.sheet_blocks(sheet, finishing))
        except Late:
            odt.clock.finishing()
            odt.out.extend(odt.sheet_blocks(sheet, True))
            raise
        finally:
            self.sheet = None

    def broken(self):
        """The XML broke, or was cut: the text of the element still open goes to it, and the row then
        open is read as far as it goes (a part cut at its size limit kept no word of its last
        paragraph); the root built so far, or None."""
        try:
            self.start(_CUT, {})
            self.end(_CUT)
            root = self.close()
        except Exception:                                      # noqa: BLE001
            return None
        if self.sheet is not None:
            st = self.stack
            k = next((i for i in range(4, len(st)) if st[i].tag not in O_ROWS), None)
            if k is not None and st[k].tag == O_ROW:
                self.sheet.open_at = self.sheet.at + 1             # its first cells stand; the rest is lost
                try:
                    self.sheet.row(st[k], self.overflow)
                except Late:
                    pass                       # the time is up: the rows before it stand
        return root


def _prolog(data):
    """What an XML part's start holds before its first element: "doctype" when it declares a DOCTYPE
    (or an entity), "element" when its first element starts within `data` (or its XML breaks first:
    the parser says how), "" when `data` ends before either."""
    p = expat.ParserCreate()
    seen = []

    def doctype(*_a):
        seen.append("doctype")
        raise _Stop()

    def element(*_a):
        seen.append("element")
        raise _Stop()
    p.StartDoctypeDeclHandler = doctype
    p.EntityDeclHandler = doctype
    p.StartElementHandler = element
    try:
        p.Parse(data, False)
    except _Stop:
        pass
    except expat.ExpatError:
        return "element"
    return seen[0] if seen else ""


def _feed(zf, name, b, clock):
    """The part `name` given to `b` (a _Body) as it unpacks, a MB at a time, one MB in memory: up to
    SHEET_BYTES once its body is a spreadsheet's, else PART_BYTES. A DOCTYPE is refused before the
    builder sees a byte (a billion laughs on an expat with no limit of its own). Returns (why, late,
    read, size): why it stopped before its end ("" when it did not; XML that breaks keeps what came
    before that point), whether the time ran out, the bytes read, and the size its archive gives."""
    real = zf.name(name)
    size = zf.z.getinfo(real).file_size if real is not None else 0
    parser = ET.XMLParser(target=b)
    head, started, got, why, late = b"", False, 0, "", False
    pieces = zf.chunks(name)
    try:
        for chunk in pieces:
            if not started:
                head += chunk
                seen = _prolog(head)
                if seen == "doctype":
                    return "it declares a DOCTYPE", False, len(head), size
                if not seen and len(head) < (1 << 20):
                    continue
                if not seen:
                    return "its first element does not start in its first MB", False, len(head), size
                started, chunk = True, head
            cap = SHEET_BYTES if b.sheets else PART_BYTES
            if got + len(chunk) > cap:
                parser.feed(chunk[:cap - got])
                got = cap
                why = "%s is over the size limit, %d MB: what comes after that is missing" % (name, cap >> 20)
                break
            got += len(chunk)
            parser.feed(chunk)
            if clock.late():
                raise Late()
        if not started and head:
            parser.feed(head)                  # under a MB, its first element never started: the parser says why
            started = True
        if not started:
            return "it is empty", False, 0, size
        if not why:
            parser.close()
    except ET.ParseError as e:
        why = "its XML breaks (%s): what comes after that point is missing" % str(e)[:60]
    except Late:
        late = True
    finally:
        pieces.close()
    return why, late, got, size


def _cut_lost(zf, b, sheet):
    """What a spreadsheet cut in its content.xml lost, as markers: the rows of the sheet the cut came in, from the
    first row not whole on - `[rows · lost in the cut · 54-? · Third]`, the extent not in the file (content.xml
    names no sheet's size) -, then the sheets after it the file names elsewhere: LibreOffice's settings.xml lists
    every sheet by name (alphabetically, not in the workbook's order: several lost sheets each say `order unknown`),
    its meta.xml how many there are; Excel writes neither (and its content.xml first), so its cut ODS names no lost
    sheet."""
    out = []
    begun = [s.name for s in b.begun if not s.cache()]          # an external link's cache is no sheet of its own
    if sheet is not None and not sheet.cache():
        first = sheet.open_at or sheet.at + 1
        if first <= SHEET_ROWS:
            out.append(lost_marker("rows", sheet.name or "Sheet %d" % len(begun), "%d-?" % first))
    settings, meta = zf.read("settings.xml", 16 << 20), zf.read("meta.xml", 1 << 20)
    names = []
    if settings:
        # the list's opening found once and its end once: a pattern that took what lies between them scanned the rest
        # of the file again from each opening with no end - 10.7 s for 398 KB, quadratic, and the readers' process
        # was stopped with the workbook's text (KNOWN-ISSUES 313)
        start = re.search(rb'config:name="Tables"\s*>', settings)
        end = settings.find(b"</config:config-item-map-named>", start.end()) if start else -1
        names = [html.unescape(n.decode("utf-8", "replace")) for n in re.findall(
            rb'<config:config-item-map-entry\s+config:name="([^"]*)"', settings[start.end():end])] if end >= 0 else []
    seen = set(s.name for s in b.begun)
    gone = [n for n in names if n not in seen]
    # settings.xml lists the sheets by name, not in the workbook's order: they all follow the last sheet that arrived,
    # and among themselves they have no order the file knows - said, when there are several. LOST_SHEETS of them are
    # named, then how many more: a file's list made a marker of each, as many as it said (KNOWN-ISSUES 313)
    out.extend(lost_marker("sheet", n, *(("order unknown",) if len(gone) > 1 else ())) for n in gone[:LOST_SHEETS])
    if len(gone) > LOST_SHEETS:
        out.append(lost_marker("sheet", "", "%d more" % (len(gone) - LOST_SHEETS)))
    count = re.search(rb'meta:table-count="(\d{1,6})"', meta or b"")
    if count and not names and int(count.group(1)) <= SHEETS_AT_MOST:
        total = int(count.group(1))           # how many, not which: each by its place
        lost = list(range(len(begun) + 1, total + 1))
        out.extend(lost_marker("sheet", "the sheet %d of %d" % (k, total)) for k in lost[:LOST_SHEETS])
        if len(lost) > LOST_SHEETS:
            out.append(lost_marker("sheet", "", "%d more of the %d" % (len(lost) - LOST_SHEETS, total)))
    return out


def odt_md(path, until=None, finish=None, cut=False):
    """An OpenDocument text, spreadsheet or presentation (ODT, ODS, ODP) as Markdown: content.xml's
    body, whichever it holds, read as it unpacks (_feed: a spreadsheet's rows as they come, _Body; a
    text's or a presentation's tree, _Odt.doc), with styles.xml for what its styles say. `cut`: the file
    is the copy of an archive cut in its content.xml, so where its XML breaks is the cut: a spreadsheet
    says what it lost there (_cut_lost)."""
    clock = _Clock(until, finish)
    with zipfile.ZipFile(path) as z:
        zf = _Zip(z)
        spreadsheet = (zf.read("mimetype", 200) or b"").strip() == b"application/vnd.oasis.opendocument.spreadsheet"
        if zf.name("content.xml") is None:
            # cut before anything of its content.xml unpacked: every sheet lost, named where the file names them
            lost = _cut_lost(zf, _Body(None), None) if cut and spreadsheet else []
            return "\n\n".join(lost), _join("no content.xml in this file", zf.note())
        styles, swhy = _OdfStyles(), ""
        sdata = zf.read("styles.xml", 16 << 20)
        if sdata:
            sroot, swhy = _xml(sdata, clock)
            styles.load(sroot)
            if swhy:
                swhy = "styles.xml could not be read%s: %s" % (" whole" if sroot is not None else "", swhy)
        odt = _Odt(styles, clock, zf)
        b = _Body(odt)
        why, late, got, size = _feed(zf, "content.xml", b, clock)
        if b.root is None and cut and not late and spreadsheet:
            # cut before its first element ended: every sheet lost, named where the file names them
            lost = _cut_lost(zf, b, None)
            if lost:
                return "\n\n".join(lost), _join("content.xml could not be read: %s" % (why or "it holds no element"),
                                               zf.note())
        if b.root is None:
            if not got and zf.bad:
                return "", _join("content.xml could not be read", zf.note())
            return "", ("its content.xml is empty" if why == "it is empty" else
                        "content.xml could not be read: %s" % (why or "it holds no element"))
        if late and not b.sheets:
            raise Late()
        if why and not late:
            b.broken()
        if b.sheets:
            open_sheet = b.sheet
            if b.sheet is not None:
                if late:
                    clock.finishing()
                try:
                    b.sheet_done(late)
                except Late:
                    late = True
            if cut and why.startswith("its XML breaks") and not late:
                odt.out.extend(_cut_lost(zf, b, open_sheet))
            md, _late = odt.finish(odt.out, late)
            done = float(got) / size if size else 0
        else:
            md, late = odt.doc(b.root)
            done = float(odt.done) / odt.of if odt.of else 0
            if cut and why.startswith("its XML breaks") and not late and spreadsheet:
                # a spreadsheet cut before its first sheet began (LibreOffice writes its styles first): every sheet lost
                md = "\n\n".join(x for x in [md] + _cut_lost(zf, b, None) if x)
        if b.detached:
            clock.cut("%d element(s) past the %d a workbook's tree holds at once left out" % (b.detached, HELD))
        broke = ""
        if odt.broke:
            broke = "%d element(s) could not be read and were left out (%s)" % (
                sum(odt.broke.values()), ", ".join(sorted(odt.broke)))
        note = _join(why, swhy, zf.note(), broke, clock.said(),
                     "the time ran out before the end of the document%s" % clock.more(done) if late else "")
        return md, note


# ---------------------------------------------------------------- RTF

_RTF_TOKEN = re.compile(r"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z'])|([{}])"
                        r"|([^\\{}\r\n]+)|[\r\n]+", re.S)
_RTF_SKIPPER = re.compile(r"\\bin(\d{1,10}) ?|\\[\\{}]|[{}]")
_RTF_DEST = re.compile(r"(?:\\\*)?[\r\n]*\\([a-zA-Z]{1,32})(-?\d{1,10})? ?")
# destinations whose text is never the document's: skipped whole, fast
_RTF_IGNORE = frozenset((
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "nonshppict", "header", "headerl", "headerr", "headerf",
    "footer", "footerl", "footerr", "footerf", "ftnsep", "ftnsepc", "ftncn", "aftnsep", "aftnsepc", "aftncn",
    "listtable", "listoverridetable", "revtbl", "rsidtbl", "filetbl", "xmlnstbl", "nonesttables", "txe", "xe",
    "tc", "tcn", "objdata", "objclass", "objalias", "objsect", "private", "pgdsctbl", "generator", "userprops",
    "template", "comment", "do", "themedata", "colorschememapping", "datastore", "latentstyles", "mmathPr",
    "atnid", "atnauthor", "atndate", "atnref", "atnparent", "annotation", "bkmkstart", "bkmkend", "pn",
    "pnseclvl", "background", "fchars", "lchars", "docvar", "sp", "sn", "sv", "shprslt", "picprop", "blipuid",
    "falt", "panose", "fname", "keycode", "operator", "title", "author", "company", "doccomm", "subject",
    "keywords", "creatim", "revtim", "printim", "buptim", "hlinkbase", "passwordhash", "wgrffmtfilter",
    "ffdeftext", "ffformat", "ffhelptext", "ffstattext", "ffentrymcr", "ffexitmcr", "ffname", "datafield",
    "pgp", "oldcprops", "oldpprops", "oldsprops", "oldtprops", "rxe", "bxe", "ixe", "pxe", "listpicture",
    "nesttableprops", "mhtmltag", "htmltag", "factoidname", "xmlattrname", "xmlattrvalue", "xmlclose",
    "xmlname", "xmlopen", "fontemb", "fontfile", "leveltext", "levelnumbers", "listname", "shpgrp"))
# destinations after \* that hold text of the document (or lead to it)
_RTF_KEEP = frozenset(("fldinst", "footnote", "shpinst", "shptxt", "ud", "listtext", "pntext"))
_CHARSET = {0: "cp1252", 2: "symbol", 77: "mac_roman", 78: "shift_jis", 79: "cp949", 80: "gb2312", 81: "big5",
            85: "mac_greek", 86: "mac_turkish", 88: "mac_latin2", 89: "mac_cyrillic", 128: "cp932", 129: "cp949",
            130: "johab", 134: "cp936", 136: "cp950", 161: "cp1253", 162: "cp1254", 163: "cp1258",
            177: "cp1255", 178: "cp1256", 186: "cp1257", 204: "cp1251", 222: "cp874", 238: "cp1250",
            254: "cp437", 255: "cp850"}
_DBCS = frozenset(("cp932", "shift_jis", "cp936", "gb2312", "cp949", "cp950", "big5", "johab"))
_SYMBOL = {0xB7: "\u2022", 0xA7: "\u25aa", 0xD8: "\u27a2", 0xFC: "\u2713", 0x6F: "\u25cb", 0x71: "\u25aa"}
_RTF_CHARS = {"emdash": "\u2014", "endash": "\u2013", "emspace": "\u2003", "enspace": "\u2002",
              "qmspace": "\u2005", "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019",
              "ldblquote": "\u201c", "rdblquote": "\u201d", "tab": "\t", "line": "\n", "lbr": "\n",
              "zwj": "\u200d", "zwnj": "\u200c", "zwbo": "\u200b", "zwnbo": "\ufeff"}
_RTF_SYMBOLS = {"~": "\u00a0", "_": "\u2011", "{": "{", "}": "}", "\\": "\\", "\t": "\t"}
_C0 = {c: None for c in range(32) if c not in (9, 10, 13)}

# a group's state, copied when a group opens: where text goes, how it looks, its paragraph
(_SINK, _UC, _FONT, _B, _I, _STRIKE, _HIDE, _STY, _OL, _LS, _LVL, _TBL, _PSINK, _FLD) = range(14)


class _Sink(object):
    """Where text goes: the body or a note (paragraphs, tables), a field's instruction or a list
    item's marker (plain text)."""
    __slots__ = ("kind", "runs", "blocks", "text", "rows", "row", "cell", "mark", "par")

    def __init__(self, kind):
        self.kind, self.runs, self.blocks, self.text = kind, [], [], []
        self.rows, self.row, self.cell, self.mark, self.par = [], [], [], None, 0


def _codec(name, cache={}):                                     # noqa: B006  (a cache on purpose)
    if name not in cache:
        try:
            codecs.lookup(name)
            cache[name] = name
        except LookupError:
            cache[name] = None
    return cache[name]


def _group_end(s, pos):
    """From inside an RTF group, the position after its closing brace (\\binN data jumped over)."""
    depth, search = 1, _RTF_SKIPPER.search
    while True:
        m = search(s, pos)
        if m is None:
            return len(s)
        pos, g = m.end(), m.group(0)
        if g == "{":
            depth += 1
        elif g == "}":
            depth -= 1
            if not depth:
                return pos
        elif m.group(1):
            pos += int(m.group(1))


# a picture's format, by the control word that names it: PNG and JPEG are written out; the others no
# browser or model shows (Windows and OS/2 metafiles, a Mac PICT, Windows' device bitmaps)
_PICT_FORMATS = {"pngblip": ".png", "jpegblip": ".jpg", "emfblip": "EMF", "wmetafile": "WMF", "macpict": "PICT",
                 "pmmetafile": "OS/2 metafile", "dibitmap": "DIB", "wbitmap": "Windows bitmap"}
_PICT_MAGIC = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff"}
_HEX_NOT = re.compile(r"[^0-9A-Fa-f]+")
_PIB = re.compile(r"[ \t\r\n]*\{\\sn[ \t\r\n]+pib[ \t\r\n]*\}")
_WZ_DESCRIPTION = re.compile(r"\{\\sn[ \t\r\n]+wzDescription[ \t\r\n]*\}[ \t\r\n]*\{\\sv[ \t\r\n]+([^{}\\]{0,1000})\}")


class _Rtf(object):
    def __init__(self, s, clock, pictures=None):
        self.s, self.clock = s, clock
        # where the pictures go (None: they are passed over), how many and how much were written,
        # and the ones of formats no one shows, by format
        self.picdir, self.pics, self.pic_bytes, self.unshown = pictures, 0, 0, {}
        self.shape = None                                # the last floating shape's group: (start, end)
        self.body = _Sink("body")
        self.st = [self.body, 1, None, False, False, False, False, 0, None, 0, 0, False, self.body, None]
        self.stack = []
        self.fonts, self.styles, self.list_ids, self.lists = {}, {}, {}, {}
        self.ansi, self.deff = "cp1252", None
        self.pend, self.skip_uc, self.high = bytearray(), 0, 0
        self.notes, self.counters = [], {}               # counters: list -> {level: the last number}
        self.cellx, self.trleft, self.rowdef = [], 0, None   # the row definition, one per \trowd
        self.pos, self.ctrl, self.chars = 0, 0, 0

    # -- the scan
    def run(self):
        s, n, match = self.s, len(self.s), _RTF_TOKEN.match
        pos, count = 0, 0
        while pos < n:
            m = match(s, pos)
            if m is None:
                pos += 1
                continue
            pos = m.end()
            count += 1
            if not count & 4095:
                self.pos = pos
                if self.clock.late():
                    raise Late()
            w = m.group(1)
            if w is not None:
                if self.pend:
                    self.flush()
                if self.skip_uc and w != "bin":
                    self.skip_uc -= 1
                    continue
                pos = self.word(w, m.group(2), pos)
                continue
            t = m.group(6)
            if t is not None:
                self.text(t)
                continue
            h = m.group(3)
            if h is not None:
                if self.skip_uc:
                    self.skip_uc -= 1
                else:
                    self.pend.append(int(h, 16))
                continue
            b = m.group(5)
            if b == "{":
                pos = self.open(pos)
            elif b == "}":
                self.close()
            elif m.group(4) is not None:
                self.symbol(m.group(4))
        self.pos = n

    def groups(self, a, b):
        """The groups one level inside s[a:b]: [(start, end)] of their insides."""
        out, depth, start = [], 0, None
        for m in _RTF_SKIPPER.finditer(self.s, a, b):
            g = m.group(0)
            if g == "{":
                depth += 1
                if depth == 1:
                    start = m.end()
            elif g == "}":
                if depth == 1 and start is not None:
                    out.append((start, m.start()))
                depth -= 1
        return out

    def open(self, pos):
        self.flush()
        self.skip_uc = 0
        self.stack.append((self.st, None))
        self.st = self.st[:]
        if len(self.stack) > 2000:                     # a nesting bomb: deeper groups are passed over
            self.st = self.stack.pop()[0]
            return _group_end(self.s, pos)
        m = _RTF_DEST.match(self.s, pos)
        if not m:
            return pos
        name, star = m.group(1), self.s.startswith("\\*", pos)
        if self.picdir is not None and name == "shpinst" and (self.shape is None or pos > self.shape[1]):
            # a floating shape: its picture's alt text is a property beside the picture's (picture());
            # a shape inside the one found is not looked for again (each would scan the outer's rest)
            self.shape = (m.end(), _group_end(self.s, m.end()))
        if self.picdir is not None and name in ("pict", "shppict", "sp"):
            # a picture where it stands: an inline one (\pict, Word's \*\shppict, whose \nonshppict
            # is the same picture again as WMF and stays passed over), a floating shape's (\sp pib)
            end = _group_end(self.s, m.end())
            try:
                self.picture(name, m.end(), max(m.end(), end - 1))
            except (Late, MemoryError):
                raise
            except Exception:                                  # noqa: BLE001  (this picture, not the text)
                self.clock.cut("picture(s) that could not be read")
            self.st = self.stack.pop()[0]
            return end
        if name in _RTF_IGNORE or (star and name not in _RTF_KEEP):
            end = _group_end(self.s, m.end())
            if name in ("fonttbl", "stylesheet", "listtable", "listoverridetable"):
                getattr(self, name)(m.end(), max(m.end(), end - 1))
            self.st = self.stack.pop()[0]
            return end
        return pos

    def close(self):
        self.flush()
        self.skip_uc = 0
        if not self.stack:
            return                                     # a "}" too many: nothing to close
        saved, closer = self.stack.pop()
        if closer:
            closer()
        self.st = saved

    def set_closer(self, fn):
        if self.stack:
            self.stack[-1] = (self.stack[-1][0], fn)

    def picture(self, kind, a, b):
        """The picture of a group s[a:b] (\\pict, \\*\\shppict holding one, \\sp whose \\sn is pib):
        a PNG or a JPEG is written to the picture folder as rtf-pict-NNNN, and ![](its name) stands in
        the text where the picture does (readpage makes it a marker); a picture of a format no browser
        or model shows (WMF, EMF, PICT) is named there in words. Its data is hex digits after the
        group's control words, or \\binN bytes; its nested groups (\\*\\blipuid, \\*\\picprop) are
        passed over. PICTURES pictures at most, PICTURE_BYTES each, TOTAL_BYTES in all."""
        s = self.s
        around = None                    # a floating shape's other properties: before and after its picture's
        if kind in ("sp", "shppict"):
            if kind == "sp" and not _PIB.match(s, a, b):
                return                                          # a shape's other properties
            if kind == "sp" and self.shape and self.shape[0] <= a <= self.shape[1]:
                around = ((max(self.shape[0], a - 65536), a), (b, min(self.shape[1], b + 65536)))
            i = s.find("{\\pict", a, b)
            if i < 0:
                return
            a, b = i + 6, max(i + 6, _group_end(s, i + 1) - 1)
        sink = self.st[_SINK] if self.st[_SINK] is not None else self.st[_PSINK]
        # its alt text, which Word keeps in the picture's properties before its data - a floating
        # shape's in a property of the shape, beside the picture's
        alt = _WZ_DESCRIPTION.search(s, a, min(b, a + 65536))
        for x, y in around or ():
            alt = alt or _WZ_DESCRIPTION.search(s, x, y)
        alt = _one_line(alt.group(1)) if alt else ""
        fmt, pos, data_at, raw = "", a, None, None
        while pos < b:
            m = _RTF_TOKEN.match(s, pos)
            if m is None:
                pos += 1
                continue
            if m.group(5) == "{":
                pos = _group_end(s, m.end())
                continue
            w = m.group(1)
            if w == "bin":
                n = max(0, _int(m.group(2)))
                if n > PICTURE_BYTES:
                    raw = b""
                else:
                    raw = s[m.end():min(b, m.end() + n)].encode("latin-1", "replace")
                break
            if w is not None:
                if w in _PICT_FORMATS:
                    fmt = w
                pos = m.end()
                continue
            if m.group(6) is not None and m.group(6).strip():
                data_at = m.start()
                break
            pos = m.end()
        ext = _PICT_FORMATS.get(fmt, "")
        if ext and not ext.startswith("."):
            self.unshown[ext] = self.unshown.get(ext, 0) + 1
            self._ref(sink, "[a picture in %s, not shown]" % ext)
            return
        if not ext:
            return
        if raw is None and data_at is not None:
            if (b - data_at) > 2.2 * PICTURE_BYTES:
                raw = b""                                       # its data alone is over the limit
            else:
                hexs = _HEX_NOT.sub("", s[data_at:b])
                raw = bytes.fromhex(hexs[:len(hexs) // 2 * 2])
        if not raw:
            self.clock.cut("picture(s) over %d MB left out" % (PICTURE_BYTES >> 20))
            return
        if not raw.startswith(_PICT_MAGIC[ext]):
            self.clock.cut("picture(s) whose data is not what their format says left out")
            return
        if self.pics >= PICTURES or self.pic_bytes + len(raw) > TOTAL_BYTES:
            self.clock.cut("pictures past %d (or %d MB) left out" % (PICTURES, TOTAL_BYTES >> 20))
            return
        self.pics += 1
        self.pic_bytes += len(raw)
        name = "rtf-pict-%04d%s" % (self.pics, ext)
        with open(os.path.join(self.picdir, name), "wb") as fh:
            fh.write(raw)
        self._ref(sink, _pic(alt, name))

    def _ref(self, sink, text):
        """Text of ours in a paragraph's runs, as it is (a note's call is put so)."""
        if sink is not None and sink.kind in ("body", "note"):
            sink.runs.append([[text], ("ref",)])

    # -- the tables of the header
    def fonttbl(self, a, b):
        cur = None
        for m in _RTF_TOKEN.finditer(self.s, a, b):
            w = m.group(1)
            if w == "f":
                cur = _int(m.group(2))
                self.fonts.setdefault(cur, None)
            elif w == "fcharset" and cur is not None:
                cp = _CHARSET.get(_int(m.group(2)))
                if cp and (cp == "symbol" or _codec(cp)):
                    self.fonts[cur] = cp
            elif w == "cpg" and cur is not None and _codec("cp%s" % m.group(2)):
                self.fonts[cur] = "cp%s" % m.group(2)

    def stylesheet(self, a, b):
        for ga, gb in self.groups(a, b):
            sid, other, lvl, name, depth = 0, False, None, [], 0
            for m in _RTF_TOKEN.finditer(self.s, ga, gb):
                w, br = m.group(1), m.group(5)
                if br:
                    depth += 1 if br == "{" else -1
                elif depth:
                    continue
                elif w == "s":
                    sid = _int(m.group(2))
                elif w in ("cs", "ds", "ts", "tsrowd"):
                    other = True
                elif w == "outlinelevel":
                    lvl = _int(m.group(2), 9)
                elif m.group(6):
                    name.append(m.group(6))
            if other:
                continue
            nm = "".join(name).strip().rstrip(";").strip().lower()
            if lvl is not None and 0 <= lvl < 9:
                self.styles[sid] = min(lvl + 1, 6)
            else:
                h = re.match(r"^(?:heading|\u00fcberschrift|titre|t\u00edtulo|titolo|kop|rubrik|otsikko|"
                             r"overskrift|nadpis)\s*([1-9])$", nm)
                if h:
                    self.styles[sid] = min(int(h.group(1)), 6)

    def listtable(self, a, b):
        for ga, gb in self.groups(a, b):
            levels = []
            for la, lb in self.groups(ga, gb):
                sub = self.s[la:lb]
                if sub.lstrip().startswith("\\listlevel"):
                    nfc = re.search(r"\\levelnfc(\d+)", sub)
                    levels.append((int(nfc.group(1)) if nfc else 0) not in (23, 255))
            lid = re.search(r"\\listid(-?\d+)", self.s[ga:gb])
            if lid:
                self.list_ids[int(lid.group(1))] = levels

    def listoverridetable(self, a, b):
        for ga, gb in self.groups(a, b):
            sub = self.s[ga:gb]
            lid, ls = re.search(r"\\listid(-?\d+)", sub), re.search(r"\\ls(\d+)", sub)
            if lid and ls and int(lid.group(1)) in self.list_ids:
                self.lists[int(ls.group(1))] = dict(enumerate(self.list_ids[int(lid.group(1))]))

    # -- text
    def cp(self):
        f = self.st[_FONT]
        return self.fonts.get(f if f is not None else self.deff) or self.ansi

    def lead_open(self, cp):
        """Does the pending run of bytes end with the first byte of a two-byte character?"""
        b, i = self.pend, 0
        lead = (lambda x: 0x81 <= x <= 0x9F or 0xE0 <= x <= 0xFC) if cp in ("cp932", "shift_jis") else \
            (lambda x: 0x81 <= x <= 0xFE)
        while i < len(b):
            i += 2 if lead(b[i]) else 1
        return i > len(b)

    def flush(self):
        if not self.pend:
            return
        cp = self.cp()
        b, self.pend = bytes(self.pend), bytearray()
        t = "".join(_SYMBOL.get(x, chr(x)) for x in b) if cp == "symbol" else b.decode(cp, "replace")
        self.emit(t)

    def text(self, t):
        if self.skip_uc:
            k = min(self.skip_uc, len(t))
            self.skip_uc -= k
            t = t[k:]
            if not t:
                return
        if self.pend:
            cp = self.cp()
            if cp in _DBCS and self.lead_open(cp):
                self.pend.append(ord(t[0]) & 0xFF)      # the second byte written as it is
                t = t[1:]
            self.flush()
            if not t:
                return
        if not t.isascii():                             # 8-bit text in the file: its code page's
            cp = self.cp()
            t = "".join(_SYMBOL.get(ord(x), x) for x in t) if cp == "symbol" else \
                t.encode("latin-1").decode(cp, "replace")
        self.emit(t)

    def emit(self, t):
        st = self.st
        sink = st[_SINK]
        if sink is None or st[_HIDE] or not t:
            return
        clean = t.translate(_C0)                         # control bytes are no text of a document
        if len(clean) != len(t):
            self.ctrl += len(t) - len(clean)
            t = clean
        self.chars += len(t)
        if sink.kind not in ("body", "note"):
            sink.text.append(t)
            return
        key = (st[_B], st[_I], st[_STRIKE])
        runs = sink.runs
        if runs and runs[-1][1] == key:
            pieces = runs[-1][0]
        elif len(runs) >= RUNS:
            # a paragraph of RUNS runs already: the rest of it is plain, one run (2 million runs
            # before one \par took 904 MB)
            if runs[-1][1] is not None:
                runs.append([[], None])
                self.clock.cut("paragraph(s) whose look past %d runs was left out" % RUNS)
            pieces = runs[-1][0]
        else:
            runs.append([[t], key])
            return
        pieces.append(t)
        if len(pieces) > 4096:
            pieces[-4096:] = ["".join(pieces[-4096:])]

    def symbol(self, c):
        self.flush()
        if self.skip_uc:
            self.skip_uc -= 1
            return
        if c in "\r\n":
            self.par()
        elif c in _RTF_SYMBOLS:
            self.emit(_RTF_SYMBOLS[c])

    def uni(self, arg):
        n = _int(arg)
        if n < 0:
            n += 65536
        if 0xD800 <= n < 0xDC00:
            self.high = n
        elif 0xDC00 <= n < 0xE000 and self.high:
            self.emit(chr(0x10000 + ((self.high - 0xD800) << 10) + (n - 0xDC00)))
            self.high = 0
        else:
            self.high = 0
            # outside Unicode (\u1114112, \u-70000) or half a pair: one U+FFFD, not the end of the
            # reading (chr() raised, and the whole document was lost)
            self.emit(chr(n) if 0 <= n <= 0x10FFFF and not 0xD800 <= n < 0xE000 else "\ufffd")
        self.skip_uc = max(0, self.st[_UC])

    # -- control words
    def word(self, w, arg, pos):
        st = self.st
        if w in ("par", "sect", "page", "column", "nestcell"):
            self.par()
        elif w == "pard":
            st[_STY], st[_OL], st[_LS], st[_LVL], st[_TBL] = 0, None, 0, 0, False
        elif w == "plain":
            st[_B] = st[_I] = st[_STRIKE] = st[_HIDE] = False
            st[_FONT] = self.deff
        elif w == "f":
            st[_FONT] = _int(arg)
        elif w == "b":
            st[_B] = arg != "0"
        elif w == "i":
            st[_I] = arg != "0"
        elif w in ("strike", "striked"):
            st[_STRIKE] = arg != "0"
        elif w in ("v", "deleted"):
            st[_HIDE] = arg != "0"
        elif w == "u":
            self.uni(arg)
        elif w == "uc":
            st[_UC] = _int(arg, 1)
        elif w in _RTF_CHARS:
            self.emit(_RTF_CHARS[w])
        elif w == "cell":
            self.cell()
        elif w == "row":
            self.row()
        elif w == "intbl":
            st[_TBL] = True
        elif w == "cellx":
            if len(self.cellx) < CELLX:                 # a row of 4 000 borders was copied into each row
                self.cellx.append(_int(arg))
                self.rowdef = None
        elif w == "trowd":
            self.cellx, self.trleft, self.rowdef = [], 0, None
        elif w == "trleft":
            self.trleft, self.rowdef = _int(arg), None
        elif w == "itap":
            st[_TBL] = _int(arg, 1) > 0
        elif w == "s":
            st[_STY] = _int(arg)
        elif w == "outlinelevel":
            st[_OL] = _int(arg, 9)
        elif w == "ls":
            st[_LS] = _int(arg)
        elif w == "ilvl":
            st[_LVL] = min(max(_int(arg), 0), 8)        # RTF's levels are 0-8 (4 000 indented 16 MB)
        elif w == "bin":
            n = max(0, _int(arg))
            if self.skip_uc:
                self.skip_uc -= 1
            return pos + n
        elif w == "field":
            rec = {"inst": [], "start": None}
            st[_FLD] = rec
            self.set_closer(lambda: self.field_end(rec))
        elif w == "fldinst":
            rec, sink = st[_FLD], _Sink("inst")
            st[_SINK] = sink
            if rec is not None:
                self.set_closer(lambda: rec["inst"].extend(sink.text))
        elif w == "fldrslt":
            rec, psink = st[_FLD], st[_PSINK]
            st[_SINK] = psink
            if rec is not None and psink is not None:
                psink.runs.append([[""], None])          # the result starts a run of its own
                rec["start"] = (psink, len(psink.runs), psink.par)
        elif w == "footnote":
            self.footnote()
        elif w in ("listtext", "pntext"):
            psink, mark = st[_PSINK], _Sink("mark")
            st[_SINK] = mark
            if psink is not None:
                self.set_closer(lambda: setattr(psink, "mark", "".join(mark.text)))
        elif w in ("shpinst", "upr"):
            st[_SINK] = None                             # nothing of it is text but what follows
        elif w in ("shptxt", "ud"):
            st[_SINK] = st[_PSINK]
        elif w == "ansicpg":
            cp = "cp%s" % arg
            if _codec(cp):
                self.ansi = cp
        elif w == "mac":
            self.ansi = "mac_roman"
        elif w == "pc":
            self.ansi = "cp437"
        elif w == "pca":
            self.ansi = "cp850"
        elif w == "deff":
            self.deff = _int(arg)
            if st[_FONT] is None:
                st[_FONT] = self.deff
        return pos

    # -- paragraphs, tables, notes, fields
    def runs_md(self, sink):
        """A paragraph's runs as Markdown: the document's text escaped, each run of one look
        marked; a note's call and a link are ours, as they are."""
        runs, sink.runs = sink.runs, []
        out = []
        for pieces, key in runs:
            t = "".join(pieces)
            if key is None or len(key) == 3:
                t = _esc(t)
            if key and len(key) == 3 and t.strip():
                b, i, s = key
                if s:
                    t = _emph(t, "~~")
                t = _bi(t, b, i)
            out.append(t)
        return _lines("".join(out))

    def par(self):
        st = self.st
        sink = st[_SINK]
        if sink is None or sink.kind not in ("body", "note"):
            if sink is not None and sink.kind == "inst":
                sink.text.append(" ")
            return
        text = self.runs_md(sink)
        mark, sink.mark = sink.mark, None
        sink.par += 1
        if st[_TBL]:
            if text:
                sink.cell.append(text)
            return
        self.end_table(sink)
        if not text:
            return
        lvl = self.heading(st) if sink.kind == "body" else None
        if lvl:
            if mark and re.search(r"\w", mark):          # a numbered heading keeps its number
                text = mark.strip() + " " + text
            sink.blocks.append(("h", lvl, text))
        elif mark is not None or st[_LS] > 0:
            ls, level = st[_LS], st[_LVL]
            ordered = self.lists.get(ls, {}).get(level)
            if ordered is None:
                ordered = bool(re.match(r"^\(?(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)]", (mark or "").strip()))
            sink.blocks.append(("li", level, ("%d. " % self.number(ls, level, mark)) if ordered else "- ", text))
        else:
            sink.blocks.append(("p", _escape(text)))

    def heading(self, st):
        ol = st[_OL]
        if ol is not None and 0 <= ol < 9:
            return min(ol + 1, 6)
        if ol is not None:
            return None                                  # \outlinelevel9: body text, whatever the style
        return self.styles.get(st[_STY])

    def number(self, ls, level, mark):
        """The item's number: its own marker's, else one more than the list's last at this level;
        the deeper levels of the list start again (each list's own counters: looking at every
        list's at each item was quadratic)."""
        nums = re.findall(r"\d+", mark or "")
        levels = self.counters.setdefault(ls, {})
        n = int(nums[-1]) if nums and len(nums[-1]) < 9 else levels.get(level, 0) + 1
        levels[level] = n
        for k in [k for k in levels if k > level]:
            del levels[k]
        return n

    def definition(self):
        """The row definition in force, one tuple for every row it lays out (it was a copy a row)."""
        if self.rowdef is None:
            self.rowdef = (tuple(self.cellx), self.trleft)
        return self.rowdef

    def add_row(self, sink, row):
        if len(sink.rows) < ROWS:
            sink.rows.append((row, self.definition()))
        else:
            self.clock.cut("table rows past %d left out" % ROWS)

    def cell(self):
        sink = self.st[_SINK]
        if sink is None or sink.kind not in ("body", "note"):
            return
        text = self.runs_md(sink)
        if text:
            sink.cell.append(text)
        if len(sink.row) < WIDTH:
            sink.row.append(" ".join(sink.cell))
        elif sink.cell:                                  # past the table's width: into its last cell
            sink.row[-1] = (sink.row[-1] + " " + " ".join(sink.cell)).strip()
        sink.cell, sink.mark = [], None

    def row(self):
        sink = self.st[_SINK]
        if sink is None or sink.kind not in ("body", "note"):
            return
        text = self.runs_md(sink)
        if text:
            sink.cell.append(text)
        if sink.cell:
            sink.row.append(" ".join(sink.cell))
            sink.cell = []
        if sink.row:
            self.add_row(sink, sink.row)
            sink.row = []

    def end_table(self, sink):
        if sink.cell or sink.row:
            if sink.cell:
                sink.row.append(" ".join(sink.cell))
                sink.cell = []
            self.add_row(sink, sink.row)
            sink.row = []
        if sink.rows:
            sink.blocks.append(("t", _rtf_grid(sink.rows, self.clock)))
            sink.rows = []

    def footnote(self):
        st = self.st
        psink = st[_PSINK]
        label = str(len(self.notes) + 1)
        note = _Sink("note")
        self.notes.append((label, note))
        if psink is not None and psink.kind in ("body", "note"):
            psink.runs.append([["[^%s]" % label], ("ref",)])
        st[_SINK] = st[_PSINK] = note
        st[_TBL] = False

        def end():
            text = self.runs_md(note)
            if text:
                note.blocks.append(("p", _escape(text)))
            self.end_table(note)
        self.set_closer(end)

    def field_end(self, rec):
        start = rec["start"]
        inst = "".join(rec["inst"]).strip()
        if not start or not re.match(r"(?i)HYPERLINK\b", inst) or re.search(r"\\l\b", inst):
            return
        sink, i, par = start
        if sink.par != par or i > len(sink.runs):
            return                                       # the result ran over paragraphs (a TOC)
        url = re.search(r'"([^"]+)"', inst) or re.match(r"(?i)HYPERLINK\s+(\S+)", inst)
        text = "".join(_esc("".join(p)) if k is None or len(k) == 3 else "".join(p) for p, k in sink.runs[i:])
        if url and text.strip():
            del sink.runs[i:]
            sink.runs.append([[_link(text, url.group(1))], ("link",)])

    def finish(self):
        """What was read as Markdown, by the clock's finishing time: what that leaves out is named."""
        self.clock.finishing()
        self.flush()
        body = self.body
        text = self.runs_md(body)
        if text:
            body.blocks.append(("p", _escape(text)))
        try:
            self.end_table(body)
        except Late:
            body.rows = []
            self.clock.cut("the time ran out while a table was written")
        md = _flat_md(body.blocks, self.clock)
        notes, empty = [], set()
        for label, note in self.notes:
            d = _note_def(label, [_flat_md(note.blocks, self.clock)])
            if d:
                notes.append(d)
            else:
                empty.add(label)
        if empty:                                        # a note with no text: no call either
            md = re.sub(r"\[\^(\d+)\]", lambda m: "" if m.group(1) in empty else m.group(0), md)
        return _marks(md + ("\n\n" + "\n\n".join(notes) if notes else ""))


def _rtf_grid(rows, clock):
    """[(cells, (right borders, left edge))] -> rows of cells on the table's columns: a cell whose
    right border (\\cellx) lies past one of the columns other rows have is followed by an empty cell
    for each, as a merged cell is elsewhere. Borders within 15 twips are one column; a table of
    more than 4 096 borders has its rows as they are. The columns are counted by bisection (each
    row summed over every border), and the grid stops at CELLS."""
    defs = {}
    for _c, d in rows:
        defs[id(d)] = d
    seen = set()
    for bounds, _l in defs.values():
        seen.update(bounds)
        if len(seen) > 4096:
            break
    grid = []
    if len(seen) <= 4096:
        for e in sorted(seen):
            if not grid or e - grid[-1] > 15:
                grid.append(e)
    out, width = [], 0
    for cells, (bounds, left) in rows:
        clock.tick()
        if not grid or len(bounds) < len(cells):
            line = list(cells)
        else:
            line = [""] * bisect.bisect_right(grid, left + 15)
            prev = left
            for k, cell in enumerate(cells):
                line.append(cell)
                span = bisect.bisect_right(grid, bounds[k] + 15) - bisect.bisect_right(grid, prev + 15)
                if span > 1:
                    line.extend([""] * (span - 1))
                prev = bounds[k]
        width = max(width, len(line))
        if _grid_room(clock, len(out), width) < 1:
            clock.cut("table(s) cut at %d cells" % CELLS)
            break
        out.append(line)
    clock.cells += len(out) * width
    return out


def _flat_md(blocks, clock):
    """The RTF reader's blocks as Markdown; list items nest by their level, each under the text of
    the item above it. A list's lines are joined once (each item was added to the list's text,
    and 100 000 items took 60 s); past the finishing time the rest is left out and named."""
    out, stack, items = [], [], None
    try:
        for b in blocks:
            clock.tick()
            if b[0] == "li":
                _k, lvl, marker, text = b
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                col = stack[-1][1] if stack else 0
                if items is None:
                    items = []
                    out.append(items)
                items.append(_indent(text, " " * col + marker, " " * (col + len(marker))))
                stack.append((lvl, col + len(marker)))
                continue
            stack, items = [], None
            if b[0] == "p":
                out.append(b[1])
            elif b[0] == "h":
                out.append(_heading(b[1], b[2]))
            elif b[0] == "t":
                out.extend(_table_blocks(b[1], clock))
    except Late:
        clock.cut("the time ran out while the document was written: what follows is missing")
    return "\n\n".join(o for o in ("\n".join(x) if isinstance(x, list) else x for x in out) if o)


def rtf_md(data, until=None, finish=None, pictures=None):
    """An RTF document as Markdown. A fault in the middle keeps what came before it. `pictures`: a
    folder its PNG and JPEG pictures are written to, each ![](its name) where it stands (_Rtf.picture);
    None passes them over."""
    clock = _Clock(until, finish)
    s = data.decode("latin-1") if isinstance(data, (bytes, bytearray)) else data
    if pictures is not None:
        os.makedirs(pictures, exist_ok=True)
    r = _Rtf(s, clock, pictures)
    late, broke = False, ""
    try:
        r.run()
    except Late:
        late = True
    except MemoryError:
        raise
    except Exception as e:                                     # noqa: BLE001  (what came before stays)
        broke = "the reading stopped at %d%% of the file (%s): what came before is kept" % (
            100 * r.pos // max(1, len(s)), type(e).__name__)
    if r.ctrl > max(50, (r.chars + r.ctrl) // 100):
        # bytes no writer leaves in text (random data after "{\rtf1" read as 64 708 words of
        # mojibake, 2026-11-20): what is there is not the document's text
        return "", "not text: this RTF holds binary data where its text should be"
    md = r.finish()
    unshown = ", ".join("%d in %s" % (n, f) for f, n in sorted(r.unshown.items()))
    note = _join(broke, clock.said(), "pictures no browser or model shows, named where they stand: %s" % unshown
                 if unshown else "", "the time ran out at %d%% of the file%s" % (
                     100 * r.pos // max(1, len(s)), clock.more(float(r.pos) / len(s) if s else 0)) if late else "")
    return md, note


# ---------------------------------------------------------------- plain text: when a reader breaks

_PLAIN_SKIP = ("fonttbl", "colortbl", "stylesheet", "info", "listtable", "listoverridetable", "generator",
               "rsidtbl", "xmlnstbl", "mmathPr", "themedata", "colorschememapping", "latentstyles",
               "datastore", "pict", "object", "header", "footer")
_PLAIN_GROUP = re.compile(r"\{\\(?:\*\\)?(?:%s)" % "|".join(_PLAIN_SKIP))


def rtf_plain(data):
    """RTF as plain text: control words and groups out, paragraphs kept, the hex and unicode escapes
    decoded; no tables. Linear: the groups nobody reads are passed over in one scan."""
    s = data.decode("latin-1", "replace") if isinstance(data, (bytes, bytearray)) else data
    out, pos = [], 0
    while True:
        m = _PLAIN_GROUP.search(s, pos)
        if m is None:
            break
        out.append(s[pos:m.start()])
        pos = _group_end(s, m.start() + 1)
    out.append(s[pos:])
    s = "".join(out)
    s = re.sub(r"\{\\\*[^{}]*\}", "", s)                         # destinations nobody shows
    s = re.sub(r"\\(par|line|sect|page)\b ?", "\n", s)
    s = re.sub(r"\\tab\b ?", "\t", s)

    def uni(m):
        n = int(m.group(1)) % 65536
        return chr(n) if not 0xD800 <= n < 0xE000 else "\ufffd"
    s = re.sub(r"\\u(-?\d{1,10})\??", uni, s)
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), s)
    s = re.sub(r"\\[a-zA-Z]{1,32}-?\d{0,10} ?", "", s)
    s = re.sub(r"\\([{}\\])", r"\1", s)
    s = s.replace("{", "").replace("}", "")
    lines = [ln.strip() for ln in s.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def odf_plain(path, cap=PART_BYTES, until=None):
    """An OpenDocument file's headings and paragraphs in order, as plain text: what is left when the
    reader breaks as a whole. content.xml read up to `cap`, a DOCTYPE refused, XML that breaks read
    up to the break. (text, note)."""
    clock = _Clock(until)
    with zipfile.ZipFile(path) as z:
        zf = _Zip(z)
        data = zf.read("content.xml", cap)
        root, why = _xml(data, clock) if data else (None, "no content.xml" if data is None else "it is empty")
        note = _join(("content.xml could not be read: %s" % why) if root is None else why, zf.note())
        if root is None:
            return "", note
        out = []
        for el in root.iter():
            clock.tick()
            if el.tag in (O_P, O_H):
                t = _flat_text(el).strip()
                if t:
                    level = el.get(_o("text:outline-level")) or "1"
                    out.append(("#" * min(6, int(level) if level.isdigit() else 1) + " " + t) if el.tag == O_H else t)
        return "\n\n".join(out), note


_PLAIN_BLOCK = re.compile(r"(?i)</?(?:p|div|h[1-6]|li|tr|br|section|blockquote|pre|dt|dd|table|ul|ol|hr|"
                          r"figure|figcaption|aside|header|footer)\b[^<>]{0,%d}>" % TAG_MAX)
_PLAIN_TAG = re.compile(r"<[^<>]{0,%d}>" % TAG_MAX)


def epub_plain(path, until=None):
    """An EPUB's words in its reading order, tags out, a paragraph at each block: the fallback when
    epub_md() breaks as a whole. (text, note)."""
    clock = _Clock(until)
    with zipfile.ZipFile(path) as z:
        zf = _Zip(z)
        try:
            parts = _epub_parts(zf, clock)
        except Late:
            raise
        except Exception:                                      # noqa: BLE001
            parts = [(n, "") for n in sorted(zf.names) if re.search(r"(?i)\.x?html?$", n)]
        out = []
        for doc, _media in parts:
            if clock.late():
                break
            data = zf.read(doc)
            if not data:
                continue
            t = _PLAIN_TAG.sub("", _PLAIN_BLOCK.sub("\n\n", _markup(_decode(data))))
            t = _lines(html.unescape(t))
            if t:
                out.append(t)
        return "\n\n".join(out), zf.note()


def plain(path, kind, until=None):
    """(text, note) of a document whose reader broke: its words without the structure."""
    if kind == "epub":
        return epub_plain(path, until)
    if kind in ("odt", "ods", "odp"):
        return odf_plain(path, PART_BYTES, until)
    with open(path, "rb") as fh:
        return rtf_plain(fh.read(min(os.fstat(fh.fileno()).st_size, RTF_BYTES))), ""


# ---------------------------------------------------------------- a process of its own

_JOB = []                          # the Job Object this process holds itself to: its handle, for its life


def _job_limit(nbytes):
    """Windows: this process in a Job Object of its own whose process memory limit is `nbytes` -
    the memory it commits, which an allocation past the limit is refused (MemoryError). Set by the
    process on itself with ctypes; a job inside the one a parent put it in is allowed since
    Windows 8. True when it is set."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):           # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [("Basic", Basic), ("Io", ctypes.c_ulonglong * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = Extended()
        info.Basic.LimitFlags = 0x100                          # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = nbytes
        if not (k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))      # extended limits
                and k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())):
            k32.CloseHandle(job)
            return False
        _JOB.append(job)
        return True
    except (OSError, AttributeError, ValueError, TypeError):
        return False


def _limit_memory(nbytes):
    """The readers' process held to `nbytes` where the OS can hold it: past it an allocation fails
    (MemoryError) and the reading ends, as no timeout can make it (a 1 KB EPUB took 1.4 GB in 5.9
    s). Linux: RLIMIT_AS, the address space. Windows: a Job Object's process memory limit, the
    memory committed (_job_limit). True when it is set. Not on macOS: its kernel does not hold to
    RLIMIT_AS (the call succeeds, and allocations go on past it), a process there reserves far more
    address space than it uses, and a process has no Job Object or cgroup it can put itself in -
    the kill at the read's time is all there is."""
    if sys.platform == "darwin":
        return False
    if os.name == "nt":
        return _job_limit(nbytes)
    try:
        import resource
    except ImportError:
        return False
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        want = nbytes if hard == resource.RLIM_INFINITY else min(nbytes, hard)
        if soft == resource.RLIM_INFINITY or soft > want:
            resource.setrlimit(resource.RLIMIT_AS, (want, hard))
        return True
    except (ValueError, OSError, AttributeError):
        return False


def main(argv):
    """python docreaders.py KIND PATH [UNTIL [KILL [PICTURES]]]: one document (KIND: epub, odt, ods, odp,
    rtf; "ods+cut" and the like: the copy of an archive cut in its content.xml, read()), as JSON on stdout
    ({"md", "note", "limit"}: limit, whether its memory is held - false where
    the OS holds none, or where holding it failed, which readpage's trace then says).
    UNTIL is when the reading stops (a time.time(); 0: no limit), KILL when readpage.py kills this
    process: what was read is written by the middle of the two. PICTURES: the folder an RTF's
    pictures are written to."""
    kind, path = argv[0], argv[1]
    until = float(argv[2]) if len(argv) > 2 and float(argv[2]) > 0 else None
    kill = float(argv[3]) if len(argv) > 3 and float(argv[3]) > 0 else None
    pictures = argv[4] if len(argv) > 4 and argv[4] else None
    finish = until + (kill - until) / 2 if until is not None and kill is not None and kill > until else None
    limited = _limit_memory(MEMORY)
    slow = os.environ.get("READ_PAGE_TEST_DOC_SLEEP")          # the test suites' stand-in for a slow document
    if slow:
        time.sleep(float(slow))
    md, note = read(path, kind, until, finish, pictures)
    sys.stdout.buffer.write(json.dumps({"md": md, "note": note, "limit": bool(limited)},
                                       ensure_ascii=False).encode("utf-8", "replace"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
