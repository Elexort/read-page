"""Where the skill's own environment is, and how a run goes into it (readpage.py --setup builds
it: envsetup.py). A Python of a fixed version with the engines, Node with defuddle, Playwright's
browser and OCR's language data, in a folder of the user's (home()) - never in the skill's, which
some harnesses list file by file to the agent.

readpage.py and mcp_server.py call use() before anything else: when the environment is there,
the run goes on under its Python, with its tools first on PATH; without it the standard library
core and whatever the machine has read as before. Kept small and stdlib-only (Python 3.8+): every
run imports it before the environment, if any, takes over.
"""
import json
import os
import re
import sys
import threading

STATE_SCHEMA = 1


def _size_note():
    """What --setup downloads and keeps (no markitdown, no pandoc, and Node is Playwright's own: nothing of
    nodejs.org): measured by real installs on GitHub's runners (2026-11-21, the bytes the network adapter received and
    the folder's size without uv's cache, which is hard-linked into it): Windows x64 359 MB and 0.9 GB, Linux x64
    393 MB and 0.96 GB (arm64 370 MB, 0.92 GB), macOS arm64 348 MB and 0.82 GB."""
    if os.name == "nt":
        return "downloads about 360 MB, takes about 0.9 GB on disk, no admin rights"
    if sys.platform == "darwin":
        return "downloads about 350 MB, takes about 0.85 GB on disk, no admin rights"
    return "downloads about 390 MB, takes about 1.0 GB on disk, no admin rights"


SIZE_NOTE = _size_note()
_STATUS = {"home": "", "used": False, "why": ""}   # what use() did, for the setup report and --caps


# ---------------------------------------------------------------- where it is
def home():
    """READ_PAGE_HOME, else a folder of the user's that every agent on the machine sees: the OS's
    one for application data on macOS and Linux, `.read-page` in the home folder on Windows. Not
    AppData there: Windows gives a packaged app (MSIX - Claude's desktop app is one) a private copy
    of whatever its processes write under AppData, so an environment an agent builds there does
    not exist for a terminal or for the next agent, and its files are slow to reach (a stat 372 us
    against 49 in the home folder)."""
    v = (os.environ.get("READ_PAGE_HOME") or "").strip()
    if v:
        return os.path.abspath(os.path.expanduser(v))
    if os.name == "nt":
        return os.path.join(os.path.expanduser("~"), ".read-page")
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or ""
        if not os.path.isabs(base):
            base = os.path.expanduser("~/.local/share")
    return os.path.join(base, "read-page")


# tessdata_fast's pack for a language (ISO 639-1 -> tesseract's three letters): what --setup fetches besides English
# for the language of the machine it runs on. Chinese goes by script: chi_sim (zh-CN, zh-SG, Hans), chi_tra (zh-TW,
# zh-HK, zh-MO, Hant). English needs none.
_OCR_PACK = {"ja": "jpn", "ko": "kor", "ru": "rus", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por",
             "pl": "pol", "uk": "ukr", "tr": "tur", "ar": "ara", "he": "heb", "iw": "heb", "hi": "hin", "th": "tha",
             "vi": "vie", "nl": "nld", "sv": "swe", "da": "dan", "fi": "fin", "el": "ell", "cs": "ces", "hu": "hun",
             "ro": "ron", "bg": "bul", "id": "ind", "ms": "msa", "fa": "fas", "bn": "ben", "ta": "tam", "ca": "cat",
             "hr": "hrv", "sk": "slk", "sl": "slv", "lt": "lit", "lv": "lav", "et": "est", "sr": "srp", "nb": "nor",
             "no": "nor", "nn": "nor", "be": "bel", "kk": "kaz", "ka": "kat", "is": "isl"}


def ocr_pack_for(name):
    """The tessdata_fast pack for a locale name (`zh_CN`, `zh-TW`, `ja_JP.UTF-8`, `sr_Latn`, `ru`): '' for English
    and for a language without a pack."""
    base = str(name or "").replace("-", "_").split(".")[0].split("@")[0]
    lang, _, rest = base.partition("_")
    lang = lang.lower()
    if lang == "zh":
        return "chi_tra" if re.search(r"(?i)hant|(^|_)(tw|hk|mo)$", rest) else "chi_sim"
    if lang == "sr" and re.search(r"(?i)latn", rest):
        return "srp_latn"
    return _OCR_PACK.get(lang, "")


def system_language(env=None):
    """The language this machine is set to, as a locale name (`zh-CN`, `ru_RU.UTF-8`), '' when it cannot be told:
    Windows' user locale first (an `LANG` there is a Unix shell's, not the user's), else the environment's
    (`LC_ALL`, `LC_MESSAGES`, `LANG`, `LANGUAGE`), on a Mac then its own setting."""
    env = os.environ if env is None else env
    if os.name == "nt" and env is os.environ:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85) and buf.value:
                return buf.value
        except (AttributeError, OSError, ValueError):
            pass
    for k in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = (env.get(k) or "").strip()
        if v and v not in ("C", "POSIX") and not v.startswith("C."):
            return v
    v = (env.get("LANGUAGE") or "").split(":")[0].strip()
    if v:
        return v
    if sys.platform == "darwin" and env is os.environ:
        import subprocess
        try:
            p = subprocess.run(["defaults", "read", "-g", "AppleLocale"], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
            return p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    return ""


def ocr_default_packs(env=None):
    """The OCR packs --setup fetches whatever the user names: English, and the pack of the machine's own language
    (READ_PAGE_OCR_LANGS names more). It was English and Russian, one person's choice."""
    pack = ocr_pack_for(system_language(env))
    return ["eng"] + ([pack] if pack and pack != "eng" else [])


def ascii_path(p):
    """`p` as an API that takes narrow characters opens it. tesserocr hands tesseract the path in the
    system's ANSI code page, so on Windows tessdata under a profile named in another alphabet (a local
    account `Иван`) fails to open - and the OCR is silently dead. Such a path goes by its 8.3 short
    name, which is ASCII; "" when it has none (the volume makes no short names, or the path is not
    there). Any other path - ASCII, or on another OS - comes back as it is."""
    p = str(p or "")
    if os.name != "nt" or p.isascii():
        return p
    try:
        import ctypes
        get = ctypes.windll.kernel32.GetShortPathNameW
        get.restype = ctypes.c_uint32
        need = get(p, None, 0)
        if not need:
            return ""
        buf = ctypes.create_unicode_buffer(need + 1)
        got = get(p, buf, need + 1)
        short = buf.value if 0 < got <= need else ""
    except (AttributeError, OSError, ValueError):
        return ""
    return short if short.isascii() else ""


def tess_arg(td):
    """(the path tesserocr is given for the tessdata folder `td`, the working directory to give it from or None).
    `td` itself where it opens (ASCII, or off Windows) and its 8.3 short name where Windows has one. Where it has
    none - a volume that makes no short names: the D: of a CI runner, a dev drive - the folder's own name, which
    is ASCII, from its parent (the process's working directory is a wide-character path: only the narrow
    argument is the trouble). ("", None) when none of that opens it: the folder's own name is outside ASCII."""
    short = ascii_path(td)
    if short or not td:
        return short or td, None
    parent, name = os.path.split(os.path.abspath(td))
    if name.isascii() and os.path.isdir(td):
        return name, parent
    return "", None


_CWD = threading.RLock()                 # the working directory is the whole process's: one mover at a time


class tess_dir(object):
    """`with ownenv.tess_dir(td) as path:` - hand `path` to tesserocr (get_languages, PyTessBaseAPI) and let it
    start inside the block. When the path is relative (tess_arg) the working directory is the folder's parent
    for the block only: tesseract reads its data when it starts, and the picture is read after. tesserocr
    opens a narrow path in the system's ANSI code page, so a tessdata folder under a profile named in another
    alphabet (a local account `Ivan`, in Cyrillic) was dead for OCR without a word; a
    runner's own volume made the short name the 2026-11-21 CI relied on impossible."""

    def __init__(self, td):
        self.td, self.old = td, None

    def __enter__(self):
        path, cwd = tess_arg(self.td)
        if cwd:
            _CWD.acquire()
            try:
                self.old = os.getcwd()
                os.chdir(cwd)
            except OSError:
                self.old = None
                _CWD.release()
                return ""
        return path

    def __exit__(self, *exc):
        if self.old is not None:
            try:
                os.chdir(self.old)
            except OSError:
                pass
            self.old = None
            _CWD.release()
        return False


# what to say when OCR cannot start for a path (the one fix that works: --setup would meet the same wall)
NONASCII_WHY = "its language data is in %s, a folder whose name has characters outside ASCII that OCR cannot open"
NONASCII_FIX = ("set READ_PAGE_HOME to a folder with an ASCII-only path (C:\\read-page, say), then run "
                "readpage.py --setup there")


def ocr_fix(why):
    """The fix for an OCR that does not start, when its reason names one; '' otherwise."""
    return NONASCII_FIX if "outside ASCII" in str(why or "") else ""


def load(d=None):
    """setup.json: what --setup built and where; {} when there is none."""
    try:
        with open(os.path.join(d or home(), "setup.json"), encoding="utf-8") as fh:
            info = json.load(fh)
        return info if isinstance(info, dict) and info.get("schema") == STATE_SCHEMA else {}
    except (OSError, ValueError):
        return {}


def at(d, rel):
    """A path setup.json keeps relative to the folder."""
    return os.path.join(d, *str(rel).split("/")) if rel else ""


def _same(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, ValueError):
        return False


def edits(a, b):
    """Letters to change, add, drop or swap to turn a into b (optimal string alignment)."""
    d = [[i + j if not (i and j) else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def meant_setup(arg):
    """Whether this argument is --setup, or a flag readpage.py's typo_fixed (which runs only after the
    hop) will read as --setup: `--stup`, `--Setup`. --setup builds the environment from outside it - its
    worker, uv's pip fallback and the machine-Python fallback all use the Python they were started in."""
    a = str(arg)
    if not a.startswith("--"):
        return False
    body = a[2:].partition("=")[0].lower()
    return bool(body) and (body == "setup" or edits(body, "setup") <= (1 if len(body) <= 6 else 2))


def _skip():
    return "env" in set(x.strip() for x in os.environ.get("READ_PAGE_SKIP", "").split(","))


def _python_ok(py):
    """The environment's Python can start: its file is there, and so is the Python it was made
    from (a venv names it in pyvenv.cfg; --setup's own, inside the folder)."""
    if not py or not os.path.isfile(py):
        return False
    cfg = os.path.join(os.path.dirname(os.path.dirname(py)), "pyvenv.cfg")
    try:
        with open(cfg, encoding="utf-8") as fh:
            for line in fh:
                k, _, v = line.partition("=")
                if k.strip() == "home" and v.strip():
                    base = v.strip()
                    return any(os.path.isfile(os.path.join(base, n))
                               for n in ("python.exe", "python3", "python"))
    except OSError:
        return False
    return True


def status():
    """What use() found: the folder, whether this run is in the environment, and why not."""
    return dict(_STATUS)


def use(script, argv):
    """Go on under the environment's Python when there is one and this is not it (POSIX: exec;
    Windows: a child with the same arguments, our console and exit code, which ends with us).
    In it, its tools come first. Returns when this process is the one to read."""
    d = home()
    _STATUS.update(home=d, used=False, why="")
    if _skip():
        _STATUS["why"] = "READ_PAGE_SKIP=env"
        return
    info = load(d)
    if not info.get("python"):
        _STATUS["why"] = "not set up"
        return
    py = at(d, info["python"])
    if _same(sys.prefix, at(d, info.get("env"))):
        hs = os.environ.pop("READ_PAGE_HANDSHAKE", "")      # first of all: the first process learns that we started
        if hs:
            try:
                os.unlink(hs)
            except OSError:
                pass
        _tools(d, info)
        _STATUS["used"] = True
        return
    if not _python_ok(py):
        _STATUS["why"] = "its Python is missing: run --setup again"
        return
    if any(meant_setup(a) for a in argv):
        _STATUS["why"] = "--setup works from outside it"
        return
    if os.environ.get("READ_PAGE_ENV_CHILD"):
        _STATUS["why"] = "a child of it, yet another Python"       # never a loop
        return
    # -E: the caller's PYTHONPATH and PYTHONHOME stay out of our engines; -B keeps the one wish of
    # theirs -E would drop (PYTHONDONTWRITEBYTECODE: no .pyc anywhere)
    cmd = [py, "-E"] + (["-B"] if sys.dont_write_bytecode or os.environ.get("PYTHONDONTWRITEBYTECODE") else []) \
        + ["-X", "utf8", os.path.abspath(script)] + [str(a) for a in argv]
    os.environ["READ_PAGE_ENV_CHILD"] = "1"
    for f in (sys.stdout, sys.stderr):
        try:
            f.flush()
        except (AttributeError, OSError, ValueError):
            pass
    once = _started_once(d, info)
    if os.name != "nt" and once:
        try:
            os.execv(py, cmd)
        except OSError as e:
            os.environ.pop("READ_PAGE_ENV_CHILD", None)
            _STATUS["why"] = "its Python did not start: %s" % e
            return
    # A child, which can be asked how it went: on Windows always (it has no exec), on POSIX until one run
    # of this build has started and reached its first line (exec leaves nothing to fall back from). The
    # child removes a file we made before it does anything else; one that is still there when the child
    # has ended never got as far - an antivirus took a DLL, the standard library or the disk is damaged
    # (the read was then empty with the interpreter's own exit code, which SKILL.md calls a wrong call).
    marker = _handshake_file()
    rc = _child(cmd)
    if rc is None or (marker and os.path.exists(marker)):
        if marker:
            try:
                os.unlink(marker)
            except OSError:
                pass
        os.environ.pop("READ_PAGE_ENV_CHILD", None)
        os.environ.pop("READ_PAGE_HANDSHAKE", None)
        _STATUS["failed"] = True
        _STATUS["why"] = ("its Python did not start" if rc is None else
                          "its Python started and ended (exit code %s) before it reached the read - an antivirus "
                          "or a damaged install may keep it from running: this read runs in the machine's Python; "
                          "READ_PAGE_SKIP=env skips the environment, `readpage.py --setup` repairs it"
                          % (rc - 0x100000000 if rc > 0x7FFFFFFF else rc))
        return
    if os.name != "nt":
        _mark_started(d, info)
    os._exit(_exit_code(rc))                                  # an NTSTATUS code stays what it was


def _exit_code(rc):
    """A child's code as os._exit takes it: NTSTATUS as it was, a signal as the shell shows it."""
    if rc > 0x7FFFFFFF:
        return rc - 0x100000000
    return 128 - rc if rc < 0 else rc


def _handshake_file():
    """A file for the child to remove first thing (READ_PAGE_HANDSHAKE names it); '' where one cannot be
    made - then nobody asks, and the read goes on as it always did."""
    base = os.environ.get("TMPDIR") or os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    path = os.path.join(base, "read-page-start-%d" % os.getpid())
    try:
        with open(path, "w"):
            pass
    except OSError:
        return ""
    os.environ["READ_PAGE_HANDSHAKE"] = path
    return path


def _start_key(info):
    return "%s|%s" % (info.get("env"), info.get("built"))


def _started_once(d, info):
    """POSIX: a run of this very build (setup.json's) has started in the environment's Python and reached its
    first line, so exec is safe from now on. Windows has no exec: always the child."""
    if os.name == "nt":
        return False
    try:
        with open(os.path.join(d, "setup.started"), encoding="utf-8") as fh:
            return fh.read().strip() == _start_key(info)
    except OSError:
        return False


def _mark_started(d, info):
    try:
        with open(os.path.join(d, "setup.started"), "w", encoding="utf-8") as fh:
            fh.write(_start_key(info) + "\n")
    except OSError:
        pass


_JOB = []


def _child(cmd):
    """Windows has no exec (POSIX: not before one start has been seen): run the child on our console and
    wait. We go into a job that closes with us first, so that everything below is born inside it: a
    harness that kills only this process does not leave the read, or what the read started, running.
    (The child put in the job after it started was late for a venv's launcher: it had already put the
    real Python in a job of its own, and that one's children were in none that ended with us -
    KNOWN-ISSUES 128.) A job around us nests: ours goes inside it. Where we cannot go into a job at all,
    the child is put in one after it started, as it was."""
    import subprocess
    if os.name == "nt":
        mine = _kill_with_us()
    try:
        p = subprocess.Popen(cmd)
    except OSError:
        return None
    if os.name == "nt":
        if not mine:
            _kill_with_us(p)
    else:
        import signal                         # no exec for this first run: what ends us ends the child too
        for name in ("SIGTERM", "SIGHUP"):
            try:
                signal.signal(getattr(signal, name), lambda sig, _f, p=p: p.send_signal(sig))
            except (AttributeError, ValueError, OSError):
                pass
    while True:
        try:
            return p.wait()
        except KeyboardInterrupt:            # the console sent it to the child too; it ends itself
            continue


def _job_api():
    """kernel32 with the job calls typed, and the limit structures: (k32, Extended) - or raises."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.c_void_p]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    return k32, Extended


def _kill_with_us(p=None):
    """A job that closes with us (kill on close; breakaway allowed, for what must outlive a read) and
    the process in it: p, or this one. True when the process is in it."""
    try:
        k32, Extended = _job_api()
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x800    # kill on close; breakaway allowed
        import ctypes
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess() if p is None else int(p._handle)):
            k32.CloseHandle(job)             # e.g. a job above that cannot nest this one
            return False
        _JOB.append(job)                     # closed by Windows when we end: the job goes with it
        return True
    except Exception:                                          # noqa: BLE001
        return False


def job_ends_us():
    """Windows: whether the job this process is directly in ends everything started in it when it closes
    and lets nothing leave it (kill on close, no breakaway) - how a harness that runs each command in a
    job can keep a command from leaving work behind. Only the job it is directly in: a venv's python.exe
    runs its interpreter in a job of its own (kill on close, silent breakaway), nested in the harness's,
    and that is all such an interpreter sees of it - breakaway_job_ends_us asks a process that has left
    it."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k32, Extended = _job_api()
        inside = wintypes.BOOL(0)
        if not k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(inside)) or not inside.value:
            return False
        info = Extended()
        if not k32.QueryInformationJobObject(None, 9, ctypes.byref(info), ctypes.sizeof(info), None):
            return False
        flags = info.BasicLimitInformation.LimitFlags
        return bool(flags & 0x2000) and not flags & (0x800 | 0x1000)   # kill on close; no (silent) breakaway
    except Exception:                                          # noqa: BLE001
        return False


def _probe_argv():
    """The child breakaway_job_ends_us runs. -I ignores the caller's PYTHONDONTWRITEBYTECODE, so -B says it
    again: a .pyc of ownenv beside the scripts is what the skill keeps out of its folder."""
    py = getattr(sys, "_base_executable", None) or sys.executable
    code = ("import sys; sys.path.insert(0, %r); import ownenv; sys.stdout.write('1' if ownenv.job_ends_us() else '0')"
            % os.path.dirname(os.path.abspath(__file__)))
    return [py, "-B", "-I", "-S", "-c", code]


def breakaway_job_ends_us():
    """Windows: whether work started apart from this process (CREATE_BREAKAWAY_FROM_JOB) ends with the
    command that started it. A process that breaks away leaves every job that lets it - ours, a venv
    launcher's - and stops in the first that does not (the harness's), so a small child of this kind,
    asked what job it landed in (job_ends_us), tells what detached work will meet. It is run by the base
    Python, never a venv's python.exe: that would wrap it in a launcher job again, and the child would
    read that one. Where the breakaway is refused (the job we are in lets nothing leave), the work stays
    where we are, and what we read ourselves is what it will meet."""
    if os.name != "nt":
        return False
    import subprocess
    try:
        p = subprocess.run(_probe_argv(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=30,
                           creationflags=0x08000000 | 0x00000200 | 0x01000000)   # no window, own group, breakaway
        got = p.stdout.strip()
        if p.returncode == 0 and got in (b"0", b"1"):
            return got == b"1"
    except (OSError, subprocess.SubprocessError):
        pass
    return job_ends_us()


def _tools(d, info):
    """Inside the environment: its programs before the machine's, its browsers and OCR data."""
    env = at(d, info.get("env"))
    add = [os.path.join(env, "Scripts" if os.name == "nt" else "bin")]
    if info.get("node_bin"):                     # (an environment of before 2026-11-21 named a pandoc too)
        add.append(os.path.dirname(at(d, info["node_bin"])))
    if info.get("npm"):
        npm = at(d, info["npm"])
        add.append(npm if os.name == "nt" else os.path.join(npm, "bin"))
    have = os.environ.get("PATH", "").split(os.pathsep) if os.environ.get("PATH") else []
    seen = set(os.path.normcase(p) for p in have)
    new = [p for p in add if p and os.path.isdir(p) and os.path.normcase(p) not in seen]
    if new:
        os.environ["PATH"] = os.pathsep.join(new + have)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = at(d, info.get("browsers") or "browsers")
    td = at(d, info.get("tessdata") or "tessdata")
    if not os.environ.get("READ_PAGE_TESSDATA") and os.path.isdir(td):
        os.environ["READ_PAGE_TESSDATA"] = td
    if not os.environ.get("READ_PAGE_OCR_LANGS"):
        # the pack --setup fetched for this machine's language (or a language it was asked for) is read with, beside
        # English; Russian keeps its own rule (a Cyrillic page), as before
        more = [x for x in (info.get("ocr_langs") or []) if x not in ("eng", "rus", "osd")]
        if more:
            os.environ["READ_PAGE_OCR_LANGS"] = "+".join(["eng"] + more)
    os.environ["READ_PAGE_ENV"] = d


# ---------------------------------------------------------------- what --setup gives here
def machine():
    """x64, arm64, x86, armv7l... - the CPU our Python runs on."""
    import platform
    m = (platform.machine() or "").lower()
    return {"amd64": "x64", "x86_64": "x64", "x64": "x64", "arm64": "arm64", "aarch64": "arm64",
            "i386": "x86", "i686": "x86", "x86": "x86"}.get(m, m)


def musl():
    if not sys.platform.startswith("linux"):
        return False
    try:
        return any(n.startswith("ld-musl") for n in os.listdir("/lib"))
    except OSError:
        return False


def mac_version():
    import platform
    try:
        return tuple(int(x) for x in platform.mac_ver()[0].split(".")[:2])
    except ValueError:
        return (0,)


def platform_name():
    """This machine, as a sentence says what it lacks: "musl Linux on arm64", "Windows on ARM", "macOS 14.7 on x64"."""
    m = machine()
    if os.name == "nt":
        return "Windows on ARM" if m == "arm64" else "Windows on %s" % m
    if sys.platform == "darwin":
        return "macOS %s on %s" % (".".join(str(x) for x in mac_version()), m)
    return "%sLinux on %s" % ("musl " if musl() else "", m)


def linux_family(text=None):
    """The package manager of this Linux by its /etc/os-release (ID and ID_LIKE, or `text`): apk, apt, dnf,
    zypper or pacman; '' when it is none of those."""
    if text is None:
        try:
            with open("/etc/os-release", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return ""
    ids = set()
    for ln in text.splitlines():
        k, _, v = ln.partition("=")
        if k.strip() in ("ID", "ID_LIKE"):
            ids.update(v.strip().strip("\"'").lower().split())
    for fam, names in (("apk", ("alpine",)), ("apt", ("debian", "ubuntu")),
                       ("dnf", ("fedora", "rhel", "centos", "rocky", "almalinux", "amzn")),
                       ("zypper", ("suse", "opensuse", "sles")), ("pacman", ("arch", "manjaro"))):
        if ids & set(names):
            return fam
    return ""


def sudo():
    """'sudo ' for a user; '' for root, whose container has no sudo and needs none."""
    try:
        return "" if os.geteuid() == 0 else "sudo "
    except AttributeError:                       # Windows
        return "sudo "


# what the machine's own package manager calls each tool (winget / brew / a Linux family's packages)
_SYSTEM = {"curl": ("winget install --id cURL.cURL", "brew install curl", {}, "curl"),
           "chromium": ("winget install --id Google.Chrome", "brew install --cask google-chrome", {}, "chromium"),
           "poppler": ("winget install --id oschwartz10612.Poppler", "brew install poppler",
                       {"pacman": "poppler", "zypper": "poppler-tools"}, "poppler-utils"),
           "tesseract": ("winget install --id UB-Mannheim.TesseractOCR", "brew install tesseract",
                         {"apt": "tesseract-ocr", "apk": "tesseract-ocr"}, "tesseract"),
           "lynx": ("choco install lynx", "brew install lynx", {}, "lynx")}
_INSTALL = {"apt": "apt install", "apk": "apk add", "dnf": "dnf install", "zypper": "zypper install",
            "pacman": "pacman -S"}


def system_install(what, family=None, root=None):
    """The command a user of *this* machine types to get `what` (curl, chromium, poppler, tesseract, lynx) from
    its own package manager: winget or choco on Windows, brew on macOS, and on a Linux the one its os-release
    names (apt where it is unknown) - without `sudo` for root, which a container has none of."""
    win, mac, names, default = _SYSTEM[what]
    if os.name == "nt":
        return win
    if sys.platform == "darwin":
        return mac
    fam = (linux_family() if family is None else family) or "apt"
    pre = (sudo() if root is None else ("" if root else "sudo "))
    if fam == "apt" and what == "chromium":
        return "%sapt install chromium-browser  (or %ssnap install chromium)" % (pre, pre)
    return "%s%s %s" % (pre, _INSTALL[fam], names.get(fam, default))


def ocr_here():
    """tesserocr 2.13 carries tesseract 5.5.4 in its wheels for these, and only these."""
    m = machine()
    if os.name == "nt":
        return m == "x64"
    if sys.platform == "darwin":
        return mac_version() >= (15,)
    return m == "x64" or (m == "arm64" and not musl())


def gives(name):
    """Whether --setup installs this engine on this machine: the fix the setup report and the
    answers name. curl, lynx and pdftotext are the machine's own (pymupdf does pdftotext's work)."""
    if name in ("curl", "lynx", "pdftotext"):
        return False
    if name in ("tesseract", "ocr", "ocr-langs", "ocr-language"):
        return ocr_here()
    return True


def problem(name):
    """What the last --setup could not do for this engine, with the command that would: or ''."""
    for p in load().get("problems") or []:
        if isinstance(p, dict) and p.get("part") == name and p.get("fix"):
            return p["fix"]
    return ""


def fix(name, default):
    """The one line that would give this engine here."""
    return problem(name) or ("readpage.py --setup" if gives(name) else default)


YTDLP_EVERY_DAYS = 3                 # how often a video read looks for a newer yt-dlp
YTDLP_RETRY_HOURS = 1                # ... and how long after a look that failed (offline, a mirror down)


def refresh_ytdlp(every_days=YTDLP_EVERY_DAYS):
    """yt-dlp is the one engine that is not pinned: a video read in the environment looks for a
    newer one every few days - in a process of its own that nothing waits for, never inside the
    read. True when one was started. READ_PAGE_SKIP=update turns it off; --setup updates it too."""
    if not _STATUS.get("used") or "update" in set(
            x.strip() for x in os.environ.get("READ_PAGE_SKIP", "").split(",")):
        return False
    d = _STATUS.get("home") or home()
    import time
    try:
        if time.time() - os.path.getmtime(os.path.join(d, "ytdlp.stamp")) < every_days * 86400:
            return False
    except OSError:
        pass                                     # never looked: look now
    try:
        if time.time() - os.path.getmtime(os.path.join(d, "ytdlp.failed")) < YTDLP_RETRY_HOURS * 3600:
            return False                         # the last look failed a moment ago: not again at once
    except OSError:
        pass
    try:
        import envsetup
        # the stamp is the updater's, touched after an update that worked; what keeps the reads of
        # this minute from starting a second one is its lock: an update or a --setup at work holds one
        if envsetup._locked(os.path.join(d, "ytdlp.lock")) or envsetup._locked(os.path.join(d, "setup.lock")):
            return False
        return bool(envsetup.ytdlp_background(d))
    except Exception:                            # noqa: BLE001  (an update that cannot start is no read's failure)
        return False


def setup(script, skill_version):
    """readpage.py --setup (envsetup.py does the work)."""
    import envsetup
    return envsetup.setup(script, skill_version)
