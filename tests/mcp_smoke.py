"""Smoke test for the MCP frontend: speak the protocol over stdio and check the shapes.

    python -X utf8 tests/mcp_smoke.py [URL]

Checks: lifecycle, the two tools, the compact header, the text slice, interleaved image
blocks with images=true, read() for text / image / manifest, path traversal, bad URL,
unknown tool. A page with pictures is fetched only when images=true is exercised.
"""
import json
import os
import re
import subprocess
import sys
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):    # the user's debug log switches stay out
    os.environ.pop(_name, None)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harness import cline_form, mcp_dir, mcp_said, mcp_status     # noqa: E402

SERVER = os.path.join(os.path.dirname(HERE), "scripts", "mcp_server.py")
URL = sys.argv[1] if len(sys.argv) > 1 else "https://en.wikipedia.org/wiki/Web_scraping"
IMG_URL = "https://en.wikipedia.org/wiki/Cat"
ok = bad = 0


def check(name, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
        print("OK   %-34s %s" % (name, detail))
    else:
        bad += 1
        print("FAIL %-34s %s" % (name, detail))


proc = subprocess.Popen([sys.executable, "-X", "utf8", SERVER],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
n = 0


def rpc(method, params=None):
    global n
    n += 1
    msg = {"jsonrpc": "2.0", "id": n, "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        print("no response to", method, "| stderr:", proc.stderr.read().decode()[-400:])
        sys.exit(1)
    return json.loads(line)


results = []                  # every tools/call result: none carries structuredContent (KNOWN-ISSUES 275)


def call(name, args):
    r = rpc("tools/call", {"name": name, "arguments": args})
    res = r.get("result") or {"content": [], "isError": True, "error": r.get("error")}
    results.append((name, res))
    return res


def notify(method, params=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


# 1. lifecycle
init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "smoke", "version": "0"}})["result"]
WANT_VERSION = re.search(r'SERVER_VERSION\s*=\s*"([^"]+)"',
                         open(SERVER, encoding="utf-8").read()).group(1)
check("initialize", init["protocolVersion"] == "2025-06-18" and
      init["serverInfo"]["version"] == WANT_VERSION,
      "%s v%s" % (init["serverInfo"]["name"], init["serverInfo"]["version"]))
notify("notifications/initialized")

# 2. tools
tools = rpc("tools/list")["result"]["tools"]
names = {t["name"] for t in tools}
check("tools/list", names == {"read_url", "read"}, sorted(names))
props = {t["name"]: sorted((t["inputSchema"] or {}).get("properties") or {}) for t in tools}
check("read_url arguments", props["read_url"] == [
    "allow_external", "alternate", "chars", "clear_cookies", "deny_images", "download", "file",
    "force_external", "from", "inline_images", "ocr", "probe", "probe_units", "refresh", "screenshots", "url"], props["read_url"])
check("read arguments", props["read"] == ["chars", "dir", "file", "from", "ocr"], props["read"])

# 3. ping
check("ping", "result" in rpc("ping"))

# 4. read_url: header, text; the manifest is the folder's file, never a part of the result
res = call("read_url", {"url": URL})
head = res["content"][0]["text"] if res["content"] else ""
lines = head.splitlines()
folder = mcp_dir(res)
check("read_url status", mcp_status(res) == "ok", mcp_status(res))
check("header is free text, not JSON", not head.lstrip().startswith("{"), head.splitlines()[0][:70])
check("header first line", lines[0].startswith("read-page · ok") and "content.md" in lines[0],
      lines[0][:90])
check("header names the files", any(ln.startswith("files: ") for ln in lines[:4]), lines[1][:70])
check("header counts lines", " lines" in lines[0], "")
check("the manifest is the folder's file", os.path.isfile(os.path.join(folder, "manifest.json")), folder[-40:])
check("the text follows the header", "── content.md" in head and len(head) > 300, "%d chars" % len(head))
nxt_m = re.search(r"── next: line (\d+) of \d+", mcp_said(res))
check("the next line is reported, or the end", nxt_m is not None or "── EOF content.md: " in mcp_said(res),
      nxt_m.group(0) if nxt_m else "the whole text")
check("the answer fits the budget", len(head.encode("utf-8")) <= 9980, "%d bytes" % len(head.encode("utf-8")))
check("the whole result as Cline counts it (its JSON) fits too", cline_form(res) <= 7900, "%d characters" % cline_form(res))

# 5. read: continue the text at the line the answer named
nxt = int(nxt_m.group(1)) if nxt_m else None
if nxt:
    more = call("read", {"dir": folder, "file": "content.md", "from": nxt})
    check("read continues at that line", ("── content.md: lines %d-" % nxt) in mcp_said(more),
          mcp_said(more).split("\n")[0][:70])
    check("read header names the file", "content.md" in more["content"][0]["text"].splitlines()[0],
          more["content"][0]["text"].splitlines()[0][:70])
    check("read: the whole result as Cline counts it fits", cline_form(more) <= 7900, "%d characters" % cline_form(more))
else:
    more = call("read", {"dir": folder})
    check("read from line 1", "── content.md: " in mcp_said(more), mcp_said(more)[:70])

# 6. read: the manifest is readable as a file
man = call("read", {"dir": folder, "file": "manifest.json"})
check("read manifest.json", "\n{" in man["content"][-1]["text"], "")

# 7. images=true: blocks interleaved with the text, caption after each
res2 = call("read_url", {"url": IMG_URL, "inline_images": True})
folder2 = mcp_dir(res2)
types = [b["type"] for b in res2["content"]]
check("images: status ok", mcp_status(res2) == "ok", mcp_status(res2))
check("images: blocks attached", types.count("image") > 0, "types=%s" % types[:8])
# each image block right after the line that holds its marker `[img #N · WxH ...] img/...`
blocks2 = res2["content"]
captions = [blocks2[i - 1]["text"].rstrip("\n").splitlines()[-1] for i, b in enumerate(blocks2)
            if b["type"] == "image" and i and blocks2[i - 1]["type"] == "text"]
check("images: caption with dims and path", bool(captions) and all(
      re.search(r"\[img #\d+ · \d+x\d+ [^\]]*\] img/\S+", c) for c in captions),
      captions[0][:60] if captions else "")
check("images: every image block has a mimeType",
      all(b.get("mimeType") for b in res2["content"] if b["type"] == "image"), "")
check("images: text still present", any(b["type"] == "text" and len(b["text"]) > 1000
                                       for b in res2["content"]), "")
order_ok = True
for _i, _b in enumerate(res2["content"]):
    if _b["type"] != "image" or not captions:
        continue          # without markers (no defuddle) the images come from the manifest
    _prev = res2["content"][_i - 1] if _i else {}
    # the text block before a picture ends with that picture's marker
    if not (_prev.get("type") == "text"
            and re.search(r"\[img #\d+ · [^\]\n]*\] img/\S+\s*$", _prev.get("text") or "")):
        order_ok = False
check("images: each picture follows its own caption", order_ok,
      "%s types=%s" % ("captions" if captions else "manifest fallback", types[:8]))

# 8. read: an image file comes back as an image block
try:
    with open(os.path.join(folder2, "manifest.json"), encoding="utf-8") as fh:
        imgs = [e for e in json.load(fh).get("images") or [] if e.get("file")]
except (OSError, ValueError):
    imgs = []
if imgs:
    one = call("read", {"dir": folder2, "file": imgs[0]["file"]})
    check("read image file", [b["type"] for b in one["content"]] == ["text", "image", "text"], imgs[0]["file"])

# 9. path traversal is refused
trav = call("read", {"dir": folder2, "file": "../../../etc/passwd"})
check("read refuses traversal", trav.get("isError") and "no such file" in trav["content"][0]["text"],
      trav["content"][0]["text"][:60] if trav["content"] else "")

# 10. error paths
bad_tool = rpc("tools/call", {"name": "nope", "arguments": {}})
check("unknown tool", "error" in bad_tool, bad_tool.get("error", {}).get("message"))

bad_url = call("read_url", {"url": "http://localhost:9/none"})
check("bad url is an error", bad_url["isError"] and mcp_status(bad_url) == "error", mcp_status(bad_url))

# 11. no result carries structuredContent: Cline's SDK runtime counted it against its 8 000 characters, a client
# may show it instead of the text (KNOWN-ISSUES 275)
check("no result carries structuredContent", not [n for n, r in results if "structuredContent" in r],
      "%d results: %s" % (len(results), sorted({tuple(sorted(r)) for _, r in results})))

proc.stdin.close()
proc.wait(timeout=10)
print("\n%d ok, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
