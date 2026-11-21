"""Speed and upkeep: caps kept, cookies locked, .part files, the disk floor.
No network.

    python -X utf8 tests/speed.py

A cached answer does not look at the machine at all (caps); caps() is computed once and kept
until PATH or one of its folders changes, and the setup report always looks again. Processes
saving one host's cookies at the same time lose none of them. A killed run's .part files are
gone at the next start, in img/ too. A download stops when the disk has less than 1 GB free.
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness import PUBLIC, SCRIPT, Checks, run_read, serve     # noqa: E402

check = Checks()
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ") * 8
PAGE = ("<!doctype html><html><head><title>Fast</title></head><body><article><h1>Fast</h1><p>FAST-PAGE "
        + EN + "</p></article></body></html>").encode("utf-8")


def module(cache):
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = cache
    os.environ["READ_PAGE_SKIP"] = "browser"
    spec = importlib.util.spec_from_file_location("rp_speed_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inproc(mod, argv):
    out, old = io.StringIO(), sys.stdout
    sys.stdout = out
    try:
        mod.main(argv + ["--json"])
    finally:
        sys.stdout = old
    try:
        return json.loads(out.getvalue() or "{}")
    except ValueError:
        return {}


def chunked(h):
    """A body with no Content-Length, sent in chunks: the length is unknown until the end."""
    h.send_response(200)
    h.send_header("Content-Type", "application/octet-stream")
    h.send_header("Transfer-Encoding", "chunked")
    h.end_headers()
    try:
        for _ in range(64):
            part = b"x" * 32768
            h.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
        h.wfile.write(b"0\r\n\r\n")
    except OSError:
        pass                                   # the reader stopped: that is the point
    h.close_connection = True


s = serve({"/fast": (200, {"Content-Type": "text/html; charset=utf-8"}, PAGE), "/blob": chunked,
           "/part": (200, {"Content-Type": "text/html; charset=utf-8"}, PAGE)})
try:
    # ------------------------------------------------ a cached answer does not look at the machine
    mod = module(tempfile.mkdtemp(prefix="rp-speed-"))
    first = inproc(mod, [s.url("/fast")])

    def boom(*a, **k):
        raise AssertionError("caps() on a cache hit")

    real_caps = mod.caps
    mod.caps = boom
    try:
        hit = inproc(mod, [s.url("/fast")])
    except AssertionError as e:
        hit = {"error": str(e)}
    mod.caps = real_caps
    check("a cached answer does not look at the machine (no caps())",
          first.get("status") == "ok" and hit.get("cache") == "hit" and hit.get("status") == "ok",
          "%s / %s" % (first.get("status"), hit.get("cache") or hit.get("error")))

    # ------------------------------------------------ caps() is kept until PATH or its folders change
    calls = []
    real_which = mod.which

    def counted(name):
        calls.append(name)
        return real_which(name)

    mod.which = counted
    mod.caps()
    calls.clear()
    mod.caps()
    check("a second caps() asks nothing again", not calls, "%d which() calls" % len(calls))
    extra = tempfile.mkdtemp(prefix="rp-path-")
    os.environ["PATH"] = extra + os.pathsep + os.environ.get("PATH", "")
    mod.caps()
    check("a new folder on PATH is looked at", bool(calls), "%d which() calls" % len(calls))
    calls.clear()
    open(os.path.join(extra, "newtool.txt"), "w").close()      # an install changes its folder
    t = time.time() + 5
    os.utime(extra, (t, t))
    mod.caps()
    check("something installed into a PATH folder is seen", bool(calls), "%d which() calls" % len(calls))
    calls.clear()
    mod.caps(fresh=True)
    check("the setup report and --caps look again (fresh)", bool(calls), "%d which() calls" % len(calls))
    mod.which = real_which

    # ------------------------------------------------ one host's cookies, many writers, none lost
    cache = tempfile.mkdtemp(prefix="rp-jar-")
    code = ("import sys, os; sys.path.insert(0, %r); os.environ['READ_PAGE_CACHE'] = %r\n"
            "import readpage\n"
            "w = int(sys.argv[1])\n"
            "for i in range(30):\n"
            "    readpage.save_cookies('https://jar.example.com/', {'c%%d_%%d' %% (w, i): {'v': 'x', 'd': '', 'e': 0,"
            " 'p': '/', 's': False}})\n") % (os.path.join(os.path.dirname(HERE), "scripts"), cache)
    procs = [subprocess.Popen([sys.executable, "-c", code, str(w)]) for w in range(4)]
    for p in procs:
        p.wait(timeout=120)
    mod_j = module(cache)
    names = set(mod_j.load_cookies("https://jar.example.com/"))
    check("four processes save 120 cookies of one host at once, none is lost", len(names) == 120,
          "%d of 120" % len(names))

    # ------------------------------------------------ a killed run's .part files are gone
    work = tempfile.mkdtemp(prefix="rp-part-")
    os.makedirs(os.path.join(work, "img"))
    for p in ("raw.html.part", os.path.join("img", "03-chart.png.part")):
        with open(os.path.join(work, p), "wb") as fh:
            fh.write(b"half a file")
    with open(os.path.join(work, "notes.txt"), "w") as fh:
        fh.write("the user's own file")
    r = run_read(s.url("/part"), "--dir", work, own_dir=False, env={"READ_PAGE_SKIP": "browser"})
    left = [p for p in ("raw.html.part", os.path.join("img", "03-chart.png.part")) if os.path.exists(os.path.join(work, p))]
    check("a killed run's .part files are gone at the next start, img/ too",
          not left and os.path.isfile(os.path.join(work, "notes.txt")), str(left))

    # ------------------------------------------------ a download stops on a full disk
    mod_d = module(tempfile.mkdtemp(prefix="rp-disk-"))
    mod_d.SPOOL_INMEM = 1024                              # the body goes to disk at once
    mod_d.free_bytes = lambda path: 500 * 1024 * 1024     # 500 MB free: under the 1 GB floor
    out = tempfile.mkdtemp(prefix="rp-disk-out-")
    md = inproc(mod_d, [s.url("/blob"), "--download", "--dir", out])
    why = str((md.get("signals") or {}).get("status_reason") or "") + " " + str(md.get("advice") or "")
    parts = [n for n in os.listdir(out) if n.endswith(".part")]
    check("a download stops when the disk has under 1 GB free, and says so",
          md.get("status") == "error" and "disk" in why and not parts,
          "%s: %s %s" % (md.get("status"), why[:90], parts))
finally:
    s.close()

sys.exit(check.done())
