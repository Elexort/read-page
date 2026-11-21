"""EPUB, ODT and RTF as Markdown with the standard library alone (2026-11-20).

pandoc - pypandoc_binary, 41 MB of --setup's download and 226 MB on disk - reads these three
formats and nothing else here. These readers are the prototype measured against it on 52 files
(2026-11-20), to see whether it can go. They need nothing but the standard library: an
EPUB's XHTML goes through html.parser, which expands no entity a DTD declares; an ODT's XML through
ElementTree, a DOCTYPE refused first; an RTF through a tokenizer of our own.

Each reader returns (markdown, note): note is "" or what it could not do - the time ran out after
chapter 12 of 40, a part over the size limit, XML that breaks somewhere (what came before is kept).
A picture is ![alt](its path in the archive), so readpage's doc_pictures() puts its marker where
the picture stands; a footnote is [^n] where it is called and "[^n]: its text" (an EPUB: where the
book keeps its notes; ODT, RTF: at the end); a table is a Markdown table whose merged cells leave
their other places empty. An archive's part is read up to PART_BYTES and all of them together up
to TOTAL_BYTES unpacked, whatever their headers claim; `until` (a time.time() to stop by, None for
no limit) is checked between chapters and every few hundred elements."""
import codecs
import html
import posixpath
import re
import time
import urllib.parse
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

PART_BYTES = 32 * 1024 * 1024      # one part of an archive, unpacked
TOTAL_BYTES = 128 * 1024 * 1024    # every part one reader takes from one archive
RTF_BYTES = 128 * 1024 * 1024      # an RTF's own bytes (pictures make the big ones)
DEPTH = 100                        # nesting a renderer follows; what is deeper comes as plain text
ROWS = 20000                       # rows of one table


class Late(Exception):
    """The time given to a reader ran out."""


class _Clock(object):
    __slots__ = ("until", "n")

    def __init__(self, until):
        self.until, self.n = until, 0

    def tick(self):
        if self.until is not None:
            self.n += 1
            if not self.n & 255 and time.time() > self.until:
                raise Late()

    def late(self):
        return self.until is not None and time.time() > self.until


def read(path, kind, until=None):
    """(markdown, note) of an EPUB, an ODT or an RTF file; ("", why) when it gives no text."""
    try:
        if kind == "epub":
            return epub_md(path, until)
        if kind == "odt":
            return odt_md(path, until)
        if kind == "rtf":
            with open(path, "rb") as fh:
                data = fh.read(RTF_BYTES + 1)
            md, note = rtf_md(data[:RTF_BYTES], until)
            if len(data) > RTF_BYTES:
                note = _join(note, "the file was read up to %d MB" % (RTF_BYTES >> 20))
            return md, note
    except Late:
        return "", "the time ran out"
    except zipfile.BadZipFile as e:
        return "", "not a whole archive (%s): the file is cut or damaged" % str(e)[:80]
    except Exception as e:                                     # noqa: BLE001
        return "", "the reader failed: %s: %s" % (type(e).__name__, str(e)[:120])
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
_PIC = r"!\[(?:\\.|[^\]\\\n])*\]\([^)\s]*\)"


def _space(s):
    return _WS.sub(" ", s)


def _one_line(s):
    return re.sub(r"\s*\n\s*", " ", s).strip()


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
    """Inline text as a paragraph: _lines(), a line Markdown would take for a heading, a list item
    or a setext underline escaped, a picture kept apart from the words around it."""
    return _escape(_lines(s))


def _escape(t):
    if not t:
        return ""
    t = re.sub(r"(?m)^(#{1,6})(?=[ \t]|$)", r"\\\1", t)
    t = re.sub(r"(?m)^([-+*])(?=[ \t])", r"\\\1", t)
    t = re.sub(r"(?m)^(\d{1,9})([.)])(?=[ \t])", r"\1\\\2", t)
    t = re.sub(r"(?m)^([=-]+)[ \t]*$", r"\\\1", t)
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
_MERGE = re.compile("\x0e/([*~]+)\x0f\x0e\\1\x0f")
_MARK = re.compile("\x0e/?([*~]+)\x0f")


def _marks(t):
    if "\x0e" not in t:
        return t
    prev = None
    while prev != t:
        prev, t = t, _MERGE.sub("", t)
    return _MARK.sub(r"\1", t)


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
    """[text](href) for an address outside the document; its words alone for one inside it."""
    core = text.strip()
    href = (href or "").strip()
    if not core or not _EXTERNAL.match(href) or "![" in core:
        return text
    i = len(text) - len(text.lstrip())
    j = len(text.rstrip())
    if re.search(r"[\s()<>]", href):
        href = "<%s>" % re.sub(r"\s+", "%20", href).replace("<", "%3C").replace(">", "%3E")
    core = _one_line(core).replace("[", "\\[").replace("]", "\\]")
    return text[:i] + "[%s](%s)" % (core, href) + text[j:]


def _pic(alt, path):
    """![alt](path): the path of a picture inside the archive, percent-encoded so the picture
    pass (pictures.IMG_LINK) takes it whole; doc_pictures() decodes it to find the file."""
    if not path:
        return ""
    alt = _one_line(alt or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    if _EXTERNAL.match(path):
        return "![%s](%s)" % (alt, re.sub(r"[\s()<>]", lambda m: "%%%02X" % ord(m.group(0)), path))
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


def md_table(rows):
    """Rows of cell texts as a Markdown table, the first row its head; None when fewer than two
    columns have text (such rows read better as paragraphs), "" when nothing is left."""
    rows = [[_one_line(c or "").replace("|", "\\|") for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    if len(keep) < 2:
        return None
    rows = [[r[j] for j in keep] for r in rows]
    line = lambda r: "| " + " | ".join(r) + " |"                    # noqa: E731
    return "\n".join([line(rows[0]), "|" + " --- |" * len(keep)] + [line(r) for r in rows[1:]])


def _table_blocks(rows):
    md = md_table(rows)
    if md is None:                     # one column: its cells as paragraphs
        return [p for p in (_para(c) for r in rows for c in r) if p]
    return [md] if md else []


# ---------------------------------------------------------------- archives

class _Zip(object):
    """An archive's parts, each read up to its limit and all of them up to TOTAL_BYTES; what was
    cut or could not be read is named in `cut` and `bad`."""

    def __init__(self, z):
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

    def note(self):
        out = []
        if self.cut:
            out.append("%d part(s) over the size limit read in part or not at all (%s)"
                       % (len(self.cut), ", ".join(self.cut[:3])))
        if self.bad:
            out.append("%d part(s) could not be unpacked (%s)" % (len(self.bad), ", ".join(self.bad[:3])))
        return "; ".join(out)


def _decode(data):
    """An XML or HTML part as text: its BOM, its XML declaration, its meta charset, else UTF-8."""
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", "replace")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    head = data[:2048]
    m = re.match(rb"""\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._:-]+)""", head) or \
        re.search(rb"""(?i)<meta\b[^>]*?charset\s*=\s*["']?([A-Za-z0-9._:-]+)""", head)
    enc = m.group(1).decode("ascii") if m else "utf-8"
    try:
        return data.decode(enc)
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", "replace")


_ATTR = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _attrs(tag):
    return {k.lower(): html.unescape(a or b) for k, a, b in _ATTR.findall(tag)}


_PROLOG = re.compile(rb"\s*(?:<\?.*?\?>|<!--.*?-->)", re.S)


def _xml(data, clock):
    """ElementTree of an XML part: (root, why). XML that breaks somewhere gives what came before
    that point and says so; a DOCTYPE is refused - no OpenDocument file has one, and its entities
    are the way to a billion laughs on a Python whose expat has no limit of its own."""
    if not data:
        return None, "it is empty"
    pos = 0
    while True:
        m = _PROLOG.match(data, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
    if data[pos:pos + 9].lstrip()[:9] == b"<!DOCTYPE":
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


NODES = 500000                     # elements of one part (a part that unpacks to 1 GB of <p>a</p>
                                   # built 4 million of them, 2 GB, 2026-11-20)


class _Tree(HTMLParser):
    """XHTML (or tag soup) as a tree of _El; the HTML rules that close a <p> or an <li> nobody
    closed, so a sloppy EPUB 2 book still nests the way a browser would show it. Which tags are
    open is counted, so a rule or an end tag looks down the stack only for a tag that is there
    (200 000 nested <div> looked down the whole stack at each tag: hours); the clock is read
    every 4096 elements, and the tree stops at NODES."""

    def __init__(self, clock):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = _El("#root", {})
        self.stack, self.open, self.clock, self.nodes = [self.root], {}, clock, 0

    def _pop(self, k):
        for el in self.stack[k:]:
            self.open[el.tag] -= 1
        del self.stack[k:]

    def _close(self, names, stop):
        if not any(self.open.get(n) for n in names):
            return
        for k in range(len(self.stack) - 1, 0, -1):
            t = self.stack[k].tag
            if t in names:
                self._pop(k)
                return
            if t in stop:
                return

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
        el = _El(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].kids.append(el)
        if not empty and tag not in _VOID:
            self.stack.append(el)
            self.open[tag] = self.open.get(tag, 0) + 1

    def handle_endtag(self, tag):
        tag = tag.rsplit(":", 1)[-1]
        if not self.open.get(tag):
            return                                     # nothing of the kind is open: a stray end tag
        for k in range(len(self.stack) - 1, 0, -1):
            if self.stack[k].tag == tag:
                self._pop(k)
                return

    def handle_data(self, data):
        kids = self.stack[-1].kids
        if kids and isinstance(kids[-1], str):
            kids[-1] += data
        else:
            kids.append(data)


def _html_tree(text, clock):
    """(root, whole): whole is False when the part had more than NODES elements and the tree
    holds the ones before."""
    t = _Tree(clock)
    try:
        for i in range(0, len(text), 1 << 16):
            t.feed(text[i:i + (1 << 16)])
            if clock.late():
                raise Late()
        t.close()
    except _Full:
        return t.root, False
    return t.root, True


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


_NOTEREF = re.compile(r"""(?is)<a\b[^>]*?\b(?:epub:type|role)\s*=\s*["'][^"']*noteref[^"']*["'][^>]*>""")
_HREF = re.compile(r"""(?is)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""")


class _Book(object):
    """What the parts of one book share: the notes it calls by epub:type or role "noteref", each
    with its number in the order the book first calls it; which of them got their text; what the
    book showed at each call (put back where a note's text was never found)."""

    def __init__(self):
        self.notes, self.defined, self.refs = {}, set(), {}

    def scan(self, doc, text):
        for m in _NOTEREF.finditer(text):
            h = _HREF.search(m.group(0))
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

    # -- blocks
    def blocks(self, el, depth=0):
        if depth > DEPTH:
            t = _para(_space(_text(el)))
            return [t] if t else []
        out, run = [], []

        def flush():
            if run:
                p = _para("".join(run))
                del run[:]
                if p:
                    out.append(p)
        for k in el.kids:
            if isinstance(k, str):
                run.append(_space(k))
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
        ordered = el.tag == "ol"
        n = _int(el.attrs.get("start"), 1)
        items, out = [], []

        def close():
            if items:
                out.append(_list(items))
                del items[:]
        for k in el.kids:
            if isinstance(k, str):
                s = _para(_space(k))
                if s:
                    if items:
                        items[-1][1].append(s)
                    else:
                        out.append(s)
                continue
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
                s = _para(_space(k))
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
        caption, rows = [], []

        def walk(x):
            for k in x.kids:
                if isinstance(k, str) or k.tag in _SKIP:
                    continue
                if k.tag == "caption":
                    c = _para(self.inline(k, depth + 1))
                    if c:
                        caption.append(c)
                elif k.tag == "tr":
                    rows.append(k)
                elif k.tag not in ("colgroup", "col", "table", "td", "th"):
                    walk(k)                    # thead, tbody, tfoot, or a form around the rows
        walk(el)
        grid, spans, cells = [], set(), []
        for r, tr in enumerate(rows[:ROWS]):
            line, col = [], 0
            for c in tr.kids:
                if isinstance(c, str) or c.tag not in ("td", "th"):
                    continue
                cells.append(c)
                while (r, col) in spans:
                    line.append("")
                    col += 1
                line.append(_one_line(self.inline(c, depth + 1)))
                cs = min(max(_int(c.attrs.get("colspan"), 1), 1), 64)
                rs = min(max(_int(c.attrs.get("rowspan"), 1), 1), 512)
                line.extend([""] * (cs - 1))
                for dr in range(1, rs):
                    for dc in range(cs):
                        spans.add((r + dr, col + dc))
                col += cs
            while (r, col) in spans:
                line.append("")
                col += 1
            grid.append(line)
        if md_table(grid) is None:
            # one column: a table that lays a page out (a title page in a cell); its cells as the
            # blocks they hold, headings and all
            return caption + [b for c in cells for b in self.blocks(c, depth + 1)]
        return caption + _table_blocks(grid)

    # -- inline
    def inline(self, el, depth):
        parts = []
        for k in el.kids:
            parts.append(_space(k) if isinstance(k, str) else self.inline_el(k, depth + 1))
        return "".join(parts)

    def inline_el(self, el, depth):
        self.clock.tick()
        t, a = el.tag, el.attrs
        if t in _SKIP or "hidden" in a or id(el) in self.skip:
            return ""
        if depth > DEPTH:
            return _space(_text(el))
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
            return " %s " % m if m else ""
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


def _epub_parts(zf):
    """The book's reading order: [(path, media type)], the navigation document left out (it
    repeats the headings as links). No package document: every (X)HTML part by name."""
    opf_path = None
    c = zf.read("META-INF/container.xml", 1 << 20)
    if c:
        for tag in re.findall(r"(?is)<rootfile\b[^>]*>", _decode(c)):
            a = _attrs(tag)
            if a.get("full-path") and (not a.get("media-type") or "oebps-package" in a.get("media-type", "")):
                opf_path = a["full-path"]
                break
    if not opf_path:
        opf_path = next((n for n in zf.names if n.lower().endswith(".opf")), None)
    opf = zf.read(opf_path, 16 << 20) if opf_path else None
    parts = []
    if opf:
        t, base = _decode(opf), posixpath.dirname(opf_path.lstrip("/"))
        items = {}
        for tag in re.findall(r"(?is)<(?:\w+:)?item\b[^>]*>", t):
            a = _attrs(tag)
            if a.get("id") and a.get("href"):
                path = posixpath.normpath(posixpath.join(base, urllib.parse.unquote(a["href"].split("#")[0])))
                items[a["id"]] = (path, a.get("media-type", "").lower(), a.get("properties", "").lower().split())
        for tag in re.findall(r"(?is)<(?:\w+:)?itemref\b[^>]*>", t):
            it = items.get(_attrs(tag).get("idref"))
            if it and "nav" not in it[2] and (it[0], it[1]) not in parts:
                parts.append((it[0], it[1]))
    if not parts:
        parts = [(n, "") for n in sorted(zf.names) if re.search(r"(?i)\.x?html?$", n)]
    return parts


def epub_md(path, until=None):
    """An EPUB 2 or 3 as Markdown: its spine in order, each part's XHTML as blocks."""
    clock = _Clock(until)
    with zipfile.ZipFile(path) as z:
        zf = _Zip(z)
        parts = _epub_parts(zf)
        book, texts = _Book(), []
        for doc, media in parts:
            if "svg" in media or doc.lower().endswith(".svg"):
                texts.append((doc, None))
                continue
            data = zf.read(doc)
            if data is None:
                continue
            t = _decode(data)
            texts.append((doc, t))
            book.scan(doc, t)
        out, done, late, big = [], 0, False, []
        for i, (doc, t) in enumerate(texts):
            if clock.late():
                late = True
                break
            if t is None:
                out.append(_pic("", doc))       # a page that is a picture (a cover in SVG)
                done += 1
                continue
            try:
                root, whole = _html_tree(t, clock)
                if not whole:
                    big.append(doc)
                blocks = _Html(doc, book, clock).blocks(_find(root, "body") or root)
            except Late:
                late = True
                break
            texts[i] = (doc, None)
            out.append("\n\n".join(b for b in blocks if b))
            done += 1
        md = _marks("\n\n".join(o for o in out if o.strip()))
        dangling = {lab for lab in book.refs if lab not in book.defined}
        if dangling:                    # a call whose note was never found: what the book showed there
            md = re.sub(r"\[\^(\d+)\]", lambda m: book.refs.get(m.group(1), "") if m.group(1) in dangling
                        else m.group(0), md)
        note = zf.note()
        if big:
            note = _join("%d part(s) read up to their first %d elements (%s)" % (len(big), NODES, ", ".join(big[:3])),
                         note)
        if late:
            note = _join("the time ran out: %d of the book's %d parts read; --download reads it whole"
                         % (done, len(texts)), note)
        return md, note


# ---------------------------------------------------------------- ODT

_ODF = {"office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
        "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
        "xlink": "http://www.w3.org/1999/xlink",
        "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"}


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


class _OdfStyles(object):
    """What the styles say: a paragraph style's outline level (a heading), bold and italic of
    paragraph and text styles through their parents, which list styles number their levels, and
    which fonts are of fixed pitch (code)."""

    def __init__(self):
        self.st, self.lists, self.fixed = {}, {}, set()

    def load(self, root):
        if root is None:
            return
        for box in root:
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
    """The body of an OpenDocument text as Markdown blocks; notes at the end."""

    def __init__(self, styles, clock, zf=None):
        self.s, self.clock, self.zf = styles, clock, zf
        self.notes = []                   # [(label, blocks)]
        self.counts = {}                  # (list style, level) -> the last number it gave

    def doc(self, root):
        body = root.find(_o("office:body"))
        text = body.find(_o("office:text")) if body is not None else None
        if text is None:
            return "", False
        out, late = [], False
        try:
            for ch in text:
                out.extend(self.blocks_of([ch], 1))
        except Late:
            late = True
        md = "\n\n".join(b for b in out if b)
        notes = [d for d in (_note_def(lab, blocks) for lab, blocks in self.notes) if d]
        if notes:
            md = md + "\n\n" + "\n\n".join(notes)
        return _marks(md), late

    def blocks_of(self, els, depth):
        out, code = [], []

        def flush_code():
            if code:
                f = _fence("\n".join(code))
                del code[:]
                if f:
                    out.append(f)
        for ch in els:
            self.clock.tick()
            tag = ch.tag
            if depth > DEPTH:
                t = _para(_space("".join(ch.itertext())))
                if t:
                    out.append(t)
                continue
            if tag in (O_P, O_H):
                pend = []
                kind, text = self.para(ch, pend, depth)
                if kind == "code":
                    code.append(text)
                    continue
                flush_code()
                if text:
                    out.append(text)
                out.extend(pend)
                continue
            flush_code()
            if tag == O_LIST:
                out.extend(self.list(ch, 0, None, depth + 1))
            elif tag == O_TABLE:
                out.extend(self.table(ch, depth + 1))
            elif tag.startswith("{%s}" % _DRAW):
                pend = []
                s = _para(self.draw(ch, pend, depth + 1))
                if s:
                    out.append(s)
                out.extend(pend)
            elif tag in _ODF_SKIP:
                continue
            else:                              # a section, an index's body, any other wrapper
                out.extend(self.blocks_of(list(ch), depth + 1))
        flush_code()
        return out

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
        parts = [_space(el.text or "")]
        for ch in el:
            parts.append(self.inline_el(ch, pend, base, depth + 1))
            if ch.tail:
                parts.append(_space(ch.tail))
        return "".join(parts)

    def inline_el(self, ch, pend, base, depth):
        self.clock.tick()
        tag = ch.tag
        if depth > DEPTH:
            return _space("".join(ch.itertext()))
        if tag == O_SPAN:
            st = ch.get(O_STYLE_NAME)
            b, i = self.s.get("text", st, "bold"), self.s.get("text", st, "italic")
            b = base[0] if b is None else b
            i = base[1] if i is None else i
            font = self.s.get("text", st, "font") or base[2]
            inner = self.inline(ch, pend, (b, i, font), depth)
            if font != base[2] and font in self.s.fixed and base[2] not in self.s.fixed:
                return _code(inner)
            if (b and not base[0]) or (i and not base[1]):
                return _bi(inner, b and not base[0], i and not base[1])
            return inner
        if tag == O_S:
            return " " * min(max(_int(ch.get(_o("text:c")), 1), 1), 200)
        if tag == O_TAB:
            return "\t"
        if tag == O_LB:
            return "\n"
        if tag == O_A:
            return _link(self.inline(ch, pend, base, depth), ch.get(O_HREF) or "")
        if tag == O_NOTE:
            label = str(len(self.notes) + 1)
            self.notes.append((label, []))
            body = ch.find(O_NBODY)
            self.notes[int(label) - 1] = (label, self.blocks_of(list(body), depth + 1) if body is not None else [])
            return "[^%s]" % label
        if tag.startswith("{%s}" % _DRAW):
            return self.draw(ch, pend, depth)
        if tag in _ODF_SKIP:
            return ""
        if tag == O_RUBY:
            b, r = ch.find(O_RUBY_BASE), ch.find(O_RUBY_TEXT)
            rb = self.inline(b, pend, base, depth) if b is not None else ""
            rt = _one_line("".join(r.itertext())) if r is not None else ""
            return rb + ("(%s)" % rt if rt else "")
        if ch.get(_o("text:is-hidden")) == "true":
            return ""
        return self.inline(ch, pend, base, depth)

    def draw(self, el, pend, depth):
        """A frame: its picture where it stands; a text box's or a shape's paragraphs after the
        paragraph that holds it."""
        if el.tag == O_DRAW_A:
            return " ".join(p for p in (self.draw(k, pend, depth + 1) for k in el) if p)
        if el.tag != O_FRAME:
            pend.extend(self.blocks_of([k for k in el if k.tag not in _ODF_SKIP], depth + 1))
            return ""
        alt, pic = "", ""
        for k in el:
            if k.tag in (O_TITLE, O_DESC) and not alt:
                alt = _one_line("".join(k.itertext()))
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
        return pic.replace("\x00", "")

    def formula(self, href):
        """An embedded formula (LibreOffice Math) as inline code: its StarMath source, else what
        its MathML says."""
        name = posixpath.normpath(urllib.parse.unquote(re.sub(r"^\./", "", href.strip())))
        data = self.zf.read(name + "/content.xml", 4 << 20) if self.zf is not None and name else None
        root = _xml(data, self.clock)[0] if data else None
        if root is None or not root.tag.endswith("}math"):
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
        out = []
        for it in el:
            for ch in it:
                if ch.tag == O_LIST:
                    out.extend(self.flat(ch, depth + 1))
                else:
                    out.extend(self.blocks_of([ch], depth + 1))
        return out

    def table(self, el, depth):
        rows = []

        def walk(box):
            for r in box:
                if len(rows) >= ROWS:
                    return
                if r.tag in O_ROWS:
                    walk(r)
                elif r.tag == O_ROW:
                    cells = []
                    for c in r:
                        if c.tag in (O_CELL, O_COVERED):
                            rep = min(max(_int(c.get(_o("table:number-columns-repeated")), 1), 1), 64)
                            text = self.cell(c, depth + 1) if c.tag == O_CELL else ""
                            cells.extend([text] * rep)
                    rep = min(max(_int(r.get(_o("table:number-rows-repeated")), 1), 1), 64)
                    rows.extend([cells] * rep)
        walk(el)
        return _table_blocks(rows)

    def cell(self, c, depth):
        parts = []
        for ch in c:
            if ch.tag in (O_P, O_H):
                pend = []
                style = ch.get(O_STYLE_NAME)
                base = (bool(self.s.get("paragraph", style, "bold")), bool(self.s.get("paragraph", style, "italic")),
                        self.s.get("paragraph", style, "font") or "")
                t = _bi(_one_line(self.inline(ch, pend, base, depth)), base[0], base[1])
                parts.append(t)
                parts.extend(_one_line(b) for b in pend)
            elif ch.tag in (O_LIST, O_ITEM, O_LHEAD, O_TABLE, O_ROW, O_CELL) + O_ROWS or \
                    ch.tag == _o("text:section"):
                parts.append(self.cell(ch, depth + 1))
            elif ch.tag not in _ODF_SKIP:
                parts.append(_one_line(_space("".join(ch.itertext()))))
        return " ".join(p for p in parts if p)


def odt_md(path, until=None):
    """An OpenDocument text as Markdown: content.xml's body, with styles.xml for what its styles
    say."""
    clock = _Clock(until)
    with zipfile.ZipFile(path) as z:
        zf = _Zip(z)
        data = zf.read("content.xml")
        if not data:
            return "", _join("no content.xml in this ODT" if data is None else "its content.xml is empty",
                             zf.note())
        root, why = _xml(data, clock)
        if root is None:
            return "", "content.xml could not be read: %s" % why
        styles = _OdfStyles()
        sdata = zf.read("styles.xml", 16 << 20)
        if sdata:
            styles.load(_xml(sdata, clock)[0])
        styles.load(root)
        md, late = _Odt(styles, clock, zf).doc(root)
        note = _join(why, zf.note(), "the time ran out before the end of the document; --download reads it "
                     "whole" if late else "")
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


class _Rtf(object):
    def __init__(self, s, clock):
        self.s, self.clock = s, clock
        self.body = _Sink("body")
        self.st = [self.body, 1, None, False, False, False, False, 0, None, 0, 0, False, self.body, None]
        self.stack = []
        self.fonts, self.styles, self.list_ids, self.lists = {}, {}, {}, {}
        self.ansi, self.deff = "cp1252", None
        self.pend, self.skip_uc, self.high = bytearray(), 0, 0
        self.notes, self.counters = [], {}
        self.cellx, self.trleft = [], 0                  # the row definition: its cells' right borders
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

    def skip_to_end(self, pos):
        """From inside a group, the position after its closing brace (\\binN data jumped over)."""
        depth, s, search = 1, self.s, _RTF_SKIPPER.search
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
            return self.skip_to_end(pos)
        m = _RTF_DEST.match(self.s, pos)
        if not m:
            return pos
        name, star = m.group(1), self.s.startswith("\\*", pos)
        if name in _RTF_IGNORE or (star and name not in _RTF_KEEP):
            end = self.skip_to_end(m.end())
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
            runs[-1][0].append(t)
        else:
            runs.append([[t], key])

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
            self.emit(chr(n) if not 0xD800 <= n < 0xE000 else "\ufffd")
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
            self.cellx.append(_int(arg))
        elif w == "trowd":
            self.cellx, self.trleft = [], 0
        elif w == "trleft":
            self.trleft = _int(arg)
        elif w == "itap":
            st[_TBL] = _int(arg, 1) > 0
        elif w == "s":
            st[_STY] = _int(arg)
        elif w == "outlinelevel":
            st[_OL] = _int(arg, 9)
        elif w == "ls":
            st[_LS] = _int(arg)
        elif w == "ilvl":
            st[_LVL] = _int(arg)
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
        runs, sink.runs = sink.runs, []
        out = []
        for pieces, key in runs:
            t = "".join(pieces)
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
        nums = re.findall(r"\d+", mark or "")
        n = int(nums[-1]) if nums and len(nums[-1]) < 9 else self.counters.get((ls, level), 0) + 1
        self.counters[(ls, level)] = n
        for k in [k for k in self.counters if k[0] == ls and k[1] > level]:
            del self.counters[k]
        return n

    def cell(self):
        sink = self.st[_SINK]
        if sink is None or sink.kind not in ("body", "note"):
            return
        text = self.runs_md(sink)
        if text:
            sink.cell.append(text)
        sink.row.append(" ".join(sink.cell))
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
            sink.rows.append((sink.row, list(self.cellx), self.trleft))
            sink.row = []

    def end_table(self, sink):
        if sink.cell or sink.row:
            if sink.cell:
                sink.row.append(" ".join(sink.cell))
                sink.cell = []
            sink.rows.append((sink.row, list(self.cellx), self.trleft))
            sink.row = []
        if sink.rows:
            sink.blocks.append(("t", _rtf_grid(sink.rows)))
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
        text = "".join("".join(p) for p, _k in sink.runs[i:])
        if url and text.strip():
            del sink.runs[i:]
            sink.runs.append([[_link(text, url.group(1))], ("link",)])

    def finish(self):
        self.flush()
        body = self.body
        text = self.runs_md(body)
        if text:
            body.blocks.append(("p", _escape(text)))
        self.end_table(body)
        md = _flat_md(body.blocks)
        notes, empty = [], set()
        for label, note in self.notes:
            d = _note_def(label, [_flat_md(note.blocks)])
            if d:
                notes.append(d)
            else:
                empty.add(label)
        if empty:                                        # a note with no text: no call either
            md = re.sub(r"\[\^(\d+)\]", lambda m: "" if m.group(1) in empty else m.group(0), md)
        return _marks(md + ("\n\n" + "\n\n".join(notes) if notes else ""))


def _rtf_grid(rows):
    """[(cells, right borders, left edge)] -> rows of cells on the table's columns: a cell whose
    right border (\\cellx) lies past one of the columns other rows have is followed by an empty
    cell for each, as a merged cell is elsewhere. Borders within 15 twips are one column."""
    grid = []
    for e in sorted(set(b for _c, bounds, _l in rows for b in bounds)):
        if not grid or e - grid[-1] > 15:
            grid.append(e)
    out = []
    for cells, bounds, left in rows:
        if not grid or len(bounds) < len(cells):
            out.append(list(cells))
            continue
        line, prev = [""] * sum(1 for g in grid if g <= left + 15), left
        for k, cell in enumerate(cells):
            line.append(cell)
            line.extend([""] * max(0, sum(1 for g in grid if prev + 15 < g <= bounds[k] + 15) - 1))
            prev = bounds[k]
        out.append(line)
    return out


def _flat_md(blocks):
    """The RTF reader's blocks as Markdown; list items nest by their level, each under the text of
    the item above it."""
    out, stack, prev = [], [], False
    for b in blocks:
        if b[0] == "li":
            _k, lvl, marker, text = b
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            col = stack[-1][1] if stack else 0
            item = _indent(text, " " * col + marker, " " * (col + len(marker)))
            if prev:
                out[-1] += "\n" + item
            else:
                out.append(item)
            stack.append((lvl, col + len(marker)))
            prev = True
            continue
        stack, prev = [], False
        if b[0] == "p":
            out.append(b[1])
        elif b[0] == "h":
            out.append(_heading(b[1], b[2]))
        elif b[0] == "t":
            out.extend(_table_blocks(b[1]))
    return "\n\n".join(o for o in out if o)


def rtf_md(data, until=None):
    """An RTF document as Markdown."""
    clock = _Clock(until)
    s = data.decode("latin-1") if isinstance(data, (bytes, bytearray)) else data
    r = _Rtf(s, clock)
    late = False
    try:
        r.run()
    except Late:
        late = True
    if r.ctrl > max(50, (r.chars + r.ctrl) // 100):
        # bytes no writer leaves in text (random data after "{\rtf1" read as 64 708 words of
        # mojibake, 2026-11-20): what is there is not the document's text
        return "", "not text: this RTF holds binary data where its text should be"
    md = r.finish()
    note = ("the time ran out at %d%% of the file; --download reads it whole" % (100 * r.pos // max(1, len(s)))
            if late else "")
    return md, note
