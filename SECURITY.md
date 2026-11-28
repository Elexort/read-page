# Security policy

## Reporting a vulnerability

Report it privately, not in an issue or a pull request: private vulnerability reporting is on for this
repository. Open the repository's **Security** tab, choose **Report a vulnerability**, and say what you
found, how to reproduce it (the command, the page or file, the platform and the version from
`readpage.py --version`) and what it lets an attacker do. The report is seen by the maintainer alone until a fix
is ready; the discussion stays on it.

## What is in scope

The skill itself, as `main` ships it:

- **The scripts** (`scripts/`): what `readpage.py` and the MCP server do with a page, a file or an address they
  are given - a way to make a read reach an internal address (the checks of every hop, `netguard`'s guard of the
  browser), to write outside the page's folder, to run a command, to read a file the call did not name, or to
  hang or exhaust the machine past the limits `references/answer.md` states.
- **`--setup`**: what it fetches, from where, and how it holds it - a download not pinned to its hash where it
  should be, a source that is not checked, a file placed outside the folder it names, a step that runs with more
  rights than it asks.

## What is not

- The engines `--setup` fetches (PyMuPDF, Playwright, defuddle, yt-dlp, Node and the rest) and the sites the
  skill reads: report a flaw in them to their own projects. A way the skill makes it worse is in scope.
- Text a page carries to the agent that reads it (a page that says "ignore your instructions"): the skill returns
  what the page says, and an agent has to treat it as data.
- A machine the attacker already controls, or a key or a path the user gave the skill on purpose.

## Versions

A fix goes into the newest version, published as `main`; older ones are not patched.
