"""The memory free now, for the tables step's model processes (KNOWN-ISSUES 242): the standard library alone.

free_memory() -> {"phys": bytes of physical memory free (Windows' available physical, Linux MemAvailable, macOS's
free and inactive pages), "commit": bytes of commit left or None (Windows: the commit limit - RAM and the pagefile as
it is now - less the commit charge; Linux under vm.overcommit_memory = 2: CommitLimit less Committed_AS), "room":
bytes left under a limit of the read's own or None (a Windows job's memory limit less its use, a Linux cgroup's)}.
READ_PAGE_TEST_MEMORY (a JSON object of those keys, in bytes) stands in for them, with "fake": true - figures that
do not fall as processes take memory, so the caller subtracts its processes itself: the suites and the measurements
never squeeze a machine's memory to see the rule work. alive(pid) tells whether a process still runs.

cgroup_room() and cgroup_cpus(): a Linux cgroup's memory room and CPU quota, each the smallest from the read's cgroup
up to the root (KNOWN-ISSUES 284, 285). READ_PAGE_TEST_CGROUP names a folder that stands for / (proc/self/cgroup and
sys/fs/cgroup in it): the suites point both at a faked cgroup on any OS, and free_memory() takes its room there too.
"""
import json
import os
import sys


def _test_figures():
    raw = os.environ.get("READ_PAGE_TEST_MEMORY")
    if not raw:
        return None
    try:
        got = json.loads(raw)
        out = {k: (int(got[k]) if got.get(k) is not None else None) for k in ("phys", "commit", "room")}
        out["fake"] = True           # figures that do not fall as processes take memory: the caller counts them
        return out
    except (ValueError, TypeError, AttributeError):
        return None


def free_memory():
    fake = _test_figures()
    if fake is not None:
        return fake
    try:
        if os.name == "nt":
            got = _windows()
        elif sys.platform == "darwin":
            got = _macos()
        else:
            return _linux()
        if os.environ.get("READ_PAGE_TEST_CGROUP"):            # (a faked cgroup counts on any OS: the suites)
            room = cgroup_room()
            if room is not None:
                got["room"] = room if got.get("room") is None else min(got["room"], room)
        return got
    except Exception:                                          # noqa: BLE001 - no figure is no rule: one process
        return {"phys": None, "commit": None, "room": None}


def _windows():
    import ctypes
    from ctypes import wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(st)
    if not k32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return {"phys": None, "commit": None, "room": None}
    # ullAvailPageFile: the commit limit less the commit charge - what every program on the machine may still
    # reserve before allocations fail; the pagefile counts as it is now, never as it might grow
    return {"phys": int(st.ullAvailPhys), "commit": int(st.ullAvailPageFile), "room": _windows_job(k32)}


def _windows_job(k32):
    """The room left under the memory limit of a job the read runs in, None without one."""
    import ctypes
    from ctypes import wintypes

    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    inside = wintypes.BOOL(False)
    if not k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(inside)) or not inside.value:
        return None

    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class USAGE(ctypes.Structure):
        _fields_ = [("JobMemory", ctypes.c_ulonglong), ("PeakJobMemoryUsed", ctypes.c_ulonglong)]
    k32.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD))
    lim = EXTENDED()
    if not k32.QueryInformationJobObject(None, 9, ctypes.byref(lim), ctypes.sizeof(lim), None):
        return None
    if not lim.Basic.LimitFlags & 0x200 or not lim.JobMemoryLimit:       # JOB_OBJECT_LIMIT_JOB_MEMORY
        return None
    use = USAGE()
    if not k32.QueryInformationJobObject(None, 28, ctypes.byref(use), ctypes.sizeof(use), None):   # memory usage
        return None
    return max(0, int(lim.JobMemoryLimit) - int(use.JobMemory))


def _meminfo():
    out = {}
    with open("/proc/meminfo", encoding="ascii", errors="replace") as fh:
        for line in fh:
            name, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                out[name.strip()] = int(parts[0]) * 1024
    return out


def _linux():
    mi = _meminfo()
    phys = mi.get("MemAvailable", mi.get("MemFree"))
    commit = None
    try:
        with open("/proc/sys/vm/overcommit_memory", encoding="ascii") as fh:
            if fh.read().strip() == "2" and "CommitLimit" in mi and "Committed_AS" in mi:
                commit = max(0, mi["CommitLimit"] - mi["Committed_AS"])
    except OSError:
        pass
    return {"phys": phys, "commit": commit, "room": cgroup_room()}


def _read_int(path):
    try:
        with open(path, encoding="ascii") as fh:
            v = fh.read().strip()
        return None if v in ("", "max") else int(v)
    except (OSError, ValueError):
        return None


def cgroup_root():
    """The folder that stands for / in a cgroup's files: READ_PAGE_TEST_CGROUP (the suites, any OS), else / on
    Linux, None elsewhere."""
    fake = os.environ.get("READ_PAGE_TEST_CGROUP")
    if fake:
        return fake
    return "/" if sys.platform.startswith("linux") else None


def _cgroup_dirs(root, controller):
    """The folders of the read's cgroup and of every cgroup above it, its own first, where `controller`'s files
    may be: v2's hierarchy (a line 0::PATH) and v1's mount of the controller (N:CONTROLLERS:PATH). A container
    without a cgroup namespace of its own names its cgroup by the host's path (/docker/<id>), which is not under
    the container's mount - that mount is its cgroup -: the folders that are not there are passed over, and the
    mount's root is the last. A limit set on a parent (a pod's) is in a folder above."""
    try:
        with open(os.path.join(root, "proc", "self", "cgroup"), encoding="utf-8", errors="replace") as fh:
            lines = [ln.strip().split(":", 2) for ln in fh if ln.strip()]
    except OSError:
        return []
    base = os.path.join(root, "sys", "fs", "cgroup")
    dirs = []
    for parts in lines:
        if len(parts) != 3:
            continue
        names = [n for n in parts[1].split(",") if n]
        if parts[0] == "0" and not names:                                            # v2
            mount = base
        elif controller in names:                                                    # v1
            mount = next((m for m in (os.path.join(base, parts[1]), os.path.join(base, controller))
                          if os.path.isdir(m)), None)
            if mount is None:
                continue
        else:
            continue
        steps = [s for s in parts[2].split("/") if s and s not in (".", "..")]
        for k in range(len(steps), -1, -1):
            d = os.path.join(mount, *steps[:k])
            if os.path.isdir(d) and d not in dirs:
                dirs.append(d)
    return dirs


def cgroup_room(root=None):
    """The room under the memory limits of the read's cgroup and every cgroup above it - v2 memory.max less
    memory.current, v1 memory.limit_in_bytes less memory.usage_in_bytes -, the smallest; None without a limit:
    a container's /proc/meminfo shows the host's memory. It read the read's own cgroup's file alone, at the path
    /proc/self/cgroup names: a v1 container without its own cgroup namespace, or a pod's limit, was not seen
    (KNOWN-ISSUES 285)."""
    root = root or cgroup_root()
    if not root:
        return None
    best = None
    for d in _cgroup_dirs(root, "memory"):
        for limit_name, used_name in (("memory.max", "memory.current"),
                                      ("memory.limit_in_bytes", "memory.usage_in_bytes")):
            limit, used = _read_int(os.path.join(d, limit_name)), _read_int(os.path.join(d, used_name))
            if limit is not None and used is not None and limit < (1 << 60):     # v1 has no "max": a huge number
                room = max(0, limit - used)
                best = room if best is None else min(best, room)
    return best


def cgroup_cpus(root=None):
    """The CPUs the CPU quotas of the read's cgroup and every cgroup above it give - v2 cpu.max "QUOTA PERIOD",
    v1 cpu.cfs_quota_us over cpu.cfs_period_us -, rounded up, the smallest; None without a quota: the affinity
    of a container given two CPUs of 32 shows 32 (KNOWN-ISSUES 284)."""
    root = root or cgroup_root()
    if not root:
        return None
    best = None
    for d in _cgroup_dirs(root, "cpu"):
        quota = period = None
        try:
            with open(os.path.join(d, "cpu.max"), encoding="ascii") as fh:
                f = fh.read().split()
            if f and f[0] != "max":
                quota, period = int(f[0]), int(f[1]) if len(f) > 1 else 100000
        except (OSError, ValueError):
            pass
        if quota is None:
            quota = _read_int(os.path.join(d, "cpu.cfs_quota_us"))
            period = _read_int(os.path.join(d, "cpu.cfs_period_us"))
        if quota and period and quota > 0 and period > 0:
            n = max(1, -(-quota // period))                     # rounded up
            best = n if best is None else min(best, n)
    return best


def _macos():
    import subprocess
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=5).stdout
    size, pages = 4096, {}
    for line in out.splitlines():
        if "page size of" in line:
            digits = [w for w in line.split() if w.isdigit()]
            if digits:
                size = int(digits[0])
        name, _, rest = line.partition(":")
        v = rest.strip().rstrip(".")
        if v.isdigit():
            pages[name.strip()] = int(v)
    free = pages.get("Pages free", 0) + pages.get("Pages inactive", 0) + pages.get("Pages speculative", 0)
    return {"phys": free * size, "commit": None, "room": None}


def alive(pid):
    """Does process `pid` still run?"""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x1000, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5                 # access denied: it is there
        try:
            code = wintypes.DWORD()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
