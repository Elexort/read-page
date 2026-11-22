"""Security (the browser's own checks are in browser_live.py; its proxy,
netguard, is checked here with a SOCKS5 client of our own). No network.

    python -X utf8 tests/security.py

127.0.0.1 is public in test mode (READ_PAGE_TEST_PUBLIC_HOST), 127.0.0.2 is the private target
nothing may reach from a public page, and a temporary file stands in for the reader's own disk.
A marker that shows up anywhere a run leaves text - the answer, content.md, page.md, raw files,
img/ - is a leak.
"""
import importlib.util
import json
import os
import socket
import stat
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import advsrv                                                # noqa: E402
from harness import PRIVATE, PUBLIC, SCRIPT, Checks, run_read   # noqa: E402

check = Checks()
SECRET, LOCAL = b"INTERNAL-SECRET-MARKER", b"LOCAL-FILE-MARKER"


def module():
    """A fresh in-process readpage with the test switch on."""
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    spec = importlib.util.spec_from_file_location("rp_sec_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def leaked(r, marker):
    """True when the marker is anywhere the run left text."""
    if marker in r.out:
        return True
    for root, _dirs, files in os.walk(r.dir):
        for name in files:
            try:
                with open(os.path.join(root, name), "rb") as fh:
                    if marker in fh.read():
                        return True
            except OSError:
                pass
    return False


s = advsrv.start()
file_url = "file:///" + s.file_target.replace("\\", "/")
if s.private:
    s.private.routes.update({
        "/to-file": advsrv.redirect(file_url),
        "/img-file": advsrv.html(200, advsrv.page("Intranet", "<article><h1>Intranet</h1><p>" + advsrv.EN
                                                  + "</p><img src='%s'></article>" % file_url)),
        "/wall": advsrv.html(403, advsrv.page("Attention Required!", "<h1>Attention Required!</h1>"
                                              "<p>Just a moment...</p>")),
        "/refpage": advsrv.html(200, advsrv.page("Intranet doc", "<article><h1>Intranet</h1><p>" + advsrv.EN
                                                 + "</p><img src='%s'></article>" % s.guarded.url("/guarded.png"))),
    })
s.public.routes.update({
    "/wall": advsrv.html(403, advsrv.page("Attention Required!", "<h1>Attention Required!</h1>"
                                          "<p>Just a moment...</p>")),
    "/docs/python3-tips-2024": advsrv.html(200, advsrv.page("Tips", "<article><h1>Python 3 tips</h1><p>"
                                                            + advsrv.EN + "</p></article>")),
    "/poster2": (200, {"Content-Type": "image/png",
                       "Content-Disposition": 'attachment; filename="manifest.json"'}, advsrv.PNG1),
})

try:
    # ------------------------------------------------ only http(s), on every hop and picture
    def reached_file(r):
        """The HTTP tier followed a redirect to the disk (a later browser page may hide the text)."""
        return ((r.manifest.get("url") or {}).get("final") or "").lower().startswith("file:")

    for path in ("/redir-file", "/f/abc123def456gh"):
        r = run_read(s.public.url(path))
        check("%s: the local file stays local" % path, not leaked(r, LOCAL) and not reached_file(r),
              "%s %s" % (r.manifest.get("status"), (r.manifest.get("signals") or {}).get("network", ""))[:70])
    if s.private:
        r = run_read(s.private.url("/to-file"))
        check("a private page redirecting to file:// is refused too",
              not leaked(r, LOCAL) and not reached_file(r), str(r.manifest.get("status")))
        r = run_read(s.private.url("/img-file"))
        check("<img src=file://> is never read, even on a private page", not leaked(r, LOCAL),
              "%d pictures" % len(r.manifest.get("images") or []))
        for path in ("/redir-private", "/r/abc123def456gh", "/pub/plain"):
            r = run_read(s.public.url(path))
            check("%s: a public page does not reach 127.0.0.2" % path, not leaked(r, SECRET),
                  str(r.manifest.get("status")))
        r = run_read(s.public.url("/imgpage"))
        check("a public page does not take a picture from 127.0.0.2",
              not any("literal-probe" in (e.get("file") or "") for e in r.manifest.get("images") or []),
              str([e.get("file") for e in r.manifest.get("images") or []])[:70])
        # every client decodes a host's percent-escapes: 127.0.0.%32 is 127.0.0.2 to curl and urllib
        s.public.routes.update({
            "/redir-escaped": advsrv.redirect("http://%%31%%32%%37.0.0.2:%d/secret" % s.private.port),
            "/img-escaped": advsrv.html(200, advsrv.page("Pics", "<article><h1>Pics</h1><p>" + advsrv.EN + "</p>"
                                                         "<img src='http://127.0.0.%%32:%d/img/literal-probe.png'>"
                                                         "</article>" % s.private.port)),
        })
        del s.private.log[:]
        r = run_read(s.public.url("/redir-escaped"))
        check("a redirect to 127.0.0.2 written with percent-escapes does not reach it",
              not leaked(r, SECRET) and not s.private.log, "%s; the private server saw %s" % (
                  r.manifest.get("status"), [e["path"] for e in s.private.log][:2]))
        r = run_read(s.public.url("/img-escaped"), "--download")
        check("... nor does a picture whose host is written so",
              not any("literal-probe" in e["path"] for e in s.private.log),
              str([e["path"] for e in s.private.log][:2]))
    else:
        check.skip("private target", "127.0.0.2 cannot be bound here")
    try:
        socket.getaddrinfo("localtest.me", 80)
        r = run_read(s.public.url("/pub/dnsname"))
        check("a name that resolves to loopback counts as private", not leaked(r, SECRET),
              str(r.manifest.get("status")))
    except OSError:
        check.skip("a name that resolves to loopback", "no DNS for localtest.me here")
    # a name Python's IDNA refuses (a right-to-left label ending in a digit), whose punycode - the name the request
    # goes to - resolves to loopback: the public server itself here, so what it is asked for is the evidence
    idn_host = "שלום1.localtest.me"

    def raw_redirect(location):
        def route(h):                              # http.server writes a header as Latin-1: the bytes by hand
            h.wfile.write(b"HTTP/1.1 302 Found\r\nLocation: " + location.encode("utf-8")
                          + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            h.close_connection = True
        return route

    try:
        socket.getaddrinfo("xn--1-9hcuf1d.localtest.me", 80)
        s.public.routes.update({
            "/redir-idn": raw_redirect("http://%s:%d/loopback-secret" % (idn_host, s.public.port)),
            "/img-idn": advsrv.html(200, advsrv.page("Pics", "<article><h1>Pics</h1><p>" + advsrv.EN + "</p>"
                                                     "<img src='http://%s:%d/loopback-only.png'></article>"
                                                     % (idn_host, s.public.port))),
            "/loopback-secret": advsrv.html(200, advsrv.page("Admin", "<article><h1>Admin</h1><p>"
                                                             "INTERNAL-SECRET-MARKER " + advsrv.EN + "</p></article>")),
            "/loopback-only.png": (200, {"Content-Type": "image/png"}, advsrv.PNG1),
        })
        del s.public.log[:]
        r = run_read(s.public.url("/redir-idn"))
        check("a redirect to a name outside ASCII whose punycode is loopback is refused",
              not leaked(r, SECRET) and not any(e["path"] == "/loopback-secret" for e in s.public.log),
              "%s %s" % (r.manifest.get("status"), str(r.manifest.get("error") or "")[:80]))
        r = run_read(s.public.url("/img-idn"), "--download")
        check("... and a picture there is not asked for",
              not any(e["path"] == "/loopback-only.png" for e in s.public.log),
              str([e["path"] for e in s.public.log][-3:]))
    except OSError:
        check.skip("a name outside ASCII that resolves to loopback", "no DNS for localtest.me here")

    mod = module()
    real = socket.getaddrinfo

    def fake(host, *a, **k):
        table = {"intranet.example": "10.1.2.3", "public.example": "93.184.216.34",
                 "fakeip.example": "198.18.0.7"}
        if host in table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], 80))]
        return real(host, *a, **k)

    socket.getaddrinfo = fake
    try:
        check("a name is private by the address it resolves to",
              bool(mod.host_is_private("http://intranet.example/a"))
              and not mod.host_is_private("http://public.example/a"), "")
        check("a fake-IP proxy's 198.18.x.x answer does not make every site internal",
              not mod.host_is_private("http://fakeip.example/a"), "")
    finally:
        socket.getaddrinfo = real
    forms = {
        "http://[::1]:8080/": True, "http://[fd00::1]/": True, "http://[fe80::1]/": True,
        "http://[::ffff:127.0.0.1]/": True, "http://2130706433/": True, "http://0x7f000001/": True,
        "http://0177.0.0.1/": True, "http://100.64.0.1/": True, "http://localhost:1/": True,
        "http://localhost./": True, "http://metadata.google.internal/": True, "http://169.254.169.254/x": True,
        "http://%s:8080/" % PRIVATE: True, "http://%s:8080/" % PUBLIC: False,
        "https://example.com/reset/abc123def456ghi789/session": False,     # the path does not decide
    }
    wrong = [u for u, want in forms.items() if bool(mod.host_is_private(u)) != want]
    check("host_is_private decides by the host only (15 forms)", not wrong, ", ".join(wrong[:3]))

    # ------------------------------------------------ the host checked is the host asked for
    # Every client decodes a host's percent-escapes (curl, libcurl and urllib alike) and sends a
    # name outside ASCII as its punycode: the rule looks at that very name, and refuses a host that
    # has none. Python's own lookup (IDNA 2003) refuses a right-to-left label that ends in a digit,
    # which the request - like a browser - sends as xn--1-9hcuf1d.
    import intl                                              # noqa: E402
    idn = "http://שלום1.inside.example:8080/secret"
    asked = urllib.parse.urlsplit(intl.iri_to_uri(idn)).hostname or ""

    def fake_idn(host, *a, **k):
        name = host.decode("ascii", "replace") if isinstance(host, bytes) else str(host)
        if name.lower().rstrip(".") == asked:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 80))]
        return real(host, *a, **k)

    socket.getaddrinfo = fake_idn
    try:
        mod = module()
        check("a name outside ASCII is checked as the punycode the request sends (%s)" % asked,
              asked.startswith("xn--") and bool(mod.host_is_private(idn)), repr(mod.host_is_private(idn)))
        check("... so a public page's redirect or picture does not reach it",
              bool(mod.hop_refused("http://%s/" % PUBLIC, idn)), "")
    finally:
        socket.getaddrinfo = real
    escaped = ["http://%31%32%37.0.0.2:8080/", "http://127.0.0.2%2e:8080/", "http://%6c%6fcalhost:8080/",
               "http://169.254.169.%32%35%34/latest/meta-data/"]
    let_through = [u for u in escaped if not mod.host_is_private(u)]
    check("a host written with percent-escapes is the host they decode to (4 forms)", not let_through,
          ", ".join(let_through[:2]))
    check("... and the request goes to that same host",
          intl.iri_to_uri("http://%31%32%37.0.0.2:8080/a%20b") == "http://127.0.0.2:8080/a%20b",
          intl.iri_to_uri("http://%31%32%37.0.0.2:8080/a%20b"))
    check("a host that has no ASCII form (escapes that are not UTF-8) is refused, never let through",
          bool(mod.hop_refused("http://%s/" % PUBLIC, "http://%ff%fe.example/x")), "")

    # ------------------------------------------------ a secret keeps a URL from readers only
    secrets = [
        "https://docsify.js.org/?token=test123#/quickstart", "https://app.example.com/reset/Zx8Kq2LmP9vT4nB7wY1cR6dF3hJ5sA0e",
        "https://example.com/share/b3f1c9d2e7a44f6c8e0a1d2c3b4f5e6a",
        "https://hooks.slack.com/" + "services/" + "T" + "0" * 8 + "/B" + "0" * 8 + "/" + "X" * 24,    # built here: no secret-shaped literal in the source
        "https://example.com/a?api_key=abc", "https://example.com/a?access_token=abc", "https://example.com/a?sig=abc&exp=1",
        "https://user:pw@example.com/", "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcdE/edit",
        "https://s3.amazonaws.com/b/k?X-Amz-Signature=abc&X-Amz-Credential=x",
        "https://discord.com/api/" + "webhooks/" + "123456789" + "012345678" + "/" + "AbCdEfGhIjKlMnOpQrStUvWxYz" + "0123456789_abcdefghijkl",
    ]
    public = [
        "https://en.wikipedia.org/wiki/Windows_11_version_history", "https://medium.com/@user/how-i-built-this-in-2024-1a2b3c4d5e6f",
        "https://www.bbc.com/news/world-us-canada-12345678", "https://dev.to/user/post-title-3k2j",
        "https://blog.example.com/python3-tips", "https://example.com/gpt4-technical-report",
        "https://www.reddit.com/r/Python/comments/abc123/python_312_released/", "https://www.npmjs.com/package/oauth2-server",
        "https://cdn.example.com/assets/app.3f2a9c1b4d5e6f7a.js", "https://stackoverflow.com/questions/2018026/urllib2-vs-requests",
    ]
    missed = [u for u in secrets if not mod.url_has_secret(u)]
    check("the 11 known secret shapes are caught", not missed, ", ".join(m[:50] for m in missed[:2]))
    flagged = [u for u in public if mod.url_has_secret(u)]
    check("ordinary slugs with digits are not secrets", not flagged, ", ".join(f[:50] for f in flagged[:2]))
    r = run_read(s.public.url("/docs/python3-tips-2024"), "--allow-external", "--json")
    pv = r.manifest.get("privacy") or {}
    check("--allow-external on a slug with digits allows readers", pv.get("mode") == "public"
          and "external" not in (pv.get("refused") or []), json.dumps(pv)[:90])

    # ------------------------------------------------ --force-external and an internal host
    def reads(mod, argv):
        sent = []
        mod.external_read = lambda url, c, refresh=False: (sent.append(url), ("", "rec", None, ""))[1]
        out = tempfile.mkdtemp(prefix="rp-sec-")
        old = sys.stdout
        try:
            import io
            sys.stdout = io.StringIO()
            mod.main(argv + ["--dir", out, "--json"])
            printed = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        try:
            return sent, json.loads(printed)
        except ValueError:
            return sent, {}

    if s.private:
        os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-sec-cache-")
        sent, m = reads(module(), [s.private.url("/wall"), "--force-external"])
        pv = m.get("privacy") or {}
        check("--force-external never sends an internal host out", not sent, "sent=%r" % sent)
        check("the refusal and its reason are in the manifest", "external" in (pv.get("refused") or [])
              and "internal" in (pv.get("why") or ""), json.dumps(pv)[:100])
        check("the local result stays", m.get("status") in ("blocked", "ok", "empty"), str(m.get("status")))
    sent, m = reads(module(), [s.public.url("/wall") + "?token=abc123", "--allow-external"])
    check("--allow-external keeps a URL with a secret local", not sent, "sent=%r" % sent)
    sent, m = reads(module(), [s.public.url("/wall") + "?token=abc123", "--force-external"])
    check("--force-external sends a public URL with a secret", bool(sent), "sent=%r" % sent)

    # ------------------------------------------------ Referer is the origin, never the page
    s.guarded.log.clear()
    r = run_read(s.public.url("/refpage") + "?token=SECRETTOKEN")
    refs = [e["referer"] for e in s.guarded.log if e["path"].startswith("/guarded.png") and e["referer"]]
    check("a picture gets only the page's origin as Referer",
          refs and all(x == "http://%s:%d/" % (PUBLIC, s.public.port) for x in refs), str(refs)[:90])
    check("the page's query never leaves with a picture request",
          not any("SECRETTOKEN" in x for x in refs), "")
    if s.private:
        s.guarded.log.clear()
        run_read(s.private.url("/refpage"))
        refs = [e["referer"] for e in s.guarded.log if e["path"].startswith("/guarded.png")]
        check("an internal page sends no Referer to an outside host", refs and not any(refs), str(refs)[:90])

    # ------------------------------------------------ a direct Chrome run gets its own profile
    mod = module()
    seen = {}

    def fake_run(argv, timeout=None, cwd=None, **kw):
        seen["argv"] = list(argv)
        for a in argv:
            if str(a).startswith("--user-data-dir="):
                seen["dir"] = str(a).split("=", 1)[1]
                seen["existed"] = os.path.isdir(seen["dir"])
        return 0, b"<html><body>" + b"x" * 400 + b"</body></html>", b""

    mod.run = fake_run
    fake_caps = {"libs": {}, "browsers": [{"name": "chrome", "path": "C:/fake/chrome.exe", "kind": "path"}]}
    mod.render("https://example.com/a", fake_caps)
    check("a direct Chrome run gets a temporary --user-data-dir", seen.get("existed") is True,
          " ".join(str(a) for a in (seen.get("argv") or [])[1:4]))
    check("the temporary profile is removed afterwards", seen.get("dir") and not os.path.exists(seen["dir"]),
          str(seen.get("dir"))[:70])

    # ------------------------------------------------ a server's file name replaces nothing
    d = tempfile.mkdtemp(prefix="rp-sec-dir-")
    with open(os.path.join(d, "victim.txt"), "w", encoding="utf-8") as fh:
        fh.write("USER-FILE")
    run_read(s.public.url("/poster"), env={}, own_dir=True)                     # warm the harness
    import subprocess
    env = dict(os.environ, READ_PAGE_TEST_PUBLIC_HOST=PUBLIC, READ_PAGE_CACHE=tempfile.mkdtemp(prefix="rp-sec-c-"))
    subprocess.run([sys.executable, "-X", "utf8", SCRIPT, s.public.url("/poster"), "--dir", d, "--json"],
                   capture_output=True, env=env, timeout=120)
    with open(os.path.join(d, "victim.txt"), encoding="utf-8", errors="replace") as fh:
        kept = fh.read()
    check("Content-Disposition does not replace a file already in --dir", kept == "USER-FILE",
          repr(kept[:30]))
    check("the download is kept under another name",
          any(n.startswith("victim-") for n in os.listdir(d)), str(sorted(os.listdir(d)))[:80])
    d2 = tempfile.mkdtemp(prefix="rp-sec-dir-")
    subprocess.run([sys.executable, "-X", "utf8", SCRIPT, s.public.url("/poster2"), "--dir", d2, "--json"],
                   capture_output=True, env=env, timeout=120)
    try:
        with open(os.path.join(d2, "manifest.json"), encoding="utf-8") as fh:
            ours = json.load(fh).get("generator") == "read-page"
    except ValueError:
        ours = False
    check("a server cannot name its file manifest.json", ours, str(sorted(os.listdir(d2)))[:80])
    # Windows' device names (a file named so is the device on Windows 10 and Server: the download lost)
    devices = {x: intl.file_stem(x) for x in ("CON", "nul", "COM1", "LPT²", "AUX.tar", "con ", "console", "COM10")}
    check("a server's name that is a Windows device's (CON, NUL, COM1, LPT², AUX.tar) is not used as it is",
          [devices[x] for x in ("CON", "nul", "COM1", "LPT²", "AUX.tar", "con ")]
          == ["file-CON", "file-nul", "file-COM1", "file-LPT²", "file-AUX.tar", "file-con"]
          and devices["console"] == "console" and devices["COM10"] == "COM10", str(devices))
    s.public.routes["/con"] = (200, {"Content-Type": "image/png", "Content-Disposition": 'attachment; filename="CON.png"'},
                               advsrv.PNG1)
    d3 = tempfile.mkdtemp(prefix="rp-sec-dir-")
    subprocess.run([sys.executable, "-X", "utf8", SCRIPT, s.public.url("/con"), "--dir", d3, "--json"],
                   capture_output=True, env=env, timeout=120)
    check("... and the download is kept under another name", "file-CON.png" in os.listdir(d3),
          str(sorted(os.listdir(d3)))[:80])

    # ------------------------------------------------ the cache belongs to this user only
    if os.name == "posix":
        tmp = tempfile.mkdtemp(prefix="rp-sec-tmp-")
        env = dict(os.environ, TMPDIR=tmp, READ_PAGE_TEST_PUBLIC_HOST=PUBLIC)
        env.pop("READ_PAGE_CACHE", None)
        subprocess.run([sys.executable, "-X", "utf8", SCRIPT, s.public.url("/ok"), "--json"],
                       capture_output=True, env=env, timeout=120)
        root = os.path.join(tmp, "read-page-%d" % os.getuid())
        mode = stat.S_IMODE(os.stat(root).st_mode) if os.path.isdir(root) else None
        check("the cache folder is per user and 0700", mode == 0o700, oct(mode) if mode else "missing")
        loose = [os.path.join(a, n) for a, _, ns in os.walk(root) for n in ns
                 if stat.S_IMODE(os.stat(os.path.join(a, n)).st_mode) & 0o077]
        check("no file in it is readable by others", not loose, str(loose[:2]))
        os.chmod(root, 0o755)
        subprocess.run([sys.executable, "-X", "utf8", SCRIPT, s.public.url("/ok"), "--json", "--refresh"],
                       capture_output=True, env=env, timeout=120)
        check("a loosened cache folder is closed again", stat.S_IMODE(os.stat(root).st_mode) == 0o700,
              oct(stat.S_IMODE(os.stat(root).st_mode)))
        mod = module()
        os.environ.pop("READ_PAGE_CACHE", None)
        os.environ["TMPDIR"] = tmp
        tempfile.tempdir = None
        real_uid = os.getuid
        os.getuid = lambda: real_uid() + 1           # a folder of that name exists and is not ours
        try:
            os.makedirs(os.path.join(tmp, "read-page-%d" % (real_uid() + 1)), exist_ok=True)
            other = mod.cache_root()
        finally:
            os.getuid = real_uid
        check("a cache folder owned by someone else is not used",
              os.path.basename(other) != "read-page-%d" % (real_uid() + 1), other)
    else:
        check.skip("cache permissions", "POSIX only; Windows keeps the cache in the user's own temp")
finally:
    s.stop()

# ------------------------------------------------ netguard, the browser's way out
# A SOCKS5 client of our own stands in for Chrome: what may pass, what may not, what reaches the
# private service at all. The browser side is in browser_live.py.
import ipaddress                                             # noqa: E402
import threading                                             # noqa: E402

from harness import can_bind, serve                          # noqa: E402

mod = module()
os.environ["READ_PAGE_TEST_HOSTS"] = "inside.test=%s,outside.test=%s" % (PRIVATE, PUBLIC)
BIG = b"N" * (1024 * 1024)
pub = serve({"/big": (200, {"Content-Type": "application/octet-stream"}, BIG),
             "/page": (200, {"Content-Type": "text/plain"}, b"PUBLIC-PAGE")}, PUBLIC)
priv = serve({"/secret": (200, {"Content-Type": "text/plain"}, SECRET)}, PRIVATE) if can_bind(PRIVATE) else None
pub_port = int(pub.url("/").rsplit(":", 1)[1].split("/")[0])
priv_port = int(priv.url("/").rsplit(":", 1)[1].split("/")[0]) if priv else 9


def socks(gport, host, dport, path=""):
    """One SOCKS5 CONNECT through the guard: (reply code, what an HTTP GET of `path` brought)."""
    c = socket.create_connection(("127.0.0.1", gport), timeout=10)
    try:
        c.sendall(b"\x05\x01\x00")
        c.recv(2)
        try:
            ip = ipaddress.ip_address(host)
            target = (b"\x01" if ip.version == 4 else b"\x04") + ip.packed
        except ValueError:
            target = b"\x03" + bytes([len(host)]) + host.encode("ascii")
        c.sendall(b"\x05\x01\x00" + target + dport.to_bytes(2, "big"))
        rep = b""
        while len(rep) < 10:
            part = c.recv(10 - len(rep))
            if not part:
                break
            rep += part
        code = rep[1] if len(rep) > 1 else -1
        body = b""
        if code == 0 and path:
            c.sendall(("GET %s HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n" % path).encode())
            while True:
                part = c.recv(65536)
                if not part:
                    break
                body += part
        return code, body
    finally:
        c.close()


# a measurement switch (READ_PAGE_TEST_BLOCKLIST): a listed name and its subdomains are refused
# before any lookup, an @@ exception passes; an ad-block DNS filter's syntax and a hosts file's
lst = os.path.join(tempfile.mkdtemp(prefix="rp-list-"), "list.txt")
with open(lst, "w", encoding="utf-8") as fh:
    fh.write("! a comment\n||ads.example^\n@@||ok.ads.example^\n0.0.0.0 tracker.example\n||x.example/path^\n")
saved_hosts = os.environ["READ_PAGE_TEST_HOSTS"]
os.environ["READ_PAGE_TEST_HOSTS"] = saved_hosts + ",ok.ads.example=%s" % PUBLIC
os.environ["READ_PAGE_TEST_BLOCKLIST"] = lst
listed = {h: mod.browser_policy(h, 443)[0] for h in ("pixel.ads.example", "ads.example", "tracker.example",
                                                      "ok.ads.example")}
del os.environ["READ_PAGE_TEST_BLOCKLIST"]
os.environ["READ_PAGE_TEST_HOSTS"] = saved_hosts
check("a test block list: listed names and their subdomains refused before a lookup, an exception passes",
      all(listed[h] == "on the test block list" for h in ("pixel.ads.example", "ads.example", "tracker.example"))
      and listed["ok.ads.example"] == "", str(listed))

g = mod.netguard.Guard(mod.browser_policy).start()
code, body = socks(g.port, PUBLIC, pub_port, "/big")
check("netguard: a public address goes through, a megabyte whole", code == 0 and body.endswith(BIG),
      "reply %s, %d bytes" % (code, len(body)))
code, body = socks(g.port, "outside.test", pub_port, "/page")
check("netguard: a name goes to the very address it was checked on", code == 0 and b"PUBLIC-PAGE" in body,
      "reply %s" % code)
hits = len(priv.log) if priv else 0
inside = [(PRIVATE, priv_port), ("2130706434", priv_port), ("localhost", priv_port), ("169.254.169.254", 80),
          ("::1", priv_port), ("inside.test", priv_port), ("metadata.google.internal", 80), ("db.internal", 80)]
codes = {h: socks(g.port, h, port)[0] for h, port in inside}
check("netguard: 127.0.0.2, its integer form, localhost, cloud metadata, ::1, a name that resolves inside "
      "and internal names are refused before any connection",
      all(v == 2 for v in codes.values()) and (len(priv.log) if priv else 0) == hits,
      "%s; private server hits +%d" % (codes, (len(priv.log) if priv else 0) - hits))
check("netguard: what it refused is listed, with the reason",
      len(g.refused) == len(inside) and all(r.get("why") for r in g.refused), str(g.refused[:2]))
code, _ = socks(g.port, "no-such-host.invalid", 80)
check("netguard: a name that does not resolve is 'host unreachable', not a hang", code == 4, "reply %s" % code)
got = []


def one():
    got.append(socks(g.port, PUBLIC, pub_port, "/page"))


ts = [threading.Thread(target=one) for _ in range(40)]
for t in ts:
    t.start()
for t in ts:
    t.join(30)
check("netguard: forty connections at once", len(got) == 40 and all(c == 0 and b"PUBLIC-PAGE" in b for c, b in got),
      "%d answered" % len(got))
g.close()
g.thread.join(5)
check("netguard: close() ends the thread that took connections (on Linux it waited for the process "
      "to end)", not g.thread.is_alive(), "still waiting in accept()" if g.thread.is_alive() else "")
try:
    socks(g.port, PUBLIC, pub_port)
    after = "still open"
except OSError:
    after = "closed"
check("netguard: after close() nothing new gets in (Linux let them in: close() alone does not wake "
      "accept())", after == "closed", after)
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
check("netguard: a proxy in the environment makes it step aside for the request rule",
      bool(mod.system_proxy()), mod.system_proxy())
del os.environ["HTTPS_PROXY"]
pub.close()
if priv:
    priv.close()

sys.exit(check.done())
