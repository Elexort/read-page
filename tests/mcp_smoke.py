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


def call(name, args):
    r = rpc("tools/call", {"name": name, "arguments": args})
    return r.get("result") or {"content": [], "structuredContent": {}, "isError": True,
                               "error": r.get("error")}


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
    "allow_external", "alternate", "clear_cookies", "deny_images", "download", "file",
    "force_external", "from", "inline_images", "ocr", "refresh", "screenshots", "to", "url"], props["read_url"])
check("read arguments", props["read"] == ["dir", "file", "from", "ocr", "to"], props["read"])

# 3. ping
check("ping", "result" in rpc("ping"))

# 4. read_url: header, text, structured manifest
res = call("read_url", {"url": URL})
sc = res["structuredContent"]
head = res["content"][0]["text"] if res["content"] else ""
lines = head.splitlines()
check("read_url status", sc.get("status") == "ok", str(sc.get("status")))
check("header is free text, not JSON", not head.lstrip().startswith("{"), head.splitlines()[0][:70])
check("header first line", lines[0].startswith("read-page · ok") and "content.md" in lines[0],
      lines[0][:90])
check("header names the files", any(ln.startswith("files: ") for ln in lines[:4]), lines[1][:70])
check("header counts lines", " lines" in lines[0], "")
check("full manifest in structuredContent",
      all(k in sc for k in ("url", "content", "signals", "chain", "files")), sorted(sc)[:8])
check("the text follows the header", "── content.md" in head and len(head) > 300, "%d chars" % len(head))
check("the next line is reported", "next_from" in sc["mcp"]
      and (sc["mcp"]["next_from"] is None or isinstance(sc["mcp"]["next_from"], int)),
      "next_from=%s" % sc["mcp"].get("next_from"))
check("the answer fits the budget", len(head.encode("utf-8")) <= 9980, "%d bytes" % len(head.encode("utf-8")))

# 5. read: continue the text at the line the answer named
nxt = sc["mcp"].get("next_from")
if nxt:
    more = call("read", {"dir": sc["dir"], "file": "content.md", "from": nxt})
    s2 = more["structuredContent"]
    check("read continues at that line", s2.get("from") == nxt
          and ("lines %d-" % nxt) in more["content"][0]["text"], "from=%s next=%s" % (s2.get("from"), s2.get("next_from")))
    check("read header names the file", "content.md" in more["content"][0]["text"].splitlines()[0],
          more["content"][0]["text"].splitlines()[0][:70])
else:
    more = call("read", {"dir": sc["dir"]})
    check("read from line 1", more["structuredContent"].get("total_lines", 0) > 0, "")

# 6. read: the manifest is readable as a file
man = call("read", {"dir": sc["dir"], "file": "manifest.json"})
check("read manifest.json", "\n{" in man["content"][-1]["text"], "")

# 7. images=true: blocks interleaved with the text, caption after each
res2 = call("read_url", {"url": IMG_URL, "inline_images": True})
sc2 = res2["structuredContent"]
types = [b["type"] for b in res2["content"]]
check("images: status ok", sc2.get("status") == "ok", str(sc2.get("status")))
check("images: blocks attached", types.count("image") > 0, "types=%s" % types[:8])
check("images: attached count reported", sc2["mcp"]["images_attached"] == types.count("image"),
      "attached=%s blocks=%s" % (sc2["mcp"]["images_attached"], types.count("image")))
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
imgs = sc2.get("images") or []
if imgs:
    one = call("read", {"dir": sc2["dir"], "file": imgs[0]["file"]})
    check("read image file", one["content"][1]["type"] == "image" and one["structuredContent"]["attached"],
          imgs[0]["file"])

# 9. path traversal is refused
trav = call("read", {"dir": sc2["dir"], "file": "../../../etc/passwd"})
check("read refuses traversal", trav.get("isError") and "no such file" in trav["content"][0]["text"],
      trav["content"][0]["text"][:60] if trav["content"] else "")

# 10. error paths
bad_tool = rpc("tools/call", {"name": "nope", "arguments": {}})
check("unknown tool", "error" in bad_tool, bad_tool.get("error", {}).get("message"))

bad_url = call("read_url", {"url": "http://localhost:9/none"})
check("bad url is an error", bad_url["isError"] and bad_url["structuredContent"].get("status") == "error",
      str(bad_url["structuredContent"].get("status")))

proc.stdin.close()
proc.wait(timeout=10)
print("\n%d ok, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
