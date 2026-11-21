"""What .github/workflows/install.yml measures and asserts: real installs on every runner.

    python -X utf8 tools/ci_install.py <command> [options]

    machine   print the machine (OS, CPU, libc, free disk) and keep it for the summary
    home      a fresh READ_PAGE_HOME whose path has a space and letters outside ASCII (-> GITHUB_ENV)
    setup     run `readpage.py --setup`, timing it and counting the bytes that came in and what it took
    check     read what the setup built (setup.json): steps and engines that did not work must be what
              the matrix expects, and each must be named with a reason and a fix
    read      a local HTML file, a public page and (--ocr) a scanned PDF, through the installed skill
    suites    the offline suites, under the environment's own Python
    bare      a Python with nothing installed and no --setup: the CLI, the report, a local read
    collect   the setup's logs and state into the folder that is uploaded
    summary   a Markdown table of everything above (the job summary)
    mkscan    (inside the environment) a scanned PDF: a picture of words, no text layer

Stdlib only and Python 3.8+: it runs under macOS's /usr/bin/python3 (3.9), Alpine's python3 and
the runner's own Pythons. What it expects to be missing on a platform comes from the matrix
(CI_EXPECT_MISSING, a comma-separated list of the names `check` prints): a platform whose wheels do
not exist is a documented floor, and a gap that is not on that list turns the job red.
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# letters outside ASCII are built from code points, so that no editor, shell or encoding can change them
DOT = chr(0xB7)                                           # the middle dot of the answer's status line
IVAN = "".join(chr(c) for c in (0x418, 0x432, 0x430, 0x43D))                 # "Ivan", Cyrillic: a user's folder
PRIVET = "".join(chr(c) for c in (0x41F, 0x440, 0x438, 0x432, 0x435, 0x442))  # "Hello", Cyrillic
STATUS_LINE = re.compile("^read-page %s (\\w+) %s (.*)$" % (DOT, DOT))
RESULT_LINE = re.compile(r"(\d+) ok, (\d+) failed")
OFFLINE = ["reading", "sources", "blocks", "images", "speed", "mcp_parallel", "timeouts", "deadline", "formats",
           "statuses", "security", "contract", "props", "fixes", "channel", "office_fixtures", "mcp_smoke",
           "setup_audit", "environment"]
# the one suite that needs the installed browser, not a third party: the setup's own Chromium, on every system
BROWSER_SUITE = "browser_live"
# the status line's `ok` is what the contract promises; the page the CI reads is the IANA example
PUBLIC_URL = "https://example.com"
PUBLIC_WORDS = "documentation examples"          # in the page's text, whichever extractor kept its title or not
SCAN_WORDS = "Invoice 4711 paid in full"


# ---------------------------------------------------------------- small things
def logs():
    d = os.environ.get("CI_LOGS") or os.path.join(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir(), "ci-logs")
    os.makedirs(d, exist_ok=True)
    return d


def skill_dir(a):
    return os.path.abspath(getattr(a, "skill", None) or ROOT)


def script(a):
    return os.path.join(skill_dir(a), "scripts", "readpage.py")


def home_of(a):
    """The folder --setup uses: READ_PAGE_HOME, else the skill's own default for this OS."""
    v = (os.environ.get("READ_PAGE_HOME") or "").strip()
    if v:
        return os.path.abspath(os.path.expanduser(v))
    sys.dont_write_bytecode = True
    sys.path.insert(0, os.path.join(skill_dir(a), "scripts"))
    import ownenv
    return ownenv.home()


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def results_path():
    return os.path.join(logs(), "results.json")


def save(key, value):
    r = load_json(results_path())
    r[key] = value
    with open(results_path(), "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1, ensure_ascii=False)


def export_env(name, value):
    path = os.environ.get("GITHUB_ENV")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s=%s\n" % (name, value))


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def tree_size(path, skip=()):
    """Bytes under a folder, a hard-linked file once (uv's cache is linked into the environment)."""
    seen, total = set(), 0
    skip = [os.path.normcase(os.path.abspath(s)) for s in skip]
    for root, dirs, files in os.walk(path):
        if os.path.normcase(os.path.abspath(root)) in skip:
            dirs[:] = []
            continue
        for n in files:
            p = os.path.join(root, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if st.st_nlink > 1 and st.st_ino:
                key = (st.st_dev, st.st_ino)
                if key in seen:
                    continue
                seen.add(key)
            total += st.st_size
    return total


def free_disk(path):
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return shutil.disk_usage(path or ".").free


def nic_rx():
    """Bytes received on every real network interface since boot (None where it cannot be read): the
    difference around a command is its download (plus a little of the runner's own traffic)."""
    try:
        if sys.platform.startswith("linux"):
            total = 0
            with open("/proc/net/dev", encoding="utf-8") as fh:
                for ln in fh.read().splitlines()[2:]:
                    name, _, rest = ln.partition(":")
                    if name.strip() != "lo" and rest.split():
                        total += int(rest.split()[0])
            return total
        if sys.platform == "darwin":
            out = subprocess.run(["netstat", "-ib"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=30).stdout.decode("utf-8", "replace")
            total = 0
            for ln in out.splitlines():
                t = ln.split()
                if len(t) >= 10 and t[0] != "lo0" and any(x.startswith("<Link#") for x in t[:4]):
                    total += int(t[-5])                 # ... Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll
            return total
        if os.name == "nt":
            # the adapters' 64-bit counters (netstat -e has 32-bit ones, which wrap after 4 GB and read
            # negative across a 500 MB download on a machine that has been up a while)
            for shell in ("powershell", "pwsh"):
                p = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command",
                                    "(Get-NetAdapterStatistics | Measure-Object -Property ReceivedBytes -Sum).Sum"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
                got = p.stdout.decode("utf-8", "replace").strip()
                if p.returncode == 0 and got.isdigit():
                    return int(got)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def run_capture(cmd, env=None, timeout=300, cwd=None):
    """(returncode, output as text) - a program that does not start or does not end is a result too."""
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           env=env, timeout=timeout, cwd=cwd)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        return -1, (e.output or b"").decode("utf-8", "replace") + "\n(timed out after %d s)" % timeout
    except OSError as e:
        return -2, str(e)


def fail(msg):
    print("FAIL: %s" % msg)
    return 1


def expected(a):
    raw = getattr(a, "expect", None)
    if raw is None:
        raw = os.environ.get("CI_EXPECT_MISSING", "")
    return sorted(x.strip() for x in raw.split(",") if x.strip())


def env_python(a):
    """The environment's Python (setup.json says where), or ''."""
    info = load_json(os.path.join(home_of(a), "setup.json"))
    rel = info.get("python")
    py = os.path.join(home_of(a), *rel.split("/")) if rel else ""
    return py if py and os.path.isfile(py) else ""


# ---------------------------------------------------------------- machine, home
def cmd_machine(a):
    info = {"platform": platform.platform(), "machine": platform.machine(), "system": platform.system(),
            "python": sys.version.split()[0], "executable": sys.executable, "cpus": os.cpu_count(),
            "free_disk": free_disk(tempfile.gettempdir())}
    if sys.platform.startswith("linux"):
        try:
            with open("/etc/os-release", encoding="utf-8") as fh:
                m = re.search(r'^PRETTY_NAME="?([^"\n]*)', fh.read(), re.M)
            info["os"] = m.group(1) if m else ""
        except OSError:
            pass
        rc, out = run_capture(["ldd", "--version"], timeout=20)
        first = (out.strip().splitlines() or [""])[0]
        info["libc"] = "musl" if "musl" in out.lower() else first
    elif sys.platform == "darwin":
        rc, out = run_capture(["sw_vers", "-productVersion"], timeout=20)
        info["os"] = "macOS " + out.strip()
    else:
        info["os"] = platform.platform()
    info["runner"] = os.environ.get("RUNNER_OS", "") + " " + os.environ.get("RUNNER_ARCH", "")
    for k, v in sorted(info.items()):
        print("%-10s %s" % (k, human(v) if k == "free_disk" else v))
    save("machine", info)
    return 0


def cmd_home(a):
    base = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
    # a space and "Ivan" in Cyrillic: the review of --setup asked for exactly this home (H1 of the 2026-11-20
    # review: OCR died silently on such a path on Windows)
    home = os.path.join(base, "rp home " + IVAN)
    shutil.rmtree(home, ignore_errors=True)
    export_env("READ_PAGE_HOME", home)
    print(home)
    return 0


# ---------------------------------------------------------------- setup
def setup_once(py, a, env):
    """One `readpage.py --setup`, its output shown as it comes: (exit code, the output)."""
    print("$ %s -X utf8 %s --setup" % (py, script(a)))
    sys.stdout.flush()
    p = subprocess.Popen([py, "-X", "utf8", script(a), "--setup"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, env=env)
    out = []
    for raw in p.stdout:
        line = raw.decode("utf-8", "replace")
        out.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()
    return p.wait(), "".join(out)


def cmd_setup(a):
    d = home_of(a)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    py = a.python or sys.executable
    # --follow: what an agent's harness does. Without a terminal the command follows the work for 100 s,
    # says it goes on in the background, and returns; the agent runs it again, which follows the same work
    # (that is the skill's own instruction). Otherwise it is followed to the end (READ_PAGE_SETUP_WAIT).
    if not a.follow:
        env["READ_PAGE_SETUP_WAIT"] = str(a.wait)
    free0, rx0, t0 = free_disk(d), nic_rx(), time.time()
    print("into %s" % d)
    runs, texts = 0, []
    while True:
        rc, text = setup_once(py, a, env)
        runs += 1
        texts.append(text)
        if not (a.follow and rc == 0 and "goes on in the background" in text and time.time() - t0 < a.wait):
            break
        print("(--setup returned with the work still going: asking again, as the skill tells an agent to)")
    secs, rx1, free1 = time.time() - t0, nic_rx(), free_disk(d)
    text = "\n".join(texts)
    with open(os.path.join(logs(), "setup-%s.log" % a.label), "w", encoding="utf-8") as fh:
        fh.write(text)
    m = {"rc": rc, "runs": runs, "seconds": round(secs, 1),
         "download": (rx1 - rx0) if (rx0 is not None and rx1 is not None) else None,
         "home_bytes": tree_size(d) if os.path.isdir(d) else 0,
         "home_bytes_no_cache": tree_size(d, skip=[os.path.join(d, "cache")]) if os.path.isdir(d) else 0,
         "disk_delta": free0 - free1}
    save("setup_" + a.label, m)
    print("\n== setup %s: exit %s, %.0f s, download %s, folder %s (%s without cache), disk used %s"
          % (a.label, rc, secs, human(m["download"]) if m["download"] is not None else "?", human(m["home_bytes"]),
             human(m["home_bytes_no_cache"]), human(m["disk_delta"])))
    bad = []
    if rc not in (0, 1):
        bad.append("--setup exited %s (0: all done, 1: something named is missing)" % rc)
    if "Traceback (most recent call last)" in text:
        bad.append("a Python traceback in --setup's output")
    if "could not start the work" in text or "the work did not start" in text:
        bad.append("the work did not start")
    if "goes on in the background" in texts[-1]:
        bad.append("it did not end in %s s" % a.wait)
    if a.max_seconds and secs > a.max_seconds:
        bad.append("took %.0f s, more than the %d s allowed" % (secs, a.max_seconds))
    if a.max_mb is not None and m["download"] is not None and m["download"] > a.max_mb * 1024 * 1024:
        bad.append("downloaded %s, more than the %d MB allowed (nothing was to be fetched)"
                   % (human(m["download"]), a.max_mb))
    for b in bad:
        fail(b)
    return 1 if bad else 0


# ---------------------------------------------------------------- check
# which problem names a step or an engine that did not work
ALIASES = {"ocr data": ("ocr-langs", "tesseract"), "tesseract": ("tesseract", "tesserocr", "ocr-langs"),
           "network": ("disk",), "check": ()}


def named(gap, problems):
    return [p for p in problems if p.get("part") == gap or p.get("part") in ALIASES.get(gap, ())]


def cmd_check(a):
    d = home_of(a)
    info = load_json(os.path.join(d, "setup.json"))
    if not info.get("env"):
        return fail("no environment was built: %s has no setup.json" % d)
    parts, checked, problems = info.get("parts") or {}, info.get("checked") or {}, info.get("problems") or []
    print("environment %s  (python %s, %s s, built %s)" % (info.get("env"), info.get("python"), info.get("seconds"),
                                                          info.get("built")))
    print("\nsteps")
    for name, v in parts.items():
        print("  %-9s %-5s %5.0f s  %s" % (name, "ok" if v.get("ok") else "FAIL", v.get("seconds") or 0,
                                           (v.get("note") or "")[:150]))
    print("engines checked on a sample")
    for name, v in sorted(checked.items()):
        if isinstance(v, dict):
            print("  %-9s %-5s %s" % (name, "ok" if v.get("ok") else "FAIL",
                                      (v.get("version") or v.get("why") or "")[:150]))
    gaps = sorted(set([k for k, v in parts.items() if not v.get("ok") and k != "check"]
                      + [k for k, v in checked.items() if isinstance(v, dict) and not v.get("ok")]))
    want = expected(a)
    print("\nnot working: %s" % (", ".join(gaps) or "nothing"))
    print("expected    : %s" % (", ".join(want) or "nothing"))
    bad = []
    unexpected = [g for g in gaps if g not in want]
    if unexpected:
        bad.append("not working and not expected: %s" % ", ".join(unexpected))
    gone = [g for g in want if g not in gaps]
    if gone:
        print("note: expected to be missing, and works now: %s (a floor that moved: update the matrix and the docs)"
              % ", ".join(gone))
    # every gap is named, with a reason and a fix
    for g in gaps:
        found = named(g, problems)
        if not found:
            bad.append("%s is missing and --setup named no problem for it" % g)
        for p in found:
            if not (p.get("why") or "").strip():
                bad.append("%s: its problem has no reason" % p.get("part"))
            if not (p.get("fix") or "").strip():
                bad.append("%s: named without a fix (%s)" % (p.get("part"), (p.get("why") or "")[:100]))
    first = os.path.join(logs(), "setup-first.log")
    text = ""
    try:
        with open(first, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        pass
    if text and problems and "not done:" not in text:
        bad.append("problems were recorded, and the last --setup says nothing of them (no 'not done:' line)")
    save("check", {"steps": {k: bool(v.get("ok")) for k, v in parts.items()},
                   "engines": {k: bool(v.get("ok")) for k, v in checked.items() if isinstance(v, dict)},
                   "gaps": gaps, "expected": want, "problems": problems,
                   "versions": {k: (v.get("version") or "") for k, v in checked.items() if isinstance(v, dict)}})
    for b in bad:
        fail(b)
    return 1 if bad else 0


# ---------------------------------------------------------------- read
def status_of(text):
    for ln in text.splitlines()[:5]:
        m = STATUS_LINE.match(ln)
        if m:
            return m.group(1), m.group(2)
    return "", ""


def read(a, args, py=None, env=None, timeout=240):
    return run_capture([py or a.python or sys.executable, "-X", "utf8", script(a)] + args,
                       env=env or dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=timeout)


def write_html(path):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("<html><head><title>CI page</title></head><body><article><h1>Hello from CI</h1>"
                 "<p>read-page reads this local file in the install job, a plain paragraph long enough to count "
                 "as the body of an article for any extractor.</p><p>" + PRIVET + ", "
                 "world: a second paragraph, with letters outside ASCII, to see UTF-8 whole.</p>"
                 "</article></body></html>")


def cmd_mkscan(a):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("L", (1240, 300), 255)
    try:
        font = ImageFont.load_default(size=72)
    except TypeError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((40, 90), SCAN_WORDS, fill=0, font=font)
    img.save(a.path, "PDF", resolution=150.0)
    return 0


def cmd_read(a):
    work = os.path.join(logs(), "reads")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    d = home_of(a)
    bad, res = [], {}
    # the environment is the one in use: the report says so
    rc, out = read(a, [])
    envline = next((ln for ln in out.splitlines() if ln.startswith("environment:")), "")
    print(envline)
    if "not used" in envline or "none yet" in envline or d not in envline:
        bad.append("the read does not go into the environment in %s: %s" % (d, envline or out[:200]))
    res["environment_used"] = not bad
    html = os.path.join(work, "page.html")
    write_html(html)
    rc, out = read(a, [html, "--dir", os.path.join(work, "local")])
    st, why = status_of(out)
    print("\n== local HTML: %s | %s" % (st, why[:100]))
    print("\n".join(out.splitlines()[:12]))
    res["local"] = st
    if st != "ok" or "Hello from CI" not in out or PRIVET not in out:
        bad.append("the local HTML did not read ok with its text whole (status %r)" % st)
    for attempt in (1, 2):                                      # a third party's page: one more try
        rc, out = read(a, [PUBLIC_URL, "--refresh", "--dir", os.path.join(work, "public%d" % attempt)])
        st, why = status_of(out)
        print("\n== %s (try %d): %s | %s" % (PUBLIC_URL, attempt, st, why[:100]))
        print("\n".join(out.splitlines()[:10]))
        if st == "ok" and PUBLIC_WORDS in out:
            break
    res["public"] = st
    if st != "ok" or PUBLIC_WORDS not in out:
        bad.append("%s did not read ok (status %r)" % (PUBLIC_URL, st))
    if a.ocr:
        py = env_python(a)
        pdf = os.path.join(work, "scan.pdf")
        rc, out = run_capture([py, "-X", "utf8", os.path.abspath(__file__), "mkscan", pdf]) if py else (1, "no env python")
        if rc != 0 or not os.path.isfile(pdf):
            bad.append("could not make the scanned PDF: %s" % out[-200:])
        else:
            rc, out = read(a, [pdf, "--dir", os.path.join(work, "scan")], timeout=300)
            st, why = status_of(out)
            print("\n== scanned PDF: %s | %s" % (st, why[:100]))
            print("\n".join(out.splitlines()[:12]))
            res["ocr"] = st
            if st != "ok" or "4711" not in out:
                msg = "the scanned PDF was not read through OCR (status %r)" % st
                if "tesseract" in expected(a):
                    print("note: " + msg + " - expected, OCR is a documented gap here")
                else:
                    bad.append(msg)
    save("reads", res)
    for b in bad:
        fail(b)
    return 1 if bad else 0


# ---------------------------------------------------------------- suites
def cmd_suites(a):
    names = [x for x in a.only.split(",") if x] or (OFFLINE + ([] if a.no_browser else [BROWSER_SUITE]))
    py = a.python or env_python(a) or sys.executable
    print("suites run under %s" % py)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("READ_PAGE_SETUP_WAIT", None)
    res, bad = {}, []
    for n in names:
        path = os.path.join(ROOT, "tests", n + ".py")
        t0 = time.time()
        rc, out = run_capture([py, "-X", "utf8", path], env=env, timeout=a.timeout, cwd=ROOT)
        with open(os.path.join(logs(), "suite-%s.log" % n), "w", encoding="utf-8") as fh:
            fh.write(out)
        m = None
        for ln in out.splitlines()[::-1]:
            m = RESULT_LINE.search(ln)
            if m:
                break
        ok_n, failed_n = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
        good = m is not None and failed_n == 0 and rc == 0
        res[n] = {"ok": ok_n, "failed": failed_n, "rc": rc, "seconds": round(time.time() - t0)}
        print("%-5s %-16s %s  (%d s)" % ("ok" if good else "FAIL", n,
                                         ("%d ok, %d failed" % (ok_n, failed_n)) if m else "no result line, exit %s" % rc,
                                         time.time() - t0))
        if not good:
            bad.append(n)
            print("".join(ln + "\n" for ln in out.splitlines() if ln.startswith("FAIL"))[-3000:] or out[-1500:])
        sys.stdout.flush()
    save("suites", res)
    if bad:
        fail("suites that did not end green: %s (every suite ran; logs in the artifact)" % ", ".join(bad))
    return 1 if bad else 0


# ---------------------------------------------------------------- bare
def cmd_bare(a):
    """A Python with nothing installed beside the standard library, and no --setup: the skill still answers,
    names --setup, and reads a local file by the standard library alone."""
    bad, res = [], {}
    home = os.path.join(tempfile.mkdtemp(prefix="rp-bare-"), "home")          # nothing set up in it
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", READ_PAGE_HOME=home)
    env.pop("READ_PAGE_SKIP", None)
    rc, out = read(a, ["--version"], env=env)
    print("--version: %s %s" % (rc, out.strip()))
    if rc != 0 or "read-page" not in out:
        bad.append("--version: exit %s: %s" % (rc, out[-200:]))
    rc, out = read(a, ["--caps"], env=env)
    try:
        caps = json.loads(out)
        libs = caps.get("libs") or {}
        print("--caps: %d libs, %s present, python %s" % (len(libs), ", ".join(k for k, v in libs.items() if v) or "none",
                                                           caps.get("python")))
        res["caps_libs"] = sorted(k for k, v in libs.items() if v)
        if any(libs.get(k) for k in ("trafilatura", "html2text", "pymupdf", "curl_cffi", "readability")):
            bad.append("this Python is not bare: %s" % ", ".join(k for k, v in libs.items() if v))
    except ValueError:
        bad.append("--caps did not answer JSON: %s" % out[-300:])
    rc, out = read(a, [], env=env)
    print("\nthe setup report:\n%s" % "\n".join(out.splitlines()[:14]))
    if "readpage.py --setup" not in out or "no URL given" not in out or "environment: none yet" not in out:
        bad.append("the setup report (no URL) does not name `readpage.py --setup` for a bare machine")
    work = tempfile.mkdtemp(prefix="rp-bare-read-")
    html = os.path.join(work, "page.html")
    write_html(html)
    rc, out = read(a, [html, "--dir", os.path.join(work, "out")], env=env)
    st, why = status_of(out)
    print("\n== local HTML, nothing installed: %s | %s" % (st, why[:100]))
    print("\n".join(out.splitlines()[:10]))
    res["local"], res["engine"] = st, why.split(",")[0]
    if st != "ok" or "Hello from CI" not in out:
        bad.append("a local HTML did not read ok with the standard library alone (status %r)" % st)
    rc, out = read(a, [PUBLIC_URL, "--dir", os.path.join(work, "public")], env=env)
    st, why = status_of(out)
    print("\n== %s, nothing installed: %s | %s" % (PUBLIC_URL, st, why[:100]))
    res["public"] = st
    if st != "ok":
        print("note: a public page did not read ok with the standard library alone (status %r)" % st)
    save("bare", res)
    for b in bad:
        fail(b)
    return 1 if bad else 0


# ---------------------------------------------------------------- collect, summary
def cmd_collect(a):
    d, out = home_of(a), logs()
    for n in ("setup.log", "setup-detail.log", "setup.json", "setup.state", "setup-check.json", "ytdlp.stamp",
              "ytdlp.failed"):
        if os.path.isfile(os.path.join(d, n)):
            shutil.copyfile(os.path.join(d, n), os.path.join(out, n))
    rows = []
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            rows.append("%10s  %s" % (human(tree_size(p) if os.path.isdir(p) else os.path.getsize(p)), n))
    with open(os.path.join(out, "home-listing.txt"), "w", encoding="utf-8") as fh:
        fh.write("%s\n%s\n" % (d, "\n".join(rows)))
    print("\n".join(rows))
    return 0


def cmd_summary(a):
    r = load_json(results_path())
    m, chk, first, second = r.get("machine") or {}, r.get("check") or {}, r.get("setup_first") or {}, r.get("setup_second") or {}
    lines = ["### %s" % (a.title or "install"), ""]
    lines.append("| | |\n|---|---|")
    lines.append("| machine | %s, %s, python %s %s |" % (m.get("os") or m.get("platform"), m.get("machine"),
                                                         m.get("python"), m.get("libc") or ""))
    if first:
        lines.append("| first `--setup` | exit %s, %s s, download %s, folder %s (%s without cache), disk used %s |"
                     % (first.get("rc"), first.get("seconds"),
                        human(first["download"]) if first.get("download") is not None else "?",
                        human(first.get("home_bytes")), human(first.get("home_bytes_no_cache")),
                        human(first.get("disk_delta"))))
    if second:
        lines.append("| second `--setup` | exit %s, %s s, download %s |"
                     % (second.get("rc"), second.get("seconds"),
                        human(second["download"]) if second.get("download") is not None else "?"))
    if chk:
        steps, eng = chk.get("steps") or {}, chk.get("engines") or {}
        lines.append("| steps / engines | %d of %d steps, %d of %d engines answer |"
                     % (sum(steps.values()), len(steps), sum(eng.values()), len(eng)))
        lines.append("| not working | %s (expected: %s) |" % (", ".join(chk.get("gaps") or []) or "nothing",
                                                              ", ".join(chk.get("expected") or []) or "nothing"))
    if r.get("reads"):
        lines.append("| reads | %s |" % ", ".join("%s %s" % kv for kv in sorted(r["reads"].items())))
    if r.get("bare"):
        lines.append("| bare | %s |" % ", ".join("%s %s" % kv for kv in sorted(r["bare"].items())))
    s = r.get("suites") or {}
    if s:
        lines.append("| suites | %d ok, %d red: %s |" % (sum(1 for v in s.values() if v["failed"] == 0 and v["rc"] == 0),
                                                         sum(1 for v in s.values() if v["failed"] != 0 or v["rc"] != 0),
                                                         ", ".join(k for k, v in s.items() if v["failed"] != 0 or v["rc"] != 0)
                                                         or "none"))
    text = "\n".join(lines) + "\n"
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0


# ---------------------------------------------------------------- main
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *opts):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--skill", help="the skill's folder (default: this repository)")
        p.add_argument("--python", help="the Python that runs the skill (default: this one)")
        for o in opts:
            o(p)
        return p

    add("machine", cmd_machine)
    add("home", cmd_home)
    add("setup", cmd_setup,
        lambda p: p.add_argument("--label", default="first"),
        lambda p: p.add_argument("--follow", action="store_true",
                                 help="ask again while the work goes on in the background, as an agent does"),
        lambda p: p.add_argument("--wait", type=int, default=3000, help="seconds --setup is followed (READ_PAGE_SETUP_WAIT)"),
        lambda p: p.add_argument("--max-seconds", type=int, default=0),
        lambda p: p.add_argument("--max-mb", type=int, default=None))
    add("check", cmd_check, lambda p: p.add_argument("--expect"))
    add("read", cmd_read, lambda p: p.add_argument("--ocr", action="store_true"),
        lambda p: p.add_argument("--expect"))
    add("suites", cmd_suites, lambda p: p.add_argument("--only", default=""),
        lambda p: p.add_argument("--no-browser", action="store_true"),
        lambda p: p.add_argument("--timeout", type=int, default=1800))
    add("bare", cmd_bare)
    add("collect", cmd_collect)
    add("summary", cmd_summary, lambda p: p.add_argument("--title"))
    p = sub.add_parser("mkscan")
    p.set_defaults(fn=cmd_mkscan)
    p.add_argument("path")
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
