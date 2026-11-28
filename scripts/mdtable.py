"""A table that a converter left as HTML, in the text's own table form (KNOWN-ISSUES 338).

defuddle writes a table one of whose cells spans rows or columns (`colspan`, `rowspan`) as its cleaned HTML, where it
writes every other table in Markdown: japanrailpass.net's price tables came as
`<table><tbody><tr><th>種類</th><th colspan="2">グリーン車用</th>...`, and the block rule, which compares words, did not
know such a table for the one page.md has, so it put page.md's rows back beside it - each price twice. tables() writes
each such table as defuddle writes the others: its first row, `| --- |`, a row a line, padded to the widest row, a
cell's `|` escaped. A cell's text stands in the first row and column of its span, and the cells it spans over are
empty, so the table's words are page.md's, in the same order. Standard library only.
"""
import re
import urllib.parse
from html.parser import HTMLParser

SPAN_MAX = 100                   # a span past this many rows or columns is taken as this many
_START = re.compile(r"(?i)^\s*<table\b")
_OPEN = re.compile(r"(?i)<table\b")
_CLOSE = re.compile(r"(?i)</table\s*>")
_BREAK = {"br", "p", "div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
          "pre", "hr", "section", "article", "figure", "figcaption", "tr"}
_MARK = {"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`"}


def _span(v):
    try:
        n = int(str(v or "").strip() or 1)
    except ValueError:
        return 1
    return 0 if n == 0 else max(1, min(SPAN_MAX, n))


class _Table(HTMLParser):
    """The rows of one table: each a list of [text, colspan, rowspan]. A table inside a cell is its text."""

    def __init__(self, base):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.base, self.rows, self.caption = base, [], []
        self.depth, self.cell, self.in_caption = 0, None, False
        self.open = []                   # (tag, what closes it, where its opening mark is in the cell): a link, a mark

    def _put(self, s):
        if self.cell is not None:
            self.cell.append(s)
        elif self.in_caption:
            self.caption.append(s)

    def _url(self, u):
        u = (u or "").strip()
        return urllib.parse.urljoin(self.base, u) if self.base and u else u

    def _begin(self, tag, mark, close):
        if self.cell is not None:
            self.open.append((tag, close, len(self.cell)))
            self.cell.append(mark)

    def _finish(self, tag=None):
        """A link's or a mark's end: its closing mark, or none of it when nothing stands inside (an icon's link). An
        end tag that closes nothing open in the cell is passed over."""
        if not self.open or (tag is not None and self.open[-1][0] != tag):
            return
        _tag, close, at = self.open.pop()
        if self.cell is None or at >= len(self.cell):
            return
        if "".join(self.cell[at + 1:]).strip():
            self.cell.append(close)
        else:
            del self.cell[at]

    def _end_cell(self):
        if self.cell is not None and self.rows:
            while self.open:
                self._finish()
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            self.rows[-1][-1][0] = text.replace("|", "\\|")
        self.cell, self.open = None, []

    def handle_starttag(self, tag, attrs):
        a = dict((k, v or "") for k, v in attrs)
        if tag == "table":
            self.depth += 1
            if self.depth > 1:
                self._put(" ")
            return
        if self.depth == 1 and tag == "tr":
            self._end_cell()
            self.rows.append([])
        elif self.depth == 1 and tag in ("td", "th"):
            self._end_cell()
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(["", _span(a.get("colspan")), _span(a.get("rowspan"))])
            self.cell = []
        elif self.depth == 1 and tag == "caption":
            self.in_caption = True
        elif tag == "a" and a.get("href") and not a["href"].lower().startswith("javascript:"):
            self._begin(tag, "[", "](%s)" % self._url(a["href"]).replace(")", "%29").replace(" ", "%20"))
        elif tag == "a":
            self._begin(tag, "", "")
        elif tag == "img" and a.get("src"):
            self._put("![%s](%s)" % (a.get("alt", "").replace("]", ")").replace("[", "("), self._url(a["src"])))
        elif tag in _MARK:
            self._begin(tag, _MARK[tag], _MARK[tag])
        elif tag in _BREAK or tag in ("td", "th"):
            self._put(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag == "a":
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "table":
            if self.depth == 1:
                self._end_cell()
            self.depth = max(0, self.depth - 1)
            if self.depth >= 1:
                self._put(" ")
            return
        if self.depth == 1 and tag in ("td", "th"):
            self._end_cell()
        elif self.depth == 1 and tag == "tr":
            self._end_cell()
        elif self.depth == 1 and tag == "caption":
            self.in_caption = False
        elif tag == "a" or tag in _MARK:
            self._finish(tag)
        elif tag in _BREAK:
            self._put(" ")

    def handle_data(self, data):
        self._put(data)


def _grid(rows):
    """The rows as a grid: a spanning cell's text in its first row and column, the cells it spans over ""."""
    grid, taken = [], set()
    total = len(rows)
    for r, row in enumerate(rows):
        while len(grid) <= r:
            grid.append([])
        c = 0
        for text, cs, rs in row:
            while (r, c) in taken:
                c += 1
            rs = (total - r) if rs == 0 else rs
            cs = 1 if cs == 0 else cs
            for dr in range(rs):
                for dc in range(cs):
                    taken.add((r + dr, c + dc))
                    while len(grid) <= r + dr:
                        grid.append([])
                    line = grid[r + dr]
                    while len(line) <= c + dc:
                        line.append("")
                    line[c + dc] = text if (dr, dc) == (0, 0) else ""
            c += cs
    return [line for line in grid[:total]]


def markdown(table_html, base=""):
    """One HTML table as a Markdown table in defuddle's form; None when it holds no cell."""
    p = _Table(base)
    try:
        p.feed(table_html)
        p.close()
    except Exception:                                         # noqa: BLE001  (a table the parser cannot take stays)
        return None
    p._end_cell()
    grid = [row for row in _grid([r for r in p.rows if r]) if row]
    width = max([len(row) for row in grid] or [0])
    if not width:
        return None
    lines = ["| %s |" % " | ".join(row + [""] * (width - len(row))) for row in grid]
    lines.insert(1, "| %s |" % " | ".join(["---"] * width))
    caption = re.sub(r"\s+", " ", "".join(p.caption)).strip()
    return (caption + "\n\n" if caption else "") + "\n".join(lines)


def tables(md, base=""):
    """The text with each table it holds as HTML - a block of its own, outside code - in its Markdown form."""
    if not md or "<table" not in md.lower():
        return md
    lines, out, i, fence = md.split("\n"), [], 0, ""
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith(("```", "~~~")):
            fence = "" if fence and s.startswith(fence) else (fence or s[:3])
        if fence or not _START.match(line):
            out.append(line)
            i += 1
            continue
        depth, j = 0, i
        while j < len(lines):
            depth += len(_OPEN.findall(lines[j])) - len(_CLOSE.findall(lines[j]))
            if depth <= 0:
                break
            j += 1
        chunk = "\n".join(lines[i:j + 1])
        if depth > 0 or not _CLOSE.search(lines[min(j, len(lines) - 1)]) or not re.search(r"(?is)</table\s*>\s*$", chunk):
            out.append(line)                                  # not closed, or text after it on its line: left as it is
            i += 1
            continue
        got = markdown(chunk, base)
        out.append(got if got else chunk)
        i = j + 1
    return "\n".join(out)
