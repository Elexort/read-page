"""The MCP server: parallel calls and picture blocks. No network.

    python -X utf8 tests/mcp_parallel.py

Every read_url runs in a child process, four at a time, and its answer is written whole; a
cancelled call's process tree is killed and the call gets no answer. With
inline_images only the content pictures become image blocks, right after their marker - not
decorations (3+ times on the page, 48 px or less, 1 KB or less) and not a logo, icon, avatar or
badge of 100 px or less; each one PNG or JPEG, its long side at most 1 568 px, at most 3.75 MB;
the whole answer inside 25 000 tokens (text plus ceil(w/28)*ceil(h/28) a picture), 256 pictures
and 20 MB. A read still running at HARD_SECONDS is stopped with a reason, and one whose
exit hung after it printed its answer keeps that answer.
"""
import base64
import importlib.util
import json
import math
import os
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness import PUBLIC, Checks, serve                    # noqa: E402

check = Checks()
SERVER = os.path.join(os.path.dirname(HERE), "scripts", "mcp_server.py")
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ")
H = {"Content-Type": "text/html; charset=utf-8"}


def png(w, h, rgb=(40, 80, 160), noise=False):
    if noise:
        raw = b"".join(b"\x00" + os.urandom(3 * w) for _ in range(h))
    else:
        raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def gif(w, h):
    try:
        from PIL import Image
        import io
        buf = io.BytesIO()
        # noise, not one colour: a one-colour GIF is under 1 KB, and that is a decoration
        Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).save(buf, "GIF")
        return buf.getvalue()
    except ImportError:
        return b""


def dims_of(b64, mime):
    b = base64.b64decode(b64)
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    if b[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            t = b[i + 1]
            if 0xC0 <= t <= 0xCF and t not in (0xC4, 0xC8, 0xCC):
                return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
            i += 2 + int.from_bytes(b[i + 2:i + 4], "big")
    return 0, 0


def slow(h):
    time.sleep(2.5)
    body = ("<html><head><title>Slow</title></head><body><article><h1>Slow</h1><p>SLOW-PAGE " + EN * 6
            + "</p></article></body></html>").encode()
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)
    h.close_connection = True


gone = {}


def trickle(h):
    """A byte every 0.3 s for a minute; notes when the reader on the other end is gone."""
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", "100000")
    h.end_headers()
    try:
        for _ in range(200):
            h.wfile.write(b"<p>x</p>")
            h.wfile.flush()
            time.sleep(0.3)
    except OSError:
        gone["at"] = time.time()
    h.close_connection = True


def pics_page():
    icon = "<img src='/i/icon.png' alt='ok' width='16' height='16'>"
    return ("<!doctype html><html><head><title>Rack</title></head><body><article><h1>Rack</h1>"
            "<p>ONE " + EN * 3 + icon + "</p><p><img src='/i/photo.png' alt='Photo of the rack'></p>"
            "<p>TWO " + EN * 3 + icon + "</p><p><img src='/i/logo.png' alt='Company logo'></p>"
            "<p>THREE " + EN * 3 + icon + "</p><p><img src='/i/wide.png' alt='Wide timeline'></p>"
            "<p>FOUR " + EN * 3 + "</p><p><img src='/i/anim.gif' alt='Animated chart'></p>"
            "<p>FIVE " + EN * 3 + "</p><p><img src='/i/noise.png' alt='Noise field'></p>"
            "<p>SIX " + EN * 3 + "</p></article></body></html>").encode()


def many_page():
    return ("<!doctype html><html><head><title>Many</title></head><body><article><h1>Many</h1>"
            + "".join("<p>PART%d %s</p><p><img src='/m/%d.png' alt='Big picture %d'></p>" % (i, EN * 2, i, i)
                      for i in range(12)) + "</article></body></html>").encode()


PNG_H = {"Content-Type": "image/png"}
routes = {"/slow/%d" % i: slow for i in range(4)}
routes.update({"/trickle": trickle, "/pics": (200, H, pics_page()), "/many": (200, H, many_page()),
               "/i/icon.png": (200, PNG_H, png(16, 16, (0, 160, 0))),
               "/i/photo.png": (200, PNG_H, png(600, 400)),
               "/i/logo.png": (200, PNG_H, png(90, 40, (10, 10, 10))),
               "/i/wide.png": (200, PNG_H, png(3000, 200, (90, 20, 20))),
               "/i/anim.gif": (200, {"Content-Type": "image/gif"}, gif(300, 200)),
               "/i/noise.png": (200, PNG_H, png(1500, 1500, noise=True))})
routes.update({"/m/%d.png" % i: (200, PNG_H, png(1400, 1400, (i * 20, 60, 90))) for i in range(12)})
s = serve(routes)
env = dict(os.environ, READ_PAGE_TEST_PUBLIC_HOST=PUBLIC, READ_PAGE_SKIP="browser",
           READ_PAGE_CACHE=tempfile.mkdtemp(prefix="rp-mcp-par-"))
for k in ("FIRECRAWL_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "JINA_API_KEY"):
    env.pop(k, None)
proc = subprocess.Popen([sys.executable, "-X", "utf8", SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, env=env)
lines = queue.Queue()


def pump():
    for line in proc.stdout:
        lines.put(line)
    lines.put(None)


threading.Thread(target=pump, daemon=True).start()


def send(msg):
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def take(timeout):
    try:
        line = lines.get(timeout=timeout)
    except queue.Empty:
        return None
    return json.loads(line) if line else None


try:
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "par", "version": "0"}}})
    take(30)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    # ------------------------------------------------ four calls at once
    t0 = time.monotonic()
    for i in range(4):
        send({"jsonrpc": "2.0", "id": 11 + i, "method": "tools/call",
              "params": {"name": "read_url", "arguments": {"url": s.url("/slow/%d" % i)}}})
    got = []
    while len(got) < 4:
        r = take(60)
        if r is None:
            break
        got.append(r)
    dt = time.monotonic() - t0
    ok_ids = sorted(r.get("id") for r in got if (r.get("result") or {}).get("structuredContent", {}).get("status") == "ok")
    check("four read_url calls run at once (each page takes 2.5 s)",
          ok_ids == [11, 12, 13, 14] and dt < 9.5,    # one after another they take 4 x 2.5 s = 10 s and more; 8.4 s on a macOS Intel runner
          "%.1f s, answered %s" % (dt, ok_ids))

    # ------------------------------------------------ a cancelled call is killed and gets no answer
    send({"jsonrpc": "2.0", "id": 21, "method": "tools/call",
          "params": {"name": "read_url", "arguments": {"url": s.url("/trickle")}}})
    time.sleep(2.0)
    cancelled_at = time.time()
    send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 21, "reason": "test"}})
    send({"jsonrpc": "2.0", "id": 22, "method": "ping"})
    r = take(15)
    check("after a cancel the next answer is the ping's, not the cancelled call's",
          r is not None and r.get("id") == 22, str(r)[:80])
    deadline = time.time() + 8
    while "at" not in gone and time.time() < deadline:
        time.sleep(0.1)
    check("the cancelled call's process is killed (the page sees its reader go)",
          "at" in gone and gone["at"] - cancelled_at < 6,
          "%.1f s after the cancel" % (gone["at"] - cancelled_at) if "at" in gone else "still reading")
    r = take(3)
    check("the cancelled call never answers", r is None or r.get("id") != 21, str(r)[:80])
finally:
    try:
        proc.stdin.close()
        proc.wait(timeout=20)
    except Exception:                                         # noqa: BLE001
        proc.kill()

# ------------------------------------------------ which pictures become image blocks
os.environ.update({"READ_PAGE_TEST_PUBLIC_HOST": PUBLIC, "READ_PAGE_SKIP": "browser",
                   "READ_PAGE_CACHE": tempfile.mkdtemp(prefix="rp-mcp-inl-")})
spec = importlib.util.spec_from_file_location("mcp_par", SERVER)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)
try:
    import PIL  # noqa: F401
    pillow = True
except ImportError:
    pillow = False
try:
    res = mcp.tool_read_url({"url": s.url("/pics"), "inline_images": True})
    blocks = res.get("content") or []
    imgs = [(i, b) for i, b in enumerate(blocks) if b.get("type") == "image"]
    before = {i: (blocks[i - 1].get("text") or "") for i, _ in imgs}
    names = [before[i].strip().split()[-1] if before[i].strip() else "" for i, _ in imgs]
    check("decorations stay markers: the 16 px icon used 3 times, the 90 px logo",
          not any("ok" in n or "logo" in n for n in names), str(names))
    check("each image block comes right after its marker", all("[img #" in before[i] for i, _ in imgs),
          str([before[i][-60:] for i, _ in imgs][:2]))
    check("only PNG or JPEG goes in", all(b.get("mimeType") in ("image/png", "image/jpeg") for _, b in imgs),
          str({b.get("mimeType") for _, b in imgs}))
    sizes = {n: dims_of(b["data"], b.get("mimeType")) for n, (_, b) in zip(names, imgs)}
    check("no picture is longer than 1 568 px", all(max(d) <= 1568 for d in sizes.values()), str(sizes))
    weights = {n: len(base64.b64decode(b["data"])) for n, (_, b) in zip(names, imgs)}
    check("no picture is heavier than 3.75 MB", all(w <= 3.75 * 1024 * 1024 for w in weights.values()),
          str(weights))
    if pillow:
        check("with Pillow a wide picture is scaled to 1 568 px, a GIF becomes PNG, a heavy PNG JPEG",
              any("wide" in n and sizes[n][0] == 1568 for n in names) and any("animated" in n for n in names)
              and any("noise" in n for n, (_, b) in zip(names, imgs) if b.get("mimeType") == "image/jpeg"),
              "%s" % sorted(sizes))
    else:
        check.skip("scaling and converting", "Pillow is not installed here")
    check("the content photo is there", any("photo-of-the-rack" in n for n in names), str(names))

    res2 = mcp.tool_read_url({"url": s.url("/many"), "inline_images": True})
    b2 = res2.get("content") or []
    text_bytes = sum(len((b.get("text") or "").encode()) for b in b2 if b.get("type") == "text")
    pics = [dims_of(b["data"], b.get("mimeType")) for b in b2 if b.get("type") == "image"]
    tokens = text_bytes / 3.0 + sum(math.ceil(w / 28.0) * math.ceil(h / 28.0) + 150 for w, h in pics)
    note = " ".join(b.get("text") or "" for b in b2 if b.get("type") == "text" and "not attached" in (b.get("text") or ""))
    check("the whole answer stays inside 25 000 tokens; the rest stay markers and are counted",
          0 < len(pics) < 12 and tokens <= 25000 and "not attached" in note,
          "%d pictures, ~%d tokens; %s" % (len(pics), tokens, note[:70]))
finally:
    s.close()

# ------------------------------------------------ the server's backstop (HARD_SECONDS), in process:
# a stand-in readpage.py that answers and then hangs, or only hangs
spec = importlib.util.spec_from_file_location("rp_mcp_hard", SERVER)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)
fake = tempfile.mkdtemp(prefix="rp-mcp-hard-")
with open(os.path.join(fake, "readpage.py"), "w", encoding="utf-8") as fh:
    fh.write("import sys, time\n"
             "if '--say' in sys.argv:\n"
             "    sys.stdout.write('read-page \\u00b7 ok \\u00b7 the answer\\n')\n"
             "    sys.stdout.flush()\n"
             "time.sleep(60)\n")
srv.HERE, srv.HARD_SECONDS, srv.spare_start = fake, 2, (lambda: None)
t0 = time.monotonic()
said = srv.run_cli(["--say", "http://example.test/"])
dt = time.monotonic() - t0
check("backstop: a read whose exit hangs after its answer keeps that answer",
      said[0] == 0 and said[1].startswith("read-page · ok") and dt < 15, "%s in %.1f s" % (str(said)[:80], dt))
t0 = time.monotonic()
said = srv.run_cli(["http://example.test/"])
dt = time.monotonic() - t0
check("backstop: a read that never ends is stopped at HARD_SECONDS, with the reason",
      said[0] == 1 and "did not end in 2 s" in said[2] and dt < 15, "%s in %.1f s" % (str(said)[:80], dt))

sys.exit(check.done())
