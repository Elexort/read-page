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
check("an ASCII path stays as it is (and so does any path off Windows)",
      hasattr(ownenv, "ascii_path") and ownenv.ascii_path(ascii_only) == ascii_only
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
    p_ns = subprocess.run([real_py, "-E", "-B", "-X", "utf8", "-c", probe], capture_output=True, timeout=120,
                          env=dict(os.environ, READ_PAGE_TESSDATA=cyr_td, READ_PAGE_HOME=cyr, RP_NO_SHORT="1",
                                   READ_PAGE_ENV_CHILD="1", READ_PAGE_CACHE=os.path.join(cyr, "cache3")))
    said_ns = p_ns.stdout.decode("utf-8", "replace").strip()
    check("... and on a volume that makes no short names (a runner's D:): the same, from the folder's parent",
          p_ns.returncode == 0 and said_ns.startswith("True ") and said_ns.endswith("True tesserocr"),
          (said_ns or p_ns.stderr.decode("utf-8", "replace"))[-200:])
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
wk = envsetup.Work(tempfile.mkdtemp(prefix="rp-env-w-"), "rw", "test")
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
    return named and "mirror.example/simple" in text, "%d lines" % len(lines142)


attempt("every setting that redirects an installer is named, with its value", over)
attempt("... and no address gives away its user name or password, nor a token of an .npmrc",
        lambda: (not any(x in "\n".join(lines142) for x in ("hunter2", "regsecret", "uvsecret", "npmsecret", "pipsecret",
                                                          "TOKEN-NOT-FOR-THE-LOG")) and bool(lines142), ""))
attempt("an http:// mirror for Node is named as not used, an https:// one as used",
        lambda: (any("NODEJS_ORG_MIRROR=http://nodes.example/dist - not used" in x for x in lines142)
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
        lambda: (any(".npmrc: registry=https://npm.example/" in x for x in lines142)
                 and any(".npmrc: strict-ssl=false" in x for x in lines142)
                 and any(x.startswith(os.path.join(user142, ".config", "pip", "pip.conf") if os.name != "nt" else
                                      os.path.join(user142, "pip", "pip.ini")) and "index-url=https://pip.example/simple" in x
                         for x in lines142), [x[:100] for x in lines142 if "npmrc" in x or "pip." in x]))
attempt("nothing set, nothing said",
        lambda: (envsetup.source_overrides({}, user142 + "-none", tempfile.mkdtemp(prefix="rp-env-bare-"),
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
        lambda: ("sources set here" in log142 and "UV_DEFAULT_INDEX=https://corp.example/simple" in log142
                 and "s3cret" not in log142 and any("corp.example" in x for x in w142.info.get("sources") or []), log142[:160]))
rep_home = tempfile.mkdtemp(prefix="rp-env-rep-")
junk.append(rep_home)
with open(os.path.join(rep_home, "setup.json"), "w", encoding="utf-8") as fh_:
    json.dump(dict(info, problems=[], sources=["UV_DEFAULT_INDEX=https://corp.example/simple - the Python packages come "
                                              "from it, not from pypi.org"],
                   disk={"folder": 1100 * 1048576, "cache": 450 * 1048576, "cache_alone": 20 * 1048576}), fh_)
rc, out, err = run([], dict(base, READ_PAGE_HOME=rep_home))
attempt("the setup report names the sources of the last --setup, and the disk it takes with uv's cache",
        lambda: ("UV_DEFAULT_INDEX=https://corp.example/simple" in out and "sources" in out
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
    os.environ.pop("UV_LINK_MODE")
    sys.platform = "linux"
    e_linux = envsetup.net_env()
finally:
    sys.platform = real_platform
    if saved_link is not None:
        os.environ["UV_LINK_MODE"] = saved_link
    else:
        os.environ.pop("UV_LINK_MODE", None)
attempt("on macOS uv links instead of cloning, so the cache costs what it does elsewhere; a link mode the user set stays",
        lambda: (e_mac.get("UV_LINK_MODE") == "hardlink" and e_mac_user.get("UV_LINK_MODE") == "copy"
                 and "UV_LINK_MODE" not in e_linux, str((e_mac.get("UV_LINK_MODE"), e_mac_user.get("UV_LINK_MODE")))))
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
    rp151b.video_text("https://example.com/v", caps151, tempfile.mkdtemp(prefix="rp-env-ytw-"))
    caps151["cli"]["yt-dlp"] = "/usr/bin/yt-dlp"
    rp151b.video_text("https://example.com/v", caps151, tempfile.mkdtemp(prefix="rp-env-ytw-"))
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
finally:
    envsetup.fetch = real_fetch3
    envsetup.NPM_INTEGRITY, envsetup.NPM_VERSION = saved_pins
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
        lambda: (any(x.startswith("READ_PAGE_TESSDATA_URL=https://m.example/fast - the OCR language data comes from it") for x in over3)
                 and any(x.startswith("READ_PAGE_TESSDATA_URL=http://m.example/fast - not used") for x in over3)
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
                 and any("taken as UV_DEFAULT_INDEX" in x and "pip.ini: index-url=https://mirrors.example/pypi/simple" in x for x in over_pip)
                 and not any("pipsecret" in x for x in over_pip)
                 and e_explicit.get("UV_DEFAULT_INDEX") == "https://explicit.example/simple"
                 and "UV_DEFAULT_INDEX" not in e_noidx, str(over_pip)[:240]))
attempt("the language's OCR pack: Chinese by script, the others by language, English and C need none",
        lambda: ([ownenv.ocr_pack_for(x) for x in ("zh_CN", "zh-CN", "zh_Hans_CN", "zh-TW", "zh_Hant_HK", "zh_MO.UTF-8", "ja_JP.UTF-8",
                                                  "ko-KR", "ru_RU", "de_DE@euro", "sr_Latn_RS", "nb_NO", "en_US", "C", "", "xx_YY")]
                 == ["chi_sim", "chi_sim", "chi_sim", "chi_tra", "chi_tra", "chi_tra", "jpn", "kor", "rus", "deu", "srp_latn", "nor",
                     "", "", "", ""], ""))
attempt("the machine's language is read from the environment where the OS has no word (LC_ALL first, C and POSIX skipped)",
        lambda: (ownenv.system_language({"LC_ALL": "zh_CN.GBK", "LANG": "en_US.UTF-8"}) == "zh_CN.GBK"
                 and ownenv.system_language({"LC_ALL": "C", "LANG": "ja_JP.eucJP"}) == "ja_JP.eucJP"
                 and ownenv.system_language({"LANGUAGE": "ko:en"}) == "ko" and ownenv.system_language({"LANG": "POSIX"}) == ""
                 and ownenv.ocr_default_packs({"LANG": "zh_CN.UTF-8"}) == ["eng", "chi_sim"]
                 and ownenv.ocr_default_packs({"LANG": "en_US.UTF-8"}) == ["eng"], ""))
asked3 = []


def fetch_names(url, dest, sha=None, timeout=60):
    asked3.append(url)
    with open(dest, "wb") as fh_:
        fh_.write(b"pack")
    return dest


real_lang3, real_fetch4 = ownenv.system_language, envsetup.fetch
envsetup.fetch = fetch_names
results3 = {}
try:
    for label_, lang_, named_ in (("zh", "zh-CN", ""), ("en", "en-US", ""), ("ru", "ru-RU", ""), ("zh+deu", "zh-TW", "deu")):
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
attempt("--setup fetches English and the pack of the user's own language, not Russian for everyone",
        lambda: (results3["zh"][0] == ["eng.traineddata", "chi_sim.traineddata"] and results3["zh"][1] == ["eng", "chi_sim"]
                 and results3["en"][0] == ["eng.traineddata"] and results3["en"][1] == ["eng"]
                 and results3["ru"][0] == ["eng.traineddata", "rus.traineddata"], str(results3)[:200]))
attempt("... READ_PAGE_OCR_LANGS adds to it, and the step says which language it took and which variable names others",
        lambda: (results3["zh+deu"][1] == ["eng", "chi_tra", "deu"] and "this machine's language (zh-TW)" in results3["zh+deu"][2]
                 and "READ_PAGE_OCR_LANGS names others" in results3["zh+deu"][2], results3["zh+deu"][2]))
attempt("... from the mirror when one is named",
        lambda: (mirror_asked == ["https://m.example/fast/eng.traineddata", "https://m.example/fast/chi_sim.traineddata"], str(mirror_asked)))
tools_home = tempfile.mkdtemp(prefix="rp-env-ocrtools-")
junk.append(tools_home)
saved_ocr = os.environ.pop("READ_PAGE_OCR_LANGS", None)
saved_path3 = os.environ.get("PATH"), os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), os.environ.get("READ_PAGE_ENV"), os.environ.get("READ_PAGE_TESSDATA")
try:
    ownenv._tools(tools_home, {"ocr_langs": ["eng", "rus", "chi_sim", "osd"]})
    default_langs = os.environ.get("READ_PAGE_OCR_LANGS")
    os.environ.pop("READ_PAGE_OCR_LANGS")
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
attempt("a read in the environment reads with the pack --setup fetched for the machine's language beside English; "
        "Russian keeps its own rule (a Cyrillic page) and a variable the user set wins",
        lambda: (default_langs == "eng+chi_sim" and only_rus is None and named_wins == "eng+deu", "%s %s %s" % (default_langs, only_rus, named_wins)))

for d in junk:
    shutil.rmtree(d, ignore_errors=True)
print("\n%d ok, %d failed" % (ok, failed))
sys.exit(0 if failed == 0 else 1)
