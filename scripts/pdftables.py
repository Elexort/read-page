"""A PDF's tables by pymupdf4llm's layout model, in a process of its own: the read's deadline holds.

The model's call cannot be interrupted, and one page of 20 010 vector paths (a scatter plot drawn
point by point, as plotting tools export one) held it 20-27 s - the read past its 55 s and past
the MCP server's kill at 58 s. Here the model runs in the read's child: the read sends it pages one
by one, takes each page's answer as it comes, and kills a child still at work when the time for
tables is up. The child costs 0.15-0.22 s a read on a 20-core Windows machine (a process and PyMuPDF's import) beside the
model's own load of 0.7-0.8 s, which a read paid before too (2026-11-20). It ends with the read:
a thread watches the read's process, so one killed from outside does not leave it at its page
(18-24 s more, 2026-11-21).

The model gives a table's box and its grid of cells; the page gives the words. The model's own
cell text - a character goes to a cell when more than half of its box is inside - cut a word at a
grid line ("1 Intr | oduction"), scattered a header's letters over two rows ("Cbid CN dl") and
dropped the points and commas that straddled a line ("5121" for "5.1.2.1", "$32200" for
"$32,200"). So each cell gets the page's whole words (PyMuPDF's words) of the text blocks the
table stands for: a block is the table's when half its words' centres are inside the box, and a
caption's lines (Table 3: ...) never are - they stay text where they stood; each word goes to
the cell that holds its centre or else the nearest. A line of prose or a note that the grid's
column lines cut at a mere space, where a cell holds two lines or more, stays text too, before
or after the table (a form's instructions, a table's footnotes). Cells that one header spans are
joined by the gap between their words alone. A table stands in place of its blocks only when its
cells hold exactly their words: that check guards against a word lost or put in twice, not
against a word in the wrong cell. On 29 PDFs (398 pages, 9 papers with known cells): no word lost
or added (187 and 277 before), 142 caption lines of 142 (137), the papers' rows whole on a line
89 % (78 %) and as table rows 74 % (70 %), with no time limit.

    python -E -B -X utf8 pdftables.py --parent PID     requests on stdin, answers on stdout

A request: {"path": PDF, "pages": [i, ...]} for those pages' tables (pages from 0), with
"markdown": true for pymupdf4llm's Markdown of the pages instead (--alternate). The answers, a
JSON object a line: {"ready": seconds} once pymupdf4llm is loaded, or {"fatal": why} and the end
(pymupdf4llm 1.28 does not import without onnxruntime); then one a page - {"page": i, "text": ...,
"n": tables, "s": seconds} ("text" is null when no table was put in) or {"page": i, "error": why}.
Pages of a Markdown request are answered together, when its one call ends. Every answer, and a
{"tick": 1} every TICK seconds from the start, says the process's pace: "busy", its seconds since
it started less those it waited for a request, and "work", its CPU seconds, at most one for each
of those seconds however many threads ran - the read gives the model as much more time as it
waits for the CPU (KNOWN-ISSUES 237). EOF on stdin, or the end of
the process PID, ends the process. -E keeps a caller's PYTHONPATH out (a folder of another
Python's PyMuPDF cost every PDF its tables); READ_PAGE_TEST_MODEL_PATH, read here only, is the
test suites' way in.
"""
import bisect
import json
import os
import re
import sys
import threading
import time
import unicodedata
from collections import defaultdict

# a table's caption: Table 3, Tab. 2, Таблица 1 - and 表 3, 表3, 表３, 表一 (Chinese and Japanese), 표 2 (Korean),
# but not 表3所示 in a sentence that starts a line
CAPTION = re.compile(r"(?mi)^\s*(?:(?:table|tab\.|таблица|табл\.)\s*[\dIVXLC]+\b"
                     r"|[表표]\s*[\d一二三四五六七八九十]+(?:[-.．][\d]+)*(?!\w))")
SPAN_GAP = 0.35        # of a word's height: two cells of a row whose words stand this close are one
BOX_CUTS = True        # a table whose box runs through a word of the page is left as text
CUT_LINES = True       # a line the column lines cut at a mere space, in a cell of two lines, is text
SPLIT_ROWS = True      # two rows of the page in one row of the grid are two rows (split_rows)
NUMBER = re.compile(r"^[-+−–±$€£(]?\d[\d.,]*%?\)?[*†‡§]*$")
TICK = 0.5             # seconds between the words of the process's pace while nothing else is said


def cpus():
    """The CPUs this process may use: its affinity where the OS keeps one (Linux: a container's
    share, taskset), else the machine's count - on Windows `os.process_cpu_count()` ignores the
    affinity mask (20 under a mask of 4, 2026-11-21)."""
    try:
        return len(os.sched_getaffinity(0)) or 1
    except (AttributeError, OSError):
        pass
    count = getattr(os, "process_cpu_count", None)               # Python 3.13
    try:
        return (count() if count else 0) or os.cpu_count() or 1
    except Exception:                                           # noqa: BLE001
        return os.cpu_count() or 1


def calm_onnx():
    """onnxruntime as a small model needs it on a machine that does other things: four threads at
    most, none spinning while it waits. As the library sets its sessions up (a thread a core, each
    spinning) a page of the layout model took 0.23 s and 2.4 s of CPU on 20 cores, but 4.5 s on
    four slow cores and 1.8 s (at most 2.5) on two; so set: 0.23, 0.51 and 0.32 s, a third of a
    CPU second (2026-11-19). The threads come from cpus(). pymupdf.layout makes its sessions when
    it is imported, so this comes before that import. A class, not a function: the library names
    the type in its annotations. Returns why it could not ("" when it did)."""
    try:
        import onnxruntime as ort
    except Exception as e:                                     # noqa: BLE001
        return "onnxruntime: %s" % str(e)[:120]
    real = ort.InferenceSession
    if getattr(real, "_read_page_calm", False):
        return ""

    class Calm(real):
        _read_page_calm = True

        def __init__(self, path, sess_options=None, **kw):
            so = sess_options or ort.SessionOptions()
            try:
                so.intra_op_num_threads = min(4, cpus())
                so.inter_op_num_threads = 1
                so.add_session_config_entry("session.intra_op.allow_spinning", "0")
            except Exception:                                  # noqa: BLE001
                pass
            real.__init__(self, path, sess_options=so, **kw)
    ort.InferenceSession = Calm
    return ""


def gfm_table(rows):
    """Rows of cells as a Markdown table, "" when there is no table in them."""
    rows = [[re.sub(r"\s+", " ", str(cell or "")).strip().replace("|", "\\|") for cell in row] for row in rows or []]
    rows = [r for r in rows if any(r)]
    width = max([len(r) for r in rows] or [0])
    if len(rows) < 2 or width < 2:
        return ""
    rows = [r + [""] * (width - len(r)) for r in rows]
    return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
                     + ["| " + " | ".join(r) + " |" for r in rows[1:]])


def wordbag(s):
    # NFKC: a ligature written out (Efficient) is the same word as the page's (Efﬁcient)
    bag = {}
    for w in re.findall(r"\w+", unicodedata.normalize("NFKC", s or "").lower()):
        bag[w] = bag.get(w, 0) + 1
    return bag


def vertical(w, dirs=None):
    """A word set on its side (a rotated column header): its line runs more up than across (the
    line's direction from PyMuPDF). Without it, three letters or more in a box taller than wide -
    which also took 821 short words of horizontal lines for rotated ones ("the", "6.8", "28,")."""
    d = dirs.get((w[5], w[6])) if dirs and len(w) > 6 else None
    if d:
        return abs(d[1]) > abs(d[0])
    return len(w[4]) >= 3 and (w[3] - w[1]) > (w[2] - w[0])


def box_cuts(words, box, dirs=None):
    """Does the model's box of a table run through a word of the page - a point and a half of it
    on each side of the box's left or right edge? Then the model saw the text in another place
    than the page has it (an invoice's "Melbourne" came as "lbourne", "ANZ Bank" as "Z Bank"), and
    the table is left as the plain text. Not a word on its side: the box of a rotated
    "Cryptographic" reached 1.5 pt past a table's edge (NIST 800-63B)."""
    for w in words:
        if len(w[4]) > 2 and not vertical(w, dirs) and box[1] <= (w[1] + w[3]) / 2.0 <= box[3]:
            for edge in (box[0], box[2]):
                if w[0] + 1.5 < edge < w[2] - 1.5:
                    return True
    return False


def grid_of(cells):
    """The model's cells as the grid's lines, (columns, rows): pymupdf4llm 1.28 builds every cell
    from them. None when a cell is not where the lines say (then the table is not used)."""
    try:
        xs = [float(c[0]) for c in cells[0]] + [float(cells[0][-1][2])]
        ys = [float(r[0][1]) for r in cells] + [float(cells[-1][0][3])]
        for r, row in enumerate(cells):
            if len(row) != len(xs) - 1:
                return None
            for c, box in enumerate(row):
                if (abs(box[0] - xs[c]) > 0.5 or abs(box[2] - xs[c + 1]) > 0.5
                        or abs(box[1] - ys[r]) > 0.5 or abs(box[3] - ys[r + 1]) > 0.5):
                    return None
    except (TypeError, IndexError, ValueError):
        return None
    if len(xs) < 3 or len(ys) < 3 or xs != sorted(xs) or ys != sorted(ys):
        return None
    return xs, ys


def fill(words, xs, ys):
    """Each word to the cell that holds its centre, else the nearest: the grid is regular, so the
    nearest column by x and the nearest row by y (found by bisection, not a look at every cell
    for every word - a page of 8 000 numbers would be 8 000 x its cells). {(row, column): words}."""
    put = defaultdict(list)
    last_c, last_r = len(xs) - 2, len(ys) - 2
    for w in words:
        c = min(max(bisect.bisect_right(xs, (w[0] + w[2]) / 2.0) - 1, 0), last_c)
        r = min(max(bisect.bisect_right(ys, (w[1] + w[3]) / 2.0) - 1, 0), last_r)
        put[(r, c)].append(w)
    return put


def cell_text(words):
    """A cell's words in reading order: a line of the page is a line of the cell."""
    lines, last = [], None
    for w in sorted(words, key=lambda w: (w[5], w[6], w[0])):          # block, line, x
        if last is not None and (w[5], w[6]) == last:
            lines[-1].append(w[4])
        else:
            lines.append([w[4]])
        last = (w[5], w[6])
    return "\n".join(" ".join(ln) for ln in lines)


def _phrase_gap(lw, rw, dirs):
    """Do two words stand as near as words of one phrase, on one baseline (neither on its side)?"""
    return (not vertical(lw, dirs) and not vertical(rw, dirs) and abs((rw[1] + rw[3]) - (lw[1] + lw[3])) <= 3
            and -1 <= rw[0] - lw[2] <= SPAN_GAP * (lw[3] - lw[1]))


def mend(put, rows, dirs=None):
    """A cell that spans columns stands in the model's grid as several ("BLEU" over two columns,
    one value under both as "3.3 ·" and "1018" - which reads as two values). Two neighbouring cells
    of one line are one when the last word of the left one and the first of the right one stand
    as near as words of a phrase do (SPAN_GAP of the word's height, on one baseline), wherever the
    grid line runs: the text goes into the first and the second is left empty. Not cells of two
    lines (a spanning line above cells of their own: joining them would mix the two), and not a
    word on its side ("Caltech101" and "CIFAR-100" are two headers)."""
    out = [list(r) for r in rows or []]
    for r, row in enumerate(out):
        anchor = None
        for k in range(len(row) - 1):
            left = anchor if anchor is not None else k
            one, two = str(row[left] or "").strip(), str(row[k + 1] or "").strip()
            lws, rws = put.get((r, k)), put.get((r, k + 1))
            if not one or not two or "\n" in one or "\n" in two or not lws or not rws:
                anchor = None
                continue
            lw, rw = max(lws, key=lambda w: w[2]), min(rws, key=lambda w: w[0])
            if SPAN_GAP and _phrase_gap(lw, rw, dirs):
                row[left] = (str(row[left]) + " " + str(row[k + 1])).strip()
                row[k + 1] = ""
                anchor = left
            else:
                anchor = None
    return out


def cut_lines(put, dirs=None):
    """The page's lines that the grid's column lines cut at a mere space - the gap of words of one
    phrase - where a cell they fall in holds two lines or more, which mend cannot join: prose or a
    table's notes inside the model's box, read cell by cell as word salad (a W-4's TIP paragraph,
    EfficientNet's three footnotes over 13 cells, GPT-3's "7 Related | Work | 39"; 52 such lines in
    6 tables of the corpus, 2026-11-21). Their (block, line) keys."""
    lines_in = {cell: len({(w[5], w[6]) for w in ws}) for cell, ws in put.items()}
    byline = defaultdict(dict)
    for cell, ws in put.items():
        for w in ws:
            byline[(w[5], w[6])].setdefault(cell, []).append(w)
    out = set()
    for key, cells in byline.items():
        order = sorted(cells)
        for a, b in zip(order, order[1:]):
            if a[0] != b[0] or max(lines_in[a], lines_in[b]) < 2:
                continue
            if _phrase_gap(max(cells[a], key=lambda w: w[2]), min(cells[b], key=lambda w: w[0]), dirs):
                out.add(key)
                break
    return out


def _cell_lines(ws):
    """A cell's lines of the page, in order: [(top, bottom, text)]."""
    by = defaultdict(list)
    for w in ws:
        by[(w[5], w[6])].append(w)
    return sorted((min(w[1] for w in ln), max(w[3] for w in ln),
                   " ".join(x[4] for x in sorted(ln, key=lambda w: w[0]))) for ln in by.values())


def _parallel(lines):
    """Are a cell's lines items of one kind - all numbers, or all with one last word ("Correct Answer
    ->" over "Incorrect Answer ->"), or one first word of phrases - rather than one text wrapped ("WiC"
    over "Accuracy", "Average number of" over "co-occurrences")?"""
    if all(NUMBER.match(t) for t in lines):
        return True
    words = [t.split() for t in lines]
    if any(not w for w in words):
        return False
    return len({w[-1] for w in words}) == 1 or (len({w[0] for w in words}) == 1 and all(len(w) > 1 for w in words))


def split_rows(put, ys):
    """The grid's row lines with one more where a row of the grid holds rows of the page (KNOWN-ISSUES
    127: GPT-3's "LAMBADA LAMBADA | acc ppl | 68.0 8.63", its examples' "Correct Answer -> Incorrect
    Answer ->" beside both answers). A row is split when one of its cells holds two lines or more that
    are items of one kind (_parallel) and every other cell has a line starting beside each of them -
    a cell's own text may wrap below its line; the new line runs under the last line that ends before
    the next row starts. Never the first row, whose header may wrap. Measured 2026-11-21 on the corpus
    with no time limit: truth rows whose first three cells start a table row 876 -> 892 of 1 051 (16 of
    GPT-3's Table H.1), rows whole 788 and as table rows 654 of 889 as before, no other document
    changed; a rule that split any row whose every cell had as many lines on shared heights lost 2
    whole rows (headers) and made 12 rows of none, one that took short lines as items broke a form's
    prose into rows."""
    extra = []
    for r in range(1, len(ys) - 1):
        cells = [_cell_lines(ws) for (rr, _c), ws in put.items() if rr == r and ws]
        if len(cells) < 2:
            continue
        anchors = [v for v in cells if len(v) >= 2 and _parallel([t[2] for t in v])]
        if not anchors:
            continue
        a = max(anchors, key=len)
        if not all(all(any(abs(t[0] - top) <= 2.0 for t in v) for top, _b, _t in a) for v in cells):
            continue
        for i in range(1, len(a)):
            top = a[i][0]
            if top <= a[i - 1][1]:
                continue
            above = max([a[i - 1][1]] + [t[1] for v in cells for t in v if t[1] <= top + 0.5])
            extra.append((above + top) / 2.0)
    return sorted(set(ys) | set(extra)) if extra else ys


def alone(lines, n):
    """Is line n of a block the only one at its height - no other line's middle inside its band?"""
    y0, y1 = min(w[1] for w in lines[n]), max(w[3] for w in lines[n])
    for m, ln in enumerate(lines):
        if m != n and y0 < (min(w[1] for w in ln) + max(w[3] for w in ln)) / 2.0 < y1:
            return False
    return True


def page_tables(doc, i):
    """Page i (from 0) with the model's tables in its text: (text, tables put in, notes). The text
    is None when no table was put in; else the page's text blocks in their order, a table where
    the first of its blocks stood."""
    import pymupdf
    import pymupdf4llm
    d = pymupdf4llm.to_json(doc, pages=[i], use_ocr=False, show_progress=False)
    d = json.loads(d) if isinstance(d, str) else d
    notes, found = [], []
    for b in ((d.get("pages") or [{}])[0].get("boxes") or []):
        t = b.get("table") if b.get("boxclass") == "table" else None
        if not (isinstance(t, dict) and t.get("bbox") and (t.get("row_count") or 0) >= 2
                and (t.get("col_count") or 0) >= 2):
            continue
        grid = grid_of(t.get("cells"))
        if grid is None:
            notes.append("a grid whose cells are not on its lines")
            continue
        found.append((t["bbox"], grid))
    if not found:
        return None, 0, notes
    page = doc[i]
    # one text page for the words, the blocks and the lines' directions: their numbers agree
    tp = page.get_textpage(flags=pymupdf.TEXTFLAGS_WORDS)
    words = page.get_text("words", textpage=tp)
    dirs = {}
    for b in page.get_text("dict", textpage=tp).get("blocks") or []:
        for n, ln in enumerate(b.get("lines") or []):
            dirs[(b.get("number"), n)] = ln.get("dir")
    if BOX_CUTS:
        kept = [f for f in found if not box_cuts(words, f[0], dirs)]
        if len(kept) < len(found):
            notes.append("a table's box cuts a word")
        found = kept
        if not found:
            return None, 0, notes
    blocks = [b for b in page.get_text("blocks", textpage=tp) if b[6] == 0]
    lines = defaultdict(list)                     # a block's lines: (block, line) -> its words
    for w in words:
        lines[(w[5], w[6])].append(w)
    of_block = defaultdict(list)
    for key in sorted(lines):
        of_block[key[0]].append(lines[key])
    owner, mine, before, after = {}, {}, {}, {}
    for b in blocks:
        bl = of_block.get(b[5])
        if not bl:
            continue
        # a caption stays where it stood, as text: its line and the lines that go on with it, each
        # alone on its height (PyMuPDF can hold a caption and the rows under it in one block, a cell
        # a line - a row is several lines side by side: VGG's Tables 3, 4 and 9)
        cut = next((n for n, ws in enumerate(bl) if CAPTION.match(" ".join(w[4] for w in ws))), len(bl))
        end = cut + 1 if cut < len(bl) else cut
        while end < len(bl) and alone(bl, end):
            end += 1
        ws = [w for ln in bl[:cut] + bl[end:] for w in ln]
        if not ws:
            continue
        for k, (box, _grid) in enumerate(found):
            inside = sum(1 for w in ws if box[0] - 2 <= (w[0] + w[2]) / 2.0 <= box[2] + 2
                         and box[1] - 2 <= (w[1] + w[3]) / 2.0 <= box[3] + 2)
            if inside * 2 >= len(ws):             # half its words' centres: blank lines widen a box
                owner[b[5]], mine[b[5]] = k, ws
                if cut < end:
                    said = "\n".join(" ".join(w[4] for w in ln) for ln in bl[cut:end]) + "\n"
                    (before if cut == 0 else after)[b[5]] = said
                break
    tables, around = {}, {}
    for k, (box, (xs, ys)) in enumerate(found):
        ws = [w for b in blocks if owner.get(b[5]) == k for w in mine[b[5]]]
        if not ws:
            continue
        put = fill(ws, xs, ys)
        if SPLIT_ROWS:
            rows_at = split_rows(put, ys)
            if rows_at is not ys:
                ys = rows_at
                put = fill(ws, xs, ys)
        gone = cut_lines(put, dirs) if CUT_LINES else set()
        if gone:
            # prose the column lines cut stays text, above the table or below it as it stands
            ws = [w for w in ws if (w[5], w[6]) not in gone]
            put = fill(ws, xs, ys)
            mid = (box[1] + box[3]) / 2.0
            said = {key: " ".join(w[4] for w in sorted(lines[key], key=lambda w: w[0])) for key in sorted(gone)}
            up = [key for key in sorted(gone) if (lines[key][0][1] + lines[key][0][3]) / 2.0 < mid]
            around[k] = ("".join(said[key] + "\n" for key in up),
                         "".join(said[key] + "\n" for key in sorted(gone) if key not in up))
            notes.append("%d lines of prose kept out of a table" % len(gone))
        rows = [[cell_text(put.get((r, c), ())) for c in range(len(xs) - 1)] for r in range(len(ys) - 1)]
        md = gfm_table(mend(put, rows, dirs))
        if md and wordbag(md) == wordbag(" ".join(w[4] for w in ws)):
            tables[k] = md
        elif md:
            notes.append("a table's cells are not its blocks' words")
    if not tables:
        return None, 0, notes
    out, done = [], set()
    for b in blocks:
        k = owner.get(b[5])
        if k not in tables:
            out.append(b[4])
            continue
        out.append(before.get(b[5], ""))
        if k not in done:
            done.add(k)
            pre, post = around.get(k, ("", ""))
            out.append(pre + "\n" + tables[k] + "\n\n" + post)
        out.append(after.get(b[5], ""))
    return "".join(out), len(done), notes


def markdown_pages(pymupdf4llm, doc, pages, heads):
    """pymupdf4llm's Markdown of some pages (page_chunks: a dict a page), its headings levelled by
    the heading sizes of every call so far (`heads`, kept by the caller for the document): a call
    levels them by its own pages alone, and a call without the title made Attention's "3.1 Encoder
    and Decoder Stacks" a level higher than one call over the whole paper did (40 lines). The
    first call holds the title, so the levels come out as one call's. pymupdf4llm 1.28's parts:
    when they are not there, its own call."""
    try:
        from pymupdf4llm.helpers import document_layout as dl
        parsed = dl.parse_document(doc, pages=pages, show_progress=False, embed_images=False, write_images=False,
                                   force_text=True, use_ocr=False, force_ocr=False)
        for page in parsed.pages:
            for box in page.boxes:
                if box.boxclass in ("title", "section-header") and getattr(box, "max_fontsize", 0):
                    heads.add(box.max_fontsize)
        if heads:
            dl.update_header_tags(parsed.pages, heads)
        return parsed.to_markdown(header=True, footer=True, write_images=False, embed_images=False, ignore_code=False,
                                  show_progress=False, page_separators=False, page_chunks=True)
    except (AttributeError, TypeError, ImportError, ValueError):
        return pymupdf4llm.to_markdown(doc, pages=pages, page_chunks=True, show_progress=False, use_ocr=False)


def watch_parent(pid):
    """End when the read's process PID ends. A read killed from outside - TerminateProcess by a
    harness that kills by PID, SIGKILL to its group as the MCP server's hard kill does - left this
    process at its page 18-24 s more, with its 200-300 MB (2026-11-21): stdin's end comes only
    after the page. Windows: a wait on the process itself (through the environment's venv
    launcher the parent is the launcher, so the read's own PID is given). A process that does not
    exist ends it at once (error 87); one the OS will not open for waiting (a sandbox that refuses
    SYNCHRONIZE: error 5) is not watched, and stdin's end stops this process with the read - it
    used to end here, and every PDF lost its tables with no word said. POSIX: the parent changes."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.WaitForSingleObject.restype = wintypes.DWORD
        ctypes.set_last_error(0)
        handle = k32.OpenProcess(0x00100000, False, pid)              # SYNCHRONIZE
        if handle:
            if k32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:        # INFINITE; WAIT_OBJECT_0
                os._exit(0)
            return
        if ctypes.get_last_error() == 87:                               # ERROR_INVALID_PARAMETER: no such process
            os._exit(0)
        # access denied (a sandbox may refuse SYNCHRONIZE, as it does for PID 4) or any other error:
        # the process cannot watch, so it is not told to end - stdin's end ends it with the read
        return
    if os.getppid() != pid:
        os._exit(0)
    while os.getppid() == pid:
        time.sleep(0.25)
    os._exit(0)


def main():
    t0, cpu0 = time.time(), time.process_time()
    args = sys.argv[1:]
    if "--parent" in args:
        try:
            pid = int(args[args.index("--parent") + 1])
        except (IndexError, ValueError):
            pid = 0
        if pid > 0:
            threading.Thread(target=watch_parent, args=(pid,), daemon=True).start()
    seam = os.environ.get("READ_PAGE_TEST_MODEL_PATH")
    if seam:
        sys.path.insert(0, seam)
    # the answers have stdout to themselves: what a library prints (PyMuPDF's messages go to
    # stdout) goes to stderr, at the level of the file descriptors too
    answers = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    lock = threading.Lock()
    waited = [(0.0, None)]          # the seconds spent waiting for a request, and since when it waits now
    said = {"busy": 0.0, "cpu": 0.0, "work": 0.0}      # at the last word said

    def pace():
        # how much of a CPU the process gets, from its own clock: the read lengthens the model's time
        # by it (a load or a page that waits for the CPU is no work done). A CPU second counts once
        # however many threads spent it: on 20 cores onnxruntime's import alone spent 1.5 CPU seconds
        # in 0.12 s (Linux), which hid the wait of a load behind it
        idle, since = waited[0]
        t = time.time()
        busy = t - t0 - idle - (t - since if since else 0.0)
        cpu = time.process_time() - cpu0
        said["work"] += max(0.0, min(cpu - said["cpu"], busy - said["busy"]))
        said["busy"], said["cpu"] = busy, cpu
        return {"busy": round(busy, 3), "work": round(said["work"], 3)}

    def say(obj):
        with lock:
            answers.write(json.dumps(dict(obj, **pace()), ensure_ascii=False) + "\n")
            answers.flush()

    def ticks():
        # the pace while the model loads or is at a page, when nothing else is said: four reads at
        # once on a Celeron's budget held its load alone 11-14 s
        while True:
            time.sleep(TICK)
            try:
                say({"tick": 1})
            except Exception:                                  # noqa: BLE001 - the answers' end: it is ending
                return
    threading.Thread(target=ticks, daemon=True).start()

    def why(e):
        return ("%s: %s" % (type(e).__name__, e))[:200]
    try:
        calm = calm_onnx()
        import pymupdf
        import pymupdf4llm
    except Exception as e:                                     # noqa: BLE001
        # pymupdf4llm 1.28 imports onnxruntime itself: without it neither tables nor Markdown
        say({"fatal": why(e)})
        return 0
    layout = bool(getattr(pymupdf4llm, "_use_layout", True))
    say({"ready": round(time.time() - t0, 2), "layout": layout})
    doc, path, heads = None, None, set()
    while True:
        waited[0] = (waited[0][0], time.time())
        line = sys.stdin.readline()
        idle, since = waited[0]
        waited[0] = (idle + time.time() - since, None)
        if not line:
            break
        try:
            req = json.loads(line)
            pages = [int(p) for p in req.get("pages") or []]
        except (ValueError, TypeError, AttributeError):
            continue
        try:
            if req.get("path") != path:
                if doc is not None:
                    doc.close()
                doc, path, heads = pymupdf.open(req.get("path")), req.get("path"), set()
        except Exception as e:                                 # noqa: BLE001
            doc, path = None, None
            for p in pages:
                say({"page": p, "error": why(e)})
            continue
        if req.get("markdown"):
            t = time.time()
            try:
                chunks = markdown_pages(pymupdf4llm, doc, pages, heads)
                each = round((time.time() - t) / max(1, len(pages)), 3)
                got = {}
                for ch in chunks or []:
                    n = ((ch.get("metadata") or {}).get("page_number") or (ch.get("metadata") or {}).get("page"))
                    if isinstance(n, int):
                        got[n - 1] = ch.get("text") or ""
                for p in pages:
                    if p in got:
                        say({"page": p, "text": got[p], "n": 0, "s": each})
                    else:
                        say({"page": p, "error": "no Markdown for this page"})
            except (ImportError, NotImplementedError) as e:
                say({"fatal": why(e)})
                return 0
            except Exception as e:                             # noqa: BLE001
                for p in pages:
                    say({"page": p, "error": why(e)})
            continue
        if not layout:
            say({"fatal": "pymupdf4llm has no layout model here (%s)" % (calm or "pymupdf.layout did not load")})
            continue
        for p in pages:
            t = time.time()
            try:
                text, n, notes = page_tables(doc, p)
                say({"page": p, "text": text, "n": n, "s": round(time.time() - t, 3), "notes": notes})
            except (ImportError, NotImplementedError) as e:      # the model does not work here
                say({"fatal": why(e)})
                return 0
            except Exception as e:                             # noqa: BLE001 - this page only
                say({"page": p, "error": why(e), "s": round(time.time() - t, 3)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
