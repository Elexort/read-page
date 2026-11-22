"""Write the locks --setup installs from: scripts/setup-lock.txt (every Python package, for every OS at once),
scripts/defuddle-lock.json (defuddle and its npm packages) and scripts/tessdata-lock.txt (the OCR packs).

    python tools/setup_lock.py [UV]
    python tools/setup_lock.py --npm [NODE NPM-CLI]
    python tools/setup_lock.py --tessdata

The top-level packages and their versions are envsetup.TOP with PINS below - the versions the suites
were green with; uv resolves what lies beneath them for envsetup.PYTHON_VERSION, universal (one file
for Windows, macOS and Linux, environment markers where a package is one system's), wheels only, with the
SHA256 of every file of every pin (--generate-hashes: `uv pip install` checks them, in -r and in -c).
Run it after changing a pin, then the suites; commit the lock with the change. UV is the uv to use
(default: the one --setup installed, else uv on PATH).

--npm: defuddle envsetup.DEFUDDLE_VERSION and the packages it names, as npm resolves them as of
envsetup.DEFUDDLE_BEFORE, each with the SHA512 the registry publishes for it (`npm ci` holds every tarball to its
line). NODE and NPM-CLI default to the ones --setup installed. Run it after moving DEFUDDLE_VERSION.

--tessdata: the SHA256 and the size of every pack of tessdata_fast 4.1.0 - GitHub's listing of the tag, each pack
downloaded (339 MB) and hashed. The release is fixed, so this runs once; again only to check the file.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

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


def _get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "read-page-setup-lock"}),
                                  timeout=timeout)


def tessdata_lock():
    """scripts/tessdata-lock.txt from the release itself: GitHub's listing of tessdata_fast's tag 4.1.0 (each pack's
    size), every pack downloaded from where --setup fetches it, its size held to the listing's."""
    tree = json.load(_get("https://api.github.com/repos/tesseract-ocr/tessdata_fast/git/trees/4.1.0"))
    if tree.get("truncated"):
        sys.exit("GitHub cut the listing short")
    packs = sorted((e["path"][:-len(".traineddata")], e["size"]) for e in tree["tree"]
                   if e.get("type") == "blob" and e["path"].endswith(".traineddata"))
    rows = []
    for lang, size in packs:
        h, got = hashlib.sha256(), 0
        with _get(envsetup.TESSDATA_URL % lang, timeout=300) as r:
            for block in iter(lambda: r.read(1 << 20), b""):
                h.update(block)
                got += len(block)
        if got != size:
            sys.exit("%s: %d bytes, the listing says %d" % (lang, got, size))
        rows.append("%s %d %s" % (h.hexdigest(), size, lang))
        print("%-14s %9d %s" % (lang, size, h.hexdigest()))
    with open(envsetup.TESSDATA_LOCK, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# tessdata_fast 4.1.0 (github.com/tesseract-ocr/tessdata_fast, tag 4.1.0): the SHA256, the size and the\n"
                 "# name of every pack. tools/setup_lock.py --tessdata on dev writes it; --setup holds each download to its line.\n"
                 + "\n".join(rows) + "\n")
    print("%s: %d packs, %.1f MB" % (envsetup.TESSDATA_LOCK, len(rows), sum(s for _l, s in packs) / 1048576.0))


def npm_lock(argv):
    """scripts/defuddle-lock.json: npm's own lock (package-lock.json, lockfileVersion 3) of defuddle and its packages,
    resolved as of DEFUDDLE_BEFORE against registry.npmjs.org - with no settings file of the user's - by the Node and
    npm --setup installed."""
    if len(argv) >= 2:
        node, cli = argv[0], argv[1]
    else:
        d = ownenv.home()
        info = ownenv.load(d)
        node = ownenv.at(d, info.get("node_bin"))
        cli = ownenv.at(d, info.get("npm_cli")) or os.path.join(d, "node", "npm-" + envsetup.NPM_VERSION, "package",
                                                                 "bin", "npm-cli.js")
    if not (node and os.path.isfile(node) and os.path.isfile(cli)):
        sys.exit("no Node and npm of --setup's: give their paths")
    work = tempfile.mkdtemp(prefix="read-page-npm-lock-")
    try:
        with open(os.path.join(work, "package.json"), "w", encoding="utf-8") as fh:
            json.dump(envsetup.npm_package(), fh)
        for n in ("user.npmrc", "global.npmrc"):            # npm refuses one file for both
            open(os.path.join(work, n), "w").close()
        env = dict((k, v) for k, v in os.environ.items() if not k.lower().startswith("npm_config_"))
        env.update(npm_config_userconfig=os.path.join(work, "user.npmrc"),
                   npm_config_globalconfig=os.path.join(work, "global.npmrc"), npm_config_update_notifier="false")
        p = subprocess.run([node, cli, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund",
                            "--include=optional", "--registry=https://registry.npmjs.org/",
                            "--before=" + envsetup.DEFUDDLE_BEFORE, "--cache", os.path.join(work, "cache")],
                           cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            sys.exit(p.stderr or p.stdout)
        with open(os.path.join(work, "package-lock.json"), encoding="utf-8") as fh:
            lock = json.load(fh)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    pkgs = dict((k, v) for k, v in lock["packages"].items() if k)
    bad = [k for k, v in pkgs.items() if not (str(v.get("resolved", "")).startswith("https://registry.npmjs.org/")
                                              and str(v.get("integrity", "")).startswith("sha512-"))]
    if bad or pkgs.get("node_modules/defuddle", {}).get("version") != envsetup.DEFUDDLE_VERSION:
        sys.exit("not a lock of registry.npmjs.org's tarballs with their SHA512: %s" % bad[:3])
    with open(envsetup.NPM_LOCK, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(lock, fh, indent=1)
        fh.write("\n")
    print("%s: defuddle %s and %d packages, each with its SHA512" % (envsetup.NPM_LOCK, envsetup.DEFUDDLE_VERSION,
                                                                     len(pkgs) - 1))


def main(argv):
    if argv[:1] == ["--tessdata"]:
        return tessdata_lock()
    if argv[:1] == ["--npm"]:
        return npm_lock(argv[1:])
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
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
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
