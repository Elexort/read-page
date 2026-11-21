"""The read's deadline: 55 s for every read, the CLI and MCP alike.

MCP harnesses cancel a call at about 60 s (Codex, Cline, Cursor, Claude desktop) and a killed call
returns nothing, so the read stops itself first and prints what it has. The deadline is a
backstop, not the plan: each step keeps its own cap, a fuse against a stuck tool, and every chain
fits by those caps. A step takes the smaller of its cap and what the deadline leaves after the
tail; the tail (the block rule, the pictures, the answer) always keeps TAIL seconds.
`--download` has no deadline.

READ_PAGE_TEST_DEADLINE shortens the deadline for the test suites; the tail shrinks with it.

Each step of a read is recorded as it ends (record): when it started, how long it took, its own
cap and the cap it got, and how it ended - ok, cap (its own fuse fired), deadline (the read's
deadline had shortened its cap, and that fired), stall (the server stopped sending), fail. With
READ_PAGE_DEBUG=1 each step goes to the read's debug log (debuglog.py), never to the answer.
"""
import os
import threading
import time

import debuglog

SECONDS = 55.0
TAIL = 6.0                 # block rule + pictures (6 s; about 4 near the deadline) + the answer

_state = {"end": None, "tail": TAIL, "start": time.time(), "seconds": SECONDS, "steps": []}
_lock = threading.Lock()


def start(seconds=SECONDS):
    """Start the clock for one read; None means no deadline (--download)."""
    if seconds is not None:
        try:
            test = float(os.environ.get("READ_PAGE_TEST_DEADLINE") or 0)
        except ValueError:
            test = 0.0
        if test > 0:
            _state["tail"] = TAIL * test / SECONDS
            seconds = test
        else:
            _state["tail"] = TAIL
    _state["start"] = time.time()
    _state["seconds"] = seconds
    _state["steps"] = []
    _state["end"] = None if seconds is None else time.time() + seconds


def debug():
    return debuglog.enabled()


def ended(own, given):
    """How a step that ran out of time ended: its own fuse, or a cap the deadline had shortened."""
    return "deadline" if given is not None and own is not None and given < float(own) - 0.5 else "cap"


def record(name, t0, end="ok", own=None, given=None, note=""):
    """One finished step: name, start (s after the read began), seconds, its own cap, the cap it
    got, how it ended and a short note. Steps run in threads too, so the list is locked."""
    row = {"step": name, "at": round(t0 - _state["start"], 2), "s": round(time.time() - t0, 2), "end": end}
    if own is not None:
        row["own"] = round(float(own), 1)
    if given is not None:
        row["cap"] = round(float(given), 1)
    if note:
        row["note"] = str(note)[:160]
    with _lock:
        _state["steps"].append(row)
    debuglog.log("step", **row)
    return row


def steps():
    with _lock:
        return sorted(_state["steps"], key=lambda r: r["at"])


def summary():
    """The debug block of a manifest: the steps, the deadline and what was left of it."""
    return {"deadline": _state["seconds"], "elapsed": round(time.time() - _state["start"], 2),
            "left": None if _state["end"] is None else round(_state["end"] - time.time(), 2),
            "steps": steps()}


def tail():
    return _state["tail"]


def left(reserve=None):
    """Seconds before the deadline, less `reserve` (the tail by default); 1e9 with no deadline."""
    if _state["end"] is None:
        return 1e9
    return _state["end"] - (tail() if reserve is None else reserve) - time.time()


def cap(own, reserve=None, floor=0.0):
    """A step's seconds: its own cap, or less when the deadline is nearer."""
    return max(floor, min(float(own), left(reserve)))


def until(reserve=None):
    """The moment (time.time()) a step must end by; None with no deadline."""
    if _state["end"] is None:
        return None
    return _state["end"] - (tail() if reserve is None else reserve)


def active():
    return _state["end"] is not None


def unlimited():
    """A read started with no deadline (--download): a step whose cap is only there for the
    deadline's sake takes the time it needs."""
    return _state["seconds"] is None
