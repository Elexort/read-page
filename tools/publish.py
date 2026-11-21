"""Publish the skill: `main` gets what an agent needs, from `dev`, and nothing else.

    python tools/publish.py [--push] [--install DIR]

Run in the dev working copy, on a clean tree, on branch `dev`. The skill is SKILL.md, README.md
(the full one: GitHub draws main's front page from it, and a harness lists a file by its name,
not its text), scripts/, references/, LICENSE and .gitattributes - the files git tracks there,
never a cache or a local leftover. main gets one commit (none when nothing changed),
named after dev's HEAD, its Co-Authored-By lines kept. --push sends it to origin; --install DIR
then pulls main into an installed copy (a clone of main, such as ~/.agents/skills/read-page).

Why a branch of its own: an install is a clone or a ZIP of the default branch, and some harnesses
show the agent every file of a skill's folder, hundreds of them - tests, CI and notes are not the
agent's business.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = ["SKILL.md", "README.md", "LICENSE", ".gitattributes", "scripts", "references"]


def git(*args, cwd=ROOT):
    p = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        sys.exit("git %s: %s" % (" ".join(args), (p.stderr or p.stdout).strip()))
    return p.stdout.strip()


def main(argv):
    push = "--push" in argv
    install = argv[argv.index("--install") + 1] if "--install" in argv else ""
    if git("rev-parse", "--abbrev-ref", "HEAD") != "dev":
        sys.exit("publish from dev")
    if git("status", "--porcelain"):
        sys.exit("dev has changes that are not committed: commit them first")
    head = git("rev-parse", "--short", "HEAD")
    body = git("log", "-1", "--format=%B")
    subject = body.splitlines()[0] if body else head
    trailers = [ln for ln in body.splitlines() if ln.lower().startswith("co-authored-by:")]
    files = git("ls-files", "--", *SKILL).splitlines()
    git("fetch", "-q", "origin", "main")
    tree = tempfile.mkdtemp(prefix="read-page-main-")
    os.rmdir(tree)
    git("worktree", "add", "-q", "-B", "main", tree, "origin/main")
    try:
        for name in os.listdir(tree):                 # the old skill goes; .git is the worktree's link
            if name != ".git":
                path = os.path.join(tree, name)
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        for rel in files:
            dst = os.path.join(tree, rel)
            os.makedirs(os.path.dirname(dst) or tree, exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, rel), dst)
        git("add", "-A", cwd=tree)
        if not git("status", "--porcelain", cwd=tree):
            print("main already has dev %s's skill" % head)
        else:
            message = "%s\n\nThe skill from dev %s.\n" % (subject, head)
            if trailers:
                message += "\n" + "\n".join(trailers) + "\n"
            git("commit", "-q", "-m", message, cwd=tree)
            print("main: %s (%d files)" % (git("log", "-1", "--format=%h %s", cwd=tree), len(files)))
            if push:
                git("push", "-q", "origin", "main", cwd=tree)
                print("pushed")
    finally:
        git("worktree", "remove", "--force", tree)
    if install:
        print(git("-C", install, "pull", "-q", "--ff-only", "origin", "main") or "installed copy updated: %s" % install)


if __name__ == "__main__":
    main(sys.argv[1:])
