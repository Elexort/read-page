#!/usr/bin/env python3
"""MCP frontend for read-page: two tools over the same core, stdio JSON-RPC.

    python -X utf8 mcp_server.py

Tools (the same names as the CLI flags):
  read_url(url, allow_external?, force_external?, alternate?, download?, deny_images?,
           screenshots?, inline_images?, refresh?, clear_cookies?, file?, from?)
      -> the answer the CLI prints (header, outline, text block, next line) + image blocks
  read(dir, file="content.md", from=1)
      -> the block of a saved file that starts at that line; images are shown, binaries described

The answer budget lives in answer.py, the download cap and the timeouts in readpage.py; this
file never repeats them, so the CLI and the MCP server cannot drift apart.

Stdlib only: no SDK. Logic lives in readpage.py; this file is a thin adapter. Each read_url runs
readpage.py in a child process, four at a time; notifications/cancelled kills that process tree.
Which pictures become image blocks is decided in content_blocks.
Never prints anything to stdout except JSON-RPC messages.
"""
import base64
import importlib.util
import io
import json
import math
import os
import re
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_VERSION = "0.4.6"
PROTOCOL = "2025-06-18"

# no compiled readpage beside the scripts (some harnesses list every file of a skill's folder to the
# agent); readpage then points the cache of its own modules and of every read's process out of it
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
# The wire is UTF-8 (JSON-RPC's), whatever the locale: a Chinese Windows reads standard input as GBK unless Python
# was started with -X utf8, and the JSON line of a client's config rarely says so - a Chinese URL or folder
# arrived as other characters. Before anything is read or written, and not as a side effect of an import. A
# UTF-8 BOM before the first line (a file saved with one, piped in) is dropped: that line was no JSON.
for _stream, _kw in ((sys.stdin, {"encoding": "utf-8-sig"}), (sys.stdout, {"encoding": "utf-8", "newline": "\n"})):
    try:
        _stream.reconfigure(errors="replace", **_kw)
    except (AttributeError, OSError, ValueError):
        pass
import ownenv                        # noqa: E402
if __name__ == "__main__":
    # the skill's own environment (readpage.py --setup): the server, and so every read it starts,
    # runs under its Python
    ownenv.use(__file__, sys.argv[1:])
_spec = importlib.util.spec_from_file_location("readpage", os.path.join(HERE, "readpage.py"))
readpage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(readpage)

answer = readpage.answer             # one answer contract for the CLI and the MCP server

# What one answer may carry - the limits someone enforces, the worst adequate case among
# clients with a 1M context; three groups, the first one reached cuts. The text has its own limits
# (answer.py). Measured in Claude Code 2.1.317: a picture counts
# ceil(w/28)*ceil(h/28) tokens plus a path line it adds itself, and going over keeps the pictures
# but tells the model "OUTPUT TRUNCATED", so the answer stays below.
IMG_SIDE = 1568                       # px, the long side: a longer picture is scaled, its proportions kept
IMG_BYTES = int(3.75 * 1024 * 1024)   # Claude on Bedrock takes 5 MB of base64
ANSWER_TOKENS = 25000                 # Claude Code's MCP output limit, text and pictures together
PATH_LINE_TOKENS = 150                # the line with a picture's path that Claude Code adds
ANSWER_PICTURES = 256                 # Qwen 3.6-plus, for the whole request
ANSWER_BYTES = 20 * 1024 * 1024       # Gemini, the whole request with its text
DECOR_SIDE, DECOR_BYTES, DECOR_REPEAT = 48, 1024, 3
# What the blocks of one result may come to together (`counted`): the answer's own block, the text with the notes
# after it and a stand-in for each image. The keywords are answer.render's.
LIMITS = {"chars": answer.BUDGET_CHARS, "budget": answer.BUDGET_BYTES, "max_lines": answer.BUDGET_LINES}
IMAGE_STANDIN = "[image attached]"
NAMED_SIDE = 100
NAMED = re.compile(r"(?i)logo|icon|avatar|badge|sprite|favicon|emoji|gravatar|spinner")

# a picture's marker: `[img #3 · 100x80 3K · alt] img/03-alt.png`; its middle holds no "[img #" (a run of
# them that no "]" closed was scanned to the end of the line from each, as pictures.MARK was)
ANY_MARKER = re.compile(r"\[img #(\d+) · %s\] (img/\S+)" % readpage.pictures.MARK_BODY)
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
        ".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml",
        ".avif": "image/avif", ".ico": "image/x-icon", ".tif": "image/tiff",
        ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".flac": "audio/flac", ".mp4": "video/mp4", ".webm": "video/webm"}

TOOLS = [
    {
        "name": "read_url",
        "description": (
            "Read the actual content of a URL or online document (web page, PDF, DOCX, PPTX, XLSX, "
            "EPUB, audio, video, image). Returns a header (status, engine, size, where the files are, "
            "what to do), then the text: whole when it fits in ~7 900 characters, otherwise an outline with line "
            "numbers, the first block and the line to continue from (read with that dir and from=N). "
            "Pictures stand in the text as markers [img #3 · 600x400 4K · alt] img/03-alt.png; with "
            "inline_images=true the content pictures also come back as image blocks right after their "
            "markers. A URL that serves a single image returns that image at once. Never returns a "
            "partial page silently."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http(s) URL of a page or document"},
                "allow_external": {"type": "boolean", "default": False,
                                   "description": "the URL is public: public readers and archives may be used if local engines fail"},
                "force_external": {"type": "boolean", "default": False,
                                   "description": "use a public reader even when the local text looks complete (implies allow_external)"},
                "alternate": {"type": "boolean", "default": False,
                              "description": "re-read locally by other means: browser and every extractor, keep the best"},
                "deny_images": {"type": "boolean", "default": False,
                                "description": "download no picture; the markers say not downloaded and keep the address"},
                "screenshots": {"type": ["boolean", "integer"], "default": 0,
                                "description": "also return the page as images: the first N screens of a "
                                               "1280x784 window (true means 2), two glued into one "
                                               "1280x1568 picture when Pillow or PyMuPDF is there. Not for "
                                               "archives; a two-screen picture is ~2 700 tokens."},
                "inline_images": {"type": "boolean", "default": False,
                                  "description": "attach the text's content pictures as image blocks, each right after its "
                                                 "marker (not icons, logos or decorations); the answer stays inside "
                                                 "25 000 tokens. Leave it off with a context under 1M tokens or a "
                                                 "provider that takes 1-3 images a request (Llama 4 on Bedrock, "
                                                 "Vertex, Azure): the markers name the files either way"},
                "refresh": {"type": "boolean", "default": False,
                            "description": "ignore the 15-minute page cache"},
                "clear_cookies": {"type": "boolean", "default": False,
                                  "description": "forget this site's stored cookies before reading (they otherwise live 6 hours)"},
                "download": {"type": "boolean", "default": False,
                             "description": "no size and no time limit, every picture of the page; only free disk space stops it"},
                "file": {"type": "string", "enum": ["content.md", "page.md"],
                         "description": "which text to answer with: content.md (the text, default) or page.md (the whole page)"},
                "from": {"type": ["integer", "string"], "minimum": 1,
                         "description": "start the text at this line of the saved copy (no network), or at the line "
                                        "that holds this piece of text (a quote, a heading, a marker such as "
                                        "\"[tab · Plans]\" or \"[img #3]\"); the answer names the next line"},
                "to": {"type": "integer", "minimum": 1,
                       "description": "with from: the lines up to this one, more than one block if need be, for a "
                                      "client that shows that much; the answer says they were sent and how to go on "
                                      "if they were cut"},
                "ocr": {"type": "integer", "minimum": 1,
                        "description": "answer with the text drawn in picture N (the number on its marker) instead "
                                       "of the page's text: for a model that cannot see pictures"},
                "probe": {"type": "integer", "minimum": 0,
                          "description": "for testing a client, not for reading: answer with N characters of numbered "
                                         "lines and nothing else, no network (the url is not read). url=\"probe:N\" is "
                                         "a page of them, answered the normal way (with from and to)"},
                "probe_units": {"type": "integer", "minimum": 0,
                                "description": "for testing a client, not for reading: like probe, but each line says how "
                                               "many characters, UTF-16 units and bytes stand before it, and its filler "
                                               "is ASCII, Cyrillic, CJK and a character past U+FFFF, so the last line a "
                                               "client shows says which of the three it counts"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "read",
        "description": (
            "Read a file left on disk by read_url: content.md, page.md (the full page text, a "
            "superset of content.md), manifest.json (the machine-readable result) or a media file "
            "(img/..., raw.jpg, ...); with no file, the text read last. Text comes in "
            "blocks of ~7 900 characters starting at line `from`, each naming the next line; an image is "
            "returned as an image block; audio and video only get their metadata."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "the folder on the files: line of the read_url answer"},
                "file": {"type": "string",
                         "description": "content.md, page.md, manifest.json, or img/...; without it, "
                                        "the text read last"},
                "from": {"type": ["integer", "string"], "minimum": 1, "default": 1,
                         "description": "the line to start at (the answer names the next one), or a piece of "
                                        "text: the first line holding it"},
                "to": {"type": "integer", "minimum": 1,
                       "description": "the last line: the lines from `from` up to it, more than one block if need be"},
                "ocr": {"type": "boolean", "default": False,
                        "description": "for a picture (img/...): its text instead of the image, for a model "
                                       "that cannot see pictures"},
            },
            "required": ["dir"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
]


def log(*a):
    sys.stderr.write("read-page-mcp: " + " ".join(str(x) for x in a) + "\n")
    sys.stderr.flush()


# Calls at once: each read_url runs readpage.py in a child process: its stdout is its own, so
# four calls at once cannot swap answers (redirect_stdout is one global and would catch another
# call's manifest), and a cancelled call is a process tree to kill. Answers go out whole, one line
# each, under a lock.
CALLS = 4
HARD_SECONDS = 58               # a read stops itself at 55 s; past this the server stops it
_SLOTS = threading.BoundedSemaphore(CALLS)
_OUT = threading.Lock()
_CALLS = {}                     # request id -> {"proc": the child, "cancelled": bool}
_CALLS_LOCK = threading.Lock()
_CTX = threading.local()        # the request this thread answers


def write(resp):
    with _OUT:
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


_POPEN_KW = ({"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)} if os.name == "nt"
             else {"start_new_session": True})
_SPARE = {"p": None}
_SPARE_LOCK = threading.Lock()


def spare_start():
    """Keep one readpage process ready for the next call: Python started and the
    imports done, curl_cffi among them - about 0.5 s of a call on a 20-core Windows machine and 2 s on a weak laptop. It
    serves one call and exits (readpage.serve_once), so no state passes from one read to the next;
    a new one starts as each is taken. It costs an idle Python's memory and no CPU."""
    with _SPARE_LOCK:
        p = _SPARE["p"]
        if p is not None and p.poll() is None:
            return
        try:
            _SPARE["p"] = subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(HERE, "readpage.py"),
                                            "--serve-once"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, **_POPEN_KW)
        except OSError as e:
            _SPARE["p"] = None
            log("no spare: %s" % e)


def spare_take(argv):
    """The spare with this call's arguments on its stdin, or None (none ready, or it died)."""
    with _SPARE_LOCK:
        p, _SPARE["p"] = _SPARE["p"], None
    if p is None or p.poll() is not None:
        return None
    try:
        p.stdin.write((json.dumps([str(a) for a in argv]) + "\n").encode("utf-8"))
        p.stdin.close()
    except (OSError, ValueError):
        readpage.kill_tree(p)
        return None
    p.stdin = None                     # fed and closed: communicate() only reads
    return p


def run_cli(argv):
    """readpage.py in a child process: (exit code, stdout, error). It is registered under the
    request this thread answers, so notifications/cancelled can kill it with all it started."""
    cmd = [sys.executable, "-X", "utf8", os.path.join(HERE, "readpage.py")] + list(argv)
    mid = getattr(_CTX, "mid", None)
    with _CALLS_LOCK:
        entry = _CALLS.get(mid)
        if entry is not None and entry.get("cancelled"):
            return 1, "", "cancelled"
        p = spare_take(argv)
        if p is None:
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 **_POPEN_KW)
        if entry is not None:
            entry["proc"] = p
    threading.Thread(target=spare_start, daemon=True).start()     # the next call's
    # the read ends itself by its 55 s deadline; this is the backstop for a stuck one, still under
    # the ~60 s at which harnesses cancel a call (none with --download, which has no deadline)
    try:
        out, err = p.communicate(timeout=None if "--download" in argv else HARD_SECONDS)
    except subprocess.TimeoutExpired:
        readpage.kill_tree(p)
        late = b""
        try:
            late = p.communicate(timeout=5)[0] or b""
        except Exception:                                    # noqa: BLE001
            pass
        if late.strip():
            # the answer was out (finish flushes it) and the exit hung after it: that answer stands
            return 0, late.decode("utf-8", "replace"), ""
        return 1, "", "the read did not end in %d s and was stopped; try again, or the CLI" % HARD_SECONDS
    if entry is not None and entry.get("cancelled"):
        return 1, "", "cancelled"
    said = out.decode("utf-8", "replace")
    if p.returncode == 2:
        return 2, "", err.decode("utf-8", "replace").strip()[-400:] or "a wrong call"
    if not said.strip():
        return 1, "", "readpage exited %s: %s" % (p.returncode, err.decode("utf-8", "replace").strip()[-300:])
    return p.returncode, said, ""


def cancel(rid):
    """notifications/cancelled: the call's process tree is killed, and the call gets no answer."""
    with _CALLS_LOCK:
        entry = _CALLS.get(rid)
        if entry is None:
            return
        entry["cancelled"] = True
        p = entry.get("proc")
    if p is None or p.poll() is not None:
        return
    if os.name == "nt":
        readpage.kill_tree(p)                   # taskkill /T follows the whole tree
        return
    # POSIX: readpage starts curl and the converters in sessions of their own, out of reach of a
    # kill aimed at its group; on SIGTERM it kills them itself, then goes (readpage._on_term)
    import signal
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except OSError:
        pass
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        readpage.kill_tree(p)


def answer_call(msg):
    """One read_url call in its own thread: at most CALLS at once, the answer written whole."""
    mid = msg.get("id")
    with _CALLS_LOCK:
        _CALLS[mid] = {"proc": None, "cancelled": False}
    try:
        with _SLOTS:
            _CTX.mid = mid
            if _CALLS[mid]["cancelled"]:
                return
            try:
                resp = handle(msg)
            except Exception as e:                            # noqa: BLE001
                resp = {"jsonrpc": "2.0", "id": mid,
                        "error": {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}}
            if resp is not None and not _CALLS[mid]["cancelled"]:
                write(resp)
    finally:
        _CTX.mid = None
        with _CALLS_LOCK:
            _CALLS.pop(mid, None)


def result(blocks, structured, is_error=False):
    return {"content": blocks, "structuredContent": structured, "isError": is_error}


def text(t):
    return {"type": "text", "text": t}


def err(msg):
    return result([text("read-page · error · " + msg)], {"status": "error", "error": msg}, True)


def picture_tokens(w, h):
    return int(math.ceil(w / 28.0) * math.ceil(h / 28.0)) + PATH_LINE_TOKENS


def content_picture(e, uses):
    """Worth an image block - not a decoration (3+ times on the page, 48 px or less,
    1 KB or less) and not a logo, icon, avatar or badge of 100 px or less. A wrong guess costs one
    `read` of the file, which the marker names."""
    m = re.match(r"(\d+)x(\d+)$", str(e.get("dims") or ""))
    side = max(int(m.group(1)), int(m.group(2))) if m else 0
    if uses.get(e.get("n"), 0) >= DECOR_REPEAT or int(e.get("bytes") or 0) <= DECOR_BYTES:
        return False
    if side and side <= DECOR_SIDE:
        return False
    named = " ".join(str(e.get(k) or "") for k in ("file", "alt", "url"))
    return not (side and side <= NAMED_SIDE and NAMED.search(named))


def sniff(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    head = data[:4096].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith((b"<?xml", b"<!--")) and b"<svg" in head):
        return "svg"
    return "other"


def inline_image(path):
    """(bytes, mime, w, h) for an image block, or (None, why). PNG or JPEG only (xAI takes no other);
    a long side above 1 568 px is scaled down, which also keeps the 8 000 px limit and the ~2 000 px
    of a request with many pictures; a PNG over 3.75 MB after that becomes one JPEG at q95 (the worst
    case, 1568x1568 of noise, is 2.88 MB; no search, no second pass). Pillow converts and scales,
    PyMuPDF renders SVG; without them only a PNG or JPEG that already fits goes in."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        return None, str(e)
    kind = sniff(data)
    w, h = readpage._img_dims(data)
    if kind in ("png", "jpeg") and w and h and max(w, h) <= IMG_SIDE and len(data) <= IMG_BYTES:
        return data, "image/" + kind, w, h
    if kind == "svg":
        try:
            import pymupdf
            doc = pymupdf.open(stream=data, filetype="svg")
            r = doc[0].rect
            zoom = min(1.0, IMG_SIDE / max(r.width, r.height, 1.0))
            data = doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True).tobytes("png")
            kind = "png"
            w, h = readpage._img_dims(data)
            if w and h and max(w, h) <= IMG_SIDE and len(data) <= IMG_BYTES:
                return data, "image/png", w, h
        except ImportError:
            return None, "an SVG needs PyMuPDF to become PNG (pip install pymupdf)"
        except Exception as e:                                # noqa: BLE001
            return None, "the SVG did not render (%s)" % type(e).__name__
    try:
        from PIL import Image
    except ImportError:
        return None, ("a %s needs Pillow to become PNG (pip install pillow)" % kind.upper()
                      if kind not in ("png", "jpeg") else
                      "over %d px or 3.75 MB, and Pillow is not installed to scale it" % IMG_SIDE)
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode not in ("RGB", "RGBA", "L", "LA"):
            im = im.convert("RGBA" if ("transparency" in im.info or im.mode in ("P", "PA")) else "RGB")
        if max(im.size) > IMG_SIDE:
            f = IMG_SIDE / float(max(im.size))
            im = im.resize((max(1, round(im.size[0] * f)), max(1, round(im.size[1] * f))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG", compress_level=6)          # level 9 and optimize: no gain, 3x slower
        out, mime = buf.getvalue(), "image/png"
        if len(out) > IMG_BYTES:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=95)
            out, mime = buf.getvalue(), "image/jpeg"
        return out, mime, im.size[0], im.size[1]
    except Exception as e:                                    # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:60])


def image_block(path, dims=None):
    """(block, caption) for an image file, converted where it must be (inline_image), or (None,
    why it could not be attached)."""
    got = inline_image(path)
    if got[0] is None:
        return None, got[1]
    data, mime, w, h = got
    try:
        size = os.path.getsize(path)
    except OSError:
        size = len(data)
    caption = "[%dx%d %s] %s" % (w, h, readpage.human_bytes(size), os.path.basename(path))
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime}, caption


# ---------------------------------------------------------------- content assembly

def content_blocks(workdir, body, inline=True, images=None, tiles=None, uses=None, converted=None):
    """The answer as MCP blocks: its text, and with inline_images an image block right after the
    line that holds a picture's marker, in reading order. The marker stays in the
    text: a client that shows no image still has the path.

    Which pictures: the screenshots asked for first, then the content pictures (content_picture),
    the biggest first, while the answer stays inside 25 000 tokens, 256 pictures and 20 MB. A
    picture that did not fit keeps its marker, and a note counts it. The text is already inside
    its own budget (answer.render), so nothing is cut here. `converted` keeps what inline_image made of
    each file, for a caller that asks again with another text.
    """
    state = {"attached": 0, "skipped": 0, "count": 0, "bytes": 0, "why": {},
             "tokens": len((body or "").encode("utf-8")) / 3.0}

    def take(path):
        if converted is None:
            got = inline_image(path)
        else:
            got = converted.get(path) or converted.setdefault(path, inline_image(path))
        if got[0] is None:
            return None, got[1]
        data, mime, w, h = got
        cost, b64 = picture_tokens(w, h), (len(data) + 2) // 3 * 4
        if (state["tokens"] + cost > ANSWER_TOKENS or state["count"] + 1 > ANSWER_PICTURES
                or state["bytes"] + b64 > ANSWER_BYTES):
            return None, "the answer's limit"
        state["tokens"] += cost
        state["bytes"] += b64
        state["count"] += 1
        return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime}, (w, h)

    shots = []
    for e in tiles or []:
        block, info = take(os.path.join(workdir, (e.get("file") or "").replace("/", os.sep)))
        shots.append((e, block, info))
    chosen = {}
    if inline:
        printed = {int(n) for n, _rel in ANY_MARKER.findall(body or "")}
        cands = [e for e in images or [] if e.get("file") and e.get("n") in printed
                 and content_picture(e, uses or {})]

        def area(e):
            m = re.match(r"(\d+)x(\d+)$", str(e.get("dims") or ""))
            return int(m.group(1)) * int(m.group(2)) if m else 0

        for e in sorted(cands, key=area, reverse=True):     # the biggest first, placed in order
            block, info = take(os.path.join(workdir, e["file"].replace("/", os.sep)))
            if block:
                chosen[e["n"]] = block
            else:
                state["why"][e["n"]] = info
        state["skipped"] = len(state["why"])
    # each picture right after its own marker, several on one line too (a gallery row): the text
    # is cut at the end of the marker, the picture follows, the line goes on in the next block
    blocks, pending, done, pos = [], "", set(), 0
    body = body or ""
    for m in ANY_MARKER.finditer(body):
        n = int(m.group(1))
        if n not in chosen or n in done:
            continue
        blocks.append(text(pending + body[pos:m.end()]))
        pending, pos = "", m.end()
        blocks.append(chosen[n])
        done.add(n)
        state["attached"] += 1
    if body[pos:]:
        blocks.append(text(body[pos:]))
    return blocks, state, shots


def result_blocks(manifest, said, workdir, inline, images, tiles, uses, shots, converted):
    """All the blocks of a read_url answer: the text with its pictures (content_blocks), then what the server
    says after it - the pictures it could not attach, the screens - and the screens' own images. A single image or
    sound the URL served comes after the text. (blocks, state)."""
    status = manifest.get("status") or "error"
    files = manifest.get("files") or {}
    blocks, state, shots_done = content_blocks(workdir, said, inline, images, tiles, uses, converted)
    if status == "media_only":
        media = ownenv.fs_path(files.get("media") or "")
        kind = (manifest.get("content") or {}).get("kind") or ""
        if media and kind == "image":
            # single-file endpoint: the point is to see the picture in one hop, not to read a path
            block, caption = image_block(media)
            if block:
                blocks.append(block)
                state["attached"] = 1
            else:
                blocks.append(text("the image could not be attached: " + caption))
        elif media and kind == "audio" and os.environ.get("READ_PAGE_MCP_MEDIA", "off") == "audio":
            try:
                data = open(media, "rb").read()
                if len(data) <= IMG_BYTES:
                    blocks.append({"type": "audio", "data": base64.b64encode(data).decode("ascii"),
                                   "mimeType": MIME.get(os.path.splitext(media)[1].lower(), "audio/mpeg")})
            except OSError:
                pass
        return blocks, state
    if state.get("skipped"):
        whys = sorted(set(state["why"].values()))
        blocks.append(text("[read-page] %d picture(s) not attached (%s); their markers name the files"
                           % (state["skipped"], "; ".join(whys)[:200])))
    if tiles:
        sig = manifest.get("signals") or {}
        taken = sig.get("screens") or len(tiles)
        total = max(taken, sig.get("screens_needed") or 0)
        more = "" if total <= taken else (" of %d the page has; ask for more with "
                                          "screenshots=N" % total)
        blocks.append(text("[read-page] %d screen(s)%s in %d image(s), %d px wide, not scaled"
                           % (taken, more, len(tiles), tiles[0].get("width") or 1280)))

        def which(e):
            sc = e.get("screens") or []
            return ("screens %d-%d" % (sc[0], sc[-1]) if len(sc) > 1 else
                    "screen %d" % sc[0] if sc else "screenshot") + " of %d" % total
        for e, block, info in shots_done:
            if not block:
                blocks.append(text("%s not attached: %s" % (which(e), info)))
                continue
            blocks.append(text("%s · %sx%s · %s"
                               % (which(e), e.get("width"), e.get("height"),
                                  readpage.human_bytes(e.get("bytes")))))
            blocks.append(block)
            state["attached"] += 1
    elif shots:
        why = ((manifest.get("signals") or {}).get("screenshot_unsupported")
               or (manifest.get("missing") and "browser")
               or "")
        if why:
            blocks.append(text("[read-page] no screenshots: %s" % why))
    return blocks, state


def counted(blocks):
    """What a client that counts a result's characters sees of its blocks. Cline's SDK, which cuts a tool
    result's middle past 8 000 characters, MCP results too, counts the text of all the blocks together and an
    image block as `[image attached]` (session/services/tool-result-cache.ts, read 2026-11-27): so the text of
    every block, an image as that, one to a line - a little more than the client counts. As answer.render's
    keywords: UTF-16 units, bytes, lines."""
    joined = "\n".join(b.get("text", "") if b.get("type") == "text" else IMAGE_STANDIN for b in blocks)
    return {"chars": answer.u16(joined), "budget": len(joined.encode("utf-8")), "max_lines": joined.count("\n")}


def mcp_next(n, total, view):
    return '── next: line %d of %d → read(dir, file="%s", from=%d) ──' % (n, total, view, n)


def mcp_call(frm, view, to=None):
    # a `to` answer's ways on: the next range, or a quote of the last line seen before a cut
    return 'read(dir, file="%s", from=%s%s)' % (view, frm, ", to=%d" % to if to else "")


def line_args(args, ignored):
    """`from` and `to` as the CLI takes them: (start, to, quote). `from` is a line number or words of a
    line - the quote, which the text resolves (readpage.start_of); a value it cannot use is left out and
    named."""
    raw, quote = args.get("from"), ""
    try:
        start = int(raw or 1)
    except (TypeError, ValueError):
        start = 1
        if isinstance(raw, str) and raw.strip():
            quote = raw
        else:
            ignored.append("from %s (a line number, or words of a line)" % raw)
    if start < 1:
        ignored.append("from %d (a line number, 1 or more)" % start)
        start = 1
    to = None
    if args.get("to") not in (None, "", 0, False):
        try:
            to = int(args.get("to"))
        except (TypeError, ValueError):
            ignored.append("to %s (a line number)" % args.get("to"))
        if to is not None and to < start:
            ignored.append("to %d (before from %d)" % (to, start))
            to = None
    return start, to, quote


def quote_start(workdir, manifest, view, quote, to):
    """A quote's line in the text (None: no line holds it), and `to` left out when it comes before that line
    (the CLI, given the same, names it on its `ignored:` line)."""
    start = readpage.start_of(workdir, manifest, view, quote)
    return start, (None if start is not None and to is not None and to < start else to)


def line_count(body):
    return len(body.split("\n")) - (1 if body.endswith("\n") else 0) if body else 0


def tool_read_url(args):
    # what this call has that read_url cannot use is left out, and the answer says so: the read goes
    # on, as the CLI's does (a model once invented --to from --from and lost the whole call); a
    # misspelled argument (allow_externl) is the one meant
    known = TOOLS[0]["inputSchema"]["properties"]
    args = {readpage.typo_fixed(k, list(known)): v for k, v in args.items()}
    ignored = ["%s (no such parameter)" % k for k in args if k not in known]
    for key, make in (("probe", answer.probe), ("probe_units", answer.probe_units)):
        if args.get(key) not in (None, False, ""):
            # numbered lines and nothing else, as `readpage.py --probe N` and `--probe-units N` print them: what the
            # client shows of a result - the second tells characters, UTF-16 units and bytes apart
            try:
                n = int(args.get(key))
            except (TypeError, ValueError):
                return err("%s takes a number of characters, such as %s=8000" % (key, key))
            return result([text(make(n))], {key: max(0, min(n, answer.PROBE_MAX))})
    url = (args.get("url") or "").strip()
    if not url:
        return err("url is required")
    # the CLI reads any file on the machine; over MCP only one inside read-page's
    # own folders (a cache entry, a folder with our manifest), checked after links are resolved -
    # so a prompt-injected model cannot read C:\Windows or a home folder through this tool
    local = readpage.local_path(url)
    if local and not owned_dir(os.path.dirname(local)):
        return err("a file on this machine is read over MCP only inside read-page's own folders "
                   "(a page folder of its cache, or a folder with its manifest); use the CLI for others")
    view = str(args.get("file") or "").strip().lower()
    view = {"page": "page.md", "content": "content.md", "text": "content.md"}.get(view, view)
    if view and view not in readpage.VIEWS:
        ignored.append("file %s (content.md or page.md)" % args.get("file"))
        view = ""
    start, to, quote = line_args(args, ignored)
    argv = [url, "--json"]
    for flag in ("allow_external", "force_external", "alternate", "refresh", "clear_cookies", "download"):
        if args.get(flag):
            argv.append("--" + flag.replace("_", "-"))
    shots = 0
    if args.get("screenshots"):
        raw = args.get("screenshots")
        try:
            shots = 2 if raw is True else max(0, int(raw))
        except (TypeError, ValueError):
            shots = 2
        if shots:
            argv += ["--screenshots", str(shots)]
    inline = bool(args.get("inline_images"))
    deny = args.get("deny_images") is True and not inline
    if deny:
        argv.append("--deny-images")
    if quote:
        argv.append("--from=" + quote)          # the saved copy, from the line holding the quote
    elif start > 1:
        argv += ["--from", str(start)]          # a continuation reads the saved copy: no network
    if to:
        argv += ["--to", str(to)]               # the window's pictures are the range's
    if view:
        argv += ["--file", view]                # page.md printed: its pictures come
    ocr_n = 0
    if args.get("ocr") not in (None, False, 0, ""):
        try:
            ocr_n = int(args.get("ocr"))
        except (TypeError, ValueError):
            ocr_n = 0
        if ocr_n >= 1:
            argv += ["--ocr", str(ocr_n)]       # picture N's text instead of the page's (CLI --ocr N)
        else:
            ignored.append("ocr %s (a picture's number, from its marker)" % args.get("ocr"))
            ocr_n = 0
    rc, out, e = run_cli(argv)
    if e:
        return err(e)
    try:
        manifest = json.loads(out)
    except Exception:
        return err("no manifest: " + (out[-300:] or "empty output"))
    if ignored:
        manifest["ignored"] = ignored + list(manifest.get("ignored") or [])
    if ocr_n and isinstance(manifest.get("ocr"), dict):
        found = manifest["ocr"].pop("text", "") or ""
        said, _ = answer.render(manifest, found, "img #%d text" % ocr_n, 1, readpage.ocr_next)
        return result([text(said)], {"dir": manifest.get("dir") or "", "status": manifest.get("status"),
                                     "ocr": manifest["ocr"]})

    status = manifest.get("status") or "error"
    # the folder as the answer names it - in the user's locale's letters, which under a POSIX locale that is not
    # UTF-8 are other bytes than this process's name for it (KNOWN-ISSUES 175)
    workdir = ownenv.fs_path(manifest.get("dir") or "")
    # the text's pictures by number; only those with a file can become image blocks
    images = sorted((e for e in manifest.get("images") or [] if e.get("file")), key=lambda x: x.get("n") or 0)
    # the same choice as the CLI: a continuation with no file goes on in the file read last,
    # which only the saved manifest knows (the printed one has no private keys)
    continuing = args.get("from") is not None
    saved = readpage.load_manifest(workdir) if workdir else {}
    view = readpage.answer_view(saved or manifest, workdir, view, continuing)
    lost = False                                # a quote no line holds: the answer is the outline
    if quote and workdir:
        found, to = quote_start(workdir, saved or {}, view, quote, to)
        lost, start = found is None, found or 1
    if workdir:
        readpage.remember_view(workdir, view, None if lost else start)
    body = ""
    if workdir and os.path.isfile(os.path.join(workdir, view)):
        body = open(os.path.join(workdir, view), encoding="utf-8", errors="replace").read()
    # how often each picture stands in the whole text: 3+ times is a decoration
    uses = {}
    for n, _rel in ANY_MARKER.findall(body):
        uses[int(n)] = uses.get(int(n), 0) + 1
    tiles = manifest.get("screenshots") or []
    # The text is rendered inside its block; the notes after it and the stand-ins of the pictures come on top, and a
    # client counts the blocks together (counted). So the text gives up the room they take: it is rendered again
    # inside what is left, until the blocks fit (a picture is converted once, whatever the number of passes). A
    # quote no line holds (the outline) and a range (`to`, sent whatever the block) have no block to give up.
    converted = {}
    room = dict(LIMITS)
    for _ in range(4):
        if lost:
            said, nxt = answer.not_found(manifest, body, view, quote), None
        else:
            said, nxt = answer.render(manifest, body, view, start, mcp_next, to=to, call=mcp_call, **room)
        blocks, state = result_blocks(manifest, said, workdir, inline, images, tiles, uses, shots, converted)
        used, own = counted(blocks), counted([text(said)])
        over = {k: used[k] - LIMITS[k] for k in LIMITS if used[k] > LIMITS[k]}
        # the text ends at a paragraph, short of its room: what it must lose is counted from what it has
        shrunk = {k: max(min(room[k], own[k]) - over[k], LIMITS[k] // 2) if k in over else room[k] for k in room}
        if lost or to or status == "media_only" or shrunk == room:
            break
        room = shrunk

    structured = {k: v for k, v in manifest.items() if not k.startswith("_")}
    structured["mcp"] = {"file": view, "from": start, "to": to, "next_from": nxt,
                         "total_lines": line_count(body),
                         "images_attached": state["attached"], "images_total": len(images),
                         "images_skipped": state.get("skipped", 0),
                         "images_inline": inline, "images_denied": deny,
                         "tokens": int(state["tokens"])}
    return result(blocks, structured, status == "error")


# ---------------------------------------------------------------- read

def inside(root, rel):
    p = os.path.realpath(os.path.join(root, rel.replace("/", os.sep)))
    r = os.path.realpath(root)
    return p if (p == r or p.startswith(r + os.sep)) else None


def owned_dir(d):
    """True when the folder is a read-page work folder: a cache entry, or a --dir with our
    manifest. Anything else (C:\\Windows, a home directory) is refused, so a prompt-injected
    model cannot turn `read` into a general file reader."""
    real = os.path.realpath(d)
    pages = os.path.realpath(os.path.join(readpage.cache_root(), "pages"))
    if real == pages or real.startswith(pages + os.sep):
        return True
    try:
        with open(os.path.join(real, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh).get("generator") == "read-page"
    except Exception:                              # noqa: BLE001
        return False


def tool_read(args):
    # left out and named, as read_url does: an old `offset`, a word for `from`; a typo is the one meant
    known = TOOLS[1]["inputSchema"]["properties"]
    args = {readpage.typo_fixed(k, list(known)): v for k, v in args.items()}
    ignored = ["%s (no such parameter)" % k for k in args if k not in known]
    d = ownenv.fs_path((args.get("dir") or "").strip())       # the folder as an answer named it (shown_paths)
    if not d or not os.path.isdir(d):
        return err("dir is not a directory: %r" % d)
    if not owned_dir(d):
        return err("dir is not a read-page working directory: %r (use the folder on the files: "
                   "line of a read_url answer, or a folder written with --dir)" % d)
    # no file named: the text read last; a text named here becomes the one read last
    rel = (args.get("file") or "").strip() or readpage.answer_view(readpage.load_manifest(d), d, "", True)
    start, to, quote = line_args(args, ignored)
    if rel in readpage.VIEWS and not quote:
        readpage.remember_view(d, rel, start)
    path = inside(d, rel)
    if not path or not os.path.isfile(path):
        return err("no such file: %s (in %s)" % (rel, d))
    shown_d = ownenv.shown(d)                                    # and as the user's locale names it, in what we say

    ext = os.path.splitext(path)[1].lower()
    size = os.path.getsize(path)
    blocks = []
    if args.get("ocr") and ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico",
                                   ".tif", ".tiff"):
        # the picture's text instead of the picture, for a model that cannot see it (CLI --ocr N)
        page_text = ""
        try:
            with open(os.path.join(d, "content.md"), encoding="utf-8", errors="replace") as fh:
                page_text = fh.read(20000)
        except OSError:
            pass
        found, info = readpage.ocr_picture(path, page_text)
        info.update(file=rel)
        manifest = dict(readpage.load_manifest(d) or {"status": "ok"}, dir=shown_d, cache="hit", ocr=info)
        if ignored:
            manifest["ignored"] = ignored
        said, _ = answer.render(manifest, found, "%s text" % os.path.basename(path), 1, readpage.ocr_next)
        return result([text(said)], {"dir": shown_d, "file": rel, "kind": "text in a picture", "ocr": info})
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico"):
        block, caption = image_block(path)
        if block:
            blocks = [text("read-page · image · %s · %s" % (readpage.human_bytes(size), os.path.basename(path))),
                      block, text(caption)]
            structured = {"dir": shown_d, "file": rel, "kind": "image", "bytes": size,
                          "attached": True, "caption": caption}
        else:
            blocks = [text("read-page · image · %s · not attached: %s" % (os.path.basename(path), caption))]
            structured = {"dir": shown_d, "file": rel, "kind": "image", "bytes": size, "attached": False,
                          "reason": caption}
        return result(blocks, structured)

    kind = ""
    if ext in readpage.AUDIO_EXT | readpage.VIDEO_EXT:
        kind = "audio" if ext in readpage.AUDIO_EXT else "video"
    if kind:
        attached = False
        if kind == "audio" and os.environ.get("READ_PAGE_MCP_MEDIA", "off") == "audio" and size <= IMG_BYTES:
            data = open(path, "rb").read()
            blocks = [{"type": "audio", "data": base64.b64encode(data).decode("ascii"),
                       "mimeType": MIME.get(ext, "audio/mpeg")}]
            attached = True
        blocks.append(text("read-page · %s · %s · %s%s" % (
            kind, os.path.basename(path), readpage.human_bytes(size),
            "" if attached else " · attached only with READ_PAGE_MCP_MEDIA=audio (and a client that renders audio)")))
        return result(blocks, {"dir": shown_d, "file": rel, "kind": kind, "bytes": size, "attached": attached})

    try:
        data = open(path, "rb").read()
    except OSError as e:
        return err(str(e))
    if readpage.media_kind(data, "", path) == "image":
        block, caption = image_block(path)
        blocks = [text("read-page · image · %s" % os.path.basename(path))] + ([block] if block else []) + [text(caption)]
        return result(blocks, {"dir": shown_d, "file": rel, "kind": "image", "bytes": size,
                               "attached": bool(block)})
    if readpage.media_kind(data, "", path):
        note = "read-page · binary · %s · %s · no text in this file" % (os.path.basename(path),
                                                                       readpage.human_bytes(size))
        return result([text(note)], {"dir": shown_d, "file": rel, "kind": "binary", "bytes": size,
                                     "attached": False})

    body = data.decode("utf-8", "replace")
    if rel.endswith(".json"):
        try:
            pretty = json.dumps(json.loads(body), ensure_ascii=False, indent=1)
            body = pretty
        except Exception:
            pass
    saved = readpage.load_manifest(d) or {}
    lost = False                                # a quote no line holds: the answer is the outline
    if quote:
        last = saved.get("_from") or {}
        found = answer.find(body.split("\n"), quote, last.get("line") if last.get("view") == rel else 1)
        lost, start = found is None, found or 1
        if not lost and to is not None and to < start:
            ignored.append("to %d (before line %d, where the quote is)" % (to, start))
            to = None
        if rel in readpage.VIEWS:
            readpage.remember_view(d, rel, None if lost else start)
    manifest = dict(saved or {"status": "ok"}, dir=shown_d, cache="hit")
    if ignored:
        manifest["ignored"] = ignored
    if lost:
        return result([text(answer.not_found(manifest, body, rel, quote))],
                      {"dir": shown_d, "file": rel, "kind": "text", "from": None, "to": to, "next_from": None,
                       "total_lines": line_count(body), "not_found": quote})
    said, nxt = answer.render(manifest, body, rel, start, mcp_next, to=to, call=mcp_call)
    return result([text(said)], {"dir": shown_d, "file": rel, "kind": "text", "from": start, "to": to,
                                 "next_from": nxt, "total_lines": line_count(body)})


# ---------------------------------------------------------------- protocol

def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "read-page", "version": SERVER_VERSION},
            "instructions": ("Read a URL or document and prove what was obtained. The header of "
                             "every answer says which engine produced the text, whether it may be "
                             "only a fragment of the page and what to do next. Follow advice when it "
                             "appears; pass allow_external=true only for public URLs; pass "
                             "inline_images=true when the pictures themselves matter."),
        }}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        a = params.get("arguments") or {}
        try:
            # an argument outside the schema no longer refuses the call: each tool
            # leaves it out and its answer names it, as the CLI does with a flag that is not ours
            if name == "read_url":
                return {"jsonrpc": "2.0", "id": mid, "result": tool_read_url(a)}
            if name == "read":
                return {"jsonrpc": "2.0", "id": mid, "result": tool_read(a)}
        except Exception as e:                   # noqa: BLE001
            return {"jsonrpc": "2.0", "id": mid, "result": err("%s: %s" % (type(e).__name__, e))}
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32602, "message": "Unknown tool: %s" % name}}
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return {"jsonrpc": "2.0", "id": mid, "result": {key: []}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "Method not found: %s" % method}}


def main():
    log("started, protocol %s" % PROTOCOL)
    threading.Thread(target=spare_start, daemon=True).start()      # ready for the first call
    workers = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:                   # noqa: BLE001
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error: %s" % e}})
            continue
        if isinstance(msg, list):
            # batching was removed from MCP 2025-06-18; before 0.4 this raised AttributeError
            # inside the loop and the client got no answer at all (it hung)
            write({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32600, "message": "batch requests are not supported"}})
            continue
        if not isinstance(msg, dict):
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "not a request"}})
            continue
        if msg.get("method") == "notifications/cancelled":
            cancel((msg.get("params") or {}).get("requestId"))
            continue
        if msg.get("method") == "tools/call" and (msg.get("params") or {}).get("name") == "read_url" \
                and msg.get("id") is not None:
            # a page read takes seconds: its own thread, so the next call does not wait for it
            t = threading.Thread(target=answer_call, args=(msg,), daemon=True)
            t.start()
            workers = [w for w in workers if w.is_alive()] + [t]
            continue
        try:
            resp = handle(msg)
        except Exception as e:                   # noqa: BLE001
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}}
        if resp is not None:
            write(resp)
    for t in workers:                            # the client closed stdin: the running calls end
        t.join()
    with _SPARE_LOCK:                            # the spare reads an empty line and exits
        p, _SPARE["p"] = _SPARE["p"], None
    if p is not None and p.poll() is None:
        try:
            p.stdin.close()
        except (OSError, ValueError):
            pass
    return 0
if __name__ == "__main__":
    sys.exit(main())
