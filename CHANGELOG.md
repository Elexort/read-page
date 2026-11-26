# Changelog

## Unreleased (0.5.0)

Two branches: `main` is the skill alone - SKILL.md, README.md, scripts/,
references/, LICENSE and .gitattributes, 35 files - so a clone, a ZIP or an installer
brings an agent nothing else; `dev` carries the code with its tests, CI, notes and this log.
`tools/publish.py` makes main's commit from dev's HEAD. Some harnesses show the agent every file
of a skill's folder (483 files in a development copy, 64 in a clean clone of the old main).

- **`--from "text"`: go on from a quote** (KNOWN-ISSUES 265): the answer starts at the first line holding a piece of
  text, whitespace folded and then without case; when several do, the first at or after where the last answer of that
  file started (`_from` in the saved manifest). A quote cut in the middle of a line matches, one of several lines by its
  first; a marker is found by its type and name - a picture by its number - whatever its state and properties say:
  `--from "[tab · Developer Plan Limits]"`, `--from "[img #3]"`. No line holds it: the answer says so and shows the
  outline. `content.md` and `page.md` alike; MCP's `from` takes text on `read_url` and `read`. SKILL.md's "rest of a long
  text" bullet names `--from "<words of a line>"` and `--to M`; the room came from its own lines (5 625 -> 5 614
  characters, 930 words).
- **`--from N --to M`: a range the agent asks for** (KNOWN-ISSUES 264): lines N to M whatever the block, for a harness
  that shows more than one (Codex with an OpenAI model about 40 000 bytes, goose and OpenCode 50 000), at most 150 KB
  a call; `--to` alone reads from line 1. The skill cannot see what the harness shows, so such an answer says its lines
  were sent - `── content.md: lines 1-300 of 812 sent; cut by your tool? go on from the last line before the cut: the
  same command with --from "<its words>" --file content.md ──` - and its bottom line names the next range, as long as
  this one, and the same way back: most harnesses keep both ends of what they cut. The text's lines carry no numbers;
  the range, the pointers and the outline keep theirs. Without `--to` nothing changes; a `--to` before `--from` is left
  out and named. MCP: `to` on `read_url` and `read`. `--until`, `--lines` and the like are still not flags; their note
  names `--to`.
- **The answer's block counts characters too** (KNOWN-ISSUES 263): Cline's SDK runtime cuts every tool result, MCP
  too, at 8 000 characters (UTF-16 units), keeping about 3 985 at each end - in its code since 2026-06-19, and missed
  by the survey the block was set on, so an English block of 9 850 characters lost about 2 000 from its middle there.
  An answer is now at most 7 900 characters as well as 9 980 bytes and 495 lines (`answer.BUDGET_CHARS`, counted as
  Cline counts them). English text meets the characters first - a block about 7 700 characters, Node's fs reference 54
  answers where it took 43 -, Cyrillic and CJK text the bytes, unchanged. The docstring of `answer.py`, `answer.md`,
  `mcp.md` and README say what the block rests on now; `tests/contract.py` checks every answer's characters, CLI and
  MCP.

- **Tabs, collapsed sections and selects are shown honestly** (KNOWN-ISSUES 256-258, 262): a tab set's labels went with
  the buttons and lists that hold them, and a panel the page hides came into the text with no word of which tab it
  was, or not at all - on Groq's rate limits the default tab's table stood under the site's note that the limits below
  are the Developer plan's, and a model answered from the wrong plan. `scripts/tabs.py` puts a marker where the page has
  each one, in one grammar - the type, the state, what more there is, the name last: `[tab · shown · Free Plan
  Limits]`, `[tab · hidden, but extracted · Developer Plan Limits]` with its text after it, `[tab · loads on click, not
  extracted · Batch Limits]` for a panel the page does not hold, `[section · hidden, but extracted · Specifications]`
  for a closed `<details>` or a collapsed accordion, `[select · chosen: EU · also US, APAC · Region]`. A hidden panel
  over 4 KB stays in `page.md`, and its marker says so and names its line there. Only the main content is marked; a
  panel keeps its place and its attributes but those that hide it; the browser's `page.md` keeps the hidden panels
  too; the engines are weighed without the markers. On 143 saved pages of the bench, the corpus and the tab set
  read offline before and after, the 101 with nothing to mark came back the same, file for file. `signals.tabs`
  counts them. The marking walks each tree once: a closed `<details>` of 80 000 items takes 0.8 s, not 11.5.
  SKILL.md's line on clicking says a tab loaded on click is named, not extracted; with the share's lines it stays
  shorter than before (5 625 characters and 930 words, from 5 640 and 932).
- **A page that shows only a loading message is no plain `ok`** (KNOWN-ISSUES 259): console.groq.com/settings/limits
  (signed in) read `ok` with its intro and "Loading organization limits...". A line of its own that says the content
  is still coming, beside under 150 words, sends the page to the browser and, if it is still there, makes the status
  `empty` with the message in `reason:` and an advice that the content did not arrive (often a sign-in);
  `signals.loading`. Of 294 pages' texts 5 had such a line, the other four beside 480-870 words or a script's shell.
- **A deep address that lands on the site's home page says so** (KNOWN-ISSUES 260): groq.com/pricing is a 308 to
  groq.com/, and the answer said it only by its `url:` line. The advice now says the page asked for may be gone or
  moved, and `signals.redirect_root` names the address; the home page by another name (`/index.html`, `/en/`) is no
  such case, and none of 292 addresses of the bench, the corpus and the campaign was.
- **A paywalled fragment says the rest of the article is not in the page** (KNOWN-ISSUES 261): its answer showed
  `page.md`, whose `next:` line led a model on through the site's menus, unable to tell a hidden article from an
  absent one. Its first line says `paywalled: the rest of the article is not in the page`, the answer shows
  `content.md`, and the advice says `page.md` holds the site's menus and links, not more of the article.
- **A PDF's tables on a busy weak laptop: the layout model's 10 s are its own work's** (KNOWN-ISSUES 237): four reads
  at once on an emulated Celeron gave the model's process a fifth of a CPU, its load alone took 11-14 s, and a fixed
  10 s laid out none of a paper's four pages of tables. The process now says its pace every half second and with
  every answer - its seconds at work over its CPU seconds, a CPU second counted once however many threads spent it -
  and the step gets as many times 10 s as it is slowed (by a tenth or more), within the read's deadline less one and
  a half tails; with a CPU to itself, and before its first word, 10 s as before. Old code against new, in pairs: four
  reads at once on the Celeron's budget lay all four pages out (the step 18.8-23.2 s; the slowest of the four reads
  29.0-31.9 -> 30.2-34.9 s, none near its 55 s); one read at a time there, an N100's four cores and this machine are as
  they were, long PDFs too (GPT-3 11.2-11.6 -> 11.1-11.5 s, 200 pages of tables 11.3-11.4 -> 11.4 s). The plain "the time
  the read has left" was measured and not taken: those 200 pages took 24.4-25.8 s here with it. When the time still
  runs out, the answer says so, as before: "the tables on pages 6, 8-10 are still one cell a line (the time for
  tables ran out ...)".

- **The first line names the share of the page only for a suspected fragment** (KNOWN-ISSUES 255): it said
  "defuddle, 49% of the page" on every read, and an agent took that for "I got half the content" and kept calling
  `--alternate` - while a whole text seldom holds all of a page's words (menus, footers and links make the rest: on
  the acceptance bench 7 of 40 whole texts were under 70 %, the 3 fragments under 30 %). A whole text's line has no
  share now; a text under a third of the page's words says `maybe a fragment: the text is 21% of the page's words`
  beside the engine (it was a bare `fragment` near the end), and its advice says the same measure. `content.cover`
  stays in the manifest for every read; the MCP server's answer is the same. SKILL.md's description, example, `ok`
  row and `--alternate` (for when neither the text nor `page.md` has what the page shows) say so, and SKILL.md is
  69 characters and 12 words shorter than before.
- **A cut workbook shows what arrived of the part it was cut in** (KNOWN-ISSUES 254), the fix wave's design question
  decided by measuring what each choice shows: 9 Excel workbooks from government sites cut at 21 points each.
  Excel keeps a workbook's text in its shared strings, after its sheets; a cut took them whole in 47 % of the cuts
  and openpyxl, at the first string it did not have, read nothing - 34 % of the cells were shown in all. Now the
  member the archive was cut in is read as far as it arrived where a reader can take one in part (an ODS's
  content.xml, a workbook's sheet up to its last whole row, its shared strings up to the last whole entry), and a
  cell whose string is lost reads `[lost]` beside its number: 53 % of the cells right, 18 % marked, none wrong
  (empty cells for the lost strings would have left 15 % wrong with nothing said). An external link whose part or
  relationships are lost no longer stops openpyxl. On the ODS corpus cut the same way, 28 % -> 54 % of the cells
  (Excel's ODS, content.xml first: 10 % -> 54 %). `signals.broken_archive` names the `partial` member and the
  `lost_strings`, and the advice says both.
  At most 2^20 stand-ins are made (23 MB of XML): a sheet that names a string far past the table gets none, as before - one index of ten digits asked for 220 GB, and the MemoryError read as "damaged, before its first member".
- **Our ODS reader on real workbooks** (KNOWN-ISSUES 250-253), measured on 34 workbooks and 16 decks from data.gov.uk,
  data.gouv.fr, Zenodo and LibreOffice's own tests, each against its content.xml read apart. A workbook is read as
  its content.xml unpacks, each sheet's rows as they end, so a sheet costs what its rows hold, not its XML: Excel
  writes an ODS cell in about 120 bytes, and a 2.7 MB workbook of 142 MB of XML, cut at 32 MB, gave 21 % of its words
  (now all of them, in 7.1 s and 57 MB); a sheet holds 2 000 000 cells it stores itself (it was 250 000 of any kind:
  repeats, the hostile case, keep that cap), and a part over its size limit says so instead of "its XML breaks". An
  external link's cache - a hidden copy of another file's sheet - is left out (LibreOffice's came out as a sheet
  named after the other file's path). A sheet's text boxes, shapes and pictures - on its page or in a cell - are its
  paragraphs and pictures before its table (they were lost, or glued into one cell word to word), and a cell's
  comment is a note of its cell, after the table (comments were left out: one said why a sheet's figures are
  missing). Every deck read the same, byte for byte.
- **The tables step on a weak machine, profiled** (KNOWN-ISSUES 242, planned): the model's process is ready in 1.2 s
  here and 2.2-2.5 s on an emulated N100 or Celeron, then a page takes 0.25-0.67 s, a third to a half of it in ONNX
  runs. Measured and not taken: ORT's optimized models on disk (0.14-0.15 s a read), its threads (today's four are the
  best below eight), a stricter test of a page before the model (each one loses tables), int8 weights (no gain, or no
  run); two model processes save 23-37 % of a long PDF on four cores or more, cost 12 % on a Celeron's budget and
  double a read's commit, and are planned behind a condition.
- **GPT-3's Table H.1 in its 30 columns** (KNOWN-ISSUES 209): the layout model's grid held them in 14 - five models'
  numbers in one cell, "54.7 62.8 67.4 70.9 78.9" under "XL 2.7B 6.7B 13B 175B" -, so which number was which model's
  was a reader's guess. A column of the grid is now cut where the page's own columns stand inside it: at the gaps no
  word of its rows crosses, when a row names each part, the rows under it are numbers alone and each part's words
  share an edge (`pdftables.split_cols`). On the PDF corpus with no time limit the papers' rows with each cell its own
  654 -> 726 of 889 (H.1 1 -> 59 of 65, and Faster R-CNN's and ResNet's VOC tables whole); no other table changed and
  no word was lost.
- **CI: the layout model's checks hold on a slow runner** (KNOWN-ISSUES 241): row 237's two checks of a model that
  waits failed once on `install.yml`'s macOS 15 x64 runner, whose stand-in load - imports, work done before its sleep -
  took all of the 2 s the checks gave the model. The checks now give it twice that load on the machine and a second
  more; a stand-in whose load works 2.25 s failed the old checks as CI did and passes the new.
- **CI: the Ubuntu container's apt retries** (KNOWN-ISSUES 249): the Ubuntu 20.04 container of `install.yml` failed twice
  on 2026-11-23 on apt's "Connection failed" to the mirrors, before any of our code ran (its re-run passed).
  `tools/ci_container.sh` runs every `apt-get` with `-o Acquire::Retries=5`; `tests/environment.py` checks it.
- **Row 186's last sentence is true again, and two by-design rows are filed** (KNOWN-ISSUES 186, 247, 248): row
  186 said the user's second OCR pack beside English had never been measured on every scan - since row 225 a scan
  is read with the pack of its own script, so the sentence now says what the code does and what row 225's
  measure bounds (all ten packs beside English on an English scan: 0.4 % CER against 0.3, 2.54 s a page
  against 0.92). Filed with their numbers: uv's cache keyed by its index (a toggled `UV_DEFAULT_INDEX` doubles it
  until the 150 MB prune), and Turkish and Vietnamese left undecided by `intl.latin_pack`.
- **`--screenshots` that takes no picture says why** (KNOWN-ISSUES 246): `screens.capture` returned nothing when a
  step of the page failed, and the answer had no screenshots and no word of it (CI's browser job once printed
  `screens None` and nothing else). It returns the step and what it said now: `signals.screenshots_failed`, a
  `screenshots:` line in the header (`none taken - screen 1, capturing: TimeoutError: ...`, or `stopped early`
  beside the screens that came), the budget's `fail` in place of `ok` or `deadline`, and `tests/browser_live.py`
  prints it where a screenshot check fails. A deadline that ends the loop is still no failure.
- **`--setup`'s three Python processes start in UTF-8 mode** (KNOWN-ISSUES 245): the launcher, the worker it starts
  and the yt-dlp updater ran `python -E -B` - and `-E` drops `PYTHONUTF8` too - so on a Chinese Windows a traceback
  with a Chinese path would reach `setup-detail.log` in GBK, in a log that is UTF-8 everywhere else. They have
  `-X utf8` now, like the rest of the skill's processes; `tests/environment.py` checks each command line and that a
  Python given those flags, with no `PYTHONUTF8`, is in UTF-8 mode.
- **The fix for an OCR that does not start survives a long path** (KNOWN-ISSUES 240): its reason was cut at 200
  characters, and under a long tessdata path the words the fix is found by went with the end - the report said
  `readpage.py --setup` where `READ_PAGE_HOME` on an ASCII path is the one that works. A longer reason keeps its start
  and its end now.
- **A scan's rendered pages stay where `files.pages` names them** (KNOWN-ISSUES 239): every read of a file on this
  machine is a `--refresh`, whose cleanup kept the files the manifest names as text and deleted the pages it had
  just rendered (a list), so "look at the rendered pages in files.pages" named files that were gone; and the cache
  step stopped at a list among the files (a TypeError), so a scan or a page read with `--screenshots` into `--dir`
  was never kept. Now a list's files are kept, cached at their places (`shots/01.png`), and a cache hit into
  another `--dir` takes them there.
- **A folder or a document named in GBK under a GBK locale is read like any other** (KNOWN-ISSUES 175): under a
  POSIX locale that is not UTF-8 (`zh_CN.GBK`) a name outside ASCII is GBK bytes, which the skill, in Python's UTF-8
  mode, keeps as they are - but PyMuPDF and tesserocr take a path as UTF-8 (PyMuPDF: "Failed to open file"; tesserocr:
  "surrogates not allowed", OCR dead), `manifest.json` could not hold the name and was not written, and the answer
  printed the folder as `????` (under a UTF-8 locale, a folder of GBK bytes stopped it with an internal error, and
  stopped the pictures of the answer's window). Now PyMuPDF and our readers' processes get such a document through
  a link of ours under an ASCII name, tesserocr its data folder by its own name from its parent, the manifest holds
  the name escaped, the answer and `--json` name the folder in the locale's letters (`资料`), a folder or a path given
  back in those letters (MCP's `read`, an MCP client's path) is the one it names, and the debug log no longer stops
  the read on such a name. `tests/cjk.py` names its folders in Chinese under every locale (they were ASCII where the
  locale is not UTF-8) and makes names of GBK bytes on any Linux; in WSL under `zh_CN.GBK` with no `-X utf8`, `props`
  and `environment` pass, and CI's GBK job runs every suite.
- **SKILL.md's `error` row fits a cut file too** (KNOWN-ISSUES 238): it said "retry later; `--allow-external` adds
  readers and the archive" for every error, and an archive cut short or damaged comes back the same however often a
  file on this machine is read. It reads "retry later; a cut or damaged file: get it again" now; SKILL.md is 12
  characters shorter (5 640), the same in tokens or fewer.
- **CI: the OCR turn checks hold under a profile named in Chinese**: their fakes told an upright page from a turned one by how it came (by its file or as a picture), and from a temp folder that is not ASCII every page comes as a picture; they tell it by the page's mark now, and the page is made in an ASCII folder where there is one.
- **OCR of real scans: a page on its side or upside down is turned upright, a page printed in columns is read with
  the vertical packs, a page whose script OSD is unsure of with the likeliest scripts' packs, Fraktur with its own**
  (KNOWN-ISSUES 232-236). Measured on a corpus of real pages - 92 proofread Wikisource pages with their scans (34 of
  before; 22 Chinese, Japanese and Korean pages printed vertically, 4 horizontal Chinese ones, 17 German pages in
  Fraktur and 15 in Antiqua) and 42 copies of 14 pages turned 90, 180 and 270 degrees - and on the 176 synthetic pages
  of before and 10 new vertical ones, the code as it was and the change one after the other on each page. **Turned**
  (232): OSD's orientation turns the page from 5.0 and OSD tells its script again upright; a page read turned and
  unsure of itself is read as it lay too (OSD took two upright pages of a Fraktur magazine for upside down, at 6.9 and
  9.4) - the 42 copies 67.0 -> 21.6 % CER, no upright page of 278 read turned. **Vertical** (233): `--setup` fetches
  `jpn_vert chi_tra_vert chi_sim_vert kor_vert` (7.9 MB); tesseract's layout finds a page's text written top to bottom,
  and such a page is read again with the vertical packs, its script's first - 27 real pages 103.5 -> 67.4 % (Japanese
  95 -> 53), 10 synthetic ones 95 -> 14. **Unsure** (234): a page whose script OSD is under its trust for, or one it
  calls Latin whose reading is unsure of itself, is read with at most three likeliest other scripts' packs (OSD's own
  answer's, then the scripts OSD was seen to take for it), the most confident kept - 6 of 29 real horizontal pages 90.2
  -> 46.4 %. **Fraktur** (235): `--setup` fetches `frk` (6.4 MB); OSD's own Fraktur (from 2.5) has the page read with
  it, and it is the first script tried for a Latin reading unsure of itself - 17 pages 31.5 -> 20.7 %. Every other
  page reads as before: the synthetic pages in 24 languages, the real horizontal ones in a script OSD is sure of, the
  German Antiqua ones - the same CER, the same time. The pages that need it take longer: 2.2-4.8 s a page against
  1.3-1.9 on this machine; on an emulated Celeron (4 GB) a three-page scan of ordinary pages reads in the same 9.2-10 s,
  and three pages that all need the extra readings in 15-33 s (8-18 before, unread), within the read's 55 s, no page
  late (the OCR step of the hardest up to 29.6 of its 30 s: there the last tries end by time) - where the turned reading of a page left no time to check OSD's turn the check was skipped and a Fraktur page
  read upside down: it is made whatever time is left. 14.3 MB more to download (53.7 MB of OCR data in all). Measured
  and left out (236): one block of vertical text assumed (PSM 5), every script tried on five lines first, OSD asked
  again to confirm a turn.
- **`--setup` says why uv did not come, and Node that it needs uv** (KNOWN-ISSUES 231): the uv step named pip's failure alone (`No module named pip`, musl's Python has none) where pypi.org's answer was what failed, and the Node step on musl said `'Work' object has no attribute 'uv_exe'`.
- **On Windows `--setup` refuses a home too long for the environment's DLLs, before it fetches anything**
  (KNOWN-ISSUES 230): Windows refuses a DLL that carries a manifest - every `.pyd`, curl_cffi's and tesserocr's
  libraries - by a path over 250 characters (measured with small DLLs copied to folders of each length, imported, by
  ctypes and found through `os.add_dll_directory`, inside a packaged app and from WSL alike: 250 loads, 251 is
  WinError 206, "The filename or extension is too long"; one without a manifest loads by 400), and curl_cffi's
  libcurl-impersonate lies 116 characters inside the home. From a home of 135 characters curl_cffi did not load,
  from 138 tesserocr, and `--setup` said so at its check, after minutes of downloads. A home over 120 characters (250,
  less 116, less 14 for pins that move it) is refused now before anything is made or fetched, with its length, the
  limit and the fix - a shorter `READ_PAGE_HOME`; off Windows nothing changes. The check at the end keeps an engine's
  whole reason: it cut "DLL load failed while importing _wrapper: The filename or ex" at 60 characters.
- **`--setup` no longer takes a read of its state that finds nothing for a run that never started** (KNOWN-ISSUES
  229): on Windows a read made while the work replaces `setup.state` cannot open the file for that moment (20-27 of
  about 38 000 reads in 5 s against a writer replacing it as fast as it can), and once 20 s had passed the command said
  "the work did not start" and exited 1 while the work ran to its end. Such a read is no news now: what was seen last
  stands, only a run never seen within 20 s did not start, and where the work's lock is let go (or a run holds it as the
  command starts) the state is read again till a read finds it. On the writer's side a reader that keeps the file open
  stops the replace (WinError 5): past its 2 s of tries the work raised and stopped, its last state lost; it writes the
  state in place then, which a reader does not stop, and goes on where even that is refused.
- **The weak laptop, emulated with its memory and disk** (KNOWN-ISSUES 73, by design): the E-core emulation of the
  numbers here runs in a Windows job whose commit is capped at 4 or 8 GB and whose own disk I/O the job's rate control
  holds at a cheap eMMC's (2000 IOPS, 150 MB/s). Five reads one at a time, two and four at once: nothing failed or
  crawled under 4 GB (four at once held 2.1 GB of commit); one at a time no step reached its cap; four at once on a
  Celeron's budget the PDF layout model's 10 s ran out (the tables came as text), an N100's four cores read them in
  11-12 s with nothing cut; a cold first read took 0.1-6.1 s more on the eMMC. What an emulation cannot show is in the
  row. **`--setup` with each step's work overlapped with the next download, one download at a time, was measured and
  left out**: from nothing it saved 10 % on a fast machine (64 -> 57.5 s), 16-19 % on an emulated N100, 7-14 % on an emulated
  Celeron, whose one core the overlapped steps' own work then shares - under the 15 % it had to save. Found on the
  way, both planned: `--setup`'s command can take a read of `setup.state` made while the worker replaces it for a
  run that never started (KNOWN-ISSUES 229), and a home over 134 characters breaks curl_cffi's and tesserocr's DLLs
  on Windows (KNOWN-ISSUES 230).
- **CI: the macOS proxy job ends instead of hanging** (KNOWN-ISSUES 228): `ci_proxy.py stop` deletes the certificate first and stops each removal at 60 s on a runner, where `security remove-trusted-cert -d` waited 90 minutes for an administrator's answer.
- **Our EPUB reader reads again in its own process** (KNOWN-ISSUES 226): it failed on every EPUB whose parts declare their encoding - `No module named 'intl'`, for the process starts with `-I` - and the read fell to PyMuPDF or to `empty`. **A home named through an 8.3 short name is under the profile** (KNOWN-ISSUES 227): `--setup` no longer changes its ACL. The OMML check compares strings of one width (the n-ary operator made its text twice as wide as the fraction's: 6.3 times the time on macOS, 1.0 alike).
- **Arabic, Greek, Thai and Hebrew join the OCR packs `--setup` fetches for everyone** (KNOWN-ISSUES 225): scripts English reads as nothing (84-99 % CER), whose packs save the most for their share of the web after the ten; 4.9 MB more, 39.3 MB of OCR data in all (35.2 more than English alone). Chosen per page they read their synthetic scans at 2.9 % CER and 2.1 s a page (Arabic), 1.1 % and 1.8 s (Greek), 2.4 % and 1.6 s (Hebrew), 0.5 % and 1.7 s (Thai); the ten languages read as before, page by page. Greek counts from OSD's 0.4 (`OCR_SCRIPT_TRUST`): 3 of 14 Greek pages gave it under 1.0, and no Latin or Cyrillic page of 130 was taken for Greek. On 7 real scans OSD named the script of a Greek and a Thai page (9.8 and 20.9 % against 75-99 with English) and took the others for another; `--ocr-langs`' example is `eng+hin` now.
- **A scanned page is read with the packs of its own script, from ten that `--setup` fetches for everyone**
  (KNOWN-ISSUES 225). `--setup` fetched English and the packs of the user's own languages, and a scan was read with all
  of them: a page in another script read as nothing (Chinese, Japanese, Korean, Arabic, Hindi: 80-98 % CER with
  English). It fetches now the ten languages with the most web text by Common Crawl's CC-MAIN-2026-43 - `eng rus
  chi_sim chi_tra jpn kor deu fra spa por`, 22.8 MiB -, the user's own beside them, and `osd` (10.1 MiB), tesseract's
  own script detection: 30 MB more to download than English alone. Each page is read with the pack of the script OSD
  sees on it - `chi_sim`, `chi_tra` and `jpn` alone, which read the English words in their text themselves, the others
  with English beside them; a Han page with `chi_sim`, then `chi_tra` and `jpn` while the best reading is unsure; a
  Latin page again with the pack of the language its words are in (`intl.latin_pack`) - and never with all of them at
  once. On 40 scans in the ten languages: English alone 46.7 % CER at 0.95 s a page, all ten at once 5.6 % at 5.2 s
  (Korean 35 %), chosen per page 1.4 % at 2.15 s - the CER of each page's own pack. OSD adds 0.3 s a page (0.25-0.6); an
  English scan reads the same, 1.19 s against 0.92. A script whose pack is not here is named in `improve`
  (`readpage.py --setup --ocr-langs eng+hin`). Measured on 94 synthetic scans in 24 languages, 16 Chinese, Japanese and
  Korean ones with English words in them and 27 real ones (references/engines.md). `READ_PAGE_OCR_LANGS` still decides
  when the user sets it: the environment no longer sets it from its packs. An environment set up before reads as it
  did until the next `--setup`.
- **Speech recognition for a video without captions was measured and left out** (KNOWN-ISSUES 15, by design): where an automatic track exists Whisper small is not better than it (WER 8.9 against 10.9 % over 43 clips), and it would add 287-345 MB to `--setup` and minutes of CPU an hour of speech.
- **No source in plain http, for any part** (KNOWN-ISSUES 210). An http index (`UV_DEFAULT_INDEX`, `UV_INDEX_URL`,
  `PIP_INDEX_URL`, pip's own `index-url`, an entry of `UV_EXTRA_INDEX_URL`, `UV_INDEX` or `UV_FIND_LINKS`), npm's
  registry (the environment's or an `.npmrc`'s, a scope's too), Playwright's download host and uv's list of Pythons
  were used as they were - for yt-dlp, the browser and the hashes our Python is checked against, which no other
  hash protects - while only Node's mirror and the OCR data's, pinned anyway, had to be https. Each is left out now and
  the default used (registry.npmjs.org in npm's case; a `UV_CONFIG_FILE` that names one is not read), the background
  yt-dlp update too, and the log says why; pip, the uv fallback, runs `--isolated`. A loopback address stays usable;
  `READ_PAGE_ALLOW_HTTP=<host>` lets a company's intranet mirror through, and every line that uses it says it goes in
  plain http.
- **The lock's hashes decide the set of packages, whatever a settings file says** (KNOWN-ISSUES 211): the install
  runs with `--require-hashes` (an index whose metadata file named one more package got it installed, unhashed - now
  refused), the one-at-a-time fallback by each top package's pin under the same flag, yt-dlp's with `--verify-hashes`;
  a `UV_CONFIG_FILE` with `verify-hashes = false` no longer lets a wrong hash in, and its keys are named in the log.
- **`UV_LINK_MODE=symlink` is not passed on** (KNOWN-ISSUES 212): the environment's files were links into uv's cache,
  which `--setup` then cleaned, 7 962 of them, after a check that passed; hard links are used, and an environment such a
  run left is built anew.
- **An address shows as its scheme, host and port** (KNOWN-ISSUES 213) in the setup's log, `setup.json` and the
  report: a password with an `@` or a `/` in it, a token in a path (Gemfury, Cloudsmith) or a query showed whole.
- **Every download is held to a hash but yt-dlp's and the browser's** (KNOWN-ISSUES 214): every OCR pack of
  tessdata_fast 4.1.0 by its SHA256 (`scripts/tessdata-lock.txt`, 125 packs: any pack beyond `eng` and `rus` was kept
  by its size), PyPI's Node for musl by the SHA256 of its wheels, defuddle and its 26 packages by `npm ci` of
  `scripts/defuddle-lock.json` (each tarball by its SHA512, the same tree as before; `tools/setup_lock.py --npm` and
  `--tessdata` write the two). README names what has none: yt-dlp with the five packages that float with it, and the
  browser.
- **OCR packs named once stay named** (KNOWN-ISSUES 215): the next plain `--setup` dropped them, and reads went back to
  English. `readpage.py --setup --ocr-langs eng+jpn` names them in any shell (the fix line was a POSIX `VAR=x cmd`);
  `READ_PAGE_LANG` decides the packs `--setup` fetches, as it does a read's.
- Smaller findings of the same review (KNOWN-ISSUES 216): a Windows home outside the profile (`C:\read-page`), which
  every signed-in user could modify, is made the user's alone; the environment's bytecode folder on a mount with no
  Unix modes gives way to the temp folder's (reads had none, 0.25 s more each); `tidy()` sees a process that names the
  environment by another path to it; npm's tarball falls back to registry.npmjs.org (a registry that wants a token
  ended the step); pip's configuration is read in pip's order; the `--setup` command compiles nothing into the temp
  folder; README, engines.md and this log say what the code does.
- **The CI tools refuse to change a machine outside CI, and undo what they did** (KNOWN-ISSUES 217):
  `tools/ci_proxy.py` left mitmproxy's root trusted system-wide with its key in a fixed temp folder; `stop` now takes
  the certificate out by its SHA-1 and deletes the CA, its state is a folder of its own, and mitmdump ends when
  trusting fails. `tools/ci_acp.py` patched Git's curl and the environment's Python in place and left a patched copy
  beside an installed Python, its manifest replaced whole; it patches copies in a folder of the job's own now,
  keeps a manifest's own content (`longPathAware`, `supportedOS`) beside the code page, and `restore` undoes
  `env-python`. `tools/ci_container.sh` runs in a container alone. Each, off GitHub Actions, only with
  `--on-this-machine`.
- tests: `environment.py` 217 (175 before); the checks of a source in plain http, of the lock's set against a local
  index with the real uv, of the pins against GitHub's listing, PyPI and the npm registry, and of the CI tools'
  refusals with nothing of the machine in their reach. It leaves no folder in the temp folder any more (on Windows a
  folder with a log the suite still held open stayed, some 20 a run), and the check of a --setup that waits for a
  yt-dlp update holds the update until the work is seen waiting (a fixed 4 s was a race on a loaded machine: the
  command, its launcher and its worker are three Python starts, 3.3-3.9 s measured, up to 16 s under load).

- **A video's subtitles in any text format, in the speaker's own language, a dub named, and a failure said**
  (KNOWN-ISSUES 218-223; measured on a census of 222 public videos - 199 whose info could be read - run through the
  code before and after with a stand-in for yt-dlp, four users, 796 answers, and 41 of them read for real: none is
  worse). Main carries one file more (`scripts/subtitles.py`; with the installer's two locks, 35 files).
  - **RuTube's subtitles come as SRT** and the answer said `no subtitles`: yt-dlp is asked for `--sub-format
    vtt/srt/best`, and `scripts/subtitles.py` turns SRT, SBV, TTML, DFXP, YouTube's srv1-3 and json3, ASS and LRC into the
    same WEBVTT cues, so the blocks and `transcript.vtt` do not depend on the site. 13 of 13 RuTube videos that
    have a track read for real (2 100 to 17 400 words); a track whose own name says automatic (`Русский • Авто`) is named so.
    A site's track is read up to 16 MB, in linear time: a TTML or srv1-3 file of paragraphs that no `</p>` closes was
    scanned to its end from each of them (8 000 took 5.4 s, 32 000 would take about 90; now 0.002 and 0.008 s).
  - **YouTube refuses its machine translations with HTTP 429, and yt-dlp then stopped with nothing written** - found
    by this measurement, not asked for: the user's `en` is a translation for any video not in English, so 16 of the 41
    videos an English reader read for real were `no subtitles`, 5 of 6 for a Chinese reader. The call carries
    `--ignore-errors`: the refused track is a warning, the others and the info arrive. Where YouTube refuses, 470 of
    796 answers were "no subtitles" and are the recognition now, 44 a human track, 22 a dub's speech.
  - **A dub's recognition is named a dub's**: the speaker's language is the audio marked original, not yt-dlp's
    `language` (the default audio, the dub's for 60 of the 163 YouTube videos); the answer says `subtitles en, automatic,
    of a dub (original audio zh-Hant)`, and the speaker's own track, human or recognition, is read before it - 22 videos
    (88 answers) were a dub's text where the speaker's own was there (`ar-orig`, the Arabic dub of an English talk). One
    video whose original audio YouTube takes for English while it is Russian is named a dub's too, the text right.
  - **The human track in the speaker's language** is asked for once more when the first call brought only a machine's
    text: an English reader of a Russian or German talk with human subtitles read the recognition. 4-13 s more, the
    answer names the track (`subtitles ru`); a broadcaster's several caption tracks of a language (`en-uYU-mmqFLq8`,
    15 s each), the live chat replay and Bilibili's comments are not taken for subtitles.
  - **A video that has not premiered, a refused request or any other yt-dlp error** said `no subtitles in en (set
    READ_PAGE_SUB_LANGS to change)`: yt-dlp's last error line decides now - `advice: the video has not started yet (This
    live event will begin in 38 days.): ... read it again after that, with --refresh`, `try again in a few minutes`, `yt-dlp
    stopped with: Private video ...`; a read that ran out of time says `read it again, with --refresh`.
  - **A media file cut in transit** (the connection broke, the server stopped sending, the time ran out) was
    `media_only` with a short file and no advice: it is `error` or, while it was still arriving, `too_large`, says how much
    arrived and names `--download`; what arrived is not kept (a cut DASH file plays only as a stream).
  - Not changed: `.*-orig` still asks every track of a many-dub video (14 of 163): 13-19 s a read. The 403 before a
    stream address's `available_at` is not met - only subtitles are asked. `tests/reading.py` (+32 checks: a stand-in
    for yt-dlp that has the tracks a site lists, in the formats it has, and refuses translations as YouTube does) and
    `tests/timeouts.py` (+3); `references/video.md` has the numbers.
- **YouTube's automatic subtitles reach the agent once, not three times** (KNOWN-ISSUES 224). Its automatic VTT rolls: a
  cue holds the line before it and the new line (whose words carry their times), and a cue of 10 ms shows the new line
  alone, so every phrase stood in three cues and `vtt_to_text()`, which dropped only a cue equal to the one before it,
  handed over about three times the words (a one-hour talk of 8 800 words as 26 400, a three-row track five times).
  `subtitles.rolled_cues()` reads such a track line by line: the bottom row of a cue is the new line, a row above it
  that is the line the screen showed last is carried and left out, so a line the speaker says twice stands twice, and
  a caption row of digits alone (`100`), where the cue reader stopped, is a line. A track is told by its word times
  plus a carried row, so a person's track - a roll-up one too - reads as it did. The blocks start at a pause of 2 s
  counted from when the line before was last spoken (a line is shown until the next one comes: the cues have no
  gaps, and a block began at nearly every line, 9.5 words of speech each; 59 now), still at most 30 s.
  `transcript.vtt` holds one cue per line, the time the line came in and the cue's end (the file yt-dlp wrote, with
  the word times, stays beside it as
  `video.<lang>.vtt`). Measured on the real subtitle files of 125 videos (309 files): 86 videos have a track in that
  form; 77 of them read 979 577 -> 329 790 words (x2.97; x2.63-x3.00 apiece, x4.91 for the three-row one) and the 9
  Japanese ones 286 873 -> 104 421 characters; the 48 clips of the measurement 515 460 -> 174 016 words and
  18 311 -> 2 961 blocks (Japanese apart). Each of the 169 automatic files in that form has every line of the track
  once and nothing lost: the measurement's own rule, "a line equal to one of the last three is a repeat", drops 348
  lines that are said again, which are kept. The 14 "automatic" files that are a person's text, the 25 RuTube tracks
  and 99 of the 101 human tracks read byte for byte as before; the other 2 are broadcasters' live captions
  (`es-uYU-mmqFLq8`, `pt-uYU-mmqFLq8`) in YouTube's rolling form, and read once. The largest real track, four times
  over (6.5 MB), reads in 0.3 s, 15 s before. `tests/reading.py` (+6 checks: a rolling track built as YouTube
  writes it, with a line said twice, a line of digits, a pause, two and three rows).
- **Sign-in, subscription and "not found" words in twenty languages, a soft 404 judged on the final page, and a
  paywall named** (KNOWN-ISSUES 13, 191-193). The wall words covered twenty languages; the login and not-found
  words covered seven. `LOGIN_PHRASES` (a wall's sentence: "sign in to continue", "for subscribers only", "войдите,
  чтобы", "请登录后", "会員限定"), `LOGIN_HINTS` (the words of a sign-in form) and `NOTFOUND_PHRASES` (a 404
  template's sentence: 页面不存在, 找不到页面, 您访问的页面不存在, 404 页面, ページが見つかりません, 페이지를 찾을 수
  없습니다, الصفحة غير موجودة ...) cover en, ru, uk, de, fr, es, pt, it, nl, pl, cs, tr, sv, ja, zh, ko, ar, hi, id and vi,
  matched as the wall words are (case, accents and marks folded). Three rules use them: a password field with a sign-in
  word on a page of up to 120 words is `login_required` (the rule stopped at 40: Facebook's form is 55-66 words,
  Instagram's 40-48, GitHub's 76), a wall's sentence on a page under 80 words is too (as before, in more languages), and a
  404 template's sentence in the title, the heading or the first 300 characters of a page up to 200 words is `not_found`
  (it was under 40 words, and judged on the server's text before the browser ran: Kinopoisk's, Tencent's, 36Kr's and
  Almasry Alyoum's missing pages read `ok`). Chinese and Japanese count two characters a word in these rules
  (`login_words`): a long article that quotes 登录 no longer reads "login mentioned". Measured on 1 368 real pages in
  20 languages, the same URLs read before and after: 187 sign-in probes `login_required` 61 -> 92, 5 of the 25 missing
  addresses that read `ok` are `not_found`, the wording of real 404 pages is recognised on 143 of 186 (88), a marker
  changed no answer of 685 ordinary pages (89 of them under 80 words); the per-language counts and what was left out
  (a title with a sign-in word, container classes, `LOGIN_URL`) are in row 13 and row 191.
- **A paywall in JavaScript is named** (KNOWN-ISSUES 13). A page whose HTML carries the article and whose script covers
  it says so in schema.org's words: `isAccessibleForFree: false` on a creative work in the JSON-LD (an `@graph` too) or
  in microdata, and `hasPart` with the `cssSelector` of the hidden part. The answer stays `ok` - the text is there and
  may be cut - and carries `signals.paywall` (with the selector) and an advice that says the page is paywalled and the
  skill cannot subscribe. 87 of 285 articles of paywalled publishers (Washington Post, Financial Times,
  The Atlantic, Business Insider, Le Monde, Le Figaro, Mediapart, NZZ, Handelsblatt, DN, Repubblica, Nikkei ...) and 4 of
  165 free-news pages carry it, none of 520 Wikipedia and Wiktionary pages; an Event's `isAccessibleForFree: false` is a
  ticket, not a paywall, and the markup printed in a `<pre>` is not the page's. A container's class is no signal: it
  fired on 49 pages with no marker, among them 3 free news pages.
- **An archive cut, damaged or no ZIP** (KNOWN-ISSUES 167) was answered "no converter for this file type",
  after a machine's markitdown had spent its 4 s on it. A cut or damaged archive is read member by member from
  the members' own headers (`zip_whole`, `zip_salvage`), the whole ones read as the archive would be: a DOCX
  cut in its picture reads its whole text, a plain ZIP lists the members that are not whole with why. An
  office file whose members do not all unpack is read from the ones that do (`zip_mend`: python-docx gave up
  on a picture with a bad CRC). `signals.broken_archive` says how, how many members were found and whole, and
  which are not; under 40 words is `error`, more is `ok`, and the advice says what of it was read and what gets
  the rest: a whole copy of a local file, `--refresh` for a server's (the same bytes while its copy is cut).
  A file whose name or type says ZIP and whose bytes do not is named: a Word, Excel or PowerPoint 97-2003 file,
  a password-protected Office file, gzip, 7-Zip, a picture, text (its text is the answer). Capped as the
  readers are (32 MB a member, 128 MB in all, 10 000 members - folder entries count - one member in memory at a time): 10 000 members
  in 0.3 s, a member that unpacks to 256 MB in 0.2 s and 98 MB. `zip_text` says under a member's name that it
  does not unpack (one such member ended the listing's reading).
- **What a cut or damaged archive costs is bounded** (KNOWN-ISSUES 199): every byte unpacked to judge its members
  counts, kept or not - members past the size limit and members with a wrong CRC were unpacked to 32 MB each and
  thrown away uncounted, so 2 000 of them (62 MB of file) held a read 58 s and a DOCX of 200 of them 7-12 s. 256 MB
  an archive (`ZIP_WHOLE_SPENT`), then the reason says the rest were not looked at; the read's clock is looked at
  every member, and a member's data is read 64 KB at first: 0.98 s and 1.2 s now.
- **A cut document's words are its own** (KNOWN-ISSUES 200): the 40-word rule of a cut archive and the 5-word
  `empty` counted the skill's markers of the pictures and their list, so a deck whose slides were lost was `ok` on
  60 words of markers; a document of a few words of its own (a DOCX that is one formula) is `ok`, not `empty`.
- **A cut or damaged XLSX or PPTX keeps its whole sheets and slides** (KNOWN-ISSUES 201): they read nothing, the
  workbook's or the presentation's list naming the lost one; what a package lacks of its index - content types,
  root relationships, a workbook's list of sheets, all of which openpyxl writes last - is written from its parts. An
  archive none of whose members unpacks where its table of contents says (a wrong offset in its end record) is read
  from the members' own headers, an EPUB too. The advice says when whole members gave no text.
- **A file cut in its table of contents is cut, its members all there** (KNOWN-ISSUES 202): it was "damaged" and
  wanted "a whole copy for the rest"; `signals.broken_archive.all_members` says every member was looked at. A header
  cut by the file's end is a cut too, a ZIP64 size past the end of the file a cut member (the whole member before
  it was lost), and a header where a deflated member's data ends the next member (a wrong packed size lost them).
- **A document's picture left out is never asked of its server** (KNOWN-ISSUES 203): a tracking pixel, a copy, one
  over the size limit or the archive lacks kept its link, and over HTTP the read asked the document's server for
  `rtf-pict-0003.png`, a name our RTF reader made up. Its link goes, or becomes its picture's marker, or a marker that
  says why (`not in the document`), its address the name inside the document.
- `rtf_images` reads each picture for its own size: a 100 MB buffer cost 17 ms a picture, 17 s at the reader's
  1 000 (KNOWN-ISSUES 204); 3.7 s now through the CLI.
- **An ODS sheet's repeats are capped by their text too** (KNOWN-ISSUES 205): one 64 KB cell repeated in 1 024
  columns and 1 000 rows, 1 KB of file, was 16 GB of text; 32 MB a table, 128 MB a document, then the table is cut.
- **ZIP names read in the code page their reading makes names of** (KNOWN-ISSUES 206): Shift-JIS names were CP437 to
  the rule for accented letters, on a Japanese machine too (データ.csv was "âfü[â^.csv"), Russian and Greek ones
  that Windows' own zipper writes in its OEM code page (CP866, CP737) were mojibake or Korean, and a GBK name that
  happens to decode as UTF-8 was read so. Shift-JIS of kana and kanji with no character glued to a Latin letter,
  the machine's OEM code page (GetOEMCP), CP866's and CP737's words now have their turn; a name is cut at a NUL and
  has "/" for a backslash. 1 458 of 1 536 names right under eight machines' code pages (703 of 960 under five).
- Smaller findings (KNOWN-ISSUES 207): a DOCX's formulas and text inside a hyperlink, an insertion, a smart tag or a
  field are read; a DOCX whose XML breaks names python-docx and its error, not "no converter (pymupdf)"; an n-ary
  operator's long body is not searched at every level; the readers' process says when its memory limit was refused
  (`memory=not held` in the trace) and "it ran out of memory"; an RTF floating shape's alt text; the copies of a cut
  archive's whole members go once read; the archive's background read keeps its own word on a broken archive; a
  reader's remarks are `signals.document_note` and the answer's `document:` line, not `missing: converter`; the
  schema has `images[].line`, and an answer with no text needs no `content.engine`.
- **An archive cut in transit is read** (KNOWN-ISSUES 208) from the members that arrived whole, as a cut archive is:
  it was `too_large` or `error` with nothing read. Its advice says the transfer was cut: `--refresh`, `--download`.
- GPT-3's Table H.1 holds two of the models' columns in one cell of the layout model's grid (KNOWN-ISSUES 209):
  filed, not fixed - a split would be measured on the corpus first.
- The "documents" gap (install pymupdf) is a PDF's alone (KNOWN-ISSUES 177): it was named for an EPUB or ODT
  read on a machine without pymupdf, pdftotext or markitdown, which our readers read with the standard library.
  A DOCX, XLSX or PPTX whose library does not import names that library instead.
- **ZIP member names in a code page** (KNOWN-ISSUES 178, seen on Windows set to Chinese): a name with no UTF-8
  flag was read as CP437, so Windows' own zipper's GBK names came out as "╦╡├≈.txt", an EPUB named in GBK lost
  its chapters, and a Shift-JIS 表 lost its backslash byte to a "/". A name whose CP437 reading is no name is
  read as UTF-8 when it is, else in the CJK code page that decodes the archive's names into its script (the
  one reading that is plainly the common characters of its script, else the machine's own; kana for Shift-JIS, GB2312's characters for GBK, Big5, Hangul); ASCII and CP437 names of
  accented letters stay (`docreaders.fix_zip_names`).
- The marker patterns of the answer (`pictures.MARK`) and of the MCP server (`ANY_MARKER`) were quadratic on a
  run of `[img #N · ` that no `]` closes (KNOWN-ISSUES 179): 16 000 in a line took 43.7 s, now 1.4 ms.
- **ODS and ODP are our readers'** (KNOWN-ISSUES 180), in their process of its own with its clock, kill and caps,
  as ODT is: they were paragraphs in order (`odf_text`, the read's own process). A sheet is `## its name` and its
  table, rows and cells repeated as the sheet says within the grid's caps; a slide is `## Slide N`, its frames'
  text, lists, tables and pictures, then `notes:`. On LibreOffice-shaped files: 678 table rows of a workbook (0
  before), its repeated rows, a deck's 12 slides, 10 table rows, 3 pictures and notes. `odf_text` is gone; the
  plain reader is what is left when the reader breaks. A table in a frame is read in an ODT too.
- **A DOCX's formulas** (KNOWN-ISSUES 165): python-docx's paragraphs hold no OMML, so a DOCX's formulas were
  lost, and one of formulas alone read as nothing. Each formula is now one line in backticks where it stands
  (`docreaders.omml_text`), as an ODT's MathML is: `(a+b)/(c−d)`, `e^(−x^2)`, `√(x+1)`, `root(3, x)`,
  `∑_(i=1)^n x_i`, a matrix by its rows `[a, b; c, d]`, `x̂`, `lim_(n→∞) a_n` - in a paragraph, a table cell, a text
  box or a paragraph of its own. On 120 formulas pandoc's OMML writer made and 16 written as Word writes them:
  all present (none before), every construct and character kept; the lines are 42 % of pandoc's TeX of them.
- **An RTF's pictures** (KNOWN-ISSUES 166): a PNG or a JPEG of an RTF - inline, Word's `\*\shppict`, a floating
  shape's - is in `img/` with its marker where it stood, its alt text Word's; Word's WMF copy of it is passed over,
  and a picture in a format no browser or model shows (WMF, EMF, PICT) is named where it stands. Written by our
  reader in its process, under its caps (1 000 pictures, 32 MB each, 128 MB in all).
- **A PDF's table: two rows of the page in one row of the model's grid are two rows again** (KNOWN-ISSUES 127):
  GPT-3's "LAMBADA LAMBADA | acc ppl | 68.0 8.63" and "Correct Answer → Incorrect Answer →" beside both
  answers. A grid row is split where one cell's lines are items of one kind (numbers, or one last or first
  word) and the other cells' lines start beside them; never the header row (`pdftables.split_rows`). On the
  corpus with no time limit: truth rows whose first three cells start a table row 876 -> 892 of 1 051, rows whole
  and as table rows unchanged, no other document changed; the rule tried before lost 2 whole rows.
- **The readers' process has a memory limit on Windows** (KNOWN-ISSUES 181): a Job Object's process memory limit
  of 2 GB, which the process sets on itself (ctypes), as RLIMIT_AS holds it on Linux: an allocation past it is a
  MemoryError. Its start costs 11 ms more (143 -> 154 ms median of 20 under the environment's Python), ctypes'
  import most of it. macOS keeps none: its kernel does not hold to RLIMIT_AS, and no process can put itself in a
  job or a cgroup there.
- CI: the repository is public, so `macos.yml` runs on every push to dev, as `tests.yml` does.
- **The installer's open rows** (KNOWN-ISSUES 142-145, 151):
  - Sources: every setting that sends an installer elsewhere than its default or skips a check - uv's index,
    find-links, mirror and insecure-host variables, `PIP_INDEX_URL`, `NODEJS_ORG_MIRROR`, npm's registry and TLS
    settings (environment and `~/.npmrc`), pip's configuration, Playwright's download host, extra CA files,
    `NODE_TLS_REJECT_UNAUTHORIZED=0` - is named at the top of the setup's log and in the setup report, with its
    value (credentials of an address left out); the step lines say where they fetched from. A plain-`http://`
    mirror for Node is not used. uv runs with `UV_NO_CONFIG=1` (measured: a `uv.toml` in a parent of the folder
    redirected the install; the environment's variables and `UV_CONFIG_FILE` still work); a `uv.toml` that names an
    index is listed as not read, with the variable to use. `UV_NO_VERIFY_HASHES` is not passed on.
  - The check: `setup-check.json` is removed first; a check that wrote nothing is "did not finish", a problem with a
    fix; a failed step says `FAILED:` on its line.
  - `tidy()` sees an environment in use on POSIX (arguments of the processes in `/proc` on Linux, `ps` on macOS):
    an MCP server under an older environment keeps it across pin moves.
  - uv's cache: an update cleans the packages whose pin moved before it installs, a yt-dlp update cleans yt-dlp,
    a cache with more than 150 MB in no environment (or an older environment whose lock was not kept) is pruned
    whole; its size and what of it is in no environment are in the closing line and the report. Plain
    `uv cache prune` removes nothing here (measured). On macOS uv runs with `UV_LINK_MODE=hardlink` (its default,
    a clone, left the cache costing 0.5 GB on a runner).
  - Files outside the folder: `NODE_COMPILE_CACHE`, the Python bytecode of a read in the environment and the
    environment's yt-dlp cache are in the folder (`cache/`); a read's start is as fast (0.441 -> 0.434 s).
- **Node from Playwright's wheel** (KNOWN-ISSUES 171): defuddle and yt-dlp's JavaScript run on the Node that the
  Playwright wheel carries in its driver (24.21.0; already in the environment), so nodejs.org's archive is not
  downloaded - 36 MB on Windows x64, 56 on Linux, 51-52 on macOS - nor kept (90-190 MB on disk). That Node has no
  npm: npm 11.19.1 is fetched from the registry's tarball (3 MB) and held to the SHA512 pinned in `envsetup.py`.
  nodejs.org's Node (SHA256 pinned) and PyPI's wheel stay as the fallback for musl, which has no Playwright wheel,
  and for a wheel that lacks its Node. defuddle's Markdown is byte for byte the same as under nodejs.org's 24.22.3
  on six pages (`example.com`, Wikipedia, Python's tutorial, MDN, SQLite, RFC 9110).
- **Mirrors and OCR languages for a user in mainland China** (KNOWN-ISSUES 172, 173): pip's own configuration
  (`pip.ini`, `pip.conf`) is read for its `index-url` when no variable names an index; `READ_PAGE_TESSDATA_URL`
  names a mirror for the OCR data (https, a folder or a template with `{lang}`); every mirror variable is named in
  the docs and in the setup's log and report. `--setup` fetches English and the packs of the user's own languages
  (Windows' display languages, its user locale only when there are none; elsewhere `LANG` and the others in the
  user's list: `LANGUAGE`, a Mac's AppleLanguages; at most three: zh-CN `chi_sim`, zh-TW `chi_tra`, ja `jpn`, ko
  `kor`, ru `rus`, ...) instead of English and Russian for everyone, and a read in the environment reads with them
  beside English.
- **CI for what was not yet checked** (KNOWN-ISSUES 174-176): `install.yml` also runs `--setup` in Debian 11 and
  Ubuntu 20.04 (glibc 2.31), Rocky Linux 8 (glibc 2.28), Fedora, Arch and openSUSE containers; behind a TLS-inspecting
  proxy (mitmproxy, its root in the OS's store only) on Linux, Windows and macOS; on a Windows whose Python and Git's
  curl have the ANSI code page of zh-CN (936) or zh-TW (950) through an application manifest (asserted), in a profile
  named in Chinese with a space, with files named and written in Chinese; the suites under `LC_ALL=zh_CN.GBK` on Linux;
  and README's ZIP. They found a floor with no fix (Ubuntu 20.04 and Debian 11: Playwright has no browser for them -
  the report now names the machine's own Chromium), and that behind such a proxy a read carries on after an
  unverified retry (row 176). The tests no longer assume an ASCII temp folder or a UTF-8 console (`text=True`
  without an encoding), and two timing bounds allow a slow runner.
- **CI: real installs** (`.github/workflows/install.yml`, on dev and ci-install pushes and by hand; the helper
  is `tools/ci_install.py`). Every standard runner a public repository gets free: `--setup` from nothing into
  a folder with a space and Cyrillic in its path on Linux, Windows and macOS (x64 and arm64) - its time, the
  bytes that came in, the disk it took, every step and engine checked, reads (a local file, a public page, a
  scanned PDF through OCR), the offline suites and the browser suite under the environment's own Python,
  then `--setup` again (nothing to fetch, so quick); a user's own install by README's commands (the public
  repository cloned into the skills folder, `--setup`, a read: main, and the pushed commit); a bare Python
  with no `--setup`; Alpine and a bare Ubuntu with Python and git only. What a platform lacks for want of
  wheels or system libraries is a floor listed in its matrix row: an unlisted gap turns the job red, and every
  gap must be named with a reason and a fix.
- CI: the first runs on the public repository were red for three reasons, none in the skill's reading:
  `tests/formats.py` timed a slow page with the real layout model, which a runner lays out in 2 s (the stand-in
  is slow now, the same everywhere); the compiled-module checks of `tests/environment.py` looked at what is
  beside the scripts, where earlier suites leave a `__pycache__` (they look at what the code under test
  changes; the workflows set `PYTHONDONTWRITEBYTECODE`); and `envsetup.unpack` without tar filters made a link
  with "/" in its target, which a Windows link does not resolve, so Node's own `bin/npm` looked to lead out of the
  folder (made with the OS's separators; the check asks what `os.symlink` is given, which needs no right to
  make links); and on the slowest runner (macOS Intel) an archive that stalls took 22.7 s against a check of
  22 (it allows 26).
- **OCR under a home with letters outside ASCII, on a volume that makes no short names** (a GitHub Windows
  runner's `D:`, a dev drive): the real install there reproduced what the fix for OCR under such a path had fixed only where
  Windows makes an 8.3 name - `--setup` said "set READ_PAGE_HOME to an ASCII-only path", and every scan read
  `empty`. The data folder's own name, which is ASCII, is now given to tesserocr from its parent, with the working
  directory moved there while tesseract starts (`ownenv.tess_dir`; it reads its data at the start; measured on
  code page 1252 against a Cyrillic folder: the absolute path fails, the relative one reads). Only a data folder
  whose own name is outside ASCII still needs an ASCII `READ_PAGE_HOME`.
- `--setup` on a machine with no build of a package (Alpine, Windows on ARM): the reason is whole ("pymupdf4llm
  has no build for musl Linux on x64"), the fix is what a user can do - the machine's own program for OCR
  and PDF text, else a plain "none here" with what still reads - not `readpage.py --setup`, which cannot
  give it; an engine is named once (the browser step and the check no longer repeat it); the package manager is
  the machine's (apk, dnf, zypper, pacman, apt, by its os-release; no `sudo` for root, which a container does not
  have); the note for Node on musl says nodejs.org has no build for it.

**Chinese, Japanese, Korean and Russian on any machine** (`scripts/intl.py`, `tests/cjk.py`: found by running the
skill under a real code page 936 - a copy of `python.exe` whose manifest says `<activeCodePage>zh-CN</activeCodePage>`
has it for its process - with the profile, the temp folder and the cache in Chinese; every offline suite was green
while the rows below stood)
- **Text in GBK or Big5 is read right, and a guess says so.** A page, a text file or a CSV that names no encoding
  was read as Cyrillic (`╧ЗнЯт╨╥╒╡╪вНпбм╗ж╙`) with status `ok` on a machine without `charset_normalizer` - the standard-library
  core before `--setup`; with it, 10 to 20 characters of GBK came back as cp949, cp932 or cp1006. Now each of
  GB18030, Big5-HKSCS, Shift_JIS, EUC-JP, EUC-KR, windows-1251 and KOI8-R reads the bytes and the one whose non-ASCII
  characters are most often the common ones of its script wins (ideographs alone cannot tell GBK from Big5: both
  decode every pair of bytes into ideographs); ties go to the machine's ANSI code page or language. A declared
  `gb2312`, `gbk`, `big5`, `shift_jis` or `euc-kr` is read as a browser does (gb18030, Big5-HKSCS, Windows-31J,
  Windows-949), so one character outside GB2312 no longer drops a page to the guess; a UTF-8 page cut in the middle
  of a character stays UTF-8; German with no charset is windows-1252, not Cyrillic. A declared double-byte label
  is set aside only when another reading is clearly better: a true gb2312 over rare characters (a periodic table,
  the provinces' one-character names) is kept. A reading by guess is `signals.charset_guess` (with `(doubtful)` for
  fewer than six non-ASCII characters, two readings alike, or a reading that fits no language well) and `charset
  gb18030 (guessed)` in the answer's first line; it no longer takes the `advice` line, which is for what an agent
  can do. A document's own XML part (EPUB, ODT) that says gb2312 is read the same way (it was U+FFFD throughout
  for one character outside GB2312).
- **Greek, Hebrew, Thai and Ukrainian are not read as Cyrillic.** The bytes of every single-byte script are letters
  in windows-1251 and KOI8, and the first guess took them: Greek and Hebrew came out in the Cyrillic alphabet,
  Thai and Ukrainian's KOI8-U in KOI8's box drawing - with `charset_normalizer` installed too, which was asked only
  after the guess. A Cyrillic reading now passes the letters' frequencies, their case and words with vowels and no
  box drawing; KOI8-U is a candidate; with charset_normalizer the double-byte guess still wins over it, and it reads
  the other single-byte scripts. On Wikipedia prose in ten languages' old code pages, no charset said (42 cases):
  with charset_normalizer 30 right (21; 0.4.6 also 30) and 3 wrong with no doubt said (13), without it 9 right (6)
  and none wrong in silence (9); Chinese, Japanese, Korean, Russian and Bulgarian as they were.
- **The MCP server reads its standard input as UTF-8** whatever the locale, a BOM before the first line dropped. It
  used the locale's code page unless Python started with `-X utf8`, which a client's config is written without: on a
  Chinese Windows a Chinese URL or folder arrived as other characters.
- **A raw non-ASCII address becomes a URI**, as a browser asks for it (host to punycode, the rest percent-encoded as
  UTF-8, a tab or a line break left out, a backslash before the query a slash, `"<>` escaped) at curl_cffi, curl,
  urllib, a picture and the archive's snapshot. Every picture whose `src` had Chinese in it was `not downloaded: ordinal
  not in range(128)`; Git's curl and older Windows curls sent the path in GBK (`%d2%b3%c3%e6`). A host goes out as a
  browser's name for it: UTS 46 non-transitional with its bidi and joiner rules, in the standard library - the
  standard library's own IDNA 2003 sent `faß.de` to `fass.de`, another site, `σοφός` without its final sigma, and
  let through a ZWJ between Latin letters; of 41 hosts tried, 40 now get Chrome's `new URL()` name (the 41st, with an
  ideographic space, Chrome makes `a%20b.com`; it is refused). The cookie jar and a page's cache folder go by that
  name: a cookie an IDN site set for its punycode never went back to it. A redirect's
  Location goes on as the bytes it came in, as a browser's does, on every channel: UTF-8 as its own escapes, any
  other byte percent-encoded as it is (`/caf\xe9` -> `/caf%E9`, a GBK path stays GBK; `intl.location`). Re-read by
  a guess, a raw UTF-8 `/café` had gone out as `/caf%D0%B9` - a Cyrillic path, `not_found`; curl's own
  `redirect_url` wrote the escapes in lower case.
- **The network rule checks the name the request goes to.** A host written with percent-escapes (`127.0.0.%32`,
  `%31%32%37.0.0.2`, `127.0.0.2%2e`), which curl, libcurl and urllib all decode, resolved to nothing and counted as
  public; so did a name outside ASCII that Python's IDNA 2003 refuses (a right-to-left label that ends in a digit,
  `שלום1`), whose lookup raised while the request went to its punycode. A public page that redirected there, or
  showed a picture from there, made the reader ask the loopback interface, and the answer was read (`ok`). The rule
  now looks at the host of the address as it is sent (`intl.host_ascii`: escapes decoded, punycode), the request -
  a picture's redirect too - sends that same name, and a host with no such name, or one Python cannot look up, is
  refused.
- **A server's Chinese file name is kept** (`filename*=UTF-8''...`, raw UTF-8 or GBK bytes, `filename*=GBK''...`):
  it was `-.png`. The header is read once, from its bytes (a right `été.pdf` had become `йtй.pdf`), and a
  Windows device's name (`CON.png`, `COM1.pdf`, `LPT².png`) gets `file-` before it.
- **OCR asks for the pack of the text's script and of the user's language** (`chi_sim` or `chi_tra`, `jpn`, `kor`,
  `rus`; the user's own unless `READ_PAGE_OCR_LANGS` is set) when it is installed, and names a missing one in
  `improve` with the command that fetches it (`readpage.py --setup --ocr-langs eng+jpn`: a flag since 2026-11-22;
  `signals.ocr_missing_langs`; on the `ocr:` line of `--ocr N`). Kana counts as Japanese when it is a real part of the
  text (five の on a Chinese shop's page made it Japanese), and so do kanji in Japan's own forms (経, 発, 駅: a
  headline of kanji alone was Chinese). tesserocr reads a page by its path when it can open it: given as a
  picture, the page lost its 150 dpi (tesseract took 70).
- **pdftotext, tesseract's command and lynx are given ASCII paths** on Windows (the file linked - copied when it is
  read-only - into an ASCII folder of the user's own: under the cache, its 8.3 name, or with Python 3.13 and later
  the environment's folder when its path is ASCII, each stage folder the user's alone; never a folder other users
  read; the output moved back); a stage a killed read left is removed after an hour. A profile named in Chinese or
  Cyrillic - or in Big5, a name with 許, 功 or 蓋, whose second byte is 0x5C - made them fail or read nothing. A
  Python program the skill runs (yt-dlp, markitdown) is given `PYTHONUTF8=1`: its output, read as UTF-8, was in
  the ANSI code page. A PDF table's caption in Chinese, Japanese or Korean (`表 3`, `表3`, `표 2`) stays text where
  it stood, as `Table 3` does.
- **English defaults follow the user.** `READ_PAGE_LANG` (else the system's languages - on Windows its display
  languages, not the regional format, which made an English Windows with German formats ask for German; `zh_TW.UTF-8`
  is Taiwan's Chinese, not Simplified - then English) sets `Accept-Language` on curl_cffi, curl and urllib (curl
  and urllib sent none), the browser's locale (it was `en-US`; Chromium sends its one tag as the header), and the
  subtitle tracks (they were `en,ru`: a Chinese video said `no subtitles in en,ru`; now `zh-Hans,zh-CN,zh,en` and the
  track the video speaks in, and a video with none of them is asked once for the language its info names). The
  track read is a human one in the user's languages, then the words as spoken; YouTube's machine translation of a
  video, which it offers in every language and which a Chinese or Russian reader of an English talk was handed,
  only when there is nothing else, named so on the answer's first line (`content.track`). `READ_PAGE_SUB_LANGS` and
  `READ_PAGE_OCR_LANGS`, when set, win. What is sent: `references/engines.md`.
- tests: `cjk.py` 182 (175 off Windows, 147 on Windows without curl_cffi and charset_normalizer; offline, any OS;
  its folders are named in Chinese under every locale since row 175); `security.py` 53 (49 on Windows).

**`readpage.py --setup`**
- **one command installs every engine** into the skill's own environment, one folder of the user's
  (`.read-page` in the home folder on Windows, `~/Library/Application Support/read-page`,
  `$XDG_DATA_HOME` or `~/.local/share/read-page`; `READ_PAGE_HOME` moves it), never the skill's
  folder: no questions (running it is the consent), no admin rights, the same pinned versions
  everywhere - uv 0.13.9, CPython 3.13.18 (python-build-standalone), the 54 packages of
  `scripts/setup-lock.txt` (curl_cffi, trafilatura, readability, html2text, PyMuPDF and
  pymupdf4llm, youtube-transcript-api, Playwright, tesserocr with tesseract 5.5.4, Pillow,
  psutil, the Office readers; pandoc 3.9 in pypandoc_binary until 2026-11-21, below), yt-dlp
  (alone not pinned, below), Node (since 2026-11-21 the one Playwright's wheel carries; first nodejs.org's
  24.22.3, its SHA256 now pinned in the skill, or nodejs-wheel-binaries from PyPI - both the fallback, above),
  defuddle 0.19.4 through that npm with its own 26 packages (as of one day, `--before`; their lock since
  2026-11-22, above), Playwright's `chromium-headless-shell`, and OCR data from tessdata_fast 4.1.0 (first English
  and Russian for everyone; since 2026-11-21 English and the user's own languages, every pack SHA256 pinned since
  2026-11-22, above). Then every engine is checked on a sample. Its first line names the download (about 360 MB
  on Windows, 390 on Linux, 350 on macOS; 430, 480 and 380 while pandoc and nodejs.org's Node were in it) and what
  it keeps (about 0.9 GB on Windows), or says the folder is up to date. From nothing 65-70 s on
  a 9 MB/s link (~48 of them downloads), an up-to-date check 8 s; the steps side by side were
  built and measured (62/68 s against 68/65, WSL 83 against 79: the branches only shared the link)
  and not kept. (The first run, still with markitdown, took
  1 min 47 s.) What it cannot do it names with this OS's command (OCR on Windows on
  ARM and macOS 14 or older; a bare Linux's browser libraries). The work runs detached and the
  command follows it for 100 s (to the end in a terminal), so a harness's timeout does not stop it;
  a second `--setup` follows the first. Proxies: the machine's own (Windows' setting too) are passed
  to uv, npm and Playwright; `PIP_INDEX_URL` becomes uv's index. Offline: one clear line, nothing
  changed. Deleting the folder uninstalls it.
- **the environment is used by itself**: `readpage.py` and `mcp_server.py` look at it before their
  other imports and go on under its Python (POSIX: exec; Windows: a child on the same console in a
  job that dies with the first process, its exit code and bytes passed through), its programs first
  on PATH; the stdlib core works without it. +0.16 s a read (`--version` 0.18 -> 0.34 s).
  `READ_PAGE_SKIP=env` keeps a run in its own Python; a broken environment is skipped and `--caps`
  says why.
- **on Windows the environment is in the home folder, not AppData** (found 2026-11-19 in agent
  tests): Windows gives a packaged app - Claude's desktop app is one - a private copy of whatever
  its processes write under AppData, so the environment an agent built from inside it did not exist
  for another agent, a terminal or WSL ("not set up", every read in the machine's Python), and a second
  `--setup` elsewhere would have fetched it all again. `.read-page` in the home folder is not
  redirected (checked from WSL and from another agent's session) and is faster to reach from inside such an
  app (a stat 49 us against 372; the hop 0.34 s against 0.40). uv's "Missing expected target
  directory" at the Python step was the same redirection. macOS and Linux keep the OS's folder.
- **yt-dlp is the one engine not pinned** (everything else is pinned and moves with the
  skill; yt-dlp is kept current): `--setup` installs `yt-dlp[default]` in the newest release
  that has been out three days (wheels only, under the lock's constraints; with yt-dlp-ejs), a
  step of its own after the engines. A video read in the environment looks for a newer one every
  three days - in a process of its own that no read waits for (`ytdlp.stamp`;
  `READ_PAGE_SKIP=update` turns it off). The environment's yt-dlp gets the environment's Node for
  YouTube's JavaScript challenges (`--js-runtimes`). The lock has 54 packages (55 with pandoc).
- **`--alternate`, measured** (is the flag called at all, is it worth its engines).
  238 hard pages read the way SKILL.md says, then again with the flag where the advice named it
  and on a sample (72 pages both ways), and 14 headless agent sessions (three weak models) on
  three walls, a thin script-built portal and a PDF
  table. Agents call the flag when the advice names it and almost never otherwise: all 7 sessions
  that met a wall called it at once (9 calls) and 6 went on to `--clear-cookies`; without advice,
  one session of 7. At the 8 walls among those pages it opened nothing (the browser had been at 6
  and met the same wall at the other 2). On pages that read `ok` the browser gave half as much text again or
  more on 7 script-built portals of 72, less on 3, the same on the rest, at 6.8 s against 2.5.
  What changed:
  - a wall's advice no longer names it: `--allow-external` when the readers were not allowed yet,
    `--force-external` when they were not asked, else no flag - "use another source, or see When
    nothing works"; an empty page gets `--alternate` only when the browser has not run, else
    `--screenshots`;
  - a wall's own cookie is no stale session: the `--clear-cookies` hint (on 9 of the 11 walled
    reads) needs cookies an earlier read had stored, and a read that ends `blocked` or
    `login_required` drops the cookies it got there - and puts back the ones it found as they were
    (a wall that re-set the session's own cookie, as a challenge cookie set on every answer does,
    had left the jar with the wall's value until 2026-11-21);
  - a page of under 200 words that carries 40 KB or more of data for its own scripts goes to the
    browser by itself (`shipped_state`; not JSON-LD, which is for search engines - a product page
    of 144 words went to the browser for 3.2 s and the same words): 4 of 168 HTML
    pages, 30, 9 and 5 times the text on three of them (soundcloud 50 -> 1 526 words, aliexpress
    79 -> 818, ivi 163 -> 894, 7-11 s instead of 1-5), the same text on one. An agent on ivi had
    1.9 KB of 15, and gave up;
  - `--alternate` on a scan with a few words of its own (a stamp, a page number) answered `empty`:
    the text layer is now judged first, and pymupdf4llm's Markdown is taken only when it kept half
    of the document's words;
  - SKILL.md says when: a text thinner than its page, not a wall (edited lines, 5 698 -> 5 689
    bytes); its description no longer promises text from an image or audio URL (they are saved
    as files; a video gives its subtitles).
  The flag stays: it is the one way to make the browser read a page
  whose HTTP text passed for complete, and it costs no engine of its own any more - what it
  alone used now works on every PDF read, below.
- **a PDF's tables come as tables, without a flag** (PyMuPDF's own
  finder and other tools were measured first, to see whether a lighter engine does it without
  a loss). PyMuPDF's text has a table one cell a line. Measured on 94 tables of 9 arXiv papers
  whose cells are known (their HTML on ar5iv, 889 rows) and 17 tables printed from HTML (250
  rows), counting the rows that come out as a table row with each cell its own: PyMuPDF's
  `find_tables()` 2 % and 65 % (9 % with `refine`), with tables made of figures; pdfplumber
  0-17 % and 48-65 %, with thousands of rows that are no table; pymupdf4llm without its model
  2 % and 64 %; with its layout model 68 % and 99 %. No lighter tool does it, so the model
  earns its 77-83 MB on every read instead of behind a flag nobody called:
  - the pages that look like they hold a table (a caption line, twelve lines that are one
    number, or eight rulings: 49 % of 398 pages, 94 % of those where the model found one) go
    through the model, and its tables stand as Markdown where the blocks they cover stood; the
    rest of the page is PyMuPDF's text as before. First the cells were the model's own text, and
    a table that would lose a tenth of its blocks' words was not used - which let cut and
    scrambled cells through (below, "the page's own words");
  - the model has 10 s a read; the pages it did not reach are in `signals.tables.left` and in
    the advice, which names `--download` (no time limit: every page that looks like a table)
    with an estimate of its seconds; `READ_PAGE_SKIP=tables` turns the step off; without the
    model `improve` says how many pages look like a table;
  - onnxruntime is held to four threads that do not spin while they wait (`calm_onnx`): as the
    library sets it up a page took 0.23 s on 20 cores but 4.5 s on four slow ones and 1.8 s
    (2.5 at most) on two, with 2.4 s of CPU for 0.3 s of work; now 0.23, 0.51 and 0.32 s. This
    is also why `--alternate` on a PDF measured 0.4-1.8 s a page earlier that day;
  - `--setup`'s report and `--caps` have a line for the model (`pymupdf4llm`);
  - a cell that spans columns comes from the model cut at the grid's lines ("BLEU" over two
    columns as "BL" and "EU", one value under both as "3.3 ·" and "1018"): cells of one line
    are joined where the words on their two sides stand as near as words of one phrase; a
    table whose box runs through a word of the page (an invoice's "Melbourne" as "lbourne") is
    left as text;
  - not `find_tables()` with the model switched on: its cells come out scrambled there (610.01
    as "61001 .", PyMuPDF 1.28.2);
  - two weak models asked for one cell of a table they cannot know by heart (the printed ones):
    one right on 5 of 32 from PyMuPDF's text and 16 with the tables, the other
    3 of 20 and 13 of 21; on the papers, whose numbers are widely quoted, the first 32 of 37
    either way.
- **a PDF's tables: the page's own words, inside the read's deadline** (an independent review
  of 2026-11-20 found the tables above putting wrong text where right text stood, and one page
  holding a read past its deadline; measured on the same corpus - 29 PDFs, 398 pages, 9 papers
  with known cells - with the same scorer, before and after on one machine, the same day):
  - the cells are the page's words: the model gives a table's box and its grid of cells, and
    each cell gets PyMuPDF's whole words of the text blocks the table stands for - each word in
    the cell that holds its centre, else the nearest (by bisection of the grid's lines). The
    model's own cells had a character where more than half of it was inside, so a grid line cut
    a word ("1 Intr | oduction", GPT-3's contents), a row line scattered a header's letters
    ("Cbid CN dl" for "Combined ConvNet models"), points and commas across a line went ("5121"
    for "5.1.2.1", "$32200"), and the tenth of words a table could lose let them through: on
    the corpus 187 words of PyMuPDF's text missing and 277 added, now 0 and 0;
  - a block is the table's when half its words' centres are inside its box (not its box's
    centre: a block 32 % inside came twice, as a line and in the table), and a caption's lines
    never are - its line and those that go on with it, each alone at its height, stay text where
    they stood (VGG's Tables 3, 4 and 9 and Mask R-CNN's Table 7 had lost theirs: caption lines
    137 of 142 -> 142); a table stands in place of its blocks only when its cells hold exactly
    their words;
  - cells one header spans are joined by the gap between the last word of one and the first of
    the next alone (with whole words no word crosses a border); not a word set on its side, whose
    height is its length (ViT's "Caltech101" and "CIFAR-100" had become one header), which the
    box-cut test leaves out too (NIST 800-63B's table was lost to a rotated "Cryptographic");
  - rows of the papers whole on one line 78 % -> 89 %, as table rows 70 % -> 74 %, tables kept
    69 -> 74 of 94, the printed tables 99 % -> 100 % (no time limit); under the default 10 s the
    same on a quiet machine (GPT-3's 30 pages with tables took the model 8.5 s), and on a busy one
    70 % -> 73-78 % and 62 % -> 65-70 % (GPT-3's pages that look like a table did not all fit, 98
    and 141 of its 242 rows whole). Measured and kept: the box-cut
    test (without it 7 more rows whole, from tables that took sub-captions and an invoice's bank
    line into cells) and the joined spans (11 rows more as table rows);
  - the model runs in a process of its own (`scripts/pdftables.py`), and the read stops waiting
    for it when its time is up: its call cannot be interrupted, and one page held a read past its
    deadline and the MCP server's kill. The pages go to it one by one while the next are chosen,
    and a process still at work at the end is killed. The process costs 0.15-0.22 s a read on a 20-core Windows machine
    beside the model's own load of 0.7-0.8 s. Whole reads (the CLI, default limits, before ->
    after): Attention 2.1 -> 2.4 s (4.7 -> 5.2 on four slow cores), GPT-3 9.7 -> 10.7 s (its 10 s
    used to the end, 18 -> 20 pages laid out), NIST 800-63B 7.3 -> 7.2 s, a paper with no table
    1.7 -> 2.0 s (3.6 -> 4.4 on four slow cores: two pages asked, nothing found); a plain read
    0.6-0.7 s as before;
  - a page over 8 000 vector paths or 2 000 words in one block of text is not asked in a read's
    time: 20 010 separate strokes (a scatter plot drawn point by point) took the model 20-27 s,
    and 8 040 words 8.5-17 s; no page of the corpus has over 4 975 paths or 976 words in a block.
    It is in `left` and `heavy`, and the advice says it was too heavy; `--download` asks it. The
    counts do not catch every slow page (2 010 strokes took 11 s), the killed process does: a
    page of 5 010 strokes (20 s in the model) read in 2.2 s with a deadline of 2 s, 4.9 s with
    5, 10.8 s with the real 55 (before: 20.7 s each); heavy2 and dense2 0.7-0.8 s (27.5 s and
    17 s);
  - one tables clock a read: every PDF of a read - in a ZIP, an archived copy - shares the 10 s,
    and the manifest reports them (`signals.tables.files`, by name; the advice names their
    pages): six copies of the Fed's H.8 in a ZIP read in 11.1 s against 48.1 s, unreported;
  - `signals.tables` also when the step spent its seconds and kept nothing (a paper with no
    table: 2 pages asked), and `error` when the model does not work: it does not load
    (pymupdf4llm 1.28.2 does not even import without onnxruntime), or a page failed, which no
    longer stops the other pages. `--caps` has a line for onnxruntime, and `improve` names it;
  - `--alternate` on a PDF stays inside the read's time: pymupdf4llm's Markdown in calls that fit
    what is left (calls of ten pages after a warm-up of two since the review below), the pages no
    call reached stay PyMuPDF's text and are named, with `--download` in the advice. 600 pages of
    tables read in 49.7 s, 111 of them as Markdown, against 262 s;
  - onnxruntime's threads come from the CPUs the process may use where the OS says it
    (`os.sched_getaffinity`, Linux), not the machine's count; on Windows `os.process_cpu_count()`
    ignores the affinity mask (20 under a mask of 4), so there four threads may share two CPUs.
- **the tables fix reviewed** (a second independent review, 2026-11-21: 0 high, 3 medium, 10 low;
  the first review's findings closed on its runs, the numbers reproduced). Fixed, measured on the
  same corpus and scorer, a failing test first:
  - `--alternate` under load: one Markdown call of all that fit at 0.5 s a page (57 pages with
    50 s left) was killed at the deadline with every page, and the step then said nothing - four
    reads of GPT-3 at once on two slow cores, as the MCP server runs them, took 51 s each and gave
    no page as Markdown, the advice speaking of tables. Now a warm-up call of two pages gives the
    model's rate, then calls of ten pages at most that fit what is left, their headings levelled
    by the heading sizes of every call so far (as one whole call on Attention, GPT-3, BERT and the
    W-4); and what came back is said either way - `markdown`, `left`, "pages 27-75 are PyMuPDF's
    plain text, not Markdown (the time for the layout ran out)". The same four reads: 26-27 of the
    75 pages each as Markdown in 50 s; GPT-3 alone 26.6 s against 36.4;
  - prose and notes inside a table's box were cut into cells at their word gaps where a cell held
    two lines (a W-4's TIP paragraph, EfficientNet's footnotes over 13 cells; 52 cuts in 6
    tables), and the exact-words check could not refuse them - it holds by construction, a guard
    against loss and duplication, not placement. Such a line now stays text before or after the
    table, as a caption does: no cut left, the rows whole the same (788 of 889), 654 as table
    rows (653), every table and caption as before;
  - a wall that re-set the session's own cookie or expired it had the last word in the jar (only
    the names a wall brought were dropped): the entries before the read's first save are kept,
    and a read that ends at a wall puts back what it changed;
  - the model's process ends with the read: a thread watches the read's process (Windows: a wait
    on its handle, POSIX: the parent), so a read killed from outside does not leave it at its page
    18-24 s more (0.01 s); it starts with `-E -B`, so a caller's PYTHONPATH (another Python's
    PyMuPDF) no longer costs every PDF its tables - xchild too. The tests reach it through
    `READ_PAGE_TEST_MODEL_PATH`, which only `pdftables.py` reads. Left for the `--setup` work: the
    hop's job is made after its child started, outside the venv launcher's (KNOWN-ISSUES 128);
  - PubMed: a search for one record's number (`?term=ID`) and the old mobile address
    (`/m/pubmed/ID`, which NCBI sends to the home page) go to the API;
  - the cookie-wall phrases count up to 150 words on a page with no sections of its own (no
    h2-h6): a 102-word block page served with 200 read as `ok`; the 127-word help page stays `ok`;
  - the pages after the model's process ended are named, as the time's end names them, with why;
    after the time `signals.tables.more` says a page of rulings only may be missing;
  - a word is on its side by its line's direction, not its box (821 short horizontal words were
    taken for rotated ones: Apple's "September 28, | 2024" stayed split); the words, blocks and
    directions come from one text page (2.2 ms a page against 2.8 for two);
  - JSON-LD is no data for the page's scripts: a short product page no longer goes to the browser;
  - `signals.tables`' page lists are ranges ("28-600"): grid600's 573 numbers made the object
    2 966 characters of every MCP answer;
  - measured and not taken: splitting a grid row whose cells each hold k lines on shared heights
    into k rows (5 rows more as table rows, 2 rows whole lost, 13 more rows that hold no table
    row) - two rows of a page in one grid row stay together (KNOWN-ISSUES 127).
- **the `--setup` review's findings, the first group** (an independent review of the installer and
  the hop, 2026-11-20: 2 high, 7 medium, 10 low; the review's own inputs reproduced, a failing test
  first, KNOWN-ISSUES 134-141 and 128). `tests/environment.py` 28 -> 87, `tests/setup_audit.py`
  32 -> 35:
  - **OCR under a path outside ASCII** (Windows, a profile named in another alphabet: `Иван`):
    tesserocr hands tesseract the path in the ANSI code page, so OCR was dead - `--setup`'s check
    said 4 of 5, the report said "Nothing is missing", a scan read as `empty`. tessdata now goes by
    its 8.3 short name (`GetShortPathNameW`) when its path is not ASCII; OCR counts as working
    (`caps()`, the report, `_tesserocr()`) only after tesseract has started on a pack; where it
    does not (no short name, a damaged pack) a scan says `missing: ocr` with why (`signals.ocr_error`,
    and the advice), and the fix named is `READ_PAGE_HOME` on an ASCII path. The real tesserocr
    with the eng pack under a Cyrillic folder: `Failed to init API` before, "Setup check 2026" after;
  - **the yt-dlp updater cannot go back**: it asked for `yt-dlp[default]` with no floor, under the
    skill's current lock and a global three-day cutoff, so a lock pin younger than that sent uv to
    yt-dlp 2022.3.8.2 (no `default` extra; exit 0, success, stamp written). Now
    `yt-dlp[default]>=<installed>`, under the lock the environment was built from (a copy in
    `envs/<id>/`; the skill's lock only where its hash is the folder's), the date only on what
    floats (`--exclude-newer-package` for yt-dlp, yt-dlp-ejs, brotli, mutagen, pycryptodomex,
    websockets), and a result older than the installed one is put back. A dry run:
    2026.10.26 -> 2022.3.8.2 rc 0 before, "no solution" rc 1 (kept) after;
  - **`--setup` follows only a run that is at work**: the updater held `setup.lock` for its whole
    run and a `--setup` started meanwhile replayed the last run's log and exited 0 with nothing
    done. Only a state that is not done, whose process is alive and whose lock is held is followed;
    the updater has its own lock (`ytdlp.lock`) that a `--setup` waits for (5 min at most) and then
    holds; a lock that cannot be opened is nobody's, a folder that cannot be written is said at
    once; no pause after the updater's last try;
  - **a Python with no root certificates** (python.org's on macOS before "Install
    Certificates.command") is named, with the fix, instead of "--setup needs the internet";
  - **`fetch()` refuses a body shorter than its Content-Length** (a cut `deu.traineddata` was kept
    and every later `--setup` kept it), OCR language names with an underscore (`chi_sim`,
    `deu_latf`, `srp_latn`) are fetched, a name that is no pack's is said, and a pack with no pinned
    hash is kept only when tesseract starts with it (the check starts every pack);
  - **detached work in a job that kills on close** (a harness that runs each command in one): the
    worker and the updater died with the command, and the updater's stamp had already said "looked".
    `_detached` says which way it went; an attached `--setup` is followed to its end, the updater is
    not started where the job would end it; the stamp is touched after an update that worked (a
    failed look waits an hour). The hop (KNOWN-ISSUES 128) puts itself in its job before it starts
    the child, so everything it starts is born inside it - the same job nests inside a harness's
    (checked: it does, and a breakaway from the inner job stops in the harness's, which is then the
    one that ends the work). What a harness's job does to detached work is asked of a child that has
    broken away - the job it lands in is the first that lets nothing leave - because a venv's
    `python.exe` (an agent's usual way to start the skill on Windows) runs its interpreter in a job of
    its own, kill on close and silent breakaway, nested in the harness's and all that interpreter
    sees; the child is run by the base Python for the same reason, and with `-B` (`-I` ignores the
    caller's no-bytecode wish). The first version read the job it was in: under a launcher it said
    "free" and the work died with the command (found by CI's Python 3.9 venv on Windows). The hop
    killed alone with a venv launcher below it left 2 of 4 processes alive before (5 of 6 runs),
    none after (3 of 3);
  - defuddle's `--before` is a full timestamp (`2026-11-19T00:00:00Z`): npm read the bare date as
    midnight UTC and it binds defuddle's own version too; the same 27 packages (a real install of
    each form against an environment already built), and a test that the pinned version was published
    before it;
  - the lows: the Linux browser advice no longer runs a user-writable interpreter as root
    (`sudo apt-get install <the libraries>` from `playwright install-deps --dry-run`); a misspelled
    `--setup` (`--stup`) is not sent into the environment; a tar on a Python without filters
    (macOS's 3.9.6) extracts files and folders first and each link only where its place and
    target resolve inside (a link chain wrote outside before, in WSL); defuddle is run as
    `node <dist>/cli.js`, not through the npm `.cmd` shim, and any `.cmd` has its arguments quoted
    for cmd.exe, not for the C runtime (an `&` in a profile folder's name split the command).
- **the `--setup` review's findings, the second group** (KNOWN-ISSUES 147-150). `tests/environment.py`
  87 -> 98:
  - **what is downloaded is checked by content**: the lock carries the SHA256 of every file of
    its 55 pins (`tools/setup_lock.py` with `--generate-hashes`: 1 099 hashes, 94 KB; the same
    names, versions and markers as before, compared; a pin moves only through `PINS`). uv checks
    hashes in `-r` and in `-c` (a wrong one fails both, tried), so the one-at-a-time fallback and the
    yt-dlp step are covered, and yt-dlp, which floats and has none, installs under them. uv's wheel
    (18 files, PyPI's JSON and its simple index agree) and Node's archive (8, nodejs.org's
    SHASUMS256.txt) are pinned by SHA256 in `envsetup.py` and fetched against those - a mirror
    serves the bytes, never their checksum; a file that is not pinned is not fetched, and a test
    compares the tables with PyPI and nodejs.org (a typo would refuse every machine). The browser
    (Playwright's download: TLS and a size, no hash anywhere) and yt-dlp are TLS only, and README and
    `references/engines.md` say so. The environment id moves with the lock's text, so the next `--setup`
    builds a folder for it from uv's cache;
  - **one certificate store**: urllib trusted the OS's, uv its bundled Mozilla roots, Node its
    own; behind a proxy that inspects TLS the check and uv's first download passed and the next step
    failed on a certificate, with no advice. `UV_SYSTEM_CERTS=1` and `NODE_USE_SYSTEM_CA=1` (uv
    0.13.9's `--system-certs` and Node 24's `--use-system-ca`, read in their own help; Node's store
    118 roots bundled, 271 with the system's 153; Playwright's driver, Node 24.21, reads it too) are
    set for every installer unless the user set them, and a step that fails on a certificate says so
    once;
  - **an environment Python that starts and fails** (an antivirus takes a DLL it needs): the
    read was empty with the interpreter's own exit code, which SKILL.md calls a wrong call. A
    start-up handshake - the parent makes a file, the child removes it as its first act - finds a
    child that never reached the read; the read then runs in the machine's Python with an
    `environment:` line (`signals.env_failed`), and `--caps` says why. On Windows every run, on POSIX
    the first of each build (`setup.started`; after it `exec` is kept, and only that start is
    guarded);
  - **the docs say what lands outside the folder and what installs by itself**: `node-compile-cache`
    and `pycache` in the temp folder, the read cache, yt-dlp's cache; the yt-dlp update of a video
    read and `READ_PAGE_SKIP=update` (README had no word of it); the setup report no longer says
    "Nothing here installs by itself" - it installs nothing, and says that a video read updates
    yt-dlp when the environment is in use. Moving those files into the folder is planned (row 151).
- **an archive's pictures: four defects** (three found by an independent review of the document
  readers on 2026-11-20; the fourth left over from the review above;
  KNOWN-ISSUES 129-132), each with a failing test first, before -> after on one machine:
  - the picture order of an EPUB or a docx ran outside the read's clock and its scans were not
    linear. `<rootfile\b[^>]*full-path` (and the patterns for `<item`, `<itemref`, `<img`, a docx's
    `<Relationship` and `<a:blip`) ran to the end of the file from every `<x ` that never closes,
    and every picture was looked for in a list: a 1.3 KB EPUB whose container holds 40 000
    `<rootfile ` took 68.9 s for the order alone, 79.6 s through the CLI (the review: 82 s), past
    the read's 55 s. Now a tag is read as `[^<>]{0,8192}` (XML has no `<` inside a tag), a set
    stands beside each list, a chapter the spine names again is scanned once (1 500 itemrefs of one
    500-picture chapter: 6.0 s -> 0.01 s), and the step is the read's: 10 s at most, less when the
    deadline is nearer (`budget`, the step `picture-order`), and with no time left there is no
    order - the book's or none, `images_ordered` unset - not a guess. The container: 0.00 s; 30 000
    pictures of one chapter 7.3 s -> 0.18 s; of a docx 8.7 s -> 0.24 s; 40 000 unclosed `<item `
    in the OPF 7.1 s -> 0.00 s; 7 000 unclosed `<img ` in a chapter 5.1 s -> 0.00 s. The CLI read
    of the broken container still takes 6.9 s: pandoc cannot read the book, and a machine's own
    markitdown is asked next - the converter's time, not the order's. An archive with no picture
    has nothing to order and is not scanned;
  - one picture the archive does not hold dropped all of an EPUB's pictures: `picture_phase`
    replaced the manifest's list with the text's remaining links, so the missing one was `#1`
    again, the text kept `[img #1]` and `[img #2]` pointing nowhere, and `--refresh` deleted their
    files. Now the pictures with a file keep their entries and the others are numbered after them:
    an EPUB of two pictures and a third not in the archive lists `#1` and `#2` with their files
    and `#3` as not downloaded, the files stay under `--refresh`, and no two markers share a number;
  - `zip_images()` counted only the pictures it kept against its 250 MB, so a package of copies
    (or of counter pixels with a gigabyte of zeros behind their header) was unpacked and hashed
    whole each time: 40 copies of a 63 MB picture in 2.6 MB of EPUB took 5.15 s. Now every byte
    unpacked counts, and a copy - the same declared size and CRC - is skipped before it is read:
    one copy is unpacked, 0.17 s; eight 2 MB counter pixels under a 5 MB budget: 8 unpacked -> 2.
    The 100x ratio check still starts at 64 MB: a flat BMP legitimately compresses further, and
    the byte count is what bounds the work;
  - the model's process watched the read's process by `OpenProcess(SYNCHRONIZE)` and, on Windows,
    ended when it got no handle: a sandbox that refuses that access (PID 4, the System process,
    does: error 5) would have ended it at once and every PDF would have lost its tables without a
    word. Now only "no such process" (error 87) ends it; where it cannot watch it goes on, and
    stdin's end ends it with the read. The test runs a child Python on PID 4 (it stays), on a
    process that has ended (it ends) and on one that is killed (it ends 0.0 s after).
- **our EPUB, ODT and RTF readers hardened** (`scripts/docreaders.py`, the standard library alone:
  an independent review of 2026-11-21 found them unsafe as the only path - 6 high, 4 medium, 10
  low, three of them fixed above; KNOWN-ISSUES 152-160, and 133). Files of 1-5 KB from
  the web made them take gigabytes or minutes. Each finding has a failing test first
  (`tests/docreaders.py` 42 -> 88, every hostile file built in the test at a small size and read in
  a child Python killed past its time or memory; the "linear, not quadratic" checks compare two
  sizes on the same machine - a ratio under 8, 4 times the size taking about 4 times as long -
  instead of a number of seconds, which a slow runner (macOS on Intel) exceeded);
  before -> after, measured with a probe (the
  reader in a watched child, the converter's 10 s) and through the CLI:
  - **a process of their own**: with pandoc's process gone nothing could stop the converter
    step - the deadline is the read's own, and three CLI reads ended at 62.8, 82.1 and 91.0 s.
    `own_doc()` runs `docreaders.py KIND PATH UNTIL KILL` (`-I -S -B`, the standard library alone):
    it stops itself at its time, writes what it read, and is killed at the converter's time (10 s,
    or what the deadline leaves; none with `--download`); RLIMIT_AS holds it to 2 GB where the OS
    has one (Linux; a timeout bounds no memory, 1.4 GB came in 5.9 s). A process start costs
    0.1 s on Windows and 0.05 s in WSL (with -E -B, as the other children: 0.11 and 0.12 s). All
    the read's EPUB, ODT and RTF documents share the 10 s - a ZIP's documents had 10 s each, and
    two RTF lists took 22.4 s, now 1.9 s; a ZIP's document its time did not reach, or whose reader
    was stopped, says so under its name. All 68 hostile files end through the CLI in
    8.9 s at most (the 17.6 MB RTF of 2 million runs), the rest in 0.6-3.8 s;
  - **caps per document, not per element**: a table's grid holds 250 000 cells at most, its
    spans and repeats included, a document's tables 1 000 000, a row 1 024 columns; an RTF row
    definition is one tuple for all its rows and 256 borders; an ODT's `text:s` adds a million
    spaces a document at most; a table cut says so. 1 KB of spanning EPUB cells 494 MB -> 23 MB;
    an ODT of rows and cells repeated 64 times each (4.5 KB) 40.0 s, 1 267 MB and 164 MB of
    answer -> 0.04 s and 1 MB; 4 000 RTF rows of 4 000 borders 15.9 s -> 0.09 s;
  - **no scan goes back over what it passed**: the note scan, the OPF and the container read
    tags as `[^<>]{0,8192}`, the spine has a set beside it, the tree builder knows where each tag is
    open (a `<p>` left open under a `<button>` walked the whole stack at every tag that closes a
    `<p>`: 27 s -> 0.18 s) and joins a text once. html.parser itself ran from every unclosed
    construct to the end of the part, again at each 64 KB it was fed (one 4 MB tag 2.5 s on Python
    3.13.18, 19.7 s on 3.9.25), so a part goes to it with its comments and CDATA out, the contents
    of its raw-text elements out (script, style, title, textarea, iframe, noembed, noframes - the
    2025 parsers read the last five as raw text, the older ones not), an xmp as a pre, and a "<"
    that no ">" closes within 8 KB as text. 100 KB of `<a ` 87.5 s -> 0.02 s; 200 KB of `<item `
    in the OPF 2.35 s -> 0.01 s (quadratic: 20.6 s at 400 KB); 40 000 spine parts 13.9 s -> 0.21 s;
    a container of 40 000 unclosed `<rootfile ` through the CLI 82.1 s -> 0.6 s;
  - **html.parser's end of input** (CVE-2025-6069, on Pythons before 2025's fix: 25 KB of `<a `
    24.5 s on 3.13.2): no "<" is left open when html.parser ends, and the kill is the backstop;
  - **a run of `![` and a book's own Markdown**: `_escape()`'s picture pattern holds no
    `[` and is bounded (40 KB of `![` 32.7 s -> 0.01 s); the picture pass's `IMG_LINK` and `LINKED`
    stop at the next `![` (8 000 `![` and 8 000 `![](` 6.9 s -> 0.00 s), and its fence scan no
    longer crosses line ends (30 000 blank lines 2.7 s -> 0.00 s). The readers escape the
    document's own text for Markdown - a backslash before punctuation, `` ` ``, `*`, `[`, `]`, and
    `_` but inside a word - so a book's literal `![x](y)`, `*****`, `[a]` and `_b_` stay text
    (`![x](y)` became a picture link, the Calc guide's `*****` emphasis);
  - **RTF lists**: a list's lines are joined once (100 000 items 60.3 s -> 0.59 s), `\ilvl`
    stays within RTF's 0-8 (4 000 levels gave 16 MB of indentation -> 92 KB), each list counts its
    own numbers (20 000 numbered lists ran out of time at 88 % -> 0.26 s for all), and the writing
    of what was read has a clock of its own;
  - **the DOCTYPE guard**: expat is asked whether the prolog declares a DOCTYPE, so a line end
    after `<?xml ...?>`, a BOM, UTF-16 or a space no longer get past it (expat's own limit was all
    that stopped the bomb); a formula or a `styles.xml` refused says so (both went silently), and
    the plain ODT reader of ODS and ODP (`odf_text`) has the guard too;
  - **one bad element is one**: an EPUB part, an ODT element or an RTF stretch that breaks is
    named and the rest is read - nesting 1 200-1 500 deep in a table, in `<ul>`, in ODT lists,
    cells and `draw:a` (RecursionError), `<![bogus[` on Python 3.8 and 3.13.2, an RTF `ᄔ112` - and a
    reader that breaks as a whole leaves the document's plain text (`docreaders.plain`, in its
    process too); `rtf_text` gave way to `docreaders.rtf_plain`, which passes the groups nobody
    reads in one scan (it cut each out of the whole text);
  - **the smaller findings**: an RTF paragraph past 50 000 runs is plain for the rest (2 million runs
    904 MB, and 81 % of the file in 15 s -> 72 MB, all of it in 5.8 s); emphasis is joined in one
    pass; an EPUB's first loop reads the clock; "--download reads it whole" is said only where the
    pace so far says it would be (it was said of a book that read 0 parts of 1 in 91 s); a
    picture that is a link keeps its address (`[![alt](path)](href)`, which the picture pass writes
    after the marker); `odf_text` reads a part past 64 MB up to it and says so (it gave nothing);
    `office_plain()` carries only the XML parts, unzipped - a template's 60 MB picture was unpacked
    and zipped again (137 MB of memory -> none); an RTF is read with a buffer its own size, not
    128 MB; pandoc's time counts in the converter's 10 s (our reader then had 10 s more);
  - **KNOWN-ISSUES 133**: an archive's `mimetype` is read up to 256 bytes and a docx's footnotes and
    endnotes up to 8 MB, their `w:t` matched in linear time (a 60 MB `mimetype` 137 MB -> 0);
  - **nothing lost**: the A/B against pandoc again on the 52 files - every count the same
    (headings, table rows, list items, notes, pictures, code blocks), prose words 1 336 902 ->
    1 336 908 (the linked picture's address, and a literal `node\_name` now escaped).
- **EPUB, ODT and RTF are our own readers', and pandoc leaves `--setup`** (decided after the
  measurement and the hardening above). `scripts/docreaders.py` reads EPUB 2 and 3, ODT
  and RTF as Markdown with the standard library alone: headings, nested lists, tables with merged
  cells, notes, links, pictures as markers where they stand, code, formulas (an ODT's StarMath),
  code pages and `\u` escapes. Against pandoc 3.9 on 52 files through the CLI (15 EPUB, 18 ODT,
  19 RTF; LibreOffice's guides, gov.uk's Word files, Google Docs; Word, WordPad, TextEdit; English,
  Russian, Chinese, Greek, Hebrew, Italian): the files' own words within 0.03 %; headings 2 440
  against 2 313, table rows 2 282 against 1 970, notes 77 against 74, pictures placed in the text
  1 126 against 760. pandoc garbled every non-Latin RTF (Greek, Hebrew and Chinese as Latin-1
  mojibake, Russian without its spaces), lost Frankenstein's endnotes, 62 of the 66 chapter
  headings of Gutenberg's Pride and Prejudice, whole tables of gov.uk's reports and 573 figure
  captions of the Calc guide, and left 7 688 HTML tags in it. A document's CLI median, ours in its
  own process: 0.74 s against 1.27 (EPUB), 0.64 against 0.88 (ODT), 0.60 against 0.80 (RTF).
  - `doc_text()` asks our readers first and alone for these three formats; `pypandoc_binary` left
    `envsetup.TOP`, `_pandoc()`, its check and its folder on `PATH` are gone, and the lock is
    regenerated by `tools/setup_lock.py`: 54 packages, 1 092 hashes, nothing else moved. The
    download is 41, 35 and 26 MB smaller (about 390 MB on Windows, 445 on Linux, 355 on macOS: the
    locked wheels by PyPI's sizes, the archives by their Content-Length) and the environment 226 MB
    (Windows) and 162 MB (Linux) smaller: about 0.95 and 1.1 GB. A machine's own pandoc stays the
    last resort for an office file the office readers cannot read, as its markitdown does; no
    advice offers it any more (`setup_rows`, `improve`: "pip install pymupdf");
  - found and fixed by the readers' measurement, on the pandoc path too (KNOWN-ISSUES 161-164): a
    damaged part of an EPUB or a DOCX crashed the read ("internal error": the picture order caught
    `KeyError` alone); an ODT whose `content.xml` unpacks to 1 GB was read whole by `odf_text()`
    (141 s, 2.1 GB), an EPUB chapter of 1 GB by the picture order (2 GB); an ODT's pictures
    (`Pictures/`, `media/`) and an EPUB's outside `images/` and `media/` were never placed (176
    broken markers in two gov.uk reports); `office_fast()` gave nothing for `.docm`, `.dotx`,
    `.ppsx`, `.potx` and Strict OOXML, which pandoc read - `office_plain()` gives python-docx and
    python-pptx the plain content type and namespaces;
  - what nobody reads now: a DOCX of formulas alone (pandoc wrote TeX; the formulas of a DOCX with
    text were dropped before too: row 165), an RTF's pictures (pandoc's links pointed at files it
    never wrote: row 166); a cut archive's misleading answer is row 167;
  - `tests/docreaders.py` (88 checks, 89 on Linux) runs in CI beside the office fixtures; the CLI
    checks there read with a machine's pandoc on PATH or not, and `tests/setup_audit.py` counts no
    pandoc among `--setup`'s engines (36). `SKILL.md` names none of this and does not change; main
    carries one file more (`scripts/docreaders.py`: 31 files).
- **PubMed** (found by a run without paid keys, 2026-11-20: 69 of 71 pages, the
  other miss a site answering 503 to everyone). Its page answers a client that did not run its
  script with HTTP 203 and "Cookies must be enabled ... reload this page to continue": that
  read as `ok`, 14 words, no advice. The phrase is a wall's now (`blocked`) - on a page of a few
  words: a help page of 127 words titled "Please enable cookies" read as `blocked` too (the two
  cookie phrases count under 60 words, and under 150 on a page with no sections of its own;
  PubMed's wall has 14, NCBI Bookshelf's 34) - and a
  PubMed record is read through NCBI's own E-utilities with no flag (`api:pubmed`: the citation,
  the authors, the abstract by section, the identifiers, the MeSH terms; only the record's
  number leaves; 0.6-0.9 s). A book's record (a chapter of StatPearls or GeneReviews: 40 288 of
  them) comes from the same call - the chapter, its authors, the book, its editors and
  publisher, the abstract, the sections, the Bookshelf ID; the old address
  `www.ncbi.nlm.nih.gov/pubmed/ID`, still in many references, goes to the API too (both were
  `blocked`), as do `?term=ID` and the old mobile `/m/pubmed/ID`; an exponent stays one ("10^-16", not "10-16"); the 4 MB cap counts the unpacked
  text of a gzipped answer.
- **README: the install on top** (for someone who came only to install): an answer example
  and an Install section right under the pitch - three steps, a `git clone` line per agent (Claude
  Code, Codex/Cline/goose, Cursor, Gemini CLI, OpenCode, GitHub Copilot), the ZIP way, `--setup`,
  update and remove - and a link to it in the first lines. The commands say `$HOME`, not `~`:
  Windows PowerShell 5.1 and `cmd` do not expand `~`, and the clone landed in a folder named `~`
  (checked in PowerShell 5.1 and 7, cmd and bash).
- **no markitdown** (only if quality does not drop - measured, references/documents.md):
  EPUB goes through pandoc with its HTML leftovers cleaned (`clean_pandoc`: wrappers out, code
  untouched, pictures as markers, an HTML table one row a line) - on 12 EPUBs the same words,
  headings, tables and pictures as markitdown, 0.8-3.6 s a book against 3.2-4.4; a DOCX is read in
  its own order with its content controls and text boxes, a PPTX with its groups and tables (only
  markitdown read those before); a plain ZIP is listed and its files read (`zip_text`); a YouTube
  transcript when yt-dlp has none comes from youtube-transcript-api directly (the same words on
  four videos, 4-6x faster, with timestamps). The environment: 16 packages and 74 MB fewer. A
  machine's own markitdown stays the last resort; the setup report no longer recommends it.
- **OCR in-process**: a scanned PDF's pages go through tesserocr when it is there (each page with
  its own clock), the tesseract command stays the fallback; the OCR languages are the packs in
  `READ_PAGE_TESSDATA`. tessdata_fast was chosen over tessdata_best by measurement: the same quality
  (clean CER 0.19 against 0.48 %, poor scans 39.6 % both), three times faster, a quarter of the size.
- **the advice says `readpage.py --setup`** wherever it installs the missing engine
  (`missing:`/`improve:`, the setup report), and the machine's own command only for what it cannot
  (curl, lynx, pdftotext - unneeded beside PyMuPDF and the extractors -, and tesseract where no
  tesserocr build exists). SKILL.md says so in three edited lines, 5 699 -> 5 696 bytes.
- tests: `environment.py` (28 checks, offline: a real venv as a fake environment - used, its tools
  first, exit codes and UTF-8 through the hop, skipped, broken, no loop, the MCP server through it,
  --setup offline and while another runs, its first line with the sizes, archive members outside
  their folder refused, uv's wheel for the machine, every promised engine pinned, yt-dlp out of the
  lock and looked for every three days, the folder outside AppData on Windows, defuddle's own
  packages as of one day); fixes 139 (a wall's
  own cookie, the session kept - by its value too, when a wall re-sets or expires it -, a stamped
  scan with `--alternate`), reading 19 (a wall's advice with and without the readers, an empty
  page without a browser, the thin app page, JSON-LD that is no app's data); each new
  check was seen failing on the commit before. A real Google Doc's address is out of the tests
  (a made-up id; the live case reads `READ_PAGE_TEST_GDOC`). formats 69 (a PDF's table as rows, its
  numbers and the text around it once, the pages in the manifest, the off switch, a PDF with no
  table - in-process too, where the model's process is not even started -, the model's time and
  `--download`, the hint without the model, a spanning cell put together, a box that cuts a word;
  then, with a stub of the model that cuts the way the real one did: a word a grid line runs
  through whole, a header a row line runs through one cell, every word of the page once, the
  caption inside the box kept as text; two headers on their side not joined, a word outside the
  grid in the nearest cell; a page that fails and a model that does not load said; one clock for
  three PDFs of a ZIP; pages too heavy not asked; a slow page against a deadline of 4 s;
  `--alternate` on 200 pages against 6 s; a ZIP's tables reported by file; then, after the second
  review: a footnote cut at its spaces kept as one line of text, a short horizontal word not on
  its side, a date split by a column line joined, the pages after the model's process ended
  named, a caller's PYTHONPATH kept from the model, `--alternate` cut by its time saying which
  pages are plain text, and the model's process gone within a second of a read killed mid-page);
  statuses 43 (the cookie wall, an article with its words, a short help page about
  cookies, a 102-word block page served with 200, an archived PDF's tables), sources 42 (PubMed
  through E-utilities; a book's record, the old address, `?term=ID` and the mobile one, an
  exponent and a gzipped answer, the cap on the unpacked text). setup audit 32 (pymupdf4llm
  without onnxruntime), props 81 (`signals.tables` as ranges, against the schema).
  `tools/setup_lock.py` writes the lock. With the environment all 21 suites are green on Windows, and in WSL Debian
  13 (`--setup` from nothing there: 1 min 19 s, 1.4 GB, every engine answers, the browser too) the
  19 offline ones. Found on the way: the hop's `-E` dropped the caller's PYTHONDONTWRITEBYTECODE
  (now passed on as `-B`), and a run's first imports wrote their `.pyc` into the private cache
  readable by others (the umask is now set before them, POSIX); a suite that puts a fake tool on
  PATH runs outside the environment (`READ_PAGE_SKIP=env`), and an in-process MCP call that needs
  OCR is skipped when the suite's own Python has none.
- tests: `probe.py`, `compare.py` and `sweep.py` are gone (live comparison tools that needed another
  skill, or a search skill, that is not published); check names no longer carry the ids of the
  notes they came from; `props.py` traded a check that was always true for one that a read into a
  folder with a non-ASCII name writes its manifest there.

**A safety net before any behaviour changes.**
- **lint in CI**: ruff with the pyflakes rules and vermin for Python 3.8, a job of its own. Unused
  names are gone; the three known defects stay visible, each tagged `noqa`:
  a timeout never marks the answer partial (`nonlocal` is missing), `too_large_out` is not
  defined, and the `ocr-langs` row is dead code after `return`.
- **`READ_PAGE_TEST_PUBLIC_HOST`**, for tests only: exactly that one address counts as public, so
  the main channel (curl_cffi) finally runs against a local server. Every other loopback address,
  `localhost` and metadata hosts stay private. Unset, nothing changes.
- tests: `harness.py` (a route server, a CLI run into a temp folder that reads `manifest.json` and
  the files rather than stdout, checks); `advsrv.py`, adversarial pages from the review (encodings,
  `#/` routes, late JS, walls, 5xx, truncated, stalled and trickling bodies, redirects to `file://`
  and to a private host on 127.0.0.2, a gallery, a Referer-guarded image host, a flaky server);
  `channel.py`, the main channel offline (9 checks, in CI with curl_cffi); `corpus_offline.py`,
  61 saved real pages run through extraction with no network - the pages stay out of git,
  `corpus_urls.txt` rebuilds them.

**CI again, and a switch to measure ad blocking.**
- **`--download` pictures work on Python 3.9 again**: a picture with no size limit was read as
  `read(-1)`, which 3.10+ takes for "all of it" and 3.9's http.client turns into `bytearray(-1)`:
  every such picture failed with "negative count". Found by the first CI run since the push
  (Ubuntu, Python 3.9); `read(None)` reads all on every version.
- The readability test skips where readability-lxml is not installed (the CI runners), as the
  defuddle tests do.
- **A status from Chrome's `--dump-dom` keeps the server's code**: with no Playwright the browser is
  Chrome's command line, which knows no HTTP status, and a 419 "Sorry." page it rendered came out
  `empty` instead of `blocked` - on any machine with Chrome and no Playwright, the CI runners among
  them. The server's code for the same address now decides, and the reason names it the server's.
- tests: the warm MCP process is looked for among all descendants (a Windows venv's python.exe is a
  launcher, the real interpreter its child).
- **A rescue after a moment's failure lives a minute, and its advice says what happened**: an agent
  found it - runoob did not answer once, the archive copy of January came back with "the live page
  is gone", and every read for 15 minutes got that copy though the page was back a minute later.
  Such an answer (a reader's or the archive's after no answer or a 5xx: `signals.rescued_after`) is
  served from the cache for 60 s; the advice says "did not answer" or "answered HTTP 503" and names
  `--refresh`, and "is gone" stays for a 404/410.
- tests: the fake defuddle that never answers keeps node alive with a timer - on Linux a pending
  promise alone let it exit, and the CI saw a quick failure, not the stuck parser meant.
- **A picture at its own address keeps its ending**: one whose type was not PNG, JPEG, GIF or WebP
  was saved as `raw.png` - an agent's offline copy of gov.uk had its SVG logo and its icons so.
  SVG, ICO, AVIF and BMP are known by their type, any other picture by its address's ending.
- **page.md's links are whole addresses, as content.md's**: html2text was given no base, so
  page.md said `/help/cookies` where content.md said `https://www.gov.uk/help/cookies`, and the
  same agent joined 102 links itself. page.md, the main block and readability's text resolve links
  and pictures against `<base href>` or the page's address.
- **netguard stops taking connections when it is closed, on Linux too**: Linux keeps a socket
  listening while another thread waits in `accept()` on it, so after `close()` the guard went on
  taking connections - under its own rules - until the read's process ended, seconds later. Nothing
  outlived the read: every read is a process of its own, MCP's too (an earlier note here said an
  MCP process kept a thread a read; it does not). `shutdown()` first wakes that `accept()`. The
  check had never run on Linux: CI's job stopped at an earlier failure each time.
- CI: every suite runs even when an earlier one failed (`if: !cancelled()`; the job still fails),
  so one red step no longer hides the rest - on Linux, security and every suite after it had not
  run for ten days.
- Measured, nothing changed: an ad and tracker list in the browser (a popular ad-block DNS filter, 67
  pages read twice with nothing else blocking) refused 341 names and 5 % of responses but made no
  read faster (wall p50 7.48 -> 7.79 s), so the browser keeps no list (KNOWN-ISSUES, decisions).
- `CLAUDE.md`: notes for working on this repo - rules, tests on three systems, CI, traps.
- **A flag that is not read-page's no longer stops the read**: a model invented `--to 407`
  from `--from` and the whole call failed with argparse's usage. Now the page is read and an
  `ignored:` line names what was left out; a misspelled flag is the flag meant, silently
  (`--screenshot`, `--allow-extrnal`, `--form`: one edit for a short name, two for a longer one,
  one near flag only - `--allow-images` is not "meant" as `--deny-images`); a bad `--from` or
  `--file` value is left out the same way, and a stray value
  taken for the URL gives the URL back. MCP's tools do the same with an argument outside their
  schema, which used to refuse the call. `--json` names them too; the saved manifest does not.
- **Python's compiled modules stay out of the skill's folder**: some harnesses show the agent every file
  of a skill's folder, and `scripts/__pycache__` was 28 of them. They go to the user's temp
  folder (on Linux and macOS inside `read-page-<uid>`, 0700, checked: a `.pyc` planted by another
  user would run as our code; no safe folder, no cache), for every read's processes too; a start
  stays as fast (0.17 s).
- "1 pictures not downloaded" reads "1 picture".
- **`--ocr N`: the text drawn in picture N, for a model that cannot see it**: two models without vision
  spent 18 to 84 calls reading Figure 1 with tesseract by hand.
  On demand only, as MCP's picture `read` is - the answers stay as long as they were. An SVG gives
  its own text; other pictures go through tesseract twice, in grey and as dark ink on light
  (threshold 120), and the reading with more confident words wins: Figure 1 gave 15 of its 16
  labels in 0.5 s. tesserocr in-process when installed, else tesseract's command. MCP:
  `read_url(ocr=N)`, `read(file=img/..., ocr=true)`.
- CI: macOS runs on demand only, before a release - not nightly.
- tests: every suite drops the user's own `READ_PAGE_DEBUG` / `READ_PAGE_DEBUG_DIR` - set for agent
  runs, they sent the suites' logs to the agents' log folder, and the debug checks found none.
- macOS CI runs again: the `macos-15` runner picked the job up at once, after the `macos-13` runs
  had waited a day each and been cancelled.
- `READ_PAGE_TEST_BLOCKLIST=FILE`, for measurements only: netguard refuses the names of a host list
  (an ad-block DNS filter, a hosts file) before any lookup, and the debug log counts them.

**A measured set, a held-out sample, five shells; seven defects it found are fixed.**
- **An archived copy that comes gzipped is unpacked**: Wayback's `id_` hands a page as its site
  sent it, gzipped as often as not, with or without a `Content-Encoding` header, and urllib
  unpacks nothing. Crunchbase's copy was decoded as KOI8-R, and 199 KB of mojibake came back as
  `ok`, "100% of the page". gzip and deflate are unpacked now, a cut snapshot as far as it goes;
  brotli or zstd without their modules is no text, and the chain says why
  (`archive:wayback (... cannot unpack it)`), never the wrong text.
- **A picture that failed is asked once more, not by every answer**: one lost to a dead host, a
  server error or a dropped connection gets `failed_at`; an answer printed 30 s or more later asks
  it once again (`PICTURE_RETRY_AFTER`), and after a second failure it is not asked. Every answer
  from the cache had asked dmoz's dead picture hosts again - 0.55 s instead of 0.23 - and a host
  that never answers would have cost the whole 6 s phase each time. A picture the phase cut, one
  never printed and one `--deny-images` named are asked whenever printed, as before.
- **readability's Markdown is not wrapped**: html2text's default 78 columns split a photo's alt
  and address over three lines on Le Monde, so the picture stayed a raw `![...](...)` with a broken
  address and no marker, and paragraphs were cut into lines. `body_width = 0`, as page.md has.
- **An outline too long for its room is thinned, not dropped to the top level**: Pride and
  Prejudice's 66 chapters did not fit the 2.5 KB, so the outline was the book's title alone and the
  last chapter was 16 answers away. When the levels that fit give fewer than 12 rows and finer
  headings exist, the next level down is listed thinned evenly - every k-th, the last one, the
  coarser rows kept - with a closing "… N more between these"; now it is 2 answers. A list too long
  even at its top level, and the block rows of a text without headings, are thinned the same way
  instead of cut after their first rows; a page whose headings were all second-level and too many
  had had no outline at all.
- **defuddle no longer drops a term's link inside a sentence**: its clutter list removes any
  element whose id or class holds one of about 590 words, "next-" among them, inline elements too;
  the WHATWG specs give each term's link an id like `data-state:next-input-character`, and the
  parsing chapter read "Consume the:" 81 times. An inline element (a, span, dfn, code, ...) loses
  its id before defuddle sees the page; a footnote reference keeps it (by its id, its class or its
  role - docutils' are `id="id1" class="footnote-reference"`). On the 61 saved corpus pages the
  WHATWG chapter gains 4 528 words, Wikipedia's LLM article 29, and no page loses a word. A block container named so
  (`<section id="next-steps">`) already came back by the block rule. Classes stay (code languages,
  math), so an inline element's class can still cost its words (KNOWN-ISSUES 80).
- **An inline SVG diagram is one line of its labels**: defuddle passes inline `<svg>` through as
  markup, and SQLite's syntax diagrams were 13.6 KB of path data, a third of lang_with.html's text.
  Each becomes `[diagram: WITH RECURSIVE cte-table-name AS ( select-stmt ) ...]`; one without labels
  (an icon) goes; an SVG inside a code block is an example and stays.
- **page.md stays the whole page**: it was swapped for a copy of the text whenever it had fewer
  characters, and the text's long absolute links (defuddle writes them so) outgrow page.md's
  relative ones - 7 HTML pages of a measured run (SQLite, namu.wiki, opennet, samlib, qiita,
  aozora, an archived python.org) had lost their menus and links that way. Words count now, links'
  addresses not, and the text stands in only below half of them: a script shell the browser
  filled, a site API's own page.
- `BUILD` 12: a copy cached before these fixes (an archive's mojibake, a wrapped readability text)
  is not served; a picture's manifest entry may carry `failed_at` and `retried` (the schema has them).
- CI: the macOS workflow asked for `macos-13`, an image GitHub retired on 2025-12-04 - the
  "cancelled under capacity pressure" runs of 2026-11-02 were that label. It asks for `macos-15`.

**SKILL and documents.**
- **SKILL.md is the procedure: about 1 400 tokens**, 5.6 K characters instead of 17 K. The
  command and its three rules (`--allow-external` for a public page from the start, up to two
  minutes for the command, no pipe on its output), how to read the answer (`--from N`, `page.md`
  for how the site is organised, `--screenshots` for how it looks, the picture markers), the
  statuses and the advice, the rules, the flags, what to do when nothing works, and the reader
  with no Python. Everything else moved, unchanged, to `references/answer.md`: the files, every
  status, every flag, privacy and the network, the manifest, limits, cookies, pictures, video, MCP.
- When nothing works - another source without asking; else ask once, naming what would get
  each page: a tool to install, or the user's own browser through a tool the agent has (behind
  their login, or where they see the page differently: signed in, an ad blocker, their region);
  else say what was tried and ask for a paste.
- The text comes in the answer, `--from N` goes on; in Windows PowerShell 5.1 a saved file is
  read with `Get-Content -Encoding UTF8` (without it a UTF-8 file comes out garbled - checked).
- Three lines with no Python - the page with curl, Markdown from Jina by POST
  (`--data-urlencode`, so a `#/` or Cyrillic address survives), the latest Wayback copy
  (`web/2id_/URL`, `--compressed`: it comes gzipped) - run in bash, PowerShell 5.1 and 7
  (`curl.exe`) and cmd.
- The README's floor is Python 3.8 (what vermin checks), the 98-page sweep is dated and the
  226-page check stand beside it, the docs list counts the rows it has; KNOWN-ISSUES 22
  gives the measured size.
- The setup report names neither LibreOffice nor ffmpeg - the reader runs neither, and
  `--caps` no longer looks for them - and its language-pack row, dead code after a `return`, works:
  with tesseract and English alone it offers another `.traineddata`.
- `caps()` once a run: the HTTP attempts take the read's own (each check of the kept one walks
  PATH: 3 ms).
- tests: `setup_audit.py` 27.

**Netguard, the browser's only way out.**
- **A hole found and closed.** Playwright's request routing, the browser's guard until netguard,
  saw only the first URL of a redirect chain. A public page that fetched its own `/hop`, answered
  by a 302 to 127.0.0.2, got the internal answer into its text; a meta refresh to such a hop made
  the internal page itself the text, no CORS needed. The HTTP tiers check every hop and were never
  open to it.
- **netguard** (`scripts/netguard.py`): the browser of a public page goes out through a SOCKS5
  proxy of the reader's own on 127.0.0.1, which only that browser uses. Every connection - a
  redirect hop, a frame, a WebSocket - is checked once on the very addresses it then goes to
  (`browser_policy`), and an internal one never opens: the tests count the internal service's log,
  +0. Chrome hands the proxy every name, so the browser's DNS rebinding window is closed too
  (KNOWN-ISSUES 51), and the `--dump-dom` path, which had no guard at all, goes through it (52).
  Fonts and media of a text render are off by flags, WebRTC is held to the proxy. TLS stays end to
  end; the site sees the same machine and the same browser. It steps aside for an internal page, a
  machine whose browser has a proxy of its own, WebKit and `READ_PAGE_SKIP=netguard`: there the
  request rule guards, and a watch on the responses drops the DOM of a page whose hop answered
  from inside (`chain.skipped`, `signals.browser_inside`); the advice then says so outright and
  names `--allow-external`, which reads the page through a remote reader instead.
- A/B against the request rule on 67 sites, a fresh process each, the order alternating: on a fast machine
  355.2 against 356.3 s in all (p50 4.52 / 4.56), on an emulated weak laptop 489.2 against 506.9
  (p50 6.69 both); the reader's own CPU 27 % less on the fast machine and 30 % less on the weak one (relays instead of a
  Python call for every request); the same wall verdicts; no real site had a connection refused.
  The texts that differ are live pages - the request rule against itself differs on 9 of the 14.
  `--screenshots` of Wikipedia's Cat: 6.8 against 6.6 s, the same picture.
- tests: `security.py` 40 (36 on Windows; netguard through a SOCKS5 client of our own: what
  passes and what does not, a megabyte whole, forty connections at once, nothing new after
  close), `browser_live.py` 32 (the traps: a fetch, a meta refresh and a navigation through a hop,
  a WebSocket, cloud metadata, [::1], a name that resolves inside, the `--dump-dom` path, a
  machine's own proxy, and the advice when the text was dropped).

**The debug log is a file.**
- **`READ_PAGE_DEBUG=1` writes a log, not answer lines** (a model retells
  what it is shown the worse the weaker it is; a file read by whoever debugs loses nothing).
  `debug/<started>-<pid>.jsonl` in the read's folder, or every read of a test session in
  `READ_PAGE_DEBUG_DIR`; nothing in the answer or the manifest, which MCP hands to the model. One
  JSON line per event: `run` (version, flags, the machine), `caps`, `step`, `event`, `decide` (each
  rule with all it looked at: after HTTP, extraction, browser needed, browser text, status),
  `browser` (launch, page open, loaded, every poll that changed something, settled), `net` (every
  response and failure, redirect hops included), `picture`, `error` (38 places that swallowed an
  exception now say where, what and the last frames) and `summary`. A key is named, never printed;
  a query value that looks like a credential is masked.
- tests: `deadline.py` 22 (the log is a file, nothing of it in the answer or the manifest, no
  secrets in it, `READ_PAGE_DEBUG_DIR`).

**Every step on a timeline, a fairer fuse for the pictures, the browser at once for
a tiny page.**
- **`READ_PAGE_DEBUG=1`** records every step of a read as it ends (`scripts/budget.py`): when it
  started, how long it took, its own cap and the cap the deadline left it, and how it ended - `ok`,
  `cap`, `deadline`, `stall` or `fail`. The answer gets `debug:` lines (the steps, the deadline's
  use, each step that ended early and why), the manifest a `debug` block. Off by default and
  changes nothing else; it is how this check counted the fuses. (The follow-up above moved all of
  it into a log file.)
- **The check**: the version before against this one on 226 URLs on a fast machine and 113
  on an emulated weak laptop (two E-cores under a 1.03-CPU cap), a fresh process per read. The fast machine:
  p50 2.9 -> 2.1 s, p90 8.5 -> 6.6, p99 18.5 -> 15.7, max 94.5 -> 22.9; weak p50 5.5 -> 4.8, p90
  16.7 -> 11.9, p99 35.2 -> 25.3, max 57.8 -> 30.9. No status is worse once the fixes below were
  in, and every text that changed is explained (live feeds; baidu's CSS that passed for text; CNN,
  below). How often each fuse fired: HTTP, defuddle, readability, trafilatura, the site APIs,
  yt-dlp, the converters and OCR never; the browser once in 51 reads (a wall's load that never
  ended, now cut at 10 s); the pictures in 2 of 130 reads on the fast machine and 3 of 65 weak - hence:
- **Pictures get 6 s, not 4.** With no limit, 129 reads of picture-heavy pages took p50 1.1 s,
  p95 2.6, at most 5.8; 4 s would have cut 2.3 % of them (NASA's pictures still arriving, a 14 MB
  photo among them; one stuck picture), 6 s none. A connection silent for 4 s is still stuck at
  4 s, and near the deadline the phase is what the tail leaves, about 4 s, as before.
- **A tiny page with a script starts the browser at once**: under 300 characters of text and any
  script, not a 404/410/5xx. crates.io and AliExpress have two scripts, Telegram one, so the
  three-script rule for a shell missed them, and their browser waited 0.6-1.2 s on a fast machine and 2.4-3.4 s
  on a weak laptop for three extractors to find nothing. When a browser was started early, the HTTP
  pass's readability and trafilatura run once it has its page open (at most 3 s later): on a weak
  laptop they no longer take the CPU from Chrome's start, and the HTTP text is decided as before.
  (The "light" HTTP pass that skipped them for a shell is gone.) Against the code before these two
  changes, on 26 URLs: the weak profile's reads took 276.9 s in all instead of 309.5, the same
  statuses and texts; pictures were cut in 1 of 34 reads instead of 3 of 35.
- Fixed by the check:
  - a wall the browser met was refused when HTTP had only an empty shell, so the answer said
    `empty`, not `blocked` (figma): a browser wall stays out only when HTTP had a real text;
  - a news front page counted as huge and lost its article extraction (CNN: 6 MB of HTML, 1 MB
    without its scripts): huge is measured without scripts and styles;
  - HTTP overran its cap by up to 10 s on a slow server: curl itself ends the transfer at the
    step's end;
  - a host that never answered: no extraction of an empty body and no https upgrade on a port of
    its own (16.1 -> 7.9 s);
  - four processes saving cookies on two slow cores lost 2-4 of 120: Windows refuses to replace a
    file another process is reading, and the error was swallowed. The replace waits that out, the
    count is made under the lock, each writer has its own temporary file: 120 of 120;
  - a printed window's three rounds of pictures share one phase (they could take 12 s);
  - every wait on the browser is bounded: the read's own wait never runs past half the tail, a
    launch at most 20 s (Playwright's default is 3 minutes), the exit's close at most what is left;
  - a render started early and then not needed takes no screenshots;
  - no DNS lookup of every picture host before the phase (ESPN: 14 hosts, a second): a private
    address is refused, and counted, when its picture is fetched;
  - an alt with escaped brackets (trafilatura's `![Rack \[File: AP\]](...)`) left its picture a raw
    link;
  - a site's API runs without the page's own request beside it: it answered on all 16 reads, and
    that request cost the site a hit and a weak laptop CPU for nothing;
  - a `#/` route whose browser failed gets its landing page's text, not nothing;
  - the MCP server stops a read still running at 58 s (`HARD_SECONDS`) with a reason, and keeps
    an answer the read had printed before its exit hung;
  - `no time (N s)` names the phase, rounded (it said 3 s for a 3.97 s phase).
- tests: `deadline.py` 19 (the debug list; no body, no extractor), `images.py` 40 (the escaped
  alt; the slow picture now trickles past the 6 s phase), `mcp_parallel.py` 14 (the backstop),
  `browser_live.py` 23 (the tiny page and the order of its extractors).

**The printed window's pictures, the headless shell first.**
- **Every picture is numbered from the first call** - content.md's, then page.md's own - and the
  manifest lists each with its address, alt, line and state. An answer downloads the pictures of
  the lines it prints that have no file yet: the first block's, a `--from` block's, page.md's when
  page.md is printed. A long page no longer waits for all of them on its
  first read (Moscow: 146 pictures, 8.6 s against 4.5 without). A picture the 4 s phase cut, or
  the network lost, is fetched again the next time its lines are printed; a 404 or a refused address is not asked again. A counter the page sizes 1-2 px gets
  no number. `BUILD` 11.
- **The headless shell first for a text-only render** when Playwright's is installed: the A/B on
  67 sites gave the same text and walls as Chrome, at p50 4.6 against 5.2 s on a fast machine and 6.4 against
  13.2 s on an emulated Celeron. Screenshots keep Chrome.
- tests: `images.py` checks the window, the listed pictures and the retry (39).
- The page's own request runs beside yt-dlp and beside a site's API (asked from the start):
  a video read no longer waits for the watch page after the subtitles, a failed API for the page.

**Formats.**
- **RTF and OpenDocument by their content.** `{\rtf` is RTF whatever the server calls it, and
  an archive's `mimetype` file is read: an ODT is no longer taken for an EPUB (it came out `empty`).
  pandoc converts both to markdown; without it the stdlib readers keep the text (RTF escapes
  decoded, ODT headings and paragraphs in order).
- **a file on this machine** (a path or a `file://` URL) goes through the same converters with
  no network at all, and is copied, never moved. Over MCP only inside read-page's own folders.
  Another scheme, or a path that is no file, is a wrong call (exit 2).
- **`--alternate` reads a PDF with pymupdf4llm** when it is installed: headings and tables as
  markdown.
- **markitdown reads a YouTube transcript** when yt-dlp gives none; a description alone does
  not count.
- tests: `formats.py` (18); `fixes.py` checks the wrong calls the new rule leaves.

**Screens instead of tiles, rescue tiers at once, the browser started when sure.**
- **Screenshots are screens** (`scripts/screens.py`):
  `--screenshots N` counts screens of a 1280x784 window (default 2), scrolled one by one; with
  Pillow or PyMuPDF two are glued into one 1280x1568 picture, without them they come alone and
  `improve:` names Pillow. Per screen one wait (pictures, fonts, a quiet page; at most 0.6 s), a
  header bar kept on screen 1 and hidden after, other fixed or sticky elements hidden by opacity,
  reduced motion; an inner scroller is scrolled where the page uses one; PNG, JPEG q95 over 3.75 MB;
  the deadline keeps what was taken (`signals.screens`, `screens_needed`). The full-page clip took
  10-49 s a tile and left the lower pictures blank; Wikipedia's Cat, three screens: 13.2 s in all.
  PDFs come as the same pictures, two screens each. MCP: `screenshots: true` is two screens, each
  picture captioned with its screens ("screens 1-2 of 14").
- **Rescue tiers at once**: on HTTP's answer the readers and the archive start together (a dead
  host or a 5xx), the readers beside the browser (a wall's status or header), the archive for a
  404, the readers from the start with `--force-external` - each one the read would ask anyway.
  A 404, 410 or 5xx no longer goes to the browser (it gets the same answer) unless it is a wall.
- **The browser starts when it is sure to be needed**: with the read for a `#/` route,
  `--screenshots` and `--alternate`; right after HTTP for a shell or a wall, beside the extraction.
  Not for every read: on an emulated Celeron a browser launching beside reads that never use it
  took them from 5.5 to 11.9 s (p50); on a fast machine it would save 0.7 s.
- The defuddle worker numbers its pages, so the page and an archive copy extracted at once each
  get their own answer.
- tests: `browser_live.py` checks screens, gluing and the Pillow hint; `fixes.py` the PDF pictures.

**The browser waits by a measured rule, renders only text, and closes later.**
- **When a page is done** (`scripts/settle.py`), measured on 67 sites on a fast machine and on an emulated
  Celeron: the text unchanged 1 s with nothing - scripts included - in flight for 1 s in a row; or
  unchanged 2 s whatever is in flight; an error status quiet 1.5 s; an empty body 3 s, unless an
  empty mount node waits to be filled. A poll the page's scripts held back is work, not quiet.
  The fast machine: p50 5.4 s from the launch, no text lost (the old rule 6.3 s, 2 lost); on the weak laptop 3
  of 67 lost against 12. One budget of 20 s for load and settle (a weak laptop needs it: VK filled
  its page 12 s after DOMContentLoaded); the extra 5 s phase for empty shells is gone.
- **A text-only render** loads no pictures, media or fonts; **page.md** is html2text's markdown of
  the visible DOM (headings, links, pictures, tables kept) instead of innerText; the browser
  **closes in its own thread** while the text is extracted (its cookies are saved before exit).
- **The browser runs only where it can help**: a weak HTTP text *and* a script, an empty mount
  node or a wall (a static page cannot change in a browser), or a `#/` route. Its text replaces
  the HTTP text only when the HTTP text was the reason it ran, and not when it is a wall the HTTP
  text was not or has fewer words.
- tests: `fixes.py` checks the rule on recorded shapes (scripts in flight, a held-back poll, rbc's
  401, analytics, placeholders, empty mount nodes, walls).

**One deadline, extraction that cannot hold a read, a cheaper start** (55 s for every read; sized
for a weak laptop; network cut by stall).
- **Every read ends by 55 s**, the CLI and MCP alike (`scripts/budget.py`): MCP harnesses cancel a
  call at about 60 s and a cancelled call returns nothing. Each step keeps its own bound, a fuse,
  and takes no more than the deadline leaves after the tail (block rule, pictures, answer: 6 s).
  HTTP has no fixed 20 s any more: a slow but moving transfer runs until 14 s before the deadline
  (a stall is still cut by the connect timeout and the 1 KB/s floor); the browser, the readers,
  the archive, the site API, yt-dlp and the converters stop by the deadline. `--download` has none.
- **defuddle as one worker per read** (`scripts/ddworker.py`, `ddworker.js`): node loads defuddle's
  modules and warms up while the HTTP request is in flight, then answers the page, the rendered
  DOM and an archive copy with the CLI's own call - the same markdown as `defuddle parse
  --markdown`. Python makes page.md, the main block and the visible length beside it. Its limit is
  the deadline; still working then, page.md is the text (`signals.extract_late`). Measured on an
  emulated Celeron: extraction p50 4.9 -> 2.9 s, p99 20.1 -> 12.4 s; the old 10 s CLI cap had
  changed the engine on 4 of 61 long pages there.
- **readability and trafilatura side by side, in processes the read can stop** (`scripts/xchild.py`,
  the extractors in `scripts/engines.py`), only when defuddle is weak or missing, as before.
- **A page over 3 MB of HTML is its own page.md**: no article extractor; html2text and crude_text
  run side by side in processes of their own (`signals.huge`; `--alternate` still runs them all).
  The 16 MB HTML spec took 155 s and 1.2 GB; now 10.5 s. ECMAScript (7.8 MB) 55 -> 5.8 s, the Emacs
  manual (5.8 MB) 39 -> 5.1 s; content.md had come out at 95-100 % of page.md anyway. The visible
  text's script regex scanned to the end of the page for every unclosed block: one pass now (16 MB:
  2.5 -> 0.4 s; crude_text 4.6 -> 0.7 s).
- **OCR pages side by side**, under one bound (30 s) instead of 30 s a page.
- **A cheaper start**: a tool's path is looked up once per process (13 Windows PATH walks a read),
  urllib's openers - and the system certificate store - load on first use, and curl_cffi is
  imported without markdownify, bs4 and readability (it pulls them in for a method this skill
  never calls; 0.2 s).
- **MCP keeps one warm process** for the next call (`readpage.py --serve-once`): Python started and
  the imports done; it serves one call and exits, and a new one starts as it is taken.
- **Playwright's current Chromium is found**: `browsers()` looked for `chrome-win/`, `chrome-linux/`
  and `chrome-mac/` only; current builds are Chrome for Testing (`chrome-win64/`, `chrome-linux64/`,
  `chrome-mac-arm64/...`). The headless shell is listed last.
- tests: `deadline.py` (15 checks); `timeouts.py` checks the cut PDF against the deadline.

**Speed, locks, MCP.**
- **A cached answer asks nothing about the machine**: `caps()` ran before the cache check
  and cost 0.3 s of the 0.6 s a hit took; a hit is 0.3 s now (Python's start and import are the
  rest). On a miss `caps()` is kept for an hour in `caps.json` and asked again the moment PATH, a
  PATH folder, site-packages, the Python or the tessdata folder changes - an install is seen at
  once, which is what the old day-long cache got wrong. The setup report and `--caps` ask fresh.
  Each tool name is looked up once, not twice (19 PATH walks were 11).
- **Locks**: a site's cookie jar is read, merged and written under a file lock (msvcrt or
  fcntl, never longer than 5 s): four processes saving 120 cookies of one host lose none. A page
  folder is locked for a read, so a second call for the same page waits and gets the cached answer
  instead of writing the folder at the same time.
- **A killed run's `.part` files are gone at the next start, in `img/` too**.
- **The disk floor**: a download stops when less than 1 GB is free - the spool looks
  at the free space when the body first goes to disk and every 64 MB after, curl gets
  `--max-filesize`; the part is deleted, the status is `error` with the reason and advice.
- **MCP calls run at once**: each `read_url` is `readpage.py` in a child process, four at a
  time, its answer written whole under a lock; four pages of 2.5 s answer in 4.2 s.
  `notifications/cancelled` kills the call's process tree (0.3 s) and the call never answers; on
  Linux and macOS readpage gets SIGTERM first and kills curl and the converters itself, since they
  run in sessions of their own (found on WSL: the page kept trickling to an orphaned curl).
  The curl channel also refuses to start a `--download` when the disk is already under the floor.
- **MCP pictures**: `inline_images` attaches only content pictures - not the
  same picture 3+ times, 48 px or less, 1 KB or less, nor a logo, icon, avatar or badge of 100 px
  or less - each right after its marker, several on one line too. PNG or JPEG only; a long side
  over 1 568 px is scaled; a PNG over 3.75 MB becomes one JPEG at q95; screenshots asked for go
  first, then the biggest pictures, while the answer stays inside 25 000 tokens (the text plus
  `ceil(w/28)*ceil(h/28)` and 150 for the path line a picture costs), 256 pictures and 20 MB. A
  picture that did not fit keeps its marker and a note counts it. Pillow converts (GIF, WebP,
  AVIF, BMP) and scales, PyMuPDF renders SVG; the setup report has a `pillow` row.
- tests: `speed.py` (8 checks) and `mcp_parallel.py` (12), both in CI; `mcp_smoke.py` and
  `setup_audit.py` follow the new contract.

**Pictures and where they live.**
- **Every picture of the text is a numbered marker in its place**:
  `[img #3 · 100x80 3K · Diagram of the flow] img/03-diagram-of-the-flow.png` - the number is the
  file's (`NN-` and words from the alt, the address or `image`, Cyrillic in Latin letters), the alt
  stays inside the brackets, the path comes last. It is the last step on any path: an extractor's
  text, a block put back from page.md, a reader's, the archive's, a site's API (an X post's photos),
  a video's cover. A picture that was not downloaded says why and keeps its address
  (`not downloaded: 404`, `no time (4 s)`, `--deny-images`). In one answer a repeat prints as
  `[img #3]`, a tiny one with a short alt as the alt; content.md keeps every marker full. Replaces
  `[12x12 7Kb] img/pencil.png`, `[image] name.png` and the all-or-nothing `## Pictures` list.
- **Pictures follow their blocks**: a picture block next to the shown text goes
  back where it stood; a picture the extractor took out of a paragraph it kept goes back right
  after the paragraph. A picture beside a menu or a footer stays out, and so does one whose alt
  reads like a banner ("Follow us"); a menu entry with a picture is a menu, not a captioned figure
  (GitHub's header promos, pkg.go.dev's icons), and a picture wrapped in a link to its full size is
  still a figure. Only a block of five words or more vouches for the picture beside it: Wikipedia's
  logo sits next to a "Search" link. On the 61 offline corpus pages the extractors keep 260
  pictures, the rule adds 141 (Wikipedia's figures, the Joel Test's own pictures), 310 stay only
  in page.md. page.md keeps its pictures now (html2text no longer strips them
  and no longer wraps lines, which could split a link); trafilatura keeps them too; a lazy picture's
  `data-src` replaces its placeholder for every extractor; tracking pixels are shown nowhere.
- **What is downloaded follows what is printed**: the text's pictures within 4 s;
  page.md's when page.md is printed (`--file page.md`, a fragment, MCP `file`) - also from the
  cache or a continuation, the lines do not move; every picture of the page with `--download`.
  `--deny-images` names them all, and a later read without it fetches them for the cached text with
  no new read of the page. `signals.images_outside` counts the page's other pictures.
- **Documents**: a DOCX or PPTX picture stands where the paragraph or the slide has it; pictures a
  document does not place are listed after the text in document order, ten lines at most.
- **Storage**: a page folder starts with its host, `pages/<host>-<key>`; a picture
  another page of the same host already has is a hard link to that page's file (a copy where the
  file system has no links), with no request: `signals.images_reused`, `images[].reused`. Deleting
  one folder never breaks another. The 7-day host picture store is gone (old ones are removed);
  the host folder keeps the cookies. `BUILD` 10: a 0.4 cache entry is not served.
- A marker's path ends clean: a picture inside a link is `marker (link)`, a caption glued to it
  starts a new line, a table's `|` gets a space. Two pages read into one `--dir` keep their own
  `01-logo.png` (the second is `01-logo-2.png`). A 304 keeps the file and says `revalidated`.
- The manifest's `images` lists the text's pictures in order with `n`, `in`, `why`; the schema
  describes every field.
- tests: `images.py` (34 checks, in CI). `props.py` and `fixes.py` moved to the new contract;
  `harness.run_read` finds the folder of a read in a shared cache.

**One wall, one credit.**
- **A paid reader that met the wall ends the paid part of the chain.** Firecrawl, Exa or Tavily
  reaching the page and finding its wall (or a 401/403/429/451) means the next paid reader would
  meet it too: in measurements Exa and Tavily never gave text where Firecrawl and the free Jina did
  not, and Amazon's wall cost three credits. The free readers are still asked; a paid reader that
  failed for its own reason (no credits, a timeout) is still replaced by the next. The note says
  `exa: not asked, firecrawl met the wall`. tests: `sources.py` 33.

**Sources.**
- **The readers are one chain, in the measured order**: Firecrawl, Jina, Exa,
  Tavily, defuddle.md (14 hard pages: 11, 8, 10, 7 and 4 opened; Exa third so its credits go to
  search). A reader without its key is skipped, so without keys it is Jina, then defuddle.md. The
  first real text ends the chain - no credit is spent after it; a wall, fewer than 40 words, the
  service's own error (`402`) or 12 s without an answer moves on; a `404` a reader saw ends it. Each
  key goes only to its own service; `JINA_API_KEY` is sent when set. Exa gets `livecrawl` and
  Firecrawl `maxAge: 0` on `--refresh`. defuddle.md's YAML front matter goes, its title stays. The
  setup report and `caps.keys` list all four keys.
- **A site's own API where the ordinary path fails** (`scripts/siteapi.py`): a Stack
  Exchange question (the question and up to 10 answers by votes), an npm package (the version's
  2-4 KB document and the README streamed out of its tarball - the registry's whole document is
  7-15 MB for react or typescript and has no README for them), a Hacker News item (the story and
  30 top comments, fetched in parallel), a post on X (fxtwitter, which gets only the post number,
  not the account or the query). No flag; 10 s; a failure reads the page as before and
  `chain.tried` says `api:<site>:failed`. Engine `api:<site>`, the JSON in `raw.json`.
  `--alternate` and `--screenshots` skip it.
- **What the extractor dropped goes back** (`scripts/blockrule.py`): a block of
  `page.md` that the text lacks - prose, code, a table, a captioned figure, and the heading over
  them - goes in after its kept neighbour. Menus, link lists (also as a browser's plain lines, and
  layout tables of links), fragments and cookie banners stay out. The header says
  `defuddle + 4 blocks of page.md` and `outside the text: 2.6 KB of menus, links and fragments -
  page.md`; `content.restored`, `restored_bytes` and `outside` in the manifest. Python's tutorial
  gets 3.1 back; on a measured corpus 23 of 60 pages change, +2.1 % on the ordinary ones, and RFC
  9110 goes from 5.5 KB (trafilatura) to 374 KB.
- tests: `sources.py` (31 checks, in CI: the order, the keys, what moves the chain on and what ends
  it, the bounds, each adapter on a local API and its fallback), `blocks.py` (18 checks, in CI;
  every paragraph, code block and table of `page.md` in the text exactly once); `sources_live.py`
  runs the same against the real services (20 checks, by hand, spends a few credits). A CLI test
  never sends the user's keys: `harness.run_read` drops them.

**Reading.**
- **Encodings a server forgot to say**: a BOM first, then the header (latin-1 and ascii count as
  unsaid - servers send them by default), `<meta>`, UTF-8, each kept only when the text reads like
  its script; then the bytes (`charset_normalizer`); then a repair guess. windows-1251 never raises an
  error, so it used to win every guess: KOI8-R, Shift_JIS, GBK, EUC-KR and UTF-16 came out as
  mojibake or `empty` (UTF-16 even counted as binary for its zero bytes). Ten cases, all right now.
- **A `#/` or `#!` route goes to the browser**, and its text wins over the landing page the server
  sends for every route.
- **"Settled" means done**: the text has not changed for 0.8 s, no script/XHR/fetch is in
  flight, the main node is neither empty nor "Loading...". A static page whose mount node is empty
  or a placeholder starts the browser however long its menu is. Content 0.8 s and 3 s late is read.
- **A dead host or a 5xx with `--allow-external` goes to the readers, then the archive**:
  "a host that never answered is not a wall" kept dmoz.org and lib.ru unread; with the readers'
  20 s bound it costs at most that. A rescued page is `ok` with a note saying which tier gave it.
- **One more try on 502/503/504** inside the HTTP step, a second later.
- **Only a video's own address takes the subtitle path**: `vimeo.com/about` and `tiktok.com/about`
  were `empty`. A video without subtitles is read as a page, `signals.no_transcript` says why.
- **Jina by POST**: the address in the body keeps `#/` routes and Cyrillic paths (a GET lost
  the route and failed with an `'ascii' codec` error); a "cached snapshot" is asked again with
  `x-no-cache`; a wall Jina met is not text.
- **No curl and no curl_cffi: urllib reads the page** with the same redirect checks and bounds;
  "the host did not answer" was said when nothing had been asked.
- **defuddle gets the page's address** through a `<base href>`: relative links were
  `about:blank/...`. The extractors get the final address after redirects.
- tests: `reading.py` (12 checks, in CI); `browser_live.py` gains the hash-route and late-JavaScript checks (21).

**Timeouts.**
- **Every step has its own bound, and there is still no whole-run deadline.** HTTP 20 s for all its
  attempts (fingerprints, plain curl, the https upgrade); browser 20 s; readers 20 s (12 s each,
  the next only while time is left); archive 20 s for the CDX lookup and the snapshot together, once
  per run; converters 10 s; OCR 30 s a page; pictures 4 s; `yt-dlp` 20 s. Worst case on a wall with
  `--allow-external` ~105 s instead of ~228 s - under the 120 s an agent's shell waits by default.
- **A trickle ends**: `stream=True` made curl_cffi's read timeout mean "less than 1 byte a
  second", so a page that dripped 22 bytes a second held the call for 154 s. Now below 1 KB/s for
  10 s in a row the transfer is cut (curl too: `--speed-limit`/`--speed-time`), and the step's end
  cuts a faster trickle; what arrived is kept with `partial`. Measured: a trickle ~12 s, a stall after
  half a page ~16 s with the half kept. A cut transfer does not start the browser: it would wait for
  the same slow server.
- **One browser**: channels were listed whether installed or not (ten "browsers" on a machine
  with two) and Chrome came twice, as a channel and as its own path. Now a browser is listed once,
  only when its program is on disk, and a second one is tried only when the first fails to start -
  a page one Chromium cannot render, another cannot either.
- **A dropped connection is tried once more** on a new one (an empty reply or a reset), and an
  `error` always has advice: check the address, try again in a minute (a failure is not cached), or
  the flag that would try a reader or the archive.
- **A cut document says why**. Still arriving when the 20 s ran out: `too_large`, "the
  PDF was still arriving when 20 s ran out: 160K of 1.9M", advice `--download`. The server stopped
  sending, or the connection broke: `error`, "the server stopped sending the PDF after 12K of 195K"
  - a document stuck at 1 KB is not "too large". A PDF needs its last bytes and a cut ZIP is not
  mended (that is deferred); HTML, text and JSON are kept as they arrived, and the advice names the
  cause (stopped sending, the step ran out, the connection broke).
- **What arrived is kept on every bound**: the HTTP body on both channels, the browser's DOM on a
  load timeout, a slow Jina reader's text and a half-arrived archive snapshot (both `partial`). OCR
  names a page that did not finish (`signals.ocr_timeouts`, a marker in the text) instead of a
  silent gap; a yt-dlp out of time says so instead of "no subtitles". Pictures in flight are counted
  (`images_truncated`); a converter out of time leaves the page to the other extractors. When a
  later tier's text replaces a cut HTTP text, its `partial` no longer describes the answer and goes.
- the pictures the text shows are fetched first, so 4 s go to the diagram the article talks about,
  not to a front page's logos.
- tests: `timeouts.py` (15 checks, in CI on every OS); `fixes.py` patches the new bounds.

**Honest statuses.**
- **`ok` needs a successful answer from the tier whose text it is.** The code of that tier decides:
  401/407 → `login_required`; 403/419/429/451 → `blocked`; 404/410 → `not_found`; any other 4xx
  or 5xx → `error`, with the server's own page kept as the text and `reason: HTTP 503 from the
  server`. Before, `/500`, `/503` with text, httpbin's 400 and Hacker News' 419 ("Sorry.") were all
  `ok`. A 403 from the server and a 200 from the browser is `ok`: the browser's text counts.
- **Rotation on any refused 4xx** (not only 403/429), then **plain curl once**: Hacker News answers
  419 to every browser fingerprint and the page to curl.
- **Walls without words first, then in twenty languages** (en, ru, uk, de, fr, es, pt, it, nl, pl,
  cs, tr, sv, ja, zh, ko, ar, hi, id, vi): a `cf-mitigated: challenge`, `x-vercel-mitigated` or
  `x-amzn-waf-action` header; Cloudflare, DataDome, PerimeterX, Imperva, AWS WAF or Anubis markup on
  a short page; then the phrases, folded (no case, no accents), counted in the title, the first
  heading or the first lines of a page under 300 words, or anywhere on a page under 40. "Just a
  moment" counts only when it is all the title says. An article that quotes the wall stays `ok` in
  every language, and so does "Access denied: a short history of paywalls". Anubis and X's
  "Something went wrong" are walls now. Chinese and Japanese are counted by character.
- **The browser's own page is never the text**: `chrome-error://`, "This site can't be
  reached", "HTTP ERROR 503" - `signals.render_error` names it, the browser's text is dropped.
- **A cut transfer says so**: a timeout or a broken connection sets `signals.partial` (it
  never did: `nonlocal` was missing), the first line says `partial`, the advice names `--refresh`
  and `--download`; a stub of a few words is `error`, not a page.
- **Only answers are cached**: `ok`, `media_only`, `not_found`, `login_required`. A network
  failure, a wall, an error page or a stub is read again on the next call instead of being served
  for 15 minutes.
- **No `data:` payload anywhere**: `content.md`, `page.md`, the answer and the manifest
  carry `data:image/png;base64,<81K sha1:3f2a9c1b>` instead of a megabyte of base64; an inline
  picture is saved as `img/inline-<hash>.png`, and `--deny-images` names it the same way.
- an archived copy goes through the same type detection as a live answer: a PDF in the
  archive is read as a PDF, not decoded as HTML; `too_large_out` exists, so a body over the cap
  is `too_large` with the cap named instead of a `NameError`.
- schema: `signals.partial`, `render_error`, `external`, `external_status` (written before, never
  declared).
- tests: `statuses.py` (35 checks, in CI on every OS), `browser_live.py` gains the check of the browser's error page (18).

**Security.**
- **Only http(s), on every hop**: a redirect, a picture, a meta refresh or a browser request to
  `file://`, `ftp://` or any other scheme is refused, private page or not; curl also gets
  `--proto =http,https --proto-redir =http,https`. Before, a URL that looked private could redirect
  anywhere: `/f/abc123def456gh` → `file:///…` put a local file into the answer, and
  `<img src="file:///…">` on such a page was copied into `img/`.
- **Two rules instead of one heuristic.** `host_is_private()` is the network rule: only the host
  decides - an IP literal in any form, an internal name, or a name that *resolves* to an internal
  address (`localtest.me`: loopback, RFC 1918, CGNAT, link-local, ULA - not 198.18.0.0/15, which a
  fake-IP proxy such as Clash answers for every name); a public page never reaches the local network. `url_has_secret()` is
  the reader rule only: credentials, a credential-like query key, a sharing or reset link, an
  opaque run of 32+ characters (measured: 1.2 % of 249 public URLs flagged, 11 of 11 secret shapes
  caught; the old token rule flagged 22 %, `python3-tips` and `oauth2-server` among them, which
  also switched off the TLS channel and the readers for them).
- **`--force-external` never sends an internal host**: the reader could not open it;
  the manifest records `privacy.conflict: ["force_external refused", "internal host"]` and the
  local result stays. It still sends a URL that may carry a secret, recorded as
  `["force_external wins", "secret heuristic ignored"]`; `--allow-external` keeps such a URL local
  and the advice names `--force-external` instead of repeating the flag that was just ignored.
- **The browser stays out of the local network**: on a public page every request is routed and
  one to an internal host or a non-web scheme is aborted - scripts, frames, meta refreshes,
  WebSockets; service workers are blocked so nothing slips past the route.
  `signals.browser_blocked` counts them.
- **Referer is the origin** (`scheme://host[:port]/`), as a browser sends it to another site; an
  internal page sends none to an outside host, and https never tells http. Before, a picture retry
  after a 403 sent the full page URL, `?token=` included.
- Chrome run without a browser library gets a throwaway `--user-data-dir` (it wrote a profile into
  HOME); a server's `Content-Disposition` name never replaces a file in the folder or one of ours
  (`victim.txt` → `victim-2.txt`, `manifest.json` → `manifest-2.json`).
- **The cache is the user's own**: `<tmp>/read-page-<uid>`, 0700, files 0600 (umask during a read);
  a folder of that name that is a link, belongs to someone else or cannot be closed is not used -
  the run takes a fresh `mkdtemp` folder. Windows keeps `%TEMP%/read-page`, already per user.
- schema: `privacy.conflict` is a list of strings (it always was in the code), `signals.browser_blocked`.
- tests: `security.py` (32 checks on Linux, 28 on Windows where the POSIX cache checks are
  skipped) in CI on every OS; `browser_live.py` gains two checks of the browser's guard (17); `fixes.py` and
  `channel.py` follow the two rules. Known: DNS rebinding and Chrome's `--dump-dom` without a
  browser library stay open (KNOWN-ISSUES 51, 52).

**The output contract.**
- **The answer is printed, not the manifest**: a header (status, engine and `cover` as "87% of the
  page", the date of an archive copy, which file and how big, `from cache`, `fragment`, seconds;
  then `url:`, `reason:`, `files:`, `advice:` and at most two `missing:`/`improve:` lines), then the
  text. One answer is at most **9 980 bytes and 495 lines**, counted on what is written (UTF-8, LF,
  stderr included): Codex passes 10 000 bytes to a non-OpenAI model, Roo Code 10 240, Cline 500
  lines, and each cuts the rest differently. A text that fits comes whole; a longer one gets an
  outline (headings with line numbers, levels dropped until it fits 2.5 KB; without headings, one
  row per block), the first block cut at a paragraph, and `── next: line N of T → the same command
  with --from N --file content.md ──`. `scripts/answer.py` holds it; the CLI and the MCP server both
  call it.
- **`--from N`** prints the block that starts at line N of the same file from the saved copy, with
  no network; past the last line it says so. When there is no saved copy (or with `--refresh`) the
  page is read again and a `note:` line says the lines may have moved. **`--file page.md`** answers
  with the whole page; a fragment answers with `page.md` by itself. **`--json`** prints the manifest
  as before. A `--from` without `--file` (and an MCP `read` without `file`) goes on in the file read
  last (a `--file` switches it), kept in the manifest, so a forgotten flag never switches texts under the
  line numbers; the pointer still names the file.
- **Exit codes**: 0 whenever an answer is printed, whatever its status (`login_required` was 1); 1
  an internal error, said on stdout; 2 a wrong call (unknown flag, a URL that is not http(s)), said
  on stderr - a `file://` URL was a status `error` manifest.
- **One name per action**: `--allow-images` and `--print` are gone (pictures are on by default, the
  answer is the text), `--screenshot` is `--screenshots`, abbreviations are refused, so an old flag
  fails loudly. MCP: `read_url` lost `allow_images` and gained `file`/`from`; `read` takes `dir`,
  `file`, `from` - `offset`/`limit` are refused. `TEXT_LIMIT`, `--print`'s 24 000-character crop,
  `parts/` and `content.parts` are gone.
- **No line longer than 1 998 characters** (2 000 with CR LF; or 6 000 bytes) in
  `content.md`/`page.md`: a longer one is cut after its last sentence end that fits (`。！？` need no
  space after them), else at a space, else exactly at the limit; table rows and code lines too, and
  every piece is kept. Claude Code's Read, OpenCode and Kimi CLI drop the rest of a longer line. A
  raw file read through MCP keeps its lines; a line longer than a whole answer (a minified page)
  shows its head and says how much was left out.
- stderr is empty on success: library noise goes to `<cache>/stderr.log` (kept under 1 MB) unless
  `READ_PAGE_TRACE` is set; stdout is UTF-8 with LF on every OS.
- an early exit (a cap hit before any text) now has its `status_reason` too, so every status but
  `ok` prints a `reason:` line; the `files:` line names only the files that exist.
- the 15-minute cache counts from the read (or a `304`): showing a cached copy - a plain repeat, a
  `--from` block or a picture top-up - used to restart the clock, so a page read block by block
  never went stale. `--refresh` still restarts it, after a `200` or a `304`.
- tests: `contract.py` (73 checks: budget on English, Russian, Chinese and heading-less pages, the
  blocks put together equal `content.md`, outline rows are real headings, `--from` with the server
  gone and with no saved copy, `--file page.md` going on in page.md, the cache age through repeats,
  `--from`, a `304`, a changed page and expiry, exit codes, line cuts in English, Chinese, a table
  row, a 5 000-character token and four-byte characters, MCP `read_url`/`read`/`from`); in CI on
  every OS. The other suites read the manifest with `--json`.

## 0.4.6 - 2026-11-02

- **`--screenshot [N]`**: the page as images for a vision model, when there is no text to read.
  1280 px wide, tiles of 1568 px tall, **nothing scaled** - 1280 is the width pages are laid out for
  (measured: ten sites, none needed a horizontal scrollbar, text column 750-960 px) and 1568 is what
  a vision host keeps. Chromium captures each tile from the full page (`full_page` + `clip`), so a
  60 000 px page needs no stitching; fixed/sticky overlays are hidden and animations frozen.
  PDFs are rendered by pymupdf into the same tiles; archives say they have no pages.
  Manifest: `screenshots`, `files.screenshots`, `signals.screenshots`,
  `signals.screenshot_tiles_needed`, `signals.screenshots_format`, `signals.screenshot_unsupported`;
  MCP: a `screenshots` argument and one captioned image block per tile.
- tests: five offline checks (mode key, no browser, PDF tiling, last tile shorter, missing browser
  named) and nine live ones across CLI and MCP, including "an independent decoder (MuPDF) opens
  every tile"; `browser_live.py` is 15 checks now.
- a **block page keeps its words**: extraction used to be skipped for a wall, so when the browser
  tier then failed the answer was empty even though the page itself said "Just a moment...".
  Only a JavaScript shell (no text by definition) skips extraction now.
- a caller that asked for fewer tiles than the page has is told so: the MCP header says
  `1 image(s) of 2 the page has` and the caption reads `screenshot 1/2`, not `1/1`.
- measured on 14 real pages: median 4 tiles needed (1-18), five pages fit in one; the default
  stays one tile on purpose (a scan page or a canvas app is one screen, a long article is not).
- CI: macOS moved to its own nightly/dispatch workflow (`macos.yml`) after GitHub cancelled macOS
  runners under capacity pressure on three pushes in a row; push runs are ubuntu (3.9, 3.12) and
  windows, plus the browser job on both.

## 0.4.5 - 2026-11-02

- **an EPUB keeps its picture order**: the spine of the package document says which
  chapter comes first, and every `<img>`/`<image xlink:href>` inside it is ranked by
  that, so `order` in the manifest and the MCP image blocks follow the book instead of
  the archive. Closes the last `partly` in `KNOWN-ISSUES #5`.
- the Linux wrappers are tested instead of assumed: CI fabricates `/snap/bin/chromium`
  and the flatpak export with `sudo`, and `tests/setup_audit.py` asserts the browser
  detector finds them (the last open half of #20; a real desktop launch is what is left).

## 0.4.4 - 2026-11-02

- **no URL means the setup report**, not an error: `readpage.py` with no arguments lists what this
  machine can already do, what is missing (each line: what it buys and the command to install it),
  and both keys, then exits 0. The skill still installs nothing - it names, the user decides.
- a shell that is still empty after the browser budget gets a **second chance that watches the
  text**: 5 s in total, 1.5 s for requests still in flight plus 3.5 s polling the body and the usual
  mount nodes (`#app`, `#root`, `#__next`, ...). Closes the rest of KNOWN-ISSUES #12; the manifest
  records `signals.browser_waited` (`networkidle`, `mount:#app` or `body`).
- `signals.browser_waited` added to `references/manifest-schema.json` (the contract, `BUILD` stays 8).
- **one session for every engine**: the stored jar is handed to the headless browser (a members-only
  page that only renders for a logged-in session read `empty` before, `ok` in 4.3 s after) and to
  `yt-dlp` (`--cookies`, members-only videos); a cookie the page sets in JavaScript goes back into
  the same jar. Measured with a local gate: `status=ok, 1596 chars, signals.cookies.sent=1` against
  `status=empty, 7 chars, sent=0` before the fix.
- the setup report is a **table**, not a list of strings: `setup_rows()` is the single source
  for what the skill detects and what it recommends, the install command follows the OS
  (`winget` / `brew` / `apt`), `readability` and `lynx` are finally recommended (they were used
  but never named), and two dead detections (`markdownify`, `youtube_transcript_api`) are gone.
- **tests/setup_audit.py**: the advice is tested in both directions on synthetic machines -
  nothing missing goes unnamed, and nothing installed is still asked for. It caught three real
  defects: `readability` never recommended, a `curl` row that did not match the detected name,
  and an `ocr-langs` row that claimed to work on machines without tesseract.
- **tests/browser_live.py**: the browser tier is now proven against local servers - a shell
  that mounts in 250 ms, a shell that mounts after the 10-second budget, and a members-only
  page that renders only with the stored session (6 checks).
- CI runs that browser suite on **ubuntu, windows and macOS**, alongside the offline suites on
  ubuntu 3.9/3.12, windows 3.12 and macOS 3.12; the bundled Chromium is found where macOS keeps
  it (`~/Library/Caches/ms-playwright`).
- README rewritten around what the tool is for: one call, an honest receipt, the numbers.
- **a unicode folder no longer breaks the plain-curl tier**: `curl.exe` receives argv in the ANSI code page, so `-o`/`-D` pointed at a Cyrillic path failed with status `000` and no error text at all. curl now runs inside an ASCII staging folder with relative names and Python moves the body into place (`KNOWN-ISSUES #45`). A curl exit with no HTTP status is reported as `curl exit N` instead of an empty status 0.

## 0.4.3 - 2026-11-01

A production-hygiene cut: no new tier, no manifest shape change (`BUILD` stays 8).

- a video transcript keeps its **timestamps**: cues are grouped into blocks of up to 30 seconds and
  each block starts with `[0:18] ...`, so a claim can be cited by time. The untouched cue file is
  copied to `transcript.vtt` next to the text.
- `--version` prints the skill version, the manifest schema and the cache build.
- OCR language packs are checked instead of assumed: `--caps` lists them (`ocr_langs`), a requested
  pack that is missing is reported (`signals.ocr_missing_langs`) and named in `improve[]` with the
  file to install, while OCR falls back to the packs that exist.
- the per-host picture store no longer doubles the disk: it hard-links the page's own file, and a
  reused picture is linked into the page folder (measured: 10 pages x 6 shared pictures = 0.4 MB,
  store 0 bytes).
- `references/video.md`: what a real "video understanding" needs (ASR, frame OCR), what was
  rejected (a vector index inside a CLI) and what is still undecided.
- `--caps` is no longer cached for a day: it is the command people run right after installing a
  language pack or `curl_cffi`, and the cache made it lie. ~150 ms, once per run.
- `references/manifest-schema.json` publishes the manifest contract, and `tests/props.py` validates
  every manifest the suite produces against it (unknown keys fail), so the file cannot drift.

## 0.4.2 - 2026-11-01

A cookies-and-honesty release. The cookie jar shape and the cache key change: `BUILD` 8 (old page
entries are ignored, old cookie jars are still read once and rewritten).

**Cookies that behave like cookies**
- every entry now carries the `Domain` it was set for and its own expiry; a cookie set for
  `example.com` is also sent to `app.example.com`, a host-only cookie stays on its host, and an
  expired or `Max-Age=0` cookie is dropped instead of lingering until the TTL.
- a cookie is stored under the host that *set* it, not under the URL the run started from
  (`http -> https`, `example.com -> www.example.com` used to lose it).
- the two HTTP tiers share one jar: the plain-`curl` tier gets it as a netscape file and its answer
  is merged back, so a session survives a fingerprint fallback.
- two runs on one host merge instead of overwriting each other's cookies.
- picture requests send the site's jar (hotlink protection by cookie now works). `signals.cookies`
  reports how many were sent and stored.
- a wall that may be our own stale session says so: the advice names `--clear-cookies`
  (renamed from `--fresh-session`; `fresh_session` in MCP is now `clear_cookies`). `--refresh`
  still keeps cookies. No legacy alias is kept: the flag is `--clear-cookies` only.
- `Path` and `Secure` are honoured: a cookie scoped to `/app` is not sent to `/other`, and a
  `Secure` cookie never travels over plain http (the plain-`curl` tier is handed a pre-filtered
  file, so curl's own jar reader cannot disagree).
- cookies set by the `curl_cffi` tier were never stored: `r.cookies` iterates *names*, so the old
  loop found no attributes and the exception was swallowed. The cookie objects live in
  `r.cookies.jar` and are read from there now.

**Redirects, names, politeness**
- a `<meta http-equiv="refresh">` stub is followed (one hop, checked for a private target,
  recorded in `signals.meta_refresh`). Such a page used to come back as `empty`.
- a downloaded file takes the server's name from `Content-Disposition` (`filename` and
  `filename*`), so `/download?id=7` gives `report-2026.pdf` instead of `raw.pdf`.
- `robots.txt` and `X-Robots-Tag: noai` stay unread, as decided; `SKILL.md` and `README.md` now say
  so explicitly instead of staying silent.

**Extraction**
- `cover` and `fragment` are counted in **words** again, not characters: the visible text is
  stripped of tags and scripts and compared word by word. On the 30-URL corpus 11 cover values
  moved (wikipedia 1.0 -> 0.871, tailwind 0.382 -> 0.448) and no fragment flipped.
- a candidate text is scored `words + 2 per heading`, so a structured article is preferred over a
  slightly longer pile of leftovers (a comments section used to win on length alone). The chosen
  engine did not change on the corpus, and the 12-URL comparison stays 12/12 with 0 silent losses.

**Pictures**
- a site's shared pictures are fetched once per host: `hosts/<host>/assets.json` maps a picture URL
  to the file the host already served, and later pages of the same site take it from there.
  Measured: 10 pages x 6 shared pictures = 6 requests instead of 60. `--refresh` bypasses the
  store for a URL it already knows (so a changed picture is noticed), reuse is reported in
  `signals.images_reused`, and the store is pruned at 7 days.
- a docx keeps its picture order: `document.xml` is parsed for the flow of `a:blip` references
  (resolved through `document.xml.rels`), so the MCP image blocks come in reading order even when
  the archive stores them differently (`order` on each entry, `signals.images_ordered`).

**Documents and MCP layout**
- a scanned PDF is now read: if `tesseract` is installed, the rendered pages are OCR'd and the
  text comes back as `document:ocr` (`signals.ocr_pages`, `signals.ocr_langs`; `READ_PAGE_OCR_LANGS`,
  `READ_PAGE_TESSDATA`). Without tesseract the answer still says what to install. Measured on a
  synthetic scan: "SCANNED REPORT / Total 42 units" read back correctly; the Russian page reads
  back "СКАН-ОТЧЁТ № 42 / Итого: 42 единицы" with `READ_PAGE_OCR_LANGS=rus+eng`.
- a scan is recognised on the `pdftotext` path too, so a machine without pymupdf reports
  `no text layer` and the `ocr` hint instead of a bare `empty`.
- page-specific hints (ocr, browser, video) come before generic "install curl_cffi" lines: the
  list is truncated at three and a scan used to lose its own hint.
- MCP: a picture's caption line (`[240x160 7Kb] img/one.png`) is its own text block right above the
  image, so text and pictures now alternate as paragraph -> path -> picture. Verified by eye on a
  page with numbered pictures and on `wikipedia.org/wiki/Cat`.

**Browser waiting**
- one 10-second budget per browser covers loading *and* settling: a page with stable text returns in
  ~0.3 s, a JavaScript shell is waited for until the budget runs out, something that paints at 12 s
  is dropped as `empty` on purpose. Previously the settle window was a flat 1.5 s.

**Smaller**
- pictures are named even when the extractor dropped every `<img>` (trafilatura on a machine
  without defuddle): the files are listed at the end of `content.md`, and the MCP server attaches
  them from the manifest instead of returning a text-only answer.
- a child process that spawns its own children no longer defeats the timeout: the whole process
  group is killed, so a hung converter or browser cannot hold a call open (68 s -> the configured
  bound on a trickling page).
- WSL: the inherited Windows PATH is ignored for tools and browsers. `which defuddle` used to
  return the npm shim under `/mnt/c`, and every read paid the full 20-second converter timeout.
- a crashed run now prints `url.requested`, `dir` and `signals.status_reason`, so the MCP server can
  still read the folder it left behind.
- `run_tool` is covered by a test: argv everywhere, a shell only for `.cmd`/`.bat` on Windows, and a
  URL with shell metacharacters never reaches a command line.
- `KNOWN-ISSUES.md` rewritten: 35 rows with honest statuses, the rejected ideas recorded as
  decisions, the `robots.txt`/credit-counter/one-module questions closed by decision.
- the installed set is listed in `README.md`.

## 0.4.1 - 2026-10-31

A session and cache follow-up. No manifest shape change: `BUILD` stays 7.

- cookies live in one folder per host for 6 hours by default (2-24 h via
  `READ_PAGE_COOKIE_HOURS`), shared by every page of that host; a same-name cookie is replaced,
  a cookie returned with an empty value is deleted. Nothing accumulates past the TTL.
- `--refresh` means "the page answer may be stale", not "start a new session": it no longer
  clears the host's cookies. `--fresh-session` (CLI) / `fresh_session` (MCP) is the explicit reset.
  Documented in `SKILL.md`, `README.md` and `references/mcp.md`.
- the one Russian code comment is translated; the multilingual login markers stay, because they
  are matching data, not prose.

## 0.4.0 - 2026-10-31

A correctness and safety release: the contract now holds under flags, private URLs, hostile pages
and MCP edge cases. `BUILD` 6 (the cache key changed, old entries are ignored).

**Cache and flags**
- one URL keeps one folder (`sha1(url|BUILD)`); the flags that produced an answer live in the
  manifest (`_mode`), and a cached answer is *served* only when they match. `--allow-external` and
  `--alternate` re-read in the same folder instead of returning the old blocked answer.
- `--allow-images` after `--deny-images` reuses the cached text and only adds the pictures (one
  local pass; the page is not fetched again).
- `--dir DIR` is honoured on a cache hit: the artefacts are copied into DIR and `dir` points there.
- `missing[]`/`improve[]` are reported on a cache hit too (the MCP header used to hide them).

**Privacy and safety**
- no flag lifts the private-URL rule. `--force-external` means "do not prefer the local text"; for a
  loopback/RFC1918/credential-bearing URL it is still refused and `privacy.why` says so.
- the `blocked` advice no longer tells the agent to repeat `--allow-external` on a private URL.
- `looks_private()` rewritten: `ipaddress`-based (IPv4/IPv6, loopback, link-local, CGNAT, reserved,
  IPv4-mapped), integer/hex/octal hosts (`2130706433`, `0x7f000001`, `0177.0.0.1`), `localhost`,
  metadata names, private suffixes, credentials in the authority, token-like path segments.
- pictures are checked too: a public page naming `127.0.0.1` or `169.254.169.254` gets the link in
  the text but no request (`signals.images_private_skipped`); a picture redirect is checked per hop.
  A page that is itself private may still use its own private pictures.
- redirects of the main URL are followed by hand in both HTTP tiers, so every hop is checked.

**Size and time**
- bodies above 8 MB are spooled to disk and never held whole: `--download` has **no size and no
  time limit** and streams straight to `raw.*` (a 120 MB file costs 33 MB of RSS, measured).
  Without the flag a download stops at `MAX_DOWNLOAD` 250 MB and a file at `MEDIA_LIMIT` 100 MB,
  with `too_large` decided from `Content-Length` before the body is read.
- `MAX_PAGE_BYTES` 64 MB is the point where HTML/text stops being parsed into one string; the file
  itself is still downloaded whole.
- no whole-run deadline: each mechanism has its own attempts x timeout (HTTP 25 s x up to 4
  fingerprints, browser 10 s x 3, reader 60 s, archive 20 s, picture 6 s; the table is in
  `references/engines.md`). A browser that times out still yields the DOM it has
  (`signals.render_partial`), instead of being thrown away.
- the plain-curl tier sends `--compressed`: a gzip response is no longer decoded as cp1251 garbage.
- zip entries are refused by their declared size, not after being read: a 120 KB docx with a 120 MB
  entry went from 248 MB peak RSS to 26 MB.

**Classification (the old thresholds produced four false statuses)**
- `empty`/`not_found`/`blocked`/`login_required` are word-based and look at `<title>`/`<h1>`:
  a 51-character status page is `ok`, a 781-character article about 404s is `ok`, a page quoting
  "access denied" is `ok`, a newsletter form is `ok`.
- a body that is binary (NUL or >10 % control bytes, not HTML) is `empty` with
  `signals.binary`; it used to be `ok` with 98 400 characters of garbage.
- an error page served at `*.png` is no longer `media_only` (the HTTP status is checked first).

**Pictures**
- `<base href>` is honoured when resolving picture URLs.
- a name collision is checked against files already in `img/`, not only the current run: two pages
  in one `--dir` no longer overwrite each other.
- `--refresh` removes only the files the previous manifest lists, so a user's own `raw.txt` in a
  `--dir` folder survives.

**MCP (same core, no duplicated policy)**
- `TEXT_LIMIT`, the download cap and the deadline are imported from `readpage.py`; the server keeps
  only client-side image limits.
- `allow_images=false` works (it was in the schema and read nowhere).
- `read` only accepts folders this skill wrote (a cache entry, or a `--dir` with our manifest); a
  prompt-injected model can no longer use it to read `C:\Windows\win.ini`.
- the crop is counted in characters and cuts a long line: a 500 000-character single-line page used
  to return 500 001 characters against a 24 000 limit.
- a JSON-RPC batch gets `-32600` instead of crashing the loop and leaving the client hanging.
- unknown arguments are rejected with the allowed list (the schema already said
  `additionalProperties: false`).
- `read` with an offset past the end says "end of file" instead of "showing 501-500".
- `read_url` exposes `download`, matching the CLI.

**Elsewhere**
- only `http(s)` is accepted: `file:///...` gets a clear `error` instead of `empty` + "try --alternate".
- `--caps` stays; the module docstring no longer lists flags removed in 0.3.0; `UA` says 0.4.
- `SKILL.md` is rewritten: where files go, what each status returns, a sample manifest, the flags,
  the limits, links to `references/`.
- `defuddle`/`markitdown` are called with an argv list (a `.cmd` on Windows still needs `cmd.exe`);
  a path with a quote can no longer change the command.

**Second pass (same day, after review feedback)**
- `--download` really has no limits: the body is spooled into the work folder (not a side temp dir),
  `curl` loses `--max-time`/`--max-filesize`, curl_cffi loses the read timeout, and free disk space
  is checked before writing. 120 MB file: 33 MB peak RSS.
- no global deadline; connect 7.5 s + read 10 s, 3 fingerprints (was 4 x 25 s); Firecrawl/Jina 20 s;
  converters 20 s; pictures 32 in parallel; a body or a DOM that arrived before a timeout is kept.
- one folder per URL again (the `mode` hash is gone); the flags live in the manifest, a re-read
  replaces the text and keeps the files, and `--allow-images` tops up pictures without refetching.
- `--refresh` revalidates: `If-None-Match`/`If-Modified-Since`, `304` -> `cache=revalidated`.
- pictures: two different names are two files even with identical bytes (a marker always resolves);
  same name + different bytes -> `-2`, documented in `SKILL.md`.
- `media_only` and `too_large` write a one-line `content.md` that names the file, so "read
  content.md" never hits a missing file.
- flag conflicts are resolved by precedence: `--force-external` wins over the private-URL heuristic
  and says so in `privacy.conflict`; `--allow-external` does not.
- cookies set by a redirect are kept for that run (never persisted).
- heuristics stay honest (a long page is not forced to `ok`); `signals.status_reason` says which rule
  fired, so a status can be checked instead of trusted - the content is always there.
- `--refresh` revalidates per file: `ETag`/`Last-Modified` for the page **and for each picture**, so
  one changed picture does not re-download the other 599. It no longer wipes the folder; files the
  new version does not reference are pruned at the end.
- cookies are kept per host for 15 minutes (shared by every page of that host), never persisted
  longer, dropped by `--refresh`.
- two TLS fingerprints by default; a third only when both answered a plain 403.
- a duplicated sweep result file is deleted; the
  "230 pages" claim is withdrawn in `KNOWN-ISSUES.md`.
- `tests/fixes.py`: 60 offline checks, one per fix above.
- `BUILD` 7.

## 0.3.0 - 2026-10-30

A contract release: the manifest says what to do instead of listing arrays, the MCP server became
useful to a model, and pictures are part of the result.

- status: `ok|blocked|login_required|not_found|empty|media_only|too_large|error`; `next` and
  `exhausted` removed, `advice` (one sentence) added.
- login: three levels - strong (401, redirect to `/login`, `/signin`, `/auth`, accounts.google.com)
  and medium (password form, "sign in to continue") give `login_required`; weak (a mention on a
  short page, a password on a long one) only sets `signals.login_hint`. The footer is never
  counted (substack: marker at 92.7 % of the text). Content is returned in every case.
- images: every `<img>/<source>` is downloaded - own host and CDN - into `img/` with original
  names, sha1 dedupe, tracking pixels dropped, `-2` on collision; the text gets
  `[12x12 7Kb] img/pencil.png` after each image block. No image count limit; the download is
  time-bounded and what it cuts is reported. Images inside docx/epub are extracted too.
- single-file endpoints: `media_only` (image/audio/video saved as is), `too_large` over 100 MB
  with `--download` to override. (0.3.0 claimed a 250 MB page cap here; it was not implemented
  until 0.4.0.)
- Google Docs/Sheets/Slides: the export endpoint (docx/xlsx/pptx) is the primary path, not a
  rescue; the JavaScript shell is only a fallback. A live doc gave 11 pictures and footnote-safe
  text in 2.4 s.
- docx: footnotes and endnotes are read from `word/footnotes.xml`/`endnotes.xml` - the extra 13 %
  of text that markitdown reported was real content, not noise.
- flags: `--allow-external` (alias `--public`), `--force-external` (alias `--external`, implies
  allow), `--alternate`, `--download`, `--print`, `--refresh`, `--dir`; `--browser`, `--images`,
  `--more`, `--sensitive` removed.
- fetch: the TLS fingerprint is chosen by measurement, not by recency. Over 14 sites the newest
  profiles (`chrome136`-`chrome152`, `edge101`, and the `chrome` alias) are exactly the ones npm
  and medium reject, while `chrome151` and `safari184` pass 12/14 and `firefox135` is the only one
  amazon accepts. The rotation is `chrome151 -> firefox135 -> safari184 -> chrome124` - at most
  four attempts, only after 403/429, one attempt on 12 of 14 sites. The list is filtered against
  the targets the installed `curl_cffi` actually has. No randomised fingerprints (sites use
  allowlists); no bot User-Agent on top of a browser handshake.
- `--download` means no policy limits: file size, page size, image count, image time.
- without `--download` the text comes first: pictures may spend only what is left of a 10-second
  budget, the rest is reported as `images_truncated`.
- a short answer from a JSON/text endpoint (a DOI resolver, an API) is `ok`, not `empty`.
- the default work directory is the cache entry itself, so pictures are never copied twice.
- a weak login signal is only reported on short pages (a shop with 27 835 characters and a header
  modal was getting a false "text may be partial").
- a dead connection is not retried by the second HTTP client; a TLS-level reset still falls back
  to plain curl.
- `READ_PAGE_TRACE=1` prints one `RP_LOG event=. k=v` line per step.
- a wall served with HTTP 200 and a few hundred characters is `blocked`, not `ok`.
- an exception inside one tier prints a manifest with `status=error` and an advice line.
- readers are not called when the host never answered at all.
- tests: a manual probe and a live sweep (both since removed); `tests/props.py` offline
  checks; `tests/sites.md` registry; `KNOWN-ISSUES.md`.
- `BUILD` 5.

## 0.2.0 - 2026-10-29

- manifest: `page.{title,description,author,published,canonical,lang,site}` from `<meta>`,
  OpenGraph and JSON-LD, so citations do not need a second request.
- images: WebP dimensions in the manifest (VP8X, VP8, VP8L).
- tests: `tests/props.py` - paths with spaces and Cyrillic, crop/`--more` continuity, cache reuse,
  page metadata.
- docs: install/update section in README, `version`/`updated` in the frontmatter.
- `BUILD` 3.

## 0.1.0 - 2026-10-29

- First working cut: one command, JSON manifest with `status/exhausted/next`, `content.md` +
  `page.md` + `raw.*`, coverage-aware extractor choice, headless fallback, archive before paid
  readers, `--public` privacy gate, documents (PDF/DOCX/XLSX/PPTX/EPUB), video transcripts,
  15-minute cache, parts/outline for long pages, cropping, MCP frontend.
