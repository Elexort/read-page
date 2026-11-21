"""The main HTTP channel offline, and the test switch that makes it possible. No network.

    python -X utf8 tests/channel.py

READ_PAGE_TEST_PUBLIC_HOST must make exactly one address public: the main channel (curl_cffi)
then reads a local server, while every other loopback address and name stays private.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import advsrv                                      # noqa: E402
import readpage                                    # noqa: E402
from harness import PRIVATE, PUBLIC, Checks, run_read   # noqa: E402

check = Checks()

# the switch is narrow: one address, nothing else
os.environ.pop("READ_PAGE_TEST_PUBLIC_HOST", None)
check("switch off: 127.0.0.1 is private", bool(readpage.host_is_private("http://%s:8080/" % PUBLIC)))
os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
check("switch on: 127.0.0.1 is public", readpage.host_is_private("http://%s:8080/" % PUBLIC) == "")
check("switch on: 127.0.0.2 stays private", bool(readpage.host_is_private("http://%s:8080/" % PRIVATE)))
check("switch on: localhost stays private", bool(readpage.host_is_private("http://localhost:8080/")))
check("switch on: metadata stays private", bool(readpage.host_is_private("http://169.254.169.254/latest")))
check("switch on: a secret in the path still keeps the URL from readers",
      bool(readpage.url_has_secret("http://%s:8080/reset/AbCdEf0123456789AbCdEf0123456789" % PUBLIC)))
os.environ.pop("READ_PAGE_TEST_PUBLIC_HOST", None)

s = advsrv.start()
try:
    if not readpage.caps()["libs"].get("curl_cffi"):
        check.skip("main channel reads a local page", "curl_cffi is not installed")
    else:
        r = run_read(s.public.url("/ok"))
        tried = (r.manifest.get("chain") or {}).get("tried") or []
        check("main channel reads a local page", "http:curl_cffi" in tried, str(tried))
        check("main channel: status ok and the text arrives",
              r.manifest.get("status") == "ok" and "OK-MARKER" in r.file("content.md"),
              r.manifest.get("status", "?"))
    r = run_read(s.public.url("/ok"), public=False)
    tried = (r.manifest.get("chain") or {}).get("tried") or []
    check("switch off: loopback takes the private path", "http:curl_cffi" not in tried, str(tried))
finally:
    s.stop()

sys.exit(check.done())
