# Site registry: where the skill broke, where it works, where it does not yet

A living list for manual and automatic checks. Updated after every live run (`tests/cases.py`,
`tests/corpus.py`) and every manual investigation.

How to use:

```bash
python -X utf8 scripts/readpage.py URL --json      # one site by hand: the manifest says what happened
python -X utf8 tests/cases.py --filter npm         # the named live cases (--external adds the readers)
python -X utf8 tests/corpus.py --fresh             # the 30-URL corpus, every page fetched again
```

Dates: 30–31 Oct 2026. Live pages in all: **200** (two random sweeps of 10 queries × 10 links
each) plus a corpus of 30 URLs and manual investigations.

---

## 1. Beaten: it was broken — now it works

| Site | Was | Now | What fixed it |
|---|---|---|---|
| `npmjs.com/package/…` | 403 for every client | 200, 5 358 chars | TLS fingerprint rotation (`chrome151 → firefox135 → safari184 → chrome124`) |
| `medium.com/@adbar/trafilatura` | a Cloudflare wall came with **200** and was returned as `ok` | `blocked` + advice about a reader | the wall is caught by its words when the text is shorter than 800 chars; the flag is recomputed from the final text |
| `velosite.ru` | `--allow-external` crashed (`UnboundLocalError`), no output; 102 s | `error` + a manifest in 22 s | a safety net in `__main__`; readers are not called if the host did not answer |
| `kakprosto.ru/kak-116055/…` | 404, not a word about the archive | `not_found` + `archive` (2025-10-12), with `--refresh` the reader confirms the 404 without the cache | an `archive{engine,timestamp,url,checked_live}` field + advice |
| `truevalue.com/…/how-to-fix-a-leaky-faucet/` | 406 Not Acceptable, empty | `empty` locally, **12 748 chars** with `--allow-external` | a retry with a browser Accept header + a reader |
| `velogrand.ru/collection/velosipedy` | 347 words (the catalogue was dropped) | **1 012 words**, 24 cards | a new `main` candidate — the largest container, if it holds ≥30 links and 1.5 times more text |
| `velo-shop.ru` | 1 799 words | **3 906 words** | the same |
| `tomsguide.com/best-picks/…` | 14.3 s | 10.1 s | the working folder = the cache folder (no copying of pictures) |
| `theguardian.com/international` | 40 s (647 pictures) | 10.3 s, 315 pictures, what was cut off is counted | a time budget for pictures |
| `python.org/doc/essays/ppt/` | a 404 with a long frame was returned as `ok` | `not_found` (the text is returned) | a hard 404 outweighs the text length |
| `unetway.com/blog/…` | certificate error | 200 (the page is JS-only → `empty`) | on a certificate error, a retry without verification + `signals.tls` |
| `tbank.ru/invest/…` | certificate error | `not_found` (a real 404) | the same |
| `sberbank.ru/…` | certificate error | `error` (the host does not answer from the test machine) | the same |
| `stackoverflow.com/questions/…` | 403 | `blocked` + advice, with `--allow-external` 35 587 chars | the rotation was exhausted, honestly |
| `w3schools.com`, `docsify.js.org` | 403 / JS shell | 10 565 and 3 956 chars | rendering + curl_cffi |

## 2. Reference: they work, kept as coverage of capabilities

| Site | What it checks |
|---|---|
| `docs.python.org/3/library/asyncio-task.html` | a huge docs page, 6 670 words |
| `developers.cloudflare.com/workers/` | the server serves markdown (`server:markdown`) |
| `docs.github.com/en/get-started` | server-side markdown, 24 k chars |
| `tailwindcss.com/docs/installation` | docs with low coverage in trafilatura |
| `en.wikipedia.org/wiki/Cat` | 58 pictures, a huge text, CJK links |
| `arxiv.org/pdf/1706.03762` | a PDF with a text layer |
| `introml.mit.edu/…/chapter_Transformers.pdf` | PDF lecture notes, 18 600 chars |
| `api.github.com/repos/adbar/trafilatura` | JSON as content |
| `lib.ru` (koi8-r), `aozora.gr.jp` (shift-jis) | encodings without a meta tag |
| `kubernetes.io/docs/concepts/services-networking/ingress/` | docs with tables |
| `openstax.org/books/world-history-volume-2/…` | a textbook, 42 854 chars |
| `metmuseum.org/-/media/…/publications…` | a PDF inside a museum site |
| `docs.google.com/document/d/…` (a document shared by link) | docx export, 11 pictures, 2.4 s |
| `youtube.com/watch?v=jNQXAC9IVRw` | subtitles + covers |
| `healthline.com/nutrition/mediterranean-diet-meal-plan` | a listing, the `main` engine |
| `eatingwell.com/…mediterranean…` | a long longread |
| `computerbild.de/bestenlisten/…` (German), `hifi.de/beste/…` | German reviews, 10 s |
| `20minutos.es`, `hola.com`, `directoalpaladar.com` (Spanish) | Spanish cuisine |
| `travel.rakuten.co.jp`, `mapple.net`, `gotokyo.org` (Japanese) | CJK pages, 42 k chars |
| `heise.de/bestenlisten/…` | 115 715 chars, readability |
| `doi.org/10.5040/…` | a short `text/plain` from an API = `ok`, not `empty` |
| `barricades.ac.uk/exhibits/…` | a real 404 (the `not_found` reference) |
| `homedepot.com/c/ah/…` | 403 for every fingerprint (the `blocked` reference) |

## 3. Open problems

| Site | What is seen | What to do |
|---|---|---|
| `sberbank.ru/…/selfinvest/etf` | sometimes a 21 s timeout, sometimes 200 with an empty body (TLS without verification) — the host is unstable from the test machine | check in a browser: looks like network filtering, not the skill |
| `unetway.com/blog/…ssh-ubuntu-2004` | the certificate is not trusted → we read without verification, the page gives 28 chars (a JS app) | needs a render that waits for the API response, then see what comes |
| `nfm.nikkeibp.co.jp/atcl/plus/21/00013/00022/` | 742 chars, but the text is complete (intro + 2 charts + «調査対象エリア») | compare with a browser: if it has the same volume — close the question |
| `news.jcbo.jp/en/news/tokyo-rental-market-q2-2026` | 1 462 chars, no «Sources & references» block (links) | decide whether to add the list of links from the article's footer |
| `truevalue.com/…` | locally 406; the text only through a reader | needs a browser Accept profile or cookies |
| `bikepremier.ru` | 62 chars: «Site under construction» | nothing to fix, a placeholder site |
| `velosite.ru` | unreachable from the test machine (a browser does not reach it either) | keep as the `error` reference |
| `medium.com/@adbar/trafilatura` | a CF wall even for the reader | a browser also shows the 404 design → the page was removed |

---

## Random live sweeps, 30–31 Oct 2026

| Sweep | Queries | Pages | ok | not_found | blocked | empty | error |
|---|---|---|---|---|---|---|---|
| A (30 Oct) | ru/en: borscht, transformers, asyncio, rent in Tokyo, keyboards, Arctic ice, bicycles, rust/go, a faucet, quantum computing | 100 | 95 | 1 | 1 | 2 | 1 |
| B (31 Oct) | en/ru/es/de/ja: the Mediterranean diet, ssh, the Ottoman Empire, paella, headphones, Tokyo, changing a tire, books of 2026, index funds, kubernetes ingress | 100 | 94 | 2* | 1 | 1* | 2* |

\* after the fixes: `tbank` went from `error` to an honest `not_found`, `unetway` went from
`error` to `empty` (a JS app), `sberbank` is sometimes `error` by timeout, sometimes `empty` (200 and
an empty body): the host is unstable from the test machine. B's total after the fixes: 94 ok, 2 not_found,
1 blocked, 2 empty, 1 error.

**After the fixes 15 sites were beaten** (table 1), reference — 23, open — 8, 3 of them not
ours (a dead host, a placeholder, a removed page).
