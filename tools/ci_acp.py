"""A Windows process with another ANSI code page, for the "Chinese user on Windows" job of install.yml.

    python tools/ci_acp.py copy LOCALE SRC.exe DST.exe   a copy of a program whose manifest asks for LOCALE's code page
    python tools/ci_acp.py patch LOCALE FILE.exe ...     the same, in place (a program that is not running)
    python tools/ci_acp.py python LOCALE                 the running Python's copy `python-acp.exe` beside it, asserted,
                                                         exported as ACPY (and Git's curl.exe, patched, first on PATH)
    python tools/ci_acp.py env-python LOCALE             the environment's own Python (what --setup built), in place
    python tools/ci_acp.py assert LOCALE PROGRAM...      each program's GetACP() must be LOCALE's, or the job fails
    python tools/ci_acp.py profile LOCALE                a user profile named in that language, for the steps after it
    python tools/ci_acp.py restore                       the runner's own profile again (before the logs are uploaded)
    python tools/ci_acp.py encoding NAME                 (any OS) this Python's preferred encoding must be NAME
    python tools/ci_acp.py show                          what a process here sees: code pages, encodings, folders

A Windows application manifest may say `<activeCodePage>zh-CN</activeCodePage>`: that one process then runs with
the ANSI code page 936 - `GetACP()`, the encoding of every narrow (`*A`) Win32 call, Python's
`locale.getpreferredencoding()` (cp936) and the encoding of its pipes (gbk) - without a reboot or a change to the
machine, which is what a Chinese Windows gives a Python started without `-X utf8`. It has been run for zh-CN 936, zh-TW 950, ja-JP 932, ko-KR 949 and ru-RU 1251 on one Windows 11 build; on any other the first
thing a job does is `assert`, and a manifest that did nothing must never be a green job.

What it does not change: the system locale, `GetOEMCP` and the console's code page, the UI language, the date
formats, the keyboard, a process nobody patched (uv, Node, npm and a user's own tools keep 1252: they take UTF-8 or
wide characters), and no console is attached to a runner's pipes (the `WriteConsoleW` path is not exercised).

Stdlib only, Python 3.8+. Letters outside ASCII are built from code points, so that no editor, shell or encoding
can change them.
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# locale -> (its ANSI code page, a user's folder name with a space, Chinese-script letters of that code page and a
# character whose trailing byte is 0x5C - a backslash to any code that splits a narrow path on bytes)
CP = {"zh-CN": 936, "zh-TW": 950, "zh-HK": 950, "ja-JP": 932, "ko-KR": 949, "ru-RU": 1251}
PROFILE = {
    # 许可乗 + space + 用户  (乗 is 0x8F5C in GBK)
    "zh-CN": (0x8BB8, 0x53EF, 0x4E57, 0x20, 0x7528, 0x6237),
    # 許功蓋 + space + 用戶  (許 is 0xB35C, 功 0xA55C in Big5)
    "zh-TW": (0x8A31, 0x529F, 0x84CB, 0x20, 0x7528, 0x6236),
    "zh-HK": (0x8A31, 0x529F, 0x84CB, 0x20, 0x7528, 0x6236),
    "ja-JP": (0x30E6, 0x30FC, 0x30B6, 0x30FC, 0x20, 0x30C6, 0x30B9, 0x30C8),
    "ko-KR": (0xC0AC, 0xC6A9, 0xC790, 0x20, 0xD14C, 0xC2A4, 0xD2B8),
    "ru-RU": (0x418, 0x432, 0x430, 0x43D, 0x20, 0x422, 0x435, 0x441, 0x442),
}
MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">%s</activeCodePage>
    </windowsSettings>
  </application>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
    </application>
  </compatibility>
</assembly>"""
ENV_NAMES = ("USERPROFILE", "HOME", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA")
SAVED = "CI_ACP_SAVED_"                       # the runner's own value of each, kept for `restore`


def profile_name(locale):
    return "".join(chr(c) for c in PROFILE[locale])


def set_manifest(path, locale):
    """Replace the application manifest (RT_MANIFEST, id 1) of a program that is not running."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.BeginUpdateResourceW.restype = wintypes.HANDLE
    k.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p,
                                  wintypes.DWORD]
    k.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    h = k.BeginUpdateResourceW(path, False)
    if not h:
        raise OSError("cannot open %s for resources (error %d)" % (path, ctypes.get_last_error()))
    data = (MANIFEST % locale).encode("utf-8")
    buf = ctypes.create_string_buffer(data, len(data))
    if not k.UpdateResourceW(h, ctypes.c_void_p(24), ctypes.c_void_p(1), 0, buf, len(data)):
        err = ctypes.get_last_error()
        k.EndUpdateResourceW(h, True)
        raise OSError("cannot write the manifest of %s (error %d)" % (path, err))
    if not k.EndUpdateResourceW(h, False):
        raise OSError("cannot save %s (error %d)" % (path, ctypes.get_last_error()))


def acp_of(program):
    """GetACP() of a Python (a program that takes -c) or of any other: through a Python it is asked of."""
    code = "import ctypes;print(ctypes.windll.kernel32.GetACP())"
    p = subprocess.run([program, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    out = p.stdout.decode("ascii", "replace").strip()
    return int(out) if out.isdigit() else None


def cmd_copy(a):
    shutil.copyfile(a.src, a.dst)
    set_manifest(a.dst, a.locale)
    print("%s -> %s (activeCodePage %s)" % (a.src, a.dst, a.locale))
    return 0


def cmd_patch(a):
    for f in a.files:
        set_manifest(f, a.locale)
        print("%s: activeCodePage %s" % (f, a.locale))
    return 0


def cmd_assert(a):
    want = CP[a.locale]
    bad = []
    for prog in a.programs:
        got = acp_of(prog)
        print("%-70s GetACP() = %s" % (prog, got))
        if got != want:
            bad.append("%s: GetACP() is %s, not %d" % (prog, got, want))
    for b in bad:
        print("FAIL: " + b)
    if bad:
        print("FAIL: the manifest did nothing here (an older Windows ignores activeCodePage): this job would test "
              "nothing, so it stops")
    return 1 if bad else 0


def export(name, value):
    path = os.environ.get("GITHUB_ENV")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s=%s\n" % (name, value))


GIT_CURL = r"C:\Program Files\Git\mingw64\bin\curl.exe"        # takes its arguments in the ANSI code page


def cmd_python(a):
    """The Python of the job, copied beside itself as python-acp.exe (a running program cannot be re-manifested; its
    copy finds the same DLLs and standard library), patched and asserted; Git's curl.exe patched in place and put
    first on PATH (System32's curl takes wide characters; Git's takes the ANSI code page, which is the one that can
    fail on a Chinese path)."""
    dst = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "python-acp.exe")
    shutil.copyfile(sys.executable, dst)
    set_manifest(dst, a.locale)
    print("%s -> %s (activeCodePage %s)" % (sys.executable, dst, a.locale))
    if os.path.isfile(GIT_CURL):
        set_manifest(GIT_CURL, a.locale)
        print("%s: activeCodePage %s" % (GIT_CURL, a.locale))
        path = os.environ.get("GITHUB_PATH")
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(os.path.dirname(GIT_CURL) + "\n")
    else:
        print("no Git curl.exe at %s: the ANSI curl is not tried here" % GIT_CURL)
    export("ACPY", dst.replace("\\", "/"))
    return cmd_assert(argparse.Namespace(locale=a.locale, programs=[dst]))


def cmd_env_python(a):
    """The Python --setup built (the one a read goes into, behind the venv's launcher), patched in place: the
    reads and the suites then run in the code page a Chinese user's environment has."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
    sys.dont_write_bytecode = True
    import ownenv
    home = ownenv.home()
    pys = os.path.join(home, "python")
    found = [os.path.join(pys, n, "python.exe") for n in (sorted(os.listdir(pys)) if os.path.isdir(pys) else [])
             if os.path.isfile(os.path.join(pys, n, "python.exe")) and not os.path.islink(os.path.join(pys, n))]
    if not found:
        print("FAIL: no Python of the environment under %s" % pys)
        return 1
    for exe in found:
        set_manifest(exe, a.locale)
        print("%s: activeCodePage %s" % (exe, a.locale))
    info = ownenv.load(home)
    venv_py = ownenv.at(home, info.get("python")) if info.get("python") else ""
    return cmd_assert(argparse.Namespace(locale=a.locale, programs=found + ([venv_py] if venv_py else [])))


def cmd_profile(a):
    base = os.environ.get("SystemDrive", "C:") + os.sep + "Users"
    home = os.path.join(base, profile_name(a.locale))
    paths = {"USERPROFILE": home, "HOME": home, "LOCALAPPDATA": os.path.join(home, "AppData", "Local"),
             "APPDATA": os.path.join(home, "AppData", "Roaming"), "TEMP": os.path.join(home, "AppData", "Local", "Temp")}
    paths["TMP"] = paths["TEMP"]
    for p in paths.values():
        os.makedirs(p, exist_ok=True)
    for k in ENV_NAMES:
        export(SAVED + k, os.environ.get(k, ""))             # for `restore`
        export(k, paths[k])
    export("CI_ACP_LOCALE", a.locale)
    # PYTHONUTF8 and PYTHONIOENCODING stay unset, and a driver is given no -X utf8: a Chinese user's Python has none
    print("profile: %s" % home)
    return 0


def cmd_restore(a):
    for k in ENV_NAMES:
        v = os.environ.get(SAVED + k)
        if v:
            export(k, v)
    return 0


def cmd_encoding(a):
    """The twin on Linux: `LC_ALL=zh_CN.GBK PYTHONUTF8=0` must give a Python the encoding the job is about."""
    import codecs
    import locale
    got = locale.getpreferredencoding(False)
    ok = codecs.lookup(got).name == codecs.lookup(a.name).name and not sys.flags.utf8_mode
    print("preferred encoding %s, stdout %s, utf8 mode %s (wanted %s)" % (got, sys.stdout.encoding, sys.flags.utf8_mode,
                                                                          a.name))
    if not ok:
        print("FAIL: this Python is not running in %s: the locale is missing, or its UTF-8 mode is on" % a.name)
    return 0 if ok else 1


def cmd_show(a):
    import locale
    out = sys.stdout.encoding
    print("python           %s" % sys.executable)
    if os.name == "nt":
        import ctypes
        print("GetACP           %d" % ctypes.windll.kernel32.GetACP())
        print("GetOEMCP         %d" % ctypes.windll.kernel32.GetOEMCP())
    print("preferred enc.   %s" % locale.getpreferredencoding(False))
    print("stdout encoding  %s" % out)
    print("filesystem enc.  %s" % sys.getfilesystemencoding())
    print("utf8 mode        %s" % sys.flags.utf8_mode)
    for k in ENV_NAMES + ("PYTHONUTF8", "PYTHONIOENCODING", "READ_PAGE_HOME", "READ_PAGE_CACHE"):
        v = os.environ.get(k)
        print("%-16s %s" % (k, "(unset)" if v is None else v.encode("unicode_escape").decode("ascii")))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("copy")
    p.set_defaults(fn=cmd_copy)
    p.add_argument("locale", choices=sorted(CP))
    p.add_argument("src")
    p.add_argument("dst")
    p = sub.add_parser("python")
    p.set_defaults(fn=cmd_python)
    p.add_argument("locale", choices=sorted(CP))
    p = sub.add_parser("env-python")
    p.set_defaults(fn=cmd_env_python)
    p.add_argument("locale", choices=sorted(CP))
    p = sub.add_parser("patch")
    p.set_defaults(fn=cmd_patch)
    p.add_argument("locale", choices=sorted(CP))
    p.add_argument("files", nargs="+")
    p = sub.add_parser("assert")
    p.set_defaults(fn=cmd_assert)
    p.add_argument("locale", choices=sorted(CP))
    p.add_argument("programs", nargs="+")
    p = sub.add_parser("profile")
    p.set_defaults(fn=cmd_profile)
    p.add_argument("locale", choices=sorted(PROFILE))
    p = sub.add_parser("encoding")
    p.set_defaults(fn=cmd_encoding)
    p.add_argument("name")
    sub.add_parser("restore").set_defaults(fn=cmd_restore)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")          # a name outside the code page must not end the tool
    except (AttributeError, ValueError):
        pass
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
