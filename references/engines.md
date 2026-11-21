# Engines: what each one is for

Measured on 2026-10-29/31. Times are warm, one page, one Windows machine.

| Engine | Does | Costs | Fails at |
|---|---|---|---|
| `curl_cffi` (a pinned browser fingerprint, see below) | HTTP with a Chrome/Firefox/Safari TLS+HTTP2 fingerprint; decompresses gzip/br. The encoding: a BOM, then the header (latin-1 counts as unsaid), `<meta>`, UTF-8 - each kept only when the text reads like its script - then the bytes (`charset_normalizer`): KOI8-R, windows-1251, Shift_JIS, GBK, EUC-KR, UTF-16 all read right | 0.2-1.5 s | JavaScript pages; some sites challenge the newest `chrome` profile |
| system `curl` | the same without the TLS fingerprint, with `--compressed`; also used for internal hosts | 0.1-0.6 s | walls that read the fingerprint (npm: 403) |
| `urllib` (standard library) | the last HTTP channel, when neither curl_cffi nor curl is there: the same redirect checks and bounds | 0.1-0.6 s | the same walls as curl |
| `defuddle` (Node) | main content + metadata; best coverage on framework docs. Inline elements lose their ids before it sees the page (a footnote's stays): its clutter list ("next-" among ~590 words) removed term links inside sentences, the WHATWG specs' among them. An inline SVG it passes through as markup becomes `[diagram: its labels]` | +0.9 s | JS shells, walls; an inline element whose class holds a clutter word |
| `trafilatura` (Python) | main content, metadata, robust charset detection | +0.2 s in-process | JS shells; keeps 7-25 % of docs pages |
| `html2text` (Python) | whole page -> markdown: the `page.md` artifact; readability's article too. Never wrapped: a wrapped line split a picture's address | +0.1 s | nothing, it is a plain superset |
| headless Chrome/Edge/Chromium | renders JavaScript, keeps hash routes | 0.65-1.4 s | Cloudflare-managed walls (npm, SO) |
| `yt-dlp` | subtitles for YouTube, TikTok, VK, Vimeo, RuTube, Twitch | 2-3 s | videos without captions |
| `Firecrawl` (`--allow-external`) | renders + residential proxy; opened the most walls in a measurement (11 of 14 hard pages) | 1 credit/page | needs a key; never for an internal host, a URL with a secret only with `--force-external` |
| `Jina Reader` (no key) | renders JS; asked by POST, so `#/` routes and Cyrillic addresses survive; its cached snapshot is asked again with `x-no-cache`; a wall it met is not text | free, rate-limited (`JINA_API_KEY` lifts it) | the same walls as everything else |
| `Exa` (`EXA_API_KEY`) | its index or a live crawl (`livecrawl: always` on `--refresh`); the only reader that opened Quora | 1 credit/page, 0.3 s median | X and `#/` routes |
| `Tavily` (`TAVILY_API_KEY`) | extract as Markdown | 1 credit/page, 1.2 s median | nothing unique in that measurement; a failing page holds it 12 s |
| `defuddle.md` (no key) | defuddle on their server; the YAML front matter goes, the title stays | free | simple pages only (4 of 14); a 404 is their 502 |
| site APIs (no flag) | Stack Exchange (`api.stackexchange.com`, question + answers by votes), npm (the version's document + the README from its tarball, streamed until the README), Hacker News (Firebase: the story + 30 top comments), X (`api.fxtwitter.com/status/<n>`), PubMed (NCBI's E-utilities: the record's citation, authors, abstract by section, identifiers, MeSH terms; a book's record - a chapter of StatPearls or GeneReviews - from the same call; the old `www.ncbi.nlm.nih.gov/pubmed/ID` address, the old mobile `.../m/pubmed/ID` and a search for one record's number (`?term=ID`) too - the page itself answers a client without its script's cookie with "Cookies must be enabled", and a headless browser with 403) | free, 0.1-1.3 s | a failure, or 10 s, reads the page the ordinary way |
| Wayback (`--allow-external`) | an archived copy with `id_` | free | page never archived |

The readers form one chain in the order measured on 14 hard pages (Firecrawl
opened 11, Exa 10, Jina 8, Tavily 7, defuddle.md 4): `READERS` in `readpage.py`. A reader
that needs a key and has none is skipped, so without keys it is Jina, then defuddle.md. The first
answer with real text ends the chain; a wall (`wall_signal()` on the reader's text and title), fewer
than 40 words, the service's own error (`402`, `429`) or no answer in 12 s moves on; a `404`/`410`
that the reader saw ends it, since every reader would see it. A paid reader that reached the page and
met its wall (or saw a 401/403/429/451) ends the paid part: the next paid reader would meet the same
wall - in that measurement Exa and Tavily never gave text where Firecrawl and the free Jina did not, and a
glass wall like Amazon's cost three credits - so only the free readers are still asked. A paid
reader that failed for its own reason (no credits, a timeout) is replaced by the next one. A key goes
only to its own service.

The site adapters (`scripts/siteapi.py`) exist only where the ordinary path fails in measurements:
Stack Overflow and npm answer with a wall, Hacker News' page has no comment text, X is a script
shell. PyPI, GitHub, arXiv and Wikipedia read fine the ordinary way. `--alternate` and
`--screenshots` skip them: they ask for the page itself.

Both HTTP tiers follow redirects **by hand** (`allow_redirects=False`, `--max-redirs 0`) so that
`hop_refused()` can stop every hop that is not http(s), or that would take a public page into the
local network (`host_is_private()`: the host literal, an internal name, or the addresses the name
resolves to). curl also gets `--proto =http,https --proto-redir =http,https`. The plain `curl`
tier sends `--compressed`, because curl does not decode a body it did not ask to be compressed.

The browser of a public page goes out through **netguard** (`scripts/netguard.py`), a SOCKS5 proxy
on `127.0.0.1` that this read's browser alone uses; Playwright gets `proxy=socks5://...` and adds
`--proxy-bypass-list=<-loopback>` (Chrome would send localhost past any proxy) and host resolver
rules that leave every name to the proxy, and the `--dump-dom` path passes the same flags itself.
Each connection arrives as `host:port`; `browser_policy()` refuses an internal name or address
literal, resolves a name once, refuses it when any of its addresses is inside, and the connection
goes to exactly those addresses: no second lookup for a rebinding DNS to answer differently. TLS
stays end to end. Playwright's request routing, used before, saw only a redirect chain's first URL:
a public page that fetched its own `/hop` (302 to an internal address) got the internal answer into
its text, and a meta refresh to it made the internal page the text (found 2026-11-06). With netguard the fonts and media of a text render are off by flags
(`--disable-remote-fonts`, `--autoplay-policy=user-gesture-required`) and WebRTC may not open UDP
past the proxy (`--force-webrtc-ip-handling-policy=disable_non_proxied_udp`).

It steps aside for an internal page (its own resources are inside), for a machine whose browser
has a proxy of its own (`system_proxy()`: the environment's, Windows' or macOS' setting, or a proxy
auto-config script - the browser keeps its way out), for WebKit and for `READ_PAGE_SKIP=netguard`.
There the request rule guards as before, and a watch on the responses catches a hop that answered
from inside: the browser's DOM is then not used (`chain.skipped`: "the page reached into the local
network", `signals.browser_inside`), and the advice says so outright and names the flag that reads
the page another way: `--allow-external` (a remote reader has no local network to reach). The
request itself has gone out in that case; with netguard it never opens.

No ad or tracker list is built in. For a measurement, `READ_PAGE_TEST_BLOCKLIST=FILE` (an ad-block
DNS filter's `||host^` rules, a hosts file, or a name a line) makes netguard refuse those names and
their subdomains before any lookup; the debug log counts them as refused "on the test block list".
On a machine measured on 2026-11-07 a DNS-level ad blocker already refused the browser's ad hosts
(366 of 6 517 requests on 67 pages), so whether the browser should have a list is measured with
nothing else blocking.

## TLS fingerprints: which ones actually pass

`curl_cffi` ships a fixed fingerprint per browser version, and sites keep **allowlists**, so the
question is not "randomise" but "which real versions still pass". Measured 2026-10-30 over 14
sites (npm, medium, reddit, x, glassdoor, indeed, amazon, booking, zillow, walmart, tiktok,
instagram, cloudflare docs, pypi), 200 = passed:

| fingerprint | passes | notes |
|---|---|---|
| `chrome151` | 12/14 | npm and medium ok; amazon and booking refuse |
| `safari184` | 12/14 | the same 12, a different TLS family |
| `chrome124` | 10/14 | old but still accepted by npm/medium |
| `firefox135` | 9/14 | **amazon passes only with Firefox 135-147** |
| `firefox155` | 11/14 | fails glassdoor and amazon |
| `chrome136`-`chrome152`, `edge101` | 8-9/14 | **rejected by npm and medium** |
| `chrome` (alias of the newest) | 1/14 | the freshest profile is the first one blocked |

The rotation is `chrome151 -> firefox135 -> safari184 -> chrome124` (**at most 4 attempts**, only
after a 4xx other than 404/410; one attempt is enough on 12 of the 14 sites, two add amazon). When
every fingerprint is refused, plain `curl` gets one try: Hacker News answers 419 to a browser's
handshake and the page to curl. The list is filtered
at runtime against the targets this `curl_cffi` build actually has, so an old version degrades to
`chrome124/120` instead of crashing. macOS uses `safari184 -> chrome151_macos -> ...`.

Two rules taken from measurement and from the curl_cffi FAQ:

- **Do not randomise.** Fingerprints are fixed per browser version; an invented one is a signal.
- **Do not mix a bot User-Agent with a browser handshake.** `firefox155` + our UA returned 403 on
  npm/medium, the same fingerprint with its own headers returned 200. The HTTP tier therefore sends
  only `Accept: text/markdown, ...` and lets the impersonation own the rest; the honest
  `read-page/0.4` UA stays on the plain-curl path and on image requests.

## Browsers we try, in order

Registry and known install dirs on Windows, `/Applications` on macOS, `PATH`/snap/flatpak on Linux,
then Playwright's own download. Named channels first, then `executable_path` for the rest:

| # | Browser | How |
|---|---|---|
| 1-2 | Chrome, Edge (stable) | `channel=chrome` / `channel=msedge` |
| 3-8 | Brave, Vivaldi, Opera, Opera GX, Yandex, Chrome SxS | `executable_path` |
| 9-14 | Chrome/Edge beta, dev, canary | `channel=...-beta` etc. |
| 15 | Playwright/Patchright bundled Chromium, then its `chromium-headless-shell` (`--setup` installs the shell) | `executable_path` |
| 16 | WebKit (macOS only, `playwright install webkit`) | `pw.webkit` |
| - | Firefox / Safari | not used: no DOM dump in headless |

The code uses **one** browser (Chrome, else Edge, else the next in the list) and tries another only
when the first fails to start: a page one Chromium cannot render, another cannot either. One budget
of **20 s** from the start of the load covers loading and settling, and the rule for "done" lives in
`scripts/settle.py`. It was measured on 67 sites (SPAs, walls, heavy news and shop pages), on a fast machine and
on an emulated Celeron: each load was watched for 20-25 s, and the text at each candidate rule's
stop was compared with the text at the end. Done means, after DOMContentLoaded:
- **settled**: the text is not empty and unchanged for 1 s, nothing (XHR, fetch, document,
  **script**) has been in flight for 1 s in a row, and the mount node (`#app`, `#root`, `#__next`,
  `main`, ...) is neither empty nor a "Loading..." placeholder;
- **busy**: the text unchanged for 2 s, whatever is in flight - analytics that never end;
- **error page**: status 400 or more, unchanged and quiet for 1.5 s, no challenge script running
  (a 403 wall is let go in 1.5 s instead of 12);
- **empty**: no text 3 s after DOMContentLoaded, quiet, and no empty mount node waiting to be filled.

A poll that comes more than 0.5 s after the one before means the page's scripts held the probe: that
pause is work, not quiet. Two things the measurement taught: scripts in flight must count (Steam,
AliExpress and Rutube fetch their data right after a burst of scripts), and quiet must be a window,
not one poll (rbc.ru answers 401 and fills the page 3 s later). On a weak laptop Steam's polls came
3.7 s apart and VK filled its page 12 s after DOMContentLoaded. On a fast machine the rule lets go at p50 5.4 s
from the launch (p90 8.9) and lost no text on the 67 sites; the old rule (stable 0.8 s and nothing in
flight at one poll, then 5 s more for an empty shell) took 6.3 / 9.6 s and lost 2. On the emulated
Celeron: 3 of 67 lost (a bot check that loops, Airbnb still growing at 20 s, gosuslugi.ru), against
12 with the old rule and its 10 s budget.

A text-only render (no `--screenshots`) loads no pictures, media or fonts and takes Playwright's
headless shell first when it is installed: on the 67 sites it read the same text and met the same
walls as Chrome, at p50 4.6 s against 5.2 on a fast machine and 6.4 against 13.2 on an emulated Celeron (faster
on all 36 pages measured there). A screenshot render is a full Chrome in a 1280x784 window with
reduced motion. page.md is html2text's
markdown of the **visible** DOM (`checkVisibility`): headings, links, pictures, tables and code
survive, and what the page hides stays out; innerText was the page.md before and kept none of it.
The browser closes in its own thread while the text is extracted. It starts with the read only
when it will surely be needed - a `#/` route, `--screenshots`, `--alternate` - and right after HTTP
for a shell or a wall, beside the extraction. Not for every read: on an emulated Celeron a browser
launching beside reads that never use it took them from 5.5 to 11.9 s (p50); on a fast machine it would save
0.7 s. A 404, a 410 or a 5xx does not go to the browser (it gets the same answer), unless the answer
is a wall's challenge. A `#/` or `#!` route always goes
to the browser (the server never sees it), and so does a page whose HTTP text is weak *and* that has
a script, an empty mount node, or a wall: a page without any of them cannot change in a browser
(4 of 22 browser runs in measurements were such pages). A page of under 200 words that carries 40 KB
or more of data for its own scripts (an inline script that is JSON, or one filling
`__NEXT_DATA__`, `__NUXT__`, `__INITIAL_STATE__`...) is an app with a teaser and goes to the
browser too (`shipped_state`, 2026-11-19): of 168 HTML pages measured that day four were such
and had seen no browser - it gave 30, 9 and 5 times the text on three (soundcloud 50 -> 1 526
words, aliexpress 79 -> 818, ivi 163 -> 894; 7-11 s a read instead of 1-5) and the same text on one
(a GitHub issue, +3.5 s). No wider rule held: of 26 more script-heavy pages under 2 000 words, read
both ways, the browser added half as much again on four (bilibili, vc.ru, Yahoo Finance, Airbnb),
lost text on two (meduza, notion.com/templates) and changed nothing on twenty - those are what
`--alternate` is for, when the text looks thinner than the page. The browser's text replaces the HTTP text only
when the HTTP text was the reason it ran, and not when it is a wall the HTTP text was not or has
fewer words; length decides nothing else - where both texts were good, "longer wins" chose wrong in
3 of 6 real differences. A browser is listed only when its program is on disk, once. The CLI
`--dump-dom` fallback (15 s) is used when no Playwright/Patchright is installed.

Every launch is **headless, in a fresh context, with no user profile**: the skill never drives
the browser you are using yourself, never reads your bookmarks, history or passwords, and never
opens a window. The only state it carries in is the per-site cookie jar it stored itself (`7`
hours, droppable with `--clear-cookies`). A snap- or flatpak-confined build is detected by path;
actually launching a snap needs snapd and AppArmor, which a container (and therefore CI) does not
have - that is a packaging question, not a UI one.

If none launches, `missing: browser` is reported; a machine with no browser still reads everything
that is not JavaScript-rendered.

## Rescue tiers at once

When HTTP's answer says the page will need rescuing, the next tools start together instead of one
after another; each is bounded by the read's deadline:
- a dead host or a 5xx: the readers and the archive (when allowed), no browser;
- a wall's status (401, 403, 407, 419, 429, 451) or header: the readers (when allowed) beside the
  browser;
- a 404 or 410: the archive (when allowed); a reader then only confirms, with `--refresh`;
- `--force-external`: the readers from the start;
- a shell or a wall with little text: the browser, beside the extraction.

The answer is chosen as before - the same order of preference - only sooner: the readers and the
archive took up to 20 s each in a row. A reader started this way is only one the read would ask
anyway, so no credit is spent on a page that did not need it.

## Screenshots (`--screenshots [N]`)

A vision path for pages that have no text to read (`scripts/screens.py`). `N` counts **screens of a
1280x784 window** - a laptop's layout - and the default is 2. With Pillow or PyMuPDF two screens
are glued into one **1280x1568** picture, the long edge a vision host keeps without resizing; without
them the screens come one by one and `improve:` names Pillow. Nothing is scaled.

- The page is scrolled screen by screen (an inner block when the page scrolls one, as Spotify does).
  The old full-page clip took 10-49 s a tile on long pages, gave no tile on some, and caught the
  pictures of tiles 2-3 blank on 9 of 12 pages: they had not loaded.
- Per screen: one wait for its pictures, its fonts and a quiet page (no DOM change for 150 ms), at
  most 0.6 s (measured p50 0.14 s, p90 0.26; a picture that never loads reaches the cap); then the
  bars are hidden and the screen captured. The context asks for reduced motion and animations are
  stopped, so a section is not caught halfway through its entrance.
- Bars: a header-like bar (top <= 5 px, at least half the width, at most 160 px tall) stays on
  screen 1 and is hidden from screen 2 on; every other fixed or sticky element is hidden at once, by
  opacity. Hiding everything left a 57-280 px empty band at the top of screen 1 on 8 of 12 pages,
  and `visibility` leaked children (Squarespace).
- PNG, captured once; a picture over 3.75 MB becomes JPEG q95 in one pass (the worst case, noise, is
  5.76 MB as PNG and 2.25 MB as JPEG q95). Metadata is not written.
- The last screen of a page stops where the page ends; the part the screen before showed is cut,
  never repeated. `signals.screens` says how many screens came, `signals.screens_needed` how many the
  page has when that is more - `N` was smaller, or the read's deadline ended the loop with what was
  taken.
- PDFs go through `pymupdf` as the same 1280x1568 pictures of two screens; docx/xlsx/pptx/epub have
  no pages and say so.
- Cost: a 1280x1568 picture is ~2 700 tokens (about w·h/750). Measured: MDN, three screens 6.9 s in
  all; Wikipedia's Cat 13.2 s (the old way: Moscow's three tiles took 124 s).

## Rules that came out of the measurements

- **Do not ask a browser to be "better than curl".** Headless Chrome is detected by Cloudflare even
  with patched fingerprints (all variants tested); a TLS-impersonating HTTP client passes the same
  page without any JavaScript. Two instruments, not one ladder.
- **Never trust one extractor.** `main/visible` below ~0.35 means the text is a fragment; `page.md`
  already holds the rest, so no second network call is needed.
- **One page, one fresh browser context.** Reusing a tab after a challenge page leaks state
  (`Execution context was destroyed`); reusing the process is fine and costs 17 ms per context.
- **A 404 is data.** The browser also exposes the status; a text-only pipeline does not.
- **Errors cost money** on Firecrawl, Exa and Tavily (a 403 or 404 is still one credit), so never
  retry a wall through them blindly: each reader is asked once a run.
- **The extractor only suggests** (`scripts/blockrule.py`). A block of `page.md` that is
  not in the text - fewer than half of its 5-word runs are there - goes back after its kept
  neighbour when it is prose (25+ words, under 30 % links, not a banner), code, a table (not a
  layout table of links) or a captioned figure; a heading goes back with its section. Menus, link
  lists, fragments and cookie banners stay out, and the header says `outside the text: N KB`. On
  the 60 extracted pages of a measured corpus 23 change: 22 of 59 ordinary ones gain 95 KB in all
  (+2.1 %), and RFC 9110, where trafilatura kept 5.5 KB of a 470 KB page, goes from 5.5 to 374 KB.
  At worst 0.3 s a page.
- **Internal hosts never go to a third party and never use TLS impersonation** - plain curl fails
  fast and nothing leaves the machine. A redirect that would leave the public internet is refused.
- **Pin more than one fingerprint.** Sites add rules against the freshest Chrome profile: on 2026-10-30
  npm returned 403 for `impersonate="chrome"` and 200 for `chrome124`, `chrome120`, `safari17_0`.
  The client walks `IMPERSONATIONS` on a refused 4xx instead of giving up, then plain curl once.

## Every timeout, retry and fallback: one deadline, a fuse per step

Every step is recorded as it ends (`scripts/budget.py`): start, seconds, its own cap, the cap it got,
and `ok`, `cap`, `deadline`, `stall` or `fail`. With `READ_PAGE_DEBUG=1` that list and much more go
to the read's log file (`scripts/debuglog.py`; `debug/*.jsonl` in its folder, or
`READ_PAGE_DEBUG_DIR`), never to the answer. Its kinds: `run` (version, flags, OS, CPUs, Python,
`READ_PAGE_*` settings, which keys exist), `caps`, `step`, `event` (what `trace()` names: HTTP
attempts, cache, extraction), `decide` (after HTTP, extraction, browser needed, browser text,
status - each with every input of its rule), `browser` (launch, page open, loaded, each poll that
changed something, settled), `net` (each response and failure, redirect hops included),
`picture`, `error` (an exception caught and gone on from, with its last frames) and `summary`.

**A read ends by 55 s, the CLI and MCP alike**: MCP harnesses cancel
a call at about 60 s (Codex, Cline, Cursor, Claude desktop), and a cancelled call returns nothing,
while our own deadline prints what arrived. It is a backstop, not the plan: each step keeps its own
bound, a fuse against a stuck tool, and takes no more than what the deadline leaves after the
**tail** - the block rule, the pictures and the answer always keep 6 s. What arrived by the end of a
step is kept. The constants are at the top of `readpage.py` and in `scripts/budget.py`;
`--download` has no deadline and lifts the HTTP and picture bounds.

| Step | Bound | Inside it | Notes |
|---|---|---|---|
| HTTP | until **14 s** before the deadline (a 45 s fuse) | connect 7.5 s an attempt; the transfer is cut below 1 KB/s for 10 s in a row | no fixed total any more: a slow but moving link is not cut (at 1 Mbit/s and +300 ms a page took up to 16 s). A stall is cut by the connect timeout and the speed floor. What arrived is kept with `signals.partial` |
| `curl_cffi` fingerprints | inside the HTTP step | 1 each (2, a 3rd after two plain 403s); the next one **only** after a refused 4xx (not 404/410) | a timeout breaks out: a dead host will not answer another fingerprint either |
| plain `curl` | inside the HTTP step | once after every fingerprint was refused, or for an internal host; the same speed floor, `--max-time` is what is left of the step | a dropped connection (empty reply, reset) is tried once more on a new one |
| certificate error | inside the HTTP step | +1 unverified | recorded in `signals.tls`; only for public URLs |
| redirects | inside the HTTP step | up to 8 hops | every hop is checked by `hop_refused()` |
| extraction | the deadline (a 120 s fuse with `--download`) | **defuddle**: one worker per read (`ddworker.js`), loaded while the HTTP request is in flight, the CLI's own call and text; **page.md**, the main block and the visible length in Python beside it; **readability and trafilatura** side by side in processes of their own, only when defuddle is weak or missing | defuddle still working at the deadline: page.md is the text (`signals.extract_late`). A process still working is killed: nothing in-process can hold the read |
| a page over 3 MB of HTML | the deadline | no article extractor: page.md is the text, from html2text and crude_text side by side in processes of their own (`signals.huge`; `--alternate` still runs them all) | the HTML spec (16 MB) took 155 s and 1.2 GB, ECMAScript (7.8 MB) 55 s; now 10.5 and 5.8 s on a fast machine. content.md had come out at 95-100 % of page.md anyway |
| browser | **25 s**, leaving 1.5 tails before the deadline | one browser, 20 s for the load and the settle rule (`settle.py`); a page HTTP met as a wall gets at most 10 s to DOMContentLoaded; a second browser **only** when the first fails to start | a page one Chromium cannot render, another cannot either: the second try used to double the step. A load timeout still returns the DOM it has (`signals.render_partial`). A wall's challenge that has not loaded in 10 s is looping (wildberries once held all 20 s) |
| browser CLI (`--dump-dom`) | 15 s | the same rule | only when no Playwright/Patchright is installed |
| site API | **10 s** | Stack Exchange, npm, Hacker News, X, PubMed; the comments of a story in parallel | the page itself is read only when the API fails: the API answered on all 16 reads of a check, and a request beside it was one more to the site, and CPU on a weak laptop, for nothing |
| readers | **20 s** | Firecrawl, Jina, Exa, Tavily, defuddle.md, at most 12 s each; the next only while 2 s are left | only with `--allow-external`; no reader is asked twice (a credit each time) |
| Wayback | **20 s**, leaving 1.5 tails | the CDX lookup and the snapshot together; once per run | the CDX API itself sometimes takes a minute |
| pictures | **6 s**, inside the tail (about 4 s near the deadline) | 32 threads; a connection silent for 4 s is stuck; only the pictures of the lines an answer prints, each call its own; one 6 s phase an answer, shared by up to three rounds as the printed window grows; one cut by the phase or lost to the network is fetched when its lines are printed again; one another page of the host has is a hard link, no request | `--download` takes every picture of the page with no limit; the site's cookie jar is sent with each request; what the phase did not reach is marked `not downloaded: no time (6 s)`. 6 s, not 4: with no limit 129 reads of picture-heavy pages took p95 2.6 s and at most 5.8; 4 s cut 2.3 % of them, twice pictures still arriving (NASA), and 6 s none |
| `pdftotext`; a machine's own `pandoc`, then `markitdown` (an office file nothing else reads) | 10 s each | 1 | local converters; a hung process is killed |
| our EPUB, ODT and RTF readers (`docreaders.py`) | **10 s a read**, all its documents together (a ZIP's too), less near the deadline; none with `--download` | a process of its own (`-I -S -B`: the standard library alone), which stops reading a little before the time, writes what it read, and is killed at the time; RLIMIT_AS holds it to 2 GB where the OS has one | a process start costs about 0.1 s on Windows, 0.05 s in WSL. Before (in the read's own process) a few KB of hostile EPUB, ODT or RTF held a read for 62-91 s; 68 hostile files of this kind now end in 8.9 s at most. A ZIP's document the time did not reach, or whose reader was stopped, says so under its name |
| a package's picture order | **10 s**, less near the deadline | a docx's `a:blip` references, an EPUB's spine and the `<img>` of each chapter, in the read's own process; no picture, no scan | tags read as `[^<>]{0,8192}`, a set beside each list, a chapter named twice scanned once; with no time left there is no order, not a guess (`images_ordered` unset). A 40 000-tag container: 68.9 s before, 0.00 s |
| a PDF's tables | **10 s a read**, all its PDFs together (a ZIP's, an archived copy) | the layout model in a process of its own (`-E -B`: a caller's PYTHONPATH stays out), a page at a time while the next are chosen; a page over 8 000 vector paths or 2 000 words in a block is not asked | the model's call cannot be interrupted: a process still at work when the time is up is killed, its pages named (`signals.tables.left`, `heavy`), and one whose read was killed from outside ends with it (it watches the read's process; where the OS will not let it - a sandbox that refuses SYNCHRONIZE on Windows - it is not watched, and stdin's end ends it with the read). A page of 5 010 strokes (20 s in the model) read in 10.8 s; before, 20.7 s, and a scatter plot of 20 010 strokes 27.5 s |
| `--alternate` on a PDF | what the read has left | pymupdf4llm's Markdown: a warm-up call of 2 pages gives the model's rate, then calls of 10 pages at most, each to fit what is left (one call with `--download`) | the pages no call reached stay plain, named in `signals.tables.left` and the advice; 600 pages: 49.7 s (262 s at one go); four reads of GPT-3 at once on two slow cores laid out none in 51 s with one long call, 26-27 of its 75 pages each in 50 s with calls of ten |
| OCR | 30 s for all pages | up to 3 pages side by side | scans only; three pages took 1.3-1.5 s together |
| `yt-dlp` | 20 s | 1 | network-bound: subtitles only; the watch page (its cover, or the page itself without subtitles) arrives beside it; when it gives none, YouTube's caption track through youtube-transcript-api (its own 20 s) |

Before the deadline the worst case, every step in a row on a wall with `--allow-external`, was
about 105 s, and a huge page took minutes. Now a read ends by 55 s; an ordinary page takes 1-3 s
on a fast machine. A PDF or an office file cut by the HTTP step says why: still arriving when its
time ran out is `too_large` ("the PDF was still arriving when the time for it ran out (41 s): 160K
of 1.9M", advice `--download`); a server that stopped sending, or a connection that broke, is
`error` ("the server stopped sending the PDF after 12K of 195K"). A PDF needs its last bytes, and a
cut ZIP is not mended. On every bound what arrived is kept: the HTTP body, the browser's DOM, a
slow reader's text, a half-arrived archive snapshot (`partial`), the OCR pages that finished
(`signals.ocr_timeouts` names the others).

Start-up is cheaper too: a tool's path is looked up once per process (a Windows lookup walks every
PATH folder with every PATHEXT ending; a read asked about 13 times), urllib's openers, and with them
the system certificate store, load on first use, and curl_cffi is imported without the markdownify,
bs4 and readability it pulls in for a method this skill never calls. The MCP server keeps one warm
`readpage.py` (imports done) for the next call; it serves one call and exits.

## Optional dependencies, and `--setup`

Core is stdlib only: with just `curl` the skill still fetches and reports. Each addition raises
quality, and the manifest's `improve[]` names the ones worth adding - as `readpage.py --setup`
wherever it installs them, else the machine's own command:

| Engine | Adds |
|---|---|
| `curl_cffi` | Chrome TLS fingerprint (npm, Medium, Reddit), better charset handling |
| `defuddle` (Node) | best main-content extraction (1.5-3x more text on docs sites) |
| `trafilatura`, `readability-lxml`, `html2text` | in-process extraction and `page.md` |
| `pymupdf`, `pymupdf4llm`, the office readers | PDF and its tables (the layout model, [documents.md](documents.md)), office documents, a plain ZIP; EPUB, RTF and ODT need nothing (our own readers, the standard library: pandoc left on 2026-11-21) |
| `yt-dlp` | video transcripts |
| Playwright and its `chromium-headless-shell` (or Patchright + Chrome/Edge) | JavaScript rendering |
| `pillow` | MCP `inline_images`: GIF, WebP, AVIF, BMP as PNG, pictures over 1 568 px scaled (PyMuPDF does SVG) |
| `tesserocr` (tesseract 5.5.4 inside), or the `tesseract` command | scanned PDFs, `--ocr N` |
| `FIRECRAWL_API_KEY`, `EXA_API_KEY`, `TAVILY_API_KEY` | the pages nothing local can read; any one of them, in that order |

**`--setup`** (`scripts/envsetup.py`) installs all of them but the keys into the skill's own
environment, a folder of the user's that every agent on the machine sees (`ownenv.home()`:
`.read-page` in the home folder on Windows, `~/Library/Application Support/read-page` on macOS,
`$XDG_DATA_HOME` or `~/.local/share/read-page` on Linux; `READ_PAGE_HOME` moves it). Not AppData on
Windows: a packaged app (MSIX - Claude's desktop app is one) gets a private copy of whatever its
processes write there, so an environment an agent built inside such an app did not exist for a
terminal or for the next agent ("not set up" in that agent's shell, every read in the machine's
Python), and its files were slow to reach (a stat 372 us against 49 in the home folder). What it
installs: uv 0.13.9 from
PyPI (its wheel's SHA256 pinned in `envsetup.py` for every platform: `UV_WHEEL_SHA256`), CPython 3.13.18 from python-build-standalone through it (`--no-bin
--no-registry`: nothing outside the folder), a venv `envs/py<version>-<lock hash>` with the 54
packages of `scripts/setup-lock.txt` (each file pinned by SHA256: `tools/setup_lock.py` writes the lock
with `--generate-hashes` - 1 092 files, about 94 KB - and uv checks the hashes of `-r` and of `-c`, the
one-package-at-a-time fallback and the yt-dlp step included; yt-dlp, which floats, has none and is not
refused for it; wheels only; a package with no wheel for the machine is left
out and named) and, not pinned, yt-dlp in the newest release that has been out three days
([video.md](video.md)), Node 24.22.3 from nodejs.org checked against its archive's SHA256 pinned in `envsetup.py` (`NODE_SHA256`; a
mirror - `NODEJS_ORG_MIRROR` - serves the archive, never its checksum; else
`nodejs-wheel-binaries` 24.19.0 from PyPI, for networks that reach PyPI alone), defuddle 0.19.4
through that npm (`--ignore-scripts`; its own 26 packages as npm resolved them as of one fixed
instant, `--before=2026-11-19T00:00:00Z`: the pinned version must exist by it), Playwright's `chromium-headless-shell`
(`PLAYWRIGHT_BROWSERS_PATH` = the folder's `browsers`), `eng` and `rus` from tessdata_fast 4.1.0
with pinned SHA256 (plus any language `READ_PAGE_OCR_LANGS` names) - then a check of every engine
on a sample (import, defuddle on a page, the browser on a page, OCR of a rendered line). No
pandoc since 2026-11-21: our own readers read EPUB, ODT and RTF ([documents.md](documents.md)).
tessdata_fast against tessdata_best and the standard tessdata, through tesserocr on
60 readings of English, Russian and mixed text in three fonts and two sizes, clean and as a poor
scan (2026-11-19): clean CER 0.19 / 0.48 / 1.71 %, poor 39.6 % all three, 0.21 / 0.61 / 0.45 s a
picture, eng+rus 8 / 31 / 43 MB; on the agent post's figures fast found as many words at
confidence 80+ (Figure 1: 55 / 50 / 48, 14 / 14 / 15 of its 16 labels) in a third of best's time.

**Platform floors.** The whole set installs with one `uv pip install -r` of the lock; where that fails
(a package of it has no wheel for the OS and CPU), the 16 top packages go one at a time, and each that fails is
named in `setup.json`'s `problems` with a reason and a fix. uv's words tell a missing build ("has no wheels with a
matching platform tag", "Wheels are required for X because building from source is disabled") from any other
failure, which is said as it was. A real install on every GitHub runner (`.github/workflows/install.yml`,
2026-11-21, the lock of that day) found: Windows on ARM has no wheel of `pymupdf-layout` (so no PDF tables),
`tesserocr` (no OCR; `pypandoc_binary` had none either, and left the lock on 2026-11-21); musl Linux x64 none of
`pymupdf-layout` (no PDF tables) or `playwright` (no browser: nothing else drives one, so JavaScript pages stay
unread); musl arm64 also none of `pymupdf` (PDF text comes from `pdftotext`) or `tesserocr`. Node on musl is
`nodejs-wheel-binaries` (nodejs.org has no musl build). The fix of a missing engine that is a program (OCR,
PDF text) is the machine's own package (`ownenv.system_install`: winget, brew, or apt, apk, dnf,
zypper, pacman by `/etc/os-release`, with no `sudo` for root); for the others it is the plain "none here", and
what still reads. A bare Linux also lacks the system libraries of Chromium: `playwright install-deps
--dry-run` names them, and the fix is `apt-get install` of that list. Each matrix row of `install.yml` lists
what its runner lacks; a gap that is not on the list turns the job red.

**OCR under a folder with letters outside ASCII.** tesserocr opens its data folder in the ANSI code page of the
system, so `C:\Users\Иван\.read-page\tessdata` failed (code page 1252) and OCR was dead without a word. The
folder goes by its 8.3 short name where the volume makes one (the system volume does; a runner's `D:` and a
dev drive do not), else by its own name, which is ASCII, from its parent: the working directory is moved there
while tesseract starts (`ownenv.tess_dir`; it reads its data at the start, and the picture is read after).
Measured against a Cyrillic folder on code page 1252: the absolute path fails, the relative one reads.

The work runs detached (its parent, a launcher, is gone at once), so a harness that kills a
long command does not kill it; the command shows its progress for 100 s (in a terminal, to the
end), then says it goes on in the background, and a second `--setup` follows the one at work - a run
that is not done, whose process is alive and whose `setup.lock` is held; nothing else counts as one.
Where a Windows job around the command kills on close and lets nothing leave (a harness that runs
each command in one), the work would end with the command: `--setup` then says so and follows it to
its end. That is asked of a small child that has broken away (the job it lands in is the first that
lets nothing leave), not read from the job the process is in: a venv's `python.exe` runs its
interpreter in a job of its own, nested in the harness's, and hides it. A background yt-dlp update has a lock of its own (`ytdlp.lock`); a `--setup` waits for it, up
to five minutes, and holds it for its run.
Its first line says what it will download (about 390 MB on Windows, 445 on Linux, 355 on macOS -
the pinned wheels by PyPI's sizes, the Python, Node and browser archives by their Content-Length;
430, 480 and 380 with pandoc) and keep (about 0.95 GB on Windows, 1.1 GB on Linux; 1.2 and 1.3
with pandoc), or that the folder is up to date and only a check follows. The steps run
one after another; only the check's engines answer side by side. Side by side was built and
measured (2026-11-19, from nothing into fresh folders): 62 and 68 s against 68 and 65
one after another, WSL 83 against 79 - no gain, so not kept. The link is the limit: 9 MB/s, no
faster with four downloads at once; of the ~65 s, ~48 are downloads (430 MB) and ~18 the local
work (unpacking Node and the browser, npm's small files, the venv, the check), and the branches only
shared the link - the engines took 59 s instead of 26 beside the browser's download.
Each run builds the venv for the skill's pins (a new folder when they change, from uv's cache:
7 s on that machine; the lock it was built from is copied into the folder, the yt-dlp updater's constraints),
switches `setup.json` to it at the end, keeps the previous one for reads still in
flight and deletes older ones. `readpage.py` and `mcp_server.py` check `setup.json` before their
other imports (`ownenv.use`): outside the environment the run goes on under its Python - `exec`
on POSIX, on Windows a child with the same arguments on the same console, the first process itself in a job
that dies with it before the child starts (so everything the read starts is born inside it, nested
inside a harness's job where there is one), its exit code passed on - and inside it the venv's `Scripts`/`bin`, Node and the
npm prefix come first on `PATH`, with `PLAYWRIGHT_BROWSERS_PATH` and
`READ_PAGE_TESSDATA` set. Measured on Windows (2026-11-19, the environment in the home folder):
`--version` 0.18 s in the machine's Python, 0.24 s in the environment's, 0.34 s through the hop
(0.29 and 0.40 s while the environment was under AppData, inside a packaged app's private copy;
full reads of 8 local corpus pages were p50 1.38 -> 1.49 s there).
`READ_PAGE_SKIP=env` keeps a run in the Python it was started with; a broken environment (its
Python gone) is skipped with the reason in `--caps`. A Python that is there, starts and fails (an
antivirus quarantined a DLL it needs, a damaged standard library) is found out by a start-up
handshake: the parent makes a file, the child removes it as its first act, and a child that ends with
the file still there never reached the read - the read then runs in the machine's Python, the answer
has an `environment:` line (`signals.env_failed`) and `--caps` says why. On POSIX, where `exec` leaves
nothing to fall back from, the first run of each build is a child (`setup.started` in the folder
holds the build once one has started); after it `exec` is kept, and only that first start is guarded.

What is fetched is checked as far as each source allows: the packages by the lock's hashes, uv's wheel
and Node's archive by hashes pinned in `envsetup.py`, defuddle's packages by npm's own integrity
values from the registry (`--before` fixes the set), the language data of English and Russian by SHA256
in the code and any other pack by Content-Length and by tesseract starting with it, Playwright's
browser by TLS and its Content-Length only (Playwright's design: no hash anywhere in its download), and
yt-dlp - not pinned - by TLS. urllib trusts the machine's certificate store; uv and Node are told to
(`UV_SYSTEM_CERTS=1`, `NODE_USE_SYSTEM_CA=1`, checked in uv 0.13.9's and Node 24's own help: 153 system
roots beside Node's 118 bundled ones on the measured machine) unless the user set them, so a proxy that inspects TLS with
its root in the OS store works for every download; a step that fails on a certificate says so once.
Inside the folder besides the engines: `cache/node-compile` (npm's compiled modules, `NODE_COMPILE_CACHE`),
`cache/pycache` (the skill's Python bytecode while a read runs in the environment; `sys.pycache_prefix`),
`cache/yt-dlp` (the environment's yt-dlp is given `--cache-dir`) and `cache/uv`. uv's cache holds every wheel
the environment was built from, hard-linked into it, so it costs the disk what its files have no other name
for (the closing line and the report give both numbers; on macOS uv clones rather than links, and that second
number is an upper bound). Plain `uv cache prune` removes nothing of what an update leaves (measured with
uv 0.13.9: the wheels of a deleted environment stay reachable, "No unused entries found"), so an update
runs `uv cache clean` for the packages whose pin moved - before it installs the new ones, which a clean
afterwards would take out too - and a yt-dlp update does it for yt-dlp and yt-dlp-ejs; where an older
environment's lock was not kept, `uv cache prune --ci` removes every wheel (527 MB to 15 MB measured; the
environment keeps its files by their links, and the next update fetches what it needs again). Outside the
folder: the read cache (`read-page` in the temp folder) and, for a read that does not run in the
environment, the skill's bytecode there.

Where the installers fetch from can be redirected - by variables, a `uv.toml`, an `.npmrc`, a `pip.conf` -
and the setup names each such setting at the top of its log, with its value (credentials left out), and keeps
the lines in `setup.json` for the report. uv is run with `UV_NO_CONFIG=1` unless the user set it: uv looks
for a `uv.toml` (or a `pyproject.toml` with `[tool.uv]`) in the working folder's parents, the user's and the
system's configuration folders, and measured with uv 0.13.9 a `uv.toml` in a parent of the folder sent the
install to the index it named, so what is installed would depend on where the folder is and on files nobody
told about it. `UV_NO_CONFIG=1` ignores all of them (user-level too) and still honours the environment's
variables (`UV_DEFAULT_INDEX`, `UV_EXTRA_INDEX_URL`, ...) and an explicit `UV_CONFIG_FILE` (also measured):
a company's mirror is one variable. A `uv.toml` that names an index is listed as not read, with that advice,
and a failed `pypi.org` check names it as the likely cause. `NODEJS_ORG_MIRROR` must be `https://`; a
plain-http one is not used (nodejs.org is), though the archive's SHA256 is pinned either way.
`UV_NO_VERIFY_HASHES` would switch off the lock's hash check: it is not passed on. `NODE_TLS_REJECT_UNAUTHORIZED=0`
and the like are named, not undone.

`caps()` - what this machine has - costs ~0.3 s on Windows (every tool name against every PATH
folder and PATHEXT ending), so it is kept for an hour in `caps.json` in the cache and asked again
the moment PATH, a PATH folder, site-packages, the Python or the tessdata folder changes; the setup
report and `--caps` always ask fresh. A cached answer does not ask at all: 0.3 s instead of 0.6 s.
