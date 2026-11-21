"""Adversarial pages: each route reproduces one failure a page reader must not hide.

    import advsrv; s = advsrv.start(); ... s.public.url("/ok") ...; s.stop()
    python tests/advsrv.py            # serve by hand and print the addresses

Three servers: `public` on 127.0.0.1 (public in test mode), `private` on 127.0.0.2 (stays private:
the target of every "must not reach" route) and `guarded`, a third-party image host that answers
only with a Referer. Requests land in each server's in-memory log.
"""
import base64
import os
import sys
import tempfile
import threading
import time

from harness import PRIVATE, PUBLIC, can_bind, serve

RU = ("Съешь же ещё этих мягких французских булок, да выпей чаю. Широкая электрификация южных "
      "губерний даст мощный толчок подъёму сельского хозяйства. ") * 12
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ") * 14
PNG1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAEklEQVR4nGP8z8DAwMDAwMAAAAwGAgH/pVPoAAAAAElFTkSuQmCC")
HTML = {"Content-Type": "text/html; charset=utf-8"}


def page(title, body, head=""):
    return "<!doctype html><html><head>%s<title>%s</title></head><body>%s</body></html>" % (head, title, body)


def html(code, text, ctype="text/html; charset=utf-8", extra=None):
    body = text.encode("utf-8") if isinstance(text, str) else text
    return code, dict({"Content-Type": ctype}, **(extra or {})), body


def redirect(location):
    return 302, {"Location": location}, b""


NAV = "<nav>" + " ".join('<a href="/s%d">Section number %d of this site</a>' % (i, i) for i in range(14)) + "</nav>"
HASH_LANDING = page(
    "Acme Router",
    "<article><h1>Acme landing page</h1><p>LANDING-MARKER " + EN + "</p></article><div id='r'></div>"
    "<script>function go(){if(location.hash.indexOf('#/pricing')==0){document.querySelector('article').outerHTML="
    "'<article><h1>Pricing</h1><p>ROUTE-MARKER the plan costs 42 credits a month. '+'Details of the plan follow here. '"
    ".repeat(30)+'</p></article>';}}go();addEventListener('hashchange',go);</script>")


def nav_delay(ms):
    return page("App", NAV + "<main id='m'>Loading…</main><script>setTimeout(function(){document.getElementById('m')"
                ".innerHTML='<article><h1>Late article</h1><p>LATE-MARKER '+'The late content arrives after the "
                "navigation is painted. '.repeat(40)+'</p></article>';},%d);</script>" % ms)


ANUBIS = page("Making sure you&#39;re not a bot!",
              "<h1>Making sure you're not a bot!</h1><p>You are seeing this because the administrator of this "
              "website has set up Anubis to protect the server against the scourge of AI companies aggressively "
              "scraping websites. Anubis uses a Proof-of-Work scheme. Please wait while we calculate the "
              "challenge, this should only take a moment or two. Enable JavaScript if the page does not continue.</p>")
XWRONG = page("X", "<div><h1>Something went wrong</h1><p>Something went wrong, but don't fret — let's give it "
                   "another shot. Try reloading. Some privacy related extensions may cause issues on x.com. Please "
                   "disable them and try again.</p></div>")
ERR500 = page("Internal Server Error", "<h1>We hit a snag</h1><p>" + (
    "Our servers are having trouble handling your request right now, and the team has been notified about the "
    "incident. Please try again in a few minutes, or visit our status page for updates about the ongoing problem. ") * 6 + "</p>")
MAINT503 = page("Scheduled maintenance", "<h1>Back soon</h1><p>" + (
    "This site is down for scheduled maintenance while the database is being upgraded. Everything will be back to "
    "normal shortly, and no data will be lost during the window. ") * 6 + "</p>")
OLD_RU = page("Заголовок", "<article><h1>Старая страница</h1><p>" + RU + "</p></article>")
LONG = page("Long story", "<article><h1>Long story</h1><p>BEGIN-MARKER " + EN + "</p>").encode()


def _promise_more(h, wait=0):
    """Content-Length three times the body, half a page, then (after `wait`) the connection dies."""
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(LONG) * 3))
    h.end_headers()
    h.wfile.write(LONG)
    h.wfile.flush()
    if wait:
        time.sleep(wait)
    h.close_connection = True


def _trickle(h):
    """One chunk a second for 150 s: never slow enough to trip a per-read timeout."""
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Transfer-Encoding", "chunked")
    h.end_headers()
    t0 = time.time()
    try:
        while time.time() - t0 < 150:
            c = b"<p>drip drip drip</p>\n"
            h.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
            h.wfile.flush()
            time.sleep(1)
        h.wfile.write(b"0\r\n\r\n")
    except OSError:
        pass
    h.close_connection = True


def _guarded(h):
    """A third-party image host: 403 without a Referer."""
    body, code = (PNG1, 200) if h.headers.get("Referer") else (b"no", 403)
    h.send_response(code)
    h.send_header("Content-Type", "image/png")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Connection", "close")
    h.end_headers()
    h.wfile.write(body)
    h.close_connection = True


class Servers:
    def __init__(self, file_target=None):
        self.file_target = file_target or _sample_file()
        self.private = serve({}, PRIVATE) if can_bind(PRIVATE) else None
        self.guarded = serve({}, PUBLIC)
        self.public = serve({}, PUBLIC)
        secret = self.private.url("/secret") if self.private else "http://localhost:1/secret"
        if self.private:
            self.private.routes.update({
                "/secret": html(200, page("Internal admin", "<article><h1>Internal</h1><p>INTERNAL-SECRET-MARKER "
                                          + EN + "</p></article>")),
                "/img/literal-probe.png": (200, {"Content-Type": "image/png"}, PNG1),
            })
        self.guarded.routes["/guarded.png"] = _guarded
        file_url = "file:///" + self.file_target.replace("\\", "/")
        seen = set()
        lock = threading.Lock()

        def flaky(h):                      # refuses the first request, then works
            with lock:
                first = "flaky" not in seen
                seen.add("flaky")
            if first:
                h.close_connection = True
                h.connection.close()
                return
            code, headers, body = html(200, page("Recovered", "<article><h1>Recovered</h1><p>RECOVERED-MARKER "
                                                 + EN + "</p></article>"))
            h.send_response(code)
            for k, v in headers.items():
                h.send_header(k, v)
            h.send_header("Content-Length", str(len(body)))
            h.end_headers()
            h.wfile.write(body)

        r = self.public.routes
        r.update({
            "/ok": html(200, page("Fine page", "<article><h1>Fine</h1><p>OK-MARKER " + EN + "</p></article>")),
            "/koi8-none": html(200, OLD_RU.encode("koi8-r"), "text/html"),
            "/cp1251-none": html(200, OLD_RU.encode("cp1251"), "text/html"),
            "/koi8-header": html(200, OLD_RU.encode("koi8-r"), "text/html; charset=koi8-r"),
            "/latin1-lie": html(200, page("Заголовок", "<article><h1>Старая страница</h1><p>" + RU + "</p></article>",
                                          "<meta charset='windows-1251'>").encode("cp1251"),
                                "text/html; charset=ISO-8859-1"),
            "/hash": html(200, HASH_LANDING),
            "/navdelay/800": html(200, nav_delay(800)),
            "/navdelay/3000": html(200, nav_delay(3000)),
            "/anubis": html(200, ANUBIS),
            "/xwrong": html(200, XWRONG),
            "/500": html(500, ERR500),
            "/503": html(503, MAINT503),
            "/503-empty": html(503, "", "text/plain"),
            "/truncated": lambda h: _promise_more(h),
            "/stall": lambda h: _promise_more(h, wait=90),
            "/trickle": _trickle,
            "/redir-file": redirect(file_url),
            "/redir-private": redirect(secret),
            "/r/abc123def456gh": redirect(secret),       # a public-looking slug the skill calls a token
            "/f/abc123def456gh": redirect(file_url),
            "/pub/plain": redirect(secret),
            "/pub/dnsname": redirect("http://localtest.me:%d/secret" % (self.private.port if self.private else 1)),
            "/imgpage": html(200, page("Pics", "<article><h1>Pics</h1><p>" + EN + "</p>"
                                       "<img src='%s'></article>" % (self.private.url("/img/literal-probe.png")
                                                                     if self.private else ""))),
            "/poster": (200, {"Content-Type": "image/png",
                              "Content-Disposition": 'attachment; filename="victim.txt"'}, PNG1),
            "/gallery": html(200, page("Gallery", "<article><h1>Gallery</h1><p>GALLERY-MARKER " + EN + "</p>" + "".join(
                '<img src="/img/%d.png" alt="picture number %d">' % (i, i) for i in range(300)) + "</article>")),
            "/refpage": html(200, page("Private doc", "<article><h1>Private</h1><p>" + EN + "</p>"
                                       "<img src='%s'></article>" % self.guarded.url("/guarded.png"))),
            "/flaky": flaky,
        })
        for i in range(300):
            r["/img/%d.png" % i] = (200, {"Content-Type": "image/png"}, PNG1 + str(i).encode())

    def stop(self):
        for s in (self.public, self.private, self.guarded):
            if s:
                s.close()


def _sample_file():
    """A local file the file:// redirects point at; its marker must never show up in an answer."""
    fd, path = tempfile.mkstemp(prefix="rp-local-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("LOCAL-FILE-MARKER this file is on the reader's own disk\n")
    return path


def start(file_target=None):
    return Servers(file_target)


if __name__ == "__main__":
    s = start(sys.argv[1] if len(sys.argv) > 1 else None)
    print("public  ", s.public.url("/"))
    print("private ", s.private.url("/") if s.private else "(127.0.0.2 is not available here)")
    print("guarded ", s.guarded.url("/"))
    print("file    ", s.file_target)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        s.stop()
