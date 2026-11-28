# read-page: notes for working on this repo

This file is for developing the skill. Agents that use it read `SKILL.md`; the engine is
`scripts/readpage.py` with its modules in `scripts/`; the details agents may need are in `references/`.

Notes about one maintainer's machine and way of working live in `CLAUDE.local.md`: it is
git-ignored, so a contributor may keep a file of their own under that name.

## Rules
- The skill serves any agent, OS and shell, weak models included. Nothing is tailored to one
  harness or to one machine.
- `SKILL.md` stays the procedure, about 1 500 tokens; details go to `references/`. It grows only where that is worth it.
- The skill installs nothing without the user's consent. Keys are the user's own.
- While the maintainer runs agent tests (headless agent sessions, weak models), `SKILL.md`,
  `references/` and `scripts/` stay as they are; the maintainer does not always announce a run, so
  ask when unsure.
- Measure before adopting a change. Fix a defect with a failing test first.
- Keep the documents current as you go, not at the end; a context compaction loses what is not
  written down. A change carries its docs in the same commit: `CHANGELOG.md` (Unreleased),
  `KNOWN-ISSUES.md` (a row, and the counts in `README.md`), test counts in `README.md`,
  `references/*` and `references/manifest-schema.json`.

## Tests
- Each suite: `python -X utf8 tests/<suite>.py` from the repo root; it ends with `N ok, M failed`.
  Run them with `PYTHONDONTWRITEBYTECODE=1` (Claude Code sets it; a plain terminal does not):
  the suites import the skill's modules, and a `__pycache__` beside them is listed to agents.
- Offline: reading sources blocks images speed mcp_parallel timeouts deadline formats statuses
  security contract props fixes channel office_fixtures docreaders mcp_smoke setup_audit
  environment cjk. Live: browser_live, sources_live.
- On a machine where `readpage.py --setup` has run, every suite that starts `readpage.py` or the
  MCP server as a process tests the environment's engines (they go under its Python by
  themselves); in-process checks use the Python the suite runs in. `READ_PAGE_SKIP=env` runs a
  suite without it; CI has none.
- Agent tests under a harness's cut: `READ_PAGE_TEST_CUT` (`middle:8000` Cline, `head:16384` Zed, `tail:51200`
  OpenCode, `file:30000` Claude Code) makes the skill cut its own answer, CLI and MCP alike, the way that harness
  would (`references/answer.md`, For testing the skill). The contract suite runs an answer's `next:` command in
  every shell the machine has (cmd, bash or sh, PowerShell 5.1 and 7): one check a shell.
- `tests/cjk.py` is the Chinese, Japanese, Korean and Russian suite (encodings, raw non-ASCII addresses and file
  names, the MCP server's stdin, OCR packs, the languages sent, a Chinese home and cache). On Windows a copy of
  `python.exe` whose application manifest says `<activeCodePage>zh-CN</activeCodePage>` (UpdateResourceW,
  RT_MANIFEST 24, id 1; `zh-TW` is 950, `ja-JP` 932, `ko-KR` 949) has the ANSI code page 936 for that process:
  run the suites with it, `READ_PAGE_SKIP=env`, no `PYTHONUTF8`, and `TEMP` in a Chinese folder, in the core
  shape (`PYTHONNOUSERSITE=1`) and with the engines on the path; `fixes`, `deadline` and `cjk` are the ones that
  need it. `scripts/intl.py` holds the decoding, the IRI-to-URI step and the user's languages.
- While working, run the suites a change touches; before a commit, all of them (about 13 minutes).
- Binary fixtures go in `tests/ocr/` (small 1-bit PNGs cut from public-domain scans, for the real-tesserocr checks of
  `tests/environment.py`); `tests/fixtures/` is git-ignored (the offline corpus's pages belong to their sites).
- Lint as CI does: `python -m ruff check --no-cache --select F scripts tests tools` (no `.ruff_cache` in
  the skill's folder) and
  `uvx vermin --target=3.8- --violations --no-tips --eval-annotations scripts tests tools`.
- CI: `tests.yml` on every push (Ubuntu with Python 3.9 and 3.12, Windows, a browser job, lint);
  `macos.yml` on every push to dev (macOS 15, arm64), or by hand from the Actions tab.
  Every suite runs even when an earlier one failed, so read all of a red run.
  `install.yml` (pushes to dev and ci-install, and by hand) is the real install: `--setup` into a
  folder with a space and Cyrillic in its path, the suites under the environment's Python, then a user's
  clone-and-read (and README's ZIP), a bare Python, containers (Alpine, Ubuntu 20.04 and 24.04, Debian 11, Rocky 8,
  Fedora, Arch, openSUSE), a proxy that inspects TLS (`tools/ci_proxy.py`: mitmproxy, its root in the OS's store),
  a Windows whose Python has the code page 936 or 950 in a profile named in Chinese (`tools/ci_acp.py`: an
  application manifest with `activeCodePage`, asserted by `GetACP()`), and the suites under `LC_ALL=zh_CN.GBK` (none
  told `-X utf8`, then `tests/cjk.py` once more told so: what it writes is UTF-8 bytes in a GBK world), on
  every free runner (Linux, Windows, macOS; x64 and arm64). `tools/ci_install.py` is what the jobs run; a matrix
  row's `expect` lists what its platform lacks for want of wheels (a floor), and any other gap is red.
  `tools/ci_proxy.py`, `tools/ci_acp.py` and `tools/ci_container.sh` change the machine they run on (a trusted root
  certificate, patched copies of programs, the package sources): off GitHub Actions they refuse unless given
  `--on-this-machine` (the container script runs in a container alone), and `ci_proxy.py stop` and
  `ci_acp.py restore` undo what they did. A run takes
  about 45 minutes (the suites); a read of a failed job: `gh run view <id> --log-failed` (once the whole run is
  done; `gh api --allow-escape-sequences repos/<owner>/<repo>/actions/jobs/<id>/logs` for a finished job of a
  run still going), or the artifacts `install-logs-*` (setup.log, setup-detail.log, setup.json, each suite's log).
  A suite never assumes an ASCII temp folder or a UTF-8 console: `text=True` always has an `encoding`, and a check
  that is about an ASCII path makes one (`ascii_base()` in `tests/environment.py`).
  The workflows live on dev only (`main` is the skill alone): `gh workflow run <file> --ref <branch>` works
  from a branch that has the file, though the default branch has no workflow.
- Bugs that belong to one OS (sockets and processes on Linux, paths and subprocesses on Windows)
  show only there: CI's Ubuntu and Windows jobs, and its oldest Python (3.9), are the check.

## Workflow
- Two branches. `dev` is the development branch: the code, tests, CI, notes; work and commit
  here. `main` is the skill alone - what a clone or a ZIP installs, and what the installed copy in
  the skills folder is (a clone of main). Never commit to main by hand:
  `python tools/publish.py --push --install <skills folder>/read-page` copies SKILL.md, README.md,
  scripts/, references/, LICENSE and .gitattributes there, from dev's committed HEAD. Run it in a
  dev working copy with a clean tree. Publish after every change: the suites green first, and not
  on top of an agent test the maintainer said is running.
- `--setup`'s versions are pinned: `scripts/envsetup.py` (uv, Python, Node, defuddle, tessdata),
  `tools/setup_lock.py` (the Python packages; it writes `scripts/setup-lock.txt` with the SHA256 of
  every file - the versions stay what the lock has until `PINS` moves them; `--npm` writes
  `scripts/defuddle-lock.json`, npm's lock of defuddle's tree as of `DEFUDDLE_BEFORE`, after
  `DEFUDDLE_VERSION` moves; `--tessdata` wrote `scripts/tessdata-lock.txt`, every pack of the fixed release).
  uv's wheel, Node's archive and PyPI's Node wheel are pinned by SHA256 too (`UV_WHEEL_SHA256`,
  `NODE_SHA256`, `NODE_WHEEL_SHA256`): they move with `UV_VERSION`, `NODE_VERSION` and `NODE_WHEEL`, copied from
  PyPI's JSON and nodejs.org's `SHASUMS256.txt` (`tests/environment.py` compares every pin with its source when
  online). A pin moves only after the suites ran green with it. What one layout model process takes
  (`TABLES_PROC_RAM`, `TABLES_PROC_COMMIT` in readpage.py: a read counts from them how many it starts) was measured
  with the onnxruntime, pymupdf4llm and pymupdf-layout of the lock (`TABLES_PROC_MEASURED`; Linux's commit by a process's
  VmData, in a Linux environment of the lock's): when one of those pins
  moves, measure the figures again and move their versions (`tests/environment.py` fails until then). yt-dlp
  alone is not pinned: the newest release that has been out three days, never older than the one
  installed (`YTDLP_FLOATS` is what floats with it). No source of `--setup` is used in plain http
  (`READ_PAGE_ALLOW_HTTP` names an intranet host that may be).
- A packaged Windows app (MSIX; Claude's desktop app is one) gets a private copy of whatever its
  processes write under `AppData\Local` or `AppData\Roaming`
  (`AppData\Local\Packages\<app>\LocalCache\`): no other program sees it. `AppData\Local\Temp`
  and the home folder are shared. To find out whether another program sees a file, look from
  outside the app, never from inside it.
- On Windows, stopping a background test run leaves its children alive: kill the tree with
  `taskkill /T /PID <pid> /F` before starting another run.

## Versions
- The version strings (SKILL.md's metadata and date, `readpage.VERSION`, `mcp_server.SERVER_VERSION`, README) move only
  when a version is pinned; until then CHANGELOG's "Unreleased" section gathers the changes, each in its own commit.
- A version is pinned once: every suite and CI's whole matrix are green on the candidate; the acceptance bench has
  run; the maintainer has tested the harnesses; and a stress round of a small model has run - several agents (Haiku),
  each on a different research question made up for that round, finding sources by web search and reading them only
  with the skill, each then answering a questionnaire on how the skill served it (what was missing, where it erred,
  whether a text looked whole or cut, which advice it followed, what else would help). The round's questions and
  procedure live outside the repository; its findings become KNOWN-ISSUES rows or changes, measured first.
- A tag, a GitHub Release or an announcement only on the maintainer's word; the first release that is announced is
  meant for 1.0.0.
