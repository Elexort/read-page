"""The answer contract. No network.

    python -X utf8 tests/contract.py

One call answers with a header and the text, inside 9 980 bytes and 495 lines counted on what
is written (UTF-8, LF), stderr included. A text that fits comes whole; a longer one comes with an
outline and the exact line to go on from, and the blocks put together are the saved file.
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from harness import PUBLIC, Checks, run_read, serve     # noqa: E402

check = Checks()
BUDGET, LINES = 9980, 495


def page(title, body):
    return (200, {"Content-Type": "text/html; charset=utf-8"},
            ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title></head><body><article>"
             "%s</article></body></html>" % (title, body)).encode("utf-8"))


def sections(n, sentence, heading="Section"):
    return "".join("<h2>%s %d</h2><p>%s</p>" % (heading, i, " ".join(sentence % (i, j) for j in range(9)))
                   for i in range(1, n + 1))


EN = "Sentence %d.%d explains one more detail of the reader, so the paragraph grows long enough."
RU = "Предложение %d.%d описывает ещё одну подробность чтения, и абзац становится длинным."
ZH = "第%d节第%d句说明读者的又一个细节，所以段落变得足够长。"
ROUTES = {
    # long enough not to look like a script shell (that would start a browser), short enough to fit
    "/short": page("Short", "<h1>Short</h1>" + "".join(
        "<p>SHORT-MARKER paragraph %d of a short page: a few sentences of ordinary text that a reader "
        "keeps whole, because the answer has room for all of it.</p>" % i for i in range(6))),
    "/long": page("Long", sections(40, EN)),
    "/flat": page("Flat", "".join("<p>%s</p>" % " ".join(EN % (i, j) for j in range(9)) for i in range(40))),
    "/ru": page("Русский", sections(40, RU, "Раздел")),
    "/zh": page("中文", sections(40, ZH, "第")),
    "/oneline": page("One line", "<p>" + " ".join("Word number %d ends a sentence." % i for i in range(3000)) + "</p>"),
    "/nospace": page("No space", "".join("<p>Paragraph %d of a page that also holds one very long token.</p>" % i
                                         for i in range(6)) + "<p>" + "y" * 5000 + "</p>"),
    "/gone": (404, {"Content-Type": "text/html; charset=utf-8"},
              b"<html><body><h1>404</h1><p>No such page here.</p></body></html>"),
    # a book - one title over 70 chapters whose list does not fit the outline (Pride and
    # Prejudice's EPUB had only its title there, and its last page was 16 answers away)
    "/book": page("Book", "<h1>The Book</h1>" + sections(70, EN, "A chapter with a rather long title, as old books have, number")),
    "/plainlong": page("Plain long", "".join("<p>%s</p>" % " ".join(EN % (i, j) for j in range(9)) for i in range(400))),
    # a short article between two long menus: the text is a small share of the page's words, maybe a fragment
    "/fragment": (200, {"Content-Type": "text/html; charset=utf-8"},
                  ("<!doctype html><html><head><meta charset='utf-8'><title>Fragment</title></head><body><header><nav>"
                   "<ul>%s</ul></nav></header><article><h1>Fragment</h1><p>%s</p></article><footer><ul>%s</ul></footer>"
                   "</body></html>" % (
                       "".join("<li><a href='/p%d'>Section %d of the site menu and its sub pages</a></li>" % (i, i)
                               for i in range(150)),
                       " ".join(EN % (1, j) for j in range(8)),
                       "".join("<li><a href='/f%d'>Footer link %d of the site and its pages</a></li>" % (i, i)
                               for i in range(150)))).encode("utf-8")),
}
class Versioned:
    """A page with an ETag: a matching If-None-Match gets a 304; `version` changes the page."""

    def __init__(self):
        self.version, self.asked = 1, []

    def __call__(self, h):
        tag = '"v%d"' % self.version
        sent = h.headers.get("If-None-Match", "")
        self.asked.append(sent)
        if sent == tag:
            h.send_response(304)
            h.send_header("ETag", tag)
            h.send_header("Connection", "close")
            h.end_headers()
            h.close_connection = True
            return
        _, headers, body = page("Versioned", "<h1>Versioned</h1>" + "".join(
            "<p>VERSION-%d paragraph %d: a few sentences of ordinary text, enough to be read as a page "
            "and not as a script shell.</p>" % (self.version, i) for i in range(6)))
        h.send_response(200)
        for k, v in dict(headers, ETag=tag).items():
            h.send_header(k, v)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(body)
        h.close_connection = True


VERSIONED = Versioned()
ROUTES["/v"] = VERSIONED
srv = serve(ROUTES)


def first_line(r):
    return r.text.split("\n")[0]


def fits(name, r):
    n = r.out.count(b"\n")
    check(name + ": within 9 980 bytes and 495 lines", len(r.out) <= BUDGET and n <= LINES,
          "%d bytes, %d lines" % (len(r.out), n))
    check(name + ": LF only, stderr empty, exit 0", b"\r" not in r.out and r.err == b"" and r.rc == 0,
          "rc=%d stderr=%r" % (r.rc, r.err[:80]))


def body(text):
    """The text lines of one answer: after the `── file: ...` separator, before the pointer."""
    lines = text.split("\n")
    i = next((k for k, ln in enumerate(lines) if ln.startswith("── ") and (": lines " in ln or ": all " in ln)), None)
    if i is None:
        return []
    rest = lines[i + 1:]
    if rest and rest[-1] == "":
        rest.pop()
    if rest and rest[-1].startswith("── next: "):
        rest.pop()
    return rest


def next_line(text):
    m = re.search(r"── next: line (\d+) of \d+", text)
    return int(m.group(1)) if m else None


def lines_of(r, name="content.md"):
    rows = r.file(name).split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    return rows


try:
    # a short page comes whole
    r = run_read(srv.url("/short"))
    fits("short", r)
    check("short: the whole text, no outline, no pointer",
          ": all " in r.text and "outline" not in r.text and next_line(r.text) is None
          and body(r.text) == lines_of(r), r.text.split("\n")[0][:80])
    check("short: the header names status, engine and the files",
          r.text.startswith("read-page · ok · ") and "files: " + r.dir in r.text, r.text.split("\n")[0][:80])
    # an agent read "49% of the page" on a whole text as "I got half the content" and kept re-reading
    # (KNOWN-ISSUES 255): a whole text's first line names no share; the manifest keeps it
    check("short: a whole text's first line names no share of the page, the manifest keeps it",
          not re.search(r"\d+%", first_line(r)) and "fragment" not in first_line(r)
          and isinstance((r.manifest.get("content") or {}).get("cover"), (int, float)), first_line(r)[:90])

    # a suspected fragment: the share beside the words, and the answer shows page.md
    r = run_read(srv.url("/fragment"))
    fits("fragment", r)
    frag_line = (r"^read-page · ok · [^·]+ · maybe a fragment: the text is \d+% of the page's words · "
                 r"page\.md [\d.]+ [KMG]?B, \d+ lines · ")
    check("a suspected fragment: the first line says so with the share beside it, and shows page.md",
          re.search(frag_line, first_line(r)) is not None and " · fragment · " not in first_line(r),
          first_line(r)[:120])
    cover = (r.manifest.get("content") or {}).get("cover")
    check("... the manifest keeps the share (content.cover) and signals.fragment",
          isinstance(cover, (int, float)) and cover < 0.35 and (r.manifest.get("signals") or {}).get("fragment") is True
          and ("is %d%% of" % int(round(cover * 100))) in first_line(r), "%s %s" % (cover, first_line(r)[:60]))
    check("... the advice says the same measure: the share of the page's words, and that page.md is shown",
          "of the page's words" in (r.manifest.get("advice") or "") and "page.md" in (r.manifest.get("advice") or ""),
          (r.manifest.get("advice") or "")[:120])

    # long pages: an outline, blocks inside the budget, and the blocks put together are the file
    for path in ("/long", "/flat", "/ru", "/zh"):
        first = run_read(srv.url(path))
        fits(path, first)
        check(path + ": an outline and the next line", "outline (line, heading):" in first.text
              and next_line(first.text) is not None, "")
        check(path + ": the pointer names the file it continues", "--file content.md ──" in first.text,
              (re.findall(r"── next: .*", first.text) or ["no pointer"])[0][:90])
        saved = lines_of(first)
        got, n, hops, over = body(first.text), next_line(first.text), 0, []
        while n and hops < 60:
            more = run_read(srv.url(path), "--from", str(n), reuse=first)
            if len(more.out) > BUDGET or more.out.count(b"\n") > LINES or more.err or more.rc:
                over.append((n, len(more.out), more.rc))
            check_start = body(more.text)[:1] == saved[n - 1:n]
            if not check_start:
                over.append((n, "starts elsewhere"))
            got += body(more.text)
            n, hops = next_line(more.text), hops + 1
        check(path + ": every block fits and starts at its line", not over, str(over[:3]))
        check(path + ": the blocks put together are content.md", got == saved,
              "%d of %d lines, %d answers" % (len(got), len(saved), hops + 1))

    # the outline points at real headings
    first = run_read(srv.url("/long"))
    saved = lines_of(first)
    rows = re.findall(r"^\s*(\d+) (#+) (.*)$", first.text, re.M)
    check("outline: every row is the heading on that line",
          rows and all(saved[int(n) - 1].lstrip("# ").startswith(t[:30]) for n, _, t in rows),
          "%d rows" % len(rows))

    # an outline too long for its room is thinned evenly and reaches the end of the text
    book = run_read(srv.url("/book"))
    fits("/book", book)
    saved = lines_of(book)
    rows = re.findall(r"^\s*(\d+) (#+) (.*)$", book.text, re.M)
    last = max((int(n) for n, _, _ in rows), default=0)
    check("a book's outline lists its chapters, thinned, to the last ones, not just its title",
          len(rows) >= 12 and last >= 0.85 * len(saved)
          and all(saved[int(n) - 1].lstrip("# ").startswith(t[:30]) for n, _, t in rows)
          and "more between these" in book.text,
          "%d rows, last at line %d of %d" % (len(rows), last, len(saved)))
    flat = run_read(srv.url("/plainlong"))
    fits("/plainlong", flat)
    saved = lines_of(flat)
    starts =[int(n) for n in re.findall(r"^\s*(\d+) \S", flat.text.split("── content.md")[0], re.M)]
    check("a long text without headings has block rows to its end",
          len(starts) >= 12 and max(starts) >= 0.85 * len(saved),
          "%d rows, last at line %s of %d" % (len(starts), max(starts) if starts else None, len(saved)))

    # a continuation needs no network: the server is gone, the saved copy answers
    lone = serve({"/long": ROUTES["/long"]})
    first = run_read(lone.url("/long"))
    lone.close()
    n = next_line(first.text)
    more = run_read(lone.url("/long"), "--from", str(n), reuse=first)
    check("--from reads the saved copy, no network", more.rc == 0 and body(more.text)[:1] == lines_of(first)[n - 1:n],
          more.text.split("\n")[0][:80])
    check("--from leaves the copy's age alone (15 minutes count from the read)",
          first.manifest.get("_cached_at") and more.manifest.get("_cached_at") == first.manifest.get("_cached_at"),
          "%s -> %s" % (first.manifest.get("_cached_at"), more.manifest.get("_cached_at")))
    past = run_read(lone.url("/long"), "--from", "99999", reuse=first)
    check("--from past the last line says so", past.rc == 0 and "past the end" in past.text
          and next_line(past.text) is None, past.text.split("\n")[-2][:80])
    check("a continuation from the saved copy has no re-read note", "\nnote: " not in more.text, "")

    # the other file goes on in the other file: the pointer carries --file page.md
    whole = run_read(srv.url("/long"), "--file", "page.md")
    n = next_line(whole.text)
    on = run_read(srv.url("/long"), "--from", str(n or 1), "--file", "page.md", reuse=whole)
    check("--file page.md: the pointer says page.md and the next block is page.md's",
          "--file page.md ──" in whole.text and body(on.text)[:1] == lines_of(whole, "page.md")[(n or 1) - 1:(n or 1)],
          first_line(on)[:80])

    # a forgotten --file goes on in the file read last; --file switches it
    on = run_read(srv.url("/long"), "--from", str(n or 1), reuse=whole)
    check("--from without --file goes on in page.md when page.md was read last",
          "── page.md: lines %d-" % (n or 1) in on.text
          and body(on.text)[:1] == lines_of(whole, "page.md")[(n or 1) - 1:(n or 1)], first_line(on)[:80])
    plain = run_read(srv.url("/long"))
    k = next_line(plain.text)
    run_read(srv.url("/long"), "--from", "1", "--file", "page.md", reuse=plain)     # switch to the other file
    stay = run_read(srv.url("/long"), "--from", str(k), reuse=plain)
    check("--file switches the file: a later --from without --file stays in page.md",
          "── page.md: lines %d-" % k in stay.text and body(stay.text)[:1] == lines_of(plain, "page.md")[k - 1:k],
          first_line(stay)[:80])
    back = run_read(srv.url("/long"), "--from", str(k), "--file", "content.md", reuse=plain)
    check("the first pointer, which names content.md, still leads back to content.md",
          "── content.md: lines %d-" % k in back.text and body(back.text)[:1] == lines_of(plain)[k - 1:k],
          first_line(back)[:80])
    anew = run_read(srv.url("/long"), reuse=plain)
    check("a new reading (no --from) starts at content.md again", "── content.md: lines 1-" in anew.text,
          first_line(anew)[:80])

    # no saved copy (or --refresh): the page is read again and the answer says so
    fresh = run_read(srv.url("/long"), "--from", "40")
    check("--from with no saved copy reads the page and says the lines may have moved",
          fresh.rc == 0 and "\nnote: the page was read again" in fresh.text, first_line(fresh)[:80])

    # the 15 minutes: counted from the read or a 304, never from showing a copy (no --dir, as an agent runs it)
    def stamp(r):
        return (r.manifest or {}).get("_cached_at") or 0

    a = run_read(srv.url("/v"), own_dir=False)
    b = run_read(srv.url("/v"), own_dir=False, reuse=a)
    check("a repeat within 15 minutes is the saved copy and keeps its age",
          "from cache" in first_line(b) and stamp(b) == stamp(a) > 0, "%s -> %s" % (stamp(a), stamp(b)))
    c = run_read(srv.url("/v"), "--from", "2", own_dir=False, reuse=a)
    check("a --from block keeps the age too", stamp(c) == stamp(a), "%s -> %s" % (stamp(a), stamp(c)))
    d = run_read(srv.url("/v"), "--refresh", own_dir=False, reuse=a)
    check("--refresh, page unchanged: a 304 and the 15 minutes start again",
          "from cache, revalidated" in first_line(d) and stamp(d) > stamp(a) and VERSIONED.asked[-1] == '"v1"',
          "%s; asked with %r" % (first_line(d)[:60], VERSIONED.asked[-1]))
    VERSIONED.version = 2
    e = run_read(srv.url("/v"), "--refresh", own_dir=False, reuse=a)
    check("--refresh, page changed: read again, the new text, a new age",
          "VERSION-2" in e.file("content.md") and "from cache" not in first_line(e) and stamp(e) > stamp(d),
          first_line(e)[:60])
    with open(os.path.join(e.dir, "manifest.json"), encoding="utf-8") as fh:
        m = json.load(fh)
    m["_cached_at"] -= 901
    with open(os.path.join(e.dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(m, fh)
    asked = len(VERSIONED.asked)
    f = run_read(srv.url("/v"), own_dir=False, reuse=a)
    check("older than 15 minutes: the page is read again", len(VERSIONED.asked) > asked
          and "from cache" not in first_line(f) and stamp(f) > stamp(e), first_line(f)[:60])

    # the other view, the manifest, and the exit codes
    r = run_read(srv.url("/short"), "--file", "page.md")
    check("--file page.md prints page.md", "· page.md " in r.text.split("\n")[0] and body(r.text) == lines_of(r, "page.md"),
          r.text.split("\n")[0][:80])
    r = run_read(srv.url("/short"), "--json")
    try:
        status = json.loads(r.out).get("status")
    except ValueError:
        status = None
    check("--json prints the manifest", status == "ok" and r.rc == 0, str(status))
    r = run_read(srv.url("/gone"))
    check("a missing page is an answer: exit 0", r.rc == 0 and r.text.startswith("read-page · not_found"),
          "rc=%d %s" % (r.rc, r.text.split("\n")[0][:60]))
    check("any status but ok names its rule on a reason: line", "\nreason: HTTP 404" in r.text,
          next((ln for ln in r.text.split("\n") if ln.startswith("reason:")), "no reason line"))
    # a flag that is not ours, or a value that cannot be used, does not stop the read (a model
    # invented --to 407 and lost the call): the page is read and the header names what was left out
    for flags, said in ((["--print"], "--print"), (["--public"], "--public"), (["--external"], "--external"),
                        (["--allow-images"], "--allow-images (no such flag)"),
                        (["--from", "-1"], "--from -1"), (["--file", "notes.md"], "--file notes.md"),
                        (["--to", "407"], "--to 407 (no such flag")):
        r = run_read(srv.url("/short"), *flags)
        ign = next((ln for ln in r.text.split("\n") if ln.startswith("ignored: ")), "")
        check("not ours, %s: the page is read, the header names it, exit 0" % " ".join(flags),
              r.rc == 0 and r.text.startswith("read-page · ok") and said in ign, "rc=%d %r" % (r.rc, ign[:90]))
    # a misspelled flag is the one meant, silently: --fil page.md prints page.md, --form 2 goes on
    r = run_read(srv.url("/short"), "--fil", "page.md", "--form", "2")
    check("a typo of a flag does what the flag does, with no note",
          r.rc == 0 and "── page.md: lines 2-" in r.text and "ignored:" not in r.text, first_line(r)[:90])
    r = run_read("--to", "5", srv.url("/short"))           # the stray flag first, its value taken for the URL
    check("a stray flag before the URL: the URL is still the one read",
          r.rc == 0 and r.text.startswith("read-page · ok") and "ignored: --to 5" in r.text, first_line(r)[:90])
    r = run_read(srv.url("/short"), "--json", "--to", "3")
    try:
        ignored = json.loads(r.text).get("ignored")
    except ValueError:
        ignored = None
    check("--json names the left-out flags too; the saved manifest does not keep them",
          ignored == ["--to 3 (no such flag: an answer prints what fits and names the next line, --from N)"]
          and "ignored" not in json.loads(open(os.path.join(r.dir, "manifest.json"), encoding="utf-8").read()),
          str(ignored)[:120])
    r = run_read("ftp://example.com/file.txt")
    check("not an http(s) URL: exit 2 and the reason on stderr", r.rc == 2 and b"http(s)" in r.err, r.err[:80])
    blocker = tempfile.NamedTemporaryFile(delete=False)
    blocker.close()
    r = run_read(srv.url("/short"), "--dir", blocker.name)      # a file where the folder should be
    check("a crash is exit 1 with the reason on stdout", r.rc == 1 and r.text.startswith("read-page · error · internal error"),
          "rc=%d %s" % (r.rc, r.text[:80]))
    os.unlink(blocker.name)

    # no line longer than a reader shows (2 000 with "\r\n"), and nothing lost on the way
    r = run_read(srv.url("/oneline"))
    rows = lines_of(r)
    longest = max(len(x) for x in rows)
    check("one 90 000-character paragraph: lines of 1 998 or less", longest <= 1998, "longest %d" % longest)
    check("one long paragraph: every word kept, every piece ends a sentence",
          " ".join(rows).split() == " ".join("Word number %d ends a sentence." % i for i in range(3000)).split()
          and all(x.endswith(".") for x in rows if x.startswith("Word number")), "")
    fits("oneline", r)
    r = run_read(srv.url("/nospace"))
    rows = lines_of(r)
    check("a 5 000-character token: cut at exactly 1 998, nothing lost",
          "y" * 5000 in "".join(rows) and max(len(x) for x in rows) <= 1998
          and [len(x) for x in rows if set(x) == {"y"}] == [1998, 1998, 1004],
          str([len(x) for x in rows if set(x) == {"y"}]))

    import answer                                              # noqa: E402
    zh = "这是一个没有空格的很长的句子，用来检查切分。" * 200
    out = answer.split_long_lines(zh).split("\n")
    check("Chinese with no spaces: cut after 。, nothing lost",
          len(out) > 1 and all(len(x) <= 1998 for x in out) and all(x.endswith("。") for x in out) and "".join(out) == zh,
          str([len(x) for x in out]))
    words = " ".join("word%d" % i for i in range(1000))
    out = answer.split_long_lines(words).split("\n")
    check("no sentence end: cut at a space, every word kept",
          len(out) > 1 and all(len(x) <= 1998 for x in out) and " ".join(out) == words, str([len(x) for x in out]))
    row = "| " + " | ".join("cell %d holds some words" % i for i in range(200)) + " |"
    out = answer.split_long_lines(row).split("\n")
    check("a table row longer than 1 998 is cut too, nothing lost",
          len(out) > 1 and all(len(x) <= 1998 for x in out) and " ".join(out) == row, str([len(x) for x in out]))
    smile = "😀" * 3000
    out = answer.split_long_lines(smile).split("\n")
    check("four-byte characters: at most 6 000 bytes a line, nothing lost",
          all(len(x.encode("utf-8")) <= 6000 for x in out) and "".join(out) == smile, str([len(x) for x in out]))
    indent = "        " + "z" * 3000
    out = answer.split_long_lines(indent).split("\n")
    check("an indented long line: no empty piece, nothing lost",
          all(x.strip() for x in out) and "".join(out) == indent, str([len(x) for x in out]))

    # MCP: the same answer, and the same continuation by line
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-mcp-")
    import mcp_server                                          # noqa: E402
    res = mcp_server.tool_read_url({"url": srv.url("/long")})
    said = "".join(b.get("text", "") for b in res["content"] if b["type"] == "text")
    sc = res["structuredContent"]
    n = sc["mcp"]["next_from"]
    check("MCP read_url: within the budget, names the next line", len(said.encode("utf-8")) <= BUDGET
          and isinstance(n, int) and ('from=%d' % n) in said, "%d bytes, next %s" % (len(said.encode("utf-8")), n))
    res2 = mcp_server.tool_read({"dir": sc["dir"], "from": n})
    check("MCP read: the block at that line", res2["structuredContent"].get("from") == n
          and ("lines %d-" % n) in res2["content"][0]["text"], str(res2["structuredContent"].get("from")))
    res3 = mcp_server.tool_read_url({"url": srv.url("/long"), "from": n})
    said3 = "".join(b.get("text", "") for b in res3["content"] if b["type"] == "text")
    check("MCP read_url from=N: the same block", ("lines %d-" % n) in said3, said3.split("\n")[0][:70])
    resf = mcp_server.tool_read_url({"url": srv.url("/fragment")})
    saidf = resf["content"][0]["text"].split("\n")[0]
    check("MCP read_url: a suspected fragment's first line says what the CLI's does",
          re.search(frag_line, saidf) is not None, saidf[:120])
    resw = mcp_server.tool_read_url({"url": srv.url("/short")})
    saidw = resw["content"][0]["text"].split("\n")[0]
    check("MCP read_url: a whole text's first line names no share", not re.search(r"\d+%", saidw), saidw[:90])
    odd = mcp_server.tool_read_url({"url": srv.url("/short"), "to": 407, "from": "abc", "file": "notes"})
    said = odd["content"][0]["text"]
    check("MCP read_url leaves out what it cannot use, says so and reads the page",
          not odd.get("isError") and said.startswith("read-page · ok")
          and "ignored: to (no such parameter) · file notes (content.md or page.md) · from abc (a line number)" in said,
          next((ln for ln in said.split("\n") if ln.startswith("ignored")), said[:90]))
    typo = mcp_server.tool_read_url({"url": srv.url("/short"), "fiel": "page.md"})
    said = typo["content"][0]["text"]
    check("MCP: a misspelled argument is the one meant, with no note",
          "── page.md:" in said and "ignored" not in said, said.split("\n")[0][:90])
    res4 = mcp_server.tool_read_url({"url": srv.url("/long"), "file": "page.md"})
    sc4 = res4["structuredContent"]
    n4 = sc4["mcp"]["next_from"]
    res5 = mcp_server.tool_read({"dir": sc4["dir"], "from": n4})
    check("MCP read without file goes on in the file read last",
          res5["structuredContent"].get("file") == "page.md" and ("page.md: lines %d-" % n4) in res5["content"][0]["text"],
          "%s from %s" % (res5["structuredContent"].get("file"), n4))
    old = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "read", "arguments": {"dir": sc["dir"], "offset": 5}}})
    said = ((old.get("result") or {}).get("content") or [{}])[0].get("text") or ""
    check("MCP: an old offset argument is left out and named, the text still comes",
          not (old.get("result") or {}).get("isError") and "ignored: offset (no such parameter)" in said
          and "lines 1-" in said, said.split("\n")[0][:90])
finally:
    srv.close()

# ---------------------------------------------------------------- SKILL.md's table of statuses
# what an agent does on each status: a row for every status the answer gives, and `error`'s fits both of its kinds -
# a network or server error passes (retry later), a file cut short or damaged does not (it said "retry later" alone)
ROOT = os.path.dirname(HERE)
with open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8") as fh_:
    skill_rows = dict(re.findall(r"(?m)^\| `([a-z_]+)` \| (.+?) \|$", fh_.read()))
with open(os.path.join(ROOT, "references", "manifest-schema.json"), encoding="utf-8") as fh_:
    statuses = json.load(fh_)["properties"]["status"]["enum"]
check("SKILL.md's table of statuses has a row for every status the answer gives",
      set(statuses) <= set(skill_rows), str(sorted(set(statuses) - set(skill_rows))))
err_row = skill_rows.get("error", "")
check("SKILL.md's `error` row fits both kinds of error: retry later, and a cut or damaged file is got again "
      "(\"retry later\" alone was wrong for a file cut short)",
      "retry later" in err_row and "cut" in err_row and "damaged" in err_row and "again" in err_row, err_row)

sys.exit(check.done())
