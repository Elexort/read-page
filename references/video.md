# Video: what is read today, and what a real "video understanding" would cost

Status 2026-11-01. This file is a decision record: it says what works now, what does
not, and why the usual "chunk + embed + ASR + OCR" recipe is not simply adopted.

## What works today (and how)

| Input | Path | Output |
|---|---|---|
| YouTube watch / shorts / live, TikTok, Vimeo, VK, RuTube, ... | `yt-dlp --skip-download --write-subs --write-auto-subs --sub-langs $READ_PAGE_SUB_LANGS --sub-format vtt/srt/best` (the tracks: `READ_PAGE_SUB_LANGS`, else the user's language, then English, then the track the video speaks in - `zh-Hans,zh-CN,zh,en,.*-orig` for `READ_PAGE_LANG=zh-CN`, `en,.*-orig` for an English user; none of them, or only a machine's: one more call for the language the video's own info names). The track read: a human one in the user's languages first, then the human one in the language the speaker uses, then the words as spoken (speech recognition), the speech recognition of a dub, YouTube's machine translation (its address asks for `tlang=`) only when there is nothing else; the answer's first line names it | `content.md`: transcript in blocks of up to 30 s, each starting with `[0:18] ...`; `transcript.vtt` kept beside it |
| a page with an embedded player | the page text, plus the player iframe is *not* followed | the text of the page, not of the video |
| a video **file** (`.mp4` URL, `Content-Type: video/*`) | magic/type detection -> `media_only` | the file is saved, no text, no transcription |
| audio file | `media_only` | the file is saved, no text |

Why the timestamps matter: they cost nothing (the VTT already has them) and they turn a transcript
into something a document can cite. A cue every two seconds is noise, so cues are grouped until
either a 2-second gap or 30 seconds of speech - that is `vtt_to_text(block_seconds=30)` (a gap is the time between
two cues' starts; for YouTube's rolling captions it is the time since the line before was last spoken, below).

Limits today: captions only, one track per read (a human track in the user's languages, else the human track in
the language the speaker uses, else the words as spoken, else - named so - YouTube's machine translation), no
translation of our own, no speaker labels, no confidence. A video without captions produces an empty text with an
honest note.

yt-dlp is the one engine `--setup` does not pin: the sites change under it
from week to week. `--setup` installs `yt-dlp[default]` - with yt-dlp-ejs, the scripts for
YouTube's JavaScript challenges - in the newest release that has been out three days (wheels only,
under the constraints of the lock the environment was built from, a copy of which `--setup` keeps in
the environment's own folder; the three days hold only what floats: yt-dlp, yt-dlp-ejs, brotli,
mutagen, pycryptodomex, websockets), and a video read in the environment starts a look for a newer
one every three days, in a process of its own that the read does not wait for (`READ_PAGE_SKIP=update`
turns it off, and `--setup` updates it too). It never goes backwards: it asks for `yt-dlp[default]>=`
the version installed, and a result older than that is put back. `ytdlp.stamp` in the environment's
folder is touched when an update has worked, never before it starts; a look that failed leaves
`ytdlp.failed`, and no read starts another within the hour; the update holds `ytdlp.lock` (one at a
time; a `--setup` waits for it and then holds it itself), and it is not started at all where a
Windows job around the read would end it with the read. The
environment's yt-dlp is given the environment's Node (`--js-runtimes node:<path>`): a YouTube read
then solves the challenge when one is asked ("Solving JS challenges using node"), 4.8 s
against 2.8 s without it. A machine's own yt-dlp is left as it is.

### Which text a track is

Measured on a census of 222 public videos (2026-11-22: YouTube in nine languages, Bilibili, RuTube), 199 of whose
infos could be read (163 YouTube, 31 RuTube, 5 Bilibili), as an English, a Russian, a Chinese and a German reader.

- **The format.** yt-dlp is asked for VTT, then SRT, then the best the site has (`--sub-format vtt/srt/best`).
  A site without VTT gives what it has: RuTube's automatic subtitles come as SRT - 13 of its 31 readable videos
  had them, and the answer said "no subtitles" while yt-dlp wrote `video.ru.srt`. `scripts/subtitles.py` turns SRT,
  SBV, TTML, DFXP, YouTube's srv1-3 and json3, ASS and LRC into the same WEBVTT cues, so the blocks and
  `transcript.vtt` are the same whatever the site sent. TTML is read by its elements' local names - EBU-TT-D, the
  broadcasters' own, writes `<tt:p>` - and its attributes in either quote; a paragraph's time is its own, else its
  spans', relative to a `<div>` that has one; a track yt-dlp named by its address's `.xml` is read as the TTML or the
  YouTube XML it holds (KNOWN-ISSUES 305). A cue's text is escaped in the WEBVTT the module writes, as WebVTT asks,
  and a cue is read back tags first, then entities: `<`, `>` and `&` stand in the transcript as they were said (an
  SRT's "x < y and y > z" lost its middle, a VTT's `&amp;` and `&gt;&gt;` stayed escaped; KNOWN-ISSUES 306). The
  file yt-dlp wrote is read by its BOM (UTF-8, UTF-16, UTF-32), else as UTF-8, else by the guess a page's bytes get:
  a UTF-16 SRT gave no cue, a cp1251 one U+FFFD (KNOWN-ISSUES 307); `transcript.vtt` is UTF-8. An ASS line's
  vector drawing (`{\p1}m 0 0 l ...{\p0}`, a sign's shape) is no words (KNOWN-ISSUES 308). A track a site names automatic (RuTube: `Русский • Авто`) is
  named so in the answer, though yt-dlp lists it among the human ones. The 13 RuTube videos read 2 100 to 17 400
  words each; the 18 with no track at all read as before.
- **A dub.** A dubbed video offers its audio in several languages (60 of the 163 YouTube videos did: YouTube's
  automatic dubbing), and yt-dlp's `language` names the default one, which can be the dub's (`en` for a Chinese
  news video whose original is `zh-Hant`; a yt-dlp of today names the original). The speaker's language is the audio
  marked original (`format_note`), else `language`. A speech recognition made from audio in another language is the
  speech of a dub, not the speaker's words: the answer names it (`subtitles en, automatic, of a dub (original audio
  zh-Hant)`), and a track in the speaker's own language - human, or speech recognition - is read before it. Every
  automatic track's name has `: numbers and names may be misheard` beside it in the answer's first line
  (KNOWN-ISSUES 366). One
  more case is named the same way and is not a dub: a video whose original audio YouTube takes for English while
  it is spoken in Russian lists the Russian recognition as a dub's (1 of the 39 videos with a dub's recognition).
  Of the 39: 7 have only that (5 Chinese news videos with the English dub's, a Portuguese one and the Russian talk
  above), and 14 list the recognition of three dubs or more - up to 19 `-orig` tracks, which `.*-orig` asks for
  all: 13-19 s a read, inside the 20 s step but not by much.
- **A human track in the speaker's language** is asked for once more when the first call brought only speech
  recognition (or a dub's, or a machine translation) and the user's languages do not include it: an English reader
  of a Russian talk with human `ru` subtitles was handed YouTube's recognition. One more call, 4-13 s more, and the
  answer names the track (`subtitles ru`). The names of a language's variants count (`pt-BR` spoken, `pt-PT`
  subtitles; `zh-Hant`, `zh-TW`), several tracks of one language named by an id (`en-uYU-mmqFLq8`: a broadcaster's
  CC1, DTVCC1, each a live-caption track that took 15 s to fetch) do not, nor does the live chat replay or Bilibili's
  comments (`live_chat`, `danmaku`: they are listed with the subtitles and are not).
- **A machine translation is refused, and that is not the end.** YouTube answers HTTP 429 to a request for its
  machine translation, and the user's `en` is one for a Russian talk. yt-dlp then stopped with no track and no
  info file written, so a Russian, Spanish or Portuguese talk read by an English user, a Chinese one by a Chinese
  user, was "no subtitles" (16 of the 41 videos an English user read for real: every YouTube video not in English
  and every one with many dubs). The call carries `--ignore-errors`: the
  refused track is a warning, the others and the info arrive.
- **YouTube's automatic captions roll, and are read line by line.** Its VTT shows a screen of two rows (a broadcaster's,
  three): the line before and the new line, whose words carry their times (`<00:00:13.620>`), and a cue of 10 ms
  shows the new line alone before the next comes. A phrase stood in three cues, and the reader, which dropped a cue
  only when it equalled the one before, gave the agent x2.97 the words (a one-hour talk of 8 800 words as 26 400): 169
  of the 183 automatic files of 125 real videos; the other 14 are a person's text that yt-dlp lists as automatic.
  `subtitles.rolled_cues()` takes a track that has word times and a row carried up: the bottom row of a cue is the new
  line, whatever it says (a line the speaker says twice stands twice), a row above it that is the line the screen
  showed last is carried and left out, and a caption row of digits alone is a line. A pause is counted from when the
  line before was last spoken - a line is shown until the next one comes, so the cues have no gaps - and a block ends
  at a pause of 2 s or 30 s: 18 311 blocks of the 48 clips (Japanese apart), 9.5 words of speech each, became 2 961 of
  59. The
  result against the measurement's own rule ("a line equal to one of the last three is a repeat"): every line of
  the track, once, and 348 lines more, which are said again. `transcript.vtt` holds one cue per line, with the time
  it came in and the cue's end; yt-dlp's own file, with the word times, stays in the folder as `video.<lang>.vtt`. A
  person's track has no word times and is read as it was, a roll-up one too (4 of the 100 human tracks repeat their
  lines, x1.5 the words, and still do): 99 of the 101 human tracks, the 25 RuTube tracks and the 14 "automatic"
  files that are a person's text are byte for byte the same, in the text and in `transcript.vtt`; the other 2 human
  tracks are a broadcaster's live captions (`es-uYU-mmqFLq8`, `pt-uYU-mmqFLq8`) in the rolling form, and read once.

What the answers did, the census's infos run through the code before and after with a stand-in for yt-dlp that has
exactly the tracks the info lists (796 answers: 199 videos, four users; and again with YouTube refusing its
translations, as it does today) and 41 videos read for real by an English user, 6 and 7 of them by a Chinese and a
Russian one: where YouTube answers its translations, 618 answers are the same, 28 the same text with the dub named,
52 (RuTube) were nothing and are the transcript, 10 a machine's recognition and are a human track, 88 a dub's
recognition and are the speaker's own (22 videos); none is worse. Where it refuses them, 244 are the same and 470
were "no subtitles" and are the recognition, 44 the human track, 22 the dub's speech, 10 a dub's recognition and are
the speaker's own. Real, an English reader: 28 of 41 better, 6 the same, 5 the same text with the dub named, the
premiere said instead of "no subtitles", and a RuTube read that ran out of time (read at the rerun); the Chinese and
the Russian reader's 13 videos: 10 better, 1 the same, 2 the same text, one named `subtitles ru` for a recognition
before (without the info file nothing says which: the info arrives now).

### What a video that gives no transcript answers

The page is read as a page and `signals.no_transcript` says why; the `advice` and the `missing:` line name what to
do. yt-dlp's own words decide it - its last `ERROR:` line, or the warning of a track it was refused:

| yt-dlp said | the answer |
|---|---|
| a premiere or a live event that has not started (`Premieres in 2 hours`, `This live event will begin in 38 days.`) | `advice: the video has not started yet (…): it has no subtitles until it has aired; read it again after that, with --refresh`, and `missing: transcript - read it again after it has started, with --refresh`. It was `no subtitles in en,ru` and `missing: transcript - set READ_PAGE_SUB_LANGS`, which cannot help. No other road to a track is tried (youtube-transcript-api and markitdown cannot have one either); the page's own text, title and description, is the answer |
| HTTP 429, too many requests, and nothing else arrived | `advice: the site refused the request for subtitles (…): try again in a few minutes, with --refresh` |
| any other error (a private or members-only video, an age check, a country block, a bot check) | `advice: yt-dlp stopped with: …`: its words, not "no subtitles" |
| nothing, and no track | `no subtitles in en,ru (set READ_PAGE_SUB_LANGS to change)`, the page read as a page |
| the read's time ran out before it ended | `advice: yt-dlp did not finish in 20 s …: read it again, with --refresh` |

`--refresh` is named because the answer of a read of the page is kept 15 minutes. Only subtitles are asked of
YouTube (`--skip-download`): a stream address, which answers 403 until its `available_at` (a few seconds after the
info), is never requested, so that wait is not met on this path. A URL that is a media file is the other path, and
a file cut in transit (the connection broke, the server stopped sending, the time ran out) was `media_only` with a
short file, said nothing of the cut, and had no advice. It is `error` (`the connection broke after 11K of 1.9M of
the video file`) or, when it was still arriving as the time ran out, `too_large` (`rerun with --download: no time
limit, the file arrives whole`), and what arrived is not kept: a cut fragmented MP4 (YouTube's DASH) opens only as
a stream, a cut MP4 with its index at the end not at all.

## The usual recipe, and why it is not copied

The recipe below is correct for a chat product that answers questions about a long video:

1. split the video into segments, 2. embed audio and key frames, 3. retrieve the relevant segments
per question, 4. run ASR (Whisper) and OCR (frames) as the foundation.

For this skill the retrieval step is already performed by the *caller*: an agent reads one URL and
searches its own text (`content.md`, `page.md`, block by block with `--from`). Building a
vector index inside a CLI would add an embedding model, a database and a query interface - three
moving parts - to duplicate something the model does for free on a 250 000-character transcript.
So **step 3 is deliberately out of scope**; steps 1 and 2 are what would actually add capability.

## What would add capability, in order of value per hour

| Step | What it buys | Cost | Risk |
|---|---|---|---|
| ASR fallback with `faster-whisper` when no captions exist (and for audio files) | a talk without subtitles becomes readable; podcast links too | model download 75-500 MB per size, CPU 0.3-1x realtime on this class of machine; ~150 lines + a test with a 10-second synthetic tone | a long video turns a 3-second call into minutes; must be opt-in (`READ_PAGE_ASR=1`) or capped by duration |
| key frames + OCR (`ffmpeg -vf select=gt(scene,0.3)`, then tesseract) | slides, screencasts, charts: text that nobody speaks | ffmpeg (no longer looked for: the reader never runs it; this would add it back); 10-20 frames x 90 ms OCR | frame OCR on video with subtitles is redundant; gate on "no captions" or "slides detected" |
| speaker labels / diarisation | interviews and hearings | pyannote or WhisperX, tens of MB, HF token | heavy dependency, licence questions |
| translation of the transcript | a Japanese video read in Russian | an API call, costs money | product decision, not code |

Recommendation: **timestamps now (done), ASR next only
if a real need appears, frame OCR after that.** Video is not a priority for this skill: the local
wins are on text pages, and every video feature multiplies runtime on a class of input that is rare
in agent work.

## What we will not do

- feed the raw video stream anywhere: it is the most expensive possible representation;
- keep a vector store inside the skill;
- transcribe by default: captions are free and instant, ASR is neither.

## Decided (2026-11-22, measured)

- **No local speech recognition.** Where a platform's automatic track exists, Whisper small int8 is not
  better than it: pooled WER 8.9 % automatic, 10.9 % Whisper small, 15.1 % Whisper base over 43 YouTube
  clips in six languages, a tie on the professionally captioned ones (5.9 against 6.5 %), Russian 9.9
  against 16.2 %; 42 questions on names and numbers answered alike. It would add 287-345 MB to `--setup`,
  4-5 s of CPU per audio minute and only 9-10 minutes of speech a read, for the one gap it closes: Chinese
  on YouTube (no speech recognition there), Bilibili to an anonymous client, RuTube videos with no track.
- **No frame OCR for now**: a few dozen slide words a lecture, half of them noise, for the video's bytes.

- A hard cap: "a video longer than N minutes is not transcribed; here is the transcript command to
  run yourself"?
