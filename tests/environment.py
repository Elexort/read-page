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
    with open(tool, "w") as fh:
        fh.write("@echo 2026.10.26\r\n")
else:
    tool = os.path.join(bindir, "yt-dlp")
    with open(tool, "w") as fh:
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

# ---------------------------------------------------------------- found and used
c = caps(base)
env = c.get("env") or {}
check("a run goes on under the environment's Python", env.get("used") is True
      and os.path.normcase(os.path.dirname(env.get("python") or "")) == os.path.normcase(bindir),
      "%s %s" % (env.get("python"), c.get("error", "")))
check("its programs come first on PATH", os.path.normcase(os.path.dirname((c.get("cli") or {}).get("yt-dlp") or ""))
      == os.path.normcase(bindir), str((c.get("cli") or {}).get("yt-dlp")))
check("no compiled module lands beside the skill's scripts", not os.path.isdir(os.path.join(SCRIPTS, "__pycache__")),
      "")
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
dead = dict(base, READ_PAGE_HOME=off, READ_PAGE_SETUP_WAIT="90", HTTPS_PROXY="http://127.0.0.1:9",
            HTTP_PROXY="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9",
            NO_PROXY="", no_proxy="")
for k in ("UV_DEFAULT_INDEX", "UV_INDEX_URL", "PIP_INDEX_URL"):
    dead.pop(k, None)
t0 = time.time()
rc, out, err = run(["--setup"], dead, timeout=180)
check("offline: --setup says it needs the internet and installs nothing",
      rc == 1 and "needs the internet" in out and not os.path.exists(os.path.join(off, "setup.json"))
      and not os.path.isdir(os.path.join(off, "envs")),
      "rc=%s %.0f s %s" % (rc, time.time() - t0, [ln for ln in out.splitlines() if "network" in ln][:1]))
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
# newest of the day of each install, so the day is fixed too
dcmd = envsetup.defuddle_command("node", "npm-cli.js", "PREFIX")
check("defuddle's own packages are pinned too: npm resolves them as of one fixed day",
      "defuddle@" + envsetup.DEFUDDLE_VERSION in dcmd and "--before=" + envsetup.DEFUDDLE_BEFORE in dcmd
      and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", envsetup.DEFUDDLE_BEFORE)
      and dcmd[:3] == ["node", "npm-cli.js", "install"] and "--ignore-scripts" in dcmd, " ".join(dcmd))
try:                                   # the pinned version must exist by the instant its tree is resolved as of
    published = envsetup.fetch_json("https://registry.npmjs.org/defuddle", timeout=20)["time"][envsetup.DEFUDDLE_VERSION]
except Exception as e:                                         # noqa: BLE001
    published = None
    print("SKIP defuddle %s's publish time (the npm registry does not answer: %s)" % (envsetup.DEFUDDLE_VERSION, str(e)[:60]))
if published:
    check("defuddle %s was published before --before's instant (npm would not find it otherwise)" % envsetup.DEFUDDLE_VERSION,
          published.replace(".000Z", "Z") <= envsetup.DEFUDDLE_BEFORE or published < envsetup.DEFUDDLE_BEFORE,
          "%s, before %s" % (published, envsetup.DEFUDDLE_BEFORE))
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
cyr = tempfile.mkdtemp(prefix="rp-Иван-")
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
check("an ASCII path stays as it is (and so does any path off Windows)",
      hasattr(ownenv, "ascii_path") and ownenv.ascii_path(home) == home
      and (os.name == "nt" or ownenv.ascii_path(cyr_td) == cyr_td), "")


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
check("tesserocr starts on tessdata under a path outside ASCII (the short path, where Windows needs it)",
      bool(got) and got[2] == ["eng"] and (os.name != "nt" or got[1].isascii()), str(got and got[1:]))
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
ownenv.ascii_path = lambda p: ""                # a volume that makes no short names
try:
    caps_nos = with_tesserocr(fake_tesserocr(), cyr_td, lambda: rp1.caps(fresh=True))
finally:
    ownenv.ascii_path = real_ascii
rows = {r[0]: r for r in rp1.setup_rows(dict(caps_nos, keys={}))}
check("... and with no short name the fix is the one that works: READ_PAGE_HOME on an ASCII path",
      caps_nos["libs"].get("tesserocr") is False and "outside ASCII" in (caps_nos.get("ocr_error") or "")
      and rows["tesseract"][2] == ownenv.NONASCII_FIX and "READ_PAGE_HOME" in ownenv.NONASCII_FIX,
      str(rows["tesseract"][2:3]))
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
if real_py and os.path.isfile(real_py) and os.path.isfile(real_eng):
    shutil.copy2(real_eng, os.path.join(cyr_td, "eng.traineddata"))
    probe = ("import os, sys, tempfile\n"
             "sys.path.insert(0, %r)\n"
             "import envsetup, readpage\n"
             "td = os.environ['READ_PAGE_TESSDATA']\n"
             "res = envsetup._check_ocr(os.path.dirname(td), {'tessdata': 'tessdata'})\n"
             "from PIL import Image, ImageDraw, ImageFont\n"
             "img = Image.new('L', (520, 90), 255)\n"
             "ImageDraw.Draw(img).text((20, 20), 'Setup check 2026', fill=0, font=ImageFont.load_default(size=40))\n"
             "png = os.path.join(tempfile.mkdtemp(), 'x.png')\n"
             "img.save(png)\n"
             "text, info = readpage.ocr_pages([png])\n"
             "print(repr(res.get('ok')), repr(res.get('why')), '2026' in text, info.get('engine'))\n") % SCRIPTS
    p = subprocess.run([real_py, "-E", "-B", "-X", "utf8", "-c", probe], capture_output=True, timeout=120,
                       env=dict(os.environ, READ_PAGE_TESSDATA=cyr_td, READ_PAGE_HOME=cyr,
                                READ_PAGE_ENV_CHILD="1", READ_PAGE_CACHE=os.path.join(cyr, "cache2")))
    said = p.stdout.decode("utf-8", "replace").strip()
    check("the real tesserocr, the eng pack under a Cyrillic folder: the check passes and a picture is read",
          p.returncode == 0 and said.startswith("True ") and said.endswith("True tesserocr"),
          (said or p.stderr.decode("utf-8", "replace"))[-200:])
    # a pack that lists fine and does not start (cut short) is found by starting it, here and in the check
    with open(real_eng, "rb") as fh_:
        cut_pack = fh_.read()[:5000]
    with open(os.path.join(cyr_td, "xyz.traineddata"), "wb") as fh_:
        fh_.write(cut_pack)
    w3 = envsetup.Work(cyr, "r3", "test")
    w3.env_py = real_py
    bad3 = w3._packs_start(cyr_td, ["eng", "xyz"])
    p3 = subprocess.run([real_py, "-E", "-B", "-X", "utf8", "-c",
                         "import sys; sys.path.insert(0, %r); import envsetup; r = envsetup._check_ocr(%r, "
                         "{'tessdata': 'tessdata'}); print(r['ok'], r['why'])" % (SCRIPTS, cyr)],
                        capture_output=True, timeout=120)
    said3 = p3.stdout.decode("utf-8", "replace").strip()
    check("a pack tesseract does not start with is found by starting it (a pack cut short), when fetched and in the check",
          list(bad3) == ["xyz"] and said3.startswith("False ") and "xyz" in said3, "%s | %s" % (bad3, said3[:120]))
    os.unlink(os.path.join(cyr_td, "xyz.traineddata"))
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
time.sleep(4)
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
os.environ["READ_PAGE_OCR_LANGS"] = "eng+chi_sim + deu_latf+Bad Name+srp_latn"
try:
    w = envsetup.Work(od, "r2", "test")
    got_ok, got_note = w.ocr_data()
finally:
    envsetup.fetch = real_fetch
    os.environ.pop("READ_PAGE_OCR_LANGS", None)
check("a language named with an underscore (chi_sim, deu_latf, srp_latn) is fetched like any other",
      {"chi_sim.traineddata", "deu_latf.traineddata", "srp_latn.traineddata"} <= set(asked), str(asked))
check("... and a name that is no pack's is said, not dropped in silence",
      "Bad Name" in got_note, got_note)

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
    try:
        os.symlink("x", os.path.join(td8, "can-link"))
        can_link = True
    except OSError:
        can_link = False                                 # Windows without the right to make links (Node's tar is POSIX's)
    if can_link:
        envsetup.unpack(good_tar, os.path.join(td8, "ok"))
        check("... and Node's own layout (files, folders, links inside) still unpacks there",
              os.path.isfile(os.path.join(td8, "ok", "node-v1", "lib", "node_modules", "npm", "bin", "npm-cli.js"))
              and os.path.islink(os.path.join(td8, "ok", "node-v1", "bin", "npm")), "")
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
check("the browser's missing libraries are named as the machine's own `sudo apt-get install`",
      fixl == "sudo apt-get install libasound2t64 libatk-bridge2.0-0t64 libnss3", fixl)
check("... from names only (what is not a package name is not put in a command), and nothing when none is missing",
      envsetup.browser_libs_fix("Missing system dependencies (1):\n  libx; rm -rf ~\n") == ""
      and envsetup.browser_libs_fix("All system dependencies are installed.\n") == "", "")
src_env = open(os.path.join(SCRIPTS, "envsetup.py"), encoding="utf-8").read()
check("... and no `sudo <environment python> -m playwright` anywhere (a user-writable interpreter run as root)",
      "sudo %s -m playwright" not in src_env, "")

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
    amp = os.path.join(dd, "Tom & Jerry")
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
probe = subprocess.run(ownenv._probe_argv(), capture_output=True, timeout=60)
pyc_dir = os.path.join(SCRIPTS, "__pycache__")
check("the job probe's child leaves no compiled module beside the scripts",
      probe.stdout in (b"0", b"1") and not os.path.isdir(pyc_dir),
      "%r %s" % (probe.stdout, os.listdir(pyc_dir) if os.path.isdir(pyc_dir) else ""))
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
    with open(bad_py, "w") as fh_:
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
rc, out, err = run([bad_note], dict(base, READ_PAGE_HOME=bh))
check("an environment Python that starts and fails: the read goes on in the machine's Python, and says why",
      rc == 0 and "Проверка: текст по-русски" in out and "environment: its Python started and ended" in out
      and "READ_PAGE_SKIP=env" in out, "rc=%s %s" % (rc, [ln for ln in out.splitlines() if "environment" in ln][:1] or (out + err)[-160:]))
c = caps(dict(base, READ_PAGE_HOME=bh))
check("... and --caps says the same, instead of a Python's silence",
      (c.get("env") or {}).get("used") is False and "started and ended" in ((c.get("env") or {}).get("why") or ""), str(c.get("env")))
leftover = [n_ for n_ in os.listdir(tempfile.gettempdir()) if n_.startswith("read-page-start-")]
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

for d in junk:
    shutil.rmtree(d, ignore_errors=True)
print("\n%d ok, %d failed" % (ok, failed))
sys.exit(0 if failed == 0 else 1)
