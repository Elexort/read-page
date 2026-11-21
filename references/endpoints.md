# Machine-readable versions of a page (cheaper than the HTML)

Send `Accept: text/markdown` first — many docs sites answer with clean markdown (measured:
`developers.cloudflare.com` 7 KB instead of 330 KB of HTML, `docs.github.com` 24 KB instead of
154 KB). The script does this on every request; the list below is for cases where the API is
better than both.

| Kind | URL |
|---|---|
| docs page, markdown | the same URL with `Accept: text/markdown`, or `PAGE.md`, or the site's `llms.txt` |
| GitHub file | `https://raw.githubusercontent.com/OWNER/REPO/HEAD/PATH` |
| GitHub issue | `https://api.github.com/repos/OWNER/REPO/issues/N` |
| npm package | `https://registry.npmjs.org/PACKAGE/latest` (or `/VERSION`), and the README from its `dist.tarball`; the bare `/PACKAGE` is 7-15 MB for react or typescript and has no README for them |
| PyPI package | `https://pypi.org/pypi/PACKAGE/json` |
| Wikipedia | `https://en.wikipedia.org/w/index.php?title=TITLE&action=raw` |
| Stack Exchange | `https://api.stackexchange.com/2.3/questions/ID?site=stackoverflow&filter=withbody` |
| Hacker News | `https://hacker-news.firebaseio.com/v0/item/ID.json` |
| arXiv | `https://arxiv.org/html/ID`, `https://export.arxiv.org/api/query?id_list=ID` |
| X / Twitter | `https://api.fxtwitter.com/status/ID` (the account name is not needed, so it is not sent) |
| PubMed | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=PMID&retmode=xml` (NCBI's E-utilities: the citation, authors, abstract, identifiers, MeSH terms; a book's record - StatPearls, GeneReviews - comes from the same call as `PubmedBookArticle`; `rettype=abstract&retmode=text` for plain text) |
| Google Docs | `https://docs.google.com/document/d/ID/export?format=docx` — the skill's primary path (docx keeps the document's pictures; `?format=txt` is plain text without them) |
| Google Sheets | `https://docs.google.com/spreadsheets/d/ID/export?format=xlsx` (`?format=csv` for one sheet) |
| Google Slides | `https://docs.google.com/presentation/d/ID/export?format=pptx` |

The script itself uses four of them, with no flag, for the sites the ordinary path fails on
(`scripts/siteapi.py`): Stack Exchange, npm, Hacker News, X and PubMed. The
rest are for a caller who wants the data rather than the page.

These endpoints answer with the page's own data: quoting them is quoting the page. A redirect to
`accounts.google.com` or a `Sign in` title means the document is private — that is a different
skill's job, not this one's. `/edit` URL forms are rewritten to `/export?format=…` automatically
for `docs.google.com` and `drive.google.com` (see `google_export()` in `scripts/readpage.py`).
