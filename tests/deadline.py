"""The read's deadline and what a read costs.
No network.

    python -X utf8 tests/deadline.py

Every read ends by its deadline (55 s; READ_PAGE_TEST_DEADLINE shortens it here) with what it
has: a slow but moving page is not cut by a fixed 20 s any more, and a stuck defuddle or a huge
page costs the deadline, not minutes. defuddle runs as one worker per read with the CLI's own
text; readability and trafilatura run side by side in processes the read can stop; a page over
3 MB is its own page.md. Start-up is cheaper: which() asks once, urllib's certificates load on
first use, curl_cffi's extras stay out. Playwright's current Chromium folders are found. OCR
pages run side by side. The MCP server keeps one warm process for the next call.
READ_PAGE_DEBUG=1 writes the read's whole story into debug/*.jsonl of its folder (or into
READ_PAGE_DEBUG_DIR), and nothing of it into the answer or the manifest; keys and query secrets
stay out of it.
"""
import glob
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness import PUBLIC, SCRIPT, Checks, run_read, serve     # noqa: E402

check = Checks()
SCRIPTS = os.path.dirname(SCRIPT)
SERVER = os.path.join(SCRIPTS, "mcp_server.py")
H = {"Content-Type": "text/html; charset=utf-8"}
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ")


def debug_log(folder):
    """The rows of the READ_PAGE_DEBUG logs in a folder: its debug/*.jsonl, or the folder itself."""
    rows = []
    for p in sorted(glob.glob(os.path.join(folder or "", "debug", "*.jsonl")) + glob.glob(os.path.join(folder or "", "*.jsonl"))):
        with open(p, encoding="utf-8") as fh:
            rows += [json.loads(line) for line in fh if line.strip()]
    return rows


def article(marker, n=8, title="A page"):
    paras = "".join("<p>%s %d. %s</p>" % (marker, i, EN * 2) for i in range(n))
    return ("<!doctype html><html><head><title>%s</title></head><body><nav><a href='/'>Home</a></nav>"
            "<article><h1>%s</h1>%s</article><footer>Footer</footer></body></html>" % (title, title, paras)
            ).encode("utf-8")


def module(cache=None):
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = cache or tempfile.mkdtemp(prefix="rp-dl-")
    spec = importlib.util.spec_from_file_location("rp_deadline_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def flowing(seconds, rate=4096, tail=b""):
    """A page that arrives at `rate` bytes a second - above the 1 KB/s floor - for `seconds`."""
    head = b"<!doctype html><html><head><title>Slow</title></head><body><article><h1>Slow</h1><p>FLOW-START " \
        + (EN * 6).encode() + b"</p>"

    def h(req):
        req.send_response(200)
        req.send_header("Content-Type", "text/html; charset=utf-8")
        req.end_headers()
        try:
            req.wfile.write(head)
            req.wfile.flush()
            end = time.time() + seconds
            while time.time() < end:
                req.wfile.write(b"<p>" + b"flowing words " * (rate // 28) + b"</p>")
                req.wfile.flush()
                time.sleep(0.5)
            req.wfile.write(tail + b"</article></body></html>")
            req.wfile.flush()
        except OSError:
            pass
        req.close_connection = True
    return h


def huge_page():
    para = "<p>HUGE-MARKER " + EN * 4 + "</p><script>var x = '" + "y" * 200 + "';</script>"
    body = "".join("<h2>Part %d</h2>%s" % (i, para * 20) for i in range(400))
    return ("<!doctype html><html><head><title>Huge</title></head><body><main>%s</main></body></html>"
            % body).encode("utf-8")


def fake_defuddle(root):
    """A defuddle install whose parser never answers: the worker loads it and hangs in warm-up."""
    dist = os.path.join(root, "node_modules", "defuddle", "dist")
    os.makedirs(os.path.join(dist, "utils"))
    with open(os.path.join(dist, "node.js"), "w") as f:
        # a timer keeps node running: with only a pending promise it exits on Linux (nothing left in
        # its event loop), and "the worker ended" is a quick failure, not the stuck parser meant here
        f.write("exports.Defuddle = () => new Promise(() => { setInterval(() => {}, 1 << 30); });\n")
    with open(os.path.join(dist, "utils", "linkedom-compat.js"), "w") as f:
        f.write("exports.parseLinkedomHTML = () => ({});\n")
    with open(os.path.join(dist, "cli.js"), "w") as f:
        f.write("setTimeout(() => {}, 600000);\n")          # the CLI hangs too
    if os.name == "nt":
        with open(os.path.join(root, "defuddle.cmd"), "w") as f:
            f.write('@node "%~dp0\\node_modules\\defuddle\\dist\\cli.js" %*\r\n')
    else:
        p = os.path.join(root, "defuddle")
        with open(p, "w") as f:
            f.write('#!/bin/sh\nexec node "$(dirname "$0")/node_modules/defuddle/dist/cli.js" "$@"\n')
        os.chmod(p, 0o755)


routes = {"/flow": flowing(120), "/flow25": flowing(22, tail=b"<p>FLOW-END</p>"),
          "/page": (200, H, article("PLAIN")), "/huge": (200, H, huge_page())}
s = serve(routes)
fast = {"READ_PAGE_SKIP": "browser"}
try:
    # ------------------------------------------------ the deadline ends a page that keeps flowing
    r = run_read(s.url("/flow"), env=dict(fast, READ_PAGE_TEST_DEADLINE="10", READ_PAGE_DEBUG="1"))
    sig = r.manifest.get("signals") or {}
    check("deadline: a page still flowing at the deadline ends with the part that arrived",
          r.seconds < 14 and sig.get("partial") is True and "FLOW-START" in r.file("content.md"),
          "%.1f s, %s, partial=%s" % (r.seconds, r.manifest.get("status"), sig.get("partial")))
    log = debug_log(r.dir)
    http = [x for x in log if x.get("k") == "step" and x.get("step") == "http"]
    check("debug: READ_PAGE_DEBUG=1 logs the step the deadline ended, with its cap",
          http and http[0].get("end") == "deadline" and http[0].get("cap", 99) < http[0].get("own", 0),
          str(http[:1]))
    check("debug: the log is a file - nothing of it in the answer or the manifest (MCP hands that to the model)",
          bool(log) and b"debug" not in r.out and "debug" not in r.manifest, "%d log rows" % len(log))
    r = run_read(s.url("/page?token=abc123secretvalue"),
                 env=dict(fast, READ_PAGE_DEBUG="1", FIRECRAWL_API_KEY="sk-test-secret-123"))
    log = debug_log(r.dir)
    kinds = {x.get("k") for x in log}
    names = [x.get("step") for x in log if x.get("k") == "step"]
    run_row = next((x for x in log if x.get("k") == "run"), {})
    picks = [x for x in log if x.get("k") == "decide" and x.get("what") == "extraction"]
    summary = next((x for x in log if x.get("k") == "summary"), {})
    check("debug: an ordinary read's log has the run, the machine, every step, the decisions and the answer",
          names[:1] == ["http"] and "page.md" in names and ("defuddle" in names or not shutil.which("node"))
          and all(x.get("end") == "ok" for x in log if x.get("k") == "step")
          and {"run", "caps", "step", "event", "decide", "summary"} <= kinds
          and (run_row.get("machine") or {}).get("cpus") and picks and picks[0].get("pick")
          and summary.get("status") == "ok", "%s; kinds %s" % (names, sorted(kinds)))
    raw = json.dumps(log, ensure_ascii=False)
    check("debug: no secret in the log - a key is named, a credential in the query is masked",
          "FIRECRAWL_API_KEY" in raw and "sk-test-secret-123" not in raw and "abc123secretvalue" not in raw
          and "token=***" in raw, "")
    central = tempfile.mkdtemp(prefix="rp-debug-dir-")
    r = run_read(s.url("/page"), env=dict(fast, READ_PAGE_DEBUG_DIR=central))
    check("debug: READ_PAGE_DEBUG_DIR gathers a session's logs in one folder, none in the page's",
          len(glob.glob(os.path.join(central, "*.jsonl"))) == 1 and not os.path.isdir(os.path.join(r.dir, "debug"))
          and debug_log(central), str(os.listdir(central)))
    r = run_read(s.url("/page"), env=fast)
    check("debug: off without READ_PAGE_DEBUG (no log, no debug lines, no debug block)",
          not os.path.isdir(os.path.join(r.dir, "debug")) and b"debug" not in r.out and "debug" not in r.manifest, "")
    import socket
    sk = socket.socket()
    sk.bind((PUBLIC, 0))
    dead = sk.getsockname()[1]
    sk.close()
    r = run_read("http://%s:%d/page" % (PUBLIC, dead), env=dict(fast, READ_PAGE_DEBUG="1"))
    names = [x.get("step") for x in debug_log(r.dir) if x.get("k") == "step"]
    check("no body, no extractor: a host that did not answer goes straight to the answer",
          r.manifest.get("status") == "error" and names == ["http"], str(names))
    r = run_read(s.url("/flow25"), env=dict(fast, READ_PAGE_TEST_DEADLINE="45"))
    sig = r.manifest.get("signals") or {}
    check("deadline: a slow link is not cut at a fixed 20 s (22 s at 4 KB/s arrives whole)",
          "FLOW-END" in r.file("page.md") and not sig.get("partial") and r.manifest.get("status") == "ok",
          "%.1f s, %s, partial=%s" % (r.seconds, r.manifest.get("status"), sig.get("partial")))

    # ------------------------------------------------ a stuck defuddle costs the deadline; page.md answers
    if shutil.which("node"):
        root = tempfile.mkdtemp(prefix="rp-fakedd-")
        fake_defuddle(root)
        # the fake on PATH is the defuddle found only outside the skill's own environment (--setup),
        # whose programs come before PATH's: env is skipped
        env = dict(fast, READ_PAGE_TEST_DEADLINE="8", READ_PAGE_SKIP="browser,readability,trafilatura,env",
                   PATH=root + os.pathsep + os.environ.get("PATH", ""))
        r = run_read(s.url("/page"), env=env)
        sig = r.manifest.get("signals") or {}
        check("deadline: a defuddle that never answers costs the deadline, and page.md is the text",
              r.seconds < 12 and r.manifest.get("status") == "ok" and "PLAIN 3" in r.file("content.md")
              and sig.get("extract_late"),
              "%.1f s, %s, engine %s, late=%s" % (r.seconds, r.manifest.get("status"),
                                                  (r.manifest.get("content") or {}).get("engine"),
                                                  bool(sig.get("extract_late"))))
    else:
        check.skip("deadline: a stuck defuddle", "node is not installed here")

    # ------------------------------------------------ one worker per read, the CLI's own text
    mod = module()
    cli = mod.which("defuddle")
    if cli and mod.ddworker.locate(cli, mod.which("node"))[0]:
        work = tempfile.mkdtemp(prefix="rp-dd-")
        same, n = 0, 0
        pages = [article("WORKER", 12, "Worker test"),
                 (b"<!doctype html><html><head><title>Table</title></head><body><main><h1>Table</h1><p>"
                  + (EN * 3).encode() + b"</p><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td>"
                  b"</tr></table><pre><code>print(1)</code></pre><ul><li>one</li><li>two</li></ul>"
                  b"<img src='/p.png' alt='a picture'></main></body></html>"),
                 "<!doctype html><html><head><title>Кириллица</title></head><body><article><h1>Заголовок</h1>"
                 "<p>{}</p></article></body></html>".format("Текст страницы, довольно длинный. " * 30).encode()]
        for i, html in enumerate(pages):
            text = html.decode("utf-8")
            url = s.url("/w%d" % i)
            got, why = mod.defuddle_start(text, work, url).result(60)
            src = os.path.join(work, "cli%d.html" % i)
            with open(src, "w", encoding="utf-8") as f:
                f.write(mod.with_base(text, url))
            rc, so, se = mod.run_tool([cli, "parse", src, "--markdown"], timeout=60)
            n += 1
            same += int(rc == 0 and got == so.decode("utf-8"))
        w = mod._DD.get("worker")
        check("worker: the same markdown as `defuddle parse --markdown`, three pages, one process",
              same == n and w is not None and w.alive(), "%d of %d the same" % (same, n))
        mod.defuddle_close()
    else:
        check.skip("worker: the CLI's own text", "defuddle (npm) is not installed here")

    # ------------------------------------------------ a huge page is its own page.md
    r = run_read(s.url("/huge"), env=fast)
    sig = r.manifest.get("signals") or {}
    content = r.file("content.md")
    check("huge: a page over 3 MB is its whole text, with no extractor and a note",
          (r.manifest.get("content") or {}).get("engine") == "full" and bool(sig.get("huge"))
          and content.count("HUGE-MARKER") > 7000 and r.seconds < 40,
          "%.1f s, engine %s, %d markers" % (r.seconds, (r.manifest.get("content") or {}).get("engine"),
                                            content.count("HUGE-MARKER")))

    # ------------------------------------------------ extractors in processes: side by side, stopped in time
    mod = module()
    html = article("CHILD").decode()
    os.environ["READ_PAGE_TEST_XCHILD_SLEEP"] = "30"
    t = time.time()
    got = mod.others(html, "https://example.com/a", 2.0)
    dt = time.time() - t
    check("extractors: a process still working when its time is up is stopped",
          dt < 6 and all(not v[0] and "no answer" in v[1] for v in got.values()) and len(got) >= 1,
          "%.1f s %s" % (dt, {k: v[1] for k, v in got.items()}))
    os.environ["READ_PAGE_TEST_XCHILD_SLEEP"] = "2"
    t = time.time()
    got = mod.others(html, "https://example.com/a", 20.0, names=("html2text", "crude"))
    dt = time.time() - t
    os.environ.pop("READ_PAGE_TEST_XCHILD_SLEEP")
    check("extractors: two run side by side (2 s each, about 2 s together)",
          dt < 3.9 and all("CHILD 3" in v[0] for v in got.values()),
          "%.1f s %s" % (dt, {k: len(v[0]) for k, v in got.items()}))

    # ------------------------------------------------ start-up: which() once, certificates and extras later
    calls = []
    real = shutil.which

    def counted(name, *a, **k):
        calls.append(name)
        return real(name, *a, **k)
    shutil.which = counted
    try:
        mod.which("no-such-tool-rp")
        mod.which("no-such-tool-rp")
        once = len(calls)
        os.environ["PATH"] = tempfile.mkdtemp(prefix="rp-p-") + os.pathsep + os.environ["PATH"]
        mod.which("no-such-tool-rp")
    finally:
        shutil.which = real
    check("start-up: which() walks PATH once per tool, again when PATH changes", once == 1 and len(calls) == 2,
          "%d, then %d" % (once, len(calls)))
    code = ("import sys, importlib.util; sys.path.insert(0, %r); import readpage\n"
            "print(len(readpage._OPENERS))\n"
            "has = importlib.util.find_spec('curl_cffi') is not None\n"
            "readpage.curl_cffi_requests() if has else None\n"
            "print(has, 'markdownify' in sys.modules, 'readability' in sys.modules, 'bs4' in sys.modules)\n"
            % SCRIPTS)
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=60)
    lines = p.stdout.split("\n")
    check("start-up: urllib's certificate store is not loaded at import", lines[:1] == ["0"], p.stdout[:80])
    check("start-up: curl_cffi loads without markdownify, bs4 and readability",
          len(lines) > 1 and (lines[1].startswith("False") or lines[1] == "True False False False"),
          (lines[1:2] or [p.stderr[-200:]])[0])

    # ------------------------------------------------ Playwright's current Chromium folders
    pw = tempfile.mkdtemp(prefix="rp-pw-")
    if os.name == "nt":
        exe = ("chromium-1243", "chrome-win64", "chrome.exe")
        shell = ("chromium_headless_shell-1243", "chrome-headless-shell-win64", "chrome-headless-shell.exe")
    elif sys.platform == "darwin":
        exe = ("chromium-1243", "chrome-mac-arm64", "Google Chrome for Testing.app", "Contents", "MacOS",
               "Google Chrome for Testing")
        shell = ("chromium_headless_shell-1243", "chrome-headless-shell-mac-arm64", "chrome-headless-shell")
    else:
        exe = ("chromium-1243", "chrome-linux64", "chrome")
        shell = ("chromium_headless_shell-1243", "chrome-headless-shell-linux64", "chrome-headless-shell")
    for parts in (exe, shell):
        os.makedirs(os.path.join(pw, *parts[:-1]), exist_ok=True)
        open(os.path.join(pw, *parts), "w").close()
    code = ("import sys, json; sys.path.insert(0, %r); import readpage\n"
            "print(json.dumps([[b['name'], b.get('path')] for b in readpage.browsers()]))\n" % SCRIPTS)
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=pw))
    try:
        found = json.loads(p.stdout)
    except ValueError:
        found = []
    names = [n for n, path in found if path and path.startswith(pw)]
    check("browsers: Playwright's Chrome for Testing folder is found, the headless shell after it",
          names == ["playwright-bundled", "playwright-shell"], str(names or p.stderr[-160:]))

    # ------------------------------------------------ OCR pages side by side
    mod2 = module()
    mod2.which = lambda name: "tesseract" if name == "tesseract" else None
    mod2.tesseract_langs = lambda exe=None: ["eng"]
    mod2._tesserocr = lambda: None              # the command's path, even where tesserocr is installed

    def slow_ocr(cmd, timeout=120):
        time.sleep(1.0)
        return 0, ("PAGE %s" % os.path.basename(cmd[1])).encode(), b""
    mod2.run_tool = slow_ocr
    t = time.time()
    text, info = mod2.ocr_pages(["a.png", "b.png", "c.png"])
    dt = time.time() - t
    check("OCR: three pages side by side (1 s each, about 1 s together), in order",
          dt < 2.5 and text.split("\n\n") == ["PAGE a.png", "PAGE b.png", "PAGE c.png"], "%.1f s" % dt)

    # ------------------------------------------------ MCP: a warm process waits for the next call
    try:
        import psutil
    except ImportError:
        psutil = None
    env = dict(os.environ, READ_PAGE_TEST_PUBLIC_HOST=PUBLIC, READ_PAGE_SKIP="browser",
               READ_PAGE_CACHE=tempfile.mkdtemp(prefix="rp-mcp-spare-"))
    for k in ("FIRECRAWL_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "JINA_API_KEY"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, "-X", "utf8", SERVER], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    lines_q = queue.Queue()
    threading.Thread(target=lambda: [lines_q.put(x) for x in proc.stdout] + [lines_q.put(None)],
                     daemon=True).start()

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()

    def take(timeout):
        try:
            line = lines_q.get(timeout=timeout)
        except queue.Empty:
            return None
        return json.loads(line) if line else None

    def spares():
        if psutil is None:
            return None
        try:
            # recursive: a Windows venv's python.exe is a launcher that starts the real one as its
            # child, so the warm process sits a level deeper there (seen with Python 3.9 in a uv venv)
            return [c.pid for c in psutil.Process(proc.pid).children(recursive=True)
                    if "--serve-once" in " ".join(c.cmdline()) and not any(
                        "--serve-once" in " ".join(k.cmdline()) for k in c.children())]
        except Exception:                                     # noqa: BLE001
            return None
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
        take(30)
        time.sleep(1.5)
        first = spares()
        answers = []
        for i, args in enumerate(({"url": s.url("/page")}, {"url": s.url("/page"), "file": "page.md"})):
            send({"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call",
                  "params": {"name": "read_url", "arguments": args}})
            answers.append(take(60))
        time.sleep(1.5)
        after = spares()
        texts = [" ".join(b.get("text", "") for b in ((a or {}).get("result") or {}).get("content") or [])
                 for a in answers]
        check("MCP: calls served by the warm process answer right (the arguments reach it)",
              all("PLAIN 3" in t for t in texts) and "page.md" in texts[1],
              str([((a or {}).get("result") or {}).get("structuredContent", {}).get("status") for a in answers]))
        if psutil is not None:
            check("MCP: one warm process waits, and a new one replaces each that is taken",
                  first and after and len(first) == 1 and len(after) == 1 and first != after,
                  "%s then %s" % (first, after))
        else:
            check.skip("MCP: the warm process itself", "psutil is not installed here")
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=20)
        except Exception:                                     # noqa: BLE001
            proc.kill()
    if psutil is not None and after:
        time.sleep(1.0)
        check("MCP: the warm process ends with the server", not any(psutil.pid_exists(p) for p in after),
              str(after))
finally:
    s.close()
sys.exit(check.done())
