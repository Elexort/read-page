"""The answer an agent reads in one call: a header, then the text, inside the smallest output limit
any harness enforces.

The harnesses' own code, read 2026-11-26: Cline's SDK runtime (its CLI, and the VS Code windows on
that bundle) cuts every tool result, MCP too, at 8 000 characters - UTF-16 units, as JavaScript
counts - keeping about 3 985 at each end; Codex with a model outside its OpenAI catalogue passes
10 000 bytes of stdout and stderr together, Roo Code 10 240; Cline's VS Code extension shows 500
lines. Past that every harness cuts in its own way (the head, the tail, the middle, or just a path
to a file). So one answer is at most BUDGET_CHARS characters, BUDGET_BYTES bytes and BUDGET_LINES
lines, counted on what is written: UTF-8 with LF; the characters leave Cline room for a line of
its own. English text meets the characters first (a 9 980-byte block lost about 2 000 characters
from its middle in Cline), Cyrillic and CJK text the bytes. A text that fits is printed whole. A
longer one gets an outline with line numbers first, then its beginning up to the limit, cut at a
paragraph, and the exact line where it goes on; continuing from that line prints the next block of
the same size. `--chars C` (MCP's chars) sets the size for a tool that shows more: C characters, the bytes and
the lines in the same ratio (limits), at least CHARS_MIN, at which the longest line stays whole.
"""
import os
import re
import tempfile

import pictures

BUDGET_CHARS = 7900    # Cline's 8 000 per tool result, less room for its own marker
BUDGET_BYTES = 9980
BUDGET_LINES = 495
OUTLINE_BYTES = 2500
OUTLINE_MIN = 12       # an outline coarser than this, finer headings below it: those, thinned
LINE_CHARS = 1998      # the Read tools of OpenCode, Kilo Code, Cline, Crush, Gemini CLI and Qwen Code stop
                       # a line at 2 000 characters; "\r\n" fits too
LINE_BYTES = 6000      # keeps every line inside one block even with the outline above it
POINTER_BYTES = 200    # the separator above the text and the pointer below it (characters too)
# --chars C: the least an answer holds - where the longest line content.md has (LINE_CHARS, LINE_BYTES of Chinese)
# always stands whole beside the header and the command under next:, measured 2026-11-28 with a header of its longest
# rows (a redirect's url:, a 400-character advice, missing: and improve:, outside the text:) under a 200-character
# folder, a 150-character script path and a 200-character address: 6 900 (5 800 with the plain header, 3 300 for an
# English text). Below it such a line was shown in part and next: went past its rest (KNOWN-ISSUES 295)
CHARS_MIN = 7000
CHARS_MAX = 150000     # and the most - the most a harness shows (Claude Code with its limit raised)
OUTSIDE_SHOWN = 1024   # less than this outside the text (a footer line) is not worth a header row
PROBE_LINE = 100       # characters a probe line takes, its "\n" too
PROBE_MAX = 10000000   # characters a probe prints at most

_SENTENCE_END = re.compile(r"[.!?…](?=\s)|[。！？]")     # CJK full stops need no space after
_SPACE = re.compile(r"\s")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def probe(n):
    """`readpage.py --probe N`: N characters of numbered lines and nothing else, for measuring what a harness
    shows of a command's output or of a tool's result - no network, outside the answer's block. Each line says
    its number and how many characters stand before it, the first and the last are sentinels, and a line is
    PROBE_LINE characters (the last 100 to 199): what a harness cut shows as the lines and numbers missing, and
    a line cut in its middle still names itself. ASCII alone, so its characters, bytes and UTF-16 units are one
    count. `probe:N` read as an address is a page of the same text (readpage.probe_page)."""
    n = max(0, min(int(n), PROBE_MAX))
    if n < 2 * PROBE_LINE:
        return ("PROBE HEAD AND TAIL: %d characters in one line " % n + "." * n)[:max(0, n - 1)] + ("\n" if n else "")
    last = (n - PROBE_LINE) // PROBE_LINE + 1
    out = []
    for k in range(1, last + 1):
        at = (k - 1) * PROBE_LINE
        width = PROBE_LINE if k < last else n - at
        if k == 1:
            words = "PROBE HEAD: line 1, 0 characters before it, %d characters in %d lines" % (n, last)
        elif k == last:
            words = "PROBE TAIL: line %d, %d characters before it, the last of %d" % (k, at, n)
        else:
            words = "line %d, %d characters before it" % (k, at)
        out.append((words + " " + "." * width)[:width - 1] + "\n")
    return "".join(out)


PROBE_FILLER = ("-", "ж", "字", "\U0001f600")   # ASCII; Cyrillic, 2 bytes; CJK, 3 bytes; past U+FFFF, 2 units and 4 bytes


def probe_units(n):
    """`readpage.py --probe-units N`: the probe that tells the units apart. `probe` is ASCII, so its characters,
    UTF-16 units and bytes are one count and it cannot show which of them a harness counts - and for a Russian or a
    Chinese answer that is the question (Cline counts UTF-16 units, Codex bytes). N characters again, in lines of
    PROBE_LINE; each line's label says its number and how many characters, UTF-16 units and bytes stand before it,
    and its filler is of one kind by the line's number - 1 ASCII, 2 Cyrillic, 3 CJK, 4 past U+FFFF, then again -,
    so the three counts drift apart line by line. The last line a harness shows and where it cut that line give the
    three counts at the cut: the one that comes to the harness's limit is the one it counts."""
    n = max(0, min(int(n), PROBE_MAX))
    if n < 2 * PROBE_LINE:
        return ("UNITS HEAD AND TAIL | %d chars in one line " % n + "".join(PROBE_FILLER) * n)[:max(0, n - 1)] \
            + ("\n" if n else "")
    last = (n - PROBE_LINE) // PROBE_LINE + 1
    out, chars, units, size = [], 0, 0, 0
    for k in range(1, last + 1):
        width = PROBE_LINE if k < last else n - chars
        where = "line %d | %d chars %d utf16 %d bytes before" % (k, chars, units, size)
        if k == 1:
            where = "UNITS HEAD | %s | %d chars in %d lines" % (where, n, last)
        elif k == last:
            where = "UNITS TAIL | %s | %d chars" % (where, n)
        line = (where + " " + PROBE_FILLER[(k - 1) % 4] * width)[:width - 1] + "\n"
        out.append(line)
        chars += len(line)
        units += u16(line)
        size += len(line.encode("utf-8"))
    return "".join(out)


def limits(chars=None):
    """answer.render's keywords for an answer of `chars` characters (--chars C, MCP's chars): the bytes and the lines
    in the default's ratio, so that none asked is BUDGET_CHARS, BUDGET_BYTES and BUDGET_LINES exactly."""
    c = BUDGET_CHARS if chars is None else int(chars)
    return {"chars": c, "budget": c * BUDGET_BYTES // BUDGET_CHARS, "max_lines": c * BUDGET_LINES // BUDGET_CHARS}


def chars_asked(raw):
    """(the characters an answer holds, why that is not the value asked for - "" when it is): --chars C or MCP's
    chars, clamped to CHARS_MIN .. CHARS_MAX; a value that is no number is the default."""
    if raw is None or isinstance(raw, bool) or str(raw).strip() == "":
        return BUDGET_CHARS, ""
    try:
        c = int(raw) if isinstance(raw, (int, float)) else int(str(raw).strip())
    except (ValueError, OverflowError):
        return BUDGET_CHARS, "a number of characters: %d used" % BUDGET_CHARS
    if c < CHARS_MIN:
        return CHARS_MIN, "%d at the least: %d used" % (CHARS_MIN, CHARS_MIN)
    if c > CHARS_MAX:
        return CHARS_MAX, "%d at the most: %d used" % (CHARS_MAX, CHARS_MAX)
    return c, ""


def _u16_slice(s, start, end=None):
    """s by UTF-16 units, as JavaScript slices a string: a pair a bound falls inside loses its half."""
    data = s.encode("utf-16-le", "surrogatepass")
    part = data[2 * start:] if end is None else data[2 * start:2 * end]
    return part.decode("utf-16-le", "ignore")


def harness_cut(out, spec=None, folder=None):
    """READ_PAGE_TEST_CUT, a hook for testing the skill (references/answer.md, For testing the skill): an answer cut
    after it is built the way a harness cuts what a command printed, so that a model can be taught to go on under each
    cut. `middle:N` Cline's SDK runtime: over N UTF-16 units, about half of N kept at each end and
    `...[truncated K chars]...` between (its truncateMiddleByChars); `head:N` Zed: over N bytes, "Command output too
    long. The first K bytes:" and those bytes, cut at a line's end; `tail:N` OpenCode: over N bytes, a
    `...output truncated...` line and the last N bytes from a line's start; `file:N` Claude Code: over N bytes the
    whole answer in a file - in the page's `folder`, which the cache's prune takes with it (one in the temp folder for
    each cut was left there: KNOWN-ISSUES 300), else in the temp folder - and a note naming it with its first 2 000
    characters. An answer under N, or a value that names no cut, is returned as it is. `spec` None: the environment's."""
    spec = os.environ.get("READ_PAGE_TEST_CUT", "") if spec is None else spec
    m = re.match(r"\s*(middle|head|tail|file)\s*:\s*(\d+)\s*$", spec or "")
    if not m or not out:
        return out
    kind, n = m.group(1), int(m.group(2))
    data = out.encode("utf-8")
    if kind == "middle":
        total = u16(out)
        if total <= n:
            return out
        marker = "\n\n...[truncated %d chars]...\n\n"
        keep = max(0, (n - len(marker % (total - n))) // 2)
        removed = max(0, total - 2 * keep)
        keep = max(0, (n - len(marker % removed)) // 2)
        return _u16_slice(out, 0, keep) + marker % removed + (_u16_slice(out, total - keep) if keep else "")
    if len(data) <= n:
        return out
    if kind == "head":
        part = data[:n]
        part = part[:part.rfind(b"\n") + 1] or part
        return "Command output too long. The first %d bytes:\n\n%s" % (len(part), part.decode("utf-8", "ignore"))
    if kind == "tail":
        part = data[-n:]
        nl = part.find(b"\n")
        part = part[nl + 1:] if 0 <= nl < len(part) - 1 else part
        return "...output truncated...\n\n" + part.decode("utf-8", "ignore")
    fd, path = tempfile.mkstemp(prefix="read-page-cut-", suffix=".txt",
                                dir=folder if folder and os.path.isdir(folder) else None)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(out)
    return "Output too large (%.1fKB). Full output saved to: %s\n\nPreview (first 2KB):\n%s\n...\n" % (
        len(data) / 1024.0, path, out[:2000])


def _too_long(line):
    return len(line) > LINE_CHARS or len(line.encode("utf-8")) > LINE_BYTES


def _limit(line):
    """How many characters fit one line: LINE_CHARS, fewer when they would pass LINE_BYTES."""
    size = 0
    for i, ch in enumerate(line[:LINE_CHARS]):
        size += len(ch.encode("utf-8"))
        if size > LINE_BYTES:
            return i
    return min(len(line), LINE_CHARS)


def _cut_at(line, limit):
    """Where a too long line is cut: after the last sentence end that fits, else at the last
    space, else exactly at the limit. Leading indentation is never a piece of its own."""
    first = len(line) - len(line.lstrip())
    end = 0
    for m in _SENTENCE_END.finditer(line, first, limit + 1):      # +1: the space may follow
        if m.end() <= limit:
            end = m.end()
    if end:
        return end
    for m in _SPACE.finditer(line, first + 1, limit + 1):
        end = m.start()
    return end or limit


def split_long_lines(text):
    """Lines longer than LINE_CHARS (or LINE_BYTES) become several; nothing is dropped.

    A pointer "go on from line N" has to work in every reader, and some readers silently drop the
    rest of a long line. Such a line is usually how the site lays its text out (one paragraph,
    a table row, a code line), so every piece is kept: the cut only replaces the whitespace at
    the cut, if any, with a line break. Markdown reads the pieces of a paragraph as one paragraph.
    """
    out = []
    for line in (text or "").split("\n"):
        if not _too_long(line):
            out.append(line)
            continue
        while _too_long(line):
            cut = _cut_at(line, _limit(line))
            piece, line = line[:cut].rstrip(), line[cut:].lstrip()
            if piece:
                out.append(piece)
        if line:
            out.append(line)
    return "\n".join(out)


def _bytes(rows):
    return sum(len(r.encode("utf-8")) + 1 for r in rows)


def u16(s):
    """Characters as Cline counts them: UTF-16 units, so a character past U+FFFF (an emoji) is two."""
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def _chars(rows):
    return sum(u16(r) + 1 for r in rows)


def _fits(out, budget, chars, max_lines):
    return len(out.encode("utf-8")) <= budget and u16(out) <= chars and out.count("\n") <= max_lines


def headings(lines):
    """(line number from 1, level, title) of every Markdown heading outside code fences."""
    out, fence = [], False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        m = None if fence else _HEADING.match(line)
        if m:
            out.append((i, len(m.group(1)), re.sub(r"\s+", " ", m.group(2))[:90]))
    return out


def window(lines, start, byte_budget, line_budget, char_budget=None):
    """Index after the last line of the block that starts at `start` (both from 1).

    The block takes whole lines while they fit its bytes, lines and characters, then steps back to
    the last blank line in its second half, so it ends between paragraphs. It always takes at least
    one line.
    """
    end, used, used_c = start, 0, 0
    while end <= len(lines) and end - start < line_budget:
        size = len(lines[end - 1].encode("utf-8")) + 1
        size_c = u16(lines[end - 1]) + 1 if char_budget is not None else 0
        if (used + size > byte_budget or (char_budget is not None and used_c + size_c > char_budget)) \
                and end > start:
            break
        used += size
        used_c += size_c
        end += 1
    if end <= len(lines):
        for i in range(end - 1, start + (end - start) // 2, -1):
            if not lines[i - 1].strip():
                return i + 1
    return end


def _thinned(rows, budget, keep=()):
    """Rows that do not all fit: every k-th, the last one and `keep` always, the smallest k that
    fits with a closing note. Spread evenly, the outline still reaches the end of the text."""
    n = len(rows)
    for k in range(2, n + 1):
        idx = sorted(set(range(0, n, k)) | {n - 1} | set(keep))
        out = [rows[i] for i in idx] + ["      … %d more between these" % (n - len(idx))]
        if _bytes(out) <= budget:
            return out
    return [rows[-1], "      … %d more before this" % (n - 1)]


def outline(lines, budget, block_starts):
    """Rows for the outline: headings with their line numbers, as many levels as fit the budget.

    When the levels that fit give fewer than OUTLINE_MIN rows and finer headings exist (a book's
    title over its 60 chapters), the next level down is listed thinned evenly, so a jump lands
    near any part of the text; a list too long even at the top level is thinned the same way.
    Without headings the outline is one row per block of the answer size, with the block's first
    words, so the agent can still jump instead of reading everything in order.
    """
    hs = headings(lines)
    if len(hs) >= 2:
        def row(h):
            return "%7d %s %s" % (h[0], "#" * h[1], h[2])
        for top in (6, 3, 2, 1):
            rows = [row(h) for h in hs if h[1] <= top]
            if _bytes(rows) <= budget:
                finer = [h[1] for h in hs if h[1] > top]
                if len(rows) >= OUTLINE_MIN or not finer:
                    return rows
                below = min(finer)
                sel = [h for h in hs if h[1] <= below]
                return _thinned([row(h) for h in sel], budget, {i for i, h in enumerate(sel) if h[1] <= top})
        return _thinned([row(h) for h in hs if h[1] == min(x[1] for x in hs)], budget)
    rows = []
    for n in block_starts:
        words = re.sub(r"\s+", " ", lines[n - 1]).strip()[:70] if n <= len(lines) else ""
        rows.append("%7d %s" % (n, words or "…"))
    return rows if _bytes(rows) <= budget else _thinned(rows, budget)


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def header(manifest, view, total_lines, text_bytes):
    """The lines above the text: what the answer is, where its files are, what to do next."""
    m = manifest or {}
    content = m.get("content") or {}
    signals = m.get("signals") or {}
    first = ["read-page", m.get("status") or "error"]
    if content.get("engine"):
        engine = str(content["engine"])
        if content.get("source") == "browser":
            engine += " (browser)"                          # the text is the browser's page's (KNOWN-ISSUES 330)
        elif content.get("source") == "server":
            engine += " (server; browser's text no better)"  # the browser ran, and its text was no fuller
        if content.get("restored"):
            # blocks the extractor dropped and the text got back from page.md
            engine += " + %d block%s of page.md" % (content["restored"], "" if content["restored"] == 1 else "s")
        first.append(engine)
        if signals.get("fragment") and signals.get("paywall"):
            # a paywall's teaser beside the site's menus: page.md has no more of the article (the block rule put
            # back every paragraph the extractor dropped), and its next: line led a model on through the menus
            first.append("paywalled: the rest of the article is not in the page")
        elif signals.get("fragment"):
            # the share only where it decides something: a text under a third of the page's words. On a
            # whole text "49% of the page" read as "half the content", and an agent kept re-reading
            # (menus, links and footers make the rest); content.cover keeps it in the manifest
            cover = content.get("cover")
            first.append("maybe a fragment: the text is %d%% of the page's words" % min(100, int(round(cover * 100)))
                         if isinstance(cover, (int, float)) else "maybe a fragment")
        if content.get("track"):
            first.append(str(content["track"]))     # a video's subtitle track: human, automatic or machine-translated
    stamp = str((m.get("archive") or {}).get("timestamp") or "")
    if stamp:
        first.append("archive copy of %s-%s-%s" % (stamp[:4], stamp[4:6], stamp[6:8]) if len(stamp) >= 8
                     else "archive copy")
    guess = str(signals.get("charset_guess") or "")
    if guess:
        # the page named no encoding and the text was read by a guess: the reader of the answer may need to know
        first.append("charset %s" % (guess.replace(" (doubtful)", "") + (" (guessed, doubtful)" if "(doubtful)" in guess
                                                                          else " (guessed)")))
    first.append("%s %s, %d line%s" % (view, _human(text_bytes), total_lines, "" if total_lines == 1 else "s"))
    if m.get("cache") in ("hit", "revalidated"):
        first.append("from cache" if m["cache"] == "hit" else "from cache, revalidated")
    if signals.get("partial"):
        first.append("partial")
    if m.get("elapsed_ms") is not None:
        first.append("%.1f s" % (m["elapsed_ms"] / 1000.0))
    rows = [" · ".join(first)]
    url = m.get("url") or {}
    final, asked = url.get("final") or "", url.get("requested") or url.get("input") or ""
    if final and final != asked:
        rows.append("url: " + final[:300])
    if m.get("status") not in (None, "ok") and signals.get("status_reason"):
        rows.append("reason: " + str(signals["status_reason"])[:300])
    if m.get("dir"):
        # only what is on disk: a too_large answer has no page.md, a media file has its own name
        files = m.get("files") or {}
        names = [n for k, n in (("content", "content.md"), ("page", "page.md")) if files.get(k)]
        for k in ("media", "raw"):
            if files.get(k) and (k == "media" or not names):
                names.append(os.path.basename(str(files[k])))
                break
        names.append("manifest.json")
        on_disk = [e for e in (m.get("images") or []) if isinstance(e, dict) and e.get("file")]
        if on_disk:
            names.append("img/ %d picture%s" % (len(on_disk), "" if len(on_disk) == 1 else "s"))
        denied = signals.get("images_denied")
        if denied:
            names.append("%s not downloaded" % ("%d picture%s" % (denied, "" if denied == 1 else "s")
                                                if type(denied) is int else "pictures"))
        if m.get("screenshots"):
            names.append("shots/ %d" % len(m["screenshots"]))
        rows.append("files: %s (%s)" % (m["dir"], ", ".join(names)))
    if view == "content.md" and (content.get("outside") or 0) >= OUTSIDE_SHOWN:
        # what only page.md has after the dropped blocks came back: menus, link lists, fragments
        rows.append("outside the text: %s of menus, links and fragments - page.md" % _human(content["outside"]))
    if m.get("ignored"):
        # flags of this call that are not ours: left out, the read went on (a model invented a `--to`)
        rows.append(("ignored: " + " · ".join(str(x) for x in m["ignored"]))[:300])
    if signals.get("env_failed"):
        # the environment's Python started and failed: this read ran in the machine's
        rows.append(("environment: " + str(signals["env_failed"]))[:300])
    if signals.get("document_note"):
        # what the document's reader says it left out or could not read (it was `missing: converter`)
        rows.append(("document: " + str(signals["document_note"]))[:300])
    if signals.get("screenshots_failed"):
        # --screenshots took no picture, or stopped early: the step that failed and what it said
        rows.append(("screenshots: %s - %s" % ("stopped early" if m.get("screenshots") else "none taken",
                                               signals["screenshots_failed"]))[:300])
    o = m.get("ocr")
    if isinstance(o, dict):
        # --ocr N: which picture, read how - or why it has no text here
        parts = [("img #%s " % o["n"] if o.get("n") else "") + str(o.get("file") or "")] if o.get("file") else []
        if o.get("why"):
            parts.append(str(o["why"]))
        else:
            parts += [x for x in (o.get("engine"), o.get("langs"), o.get("pass") and "%s pass" % o["pass"]) if x]
            parts.append("%.1f s" % float(o.get("seconds") or 0))
            if o.get("note"):
                parts.append(str(o["note"]))               # a language pack the text called for and this machine lacks
        rows.append(("ocr: " + " · ".join(p.strip() for p in parts))[:300])
    if m.get("advice"):
        rows.append("advice: " + str(m["advice"])[:400])
    # what the machine lacks, then what would read better: two lines at most, on every answer
    gaps = [("missing", i) for i in (m.get("missing") or []) if isinstance(i, dict) and i.get("what")]
    better = [i for i in (m.get("improve") or []) if isinstance(i, dict) and i.get("what")]
    gaps += [("improve", i) for i in sorted(better, key=lambda i: not i.get("recommended"))]
    for word, item in gaps[:2]:
        rows.append(("%s: %s%s%s" % (word, item["what"], " (%s)" % item["gain"] if item.get("gain") else "",
                                     " - " + item["fix"] if item.get("fix") else ""))[:300])
    return rows


# an element's marker, `[tab · hidden, but extracted · 6.0 KB, ... · Go]`: its type, then its state, what more
# there is to say, its name last (tabs.py, and a cut workbook's rows and sheets)
ELEMENT = re.compile(r"\[(tab|section|select|rows|sheet) · ([^\]\n]*)\]")


def _plain(s):
    """A line as a quote is matched against it: a marker is its type and name alone (a picture its number),
    whitespace folded - so `[tab · Developer Plan Limits]` finds the marker whatever its state says."""
    if "[" in s:
        s = pictures.MARK.sub(lambda m: "[img #%s]" % m.group(1), s)
        s = ELEMENT.sub(lambda m: "[%s · %s]" % (m.group(1), m.group(2).split(" · ")[-1].strip()), s)
    return " ".join(s.split())


def _first(rows, want, after):
    """(the first line at or after `after` that holds `want`, the first line that holds it): line numbers or
    None, from (number, text) pairs in order; stops at the first line at or after `after`."""
    first = None
    for i, x in rows:
        if want in x:
            if first is None:
                first = i
            if i >= after:
                return i, first
    return None, first


def _earliest(*numbers):
    got = [n for n in numbers if n is not None]
    return min(got) if got else None


def find(lines, quote, after=1):
    """The line a quote starts at (`--from "text"`), from 1, or None: the first line holding it - whitespace
    folded, then without case -, the first at or after `after` (where the last answer of the page started)
    when there are several. A quote cut in the middle of a line matches; one of several lines is looked for
    by its first, when it is not found whole. A marker is matched twice: by its type and name (_plain) and as
    it stands, so a quote that ends inside a marker - what an agent has when its harness cut the answer in
    the middle of a picture's or a tab's line - is found too."""
    texts = [str(quote)]
    rows = [r for r in str(quote).split("\n") if r.strip()]
    if len(rows) > 1:
        texts.append(rows[0])
    after = after or 1
    plain = folded = alt = alt_folded = None
    for text in texts:
        want, raw = _plain(text), " ".join(text.split())
        if not want:
            continue
        if plain is None:
            plain = [_plain(x) for x in lines]
            # the lines that hold a marker, as they stand: the only ones whose two forms differ
            alt = {i: r for i, r in ((i, " ".join(x.split())) for i, x in enumerate(lines, 1) if "[" in x)
                   if r != plain[i - 1]}
        # where the reading is first: an agent goes on from its own place, a retyped quote may differ in case
        hit = _first(enumerate(plain, 1), want, after), _first(alt.items(), raw, after)
        if hit[0][0] or hit[1][0]:
            return _earliest(hit[0][0], hit[1][0])
        if folded is None:
            folded = [x.casefold() for x in plain]
            alt_folded = {i: x.casefold() for i, x in alt.items()}
        loose = _first(enumerate(folded, 1), want.casefold(), after), _first(alt_folded.items(), raw.casefold(), after)
        if loose[0][0] or loose[1][0]:
            return _earliest(loose[0][0], loose[1][0])
        for first in (_earliest(hit[0][1], hit[1][1]), _earliest(loose[0][1], loose[1][1])):
            if first is not None:
                return first
    return None


def not_found(manifest, text, view, quote, budget=BUDGET_BYTES, max_lines=BUDGET_LINES, chars=BUDGET_CHARS):
    """`--from "text"` that no line holds: the answer says so and shows the outline, whose line numbers
    `--from N` takes; inside the answer's size (render's keywords)."""
    lines = (text or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    head = header(manifest, view, len(lines), len((text or "").encode("utf-8")))
    q = " ".join(str(quote).split())
    try:
        q = q.encode("utf-8", "surrogateescape").decode("utf-8", "replace")     # bytes of another code set: U+FFFD
    except UnicodeError:
        q = q.encode("utf-8", "replace").decode("utf-8")
    q = q if len(q) <= 80 else q[:79] + "…"
    say = ['── not in %s: "%s", spaces and case aside; the outline below names its lines for --from N ──' % (view, q)]
    room = max(0, min(OUTLINE_BYTES * 2, (budget - _bytes(head + say)) // 2, (chars - _chars(head + say)) // 2))
    starts, n = [], 1
    while n <= len(lines):
        starts.append(n)
        n = window(lines, n, budget - _bytes(head) - POINTER_BYTES, max(1, max_lines - len(head) - 3),
                   chars - _chars(head) - POINTER_BYTES)
    rows = outline(lines, room, starts) if lines else []
    return "\n".join(head + say + (["outline (line, heading):"] + rows if rows else [])) + "\n"


def _lines(view, first, total):
    """The line above an answer's text: where in which file it starts, and no end. A harness that keeps an answer's
    head and cuts its tail (Zed) cuts `next:` off and leaves this line, and a model took the end it named for the end
    of what it had seen (KNOWN-ISSUES 279): the end is named in `next:` and in EOF alone."""
    return "── %s: from line %d of %d ──" % (view, first, total)


def _eof(view, first, last, total):
    """The last line of the answer the text ends in: the end, and the lines this answer held."""
    return "── EOF %s: lines %d-%d of %d ──" % (view, first, last, total)


def render(manifest, text, view, start, next_hint, budget=BUDGET_BYTES, max_lines=BUDGET_LINES, chars=BUDGET_CHARS):
    """The whole answer as one string, and the line the next block starts at (None at the end).

    `next_hint(n, total, view)` words the pointer for the caller while text remains: `── next: line N of T ──` and
    on a line of its own the command or the MCP call that reads on. `budget`, `max_lines` and `chars` are the
    answer's size in bytes, lines and characters (limits: --chars C sets all three). The lines around the text are
    dry: above it `── content.md: from line A of T ──`, every block alike, no end (KNOWN-ISSUES 279); the last
    block's last line `── EOF content.md: lines A-T of T ──` (KNOWN-ISSUES 276).
    """
    lines = (text or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines)
    start = max(1, int(start or 1))
    head = header(manifest, view, total, len((text or "").encode("utf-8")))
    if start > 1 and (manifest or {}).get("cache") not in ("hit", "revalidated"):
        # a continuation is meant to read the copy the first answer came from; this one had
        # to read the page again (no saved copy, or --refresh), so its lines may have moved
        head.append("note: the page was read again (no saved copy, or a refresh), so line %d may "
                    "not be where an earlier answer pointed; the outline is in the answer from line 1"
                    % start)
    room_b, room_l, room_c = budget - _bytes(head), max_lines - len(head), chars - _chars(head)

    if total == 0:
        return "\n".join(head + ["── %s is empty ──" % view]) + "\n", None
    if start > total:
        return "\n".join(head + ["── %s has %d lines: line %d is past the end ──" % (view, total, start)]) + "\n", None
    whole = (start == 1 and _bytes(lines) + POINTER_BYTES <= room_b and _chars(lines) + POINTER_BYTES <= room_c
             and total + 2 <= room_l)
    if whole:
        return "\n".join(head + [_lines(view, 1, total)] + pictures.compact(lines)
                         + [_eof(view, 1, total, total)]) + "\n", None

    block, block_c = room_b - POINTER_BYTES, room_c - POINTER_BYTES
    rows = []
    if start == 1 and not whole:
        # the blocks the answers will really have: the first one shares its room with the
        # outline, every continuation (no outline) gets the whole block. Two passes, because the
        # first block depends on the outline's size and a heading-less outline on the blocks.
        def starts_after(first_end):
            out, n = [1], first_end
            while n <= total:
                out.append(n)
                n = window(lines, n, block, room_l - 3, block_c)
            return out

        def outline_rows(room_o):
            rows = outline(lines, room_o, starts_after(window(lines, 1, block - OUTLINE_BYTES, room_l - 60,
                                                              block_c - OUTLINE_BYTES)))
            first_end = window(lines, 1, block - _bytes(rows) - 30, room_l - len(rows) - 4,
                               block_c - _chars(rows) - 30)
            rows = outline(lines, room_o, starts_after(first_end))
            return ["outline (line, heading):"] + rows if rows else []

        def first_fits(rows):
            # the text's first line whole beside the outline, under the longest pointer this text can have
            tail = [next_hint(max(2, total), total, view) if total > 1 else _eof(view, 1, 1, total)]
            return _fits("\n".join(head + rows + [_lines(view, 1, total)] + pictures.compact(lines[:1]) + tail) + "\n",
                         budget, chars, max_lines)

        room_o = min(OUTLINE_BYTES, room_b // 3, room_c // 3)
        rows = outline_rows(room_o)
        if rows and not first_fits(rows):
            # a first line too long to stand beside the outline - a text with no headings that opens with a paragraph
            # of 1 998 characters, a Chinese one of 6 KB - was cut and its rest never shown (KNOWN-ISSUES 295): the
            # outline gives up its room, a half, a quarter, all of it
            for smaller in (room_o // 2, room_o // 4):
                rows = outline_rows(smaller)
                if first_fits(rows):
                    break
            else:
                rows = []
    end = window(lines, start, block - _bytes(rows), room_l - len(rows) - 3, block_c - _chars(rows))
    while True:
        # a picture's first marker in this answer is full, a repeat short
        body = [_lines(view, start, total)] + pictures.compact(lines[start - 1:end - 1])
        tail = [next_hint(end, total, view) if end <= total else _eof(view, start, end - 1, total)]
        out = "\n".join(head + rows + body + tail) + "\n"
        if _fits(out, budget, chars, max_lines):
            return out, (end if end <= total else None)
        if end <= start + 1:
            break
        end -= 1

    # one line longer than a whole answer: content.md and page.md never have one (split_long_lines),
    # a raw file read through MCP can (a minified page is one line). Show its head and say so.
    line = lines[start - 1]
    size = len(line.encode("utf-8"))
    note = "── line %d is longer than one answer: the first %%s of %s shown ──" % (start, _human(size))
    around = head + rows + body[:1] + tail
    room = budget - _bytes(around) - len((note % "000.0 KB").encode("utf-8")) - 2
    room_u = chars - _chars(around) - u16(note % "000.0 KB") - 2
    cut = line.encode("utf-8")[:max(0, room)].decode("utf-8", "ignore")
    while cut and u16(cut) > room_u:
        cut = cut[:max(0, len(cut) - (u16(cut) - room_u))]       # each character is one unit or two
    out = "\n".join(around[:len(head + rows + body[:1])] + [cut, note % _human(len(cut.encode("utf-8")))] + tail) + "\n"
    return out, (end if end <= total else None)
