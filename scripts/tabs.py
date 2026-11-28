"""Tabs, collapsed sections and selects, shown honestly: a marker where the page has each one, with its state.

    import tabs; html, info = tabs.mark(html)            # before the extractors; page=True for page.md

A page shows one tab of a set and folds its other panels or sections away; the extractors read the HTML,
so a hidden panel came into the text with no word of it, or not at all, and the labels went with the
buttons and lists they stand in (defuddle drops every button, label and select, and whatever is marked
hidden). On 34 public pages with tabs, accordions or <details> in their main content (2026-11-26), the
hidden panels the HTML holds were 79-99 % in content.md already on most of them - unlabelled - and some
not at all (Go's examples, Node's history tables); four people's biographies on the ARIA example came with
no name above any; and Groq's rate limits showed the default tab's table under the site's own note that
the limits below are the Developer plan's, with no word of which tab it was.

Every marker has one grammar - its type, its state, what more there is to say, its name last (a picture's
too, pictures.marker: `[img #3 · not downloaded: 404 · alt] https://...`):

    [tab · shown · Free Plan Limits]
    [tab · hidden, but extracted · Developer Plan Limits]       its text follows
    [tab · loads on click, not extracted · Batch Limits]        not in the page
    [tab · hidden, but extracted · 14 KB, too long for here: page.md from line 410 · Go]
    [section · hidden, but extracted · Specifications]          a closed <details>, a collapsed accordion
    [select · chosen: EU · also US, APAC · Region]

The words of the states live here alone (STATE), so they change in one edit. Only the main content is
marked: nothing inside a nav, header, footer, aside, form, dialog or template, or the like by its role. A
tab set is role=tablist with its role=tab and their panels (aria-controls, aria-labelledby, or the
tabpanels in order); a set of links is navigation and stays as it is. A section is a closed <details>, or
a button with aria-expanded and aria-controls whose region the HTML holds as text, not as a list of links
(a responsive menu) - unless the button is a heading's, an accordion's: a list of files there is the page's, and
its text goes to the block rule (`links`). A table whose header cell holds two buttons or more and nothing else has tabs of its
own (Groq's plans). A hidden panel longer than PANEL_LIMIT stays in page.md: the text's marker says where.
Standard library only; a page over MAX_HTML is left as it is.
"""
import hashlib
import re
from html import unescape
from html.parser import HTMLParser

STATE = {"shown": "shown", "hidden": "hidden, but extracted", "missing": "loads on click, not extracted",
         "cut": "lost in the cut"}         # the last: a cut workbook's rows and sheets (readpage._xlsx_cut, docreaders)
TOO_LONG = "%s, too long for here: page.md from line %s"
PANEL_LIMIT = 4096          # bytes of a hidden panel's text; the largest of the 34 pages measured was 3.4 KB
MAX_HTML = 3 * 1024 * 1024  # as readpage.HUGE_HTML: above it no extractor runs
NAME_CHARS = 200           # a tab's label, a summary that is a whole sentence
SELECT_ALSO = 5             # a select's other options named, then how many more

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
# an open element of these ends where the next one of its kind starts (an <li> before an <li>)
SELF_ENDING = {"li": {"li"}, "option": {"option", "optgroup"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"},
               "tr": {"tr"}, "td": {"td", "th", "tr"}, "th": {"td", "th", "tr"}, "p": {"p", "div", "ul", "ol", "table",
                                                                                         "section", "h1", "h2", "h3",
                                                                                         "h4", "h5", "h6", "pre",
                                                                                         "blockquote", "details"}}
OUT_TAGS = {"nav", "header", "footer", "aside", "form", "dialog", "template", "noscript", "select", "button", "svg"}
OUT_ROLES = {"navigation", "banner", "contentinfo", "complementary", "dialog", "alertdialog", "menu", "menubar",
             "search", "toolbar", "listbox", "tree"}
MEDIA = {"img", "picture", "video", "audio", "iframe", "table", "pre", "svg", "canvas"}
ACTIVE = re.compile(r"(?i)^(active|is-active|selected|is-selected|current|checked|on)$")
MARKER = re.compile(r"\\?\[(tab|section|select) · ((?:[^\]\n\\]|\\.)*?)\\?\]")
LINE_TOKEN = re.compile(r"RPTABLINE([0-9a-f]{10})")


class _El(object):
    __slots__ = ("tag", "attrs", "start", "open_end", "end", "parent", "kids")

    def __init__(self, tag, attrs, start, open_end, parent):
        self.tag, self.attrs, self.start, self.open_end, self.end = tag, attrs, start, open_end, None
        self.parent, self.kids = parent, []

    def get(self, name, default=""):
        v = self.attrs.get(name)
        return default if v is None else v


class _Tree(HTMLParser):
    """Every element of the page with its place in the source: start, end of its start tag, end."""

    def __init__(self, html):
        HTMLParser.__init__(self, convert_charrefs=False)
        self.src = html
        self.lines = [0] + [m.end() for m in re.finditer("\n", html)]
        self.els, self.stack, self.ids = [], [], {}
        self.root = _El("#root", {}, 0, 0, None)

    def _at(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def _close(self, el, at):
        el.end = at

    def handle_starttag(self, tag, attrs):
        at = self._at()
        raw = self.get_starttag_text() or ""
        while self.stack and tag in SELF_ENDING.get(self.stack[-1].tag, ()):
            self._close(self.stack.pop(), at)
        parent = self.stack[-1] if self.stack else self.root
        el = _El(tag, dict((k.lower(), v if v is not None else "") for k, v in attrs), at, at + len(raw), parent)
        parent.kids.append(el)
        self.els.append(el)
        if el.attrs.get("id"):
            self.ids.setdefault(el.attrs["id"], el)
        if tag in VOID or raw.endswith("/>"):
            el.end = el.open_end
        else:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1].tag == tag and self.stack[-1].end is None and tag not in VOID:
            el = self.stack.pop()
            el.end = el.open_end

    def handle_endtag(self, tag):
        at = self._at()
        gt = self.src.find(">", at)
        end = gt + 1 if gt >= 0 else len(self.src)
        if not any(e.tag == tag for e in self.stack):
            return                                  # a stray end tag
        while self.stack:
            el = self.stack.pop()
            self._close(el, at if el.tag != tag else end)
            if el.tag == tag:
                break

    def finish(self):
        self.close()
        for el in self.stack:
            el.end = len(self.src)
        self.stack = []


def _tree(html):
    t = _Tree(html)
    try:
        t.feed(html)
        t.finish()
    except Exception:                                  # noqa: BLE001 - a page the parser cannot take is left as it is
        return None
    return t


_TAG = re.compile(r"(?s)<!--.*?-->|<(script|style|template)\b.*?</\1\s*>|<[^>]+>")


def _text(src, el, outer=False):
    """The element's text, tags gone, whitespace folded: what a reader sees in it."""
    if el.end is None:
        return ""
    h = src[el.start:el.end] if outer else src[el.open_end:el.end]
    return re.sub(r"\s+", " ", unescape(_TAG.sub(" ", h))).strip()


def _inner(src, el):
    """The source between the start tag and the end tag."""
    if el.end is None or el.end <= el.open_end:
        return ""
    inner = src[el.open_end:el.end]
    m = re.search(r"(?is)</%s\s*>\s*$" % re.escape(el.tag), inner)
    return inner[:m.start()] if m else inner


def _name(s):
    s = re.sub(r"\s+", " ", (s or "").replace("[", "(").replace("]", ")").replace("·", "-")).strip()
    return s if len(s) <= NAME_CHARS else s[:NAME_CHARS - 1].rstrip() + "…"


def marker(kind, state, name, *props):
    """`[tab · shown · Free Plan Limits]`: the type, the state, what more there is to say, the name last."""
    parts = [kind, STATE.get(state, state)] + [p for p in props if p] + ([_name(name)] if name else [])
    return "[%s]" % " · ".join(parts)


def _escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _human(n):
    return "%d B" % n if n < 1024 else "%.1f KB" % (n / 1024.0) if n < 1024 * 1024 else "%.1f MB" % (n / 1048576.0)


def _out_of_main(el, stop=None):
    """Inside a menu, a header or footer, a form, a dialog: not the main content."""
    p = el.parent
    while p is not None and p is not stop and p.tag != "#root":
        if p.tag in OUT_TAGS or p.get("role").lower() in OUT_ROLES or p.get("aria-modal").lower() == "true":
            return True
        p = p.parent
    return False


def _inside(el, anc):
    p = el.parent
    while p is not None:
        if p is anc:
            return True
        p = p.parent
    return False


def _descendants(el):
    """Every element under el, in the page's order. A stack: taken from a list's head, a section of 80 000 items
    took 11.5 s on a fast machine."""
    out, todo = [], el.kids[::-1]
    while todo:
        k = todo.pop()
        out.append(k)
        todo.extend(k.kids[::-1])
    return out


def _is_link(el):
    p = el
    while p is not None and p.tag != "#root":
        if p.tag == "a" and p.get("href") and not p.get("href").startswith("#") \
                and not p.get("href").lower().startswith("javascript:"):
            return True
        p = p.parent
    return False


def _has_content(src, el):
    if el is None or el.end is None:
        return False
    if _text(src, el):
        return True
    return any(k.tag in MEDIA for k in _descendants(el))


def _link_share(src, el):
    """How much of an element's text is the text of links: a list of links is a menu."""
    words = len(_text(src, el).split())
    if not words:
        return 0.0
    linked = sum(len(_text(src, a).split()) for a in _descendants(el) if a.tag == "a" and a.get("href"))
    return linked / float(words)


def _token(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:10]


class _Edits(object):
    def __init__(self):
        self.rows = []

    def add(self, start, end, new):
        self.rows.append((start, end, new))

    def taken(self, start, end):
        return any(not (end <= a or start >= b) for a, b, _n in self.rows)

    def apply(self, src):
        out, pos = [], 0
        for a, b, new in sorted(self.rows, key=lambda r: (r[0], r[1])):
            if a < pos:
                continue                                 # overlaps an edit before it: left out
            out += [src[pos:a], new]
            pos = b
        out.append(src[pos:])
        return "".join(out)


def _p(text):
    return "<p>%s</p>" % _escape(text)


def _tab_sets(tree, src, page, edits, info):
    ids = tree.ids
    for tl in [e for e in tree.els if e.get("role").lower() == "tablist"]:
        if tl.end is None or _out_of_main(tl) or edits.taken(tl.start, tl.end):
            continue
        tabs = [d for d in _descendants(tl) if d.get("role").lower() == "tab"]
        if len(tabs) < 2 or any(_is_link(t) for t in tabs):
            continue                                     # a set of links is navigation: each tab is a page
        labels = [_text(src, t, outer=True) for t in tabs]
        if not all(labels):
            continue
        # the panels: aria-controls, else aria-labelledby, else the tabpanels near the list in order
        pool, box = [], tl.parent
        for _k in range(4):
            if box is None or box.tag == "#root":
                break
            pool = [d for d in _descendants(box) if d.get("role").lower() == "tabpanel"]
            if pool:
                break
            box = box.parent
        panels, used = [], set()
        for i, t in enumerate(tabs):
            p = None
            for ref in t.get("aria-controls").split():
                p = ids.get(ref)
                if p is not None:
                    break
            if p is None and t.get("id"):
                p = next((d for d in pool if t.get("id") in d.get("aria-labelledby").split()), None)
            if p is None and not any(x.get("aria-controls") for x in tabs) and len(pool) == len(tabs):
                p = pool[i]
            if p is not None and (p.end is None or id(p) in used or _inside(tl, p) or _inside(t, p) or _inside(p, t)):
                p = None                                 # one panel for every tab: the first tab's alone
            if p is not None:
                used.add(id(p))
            panels.append(p)
        present = [p for p in panels if p is not None]
        if any(edits.taken(p.start, p.end) for p in present):
            continue
        shown = [i for i, t in enumerate(tabs) if t.get("aria-selected").lower() == "true"]
        if not shown:
            shown = [i for i, t in enumerate(tabs) if t.get("data-state").lower() in ("active", "on", "selected")]
        if not shown:
            shown = [i for i, p in enumerate(panels) if p is not None and not _hidden(p)]
            shown = shown if len(shown) == 1 else []
        shown = set(shown or [0])
        rows = []                                        # (marker, the panel it heads or None)
        for i, (t, p) in enumerate(zip(tabs, panels)):
            name = labels[i]
            if i in shown:
                rows.append((_p(marker("tab", "shown", name)), p))
                continue
            if p is None or not _has_content(src, p):
                rows.append((_p(marker("tab", "missing", name)), None))
                info["counts"]["not_extracted"] += 1
                continue
            text = _text(src, p)
            size = len(text.encode("utf-8"))
            m = marker("tab", "hidden", name)
            nth = info["seen"][m] = info["seen"].get(m, 0) + 1
            if size > PANEL_LIMIT and not page:
                tok = _token(text)
                info["long"].append({"token": tok, "text": text})
                rows.append((_p(marker("tab", "hidden", name, TOO_LONG % (_human(size), "RPTABLINE" + tok))), None))
                info["counts"]["long"] += 1
                continue
            if size > PANEL_LIMIT:
                info["page_long"][_token(text)] = [m, nth]
            rows.append((_p(m), p))
            info["counts"]["extracted"] += 1
            if _dropped(p):
                info["extra"] += len(text)               # what the extractors had not seen: readpage weighs them without it
        info["counts"]["tabs"] += 1
        kept = set(id(p) for _m, p in rows if p is not None)
        # a panel keeps its place and its own attributes but those that hide it, its marker first inside it: the
        # page's structure is the extractors' as before (a panel they took before they take now, with a name)
        if any(_inside(p, tl) for p in present):
            # the panels stand inside the list, each after its tab (arXiv's labs): a tab with a panel goes, its
            # marker heads the panel; a tab with none is its marker, where it stood
            for t, (m, p) in zip(tabs, rows):
                edits.add(t.start, t.end, "" if p is not None else m)
                if p is not None:
                    edits.add(p.start, p.open_end, _unhidden(p) + m)
        else:
            # a marker with no panel stands after the panel before it, or where the list was
            first = next((k for k, (_m, p) in enumerate(rows) if p is not None), len(rows))
            edits.add(tl.start, tl.end, "".join(m for m, _p2 in rows[:first]))
            for k in range(first, len(rows)):
                m, p = rows[k]
                if p is None:
                    continue
                nxt = next((j for j in range(k + 1, len(rows)) if rows[j][1] is not None), len(rows))
                after = "".join(m2 for m2, _p2 in rows[k + 1:nxt])
                edits.add(p.start, p.open_end, _unhidden(p) + m)
                if after:
                    edits.add(p.end, p.end, after)
        for p in panels:
            if p is not None and id(p) not in kept:
                edits.add(p.start, p.end, "")           # an empty panel, or one too long for the text


HIDING = {"hidden", "invisible", "d-none", "is-hidden", "hide", "collapse", "collapsed", "is-collapsed"}


def _dropped(el):
    """Hidden the way defuddle drops an element (the hidden attribute, aria-hidden, a display:none, the class
    `hidden`): its text was in no extractor's text before, so the engines are weighed without it."""
    style = el.get("style").replace(" ", "").lower()
    cls = [c.lower() for c in el.get("class").split()]
    return ("hidden" in el.attrs or el.get("aria-hidden").lower() == "true" or "display:none" in style
            or "visibility:hidden" in style or any(c in ("hidden", "invisible") or c.endswith((":hidden", ":invisible"))
                                                    for c in cls))


def _unhidden(el):
    """The element's start tag without what hides it: the hidden attribute, aria-hidden, a display:none, a class
    that hides (defuddle drops all of them, and so did the page)."""
    parts = [el.tag]
    for k, v in el.attrs.items():
        if k in ("hidden", "aria-hidden", "inert"):
            continue
        if k == "style":
            v = re.sub(r"(?i)(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0)\s*(!important)?\s*;?", "", v)
            if not v.strip():
                continue
        if k == "class":
            v = " ".join(c for c in v.split() if c.lower() not in HIDING and not c.lower().endswith((":hidden", ":invisible")))
            if not v:
                continue
        parts.append('%s="%s"' % (k, v.replace("&", "&amp;").replace('"', "&quot;")) if v != "" else k)
    return "<%s>" % " ".join(parts)


def _hidden(el):
    style = el.get("style").replace(" ", "").lower()
    cls = set(el.get("class").split())
    return ("hidden" in el.attrs or el.get("aria-hidden").lower() == "true" or "display:none" in style
            or "visibility:hidden" in style or bool(cls & {"hidden", "d-none", "is-hidden", "hide", "invisible"})
            or ("collapse" in cls and not cls & {"show", "in"}))


def _a_form(el):
    return any(d.tag in ("form", "input", "textarea", "select", "fieldset") for d in _descendants(el))


def _a_widget(src, el):
    """A popover or a form folded into a section (a menu of links, a feedback form): no content of the page."""
    return _link_share(src, el) >= 0.5 or _a_form(el)


def _details(tree, src, page, edits, info):
    for d in [e for e in tree.els if e.tag == "details"]:
        if d.end is None or "open" in d.attrs or _out_of_main(d) or edits.taken(d.start, d.end):
            continue
        summary = next((k for k in d.kids if k.tag == "summary"), None)
        name = _text(src, summary, outer=True) if summary is not None else ""
        if not name or _a_widget(src, d):
            continue                                     # an icon's popover, a menu, a feedback form
        inner = src[d.open_end:summary.start] + src[summary.end:d.end] if summary.end is not None else ""
        inner = re.sub(r"(?is)</details\s*>\s*$", "", inner)
        body = re.sub(r"\s+", " ", unescape(_TAG.sub(" ", inner))).strip()
        if not body:
            continue
        # the summary is the marker; the <details> stays as it was, so an extractor takes what it took before. A
        # summary that holds a heading keeps its level: the marker is the heading, and the outline lists it
        h = next((k for k in _descendants(summary) if re.match(r"h[1-6]$", k.tag)), None)
        m = marker("section", "hidden", name)
        edits.add(summary.start, summary.end, "<%s>%s</%s>" % (h.tag, _escape(m), h.tag) if h is not None else _p(m))
        info["counts"]["sections"] += 1


def _sections(tree, src, page, edits, info):
    """Accordions: a button with aria-expanded whose region (aria-controls) the HTML holds as text."""
    for b in tree.els:
        exp = b.get("aria-expanded").lower()
        if exp not in ("true", "false") or not b.get("aria-controls"):
            continue
        role = b.get("role").lower()
        if not (b.tag == "button" or role == "button") or role in ("tab", "combobox", "menuitem", "treeitem"):
            continue
        if b.get("aria-haspopup").lower() not in ("", "false") or _is_link(b) or b.end is None:
            continue
        if _out_of_main(b) or edits.taken(b.start, b.end):
            continue
        region = None
        for ref in b.get("aria-controls").split():
            region = tree.ids.get(ref)
            if region is not None:
                break
        if region is None or region.end is None or _inside(b, region) or _inside(region, b):
            continue
        # a button that is a heading's is an accordion's (ARIA's pattern), whatever its region holds: a list of files
        # in one is the page's content (statistik.at's "Historische Daten", two .ods files), where a toggle that heads
        # no heading folding away a list of links is a menu - on 1 602 pages of the bench and the corpora, the 8 such
        # regions in a heading were all content, the 49 others menus (KNOWN-ISSUES 339)
        heading = b.parent if b.parent is not None and re.match(r"h[1-6]$", b.parent.tag) else None
        links = heading is not None and _link_share(src, region) >= 0.5
        if (_out_of_main(region) or region.tag in OUT_TAGS or region.get("role").lower() in OUT_ROLES
                or not _text(src, region) or (_a_form(region) if links else _a_widget(src, region))):
            continue                                     # nothing in the page, a menu folded away, a form
        if edits.taken(region.start, region.end):
            continue
        name = _text(src, b, outer=True)
        if not name:
            continue
        m = marker("section", "shown" if exp == "true" else "hidden", name)
        edits.add(b.start, b.end, _escape(m) if heading is not None else _p(m))
        edits.add(region.start, region.open_end, _unhidden(region))
        info["counts"]["sections"] += 1
        if links:
            info["links"].append(_text(src, region))      # an extractor drops such a list: the block rule puts it back
        if _dropped(region):
            info["extra"] += len(_text(src, region))


def _table_tabs(tree, src, page, edits, info):
    """A table whose header cell holds buttons and nothing else: the table's own tabs (Groq's plans)."""
    for th in [e for e in tree.els if e.tag in ("th", "caption")]:
        if th.end is None:
            continue
        buttons = [d for d in _descendants(th) if d.tag == "button"]
        if not 2 <= len(buttons) <= 8 or any(_inside(x, y) for x in buttons for y in buttons if x is not y):
            continue
        labels = [_text(src, x, outer=True) for x in buttons]
        if not all(labels) or any(len(x) > 40 for x in labels):
            continue
        if _text(src, th) != " ".join(labels) and len(_text(src, th)) > len(" ".join(labels)) + 2:
            continue                                     # the cell says more than its buttons: not a tab bar
        table = th.parent
        while table is not None and table.tag != "table":
            table = table.parent
        if table is None or table.end is None or _out_of_main(table) or edits.taken(table.start, table.end):
            continue
        row = th.parent if th.tag == "th" else th
        while row is not None and row.tag not in ("tr", "caption"):
            row = row.parent
        if row is None:
            continue
        if row.tag == "tr" and _text(src, row, outer=True) != _text(src, th, outer=True):
            continue                                     # the row has headers of its own beside the buttons
        shown = [i for i, x in enumerate(buttons) if x.get("aria-pressed").lower() == "true"
                 or x.get("aria-selected").lower() == "true" or x.get("aria-current").lower() not in ("", "false")
                 or x.get("data-state").lower() in ("active", "on", "checked", "selected")
                 or any(ACTIVE.match(c) for c in x.get("class").split())]
        i_shown = shown[0] if len(shown) == 1 else 0
        before = "".join(_p(marker("tab", "missing", n)) for n in labels[:i_shown])
        after = "".join(_p(marker("tab", "missing", n)) for n in labels[i_shown + 1:])
        body = src[table.open_end:row.start] + src[row.end:table.end]
        # the rows may stand in a table of their own beside the header's (Groq's sticky header): the other tabs'
        # markers go after the box that holds the tables and nothing else
        top, up = table, table.parent
        while up is not None and up.tag not in ("#root", "html", "body", "main", "article") and _only_tables(src, up):
            top, up = up, up.parent
        if edits.taken(top.end, top.end) and top is not table:
            top = table
        edits.add(table.start, table.end, "%s%s%s%s%s" % (before, _p(marker("tab", "shown", labels[i_shown])),
                                                          src[table.start:table.open_end], body,
                                                          after if top is table else ""))
        if top is not table:
            edits.add(top.end, top.end, after)
        info["counts"]["tabs"] += 1
        info["counts"]["not_extracted"] += len(labels) - 1


def _only_tables(src, el):
    """A box whose text is all in its tables (wrappers of a header table and of its rows' table)."""
    every = [d for d in _descendants(el) if d.tag == "table"]
    tables = [d for d in every if not any(_inside(d, o) for o in every if o is not d)]
    if not tables:
        return False
    return len(_text(src, el).split()) - sum(len(_text(src, t, outer=True).split()) for t in tables) <= 2


def _selects(tree, src, page, edits, info):
    for s in [e for e in tree.els if e.tag == "select"]:
        if s.end is None or _out_of_main(s) or edits.taken(s.start, s.end):
            continue
        opts = [d for d in _descendants(s) if d.tag == "option"]
        texts = [_text(src, o) for o in opts]
        if len([t for t in texts if t]) < 2:
            continue
        chosen = next((i for i, o in enumerate(opts) if "selected" in o.attrs), 0)
        others = [t for i, t in enumerate(texts) if t and i != chosen]
        also = ", ".join(_name(t) for t in others[:SELECT_ALSO]) + (
            " and %d more" % (len(others) - SELECT_ALSO) if len(others) > SELECT_ALSO else "")
        name = ""
        if s.get("id"):
            lab = next((e for e in tree.els if e.tag == "label" and e.get("for") == s.get("id")), None)
            name = _text(src, lab) if lab is not None else ""
        name = name or s.get("aria-label") or s.get("title")
        m = marker("select", "chosen: %s" % _name(texts[chosen] or "-"), name, "also " + also if also else "")
        edits.add(s.start, s.end, "<span>%s</span>" % _escape(m))
        info["counts"]["selects"] += 1


def mark(html, page=False):
    """The page with a marker at every tab, collapsed section and select of its main content, and what was
    done: {"counts": {...}, "long": [{"token", "text"}], "page_long": {token: marker}}. page=True is
    page.md's copy: every hidden panel stays whole there."""
    info = {"counts": {"tabs": 0, "extracted": 0, "not_extracted": 0, "long": 0, "sections": 0, "selects": 0},
            "long": [], "page_long": {}, "seen": {}, "extra": 0, "links": []}
    if not html or len(html) > MAX_HTML or not re.search(
            r"(?i)role\s*=\s*[\"']?tablist|<details\b|aria-expanded|<select\b|<th\b[^>]*>(?:(?!</th>).){0,600}<button",
            html):
        return html, info
    for _pass in range(2):                               # a section inside a panel is the second pass's
        tree = _tree(html)
        if tree is None:
            return html, info
        edits = _Edits()
        for step in (_tab_sets, _table_tabs, _details, _sections, _selects):
            step(tree, tree.src, page, edits, info)
        if not edits.rows:
            break
        html = edits.apply(html)
    return html, info


def unmarked(md):
    """The text without its markers: what the engines are weighed on, so a marker chooses no engine."""
    return MARKER.sub("", md) if md and "· " in md else (md or "")


def unescape_markers(md):
    """A converter escapes the brackets of a marker (`\\[tab · shown · X\\]`): they are the marker's own."""
    if not md or "· " not in md:
        return md
    return MARKER.sub(lambda m: "[%s · %s]" % (m.group(1), re.sub(r"\\(.)", r"\1", m.group(2))), md)


def place_lines(text, page_md, page_long):
    """A too long panel's marker in the text names its line in page.md: the line of its marker there."""
    if not text or "RPTABLINE" not in text:
        return text
    lines = (page_md or "").split("\n")

    def one(m):
        want, nth = (page_long.get(m.group(1)) or ["", 0])[:2]
        if want:
            for n, line in enumerate(lines, 1):
                if want in line:
                    nth -= 1
                    if nth <= 0:
                        return str(n)
        return "?"
    out = LINE_TOKEN.sub(one, text)
    return out.replace("page.md from line ?", "page.md")
