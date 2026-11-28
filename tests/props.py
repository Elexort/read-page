"""Property checks for the parts that break silently on real machines:
paths with spaces and non-ASCII, cropping, cache reuse, page metadata, images,
single-file endpoints, size limits, login walls, Google export mapping, docx notes
and docx images.

Runs entirely offline: a local HTTP server serves generated pages and files, and the
few network-shaped functions (google_export, docx_notes) are called in-process.

    python -X utf8 tests/props.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):    # the user's debug log switches stay out
    os.environ.pop(_name, None)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "readpage.py")
PY = [sys.executable, "-X", "utf8", SCRIPT]
BUDGET_BYTES, BUDGET_LINES = 9980, 495     # the answer contract
ok = failed = 0


# ---------------------------------------------------------------- helpers

def check(name, cond, detail=""):
    global ok, failed
    if cond:
        ok += 1
        print("OK   %-52s %s" % (name, detail))
    else:
        failed += 1
        print("FAIL %-52s %s" % (name, detail))


def why(m):
    """A failure detail that survives the trip through CI logs."""
    sig = m.get("signals") or {}
    return " | ".join(x for x in (str(m.get("status")), str(sig.get("status_reason") or ""),
                                  str(sig.get("network") or ""), str(m.get("advice") or "")) if x)[:200]


def run(args, cwd=None):
    env = dict(os.environ)
    if os.environ.get("PROPS_TRACE"):
        env["READ_PAGE_TRACE"] = "1"
    p = subprocess.run(PY + args + ["--json"], capture_output=True, cwd=cwd, env=env)
    err = p.stderr.decode("utf-8", "replace")
    if p.returncode != 0 and err.strip():
        print("   child stderr: %s" % " / ".join(err.strip().splitlines()[-12:])[:1500])
    return p.returncode, p.stdout.decode("utf-8", "replace"), err


def load_module():
    spec = importlib.util.spec_from_file_location("readpage_props", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inproc(argv, patch=None):
    """Call readpage.main() in-process with optional module globals patched."""
    mod = load_module()
    for k, v in (patch or {}).items():
        setattr(mod, k, v)
    buf = io.StringIO()
    rc = 0
    with contextlib.redirect_stdout(buf):
        try:
            rc = mod.main(list(argv) + ["--json"])
        except SystemExit:
            rc = 2
    out = buf.getvalue()
    try:
        return rc, json.loads(out), mod
    except Exception:
        return rc, {}, mod


def png(w, h, color=(200, 30, 30)):
    raw = b"".join(b"\x00" + bytes(color) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def jpeg(w=64, h=48):
    """A tiny valid JPEG header is enough: magic detection and dims both look at markers."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\xff\xd9"


def docx_bytes(body_text, footnote, media_png):
    """A real DOCX (python-docx writes the skeleton), then a footnote and a picture are added.

    The body comes from python-docx so the fast path reads it; footnotes and media are appended
    as package parts, exactly as Word and Google Docs store them.
    """
    import zipfile
    try:
        import docx as _docx
        d = _docx.Document()
        d.add_paragraph(body_text)
        base = io.BytesIO()
        d.save(base)
        parts = {}
        with zipfile.ZipFile(io.BytesIO(base.getvalue())) as z:
            for name in z.namelist():
                parts[name] = z.read(name)
        parts["word/footnotes.xml"] = (
            '<?xml version="1.0"?><w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:footnote w:id="1"><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:footnote></w:footnotes>'
            % footnote).encode("utf-8")
        parts["word/media/image1.png"] = media_png
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts.items():
                z.writestr(name, data)
        return out.getvalue()
    except Exception:
        pass
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                   '</Relationships>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:body><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:body></w:document>' % body_text)
        z.writestr("word/footnotes.xml",
                   '<?xml version="1.0"?><w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:footnote w:id="1"><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:footnote></w:footnotes>' % footnote)
        z.writestr("word/media/image1.png", media_png)
    return buf.getvalue()


def body(n, start=0, sentence="Строка текста для проверки свойств."):
    return "\n".join("<p>%s %d</p>" % (sentence * 3, i) for i in range(start, start + n))


# ---------------------------------------------------------------- fixtures

FILES = {}


def build_fixtures():
    FILES["/pencil.png"] = ("image/png", png(12, 12))
    FILES["/dot.png"] = ("image/png", png(1, 1))
    FILES["/photo.jpg"] = ("image/jpeg", jpeg())
    FILES["/big.jpg"] = ("image/jpeg", jpeg() + b"\x00" * 5000)
    FILES["/doc.docx"] = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          docx_bytes("Тело документа для проверки.",
                                     "Сноска из footnotes.xml, достаточно длинная для проверки.",
                                     png(20, 10)))

    image_page = """<!doctype html><html lang="ru"><head><title>Страница с картинками</title></head>
<body><article><h1>Картинки</h1>%s
<p>Первая картинка:</p><img src="/pencil.png" alt="карандаш">
<p>Между ними текст, чтобы позиция была видна.</p>
<img src="/pencil.png" alt="тот же файл"><img src="/dot.png" alt="пиксель">
<p>%s</p></article></body></html>""" % (body(4), body(4, 10))
    FILES["/images.html"] = ("text/html", image_page.encode("utf-8"))

    login_page = """<!doctype html><html lang="en"><head><title>Sign in</title></head><body>
<form><h1>Sign in</h1><input type="text" name="u"><input type="password" name="p">
<button>Sign in to continue</button></form></body></html>"""
    FILES["/login"] = ("text/html", login_page.encode("utf-8"))

    # ~18 words on purpose: the weak rule only fires under 40, and an extractor that adds one
    # navigation line must not decide whether the rule is tested
    weak_page = """<!doctype html><html lang="en"><head><title>Article</title></head><body><article>
<p>Sign in to save this article for later.</p><p>Plain article text that carries the page.</p>
</article></body></html>"""
    FILES["/weak.html"] = ("text/html", weak_page.encode("utf-8"))
    # prose that *talks about* walls must not be mistaken for a wall (403 docs, JS docs)
    mention_page = """<!doctype html><html lang="en"><head><title>HTTP 403 and JavaScript</title></head>
<body><article><h1>HTTP 403 Forbidden</h1>
<p>The server understood the request but refuses to authorize it. A 403 is not the same as an
access denied page served by a bot-protection service: the latter usually shows a challenge and
the words "checking your browser" or "enable javascript and cookies to continue".</p>
<p>%s</p>
<p>To tell the two apart, read the body: a real document explains the status, a challenge page
asks the visitor to wait or to prove they are human, and often it is served with 200.</p>
</article></body></html>""" % body(4, 40, "A documentation paragraph that belongs to the article. ")
    FILES["/mentions-wall.html"] = ("text/html", mention_page.encode("utf-8"))
    # a short page that *is* a challenge: this one must be reported as blocked
    FILES["/challenge.html"] = ("text/html", b"""<!doctype html><html><head><title>Just a moment</title></head>
<body><h1>Checking your browser before accessing the site</h1>
<p>Enable JavaScript and cookies to continue. Verifying you are human. This may take a few seconds.</p>
</body></html>""")
    FILES["/missing-but-pretty.html"] = ("text/html", ("""<!doctype html><html><head><title>Page not found</title>
</head><body><nav>%s</nav><main><h1>404</h1><p>This page has moved.</p></main></body></html>"""
        % " ".join("<a href='/x%d'>Section %d</a>" % (i, i) for i in range(200))).encode("utf-8"))
    FILES["/citation"] = ("text/plain",
                          b'{"doi":"10.31219/osf.io/mru2x","title":"A short machine-readable answer"}')
    # a picture that only fits when no limit applies
    FILES["/heavy.png"] = ("image/png", png(40, 40) + b"\x00" * 4000)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/secret":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if path == "/missing-but-pretty.html":
            ct, data = FILES[path]
            self.send_response(404)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        item = FILES.get(path)
        if not item:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Not found</h1></body></html>")
            return
        ct, data = item
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def validate(node, schema, path="$"):
    """A tiny JSON-Schema subset: type, const, enum, required, additionalProperties, properties.

    Enough to keep references/manifest-schema.json honest without adding a dependency. Keys that
    start with "_" are internal (cache bookkeeping) and are not part of the contract.
    """
    errs = []
    if not isinstance(node, dict):
        return ["%s: expected an object, got %s" % (path, type(node).__name__)]
    props = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in node:
            errs.append("%s: missing required %r" % (path, key))
    if schema.get("additionalProperties") is False:
        for key in node:
            if key.startswith("_"):
                continue
            if key not in props:
                errs.append("%s: %r is not in the schema" % (path, key))
    for key, val in node.items():
        if key.startswith("_") or key not in props:
            continue
        sub = props[key]
        want = sub.get("type")
        if want:
            kinds = want if isinstance(want, list) else [want]
            mappy = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
                     "object": dict, "array": list, "null": type(None)}
            if not any(isinstance(val, mappy[k]) and not
                       (k in ("integer", "number") and isinstance(val, bool)) for k in kinds):
                errs.append("%s.%s: expected %s, got %s" % (path, key, want, type(val).__name__))
        if "const" in sub and val != sub["const"]:
            errs.append("%s.%s: expected %r" % (path, key, sub["const"]))
        if "enum" in sub and val not in sub["enum"]:
            errs.append("%s.%s: %r is not one of %s" % (path, key, val, sub["enum"]))
        if isinstance(val, dict) and (sub.get("properties") or sub.get("additionalProperties") is False):
            errs.extend(validate(val, sub, path + "." + key))
    return errs


def main():
    tmp = tempfile.mkdtemp(prefix="read-page-props-")
    site = os.path.join(tmp, "site")
    os.makedirs(site)
    page = os.path.join(site, "тест с пробелами.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write("""<!doctype html><html lang="ru"><head>
<title>Тестовая страница с пробелами</title>
<meta name="author" content="Иван Петров">
<meta property="article:published_time" content="2026-01-15T10:00:00Z">
<meta name="description" content="Страница для проверки свойств.">
<link rel="canonical" href="https://example.com/canonical">
</head><body><article><h1>Заголовок</h1>%s</article></body></html>""" % body(40))
    big = os.path.join(site, "big.html")
    with open(big, "w", encoding="utf-8") as f:
        parts = ["<h2>Раздел %d</h2>%s" % (i, body(30, i * 30)) for i in range(20)]
        f.write("<html lang='ru'><head><title>Большая страница</title></head><body>%s</body></html>"
                % "".join(parts))

    static_handler = lambda *a, **kw: SimpleHTTPRequestHandler(*a, directory=site, **kw)  # noqa: E731
    static_srv = ThreadingHTTPServer(("127.0.0.1", 0), static_handler)
    threading.Thread(target=static_srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/" % static_srv.server_address[1]

    build_fixtures()
    mock_srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=mock_srv.serve_forever, daemon=True).start()
    mock = "http://127.0.0.1:%d" % mock_srv.server_address[1]

    # ------------------------------------------------ paths, metadata, cache
    work = os.path.join(tmp, "папка с пробелами", "очень длинное имя каталога " + "x" * 40)
    url = base + urllib.parse.quote("тест с пробелами.html")

    rc, out, err = run([url, "--dir", work])
    try:
        m = json.loads(out)
    except Exception:
        m = {}
    check("unicode path: exit 0", rc == 0, err.strip()[:80])
    check("manifest is valid JSON", bool(m), "keys=%d" % len(m))
    check("status ok", m.get("status") == "ok", str(m.get("status")))
    check("manifest carries dir", m.get("dir") == work, str(m.get("dir"))[:40])
    check("files written", all(os.path.isfile((m.get("files") or {}).get(k, "")) for k in ("content", "page", "raw")))
    pg = m.get("page") or {}
    check("page.title", pg.get("title") == "Тестовая страница с пробелами", pg.get("title", ""))
    check("page.author", pg.get("author") == "Иван Петров", pg.get("author", ""))
    check("page.published", pg.get("published", "").startswith("2026-01-15"), pg.get("published", ""))
    check("page.canonical", pg.get("canonical") == "https://example.com/canonical", pg.get("canonical", ""))
    check("page.lang", pg.get("lang") == "ru", pg.get("lang", ""))
    empties = [k for k, v in m.items() if v in ({}, [], "", None)]
    check("empty fields are dropped", not empties and
          all(isinstance(m.get(k), list) and m.get(k)
              for k in ("missing", "improve") if k in m),
          "empties=%s lists=%s" % (empties, [k for k in ("missing", "improve") if k in m]))

    rc2, out2, _ = run([url, "--dir", work])
    m2 = json.loads(out2) if out2.strip().startswith("{") else {}
    check("second call is a cache hit", m2.get("cache") == "hit", str(m2.get("cache")))
    check("cache keeps the same text", (m2.get("content") or {}).get("chars") == (m.get("content") or {}).get("chars"))

    said = subprocess.run(PY + [url, "--dir", work], capture_output=True).stdout
    check("the answer fits the budget", len(said) <= BUDGET_BYTES and said.count(b"\n") <= BUDGET_LINES,
          "%d bytes, %d lines" % (len(said), said.count(b"\n")))
    check("the answer is the text, not JSON", not said.lstrip().startswith(b"{") and b"\r" not in said,
          said[:60].decode("utf-8", "replace"))
    check("the answer names its files", work.encode("utf-8") in said, "")

    big_url = base + "big.html"
    big_dir = os.path.join(tmp, "большая папка")
    rc5, out5, _ = run([big_url, "--dir", big_dir])
    mb = json.loads(out5) if out5.strip().startswith("{") else {}
    check("big page: ok", rc5 == 0 and mb.get("status") == "ok", why(mb))
    check("big page: large flag", bool((mb.get("content") or {}).get("large")), str((mb.get("content") or {}).get("chars")))
    said = subprocess.run(PY + [big_url, "--dir", big_dir], capture_output=True).stdout
    # its 20 sections' headings are the outline where the extractor keeps them (defuddle, readability); trafilatura -
    # CI's only one - drops them, and a text with fewer than two headings has an outline of first words (KNOWN-ISSUES
    # 321): either is an outline whose rows are line numbers
    head_b = said.split("\n── ".encode("utf-8"), 1)[0].split(b"\n")
    at = [i for i, x in enumerate(head_b) if x in (b"outline (line, heading):", b"outline (line, first words):")]
    rows_b = [x.strip() for x in head_b[at[0] + 1:] if x.strip()] if at else []
    check("big page: an outline with line numbers", len(rows_b) >= 3
          and all(x.split()[0].isdigit() or x.startswith("…".encode("utf-8")) for x in rows_b),
          "%s, %d rows" % (head_b[at[0]].decode("utf-8") if at else "no outline", len(rows_b)))
    check("big page: the answer names the next line", b"--from " in said and len(said) <= BUDGET_BYTES,
          "%d bytes" % len(said))

    # ------------------------------------------------ images: download, dedupe, markers
    img_dir = os.path.join(tmp, "картинки")
    rc6, out6, _ = run([mock + "/images.html", "--dir", img_dir, "--refresh"])
    mi = json.loads(out6) if out6.strip().startswith("{") else {}
    entries = mi.get("images") or []
    names = [e["file"] for e in entries]
    check("image page: ok", rc6 == 0 and mi.get("status") == "ok", why(mi))
    check("image page: duplicate dropped, 1x1 dropped", len(entries) == 1, str(names))
    check("image page: file on disk", all(os.path.isfile(os.path.join(img_dir, n.replace("/", os.sep))) for n in names))
    check("image page: dims recorded", (entries[0].get("dims") if entries else "") == "12x12",
          entries[0].get("dims") if entries else "")
    body_md = open(os.path.join(img_dir, "content.md"), encoding="utf-8").read()
    # `[img #1 · 12x12 ... · карандаш] img/01-karandash.png`, the alt in Latin letters
    marker = [ln for ln in body_md.splitlines() if "[img #1 · 12x12" in ln]
    check("image page: marker in the text", bool(marker), marker[0] if marker else "")
    check("image page: marker points at img/, named by its number and alt",
          any("img/01-karandash.png" in x for x in marker), str(marker[:1]))
    check("image page: the downloaded image link is replaced",
          "/pencil.png" not in body_md and "img/01-karandash.png" in body_md,
          [ln for ln in body_md.splitlines() if "pencil" in ln][:1])

    # ------------------------------------------------ pictures: allow (default) vs deny
    allow_dir = os.path.join(tmp, "картинки разрешены")
    rc_a, out_a, _ = run([mock + "/images.html", "--dir", allow_dir, "--refresh"])
    try:
        ma = json.loads(out_a)
    except Exception:
        ma = {}
    check("images allowed by default: files on disk",
          os.path.isdir(os.path.join(allow_dir, "img")), str(os.listdir(allow_dir))[:60])
    allow_md = open(os.path.join(allow_dir, "content.md"), encoding="utf-8").read()
    check("images allowed: marker carries the path", "img/01-karandash.png" in allow_md, "")
    check("images allowed: no deny signal", not (ma.get("signals") or {}).get("images_denied"), "")

    deny_dir = os.path.join(tmp, "картинки запрещены")
    rc_d, out_d, _ = run([mock + "/images.html", "--dir", deny_dir, "--refresh", "--deny-images"])
    try:
        mden = json.loads(out_d)
    except Exception:
        mden = {}
    check("--deny-images: no img folder", not os.path.isdir(os.path.join(deny_dir, "img")),
          str(os.listdir(deny_dir))[:60])
    deny_md = open(os.path.join(deny_dir, "content.md"), encoding="utf-8").read()
    check("--deny-images: the marker says not downloaded and keeps the address, no path",
          "· not downloaded: --deny-images · " in deny_md and "/pencil.png" in deny_md and "img/01-" not in deny_md,
          [ln for ln in deny_md.splitlines() if "pencil" in ln][:1])
    check("--deny-images: signal is set", bool((mden.get("signals") or {}).get("images_denied")), "")
    check("--deny-images: no picture in images[] has a file",
          not any(e.get("file") for e in (mden.get("images") or [])), str(mden.get("images"))[:80])
    check("--deny-images: text is still there", (mden.get("content") or {}).get("chars", 0) > 100,
          str((mden.get("content") or {}).get("chars")))
    # a folder the code before 2026-11-26 wrote has the state after the alt (KNOWN-ISSUES 266): a later read
    # without --deny-images still finds its markers and gives them their files
    old_form = deny_md.replace("· not downloaded: --deny-images · карандаш]", "· карандаш · not downloaded: --deny-images]")
    with open(os.path.join(deny_dir, "content.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(old_form)
    run([mock + "/images.html", "--dir", deny_dir])
    again_md = open(os.path.join(deny_dir, "content.md"), encoding="utf-8").read()
    check("a marker of the older form is rewritten when its picture comes",
          old_form != deny_md and "img/01-karandash.png" in again_md and "not downloaded" not in again_md,
          [ln for ln in again_md.splitlines() if "pencil" in ln or "karandash" in ln][:1])

    # ------------------------------------------------ single file endpoint
    media_dir = os.path.join(tmp, "медиа")
    rc7, out7, _ = run([mock + "/photo.jpg", "--dir", media_dir, "--refresh"])
    mm = json.loads(out7) if out7.strip().startswith("{") else {}
    check("single jpeg: exit 0", rc7 == 0, str(rc7))
    check("single jpeg: status media_only", mm.get("status") == "media_only", str(mm.get("status")))
    check("single jpeg: kind image", (mm.get("content") or {}).get("kind") == "image",
          str((mm.get("content") or {}).get("kind")))
    check("single jpeg: file saved", os.path.isfile((mm.get("files") or {}).get("media", "")),
          os.path.basename((mm.get("files") or {}).get("media", "")))
    check("single jpeg: text is empty", (mm.get("content") or {}).get("chars") == 0)

    # ------------------------------------------------ size limit
    large_dir = os.path.join(tmp, "слишком большой")
    rc8, ml, _ = inproc([mock + "/big.jpg", "--dir", large_dir, "--refresh"],
                        patch={"MEDIA_LIMIT": 1000})
    check("oversized file: status too_large", ml.get("status") == "too_large", str(ml.get("status")))
    check("oversized file: advice offers --download", "--download" in (ml.get("advice") or ""),
          why(ml)[:120])
    check("oversized file: nothing saved", not (ml.get("files") or {}).get("media"))

    # ------------------------------------------------ login: strong, medium, weak
    login_dir = os.path.join(tmp, "логин")
    rc9, out9, _ = run([mock + "/secret", "--dir", login_dir, "--refresh"])
    try:
        mlo = json.loads(out9)
    except Exception:
        mlo = {}
    check("login redirect: status login_required", mlo.get("status") == "login_required", str(mlo.get("status")))
    check("login redirect: advice names the reason", "account" in (mlo.get("advice") or ""),
          why(mlo)[:120])
    login_text = open((mlo.get("files") or {}).get("content") or os.devnull, encoding="utf-8").read()
    check("login redirect: content is still returned", "Sign in" in login_text, "%d chars" % len(login_text))
    check("login redirect: exit 0, the status says it", rc9 == 0, str(rc9))

    weak_dir = os.path.join(tmp, "слабый логин")
    rc10, out10, _ = run([mock + "/weak.html", "--dir", weak_dir, "--refresh"])
    try:
        mw = json.loads(out10)
    except Exception:
        mw = {}
    check("weak login hint: status stays ok", mw.get("status") == "ok", str(mw.get("status")))
    check("weak login hint: signals.login_hint set", bool((mw.get("signals") or {}).get("login_hint")),
          str((mw.get("signals") or {}).get("login_hint"))[:60])
    check("weak login hint: advice is soft", "signing in" in (mw.get("advice") or ""),
          (mw.get("advice") or "")[:60])

    # ------------------------------------------------ google export mapping
    _, _, mod = inproc(["--caps"])
    g = mod.google_export
    check("google: document -> docx",
          g("https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcdE/edit?tab=t.0")
          == "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcdE/export?format=docx")
    check("google: spreadsheets -> xlsx",
          g("https://docs.google.com/spreadsheets/d/abcDEF123456/edit#gid=0")
          == "https://docs.google.com/spreadsheets/d/abcDEF123456/export?format=xlsx")
    check("google: presentation -> pptx",
          g("https://docs.google.com/presentation/d/abcDEF123456/edit")
          == "https://docs.google.com/presentation/d/abcDEF123456/export?format=pptx")
    check("google: non-google url untouched", g("https://example.com/document/d/1/x") == "")
    check("google: folders are not documents", g("https://drive.google.com/drive/folders/abcDEF123456") == "")

    # ------------------------------------------------ docx: footnotes and pictures
    docx_dir = os.path.join(tmp, "документ")
    rc11, out11, _ = run([mock + "/doc.docx", "--dir", docx_dir, "--refresh"])
    try:
        md = json.loads(out11)
    except Exception:
        md = {}
    dtext = open((md.get("files") or {}).get("content") or os.devnull, encoding="utf-8").read()
    check("docx: ok", rc11 == 0 and md.get("status") == "ok", str(md.get("status")))
    check("docx: body text", "Тело документа" in dtext, dtext[:60].replace("\n", " "))
    check("docx: footnote text is read", "footnotes.xml" in dtext, dtext[-80:].replace("\n", " "))
    dimgs = md.get("images") or []
    check("docx: picture extracted to img/", bool(dimgs) and os.path.isfile(
        os.path.join(docx_dir, dimgs[0]["file"].replace("/", os.sep))), str(dimgs[:1]))
    check("docx: picture dims", (dimgs[0].get("dims") if dimgs else "") == "20x10",
          dimgs[0].get("dims") if dimgs else "")
    # the document names no place for it: listed after the text, never invented inside
    after = dtext.find("## Pictures not in the text")
    check("docx: a picture with no place in the text is listed after it",
          after > dtext.find("Тело документа") >= 0 and "img/01-" in dtext[after:] and "img/" not in dtext[:after],
          dtext[after:after + 80].replace("\n", " "))

    # ------------------------------------------------ short machine-readable answers
    api_dir = os.path.join(tmp, "api")
    rc12, out12, _ = run([mock + "/citation", "--dir", api_dir, "--refresh"])
    try:
        mapi = json.loads(out12)
    except Exception:
        mapi = {}
    check("short text/plain answer: status ok", mapi.get("status") == "ok", str(mapi.get("status")))
    check("short text/plain answer: engine server", str((mapi.get("content") or {}).get("engine", "")).startswith("server:"),
          str((mapi.get("content") or {}).get("engine")))

    # ------------------------------------------------ a 404 stays a 404 even with a big frame
    nf_dir = os.path.join(tmp, "404")
    rc_nf, out_nf, _ = run([mock + "/missing-but-pretty.html", "--dir", nf_dir, "--refresh"])
    try:
        mnf = json.loads(out_nf)
    except Exception:
        mnf = {}
    check("a 404 with a long frame is still not_found", mnf.get("status") == "not_found",
          "status=%s chars=%s" % (mnf.get("status"), (mnf.get("content") or {}).get("chars")))
    check("the 404 page's own words are returned",
          os.path.isfile((mnf.get("files") or {}).get("content") or ""))

    # ------------------------------------------------ a wall in the words, not in the status
    wall_dir = os.path.join(tmp, "стена по словам")
    rcw, outw, _ = run([mock + "/mentions-wall.html", "--dir", wall_dir, "--refresh"])
    try:
        mw2 = json.loads(outw)
    except Exception:
        mw2 = {}
    check("prose about walls is not a wall", mw2.get("status") == "ok", str(mw2.get("status")))
    check("prose about walls sets no block signal", not (mw2.get("signals") or {}).get("block_text"),
          str((mw2.get("signals") or {}).get("block_text")))

    ch_dir = os.path.join(tmp, "челлендж")
    rcch, outch, _ = run([mock + "/challenge.html", "--dir", ch_dir, "--refresh"])
    try:
        mch = json.loads(outch)
    except Exception:
        mch = {}
    check("a challenge page served with 200 is blocked", mch.get("status") == "blocked",
          str(mch.get("status")))
    check("blocked page still returns its text", "Verifying you are human" in open(
        (mch.get("files") or {}).get("content") or os.devnull, encoding="utf-8").read(), "")

    # ------------------------------------------------ a read into a folder with a non-ASCII name
    arch_dir = os.path.join(tmp, "архив")
    rcw2, outw2, _ = run([mock + "/secret", "--dir", arch_dir, "--refresh"])
    check("a read into a folder with a non-ASCII name writes its manifest there",
          os.path.isfile(os.path.join(arch_dir, "manifest.json")), "rc=%s" % rcw2)

    # ------------------------------------------------ --download: no limits at all
    dl_dir = os.path.join(tmp, "no limits")
    rc13, mdl, _ = inproc([mock + "/big.jpg", "--dir", dl_dir, "--refresh", "--download"],
                          patch={"MEDIA_LIMIT": 1000})
    check("--download ignores the file limit", mdl.get("status") == "media_only", str(mdl.get("status")))
    check("--download saves the file", os.path.isfile((mdl.get("files") or {}).get("media", "")),
          os.path.basename((mdl.get("files") or {}).get("media", "")))

    img_dl = os.path.join(tmp, "картинки без лимитов")
    rc14, mimg, _ = inproc([mock + "/images.html", "--dir", img_dl, "--refresh", "--download"],
                           patch={"MEDIA_LIMIT": 1000, "PAGE_LIMIT": 10})
    names = [e["file"] for e in (mimg.get("images") or [])]
    check("--download ignores the page image budget", bool(names), str(names))
    check("--download reports nothing cut", not (mimg.get("signals") or {}).get("images_truncated"),
          str((mimg.get("signals") or {}).get("images_truncated")))

    # ------------------------------------------------ text first: pictures are time-boxed
    _, _, mod = inproc(["--caps"])
    t0 = time.time()
    never = "http://10.255.255.1/never-answers.png"
    got = mod.fetch_pictures([(mock + "/heavy.png", ""), (never, "")], mock, os.path.join(tmp, "таймаут"),
                             seconds=1.0, page_private=True)
    took = time.time() - t0
    check("picture phase obeys its deadline", took < 5.0, "%.2fs" % took)
    # a cold runner can miss even a 1 s deadline for the local picture, so the promise tested
    # here is the accounting: every reference comes back, a cut one says why, none is lost
    check("deadline is reported, not hidden",
          len(got) == 2 and str((got.get(never) or {}).get("why") or "").startswith(("no time", "timeout")),
          str({k[-20:]: (v.get("why") or "data") for k, v in got.items()}))

    # ------------------------------------------------ fingerprint rotation
    _, _, mod = inproc(["--caps"])
    rot = mod.impersonations() if hasattr(mod, "impersonations") else ()
    check("rotation has real targets", 1 <= len(rot) <= 4, str(rot))

    class FakeResp:
        def __init__(self, code):
            self.status_code = code
            self.headers = {"content-type": "text/html; charset=utf-8"}
            self.content = b"<html><body><p>ok</p></body></html>"
            self.url = "https://example.com/page"

    seen = []

    def fake_get(url, imp, *a, **k):
        seen.append(imp)
        return FakeResp(403 if len(seen) < 3 else 200)

    mod._cffi_get = fake_get
    if mod.caps()["libs"].get("curl_cffi"):
        out = mod._fetch_once("https://example.com/page")
        check("403 triggers the next fingerprint", out["status"] == 200 and len(seen) == 3,
              "tries=%d rotation=%s" % (len(seen), rot))
        check("rotation stops at the first success", seen[:3] == list(rot[:3]), str(seen))

        seen.clear()

        def all_blocked(url, imp, *a, **k):
            seen.append(imp)
            return FakeResp(403)

        mod._cffi_get = all_blocked
        out = mod._fetch_once("https://example.com/blocked")
        # two fingerprints normally; a third only when both answered a plain 403
        check("rotation is bounded", out["status"] == 403 and len(seen) <= mod.HTTP_ATTEMPTS + 1,
              "tries=%d of %d (cap %d+1)" % (len(seen), len(rot), mod.HTTP_ATTEMPTS))
    else:
        check("curl_cffi not installed: rotation checks skipped", True, "")

    # ------------------------------------------------ the manifest matches its published schema
    schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "references", "manifest-schema.json")
    schema = json.load(open(schema_path, encoding="utf-8"))
    seen_manifests, schema_errors = 0, []
    for root, _dirs, names in os.walk(tmp):
        if "manifest.json" not in names:
            continue
        seen_manifests += 1
        try:
            data = json.load(open(os.path.join(root, "manifest.json"), encoding="utf-8"))
        except Exception as e:                                # noqa: BLE001
            schema_errors.append("%s: unreadable (%s)" % (root, e))
            continue
        schema_errors.extend("%s: %s" % (os.path.basename(root), e)
                             for e in validate(data, schema))
    check("every manifest matches references/manifest-schema.json",
          seen_manifests > 5 and not schema_errors,
          "%d manifests, %d errors%s" % (seen_manifests, len(schema_errors),
                                         (": " + schema_errors[0]) if schema_errors else ""))
    # a PDF's signals.tables, as a read of a long PDF and of a ZIP of PDFs makes it: its page lists
    # are ranges ("28-600", not 573 numbers in every MCP answer), and the schema says so
    tm = load_module()
    tm.tables_reset()
    tm.tables_merge({"pages": [1, 2, 3], "left": list(range(4, 601)), "heavy": [9], "more": True, "tables": 3,
                     "asked": 3, "secs": 10.0, "of": 600})
    tm.tables_merge({"left": [1, 2], "stopped": [1, 2], "of": 2, "error": "the model's process ended"}, name="b.pdf")
    tsig = tm.tables_signal()
    tschema = schema["properties"]["signals"]["properties"]["tables"]
    terrs = validate(tsig, tschema, "$.signals.tables") + [
        e for f in tsig.get("files") or [] for e in validate(f, tschema["properties"]["files"]["items"], "$.files[]")]
    check("signals.tables: page lists as ranges, and the schema says so",
          tsig.get("left") == "4-600" and tsig.get("pages") == "1-3" and tsig["files"][0].get("left") == "1-2"
          and "stopped" not in tsig["files"][0] and not terrs, "%s %s" % (terrs[:2], {k: tsig.get(k) for k in ("left", "pages")}))

    static_srv.shutdown()
    mock_srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d ok, %d failed" % (ok, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
