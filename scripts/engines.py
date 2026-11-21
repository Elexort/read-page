"""The Python extractors, light to import: readpage uses them in-process, xchild.py in a process of
its own that the read can stop at its deadline. Nothing heavy is imported at the top:
html2text, readability and trafilatura load on their first call."""
import contextlib
import io
import os
import re
import urllib.parse
from html import unescape as _unescape

# READ_PAGE_SKIP=defuddle,readability,... turns engines off (tests, and a machine where one hangs)
SKIP = set(x.strip() for x in os.environ.get("READ_PAGE_SKIP", "").split(",") if x.strip())

TRAFILATURA_FAST = False     # True: trafilatura's `fast` mode, which skips its own readability/justext fallback


_OPENERS = {}
_CLOSERS = {}


def drop_blocks(html, tags):
    """`html` without the <script>...</script> (and the like) blocks of `tags`, in one pass. The
    regex `<(script|style)[^>]*>.*?</\\1>` scanned to the end of the page for every block without
    its closing tag: 3.9 of the 4.4 s visible_text took on the 16 MB HTML spec. An unclosed block
    loses only its opening tag, as the regex left it."""
    key = tuple(tags)
    if key not in _OPENERS:
        _OPENERS[key] = re.compile(r"(?i)<(%s)\b" % "|".join(tags))
    out, pos, unclosed = [], 0, set()
    for m in _OPENERS[key].finditer(html):
        if m.start() < pos:
            continue
        tag = m.group(1).lower()
        end = None
        if tag not in unclosed:
            if tag not in _CLOSERS:
                _CLOSERS[tag] = re.compile(r"(?i)</%s\s*>" % tag)
            c = _CLOSERS[tag].search(html, m.end())
            if c:
                end = c.end()
            else:
                unclosed.add(tag)              # no closer later on: never look again
        if end is None:
            gt = html.find(">", m.end())
            end = gt + 1 if gt >= 0 else len(html)
        out.append(html[pos:m.start()])
        out.append(" ")
        pos = end
    out.append(html[pos:])
    return "".join(out)


def visible_text(html):
    """The readable text of a page, tags and scripts gone (used for the cover ratio)."""
    h = drop_blocks(html or "", ("script", "style", "noscript"))
    h = re.sub(r"(?s)<!--.*?-->", " ", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;?", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def visible_len(html):
    return len(visible_text(html))


def crude_text(html):
    """stdlib-only: block tags to newlines, everything else to spaces. Never fails."""
    import html as _html
    h = drop_blocks(html, ("script", "style", "noscript", "template", "svg"))
    h = re.sub(r"(?is)<!--.*?-->", " ", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article|blockquote|pre|table)>", "\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = _html.unescape(h)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in h.splitlines()]
    return "\n".join(ln for ln in lines if ln)


_BASE_TAG = re.compile(r"(?is)<base\b[^>]*>")
_HREF = re.compile(r"""(?is)\bhref\s*=\s*["']([^"']*)""")


def page_base(html, url):
    """What a browser resolves the page's relative addresses against: <base href>, else the URL."""
    m = _BASE_TAG.search(html or "")
    h = _HREF.search(m.group(0)) if m else None
    if h and _unescape(h.group(1)).strip():
        return urllib.parse.urljoin(url or "", _unescape(h.group(1)).strip())
    return url or ""


def html2text_full(html, vis=None, base=""):
    """page.md: html2text when it works, crude_text when the page defeats it. Pictures stay in
    (page.md is the whole page, its pictures included), and nothing is wrapped: a
    wrapped line could split a picture's link in two. `vis` is the visible length, when known.
    `base` (page_base) makes every link a whole address, as in content.md: page.md's were
    relative, and an agent had to join them itself (gov.uk)."""
    out = ""
    if "html2text" in SKIP:
        return crude_text(html)
    try:
        import html2text
        h = html2text.HTML2Text()
        h.body_width = 0
        h.baseurl = base or ""
        out = h.handle(html)
        out = re.sub(r"\n{3,}", "\n\n", out)
    except Exception:                                         # noqa: BLE001
        out = ""
    vis = visible_len(html) if vis is None else vis
    if not out.strip() or (vis and len(out) < vis * 0.5):
        alt = crude_text(html)
        if len(alt) > len(out):
            return alt
    return out


def readability_text(html, url=""):
    """readability-lxml, when installed: light and better than a tag strip."""
    if "readability" in SKIP:
        return ""
    try:
        from readability import Document
        import html2text as _h2t
        with contextlib.redirect_stderr(io.StringIO()):
            # readability prints a traceback to stderr for an empty document; the caller only
            # wants "" in that case, and a traceback in the agent's log looks like a crash
            summary = Document(html).summary()
        # unwrapped, as html2text_full: the default 78 columns split a picture's alt and address
        # over lines, and the picture stayed a raw link with a broken address (Le Monde)
        h = _h2t.HTML2Text()
        h.body_width = 0
        h.baseurl = page_base(html, url)
        return h.handle(summary).strip()
    except Exception:                                         # noqa: BLE001
        return ""


def trafilatura_text(html, url, fast=None):
    if "trafilatura" in SKIP:
        return ""
    try:
        import trafilatura
        # include_images: a picture stands where the page has it
        kw = {"fast": True} if (TRAFILATURA_FAST if fast is None else fast) else {}
        try:
            return trafilatura.extract(html, output_format="markdown", include_links=False,
                                       include_tables=True, include_images=True, url=url, **kw) or ""
        except TypeError:                                     # an old trafilatura: no `fast`
            return trafilatura.extract(html, output_format="markdown", include_links=False,
                                       include_tables=True, include_images=True, url=url) or ""
    except Exception:                                         # noqa: BLE001
        return ""


RUN = {"readability": lambda html, url: readability_text(html, url),
       "trafilatura": lambda html, url: trafilatura_text(html, url),
       "html2text": lambda html, url: html2text_full(html, base=page_base(html, url)),
       "crude": lambda html, url: crude_text(html)}
