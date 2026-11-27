"""Regression checks for the 0.4.0 fixes. Offline: local servers, no network, no browser.

    python -X utf8 tests/fixes.py

Each check names the problem it pins down (see KNOWN-ISSUES.md).
"""
import contextlib
import gzip
import io
import importlib.util
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import http.server
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):    # the user's debug log switches stay out
    os.environ.pop(_name, None)

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "readpage.py")
MCP = os.path.join(SKILL, "scripts", "mcp_server.py")

ok = failed = 0
ONLY = sys.argv[1] if len(sys.argv) > 1 else ""


def check(name, good, detail=""):
    global ok, failed
    if ONLY and ONLY not in name:
        return
    if good:
        ok += 1
        print("OK   %-58s %s" % (name, detail))
    else:
        failed += 1
        print("FAIL %-58s %s" % (name, detail))


def inproc(argv, patch=None, env=None):
    """Run readpage.main() in this process; returns (rc, manifest, module)."""
    spec = importlib.util.spec_from_file_location("rp_fix_%d" % time.time_ns(), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old_env = {}
    for k, v in (env or {}).items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v
    saved = {}
    for k, v in (patch or {}).items():
        saved[k] = getattr(mod, k)
        setattr(mod, k, v)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main(list(argv) + ["--json"])
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    try:
        return rc, json.loads(buf.getvalue()), mod
    except Exception:
        return rc, {}, mod


def run(argv, env=None):
    e = dict(os.environ, READ_PAGE_SKIP="browser", **(env or {}))
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT] + argv + ["--json"],
                       capture_output=True, env=e, timeout=120)
    try:
        return json.loads(p.stdout.decode("utf-8", "replace")), p.returncode
    except Exception:
        return {}, p.returncode


class H(http.server.BaseHTTPRequestHandler):
    routes = {}
    log = []
    cookies = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        type(self).log.append(self.path)
        type(self).cookies[self.path] = self.headers.get("Cookie", "")
        r = type(self).routes.get(self.path.split("?")[0])
        if callable(r):
            return r(self)
        if r is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"missing")
            return
        code, headers, body = r
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(routes):
    cls = type("H%d" % time.time_ns(), (H,), {"routes": routes, "log": [], "cookies": {}})
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), cls)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1], cls


def page(text, title="t", extra=""):
    return ("<html><head><meta charset='utf-8'><title>%s</title></head><body>%s%s</body></html>"
            % (title, text, extra)).encode("utf-8")


def para(n=200, word="text"):
    return "<p>" + " ".join([word] * n) + "</p>"


def io_bytes(data):
    import io as _io
    return _io.BytesIO(data)


def tiny_png(color):
    """A valid 4x4 PNG in one colour (no external library needed)."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(color) * 4 for _ in range(4))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(
        b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def main():
    global tmp
    tmp = tempfile.mkdtemp(prefix="read-page-fixes-")
    os.environ["READ_PAGE_CACHE"] = os.path.join(tmp, "cache")
    os.environ["READ_PAGE_SKIP"] = "browser"

    # ------------------------------------------------ one folder per URL, flags in the manifest
    _, _, mod = inproc(["--caps"])
    check("cache: one folder per URL", mod.page_dir("https://x.test/a") == mod.page_dir("https://x.test/a"),
          mod.page_dir("https://x.test/a")[-16:])
    check("cache: mode differs by flag", mod.mode_key(True, False, False) != mod.mode_key(False, False, False), "")

    # ------------------------------------------------ --dir is honoured on a cache hit
    srv, port, _ = serve({"/p": (200, {"Content-Type": "text/html"}, page("<h1>Dir</h1>" + para()))})
    d1, d2 = os.path.join(tmp, "d1"), os.path.join(tmp, "d2")
    m1, _ = run([f"http://127.0.0.1:{port}/p", "--dir", d1])
    m2, _ = run([f"http://127.0.0.1:{port}/p", "--dir", d2])
    check("--dir honoured on a cache hit", m2.get("cache") == "hit" and m2.get("dir") == d2,
          "%s cached=%s" % (m2.get("dir"), m2.get("cache")))
    check("--dir artefacts really exist", os.path.isfile(os.path.join(d2, "content.md")), d2)

    # ------------------------------------------------ privacy: no flag lifts the rule
    blocked = page("<h1>Attention Required!</h1><p>Just a moment...</p>", "Cloudflare")
    srv2, port2, _ = serve({"/": (403, {"Content-Type": "text/html"}, blocked)})
    seen = []
    _, m, mod = inproc([f"http://127.0.0.1:{port2}/", "--allow-external"],
                       patch={"external_read": lambda url, c, refresh=False: (
                           seen.append(url), ("", "rec", None, ""))[1]})
    check("--allow-external does not send a private URL out",
          not seen and m.get("privacy", {}).get("mode") == "sensitive", "sent=%r" % seen)
    seen.clear()
    _, mf, _ = inproc([f"http://127.0.0.1:{port2}/", "--force-external"],
                      patch={"external_read": lambda url, c, refresh=False: (
                          seen.append(url), ("", "rec", None, ""))[1]})
    check("--force-external does not send an internal host either", not seen, "sent=%r" % seen)
    check("the refused flag is recorded",
          (mf.get("privacy") or {}).get("conflict") == ["force_external refused", "internal host"]
          and not (mf.get("privacy") or {}).get("override"),
          str((mf.get("privacy") or {}).get("conflict")))
    check("private refusal is explained", "internal host" in (m.get("privacy", {}).get("why") or ""),
          (m.get("privacy", {}).get("why") or "")[:60])
    check("advice does not repeat the refused flag", "rerun with --allow-external" not in (m.get("advice") or ""),
          (m.get("advice") or "")[:70])

    # ------------------------------------------------ host_is_private covers the browser's forms
    cases = {
        "http://[::1]:8080/": True, "http://[fd00::1]/": True, "http://[fe80::1]/": True,
        "http://[::ffff:127.0.0.1]/": True, "http://2130706433/": True, "http://0x7f000001/": True,
        "http://0177.0.0.1/": True, "http://100.64.0.1/": True, "http://localhost:1/": True,
        "http://localhost./": True, "http://metadata.google.internal/": True,
        "https://x.test/reset/abc123def456ghi789/session": False,      # a path is not a host
        "https://example.com/article": False, "https://example.com/a/b": False,
    }
    wrong = [u for u, want in cases.items() if bool(mod.host_is_private(u)) != want]
    check("host_is_private: 14 forms", not wrong, ", ".join(wrong[:3]))

    # ------------------------------------------------ a public page may not fetch a private image
    secret = b"\x89PNG\r\n\x1a\nPRIVATE"
    srv3, port3, _ = serve({"/secret.png": (200, {"Content-Type": "image/png"}, secret)})
    body = page("<h1>A</h1>" + para(), extra='<img src="http://127.0.0.1:%d/secret.png">' % port3)
    fake = {"engine": "fake", "status": 200, "ct": "text/html; charset=utf-8", "body": body,
            "final": "https://example.com/article", "error": "", "ms": 1}
    _, m, _ = inproc(["https://example.com/article"],
                     patch={"fetch_http": lambda url, download=False, workdir=None, validators=None: dict(fake)})
    d = m.get("dir") or ""
    imgs = os.listdir(os.path.join(d, "img")) if os.path.isdir(os.path.join(d, "img")) else []
    # the text still names it (a marker with the reason), no file is taken
    check("public page: private image is not fetched",
          not imgs and not any(e.get("file") for e in m.get("images") or [])
          and all("refused" in str(e.get("why")) for e in m.get("images") or []), str(imgs or m.get("images")))
    check("public page: the skip is reported",
          (m.get("signals") or {}).get("images_private_skipped") == 1,
          str((m.get("signals") or {}).get("images_private_skipped")))

    # ------------------------------------------------ a private page may use its own pictures
    local = page("<h1>A</h1>" + para(), extra='<img src="/secret.png">')
    srv4, port4, _ = serve({"/p": (200, {"Content-Type": "text/html"}, local),
                            "/secret.png": (200, {"Content-Type": "image/png"}, secret)})
    m, _ = run([f"http://127.0.0.1:{port4}/p"])
    check("private page: local pictures still work", bool(m.get("images")),
          str([e["file"] for e in (m.get("images") or [])]))

    # ------------------------------------------------ redirect into a private address is refused
    srv5, port5, _ = serve({"/r": lambda h: (h.send_response(302),
                                             h.send_header("Location", "http://10.0.0.1/secret"),
                                             h.end_headers())})
    _, _, mod = inproc(["--caps"])
    check("redirect: public -> private is refused",
          bool(mod.hop_refused("https://example.com/a", "http://10.0.0.1/secret")), "")
    check("redirect: private -> private stays allowed",
          not mod.hop_refused("http://127.0.0.1/a", "http://127.0.0.1:9/b"), "")
    check("redirect: public -> public is allowed",
          not mod.hop_refused("https://example.com/a", "https://example.com/b"), "")
    check("redirect: file:// is refused from any page, private ones too",
          bool(mod.hop_refused("http://127.0.0.1/a", "file:///etc/passwd"))
          and bool(mod.hop_refused("https://example.com/a", "ftp://example.com/x")), "")

    # ------------------------------------------------ statuses: four false ones are gone
    fixtures = {
        "short": page("<h1>Status</h1><p>All systems operational. Latency 42 ms.</p>"),
        "prose-not-found": page("<h1>Debugging HTTP</h1>" + para(60, "A 404 means the page was not found.")),
        "prose-denied": page("<h1>Error codes</h1>" + para(60, "A firewall may answer access denied.")),
        "newsletter": page("<h1>Newsletter</h1>" + para(90),
                           extra='<form><input type="password" name="p"><button>Subscribe</button></form>'),
        "challenge": page("<h1>Just a moment...</h1><p>Checking your browser.</p>", "Attention Required!"),
        "binary": bytes(range(256)) * 40,
    }
    srv6, port6, _ = serve({"/short": (200, {"Content-Type": "text/html"}, fixtures["short"]),
                            "/prose-not-found": (200, {"Content-Type": "text/html"}, fixtures["prose-not-found"]),
                            "/prose-denied": (200, {"Content-Type": "text/html"}, fixtures["prose-denied"]),
                            "/newsletter": (200, {"Content-Type": "text/html"}, fixtures["newsletter"]),
                            "/challenge": (200, {"Content-Type": "text/html"}, fixtures["challenge"]),
                            "/binary": (200, {"Content-Type": "application/octet-stream"}, fixtures["binary"]),
                            "/404": (404, {"Content-Type": "text/html"}, page("<h1>Not here</h1>"))})
    want = {"short": "ok", "prose-not-found": "ok", "prose-denied": "ok", "newsletter": "ok",
            "challenge": "blocked", "binary": "empty", "/404": "not_found"}
    for path, expected in want.items():
        m, _ = run([f"http://127.0.0.1:{port6}/{path.lstrip('/')}"])
        check("status: %s -> %s" % (path.lstrip("/"), expected), m.get("status") == expected,
              str(m.get("status")))
    m, _ = run([f"http://127.0.0.1:{port6}/binary"])
    check("binary body carries a signal", (m.get("signals") or {}).get("binary") is True, "")

    # ------------------------------------------------ an error page at *.png is not a file
    srv7, port7, _ = serve({"/x.png": (404, {"Content-Type": "text/plain"}, b"no such image")})
    m, _ = run([f"http://127.0.0.1:{port7}/x.png"])
    check("404 at *.png is not media_only", m.get("status") == "not_found", str(m.get("status")))

    # ------------------------------------------------ gzip is decoded on the plain-curl path
    gz = gzip.compress(page("<h1>Compressed</h1><p>MARKER-WORD " + " ".join(["w"] * 200) + "</p>"))
    srv8, port8, _ = serve({"/gz": (200, {"Content-Type": "text/html; charset=utf-8",
                                          "Content-Encoding": "gzip"}, gz)})
    m, _ = run([f"http://127.0.0.1:{port8}/gz"])
    text = open((m.get("files") or {}).get("content") or os.devnull, encoding="utf-8", errors="replace").read()
    check("gzip response is text, not mojibake", "MARKER-WORD" in text, text[:40].replace("\n", " "))

    # ------------------------------------------------ <base href> decides picture URLs
    asset = b"\x89PNG\r\n\x1a\nASSET"
    srv9, port9, _ = serve({
        "/p/page.html": (200, {"Content-Type": "text/html"},
                         page("<h1>Doc</h1>" + para(), extra='<img src="logo.png">').replace(
                             b"<head>", b'<head><base href="/assets/">')),
        "/assets/logo.png": (200, {"Content-Type": "image/png"}, asset),
    })
    m, _ = run([f"http://127.0.0.1:{port9}/p/page.html"])
    check("<base href> resolves the picture", bool(m.get("images")),
          str([e["url"] for e in (m.get("images") or [])]))

    # ------------------------------------------------ two pages, one folder: no overwrite
    shared = os.path.join(tmp, "shared")
    srv10, port10, _ = serve({"/logo.png": (200, {"Content-Type": "image/png"}, b"\x89PNG\r\n\x1a\nAAAA"),
                              "/a": (200, {"Content-Type": "text/html"},
                                     page("<h1>A</h1>" + para(), extra='<img src="/logo.png">'))})
    srv11, port11, _ = serve({"/logo.png": (200, {"Content-Type": "image/png"}, b"\x89PNG\r\n\x1a\nBBBB"),
                              "/b": (200, {"Content-Type": "text/html"},
                                     page("<h1>B</h1>" + para(), extra='<img src="/logo.png">'))})
    run([f"http://127.0.0.1:{port10}/a", "--dir", shared])
    run([f"http://127.0.0.1:{port11}/b", "--dir", shared])
    files = sorted(os.listdir(os.path.join(shared, "img")))
    check("second page does not overwrite a picture", len(files) == 2, str(files))

    # ------------------------------------------------ --refresh keeps a user's own raw.txt
    userdir = os.path.join(tmp, "userdir")
    os.makedirs(userdir, exist_ok=True)
    open(os.path.join(userdir, "raw.txt"), "w").write("my notes")
    run([f"http://127.0.0.1:{port}/p", "--dir", userdir, "--refresh"])
    check("--refresh keeps a user's raw.* file", os.path.exists(os.path.join(userdir, "raw.txt")),
          str(sorted(os.listdir(userdir))))

    # ------------------------------------------------ one folder per URL, pictures topped up
    _, _, mod = inproc(["--caps"])
    pict_page = page("<h1>Pics</h1>" + para(),
                     extra='<img src="/one.png"><img src="/one.png"><img src="/two.png">')
    srv15, port15, log15 = serve({"/pics": (200, {"Content-Type": "text/html"}, pict_page),
                                  "/one.png": (200, {"Content-Type": "image/png"}, b"\x89PNG\r\n\x1a\nONE" + b"1" * 40),
                                  "/two.png": (200, {"Content-Type": "image/png"}, b"\x89PNG\r\n\x1a\nTWO" + b"2" * 40)})
    u15 = f"http://127.0.0.1:{port15}/pics"
    m_deny, _ = run([u15, "--deny-images", "--refresh"])
    d_deny = m_deny.get("dir")
    pages_after_deny = sum(1 for x in log15.log if x.startswith("/pics"))
    m_allow, _ = run([u15])
    pages_after_allow = sum(1 for x in log15.log if x.startswith("/pics"))
    check("deny then allow: one folder", m_allow.get("dir") == d_deny, str(m_allow.get("dir")))
    check("deny then allow: pictures appear", bool(m_allow.get("images")),
          str([e["file"] for e in (m_allow.get("images") or [])]))
    check("deny then allow: the page is not fetched again",
          pages_after_allow == pages_after_deny, "%d -> %d" % (pages_after_deny, pages_after_allow))
    check("deny then allow: identical pictures are one file",
          len({e["file"] for e in (m_allow.get("images") or [])}) == len(m_allow.get("images") or []),
          str([e["file"] for e in (m_allow.get("images") or [])]))

    # a second identical run must not add -2 copies of the same picture
    before = sorted(os.listdir(os.path.join(d_deny, "img")))
    run([u15, "--refresh"], env={"READ_PAGE_CACHE": os.environ["READ_PAGE_CACHE"]})
    after = sorted(os.listdir(os.path.join(d_deny, "img")))
    check("re-run keeps the same picture names", before == after, "%s vs %s" % (before, after))

    # ------------------------------------------------ --download has no size cap and stays off-heap
    huge = b"\x89PNG\r\n\x1a\n" + b"\0" * (120 * 1024 * 1024)
    srv16, port16, _ = serve({"/huge.png": (200, {"Content-Type": "image/png"}, huge)})
    try:
        import psutil
    except ImportError:
        psutil = None      # pip install psutil for the memory part of this check
    env16 = dict(os.environ, READ_PAGE_CACHE=os.path.join(tmp, "dl"), READ_PAGE_SKIP="browser")
    of = tempfile.TemporaryFile()
    p16 = subprocess.Popen([sys.executable, "-X", "utf8", SCRIPT, f"http://127.0.0.1:{port16}/huge.png",
                            "--download", "--json"], stdout=of, stderr=subprocess.DEVNULL, env=env16)
    peak = 0
    proc = psutil.Process(p16.pid) if psutil else None
    while p16.poll() is None:
        if proc is not None:
            try:
                peak = max(peak, proc.memory_info().rss)
            except psutil.Error:
                proc = None
        time.sleep(0.01)
    of.seek(0)
    m16 = json.loads(of.read().decode("utf-8", "replace"))
    of.close()
    check("--download takes a file over the 100 MB limit", m16.get("status") == "media_only",
          str(m16.get("status")))
    check("--download does not hold the file in memory", peak < 200 * 1024 * 1024,
          "peak %.0f MB" % (peak / 1048576))
    saved = (m16.get("files") or {}).get("media")
    check("--download writes the whole file", bool(saved) and os.path.getsize(saved) == len(huge),
          "%s bytes" % (os.path.getsize(saved) if saved else 0))
    shutil.rmtree(os.path.join(tmp, "dl"), ignore_errors=True)

    # ------------------------------------------------ a body that arrived before a timeout is kept
    def stall_after(h):
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.end_headers()
        h.wfile.write(page("<h1>Half</h1>" + para(300)).replace(b"</body>", b""))
        h.wfile.flush()
        time.sleep(6)

    srv19, port19, _ = serve({"/half": stall_after})
    _, m19, _ = inproc([f"http://127.0.0.1:{port19}/half"],
                       patch={"HTTP_LOW_SPEED": (1024, 2), "BROWSER_TRIES": 0})
    check("a partial body is kept, not thrown away",
          (m19.get("content") or {}).get("chars", 0) > 100 and (m19.get("signals") or {}).get("partial"),
          "%s %s chars" % ((m19.get("signals") or {}).get("partial"),
                           (m19.get("content") or {}).get("chars")))

    # ------------------------------------------------ a cookie set by one hop is sent to the next
    def start_handler(h):
        h.send_response(302)
        h.send_header("Location", "/final")
        h.send_header("Set-Cookie", "sid=abc123; Path=/")
        h.end_headers()

    def final_handler(h):
        if "sid=abc123" in (h.headers.get("Cookie") or ""):
            body = page("<h1>Session</h1>" + para())
            h.send_response(200)
            h.send_header("Content-Type", "text/html; charset=utf-8")
            h.send_header("Content-Length", str(len(body)))
            h.end_headers()
            h.wfile.write(body)
        else:
            h.send_response(403)
            h.send_header("Content-Length", "0")
            h.end_headers()

    srv18, port18, _ = serve({"/start": start_handler, "/final": final_handler})
    m18, _ = run([f"http://127.0.0.1:{port18}/start"])
    check("a cookie from a redirect is kept for the run", m18.get("status") == "ok",
          "%s %d chars" % (m18.get("status"), (m18.get("content") or {}).get("chars", 0)))

    # ------------------------------------------------ per-picture revalidation (no bulk re-download)
    st2 = {"page": 0, "img": 0, "img304": 0}
    pic_page = page("<h1>Pics</h1>" + para(), extra='<img src="/p1.png"><img src="/p2.png">')

    def p1(h):
        st2["img"] += 1
        if (h.headers.get("If-None-Match") or "") == '"i1"':
            st2["img304"] += 1
            h.send_response(304); h.send_header("ETag", '"i1"'); h.end_headers(); return
        b = b"\x89PNG\r\n\x1a\nP1" + b"1" * 40
        h.send_response(200); h.send_header("Content-Type", "image/png")
        h.send_header("ETag", '"i1"'); h.send_header("Content-Length", str(len(b)))
        h.end_headers(); h.wfile.write(b)

    def p2(h):
        st2["img"] += 1
        b = b"\x89PNG\r\n\x1a\nP2" + b"2" * 40
        h.send_response(200); h.send_header("Content-Type", "image/png")
        h.send_header("Content-Length", str(len(b)))
        h.end_headers(); h.wfile.write(b)

    def pg(h):
        st2["page"] += 1
        h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(pic_page)))
        h.end_headers(); h.wfile.write(pic_page)

    srv20, port20, _ = serve({"/pg": pg, "/p1.png": p1, "/p2.png": p2})
    u20 = f"http://127.0.0.1:{port20}/pg"
    m20a, _ = run([u20, "--refresh"])
    imgs_a = sum(1 for e in (m20a.get("images") or []) if e.get("etag"))
    m20b, _ = run([u20, "--refresh"])
    check("pictures keep their validators", imgs_a == 1, "%d of 1 with an ETag" % imgs_a)
    check("one unchanged picture is not downloaded again", st2["img304"] == 1,
          "img requests=%d 304=%d" % (st2["img"], st2["img304"]))
    check("the revalidated picture is still listed",
          len(m20b.get("images") or []) == 2 and any(e.get("revalidated") for e in m20b.get("images") or []),
          str([e.get("revalidated") for e in (m20b.get("images") or [])]))

    # ------------------------------------------------ --refresh prunes pictures the page no longer has
    def pgone(h):
        html2 = page("<h1>Pics</h1>" + para())
        h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(html2)))
        h.end_headers(); h.wfile.write(html2)

    gone_state = {"gone": False}
    def pg2(h):
        if gone_state["gone"]:
            return pgone(h)
        h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(pic_page)))
        h.end_headers(); h.wfile.write(pic_page)
    srv21, port21, _ = serve({"/pg": pg2, "/p1.png": p1, "/p2.png": p2})
    u21 = f"http://127.0.0.1:{port21}/pg"
    m21a, _ = run([u21, "--refresh"])
    gone_state["gone"] = True
    m21b, _ = run([u21, "--refresh"])
    d21 = m21b.get("dir") or ""
    left = sorted(os.listdir(os.path.join(d21, "img"))) if os.path.isdir(os.path.join(d21, "img")) else []
    check("--refresh removes pictures the page dropped", left == [], str(left))
    check("--refresh keeps the text", (m21b.get("content") or {}).get("chars", 0) > 100, "")

    # ------------------------------------------------ status_reason explains every status
    m22, _ = run([f"http://127.0.0.1:{port20}/pg"])
    check("status_reason is present", bool((m22.get("signals") or {}).get("status_reason")),
          str((m22.get("signals") or {}).get("status_reason"))[:60])

    # ------------------------------------------------ --refresh asks the server, not the disk
    etag_page = page("<h1>ETag</h1>" + para())
    state = {"hits": 0, "not_modified": 0}

    def etag_handler(h):
        state["hits"] += 1
        if (h.headers.get("If-None-Match") or "") == '"v1"':
            state["not_modified"] += 1
            h.send_response(304)
            h.send_header("ETag", '"v1"')
            h.end_headers()
            return
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("ETag", '"v1"')
        h.send_header("Content-Length", str(len(etag_page)))
        h.end_headers()
        h.wfile.write(etag_page)

    srv17, port17, _ = serve({"/etag": etag_handler})
    u17 = f"http://127.0.0.1:{port17}/etag"
    m_first, _ = run([u17, "--refresh"])
    m_second, _ = run([u17, "--refresh"])
    check("--refresh stores the validator", bool((m_first.get("url") or {}).get("etag")), "")
    check("--refresh revalidates instead of re-downloading", m_second.get("cache") == "revalidated",
          str(m_second.get("cache")))
    check("--refresh did not lose the text", (m_second.get("content") or {}).get("chars", 0) > 100,
          str((m_second.get("content") or {}).get("chars")))
    check("the server answered 304 once", state["not_modified"] == 1, str(state))

    # ------------------------------------------------ a zip bomb is refused before reading
    import zipfile
    bomb = os.path.join(tmp, "bomb.docx")
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("word/document.xml", "<w:t>hello</w:t>")
        z.writestr("word/media/big.png", b"\x89PNG\r\n\x1a\n" + b"\0" * (120 * 1024 * 1024))
    _, _, mod = inproc(["--caps"])
    out = mod.zip_images(bomb, os.path.join(tmp, "bombout"))
    check("zip bomb: entry skipped by declared size", out == [], str(out))

    # ------------------------------------------------ size caps
    check("--download has no size cap", mod.download_limit(True) is None, "")
    check("without --download the cap is MAX_DOWNLOAD",
          mod.download_limit(False) == mod.MAX_DOWNLOAD, mod.human_bytes(mod.MAX_DOWNLOAD))
    small, tiny_path, tiny_size, _head = mod.spool_to_file([b"x" * 100], tmp)
    check("a small body stays in memory", small == b"x" * 100 and tiny_size == 100 and not tiny_path,
          "%d bytes" % tiny_size)
    _b, big_path, big_size, head = mod.spool_to_file([b"y" * 100], tmp, keep_in_mem=10)
    check("a big body is spooled to disk", bool(big_path) and os.path.isfile(big_path)
          and big_size == 100 and head == b"y" * 100, "%s" % (big_path and "path"))
    if big_path:
        os.unlink(big_path)

    srv12, port12, _ = serve({"/big": (200, {"Content-Type": "text/html"}, page("<h1>Big</h1>" + para(400)))})
    _, m, _ = inproc([f"http://127.0.0.1:{port12}/big"], patch={"MAX_PAGE_BYTES": 200})
    check("page over MAX_PAGE_BYTES is too_large", m.get("status") == "too_large", str(m.get("status")))
    check("the limit message is readable", "text parsing stops" in ((m.get("signals") or {}).get("limit") or ""),
          ((m.get("signals") or {}).get("limit") or "")[:60])

    # ------------------------------------------------ the deadline actually bounds a run
    def trickle(h):
        h.send_response(200)
        h.send_header("Content-Type", "text/html")
        h.end_headers()
        for _ in range(60):
            try:
                h.wfile.write(b" ")
                h.wfile.flush()
            except Exception:
                return
            time.sleep(0.5)
    srv13, port13, _ = serve({"/t": trickle})
    t0 = time.time()
    _, m, _ = inproc([f"http://127.0.0.1:{port13}/t"],
                     patch={"HTTP_STEP_SECONDS": 3, "BROWSER_TIMEOUT_MS": 1000, "BROWSER_TRIES": 1})
    took = time.time() - t0
    # there is no whole-run stopwatch: the HTTP step has its own bound
    check("per-attempt timeouts bound a slow page", took < 15,
          "%.1fs status=%s" % (took, m.get("status")))

    # ------------------------------------------------ http(s), or a file on this machine
    m, rc = run(["file:///C:/no/such/dir/win.ini"])
    check("a file:// address of no file is a wrong call: exit 2, no answer",
          rc == 2 and not m, "rc=%d" % rc)
    m, rc = run(["ftp://example.com/a.txt"])
    check("another scheme is a wrong call: exit 2", rc == 2 and not m, "rc=%d" % rc)

    # ------------------------------------------------ MCP: the engine's limits, not copies
    spec = importlib.util.spec_from_file_location("mcpfix", MCP)
    mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcp)
    check("MCP and the CLI share one answer contract", not hasattr(mcp, "LIMIT")
          and os.path.samefile(mcp.answer.__file__, mod.answer.__file__), os.path.basename(mcp.answer.__file__))
    res = mcp.tool_read({"dir": tmp, "file": "nope.md"})
    check("MCP read refuses a folder this skill did not write", res.get("isError") is True,
          (res.get("content") or [{}])[0].get("text", "")[:60])
    res = mcp.tool_read({"dir": d2, "file": "nope.md"})
    check("MCP read reports a missing file", res.get("isError") is True, "")
    open(os.path.join(d2, "note.md"), "w", encoding="utf-8").write("hello")
    with open(os.path.join(d2, "minified.html"), "w", encoding="utf-8") as fh:
        fh.write("<p>" + "x" * 500000 + "</p>")       # a raw file is not split into lines
    res = mcp.tool_read({"dir": d2, "file": "minified.html"})
    said = (res.get("content") or [{}])[0].get("text", "")
    check("MCP read: a 500 000-character line stays inside one answer",
          len(said.encode("utf-8")) <= mod.answer.BUDGET_BYTES and "longer than one answer" in said,
          "%d bytes" % len(said.encode("utf-8")))

    pict = page("<h1>Pic</h1>" + para(), extra='<img src="/one.png">')
    srv14, port14, _ = serve({"/p": (200, {"Content-Type": "text/html"}, pict),
                              "/one.png": (200, {"Content-Type": "image/png"}, b"\x89PNG\r\n\x1a\n" + b"\0" * 30)})
    res = mcp.tool_read_url({"url": f"http://127.0.0.1:{port14}/p", "deny_images": True})
    said = "".join(b.get("text", "") for b in res.get("content") or [] if b.get("type") == "text")
    folder = next((ln[len("files: "):ln.rindex(" (")] for ln in said.split("\n") if ln.startswith("files: ")), "")
    try:
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as fh:
            sc = json.load(fh)          # the manifest is the folder's file: no structuredContent (KNOWN-ISSUES 275)
    except (OSError, ValueError):
        sc = {}
    # the picture is named (a marker that says not downloaded), nothing is fetched or attached
    check("MCP deny_images=true works",
          not any(e.get("file") for e in sc.get("images") or []) and not any(
              b.get("type") == "image" for b in res.get("content") or [])
          and (sc.get("signals") or {}).get("images_denied") == 1 and "not downloaded" in said,
          str(len(sc.get("images") or [])))

    # unknown argument through the real protocol
    p = subprocess.run([sys.executable, "-X", "utf8", MCP], input=json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "read", "arguments": {"dir": d2, "bogus": 1}}}) + "\n",
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    out = json.loads(p.stdout.splitlines()[0])
    said = (((out.get("result") or {}).get("content") or [{}])[0].get("text") or "")
    check("MCP leaves an unknown argument out and names it; the call is answered",
          not (out.get("result") or {}).get("isError") and "ignored: bogus (no such parameter)" in said,
          said.split("\n")[0][:90])
    p = subprocess.run([sys.executable, "-X", "utf8", MCP], input=json.dumps(
        [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]) + "\n", capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    out = json.loads(p.stdout.splitlines()[0])
    check("MCP answers a batch instead of dying", (out.get("error") or {}).get("code") == -32600, "")
    p = subprocess.run([sys.executable, "-X", "utf8", MCP], input=json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "read", "arguments": {"dir": d2, "file": "note.md", "from": 99999}}}) + "\n",
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    out = json.loads(p.stdout.splitlines()[0])
    said = "".join(b.get("text", "") for b in (out.get("result") or {}).get("content") or [])
    check("MCP from past the end says so, no next", "past the end" in said and "── next:" not in said
          and "structuredContent" not in (out.get("result") or {}), said.split("\n")[-2][:80])

    # ------------------------------------------------ a wall is asked again, and says the same
    m1, _ = run([f"http://127.0.0.1:{port6}/challenge"])
    m2, _ = run([f"http://127.0.0.1:{port6}/challenge"])
    check("a wall is read again, not served from the cache, and keeps its advice",
          m2.get("cache") != "hit" and bool(m2.get("advice")) and m2.get("advice") == m1.get("advice"),
          "%s advice=%r" % (m2.get("cache"), (m2.get("advice") or "")[:30]))

    # ------------------------------------------------ cookies: store, domain, merge, images
    def _set_cookie(h, extra=""):
        body = page("<h1>Cookie</h1>" + para()).decode()
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Set-Cookie", "sid=abc; Path=/" + extra)
        h.send_header("Content-Length", str(len(body.encode())))
        h.end_headers()
        h.wfile.write(body.encode())

    png = b"\x89PNG\r\n\x1a\nCOOKIE"
    srv12, port12, cls12 = serve({
        "/set": _set_cookie,
        "/who": (200, {"Content-Type": "text/html"}, page("<h1>Who</h1>" + para())),
        "/imgpage": (200, {"Content-Type": "text/html"},
                     page("<h1>Pics</h1>" + para(), extra='<img src="/i.png">')),
        "/i.png": (200, {"Content-Type": "image/png"}, png),
    })
    base12 = f"http://127.0.0.1:{port12}"
    run([base12 + "/set"])
    m_who, _ = run([base12 + "/who"])
    check("cookie: set by one run, sent by the next", "sid=abc" in cls12.cookies.get("/who", ""),
          cls12.cookies.get("/who", ""))
    check("cookie: the manifest reports the jar", bool((m_who.get("signals") or {}).get("cookies")),
          (m_who.get("signals") or {}).get("cookies"))
    run([base12 + "/imgpage"])
    check("cookie: a hotlink-protected picture gets the jar",
          "sid=abc" in cls12.cookies.get("/i.png", ""), cls12.cookies.get("/i.png", ""))
    m_clear, _ = run([base12 + "/who", "--clear-cookies", "--refresh"])
    check("--clear-cookies forgets the site", "sid" not in cls12.cookies.get("/who", ""),
          cls12.cookies.get("/who", ""))

    # a stale session must not be reported as the site's wall
    srv13, port13, _ = serve({
        "/wall": (200, {"Content-Type": "text/html"},
                  page("<h1>Just a moment...</h1>Checking your browser.", "Attention Required")),
    })
    _, _, mod13 = inproc(["--caps"])
    u13 = f"http://127.0.0.1:{port13}/wall"
    mod13.save_cookies(u13, {"sid": {"v": "old", "d": "", "e": 0, "h": "127.0.0.1"}})
    m_wall, _ = run([u13, "--refresh"])
    check("a wall with a stale jar names --clear-cookies",
          m_wall.get("status") == "blocked" and "--clear-cookies" in (m_wall.get("advice") or ""),
          "%s %r" % (m_wall.get("status"), (m_wall.get("advice") or "")[-40:]))

    # ... and a wall's own cookie is not a stale session. A challenge sets one with its first
    # answer and the same read sends it back: the advice then named --clear-cookies on 9 of 11
    # walled reads in a measured run, and agents spent a call on it (2026-11-19).
    # Not on the retry either: a read that ends at a wall does not keep the cookies it got there.
    def _wall_cookie(h):
        h.send_response(302)
        h.send_header("Set-Cookie", "dd=fresh; Path=/")
        h.send_header("Location", "/wall-b")
        h.send_header("Content-Length", "0")
        h.end_headers()

    srv13b, port13b, cls13b = serve({
        "/wall-a": _wall_cookie,
        "/wall-b": (200, {"Content-Type": "text/html"},
                    page("<h1>Just a moment...</h1>Checking your browser.", "Attention Required")),
    })
    u13b = f"http://127.0.0.1:{port13b}/wall-a"
    mod13.clear_cookies(u13b)
    m_w1, _ = run([u13b, "--refresh"])
    sent_b = cls13b.cookies.get("/wall-b", "")
    kept_b = sorted(mod13.load_cookies(u13b))
    m_w2, _ = run([u13b, "--refresh"])
    check("a wall's own cookie is not a stale session: no --clear-cookies, now or on the retry",
          m_w1.get("status") == "blocked" and "dd=fresh" in sent_b and not kept_b
          and "--clear-cookies" not in (m_w1.get("advice") or "")
          and "--clear-cookies" not in (m_w2.get("advice") or ""),
          "%s sent %r kept %s; %r | %r" % (m_w1.get("status"), sent_b, kept_b, (m_w1.get("advice") or "")[-50:],
                                           (m_w2.get("advice") or "")[-50:]))
    mod13.save_cookies(u13b, {"sid": {"v": "old", "d": "", "e": 0, "h": "127.0.0.1"}})
    m_w3, _ = run([u13b, "--refresh"])
    check("... and the session that was there before the wall is kept, and named",
          "--clear-cookies" in (m_w3.get("advice") or "") and sorted(mod13.load_cookies(u13b)) == ["sid"],
          "%r jar %s" % ((m_w3.get("advice") or "")[-40:], sorted(mod13.load_cookies(u13b))))
    mod13.clear_cookies(u13b)

    # ... and kept as it was, not just by its name: a wall that re-sets the session's own cookie
    # (Cloudflare's __cf_bm comes with every answer) or expires it left the jar with the wall's
    # value or none (sid=good became sid=anon)
    def _wall_redirect(*cookies):
        def answer(h):
            h.send_response(302)
            for c in cookies:
                h.send_header("Set-Cookie", c)
            h.send_header("Location", "/wall-b")
            h.send_header("Content-Length", "0")
            h.end_headers()
        return answer

    srv13c, port13c, _ = serve({
        "/wall-reset": _wall_redirect("sid=anon; Path=/", "chl=1; Path=/"),
        "/wall-expire": _wall_redirect("sid=gone; Path=/; Max-Age=0"),
        "/wall-b": (200, {"Content-Type": "text/html"},
                    page("<h1>Just a moment...</h1>Checking your browser.", "Attention Required")),
    })
    for path, how in (("/wall-reset", "re-sets"), ("/wall-expire", "expires")):
        u13c = f"http://127.0.0.1:{port13c}{path}"
        mod13.clear_cookies(u13c)
        mod13.save_cookies(u13c, {"sid": {"v": "good", "d": "", "e": 0, "h": "127.0.0.1"},
                                  "pref": {"v": "1", "d": "", "e": 0, "h": "127.0.0.1"}})
        m_w4, _ = run([u13c, "--refresh"])
        jar13 = {k: e["v"] for k, e in mod13.load_cookies(u13c).items()}
        check("a wall that %s the session's own cookie leaves the session as it was, and keeps none of its own" % how,
              m_w4.get("status") == "blocked" and jar13 == {"sid": "good", "pref": "1"},
              "%s jar %s" % (m_w4.get("status"), jar13))
        mod13.clear_cookies(u13c)
    srv13c.shutdown()

    # the rules themselves: a Domain cookie goes to subdomains, a host cookie does not go up
    _, _, mod14 = inproc(["--caps"])
    check("cookie: Domain matches a subdomain", mod14._domain_ok("app.example.com", "example.com"), "")
    check("cookie: a subdomain cookie stays there",
          not mod14._domain_ok("example.com", "accounts.example.com"), "")
    check("cookie: example.com is not matched by example.com.evil.test",
          not mod14._domain_ok("example.com.evil.test", "example.com"), "")

    # two runs on one host must not overwrite each other's cookies
    u14 = "http://127.0.0.1:1/a"
    mod14.save_cookies(u14, {"a": {"v": "1", "d": "", "e": 0, "h": "127.0.0.1"}})
    mod14.save_cookies(u14, {"b": {"v": "2", "d": "", "e": 0, "h": "127.0.0.1"}})
    both = mod14.load_cookies(u14)
    check("cookie: a second save merges instead of replacing", {"a", "b"} <= set(both), sorted(both))

    # a jar stored by 0.4.1 (a flat name -> value map) is still readable
    js14, _ = mod14.cookie_paths(u14)
    with open(js14, "w", encoding="utf-8") as fh:
        fh.write('{"sid": "legacy"}')
    old = mod14.load_cookies(u14)
    check("cookie: the 0.4.1 jar shape still loads", old.get("sid", {}).get("v") == "legacy", old.get("sid"))

    # an expired cookie is neither sent nor kept
    mod14.save_cookies(u14, {"gone": {"v": "x", "d": "", "e": int(time.time()) - 60, "h": "127.0.0.1"}})
    check("cookie: an expired cookie is dropped", "gone" not in mod14.load_cookies(u14), "")

    # ------------------------------------------------ meta refresh, Content-Disposition, cookie scope
    def _stub(h):
        body = page("<p>This page has moved</p>",
                    extra='<meta http-equiv="refresh" content="0; url=/real">').decode()
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(body.encode())))
        h.end_headers()
        h.wfile.write(body.encode())

    def _media(h):
        body = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 400
        h.send_response(200)
        h.send_header("Content-Type", "audio/mpeg")
        h.send_header("Content-Disposition", 'attachment; filename="song-2026.mp3"')
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    def _path_cookie(h):
        body = page("<h1>C</h1>" + para()).decode()
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Set-Cookie", "area=app; Path=/app")
        h.send_header("Set-Cookie", "sec=1; Path=/; Secure")
        h.send_header("Content-Length", str(len(body.encode())))
        h.end_headers()
        h.wfile.write(body.encode())

    srv16, port16, cls16 = serve({
        "/m": _stub,
        "/real": (200, {"Content-Type": "text/html"}, page("<h1>Real</h1>" + para())),
        "/file": _media,
        "/app/start": _path_cookie,
        "/other": (200, {"Content-Type": "text/html"}, page("<h1>O</h1>" + para())),
        "/app/deep": (200, {"Content-Type": "text/html"}, page("<h1>D</h1>" + para())),
    })
    b16 = f"http://127.0.0.1:{port16}"
    m_ref, _ = run([b16 + "/m", "--refresh"])
    check("meta refresh is followed", m_ref.get("status") == "ok"
          and (m_ref.get("signals") or {}).get("meta_refresh", "").endswith("/real"),
          "%s %s" % (m_ref.get("status"), (m_ref.get("signals") or {}).get("meta_refresh")))
    m_med, _ = run([b16 + "/file", "--refresh"])
    check("Content-Disposition names the file",
          (m_med.get("files") or {}).get("media", "").endswith("song-2026.mp3"),
          (m_med.get("files") or {}).get("media"))
    run([b16 + "/app/start", "--refresh"])
    run([b16 + "/other", "--refresh"])
    check("cookie: Path keeps a scoped cookie off another path",
          "area=" not in cls16.cookies.get("/other", ""), cls16.cookies.get("/other", ""))
    run([b16 + "/app/deep", "--refresh"])
    check("cookie: Path sends it inside the folder",
          "area=app" in cls16.cookies.get("/app/deep", ""), cls16.cookies.get("/app/deep", ""))
    check("cookie: Secure is not sent over http",
          "sec=" not in cls16.cookies.get("/app/deep", ""), cls16.cookies.get("/app/deep", ""))

    # ------------------------------------------------ a host's pictures are fetched once
    png2 = b"\x89PNG\r\n\x1a\nSHARED"
    srv17, port17, cls17 = serve({
        "/a": (200, {"Content-Type": "text/html"},
               page("<h1>A</h1>" + para(), extra='<img src="/shared.png">')),
        "/b": (200, {"Content-Type": "text/html"},
               page("<h1>B</h1>" + para(), extra='<img src="/shared.png">')),
        "/shared.png": (200, {"Content-Type": "image/png"}, png2),
    })
    b17 = f"http://127.0.0.1:{port17}"
    d17a, d17b = os.path.join(tmp, "host-a"), os.path.join(tmp, "host-b")
    run([b17 + "/a", "--dir", d17a, "--refresh"])
    first = sum(1 for x in cls17.log if x == "/shared.png")
    m17, _ = run([b17 + "/b", "--dir", d17b, "--refresh"])
    second = sum(1 for x in cls17.log if x == "/shared.png")
    # no picture store; the other page's folder (its cache copy) is the source
    check("pictures: the same picture is fetched once per host", first == 1 and second == first,
          "%d -> %d requests" % (first, second))
    f17 = [e["file"] for e in (m17.get("images") or []) if e.get("file")]
    p17 = os.path.join(d17b, f17[0].replace("/", os.sep)) if f17 else ""
    check("pictures: the second page still gets the file", bool(p17) and os.path.isfile(p17),
          str(f17))
    check("pictures: reuse is reported",
          (m17.get("signals") or {}).get("images_reused") == 1,
          (m17.get("signals") or {}).get("images_reused"))
    on_disk = open(p17, "rb").read() if p17 and os.path.isfile(p17) else b""
    check("pictures: the reused file is a real copy", on_disk == png2, "%d bytes" % len(on_disk))
    _, _, mod19 = inproc(["--caps"])
    a_dir = mod19.page_dir(b17 + "/a")
    try:
        a_man = json.load(open(os.path.join(a_dir, "manifest.json"), encoding="utf-8"))
        a_file = os.path.join(a_dir, [e["file"] for e in a_man.get("images") or [] if e.get("file")][0])
        linked = os.path.samefile(a_file, p17)
    except (OSError, ValueError, IndexError):
        a_file, linked = "", False
    check("pictures: one inode, not two copies", linked, a_file)

    # ------------------------------------------------ extraction: structure beats length
    _, _, mod18 = inproc(["--caps"])
    flat = "word " * 500                                   # 500 words, no structure
    shaped = "## Heading\n\n" + "word " * 400              # 400 words, 8 headings
    shaped += "\n".join("## H%d\n\n%s" % (i, "word " * 40) for i in range(7))
    check("extraction: headings beat raw length", mod18.text_score(shaped) > mod18.text_score(flat),
          "%d vs %d" % (mod18.text_score(shaped), mod18.text_score(flat)))
    check("extraction: a longer flat text still wins over a much shorter one",
          mod18.text_score("word " * 800) > mod18.text_score(shaped), "")
    check("extraction: score is words plus two per heading",
          mod18.text_score("## a\n\n## b\n\ntext") == len("## a ## b text".split()) + 4,
          mod18.text_score("## a\n\n## b\n\ntext"))

    # ------------------------------------------------ a docx keeps its picture order
    try:
        import docx
        doc = docx.Document()
        doc.add_paragraph("first")
        doc.add_picture(io_bytes(tiny_png((255, 0, 0))), width=docx.shared.Inches(0.2))
        doc.add_paragraph("second")
        doc.add_picture(io_bytes(tiny_png((0, 0, 255))), width=docx.shared.Inches(0.2))
        buf = io.BytesIO()
        doc.save(buf)
        srv19, port19, _ = serve({
            "/ordered.docx": (200, {"Content-Type":
                                    "application/vnd.openxmlformats-officedocument."
                                    "wordprocessingml.document"}, buf.getvalue()),
        })
        d19_out = os.path.join(tmp, "ordered-out")
        m19, _ = run([f"http://127.0.0.1:{port19}/ordered.docx", "--dir", d19_out, "--refresh"])
        names = [e["file"] for e in (m19.get("images") or [])]
        check("docx: two pictures are found", len(names) == 2, str(names))
        check("docx: order comes from document.xml",
              [e.get("order") for e in (m19.get("images") or [])] == [1, 2]
              and (m19.get("signals") or {}).get("images_ordered") is True,
              str([(e.get("order"), e["file"]) for e in (m19.get("images") or [])]))
    except ImportError:
        print("SKIP docx order (python-docx is not installed)")

    # document order, not zip order: the two are not the same in a real docx
    class _ZipShim:
        def __init__(self, files):
            self.files = files

        def read(self, name):
            return self.files[name].encode("utf-8")

        def open(self, name):              # zip_part() reads a part through open(), capped
            return io.BytesIO(self.read(name))

    shim = _ZipShim({
        "word/document.xml": '<w:body><a:blip r:embed="rId9"/><a:blip r:embed="rId2"/></w:body>',
        "word/_rels/document.xml.rels":
            '<Relationship Id="rId2" Target="media/second.png"/>'
            '<Relationship Id="rId9" Target="media/first.png"/>',
    })
    check("docx: order follows document.xml, not the archive",
          mod18.docx_image_order(shim) == ["word/media/first.png", "word/media/second.png"],
          mod18.docx_image_order(shim))

    # an EPUB names its pictures through the spine of the package document
    import zipfile
    epub_buf = io.BytesIO()
    with zipfile.ZipFile(epub_buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf",
                   '<package><manifest>'
                   '<item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="c2" href="chap2.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="i1" href="images/z.png" media-type="image/png"/>'
                   '<item id="i2" href="images/a.png" media-type="image/png"/>'
                   '</manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine>'
                   '</package>')
        z.writestr("OEBPS/chap1.xhtml", '<html><body><img src="images/z.png"/></body></html>')
        z.writestr("OEBPS/chap2.xhtml", '<html><body><img src="images/a.png"/></body></html>')
        z.writestr("OEBPS/images/a.png", tiny_png((0, 0, 255)))    # written first, read second
        z.writestr("OEBPS/images/z.png", tiny_png((255, 0, 0)))

    epub_dir = os.path.join(tmp, "epub-out")
    entries = mod18.zip_images(io.BytesIO(epub_buf.getvalue()), epub_dir)
    check("epub: the pictures land in the manifest", len(entries) == 2,
          str([e["file"] for e in entries]))
    check("epub: order follows the spine, not the archive",
          [e.get("file") for e in entries] == ["img/z.png", "img/a.png"],
          str([(e.get("order"), e["file"]) for e in entries]))

    # ------------------------------------------------ the picture order of a package: linear scans, on the clock
    # A few KB of archive made the scans take minutes (a tag that never closes, a list searched
    # for every picture, one chapter named by the spine again and again), past the read's deadline
    def epub_zip(container, opf, parts):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", container)
            zf.writestr("OEBPS/content.opf", opf)
            for part, body in parts.items():
                zf.writestr("OEBPS/" + part, body)
        return zipfile.ZipFile(io.BytesIO(buf.getvalue()))

    def took(fn, *a):
        t0 = time.time()
        got = fn(*a)
        return got, time.time() - t0

    root_xml = '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'
    one_chapter = ('<package><manifest><item id="c" href="c.xhtml"/></manifest>'
                   '<spine><itemref idref="c"/></spine></package>')
    got, secs = took(mod18.epub_image_order, epub_zip("<container><rootfiles>" + "<rootfile " * 18000, "<package/>", {}))
    check("a container of <rootfile tags that never close is read in linear time (18 000 of them)",
          got == [] and secs < 2.0, "%d names, %.2f s (14 s when quadratic)" % (len(got), secs))
    got, secs = took(mod18.epub_image_order, epub_zip(root_xml, "<package><manifest>" + "<item " * 40000, {}))
    check("an OPF of <item tags that never close is read in linear time (40 000 of them)",
          got == [] and secs < 2.0, "%d names, %.2f s" % (len(got), secs))
    got, secs = took(mod18.epub_image_order,
                     epub_zip(root_xml, one_chapter, {"c.xhtml": "<html><body>" + "<img " * 7000 + "</body></html>"}))
    check("a chapter of <img tags that never close is read in linear time (7 000 of them)",
          got == [] and secs < 2.0, "%d names, %.2f s" % (len(got), secs))
    many = "<html><body>" + "".join('<img src="images/i%d.png"/>' % i for i in range(30000)) + "</body></html>"
    got, secs = took(mod18.epub_image_order, epub_zip(root_xml, one_chapter, {"c.xhtml": many}))
    check("30 000 distinct pictures in one chapter are put in order in linear time, none lost",
          len(got) == 30000 and got[0] == "OEBPS/images/i0.png" and got[-1] == "OEBPS/images/i29999.png"
          and secs < 2.0, "%d names, %.2f s (6 s when quadratic)" % (len(got), secs))
    rep = ('<package><manifest><item id="c" href="c.xhtml"/></manifest><spine>' + '<itemref idref="c"/>' * 1500
           + '</spine></package>')
    five = "<html><body>" + "".join('<img src="images/i%d.png"/>' % i for i in range(500)) + "</body></html>"
    got, secs = took(mod18.epub_image_order, epub_zip(root_xml, rep, {"c.xhtml": five}))
    check("a chapter the spine names 1 500 times is scanned once",
          len(got) == 500 and secs < 2.0, "%d names, %.2f s (5 s when it is scanned each time)" % (len(got), secs))
    shim2 = _ZipShim({
        "word/document.xml": "<w:body>" + "".join('<a:blip r:embed="rId%d"/>' % i for i in range(30000)) + "</w:body>",
        "word/_rels/document.xml.rels": "".join('<Relationship Id="rId%d" Target="media/i%d.png"/>' % (i, i)
                                                for i in range(30000)),
    })
    got, secs = took(mod18.docx_image_order, shim2)
    check("30 000 distinct pictures of a docx are put in order in linear time, none lost",
          len(got) == 30000 and got[0] == "word/media/i0.png" and secs < 2.0, "%d names, %.2f s" % (len(got), secs))
    shim3 = _ZipShim({
        "word/document.xml": "<w:body>" + "<a:blip " * 7000 + "</w:body>",
        "word/_rels/document.xml.rels": "<Relationship " * 7000,
    })
    got, secs = took(mod18.docx_image_order, shim3)
    check("a docx whose tags never close is read in linear time", got == [] and secs < 2.0,
          "%d names, %.2f s" % (len(got), secs))
    ep = epub_zip(root_xml, one_chapter, {"c.xhtml": '<html><body><img src="images/a.png"/></body></html>'})
    def ordered_until(until):
        try:
            return mod18.epub_image_order(ep, until)
        except TypeError as e:                       # a function that takes no clock
            return "TypeError: %s" % e
    check("with time left the order is the book's; with none left there is no order, not a guess",
          ordered_until(time.time() + 60) == ["OEBPS/images/a.png"] and ordered_until(time.time() - 1) == [],
          "%s / %s" % (ordered_until(time.time() + 60), ordered_until(time.time() - 1)))
    asked = []
    real_order = mod18.epub_image_order
    mod18.epub_image_order = lambda zf, until=None: asked.append(until) or []
    try:
        mod18.zip_images(io.BytesIO(epub_buf.getvalue()), os.path.join(tmp, "epub-clock"))
    finally:
        mod18.epub_image_order = real_order
    check("the picture order is asked for on the read's clock (10 s at most)",
          len(asked) == 1 and isinstance(asked[0], float)
          and time.time() < asked[0] <= time.time() + mod18.PICTURE_ORDER_SECONDS + 0.5, str(asked))

    # ------------------------------------------------ every unpacked byte counts, a duplicate is not unpacked
    def package(parts, level=1):
        path_ = os.path.join(tmp, "l1-%d.epub" % time.time_ns())
        with zipfile.ZipFile(path_, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
            zf.writestr("mimetype", "application/epub+zip")
            for part, body in parts:
                zf.writestr(part, body)
        return path_

    def unpacked(path_, *a):
        """(entries, the pictures zip_images unpacked): the archive's open() is counted."""
        real = zipfile.ZipFile.open
        names = []

        def counting(self, name, *oa, **ok):
            names.append(getattr(name, "filename", name))
            return real(self, name, *oa, **ok)
        zipfile.ZipFile.open = counting
        try:
            got_ = mod18.zip_images(path_, os.path.join(tmp, "l1-out-%d" % time.time_ns()), *a)
        finally:
            zipfile.ZipFile.open = real
        return got_, [n for n in names if str(n).endswith(".png")]
    blob = tiny_png((9, 8, 7)) + b"\0" * (4 * 1024 * 1024)
    got, opened = unpacked(package([("OEBPS/images/c%d.png" % i, blob) for i in range(40)]))
    check("40 copies of one picture: one is unpacked, the other 39 are skipped by size and CRC",
          len(got) == 1 and len(opened) == 1, "%d kept, %d unpacked" % (len(got), len(opened)))

    def pixel(i):
        # a 1x1 picture by its header, 2 MB of its own bytes after it
        head = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (1).to_bytes(4, "big") * 2
        return head + b"\0" * (2 * 1024 * 1024) + bytes([i])
    got, opened = unpacked(package([("OEBPS/images/p%d.png" % i, pixel(i)) for i in range(8)]), 5 * 1024 * 1024)
    check("pictures that are not kept (a counter pixel) still count against the budget: 2 of 8 unpacked in 5 MB",
          got == [] and len(opened) == 2, "%d kept, %d unpacked" % (len(got), len(opened)))
    got, opened = unpacked(package([("OEBPS/images/a.png", tiny_png((1, 1, 1))),
                                    ("OEBPS/images/b.png", tiny_png((2, 2, 2))),
                                    ("OEBPS/images/c.png", tiny_png((1, 1, 1)))]))
    check("different pictures are all kept; a repeat is not", len(got) == 2 and len(opened) == 2,
          "%d kept, %d unpacked" % (len(got), len(opened)))

    # ------------------------------------------------ a picture the archive lacks costs the others nothing
    import types
    m4 = os.path.join(tmp, "m4")
    os.makedirs(os.path.join(m4, "img"), exist_ok=True)
    m4_entries = []
    for i, (nm, col) in enumerate((("one", (255, 0, 0)), ("two", (0, 255, 0))), 1):
        with open(os.path.join(m4, "img", "%s.png" % nm), "wb") as fh:
            fh.write(tiny_png(col))
        m4_entries.append({"file": "img/%s.png" % nm, "bytes": 60, "dims": "4x4", "alt": "", "_zip": "OEBPS/images/%s.png" % nm})
    m4_text = "![one](images/one.png)\n\nbody words.\n\n![two](images/two.png)\n\n![gone](images/gone.png)\n"
    m4_text, m4_entries = mod18.doc_pictures(m4_text, m4_entries, m4)
    m4_man = {"images": m4_entries}
    m4_text, _ = mod18.picture_phase(m4_text, m4_text, "", "http://127.0.0.1:9/book.epub", m4, m4_man,
                                     types.SimpleNamespace(download=False), False)
    got = m4_man["images"]
    check("the pictures with a file keep their entries, the missing one is listed after them",
          [(e["n"], bool(e.get("file"))) for e in got] == [(1, True), (2, True), (3, False)],
          str([(e["n"], e.get("file"), e.get("why")) for e in got]))
    check("every marker of the text is its own number, the missing one's too",
          sorted(re.findall(r"\[img #(\d+)", m4_text)) == ["1", "2", "3"] and "gone" in m4_text.split("#3")[1],
          m4_text.replace("\n", " ")[:200])
    mod18.prune_unreferenced(m4, {"images": got})
    check("--refresh's cleanup keeps the pictures the manifest lists",
          sorted(os.listdir(os.path.join(m4, "img"))) == ["01-one.png", "02-two.png"],
          str(os.listdir(os.path.join(m4, "img"))))

    # the cache step stopped at a list among a read's files - a scan's pages, the screenshots - with a TypeError, so
    # such a read read into --dir was never kept, and one in the cache's own folder was kept without its files
    _, _, modc = inproc(["--caps"])
    wdc = os.path.join(tmp, "cache-lists")
    os.makedirs(os.path.join(wdc, "shots"))
    for name_ in ("content.md", "page-01.png", os.path.join("shots", "01.png")):
        with open(os.path.join(wdc, name_), "wb") as fh_:
            fh_.write(b"x")
    modc.store_cache(wdc, {"status": "ok", "files": {
        "content": os.path.join(wdc, "content.md"), "pages": [os.path.join(wdc, "page-01.png")],
        "screenshots": [os.path.join(wdc, "shots", "01.png")]}}, "http://127.0.0.1:9/cache-lists")
    hitc = modc.cached("http://127.0.0.1:9/cache-lists", False)
    fc = (hitc[1].get("files") if hitc else None) or {}
    check("a read whose files hold lists (a scan's pages, screenshots) is kept in the cache with them (TypeError)",
          bool(fc.get("content")) and [os.path.basename(p) for p in fc.get("pages") or []] == ["page-01.png"]
          and [os.path.relpath(p, hitc[0]) for p in fc.get("screenshots") or []] == [os.path.join("shots", "01.png")]
          and all(os.path.isfile(p) for p in (fc.get("pages") or []) + (fc.get("screenshots") or [])), str(fc)[:200])
    # ... and a cache hit into another --dir takes them there (it named each file by its name in the folder alone)
    wdm = os.path.join(tmp, "cache-lists-dir")
    try:
        fm = modc.moved_files(fc, hitc[0], modc.materialize(hitc[0], wdm)) if hitc else {}
    except Exception as e_:                                         # noqa: BLE001
        fm = {"error": repr(e_)}
    check("... and a cache hit into another --dir takes them there, the screenshots in shots/",
          [os.path.relpath(p, wdm) for p in (fm.get("pages") or []) + (fm.get("screenshots") or [])]
          == ["page-01.png", os.path.join("shots", "01.png")]
          and all(os.path.isfile(p) for p in (fm.get("pages") or []) + (fm.get("screenshots") or [])), str(fm)[:200])

    # ------------------------------------------------ OCR of a scanned PDF
    try:
        from PIL import Image, ImageDraw, ImageFont
        font = None
        for cand in ("C:/Windows/Fonts/arialbd.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(cand, 64)
                break
            except OSError:
                continue
        img = Image.new("RGB", (1240, 800), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        if font is None:
            draw.text((60, 80), "SCANNED REPORT", fill=(0, 0, 0))
        else:
            draw.text((60, 80), "SCANNED REPORT", fill=(0, 0, 0), font=font)
            draw.text((60, 220), "Total 42 units", fill=(0, 0, 0), font=font)
        pdf = io.BytesIO()
        img.save(pdf, "PDF", resolution=150)
        srv20, port20, _ = serve({"/scan.pdf": (200, {"Content-Type": "application/pdf"},
                                                pdf.getvalue())})
        d20 = os.path.join(tmp, "scan-out")
        m20, _ = run([f"http://127.0.0.1:{port20}/scan.pdf", "--dir", d20, "--refresh"])
        cpath = os.path.join(d20, "content.md")
        txt20 = open(cpath, encoding="utf-8").read() if os.path.isfile(cpath) else ""
        # a --refresh (every read of a file on this machine is one) cleaned up the files the manifest does not name,
        # and it took a list among them for nothing: the pages it had just rendered went, with or without OCR
        pages20 = (m20.get("files") or {}).get("pages") or []
        check("a scan's rendered pages stay where files.pages names them (a --refresh deleted them)",
              bool(pages20) and all(os.path.isfile(p) for p in pages20), str(pages20)[:120])
        if "ocr:tesseract" in ((m20.get("chain") or {}).get("tried") or []):
            check("OCR: a scanned PDF becomes text", "SCANNED" in txt20.upper(),
                  txt20[:50].replace("\n", " "))
            check("OCR: the pages and languages are reported",
                  (m20.get("signals") or {}).get("ocr_pages") == 1
                  and bool((m20.get("signals") or {}).get("ocr_langs")),
                  str({k: v for k, v in (m20.get("signals") or {}).items()
                       if k.startswith("ocr")}))
            check("OCR: the text is not marked as a missing text layer",
                  "OCR" in json.dumps(m20.get("missing") or []), "")
            env20 = {"READ_PAGE_OCR_LANGS": "kat"}        # Georgian: none of the packs --setup fetches by itself
            m21, _ = run([f"http://127.0.0.1:{port20}/scan.pdf", "--refresh"], env=env20)
            check("OCR: a missing language pack is named, not silent",
                  (m21.get("signals") or {}).get("ocr_missing_langs") == ["kat"]
                  and "kat.traineddata" in json.dumps(m21.get("improve") or []),
                  str((m21.get("signals") or {}).get("ocr_missing_langs")))
        else:
            print("SKIP OCR checks (tesseract is not installed)")
            check("without tesseract the scan names the fix",
                  "ocr" in json.dumps(m20.get("improve") or []), json.dumps(m20.get("improve"))[:80])
        # a scan with a few words of its own (a scanner's stamp, a page number): --alternate took
        # pymupdf4llm's three words for the document and never looked for a text layer - `empty`,
        # no OCR, no rendered pages (w3.org's dummy.pdf, 2026-11-19)
        stamped = pdf.getvalue()
        try:
            import pymupdf
            d20 = pymupdf.open(stream=stamped, filetype="pdf")
            d20[0].insert_text((40, 30), "p. 1", fontsize=8)
            stamped = d20.tobytes()
            d20.close()
        except ImportError:
            pass
        srv20.RequestHandlerClass.routes["/stamped.pdf"] = (200, {"Content-Type": "application/pdf"}, stamped)
        got20 = []
        for extra in ([], ["--alternate"]):
            m, _ = run([f"http://127.0.0.1:{port20}/stamped.pdf", "--refresh"] + extra)
            got20.append((m.get("status"), (m.get("signals") or {}).get("scanned"),
                          (m.get("signals") or {}).get("ocr_pages")))
        check("--alternate: a scan is still a scan (the same status, its pages rendered or read)",
              got20[0] == got20[1] and got20[0][1] is True, "plain %s, --alternate %s" % tuple(got20))
    except ImportError:
        print("SKIP OCR checks (Pillow is not installed)")

    # ------------------------------------------------ video: timestamps survive
    _, _, mod22 = inproc(["--caps"])
    vtt = ("WEBVTT\nKind: captions\n\n"
           "00:00:01.000 --> 00:00:02.000\nhello there\n\n"
           "00:00:02.500 --> 00:00:04.000\nsecond cue\n\n"
           "00:00:40.000 --> 00:00:42.000\nmuch later\n\n"
           "00:01:05.000 --> 00:01:07.000\nan hour test\n")
    txt = mod22.vtt_to_text(vtt)
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    check("video: the transcript keeps timestamps", bool(lines) and lines[0].startswith("[0:0"),
          lines[0][:40] if lines else "")
    check("video: cues are grouped, not one line each", 1 < len(lines) <= 3,
          "blocks=%d" % len(lines))
    check("video: a later block gets its own stamp",
          any(ln.startswith("[0:40]") for ln in lines), str([ln[:8] for ln in lines]))
    check("video: over an hour is written h:mm:ss",
          "1:05" in mod22.vtt_to_text(
              "WEBVTT\n\n00:01:05.000 --> 00:01:07.000\nx\n"), "")

    # ------------------------------------------------ a URL never reaches a command line
    seen = {}
    _, _, mod15 = inproc(["--caps"])

    def fake_run(cmd, timeout=120):
        seen["cmd"] = cmd
        return 0, b"out", b""

    mod15.run = fake_run
    mod15.run_tool(["C:\\tools\\defuddle", "parse", "a&b|c>d.html", "--markdown"])
    cmd = seen.get("cmd")
    check("run_tool passes argv, not a shell string", isinstance(cmd, list), type(cmd).__name__)
    check("run_tool keeps a metacharacter argument in one piece",
          isinstance(cmd, list) and "a&b|c>d.html" in cmd, cmd)

    # ------------------------------------------------ --screenshots is a mode, not a hint
    _, _, mod_shot = inproc(["--caps"])
    check("screenshots: the cache mode changes with the count",
          mod_shot.mode_key(False, False, False, 1) != mod_shot.mode_key(False, False, False, 0)
          and mod_shot.mode_key(False, False, False, 3) != mod_shot.mode_key(False, False, False, 1),
          "%s vs %s" % (mod_shot.mode_key(False, False, False, 1),
                         mod_shot.mode_key(False, False, False, 0)))

    srv_s, port_s, _ = serve({"/plain.html": (200, {"Content-Type": "text/html; charset=utf-8"},
        ("<html><body><h1>Plain</h1><p>" + "word " * 300 + "</p></body></html>").encode())})
    m_s, _ = run([f"http://127.0.0.1:{port_s}/plain.html", "--screenshots"])
    check("screenshots: without a browser nothing is invented",
          not (m_s.get("files") or {}).get("screenshots")
          and not (m_s.get("signals") or {}).get("screenshots"),
          str((m_s.get("signals") or {}).get("screenshots")))
    check("screenshots: the missing browser is named",
          "browser" in json.dumps(m_s.get("missing") or []), json.dumps(m_s.get("missing"))[:80])

    try:
        import pymupdf
        doc = pymupdf.open()
        pg = doc.new_page(width=595, height=842)
        for i in range(30):
            pg.insert_text((60, 60 + i * 24), "line %d of a scanned report" % i, fontsize=11)
        pdf_path = os.path.join(tmp, "tall.pdf")
        doc.save(pdf_path)
        doc.close()
        tiles, needed = mod_shot.pdf_shots(pdf_path, os.path.join(tmp, "pdf-shots"), 3)
        # N counts screens of 784 px; a 1568 px picture holds two (an A4 page: 1811 px, 3)
        check("screenshots: a PDF page is cut into 1280x1568 pictures, two screens each",
              len(tiles) == 2 and needed == 3 and [t.get("screens") for t in tiles] == [[1, 2], [3]]
              and all(t["width"] == 1280 and t["height"] <= 1568 for t in tiles),
              "%d pictures, needed %d, sizes %s" % (len(tiles), needed,
                                                    [(t["height"], t.get("screens")) for t in tiles]))
        check("screenshots: the last tile is shorter, not padded",
              tiles[0]["height"] == 1568 and tiles[-1]["height"] < 1568,
              str([t["height"] for t in tiles]))
    except ImportError:
        print("SKIP PDF screenshots (pymupdf is not installed)")

    # ------------------------------------------------ no URL: the setup report
    p23 = subprocess.run([sys.executable, "-X", "utf8", SCRIPT], capture_output=True, timeout=120)
    out23 = p23.stdout.decode("utf-8", "replace")
    check("no URL: the setup report replaces the error",
          p23.returncode == 0 and "setup report" in out23,
          out23.splitlines()[0][:60] if out23 else "")
    check("no URL: the report names --setup and installs nothing by itself",
          "readpage.py --setup" in out23 and ("report installs nothing" in out23
                                              or "their yes is all it needs" in out23), "")
    check("no URL: both keys are named, neither fetched",
          "FIRECRAWL_API_KEY" in out23 and "JINA_API_KEY" in out23, "")

    # ------------------------------------------------ when a rendered page is done
    _, _, mod23 = inproc(["--caps"])
    settle = mod23.settle

    def settles(polls, status=200, dcl=0.0):
        """The rule over polls of (t, chars, mount size, mount head, challenge, in flight): the
        first (t, reason) it lets go at, or (None, "")."""
        rule = settle.Settle(dcl, status)
        for t, chars, msize, mhead, chl, busy in polls:
            why = rule.see(t, chars, msize, mhead, chl, busy)
            if why:
                return t, why
        return None, ""

    def steps(until, every=0.1):
        return [round(i * every, 2) for i in range(1, int(until / every) + 1)]

    # text at 0.5 s, a burst of scripts until 1.4 s, then the data until 2.0 s (Steam, AliExpress)
    polls = [(t, 3000 if t < 2.0 else 5000, -1, "", False, 0.5 < t < 2.0) for t in steps(6)]
    t, why = settles(polls)
    check("settle: scripts in flight hold the page; done after the data, not before",
          why == "settled" and t >= 3.0, "%s at %s" % (why, t))
    # quiet at one poll is not quiet: requests come and go every 0.6 s while the text grows (rbc.ru)
    polls = [(t, 0 if t < 3.0 else 6000, -1, "", False, round(t * 10) % 6 != 0 and t < 3.5) for t in steps(8)]
    t, why = settles(polls, status=401)
    check("settle: an error status with requests still coming is waited for (rbc.ru: 401, text at 3 s)",
          why == "settled" and t > 4.0, "%s at %s" % (why, t))
    polls = [(t, 900, -1, "", False, False) for t in steps(4)]
    check("settle: unchanged text and a quiet network for 1 s is done", settles(polls) == (1.1, "settled"), str(settles(polls)))
    polls = [(t, 900, -1, "", False, True) for t in steps(6)]
    check("settle: requests that never end (analytics) let go after 2 s of unchanged text",
          settles(polls) == (2.1, "busy"), str(settles(polls)))
    # a weak laptop: Steam's scripts held the probe 3.7 s; that pause is work, not quiet
    polls = [(0.1, 4220, -1, "", False, True), (0.2, 4220, -1, "", False, True), (3.9, 4220, -1, "", False, False)] \
        + [(round(3.9 + i * 0.1, 2), 4220 if i < 5 else 5700, -1, "", False, False) for i in range(1, 40)]
    t, why = settles(polls)
    check("settle: a poll the page held back is not a quiet page (the text after it is waited for)",
          why == "settled" and t >= 5.4, "%s at %s" % (why, t))
    polls = [(t, 600, 0, "", False, False) for t in steps(6)]
    check("settle: an empty mount node is not done (a page still to be filled)", settles(polls) == (None, ""), "")
    polls = [(t, 600, 50, "Loading...", False, False) for t in steps(6)]
    check("settle: a Loading... placeholder is not done", settles(polls) == (None, ""), "")
    polls = [(t, 0, -1, "", False, False) for t in steps(6)]
    check("settle: an empty body with nothing coming is let go at 3 s", settles(polls) == (3.0, "empty"), "")
    polls = [(t, 0, 0, "", False, False) for t in steps(6)]
    check("settle: an empty body with an empty #app waits (a timer fills it)", settles(polls) == (None, ""), "")
    polls = [(t, 40, -1, "", False, False) for t in steps(6)]
    check("settle: a 403 page that does not change is let go after a second",
          settles(polls, status=403) == (1.1, "settled"), str(settles(polls, status=403)))
    polls = [(t, 0, -1, "", False, False) for t in steps(6)]
    check("settle: an empty 403 is let go 1.5 s after it is seen, not after 12 (g2, amazon)",
          settles(polls, status=403) == (1.6, "error-page"), str(settles(polls, status=403)))
    polls = [(t, 0, -1, "", True, False) for t in steps(6)]
    check("settle: a challenge still running is not an error page to let go of",
          settles(polls, status=403)[1] != "error-page", str(settles(polls, status=403)))

    # ------------------------------------------------ one session for every engine
    old_cache = os.environ.get("READ_PAGE_CACHE")
    os.environ["READ_PAGE_CACHE"] = os.path.join(tmp, "sess")
    try:
        u24 = "https://app.example.com/a"
        exp = int(time.time()) + 600
        mod23.save_cookies(u24, {"sid": {"v": "abc", "d": "example.com", "e": exp, "p": "/",
                                         "s": True, "h": "app.example.com"},
                                 "hostonly": {"v": "h", "d": "", "e": 0, "p": "/", "s": False,
                                              "h": "app.example.com"}}, set_from=u24)
        pwc = {c["name"]: c for c in mod23.pw_cookies(u24)}
        check("browser tier gets the jar: a Domain cookie goes in as domain",
              pwc.get("sid", {}).get("domain") == "example.com", str(pwc.get("sid")))
        check("browser tier gets the jar: a host-only cookie goes in as url",
              pwc.get("hostonly", {}).get("url", "").startswith("https://app.example.com/"),
              str(pwc.get("hostonly")))
        check("browser tier gets the jar: Secure survives the trip",
              pwc.get("sid", {}).get("secure") is True, "")

        class FakeCtx:
            def cookies(self):
                return [{"name": "js_session", "value": "x1", "domain": "app.example.com",
                         "path": "/", "expires": int(time.time()) + 300, "secure": False},
                        {"name": "gone", "value": "y", "domain": ".example.com", "path": "/",
                         "expires": int(time.time()) - 300, "secure": False}]

        n24 = mod23.save_browser_cookies(FakeCtx(), u24)
        got24 = mod23.cookies_for_url(u24)
        check("browser tier: what JS set is stored for the next run",
              n24 >= 1 and (got24.get("js_session") or {}).get("v") == "x1", str(sorted(got24)))
        check("browser tier: an expired cookie is not stored", "gone" not in got24,
              str(sorted(got24)))

        seen24 = {}
        real_run24 = mod23.run

        def fake_run24(cmd, timeout=120, **kw):
            seen24["cmd"] = cmd
            return 1, b"", b""

        caps24 = mod23.caps()
        caps24["cli"]["yt-dlp"] = "yt-dlp"     # the runner's machine may not have it installed
        mod23.run = fake_run24
        try:
            mod23.video_text("https://app.example.com/v", caps24, os.path.join(tmp, "vid"))
        finally:
            mod23.run = real_run24
        cmd24 = seen24.get("cmd") or []
        check("video: yt-dlp is handed the session cookie file",
              "--cookies" in cmd24, " ".join(cmd24[:5]))
    finally:
        if old_cache is None:
            os.environ.pop("READ_PAGE_CACHE", None)
        else:
            os.environ["READ_PAGE_CACHE"] = old_cache

    # ------------------------------------------------ --screenshots that takes no picture says why (KNOWN-ISSUES 246)
    # screens.capture returned [] when a step of the page failed - the answer had no screenshots and no word of it
    # (CI's browser job once printed "screens None" with nothing to go on). A fake browser breaks one step at a time.
    _, _, mods = inproc(["--caps"])

    class ShotPage:
        """A page as screens.capture drives it: it answers the scripts, and `breaks` names the step that raises."""
        def __init__(self, breaks="", at=0, height=2000):
            self.breaks, self.at, self.height, self.shots = breaks, at, height, 0

        def hit(self, step):
            if self.breaks == step:
                raise RuntimeError("Page.%s: Target page, context or browser has been closed\nCall log: ..." % step)

        def add_style_tag(self, content=""):
            self.hit("add_style_tag")

        def wait_for_timeout(self, ms):
            pass

        def evaluate(self, js, arg=None):
            sc = mods.screens
            if js == sc.SCROLLER_JS:
                self.hit("evaluate")
                return ["", self.height]
            if js == sc.STATE_JS:
                return [0, 1000.0, "loaded"]
            if js == sc.SCROLL_JS:
                return arg[1]
            if js == "() => innerHeight":
                return 784
            return 0

        def screenshot(self, type="png", quality=None):
            self.shots += 1
            if self.breaks == "screenshot" and self.shots > self.at:
                raise RuntimeError("Page.screenshot: Timeout 30000ms exceeded.\nCall log: ...")
            return b"\x89PNG fake screen %d" % self.shots

    def shots_of(page, **kw):
        """screens.capture on the fake page: (entries, needed, taken, why) - why None where the old code gave no fourth."""
        wd = tempfile.mkdtemp(prefix="shots-", dir=tmp)
        try:
            got = mods.screens.capture(page, wd, kw.pop("want", 2), **kw)
        except Exception as e:                                     # noqa: BLE001
            return [], 0, 0, "raised %s" % e
        return got if len(got) > 3 else got + (None,)

    old_skip = os.environ.get("READ_PAGE_SKIP")
    os.environ["READ_PAGE_SKIP"] = "glue"                          # one screen a picture: no Pillow needed
    try:
        e0, n0, t0, why0 = shots_of(ShotPage())
        check("--screenshots: a page that takes its screens says nothing is wrong",
              (len(e0), n0, t0, why0) == (2, 3, 2, ""), str((len(e0), n0, t0, why0)))
        e1, _n1, t1, why1 = shots_of(ShotPage("add_style_tag"))
        check("--screenshots: a page that refuses the setup gives no picture, and says which step and what it said",
              not e1 and t1 == 0 and isinstance(why1, str) and "adding the style" in why1
              and "RuntimeError" in why1 and "has been closed" in why1 and "Call log" not in why1, repr(why1))
        e2, _n2, t2, why2 = shots_of(ShotPage("screenshot"))
        check("--screenshots: a first screen that cannot be captured gives no picture, and says so",
              not e2 and t2 == 0 and isinstance(why2, str) and "screen 1" in why2 and "capturing" in why2
              and "Timeout 30000ms" in why2, repr(why2))
        e3, n3, t3, why3 = shots_of(ShotPage("screenshot", at=1))
        check("--screenshots: a later screen that fails keeps the first one, and says where it stopped",
              len(e3) == 1 and t3 == 1 and n3 == 3 and isinstance(why3, str) and "screen 2" in why3, repr((len(e3), why3)))
        e4, _n4, t4, why4 = shots_of(ShotPage(), seconds_left=lambda: 0.0)
        check("--screenshots: the read's deadline that ends the loop is no failure",
              len(e4) == 1 and t4 == 1 and why4 == "", repr((len(e4), why4)))

        # the answer carries it: the signal in the manifest, the row in the header, the budget's word
        wd5 = tempfile.mkdtemp(prefix="shots-", dir=tmp)

        def applied(entries, needed, why):
            """A manifest after apply_shots, and its answer's header (the old apply_shots took no reason)."""
            man = {"files": {}, "signals": {}, "status": "ok"}
            try:
                mods.apply_shots(man, wd5, entries, needed, why)
            except TypeError as e:
                man["signals"]["apply_shots"] = str(e)
            return man, "\n".join(mods.answer.header(man, "content.md", 1, 10))

        got5 = mods.capture_shots(ShotPage("screenshot"), wd5, 2)
        why5 = got5[2] if len(got5) > 2 else None
        man5, head5 = applied(got5[0], got5[1], why5)
        check("--screenshots: apply_shots puts the reason into signals.screenshots_failed",
              isinstance(why5, str) and man5["signals"].get("screenshots_failed") == why5 and "screenshots" not in man5,
              str(man5["signals"]))
        check("--screenshots: the answer's header says no screenshot was taken, and why",
              isinstance(why5, str) and "screenshots: none taken - %s" % why5 in head5, head5.replace("\n", " | ")[:300])
        row5 = [r for r in mods.budget.steps() if r["step"] == "screens"][-1:]
        check("--screenshots: the budget records the failed capture as a failure, not as ok or a deadline",
              bool(row5) and row5[0]["end"] == "fail" and "capturing" in row5[0].get("note", ""), str(row5))
        man6, head6 = applied([{"file": "shots/01.png", "width": 1280, "height": 784, "bytes": 10, "format": "png",
                                "screens": [1]}], 3, "screen 2, capturing: RuntimeError: boom")
        check("--screenshots: a page that stopped after some screens says so beside them",
              man6["signals"].get("screens_needed") == 3 and "screenshots: stopped early - screen 2" in head6,
              head6.replace("\n", " | ")[:300])
        man7, head7 = applied([], 0, "")
        check("--screenshots: nothing asked, nothing failed, no signal and no row",
              "screenshots_failed" not in man7["signals"] and "screenshots:" not in head7, head7.replace("\n", " | ")[:200])
    finally:
        if old_skip is None:
            os.environ.pop("READ_PAGE_SKIP", None)
        else:
            os.environ["READ_PAGE_SKIP"] = old_skip

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d ok, %d failed" % (ok, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
