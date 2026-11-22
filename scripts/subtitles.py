"""Subtitle files as yt-dlp writes them, turned into WEBVTT cues.

yt-dlp is asked for VTT, then SRT, then whatever the site has (`--sub-format vtt/srt/best`): RuTube gives SRT only,
a broadcaster's site TTML, a YouTube track in another client's form srv1-3 or json3, an anime site ASS, a lyrics site
LRC. `to_vtt(raw, ext)` gives the cues of any of them as one WEBVTT text - `readpage.vtt_to_text` reads that, and it
is what `transcript.vtt` holds. Nothing here installs or runs anything; the standard library only.
"""
import json
import re
from html import unescape

# the text formats a track may come in, in the order one is taken when a language has several
EXTS = ("vtt", "srt", "sbv", "ttml", "dfxp", "srv3", "srv2", "srv1", "json3", "ass", "ssa", "lrc")


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
    s = re.sub(r"<br\s*/?>", " ", text or "", flags=re.I)
    s = re.sub(r"<[^<>]*>", "", s)
    s = re.sub(r"\{\\[^}]*\}", "", s)                        # {\an8}, {\i1}: an override, never a word
    s = unescape(s)
    if re.search(r"&(#\d+|#x[0-9a-fA-F]+|amp|lt|gt|quot|apos);", s):
        s = unescape(s)                                      # YouTube's srv1 escapes twice
    s = s.replace("\\N", " ").replace("\\n", " ").replace("-->", "->")
    return re.sub(r"\s+", " ", s).strip()


def _vtt(cues):
    """WEBVTT from [(start, end, text)]; "" when there is no cue with text."""
    out = ["%s --> %s\n%s" % (_stamp(a), _stamp(max(a, b)), t) for a, b, t in cues if t]
    return "WEBVTT\n\n" + "\n\n".join(out) + "\n" if out else ""


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


def _ttml(raw):
    m = re.search(r'tickRate="(\d+)"', raw)
    tick = float(m.group(1)) if m else 10000000.0
    cues = []
    # a paragraph's text holds no other <p>: one that no </p> closes is not scanned to the end of the file from
    # each of a run of them (8 000 took 5 s), and an opening's attributes stop at the next tag
    for p in re.finditer(r"<p\b([^<>]*)>((?:(?!</?p\b).)*)</p>", raw, re.S):
        attrs = p.group(1)
        b, e, d = (re.search(r'\b%s="([^"]+)"' % k, attrs) for k in ("begin", "end", "dur"))
        if not b:
            continue
        start = _seconds(b.group(1), tick)
        end = _seconds(e.group(1), tick) if e else start + (_seconds(d.group(1), tick) if d else 0.0)
        cues.append((start, end, _clean(p.group(2))))
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


_READERS = {"srt": _arrow, "sbv": _sbv, "ttml": _ttml, "dfxp": _ttml, "srv1": _srv, "srv2": _srv, "srv3": _srv,
            "json3": _json3, "ass": _ass, "ssa": _ass, "lrc": _lrc}


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
