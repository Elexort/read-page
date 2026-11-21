"""Formats. No network.

    python -X utf8 tests/formats.py

RTF and OpenDocument are known by their content - an RTF served as octet-stream, an ODT whose
`mimetype` is not EPUB's - and read through pandoc, or the stdlib readers without it. A file
on this machine goes through the same converters with no network; over MCP only one inside
read-page's own folders. --alternate reads a PDF with pymupdf4llm when it is installed
(headings as markdown). YouTube's caption track when yt-dlp gives none - youtube-transcript-api,
else a machine's own markitdown. Also pandoc's Markdown cleaned
with code untouched, a DOCX's content controls and text boxes, a PPTX's groups and tables, a plain
ZIP's files and their text.
"""
import importlib.util
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


# pymupdf4llm as the tests need it, first on the model's process' path (READ_PAGE_TEST_MODEL_PATH,
# which pdftables.py alone reads: the process runs with -E): the tables above with the model's own
# (cut) cells; a page that fails, a process that ends at a page, a page or a Markdown call that
# takes long; a model that does not load
STUB = '''
import json, os, time
if os.environ.get("RP_STUB_NOLOAD"):
    raise ImportError("RP-STUB: no model here")
_use_layout = True
GRID = %s
MODEL = %s

def to_json(doc, pages, **kw):
    p = pages[0] if pages else -1
    if os.environ.get("RP_STUB_CRASH") == str(p):
        os._exit(9)
    if os.environ.get("RP_STUB_SLEEP"):
        time.sleep(float(os.environ["RP_STUB_SLEEP"]))
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
    have_pandoc = bool(mod.which("pandoc"))
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
    plain = mod.odf_text(odt_path)
    check("ODT without pandoc: heading and paragraphs in order (the stdlib reader)",
          plain.startswith("# ODT-HEADING") and plain.rstrip().endswith("ODT-MARKER."), repr(plain[:60]))

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
              got == {} and mod3._TABLES["worker"] is None, str(got))
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
            os.environ["RP_STUB_CRASH"] = "1"
            mod3.tables_reset()
            info = mod3.pdf_tables(many, d3, [p.get_text() for p in d3])
            check("a PDF's tables: when the model's process ends at a page, that page and the ones after it "
                  "are named, as the time's end names them",
                  info.get("asked") == 1 and info.get("left") == [2, 3] and info.get("stopped") == [2, 3]
                  and "process ended" in (info.get("error") or "")
                  and "pages 2-3 are still one cell a line (the layout model did not work" in mod3.tables_advice(info),
                  "%s | %s" % (info, mod3.tables_advice(info)))
            os.environ.pop("RP_STUB_CRASH", None)
            mod3.tables_close(kill=True)
            os.environ["RP_STUB_NOLOAD"] = "1"
            mod3.tables_reset()
            info = mod3.pdf_tables(many, d3, [p.get_text() for p in d3])
            mod3.tables_merge(info)
            check("a PDF's tables: a model that does not load is said in signals.tables.error, not met in silence",
                  "RP-STUB: no model here" in (mod3.tables_signal().get("error") or "") and not info.get("pages")
                  and mod3.tables_signal().get("left") == "1-3", str(mod3.tables_signal()))
        finally:
            for k in ("RP_STUB_NOLOAD", "RP_STUB_FAIL", "RP_STUB_CRASH", "READ_PAGE_TEST_MODEL_PATH"):
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
            # under those counts the model can still take long (2 010 strokes: 11 s, 8 010: 24 s): its
            # process is killed when the time is up, and the read keeps its deadline
            sl = os.path.join(tmp, "slow.pdf")
            doc = pymupdf.open()
            strokes_page(doc, strokes=7000)
            doc.save(sl)
            doc.close()
            r = run_read(sl, env=dict(env, READ_PAGE_TEST_DEADLINE="4"))
            tab = (r.manifest.get("signals") or {}).get("tables") or {}
            check("a PDF's tables: a slow page does not hold the read past its deadline (4 s here)",
                  r.manifest.get("status") == "ok" and tab.get("left") == "1" and r.seconds < 7
                  and "Row 8" in r.file("content.md"), "%.1f s %s %s" % (r.seconds, r.manifest.get("status"), tab))
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
    if not have_pandoc:
        check.skip("an EPUB with one picture missing from its archive", "no pandoc: no text that names the pictures")
    else:
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
finally:
    s.close()
sys.exit(check.done())
