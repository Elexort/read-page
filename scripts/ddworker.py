"""defuddle without the CLI's start-up: one node process per read.

The CLI loads defuddle's modules on every call (0.55 s on a 20-core Windows machine, about 2 s on a weak laptop) and runs
them with a cold JIT, and a read may call it three times: the page, the rendered DOM, an archive
copy. The worker starts with the read, loads and warms up while the HTTP request is in flight,
and answers each page the way `defuddle parse FILE --markdown` would (ddworker.js has the same
parser, options and empty-content check). Measured on 141 pages: the same text as the CLI on 139
(the other two differ in a timestamp), extraction p50 1.4 -> 0.7 s on the same machine and 4.9 -> 2.9 s on an
emulated Celeron. It ends with the read. Pages are numbered, so two threads of one read (the page
and an archive copy) each get their own answer.

Several agents reading at once get a worker each. A shared daemon would save only the start-up,
which the HTTP request hides anyway, and would bring its own lifecycle: who stops it, an old one
after an update, one crash failing every agent.
"""
import itertools
import json
import os
import re
import subprocess
import threading

JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ddworker.js")
_SHIM = re.compile(r"node_modules[\\/]+defuddle[\\/]+dist[\\/]+cli\.js")


def locate(cli, node_on_path):
    """defuddle's dist folder and the node to run it with, from the CLI's own path: (dist, node),
    or (None, None) when this install is not one we recognise (then the CLI is used as before)."""
    if not cli:
        return None, None
    here = os.path.dirname(cli)
    cands = [os.path.join(here, "node_modules", "defuddle", "dist")]      # npm on Windows: a .cmd shim
    try:
        real = os.path.realpath(cli)
        if real.endswith(".js"):
            cands.append(os.path.dirname(real))                             # npm elsewhere: a symlink to cli.js
    except OSError:
        pass
    cands.append(os.path.join(os.path.dirname(here), "lib", "node_modules", "defuddle", "dist"))
    try:
        if os.path.getsize(cli) < 20000:                                    # a shell shim names cli.js
            with open(cli, encoding="utf-8", errors="replace") as fh:
                m = _SHIM.search(fh.read())
            if m:
                cands.append(os.path.join(here, os.path.dirname(m.group(0))))
    except OSError:
        pass
    for dist in cands:
        if (os.path.isfile(os.path.join(dist, "node.js"))
                and os.path.isfile(os.path.join(dist, "utils", "linkedom-compat.js"))):
            beside = os.path.join(here, "node.exe" if os.name == "nt" else "node")
            node = beside if os.path.isfile(beside) else node_on_path
            if node:
                return os.path.normpath(dist), node
    return None, None


class Job:
    """One page sent to the worker; result() waits for its own answer."""

    def __init__(self, worker, jid):
        self.worker, self.id = worker, jid
        self.done = threading.Event()
        self.answer = None

    def result(self, seconds):
        """(markdown, why): markdown "" with why "" when defuddle found no content (the CLI's
        exit 1); None with why when the worker failed or did not answer in time."""
        if not self.done.wait(max(0.05, seconds)):
            self.worker.failed = self.worker.failed or "no answer in %.0f s" % seconds
            self.worker.close()
            return None, "no answer in %.0f s" % seconds
        msg = self.answer
        if msg is None:
            return None, self.worker.failed or "the worker ended"
        return msg.get("content") or "", msg.get("error") or ""


class Worker:
    def __init__(self, node, dist, popen_kw=None, on_start=None):
        self.p = subprocess.Popen([node, JS, dist], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, **(popen_kw or {}))
        if on_start:
            on_start(self.p)
        self.ready = threading.Event()
        self.failed = ""
        self.lock = threading.Lock()
        self.jobs = {}
        self.ids = itertools.count(1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.p.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "ready" in msg:
                    if not msg.get("ready"):
                        self.failed = "defuddle did not load: %s" % (msg.get("error") or "?")
                    self.ready.set()
                    continue
                job = self.jobs.pop(str(msg.get("id") or ""), None)
                if job is not None:
                    job.answer = msg
                    job.done.set()
        except (OSError, ValueError):
            pass
        self.failed = self.failed or "the worker ended"
        self.ready.set()
        for job in list(self.jobs.values()):         # nobody will answer them now
            job.done.set()
        self.jobs.clear()

    def submit(self, html):
        """Send a page; the writing happens in a thread, so Python works on while node reads."""
        data = html.encode("utf-8", "replace")
        job = Job(self, str(next(self.ids)))
        self.jobs[job.id] = job

        def write():
            with self.lock:
                try:
                    self.p.stdin.write(b"%s %d\n" % (job.id.encode(), len(data)))
                    self.p.stdin.write(data)
                    self.p.stdin.flush()
                except (OSError, ValueError):
                    self.failed = self.failed or "the worker stopped reading"
                    self.jobs.pop(job.id, None)
                    job.done.set()

        threading.Thread(target=write, daemon=True).start()
        return job

    def alive(self):
        return not self.failed and self.p.poll() is None

    def close(self):
        try:
            self.p.stdin.close()
        except (OSError, ValueError):
            pass
        if self.p.poll() is None:
            try:
                self.p.kill()
            except OSError:
                pass
