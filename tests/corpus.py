"""Corpus run: 30 URLs across categories, and the numbers we care about.

    python -X utf8 tests/corpus.py            # uses the page cache when fresh
    python -X utf8 tests/corpus.py --fresh    # every page fetched again
    python -X utf8 tests/corpus.py --allow-external   # allow readers (spends credits on walls)

Answers: how often the type is guessed wrong, how often extraction comes back empty,
how often the text is a fragment, and what each category costs in time.
"""
import json
import os
import subprocess
import sys
import time
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):    # the user's debug log switches stay out
    os.environ.pop(_name, None)

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "readpage.py")
OUT = os.path.join(HERE, "corpus_results.json")

CORPUS = [
    ("docs", "docs.python.org pathlib", "https://docs.python.org/3/library/pathlib.html"),
    ("docs", "MDN Fetch API", "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API"),
    ("docs", "cloudflare workers", "https://developers.cloudflare.com/workers/"),
    ("docs", "github docs", "https://docs.github.com/en/get-started"),
    ("docs", "tailwind installation", "https://tailwindcss.com/docs/installation"),
    ("docs", "react learn", "https://react.dev/learn"),
    ("docs", "nodejs learn", "https://nodejs.org/en/learn/getting-started/introduction-to-nodejs"),
    ("docs", "kubernetes overview", "https://kubernetes.io/docs/concepts/overview/"),
    ("docs", "chrome docs", "https://developer.chrome.com/docs/extensions/get-started"),
    ("article", "wikipedia Web_scraping", "https://en.wikipedia.org/wiki/Web_scraping"),
    ("article", "wikipedia ru HTTP", "https://ru.wikipedia.org/wiki/HTTP"),
    ("article", "habr articles", "https://habr.com/ru/articles/"),
    ("article", "the guardian", "https://www.theguardian.com/international"),
    ("news", "bbc news", "https://www.bbc.com/news"),
    ("ads", "w3schools html intro", "https://www.w3schools.com/html/html_intro.asp"),
    ("ads", "geeksforgeeks python", "https://www.geeksforgeeks.org/python/python-programming-language-tutorial/"),
    ("wall", "npmjs package", "https://www.npmjs.com/package/trafilatura"),
    ("wall", "stack overflow", "https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-processing-an-unsorted-array"),
    ("wall", "reddit webdev", "https://www.reddit.com/r/webdev/"),
    ("spa", "docsify quickstart", "https://docsify.js.org/#/quickstart"),
    ("data", "github api", "https://api.github.com/repos/adbar/trafilatura"),
    ("data", "pypi json", "https://pypi.org/pypi/trafilatura/json"),
    ("data", "raw readme", "https://raw.githubusercontent.com/adbar/trafilatura/HEAD/README.md"),
    ("file", "arxiv pdf", "https://arxiv.org/pdf/1706.03762"),
    ("file", "demo docx", "https://calibre-ebook.com/downloads/demos/demo.docx"),
    ("encoding", "lib.ru koi8-r", "http://lib.ru/"),
    ("encoding", "aozora shift-jis", "https://www.aozora.gr.jp/"),
    ("video", "youtube 19s", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("dead", "python.org ppt", "https://www.python.org/doc/essays/ppt/"),
    ("minimal", "example.com", "https://example.com/"),
]


def run(url, args):
    t = time.time()
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, url] + args + ["--json"], capture_output=True, timeout=300)
    dt = int((time.time() - t) * 1000)
    try:
        m = json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        return None, dt, p.stderr.decode("utf-8", "replace")[:200]
    return m, dt, ""


def main():
    fresh = "--fresh" in sys.argv
    public = "--allow-external" in sys.argv
    args = (["--refresh"] if fresh else []) + (["--allow-external"] if public else [])
    rows = []
    for cat, name, url in CORPUS:
        m, dt, err = run(url, args)
        if not m:
            print("ERR  %-10s %-26s %s" % (cat, name, err))
            rows.append({"cat": cat, "name": name, "status": "crashed", "ms": dt})
            continue
        c = m.get("content") or {}
        sig = m.get("signals") or {}
        row = {"cat": cat, "name": name, "status": m.get("status"), "engine": c.get("engine"),
               "chars": c.get("chars"), "cover": c.get("cover"), "fragment": bool(sig.get("fragment")),
               "conflict": bool(sig.get("type_conflict")), "js_shell": bool(sig.get("js_shell")),
               "blocked": bool(sig.get("blocked")), "ms": m.get("elapsed_ms") or dt,
               "cache": m.get("cache")}
        rows.append(row)
        print("%-5s %-10s %-26s %-8s %-22s %7s ch cover=%-5s %5s ms %s" % (
            "OK" if row["status"] == "ok" else "..", cat, name[:26], row["status"],
            (row["engine"] or "?")[:22], row["chars"], row["cover"], row["ms"],
            ("fragment " if row["fragment"] else "") + ("conflict " if row["conflict"] else "") +
            ("blocked" if row["blocked"] else "")), flush=True)

    ok = [r for r in rows if r.get("status") == "ok"]
    print("\n== summary ==")
    print("total %d | ok %d | blocked %d | empty %d | error %d | not_found %d" % (
        len(rows), len(ok),
        sum(1 for r in rows if r.get("status") == "blocked"),
        sum(1 for r in rows if r.get("status") == "empty"),
        sum(1 for r in rows if r.get("status") == "error"),
        sum(1 for r in rows if r.get("status") == "not_found")))
    print("fragments: %d | type conflicts: %d | empty text (<300 ch): %d" % (
        sum(1 for r in rows if r.get("fragment")),
        sum(1 for r in rows if r.get("conflict")),
        sum(1 for r in ok if (r.get("chars") or 0) < 300)))
    ms = sorted(r["ms"] for r in rows if r.get("ms"))
    if ms:
        print("time: median %d ms | p90 %d ms | max %d ms" % (ms[len(ms) // 2], ms[int(len(ms) * 0.9) - 1], ms[-1]))
    from collections import Counter
    print("engines:", dict(Counter((r.get("engine") or "-").split(":")[0] for r in rows)))
    print("by category:", {c: "%d/%d ok" % (sum(1 for r in rows if r["cat"] == c and r.get("status") == "ok"),
                                            sum(1 for r in rows if r["cat"] == c))
                           for c in dict.fromkeys(r["cat"] for r in rows)})
    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("written", OUT)


if __name__ == "__main__":
    main()
