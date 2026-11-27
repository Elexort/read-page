"""The answer contract. No network.

    python -X utf8 tests/contract.py

One call answers with a header and the text, inside 7 900 characters (UTF-16 units, as Cline counts
them), 9 980 bytes and 495 lines counted on what is written (UTF-8, LF), stderr included. A text that
fits comes whole; a longer one comes with an outline, the exact line to go on from and the command that
reads on - run as printed in each shell the machine has -, and the blocks put together are the saved file.
"""
import argparse
import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from harness import PUBLIC, SCRIPT, Checks, cline_form, mcp_dir, mcp_said, run_read, serve     # noqa: E402

check = Checks()
BUDGET, LINES = 9980, 495
CHARS = 7900      # Cline's SDK runtime cuts every tool result at 8 000 characters (KNOWN-ISSUES 263)


def u16(s):
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def slashed(path):
    """A path as an answer's command names it: absolute, forward slashes on Windows."""
    path = os.path.abspath(path)
    return path.replace("\\", "/") if os.name == "nt" else path


def shells():
    """The shells on this machine that a printed command is run in, as (name, run one line with an environment):
    cmd, bash, PowerShell 5.1 and 7. Each is given the line as typed: cmd /s /c with it in quotes, bash -c,
    PowerShell as an encoded command (its own words, no quoting between). Not WSL's bash: its paths are another
    machine's."""
    out = []
    if os.name == "nt":
        out.append(("cmd", lambda line, env: subprocess.run('cmd /d /s /c "%s"' % line, capture_output=True,
                                                             timeout=240, env=env)))
        git_bash = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe")
        if os.path.isfile(git_bash):
            out.append(("bash", lambda line, env: subprocess.run([git_bash, "-c", line], capture_output=True,
                                                                  timeout=240, env=env)))
    else:
        posix = shutil.which("bash") or shutil.which("sh")       # Alpine's containers have sh alone
        if posix:
            out.append((os.path.basename(posix), lambda line, env: subprocess.run(
                [posix, "-c", line], capture_output=True, timeout=240, env=env)))
    for ps in ("powershell", "pwsh"):
        exe = shutil.which(ps)
        if exe:
            out.append((ps, lambda line, env, exe=exe: subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-EncodedCommand",
                 base64.b64encode(line.encode("utf-16-le")).decode("ascii")], capture_output=True, timeout=240,
                env=env)))
    return out


def split_windows(line):
    """argv as a Windows program gets it from a command line with no backslash before a quote (CommandLineToArgvW):
    double quotes group and are dropped."""
    out, cur, quoted, any_ = [], [], False, False
    for ch in line:
        if ch == '"':
            quoted, any_ = not quoted, True
        elif ch in " \t" and not quoted:
            if cur or any_:
                out.append("".join(cur))
            cur, any_ = [], False
        else:
            cur.append(ch)
    if cur or any_:
        out.append("".join(cur))
    return out


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
    # short lines: what JSON adds to an MCP result is most here, a line's "\n" two characters in it (KNOWN-ISSUES 275)
    "/shortlines": page("Short lines", "<h1>Short lines</h1><ul>" + "".join("<li>Short item %04d</li>" % i
                                                                            for i in range(3000)) + "</ul>"),
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
# a page with a tab set and a picture: their markers are found by type and name (KNOWN-ISSUES 265)
ROUTES["/tabs"] = page("Plans", "<h1>Plans</h1>" + sections(12, EN) + (
    "<div role='tablist'><button role='tab' aria-selected='true' aria-controls='p1'>Free Plan Limits</button>"
    "<button role='tab' aria-controls='p2'>Developer Plan Limits</button></div>"
    "<div role='tabpanel' id='p1'><p>FREE-PANEL requests per minute: thirty, and tokens per day: a few.</p></div>"
    "<div role='tabpanel' id='p2' hidden><p>DEV-PANEL requests per minute: a thousand, tokens per day: many.</p></div>")
    + "<p>Before the chart comes a sentence that says what it shows.</p><p><img src='/chart.png' alt='Usage chart'></p>"
    + sections(12, EN, "Later section"))


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
ROUTES["/dollar$sign"] = ROUTES["/long"]      # an address a shell would read inside double quotes (KNOWN-ISSUES 276)
srv = serve(ROUTES)


def first_line(r):
    return r.text.split("\n")[0]


def fits(name, r):
    n = r.out.count(b"\n")
    check(name + ": within 9 980 bytes and 495 lines", len(r.out) <= BUDGET and n <= LINES,
          "%d bytes, %d lines" % (len(r.out), n))
    check(name + ": within 7 900 characters", u16(r.out.decode("utf-8", "replace")) <= CHARS,
          "%d characters" % u16(r.out.decode("utf-8", "replace")))
    check(name + ": LF only, stderr empty, exit 0", b"\r" not in r.out and r.err == b"" and r.rc == 0,
          "rc=%d stderr=%r" % (r.rc, r.err[:80]))


def body(text):
    """The text lines of one answer: after the `── file: from line N of T ──` line, before the pointer - `── next: ...`
    and the command under it - or the end, `── EOF ...`."""
    lines = text.split("\n")
    i = next((k for k, ln in enumerate(lines) if ln.startswith("── ") and not ln.startswith("── EOF ")
              and ": from line " in ln), None)
    if i is None:
        return []
    rest = lines[i + 1:]
    if rest and rest[-1] == "":
        rest.pop()
    for k in range(len(rest) - 1, max(-1, len(rest) - 3), -1):
        if rest[k].startswith("── next: ") or rest[k].startswith("── EOF "):
            return rest[:k]
    return rest


def last_rows(text, n=2):
    """The last n lines of an answer."""
    return text.rstrip("\n").split("\n")[-n:]


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
    n_short = len(lines_of(r))
    check("short: the whole text, no outline, no pointer, its start above it and EOF its last line (KNOWN-ISSUES 276)",
          "── content.md: from line 1 of %d ──" % n_short in r.text and "outline" not in r.text
          and next_line(r.text) is None and body(r.text) == lines_of(r)
          and last_rows(r.text, 1) == ["── EOF content.md: lines 1-%d of %d ──" % (n_short, n_short)],
          str(last_rows(r.text, 1))[:90])
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
        check(path + ": the command under next: names the file it continues",
              last_rows(first.text, 1)[0].endswith(" --file content.md"), last_rows(first.text, 1)[0][-90:])
        saved = lines_of(first)
        got, n, hops, over, more = body(first.text), next_line(first.text), 0, [], first
        while n and hops < 60:
            more = run_read(srv.url(path), "--from", str(n), reuse=first)
            if (len(more.out) > BUDGET or more.out.count(b"\n") > LINES or more.err or more.rc
                    or u16(more.out.decode("utf-8", "replace")) > CHARS):
                over.append((n, len(more.out), more.rc))
            check_start = body(more.text)[:1] == saved[n - 1:n]
            if not check_start:
                over.append((n, "starts elsewhere"))
            got += body(more.text)
            n, hops = next_line(more.text), hops + 1
        check(path + ": every block fits and starts at its line", not over, str(over[:3]))
        check(path + ": the blocks put together are content.md", got == saved,
              "%d of %d lines, %d answers" % (len(got), len(saved), hops + 1))
        top = re.findall(r"── content\.md: from line (\d+) of (\d+) ──", more.text)
        check(path + ": the last block's last line is EOF, with the lines it holds (KNOWN-ISSUES 276)",
              top and last_rows(more.text, 1) == ["── EOF content.md: lines %s-%d of %d ──" % (top[-1][0], len(saved),
                                                                                             len(saved))]
              and top[-1][1] == str(len(saved)), str(last_rows(more.text, 1))[:90])

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
          last_rows(whole.text, 1)[0].endswith(" --file page.md")
          and body(on.text)[:1] == lines_of(whole, "page.md")[(n or 1) - 1:(n or 1)],
          first_line(on)[:80])

    # a forgotten --file goes on in the file read last; --file switches it
    on = run_read(srv.url("/long"), "--from", str(n or 1), reuse=whole)
    check("--from without --file goes on in page.md when page.md was read last",
          "── page.md: from line %d of " % (n or 1) in on.text
          and body(on.text)[:1] == lines_of(whole, "page.md")[(n or 1) - 1:(n or 1)], first_line(on)[:80])
    plain = run_read(srv.url("/long"))
    k = next_line(plain.text)
    run_read(srv.url("/long"), "--from", "1", "--file", "page.md", reuse=plain)     # switch to the other file
    stay = run_read(srv.url("/long"), "--from", str(k), reuse=plain)
    check("--file switches the file: a later --from without --file stays in page.md",
          "── page.md: from line %d of " % k in stay.text and body(stay.text)[:1] == lines_of(plain, "page.md")[k - 1:k],
          first_line(stay)[:80])
    back = run_read(srv.url("/long"), "--from", str(k), "--file", "content.md", reuse=plain)
    check("the first pointer, which names content.md, still leads back to content.md",
          "── content.md: from line %d of " % k in back.text and body(back.text)[:1] == lines_of(plain)[k - 1:k],
          first_line(back)[:80])
    anew = run_read(srv.url("/long"), reuse=plain)
    check("a new reading (no --from) starts at content.md again", "── content.md: from line 1 of " in anew.text,
          first_line(anew)[:80])

    # the answer's lines (KNOWN-ISSUES 276): above the text `── content.md: from line A of T ──`, every block alike;
    # below it, while text remains, `── next: line N of T ──` and on a line of its own the command that reads on,
    # literal - run here as printed in each shell the machine has; the end is `── EOF content.md: lines A-T of T ──`
    import ownenv                                              # noqa: E402
    first = run_read(srv.url("/long"))
    saved = lines_of(first)
    n = next_line(first.text)
    line = last_rows(first.text, 1)[0]
    python_name = getattr(ownenv, "python_name", None) or (lambda exe: "python")   # none before KNOWN-ISSUES 276
    me = python_name(sys.executable)
    argv_want = [me, "-X", "utf8", slashed(SCRIPT), srv.url("/long"), "--dir", slashed(first.dir), "--from", str(n),
                 "--chars", "7900", "--file", "content.md"]
    check("next: two lines - where it goes on, then the command that reads on, alone and literal",
          last_rows(first.text, 2) == ["── next: line %d of %d ──" % (n, len(saved)),
                                       '%s -X utf8 "%s" "%s" --dir "%s" --from %d --chars 7900 --file content.md' % (
                                           me, slashed(SCRIPT), srv.url("/long"), slashed(first.dir), n)],
          str(last_rows(first.text, 2))[:200])
    for name, argv in (("as bash splits it", shlex.split(line)), ("as Windows splits it", split_windows(line))):
        check("... split %s: the interpreter, -X utf8, the script, the address, the flags" % name, argv == argv_want,
              str(argv[3:])[:160])
    e_sh = dict(os.environ, READ_PAGE_CACHE=os.path.join(first.root, "cache"), READ_PAGE_TEST_PUBLIC_HOST=PUBLIC,
                PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
    for k in ("FIRECRAWL_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "JINA_API_KEY", "READ_PAGE_PYTHON_NAME"):
        e_sh.pop(k, None)
    ran = []
    for name, run in shells():
        p = run(line, e_sh)
        said = p.stdout.decode("utf-8", "replace")
        ran.append(name)
        check("... run as printed in %s: the next block, from line %d" % (name, n),
              p.returncode == 0 and "── content.md: from line %d of " % n in said and body(said)[:1] == saved[n - 1:n],
              "rc %s %s" % (p.returncode, (said.split("\n")[0] or p.stderr.decode("utf-8", "replace")[-160:])[:100]))
    check("... in the shells this machine has (cmd and PowerShell on Windows at the least): %s" % ", ".join(ran),
          len(ran) >= (2 if os.name == "nt" else 1), str(ran))
    kept = run_read(srv.url("/long"), "--allow-external", "--deny-images", "--download", "--refresh", "--clear-cookies",
                    "--screenshots", "0")
    k_argv = shlex.split(last_rows(kept.text, 1)[0])
    check("... it keeps the flags that matter if the page is read again, and drops --refresh and the rest",
          [a for a in k_argv if a.startswith("--") and a not in ("--dir", "--from", "--chars", "--file")]
          == ["--allow-external", "--deny-images", "--download"], str(k_argv[5:])[:140])
    named = run_read(srv.url("/long"), env={"READ_PAGE_PYTHON_NAME": "python3.99"})
    check("... the interpreter by the name the agent started the skill with, which the first process hands on",
          last_rows(named.text, 1)[0].startswith("python3.99 -X utf8 "), last_rows(named.text, 1)[0][:60])
    check("ownenv.python_name: a Python as a command names it, \"python\" for anything else",
          [python_name(x) for x in ("C:\\Python313\\python.exe", "/usr/bin/python3.12", "", "C:\\x\\pythonw.exe",
                                           "/opt/app/host", "C:\\a b\\my python.exe", "pypy3")]
          == ["python", "python3.12", "python", "python", "python", "python", "pypy3"], "")
    dollar = run_read(srv.url("/dollar$sign"))
    n_d = next_line(dollar.text)
    check("an address a shell reads inside double quotes ($): the words instead of the command",
          n_d and last_rows(dollar.text, 2) == ["── next: line %d of %d ──" % (n_d, len(lines_of(dollar))),
                                                "the same command with --from %d --chars 7900 --file content.md" % n_d],
          str(last_rows(dollar.text, 1))[:120])
    stray = run_read(srv.url("/long"), "--from", "5", "--file", "content.md", "──", reuse=first)
    ign = next((ln for ln in stray.text.split("\n") if ln.startswith("ignored: ")), "")
    check("a stray ── (a model copied the decoration): left out and named, the read goes on",
          stray.rc == 0 and ign == "ignored: ── (the answer's decoration, not part of the command)"
          and "── content.md: from line 5 of " in stray.text, ign or first_line(stray)[:80])

    # the line above the text names where it starts, and no end (KNOWN-ISSUES 279): a harness that keeps an answer's
    # head and cuts its tail (Zed) cuts next: off and leaves that line, and a model took the end it named for the end
    # of what it had seen and went on after lines it never saw. The end is named in next: and in EOF alone
    def tops(text):
        return [ln for ln in text.split("\n") if re.match(r"── (content|page)\.md: ", ln)]

    on_top = run_read(srv.url("/long"), "--from", str(n), "--file", "content.md", reuse=first)
    page_top = run_read(srv.url("/long"), "--file", "page.md")
    short_top = run_read(srv.url("/short"))
    got_tops = [tops(r.text) for r in (first, on_top, page_top, short_top)]
    want_tops = [["── content.md: from line 1 of %d ──" % len(saved)],
                 ["── content.md: from line %d of %d ──" % (n, len(saved))],
                 ["── page.md: from line 1 of %d ──" % len(lines_of(page_top, "page.md"))],
                 ["── content.md: from line 1 of %d ──" % len(lines_of(short_top))]]
    check("the line above the text names where it starts and of how many lines, no end: a first block, a later one, "
          "page.md, a text that fits (KNOWN-ISSUES 279)", got_tops == want_tops, str(got_tops)[:200])

    # --chars C, one knob in characters (KNOWN-ISSUES 277): the whole answer - header, outline, the lines above and
    # below the text - within C characters (UTF-16 units), C x 9 980 / 7 900 bytes and C x 495 / 7 900 lines, whole
    # lines; on a first read, --from N and --from "text"; clamped to 1 000 .. 150 000, named on ignored: with what was
    # used; no --chars is --chars 7900. --to is gone: named on ignored:, the read goes on
    import answer                                              # noqa: E402
    plain = run_read(srv.url("/plainlong"))
    saved = lines_of(plain)

    def within(r, c):
        return u16(r.text) <= c and len(r.out) <= c * 9980 // 7900 and r.out.count(b"\n") <= c * 495 // 7900

    def size(r):
        return "%d characters, %d bytes, %d lines" % (u16(r.text), len(r.out), r.out.count(b"\n"))

    big = run_read(srv.url("/plainlong"), "--chars", "20000", reuse=plain)
    n_big = next_line(big.text)
    check("--chars 20000 on a first read: within 20 000 characters, 25 265 bytes and 1 253 lines, past one block",
          within(big, 20000) and u16(big.text) > 15000 and n_big and body(big.text) == saved[:n_big - 1],
          size(big) + ", next %s" % n_big)
    on = run_read(srv.url("/plainlong"), "--from", str(n_big or 1), "--chars", "20000", reuse=plain)
    n_on = next_line(on.text)
    check("--from N --chars 20000: from line N, whole lines, within the size",
          within(on, 20000) and u16(on.text) > 15000 and n_on and body(on.text) == saved[(n_big or 1) - 1:n_on - 1],
          size(on))
    at_q = next(i for i, ln in enumerate(saved, 1) if "Sentence 300.4 explains" in ln)
    q = run_read(srv.url("/plainlong"), "--from", "Sentence 300.4 explains", "--chars", "3000", reuse=plain)
    check("--from \"text\" --chars 3000: from the quote's line, within 3 000 characters",
          within(q, 3000) and "── content.md: from line %d of " % at_q in q.text and body(q.text)[:1] == saved[at_q - 1:at_q],
          size(q))
    d0 = run_read(srv.url("/plainlong"), "--from", "5", reuse=plain)
    d79 = run_read(srv.url("/plainlong"), "--from", "5", "--chars", "7900", reuse=plain)
    check("no --chars is --chars 7900: the same answer, 7 900 characters, 9 980 bytes and 495 lines at most",
          d0.text.split("\n")[1:] == d79.text.split("\n")[1:] and within(d0, 7900)
          and answer.limits(7900) == answer.limits() == {"chars": 7900, "budget": 9980, "max_lines": 495},
          size(d0))
    for value, used, note in (("500", 1000, "--chars 500 (1000 at the least: 1000 used)"),
                              ("999999", 150000, "--chars 999999 (150000 at the most: 150000 used)"),
                              ("abc", 7900, "--chars abc (a number of characters: 7900 used)")):
        r = run_read(srv.url("/plainlong"), "--from", "5", "--chars", value, reuse=plain)
        ign = next((ln for ln in r.text.split("\n") if ln.startswith("ignored: ")), "")
        check("--chars %s: %d used, named on ignored:, the read goes on" % (value, used),
              r.rc == 0 and note in ign and within(r, used) and "── content.md: from line 5 of " in r.text
              and (used < 100000 or u16(r.text) > 100000), ign[:90] + " | " + size(r))
    one = run_read(srv.url("/oneline"), "--chars", "1000")
    check("--chars 1000, lines of 1 998 characters: one line at least, its head, within 1 000",
          within(one, 1000) and "is longer than one answer" in one.text and next_line(one.text) == 2, size(one))
    gone = run_read(srv.url("/plainlong"), "--from", "50", "--to", "60", reuse=plain)
    ign = next((ln for ln in gone.text.split("\n") if ln.startswith("ignored: ")), "")
    check("--to is gone: left out and named, the usual block from --from",
          ign == "ignored: --to 60 (gone: --chars sets the size)" and "── content.md: from line 50 of " in gone.text
          and " sent" not in gone.text and next_line(gone.text) and within(gone, 7900), ign or first_line(gone)[:80])
    alone = run_read(srv.url("/short"), "--to", "3")
    check("--to alone is gone too: the whole short text, the note", "--to 3 (gone: --chars sets the size)" in alone.text
          and body(alone.text) == lines_of(alone), first_line(alone)[:80])

    # READ_PAGE_TEST_CUT, a test hook (references/answer.md, For testing the skill): the skill cuts its own answer the
    # way a harness cuts what a command printed, after the answer is built - Cline's middle, Zed's head, OpenCode's
    # tail, Claude Code's file - so that a model can be taught to go on under each cut
    cut_of = getattr(answer, "harness_cut", None) or (lambda out, spec=None: out)        # none before the hook
    big_text = "".join("line %04d %s\n" % (i, "x" * 90) for i in range(1, 801))
    mid = cut_of(big_text, "middle:8000")
    m_gap = re.search(r"\n\n\.\.\.\[truncated (\d+) chars\]\.\.\.\n\n", mid)
    check("READ_PAGE_TEST_CUT=middle:8000 (Cline): 8 000 characters, both ends kept, the gap named as Cline names it",
          u16(mid) <= 8000 and m_gap is not None and mid.startswith(big_text[:3900]) and mid.endswith(big_text[-3900:])
          and abs(int(m_gap.group(1)) - (u16(big_text) - (u16(mid) - len(m_gap.group(0))))) <= 2,
          "%d characters; %s" % (u16(mid), m_gap.group(0).strip() if m_gap else "no gap"))
    head_cut = cut_of(big_text, "head:16384")
    h_note = re.match(r"Command output too long\. The first (\d+) bytes:\n\n", head_cut)
    check("... head:16384 (Zed): the first 16 384 bytes at most, cut at a line's end, the note above",
          h_note is not None and int(h_note.group(1)) <= 16384 and big_text.startswith(head_cut[h_note.end():])
          and head_cut.endswith("\n") and len(head_cut[h_note.end():].encode("utf-8")) == int(h_note.group(1)),
          head_cut[:60])
    t_note = "...output truncated...\n\n"
    tail_cut = cut_of(big_text, "tail:51200")
    check("... tail:51200 (OpenCode): the last 51 200 bytes at most, from a line's start, `...output truncated...` above",
          tail_cut.startswith(t_note) and big_text.endswith(tail_cut[len(t_note):])
          and tail_cut[len(t_note):].startswith("line ") and len(tail_cut[len(t_note):].encode("utf-8")) <= 51200,
          tail_cut[:60])
    file_cut = cut_of(big_text, "file:30000")
    f_path = re.match(r"Output too large \([\d.]+KB\)\. Full output saved to: (.+)\n", file_cut)
    saved_whole = ""
    if f_path and os.path.isfile(f_path.group(1)):
        with open(f_path.group(1), encoding="utf-8") as fh_:
            saved_whole = fh_.read()
        os.unlink(f_path.group(1))
    check("... file:30000 (Claude Code): over 30 000 bytes the whole answer goes to a file, its name and its first "
          "2 000 characters are printed",
          saved_whole == big_text and big_text[:2000] in file_cut and len(file_cut) < 2400, file_cut[:80])
    check("... an answer under N, a value that names no cut, no value: the answer as it is",
          cut_of("short\n", "middle:8000") == "short\n" and cut_of(big_text, "sideways:9") == big_text
          and cut_of(big_text, "") == big_text and cut_of(big_text, "head:x") == big_text, "")
    cli_cut = run_read(srv.url("/plainlong"), "--chars", "20000", env={"READ_PAGE_TEST_CUT": "middle:8000"})
    check("... the CLI: its own answer, built at 20 000 characters, printed cut as Cline would, its command at the end",
          cli_cut.rc == 0 and u16(cli_cut.text) <= 8000 and "...[truncated " in cli_cut.text
          and cli_cut.text.startswith("read-page · ok")
          and last_rows(cli_cut.text, 1)[0].endswith("--chars 20000 --file content.md"), "%d characters" % u16(cli_cut.text))
    zed = run_read(srv.url("/plainlong"), "--chars", "20000", env={"READ_PAGE_TEST_CUT": "head:16384"})
    check("... head:16384 on the CLI: the head alone, no next: line", zed.text.startswith("Command output too long. ")
          and "── next:" not in zed.text and len(zed.out) <= 16384 + 60, "%d bytes" % len(zed.out))
    check("... and the line above its text names no end, which a model whose next: was cut off would take for the end "
          "of what it saw (KNOWN-ISSUES 279)",
          tops(zed.text) == ["── content.md: from line 1 of %d ──" % len(lines_of(zed))], str(tops(zed.text))[:120])
    js = run_read(srv.url("/plainlong"), "--json", env={"READ_PAGE_TEST_CUT": "middle:2000"})
    check("... --json is never cut", js.text.lstrip().startswith("{") and "...[truncated" not in js.text, js.text[:40])

    # --from "text": the answer starts at the first line holding it - whitespace folded, then without case -,
    # the first at or after where the last answer started when several do; a marker by its type and name, a
    # picture by its number; not found, the outline (KNOWN-ISSUES 265)
    first = run_read(srv.url("/long"))
    saved = lines_of(first)
    at = next(i for i, ln in enumerate(saved, 1) if "Sentence 20.4 explains" in ln)
    for quote, why in (("Sentence 20.4 explains one more detail", "a quote"),
                       ("20.4 explains one more det", "a quote cut in the middle of a line"),
                       ("  sentence   20.4 EXPLAINS one  ", "spaces and case aside"),
                       ("Sentence 20.4 explains one more detail\nSentence 20.5 explains", "two lines, by the first")):
        r = run_read(srv.url("/long"), "--from", quote, reuse=first)
        check("--from \"text\", %s: the answer starts at the line holding it" % why,
              "── content.md: from line %d of " % at in r.text and body(r.text)[:1] == saved[at - 1:at]
              and "ignored:" not in r.text, first_line(r)[:60] + " | " + (re.findall(r"── content\.md: from line \d+", r.text)
                                                                           or ["no block"])[0])
    many = "explains one more detail of the reader"
    hits = [i for i, ln in enumerate(saved, 1) if many in ln]
    run_read(srv.url("/long"), "--from", "1", reuse=first)
    r = run_read(srv.url("/long"), "--from", many, reuse=first)
    check("--from \"text\" that many lines hold: the first, the last answer having started at line 1",
          "── content.md: from line %d of " % hits[0] in r.text, (re.findall(r"── content\.md: from line \d+", r.text) or [""])[0])
    run_read(srv.url("/long"), "--from", str(hits[3] - 1), reuse=first)
    r = run_read(srv.url("/long"), "--from", many, reuse=first)
    check("... and the first after where the last answer started (line %d)" % (hits[3] - 1),
          "── content.md: from line %d of " % hits[3] in r.text, (re.findall(r"── content\.md: from line \d+", r.text) or [""])[0])
    r = run_read(srv.url("/long"), "--from", "no line of this page holds these words", reuse=first)
    check("--from \"text\" not found: the answer says so and shows the outline, no text",
          '── not in content.md: "no line of this page holds these words", spaces and case aside; the outline below '
          'names its lines for --from N ──' in r.text and "outline (line, heading):" in r.text
          and re.search(r"^\s+\d+ ## Section 30$", r.text, re.M) and "── content.md: from line" not in r.text
          and "Sentence 1.1" not in r.text, r.text.split("\n")[-2][:90])
    r = run_read(srv.url("/long"), "--from", "Sentence 20.4 explains", "--file", "page.md", reuse=first)
    pm = lines_of(first, "page.md")
    at_p = next(i for i, ln in enumerate(pm, 1) if "Sentence 20.4 explains" in ln)
    check("--from \"text\" in page.md alike", "── page.md: from line %d of " % at_p in r.text, first_line(r)[:80])
    r = run_read(srv.url("/long"), "--from", "Sentence 20.4 explains", "--chars", "1500", "--file", "content.md",
                 reuse=first)
    check("--from \"text\" --chars 1500: from the quote's line, within 1 500 characters",
          "── content.md: from line %d of " % at in r.text and body(r.text)[:1] == saved[at - 1:at]
          and u16(r.text) <= 1500, "%d characters" % u16(r.text))
    tabs_r = run_read(srv.url("/tabs"))
    tl = lines_of(tabs_r)
    for quote, want in (("[tab · Developer Plan Limits]", "[tab · hidden, but extracted · Developer Plan Limits]"),
                        ("[tab · Free Plan Limits]", "[tab · shown · Free Plan Limits]"),
                        ("[img #1]", "[img #1 · ")):
        line = next((i for i, ln in enumerate(tl, 1) if want in ln), None)
        r = run_read(srv.url("/tabs"), "--from", quote, reuse=tabs_r)
        check("--from \"%s\": the marker is found whatever its state says" % quote,
              line and "── content.md: from line %d of " % line in r.text, "line %s; %s" % (
                  line, (re.findall(r"── content\.md: from line \d+|── not in .*", r.text) or [""])[0][:80]))
    # a quote that ends INSIDE a marker - what an agent quotes when its harness cut the answer in the middle of a
    # picture's or a tab's line (Cline keeps about 3 985 characters at each end): the line as it stands is matched
    # too, whitespace folded, so a part of a marker and a marker quoted without its state are both found
    # (KNOWN-ISSUES 269)
    tab_at = next(i for i, ln in enumerate(tl, 1) if "[tab · hidden, but extracted · Developer Plan Limits]" in ln)
    img_at = next(i for i, ln in enumerate(tl, 1) if "[img #1 · " in ln)
    for quote, want, why in (("[tab · hidden, but extr", tab_at, "the head of a tab's marker"),
                             ("hidden, but extracted · Developer Pl", tab_at, "the middle of a tab's marker"),
                             ("but extracted · Developer Plan Limits]", tab_at, "the tail of a tab's marker"),
                             ("[img #1 · not downloaded", img_at, "the head of a picture's marker"),
                             ("not downloaded: 404 · Usage", img_at, "the middle of a picture's marker"),
                             ("Usage chart] " + srv.url("/chart.png"), img_at, "the tail of a picture's marker and the text after it"),
                             ("  usage   CHART]  " + srv.url("/CHART.png"), img_at, "... with spaces and case aside")):
        r = run_read(srv.url("/tabs"), "--from", quote, reuse=tabs_r)
        check("--from \"%s\": %s is found" % (quote.strip(), why),
              "── content.md: from line %d of " % want in r.text, "line %s; %s" % (
                  want, (re.findall(r"── content\.md: from line \d+|── not in .*", r.text) or [""])[0][:80]))
    # the order of preference does not change: an exact match at or after the last answer's start comes first
    r = run_read(srv.url("/tabs"), "--from", "Plan Limits]", reuse=tabs_r)
    free_at = next(i for i, ln in enumerate(tl, 1) if "[tab · shown · Free Plan Limits]" in ln)
    check("--from \"Plan Limits]\" (two markers hold it): the first, as before",
          "── content.md: from line %d of " % free_at in r.text, (re.findall(r"── content\.md: from line \d+", r.text) or [""])[0])
    # 300 000 marker lines, the case that was measured: the quote of a cut marker is found, and not slowly
    import time
    import answer                                              # noqa: E402
    marks =["[img #%d · 100x80 3K · picture %d] img/%06d-picture-%d.png" % (k, k, k, k) for k in range(1, 300001)]
    t0 = time.perf_counter()
    got = answer.find(marks, "#299997 · 100x80 3K · picture 299997] im")
    took = time.perf_counter() - t0
    check("find on 300 000 lines: a quote that ends inside a marker is found, in seconds", got == 299997 and took < 6,
          "line %s in %.2f s" % (got, took))
    check("... a marker quoted by its number and name is found as before", answer.find(marks, "[img #299997]") == 299997
          and answer.find(marks, "[img #299997 · 100x80 3K · picture 299997]") == 299997, "")

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
    # invented --to 407 and lost the call, before --to was one, and --to is gone again): the page is read and the
    # header names what was left out
    for flags, said in ((["--print"], "--print"), (["--public"], "--public"), (["--external"], "--external"),
                        (["--allow-images"], "--allow-images (no such flag)"),
                        (["--from", "-1"], "--from -1"), (["--file", "notes.md"], "--file notes.md"),
                        (["--until", "407"], "--until 407 (no such flag: --chars sets the size)"),
                        (["--to", "abc"], "--to abc (gone: --chars sets the size)"),
                        (["--to=40"], "--to=40 (gone: --chars sets the size)")):
        r = run_read(srv.url("/short"), *flags)
        ign = next((ln for ln in r.text.split("\n") if ln.startswith("ignored: ")), "")
        check("not ours, %s: the page is read, the header names it, exit 0" % " ".join(flags),
              r.rc == 0 and r.text.startswith("read-page · ok") and said in ign, "rc=%d %r" % (r.rc, ign[:90]))
    # a misspelled flag is the one meant, silently: --fil page.md prints page.md, --form 2 goes on
    r = run_read(srv.url("/short"), "--fil", "page.md", "--form", "2")
    check("a typo of a flag does what the flag does, with no note",
          r.rc == 0 and "── page.md: from line 2 of " in r.text and "ignored:" not in r.text, first_line(r)[:90])
    r = run_read("--until", "5", srv.url("/short"))        # the stray flag first, its value taken for the URL
    check("a stray flag before the URL: the URL is still the one read",
          r.rc == 0 and r.text.startswith("read-page · ok") and "ignored: --until 5" in r.text, first_line(r)[:90])
    r = run_read(srv.url("/short"), "--json", "--until", "3")
    try:
        ignored = json.loads(r.text).get("ignored")
    except ValueError:
        ignored = None
    check("--json names the left-out flags too; the saved manifest does not keep them",
          ignored == ["--until 3 (no such flag: --chars sets the size)"]
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

    # MCP: the same answer, and the same continuation by line. A result is its blocks alone, no structuredContent
    # (KNOWN-ISSUES 275): Cline's SDK runtime hands the model the whole result object as JSON and counts it, so the
    # manifest there cost a read about 3 000 characters of its text. The folder is on the answer's files: line, the
    # manifest is the folder's file
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-mcp-")
    import mcp_server                                          # noqa: E402
    results = []                         # (what was asked, the result) of every call here

    def mcp(args, tool="read_url"):
        res = (mcp_server.tool_read if tool == "read" else mcp_server.tool_read_url)(args)
        results.append(("%s %s" % (tool, json.dumps(args, ensure_ascii=False)[:60]), res))
        return res

    res = mcp({"url": srv.url("/long")})
    said = mcp_said(res)
    d = mcp_dir(res)
    n = next_line(said)
    check("MCP read_url: within the budget, names the next line and its folder (files:), whose manifest is there",
          len(said.encode("utf-8")) <= BUDGET and u16(said) <= CHARS and isinstance(n, int) and ('from=%d' % n) in said
          and os.path.isfile(os.path.join(d, "manifest.json")),
          "%d bytes, %d characters, next %s, %s" % (len(said.encode("utf-8")), u16(said), n, d[-30:]))
    rows_m = last_rows(said, 2)
    call_m = re.match(r'read\(dir="([^"]+)", file="content\.md", from=(\d+), chars=7900\)$', rows_m[-1])
    check("MCP next: two lines, the read call under it with its folder (KNOWN-ISSUES 276)",
          rows_m[0].startswith("── next: line %d of " % n) and rows_m[0].endswith(" ──") and call_m
          and int(call_m.group(2)) == n
          and os.path.normcase(os.path.abspath(call_m.group(1))) == os.path.normcase(os.path.abspath(d)),
          rows_m[-1][:140])
    on_m = mcp({"dir": call_m.group(1), "file": "content.md", "from": int(call_m.group(2)), "chars": 7900},
               "read") if call_m else {}
    check("... that call, as printed, gives the next block", ("── content.md: from line %d of " % n) in mcp_said(on_m),
          mcp_said(on_m)[:80])
    with open(os.path.join(d, "content.md"), encoding="utf-8") as fh_:
        n_long = len(fh_.read().rstrip("\n").split("\n"))
    m_tops = [tops(mcp_said(x)) for x in (res, on_m)]
    check("MCP: the line above the text names where it starts and of how many lines, no end (KNOWN-ISSUES 279)",
          m_tops == [["── content.md: from line 1 of %d ──" % n_long], ["── content.md: from line %d of %d ──" % (n, n_long)]],
          str(m_tops)[:160])
    rp = mcp_server.readpage
    ns = argparse.Namespace(url="https://example.com/a", target="https://example.com/a", dir="", allow_external=True,
                            force_external=True, alternate=True, deny_images=True, download=True, refresh=True,
                            clear_cookies=True, screenshots="2", ocr=3, json=True)
    cmd = rp.cli_command(ns, 12, 20000, "page.md") if hasattr(rp, "cli_command") else ""
    check("the CLI's command carries --allow-external, --force-external, --alternate, --deny-images and --download; "
          "never --refresh, --clear-cookies, --screenshots, --ocr or --json",
          cmd == '%s -X utf8 "%s" "https://example.com/a" --allow-external --force-external --alternate --deny-images '
          '--download --from 12 --chars 20000 --file page.md' % (me, slashed(SCRIPT)),
          cmd[:160])
    res2 = mcp({"dir": d, "from": n}, "read")
    check("MCP read: the block at that line", ("── content.md: from line %d of " % n) in mcp_said(res2), mcp_said(res2)[:70])
    res3 = mcp({"url": srv.url("/long"), "from": n})
    said3 = mcp_said(res3)
    check("MCP read_url from=N: the same block", ("from line %d of " % n) in said3, said3.split("\n")[0][:70])
    long_lines = open(os.path.join(d, "content.md"), encoding="utf-8").read().rstrip("\n").split("\n")
    # chars, as --chars (KNOWN-ISSUES 277): the whole result as Cline counts it within that many; to is gone
    rc20 = mcp({"url": srv.url("/plainlong"), "chars": 20000})
    check("MCP read_url chars=20000: past one block, as Cline counts it within 20 000 characters, the size carried on",
          15000 < cline_form(rc20) <= 20000 and "chars=20000" in mcp_said(rc20).rstrip("\n").split("\n")[-1],
          "%d characters as JSON; %s" % (cline_form(rc20), mcp_said(rc20).rstrip("\n").split("\n")[-1][-60:]))
    rc3 = mcp({"dir": d, "from": 121, "chars": 3000}, "read")
    check("MCP read chars=3000: from line 121, as Cline counts it within 3 000 characters",
          cline_form(rc3) <= 3000 and "── content.md: from line 121 of " in mcp_said(rc3) and "chars=3000" in mcp_said(rc3),
          "%d characters as JSON" % cline_form(rc3))
    rc1 = mcp({"dir": d, "from": 121, "chars": "99"}, "read")
    check("MCP chars=99: 1 000 used, named on ignored:", "chars 99 (1000 at the least: 1000 used)" in mcp_said(rc1)
          and cline_form(rc1) <= 1000, next((ln for ln in mcp_said(rc1).split("\n") if ln.startswith("ignored")), ""))
    rt = mcp({"url": srv.url("/long"), "from": 1, "to": 120})
    check("MCP read_url to= is gone: named on ignored:, the usual block",
          "to 120 (gone: chars sets the size)" in mcp_said(rt) and "── content.md: from line 1 of " in mcp_said(rt)
          and " sent" not in mcp_said(rt) and cline_form(rt) <= CHARS,
          next((ln for ln in mcp_said(rt).split("\n") if ln.startswith("ignored")), mcp_said(rt)[:80]))
    rr = mcp({"dir": d, "from": 121, "to": 130}, "read")
    check("MCP read to= is gone too", "to 130 (gone: chars sets the size)" in mcp_said(rr)
          and "── content.md: from line 121 of " in mcp_said(rr), mcp_said(rr)[:90])
    # READ_PAGE_TEST_CUT over MCP: the result's text cut the same way, one text block
    os.environ["READ_PAGE_TEST_CUT"] = "middle:8000"
    try:
        cut_r = (mcp_server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "read_url", "arguments": {"url": srv.url("/plainlong"), "chars": 20000}}}) or {}).get("result") or {}
        probe_r = (mcp_server.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
            "name": "read_url", "arguments": {"url": "probe", "probe": 9000}}}) or {}).get("result") or {}
    finally:
        os.environ.pop("READ_PAGE_TEST_CUT", None)
    results.append(("read_url under READ_PAGE_TEST_CUT", cut_r))
    check("MCP under READ_PAGE_TEST_CUT=middle:8000: the text cut as Cline would cut it, one block; the probe is not",
          len(cut_r.get("content") or []) == 1 and u16(mcp_said(cut_r)) <= 8000 and "...[truncated " in mcp_said(cut_r)
          and mcp_said(cut_r).startswith("read-page · ok") and mcp_said(probe_r) == answer.probe(9000),
          "%d characters" % u16(mcp_said(cut_r)))
    at = next(i for i, ln in enumerate(long_lines, 1) if "Sentence 20.4 explains" in ln)
    rq = mcp({"url": srv.url("/long"), "from": "sentence 20.4 EXPLAINS"})
    said_q = mcp_said(rq)
    check("MCP read_url from=\"text\": from the line holding it", ("── content.md: from line %d of " % at) in said_q,
          (re.findall(r"── content\.md: from line \d+", said_q) or [""])[0])
    rq = mcp({"dir": d, "from": "20.4 explains one"}, "read")
    check("MCP read from=\"text\": from the line holding it", ("── content.md: from line %d of " % at) in mcp_said(rq),
          mcp_said(rq).split("\n")[-2][:80])
    rq = mcp({"dir": d, "from": "words no line holds"}, "read")
    check("MCP read from=\"text\" not found: the outline", '── not in content.md: "words no line holds"'
          in mcp_said(rq) and "outline (line, heading):" in mcp_said(rq) and not rq.get("isError"), mcp_said(rq)[:90])
    resf = mcp({"url": srv.url("/fragment")})
    saidf = mcp_said(resf).split("\n")[0]
    check("MCP read_url: a suspected fragment's first line says what the CLI's does",
          re.search(frag_line, saidf) is not None, saidf[:120])
    resw = mcp({"url": srv.url("/short")})
    saidw = mcp_said(resw).split("\n")[0]
    check("MCP read_url: a whole text's first line names no share", not re.search(r"\d+%", saidw), saidw[:90])
    check("MCP read_url: a text that fits ends with EOF, its lines named",
          re.match(r"── EOF content\.md: lines 1-(\d+) of \1 ──$", last_rows(mcp_said(resw), 1)[0]) is not None,
          last_rows(mcp_said(resw), 1)[0][:80])
    odd = mcp({"url": srv.url("/short"), "till": 407, "from": -3, "file": "notes"})
    said = mcp_said(odd)
    check("MCP read_url leaves out what it cannot use, says so and reads the page",
          not odd.get("isError") and said.startswith("read-page · ok")
          and "ignored: till (no such parameter) · file notes (content.md or page.md) · from -3 (a line number, 1 or "
              "more)" in said, next((ln for ln in said.split("\n") if ln.startswith("ignored")), said[:90]))
    odd = mcp({"url": srv.url("/short"), "from": "abc"})
    said = mcp_said(odd)
    check("MCP read_url from=\"abc\" is a quote: not found, it says so", not odd.get("isError")
          and '── not in content.md: "abc", spaces and case aside' in said and "ignored" not in said, said[:120])
    typo = mcp({"url": srv.url("/short"), "fiel": "page.md"})
    said = mcp_said(typo)
    check("MCP: a misspelled argument is the one meant, with no note",
          "── page.md:" in said and "ignored" not in said, said.split("\n")[0][:90])
    res4 = mcp({"url": srv.url("/long"), "file": "page.md"})
    n4 = next_line(mcp_said(res4))
    res5 = mcp({"dir": mcp_dir(res4), "from": n4}, "read")
    check("MCP read without file goes on in the file read last", ("── page.md: from line %d of " % n4) in mcp_said(res5),
          mcp_said(res5).split("\n")[0][:70])
    old = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "read", "arguments": {"dir": d, "offset": 5}}})
    results.append(("read offset=5 (handle)", old.get("result") or {}))
    said = mcp_said(old.get("result"))
    check("MCP: an old offset argument is left out and named, the text still comes",
          not (old.get("result") or {}).get("isError") and "ignored: offset (no such parameter)" in said
          and ": from line 1 of " in said, said.split("\n")[0][:90])
    for args, tool, why in (({"url": ""}, "read_url", "a call with no url"),
                            ({"dir": os.path.join(tempfile.gettempdir(), "no-such-read-page-folder")}, "read", "no such folder"),
                            ({"dir": d, "file": "img/none.png"}, "read", "no such file")):
        bad = mcp(args, tool)
        check("MCP, an error (%s): the answer says so, an error result" % why,
              bad.get("isError") is True and mcp_said(bad).startswith("read-page · error · "), mcp_said(bad)[:80])

    # the whole result as Cline's SDK runtime counts it - JSON.stringify of the result object, a line's "\n" two
    # characters in it - stays within the block: 8 000 is where Cline cuts (KNOWN-ISSUES 275)
    sl = mcp({"url": srv.url("/shortlines")})
    sl2 = mcp({"dir": mcp_dir(sl), "from": next_line(mcp_said(sl)) or 1}, "read")
    pr79 = mcp({"url": "probe:7900"})
    for name, r in (("read_url, a long page", res), ("read, its next block", res2), ("read_url from=N", res3),
                    ("read_url, a page of short lines", sl), ("read, its next block", sl2),
                    ("read_url, page.md of a long page", res4), ("read_url(url=\"probe:7900\")", pr79)):
        check("MCP %s: the whole result as Cline counts it (its JSON) within 7 900 characters" % name,
              cline_form(r) <= CHARS and u16(mcp_said(r)) > 3000,
              "%d characters as JSON, %d of text" % (cline_form(r), u16(mcp_said(r))))
    check("... a page of short lines gives up no more of its block than JSON's escapes take",
          u16(mcp_said(sl)) > CHARS - mcp_said(sl).count("\n") - 400, "%d characters of text, %d lines" % (
              u16(mcp_said(sl)), mcp_said(sl).count("\n")))

    # a probe for measuring what a harness shows, no network (KNOWN-ISSUES 268): N characters of numbered lines,
    # outside the answer's block; probe:N read as an address is a page of them, for --from and --to
    e = dict(os.environ, READ_PAGE_CACHE=tempfile.mkdtemp(prefix="rp-probe-"))
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, "--probe", "8000"], capture_output=True, timeout=120, env=e)
    out = p.stdout.decode("utf-8", "replace")
    rows = out.split("\n")[:-1]
    check("--probe 8000: 8 000 characters of numbered lines, ASCII, LF, nothing else, exit 0",
          p.returncode == 0 and len(p.stdout) == 8000 and out.isascii() and b"\r" not in p.stdout and p.stderr == b""
          and len(rows) == 80 and not out.startswith("read-page"), "rc %s, %d bytes, %d lines, stderr %r" % (
              p.returncode, len(p.stdout), len(rows), p.stderr[:80]))
    check("... each line its number and the characters before it, a head and a tail sentinel",
          rows and rows[0].startswith("PROBE HEAD: line 1, 0 characters before it, 8000 characters in 80 lines")
          and rows[-1].startswith("PROBE TAIL: line 80, 7900 characters before it, the last of 8000")
          and all(r.startswith("line %d, %d characters before it" % (k, (k - 1) * 100)) and len(r) == 99
                  for k, r in enumerate(rows[1:-1], 2)), (rows[:1] + rows[-1:]) if rows else out[:80])
    bad = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, "--probe", "lots"], capture_output=True, timeout=120,
                         env=e)
    check("--probe with no number: exit 2, the reason on stderr", bad.returncode == 2 and b"--probe" in bad.stderr,
          "rc %s %r" % (bad.returncode, bad.stderr[:80]))
    page_r = run_read("probe:20000")
    fits("probe:20000", page_r)
    check("probe:N read as an address: the answer any page has, its text the probe's",
          first_line(page_r).startswith("read-page · ok · probe · content.md ") and page_r.file("content.md") == \
          answer.probe(20000) and next_line(page_r.text) is not None, first_line(page_r)[:90])
    sized = run_read("probe:20000", "--from", "21", "--chars", "12000", reuse=page_r)
    n_s = next_line(sized.text)
    check("probe:N with --from and --chars: the lines from 21, whole, within 12 000 characters",
          n_s and body(sized.text) == answer.probe(20000).split("\n")[20:n_s - 1] and u16(sized.text) <= 12000
          and n_s - 21 > 100, "lines 21-%s, %d characters" % (n_s and n_s - 1, u16(sized.text)))
    raw = mcp({"url": "probe", "probe": 8000})
    check("MCP read_url(probe=N): the same N characters, nothing else",
          [b.get("text") for b in raw["content"]] == [answer.probe(8000)] and not raw.get("isError"),
          str(sorted(raw))[:90])
    pr = mcp({"url": "probe:20000", "from": 21, "chars": 12000})
    n_p = next_line(mcp_said(pr))
    check("MCP read_url(url=\"probe:N\", from, chars): the lines from 21, as Cline counts them within 12 000",
          n_p and body(mcp_said(pr)) == answer.probe(20000).split("\n")[20:n_p - 1] and cline_form(pr) <= 12000
          and n_p - 21 > 100, "lines 21-%s, %d characters as JSON" % (n_p and n_p - 1, cline_form(pr)))

    # the probe that tells the units apart (KNOWN-ISSUES 268): ASCII alone makes characters, UTF-16 units and bytes
    # one count, so it cannot show which of them a harness counts - and for a Russian or a Chinese answer that is
    # the question. Each line says how many of the three stand before it; its filler is ASCII, Cyrillic (2 bytes),
    # CJK (3 bytes) or a character past U+FFFF (2 units, 4 bytes), by the line's number.
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, "--probe-units", "8000"], capture_output=True, timeout=120,
                       env=e)
    out = p.stdout.decode("utf-8", "replace")
    rows = out.split("\n")[:-1]
    check("--probe-units 8000: 8 000 characters in lines of 100, LF, UTF-8, nothing else, exit 0",
          p.returncode == 0 and len(out) == 8000 and b"\r" not in p.stdout and p.stderr == b"" and len(rows) == 80
          and all(len(r) == 99 for r in rows) and "�" not in out and not out.startswith("read-page"),
          "rc %s, %d characters, %d bytes, %d lines, stderr %r" % (p.returncode, len(out), len(p.stdout), len(rows),
                                                               p.stderr[:80]))
    check("... the filler is ASCII, Cyrillic, CJK and a character past U+FFFF, so the three counts differ",
          len(out) < u16(out) < len(p.stdout) and any(0x400 <= ord(c) < 0x500 for c in out)
          and any(0x4e00 <= ord(c) < 0xa000 for c in out) and any(ord(c) > 0xFFFF for c in out),
          "%d characters, %d units, %d bytes" % (len(out), u16(out), len(p.stdout)))
    want_rows, seen = [], [0, 0, 0]
    for k, r in enumerate(rows, 1):
        m = re.match(r"(?:UNITS HEAD \| |UNITS TAIL \| )?line (\d+) \| (\d+) chars (\d+) utf16 (\d+) bytes before", r)
        want_rows.append(bool(m) and tuple(int(x) for x in m.groups()) == (k, seen[0], seen[1], seen[2]))
        seen = [seen[0] + len(r) + 1, seen[1] + u16(r) + 1, seen[2] + len(r.encode("utf-8")) + 1]
    check("... each line says its number and how many characters, UTF-16 units and bytes stand before it, and it is right",
          want_rows and all(want_rows), "%d of %d lines right; %s" % (sum(want_rows), len(rows), (rows[:1] or [""])[0][:60]))
    check("... a head and a tail sentinel; the tail says the whole length",
          rows and rows[0].startswith("UNITS HEAD | line 1 | 0 chars 0 utf16 0 bytes before | 8000 chars in 80 lines ")
          and rows[-1].startswith("UNITS TAIL | line 80 | 7900 chars ") and " bytes before | 8000 chars " in rows[-1],
          (rows[:1] + rows[-1:])[0][:90] if rows else out[:80])
    fillers = [(re.match(r"(?:UNITS \w+ \| )?line \d+ \| \d+ chars \d+ utf16 \d+ bytes before (?:\| .*? )?(\S+)$", r) or [0, ""])[1]
               for r in rows[:4]]
    check("... the filler of lines 1 to 4 is ASCII, Cyrillic, CJK and a character past U+FFFF, one kind to a line",
          len(fillers) == 4 and fillers[0].isascii() and all(0x400 <= ord(c) < 0x500 for c in fillers[1])
          and all(0x4e00 <= ord(c) < 0xa000 for c in fillers[2]) and all(ord(c) > 0xFFFF for c in fillers[3])
          and all(fillers), [f[:3] for f in fillers])
    for n, why in ((0, "nothing"), (7, "a line shorter than its label"), (150, "one line"), (199, "one line, the longest")):
        q = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, "--probe-units", str(n)], capture_output=True,
                           timeout=120, env=e).stdout.decode("utf-8", "replace")
        check("--probe-units %d: exactly %d characters, %s" % (n, n, why),
              len(q) == n and q.count("\n") == (1 if n else 0), "%d characters %r" % (len(q), q[:30]))
    big = answer.probe_units(10 ** 7)
    last_row = big.rsplit("\n", 2)[-2]
    check("--probe-units at its largest (10 000 000): exactly that many characters, the tail sentinel whole",
          len(big) == 10 ** 7 and last_row.startswith("UNITS TAIL | line 100000 | ") and " bytes before | 10000000 chars " in last_row,
          last_row[:110])
    bad = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, "--probe-units", "lots"], capture_output=True, timeout=120,
                         env=e)
    check("--probe-units with no number: exit 2, the reason on stderr", bad.returncode == 2 and b"--probe-units" in bad.stderr,
          "rc %s %r" % (bad.returncode, bad.stderr[:80]))
    ru = mcp({"url": "probe", "probe_units": 8000})
    check("MCP read_url(probe_units=N): the same N characters, nothing else",
          [b.get("text") for b in ru["content"]] == [answer.probe_units(8000)] and not ru.get("isError")
          and out == answer.probe_units(8000), str(sorted(ru))[:90])
    # the manifest is a file, never a part of the result: a client that shows the model structuredContent counted it
    # against its limit (Cline) or showed it instead of the text (KNOWN-ISSUES 275)
    with_sc = [name for name, r in results if "structuredContent" in r]
    check("MCP: no result carries structuredContent - read_url, read, from=N and text, to, a quote not found, page.md, "
          "the probe, an error (%d results)" % len(results), results and not with_sc, str(with_sc[:3]))
    check("... each is its blocks and isError, nothing else", all(sorted(r) == ["content", "isError"] for _, r in results),
          str(sorted({tuple(sorted(r)) for _, r in results}))[:120])
    shutil.rmtree(e["READ_PAGE_CACHE"], ignore_errors=True)
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

# SKILL.md's answer is the answer's own (KNOWN-ISSUES 276, 277): its example ends with the next: line and the
# command under it, as an answer does; it names --chars and EOF, the way back from a cut, and no --to
with open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8") as fh_:
    skill = fh_.read()
example = re.search(r"(?s)```\nread-page · ok · .*?\n```", skill)
ex_rows = example.group(0).split("\n")[1:-1] if example else []
check("SKILL.md's example answer ends as an answer does: `── next: line N of T ──`, then the command alone",
      len(ex_rows) >= 2 and re.match(r"── next: line (\d+) of \d+ ──$", ex_rows[-2]) is not None
      and re.match(r'python -X utf8 "SKILL_DIR/scripts/readpage\.py" URL .*--from %s --chars 7900 --file content\.md$'
                   % re.match(r"── next: line (\d+)", ex_rows[-2]).group(1), ex_rows[-1]) is not None
      if len(ex_rows) >= 2 and ex_rows[-2].startswith("── next: line ") else False, str(ex_rows[-2:])[:160])
rest = " ".join(next((p for p in skill.split("\n- ") if p.startswith("The rest of a long text")), "").split())
# after a cut, the last size that came back whole (KNOWN-ISSUES 280): under Cline's middle cut next: survives and
# repeats the size that was cut, and "about half the --chars" kept a model above the cut (half of 20 000 is 10 000);
# the words of that rule, here once for both checks
WHOLE_AGAIN = ("that came back whole", "(7 900, the default, if none did)", "keep that size for the rest")
check("SKILL.md: the rest of a text is the command under next:, EOF its end, --chars its size; after a cut the last "
      "--chars that came back whole, 7 900 if none did (KNOWN-ISSUES 280)",
      all(w in rest for w in ("`next:`", "`EOF`", "`--chars`", "20 000", "--from \"<words of the last line")
          + WHOLE_AGAIN) and "half" not in rest and "--to" not in skill, rest[:120])
import mcp_server                                              # noqa: E402
read_says = " ".join(next((t["description"] for t in mcp_server.TOOLS if t["name"] == "read"), "").split())
check("the MCP read tool's description says the same of a cut: the last chars that came back whole (KNOWN-ISSUES 280)",
      all(w in read_says for w in WHOLE_AGAIN) and "half" not in read_says, read_says[-160:])

sys.exit(check.done())
