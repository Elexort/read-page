"""Shared pieces for the offline suites: a route server, a CLI run into a temp folder, checks.

    from harness import serve, run_read, Checks, PUBLIC, PRIVATE

Tests read what a run left on disk (manifest.json, content.md, page.md), not stdout: the printed
answer changes format by design, the files are the contract. Only the output-budget tests read
stdout, and they read it as bytes.

READ_PAGE_TEST_PUBLIC_HOST makes exactly one address public, so the main HTTP channel
(curl_cffi) runs against a local server. Every other loopback address stays private: 127.0.0.2
is the target of the "must not reach" tests.
"""
import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "readpage.py")

# A suite sees only what it sets: the user's own debug log switches (READ_PAGE_DEBUG_DIR stays set
# for agent runs) would send every read's log elsewhere, and the debug checks found none
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):
    os.environ.pop(_name, None)
PUBLIC = "127.0.0.1"
PRIVATE = "127.0.0.2"


class Handler(http.server.BaseHTTPRequestHandler):
    """A route is (code, headers, body) or a callable that answers the request itself."""
    protocol_version = "HTTP/1.1"
    routes = {}
    log = []

    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        type(self).log.append({"path": self.path, "method": self.command,
                               "referer": self.headers.get("Referer", ""),
                               "cookie": self.headers.get("Cookie", ""),
                               "ua": self.headers.get("User-Agent", "")})
        r = type(self).routes.get(self.path.split("?")[0])
        if callable(r):
            return r(self)
        if r is None:
            r = (404, {"Content-Type": "text/plain"}, b"missing")
        code, headers, body = r
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True


class Server:
    def __init__(self, routes, host=PUBLIC):
        self.cls = type("H%d" % time.time_ns(), (Handler,), {"routes": routes, "log": []})
        self.srv = socketserver.ThreadingTCPServer((host, 0), self.cls)
        self.srv.daemon_threads = True
        self.host, self.port = host, self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def url(self, path="/"):
        return "http://%s:%d%s" % (self.host, self.port, path)

    @property
    def routes(self):
        return self.cls.routes

    @property
    def log(self):
        return self.cls.log

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def serve(routes, host=PUBLIC):
    return Server(routes, host)


def can_bind(host):
    import socket
    s = socket.socket()
    try:
        s.bind((host, 0))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Run:
    def __init__(self, rc, out, err, manifest, folder, seconds, root=""):
        self.rc, self.out, self.err = rc, out, err          # stdout and stderr are bytes
        self.manifest, self.dir, self.seconds, self.root = manifest or {}, folder, seconds, root

    @property
    def text(self):
        return self.out.decode("utf-8", "replace")

    def file(self, name):
        p = os.path.join(self.dir, name)
        if not os.path.isfile(p):
            return ""
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()


def run_read(url, *flags, env=None, timeout=240, public=True, reuse=None, own_dir=True):
    """One CLI read into a fresh folder with its own cache, or into the folder and cache of an
    earlier Run (`reuse`, for continuations). public=False leaves loopback private.
    own_dir=False runs without --dir, the way an agent does: the folder is the cache entry."""
    tmp = reuse.root if reuse is not None else tempfile.mkdtemp(prefix="rp-test-")
    out = os.path.join(tmp, "out")
    e = dict(os.environ)
    e["READ_PAGE_CACHE"] = os.path.join(tmp, "cache")
    e.pop("READ_PAGE_TEST_PUBLIC_HOST", None)
    for k in ("FIRECRAWL_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "JINA_API_KEY"):
        e.pop(k, None)                     # a test never spends the user's credits; `env` may set a fake one
    if public:
        e["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    e.update(env or {})
    t0 = time.time()
    where = ["--dir", out] if own_dir else []
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, url] + where + list(flags),
                       capture_output=True, timeout=timeout, env=e)
    if not own_dir:
        # the folder of this read: the one whose manifest names this URL (a shared cache holds
        # the pages of earlier reads too)
        pages = os.path.join(tmp, "cache", "pages")
        entries = sorted(n for n in os.listdir(pages) if os.path.isdir(os.path.join(pages, n))) \
            if os.path.isdir(pages) else []
        for n in entries:
            try:
                with open(os.path.join(pages, n, "manifest.json"), encoding="utf-8") as f:
                    if (json.load(f).get("url") or {}).get("requested") == url:
                        out = os.path.join(pages, n)
                        break
            except (OSError, ValueError):
                continue
        else:
            out = os.path.join(pages, entries[0]) if len(entries) == 1 else out
    man = None
    mp = os.path.join(out, "manifest.json")
    if os.path.isfile(mp):
        with open(mp, encoding="utf-8") as f:
            man = json.load(f)
    return Run(p.returncode, p.stdout, p.stderr, man, out, time.time() - t0, tmp)


class Checks:
    def __init__(self):
        self.ok = self.failed = 0
        self.only = sys.argv[1] if len(sys.argv) > 1 else ""

    def __call__(self, name, good, detail=""):
        if self.only and self.only not in name:
            return
        if good:
            self.ok += 1
            print("OK   %-58s %s" % (name, detail))
        else:
            self.failed += 1
            print("FAIL %-58s %s" % (name, detail))

    def skip(self, name, why):
        if not self.only or self.only in name:
            print("SKIP %-58s %s" % (name, why))

    def done(self):
        print("\n%d ok, %d failed" % (self.ok, self.failed))
        return 1 if self.failed else 0
