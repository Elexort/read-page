"""The browser tier, exercised for real on whatever OS this is.

    python -X utf8 tests/browser_live.py

No network: three local servers stand in for the three cases the tier exists for.

  1. a shell that fills itself a moment after load (the ordinary SPA);
  2. a shell that fills *after* the 10-second budget - the mount watch (KNOWN-ISSUES #12);
  3. a members-only page that only renders when the request carries the session cookie the HTTP
     tier was given (KNOWN-ISSUES #44).

Skipped when this machine has no Playwright/Patchright or no Chromium: it is the one suite that
cannot run on a bare runner, and it says so instead of passing quietly.
"""
import glob
import http.server
import importlib.util
import json
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "readpage.py")
# the user's debug log switches stay out (harness does the same; this suite imports it later)
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):
    os.environ.pop(_name, None)
ok = failed = skipped = 0


def check(name, good, detail=""):
    global ok, failed
    if good:
        ok += 1
        print("OK   %-58s %s" % (name, detail))
    else:
        failed += 1
        print("FAIL %-58s %s" % (name, detail))


def skip(name, why):
    global skipped
    skipped += 1
    print("SKIP %-58s %s" % (name, why))


spec = importlib.util.spec_from_file_location("rp_live", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

caps = mod.caps()
have_driver = bool(caps["libs"].get("patchright") or caps["libs"].get("playwright"))
have_browser = bool(caps.get("browsers"))
if not (have_driver and have_browser):
    skip("browser tier", "no driver" if not have_driver else "no Chromium")
    print("\n%d ok, %d failed, %d skipped" % (ok, failed, skipped))
    sys.exit(0)

WORDS = ("the article body arrives only after the framework has mounted it into the page. " * 12)
SHELL = """<!doctype html><html><head><title>Shell</title></head><body><div id="app"></div>
<script>setTimeout(function(){ document.getElementById("app").innerHTML =
  "<h1>Mounted</h1><p>%s</p>"; }, 250);</script></body></html>""" % WORDS
LATE = SHELL.replace("}, 250);", "}, 11000);")
TALL = ("<!doctype html><html><head><meta charset='utf-8'><title>Tall</title>"
        "<style>body{font:16px/1.5 sans-serif;max-width:900px;margin:24px auto}</style></head>"
        "<body><h1>Tall</h1>"
        + "".join("<p>Paragraph %d: the quick brown fox jumps over the lazy dog, twice over.</p>" % i
                  for i in range(60))
        + "</body></html>")
# a page whose own script makes `innerHeight` throw: the screens cannot be measured, so it gives no picture - and says why
BROKEN = TALL.replace("<body>", "<body><script>Object.defineProperty(window, 'innerHeight', "
                      "{get: function () { throw new Error('no height here'); }});</script>")
GATE_ARTICLE = ("<!doctype html><html><head><title>Members</title></head><body><h1>Members</h1><p>"
                + WORDS + "</p></body></html>")
GATE_SHELL = """<!doctype html><html><head><title>Members</title></head><body><div id="app"></div>
</body></html>"""
# a menu and one script, no empty mount node: no shell by the old rule (three scripts), yet its
# text can only come from the browser (crates.io, AliExpress, Telegram); defuddle finds nothing
TINY = """<!doctype html><html><head><title>Tiny</title></head><body><nav><a href="/a">Home</a> <a href="/b">Pricing</a>
<a href="/c">Docs</a> <a href="/d">Sign in</a></nav><div id="mount-point"></div>
<script>setTimeout(function(){ document.getElementById("mount-point").innerHTML =
  "<h1>Tiny mounted</h1><p>TINY-MOUNTED %s</p>"; }, 250);</script></body></html>""" % WORDS
# a tab set a script mounts: the browser's text, and page.md from what the browser shows - which folded
# the hidden panel away (KNOWN-ISSUES 256)
TABS_SHELL = """<!doctype html><html><head><title>Plans</title></head><body><div id="app"></div>
<script>setTimeout(function(){ document.getElementById("app").innerHTML =
  "<main><h1>Plans</h1><p>%s</p><div role='tablist'><button role='tab' aria-selected='true' aria-controls='p1'>" +
  "Free Plan Limits</button><button role='tab' aria-selected='false' aria-controls='p2'>Developer Plan Limits" +
  "</button><button role='tab' aria-selected='false' aria-controls='p3'>Batch Limits</button></div>" +
  "<div role='tabpanel' id='p1'><p>FREE-PANEL %s</p></div><div role='tabpanel' id='p2' hidden><p>DEV-PANEL %s" +
  "</p></div><div role='tabpanel' id='p3' hidden></div></main>"; }, 250);</script></body></html>""" % (
    WORDS, WORDS[:200], WORDS[:200])


def serve(routes):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            kind = routes.get(self.path.split("?")[0], "shell")
            cookie = self.headers.get("Cookie") or ""
            if kind == "gate":
                body = GATE_ARTICLE if "pass=1" in cookie else GATE_SHELL
                if "pass=1" not in cookie:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Set-Cookie", "pass=1; Path=/; Max-Age=600")
                    b = body.encode()
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
            else:
                body = {"shell": SHELL, "late": LATE, "tall": TALL, "tiny": TINY, "broken": BROKEN,
                        "tabs": TABS_SHELL}.get(kind, SHELL)
            b = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


cache = os.path.join(tempfile.mkdtemp(prefix="browser-live-"), "cache")
srv, port = serve({"/spa": "shell", "/late": "late", "/gate": "gate", "/tall": "tall", "/tiny": "tiny", "/broken": "broken",
                   "/tabs": "tabs"})
base = "http://127.0.0.1:%d" % port


def read(path, *flags, env_extra=None):
    env = dict(os.environ, READ_PAGE_CACHE=cache, **(env_extra or {}))
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, base + path, "--refresh", "--json"] + list(flags),
                       capture_output=True, env=env, timeout=180)
    try:
        return json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        return {}


def shots_said(m):
    """What the answer says about --screenshots that took no picture or stopped early: the capture's own reason
    (signals.screenshots_failed, KNOWN-ISSUES 246) and, where nothing came, what the browser tier did - a flake of
    CI's browser job once printed `screens None` and nothing else."""
    sig, chain = m.get("signals") or {}, m.get("chain") or {}
    bits = []
    if sig.get("screenshots_failed"):
        bits.append("screenshots_failed: %s" % sig["screenshots_failed"])
    if not m.get("screenshots"):
        bits.append("status %s, tried %s, skipped %s" % (
            m.get("status"), chain.get("tried"), [s.get("why") for s in chain.get("skipped") or []]))
    return "; " + " | ".join(bits) if bits else ""


m1 = read("/spa")
check("a shell that mounts in 250 ms reads as text",
      m1.get("status") == "ok" and (m1.get("content") or {}).get("chars", 0) > 500,
      "%s %s chars" % (m1.get("status"), (m1.get("content") or {}).get("chars")))
check("the browser tier is what got it",
      any(str(t).startswith("browser") for t in (m1.get("chain") or {}).get("tried") or []),
      str((m1.get("chain") or {}).get("tried"))[:70])
# the answer says whose text it is when a browser's was weighed: an --alternate read named an extractor alone, and an
# agent could not tell whether the browser had run (KNOWN-ISSUES 322)
check("... and the manifest says the text is the browser's (content.source)",
      (m1.get("content") or {}).get("source") == "browser", str((m1.get("content") or {}).get("source")))
m_alt = read("/tall", "--alternate")
check("an --alternate read of a page the server serves whole: the browser's text weighed, which one stands said",
      (m_alt.get("content") or {}).get("source") in ("browser", "server")
      and any(str(t).startswith("browser") for t in (m_alt.get("chain") or {}).get("tried") or []),
      "%s; tried %s" % ((m_alt.get("content") or {}).get("source"), (m_alt.get("chain") or {}).get("tried")))

# such a page starts the browser right after HTTP, and the HTTP pass's readability
# and trafilatura run once the browser has its page open (a weak laptop's CPU goes to Chrome's start)
mt = read("/tiny", env_extra={"READ_PAGE_DEBUG": "1"})
st = {}
for log_path in sorted(glob.glob(os.path.join(mt.get("dir") or "", "debug", "*.jsonl"))):
    with open(log_path, encoding="utf-8") as fh:
        for row in (json.loads(line) for line in fh if line.strip()):
            if row.get("k") == "step":
                st.setdefault(row["step"], row)
http_end = (st.get("http") or {}).get("at", 0) + (st.get("http") or {}).get("s", 0)
br = st.get("browser") or {}
opened = br.get("at", 0) + float((re.search(r"start ([0-9.]+)", br.get("note") or "") or [0, 0])[1])
tiny_text = ""
try:
    with open(os.path.join(mt.get("dir") or "", "content.md"), encoding="utf-8") as fh:
        tiny_text = fh.read()
except OSError:
    pass
check("a tiny page with one script: the browser starts right after HTTP, and its text is the answer",
      mt.get("status") == "ok" and bool(br) and br["at"] - http_end < 0.5 and "TINY-MOUNTED" in tiny_text,
      "browser at %.2f s, HTTP done at %.2f s, %s" % (br.get("at", -1), http_end, mt.get("status")))
kids = [st[k] for k in ("readability", "trafilatura") if k in st]
check("its slower extractors wait for the browser's page (the HTTP text is decided the same)",
      kids and all(k["at"] >= opened - 0.2 for k in kids),
      "page open at %.2f s, extractors at %s" % (opened, [k["at"] for k in kids]))

mtab = read("/tabs")
tab_text = tab_page = ""
try:
    with open(os.path.join(mtab.get("dir") or "", "content.md"), encoding="utf-8") as fh:
        tab_text = fh.read()
    with open(os.path.join(mtab.get("dir") or "", "page.md"), encoding="utf-8") as fh:
        tab_page = fh.read()
except OSError:
    pass
check("a tab set the browser drew: the shown tab, the hidden tab's text under its marker, the tab with no panel",
      0 <= tab_text.find("[tab · shown · Free Plan Limits]") < tab_text.find("FREE-PANEL")
      < tab_text.find("[tab · hidden, but extracted · Developer Plan Limits]") < tab_text.find("DEV-PANEL")
      and "[tab · loads on click, not extracted · Batch Limits]" in tab_text
      and any(str(t).startswith("browser") for t in (mtab.get("chain") or {}).get("tried") or []),
      "%s %s" % (mtab.get("status"), [ln[:60] for ln in tab_text.split("\n") if "[tab" in ln]))
check("... page.md, made from what the browser shows, keeps the hidden panel under its marker",
      0 <= tab_page.find("[tab · hidden, but extracted · Developer Plan Limits]") < tab_page.find("DEV-PANEL"),
      [ln[:60] for ln in tab_page.split("\n") if "[tab" in ln or "PANEL" in ln])

m2 = read("/late")
waited = (m2.get("signals") or {}).get("browser_waited")
check("a shell that mounts after the budget is still caught", m2.get("status") == "ok",
      "%s %s chars" % (m2.get("status"), (m2.get("content") or {}).get("chars")))
check("the manifest says what the extra wait caught", bool(waited), str(waited))

# --screenshots counts screens of a 1280x784 window; two are glued into one 1280x1568
# picture when Pillow or PyMuPDF is there (READ_PAGE_SKIP=glue pretends neither is)
m4 = read("/tall", "--screenshots")
tiles = m4.get("screenshots") or []
sig4 = m4.get("signals") or {}
check("--screenshots alone: two screens, glued into one 1280x1568 picture",
      len(tiles) == 1 and tiles[0]["width"] == 1280 and tiles[0]["height"] == 1568
      and tiles[0].get("screens") == [1, 2] and sig4.get("screens") == 2,
      "%s; screens %s%s" % ([(t["width"], t["height"], t.get("screens")) for t in tiles], sig4.get("screens"),
                            shots_said(m4)))
check("the page admits it has more screens", (sig4.get("screens_needed") or 0) > 2, str(sig4.get("screens_needed")))
m4b = read("/tall", "--screenshots", env_extra={"READ_PAGE_SKIP": "glue"})
t4b = m4b.get("screenshots") or []
check("without Pillow or PyMuPDF the two screens come one by one, and the answer says what helps",
      len(t4b) == 2 and all(t["height"] == 784 for t in t4b)
      and any(i.get("what") == "screenshots" for i in m4b.get("improve") or []),
      "%s; improve %s%s" % ([(t["width"], t["height"]) for t in t4b], m4b.get("improve"), shots_said(m4b)))

m5 = read("/tall", "--screenshots", "3")
tiles5 = m5.get("screenshots") or []
check("--screenshots 3: screens 1-2 glued, screen 3 alone",
      [t.get("screens") for t in tiles5] == [[1, 2], [3]]
      and [t["height"] for t in tiles5] == [1568, 784] and all(t["width"] == 1280 for t in tiles5),
      str([(t["height"], t.get("screens")) for t in tiles5]) + shots_said(m5))
m5s = read("/spa", "--screenshots", "3")
t5s = m5s.get("screenshots") or []
check("a page shorter than the screens asked for gives the screens it has",
      bool(t5s) and (m5s.get("signals") or {}).get("screens", 0) <= 3
      and not (m5s.get("signals") or {}).get("screens_needed"),
      "%s %s%s" % ([(t["height"], t.get("screens")) for t in t5s], m5s.get("signals", {}).get("screens"), shots_said(m5s)))
m5b = read("/broken", "--screenshots")
why5b = (m5b.get("signals") or {}).get("screenshots_failed") or ""
check("--screenshots of a page that cannot be measured takes no picture and says why (KNOWN-ISSUES 246)",
      m5b.get("status") == "ok" and not m5b.get("screenshots") and "measuring the page" in why5b and "no height here" in why5b,
      "%s; %s%s" % (m5b.get("status"), why5b, shots_said(m5b) if not why5b else ""))

# the files must be readable by something that is not the writer: a magic check, and a decode
# by MuPDF when it is installed (it is in the offline job and can be added to this one)
bad = []
for e in tiles5:
    path = os.path.join(m5.get("dir") or "", e["file"].replace("/", os.sep))
    try:
        head = open(path, "rb").read(8)
    except OSError as exc:
        bad.append("%s: %s" % (e["file"], exc))
        continue
    if e["format"] == "png" and head[:8] != b"\x89PNG\r\n\x1a\n":
        bad.append(e["file"] + ": not a PNG")
    if e["format"] == "jpg" and head[:2] != b"\xff\xd8":
        bad.append(e["file"] + ": not a JPEG")
check("every tile is a real PNG or JPEG", not bad, str(bad)[:120])
try:
    import pymupdf
    sizes = [pymupdf.open(os.path.join(m5.get("dir") or "",
                                       e["file"].replace("/", os.sep)))[0].rect
             for e in tiles5]
    check("an independent decoder opens every tile", len(sizes) == len(tiles5),
          str([(int(s.width), int(s.height)) for s in sizes]))
except ImportError:
    print("SKIP independent decode (pymupdf is not installed here)")

m3 = read("/gate", "--clear-cookies")
check("a members-only page renders when the jar travels with the browser",
      m3.get("status") == "ok" and (m3.get("content") or {}).get("chars", 0) > 500,
      "%s %s chars" % (m3.get("status"), (m3.get("content") or {}).get("chars")))
check("the manifest counts the cookies it sent",
      ((m3.get("signals") or {}).get("cookies") or {}).get("sent", 0) >= 1,
      str((m3.get("signals") or {}).get("cookies")))

# the same tiles through MCP, as image blocks with their own captions
import json as _json

mcp = os.path.join(SKILL, "scripts", "mcp_server.py")
proc = subprocess.Popen([sys.executable, "-X", "utf8", mcp], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
n = 0


def rpc(method, params=None):
    global n
    n += 1
    msg = {"jsonrpc": "2.0", "id": n, "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write((_json.dumps(msg) + "\n").encode())
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            return {}
        try:
            got = _json.loads(line.decode("utf-8", "replace"))
        except Exception:
            continue
        if got.get("id") == n:
            return got


rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "browser-live", "version": "1"}})
proc.stdin.write((_json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode())
proc.stdin.flush()
res = rpc("tools/call", {"name": "read_url",
                         "arguments": {"url": base + "/tall", "screenshots": 1}})
blocks = (res.get("result") or {}).get("content") or []
kinds = [b.get("type") for b in blocks]
caps = [b.get("text", "") for b in blocks if b.get("type") == "text"]
check("MCP: screenshots arrive as an image block", "image" in kinds,
      str(kinds[:10]) + "".join("; " + ln for c in caps[:1] for ln in c.splitlines() if ln.startswith("screenshots:")))
check("MCP: the picture has its own caption (which screens, of how many)",
      any(c.startswith("screen 1 of ") for c in caps), [c[:40] for c in caps][-2:])
proc.stdin.close()
proc.terminate()

# the browser of a public page stays out of the local network. 127.0.0.1 is public
# in test mode, 127.0.0.2 is the internal service; it answers any origin (CORS *), so only the
# reader's own guard stands between a page script and its text.
sys.path.insert(0, HERE)
from harness import PRIVATE, PUBLIC, can_bind, serve as hserve      # noqa: E402

if can_bind(PRIVATE):
    MARK = "INTERNAL-SECRET-MARKER"
    inner = hserve({
        "/secret-cors": (200, {"Content-Type": "text/plain", "Access-Control-Allow-Origin": "*"},
                         (MARK + " " + WORDS).encode()),
        "/secret": (200, {"Content-Type": "text/html; charset=utf-8"},
                    ("<!doctype html><html><body><h1>Internal</h1><p>%s %s</p></body></html>"
                     % (MARK, WORDS)).encode()),
    }, PRIVATE)
    fetcher = ("<!doctype html><html><head><title>Fetcher</title></head><body><div id='app'></div>"
               "<script>fetch('%s').then(function(r){return r.text()}).then(function(t){"
               "document.getElementById('app').innerHTML='<h1>Got</h1><p>'+t+'</p>'}).catch(function(){"
               "document.getElementById('app').innerHTML='<h1>Nothing</h1><p>%s</p>'});</script>"
               "</body></html>") % (inner.url("/secret-cors"), WORDS)
    refresher = ("<!doctype html><html><head><title>Refresh</title><meta http-equiv='refresh' "
                 "content='0;url=%s'></head><body><div id='app'></div></body></html>") % inner.url("/secret")
    def script_page(js):
        return ("<!doctype html><html><head><title>Trap</title></head><body><div id='app'></div><script>%s"
                "</script></body></html>") % js
    shown_js = ("function show(t){document.getElementById('app').innerHTML='<h1>Got</h1><p>'+t+' %s</p>'}" % WORDS)
    inner_host = inner.url("/").split("//")[1].rstrip("/")
    traps = {
        # Playwright's request rule saw only a redirect chain's first URL
        "/s3-hop-fetch": script_page(shown_js + ";fetch('/hop-cors').then(function(r){return r.text()})"
                                     ".then(show).catch(function(e){show('blocked')})"),
        "/s3-hop-refresh": ("<!doctype html><html><head><title>Hop</title><meta http-equiv='refresh' "
                            "content='0;url=/hop'></head><body><div id='app'></div></body></html>"),
        "/s3-hop-nav": script_page("setTimeout(function(){location.href='/hop'},100)") ,
        "/s3-ws": script_page(shown_js + ";var w=new WebSocket('ws://%s/s');w.onopen=function(){show('OPEN')};"
                              "w.onerror=function(){show('blocked')}" % inner_host),
        "/s3-places": script_page(shown_js + ";Promise.all(['http://169.254.169.254/latest/meta-data/',"
                                  "'http://[::1]:%s/x','http://inside.test:%s/secret-cors'].map(function(u){"
                                  "return fetch(u).then(function(r){return r.text()}).catch(function(){return 'no'})}))"
                                  ".then(function(a){show(a.join(' '))})" % (inner_host.rsplit(":", 1)[1],
                                                                              inner_host.rsplit(":", 1)[1])),
    }
    outer = hserve(dict({k: (200, {"Content-Type": "text/html; charset=utf-8"}, v.encode()) for k, v in traps.items()},
                        **{"/hop": (302, {"Location": inner.url("/secret")}, b""),
                           "/hop-cors": (302, {"Location": inner.url("/secret-cors")}, b""),
                           "/s3-fetch": (200, {"Content-Type": "text/html; charset=utf-8"}, fetcher.encode()),
                    "/s3-refresh": (200, {"Content-Type": "text/html; charset=utf-8"}, refresher.encode()),
                    "/a3-503": (503, {"Content-Type": "text/html; charset=utf-8"}, b"")}),
                   PUBLIC)

    def read_public(url, *flags, env_extra=None):
        env = dict(os.environ, READ_PAGE_CACHE=cache, READ_PAGE_TEST_PUBLIC_HOST=PUBLIC, **(env_extra or {}))
        p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, url, "--refresh", "--json"] + list(flags),
                           capture_output=True, env=env, timeout=180)
        try:
            m = json.loads(p.stdout.decode("utf-8", "replace"))
        except Exception:
            m = {}
        text = ""
        for name in ("content.md", "page.md", "raw.html"):
            try:
                with open(os.path.join(m.get("dir") or "", name), encoding="utf-8", errors="replace") as fh:
                    text += fh.read()
            except OSError:
                pass
        return m, text

    m6, t6 = read_public(outer.url("/s3-fetch"))
    check("a page script cannot read 127.0.0.2 through the browser",
          MARK not in t6 and (m6.get("signals") or {}).get("browser_blocked", 0) >= 1,
          "%s, blocked %s" % (m6.get("status"), (m6.get("signals") or {}).get("browser_blocked")))
    m7, t7 = read_public(outer.url("/s3-refresh"))
    check("a meta refresh to 127.0.0.2 is not followed, and the manifest counts it",
          MARK not in t7 and (m7.get("signals") or {}).get("browser_blocked", 0) >= 1,
          "%s, blocked %s" % (m7.get("status"), (m7.get("signals") or {}).get("browser_blocked")))
    check("a public page renders through the guard: its own script ran, its own words arrived",
          "Nothing" in t6 and WORDS.split()[3] in t6, t6[:80].replace("\n", " "))

    # netguard, the browser's only way out - nothing reaches the inside at all
    def inner_hits():
        return len([x for x in inner.log if "secret" in x["path"] or x["path"] == "/s"])

    for path, what in (("/s3-hop-fetch", "a script's fetch whose 302 points inside"),
                       ("/s3-hop-refresh", "a meta refresh to a hop that points inside"),
                       ("/s3-hop-nav", "a page that sends itself to such a hop"),
                       ("/s3-ws", "a WebSocket to the internal service")):
        before = inner_hits()
        mg, tg = read_public(outer.url(path))
        check("%s - refused before it opens" % what,
              MARK not in tg and inner_hits() == before and (mg.get("signals") or {}).get("browser_blocked", 0) >= 1,
              "%s, blocked %s, inner hits +%d" % (mg.get("status"), (mg.get("signals") or {}).get("browser_blocked"),
                                                 inner_hits() - before))
    before = inner_hits()
    mg, tg = read_public(outer.url("/s3-places"), env_extra={"READ_PAGE_TEST_HOSTS": "inside.test=" + PRIVATE,
                                                            "READ_PAGE_DEBUG": "1"})
    refused = []
    for lp in glob.glob(os.path.join(mg.get("dir") or "", "debug", "*.jsonl")):
        with open(lp, encoding="utf-8") as fh:
            refused += [r.get("host") for r in (json.loads(x) for x in fh if x.strip())
                        if r.get("k") == "net" and r.get("ev") == "refused"]
    check("cloud metadata, [::1] and a name that resolves inside are refused",
          {"169.254.169.254", "::1", "inside.test"} <= set(refused) and inner_hits() == before and MARK not in tg,
          "refused %s" % sorted(set(refused)))
    before = inner_hits()
    mg, tg = read_public(outer.url("/s3-hop-refresh"), env_extra={"READ_PAGE_SKIP": "playwright"})
    # --dump-dom is a Chrome's path: where the only browser is Playwright's headless shell (a Linux arm64 runner
    # after --setup: no Chrome on the image) the read did not try it (chain.tried: http, extract), 2026-11-21
    if any(b.get("path") and b.get("name") != "playwright-shell" for b in mod.browsers()):
        check("Chrome's --dump-dom path goes through the guard too",
              MARK not in tg and inner_hits() == before and "cli" in str((mg.get("chain") or {}).get("tried")),
              "%s, %s, inner hits +%d" % (mg.get("status"), (mg.get("chain") or {}).get("tried"), inner_hits() - before))
    else:
        skip("Chrome's --dump-dom path goes through the guard too", "no Chrome, Chromium or Edge here (only Playwright's shell)")
    mg, tg = read_public(outer.url("/s3-hop-refresh"), env_extra={
        "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "127.0.0.1,127.0.0.2,localhost"})
    why_skipped = " ".join(str(x.get("why")) for x in (mg.get("chain") or {}).get("skipped") or []
                           if isinstance(x, dict))
    check("with a proxy of the machine's own the request rule guards, and a hop that answered from "
          "inside costs the browser's text",
          MARK not in tg and "local network" in why_skipped, "%s; %s" % (mg.get("status"), why_skipped[:90]))
    advice = str(mg.get("advice") or "")
    check("the answer says outright the browser's text was dropped, and the flag that reads it another way",
          "browser's text was not used" in advice and "local network" in advice and "--allow-external" in advice,
          advice[:120])
    # Chrome's own "This page isn't working / HTTP ERROR 503" is not the site's text
    m8, _ = read_public(outer.url("/a3-503"), "--alternate")
    shown = ""
    for name in ("content.md", "page.md"):
        try:
            with open(os.path.join(m8.get("dir") or "", name), encoding="utf-8", errors="replace") as fh:
                shown += fh.read()
        except OSError:
            pass
    check("the browser's error page is not the text, and the status is not ok",
          m8.get("status") == "error" and "This page isn" not in shown and "HTTP ERROR" not in shown,
          "%s: %s; render_error=%s" % (m8.get("status"), ((m8.get("signals") or {}).get("status_reason") or "")[:50],
                                       (m8.get("signals") or {}).get("render_error")))
    inner.close()
    outer.close()
else:
    skip("the browser and the local network", "127.0.0.2 cannot be bound here")

# a #/ route is the browser's to read, and a late page is waited for until it is
# really done - not until the text pauses for 300 ms
import advsrv                                                        # noqa: E402

adv = advsrv.start()


def read_adv(url, *flags):
    env = dict(os.environ, READ_PAGE_CACHE=cache, READ_PAGE_TEST_PUBLIC_HOST=PUBLIC)
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, url, "--refresh", "--json"] + list(flags),
                       capture_output=True, env=env, timeout=180)
    try:
        m = json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        m = {}
    try:
        with open(os.path.join(m.get("dir") or "", "content.md"), encoding="utf-8", errors="replace") as fh:
            return m, fh.read()
    except OSError:
        return m, ""


try:
    m9, t9 = read_adv(adv.public.url("/hash") + "#/pricing")
    check("a #/ route is read by the browser, not as the landing page",
          "ROUTE-MARKER" in t9 and "LANDING-MARKER" not in t9, "%s %s" % (m9.get("status"),
                                                                       (m9.get("chain") or {}).get("tried")))
    for ms in (800, 3000):
        m10, t10 = read_adv(adv.public.url("/navdelay/%d" % ms))
        check("content that arrives %.1f s after the menu is waited for" % (ms / 1000.0),
              "LATE-MARKER" in t10, "%s, %s" % (m10.get("status"), (m10.get("signals") or {}).get("browser_waited")))
finally:
    adv.stop()

srv.shutdown()
print("\n%d ok, %d failed, %d skipped" % (ok, failed, skipped))
sys.exit(0 if failed == 0 else 1)
