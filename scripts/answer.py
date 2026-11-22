"""The answer an agent reads in one call: a header, then the text, inside the smallest output limit
any harness enforces.

Codex with a non-OpenAI model passes 10 000 bytes of stdout and stderr together, Roo Code 10 240,
Cline 500 lines; past that every harness cuts in its own way (the head, the tail, the middle, or
just a path to a file). So one answer is at most BUDGET_BYTES and BUDGET_LINES, counted on what
is written: UTF-8 with LF. A text that fits is printed whole. A longer one gets an outline with
line numbers first, then its beginning up to the limit, cut at a paragraph, and the exact line
where it goes on; continuing from that line prints the next block of the same size.
"""
import os
import re

import pictures

BUDGET_BYTES = 9980
BUDGET_LINES = 495
OUTLINE_BYTES = 2500
OUTLINE_MIN = 12       # an outline coarser than this, finer headings below it: those, thinned
LINE_CHARS = 1998      # Read in Claude Code, OpenCode and Kimi CLI stop at 2 000; "\r\n" fits too
LINE_BYTES = 6000      # keeps every line inside one block even with the outline above it
POINTER_BYTES = 200    # the separator above the text and the pointer below it
OUTSIDE_SHOWN = 1024   # less than this outside the text (a footer line) is not worth a header row

_SENTENCE_END = re.compile(r"[.!?…](?=\s)|[。！？]")     # CJK full stops need no space after
_SPACE = re.compile(r"\s")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


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


def window(lines, start, byte_budget, line_budget):
    """Index after the last line of the block that starts at `start` (both from 1).

    The block takes whole lines while they fit, then steps back to the last blank line in its
    second half, so it ends between paragraphs. It always takes at least one line.
    """
    end, used = start, 0
    while end <= len(lines) and end - start < line_budget:
        size = len(lines[end - 1].encode("utf-8")) + 1
        if used + size > byte_budget and end > start:
            break
        used += size
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
        if content.get("restored"):
            # blocks the extractor dropped and the text got back from page.md
            engine += " + %d block%s of page.md" % (content["restored"], "" if content["restored"] == 1 else "s")
        if isinstance(content.get("cover"), (int, float)):
            # the proof the description promises: how much of the visible page the text holds
            engine += ", %d%% of the page" % min(100, int(round(content["cover"] * 100)))
        first.append(engine)
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
    if signals.get("fragment"):
        first.append("fragment")
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


def render(manifest, text, view, start, next_hint, budget=BUDGET_BYTES, max_lines=BUDGET_LINES):
    """The whole answer as one string, and the line the next block starts at (None at the end).

    `next_hint(n, total, view)` words the pointer for the caller: a flag on the command line, an
    argument of an MCP tool.
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
    room_b, room_l = budget - _bytes(head), max_lines - len(head)

    if total == 0:
        return "\n".join(head + ["── %s is empty ──" % view]) + "\n", None
    if start > total:
        return "\n".join(head + ["── %s has %d lines: line %d is past the end ──" % (view, total, start)]) + "\n", None
    if start == 1 and _bytes(lines) + POINTER_BYTES <= room_b and total + 2 <= room_l:
        return "\n".join(head + ["── %s: all %d lines ──" % (view, total)] + pictures.compact(lines)) + "\n", None

    block = room_b - POINTER_BYTES
    rows = []
    if start == 1:
        # the blocks the answers will really have: the first one shares its room with the
        # outline, every continuation (no outline) gets the whole block. Two passes, because the
        # first block depends on the outline's size and a heading-less outline on the blocks.
        def starts_after(first_end):
            out, n = [1], first_end
            while n <= total:
                out.append(n)
                n = window(lines, n, block, room_l - 3)
            return out

        rows = outline(lines, min(OUTLINE_BYTES, room_b // 3),
                       starts_after(window(lines, 1, block - OUTLINE_BYTES, room_l - 60)))
        first_end = window(lines, 1, block - _bytes(rows) - 30, room_l - len(rows) - 4)
        rows = outline(lines, min(OUTLINE_BYTES, room_b // 3), starts_after(first_end))
        if rows:
            rows = ["outline (line, heading):"] + rows
    end = window(lines, start, block - _bytes(rows), room_l - len(rows) - 3)
    while True:
        # a picture's first marker in this answer is full, a repeat short
        body = (["── %s: lines %d-%d of %d ──" % (view, start, end - 1, total)]
                + pictures.compact(lines[start - 1:end - 1]))
        tail = [next_hint(end, total, view)] if end <= total else []
        out = "\n".join(head + rows + body + tail) + "\n"
        if len(out.encode("utf-8")) <= budget and out.count("\n") <= max_lines:
            return out, (end if end <= total else None)
        if end <= start + 1:
            break
        end -= 1

    # one line longer than a whole answer: content.md and page.md never have one (split_long_lines),
    # a raw file read through MCP can (a minified page is one line). Show its head and say so.
    line = lines[start - 1]
    size = len(line.encode("utf-8"))
    note = "── line %d is longer than one answer: the first %%s of %s shown ──" % (start, _human(size))
    room = budget - _bytes(head + rows + body[:1] + tail) - len((note % "000.0 KB").encode("utf-8")) - 2
    cut = line.encode("utf-8")[:max(0, room)].decode("utf-8", "ignore")
    out = "\n".join(head + rows + body[:1] + [cut, note % _human(len(cut.encode("utf-8")))] + tail) + "\n"
    return out, (end if end <= total else None)
