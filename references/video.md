# Video: what is read today, and what a real "video understanding" would cost

Status 2026-11-01. This file is a decision record: it says what works now, what does
not, and why the usual "chunk + embed + ASR + OCR" recipe is not simply adopted.

## What works today (and how)

| Input | Path | Output |
|---|---|---|
| YouTube watch / shorts / live, TikTok, Vimeo, VK, RuTube, ... | `yt-dlp --skip-download --write-subs --write-auto-subs --sub-langs $READ_PAGE_SUB_LANGS --sub-format vtt` (the tracks: `READ_PAGE_SUB_LANGS`, else the user's language, then English, then the track the video speaks in - `zh-Hans,zh-CN,zh,en,.*-orig` for `READ_PAGE_LANG=zh-CN`, `en,.*-orig` for an English user; none of them: one more call for the language the video's own info names). The track read: a human one in the user's languages first, then the words as spoken (speech recognition), YouTube's machine translation (its address asks for `tlang=`) only when there is nothing else; the answer's first line names it | `content.md`: transcript in blocks of up to 30 s, each starting with `[0:18] ...`; `transcript.vtt` kept beside it |
| a page with an embedded player | the page text, plus the player iframe is *not* followed | the text of the page, not of the video |
| a video **file** (`.mp4` URL, `Content-Type: video/*`) | magic/type detection -> `media_only` | the file is saved, no text, no transcription |
| audio file | `media_only` | the file is saved, no text |

Why the timestamps matter: they cost nothing (the VTT already has them) and they turn a transcript
into something a document can cite. A cue every two seconds is noise, so cues are grouped until
either a 2-second gap or 30 seconds of speech - that is `vtt_to_text(block_seconds=30)`.

Limits today: captions only, one track per read (a human track in the user's languages, else the words as
spoken, else - named so - YouTube's machine translation), no translation of our own, no speaker labels, no
confidence. A video without captions produces an empty text with an honest note.

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

## Undecided

- Is ASR worth a 75-500 MB model download (and ffmpeg for the audio)? An opt-in flag, or never?
- Frame OCR: only for "no captions", or also when a video has slides with text? (The second case
  can double the run time for little gain.)
- A hard cap: "a video longer than N minutes is not transcribed; here is the transcript command to
  run yourself"?
