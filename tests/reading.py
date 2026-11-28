"""Reading: encodings, dead hosts, readers, retries. No network.
Hash routes and late JavaScript need a browser: they are in browser_live.py.

    python -X utf8 tests/reading.py

The page in any encoding a server forgets to declare; a dead host or a 5xx goes to the readers and
the archive when that is allowed; a video site's ordinary page is a page; Jina gets the address in
a POST body; a machine without curl still reads; a 503 gets one more try; defuddle knows the page's
address, so relative links do not turn into about:blank.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import advsrv                                                # noqa: E402
from harness import PUBLIC, SCRIPT, Checks, run_read         # noqa: E402

check = Checks()
H = {"Content-Type": "text/html; charset=utf-8"}


def page(title, body, head=""):
    return "<!doctype html><html><head>%s<title>%s</title></head><body><article><h1>%s</h1><p>%s</p></article></body></html>" % (
        head, title, title, body)


RU = ("Съешь же ещё этих мягких французских булок, да выпей чаю. Широкая электрификация южных губерний "
      "даст мощный толчок подъёму сельского хозяйства. ") * 12
JP = "吾輩は猫である。名前はまだ無い。どこで生れたかとんと見当がつかぬ。何でも薄暗いじめじめした所でニャーニャー泣いていた事だけは記憶している。" * 12
ZH = "中华人民共和国的首都是北京，这是一个历史悠久的城市，拥有许多著名的景点和丰富的文化遗产。" * 14
KO = "대한민국의 수도는 서울이며 역사가 깊고 많은 유명한 명소와 풍부한 문화유산을 가지고 있습니다. " * 14
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ") * 14


def module():
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-read-")
    spec = importlib.util.spec_from_file_location("rp_read_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inproc(mod, argv):
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        mod.main(argv + ["--json", "--dir", tempfile.mkdtemp(prefix="rp-read-out-")])
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


class Count:
    """Answers `first` for the first `times` requests, then `then`."""

    def __init__(self, first, then, times=1):
        self.first, self.then, self.times, self.n = first, then, times, 0
        self.lock = threading.Lock()

    def __call__(self, h):
        with self.lock:
            self.n += 1
            n = self.n
        code, body = self.first if n <= self.times else self.then
        h.send_response(code)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(body)
        h.close_connection = True


s = advsrv.start()
pub = s.public.routes
pub.update({
    "/utf16": (200, {"Content-Type": "text/html"}, page("Документ", RU).encode("utf-16")),
    "/sjis": (200, {"Content-Type": "text/html"}, page("文書", JP).encode("shift_jis")),
    "/gbk": (200, {"Content-Type": "text/html"}, page("文档", ZH).encode("gbk")),
    "/euckr": (200, {"Content-Type": "text/html"}, page("문서", KO).encode("euc-kr")),
    "/bad-meta": (200, {"Content-Type": "text/html"}, page("Документ", RU, "<meta charset='utf-8'>").encode("cp1251")),
    "/utf8": (200, {"Content-Type": "text/html"}, page("Документ", RU).encode("utf-8")),
    "/r12": Count((503, b"<h1>Service Unavailable</h1>"),
                  (200, page("Back", "RETRY-OK " + EN).encode("utf-8"))),
    "/relative": (200, H, ("<!doctype html><html><head><title>Links</title></head><body><article><h1>Links</h1><p>"
                           + EN + " <a href='/docs/next.html'>the next chapter</a> and <a href='part2.html'>part two</a>."
                           "</p></article></body></html>").encode("utf-8")),
    "/watch-page": (200, H, page("About this video site", "VIDEO-SITE-PAGE " + EN).encode("utf-8")),
})

try:
    # ------------------------------------------------ the encoding a server forgot to say
    cases = {"/koi8-none": "булок", "/cp1251-none": "булок", "/koi8-header": "булок", "/latin1-lie": "булок",
             "/utf16": "булок", "/sjis": "吾輩は猫", "/gbk": "中华人民", "/euckr": "대한민국",
             "/bad-meta": "булок", "/utf8": "булок"}
    wrong = []
    for path, needle in cases.items():
        r = run_read(s.public.url(path), "--json")
        if needle not in r.file("content.md"):
            wrong.append("%s (%s)" % (path, (r.manifest.get("url") or {}).get("charset")))
    check("%d encodings, declared or not, read right" % len(cases), not wrong, ", ".join(wrong))

    # ------------------------------------------------ one more try on 502/503/504
    r = run_read(s.public.url("/r12"), "--json", env={"READ_PAGE_SKIP": "browser"})   # the HTTP step itself
    check("a 503 then a 200 is the page", r.manifest.get("status") == "ok" and "RETRY-OK" in r.file("content.md"),
          "%s, %d requests" % (r.manifest.get("status"), pub["/r12"].n))

    # ------------------------------------------------ a dead host or a 5xx goes to the readers and the archive
    mod = module()
    seen = []
    mod.external_read = lambda url, c, refresh=False: (seen.append(url), (
        "# Rescued\n\n" + "READER-TEXT " + EN, "reader:jina", 200, ""))[1]
    mod.wayback = lambda url: (b"", "", "archive:wayback", "never archived")
    dead = "http://%s:%d/gone" % (PUBLIC, 9)            # discard port: nothing listens
    m, text = inproc(mod, [dead, "--allow-external"])
    check("a host that does not answer is tried through a reader with --allow-external",
          bool(seen) and m.get("status") == "ok" and "READER-TEXT" in text, "%s, readers %d" % (m.get("status"), len(seen)))
    seen.clear()
    m, text = inproc(mod, [dead])
    check("without the flag nothing leaves, and the advice names the flag",
          not seen and m.get("status") == "error" and "--allow-external" in (m.get("advice") or ""),
          (m.get("advice") or "")[:70])
    mod2 = module()
    archived = []
    mod2.external_read = lambda url, c, refresh=False: ("", "reader:jina", None, "no text")
    mod2.wayback = lambda url: (archived.append(url), (page("Archived", "ARCHIVE-TEXT " + EN).encode(), "text/html",
                                                       "archive:wayback", "20240101000000"))[1]
    pub["/503-long"] = (503, H, page("Maintenance", "We are down for maintenance. " + EN).encode())
    m, text = inproc(mod2, [s.public.url("/503-long"), "--allow-external"])
    check("a 5xx with --allow-external is answered from the archive", bool(archived)
          and "ARCHIVE-TEXT" in text and m.get("status") == "ok", "%s, archive %d" % (m.get("status"), len(archived)))
    # runoob timed out once, the archive answered "the live page is gone", and that copy
    # was the answer for 15 minutes though the page was back a minute later
    adv = m.get("advice") or ""
    check("after a 5xx the archive copy says what the live page did, not that it is gone, and names --refresh",
          "answered HTTP 503" in adv and "--refresh" in adv and "gone" not in adv, adv[:120])
    n0 = len(archived)
    m2, _ = inproc(mod2, [s.public.url("/503-long"), "--allow-external"])
    mpath = os.path.join(mod2.page_dir(s.public.url("/503-long")), "manifest.json")
    with open(mpath, encoding="utf-8") as fh:
        cm = json.load(fh)
    cm["_cached_at"] -= 120                              # two minutes later
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(cm, fh)
    m3, _ = inproc(mod2, [s.public.url("/503-long"), "--allow-external"])
    check("such a rescue comes from the cache for a minute, then the live page is asked again",
          m2.get("cache") == "hit" and m3.get("cache") != "hit" and len(archived) == n0 + 1,
          "%s then %s, archive asked %d more" % (m2.get("cache"), m3.get("cache"), len(archived) - n0))

    # ------------------------------------------------ a video site's ordinary page is a page
    mod3 = module()
    pats = {"https://www.youtube.com/watch?v=dQw4w9WgXcQ": True, "https://youtu.be/dQw4w9WgXcQ": True,
            "https://vimeo.com/76979871": True, "https://vimeo.com/about": False,
            "https://www.tiktok.com/@scout2015/video/6718335390845095173": True, "https://www.tiktok.com/about": False,
            "https://www.twitch.tv/videos/1234567890": True, "https://www.twitch.tv/directory": False,
            "https://rutube.ru/video/0123456789abcdef0123456789abcdef/": True, "https://rutube.ru/feeds/": False,
            "https://vk.com/video-12345_67890": True, "https://ok.ru/video/123456789": True,
            "https://www.dailymotion.com/video/x7tgad0": True, "https://www.dailymotion.com/us": False}
    wrong = [u for u, want in pats.items() if bool(mod3.VIDEO_URL.search(u)) != want]
    check("only real video addresses take the subtitle path (%d cases)" % len(pats), not wrong, ", ".join(wrong[:3]))
    mod3.VIDEO_URL = __import__("re").compile(r"/watch-page")
    mod3.video_text = lambda url, c, workdir: ("", "A video", "no subtitles in en,ru (set READ_PAGE_SUB_LANGS to change)")
    m, text = inproc(mod3, [s.public.url("/watch-page")])
    check("no subtitles - the page is read as a page, and the manifest says why",
          "VIDEO-SITE-PAGE" in text and m.get("status") == "ok" and (m.get("signals") or {}).get("no_transcript"),
          "%s %s" % (m.get("status"), (m.get("signals") or {}).get("no_transcript")))

    # ------------------------------------------------ a video's subtitle tracks: any text format, the speaker's language
    # yt-dlp is a stand-in that has the tracks `available` ({track: {format: text}}, the site's list, best last),
    # writes the ones a call asks for in the format `--sub-format` names first (else its last, as yt-dlp does),
    # and the info file `info` says
    import re
    mod8 = module()
    c8 = mod8.caps()
    c8["cli"]["yt-dlp"] = "yt-dlp"             # the runner's machine may not have it installed
    sub8 = getattr(mod8, "subtitles", None)

    def yt_video(info, available, lang="en", rc=0, err=b"", sub_langs=None, refuse_translated=False):
        """video_text() on the stand-in: (what it returned, the yt-dlp commands it ran, its folder). With
        `refuse_translated` a machine translation (its address asks for `tlang=`) answers 429, as YouTube's now do:
        yt-dlp then stops with nothing written - no track, no info file - unless it was told --ignore-errors."""
        folder, calls = tempfile.mkdtemp(prefix="rp-vid8-"), []
        translated8 = set(k for k, v in ((info or {}).get("automatic_captions") or {}).items()
                          if any("tlang=" in str(x.get("url") or "") for x in v))

        def fake(cmd, timeout=120, **kw):
            if not (cmd and cmd[0] == "yt-dlp"):
                return real8(cmd, timeout=timeout, **kw)
            calls.append(cmd)
            asked8 = cmd[cmd.index("--sub-langs") + 1].split(",")
            prefs = cmd[cmd.index("--sub-format") + 1].split("/")
            wanted = [k for k in available if any(re.fullmatch(p, k) for p in asked8)]
            refused = [k for k in wanted if refuse_translated and k in translated8]
            if refused and "--ignore-errors" not in cmd:
                return 1, b"", ("ERROR: Unable to download video subtitles for '%s': HTTP Error 429: Too Many Requests\n"
                                % refused[0]).encode()
            if info is not None and "--write-info-json" in cmd:
                with open(os.path.join(folder, "video.info.json"), "w", encoding="utf-8") as fh:
                    json.dump(info, fh)
            for key in wanted:
                if key in refused:
                    continue
                formats = available[key]
                ext = next((e for e in prefs if e in formats), list(formats)[-1])
                with open(os.path.join(folder, "video.%s.%s" % (key, ext)), "w", encoding="utf-8") as fh:
                    fh.write(formats[ext])
            if refused:
                return 0, b"", ("WARNING: Unable to download video subtitles for '%s': HTTP Error 429: Too Many Requests\n"
                                % refused[0]).encode()
            return rc, b"", err
        real8 = mod8.run
        mod8.run = fake
        os.environ["READ_PAGE_LANG"] = lang
        if sub_langs:
            os.environ["READ_PAGE_SUB_LANGS"] = sub_langs
        try:
            got = mod8.video_text("https://example.org/v", c8, folder)
        except Exception as e:                                    # noqa: BLE001
            got = ("%s: %s" % (type(e).__name__, e), "", "")
        finally:
            mod8.run = real8
            os.environ.pop("READ_PAGE_LANG", None)
            os.environ.pop("READ_PAGE_SUB_LANGS", None)
        return got, calls, folder

    def langs_of(cmd):
        return cmd[cmd.index("--sub-langs") + 1]

    def cues(*texts):
        return "WEBVTT\n\n" + "\n\n".join("00:00:%02d.000 --> 00:00:%02d.500\n%s" % (1 + 40 * i, 3 + 40 * i, t)
                                         for i, t in enumerate(texts)) + "\n"

    # each format, the same two cues (a 40 s gap: two blocks)
    want8 = "[0:01] Hello, it's world\n\n[0:41] Second block"
    formats8 = {
        "srt": "\ufeff1\n00:00:01,000 --> 00:00:03,500\n{\\an8}<i>Hello</i>, it's world\n\n2\n00:00:41,000 --> 00:00:43,500\nSecond block\n",
        "sbv": "0:00:01.000,0:00:03.500\nHello, it's world\n\n0:00:41.000,0:00:43.500\nSecond block\n",
        "ttml": ('<?xml version="1.0"?><tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
                 '<p begin="00:00:01.000" end="00:00:03.500">Hello,<br/>it&apos;s <span>world</span></p>'
                 '<p begin="41s" dur="2.5s">Second block</p></div></body></tt>'),
        "srv1": ('<?xml version="1.0"?><transcript><text start="1" dur="2.5">Hello, it&amp;#39;s world</text>'
                 '<text start="41" dur="2.5">Second block</text></transcript>'),
        "srv3": ('<timedtext format="3"><body><p t="1000" d="2500">Hello, it&#39;s <s>world</s></p>'
                 '<p t="41000" d="2500">Second block</p></body></timedtext>'),
        "json3": json.dumps({"events": [{"tStartMs": 1000, "dDurationMs": 2500, "segs": [{"utf8": "Hello, it's "}, {"utf8": "world"}]},
                                        {"tStartMs": 30000, "dDurationMs": 100},
                                        {"tStartMs": 41000, "dDurationMs": 2500, "segs": [{"utf8": "Second block"}]}]}),
        "ass": ("[Script Info]\nTitle: x\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\\i1}Hello, it's{\\i0}\\Nworld\n"
                "Dialogue: 0,0:00:41.00,0:00:43.50,Default,,0,0,0,,Second block\n"),
        "lrc": "[ti:x]\n[00:01.00]Hello, it's world\n[00:41.00]Second block\n",
    }
    formats8["dfxp"] = formats8["ttml"]
    formats8["srv2"] = formats8["srv3"].replace("<timedtext format=\"3\">", "<timedtext>")
    if sub8 is None:
        check("subtitle formats: scripts/subtitles.py", False, "no readpage.subtitles")
    else:
        wrong = []
        for ext, raw in sorted(formats8.items()):
            got = mod8.vtt_to_text(sub8.to_vtt(raw, ext))
            if got != want8:
                wrong.append("%s: %r" % (ext, got[:70]))
        check("%d subtitle formats (SRT, SBV, TTML, DFXP, srv1-3, json3, ASS, LRC) read as the same two blocks" % len(formats8),
              not wrong, "; ".join(wrong[:2]))
        vtt8 = sub8.to_vtt(formats8["srt"], "srt")
        check("an SRT becomes a WEBVTT text (dotted times, no index lines): what transcript.vtt holds",
              vtt8.startswith("WEBVTT") and "00:00:01.000 --> 00:00:03.500" in vtt8 and "," not in vtt8.split("\n\n")[1].split("\n")[0],
              vtt8[:80].replace("\n", "/"))
        check("a file of no known format and no cue is no transcript", sub8.to_vtt("{}", "json") == "" and sub8.to_vtt("", "srt") == ""
              and sub8.track_of("video.zh-Hans.vtt") == ("zh-Hans", "vtt") and sub8.track_of("video.info.json") == ("", "")
              and sub8.track_of("transcript.vtt") == ("", "") and sub8.track_of("video.en.json3") == ("en", "json3"),
              str([sub8.track_of(n) for n in ("video.zh-Hans.vtt", "video.info.json", "transcript.vtt")]))

        # a hostile track (a site yt-dlp reads serves it): paragraphs that no "</p>" closes, and openings with no
        # ">", were scanned to the end of the file from each one. Linear means 4 times the size takes about 4
        # times as long; a ratio over 8 fails (the best of two, a time under 0.05 s counted as 0.05 s)
        def hostile_ratio(make, ext):
            best = None
            for _try in range(2):
                times = []
                for n_ in (2000, 8000):
                    raw_ = make(n_)
                    t0_ = time.time()
                    sub8.to_vtt(raw_, ext)
                    times.append(time.time() - t0_)
                r_ = times[1] / max(times[0], 0.05)
                best = r_ if best is None else min(best, r_)
                if best <= 8:
                    break
            return best, times
        hostile8 = {
            "TTML, <p> never closed": (lambda n_: "<tt><body>" + '<p begin="1s" end="2s">x' * n_ + "</body></tt>", "ttml"),
            "srv3, <p> never closed": (lambda n_: "<timedtext><body>" + '<p t="1000" d="500">x' * n_ + "</body></timedtext>", "srv3"),
            "srv1, <text> never closed": (lambda n_: "<transcript>" + '<text start="1" dur="2">x' * n_ + "</transcript>", "srv1"),
            "TTML, <p with no >": (lambda n_: "<tt><body>" + "<p" * n_ + "</p></body></tt>", "ttml"),
        }
        slow8 = []
        for label_, (make_, ext_) in sorted(hostile8.items()):
            ratio_, times_ = hostile_ratio(make_, ext_)
            if ratio_ > 8:
                slow8.append("%s: %.2f s -> %.2f s" % (label_, times_[0], times_[1]))
        check("a hostile subtitle file (paragraphs never closed, openings with no >) is read in linear time",
              not slow8, "; ".join(slow8))
    names8 = ["video.ru.srt", "video.ru.vtt", "video.en.ttml", "video.info.json", "transcript.vtt", "page.md"]
    check("a language with a VTT and an SRT is read in the VTT; a folder's other files are no tracks",
          getattr(mod8, "pick_subtitle", lambda *a: "")(names8, ["ru"]) == "video.ru.vtt"
          and getattr(mod8, "pick_subtitle", lambda *a: "")(["video.info.json", "transcript.vtt"], ["en"]) == "", "")

    # RuTube: its automatic subtitles come as SRT only ("No subtitle format found matching vtt ... using srt")
    RU_SRT = "1\n00:00:01,000 --> 00:00:03,500\nДобрый день, коллеги\n\n2\n00:00:04,000 --> 00:00:06,000\nСегодня говорим о субтитрах\n"
    rutube = {"title": "Лекция", "uploader": "Канал", "subtitles": {"ru": [{"ext": "srt", "name": "Русский • Авто"}]},
              "automatic_captions": {}, "formats": [{"format_id": "default-247-0"}]}
    got, calls, folder = yt_video(rutube, {"ru": {"srt": RU_SRT}}, lang="ru")
    vtt8 = open(os.path.join(folder, "transcript.vtt"), encoding="utf-8").read() if os.path.isfile(
        os.path.join(folder, "transcript.vtt")) else ""
    check("RuTube: a track that comes as SRT is read, named automatic (its own name says so), kept as VTT",
          "Добрый день, коллеги" in got[0] and got[0].startswith("[0:01]") and got[2] == "subtitles ru, automatic"
          and vtt8.startswith("WEBVTT") and "00:00:01.000 --> 00:00:03.500" in vtt8 and len(calls) == 1,
          "%s | %s | %d calls" % (got[0][:50], got[2], len(calls)))
    got, calls, folder = yt_video(rutube, {"ru": {"srt": RU_SRT}}, lang="en")
    check("... for an English reader too: the video's own language is asked for once more",
          "Добрый день" in got[0] and len(calls) == 2 and langs_of(calls[1]) == "ru", "%s | %d calls" % (got[0][:40], len(calls)))
    got, calls, _ = yt_video({"title": "T", "language": "de", "subtitles": {"de": [{"ext": "ttml", "name": "Deutsch"}]}},
                             {"de": {"ttml": formats8["ttml"]}}, lang="en")
    check("a site that has TTML only: its track is read all the same", "Hello," in got[0] and got[2] == "subtitles de",
          "%s | %s" % (got[0][:40], got[2]))
    # EBU-TT-D, the broadcasters' TTML, writes every element <tt:...>, and XML allows either quote; a paragraph may
    # have its time on its spans, or under a <div> that has one; yt-dlp names a track by its address: `.xml`
    # (KNOWN-ISSUES 331)
    ebu8 = ('<?xml version="1.0" encoding="UTF-8"?><tt:tt xmlns:tt="http://www.w3.org/ns/ttml" xml:lang="de"><tt:body>'
            "<tt:div><tt:p xml:id='s1' begin='00:00:01.000' end='00:00:03.500'><tt:span>Hello,</tt:span><tt:br/>"
            "<tt:span>it&apos;s world</tt:span></tt:p><tt:p begin=\"41s\" dur=\"2.5s\">Second block</tt:p></tt:div>"
            "</tt:body></tt:tt>")
    if sub8 is not None:
        got8 = [mod8.vtt_to_text(sub8.to_vtt(ebu8, ext)) for ext in ("ttml", "xml")]
        check("331: EBU-TT-D's TTML (<tt:p>, single quotes, <tt:br/>) reads as the two blocks, named .ttml or .xml (no "
              "cue: 'subtitles were empty')", got8 == [want8, want8], str(got8)[:160])
        timed8 = ('<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p><span begin="00:00:01.000" end="00:00:02.000">'
                  "Hello,</span> <span begin='2s' end='3.5s'>it's world</span></p></div><div begin=\"40s\">"
                  '<p begin="1s" end="3.5s">Second block</p></div></body></tt>')
        got8 = mod8.vtt_to_text(sub8.to_vtt(timed8, "ttml"))
        check("331: a TTML paragraph timed by its spans, and one under a <div> with a begin, take those times (the first "
              "was left out, the second read 40 s early)", got8 == want8, got8[:120])
    got, calls, _ = yt_video({"title": "T", "language": "de", "subtitles": {"de": [{"ext": "xml", "name": "Deutsch"}]}},
                             {"de": {"xml": ebu8}}, lang="en")
    check("331: a broadcaster's track yt-dlp named by its address (video.de.xml) is read (it was no track: 'no "
          "subtitles')", "Hello," in got[0] and got[2] == "subtitles de", "%s | %s" % (got[0][:40], got[2]))

    # a dubbed video: yt-dlp's `language` names the default audio track, and the automatic track is that audio's speech
    ASR = "https://www.youtube.com/api/timedtext?v=x&caps=asr&hl=en&kind=asr&lang=en&fmt=vtt"
    dub = {"title": "新聞", "language": "en", "subtitles": {},
           "formats": [{"format_id": "249-0", "language": "en-US", "format_note": "English (US), low", "acodec": "opus"},
                       {"format_id": "249-1", "language": "zh-Hant", "format_note": "Chinese (Traditional) original (default), low",
                        "acodec": "opus"}],
           "automatic_captions": {"en": [{"url": ASR}], "en-orig": [{"url": ASR}],
                                  "zh-Hant": [{"url": ASR + "&tlang=zh-Hant"}], "zh-Hans": [{"url": ASR + "&tlang=zh-Hans"}]}}
    on8 = {"en": {"vtt": cues("the English dub speaks")}, "en-orig": {"vtt": cues("the English dub speaks")},
           "zh-Hant": {"vtt": cues("機器翻譯")}, "zh-Hans": {"vtt": cues("机器翻译")}}
    got, calls, _ = yt_video(dub, on8, lang="en")
    check("a dub's automatic track is named for what it is: the dub's speech, and the original language",
          "the English dub speaks" in got[0] and "dub" in got[2] and "zh-Hant" in got[2] and "en" in got[2], got[2])
    def kinds_of(info):
        try:
            return mod8.subtitle_kinds(info)
        except Exception as e:                                    # noqa: BLE001
            return {"error": "%s: %s" % (type(e).__name__, e)}
    kinds8 = kinds_of(dub)
    check("... and it is no track of the speaker's: a machine translation of it is worse still",
          kinds8.get("en-orig", "").startswith("dub") and kinds8.get("zh-Hant", "").startswith("translated")
          and kinds_of(dict(dub, formats=[])).get("en-orig") == "auto", str(kinds8))
    got, calls, _ = yt_video(dict(dub, language="zh-Hant"), on8, lang="en")
    check("... the same when yt-dlp's `language` is already the original's", "dub" in got[2], got[2])
    plain = dict(dub, formats=[], language="en")
    got, calls, _ = yt_video(plain, on8, lang="en")
    check("... but an English talk is still `subtitles en, automatic`", got[2] == "subtitles en, automatic", got[2])
    human_zh = dict(dub, subtitles={"zh-Hant": [{"ext": "vtt", "name": "Chinese (Traditional)"}]})
    on_zh = dict(on8, **{"zh-Hant": {"vtt": cues("人工字幕")}})
    got, calls, _ = yt_video(human_zh, on_zh, lang="en")
    check("a dubbed video's human track in the original language is asked for and read before the dub's speech",
          "人工字幕" in got[0] and got[2] == "subtitles zh-Hant" and len(calls) == 2 and langs_of(calls[1]) == "zh-Hant",
          "%s | %s | %d calls" % (got[0][:30], got[2], len(calls)))
    got, calls, _ = yt_video(human_zh, on_zh, lang="zh-TW")
    check("... and a reader of Chinese has it at once", "人工字幕" in got[0] and len(calls) == 1, "%d calls" % len(calls))
    # the Arabic dub of an English talk is no more the talk than the English dub of a Chinese one
    multi = {"title": "Keynote", "language": "en-US", "subtitles": {},
             "formats": [{"format_id": "139-0", "language": "ar", "format_note": "Arabic, low", "acodec": "x"},
                         {"format_id": "139-1", "language": "ru", "format_note": "Russian, low", "acodec": "x"},
                         {"format_id": "139-2", "language": "en-US", "format_note": "English (US) original (default), low",
                          "acodec": "x"}],
             "automatic_captions": {k: [{"url": ASR.replace("lang=en", "lang=" + k.split("-")[0])}] for k in
                                    ("ar-orig", "ru-orig", "en-orig")}}
    got, calls, _ = yt_video(multi, {"ar-orig": {"vtt": cues("arabic")}, "ru-orig": {"vtt": cues("russian dub")},
                                     "en-orig": {"vtt": cues("the talk itself")}}, lang="ru")
    check("a talk dubbed into the reader's language is read in its own words, not in the dub's",
          "the talk itself" in got[0] and got[2] == "subtitles en, automatic", "%s | %s" % (got[0][:30], got[2]))

    # a human track in the language spoken is better than YouTube's recognition, whoever asks
    ru_info = {"title": "Лекция", "language": "ru", "subtitles": {"ru": [{"ext": "vtt", "name": "Russian"}]},
               "automatic_captions": {"ru-orig": [{"url": ASR.replace("lang=en", "lang=ru")}]}}
    ru_tracks = {"ru-orig": {"vtt": cues("распознано машиной")}, "ru": {"vtt": cues("написано человеком")}}
    got, calls, _ = yt_video(ru_info, ru_tracks, lang="en")
    check("a Russian talk with human subtitles, read by an English user: the human track, named, not the recognition",
          "написано человеком" in got[0] and got[2] == "subtitles ru" and len(calls) == 2 and langs_of(calls[1]) == "ru",
          "%s | %s | %d calls" % (got[0][:30], got[2], len(calls)))
    got, calls, _ = yt_video(ru_info, ru_tracks, lang="ru")
    check("... a Russian reader has it at once, with one call", "написано человеком" in got[0] and len(calls) == 1, "%d calls" % len(calls))
    machine_only = dict(ru_info, subtitles={})
    got, calls, _ = yt_video(machine_only, ru_tracks, lang="en")
    check("... without a human track the recognition is read, and no second call is made",
          "распознано машиной" in got[0] and got[2] == "subtitles ru, automatic" and len(calls) == 1, "%s | %d calls" % (got[2], len(calls)))
    en_info = {"title": "Talk", "language": "en", "subtitles": {"fr": [{"ext": "vtt"}]},
               "automatic_captions": {"en": [{"url": ASR}], "en-orig": [{"url": ASR}]}}
    got, calls, _ = yt_video(en_info, {"en": {"vtt": cues("english words")}, "en-orig": {"vtt": cues("english words")},
                                       "fr": {"vtt": cues("mots")}}, lang="en")
    check("... nor for an English talk whose only human track is a translation", got[2] == "subtitles en, automatic" and len(calls) == 1,
          "%s | %d calls" % (got[2], len(calls)))
    news = {"title": "Headlines", "language": "en", "automatic_captions": {"en": [{"url": ASR}], "en-orig": [{"url": ASR}]},
            "subtitles": {"en-uYU-mmqFLq8": [{"ext": "vtt", "name": "English - CC1"}], "en-JkeT_87f4cc": [{"ext": "vtt", "name": "English - DTVCC1"}]}}
    got, calls, _ = yt_video(news, {"en": {"vtt": cues("recognised")}, "en-orig": {"vtt": cues("recognised")},
                                    "en-uYU-mmqFLq8": {"vtt": cues("CC ONE")}}, lang="en")
    check("... nor for a broadcaster's several caption tracks of the language (CC1, DTVCC1: 15 s each to fetch)",
          "recognised" in got[0] and len(calls) == 1, "%s | %d calls" % (got[2], len(calls)))
    pt = {"title": "Fala", "language": "pt-BR", "automatic_captions": {"pt-orig": [{"url": ASR.replace("lang=en", "lang=pt")}]},
          "subtitles": {"pt-PT": [{"ext": "vtt", "name": "Portuguese (Portugal)"}]}}
    got, calls, _ = yt_video(pt, {"pt-orig": {"vtt": cues("reconhecido")}, "pt-PT": {"vtt": cues("legendado")}}, lang="en")
    check("... but a regional variant of the language spoken is its human track (pt-BR spoken, pt-PT subtitles)",
          "legendado" in got[0] and got[2] == "subtitles pt-PT" and len(calls) == 2, "%s | %d calls" % (got[2], len(calls)))
    got, calls, _ = yt_video(ru_info, ru_tracks, lang="en", sub_langs="en")
    check("READ_PAGE_SUB_LANGS is the user's own word: no second call is made for the speaker's track",
          len(calls) == 1 and "распознано машиной" not in got[0] and "написано человеком" not in got[0], "%d calls" % len(calls))

    # YouTube answers 429 to a machine translation, and the user's `en` is one for a Russian talk: yt-dlp stopped there
    # with nothing written, so every video not in the user's own language was "no subtitles"
    ru_tr = {"title": "Лекция", "language": "ru", "subtitles": {},
             "automatic_captions": {"ru-orig": [{"url": ASR.replace("lang=en", "lang=ru")}],
                                    "en": [{"url": ASR.replace("lang=en", "lang=ru") + "&tlang=en"}]}}
    tr_tracks = {"ru-orig": {"vtt": cues("распознано машиной")}, "en": {"vtt": cues("machine translation")}}
    got, calls, _ = yt_video(ru_tr, tr_tracks, lang="en", refuse_translated=True)
    check("a Russian talk read by an English user, YouTube refusing its machine translation: the recognition is read",
          "распознано машиной" in got[0] and got[2] == "subtitles ru, automatic" and "--ignore-errors" in calls[0],
          "%s | %s" % (got[0][:30], got[2]))
    got, calls, _ = yt_video(dict(ru_info, automatic_captions=ru_tr["automatic_captions"]), dict(tr_tracks, ru=ru_tracks["ru"]),
                             lang="en", refuse_translated=True)
    check("... and the human track of the speaker's language is still asked for", "написано человеком" in got[0] and got[2] == "subtitles ru",
          "%s | %s | %d calls" % (got[0][:30], got[2], len(calls)))
    only_tr = {"title": "T", "language": "ru", "subtitles": {}, "automatic_captions": {"en": ru_tr["automatic_captions"]["en"]}}
    got, calls, _ = yt_video(only_tr, {"en": {"vtt": cues("machine translation")}}, lang="en", refuse_translated=True)
    check("... and when the refusal leaves nothing, the answer says so, not `no subtitles`",
          "refused" in got[2] and "429" in got[2] and getattr(mod8, "_VIDEO", {}).get("kind") == "limit", got[2])

    # YouTube's automatic captions roll: a cue is a screen of two rows (three on a broadcaster's), the line before and the
    # new line, whose words carry their times; a cue of 10 ms shows the new line alone before the next one; a row of one
    # space is an empty one. Every phrase stood in three cues, and in the answer three times (x3.07 the words over 48
    # real tracks, a one-hour talk of 8 700 words reaching the agent as 26 700)
    def at8(t):
        ms = int(round(t * 1000))
        return "%02d:%02d:%02d.%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)

    def timed8(text, t0):
        words = text.split()
        return words[0] + "".join("<%s><c> %s</c>" % (at8(t0 + 0.4 * (k + 1)), w) for k, w in enumerate(words[1:]))

    def rolling8(lines, rows=2):
        """The VTT YouTube writes for `lines` ([(start, text)]): each one shown from its start to the next one's."""
        out, above = ["WEBVTT\nKind: captions\nLanguage: en"], []
        for n, (start, text) in enumerate(lines):
            end = lines[n + 1][0] - 0.01 if n + 1 < len(lines) else start + 3.0
            screen = ([" "] * rows + above)[-(rows - 1):] if rows > 1 else []
            out.append("%s --> %s align:start position:0%%\n%s" % (at8(start), at8(end), "\n".join(screen + [timed8(text, start)])))
            above = above + [text]
            screen = ([" "] * rows + above)[-(rows - 1):]
            out.append("%s --> %s align:start position:0%%\n%s\n " % (at8(end), at8(end + 0.01), "\n".join(screen)))
        return "\n\n".join(out) + "\n\n"
    said8 = [(1.0, "so today we talk about captions"), (4.2, "and how they roll up the screen"),
             (7.4, "no no no that is not what I meant"), (10.6, "when you think in categories you"),
             (13.8, "underestimate how different two facts are"), (17.0, "when you think in categories you"),
             (20.2, "overestimate how different they are"), (23.4, "100"), (24.0, "percent of the time"),
             (45.0, "[Music]"), (46.5, "thank you")]
    spoken8 = [t for _, t in said8]
    want_rolled = "[0:01] " + " ".join(spoken8[:9]) + "\n\n[0:45] " + " ".join(spoken8[9:])
    got8 = [mod8.vtt_to_text(rolling8(said8, rows)) for rows in (2, 3)]
    check("YouTube's rolling captions: every line is read once, a line said again stays, a line of digits stays, "
          "and a pause of 20 s starts a block", got8[0] == want_rolled, "%d words, %r" % (len(got8[0].split()), got8[0][:120]))
    check("... a screen of three rows reads the same", got8[1] == want_rolled, "%d words, %r" % (len(got8[1].split()), got8[1][:120]))
    rolled_info = {"title": "Talk", "language": "en", "automatic_captions": {"en": [{"url": ASR}], "en-orig": [{"url": ASR}]}}
    got, calls, folder = yt_video(rolled_info, {"en": {"vtt": rolling8(said8)}, "en-orig": {"vtt": rolling8(said8)}}, lang="en")
    kept8 = open(os.path.join(folder, "transcript.vtt"), encoding="utf-8").read() if os.path.isfile(
        os.path.join(folder, "transcript.vtt")) else ""
    check("... the answer says so and the cues kept as transcript.vtt hold each line once, with the time it came in",
          got[0] == want_rolled and got[2] == "subtitles en, automatic" and kept8.startswith("WEBVTT")
          and kept8.count("underestimate") == 1 and kept8.count("when you think in categories you") == 2
          and "00:00:13.800 --> 00:00:16.990\nunderestimate how different two facts are" in kept8 and "<c>" not in kept8,
          "%r | %s | %d words kept" % (got[0][:50], got[2], len(kept8.split())))
    human8 = ("WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nfirst line\n\n00:00:02.500 --> 00:00:04.000\nfirst line\nsecond line\n\n"
              "00:00:04.000 --> 00:00:05.500\nsecond line\nthird line\n")
    check("a person's roll-up captions have no word times and are read as they were (this is YouTube's automatic form only)",
          mod8.vtt_to_text(human8) == "[0:01] first line first line second line second line third line",
          mod8.vtt_to_text(human8))
    got, calls, folder = yt_video({"title": "Talk", "language": "en", "subtitles": {"en": [{"ext": "vtt", "name": "English"}]}},
                                  {"en": {"vtt": human8}}, lang="en")
    check("... and a track with no rolling in it is kept as transcript.vtt byte for byte",
          open(os.path.join(folder, "transcript.vtt"), "rb").read() == open(os.path.join(folder, "video.en.vtt"), "rb").read()
          and got[2] == "subtitles en", got[2])
    karaoke8 = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nsing<00:00:01.500><c> along</c>\n\n00:00:05.000 --> 00:00:07.000\nsing<00:00:05.500><c> along</c>\n"
    check("a track with word times and no line carried up is not rolling either: a line said twice is read twice",
          mod8.vtt_to_text(karaoke8) == "[0:01] sing along\n\n[0:05] sing along", mod8.vtt_to_text(karaoke8))

    # a video that has not started yet, and a refusal: what happened, and what to do
    upcoming =b"ERROR: [youtube] 1hEmuJOxNTI: This live event will begin in 38 days.\n"
    got, calls, _ = yt_video(None, {}, rc=1, err=upcoming)
    check("a video that has not premiered: the note says so, with what YouTube said",
          "has not started yet" in got[2] and "38 days" in got[2] and "READ_PAGE_SUB_LANGS" not in got[2]
          and getattr(mod8, "_VIDEO", {}).get("kind") == "upcoming" and "--refresh" in getattr(mod8, "_VIDEO", {}).get("advice", ""), got[2])
    got, calls, _ = yt_video(None, {}, rc=1, err=b"ERROR: [youtube] abc: Premieres in 2 hours\n")
    check("... a premiere too", "has not started yet" in got[2] and "2 hours" in got[2], got[2])
    got, calls, _ = yt_video(None, {}, rc=1, err=b"ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests\n")
    check("a refused request for subtitles is said, not 'no subtitles'",
          "refused" in got[2] and "429" in got[2] and getattr(mod8, "_VIDEO", {}).get("kind") == "limit", got[2])
    got, calls, _ = yt_video(None, {}, rc=1, err=b"ERROR: [youtube] abc: Private video. Sign in if you've been granted access\n")
    check("any other error yt-dlp stops with is said in its words", "Private video" in got[2] and getattr(mod8, "_VIDEO", {}).get("kind") == "error", got[2])
    got, calls, _ = yt_video({"title": "T", "language": "en"}, {}, rc=0)
    check("no error and no track is `no subtitles`, with the way to ask for another language",
          got[2].startswith("no subtitles in en") and "READ_PAGE_SUB_LANGS" in got[2] and getattr(mod8, "_VIDEO", {}).get("kind") == "", got[2])

    got, calls, _ = yt_video({"title": "T", "language": "zh-Hant", "subtitles": {"live_chat": [{"ext": "json"}]}},
                             {"live_chat": {"json": "{}"}}, lang="en")
    check("a live chat replay is no subtitle track: a video that has only that is not asked again for it",
          len(calls) == 1 and got[2].startswith("no subtitles in en"), "%d calls | %s" % (len(calls), got[2]))

    # the answer: the advice, the missing line, and no road tried that cannot have a track
    mod9 = module()
    mod9.VIDEO_URL = re.compile(r"/watch-page")
    c9 = mod9.caps()
    c9["cli"]["yt-dlp"] = "yt-dlp"
    mod9.caps = lambda *a, **k: c9
    real9 = mod9.run
    mod9.run = lambda cmd, timeout=120, **kw: ((1, b"", upcoming) if cmd and cmd[0] == "yt-dlp" else real9(cmd, timeout=timeout, **kw))
    tried9 = []
    mod9.transcript_video = lambda url, workdir: (tried9.append("transcript-api"), ("", ""))[1]
    mod9.markitdown_video = lambda url, c: (tried9.append("markitdown"), ("", ""))[1]
    m, text = inproc(mod9, [s.public.url("/watch-page")])
    miss9 = [x for x in m.get("missing") or [] if x.get("what") == "transcript"]
    check("a video that has not started: the page is read, the advice says why there is no text and when to come back",
          m.get("status") == "ok" and "VIDEO-SITE-PAGE" in text and (m.get("advice") or "").startswith("the video has not started yet")
          and "38 days" in (m.get("advice") or "") and "--refresh" in (m.get("advice") or ""), (m.get("advice") or "")[:140])
    check("... the missing line has no `set READ_PAGE_SUB_LANGS`, and no other road to a track is tried",
          bool(miss9) and "READ_PAGE_SUB_LANGS" not in json.dumps(miss9) and "--refresh" in miss9[0].get("fix", "") and not tried9,
          "%s %s" % (miss9, tried9))

    # ------------------------------------------------ Jina gets the address in a POST body
    import http.server
    import socketserver
    got = []

    class Jina(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n).decode("utf-8", "replace")
            got.append(("POST", body, self.headers.get("X-No-Cache", "")))
            cached = len(got) == 1 and "/cached" in body
            text = ("Warning: This is a cached snapshot of the original page, consider retry with caching opt-out.\n\n"
                    if cached else "") + "Title: Doc\n\nMarkdown Content:\n" + "JINA-TEXT " + EN
            if "/walled" in body:
                text = "Title: Just a moment...\n\nMarkdown Content:\nChecking your browser before accessing the site."
            b = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            got.append(("GET", self.path, ""))
            self.send_response(405)
            self.end_headers()

        def log_message(self, *a):
            pass

    jsrv = socketserver.ThreadingTCPServer((PUBLIC, 0), Jina)
    jsrv.daemon_threads = True
    threading.Thread(target=jsrv.serve_forever, daemon=True).start()
    mod4 = module()
    mod4.JINA_URL = "http://%s:%d/" % (PUBLIC, jsrv.server_address[1])
    mod4.READERS = ("jina",)               # the chain itself is tests/sources.py; nothing real is asked
    os.environ.pop("FIRECRAWL_API_KEY", None)
    target = "https://docs.example.org/путь/#/quickstart"
    text, eng, st, note = mod4.external_read(target, mod4.caps())
    sent = got[-1] if got else ("", "", "")
    check("Jina is asked by POST, with the #/ route and the Cyrillic path intact",
          sent[0] == "POST" and json.loads(sent[1] or "{}").get("url") == target and "JINA-TEXT" in (text or ""),
          "%s %s" % (sent[0], (sent[1] or "")[:80]))
    got.clear()
    text, eng, st, note = mod4.external_read("https://example.org/cached", mod4.caps())
    check("a cached snapshot is asked again with x-no-cache", len(got) == 2 and got[1][2].lower() == "true"
          and "JINA-TEXT" in (text or ""), str([(g[0], g[2]) for g in got]))
    got.clear()
    text, eng, st, note = mod4.external_read("https://example.org/walled", mod4.caps())
    check("a wall that Jina hit is not text", not text, note[:70])
    jsrv.shutdown()

    # ------------------------------------------------ no curl_cffi and no curl - urllib reads the page
    mod5 = module()
    caps0 = mod5.caps()
    caps0["libs"]["curl_cffi"] = False
    mod5.caps = lambda: caps0
    real_which = mod5.which
    mod5.which = lambda name: None if "curl" in str(name) else real_which(name)
    m, text = inproc(mod5, [s.public.url("/utf8")])
    check("without curl_cffi and curl the page is still read (urllib)",
          m.get("status") == "ok" and "булок" in text and "urllib" in str((m.get("chain") or {}).get("tried")),
          "%s %s" % (m.get("status"), (m.get("chain") or {}).get("tried")))

    # ------------------------------------------------ defuddle knows the page's address
    if mod5.which("defuddle") or real_which("defuddle"):
        r = run_read(s.public.url("/relative"))
        body = r.file("content.md")
        check("relative links resolve against the page, never about:blank",
              "about:blank" not in body and s.public.url("/docs/next.html") in body
              and s.public.url("/part2.html") in body,
              [ln for ln in body.split("\n") if "next" in ln][:1])
    else:
        check.skip("defuddle and relative links", "defuddle is not installed here")

    # ------------------------------------------------ a wall: the advice names no step that only repeats
    # 2026-11-19: --alternate opened none of 8 walls in a measured run (the browser had been at 6, and
    # met the same wall at the other 2), and agents at a wall spent a call on it, because the advice
    # named it
    wall = ("<!doctype html><html><head><title>Just a moment...</title></head><body><h1>Just a moment...</h1>"
            "<p>Checking your browser before accessing the site.</p></body></html>").encode("utf-8")
    pub["/wall"] = (403, H, wall)
    mod6 = module()
    mod6.SKIP.add("browser")
    asked = []
    mod6.external_read = lambda url, c, refresh=False: (asked.append(url), (
        "", "reader:jina/defuddle.md", 403, "jina: the page answered it 403"))[1]
    m, _ = inproc(mod6, [s.public.url("/wall")])
    adv = m.get("advice") or ""
    check("a wall, readers not allowed yet: the advice is --allow-external and nothing else",
          m.get("status") == "blocked" and "--allow-external" in adv and "--alternate" not in adv and not asked, adv)
    m, _ = inproc(mod6, [s.public.url("/wall"), "--allow-external"])
    adv = m.get("advice") or ""
    check("a wall the readers did not pass either: no flag is named, the next step is another source",
          m.get("status") == "blocked" and bool(asked) and "--" not in adv and "the public readers were stopped too" in adv
          and "another source" in adv, adv)
    mod7 = module()
    mod7.SKIP.add("browser")
    pub["/hollow"] = (200, H, b"<!doctype html><html><head><title>App</title></head><body><div id='root'></div>"
                              b"<script>render()</script></body></html>")
    m, _ = inproc(mod7, [s.public.url("/hollow")])
    adv = m.get("advice") or ""
    check("an empty page with no browser to render it: --alternate is not offered, a reader is",
          m.get("status") == "empty" and "--alternate" not in adv and "--allow-external" in adv, adv)

    # ------------------------------------------------ a thin app page goes to the browser by itself
    # 2026-11-19, 168 pages measured: four gave under 200 words while shipping 40 KB+ of data
    # for their own scripts (soundcloud 50 words, aliexpress 79, ivi 163, a GitHub issue 118), and
    # the browser then gave 30, 9 and 5 times the text on three of them. Only --alternate reached
    # it, and an agent on ivi kept digging in raw.html until its turns ran out.
    state = json.dumps({"items": [{"id": i, "title": "Film number %d" % i, "about": EN[:120]} for i in range(400)]})
    teaser = "<p>" + " ".join(["teaser"] * 150) + "</p>"
    shell = "<!doctype html><html><head><title>Portal</title></head><body><main><h1>Portal</h1>%s</main>%s</body></html>"
    pub["/thin-app"] = (200, H, (shell % (teaser, "<script id='__NEXT_DATA__' type='application/json'>%s</script>"
                                          % state)).encode("utf-8"))
    pub["/short-page"] = (200, H, (shell % (teaser, "<script>console.log('a short page with a script')</script>")).encode("utf-8"))
    # JSON-LD is for search engines, no script draws it: a product page with its reviews as 63 KB of
    # it went to the browser for 3.2 s and the same 144 words (2026-11-21)
    pub["/ld-json"] = (200, H, (shell % (teaser, "<script type='application/ld+json'>%s</script>" % state)).encode("utf-8"))
    mod8 = module()
    mod8.SKIP.add("browser")                     # the decision is what is tested: the browser's turn is recorded
    asked8 = []
    for path in ("/thin-app", "/short-page", "/ld-json"):
        m, _ = inproc(mod8, [s.public.url(path)])
        asked8.append([x.get("why") for x in (m.get("chain") or {}).get("skipped") or [] if x.get("tier") == "browser"])
    check("under 200 words beside 40 KB+ of the page's own data: the browser's turn; a short page with a script: not",
          bool(asked8[0]) and not asked8[1] and len(state) > 40000, "%s / %s (%d KB of data)" % (asked8[0], asked8[1], len(state) // 1000))
    check("... nor a short page whose data is JSON-LD for search engines (application/ld+json)",
          not asked8[2] and mod8.shipped_state("<script type=\"application/ld+json\">%s</script>" % state) == 0,
          str(asked8[2]))
finally:
    s.stop()

sys.exit(check.done())
