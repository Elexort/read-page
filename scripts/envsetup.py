"""readpage.py --setup: the skill's own environment, built or brought up to date and checked
(ownenv.py finds it and puts a run into it).

    python readpage.py --setup

One command, the full set, no questions: running it is the consent. Everything that installs
without admin rights goes into one folder of the user's (ownenv.home()); what cannot is named with
the machine's own command. The work runs detached, so a harness that stops a long command does
not stop it; the command shows it for up to FOLLOW_SECONDS (to the end in a terminal), and a
second --setup follows the one at work. Re-running updates to the skill's pins and checks every
engine; deleting the folder uninstalls it.

Stdlib only, Python 3.8+: this file runs before the environment exists.
"""
import base64
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

if __name__ == "__main__":
    sys.dont_write_bytecode = True     # the worker runs with -E: no .pyc of ownenv beside the scripts
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ownenv                                                                       # noqa: E402
from ownenv import (SIZE_NOTE, STATE_SCHEMA, YTDLP_EVERY_DAYS, _python_ok, at, home, load,  # noqa: E402,F401
                    mac_version, machine, musl, ocr_here)

# ---------------------------------------------------------------- what --setup installs
# Pinned, the same on every machine (no zoo of whatever the OS or the user has). The
# Python packages are the ones the suites were green with; setup-lock.txt pins every package
# beneath them too (tools/setup_lock.py writes it with this uv).
UV_VERSION = "0.13.9"
PYTHON_VERSION = "3.13.18"          # python-build-standalone, through uv
NODE_VERSION = "24.22.3"            # LTS; the official build from nodejs.org, SHA256 checked
NODE_WHEEL = "24.19.0"              # nodejs-wheel-binaries on PyPI, when nodejs.org cannot be reached
# The Node that runs defuddle and yt-dlp's JavaScript is the one Playwright's wheel carries (driver/node: Playwright
# is installed anyway, and 24.21 for the pinned Playwright) - nothing of nodejs.org is downloaded. That Node has no
# npm: npm is its registry tarball (the version Node 24.22.3 ships), held to this integrity - the value the
# registry publishes for it (`dist.integrity`), checked by the tests against the registry. nodejs.org's Node and
# PyPI's nodejs-wheel-binaries stay as the fallback: musl has no Playwright wheel, and a wheel may lack its Node.
NPM_VERSION = "11.19.1"
NPM_INTEGRITY = "sha512-ztsxKxt/kkIaAs+2i0GU6I+DRmUdrNasxTZKJe9TCdSjKxlhah/4r/hl5ygMD6XAg1qZ9c2TNomR4qgOydp10g=="
NODE_FLOOR = (22, 9)                # npm 11 asks `^20.17.0 || >=22.9.0` of its Node
DEFUDDLE_VERSION = "0.19.4"
# defuddle names its own packages by range (linkedom ^0.18.12, turndown ^7.2.0, temml, commander:
# 26 with theirs), and npm takes the newest of the day of the install. The tree is the lock's (NPM_LOCK:
# `npm ci`, every tarball held to its SHA512 there), which tools/setup_lock.py --npm resolves as of this
# instant - the tree the suites ran with; it moves with the version above. A full timestamp, UTC: npm reads
# a bare date as midnight UTC, and that instant binds defuddle's own version too (a DEFUDDLE_VERSION
# published after it is not found). The pinned version must exist by it.
DEFUDDLE_BEFORE = "2026-11-19T00:00:00Z"
# no markitdown: ~200 MB (magika -> onnxruntime, sympy, numpy; pandas) for what the office readers
# and youtube-transcript-api do as well; no pandoc (2026-11-21, after the hardening of our own
# readers): pypandoc_binary was 41 MB of the download and 226 MB on disk for EPUB, ODT and RTF,
# which docreaders.py reads with the standard library, and better - both A/Bs are in
# references/documents.md
TOP = ["curl_cffi", "trafilatura", "readability-lxml", "lxml", "lxml_html_clean", "html2text",
       "pymupdf", "pymupdf4llm", "python-docx", "openpyxl", "python-pptx", "pillow", "psutil",
       "youtube-transcript-api", "playwright", "tesserocr"]
# yt-dlp is the one engine that is not pinned: its work is to follow the sites,
# and a pinned one stops reading YouTube within weeks. --setup takes its newest release that has
# been out YTDLP_AGE_DAYS (a hijacked upload is usually caught sooner), with the challenge solver
# its own "default" extra names; a video read looks for a newer one in the background every
# YTDLP_EVERY_DAYS (ownenv.refresh_ytdlp). Packages it shares with the lock stay at the lock's.
YTDLP = "yt-dlp[default]"
YTDLP_AGE_DAYS = 3
# What floats with it: its tree beyond the lock's 54 packages. Only these are held to the three days;
# the rest of its tree is the lock's (certifi, requests, urllib3, idna, charset-normalizer), and a pin of
# the lock younger than three days must not make uv go looking for a yt-dlp old enough not to need it.
YTDLP_FLOATS = ("yt-dlp", "yt-dlp-ejs", "brotli", "mutagen", "pycryptodomex", "websockets")
# tessdata_fast 4.1.0 (Apache-2.0): as good as tessdata_best on 60 readings of English, Russian
# and mixed text (clean CER 0.19 against 0.48 %, poor scans 39.6 % both), three times faster
# (0.21 against 0.61 s a picture) and a quarter of the size (8 against 31 MB)
TESSDATA_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/%s.traineddata"
# READ_PAGE_TESSDATA_URL: a mirror for it where raw.githubusercontent.com is slow or not reached - a folder that holds
# `<lang>.traineddata` (https://mirror.example/tessdata_fast/), or a template with {lang} in it. Every pack of the
# release - 125, 339 MB - is pinned by SHA256 in TESSDATA_LOCK (tools/setup_lock.py --tessdata): a pack is held to
# its line whoever serves it, and a name that is not one of them is not fetched.
# What the downloads that are not in a lock are checked against: their SHA256, pinned here for every platform
# they come in, so a mirror, a MITM or whoever serves the file cannot serve other bytes under a version -
# before, the hash came from the same host as the file (PyPI's JSON; nodejs.org's SHASUMS256.txt). A file
# that is not in the table is refused. They move with UV_VERSION, NODE_VERSION and NODE_WHEEL, from the same
# places, after the suites ran green with the new ones.
UV_WHEEL_SHA256 = {   # uv 0.13.9's wheels, from PyPI (its JSON and its simple index agree), 2026-11-21
    "uv-0.13.9-py3-none-linux_armv6l.whl":
        "56ec37616c00220032fc7b8c9d0ef51367fd0d70d9cd6ddd841660f949f84fed",
    "uv-0.13.9-py3-none-macosx_10_12_x86_64.whl":
        "c16ed11e013557536b3e60065f1b912f6407bd6518e041b961e23ef9e6b4fbf5",
    "uv-0.13.9-py3-none-macosx_11_0_arm64.whl":
        "66c512266d633bef48384a1f53003f41f2a8e7b36fe6e7fbfd3e0fd52d96fa63",
    "uv-0.13.9-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl":
        "5435c5ce14a56431208ca0996416d310f1598e8c2c8ba707688985a16bb82dbe",
    "uv-0.13.9-py3-none-manylinux_2_17_armv7l.manylinux2014_armv7l.musllinux_1_1_armv7l.whl":
        "7ec1e1dd9b6cb335c301afdf877989df384227313981850755a59561f75e4ab8",
    "uv-0.13.9-py3-none-manylinux_2_17_armv7l.manylinux2014_armv7l.whl":
        "16963d19594e18d746a70c7fce82237bde4f2cac4cfcf0ca2b84796fe9d0c6e9",
    "uv-0.13.9-py3-none-manylinux_2_17_i686.manylinux2014_i686.whl":
        "db5c8df7145c21ffea9c0f74e38823bac3af60cbadf0e26b8633f08627b17bab",
    "uv-0.13.9-py3-none-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl":
        "c5dbdb7c8737cd183a9dce95b39cfd1f3d54ec2a27a1bb58f160293f9ba2c805",
    "uv-0.13.9-py3-none-manylinux_2_17_s390x.manylinux2014_s390x.whl":
        "a6e845f387e4ed55bb59342957a9179e24a631fcc7668bda3426ae1cef8ed4b9",
    "uv-0.13.9-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl":
        "d7f459fe4fd247d830351c75686d3996ace3c6f3f728eb0e85a30b7ada0cef19",
    "uv-0.13.9-py3-none-manylinux_2_28_aarch64.whl":
        "ecb6028d79dc96fbeafffe5c8af62a7099487ebc05a701e76714eebcffd06375",
    "uv-0.13.9-py3-none-manylinux_2_31_riscv64.musllinux_1_1_riscv64.whl":
        "6d5114bba238adddacb32fb11904f2b3ff4e988f8e9ff0d8d3b5e9822cf836b8",
    "uv-0.13.9-py3-none-manylinux_2_31_riscv64.whl":
        "6b0c7b9f47a5d011939d61e324d3fe18a8bc155d8dd53add738709a92f290a7c",
    "uv-0.13.9-py3-none-musllinux_1_1_i686.whl":
        "a2ee66fe8b6608e1482ab1bde5799da04705c1cb40324c7f66054ecf46ae6e40",
    "uv-0.13.9-py3-none-musllinux_1_1_x86_64.whl":
        "2c45530751517d6c3bbc69a19473f6effe47cce047bede01ffd8af7ea7b36b25",
    "uv-0.13.9-py3-none-win32.whl":
        "3eeeb51a267a2144640fcd8f38d4a2f63439b39bc47445fd84727c3fc462c843",
    "uv-0.13.9-py3-none-win_amd64.whl":
        "6a44b2ed8111d2f60d2b92627c5dccda3f7ed7570b18ce115e569cd68c28246b",
    "uv-0.13.9-py3-none-win_arm64.whl":
        "eeb92051c2123b9730c46b04cc843cfa4bc7d7b0aec56df431a2215ef4cb0273",
}
NODE_SHA256 = {   # Node 24.22.3's archives, from nodejs.org's SHASUMS256.txt, 2026-11-21
    "node-v24.22.3-darwin-arm64.tar.gz":
        "ff6e17d4874b76d272212b908cc020d6e815fba5a6c7eaaa06add725840307fd",
    "node-v24.22.3-darwin-x64.tar.gz":
        "977614af0504c81045e7fd85596dbca0e5f951b96681516dadafedcca8c447f7",
    "node-v24.22.3-linux-arm64.tar.gz":
        "261af2af250dfd7e9f25cf151d1b2713a0adf8f10a9ad116c4947f68627affe8",
    "node-v24.22.3-linux-ppc64le.tar.gz":
        "ba4b26ade1f7b3f5ba6756856815de58e353746004e7e46cc838243a6cbf3299",
    "node-v24.22.3-linux-s390x.tar.gz":
        "d8f84397c1478c0ed0c1b29343626ed0f5f1a0985df0c5975c30f0c03836631f",
    "node-v24.22.3-linux-x64.tar.gz":
        "061ec3e3062115705b56b51fa9cc330ab50d34b6969387d4e4b1a50c6809acc2",
    "node-v24.22.3-win-arm64.zip":
        "b3cc74a295b39d4f273271e96f58c06dd2b35757ca12abec64c7d0598b434f14",
    "node-v24.22.3-win-x64.zip":
        "e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f",
}
NODE_WHEEL_SHA256 = {   # nodejs-wheel-binaries 24.19.0's wheels, from PyPI's JSON, 2026-11-22 (musl's only Node)
    "nodejs_wheel_binaries-24.19.0-py2.py3-none-macosx_13_0_arm64.whl":
        "e12cbfd69089504e42fb14194ce734a9dcf3eb38c820ca63dd511d36fb964e9c",
    "nodejs_wheel_binaries-24.19.0-py2.py3-none-macosx_13_0_x86_64.whl":
        "1c890adf4b7e6556ccc1ca66c866bb81884b6c9a581dee4e530dc7f78fb9d514",
    "nodejs_wheel_binaries-24.19.0-py2.py3-none-manylinux_2_28_aarch64.whl":
        "4e029dadfae1295876063c96b236f673487e8c27379fe146c1e2250283520227",
    "nodejs_wheel_binaries-24.19.0-py2.py3-none-manylinux_2_28_x86_64.whl":
        "4196a947bcc883f2003ab101762d729f3e99b5e86b75bd09151563403e2eceb8",
    "nodejs_wheel_binaries-24.19.0-py2.py3-none-musllinux_1_2_aarch64.whl":
        "352e048ab4dd35e7de5f338d1cc4fcbf77a0e93da30bf7336a8217ee246b31d7",
    "nodejs_wheel_binaries-24.19.0-py2.py3-none-musllinux_1_2_x86_64.whl":
        "28d078b2ced9e2069516e652dc4b1380e7a1a7f2d3934eccd1611586d283ba4c",
    "nodejs_wheel_binaries-24.19.0-py2.py3-none-win_amd64.whl":
        "67e3abeb9c3830cae8c8487ae8a2af7cc27dfa75af06145cee5ca7d1857c81bd",
    "nodejs_wheel_binaries-24.19.0-py2.py3-none-win_arm64.whl":
        "d9074c665ea68b04e183d82482c86dc907d3a9bd15eb6cf85542cb785266bb36",
}
# The 54 packages are pinned by content in setup-lock.txt (--generate-hashes), defuddle's 27 in
# defuddle-lock.json (npm's SHA512), the OCR packs in tessdata-lock.txt; our Python by the SHA256 the pinned
# uv carries for each build. Not checked by content: yt-dlp and what floats with it (no hash can name a
# release that is newer than the repository) and Playwright's browser, which Playwright downloads over TLS
# with a Content-Length check and no hash - both from https sources only (refuse_plain_http).
BROWSER = "chromium-headless-shell"
LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup-lock.txt")
NPM_LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "defuddle-lock.json")
TESSDATA_LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata-lock.txt")
ENV_LOCK = "setup-lock.txt"          # inside an environment's folder: the lock it was built from
FOLLOW_SECONDS = 100                # --setup shows the work this long, then leaves it in the background
# Windows refuses a DLL that carries a manifest (every .pyd; curl_cffi's and tesserocr's libraries) by a path over
# WIN_DLL_PATH_MAX characters: measured on Windows 11, long paths on, inside a packaged app and outside it alike - 250
# loads, 251 is "The filename or extension is too long" (WinError 206), whether imported, loaded by ctypes or found
# in a folder of os.add_dll_directory; one without a manifest loads by 400. The environment's deepest DLL is
# ENV_DLL_DEPTH characters inside the home (curl_cffi's libcurl-impersonate, with the pins of 2026-11-23), and
# DLL_DEPTH_MARGIN is room for pins that move it (tests/environment.py walks a real environment and fails when they eat
# it). A longer home is refused before anything is fetched: curl_cffi and OCR would not load from it, and the check
# would say so after minutes of downloads.
WIN_DLL_PATH_MAX = 250
ENV_DLL_DEPTH = 116
DLL_DEPTH_MARGIN = 14
WIN_HOME_MAX = WIN_DLL_PATH_MAX - ENV_DLL_DEPTH - DLL_DEPTH_MARGIN       # 120
NOT_PASSED_ON = ("UV_NO_VERIFY_HASHES",)     # settings of the user's that would switch off the lock's hash check
STALE_CACHE_BYTES = 150 * 1024 * 1024         # uv's cache beyond this in no environment is stale (a fresh install: 14-21 MB)
# what an installer says (uv, npm, Playwright, pip) when it cannot verify who answers
CERT_FAILURE = re.compile(r"(?i)certificate verify failed|invalid peer certificate|unknownissuer|unknown issuer|"
                          r"unable to verify the first certificate|self[- ]signed certificate|"
                          r"unable_to_get_issuer_cert|unable_to_verify_leaf_signature|cert_untrusted")


# ---------------------------------------------------------------- --setup: the command
def setup(script, skill_version):
    """Start the work in the background (or join one already running), show it for up to
    FOLLOW_SECONDS - till the end in a terminal - and print the report when it is done."""
    d = home()
    too_long = home_too_long(d)
    if too_long:
        print("read-page --setup: " + too_long)
        return 1
    try:
        new = not os.path.isdir(d)
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write-check.%d" % os.getpid())
        with open(probe, "w", encoding="utf-8"):
            pass
        os.unlink(probe)
    except OSError as e:
        print("read-page --setup: cannot write to %s: %s" % (d, e))
        return 1
    said = secure_home(d, new)
    if said:
        print("read-page --setup: " + said)
    t0 = time.time()
    run = "%d-%d" % (int(t0 * 1000), os.getpid())
    lock, state = os.path.join(d, "setup.lock"), os.path.join(d, "setup.state")
    # the size first, before anything is fetched
    if _current(d):
        print("read-page --setup: %s - set up already for these pins: it checks every engine and "
              "downloads only what is missing" % d)
    elif load(d).get("env"):
        print("read-page --setup: %s - brings it up to the skill's pins: downloads what changed, at most "
              "the full set (%s)" % (d, SIZE_NOTE))
    else:
        print("read-page --setup: %s - %s" % (d, SIZE_NOTE))
    sys.stdout.flush()
    st0 = _read_json(state)
    if not st0 and _locked(lock):
        st0 = _read_again(state, {})           # made while the run at work replaced it (Windows): read it again
    attached = False
    if _locked(lock) and st0.get("done") is False and _pid_alive(st0.get("pid")):
        # only a run still at work is followed: the lock alone, or a state of a run that ended, is
        # not one (it replayed the last run's log and exited 0 with nothing done)
        target = st0.get("run") or ""
        print("a --setup started earlier is still working; following it")
    else:
        target = run
        err, attached = _launch(d, run, skill_version)
        if err:
            print("could not start the work: %s" % err)
            return 1
        if attached:
            print("this shell ends what a command started when the command ends, so the work is followed "
                  "here to its end (a harness that stops the command sooner stops it; --setup again goes on)")
    sys.stdout.flush()
    wait = os.environ.get("READ_PAGE_SETUP_WAIT")
    try:
        limit = float(wait) if wait else (1e9 if (_tty() or attached) else FOLLOW_SECONDS)
    except ValueError:
        limit = FOLLOW_SECONDS
    seen, last = 0, {}
    while True:
        # a read that finds nothing is no news (on Windows the file cannot be opened for the moment the worker replaces
        # it): what was seen last stands, and only a run never seen at all did not start
        st = last = _read_json(state) or last
        if st.get("run") != target and float(st.get("started") or 0) >= t0 - 1:
            target = st.get("run")             # another --setup's work started first: that one
        mine = st.get("run") == target
        if mine:
            seen = _show_log(d, seen)          # the work's log is its own run's: shown from the top
            if st.get("done"):
                break
            if not _locked(lock):
                time.sleep(0.5)                # the state may be one write behind the lock
                st = last = _read_again(state, st)
                if not st.get("done"):
                    _show_log(d, seen)
                    print("the work stopped after %s of %s steps, before its end (its log: %s); run --setup "
                          "again to go on" % (_done(st), st.get("steps") or "?", os.path.join(d, "setup-detail.log")))
                    return 1
                continue
        elif time.time() - t0 > 20:
            print("the work did not start; its log: %s" % os.path.join(d, "setup-detail.log"))
            return 1
        if time.time() - t0 > limit:
            print("--setup goes on in the background (%s of %s steps done, now: %s). Run `readpage.py --setup` "
                  "again to follow it; reads work meanwhile with what is ready."
                  % (_done(st), st.get("steps") or "?", st.get("name") or "starting"))
            return 0
        time.sleep(0.3)
    _show_log(d, seen)
    info = load(d)
    py = at(d, info.get("python"))
    if py and _python_ok(py):
        print("")
        sys.stdout.flush()
        try:
            p = subprocess.run([py, "-E", "-X", "utf8", os.path.abspath(script)], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=120)
            sys.stdout.write(p.stdout.decode("utf-8", "replace"))
        except (OSError, subprocess.SubprocessError) as e:
            print("the setup report did not come: %s" % e)
    return 0 if st.get("ok") else 1


def home_too_long(d, windows=None):
    """What --setup says, and stops at, where the home's path is too long for the environment's DLLs to load (Windows,
    WIN_HOME_MAX); '' where it is not, and anywhere off Windows. A length is Windows' own (UTF-16 units)."""
    def units(p):
        return len(p.encode("utf-16-le", "surrogatepass")) // 2

    if not (os.name == "nt" if windows is None else windows) or units(d) <= WIN_HOME_MAX:
        return ""
    default = os.path.join(os.path.expanduser("~"), ".read-page")
    other = (" (the default, %s, is %d)" % (default, units(default))
             if (os.environ.get("READ_PAGE_HOME") or "").strip() and units(default) <= WIN_HOME_MAX else "")
    return ("%s is %d characters long: on Windows the environment's DLLs do not load from a folder over %d characters "
            "(Windows refuses a DLL by a path over %d, and the deepest lies %d inside the folder). Nothing was "
            "downloaded: set READ_PAGE_HOME to a shorter folder%s and run --setup again."
            % (d, units(d), WIN_HOME_MAX, WIN_DLL_PATH_MAX, ENV_DLL_DEPTH, other))


def _done(st):
    """How many steps the work had finished, from its state (an older one counted `step` instead)."""
    if isinstance(st.get("finished"), int):
        return st["finished"]
    return max(0, int(st.get("step") or 1) - 1)


def env_id(pyver):
    """The environment's folder for the skill's pins: envs/py<version>-<hash of the lock>."""
    with open(LOCK_FILE, encoding="utf-8") as fh:
        lock = fh.read()
    return "envs/py%s-%s" % (pyver, hashlib.sha1(("%s|%s|%s" % (pyver, lock, "|".join(TOP)))
                                                 .encode("utf-8")).hexdigest()[:10])


def lock_packages(text):
    """How many packages a lock names (a hashed lock has a line of hash for each of a package's files)."""
    return sum(1 for ln in text.splitlines() if re.match(r"[A-Za-z0-9][A-Za-z0-9._\[\],-]*==", ln))


def _current(d):
    """Whether the folder already holds an environment for these pins, every part of it working."""
    info = load(d)
    try:
        return (info.get("env") == env_id(PYTHON_VERSION) and _python_ok(at(d, info.get("python")))
                and all(p.get("ok") for p in (info.get("parts") or {}).values()) and bool(info.get("parts")))
    except OSError:
        return False


def _tty():
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _show_log(d, seen):
    """Print the lines the work added to setup.log since `seen` bytes (a new run starts it anew)."""
    path = os.path.join(d, "setup.log")
    try:
        size = os.path.getsize(path)
    except OSError:
        return seen
    if size < seen:
        seen = 0
    if size == seen:
        return seen
    with open(path, "rb") as fh:
        fh.seek(seen)
        chunk = fh.read(size - seen)
    end = chunk.rfind(b"\n") + 1               # whole lines only
    if end:
        sys.stdout.write(chunk[:end].decode("utf-8", "replace"))
        sys.stdout.flush()
    return seen + end


LAUNCH_ATTACHED = 12                 # --launch's exit code: started, but it ends with the command (see _detached)


def _launch(d, run, skill_version):
    """The worker runs detached, its parent a launcher that is gone at once: a harness that kills
    this command's process tree on a timeout does not take the work with it. (error text, attached):
    attached when a job around the command ends what is in it - the work then ends with the command."""
    me = os.path.abspath(__file__)
    try:
        p = subprocess.run([sys.executable, "-E", "-B", "-X", "utf8", me, "--launch", d, run, skill_version],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e), False
    if p.returncode in (0, LAUNCH_ATTACHED):
        return "", p.returncode == LAUNCH_ATTACHED
    return p.stdout.decode("utf-8", "replace").strip()[-300:], False


def _detached(cmd, cwd, log, attached_ok=True):
    """Start cmd apart from this process. Says which way it went: "free" (out of this process's group
    and job: it goes on when the command that started it ends), "attached" (started, but a job around
    us - a harness that runs each command in one that kills on close and lets nothing leave - ends it
    with the command), or "" (not started: attached_ok is False and it would have been attached)."""
    with open(log, "ab") as out:
        kw = dict(stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=cwd, close_fds=True)
        if os.name == "nt":
            # a console of its own that nobody sees (its installers open no windows), its own group
            # (the user's Ctrl+C is not for it), out of the harness's job when that job allows it
            flags = 0x08000000 | 0x00000200          # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            if not ownenv.breakaway_job_ends_us():
                try:
                    subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)   # | CREATE_BREAKAWAY_FROM_JOB
                except OSError:
                    # a job that lets nothing leave but does not end what is in it either (no kill on
                    # close): the work stays in it, and the command's end does not touch it
                    subprocess.Popen(cmd, creationflags=flags, **kw)
                return "free"
            if not attached_ok:
                return ""
            subprocess.Popen(cmd, creationflags=flags, **kw)
            return "attached"
        subprocess.Popen(cmd, start_new_session=True, **kw)
        return "free"


# ---------------------------------------------------------------- a folder of the user's alone (Windows)
# SIDs of the groups whose write access makes a folder the machine's other users' too: Everyone, Authenticated Users,
# Users, Interactive. A folder under C:\ (C:\read-page, the ASCII home OCR may need) inherits Authenticated Users'
# Modify; a home under the profile has the profile's ACL - its user, SYSTEM, Administrators.
_OTHERS = ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-4")
_WRITE = 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000
_OURS = {"setup.json", "setup.log", "setup-detail.log", "setup.lock", "setup.state", "setup.started", "setup-check.json",
         "setup-new.json", "ytdlp.lock", "ytdlp.stamp", "ytdlp.failed", "envs", "python", "uv", "node", "npm", "browsers",
         "tessdata", "cache"}


def _win_sid_text(psid):
    import ctypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    s = ctypes.c_wchar_p()
    if not advapi.ConvertSidToStringSidW(ctypes.c_void_p(psid), ctypes.byref(s)):
        return ""
    try:
        return s.value or ""
    finally:
        ctypes.windll.kernel32.LocalFree(s)


def user_sid():
    """Windows: this process's user, as a SID (`S-1-5-21-...`); '' where it cannot be read."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):      # TOKEN_QUERY
            return ""
        try:
            size = wintypes.DWORD(0)
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))                     # TokenUser
            buf = ctypes.create_string_buffer(size.value)
            if not advapi.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                return ""
            return _win_sid_text(ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0])
        finally:
            k32.CloseHandle(token)
    except Exception:                                          # noqa: BLE001
        return ""


def others_write(path):
    """Windows: whether the machine's other users may write in this folder - its DACL lets Everyone, Authenticated
    Users, Users or Interactive add or change something (or it has none); False elsewhere, None where it cannot be read."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
        advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                                 ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                                 ctypes.POINTER(ctypes.c_void_p)]
        if advapi.GetNamedSecurityInfoW(path, 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(sd)) != 0:
            return None                                                     # SE_FILE_OBJECT, DACL_SECURITY_INFORMATION
        try:
            if not dacl.value:
                return True                                                 # no DACL at all: everyone may do anything
            count = ctypes.cast(dacl.value + 4, ctypes.POINTER(ctypes.c_ushort))[0]      # ACL.AceCount
            advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
            for i in range(count):
                ace = ctypes.c_void_p()
                if not advapi.GetAce(dacl, i, ctypes.byref(ace)):
                    continue
                if ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte))[0] != 0:      # ACCESS_ALLOWED_ACE_TYPE alone
                    continue
                mask = ctypes.cast(ace.value + 4, ctypes.POINTER(ctypes.c_uint32))[0]
                if mask & _WRITE and _win_sid_text(ace.value + 8) in _OTHERS:
                    return True
            return False
        finally:
            ctypes.windll.kernel32.LocalFree(sd)
    except Exception:                                          # noqa: BLE001
        return None


def secure_home(d, new=False, profile=None):
    """Windows: the folder --setup puts programs in must be this user's alone - the machine's other users could
    otherwise replace python.exe, site-packages or the bytecode a read runs. A home under the profile is (the profile's
    ACL); one elsewhere that others may write in is made this user's, SYSTEM's and the administrators' alone where it
    is the skill's own (new, or nothing in it but what --setup keeps), else named with the command that would. What to
    say ('' for nothing)."""
    if os.name != "nt":
        return ""

    def full(p):
        # the long names: a path through a short 8.3 one (C:\Users\RUNNER~1, as Windows gives TEMP for a long user
        # name, and a READ_PAGE_HOME made from it) is the same folder
        return os.path.normcase(os.path.realpath(os.path.abspath(p)))

    profile = full(profile or os.path.expanduser("~")).rstrip(os.sep) + os.sep
    if full(d).startswith(profile) or others_write(d) is not True:
        return ""
    sid = user_sid()
    cmd = ["icacls", d, "/inheritance:r", "/grant:r", "*%s:(OI)(CI)F" % (sid or "<your SID>"), "/grant:r",
           "*S-1-5-18:(OI)(CI)F", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "/remove:g"] + ["*" + s for s in _OTHERS] + ["/Q"]
    ours = new or set(n for n in os.listdir(d) if not n.startswith(".write-check.")) <= _OURS
    if sid and ours:
        try:
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
            if p.returncode == 0 and others_write(d) is False:
                return ("%s is outside your profile, and the machine's other users could write in it (it took the ACL "
                        "of its parent): it is yours alone now (yours, SYSTEM's and the administrators')" % d)
        except (OSError, subprocess.SubprocessError):
            pass
    return ("warning: the machine's other users can write in %s, and so change the programs --setup puts there; make "
            "it yours alone: %s" % (d, " ".join('"%s"' % c if " " in c else c for c in cmd)))


# ---------------------------------------------------------------- small tools
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_again(path, last, tries=20):
    """setup.state read till a read finds it, 0.1 s apart (on Windows one made while the file is replaced, or while
    something else holds it, finds nothing); where none does, what was seen last stands."""
    for _ in range(tries):
        st = _read_json(path)
        if st:
            return st
        time.sleep(0.1)
    return last


def _write_json(path, data):
    """The file whole or not at all: a temp file, then os.replace. On Windows a reader that has the file open stops the
    replace (WinError 5) for as long as it holds it: it is tried for 2 s, then the error is raised (the temp file gone)."""
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    for i in range(41):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 40:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.05)


def _lock_state(path):
    """"free", "held" (another process holds it now) or "unusable" (the file cannot be opened: a
    read-only folder - nobody can be said to hold it)."""
    try:
        open(path, "a+b").close()
    except OSError:
        return "unusable"
    fh = _try_lock(path)
    if fh is None:
        return "held"
    _unlock(fh)
    return "free"


def _locked(path):
    """Whether another process holds this lock now."""
    return _lock_state(path) == "held"


def _pid_alive(pid):
    """Whether a process of this pid runs now (an unknown pid counts as alive: the lock decides then)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.OpenProcess.restype = ctypes.c_void_p
            h = k32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return k32.GetLastError() == 5                # access denied: it is there
            try:
                code = ctypes.c_ulong(0)
                return bool(k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))) and code.value == 259
            finally:
                k32.CloseHandle(ctypes.c_void_p(h))
        except Exception:                                      # noqa: BLE001
            return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _try_lock(path):
    try:
        fh = open(path, "a+b")
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def _unlock(fh):
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    fh.close()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def net_env(user_home=None, folder=None):
    """The environment for the installers: the machine's proxy (Windows keeps it in the registry,
    which uv, npm and Playwright do not read) named the way they all do; no source in plain http (refuse_plain_http),
    and nothing of the user's that would switch the lock's check off or leave an environment of links into the cache
    --setup cleans. `user_home` and `folder` (where uv runs: the environment's folder) are for the settings files."""
    env = dict(os.environ)
    user_home = user_home or os.path.expanduser("~")
    try:
        import urllib.request
        px = urllib.request.getproxies()
    except Exception:                                          # noqa: BLE001
        px = {}
    for scheme in ("https", "http"):
        k = scheme.upper() + "_PROXY"
        if px.get(scheme) and not (env.get(k) or env.get(k.lower())):
            env[k] = px[scheme]
    if px.get("no") and not (env.get("NO_PROXY") or env.get("no_proxy")):
        env["NO_PROXY"] = px["no"]
    for k in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "UV_PYTHON", "UV_PROJECT_ENVIRONMENT"):
        env.pop(k, None)
    if not env.get("UV_DEFAULT_INDEX") and not env.get("UV_INDEX_URL") and env.get("PIP_INDEX_URL"):
        env["UV_DEFAULT_INDEX"] = env["PIP_INDEX_URL"]           # a company's mirror, named for pip
    if not env.get("UV_DEFAULT_INDEX") and not env.get("UV_INDEX_URL"):
        # pip's own configuration (pip.ini, pip.conf: the user's and the system's) is where a user in mainland China
        # or behind a company keeps the mirror, and uv does not read it: its index-url is taken, and named in the log
        got = pip_config_index(env, user_home)
        if got:
            env["UV_DEFAULT_INDEX"] = got[1]
    # uv reads uv.toml (and a pyproject.toml with [tool.uv]) from the working folder's parents, the user's and the
    # system's configuration folders: measured with uv 0.13.9, a uv.toml in a parent of the folder sent every
    # install to the index it named, so what --setup installs would depend on where the folder is and on files
    # nobody told about it. UV_NO_CONFIG=1 ignores all of them and still honours the environment's variables
    # (UV_DEFAULT_INDEX, UV_EXTRA_INDEX_URL, ...) and an explicit UV_CONFIG_FILE: a company's mirror is named in
    # one of those, and the log says which (source_overrides). Unless the user set it.
    if not env.get("UV_NO_CONFIG"):
        env["UV_NO_CONFIG"] = "1"
    refuse_plain_http(env, user_home, folder or home())
    # uv clones (copy-on-write) rather than links on macOS, and the GitHub runner's free space showed the cache cost
    # what it holds there (1.5 GB for a setup of 1.0): hard links, which uv uses everywhere else, share the file
    if sys.platform == "darwin" and not env.get("UV_LINK_MODE"):
        env["UV_LINK_MODE"] = "hardlink"
    # symbolic links into uv's cache would leave the environment empty the moment --setup cleans the cache (a moved
    # pin's wheels, a prune of what is in no environment - every file of a linked environment looks like that):
    # measured with UV_LINK_MODE=symlink, the check passed and the cleaning after it removed 7 962 files of it. Hard
    # links, uv's own default, keep a file whatever happens to the cache; the log names the setting (source_overrides)
    if symlink_mode(env, user_home, folder or home()):
        env["UV_LINK_MODE"] = "hardlink"
    # the lock's hashes are what the packages are checked against (README): a variable that turns that check off
    # is not passed on, and the log says so; the commands say --require-hashes and --verify-hashes, which no
    # settings file overrides
    for k in NOT_PASSED_ON:
        env.pop(k, None)
    # urllib (the network check) trusts the OS's certificate store; uv trusts its bundled Mozilla roots and
    # Node its own, so behind a proxy that inspects TLS - its root in the OS's store - the check and the
    # first download passed and the next failed on a certificate. uv 0.13.9's own help: UV_SYSTEM_CERTS
    # ("load TLS certificates from the platform's native certificate store"); Node 24's: NODE_USE_SYSTEM_CA
    # (--use-system-ca; Playwright's driver, Node 24.21, reads it too: 121 roots by default, 274 with it).
    # Unless the user set them.
    for k in ("UV_SYSTEM_CERTS", "NODE_USE_SYSTEM_CA"):
        if not env.get(k):
            env[k] = "1"
    return env


# ---------------------------------------------------------------- what redirects the installers
# Whoever can set these already runs code as the user, so none of them is an escalation. But an address left
# from a trial, an `http://` mirror or a TLS check switched off for a debugging session lowers what the install
# is worth without a word, and the log used to say "pypi.org" and "nodejs.org, SHA256 pinned" whatever was set.
_URL = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)(?!\(not shown\))([^\s'\"<>]*)")      # (what redact left: as it is)
_HOST = re.compile(r"(?i)(\[[0-9a-f:.]+\]|[a-z0-9._~%-]+)(:\d{1,5})?")


def _host_part(rest):
    """The host[:port] of what follows an address's `scheme://`, '' where it cannot be told safely. A user and a
    password come before the last `@` of the authority, which ends at the first / ? or # - but a password may hold a
    / or a ? itself (`user:pa/ss@host`): an `@` after that end, before any query, is the authority's too. An `@` in a
    query is never one (`?apikey=ab@cd`): nothing of that address is shown then."""
    end = min([i for i in (rest.find(c) for c in "/?#") if i >= 0] or [len(rest)])
    host, after = rest[:end].rpartition("@")[2], rest[end:]
    if "@" in after:
        query = min([i for i in (after.find(c) for c in "?#") if i >= 0] or [len(after)])
        at = after.rfind("@")
        host = re.split(r"[/?#]", after[at + 1:], 1)[0] if at < query else ""
    return host if _HOST.fullmatch(host) else ""


def redact(text):
    """Every address in a text as its scheme, host and port, and nothing else of it: a user name or a password
    (whatever characters it holds), a token in the path (Gemfury's `pypi.fury.io/<token>/`, Cloudsmith's) or in the
    query (`?apikey=`) never shows. A file:// address is a path of this machine, and shows whole; the rest of the
    text stays."""
    return _URL.sub(lambda m: m.group(0) if m.group(1).lower() == "file://" else
                    m.group(1) + (_host_part(m.group(2)) or "(not shown)"), str(text))


def _truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _falsy(v):
    return str(v or "").strip().lower() in ("0", "false", "no", "off")


# ---------------------------------------------------------------- no source in plain http
ALLOW_HTTP = "READ_PAGE_ALLOW_HTTP"
NPM_REGISTRY = "https://registry.npmjs.org/"
HTTP_WHY = ("a source must be https:// (in plain http anyone on the network path can change what it serves, and "
            "yt-dlp and the browser have no hash to check; %s=<its host> lets an intranet mirror through)" % ALLOW_HTTP)
REFUSED = "not used: " + HTTP_WHY


def _keys(env, name):
    """The variables of env that are `name`, in any case (Windows keeps them in upper case; npm reads its own in any)."""
    low = name.lower()
    return [k for k in list(env) if k.lower() == low]


def _set(env, name, value):
    for k in _keys(env, name):
        env.pop(k)
    env[name] = value


def http_hosts(env):
    """The hosts READ_PAGE_ALLOW_HTTP names (`mirror.corp`, `mirror.corp:8080`; a list, by commas or spaces)."""
    return set(x.strip().lower() for x in re.split(r"[\s,;]+", str(env.get(ALLOW_HTTP) or "")) if x.strip())


def http_source(url, env):
    """How a source's address may be used: "" (https, a file, a path: as it is), "loopback" (plain http that stays on
    this machine), "allowed" (plain http to a host READ_PAGE_ALLOW_HTTP names: used, and said each time) or "refused"
    (plain http to any other host: not used). uv has no rule of its own for plain http (its allow-insecure-host is
    about TLS), and pip's trusted-host is pip's word, not this setup's."""
    u = str(url or "").strip()
    if not re.match(r"(?i)http://", u):
        return ""
    host = _host_part(u[7:]).lower()
    name, _, port = host.rpartition(":") if not host.endswith("]") and host.count(":") == 1 else (host, "", "")
    name = name.strip("[]")
    if name == "localhost" or name.endswith(".localhost"):
        return "loopback"
    try:
        import ipaddress
        if name and ipaddress.ip_address(name).is_loopback:
            return "loopback"
    except ValueError:
        pass
    allowed = http_hosts(env)
    return "allowed" if name and (name in allowed or host in allowed) else "refused"


def usable_source(url, env):
    """An address an installer may fetch from: https, a file, or plain http that is not refused (http_source)."""
    u = str(url or "").strip().lower()
    return u.startswith(("https://", "file://")) or (u.startswith("http://") and http_source(u, env) != "refused")


# variables that name one source, and those that name a list of them (uv's and pip's: their separators)
_ONE_SOURCE = ("UV_DEFAULT_INDEX", "UV_INDEX_URL", "PIP_INDEX_URL", "UV_PYTHON_INSTALL_MIRROR",
               "UV_PYTHON_DOWNLOADS_JSON_URL", "NODEJS_ORG_MIRROR", "READ_PAGE_TESSDATA_URL")
# the browser's host, as Playwright looks for it: the Chromium one before the general one, each also as npm's
_BROWSER_HOSTS = tuple(p + n for n in ("PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", "PLAYWRIGHT_DOWNLOAD_HOST")
                       for p in ("", "npm_config_", "npm_package_config_"))
_SOURCE_LISTS = (("UV_EXTRA_INDEX_URL", " "), ("UV_INDEX", " "), ("UV_FIND_LINKS", ","), ("UV_CONSTRAINT", " "),
                 ("UV_OVERRIDE", " "), ("PIP_EXTRA_INDEX_URL", " "), ("PIP_FIND_LINKS", " "))


def _entries(value, sep):
    return [x for x in (str(value).split(sep) if sep != " " else str(value).split()) if x.strip()]


def _entry_url(entry):
    """The address of one entry of a list: UV_INDEX's `name=https://...` names it after the `=`."""
    name, eq, rest = entry.strip().partition("=")
    return rest if eq and "://" not in name else entry.strip()


def _urls(text):
    return re.findall(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s'\"<>,\]\)]+", text or "")


def refuse_plain_http(env, user_home, folder):
    """No source in plain http to a host off this machine (http_source): a variable that names one is not passed on -
    the default is used (pypi.org, GitHub, nodejs.org, Playwright's CDN) -, a list keeps its other entries, npm is given
    registry.npmjs.org in place of an http registry of its own settings, and a UV_CONFIG_FILE that names one is not
    read (nor are uv's own settings files, where UV_NO_CONFIG=0 lets uv read them). It is what Node's mirror had alone:
    an http index, registry or host was used as it was, for the very parts no hash protects. The log names each
    (source_overrides)."""
    for name in _ONE_SOURCE + _BROWSER_HOSTS:
        for k in _keys(env, name):
            if http_source(env[k], env) == "refused":
                env.pop(k)
    for name, sep in _SOURCE_LISTS:
        for k in _keys(env, name):
            kept = [x for x in _entries(env[k], sep) if http_source(_entry_url(x), env) != "refused"]
            if kept:
                env[k] = sep.join(kept)
            else:
                env.pop(k)
    for key, url, _where in npm_registries(env, user_home):
        if http_source(url, env) == "refused":
            _set(env, "npm_config_" + key, NPM_REGISTRY)
    cfg = env.get("UV_CONFIG_FILE")
    if cfg and any(http_source(u, env) == "refused" for u in _urls(_file_text(cfg))):
        env.pop("UV_CONFIG_FILE")
    if _falsy(env.get("UV_NO_CONFIG")) and any(
            any(http_source(u, env) == "refused" for u in _urls(_file_text(p))) for p, _k in uv_config_files(
                env, user_home, folder)):
        env["UV_NO_CONFIG"] = "1"


def symlink_mode(env, user_home, folder):
    """Where the user's settings make uv link the environment's files symbolically into its cache: the variable, the
    UV_CONFIG_FILE, or a uv.toml uv reads (UV_NO_CONFIG=0); '' where none does."""
    if str(env.get("UV_LINK_MODE") or "").strip().lower() == "symlink":
        return "UV_LINK_MODE"
    files = ([env["UV_CONFIG_FILE"]] if env.get("UV_CONFIG_FILE") else []) + (
        [p for p, _k in uv_config_files(env, user_home, folder)] if _falsy(env.get("UV_NO_CONFIG")) else [])
    for p in files:
        if re.search(r"(?mi)^\s*link-mode\s*=\s*[\"']symlink[\"']", _file_text(p) or ""):
            return p
    return ""


# (variable, what it does here, what is used where it is refused): a setting of the user's that sends an installer
# somewhere else, or changes what it does
_SOURCE_VARS = (
    ("UV_DEFAULT_INDEX", "the Python packages come from it, not from pypi.org", "pypi.org"),
    ("UV_INDEX_URL", "the Python packages come from it, not from pypi.org", "pypi.org"),
    ("UV_INDEX", "uv looks in this index too", ""),
    ("UV_EXTRA_INDEX_URL", "uv looks in it besides the default index", ""),
    ("UV_FIND_LINKS", "uv takes wheels from it", ""),
    ("UV_PYTHON_INSTALL_MIRROR", "our Python comes from it, not from github.com", "github.com"),
    ("UV_PYTHON_DOWNLOADS_JSON_URL", "uv takes its list of Pythons, and their hashes, from it", "uv's own list"),
    ("UV_INSECURE_HOST", "uv does not verify TLS for it", ""),
    ("UV_CONSTRAINT", "uv resolves under these constraints", ""),
    ("UV_OVERRIDE", "uv resolves under these overrides", ""),
    ("UV_EXCLUDE_NEWER", "uv leaves out files newer than it", ""),
    ("UV_INDEX_STRATEGY", "uv looks for a package across its indexes this way", ""),
    ("UV_PRERELEASE", "uv takes pre-releases this way", ""),
    ("UV_RESOLUTION", "uv picks versions this way", ""),
    ("PIP_EXTRA_INDEX_URL", "not read: pip, used only if pypi.org gives no uv, is run with --isolated and the index "
                            "uv uses", ""),
    ("PIP_FIND_LINKS", "not read: pip, used only if pypi.org gives no uv, is run with --isolated and the index uv "
                       "uses", ""),
    ("PLAYWRIGHT_DOWNLOAD_HOST", "the browser comes from it, not from Playwright's CDN", "Playwright's CDN"),
    ("PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", "the browser comes from it, not from Playwright's CDN", "Playwright's CDN"),
    ("NODE_EXTRA_CA_CERTS", "Node and Playwright trust the certificates in this file too", ""),
    ("SSL_CERT_FILE", "Python trusts the certificates in this file", ""),
    ("NODE_OPTIONS", "given to every Node process of the install", ""),
    (ALLOW_HTTP, "plain http is used for a source on these hosts (each such source says so below)", ""),
)
# what a settings file may hold that moves a source or a check; `[[index]]` is uv.toml's table of indexes
_UV_KEYS = ("index-url", "extra-index-url", "find-links", "allow-insecure-host", "python-install-mirror",
            "python-downloads-json-url", "exclude-newer", "no-binary", "no-build", "native-tls", "index-strategy",
            "constraint-dependencies", "override-dependencies", "no-verify-hashes", "verify-hashes",
            "require-hashes", "link-mode", "prerelease", "resolution")
_NPM_KEYS = ("registry", "strict-ssl", "cafile", "ca", "proxy", "https-proxy")
_PIP_KEYS = ("index-url", "extra-index-url", "find-links", "trusted-host", "cert")


def _file_text(path):
    """The first 64 KB of a settings file, or None where there is none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(65536)
    except OSError:
        return None


def _pairs(text, wanted):
    """The (key, value) pairs of an ini file or an .npmrc (`key = value`) for the keys it is asked for;
    a scope's `@x:registry` counts as `registry`. Credentials (`_authToken`, `_password`) are not asked for."""
    got = []
    for ln in (text or "").splitlines():
        if ln.lstrip().startswith(("#", ";")):
            continue
        m = re.match(r"\s*([A-Za-z0-9_@:./-]+)\s*[=:]\s*(.*?)\s*$", ln)
        if m:
            key = m.group(1).lower()
            base = "registry" if key.endswith(":registry") else key
            if base in wanted:
                got.append((m.group(1), m.group(2).strip("'\"")))
    return got


def npm_configs(env, user_home):
    """npm's settings files for an install: the user's (npm_config_userconfig, else ~/.npmrc), then the global one
    where npm_config_globalconfig names it (else it is under npm's prefix: the folder's own)."""
    files = [env[k] for k in _keys(env, "npm_config_userconfig") if env[k]][:1] or [os.path.join(user_home, ".npmrc")]
    return files + [env[k] for k in _keys(env, "npm_config_globalconfig") if env[k]][:1]


def npm_registries(env, user_home):
    """npm's registries as npm takes them: [(key, address, where)] - `registry` and each scope's (`@acme:registry`;
    defuddle's packages have two scopes, @mixmark-io and @xmldom) - from the environment (npm_config_*, in any case)
    before the settings files (npm_configs); `${VAR}` in a file is the variable's value, as npm reads it."""
    got, seen = [], set()
    for k in sorted(env):
        key = k.lower()[11:]
        if k.lower().startswith("npm_config_") and (key == "registry" or key.endswith(":registry")) and env[k]:
            if key not in seen:
                seen.add(key)
                got.append((key, env[k], k))
    for path in npm_configs(env, user_home):
        for key, value in _pairs(_file_text(path), ("registry",)):
            if key.lower() not in seen:
                seen.add(key.lower())
                got.append((key.lower(), re.sub(r"\$\{([^}?]+)\??\}", lambda m: env.get(m.group(1), ""), value), path))
    return got


def uv_config_keys(text):
    """What of _UV_KEYS a uv settings file sets (`[[index]]`: its table of indexes)."""
    keys = [k for k in _UV_KEYS if re.search(r"(?m)^\s*(\[tool\.uv\.)?%s\s*=" % re.escape(k), text or "")]
    if re.search(r"(?m)^\s*\[\[(tool\.uv\.)?index\]\]", text or ""):
        keys.append("[[index]]")
    return keys


def uv_config_files(env, user_home, folder, system=True):
    """The configuration files uv would read for an install run in `folder` that set a source or a check:
    [(path, [keys])] - a uv.toml, or a pyproject.toml with a [tool.uv] table, in the folder or any parent; the
    user's (`$XDG_CONFIG_HOME` or `~/.config`, `%APPDATA%`) and the system's (`/etc/uv`, `%PROGRAMDATA%`)."""
    paths = []
    here = os.path.abspath(folder)
    while True:
        paths += [os.path.join(here, "uv.toml"), os.path.join(here, "pyproject.toml")]
        up = os.path.dirname(here)
        if up == here:
            break
        here = up
    if os.name == "nt":
        for var in ("APPDATA",) + (("PROGRAMDATA",) if system else ()):
            if env.get(var):
                paths.append(os.path.join(env[var], "uv", "uv.toml"))
    else:
        cfg = env.get("XDG_CONFIG_HOME") or os.path.join(user_home, ".config")
        paths.append(os.path.join(cfg, "uv", "uv.toml"))
        for d in ((env.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(os.pathsep) + ["/etc"]) if system else ():
            if d:
                paths.append(os.path.join(d, "uv", "uv.toml"))
    found, seen = [], set()
    for p in paths:
        text = _file_text(p)
        key = os.path.normcase(os.path.abspath(p))
        if text is None or key in seen:
            continue
        seen.add(key)
        if p.endswith("pyproject.toml") and "[tool.uv" not in text:
            continue
        keys = uv_config_keys(text)
        if keys:
            found.append((p, keys))
    return found


def pip_config_files(env, user_home=None, system=True):
    """The pip configuration files that exist for this user, in the order pip reads them, each one's values over those
    before it: the system's; the user's (the old place, then the new) unless PIP_CONFIG_FILE names a file that is
    there; then PIP_CONFIG_FILE's. PIP_CONFIG_FILE=os.devnull: none at all, as pip has it."""
    user_home = user_home or os.path.expanduser("~")
    own = env.get("PIP_CONFIG_FILE") or ""
    if own and os.path.normcase(own) == os.path.normcase(os.devnull):
        return []
    if os.name == "nt":
        system_files = [os.path.join(env["PROGRAMDATA"], "pip", "pip.ini")] if env.get("PROGRAMDATA") else []
        user_files = [os.path.join(user_home, "pip", "pip.ini")] + (
            [os.path.join(env["APPDATA"], "pip", "pip.ini")] if env.get("APPDATA") else [])
    else:
        if sys.platform == "darwin":
            system_files = ["/Library/Application Support/pip/pip.conf"]
        else:
            system_files = [os.path.join(d, "pip", "pip.conf") for d in
                            (env.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(os.pathsep) if d]
        system_files.append("/etc/pip.conf")
        new = os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(user_home, ".config"), "pip", "pip.conf")
        mac = os.path.join(user_home, "Library", "Application Support", "pip")
        if sys.platform == "darwin" and os.path.isdir(mac):
            new = os.path.join(mac, "pip.conf")
        user_files = [os.path.join(user_home, ".pip", "pip.conf"), new]
    paths = (system_files if system else []) + ([] if own and _file_text(own) is not None else user_files) + (
        [own] if own else [])
    return [x for x in paths if _file_text(x) is not None]


def pip_config_index(env, user_home=None, system=True):
    """(file, index-url) pip would install from by its configuration, or None. As pip merges its files: a later file's
    value over an earlier one's, and a value of [install] over one of [global] whatever file holds it."""
    import configparser
    merged = {}
    for path in pip_config_files(env, user_home, system):
        parser = configparser.RawConfigParser()
        try:
            parser.read_string(_file_text(path) or "", source=path)
        except configparser.Error:
            continue
        for section in ("global", "install"):
            for name in ("index-url", "index_url"):
                if parser.has_option(section, name) and parser.get(section, name).strip():
                    merged[section] = (path, parser.get(section, name).strip().strip("'\""))
    return merged.get("install") or merged.get("global")


def source_overrides(env, user_home=None, folder=None, system=True):
    """What sends an installer somewhere other than its default, or lets it skip a check, as one line each for
    the log and the report: `NAME=value - what it does`. `env` is the user's own environment, as it was before
    net_env added ours. An address shows as its scheme, host and port alone (redact). A source in plain http says it
    is not used (refuse_plain_http), or - where READ_PAGE_ALLOW_HTTP lets it through - that it goes in plain http.
    Empty when nothing is set."""
    user_home = user_home or os.path.expanduser("~")
    folder = folder or os.getcwd()
    out = []
    lists = dict(_SOURCE_LISTS)

    def add(name, value, note):
        if name in lists:      # entry by entry: a list's separator ends no address; what is left of one shows nothing
            shown = lists[name].join(redact(x) if "://" in x else "(not shown)" if "@" in x else x
                                     for x in _entries(value, lists[name]))
        else:
            shown = redact(value)
        out.append("%s%s - %s" % (name, ("=" + (shown if len(shown) <= 100 else shown[:97] + "...")) if shown else "", note))

    def by_http(urls, note, default=""):
        """The note of a source given by these addresses, as refuse_plain_http treats them."""
        kinds = [http_source(u, env) for u in urls]
        refused = [u for u, k in zip(urls, kinds) if k == "refused"]
        if refused and len(refused) == len(urls):
            return REFUSED + ("; %s is used" % default if default else "")
        more = (["not used of it: %s (a source must be https://)" % ", ".join(redact(u) for u in refused)] if refused
                else []) + (["in plain http, which %s lets through: anyone on the network path can read it and change "
                             "what it serves" % ALLOW_HTTP] if "allowed" in kinds else []) + (
            ["in plain http on this machine"] if "loopback" in kinds else [])
        return note + "".join("; " + x for x in more)

    for k, note, default in _SOURCE_VARS:
        if env.get(k):
            urls = [_entry_url(x) for x in _entries(env[k], lists[k])] if k in lists else [env[k]]
            add(k, env[k], by_http(urls, note, default) if k != ALLOW_HTTP else note)
    for name in _BROWSER_HOSTS:
        for k in (_keys(env, name) if name.startswith("npm_") else []):
            if env[k]:
                add(k, env[k], by_http([env[k]], "the browser comes from it, not from Playwright's CDN",
                                       "Playwright's CDN"))
    if env.get("PIP_INDEX_URL"):
        if env.get("UV_DEFAULT_INDEX") or env.get("UV_INDEX_URL"):
            add("PIP_INDEX_URL", env["PIP_INDEX_URL"], "not used: uv's own index setting is there")
        else:
            add("PIP_INDEX_URL", env["PIP_INDEX_URL"], by_http([env["PIP_INDEX_URL"]], "taken as UV_DEFAULT_INDEX: the "
                                                               "Python packages come from it, not from pypi.org", "pypi.org"))
    if _truthy(env.get("UV_NO_VERIFY_HASHES")):
        add("UV_NO_VERIFY_HASHES", env["UV_NO_VERIFY_HASHES"], "not passed on: the packages are checked against the "
            "hashes of the skill's lock")
    link = str(env.get("UV_LINK_MODE") or "").strip()
    if link:
        add("UV_LINK_MODE", link, "not passed on: uv links the environment's files by hard links, its own default - "
            "--setup cleans uv's cache, and an environment of symbolic links into it would lose its files with it"
            if link.lower() == "symlink" else "uv puts the environment's files in place this way")
    for k, what, default in (("READ_PAGE_TESSDATA_URL", "the OCR language data comes from it, not from "
                              "raw.githubusercontent.com (every pack is pinned by SHA256 and checked either way)",
                              "raw.githubusercontent.com"),
                             ("NODEJS_ORG_MIRROR", "Node comes from it, not from nodejs.org (the archive's SHA256 is "
                              "pinned in the skill and checked either way)", "nodejs.org")):
        mirror = (env.get(k) or "").strip()
        if mirror:
            add(k, mirror, by_http([mirror], what, default) if usable_source(mirror, env) or http_source(mirror, env)
                else "not used: a mirror is an https:// address; %s is used" % default)
    if str(env.get("NODE_TLS_REJECT_UNAUTHORIZED") or "").strip() == "0":
        add("NODE_TLS_REJECT_UNAUTHORIZED", "0", "Node does not verify TLS: npm's downloads (defuddle and its "
            "packages, each still held to the SHA512 of the skill's lock) are not checked by a certificate")
    for k in sorted(env):
        low = k.lower()
        key = low[11:]
        if low.startswith("npm_config_") and (key in ("registry", "strict_ssl", "cafile", "ca", "userconfig",
                                                      "globalconfig") or key.endswith(":registry")):
            if key == "strict_ssl" and _truthy(env[k]):
                continue
            if key == "registry" or key.endswith(":registry"):
                note = by_http([env[k]], "npm reads it: defuddle and its packages come from this registry, not from "
                               "registry.npmjs.org (each held to the SHA512 of the skill's lock)", "registry.npmjs.org")
            else:
                note = "npm reads it: " + {
                    "strict_ssl": "npm does not verify TLS", "cafile": "npm trusts the certificates in this file too",
                    "ca": "npm trusts this certificate too", "userconfig": "npm reads this settings file",
                    "globalconfig": "npm reads this settings file"}[key]
            add(k, env[k], note)
    # settings files
    if env.get("UV_CONFIG_FILE"):
        text = _file_text(env["UV_CONFIG_FILE"])
        keys = uv_config_keys(text)
        plain = [u for u in _urls(text) if http_source(u, env) == "refused"]
        add("UV_CONFIG_FILE", env["UV_CONFIG_FILE"], (
            "not read: it names a source in plain http (%s) - %s" % (", ".join(redact(u) for u in plain), HTTP_WHY)) if plain
            else "uv reads this file (it is honoured though UV_NO_CONFIG is set for the install)%s%s" % (
                ": it sets %s" % ", ".join(keys) if keys else "",
                " - the lock's hashes are required on the command line, which no file can switch off"
                if {"verify-hashes", "no-verify-hashes", "require-hashes"} & set(keys) else ""))
    reads = _falsy(env.get("UV_NO_CONFIG"))
    files = uv_config_files(env, user_home, folder, system)
    plain_files = reads and any(any(http_source(u, env) == "refused" for u in _urls(_file_text(p))) for p, _k in files)
    for path, keys in files:
        out.append("%s sets %s - %s" % (path, ", ".join(keys), (
            "not read: one of uv's settings files names a source in plain http, so --setup runs uv with "
            "UV_NO_CONFIG=1 though UV_NO_CONFIG=0 is set" if plain_files else
            "uv reads it (UV_NO_CONFIG=0)" if reads else
            "not read: --setup runs uv with UV_NO_CONFIG=1, so where a folder is does not change what is installed; "
            "name an index in UV_DEFAULT_INDEX (or the file in UV_CONFIG_FILE) to use it")))
    for npmrc in npm_configs(env, user_home):
        for key, value in _pairs(_file_text(npmrc), _NPM_KEYS):
            if key.lower() == "strict-ssl" and _truthy(value):
                continue
            add("%s: %s" % (npmrc, key), value, by_http([value], "npm reads it for the install of defuddle",
                                                        "registry.npmjs.org")
                if key.lower().endswith("registry") else "npm reads it for the install of defuddle")
    taken = pip_config_index(env, user_home, system) if not (env.get("UV_DEFAULT_INDEX") or env.get("UV_INDEX_URL")
                                                              or env.get("PIP_INDEX_URL")) else None
    for p in pip_config_files(env, user_home, system):
        for key, value in _pairs(_file_text(p), _PIP_KEYS):
            if taken and key.lower().replace("_", "-") == "index-url" and (p, value) == taken:
                add("%s: %s" % (p, key), value, by_http([value], "taken as UV_DEFAULT_INDEX (pip's configuration is read "
                                                        "for its index; uv's own is not): the Python packages come from "
                                                        "it, not from pypi.org", "pypi.org"))
            else:
                add("%s: %s" % (p, key), value, "not read: pip, used only if pypi.org gives no uv, is run with "
                    "--isolated and the index uv uses")
    return out


def tessdata_url(lang, env=None):
    """Where a language pack comes from: READ_PAGE_TESSDATA_URL when it may be used (https, or plain http that is not
    refused: usable_source; a folder, or a template with {lang}), else GitHub's raw host. Every pack's SHA256 is
    pinned (TESSDATA_LOCK) and checked whatever serves it."""
    env = env if env is not None else os.environ
    base = (env.get("READ_PAGE_TESSDATA_URL") or "").strip()
    if base and usable_source(base, env):
        return base.replace("{lang}", lang) if "{lang}" in base else base.rstrip("/") + "/" + lang + ".traineddata"
    return TESSDATA_URL % lang


def check_integrity(path, integrity):
    """npm's form of a hash - `sha512-<base64 of the digest>` - held against a file: ValueError when it differs."""
    algo, _, want = integrity.partition("-")
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    if base64.b64encode(h.digest()).decode("ascii") != want:
        raise ValueError("%s: its %s does not match the one pinned" % (os.path.basename(path), algo))


def playwright_node(env):
    """The Node Playwright's wheel carries, in the environment folder `env`: Lib/site-packages/playwright/driver/node.exe
    on Windows, lib/python3.x/site-packages/playwright/driver/node elsewhere; '' where there is none."""
    roots = [os.path.join(env, "Lib", "site-packages")] if os.name == "nt" else \
        sorted(glob.glob(os.path.join(env, "lib*", "python3*", "site-packages")))
    for r in roots:
        path = os.path.join(r, "playwright", "driver", "node.exe" if os.name == "nt" else "node")
        if os.path.isfile(path):
            return path
    return ""


def node_version(out):
    """(24, 21, 0) from `node --version`'s "v24.21.0"; (0,) where it does not read so."""
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(x) for x in m.groups()) if m else (0,)


def fetch(url, dest, sha=None, timeout=60):
    """Download to dest (through dest.part), checking SHA256 when one is given."""
    import urllib.request
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "read-page-setup"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as out:
        promised = r.headers.get("Content-Length")
        shutil.copyfileobj(r, out, 1 << 20)
    try:
        promised = int(promised) if promised is not None else None
    except ValueError:
        promised = None
    if promised is not None and os.path.getsize(tmp) != promised:
        got = os.path.getsize(tmp)                 # urllib does not raise on a body that stops short
        os.unlink(tmp)
        raise ValueError("%s: the connection ended after %d of %d bytes" % (os.path.basename(dest), got, promised))
    if sha and sha256(tmp) != sha.lower():
        os.unlink(tmp)
        raise ValueError("%s: SHA256 does not match" % os.path.basename(dest))
    os.replace(tmp, dest)
    return dest


def cert_error(e):
    """Whether this failure is the machine's TLS roots, not the network."""
    import ssl
    r = getattr(e, "reason", e)
    return isinstance(r, ssl.SSLCertVerificationError) or isinstance(e, ssl.SSLCertVerificationError) \
        or "CERTIFICATE_VERIFY_FAILED" in str(e)


def cert_advice():
    """What to do about a Python that cannot verify a certificate."""
    if sys.platform == "darwin":
        return ("this Python has no root certificates: run 'Install Certificates.command' in its folder under "
                "/Applications/Python 3.x/ (python.org's Python ships none until then), or run --setup "
                "with /usr/bin/python3; behind a proxy that inspects TLS name a file with its root in "
                "SSL_CERT_FILE (neither Python reads the keychain)")
    return ("this Python does not trust the certificate pypi.org presents: install the system's root certificates "
            "(sudo apt install ca-certificates), or - behind a proxy that inspects TLS - name a file with its "
            "root in SSL_CERT_FILE")


def fetch_json(url, timeout=30):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "read-page-setup", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _inside(root, name):
    target = os.path.normcase(os.path.realpath(os.path.join(root, name)))
    base = os.path.normcase(os.path.realpath(root))
    return target == base or target.startswith(base.rstrip(os.sep) + os.sep)


def unpack(archive, dest):
    """A zip or a tar.gz into dest, every member inside it (no absolute paths, no "..")."""
    os.makedirs(dest, exist_ok=True)
    if archive.endswith(".zip") or archive.endswith(".whl"):
        import zipfile
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if os.path.isabs(n) or not _inside(dest, n):
                    raise ValueError("an archive member outside its folder: %s" % n)
            z.extractall(dest)
        return
    import tarfile
    with tarfile.open(archive, "r:*") as t:
        members = t.getmembers()
        for m in members:
            if os.path.isabs(m.name) or not _inside(dest, m.name):
                raise ValueError("an archive member outside its folder: %s" % m.name)
            if (m.issym() or m.islnk()) and not _inside(dest, os.path.join(os.path.dirname(m.name), m.linkname)
                                                         if m.issym() else m.linkname):
                raise ValueError("a link out of its folder: %s" % m.name)
        if _tar_filters():
            t.extractall(dest, members=members, filter="data")
        else:
            _extract_plain(t, members, dest)


def _tar_filters():
    """Whether this Python's tarfile has extraction filters (3.12; 3.8.17, 3.9.17, 3.10.12, 3.11.4 on)."""
    import tarfile
    return hasattr(tarfile, "data_filter")


def _extract_plain(t, members, dest):
    """A tar without the data filter (macOS's /usr/bin/python3 is 3.9.6): files and folders first, each in
    a folder that is really there, then the links one by one - each only where its place and its target
    both resolve inside dest now, with the earlier links in place. Judged by names alone a chain
    (`l1 -> .`, `l2 -> l1/..`, then `l2/x`) writes outside; here `l2/x` is a real folder's file, and the
    link over it is refused. Devices, pipes and hard links are refused (Node's tar has none)."""
    for m in members:
        if not (m.isreg() or m.isdir() or m.issym()):
            raise ValueError("an archive member that is no file, folder or link: %s" % m.name)
    t.extractall(dest, members=[m for m in members if m.isreg() or m.isdir()])
    made = []
    for m in members:
        if not m.issym():
            continue
        place = os.path.join(dest, m.name)
        here = dest
        for part in os.path.dirname(m.name).replace("\\", "/").split("/"):      # a folder only a link stands in
            if part in ("", "."):
                continue
            here = os.path.join(here, part)
            if os.path.islink(here):
                raise ValueError("a link's place is beyond another link: %s" % m.name)
            if not os.path.isdir(here):
                os.mkdir(here)
        parent = os.path.realpath(os.path.dirname(place))
        if not _inside(dest, parent) or os.path.lexists(place):
            raise ValueError("a link where %s cannot be made: %s" % ("a file is" if os.path.lexists(place)
                                                                      else "the folder leaves its own", m.name))
        if not _inside(dest, os.path.join(parent, m.linkname)):
            raise ValueError("a link out of its folder: %s" % m.name)
        try:
            # a tar's links are written with "/"; a Windows link whose target has one does not resolve
            # (the file system reads the target as it is), so the final check below judged Node's own
            # `bin/npm -> ../lib/node_modules/npm/bin/npm-cli.js` to lead out of the folder
            os.symlink(m.linkname.replace("/", os.sep) if os.name == "nt" else m.linkname, place)
        except (OSError, NotImplementedError) as e:
            raise ValueError("a link that cannot be made here (%s): %s" % (e, m.name))
        made.append(place)
    for place in made:                         # once all are in place, every one still ends inside
        if not _inside(dest, place):
            raise ValueError("a chain of links out of its folder: %s" % os.path.relpath(place, dest))


def du(path, skip=()):
    """Bytes of the files under path, by the directory listing alone: an lstat a file took 17 s
    for 41 000 files. Folders named in skip are left out (uv's cache: its files are the
    environment's own, hard-linked)."""
    total, todo = 0, [path]
    skip = set(os.path.normcase(os.path.abspath(p)) for p in skip)
    while todo:
        try:
            it = os.scandir(todo.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if os.path.normcase(os.path.abspath(e.path)) not in skip:
                            todo.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    return total


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return str(n)


# ---------------------------------------------------------------- the work (a detached process)
class Work:
    STEPS = ["network", "uv", "python", "engines", "yt-dlp", "node", "defuddle", "browser", "ocr data", "check"]

    def __init__(self, d, run, skill_version):
        import threading
        self.d, self.run, self.skill = d, run, skill_version
        self.t0 = time.time()
        self.lock = threading.RLock()            # one writer of the logs and the state at a time
        self.running = []
        self.problems = []
        self.parts = {}
        self.prev = load(d)
        self.info = dict(self.prev)
        self.detail = open(os.path.join(d, "setup-detail.log"), "a", encoding="utf-8", errors="replace")
        with open(os.path.join(d, "setup.log"), "w", encoding="utf-8"):
            pass                                # this run's lines only
        self.env = net_env(folder=d)
        self.env.update(UV_CACHE_DIR=os.path.join(d, "cache", "uv"),
                        UV_PYTHON_INSTALL_DIR=os.path.join(d, "python"),
                        UV_PYTHON_INSTALL_BIN="0", UV_PYTHON_INSTALL_REGISTRY="0",
                        UV_PYTHON_DOWNLOADS="manual",   # a Python only through our own install step
                        PLAYWRIGHT_BROWSERS_PATH=os.path.join(d, "browsers"),
                        npm_config_cache=os.path.join(d, "cache", "npm"),
                        npm_config_update_notifier="false", npm_config_fund="false",
                        npm_config_audit="false",
                        # npm (Node 22.1+) keeps its compiled modules in the temp folder otherwise
                        # (`node-compile-cache`, 2.7 MB): inside the one folder, so deleting it removes them
                        NODE_COMPILE_CACHE=os.path.join(d, "cache", "node-compile"))
        self.state(done=False)

    # progress
    def say(self, line):
        """A line of setup.log, which the command shows: an address in it shows its scheme, host and port alone (an
        installer's last words may name one with its credentials)."""
        line = redact(line)
        with self.lock:
            with open(os.path.join(self.d, "setup.log"), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self.log(line)

    def log(self, line):
        with self.lock:
            self.detail.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
            self.detail.flush()

    def state(self, **kw):
        with self.lock:
            st = {"run": self.run, "pid": os.getpid(), "started": self.t0, "updated": time.time(),
                  "steps": len(self.STEPS), "finished": len(self.parts),
                  "step": len(self.parts) + 1, "name": ", ".join(self.running) or "starting"}
            st.update(kw)
            path = os.path.join(self.d, "setup.state")
            try:
                _write_json(path, st)
            except OSError as e:
                # past the retries a reader that keeps the file open (Windows) still stops a replace, not a write in
                # place (measured); a read made while that is half written finds nothing, which the command takes for
                # no news. The last state is what the command waits for. Where even this is refused the work goes on:
                # each state is the whole of it, and the next one carries this one
                try:
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(st, fh, indent=1, ensure_ascii=False)
                except OSError as e2:
                    self.log("setup.state was not written: %s; in place: %s" % (e, e2))

    def step(self, name, fn, need=None):
        """One step: it runs, or is skipped when the step it needs did not succeed; its line goes
        to the log when it ends (the branches' lines in the order they end)."""
        if need and not self.parts.get(need, {}).get("ok"):
            ok, note, took = False, "skipped: no %s" % need, 0.0
        else:
            with self.lock:
                self.running.append(name)
            self.state(done=False)
            t = time.time()
            try:
                ok, note = fn()
            except Exception as e:                             # noqa: BLE001
                ok, note = False, "failed: %s: %s" % (type(e).__name__, str(e)[:160])
                self.log(note)
            took = time.time() - t
            with self.lock:
                self.running.remove(name)
        with self.lock:
            self.parts[name] = {"ok": bool(ok), "note": redact(note), "seconds": round(took, 1)}
            # a step that did not work says so on its own line (the line used to be the note alone)
            self.say("  %2d/%d %-9s %s%s%s" % (self.STEPS.index(name) + 1, len(self.STEPS), name,
                                              "" if ok or str(note).startswith("skipped") else "FAILED: ", note,
                                              (" (%.0f s)" % took) if took >= 2 else ""))
        self.state(done=False)
        return bool(ok)

    def lack(self, part, why, fix=""):
        with self.lock:                          # (setup.json's problems reach the report: addresses as say() has them)
            self.problems.append({"part": part, "why": redact(why), "fix": redact(fix)})

    def sh(self, cmd, timeout=900, env=None, cwd=None):
        """Run an installer; its output goes to setup-detail.log. (returncode, the last lines)."""
        self.log("$ " + redact(" ".join(str(c) for c in cmd)))
        try:
            p = subprocess.run([str(c) for c in cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=timeout, env=env or self.env, cwd=cwd or self.d)
            out = p.stdout.decode("utf-8", "replace")
            rc = p.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = (e.output or b"").decode("utf-8", "replace") + "\n(timed out)", -1
        except OSError as e:
            out, rc = str(e), -1
        self.detail.write(out[-20000:] + "\n")
        self.detail.flush()
        if rc != 0 and not getattr(self, "cert_noted", False) and CERT_FAILURE.search(out):
            self.cert_noted = True              # once: every step behind such a proxy fails the same way
            self.say("  a download failed on a certificate: behind a proxy that inspects TLS its root certificate "
                     "must be in this machine's own store (uv and Node are told to use it, unless UV_SYSTEM_CERTS or "
                     "NODE_USE_SYSTEM_CA is set); a file holding the root can also be named in SSL_CERT_FILE and "
                     "NODE_EXTRA_CA_CERTS")
        self.full = out                         # the whole of it, for what the last three lines cannot say
        tail = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
        return rc, " | ".join(tail[-3:])[-400:]

    # the steps
    def network(self):
        free = shutil.disk_usage(self.d).free
        if free < 2 * 1024 ** 3:
            self.lack("disk", "%s free where it goes (%s); it needs about 1.5 GB" % (human(free), self.d))
        index = self.env.get("UV_DEFAULT_INDEX") or self.env.get("UV_INDEX_URL")
        try:
            fetch_json("https://pypi.org/pypi/uv/%s/json" % UV_VERSION, timeout=15)
            return True, "pypi.org answers; %s free%s" % (
                human(free), ("; the Python packages come from the index set here (%s)" % redact(index)) if index else "")
        except Exception as e:                                 # noqa: BLE001
            if cert_error(e):
                # the network is there; this Python cannot check who answers (not "no internet")
                self.cert_why = cert_advice()
                return False, "pypi.org answers, but its certificate cannot be verified: " + self.cert_why
            if index:
                return True, "pypi.org does not answer (%s); using the index set here" % str(e)[:80]
            return False, "no answer from pypi.org: %s%s" % (str(e)[:120], self._http_hint() or self._config_hint())

    def _http_hint(self):
        """A machine that reaches PyPI only through a mirror in plain http, which is not used: say how it would be."""
        raw = dict(os.environ)
        index = raw.get("UV_DEFAULT_INDEX") or raw.get("UV_INDEX_URL") or raw.get("PIP_INDEX_URL") or (
            pip_config_index(raw) or ("", ""))[1]
        if http_source(index, raw) != "refused":
            return ""
        host = _host_part(index[7:]) or "its host"
        return ("; the index set here (http://%s) is plain http and not used: %s=%s lets it through, if that mirror is "
                "on a network of your own" % (host, ALLOW_HTTP, host.split(":")[0]))

    def _config_hint(self):
        """A machine that reaches PyPI only through the mirror its uv.toml names: --setup does not read that file
        (UV_NO_CONFIG=1), so the mirror must be named another way - say so, where it matters."""
        if _truthy(self.env.get("UV_NO_CONFIG")) is False:
            return ""
        try:
            files = [(p, k) for p, k in uv_config_files(os.environ, os.path.expanduser("~"), self.d)
                     if "index-url" in k or "[[index]]" in k or "extra-index-url" in k or "find-links" in k]
        except OSError:
            return ""
        if not files:
            return ""
        return ("; %s names an index, and --setup does not read uv.toml files (UV_NO_CONFIG=1): set UV_DEFAULT_INDEX to "
                "that index, or UV_CONFIG_FILE to the file, and run it again" % files[0][0])

    def note_sources(self):
        """The first lines of the log: every setting of the user's that sends an installer elsewhere than its
        default, or skips a check (source_overrides) - what the lines below are fetched from is what these say, not
        always pypi.org and nodejs.org. Kept in setup.json for the setup report."""
        try:
            lines = source_overrides(dict(os.environ), os.path.expanduser("~"), self.d)
        except Exception as e:                                 # noqa: BLE001
            self.log("sources: %s" % e)
            lines = []
        if lines:
            self.say("  sources set here, not the defaults:")
            for ln in lines:
                self.say("    " + ln)
            self.info["sources"] = lines
        else:
            self.info.pop("sources", None)

    def uv(self):
        exe = os.path.join(self.d, "uv", "uv-" + UV_VERSION, "uv.exe" if os.name == "nt" else "uv")
        if os.path.isfile(exe):
            rc, out = self.sh([exe, "--version"], timeout=60)
            if rc == 0 and UV_VERSION in out:
                self.uv_exe = exe
                return True, "uv %s" % UV_VERSION
        dl = os.path.join(self.d, "cache", "dl")
        os.makedirs(dl, exist_ok=True)
        why = ""
        try:
            whl = self._uv_wheel(dl)
            tmp = os.path.join(dl, "uv-unpack")
            shutil.rmtree(tmp, ignore_errors=True)
            unpack(whl, tmp)
            os.makedirs(os.path.dirname(exe), exist_ok=True)
            for n in os.listdir(os.path.join(tmp, "uv-%s.data" % UV_VERSION, "scripts")):
                shutil.copy2(os.path.join(tmp, "uv-%s.data" % UV_VERSION, "scripts", n),
                             os.path.join(os.path.dirname(exe), n))
            if os.name != "nt":
                os.chmod(exe, 0o755)
            shutil.rmtree(tmp, ignore_errors=True)
            self.uv_exe = exe
            return True, "uv %s (pypi.org, SHA256 pinned)" % UV_VERSION
        except Exception as e:                                 # noqa: BLE001
            why = str(e)[:160]
            self.log("uv download: " + why)
        other = shutil.which("uv")
        if other:
            self.uv_exe = other
            return True, "uv from this machine (%s): ours did not download - %s" % (other, why)
        self.lack("uv", why)
        return False, "no uv: " + why

    def _uv_wheel(self, dl):
        """uv's wheel for this machine: from pypi.org's JSON, else through pip - and either way a wheel
        whose SHA256 this skill pins (UV_WHEEL_SHA256), checked against the pinned one, not PyPI's."""
        try:
            meta = fetch_json("https://pypi.org/pypi/uv/%s/json" % UV_VERSION)
            f = pick_wheel([x for x in meta.get("urls") or [] if x.get("packagetype") == "bdist_wheel"])
            if f:
                sha = UV_WHEEL_SHA256.get(f["filename"])
                if not sha:
                    raise ValueError("%s is not a uv wheel this skill pins" % f["filename"])
                return fetch(f["url"], os.path.join(dl, f["filename"]), sha, timeout=300)
            raise ValueError("no uv wheel for this machine (%s %s)" % (sys.platform, machine()))
        except Exception as e:                                 # noqa: BLE001
            self.log("pypi.org JSON: %s" % e)
            # --isolated: pip reads none of its own settings (an http index pip.conf lets through with trusted-host),
            # only the index uv uses - which no source in plain http is (refuse_plain_http)
            index = self.env.get("UV_DEFAULT_INDEX") or self.env.get("UV_INDEX_URL") or "https://pypi.org/simple"
            rc, out = self.sh([sys.executable, "-m", "pip", "--isolated", "download", "--only-binary", ":all:",
                               "--no-deps", "--index-url", index, "-d", dl, "uv==%s" % UV_VERSION], timeout=600)
            for n in os.listdir(dl):
                if n.startswith("uv-%s-" % UV_VERSION) and n.endswith(".whl"):
                    path = os.path.join(dl, n)
                    if UV_WHEEL_SHA256.get(n) != sha256(path):
                        os.unlink(path)
                        raise ValueError("the uv wheel pip fetched (%s) is not one this skill pins" % n)
                    return path
            # both reasons: pypi.org's is what failed first, and a Python with no pip (musl's) says only that
            raise ValueError("neither pypi.org (%s) nor pip (%s) gave uv"
                             % (" ".join(str(e).split())[:60], " ".join(out.split())[-60:]))

    def python(self):
        # --no-bin --no-registry: nothing outside our folder (by default uv puts python3.13 into
        # ~/.local/bin and registers the Python in Windows' registry). Never `uv python uninstall`:
        # with its own install folder it dropped another uv Python's registry entry
        rc, out = self.sh([self.uv_exe, "python", "install", PYTHON_VERSION, "--managed-python",
                           "--no-bin", "--no-registry"], timeout=900)
        # uv 0.13.9 ends with "Missing expected target directory for Python minor version link"
        # in a folder a packaged Windows app keeps as its private copy (anything its processes
        # write under AppData, where READ_PAGE_HOME may still point), the Python installed and
        # working all the same: what counts is that it is found and runs
        rc2, out2 = self.sh([self.uv_exe, "python", "find", PYTHON_VERSION, "--managed-python"], timeout=120)
        path = out2.split(" | ")[-1].strip()
        if rc2 == 0 and os.path.isfile(path) and self._py_version(path) == PYTHON_VERSION:
            if rc != 0:
                self.log("uv's install said: %s - the Python is there and runs" % out[-200:])
            self.base_python = path
            return True, "python %s (python-build-standalone)" % PYTHON_VERSION
        why = out[-160:]
        if sys.version_info >= (3, 11):
            self.base_python = sys.executable
            self.lack("python", "our own Python did not download (%s); the environment is built on this "
                                "machine's %s instead" % (why, platform.python_version()), "")
            return True, "python %s of this machine: ours did not download" % platform.python_version()
        self.lack("python", "our own Python did not download (%s), and this machine's is older than 3.11"
                  % why, "readpage.py --setup with Python 3.11 or newer")
        return False, "no Python 3.11+: " + why

    def engines(self):
        with open(LOCK_FILE, encoding="utf-8") as fh:
            lock = fh.read()
        pyver = self._py_version(self.base_python)
        rel = env_id(pyver)
        self.drop_stale_pins(lock, rel)
        env = at(self.d, rel)
        py = os.path.join(env, "Scripts", "python.exe") if os.name == "nt" else os.path.join(env, "bin", "python")
        linked = linked_env(env)
        if linked:
            # built with UV_LINK_MODE=symlink by a --setup before this one: its files are links into uv's cache, which
            # that run cleaned, and nothing short of a new environment brings them back
            self.log("environment %s is links into uv's cache (%s): built again" % (rel, linked))
        if linked or not _python_ok(py):
            shutil.rmtree(env, ignore_errors=True)
            rc, out = self.sh([self.uv_exe, "venv", env, "--python", self.base_python, "-q"])
            if rc != 0:
                return False, "the environment was not created: " + out
        self.env_py = py
        try:                                   # the lock this environment is built from, kept in it (the updater's constraints)
            shutil.copy2(LOCK_FILE, os.path.join(env, ENV_LOCK))
        except OSError as e:
            self.log("lock copy: %s" % e)
        rc, out = self.sh(lock_command(self.uv_exe, py))
        failed = []
        if rc != 0:
            self.log("the whole set did not install; one package at a time")
            pins = lock_pins(lock)
            for top in TOP:
                name = top.split("[")[0]
                pin = pins.get(re.sub(r"[-_.]+", "-", name).lower())
                if not pin:
                    failed.append((name, "error: %s is not in the lock" % name))
                    continue
                rc1, out1 = self.sh(top_command(self.uv_exe, py, top, pin))
                if rc1 != 0:
                    failed.append((name, self.full))
        self.env_rel, self.env_py = rel, py
        self.info.update(env=rel, python=os.path.relpath(py, self.d).replace(os.sep, "/"))
        self.info.pop("pandoc", None)           # an environment of before 2026-11-21 named its pandoc
        for name, full in failed:
            self.lack(*package_problem(name, full))
        failed = [name for name, _full in failed]
        n = lock_packages(lock)
        return not failed or len(failed) < len(TOP), (
            "%d packages, python %s" % (n, pyver) + ("; not here: %s" % ", ".join(failed) if failed else ""))

    def _py_version(self, py):
        rc, out = self.sh([py, "-c", "import platform; print(platform.python_version())"], timeout=60)
        return out.split(" | ")[-1].strip() if rc == 0 else "3"

    def ytdlp(self):
        ok, note = ytdlp_update(self.d, self.uv_exe, self.env_py, self.env, self.sh,
                                lock=os.path.join(at(self.d, self.env_rel), ENV_LOCK))
        if not ok:
            self.lack("yt-dlp", note, "readpage.py --setup")
        return ok, note

    def node(self):
        # the Node of Playwright's wheel: it is in the environment already (the driver runs on it), so the 36-56 MB
        # of nodejs.org's archive and its 90-180 MB on disk are not needed
        rel_env = getattr(self, "env_rel", "")
        wheel = playwright_node(at(self.d, rel_env)) if rel_env else ""
        if wheel:
            rc, out = self.sh([wheel, "--version"], timeout=60)
            if rc == 0 and node_version(out) >= NODE_FLOOR:
                self.node_bin = wheel
                self.info["node_bin"] = os.path.relpath(wheel, self.d).replace(os.sep, "/")
                return True, "node %s (Playwright's own, from its wheel: nothing downloaded)" % out.strip().splitlines()[-1]
            self.log("the Node in Playwright's wheel does not do (%s %s): nodejs.org's is used" % (rc, out[-80:]))
        cur = at(self.d, self.prev.get("node_bin"))
        if cur and os.path.isfile(cur) and "playwright" not in cur:
            rc, out = self.sh([cur, "--version"], timeout=60)
            if rc == 0 and out.strip().lstrip("v") in (NODE_VERSION, NODE_WHEEL):
                self.node_bin = cur
                self.info["node_bin"] = self.prev["node_bin"]
                return True, "node %s" % out.strip()
        try:
            self.node_bin = self._node_official()
            src = "%s, SHA256 pinned" % self.node_source
        except Exception as e:                                 # noqa: BLE001
            self.log("nodejs.org: %s" % e)
            try:
                self.node_bin = self._node_wheel()
                src = "nodejs-wheel-binaries from PyPI (nodejs.org gave none: %s)" % str(e)[:80]
            except Exception as e2:                            # noqa: BLE001
                self.lack("defuddle", "no Node: nodejs.org (%s) and PyPI (%s) failed" % (str(e)[:80], str(e2)[:80]),
                          "install Node.js (nodejs.org), then readpage.py --setup")
                return False, "no Node: %s" % str(e2)[:120]
        self.info["node_bin"] = os.path.relpath(self.node_bin, self.d).replace(os.sep, "/")
        rc, out = self.sh([self.node_bin, "--version"], timeout=60)
        return rc == 0, "node %s (%s)" % (out.strip(), src)

    def _npm_cli(self, node):
        """npm's command line script for the Node at `node`: the one that came with it (nodejs.org's archive and PyPI's
        wheel carry npm), else npm's own tarball from the registry - held to NPM_INTEGRITY, so a mirror or a proxy
        cannot serve other bytes - unpacked in the folder. A Node of Playwright's wheel has no npm."""
        root = os.path.dirname(os.path.dirname(node)) if os.name != "nt" and node.endswith("bin" + os.sep + "node") \
            else os.path.dirname(node)
        for c in (os.path.join(root, "node_modules", "npm", "bin", "npm-cli.js"),
                  os.path.join(root, "lib", "node_modules", "npm", "bin", "npm-cli.js")):
            if os.path.isfile(c):
                return c
        dest = os.path.join(self.d, "node", "npm-" + NPM_VERSION)
        cli = os.path.join(dest, "package", "bin", "npm-cli.js")
        if os.path.isfile(cli) and _read_json(os.path.join(dest, "package", "package.json")).get("version") == NPM_VERSION:
            self.info["npm_cli"] = os.path.relpath(cli, self.d).replace(os.sep, "/")
            return cli
        # the user's registry (the environment's, else their .npmrc's), then npmjs.org's: the tarball's SHA512 is pinned,
        # so any host may serve it, and one that wants a token (401) or is down is not the end of the step
        user = [url for key, url, _w in npm_registries(self.env, os.path.expanduser("~")) if key == "registry"][:1]
        hosts = [r for r in user if usable_source(r, self.env)]
        hosts += [NPM_REGISTRY] if NPM_REGISTRY.rstrip("/") not in [r.strip().rstrip("/") for r in hosts] else []
        dl = os.path.join(self.d, "cache", "dl")
        os.makedirs(dl, exist_ok=True)
        arc = os.path.join(dl, "npm-%s.tgz" % NPM_VERSION)
        why = []
        for registry in hosts:
            try:
                fetch("%s/npm/-/npm-%s.tgz" % (registry.strip().rstrip("/"), NPM_VERSION), arc, None, timeout=300)
                check_integrity(arc, NPM_INTEGRITY)
                break
            except Exception as e:                             # noqa: BLE001
                why.append("%s: %s" % (redact(registry), str(e)[:100]))
                self.log("npm's tarball from %s" % why[-1])
                try:
                    os.unlink(arc)
                except OSError:
                    pass
        else:
            raise ValueError("; ".join(why))
        shutil.rmtree(dest, ignore_errors=True)
        unpack(arc, dest)
        os.unlink(arc)
        if not os.path.isfile(cli):
            raise ValueError("no npm-cli.js in npm's tarball")
        self.info["npm_cli"] = os.path.relpath(cli, self.d).replace(os.sep, "/")
        return cli

    def _node_official(self):
        if musl():
            raise ValueError("nodejs.org has no build for musl")
        m = machine()
        osn = "win" if os.name == "nt" else "darwin" if sys.platform == "darwin" else "linux"
        arch = {"x64": "x64", "arm64": "arm64", "x86": "x86", "armv7l": "armv7l", "ppc64le": "ppc64le",
                "s390x": "s390x"}.get(m)
        if not arch:
            raise ValueError("no Node build for %s" % m)
        name = "node-v%s-%s-%s" % (NODE_VERSION, osn, arch)
        fname = name + (".zip" if os.name == "nt" else ".tar.gz")
        mirror = (self.env.get("NODEJS_ORG_MIRROR") or "").strip()
        if mirror and not usable_source(mirror, self.env):
            # a plain-http mirror is not used (the archive's hash is pinned, so it could not change the bytes, but
            # the request and the version asked for would go in the clear); the log names it (note_sources)
            self.log("NODEJS_ORG_MIRROR is not https:// (%s): not used" % redact(mirror))
            mirror = ""
        self.node_source = "the mirror %s" % redact(mirror).split("/")[2] if mirror else "nodejs.org"
        base = (mirror or "https://nodejs.org/dist").rstrip("/")
        url = "%s/v%s/" % (base, NODE_VERSION)
        sha = NODE_SHA256.get(fname)           # pinned here: a mirror serves the archive, never its checksum
        if not sha:
            raise ValueError("%s is not a Node archive this skill pins" % fname)
        dl = os.path.join(self.d, "cache", "dl")
        os.makedirs(dl, exist_ok=True)
        arc = fetch(url + fname, os.path.join(dl, fname), sha, timeout=600)
        dest = os.path.join(self.d, "node")
        shutil.rmtree(os.path.join(dest, name), ignore_errors=True)
        unpack(arc, dest)
        os.unlink(arc)
        exe = os.path.join(dest, name, "node.exe") if os.name == "nt" else os.path.join(dest, name, "bin", "node")
        if not os.path.isfile(exe):
            raise ValueError("no node in %s" % fname)
        return exe

    def _node_wheel(self):
        """Node from PyPI's nodejs-wheel-binaries: musl's only Node (no Playwright wheel, no nodejs.org build), and the
        way for a network that reaches PyPI alone - held to the SHA256 pinned here for every wheel of it, as the lock's
        packages are (it is not in the lock: only these machines need it)."""
        uv = getattr(self, "uv_exe", "")
        if not uv:
            raise ValueError("it installs with uv, and uv did not install")
        dest = os.path.join(self.d, "node", "wheel-" + NODE_WHEEL)
        shutil.rmtree(dest, ignore_errors=True)
        req = os.path.join(self.d, "cache", "dl", "nodejs-wheel-binaries.txt")
        os.makedirs(os.path.dirname(req), exist_ok=True)
        with open(req, "w", encoding="utf-8") as fh:
            fh.write(node_wheel_requirement())
        rc, out = self.sh([uv, "pip", "install", "--target", dest, "--only-binary", ":all:",
                           "--python", getattr(self, "env_py", "") or sys.executable, "-r", req, "--require-hashes"])
        if rc != 0:
            raise ValueError(out[-160:])
        for c in (os.path.join(dest, "nodejs_wheel", "node.exe"), os.path.join(dest, "nodejs_wheel", "bin", "node")):
            if os.path.isfile(c):
                return c
        raise ValueError("no node in nodejs-wheel-binaries")

    def defuddle(self):
        node = getattr(self, "node_bin", "")
        if not node:
            return False, "no Node, so no defuddle"
        prefix = os.path.join(self.d, "npm")
        root = npm_root(prefix)
        lock = _read_json(NPM_LOCK)
        n = len([k for k in (lock.get("packages") or {}) if k])
        self.info["npm"] = "npm"
        # the folder of its command (defuddle.cmd, or a link to its cli.js) that reads put first on PATH
        self.info["npm_bin"] = os.path.relpath(os.path.join(root, "node_modules", ".bin"), self.d).replace(os.sep, "/")
        self.info.pop("npm_cli", None)                         # only an npm of ours that was used stays named
        if not n:
            self.lack("defuddle", "the skill's %s is missing or damaged" % os.path.basename(NPM_LOCK),
                      "a whole copy of the skill (git pull, or its ZIP), then readpage.py --setup")
            return False, "no lock of defuddle's packages in the skill"
        shim = os.path.join(root, "node_modules", ".bin", "defuddle.cmd" if os.name == "nt" else "defuddle")
        if _read_json(os.path.join(root, "package-lock.json")) == lock and os.path.isfile(shim) \
                and not npm_tree_lacks(root, lock):
            return True, "defuddle %s" % DEFUDDLE_VERSION
        try:
            cli = self._npm_cli(node)
        except Exception as e:                                 # noqa: BLE001
            self.lack("defuddle", "no npm: %s" % str(e)[:160], "readpage.py --setup again")
            return False, "no npm: %s" % str(e)[:120]
        os.makedirs(root, exist_ok=True)
        _write_json(os.path.join(root, "package.json"), npm_package())
        shutil.copyfile(NPM_LOCK, os.path.join(root, "package-lock.json"))
        env = dict(self.env, PATH=os.path.dirname(node) + os.pathsep + self.env.get("PATH", ""))
        rc, out = self.sh(defuddle_command(node, cli, root), env=env)
        lacks = npm_tree_lacks(root, lock)
        if rc != 0 or lacks or not os.path.isfile(shim):
            why = ("npm did not install it: " + out[-120:]) if rc != 0 else (
                "npm left out %s: a tarball that does not match the SHA512 of the skill's lock, or did not arrive"
                % ", ".join(lacks[:4]) if lacks else "npm made no defuddle command")
            self.lack("defuddle", why, "readpage.py --setup again")
            return False, why
        return True, "defuddle %s and %d packages (npm ci: each tarball held to the SHA512 of the skill's lock)" % (
            DEFUDDLE_VERSION, n - 1)

    def browser(self):
        py = getattr(self, "env_py", "")
        if not py:
            return False, "no environment, so no browser"
        if any(p.get("part") == "browser" for p in self.problems):      # playwright itself did not install
            return False, "skipped: playwright is not installed here (said above)"
        self.info["browsers"] = "browsers"
        rc, out = self.sh([py, "-E", "-m", "playwright", "install", BROWSER], timeout=1200)
        if rc != 0:
            # where Playwright has no build for this distribution (it says "does not support") the machine's own
            # Chromium is the way; where the download failed, once more or through a mirror first
            fix = _system_fix("browser")
            if "does not support" not in out:
                fix = "readpage.py --setup again (PLAYWRIGHT_DOWNLOAD_HOST names a mirror), or the machine's own: " + fix
            self.lack("browser", "Playwright's browser did not download: " + out[-120:], fix)
            return False, "not downloaded: " + out[-120:]
        found = sorted(n for n in os.listdir(os.path.join(self.d, "browsers")) if n.startswith("chromium_headless_shell-"))
        return True, "%s %s" % (BROWSER, found[-1].split("-")[-1] if found else "?")

    def ocr_data(self):
        """The packs every environment gets (ownenv.OCR_DEFAULT_PACKS), the user's own languages' first, osd for a
        scan's script, and the packs the user named - now, or at an earlier --setup (ocr_named) - each held to its
        SHA256 in TESSDATA_LOCK, whoever serves it."""
        td = os.path.join(self.d, "tessdata")
        os.makedirs(td, exist_ok=True)
        self.info["tessdata"] = "tessdata"
        pins = tessdata_pins()
        mine = ownenv.ocr_default_packs(os.environ)               # the defaults, the user's languages' first, osd
        named, now = ocr_named(os.environ, self.prev, td, mine)
        got, bad = [], []
        for lang in mine + [x for x in named if x not in mine]:
            pin = pins.get(lang)
            if not pin:
                bad.append(lang)
                self.log("tessdata %s: not a pack of tessdata_fast 4.1.0 (a pack's name: lower case, with _ for a "
                         "script - chi_sim)" % lang)
                continue
            dest = os.path.join(td, lang + ".traineddata")
            if os.path.isfile(dest) and sha256(dest) == pin[0]:
                got.append(lang)
                continue
            try:
                fetch(tessdata_url(lang, self.env), dest, pin[0], timeout=300)
                got.append(lang)
            except Exception as e:                             # noqa: BLE001
                bad.append(lang)
                self.log("tessdata %s: %s" % (lang, e))
        if bad:
            self.lack("ocr-langs", "language data not downloaded: %s" % ", ".join(bad))
        self.info["ocr_langs"] = [x for x in got if x != "osd"]
        # what the user named stays named: the next plain --setup keeps it, so reads go on with it (it was dropped,
        # and reads went back to English without a word)
        self.info["ocr_named"] = [x for x in named if x in pins]
        own = [x for x in ownenv.ocr_languages(os.environ) if ownenv.ocr_pack_for(x)]
        why = " - the %d packs every environment gets (the languages with the most web text, scripts English reads " \
              "as nothing, Chinese, Japanese and Korean printed in columns, and Fraktur)%s; osd tells a scanned " \
              "page's script and which way up it is, and each page is read with its own pack" % (
                  len(ownenv.OCR_DEFAULT_PACKS), (", the user's languages (%s) first" % ", ".join(own)) if own else "")
        more = [x for x in named if x not in mine and x in got]
        kept = ("; named %s, kept for the next --setup: %s" % ("now" if now else "at an earlier --setup", "+".join(more))
                if more else "")
        return bool(got), "%s (tessdata_fast 4.1.0, each pack held to its SHA256%s%s; --setup --ocr-langs eng+hin " \
                          "names others)" % ("+".join(got), why, kept) + ("; failed: %s" % ", ".join(bad) if bad else "")

    def check(self):
        py = getattr(self, "env_py", "")
        if not py:
            return False, "nothing to check"
        env = dict(self.env)
        env.pop("READ_PAGE_ENV_CHILD", None)
        pending = os.path.join(self.d, "setup-new.json")      # setup.json comes after the check
        _write_json(pending, self.info)
        result = os.path.join(self.d, "setup-check.json")
        try:                                   # the last run's answers are not this run's: a check that is cut off or
            os.unlink(result)                  # crashes would leave them, to be read as its own
        except OSError:
            pass
        rc, out = self.sh([py, "-E", "-B", "-X", "utf8", os.path.abspath(__file__), "--check", self.d,
                           result, pending], timeout=300, env=env)
        try:
            os.unlink(pending)
        except OSError:
            pass
        res = _read_json(result)
        self.info["checked"] = res
        if not res:
            # it wrote nothing: it did not get to its end (cut off at 300 s, a crash, an interpreter that did not start)
            why = out[-160:] or "no output"
            self.lack("check", "the check did not finish (exit code %s: %s)" % (rc, why),
                      "readpage.py --setup again; the output is in %s" % os.path.join(self.d, "setup-detail.log"))
            return False, "the check did not finish (exit code %s): %s" % (rc, why)
        bad = sorted(k for k, v in res.items() if isinstance(v, dict) and not v.get("ok"))
        for k in bad:
            if k == "engines" and engines_covered(res[k].get("why"), self.problems):
                continue                                       # each of them was named when it did not install
            if not any(p["part"] == k for p in self.problems):
                self.lack(k, res[k].get("why") or "it did not answer", res[k].get("fix") or "")
        good = sorted(k for k, v in res.items() if isinstance(v, dict) and v.get("ok"))
        return rc == 0 and not bad, ("%d of %d answer" % (len(good), len(good) + len(bad))
                                     + ("; not: %s" % ", ".join(bad) if bad else ""))

    def tidy(self):
        """Keep the environment in use and the one before it (a read may still run there); the rest goes, unless a
        process runs from it (an MCP server started under an older one runs for weeks across pin moves); so do
        Pythons and Nodes no environment of these uses, and uv's cache is looked after."""
        keep_envs = {self.info.get("env"), self.prev.get("env")}
        envs = os.path.join(self.d, "envs")
        homes = set()
        for n in (os.listdir(envs) if os.path.isdir(envs) else []):
            p = os.path.join(envs, n)
            if "envs/" + n not in keep_envs:
                used = env_in_use(p)
                if used is False:
                    shutil.rmtree(p, ignore_errors=True)      # (on Windows an MCP server still in it keeps it)
                    continue
                self.log("environment %s kept: %s" % (n, "a process runs from it" if used else
                                                      "whether one runs from it cannot be told here"))
            try:
                with open(os.path.join(p, "pyvenv.cfg"), encoding="utf-8") as fh:
                    for line in fh:
                        k, _, v = line.partition("=")
                        if k.strip() == "home":
                            homes.add(os.path.normcase(os.path.realpath(v.strip())))
            except OSError:
                pass
        pys = os.path.join(self.d, "python")
        for n in (os.listdir(pys) if os.path.isdir(pys) else []):
            p = os.path.join(pys, n)
            if n.startswith("cpython-") and os.path.isdir(p) and not any(
                    h.startswith(os.path.normcase(os.path.realpath(p))) for h in homes):
                shutil.rmtree(p, ignore_errors=True)
        nodes = os.path.join(self.d, "node")
        cur = (self.info.get("node_bin") or "") + "/" + (self.info.get("npm_cli") or "")
        for n in (os.listdir(nodes) if os.path.isdir(nodes) else []):
            if n not in cur.split("/"):
                shutil.rmtree(os.path.join(nodes, n), ignore_errors=True)
        shutil.rmtree(os.path.join(self.d, "cache", "dl"), ignore_errors=True)
        self.tidy_uv_cache()

    def drop_stale_pins(self, new_lock, rel):
        """Before an update installs its pins: the packages whose version the new lock changes or drops have
        their old files in uv's cache, and nothing would ever remove them (`uv cache prune` finds nothing: those
        wheels stay reachable, measured with uv 0.13.9 - "No unused entries found" after an old environment's wheels
        were all that was left). The environment that used them keeps its files by their hard links. Done before
        the install, because a clean after it would take the new versions out too, and the next update would fetch
        every package whose pin did not move again."""
        prev = self.prev.get("env")
        if not prev or prev == rel or not getattr(self, "uv_exe", ""):
            return
        old_lock = env_lock(self.d, self.prev)
        if not old_lock:
            self.cache_unknown = True        # built before its lock was kept: which wheels are stale is not known
            return
        try:
            with open(old_lock, encoding="utf-8") as fh:
                names = moved_pins(fh.read(), new_lock)
        except OSError:
            self.cache_unknown = True
            return
        if names:
            self.sh([self.uv_exe, "cache", "clean"] + names, timeout=300)

    def tidy_uv_cache(self):
        """uv's cache holds each wheel the environment was built from, hard-linked into it (so it costs the
        folder next to nothing - where the file system has links), and every wheel an older pin left behind.
        `drop_stale_pins` removes those as they come. The cache is pruned whole (`--ci`: every wheel goes, the
        environment keeps its files by their links, and an update fetches what it needs once more) where an older
        environment's lock was not kept, and where more than STALE_CACHE_BYTES of it is in no environment (a fresh
        install leaves 14-21 MB; what is left after an index was changed, or by a version that did not clean, is
        hundreds). Its size goes in the report either way."""
        uv = getattr(self, "uv_exe", "")
        path = os.path.join(self.d, "cache", "uv")
        total, alone = cache_bytes(path)
        stale = alone is not None and alone > STALE_CACHE_BYTES
        if uv and (getattr(self, "cache_unknown", False) or stale):
            rc, out = self.sh([uv, "cache", "prune", "--ci"], timeout=300)
            self.log("uv cache prune --ci (%s): %s" % ("an older environment's lock was not kept" if not stale else
                                                      "%s of the cache is in no environment" % human(alone or 0), out[-120:]))
            total, alone = cache_bytes(path)
        self.cache_size = (total, alone)

    @staticmethod
    def cache_note(total, alone):
        """uv's cache for the closing line: its size, and what of it the environment does not already hold."""
        if not total:
            return ""
        if alone is None:
            return " (uv's cache is %s, mostly hard-linked into the environment)" % human(total)
        return " (uv's cache is %s, %s of it in no environment: the rest is hard-linked into it)" % (human(total), human(alone))

    def wait_updater(self, seconds=300):
        """A background yt-dlp update holds ytdlp.lock while it works in this very environment: wait for
        it (a few minutes at most), then hold the lock for this run, so that none starts meanwhile."""
        path = os.path.join(self.d, "ytdlp.lock")
        t = time.time()
        self.ytlock = _try_lock(path)
        if self.ytlock is None:
            self.say("a yt-dlp update of an earlier read is at work in this environment; waiting for it")
            while self.ytlock is None and time.time() - t < seconds:
                time.sleep(2)
                self.ytlock = _try_lock(path)
            if self.ytlock is None:
                self.say("it has not ended in %d s; going on" % seconds)

    def go(self):
        """The steps one after another. Side by side was measured (2026-11-19, from nothing into
        fresh folders on one Windows machine: 62 and 68 s against 68 and 65 one after another; WSL 83 against 79):
        no gain - the link is the limit (9 MB/s, no faster with four downloads at once), about
        48 s of the 65 are downloads, and the branches only shared it; only the check's engines
        answer side by side."""
        self.wait_updater()
        self.note_sources()
        ok_net = self.step("network", self.network)
        if not ok_net:
            for name in self.STEPS[1:]:
                with self.lock:
                    self.parts[name] = {"ok": False, "note": "skipped"}
        else:
            self.step("uv", self.uv)
            self.step("python", self.python, need="uv")
            self.step("engines", self.engines, need="python")
            self.step("yt-dlp", self.ytdlp, need="engines")
            self.step("node", self.node)
            self.step("defuddle", self.defuddle, need="node")
            self.step("browser", self.browser, need="engines")
            self.step("ocr data", self.ocr_data)
        self.step("check", self.check)
        ready = bool(self.parts.get("engines", {}).get("ok")) and getattr(self, "env_py", "")
        if ready:
            self.info.update(schema=STATE_SCHEMA, skill=self.skill, problems=self.problems,
                             parts=self.parts, built=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                             seconds=round(time.time() - self.t0))
            _write_json(os.path.join(self.d, "setup.json"), self.info)
            try:
                self.tidy()
            except Exception as e:                             # noqa: BLE001
                self.log("tidy: %s" % e)
        took = time.time() - self.t0
        if not ok_net and getattr(self, "cert_why", ""):
            self.say("nothing was installed: %s. Reads work as before with what this machine has." % self.cert_why)
        elif not ok_net:
            self.say("nothing was installed: --setup needs the internet (pypi.org; nodejs.org, github.com "
                     "and Playwright's CDN for the rest). Reads work as before with what this machine has.")
        else:
            old = [os.path.join(self.d, "envs", n) for n in (os.listdir(os.path.join(self.d, "envs"))
                   if os.path.isdir(os.path.join(self.d, "envs")) else []) if "envs/" + n != self.info.get("env")]
            size = du(self.d, skip=[os.path.join(self.d, "cache")] + old)
            total, alone = getattr(self, "cache_size", (0, None))
            self.say("done in %d min %02d s; %s in %s%s. To remove it all, delete that folder."
                     % (took // 60, took % 60, human(size + (alone or 0)), self.d, self.cache_note(total, alone)))
            self.info["disk"] = {"folder": size + (alone or 0), "cache": total, "cache_alone": alone}
            if ready:
                _write_json(os.path.join(self.d, "setup.json"), self.info)
            for p in self.problems:
                self.say("not done: %s - %s%s" % (p["part"], p["why"], (" - " + p["fix"]) if p.get("fix") else ""))
        if getattr(self, "ytlock", None):
            _unlock(self.ytlock)
        self.state(done=True, ok=bool(ready) and not any(not v["ok"] for v in self.parts.values()))


def node_wheel_requirement():
    """nodejs-wheel-binaries at NODE_WHEEL with the SHA256 of each of its wheels (NODE_WHEEL_SHA256), as a requirements
    file for `uv pip install -r ... --require-hashes`."""
    return "nodejs-wheel-binaries==%s \\\n%s\n" % (NODE_WHEEL, " \\\n".join(
        "    --hash=sha256:%s" % h for h in sorted(set(NODE_WHEEL_SHA256.values()))))


def tessdata_pins(path=None):
    """{pack: (sha256, size)} of every pack of tessdata_fast 4.1.0 (TESSDATA_LOCK); {} where the file is not there."""
    pins = {}
    try:
        with open(path or TESSDATA_LOCK, encoding="utf-8") as fh:
            for ln in fh:
                parts = ln.split()
                if len(parts) == 3 and re.fullmatch(r"[0-9a-f]{64}", parts[0]) and parts[1].isdigit():
                    pins[parts[2]] = (parts[0], int(parts[1]))
    except OSError:
        pass
    return pins


def ocr_named(env, prev, td, defaults=()):
    """(the OCR packs the user named, whether named now): READ_PAGE_OCR_LANGS as it is now (`--setup --ocr-langs`
    sets it) - the user's word replaces what was named before -, else the packs an earlier --setup was named
    (setup.json's ocr_named) that are still in `td`. A setup.json of before ocr_named was kept names them among its
    ocr_langs: those beyond today's `defaults` count as named."""
    raw = str(env.get("READ_PAGE_OCR_LANGS") or "").strip()
    if raw:
        out = []
        for x in raw.split("+"):
            if x.strip() and x.strip() not in out:
                out.append(x.strip())
        return out, True
    earlier = prev.get("ocr_named") if isinstance(prev.get("ocr_named"), list) else [
        x for x in (prev.get("ocr_langs") or []) if x not in defaults]
    return [x for x in earlier if isinstance(x, str) and re.fullmatch(r"[a-z]+(?:_[a-z]+)*", x)
            and os.path.isfile(os.path.join(td, x + ".traineddata"))], False


def npm_package():
    """The package.json that defuddle's lock (NPM_LOCK) is the lock of: defuddle, at its pinned version."""
    return {"name": "read-page-defuddle", "private": True, "dependencies": {"defuddle": DEFUDDLE_VERSION}}


def npm_root(prefix):
    """Where defuddle's tree goes under the npm folder: the place an `npm install -g` put it before (`node_modules` on
    Windows, `lib/node_modules` elsewhere), so a read of an older environment, still running, finds its files."""
    return prefix if os.name == "nt" else os.path.join(prefix, "lib")


def defuddle_command(node, cli, root):
    """npm's command for defuddle: `npm ci` of the skill's lock (NPM_LOCK, written into `root` with its package.json),
    so defuddle and every package it brings are the lock's, each tarball held to the SHA512 the lock names, whatever
    registry serves it - the same tree on every machine, and nothing resolved anew. Its optional packages too
    (linkedom, which its Node entry needs, is one: npm leaves out an optional package whose tarball does not match,
    so the step checks the tree against the lock after it). No install script of any package runs."""
    return [node, cli, "ci", "--prefix", root, "--no-audit", "--no-fund", "--ignore-scripts", "--include=optional",
            "--loglevel=error"]


def npm_tree_lacks(root, lock):
    """The packages of the lock that npm did not put in `root`, or put there in another version or from other bytes:
    npm's own record of what it installed (node_modules/.package-lock.json) against the lock. [] when they agree."""
    have = (_read_json(os.path.join(root, "node_modules", ".package-lock.json")).get("packages") or {})
    want = dict((k, v) for k, v in ((lock or {}).get("packages") or {}).items() if k)
    return sorted(k[len("node_modules/"):] for k, v in want.items()
                  if (have.get(k) or {}).get("version") != v.get("version")
                  or (have.get(k) or {}).get("integrity") != v.get("integrity")
                  or not os.path.isfile(os.path.join(root, *k.split("/") + ["package.json"])))


def lock_command(uv, py, lock=None):
    """uv's command for the whole set: the lock's packages and nothing more, every file held to its hash. With
    --require-hashes a package the lock does not name is refused - an index that serves a pinned wheel with a
    metadata file (PEP 658) naming one more dependency got it installed, unhashed, beside the pinned ones (measured
    with uv 0.13.9) - and no settings file switches the check off (`verify-hashes = false` in a UV_CONFIG_FILE did)."""
    return [uv, "pip", "install", "--python", py, "-r", lock or LOCK_FILE, "--only-binary", ":all:", "--require-hashes"]


def top_command(uv, py, top, pin, lock=None):
    """One top package by the lock's pin, the lock as constraints, under the same --require-hashes: the fallback where
    the whole set does not install (a package of it has no wheel for the machine). A bare name is refused in that mode,
    so it is named with its pin; its dependencies take their hashes from the constraints."""
    return [uv, "pip", "install", "--python", py, "%s==%s" % (top, pin), "-c", lock or LOCK_FILE, "--only-binary",
            ":all:", "--require-hashes"]


def linked_env(env, limit=4000):
    """Why an environment's files are not its own - a symbolic link among its site-packages (a --setup run with
    UV_LINK_MODE=symlink links every file into uv's cache, which it then cleaned) - or '' (none found, or no such
    environment). The first two levels of site-packages, at most `limit` entries."""
    roots = [os.path.join(env, "Lib", "site-packages")] if os.name == "nt" else \
        sorted(glob.glob(os.path.join(env, "lib*", "python3*", "site-packages")))
    seen = 0
    for root in roots:
        todo = [(root, 0)]
        while todo:
            here, depth = todo.pop()
            try:
                entries = list(os.scandir(here))
            except OSError:
                continue
            for e in entries:
                seen += 1
                if seen > limit:
                    return ""
                if e.is_symlink():
                    return os.path.relpath(e.path, env)
                if depth < 1 and e.is_dir(follow_symlinks=False):
                    todo.append((e.path, depth + 1))
    return ""


def ytdlp_command(uv, py, now=None, floor="", lock=None):
    """uv's command for the newest yt-dlp that has been out YTDLP_AGE_DAYS - and never an older one than
    `floor`, the version installed now (with no floor, a pin of the lock younger than the cutoff made
    uv backtrack to yt-dlp 2022.3.8.2, which has no `default` extra and needs none of the packages: exit 0,
    "success", and every video read passing --js-runtimes to a yt-dlp that rejects it). The packages of
    the environment's own lock stay at its pins, held to its hashes (--verify-hashes: no settings file switches that
    off); the date holds only what floats (YTDLP_FLOATS), which no hash can name - its files are checked by TLS alone,
    from an https index (refuse_plain_http)."""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((now or time.time()) - YTDLP_AGE_DAYS * 86400))
    cmd = [uv, "pip", "install", "--python", py, "--upgrade", YTDLP + (">=" + floor if floor else ""),
           "-c", lock or LOCK_FILE, "--only-binary", ":all:", "--verify-hashes"]
    for pkg in YTDLP_FLOATS:
        cmd += ["--exclude-newer-package", "%s=%s" % (pkg, cutoff)]
    return cmd


def _vkey(v):
    """A yt-dlp version ("2026.10.26", "2026.11.20.232656") as numbers to compare."""
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _ytdlp_version(py):
    """The yt-dlp installed in the environment, "" when there is none (or it does not start)."""
    try:
        p = subprocess.run([py, "-E", "-m", "yt_dlp", "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=120)
        return p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def env_lock(d, info):
    """The lock the environment was built from: its own copy; else the skill's lock when that is the one
    its folder's name says (an environment from before the copy was kept); else None - the skill's pins
    have moved, and constraining with them would change an environment they did not build."""
    own = os.path.join(at(d, info.get("env")), ENV_LOCK) if info.get("env") else ""
    if own and os.path.isfile(own):
        return own
    m = re.match(r"envs/py([0-9.]+)-", str(info.get("env") or ""))
    try:
        if m and info.get("env") == env_id(m.group(1)):
            return LOCK_FILE
    except OSError:
        pass
    return None


def ytdlp_update(d, uv, py, env, sh, now=None, lock=None):
    """Install or update yt-dlp in the environment: (ok, note). It never goes backwards: the version
    installed now is the floor, and a result older than it is put back. The stamp - when it was looked
    for - is touched after an update that worked, never before (an updater killed with its command
    had already said "looked", and nothing looked again for three days); a look that failed leaves
    `ytdlp.failed`, so a read does not start another at once."""
    before = _ytdlp_version(py)
    rc, out = sh(ytdlp_command(uv, py, now, floor=before, lock=lock), timeout=600, env=env)
    version = _ytdlp_version(py)
    if before and _vkey(version) < _vkey(before):
        sh([uv, "pip", "install", "--python", py, "%s==%s" % (YTDLP, before), "-c", lock or LOCK_FILE,
            "--only-binary", ":all:", "--verify-hashes"], timeout=600, env=env)
        version = _ytdlp_version(py)
        rc, out = 1, "it would have gone back from %s: kept" % before
    if rc == 0 and version:
        try:
            with open(os.path.join(d, "ytdlp.stamp"), "w", encoding="utf-8") as fh:
                fh.write(version + "\n")
            os.unlink(os.path.join(d, "ytdlp.failed"))
        except OSError:
            pass
        if version != before:
            # every release stays in uv's cache for good otherwise (one about every three days); the environment
            # keeps its own file by its hard link, and the next update fetches a release that is new anyway
            sh([uv, "cache", "clean", "yt-dlp", "yt-dlp-ejs"], timeout=120, env=env)
    else:
        try:
            with open(os.path.join(d, "ytdlp.failed"), "w", encoding="utf-8") as fh:
                fh.write("%s\n" % out[-200:])
        except OSError:
            pass
    if rc != 0 and not version:
        return False, "not installed: " + out[-140:]
    return True, "%s%s" % (version or "?", "" if rc == 0 else " (kept: no newer one could be fetched - %s)" % out[-80:])


def ytdlp_background(d):
    """Start the update apart from the read that asked: nothing waits for it. True when it was started -
    not where a job around the read would end it with the read (it would be killed seconds in)."""
    return _detached([sys.executable, "-E", "-B", "-X", "utf8", os.path.abspath(__file__), "--ytdlp", d], d,
                     os.path.join(d, "setup-detail.log"), attached_ok=False) == "free"


def _ytdlp_worker(d):
    """The background update, three tries twenty seconds apart (on Windows a read still running the old
    yt-dlp holds its file). It has a lock of its own, ytdlp.lock - held by one update, and by a --setup
    for as long as it runs, so a read starts no second one meanwhile - and gives way to a --setup."""
    fh = _try_lock(os.path.join(d, "ytdlp.lock"))
    if fh is None:
        return 0
    try:
        if _locked(os.path.join(d, "setup.lock")):
            return 0                                   # a --setup is at work: it updates yt-dlp itself
        info = load(d)
        py = at(d, info.get("python"))
        uv = os.path.join(d, "uv", "uv-" + UV_VERSION, "uv.exe" if os.name == "nt" else "uv")
        lock = env_lock(d, info)
        if not (_python_ok(py) and os.path.isfile(uv) and lock):
            return 0
        env = net_env(folder=d)                        # the same sources as --setup's: none in plain http
        env.update(UV_CACHE_DIR=os.path.join(d, "cache", "uv"), UV_PYTHON_DOWNLOADS="never")
        log = open(os.path.join(d, "setup-detail.log"), "a", encoding="utf-8", errors="replace")

        def sh(cmd, timeout=600, env=env):
            log.write("%s (yt-dlp, background) $ %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(cmd)))
            try:
                p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=timeout, env=env, cwd=d)
                out, rc = p.stdout.decode("utf-8", "replace"), p.returncode
            except (OSError, subprocess.SubprocessError) as e:
                out, rc = str(e), -1
            log.write(out[-4000:] + "\n")
            log.flush()
            return rc, " | ".join(ln.strip() for ln in out.strip().splitlines()[-3:])[-300:]
        for attempt in range(3):
            ok, note = ytdlp_update(d, uv, py, env, sh, lock=lock)
            if ok and "kept" not in note:
                break
            if attempt < 2:                            # no pause after the last try: it serves nothing
                time.sleep(20)
        log.write("%s yt-dlp: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), note))
        log.close()
    finally:
        _unlock(fh)
    return 0


def _running(exe):
    """Windows: a program that runs cannot be opened for writing - an environment in use."""
    if os.name != "nt" or not os.path.isfile(exe):
        return False
    try:
        with open(exe, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _proc_cmdlines(root="/proc"):
    """The arguments of every process /proc lists (Linux): [[str]], or None where there is no /proc."""
    try:
        names = os.listdir(root)
    except OSError:
        return None
    mine, out = str(os.getpid()), []
    for n in names:
        if not n.isdigit() or n == mine:
            continue
        try:
            with open(os.path.join(root, n, "cmdline"), "rb") as fh:
                raw = fh.read(1 << 16)
        except OSError:
            continue                                    # it ended, or it is another user's and says nothing
        out.append([a.decode("utf-8", "replace") for a in raw.split(b"\0") if a])
    return out


def _ps_commands():
    """The command line of every process of the machine from `ps` (macOS and the BSDs have no /proc): [str], or
    None where ps does not answer."""
    try:
        p = subprocess.run(["ps", "-axww", "-o", "command="], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.decode("utf-8", "replace").splitlines() if p.returncode == 0 else None


def uses_folder(folder, commands):
    """Whether any of these commands - a list of arguments, or a line as `ps` prints it - names a path inside
    `folder`: its interpreter, or the script an interpreter of it runs. A sibling whose name only starts the same
    way is no match (`py3.13-abc` and `py3.13-abcdef`). An argument (of a list: /proc's) that names the folder by
    another way to it - a second link to it, `//` or `/./` in it - is matched by where it leads."""
    roots = {str(folder), os.path.abspath(folder), os.path.realpath(folder)}
    marks = [r.rstrip(os.sep) + os.sep for r in roots]
    real = os.path.normcase(os.path.realpath(folder)).rstrip(os.sep)
    for c in commands:
        for arg in (c if isinstance(c, (list, tuple)) else [c]):
            if any(m in arg for m in marks) or arg.rstrip(os.sep) in roots:
                return True
            if isinstance(c, (list, tuple)) and (os.sep in arg or (os.altsep and os.altsep in arg)) and "://" not in arg:
                try:
                    leads = os.path.normcase(os.path.realpath(arg))
                except (OSError, ValueError):
                    continue
                if leads == real or leads.startswith(real + os.sep):
                    return True
    return False


def env_in_use(folder):
    """Whether a program of this environment runs now, so that its folder must stay: True, False, or None where
    that cannot be told. An MCP server started under an environment runs for weeks, across pin moves, and its
    interpreter is a file of the folder - the second move after it used to delete it (tidy keeps two), and the
    server's next read started an interpreter that was gone. Windows: a program that runs cannot be opened for
    writing. Linux: the arguments of every process in /proc - an `exec` (what a read does on POSIX) leaves the
    environment's interpreter as argument 0; macOS: `ps`."""
    if os.name == "nt":
        return _running(os.path.join(folder, "Scripts", "python.exe"))
    cmds = _proc_cmdlines() if sys.platform.startswith("linux") else None
    if cmds is None:
        cmds = _ps_commands()
    if cmds is None:
        return None
    return uses_folder(folder, cmds)


# ---------------------------------------------------------------- uv's cache
def lock_pins(text):
    """{package: version} of a lock, a name as pip compares them (lower case, a run of - _ . is one -)."""
    pins = {}
    for ln in (text or "").splitlines():
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)", ln)
        if m:
            pins[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return pins


def moved_pins(old_lock, new_lock):
    """The packages of the old lock that the new one gives another version or drops: what an update leaves in uv's cache."""
    old, new = lock_pins(old_lock), lock_pins(new_lock)
    return sorted(k for k, v in old.items() if new.get(k) != v)


def cache_bytes(path, seconds=20.0):
    """(bytes under path, bytes of those files no other name holds): uv hard-links what an environment uses out
    of its cache, so the cache costs the disk only what is in no environment. The second is None where the look
    took longer than `seconds` (a file's link count costs a call each on Windows). Where uv clones instead of linking
    (a file system with copy-on-write, a different link mode set by the user) a clone looks like a file with no other
    name, and that second number is an upper bound."""
    total, alone, todo, t0, late = 0, 0, [path], time.time(), False
    while todo:
        try:
            it = os.scandir(todo.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        todo.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        total += st.st_size
                        if late or time.time() - t0 > seconds:
                            late = True
                            continue
                        links = st.st_nlink or os.lstat(e.path).st_nlink     # DirEntry has no link count on Windows
                        if links <= 1:
                            alone += st.st_size
                except OSError:
                    continue
    return total, (None if late else alone)


# the part a package belongs to in the report: the program or tier it gives (the others are named as they are)
PARTS = {"tesserocr": "tesseract", "playwright": "browser", "readability-lxml": "readability"}


def _system_fix(part):
    """The machine's own install, for what our environment cannot carry here."""
    what = {"tesseract": "tesseract", "browser": "chromium"}.get(part)
    return ownenv.system_install(what) if what else ""


def no_build(out):
    """uv's own word that a package has no wheel for this OS and CPU: "has no wheels with a matching platform
    tag (e.g. `musllinux_1_2_x86_64`)", or "Wheels are required for X because building from source is
    disabled" where only a source release exists."""
    return bool(re.search(r"no wheels? with a matching platform tag|wheels are required for|no matching distribution",
                          out or "", re.I))


def first_error(out):
    """What went wrong, from an installer's whole output: its first `error` line and the cause under it."""
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if re.match(r"(?i)(error|×)", ln):
            return " ".join(lines[i:i + 2])
    return lines[-1] if lines else ""


def no_build_fix(part):
    """What a user can do where a package has no build for their machine: the machine's own program for the
    engines that are programs (the skill uses a tesseract on PATH), else the honest line - what is not here,
    and what still reads."""
    if part == "tesseract":
        return _system_fix(part)
    if part == "pymupdf":
        return "%s (PDF text then comes from pdftotext)" % ownenv.system_install("poppler")
    if part == "pymupdf4llm":
        return ("none here: the tables of a PDF stay one cell a line, its text reads; Linux (glibc), macOS and "
                "Windows on x64 have the layout model")
    if part == "browser":
        return ("none here: no headless browser, so JavaScript pages and hash routes stay unread; Linux (glibc), "
                "macOS and Windows have one")
    return "none here: the skill reads without it"


def package_problem(name, full):
    """(part, why, fix) for a package that did not install, from the installer's whole output: a package that
    has no build for this OS and CPU says so (and what to do instead); any other failure says what it was."""
    part = PARTS.get(name, name)
    if no_build(full):
        return part, "%s has no build for %s" % (name, ownenv.platform_name()), no_build_fix(part)
    return part, "%s did not install: %s" % (name, first_error(full)[:200]), _system_fix(part)


def reason(e, room=400):
    """An error's text for the check, whole and on one line: its end is usually the part that says why (a cut at 60
    characters left "DLL load failed while importing _wrapper: The filename or ex"). One longer than `room` keeps its
    start and its end; "; " inside it is ", " - it is what the check puts between engines (engines_covered)."""
    text = " ".join(str(e).split()).replace("; ", ", ") or type(e).__name__
    if len(text) > room:
        text = text[:room // 4] + " ... " + text[-(room - room // 4 - 5):]
    return text


def engines_covered(why, problems):
    """Whether every package the check found broken ("dist (reason); dist (reason)") has its problem already:
    each is said once, when it did not install, not again as "engines"."""
    names = [x.split(" (")[0].strip() for x in str(why or "").split("; ") if x.strip()]
    parts = set(p.get("part") for p in problems)
    return bool(names) and all(PARTS.get(n, n) in parts for n in names)


def pick_wheel(files):
    """The wheel of a py3-none package (uv's) for this machine, from PyPI's file list."""
    m = machine()
    names = [(f.get("filename") or "", f) for f in files]
    if os.name == "nt":
        want = {"x64": "win_amd64", "arm64": "win_arm64", "x86": "win32"}.get(m)
        return next((f for n, f in names if want and n.endswith(want + ".whl")), None)
    if sys.platform == "darwin":
        want = {"x64": "x86_64", "arm64": "arm64"}.get(m)
        return next((f for n, f in names if want and "macosx" in n and n.endswith(want + ".whl")), None)
    arch = {"x64": "x86_64", "arm64": "aarch64", "x86": "i686"}.get(m, m)
    tag = "musllinux" if musl() else "manylinux"
    return next((f for n, f in names if tag in n and ("_" + arch) in n), None)


# ---------------------------------------------------------------- the check (the environment's Python)
def check(d, out_path, info_path=""):
    """Every engine answers: imported, run on a small sample. Writes {part: {ok, ...}}."""
    import importlib
    try:
        from importlib import metadata as md
    except ImportError:
        md = None
    import threading
    info = _read_json(info_path) if info_path else load(d)
    res = {}
    # the engines that run something answer side by side while the imports are checked here
    side = [threading.Thread(target=lambda k=k, f=f: res.__setitem__(k, f(d, info)), daemon=True)
            for k, f in (("defuddle", _check_defuddle), ("browser", _check_browser), ("tesseract", _check_ocr))]
    for t in side:
        t.start()
    mods = (("curl_cffi", "curl_cffi"), ("trafilatura", "trafilatura"), ("readability-lxml", "readability"),
            ("html2text", "html2text"), ("pymupdf", "pymupdf"), ("pymupdf4llm", "pymupdf4llm"),
            ("python-docx", "docx"), ("openpyxl", "openpyxl"), ("python-pptx", "pptx"), ("pillow", "PIL"),
            ("psutil", "psutil"), ("youtube-transcript-api", "youtube_transcript_api"), ("yt-dlp", "yt_dlp"),
            ("playwright", "playwright"), ("tesserocr", "tesserocr"))
    libs, broken = {}, []
    for dist, mod in mods:
        try:
            importlib.import_module(mod)
            libs[dist] = md.version(dist) if md else "?"
        except Exception as e:                                 # noqa: BLE001
            broken.append("%s (%s)" % (dist, reason(e)))
    res["engines"] = {"ok": not broken, "versions": libs, "why": "; ".join(broken)}
    for t in side:
        t.join(240)
    for k in ("defuddle", "browser", "tesseract"):
        res.setdefault(k, {"ok": False, "why": "its check did not end in 240 s"})
    _write_json(out_path, res)
    return 0 if all(v.get("ok") for v in res.values()) else 1


def _check_defuddle(d, info):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import ddworker
        node = at(d, info.get("node_bin"))
        npm = at(d, info.get("npm") or "npm")
        cli = os.path.join(npm, "defuddle.cmd") if os.name == "nt" else os.path.join(npm, "bin", "defuddle")
        if info.get("npm_bin"):                                    # `npm ci` of the skill's lock: node_modules/.bin
            cli = os.path.join(at(d, info["npm_bin"]), "defuddle.cmd" if os.name == "nt" else "defuddle")
        dist, node = ddworker.locate(cli, node)
        if not dist:
            return {"ok": False, "why": "defuddle's files are not where npm puts them"}
        w = ddworker.Worker(node, dist)
        try:
            html = ("<html><head><title>read-page check</title></head><body><article><h1>Setup check</h1>"
                    + "<p>read-page asks defuddle for the text of this small page, sentence after sentence. </p>" * 6
                    + "</article></body></html>")
            md_text, why = w.submit(html).result(60)
        finally:
            w.close()
        return {"ok": bool(md_text and "defuddle for the text" in md_text), "why": why or ""}
    except Exception as e:                                     # noqa: BLE001
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:120])}


def _check_browser(d, info):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(timeout=60000)
            try:
                version = b.version
                page = b.new_page()
                page.set_content("<p id=x>read-page check</p>")
                txt = page.inner_text("#x")
            finally:
                b.close()
        return {"ok": txt == "read-page check", "version": version}
    except Exception as e:                                     # noqa: BLE001
        why = str(e)
        fix = ""
        if sys.platform.startswith("linux") and ("dependencies" in why or "shared librar" in why):
            fix = _browser_libs_fix()
            why = "the browser needs system libraries this machine lacks"
        return {"ok": False, "why": why.strip().splitlines()[0][:200] if why.strip() else type(e).__name__,
                "fix": fix}


def browser_libs_fix(out):
    """`sudo apt-get install <the libraries>` from `playwright install-deps --dry-run`'s answer (it lists
    "Missing system dependencies (N):" and the packages, two spaces in), or ''. The names are checked: a
    line is shown to the user as a command, and what is not a package name is not put in it."""
    names, inside = [], False
    for ln in str(out).splitlines():
        if ln.startswith("Missing system dependencies"):
            inside = True
        elif inside and ln.startswith("  ") and ln.strip():
            names.append(ln.strip())
        elif inside:
            break
    if not names or not all(re.fullmatch(r"[a-z0-9][a-z0-9+.:-]*", n) for n in names):
        return ""
    return ownenv.sudo() + "apt-get install " + " ".join(names)


def _browser_libs_fix():
    """What names the missing libraries: the environment's Python asks Playwright to simulate its own
    install - no root, nothing installed; root is the user's, for the machine's own package manager,
    never for a Python in a folder this user can write."""
    try:
        p = subprocess.run([sys.executable, "-m", "playwright", "install-deps", "--dry-run", BROWSER],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        fix = browser_libs_fix(p.stdout.decode("utf-8", "replace"))
    except (OSError, subprocess.SubprocessError):
        fix = ""
    return fix or _system_fix("browser")


def _check_ocr(d, info):
    if not ocr_here():
        return {"ok": False, "why": "tesserocr has no build for this machine", "fix": _system_fix("tesseract")}
    try:
        import tesserocr
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("L", (520, 90), 255)
        try:
            font = ImageFont.load_default(size=40)
        except TypeError:
            font = ImageFont.load_default()
        ImageDraw.Draw(img).text((20, 20), "Setup check 2026", fill=0, font=font)
        td = at(d, info.get("tessdata") or "tessdata")
        # tesserocr opens a path in the system's narrow code page: under a profile named in another
        # alphabet it goes by its 8.3 short name, where there is none by its own name from its parent
        # (the working directory is moved there for the start), and where even that cannot be, OCR cannot start
        langs = sorted(n[:-12] for n in os.listdir(td) if n.endswith(".traineddata"))
        broken = []                       # every pack must start: one cut short lists fine and fails at its first page
        with ownenv.tess_dir(td) as api_dir:
            if not api_dir:
                return {"ok": False, "why": ownenv.NONASCII_WHY % td, "fix": ownenv.NONASCII_FIX}
            api = tesserocr.PyTessBaseAPI(path=api_dir, lang="+".join(x for x in langs if x in ("eng", "rus"))
                                          or "eng")
            for lang in langs:
                try:                                           # osd tells a scan's script (OSD_ONLY, the legacy engine)
                    with tesserocr.PyTessBaseAPI(path=api_dir, lang=lang, psm=0 if lang == "osd" else 3):
                        pass
                except Exception:                              # noqa: BLE001
                    broken.append(lang)
        with api:
            api.SetImage(img)
            txt = api.GetUTF8Text()
        why = "read %r" % txt.strip()[:60] if "2026" not in txt else ""
        if broken:
            why = "a language pack does not start: %s" % ", ".join(broken)
        return {"ok": "2026" in txt and not broken, "version": tesserocr.tesseract_version().split()[1],
                "langs": langs, "why": why,
                "fix": ("delete %s, then run readpage.py --setup" % ", ".join(
                    os.path.join(td, x + ".traineddata") for x in broken)) if broken else ""}
    except Exception as e:                                     # noqa: BLE001
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:120])}


# ---------------------------------------------------------------- entry points of this file
def _main(argv):
    if argv[:1] == ["--launch"] and len(argv) >= 4:
        d, run, ver = argv[1], argv[2], argv[3]
        how = _detached([sys.executable, "-E", "-B", "-X", "utf8", os.path.abspath(__file__), "--worker", d, run, ver], d,
                        os.path.join(d, "setup-detail.log"))
        return LAUNCH_ATTACHED if how == "attached" else 0
    if argv[:1] == ["--worker"] and len(argv) >= 4:
        d, run, ver = argv[1], argv[2], argv[3]
        fh = None
        for _ in range(10):                    # a follower's own look at the lock lasts a moment
            fh = _try_lock(os.path.join(d, "setup.lock"))
            if fh is not None:
                break
            time.sleep(0.1)
        if fh is None:
            return 0                           # another one is at work; the command follows it
        work = None
        try:
            work = Work(d, run, ver)
            work.go()
        finally:
            if work is not None and getattr(work, "ytlock", None):
                _unlock(work.ytlock)
            _unlock(fh)
        return 0
    if argv[:1] == ["--ytdlp"] and len(argv) >= 2:
        return _ytdlp_worker(argv[1])
    if argv[:1] == ["--check"] and len(argv) >= 3:
        return check(argv[1], argv[2], argv[3] if len(argv) > 3 else "")
    print("ownenv.py is run by readpage.py --setup")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
