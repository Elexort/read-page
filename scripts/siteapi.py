"""A site's own data for the pages where the ordinary path fails.

    import siteapi; got = siteapi.read(url, seconds=10)   # (markdown, engine, raw_json) or None

Only where the general path fails in measurements: Stack Exchange and npm answer a reader with a
wall, Hacker News' item page lacks the comments' text, X is a JavaScript shell, PubMed answers a
client that did not run its script with a cookie wall. PyPI, GitHub, arXiv and Wikipedia read
fine the ordinary way. The APIs belong to the sites themselves (NCBI's E-utilities for PubMed);
fxtwitter is a third party but only learns the number of a public post. No key, no flag; any
failure returns None and the ordinary path reads the page. JSON and XML become Markdown here.
Standard library only.
"""
import gzip
import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import zlib

UA = "read-page/0.5 (agent skill)"
SE_SITES = {"stackoverflow.com": "stackoverflow", "superuser.com": "superuser", "serverfault.com": "serverfault",
            "askubuntu.com": "askubuntu", "mathoverflow.net": "mathoverflow.net"}
PATTERNS = (
    ("stackexchange", re.compile(r"^https?://(?:www\.)?((?:[\w-]+\.)?stackexchange\.com|stackoverflow\.com|"
                                 r"superuser\.com|serverfault\.com|askubuntu\.com|mathoverflow\.net)"
                                 r"/(?:questions|q)/(\d+)", re.I)),
    ("npm", re.compile(r"^https?://(?:www\.)?npmjs\.com/package/((?:@[^/?#]+/)?[^/?#]+)(?:/v/([^/?#]+))?", re.I)),
    ("hn", re.compile(r"^https?://news\.ycombinator\.com/item\?(?:[^#]*&)?id=(\d+)", re.I)),
    ("x", re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([^/?#]+)/status(?:es)?/(\d+)", re.I)),
    # the record's page, its old address that NCBI redirects to it (still in many references), the
    # old mobile one (NCBI sends it to PubMed's home page) and a search for one record's number -
    # those three were `blocked` or the home page (2026-11-21)
    ("pubmed", re.compile(r"^https?://(?:(?:www\.)?pubmed\.ncbi\.nlm\.nih\.gov|(?:www\.)?ncbi\.nlm\.nih\.gov/(?:m/)?pubmed)"
                          r"/(\d+)/?(?:[?#].*)?$", re.I)),
    ("pubmed", re.compile(r"^https?://(?:(?:www\.)?pubmed\.ncbi\.nlm\.nih\.gov|(?:www\.)?ncbi\.nlm\.nih\.gov/(?:m/)?pubmed)"
                          r"/?\?(?:[^#]*&)?term=(\d+)(?:&[^#]*)?(?:#.*)?$", re.I)),
)
SE_API = "https://api.stackexchange.com/2.3"
NPM_API = "https://registry.npmjs.org"
HN_API = "https://hacker-news.firebaseio.com/v0"
FX_API = "https://api.fxtwitter.com"
PM_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HN_COMMENTS = 30
PM_AUTHORS = 40


def which(url):
    """The adapter for this address, or None."""
    for name, rx in PATTERNS:
        m = rx.search(url or "")
        if m:
            return name, m
    return None


def read(url, seconds=10):
    """(markdown, engine, raw_json) from the site's API, or None when there is no adapter for the
    address or it failed in `seconds` - then the ordinary path reads the page."""
    hit = which(url)
    if not hit:
        return None
    name, m = hit
    box = {}

    def run():
        try:
            box["v"] = ADAPTERS[name](m, time.time() + seconds)
        except Exception as e:                                 # noqa: BLE001
            box["e"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    got = box.get("v")
    if t.is_alive() or not got or not (got[0] or "").strip():
        return None
    return got[0], "api:" + name, got[1]


def get_json(url, deadline, headers=None):
    left = max(1.0, deadline - time.time())
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA, "Accept": "application/json",
                                                    "Accept-Encoding": "gzip"}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=left) as r:
        body = r.read()
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            body = gzip.decompress(body)
    return json.loads(body.decode("utf-8", "replace")), body.decode("utf-8", "replace")


def md(fragment):
    """An HTML fragment (a post, a comment) as Markdown: html2text when installed, else a strip."""
    try:
        import html2text
        h = html2text.HTML2Text()
        h.body_width = 0
        return h.handle(fragment or "").strip()
    except Exception:                                          # noqa: BLE001
        t = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</pre>", "\n", fragment or "")
        t = re.sub(r"(?i)<li[^>]*>", "- ", t)
        t = re.sub(r"<[^>]+>", "", t)
        return html.unescape(re.sub(r"\n{3,}", "\n\n", t)).strip()


def day(ts):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))
    except (TypeError, ValueError):
        return ""


def stackexchange(m, deadline):
    host, qid = m.group(1).lower(), m.group(2)
    site = SE_SITES.get(host) or host.split(".")[0]
    q, raw_q = get_json("%s/questions/%s?site=%s&filter=withbody" % (SE_API, qid, site), deadline)
    items = q.get("items") or []
    if not items:
        return None
    it = items[0]
    a, raw_a = get_json("%s/questions/%s/answers?site=%s&filter=withbody&sort=votes&order=desc&pagesize=10"
                        % (SE_API, qid, site), deadline)
    out = ["# " + html.unescape(it.get("title") or ""), "",
           "%s votes · %s answers · asked %s by %s · tags: %s" % (
               it.get("score", 0), it.get("answer_count", 0), day(it.get("creation_date")),
               html.unescape((it.get("owner") or {}).get("display_name") or "?"), ", ".join(it.get("tags") or [])),
           "", md(it.get("body")), ""]
    for ans in sorted(a.get("items") or [], key=lambda x: -(x.get("score") or 0)):    # the page's own order
        out += ["## Answer by %s · %s votes%s" % (html.unescape((ans.get("owner") or {}).get("display_name") or "?"),
                                                  ans.get("score", 0), " · accepted" if ans.get("is_accepted") else ""),
                "", md(ans.get("body")), ""]
    out.append("Source: %s" % (it.get("link") or ""))
    return "\n".join(out), json.dumps({"question": json.loads(raw_q), "answers": json.loads(raw_a)}, ensure_ascii=False)


def npm(m, deadline):
    """The version's own document (2-4 KB) and the README from its tarball, which is what
    npmjs.com shows. The whole registry document is 7-15 MB for react or typescript and has no
    README at all for them."""
    name = urllib.parse.unquote(m.group(1))
    tag = urllib.parse.unquote(m.group(2) or "latest")
    d, raw = get_json("%s/%s/%s" % (NPM_API, urllib.parse.quote(name, safe="@"), urllib.parse.quote(tag)), deadline)
    if not d.get("name"):
        return None
    repo = d.get("repository") or {}
    repo = repo.get("url") if isinstance(repo, dict) else repo
    lic = d.get("license")
    lic = lic.get("type") if isinstance(lic, dict) else lic
    facts = [x for x in ("version %s" % d.get("version") if d.get("version") else "",
                         "license %s" % lic if lic else "", d.get("homepage") or "",
                         re.sub(r"^git\+|\.git$", "", str(repo or ""))) if x]
    readme = d.get("readme") or ""
    if not readme.strip() and (d.get("dist") or {}).get("tarball"):
        readme = tar_readme(d["dist"]["tarball"], deadline)
    out = ["# " + d["name"], "", d.get("description") or "", "", " · ".join(facts), "", readme]
    return "\n".join(out).strip(), raw


README = re.compile(r"^[^/]+/readme(\.(md|markdown|txt|rst))?$", re.I)


def tar_readme(url, deadline, limit=1024 * 1024):
    """README of a package tarball, read as a stream that stops at it: a few KB of a 4 MB
    typescript tarball. Only from the registry's own host."""
    if urllib.parse.urlparse(url).hostname != urllib.parse.urlparse(NPM_API).hostname:
        return ""
    import tarfile
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=max(1.0, deadline - time.time())) as r:
        with tarfile.open(fileobj=r, mode="r|gz") as tf:
            for member in tf:
                if time.time() > deadline:
                    return ""
                if member.isfile() and README.match(member.name) and member.size <= limit:
                    return tf.extractfile(member).read().decode("utf-8", "replace")
    return ""


def hn(m, deadline):
    item, raw = get_json("%s/item/%s.json" % (HN_API, m.group(1)), deadline)
    if not item:
        return None
    out = []
    if item.get("title"):
        out += ["# " + html.unescape(item["title"]), ""]
    if item.get("url"):
        out += [item["url"], ""]
    out += ["%s points by %s · %s · %s comments" % (item.get("score", 0), item.get("by", "?"), day(item.get("time")),
                                                  item.get("descendants", len(item.get("kids") or []))), ""]
    if item.get("text"):
        out += [md(item["text"]), ""]
    kids = (item.get("kids") or [])[:HN_COMMENTS]
    got = {}

    def one(k):
        try:
            got[k] = get_json("%s/item/%s.json" % (HN_API, k), deadline)[0]
        except Exception:                                      # noqa: BLE001
            pass

    threads = [threading.Thread(target=one, args=(k,), daemon=True) for k in kids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.1, deadline - time.time() - 0.5))
    shown = [got[k] for k in kids if got.get(k) and not got[k].get("deleted") and not got[k].get("dead")]
    if shown:
        out += ["## Comments", ""]
        for c in shown:
            out += ["**%s** · %s" % (c.get("by", "?"), day(c.get("time"))), "", md(c.get("text")), ""]
        rest = int(item.get("descendants") or 0) - len(shown)
        if rest > 0:
            out.append("%d more comments and replies are on the page." % rest)
    return "\n".join(out).strip(), raw


def x_post(m, deadline):
    # only the post number leaves: not the account in the address, not its query
    d, raw = get_json("%s/status/%s" % (FX_API, m.group(2)), deadline)
    tw = d.get("tweet") or {}
    if not tw.get("text") and not tw.get("media"):
        return None
    au = tw.get("author") or {}
    out = ["**%s** (@%s) · %s" % (au.get("name") or "?", au.get("screen_name") or m.group(1), tw.get("created_at") or ""),
           "", tw.get("text") or "", ""]
    for p in ((tw.get("media") or {}).get("photos") or []):
        if p.get("url"):
            out.append("![photo](%s)" % p["url"])
    quote = tw.get("quote") or {}
    if quote.get("text"):
        out += ["", "> **@%s**: %s" % ((quote.get("author") or {}).get("screen_name") or "?", quote["text"])]
    out += ["", "%s likes · %s reposts · %s replies" % (tw.get("likes", 0), tw.get("retweets", 0), tw.get("replies", 0))]
    return "\n".join(out).strip(), raw


def get_text(url, deadline, accept="*/*", limit=4 * 1024 * 1024):
    """The answer as text, `limit` bytes at most - of the text itself, also when it came gzipped
    (a capped stream unpacks as far as it goes; a small one cannot unpack past the cap)."""
    left = max(1.0, deadline - time.time())
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=left) as r:
        body = r.read(limit + 1)
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            body = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(body, limit + 1)
    return body[:limit].decode("utf-8", "replace")


def _flat(el):
    parts = [el.text or ""]
    for ch in el:
        inner = _flat(ch)
        tag = ch.tag.lower() if isinstance(ch.tag, str) else ""
        # an exponent keeps its mark (10^-16, not 10-16); a superscript sign does not (GeneReviews®)
        parts.append("^" + inner.strip() if tag == "sup" and any(c.isalnum() for c in inner) else inner)
        parts.append(ch.tail or "")
    return "".join(parts)


def _xt(el):
    """An XML element's text with its inline markup's (<i>, <sub>, <sup>) text, spaces folded."""
    return re.sub(r"\s+", " ", _flat(el)).strip() if el is not None else ""


def _names(el):
    out = []
    for au in el.findall("Author") if el is not None else []:
        name = _xt(au.find("CollectiveName")) or " ".join(
            x for x in (_xt(au.find("ForeName")) or _xt(au.find("Initials")), _xt(au.find("LastName"))) if x)
        if name:
            out.append(name)
    return out


def _date(pd):
    if pd is None:
        return ""
    return (" ".join(x for x in (_xt(pd.find("Year")), _xt(pd.find("Month")), _xt(pd.find("Day"))) if x)
            or _xt(pd.find("MedlineDate")))


def _abstract(el):
    return [(lb, tx) for lb, tx in (((t.get("Label") or "").strip(), _xt(t))
                                    for t in (el.findall("Abstract/AbstractText") if el is not None else [])) if tx]


def _abstract_md(abstract):
    if not abstract:
        return ["The record has no abstract.", ""]
    out = ["## Abstract", ""]
    for label, text in abstract:
        out += [("**%s:** " % label.capitalize() if label else "") + text, ""]
    return out


def pubmed(m, deadline):
    """A PubMed record from NCBI's own E-utilities. The page answers a client that did not run
    its script with "Cookies must be enabled" (HTTP 203, 2026-11-20) and a headless browser with
    403; the record has what the page shows: the citation, the authors, the abstract with its
    section labels, the identifiers, the MeSH terms and keywords. A book's record (a chapter of
    StatPearls or GeneReviews: 40 288 of them, 2026-11-20) comes from the same call. Only the
    record's number leaves."""
    import xml.etree.ElementTree as ET
    pmid = m.group(1)
    raw = get_text("%s/efetch.fcgi?db=pubmed&id=%s&retmode=xml&tool=read-page" % (PM_API, pmid), deadline,
                   "application/xml")
    root = ET.fromstring(raw.encode("utf-8"))
    art = root.find(".//PubmedArticle")
    if art is None:
        book = root.find(".//PubmedBookArticle")
        return pubmed_book(pmid, book) if book is not None else None
    a = art.find("MedlineCitation/Article")
    title = _xt(a.find("ArticleTitle")) if a is not None else ""
    if not title:
        return None                        # no record: the ordinary path answers
    authors = _names(a.find("AuthorList"))
    journal = _xt(a.find("Journal/Title")) or _xt(a.find("Journal/ISOAbbreviation"))
    date = _date(a.find("Journal/JournalIssue/PubDate"))
    vol, issue = _xt(a.find("Journal/JournalIssue/Volume")), _xt(a.find("Journal/JournalIssue/Issue"))
    pages = _xt(a.find("Pagination/MedlinePgn"))
    ids = {i.get("IdType"): _xt(i) for i in art.findall("PubmedData/ArticleIdList/ArticleId")}
    doi = ids.get("doi") or next((_xt(e) for e in a.findall("ELocationID") if e.get("EIdType") == "doi"), "")
    abstract = _abstract(a)
    types = [x for x in (_xt(t) for t in a.findall("PublicationTypeList/PublicationType")) if x]
    mesh = [x for x in (_xt(h.find("DescriptorName"))
                        for h in art.findall("MedlineCitation/MeshHeadingList/MeshHeading")) if x]
    keywords = [x for x in (_xt(k) for k in art.findall("MedlineCitation/KeywordList/Keyword")) if x]
    cite = "%s. %s%s%s%s" % (journal, date, ";" + vol if vol else "", "(%s)" % issue if issue else "",
                             ":" + pages if pages else "")
    out = ["# " + title, ""]
    if authors:
        out += [", ".join(authors[:PM_AUTHORS])
                + (" and %d more" % (len(authors) - PM_AUTHORS) if len(authors) > PM_AUTHORS else ""), ""]
    out += [cite.strip(" .;") + ".", "",
            " · ".join(x for x in ("PMID: " + pmid, "DOI: " + doi if doi else "",
                                   "PMCID: " + ids["pmc"] if ids.get("pmc") else "") if x), ""]
    out += _abstract_md(abstract)
    for name, items in (("Publication types", types), ("MeSH terms", mesh), ("Keywords", keywords)):
        if items:
            out += ["%s: %s" % (name, "; ".join(items)), ""]      # a term may have a comma of its own
    if ids.get("pmc"):
        out += ["Free full text: https://pmc.ncbi.nlm.nih.gov/articles/%s/" % ids["pmc"], ""]
    out.append("Source: https://pubmed.ncbi.nlm.nih.gov/%s/ (the record, from NCBI's E-utilities)" % pmid)
    record = {"pmid": pmid, "title": title, "authors": authors, "journal": journal, "date": date, "volume": vol,
              "issue": issue, "pages": pages, "ids": ids, "abstract": [{"label": lb, "text": tx} for lb, tx in abstract],
              "publication_types": types, "mesh": mesh, "keywords": keywords}
    return "\n".join(out), json.dumps(record, ensure_ascii=False)


def pubmed_book(pmid, art):
    """A book's record (PubmedBookArticle): a chapter's title, its authors, the book, its
    editors and publisher, the abstract by section, the chapter's sections, the identifiers."""
    d = art.find("BookDocument")
    if d is None:
        return None
    book = d.find("Book")
    book_title = _xt(book.find("BookTitle")) if book is not None else ""
    title = _xt(d.find("ArticleTitle")) or book_title
    if not title:
        return None
    lists = d.findall("AuthorList")
    authors = _names(next((x for x in lists if (x.get("Type") or "authors") == "authors"), None))
    editors = _names(next((x for x in (book.findall("AuthorList") if book is not None else [])
                           if (x.get("Type") or "") == "editors"), None))
    date = _date(book.find("PubDate")) if book is not None else ""
    end = _xt(book.find("EndingDate/Year")) if book is not None else ""
    if end and date and not date.startswith(end):
        date = "%s-%s" % (date.split()[0], end)
    publisher = ": ".join(x for x in (_xt(book.find("Publisher/PublisherLocation")) if book is not None else "",
                                      _xt(book.find("Publisher/PublisherName")) if book is not None else "") if x)
    ids = {i.get("IdType"): _xt(i) for i in d.findall("ArticleIdList/ArticleId")}
    ids.update({i.get("IdType"): _xt(i) for i in art.findall("PubmedBookData/ArticleIdList/ArticleId")})
    abstract = _abstract(d)
    types = [x for x in (_xt(t) for t in d.findall("PublicationType")) if x]
    sections = [x for x in (_xt(s.find("SectionTitle")) for s in d.findall("Sections/Section")) if x]
    out = ["# " + title, ""]
    if authors:
        out += [", ".join(authors[:PM_AUTHORS])
                + (" and %d more" % (len(authors) - PM_AUTHORS) if len(authors) > PM_AUTHORS else ""), ""]
    where = "In: %s" % (book_title or "a book")
    if editors:
        where += ", edited by " + ", ".join(editors[:10]) + (" and %d more" % (len(editors) - 10)
                                                              if len(editors) > 10 else "")
    out += [(where + ". " + "; ".join(x for x in (publisher, date) if x)).strip(" .;") + ".", "",
            " · ".join(x for x in ("PMID: " + pmid, "Bookshelf ID: " + ids["bookaccession"]
                                   if ids.get("bookaccession") else "") if x), ""]
    out += _abstract_md(abstract)
    for name, items in (("Sections", sections), ("Publication types", types)):
        if items:
            out += ["%s: %s" % (name, "; ".join(items)), ""]
    if ids.get("bookaccession"):
        out += ["Full text (NCBI Bookshelf): https://www.ncbi.nlm.nih.gov/books/%s/" % ids["bookaccession"], ""]
    out.append("Source: https://pubmed.ncbi.nlm.nih.gov/%s/ (the record, from NCBI's E-utilities)" % pmid)
    record = {"pmid": pmid, "title": title, "authors": authors, "book": book_title, "editors": editors,
              "publisher": publisher, "date": date, "ids": ids,
              "abstract": [{"label": lb, "text": tx} for lb, tx in abstract], "sections": sections,
              "publication_types": types}
    return "\n".join(out), json.dumps(record, ensure_ascii=False)


ADAPTERS = {"stackexchange": stackexchange, "npm": npm, "hn": hn, "x": x_post, "pubmed": pubmed}
