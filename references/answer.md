# The answer, its files and its rules

What `SKILL.md` says in a line, in full: the answer, the files it points at, every status, every
flag, the privacy and network rules, the limits, cookies, pictures and video.

## The answer

`readpage.py URL` prints a header - status, engine, size, the work folder, `reason:`, `ignored:`, `document:`,
`advice:`, `missing:`/`improve:` - then the text: whole when it fits, otherwise an outline with line numbers,
the first block and the line to go on from. `document:` is what a document's reader says of what it
left out or could not read (parts that do not unpack, a table cut at its caps, pictures past its limit or in
a format no browser shows, its time run out, its own error: `signals.document_note`); `missing:` is what this
machine lacks, never that.

```
read-page · ok · defuddle, 87% of the page · content.md 24.7 KB, 389 lines · 1.9 s
files: /tmp/read-page/pages/9c1f… (content.md, page.md, manifest.json)
outline (line, heading):
      1 ## Installation
     27 ## Configuration
      …
── content.md: lines 1-126 of 389 ──
(the text)
── next: line 127 of 389 → the same command with --from 127 --file content.md ──
```

The outline takes at most 2.5 KB: every heading when they fit, else the deepest levels that fit.
When those give fewer than 12 rows and there are finer headings (a book's title over its chapters),
the next level down is listed thinned evenly, the coarser rows kept, and a last row says how many
are between them; a text without headings gets a row per block, thinned the same way. Either way
the outline reaches the end of the text.

Every answer fits the smallest output an agent harness passes on (9 980 bytes, 495 lines): Codex
passes 10 000 bytes of output to a non-OpenAI model, Roo Code 10 240, Cline 500 lines, and past
that each one cuts differently, so nothing is cut between the script and the agent. `--from N`
prints the block that starts at line N - the next one, or a heading from the outline - of the same
file, from the saved copy, with no network; without `--file` it goes on in the file read last
(`--file` switches it). If the copy is gone the page is read again and a `note:` line says the
lines may have moved. The files stay in the work folder: the per-URL cache entry under the system
temp directory, or `--dir DIR`.

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
| `empty` | no usable text: an app shell, an error stub, or a binary body; a document with no word of its own; a file named as an archive that is none (a `.doc` saved as `.docx`: `advice` says what it is) | follow `advice`: `--alternate` when the browser has not rendered it, `--screenshots` when it has; for a file that is no archive, what reads it |
| `media_only` | the URL *is* a file (image/audio/video); it is saved, not converted | the text names the file: open it |
| `too_large` | the file or page is over the cap, or a document was still arriving when its time ran out | the `reason:` line names the cap; `--download` lifts policy limits |
| `error` | network, DNS, timeout; a transfer the server stopped (a stub, or a document stuck halfway); the server's own HTTP 4xx/5xx page (kept as the text); or an archive cut or damaged (a DOCX, an EPUB, a ZIP) whose whole members hold under 40 words of their own (`signals.broken_archive`) | retry later; for a public page `--allow-external` also tries a reader and the archive; for a cut or damaged archive what `advice` says - a whole copy of a file on this machine, `--refresh` for a server's |

`+ 3 blocks of page.md` after the engine: the extractor dropped those paragraphs, code blocks or
tables and they were put back where they stood; `outside the text: 6.2 KB … - page.md` is what only
`page.md` has (menus, link lists, fragments). `fragment` in the first line is not a status: the
text is real but shorter than the page, so the answer shows `page.md`. `partial` there means the
transfer was cut (a timeout, a broken connection): the text may stop early, and the advice says how
to get the rest. `signals.paywall` (and an advice saying so) is a page that says it is paywalled - schema.org's
`isAccessibleForFree: false` in its JSON-LD or microdata, with the `cssSelector` of the hidden part when it names one -
while the status stays `ok`: the text is what the server sent, the whole article a script hides or only the part open
to everyone, and the page cannot tell which; a container named `paywall` is no such word (free pages carry them).
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

A PDF's tables come as Markdown tables where the layout model is installed (`--setup`): `signals.tables` has the pages laid out (`pages`, as ranges: "2, 8-9, 28-600"), their number of tables, the model's seconds, and `left` - the pages that look like a table and were not laid out: the read's 10 s for tables ran out (`more`: after it pages were judged by their text alone, so a page of rulings only may be missing), a page was too heavy for that time (`heavy`: over 8 000 vector paths, or 2 000 words in one block), or the model stopped (`error` says why: it does not load, or its process ended); `files` does the same for each PDF inside a ZIP, which share the read's 10 s. Then `advice` names the pages and why, and `--download`, which gives the model the time, with an estimate of its seconds. With `--alternate` (`markdown`) `left` names the pages that are PyMuPDF's text and not Markdown, and why - also when no page came as Markdown. Without the model `improve` says how many pages look like a table. More in [documents.md](documents.md).

## Flags

| Flag | Meaning |
|---|---|
| `--from N` | print the block that starts at line N of the saved copy, no network; without `--file` it goes on in the file read last (`--file` switches it) |
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
| `--setup` | install every engine into the skill's own environment, a folder of the user's that every agent sees (no admin rights; it first says the download, about 360-390 MB, and the 0.85-1.0 GB it keeps), or bring it up to date and check it; asks nothing - running it is the consent |
| `--ocr-langs eng+jpn` | with `--setup`: the OCR language packs to fetch besides English and the user's own; kept for the next `--setup`, and read with in the environment (the `ocr:` line and `improve` name this command for a pack a scan needs) |
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
 "advice": "content.md holds 31% of the visible text, so the answer shows page.md"}
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
its address: `[img #5 · chart · not downloaded: 404] https://…`. Tracking pixels and spacers are
shown nowhere; a lazy picture is its real address, not its placeholder.

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
words wins (a diagram on tinted boxes: 7 of its 16 labels in grey, 14 as ink). Languages are
`READ_PAGE_OCR_LANGS` (`eng`), plus the pack of the page's script (Chinese, Japanese, Korean, Russian) and of the user's language (`READ_PAGE_LANG`, the system's) when the pack is there; a pack the text needs and the machine lacks is named on the `ocr:` line. The `ocr:`
line names the picture, the engine and the pass - or why there is no text: no such picture, not
on disk, no OCR engine.

## Video

Read through **subtitles** only: 30-second blocks, each with a timestamp (`[0:18] …`, citable), raw
cues kept as `transcript.vtt`. The first line names the track (`subtitles en`; `subtitles fr, automatic` for
speech recognition; `subtitles zh-Hans, machine-translated from en` - YouTube's translation, read only when the
video has no other track; `content.track`). No captions: the page is read as a page (description, comments) and
`signals.no_transcript` says why; an `.mp4` URL is `media_only`. Only a video's own address takes
this path: `vimeo.com/about` is a page. No speech recognition, no frame analysis -
[video.md](video.md) prices both.

## MCP

`read_url(url, allow_external?, force_external?, alternate?, download?, deny_images?, screenshots?,
inline_images?, refresh?, clear_cookies?, file?, from?)` and `read(dir, file?, from=1)`.
`read_url` answers with the text the CLI prints; its last line names the call that goes on:
`read(dir, file="content.md", from=127)`, with `dir` from the `files:` line. Without `file`, `read`
goes on in the text read last. `read` also opens `manifest.json`, and a picture as an image block.
`inline_images=true` attaches the text's content pictures (not icons, logos or decorations) as
image blocks right after their markers, as PNG or JPEG up to 1 568 px, the whole answer inside
25 000 tokens; leave it off below a 1M context. Calls run four at a time, and a cancelled call is
killed. Details: [mcp.md](mcp.md).
