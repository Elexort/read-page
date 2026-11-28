"""Formats. No network.

    python -X utf8 tests/formats.py

RTF and OpenDocument are known by their content - an RTF served as octet-stream, an ODT whose
`mimetype` is not EPUB's - and read by our own readers (docreaders.py, tests/docreaders.py). A file
on this machine goes through the same converters with no network; over MCP only one inside
read-page's own folders. --alternate reads a PDF with pymupdf4llm when it is installed
(headings as markdown). YouTube's caption track when yt-dlp gives none - youtube-transcript-api,
else a machine's own markitdown. Also a machine's own pandoc's Markdown cleaned
with code untouched, a DOCX's content controls and text boxes, a PPTX's groups and tables, a plain
ZIP's files and their text.
"""
import importlib.util
import io
import json
import os
import queue
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness import SCRIPT, Checks, run_read, serve     # noqa: E402

check = Checks()
SERVER = os.path.join(os.path.dirname(SCRIPT), "mcp_server.py")
EN = "The quarterly report shows steady growth across every region we measured this year. "
RTF = (b"{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Times New Roman;}}{\\*\\generator Test;}\\f0\\fs24 "
       b"{\\b RTF-HEADING}\\par " + (EN * 4).encode() + b" caf\\'e9 \\u1055?\\u1088?\\u1080?\\par "
       b"Second paragraph RTF-MARKER.\\par}")


SVG = (b'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="40" '
       b'height="40"><circle cx="20" cy="20" r="18" fill="teal"/></svg>')
ICO = b"\x00\x00\x01\x00\x01\x00\x10\x10\x00\x00\x01\x00 \x00" + b"\x00" * 60


def odt(path, mimetype="application/vnd.oasis.opendocument.text"):
    content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content '
               'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
               '<text:h text:outline-level="1">ODT-HEADING</text:h><text:p>%s</text:p>'
               '<text:p>Second paragraph ODT-MARKER.</text:p></office:text></office:body>'
               '</office:document-content>' % (EN * 4))
    manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest '
                'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
                '<manifest:file-entry manifest:full-path="/" manifest:media-type="%s"/></manifest:manifest>'
                % mimetype)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", content)
        z.writestr("META-INF/manifest.xml", manifest)


T_HEAD = ("Region", "North", "South", "West")
T_ROWS = [("Harbor", "610.01", "975.25", "844.22"), ("Lantern", "994.05", "443.74", "861.13"),
          ("Meadow", "51.20", "665.63", "724.03"), ("Copper", "311.90", "27.45", "5.08"),
          ("Violet", "78.30", "190.02", "66.41"), ("Timber", "402.77", "8.19", "930.60")]


def table_pdf(path, pages=1):
    """A page with text, a caption, a table of 7 rows under three rules, and text again."""
    import pymupdf
    doc = pymupdf.open()
    for n in range(1, pages + 1):
        pg = doc.new_page()
        pg.insert_text((72, 80), "TABLE-INTRO %d. %s" % (n, EN), fontsize=10)
        pg.insert_text((72, 96), EN, fontsize=10)
        pg.insert_text((72, 126), "Table %d: Results by region" % n, fontsize=10)
        y = 152
        pg.draw_line((72, y - 13), (470, y - 13))
        for k, row in enumerate([T_HEAD] + T_ROWS):
            for x, cell in zip((76, 230, 320, 410), row):
                pg.insert_text((x, y), cell, fontsize=10)
            if k == 0:
                pg.draw_line((72, y + 5), (470, y + 5))
            y += 18
        pg.draw_line((72, y - 9), (470, y - 9))
        pg.insert_text((72, y + 22), "TABLE-OUTRO %d. %s" % (n, EN), fontsize=10)
        pg.insert_text((72, y + 38), EN, fontsize=10)
    doc.save(path)
    doc.close()


def strokes_page(doc, strokes=0, numbers=0, seed=7):
    """A page that looks like a table (ten rulings and a few rows) with what the layout model
    takes long over: separate short strokes below it - a scatter plot drawn point by point, as
    plotting tools export one - and one block of small numbers."""
    import random
    rnd = random.Random(seed)
    pg = doc.new_page()
    sh = pg.new_shape()
    for k in range(10):
        sh.draw_line((72, 100 + 20 * k), (540, 100 + 20 * k))
        sh.finish(width=0.3, color=(0, 0, 0))
    for _ in range(strokes):
        x, y = rnd.uniform(72, 540), rnd.uniform(320, 760)
        sh.draw_line((x, y), (x + 1.5, y + 1.0))
        sh.finish(width=0.3, color=(0, 0, 0))
    sh.commit()
    for k in range(9):
        pg.insert_text((80, 115 + 20 * k), "Row %d   %d.%d   %d" % (k, k * 3, k, k * 7), fontsize=9)
    y, left = 320, numbers
    while left > 0:
        k = min(40, left)
        pg.insert_text((20, y), "  ".join("%d.%02d" % (rnd.randint(0, 999), rnd.randint(0, 99)) for _ in range(k)),
                       fontsize=3)
        left, y = left - k, y + 3.4
    return pg


# A page the stub model below cuts the way the real one did: a grid line through "Introduction",
# a row line through the header "Combined ConvNet models", the points of "5.1.2.1," and the comma
# of "$32,200" across lines, and the caption inside the table's box ("Table 1: ...").
CUT_ROWS = [("Section", "Combined ConvNet models", "Amount"), ("Introduction", "5.1.2.1, 5.1.7.1", "$32,200"),
            ("Approach", "6.2.1", "$24,150"), ("Results", "7.3", "$1,000")]
CUT_GRID = {"xs": [70, 100, 190, 300, 418, 470], "ys": [112, 132, 145, 160, 178, 196, 214]}
CUT_MODEL = ("Intr", "oduction", "5121 5171", "$32", "200", "Cbid CN dl")     # the model's own cells


def cut_pdf(path):
    import pymupdf
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 80), "CUT-INTRO a paragraph before the table, with words of its own.", fontsize=10)
    pg.insert_text((72, 126), "Table 1: Results by region", fontsize=10)
    for k, row in enumerate(CUT_ROWS):
        for x, cell in zip((72, 200, 405), row):            # lines at x 100, 300, 418 run through words
            pg.insert_text((x, 150 + 18 * k), cell, fontsize=10)
    pg.insert_text((72, 250), "CUT-OUTRO a paragraph after the table.", fontsize=10)
    doc.save(path)
    doc.close()


# A table with its notes inside the model's box: two footnotes under the rows, each across the
# column lines at mere spaces, in the grid's last row (EfficientNet's Table 5 came as "| †GPipe
# (Huang et ‡DAT denotes Transfer accuracy | al., 2018) trains ...").
NOTES = ("(a) GPipe trains giant models with a specialized pipeline parallelism library.",
         "(b) DAT denotes domain adaptive transfer learning on the target data.")    # the font has no dagger
NOTES_GRID = {"xs": [70, 190, 300, 420], "ys": [140, 155, 173, 191, 228]}


def notes_pdf(path):
    import pymupdf
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "NOTES-INTRO the paragraph before the table.", fontsize=10)
    for k, row in enumerate([("Model", "Params", "Acc."), ("GPipe", "556M", "84.3"), ("EffNet-B7", "66M", "84.3")]):
        for x, cell in zip((72, 200, 320), row):
            pg.insert_text((x, 151 + 18 * k), cell, fontsize=10)
    for k, note in enumerate(NOTES):
        pg.insert_text((72, 210 + 12 * k), note, fontsize=9)
    pg.insert_text((72, 270), "NOTES-OUTRO the paragraph after the table.", fontsize=10)
    doc.save(path)
    doc.close()


# Rows of the page two of which the model's grid holds as one (KNOWN-ISSUES 127): its second and third
# rows share a grid row, and its last a label over two lines beside one value
PAIRED = [("Task", "Metric", "Score"), ("LAMBADA", "acc", "68.0"), ("LAMBADA", "ppl", "8.63"), ("ARC", "acc", "78.5")]
PAIRED_GRID = {"xs": [70, 190, 300, 420], "ys": [140, 158, 194, 212, 246]}


def paired_pdf(path):
    import pymupdf
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "PAIRED-INTRO the paragraph before the table.", fontsize=10)
    for k, row in enumerate(PAIRED):
        for x, cell in zip((72, 200, 320), row):
            pg.insert_text((x, 151 + 18 * k), cell, fontsize=10)
    pg.insert_text((72, 223), "Average number of", fontsize=10)
    pg.insert_text((72, 237), "co-occurrences", fontsize=10)
    pg.insert_text((320, 223), "17.5", fontsize=10)
    pg.insert_text((72, 290), "PAIRED-OUTRO the paragraph after the table.", fontsize=10)
    doc.save(path)
    doc.close()


# Columns of the page two of which the model's grid holds as one (KNOWN-ISSUES 209, GPT-3's Table H.1: its 30
# columns in the model's 14, "43.6 51.0" under "Med Large"); a row is its cells, (x, text). A column whose cells
# hold two numbers under one name ("27.3 (0.4)" under "BLEU") is one column of the page, and so is one whose
# second numbers stand in no column of their own
MERGED = [[(72, "Task"), (200, "Small"), (260, "Med"), (320, "Large")],
          [(72, "HellaSwag"), (200, "33.7"), (260, "43.6"), (320, "51.0")],
          [(72, "LAMBADA"), (200, "42.7"), (260, "54.3"), (320, "60.4")],
          [(72, "StoryCloze"), (200, "63.3"), (260, "68.5"), (320, "72.4")],
          [(72, "NQs"), (200, "0.64"), (260, "1.75"), (320, "2.71")]]
MERGED_GRID = {"xs": [70, 190, 250, 420], "ys": [140, 158, 176, 194, 212, 230]}    # Med and Large: one column
ONE_NAME = [[(72, "Model"), (200, "BLEU")], [(72, "Base"), (200, "27.3 (0.4)")], [(72, "Big"), (200, "28.4 (0.3)")],
            [(72, "Deep"), (200, "26.9 (0.5)")], [(72, "Wide"), (200, "27.8 (0.2)")]]
ASKEW = [[(72, "Model"), (200, "Mean"), (260, "SD")], [(72, "Base"), (200, "27.3"), (255, "0.4")],
         [(72, "Big"), (200, "28.4"), (266, "1.3")], [(72, "Deep"), (200, "26.9"), (249, "0.5")],
         [(72, "Wide"), (200, "27.8"), (262, "0.2")]]
TWO_GRID = {"xs": [70, 190, 420], "ys": [140, 158, 176, 194, 212, 230]}


def cells_pdf(path, rows):
    import pymupdf
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "COLUMNS-INTRO the paragraph before the table.", fontsize=10)
    for k, row in enumerate(rows):
        for x, cell in row:
            pg.insert_text((x, 151 + 18 * k), cell, fontsize=10)
    pg.insert_text((72, 290), "COLUMNS-OUTRO the paragraph after the table.", fontsize=10)
    doc.save(path)
    doc.close()


# pymupdf4llm as the tests need it, first on the model's process' path (READ_PAGE_TEST_MODEL_PATH,
# which pdftables.py alone reads: the process runs with -E): the tables above with the model's own
# (cut) cells; a page that fails, a process that ends at a page, a page or a Markdown call that
# takes long; a model that does not load; one that waits - for the CPU, as a process does among
# others on a weak machine, its load or its pages taking long while it does nothing (sleep) - and
# one that works (a busy loop: its seconds are CPU seconds)
STUB = '''
import json, os, time
if os.environ.get("RP_STUB_NOLOAD"):
    raise ImportError("RP-STUB: no model here")
if os.environ.get("RP_STUB_LOAD_SLEEP"):
    time.sleep(float(os.environ["RP_STUB_LOAD_SLEEP"]))
if os.environ.get("RP_STUB_LOAD_EXIT"):          # "marker": the first process ends at its load at once, the rest 0.5 s in
    if not os.path.exists(os.environ["RP_STUB_LOAD_EXIT"]):
        open(os.environ["RP_STUB_LOAD_EXIT"], "w").close()
        os._exit(9)
    time.sleep(0.5)
    os._exit(9)
_use_layout = True
GRID = %s
MODEL = %s

def to_json(doc, pages, **kw):
    p = pages[0] if pages else -1
    if os.environ.get("RP_STUB_CRASH") == str(p):
        os._exit(9)
    once = (os.environ.get("RP_STUB_NOMEM") or "").split(":", 1)    # "page:marker": the first process there
    if len(once) == 2 and once[0] == str(p) and not os.path.exists(once[1]):
        open(once[1], "w").close()
        raise MemoryError("RP-STUB: no memory for this page")
    if os.environ.get("RP_STUB_SLEEP"):
        time.sleep(float(os.environ["RP_STUB_SLEEP"]))
    slow = json.loads(os.environ.get("RP_STUB_PAGE_SLEEP") or "{}")      # {"page": seconds more}
    if str(p) in slow:
        time.sleep(float(slow[str(p)]))
    if os.environ.get("RP_STUB_HANG") == str(p):            # at work and never done: no wait to lengthen its time
        t = time.time()
        while time.time() - t < 60:
            pass
    if os.environ.get("RP_STUB_BUSY"):
        t = time.time()
        while time.time() - t < float(os.environ["RP_STUB_BUSY"]):
            pass
    if os.environ.get("RP_STUB_FAIL") == str(p):
        raise ValueError("RP-STUB: a page the model cannot read")
    if not os.environ.get("RP_STUB_TABLE"):
        return json.dumps({"pages": [{"boxes": []}]})
    grid = json.loads(os.environ.get("RP_STUB_GRID") or "null") or GRID
    xs, ys = grid["xs"], grid["ys"]
    cells = [[[xs[c], ys[r], xs[c + 1], ys[r + 1]] for c in range(len(xs) - 1)] for r in range(len(ys) - 1)]
    extract = [[MODEL[(r + c) %% len(MODEL)] for c in range(len(xs) - 1)] for r in range(len(ys) - 1)]
    box = {"boxclass": "table", "table": {"bbox": [xs[0], ys[0], xs[-1], ys[-1]], "row_count": len(ys) - 1,
                                         "col_count": len(xs) - 1, "cells": cells, "extract": extract}}
    return json.dumps({"pages": [{"boxes": [box]}]})

def to_markdown(doc, pages=None, page_chunks=False, **kw):
    if os.environ.get("RP_STUB_MD_SLEEP"):
        time.sleep(float(os.environ["RP_STUB_MD_SLEEP"]))
    out = [{"metadata": {"page_number": p + 1}, "text": "# RP-STUB-MD %%d\\n\\n" %% (p + 1)} for p in pages or []]
    return out if page_chunks else "".join(c["text"] for c in out)
''' % (json.dumps(CUT_GRID), json.dumps(CUT_MODEL))


def wordbag(s):
    import collections
    import re
    import unicodedata
    return collections.Counter(re.findall(r"\w+", unicodedata.normalize("NFKC", s or "").lower()))


def row_whole(text, cells):
    """A line of the text that has the row's cells, in order."""
    for ln in text.splitlines():
        pos = 0
        for c in cells:
            pos = ln.find(c, pos) + len(c) if ln.find(c, pos) >= 0 else -1
            if pos < 0:
                break
        else:
            return True
    return False


def module():
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-fmt-")
    spec = importlib.util.spec_from_file_location("rp_fmt_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tmp = tempfile.mkdtemp(prefix="rp-formats-")
odt_path = os.path.join(tmp, "report.odt")
odt(odt_path)
with open(odt_path, "rb") as fh:
    ODT = fh.read()
s = serve({"/report.rtf": (200, {"Content-Type": "application/rtf"}, RTF),
           "/blob": (200, {"Content-Type": "application/octet-stream"}, RTF),
           "/report.odt": (200, {"Content-Type": "application/vnd.oasis.opendocument.text"}, ODT),
           "/odt-as-zip": (200, {"Content-Type": "application/zip"}, ODT),
           # pictures whose type is not PNG keep their own ending (an SVG was saved as raw.png)
           "/logo": (200, {"Content-Type": "image/svg+xml"}, SVG),
           "/favicon": (200, {"Content-Type": "image/vnd.microsoft.icon"}, ICO),
           "/scan.tiff": (200, {"Content-Type": "image/x-scan"}, b"II*\x00" + b"\x00" * 60)})
env = {"READ_PAGE_SKIP": "browser"}
try:
    mod = module()
    # ------------------------------------------------ RTF, by its content too
    for path in ("/report.rtf", "/blob"):
        r = run_read(s.url(path), env=env)
        text = r.file("content.md")
        check("RTF (%s) is read, its words and escapes decoded" % path,
              r.manifest.get("status") == "ok" and "RTF-MARKER" in text and "café" in text and "При" in text,
              "%s %s: %r" % (r.manifest.get("status"), (r.manifest.get("content") or {}).get("engine"), text[:80]))
    plain = mod.docreaders.rtf_plain(RTF)
    check("an RTF's plain text, when its reader breaks, keeps the words (docreaders.rtf_plain)",
          "RTF-MARKER" in plain and "fonttbl" not in plain and "Times New Roman" not in plain, repr(plain[:80]))

    # ------------------------------------------------ OpenDocument is not EPUB
    check("an ODT's mimetype is read, not taken for EPUB",
          mod.zip_subtype(odt_path) == "odt", mod.zip_subtype(odt_path))
    epub = os.path.join(tmp, "book.epub")
    odt(epub, "application/epub+zip")
    check("an EPUB is still an EPUB", mod.zip_subtype(epub) == "epub", mod.zip_subtype(epub))
    for path in ("/report.odt", "/odt-as-zip"):
        r = run_read(s.url(path), env=env)
        text = r.file("content.md")
        check("ODT (%s) is read with its heading" % path,
              r.manifest.get("status") == "ok" and "ODT-MARKER" in text and "ODT-HEADING" in text,
              "%s: %r" % (r.manifest.get("status"), text[:80]))
    ods_path = os.path.join(tmp, "labelled.ods")
    odt(ods_path, "application/vnd.oasis.opendocument.spreadsheet")      # a text's body, a sheet's type
    r = run_read(ods_path, env=dict(env, READ_PAGE_TRACE="1"))
    text = r.file("content.md")
    check("an ODS is our readers' too, in their process, and its body decides how (a text's here)",
          mod.zip_subtype(ods_path) == "ods" and text.startswith("# ODT-HEADING")
          and text.rstrip().endswith("ODT-MARKER.") and b"event=document.own" in r.err, repr(text[:60]))

    # ------------------------------------------------ a picture is saved under its own ending
    for path, want in (("/logo", ".svg"), ("/favicon", ".ico"), ("/scan.tiff", ".tiff")):
        r = run_read(s.url(path), env=env)
        media = (r.manifest.get("files") or {}).get("media") or ""
        check("a %s picture is saved as %s, not .png" % (path.strip("/"), want),
              r.manifest.get("status") == "media_only" and media.endswith(want) and os.path.isfile(media),
              "%s %s" % (r.manifest.get("status"), media))

    # ------------------------------------------------ a file on this machine, no network
    page = os.path.join(tmp, "notes.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write("<!doctype html><html><head><title>Notes</title></head><body><article><h1>Notes</h1>"
                 "<p>LOCAL-MARKER %s</p><img src='http://127.0.0.2:9/p.png' alt='remote'></article></body></html>"
                 % (EN * 5))
    r = run_read(page, env={})
    text = r.file("content.md")
    check("a local HTML file is read by path, with no network (the picture stays a marker)",
          r.manifest.get("status") == "ok" and "LOCAL-MARKER" in text
          and str((r.manifest.get("url") or {}).get("final", "")).startswith("file:")
          and not os.listdir(os.path.join(r.dir, "img")) if os.path.isdir(os.path.join(r.dir, "img")) else
          r.manifest.get("status") == "ok" and "LOCAL-MARKER" in text,
          "%s %s" % (r.manifest.get("status"), (r.manifest.get("url") or {}).get("final")))
    check("the file stays where it was", os.path.isfile(page), page)
    r = run_read("file:///" + odt_path.replace("\\", "/").lstrip("/"), env={})
    check("a file:// URL of an ODT goes through the same converter",
          r.manifest.get("status") == "ok" and "ODT-MARKER" in r.file("content.md"),
          str(r.manifest.get("status")))
    r = run_read(os.path.join(tmp, "no-such-file.pdf"), env={})
    check("a path that is no file is a wrong call (exit 2), not a URL guess",
          r.rc == 2 and b"no such file" in r.err.lower() or r.rc == 2, "rc=%s %s" % (r.rc, r.err[-80:]))

    # ------------------------------------------------ over MCP: only inside read-page's folders
    proc = subprocess.Popen([sys.executable, "-X", "utf8", SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=dict(os.environ, READ_PAGE_CACHE=os.path.join(tmp, "mcp")))
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(x) for x in proc.stdout] + [lines.put(None)], daemon=True).start()

    def call(i, args):
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                      "params": {"name": "read_url", "arguments": args}}) + "\n").encode())
        proc.stdin.flush()
        line = lines.get(timeout=120)
        return json.loads(line) if line else {}
    try:
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "f", "version": "0"}}})
            + "\n").encode())
        proc.stdin.flush()
        lines.get(timeout=30)
        got = call(2, {"url": page})
        res = got.get("result") or {}
        said = " ".join(b.get("text", "") for b in res.get("content") or [])
        check("MCP: a file outside read-page's folders is refused",
              res.get("isError") and "own folders" in said and "LOCAL-MARKER" not in said, said[:90])
        inside = os.path.join(tmp, "mcp", "pages", "mine")
        os.makedirs(inside, exist_ok=True)
        own = os.path.join(inside, "notes.html")
        with open(page, encoding="utf-8") as a, open(own, "w", encoding="utf-8") as b:
            b.write(a.read())
        got = call(3, {"url": own})
        said = " ".join(b.get("text", "") for b in (got.get("result") or {}).get("content") or [])
        check("MCP: a file in a page folder of its cache is read", "LOCAL-MARKER" in said, said[:90])
    finally:
        proc.stdin.close()
        proc.wait(timeout=20)

    # ------------------------------------------------ --alternate reads a PDF with pymupdf4llm
    try:
        import pymupdf
        import pymupdf4llm                                   # noqa: F401
        pdf = os.path.join(tmp, "paper.pdf")
        doc = pymupdf.open()
        pg = doc.new_page()
        pg.insert_text((72, 90), "PDF-TITLE Results", fontsize=24)
        for i in range(12):
            pg.insert_text((72, 140 + i * 18), "Body line %d of the paper, plain text. %s" % (i, EN[:40]), fontsize=10)
        doc.save(pdf)
        doc.close()
        r = run_read(pdf, "--alternate", env=env)
        text = r.file("content.md")
        check("--alternate gives the PDF's title as a markdown heading (pymupdf4llm)",
              r.manifest.get("status") == "ok" and any(ln.startswith("#") and "PDF-TITLE" in ln
                                                       for ln in text.splitlines()), repr(text[:80]))
    except ImportError:
        check.skip("pymupdf4llm", "pymupdf4llm is not installed here")

    # ------------------------------------------------ a PDF's tables, without a flag
    # PyMuPDF's text has a table one cell a line. Where pymupdf4llm's layout model is installed,
    # the pages that look like they hold a table get its tables as rows, in the text as it was.
    # The read runs in the environment when there is one, so what it has is asked of its answer
    try:
        import pymupdf                                       # noqa: F811
        tpdf = os.path.join(tmp, "table.pdf")
        table_pdf(tpdf)
        r = run_read(tpdf, env=env)
        text = r.file("content.md")
        tab = (r.manifest.get("signals") or {}).get("tables") or {}
        hint = [i for i in r.manifest.get("improve") or [] if i.get("what") == "tables"]
        model_here = not hint                                # the layout model where the read runs
        if hint:
            check("a PDF's table without the layout model: plain text, and `improve` names the pages and the fix",
                  not tab and "610.01" in text and "1 page" in hint[0].get("gain", "") and hint[0].get("fix"),
                  json.dumps(hint))
            check.skip("a PDF's tables in a read", "no pymupdf4llm where the read runs")
        else:
            check("a PDF's table: a row's cells stand on one line, in order",
                  row_whole(text, T_HEAD) and row_whole(text, T_ROWS[0]) and row_whole(text, T_ROWS[5]),
                  repr(text[170:420]))
            check("a PDF's table: each number is the PDF's own, once (no decimal point moved, nothing twice)",
                  all(text.count(c) == 1 for row in T_ROWS for c in row[1:]),
                  str([c for row in T_ROWS for c in row[1:] if text.count(c) != 1]))
            check("a PDF's table: the caption and the text around it stay, once",
                  all(text.count(x) == 1 for x in ("TABLE-INTRO 1", "TABLE-OUTRO 1", "Table 1: Results by region")),
                  repr(text[:120]))
            check("a PDF's table: the manifest names the pages laid out",
                  tab.get("pages") == "1" and not tab.get("left"), str(tab))
            r = run_read(tpdf, env=dict(env, READ_PAGE_SKIP=env["READ_PAGE_SKIP"] + ",tables"))
            t2 = r.file("content.md")
            check("READ_PAGE_SKIP=tables: PyMuPDF's text as before, one cell a line",
                  not row_whole(t2, T_ROWS[0]) and "610.01" in t2
                  and "tables" not in (r.manifest.get("signals") or {}), repr(t2[170:300]))
        prose = os.path.join(tmp, "prose.pdf")
        doc = pymupdf.open()
        pg = doc.new_page()
        for i in range(30):
            pg.insert_text((72, 80 + i * 18), "PROSE line %d. %s" % (i, EN[:60]), fontsize=10)
        doc.save(prose)
        doc.close()
        r = run_read(prose, env=env)
        check("a PDF with no sign of a table: nothing is said of tables",
              "tables" not in (r.manifest.get("signals") or {}) and "PROSE line 29" in r.file("content.md")
              and not [i for i in r.manifest.get("improve") or [] if i.get("what") == "tables"],
              str((r.manifest.get("signals") or {}).get("tables")))
        mod3 = module()
        dp = pymupdf.open(prose)
        got = mod3.pdf_tables(prose, dp, [p.get_text() for p in dp])
        check("... and the model is not asked: its process is not even started",
              got == {} and not mod3._TABLES.get("pool") and mod3._TABLES.get("worker") is None, str(got))
        said = mod3.tables_advice({"pages": [1], "left": [2, 3], "asked": 1, "secs": 1.0, "of": 3})
        check("a PDF's tables: the advice names the pages left and --download, which gives the model the time",
              "pages 2-3" in said and "--download" in said and "about 3 s" in said
              and mod3.tables_advice({"pages": [1, 2, 3], "left": [], "asked": 3, "secs": 1.0, "of": 3}) == "", said)
        said = mod3.tables_advice({"left": [1, 4], "heavy": [1], "asked": 2, "secs": 1.0, "of": 4,
                                   "files": [{"name": "b.pdf", "left": [2]}]})
        check("... a page too heavy for a read's time, and a PDF inside an archive, by its name",
              "page 1 (too heavy" in said and "page 4 (the time" in said and "page 2 of b.pdf" in said
              and "--download" in said, said)

        # whole words in the model's grid: a stub model with the cuts the real one made
        pt = mod3.pdftables
        cut = os.path.join(tmp, "cut.pdf")
        cut_pdf(cut)
        import types
        stub = types.ModuleType("pymupdf4llm")
        os.environ["RP_STUB_TABLE"] = "1"
        exec(STUB, stub.__dict__)
        real4llm = sys.modules.get("pymupdf4llm")
        sys.modules["pymupdf4llm"] = stub
        try:
            dc = pymupdf.open(cut)
            plain_cut = dc[0].get_text()
            out, n, _notes = pt.page_tables(dc, 0)
        finally:
            os.environ.pop("RP_STUB_TABLE", None)
            if real4llm is not None:
                sys.modules["pymupdf4llm"] = real4llm
            else:
                sys.modules.pop("pymupdf4llm", None)
        out = out or ""
        rows_md = [ln for ln in out.splitlines() if ln.startswith("|")]
        check("a PDF's table: a word a grid line runs through stands whole, in one cell, its points and "
              "commas kept (not \"Intr | oduction\", \"5121\", \"$32200\")",
              n == 1 and any("| Introduction |" in ln and "| 5.1.2.1, 5.1.7.1 |" in ln and "$32,200" in ln
                             for ln in rows_md)
              and not any("| %s |" % x in out for x in CUT_MODEL), repr(out[:400]))
        check("... a header a row line runs through stays one line, one cell (not \"Cbid CN dl\")",
              any("| Combined ConvNet models |" in ln for ln in rows_md), repr(rows_md[:2]))
        check("... every word of the page once: none lost, none twice",
              wordbag(out) == wordbag(plain_cut), str((wordbag(plain_cut) - wordbag(out), wordbag(out) - wordbag(plain_cut))))
        check("a PDF's table: its caption inside the model's box stays a line of text, once, before the table",
              out.count("Table 1: Results by region") == 1 and "Table 1: Results by region\n" in out
              and out.index("Table 1:") < out.index("| Section")
              and not any("Table" in ln for ln in rows_md), repr(out[:200]))
        # cells that one header spans are joined by the gap between their words alone
        w = [(10, 10, 60, 20, "Model", 0, 0, 0), (100, 10, 140, 20, "BLEU", 0, 0, 1),
             (200, 10, 215, 20, "3.3", 0, 0, 2), (217, 10, 221, 20, "·", 0, 0, 3), (224, 10, 250, 20, "1018", 0, 0, 4),
             (300, 10, 330, 20, "27.3", 0, 0, 5), (360, 10, 390, 20, "38.1", 0, 0, 6)]
        xs, ys = [0, 90, 120, 190, 222.5, 280, 345, 400], [8, 22]
        put = pt.fill(w, xs, ys)
        rows = [[pt.cell_text(put.get((0, c), ())) for c in range(len(xs) - 1)]]
        got = pt.mend(put, rows)
        check("a PDF's table: a value one cell spans is put back together, its neighbours left alone",
              got == [["Model", "", "BLEU", "3.3 · 1018", "", "27.3", "38.1"]], str(got))
        two = [(40, 10, 70, 16, "Comp", 0, 0, 0), (40, 18, 70, 24, "Acc.", 0, 1, 0), (72, 10, 100, 16, "arison", 0, 0, 1)]
        put = pt.fill(two, [0, 70, 140], [8, 30])
        rows = [[pt.cell_text(put.get((0, c), ())) for c in range(2)]]
        check("... but not cells of two lines (a spanning line above cells of their own)",
              pt.mend(put, rows) == rows, str(pt.mend(put, rows)))
        side = [(100, 10, 112, 42, "Caltech101", 0, 0, 0), (113, 10, 125, 41, "CIFAR-100", 0, 0, 1)]
        put = pt.fill(side, [90, 112.5, 140], [8, 44])
        rows = [[pt.cell_text(put.get((0, c), ())) for c in range(2)]]
        check("... nor two headers set on their side, side by side (ViT's Caltech101 and CIFAR-100)",
              pt.mend(put, rows) == [["Caltech101", "CIFAR-100"]], str(pt.mend(put, rows)))
        check("a PDF's table: a box that cuts a word of the page is no table of its text - not a word on its side",
              pt.box_cuts([(80, 50, 130, 60, "Melbourne")], [100, 40, 400, 200])
              and not pt.box_cuts([(104, 50, 150, 60, "Melbourne"), (60, 50, 99, 60, "To:")], [100, 40, 400, 200])
              and not pt.box_cuts([(395, 45, 408, 120, "Cryptographic")], [100, 40, 400, 200]), "")
        put = pt.fill([(500, 50, 520, 60, "far", 0, 0, 0), (0, 0, 5, 5, "corner", 0, 0, 1)], [100, 200, 300], [40, 80, 120])
        check("a PDF's table: a word outside the grid goes to the nearest cell (found by bisection)",
              [w[4] for w in put.get((0, 1), [])] == ["far"] and [w[4] for w in put.get((0, 0), [])] == ["corner"],
              str(dict(put)))

        # prose and notes inside the model's box that its column lines cut at mere spaces stay text
        nts = os.path.join(tmp, "notes.pdf")
        notes_pdf(nts)
        os.environ.update(RP_STUB_TABLE="1", RP_STUB_GRID=json.dumps(NOTES_GRID))
        sys.modules["pymupdf4llm"] = stub
        try:
            dn = pymupdf.open(nts)
            plain_notes = dn[0].get_text()
            out_n, n_n, _notes = pt.page_tables(dn, 0)
        finally:
            for k in ("RP_STUB_TABLE", "RP_STUB_GRID"):
                os.environ.pop(k, None)
            if real4llm is not None:
                sys.modules["pymupdf4llm"] = real4llm
            else:
                sys.modules.pop("pymupdf4llm", None)
        out_n = out_n or ""
        check("a PDF's table: a footnote the column lines cut at its spaces stays one line of text, once, after "
              "the table (not \"| (a) GPipe trains giant\\n(b) DAT denotes | ...\")",
              n_n == 1 and all(out_n.splitlines().count(note) == 1 for note in NOTES)
              and out_n.index(NOTES[0]) > out_n.index("| Model") and "| GPipe | 556M | 84.3 |" in out_n
              and wordbag(out_n) == wordbag(plain_notes), repr(out_n[:500]))
        # KNOWN-ISSUES 127: two rows of the page in one row of the model's grid keep their pairing
        prd = os.path.join(tmp, "paired.pdf")
        paired_pdf(prd)
        os.environ.update(RP_STUB_TABLE="1", RP_STUB_GRID=json.dumps(PAIRED_GRID))
        sys.modules["pymupdf4llm"] = stub
        try:
            dp_ = pymupdf.open(prd)
            plain_p = dp_[0].get_text()
            out_p, n_p, _notes = pt.page_tables(dp_, 0)
        finally:
            for k in ("RP_STUB_TABLE", "RP_STUB_GRID"):
                os.environ.pop(k, None)
            if real4llm is not None:
                sys.modules["pymupdf4llm"] = real4llm
            else:
                sys.modules.pop("pymupdf4llm", None)
        out_p = out_p or ""
        check("127: two rows of the page in one row of the model's grid are two rows (GPT-3's \"LAMBADA LAMBADA | "
              "acc ppl\")", n_p == 1 and "| LAMBADA | acc | 68.0 |" in out_p and "| LAMBADA | ppl | 8.63 |" in out_p
              and wordbag(out_p) == wordbag(plain_p), repr(out_p[:400]))
        check("... and a label of two lines beside one value stays one row (its lines are no items of one kind)",
              any("Average number of" in ln and "co-occurrences" in ln and "17.5" in ln
                  for ln in out_p.splitlines() if ln.startswith("|")), repr(out_p[-200:]))
        # KNOWN-ISSUES 209: two columns of the page in one column of the model's grid are two again
        cols = {}
        for key, rows_c, grid_c in (("merged", MERGED, MERGED_GRID), ("one", ONE_NAME, TWO_GRID),
                                    ("askew", ASKEW, TWO_GRID)):
            cpdf = os.path.join(tmp, "cols-%s.pdf" % key)
            cells_pdf(cpdf, rows_c)
            os.environ.update(RP_STUB_TABLE="1", RP_STUB_GRID=json.dumps(grid_c))
            sys.modules["pymupdf4llm"] = stub
            try:
                dcol = pymupdf.open(cpdf)
                out_c, n_c, _notes = pt.page_tables(dcol, 0)
                cols[key] = (out_c or "", n_c, dcol[0].get_text())
            finally:
                for k in ("RP_STUB_TABLE", "RP_STUB_GRID"):
                    os.environ.pop(k, None)
                if real4llm is not None:
                    sys.modules["pymupdf4llm"] = real4llm
                else:
                    sys.modules.pop("pymupdf4llm", None)
        out_c, n_c, plain_c = cols["merged"]
        check("209: two columns of the page in one column of the model's grid are two, each name over its numbers "
              "(GPT-3's \"Med Large | 43.6 51.0\")",
              n_c == 1 and "| Task | Small | Med | Large |" in out_c and "| HellaSwag | 33.7 | 43.6 | 51.0 |" in out_c
              and "| NQs | 0.64 | 1.75 | 2.71 |" in out_c and wordbag(out_c) == wordbag(plain_c), repr(out_c[:400]))
        check("... but a column of two numbers a cell under one name is one (\"27.3 (0.4)\" under \"BLEU\"), and so is "
              "one whose second numbers stand in no column of their own",
              "| Base | 27.3 (0.4) |" in cols["one"][0] and "| Base | 27.3 0.4 |" in cols["askew"][0],
              repr((cols["one"][0][:300], cols["askew"][0][:300])))
        # a word is on its side by its line's direction; its box only when no direction is known
        flat_d, side_d = {(0, 0): (1.0, 0.0)}, {(0, 0): (0.0, -1.0)}
        short = (10, 0, 20, 30, "the", 0, 0, 0)
        check("a PDF's table: a short word in a tall box on a horizontal line is not on its side (821 were); "
              "on a line that runs up it is",
              not pt.vertical(short, flat_d) and pt.vertical(short, side_d) and pt.vertical(short), "")
        sept = [(10, 10, 60, 22, "September", 0, 0, 0), (62, 10, 70, 22, "28,", 0, 0, 1), (72, 10, 80, 22, "2024", 0, 0, 2)]
        put = pt.fill(sept, [0, 71, 120], [8, 24])
        rows = [[pt.cell_text(put.get((0, c), ())) for c in range(2)]]
        check("... so a date split by a column line is joined again (Apple's \"September 28, | 2024\")",
              pt.mend(put, rows, {(0, 0): (1.0, 0.0)}) == [["September 28, 2024", ""]],
              str(pt.mend(put, rows, {(0, 0): (1.0, 0.0)})))

        # the model's process: a failed page does not stop the others, and an error is said
        stubdir = tempfile.mkdtemp(prefix="rp-stub-")
        with open(os.path.join(stubdir, "pymupdf4llm.py"), "w", encoding="utf-8") as fh:
            fh.write(STUB)
        many = os.path.join(tmp, "tables3.pdf")
        table_pdf(many, pages=3)
        os.environ["READ_PAGE_TEST_MODEL_PATH"] = stubdir
        try:
            os.environ["RP_STUB_FAIL"] = "0"
            mod3.tables_reset()
            d3 = pymupdf.open(many)
            info = mod3.pdf_tables(many, d3, [p.get_text() for p in d3])
            check("a PDF's tables: a page the model fails on is said, and the next pages are still asked",
                  info.get("asked") == 3 and "page 1" in (info.get("error") or "") and "RP-STUB" in info["error"],
                  str(info))
            os.environ.pop("RP_STUB_FAIL", None)
            mod3.tables_close(kill=True)
            os.environ.update(RP_STUB_CRASH="1", READ_PAGE_TEST_CPUS="1")       # one CPU: one process
            mod3.tables_reset()
            info = mod3.pdf_tables(many, d3, [p.get_text() for p in d3])
            check("a PDF's tables: when the model's process ends at a page, and the one started after it too, that "
                  "page and the ones after it are named, as the time's end names them",
                  info.get("asked") == 1 and info.get("left") == [2, 3] and info.get("stopped") == [2, 3]
                  and "process ended" in (info.get("error") or "")
                  and "pages 2-3 are still one cell a line (the layout model did not work" in mod3.tables_advice(info),
                  "%s | %s" % (info, mod3.tables_advice(info)))
            mod3.tables_close(kill=True)
            # KNOWN-ISSUES 242: as many model processes as the CPUs and the memory hold, a page each from one queue
            # (READ_PAGE_TEST_CPUS and READ_PAGE_TEST_MEMORY stand in for the machine: the suites never squeeze its
            # memory). A process that dies at a page, or hangs, loses that page alone; the others are laid out
            big = json.dumps({"phys": 64 << 30, "commit": 64 << 30})
            os.environ.update(READ_PAGE_TEST_CPUS="4", READ_PAGE_TEST_MEMORY=big)
            mod3.tables_reset()
            info = mod3.pdf_tables(many, d3, [p.get_text() for p in d3])
            check("242: a process that dies at a page loses that page alone, which is named; the others laid out",
                  info.get("asked") == 2 and info.get("left") == [2] and info.get("stopped") == [2]
                  and (info.get("procs") or 0) >= 2 and "process ended" in (info.get("error") or ""), str(info))
            os.environ.pop("RP_STUB_CRASH", None)
            mod3.tables_close(kill=True)
            os.environ["RP_STUB_HANG"] = "1"
            keep_hang, mod3.PDF_TABLES_SECONDS = mod3.PDF_TABLES_SECONDS, 3.0
            mod3.tables_reset()
            info = mod3.pdf_tables(many, d3, [p.get_text() for p in d3])
            mod3.PDF_TABLES_SECONDS = keep_hang
            os.environ.pop("RP_STUB_HANG", None)
            mod3.tables_close(kill=True)
            check("... and one that hangs at a page loses that page alone when the time is up",
                  info.get("asked") == 2 and info.get("left") == [2] and info.get("secs", 99) < 8, str(info))
            six_p = os.path.join(tmp, "tables6-pool.pdf")
            table_pdf(six_p, pages=6)
            d6p = pymupdf.open(six_p)
            # pages slow enough that more processes pay for their load; their pace as on CPUs of their own (a
            # sleeping stand-in reads as starved, READ_PAGE_TEST_PACE stands in for its measure)
            os.environ.update(RP_STUB_SLEEP="1.5", READ_PAGE_TEST_PACE="1")
            mod3.tables_reset()
            texts6 = [p.get_text() for p in d6p]
            info = mod3.pdf_tables(six_p, d6p, texts6)

            def threads_of():
                """The onnxruntime threads each of the read's model processes was started with."""
                return [a[a.index("--threads") + 1] if "--threads" in a else "-"
                        for a in (list(w.p.args) for w in mod3._TABLES.get("pool") or [])]
            got_threads = threads_of()
            check("242: on 4 CPUs three processes (85 %) lay out the pages, every one asked, each with a thread",
                  info.get("procs") == 3 and info.get("asked") == 6 and not info.get("left")
                  and got_threads == ["1"] * 3, "%s %s" % (info, got_threads))
            mod3.tables_close(kill=True)
            # the tables land on their own pages, in page order, whatever order the processes end them in (the
            # first page the slowest, so a later one is done before it)
            os.environ.update(RP_STUB_TABLE="1", RP_STUB_PAGE_SLEEP=json.dumps({"0": 3.0}))
            mod3.tables_reset()
            texts_t = list(texts6)
            info = mod3.pdf_tables(six_p, d6p, texts_t)
            mod3.tables_close(kill=True)
            for k in ("RP_STUB_TABLE", "RP_STUB_PAGE_SLEEP"):
                os.environ.pop(k, None)
            own_page = [("TABLE-INTRO %d." % (k + 1)) in t and "TABLE-INTRO %d." % (k + 2) not in t
                        and row_whole(t, T_ROWS[0]) and "\n|" in t for k, t in enumerate(texts_t)]
            check("242: the tables of several processes land on their own pages, in page order, a slow first page "
                  "and all", info.get("pages") == [1, 2, 3, 4, 5, 6] and info.get("tables") == 6
                  and (info.get("procs") or 0) >= 2 and all(own_page), "%s %s" % (info, own_page))
            # one that runs out of memory at a page gives it back: another lays it out, and none more starts
            marker = os.path.join(tmp, "nomem-once")
            os.environ["RP_STUB_NOMEM"] = "2:" + marker
            mod3.tables_reset()
            info = mod3.pdf_tables(six_p, d6p, list(texts6))
            mod3.tables_close(kill=True)
            os.environ.pop("RP_STUB_NOMEM", None)
            check("... and one that runs out of memory at a page gives it back: another lays it out, and no more "
                  "processes start", os.path.exists(marker) and info.get("asked") == 6 and not info.get("left")
                  and info.get("procs") == 2 and not info.get("error"), str(info))
            os.environ["READ_PAGE_TEST_PACE"] = "3"        # three times slower than on CPUs of their own
            mod3.tables_reset()
            info = mod3.pdf_tables(six_p, d6p, list(texts6))
            mod3.tables_close(kill=True)
            os.environ.pop("READ_PAGE_TEST_PACE", None)
            check("... but two processes that already wait for the CPU start no third: it would only share it",
                  info.get("procs") == 2 and info.get("asked") == 6 and not info.get("left"), str(info))
            os.environ.update(RP_STUB_SLEEP="0.4", READ_PAGE_TEST_MEMORY=json.dumps({"phys": 600 << 20,
                                                                                      "commit": 64 << 30}))
            mod3.tables_reset()
            info = mod3.pdf_tables(six_p, d6p, list(texts6))
            got_threads = threads_of()
            mod3.tables_close(kill=True)
            check("... and where the free memory holds one process alone (80 % of 600 MB), one does it all, with the "
                  "four CPUs for its onnxruntime", info.get("procs") == 1 and info.get("asked") == 6
                  and not info.get("left") and got_threads == ["4"], "%s %s" % (info, got_threads))
            # KNOWN-ISSUES 281: a lone process's onnxruntime threads are capped - 20 threads took GPT-3's pages no faster
            # than 8 for 25 % more CPU - and pdftables' own default (no share from the read: --alternate) is the same
            os.environ["READ_PAGE_TEST_CPUS"] = "20"
            mod3.tables_reset()
            info = mod3.pdf_tables(six_p, d6p, list(texts6))
            got_threads = threads_of()
            mod3.tables_close(kill=True)
            os.environ["READ_PAGE_TEST_CPUS"] = "4"
            own = getattr(pt, "threads_for", None)
            check("281: ... on 20 CPUs that one process gets 8 threads, not 20; pdftables' own default is 8 at most",
                  info.get("procs") == 1 and info.get("asked") == 6 and got_threads == ["8"] and own is not None
                  and own(0) == min(8, pt.cpus()) and own(20) == 8 and own(3) == 3,
                  "%s %s %s" % (info, got_threads, [own(0), own(20), own(3)] if own else "no threads_for"))
            # several reads count together: the processes another read has started and not yet measured take
            # their figures from the same memory, as the note in the cache says
            os.environ["READ_PAGE_TEST_MEMORY"] = json.dumps({"phys": 3 << 30, "commit": 64 << 30})
            other = {"pid": os.getpid(), "read": os.getpid(), "ram": 1 << 30, "commit": 1 << 30, "said": False}
            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            gone_one = dict(other, pid=dead.pid)
            note = getattr(mod3, "tables_note", None) or (lambda change=None: [])     # (none before 242)
            note(lambda e: e.extend([dict(other), dict(other), gone_one]))
            mod3.tables_reset()
            info = mod3.pdf_tables(six_p, d6p, list(texts6))
            mod3.tables_close(kill=True)
            left_note = note()
            note(lambda e: e.__setitem__(slice(None), [x for x in e if x.get("pid") != os.getpid()]))
            check("... and another read's two processes still to grow leave this one a single process; a process "
                  "that ended is dropped from the note", info.get("procs") == 1 and info.get("asked") == 6
                  and not any(x.get("pid") == dead.pid for x in left_note)
                  and sum(1 for x in left_note if x.get("pid") == os.getpid()) == 2, "%s %s" % (info, left_note))
            # ... and processes that have laid a page out count as what one takes at most, not as what their first
            # page took: they grow over their pages (GPT-3's from 0.25 to 0.45 GB), and a laptop's commit with them
            os.environ["READ_PAGE_TEST_MEMORY"] = json.dumps({"phys": 2 << 30, "commit": 64 << 30})
            small = dict(other, ram=256 << 20, commit=256 << 20, said=True)
            note(lambda e: e.extend([dict(small), dict(small)]))
            mod3.tables_reset()
            info = mod3.pdf_tables(six_p, d6p, list(texts6))
            mod3.tables_close(kill=True)
            note(lambda e: e.__setitem__(slice(None), [x for x in e if x.get("pid") != os.getpid()]))
            check("... and another read's two processes that said 256 MB after a page count as 512 each (80 % of "
                  "2 GB holds one more): one process here", info.get("procs") == 1 and info.get("asked") == 6
                  and not info.get("left"), str(info))

            # row 237's pace with several processes: theirs together, less the crowding they make among themselves on
            # few CPUs - two model processes on two E-cores wait 35-40 % by each other alone, and taken for other work
            # that kept the step 15-17 s instead of 10 there (KNOWN-ISSUES 288; not the main thread's, 0.2 CPU s)
            class FakeProc:
                def __init__(self, busy, work):
                    self.busy, self.work = busy, work
            keep_pool = list(mod3._TABLES["pool"])
            os.environ["READ_PAGE_TEST_CPUS"] = "2"
            try:
                paces = []
                for procs in ([FakeProc(3.0, 2.0)] * 2, [FakeProc(3.0, 2.0)], [FakeProc(6.0, 2.0)] * 2):
                    mod3._TABLES["pool"][:] = procs
                    paces.append(mod3.tables_pace())
            finally:
                mod3._TABLES["pool"][:] = keep_pool
                os.environ.pop("READ_PAGE_TEST_CPUS", None)
            check("242: two processes and the read on 2 CPUs crowd each other 1.5 times: they keep the 10 s; one "
                  "process that slow gets 1.5 times them, two three times slower twice",
                  paces[0] == 1.0 and abs(paces[1] - 1.5) < 0.01 and abs(paces[2] - 2.0) < 0.01, str(paces))

            # KNOWN-ISSUES 284, 285: a Linux cgroup's CPU quota bounds the CPUs a read counts (a container given two
            # CPUs of 32 started 27 processes), and the memory rule's cgroup room is the smallest from the read's
            # cgroup up to the root, found too in a container without its own cgroup namespace. READ_PAGE_TEST_CGROUP
            # is a folder that stands for /, with proc/self/cgroup and sys/fs/cgroup in it, on any OS
            def fake_cgroup(name, self_cgroup, files):
                root = os.path.join(tmp, "cgroup-" + name)
                for rel, text in dict(files, **{"proc/self/cgroup": self_cgroup}).items():
                    p = os.path.join(root, *rel.split("/"))
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "w", encoding="ascii") as fh:
                        fh.write(text)
                return root
            G = 1 << 30
            fs = "sys/fs/cgroup/"
            v2_parent = fake_cgroup("v2p", "0::/a/b\n", {
                fs + "a/memory.max": str(3 * G), fs + "a/memory.current": str(G), fs + "a/b/memory.max": "max",
                fs + "a/b/memory.current": str(G // 2), fs + "a/cpu.max": "150000 100000", fs + "a/b/cpu.max": "max 100000"})
            v1_no_ns = fake_cgroup("v1n", "4:memory:/docker/abc\n3:cpu,cpuacct:/docker/abc\n", {
                fs + "memory/memory.limit_in_bytes": str(2 * G), fs + "memory/memory.usage_in_bytes": str(G),
                fs + "cpu,cpuacct/cpu.cfs_quota_us": "50000", fs + "cpu,cpuacct/cpu.cfs_period_us": "100000"})
            v1_pod = fake_cgroup("v1p", "4:memory:/k/pod/c\n", {
                fs + "memory/k/pod/memory.limit_in_bytes": str(2 * G), fs + "memory/k/pod/memory.usage_in_bytes": str(G + G // 2),
                fs + "memory/k/pod/c/memory.limit_in_bytes": "9223372036854771712",
                fs + "memory/k/pod/c/memory.usage_in_bytes": str(G)})
            no_limit = fake_cgroup("none", "0::/\n", {fs + "cpu.max": "max 100000"})
            cg_many = fake_cgroup("many", "0::/\n", {fs + "cpu.max": "6400000 100000"})
            room = getattr(mod3.hostmem, "cgroup_room", None)
            quota = getattr(mod3.hostmem, "cgroup_cpus", None)
            got = ([room(r) for r in (v2_parent, v1_no_ns, v1_pod, no_limit)] if room else ["no cgroup_room"]) + (
                [quota(r) for r in (v2_parent, v1_no_ns, no_limit)] if quota else ["no cgroup_cpus"])
            check("284/285: a cgroup's room is the smallest up the tree (a parent's 3 GB less 1 used), found in a v1 "
                  "container without a namespace of its own (the mount's root) and under a pod's limit; its CPU "
                  "quota rounded up (1.5 -> 2, 0.5 -> 1), none where cpu.max says max",
                  got == [2 * G, G, G // 2, None, 2, 1, None], str(got))
            own_cpus = pt.cpus()
            os.environ["READ_PAGE_TEST_CGROUP"] = v1_no_ns
            under_quota = pt.cpus()
            os.environ["READ_PAGE_TEST_CGROUP"] = cg_many
            under_many = pt.cpus()
            check("284: ... and the CPUs the read counts are within the quota, never more than its affinity",
                  under_quota == 1 and under_many == own_cpus, "%s %s %s" % (under_quota, under_many, own_cpus))
            # the read's processes under them: a quota of one CPU (half a CPU's), and 600 MB of room in a cgroup
            # where the machine has more; the memory is the OS's own here (no READ_PAGE_TEST_MEMORY)
            cpu_only = fake_cgroup("cpu1", "0::/c\n", {fs + "c/cpu.max": "50000 100000"})
            mem_only = fake_cgroup("mem600", "0::/c\n", {fs + "c/memory.max": str(700 << 20),
                                                         fs + "c/memory.current": str(100 << 20)})
            got = []
            for cg, cpus_env, mem_env in ((cpu_only, None, json.dumps({"phys": 64 << 30, "commit": 64 << 30})),
                                          (mem_only, "4", None)):
                for k, v in (("READ_PAGE_TEST_CGROUP", cg), ("READ_PAGE_TEST_CPUS", cpus_env),
                             ("READ_PAGE_TEST_MEMORY", mem_env)):
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                os.environ.update(RP_STUB_SLEEP="1.5", READ_PAGE_TEST_PACE="1")
                mod3.tables_reset()
                info = mod3.pdf_tables(six_p, d6p, list(texts6))
                mod3.tables_close(kill=True)
                got.append((info.get("procs"), info.get("asked"), bool(info.get("left"))))
            for k in ("READ_PAGE_TEST_CGROUP", "READ_PAGE_TEST_PACE"):
                os.environ.pop(k, None)
            check("284/285: ... so a read in a cgroup of one CPU runs one process, and one in a cgroup of 600 MB "
                  "room one (80 % of it holds no 512 MB more), every page laid out", got == [(1, 6, False)] * 2, str(got))

            # KNOWN-ISSUES 286: a process's own answer is waited for without a loop - another's, which came first,
            # waits aside and goes back to the queue after. Put back at once, it came out again at once, 100 times a
            # second, and the wait never ended: the queue was never empty, so its time was never looked at
            # (--alternate waits so). The wait runs in a thread here, as on 3b501bf it does not end
            mod3.tables_reset()
            r_w1, r_w2 = mod3.tables_start(), mod3.tables_start()
            r_q = mod3._TABLES["q"]
            r_ready = [r_w1.get(time.time() + 60), r_w2.get(time.time() + 60)]
            r_puts, real_put, r_out = [0], r_q.put, {}

            def counting_put(*a, **kw):
                r_puts[0] += 1
                return real_put(*a, **kw)

            def r_wait():
                t_wait = time.time()
                r_out["mine"] = r_w1.get(time.time() + 1.0)
                r_out["waited"] = time.time() - t_wait
            r_q.put = counting_put
            try:
                r_q.put({"page": 5, "_w": r_w2})
                r_puts[0] = 0
                r_th = threading.Thread(target=r_wait, daemon=True)
                r_th.start()
                r_th.join(5)
                r_hung = r_th.is_alive()
                r_n = r_puts[0]
                if r_hung:                     # (it lets go of another's answer once that one is no process of the read's)
                    mod3._TABLES["pool"].remove(r_w2)
                    r_th.join(5)
                r_left = r_q.get_nowait() if not r_q.empty() else None
            finally:
                del r_q.put
                mod3.tables_close(kill=True)
            check("286: a wait for one process's answer ends at its time and puts another's back once",
                  all(r and r.get("ready") is not None for r in r_ready) and not r_hung and r_out.get("mine") is None
                  and 0.9 < r_out.get("waited", 0) < 3 and r_n <= 2 and (r_left or {}).get("page") == 5,
                  "hung %s, %s %s, %d puts, left %s" % (r_hung, r_ready, r_out, r_n, r_left))
            # KNOWN-ISSUES 287: processes that end while their model loads are started again once, as a page a
            # process ends at is given to another once: a model that cannot load stops the step after two, where
            # before a death that left another running started a new one until the time was up
            os.environ.update(RP_STUB_LOAD_EXIT=os.path.join(tmp, "load-exit-once"), READ_PAGE_TEST_CPUS="4",
                              READ_PAGE_TEST_MEMORY=json.dumps({"phys": 64 << 30, "commit": 64 << 30}))
            r_starts, real_start = [0], mod3.tables_start

            def counting_start(*a, **kw):
                r_starts[0] += 1
                return real_start(*a, **kw)
            mod3.tables_start = counting_start
            try:
                mod3.tables_reset()
                info = mod3.pdf_tables(six_p, d6p, list(texts6))
            finally:
                mod3.tables_start = real_start
                mod3.tables_close(kill=True)
                for k in ("RP_STUB_LOAD_EXIT", "READ_PAGE_TEST_CPUS", "READ_PAGE_TEST_MEMORY"):
                    os.environ.pop(k, None)
            check("287: processes that end while the model loads are started again once, then the step stops with "
                  "every page named", r_starts[0] <= 3 and info.get("asked") == 0
                  and info.get("left") == [1, 2, 3, 4, 5, 6] and "ended" in (info.get("error") or "")
                  and info.get("secs", 99) < 6, "%d starts %s" % (r_starts[0], info))
            for k in ("RP_STUB_SLEEP", "READ_PAGE_TEST_MEMORY", "READ_PAGE_TEST_CPUS"):
                os.environ.pop(k, None)
            os.environ["RP_STUB_NOLOAD"] = "1"
            mod3.tables_reset()
            info = mod3.pdf_tables(many, d3, [p.get_text() for p in d3])
            mod3.tables_merge(info)
            check("a PDF's tables: a model that does not load is said in signals.tables.error, not met in silence",
                  "RP-STUB: no model here" in (mod3.tables_signal().get("error") or "") and not info.get("pages")
                  and mod3.tables_signal().get("left") == "1-3", str(mod3.tables_signal()))
            os.environ.pop("RP_STUB_NOLOAD", None)
            mod3.tables_close(kill=True)
            # KNOWN-ISSUES 237: the model's time is the time it works. Four reads at once on a Celeron's budget gave
            # its process a fifth of a CPU: its load alone outlasted the fixed 10 s, and no page was laid out. A
            # model that waits - for the CPU; here its load or its pages sleep - gets the time it waits, within what
            # the read has left; one at work the whole time (a busy loop) keeps its own seconds. Its own seconds
            # here come from the stand-in's load on this machine, which is work - Python and onnxruntime imported -
            # done before its sleep: 2 s fixed lost to a CI macOS x64 runner whose load took them all (asked 0 of 3,
            # once in two runs, 2026-11-26); twice the load and a second more, 2 s at least (its pace comes every half
            # second, and a word or two must come before those seconds are up)
            clock, keep_secs = dict(mod3.budget._state), mod3.PDF_TABLES_SECONDS
            six = os.path.join(tmp, "tables6.pdf")
            table_pdf(six, pages=6)
            d6 = pymupdf.open(six)
            try:
                os.environ["READ_PAGE_TEST_CPUS"] = "1"        # one process: its own seconds, as a CPU of its own
                w0 = mod3.TablesWorker()
                ready = w0.get(time.time() + 60) or {}
                w0.kill()
                base = max(2.0, 2 * float(ready.get("busy") or 0) + 1.0)
                mod3.budget.start(max(30.0, 4 * base + 10))
                mod3.PDF_TABLES_SECONDS = base
                for name, var, val in (("its load", "RP_STUB_LOAD_SLEEP", base + 1.5),
                                       ("its pages", "RP_STUB_SLEEP", base / 2)):
                    os.environ[var] = str(val)
                    mod3.tables_reset()
                    info = mod3.pdf_tables(many, d3, [p.get_text() for p in d3])
                    os.environ.pop(var, None)
                    mod3.tables_close(kill=True)
                    check("237: a model that waits past its seconds (%s) lays every page out, within the read's time"
                          % name, info.get("asked") == 3 and not info.get("left") and info.get("secs", 99) < 3 * base + 10,
                          "%s (its own %.1f s)" % (info, base))
                os.environ["RP_STUB_BUSY"] = str(base / 2.5)          # six pages: 2.4 times its own seconds of work
                mod3.tables_reset()
                info = mod3.pdf_tables(six, d6, [p.get_text() for p in d6])
                check("... but a model at work all the time keeps its own seconds: the pages it did not reach are named",
                      info.get("asked", 9) < 6 and len(info.get("left") or []) >= 2 and info.get("secs", 99) < base + 3,
                      "%s (its own %.1f s)" % (info, base))
            finally:
                os.environ.pop("RP_STUB_BUSY", None)
                os.environ.pop("READ_PAGE_TEST_CPUS", None)
                mod3.PDF_TABLES_SECONDS = keep_secs
                mod3.budget._state.update(clock)
        finally:
            for k in ("RP_STUB_NOLOAD", "RP_STUB_FAIL", "RP_STUB_CRASH", "READ_PAGE_TEST_MODEL_PATH",
                      "RP_STUB_LOAD_SLEEP", "RP_STUB_SLEEP", "RP_STUB_BUSY", "RP_STUB_HANG", "READ_PAGE_TEST_CPUS",
                      "READ_PAGE_TEST_PACE", "READ_PAGE_TEST_MEMORY", "RP_STUB_NOMEM", "RP_STUB_PAGE_SLEEP",
                      "RP_STUB_TABLE", "READ_PAGE_TEST_CGROUP", "RP_STUB_LOAD_EXIT"):
                os.environ.pop(k, None)
            mod3.tables_close(kill=True)
        zp = os.path.join(tmp, "three.zip")
        with zipfile.ZipFile(zp, "w") as z:
            for k in range(3):
                z.write(many, "report-%d.pdf" % k)
        try:
            import pymupdf4llm                               # noqa: F401,F811
            # the model's own time: the pages it did not reach are named, and stay plain
            mod3.PDF_TABLES_SECONDS = 0
            mod3.tables_reset()
            pages3 = [p.get_text() for p in d3]
            info = mod3.pdf_tables(many, d3, pages3)
            check("a PDF's tables: with no time for the model the text stays plain and the pages are named",
                  info.get("left") == [1, 2, 3] and not info.get("pages")
                  and not row_whole("\n".join(pages3), T_ROWS[0]), str(info))
            mod3.PDF_TABLES_SECONDS = 60
            mod3.tables_reset()
            info = mod3.pdf_tables(many, d3, pages3)
            check("a PDF's tables: with time, every page that has one",
                  info.get("pages") == [1, 2, 3] and not info.get("left") and info.get("asked") == 3
                  and all(row_whole(pg3, T_ROWS[2]) for pg3 in pages3), str(info))
            mod3.PDF_TABLES_SECONDS = 0
            mod3.tables_reset()
            clock = dict(mod3.budget._state)
            mod3.budget.start(None)                          # --download: no deadline, so no cap of its own
            pages3 = [p.get_text() for p in pymupdf.open(many)]
            info = mod3.pdf_tables(many, pymupdf.open(many), pages3)
            mod3.budget._state.update(clock)
            check("a PDF's tables: a read with no deadline (--download) lays out every page",
                  info.get("pages") == [1, 2, 3] and not info.get("left"), str(info))
            # a caller's PYTHONPATH does not reach the model's process: a folder of another Python's
            # build there cost every PDF its tables (2026-11-21)
            fake = tempfile.mkdtemp(prefix="rp-fake-")
            with open(os.path.join(fake, "pymupdf4llm.py"), "w", encoding="utf-8") as fh:
                fh.write("raise ImportError('RP-FAKE: a build for another Python')\n")
            keep_path = os.environ.get("PYTHONPATH")
            os.environ["PYTHONPATH"] = fake
            try:
                mod3.PDF_TABLES_SECONDS = 60
                mod3.tables_reset()
                pages3 = [p.get_text() for p in d3]
                info = mod3.pdf_tables(many, d3, pages3)
            finally:
                mod3.tables_close(kill=True)
                if keep_path is None:
                    os.environ.pop("PYTHONPATH", None)
                else:
                    os.environ["PYTHONPATH"] = keep_path
            check("a PDF's tables: a caller's PYTHONPATH does not reach the model's process",
                  info.get("pages") == [1, 2, 3] and "RP-FAKE" not in (info.get("error") or ""), str(info))
            # one tables clock a read: the PDFs of an archive share it - 30 pages of tables in 0.6 s
            # is past any machine, so the last PDF gets none of it, and every page is laid out or named
            ten = os.path.join(tmp, "tables10.pdf")
            table_pdf(ten, pages=10)
            zp10 = os.path.join(tmp, "thirty.zip")
            with zipfile.ZipFile(zp10, "w") as z:
                for k in range(3):
                    z.write(ten, "report-%d.pdf" % k)
            mod3.PDF_TABLES_SECONDS = 0.6
            mod3.tables_reset()
            t0 = time.time()
            mod3.doc_text(zp10, "zip", {"libs": {"pymupdf": True, "pymupdf4llm": True}, "cli": {}},
                          tempfile.mkdtemp(prefix="rp-zip3-"))
            took, said = time.time() - t0, dict(mod3._PDF)    # the read's own lists, not the ranges
            files = said.get("files") or []
            check("a PDF's tables: one clock a read - three PDFs of an archive share its seconds, and the "
                  "pages not reached are named by file",
                  said.get("secs", 99) <= 1.5 and len(files) == 3 and files[-1].get("left") == list(range(1, 11))
                  and all(sorted((f.get("pages") or []) + (f.get("left") or [])) == list(range(1, 11)) for f in files)
                  and "report-2.pdf" in mod3.tables_advice(said)
                  and (mod3.tables_signal().get("files") or [{}])[-1].get("left") == "1-10", "%.1f s %s" % (took, said))
            mod3.PDF_TABLES_SECONDS = 10
            mod3.tables_close(kill=True)
        except ImportError:
            check.skip("a PDF's tables, the model's time", "pymupdf4llm is not installed in the suite's Python")
        if model_here:
            # a page the model would take long over is not asked in a read's time, and is named
            hv = os.path.join(tmp, "heavy.pdf")
            doc = pymupdf.open()
            strokes_page(doc, strokes=8100)
            strokes_page(doc, numbers=2100)
            doc.save(hv)
            doc.close()
            r = run_read(hv, env=env)
            tab = (r.manifest.get("signals") or {}).get("tables") or {}
            check("a PDF's tables: pages too heavy for a read's time (8 100 vector paths; 2 100 words in a "
                  "block) are not asked, and are named",
                  tab.get("heavy") == "1-2" and tab.get("left") == "1-2" and not tab.get("asked")
                  and "too heavy" in (r.manifest.get("advice") or "") and r.seconds < 20,
                  "%.1f s %s %s" % (r.seconds, tab, r.manifest.get("advice")))
            # under those counts the model can still take long (2 010 strokes: 11 s, 8 010: 24 s on a laptop):
            # its process is killed when the time is up, and the read keeps its deadline. The real model is no
            # measure of that: on a CI runner it laid these 7 000 strokes out in 2 s, so the page was not slow
            # and the check failed there. The slowness is the stand-in's (RP_STUB_SLEEP), the same everywhere
            sl = os.path.join(tmp, "slow.pdf")
            doc = pymupdf.open()
            strokes_page(doc, strokes=7000)
            doc.save(sl)
            doc.close()
            r = run_read(sl, env=dict(env, READ_PAGE_TEST_DEADLINE="4", READ_PAGE_TEST_MODEL_PATH=stubdir,
                                      RP_STUB_SLEEP="30"))
            tab = (r.manifest.get("signals") or {}).get("tables") or {}
            check("a PDF's tables: a slow page does not hold the read past its deadline (4 s here)",
                  r.manifest.get("status") == "ok" and tab.get("left") == "1" and r.seconds < 7
                  and "Row 8" in r.file("content.md"), "%.1f s %s %s" % (r.seconds, r.manifest.get("status"), tab))
            r = run_read(many, env=dict(env, READ_PAGE_TEST_DEADLINE="4", READ_PAGE_TEST_MODEL_PATH=stubdir,
                                        RP_STUB_SLEEP="30", READ_PAGE_TEST_CPUS="4"))
            tab = (r.manifest.get("signals") or {}).get("tables") or {}
            check("242: ... nor three processes, each at a slow page: the deadline holds, every page named",
                  r.manifest.get("status") == "ok" and tab.get("left") == "1-3" and r.seconds < 7,
                  "%.1f s %s %s" % (r.seconds, r.manifest.get("status"), tab))
            # --alternate lays out what fits the read's time, and names the rest
            lp = os.path.join(tmp, "long.pdf")
            table_pdf(lp, pages=200)                         # 0.1-0.5 s a page: far more than 6 s
            r = run_read(lp, "--alternate", env=dict(env, READ_PAGE_TEST_DEADLINE="6"))
            tab = (r.manifest.get("signals") or {}).get("tables") or {}
            text = r.file("content.md")
            check("--alternate on a long PDF stays inside the read's deadline, the pages not laid out named",
                  r.manifest.get("status") == "ok" and r.seconds < 10 and tab.get("markdown")
                  and str(tab.get("left") or "").endswith("-200") and "--download" in (r.manifest.get("advice") or "")
                  and "TABLE-OUTRO 200" in text and "TABLE-INTRO 1" in text,
                  "%.1f s %s %s" % (r.seconds, tab, r.manifest.get("advice")))
            # the PDFs of an archive: their tables are laid out and reported
            r = run_read(zp, env=env)
            tab = (r.manifest.get("signals") or {}).get("tables") or {}
            check("a ZIP of PDFs: their tables are laid out, and the manifest says so by file",
                  [f.get("name") for f in tab.get("files") or []] == ["report-0.pdf", "report-1.pdf", "report-2.pdf"]
                  and row_whole(r.file("content.md"), T_ROWS[0]), str(tab))
        else:
            check.skip("a PDF's tables against a read's deadline", "no pymupdf4llm where the read runs")
        # --alternate whose Markdown call outlasts the time (four reads at once on two slow cores lost
        # all 75 pages to one call, and the answer spoke of tables): what it laid out and what is
        # plain text is said. Without the model it says so too: pymupdf4llm 1.28 needs onnxruntime
        r = run_read(many, "--alternate", env=dict(env, READ_PAGE_TEST_DEADLINE="5", RP_STUB_MD_SLEEP="30",
                                                   READ_PAGE_TEST_MODEL_PATH=stubdir))
        tab = (r.manifest.get("signals") or {}).get("tables") or {}
        adv = r.manifest.get("advice") or ""
        if model_here:
            check("--alternate cut by its time: the manifest says Markdown was asked and which pages are plain "
                  "text, and the advice says why",
                  r.manifest.get("status") == "ok" and r.seconds < 9 and tab.get("markdown") and tab.get("left") == "1-3"
                  and "pages 1-3 are PyMuPDF's plain text, not Markdown (the time for the layout ran out)" in adv
                  and "610.01" in r.file("content.md"), "%.1f s %s %r" % (r.seconds, tab, adv))
        else:
            check("--alternate without the layout model: plain text, and the read says so",
                  r.manifest.get("status") == "ok" and tab.get("markdown") and "not installed" in (tab.get("error") or "")
                  and "PyMuPDF's plain text, not Markdown" in adv, "%s %r" % (tab, adv))
        # the model's process ends with the read, however the read ends: killed alone mid-page (a
        # harness that kills by PID; the MCP server's hard kill), it had lived its page out, 18-24 s
        try:
            import psutil
        except ImportError:
            psutil = None
        here = importlib.util.find_spec("pymupdf4llm") and importlib.util.find_spec("onnxruntime")
        if psutil is None or not here:
            check.skip("the model's process ends with a read killed mid-page", "no psutil or no model in the suite's Python")
        else:
            e = dict(os.environ, READ_PAGE_SKIP="browser,env", READ_PAGE_TEST_MODEL_PATH=stubdir, RP_STUB_SLEEP="30",
                     READ_PAGE_CACHE=tempfile.mkdtemp(prefix="rp-kill-"))
            for k in ("FIRECRAWL_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY"):
                e.pop(k, None)
            rd = subprocess.Popen([sys.executable, "-X", "utf8", SCRIPT, many, "--json"], env=e,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            child, t_end = None, time.time() + 20
            while child is None and time.time() < t_end and rd.poll() is None:
                try:
                    child = next((ch for ch in psutil.Process(rd.pid).children(recursive=True)
                                  if "pdftables.py" in " ".join(ch.cmdline())), None)
                except psutil.Error:
                    pass
                time.sleep(0.2)
            gone_in = None
            if child is not None:
                time.sleep(1.0)                              # at its page now, for 30 s
                rd.kill()                                    # the read alone: TerminateProcess, SIGKILL
                rd.wait(10)
                t_kill = time.time()
                try:
                    child.wait(5)
                    gone_in = time.time() - t_kill
                except psutil.TimeoutExpired:
                    child.kill()
                except psutil.Error:
                    gone_in = time.time() - t_kill
            else:
                rd.kill()
                rd.wait(10)
            check("the model's process ends within a second or two of a read killed mid-page",
                  child is not None and gone_in is not None and gone_in < 2.5,
                  "child %s, gone in %s s" % (child and child.pid, gone_in and round(gone_in, 2)))
    except ImportError:
        check.skip("a PDF's tables", "pymupdf is not installed here")

    # ------------------------------------------------ the model's process and a read it cannot watch (Windows)
    # A sandbox that refuses SYNCHRONIZE on the read's process made OpenProcess give no handle, and
    # the process ended at once: every PDF lost its tables with no word said. PID 4, the System
    # process, refuses it the same way (error 5); a process that is gone is error 87
    if os.name != "nt":
        check.skip("the model's process stays when it cannot watch its read", "Windows: POSIX watches the parent's PID")
    else:
        watcher = os.path.join(tmp, "watcher.py")
        with open(watcher, "w", encoding="utf-8") as fh:
            fh.write("import sys, threading, time\n"
                     "sys.path.insert(0, sys.argv[1])\n"
                     "import pdftables\n"
                     "threading.Thread(target=pdftables.watch_parent, args=(int(sys.argv[2]),), daemon=True).start()\n"
                     "time.sleep(float(sys.argv[3]))\n"
                     "print('ALIVE', flush=True)\n")

        def watching(pid, wait):
            return subprocess.Popen([sys.executable, "-I", "-B", "-X", "utf8", watcher, os.path.dirname(SCRIPT), str(pid),
                                     str(wait)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        t0 = time.time()
        out, _ = watching(4, 2.5).communicate(timeout=60)
        check("the model's process stays when the OS refuses it a handle on the read (PID 4)",
              b"ALIVE" in out, "%r after %.1f s" % (out, time.time() - t0))
        gone = subprocess.Popen([sys.executable, "-I", "-c", "pass"])
        gone.wait(30)
        t0 = time.time()
        out, _ = watching(gone.pid, 6).communicate(timeout=60)
        check("the model's process ends when the read's process does not exist", b"ALIVE" not in out and time.time() - t0 < 5,
              "%r after %.1f s" % (out, time.time() - t0))
        read = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(120)"])
        try:
            child = watching(read.pid, 8)
            time.sleep(1.5)
            read.kill()
            t0 = time.time()
            out, _ = child.communicate(timeout=60)
            check("the model's process ends when the read it watches ends", b"ALIVE" not in out and time.time() - t0 < 4,
                  "%r, %.1f s after the kill" % (out, time.time() - t0))
        finally:
            read.kill()

    # ------------------------------------------------ markitdown for a YouTube transcript
    mod2 = module()
    calls = []

    def fake_tool(cmd, timeout=120):
        calls.append(cmd)
        return 0, b"# YouTube\n\n## A talk\n\n### Transcript\nhello from the transcript\n", b""
    mod2.run_tool = fake_tool
    md, why = mod2.markitdown_video("https://www.youtube.com/watch?v=abcdefghijk", {"cli": {"markitdown": "md"}})
    check("markitdown's transcript is taken when yt-dlp has none",
          "hello from the transcript" in md and not why and calls, why)
    md, why = mod2.markitdown_video("https://vimeo.com/12345", {"cli": {"markitdown": "md"}})
    check("only for YouTube", not md and not why, why)
    mod2.run_tool = lambda cmd, timeout=120: (0, b"# YouTube\n\n## A talk\n\n### Description\nno words\n", b"")
    md, why = mod2.markitdown_video("https://youtu.be/abcdefghijk", {"cli": {"markitdown": "md"}})
    check("a title and description without a transcript is not taken", not md and "no transcript" in why, why)

    # ------------------------------------------------ without markitdown: the caption
    # track through youtube-transcript-api, the library markitdown used, in yt-dlp's form
    import types

    class Snip:
        def __init__(self, start, duration, text):
            self.start, self.duration, self.text = start, duration, text

    class FakeApi:
        def fetch(self, vid, languages=()):
            if vid != "abcdefghijk":
                raise ValueError("no transcript")
            return [Snip(1.0, 1.5, "hello from the caption track"), Snip(2.5, 1.0, "second cue"),
                    Snip(65.0, 2.0, "a minute later")]

        def list(self, vid):
            raise ValueError("no transcripts at all")
    sys.modules["youtube_transcript_api"] = types.SimpleNamespace(YouTubeTranscriptApi=FakeApi)
    try:
        tmp14 = tempfile.mkdtemp(prefix="rp-r14-")
        text, why = mod2.transcript_video("https://www.youtube.com/watch?v=abcdefghijk&t=10", tmp14)
        check("the caption track comes in yt-dlp's form, timestamps and all, transcript.vtt beside it",
              "[0:01] hello from the caption track second cue" in text and "[1:05] a minute later" in text
              and os.path.isfile(os.path.join(tmp14, "transcript.vtt")) and not why, repr(text[:90]) + why)
        text, why = mod2.transcript_video("https://youtu.be/zzzzzzzzzzz", tmp14)
        check("a video with no caption track says why", not text and "no transcripts" in why, why)
        check("a YouTube id is found in every address form",
              [mod2.youtube_id(u) for u in ("https://youtu.be/abcdefghijk", "https://www.youtube.com/shorts/abcdefghijk",
                                            "https://m.youtube.com/watch?feature=x&v=abcdefghijk",
                                            "https://www.youtube.com/embed/abcdefghijk", "https://vimeo.com/123")]
              == ["abcdefghijk"] * 4 + [""], "")
    finally:
        sys.modules.pop("youtube_transcript_api", None)

    # ------------------------------------------------ pandoc's Markdown, cleaned (no markitdown)
    raw = ("<div>\r\n\r\nMemory and desire, stirring\r\n\r\n</div>\r\n\r\n"
           "Text with `<span>code</span>` inline and a <span class=\"x\">span</span>.\r\n\r\n"
           "````\r\n```java\r\n<div>kept in code</div>\r\n```\r\n````\r\n\r\n"
           "<pre class=\"highlight\"><code>$ git log &amp;&amp; echo &lt;ok&gt;\r\n```not a fence```</code></pre>\r\n\r\n"
           "<figure><img src=\"images/a.png\" alt=\"The `iss53` branch\" /><figcaption>Figure 1</figcaption></figure>\r\n\r\n"
           "<table><tr><th rowspan=\"2\">Region</th><th>Q1</th></tr><tr><td>EMEA <b>42</b></td></tr></table>\r\n\r\n"
           "See <a href=\"https://example.com/x\" class=\"ulink\">the guide</a>.\r\n\r\n"
           "<script>var navLists = document.getElementsByTagName('nav');</script>\r\nAfter.\r\n")
    md = mod2.clean_pandoc(raw)
    check("pandoc: layout wrappers go, their text stays", "<div>" not in md.split("````")[0]
          and "Memory and desire, stirring" in md and "a span." in md, repr(md[:80]))
    check("pandoc: code stays as it is - fenced, a four-backtick fence holding three, inline",
          "<div>kept in code</div>" in md and "```java" in md and "`<span>code</span>`" in md, "")
    check("pandoc: a raw <pre><code> becomes a fenced block, its entities read",
          "$ git log && echo <ok>" in md and "```not a fence```" in md, "")
    check("pandoc: a picture becomes Markdown (so a marker), its alt kept whole",
          "![The `iss53` branch](images/a.png)" in md and "<img" not in md, "")
    check("pandoc: a table pandoc kept as HTML is one row a line", "Region | Q1" in md and "EMEA 42" in md, "")
    check("pandoc: a link becomes [text](address); a script goes with its code",
          "[the guide](https://example.com/x)" in md and "navLists" not in md and "After." in md and "\r" not in md, "")

    # ------------------------------------------------ office files: what python-docx and python-pptx hid
    try:
        import docx
        from docx.oxml import parse_xml
        tmpo = tempfile.mkdtemp(prefix="rp-office-")
        W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        d = docx.Document()
        d.add_paragraph("FIRST paragraph.")
        d.element.body.insert(1, parse_xml(
            '<w:sdt %s><w:sdtContent><w:p><w:r><w:t>CONTROL-FACT invoice 4417-B.</w:t></w:r></w:p>'
            '</w:sdtContent></w:sdt>' % W))
        d.element.body.insert(2, parse_xml(
            '<w:p %s xmlns:v="urn:schemas-microsoft-com:vml"><w:r><w:pict><v:shape><v:textbox><w:txbxContent>'
            '<w:p><w:r><w:t>BOXED-FACT 27 months.</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict>'
            '</w:r></w:p>' % W))
        t = d.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text, t.rows[0].cells[1].text = "CELL-A", "CELL-B"
        d.add_paragraph("LAST paragraph.")
        dp = os.path.join(tmpo, "edge.docx")
        d.save(dp)
        got = mod2.office_fast(dp, "docx")
        order = [got.find(x) for x in ("FIRST", "CONTROL-FACT", "BOXED-FACT", "CELL-A | CELL-B", "LAST")]
        check("docx: a content control's text, a text box's and a table's, each where it stands",
              all(i >= 0 for i in order) and order == sorted(order), str(order))
    except ImportError:
        check.skip("docx: content controls and text boxes", "python-docx is not installed here")

    # ------------------------------------------------ KNOWN-ISSUES 165: a DOCX's formulas (OMML), as Word writes them
    MATH = ('xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"')
    CTRL = '<m:ctrlPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/><w:i/></w:rPr></m:ctrlPr>'

    def mr(t):
        return ('<m:r><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/></w:rPr><m:t>%s</m:t></m:r>'
                % t)

    def e(*xs):
        return "<m:e>%s</m:e>" % "".join(xs)
    WORD_FORMULAS = [            # (OMML as Word writes it, the line it is read as)
        (mr("E=m") + '<m:sSup><m:sSupPr>%s</m:sSupPr>%s<m:sup>%s</m:sup></m:sSup>' % (CTRL, e(mr("c")), mr("2")),
         "E=mc^2"),
        ('<m:f><m:fPr>%s</m:fPr><m:num>%s</m:num><m:den>%s</m:den></m:f>' % (CTRL, mr("a+b"), mr("2")), "(a+b)/2"),
        ('<m:f><m:fPr><m:type m:val="lin"/>%s</m:fPr><m:num>%s</m:num><m:den>%s</m:den></m:f>' % (CTRL, mr("a"), mr("b")),
         "a/b"),
        ('<m:rad><m:radPr>%s</m:radPr><m:deg/>%s</m:rad>' % (CTRL, e(mr("x+1"))), "√(x+1)"),
        ('<m:rad><m:radPr>%s</m:radPr><m:deg>%s</m:deg>%s</m:rad>' % (CTRL, mr("3"), e(mr("x"))), "root(3, x)"),
        ('<m:nary><m:naryPr><m:chr m:val="∑"/><m:limLoc m:val="undOvr"/>%s</m:naryPr><m:sub>%s</m:sub><m:sup>%s</m:sup>%s'
         '</m:nary>' % (CTRL, mr("i=1"), mr("n"), e('<m:sSub><m:sSubPr>%s</m:sSubPr>%s<m:sub>%s</m:sub></m:sSub>'
                                                   % (CTRL, e(mr("x")), mr("i")))), "∑_(i=1)^n x_i"),
        ('<m:nary><m:naryPr><m:limLoc m:val="subSup"/>%s</m:naryPr><m:sub>%s</m:sub><m:sup>%s</m:sup>%s</m:nary>'
         % (CTRL, mr("0"), mr("1"), e(mr("f(x)dx"))), "∫_0^1 f(x)dx"),                   # no m:chr: an integral
        ('<m:func><m:funcPr>%s</m:funcPr><m:fName>%s</m:fName>%s</m:func>' % (CTRL, mr("sin"), e(mr("x"))), "sin x"),
        ('<m:func><m:funcPr>%s</m:funcPr><m:fName><m:limLow><m:limLowPr>%s</m:limLowPr>%s<m:lim>%s</m:lim></m:limLow>'
         '</m:fName>%s</m:func>' % (CTRL, CTRL, e(mr("lim")), mr("n→∞"), e(mr("a_n"))), "lim_(n→∞) a_n"),
        ('<m:d><m:dPr><m:begChr m:val="["/><m:endChr m:val="]"/>%s</m:dPr>%s</m:d>' % (CTRL, e(
            '<m:m><m:mPr>%s</m:mPr><m:mr>%s%s</m:mr><m:mr>%s%s</m:mr></m:m>' % (CTRL, e(mr("1")), e(mr("2")), e(mr("3")),
                                                                            e(mr("4"))))), "[1, 2; 3, 4]"),
        ('<m:d><m:dPr>%s</m:dPr>%s%s</m:d>' % (CTRL, e(mr("a")), e(mr("b"))), "(a|b)"),     # Word's defaults
        ('<m:acc><m:accPr>%s</m:accPr>%s</m:acc>' % (CTRL, e(mr("x"))), "x̂"),
        ('<m:groupChr><m:groupChrPr>%s</m:groupChrPr>%s</m:groupChr>' % (CTRL, e(mr("a+b"))), "underbrace(a+b)"),
        ('<m:sPre><m:sPrePr>%s</m:sPrePr><m:sub>%s</m:sub><m:sup>%s</m:sup>%s</m:sPre>' % (CTRL, mr("1"), mr("2"),
                                                                                         e(mr("X"))), "_1^2 X"),
        ('<m:eqArr><m:eqArrPr>%s</m:eqArrPr>%s%s</m:eqArr>' % (CTRL, e(mr("x=1")), e(mr("y=2"))), "x=1; y=2"),
        (mr("a") + '<m:phant><m:phantPr><m:show m:val="0"/>%s</m:phantPr>%s</m:phant>' % (CTRL, e(mr("HIDDEN")))
         + mr("b"), "ab"),
    ]
    try:
        import docx
        from docx.oxml import parse_xml
        tmpm = tempfile.mkdtemp(prefix="rp-math-")
        d = docx.Document()
        for k, (omml, _want) in enumerate(WORD_FORMULAS):
            d.add_paragraph("FORMULA-%02d: " % k)
            d.paragraphs[-1]._p.append(parse_xml('<m:oMath %s>%s</m:oMath>' % (MATH, omml)))
            d.paragraphs[-1].add_run(" ends here.")
        d.add_paragraph()._p.append(parse_xml('<m:oMathPara %s><m:oMath>%s</m:oMath></m:oMathPara>'
                                              % (MATH, mr("DISPLAY=") + WORD_FORMULAS[1][0])))
        t = d.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text = "IN-A-CELL"
        t.rows[0].cells[1].paragraphs[0]._p.append(parse_xml('<m:oMath %s>%s</m:oMath>' % (MATH, WORD_FORMULAS[0][0])))
        mp = os.path.join(tmpm, "math.docx")
        d.save(mp)
        got = mod2.office_fast(mp, "docx")
        lost = [(k, want) for k, (_o, want) in enumerate(WORD_FORMULAS)
                if "FORMULA-%02d: `%s` ends here." % (k, want) not in got]
        check("165: a DOCX's formulas are read where they stand, as a line each (Word's own OMML: %d of them)"
              % len(WORD_FORMULAS), not lost, "%s %r" % (lost[:3], got[:200]))
        check("165: a formula of its own paragraph is a paragraph; a formula in a table cell is in its cell",
              "\n\n`DISPLAY=(a+b)/2`\n\n" in got and "IN-A-CELL | `E=mc^2`" in got, repr(got[-200:]))
        only = docx.Document()
        for k in (5, 9):
            only.add_paragraph()._p.append(parse_xml('<m:oMathPara %s><m:oMath>%s</m:oMath></m:oMathPara>'
                                                     % (MATH, WORD_FORMULAS[k][0])))
        op = os.path.join(tmpm, "only-math.docx")
        only.save(op)
        r = run_read(op, env=env)
        check("165: a DOCX of formulas alone reads as them (it read as nothing: python-docx skips OMML)",
              r.manifest.get("status") == "ok" and "`∑_(i=1)^n x_i`" in r.file("content.md")
              and "`[1, 2; 3, 4]`" in r.file("content.md"), "%s %r" % (r.manifest.get("status"),
                                                                       r.file("content.md")[:80]))
        wrapped = docx.Document()
        frac = '<m:oMath %s>%s</m:oMath>' % (MATH, WORD_FORMULAS[2][0])           # a/b
        for label, xml in (("IN-A-LINK", '<w:hyperlink w:anchor="x" %s><w:r><w:t>LINK-TEXT </w:t></w:r>%s</w:hyperlink>'),
                           ("IN-AN-INSERTION", '<w:ins w:id="1" w:author="a" %s><w:r><w:t>INSERTED-TEXT </w:t></w:r>%s</w:ins>'),
                           ("IN-A-SMART-TAG", '<w:smartTag w:uri="u" w:element="e" %s><w:r><w:t>TAGGED-TEXT </w:t></w:r>%s'
                                              '</w:smartTag>'),
                           ("IN-A-FIELD", '<w:fldSimple w:instr="PAGE" %s><w:r><w:t>FIELD-TEXT </w:t></w:r>%s</w:fldSimple>')):
            para = wrapped.add_paragraph(label + ": ")
            para._p.append(parse_xml(xml % (MATH, frac)))
            para.add_run(" after.")
        wrapped.add_paragraph("NO-FORMULA: ")._p.append(parse_xml(
            '<w:ins w:id="2" w:author="a" %s><w:r><w:t>ONLY-INSERTED</w:t></w:r></w:ins>' % MATH))
        wp = os.path.join(tmpm, "wrapped.docx")
        wrapped.save(wp)
        got = mod2.office_fast(wp, "docx")
        lost = [x for x in ("IN-A-LINK: LINK-TEXT `a/b` after.", "IN-AN-INSERTION: INSERTED-TEXT `a/b` after.",
                            "IN-A-SMART-TAG: TAGGED-TEXT `a/b` after.", "IN-A-FIELD: FIELD-TEXT `a/b` after.",
                            "NO-FORMULA: ONLY-INSERTED") if x not in got]
        check("165: a formula in a hyperlink, an insertion, a smart tag or a field is read, and their text (both lost)",
              not lost, "%s %r" % (lost, got[:300]))
        one = docx.Document()
        one.add_paragraph()._p.append(parse_xml('<m:oMathPara %s><m:oMath>%s</m:oMath></m:oMathPara>'
                                                % (MATH, WORD_FORMULAS[0][0])))
        onep = os.path.join(tmpm, "one-formula.docx")
        one.save(onep)
        r = run_read(onep, env=env)
        check("165: a DOCX that is one formula is `ok`: a document's few words are the document (it was `empty`, "
              "its text shown)", r.manifest.get("status") == "ok" and "`E=mc^2`" in r.file("content.md"),
              "%s %r" % (r.manifest.get("status"), r.file("content.md")[:80]))
    except ImportError:
        check.skip("165: a DOCX's formulas", "python-docx is not installed here")
    try:
        from pptx import Presentation
        from pptx.util import Inches
        pr = Presentation()
        sl = pr.slides.add_slide(pr.slide_layouts[6])
        grp = sl.shapes.add_group_shape()
        grp.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text_frame.text = "GROUPED-FACT"
        tb = sl.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(4), Inches(1)).table
        tb.cell(0, 0).text, tb.cell(1, 1).text = "TABLE-HEAD", "TABLE-42"
        pp = os.path.join(tmpo if "tmpo" in dir() else tempfile.mkdtemp(), "edge.pptx")
        pr.save(pp)
        got = mod2.office_fast(pp, "pptx")
        check("pptx: a group's text and a table's cells", "GROUPED-FACT" in got and "TABLE-HEAD" in got
              and "TABLE-42" in got, repr(got[:120]))
    except ImportError:
        check.skip("pptx: groups and tables", "python-pptx is not installed here")

    # ------------------------------------------------ a plain archive: its files and their text
    tmpz = tempfile.mkdtemp(prefix="rp-zip-")
    zp = os.path.join(tmpz, "bundle.zip")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("notes/readme.txt", "ZIP-README-FACT this bundle holds a note and a page.\n")
        z.writestr("page.html", "<html><body><h1>Inner</h1><p>ZIP-HTML-FACT a page inside.</p></body></html>")
        z.writestr("../../escape.txt", "ZIP-ESCAPE-FACT a member named outside the folder.\n")
        z.writestr("tool.exe", b"MZ\x00\x00")
    got = mod2.zip_text(zp, mod2.caps(), tmpz)
    check("zip: the files are listed, and the text of what can be read is there",
          "Files in the archive (4)" in got and "ZIP-README-FACT" in got and "ZIP-HTML-FACT" in got
          and "tool.exe" in got, repr(got[:100]))
    check("zip: a member is never written where its name points",
          not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(tmpz)), "escape.txt"))
          and not any(n.endswith("escape.txt") for n in os.listdir(tmpz)), str(os.listdir(tmpz)))

    # ------------------------------------------------ an EPUB's pictures: one the archive lacks, a hostile container
    def png(w, h, color):
        raw = b"".join(b"\x00" + bytes(color) * w for _ in range(h))

        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def picture_epub(name, container=None, missing=True):
        """A one-chapter EPUB with the pictures one.png and two.png, and gone.png in its text only."""
        path_ = os.path.join(tmp, name)
        with zipfile.ZipFile(path_, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container or
                        '<?xml version="1.0"?><container version="1.0" '
                        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                        '</rootfiles></container>')
            zf.writestr("OEBPS/content.opf",
                        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                        'unique-identifier="i"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                        '<dc:identifier id="i">x</dc:identifier><dc:title>Pictures</dc:title>'
                        '<dc:language>en</dc:language></metadata><manifest>'
                        '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
                        '<spine><itemref idref="c1"/></spine></package>')
            zf.writestr("OEBPS/c1.xhtml",
                        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title></head><body><h1>Chapter</h1>'
                        + "<p>%s</p>" % (EN * 3) + '<p><img src="images/one.png" alt="one"/></p><p>Between.</p>'
                        '<p><img src="images/two.png" alt="two"/></p>'
                        + ('<p><img src="images/gone.png" alt="gone"/></p>' if missing else "") + '</body></html>')
            zf.writestr("OEBPS/images/one.png", png(30, 20, (255, 0, 0)))
            zf.writestr("OEBPS/images/two.png", png(40, 30, (0, 255, 0)))
        return path_
    # our EPUB reader names the pictures where they stand, on every machine (pandoc's text did, where
    # pandoc was installed)
    r = run_read(picture_epub("m4.epub"), "--refresh", env=env)
    imgs = r.manifest.get("images") or []
    check("an EPUB with one picture missing from its archive keeps the others, listed first",
          [(e.get("n"), bool(e.get("file"))) for e in imgs] == [(1, True), (2, True), (3, False)],
          "%s %s" % (r.manifest.get("status"), [(e.get("n"), e.get("file"), e.get("why")) for e in imgs]))
    shown = r.file("content.md")
    folder = os.path.join(r.dir, "img")
    check("--refresh leaves their files, and every marker of the text has its own number",
          sorted(os.listdir(folder)) == ["01-one.png", "02-two.png"] if os.path.isdir(folder) else False,
          "%s %s" % (sorted(os.listdir(folder)) if os.path.isdir(folder) else None,
                     re.findall(r"\[img #\d+", shown)))
    check("no two markers share a number", sorted(set(re.findall(r"\[img #(\d+)", shown))) == ["1", "2", "3"]
          and len(re.findall(r"\[img #\d+", shown)) == 3, str(re.findall(r"\[img #\d+", shown)))
    # a container whose <rootfile tags never close (a few hundred bytes zipped) held the read for a
    # minute and a half; the pictures are still found, in the archive's own order
    control = run_read(picture_epub("h5-control.epub", "<container><rootfiles>" + "<rootfile " * 10, missing=False),
                       "--refresh", env=env)
    hostile = run_read(picture_epub("h5.epub", "<container><rootfiles>" + "<rootfile " * 16000, missing=False),
                       "--refresh", env=env)
    check("16 000 unclosed <rootfile tags cost no more than 10 (11-19 s more when quadratic)",
          hostile.seconds < control.seconds + 4 and len(hostile.manifest.get("images") or []) == 2
          and len(control.manifest.get("images") or []) == 2,
          "%.1f s against %.1f s, %d pictures" % (hostile.seconds, control.seconds,
                                                   len(hostile.manifest.get("images") or [])))

    # ------------------------------------------------ KNOWN-ISSUES 167: an archive cut, damaged or no ZIP
    # was answered "no converter for this file type", after a machine's markitdown had its 4 s
    def noise_png(w, h):
        raw = b"".join(b"\x00" + os.urandom(w * 3) for _ in range(h))

        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def said(r):
        m = r.manifest
        return "%s | %s | %s | %s" % (m.get("status"), (m.get("signals") or {}).get("status_reason"),
                                       m.get("advice"), json.dumps(m.get("missing") or [])[:120])

    def no_converter(r):
        return "no converter" in json.dumps(r.manifest)

    tmpc = tempfile.mkdtemp(prefix="rp-cut-")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k in range(3):
            z.writestr("notes/part%d.txt" % k, ("PART-%d-FACT " % k) + EN * 30)
    whole = buf.getvalue()
    third = zipfile.ZipFile(io.BytesIO(whole)).infolist()[2].header_offset
    cutzip = os.path.join(tmpc, "bundle.zip")
    with open(cutzip, "wb") as fh:
        fh.write(whole[:third + 60])                  # in the middle of the third member
    r = run_read(cutzip, env=env)
    text, sig = r.file("content.md"), (r.manifest.get("signals") or {}).get("broken_archive") or {}
    check("167: a cut ZIP is read from its whole members, and the answer says it is cut",
          r.manifest.get("status") == "ok" and "PART-0-FACT" in text and "PART-1-FACT" in text
          and "PART-2-FACT" not in text and sig.get("how") == "cut" and sig.get("whole") == 2
          and "cut" in (r.manifest.get("advice") or "") and not no_converter(r), said(r))
    check("... its listing names the member that is not whole, and the advice what gets the rest (a whole copy)",
          "part2.txt (not read: cut)" in text and "whole copy" in (r.manifest.get("advice") or ""), said(r))
    left_over = [n for n in os.listdir(r.dir) if n.startswith(("_whole-", "_mended-"))]
    check("... and the archive made of its whole members is gone once read (it stayed for the cache's day)",
          not left_over, str(left_over))
    with open(os.path.join(os.path.dirname(HERE), "references", "manifest-schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)["properties"]["signals"]["properties"].get("broken_archive") or {}
    check("... and references/manifest-schema.json has every field of signals.broken_archive",
          sig and set(sig) <= set(schema.get("properties") or {}), "%s %s" % (sorted(sig), sorted(schema.get(
              "properties") or {})))
    with open(cutzip, "wb") as fh:
        fh.write(whole[:50])                          # inside the first member's data
    r = run_read(cutzip, env=env)
    check("167: a ZIP cut before any member is whole: an error that says so, not \"no converter\"",
          r.manifest.get("status") == "error" and "not a whole archive" in str(
              (r.manifest.get("signals") or {}).get("status_reason")) and "no member of it is whole" in (
              r.manifest.get("advice") or "") and not no_converter(r), said(r))
    toc = zipfile.ZipFile(io.BytesIO(whole)).start_dir
    with open(cutzip, "wb") as fh:
        fh.write(whole[:(toc + whole.rfind(b"PK\x05\x06")) // 2])       # halfway through its table of contents
    r = run_read(cutzip, env=env)
    sig = (r.manifest.get("signals") or {}).get("broken_archive") or {}
    check("167: a ZIP cut in its table of contents: every member is whole, and the advice wants nothing more (it "
          "said \"damaged\", and that a whole copy was needed for the rest)",
          r.manifest.get("status") == "ok" and "PART-2-FACT" in r.file("content.md") and sig.get("how") == "cut"
          and sig.get("all_members") is True and "all 3 of its members are whole" in (r.manifest.get("advice") or "")
          and "the rest" not in (r.manifest.get("advice") or ""), said(r))
    def cut_in_transit(h):
        # the whole archive's length is sent, and two thirds of its bytes, then the connection closes
        h.send_response(200)
        h.send_header("Content-Type", "application/zip")
        h.send_header("Content-Length", str(len(whole)))
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(whole[:third + 60])
        h.wfile.flush()
        h.close_connection = True
    s.routes["/transit.zip"] = cut_in_transit
    r = run_read(s.url("/transit.zip"), env=env)
    sig = (r.manifest.get("signals") or {}).get("broken_archive") or {}
    check("167: a ZIP cut in transit is read from the members that arrived whole (it was `error`, nothing read), and "
          "the advice says the transfer was cut, not the server's copy",
          r.manifest.get("status") == "ok" and "PART-1-FACT" in r.file("content.md") and sig.get("how") == "cut"
          and (r.manifest.get("signals") or {}).get("partial") and "did not arrive" in (r.manifest.get("advice") or "")
          and "server's copy" not in (r.manifest.get("advice") or ""), said(r))
    s.routes["/cut.zip"] = (200, {"Content-Type": "application/zip"}, whole[:third + 60])
    r = run_read(s.url("/cut.zip"), env=env)
    check("167: a server's cut ZIP sent whole: --refresh fetches it again, the same bytes while its copy is cut",
          r.manifest.get("status") == "ok" and "PART-1-FACT" in r.file("content.md")
          and "--refresh" in (r.manifest.get("advice") or "") and "server's copy is cut" in (
              r.manifest.get("advice") or ""), said(r))
    try:
        import docx
        d = docx.Document()
        d.add_paragraph("DOCX-FIRST-FACT " + EN * 5)
        d.add_picture(io.BytesIO(noise_png(160, 160)))
        d.add_paragraph("DOCX-LAST-FACT " + EN * 5)
        dbuf = io.BytesIO()
        d.save(dbuf)
        data = dbuf.getvalue()
        media = [i for i in zipfile.ZipFile(io.BytesIO(data)).infolist() if "media/" in i.filename][0]
        cutdocx = os.path.join(tmpc, "report.docx")
        with open(cutdocx, "wb") as fh:
            fh.write(data[:media.header_offset + 2000])       # in its picture, everything after it gone
        r = run_read(cutdocx, env=env)
        text, sig = r.file("content.md"), (r.manifest.get("signals") or {}).get("broken_archive") or {}
        check("167: a DOCX cut in its picture: its text is read, the archive named cut",
              r.manifest.get("status") == "ok" and "DOCX-FIRST-FACT" in text and "DOCX-LAST-FACT" in text
              and sig.get("how") == "cut" and not no_converter(r), said(r))
        bad = bytearray(data)
        k = media.header_offset + 30 + len(media.filename) + 500
        bad[k:k + 64] = bytes(b ^ 0x5A for b in bad[k:k + 64])           # its picture's data broken
        damaged = os.path.join(tmpc, "damaged.docx")
        with open(damaged, "wb") as fh:
            fh.write(bytes(bad))
        r = run_read(damaged, env=env)
        text, sig = r.file("content.md"), (r.manifest.get("signals") or {}).get("broken_archive") or {}
        check("167: a DOCX whose picture does not unpack: its text is read, the member named (python-docx gave up)",
              r.manifest.get("status") == "ok" and "DOCX-LAST-FACT" in text and sig.get("how") == "damaged"
              and any("media/" in x for x in sig.get("not_whole") or []) and not no_converter(r), said(r))
        # a wrong offset of the table of contents in its end record: zipfile opens the file, and no member
        # unpacks where the table says it starts (python-docx: "negative seek value"); its members' own headers
        # are right
        eocd = data.rfind(b"PK\x05\x06")
        wrong = bytearray(data)
        wrong[eocd + 16:eocd + 20] = struct.pack("<I", struct.unpack("<I", data[eocd + 16:eocd + 20])[0] + 3)
        offset = os.path.join(tmpc, "offset.docx")
        with open(offset, "wb") as fh:
            fh.write(bytes(wrong))
        r = run_read(offset, env=env)
        text, sig = r.file("content.md"), (r.manifest.get("signals") or {}).get("broken_archive") or {}
        check("167: a DOCX whose table of contents is out of place is read from its members' own headers (it was "
              "\"no converter\")", r.manifest.get("status") == "ok" and "DOCX-LAST-FACT" in text
              and sig.get("whole") == sig.get("members") and sig.get("all_members") is True
              and "not its members" in (r.manifest.get("advice") or "") and not no_converter(r), said(r))
    except ImportError:
        check.skip("167: a cut DOCX", "python-docx is not installed here")

    def cut_in(data, member, into=200):
        """The package's bytes up to `into` bytes into the data of `member`."""
        info = zipfile.ZipFile(io.BytesIO(data)).getinfo(member)
        return data[:info.header_offset + 30 + len(info.filename) + into]

    def reordered(data, first=(), last=()):
        """The package again: [Content_Types].xml first (as Excel and PowerPoint write it), then the members
        whose names start with one of `first`, the others in their order, those that start with one of `last`."""
        zin = zipfile.ZipFile(io.BytesIO(data))

        def rank(i):
            n = i.filename
            return 0 if n == "[Content_Types].xml" else 1 if n.startswith(first) else 3 if n.startswith(last) else 2
        infos = sorted(zin.infolist(), key=rank)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for i in infos:
                z.writestr(i.filename, zin.read(i))
        return out.getvalue()
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        for k, title in enumerate(("First", "Second", "Third")):
            ws = wb.active if k == 0 else wb.create_sheet(title)
            ws.title = title
            for row in range(20):
                ws.append(["SHEET-%d-FACT row %d" % (k + 1, row), "the quarterly figures", row * 7])
        xbuf = io.BytesIO()
        wb.save(xbuf)
        xdata = xbuf.getvalue()
        for label, made in (("as openpyxl writes it (its sheets first, the workbook and its content types last)",
                             cut_in(xdata, "xl/worksheets/sheet3.xml")),
                            ("as Excel orders it (the workbook and its content types first)",
                             cut_in(reordered(xdata, last=("xl/worksheets/sheet3.xml",)), "xl/worksheets/sheet3.xml"))):
            p = os.path.join(tmpc, "cut.xlsx")
            with open(p, "wb") as fh:
                fh.write(made)
            r = run_read(p, env=env)
            text = r.file("content.md")
            check("167: an XLSX cut in its third sheet keeps the first two, %s (it read nothing)" % label,
                  r.manifest.get("status") == "ok" and "SHEET-1-FACT row 19" in text and "SHEET-2-FACT row 19" in text
                  and "SHEET-3-FACT" not in text and "cut" in (r.manifest.get("advice") or ""), said(r))
    except ImportError:
        check.skip("167: a cut XLSX", "openpyxl is not installed here")
    try:
        from pptx import Presentation
        deck = Presentation()
        for k in range(3):
            sl = deck.slides.add_slide(deck.slide_layouts[1])
            sl.shapes.title.text = "SLIDE-%d-TITLE" % (k + 1)
            sl.placeholders[1].text = "SLIDE-%d-FACT %s" % (k + 1, EN * 3)
        pbuf = io.BytesIO()
        deck.save(pbuf)
        p = os.path.join(tmpc, "cut.pptx")
        with open(p, "wb") as fh:
            fh.write(cut_in(pbuf.getvalue(), "ppt/slides/slide3.xml"))
        r = run_read(p, env=env)
        text = r.file("content.md")
        check("167: a PPTX cut in its third slide keeps the first two (its slide list named the lost one: nothing read)",
              r.manifest.get("status") == "ok" and "SLIDE-1-FACT" in text and "SLIDE-2-FACT" in text
              and "SLIDE-3" not in text and "cut" in (r.manifest.get("advice") or ""), said(r))
        # its pictures whole and its slides lost: the answer's words are the skill's list of the pictures
        from pptx.util import Inches
        pics = Presentation()
        for k in range(3):
            sl = pics.slides.add_slide(pics.slide_layouts[6])
            sl.shapes.add_picture(io.BytesIO(noise_png(60 + k, 60)), Inches(1), Inches(1))
        pbuf = io.BytesIO()
        pics.save(pbuf)
        p = os.path.join(tmpc, "pictures.pptx")
        with open(p, "wb") as fh:
            fh.write(cut_in(reordered(pbuf.getvalue(), ("ppt/media/",), ("ppt/slides/",)), "ppt/slides/slide1.xml", 40))
        r = run_read(p, env=env)
        check("167: a PPTX whose slides are lost and its pictures whole is an error, not `ok` on the list of its "
              "pictures (60 words of markers)", r.manifest.get("status") == "error"
              and len(r.manifest.get("images") or []) == 3 and "no text could be read" in (r.manifest.get("advice") or ""),
              said(r))
    except ImportError:
        check.skip("167: a cut PPTX", "python-pptx is not installed here")
    # a workbook as Excel writes one - its text in xl/sharedStrings.xml, after its sheets - cut in transit or on
    # disk: the shared strings that did not arrive leave its cells' numbers (they read nothing: openpyxl stops at
    # the first string it does not have), and what arrived of the part it was cut in is read up to the cut
    def excel_xlsx(sheets, sst_first=False, dimension=False, last=()):
        """sheets: [(name, [(label, number)])], each label a shared string; the members in Excel's order (the
        shared strings after the sheets), or with the shared strings first, and an external link last (a
        government workbook had five; openpyxl stopped at one whose part the cut took). openpyxl writes no
        shared strings. `dimension`: each sheet's extent at its top, as Excel writes it; `last`: members put
        after the shared strings (a government workbook had its fifth sheet there)."""
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        ooxml = "application/vnd.openxmlformats-officedocument.spreadsheetml."
        strings, at, parts = [], {}, []
        for k, (_name, rows) in enumerate(sheets, 1):
            xml = []
            for r, (label, number) in enumerate(rows, 1):
                at.setdefault(label, len(strings))
                if at[label] == len(strings):
                    strings.append(label)
                xml.append('<row r="%d"><c r="A%d" t="s"><v>%d</v></c><c r="B%d"><v>%s</v></c></row>'
                           % (r, r, at[label], r, number))
            parts.append(("xl/worksheets/sheet%d.xml" % k, '<?xml version="1.0" encoding="UTF-8"?><worksheet '
                          'xmlns="%s">%s<sheetData>%s</sheetData></worksheet>' % (
                              main, '<dimension ref="A1:B%d"/>' % len(rows) if dimension else "", "".join(xml))))
        sst = ('<?xml version="1.0" encoding="UTF-8"?><sst xmlns="%s" count="%d" uniqueCount="%d">%s</sst>'
               % (main, len(strings), len(strings), "".join("<si><t>%s</t></si>" % s for s in strings)))
        n = len(sheets)
        index = [
            ("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.'
             'org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-'
             'package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName='
             '"/xl/workbook.xml" ContentType="%ssheet.main+xml"/>%s<Override PartName="/xl/sharedStrings.xml" '
             'ContentType="%ssharedStrings+xml"/><Override PartName="/xl/externalLinks/externalLink1.xml" '
             'ContentType="%sexternalLink+xml"/></Types>' % (ooxml, "".join(
                 '<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="%sworksheet+xml"/>' % (k, ooxml)
                 for k in range(1, n + 1)), ooxml, ooxml)),
            ("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.'
             'org/package/2006/relationships"><Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/>'
             '</Relationships>' % rel),
            ("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%s" xmlns:r="%s"><sheets>%s'
             '</sheets><externalReferences><externalReference r:id="rId%d"/></externalReferences></workbook>'
             % (main, rel, "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (name, k, k)
                                   for k, (name, _rows) in enumerate(sheets, 1)), n + 2)),
            ("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
             'openxmlformats.org/package/2006/relationships">%s<Relationship Id="rId%d" Type="%s/sharedStrings" '
             'Target="sharedStrings.xml"/><Relationship Id="rId%d" Type="%s/externalLink" Target="externalLinks/'
             'externalLink1.xml"/></Relationships>' % ("".join(
                 '<Relationship Id="rId%d" Type="%s/worksheet" Target="worksheets/sheet%d.xml"/>' % (k, rel, k)
                 for k in range(1, n + 1)), n + 1, rel, n + 2, rel))]
        link = [("xl/externalLinks/externalLink1.xml", '<?xml version="1.0" encoding="UTF-8"?><externalLink xmlns="%s" '
                 'xmlns:r="%s"><externalBook r:id="rId1"><sheetNames><sheetName val="Totals"/></sheetNames>'
                 '</externalBook></externalLink>' % (main, rel)),
                ("xl/externalLinks/_rels/externalLink1.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships '
                 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/'
                 'externalLinkPath" Target="file:///C:/totals.xlsx" TargetMode="External"/></Relationships>' % rel)]
        order = index + ([("xl/sharedStrings.xml", sst)] + parts if sst_first else
                         [p for p in parts if p[0] not in last] + [("xl/sharedStrings.xml", sst)]
                         + [p for p in parts if p[0] in last]) + link
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for member, text in order:
                z.writestr(member, text)
        return buf.getvalue()

    def into(data, member, share):
        """The file's bytes up to `share` of the way into `member`'s packed data."""
        info = zipfile.ZipFile(io.BytesIO(data)).getinfo(member)
        start = info.header_offset + 30 + len(info.filename)
        return data[:start + int(info.compress_size * share)]

    try:
        import openpyxl  # noqa: F401
        rows = lambda tag, n, add: [("%s-LABEL %d" % (tag, r), r * 7 + add) for r in range(n)]   # noqa: E731
        book = excel_xlsx([("First", rows("FIRST", 40, 1)), ("Second", rows("SECOND", 40, 2)),
                           ("Third", rows("THIRD", 400, 3))])
        p = os.path.join(tmpc, "strings-lost.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(book, "xl/worksheets/sheet3.xml", 0.5))
        r = run_read(p, env=env)
        text, sig = r.file("content.md"), (r.manifest.get("signals") or {}).get("broken_archive") or {}
        check("254: an XLSX cut in a sheet, its shared strings after the sheets (Excel's order): the numbers of the "
              "sheets that arrived and of the cut one's first rows, each lost text [lost] (it read nothing)",
              r.manifest.get("status") == "ok" and "[lost] | 274\n" in text and "[lost] | 275\n" in text
              and "[lost] | 3\n" in text and "LABEL" not in text and sig.get("lost_strings", 0) >= 80
              and sig.get("partial") == "xl/worksheets/sheet3.xml" and "[lost]" in (r.manifest.get("advice") or ""),
              said(r))
        p = os.path.join(tmpc, "strings-cut.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(book, "xl/sharedStrings.xml", 0.5))
        r = run_read(p, env=env)
        text = r.file("content.md")
        check("254: an XLSX cut in its shared strings keeps the strings that arrived, the rest [lost]",
              "FIRST-LABEL 0 | 1" in text and "SECOND-LABEL 39 | 275" in text and "THIRD-LABEL 399" not in text
              and "[lost] | 2796" in text, said(r))
        early = excel_xlsx([("First", rows("FIRST", 40, 1)), ("Second", rows("SECOND", 400, 2))], sst_first=True)
        p = os.path.join(tmpc, "sheet-cut.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(early, "xl/worksheets/sheet2.xml", 0.5))
        r = run_read(p, env=env)
        text = r.file("content.md")
        check("254: an XLSX cut in a sheet after its shared strings reads that sheet's rows up to the cut, their text "
              "with them", "FIRST-LABEL 39 | 274" in text and "SECOND-LABEL 0 | 2" in text and "[lost]" not in text
              and "SECOND-LABEL 399" not in text and r.manifest.get("status") == "ok", said(r))
        p = os.path.join(tmpc, "link-cut.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(book, "xl/externalLinks/_rels/externalLink1.xml.rels", 0.5))
        r = run_read(p, env=env)
        text = r.file("content.md")
        check("254: an XLSX cut in its last part, an external link's relationships: every sheet read with its text "
              "(openpyxl stopped at the link, and the whole workbook read nothing)", r.manifest.get("status") == "ok"
              and "THIRD-LABEL 399 | 2796" in text and "FIRST-LABEL 0 | 1" in text and "[lost]" not in text, said(r))
        # a sheet that names a shared string far past any table (ten digits): the lost strings made for a cut
        # workbook were as many as its highest index asked - 10 000 000 000 of them, a 220 GB allocation
        z_in = zipfile.ZipFile(io.BytesIO(excel_xlsx([("First", rows("FIRST", 40, 1))])))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z_out:
            for info in z_in.infolist():
                data = z_in.read(info.filename)
                if info.filename == "xl/worksheets/sheet1.xml":
                    data = data.replace(b'<v>0</v></c><c r="B1">', b'<v>9999999999</v></c><c r="B1">')
                z_out.writestr(info.filename, data)
        p = os.path.join(tmpc, "strings-far.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(buf.getvalue(), "xl/sharedStrings.xml", 0.5))
        r = run_read(p, env=env)
        sig = (r.manifest.get("signals") or {}).get("broken_archive") or {}
        reason = str((r.manifest.get("signals") or {}).get("status_reason") or "")
        check("254: a cut XLSX whose sheet names a shared string ten digits past its table is salvaged, no stand-ins "
              "made past a bound (it asked for 220 GB, and the MemoryError read as 'damaged, before its first member')",
              r.rc == 0 and sig.get("partial") == "xl/sharedStrings.xml" and "before its first member" not in reason
              and r.seconds < 60, "rc %s, %.1f s, %s | %s" % (r.rc, r.seconds, json.dumps(sig)[:160], said(r)))
        # what the cut took, said where it took it: the rows a cut sheet lost after its last row that arrived, the
        # total from its extent (<dimension ref="A1:B400"/>, at its top); a sheet taken whole where it would stand,
        # its name from workbook.xml (KNOWN-ISSUES 267)
        four = [("First", rows("FIRST", 40, 1)), ("Second", rows("SECOND", 40, 2)), ("Third", rows("THIRD", 400, 3)),
                ("Fourth", rows("FOURTH", 40, 4))]
        p = os.path.join(tmpc, "rows-lost.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(excel_xlsx(four, dimension=True), "xl/worksheets/sheet3.xml", 0.5))
        r = run_read(p, env=env)
        lines = r.file("content.md").split("\n")
        at = next((i for i, ln in enumerate(lines) if ln.startswith("[rows · ")), None)
        upto = int(re.match(r"\[lost\] \| (\d+)$", lines[at - 1]).group(1)) // 7 + 1 if at and re.match(
            r"\[lost\] \| \d+$", lines[at - 1]) else None
        check("267: a sheet cut short says which rows it lost, after the last that arrived, the total from its "
              "extent: [rows · lost in the cut · N-400 · Third]",
              at is not None and upto and lines[at] == "[rows · lost in the cut · %d-400 · Third]" % (upto + 1)
              and "## Third" in lines[:at] and r.manifest.get("status") == "ok", lines[at - 1:at + 2] if at else said(r))
        check("267: a sheet the cut took whole stands where it would: [sheet · lost in the cut · Fourth], no heading",
              at is not None and lines[at + 1:at + 2] == ["[sheet · lost in the cut · Fourth]"]
              and "## Fourth" not in lines, lines[at:at + 3] if at else said(r))
        many = [("First", rows("FIRST", 3, 1))] + [("Lost sheet number %d of the workbook" % k, rows("L%d" % k, 3, k))
                                                    for k in range(2, 10)]
        p = os.path.join(tmpc, "few-words.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(excel_xlsx(many), "xl/worksheets/sheet2.xml", 0.0))
        r = run_read(p, env=env)
        check("267: the markers are the skill's words, not the document's: eight lost sheets' markers do not make "
              "three rows of numbers a document of 40 words", r.manifest.get("status") == "error"
              and r.file("content.md").count("[sheet · lost in the cut · Lost sheet number") == 8, said(r))
        p = os.path.join(tmpc, "rows-lost-no-extent.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(excel_xlsx(four), "xl/worksheets/sheet3.xml", 0.5))
        text = run_read(p, env=env).file("content.md")
        check("267: with no extent in the sheet, the rows lost are N-?",
              re.search(r"^\[rows · lost in the cut · \d+-\? · Third\]$", text, re.M) is not None
              and "[sheet · lost in the cut · Fourth]" in text, said(r))
        p = os.path.join(tmpc, "sheet-lost-between.xlsx")
        with open(p, "wb") as fh:
            fh.write(into(excel_xlsx(four, dimension=True, last=("xl/worksheets/sheet2.xml",)),
                          "xl/worksheets/sheet2.xml", 0.0))
        r = run_read(p, env=env)
        heads = [ln for ln in r.file("content.md").split("\n") if ln.startswith(("## ", "[sheet · ", "[rows · "))]
        check("267: a sheet written after the shared strings and lost stands between its neighbours (a government "
              "workbook keeps its fifth sheet there)",
              heads == ["## First", "[sheet · lost in the cut · Second]", "## Third", "## Fourth"], str(heads))
    except ImportError:
        check.skip("254: a cut XLSX's shared strings", "openpyxl is not installed here")

    # openpyxl's read-only sheet takes its size from <dimension ref> and pads every row to it, a missing row too: a
    # sheet that says A1:XFD1048576 made each of a million rows 16 384 cells, minutes in the read's own process with
    # no clock; one that says less than it holds was read up to that size (KNOWN-ISSUES 330)
    def raw_xlsx(dim, rows):
        """A workbook of one sheet, its rows [(row number, [(column letters, text)])] as inline strings, under
        <dimension ref=dim> (none for "")."""
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        sheet_xml = "".join('<row r="%d">%s</row>' % (r, "".join(
            '<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' % (col, r, t) for col, t in cells)) for r, cells in rows)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                       'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxml'
                       'formats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                       '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                       'spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType='
                       '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
            z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                       'package/2006/relationships"><Relationship Id="rId1" Type="%s/officeDocument" Target="xl/'
                       'workbook.xml"/></Relationships>' % rel)
            z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="%s" xmlns:r="%s"><sheets><sheet '
                       'name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>' % (main, rel))
            z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                       'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/worksheet" '
                       'Target="worksheets/sheet1.xml"/></Relationships>' % rel)
            z.writestr("xl/worksheets/sheet1.xml", '<?xml version="1.0"?><worksheet xmlns="%s">%s<sheetData>%s'
                       '</sheetData></worksheet>' % (main, '<dimension ref="%s"/>' % dim if dim else "", sheet_xml))
        return buf.getvalue()

    try:
        import openpyxl  # noqa: F401
        p = os.path.join(tmpc, "far.xlsx")
        with open(p, "wb") as fh:
            fh.write(raw_xlsx("A1:XFD1048576", [(1, [("A", "FAR-FIRST-CELL"), ("B", "beside it")]),
                                                (1048576, [("XFD", "FAR-LAST-CELL")])]))
        name = ("330: an XLSX whose sheet says A1:XFD1048576, two rows a million apart, reads in seconds and says its "
                "columns past 1024 are not read (it padded every row to 16 384 cells: minutes)")
        try:
            r = run_read(p, env=env, timeout=90)
            note = str((r.manifest.get("signals") or {}).get("document_note") or "")
            check(name, r.manifest.get("status") == "ok" and r.seconds < 30 and "FAR-FIRST-CELL | beside it" in
                  r.file("content.md") and "past 1024 are not read" in note and "XFD" in note,
                  "%.1f s, %s | %s" % (r.seconds, note[:160], said(r)))
        except subprocess.TimeoutExpired:
            check(name, False, "still reading at 90 s")
        p = os.path.join(tmpc, "small-dimension.xlsx")
        with open(p, "wb") as fh:
            fh.write(raw_xlsx("A1", [(r, [(c, "R%dC%d" % (r, k)) for k, c in enumerate("ABCDE")]) for r in range(1, 6)]))
        r = run_read(p, env=env)
        text = r.file("content.md")
        check("330: a sheet that says it is A1 (some writers put that) reads every row and column it holds (openpyxl "
              "read the one cell its size said)", "R1C0 | R1C1 | R1C2 | R1C3 | R1C4" in text
              and "R5C0 | R5C1 | R5C2 | R5C3 | R5C4" in text, said(r))
        p = os.path.join(tmpc, "long.xlsx")
        with open(p, "wb") as fh:
            fh.write(raw_xlsx("A1:A300000", [(r, [("A", "LONG-ROW-%d" % r)]) for r in range(1, 300001)]))
        r = run_read(p, env=dict(env, READ_PAGE_TEST_DEADLINE="2"))
        text, note = r.file("content.md"), str((r.manifest.get("signals") or {}).get("document_note") or "")
        check("330: a workbook its time does not hold is read up to a row and says where the time ran out (no clock "
              "looked at it)", r.manifest.get("status") == "ok" and "LONG-ROW-1\n" in text + "\n"
              and "LONG-ROW-300000" not in text and "the time ran out in sheet Data at its row" in note,
              "%.1f s, %s | %s" % (r.seconds, note[:160], said(r)))
    except ImportError:
        check.skip("330: an XLSX's stated size", "openpyxl is not installed here")

    # a PDF cut short ends without its %%EOF: one that does not open was `empty`, "no text in it"; one that opens with
    # no page was a scan with no page to render; one whose first pages open was `ok` with the rest unsaid (KNOWN-ISSUES
    # 335)
    try:
        import pymupdf
        made = pymupdf.open()
        for n in range(8):
            made.new_page().insert_textbox((72, 72, 520, 760), "PDF-PAGE-%d-FACT %s" % (n + 1, EN * 12), fontsize=10)
        plain_pdf, streams_pdf = made.tobytes(garbage=3, deflate=True), made.tobytes(garbage=3, deflate=True, use_objstms=1)
        made.close()
        for label, data in (("that does not open (its first 200 bytes)", plain_pdf[:200]),
                            ("whose objects are in streams, cut at half (it opens with no page)",
                             streams_pdf[:len(streams_pdf) // 2])):
            p = os.path.join(tmpc, "cut-%d.pdf" % len(data))
            with open(p, "wb") as fh:
                fh.write(data)
            r = run_read(p, env=env)
            sig = (r.manifest.get("signals") or {}).get("broken_pdf") or {}
            check("335: a PDF %s is an error that says it is cut and asks for a whole copy (it was `empty`, \"no text in "
                  "it\", or a scan)" % label, r.manifest.get("status") == "error" and sig.get("how") == "cut"
                  and sig.get("pages") == 0 and "a whole copy of the file is needed" in (r.manifest.get("advice") or "")
                  and "text layer" not in json.dumps(r.manifest.get("missing") or []), said(r))
        p = os.path.join(tmpc, "cut-half.pdf")
        with open(p, "wb") as fh:
            fh.write(plain_pdf[:len(plain_pdf) // 2])
        r = run_read(p, env=env)
        sig = (r.manifest.get("signals") or {}).get("broken_pdf") or {}
        check("335: a PDF cut at half whose pages open keeps what they hold, `ok`, and says it is cut (it said nothing)",
              r.manifest.get("status") == "ok" and "PDF-PAGE-1-FACT" in r.file("content.md") and sig.get("how") == "cut"
              and sig.get("pages") == 8 and "the file is needed for the rest" in (r.manifest.get("advice") or ""), said(r))
        p = os.path.join(tmpc, "whole.pdf")
        with open(p, "wb") as fh:
            fh.write(plain_pdf)
        r = run_read(p, env=env)
        check("335: a whole PDF says nothing of a cut", r.manifest.get("status") == "ok" and "PDF-PAGE-8-FACT" in
              r.file("content.md") and not (r.manifest.get("signals") or {}).get("broken_pdf"), said(r))
    except ImportError:
        check.skip("335: a cut PDF", "pymupdf is not installed here")

    # MuPDF writes its errors to file descriptor 1: a damaged PDF's "MuPDF error: ..." stood before the answer's first
    # line, and `--json` did not parse; the MCP server's stdout is its protocol, and an SVG with a broken picture made
    # lines there that are no JSON-RPC (KNOWN-ISSUES 336)
    try:
        import pymupdf  # noqa: F401
        p = os.path.join(tmpc, "complains.pdf")
        with open(p, "wb") as fh:
            fh.write(plain_pdf[:len(plain_pdf) // 2])
        first = run_read(p, env=env).text.split("\n", 1)[0]
        try:
            parsed = json.loads(run_read(p, "--json", env=env).text)
        except ValueError:
            parsed = None
        check("336: a PDF MuPDF complains of: the answer's first line is its header, and --json parses (MuPDF's error "
              "stood before them)", first.startswith("read-page · ") and isinstance(parsed, dict), repr(first[:90]))
        svg = os.path.join(tmpc, "broken-picture.svg")
        with open(svg, "wb") as fh:
            fh.write(b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><image width="40" height="40" '
                     b'href="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ"/></svg>')
        code = ("import sys; sys.path.insert(0, %r); import mcp_server; got = mcp_server.inline_image(%r); "
                "sys.stderr.write(str(got[1:])[:80])" % (os.path.dirname(SCRIPT), svg))
        child = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, timeout=120)
        check("336: the MCP server makes an SVG with a broken picture a PNG and writes nothing on its stdout, its "
              "protocol (MuPDF's errors were lines there)", child.returncode == 0 and child.stdout == b"",
              repr(child.stdout[:120]) + " | " + child.stderr.decode("utf-8", "replace")[-160:])
    except ImportError:
        check.skip("336: MuPDF's messages", "pymupdf is not installed here")

    # a scan's page was rendered at 150 dpi whatever its size: a page of 200 x 200 in, which PDF allows, was 900 million
    # pixels in the read's own process (KNOWN-ISSUES 337); here a page of 60 x 60 in, 81 million at 150 dpi
    try:
        import pymupdf
        big = pymupdf.open()
        big.new_page(width=4320, height=4320).draw_rect(pymupdf.Rect(100, 100, 4220, 4220), color=(0, 0, 0))
        p = os.path.join(tmpc, "big-scan.pdf")
        big.save(p)
        big.close()
        r = run_read(p, env=env)
        shots = [os.path.join(r.dir, x) for x in (r.manifest.get("files") or {}).get("pages") or []]
        dims = []
        for s_ in shots:
            with open(s_ if os.path.isabs(s_) else os.path.join(r.dir, s_), "rb") as fh:
                head = fh.read(24)
            dims.append(struct.unpack(">II", head[16:24]) if head[:8] == b"\x89PNG\r\n\x1a\n" else (0, 0))
        check("337: a scan's page of 60 x 60 in is rendered within 25 million pixels (at 150 dpi it was 81 million)",
              dims and all(0 < w_ * h_ <= 25000000 for w_, h_ in dims), "%s | %s" % (dims, said(r)))
    except ImportError:
        check.skip("337: a large scanned page", "pymupdf is not installed here")

    def excel_ods(sheets, before=(), head=""):
        """An ODS in Excel's order: content.xml right after the styles, before the rest; `before`: members
        [(name, text)] written ahead of content.xml, as LibreOffice writes its settings.xml and meta.xml;
        `head`: what content.xml holds before its body (LibreOffice's automatic styles)."""
        body = "".join('<table:table table:name="%s">%s</table:table>' % (name, "".join(
            '<table:table-row><table:table-cell office:value-type="string"><text:p>%s</text:p></table:table-cell>'
            '<table:table-cell office:value-type="float" office:value="%d"><text:p>%d</text:p></table:table-cell>'
            '</table:table-row>' % (label, n, n) for label, n in rows)) for name, rows in sheets)
        ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:'
              'opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.spreadsheet")
            z.writestr("styles.xml", '<?xml version="1.0"?><office:document-styles %s/>' % ns)
            for member, text in before:
                z.writestr(member, text)
            z.writestr("content.xml", '<?xml version="1.0" encoding="UTF-8"?><office:document-content %s>%s<office:body>'
                       '<office:spreadsheet>%s</office:spreadsheet></office:body></office:document-content>'
                       % (ns, head, body))
            if "meta.xml" not in dict(before):
                z.writestr("meta.xml", '<?xml version="1.0"?><office:document-meta %s/>' % ns)
        return buf.getvalue()

    def rows_arrived(whole, cut, member):
        """The rows of `member` that ended in what arrived of it (`cut`, the file's first bytes): its deflate
        stream unpacked up to the cut."""
        off = zipfile.ZipFile(io.BytesIO(whole)).getinfo(member).header_offset
        n, e = struct.unpack("<HH", whole[off + 26:off + 30])
        return zlib.decompressobj(-15).decompress(cut[off + 30 + n + e:]).count(b"</table:table-row>")
    sheet = excel_ods([("First", [("FIRST-ROW %d of the survey" % k, k) for k in range(600)]),
                       ("Second", [("SECOND-ROW %d of the survey" % k, k) for k in range(600)])])
    p = os.path.join(tmpc, "cut.ods")
    with open(p, "wb") as fh:
        fh.write(into(sheet, "content.xml", 0.3))
    r = run_read(p, env=env)
    text, sig = r.file("content.md"), (r.manifest.get("signals") or {}).get("broken_archive") or {}
    check("254: an ODS cut in its content.xml reads the rows that arrived (it read nothing: the one part with its "
          "text was not whole)", r.manifest.get("status") == "ok" and "FIRST-ROW 0 of the survey" in text
          and "SECOND-ROW 599" not in text and sig.get("partial") == "content.xml"
          and "cut" in (r.manifest.get("advice") or ""), said(r))
    # the rows an ODS cut in its content.xml lost: from the first row not whole on, the extent not in the file
    # (content.xml names no sheet's size); Excel names no other sheet before its content.xml (KNOWN-ISSUES 267)
    cut = into(sheet, "content.xml", 0.3)
    want = "[rows · lost in the cut · %d-? · First]" % (rows_arrived(sheet, cut, "content.xml") + 1)
    check("267: an ODS cut in its content.xml says from which row its sheet lost its rows: %s, and names no lost "
          "sheet when nothing that arrived names them (Excel's order)" % want,
          want in text.split("\n") and "[sheet · " not in text, [ln for ln in text.split("\n") if "lost in the" in ln][:3])
    ns_cfg = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:config="urn:oasis:names:tc:'
              'opendocument:xmlns:config:1.0" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"')

    def lo_settings(names):
        """settings.xml as LibreOffice writes it, its sheets named (by name, not in their order)."""
        return [("settings.xml", '<?xml version="1.0"?><office:document-settings %s><office:settings>'
                 '<config:config-item-set config:name="ooo:view-settings"><config:config-item-map-named '
                 'config:name="Tables">%s</config:config-item-map-named></config:config-item-set>'
                 '</office:settings></office:document-settings>' % (ns_cfg, "".join(
                     '<config:config-item-map-entry config:name="%s"/>' % n for n in sorted(names))))]
    three = [("First", [("FIRST-ROW %d of the survey" % k, k) for k in range(600)]),
             ("Second", [("SECOND-ROW %d" % k, k) for k in range(10)]), ("Third", [("THIRD-ROW %d" % k, k) for k in range(10)])]
    lo = excel_ods(three, before=lo_settings(["First", "Second", "Third"]))
    p = os.path.join(tmpc, "cut-lo.ods")
    with open(p, "wb") as fh:
        fh.write(into(lo, "content.xml", 0.3))
    text = run_read(p, env=env).file("content.md")
    check("267: a LibreOffice ODS cut in its content.xml names the sheets the cut took, from its settings.xml - "
          "and, being several, says their order is not known",
          "[sheet · lost in the cut · order unknown · Second]" in text.split("\n")
          and "[sheet · lost in the cut · order unknown · Third]" in text.split("\n")
          and re.search(r"^\[rows · lost in the cut · \d+-\? · First\]$", text, re.M) is not None,
          [ln for ln in text.split("\n") if "lost in the" in ln][:4])
    # settings.xml lists the sheets by name, not in the workbook's order (LibreOffice writes it so): the markers of the
    # sheets it names stand after the last sheet that arrived and claim no order among themselves (KNOWN-ISSUES 267)
    mixed = three + [("Zebra", [("ZEBRA-ROW %d" % k, k) for k in range(10)]), ("Apple", [("APPLE-ROW %d" % k, k)
                                                                                         for k in range(10)])]
    lo_mixed = excel_ods(mixed, before=lo_settings(["First", "Second", "Third", "Zebra", "Apple"]))
    p = os.path.join(tmpc, "cut-lo-mixed.ods")
    with open(p, "wb") as fh:
        fh.write(into(lo_mixed, "content.xml", 0.3))
    rows_ = run_read(p, env=env).file("content.md").split("\n")
    marks = [ln for ln in rows_ if ln.startswith("[sheet · lost in the cut")]
    open_at = next((i for i, ln in enumerate(rows_) if ln.startswith("[rows · lost in the cut · ")), -1)
    check("267: the sheets settings.xml names come in its order (by name: Apple, Second, Third, Zebra - not the "
          "workbook's, which ends Zebra, Apple), each says the order is unknown, and they stand after the last sheet "
          "that arrived",
          marks == ["[sheet · lost in the cut · order unknown · %s]" % n for n in ("Apple", "Second", "Third", "Zebra")]
          and open_at >= 0 and all(rows_.index(m) > open_at for m in marks), marks)
    two = excel_ods(three[:2], before=lo_settings(["First", "Second"]))
    p = os.path.join(tmpc, "cut-lo-two.ods")
    with open(p, "wb") as fh:
        fh.write(into(two, "content.xml", 0.3))
    rows_ = run_read(p, env=env).file("content.md").split("\n")
    check("267: one sheet lost, named from settings.xml: its place is known (after the last that arrived), so no word "
          "of order", [ln for ln in rows_ if ln.startswith("[sheet · lost in the cut")] == ["[sheet · lost in the cut · Second]"],
          [ln for ln in rows_ if "lost in the" in ln][:3])
    counted = excel_ods(three, before=[("meta.xml", '<?xml version="1.0"?><office:document-meta %s><office:meta>'
                                        '<meta:document-statistic meta:table-count="3"/></office:meta>'
                                        '</office:document-meta>' % ns_cfg)])
    p = os.path.join(tmpc, "cut-count.ods")
    with open(p, "wb") as fh:
        fh.write(into(counted, "content.xml", 0.3))
    text = run_read(p, env=env).file("content.md")
    check("267: one whose meta.xml alone arrived counts them: [sheet · lost in the cut · the sheet 2 of 3]",
          "[sheet · lost in the cut · the sheet 2 of 3]" in text.split("\n")
          and "[sheet · lost in the cut · the sheet 3 of 3]" in text.split("\n"), [ln for ln in text.split("\n")
                                                                                   if "lost in the" in ln][:4])
    early_cut = excel_ods([("Only", [("ONLY-ROW %d" % k, k) for k in range(5)])], before=lo_settings(["Only"]),
                          head="<!-- %s -->" % " ".join("style%d-%d" % (k, (k * 7919) % 10007) for k in range(4000)))
    p = os.path.join(tmpc, "cut-early.ods")
    with open(p, "wb") as fh:
        fh.write(into(early_cut, "content.xml", 0.5))
    text = run_read(p, env=env).file("content.md")
    check("267: a spreadsheet cut before its first sheet began (LibreOffice writes its styles first) names every "
          "sheet as lost", "[sheet · lost in the cut · Only]" in text.split("\n") and "ONLY-ROW" not in text, text[:120])
    p = os.path.join(tmpc, "cut-at-once.ods")
    with open(p, "wb") as fh:
        fh.write(into(early_cut, "content.xml", 0.002))
    text = run_read(p, env=env).file("content.md")
    check("267: ... and one cut before content.xml's first element ended too", "[sheet · lost in the cut · Only]"
          in text.split("\n"), text[:120])
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
    import docreaders                                                                              # noqa: E402
    import tabs                                                                                    # noqa: E402
    check("267: the reader's state word is tabs.STATE's (it imports nothing of the skill's)",
          docreaders.LOST == tabs.STATE["cut"], "%r %r" % (docreaders.LOST, tabs.STATE.get("cut")))
    try:
        import docx
        d = docx.Document()
        for k in range(4):
            d.add_paragraph("DOCX-PICTURE-%d %s" % (k, EN))
            d.add_picture(io.BytesIO(noise_png(50 + k, 50)))
        dbuf = io.BytesIO()
        d.save(dbuf)
        p = os.path.join(tmpc, "pictures.docx")
        with open(p, "wb") as fh:
            fh.write(cut_in(reordered(dbuf.getvalue(), ("word/media/",), ("word/document.xml",)), "word/document.xml", 100))
        r = run_read(p, env=env)
        check("167: a DOCX cut in its text, its pictures whole before it: an error, not `ok` on its pictures' list",
              r.manifest.get("status") == "error" and len(r.manifest.get("images") or []) == 4
              and "DOCX-PICTURE" not in r.file("content.md")
              and "no text could be read" in (r.manifest.get("advice") or ""), said(r))
        # a DOCX whose XML breaks: python-docx's own error is named, not "no converter for this file type (pymupdf)"
        zin = zipfile.ZipFile(io.BytesIO(dbuf.getvalue()))
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as z:
            for i in zin.infolist():
                part = zin.read(i)
                z.writestr(i.filename, part.replace(b"<w:body>", b"<w:body>&undeclared;", 1)
                           if i.filename == "word/document.xml" else part)
        p = os.path.join(tmpc, "badxml.docx")
        with open(p, "wb") as fh:
            fh.write(bad.getvalue())
        r = run_read(p, env={"READ_PAGE_SKIP": "browser,pandoc,markitdown"})
        note = (r.manifest.get("signals") or {}).get("document_note") or ""
        check("a DOCX whose XML breaks names python-docx and its error, not \"no converter (pymupdf)\", and is `empty` "
              "with its pictures (it was `ok` on their list)", "python-docx could not read it" in note
              and "pymupdf" not in json.dumps(r.manifest) and r.manifest.get("status") == "empty", said(r))
    except ImportError:
        check.skip("167: a cut DOCX with pictures", "python-docx is not installed here")
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600       # a compound file, its directory's stream names
    for name, data, want in (
            ("old.docx", ole2 + "WordDocument".encode("utf-16-le") + b"\x00" * 900, "Word 97-2003"),
            ("locked.xlsx", ole2 + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 900, "password-protected"),
            ("noise.epub", bytes(range(1, 256)) * 30, "no type this skill knows")):
        p = os.path.join(tmpc, name)
        with open(p, "wb") as fh:
            fh.write(data)
        r = run_read(p, env=env)
        check("167: %s that is no ZIP is named for what it is (%s)" % (name, want),
              r.manifest.get("status") == "empty" and want in str((r.manifest.get("signals") or {}).get(
                  "status_reason")) and "not a ZIP archive" in str((r.manifest.get("signals") or {}).get(
                      "status_reason")) and r.manifest.get("advice") and not no_converter(r), said(r))
    # member names written in GBK with no UTF-8 flag (Windows' own zipper, many Chinese tools): zipfile reads
    # them as CP437, and the listing and the headings said "╦╡├≈.txt"
    zbuf, stand = io.BytesIO(), []
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, (name, body) in enumerate((("说明.txt", "GBK-NAMED-FACT the note. " + EN), ("数据/报告.txt", EN))):
            raw = name.encode("gbk")
            stand.append((("~%04d" % k).ljust(len(raw), "~").encode("ascii"), raw))
            z.writestr(stand[-1][0].decode("ascii"), body)
    zdata = zbuf.getvalue()
    for st, raw in stand:
        zdata = zdata.replace(st, raw)
    gbkzip = os.path.join(tmpc, "gbk-names.zip")
    with open(gbkzip, "wb") as fh:
        fh.write(zdata)
    r = run_read(gbkzip, env=env)
    text = r.file("content.md")
    check("a ZIP's members named in GBK with no UTF-8 flag are listed and headed by their names (were CP437)",
          "- 说明.txt" in text and "## 说明.txt" in text and "数据/报告.txt" in text and "GBK-NAMED-FACT" in text,
          repr(text[:160]))
    s.routes["/text.zip"] = (200, {"Content-Type": "application/zip"},
                             ("The file you asked for was moved to the archive server. " + EN * 2).encode())
    r = run_read(s.url("/text.zip"), env=env)
    check("167: text served as a ZIP is answered with its text, and said to be no archive",
          "moved to the archive server" in r.file("content.md") and "is text" in (r.manifest.get("advice") or "")
          and not no_converter(r), said(r))

    # ------------------------------------------------ a document's picture left out is never asked of its server
    # a 1x1 counter in an RTF or a DOCX kept its link, which the picture phase resolved against the document's
    # address: `rtf-pict-0002.png`, a name our reader made up, was asked of the server
    def hexpic(data):
        return data.hex().encode()
    pix_rtf = (b"{\\rtf1\\ansi RTF-PICTURES-FACT " + (EN * 3).encode() + b"\\par {\\pict\\pngblip "
               + hexpic(png(30, 20, (200, 10, 10))) + b"}\\par {\\pict\\pngblip " + hexpic(png(1, 1, (0, 0, 0)))
               + b"}\\par The end.\\par}")
    s.routes["/pics/pixel.rtf"] = (200, {"Content-Type": "application/rtf"}, pix_rtf)
    before = len(s.log)
    r = run_read(s.url("/pics/pixel.rtf"), env=env)
    asked = [x["path"] for x in s.log[before:]]
    text = r.file("content.md")
    check("pictures: an RTF's 1x1 picture is left out with its link: nothing asked of the server for it, one marker",
          asked == ["/pics/pixel.rtf"] and text.count("[img #") == 1 and "rtf-pict-0002" not in text and "![" not in text
          and len(r.manifest.get("images") or []) == 1, "%s %s %r" % (asked, len(r.manifest.get("images") or []),
                                                                   re.findall(r"\[img #[^\n]*", text)))
    try:
        import docx
        dd = docx.Document()
        dd.add_paragraph("DOCX-PIXEL-FACT " + EN * 3)
        dd.add_picture(io.BytesIO(png(40, 40, (10, 200, 10))))
        dd.add_picture(io.BytesIO(png(1, 1, (255, 255, 255))))
        dd.add_paragraph("After the pictures.")
        dbuf = io.BytesIO()
        dd.save(dbuf)
        s.routes["/pics/pixel.docx"] = (200, {"Content-Type": "application/vnd.openxmlformats-officedocument."
                                                              "wordprocessingml.document"}, dbuf.getvalue())
        before = len(s.log)
        r = run_read(s.url("/pics/pixel.docx"), env=env)
        asked = [x["path"] for x in s.log[before:]]
        text = r.file("content.md")
        check("pictures: ... a DOCX's 1x1 picture the same (word/media/image2.png was asked of the server)",
              asked == ["/pics/pixel.docx"] and text.count("[img #") == 1 and "word/media" not in text,
              "%s %r" % (asked, re.findall(r"\[img #[^\n]*", text)))
    except ImportError:
        check.skip("pictures: a DOCX's 1x1 picture", "python-docx is not installed here")
    with open(picture_epub("served.epub"), "rb") as fh:
        s.routes["/pics/book.epub"] = (200, {"Content-Type": "application/epub+zip"}, fh.read())
    before = len(s.log)
    r = run_read(s.url("/pics/book.epub"), env=env)
    asked = [x["path"] for x in s.log[before:]]
    gone = [e for e in r.manifest.get("images") or [] if not e.get("file")]
    check("pictures: an EPUB's picture its archive lacks is named so, not asked of the server under its name there",
          asked == ["/pics/book.epub"] and len(gone) == 1 and gone[0].get("why") == "not in the document"
          and gone[0].get("n") == 3, "%s %s" % (asked, gone))
finally:
    s.close()
sys.exit(check.done())
