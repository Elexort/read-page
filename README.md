# read-page

**One call for every reader on the machine — and a receipt for what came back.**

![tests](https://github.com/Elexort/read-page/actions/workflows/tests.yml/badge.svg?branch=dev)
Python 3.8+ · MIT · no keys required · CLI + MCP server · v0.4.6 · **[install in three steps](#install)**

---

An agent that finds ten links usually reads seven. The other three answer with a `403`, a
JavaScript shell, or a `200` with nothing in it — and the agent quietly drops them. The facts on
those three pages never reach the answer, and nothing in the transcript says so.

`read-page` is the one call that does not let that happen. It puts every reader on the machine
behind a single command, tries them in the order that costs least, and always answers with a
header that says which engine produced the text, whether it may be only a fragment of the page,
and what to do next - then the text itself, in one answer that no agent harness has to cut. When a
page genuinely cannot be read, the answer says that too, in one of eight statuses, with a reason
and one concrete next step.

On 226 real pages picked to be hard - walls, script shells, feeds, documents, dead hosts, 404s -
it answered **202 `ok`, 6 `blocked`, 4 `login_required`, 5 `not_found`, 7 `error` and 2 `empty`,
each with its reason; no text came back short without saying so** (the 226-page check of 2026-11-06;
the shortest `ok` was a test PDF of six words).

```
read-page · ok · defuddle · content.md 24.7 KB, 389 lines · 1.9 s
files: …/pages/example.com-9c1f… (content.md, page.md, manifest.json)
outline (line, heading): …
── content.md: from line 1 of 389 ──
(the text)
── next: line 127 of 389 ──
python3 -X utf8 "/home/me/.agents/skills/read-page/scripts/readpage.py" "https://example.com/a" --allow-external --from 127 --chars 7900 --file content.md
```

## Install

read-page is an [Agent Skill](https://agentskills.io): a folder your AI agent reads when a task
calls for it. You need **Python 3.8 or newer** and **git**. Three steps:

**1. Put the folder where your agent looks for skills.** It must be named `read-page`.

| Your agent | Run once |
|---|---|
| Claude Code | `git clone https://github.com/Elexort/read-page $HOME/.claude/skills/read-page` |
| Codex, Cline, goose, and others that read the shared folder | `git clone https://github.com/Elexort/read-page $HOME/.agents/skills/read-page` |
| Cursor | `git clone https://github.com/Elexort/read-page $HOME/.cursor/skills/read-page` |
| Gemini CLI | `git clone https://github.com/Elexort/read-page $HOME/.gemini/skills/read-page` |
| OpenCode | `git clone https://github.com/Elexort/read-page $HOME/.config/opencode/skills/read-page` |
| GitHub Copilot | `git clone https://github.com/Elexort/read-page $HOME/.copilot/skills/read-page` |

`$HOME` is your home folder in macOS and Linux terminals and in PowerShell on Windows (in the old
`cmd` window write `%USERPROFILE%` instead; `~` is not understood by Windows PowerShell 5.1 or
`cmd` - it would make a folder named `~`). No git: download the ZIP from the green **Code**
button, unpack it into that place and name the folder `read-page`. Not sure where your agent
looks: ask it "where do you load skills from?".

**2. Let it install its engines** - optional: it reads without them, and much better with them.
Tell your agent *"set up the read-page skill"*, or run it yourself (the path of step 1):

```bash
python $HOME/.agents/skills/read-page/scripts/readpage.py --setup
```

(`python3` where `python` is not found, as on macOS.) It says first what it will fetch (about
400-445 MB), puts everything into one folder of its own outside the skill (it names it), needs no admin
rights, asks nothing, and names what it could not install. [Engines](#engines) has the list.

**3. Ask your agent to read something**: *"read https://example.com/article and summarise it"*.
The agent picks the skill by itself when a page matters; "use read-page" makes sure.

Update: `git -C $HOME/.agents/skills/read-page pull`, then `--setup` once more. Remove: delete the
skill's folder, and the folder `--setup` named (a little lives outside both: [Engines](#engines)).

**In this README:** [what you get](#what-you-get) · [command line](#command-line) ·
[MCP server](#mcp-server) · [one call, in order](#one-call-in-order) · [engines](#engines) ·
[flags](#flags) · [proof](#proof) · [when it cannot read a page](#when-it-cannot-read-a-page) ·
[docs](#docs)

## What you get

**The whole page, not what one tool managed.**
HTTP with real browser TLS fingerprints → three extractors → headless browser → document readers
(PDF with its tables as tables, DOCX, PPTX, XLSX, EPUB, ODT, RTF, OCR) → subtitles → archives → paid
readers. A file on this
machine goes through the same converters with no network. One command, and the agent never has to
know which tier will work.

**An answer you can cite.**
Every read's manifest has `cover` (words of the article over words visible on the page), `fragment`,
`status_reason`, the engine that won, and the candidates it beat. "This text is 87 % of the page's
words, from defuddle, 612 words" is a sentence an agent can stand behind — and a reviewer can check;
the answer's first line names the share only when the text may be a fragment (under a third).

**One system under ten tools.**
One folder per URL, one cookie jar shared by every engine, one cache with `ETag` revalidation, one
vocabulary of statuses, pictures fetched once per site and hard-linked into each page. It is the
plumbing that a hand-rolled chain of tools never gets right, in one script whose core needs nothing
beyond the standard library.

## Command line

The agent runs these for you; they also work by hand, from the skill's folder:

```bash
python -X utf8 scripts/readpage.py https://example.com/article
#   -> the answer: a header and the text (an outline and the next line when it is long);
#      content.md, page.md, manifest.json and img/ stay in the page's folder

python -X utf8 scripts/readpage.py                     # what this machine can do, and what to add
python -X utf8 scripts/readpage.py --setup             # every engine, into the skill's own environment
python -X utf8 scripts/readpage.py URL --from 127      # the next block, from the saved copy
python -X utf8 scripts/readpage.py URL --json          # the manifest instead of the text
python -X utf8 scripts/readpage.py URL --allow-external --alternate   # a thin text: the browser, every extractor
```

**Start with no URL.** `readpage.py` on its own prints the setup report: which engines this machine
already has, what each missing one would buy, and which keys are set. **`readpage.py --setup`**
installs every engine it can into the skill's own environment (see [Engines](#engines)) - one
command, no questions, no admin rights; the report then names only what it could not do, with the
command for *this* OS. Nothing is installed any other way. Run the report again after installing
anything; it reads the machine fresh every time.

The `main` branch is the skill alone - what a clone or a ZIP installs. The
[`dev`](https://github.com/Elexort/read-page/tree/dev) branch adds the tests, CI and notes;
`tools/publish.py` there makes `main` from it.

## MCP server

For a client that speaks MCP instead of loading skills (use the path of your install):

```json
{"mcpServers": {"read-page": {"command": "python",
  "args": ["/home/you/.agents/skills/read-page/scripts/mcp_server.py"]}}}
```

Two tools: `read_url(url, allow_external?, force_external?, alternate?, download?, deny_images?,
screenshots?, inline_images?, refresh?, clear_cookies?, file?, from?, ocr?)` and
`read(dir, file?, from?, ocr?)`.
Both answer with the text the CLI prints; with `inline_images` the pictures come back as image
blocks, each under its own caption, in page order.

## One call, in order

```
google docs/sheets/slides  -> export endpoint (docx/xlsx/pptx)      # the page itself is a JS shell
video                      -> yt-dlp subtitles + thumbnails         # YouTube, TikTok, VK, Vimeo, RuTube
site API                   -> Stack Exchange, npm, Hacker News, X, PubMed   # no flag; X via fxtwitter (the post number only); a failure reads the page
single file                -> magic > content-type > extension      # media_only / too_large
http  (curl_cffi, pinned TLS fingerprints, Accept: text/markdown, redirects checked per hop; curl, then urllib)
   -> server markdown/json/text -> as is
   -> html -> defuddle -> trafilatura -> readability -> html2text -> lynx/w3m   content.md + page.md
   -> dropped blocks: prose, code and tables of page.md the extractor threw away go back in place
   -> pictures (any path, last): numbered markers in place; the printed lines' into img/, a neighbour page's by hard link;
      --ocr N: the text drawn in picture N, on demand, for a model that cannot see it
   -> signals: status, chars, cover = text words / visible words, fragment, block markers, login level
headless browser (one, 20 s for load and settle by a measured rule; another only if it fails to start)
readers: firecrawl -> jina -> exa -> tavily -> defuddle.md -> wayback   # only with --allow-external; keyless ones skipped; also for a dead host or a 5xx
documents: pymupdf (a layout model for a PDF's tables) / office readers / our EPUB, ODT, RTF readers / pdftotext + OCR   # pdf, docx, pptx, xlsx, epub, odt, rtf, zip
```

Every read ends by 55 s, the CLI and MCP alike (MCP harnesses cancel a call at about 60 s), and
prints what it has. Inside that every step keeps its own bound - HTTP until 14 s before the
deadline, browser 20 s, readers 20 s, archive 20 s, converters 10 s, pictures 6 s - and the
manifest records which tiers were tried, which were skipped and why (`chain.tried`,
`chain.skipped`). defuddle runs as one worker per read, page.md is made beside it, and readability
and trafilatura run side by side in processes the deadline can stop; a page over 3 MB of HTML is
its own page.md (the 16 MB HTML spec: 155 s before, 10.5 s now).

## What comes back

```
read-page · ok · defuddle · content.md 24.7 KB, 389 lines · 1.9 s
files: .../pages/docs.example.com-6f2a... (content.md, page.md, manifest.json, img/ 6 pictures)
outline (line, heading):
      1 ## Installation
     27 ## Configuration
      …
── content.md: from line 1 of 389 ──
(the text)
── next: line 127 of 389 ──
python3 -X utf8 "/home/me/.agents/skills/read-page/scripts/readpage.py" "https://example.com/a" --allow-external --from 127 --chars 7900 --file content.md
```

One answer is at most 7 900 characters, 9 980 bytes and 495 lines, UTF-8 with LF: Cline's SDK runtime
passes 8 000 characters of any tool's result, Codex 10 000 bytes of output to a non-OpenAI model, Roo
Code 10 240, Cline's VS Code extension 500 lines, and each cuts the rest its own way; `--chars C` sets another size.
So a page that fits comes whole; a longer one comes with an outline and, under `next:`, the command that reads on,
to run as printed - it reads that block of the same file from the saved copy, without the network, and the text's
last answer ends with `── EOF content.md: lines 352-389 of 389 ──`. A `--from N` with `--file` forgotten goes on
in the file read last. Exit code 0 means an answer
was printed, whatever its status; 1 is an internal error, 2 a wrong call.

Behind the answer is the manifest (`--json` prints it):

```json
{"status": "ok",
 "url": {"requested": "https://example.com/a", "final": "https://example.com/a", "http_status": 200},
 "content": {"engine": "defuddle", "chars": 4123, "words": 612, "cover": 0.871},
 "signals": {"fragment": false, "status_reason": "612 words, engine defuddle",
             "cookies": {"sent": 1, "stored": 1}},
 "files": {"content": ".../content.md", "page": ".../page.md", "raw": ".../raw.html"},
 "dir": ".../pages/6f2a..."}
```

Three things an agent does with it: quote the text and cite `cover`; act on `advice` when
`status` is not `ok`; and stop guessing — a `login_required` is a login, not a broken skill.

The full contract is `references/manifest-schema.json` and is validated on every test run, so the
manifest shape cannot drift between releases.

## Seeing the page

Some pages have no text to read: a scan without a text layer, a canvas app, a picture that *is* the
page. `--screenshots [N]` adds the first N screens of the page as a laptop shows it, a 1280x784
window scrolled screen by screen, never scaled:

| Call | What comes back | ≈ tokens |
|---|---|---|
| `--screenshots` | screens 1-2 as one 1280×1568 picture (two pictures without Pillow or PyMuPDF) | 2 700 |
| `--screenshots 3` | screens 1-2 glued, then screen 3 alone | 4 000 |

Each screen waits for its own pictures and a quiet page (at most 0.6 s), so the pictures further
down are not blank, as the old full-page tiles left them on 9 of 12 pages. Fixed bars are hidden,
except a header on the first screen; animations are stopped. `signals.screens_needed` says how many
screens the page has when N was smaller, or when the read's deadline ended the loop - what was
taken is kept; a step of the page that fails ends the loop too, and `signals.screenshots_failed` (with a
`screenshots:` line in the header) says which step and what it said, so a read that gave no picture says
why. PDFs come as the same 1280×1568 pictures; an archive has no pages, and the manifest
says that instead of returning nothing. In MCP the pictures arrive as image blocks after the text,
each under its own caption (`screens 1-2 of 14 · 1280x1568 · 191 KB`).

## Why the aggregate beats the parts

- **The same session everywhere.** A cookie set by the HTTP tier is sent by the browser tier, a
  cookie a page sets in JavaScript is stored for the next run, and `yt-dlp` gets the same jar. A
  members-only page that read as `empty` before now reads in 4.3 s (`status=ok, 1596 chars,
  cookies.sent=1`).
- **Pictures in place, once per site.** Every picture the text shows is a numbered marker where
  the page has it, `[img #3 · 100x80 3K · alt] img/03-alt.png`, whichever engine, reader or API
  gave the text; one the extractor dropped from a paragraph comes back after it. Page folders
  start with their host, and a picture another page of the site already has is hard-linked from
  that page's folder - no request, no second copy on disk (with the 0.4 host store this avoided
  64 of 318 picture requests, 0.8 of 11.8 MB, on six Wikipedia articles).
- **Re-reads are nearly free.** One folder per URL; `--refresh` revalidates with
  `If-None-Match`/`If-Modified-Since` for the page *and every picture*, so an unchanged page costs
  a `304` and zero bytes.
- **Arbitration, not guesswork.** Candidates are scored `words + 2 × headings`, so a structured
  article beats a slightly longer bag of leftovers; the browser runs only when the text is a shell
  or a fragment.
- **One vocabulary.** Eight statuses (`ok`, `blocked`, `login_required`, `not_found`, `empty`,
  `media_only`, `too_large`, `error`), each with a reason — so a caller can decide, and a test can
  assert.

## Engines

The core is standard library only. Each engine below is optional and raises quality, and
**`readpage.py --setup`** installs all of them at once into the skill's own environment: one
command, no questions (running it is the consent), no admin rights, the same pinned versions on
every machine. It goes into one folder of the user's that every agent on the machine sees, never
the skill's - `.read-page` in the home folder on Windows (not AppData: a packaged app such as
Claude's desktop app gets a private copy of what it writes there, and no other agent would see
the environment), `~/Library/Application Support/read-page` on macOS, `$XDG_DATA_HOME` or
`~/.local/share/read-page` on Linux; `READ_PAGE_HOME` moves it (on Windows to a folder of at most 120 characters:
the environment's DLLs do not load from a longer one, and `--setup` refuses it before it fetches anything). It says
first what it will fetch: about 410 MB to download on Windows (445 on Linux, 400 on macOS) and about 0.9 GB on disk (on
Windows: the Python engines 469 MB; the browser 275; defuddle and npm 30, on the Node Playwright's wheel
carries; Python 69; the OCR packs 54 - nodejs.org's Node, 36-56 MB to fetch and 90-190 on disk, and pandoc's 226 MB, are
gone, our own readers read EPUB, ODT and RTF; measured by real installs on GitHub's runners, and the fourteen OCR packs
and osd, the four vertical packs and Fraktur's added by their sizes in the lock: 50 MB more than English alone).
From nothing it takes about a minute (63-65 s on a 12 MB/s link, of which ~41 s are downloads; on an
emulated weak laptop 94-99 s with an N100's four cores, 105-122 s on a Celeron's budget), a check of an
environment already up to date 5-8 s. Its steps run one after another: each step's work overlapped with
the next download, one download at a time, was measured and saved 10 % on a fast machine, 16-19 % on the
N100 and 7-14 % on the Celeron (2026-11-23) - left out, for under 15 %. From then on `readpage.py` and the
MCP server run under that environment's Python by themselves (POSIX: `exec`; Windows: a child process
tied to the first, +0.16 s a read), with its tools first; `READ_PAGE_SKIP=env` keeps a run in the Python it was started with, and is the way
out when the environment's Python starts and fails (an antivirus took one of its files): that read
runs in the machine's Python with an `environment:` line saying why, and `--setup` repairs it. Running
`--setup` again brings the environment up to the skill's pins and checks every engine; deleting
the folder removes it.

What it downloads is checked against hashes the skill carries, so a mirror serves the bytes, never their
checksum: the 54 Python packages by the SHA256 of every file in `scripts/setup-lock.txt` - and nothing but
them (`--require-hashes`: a package an index adds is refused, and no settings file turns the check off);
defuddle and its 26 npm packages by the SHA512 of each in `scripts/defuddle-lock.json` (`npm ci`); every
OCR pack of tessdata_fast 4.1.0 by its SHA256 in `scripts/tessdata-lock.txt`; uv's wheel, Node's archive and
PyPI's Node wheel (only where there is no Playwright wheel to take Node from - musl) by SHA256 pinned for
each platform; npm's tarball by its SHA512; our Python by the SHA256 the pinned uv carries for it. Two
downloads have no hash: yt-dlp and the five packages that float with it (`yt-dlp-ejs`, `brotli`, `mutagen`,
`pycryptodomex`, `websockets`), which follow the sites by design - the newest release that has been out three
days, checked by TLS alone, the lock's own packages in its tree still held to their hashes - and
Playwright's browser, which Playwright downloads over TLS with a size check and no hash. That is why no
source is used in plain `http://`: an index, a registry, a mirror or a download host named so is left out
and the default used, and the setup's log says so; `READ_PAGE_ALLOW_HTTP=<host>` lets a company's intranet
mirror through, and every line that uses it says it goes in plain http (anyone on that network path could
change what no hash checks). uv and Node trust the machine's own certificate store, as Python does
(`UV_SYSTEM_CERTS`, `NODE_USE_SYSTEM_CA`, unless you set them), so a proxy that inspects TLS and has its root
there works for all three.

Inside the folder, besides the engines: Node's compile cache (`cache/node-compile`), the environment's
Python bytecode (`cache/pycache`), yt-dlp's own cache (`cache/yt-dlp`) and uv's cache (`cache/uv`), which
holds each wheel the environment was built from hard-linked into it (where the file system has links, it
costs the disk almost nothing: the setup's last line and the report say how much of it is in no
environment). An update drops the old files of the packages whose pin moved from it. Outside the folder
stays the read cache (`read-page` in the temp folder: pages and cookies, 24 hours) and, for a read that
does not run in the environment, the skill's Python bytecode there. Nothing is installed by itself except
one thing: a video read in the environment looks for a newer yt-dlp every three days, in the background
(`READ_PAGE_SKIP=update` turns that off).

| Engine | What it buys | `--setup` installs |
|---|---|---|
| `curl_cffi` | passes TLS walls (npm, Medium, Reddit), ~3× faster | 0.17.0 |
| `defuddle` | the best text on docs pages; keeps picture positions | 0.19.4 and its 26 packages from the skill's lock (`npm ci`, each tarball by its SHA512; the tree npm resolved as of 2026-11-19), on the Node 24 that Playwright's wheel carries (nothing of nodejs.org is downloaded; npm is its registry tarball, SHA512 pinned; where there is no Playwright wheel - musl - nodejs.org's Node or PyPI's, SHA256 pinned) |
| `trafilatura`, `readability-lxml`, `html2text` | second opinions and the full-page fallback | 2.2.0, 0.9, 2025.4.15 |
| headless Chromium | JavaScript pages, hash routes, late mounts | Playwright 1.63's `chromium-headless-shell`; a Chrome or Edge on the machine is used for screenshots |
| `pymupdf`, `pymupdf4llm` | PDF text, its tables as tables (a small layout model, on the pages that look like they hold one), and the scanned-PDF path | 1.28.2 |
| our EPUB, ODT, ODS, ODP and RTF readers | headings, nested lists, tables with merged cells, notes, links, pictures where they stand (an RTF's too), code, formulas (ODT), a sheet's table, its text boxes and its cells' comments, a slide's text and notes (ODS, ODP), code pages (RTF); against pandoc on 52 files they lost nothing it kept, and kept the endnotes, headings, tables and non-Latin RTF it lost | built in: `scripts/docreaders.py`, the standard library alone, in a process of its own (pandoc left `--setup` on 2026-11-21) |
| `youtube-transcript-api` | a YouTube transcript when yt-dlp has none | 1.2.5 |
| OCR | scanned PDFs (3 pages a document) and `--ocr N` | tesseract 5.5.4 in `tesserocr` 2.13 with `tessdata_fast` 4.1.0, each pack SHA256 pinned: the ten languages with the most web text (`eng rus chi_sim chi_tra jpn kor deu fra spa por`) and four scripts English reads as nothing (`ara ell tha heb`), 27.4 MiB, the vertical packs of Chinese, Japanese and Korean and Fraktur's (`jpn_vert chi_tra_vert chi_sim_vert kor_vert frk`, 13.7 MiB), the packs of the user's own languages beside them, and `osd` (10.1 MiB), which tells each scanned page's script and which way up it lies, so that the page is turned upright and read with its own pack - a page printed in columns with a vertical one, a page whose script OSD is unsure of with the likeliest scripts' packs, the surest reading kept; `--setup --ocr-langs eng+hin` names more |
| `yt-dlp` | video subtitles and thumbnails | not pinned: the newest release that has been out three days, looked for again every three days by a video read |
| `pillow`, `psutil`, `python-docx`, `openpyxl`, `python-pptx` | pictures for MCP, Office files | pinned in `scripts/setup-lock.txt` with all 54 packages |

What `--setup` cannot do, it says, with this OS's command: OCR on Windows on ARM and macOS 14 or
older (no `tesserocr` build: `winget`/`brew install tesseract`), the browser's system libraries on a
bare Linux (`apt-get install` of the libraries it names), `curl`, `pdftotext` and `lynx`, which stay the
machine's own. A package with no build for the machine is left out and named with its reason and what to
do (the package manager of the machine: `apt`, `apk`, `dnf`, `zypper` or `pacman` on Linux, by its
os-release). Measured by a real install on every runner GitHub gives a public repository
(`.github/workflows/install.yml`, 2026-11-21), the floors are:

| Machine | `--setup` leaves out | What still reads |
|---|---|---|
| Linux with glibc (x64, arm64), Windows x64, macOS 15 and newer (arm64, Intel) | nothing; a bare Linux lacks the browser's system libraries, and the report names them | everything |
| Windows on ARM | PDF tables (no `pymupdf-layout` wheel), OCR (`tesserocr`) | PDF text, the office readers, EPUB, ODT and RTF; `winget install` of tesseract gives OCR |
| Alpine and other musl Linux, x64 | the browser (no Playwright build), PDF tables | everything else; Node comes from PyPI there |
| musl Linux, arm64 | the same, and PyMuPDF (PDF text then comes from `pdftotext`), OCR | `apk add poppler-utils tesseract-ocr` |
| macOS 14 and older | OCR (`tesserocr` needs macOS 15; not run in CI: GitHub retired its macOS 14 runners) | `brew install tesseract` |

Where the home folder has letters outside ASCII (a local account `Иван`) OCR still starts: by the 8.3 short
name of its data folder where the volume makes one, else by the folder's own name from its parent.

OCR languages: `--setup` fetches the ten languages with the most web text (Common Crawl's CC-MAIN-2026-43: English,
Russian, Chinese in both scripts, Japanese, Korean, German, French, Spanish, Portuguese) and Arabic, Greek, Thai and
Hebrew, scripts English reads as nothing whose packs save the most for their share of the web after those, the
vertical packs of Chinese, Japanese and Korean, and Fraktur's; the packs
of the user's own languages beside them - `READ_PAGE_LANG`'s when it is set, else Windows' display languages (its user
locale only when there are none), else the one the machine is set to (`LC_ALL`/`LANG`) and the others in the user's
list (`LANGUAGE`, a Mac's AppleLanguages), at most three; Chinese goes by script - and `osd`, tesseract's own script
and orientation detection. Each
scanned page is read with the pack of the script OSD sees on it (Chinese, Japanese and Fraktur alone, the others with English
beside them), a Latin page again with the pack of the language its words are in; a picture with the pack of its
page's text. Never all of them at once: on 40 scans in the ten languages that read at 5.6 % CER and 5.2 s a page,
against 1.4 % and 2.2 s chosen per page (English alone: 46.7 %), Korean at 35 %. Real scans as they come: a page on
its side or upside down is turned upright by OSD (42 turned copies of 14 pages: 67 -> 22 % CER), a Chinese, Japanese
or Korean page printed in columns is read with the vertical packs (27 pages of Wikisource: 104 -> 67 %, Japanese 95 ->
53), a page whose script OSD is unsure of or wrong about with the likeliest other scripts' packs (6 of 29 real pages:
90 -> 46 %), a German page in Fraktur with `frk` (17 pages: 32 -> 21 %); an upright page in a script OSD is sure of
is read as before, in the same time. A page whose script
needs a pack the machine lacks is named in `improve` with the command: `readpage.py --setup --ocr-langs eng+hin` (a
flag, the same in every shell; `READ_PAGE_OCR_LANGS` set for the `--setup` does the same) - the next plain `--setup`
keeps the packs it named; `READ_PAGE_OCR_LANGS` set for a read decides that read's. An environment set up before
reads as it did (English and the user's packs) until the next `--setup`. Without the environment the skill uses
whatever the machine has, as before. Behind a proxy it uses the machine's (`HTTPS_PROXY`, or Windows' own setting); a
company's package mirror named in `UV_DEFAULT_INDEX` or `PIP_INDEX_URL` is used for the Python
packages, and one for Node in `NODEJS_ORG_MIRROR`. Every source must be `https://` (a loopback address on this
machine may be http; `READ_PAGE_ALLOW_HTTP` names an intranet host whose plain http is used, and said so).
uv reads no `uv.toml` here (`UV_NO_CONFIG=1`: a file in a parent folder of the home would change what is
installed, which was measured), so a mirror a `uv.toml` names goes in `UV_DEFAULT_INDEX`, or the file in
`UV_CONFIG_FILE`; pip's own configuration (the user's and the system's `pip.ini` or `pip.conf`, read in pip's order)
is read for its `index-url` when no variable names an index - that is where a Chinese or a company machine keeps its
mirror, and uv does not look there. For a machine that does not reach GitHub, PyPI or nodejs.org these name a
mirror each: `UV_DEFAULT_INDEX` (Python packages), `UV_PYTHON_INSTALL_MIRROR` (our Python),
`READ_PAGE_TESSDATA_URL` (OCR data: a folder of `<lang>.traineddata`, or a template with `{lang}`; https),
`PLAYWRIGHT_DOWNLOAD_HOST` (the browser), `npm_config_registry` (defuddle, and npm's tarball, which falls back to
registry.npmjs.org), `NODEJS_ORG_MIRROR` (Node, only where there is no Playwright wheel). Whatever sends an installer elsewhere than its default, or skips a check - those variables,
a `uv.toml`, a `UV_CONFIG_FILE`, an `.npmrc`, a `pip.conf`, `NODE_TLS_REJECT_UNAUTHORIZED=0` - is named at the top
of the setup's log and in the setup report, an address as its scheme, host and port alone (no user, password or
token of a path or a query); `UV_NO_VERIFY_HASHES` is not passed on, nor is a link mode of `symlink` (`--setup`
cleans uv's cache, and an environment of links into it would lose its files), and the commands require the lock's
hashes, so they always decide. A home outside the profile on Windows (`C:\read-page`) is made the user's alone by
`--setup`, where it would have taken the ACL of `C:\` (every signed-in user may write there). An offline machine
gets a clear message and nothing changes.

### Another language, another alphabet

`READ_PAGE_LANG` (`zh-CN`, `zh-TW`, `ja`, `ru`, or a list `zh-CN,en`; unset: the system's languages in the user's order, then English)
is what the reader sends in the user's name: `Accept-Language` on every HTTP channel, the browser's locale, the
subtitle tracks yt-dlp is asked for (`READ_PAGE_SUB_LANGS` still wins; a human track before YouTube's machine
translation) and the OCR language pack. A page, a text file or a CSV that names no encoding is read by what its
characters are - GBK, Big5, Shift_JIS, EUC-KR, windows-1251, KOI8-R and KOI8-U with or without `charset_normalizer`,
Greek, Hebrew, Thai, Arabic and Central European with it - and such a reading is named a guess in the manifest and
the answer's first line (`charset gb18030 (guessed)`), a doubtful one too. A raw address with Chinese in it
(`https://例子.测试/页面`) goes out as UTF-8 through every channel, its host as a browser names it (`faß.de` is
`xn--fa-hia.de`), and the MCP server's standard input is UTF-8 whatever the code page is. Under a POSIX locale that is not UTF-8
(`zh_CN.GBK`) a folder or a document named in it is read like any other and named in its letters. The reader prints UTF-8 whatever the console's code page is: set `PYTHONUTF8=1` (or
`chcp 65001`) where a program reads its output as the console's code page. Details: `references/engines.md`.

### Keys, and what they cost

Keys are yours, never fetched or guessed. The skill never calls a paid reader without a flag.

| Reader | Cost | When it is used |
|---|---|---|
| Firecrawl (`FIRECRAWL_API_KEY`) | **1 credit per page**, including a `403`/`404` | only with `--allow-external` / `--force-external`, and only after the local tiers failed (or `--refresh` on an archived page) |
| Jina Reader (`JINA_API_KEY`, optional) | free tier with rate limits; the key lifts them | same flags, after Firecrawl |
| Exa (`EXA_API_KEY`) | 1 credit per page | same flags, after Jina: third, so its credits go to search |
| Tavily (`TAVILY_API_KEY`) | 1 credit per page | same flags, after Exa |
| defuddle.md | free, no key | same flags, last; simple pages only |
| Wayback | free | dead pages, before any paid reader |
| Site APIs: Stack Exchange, npm registry, Hacker News, fxtwitter, NCBI's E-utilities for PubMed | free, no key | automatically, for their own addresses; fxtwitter gets only the post number, NCBI only the record's |

The readers are asked in this order (measured on 14 hard pages: Firecrawl opened 11,
Exa 10, Jina 8, Tavily 7, defuddle.md 4), one at a time, at most 12 s each and 20 s in all. The first
one with real text ends the chain, so no credit is spent after it; an answer that is a wall or a few
words is not text and the next reader is asked; a `404` that a reader saw ends the chain. Once a paid
reader reached the page and met its wall (or a 401/403/429), the other paid readers are not asked -
they would meet the same wall, and in that measurement they never got past one - while the free ones still
are; a paid reader that failed for its own reason (no credits, a timeout) is replaced by the next.
A reader without its key is skipped, and a key goes only to its own service.

An internal host (loopback, RFC 1918, link-local, IPv6 private, metadata, or a name that resolves
to one of those) is **never** sent to a reader, with or without a flag. A URL that may carry a
secret (credentials, a `token=`-like parameter, a sharing or reset link, an opaque 32+ character
token) goes to a reader only with `--force-external`; a slug with digits is not a secret.
`privacy.why` says which rule held, and `privacy.mode` records the decision. Cookies are never sent
to a reader at all — a session stays on this machine.

The reader itself takes only http(s), on every redirect, picture, meta refresh and browser request,
and a public page never reaches into the local network through it: a redirect to `file://` or to
`127.0.0.1`, a picture on an internal host, a script that fetches an internal service — refused,
and `signals.browser_blocked` counts what the browser was stopped from loading. A host is checked as
the name the request goes to (escapes decoded, a name outside ASCII in punycode), and one that has
no such name is refused. The browser of a
public page has one way out, a SOCKS5 proxy of the reader's own on `127.0.0.1` (`netguard`): every
connection it opens — a redirect hop, a frame, a WebSocket included — is checked once, on the very
addresses it then goes to, and an internal one never opens. Nothing is sent anywhere else and
nothing is decrypted: the site sees the same machine and the same browser. On a machine whose
browser uses a proxy of its own the reader keeps it and checks the page's requests instead, and a
page that reached inside through a redirect gives no text. A picture gets only the site's origin
as `Referer`; on a shared `/tmp` the cache is `read-page-<uid>`, 0700.

## Flags

| Flag | Meaning |
|---|---|
| `--from N` | the block that starts at line N of the saved copy; no network. `--from "text"`: from the first line that holds it (a marker by its type and name: `--from "[tab · Plans]"`, `--from "[img #3]"`, or as it stands, so a quote cut inside a marker is found) |
| `--chars C` | how much one answer holds, in characters (UTF-16 units), whole lines: 7 900 by default, which fits every harness; 1 000 to 150 000, the bytes and lines in the same ratio |
| `--file page.md` | answer with the whole page instead of `content.md` |
| `--json` | the manifest instead of the answer |
| `--allow-external` | the URL is public: public readers and archives may be used if local engines fail |
| `--force-external` | use a reader even when the local text looks complete or the URL may carry a secret (never for an internal host) |
| `--alternate` | re-read locally by other means - the browser plus every extractor, the fullest text kept; a PDF as Markdown, with its headings (the pages that do not fit the read's time stay plain, named). For a text thinner than its page, not for a wall |
| `--download` | no size and no time limit: the response streams to disk, so a 5 GB file is a file; a long PDF's tables are all laid out |
| `--deny-images` | no picture is downloaded, the markers say so and keep the address; by default the text's go to `img/` and the markers carry the path |
| `--screenshots [N]` | the first N screens of a 1280×784 window (default 2), two glued into one 1280×1568 picture |
| `--refresh` | ignore the 15-minute cache and revalidate with `ETag`/`Last-Modified` |
| `--clear-cookies` | forget this site's stored cookies first (they otherwise live 6 hours) |
| `--dir DIR` | write into this folder instead of the cache entry |
| `--caps` | the same machine facts as the setup report, as JSON, with the environment in use |
| `--setup` | install every engine into the skill's own environment, or bring it up to date ([Engines](#engines)) |
| `--ocr-langs eng+hin` | with `--setup`: the OCR packs to fetch besides the fourteen it fetches for everyone and the user's own languages; kept for the next `--setup` |
| `--version` | skill version, manifest schema, cache build |

## Proof

| | |
|---|---|
| Random sweep, 10 queries, all results opened (2026-11-01) | 98 pages: **91 ok, 6 blocked, 1 not_found, 0 silent**; median 2.6 s, max 23.4 s |
| The 226-page check (2026-11-06), pages picked to be hard | **202 ok, 6 blocked, 4 login_required, 5 not_found, 7 error, 2 empty**, each with its reason; p50 2.1 s, max 22.9 s on a fast machine, p50 4.8 s, max 30.9 s on an emulated weak laptop |
| A set read the way `SKILL.md` says (2026-11-07): `--allow-external` first, advice followed, the outline to jump | a 34-page set **34 of 34**, 37 held-out pages no rule was tuned on **37 of 37** (each fact taken from a real Chrome; walls and paywalls by an honest status or through a reader); **1.10 calls** a question; every answer within 9 911 bytes and 309 lines, no CR; from the cache p50 0.22 s, max 0.26; UTF-8 whole in cmd, PowerShell 5.1 and 7, Git Bash and WSL under five code pages |
| Contract | every manifest in the suite validated against `references/manifest-schema.json` (17 manifests, 0 errors) |
| Tests | answer contract **217** (one check a shell the machine has - cmd, bash, PowerShell 5.1 and 7: 214 with bash alone), statuses **83**, timeouts **18**, deadline **22**, formats **164** (161 on Linux, 159 on macOS), reading **66**, sources **42**, blocks **44**, images **55**, speed **8**, MCP parallel **28**, security **53** (49 on Windows), props **83**, fixes **167**, channel **9**, setup audit **40**, environment **255** (246 off Windows; 2 fewer where no uv is found, 2 fewer with an environment set up before 2026-11-23, 4 before 2026-11-22), MCP **30**, office **3**, our EPUB/ODT/ODS/ODP/RTF readers **169** (167 on macOS), Chinese, Japanese and Korean input **228** (225 on Linux, 227 where a GBK locale is installed, 221 on macOS; 193 without curl_cffi and charset_normalizer), browser live **35**; against the real services: sources live **20** (15 without the paid readers' keys: with no Firecrawl, Exa or Tavily key set, their five checks are skipped, not failed) |
| CI | the offline suites on ubuntu (3.9 and 3.12), windows, macOS; a browser job on all three; and a real install - `--setup` from nothing into a folder with a space and Cyrillic in its path, every engine checked, the suites and a scanned PDF read through OCR under the environment's Python, `--setup` again with nothing to fetch - on Linux, Windows and macOS, x64 and arm64, a user's own clone-and-read, a bare Python, and containers of Alpine, Ubuntu 20.04 and 24.04, Debian 11, Rocky Linux 8, Fedora, Arch and openSUSE, a proxy that inspects TLS (Linux, Windows, macOS), a Windows whose Python has the code page 936 or 950 in a profile named in Chinese, README's ZIP, and the suites in a GBK locale on Linux, `tests/cjk.py` once more in UTF-8 mode there (`install.yml`) |
| Coverage | 65 % of the engine's statements |

The browser job is the interesting one: a shell that mounts in 250 ms, a shell that mounts after 11 s
with no request in flight (an empty `#app` is waited for), and a members-only page that only renders
with the session cookie — on Linux, Windows and macOS.

`READ_PAGE_DEBUG=1` writes the whole story of a read into a log file, `debug/<started>-<pid>.jsonl`
in the read's folder (`READ_PAGE_DEBUG_DIR=<folder>`: every read of a test session into that one
folder). Nothing of it reaches the answer or the manifest - the model never sees it, the log is for
whoever debugs the reader. One JSON line per event: the run (version, flags, the machine), the tools
found, every step with its cap and how it ended, every decision with what it looked at (the early
browser, the extractor's pick, the browser needed or not, its text taken or not, the status), the
browser's launch, load and every change its settle rule saw, every response and failure of the
page's requests, every picture, every exception the reader caught and went on from, and the
answer's summary. A key is named, never printed; a query value that looks like a credential is
masked. Off by default; it changes nothing else.

`readpage.py --probe N` is for testing a harness, not for reading: it prints N characters of numbered lines and
nothing else, with no network - each line its number and how many characters stand before it, a head and a tail
sentinel, 100 characters a line, ASCII so that characters, bytes and UTF-16 units are one count - so what a harness
shows of a command's output, and where it cut, can be read off what reaches the model. `probe:N` read as an address
is a page of the same lines, answered as any page is (`readpage.py probe:20000 --from 21 --chars 12000` shows what
an answer of that size sends). Over MCP, `read_url(url="probe", probe=N)` answers with the lines alone and
`read_url(url="probe:N", from, chars)` with the page ([mcp.md](references/mcp.md)).

`readpage.py --probe-units N` tells what a harness counts. Its lines are the same 100 characters, but each one's label
says its number and how many characters, UTF-16 units and bytes stand before it (`line 12 | 1100 chars 1190 utf16
1830 bytes before`), and its filler is of one kind by the line's number - line 1 ASCII (the head sentinel), 2
Cyrillic (2 bytes a character), 3 CJK (3 bytes), 4 a character past U+FFFF (2 units, 4 bytes), 5 ASCII again - so the
three counts drift apart line by line. To read it, run it in a harness with a limit you know, say `--probe-units
20000`, and take the last line the harness shows and where it cut that line: the label's three numbers, plus what the
shown part of the line adds (a character is one unit, and 1, 2 or 3 bytes for ASCII, Cyrillic and CJK; the fourth
kind is two units and 4 bytes), are the three counts at the cut, and the one that comes to the harness's limit is
the one it counts. A harness that counts characters shows more lines of it than one that counts UTF-16 units, and
one that counts bytes fewest. Over MCP, `read_url(url="probe", probe_units=N)`.

`READ_PAGE_TEST_CUT` makes the skill cut its own answer the way a harness does, after the answer is built - `middle:8000`
(Cline: about half kept at each end, `...[truncated N chars]...` between), `head:16384` (Zed), `tail:51200` (OpenCode),
`file:30000` (Claude Code: the answer in a file, a note with its first 2 000 characters) -, the CLI's answer and the MCP
result's text alike, so that a model can be taught to go on under each cut ([answer.md](references/answer.md#for-testing-the-skill)).

## When it cannot read a page

It says so, and says what to do:

| Status | What the caller learns |
|---|---|
| `blocked` | a wall answered - a challenge header or markup, a wall's words in any of 20 languages, or HTTP 403/419/429/451; archive or reader may have it (`advice` says which flag) |
| `login_required` | a login marker was found; this skill does not log in |
| `not_found` | a real `404`/`410`, or a soft-404 page |
| `empty` | the page is a shell that no engine could fill, or the text was below the floor; a document with no word of its own; a file named as an archive that is none (a `.doc` saved as `.docx`) |
| `media_only` | the URL is a file; it was saved, not parsed |
| `too_large` | over the parse limit; the bytes are on disk as `raw.*` |
| `error` | the host did not answer, the transfer broke after a stub, the server answered 4xx/5xx (its own page is kept as the text), or an archive is cut or damaged and its whole members hold under 40 words, or a PDF is cut or damaged and the pages that opened hold under 40; the reason is in `status_reason` |

## Docs

`SKILL.md` (the procedure for an agent, about 1 400 tokens) · `references/answer.md` (the answer,
its files, statuses, flags, privacy, limits, cookies, pictures, video) · `references/engines.md`
(every tier, timeout and failure mode) · `references/documents.md` · `references/endpoints.md` ·
`references/mcp.md` · `references/video.md` · `references/manifest-schema.json` ·
[`KNOWN-ISSUES.md`](https://github.com/Elexort/read-page/blob/dev/KNOWN-ISSUES.md) (301 rows: 249 fixed, 4 planned, 48 by design) ·
[`CHANGELOG.md`](https://github.com/Elexort/read-page/blob/dev/CHANGELOG.md) - both on the `dev` branch, with the tests

## License

MIT. `--setup` fetches each engine from its own source under its own license (html2text GPL-3.0+,
PyMuPDF, pymupdf4llm and its layout model AGPL-3.0 or Artifex's commercial license, the rest
permissive); the skill ships none of them.
