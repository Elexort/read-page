"""Timeouts. No network.

    python -X utf8 tests/timeouts.py

Every step has its own bound inside the read's deadline (scripts/budget.py): the HTTP step ends in
time whatever the server does (a trickle, a stall), a dead port is quick, a dropped connection is tried
once more, the readers and the archive take at most 20 s each, pictures 6 s, and a PDF that did not
arrive in time is `too_large` with the reason rather than a broken document.
"""
import http.server
import importlib.util
import os
import socket
import socketserver
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import advsrv                                                # noqa: E402
from harness import PRIVATE, PUBLIC, SCRIPT, Checks, can_bind, run_read, serve   # noqa: E402

check = Checks()
H = {"Content-Type": "text/html; charset=utf-8"}
WORDS = ("A reader that waits forever is a reader that never answers, so every step has a bound. ") * 30


def page(title, body):
    return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title></head><body>%s</body></html>"
            % (title, body)).encode("utf-8")


def timed(fn, *a, **k):
    t0 = time.monotonic()
    out = fn(*a, **k)
    return out, time.monotonic() - t0


class Slow(http.server.BaseHTTPRequestHandler):
    """Any path: headers at once, then nothing for `stall` seconds (a reader, an archive, a picture)."""
    stall = 40

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "100000")
        self.end_headers()
        try:
            self.wfile.write(b"x")
            self.wfile.flush()
            time.sleep(self.stall)
        except OSError:
            pass

    do_POST = do_GET

    def log_message(self, *a):
        pass


class SlowText(Slow):
    """A reader that sends 3 000 characters of its answer and then nothing for 40 s."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "100000")
        self.end_headers()
        try:
            self.wfile.write(("READER-PART " + WORDS)[:3000].encode())
            self.wfile.flush()
            time.sleep(self.stall)
        except OSError:
            pass

    do_POST = do_GET                       # Jina is asked by POST


class SlowArchive(Slow):
    """Wayback: the CDX answers at once, the snapshot sends half a page and then nothing."""

    def do_GET(self):
        if self.path.startswith("/cdx/"):
            body = b"20200101000000 https://example.com/a\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        half = page("Archived", "<article><h1>Archived</h1><p>ARCHIVE-PART " + WORDS + "</p>")[:2600]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", "200000")
        self.end_headers()
        try:
            self.wfile.write(half)
            self.wfile.flush()
            time.sleep(self.stall)
        except OSError:
            pass


def slow_server(handler=Slow):
    srv = socketserver.ThreadingTCPServer((PUBLIC, 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://%s:%d" % (PUBLIC, srv.server_address[1])


def flowing_pdf(h):
    """A PDF that keeps arriving at ~8 KB/s: above the speed floor, too big for 20 s."""
    h.send_response(200)
    h.send_header("Content-Type", "application/pdf")
    h.send_header("Content-Length", "2000000")
    h.end_headers()
    try:
        h.wfile.write(b"%PDF-1.4\n")
        for _ in range(120):
            h.wfile.write(b"%" + b"x" * 4094 + b"\n")
            h.wfile.flush()
            time.sleep(0.5)
    except OSError:
        pass
    h.close_connection = True


def cut_media(ctype, head, mode):
    """A media file that promises 2 000 000 bytes: `mode` "break" sends 12 000 and closes the connection, "flow" keeps
    arriving at ~8 KB/s (above the speed floor, too big for the read's time)."""
    def handler(h):
        h.send_response(200)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", "2000000")
        h.send_header("Connection", "close")
        h.end_headers()
        try:
            h.wfile.write(head + b"\x01" * 11980)
            h.wfile.flush()
            for _ in range(120 if mode == "flow" else 0):
                h.wfile.write(b"\x02" * 4096)
                h.wfile.flush()
                time.sleep(0.5)
        except OSError:
            pass
        h.close_connection = True
    return handler


def module():
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-time-")
    spec = importlib.util.spec_from_file_location("rp_time_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Drop:
    """Drops the first connection, then answers: a reset that one more try gets past."""

    def __init__(self, body):
        self.body, self.n = body, 0

    def __call__(self, h):
        self.n += 1
        if self.n == 1:
            h.close_connection = True
            h.connection.close()
            return
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(self.body)))
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(self.body)
        h.close_connection = True


def slow_pdf(h):
    """A PDF that promises 200 000 bytes, sends 12 000 and then stalls."""
    head = b"%PDF-1.4\n" + b"%" + b"x" * 11990 + b"\n"
    h.send_response(200)
    h.send_header("Content-Type", "application/pdf")
    h.send_header("Content-Length", "200000")
    h.end_headers()
    try:
        h.wfile.write(head)
        h.wfile.flush()
        time.sleep(40)
    except OSError:
        pass
    h.close_connection = True


s = advsrv.start()
slow, slow_url = slow_server()
slow_text, slow_text_url = slow_server(SlowText)
slow_arch, slow_arch_url = slow_server(SlowArchive)
s.public.routes.update({
    "/slow.pdf": slow_pdf,
    "/flowing.pdf": flowing_pdf,
    "/broken.mp4": cut_media("video/mp4", b"\x00\x00\x00\x18ftypdash\x00\x00\x00\x00iso6dash", "break"),
    "/broken.mp3": cut_media("audio/mpeg", b"ID3\x03\x00\x00\x00\x00\x00\x00", "break"),
    "/flowing.mp4": cut_media("video/mp4", b"\x00\x00\x00\x18ftypdash\x00\x00\x00\x00iso6dash", "flow"),
    "/pics": (200, H, page("Pictures", "<article><h1>Pictures</h1><p>PICS-MARKER " + WORDS + "</p>"
                           + "".join("<img src='%s/p%d.png' alt='p%d'>" % (slow_url, i, i) for i in range(5))
                           + "</article>")),
})

try:
    # ------------------------------------------------ the HTTP step ends within 20 s
    r, dt = timed(run_read, s.public.url("/trickle"))
    sig = r.manifest.get("signals") or {}
    check("a trickle (22 bytes a second for 150 s) ends within 25 s", dt < 25 and sig.get("partial") is True,
          "%.1f s, partial=%s, %s" % (dt, sig.get("partial"), r.manifest.get("status")))
    r, dt = timed(run_read, s.public.url("/stall"))
    sig = r.manifest.get("signals") or {}
    check("a stall after half a page ends within 20 s, the half is kept",
          dt < 20 and sig.get("partial") is True and r.manifest.get("status") == "ok",
          "%.1f s, partial=%s, %s" % (dt, sig.get("partial"), r.manifest.get("status")))

    # ------------------------------------------------ a dead port is quick, and the error says what to do
    sock = socket.socket()
    sock.bind((PUBLIC, 0))
    dead = sock.getsockname()[1]
    sock.close()
    r, dt = timed(run_read, "http://%s:%d/page" % (PUBLIC, dead))
    # quick, not a timeout: mostly process start-up (3 s on Windows, 5 s from a WSL mount); 0.4.6
    # spent 19.8 s on a dead port
    check("a refused connection answers within 8 s", dt < 8, "%.1f s" % dt)
    check("an error has advice", r.manifest.get("status") == "error" and bool(r.manifest.get("advice")),
          "%s: %r" % (r.manifest.get("status"), (r.manifest.get("advice") or "")[:60]))

    # ------------------------------------------------ a dropped connection is tried once more
    if can_bind(PRIVATE):
        inner = serve({"/drop": Drop(page("Back", "<article><h1>Back</h1><p>DROP-OK " + WORDS + "</p></article>"))},
                      PRIVATE)
        r = run_read(inner.url("/drop"))
        check("a reset on the first try is not an error (plain curl)", r.manifest.get("status") == "ok"
              and "DROP-OK" in r.file("content.md"), str(r.manifest.get("status")))
        inner.close()
    else:
        check.skip("a dropped connection", "127.0.0.2 cannot be bound here")
    s.public.routes["/drop"] = Drop(page("Back", "<article><h1>Back</h1><p>DROP-OK " + WORDS + "</p></article>"))
    r = run_read(s.public.url("/drop"))
    check("a reset on the first try is not an error (curl_cffi)", r.manifest.get("status") == "ok",
          str(r.manifest.get("status")))

    # ------------------------------------------------ why a document was cut decides
    r, dt = timed(run_read, s.public.url("/slow.pdf"))
    reason = str((r.manifest.get("signals") or {}).get("status_reason") or "")
    check("a PDF stuck after 12K is an error (the server stopped), not too_large",
          r.manifest.get("status") == "error" and "stopped sending" in reason
          and "--download" in (r.manifest.get("advice") or "") and dt < 25,
          "%.1f s %s: %s" % (dt, r.manifest.get("status"), reason[:70]))
    # no fixed 20 s for HTTP any more; the read's deadline (here shortened to 20 s) ends it
    r, dt = timed(run_read, s.public.url("/flowing.pdf"), env={"READ_PAGE_TEST_DEADLINE": "20"})
    reason = str((r.manifest.get("signals") or {}).get("status_reason") or "")
    check("a PDF still arriving at the read's deadline is too_large, with the reason",
          r.manifest.get("status") == "too_large" and "still arriving" in reason
          and "--download" in (r.manifest.get("advice") or "") and dt < 30,
          "%.1f s %s: %s" % (dt, r.manifest.get("status"), reason[:70]))

    # ------------------------------------------------ a media file cut in transit is not a file read (it was `media_only`)
    # a fragmented MP4 (YouTube's DASH) cut short plays only as a stream, and the answer called it a file with no
    # word of the cut
    r, dt = timed(run_read, s.public.url("/broken.mp4"))
    reason = str((r.manifest.get("signals") or {}).get("status_reason") or "")
    adv = r.manifest.get("advice") or ""
    kept = [n for n in os.listdir(r.dir) if n.endswith(".mp4")] if os.path.isdir(r.dir) else []
    check("a video whose connection broke after 12K is an error, with how much arrived and what to do, and no file kept",
          r.manifest.get("status") == "error" and "connection broke" in reason and "video file" in reason
          and "--download" in adv and not (r.manifest.get("files") or {}).get("media") and not kept,
          "%s: %s | %s | %s" % (r.manifest.get("status"), reason[:90], adv[:60], kept))
    r, dt = timed(run_read, s.public.url("/broken.mp3"))
    reason = str((r.manifest.get("signals") or {}).get("status_reason") or "")
    check("... an audio file the same", r.manifest.get("status") == "error" and "audio file" in reason,
          "%s: %s" % (r.manifest.get("status"), reason[:90]))
    r, dt = timed(run_read, s.public.url("/flowing.mp4"), env={"READ_PAGE_TEST_DEADLINE": "20"})
    reason = str((r.manifest.get("signals") or {}).get("limit") or "")
    check("a video still arriving at the read's deadline is too_large, with the reason, and --download",
          r.manifest.get("status") == "too_large" and "still arriving" in reason and "video file" in reason
          and "--download" in (r.manifest.get("advice") or "") and not (r.manifest.get("files") or {}).get("media") and dt < 30,
          "%.1f s %s: %s" % (dt, r.manifest.get("status"), reason[:70]))

    # ------------------------------------------------ pictures: a stuck one 4 s, then the answer
    r, dt = timed(run_read, s.public.url("/pics"))
    check("pictures that never answer cost their own 4 s, not the phase", dt < 12 and "PICS-MARKER" in r.file("content.md"),
          "%.1f s" % dt)

    # ------------------------------------------------ readers and the archive: 20 s a step
    mod = module()
    mod.JINA_URL = slow_url + "/jina/"
    mod.READERS = ("jina",)                # the chain itself is tests/sources.py; nothing real is asked
    os.environ.pop("FIRECRAWL_API_KEY", None)
    (text, eng, st, note), dt = timed(mod.external_read, "https://example.com/a", mod.caps())
    check("a reader that stalls costs at most ~12 s", dt < 14 and not text, "%.1f s %s %s" % (dt, eng, note[:50]))
    mod.JINA_URL = slow_text_url + "/jina/"
    (text, eng, st, note), dt = timed(mod.external_read, "https://example.com/a", mod.caps())
    check("a reader that sent part of its text and stalled: the part is kept, marked cut",
          dt < 14 and "READER-PART" in (text or "") and note.startswith("cut:"), "%.1f s %s" % (dt, note[:60]))
    mod.WAYBACK_URL = slow_url
    out, dt = timed(mod.archived_text, "https://example.com/a", mod.caps(), tempfile.mkdtemp(prefix="rp-arch-"))
    # 20 s is the step's own bound; the rest is a machine's overhead (a macOS Intel runner took 22.7 s for the
    # second, 2026-11-21): the check is that the step is bounded, not that the machine is fast
    check("an archive that stalls costs at most ~20 s", dt < 26 and not out[0], "%.1f s" % dt)
    mod.WAYBACK_URL = slow_arch_url
    out, dt = timed(mod.archived_text, "https://example.com/a", mod.caps(), tempfile.mkdtemp(prefix="rp-arch-"))
    check("a snapshot that stalled after half a page: the half is read, marked partial",
          dt < 26 and "ARCHIVE-PART" in (out[0] or "") and out[5].endswith(":partial"),
          "%.1f s %s" % (dt, out[5]))

    # ------------------------------------------------ one entry per browser that exists
    found = mod.browsers()
    paths = [os.path.normcase(os.path.realpath(b["path"])) for b in found if b.get("path")]
    check("no browser is listed twice", len(paths) == len(set(paths)), str([b.get("name") for b in found]))
    check("every listed browser has its program on disk",
          all(b.get("path") and os.path.exists(b["path"]) for b in found),
          str([(b.get("name"), b.get("path")) for b in found if not (b.get("path") and os.path.exists(b["path"]))]))
finally:
    s.stop()
    for srv in (slow, slow_text, slow_arch):
        srv.shutdown()

sys.exit(check.done())
