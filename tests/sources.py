"""The public readers and the site APIs. No network.

    python -X utf8 tests/sources.py

The public readers are asked in the order measured: Firecrawl, Jina, Exa,
Tavily, then defuddle.md. A reader without its key is skipped, and a key goes only to its own
service. The first reader with real text ends the chain, so no credit is spent after it; a wall,
too little text, the service's own error or a slow reader moves on to the next one; a 404 the
reader saw ends the chain. A site with its own API (Stack Exchange, npm, Hacker News, X through
fxtwitter) is read through it without a flag; when the API fails, the ordinary path reads the page.
"""
import gzip
import http.server
import importlib.util
import io
import json
import os
import re
import socketserver
import sys
import tempfile
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness import PUBLIC, SCRIPT, Checks, serve           # noqa: E402

check = Checks()
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ") * 14
KEYS = {"FIRECRAWL_API_KEY": "fc-test-key-1", "EXA_API_KEY": "exa-test-key-2", "TAVILY_API_KEY": "tvly-test-key-3"}


def tarball():
    """A package tarball as npm packs it: package.json first, the README after it."""
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in (("package/package.json", b'{"name": "pkg"}'),
                           ("package/README.md", b"# pkg\n\nNPM-README usage: `npm i pkg`.\n"),
                           ("package/index.js", b"module.exports = 1;\n" * 2000)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


TARBALL = tarball()
WALL_TITLE = "Just a moment..."
WALL_TEXT = "Checking your browser before accessing example.org. This process is automatic."


class Api(http.server.BaseHTTPRequestHandler):
    """Every remote service on one local port. `mode[service]` says how it answers this time."""
    protocol_version = "HTTP/1.1"
    mode = {}
    log = []
    hn = {}

    def log_message(self, *a):
        pass

    def answer(self, code, body, ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(b)
        except OSError:
            pass
        self.close_connection = True

    def stall(self):
        try:
            time.sleep(30)
        except OSError:
            pass

    def service(self):
        p = self.path
        for name in ("firecrawl", "jina", "exa", "tavily", "defuddle", "se", "npm", "hn", "fx", "pm"):
            if p.startswith("/" + name):
                return name
        return "?"

    def record(self, body=""):
        name = self.service()
        type(self).log.append({"service": name, "method": self.command, "path": self.path, "body": body,
                               "headers": {k.lower(): v for k, v in self.headers.items()}})
        return name, type(self).mode.get(name, "ok")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace") if n else ""
        name, mode = self.record(body)
        if mode == "stall":
            return self.stall()
        try:
            asked = json.loads(body or "{}")
        except ValueError:
            asked = {}
        url = asked.get("url") or (asked.get("urls") or [""])[0]
        if name == "firecrawl":
            if mode == "402":
                return self.answer(402, {"success": False, "error": "Payment required"})
            md, title, st = {"ok": ("# Doc\n\nFIRECRAWL-TEXT " + EN, "Doc", 200),
                             "wall": ("# " + WALL_TITLE + "\n\n" + WALL_TEXT, WALL_TITLE, 200),
                             "404": ("# Not Found\n\nThe page is not here.", "Not Found", 404),
                             "403": ("# Forbidden\n\nAccess denied.", "Forbidden", 403)}[mode]
            return self.answer(200, {"success": True, "data": {"markdown": md, "metadata": {
                "title": title, "statusCode": st, "sourceURL": url}}})
        if name == "jina":
            text = {"ok": "Title: Doc\n\nURL Source: %s\n\nMarkdown Content:\nJINA-TEXT %s" % (url, EN),
                    "wall": "Title: %s\n\nURL Source: %s\n\nMarkdown Content:\n%s" % (WALL_TITLE, url, WALL_TEXT),
                    "little": "Title: Doc\n\nMarkdown Content:\nHi."}[mode]
            return self.answer(200, text, "text/plain; charset=utf-8")
        if name == "exa":
            if mode == "404":
                return self.answer(200, {"results": [], "statuses": [
                    {"id": url, "status": "error", "error": {"tag": "CRAWL_NOT_FOUND", "httpStatusCode": 404}}]})
            title, text = {"ok": ("Doc", "EXA-TEXT " + EN), "wall": (WALL_TITLE, WALL_TEXT),
                           "little": ("Doc", "Hi.")}[mode]
            return self.answer(200, {"results": [{"url": url, "id": url, "title": title, "text": text}],
                                     "statuses": [{"id": url, "status": "success"}]})
        if name == "tavily":
            if mode == "fail":
                return self.answer(200, {"results": [], "failed_results": [{"url": url, "error": "Failed to fetch"}]})
            text = {"ok": "TAVILY-TEXT " + EN, "wall": WALL_TITLE + "\n\n" + WALL_TEXT}[mode]
            return self.answer(200, {"results": [{"url": url, "raw_content": text, "title": "Doc"}],
                                     "failed_results": []})
        return self.answer(404, {"error": "no such service"})

    def do_GET(self):
        name, mode = self.record()
        if mode == "stall":
            return self.stall()
        if mode == "500":
            return self.answer(500, {"error": "down"})
        p = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(p.query)
        if name == "defuddle":
            if mode == "wall":
                return self.answer(200, '---\ntitle: "%s"\n---\n\n%s' % (WALL_TITLE, WALL_TEXT), "text/markdown")
            return self.answer(200, '---\ntitle: "Doc title"\nsource: "x"\nword_count: 300\n---\n\nDEFUDDLE-TEXT '
                               + EN, "text/markdown; charset=utf-8")
        if name == "se":
            if p.path.endswith("/answers"):
                return self.answer(200, {"items": [
                    {"score": 120, "is_accepted": False, "owner": {"display_name": "Second"},
                     "body": "<p>SE-ANSWER-TWO a later answer with fewer votes.</p>"},
                    {"score": 3400, "is_accepted": True, "owner": {"display_name": "Mysticial"},
                     "body": "<p>SE-ANSWER-ONE <b>branch prediction</b> explains it.</p><pre><code>if (data[c] &gt;= 128)\n"
                             "    sum += data[c];</code></pre>"}]})
            return self.answer(200, {"items": [{"title": "Why is processing a sorted array faster?", "score": 27000,
                                                "answer_count": 2, "creation_date": 1340805096,
                                                "tags": ["java", "c++", "performance"],
                                                "owner": {"display_name": "GManNickG"},
                                                "link": "https://stackoverflow.com/questions/11227809/x",
                                                "body": "<p>SE-QUESTION-BODY here is a piece of C++ code.</p>",
                                                "site": q.get("site", [""])[0]}]})
        if name == "npm":
            if p.path.endswith(".tgz"):
                return self.answer(200, TARBALL, "application/octet-stream")
            pkg, _, ver = urllib.parse.unquote(p.path[len("/npm/"):]).rpartition("/")
            return self.answer(200, {"name": pkg, "version": "2.1.0" if ver == "latest" else ver,
                                     "description": "NPM-DESCRIPTION a tiny package", "license": "MIT",
                                     "repository": {"type": "git", "url": "git+https://github.com/x/y.git"},
                                     "dist": {"tarball": "http://%s:%d/npm/%s/-/pkg-2.1.0.tgz" % (
                                         PUBLIC, self.server.server_address[1], pkg)}})
        if name == "hn":
            iid = re.search(r"/item/(\d+)\.json", p.path)
            return self.answer(200, type(self).hn.get(iid.group(1) if iid else "", None))
        if name == "fx":
            return self.answer(200, {"code": 200, "message": "OK", "tweet": {
                "id": "20", "text": "FX-TWEET-TEXT just setting up my twttr",
                "author": {"name": "jack", "screen_name": "jack"}, "created_at": "Tue Mar 21 20:50:14 +0000 2006",
                "likes": 300000, "retweets": 120000, "replies": 17000}})
        if name == "pm":
            if q.get("id") == ["999"]:
                return self.answer(200, "<?xml version='1.0'?><PubmedArticleSet></PubmedArticleSet>", "text/xml")
            if q.get("id") == ["20301331"]:
                return self.answer(200, PM_BOOK, "text/xml; charset=UTF-8")
            if q.get("id") == ["40225927"]:
                # NCBI sends its records gzipped to a client that asks for it
                return self.answer(200, gzip.compress(PM_SUP.encode("utf-8")), "text/xml; charset=UTF-8",
                                   {"Content-Encoding": "gzip"})
            return self.answer(200, PM_XML, "text/xml; charset=UTF-8")
        return self.answer(404, {"error": "no such service"})


# a record as NCBI's efetch sends it, cut to what the adapter reads: inline markup in the title, an
# abstract in labelled sections, a group among the authors, a MeSH term with a comma of its own
PM_XML = """<?xml version="1.0" ?>
<PubmedArticleSet><PubmedArticle><MedlineCitation Status="MEDLINE"><PMID Version="1">22745249</PMID>
<Article PubModel="Print-Electronic"><Journal><JournalIssue CitedMedium="Internet"><Volume>337</Volume>
<Issue>6096</Issue><PubDate><Year>2012</Year><Month>Aug</Month><Day>17</Day></PubDate></JournalIssue>
<Title>Science (New York, N.Y.)</Title><ISOAbbreviation>Science</ISOAbbreviation></Journal>
<ArticleTitle>A programmable <i>dual-RNA</i>-guided DNA endonuclease.</ArticleTitle>
<Pagination><MedlinePgn>816-21</MedlinePgn></Pagination>
<ELocationID EIdType="doi" ValidYN="Y">10.1126/science.1225829</ELocationID>
<Abstract><AbstractText Label="BACKGROUND">PM-BACKGROUND adaptive immunity in bacteria.</AbstractText>
<AbstractText Label="RESULTS">PM-RESULTS the Cas9 endonuclease is guided by two RNAs.</AbstractText></Abstract>
<AuthorList><Author><LastName>Jinek</LastName><ForeName>Martin</ForeName><Initials>M</Initials></Author>
<Author><CollectiveName>The CRISPR Group</CollectiveName></Author></AuthorList>
<PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType></PublicationTypeList>
</Article><MeshHeadingList><MeshHeading><DescriptorName UI="D001426">Bacterial Proteins</DescriptorName>
</MeshHeading><MeshHeading><DescriptorName UI="D014614">Vaccines, Synthetic</DescriptorName></MeshHeading>
</MeshHeadingList></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pubmed">22745249</ArticleId>
<ArticleId IdType="pmc">PMC6286148</ArticleId><ArticleId IdType="doi">10.1126/science.1225829</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""

# a book's record, as efetch sends one for a chapter of GeneReviews (StatPearls is the same shape)
PM_BOOK = """<?xml version="1.0" ?>
<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID Version="1">20301331</PMID><ArticleIdList>
<ArticleId IdType="bookaccession">NBK1152</ArticleId></ArticleIdList><Book><Publisher><PublisherName>University of
Washington, Seattle</PublisherName><PublisherLocation>Seattle (WA)</PublisherLocation></Publisher>
<BookTitle book="gene">GeneReviews<sup>&#xae;</sup></BookTitle><PubDate><Year>1993</Year></PubDate>
<BeginningDate><Year>1993</Year></BeginningDate><EndingDate><Year>2026</Year></EndingDate>
<AuthorList Type="editors"><Author><LastName>Adam</LastName><ForeName>Margaret P</ForeName></Author></AuthorList>
</Book><ArticleTitle book="gene" part="achondroplasia">Achondroplasia</ArticleTitle><Language>eng</Language>
<AuthorList Type="authors"><Author><LastName>Legare</LastName><ForeName>Janet M</ForeName></Author></AuthorList>
<PublicationType UI="D016454">Review</PublicationType><Abstract><AbstractText Label="CLINICAL CHARACTERISTICS">
PM-BOOK-ABSTRACT achondroplasia is the most common cause of disproportionate short stature.</AbstractText>
</Abstract><Sections><Section><SectionTitle book="gene" part="achondroplasia">Summary</SectionTitle></Section>
<Section><SectionTitle book="gene" part="achondroplasia">Diagnosis</SectionTitle></Section></Sections>
</BookDocument><PubmedBookData><ArticleIdList><ArticleId IdType="pubmed">20301331</ArticleId></ArticleIdList>
</PubmedBookData></PubmedBookArticle></PubmedArticleSet>"""

# an exponent and a citation mark in an abstract (PMID 40225927's "P = 2.2 × 10<sup>-16</sup>")
PM_SUP = PM_XML.replace("PM-RESULTS the Cas9 endonuclease is guided by two RNAs.",
                        "PM-SUP association at P = 2.2 × 10<sup>-16</sup> with autophagy<sup>1</sup> and CO<sub>2</sub>.")


def start_api():
    srv = socketserver.ThreadingTCPServer((PUBLIC, 0), Api)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://%s:%d" % (PUBLIC, srv.server_address[1])


def module(base):
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-src-")
    spec = importlib.util.spec_from_file_location("rp_src_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.FIRECRAWL_URL = base + "/firecrawl/v2/scrape"
    mod.JINA_URL = base + "/jina/"
    mod.EXA_URL = base + "/exa/contents"
    mod.TAVILY_URL = base + "/tavily/extract"
    mod.DEFUDDLE_MD_URL = base + "/defuddle/"
    sa = mod.siteapi
    sa.SE_API, sa.NPM_API, sa.HN_API, sa.FX_API = base + "/se/2.3", base + "/npm", base + "/hn/v0", base + "/fx"
    sa.PM_API = base + "/pm"
    return mod


def keys(on):
    for k, v in KEYS.items():
        if on:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    os.environ.pop("JINA_API_KEY", None)


def ask(mod, mode, url="https://example.org/doc", refresh=False):
    Api.mode = dict(mode)
    Api.log.clear()
    t0 = time.monotonic()
    out = mod.external_read(url, mod.caps(), refresh=refresh)
    return out, [e["service"] for e in Api.log], time.monotonic() - t0


def inproc(mod, argv):
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        mod.main(argv + ["--json", "--dir", tempfile.mkdtemp(prefix="rp-src-out-")])
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


api, base = start_api()
PAGE = ("<!doctype html><html><head><title>Local</title></head><body><article><h1>Local</h1><p>"
        "LOCAL-PAGE-TEXT " + EN + "</p></article></body></html>").encode("utf-8")
site = serve({"/item": (200, {"Content-Type": "text/html; charset=utf-8"}, PAGE)})
ALL_WALL = {"firecrawl": "wall", "jina": "wall", "exa": "wall", "tavily": "wall", "defuddle": "wall"}

try:
    mod = module(base)
    mod.SKIP.add("browser")              # nothing here needs one; --alternate would start it
    # ------------------------------------------------ the readers' order, keys gate the paid ones
    keys(True)
    # Firecrawl out of credits and Exa with too little text fail for their own reasons: every
    # reader is asked, in the readers' order
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, firecrawl="402", exa="little"))
    check("with every key: Firecrawl, Jina, Exa, Tavily, defuddle.md",
          order == ["firecrawl", "jina", "exa", "tavily", "defuddle"] and not text, "%s | %s" % (order, note[:80]))
    check("a wall from any reader is not text, and the note says which met it",
          not text and note.count("wall") >= 3, note[:120])
    sent = {e["service"]: json.dumps(e["headers"]) + e["body"] + e["path"] for e in Api.log}
    own = {"firecrawl": KEYS["FIRECRAWL_API_KEY"], "exa": KEYS["EXA_API_KEY"], "tavily": KEYS["TAVILY_API_KEY"]}
    leaks = ["%s got %s's key" % (svc, other) for svc, blob in sent.items() for other, k in own.items()
             if other != svc and k in blob]
    check("each key goes to its own service only", not leaks, ", ".join(leaks))
    hdr = {e["service"]: e["headers"] for e in Api.log}
    check("Firecrawl and Tavily get a Bearer key, Exa its x-api-key header",
          hdr.get("firecrawl", {}).get("authorization") == "Bearer " + KEYS["FIRECRAWL_API_KEY"]
          and hdr.get("tavily", {}).get("authorization") == "Bearer " + KEYS["TAVILY_API_KEY"]
          and hdr.get("exa", {}).get("x-api-key") == KEYS["EXA_API_KEY"], "")
    (text, eng, st, note), order, _ = ask(mod, ALL_WALL)
    check("a paid reader met the wall: no other paid reader is asked, the free ones are",
          order == ["firecrawl", "jina", "defuddle"] and "not asked, firecrawl met the wall" in note,
          "%s | %s" % (order, note[-90:]))
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, firecrawl="403"))
    check("a 403 a paid reader saw is a wall too", order == ["firecrawl", "jina", "defuddle"] and st == 403,
          "%s %s" % (order, st))
    keys(False)
    (text, eng, st, note), order, _ = ask(mod, ALL_WALL)
    check("without keys only Jina and defuddle.md are asked", order == ["jina", "defuddle"], str(order))
    check("Jina without its key sends no Authorization header",
          "authorization" not in (Api.log[0]["headers"] if Api.log else {}), "")

    # ------------------------------------------------ the first text ends the chain
    keys(True)
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, jina="ok"))
    check("the first reader with text ends the chain (no credit spent after it)",
          "JINA-TEXT" in (text or "") and eng == "reader:jina" and order == ["firecrawl", "jina"],
          "%s %s" % (eng, order))
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, firecrawl="402", exa="ok"))
    exa_req = next((json.loads(e["body"]) for e in Api.log if e["service"] == "exa"), {})
    check("Exa's text is read, the address in its JSON body",
          "EXA-TEXT" in (text or "") and eng == "reader:exa" and exa_req.get("urls") == ["https://example.org/doc"]
          and exa_req.get("text") is True, "%s %s" % (eng, exa_req))
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, firecrawl="402", exa="little", tavily="ok"))
    tv_req = next((json.loads(e["body"]) for e in Api.log if e["service"] == "tavily"), {})
    check("too little text moves on; Tavily's markdown is read",
          "TAVILY-TEXT" in (text or "") and eng == "reader:tavily" and tv_req.get("urls") == ["https://example.org/doc"],
          "%s %s" % (eng, order))
    keys(False)
    target = "https://example.org/a b/путь?q=1"
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, defuddle="ok"), url=target)
    dpath = next((e["path"] for e in Api.log if e["service"] == "defuddle"), "")
    check("defuddle.md: the front matter goes, the title stays as a heading",
          eng == "reader:defuddle.md" and (text or "").startswith("# Doc title") and "word_count:" not in (text or "")
          and "DEFUDDLE-TEXT" in (text or ""), (text or "")[:60])
    check("defuddle.md gets the whole address, encoded",
          urllib.parse.unquote(dpath[len("/defuddle/"):]) == target, dpath[:90])

    # ------------------------------------------------ what ends the chain and what moves it on
    keys(True)
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, firecrawl="404"))
    check("a 404 the reader saw ends the chain (every reader would see it)",
          not text and st == 404 and order == ["firecrawl"], "%s %s" % (st, order))
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, firecrawl="402", jina="wall", exa="404"))
    check("Exa's 404 is the page's status too", st == 404 and order == ["firecrawl", "jina", "exa"],
          "%s %s" % (st, order))
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, firecrawl="402", jina="ok"))
    check("a reader's own error (HTTP 402) moves on to the next",
          "JINA-TEXT" in (text or "") and order == ["firecrawl", "jina"], "%s %s" % (eng, order))
    mod.READER_SECONDS = 2
    (text, eng, st, note), order, dt = ask(mod, dict(ALL_WALL, firecrawl="stall", jina="ok"))
    check("a stalled reader costs its bound, then the next one answers",
          "JINA-TEXT" in (text or "") and dt < 6, "%.1f s %s" % (dt, order))
    mod.READERS_STEP_SECONDS = 5
    (text, eng, st, note), order, dt = ask(mod, {k: "stall" for k in ALL_WALL})
    check("the whole chain stays inside its step", not text and dt < 7 and len(order) < 5,
          "%.1f s %s" % (dt, order))
    mod.READER_SECONDS, mod.READERS_STEP_SECONDS = 12, 20
    (text, eng, st, note), order, _ = ask(mod, dict(ALL_WALL, tavily="ok"), refresh=True)
    first = {e["service"]: e for e in Api.log}
    fc = json.loads(first.get("firecrawl", {}).get("body") or "{}")
    check("--refresh asks Firecrawl (maxAge 0) and Jina (x-no-cache) for a fresh copy",
          fc.get("maxAge") == 0 and first.get("jina", {}).get("headers", {}).get("x-no-cache") == "true", str(fc)[:80])
    keys(False)

    # ------------------------------------------------ which addresses have an adapter
    sa = mod.siteapi
    cases = {
        "https://stackoverflow.com/questions/11227809/why-is-processing": "stackexchange",
        "https://stackoverflow.com/q/11227809": "stackexchange",
        "https://unix.stackexchange.com/questions/4126/what-is-the-exact-difference": "stackexchange",
        "https://superuser.com/questions/12345/x": "stackexchange",
        "https://askubuntu.com/questions/1/x": "stackexchange",
        "https://www.npmjs.com/package/trafilatura": "npm",
        "https://www.npmjs.com/package/@types/node": "npm",
        "https://www.npmjs.com/package/react/v/18.2.0": "npm",
        "https://news.ycombinator.com/item?id=8863": "hn",
        "https://x.com/jack/status/20": "x",
        "https://twitter.com/jack/status/20?s=20": "x",
        "https://mobile.twitter.com/jack/status/20": "x",
        "https://stackoverflow.com/users/1/jeff-atwood": None,
        "https://stackoverflow.com/questions/tagged/python": None,
        "https://www.npmjs.com/search?q=react": None,
        "https://news.ycombinator.com/news": None,
        "https://x.com/jack": None,
        "https://example.com/questions/1/x": None,
    }
    wrong = ["%s -> %s" % (u, (sa.which(u) or [None])[0]) for u, want in cases.items()
             if (sa.which(u) or [None])[0] != want]
    check("the adapters take exactly their own addresses (%d cases)" % len(cases), not wrong, "; ".join(wrong[:3]))

    # ------------------------------------------------ each adapter, JSON into Markdown
    Api.mode, Api.log[:] = {}, []
    got = sa.read("https://stackoverflow.com/questions/11227809/why-is-processing", 10)
    md, eng, raw = got or ("", "", "")
    se_q = [e["path"] for e in Api.log if e["service"] == "se"]
    check("Stack Overflow through its API: the question, then answers by votes",
          eng == "api:stackexchange" and md.startswith("# Why is processing a sorted array faster?")
          and "SE-QUESTION-BODY" in md and md.find("SE-ANSWER-ONE") < md.find("SE-ANSWER-TWO") and "accepted" in md,
          "%s %r" % (eng, md[:60]))
    check("the API is asked for that question on that site",
          se_q and all("/questions/11227809" in p and "site=stackoverflow" in p for p in se_q), str(se_q)[:120])
    check("the raw JSON is kept", '"question"' in (raw or "") and '"answers"' in (raw or ""), (raw or "")[:60])
    Api.log.clear()
    sa.read("https://unix.stackexchange.com/questions/4126/x", 10)
    check("a Stack Exchange site is asked by its own name",
          any("site=unix" in e["path"] for e in Api.log), str([e["path"] for e in Api.log])[:100])
    Api.log.clear()
    md, eng, raw = sa.read("https://www.npmjs.com/package/@types/node", 10) or ("", "", "")
    paths = [e["path"] for e in Api.log]
    check("npm: the version's document, and the README from its tarball",
          eng == "api:npm" and "NPM-README" in md and "2.1.0" in md and "MIT" in md and "github.com/x/y" in md
          and "/npm/@types%2Fnode/latest" in paths and any(x.endswith(".tgz") for x in paths), "%s %s" % (eng, paths))
    Api.log.clear()
    sa.read("https://www.npmjs.com/package/react/v/18.2.0", 10)
    check("npm: a version in the address is the version asked for",
          [e["path"] for e in Api.log][:1] == ["/npm/react/18.2.0"], str([e["path"] for e in Api.log]))
    Api.hn = {
        "8863": {"id": 8863, "type": "story", "by": "dhouston", "title": "My YC app: Dropbox", "score": 104,
                 "url": "http://www.getdropbox.com/u/2/screencast.html", "time": 1175714200, "descendants": 71,
                 "kids": [9224, 8917, 8884]},
        "9224": {"id": 9224, "by": "BrandonM", "time": 1175727286, "text": "HN-COMMENT-ONE <i>you can already</i> build it."},
        "8917": {"id": 8917, "deleted": True, "time": 1175718900},
        "8884": {"id": 8884, "by": "x", "dead": True, "text": "HN-DEAD-COMMENT", "time": 1175715000},
    }
    md, eng, raw = sa.read("https://news.ycombinator.com/item?id=8863", 10) or ("", "", "")
    check("Hacker News: the story and its comments' text, without deleted or dead ones",
          eng == "api:hn" and "# My YC app: Dropbox" in md and "HN-COMMENT-ONE" in md and "HN-DEAD-COMMENT" not in md
          and "more comments" in md, "%s %r" % (eng, md[:80]))
    Api.log.clear()
    md, eng, raw = sa.read("https://x.com/jack/status/20?s=20&t=SECRET-TRACKER", 10) or ("", "", "")
    fx = [e["path"] for e in Api.log if e["service"] == "fx"]
    check("X through fxtwitter: the post's text and author", eng == "api:x" and "FX-TWEET-TEXT" in md
          and "@jack" in md, "%s %r" % (eng, md[:60]))
    check("fxtwitter learns only the post number",
          fx == ["/fx/status/20"], str(fx))
    # PubMed's page answers "Cookies must be enabled" to a client without its script's cookie
    # (2026-11-20); NCBI's own E-utilities have the record
    Api.log.clear()
    md, eng, raw = sa.read("https://pubmed.ncbi.nlm.nih.gov/22745249/?utm_source=x", 10) or ("", "", "")
    pm = [e["path"] for e in Api.log if e["service"] == "pm"]
    check("PubMed through NCBI's E-utilities: the title, the authors, the citation and the identifiers",
          eng == "api:pubmed" and "# A programmable dual-RNA-guided DNA endonuclease." in md
          and "Martin Jinek, The CRISPR Group" in md and "2012 Aug 17;337(6096):816-21." in md
          and "PMID: 22745249 · DOI: 10.1126/science.1225829 · PMCID: PMC6286148" in md, "%s %r" % (eng, md[:120]))
    check("PubMed: the abstract with its sections, the MeSH terms each whole",
          "**Background:** PM-BACKGROUND" in md and "**Results:** PM-RESULTS" in md
          and "MeSH terms: Bacterial Proteins; Vaccines, Synthetic" in md
          and json.loads(raw).get("pmid") == "22745249", repr(md[-330:]))
    check("NCBI learns only the record's number",
          pm == ["/pm/efetch.fcgi?db=pubmed&id=22745249&retmode=xml&tool=read-page"], str(pm))
    check("a PubMed address that is no record (a search, a record NCBI does not have) is read the ordinary way",
          sa.which("https://pubmed.ncbi.nlm.nih.gov/?term=crispr") is None
          and sa.read("https://pubmed.ncbi.nlm.nih.gov/999/", 10) is None, "")
    # a book's record (StatPearls, GeneReviews: 40 288 of them) was `blocked`, the cookie wall
    md, eng, raw = sa.read("https://pubmed.ncbi.nlm.nih.gov/20301331/", 10) or ("", "", "")
    check("PubMed: a book's record - the chapter, its authors, the book and its editors, the abstract",
          eng == "api:pubmed" and "# Achondroplasia" in md and "Janet M Legare" in md
          and "In: GeneReviews®, edited by Margaret P Adam. Seattle (WA): University of Washington, Seattle; 1993-2026."
          in md and "PMID: 20301331 · Bookshelf ID: NBK1152" in md
          and "**Clinical characteristics:** PM-BOOK-ABSTRACT" in md and "Sections: Summary; Diagnosis" in md
          and json.loads(raw).get("book") == "GeneReviews®", "%s %r" % (eng, md[:300]))
    # the old address, which NCBI redirects to the record's page (and its wall)
    Api.log.clear()
    md, eng, raw = sa.read("https://www.ncbi.nlm.nih.gov/pubmed/22745249", 10) or ("", "", "")
    check("PubMed's old address (www.ncbi.nlm.nih.gov/pubmed/ID) goes to the API too",
          eng == "api:pubmed" and "# A programmable dual-RNA-guided DNA endonuclease." in md
          and sa.which("http://ncbi.nlm.nih.gov/pubmed/22745249/?report=abstract")[0] == "pubmed", "%s" % eng)
    # a search for one record's number was `blocked`, the old mobile address read as PubMed's home
    # page (NCBI sends it there) - 2026-11-21
    forms = ("https://pubmed.ncbi.nlm.nih.gov/?term=22745249", "https://www.ncbi.nlm.nih.gov/pubmed/?term=22745249",
             "https://www.ncbi.nlm.nih.gov/pubmed/?cmd=search&term=22745249", "https://www.ncbi.nlm.nih.gov/m/pubmed/22745249/")
    hits = [sa.which(u) for u in forms]
    got = sa.read(forms[0], 10) or ("", "", "")
    check("PubMed: a search for one record's number and the old mobile address go to the API too; a search for more does not",
          all(h and h[0] == "pubmed" and h[1].group(1) == "22745249" for h in hits) and got[1] == "api:pubmed"
          and sa.which("https://pubmed.ncbi.nlm.nih.gov/?term=22745249+cas9") is None
          and sa.which("https://pubmed.ncbi.nlm.nih.gov/?term=cas9") is None,
          "%s %s" % ([h and h[0] for h in hits], got[1]))
    md, eng, raw = sa.read("https://pubmed.ncbi.nlm.nih.gov/40225927/", 10) or ("", "", "")
    check("PubMed: an exponent stays one (10^-16, not 10-16), a subscript reads as it is, a gzipped answer unpacks",
          "P = 2.2 × 10^-16 with autophagy^1 and CO2." in md, repr(md[md.find("PM-SUP"):][:120]))
    import random
    import string
    rnd = random.Random(1)
    letters = "".join(rnd.choice(string.ascii_letters) for _ in range(20000))
    big = gzip.compress(letters.encode("ascii"))

    class _Gz:
        headers = {"Content-Encoding": "gzip"}

        def __init__(self, body):
            self.body = body

        def read(self, n=-1):
            return self.body[:n] if n >= 0 else self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    keep = sa.urllib.request.urlopen
    sa.urllib.request.urlopen = lambda req, timeout=0: _Gz(big)
    try:
        got = sa.get_text("http://x/", time.time() + 5, limit=1000)
    except Exception as e:                                     # noqa: BLE001
        got = "%s: %s" % (type(e).__name__, e)
    finally:
        sa.urllib.request.urlopen = keep
    check("the API's size cap counts the unpacked text: a gzipped answer cut at the cap unpacks as far as it goes",
          len(big) > 1001 and got == letters[:1000], "%d bytes gzipped: %r" % (len(big), got[:80]))

    # ------------------------------------------------ inside a read
    Api.log.clear()
    m, text = inproc(mod, ["https://stackoverflow.com/questions/11227809/why-is-processing"])
    check("a read of a Stack Overflow question is the API's answer, status ok",
          m.get("status") == "ok" and (m.get("content") or {}).get("engine") == "api:stackexchange"
          and "SE-ANSWER-ONE" in text and os.path.isfile(os.path.join(m.get("dir") or "", "raw.json")),
          "%s %s" % (m.get("status"), (m.get("content") or {}).get("engine")))
    local = site.url("/item")
    pat = re.compile(r"^" + re.escape(site.url("/item")) + r"\?id=(\d+)")
    sa.PATTERNS = (("hn", pat),) + tuple(sa.PATTERNS)
    Api.mode = {"hn": "500"}
    m, text = inproc(mod, [local + "?id=1"])
    tried = (m.get("chain") or {}).get("tried") or []
    check("the API failed: the ordinary path reads the page, the chain says so",
          m.get("status") == "ok" and "LOCAL-PAGE-TEXT" in text and any("api:hn" in str(t) for t in tried),
          "%s %s" % (m.get("status"), tried))
    Api.mode = {"hn": "stall"}
    mod.SITE_API_SECONDS = 2
    t0 = time.monotonic()
    m, text = inproc(mod, [local + "?id=2"])
    dt = time.monotonic() - t0
    check("a stalled API costs its bound, then the page is read", "LOCAL-PAGE-TEXT" in text and dt < 9,
          "%.1f s %s" % (dt, m.get("status")))
    Api.mode, Api.log[:] = {}, []
    m, text = inproc(mod, [local + "?id=8863", "--alternate"])
    check("--alternate reads the page itself, not the API",
          not any(e["service"] == "hn" for e in Api.log) and "LOCAL-PAGE-TEXT" in text,
          str((m.get("chain") or {}).get("tried")))
finally:
    api.shutdown()
    site.close()

sys.exit(check.done())
