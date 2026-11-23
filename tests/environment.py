"""The skill's own environment (readpage.py --setup), offline: found, used, skipped, broken.

    python -X utf8 tests/environment.py

A fake environment is a real venv of this Python (no packages) with a setup.json beside it, in a
temp folder named by READ_PAGE_HOME: a run of readpage.py goes on under the venv's Python, with
its tools first on PATH, its exit code and its UTF-8 output kept; READ_PAGE_SKIP=env and a broken
environment leave the run where it started; the MCP server answers through the same hop. Then
--setup itself: with no network it says so and installs nothing; with a run already at work it
follows that one instead of starting another. The real install is minutes and half a gigabyte:
not here (a CI job of its own later).
"""
import contextlib
import glob
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import zipfile

for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR", "READ_PAGE_ENV_CHILD", "READ_PAGE_ENV",
              "READ_PAGE_SKIP", "READ_PAGE_TESSDATA"):
    os.environ.pop(_name, None)
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
SCRIPT = os.path.join(SCRIPTS, "readpage.py")
SERVER = os.path.join(SCRIPTS, "mcp_server.py")
sys.path.insert(0, SCRIPTS)
sys.dont_write_bytecode = True
import envsetup  # noqa: E402
import ownenv    # noqa: E402

ok = failed = 0


def ascii_base():
    """A short folder with an ASCII path, for the checks that are about one: TEMP is not ASCII under a Chinese
    profile (the CJK job runs the suites there), and cmd.exe prints a path in the OEM code page."""
    for base in (tempfile.gettempdir(), os.environ.get("RUNNER_TEMP"), os.environ.get("PUBLIC"),
                 os.environ.get("SystemDrive", "C:") + os.sep):
        if base and base.isascii() and os.path.isdir(base) and os.access(base, os.W_OK):
            return base
    return tempfile.gettempdir()


def check(name, good, detail=""):
    global ok, failed
    if good:
        ok += 1
        print("OK   %-66s %s" % (name, detail))
    else:
        failed += 1
        print("FAIL %-66s %s" % (name, detail))


def run(args, env, timeout=120, stdin=None):
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT] + args, capture_output=True, env=env,
                       timeout=timeout, input=stdin)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def caps(env):
    rc, out, err = run(["--caps"], env)
    try:
        return json.loads(out)
    except ValueError:
        return {"error": (out + err)[-300:]}


home = tempfile.mkdtemp(prefix="rp-env-")
venv = os.path.join(home, "envs", "fake")
subprocess.run([sys.executable, "-m", "venv", "--without-pip", venv], check=True, timeout=300)
bindir = os.path.join(venv, "Scripts" if os.name == "nt" else "bin")
py = os.path.join(bindir, "python.exe" if os.name == "nt" else "python")
# a tool of the environment's own, to see that its folder comes first on PATH
if os.name == "nt":
    tool = os.path.join(bindir, "yt-dlp.cmd")
    with open(tool, "w", encoding="utf-8") as fh:
        fh.write("@echo 2026.10.26\r\n")
else:
    tool = os.path.join(bindir, "yt-dlp")
    with open(tool, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\necho 2026.10.26\n")
    os.chmod(tool, 0o755)
os.makedirs(os.path.join(home, "tessdata"))
info = {"schema": ownenv.STATE_SCHEMA, "env": "envs/fake", "built": "2026-11-19T10:00:00+0000",
        "python": os.path.relpath(py, home).replace(os.sep, "/"), "browsers": "browsers", "tessdata": "tessdata",
        "problems": [{"part": "browser", "why": "the browser needs system libraries this machine lacks",
                      "fix": "sudo apt-get install the-browser-libraries"}]}
with open(os.path.join(home, "setup.json"), "w", encoding="utf-8") as fh:
    json.dump(info, fh)
base = dict(os.environ, READ_PAGE_HOME=home, READ_PAGE_CACHE=os.path.join(home, "cache-test"))
base.pop("PYTHONDONTWRITEBYTECODE", None)       # -E in the hop drops it anyway: readpage keeps .pyc out

def compiled():
    """What has been compiled beside the skill's scripts: {file: modification time}. The suites that ran
    before this one in a job (CI runs them one after another) import the skill in-process and may leave
    some, so a check looks at what the code under test changes - before and after - never at what is there."""
    folder = os.path.join(SCRIPTS, "__pycache__")
    try:
        return {n: os.stat(os.path.join(folder, n)).st_mtime_ns for n in os.listdir(folder)}
    except OSError:
        return {}


# ---------------------------------------------------------------- found and used
pyc_before = compiled()
c = caps(base)
env = c.get("env") or {}
check("a run goes on under the environment's Python", env.get("used") is True
      and os.path.normcase(os.path.dirname(env.get("python") or "")) == os.path.normcase(bindir),
      "%s %s" % (env.get("python"), c.get("error", "")))
check("its programs come first on PATH", os.path.normcase(os.path.dirname((c.get("cli") or {}).get("yt-dlp") or ""))
      == os.path.normcase(bindir), str((c.get("cli") or {}).get("yt-dlp")))
check("no compiled module lands beside the skill's scripts", compiled() == pyc_before,
      sorted(n for n, t in compiled().items() if pyc_before.get(n) != t))
rc, out, err = run([], base)
check("the setup report names the environment and when it was set up",
      "environment: %s, set up 2026-11-19" % home in out, [ln for ln in out.splitlines() if "environment" in ln][:1])
check("what --setup could not do is named with its own command",
      "sudo apt-get install the-browser-libraries" in out,
      [ln for ln in out.splitlines() if "browser" in ln][:2])

# exit codes and bytes pass through the hop
rc, out, err = run(["mailto:someone@example.com"], base)
check("a wrong call still exits 2 through the environment", rc == 2, "rc=%s %s" % (rc, (out + err)[-120:]))
doc = os.path.join(home, "note.txt")
with open(doc, "w", encoding="utf-8") as fh:
    fh.write("Проверка: текст по-русски и « кавычки », 東京.\n" * 3)
rc, out, err = run([doc], base)
check("UTF-8 output comes through the hop intact", rc == 0 and "Проверка: текст по-русски" in out and "東京" in out,
      "rc=%s %s" % (rc, out.splitlines()[0][:120] if out else err[-120:]))

# ---------------------------------------------------------------- not used
c = caps(dict(base, READ_PAGE_SKIP="env"))
check("READ_PAGE_SKIP=env keeps the run in its own Python", (c.get("env") or {}).get("used") is False
      and (c.get("env") or {}).get("why") == "READ_PAGE_SKIP=env", str(c.get("env")))
c = caps(dict(base, READ_PAGE_ENV_CHILD="1", READ_PAGE_SKIP=""))
check("a run already sent once is not sent again (no loop)", (c.get("env") or {}).get("used") is False
      and "child" in ((c.get("env") or {}).get("why") or ""), str(c.get("env")))
broken = tempfile.mkdtemp(prefix="rp-env-broken-")
with open(os.path.join(broken, "setup.json"), "w", encoding="utf-8") as fh:
    json.dump(dict(info, python="envs/gone/python.exe", env="envs/gone"), fh)
c = caps(dict(base, READ_PAGE_HOME=broken))
check("a broken environment leaves the run where it was, and says why",
      (c.get("env") or {}).get("used") is False and "missing" in ((c.get("env") or {}).get("why") or ""),
      str(c.get("env")))
rc, out, err = run([doc], dict(base, READ_PAGE_HOME=broken))
check("... and the read still works there", rc == 0 and "Проверка" in out, "rc=%s" % rc)
empty = tempfile.mkdtemp(prefix="rp-env-none-")
rc, out, err = run([], dict(base, READ_PAGE_HOME=empty))
check("no environment: the report says --setup installs the engines, and where",
      "environment: none yet - readpage.py --setup installs" in out and empty in out,
      [ln for ln in out.splitlines() if "environment" in ln][:1])
saved = dict(os.environ)
os.environ["READ_PAGE_HOME"] = home
ownenv.use(SCRIPT, ["--setup"])
check("--setup itself is never sent into the environment it builds",
      ownenv.status().get("why") == "--setup works from outside it", str(ownenv.status()))
os.environ.clear()
os.environ.update(saved)

# ---------------------------------------------------------------- the MCP server through the hop
p = subprocess.Popen([sys.executable, "-X", "utf8", SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, env=base)
try:
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
           "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    p.stdin.write((json.dumps(msg) + "\n").encode())
    p.stdin.flush()
    t0 = time.time()
    line = p.stdout.readline()
    reply = json.loads(line) if line else {}
    check("the MCP server answers through the environment's Python",
          (reply.get("result") or {}).get("serverInfo", {}).get("name") == "read-page",
          "%.1f s %s" % (time.time() - t0, line[:100]))
finally:
    try:
        p.stdin.close()
        p.wait(timeout=20)
    except Exception:                                          # noqa: BLE001
        p.kill()
check("... and ends when its client closes stdin", p.returncode is not None, "rc=%s" % p.returncode)

# ---------------------------------------------------------------- --setup with no network
off = tempfile.mkdtemp(prefix="rp-env-offline-")
off_tmp = tempfile.mkdtemp(prefix="rp-env-offtmp-", dir=ascii_base())       # a temp folder of this run alone
dead = dict(base, READ_PAGE_HOME=off, READ_PAGE_SETUP_WAIT="90", HTTPS_PROXY="http://127.0.0.1:9",
            HTTP_PROXY="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9",
            NO_PROXY="", no_proxy="", TEMP=off_tmp, TMP=off_tmp, TMPDIR=off_tmp)
for k in ("UV_DEFAULT_INDEX", "UV_INDEX_URL", "PIP_INDEX_URL"):
    dead.pop(k, None)
t0 = time.time()
rc, out, err = run(["--setup"], dead, timeout=180)
check("offline: --setup says it needs the internet and installs nothing",
      rc == 1 and "needs the internet" in out and not os.path.exists(os.path.join(off, "setup.json"))
      and not os.path.isdir(os.path.join(off, "envs")),
      "rc=%s %.0f s %s" % (rc, time.time() - t0, [ln for ln in out.splitlines() if "network" in ln][:1]))
off_pyc = [os.path.join(dp, n) for dp, _dn, fn in os.walk(off_tmp) for n in fn if n.endswith(".pyc")]
check("... and the --setup command compiles nothing into the temp folder (it served nothing, outside the folder it names)",
      not off_pyc, str(off_pyc[:2]))
shutil.rmtree(off_tmp, ignore_errors=True)
check("--setup's first line names the download and the disk it takes, before anything is fetched",
      re.match(r"read-page --setup: .* - downloads about \d+ MB, takes (about )?[\d.]+ GB on disk", out) is not None,
      out.splitlines()[0][:140] if out else "")

# ---------------------------------------------------------------- a second --setup follows the first
busy = tempfile.mkdtemp(prefix="rp-env-busy-")
held = envsetup._try_lock(os.path.join(busy, "setup.lock"))
with open(os.path.join(busy, "setup.state"), "w", encoding="utf-8") as fh:
    json.dump({"run": "earlier", "pid": os.getpid(), "started": time.time() - 30, "updated": time.time(), "step": 4,
               "steps": 9, "name": "engines", "done": False}, fh)
with open(os.path.join(busy, "setup.log"), "w", encoding="utf-8") as fh:
    fh.write("  1/9 network   pypi.org answers\n")
rc, out, err = run(["--setup"], dict(base, READ_PAGE_HOME=busy, READ_PAGE_SETUP_WAIT="2"))
envsetup._unlock(held)
check("a second --setup follows the run at work instead of starting another",
      rc == 0 and "still working; following it" in out and "1/9 network" in out
      and "goes on in the background (3 of 9 steps done, now: engines)" in out, out.replace("\n", " | ")[:200])

# ---------------------------------------------------------------- the installer's own pieces
bad_zip = os.path.join(home, "bad.zip")
with zipfile.ZipFile(bad_zip, "w") as z:
    z.writestr("../escaped.txt", "x")
try:
    envsetup.unpack(bad_zip, os.path.join(home, "unz"))
    refused = False
except ValueError:
    refused = True
check("an archive member outside its folder is refused (zip)", refused and not os.path.exists(
    os.path.join(home, "escaped.txt")), "")
bad_tar = os.path.join(home, "bad.tar.gz")
with tarfile.open(bad_tar, "w:gz") as t:
    ti = tarfile.TarInfo("node/bin/npm")
    ti.type, ti.linkname = tarfile.SYMTYPE, "../../../../outside"
    t.addfile(ti)
try:
    envsetup.unpack(bad_tar, os.path.join(home, "unt"))
    refused = False
except ValueError:
    refused = True
check("a link out of its folder is refused (tar)", refused, "")
good_tar = os.path.join(home, "good.tar.gz")
with tarfile.open(good_tar, "w:gz") as t:
    data = b"console.log(1)\n"
    ti = tarfile.TarInfo("node-v1/lib/node_modules/npm/bin/npm-cli.js")
    ti.size = len(data)
    t.addfile(ti, io.BytesIO(data))
    ln = tarfile.TarInfo("node-v1/bin/npm")
    ln.type, ln.linkname = tarfile.SYMTYPE, "../lib/node_modules/npm/bin/npm-cli.js"
    t.addfile(ln)
envsetup.unpack(good_tar, os.path.join(home, "ok"))
check("Node's own archive layout unpacks (a link inside it)",
      os.path.isfile(os.path.join(home, "ok", "node-v1", "lib", "node_modules", "npm", "bin", "npm-cli.js")), "")
f = envsetup.pick_wheel([{"filename": "uv-0.13.9-py3-none-win_amd64.whl"},
                         {"filename": "uv-0.13.9-py3-none-win_arm64.whl"},
                         {"filename": "uv-0.13.9-py3-none-macosx_11_0_arm64.whl"},
                         {"filename": "uv-0.13.9-py3-none-macosx_10_12_x86_64.whl"},
                         {"filename": "uv-0.13.9-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"},
                         {"filename": "uv-0.13.9-py3-none-musllinux_1_1_x86_64.whl"},
                         {"filename": "uv-0.13.9-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64"
                                      ".musllinux_1_1_aarch64.whl"}])
want = {("nt", "x64"): "win_amd64", ("nt", "arm64"): "win_arm64", ("darwin", "arm64"): "macosx_11_0_arm64",
        ("darwin", "x64"): "macosx_10_12_x86_64",
        ("linux", "x64"): "musllinux_1_1_x86_64" if ownenv.musl() else "manylinux_2_17_x86_64",
        ("linux", "arm64"): "aarch64"}.get(("nt" if os.name == "nt" else sys.platform if sys.platform == "darwin"
                                            else "linux", ownenv.machine()))
check("uv's wheel for this machine is the one picked", bool(f and want and want in f["filename"]),
      "%s for %s" % (f and f["filename"], ownenv.machine()))
with open(envsetup.LOCK_FILE, encoding="utf-8") as fh:
    lock = fh.read().lower().replace("_", "-")
missing = [t for t in envsetup.TOP if t.split("[")[0].lower().replace("_", "-") + "==" not in lock]
check("every engine --setup promises is pinned in setup-lock.txt", not missing, str(missing))
# defuddle's own packages have ranges (linkedom ^0.18.12, turndown ^7.2.0...): npm would take the
# newest of the day of each install, so the tree is a lock of its own, every tarball held to its SHA512
dcmd = envsetup.defuddle_command("node", "npm-cli.js", "ROOT")
npm_lock = json.load(open(envsetup.NPM_LOCK, encoding="utf-8"))
npm_pkgs = dict((k, v) for k, v in npm_lock["packages"].items() if k)
check("defuddle's own packages are pinned too: `npm ci` of the skill's lock, each tarball by its SHA512",
      dcmd[:4] == ["node", "npm-cli.js", "ci", "--prefix"] and "--ignore-scripts" in dcmd and "--include=optional" in dcmd
      and npm_lock["packages"][""]["dependencies"] == envsetup.npm_package()["dependencies"]
      and npm_pkgs["node_modules/defuddle"]["version"] == envsetup.DEFUDDLE_VERSION and len(npm_pkgs) == 27
      and all(re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", v.get("integrity", ""))
              and v.get("resolved", "").startswith("https://registry.npmjs.org/") for v in npm_pkgs.values())
      and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", envsetup.DEFUDDLE_BEFORE), " ".join(dcmd))
try:                                   # the pinned version must exist by the instant its tree is resolved as of
    published = envsetup.fetch_json("https://registry.npmjs.org/defuddle", timeout=20)["time"][envsetup.DEFUDDLE_VERSION]
except Exception as e:                                         # noqa: BLE001
    published = None
    print("SKIP defuddle %s's publish time (the npm registry does not answer: %s)" % (envsetup.DEFUDDLE_VERSION, str(e)[:60]))
if published:
    check("defuddle %s was published before --before's instant (npm would not find it otherwise)" % envsetup.DEFUDDLE_VERSION,
          published.replace(".000Z", "Z") <= envsetup.DEFUDDLE_BEFORE or published < envsetup.DEFUDDLE_BEFORE,
          "%s, before %s" % (published, envsetup.DEFUDDLE_BEFORE))
    # the lock's SHA512 of each of its 27 tarballs is the one the registry publishes (a typo would refuse every machine)
    import concurrent.futures                            # noqa: E402

    def published_integrity(key):
        name = key[key.rindex("node_modules/") + len("node_modules/"):]
        try:
            return key, envsetup.fetch_json("https://registry.npmjs.org/%s/%s" % (name.replace("/", "%2f"),
                                                                                  npm_pkgs[key]["version"]),
                                            timeout=20)["dist"]["integrity"]
        except Exception as e:                                 # noqa: BLE001
            return key, "?%s" % str(e)[:40]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        live_npm = dict(pool.map(published_integrity, sorted(npm_pkgs)))
    if any(v.startswith("?") for v in live_npm.values()):
        print("SKIP the lock's SHA512 against the registry (it did not answer for each: %s)"
              % [k for k, v in live_npm.items() if v.startswith("?")][:2])
    else:
        check("... and every SHA512 of the lock is the one the registry publishes for that version",
              all(live_npm[k] == v["integrity"] for k, v in npm_pkgs.items()),
              str([k for k, v in npm_pkgs.items() if live_npm[k] != v["integrity"]][:3]))
# ---------------------------------------------------------------- yt-dlp: the one engine not pinned
cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1795000000 - 3 * 86400))
cmd = envsetup.ytdlp_command("uv", "py", now=1795000000, floor="2026.10.26", lock="ENV-LOCK")
pkgs = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--exclude-newer-package"]
check("yt-dlp is not in the lock: --setup takes the newest release that has been out three days",
      "yt-dlp==" not in lock and "--upgrade" in cmd and "yt-dlp[default]>=2026.10.26" in cmd
      and sorted(pkgs) == sorted("%s=%s" % (n, cutoff) for n in envsetup.YTDLP_FLOATS), " ".join(cmd[5:]))
check("it never goes backwards (a floor: the version installed), under the lock the environment was built from",
      "yt-dlp[default]>=2026.10.26" in cmd and cmd[cmd.index("-c") + 1] == "ENV-LOCK"
      and "yt-dlp[default]" in envsetup.ytdlp_command("uv", "py")
      and not any(x.startswith("yt-dlp[default]>=") for x in envsetup.ytdlp_command("uv", "py")), "")
check("the date holds what floats only: no global --exclude-newer, so a pin of the lock younger than "
      "three days cannot send uv back to an old yt-dlp",
      "--exclude-newer" not in cmd and not (set(envsetup.YTDLP_FLOATS) & {"certifi", "requests", "urllib3", "idna",
                                                                         "charset-normalizer"}), "")


check("the advice names --setup only where it installs the engine",
      ownenv.gives("curl_cffi") and not ownenv.gives("lynx") and not ownenv.gives("curl")
      and ownenv.gives("tesseract") == ownenv.ocr_here(), "ocr here: %s" % ownenv.ocr_here())
# ---------------------------------------------------------------- where the folder is
# Windows gives a packaged app (MSIX: Claude's desktop app is one) a private copy of whatever its
# processes write under AppData: an environment built there by an agent in that app does not exist
# for a terminal or the next agent (another agent's shell saw "not set up")
kept = dict((k, os.environ.pop(k)) for k in ("READ_PAGE_HOME", "XDG_DATA_HOME") if k in os.environ)
try:
    where = ownenv.home()
finally:
    os.environ.update(kept)
user = os.path.expanduser("~")
if os.name == "nt":
    private = [os.path.normcase(os.path.abspath(os.environ.get(k) or os.path.join(user, "AppData", n))) + os.sep
               for k, n in (("LOCALAPPDATA", "Local"), ("APPDATA", "Roaming"))]
    good = (os.path.normcase(where) == os.path.normcase(os.path.join(user, ".read-page"))
            and not any(os.path.normcase(where).startswith(p) for p in private))
elif sys.platform == "darwin":
    good = where == os.path.join(user, "Library", "Application Support", "read-page")
else:
    good = where == os.path.join(user, ".local", "share", "read-page")
check("the folder is one every agent of the user sees (Windows: the home folder, not AppData)", good, where)

# ---------------------------------------------------------------- OCR when the folder's path is not ASCII
# on Windows tesserocr hands tesseract a narrow path, so tessdata under a profile
# named in another alphabet (`Иван`) failed to start - silently: --setup's check said 4 of 5, the setup
# report said nothing is missing, and a scan read as `empty`. The 8.3 short path opens; where it does not
# (or the pack is broken), OCR is not counted as working, and the read says `missing: ocr` with the reason.
junk = [home, broken, empty, off, busy]


def scratch(prefix):
    """A temp folder the suite removes at its end."""
    d_ = tempfile.mkdtemp(prefix=prefix)
    junk.append(d_)
    return d_


cyr = tempfile.mkdtemp(prefix="rp-Иван-", dir=ascii_base())
junk.append(cyr)
cyr_td = os.path.join(cyr, "tessdata")
os.makedirs(cyr_td)
with open(os.path.join(cyr_td, "eng.traineddata"), "wb") as fh:
    fh.write(b"a pack\n" * 100)
short = ownenv.ascii_path(cyr_td) if hasattr(ownenv, "ascii_path") else None
if os.name == "nt":
    if short == "":
        print("SKIP the 8.3 short path (this volume makes no short names)")
    else:
        check("a path outside ASCII goes by its 8.3 short name (Windows), the same folder",
              bool(short) and short.isascii() and os.path.samefile(short, cyr_td), str(short))
    check("a path that is not there has no short name: '' (never a guess)",
          hasattr(ownenv, "ascii_path") and ownenv.ascii_path(os.path.join(cyr, "Ещё", "нет")) == "", "")
ascii_only = os.path.join(os.sep, "ascii only", "folder")          # a path is a string here: it need not exist
check("an ASCII path stays as it is (and so does a path off Windows whose bytes are its UTF-8; one in another code "
      "set's bytes has none: tesserocr takes the path as UTF-8)",
      hasattr(ownenv, "ascii_path") and ownenv.ascii_path(ascii_only) == ascii_only
      and (os.name == "nt" or ownenv.ascii_path(cyr_td) == (cyr_td if ownenv.utf8_clean(cyr_td) else "")), "")


def fake_tesserocr(broken_pack=False):
    """What tesserocr does on Windows with a narrow path, and a pack that tesseract cannot start with."""
    mod = types.ModuleType("tesserocr")
    mod.__spec__ = importlib.machinery.ModuleSpec("tesserocr", None)

    def narrow(p):
        return os.name != "nt" or str(p).isascii()

    def get_languages(path=""):
        if not narrow(path):
            raise RuntimeError('recursive_directory_iterator: The system cannot find the path specified.: "%s"' % path)
        return path, sorted(n[:-12] for n in os.listdir(path) if n.endswith(".traineddata"))

    class PyTessBaseAPI:
        def __init__(self, path="", lang="eng"):
            if broken_pack or not narrow(path) or not os.path.isfile(os.path.join(path, lang + ".traineddata")):
                raise RuntimeError("Failed to init API, possibly an invalid tessdata path: %s" % path)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def SetImageFile(self, p):
            pass

        def Recognize(self, ms=0):
            return True

        def GetUTF8Text(self):
            return "Setup check 2026\n"

    mod.get_languages, mod.PyTessBaseAPI = get_languages, PyTessBaseAPI
    mod.tesseract_version = lambda: "tesseract 5.5.4\n"
    return mod


def load_rp(name):
    spec = importlib.util.spec_from_file_location("rp_env_%s_%d" % (name, time.time_ns()), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def with_tesserocr(fake, tessdata, fn):
    saved_mod, saved_td = sys.modules.get("tesserocr"), os.environ.get("READ_PAGE_TESSDATA")
    sys.modules["tesserocr"] = fake
    os.environ["READ_PAGE_TESSDATA"] = tessdata
    try:
        return fn()
    finally:
        if saved_mod is None:
            sys.modules.pop("tesserocr", None)
        else:
            sys.modules["tesserocr"] = saved_mod
        if saved_td is None:
            os.environ.pop("READ_PAGE_TESSDATA", None)
        else:
            os.environ["READ_PAGE_TESSDATA"] = saved_td


rp1 = load_rp("ocr")
rp1.which = lambda name: None                # no tesseract command on PATH: tesserocr alone
got = with_tesserocr(fake_tesserocr(), cyr_td, lambda: rp1._tesserocr())
check("tesserocr starts on tessdata under a path outside ASCII (by the short path, where Windows needs it), and "
      "what it hands back is the folder itself: every later start goes through ownenv.tess_dir",
      bool(got) and got[2] == ["eng"] and got[1] == cyr_td, str(got and got[1:]))
caps_ok = with_tesserocr(fake_tesserocr(), cyr_td, lambda: rp1.caps(fresh=True))
check("caps counts OCR as working only once it starts: here it does",
      caps_ok["libs"].get("tesserocr") is True and "eng" in caps_ok["ocr_langs"] and not caps_ok.get("ocr_error"),
      str(caps_ok.get("ocr_langs")))
caps_bad = with_tesserocr(fake_tesserocr(broken_pack=True), cyr_td, lambda: rp1.caps(fresh=True))
check("... and where it is installed but does not start, it does not count, and the reason is kept",
      caps_bad["libs"].get("tesserocr") is False and "does not start" in (caps_bad.get("ocr_error") or ""),
      str(caps_bad.get("ocr_error")))
rows = {r[0]: r for r in rp1.setup_rows(dict(caps_bad, keys={}))}
check("the setup report shows OCR as missing, with why - not under 'works now'",
      rows.get("tesseract") and rows["tesseract"][1] is False and "does not start" in rows["tesseract"][3],
      str(rows.get("tesseract")))
real_ascii = ownenv.ascii_path
ownenv.ascii_path = lambda p: ""                # a volume that makes no short names (a CI runner's D:)
cwd_before = os.getcwd()
try:
    arg_rel, cwd_rel = ownenv.tess_arg(cyr_td)
    with ownenv.tess_dir(cyr_td) as inside:
        moved = (inside, os.path.samefile(os.getcwd(), cyr))
    caps_nos = with_tesserocr(fake_tesserocr(), cyr_td, lambda: rp1.caps(fresh=True))
    got_nos = with_tesserocr(fake_tesserocr(), cyr_td, lambda: rp1._tesserocr())
    # a tessdata folder whose own name is outside ASCII has no such way: the one fix that works is said
    odd_td = os.path.join(cyr, "".join(chr(c) for c in (0x434, 0x430, 0x43D, 0x43D, 0x44B, 0x435)))
    os.makedirs(odd_td)
    shutil.copy2(os.path.join(cyr_td, "eng.traineddata"), odd_td)
    arg_odd = ownenv.tess_arg(odd_td)
    caps_odd = with_tesserocr(fake_tesserocr(), odd_td, lambda: rp1.caps(fresh=True))
    # the same folder down a long path (a long TEMP, a deep home): the reason was cut at 200 characters, the words
    # the fix is found by went with its end, and the report said `readpage.py --setup`
    long_td = os.path.join(cyr, "a-long-folder-name-" * 7, os.path.basename(odd_td))
    os.makedirs(long_td)
    shutil.copy2(os.path.join(cyr_td, "eng.traineddata"), long_td)
    caps_long = with_tesserocr(fake_tesserocr(), long_td, lambda: rp1.caps(fresh=True))
finally:
    ownenv.ascii_path = real_ascii
check("with no short name the folder's own name goes from its parent (ASCII; the working directory is moved for the "
      "start and put back)",
      arg_rel == "tessdata" and cwd_rel == os.path.abspath(cyr) and moved == ("tessdata", True)
      and os.getcwd() == cwd_before, str((arg_rel, cwd_rel, moved)))
check("... and OCR starts that way, and counts as working (before: dead without a word, on a volume with no short names)",
      bool(got_nos) and got_nos[1] == cyr_td and got_nos[2] == ["eng"] and caps_nos["libs"].get("tesserocr") is True
      and "eng" in caps_nos["ocr_langs"] and not caps_nos.get("ocr_error"), str(got_nos and got_nos[1:]))
rows = {r[0]: r for r in rp1.setup_rows(dict(caps_odd, keys={}))}
check("... and when the folder's own name is outside ASCII too the fix is the one that works: READ_PAGE_HOME on an ASCII path",
      arg_odd == ("", None) and caps_odd["libs"].get("tesserocr") is False
      and "outside ASCII" in (caps_odd.get("ocr_error") or "")
      and rows["tesseract"][2] == ownenv.NONASCII_FIX and "READ_PAGE_HOME" in ownenv.NONASCII_FIX,
      str((arg_odd, rows["tesseract"][2:3])))
rows = {r[0]: r for r in rp1.setup_rows(dict(caps_long, keys={}))}
check("... and down a long path too: the reason keeps what names the fix (it was cut at 200 characters, and the fix "
      "said `readpage.py --setup`)", rows["tesseract"][2] == ownenv.NONASCII_FIX
      and len(caps_long.get("ocr_error") or "") <= 300, "%d: %s" % (len(caps_long.get("ocr_error") or ""),
                                                                    rows["tesseract"][2:3]))
ownenv.ascii_path = lambda p: ""
try:
    try:
        with ownenv.tess_dir(cyr_td):
            raise RuntimeError("the start failed")
    except RuntimeError:
        pass
finally:
    ownenv.ascii_path = real_ascii
check("... and a start that fails puts the working directory back all the same", os.getcwd() == cwd_before, os.getcwd())
# a scanned PDF through all of it: `missing: ocr` with the reason, never a bare `empty`
try:
    from PIL import Image
    import pymupdf  # noqa: F401
    scan = os.path.join(cyr, "scan.pdf")
    Image.new("RGB", (800, 500), (255, 255, 255)).save(scan, "PDF", resolution=100)
    os.environ["READ_PAGE_CACHE"] = os.path.join(cyr, "cache")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rp2 = load_rp("scan")
        rp2.which = lambda name: None
        with_tesserocr(fake_tesserocr(broken_pack=True), cyr_td, lambda: rp2.main([scan, "--json"]))
    os.environ.pop("READ_PAGE_CACHE", None)
    man = json.loads(buf.getvalue())
    miss = [m for m in man.get("missing") or [] if m.get("what") == "ocr"]
    check("a scan read where OCR does not start says `missing: ocr` and why",
          bool(miss) and "does not start" in json.dumps(miss) and "ocr_error" in (man.get("signals") or {}),
          json.dumps(man.get("missing"))[:200])
except ImportError:
    print("SKIP the scan read (Pillow or PyMuPDF is not installed)")

# the real thing: the environment's tesserocr (this machine only), the pack copied under a Cyrillic folder
real_info = ownenv.load(ownenv.home())
real_py = ownenv.at(ownenv.home(), real_info.get("python"))
real_eng = os.path.join(ownenv.at(ownenv.home(), real_info.get("tessdata") or "tessdata"), "eng.traineddata")
has_tesserocr = bool(real_py and os.path.isfile(real_py)) and subprocess.run(
    [real_py, "-E", "-c", "import tesserocr"], capture_output=True, timeout=120).returncode == 0
if has_tesserocr and os.path.isfile(real_eng):             # (Windows on ARM: an environment with no tesserocr in it)
    shutil.copy2(real_eng, os.path.join(cyr_td, "eng.traineddata"))
    probe = ("import os, sys, tempfile\n"
             "sys.path.insert(0, %r)\n"
             "import envsetup, readpage, ownenv\n"
             "if os.environ.get('RP_NO_SHORT'):\n"
             "    ownenv.ascii_path = lambda p: ''          # a volume that makes no short names\n"
             "td = os.environ['READ_PAGE_TESSDATA']\n"
             "res = envsetup._check_ocr(os.path.dirname(td), {'tessdata': 'tessdata'})\n"
             "from PIL import Image, ImageDraw, ImageFont\n"
             "img = Image.new('L', (520, 90), 255)\n"
             "ImageDraw.Draw(img).text((20, 20), 'Setup check 2026', fill=0, font=ImageFont.load_default(size=40))\n"
             "png = os.path.join(os.environ['RP_PROBE_TMP'], 'x.png')\n"
             "img.save(png)\n"
             "text, info = readpage.ocr_pages([png])\n"
             "print(repr(res.get('ok')), repr(res.get('why')), '2026' in text, info.get('engine'))\n") % SCRIPTS
    probe_tmp = scratch("rp-env-probe-")                     # the picture it reads
    p = subprocess.run([real_py, "-E", "-B", "-X", "utf8", "-c", probe], capture_output=True, timeout=120,
                       env=dict(os.environ, READ_PAGE_TESSDATA=cyr_td, READ_PAGE_HOME=cyr, RP_PROBE_TMP=probe_tmp,
                                READ_PAGE_ENV_CHILD="1", READ_PAGE_CACHE=os.path.join(cyr, "cache2")))
    said = p.stdout.decode("utf-8", "replace").strip()
    check("the real tesserocr, the eng pack under a Cyrillic folder: the check passes and a picture is read",
          p.returncode == 0 and said.startswith("True ") and said.endswith("True tesserocr"),
          (said or p.stderr.decode("utf-8", "replace"))[-200:])
    p_ns = subprocess.run([real_py, "-E", "-B", "-X", "utf8", "-c", probe], capture_output=True, timeout=120,
                          env=dict(os.environ, READ_PAGE_TESSDATA=cyr_td, READ_PAGE_HOME=cyr, RP_NO_SHORT="1",
                                   RP_PROBE_TMP=probe_tmp, READ_PAGE_ENV_CHILD="1",
                                   READ_PAGE_CACHE=os.path.join(cyr, "cache3")))
    said_ns = p_ns.stdout.decode("utf-8", "replace").strip()
    check("... and on a volume that makes no short names (a runner's D:): the same, from the folder's parent",
          p_ns.returncode == 0 and said_ns.startswith("True ") and said_ns.endswith("True tesserocr"),
          (said_ns or p_ns.stderr.decode("utf-8", "replace"))[-200:])
    # a pack on disk that lists fine and does not start (cut short, put there by hand) is found by the check, which
    # starts every pack (a download is held to its SHA256, and one cut short never stays)
    with open(real_eng, "rb") as fh_:
        cut_pack = fh_.read()[:5000]
    with open(os.path.join(cyr_td, "xyz.traineddata"), "wb") as fh_:
        fh_.write(cut_pack)
    # the folder goes as --setup's check gets it, in its arguments (bytes): written into the code, a name of this
    # process's would be the UTF-8 mode child's other bytes under a POSIX locale that is not UTF-8
    p3 = subprocess.run([real_py, "-E", "-B", "-X", "utf8", "-c",
                         "import sys; sys.path.insert(0, %r); import envsetup; r = envsetup._check_ocr(sys.argv[1], "
                         "{'tessdata': 'tessdata'}); print(r['ok'], r['why'])" % SCRIPTS, cyr],
                        capture_output=True, timeout=120)
    said3 = p3.stdout.decode("utf-8", "replace").strip()
    check("a pack tesseract does not start with (a pack cut short) is found by the check, which starts each",
          said3.startswith("False ") and "xyz" in said3, said3[:120])
    os.unlink(os.path.join(cyr_td, "xyz.traineddata"))
    # the environment's own packs: OSD (the legacy engine, which a wheel may be built without) tells a Russian scan's
    # script, and the page is read with rus beside English - for an English user, whose own packs have none
    real_td = ownenv.at(ownenv.home(), real_info.get("tessdata") or "tessdata")
    if all(os.path.isfile(os.path.join(real_td, p_ + ".traineddata")) for p_ in ("osd", "rus", "eng")):
        lines_ru = ["Москва - столица России и самый большой город страны.", "Город стоит на реке Москве, в нём много",
                    "старых церквей, музеев, театров и парков.", "Каждый год сюда приезжают миллионы туристов,",
                    "чтобы увидеть Красную площадь и Кремль.", "Летом на улицах много людей, а зимой идёт снег.",
                    "Съешь же ещё этих мягких французских булок,", "да выпей чаю: широкая электрификация южных",
                    "губерний даст мощный толчок подъёму хозяйства."]
        probe_osd = ("import os, sys\n"
                     "sys.path.insert(0, %r)\n"
                     "import readpage\n"
                     "from PIL import Image, ImageDraw, ImageFont\n"
                     "font = None\n"
                     "for f in ('C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',\n"
                     "          '/System/Library/Fonts/Supplemental/Arial.ttf', '/Library/Fonts/Arial Unicode.ttf'):\n"
                     "    try:\n"
                     "        font = ImageFont.truetype(f, 30)\n"
                     "        break\n"
                     "    except OSError:\n"
                     "        pass\n"
                     "if font is None:\n"
                     "    print('SKIP no font with Cyrillic')\n"
                     "    sys.exit(0)\n"
                     "img = Image.new('L', (1240, 700), 255)\n"
                     "for i, ln in enumerate(%r):\n"
                     "    ImageDraw.Draw(img).text((60, 60 + 60 * i), ln, fill=0, font=font)\n"
                     "png = os.path.join(os.environ['RP_PROBE_TMP'], 'ru.png')\n"
                     "img.save(png, dpi=(150, 150))\n"
                     "text, info = readpage.ocr_pages([png])\n"
                     "print('+'.join(info.get('used') or []), 'Москва' in text)\n") % (SCRIPTS, lines_ru)
        p4 = subprocess.run([real_py, "-E", "-B", "-X", "utf8", "-c", probe_osd], capture_output=True, timeout=120,
                            env=dict(os.environ, READ_PAGE_TESSDATA=real_td, READ_PAGE_LANG="en", RP_PROBE_TMP=probe_tmp,
                                     READ_PAGE_ENV_CHILD="1", READ_PAGE_CACHE=os.path.join(cyr, "cache4")))
        said4 = p4.stdout.decode("utf-8", "replace").strip()
        if said4.startswith("SKIP"):
            print("SKIP a Russian scan through OSD (%s)" % said4[5:])
        else:
            check("the environment's tesserocr and osd: a Russian scan is told Cyrillic and read with rus+eng",
                  p4.returncode == 0 and said4 == "rus+eng True", (said4 or p4.stderr.decode("utf-8", "replace"))[-200:])
    else:
        print("SKIP a Russian scan through OSD (the environment has no osd or rus: set up before 2026-11-22)")
    # pages as they are scanned, cut from public-domain scans of Wikisource (tests/ocr, 1 bit, 150 dpi): a few lines
    # of an English book of 1854 upside down, which OSD turns upright; five columns of a Japanese court judgment printed
    # vertically, which jpn_vert reads (OSD calls it Latin; its English reading is unsure of itself); and a few lines of
    # German verse of the 1830s in Fraktur, which frk reads (English and deu read "Aufgeschichtet" as "ARufgefchidter")
    for fixture, packs, words, what in (
            ("upside-down.png", ("osd", "eng"), ("Himalaya", "Tibet"), "an upside-down page is turned upright and read"),
            ("vertical-ja.png", ("osd", "eng", "jpn_vert"), ("想定すること自体", "述べるまでもない", "jpn_vert"),
             "a page in vertical Japanese columns is read with jpn_vert"),
            ("fraktur.png", ("osd", "eng", "frk"), ("Johannisabend", "Aufgeschichtet", "frk"),
             "a German page in Fraktur is read with frk")):
        lacking = [p_ for p_ in packs if not os.path.isfile(os.path.join(real_td, p_ + ".traineddata"))]
        if lacking:
            print("SKIP the environment's OCR of %s (no %s: an environment set up before 2026-11-23)" % (
                fixture, "+".join(lacking)))
            continue
        probe_fix = ("import sys\nsys.path.insert(0, %r)\nimport readpage\n"
                     "text, info = readpage.ocr_pages([%r])\n"
                     "print('+'.join(info.get('used') or []))\nprint(''.join(text.split()).replace('\\u017f', 's'))\n"
                     ) % (SCRIPTS, os.path.join(HERE, "ocr", fixture))
        p5 = subprocess.run([real_py, "-E", "-B", "-X", "utf8", "-c", probe_fix], capture_output=True, timeout=120,
                            env=dict(os.environ, READ_PAGE_TESSDATA=real_td, READ_PAGE_LANG="en", READ_PAGE_ENV_CHILD="1",
                                     READ_PAGE_CACHE=os.path.join(cyr, "cache5")))
        said5 = p5.stdout.decode("utf-8", "replace")
        check("the environment's tesserocr: %s" % what, p5.returncode == 0 and all(w in said5 for w in words),
              (said5 or p5.stderr.decode("utf-8", "replace"))[-200:])
else:
    print("SKIP the real tesserocr under a Cyrillic folder (no environment here)")

# ---------------------------------------------------------------- the yt-dlp updater
# It used to ask for `yt-dlp[default]` with no floor, under the skill's current lock and a global three-day
# cutoff: a pin of the lock younger than that sent uv back to yt-dlp 2022.3.8.2, which has no `default` extra and
# needs none of them - exit 0, "success", the stamp written, every video read failing on --js-runtimes.
ud = tempfile.mkdtemp(prefix="rp-env-upd-")
junk.append(ud)
versions, calls = [], []


def fake_sh(rc):
    def sh(cmd, timeout=600, env=None):
        calls.append(list(cmd))
        return rc, "the tail of uv's answer"
    return sh


def run_update(before, after, rc, restored=None):
    """ytdlp_update with the installed version `before` and, after uv ran, `after` (then `restored`)."""
    del calls[:]
    versions[:] = [before, after] + ([restored] if restored else [])
    saved = envsetup._ytdlp_version
    envsetup._ytdlp_version = lambda py: versions.pop(0)
    try:
        for n in ("ytdlp.stamp", "ytdlp.failed"):
            if os.path.exists(os.path.join(ud, n)):
                os.unlink(os.path.join(ud, n))
        return envsetup.ytdlp_update(ud, "uv", "py", {}, fake_sh(rc), lock="ENV-LOCK")
    finally:
        envsetup._ytdlp_version = saved


ok1, note1 = run_update("2026.10.26", "2026.11.2", 0)
check("an update that worked: the floor is the version installed, the stamp says when",
      ok1 and "yt-dlp[default]>=2026.10.26" in calls[0] and "ENV-LOCK" in calls[0]
      and open(os.path.join(ud, "ytdlp.stamp"), encoding="utf-8").read().strip() == "2026.11.2"
      and not os.path.exists(os.path.join(ud, "ytdlp.failed")), "%s %s" % (note1, calls[0][5:8]))
ok2, note2 = run_update("2026.10.26", "2022.3.8.2", 0, restored="2026.10.26")             # what the old command did: success, 2022
check("a result older than what was installed is refused and put back - and is no success",
      ok2 and "kept" in note2 and len(calls) == 2 and "yt-dlp[default]==2026.10.26" in calls[1]
      and not os.path.exists(os.path.join(ud, "ytdlp.stamp")) and os.path.exists(os.path.join(ud, "ytdlp.failed")),
      "%s | %s" % (note2, [c[5] for c in calls]))
ok3, note3 = run_update("2026.10.26", "2026.10.26", 1)            # uv could not: the old one stays
check("no stamp for a look that failed (an updater killed mid-way had said 'looked' already)",
      ok3 and "kept" in note3 and not os.path.exists(os.path.join(ud, "ytdlp.stamp"))
      and os.path.exists(os.path.join(ud, "ytdlp.failed")), note3)
ok4, note4 = run_update("", "2026.11.2", 0)
check("a first install has no floor (nothing to go back to)",
      ok4 and not any(a.startswith("yt-dlp[default]>=") for a in calls[0]), str(calls[0][5:8]))
cur = envsetup.env_id("3.13.18")
os.makedirs(os.path.join(ud, "envs", "x"), exist_ok=True)
with open(os.path.join(ud, "envs", "x", envsetup.ENV_LOCK), "w", encoding="utf-8") as fh:
    fh.write("certifi==1\n")
check("the updater is constrained by the lock the environment was built from: its own copy first, the skill's "
      "when the folder's name says it is the same lock, else nothing",
      envsetup.env_lock(ud, {"env": "envs/x"}) == os.path.join(ud, "envs", "x", envsetup.ENV_LOCK)
      and envsetup.env_lock(ud, {"env": cur}) == envsetup.LOCK_FILE
      and envsetup.env_lock(ud, {"env": "envs/py3.13.18-0000000000"}) is None
      and envsetup.env_lock(ud, {}) is None, "")

# the worker: a lock of its own, no sleep after the last try, no update beside a --setup
wd = tempfile.mkdtemp(prefix="rp-env-wk-")
junk.append(wd)
os.makedirs(os.path.join(wd, "envs", "x"))
os.makedirs(os.path.join(wd, "uv", "uv-" + envsetup.UV_VERSION))
for rel in (os.path.join("uv", "uv-" + envsetup.UV_VERSION, "uv.exe" if os.name == "nt" else "uv"),
            os.path.join("envs", "x", envsetup.ENV_LOCK)):
    with open(os.path.join(wd, rel), "w", encoding="utf-8") as fh:
        fh.write("x\n")
with open(os.path.join(wd, "setup.json"), "w", encoding="utf-8") as fh:
    json.dump({"schema": ownenv.STATE_SCHEMA, "env": "envs/x", "python": "envs/x/python"}, fh)
slept, tried = [], []
real_py_ok, real_update, real_sleep = envsetup._python_ok, envsetup.ytdlp_update, envsetup.time.sleep
envsetup._python_ok = lambda py: True
envsetup.ytdlp_update = lambda *a, **k: (tried.append(1) or (True, "2026.10.26 (kept: no newer one could be fetched)"))
envsetup.time.sleep = slept.append
try:
    envsetup._ytdlp_worker(wd)
    check("a failing look is tried three times, with a pause between and none after the last",
          len(tried) == 3 and slept == [20, 20], "tries %d pauses %s" % (len(tried), slept))
    del tried[:]
    held = envsetup._try_lock(os.path.join(wd, "ytdlp.lock"))
    envsetup._ytdlp_worker(wd)                       # another update is at work
    envsetup._unlock(held)
    check("one update at a time: with ytdlp.lock held a second one does nothing", not tried, str(tried))
    held = envsetup._try_lock(os.path.join(wd, "setup.lock"))
    envsetup._ytdlp_worker(wd)                       # a --setup is at work
    envsetup._unlock(held)
    check("the update gives way to a --setup (its own lock is free again after)",
          not tried and envsetup._lock_state(os.path.join(wd, "ytdlp.lock")) == "free", str(tried))
    envsetup._ytdlp_worker(wd)
    check("... and takes setup.lock of nobody: a --setup started meanwhile finds it free",
          envsetup._lock_state(os.path.join(wd, "setup.lock")) == "free" and len(tried) == 3, "")
finally:
    envsetup._python_ok, envsetup.ytdlp_update, envsetup.time.sleep = real_py_ok, real_update, real_sleep

# a read starts the look: the stamp is the updater's, a lock keeps it to one, a failed look waits an hour
started = []
real_bg, real_status = envsetup.ytdlp_background, dict(ownenv._STATUS)
envsetup.ytdlp_background = lambda d: started.append(d) or True
yhome = tempfile.mkdtemp(prefix="rp-env-yt-")
junk.append(yhome)
stamp, failmark = os.path.join(yhome, "ytdlp.stamp"), os.path.join(yhome, "ytdlp.failed")
old = time.time() - 4 * 86400
try:
    ownenv._STATUS.update(home=yhome, used=False)
    a = ownenv.refresh_ytdlp()
    ownenv._STATUS.update(used=True)
    b = ownenv.refresh_ytdlp()                       # never looked for: now
    open(stamp, "w").close()                         # the updater's, after an update that worked
    c2 = ownenv.refresh_ytdlp()                      # a minute later: not again
    os.utime(stamp, (old, old))
    d2 = ownenv.refresh_ytdlp()                      # four days later: again
    held = envsetup._try_lock(os.path.join(yhome, "ytdlp.lock"))
    e2 = ownenv.refresh_ytdlp()                      # one is at work now
    envsetup._unlock(held)
    open(failmark, "w").close()
    f2 = ownenv.refresh_ytdlp()                      # the last look failed a moment ago
    os.utime(failmark, (time.time() - 7200, time.time() - 7200))
    g2 = ownenv.refresh_ytdlp()                      # two hours ago: again
    os.environ["READ_PAGE_SKIP"] = "update"
    h2 = ownenv.refresh_ytdlp()
    os.environ.pop("READ_PAGE_SKIP", None)
    envsetup.ytdlp_background = lambda d: False      # a job that ends it with the read: not started
    os.environ.pop("READ_PAGE_SKIP", None)
    os.unlink(failmark)
    i2 = ownenv.refresh_ytdlp()
finally:
    envsetup.ytdlp_background = real_bg
    ownenv._STATUS.clear()
    ownenv._STATUS.update(real_status)
check("a video read looks for a newer yt-dlp every three days, in the environment only, apart from the read",
      (a, b, c2, d2) == (False, True, False, True) and started == [yhome] * 3,
      "%s started %d" % ((a, b, c2, d2), len(started)))
check("... not while one is at work, nor within an hour of a look that failed, nor with READ_PAGE_SKIP=update, "
      "nor where it could not be started (and no stamp is written by the read)",
      (e2, f2, g2, h2, i2) == (False, False, True, False, False) and os.path.getmtime(stamp) == old,
      str((e2, f2, g2, h2, i2)))

# ---------------------------------------------------------------- --setup follows only a run that is at work
fd = tempfile.mkdtemp(prefix="rp-env-fol-")
junk.append(fd)
launched = []
real_launch = envsetup._launch
envsetup._launch = lambda d_, run_, ver_: (launched.append(run_) or ("", False))
finished_log = "  1/10 network   pypi.org answers\ndone in 1 min 06 s; 1.2 GB in somewhere. To remove it all, delete that folder.\n"


def follow(lock_held, state, log=finished_log):
    """envsetup.setup() in this process, its launch stubbed: what it printed, and whether it launched."""
    del launched[:]
    for n in ("setup.state", "setup.log"):
        if os.path.exists(os.path.join(fd, n)):
            os.unlink(os.path.join(fd, n))
    if state is not None:
        with open(os.path.join(fd, "setup.state"), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    with open(os.path.join(fd, "setup.log"), "w", encoding="utf-8") as fh:
        fh.write(log)
    held_ = envsetup._try_lock(os.path.join(fd, "setup.lock")) if lock_held else None
    old_env = dict((k, os.environ.get(k)) for k in ("READ_PAGE_HOME", "READ_PAGE_SETUP_WAIT"))
    os.environ.update(READ_PAGE_HOME=fd, READ_PAGE_SETUP_WAIT="1")
    buf_ = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf_):
            rc_ = envsetup.setup(SCRIPT, "test")
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if held_:
            envsetup._unlock(held_)
    return rc_, buf_.getvalue(), list(launched)


dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
fin = {"run": "last", "pid": os.getpid(), "started": time.time() - 90, "updated": time.time() - 60, "done": True, "ok": True}
rc_, out_, l_ = follow(True, fin)
check("a lock held beside a state of a run that ended is no run to follow: its log is not replayed, "
      "the work is started",
      len(l_) == 1 and "following it" not in out_ and "done in 1 min" not in out_, out_.replace("\n", " | ")[:160])
rc_, out_, l_ = follow(True, dict(fin, done=False, pid=dead.pid))
check("... nor a state whose process is gone", len(l_) == 1 and "following it" not in out_, out_.replace("\n", " | ")[:160])
rc_, out_, l_ = follow(True, dict(fin, done=False, step=3, steps=10, name="engines"))
check("... but a run still at work (not done, its process alive) is followed, and nothing is started",
      not l_ and "still working; following it" in out_ and "1/10 network" in out_, out_.replace("\n", " | ")[:160])
rc_, out_, l_ = follow(False, dict(fin, done=False))
check("a state that says 'at work' with no lock held is a run that stopped: a new one is started",
      len(l_) == 1 and "following it" not in out_, out_.replace("\n", " | ")[:160])
envsetup._launch = lambda d_, run_, ver_: ("", True)
rc_, out_, l_ = follow(False, None)
check("where the work ends with the command (a job around it), --setup says so and follows it to its end",
      "ends what a command started when the command ends" in out_, out_.replace("\n", " | ")[:160])
envsetup._launch = real_launch
real_run, real_detached = envsetup.subprocess.run, envsetup._detached
try:
    codes = []
    for rc_in, out_in in ((0, b""), (envsetup.LAUNCH_ATTACHED, b""), (1, b"boom")):
        envsetup.subprocess.run = lambda *a, rc_in=rc_in, out_in=out_in, **k: types.SimpleNamespace(returncode=rc_in, stdout=out_in)
        codes.append(envsetup._launch(fd, "run", "v"))
    envsetup.subprocess.run = real_run
    mapped = []
    for how_in in ("free", "attached"):
        envsetup._detached = lambda *a, how_in=how_in, **k: how_in
        mapped.append(envsetup._main(["--launch", fd, "run", "v"]))
finally:
    envsetup.subprocess.run, envsetup._detached = real_run, real_detached
check("the launcher tells --setup how it went (exit code 0: free; %d: attached to the command's job)" % envsetup.LAUNCH_ATTACHED,
      codes == [("", False), ("", True), ("boom", False)] and mapped == [0, envsetup.LAUNCH_ATTACHED], "%s %s" % (codes, mapped))
os.mkdir(os.path.join(fd, "no.lock"))
check("a lock file that cannot be opened (a read-only folder) is nobody's lock - the file existing proves nothing",
      envsetup._lock_state(os.path.join(fd, "no.lock")) == "unusable" and not envsetup._locked(os.path.join(fd, "no.lock")), "")

# ---------------------------------------------------------------- a read of setup.state that finds nothing is no news
# On Windows a read made while the worker replaces setup.state (a temp file, then os.replace) cannot open the file for that
# moment: once 20 s had passed, the command took such a read for a run that never started - "the work did not start",
# exit 1, while the work ran to its end (KNOWN-ISSUES 229). The worker is played: its state and its lock as a clock of the
# test's has them (time.sleep moves it), the reads that find nothing scripted - nothing here depends on timing.
real_read_json = envsetup._read_json


class PlayedWork:
    """The worker of a --setup, played for envsetup.setup(): it starts when launched (or was at work before: `earlier`),
    writes its last state at `ends` s and lets go of the lock right after the command's read of the state before it (one
    write behind the lock, as can be); `dies`: it lets go there without a last state. A read finds nothing at the first
    read past each of `torn` (s), and at the first read after the work's end with `torn_end`. `starts=False`: launched,
    it never starts."""

    strftime = staticmethod(time.strftime)

    def __init__(self, ends=40.0, torn=(), torn_end=False, earlier=False, starts=True, dies=False):
        self.t0 = self.now = 1000.0
        self.ends, self.torn, self.torn_end, self.starts, self.dies = ends, sorted(torn), torn_end, starts, dies
        self.run, self.started = ("earlier", self.t0 - 300) if earlier else (None, None)
        self.over, self.launched = False, []

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s

    def launch(self, d_, run_, ver_):
        self.launched.append(run_)
        if self.run is None and self.starts:
            self.run, self.started = run_, self.now + 0.5
        return "", False

    def locked(self, path):
        return self.run is not None and not self.over

    def read(self, path):
        if os.path.basename(path) != "setup.state":
            return real_read_json(path)
        if self.torn and self.now - self.t0 >= self.torn[0]:
            self.torn.pop(0)
            return {}
        if self.run is None or self.now < self.started:
            return {}
        st = {"run": self.run, "pid": os.getpid(), "started": self.started, "steps": 10, "done": False,
              "finished": min(9, int((self.now - self.started) / 4))}
        if self.over and not self.dies:
            if self.torn_end:
                self.torn_end = False
                return {}
            return dict(st, finished=10, done=True, ok=True)
        if self.now - self.t0 >= self.ends:
            self.over = True
        return st


pw_home = scratch("rp-env-torn-")


def played(work, home_=None):
    """envsetup.setup() following a played worker, in pw_home or `home_` (made by --setup where it is not there): (exit
    code, what it printed)."""
    home_ = home_ or pw_home
    if os.path.isdir(home_):
        with open(os.path.join(home_, "setup.log"), "w", encoding="utf-8") as fh_:
            fh_.write(finished_log)
    saved_ = (envsetup.time, envsetup._read_json, envsetup._locked, envsetup._launch)
    old_env = dict((k, os.environ.get(k)) for k in ("READ_PAGE_HOME", "READ_PAGE_SETUP_WAIT"))
    os.environ.update(READ_PAGE_HOME=home_, READ_PAGE_SETUP_WAIT="1000")
    envsetup.time, envsetup._read_json, envsetup._locked, envsetup._launch = work, work.read, work.locked, work.launch
    buf_ = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf_):
            rc_ = envsetup.setup(SCRIPT, "test")
    finally:
        envsetup.time, envsetup._read_json, envsetup._locked, envsetup._launch = saved_
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return rc_, buf_.getvalue()


rc_, out_ = played(PlayedWork(torn=(25,)))
check("a read of setup.state that finds nothing past 20 s (the worker replacing it, on Windows) is no news: --setup "
      "follows the work to its end", rc_ == 0 and "did not start" not in out_ and "stopped after" not in out_,
      out_.replace("\n", " | ")[-160:])
rc_, out_ = played(PlayedWork(torn=(1.0,)))
check("... and one right after the run was first seen", rc_ == 0 and "did not start" not in out_
      and "stopped after" not in out_, out_.replace("\n", " | ")[-160:])
rc_, out_ = played(PlayedWork(torn_end=True))
check("the worker gone (its lock let go) and the state one write behind: a read that finds nothing is read again, and "
      "the work's own end is what --setup says", rc_ == 0 and "stopped after" not in out_, out_.replace("\n", " | ")[-160:])
pw_ = PlayedWork(earlier=True, torn=(0,))
rc_, out_ = played(pw_)
check("a run at work when --setup starts, and the first read finds nothing: that run is followed, none is started",
      rc_ == 0 and not pw_.launched and "following it" in out_ and "did not start" not in out_,
      "%d launched; %s" % (len(pw_.launched), out_.replace("\n", " | ")[-140:]))
rc_, out_ = played(PlayedWork(starts=False))
check("... while a run never seen at all within the wait did not start (exit 1)",
      rc_ == 1 and "the work did not start" in out_, out_.replace("\n", " | ")[-160:])
rc_, out_ = played(PlayedWork(ends=10.0, dies=True))
check("... and a worker that let go of its lock with no last state stopped (exit 1)",
      rc_ == 1 and "the work stopped after 2 of 10 steps" in out_, out_.replace("\n", " | ")[-160:])
# the writer's side: a reader that keeps the file open stops os.replace (measured on Windows: WinError 5 while a Python
# reader holds it; a write in place goes through). Past the retries the worker raised and stopped there, and a last
# state - what the command waits for - was lost with it
wr_home = scratch("rp-env-wr-")
wr = envsetup.Work(wr_home, "wr", "test")
wr_tmp = os.path.join(wr_home, "setup.state.%d.tmp" % os.getpid())
real_replace, wr_errs = os.replace, []


def refuse_replace(src, dst, *a, **k):
    if os.path.basename(str(dst)) == "setup.state":
        raise PermissionError(13, "Permission denied", str(dst))
    return real_replace(src, dst, *a, **k)


def refuse_open(path, mode="r", *a, **k):
    if os.path.basename(str(path)) == "setup.state" and "w" in mode:
        raise PermissionError(13, "Permission denied", str(path))
    return io.open(path, mode, *a, **k)


envsetup.time, os.replace = PlayedWork(), refuse_replace
try:
    for kw_ in ({"done": False}, {"done": True, "ok": True}):
        try:
            wr.state(**kw_)
        except OSError as e:
            wr_errs.append(repr(e))
    wr_last = real_read_json(os.path.join(wr_home, "setup.state"))
    wr_left = os.path.exists(wr_tmp)
    envsetup.open = refuse_open                          # a write in place refused too
    try:
        wr.state(done=False, name="again")
    except OSError as e:
        wr_errs.append(repr(e))
    finally:
        del envsetup.open
finally:
    envsetup.time, os.replace = time, real_replace
check("a reader that keeps setup.state open past the retries loses no state: it is written in place, the last one too",
      not wr_errs[:2] and wr_last.get("done") is True and wr_last.get("ok") is True and not wr_left,
      "%s %s tmp left: %s" % (wr_errs[:2], wr_last.get("done"), wr_left))
check("... and where even that is refused the work goes on (the next state carries it), and the log says so",
      not wr_errs and "setup.state was not written" in io.open(os.path.join(wr_home, "setup-detail.log"),
                                                               encoding="utf-8").read(), str(wr_errs[2:]))

# ---------------------------------------------------------------- a home too long for the environment's DLLs (Windows)
# Windows refuses a DLL that carries a manifest (every .pyd, curl_cffi's and tesserocr's libraries) by a path over 250
# characters - WinError 206, measured - and curl_cffi's lies 116 inside the home: from a home of 135 characters it did
# not load, from 138 tesserocr, found by the check after minutes of downloads, its reason cut at 60 (KNOWN-ISSUES 230)
lh_max = getattr(envsetup, "WIN_HOME_MAX", 120)
lh_base = scratch("rp-env-lh-")
lh_over, lh_at = [os.path.join(lh_base, "h" * (n_ - len(lh_base) - 1)) for n_ in (lh_max + 1, lh_max)]
pw_over, pw_at = PlayedWork(ends=0.0), PlayedWork(ends=0.0)
rc_over, out_over = played(pw_over, lh_over)
rc_at, out_at = played(pw_at, lh_at)
if os.name == "nt":
    check("a home over %d characters is refused before anything is fetched (Windows): its length, the limit and the "
          "fix said, exit 1, nothing launched or made" % lh_max,
          rc_over == 1 and not pw_over.launched and not os.path.exists(lh_over)
          and "is %d characters long" % (lh_max + 1) in out_over and "over %d" % lh_max in out_over
          and "READ_PAGE_HOME" in out_over, out_over.replace("\n", " | ")[-220:])
else:
    check("off Windows a home over %d characters changes nothing: --setup goes on" % lh_max,
          rc_over == 0 and len(pw_over.launched) == 1, out_over.replace("\n", " | ")[-160:])
check("... and one of %d characters goes on" % lh_max, rc_at == 0 and len(pw_at.launched) == 1 and os.path.isdir(lh_at),
      out_at.replace("\n", " | ")[-160:])
# the check at the end of --setup, in a bare Python, against a curl_cffi whose import fails as it did from a long home
ck_site, ck_home = scratch("rp-env-cksite-"), scratch("rp-env-ck-")
os.makedirs(os.path.join(ck_site, "curl_cffi"))
with open(os.path.join(ck_site, "curl_cffi", "__init__.py"), "w", encoding="utf-8") as fh:
    fh.write('raise ImportError("DLL load failed while importing _wrapper: The filename or extension is too long.")\n')
p_ck = subprocess.run([sys.executable, "-I", "-S", "-B", "-X", "utf8", "-c",
                       "import sys; sys.path[:0] = [%r, %r]; import envsetup; envsetup.check(%r, %r)"
                       % (ck_site, SCRIPTS, ck_home, os.path.join(ck_home, "setup-check.json"))],
                      capture_output=True, timeout=300)
why_ck = (real_read_json(os.path.join(ck_home, "setup-check.json")).get("engines") or {}).get("why") or ""
check("the check at the end of --setup keeps an engine's whole reason (the end of an error is what says why)",
      "curl_cffi (DLL load failed while importing _wrapper: The filename or extension is too long.)" in why_ck,
      (why_ck or p_ck.stderr.decode("utf-8", "replace"))[:200])
# the margin, where a real environment is here: the install workflow runs the suites under one on Windows
lh_home = ownenv.home()
if os.name == "nt" and ownenv.load(lh_home).get("env"):
    lh_dlls = [(len(os.path.join(r_, f_)) - len(lh_home), os.path.relpath(os.path.join(r_, f_), lh_home))
               for t_ in os.listdir(lh_home) if t_ != "cache" and os.path.isdir(os.path.join(lh_home, t_))
               for r_, _d, fs_ in os.walk(os.path.join(lh_home, t_))
               for f_ in fs_ if f_.lower().endswith((".dll", ".pyd"))]
    lh_deep = max(lh_dlls) if lh_dlls else (0, "")
    lh_bound = getattr(envsetup, "WIN_DLL_PATH_MAX", 250)
    check("the environment here: its deepest DLL leaves room for a home of %d (%d + %d characters; Windows refuses a "
          "DLL by a path over %d) - a pin that moves it past the margin fails here"
          % (lh_max, lh_max, lh_deep[0], lh_bound),
          lh_deep[0] > 0 and lh_max + lh_deep[0] <= lh_bound, "%d files; %s" % (len(lh_dlls), lh_deep[1]))
else:
    print("SKIP the deepest DLL of a real environment (%s)" % ("no environment here" if os.name == "nt" else
                                                                "a DLL's path is bound on Windows alone"))
ro = tempfile.mkdtemp(prefix="rp-env-ro-")
junk.append(ro)
real_open = open


def no_write(path, mode="r", *a, **k):                 # a read-only folder: nothing can be created in it
    if "w" in mode and os.path.dirname(os.path.abspath(str(path))) == os.path.abspath(ro):
        raise PermissionError(13, "Permission denied", str(path))
    return real_open(path, mode, *a, **k)


import builtins                                          # noqa: E402
builtins.open = no_write
os.environ["READ_PAGE_HOME"] = ro
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        rc_ro = envsetup.setup(SCRIPT, "test")
finally:
    builtins.open = real_open
    os.environ.pop("READ_PAGE_HOME", None)
check("--setup in a folder it cannot write to says so at once, and exits 1",
      rc_ro == 1 and "cannot write to" in buf.getvalue(), buf.getvalue().replace("\n", " | ")[:140])

# --setup while a yt-dlp update holds ytdlp.lock: it runs its own work after the update, never someone else's log
bd = tempfile.mkdtemp(prefix="rp-env-wait-")
junk.append(bd)
upd = envsetup._try_lock(os.path.join(bd, "ytdlp.lock"))
with open(os.path.join(bd, "setup.state"), "w", encoding="utf-8") as fh:        # an old run's, finished
    json.dump({"run": "old", "pid": 1, "started": 1, "done": True, "ok": True}, fh)
with open(os.path.join(bd, "setup.log"), "w", encoding="utf-8") as fh:
    fh.write(finished_log)
t0 = time.time()
side = subprocess.Popen([sys.executable, "-X", "utf8", SCRIPT, "--setup"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        env=dict(base, READ_PAGE_HOME=bd, READ_PAGE_SETUP_WAIT="60",
                                 HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9",
                                 https_proxy="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9",
                                 NO_PROXY="", no_proxy=""))
# the update ends once the --setup's work is seen waiting for it - a fixed 4 s was a race on a loaded machine (the
# command, its launcher and its worker are three Python starts; 3.3-3.7 s measured, up to 16 s under load)
while time.time() - t0 < 60 and "waiting for it" not in (open(os.path.join(bd, "setup.log"), encoding="utf-8",
                                                               errors="replace").read()
                                                          if os.path.exists(os.path.join(bd, "setup.log")) else ""):
    time.sleep(0.2)
time.sleep(1)
envsetup._unlock(upd)                                # the update ends
out_b = side.communicate(timeout=120)[0].decode("utf-8", "replace")
check("a --setup started while the yt-dlp update works waits for it, then does its own work (and exits 1 offline)",
      side.returncode == 1 and "waiting for it" in out_b and "needs the internet" in out_b
      and "done in 1 min 06 s" not in out_b and "following it" not in out_b,
      "rc=%s %.0f s %s" % (side.returncode, time.time() - t0, out_b.replace("\n", " | ")[:200]))

# ---------------------------------------------------------------- a certificate store is not "no internet"
import ssl                                               # noqa: E402
import urllib.error                                      # noqa: E402
cd = tempfile.mkdtemp(prefix="rp-env-cert-")
junk.append(cd)
real_fj = envsetup.fetch_json


def no_roots(url, timeout=30):
    raise urllib.error.URLError(ssl.SSLCertVerificationError(
        1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"))


envsetup.fetch_json = no_roots
try:
    w = envsetup.Work(cd, "r1", "test")
    got_ok, got_note = w.network()
    w.go()
    said = open(os.path.join(cd, "setup.log"), encoding="utf-8").read()
    saved_platform = sys.platform
    sys.platform = "darwin"
    try:
        mac = envsetup.cert_advice()
    finally:
        sys.platform = saved_platform
finally:
    envsetup.fetch_json = real_fj
check("a Python with no root certificates is named so, not reported as 'no internet'",
      not got_ok and "certificate" in got_note and "no answer from pypi.org" not in got_note
      and "needs the internet" not in said and "certificate" in said and "nothing was installed" in said,
      said.strip().splitlines()[-1][:200])
check("... and on a Mac the fix is python.org's Install Certificates.command (or /usr/bin/python3)",
      "Install Certificates.command" in mac and "/usr/bin/python3" in mac, mac[:100])
check("... but a plain network error is still 'no answer'",
      envsetup.cert_error(urllib.error.URLError(ConnectionRefusedError(10061, "refused"))) is False
      and envsetup.cert_error(urllib.error.URLError(ssl.SSLCertVerificationError(1, "x"))) is True, "")

# ---------------------------------------------------------------- a download is the size it promised, a language name any pack's
import http.server                                       # noqa: E402
import threading                                         # noqa: E402


class Cut(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        full = self.path.startswith("/whole")
        body = b"x" * (100000 if full else 40000)
        self.send_response(200)
        self.send_header("Content-Length", "100000")     # the promise
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Cut)
threading.Thread(target=srv.serve_forever, daemon=True).start()
fdir = tempfile.mkdtemp(prefix="rp-env-fetch-")
junk.append(fdir)
try:
    envsetup.fetch("http://127.0.0.1:%d/cut" % srv.server_address[1], os.path.join(fdir, "deu.traineddata"))
    cut = False
except Exception as e:                                   # noqa: BLE001
    cut = "40000 of 100000" in str(e)
whole = envsetup.fetch("http://127.0.0.1:%d/whole" % srv.server_address[1], os.path.join(fdir, "whole.bin"))
srv.shutdown()
check("a body that ends before its Content-Length is refused, and nothing is kept (no hash needed)",
      cut and not os.path.exists(os.path.join(fdir, "deu.traineddata"))
      and not os.path.exists(os.path.join(fdir, "deu.traineddata.part")) and os.path.getsize(whole) == 100000, str(os.listdir(fdir)))
od = tempfile.mkdtemp(prefix="rp-env-ocr-")
junk.append(od)
asked = []


def fake_fetch(url, dest, sha=None, timeout=60):
    asked.append(url.rsplit("/", 1)[-1])
    with open(dest, "wb") as fh_:
        fh_.write(b"pack")
    return dest


real_fetch = envsetup.fetch
envsetup.fetch = fake_fetch
os.environ["READ_PAGE_OCR_LANGS"] = "eng+chi_sim + chi_sim_vert+Bad Name+srp_latn+deu_latf"
try:
    w = envsetup.Work(od, "r2", "test")
    got_ok, got_note = w.ocr_data()
finally:
    envsetup.fetch = real_fetch
    os.environ.pop("READ_PAGE_OCR_LANGS", None)
check("a language named with an underscore (chi_sim, chi_sim_vert, srp_latn) is fetched like any other",
      {"chi_sim.traineddata", "chi_sim_vert.traineddata", "srp_latn.traineddata"} <= set(asked), str(asked))
check("... and a name that is no pack's of tessdata_fast 4.1.0 is said, not dropped in silence (nor fetched)",
      "Bad Name" in got_note and "deu_latf" in got_note and "deu_latf.traineddata" not in asked, got_note)

# ---------------------------------------------------------------- tar on a Python without filters
import tarfile as _tar                                   # noqa: E402
td8 = tempfile.mkdtemp(prefix="rp-env-tar-")
junk.append(td8)
chain = os.path.join(td8, "chain.tar.gz")
with _tar.open(chain, "w:gz") as t:
    for name, target in (("l1", "."), ("l2", "l1/..")):
        ti = _tar.TarInfo(name)
        ti.type, ti.linkname = _tar.SYMTYPE, target
        t.addfile(ti)
    data = b"escaped\n"
    ti = _tar.TarInfo("l2/x")
    ti.size = len(data)
    t.addfile(ti, io.BytesIO(data))
real_filters = envsetup._tar_filters
envsetup._tar_filters = lambda: False
try:
    dest8 = os.path.join(td8, "dest")
    try:
        envsetup.unpack(chain, dest8)
        refused8 = False
    except ValueError:
        refused8 = True
    check("on a Python with no tar filters a chain of links cannot write outside (l1 -> ., l2 -> l1/.., l2/x)",
          refused8 and not os.path.exists(os.path.join(td8, "x")), os.listdir(td8))
    # a tar writes its links with "/", and a Windows link whose target has one does not resolve: Node's own
    # `bin/npm -> ../lib/node_modules/npm/bin/npm-cli.js` then looked to lead out of the folder (a Windows
    # runner, which may make links, refused it with "a chain of links out of its folder"). Seen from what
    # unpack hands os.symlink, so this holds on an account that cannot make links too
    asked_links, real_symlink = [], os.symlink

    def record_symlink(src, dst, *args, **kw):
        asked_links.append(src)
        return real_symlink(src, dst, *args, **kw)
    os.symlink = record_symlink
    try:
        try:
            envsetup.unpack(good_tar, os.path.join(td8, "ok-recorded"))
        except ValueError:
            pass                                         # where it cannot make links: what it asked for is all we need
    finally:
        os.symlink = real_symlink
    check("a link is made with this OS's separators in its target",
          asked_links == ["..%slib%snode_modules%snpm%sbin%snpm-cli.js" % ((os.sep,) * 5)], str(asked_links))
    try:
        os.symlink("x", os.path.join(td8, "can-link"))
        can_link = True
    except OSError:
        can_link = False                                 # Windows without the right to make links (Node's tar is POSIX's)
    if can_link:
        why8 = ""
        try:
            envsetup.unpack(good_tar, os.path.join(td8, "ok"))
        except ValueError as e:
            link8 = os.path.join(td8, "ok", "node-v1", "bin", "npm")
            why8 = "%s (target %r, resolved %r, folder %r)" % (
                e, os.readlink(link8) if os.path.islink(link8) else None, os.path.realpath(link8),
                os.path.realpath(os.path.join(td8, "ok")))
        check("... and Node's own layout (files, folders, links inside) still unpacks there",
              os.path.isfile(os.path.join(td8, "ok", "node-v1", "lib", "node_modules", "npm", "bin", "npm-cli.js"))
              and os.path.islink(os.path.join(td8, "ok", "node-v1", "bin", "npm")), why8)
    else:
        print("SKIP Node's tar layout without tar filters (this account cannot make symbolic links)")
    for what, mk in (("a hard link", lambda ti: (setattr(ti, "type", _tar.LNKTYPE), setattr(ti, "linkname", "a"))),
                     ("a device", lambda ti: setattr(ti, "type", _tar.CHRTYPE))):
        weird = os.path.join(td8, "weird.tar")
        with _tar.open(weird, "w") as t:
            ti = _tar.TarInfo("a")
            ti.size = 1
            t.addfile(ti, io.BytesIO(b"1"))
            ti2 = _tar.TarInfo("b")
            mk(ti2)
            t.addfile(ti2)
        try:
            envsetup.unpack(weird, os.path.join(td8, "weird"))
            r8 = False
        except ValueError:
            r8 = True
        check("... %s is refused (Node's archive has none)" % what, r8, "")
finally:
    envsetup._tar_filters = real_filters

# ---------------------------------------------------------------- the Linux browser advice runs no interpreter as root
dry = ("Missing system dependencies (3):\n  libasound2t64\n  libatk-bridge2.0-0t64\n  libnss3\n")
fixl = envsetup.browser_libs_fix(dry)
check("the browser's missing libraries are named as the machine's own `sudo apt-get install` (no sudo for root)",
      fixl == "%sapt-get install libasound2t64 libatk-bridge2.0-0t64 libnss3" % ownenv.sudo(), fixl)
check("... from names only (what is not a package name is not put in a command), and nothing when none is missing",
      envsetup.browser_libs_fix("Missing system dependencies (1):\n  libx; rm -rf ~\n") == ""
      and envsetup.browser_libs_fix("All system dependencies are installed.\n") == "", "")
src_env = open(os.path.join(SCRIPTS, "envsetup.py"), encoding="utf-8").read()
check("... and no `sudo <environment python> -m playwright` anywhere (a user-writable interpreter run as root)",
      "sudo %s -m playwright" not in src_env, "")

# ---------------------------------------------------------------- what --setup cannot install is named, with a fix
# the first CI install on Alpine (musl) and on a bare Ubuntu: "sudo apt install" on an Alpine, a reason cut at
# its start ("ur requirements are unsatisfiable"), `readpage.py --setup` offered for what it cannot give, the
# same engine named twice. uv's own words (`uv pip compile --python-platform x86_64-unknown-linux-musl`):
UV_NO_WHEEL = ("error: No solution found when resolving dependencies\n"
               "  cause: Because pymupdf-layout==1.28.2 has no wheels with a matching platform tag (e.g., "
               "`musllinux_1_2_x86_64`) and pymupdf4llm==1.28.2 depends on pymupdf-layout==1.28.2, we can conclude "
               "that pymupdf4llm==1.28.2 cannot be used.\n         And because you require pymupdf4llm==1.28.2, we "
               "can conclude that your requirements are unsatisfiable.\n\nhint: Wheels are available for "
               "`pymupdf-layout` (v1.28.2) on the following platforms: `manylinux_2_28_aarch64`, `win_amd64`\n")
UV_SDIST_ONLY = ("  x No solution found when resolving dependencies:\n  `-> Because tesserocr==2.13.0 has no usable "
                 "wheels and you require it, we can conclude that your requirements are unsatisfiable.\n"
                 "hint: Wheels are required for `tesserocr` because building from source is disabled for all "
                 "packages (i.e., with `--no-build`)\n")
UV_NETWORK = ("error: Failed to fetch: `https://pypi.org/simple/lxml/`\n  Caused by: error sending request for url\n"
              "  Caused by: dns error: failed to lookup address information\n")
check("uv's no-wheel answers are told from a failure of the network",
      envsetup.no_build(UV_NO_WHEEL) and envsetup.no_build(UV_SDIST_ONLY) and not envsetup.no_build(UV_NETWORK), "")
real_machine, real_musl = envsetup.machine, envsetup.musl
envsetup.machine, envsetup.musl = (lambda: "x64"), (lambda: True)
ownenv_machine, ownenv_musl = ownenv.machine, ownenv.musl
ownenv.machine, ownenv.musl = envsetup.machine, envsetup.musl
try:
    part, why, fixed = envsetup.package_problem("pymupdf4llm", UV_NO_WHEEL)
    here_name = "musl Linux on x64" if (os.name != "nt" and sys.platform != "darwin") else ownenv.platform_name()
    check("a package with no build here is named for this machine, in whole, not cut at its start",
          part == "pymupdf4llm" and why == "pymupdf4llm has no build for " + here_name, why)
    check("... with what a user can do (not `readpage.py --setup`, which cannot give it)",
          "none here" in fixed and "setup" not in fixed and "glibc" in fixed, fixed)
    part_b, why_b, fix_b = envsetup.package_problem("playwright", UV_NO_WHEEL)
    check("... Playwright is the browser part, and its fix does not send a user to a system Chromium that has no driver",
          part_b == "browser" and "no headless browser" in fix_b and "chromium" not in fix_b, fix_b)
    part_n, why_n, fix_n = envsetup.package_problem("lxml", UV_NETWORK)
    check("a failure that is not a missing build says what it was (the line, and its cause)",
          "has no build" not in why_n and "Failed to fetch" in why_n and "error sending request" in why_n, why_n)
finally:
    envsetup.machine, envsetup.musl = real_machine, real_musl
    ownenv.machine, ownenv.musl = ownenv_machine, ownenv_musl
if os.name == "nt":
    ownenv.machine = lambda: "arm64"
    arm_name = ownenv.platform_name()
    ownenv.machine = ownenv_machine
    check("Windows on ARM is named the way its users say it", arm_name == "Windows on ARM", arm_name)
else:
    print("SKIP the name of Windows on ARM (this is not Windows)")
check("the engines that are programs name the machine's own install of the program (OCR, PDF text)",
      envsetup.package_problem("tesserocr", UV_SDIST_ONLY)[2] == ownenv.system_install("tesseract")
      and envsetup.package_problem("pymupdf", UV_SDIST_ONLY)[2].startswith(ownenv.system_install("poppler")), "")
os_release = {"alpine": 'NAME="Alpine Linux"\nID=alpine\nVERSION_ID=3.24.1\n',
              "ubuntu": 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n', "mint": "ID=linuxmint\nID_LIKE=\"ubuntu debian\"\n",
              "fedora": "ID=fedora\n", "rocky": 'ID="rocky"\nID_LIKE="rhel centos fedora"\n',
              "suse": 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "arch": "ID=arch\n", "other": "ID=nixos\n"}
fam = {k: ownenv.linux_family(v) for k, v in os_release.items()}
check("a Linux's package manager is read from its os-release (ID and ID_LIKE)",
      fam == {"alpine": "apk", "ubuntu": "apt", "mint": "apt", "fedora": "dnf", "rocky": "dnf", "suse": "zypper",
              "arch": "pacman", "other": ""}, str(fam))
if os.name == "nt" or sys.platform == "darwin":
    print("SKIP the Linux package lines (this is %s: winget or brew)" % ("Windows" if os.name == "nt" else "macOS"))
else:
    check("the install line is the machine's own: apk on Alpine, dnf on Fedora, apt (and sudo for a user, none for root)",
          ownenv.system_install("tesseract", family="apk", root=True) == "apk add tesseract-ocr"
          and ownenv.system_install("tesseract", family="dnf", root=False) == "sudo dnf install tesseract"
          and ownenv.system_install("poppler", family="pacman", root=False) == "sudo pacman -S poppler"
          and ownenv.system_install("curl", family="", root=True) == "apt install curl"
          and ownenv.system_install("chromium", family="apt", root=False)
          == "sudo apt install chromium-browser  (or sudo snap install chromium)", "")
wk = envsetup.Work(scratch("rp-env-w-"), "rw", "test")
wk.env_py = sys.executable
wk.problems = [{"part": "browser", "why": "playwright has no build", "fix": "none here"}]
wk.sh = lambda *a, **k: (_ for _ in ()).throw(AssertionError("an installer was run"))
res_b = wk.browser()
check("the browser step does not download a browser for a Playwright that is not there (and says nothing twice)",
      res_b[0] is False and "playwright is not installed" in res_b[1] and len(wk.problems) == 1, str(res_b))
check("a broken engine that was named when it did not install is not named again as `engines`",
      envsetup.engines_covered("pymupdf4llm (No module named 'pymupdf4llm'); playwright (No module named 'playwright')",
                               [{"part": "pymupdf4llm"}, {"part": "browser"}])
      and not envsetup.engines_covered("lxml (No module named 'lxml')", [{"part": "browser"}])
      and not envsetup.engines_covered("", []), "")

# ---------------------------------------------------------------- a misspelled --setup is --setup
rp_l5 = load_rp("l5")
known_l5 = ["--setup", "--caps", "--file", "--from", "--json", "--ocr", "--dir", "--version", "--refresh", "--download"]
mis = ["--stup", "--Setup", "--setpu", "--setup=1", "--seetup", "--setup"]
check("every flag typo_fixed reads as --setup is exempt from the hop (it builds the environment from outside it)",
      all(ownenv.meant_setup(a) for a in mis)
      and all(rp_l5.typo_fixed(a.partition("=")[0], known_l5) == "--setup" for a in mis if a != "--setup=1"),
      str([(a, ownenv.meant_setup(a)) for a in mis]))
check("... and a flag that is not near it is not (the read goes into the environment)",
      not any(ownenv.meant_setup(a) for a in ("--set", "--file", "--json", "--from=3", "--ocr", "--screenshots", "-setup",
                                              "setup", "https://example.com/setup", "--allow-external", "--dir")), "")
saved = dict(os.environ)
os.environ["READ_PAGE_HOME"] = home
ownenv.use(SCRIPT, ["--stup"])
check("--stup is never sent into the environment either", ownenv.status().get("why") == "--setup works from outside it",
      str(ownenv.status()))
os.environ.clear()
os.environ.update(saved)

# ---------------------------------------------------------------- defuddle without cmd.exe, and a .cmd with cmd's own syntax
rp10 = load_rp("l10")
dd = tempfile.mkdtemp(prefix="rp-env-dd-")
junk.append(dd)
dist = os.path.join(dd, "npm", "node_modules", "defuddle", "dist")
os.makedirs(os.path.join(dist, "utils"))
for rel in ("node.js", "cli.js", os.path.join("utils", "linkedom-compat.js")):
    with open(os.path.join(dist, rel), "w", encoding="utf-8") as fh:
        fh.write("//\n")
shim = os.path.join(dd, "npm", "defuddle.cmd" if os.name == "nt" else "defuddle")
with open(shim, "w", encoding="utf-8") as fh:
    fh.write("@echo off\n" if os.name == "nt" else "#!/bin/sh\n")
dcmd = rp10.defuddle_cli_command(shim, "page.html", node="NODE")
check("defuddle is run as node on its own cli.js, never through the npm shim (a .cmd that cmd.exe reads)",
      dcmd == ["NODE", os.path.join(os.path.normpath(dist), "cli.js"), "parse", "page.html", "--markdown"], str(dcmd))
check("... and an install that is not ours is run as it is",
      rp10.defuddle_cli_command(os.path.join(dd, "other", "defuddle"), "p.html", node="NODE")
      == [os.path.join(dd, "other", "defuddle"), "parse", "p.html", "--markdown"], "")
line = rp10.cmd_line(["C:\\a b\\tool.cmd", "x&y", "p|q", "c^d", "(e)", "plain", "end\\", "a b&c"])
check("a .cmd's arguments are quoted for cmd.exe, not for the C runtime: & | ^ ( ) go inside quotes",
      line == '"C:\\a b\\tool.cmd" "x&y" "p|q" "c^d" "(e)" plain end\\ "a b&c"', str(line))
check("... and an argument cmd.exe would expand or end (%, a quote, a line break) is refused, not guessed at",
      rp10.cmd_line(["t.cmd", "%PATH%"]) is None and rp10.cmd_line(["t.cmd", 'a"b']) is None
      and rp10.cmd_line(["t.cmd", "a\nb"]) is None, "")
if os.name == "nt":
    amp = os.path.join(tempfile.mkdtemp(prefix="rp-env-amp-", dir=ascii_base()), "Tom & Jerry")   # cmd's echo is OEM-coded
    junk.append(os.path.dirname(amp))
    os.makedirs(amp)
    echo = os.path.join(amp, "echo.cmd")
    with open(echo, "w", encoding="utf-8") as fh:
        # the batch file expands its own arguments late (!A!): an & in one is its own text, not a second command
        fh.write("@echo off\r\nsetlocal enabledelayedexpansion\r\nset \"A=%~1\"\r\nset \"B=%~2\"\r\necho [!A!] [!B!]\r\n")
    rc_, so_, se_ = rp10.run_tool([echo, "a&b", os.path.join(amp, "p^q|r.html")])
    check("a .cmd in a folder with an & in its name, given arguments with & ^ |: they arrive whole",
          rc_ == 0 and so_.decode("utf-8", "replace").strip() == "[a&b] [%s]" % os.path.join(amp, "p^q|r.html"),
          "rc=%s %r %r" % (rc_, so_[:120], se_[:120]))
else:
    print("SKIP a .cmd through cmd.exe (Windows only)")

# ---------------------------------------------------------------- detached work says which way it went (KNOWN-ISSUES 128)
# A harness that runs each command in a Windows job that kills on close and lets nothing leave it ends what a
# command started with the command: --setup's worker (the "goes on in the background" printed after 100 s was
# false) and the yt-dlp updater (killed seconds in, after its stamp had said "looked").
dj = tempfile.mkdtemp(prefix="rp-env-job-")
junk.append(dj)
marker = os.path.join(dj, "ran.txt")
how1 = envsetup._detached([sys.executable, "-c", "open(%r, 'w').write('x')" % marker], dj, os.path.join(dj, "d.log"))
how2 = envsetup._detached([sys.executable, "-c", "pass"], dj, os.path.join(dj, "d.log"), attached_ok=False)
for _ in range(100):
    if os.path.exists(marker):
        break
    time.sleep(0.1)
ends = ownenv.breakaway_job_ends_us()
check("_detached starts the work and says which way: free, or attached where a job around us ends it",
      os.path.exists(marker) and how1 == ("attached" if ends else "free") and how2 == ("" if ends else "free"),
      "%r %r (a job around this test ends what it starts: %s)" % (how1, how2, ends))

# the probe's child runs with -I, which ignores the caller's PYTHONDONTWRITEBYTECODE: it must say -B itself
pyc_before = compiled()
probe = subprocess.run(ownenv._probe_argv(), capture_output=True, timeout=60)
check("the job probe's child leaves no compiled module beside the scripts",
      probe.stdout in (b"0", b"1") and compiled() == pyc_before,
      "%r %s" % (probe.stdout, sorted(n for n, t in compiled().items() if pyc_before.get(n) != t)))
try:
    import psutil
except ImportError:
    psutil = None
if os.name != "nt":
    print("SKIP the Windows jobs (a job object is Windows')")
elif psutil is None:
    print("SKIP the Windows jobs (psutil is not installed)")
else:
    import ctypes
    from ctypes import wintypes
    HELPER = os.path.join(dj, "jobhelper.py")
    READ = ("import sys, os\nsys.path.insert(0, %r)\nimport envsetup\n"
            "how = envsetup._detached([sys.executable, '-c', 'import time; time.sleep(40)  # DETACHED-MARK'], "
            "os.getcwd(), os.devnull, attached_ok=%%s)\nprint('HOW', repr(how), flush=True)\n" % SCRIPTS)
    with open(HELPER, "w", encoding="utf-8") as fh:
        fh.write("import sys, time\nsys.dont_write_bytecode = True\nsys.path.insert(0, %r)\nimport ownenv\n"
                 "time.sleep(1.5)                       # the harness has put us in its job by now\n"
                 "rc = ownenv._child([sys.argv[1], '-c', sys.argv[2]])\nprint('CHILD', rc, flush=True)\n" % SCRIPTS)

    def harness_job(breakaway):
        """A job as a harness makes it: kill on close, breakaway allowed or not."""
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        class Basic(ctypes.Structure):
            _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                        ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD), ("f", ctypes.c_size_t),
                        ("g", wintypes.DWORD), ("h", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6), ("i", ctypes.c_size_t),
                        ("j", ctypes.c_size_t), ("k", ctypes.c_size_t), ("m", ctypes.c_size_t)]
        job = k32.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000 | (0x800 if breakaway else 0)
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        return k32, job

    def detached_alive():
        out = []
        for pr in psutil.process_iter(["cmdline"]):
            try:
                cl = pr.info.get("cmdline") or []
                # only the sleeper itself: a python started with exactly that one-liner (never a shell or a
                # tool whose own command line merely mentions the marker)
                if len(cl) == 3 and cl[1] == "-c" and cl[2].endswith("time.sleep(40)  # DETACHED-MARK"):
                    out.append(pr)
            except psutil.Error:
                pass
        return out

    base_exe = getattr(sys, "_base_executable", None) or sys.executable      # not a venv's launcher
    FIRST = "import time, subprocess, sys; time.sleep(0.8); sys.exit(subprocess.call(sys.argv[1:]))"

    def in_harness_job(breakaway, attached_ok, launcher=False):
        """The hop's _child inside a harness's job runs a read that starts detached work; the harness's job
        then closes: (what _detached said, whether the work is still there). With `launcher` the hop itself
        is run by a venv's python.exe - which puts its interpreter in a job of its own, nested in the harness's
        (how an agent that starts the skill from a venv's python on Windows runs it) - as is the read."""
        k32, job = harness_job(breakaway)
        cmd = ([base_exe, "-c", FIRST, py, HELPER, py, READ % attached_ok] if launcher
               else [sys.executable, HELPER, py, READ % attached_ok])
        helper = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        k32.AssignProcessToJobObject(job, int(helper._handle))
        said, t_end = "", time.time() + 30
        while time.time() < t_end and "CHILD" not in said:
            line = helper.stdout.readline().decode("utf-8", "replace")
            if not line:
                break
            said += line
        how = re.search(r"HOW (.*)", said)
        k32.CloseHandle(job)                       # the command ends: the harness's job closes
        time.sleep(2)
        left = detached_alive()
        for pr in left:
            try:
                pr.kill()
            except psutil.Error:
                pass
        try:
            helper.kill()
        except OSError:
            pass
        return (how.group(1).strip() if how else said[-120:]), bool(left)

    for pr_ in detached_alive():                    # a straggler of an earlier, interrupted run would count as work left
        try:
            pr_.kill()
        except psutil.Error:
            pass
    for breakaway, attached_ok, want_how, want_alive, what in (
            (False, False, "''", False, "a harness's job that kills on close and lets nothing leave: the updater is not started"),
            (False, True, "'attached'", False, "... and --setup's worker, which must go on, is said to be attached (it ends with the command)"),
            (True, False, "'free'", True, "a job that lets the work break away: it is started free, and outlives the command")):
        got_how, alive = in_harness_job(breakaway, attached_ok)
        check(what, got_how == want_how and alive == want_alive, "said %s, work left: %s" % (got_how, alive))
        got_how, alive = in_harness_job(breakaway, attached_ok, launcher=True)
        check("under a venv's launcher (its job nests in the harness's and hides it): " + what.split(":")[0],
              got_how == want_how and alive == want_alive, "said %s, work left: %s" % (got_how, alive))

    # KNOWN-ISSUES 128: the first process is in its job before it starts the child, so what the read's
    # interpreter (a venv's launcher starts the real one) starts is born inside it - and goes with it
    SPAWN = ("import subprocess, sys, time; q = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', "
             "'import time; time.sleep(30)  # HOP-GRAND' + 'CHILD'], creationflags=0x200, stdin=subprocess.PIPE, "
             "stdout=subprocess.PIPE, stderr=subprocess.DEVNULL); time.sleep(30)  # HOP-CHILD")
    env_py_for_jobs = real_py if (real_py and os.path.isfile(real_py)) else py
    helper = subprocess.Popen([sys.executable, HELPER, env_py_for_jobs, SPAWN], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)
    time.sleep(5)
    below = []
    for pr in psutil.Process(helper.pid).children(recursive=True):
        try:
            below.append(pr)
        except psutil.Error:
            pass
    helper.kill()                                   # the harness kills the first process alone
    time.sleep(3)
    survivors = [pr.pid for pr in below if pr.is_running()]
    for pr in below:
        try:
            pr.kill()
        except psutil.Error:
            pass
    check("KNOWN-ISSUES 128: the hop killed alone leaves nothing of the read behind (its child, the child's children)",
          len(below) >= 3 and not survivors, "%d processes below it, alive after: %s" % (len(below), survivors))

# ---------------------------------------------------------------- what each download is checked against
import urllib.request                                    # noqa: E402
with open(envsetup.LOCK_FILE, encoding="utf-8") as fh_:
    lock_text = fh_.read()
HEX64 = re.compile(r"[0-9a-f]{64}")
blocks, cur = {}, None
for ln_ in lock_text.splitlines():
    m_ = re.match(r"([A-Za-z0-9][A-Za-z0-9._\[\],-]*)==", ln_)
    if m_:
        cur = m_.group(1)
        blocks[cur] = []
    elif cur and ln_.startswith("    --hash=sha256:"):
        blocks[cur].append(ln_.split(":", 1)[1].rstrip(" \\"))
check("the lock pins every package by content - each of its %d has the SHA256 of every file it may be" % len(blocks),
      len(blocks) == envsetup.lock_packages(lock_text) >= len(envsetup.TOP)
      and all(h_ and all(HEX64.fullmatch(x) for x in h_) for h_ in blocks.values()),
      "packages without a hash: %s" % [k for k, v in blocks.items() if not v][:5])
check("... and the engines step counts packages, not hash lines",
      envsetup.lock_packages(lock_text) == len(blocks) and envsetup.lock_packages("a==1 \\\n    --hash=sha256:" + "0" * 64) == 1, "")
check("uv's wheels and Node's archives are pinned by SHA256, every platform they come in",
      all(k.startswith("uv-%s-" % envsetup.UV_VERSION) and HEX64.fullmatch(v) for k, v in envsetup.UV_WHEEL_SHA256.items())
      and all(k.startswith("node-v%s-" % envsetup.NODE_VERSION) and HEX64.fullmatch(v) for k, v in envsetup.NODE_SHA256.items())
      and {"win-x64.zip", "win-arm64.zip", "darwin-x64.tar.gz", "darwin-arm64.tar.gz", "linux-x64.tar.gz", "linux-arm64.tar.gz"}
      <= {k.split(envsetup.NODE_VERSION + "-")[1] for k in envsetup.NODE_SHA256}
      and any("win_amd64" in k for k in envsetup.UV_WHEEL_SHA256) and any("macosx_11_0_arm64" in k for k in envsetup.UV_WHEEL_SHA256)
      and any("manylinux_2_17_x86_64" in k for k in envsetup.UV_WHEEL_SHA256) and any("musllinux" in k for k in envsetup.UV_WHEEL_SHA256),
      "%d wheels, %d archives" % (len(envsetup.UV_WHEEL_SHA256), len(envsetup.NODE_SHA256)))
try:
    pypi = envsetup.fetch_json("https://pypi.org/pypi/uv/%s/json" % envsetup.UV_VERSION, timeout=20)
    node_sums = urllib.request.urlopen(urllib.request.Request(
        "https://nodejs.org/dist/v%s/SHASUMS256.txt" % envsetup.NODE_VERSION, headers={"User-Agent": "read-page-test"}),
        timeout=20).read().decode("utf-8", "replace")
except Exception as e:                                         # noqa: BLE001
    pypi = None
    print("SKIP the pinned hashes against PyPI and nodejs.org (no answer: %s)" % str(e)[:60])
if pypi:
    live_uv = {f["filename"]: f["digests"]["sha256"] for f in pypi["urls"] if f["packagetype"] == "bdist_wheel"}
    live_node = {ln_.split("  ")[1]: ln_.split("  ")[0] for ln_ in node_sums.splitlines() if "  " in ln_}
    check("the pinned hashes are the ones PyPI and nodejs.org publish (a typo would refuse every machine)",
          live_uv == envsetup.UV_WHEEL_SHA256 and all(live_node.get(k) == v for k, v in envsetup.NODE_SHA256.items()),
          "uv wrong: %s; node wrong: %s" % ([k for k in envsetup.UV_WHEEL_SHA256 if live_uv.get(k) != envsetup.UV_WHEEL_SHA256[k]][:2],
                                            [k for k, v in envsetup.NODE_SHA256.items() if live_node.get(k) != v][:2]))

# the download is checked against what is pinned here, not against what the server says
mdir = tempfile.mkdtemp(prefix="rp-env-pin-")
junk.append(mdir)
wd_ = envsetup.Work(mdir, "r9", "test")
wd_.sh = lambda *a, **k: (1, "no pip here")
mine_uv = envsetup.pick_wheel([{"filename": n_} for n_ in envsetup.UV_WHEEL_SHA256])
asked = []


def stop_fetch(url, dest, sha=None, timeout=60):
    asked.append((url, sha))
    raise RuntimeError("stop")


real_fetch, real_fj = envsetup.fetch, envsetup.fetch_json
envsetup.fetch = stop_fetch
try:
    envsetup.fetch_json = lambda url, timeout=30: {"urls": [{"packagetype": "bdist_wheel", "filename": mine_uv["filename"],
                                                             "url": "https://files.example/" + mine_uv["filename"],
                                                             "digests": {"sha256": "0" * 64}}]}
    try:
        wd_._uv_wheel(mdir)
    except ValueError:
        pass
    pinned_asked = list(asked)
    del asked[:]
    evil = mine_uv["filename"].replace("-py3-", "-1-py3-")        # a build another maintainer added to the release
    envsetup.fetch_json = lambda url, timeout=30: {"urls": [{"packagetype": "bdist_wheel", "filename": evil,
                                                             "url": "https://files.example/" + evil,
                                                             "digests": {"sha256": "1" * 64}}]}
    try:
        wd_._uv_wheel(mdir)
    except ValueError:
        pass
    check("uv's wheel is fetched against the hash pinned here (not PyPI's), and a file that is not pinned is not fetched",
          len(pinned_asked) == 1 and pinned_asked[0][1] == envsetup.UV_WHEEL_SHA256[mine_uv["filename"]] and not asked,
          "asked %s then %s" % (pinned_asked, asked))
    if ownenv.machine() in ("x64", "arm64") and not ownenv.musl():
        calls_ = []
        real_urlopen = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: calls_.append(a) or (_ for _ in ()).throw(AssertionError("asked a host"))
        try:
            try:
                wd_._node_official()
            except RuntimeError:
                pass
        finally:
            urllib.request.urlopen = real_urlopen
        osn_ = "win" if os.name == "nt" else "darwin" if sys.platform == "darwin" else "linux"
        fname_ = "node-v%s-%s-%s%s" % (envsetup.NODE_VERSION, osn_, ownenv.machine(), ".zip" if os.name == "nt" else ".tar.gz")
        check("Node's archive is fetched against the hash pinned here, and no checksum file is asked of the host that serves it",
              len(asked) == 1 and asked[0][1] == envsetup.NODE_SHA256[fname_] and not calls_, "%s %s" % (asked, calls_))
finally:
    envsetup.fetch, envsetup.fetch_json = real_fetch, real_fj

# ---------------------------------------------------------------- one certificate store for urllib, uv and Node
kept_env = dict((k, os.environ.pop(k)) for k in ("UV_SYSTEM_CERTS", "NODE_USE_SYSTEM_CA") if k in os.environ)
try:
    e_default = envsetup.net_env()
    os.environ["UV_SYSTEM_CERTS"] = "0"
    e_user = envsetup.net_env()
finally:
    os.environ.pop("UV_SYSTEM_CERTS", None)
    os.environ.update(kept_env)
check("uv and Node are told to trust the machine's certificate store, as urllib does, unless the user set it",
      e_default.get("UV_SYSTEM_CERTS") == "1" and e_default.get("NODE_USE_SYSTEM_CA") == "1"
      and e_user.get("UV_SYSTEM_CERTS") == "0" and e_user.get("NODE_USE_SYSTEM_CA") == "1", "")
w_cert = envsetup.Work(mdir, "r10", "test")
for _ in range(2):
    w_cert.sh([sys.executable, "-c", "print('Error: unable to verify the first certificate'); raise SystemExit(1)"])
log_cert = open(os.path.join(mdir, "setup.log"), encoding="utf-8").read()
check("a step that fails on a certificate says what is going on - once, however many steps do",
      log_cert.count("failed on a certificate") == 1 and "UV_SYSTEM_CERTS" in log_cert and "SSL_CERT_FILE" in log_cert,
      log_cert.strip()[:200])

# ---------------------------------------------------------------- an environment whose Python starts and fails
bh = tempfile.mkdtemp(prefix="rp-env-bad-")
junk.append(bh)
bad_bin = os.path.join(bh, "envs", "bad", "Scripts" if os.name == "nt" else "bin")
os.makedirs(bad_bin)
bad_py = os.path.join(bad_bin, "python.exe" if os.name == "nt" else "python")
if os.name == "nt":
    shutil.copy2(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "find.exe"), bad_py)   # "Parameter format not correct", exit 2
else:
    with open(bad_py, "w", encoding="utf-8") as fh_:
        fh_.write("#!/bin/sh\necho 'python: error while loading shared libraries: libpython3.so' >&2\nexit 127\n")
    os.chmod(bad_py, 0o755)
with open(os.path.join(bh, "envs", "bad", "pyvenv.cfg"), "w", encoding="utf-8") as fh_:
    fh_.write("home = %s\n" % os.path.dirname(sys.executable))
with open(os.path.join(bh, "setup.json"), "w", encoding="utf-8") as fh_:
    json.dump(dict(info, env="envs/bad", python=os.path.relpath(bad_py, bh).replace(os.sep, "/"), problems=[],
                   built="2026-11-21T10:00:00+0000"), fh_)
bad_note = os.path.join(bh, "note.txt")
with open(bad_note, "w", encoding="utf-8") as fh_:
    fh_.write("Проверка: текст по-русски и « кавычки », 東京.\n" * 3)
# a temp folder of these two runs alone: the start-up files of reads that other processes of the machine run at
# the same time (another suite, an agent) are in the shared one
start_tmp = tempfile.mkdtemp(prefix="rp-env-starttmp-", dir=ascii_base())
junk.append(start_tmp)
own_tmp = {"TEMP": start_tmp, "TMP": start_tmp, "TMPDIR": start_tmp}
rc, out, err = run([bad_note], dict(base, READ_PAGE_HOME=bh, **own_tmp))
check("an environment Python that starts and fails: the read goes on in the machine's Python, and says why",
      rc == 0 and "Проверка: текст по-русски" in out and "environment: its Python started and ended" in out
      and "READ_PAGE_SKIP=env" in out, "rc=%s %s" % (rc, [ln for ln in out.splitlines() if "environment" in ln][:1] or (out + err)[-160:]))
c = caps(dict(base, READ_PAGE_HOME=bh, **own_tmp))
check("... and --caps says the same, instead of a Python's silence",
      (c.get("env") or {}).get("used") is False and "started and ended" in ((c.get("env") or {}).get("why") or ""), str(c.get("env")))
leftover = [n_ for n_ in os.listdir(start_tmp) if n_.startswith("read-page-start-")]
check("... leaving no start-up file behind", not leftover, str(leftover[:3]))
if os.name != "nt":
    good_run, _o, _e = run([doc], base)
    stamp_ = os.path.join(home, "setup.started")
    check("POSIX: after one run of this build has started in the environment, the stamp lets exec take over",
          good_run == 0 and os.path.isfile(stamp_)
          and open(stamp_, encoding="utf-8").read().strip() == "%s|%s" % (info["env"], info["built"]), "")
    with open(os.path.join(bh, "setup.started"), "w", encoding="utf-8") as fh_:
        fh_.write("envs/bad|2026-11-21T10:00:00+0000\n")
    rc2, out2, err2 = run([bad_note], dict(base, READ_PAGE_HOME=bh))
    check("... and with the stamp there is no way back from a failing start (exec) - the first start is the one guarded",
          rc2 != 0 and "environment: its Python started" not in out2, "rc=%s" % rc2)
else:
    print("SKIP the POSIX stamp (Windows has no exec: every run is a child, asked each time)")

# ---------------------------------------------------------------- the installer's open rows (KNOWN-ISSUES 142-145, 151)
def attempt(name, fn):
    """A check whose subject may not exist yet: an exception is a FAIL with its text, not the end of the suite."""
    try:
        good, detail = fn()
    except Exception as e:                                     # noqa: BLE001
        good, detail = False, "%s: %s" % (type(e).__name__, str(e)[:160])
    check(name, good, detail)


def work_in(prefix):
    d_ = tempfile.mkdtemp(prefix=prefix)
    junk.append(d_)
    return d_, envsetup.Work(d_, "rx", "test")


# 142: sources redirected by the environment or by configuration
user142 = tempfile.mkdtemp(prefix="rp-env-user-")
junk.append(user142)
folder142 = os.path.join(user142, "projects", "read-page-home")
os.makedirs(folder142)
os.makedirs(os.path.join(user142, ".config", "uv"))
os.makedirs(os.path.join(user142, ".config", "pip"))
os.makedirs(os.path.join(user142, "pip"))
os.makedirs(os.path.join(user142, "AppData", "uv"))
with open(os.path.join(user142, ".config", "uv", "uv.toml"), "w", encoding="utf-8") as fh_:
    fh_.write('index-url = "https://uvuser:uvsecret@uv-user.example/simple"\n')
with open(os.path.join(user142, "AppData", "uv", "uv.toml"), "w", encoding="utf-8") as fh_:
    fh_.write('index-url = "https://uvuser:uvsecret@uv-user.example/simple"\n')
with open(os.path.join(user142, "projects", "uv.toml"), "w", encoding="utf-8") as fh_:
    fh_.write('[[index]]\nurl = "https://parent.example/simple"\nexclude-newer = "2020-01-01T00:00:00Z"\n')
with open(os.path.join(user142, ".npmrc"), "w", encoding="utf-8") as fh_:
    fh_.write("registry=https://npmuser:npmsecret@npm.example/\nstrict-ssl=false\n"
              "//npm.example/:_authToken=TOKEN-NOT-FOR-THE-LOG\n; a comment\n")
with open(os.path.join(user142, ".config", "pip", "pip.conf"), "w", encoding="utf-8") as fh_:
    fh_.write("[global]\nindex-url = https://pipuser:pipsecret@pip.example/simple\ntrusted-host = pip.example\n")
with open(os.path.join(user142, "pip", "pip.ini"), "w", encoding="utf-8") as fh_:
    fh_.write("[global]\nindex-url = https://pipuser:pipsecret@pip.example/simple\ntrusted-host = pip.example\n")
env142 = {"UV_DEFAULT_INDEX": "https://bob:hunter2@mirror.example/simple", "UV_EXTRA_INDEX_URL": "https://extra.example/simple",
          "UV_INSECURE_HOST": "mirror.example", "UV_NO_VERIFY_HASHES": "1", "NODEJS_ORG_MIRROR": "http://nodes.example/dist",
          "NODE_TLS_REJECT_UNAUTHORIZED": "0", "PIP_INDEX_URL": "https://pip-env.example/simple",
          "npm_config_registry": "https://reg:regsecret@registry.example/", "APPDATA": os.path.join(user142, "AppData")}
lines142 = []


def over():
    global lines142
    lines142 = envsetup.source_overrides(env142, user142, folder142, system=False)
    text = "\n".join(lines142)
    named = all(any(ln.startswith(n + "=") for ln in lines142) for n in (
        "UV_DEFAULT_INDEX", "UV_EXTRA_INDEX_URL", "UV_INSECURE_HOST", "NODEJS_ORG_MIRROR", "NODE_TLS_REJECT_UNAUTHORIZED",
        "PIP_INDEX_URL", "npm_config_registry"))
    return named and "UV_DEFAULT_INDEX=https://mirror.example - " in text, "%d lines" % len(lines142)


attempt("every setting that redirects an installer is named, with its value", over)
attempt("... and no address gives away its user name or password, nor a token of an .npmrc",
        lambda: (not any(x in "\n".join(lines142) for x in ("hunter2", "regsecret", "uvsecret", "npmsecret", "pipsecret",
                                                          "TOKEN-NOT-FOR-THE-LOG")) and bool(lines142), ""))
attempt("an http:// mirror for Node is named as not used, an https:// one as used",
        lambda: (any("NODEJS_ORG_MIRROR=http://nodes.example - not used" in x for x in lines142)
                 and any("Node comes from it" in x for x in envsetup.source_overrides(
                     {"NODEJS_ORG_MIRROR": "https://nodes.example/dist"}, user142, folder142, system=False)), ""))
attempt("a setting that would switch off the lock's hash check is named as not passed on",
        lambda: (any(x.startswith("UV_NO_VERIFY_HASHES") and "not passed on" in x for x in lines142), ""))
attempt("TLS switched off for Node is named",
        lambda: (any(x.startswith("NODE_TLS_REJECT_UNAUTHORIZED=0") and "does not verify TLS" in x for x in lines142), ""))
attempt("uv's configuration files (the user's, and a uv.toml in a parent of the folder) are named as not read",
        lambda: (sum(1 for x in lines142 if "uv.toml sets" in x and "not read" in x) >= 2
                 and any(os.path.join("projects", "uv.toml") in x and "[[index]]" in x and "exclude-newer" in x
                         for x in lines142), [x[:90] for x in lines142 if "uv.toml" in x]))
attempt("the user's .npmrc and pip's configuration are named by their registry, index and TLS setting",
        lambda: (any(".npmrc: registry=https://npm.example - " in x for x in lines142)
                 and any(".npmrc: strict-ssl=false" in x for x in lines142)
                 and any(x.startswith(os.path.join(user142, ".config", "pip", "pip.conf") if os.name != "nt" else
                                      os.path.join(user142, "pip", "pip.ini")) and "index-url=https://pip.example - " in x
                         for x in lines142), [x[:100] for x in lines142 if "npmrc" in x or "pip." in x]))
attempt("nothing set, nothing said",
        lambda: (envsetup.source_overrides({}, user142 + "-none", scratch("rp-env-bare-"),
                                           system=False) == [], ""))
os.environ.pop("UV_NO_CONFIG", None)
os.environ.pop("UV_CONFIG_FILE", None)
e_cfg = envsetup.net_env()
os.environ["UV_NO_CONFIG"] = "0"
try:
    e_cfg_user = envsetup.net_env()
finally:
    os.environ.pop("UV_NO_CONFIG", None)
os.environ["UV_DEFAULT_INDEX"] = "https://company.example/simple"
os.environ["UV_NO_VERIFY_HASHES"] = "1"
try:
    e_idx = envsetup.net_env()
finally:
    os.environ.pop("UV_DEFAULT_INDEX", None)
    os.environ.pop("UV_NO_VERIFY_HASHES", None)
attempt("uv reads no configuration file (UV_NO_CONFIG=1), unless the user set it - where the folder is does not change "
        "what is installed - and the variables that name a mirror still reach it",
        lambda: (e_cfg.get("UV_NO_CONFIG") == "1" and e_cfg_user.get("UV_NO_CONFIG") == "0"
                 and e_idx.get("UV_DEFAULT_INDEX") == "https://company.example/simple" and e_idx.get("UV_NO_CONFIG") == "1",
                 str(e_cfg.get("UV_NO_CONFIG"))))
attempt("the variable that switches the lock's hash check off is not handed to uv",
        lambda: ("UV_NO_VERIFY_HASHES" not in e_idx, ""))
node_asked = []
real_fetch142 = envsetup.fetch


def note_fetch(url, dest, sha=None, timeout=60):
    node_asked.append(url)
    raise RuntimeError("stop")


envsetup.fetch = note_fetch
try:
    for mirror, label in (("http://nodes.example/dist", "http"), ("https://nodes.example/dist/", "https"), ("", "none")):
        d_, w_ = work_in("rp-env-nodemirror-")
        w_.env["NODEJS_ORG_MIRROR"] = mirror
        try:
            w_._node_official()
        except (RuntimeError, ValueError):
            pass
finally:
    envsetup.fetch = real_fetch142
if ownenv.machine() in ("x64", "arm64") and not ownenv.musl():
    attempt("Node from a plain-http mirror is refused: nodejs.org is used; an https mirror is used as named",
            lambda: (len(node_asked) == 3 and node_asked[0].startswith("https://nodejs.org/dist/")
                     and node_asked[1].startswith("https://nodes.example/dist/v") and node_asked[2].startswith("https://nodejs.org/dist/")
                     and not any(u.startswith("http://") for u in node_asked), str(node_asked)))
os.environ["UV_DEFAULT_INDEX"] = "https://carol:s3cret@corp.example/simple"
try:
    d142, w142 = work_in("rp-env-note-")
    w142.note_sources()
finally:
    os.environ.pop("UV_DEFAULT_INDEX", None)
log142 = open(os.path.join(d142, "setup.log"), encoding="utf-8").read()
attempt("with a mirror set, the log names it before any step, and the state keeps the lines for the report",
        lambda: ("sources set here" in log142 and "UV_DEFAULT_INDEX=https://corp.example - " in log142
                 and "s3cret" not in log142 and any("corp.example" in x for x in w142.info.get("sources") or []), log142[:160]))
rep_home = tempfile.mkdtemp(prefix="rp-env-rep-")
junk.append(rep_home)
with open(os.path.join(rep_home, "setup.json"), "w", encoding="utf-8") as fh_:
    json.dump(dict(info, problems=[], sources=["UV_DEFAULT_INDEX=https://corp.example/simple - the Python packages come "
                                              "from it, not from pypi.org"],
                   disk={"folder": 1100 * 1048576, "cache": 450 * 1048576, "cache_alone": 20 * 1048576}), fh_)
rc, out, err = run([], dict(base, READ_PAGE_HOME=rep_home))
attempt("the setup report names the sources of the last --setup, and the disk it takes with uv's cache",
        lambda: ("UV_DEFAULT_INDEX=https://corp.example - " in out and "sources" in out
                 and "uv's cache is 450 MB, 20 MB of it in no environment" in out and "1.1 GB in the folder" in out,
                 [ln for ln in out.splitlines() if "sources" in ln or "disk" in ln][:3] or (out + err)[-200:]))

# 143: the check shows this run's results, and a step that failed says so
d143, w143 = work_in("rp-env-chk-")
w143.env_py = sys.executable
stale = os.path.join(d143, "setup-check.json")
with open(stale, "w", encoding="utf-8") as fh_:
    json.dump({"engines": {"ok": True}, "defuddle": {"ok": True}, "browser": {"ok": True}, "tesseract": {"ok": True}}, fh_)
w143.sh = lambda cmd, timeout=900, env=None, cwd=None: (-1, "(timed out)")          # the check is cut off: it writes nothing
ok143, note143 = w143.check()
attempt("a check that did not finish is not the last run's answer: it says so, names it, and holds no old result",
        lambda: (ok143 is False and "did not finish" in note143 and not w143.info.get("checked")
                 and any(p["part"] == "check" and "did not finish" in p["why"] and p["fix"] for p in w143.problems)
                 and not os.path.exists(stale), note143))
d143b, w143b = work_in("rp-env-chk2-")
w143b.env_py = sys.executable


def sh_writes(cmd, timeout=900, env=None, cwd=None):
    with open(os.path.join(d143b, "setup-check.json"), "w", encoding="utf-8") as fh2:
        json.dump({"engines": {"ok": True}, "defuddle": {"ok": True}, "browser": {"ok": False, "why": "no libs", "fix": "x"},
                   "tesseract": {"ok": True}}, fh2)
    return 1, ""


w143b.sh = sh_writes
ok143b, note143b = w143b.check()
attempt("a check that ran still reports each engine as before",
        lambda: (ok143b is False and note143b == "3 of 4 answer; not: browser" and w143b.info["checked"]["engines"]["ok"], note143b))
d143c, w143c = work_in("rp-env-step-")
w143c.step("uv", lambda: (False, "no uv: nothing answered"))
w143c.step("python", lambda: (True, "python 3.13"))
w143c.step("engines", lambda: (False, "skipped: no python"), need="python")
w143c.step("node", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
log143 = open(os.path.join(d143c, "setup.log"), encoding="utf-8").read().splitlines()
attempt("a step that did not work is marked FAILED on its own line, one that did is not, and a skipped step says skipped",
        lambda: ("FAILED: no uv" in log143[0] and "FAILED" not in log143[1] and "python 3.13" in log143[1]
                 and "FAILED" not in log143[2] and "skipped: no python" in log143[2] and "FAILED: failed: RuntimeError" in log143[3],
                 log143))

# 144: an environment in use is seen on POSIX too
proc_root = tempfile.mkdtemp(prefix="rp-env-proc-")
junk.append(proc_root)
env_a = os.path.join(proc_root, "home dir", "envs", "py3.13.18-aaaaaaaaaa")
env_b = os.path.join(proc_root, "home dir", "envs", "py3.13.18-aaaaaaaaaabb")
for pid_, args_ in (("101", [os.path.join(env_a, "bin", "python"), "-E", "-X", "utf8", "/skill/scripts/mcp_server.py"]),
                    ("102", ["/usr/bin/python3", "/skill/scripts/readpage.py", "--setup"]),
                    ("103", [os.path.join(env_b, "bin", "python"), "-E", "-c", "pass"]),
                    ("104", ["/bin/sleep", env_b])):
    os.makedirs(os.path.join(proc_root, pid_))
    with open(os.path.join(proc_root, pid_, "cmdline"), "wb") as fh_:
        fh_.write(b"\0".join(a_.encode("utf-8") for a_ in args_) + b"\0")
os.makedirs(os.path.join(proc_root, "self"))                       # not a process number
os.makedirs(os.path.join(proc_root, "105"))                        # one that ended: no cmdline
got_cmds = envsetup._proc_cmdlines(proc_root)
attempt("/proc is read for the arguments of every process (a path with a space stays one argument)",
        lambda: (got_cmds is not None and len(got_cmds) == 4 and [os.path.join(env_a, "bin", "python"), "-E", "-X", "utf8",
                                                                 "/skill/scripts/mcp_server.py"] in got_cmds, str(got_cmds)[:120]))
attempt("a process that runs from an environment's folder is found; a sibling whose name starts the same way is not",
        lambda: (envsetup.uses_folder(env_a, got_cmds) and envsetup.uses_folder(env_b, got_cmds)
                 and not envsetup.uses_folder(env_a + "x", [[os.path.join(env_a, "bin", "python")]])
                 and not envsetup.uses_folder(os.path.join(proc_root, "home dir", "envs", "py3.13.18-aaaaaaaaaa"),
                                              [c_ for c_ in got_cmds if c_[0] != os.path.join(env_a, "bin", "python")
                                               and c_[0] != "/bin/sleep" and c_[0] != "/usr/bin/python3"]), ""))
os.makedirs(os.path.join(env_a, "bin"))
alias_root = os.path.join(proc_root, "alias")
try:
    os.symlink(os.path.join(proc_root, "home dir"), alias_root, target_is_directory=True)
    alias_ok = True
except (OSError, NotImplementedError):
    alias_ok = False
odd_a = os.path.join(proc_root, "home dir") + os.sep + os.sep + "envs" + os.sep + "." + os.sep + os.path.basename(env_a)
attempt("a process that names the folder another way - `//` or `/./` in the path, a second link to it - is found too",
        lambda: (envsetup.uses_folder(env_a, [[os.path.join(odd_a, "bin", "python"), "-c", "pass"]])
                 and (not alias_ok or envsetup.uses_folder(env_a, [[os.path.join(alias_root, "envs", os.path.basename(env_a),
                                                                                 "bin", "python")]]))
                 and not envsetup.uses_folder(env_a, [[os.path.join(env_b, "bin", "python")]]), "a link: %s" % alias_ok))
attempt("a line of `ps` (macOS) is judged the same way: the whole line, a space in the path included",
        lambda: (envsetup.uses_folder(env_a, ["%s -E -X utf8 /skill/scripts/mcp_server.py" % os.path.join(env_a, "bin", "python"),
                                              "/usr/bin/python3 /skill/scripts/readpage.py"])
                 and not envsetup.uses_folder(env_a, ["/usr/bin/python3 /skill/scripts/readpage.py --setup"])
                 and not envsetup.uses_folder(env_a, ["%s/bin/python -c pass" % (env_a + "x")]), ""))
if os.name != "nt":
    live_env = os.path.join(tempfile.mkdtemp(prefix="rp-env-live-"), "envs", "py-live")
    junk.append(os.path.dirname(os.path.dirname(live_env)))
    os.makedirs(os.path.join(live_env, "bin"))
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", os.path.join(live_env, "bin", "python")])
    try:
        time.sleep(0.3)
        seen_live = envsetup.env_in_use(live_env)
    finally:
        sleeper.kill()
        sleeper.wait()
    seen_gone = envsetup.env_in_use(live_env)
    attempt("POSIX: a real process that runs from the folder makes it in use; once it has ended the folder is free",
            lambda: (seen_live is True and seen_gone is False, "%s then %s" % (seen_live, seen_gone)))
else:
    print("SKIP the real process of an environment in use (Windows decides by a program that cannot be opened for writing: "
          "_running, tested where it is told)")
d144 = tempfile.mkdtemp(prefix="rp-env-tidy-")
junk.append(d144)
for n_ in ("py3.13.18-old0000001", "py3.13.18-old0000002", "py3.13.18-prev000003", "py3.13.18-cur0000004"):
    os.makedirs(os.path.join(d144, "envs", n_))
w144 = envsetup.Work(d144, "r44", "test")
w144.prev = {"env": "envs/py3.13.18-prev000003"}
w144.info = {"env": "envs/py3.13.18-cur0000004"}
real_in_use = envsetup.env_in_use
envsetup.env_in_use = lambda p: True if p.endswith("old0000001") else (None if p.endswith("old0000002") else False)
try:
    w144.tidy()
finally:
    envsetup.env_in_use = real_in_use
left = sorted(os.listdir(os.path.join(d144, "envs")))
attempt("tidy keeps the environment in use, and one it cannot tell about, besides the current and the previous; "
        "it deletes the rest",
        lambda: (left == ["py3.13.18-cur0000004", "py3.13.18-old0000001", "py3.13.18-old0000002", "py3.13.18-prev000003"],
                 str(left)))
envsetup.env_in_use = lambda p: False
try:
    w144.tidy()
finally:
    envsetup.env_in_use = real_in_use
attempt("... and when none runs, only the current and the previous stay",
        lambda: (sorted(os.listdir(os.path.join(d144, "envs"))) == ["py3.13.18-cur0000004", "py3.13.18-prev000003"], ""))

# 145: uv's cache
lock_old = "a==1 \\\n    --hash=sha256:%s\nb==2.0\nc[x]==3 ; sys_platform == 'win32'\nPillow==10\nold_pkg==1\n" % ("0" * 64)
lock_new = "a==1 \\\n    --hash=sha256:%s\nb==2.1\nc[x]==3 ; sys_platform == 'win32'\npillow==10\nnew-pkg==9\n" % ("0" * 64)
attempt("the packages an update leaves in uv's cache are the ones whose pin moved or went (names as pip compares them)",
        lambda: (envsetup.lock_pins(lock_old) == {"a": "1", "b": "2.0", "c": "3", "pillow": "10", "old-pkg": "1"}
                 and envsetup.moved_pins(lock_old, lock_new) == ["b", "old-pkg"] and envsetup.moved_pins(lock_new, lock_new) == [],
                 str(envsetup.moved_pins(lock_old, lock_new))))
d145, w145 = work_in("rp-env-cache-")
os.makedirs(os.path.join(d145, "envs", "prev"))
with open(os.path.join(d145, "envs", "prev", envsetup.ENV_LOCK), "w", encoding="utf-8") as fh_:
    fh_.write(lock_old)
w145.uv_exe = "UV"
w145.prev = {"env": "envs/prev"}
sh_calls = []
w145.sh = lambda cmd, timeout=900, env=None, cwd=None: (sh_calls.append(list(cmd)) or (0, "Removed 3 files"))
w145.drop_stale_pins(lock_new, "envs/new")
attempt("an update drops the old pins of the packages that moved from uv's cache, before it installs",
        lambda: (sh_calls == [["UV", "cache", "clean", "b", "old-pkg"]] and not getattr(w145, "cache_unknown", False), str(sh_calls)))
del sh_calls[:]
w145.drop_stale_pins(lock_old, "envs/prev")
attempt("... and does nothing when the environment is the same one", lambda: (not sh_calls, str(sh_calls)))
w145.prev = {"env": "envs/older-without-its-lock"}
w145.drop_stale_pins(lock_new, "envs/new")
attempt("... and where the old environment's lock was not kept (which wheels are stale is not known) the cache is pruned "
        "whole after the update",
        lambda: (not sh_calls and w145.cache_unknown is True, str(sh_calls)))
os.makedirs(os.path.join(d145, "cache", "uv"))
w145.info = {"env": "envs/new"}
w145.prev = {"env": "envs/older-without-its-lock"}
w145.tidy()
attempt("... by `uv cache prune --ci` (plain `uv cache prune` finds nothing to remove: measured)",
        lambda: (["UV", "cache", "prune", "--ci"] in sh_calls, str(sh_calls)))
del sh_calls[:]
w145.cache_unknown = False
real_cb = envsetup.cache_bytes
sizes_seen = [(500 << 20, 300 << 20), (200 << 20, 10 << 20)]
envsetup.cache_bytes = lambda p, seconds=20.0: sizes_seen.pop(0)
try:
    w145.tidy()
finally:
    envsetup.cache_bytes = real_cb
attempt("... and where more than 150 MB of it is in no environment (an index was changed, a version that did not clean), "
        "and the size reported is the one after",
        lambda: (["UV", "cache", "prune", "--ci"] in sh_calls and w145.cache_size == (200 << 20, 10 << 20),
                 "%s %s" % (sh_calls, w145.cache_size)))
saved_link = os.environ.pop("UV_LINK_MODE", None)
real_platform = sys.platform
try:
    sys.platform = "darwin"
    e_mac = envsetup.net_env()
    os.environ["UV_LINK_MODE"] = "copy"
    e_mac_user = envsetup.net_env()
    os.environ["UV_LINK_MODE"] = "symlink"
    e_mac_link = envsetup.net_env()
    sys.platform = "linux"
    e_linux_link = envsetup.net_env()
    os.environ.pop("UV_LINK_MODE")
    e_linux = envsetup.net_env()
finally:
    sys.platform = real_platform
    if saved_link is not None:
        os.environ["UV_LINK_MODE"] = saved_link
    else:
        os.environ.pop("UV_LINK_MODE", None)
attempt("on macOS uv links instead of cloning, so the cache costs what it does elsewhere; a link mode the user set stays "
        "- but symlink, which leaves the environment empty when --setup cleans uv's cache: hard links then",
        lambda: (e_mac.get("UV_LINK_MODE") == "hardlink" and e_mac_user.get("UV_LINK_MODE") == "copy"
                 and e_mac_link.get("UV_LINK_MODE") == "hardlink" and e_linux_link.get("UV_LINK_MODE") == "hardlink"
                 and "UV_LINK_MODE" not in e_linux,
                 str((e_mac.get("UV_LINK_MODE"), e_mac_user.get("UV_LINK_MODE"), e_mac_link.get("UV_LINK_MODE"),
                      e_linux_link.get("UV_LINK_MODE")))))
cache_dir = tempfile.mkdtemp(prefix="rp-env-cachesz-")
junk.append(cache_dir)
for n_, size_ in (("only.whl", 3000), ("shared.whl", 5000)):
    with open(os.path.join(cache_dir, n_), "wb") as fh_:
        fh_.write(b"x" * size_)
try:
    os.link(os.path.join(cache_dir, "shared.whl"), os.path.join(cache_dir, "env-copy.whl"))
    linked = True
except OSError:
    linked = False
tot145, alone145 = envsetup.cache_bytes(cache_dir)
attempt("the cache's size counts what no environment holds apart from what is hard-linked into one",
        lambda: ((tot145, alone145) == ((13000, 3000) if linked else (8000, 8000)), "%s %s linked=%s" % (tot145, alone145, linked)))
check("... and the closing line gives it",
      envsetup.Work.cache_note(13000, 3000) == " (uv's cache is 12.7 KB, 2.9 KB of it in no environment: the rest is "
                                                "hard-linked into it)" and envsetup.Work.cache_note(0, 0) == ""
      and "mostly hard-linked" in envsetup.Work.cache_note(13000, None), envsetup.Work.cache_note(13000, 3000))
del sh_calls[:]
real_ytv = envsetup._ytdlp_version
vs_ = ["2026.10.26", "2026.11.2"]
envsetup._ytdlp_version = lambda py: vs_.pop(0)
try:
    ud_ok, ud_note = envsetup.ytdlp_update(d145, "uv", "py", {}, lambda cmd, timeout=600, env=None: (sh_calls.append(list(cmd)) or (0, "ok")),
                                          lock="ENV-LOCK")
finally:
    envsetup._ytdlp_version = real_ytv
attempt("a yt-dlp update that brought a new release drops the old releases from uv's cache (one every three days)",
        lambda: (ud_ok and ["uv", "cache", "clean", "yt-dlp", "yt-dlp-ejs"] in sh_calls and sh_calls[0][:3] == ["uv", "pip", "install"],
                 str(sh_calls)[:200]))

# 151: the files that landed outside the folder land inside it
attempt("npm's compiled modules go to a folder of ours (node-compile-cache was left in the temp folder)",
        lambda: (w145.env.get("NODE_COMPILE_CACHE") == os.path.join(d145, "cache", "node-compile"), str(w145.env.get("NODE_COMPILE_CACHE"))))
rp151 = load_rp("pycache")
saved_status = dict(ownenv._STATUS)
py_home = tempfile.mkdtemp(prefix="rp-env-pyc-")
junk.append(py_home)
try:
    ownenv._STATUS.update(used=False, home=py_home)
    outside = rp151._pycache_home()
    ownenv._STATUS.update(used=True, home=py_home)
    inside = rp151._pycache_home()
finally:
    ownenv._STATUS.clear()
    ownenv._STATUS.update(saved_status)
attempt("in the environment Python's bytecode goes to its folder (cache/pycache); without one, to the temp folder as before",
        lambda: (inside == os.path.join(py_home, "cache", "pycache") and os.path.isdir(inside)
                 and outside and not outside.startswith(py_home) and outside.startswith(tempfile.gettempdir()),
                 "%s | %s" % (inside, outside)))
if os.name == "posix":
    loose = tempfile.mkdtemp(prefix="rp-env-loose-")
    junk.append(loose)
    os.makedirs(os.path.join(loose, "cache", "pycache"))
    os.chmod(os.path.join(loose, "cache"), 0o777)            # a mount with no Unix modes shows every folder so
    try:
        ownenv._STATUS.update(used=True, home=loose)
        loose_pyc = rp151._pycache_home()
    finally:
        ownenv._STATUS.clear()
        ownenv._STATUS.update(saved_status)
    attempt("POSIX: where the environment's folder looks writable by all (WSL's /mnt/c, exFAT), the bytecode goes to the "
            "temp folder's - not nowhere, which cost every read 0.25 s",
            lambda: (bool(loose_pyc) and not loose_pyc.startswith(loose) and loose_pyc.startswith(tempfile.gettempdir()),
                     str(loose_pyc)))
else:
    # a folder under C:\ (C:\read-page) inherits Authenticated Users' Modify: every signed-in user could replace the
    # environment's python.exe, its site-packages, the bytecode a read runs
    acl_dir, acl_other = tempfile.mkdtemp(prefix="rp-env-acl-"), tempfile.mkdtemp(prefix="rp-env-acl2-")
    junk += [acl_dir, acl_other]
    acl_before = envsetup.others_write(acl_dir)
    for d_ in (acl_dir, acl_other):
        subprocess.run(["icacls", d_, "/grant", "*S-1-5-11:(OI)(CI)M", "/Q"], capture_output=True, timeout=60)
    acl_opened = envsetup.others_write(acl_dir)
    open(os.path.join(acl_dir, "setup.json"), "w").close()                  # the skill's own folder
    open(os.path.join(acl_other, "notes.txt"), "w").close()                 # a folder of the user's, with more in it
    nowhere = os.path.join(acl_dir, "not-the-profile")
    acl_said, acl_warn = envsetup.secure_home(acl_dir, profile=nowhere), envsetup.secure_home(acl_other, profile=nowhere)
    attempt("Windows: a home outside the profile that the machine's other users may write in is made the user's alone "
            "where it is the skill's own, and named with the command that would where it holds more; one under the "
            "profile is left as it is",
            lambda: (acl_before is False and acl_opened is True and "yours alone now" in acl_said
                     and envsetup.others_write(acl_dir) is False and acl_warn.startswith("warning") and "icacls" in acl_warn
                     and envsetup.others_write(acl_other) is True and envsetup.secure_home(acl_other) == "",
                     "%s %s | %s | %s" % (acl_before, acl_opened, acl_said[:60], acl_warn[:60])))
    # a home that names the profile by its 8.3 name (C:\Users\RUNNER~1\..., as GitHub's runners give TEMP) is under
    # it all the same: it was taken for a folder outside the profile, its ACL changed or warned about
    import ctypes
    long_profile = tempfile.mkdtemp(prefix="rp-env-longprofile-name-")
    junk.append(long_profile)
    long_home = os.path.join(long_profile, "home")
    os.makedirs(long_home)
    subprocess.run(["icacls", long_profile, "/grant", "*S-1-5-11:(OI)(CI)M", "/Q"], capture_output=True, timeout=60)
    sbuf = ctypes.create_unicode_buffer(1024)
    short_home = sbuf.value if ctypes.windll.kernel32.GetShortPathNameW(long_home, sbuf, 1024) else ""
    short_said = envsetup.secure_home(short_home, profile=long_profile) if short_home != long_home and short_home else None
    attempt("Windows: a home named through the profile's short 8.3 name is under the profile, and left as it is",
            lambda: (short_said is None or (short_said == "" and envsetup.others_write(long_home) is True),
                     "no 8.3 names on this volume" if short_said is None else "%s | %r" % (short_home, short_said[:80])))
yt_home = tempfile.mkdtemp(prefix="rp-env-ytc-")
junk.append(yt_home)
rp151b = load_rp("ytcache")
seen_cmds = []
rp151b.run = lambda cmd, timeout=120, **kw: (seen_cmds.append(list(cmd)) or (1, b"", b""))
caps151 = rp151b.caps()
del seen_cmds[:]                                    # (caps asked tesseract what it reads)
yt_ours = os.path.join(yt_home, "envs", "x", "Scripts" if os.name == "nt" else "bin", "yt-dlp")
saved_env_var, saved_cache = os.environ.get("READ_PAGE_ENV"), os.environ.get("READ_PAGE_CACHE")
try:
    os.environ["READ_PAGE_CACHE"] = os.path.join(yt_home, "cache-test")
    os.environ["READ_PAGE_ENV"] = yt_home
    caps151["cli"]["yt-dlp"] = yt_ours
    rp151b.video_text("https://example.com/v", caps151, scratch("rp-env-ytw-"))
    caps151["cli"]["yt-dlp"] = "/usr/bin/yt-dlp"
    rp151b.video_text("https://example.com/v", caps151, scratch("rp-env-ytw-"))
finally:
    for k_, v_ in (("READ_PAGE_ENV", saved_env_var), ("READ_PAGE_CACHE", saved_cache)):
        if v_ is None:
            os.environ.pop(k_, None)
        else:
            os.environ[k_] = v_
attempt("the environment's yt-dlp keeps its own cache in the folder; another yt-dlp is left to its defaults",
        lambda: (len(seen_cmds) == 2 and "--cache-dir" in seen_cmds[0]
                 and seen_cmds[0][seen_cmds[0].index("--cache-dir") + 1] == os.path.join(yt_home, "cache", "yt-dlp")
                 and "--cache-dir" not in seen_cmds[1], str([c_[:3] for c_ in seen_cmds])))


# ---------------------------------------------------------------- Node from Playwright's wheel, npm from the registry
import base64                                            # noqa: E402
import hashlib                                           # noqa: E402


def sri(path):
    with open(path, "rb") as fh_:
        return "sha512-" + base64.b64encode(hashlib.sha512(fh_.read()).digest()).decode()


def fake_driver(env_dir, name="node"):
    """An environment folder with a file where Playwright's wheel puts its Node."""
    if os.name == "nt":
        site = os.path.join(env_dir, "Lib", "site-packages")
        name = name + ".exe"
    else:
        site = os.path.join(env_dir, "lib", "python3.13", "site-packages")
    path = os.path.join(site, "playwright", "driver", name)
    os.makedirs(os.path.dirname(path))
    with open(path, "wb") as fh_:
        fh_.write(b"not a real node")
    return path


attempt("npm's integrity is pinned in npm's own form: sha512 and base64, for the version Node 24.22.3 ships",
        lambda: (re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", envsetup.NPM_INTEGRITY) is not None
                 and re.fullmatch(r"\d+\.\d+\.\d+", envsetup.NPM_VERSION) is not None, envsetup.NPM_INTEGRITY[:30]))
try:
    reg = envsetup.fetch_json("https://registry.npmjs.org/npm/%s" % envsetup.NPM_VERSION, timeout=20)["dist"]
except Exception as e:                                         # noqa: BLE001
    reg = None
    print("SKIP npm's pinned integrity against the registry (no answer: %s)" % str(e)[:60])
if reg:
    attempt("... and it is the one the registry publishes for that version (a typo would refuse every machine)",
            lambda: (reg.get("integrity") == envsetup.NPM_INTEGRITY
                     and reg.get("tarball") == "https://registry.npmjs.org/npm/-/npm-%s.tgz" % envsetup.NPM_VERSION,
                     "%s %s" % (reg.get("integrity", "")[:30], reg.get("tarball"))))
d2 = tempfile.mkdtemp(prefix="rp-env-npm-")
junk.append(d2)
blob = os.path.join(d2, "blob.bin")
with open(blob, "wb") as fh_:
    fh_.write(b"the bytes of a tarball")
bad_tgz = [False]
try:
    envsetup.check_integrity(blob, sri(blob))
    envsetup.check_integrity(blob, "sha512-" + base64.b64encode(b"x" * 64).decode())
except ValueError:
    bad_tgz[0] = True
attempt("a file is held to its integrity: the right hash passes, another is refused", lambda: (bad_tgz[0], ""))
dw, ww = work_in("rp-env-wheelnode-")
env_rel = "envs/py3.13.18-fake"
driver = fake_driver(os.path.join(dw, "envs", "py3.13.18-fake"))
attempt("Playwright's Node is found where its wheel puts it, and '' where there is none",
        lambda: (envsetup.playwright_node(os.path.join(dw, "envs", "py3.13.18-fake")) == driver
                 and envsetup.playwright_node(os.path.join(dw, "envs", "nothing")) == "", driver))
ww.env_rel = env_rel
calls2 = []
real_off, real_whl, real_fetch2 = ww._node_official, ww._node_wheel, envsetup.fetch
ww._node_official = lambda: calls2.append("official") or (_ for _ in ()).throw(ValueError("not asked"))
ww._node_wheel = lambda: calls2.append("pypi") or (_ for _ in ()).throw(ValueError("not asked"))
envsetup.fetch = lambda *a, **k: calls2.append("fetch") or (_ for _ in ()).throw(AssertionError("a download"))
ww.sh = lambda cmd, timeout=900, env=None, cwd=None: (0, "v24.21.0")
try:
    ok_n, note_n = ww.node()
finally:
    envsetup.fetch = real_fetch2
attempt("Node is the one in Playwright's wheel: nothing is downloaded, setup.json names it, the step says where it came from",
        lambda: (ok_n and not calls2 and ww.node_bin == driver and ww.info["node_bin"] == "%s/%s" % (
            env_rel, os.path.relpath(driver, os.path.join(dw, env_rel)).replace(os.sep, "/"))
                 and "Playwright" in note_n and "v24.21.0" in note_n, "%s %s" % (note_n, calls2)))
ww2 = envsetup.Work(dw, "r2", "test")
ww2.env_rel = env_rel
calls2b = []
ww2._node_official = lambda: calls2b.append("official") or (_ for _ in ()).throw(ValueError("nodejs.org: not asked"))
ww2._node_wheel = lambda: calls2b.append("pypi") or (_ for _ in ()).throw(ValueError("pypi: not asked"))
ww2.sh = lambda cmd, timeout=900, env=None, cwd=None: (0, "v18.20.0")
ok_old, note_old = ww2.node()
attempt("a Node in the wheel older than npm 11 runs on is not used: nodejs.org's comes next, then PyPI's",
        lambda: (not ok_old and calls2b == ["official", "pypi"], "%s %s" % (note_old, calls2b)))
dw3, ww3 = work_in("rp-env-nowheel-")
ww3.env_rel = env_rel
calls3 = []
ww3._node_official = lambda: calls3.append("official") or (_ for _ in ()).throw(ValueError("musl has none"))
ww3._node_wheel = lambda: calls3.append("pypi") or os.path.join(dw3, "node", "wheel", "node")
ww3.sh = lambda cmd, timeout=900, env=None, cwd=None: (0, "v24.19.0")
ok3, note3 = ww3.node()
attempt("with no Node in a wheel (musl has no Playwright wheel) the earlier road stays: nodejs.org, then PyPI's wheel",
        lambda: (ok3 and calls3 == ["official", "pypi"] and "nodejs-wheel-binaries" in note3, "%s %s" % (note3, calls3)))

# npm's tarball: from the registry, held to the pinned integrity, unpacked beside nothing of Node's
tgz = os.path.join(d2, "npm-test.tgz")
with tarfile.open(tgz, "w:gz") as t_:
    for name_, data_ in (("package/bin/npm-cli.js", b"console.log(1)\n"), ("package/package.json", b'{"name":"npm"}')):
        ti_ = tarfile.TarInfo(name_)
        ti_.size = len(data_)
        t_.addfile(ti_, io.BytesIO(data_))
dn, wn = work_in("rp-env-npmcli-")
asked2 = []


def serve_tgz(url, dest, sha=None, timeout=60):
    asked2.append(url)
    shutil.copyfile(tgz if "bad" not in url else blob, dest)
    return dest


saved_pins = (envsetup.NPM_INTEGRITY, envsetup.NPM_VERSION)
real_fetch3 = envsetup.fetch
envsetup.NPM_INTEGRITY, envsetup.NPM_VERSION = sri(tgz), "11.1.1"
envsetup.fetch = serve_tgz
node_wheel_dir = os.path.join(dn, "driver")
os.makedirs(node_wheel_dir)
npmrc_l5 = os.path.join(dn, "user.npmrc")
open(npmrc_l5, "w").close()
for k_ in [k_ for k_ in wn.env if k_.lower().startswith("npm_config_")]:
    wn.env.pop(k_)
wn.env["npm_config_userconfig"] = npmrc_l5                  # this machine's own .npmrc stays out
try:
    cli_a = wn._npm_cli(os.path.join(node_wheel_dir, "node"))
    first = list(asked2)
    cli_b = wn._npm_cli(os.path.join(node_wheel_dir, "node"))
    wn.env["npm_config_registry"] = "https://registry.corp.example/npm-proxy/"
    shutil.rmtree(os.path.join(dn, "node"))
    wn._npm_cli(os.path.join(node_wheel_dir, "node"))
    mirror_url = asked2[-1]
    wn.env["npm_config_registry"] = "http://registry.corp.example/"
    shutil.rmtree(os.path.join(dn, "node"))
    wn._npm_cli(os.path.join(node_wheel_dir, "node"))
    http_url = asked2[-1]
    # the registry of the user's .npmrc, which wants a token: it answers 401, and registry.npmjs.org serves the tarball
    wn.env.pop("npm_config_registry")
    with open(npmrc_l5, "w", encoding="utf-8") as fh_:
        fh_.write("registry=https://npm.private.example/\n")
    del asked2[:]

    def token_wanted(url, dest, sha=None, timeout=60):
        if "npm.private.example" in url:
            asked2.append(url)
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        return serve_tgz(url, dest, sha, timeout)
    envsetup.fetch = token_wanted
    shutil.rmtree(os.path.join(dn, "node"))
    l5_cli = wn._npm_cli(os.path.join(node_wheel_dir, "node"))
    l5_asked = list(asked2)
finally:
    envsetup.fetch = real_fetch3
    envsetup.NPM_INTEGRITY, envsetup.NPM_VERSION = saved_pins
attempt("npm's tarball comes from the user's registry, the one their .npmrc names too - and where that one fails (it "
        "wants a token: 401) from registry.npmjs.org, the hash being pinned (it was 'no npm' for good)",
        lambda: (l5_asked == ["https://npm.private.example/npm/-/npm-11.1.1.tgz",
                              "https://registry.npmjs.org/npm/-/npm-11.1.1.tgz"] and os.path.isfile(l5_cli), str(l5_asked)))
attempt("a Node with no npm gets npm from the registry's tarball: its address, unpacked in the folder, used again next time",
        lambda: (first == ["https://registry.npmjs.org/npm/-/npm-11.1.1.tgz"]
                 and cli_a == os.path.join(dn, "node", "npm-11.1.1", "package", "bin", "npm-cli.js") and os.path.isfile(cli_a)
                 and cli_b == cli_a and len(first) == 1 and not os.path.exists(os.path.join(dn, "cache", "dl", "npm-11.1.1.tgz")),
                 "%s %s" % (cli_a, first)))
attempt("... a company's https registry (npm_config_registry) serves it, an http one is not used (the hash is pinned either way)",
        lambda: (mirror_url == "https://registry.corp.example/npm-proxy/npm/-/npm-11.1.1.tgz"
                 and http_url == "https://registry.npmjs.org/npm/-/npm-11.1.1.tgz", "%s | %s" % (mirror_url, http_url)))
dn2, wn2 = work_in("rp-env-npmbad-")
envsetup.NPM_INTEGRITY, envsetup.NPM_VERSION = sri(tgz), "11.1.1"
envsetup.fetch = lambda url, dest, sha=None, timeout=60: serve_tgz("https://bad/" + url, dest)       # other bytes than pinned
refused2 = False
try:
    wn2._npm_cli(os.path.join(dn2, "driver", "node"))
except ValueError:
    refused2 = True
finally:
    envsetup.fetch = real_fetch3
    envsetup.NPM_INTEGRITY, envsetup.NPM_VERSION = saved_pins
attempt("a tarball that is not the pinned one is refused, and nothing of it is kept",
        lambda: (refused2 and not os.path.exists(os.path.join(dn2, "node", "npm-11.1.1"))
                 and not any(n_.endswith(".tgz") for n_ in os.listdir(os.path.join(dn2, "cache", "dl"))), ""))
dn3, wn3 = work_in("rp-env-npmbeside-")
beside = os.path.join(dn3, "node", "node-v24", "node_modules", "npm", "bin", "npm-cli.js") if os.name == "nt" else \
    os.path.join(dn3, "node", "node-v24", "lib", "node_modules", "npm", "bin", "npm-cli.js")
os.makedirs(os.path.dirname(beside))
with open(beside, "w") as fh_:
    fh_.write("x")
envsetup.fetch = lambda *a, **k: (_ for _ in ()).throw(AssertionError("a download"))
try:
    got_beside = wn3._npm_cli(os.path.join(dn3, "node", "node-v24", "node.exe" if os.name == "nt" else "bin/node"))
finally:
    envsetup.fetch = real_fetch3
attempt("a Node that brings its own npm (nodejs.org's, PyPI's) is used with it: nothing is fetched",
        lambda: (got_beside == beside, got_beside))
dt, wt = work_in("rp-env-nodetidy-")
for n_ in ("node-v24.22.3-win-x64", "npm-11.19.1", "wheel-24.19.0"):
    os.makedirs(os.path.join(dt, "node", n_))
wt.info = {"env": "envs/x", "node_bin": "envs/x/Lib/site-packages/playwright/driver/node.exe",
           "npm_cli": "node/npm-11.19.1/package/bin/npm-cli.js"}
wt.prev = {}
wt.tidy()
attempt("tidy keeps the npm in use and removes a Node of nodejs.org's or PyPI's that nothing names any more (the saving)",
        lambda: (sorted(os.listdir(os.path.join(dt, "node"))) == ["npm-11.19.1"], str(os.listdir(os.path.join(dt, "node")))))


# a browser that cannot be had names the machine's own Chromium as its fix (an OS Playwright has no build for: Ubuntu 20.04)
db, wb = work_in("rp-env-browserfix-")
wb.env_py = sys.executable
wb.sh = lambda cmd, timeout=900, env=None, cwd=None: (1, "Error: ERROR: Playwright does not support chromium-headless-shell on ubuntu20.04-x64")
ok_b2, note_b2 = wb.browser()
db2, wb2 = work_in("rp-env-browserfix2-")
wb2.env_py = sys.executable
wb2.sh = lambda cmd, timeout=900, env=None, cwd=None: (1, "getaddrinfo ENOTFOUND cdn.playwright.dev")
wb2.browser()
attempt("a browser Playwright has no build for is named with a fix - the machine's own Chromium; a download that failed says "
        "once more or through a mirror first (a floor with no fix turned the container job red)",
        lambda: (not ok_b2 and wb.problems[0]["part"] == "browser" and wb.problems[0]["fix"] == envsetup._system_fix("browser")
                 and "PLAYWRIGHT_DOWNLOAD_HOST" in wb2.problems[0]["fix"] and envsetup._system_fix("browser") in wb2.problems[0]["fix"],
                 str(wb.problems[0]["fix"])[:100]))
attempt("macOS' certificate advice names SSL_CERT_FILE for a proxy that inspects TLS (neither Python reads the keychain)",
        lambda: ((lambda saved: (setattr(sys, "platform", "darwin"), envsetup.cert_advice(), setattr(sys, "platform", saved))[1])(sys.platform)
                 .count("SSL_CERT_FILE") == 1, ""))

# ---------------------------------------------------------------- mirrors for a user in mainland China, and OCR in the user's own language
attempt("a tessdata mirror: a folder or a template, https only; without one GitHub's raw host",
        lambda: (envsetup.tessdata_url("chi_sim", {}) == envsetup.TESSDATA_URL % "chi_sim"
                 and envsetup.tessdata_url("deu", {"READ_PAGE_TESSDATA_URL": "https://m.example/fast/"}) == "https://m.example/fast/deu.traineddata"
                 and envsetup.tessdata_url("deu", {"READ_PAGE_TESSDATA_URL": "https://m.example/{lang}.bin"}) == "https://m.example/deu.bin"
                 and envsetup.tessdata_url("deu", {"READ_PAGE_TESSDATA_URL": "http://m.example/fast"}) == envsetup.TESSDATA_URL % "deu", ""))
over3 = envsetup.source_overrides({"READ_PAGE_TESSDATA_URL": "https://carol:pw@m.example/fast"}, user142, folder142, system=False) + \
    envsetup.source_overrides({"READ_PAGE_TESSDATA_URL": "http://m.example/fast"}, user142, folder142, system=False)
attempt("... and it is named in the log and the report: used when https, not used otherwise, credentials left out",
        lambda: (any(x.startswith("READ_PAGE_TESSDATA_URL=https://m.example - the OCR language data comes from it") for x in over3)
                 and any(x.startswith("READ_PAGE_TESSDATA_URL=http://m.example - not used") for x in over3)
                 and not any("pw@" in x for x in over3), str(over3)[:200]))
pipdir = tempfile.mkdtemp(prefix="rp-env-pipcfg-")
junk.append(pipdir)
pip_ini = os.path.join(pipdir, "pip.ini")
with open(pip_ini, "w", encoding="utf-8") as fh_:
    fh_.write("[global]\nindex-url = https://pipuser:pipsecret@mirrors.example/pypi/simple\ntrusted-host = mirrors.example\n")
no_index = os.path.join(pipdir, "other.ini")
with open(no_index, "w", encoding="utf-8") as fh_:
    fh_.write("[global]\ntimeout = 60\n")
saved3 = dict((k_, os.environ.pop(k_)) for k_ in ("UV_DEFAULT_INDEX", "UV_INDEX_URL", "PIP_INDEX_URL", "PIP_CONFIG_FILE") if k_ in os.environ)
try:
    os.environ["PIP_CONFIG_FILE"] = pip_ini
    e_pipcfg = envsetup.net_env()
    over_pip = envsetup.source_overrides(dict(os.environ), user142, folder142, system=False)
    os.environ["UV_DEFAULT_INDEX"] = "https://explicit.example/simple"
    e_explicit = envsetup.net_env()
    os.environ.pop("UV_DEFAULT_INDEX")
    os.environ["PIP_CONFIG_FILE"] = no_index
    e_noidx = envsetup.net_env()
finally:
    os.environ.pop("UV_DEFAULT_INDEX", None)
    os.environ.pop("PIP_CONFIG_FILE", None)
    os.environ.update(saved3)
attempt("pip's own configuration names the index when no variable does (uv reads none of it): taken for uv, named in the log "
        "with its credentials left out, and a variable of uv's still wins",
        lambda: (e_pipcfg.get("UV_DEFAULT_INDEX") == "https://pipuser:pipsecret@mirrors.example/pypi/simple"
                 and any("taken as UV_DEFAULT_INDEX" in x and "pip.ini: index-url=https://mirrors.example - " in x for x in over_pip)
                 and not any("pipsecret" in x for x in over_pip)
                 and e_explicit.get("UV_DEFAULT_INDEX") == "https://explicit.example/simple"
                 and "UV_DEFAULT_INDEX" not in e_noidx, str(over_pip)[:240]))
po = tempfile.mkdtemp(prefix="rp-env-piporder-")
junk.append(po)
po_sys, po_app, po_home = (os.path.join(po, n_) for n_ in ("system", "user-new", "home"))
po_files = {"sys": os.path.join(po_sys, "pip", "pip.conf" if os.name != "nt" else "pip.ini"),
            "new": os.path.join(po_app, "pip", "pip.conf" if os.name != "nt" else "pip.ini"),
            "old": os.path.join(po_home, ".pip" if os.name != "nt" else "pip", "pip.conf" if os.name != "nt" else "pip.ini"),
            "own": os.path.join(po, "own.ini")}
po_env = {"PROGRAMDATA": po_sys, "APPDATA": po_app} if os.name == "nt" else {"XDG_CONFIG_DIRS": po_sys, "XDG_CONFIG_HOME": po_app}
# the system's files are the machine's own on macOS, and /etc/pip.conf is one wherever it is there: left out then
po_system = os.name == "nt" or (sys.platform != "darwin" and not os.path.exists("/etc/pip.conf"))


def pip_order(texts, own=None):
    """The index-url pip_config_index finds with these files ({which: text}) and PIP_CONFIG_FILE=own."""
    for which, path in po_files.items():
        if os.path.exists(path):
            os.unlink(path)
        if which in texts:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh2:
                fh2.write(texts[which])
    got_ = envsetup.pip_config_index(dict(po_env, **({"PIP_CONFIG_FILE": own} if own else {})), po_home, system=po_system)
    return got_[1] if got_ else None


order = [pip_order({"old": "[global]\nindex-url = https://old.example/\n", "new": "[global]\nindex-url = https://new.example/\n"}),
         pip_order({"old": "[install]\nindex-url = https://old.example/\n", "new": "[global]\nindex-url = https://new.example/\n"}),
         pip_order({"new": "[global]\nindex-url = https://new.example/\n", "own": "[global]\nindex-url = https://own.example/\n"},
                   own=po_files["own"]),
         pip_order({"new": "[global]\nindex-url = https://new.example/\n"}, own=os.devnull)]
if po_system:
    order.append(pip_order({"sys": "[install]\nindex-url = https://sys.example/\n",
                            "own": "[global]\nindex-url = https://own.example/\n"}, own=po_files["own"]))
attempt("pip's configuration is read as pip reads it: the newer user file over the older, [install] over [global] in "
        "any file, PIP_CONFIG_FILE in place of the user's and over the system's, os.devnull for none",
        lambda: (order == ["https://new.example/", "https://old.example/", "https://own.example/", None]
                 + (["https://sys.example/"] if po_system else []), str(order)))
attempt("the language's OCR pack: Chinese by script, the others by language, English and C need none",
        lambda: ([ownenv.ocr_pack_for(x) for x in ("zh_CN", "zh-CN", "zh_Hans_CN", "zh-TW", "zh_Hant_HK", "zh_MO.UTF-8", "ja_JP.UTF-8",
                                                  "ko-KR", "ru_RU", "de_DE@euro", "sr_Latn_RS", "nb_NO", "en_US", "C", "", "xx_YY")]
                 == ["chi_sim", "chi_sim", "chi_sim", "chi_tra", "chi_tra", "chi_tra", "jpn", "kor", "rus", "deu", "srp_latn", "nor",
                     "", "", "", ""], ""))
# the OCR packs --setup fetches for everyone: the ten with the most web text (Common Crawl), four scripts English reads
# as nothing (Arabic, Greek, Thai, Hebrew), and osd, which tells the script of a scanned page so that each page is read
# with its own pack (2026-11-22); the vertical packs of Chinese, Japanese and Korean, for pages printed in columns, and
# Fraktur's (2026-11-23)
DEFAULTS = ["eng", "rus", "chi_sim", "chi_tra", "jpn", "kor", "deu", "fra", "spa", "por", "ara", "ell", "tha", "heb",
            "jpn_vert", "chi_tra_vert", "chi_sim_vert", "kor_vert", "frk"]


def ocr_set(*own):
    """English, the user's own packs, the rest of the defaults, osd."""
    return ["eng"] + list(own) + [p for p in DEFAULTS[1:] if p not in own] + ["osd"]


attempt("the machine's language is read from the environment where the OS has no word (LC_ALL first, C and POSIX skipped)",
        lambda: (ownenv.system_language({"LC_ALL": "zh_CN.GBK", "LANG": "en_US.UTF-8"}) == "zh_CN.GBK"
                 and ownenv.system_language({"LC_ALL": "C", "LANG": "ja_JP.eucJP"}) == "ja_JP.eucJP"
                 and ownenv.system_language({"LANGUAGE": "ko:en"}) == "ko" and ownenv.system_language({"LANG": "POSIX"}) == "", ""))
attempt("--setup's OCR packs: the fourteen (the ten with the most web text, four scripts English reads as nothing), "
        "the vertical packs of Chinese, Japanese and Korean, Fraktur's, and osd for everyone, the user's own language's "
        "first (a Polish user's beside them)",
        lambda: (ownenv.ocr_default_packs({"LANG": "en_US.UTF-8"}) == ocr_set()
                 and ownenv.ocr_default_packs({"LANG": "zh_CN.UTF-8"}) == ocr_set("chi_sim")
                 and ownenv.ocr_default_packs({"LANG": "pl_PL.UTF-8"}) == ocr_set("pol"),
                 str((ownenv.ocr_default_packs({"LANG": "en_US.UTF-8"}), ownenv.ocr_default_packs({"LANG": "pl_PL.UTF-8"})))))
real_lang4, real_os4 = ownenv.system_language, getattr(ownenv, "_os_languages", None)
saved_language4 = os.environ.pop("LANGUAGE", None)
try:
    ownenv.system_language = lambda env=None: "en-150"
    ownenv._os_languages = lambda: ["en-US", "ru"]                 # an English Windows with Russian in its list
    packs_en_ru = ownenv.ocr_default_packs(os.environ)
    ownenv.system_language = lambda env=None: "zh-CN"
    ownenv._os_languages = lambda: ["zh-Hans-CN", "ja", "ko-KR", "de-DE", "fr-FR"]
    packs_many = ownenv.ocr_default_packs(os.environ)
finally:
    ownenv.system_language = real_lang4
    if real_os4 is not None:
        ownenv._os_languages = real_os4
    if saved_language4 is not None:
        os.environ["LANGUAGE"] = saved_language4
attempt("... and the user's other languages count: an English Windows with Russian in its language list gets rus first "
        "(at most three of the user's packs beyond English), and so does LANGUAGE's list on POSIX",
        lambda: (packs_en_ru == ocr_set("rus") and packs_many == ocr_set("chi_sim", "jpn", "kor")
                 and ownenv.ocr_default_packs({"LANG": "ru_RU.UTF-8", "LANGUAGE": "ru:en:de"}) == ocr_set("rus", "deu")
                 and ownenv.ocr_default_packs({"LANG": "pl_PL.UTF-8", "LANGUAGE": "pl:uk:el:tr"}) == ocr_set("pol", "ukr", "ell"),
                 str((packs_en_ru, packs_many))))
asked3 = []


def fetch_names(url, dest, sha=None, timeout=60):
    asked3.append(url)
    with open(dest, "wb") as fh_:
        fh_.write(b"pack")
    return dest


real_lang3, real_fetch4 = ownenv.system_language, envsetup.fetch
real_os3 = getattr(ownenv, "_os_languages", None)
ownenv._os_languages = lambda: []                  # the language list of the machine that runs the suite stays out
saved_language3 = os.environ.pop("LANGUAGE", None)
envsetup.fetch = fetch_names
results3 = {}
try:
    for label_, lang_, named_ in (("zh", "zh-CN", ""), ("en", "en-US", ""), ("ru", "ru-RU", ""), ("zh+hin", "zh-TW", "hin")):
        ownenv.system_language = lambda env=None, v=lang_: v
        d_, w_ = work_in("rp-env-ocrpack-")
        del asked3[:]
        if named_:
            os.environ["READ_PAGE_OCR_LANGS"] = named_
        try:
            ok_, note_ = w_.ocr_data()
        finally:
            os.environ.pop("READ_PAGE_OCR_LANGS", None)
        results3[label_] = ([u_.rsplit("/", 1)[-1] for u_ in asked3], w_.info.get("ocr_langs"), note_)
    os.environ["READ_PAGE_TESSDATA_URL"] = "https://m.example/fast"
    ownenv.system_language = lambda env=None: "zh-CN"
    d_, w_ = work_in("rp-env-ocrpack-")
    del asked3[:]
    w_.env["READ_PAGE_TESSDATA_URL"] = "https://m.example/fast"
    w_.ocr_data()
    mirror_asked = list(asked3)
finally:
    os.environ.pop("READ_PAGE_TESSDATA_URL", None)
    ownenv.system_language, envsetup.fetch = real_lang3, real_fetch4
    if real_os3 is not None:
        ownenv._os_languages = real_os3
    if saved_language3 is not None:
        os.environ["LANGUAGE"] = saved_language3
attempt("--setup fetches the default packs and osd for everyone, the user's own language's first",
        lambda: (results3["zh"][0] == [p + ".traineddata" for p in ocr_set("chi_sim")]
                 and results3["zh"][1] == ocr_set("chi_sim")[:-1]
                 and results3["en"][0] == [p + ".traineddata" for p in ocr_set()] and results3["en"][1] == DEFAULTS
                 and results3["ru"][0] == [p + ".traineddata" for p in ocr_set("rus")], str(results3)[:300]))
attempt("... READ_PAGE_OCR_LANGS adds to them, and the step says which it took, why, and which flag names others",
        lambda: (results3["zh+hin"][1] == ocr_set("chi_tra")[:-1] + ["hin"]
                 and "the user's languages (zh-TW)" in results3["zh+hin"][2] and "osd" in results3["zh+hin"][2]
                 and "--setup --ocr-langs eng+hin names others" in results3["zh+hin"][2], results3["zh+hin"][2]))
attempt("... from the mirror when one is named",
        lambda: (mirror_asked == ["https://m.example/fast/%s.traineddata" % p for p in ocr_set("chi_sim")], str(mirror_asked)))
tools_home = tempfile.mkdtemp(prefix="rp-env-ocrtools-")
junk.append(tools_home)
saved_ocr = os.environ.pop("READ_PAGE_OCR_LANGS", None)
saved_path3 = os.environ.get("PATH"), os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), os.environ.get("READ_PAGE_ENV"), os.environ.get("READ_PAGE_TESSDATA")
try:
    ownenv._tools(tools_home, {"ocr_langs": ["eng", "rus", "chi_sim", "osd"]})
    default_langs = os.environ.get("READ_PAGE_OCR_LANGS")
    os.environ.pop("READ_PAGE_OCR_LANGS", None)
    ownenv._tools(tools_home, {"ocr_langs": ["eng", "rus"]})
    only_rus = os.environ.get("READ_PAGE_OCR_LANGS")
    os.environ["READ_PAGE_OCR_LANGS"] = "eng+deu"
    ownenv._tools(tools_home, {"ocr_langs": ["eng", "chi_sim"]})
    named_wins = os.environ.get("READ_PAGE_OCR_LANGS")
finally:
    os.environ.pop("READ_PAGE_OCR_LANGS", None)
    if saved_ocr is not None:
        os.environ["READ_PAGE_OCR_LANGS"] = saved_ocr
    for k_, v_ in zip(("PATH", "PLAYWRIGHT_BROWSERS_PATH", "READ_PAGE_ENV", "READ_PAGE_TESSDATA"), saved_path3):
        if v_ is None:
            os.environ.pop(k_, None)
        else:
            os.environ[k_] = v_
attempt("a read in the environment is not given the packs --setup fetched as READ_PAGE_OCR_LANGS (every page would be "
        "read with all of them: each is read with its own); a variable the user set wins",
        lambda: (default_langs is None and only_rus is None and named_wins == "eng+deu", "%s %s %s" % (default_langs, only_rus, named_wins)))

# ---------------------------------------------------------------- no source in plain http (KNOWN-ISSUES 210)
# An http index, registry or download host was used as it was - for the very parts no hash protects (yt-dlp and what
# floats with it, the browser, uv's list of Pythons with their hashes) - while only Node's mirror and the OCR data's,
# pinned by hash anyway, had to be https. One check a source.
h_user = tempfile.mkdtemp(prefix="rp-env-http-")
junk.append(h_user)
h_npmrc = os.path.join(h_user, ".npmrc")
SOURCE_PREFIXES = ("UV_", "PIP_", "NPM_CONFIG_", "NPM_PACKAGE_CONFIG_", "PLAYWRIGHT_")
SOURCE_NAMES = ("NODEJS_ORG_MIRROR", "READ_PAGE_TESSDATA_URL", "READ_PAGE_ALLOW_HTTP")


def as_user(npmrc="", files=None, **variables):
    """(net_env(), source_overrides()) for a user with these variables alone, this .npmrc and these files of their own
    (name: text, in h_user) - none of this machine's settings."""
    saved = dict(os.environ)
    try:
        for k in list(os.environ):
            if k.upper().startswith(SOURCE_PREFIXES) or k.upper() in SOURCE_NAMES:
                del os.environ[k]
        with open(h_npmrc, "w", encoding="utf-8") as fh2:
            fh2.write(npmrc)
        for name, text in (files or {}).items():
            with open(os.path.join(h_user, name), "w", encoding="utf-8") as fh2:
                fh2.write(text)
        os.environ.update(PIP_CONFIG_FILE=os.devnull, npm_config_userconfig=h_npmrc)
        os.environ.update(variables)
        return (envsetup.net_env(user_home=h_user, folder=h_user),
                envsetup.source_overrides(dict(os.environ), h_user, h_user, system=False))
    finally:
        os.environ.clear()
        os.environ.update(saved)
        for name in (files or {}):
            os.unlink(os.path.join(h_user, name))


def got(env, name):
    """A variable of net_env's environment, in any case (Windows keeps them in upper case)."""
    return next((v for k, v in env.items() if k.lower() == name.lower()), None)


def said(lines, start, *words):
    return any(x.startswith(start) and all(w in x for w in words) for x in lines)


e1, l1 = as_user(UV_DEFAULT_INDEX="http://mirror.example/simple")
e2, l2 = as_user(UV_INDEX_URL="http://mirror.example/simple")
e3, l3 = as_user(PIP_INDEX_URL="http://pipmirror.example/simple")
e4, l4 = as_user(files={"pip.ini": "[global]\nindex-url = http://pipconf.example/simple\ntrusted-host = pipconf.example\n"},
                 PIP_CONFIG_FILE=os.path.join(h_user, "pip.ini"))
attempt("an http:// index is not used, whatever names it - UV_DEFAULT_INDEX, UV_INDEX_URL, PIP_INDEX_URL, pip's own "
        "configuration (its trusted-host notwithstanding): pypi.org is, and the log says why",
        lambda: (got(e1, "UV_DEFAULT_INDEX") is None and got(e2, "UV_INDEX_URL") is None and got(e2, "UV_DEFAULT_INDEX") is None
                 and got(e3, "UV_DEFAULT_INDEX") is None and got(e3, "PIP_INDEX_URL") is None
                 and got(e4, "UV_DEFAULT_INDEX") is None
                 and said(l1, "UV_DEFAULT_INDEX=http://mirror.example - not used: a source must be https://", "pypi.org is used")
                 and said(l3, "PIP_INDEX_URL=http://pipmirror.example - not used")
                 and any("pip.ini: index-url=http://pipconf.example - not used" in x for x in l4),
                 str([l1[:1], l3[:1], [x for x in l4 if "index-url" in x]])[:300]))
e5, l5 = as_user(UV_EXTRA_INDEX_URL="https://a.example/simple http://b.example/simple",
                 UV_INDEX="corp=http://c.example/simple ok=https://d.example/simple",
                 UV_FIND_LINKS="http://e.example/wheels,/opt/wheels,https://f.example/wheels",
                 PIP_EXTRA_INDEX_URL="http://g.example/simple")
attempt("a list of sources keeps its https entries and loses its http ones (UV_EXTRA_INDEX_URL, UV_INDEX, UV_FIND_LINKS, "
        "pip's), and the log says which",
        lambda: (got(e5, "UV_EXTRA_INDEX_URL") == "https://a.example/simple" and got(e5, "UV_INDEX") == "ok=https://d.example/simple"
                 and got(e5, "UV_FIND_LINKS") == "/opt/wheels,https://f.example/wheels" and got(e5, "PIP_EXTRA_INDEX_URL") is None
                 and said(l5, "UV_EXTRA_INDEX_URL=https://a.example http://b.example", "not used of it: http://b.example")
                 and said(l5, "UV_FIND_LINKS=http://e.example,/opt/wheels,https://f.example", "not used of it: http://e.example"),
                 str([got(e5, k) for k in ("UV_EXTRA_INDEX_URL", "UV_INDEX", "UV_FIND_LINKS")] + l5)[:300]))
e6, l6 = as_user(UV_PYTHON_INSTALL_MIRROR="http://py.example/releases", UV_PYTHON_DOWNLOADS_JSON_URL="http://py.example/l.json")
attempt("our Python's mirror, and uv's list of Pythons - the hashes uv checks our Python against -, in plain http are not used",
        lambda: (got(e6, "UV_PYTHON_INSTALL_MIRROR") is None and got(e6, "UV_PYTHON_DOWNLOADS_JSON_URL") is None
                 and said(l6, "UV_PYTHON_DOWNLOADS_JSON_URL=http://py.example - not used", "uv's own list is used"), str(l6)[:200]))
e7, l7 = as_user(PLAYWRIGHT_DOWNLOAD_HOST="http://cdn.example", npm_config_playwright_download_host="http://cdn2.example")
e7b, _l7b = as_user(PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST="http://cdn.example", PLAYWRIGHT_DOWNLOAD_HOST="https://cdn.example")
attempt("the browser's download host in plain http is not used - Playwright's variable, its Chromium one, npm's form of "
        "it: Playwright's CDN is",
        lambda: (got(e7, "PLAYWRIGHT_DOWNLOAD_HOST") is None and got(e7, "npm_config_playwright_download_host") is None
                 and got(e7b, "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST") is None and got(e7b, "PLAYWRIGHT_DOWNLOAD_HOST") == "https://cdn.example"
                 and said(l7, "PLAYWRIGHT_DOWNLOAD_HOST=http://cdn.example - not used", "Playwright's CDN is used"), str(l7)[:200]))
e8, _l8 = as_user(npm_config_registry="http://npm.example/")
e9, l9 = as_user(npmrc="registry=http://npmrc.example/\n@acme:registry=http://acme.example/\n@ok:registry=https://ok.example/\n")
e10, _l10 = as_user(npmrc="registry=https://npmrc.example/\n")
attempt("npm's registry in plain http - the variable, the .npmrc's, a scope's - gives way to registry.npmjs.org for the "
        "install; an https one stays the user's",
        lambda: (got(e8, "npm_config_registry") == envsetup.NPM_REGISTRY and got(e9, "npm_config_registry") == envsetup.NPM_REGISTRY
                 and got(e9, "npm_config_@acme:registry") == envsetup.NPM_REGISTRY and got(e9, "npm_config_@ok:registry") is None
                 and got(e10, "npm_config_registry") is None
                 and any(".npmrc: @acme:registry=http://acme.example - not used" in x for x in l9),
                 str([x for x in l9 if "npmrc" in x])[:200]))
e11, l11 = as_user(files={"plain.toml": '[pip]\nindex-url = "http://cfg.example/simple"\n'},
                   UV_CONFIG_FILE=os.path.join(h_user, "plain.toml"))
e12, _l12 = as_user(files={"tls.toml": '[pip]\nindex-url = "https://cfg.example/simple"\n'},
                    UV_CONFIG_FILE=os.path.join(h_user, "tls.toml"))
e12b, l12b = as_user(files={"uv.toml": '[[index]]\nurl = "http://idx.example/simple"\n'}, UV_NO_CONFIG="0")
attempt("a UV_CONFIG_FILE that names a source in plain http is not read (one of https sources is); where UV_NO_CONFIG=0 "
        "lets uv read its own settings files, one that names such a source keeps them all unread",
        lambda: (got(e11, "UV_CONFIG_FILE") is None and got(e12, "UV_CONFIG_FILE") == os.path.join(h_user, "tls.toml")
                 and said(l11, "UV_CONFIG_FILE=", "not read: it names a source in plain http (http://cfg.example)")
                 and got(e12b, "UV_NO_CONFIG") == "1" and any("uv.toml sets [[index]]" in x and "not read" in x for x in l12b),
                 str(l11 + l12b)[:300]))
e13, l13 = as_user(UV_DEFAULT_INDEX="http://mirror.corp.example/simple", READ_PAGE_ALLOW_HTTP="mirror.corp.example",
                   npm_config_registry="http://mirror.corp.example/npm/")
e14, l14 = as_user(UV_DEFAULT_INDEX="http://127.0.0.1:3141/root/pypi/+simple/")
attempt("READ_PAGE_ALLOW_HTTP=<host> lets an intranet mirror through, and the log says each time that it goes in plain "
        "http; a mirror on this machine's loopback goes as it is",
        lambda: (got(e13, "UV_DEFAULT_INDEX") == "http://mirror.corp.example/simple"
                 and got(e13, "npm_config_registry") == "http://mirror.corp.example/npm/"
                 and said(l13, "UV_DEFAULT_INDEX=http://mirror.corp.example - the Python packages come from it",
                          "in plain http, which READ_PAGE_ALLOW_HTTP lets through")
                 and said([x.lower() for x in l13], "npm_config_registry=http://mirror.corp.example - ", "in plain http")
                 and said(l13, "READ_PAGE_ALLOW_HTTP=mirror.corp.example")
                 and got(e14, "UV_DEFAULT_INDEX") == "http://127.0.0.1:3141/root/pypi/+simple/"
                 and said(l14, "UV_DEFAULT_INDEX=http://127.0.0.1:3141 - ", "on this machine"), str(l13)[:300]))
attempt("... and so it does for Node's mirror and the OCR data's (each held to its pinned hash either way)",
        lambda: (envsetup.tessdata_url("deu", {"READ_PAGE_TESSDATA_URL": "http://m.corp.example/fast",
                                               "READ_PAGE_ALLOW_HTTP": "m.corp.example"}) == "http://m.corp.example/fast/deu.traineddata"
                 and envsetup.tessdata_url("deu", {"READ_PAGE_TESSDATA_URL": "http://m.corp.example/fast"}) == envsetup.TESSDATA_URL % "deu"
                 and envsetup.usable_source("http://nodes.corp.example/dist", {"READ_PAGE_ALLOW_HTTP": "nodes.corp.example"})
                 and not envsetup.usable_source("http://nodes.corp.example/dist", {}), ""))
yt_envs = []
real_update2, real_pyok2 = envsetup.ytdlp_update, envsetup._python_ok
envsetup.ytdlp_update = lambda d, uv, py, env, sh, now=None, lock=None: (yt_envs.append(dict(env)) or (True, "2026.11.2"))
envsetup._python_ok = lambda py: True
saved_idx = os.environ.get("UV_DEFAULT_INDEX")
os.environ["UV_DEFAULT_INDEX"] = "http://mirror.example/simple"
try:
    envsetup._ytdlp_worker(wd)
finally:
    envsetup.ytdlp_update, envsetup._python_ok = real_update2, real_pyok2
    if saved_idx is None:
        os.environ.pop("UV_DEFAULT_INDEX", None)
    else:
        os.environ["UV_DEFAULT_INDEX"] = saved_idx
attempt("the background yt-dlp update - every three days, by itself - takes no http index either",
        lambda: (len(yt_envs) == 1 and got(yt_envs[0], "UV_DEFAULT_INDEX") is None, str(len(yt_envs))))
d_pip, w_pip = work_in("rp-env-pipiso-")
pip_cmds = []
w_pip.sh = lambda cmd, timeout=900, env=None, cwd=None: (pip_cmds.append(list(cmd)) or (1, "no pip here"))
real_fj3 = envsetup.fetch_json
envsetup.fetch_json = lambda url, timeout=30: (_ for _ in ()).throw(OSError("no answer"))
try:
    try:
        w_pip._uv_wheel(d_pip)
    except ValueError:
        pass
finally:
    envsetup.fetch_json = real_fj3
attempt("pip, where pypi.org's JSON gives no uv, reads none of its own settings (--isolated) and takes the index uv uses",
        lambda: (len(pip_cmds) == 1 and "--isolated" in pip_cmds[0] and pip_cmds[0][pip_cmds[0].index("--index-url") + 1]
                 in ("https://pypi.org/simple", w_pip.env.get("UV_DEFAULT_INDEX")), str(pip_cmds)[:200]))
d_net, w_net = work_in("rp-env-nethint-")
real_fj4 = envsetup.fetch_json
envsetup.fetch_json = lambda url, timeout=30: (_ for _ in ()).throw(urllib.error.URLError(ConnectionRefusedError(10061, "no")))
saved_idx = os.environ.get("UV_DEFAULT_INDEX")
os.environ["UV_DEFAULT_INDEX"] = "http://mirror.corp.example/simple"
try:
    w_net.env.pop("UV_DEFAULT_INDEX", None)                   # as net_env leaves it
    ok_net, note_net = w_net.network()
finally:
    envsetup.fetch_json = real_fj4
    if saved_idx is None:
        os.environ.pop("UV_DEFAULT_INDEX", None)
    else:
        os.environ["UV_DEFAULT_INDEX"] = saved_idx
attempt("a machine that reaches PyPI only through its mirror in plain http is told how to let it through",
        lambda: (not ok_net and "READ_PAGE_ALLOW_HTTP=mirror.corp.example" in note_net, note_net))

# ---------------------------------------------------------------- the lock's hashes decide what is installed (KNOWN-ISSUES 211)
attempt("the whole set installs with --require-hashes (no package beside the lock's), the fallback by each top package's "
        "pin under the same rule, yt-dlp with --verify-hashes - which no settings file turns off",
        lambda: ("--require-hashes" in envsetup.lock_command("UV", "PY")
                 and envsetup.lock_command("UV", "PY")[envsetup.lock_command("UV", "PY").index("-r") + 1] == envsetup.LOCK_FILE
                 and envsetup.top_command("UV", "PY", "curl_cffi", "0.17.0")[5] == "curl_cffi==0.17.0"
                 and "--require-hashes" in envsetup.top_command("UV", "PY", "curl_cffi", "0.17.0")
                 and "--verify-hashes" in envsetup.ytdlp_command("UV", "PY", floor="2026.10.26", lock="L"), ""))
d_eng, w_eng = work_in("rp-env-engines-")
w_eng.uv_exe, w_eng.base_python = "UV", sys.executable
eng_cmds = []


def eng_sh(cmd, timeout=900, env=None, cwd=None):
    eng_cmds.append([str(c) for c in cmd])
    if cmd[0] == sys.executable:
        return 0, "3.13.18"                                   # _py_version
    if cmd[1:3] == ["pip", "install"] and "-r" in cmd:
        return 1, "error: no wheel for this machine"           # the whole set fails: one at a time
    return 0, "ok"


w_eng.sh = eng_sh
real_pyok3 = envsetup._python_ok
envsetup._python_ok = lambda py: True
try:
    w_eng.engines()
finally:
    envsetup._python_ok = real_pyok3
tops_eng = [c for c in eng_cmds if c[1:3] == ["pip", "install"] and "-r" not in c]
attempt("... and the engines step runs exactly those: the lock with --require-hashes, then each top package by its pin",
        lambda: (any("--require-hashes" in c and "-r" in c for c in eng_cmds) and len(tops_eng) == len(envsetup.TOP)
                 and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][^ ]*", c[5]) and "--require-hashes" in c for c in tops_eng),
                 str(tops_eng[:2])[:200]))


def uv_here():
    """A uv for the checks that run one: --setup's, else one on PATH (CI's offline jobs have none)."""
    mine = os.path.join(ownenv.home(), "uv", "uv-" + envsetup.UV_VERSION, "uv.exe" if os.name == "nt" else "uv")
    return mine if os.path.isfile(mine) else shutil.which("uv")


def probe_wheel(folder, name, requires=()):
    """A wheel of a package of nothing (name-1.0, py3-none-any), and the METADATA it may be served with."""
    dist = name.replace("-", "_")
    info_ = "%s-1.0.dist-info" % dist
    meta = "Metadata-Version: 2.1\nName: %s\nVersion: 1.0\n%s" % (name, "".join("Requires-Dist: %s\n" % r for r in requires))
    path = os.path.join(folder, "%s-1.0-py3-none-any.whl" % dist)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("%s/__init__.py" % dist, "")
        z.writestr(info_ + "/METADATA", "Metadata-Version: 2.1\nName: %s\nVersion: 1.0\n" % name)
        z.writestr(info_ + "/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(info_ + "/RECORD", "%s/__init__.py,,\n%s/METADATA,,\n%s/WHEEL,,\n%s/RECORD,,\n" % (dist, info_, info_, info_))
    with open(path, "rb") as fh2:
        return os.path.basename(path), fh2.read(), meta.encode("utf-8")


uvx = uv_here()
if uvx:
    # an index that serves the lock's own wheel (its hash matches) with a metadata file (PEP 658) naming one more
    # package: the lock's install took that one too, with no hash at all
    pidx = tempfile.mkdtemp(prefix="rp-env-index-")
    junk.append(pidx)
    a_name, a_bytes, a_meta = probe_wheel(pidx, "rp-probe-a", requires=("rp-probe-b",))
    b_name, b_bytes, _b_meta = probe_wheel(pidx, "rp-probe-b")
    sha_a, sha_m = hashlib.sha256(a_bytes).hexdigest(), hashlib.sha256(a_meta).hexdigest()

    class Index(http.server.BaseHTTPRequestHandler):
        pages = {"/simple/rp-probe-a/": ('<a href="/files/%s#sha256=%s" data-dist-info-metadata="sha256=%s" '
                                         'data-core-metadata="sha256=%s">%s</a>' % (a_name, sha_a, sha_m, sha_m, a_name)).encode(),
                 "/simple/rp-probe-b/": ('<a href="/files/%s#sha256=%s">%s</a>'
                                         % (b_name, hashlib.sha256(b_bytes).hexdigest(), b_name)).encode(),
                 "/files/" + a_name: a_bytes, "/files/" + a_name + ".metadata": a_meta, "/files/" + b_name: b_bytes}

        def do_GET(self, head=False):
            body = self.pages.get(self.path.split("?")[0].split("#")[0])
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "text/html" if self.path.endswith("/") else "application/octet-stream")
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            if not head:
                self.wfile.write(body or b"")

        def do_HEAD(self):                         # uv asks a wheel's size first (to read its metadata by ranges)
            self.do_GET(head=True)

        def log_message(self, *a):
            pass

    isrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Index)
    threading.Thread(target=isrv.serve_forever, daemon=True).start()
    lock_ok, lock_bad = os.path.join(pidx, "lock-ok.txt"), os.path.join(pidx, "lock-bad.txt")
    with open(lock_ok, "w", encoding="utf-8") as fh_:
        fh_.write("rp-probe-a==1.0 \\\n    --hash=sha256:%s\n" % sha_a)
    with open(lock_bad, "w", encoding="utf-8") as fh_:
        fh_.write("rp-probe-a==1.0 \\\n    --hash=sha256:%s\n" % ("0" * 64))
    cfg_off = os.path.join(pidx, "uv.toml")
    with open(cfg_off, "w", encoding="utf-8") as fh_:
        fh_.write("[pip]\nverify-hashes = false\n")
    uv_env = dict((k, v) for k, v in envsetup.net_env().items()
                  if not k.upper().startswith(("UV_INDEX", "UV_EXTRA_INDEX", "UV_FIND_LINKS", "UV_CONFIG_FILE")))
    uv_env.update(UV_DEFAULT_INDEX="http://127.0.0.1:%d/simple" % isrv.server_address[1], UV_NO_CONFIG="1",
                  UV_CACHE_DIR=os.path.join(pidx, "cache"), UV_PYTHON_DOWNLOADS="never")

    def probe_install(cmd, venv, **more):
        """Run cmd into a new venv: (exit code, the probe packages it holds after)."""
        subprocess.run([uvx, "venv", venv, "--python", sys.executable, "-q"], env=uv_env, capture_output=True, timeout=120)
        vpy = os.path.join(venv, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv, "bin", "python")
        p = subprocess.run([vpy if c == "PY" else c for c in cmd], env=dict(uv_env, **more), capture_output=True, timeout=300)
        site = glob.glob(os.path.join(venv, "Lib" if os.name == "nt" else "lib*", *([] if os.name == "nt" else ["python3*"]),
                                      "site-packages", "rp_probe_*"))
        return p.returncode, sorted(set(os.path.basename(s) for s in site                    # (lib64 is a link to lib)
                                        if os.path.isdir(s) and "-" not in os.path.basename(s)))

    try:
        new_cmd = envsetup.lock_command(uvx, "PY", lock_ok)
        old_cmd = [c for c in new_cmd if c != "--require-hashes"]                    # the command before
        rc_old, have_old = probe_install(old_cmd, os.path.join(pidx, "v1"))
        rc_new, have_new = probe_install(new_cmd, os.path.join(pidx, "v2"))
        rc_off_old, have_off_old = probe_install([c for c in envsetup.lock_command(uvx, "PY", lock_bad) if c != "--require-hashes"],
                                                 os.path.join(pidx, "v3"), UV_CONFIG_FILE=cfg_off)
        rc_off, have_off = probe_install(envsetup.lock_command(uvx, "PY", lock_bad), os.path.join(pidx, "v4"),
                                         UV_CONFIG_FILE=cfg_off)
    finally:
        isrv.shutdown()
    attempt("the lock's install refuses a package the lock does not name: an index that adds one by a metadata file got it "
            "installed with no hash (the command before this did; it now ends with nothing installed)",
            lambda: (rc_old == 0 and have_old == ["rp_probe_a", "rp_probe_b"] and rc_new != 0 and have_new == [],
                     "before: %s %s, now: %s %s" % (rc_old, have_old, rc_new, have_new)))
    attempt("... and a UV_CONFIG_FILE with verify-hashes = false lets no file through that the lock's hash refuses",
            lambda: (rc_off_old == 0 and have_off_old and rc_off != 0 and have_off == [],
                     "before: %s %s, now: %s %s" % (rc_off_old, have_off_old, rc_off, have_off)))
else:
    print("SKIP the lock's install against a local index (no uv here: --setup's, or one on PATH)")
e19, l19 = as_user(files={"hashes.toml": "[pip]\nverify-hashes = false\n"}, UV_CONFIG_FILE=os.path.join(h_user, "hashes.toml"),
                   UV_INDEX_STRATEGY="unsafe-best-match", UV_PRERELEASE="allow", UV_RESOLUTION="lowest")
attempt("the UV_CONFIG_FILE's keys are named like a uv.toml's (verify-hashes too, which the command line overrides), and so "
        "are uv's variables that change what is picked",
        lambda: (said(l19, "UV_CONFIG_FILE=", "sets verify-hashes", "no file can switch off")
                 and all(said(l19, k + "=") for k in ("UV_INDEX_STRATEGY", "UV_PRERELEASE", "UV_RESOLUTION")), str(l19)[:300]))

# ---------------------------------------------------------------- a link mode that empties the environment (KNOWN-ISSUES 212)
e15, l15 = as_user(UV_LINK_MODE="symlink")
e16, _l16 = as_user(files={"links.toml": '[pip]\nlink-mode = "symlink"\n'}, UV_CONFIG_FILE=os.path.join(h_user, "links.toml"))
e17, _l17 = as_user(UV_LINK_MODE="copy")
attempt("UV_LINK_MODE=symlink, or a UV_CONFIG_FILE's link-mode = \"symlink\", is not passed on: hard links are (uv's own "
        "default), and the log says why; copy stays",
        lambda: (got(e15, "UV_LINK_MODE") == "hardlink" and got(e16, "UV_LINK_MODE") == "hardlink"
                 and got(e17, "UV_LINK_MODE") == "copy" and said(l15, "UV_LINK_MODE=symlink - not passed on"), str(l15)[:200]))
d_ln = tempfile.mkdtemp(prefix="rp-env-linked-")
junk.append(d_ln)
rel_ln = envsetup.env_id("3.13.18")
env_ln = ownenv.at(d_ln, rel_ln)
site_ln = os.path.join(env_ln, "Lib", "site-packages") if os.name == "nt" else os.path.join(env_ln, "lib", "python3.13",
                                                                                            "site-packages")
os.makedirs(os.path.join(site_ln, "pkg"))
with open(os.path.join(site_ln, "pkg", "real.py"), "w") as fh_:
    fh_.write("")
plain_found = envsetup.linked_env(env_ln)
try:
    os.symlink(os.path.join(d_ln, "cache", "uv", "gone.py"), os.path.join(site_ln, "pkg", "__init__.py"))
    can_link = True
except (OSError, NotImplementedError):
    can_link = False
if can_link:
    w_ln = envsetup.Work(d_ln, "rln", "test")
    w_ln.uv_exe, w_ln.base_python = "UV", sys.executable
    del eng_cmds[:]
    w_ln.sh = eng_sh
    envsetup._python_ok = lambda py: True
    try:
        found_ln = envsetup.linked_env(env_ln)
        w_ln.engines()
    finally:
        envsetup._python_ok = real_pyok3
    attempt("an environment a --setup with symlink left - its files links into uv's cache, which that run cleaned - is "
            "found, and built anew (it read 'not here: all 16' for good)",
            lambda: (plain_found == "" and found_ln.endswith("__init__.py") and any(c[1] == "venv" for c in eng_cmds)
                     and not os.path.lexists(os.path.join(site_ln, "pkg", "__init__.py")), "%r %r" % (plain_found, found_ln)))
else:
    print("SKIP an environment of links (this account cannot make one)")

# ---------------------------------------------------------------- an address shows its scheme, host and port (KNOWN-ISSUES 213)
forms = {"https://user:p@ssw0rd@pypi.example.com/simple/": "https://pypi.example.com",
         "https://user:pa/ss@extra.example/simple": "https://extra.example",
         "http://proxyuser:pr/oxy@proxy.example:8080": "http://proxy.example:8080",
         "https://pypi.fury.io/TOKEN-IN-PATH/acme/": "https://pypi.fury.io",
         "https://npm.fury.io/TOKEN2/": "https://npm.fury.io",
         "https://dl.cloudsmith.io/TOKEN3/acme/repo/python/simple/": "https://dl.cloudsmith.io",
         "https://h.example/wheels/?token=SECRET-Q": "https://h.example",
         "https://h.example/npm/?apikey=KEY-Q": "https://h.example",
         "https://host.example/simple?apikey=abc@def": "https://(not shown)",
         "http://[::1]:3141/root/pypi": "http://[::1]:3141",
         "file:///opt/wheels": "file:///opt/wheels"}
secret_words = ("p@ssw0rd", "ssw0rd", "pa/ss", "pr/oxy", "proxyuser", "TOKEN-IN-PATH", "TOKEN2", "TOKEN3", "SECRET-Q",
                "KEY-Q", "abc@def", "@def")
attempt("an address shows as its scheme, host and port: a password with @ or / in it, a token in its path (Gemfury, "
        "Cloudsmith) or in its query never shows - and what is shown once shows the same again",
        lambda: (all(envsetup.redact(k) == v for k, v in forms.items())
                 and envsetup.redact("a https://u:p@h.example/x b") == "a https://h.example b"
                 and all(envsetup.redact(envsetup.redact(k)) == envsetup.redact(k) for k in forms),
                 str([(k, envsetup.redact(k)) for k, v in forms.items() if envsetup.redact(k) != v])[:240]))
e18, l18 = as_user(npmrc="registry=https://npm.fury.io/TOKEN2/\n@acme:registry=https://h.example/npm/?apikey=KEY-Q\n"
                         "https-proxy=http://proxyuser:pr/oxy@proxy.example:8080\n",
                   files={"pip.ini": "[global]\nindex-url = https://dl.cloudsmith.io/TOKEN3/acme/repo/python/simple/\n"},
                   PIP_CONFIG_FILE=os.path.join(h_user, "pip.ini"), UV_INDEX_URL="https://user:p@ssw0rd@pypi.example.com/simple/",
                   UV_EXTRA_INDEX_URL="https://user:pa/ss@extra.example/simple", UV_FIND_LINKS="https://h.example/wheels/?token=SECRET-Q",
                   UV_INDEX="fury=https://pypi.fury.io/TOKEN-IN-PATH/acme/")
attempt("... from variables, the .npmrc and pip's configuration alike: no line of the log or of the report holds a secret",
        lambda: (len(l18) >= 7 and not any(s in x for s in secret_words for x in l18) and said(l18, "UV_INDEX=fury=https://pypi.fury.io - "),
                 str([x for x in l18 if any(s in x for s in secret_words)] or l18)[:300]))
d_say, w_say = work_in("rp-env-say-")
w_say.say("  4/10 engines   FAILED: https://user:tok1@pypi.example.com/simple/abc/ answered 401")
w_say.lack("engines", "https://user:tok2@pypi.example.com/x answered 401", "")
w_say.step("uv", lambda: (False, "no uv: https://user:tok3@files.example/uv.whl answered 401"))
log_say = open(os.path.join(d_say, "setup.log"), encoding="utf-8").read()
attempt("a line of the log (an installer's last words in a step's note), a problem and a step's note kept for the report "
        "show an address the same way",
        lambda: (not any(t in log_say + json.dumps(w_say.problems) + json.dumps(w_say.parts) for t in ("tok1", "tok2", "tok3"))
                 and "https://pypi.example.com answered" in log_say, log_say[-200:]))

# ---------------------------------------------------------------- every download held to a hash but yt-dlp's and the browser's (KNOWN-ISSUES 214)
pins_t = envsetup.tessdata_pins()
mapped = set(ownenv._OCR_PACK.values()) | {"eng", "chi_sim", "chi_tra", "srp_latn"}
attempt("every OCR pack of tessdata_fast 4.1.0 is pinned by SHA256 - 125, among them each the language map can fetch, "
        "eng's and rus's as before",
        lambda: (len(pins_t) == 125 and mapped <= set(pins_t)
                 and pins_t["eng"][0] == "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
                 and pins_t["rus"][0] == "e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225"
                 and all(n > 0 for _s, n in pins_t.values()), str(sorted(mapped - set(pins_t)))))
try:
    tree_ = envsetup.fetch_json("https://api.github.com/repos/tesseract-ocr/tessdata_fast/git/trees/4.1.0", timeout=20)
except Exception as e:                                         # noqa: BLE001
    tree_ = None
    print("SKIP the OCR pins against GitHub's listing of tessdata_fast 4.1.0 (no answer: %s)" % str(e)[:60])
if tree_:
    listed = dict((x["path"][:-len(".traineddata")], x["size"]) for x in tree_.get("tree") or []
                  if x.get("path", "").endswith(".traineddata"))
    small = min(pins_t, key=lambda k: pins_t[k][1])
    small_dir = tempfile.mkdtemp(prefix="rp-env-pack-")
    junk.append(small_dir)
    try:
        envsetup.fetch(envsetup.TESSDATA_URL % small, os.path.join(small_dir, small + ".traineddata"), pins_t[small][0])
        small_ok = True
    except Exception as e:                                     # noqa: BLE001
        small_ok = "%s: %s" % (small, e)
    attempt("... and they are the release's own: each name and size as GitHub lists the tag, the smallest pack's bytes "
            "as pinned",
            lambda: (listed == dict((k, v[1]) for k, v in pins_t.items()) and small_ok is True,
                     "%s; %s" % (sorted(set(listed) ^ set(pins_t))[:4], small_ok)))
od2 = tempfile.mkdtemp(prefix="rp-env-ocrpin-")
junk.append(od2)
asked_pin = []


def pin_fetch(url, dest, sha=None, timeout=60):
    asked_pin.append((url.rsplit("/", 1)[-1], sha))
    raise RuntimeError("stop")


real_fetch5 = envsetup.fetch
envsetup.fetch = pin_fetch
os.environ["READ_PAGE_OCR_LANGS"] = "eng+jpn+kor_vert"
try:
    envsetup.Work(od2, "rpin", "test").ocr_data()
finally:
    envsetup.fetch = real_fetch5
    os.environ.pop("READ_PAGE_OCR_LANGS", None)
attempt("... and --setup fetches every pack against its pin, not eng and rus alone (any other was kept by its size)",
        lambda: (("jpn.traineddata", pins_t["jpn"][0]) in asked_pin and ("kor_vert.traineddata", pins_t["kor_vert"][0]) in asked_pin
                 and all(s for _n, s in asked_pin), str(asked_pin)[:200]))
d_nw, w_nw = work_in("rp-env-nodewheel-")
nw_cmds = []
w_nw.uv_exe = "UV"
w_nw.sh = lambda cmd, timeout=900, env=None, cwd=None: (nw_cmds.append(list(cmd)) or (1, "stop"))
try:
    w_nw._node_wheel()
except ValueError:
    pass
nw_req = open(os.path.join(d_nw, "cache", "dl", "nodejs-wheel-binaries.txt"), encoding="utf-8").read()
attempt("musl's Node from PyPI is installed with --require-hashes, against the SHA256 pinned for each of its wheels",
        lambda: (len(nw_cmds) == 1 and "--require-hashes" in nw_cmds[0] and "-r" in nw_cmds[0]
                 and nw_req.startswith("nodejs-wheel-binaries==%s " % envsetup.NODE_WHEEL)
                 and all(h in nw_req for h in envsetup.NODE_WHEEL_SHA256.values())
                 and any("musllinux" in k for k in envsetup.NODE_WHEEL_SHA256), str(nw_cmds)[:200]))
# KNOWN-ISSUES 231: on musl the Node step's only way is PyPI's wheel, which uv installs; where uv's own step failed,
# the step said "no Node: 'Work' object has no attribute 'uv_exe'"
d_nu, w_nu = work_in("rp-env-nodenouv-")
nu_cmds = []
w_nu.sh = lambda cmd, timeout=900, env=None, cwd=None: (nu_cmds.append(list(cmd)) or (0, ""))
try:
    w_nu._node_wheel()
    nu_err = ""
except Exception as e:                                         # noqa: BLE001
    nu_err = "%s: %s" % (type(e).__name__, e)
attempt("musl's Node from PyPI where uv did not install: the reason says so (not an AttributeError), and nothing runs",
        lambda: (nu_err.startswith("ValueError") and "uv" in nu_err and "attribute" not in nu_err and not nu_cmds,
                 nu_err[:200]))
# ... and the uv step named pip's failure alone ("No module named pip", musl's Python has no pip) where pypi.org's
# answer was what failed
d_um, w_um = work_in("rp-env-uvmsg-")
w_um.sh = lambda cmd, timeout=900, env=None, cwd=None: (1, "/usr/bin/python3: No module named pip")
um_dl = os.path.join(d_um, "dl")
os.makedirs(um_dl, exist_ok=True)
real_fj6 = envsetup.fetch_json


def fj_timed_out(url, timeout=30):
    raise TimeoutError("The read operation timed out")


envsetup.fetch_json = fj_timed_out
try:
    w_um._uv_wheel(um_dl)
    um_err = ""
except ValueError as e:
    um_err = str(e)
finally:
    envsetup.fetch_json = real_fj6
attempt("uv from neither pypi.org nor pip: the reason names both, pypi.org's first (it was in the log alone)",
        lambda: ("timed out" in um_err and "No module named pip" in um_err
                 and um_err.index("timed out") < um_err.index("No module named pip") and len(um_err) <= 160, um_err[:200]))
try:
    pypi_nw = envsetup.fetch_json("https://pypi.org/pypi/nodejs-wheel-binaries/%s/json" % envsetup.NODE_WHEEL, timeout=20)
except Exception as e:                                         # noqa: BLE001
    pypi_nw = None
    print("SKIP nodejs-wheel-binaries' pins against PyPI (no answer: %s)" % str(e)[:60])
if pypi_nw:
    attempt("... and they are the ones PyPI publishes for every wheel of that version",
            lambda: (dict((f["filename"], f["digests"]["sha256"]) for f in pypi_nw["urls"] if f["packagetype"] == "bdist_wheel")
                     == envsetup.NODE_WHEEL_SHA256, ""))
d_dd, w_dd = work_in("rp-env-npmci-")
w_dd.node_bin = os.path.join(d_dd, "node.exe" if os.name == "nt" else "node")
w_dd._npm_cli = lambda node: "npm-cli.js"
left_out = ["linkedom"]


def ci_sh(cmd, timeout=900, env=None, cwd=None):
    """npm ci as it went where a tarball of an optional package did not match the lock: the rest installed, exit 0."""
    root = cmd[cmd.index("--prefix") + 1]
    lock_ = json.load(open(os.path.join(root, "package-lock.json"), encoding="utf-8"))
    have_ = dict((k, v) for k, v in lock_["packages"].items() if k and k.rsplit("node_modules/", 1)[-1] not in left_out)
    for k, v in have_.items():
        os.makedirs(os.path.join(root, *k.split("/")), exist_ok=True)
        with open(os.path.join(root, *k.split("/") + ["package.json"]), "w", encoding="utf-8") as fh2:
            json.dump({"version": v["version"]}, fh2)
    os.makedirs(os.path.join(root, "node_modules", ".bin"), exist_ok=True)
    open(os.path.join(root, "node_modules", ".bin", "defuddle.cmd" if os.name == "nt" else "defuddle"), "w").close()
    with open(os.path.join(root, "node_modules", ".package-lock.json"), "w", encoding="utf-8") as fh2:
        json.dump({"packages": have_}, fh2)
    return 0, "added %d packages" % len(have_)


w_dd.sh = ci_sh
ok_dd, note_dd = w_dd.defuddle()
left_out[:] = []
w_dd2 = envsetup.Work(d_dd, "rdd2", "test")
w_dd2.node_bin, w_dd2._npm_cli, w_dd2.sh = w_dd.node_bin, w_dd._npm_cli, ci_sh
ok_dd2, note_dd2 = w_dd2.defuddle()
ran_again = []
w_dd2.sh = lambda *a, **k: ran_again.append(1) or (1, "")
ok_dd3, _note_dd3 = w_dd2.defuddle()
attempt("defuddle's tree is the lock's, held to it after `npm ci`: an optional package npm left out (its tarball did not "
        "match) fails the step by name; a whole tree passes, and the next --setup leaves it as it is",
        lambda: (not ok_dd and "linkedom" in note_dd and any(p["part"] == "defuddle" for p in w_dd.problems)
                 and ok_dd2 and "npm ci" in note_dd2 and w_dd2.info.get("npm_bin", "").endswith("node_modules/.bin")
                 and ok_dd3 and not ran_again, "%s | %s" % (note_dd, note_dd2)))
dd_home = tempfile.mkdtemp(prefix="rp-env-ddbin-")
junk.append(dd_home)
dd_dist = os.path.join(dd_home, "npm", "node_modules", "defuddle", "dist")
os.makedirs(os.path.join(dd_dist, "utils"))
for n_ in ("node.js", os.path.join("utils", "linkedom-compat.js"), "cli.js"):
    open(os.path.join(dd_dist, n_), "w").close()
dd_bin = os.path.join(dd_home, "npm", "node_modules", ".bin")
os.makedirs(dd_bin)
with open(os.path.join(dd_bin, "defuddle.cmd"), "w") as fh_:
    fh_.write('@"%~dp0\\..\\defuddle\\dist\\cli.js" %*\r\n')
import ddworker                                          # noqa: E402
attempt("a read finds defuddle's files from npm ci's node_modules/.bin, as it did from npm's global shim",
        lambda: (ddworker.locate(os.path.join(dd_bin, "defuddle.cmd"), "NODE") == (os.path.normpath(dd_dist), "NODE"), ""))

# ---------------------------------------------------------------- OCR packs named once stay named (KNOWN-ISSUES 215)
od3 = tempfile.mkdtemp(prefix="rp-env-named-")
junk.append(od3)
os.makedirs(os.path.join(od3, "tessdata"))
for n_ in ("hin", "ben", "chi_sim", "rus"):
    open(os.path.join(od3, "tessdata", n_ + ".traineddata"), "w").close()
named_runs = {}
real_fetch6, real_lang6, real_os6 = envsetup.fetch, ownenv.system_language, ownenv._os_languages
envsetup.fetch = fake_fetch
ownenv.system_language, ownenv._os_languages = (lambda env=None: "en-US"), (lambda: [])
saved_lang6 = dict((k_, os.environ.pop(k_)) for k_ in ("LANGUAGE", "READ_PAGE_LANG", "READ_PAGE_OCR_LANGS") if k_ in os.environ)
try:
    for label_, prev_, named_ in (("kept", {"ocr_named": ["hin", "ben", "tam"]}, ""),          # tam: not on disk any more
                                  ("older", {"ocr_langs": ["eng", "rus", "chi_sim", "hin"]}, ""),  # before ocr_named
                                  ("now", {"ocr_named": ["hin", "ben"]}, "eng+tam")):
        w_ = envsetup.Work(od3, "rn", "test")
        w_.prev = prev_
        if named_:
            os.environ["READ_PAGE_OCR_LANGS"] = named_
        try:
            named_runs[label_] = (w_.ocr_data(), w_.info.get("ocr_langs"), w_.info.get("ocr_named"))
        finally:
            os.environ.pop("READ_PAGE_OCR_LANGS", None)
    os.environ["READ_PAGE_LANG"] = "zh-TW,en"
    lang_packs = ownenv.ocr_default_packs(os.environ)
finally:
    envsetup.fetch, ownenv.system_language, ownenv._os_languages = real_fetch6, real_lang6, real_os6
    os.environ.pop("READ_PAGE_LANG", None)
    os.environ.update(saved_lang6)
attempt("a pack named once stays named: the next plain --setup keeps it (it was dropped, and reads went back to English), "
        "one the user deleted goes, and a setup.json of before keeps what it had beyond today's own",
        lambda: (named_runs["kept"][1] == DEFAULTS + ["hin", "ben"] and named_runs["kept"][2] == ["hin", "ben"]
                 and "named at an earlier --setup, kept for the next --setup: hin+ben" in named_runs["kept"][0][1]
                 and named_runs["older"][1] == DEFAULTS + ["hin"], str(named_runs)[:300]))
attempt("... and what is named now replaces it (the user's own word)",
        lambda: (named_runs["now"][1] == DEFAULTS + ["tam"] and named_runs["now"][2] == ["eng", "tam"], str(named_runs["now"])))
attempt("READ_PAGE_LANG decides what --setup fetches, as it decides what a read asks for",
        lambda: (lang_packs == ocr_set("chi_tra"), str(lang_packs)))
rp_flag = load_rp("ocrflag")
seen_flag = []
real_setup = ownenv.setup
ownenv.setup = lambda script, ver: seen_flag.append(os.environ.get("READ_PAGE_OCR_LANGS")) or 0
saved_ocr7 = os.environ.pop("READ_PAGE_OCR_LANGS", None)
try:
    rp_flag.main(["--setup", "--ocr-langs", "eng+jpn"])
finally:
    ownenv.setup = real_setup
    os.environ.pop("READ_PAGE_OCR_LANGS", None)
    if saved_ocr7 is not None:
        os.environ["READ_PAGE_OCR_LANGS"] = saved_ocr7
attempt("`--setup --ocr-langs eng+jpn` names the packs in any shell (a POSIX `VAR=x cmd` is no command in PowerShell or "
        "cmd), and the line that names a missing pack says it so",
        lambda: (seen_flag == ["eng+jpn"] and (not ownenv.gives("ocr-langs") or rp_flag.ocr_pack_fix(["jpn"]) ==
                                              "jpn.traineddata: readpage.py --setup --ocr-langs eng+jpn"),
                 "%s %s" % (seen_flag, rp_flag.ocr_pack_fix(["jpn"]))))

# ---------------------------------------------------------------- the CI tools, run by hand (KNOWN-ISSUES 217)
# ci_proxy.py put mitmproxy's root into the machine's store and never took it out (its key in a fixed temp folder);
# ci_acp.py patched Git's curl.exe and the environment's Python in place and left a patched copy beside an installed
# Python; ci_container.sh rewrote /etc/apt/sources.list wherever it ran. Every call below is made with nothing of this
# machine within the tools' reach: their processes, copies and manifest writes are recorded, never done.
sys.path.insert(0, os.path.join(SKILL, "tools"))
import ci_acp                                            # noqa: E402
import ci_proxy                                          # noqa: E402


class Recorded(object):
    """What a tool tried to start or copy, none of it done (a call fails as a missing program would)."""

    def __init__(self, ok=False):
        self.tried, self.ok = [], ok

    def __call__(self, name):
        def call(*a, **k):
            self.tried.append((name, [str(x) for x in (a[0] if a and isinstance(a[0], (list, tuple)) else a)]))
            if self.ok and name == "run":
                return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            raise OSError("not on this machine")
        return call


def tool_call(mod, argv, ci=False, ok=False, env=None):
    """mod.main(argv) off a runner (no GITHUB_ACTIONS, no GITHUB_ENV, no GITHUB_PATH) or on one: (exit code, what it
    tried, what it printed)."""
    rec = Recorded(ok)
    fake_sub = types.SimpleNamespace(run=rec("run"), Popen=rec("Popen"), PIPE=-1, STDOUT=-2, DEVNULL=-3)
    fake_shutil = types.SimpleNamespace(copyfile=rec("copy"), copy2=rec("copy"), copytree=rec("copytree"),
                                        rmtree=shutil.rmtree, which=lambda n: "mitmdump-of-the-test",
                                        ignore_patterns=shutil.ignore_patterns)
    saved_mods = (mod.subprocess, mod.shutil, getattr(mod, "set_manifest", None), os.makedirs)
    saved_env = dict((k_, os.environ.pop(k_)) for k_ in ("GITHUB_ACTIONS", "GITHUB_ENV", "GITHUB_PATH", "RUNNER_TEMP",
                                                         "CI_PROXY_DIR", "CI_ACP_COPIES", "READ_PAGE_HOME") if k_ in os.environ)
    os.environ.update(env or {})
    if ci:
        os.environ["GITHUB_ACTIONS"] = "true"
    mod.subprocess, mod.shutil = fake_sub, fake_shutil
    if saved_mods[2] is not None:
        mod.set_manifest = rec("manifest")
    os.makedirs = rec("makedirs")
    out_ = io.StringIO()
    try:
        with contextlib.redirect_stdout(out_):
            try:
                rc_ = mod.main(argv)
            except Exception as e:                             # noqa: BLE001
                rc_ = "%s: %s" % (type(e).__name__, e)
    finally:
        mod.subprocess, mod.shutil = saved_mods[0], saved_mods[1]
        if saved_mods[2] is not None:
            mod.set_manifest = saved_mods[2]
        os.makedirs = saved_mods[3]
        for k_ in ("GITHUB_ACTIONS", "CI_PROXY_DIR", "CI_ACP_COPIES", "READ_PAGE_HOME"):
            os.environ.pop(k_, None)
        os.environ.update(saved_env)
    return rc_, rec.tried, out_.getvalue()


px_start = tool_call(ci_proxy, ["start"])
px_stop = tool_call(ci_proxy, ["stop"])
ac_python = tool_call(ci_acp, ["python", "zh-CN"])
ac_env = tool_call(ci_acp, ["env-python", "zh-CN"])
ac_env_told = tool_call(ci_acp, ["env-python", "zh-CN", "--on-this-machine"])
ac_profile = tool_call(ci_acp, ["profile", "zh-CN"])
attempt("off a CI runner the CI tools refuse what changes the machine - the proxy's root certificate, copies and patched "
        "programs, a profile folder - unless told plainly, and touch nothing",
        lambda: (px_start[0] == 2 and "REFUSED" in px_start[2] and not px_start[1]
                 and px_stop[0] == 0 and not px_stop[1]
                 and all(r_[0] == 2 and "REFUSED" in r_[2] and not r_[1] for r_ in (ac_python, ac_env, ac_profile))
                 and ac_env_told[0] == 2 and "READ_PAGE_HOME" in ac_env_told[2] and not ac_env_told[1],
                 str([(r_[0], r_[1][:2], r_[2][:60]) for r_ in (px_start, px_stop, ac_python, ac_env, ac_env_told, ac_profile)])[:400]))
pem_dir = tempfile.mkdtemp(prefix="rp-env-proxy-")
junk.append(pem_dir)
pem = os.path.join(pem_dir, "conf", "mitmproxy-ca-cert.pem")
os.makedirs(os.path.dirname(pem))
with open(pem, "w", encoding="ascii") as fh_:
    fh_.write("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n" % base64.b64encode(b"a certificate").decode())
sha_pem = hashlib.sha1(b"a certificate").hexdigest().upper()
with open(os.path.join(pem_dir, "state.json"), "w", encoding="utf-8") as fh_:
    json.dump({"cert": pem, "sha1": sha_pem, "trusted": True, "conf": os.path.dirname(pem)}, fh_)
undo_cmds = ci_proxy.untrust_commands(pem, sha_pem)            # (macOS's asks for the file, which stop deletes)
thumb_pem = ci_proxy.thumbprint(pem)
px_undo = tool_call(ci_proxy, ["stop"], ok=True, env={"CI_PROXY_DIR": pem_dir})
attempt("`ci_proxy.py stop` takes out what `start` put in: the root certificate - by its SHA-1, this run's and no other "
        "- out of the store, the CA and its key deleted",
        lambda: (thumb_pem == sha_pem
                 and ci_proxy.untrust_commands(pem, sha_pem, "nt") == [["certutil", "-delstore", "Root", sha_pem]]
                 and ci_proxy.untrust_commands(pem, sha_pem, "darwin")[0] == ["sudo", "security", "delete-certificate", "-Z",
                                                                             sha_pem, ci_proxy.MAC_KEYCHAIN]
                 and ci_proxy.untrust_commands(pem, sha_pem, "linux")[-1] == ["sudo", "update-ca-certificates", "--fresh"]
                 and px_undo[0] == 0 and [c_ for _n, c_ in px_undo[1]] == undo_cmds
                 and not os.path.exists(os.path.dirname(pem)), str(px_undo)[:300]))
# macOS's runner: `security remove-trusted-cert -d` waits for an administrator's answer no one gives, and `stop` held
# the job for its 90 minutes, every run (the certificate itself, deleted first now, goes without a word)
mac_calls = []


def mac_run(cmd, **kw):
    mac_calls.append((list(cmd), kw.get("timeout")))
    if "remove-trusted-cert" in cmd:
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout") or 0)
    return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


mac_pem = os.path.join(pem_dir, "mac-ca-cert.pem")                 # the one above went with stop's conf folder
with open(mac_pem, "w", encoding="ascii") as fh_:
    fh_.write("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n" % base64.b64encode(b"a certificate").decode())
saved_sub_ = ci_proxy.subprocess
ci_proxy.subprocess = types.SimpleNamespace(run=mac_run, PIPE=-1, STDOUT=-2, DEVNULL=-3,
                                            TimeoutExpired=subprocess.TimeoutExpired)
try:
    with contextlib.redirect_stdout(io.StringIO()):
        mac_undo = getattr(ci_proxy, "untrust", None) and ci_proxy.untrust(
            ci_proxy.untrust_commands(mac_pem, sha_pem, "darwin"), True)
finally:
    ci_proxy.subprocess = saved_sub_
attempt("`ci_proxy.py stop` on a runner bounds each removal: macOS's trust setting that waits for a prompt is named and "
        "left, the certificate deleted before it, the step ends",
        lambda: (bool(mac_undo) and mac_undo[0] == [] and len(mac_undo[1]) == 1 and "remove-trusted-cert" in mac_undo[1][0]
                 and [c_[2] for c_, _t in mac_calls] == ["delete-certificate", "remove-trusted-cert"]
                 and all(t_ and t_ <= 120 for _c, t_ in mac_calls), "%r %r" % (mac_undo, mac_calls)))
PY_MANIFEST = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<assembly xmlns="urn:schemas-microsoft-com:asm.v1" '
               'manifestVersion="1.0"><trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>'
               '<requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo>'
               '<compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1"><application>'
               + "".join('<supportedOS Id="{%d}"/>' % i for i in range(5)) +
               '</application></compatibility><application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>'
               '<longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>'
               '</windowsSettings></application><dependency><dependentAssembly><assemblyIdentity type="win32" '
               'name="Microsoft.Windows.Common-Controls" version="6.0.0.0"/></dependentAssembly></dependency></assembly>')
m_cn = ci_acp.with_code_page(PY_MANIFEST, "zh-CN")
m_tw = ci_acp.with_code_page(m_cn, "zh-TW")
attempt("the code page goes into a program's own manifest beside what it had (Python's lost longPathAware, four of "
        "five supportedOS and Common Controls), once, and a second locale replaces the first",
        lambda: (m_cn.count("supportedOS") == 5 and "longPathAware" in m_cn and "Common-Controls" in m_cn
                 and "requestedExecutionLevel" in m_cn and m_cn.count("<activeCodePage") == 1 and ">zh-CN</activeCodePage>" in m_cn
                 and m_tw.count("<activeCodePage") == 1 and ">zh-TW</activeCodePage>" in m_tw
                 and "<activeCodePage" in ci_acp.with_code_page("", "ja-JP"), m_cn[-260:]))
sh_ = shutil.which("sh")
if sh_ and not os.path.exists("/.dockerenv") and not os.path.exists("/run/.containerenv") and not os.environ.get("container"):
    no_path = tempfile.mkdtemp(prefix="rp-env-nopath-")       # nothing it could run is on PATH
    junk.append(no_path)
    p_ct = subprocess.run([sh_, os.path.join(SKILL, "tools", "ci_container.sh"), "none:0", "0"], capture_output=True,
                          timeout=60, env=dict(PATH=no_path, **({"SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
                                                                 if os.name == "nt" else {})))
    attempt("ci_container.sh refuses to run outside a container (it rewrites the package sources and installs as root)",
            lambda: (p_ct.returncode == 2 and b"REFUSED" in p_ct.stderr, (p_ct.stdout + p_ct.stderr)[-200:]))
else:
    print("SKIP ci_container.sh's refusal (no sh here, or this is a container)")

import gc                                                # noqa: E402
for w_ in [o_ for o_ in gc.get_objects() if isinstance(o_, envsetup.Work)]:
    w_.detail.close()                                    # (Windows deletes no folder with a file open in it)
for d in junk:
    shutil.rmtree(d, ignore_errors=True)
print("\n%d ok, %d failed" % (ok, failed))
sys.exit(0 if failed == 0 else 1)
