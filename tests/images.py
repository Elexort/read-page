"""Pictures and their storage.
No network.

    python -X utf8 tests/images.py

Every picture the text shows is a numbered marker in its place - `[img #3 · 100x100 3K · alt]
img/03-alt.png`, the number is the file's - whatever produced the text: an extractor, a block
the block rule put back, a reader, a site's API. page.md keeps its pictures. What is downloaded
follows the printed view (the printed window): every picture of content.md and page.md is
numbered from the first call, and a call downloads those of the lines it prints that have no file
yet - a continuation's, page.md's when page.md is printed, one the 6 s phase cut; everything with
--download. A page folder starts with its host, and a picture another page of the same host
already has is taken by a hard link from that page's folder, not from the network.
"""
import importlib.util
import io
import json
import os
import re
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import answer                                                # noqa: E402
import blockrule                                             # noqa: E402
from harness import PUBLIC, Checks, run_read, serve          # noqa: E402

check = Checks()
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ")
MARK = re.compile(r"\[img #(\d+)(?: · [^\]\n]*)?\](?: (\S+))?")


def png(w, h, rgb=(200, 30, 30)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


GIF1 = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
        b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
PNG_H = {"Content-Type": "image/png"}
HTML_H = {"Content-Type": "text/html; charset=utf-8"}
LAZY = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
ARTICLE = (
    "<!doctype html><html><head><meta charset='utf-8'><title>Flows</title></head><body>"
    "<nav><a href='/'><img src='/img/logo.png' alt='Site logo'></a><ul>"
    + "".join("<li><a href='/s/%d'>Section %d of the site</a></li>" % (i, i) for i in range(30)) +
    "</ul></nav><main><article><h1>Flows</h1>"
    "<p>INTRO-PARA " + EN * 3 + " <img src='/img/icon.png' alt='ok' width='16' height='16'> done.</p>"
    "<p><img src='/img/diagram.png' alt='Diagram of the flow'></p>"
    "<p>MIDDLE-PARA " + EN * 3 + " <img src='/img/icon.png' alt='ok' width='16' height='16'> again.</p>"
    "<figure><img src='/img/photo.png' alt='Photo of the rack'><figcaption>The rack after the move"
    "</figcaption></figure>"
    "<p>LAZY-PARA " + EN * 2 + "</p><p><img src='" + LAZY + "' data-src='/img/lazy-real.png' alt='Lazy chart'></p>"
    "<p>GONE-PARA " + EN * 2 + "</p><p><img src='/img/missing.png' alt='A missing chart'></p>"
    "<p>END-PARA " + EN * 3 + "<img src='/img/pixel.gif' width='1' height='1' alt=''></p>"
    "</article><aside class='sidebar'><p>ASIDE-PARA The sidebar holds a whole paragraph of real advice that "
    "a main-content extractor throws away, although the reader of this guide needs it.</p>"
    "<p><img src='/img/aside.png' alt='Aside sketch'></p></aside></main>"
    "<footer><img src='/img/social.png' alt='Follow us'><p>&copy; 2026 Example Inc.</p></footer></body></html>")
SECOND = (
    "<!doctype html><html><head><meta charset='utf-8'><title>Second</title></head><body><article><h1>Second"
    "</h1><p>SECOND-PARA " + EN * 4 + "</p><p><img src='/img/diagram.png' alt='Diagram of the flow'></p>"
    "<p>SECOND-END " + EN * 3 + "</p></article></body></html>")
s = serve({
    "/article": (200, HTML_H, ARTICLE.encode("utf-8")),
    "/second": (200, HTML_H, SECOND.encode("utf-8")),
    "/img/logo.png": (200, PNG_H, png(120, 40)),
    "/img/icon.png": (200, PNG_H, png(16, 16, (0, 160, 0))),
    "/img/diagram.png": (200, PNG_H, png(100, 80, (0, 0, 200))),
    "/img/photo.png": (200, PNG_H, png(64, 48, (90, 90, 90))),
    "/img/lazy-real.png": (200, PNG_H, png(50, 30, (10, 200, 200))),
    "/img/aside.png": (200, PNG_H, png(40, 40, (200, 200, 0))),
    "/img/social.png": (200, PNG_H, png(24, 24)),
    "/img/pixel.gif": (200, {"Content-Type": "image/gif"}, GIF1),
})


def markers(text):
    return [(int(m.group(1)), m.group(2) or "", m.group(0)) for m in MARK.finditer(text or "")]


def gets(path):
    return sum(1 for e in s.log if e["path"].split("?")[0] == path)


try:
    # ------------------------------------------------ the marker: numbered, in place, the number is the file's
    s.log.clear()
    r = run_read(s.url("/article"), env={"READ_PAGE_SKIP": "browser"})
    body, page, man = r.file("content.md"), r.file("page.md"), r.manifest
    eng = str((man.get("content") or {}).get("engine") or "")
    ms = markers(body)
    check("every picture of the text is a marker `[img #N · ...] img/NN-...`",
          ms and all(rel.startswith("img/%02d-" % n) for n, rel, _ in ms if rel.startswith("img/")),
          "%s: %s" % (eng, [m[2][:60] for m in ms[:3]]))
    first = {}
    for n, rel, _ in ms:
        first.setdefault(n, rel)
    check("numbers follow the first appearance, a repeat keeps its number",
          sorted(first) == list(range(1, len(first) + 1)) and len([n for n, _, _ in ms if n == ms[0][0]]) >= 1,
          str([n for n, _, _ in ms]))
    diag = [m for m in ms if "Diagram of the flow" in m[2]]
    check("the alt is inside the marker, the file name is the number and its words",
          diag and diag[0][1].startswith("img/") and re.match(r"img/\d\d-diagram-of-the-flow\.png$", diag[0][1]),
          diag[0][2] if diag else "no diagram marker")
    check("the marker carries size and dimensions", diag and re.search(r"· 100x80 \d+(B|K) ·", diag[0][2]),
          diag[0][2] if diag else "")
    files = sorted(os.listdir(os.path.join(r.dir, "img"))) if os.path.isdir(os.path.join(r.dir, "img")) else []
    absent = [rel for _, rel, _ in ms if rel.startswith("img/") and not os.path.isfile(os.path.join(r.dir, rel))]
    check("each marked file is on disk", not absent, "missing %s of %s" % (absent, files))
    pos = [body.find(x) for x in ("INTRO-PARA", "Diagram of the flow", "MIDDLE-PARA")]
    check("a picture stands where the page has it", all(p >= 0 for p in pos) and pos == sorted(pos), str(pos))
    icon = [m for m in ms if "icon" in m[1] or "· ok" in m[2]]
    check("one picture used twice is one number and one file",
          len({n for n, _, _ in icon}) == 1 and len([f for f in files if "ok" in f or "icon" in f]) == 1,
          "%s %s" % ([m[2][:40] for m in icon], files))
    check("a tracking pixel is in neither the text nor img/", "pixel" not in body and not any(
          "pixel" in f for f in files), str(files))
    check("a lazy picture is the real one (data-src), not its placeholder",
          any("lazy-chart" in rel for _, rel, _ in ms) and gets("/img/lazy-real.png") == 1, str(files))
    gone = [m for m in ms if "A missing chart" in m[2]]
    check("a picture that failed says so in its marker, with its address",
          gone and "not downloaded" in gone[0][2] and "404" in gone[0][2] and gone[0][1].endswith("/img/missing.png"),
          gone[0][2] if gone else "no marker")
    check("the nav logo and the footer icon are not downloaded for the text",
          gets("/img/logo.png") == 0 and gets("/img/social.png") == 0,
          "logo %d, social %d" % (gets("/img/logo.png"), gets("/img/social.png")))
    check("pictures outside the text are counted", ((man.get("signals") or {}).get("images_outside") or 0) >= 2,
          str((man.get("signals") or {}).get("images_outside")))
    imgs = man.get("images") or []
    check("the manifest lists the text's pictures in order",
          [e.get("n") for e in imgs][:len(first)] == sorted(first) and all(e.get("url") for e in imgs),
          str([(e.get("n"), e.get("file")) for e in imgs][:6]))
    check("page.md keeps its pictures", "logo" in page.lower() and ("Diagram of the flow" in page),
          page[:0])
    if eng.split(":")[0] in ("full", "crude"):
        check.skip("the sidebar's picture comes back with its paragraph", "no extractor here (%s)" % eng)
    else:
        a, b = body.find("ASIDE-PARA"), body.find("Aside sketch")
        check("the sidebar's picture comes back with its paragraph", 0 <= a < b, "%s %s" % (eng, (a, b)))

    # ------------------------------------------------ what is downloaded follows the printed view
    s.log.clear()
    rp = run_read(s.url("/article"), "--file", "page.md", env={"READ_PAGE_SKIP": "browser"})
    pmd = rp.file("page.md")
    check("--file page.md downloads page.md's pictures, the logo too",
          gets("/img/logo.png") == 1 and any("site-logo" in rel for _, rel, _ in markers(pmd)),
          str([m[2][:50] for m in markers(pmd)][:4]))
    s.log.clear()
    rd = run_read(s.url("/article"), "--download", env={"READ_PAGE_SKIP": "browser"})
    dfiles = os.listdir(os.path.join(rd.dir, "img")) if os.path.isdir(os.path.join(rd.dir, "img")) else []
    check("--download takes every picture of the page, the text stays the same",
          gets("/img/logo.png") == 1 and gets("/img/social.png") == 1 and any("follow-us" in f for f in dfiles)
          and "site-logo" not in rd.file("content.md"), str(dfiles))

    # ------------------------------------------------ --deny-images, then a read with pictures
    s.log.clear()
    rn = run_read(s.url("/article"), "--deny-images", env={"READ_PAGE_SKIP": "browser"}, own_dir=False)
    nbody = rn.file("content.md")
    check("--deny-images: markers say not downloaded, nothing is fetched",
          "not downloaded" in nbody and not any(e["path"].startswith("/img/") for e in s.log)
          and not os.path.isdir(os.path.join(rn.dir, "img")), str(markers(nbody)[:1]))
    s.log.clear()
    ra = run_read(s.url("/article"), env={"READ_PAGE_SKIP": "browser"}, own_dir=False, reuse=rn)
    abody = ra.file("content.md")
    check("deny, then allow: the cached text gets its pictures, without reading the page again",
          ra.manifest.get("cache") == "hit" and gets("/article") == 0 and "img/" in abody
          and len(markers(abody)) == len(markers(nbody)), "%s, page GETs %d" % (ra.manifest.get("cache"), gets("/article")))

    # ------------------------------------------------ storage: the host in the folder, hard links between pages
    s.log.clear()
    r1 = run_read(s.url("/article"), env={"READ_PAGE_SKIP": "browser"}, own_dir=False)
    r2 = run_read(s.url("/second"), env={"READ_PAGE_SKIP": "browser"}, own_dir=False, reuse=r1)
    pages_root = os.path.join(r1.root, "cache", "pages")
    names = sorted(n for n in os.listdir(pages_root) if os.path.isfile(os.path.join(pages_root, n, "manifest.json"))) \
        if os.path.isdir(pages_root) else []
    check("a page folder starts with its host", names and all(n.startswith(PUBLIC + "-") for n in names),
          str(names))
    d1 = [os.path.join(pages_root, n) for n in names if "article" in json.dumps(json.load(open(os.path.join(
        pages_root, n, "manifest.json"), encoding="utf-8")).get("url"))]
    d2 = [os.path.join(pages_root, n) for n in names if "second" in json.dumps(json.load(open(os.path.join(
        pages_root, n, "manifest.json"), encoding="utf-8")).get("url"))]
    f1 = [e["file"] for e in (r1.manifest.get("images") or []) if "diagram" in (e.get("file") or "")]
    f2 = [e["file"] for e in (r2.manifest.get("images") or []) if "diagram" in (e.get("file") or "")]
    same = False
    if d1 and d2 and f1 and f2:
        a, b = os.stat(os.path.join(d1[0], f1[0])), os.stat(os.path.join(d2[0], f2[0]))
        same = (a.st_ino, a.st_dev) == (b.st_ino, b.st_dev) and a.st_ino != 0
    check("the second page takes the picture by a hard link, no second request",
          same and gets("/img/diagram.png") == 1, "same inode %s, GETs %d" % (same, gets("/img/diagram.png")))
    check("the second page counts it as reused",
          ((r2.manifest.get("signals") or {}).get("images_reused") or 0) >= 1,
          str((r2.manifest.get("signals") or {}).get("images_reused")))
    if d1 and d2 and f2:
        shutil.rmtree(d1[0], ignore_errors=True)
        check("deleting the first folder leaves the second one's picture",
              os.path.isfile(os.path.join(d2[0], f2[0])) and os.path.getsize(os.path.join(d2[0], f2[0])) > 0, f2[0])
    hosts = os.path.join(r1.root, "cache", "hosts")
    stores = [p for p, _, fs in os.walk(hosts) if os.path.basename(p) == "assets" or "assets.json" in fs]
    check("there is no separate picture store", not stores, str(stores))

    # ------------------------------------------------ a reader's text gets its pictures too
    s.routes["/walled"] = (403, HTML_H, b"<html><head><title>Just a moment...</title></head><body>"
                                        b"<h1>Just a moment...</h1><p>Checking your browser.</p></body></html>")
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = os.path.join(r1.root, "cache-reader")
    os.environ["READ_PAGE_SKIP"] = "browser"
    spec = importlib.util.spec_from_file_location("rp_img_reader", os.path.join(os.path.dirname(HERE), "scripts",
                                                                                "readpage.py"))
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    reader_md = "# Walled\n\nREADER-PARA " + EN * 3 + "\n\n![Reader chart](%s)\n\n" % s.url("/img/photo.png") + EN
    rp.external_read = lambda url, c, refresh=False: (reader_md, "reader:jina", 200, "")
    out_dir = os.path.join(r1.root, "reader-out")
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        rp.main([s.url("/walled"), "--allow-external", "--json", "--dir", out_dir])
    finally:
        sys.stdout = old
    rm = json.loads(buf.getvalue() or "{}")
    rbody = open(os.path.join(out_dir, "content.md"), encoding="utf-8").read() if os.path.isfile(
        os.path.join(out_dir, "content.md")) else ""
    check("a reader's pictures are downloaded and marked like any other",
          (rm.get("content") or {}).get("engine") == "reader:jina" and "img/01-reader-chart.png" in rbody
          and os.path.isfile(os.path.join(out_dir, "img", "01-reader-chart.png")),
          "%s %s" % ((rm.get("content") or {}).get("engine"), [m[2][:50] for m in markers(rbody)]))
    os.environ.pop("READ_PAGE_SKIP", None)

    # ------------------------------------------------ an alt with escaped brackets (trafilatura's)
    esc = r"Text before. ![A rack \[File: AP\]](/img/rack.jpg?w=770&q=80) and [![Linked \[x\]](/img/c.png)](/page)"
    found = __import__("pictures").refs(esc, "https://example.com/")
    marked = __import__("pictures").mark(esc, "https://example.com/", {
        u: {"n": i + 1, "url": u, "alt": a, "why": "not printed yet"} for i, (u, a) in enumerate(found)})
    check("a picture whose alt has escaped brackets is still a picture, its alt clean",
          len(found) == 2 and "[img #1 · A rack (File: AP)" in marked and "![" not in marked, marked[:120])

    # ------------------------------------------------ the printed window's pictures
    import time as _time
    slow_hits = []

    def slow_png(h):
        """The first time a byte a second for 8 s - still arriving, so not stuck, and past the 6 s
        phase - then at once."""
        slow_hits.append(1)
        body = png(60, 40, (20, 20, 160))
        try:
            h.send_response(200)
            h.send_header("Content-Type", "image/png")
            h.send_header("Content-Length", str(len(body)))
            h.end_headers()
            if len(slow_hits) == 1:
                for i in range(8):
                    h.wfile.write(body[i:i + 1])
                    h.wfile.flush()
                    _time.sleep(1)
                h.wfile.write(body[8:])
            else:
                h.wfile.write(body)
        except OSError:
            pass
    long_page = ("<!doctype html><html><head><title>Long</title></head><body><article><h1>Long</h1>"
                 "<p>TOP-PARA " + EN + "</p><p><img src='/w/top.png' alt='Top chart'></p>"
                 "<p><img src='/w/slow.png' alt='Slow chart'></p>"
                 + "".join("<h2>Part %d</h2><p>BODY-%d %s</p>" % (i, i, EN * 3) for i in range(80))
                 + "<p><img src='/w/bottom.png' alt='Bottom chart'></p><p>END-PARA " + EN + "</p>"
                 "</article></body></html>")
    s.routes.update({"/long": (200, HTML_H, long_page.encode("utf-8")),
                     "/w/top.png": (200, PNG_H, png(60, 40)), "/w/bottom.png": (200, PNG_H, png(60, 40, (0, 120, 0))),
                     "/w/slow.png": slow_png})
    s.log.clear()
    rl = run_read(s.url("/long"), env={"READ_PAGE_SKIP": "browser"}, own_dir=False)
    imgs = {e.get("alt"): e for e in rl.manifest.get("images") or []}
    lbody = rl.file("content.md")
    check("the first answer downloads its window's pictures, not the page's last one",
          gets("/w/top.png") == 1 and gets("/w/bottom.png") == 0
          and (imgs.get("Top chart") or {}).get("file") and not (imgs.get("Bottom chart") or {}).get("file"),
          "top %d bottom %d" % (gets("/w/top.png"), gets("/w/bottom.png")))
    bottom = imgs.get("Bottom chart") or {}
    check("every picture is numbered and listed from the first call, with its line",
          bottom.get("n") and bottom.get("line") and bottom.get("why") == "not printed yet"
          and "[img #%d" % bottom["n"] in lbody.split("\n")[bottom["line"] - 1], str(bottom))
    check("a picture cut by the 6 s phase is marked so",
          str((imgs.get("Slow chart") or {}).get("why") or "").startswith("no time"),
          str(imgs.get("Slow chart")))
    n_lines = len(lbody.split("\n"))
    rc2 = run_read(s.url("/long"), "--from", str(bottom.get("line") or 1), env={"READ_PAGE_SKIP": "browser"},
                   own_dir=False, reuse=rl)
    imgs2 = {e.get("alt"): e for e in rc2.manifest.get("images") or []}
    cbody = rc2.file("content.md")
    check("a continuation downloads the pictures of the lines it prints, in place",
          gets("/w/bottom.png") == 1 and (imgs2.get("Bottom chart") or {}).get("file")
          and (imgs2["Bottom chart"]["file"] in cbody.split("\n")[bottom["line"] - 1])
          and len(cbody.split("\n")) == n_lines,
          "bottom GETs %d, lines %d -> %d" % (gets("/w/bottom.png"), n_lines, len(cbody.split("\n"))))
    rc3 = run_read(s.url("/long"), "--from", "1", env={"READ_PAGE_SKIP": "browser"}, own_dir=False, reuse=rl)
    imgs3 = {e.get("alt"): e for e in rc3.manifest.get("images") or []}
    check("printed again, a picture the 6 s phase cut is fetched again",
          (imgs3.get("Slow chart") or {}).get("file") and len(slow_hits) >= 2,
          "%s, %d requests" % (imgs3.get("Slow chart"), len(slow_hits)))

    # ------------------------------------------------ a failed picture is asked once more, later
    # a measured run found every answer from the cache asking a dead picture host again (0.55 s instead
    # of 0.23 on dmoz's archive copy; a host that never answers would cost the whole phase each time)
    busy_page = ("<!doctype html><html><head><title>Busy</title></head><body><article><h1>Busy</h1>"
                 "<p>BUSY-PARA " + EN * 3 + "</p><p><img src='/w/busy.png' alt='Busy chart'></p>"
                 "<p>BUSY-END " + EN * 2 + "</p></article></body></html>")
    s.routes.update({"/busy": (200, HTML_H, busy_page.encode("utf-8")),
                     "/w/busy.png": (503, {"Content-Type": "text/plain"}, b"busy")})
    s.log.clear()
    rb1 = run_read(s.url("/busy"), env={"READ_PAGE_SKIP": "browser"}, own_dir=False)
    busy = next((e for e in rb1.manifest.get("images") or [] if e.get("alt") == "Busy chart"), {})
    first_gets = gets("/w/busy.png")
    rb2 = run_read(s.url("/busy"), env={"READ_PAGE_SKIP": "browser"}, own_dir=False, reuse=rb1)
    check("a picture that just failed is not asked again by the next answer from the cache",
          first_gets >= 1 and not busy.get("file") and busy.get("why") == "503" and gets("/w/busy.png") == first_gets
          and "from cache" in rb2.text.split("\n")[0],
          "first %d, then %d; %s" % (first_gets, gets("/w/busy.png"), busy))
    mpath = os.path.join(rb1.dir, "manifest.json")
    with open(mpath, encoding="utf-8") as fh:
        mb = json.load(fh)
    for e in mb.get("images") or []:
        if e.get("alt") == "Busy chart" and e.get("failed_at"):
            e["failed_at"] -= 120                    # two minutes later
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(mb, fh)
    run_read(s.url("/busy"), env={"READ_PAGE_SKIP": "browser"}, own_dir=False, reuse=rb1)
    later_gets = gets("/w/busy.png")
    run_read(s.url("/busy"), env={"READ_PAGE_SKIP": "browser"}, own_dir=False, reuse=rb1)
    check("printed later, it is asked once more, and then never again",
          later_gets > first_gets and gets("/w/busy.png") == later_gets,
          "first %d, later %d, last %d" % (first_gets, later_gets, gets("/w/busy.png")))

    # ------------------------------------------------ readability's Markdown is not wrapped
    # Le Monde: html2text's default 78 columns split a photo's alt and address
    # over three lines, so the picture stayed a raw `![...](...)` with a broken address, no marker
    wide = "/w/a-photo-of-the-reading-room-of-the-old-library-at-dusk-with-every-lamp-lit.png"
    wrap_page = ("<!doctype html><html><head><title>Wrap</title></head><body><article><h1>Wrap</h1>"
                 "<p>WRAP-PARA " + EN * 3 + "</p><figure><img src='" + wide + "' alt='A wide photo of the "
                 "reading room of the old library at dusk, every lamp lit, the shelves full'><figcaption>The "
                 "reading room</figcaption></figure><p>WRAP-END " + EN * 2 + "</p></article></body></html>")
    s.routes.update({"/wrap": (200, HTML_H, wrap_page.encode("utf-8")), wide: (200, PNG_H, png(80, 60))})
    rw = run_read(s.url("/wrap"), env={"READ_PAGE_SKIP": "browser,defuddle,trafilatura"})
    wbody = rw.file("content.md")
    para = [ln for ln in wbody.split("\n") if ln.startswith("WRAP-PARA")]
    weng = str((rw.manifest.get("content") or {}).get("engine"))
    if "readability" not in weng:
        check.skip("readability's text keeps a paragraph on one line", "readability-lxml is not here (%s)" % weng)
    else:
        check("readability's text keeps a paragraph on one line and its picture a marker",
              para and para[0].rstrip().endswith("first paint.") and "![" not in wbody
              and re.search(r"\[img #\d+ · 80x60", wbody), "%s | %s" % (weng, wbody[:300].replace("\n", " / ")))
finally:
    s.close()

# ------------------------------------------------ the block rule places pictures too
CONTENT = "# Flows\n\nINTRO-PARA " + EN * 3 + "\n\nMIDDLE-PARA " + EN * 3
PAGE = ("# Flows\n\nINTRO-PARA " + EN * 3 + " ![ok](https://x.org/icon.png)\n\n![Diagram of the flow](/img/d.png)"
        "\n\nMIDDLE-PARA " + EN * 3 + "\n\n* [Home](/)\n* [Docs](/docs)\n* [Blog](/b)\n* [About](/a)\n\n"
        "![Site logo](/img/logo.png)")
out, info = blockrule.restore(CONTENT, PAGE, base="https://x.org/page")
p_icon, p_diag, p_mid = out.find("icon.png"), out.find("Diagram of the flow"), out.find("MIDDLE-PARA")
check("a picture the extractor dropped from a kept paragraph comes back after it",
      0 < p_icon < p_mid, str((p_icon, p_mid)))
check("a picture standing between two kept paragraphs comes back between them", 0 < p_diag < p_mid,
      str((p_diag, p_mid)))
check("a picture outside the shown blocks stays out (the logo after the menu)", "logo" not in out, "")
again, info2 = blockrule.restore(out, PAGE, base="https://x.org/page")
check("a second pass adds no picture twice", again == out, "")

# ------------------------------------------------ the answer window: a repeat is short
full = "[img #3 · 100x80 2K · Diagram of the flow] img/03-diagram-of-the-flow.png"
tiny = "[img #4 · 16x16 1K · ✓] img/04-ok.png"
txt = "\n".join(["A " + full, "B " + tiny, "C " + full, "D " + tiny + " and " + tiny])
said, _ = answer.render({"status": "ok"}, txt, "content.md", 1, lambda n, t, v: "next %d" % n)
lines = [ln for ln in said.split("\n") if ln[:2] in ("A ", "B ", "C ", "D ")]
check("in one answer a picture's first marker is full, a repeat is `[img #N]`",
      len(lines) == 4 and full in lines[0] and lines[2] == "C [img #3]", str(lines[2:3]))
check("a repeat of a tiny picture with a short alt is its alt", lines[3] == "D ✓ and ✓", str(lines[3:4]))
check("content.md keeps every marker full", txt.count(full) == 2, "")

# ------------------------------------------------ the list of pictures without a place: ten lines at most
mod_spec = importlib.util.spec_from_file_location("pictures", os.path.join(os.path.dirname(HERE), "scripts",
                                                                           "pictures.py"))
pictures = importlib.util.module_from_spec(mod_spec)
mod_spec.loader.exec_module(pictures)
e4 = {"n": 4, "file": "img/04-icon.png", "bytes": 3000, "dims": "40x40", "alt": "icon"}
md = "[![icon](/i.png)](https://w.org/File:I.svg)[Next](/p) and |![a](/i.png)| cell ![a](/i.png)Caption"
got = pictures.mark(md, "https://x.org/", {"https://x.org/i.png": e4})
check("a marker's path ends clean (a link after it, a table bar, a glued caption)",
      "img/04-icon.png (https://w.org/File:I.svg)" in got and "img/04-icon.png |" in got
      and "img/04-icon.png\nCaption" in got, got)
entries = [{"n": i, "file": "img/%02d-p.png" % i, "bytes": 2048, "dims": "10x10", "alt": "p%d" % i}
           for i in range(1, 15)]
lst = pictures.unplaced_list(entries)
check("pictures without a place are listed, ten lines at most",
      lst.count("[img #") == 10 and "4 more" in lst and "manifest.json" in lst, lst[-80:])
doc = ("Words of the document itself. [img #1 · 10x10 2K · p1] img/01-p.png and a tail.\n\n"
       + pictures.unplaced_list(entries))
own = pictures.unmarked(doc).split() if hasattr(pictures, "unmarked") else []
check("a document's own words leave out its pictures' markers and their list (a deck of 9 pictures was `ok` "
      "on their 60)", own == ["Words", "of", "the", "document", "itself.", "and", "a", "tail."], str(own))

# ------------------------------------------------ --ocr N: a picture's text for a model that cannot see it
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
SVG_TEXT = (b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="80"><rect width="300" height="80" '
            b'fill="#eee"/><text x="10" y="30">ALPHA-STEP</text><text x="10" y="60">BETA-STEP</text></svg>')
if Image is None:
    check.skip("--ocr: a picture's text", "no Pillow here")
else:
    pic = Image.new("RGB", (900, 220), (244, 204, 204))         # a box tinted as on a diagram
    draw = ImageDraw.Draw(pic)
    font = None
    for face in ("arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            font = ImageFont.truetype(face, 44)
            break
        except OSError:
            continue
    draw.text((30, 40), "QUARTERLY REPORT", fill=(89, 89, 89), font=font)
    draw.text((30, 120), "Total 42 units", fill=(89, 89, 89), font=font)
    buf = io.BytesIO()
    pic.save(buf, "PNG")
    srv_o = serve({"/report": (200, {"Content-Type": "text/html"},
                               ("<html><body><h1>Report</h1><p>%s</p><img src=\"/chart.png\" alt=\"chart\">"
                                "<img src=\"/flow.svg\" alt=\"flow\"></body></html>" % ("Numbers of the quarter. " * 20))
                               .encode()),
                   "/chart.png": (200, PNG_H, buf.getvalue()),
                   "/flow.svg": (200, {"Content-Type": "image/svg+xml"}, SVG_TEXT)})
    try:
        r = run_read(srv_o.url("/report"), "--ocr", "1")
        ocr_row = next((ln for ln in r.text.split("\n") if ln.startswith("ocr: ")), "")
        has_engine = "no OCR engine" not in ocr_row and "OCR is off" not in ocr_row
        if not has_engine:
            check.skip("--ocr 1: the text drawn in a picture", ocr_row)
        else:
            check("--ocr 1: the text drawn in a picture, on a tinted box, instead of the page's text",
                  "QUARTERLY REPORT" in r.text and "42" in r.text and "Numbers of the quarter" not in r.text
                  and "img #1 text" in r.text.split("\n")[0], ocr_row + " | " + r.text[-120:].replace("\n", " / "))
        r = run_read(srv_o.url("/report"), "--ocr", "2", reuse=r)
        check("--ocr 2: an SVG drawing gives its own text, no OCR needed",
              "ALPHA-STEP" in r.text and "BETA-STEP" in r.text and "the drawing's own text" in r.text,
              r.text[:200].replace("\n", " / "))
        r = run_read(srv_o.url("/report"), "--ocr", "9", reuse=r)
        check("--ocr 9: a number the page has no picture for says so, and prints nothing else",
              "ocr: this page has no picture #9 (2 in all)" in r.text and "img #9 text is empty" in r.text,
              r.text[:200].replace("\n", " / "))
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
        import mcp_server                                            # noqa: E402
        first = mcp_server.tool_read_url({"url": srv_o.url("/report"), "ocr": 2})
        said = first["content"][0]["text"]
        check("MCP read_url ocr=2: the same text as --ocr 2", "ALPHA-STEP" in said and not first.get("isError"),
              said[:120])
        # the CLI's folder has picture 1 on disk (its --ocr 1 fetched it)
        pngs = [e for e in (json.load(open(os.path.join(r.dir, "manifest.json"), encoding="utf-8"))
                            .get("images") or []) if e.get("n") == 1 and e.get("file")]
        # this call runs in the suite's own Python, not in the --setup environment the CLI runs above
        # went into: it can OCR only with an engine of its own
        here = mcp_server.readpage._tesserocr() is not None or bool(mcp_server.readpage.which("tesseract"))
        if has_engine and not here:
            check.skip("MCP read ocr=true on a picture file", "no OCR engine in the suite's own Python")
        elif has_engine:
            got = (mcp_server.tool_read({"dir": r.dir, "file": pngs[0]["file"], "ocr": True}) if pngs
                   else {"content": [{"text": "picture 1 is not on disk"}]})
            check("MCP read ocr=true on a picture file: its text instead of the image",
                  "QUARTERLY REPORT" in got["content"][0]["text"] and len(got["content"]) == 1,
                  got["content"][0]["text"][:120])
    finally:
        srv_o.close()


# ------------------------------------------------ a run of `[img #N · ` that no `]` closes
# The marker pattern scanned from each one to the end of its line: 8 000 in a line took 8.2 s, 16 000 43.7 s
# (2026-11-21). Linear is a ratio of two sizes, not a number of seconds (a slow runner is slower at both).
def timed_twice(fn, small, big):
    """fn(small) and fn(big): (the big result, seconds big / small, whether big is within 8 times small)."""
    import time as _t

    def one(arg):
        t0 = _t.perf_counter()
        out = fn(arg)
        return out, _t.perf_counter() - t0
    out, hi = one(big)
    lo = one(small)[1]
    if hi > 8 * max(lo, 0.05):                          # a busy machine slows one run, not both: again
        hi, lo = min(hi, one(big)[1]), min(lo, one(small)[1])
    return out, "%.3fs / %.3fs" % (hi, lo), hi <= 8 * max(lo, 0.05)


import pictures                                              # noqa: E402
for label, piece in (("[img #1 · ", "[img #1 · "), ("[img #1 · [", "[img #1 · [")):
    out, said, linear = timed_twice(lambda n: pictures.compact([piece * n]), 2000, 8000)
    check("pictures.MARK is linear on 8 000 unclosed %r in a line (8 000 took 8.2 s)" % label,
          linear and out == [piece * 8000], said)
out = pictures.compact(["[img #3 · 100x80 3K · alt] img/03-alt.png and [img #3 · 100x80 3K · alt] img/03-alt.png"])
check("... and a repeated marker is still shortened", out == ["[img #3 · 100x80 3K · alt] img/03-alt.png and [img #3]"],
      repr(out))
import mcp_server                                            # noqa: E402
out, said, linear = timed_twice(lambda n: mcp_server.ANY_MARKER.findall("[img #1 · " * n), 2000, 8000)
check("the MCP server's marker pattern is linear on the same run (it had the same scan)", linear and out == [], said)
check("... and still finds a marker", mcp_server.ANY_MARKER.findall("x [img #2 · 5x5 1K · a] img/02-a.png y")
      == [("2", "img/02-a.png")], "")

sys.exit(check.done())
