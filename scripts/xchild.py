"""One Python extractor in a process of its own, so the read can stop it at its deadline.

In-process, nothing could stop trafilatura: it took 87 s on the 16 MB HTML spec, readability 31 s
and html2text 12 s, with 1.2 GB of memory. Here readability and trafilatura run side by side,
each in its own process, and a process still working when the time is up is killed.

    python xchild.py readability|trafilatura|html2text URL  < page.html  > {"text": ...}
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engines                                                      # noqa: E402


def main():
    name = sys.argv[1]
    url = sys.argv[2] if len(sys.argv) > 2 else ""
    html = sys.stdin.buffer.read().decode("utf-8", "replace")
    slow = os.environ.get("READ_PAGE_TEST_XCHILD_SLEEP")      # the test suites' stand-in for a slow page
    if slow:
        import time
        time.sleep(float(slow))
    text = engines.RUN[name](html, url) if name in engines.RUN else ""
    sys.stdout.buffer.write(json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
