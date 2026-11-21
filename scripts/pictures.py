"""Pictures: every picture the printed text shows becomes a numbered
marker in its place, its file sits in the page's own img/ folder, and a picture another page of
the same site already downloaded comes from that page's folder by a hard link, not the network.

    refs = pictures.refs(text, base)          # [(url, alt)], in the order they first appear
    text = pictures.mark(text, base, by_url)  # ![alt](url) -> [img #3 · 100x80 3K · alt] img/03-alt.png
    lines = pictures.compact(lines)           # one answer: a repeat is [img #3], a tiny one its alt

The number is the file's number, the alt stays inside the brackets, the path comes last. A picture
that was not downloaded says why and keeps its address. This module holds no network code: the
fetching (cookies, redirect checks, Referer) stays in readpage.py. Standard library only.
"""
import glob
import json
import os
import re
import shutil
import unicodedata
import urllib.parse

# ![alt](src) and ![alt](<src> "title"); a code fence is code, not a picture. An alt may carry
# escaped brackets - trafilatura writes `![Rack \[File: AP\]](...)` - and those links were left raw
IMG_LINK = re.compile(r"!\[((?:\\.|[^\]\\\n])*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"\n]*\")?\s*\)")
FENCE = re.compile(r"(?m)^\s*(```|~~~)")
MARK = re.compile(r"\[img #(\d+)((?: · [^\]\n]*)?)\](?: (\S+))?")
TINY_SIDE = 48          # px: a repeat this small with a short alt is printed as its alt
TINY_ALT = 16           # characters
LIST_LINES = 10         # pictures with no place in the text: this many lines, then a count
LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-lazy", "data-url", "data-hi-res-src")
PLACEHOLDER = re.compile(r"(?i)^data:|(blank|spacer|placeholder|lazy|pixel|transparent|loading|grey|gray)"
                         r"[\w-]*\.(gif|png|svg|jpg)(\?|$)")
CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r",
                "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))
EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico", ".tif", ".tiff")


def _outside_code(md):
    """(start, end) spans of `md` that are not inside a fenced code block."""
    spans, pos, fence = [], 0, False
    for m in FENCE.finditer(md or ""):
        if not fence:
            spans.append((pos, m.start()))
        else:
            pos = m.end()
        fence = not fence
        if not fence:
            pos = (md or "").find("\n", m.end())
            pos = len(md) if pos < 0 else pos
    if not fence:
        spans.append((pos, len(md or "")))
    return spans


def links(md):
    """Every picture link outside code: (start, end, alt, src)."""
    out = []
    for a, b in _outside_code(md or ""):
        for m in IMG_LINK.finditer(md, a, b):
            out.append((m.start(), m.end(), m.group(1), m.group(2)))
    return out


def resolve(src, base):
    src = (src or "").strip()
    if src.startswith("data:") or not base:
        return src
    return urllib.parse.urljoin(base, src)


def refs(md, base=""):
    """The pictures of a text in the order they first appear: [(url, alt)], each url once."""
    out, seen = [], set()
    for _a, _b, alt, src in links(md):
        url = resolve(src, base)
        if url and url not in seen:
            seen.add(url)
            out.append((url, alt))
    return out


def slug(s, n=30):
    """Short Latin words for a file name: Cyrillic transliterated, accents dropped."""
    s = "".join(CYR.get(ch, CYR.get(ch.lower(), ch)) for ch in (s or ""))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > n:
        s = s[:n].rsplit("-", 1)[0] if "-" in s[:n] else s[:n]
    return s.strip("-")


def ext_of(url, ct=""):
    path = urllib.parse.urlparse(url or "").path
    ext = os.path.splitext(path)[1].lower()
    if ext in EXTS:
        return ".jpg" if ext == ".jpeg" else ext
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
            "image/svg+xml": ".svg", "image/avif": ".avif", "image/bmp": ".bmp",
            "image/x-icon": ".ico"}.get((ct or "").split(";")[0].strip().lower(), ".png")


def file_name(n, alt, url, ext):
    """img/03-express-logo.png: the number, then words from the alt, the address or "image"."""
    stem = ""
    if not (url or "").startswith("data:"):
        stem = os.path.splitext(os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url or "").path)))[0]
    words = slug(alt) or slug(stem) or "image"
    return "img/%02d-%s%s" % (n, words, ext)


def clean_alt(alt, n=60):
    a = re.sub(r"\\([\[\]\\*_`()])", r"\1", alt or "")          # markdown's escapes: "\[File\]" is "[File]"
    a = re.sub(r"\s+", " ", a.replace("[", "(").replace("]", ")")).strip()
    if len(a) > n:
        a = a[:n].rsplit(" ", 1)[0] + "…"
    return a


def size(n):
    if n >= 1024 * 1024:
        v = n / 1048576.0
        return ("%.1fM" % v) if v < 10 else ("%dM" % round(v))
    if n >= 1024:
        return "%dK" % (n // 1024)
    return "%dB" % n


def marker(e):
    """The marker of one picture. On disk: `[img #3 · 100x80 3K · alt] img/03-alt.png`. Not on
    disk: `[img #3 · alt · not downloaded: 404] https://...` - the address stays, so it can be
    fetched another way."""
    parts = ["img #%d" % e["n"]]
    alt = clean_alt(e.get("alt"))
    if e.get("file"):
        dims = e.get("dims") if e.get("dims") and e.get("dims") != "?" else ""
        parts.append(("%s %s" % (dims, size(e.get("bytes") or 0))).strip())
        if alt:
            parts.append(alt)
        return "[%s] %s" % (" · ".join(parts), e["file"])
    if alt:
        parts.append(alt)
    parts.append("not downloaded" + (": " + e["why"] if e.get("why") else ""))
    url = e.get("url") or ""
    if url.startswith("data:"):
        url = "(an inline picture)"
    elif e.get("why") == "not printed yet" or len(url) > 300:
        # a picture whose lines were not printed yet keeps only its file name here (the manifest
        # has the address): a long page's markers would otherwise fill the answer's window
        url = re.sub(r"\s+", "_", urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))) or url[:60]
    return "[%s] %s" % (" · ".join(parts), url)


LINKED = re.compile(r"\[\s*(!\[(?:\\.|[^\]\\\n])*\]\(\s*<?[^)\s>]+>?(?:\s+\"[^\"\n]*\")?\s*\))\s*\]\(\s*<?([^)\s>]+)>?"
                    r"(?:\s+\"[^\"\n]*\")?\s*\)")


def mark(md, base, by_url, drop=()):
    """Every picture link whose picture has an entry becomes its marker; a link in `drop` (a
    tracking pixel, a spacer) is removed; any other link stays as it is. The marker's path is its
    last word and ends clean: a picture inside a link is `marker (link)`, a word glued to it starts
    a new line, a table's `|` gets a space."""
    def unwrap(m):
        inner = IMG_LINK.match(m.group(1))
        url = resolve(inner.group(2), base) if inner else ""
        if url in drop:
            return ""
        return m.group(1) + " (" + m.group(2) + ")" if url in by_url else m.group(0)

    md = LINKED.sub(unwrap, md or "")
    out, pos = [], 0
    for a, b, _alt, src in links(md):
        url = resolve(src, base)
        e = by_url.get(url)
        if url in drop:
            out += [md[pos:a]]
        elif e:
            nxt = md[b] if b < len(md) else " "
            # a converter may glue a caption to the picture (`![x](a.png)The rack`)
            tail = "\n" if (nxt.isalnum() or nxt in "![") else ("" if nxt.isspace() or nxt in ".,;:)" else " ")
            out += [md[pos:a], marker(e), tail]
        else:
            continue
        pos = b
    out.append(md[pos:])
    return "".join(out)


def unplaced_list(entries):
    """Pictures of the shown blocks that found no place in the text (a document's pictures the
    converter does not name): ten lines at most, then where the rest are."""
    if not entries:
        return ""
    lines = ["## Pictures not in the text", ""] + [marker(e) for e in entries[:LIST_LINES]]
    if len(entries) > LIST_LINES:
        lines.append("… and %d more: the `images` list of manifest.json" % (len(entries) - LIST_LINES))
    return "\n".join(lines) + "\n"


def compact(lines):
    """One answer: a picture's first marker is full, a repeat is `[img #N]`, and a
    repeat of a tiny picture with a short alt is the alt itself (`✓`, `:tada:`), as a text browser
    shows it. content.md keeps every marker full; only what is printed is shortened."""
    seen, out = set(), []

    def one(m):
        if not m.group(2):
            return m.group(0)                      # already short
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            return m.group(0)
        parts = [p.strip() for p in m.group(2).split(" · ") if p.strip()]
        dims = re.match(r"(\d+)x(\d+)\b", parts[0]) if parts else None
        alt = parts[1] if len(parts) > 1 and not parts[1].startswith("not downloaded") else ""
        if dims and max(int(dims.group(1)), int(dims.group(2))) <= TINY_SIDE and 0 < len(alt) <= TINY_ALT:
            return alt
        return "[img #%s]" % n

    for line in lines:
        out.append(MARK.sub(one, line) if "[img #" in line else line)
    return out


def real_srcs(html):
    """A lazy picture's real address in its src: `<img src="data:..." data-src="real.png">` is
    real.png for every extractor, and the placeholder never becomes a picture of the page."""
    def fix(m):
        tag = m.group(0)
        src = re.search(r"""(?is)\ssrc\s*=\s*(["'])(.*?)\1""", tag)
        cur = src.group(2).strip() if src else ""
        if cur and not PLACEHOLDER.search(cur):
            return tag
        real = ""
        for attr in LAZY_ATTRS:
            a = re.search(r"""(?is)\s%s\s*=\s*(["'])(.*?)\1""" % re.escape(attr), tag)
            if a and a.group(2).strip() and not a.group(2).strip().startswith("data:"):
                real = a.group(2).strip()
                break
        if not real:
            ss = re.search(r"""(?is)\s(?:data-)?srcset\s*=\s*(["'])(.*?)\1""", tag)
            if ss and ss.group(2).strip():
                real = ss.group(2).split(",")[0].strip().split(" ")[0]
        if not real:
            return tag
        if src:
            return tag[:src.start(2)] + real.replace('"', "%22") + tag[src.end(2):]
        return tag[:4] + ' src="%s"' % real.replace('"', "%22") + tag[4:]
    return re.sub(r"(?is)<img\b[^>]*>", fix, html or "")


def folder_prefix(host):
    """The host part of a page folder's name: neighbours share it."""
    h = (host or "").strip().lower().rstrip(".")
    try:
        h = h.encode("idna").decode("ascii")
    except UnicodeError:
        h = slug(h, 60)
    return re.sub(r"[^a-z0-9.-]", "-", h)[:80] or "local"


def siblings(pages_root, prefix, own_dir):
    """Pictures other pages of the same host already have: {url: absolute file}. Only folders of
    exactly this host (`<host>-` and the 16-character key), only files that still exist."""
    found = {}
    own = os.path.normcase(os.path.abspath(own_dir or ""))
    for d in glob.glob(os.path.join(glob.escape(pages_root), glob.escape(prefix) + "-" + "?" * 16)):
        if os.path.normcase(os.path.abspath(d)) == own or not re.fullmatch(r"[0-9a-f]{16}",
                                                                            os.path.basename(d)[len(prefix) + 1:]):
            continue
        try:
            with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        for e in m.get("images") or []:
            if isinstance(e, dict) and e.get("url") and e.get("file") and e["url"] not in found:
                p = os.path.join(d, e["file"].replace("/", os.sep))
                if os.path.isfile(p):
                    found[e["url"]] = p
    return found


def link_or_copy(src, dst):
    """One copy on disk where the file system allows it (NTFS, ext4); a copy elsewhere (FAT32,
    exFAT, another disk). Returns "link" or "copy"."""
    try:
        os.link(src, dst)
        return "link"
    except OSError:
        shutil.copyfile(src, dst)
        return "copy"
