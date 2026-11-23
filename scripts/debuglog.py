"""READ_PAGE_DEBUG=1: the whole story of one read, as JSON lines, for whoever debugs the reader.

Nothing of it reaches the answer or the manifest (MCP hands the manifest to the model): the log is
a file. With READ_PAGE_DEBUG=1 it is the read's own folder, debug/<started>-<pid>.jsonl; with
READ_PAGE_DEBUG_DIR=<folder> every read of a test session writes <started>-<host>-<pid>.jsonl
there instead, so a session's logs are in one place. A line is {"t": seconds since the read
began, "k": kind, "th": the thread when it is not the main one, ...}. Kinds:

  run       version, flags, the machine (OS, CPUs, Python), READ_PAGE_* settings, which keys exist
  caps      the tools, libraries and browsers this read can use
  step      a step as it ended (budget.record): start, seconds, own cap, the cap it got, how it ended
  event     what trace() names: HTTP attempts, cache, extraction, the browser, pictures
  decide    a rule and everything it looked at: early browser, extraction, walls, the browser's
            text taken or not, the status
  browser   the browser's own story: which one, launch, load, every change the settle rule saw
  net       a request the browser made, finished, failed or was refused
  picture   one picture: its result, bytes, time
  error     an exception the reader caught and went on from
  summary   what the read answered: status, engine, words, signals, chain, files, time

Secrets stay out: an API key is named, never printed; cookie values are never logged; a URL's
query values whose names look like credentials are masked (mask_url).
"""
import json
import os
import platform
import re
import sys
import threading
import time
import traceback

_S = {"on": None, "t0": time.time(), "buf": [], "fh": None, "path": ""}
_LOCK = threading.Lock()
_CRED = re.compile(r"(?i)(key|token|secret|passw|pwd|auth|sig|session|sid|code|credential|ticket|jwt)")
_OFF = ("", "0", "false", "no", "off")


def enabled():
    """READ_PAGE_DEBUG set (to anything but 0/false/no/off), or READ_PAGE_DEBUG_DIR set."""
    if _S["on"] is None:
        v = (os.environ.get("READ_PAGE_DEBUG") or "").strip().lower()
        _S["on"] = bool((os.environ.get("READ_PAGE_DEBUG_DIR") or "").strip()) or v not in _OFF
    return _S["on"]


def begin():
    """A new read: the clock restarts, the previous read's file is closed."""
    close()
    with _LOCK:
        _S.update(on=None, t0=time.time(), buf=[], fh=None, path="")


def bind(folder, host=""):
    """Where this read's log goes, once its folder is known; what was logged before is written now."""
    if not enabled() or _S["fh"] is not None:
        return _S["path"]
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(_S["t0"])) + ".%03d" % int((_S["t0"] % 1) * 1000)
    central = (os.environ.get("READ_PAGE_DEBUG_DIR") or "").strip()
    if central:
        safe = re.sub(r"[^A-Za-z0-9.-]+", "_", host or "page")[:60]
        path = os.path.join(central, "%s-%s-%d.jsonl" % (stamp, safe, os.getpid()))
    else:
        path = os.path.join(folder, "debug", "%s-%d.jsonl" % (stamp, os.getpid()))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # a path of bytes that are no UTF-8 (a folder named in GBK under that locale: lone surrogates) is
        # written escaped - the log never raises, and it stopped the read at its first buffered line
        fh = open(path, "a", encoding="utf-8", errors="backslashreplace", newline="\n")
    except OSError:
        return ""
    with _LOCK:
        for line in _S["buf"]:
            fh.write(line + "\n")
        fh.flush()
        _S.update(buf=[], fh=fh, path=path)
    return path


def path():
    return _S["path"]


def log(_k, **fields):
    """One line of the log, kind `_k`. Cheap when debugging is off; never raises. The kind is
    positional-only in spirit: a field may be called anything, `kind` included."""
    if not enabled():
        return
    try:
        row = {"t": round(time.time() - _S["t0"], 3), "k": _k}
        th = threading.current_thread().name
        if th != "MainThread":
            row["th"] = th
        row.update(fields)
        line = json.dumps(row, ensure_ascii=False, default=_plain)
    except Exception:                                             # noqa: BLE001
        return
    with _LOCK:
        fh = _S["fh"]
        if fh is None:
            _S["buf"].append(line)
            return
        try:
            fh.write(line + "\n")
            fh.flush()                       # a read killed at its backstop keeps what it logged
        except (OSError, ValueError):
            pass


def exc(_where, _e=None, **fields):
    """An exception the reader caught and went on from: where, its type and text, the last frames."""
    if not enabled():
        return
    e = _e if _e is not None else sys.exc_info()[1]
    tb = ""
    if e is not None and getattr(e, "__traceback__", None) is not None:
        tb = " | ".join(line.strip().replace("\n", " ") for line in
                        traceback.format_tb(e.__traceback__)[-3:])[:900]
    log("error", where=_where, type=type(e).__name__ if e is not None else "", msg=str(e)[:500], tb=tb, **fields)


def close():
    with _LOCK:
        fh, _S["fh"] = _S["fh"], None
    if fh is not None:
        try:
            fh.close()
        except OSError:
            pass


def _plain(v):
    if isinstance(v, (set, frozenset, tuple)):
        return list(v)
    if isinstance(v, bytes):
        return "<%d bytes>" % len(v)
    return str(v)


def mask_url(url):
    """A URL fit for the log: query values whose names look like credentials become ***."""
    u = str(url or "")
    if "?" not in u and "#" not in u:
        return u[:600]
    head, sep, rest = u.partition("?")
    if not sep:
        return u[:600]
    q, hsep, frag = rest.partition("#")
    parts = []
    for item in q.split("&"):
        k, eq, v = item.partition("=")
        parts.append("%s=***" % k if (eq and v and _CRED.search(k)) else item)
    return (head + "?" + "&".join(parts) + (hsep + frag if hsep else ""))[:600]


def environment():
    """The machine and this reader's settings, for the run line: what makes two logs comparable."""
    env = {}
    for k in sorted(os.environ):
        up = k.upper()
        if up.startswith("READ_PAGE_"):
            env[k] = "set" if _CRED.search(up[len("READ_PAGE_"):]) else os.environ[k][:200]
        elif up.endswith(("_API_KEY", "_TOKEN", "_SECRET")):
            env[k] = "set"                   # named, never printed
    proxies = {k: "set" for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy",
                                  "https_proxy", "all_proxy", "no_proxy") if os.environ.get(k)}
    return {"os": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count(),
            "python": sys.version.split()[0], "executable": sys.executable,
            "encoding": sys.getfilesystemencoding(), "env": env, "proxy_env": proxies}
