"""Subtitle files as yt-dlp writes them, turned into WEBVTT cues.

yt-dlp is asked for VTT, then SRT, then whatever the site has (`--sub-format vtt/srt/best`): RuTube gives SRT only,
a broadcaster's site TTML, a YouTube track in another client's form srv1-3 or json3, an anime site ASS, a lyrics site
LRC. `to_vtt(raw, ext)` gives the cues of any of them as one WEBVTT text - `readpage.vtt_to_text` reads that, and it
is what `transcript.vtt` holds. YouTube's automatic VTT rolls (each cue repeats the line before): `rolled_cues(vtt)`
gives its lines once, and `unrolled(vtt)` is what `transcript.vtt` holds then. Nothing here installs or runs
anything; the standard library only.
"""
import bisect
import json
import re
from html import escape, unescape

# the text formats a track may come in, in the order one is taken when a language has several; `xml` is a TTML or a
# YouTube XML track whose address yt-dlp took its extension from (an EBU-TT file at `...deu.xml`, KNOWN-ISSUES 331)
EXTS = ("vtt", "srt", "sbv", "ttml", "dfxp", "srv3", "srv2", "srv1", "json3", "ass", "ssa", "lrc", "xml")


def track_of(name):
    """("zh-Hans", "vtt") for `video.zh-Hans.vtt`; ("", "") for a file that is not a subtitle track of the video
    (`video.info.json`, `transcript.vtt`, a page's own files)."""
    m = re.match(r"^video\.(.+)\.([A-Za-z0-9]+)$", name or "")
    if not m or m.group(2).lower() not in EXTS:
        return "", ""
    return m.group(1), m.group(2).lower()


def _seconds(text, tick=10000000.0):
    """A cue time as seconds: 00:01:02,500  1:02.5  00:00:01:15 (frames)  62.5s  1500ms  10000000t  62.5"""
    t = (text or "").strip().replace(",", ".")
    m = re.match(r"^(\d+(?:\.\d+)?)(ms|s|t|m|h)$", t)
    if m:
        v = float(m.group(1))
        return {"ms": v / 1000.0, "s": v, "t": v / tick, "m": v * 60, "h": v * 3600}[m.group(2)]
    parts = t.split(":")
    try:
        nums = [float(x) for x in parts]
    except ValueError:
        return 0.0
    if len(nums) == 4:                                       # hh:mm:ss:frames
        nums = [nums[0], nums[1], nums[2] + nums[3] / 30.0]
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def _stamp(sec):
    ms = int(round(max(0.0, sec) * 1000))
    return "%02d:%02d:%02d.%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def _clean(text):
    """One line of cue text: tags, ASS overrides and entities out, the break between lines a space."""
    s = re.sub(r"<(?:[\w.-]+:)?br\s*/?>", " ", text or "", flags=re.I)   # <tt:br/> too: "Abend,meine" was glued
    s = re.sub(r"<[^<>]*>", "", s)
    s = re.sub(r"\{\\[^}]*\}", "", s)                        # {\an8}, {\i1}: an override, never a word
    s = unescape(s)
    if re.search(r"&(#\d+|#x[0-9a-fA-F]+|amp|lt|gt|quot|apos);", s):
        s = unescape(s)                                      # YouTube's srv1 escapes twice
    s = s.replace("\\N", " ").replace("\\n", " ").replace("-->", "->")
    return re.sub(r"\s+", " ", s).strip()


def _vtt(cues):
    """WEBVTT from [(start, end, text)]; "" when there is no cue with text. A cue's text is escaped as WebVTT asks
    (&, <, >): it is read back tags first, then entities, and "x < y and y > z" lost "< y and y >" (KNOWN-ISSUES 332)."""
    out = ["%s --> %s\n%s" % (_stamp(a), _stamp(max(a, b)), escape(t, quote=False)) for a, b, t in cues if t]
    return "WEBVTT\n\n" + "\n\n".join(out) + "\n" if out else ""


def cue_text(line):
    """A WebVTT cue's line as text: its tags out (<c>, <i>, a word's time <00:00:01.500>), then its entities (&amp;,
    &gt;&gt;, &lt;), which stayed in the transcript as they were written (KNOWN-ISSUES 332). In that order, so an
    escaped tag stays text."""
    return unescape(re.sub(r"<[^>]+>", "", line or ""))


def _split_blocks(raw):
    return [b for b in re.split(r"\n[ \t]*\n", raw.replace("\r\n", "\n").replace("\r", "\n").strip()) if b.strip()]


def _arrow(raw):
    """SRT and anything laid out like it: a time line `start --> end`, the text under it until a blank line."""
    cues = []
    for block in _split_blocks(raw):
        lines = block.split("\n")
        at = next((i for i, x in enumerate(lines) if "-->" in x), -1)
        if at < 0:
            continue
        a, _, b = lines[at].partition("-->")
        cues.append((_seconds(a), _seconds(b.split()[0] if b.split() else ""), _clean(" ".join(lines[at + 1:]))))
    return cues


def _sbv(raw):
    cues = []
    for block in _split_blocks(raw):
        lines = block.split("\n")
        m = re.match(r"^\s*([\d:.]+)\s*,\s*([\d:.]+)\s*$", lines[0])
        if m:
            cues.append((_seconds(m.group(1)), _seconds(m.group(2)), _clean(" ".join(lines[1:]))))
    return cues


_PREFIX = r"(?:[\w.-]+:)?"          # an element's namespace prefix: EBU-TT-D writes every one <tt:...>


def _attr(attrs, name):
    """An attribute's value, in either quote; None without it."""
    m = re.search(r"""(?<![\w:.-])%s\s*=\s*(?:"([^"]*)"|'([^']*)')""" % name, attrs)
    return None if m is None else (m.group(1) if m.group(1) is not None else m.group(2))


def _times(attrs, tick):
    """(begin, end) of an element's own attributes, in seconds: end from `end`, else begin + `dur`; (None, None)
    without a begin."""
    b, e, d = (_attr(attrs, k) for k in ("begin", "end", "dur"))
    if b is None:
        return None, None
    start = _seconds(b, tick)
    return start, (_seconds(e, tick) if e is not None else start + (_seconds(d, tick) if d is not None else 0.0))


def _ttml(raw):
    """TTML and DFXP: each paragraph a cue. Elements are known by their local name - EBU-TT-D, the broadcasters' TTML,
    writes <tt:p>, and none of its cues was read (KNOWN-ISSUES 331) - and attributes in either quote. A paragraph's time
    is its own, else its spans' (the first begin, the last end); a time under a <div> that has one is relative to it,
    as TTML says; a paragraph with no time at all keeps its text, at the end of the cue before it."""
    m = re.search(r"""tickRate\s*=\s*["'](\d+)["']""", raw)
    tick = float(m.group(1)) if m else 10000000.0
    # where each <div> that has a begin opens and closes: a paragraph's time under it is relative to it
    marks, open_ = [], []
    for d in re.finditer(r"<(/?)%sdiv\b([^<>]*)>" % _PREFIX, raw):
        if d.group(1):
            if open_:
                open_.pop()
        elif not d.group(2).rstrip().endswith("/"):
            open_.append(_times(d.group(2), tick)[0] or 0.0)
        marks.append((d.start(), sum(open_)))
    at = [k for k, _off in marks]
    cues = []
    # a paragraph's text holds no other <p>: one that no </p> closes is not scanned to the end of the file from
    # each of a run of them (8 000 took 5 s), and an opening's attributes stop at the next tag
    for p in re.finditer(r"<%sp\b([^<>]*)>((?:(?!</?%sp\b).)*)</%sp\s*>" % (_PREFIX, _PREFIX, _PREFIX), raw, re.S):
        start, end = _times(p.group(1), tick)
        if start is None:
            spans = [_times(s.group(1), tick) for s in re.finditer(r"<%sspan\b([^<>]*)>" % _PREFIX, p.group(2))]
            spans = [t for t in spans if t[0] is not None]
            if spans:
                start, end = min(t[0] for t in spans), max(t[1] for t in spans)
        k = bisect.bisect_right(at, p.start()) - 1
        offset = marks[k][1] if k >= 0 else 0.0
        if start is None:
            start = end = cues[-1][1] if cues else 0.0     # no time of its own: its words stay, after the cue before
            offset = 0.0
        cues.append((start + offset, end + offset, _clean(p.group(2))))
    return cues


def _srv(raw):
    """YouTube's own XML: srv1 `<text start="1.2" dur="2.3">`, srv2 `<text t="1200" d="2300">`, srv3 `<p t= d=>`."""
    cues = []
    for p in re.finditer(r"<(text|p)\b([^<>]*)>((?:(?!</?(?:text|p)\b).)*)</\1>", raw, re.S):     # linear, as _ttml's
        attrs = p.group(2)
        s1, s2 = re.search(r'\bstart="([\d.]+)"', attrs), re.search(r'\bt="(\d+)"', attrs)
        if s1:
            d = re.search(r'\bdur="([\d.]+)"', attrs)
            start = float(s1.group(1))
            end = start + (float(d.group(1)) if d else 0.0)
        elif s2:
            d = re.search(r'\bd="(\d+)"', attrs)
            start = int(s2.group(1)) / 1000.0
            end = start + (int(d.group(1)) / 1000.0 if d else 0.0)
        else:
            continue
        cues.append((start, end, _clean(p.group(3))))
    return cues


def _json3(raw):
    cues = []
    try:
        events = json.loads(raw).get("events") or []
    except (ValueError, AttributeError):
        return cues
    for ev in events:
        if not isinstance(ev, dict) or not ev.get("segs"):
            continue
        text = _clean("".join(str(s.get("utf8") or "") for s in ev["segs"] if isinstance(s, dict)))
        start = float(ev.get("tStartMs") or 0) / 1000.0
        cues.append((start, start + float(ev.get("dDurationMs") or 0) / 1000.0, text))
    return cues


def _ass(raw):
    fields, in_events, cues = None, False, []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip()
        if line.startswith("["):
            in_events = line.lower() == "[events]"
        elif in_events and line.lower().startswith("format:"):
            fields = [x.strip().lower() for x in line[7:].split(",")]
        elif in_events and line.lower().startswith("dialogue:"):
            names = fields or ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
            parts = line[9:].split(",", len(names) - 1)
            if len(parts) == len(names) and "start" in names and "end" in names and "text" in names:
                row = dict(zip(names, parts))
                cues.append((_seconds(row["start"]), _seconds(row["end"]), _clean(row["text"])))
    return sorted(cues, key=lambda c: c[0])


def _lrc(raw):
    stamped = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        tags = re.findall(r"\[(\d+):(\d+(?:[.:]\d+)?)\]", line)
        text = _clean(re.sub(r"\[[^\]]*\]", "", line))
        for mm, ss in tags:
            stamped.append((int(mm) * 60 + float(ss.replace(":", ".")), text))
    stamped.sort(key=lambda x: x[0])
    return [(a, stamped[i + 1][0] if i + 1 < len(stamped) else a + 3.0, t) for i, (a, t) in enumerate(stamped)]


def _xml(raw):
    """A track yt-dlp named by its address's `.xml`: TTML (its root `tt`, or TTML's namespace), else YouTube's own XML;
    no cue for any other XML."""
    head = raw[:4096]
    if re.search(r"<%stt\b|http://www\.w3\.org/ns/ttml|http://www\.w3\.org/2006/(?:04|10)/ttaf1" % _PREFIX, head):
        return _ttml(raw)
    if re.search(r"<(?:transcript|timedtext)\b", head):
        return _srv(raw)
    return []


_READERS = {"srt": _arrow, "sbv": _sbv, "ttml": _ttml, "dfxp": _ttml, "srv1": _srv, "srv2": _srv, "srv3": _srv,
            "json3": _json3, "ass": _ass, "ssa": _ass, "lrc": _lrc, "xml": _xml}

_WORD_TIME = re.compile(r"<(\d\d:\d\d:\d\d[.,]\d+)>")


def rolled_cues(vtt):
    """YouTube's automatic captions in their rolling form, every line once: [(start, end, text, since)], the times in
    seconds; None for a track that is not in that form.

    A cue of such a track is a screen of two rows (a broadcaster's, three): the rows above the bottom one are the lines
    the cues before it showed, carried up, and the bottom row is the new line, whose words carry their own times
    (`<00:00:13.620>`); a cue of 10 ms shows the new line alone before the next one comes (a row of one space is an
    empty row). So each line stood in three cues, and in the text three times. Here a row that is not the bottom one
    and is the line the screen showed last is carried and left out; the bottom row is new whatever it says, so a line
    that is said twice stands twice. `start` and `end` are those of the cue the line came in; `text` has no tags;
    `since` is when the line before was last spoken (its last word's time, else its cue's start; None for the first),
    which is what a pause is told by: a line is shown until the next one comes, so the cues have no gaps.

    A track is in this form when its words carry times and a row is carried up somewhere; a person's roll-up captions,
    which have no word times, and cues that only carry words are not, and are read as they are."""
    if not _WORD_TIME.search(vtt or ""):
        return None
    cues, rows = [], None
    for line in vtt.splitlines():
        if "-->" in line:
            head, _, tail = line.partition("-->")
            rows = []
            cues.append((_seconds(head), _seconds(tail.split()[0] if tail.split() else head), rows))
        elif rows is not None:
            if line == "":
                rows = None                         # the cue ends at an empty line; a row of a space is an empty row
            else:
                rows.append(line)
    out, shown, since, carried = [], [], None, 0
    for start, end, rows in cues:
        keys = [" ".join(re.sub(r"<[^>]+>", "", r).replace("&nbsp;", " ").split()) for r in rows]
        bottom = len(rows) - 1 if rows and keys[-1] else -1
        above = [i for i, k in enumerate(keys) if k and i != bottom]
        base = len(shown) - len(above)
        take = []
        for n, i in enumerate(above):
            if base + n >= 0 and shown[base + n] == keys[i]:
                carried += 1
            else:
                take.append(i)                      # a row the screen did not show: it is a line, not lost
        if bottom >= 0:
            take.append(bottom)
        for i in take:
            times = _WORD_TIME.findall(rows[i])
            out.append((start, end, cue_text(rows[i]).strip(), since))
            since = _seconds(times[-1]) if times else start
            shown.append(keys[i])
        del shown[:-8]
    return out if carried else None


def unrolled(vtt):
    """WEBVTT of a rolling track's lines, one cue each, as the other formats' are kept; "" for any other track."""
    cues = rolled_cues(vtt)
    return _vtt([(a, b, t) for a, b, t, _since in cues]) if cues else ""


def to_vtt(raw, ext):
    """The cues of a subtitle file of format `ext` (without the dot) as a WEBVTT text; a VTT is returned as it is.
    "" when it holds no cue - an empty file, or a format that is not one of EXTS."""
    ext = (ext or "").lower().lstrip(".")
    raw = (raw or "").lstrip("\ufeff")
    if ext == "vtt":
        return raw
    reader = _READERS.get(ext)
    if reader is None:
        return _vtt(_arrow(raw)) if "-->" in raw else ""
    try:
        return _vtt(reader(raw))
    except (ValueError, TypeError, KeyError):
        return ""
