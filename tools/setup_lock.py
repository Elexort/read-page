"""Write scripts/setup-lock.txt: every package --setup installs, pinned, for every OS at once.

    python tools/setup_lock.py [UV]

The top-level packages and their versions are envsetup.TOP with PINS below - the versions the suites
were green with; uv resolves what lies beneath them for envsetup.PYTHON_VERSION, universal (one file
for Windows, macOS and Linux, environment markers where a package is one system's), wheels only, with the
SHA256 of every file of every pin (--generate-hashes: `uv pip install` checks them, in -r and in -c).
Run it after changing a pin, then the suites; commit the lock with the change. UV is the uv to use
(default: the one --setup installed, else uv on PATH).
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import envsetup  # noqa: E402
import ownenv  # noqa: E402

# the versions the suites ran green with (pypandoc_binary left 2026-11-21). yt-dlp is not here: it
# is never pinned (envsetup.YTDLP)
PINS = {"curl_cffi": "0.17.0", "trafilatura": "2.2.0", "readability-lxml": "0.9", "lxml": "6.1.3",
        "lxml_html_clean": "0.4.5", "html2text": "2025.4.15", "pymupdf": "1.28.2", "pymupdf4llm": "1.28.2",
        "python-docx": "1.2.0", "openpyxl": "3.1.5", "python-pptx": "1.0.2", "pillow": "13.0.0",
        "psutil": "7.2.2", "youtube-transcript-api": "1.2.5", "playwright": "1.63.0",
        "tesserocr": "2.13.0"}


def main(argv):
    uv = argv[0] if argv else ""
    if not uv:
        mine = os.path.join(ownenv.home(), "uv", "uv-" + envsetup.UV_VERSION, "uv.exe" if os.name == "nt" else "uv")
        uv = mine if os.path.isfile(mine) else (shutil.which("uv") or "")
    if not uv:
        sys.exit("no uv: give its path")
    lines = []
    for top in envsetup.TOP:
        name = top.split("[")[0]
        if name not in PINS:
            sys.exit("no pin for %s" % name)
        lines.append("%s==%s" % (top, PINS[name]))
    fd, src = tempfile.mkstemp(suffix=".in")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    out = os.path.join(ROOT, "scripts", "setup-lock.txt")
    try:
        # --generate-hashes: every file of every pin, so the install checks content. The lock that
        # is there is the preferences: the versions stay what they are (uv keeps what an existing
        # output file pins) - a pin moves only through PINS, after the suites
        p = subprocess.run([uv, "pip", "compile", src, "--universal", "--python-version",
                            ".".join(envsetup.PYTHON_VERSION.split(".")[:2]), "--only-binary", ":all:",
                            "--no-header", "--no-annotate", "--generate-hashes", "-o", out],
                           capture_output=True, text=True)
    finally:
        os.unlink(src)
    if p.returncode != 0:
        sys.exit(p.stderr or p.stdout)
    with open(out, encoding="utf-8") as fh:
        body = fh.read()
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Every package `readpage.py --setup` installs, pinned (tools/setup_lock.py on dev writes it).\n"
                 + body)
    print("%s: %d packages, %d hashes" % (out, envsetup.lock_packages(body), body.count("--hash=sha256:")))


if __name__ == "__main__":
    main(sys.argv[1:])
