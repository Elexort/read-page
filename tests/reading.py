"""Reading: encodings, dead hosts, readers, retries. No network.
Hash routes and late JavaScript need a browser: they are in browser_live.py.

    python -X utf8 tests/reading.py

The page in any encoding a server forgets to declare; a dead host or a 5xx goes to the readers and
the archive when that is allowed; a video site's ordinary page is a page; Jina gets the address in
a POST body; a machine without curl still reads; a 503 gets one more try; defuddle knows the page's
address, so relative links do not turn into about:blank.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import advsrv                                                # noqa: E402
from harness import PUBLIC, SCRIPT, Checks, run_read         # noqa: E402

check = Checks()
H = {"Content-Type": "text/html; charset=utf-8"}


def page(title, body, head=""):
    return "<!doctype html><html><head>%s<title>%s</title></head><body><article><h1>%s</h1><p>%s</p></article></body></html>" % (
        head, title, title, body)


RU = ("Съешь же ещё этих мягких французских булок, да выпей чаю. Широкая электрификация южных губерний "
      "даст мощный толчок подъёму сельского хозяйства. ") * 12
JP = "吾輩は猫である。名前はまだ無い。どこで生れたかとんと見当がつかぬ。何でも薄暗いじめじめした所でニャーニャー泣いていた事だけは記憶している。" * 12
ZH = "中华人民共和国的首都是北京，这是一个历史悠久的城市，拥有许多著名的景点和丰富的文化遗产。" * 14
KO = "대한민국의 수도는 서울이며 역사가 깊고 많은 유명한 명소와 풍부한 문화유산을 가지고 있습니다. " * 14
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ") * 14


def module():
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-read-")
    spec = importlib.util.spec_from_file_location("rp_read_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inproc(mod, argv):
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        mod.main(argv + ["--json", "--dir", tempfile.mkdtemp(prefix="rp-read-out-")])
    finally:
        sys.stdout = old
    try:
        m = json.loads(out.getvalue() or "{}")
    except ValueError:
        m = {}
    text = ""
    if m.get("dir") and os.path.isfile(os.path.join(m["dir"], "content.md")):
        text = open(os.path.join(m["dir"], "content.md"), encoding="utf-8").read()
    return m, text


class Count:
    """Answers `first` for the first `times` requests, then `then`."""

    def __init__(self, first, then, times=1):
        self.first, self.then, self.times, self.n = first, then, times, 0
        self.lock = threading.Lock()

    def __call__(self, h):
        with self.lock:
            self.n += 1
            n = self.n
        code, body = self.first if n <= self.times else self.then
        h.send_response(code)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(body)
        h.close_connection = True


s = advsrv.start()
pub = s.public.routes
pub.update({
    "/utf16": (200, {"Content-Type": "text/html"}, page("Документ", RU).encode("utf-16")),
    "/sjis": (200, {"Content-Type": "text/html"}, page("文書", JP).encode("shift_jis")),
    "/gbk": (200, {"Content-Type": "text/html"}, page("文档", ZH).encode("gbk")),
    "/euckr": (200, {"Content-Type": "text/html"}, page("문서", KO).encode("euc-kr")),
    "/bad-meta": (200, {"Content-Type": "text/html"}, page("Документ", RU, "<meta charset='utf-8'>").encode("cp1251")),
    "/utf8": (200, {"Content-Type": "text/html"}, page("Документ", RU).encode("utf-8")),
    "/r12": Count((503, b"<h1>Service Unavailable</h1>"),
                  (200, page("Back", "RETRY-OK " + EN).encode("utf-8"))),
    "/relative": (200, H, ("<!doctype html><html><head><title>Links</title></head><body><article><h1>Links</h1><p>"
                           + EN + " <a href='/docs/next.html'>the next chapter</a> and <a href='part2.html'>part two</a>."
                           "</p></article></body></html>").encode("utf-8")),
    "/watch-page": (200, H, page("About this video site", "VIDEO-SITE-PAGE " + EN).encode("utf-8")),
})

try:
    # ------------------------------------------------ the encoding a server forgot to say
    cases = {"/koi8-none": "булок", "/cp1251-none": "булок", "/koi8-header": "булок", "/latin1-lie": "булок",
             "/utf16": "булок", "/sjis": "吾輩は猫", "/gbk": "中华人民", "/euckr": "대한민국",
             "/bad-meta": "булок", "/utf8": "булок"}
    wrong = []
    for path, needle in cases.items():
        r = run_read(s.public.url(path), "--json")
        if needle not in r.file("content.md"):
            wrong.append("%s (%s)" % (path, (r.manifest.get("url") or {}).get("charset")))
    check("%d encodings, declared or not, read right" % len(cases), not wrong, ", ".join(wrong))

    # ------------------------------------------------ one more try on 502/503/504
    r = run_read(s.public.url("/r12"), "--json", env={"READ_PAGE_SKIP": "browser"})   # the HTTP step itself
    check("a 503 then a 200 is the page", r.manifest.get("status") == "ok" and "RETRY-OK" in r.file("content.md"),
          "%s, %d requests" % (r.manifest.get("status"), pub["/r12"].n))

    # ------------------------------------------------ a dead host or a 5xx goes to the readers and the archive
    mod = module()
    seen = []
    mod.external_read = lambda url, c, refresh=False: (seen.append(url), (
        "# Rescued\n\n" + "READER-TEXT " + EN, "reader:jina", 200, ""))[1]
    mod.wayback = lambda url: (b"", "", "archive:wayback", "never archived")
    dead = "http://%s:%d/gone" % (PUBLIC, 9)            # discard port: nothing listens
    m, text = inproc(mod, [dead, "--allow-external"])
    check("a host that does not answer is tried through a reader with --allow-external",
          bool(seen) and m.get("status") == "ok" and "READER-TEXT" in text, "%s, readers %d" % (m.get("status"), len(seen)))
    seen.clear()
    m, text = inproc(mod, [dead])
    check("without the flag nothing leaves, and the advice names the flag",
          not seen and m.get("status") == "error" and "--allow-external" in (m.get("advice") or ""),
          (m.get("advice") or "")[:70])
    mod2 = module()
    archived = []
    mod2.external_read = lambda url, c, refresh=False: ("", "reader:jina", None, "no text")
    mod2.wayback = lambda url: (archived.append(url), (page("Archived", "ARCHIVE-TEXT " + EN).encode(), "text/html",
                                                       "archive:wayback", "20240101000000"))[1]
    pub["/503-long"] = (503, H, page("Maintenance", "We are down for maintenance. " + EN).encode())
    m, text = inproc(mod2, [s.public.url("/503-long"), "--allow-external"])
    check("a 5xx with --allow-external is answered from the archive", bool(archived)
          and "ARCHIVE-TEXT" in text and m.get("status") == "ok", "%s, archive %d" % (m.get("status"), len(archived)))
    # runoob timed out once, the archive answered "the live page is gone", and that copy
    # was the answer for 15 minutes though the page was back a minute later
    adv = m.get("advice") or ""
    check("after a 5xx the archive copy says what the live page did, not that it is gone, and names --refresh",
          "answered HTTP 503" in adv and "--refresh" in adv and "gone" not in adv, adv[:120])
    n0 = len(archived)
    m2, _ = inproc(mod2, [s.public.url("/503-long"), "--allow-external"])
    mpath = os.path.join(mod2.page_dir(s.public.url("/503-long")), "manifest.json")
    with open(mpath, encoding="utf-8") as fh:
        cm = json.load(fh)
    cm["_cached_at"] -= 120                              # two minutes later
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(cm, fh)
    m3, _ = inproc(mod2, [s.public.url("/503-long"), "--allow-external"])
    check("such a rescue comes from the cache for a minute, then the live page is asked again",
          m2.get("cache") == "hit" and m3.get("cache") != "hit" and len(archived) == n0 + 1,
          "%s then %s, archive asked %d more" % (m2.get("cache"), m3.get("cache"), len(archived) - n0))

    # ------------------------------------------------ a video site's ordinary page is a page
    mod3 = module()
    pats = {"https://www.youtube.com/watch?v=dQw4w9WgXcQ": True, "https://youtu.be/dQw4w9WgXcQ": True,
            "https://vimeo.com/76979871": True, "https://vimeo.com/about": False,
            "https://www.tiktok.com/@scout2015/video/6718335390845095173": True, "https://www.tiktok.com/about": False,
            "https://www.twitch.tv/videos/1234567890": True, "https://www.twitch.tv/directory": False,
            "https://rutube.ru/video/0123456789abcdef0123456789abcdef/": True, "https://rutube.ru/feeds/": False,
            "https://vk.com/video-12345_67890": True, "https://ok.ru/video/123456789": True,
            "https://www.dailymotion.com/video/x7tgad0": True, "https://www.dailymotion.com/us": False}
    wrong = [u for u, want in pats.items() if bool(mod3.VIDEO_URL.search(u)) != want]
    check("only real video addresses take the subtitle path (%d cases)" % len(pats), not wrong, ", ".join(wrong[:3]))
    mod3.VIDEO_URL = __import__("re").compile(r"/watch-page")
    mod3.video_text = lambda url, c, workdir: ("", "A video", "no subtitles in en,ru (set READ_PAGE_SUB_LANGS to change)")
    m, text = inproc(mod3, [s.public.url("/watch-page")])
    check("no subtitles - the page is read as a page, and the manifest says why",
          "VIDEO-SITE-PAGE" in text and m.get("status") == "ok" and (m.get("signals") or {}).get("no_transcript"),
          "%s %s" % (m.get("status"), (m.get("signals") or {}).get("no_transcript")))

    # ------------------------------------------------ Jina gets the address in a POST body
    import http.server
    import socketserver
    got = []

    class Jina(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n).decode("utf-8", "replace")
            got.append(("POST", body, self.headers.get("X-No-Cache", "")))
            cached = len(got) == 1 and "/cached" in body
            text = ("Warning: This is a cached snapshot of the original page, consider retry with caching opt-out.\n\n"
                    if cached else "") + "Title: Doc\n\nMarkdown Content:\n" + "JINA-TEXT " + EN
            if "/walled" in body:
                text = "Title: Just a moment...\n\nMarkdown Content:\nChecking your browser before accessing the site."
            b = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            got.append(("GET", self.path, ""))
            self.send_response(405)
            self.end_headers()

        def log_message(self, *a):
            pass

    jsrv = socketserver.ThreadingTCPServer((PUBLIC, 0), Jina)
    jsrv.daemon_threads = True
    threading.Thread(target=jsrv.serve_forever, daemon=True).start()
    mod4 = module()
    mod4.JINA_URL = "http://%s:%d/" % (PUBLIC, jsrv.server_address[1])
    mod4.READERS = ("jina",)               # the chain itself is tests/sources.py; nothing real is asked
    os.environ.pop("FIRECRAWL_API_KEY", None)
    target = "https://docs.example.org/путь/#/quickstart"
    text, eng, st, note = mod4.external_read(target, mod4.caps())
    sent = got[-1] if got else ("", "", "")
    check("Jina is asked by POST, with the #/ route and the Cyrillic path intact",
          sent[0] == "POST" and json.loads(sent[1] or "{}").get("url") == target and "JINA-TEXT" in (text or ""),
          "%s %s" % (sent[0], (sent[1] or "")[:80]))
    got.clear()
    text, eng, st, note = mod4.external_read("https://example.org/cached", mod4.caps())
    check("a cached snapshot is asked again with x-no-cache", len(got) == 2 and got[1][2].lower() == "true"
          and "JINA-TEXT" in (text or ""), str([(g[0], g[2]) for g in got]))
    got.clear()
    text, eng, st, note = mod4.external_read("https://example.org/walled", mod4.caps())
    check("a wall that Jina hit is not text", not text, note[:70])
    jsrv.shutdown()

    # ------------------------------------------------ no curl_cffi and no curl - urllib reads the page
    mod5 = module()
    caps0 = mod5.caps()
    caps0["libs"]["curl_cffi"] = False
    mod5.caps = lambda: caps0
    real_which = mod5.which
    mod5.which = lambda name: None if "curl" in str(name) else real_which(name)
    m, text = inproc(mod5, [s.public.url("/utf8")])
    check("without curl_cffi and curl the page is still read (urllib)",
          m.get("status") == "ok" and "булок" in text and "urllib" in str((m.get("chain") or {}).get("tried")),
          "%s %s" % (m.get("status"), (m.get("chain") or {}).get("tried")))

    # ------------------------------------------------ defuddle knows the page's address
    if mod5.which("defuddle") or real_which("defuddle"):
        r = run_read(s.public.url("/relative"))
        body = r.file("content.md")
        check("relative links resolve against the page, never about:blank",
              "about:blank" not in body and s.public.url("/docs/next.html") in body
              and s.public.url("/part2.html") in body,
              [ln for ln in body.split("\n") if "next" in ln][:1])
    else:
        check.skip("defuddle and relative links", "defuddle is not installed here")

    # ------------------------------------------------ a wall: the advice names no step that only repeats
    # 2026-11-19: --alternate opened none of 8 walls in a measured run (the browser had been at 6, and
    # met the same wall at the other 2), and agents at a wall spent a call on it, because the advice
    # named it
    wall = ("<!doctype html><html><head><title>Just a moment...</title></head><body><h1>Just a moment...</h1>"
            "<p>Checking your browser before accessing the site.</p></body></html>").encode("utf-8")
    pub["/wall"] = (403, H, wall)
    mod6 = module()
    mod6.SKIP.add("browser")
    asked = []
    mod6.external_read = lambda url, c, refresh=False: (asked.append(url), (
        "", "reader:jina/defuddle.md", 403, "jina: the page answered it 403"))[1]
    m, _ = inproc(mod6, [s.public.url("/wall")])
    adv = m.get("advice") or ""
    check("a wall, readers not allowed yet: the advice is --allow-external and nothing else",
          m.get("status") == "blocked" and "--allow-external" in adv and "--alternate" not in adv and not asked, adv)
    m, _ = inproc(mod6, [s.public.url("/wall"), "--allow-external"])
    adv = m.get("advice") or ""
    check("a wall the readers did not pass either: no flag is named, the next step is another source",
          m.get("status") == "blocked" and bool(asked) and "--" not in adv and "the public readers were stopped too" in adv
          and "another source" in adv, adv)
    mod7 = module()
    mod7.SKIP.add("browser")
    pub["/hollow"] = (200, H, b"<!doctype html><html><head><title>App</title></head><body><div id='root'></div>"
                              b"<script>render()</script></body></html>")
    m, _ = inproc(mod7, [s.public.url("/hollow")])
    adv = m.get("advice") or ""
    check("an empty page with no browser to render it: --alternate is not offered, a reader is",
          m.get("status") == "empty" and "--alternate" not in adv and "--allow-external" in adv, adv)

    # ------------------------------------------------ a thin app page goes to the browser by itself
    # 2026-11-19, 168 pages measured: four gave under 200 words while shipping 40 KB+ of data
    # for their own scripts (soundcloud 50 words, aliexpress 79, ivi 163, a GitHub issue 118), and
    # the browser then gave 30, 9 and 5 times the text on three of them. Only --alternate reached
    # it, and an agent on ivi kept digging in raw.html until its turns ran out.
    state = json.dumps({"items": [{"id": i, "title": "Film number %d" % i, "about": EN[:120]} for i in range(400)]})
    teaser = "<p>" + " ".join(["teaser"] * 150) + "</p>"
    shell = "<!doctype html><html><head><title>Portal</title></head><body><main><h1>Portal</h1>%s</main>%s</body></html>"
    pub["/thin-app"] = (200, H, (shell % (teaser, "<script id='__NEXT_DATA__' type='application/json'>%s</script>"
                                          % state)).encode("utf-8"))
    pub["/short-page"] = (200, H, (shell % (teaser, "<script>console.log('a short page with a script')</script>")).encode("utf-8"))
    # JSON-LD is for search engines, no script draws it: a product page with its reviews as 63 KB of
    # it went to the browser for 3.2 s and the same 144 words (2026-11-21)
    pub["/ld-json"] = (200, H, (shell % (teaser, "<script type='application/ld+json'>%s</script>" % state)).encode("utf-8"))
    mod8 = module()
    mod8.SKIP.add("browser")                     # the decision is what is tested: the browser's turn is recorded
    asked8 = []
    for path in ("/thin-app", "/short-page", "/ld-json"):
        m, _ = inproc(mod8, [s.public.url(path)])
        asked8.append([x.get("why") for x in (m.get("chain") or {}).get("skipped") or [] if x.get("tier") == "browser"])
    check("under 200 words beside 40 KB+ of the page's own data: the browser's turn; a short page with a script: not",
          bool(asked8[0]) and not asked8[1] and len(state) > 40000, "%s / %s (%d KB of data)" % (asked8[0], asked8[1], len(state) // 1000))
    check("... nor a short page whose data is JSON-LD for search engines (application/ld+json)",
          not asked8[2] and mod8.shipped_state("<script type=\"application/ld+json\">%s</script>" % state) == 0,
          str(asked8[2]))
finally:
    s.stop()

sys.exit(check.done())
