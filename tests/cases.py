"""Test cases for read-page: run the script, check the manifest against expectations.

usage: python -X utf8 tests/cases.py [--external] [--filter substring]

Each case is (name, url, args, checks). Checks are (field-path, predicate) pairs:
  status=ok | min:chars=N | has:signals.fragment | engine-starts:defuddle | cache=hit
"""
import json
import os
import subprocess
import sys
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):    # the user's debug log switches stay out
    os.environ.pop(_name, None)

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "readpage.py")

# A Google Doc of your own that is shared by link and has pictures: its address stays out of the
# repository (a document id in a public file is a public document). Unset: the case is skipped.
GDOC = os.environ.get("READ_PAGE_TEST_GDOC", "")

CASES = [
    ("cloudflare docs (server markdown)", "https://developers.cloudflare.com/workers/", [],
     ["status=ok", "min:chars=6000", "engine=server:markdown"]),
    ("github docs (server markdown)", "https://docs.github.com/en/get-started", [],
     ["status=ok", "min:chars=15000"]),
    ("wikipedia (static article)", "https://en.wikipedia.org/wiki/Web_scraping", [],
     ["status=ok", "min:chars=20000"]),
    ("docsify (JS shell, hash route)", "https://docsify.js.org/#/quickstart", [],
     ["status=ok", "min:chars=3000", "tried:browser"]),
    ("w3schools (403 to HTTP, ads)", "https://www.w3schools.com/html/html_intro.asp", [],
     ["status=ok", "min:chars=5000"]),
    ("npm (TLS wall)", "https://www.npmjs.com/package/trafilatura", [],
     ["status=ok", "min:chars=3000"]),
    ("lib.ru (koi8-r/cp1251, no meta)", "http://lib.ru/", [],
     ["status=ok", "min:chars=5000"]),
    ("arxiv PDF", "https://arxiv.org/pdf/1706.03762", [],
     ["status=ok", "min:chars=30000", "engine=document"]),
    ("github api (json)", "https://api.github.com/repos/adbar/trafilatura", [],
     ["status=ok", "min:chars=1000"]),
    ("stack overflow (sensitive)", "https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-processing-an-unsorted-array", [],
     ["status=blocked", "has:advice", "has:privacy.refused"]),
    ("stack overflow (--allow-external)", "https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-processing-an-unsorted-array", ["--allow-external"],
     ["status=ok", "min:chars=50000"], True),
    ("video transcript (yt-dlp)", "https://www.youtube.com/watch?v=jNQXAC9IVRw", [],
     ["status=ok", "min:chars=100", "engine=video:yt-dlp"]),
    ("private url keeps external refused", "http://localhost:9/none", [],
     ["status=error"]),
    ("dead page (404)", "https://www.python.org/doc/essays/ppt/", [],
     ["status=not_found", "has:advice"]),
    ("google doc (export is the primary path)", GDOC, [],
     ["status=ok", "min:chars=1000", "engine=document", "tried:document:docx", "has:images"]),
    ("single image endpoint (media_only)",
     "https://upload.wikimedia.org/wikipedia/commons/3/3a/Cat03.jpg", [],
     ["status=media_only", "has:files.media"]),
]


FRESH = "--fresh" in sys.argv


def run_case(url, args):
    if FRESH:
        args = list(args) + ["--refresh"]
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, url] + args + ["--json"],
                       capture_output=True, timeout=300)
    try:
        return json.loads(p.stdout.decode("utf-8", "replace")), p.stderr.decode("utf-8", "replace")
    except Exception:
        return None, p.stderr.decode("utf-8", "replace")


def check(m, spec):
    if "=" in spec:
        kind, _, val = spec.partition("=")
        if ":" in kind:                                   # "min:chars=6000"
            kind, _, prefix = kind.partition(":")
            val = prefix + "=" + val
    else:
        kind, _, val = spec.partition(":")                # "has:next", "tried:browser"
    if kind == "status":
        return m.get("status") == val
    if kind == "min":
        key, _, n = val.partition("=")
        root = m.get("content") if isinstance(m.get("content"), dict) and key in m["content"] else m
        node = root.get(key)
        return isinstance(node, (int, float)) and node >= int(n)
    if kind == "engine":
        return (m.get("content") or {}).get("engine") == val
    if kind == "engine-starts":
        return str((m.get("content") or {}).get("engine", "")).startswith(val)
    if kind == "has":
        node = m
        for part in val.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return bool(node) if not isinstance(node, list) else len(node) > 0
    if kind == "tried":
        return any(val in t for t in (m.get("chain") or {}).get("tried", []))
    if kind == "advice":
        return val in (m.get("advice") or "")
    if kind == "cache":
        return m.get("cache") == val
    return False


def main():
    want_external = "--external" in sys.argv
    flt = ""
    if "--filter" in sys.argv:
        flt = sys.argv[sys.argv.index("--filter") + 1]
    ok = bad = skipped = 0
    for case in CASES:
        name, url, args, checks = case[:4]
        needs_money = len(case) > 4 and case[4]
        if flt and flt not in name:
            continue
        if not url:                                 # a case whose address comes from the environment
            skipped += 1
            print("SKIP %-45s (its address is not set here)" % name)
            continue
        if needs_money and not want_external:
            print("SKIP %-42s (needs --external)" % name)
            skipped += 1
            continue
        m, err = run_case(url, args)
        if m is None:
            print("FAIL %-42s no manifest | %s" % (name, err.strip()[:120]))
            bad += 1
            continue
        results = [(c, check(m, c)) for c in checks]
        failed = [c for c, r in results if not r]
        line = "%-42s %-8s %7d ch  %5d ms  %s" % (
            name, m.get("status"), (m.get("content") or {}).get("chars", 0), m.get("elapsed_ms", 0),
            ", ".join(c for c, r in results if r) or "-")
        if failed:
            print("FAIL " + line + "  MISSING: " + ", ".join(failed))
            bad += 1
        else:
            print("OK   " + line)
            ok += 1
    # the answer: a long page fits the budget and names the line it goes on from
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT,
                        "https://en.wikipedia.org/wiki/Web_scraping", "--refresh"],
                       capture_output=True, timeout=300)
    if len(p.stdout) <= 9980 and b"--from " in p.stdout:
        print("OK   %-42s %d bytes, next line named" % ("answer budget", len(p.stdout)))
        ok += 1
    else:
        print("FAIL %-42s %d bytes" % ("answer budget", len(p.stdout)))
        bad += 1

    print("\n%d ok, %d failed, %d skipped" % (ok, bad, skipped))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
