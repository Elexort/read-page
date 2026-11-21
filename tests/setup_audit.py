"""The setup contract, tested in both directions.

    python -X utf8 tests/setup_audit.py

Two failures have happened and must not come back:

  * an engine is missing and nothing ever names it - the user cannot install what is not said;
  * an engine is installed and the advice still asks for it - the report stops being trustworthy.

The first half runs on a synthetic *empty* machine (`caps()` shadowed), the second on a synthetic
*full* one, so the result does not depend on what this runner happens to have. One end-to-end read
is done with every extractor disabled, to prove a page still comes back without any of them.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "readpage.py")
ok = failed = 0
# the report's contract on a machine with no --setup environment: this machine's own one (its
# setup.json names what it could not do) must not leak into the synthetic machines below
os.environ["READ_PAGE_HOME"] = tempfile.mkdtemp(prefix="audit-home-")
for _name in ("READ_PAGE_ENV", "READ_PAGE_ENV_CHILD", "READ_PAGE_TESSDATA"):
    os.environ.pop(_name, None)


def check(name, good, detail=""):
    global ok, failed
    if good:
        ok += 1
        print("OK   %-62s %s" % (name, detail))
    else:
        failed += 1
        print("FAIL %-62s %s" % (name, detail))


def inproc(argv, patch=None, env=None):
    spec = importlib.util.spec_from_file_location("rp_audit_%d" % time.time_ns(), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    saved = {k: getattr(mod, k) for k, v in (patch or {}).items()}
    for k, v in (patch or {}).items():
        setattr(mod, k, v)
    old_env = {}
    for k, v in (env or {}).items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main(argv)
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return rc, buf.getvalue(), mod


LIBS = ("trafilatura", "html2text", "pymupdf", "curl_cffi", "patchright", "playwright",
        "readability", "PIL", "pymupdf4llm")
CLIS = ("defuddle", "markitdown", "pandoc", "pdftotext", "yt-dlp", "curl", "tesseract", "lynx", "w3m")


def caps_of(libs=False, cli=False, browsers=False, langs=(), keys=False):
    return {"at": time.time(), "python": "3.13.0",
            "libs": {k: libs for k in LIBS},
            "cli": {k: ("/usr/bin/" + k if cli else None) for k in CLIS} if cli else {},
            "browsers": [{"name": "chrome", "path": "/usr/bin/chrome", "channel": "chrome",
                          "kind": "path"}] if browsers else [],
            "keys": {"FIRECRAWL_API_KEY": keys, "JINA_API_KEY": keys},
            "ocr_langs": list(langs)}


def gaps_for(mod, caps, ctx):
    missing, improve = mod.gaps(caps, ctx)
    return ([m.get("what") for m in missing], [m.get("what") for m in improve],
            json.dumps(missing + improve))


rc, _, mod = inproc(["--caps"])

# ---------------------------------------------------------------- an empty machine
empty = caps_of()
rows = mod.setup_rows(empty)
report = mod.setup_report(empty)
fixable = [(n, f) for n, good, f, _g in rows if not good and f]
check("empty machine: every engine with a fix is named in the report",
      all(n in report for n, _f in fixable), "%d rows" % len(fixable))
check("empty machine: the report names --setup, and that the user's one yes is all it needs",
      "readpage.py --setup installs every line that names it" in report and "ask the" in report
      and "environment: none yet" in report, "")
setup_rows_ = [(n, f) for n, good, f, _g in rows if not good and f == "readpage.py --setup"]
own = [n for n, good, f, _g in rows if not good and f and f != "readpage.py --setup"]
check("empty machine: --setup is the fix for every engine it installs here",
      {"curl_cffi", "defuddle", "trafilatura", "browser", "pymupdf", "yt-dlp"}
      <= {n for n, _f in setup_rows_}, str(sorted(own)))
check("empty machine: no pandoc is offered (our readers read EPUB, ODT and RTF; --setup installs none)",
      "pandoc" not in {n for n, _g, _f, _x in rows} and "pandoc" not in report.lower(), "")
want_installer = {"nt": "winget", "darwin": "brew"}.get(
    "nt" if os.name == "nt" else ("darwin" if sys.platform == "darwin" else ""), "apt")
check("empty machine: what --setup cannot install names this OS's installer",
      want_installer in report and set(own) <= {"curl", "lynx", "pdftotext", "tesseract"}, want_installer)
check("empty machine: no engine is claimed to work",
      "nothing beyond the standard library" in report, "")

m, i, text = gaps_for(mod, empty, {"need_browser": True})
check("empty machine + a JavaScript shell: browser and extractor asked for",
      "browser" in m and ("http-client" in m or "extractor" in m), text[:90])
m, i, text = gaps_for(mod, empty, {"kind_doc": True})
check("empty machine + a document: a document reader is asked for",
      "documents" in m or "documents" in i, text[:90])
# an EPUB, ODT or RTF is our readers' (the standard library), a plain or cut archive no engine's: nothing
# to install for them - the gap was named for any archive (kind_doc was "pdf or zip")
m, i, text = gaps_for(mod, empty, {"kind_doc": False})
check("empty machine + an EPUB or ODT (our readers'): no document reader is asked for",
      "documents" not in m and "documents" not in i, text[:90])
m, i, text = gaps_for(mod, empty, {"office_lib": "python-docx"})
check("empty machine + a DOCX whose library is not here: that library is named, not pymupdf",
      "documents" in m and "python-docx" in text and "pymupdf" not in text, text[:120])
d = tempfile.mkdtemp(prefix="audit-doc-")
import zipfile  # noqa: E402
with zipfile.ZipFile(os.path.join(d, "book.epub"), "w") as z:
    z.writestr("mimetype", "application/epub+zip")
    z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="c.opf"/></rootfiles></container>')
    z.writestr("c.opf", '<package><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>'
                        '</manifest><spine><itemref idref="a"/></spine></package>')
    z.writestr("a.xhtml", "<html><body><p>%s</p></body></html>" % ("An EPUB read by our own reader. " * 20))
os.environ["READ_PAGE_CACHE"] = os.path.join(d, "cache")
rc, out, _m = inproc([os.path.join(d, "book.epub"), "--json"], patch={"caps": lambda: caps_of()})
try:
    man = json.loads(out)
except ValueError:
    man = {}
check("an EPUB read on a machine without pymupdf, pdftotext or markitdown asks for no document reader",
      man.get("status") == "ok" and not [x for x in (man.get("missing") or []) + (man.get("improve") or [])
                                         if x.get("what") == "documents"],
      "%s %s" % (man.get("status"), json.dumps(man.get("missing"))[:120]))
m, i, text = gaps_for(mod, empty, {"no_text_layer": True})
check("empty machine + a scan: OCR is asked for", "ocr" in i or "ocr" in m, text[:90])
m, i, text = gaps_for(mod, empty, {"video": True})
check("empty machine + a video: yt-dlp is asked for", "video" in m or "video" in i, text[:90])
m, i, text = gaps_for(mod, empty, {"blocked": True})
check("empty machine + a wall: the paid key is named as an option",
      "FIRECRAWL_API_KEY" in text, text[:90])
m, i, text = gaps_for(mod, dict(caps_of(libs=True), libs=dict(caps_of(libs=True)["libs"], pymupdf4llm=False)),
                      {"kind_doc": True, "pdf_tables": 3})
check("a PDF whose pages look like tables, no layout model: what reads a table is asked for",
      "tables" in i and "3 pages" in text, text[:120])
m, i, text = gaps_for(mod, caps_of(libs=True), {"kind_doc": True, "pdf_tables": 3})
check("... and nothing is asked where the model is installed", "tables" not in i, text[:120])
no_onnx = dict(caps_of(libs=True), libs=dict(caps_of(libs=True)["libs"], onnxruntime=False))
m, i, text = gaps_for(mod, no_onnx, {"kind_doc": True, "pdf_tables": 3})
row = [g for n, g, _f, _g in mod.setup_rows(no_onnx) if n == "pymupdf4llm"]
check("... nor met in silence where pymupdf4llm is there without onnxruntime (it imports, lays out nothing)",
      "tables" in i and row == [False], "%s %s" % (text[:120], row))
check("the setup report has a line for the tables' model",
      any(n == "pymupdf4llm" for n, _good, _f, _g in rows), str([n for n, _good, _f, _g in rows]))

# a page still reads with every extractor gone (the crude path is the floor)
html = ("<!doctype html><html><head><title>Bare</title></head><body><h1>Bare page</h1><p>"
        + ("a sentence of real text. " * 40) + "</p></body></html>")
d = tempfile.mkdtemp(prefix="audit-")
with open(os.path.join(d, "bare.html"), "w", encoding="utf-8") as fh:
    fh.write(html)


class H(__import__("http.server").server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


import socketserver  # noqa: E402
import threading     # noqa: E402

srv = socketserver.TCPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["READ_PAGE_CACHE"] = os.path.join(d, "cache")
rc, out, mod_e2e = inproc(["http://127.0.0.1:%d/bare" % srv.server_address[1], "--json"],
                          patch={"caps": lambda: caps_of()})
_rc, said, _m = inproc(["http://127.0.0.1:%d/bare" % srv.server_address[1]],
                       patch={"caps": lambda: caps_of()})
srv.shutdown()
try:
    man = json.loads(out)
except Exception:
    man = {}
check("empty machine: a plain page still reads (crude is the floor)",
      man.get("status") == "ok" and (man.get("content") or {}).get("chars", 0) > 500,
      "%s %s" % (man.get("status"), (man.get("content") or {}).get("chars")))
check("empty machine: the manifest says what to install",
      bool(man.get("missing") or man.get("improve")),
      json.dumps((man.get("missing") or man.get("improve") or [])[:1])[:80])
check("empty machine: so does the printed answer, above the text",
      "\nmissing: " in said.split("── ")[0] or "\nimprove: " in said.split("── ")[0],
      said.split("\n")[0][:80])

# ---------------------------------------------------------------- a full machine
full = caps_of(libs=True, cli=True, browsers=True, langs=("eng", "osd", "rus"), keys=True)
rows_full = mod.setup_rows(full)
check("full machine: every engine is detected",
      all(good for _n, good, _f, _g in rows_full),
      ", ".join(n for n, good, _f, _g in rows_full if not good))
check("full machine: the report asks for nothing",
      "worth adding" not in mod.setup_report(full), "")
for ctx in ({"need_browser": True}, {"kind_doc": True}, {"no_text_layer": True},
            {"blocked": True}, {"video": True}):
    m, i, text = gaps_for(mod, full, ctx)
    check("full machine: no advice for %s" % sorted(ctx)[0], not m and not i,
          json.dumps(m + i)[:80])

# OCR installed and not starting: not a working engine, and not silent
broken_ocr = dict(caps_of(libs=True), ocr_error="does not start: Failed to init API, possibly an invalid tessdata path")
broken_ocr["libs"] = dict(broken_ocr["libs"], tesserocr=False)
rows_b = {n: (good, f, g) for n, good, f, g in mod.setup_rows(broken_ocr)}
m, i, text = gaps_for(mod, broken_ocr, {"no_text_layer": True})
check("OCR installed but not starting: the report lists it as missing, with why",
      rows_b["tesseract"][0] is False and "does not start" in rows_b["tesseract"][2]
      and "tesseract" in mod.setup_report(broken_ocr).split("worth adding")[-1], str(rows_b["tesseract"])[:120])
check("... and a scan names it as missing (not an improvement, not nothing), with why",
      "ocr" in m and "ocr" not in i and "does not start" in text, text[:140])
no_short = dict(broken_ocr, ocr_error="does not start: its language data is in C:\\Users\\Иван\\.read-page\\tessdata, "
                                      "a folder whose name has characters outside ASCII that OCR cannot open")
check("... with the fix that works for a path outside ASCII: READ_PAGE_HOME on an ASCII folder",
      "READ_PAGE_HOME" in json.dumps(gaps_for(mod, no_short, {"no_text_layer": True})[2]), "")

# ---------------------------------------------------------------- no dead detection
covered = {n for n, _g, _f, _x in rows_full}
check("every library caps() looks for is either a row or not used",
      {"trafilatura", "html2text", "pymupdf", "curl_cffi", "readability"} <= covered,
      str(sorted({"trafilatura", "html2text", "pymupdf", "curl_cffi", "readability"} - covered)))
# markitdown and pandoc are looked for only as an office file's last resort when the machine has one:
# never a row
check("every CLI caps() looks for is either a row or not used",
      {"defuddle", "pdftotext", "curl", "tesseract", "yt-dlp"} <= covered
      and not ({"markitdown", "pandoc"} & covered),
      str(sorted({"defuddle", "pdftotext", "curl", "tesseract", "yt-dlp"} - covered)))
check("the report names nothing the reader never runs (LibreOffice, ffmpeg)",
      not ({"libreoffice", "ffmpeg"} & covered) and "libreoffice" not in mod.setup_report(empty).lower()
      and "ffmpeg" not in mod.setup_report(empty).lower(), str(sorted(covered)))
tess_only = caps_of(langs=("eng", "osd"))
tess_only["cli"] = {"tesseract": "/usr/bin/tesseract"}
ocr_row = [r for r in mod.setup_rows(tess_only) if r[0] == "ocr-langs"]
check("with tesseract and English alone the report offers another language pack",
      ocr_row and not ocr_row[0][1] and ("traineddata" in ocr_row[0][2] or "READ_PAGE_OCR_LANGS" in ocr_row[0][2])
      and "ocr-langs" in mod.setup_report(tess_only), str(ocr_row)[:120])
check("no language-pack row where there is no tesseract",
      not [r for r in mod.setup_rows(empty) if r[0] == "ocr-langs"], "")

# ---------------------------------------------------------------- this machine
real = mod.caps()
rows_real = mod.setup_rows(real)
check("this machine: every row is either working or explained",
      all(good or fix for _n, good, fix, _g in rows_real),
      ", ".join(n for n, good, fix, _g in rows_real if not good and not fix))
ok_names = {n for n, good, _f, _g in rows_real if good}
check("this machine: what is claimed is really there",
      ("defuddle" in ok_names) == bool(real["cli"].get("defuddle"))
      and ("curl_cffi" in ok_names) == bool(real["libs"].get("curl_cffi")),
      "libs=%s cli=%s" % (real["libs"].get("curl_cffi"), bool(real["cli"].get("defuddle"))))
okmap = {n: good for n, good, _f, _g in rows_real}
m, i, text = gaps_for(mod, real, {"need_browser": True, "kind_doc": True, "video": True})
# missing[] only: improve[] is allowed to suggest a better engine next to a working one
bogus = [x for x in m if
         (x == "video" and okmap.get("yt-dlp"))
         or (x == "browser" and okmap.get("browser"))
         or (x == "http-client" and (okmap.get("curl_cffi") or okmap.get("curl")))
         or (x == "extractor" and (okmap.get("defuddle") or okmap.get("trafilatura")
                                  or okmap.get("html2text")))
         or (x == "documents" and (okmap.get("pymupdf") or okmap.get("markitdown")
                                  or okmap.get("pdftotext")))]
check("this machine: no advice for an engine it already has", not bogus, str(bogus)[:90])

# ---------------------------------------------------------------- linux desktop wrappers
if sys.platform.startswith("linux"):
    snap = "/snap/bin/chromium"
    flat = "/var/lib/flatpak/exports/bin/com.google.Chrome"
    names = {b.get("name") for b in (mod.caps().get("browsers") or [])}
    if not (os.path.isfile(snap) or os.path.isfile(flat)):
        print("SKIP snap/flatpak detection (no wrapper on this machine; CI creates %s)" % snap)
    else:
        check("linux: a snap or flatpak wrapper is detected as a browser",
              bool(names & {"chromium-snap", "chrome-flatpak", "chromium-flatpak"}),
              str(sorted(names)))

print("\n%d ok, %d failed" % (ok, failed))
sys.exit(0 if failed == 0 else 1)
