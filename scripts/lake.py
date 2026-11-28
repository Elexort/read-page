"""A document a page holds in a script for its viewer to draw: Lake, the format of Yuque's editor (KNOWN-ISSUES 334).

Aliyun's developer articles (developer.aliyun.com/article/N) keep the article as a Lake document in a JavaScript
string, `GLOBAL_CONFIG.larkContent = '<!doctype lake>...'`, beside an empty `<div id="lark-content">` that the site's
Yuque viewer draws it into. A headless browser whose viewer did not draw it had the site's menus and footer alone
(2026-11-28), and so had the server's HTML, though a user's browser showed the whole article. drawn() puts the
document into that empty element as plain HTML, its cards (code, pictures, tables, rules) the tags they stand for, so
that every extractor and page.md see the page as its viewer shows it. Yuque's own pages fetch their documents with a
request of their own: there is nothing in their HTML to draw.
"""
import collections
import json
import re
import urllib.parse
from html import escape, unescape

_START = re.compile(r"""(['"`])<!doctype lake>""", re.I)
# the element a Lake viewer draws into, still empty: an id or a class that starts with its names (lark, lake)
_HOST = re.compile(r"""(?is)<(div|section|article)\b[^>]*?\b(?:id|class)\s*=\s*["'](?:[^"']*\s)?(?:lark|lake)[\w-]*"""
                   r"""(?:\s[^"']*)?["'][^>]*>\s*</\1\s*>""")
_ESCAPE = re.compile(r"\\(u\{[0-9a-fA-F]{1,6}\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r\n|[\s\S])")
_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
           "\n": "", "\r": "", "\r\n": "", "\u2028": "", "\u2029": ""}
_CARD = re.compile(r"(?is)<card\b([^>]*?)(?:/>|>(.*?)</card\s*>)")
LIMIT = 4 * 1024 * 1024          # characters of a script string: past it the document is not read
_CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯"
_WORDS = re.compile(r"([%s]+)|[^\W_%s]+" % (_CJK, _CJK))
WHOLE = 0.9                      # the share of the document's words a text holds to be the whole document


def _js_unescape(s):
    """A JavaScript string literal's value from its source: \\n, \\uXXXX, \\u{...}, \\xXX, a line continuation, and
    any other escaped character as itself; a surrogate pair written as two \\u escapes becomes its character."""
    def one(m):
        e = m.group(1)
        if e[:2] == "u{":
            return chr(min(int(e[2:-1], 16), 0x10FFFF))
        if e[0] in "ux" and len(e) > 1:
            return chr(int(e[1:], 16))
        return _SIMPLE.get(e, e)
    out = _ESCAPE.sub(one, s)
    return out.encode("utf-16", "surrogatepass").decode("utf-16", "replace") if re.search(r"[\ud800-\udfff]", out) \
        else out


def _string_at(html, quote, start):
    """The source of the string literal that opens with `quote` just before `start`, up to its closing quote: None
    when it does not close, or runs past LIMIT."""
    stop = re.compile(r"\\[\s\S]|" + re.escape(quote))
    for m in stop.finditer(html, start, min(len(html), start + LIMIT)):
        if m.group(0) == quote:
            return html[start:m.start()]
    return None


def document(html, m=None):
    """The Lake document a page's script holds, as Lake's own HTML with the escapes undone; "" when it holds none."""
    m = m or _START.search(html or "")
    if not m:
        return ""
    src = _string_at(html, m.group(1), m.start() + 1)
    return _js_unescape(src) if src else ""


def _value(attrs):
    v = re.search(r"""\bvalue\s*=\s*(["'])(.*?)\1""", attrs, re.S)
    data = unescape(v.group(2)) if v else ""
    if data.startswith("data:"):
        data = data[5:]
    try:
        got = json.loads(urllib.parse.unquote(data))
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _card(m):
    attrs = m.group(1) or ""
    name = (re.search(r"""\bname\s*=\s*["']([^"']*)""", attrs) or [None, ""])[1].lower()
    inline = bool(re.search(r"""\btype\s*=\s*["']inline""", attrs))
    v = _value(attrs)
    if name == "hr":
        return "<hr>"
    if name == "image" or (v.get("src") and re.search(r"(?i)\.(png|jpe?g|gif|webp|svg|bmp|avif)(\?|$)",
                                                       str(v.get("src")))):
        alt = v.get("title") or v.get("name") or v.get("alt") or ""
        return '<img src="%s" alt="%s">' % (escape(str(v.get("src") or ""), True), escape(str(alt), True)) \
            if v.get("src") else ""
    if isinstance(v.get("html"), str):
        return to_html(v["html"])                               # a table's cells may hold cards of their own
    if isinstance(v.get("code"), str):
        lang = re.sub(r"[^\w+#.-]", "", str(v.get("mode") or ""))
        attr = ' class="language-%s"' % lang if lang and lang.lower() not in ("plain", "text", "plaintext") else ""
        return ("<code>%s</code>" % escape(v["code"])) if inline else (
            "<pre><code%s>%s</code></pre>" % (attr, escape(v["code"])))
    if v.get("src"):
        label = v.get("name") or v.get("title") or v.get("src")
        return '<a href="%s">%s</a>' % (escape(str(v["src"]), True), escape(str(label)))
    return m.group(2) or ""


def to_html(lake):
    """Lake's HTML as plain HTML: its doctype and meta tags out, each card the tag it stands for (a code block, a
    picture, a table's own HTML, a rule, a file's link); a card of another kind keeps only what it holds."""
    lake = re.sub(r"(?is)<!doctype lake>|<meta\b[^>]*>", "", lake or "")
    return _CARD.sub(_card, lake)


def drawn(html, doc_from=None):
    """(html, drawn): the page with the Lake document its script holds put into the empty element its viewer draws
    into. `doc_from` is the HTML that holds the script when `html` is a copy without it (the browser's visible DOM).
    A page with no such document, or no such empty element, is returned as it is."""
    src = html if doc_from is None else doc_from
    start = _START.search(src or "") if html else None
    if not start:
        return html, False
    host = _HOST.search(html)
    if not host:
        return html, False
    body = to_html(document(src, start))
    if not re.sub(r"(?s)<[^>]*>|\s", "", body):
        return html, False
    close = host.group(0).rindex("<")
    at = host.start() + close
    return html[:at] + body + html[at:], True


def _bag(text):
    """The words of a text to compare: a run of Chinese, Japanese or Korean as its pairs of characters (no space
    parts their words, and one character is common to any two texts), any other word in lower case."""
    bag = collections.Counter()
    for m in _WORDS.finditer(text or ""):
        w = m.group(0)
        if m.group(1):
            bag.update([w] if len(w) == 1 else [w[i:i + 2] for i in range(len(w) - 1)])
        else:
            bag[w.lower()] += 1
    return bag


def held(html, text):
    """The share of the words of the Lake document a page's script holds that `text` has, each counted as often as
    the document has it: 1.0 when all of them are there, 0.0 when the page holds no document."""
    doc = _bag(unescape(re.sub(r"(?s)<[^>]+>", " ", to_html(document(html)))))
    total = sum(doc.values())
    if not total:
        return 0.0
    have = _bag(text)
    return sum(min(n, have[w]) for w, n in doc.items()) / float(total)
