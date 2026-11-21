# Documents: PDF, office, e-books, video

The HTTP tier downloads the bytes; the converter depends on what they are. Detection is by magic
bytes first (`%PDF`, `PK`, `{\rtf`), then `Content-Type`, then the URL extension — never by trust in
the extension alone. An archive says what it is in its own `mimetype` file: `application/epub+zip`
is an EPUB, `...opendocument.text` an ODT (an archive used to be an EPUB whatever its `mimetype`, and an ODT came
out `empty`).

A file on this machine goes through the same converters: the CLI takes a path or
a `file://` URL, and nothing goes to the network - no reader, archive, browser or picture download.
The file is copied, never moved. Over MCP only a file inside read-page's own folders is read (a
page folder of its cache, or a folder with its manifest), checked after links are resolved.

| Kind | Converter | Notes |
|---|---|---|
| PDF, text layer | `pymupdf` (0.02 s for a page) or `pdftotext -enc UTF-8` | the text layer is an approximation: ligatures and hyphenation break exact quotes |
| PDF, its tables | `pymupdf4llm`'s layout model when installed (`--setup` installs it), in a process of its own (`scripts/pdftables.py`), on the pages that look like they hold a table: a caption line (Table 3, TABLE IV, Таблица 2), twelve lines that are one number, or eight rulings. The model gives a table's box and its grid of cells; each cell gets `pymupdf`'s whole words of the text blocks the table stands for (a block is the table's when half its words' centres are inside the box; a caption's lines never are), each word in the cell that holds its centre or else the nearest; a line of prose or a note that the grid's column lines cut at a mere space, where a cell holds two lines or more, stays text before or after the table; cells one header spans are joined by the gap between their words (a word on its side by its line's direction). The table stands as Markdown where those blocks stood, and only when its cells hold exactly their words - a check against a word lost or put in twice, not against one in the wrong cell; the rest of the page is `pymupdf`'s text | `pymupdf`'s text has a table one cell a line. Measured 2026-11-19 on 94 tables of 9 arXiv papers whose cells are known (their HTML on ar5iv, 889 rows) and 17 tables printed from HTML (250 rows), counting the rows that come out as a table row with each cell its own: `pymupdf`'s text 0 % and 0 %; its line-based `find_tables()` 2 % and 65 % (9 % with `refine`), with tables made of figures; pdfplumber 0-17 % and 48-65 %, with thousands of rows that are no table; `pymupdf4llm` without the model 2 % and 64 %; with the model 68 % and 99 %, with no time limit. Its own cells, though, take a character where more than half of it is inside: a grid line cut a word ("1 Intr \| oduction"), a row line scattered a header's letters ("Cbid CN dl"), points and commas went ("5121" for "5.1.2.1", "$32200"), captions inside its box were lost - 187 words of `pymupdf`'s text missing and 277 added on 29 PDFs, 137 caption lines of 142. With the page's words (2026-11-20/21, the same scorer, no time limit): 74 % and 100 % as table rows, 89 % and 100 % of the rows whole on one line, no word lost or added, 142 caption lines of 142, no line of prose cut into cells (52 such cuts in 6 tables before the lines were kept out). Under the default 10 s a read the same on a quiet machine (GPT-3's 30 pages with tables took the model 8.5 s), and on a busy one 65-70 % and 73-78 % (its pages that look like a table did not all fit; the model's own cells gave 62 % and 70 % there). A table whose box runs through a word of the page is left as text (7 rows more would be whole without that test, from tables that took prose into cells); a word on its side is no word of a phrase (ViT's "Caltech101" and "CIFAR-100" are two headers). Two weak models asked for one cell of a table they cannot know by heart (the printed ones): one was right on 5 of 32 from `pymupdf`'s text and 16 of 32 with the tables, the other on 3 of 20 and 13 of 21 (a third of its calls were lost to a rate limit); on the papers, whose numbers are widely quoted, the first was right on 32 of 37 either way. The model has 10 s a read, all the read's PDFs together (a ZIP's, an archived copy); 0.14-1.0 s a page measured on 20 cores (about twice that on a busy evening), the model's load 0.7-0.8 s and its process 0.15-0.22 s more (onnxruntime held to four threads, none spinning - left alone it took 1.8 s, at most 2.5, a page on two cores; the four come from the CPUs the process may use on Linux, while on Windows `os.process_cpu_count()` ignores the affinity mask): a paper of 15 pages reads in 2.4 s instead of 0.6, one of 75 in 10.7 s (its 10 s used up), NIST 800-63B (80 pages) in 7.2 s, a paper with no table in 2.0 s (two pages asked for nothing); on four slow cores 5.2, 11.6, 11.5 and 4.4 s. A page over 8 000 vector paths or 2 000 words in one block is not asked in a read's time (20 010 strokes of a scatter plot held the model 20-27 s, 6 000 words in a block 9.6 s; no page of the corpus has over 4 975 paths or 976 words in a block): `signals.tables.heavy`. The counts do not catch every slow page, so the model's process is killed when the time is up and the read keeps its deadline (a page of 5 010 strokes, 20 s in the model: 2.2 s at a deadline of 2 s, 10.8 s at 55). Pages not laid out are named in `signals.tables.left` (by file for the PDFs of a ZIP) and in `advice`, with `--download`, which has no time limit and lays them all out; `signals.tables.error` says why the model did not work (pymupdf4llm 1.28.2 does not import without onnxruntime), and the pages after it stopped are named too; the page lists are ranges ("28-600"); `READ_PAGE_SKIP=tables` turns the step off. `find_tables()` with the model switched on is not used: its cells came out scrambled (610.01 as "61001 .", PyMuPDF 1.28.2) |
| PDF with `--alternate` | `pymupdf4llm`'s Markdown of the document when installed: headings, and the tables in its own way, in the model's process within the read's time - a warm-up call of two pages gives the model's rate here, then calls of ten pages at most that fit what is left, so the time's end costs one small call (`--download`: one call), their headings levelled by the heading sizes of every call so far - as one call over the whole document on Attention, GPT-3, BERT and the W-4, NIST 800-63B's first page two headings a level higher (its largest heading is on page 3; the old calls of 57 and 23 pages had 90 heading lines of their own); a page too heavy for a read's time and the pages no call reached stay `pymupdf`'s text, named in `signals.tables.left` and the advice (`--download` lays out every page) - also when no page came as Markdown, and when the model cannot run (pymupdf4llm 1.28.2 does not import without onnxruntime: then `--alternate` is `pymupdf`'s text, and says so). The text layer is judged first (a scan goes to OCR with the flag as without it), and its Markdown is taken only when it kept half of the document's words | 0.2-0.5 s a page. Measured 2026-11-19 on five PDFs (three papers, a tax form, a NIST standard): headings 9-145 against none, the same words within 4 % (the form +14 %). A paper's Markdown is the same as at one go (Attention, 2026-11-20: no line differs); 600 pages of tables: 111 laid out in a 49.7 s read, the rest named - it took 114-262 s at one go; four reads of GPT-3 at once on two slow cores (0.9 s a page and more) laid out none in 51 s with one long call, 26-27 of 75 each in 50 s with calls of ten |
| RTF | our reader (`docreaders.py`, the standard library alone, in a process of its own) | headings (by style sheet and outline level, a numbered one with its number), nested lists from `\listtext`, tables on their `\cellx` columns, footnotes, `HYPERLINK` fields, the font's code page before `\ansicpg` (Greek, Hebrew, Chinese, Russian), `\uN` with its fallback; hidden text, headers, pictures' data out; random bytes after `{\rtf1` are "not text"; a reader that breaks gives the plain text (`docreaders.rtf_plain`) |
| ODT | our reader (`docreaders.py`, as RTF) | `content.xml` with `styles.xml`: headings, lists numbered as their style says, tables with covered cells and repeats, notes at the end, pictures with their `svg:title`, a text box's paragraphs after its frame, a formula's StarMath source; tracked deletions and comments out. ODS and ODP: `odf_text`, headings and paragraphs in order, `content.xml` read up to 64 MB, a DOCTYPE refused |
| PDF, scanned | render the page to PNG and OCR it: `tesserocr` in-process (`--setup` installs it), else the `tesseract` command | 150 dpi ≈ 33 ms, ~18 KB per page. `missing: no text layer` is reported so the caller knows why |
| DOCX / PPTX / XLSX | `python-docx` / `openpyxl` / `python-pptx` first (0.17–0.4 s): a DOCX in its own order with its content controls and text boxes, a PPTX with its groups and tables; a `.docm`, `.dotx`, `.ppsx`, `.potx` or Strict OOXML package is given the plain content type and namespaces in memory first (`office_plain`); a machine's own `pandoc`, then `markitdown`, when they give nothing (`--setup` installs neither) | tables survive; layout does not |
| EPUB | our reader (`docreaders.py`, as RTF): the spine in order through the OPF, the navigation document and a `<nav>` table of contents left out; each part through a tolerant tree builder; headings, nested lists, tables with merged cells, emphasis, outside links, code with its language, pictures `![alt](path in the archive)` so they become markers where they stand (SVG `<image>` too), MathML's `alttext`, ruby; a noteref's note as `[^n]: text` where the book keeps it | measured against pandoc and markitdown below. Our readers' bounds: a part 32 MB unpacked, an archive 128 MB, an RTF 128 MB; a table's grid 250 000 cells (spans and repeats included), a document's tables 1 000 000, a row 1 024 columns; a tag 8 KB; nesting 100 deep, deeper as text; the converter's 10 s for all the read's EPUB, ODT and RTF documents (none with `--download`), and 2 GB of memory where the OS limits it (RLIMIT_AS); a part or an element that breaks is named and the rest is read; the document's own text escaped for Markdown |
| a plain ZIP | `zip_text()`: the files listed, then the text of up to 30 of them - text files as they are, documents through the converters above, one level deep, under names of our own | 20 MB a member, 60 MB in all |
| DOCX footnotes | `word/footnotes.xml` + `word/endnotes.xml` via `zipfile` | python-docx cannot see them: on `demo.docx` the "extra 13 %" of text that markitdown reported was footnotes and TOC bookmarks, so the fast path plus `docx_notes()` is enough |
| images inside a document | `zip_images()` reads `word/media/…`, `…/images/…` into `img/` | deduplicated, `≤2×2` dropped. A Google Doc exported as docx carried 11 pictures this way. A docx is ordered by the flow of `a:blip` references in `document.xml` (resolved through `document.xml.rels`), so the list and the MCP image blocks are in reading order, an EPUB by the spine of its package document (a chapter the spine names again is scanned once); markers inside the text are still not invented. The order is a step of the read (`picture-order`): 10 s at most, less near the deadline, tags read as `[^<>]{0,8192}`; with no time left there is no order (`images_ordered` unset), not a guess. The archive unpacks 250 MB of pictures in all, every byte read counting, kept or not, and a copy - the same declared size and CRC - is not read twice. A picture the text names that the archive does not hold is listed after the others, numbered after them |
| YouTube | `yt-dlp` subtitles + the page's thumbnails; when yt-dlp gives none, the caption track through `youtube-transcript-api` in yt-dlp's form, else a machine's own markitdown | title + transcript, one language at a time; only a transcript counts, never a description alone |

## Without markitdown: the A/B (2026-11-19)

`--setup` installed markitdown for the documents the office readers give nothing and for EPUB,
and for YouTube transcripts; it is no longer installed (the condition was that quality does not drop).
Measured on 12 EPUBs (Standard Ebooks' Pride and Prejudice, Frankenstein, Sherlock Holmes and
Alice; IDPF's EPUB 3 samples Moby-Dick, The Waste Land, a children's book, Accessible EPUB 3, A
Shared Culture; Pro Git; a Russian one) against the words and headings of each book's own spine:
markitdown and the cleaned pandoc both read 99.7-105 % of the words (Pro Git 104.8 against 102.9 %:
markitdown also printed the table of contents); headings the same but for the table of contents
and title pages markitdown kept (Moby-Dick 147 against 146, Pro Git 689 both); tables the same (Pro
Git 61, Pride and Prejudice 6, Sherlock 8); pictures placed the same (Pro Git 187 against 188,
Alice 55 both); 0.8-3.6 s a book against 3.2-4.4 (markitdown's start alone took ~2.5 s). Raw
pandoc was not enough: its `gfm` wrapped every line of a poem in a `div` (+39 % noise) and left
Pro Git's examples as raw `<pre><code>`, while `gfm-raw_html` turned a table with merged cells into
`[TABLE]` - hence `clean_pandoc()`. The cases only markitdown read before: a DOCX whose text sits in
a content control or a text box (python-docx's paragraphs hold neither) - now read in order; a
plain ZIP of documents - now listed and read. YouTube: on four videos the caption track called
directly gave the same words as markitdown (3 294, 41, 385, 3 422), in 0.8-1.2 s against 4.8-5.3,
with timestamps. The environment lost 16 packages and 74 MB (741 -> 667 MB); onnxruntime, sympy
and numpy stay, pymupdf4llm needs them (through pymupdf-layout).

## Without pandoc: the A/B (2026-11-20, again 2026-11-21)

pandoc (`pypandoc_binary`: 41 MB of `--setup`'s download on Windows, 35 on Linux, 26 on macOS; 226
MB on disk on Windows, 162 on Linux) read EPUB, ODT and RTF and nothing else. Our readers (`docreaders.py`) were
measured against pandoc 3.9 on 52 files, each read twice through the CLI: 15 EPUBs (Standard
Ebooks, IDPF's samples, Pro Git, calibre's demo, Gutenberg's EPUB 2 in English and Russian), 18
ODTs (LibreOffice's guides 4.2-7.5, gov.uk's files saved by Word 2010/2013, Google Docs exports), 19
RTFs (Word, WordPad, TextEdit, LibreOffice and unnamed producers; English, Russian, Chinese, Greek,
Hebrew, Italian). The counts, ours against pandoc (and the file itself where it can be counted):

| | ours | pandoc | the files |
| --- | --- | --- | --- |
| words (EPUB, ODT) | 962 624, 278 527 | 962 855, 279 809 | 962 646, 278 597 |
| headings | 2 440 | 2 313 | |
| table rows | 2 282 | 1 970 | |
| footnote definitions | 77 | 74 | |
| pictures placed in the text | 1 126 | 760 | |

Ours matches the files' own words within 0.03 %; pandoc's ODT count holds 7 688 leftover HTML tags
and misses about 9 000 real words. pandoc lost Frankenstein's endnotes, 62 of the 66 chapter
headings of Gutenberg's *Pride and Prejudice*, whole tables of gov.uk's reports (a form's cells,
27 rows of figures), 573 figure captions of LibreOffice's Calc guide (which it wrote 356 times as
"(Figure )"), and every non-Latin RTF: Greek, Hebrew and Chinese came out as Latin-1 mojibake (it
decodes `\'hh` as cp1252 whatever the font's code page), Russian without its spaces. As a converter
ours is 6-17 times faster; through the CLI, a document's median (2026-11-21, in its own process)
0.74 s against 1.27 (EPUB), 0.64 against 0.88 (ODT), 0.60 against 0.80 (RTF). The hardening of
2026-11-21 (KNOWN-ISSUES 152-160) kept every count the same (6 prose words more: a linked
picture's address, a literal `node\_name` now escaped). So `--setup` installs no pandoc; a
machine's own stays the last resort for an office file the office readers cannot read. What
nobody reads now: a DOCX that is formulas alone (pandoc wrote TeX; row 165) and an RTF's pictures
(pandoc's links pointed at files it never wrote; row 166).

## Google Docs, Sheets, Slides: the export endpoint is the primary path

A `/document/d/ID/edit` URL returns a 663 KB JavaScript shell (200 OK, no text). The same ID with
`/export?format=docx` returns the document itself (734 KB, 11 pictures in `word/media`), and
`?format=txt` gives plain text without the pictures. So for `docs.google.com` the skill rewrites the
URL before fetching, and only falls back to the page if the export answers with HTML or an error.
A bounce to `accounts.google.com` from **both** means the document is private: that is
`login_required`, not a broken export.

Measured: 11 326 characters, 2.4 s, `chain.tried = ["google:export", "document:docx"]`.

## trafilatura and images

`trafilatura 2.2.0` accepts `include_images=True` and silently ignores it: no `![]()` appears in
its output. The call is kept anyway — the flag is the documented way and future versions may honour
it — but picture markers depend on the extractor that keeps images (`defuddle` does, trafilatura
does not). Pictures are downloaded either way; only their positions in the text are affected.

## OCR: on when tesseract is there

Detecting a missing text layer takes 14 ms and rendering a page 33 ms; both always happen, and the
PNGs land in `files.pages` for a model that can look. With OCR - `tesserocr` in-process, which
`readpage.py --setup` installs with English and Russian from tessdata_fast, or the `tesseract`
command - the same pages are OCR'd side by side and the result becomes the text (`engine:
document:ocr`, `signals.ocr_pages`), so a text-only pipeline gets words instead of a picture.
Measured on a synthetic scan: "SCANNED REPORT / Total 42 units" read back correctly. Languages
follow `READ_PAGE_OCR_LANGS` (`eng` by default, `eng+rus` for both; with `eng+deu` the next
`--setup` fetches German; `--ocr N` adds `rus` by itself on a page written in it),
`READ_PAGE_TESSDATA` points at a data folder outside the install (the environment sets its own). Without OCR nothing changes: the answer names the fix, and
a vision model can still read `files.pages` more accurately than OCR.

OCR counts as working only once tesseract has started on a pack (`caps()`, the setup report and the
read all ask it, not a listing of the folder). Where it is installed and does not start - on Windows a
profile folder with characters outside ASCII (`Иван`), which tesserocr cannot hand tesseract in the
ANSI code page, goes by its 8.3 short name and, with none, cannot start; a pack cut short - a scan
reads `missing: ocr` with the reason (`signals.ocr_error`), not a bare `empty`, and the fix named for
a path is `READ_PAGE_HOME` on an ASCII folder, then `--setup` there.

## Exact quotes

`raw.pdf` is kept, but a PDF text layer is itself an approximation. The manifest marks
`content.engine: document`, which means: quote markup and numbers freely, quote running text with
care. For HTML the raw bytes are authoritative.
