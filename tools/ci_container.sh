#!/bin/sh
# Runs inside a container of install.yml: a bare Linux that has only what a minimal image has.
#   sh ci_container.sh <image> <commit>
# It adds Python and git (nothing else, no browser libraries), installs the skill as README tells a
# user (git clone), runs `--setup`, and checks that whatever it could not do is named, with a fix.
# POSIX sh: Alpine has no bash. The repository is mounted at /src (read-only) for tools/ci_install.py.
img="$1"
sha="$2"
case "$img" in
  alpine*) apk add --no-cache python3 git >/dev/null || exit 1 ;;
  *) export DEBIAN_FRONTEND=noninteractive
     apt-get update -qq >/dev/null && apt-get install -y -qq python3 git >/dev/null || exit 1 ;;
esac
skill="$HOME/.agents/skills/read-page"
git clone -q https://github.com/Elexort/read-page "$skill" || exit 1
git -C "$skill" checkout -q "$sha" || exit 1       # the commit being tested, as a user's clone of it
ci="python3 -X utf8 /src/tools/ci_install.py"
rc=0
$ci machine || rc=1
$ci setup --follow --skill "$skill" --label first || rc=1
$ci check --skill "$skill" || rc=1
$ci read --skill "$skill" || rc=1
$ci collect --skill "$skill"
$ci summary --title "container $img"
exit $rc
