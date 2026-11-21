"""Honest statuses. No network. The browser's error page is in browser_live.py.

    python -X utf8 tests/statuses.py

Every check reads the manifest and the files of a run. A status is a promise: `ok` only when some
tier got a successful answer, a wall is `blocked` in any of twenty languages, and an article that
merely talks about walls stays `ok`.
"""
import base64
import importlib.util
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import advsrv                                                # noqa: E402
from harness import PUBLIC, SCRIPT, Checks, run_read         # noqa: E402

check = Checks()
H = {"Content-Type": "text/html; charset=utf-8"}
LONG_EN = ("Reading pages reliably is harder than it looks, because servers lie about what they "
           "send and scripts change what a reader sees after the first paint. ") * 30


def page(title, body):
    return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title></head><body>%s</body></html>"
            % (title, body)).encode("utf-8")


def status(r):
    return r.manifest.get("status")


def reason(r):
    return str((r.manifest.get("signals") or {}).get("status_reason") or "")


# one wall phrase per language, as the walls write it, and a sentence of ordinary prose around it
WALLS = {
    "en": ("Verify you are human", "Sites sometimes ask a visitor to verify you are human before they show a page."),
    "ru": ("Подтвердите, что вы человек", "Иногда сайт просит: подтвердите, что вы человек, и только потом показывает текст."),
    "uk": ("Підтвердьте, що ви людина", "Іноді сайт просить: підтвердьте, що ви людина, і лише потім показує текст."),
    "de": ("Bestätigen Sie, dass Sie ein Mensch sind", "Manche Seiten verlangen: Bestätigen Sie, dass Sie ein Mensch sind, bevor sie den Text zeigen."),
    "fr": ("Vérifiez que vous êtes humain", "Certains sites demandent : vérifiez que vous êtes humain, puis affichent la page."),
    "es": ("Verifica que eres humano", "Algunos sitios piden: verifica que eres humano, y luego muestran la página."),
    "pt": ("Verifique se você é humano", "Alguns sites pedem: verifique se você é humano, e depois mostram a página."),
    "it": ("Verifica di essere umano", "Alcuni siti chiedono: verifica di essere umano, e poi mostrano la pagina."),
    "nl": ("Bevestig dat u een mens bent", "Sommige sites vragen: bevestig dat u een mens bent, en tonen dan de pagina."),
    "pl": ("Potwierdź, że jesteś człowiekiem", "Niektóre strony proszą: potwierdź, że jesteś człowiekiem, a potem pokazują tekst."),
    "cs": ("Ověřte, že jste člověk", "Některé stránky žádají: ověřte, že jste člověk, a teprve potom ukážou text."),
    "tr": ("İnsan olduğunuzu doğrulayın", "Bazı siteler önce insan olduğunuzu doğrulayın der, sonra sayfayı gösterir."),
    "sv": ("Bekräfta att du är människa", "Vissa sajter ber dig: bekräfta att du är människa, och visar sedan sidan."),
    "ja": ("人間であることを確認してください", "サイトによっては、人間であることを確認してくださいと表示してからページを見せる。"),
    "zh": ("确认您是真人", "有些网站会先要求确认您是真人，然后才显示页面内容。"),
    "ko": ("사람인지 확인하십시오", "어떤 사이트는 먼저 사람인지 확인하십시오라고 요청한 뒤 페이지를 보여 준다."),
    "ar": ("تحقق من أنك إنسان", "تطلب بعض المواقع أولاً: تحقق من أنك إنسان، ثم تعرض الصفحة."),
    "hi": ("सत्यापित करें कि आप इंसान हैं", "कुछ साइटें पहले कहती हैं कि सत्यापित करें कि आप इंसान हैं, फिर पेज दिखाती हैं।"),
    "id": ("Verifikasi bahwa Anda manusia", "Beberapa situs meminta: verifikasi bahwa Anda manusia, lalu menampilkan halaman."),
    "vi": ("Xác minh bạn là con người", "Một số trang yêu cầu: xác minh bạn là con người, rồi mới hiển thị trang."),
}
FILLER = {lang: (sentence + " ") * 3 for lang, (_, sentence) in WALLS.items()}


class Flip:
    """Answers `first` while `failing` is set, then `then`: a failure that must not stay in the
    cache. A switch, not a counter: one run may make several requests (fingerprints, plain curl)."""

    def __init__(self, first, then):
        self.first, self.then, self.failing = first, then, True

    def __call__(self, h):
        if self.failing and self.first == "drop":
            h.close_connection = True
            h.connection.close()
            return
        code, body = (self.first if self.failing else self.then)
        h.send_response(code)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(body)
        h.close_connection = True


def hn(h):
    """Hacker News in 2026: 419 to a browser fingerprint, the page to a plain client."""
    plain = "read-page" in (h.headers.get("User-Agent") or "")
    body = page("Hacker News", "<article><h1>Hacker News</h1><p>HN-MARKER " + LONG_EN + "</p></article>") \
        if plain else b"Sorry."
    h.send_response(200 if plain else 419)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Connection", "close")
    h.end_headers()
    h.wfile.write(body)
    h.close_connection = True


def stub_cut(h):
    """A promise of 5 000 bytes and two words, then the connection dies."""
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", "5000")
    h.end_headers()
    h.wfile.write(b"<html><body><p>Hello there")
    h.wfile.flush()
    h.close_connection = True


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAEklEQVR4nGP8z8DAwMDAwMAAAAwGAgH/pVPoAAAAAElFTkSuQmCC")
BIG_DATA = "data:image/png;base64," + base64.b64encode(PNG + os.urandom(60000)).decode()

s = advsrv.start()
r_ = s.public.routes
r_.update({
    "/stub-cut": stub_cut,
    "/400": (400, H, page("Bad Request", "<h1>Bad Request</h1><p>" + LONG_EN[:400] + "</p>")),
    "/401": (401, H, page("Unauthorized", "<h1>Unauthorized</h1><p>" + LONG_EN[:600] + "</p>")),
    "/407": (407, H, page("Proxy Authentication Required", "<h1>Proxy</h1><p>" + LONG_EN[:600] + "</p>")),
    "/403-long": (403, H, page("Forbidden", "<article><h1>Forbidden</h1><p>" + LONG_EN + "</p></article>")),
    "/419": (419, H, b"Sorry."),
    "/451": (451, H, page("Unavailable For Legal Reasons", "<h1>Unavailable</h1><p>" + LONG_EN[:600] + "</p>")),
    "/503-wall": (503, H, page("Just a moment...", "<h1>Just a moment...</h1><p>Checking your browser before "
                                                   "accessing the site.</p>")),
    "/hn": hn,
    "/cf-header": (200, dict(H, **{"cf-mitigated": "challenge"}),
                   page("Welcome", "<article><h1>Welcome</h1><p>" + LONG_EN + "</p></article>")),
    "/challenge-markup": (200, H, page("Loading", "<div id='challenge-form'></div><script src='/cdn-cgi/"
                                       "challenge-platform/h/b/orchestrate/chl_page/v1'></script>"
                                       "<p>One more step before you continue.</p>")),
    "/datadome": (200, H, page("example.com", "<script src='https://ct.captcha-delivery.com/c.js'></script>"
                               "<p>Please wait while we check.</p>")),
    # PubMed's challenge (2026-11-20): HTTP 203, the host for a title, a script that sets a cookie
    # and reloads, and these words for a client that did neither. It read as `ok`, 14 words
    "/cookie-wall": (203, H, page("pubmed.example", "<script>document.cookie='ncbi_pass=1';location.reload()"
                                  "</script><div id='cookie-required' hidden><h1>Cookies must be enabled</h1>"
                                  "<p>Enable cookies for <span>pubmed.example</span> and reload this page to "
                                  "continue.</p></div><footer><p><a href='/vdp'>Vulnerability Disclosure</a>"
                                  "</p></footer>")),
    "/cookie-help": (200, H, page("Why cookies must be enabled for this shop",
                                  "<article><h1>Why cookies must be enabled for this shop</h1><p>" + LONG_EN
                                  + "</p></article>")),
    # a block page in Cloudflare's wording, 102 words of one paragraph with the phrase in its title,
    # served with 200: `ok` while the phrase counted under 60 words only (2026-11-21)
    "/cookie-wall-102": (200, H, page("Please enable cookies.", "<h1>Please enable cookies.</h1><p>Sorry, you have "
                                      "been blocked. You are unable to access shop.example. Why have I been blocked? "
                                      "This website is using a security service to protect itself from online attacks. "
                                      "The action you just performed triggered the security solution. There are several "
                                      "actions that could trigger this block including submitting a certain word or "
                                      "phrase, a SQL command or malformed data. What can I do to resolve this? You can "
                                      "email the site owner to let them know you were blocked. Please include what you "
                                      "were doing when this page came up and the Ray ID found at the bottom of this "
                                      "page.</p>")),
    # a short help page about the same: 127 words, the phrase in its title and heading. It read as
    # `blocked`, "a challenge page" (2026-11-20)
    "/cookie-help-short": (200, H, page(
        "Please enable cookies | Example Help Center",
        "<header><a href='/'>Example Help Center</a></header><main><article><h1>Please enable cookies</h1>"
        "<p>Our checkout keeps your basket in a cookie, so the shop cannot work when your browser blocks "
        "cookies. Here is how to allow them for our site in the common browsers.</p><h2>Chrome</h2><p>Open "
        "Settings, then Privacy and security, then Third-party cookies. Choose Allow third-party cookies, or "
        "add our address under Sites allowed to use third-party cookies.</p><h2>Firefox</h2><p>Open Settings, "
        "then Privacy and Security. Under Enhanced Tracking Protection choose Standard, or add an exception "
        "for our address under Cookies and Site Data.</p><h2>Safari</h2><p>Open Settings, then Privacy, and "
        "clear Block all cookies. Reload the shop afterwards; your basket comes back when you sign in "
        "again.</p><p>Still stuck? Write to our support team and tell us which browser and version you "
        "use.</p></article></main>")),
    "/title-long": (200, H, page("Access denied: a short history of paywalls",
                                 "<article><h1>Access denied: a short history of paywalls</h1><p>"
                                 + LONG_EN + "</p></article>")),
    "/moment-long": (200, H, page("Just a moment of silence",
                                  "<article><h1>Just a moment of silence</h1><p>" + LONG_EN + "</p></article>")),
    "/inline": (200, H, page("Inline", "<article><h1>Inline picture</h1><p>" + LONG_EN
                             + "</p><img src='%s' alt='inline'><p>INLINE-MARKER after the picture.</p></article>"
                             % BIG_DATA)),
    "/flip-drop": Flip("drop", (200, page("Back", "<article><h1>Back</h1><p>FLIP-OK " + LONG_EN + "</p></article>"))),
    "/flip-503": Flip((503, page("Maintenance", "<h1>Back soon</h1><p>" + LONG_EN[:500] + "</p>")),
                      (200, page("Back", "<article><h1>Back</h1><p>FLIP-OK " + LONG_EN + "</p></article>"))),
    "/flip-429": Flip((429, page("Too Many Requests", "<h1>Too Many Requests</h1>")),
                      (200, page("Back", "<article><h1>Back</h1><p>FLIP-OK " + LONG_EN + "</p></article>"))),
})
for lang, (phrase, sentence) in WALLS.items():
    r_["/wall/" + lang] = (200, H, page(phrase, "<h1>%s</h1><p>%s</p>" % (phrase, phrase)))
    prose = " ".join([FILLER[lang]] * 12)
    r_["/article/" + lang] = (200, H, page("Article " + lang, "<article><h1>Article</h1><p>%s</p></article>" % prose))

try:
    # ------------------------------------------------ a cut transfer says so
    for path in ("/truncated", "/stall"):
        r = run_read(s.public.url(path))
        sig = r.manifest.get("signals") or {}
        check("%s: signals.partial, and the answer says how to get the rest" % path,
              sig.get("partial") is True and ("--refresh" in (r.manifest.get("advice") or "")
                                             or "--download" in (r.manifest.get("advice") or "")),
              "%s partial=%s advice=%s" % (status(r), sig.get("partial"), (r.manifest.get("advice") or "")[:60]))
        check("%s: the first line of the answer says partial" % path,
              " partial" in r.text.split("\n")[0], r.text.split("\n")[0][:90])
    r = run_read(s.public.url("/stub-cut"))
    check("two words and a broken connection are not a page", status(r) != "ok",
          "%s: %s" % (status(r), reason(r)[:60]))

    # ------------------------------------------------ the code of the tier that gave the text
    expect = {"/500": "error", "/503": "error", "/400": "error", "/401": "login_required",
              "/407": "login_required", "/403-long": "blocked", "/419": "blocked", "/451": "blocked",
              "/503-wall": "blocked", "/404": "not_found"}
    r_["/404"] = (404, H, page("Not Found", "<h1>Not Found</h1><p>" + LONG_EN[:600] + "</p>"))
    for path, want in expect.items():
        r = run_read(s.public.url(path))
        check("%s -> %s" % (path, want), status(r) == want, "%s: %s" % (status(r), reason(r)[:60]))
    # with no Playwright the browser is Chrome's --dump-dom, which knows no HTTP status; the
    # server's code must still decide (it was `empty` on the CI runners: Chrome, no Playwright)
    r = run_read(s.public.url("/419"), env={"READ_PAGE_SKIP": "playwright"})
    tried = " ".join((r.manifest.get("chain") or {}).get("tried") or [])
    if "browser:cli" not in tried:
        check.skip("/419 through Chrome's --dump-dom", "no Chrome here (%s)" % tried)
    else:
        check("/419 through Chrome's --dump-dom -> blocked, the code named as the server's",
              status(r) == "blocked" and "from the server" in reason(r), "%s: %s" % (status(r), reason(r)[:60]))
    r = run_read(s.public.url("/500"))
    check("an error page's own text is kept",       # the body: trafilatura drops the <h1>
          "servers are having trouble" in r.file("content.md") and "500" in reason(r), reason(r)[:60])
    r = run_read(s.public.url("/hn"))
    check("a 419 to every fingerprint, then plain curl gets the page", status(r) == "ok"
          and "HN-MARKER" in r.file("content.md"), "%s %s" % (status(r), (r.manifest.get("chain") or {}).get("tried")))

    # ------------------------------------------------ walls without words, then in twenty languages
    for path in ("/anubis", "/xwrong", "/cf-header", "/challenge-markup", "/datadome"):
        r = run_read(s.public.url(path))
        check("%s is a wall" % path, status(r) == "blocked", "%s: %s" % (status(r), reason(r)[:60]))
    for path in ("/title-long", "/moment-long", "/cookie-help"):
        r = run_read(s.public.url(path))
        check("%s: a long article with the words in its title is an article" % path, status(r) == "ok",
              "%s: %s" % (status(r), reason(r)[:60]))
    r = run_read(s.public.url("/cookie-wall"))
    check("/cookie-wall: \"Cookies must be enabled ... reload this page\" is a wall, not a page of 14 words",
          status(r) == "blocked", "%s: %s | %r" % (status(r), reason(r)[:60], r.file("content.md")[:60]))
    r = run_read(s.public.url("/cookie-help-short"))
    check("/cookie-help-short: a help page of 127 words titled \"Please enable cookies\" is a page, not a wall",
          status(r) == "ok" and "Third-party cookies" in r.file("content.md"),
          "%s: %s" % (status(r), reason(r)[:60]))
    r = run_read(s.public.url("/cookie-wall-102"))
    check("/cookie-wall-102: a cookie wall of 102 words with no sections, served with 200, is a wall",
          status(r) == "blocked", "%s: %s" % (status(r), reason(r)[:60]))
    walls_missed, articles_hit = [], []
    for lang in WALLS:
        if status(run_read(s.public.url("/wall/" + lang))) != "blocked":
            walls_missed.append(lang)
        if status(run_read(s.public.url("/article/" + lang))) != "ok":
            articles_hit.append(lang)
    check("a wall is blocked in all %d languages" % len(WALLS), not walls_missed, "missed: %s" % walls_missed)
    check("an article that quotes the wall is ok in all %d languages" % len(WALLS), not articles_hit,
          "wrong: %s" % articles_hit)

    # ------------------------------------------------ an archived PDF goes through the document path
    spec = importlib.util.spec_from_file_location("rp_status_a8", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-status-")
    spec.loader.exec_module(mod)
    try:
        import pymupdf
        doc = pymupdf.open()
        pg = doc.new_page()
        pg.insert_text((72, 72), "ARCHIVED-PDF-MARKER a document that only the archive still has.", fontsize=11)
        for i in range(30):
            pg.insert_text((72, 100 + 18 * i), "Line %d of the archived report, ordinary prose for the reader." % i,
                           fontsize=10)
        pg = doc.new_page()                                  # and a table, whose layout is the read's too
        pg.insert_text((72, 80), "Table 1: Archived results by region", fontsize=10)
        pg.draw_line((72, 92), (470, 92))
        for k, row in enumerate([("Region", "North", "South")] + [("Area %d" % n, "%d.25" % (n * 7), "%d.75" % (n * 3))
                                                                  for n in range(1, 7)]):
            for x, cell in zip((76, 230, 360), row):
                pg.insert_text((x, 106 + 18 * k), cell, fontsize=10)
        pg.draw_line((72, 112), (470, 112))
        pg.draw_line((72, 236), (470, 236))
        pdf = doc.tobytes()
        mod.wayback = lambda url: (pdf, "application/pdf", "archive:wayback", "20200101000000")
        out = io.StringIO()
        old, sys.stdout = sys.stdout, out
        try:
            mod.main([s.public.url("/404"), "--allow-external", "--json", "--dir", tempfile.mkdtemp(prefix="rp-a8-")])
        finally:
            sys.stdout = old
        m = json.loads(out.getvalue() or "{}")
        text = open(os.path.join(m.get("dir") or "", "content.md"), encoding="utf-8").read() if m.get("dir") else ""
        check("an archived PDF is read as a PDF, not decoded as HTML",
              "ARCHIVED-PDF-MARKER" in text and "%PDF" not in text, "%s %s" % (m.get("status"), text[:60]))
        tab = (m.get("signals") or {}).get("tables") or {}
        if importlib.util.find_spec("pymupdf4llm") and importlib.util.find_spec("onnxruntime"):
            check("an archived PDF's tables are the read's: laid out, and in the manifest",
                  tab.get("pages") == "2" and any(ln.startswith("|") and "Area 1" in ln and "7.25" in ln and "3.75" in ln
                                                  for ln in text.splitlines()), "%s %r" % (tab, text[-300:]))
        else:
            check.skip("an archived PDF's tables", "no layout model in the suite's Python")
    except ImportError:
        check.skip("an archived PDF", "pymupdf is not installed here")

    # ------------------------------------------------ an archived page that comes gzipped
    # Wayback's id_ hands the payload as the site sent it; urllib unpacks nothing, and Crunchbase's
    # copy was decoded as KOI8-R: 199 KB of mojibake answered as `ok`
    import gzip as _gzip
    from harness import serve as _serve
    arch_page = ("<!doctype html><html><head><meta charset='utf-8'><title>Archived</title></head><body><article>"
                 "<h1>Archived</h1>" + "<p>ARCHIVE-GZ-MARKER Эту страницу хранит только архив, и она пришла сжатой.</p>" * 30
                 + "</article></body></html>").encode("utf-8")

    def cdx(h):
        import urllib.parse as _up
        want = _up.parse_qs(_up.urlsplit(h.path).query).get("url", [""])[0]
        body = ("20200101000000 %s\n" % want).encode("utf-8")
        h.send_response(200)
        h.send_header("Content-Type", "text/plain")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)
    snap = "/web/20200101000000id_/https://example.com/"
    arch = _serve({"/cdx/search/cdx": cdx,
                   snap + "gz-header": (200, {"Content-Type": "text/html", "Content-Encoding": "gzip"}, _gzip.compress(arch_page)),
                   snap + "gz-bare": (200, {"Content-Type": "text/html"}, _gzip.compress(arch_page)),
                   snap + "br": (200, {"Content-Type": "text/html", "Content-Encoding": "br"}, os.urandom(3000))})
    spec_gz = importlib.util.spec_from_file_location("rp_status_gz", SCRIPT)
    mod_gz = importlib.util.module_from_spec(spec_gz)          # the check above replaced its module's wayback()
    spec_gz.loader.exec_module(mod_gz)
    try:
        mod_gz.WAYBACK_URL = arch.url("")
        mod_gz.budget.start(mod_gz.budget.SECONDS)
        got = {k: mod_gz.archived_text("https://example.com/" + k, mod_gz.caps(), tempfile.mkdtemp(prefix="rp-gz-"))
               for k in ("gz-header", "gz-bare", "br")}
        ok_gz = all("ARCHIVE-GZ-MARKER" in (got[k][0] or "") and "Эту страницу хранит" in got[k][0]
                    for k in ("gz-header", "gz-bare"))
        check("an archived page sent gzipped, with the header or without it, is read as its text",
              ok_gz, "; ".join("%s: %r" % (k, (got[k][0] or got[k][5])[:60]) for k in ("gz-header", "gz-bare")))
        check("one that cannot be unpacked is no text, with the reason, not mojibake",
              not got["br"][0] and "unpack" in (got["br"][5] or ""), repr(got["br"][5])[:100])
    finally:
        arch.close()

    # ------------------------------------------------ too big is a status, not a crash
    mod.MAX_DOWNLOAD = 1000
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        mod.main([s.public.url("/gallery"), "--json", "--refresh", "--dir", tempfile.mkdtemp(prefix="rp-a9-")])
    finally:
        sys.stdout = old
    m = json.loads(out.getvalue() or "{}")
    limit = str((m.get("signals") or {}).get("limit") or "")
    check("a body over the cap is too_large, with the cap named",
          m.get("status") == "too_large" and "cap" in limit, "%s: %s" % (m.get("status"), limit[:70]))

    # ------------------------------------------------ no data: payload anywhere
    import re
    for flags in ((), ("--deny-images",)):
        r = run_read(s.public.url("/inline"), *flags)
        blob = r.text + "".join(r.file(n) for n in ("content.md", "page.md", "manifest.json"))
        run = max([len(x) for x in re.findall(r"[A-Za-z0-9+/=]{100,}", blob)] or [0])
        check("%s: no base64 payload in the answer, the text or the manifest" % (" ".join(flags) or "pictures on"),
              run < 300 and "INLINE-MARKER" in r.file("content.md"), "longest base64-like run %d" % run)

    # ------------------------------------------------ a failure is not kept for 15 minutes
    for path in ("/flip-drop", "/flip-503", "/flip-429"):
        r_[path].failing = True
        first = run_read(s.public.url(path))
        r_[path].failing = False
        again = run_read(s.public.url(path), reuse=first)
        check("%s: the failure is not served from the cache" % path,
              status(first) != "ok" and status(again) == "ok" and "FLIP-OK" in again.file("content.md"),
              "%s then %s (%s)" % (status(first), status(again), again.manifest.get("cache")))
    first = run_read(s.public.url("/404"))
    again = run_read(s.public.url("/404"), reuse=first)
    check("not_found is a real answer and is kept", again.manifest.get("cache") == "hit", str(again.manifest.get("cache")))

    # ------------------------------------------------ advice never repeats the flag just given
    r = run_read(s.public.url("/wall/en") + "?token=abc123", "--allow-external")
    check("a refused --allow-external is not advised again", "--allow-external" not in (r.manifest.get("advice") or "")
          and "--force-external" in (r.manifest.get("advice") or ""), (r.manifest.get("advice") or "")[:80])
finally:
    s.stop()

sys.exit(check.done())
