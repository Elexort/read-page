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
DEFUDDLE_VERSION = "0.19.4"
# defuddle names its own packages by range (linkedom ^0.18.12, turndown ^7.2.0, temml, commander:
# 26 with theirs), and npm takes the newest of the day of the install. So the day is pinned too:
# the tree npm resolves as of it is the one the suites ran with. It moves with the version above.
# A full timestamp, UTC: npm reads a bare date as midnight UTC, and that instant binds defuddle's own
# version too (a DEFUDDLE_VERSION published after it is not found). The pinned version must exist by it.
DEFUDDLE_BEFORE = "2026-11-19T00:00:00Z"
# no markitdown: ~200 MB (magika -> onnxruntime, sympy, numpy; pandas) for
# what pandoc, the office readers and youtube-transcript-api do as well - the A/B is in
# references/documents.md
TOP = ["curl_cffi", "trafilatura", "readability-lxml", "lxml", "lxml_html_clean", "html2text",
       "pymupdf", "pymupdf4llm", "python-docx", "openpyxl", "python-pptx", "pillow", "psutil",
       "youtube-transcript-api", "playwright", "tesserocr", "pypandoc_binary"]
# yt-dlp is the one engine that is not pinned: its work is to follow the sites,
# and a pinned one stops reading YouTube within weeks. --setup takes its newest release that has
# been out YTDLP_AGE_DAYS (a hijacked upload is usually caught sooner), with the challenge solver
# its own "default" extra names; a video read looks for a newer one in the background every
# YTDLP_EVERY_DAYS (ownenv.refresh_ytdlp). Packages it shares with the lock stay at the lock's.
YTDLP = "yt-dlp[default]"
YTDLP_AGE_DAYS = 3
# What floats with it: its tree beyond the lock's 55 packages. Only these are held to the three days;
# the rest of its tree is the lock's (certifi, requests, urllib3, idna, charset-normalizer), and a pin of
# the lock younger than three days must not make uv go looking for a yt-dlp old enough not to need it.
YTDLP_FLOATS = ("yt-dlp", "yt-dlp-ejs", "brotli", "mutagen", "pycryptodomex", "websockets")
# tessdata_fast 4.1.0 (Apache-2.0): as good as tessdata_best on 60 readings of English, Russian
# and mixed text (clean CER 0.19 against 0.48 %, poor scans 39.6 % both), three times faster
# (0.21 against 0.61 s a picture) and a quarter of the size (8 against 31 MB)
TESSDATA_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/%s.traineddata"
TESSDATA = {"eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
            "rus": "e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225"}
# What the two downloads that are not PyPI's packages are checked against: their
# SHA256, pinned here for every platform they come in, so a mirror, a MITM or whoever serves the file
# cannot serve other bytes under a version - before, the hash came from the same host as the file (PyPI's
# JSON; nodejs.org's SHASUMS256.txt). A file that is not in the table is refused. They move with
# UV_VERSION and NODE_VERSION, from the same places, after the suites ran green with the new ones.
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
# The 55 packages are pinned by content in setup-lock.txt (--generate-hashes). Not checked by content:
# yt-dlp and what floats with it (no hash can name a release that is newer than the repository), and
# Playwright's browser, which Playwright downloads over TLS with a Content-Length check and no hash.
BROWSER = "chromium-headless-shell"
LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup-lock.txt")
ENV_LOCK = "setup-lock.txt"          # inside an environment's folder: the lock it was built from
FOLLOW_SECONDS = 100                # --setup shows the work this long, then leaves it in the background
# what an installer says (uv, npm, Playwright, pip) when it cannot verify who answers
CERT_FAILURE = re.compile(r"(?i)certificate verify failed|invalid peer certificate|unknownissuer|unknown issuer|"
                          r"unable to verify the first certificate|self[- ]signed certificate|"
                          r"unable_to_get_issuer_cert|unable_to_verify_leaf_signature|cert_untrusted")


# ---------------------------------------------------------------- --setup: the command
def setup(script, skill_version):
    """Start the work in the background (or join one already running), show it for up to
    FOLLOW_SECONDS - till the end in a terminal - and print the report when it is done."""
    d = home()
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write-check.%d" % os.getpid())
        with open(probe, "w", encoding="utf-8"):
            pass
        os.unlink(probe)
    except OSError as e:
        print("read-page --setup: cannot write to %s: %s" % (d, e))
        return 1
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
    seen = 0
    while True:
        st = _read_json(state)
        if st.get("run") != target and float(st.get("started") or 0) >= t0 - 1:
            target = st.get("run")             # another --setup's work started first: that one
        mine = st.get("run") == target
        if mine:
            seen = _show_log(d, seen)          # the work's log is its own run's: shown from the top
            if st.get("done"):
                break
            if not _locked(lock):
                time.sleep(0.5)                # the state may be one write behind the lock
                st = _read_json(state)
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
        p = subprocess.run([sys.executable, "-E", "-B", me, "--launch", d, run, skill_version],
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


# ---------------------------------------------------------------- small tools
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    for _ in range(40):                       # a reader on Windows holds it for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, path)


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


def net_env():
    """The environment for the installers: the machine's proxy (Windows keeps it in the registry,
    which uv, npm and Playwright do not read) named the way they all do."""
    env = dict(os.environ)
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
                "with /usr/bin/python3")
    return ("this Python does not trust the certificate pypi.org presents: install the system's root certificates "
            "(sudo apt install ca-certificates), or - behind a proxy that inspects TLS - name a file with its "
            "root in SSL_CERT_FILE")


def fetch_json(url, timeout=30):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "read-page-setup", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _inside(root, name):
    target = os.path.realpath(os.path.join(root, name))
    base = os.path.realpath(root)
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
            os.symlink(m.linkname, place)
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
        self.env = net_env()
        self.env.update(UV_CACHE_DIR=os.path.join(d, "cache", "uv"),
                        UV_PYTHON_INSTALL_DIR=os.path.join(d, "python"),
                        UV_PYTHON_INSTALL_BIN="0", UV_PYTHON_INSTALL_REGISTRY="0",
                        UV_PYTHON_DOWNLOADS="manual",   # a Python only through our own install step
                        PLAYWRIGHT_BROWSERS_PATH=os.path.join(d, "browsers"),
                        npm_config_cache=os.path.join(d, "cache", "npm"),
                        npm_config_update_notifier="false", npm_config_fund="false",
                        npm_config_audit="false")
        self.state(done=False)

    # progress
    def say(self, line):
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
            _write_json(os.path.join(self.d, "setup.state"), st)

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
            self.parts[name] = {"ok": bool(ok), "note": note, "seconds": round(took, 1)}
            self.say("  %2d/%d %-9s %s%s" % (self.STEPS.index(name) + 1, len(self.STEPS), name, note,
                                            (" (%.0f s)" % took) if took >= 2 else ""))
        self.state(done=False)
        return bool(ok)

    def lack(self, part, why, fix=""):
        with self.lock:
            self.problems.append({"part": part, "why": why, "fix": fix})

    def sh(self, cmd, timeout=900, env=None, cwd=None):
        """Run an installer; its output goes to setup-detail.log. (returncode, the last lines)."""
        self.log("$ " + " ".join(str(c) for c in cmd))
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
        tail = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
        return rc, " | ".join(tail[-3:])[-400:]

    # the steps
    def network(self):
        free = shutil.disk_usage(self.d).free
        if free < 2 * 1024 ** 3:
            self.lack("disk", "%s free where it goes (%s); it needs about 1.5 GB" % (human(free), self.d))
        try:
            fetch_json("https://pypi.org/pypi/uv/%s/json" % UV_VERSION, timeout=15)
            return True, "pypi.org answers; %s free" % human(free)
        except Exception as e:                                 # noqa: BLE001
            if cert_error(e):
                # the network is there; this Python cannot check who answers (not "no internet")
                self.cert_why = cert_advice()
                return False, "pypi.org answers, but its certificate cannot be verified: " + self.cert_why
            if self.env.get("UV_DEFAULT_INDEX") or self.env.get("UV_INDEX_URL"):
                return True, "pypi.org does not answer (%s); using the index set here" % str(e)[:80]
            return False, "no answer from pypi.org: %s" % str(e)[:120]

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
            rc, out = self.sh([sys.executable, "-m", "pip", "download", "--only-binary", ":all:", "--no-deps",
                               "-d", dl, "uv==%s" % UV_VERSION], timeout=600)
            for n in os.listdir(dl):
                if n.startswith("uv-%s-" % UV_VERSION) and n.endswith(".whl"):
                    path = os.path.join(dl, n)
                    if UV_WHEEL_SHA256.get(n) != sha256(path):
                        os.unlink(path)
                        raise ValueError("the uv wheel pip fetched (%s) is not one this skill pins" % n)
                    return path
            raise ValueError("neither pypi.org nor pip gave uv: %s" % out[-120:])

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
        env = at(self.d, rel)
        py = os.path.join(env, "Scripts", "python.exe") if os.name == "nt" else os.path.join(env, "bin", "python")
        if not _python_ok(py):
            shutil.rmtree(env, ignore_errors=True)
            rc, out = self.sh([self.uv_exe, "venv", env, "--python", self.base_python, "-q"])
            if rc != 0:
                return False, "the environment was not created: " + out
        self.env_py = py
        try:                                   # the lock this environment is built from, kept in it (the updater's constraints)
            shutil.copy2(LOCK_FILE, os.path.join(env, ENV_LOCK))
        except OSError as e:
            self.log("lock copy: %s" % e)
        rc, out = self.sh([self.uv_exe, "pip", "install", "--python", py, "-r", LOCK_FILE, "--only-binary", ":all:"])
        failed = []
        if rc != 0:
            self.log("the whole set did not install; one package at a time")
            for top in TOP:
                rc1, out1 = self.sh([self.uv_exe, "pip", "install", "--python", py, top, "-c", LOCK_FILE,
                                     "--only-binary", ":all:"])
                if rc1 != 0:
                    failed.append((top.split("[")[0], out1))
        self.env_rel, self.env_py = rel, py
        self.info.update(env=rel, python=os.path.relpath(py, self.d).replace(os.sep, "/"))
        pandoc = self._pandoc(env)
        if pandoc:
            self.info["pandoc"] = os.path.relpath(pandoc, self.d).replace(os.sep, "/")
        for name, why in failed:
            part = {"tesserocr": "tesseract", "pypandoc_binary": "pandoc", "playwright": "browser",
                    "readability-lxml": "readability"}.get(name, name)
            nowheel = "no wheel" in why.lower() or "not supported" in why.lower() or "no matching" in why.lower()
            self.lack(part, "%s %s" % (name, "has no build for this machine" if nowheel else
                                       "did not install: " + why[-160:]), _system_fix(part))
        failed = [name for name, _why in failed]
        n = lock_packages(lock)
        return not failed or len(failed) < len(TOP), (
            "%d packages, python %s" % (n, pyver) + ("; not here: %s" % ", ".join(failed) if failed else ""))

    def _py_version(self, py):
        rc, out = self.sh([py, "-c", "import platform; print(platform.python_version())"], timeout=60)
        return out.split(" | ")[-1].strip() if rc == 0 else "3"

    def _pandoc(self, env):
        """pypandoc_binary's pandoc: <site-packages>/pypandoc/files/pandoc[.exe]."""
        if os.name == "nt":
            sites = [os.path.join(env, "Lib", "site-packages")]
        else:
            lib = os.path.join(env, "lib")
            sites = [os.path.join(lib, n, "site-packages") for n in (os.listdir(lib) if os.path.isdir(lib) else [])
                     if n.startswith("python")]
        for site in sites:
            for name in ("pandoc.exe", "pandoc"):
                p = os.path.join(site, "pypandoc", "files", name)
                if os.path.isfile(p):
                    return p
        return ""

    def ytdlp(self):
        ok, note = ytdlp_update(self.d, self.uv_exe, self.env_py, self.env, self.sh,
                                lock=os.path.join(at(self.d, self.env_rel), ENV_LOCK))
        if not ok:
            self.lack("yt-dlp", note, "readpage.py --setup")
        return ok, note

    def node(self):
        cur = at(self.d, self.prev.get("node_bin"))
        if cur and os.path.isfile(cur):
            rc, out = self.sh([cur, "--version"], timeout=60)
            if rc == 0 and out.strip().lstrip("v") in (NODE_VERSION, NODE_WHEEL):
                self.node_bin = cur
                self.info["node_bin"] = self.prev["node_bin"]
                return True, "node %s" % out.strip()
        try:
            self.node_bin = self._node_official()
            src = "nodejs.org, SHA256 pinned"
        except Exception as e:                                 # noqa: BLE001
            self.log("nodejs.org: %s" % e)
            try:
                self.node_bin = self._node_wheel()
                src = "nodejs-wheel-binaries from PyPI: nodejs.org did not answer (%s)" % str(e)[:80]
            except Exception as e2:                            # noqa: BLE001
                self.lack("defuddle", "no Node: nodejs.org (%s) and PyPI (%s) failed" % (str(e)[:80], str(e2)[:80]),
                          "install Node.js (nodejs.org), then readpage.py --setup")
                return False, "no Node: %s" % str(e2)[:120]
        self.info["node_bin"] = os.path.relpath(self.node_bin, self.d).replace(os.sep, "/")
        rc, out = self.sh([self.node_bin, "--version"], timeout=60)
        return rc == 0, "node %s (%s)" % (out.strip(), src)

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
        base = (self.env.get("NODEJS_ORG_MIRROR") or "https://nodejs.org/dist").rstrip("/")
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
        dest = os.path.join(self.d, "node", "wheel-" + NODE_WHEEL)
        shutil.rmtree(dest, ignore_errors=True)
        rc, out = self.sh([self.uv_exe, "pip", "install", "--target", dest, "--only-binary", ":all:",
                           "--python", getattr(self, "env_py", "") or sys.executable,
                           "nodejs-wheel-binaries==" + NODE_WHEEL])
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
        pkg = os.path.join(prefix, "node_modules" if os.name == "nt" else "lib/node_modules", "defuddle", "package.json")
        have = _read_json(pkg).get("version")
        self.info["npm"] = "npm"
        if have == DEFUDDLE_VERSION:
            return True, "defuddle %s" % have
        root = os.path.dirname(os.path.dirname(node)) if os.name != "nt" and node.endswith("bin" + os.sep + "node") \
            else os.path.dirname(node)
        cli = next((c for c in (os.path.join(root, "node_modules", "npm", "bin", "npm-cli.js"),
                                os.path.join(root, "lib", "node_modules", "npm", "bin", "npm-cli.js"))
                    if os.path.isfile(c)), "")
        if not cli:
            return False, "no npm beside node"
        env = dict(self.env, PATH=os.path.dirname(node) + os.pathsep + self.env.get("PATH", ""))
        rc, out = self.sh(defuddle_command(node, cli, prefix), env=env)
        have = _read_json(pkg).get("version")
        if rc != 0 or have != DEFUDDLE_VERSION:
            self.lack("defuddle", "npm did not install it: " + out[-120:])
            return False, "npm failed: " + out[-120:]
        return True, "defuddle %s (npm)" % have

    def browser(self):
        py = getattr(self, "env_py", "")
        if not py:
            return False, "no environment, so no browser"
        self.info["browsers"] = "browsers"
        rc, out = self.sh([py, "-E", "-m", "playwright", "install", BROWSER], timeout=1200)
        if rc != 0:
            self.lack("browser", "Playwright's browser did not download: " + out[-120:])
            return False, "not downloaded: " + out[-120:]
        found = sorted(n for n in os.listdir(os.path.join(self.d, "browsers")) if n.startswith("chromium_headless_shell-"))
        return True, "%s %s" % (BROWSER, found[-1].split("-")[-1] if found else "?")

    def ocr_data(self):
        td = os.path.join(self.d, "tessdata")
        os.makedirs(td, exist_ok=True)
        self.info["tessdata"] = "tessdata"
        langs = dict(TESSDATA)
        got, bad = [], []
        for x in os.environ.get("READ_PAGE_OCR_LANGS", "").split("+"):     # a language the user named
            x = x.strip()
            if x and re.fullmatch(r"[a-z]+(?:_[a-z]+)*", x):               # chi_sim, deu_latf, srp_latn too
                langs.setdefault(x, None)
            elif x:
                bad.append(x)
                self.log("tessdata %s: not the name of a language pack (lower case, with _ for a script: chi_sim)" % x)
        for lang, sha in langs.items():
            dest = os.path.join(td, lang + ".traineddata")
            if os.path.isfile(dest) and (not sha or sha256(dest) == sha):
                got.append(lang)
                continue
            try:
                fetch(TESSDATA_URL % lang, dest, sha, timeout=300)
                got.append(lang)
            except Exception as e:                             # noqa: BLE001
                bad.append(lang)
                self.log("tessdata %s: %s" % (lang, e))
        # a pack with no pinned hash (every language beyond eng and rus) is kept only when tesseract
        # starts with it: one cut short, or not a pack at all, lists fine and fails at the first page
        for lang, why in self._packs_start(td, [x for x in got if langs[x] is None]).items():
            try:
                os.unlink(os.path.join(td, lang + ".traineddata"))
            except OSError:
                pass
            got.remove(lang)
            bad.append(lang)
            self.log("tessdata %s: tesseract does not start with it (%s); removed" % (lang, why))
        if bad:
            self.lack("ocr-langs", "language data not downloaded: %s" % ", ".join(bad))
        return bool(got), "%s (tessdata_fast 4.1.0)" % "+".join(got) + ("; failed: %s" % ", ".join(bad) if bad else "")

    def _packs_start(self, td, langs):
        """{lang: why} for the packs tesseract does not start with: one run of the environment's Python
        (its tesserocr); {} where there is none to ask."""
        py = getattr(self, "env_py", "")
        if not (py and langs):
            return {}
        code = ("import sys, tesserocr\nfor lang in sys.argv[2:]:\n try:\n"
                "  tesserocr.PyTessBaseAPI(path=sys.argv[1], lang=lang).End()\n except Exception as e:\n"
                "  print('BAD', lang, ' '.join(str(e).split())[:100])\n")
        self.log("$ tesserocr starts with: %s" % " ".join(langs))
        try:
            p = subprocess.run([py, "-E", "-X", "utf8", "-c", code, ownenv.ascii_path(td) or td] + list(langs),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=120, env=self.env)
            out = p.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError) as e:
            self.log("the packs could not be tried: %s" % e)
            return {}
        return {ln.split()[1]: ln.split(None, 2)[2] if len(ln.split(None, 2)) > 2 else ""
                for ln in out.splitlines() if ln.startswith("BAD ") and len(ln.split()) > 1}

    def check(self):
        py = getattr(self, "env_py", "")
        if not py:
            return False, "nothing to check"
        env = dict(self.env)
        env.pop("READ_PAGE_ENV_CHILD", None)
        pending = os.path.join(self.d, "setup-new.json")      # setup.json comes after the check
        _write_json(pending, self.info)
        rc, _out = self.sh([py, "-E", "-B", "-X", "utf8", os.path.abspath(__file__), "--check", self.d,
                            os.path.join(self.d, "setup-check.json"), pending], timeout=300, env=env)
        try:
            os.unlink(pending)
        except OSError:
            pass
        res = _read_json(os.path.join(self.d, "setup-check.json"))
        self.info["checked"] = res
        bad = sorted(k for k, v in res.items() if isinstance(v, dict) and not v.get("ok"))
        for k in bad:
            if not any(p["part"] == k for p in self.problems):
                self.lack(k, res[k].get("why") or "it did not answer", res[k].get("fix") or "")
        good = sorted(k for k, v in res.items() if isinstance(v, dict) and v.get("ok"))
        return rc == 0 and not bad, ("%d of %d answer" % (len(good), len(good) + len(bad))
                                     + ("; not: %s" % ", ".join(bad) if bad else ""))

    def tidy(self):
        """Keep the environment in use and the one before it (a read may still run there); the
        rest goes, and so do Pythons and Nodes no environment of these uses."""
        keep_envs = {self.info.get("env"), self.prev.get("env")}
        envs = os.path.join(self.d, "envs")
        homes = set()
        for n in (os.listdir(envs) if os.path.isdir(envs) else []):
            p = os.path.join(envs, n)
            if "envs/" + n not in keep_envs and not _running(os.path.join(p, "Scripts", "python.exe")):
                shutil.rmtree(p, ignore_errors=True)      # (an MCP server still in it keeps it, on Windows)
                continue
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
        cur = self.info.get("node_bin") or ""
        for n in (os.listdir(nodes) if os.path.isdir(nodes) else []):
            if n not in cur.split("/"):
                shutil.rmtree(os.path.join(nodes, n), ignore_errors=True)
        shutil.rmtree(os.path.join(self.d, "cache", "dl"), ignore_errors=True)

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
            self.say("done in %d min %02d s; %s in %s. To remove it all, delete that folder."
                     % (took // 60, took % 60, human(size), self.d))
            for p in self.problems:
                self.say("not done: %s - %s%s" % (p["part"], p["why"], (" - " + p["fix"]) if p.get("fix") else ""))
        if getattr(self, "ytlock", None):
            _unlock(self.ytlock)
        self.state(done=True, ok=bool(ready) and not any(not v["ok"] for v in self.parts.values()))


def defuddle_command(node, cli, prefix):
    """npm's command for defuddle: its version by name, the packages it brings as of one day
    (DEFUDDLE_BEFORE) - the same tree on every machine, whenever it is set up. No install script
    of any package runs."""
    return [node, cli, "install", "-g", "--prefix", prefix, "--no-audit", "--no-fund", "--ignore-scripts",
            "--loglevel=error", "--before=" + DEFUDDLE_BEFORE, "defuddle@" + DEFUDDLE_VERSION]


def ytdlp_command(uv, py, now=None, floor="", lock=None):
    """uv's command for the newest yt-dlp that has been out YTDLP_AGE_DAYS - and never an older one than
    `floor`, the version installed now (with no floor, a pin of the lock younger than the cutoff made
    uv backtrack to yt-dlp 2022.3.8.2, which has no `default` extra and needs none of the packages: exit 0,
    "success", and every video read passing --js-runtimes to a yt-dlp that rejects it). The packages of
    the environment's own lock stay at its pins; the date holds only what floats (YTDLP_FLOATS)."""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((now or time.time()) - YTDLP_AGE_DAYS * 86400))
    cmd = [uv, "pip", "install", "--python", py, "--upgrade", YTDLP + (">=" + floor if floor else ""),
           "-c", lock or LOCK_FILE, "--only-binary", ":all:"]
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
            "--only-binary", ":all:"], timeout=600, env=env)
        version = _ytdlp_version(py)
        rc, out = 1, "it would have gone back from %s: kept" % before
    if rc == 0 and version:
        try:
            with open(os.path.join(d, "ytdlp.stamp"), "w", encoding="utf-8") as fh:
                fh.write(version + "\n")
            os.unlink(os.path.join(d, "ytdlp.failed"))
        except OSError:
            pass
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
    return _detached([sys.executable, "-E", "-B", os.path.abspath(__file__), "--ytdlp", d], d,
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
        env = net_env()
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


def _system_fix(part):
    """The machine's own install, for what our environment cannot carry here."""
    if part == "tesseract":
        return ("winget install --id UB-Mannheim.TesseractOCR" if os.name == "nt" else
                "brew install tesseract" if sys.platform == "darwin" else "sudo apt install tesseract-ocr")
    if part == "browser":
        return ("winget install --id Google.Chrome" if os.name == "nt" else
                "brew install --cask google-chrome" if sys.platform == "darwin" else "sudo apt install chromium")
    if part == "pandoc":
        return ("winget install --id JohnMacFarlane.Pandoc" if os.name == "nt" else
                "brew install pandoc" if sys.platform == "darwin" else "sudo apt install pandoc")
    return ""


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
            for k, f in (("defuddle", _check_defuddle), ("browser", _check_browser), ("tesseract", _check_ocr),
                         ("pandoc", _check_pandoc))]
    for t in side:
        t.start()
    mods = (("curl_cffi", "curl_cffi"), ("trafilatura", "trafilatura"), ("readability-lxml", "readability"),
            ("html2text", "html2text"), ("pymupdf", "pymupdf"), ("pymupdf4llm", "pymupdf4llm"),
            ("python-docx", "docx"), ("openpyxl", "openpyxl"), ("python-pptx", "pptx"), ("pillow", "PIL"),
            ("psutil", "psutil"), ("youtube-transcript-api", "youtube_transcript_api"), ("yt-dlp", "yt_dlp"),
            ("playwright", "playwright"),
            ("tesserocr", "tesserocr"), ("pypandoc_binary", "pypandoc"))
    libs, broken = {}, []
    for dist, mod in mods:
        try:
            importlib.import_module(mod)
            libs[dist] = md.version(dist) if md else "?"
        except Exception as e:                                 # noqa: BLE001
            broken.append("%s (%s)" % (dist, str(e)[:60]))
    res["engines"] = {"ok": not broken, "versions": libs, "why": "; ".join(broken)}
    for t in side:
        t.join(240)
    for k in ("defuddle", "browser", "tesseract", "pandoc"):
        res.setdefault(k, {"ok": False, "why": "its check did not end in 240 s"})
    _write_json(out_path, res)
    return 0 if all(v.get("ok") for v in res.values()) else 1


def _check_pandoc(d, info):
    pandoc = at(d, info.get("pandoc"))
    try:
        if not (pandoc and os.path.isfile(pandoc)):
            raise OSError("pypandoc_binary's pandoc is not in the environment")
        p = subprocess.run([pandoc, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        first = p.stdout.decode("utf-8", "replace").splitlines()[0] if p.stdout else ""
        return {"ok": p.returncode == 0 and first.startswith("pandoc"), "version": first}
    except (OSError, subprocess.SubprocessError, IndexError) as e:
        return {"ok": False, "why": str(e)[:120]}


def _check_defuddle(d, info):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import ddworker
        node = at(d, info.get("node_bin"))
        npm = at(d, info.get("npm") or "npm")
        cli = os.path.join(npm, "defuddle.cmd") if os.name == "nt" else os.path.join(npm, "bin", "defuddle")
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
    return "sudo apt-get install " + " ".join(names)


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
        # alphabet it goes by its 8.3 short name, and where there is none OCR cannot start
        api_dir = ownenv.ascii_path(td)
        if not api_dir:
            return {"ok": False, "why": ownenv.NONASCII_WHY % td, "fix": ownenv.NONASCII_FIX}
        langs = sorted(n[:-12] for n in os.listdir(td) if n.endswith(".traineddata"))
        with tesserocr.PyTessBaseAPI(path=api_dir, lang="+".join(x for x in langs if x in ("eng", "rus"))
                                     or "eng") as api:
            api.SetImage(img)
            txt = api.GetUTF8Text()
        broken = []                       # every pack must start: one cut short lists fine and fails at its first page
        for lang in langs:
            if lang == "osd":
                continue
            try:
                with tesserocr.PyTessBaseAPI(path=api_dir, lang=lang):
                    pass
            except Exception:                                  # noqa: BLE001
                broken.append(lang)
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
        how = _detached([sys.executable, "-E", "-B", os.path.abspath(__file__), "--worker", d, run, ver], d,
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
