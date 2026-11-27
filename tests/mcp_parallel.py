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
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness import PUBLIC, Checks, cline_form, mcp_dir, mcp_said, mcp_status, serve     # noqa: E402

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


def fill_page():
    # text enough to fill the answer's block, and a picture in every part: with inline_images and screenshots the
    # notes and the picture stand-ins come on top of it (KNOWN-ISSUES 273)
    return ("<!doctype html><html><head><title>Fill</title></head><body><article><h1>Fill</h1>"
            + "".join("<h2>Part %d</h2><p>PART%d %s</p><p><img src='/m/%d.png' alt='Big picture %d'></p>"
                      % (i, i, EN * 4, i, i) for i in range(12)) + "</article></body></html>").encode()


PNG_H = {"Content-Type": "image/png"}
routes = {"/slow/%d" % i: slow for i in range(4)}
routes.update({"/trickle": trickle, "/pics": (200, H, pics_page()), "/many": (200, H, many_page()),
               "/fill": (200, H, fill_page()),
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
    ok_ids = sorted(r.get("id") for r in got if mcp_status(r.get("result")) == "ok")
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

    # ------------------------------------------------ the counted blocks of one result stay inside the block
    # (KNOWN-ISSUES 273). Cline counts a tool result's characters, MCP results too: its SDK counts the text of all the
    # blocks together and an image block as "[image attached]" (tool-result-cache.ts), then cuts the middle past
    # 8 000. So the text of every block together, an image as that word, stays within 7 900 UTF-16 units, 9 980
    # bytes and 495 lines.
    def counted(blocks):
        joined = "\n".join(b.get("text", "") if b.get("type") == "text" else "[image attached]" for b in blocks)
        return len(joined.encode("utf-16-le")) // 2, len(joined.encode("utf-8")), joined.count("\n")

    def with_screens(argv):
        # a page read with screenshots, the way a browser's capture leaves them: two tiles of 1280x1568 in shots/
        rc, out, e = real_run_cli(argv)
        man = json.loads(out)
        os.makedirs(os.path.join(man["dir"], "shots"), exist_ok=True)
        tiles = []
        for k in (1, 2):
            data = png(1280, 1568, (30 * k, 90, 120))
            with open(os.path.join(man["dir"], "shots", "%02d.png" % k), "wb") as fh:
                fh.write(data)
            tiles.append({"file": "shots/%02d.png" % k, "width": 1280, "height": 1568, "bytes": len(data),
                          "format": "png", "screens": [1, 2] if k == 1 else [3]})
        man["screenshots"] = tiles
        man.setdefault("signals", {}).update(screens=3, screens_needed=9)
        return rc, json.dumps(man, ensure_ascii=False), e

    real_run_cli = mcp.run_cli
    plain = mcp.tool_read_url({"url": s.url("/fill")})
    p_chars, p_bytes, p_lines = counted(plain["content"])
    check("a long page with no notes: its block is as long as ever (the baseline of what follows)",
          7000 < p_chars <= 7900 and p_bytes <= 9980, "%d chars, %d bytes, %d lines" % (p_chars, p_bytes, p_lines))
    try:
        mcp.run_cli = with_screens
        busy = mcp.tool_read_url({"url": s.url("/fill"), "inline_images": True, "screenshots": 3, "refresh": True})
    finally:
        mcp.run_cli = real_run_cli
    bb = busy.get("content") or []
    n_img = sum(1 for b in bb if b.get("type") == "image")
    notes = " ".join(b.get("text") or "" for b in bb if b.get("type") == "text" and (
        "not attached" in (b.get("text") or "") or "screen(s)" in (b.get("text") or "")))
    c_chars, c_bytes, c_lines = counted(bb)
    check("inline_images and screenshots: the notes and the pictures are there (the test is not empty)",
          n_img >= 4 and "not attached" in notes and "screen(s)" in notes and "of 9 the page has" in notes,
          "%d image blocks; %s" % (n_img, notes[:100]))
    check("... and the blocks together stay within 7 900 characters, 9 980 bytes and 495 lines "
          "(the text gave up the room the notes and the pictures take)",
          c_chars <= 7900 and c_bytes <= 9980 and c_lines <= 495,
          "%d chars, %d bytes, %d lines" % (c_chars, c_bytes, c_lines))
    check("... and the text gave up no more than it had to (not more than two paragraphs of it)",
          c_chars > p_chars - 2 * 700, "%d chars against %d without the notes" % (c_chars, p_chars))
    said = mcp_said(busy)
    nxt = re.search(r"── next: line (\d+) of \d+ ──\nread\(dir=\"[^\"]+\", file=\"content.md\", from=(\d+), chars=7900\)",
                    said)
    # the line above the text names no end (KNOWN-ISSUES 279): the block's lines are counted between that line and
    # next:, in the text blocks joined back (each is cut at a marker's end)
    rows = said.split("\n")
    top = next((i for i, ln in enumerate(rows) if ln.startswith("── content.md: from line 1 of ")), None)
    at_next = next((i for i, ln in enumerate(rows) if ln.startswith("── next: line ")), None)
    shown = at_next - top - 1 if top is not None and at_next is not None else None
    check("... the pointer is the line after the block's last one",
          nxt and shown and int(nxt.group(1)) == shown + 1 == int(nxt.group(2)),
          "%s %s" % (nxt and nxt.group(1), shown))
    more = mcp.tool_read({"dir": mcp_dir(busy), "from": int(nxt.group(1))}) if nxt else {}
    mt = mcp_said(more)
    check("... and read(dir, from=next) goes on from there",
          nxt and ("── content.md: from line %s of " % nxt.group(1)) in mt, mt[:120].replace("\n", " | "))
    again = mcp.tool_read_url({"url": s.url("/fill"), "inline_images": True})
    a_chars, a_bytes, a_lines = counted(again["content"])
    check("inline_images alone: within the block as well",
          a_chars <= 7900 and a_bytes <= 9980 and a_lines <= 495,
          "%d chars, %d bytes, %d lines" % (a_chars, a_bytes, a_lines))

    # ------------------------------------------------ the whole result as Cline's SDK runtime counts it
    # (KNOWN-ISSUES 275): the model gets the result object as JSON.stringify writes it, every block and every
    # escape of its text (a line's "\n" is two characters), an image as "[image attached]"; 8 000 is where it cuts.
    # The manifest is the folder's file, never a part of the result: as structuredContent it came on top (3.6 KB on
    # the 12-picture page, 10.8 KB on one of 60)
    man = json.load(open(os.path.join(mcp_dir(res), "manifest.json"), encoding="utf-8"))
    on_disk = [e["file"] for e in man.get("images") or [] if e.get("file")]
    pic = mcp.tool_read({"dir": mcp_dir(res), "file": on_disk[0]}) if on_disk else {}
    check("read(dir, file=\"img/...\"): the picture as an image block, its caption after it",
          [b.get("type") for b in pic.get("content") or []] == ["text", "image", "text"], str(on_disk[:1]))
    for name, r in (("a long page", plain), ("inline_images and screenshots", busy), ("inline_images", again),
                    ("12 big pictures, inline_images", res2), ("the pictures page, inline_images", res)):
        check("as Cline counts it (its JSON), %s: within 7 900 characters" % name, cline_form(r) <= 7900,
              "%d characters, %d image blocks" % (cline_form(r), sum(1 for b in r.get("content") or []
                                                                     if b.get("type") == "image")))
    check("no result carries structuredContent: a page, its pictures, its screens, a picture read",
          not [r for r in (plain, busy, again, res2, res, more, pic) if "structuredContent" in r]
          and all(sorted(r) == ["content", "isError"] for r in (plain, busy, again, res2, res, more, pic)),
          str(sorted({tuple(sorted(r)) for r in (plain, busy, again, res2, res, more, pic)}))[:120])
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
