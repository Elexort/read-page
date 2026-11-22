#!/bin/sh
# Runs inside a container of install.yml: a bare Linux that has only what a minimal image has.
#   sh ci_container.sh <image> <commit>
# It adds Python and git (nothing else, no browser libraries), installs the skill as README tells a
# user (git clone), runs `--setup`, and checks that whatever it could not do is named, with a fix.
# POSIX sh: Alpine has no bash. The repository is mounted at /src (read-only) for tools/ci_install.py.
# The images are the package managers and the glibc ages a user has: apk (musl), apt (Debian 11 and Ubuntu 20.04
# have glibc 2.31 and Python 3.9 / 3.8), dnf, pacman, zypper.
img="$1"
sha="$2"
py=python3
# it rewrites the package manager's sources (Debian 11's), installs packages as root, clones into $HOME: a container's
# business, never a machine's - it refuses to run outside one (docker's /.dockerenv, podman's /run/.containerenv)
if [ ! -f /.dockerenv ] && [ ! -f /run/.containerenv ] && [ -z "$container" ]; then
  echo "REFUSED: ci_container.sh runs inside a container of install.yml: it rewrites /etc/apt/sources.list and installs packages as root" >&2
  exit 2
fi
case "$img" in
  alpine*) apk add --no-cache python3 git >/dev/null || exit 1 ;;
  rockylinux:8*|almalinux:8*) dnf install -y -q python39 git >/dev/null && py=python3.9 || exit 1 ;;   # glibc 2.28, the floor
  fedora*|rockylinux*|almalinux*|centos*) dnf install -y -q python3 git >/dev/null || exit 1 ;;
  archlinux*) pacman -Syu --noconfirm python git >/dev/null || exit 1 ;;
  opensuse*) zypper --non-interactive -q install python3 git >/dev/null || exit 1 ;;
  debian:11*)
     # Debian 11 has left its mirrors for archive.debian.org: the packages of its own security repository 404 on the old ones
     printf 'deb http://archive.debian.org/debian bullseye main\ndeb http://archive.debian.org/debian-security bullseye-security main\n' > /etc/apt/sources.list
     export DEBIAN_FRONTEND=noninteractive
     apt-get -o Acquire::Check-Valid-Until=false update -qq >/dev/null && apt-get install -y -qq python3 git >/dev/null || exit 1 ;;
  *) export DEBIAN_FRONTEND=noninteractive
     apt-get update -qq >/dev/null && apt-get install -y -qq python3 git >/dev/null || exit 1 ;;
esac
echo "image $img: $($py --version 2>&1), $(ldd --version 2>&1 | head -n 1)"
skill="$HOME/.agents/skills/read-page"
git clone -q https://github.com/Elexort/read-page "$skill" || exit 1
git -C "$skill" checkout -q "$sha" || exit 1       # the commit being tested, as a user's clone of it
ci="$py -X utf8 /src/tools/ci_install.py"
rc=0
$ci machine || rc=1
$ci setup --follow --skill "$skill" --label first || rc=1
$ci check --skill "$skill" || rc=1
$ci nodecheck --skill "$skill" || rc=1
$ci read --skill "$skill" || rc=1
$ci collect --skill "$skill"
$ci summary --title "container $img"
exit $rc
