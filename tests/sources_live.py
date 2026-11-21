"""Against the real services: each reader alone, each site adapter, and a
read through the CLI. Network; the keyed readers spend about one credit per check.

    python -X utf8 tests/sources_live.py              # all
    python -X utf8 tests/sources_live.py adapter      # only the checks whose name has "adapter"

A reader whose key is not set is skipped, not failed. Nothing here prints a key.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness import SCRIPT, Checks                           # noqa: E402

check = Checks()
spec = importlib.util.spec_from_file_location("rp_live", SCRIPT)
mod = importlib.util.module_from_spec(spec)
os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-live-")
spec.loader.exec_module(mod)
PAGE = "https://en.wikipedia.org/wiki/Web_scraping"
QUERY = "https://en.wikipedia.org/w/index.php?title=Web_scraping&action=view"
GONE = "https://en.wikipedia.org/wiki/Read_page_test_no_such_article_4f7a9c"

# ------------------------------------------------ every reader on its own, on a real page
for name in mod.READERS:
    key = mod.READER_KEYS.get(name)
    if name in mod.KEY_NEEDED and not os.environ.get(key or ""):
        check.skip("reader live: %s reads a page" % name, "%s is not set" % key)
        continue
    mod.READERS = (name,)
    t0 = time.monotonic()
    text, eng, st, note = mod.external_read(PAGE, mod.caps())
    dt = time.monotonic() - t0
    check("reader live: %s reads a page" % name, eng == "reader:" + name and "scraping" in (text or "").lower()
          and len(text) > 2000, "%.1f s, %d chars, %s" % (dt, len(text or ""), note[:80]))
    if name in ("exa", "firecrawl", "jina"):
        text, eng, st, note = mod.external_read(PAGE, mod.caps(), refresh=True)
        check("reader live: %s takes the fresh-copy option" % name, "scraping" in (text or "").lower(), note[:80])
    text, eng, st, note = mod.external_read(GONE, mod.caps())
    print("INFO %-58s status %s, %d chars, %s" % ("reader live: what %s says about a 404" % name, st, len(text or ""),
                                                note[:70]))
    mod.READERS = tuple(mod.READER_CALLS)
mod.READERS = ("defuddle.md",)
text, eng, st, note = mod.external_read(QUERY, mod.caps())
check("reader live: defuddle.md reads an address with a query", "scraping" in (text or "").lower(), note[:80])
mod.READERS = tuple(mod.READER_CALLS)

# ------------------------------------------------ every adapter on a real page
cases = [
    ("stackexchange", "https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-"
                      "processing-an-unsorted-array", "branch prediction"),
    ("stackexchange", "https://unix.stackexchange.com/questions/4126/what-is-the-exact-difference-between-a-terminal-"
                      "a-shell-a-tty-and-a-con", "terminal"),
    ("npm", "https://www.npmjs.com/package/react", "react"),
    ("npm", "https://www.npmjs.com/package/@types/node", "node"),
    ("npm", "https://www.npmjs.com/package/left-pad", "leftpad"),
    ("hn", "https://news.ycombinator.com/item?id=8863", "dropbox"),
    ("x", "https://x.com/jack/status/20", "just setting up my twttr"),
]
for name, url, needle in cases:
    t0 = time.monotonic()
    got = mod.siteapi.read(url, mod.SITE_API_SECONDS)
    dt = time.monotonic() - t0
    md, eng, raw = got or ("", "", "")
    check("adapter live: %s %s" % (name, url.split("/")[2] + "/" + url.split("/")[-1][:24]),
          eng == "api:" + name and needle in md.lower().replace("-", "") and dt < mod.SITE_API_SECONDS,
          "%.1f s, %d chars: %r" % (dt, len(md), md[:70]))
    if name == "npm" and "react" in url:
        check("adapter live: npm's README comes from the tarball (the registry has none for react)",
              "## " in md or "React" in md.split("\n", 6)[-1], "%d chars after the facts" % len(md.split("\n", 6)[-1]))
    if name == "hn":
        check("adapter live: Hacker News comments have their text", "## Comments" in md and md.count("**") >= 6,
              "%d comment headers" % (md.count("**") // 2))


# ------------------------------------------------ a read through the CLI, the way an agent calls it
def cli(url, *flags):
    tmp = tempfile.mkdtemp(prefix="rp-live-cli-")
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, url, "--json", "--dir", os.path.join(tmp, "out")]
                       + list(flags), capture_output=True, timeout=240,
                       env=dict(os.environ, READ_PAGE_CACHE=os.path.join(tmp, "cache")))
    try:
        return json.loads(p.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        return {}


m = cli("https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-processing-an-"
        "unsorted-array")
check("adapter live: a CLI read of a Stack Overflow question is ok through the API",
      m.get("status") == "ok" and (m.get("content") or {}).get("engine") == "api:stackexchange",
      "%s %s %.1f s" % (m.get("status"), (m.get("content") or {}).get("engine"), (m.get("elapsed_ms") or 0) / 1000))
m = cli("https://x.com/jack/status/20")
check("adapter live: a CLI read of a post on X is ok through fxtwitter",
      m.get("status") == "ok" and (m.get("content") or {}).get("engine") == "api:x",
      "%s %s" % (m.get("status"), (m.get("content") or {}).get("engine")))

sys.exit(check.done())
