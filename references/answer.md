# The answer, its files and its rules

What `SKILL.md` says in a line, in full: the answer, the files it points at, every status, every
flag, the privacy and network rules, the limits, cookies, pictures, tabs and video.

## The answer

`readpage.py URL` prints a header - status, engine, size, the work folder, `reason:`, `ignored:`, `document:`,
`screenshots:`, `advice:`, `missing:`/`improve:` - then the text: whole when it fits, otherwise an outline with line numbers,
the first block and the command that goes on. `document:` is what a document's reader says of what it
left out or could not read (parts that do not unpack, a table cut at its caps, pictures past its limit or in
a format no browser shows, its time run out, its own error: `signals.document_note`); `screenshots:` is there
only when `--screenshots` took no picture (`none taken`) or stopped early (`stopped early`, beside the screens that
came) because a step of the page failed - the step and what it said (`signals.screenshots_failed`); `missing:` is
what this machine lacks, never that.

```
read-page · ok · defuddle · content.md 24.7 KB, 389 lines · 1.9 s
files: /tmp/read-page-1000/pages/example.com-9c1f… (content.md, page.md, manifest.json)
outline (line, heading):
      1 ## Installation
     27 ## Configuration
      …
── content.md: from line 1 of 389 ──
(the text)
── next: line 127 of 389 ──
python3 -X utf8 "/home/me/.agents/skills/read-page/scripts/readpage.py" "https://example.com/a" --allow-external --from 127 --chars 7900 --file content.md
```

The lines around the text are dry (KNOWN-ISSUES 276): above it `── content.md: from line 1 of 389 ──`, every block
alike (a text that fits too: `from line 1 of 12`) - where the text starts, never where it ends: a harness that keeps
an answer's head and cuts its tail (Zed) cuts `next:` off and leaves this line, and a model took an end named there
for the end of what it had seen (KNOWN-ISSUES 279); below it, while text remains, `── next: line 127 of 389 ──` and
on a line of its own the command that reads on, literal, so that a model copies it whole - the interpreter by the
name the agent started the skill with (the first process's, which the environment's child is handed), `-X utf8`,
the script by its absolute path in forward slashes, the address and `--dir` in double quotes, the flags that matter
if the saved copy is gone and the page is read again (`--allow-external`, `--force-external`, `--alternate`,
`--deny-images`, `--download`, `--dir`; never `--refresh`, whose every step would fetch again and could move the
lines, `--clear-cookies`, `--screenshots`, `--ocr` or `--json`), then `--from N --chars C --file F`, C the size this
answer was asked with. It runs as printed in bash, PowerShell 5.1 and 7 and cmd; its paths are in the locale's letters,
as the `files:` line names them (under zh_CN.GBK the GBK reading of their bytes). An address, a folder or a script
path holding `"`, `$`, a backtick, `%` or a backslash - what a shell reads inside double quotes -, or one a shell of the
locale could not write back to its bytes, gets the words instead: `the same command with --from 127 --chars 7900
--file content.md`. When the text ends in an answer, a short
page's too, the answer's last line says so: `── EOF content.md: lines 352-389 of 389 ──`. A stray `──` on the command
line (a model copied the decoration) is left out and named on the `ignored:` line.

The outline takes at most 2.5 KB: every heading when they fit, else the deepest levels that fit.
When those give fewer than 12 rows and there are finer headings (a book's title over its chapters),
the next level down is listed thinned evenly, the coarser rows kept, and a last row says how many
are between them; a text without headings gets a row per block, thinned the same way. Either way
the outline reaches the end of the text.

Every answer fits the smallest output an agent harness passes on (7 900 characters, 9 980 bytes, 495
lines), as the harnesses' code had it on 2026-11-26: Cline's SDK runtime (its CLI, and the VS Code
windows on that bundle) cuts every tool result, MCP too, at 8 000 characters - UTF-16 units - keeping
about 3 985 at each end; Codex passes 10 000 bytes of output to a model outside its OpenAI catalogue,
Roo Code 10 240; Cline's VS Code extension shows 500 lines. Past that each one cuts differently, so
nothing is cut between the script and the agent. English text meets the characters first: a block is
about 7 700 characters where it was 9 850 (Node's fs reference, 381 KB, takes 54 answers instead of
43); Cyrillic and CJK text meet the bytes, as before. `--from N`
prints the block that starts at line N - the next one, or a heading from the outline - of the same
file, from the saved copy, with no network; without `--file` it goes on in the file read last
(`--file` switches it). If the copy is gone the page is read again and a `note:` line says the
lines may have moved. The files stay in the work folder: the per-URL cache entry under the system
temp directory, or `--dir DIR`.

`--from "text"` starts at the first line that holds a piece of text, whitespace folded and then without case; when
several do, the first at or after where the last answer of that file started, so an agent that quotes the last line
it saw goes on from its own place. A quote cut in the middle of a line matches, one of several lines is looked for
by its first, and a marker is found by its type and name - a picture by its number - whatever its state and
properties say: `--from "[tab · Developer Plan Limits]"`, `--from "[img #3]"`. The line is matched as it stands too,
whitespace folded, so a quote that ends inside a marker is found - the case when a harness cut the answer in the middle
of a picture's or a tab's line: `--from "#3 · 100x80 3K · picture 3] im"`, `--from "[tab · hidden, but extr"`. When no
line holds it, the answer says
so and shows the outline (its line numbers are what `--from N` takes), and no text. It works on `content.md` and
`page.md` alike.

`--chars C` sets how much one answer holds, for a harness that shows more (Codex with an OpenAI model about 40 000
bytes, Claude Code 30 000, goose and OpenCode 50 000) or less: at most C characters (UTF-16 units, as Cline counts
them), whole lines, at most C x 9 980 / 7 900 bytes and C x 495 / 7 900 lines - the header, the outline and the lines
above and below the text included. Without it an answer is `--chars 7900`: the 7 900 characters, 9 980 bytes and
495 lines that fit every harness. It works on a first read, `--from N` and `--from "text"` alike, and the next line
carries it on; C is 1 000 to 150 000 (the most a harness shows: Claude Code with its limit raised), and a value
outside, or not a number, is named on the `ignored:` line with what was used (`--chars 500 (1000 at the least: 1000
used)`). The skill cannot see what the harness shows: SKILL.md says when to raise the size and how to go on from a
cut. `--to` is gone (it named a range in lines until 2026-11-27): `--to M` is left out and named, `--to 120 (gone:
--chars sets the size)`, and the read goes on.

The text's own lines carry no numbers, as an editor would show them; the block's line above it, the pointers and the
outline (an answer from line 1 has it) keep theirs.

| File | What it is |
|---|---|
| `content.md` | the main content, what the answer prints; picture markers `[img #3 · 100x80 3K · alt] img/03-alt.png` point at `img/`. For `media_only` it is one line naming the saved file |
| `page.md` | the whole page as text: also menus, links and ads, every link a whole address as in `content.md`. Paragraphs, code and tables the extractor dropped are already back in `content.md`; the answer prints `page.md` instead when `content.md` is a fragment. Where there is no page to show - a document, a site's API, a reader, or a page with under half the text's words (a script shell the browser filled) - it is the text itself |
| `raw.*` | what the server, export endpoint or browser returned. A downloaded file keeps the server's own name when it sends `Content-Disposition`, otherwise `raw.<ext>` |
| `manifest.json` | everything the run established: engine, tiers tried, signals, privacy, files; `--json` prints it instead of the answer |
| `img/` | the pictures of the lines printed so far as `NN-words.ext`, NN the marker's number |
| `shots/` | `--screenshots`: the screens, two glued into one 1280x1568 picture |

No line of `content.md` or `page.md` is longer than 1 998 characters: a longer one is cut after its
last sentence end that fits, else at a space, else exactly at the limit, and every piece is kept -
so a file tool that stops at 2 000 still sees every word.

## Statuses

| Status | Meaning | What to do |
|---|---|---|
| `ok` | text is there, and the tier that gave it got a successful answer | answer from the text |
| `blocked` | an anti-bot wall: a challenge header or markup, a wall's words (20 languages), or HTTP 403/419/429/451 | follow `advice`: `--allow-external` for a public URL; once the readers were stopped too, no flag opens it (`--alternate` opened none of 8 measured walls) - another source, or the user |
| `login_required` | an account is needed (a password form with its sign-in label on a short page, a sentence of a wall - "sign in to continue", "for subscribers only" - in 20 languages, redirect to /login, 401/407) | not this skill: the user's own browser, or their paste |
| `not_found` | 404 or a soft 404 (a 200 page that says it is not there, in 20 languages: in its title or heading, or with few words; the browser's page counts); the archive was tried with `--allow-external` | report it |
| `empty` | no usable text: an app shell, an error stub, or a binary body; a document with no word of its own; a file named as an archive that is none (a `.doc` saved as `.docx`: `advice` says what it is); a page whose text is a loading message where its content goes and little else (`Loading organization limits...` beside under 150 words: the content its scripts fetch never came - `signals.loading`, quoted in `reason:`) | follow `advice`: `--alternate` when the browser has not rendered it, `--screenshots` when it has; for a file that is no archive, what reads it; for a loading message, a page behind a sign-in most often: "When nothing works" |
| `media_only` | the URL *is* a file (image/audio/video), whole; it is saved, not converted | the text names the file: open it |
| `too_large` | the file or page is over the cap, or a document or a media file was still arriving when its time ran out | the `reason:` line names the cap, or how much arrived; `--download` lifts policy limits and the time limit |
| `error` | network, DNS, timeout; a transfer the server stopped (a stub, or a document or a media file stuck halfway); the server's own HTTP 4xx/5xx page (kept as the text); or an archive cut or damaged (a DOCX, an EPUB, a ZIP) whose whole members - and the one it was cut in, as far as it arrived, where a reader can take one in part - hold under 40 words of their own (`signals.broken_archive`) | retry later; for a public page `--allow-external` also tries a reader and the archive; for a cut or damaged archive what `advice` says - a whole copy of a file on this machine, `--refresh` for a server's |

`+ 3 blocks of page.md` after the engine: the extractor dropped those paragraphs, code blocks or
tables and they were put back where they stood; `outside the text: 6.2 KB … - page.md` is what only
`page.md` has (menus, link lists, fragments). `maybe a fragment: the text is 12% of the page's words`
after the engine is not a status: `content.cover`, the text's words over the words the page shows
(menus, footers and links counted), is under 0.35 with a text over 200 characters, so the text may
be part of what the page holds and the answer shows `page.md`, the whole page (`signals.fragment`).
A whole text holds more but seldom all of the page's words: on the acceptance bench 7 of 40 whole
texts were under 70 % (a news article 49 %, gov.uk's tax rates 50 %, a GitHub issue 44 %) and its 3
fragments under 30 %, and "49% of the page" on a whole text was read as "half the content" - so the
share is named only where it decides something, and `content.cover` keeps it for every read.
`partial` there means the transfer was cut (a timeout, a broken connection): the text may stop
early, and the advice says how to get the rest. `signals.paywall` (and an advice saying so) is a page that says it is paywalled - schema.org's
`isAccessibleForFree: false` in its JSON-LD or microdata, with the `cssSelector` of the hidden part when it names one -
while the status stays `ok`: the text is what the server sent, the whole article a script hides or only the part open
to everyone, and the page cannot tell which; a container named `paywall` is no such word (free pages carry them). A
paywalled page whose text is also under a third of its words is the part open to everyone and no more: the block rule
has put back every paragraph `page.md` has, so the rest of `page.md` is the site's menus and links. Its first line
says `paywalled: the rest of the article is not in the page` in place of `maybe a fragment`, and the answer shows
`content.md`, with no `next:` line leading on through the menus (Spiegel's and Le Monde's paywalled articles, the
bench's two paywalled fragments: a model read on through `page.md` and could not tell whether the article was hidden
or absent). A deep address whose redirects end on the site's home page (`groq.com/pricing` went to `groq.com/`) is
`ok` with an advice that says so - the page asked for may be gone or moved - and `signals.redirect_root`; the home
page by another name (`/index.html`, `/home`, `/en/`) is no such case, and none of 292 addresses of the bench, the
corpus and the campaign was.
`charset gb18030 (guessed)` there means the page named no encoding and its text was read by
what its characters are (`guessed, doubtful` when little text, two readings alike or a reading that fits no language
well make it a close call: some characters, or the whole alphabet, may be wrong - nothing an option changes; the same
is `signals.charset_guess`). Status words describe the *text*, not its length: a five-line status page is `ok`,
a page that quotes "access denied" in prose is `ok`. Any status but `ok` comes with a `reason:` line
naming the rule that fired (`a challenge page: Just a moment...`), so a status can be checked
instead of trusted. Content is never hidden, whatever the status.

Exit code: 0 whenever an answer is printed, whatever its status; 1 an internal error (the answer
says so); 2 a wrong call - no URL, or one that is neither http(s) nor a file here - with the reason
on stderr. A flag that is not read-page's, or a value it cannot use (`--to 407`, `--from abc`,
`--file notes.md`), does not stop the read: it is left out and an `ignored:` line names it. A
misspelled flag is the flag meant, silently (`--screenshot`, `--allow-extrnal`, `--form`): one edit
for a short name, two for a longer one, and only when one flag is that near.

`robots.txt` and `X-Robots-Tag: noai` are not consulted: one user-requested read behaves like a
browser. A crawl of a whole site is not this skill's job.

A PDF's tables come as Markdown tables where the layout model is installed (`--setup`): `signals.tables` has the pages laid out (`pages`, as ranges: "2, 8-9, 28-600"), their number of tables, the model's seconds, and `left` - the pages that look like a table and were not laid out: the read's time for tables ran out - 10 s of the model's own work, its processes side by side (as many as the CPUs and the memory hold), as many times longer as other work on the machine slows them, within the read's deadline (`more`: after it pages were judged by their text alone, so a page of rulings only may be missing), a page was too heavy for that time (`heavy`: over 8 000 vector paths, or 2 000 words in one block), or the model stopped (`error` says why: it does not load, or its process ended); `files` does the same for each PDF inside a ZIP, which share the read's time for tables. Then `advice` names the pages and why, and `--download`, which gives the model the time, with an estimate of its seconds. With `--alternate` (`markdown`) `left` names the pages that are PyMuPDF's text and not Markdown, and why - also when no page came as Markdown. Without the model `improve` says how many pages look like a table. More in [documents.md](documents.md).

## Flags

| Flag | Meaning |
|---|---|
| `--from N` | print the block that starts at line N of the saved copy, no network; without `--file` it goes on in the file read last (`--file` switches it). `--from "text"`: from the first line that holds it, a marker by its type and name (see The answer) |
| `--chars C` | how much one answer holds: C characters (UTF-16 units), whole lines, the bytes and lines in the same ratio; 7 900 by default, which fits every harness; 1 000 to 150 000 (see The answer) |
| `--file page.md` | answer with the whole page (default: `content.md`, or `page.md` for a fragment) |
| `--json` | print the manifest instead of the answer |
| `--ocr N` | answer with the text drawn in picture N, the number on its marker, instead of the page's text: for a model that cannot see pictures (see Pictures) |
| `--allow-external` | the URL is public: public readers (Firecrawl, Jina, Exa, Tavily, defuddle.md, in that order; one without its key is skipped) and the archive may be used if local engines fail |
| `--force-external` | use a reader even when the local text looks complete, and even for a URL that may carry a secret (implies allow; never for an internal host) |
| `--alternate` | re-read locally by other means: the browser plus every extractor, the fullest text kept; a PDF through pymupdf4llm (Markdown with its headings; the pages it did not reach in the read's time stay PyMuPDF's text, named in `signals.tables.left` and the advice); the page itself where a site's API would answer. For a text that looks thinner than the page (measured 2026-11-19 on 72 pages read both ways: half as much text again or more on 7 script-built portals - the three thinnest now go to the browser by themselves -, less text on 3, the same on the rest; 6.8 s against 2.5) - not for a wall |
| `--download` | **no size and no time limit**: the response is streamed to disk as it arrives, so a 5 GB file is a file, not a memory error; a PDF's tables are laid out on every page that looks like one, however long it takes |
| `--deny-images` | download no pictures (by default the printed lines' go to `img/` and the markers carry the path); the markers say `not downloaded` and keep the address |
| `--refresh` | ignore the 15-minute cache; `--dir DIR` sets the output folder |
| `--clear-cookies` | forget this site's stored cookies first (they otherwise live 6 hours; `--refresh` keeps them) |
| `--screenshots [N]` | also capture the page as images: the first N screens of a 1280x784 window (default 2, 0 = none), two glued into one 1280x1568 picture, never scaled; needs a browser, works for PDFs too |
| `--caps` | print what this machine has (libs, CLIs, browsers, keys, OCR languages, the environment in use) and exit |
| `--setup` | install every engine into the skill's own environment, a folder of the user's that every agent sees (no admin rights; it first says the download, about 400-445 MB, and the 0.85-1.0 GB it keeps), or bring it up to date and check it; asks nothing - running it is the consent |
| `--ocr-langs eng+hin` | with `--setup`: the OCR language packs to fetch besides the fourteen it fetches for everyone and the user's own; kept for the next `--setup`, and chosen from for each scanned page by its script (the `ocr:` line and `improve` name this command for a pack a scan needs) |
| `--version` | print the skill version, schema and cache build |

**No URL is a command too**: `readpage.py` with nothing else prints the *setup report* - the
environment (where, when it was set up), what this machine already has, what is missing (what it
buys, and `readpage.py --setup` or, for what --setup cannot install here, the exact command), and
the readers' keys - and exits 0. That is the first thing to run on a new machine; the report
installs nothing, it names. `--setup` runs its work detached and shows it for up to 100 s, then
says it goes on in the background (run it again to follow a run that is still at work); where the
shell ends what a command started when the command ends (a Windows job that kills on close), it is
followed to its end instead; deleting the folder removes it all.

One URL keeps one folder (the download lands there too, `.part` until it is complete). A cached
answer is *served* only when the flags that change the text match; `--alternate`,
`--allow-external` and `--download` re-read in the same folder and replace `content.md`/`page.md`
while leaving already downloaded files alone. A later run without `--deny-images` reuses the cached
text and only adds the pictures. `--refresh` sends `If-None-Match`/`If-Modified-Since` first - for
the page and for every picture separately: an unchanged page and unchanged pictures come back as
`304`, the header says `from cache, revalidated` and nothing is downloaded again.

A cached answer is served for 15 minutes; a failure (`error`, `blocked`, `empty`) is never served.
An answer a reader or the archive gave because the live page did not answer or answered 5xx
(`signals.rescued_after`) is served for one minute only: then the live page is asked again. The
advice says what the live page did - "is gone" only for a 404/410 - and names `--refresh`.

## Privacy and the network

Default is sensitive: the URL never goes to a third party. Two rules decide when it may.
**An internal host** - loopback, RFC 1918, link-local, IPv6 private, cloud metadata, `*.local`, or
a name that resolves to one of those - never goes to a remote reader, whatever the flags: the
reader could not open it anyway, and `--force-external` is refused with the reason in
`privacy.conflict`. **A URL that may carry a secret** - credentials, a `token=`/`key=`/`sig=`-like
parameter, a sharing or reset link, an opaque token of 32+ characters - stays local with
`--allow-external` (only a hint: "public if it looks public"); `--force-external` is the explicit
"I know, send it" and the manifest records the conflict. A slug with digits (`python3-tips`,
`oauth2-server`) is not a secret. `privacy.why` says which rule held. Cookies never go to a reader.

Whatever a page does, the reader takes only http(s) - on every redirect, picture, meta refresh and
browser request - and a public page never reaches into the local network. The browser of a public
page has one way out, a SOCKS5 proxy of the reader's own on 127.0.0.1 (netguard): every connection
it opens, a redirect hop's too, is checked on the very addresses it goes to, and an internal one is
refused (`signals.browser_blocked`). On a machine whose browser uses a proxy of its own the reader
checks the page's requests instead; if a redirect still reached inside, the browser's text is not
used, and the advice says so and names `--allow-external` (`signals.browser_inside`). A picture gets
only the site's origin as `Referer`. The cache is the user's own (`read-page-<uid>`, 0700, files
0600, on a shared /tmp).

A public Google Doc, Sheet or deck is read through its export endpoint (docx/xlsx/pptx), because
the page itself is a JS shell. A question on Stack Overflow or another Stack Exchange site, an npm
package, a Hacker News item, a PubMed record and a post on X are read through the site's own API with no flag
(engine `api:…`; X through fxtwitter, which gets only the post number); if the API fails, the page
is read as usual.

## The manifest (`--json`, trimmed)

```json
{"status": "ok", "url": {"requested": "https://example.com/a", "http_status": 200},
 "content": {"engine": "defuddle", "chars": 4123, "words": 612, "cover": 0.31},
 "signals": {"fragment": true, "status_reason": "612 words, engine defuddle"},
 "files": {"content": ".../content.md", "page": ".../page.md", "raw": ".../raw.html"},
 "privacy": {"mode": "sensitive", "refused": ["external"]},
 "advice": "content.md holds 31% of the page's words, so the answer shows page.md, the whole page (the extracted text may have missed part of it)"}
```

The full schema is [manifest-schema.json](manifest-schema.json).

## Limits and cookies (one policy for the CLI and MCP)

`MAX_DOWNLOAD` 250 MB and `MEDIA_LIMIT` 100 MB per file *before* `--download`; `MAX_PAGE_BYTES`
64 MB of HTML/text parsed in memory (a bigger file is still downloaded whole, it just cannot become
one string). Every read ends by 55 s, the CLI and MCP alike, with what it has; each step keeps its
own bound inside that - HTTP until 14 s before the deadline (below 1 KB/s for 10 s the transfer is
cut, `partial`); a site's API 10 s; browser 20 s, one browser; readers 20 s, 12 s each; archive
20 s; converters 10 s; OCR 30 s for 3 pages at once; pictures 6 s, the text's first. A page over
3 MB of HTML is its own page.md. `--download` has no deadline. They live in
`scripts/readpage.py` (the table with the reasons is in [engines.md](engines.md)); the MCP server
imports them.

Cookies set by a site are kept for that host for 6 hours by default (2-24 h via
`READ_PAGE_COOKIE_HOURS`, shared by all pages of the host). They obey `Domain` (a cookie set for
`example.com` also goes to `app.example.com`) and their own expiry; `--refresh` keeps them,
`--clear-cookies` drops them. A stale session can make a page look like a wall: `signals.cookies`
says whether any were sent, and the advice names the flag when cookies of an earlier read were
among them. A wall's own cookies are no session: a read that ends `blocked` or `login_required`
does not keep the ones it got there. Every local engine shares that one jar -
the HTTP tiers, the pictures, the headless browser (so a JS login works) and `yt-dlp` for
members-only videos; a cookie the browser set in JavaScript is stored for the next run. Remote
readers never get it: a session stays on this machine.

## Pictures

Every picture the text shows is a numbered marker where the page has it:
`[img #3 · 100x80 3K · Diagram of the flow] img/03-diagram-of-the-flow.png` - the number is the
file's, the alt is inside the brackets, the path comes last. Whatever produced the text, the
pictures are there: an extractor, a block put back from `page.md` (a picture the extractor took out
of a paragraph comes back after it), a reader, a site's API; a DOCX, PPTX, EPUB, ODT or RTF picture stands
where the document has it, and pictures a document does not place are listed after the text, in document
order. In one answer a repeat prints as `[img #3]` (a tiny picture with a short alt as the alt,
`✓`); `content.md` keeps every marker full. A picture that was not downloaded says why and keeps
its address: `[img #5 · not downloaded: 404 · chart] https://…` - its state before its alt, as every
marker has it (the type, the state, what more there is to say, the name last; see Tabs, sections and
selects). Until 2026-11-26 the state came after the alt; a page folder written so is rewritten when its
pictures come. Tracking pixels and spacers are shown nowhere; a lazy picture is its real address, not its
placeholder. `--from "[img #5]"` goes to a picture's line, whatever its marker says.

What is downloaded follows what is printed: every picture of `content.md` and `page.md` is
numbered and listed in the manifest from the first call (with its line), and an answer downloads
the pictures of the lines it prints that have no file yet (6 s) - the first block's, a `--from`
block's, `page.md`'s when `page.md` is printed. A picture not printed yet says
`not downloaded: not printed yet`; one the 6 s cut is fetched again the next time its lines are
printed, and one the network failed (a dead host, a server error) once more, by an answer printed
30 s or more later - not by every answer from the cache. With `--download` every picture of the
page, the text unchanged.
`--deny-images` downloads none, the markers say so, and a later read without it fetches them for
the cached text. `signals.images_outside` counts the page's other pictures (menus, footers), which
`page.md` has. Pages of one site share pictures: a folder starts with its host
(`pages/<host>-<key>`), and a picture another page already has is a hard link to that page's file
(`signals.images_reused`), not a download; deleting one folder never breaks another. A picture on a
private host named by a public page is not fetched (`signals.images_private_skipped`). Over MCP
`inline_images=true` turns a marker into a real image block; a URL serving a single image comes
back as that image in one hop.

A model that cannot see pictures asks for their text: `--ocr N` answers with what is drawn in
picture N - the page's other files stay as they are, and a picture still only an address is
downloaded first. An SVG drawing gives its own `<text>`; any other picture goes through
tesseract twice, as it is in grey and as dark ink on light, and the reading with more confident
words wins (a diagram on tinted boxes: 7 of its 16 labels in grey, 14 as ink). Languages are the
pack of the page text's script (Chinese, Japanese, Korean, Russian) or of its Latin-script language (German, French,
Spanish ...), English and the user's languages' (`READ_PAGE_LANG`, the system's) beside it, each when the pack is
there, or `READ_PAGE_OCR_LANGS` when it is set; a pack the text needs and the machine lacks is named on the `ocr:`
line. A scanned PDF's pages are read each with the pack of the script tesseract sees on it
([documents.md](documents.md#ocr-on-when-tesseract-is-there)). The `ocr:`
line names the picture, the engine and the pass - or why there is no text: no such picture, not
on disk, no OCR engine.

## Tabs, sections and selects

A page shows one tab of a set and folds its other panels and sections away; the text says where each one is and
what state it is in, with markers of one grammar - the type, the state, what more there is to say, the name last
(the pictures' markers have it too, and a cut workbook's: `[rows · lost in the cut · 54-78954 · Third]`, `[sheet · lost
in the cut · Fourth]`, [documents.md](documents.md)):

```
[tab · shown · Free Plan Limits]
[tab · hidden, but extracted · Developer Plan Limits]        its text follows, as the page has it
[tab · loads on click, not extracted · Batch Limits]         not in the page: only a click would fetch it
[tab · hidden, but extracted · 6.0 KB, too long for here: page.md from line 410 · Go]
[section · hidden, but extracted · Specifications]           a closed <details>, a collapsed accordion
[select · chosen: EU · also US, APAC · Region]
```

A hidden panel's text is in `content.md` under its marker - a FAQ's answers are folded by default, a plan's table is
what was asked - unless it is over 4 KB: then it stays in `page.md`, and the marker names its line there (the largest
hidden panel of the 34 pages measured was 3.4 KB, a quickstart's other way to sign in). `page.md` has every panel under
its marker, the browser's copy too. A tab that loads on click is named, not extracted: this skill clicks nothing.
`signals.tabs` counts them all.

What is marked is the main content's: nothing inside a nav, a header or footer, an aside, a form or a dialog, by tag
or by role. A tab set is `role=tablist` with its `role=tab`s and their panels (`aria-controls`, `aria-labelledby`, or
the tabpanels in order); a set of links is navigation and stays as it is. The shown tab is the one `aria-selected`,
else `data-state=active`, else the one panel not hidden, else the first. A section is a closed `<details>` with a
summary, or a button with `aria-expanded` whose `aria-controls` region the page holds as text - not a menu of links or
a form folded away (a responsive menu, a feedback popover). A table whose header cell holds two to eight buttons and
nothing else has tabs of its own (Groq's plans: the shown tab is named above the table, the others below it). A select
names its chosen option and five others. A panel keeps its place and its attributes, but those that hide it; the
engines are weighed without the markers and without the text they did not see before, so no engine is chosen by them.

Not marked yet: tabs made of radio inputs and CSS alone (MkDocs Material, sphinx-inline-tabs), groups of buttons
elsewhere (on the 34 pages most were feedback buttons, toolbars and players), and the short panels of a tab box an
extractor drops whole (Docusaurus's examples: their code and prose come back by the block rule, with their markers;
a five-word panel does not). Measured 2026-11-26 on 34 public pages with tabs, accordions or `<details>` in their main
content, and on 109 saved pages of the bench and the corpus read offline before and after: the 89 with nothing to
mark came back the same, file for file.

## Video

Read through **subtitles** only: 30-second blocks, each with a timestamp (`[0:18] …`, citable), the cues kept
as `transcript.vtt` (WEBVTT whatever format the site sent: VTT, SRT, TTML, ASS ...). The first line names the
track: `subtitles en` (a person's), `subtitles fr, automatic` (speech recognition), `subtitles en, automatic, of a dub
(original audio zh-Hant)` (the recognition of a dubbed video's default audio, which is not the speaker's words: a
track in the speaker's own language, a human one first, is read before it), `subtitles zh-Hans, machine-translated
from en` (YouTube's translation, read only when the video has no other track); `content.track`. No captions: the
page is read as a page (description, comments) and `signals.no_transcript` says why. A video that has not
premiered, a site that refused the request and any other error yt-dlp stopped with are said in its words, with an
`advice:` (`--refresh` once the video has started or the refusal has passed; [video.md](video.md)). A video URL
that is itself a file (`.mp4`) is `media_only`; one cut in transit is `error` or `too_large`, with how much arrived,
never a file that looks whole. Only a video's own address takes this path: `vimeo.com/about` is a page. No speech
recognition, no frame analysis - [video.md](video.md) prices both.

## MCP

`read_url(url, allow_external?, force_external?, alternate?, download?, deny_images?, screenshots?,
inline_images?, refresh?, clear_cookies?, file?, from?, chars?)` and `read(dir, file?, from=1, chars?)`.
`read_url` answers with the text the CLI prints; under its `next:` line stands the call that goes on, with the
answer's folder: `read(dir="C:/.../pages/example.com-9c1f…", file="content.md", from=127, chars=7900)`. Without
`file`, `read` goes on in the text read last. `read` also opens `manifest.json`, and a picture as an image block.
`inline_images=true` attaches the text's content pictures (not icons, logos or decorations) as
image blocks right after their markers, as PNG or JPEG up to 1 568 px, the whole answer inside
25 000 tokens; leave it off below a 1M context. The blocks of a result together, as Cline counts them (the result's
JSON), stay inside the text's 7 900 characters: the text gives up the room the notes, the pictures and the JSON's
escapes take. A result carries no `structuredContent`: the manifest is the folder's `manifest.json`. Calls run four
at a time, and a cancelled call is killed. Details: [mcp.md](mcp.md).

## For testing the skill

Not for reading, and not in SKILL.md: tools for seeing what a harness does to an answer.

- `readpage.py --probe N` and `--probe-units N`, and `probe:N` read as an address: numbered lines that show what a
  harness shows of a command's output and which unit it counts (README's development notes, [mcp.md](mcp.md)).
- `READ_PAGE_TEST_CUT` makes the skill cut its own answer the way a harness does, after the answer is built - the
  CLI's printed answer and the MCP result's text alike (its text blocks joined into one, its image blocks left out) -,
  so that a model can be taught to go on under each cut:

  | Value | Harness | What is printed |
  |---|---|---|
  | `middle:8000` | Cline's SDK runtime | over N UTF-16 units, about half of N kept at each end, `...[truncated K chars]...` between (Cline's `truncateMiddleByChars`) |
  | `head:16384` | Zed | over N bytes, `Command output too long. The first K bytes:` and those K bytes (K <= N), cut at a line's end |
  | `tail:51200` | OpenCode | over N bytes, a `...output truncated...` line and the last N bytes, from a line's start |
  | `file:30000` | Claude Code | over N bytes, the whole answer in a file of the temp folder, and `Output too large (37.6KB). Full output saved to: <path>` with its first 2 000 characters |

  An answer under N, or a value that names no cut, is printed as it is; `--json`, `--probe`, `--probe-units` and
  MCP's `probe` are never cut.
