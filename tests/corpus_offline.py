"""Real pages, offline: saved raw.html of ordinary pages, run through extraction with no network.

    python -X utf8 tests/corpus_offline.py                  # run extraction on every saved page
    python -X utf8 tests/corpus_offline.py --collect DIR..  # take raw.html from read-page cache folders
    python -X utf8 tests/corpus_offline.py --fetch          # rebuild from tests/corpus_urls.txt (network)

The pages live in tests/fixtures/corpus/ and stay out of git: they belong to their sites. The URL
list is in git, so any machine can rebuild them. The run prints a baseline per page; the stages
that change extraction add their properties here (restored blocks, picture markers, budget).
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):    # the user's debug log switches stay out
    os.environ.pop(_name, None)

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
CORPUS = os.path.join(HERE, "fixtures", "corpus")
URLS = os.path.join(HERE, "corpus_urls.txt")
sys.path.insert(0, os.path.join(SKILL, "scripts"))


def slug(url):
    s = re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://", "", url.lower())).strip("-")[:60]
    return "%s-%s" % (s, hashlib.sha1(url.encode()).hexdigest()[:6])


def save(url, raw_path, extra):
    d = os.path.join(CORPUS, slug(url))
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(raw_path, os.path.join(d, "raw.html"))
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(dict(extra, url=url), f, ensure_ascii=False, indent=1)
    return d


def collect(dirs):
    n = 0
    for root in dirs:
        for mp in glob.glob(os.path.join(root, "**", "manifest.json"), recursive=True):
            folder = os.path.dirname(mp)
            raw = os.path.join(folder, "raw.html")
            if not os.path.isfile(raw):
                continue
            with open(mp, encoding="utf-8") as f:
                m = json.load(f)
            url = (m.get("url") or {}).get("final") or (m.get("url") or {}).get("input")
            if not url or m.get("status") != "ok":
                continue
            save(url, raw, {"status": m.get("status"), "engine": (m.get("content") or {}).get("engine")})
            n += 1
    print("collected %d pages into %s" % (n, CORPUS))


def fetch():
    urls = [u.strip() for u in open(URLS, encoding="utf-8") if u.strip() and not u.startswith("#")]
    for url in urls:
        tmp = tempfile.mkdtemp(prefix="rp-corpus-")
        subprocess.run([sys.executable, "-X", "utf8", os.path.join(SKILL, "scripts", "readpage.py"), url,
                        "--allow-external", "--deny-images", "--dir", os.path.join(tmp, "out")],
                       capture_output=True, timeout=240,
                       env=dict(os.environ, READ_PAGE_CACHE=os.path.join(tmp, "cache")))
        raw = os.path.join(tmp, "out", "raw.html")
        print(("ok    " if os.path.isfile(raw) else "miss  ") + url)
        if os.path.isfile(raw):
            save(url, raw, {"fetched": int(time.time())})
        shutil.rmtree(tmp, ignore_errors=True)


def run():
    import readpage
    c = readpage.caps()
    pages = sorted(glob.glob(os.path.join(CORPUS, "*", "raw.html")))
    if not pages:
        print("no saved pages in %s: run --collect or --fetch first" % CORPUS)
        return 0
    tot_chars = tot_pics = 0
    t0 = time.time()
    for raw in pages:
        with open(os.path.join(os.path.dirname(raw), "meta.json"), encoding="utf-8") as f:
            url = json.load(f)["url"]
        with open(raw, encoding="utf-8", errors="replace") as f:
            html = f.read()
        work = tempfile.mkdtemp(prefix="rp-extract-")
        try:
            text, engine, _cands, _page = readpage.extract(html, url, c, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        pics = len(re.findall(r"!\[[^\]]*\]\(", text or ""))
        tot_chars += len(text or "")
        tot_pics += pics
        print("%-12s %7d chars %4d pictures  %s" % (engine or "-", len(text or ""), pics, url[:90]))
    print("\n%d pages, %d chars, %d picture links, %.0f s" % (len(pages), tot_chars, tot_pics, time.time() - t0))
    return 0


if __name__ == "__main__":
    if "--collect" in sys.argv:
        collect([a for a in sys.argv[1:] if a != "--collect"])
    elif "--fetch" in sys.argv:
        fetch()
    else:
        sys.exit(run())
