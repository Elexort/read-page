"""A TLS-inspecting proxy for the proxy job of install.yml: mitmproxy, its root certificate in the OS's own store.

    python tools/ci_proxy.py start [--port N] [--cafile] [--on-this-machine]
                                                  run mitmdump, trust its CA in the OS store, export the proxy variables
                                                  (--cafile: SSL_CERT_FILE too, for a Python that reads no store - macOS)
    python tools/ci_proxy.py report               what went through it, and which clients refused its certificate
    python tools/ci_proxy.py stop                 the proxy off again, its root certificate out of the OS store and its
                                                  key deleted (the actions that upload the logs must not use it)

README says that uv, Node and Python all trust the machine's certificate store (`UV_SYSTEM_CERTS=1`,
`NODE_USE_SYSTEM_CA=1`, urllib's own default), so a company's proxy that re-signs every connection works for the
whole `--setup`. Nothing had run it. This does: the root certificate goes into the system store and nowhere else
(no `SSL_CERT_FILE`, no `NODE_EXTRA_CA_CERTS`, no `REQUESTS_CA_BUNDLE`), every download of the setup goes through the
proxy, and the report says which hosts it saw and which client turned its certificate down.

It is for a CI runner, which is thrown away after the job: a root certificate trusted system-wide, with its key in a
folder, lets whoever reads that key intercept every TLS connection of the machine. Outside GitHub Actions it refuses
to run unless told plainly (--on-this-machine), and `stop` takes out what `start` put in: the certificate (by its
SHA-1, the one this run made and no other), the CA and its key, the proxy. Its state is a folder of its own
(RUNNER_TEMP's `ci-proxy` on a runner, a new private one elsewhere, named in CI_PROXY_DIR for the later commands):
mitmproxy reuses a CA it finds in its folder, and a fixed one in a shared /tmp could hold someone else's.

Stdlib only; mitmproxy itself is installed by the workflow (`pip install mitmproxy`, Python 3.12).
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LINUX_CERT = "/usr/local/share/ca-certificates/mitmproxy-ci.crt"
MAC_KEYCHAIN = "/Library/Keychains/System.keychain"
# what a whole --setup and a read must be seen asking for: PyPI's index and its files, Python's builds (GitHub),
# the OCR data (raw.githubusercontent.com), Node or npm's registry, the browser's CDN
REQUIRED = [("pypi.org", ("pypi.org",)),
            ("PyPI's files", ("files.pythonhosted.org",)),
            ("Python's builds", ("releases.astral.sh", "github.com", "release-assets.githubusercontent.com",
                                 "objects.githubusercontent.com")),
            ("OCR data", ("raw.githubusercontent.com",)),
            ("npm's registry (defuddle)", ("registry.npmjs.org",)),
            ("the browser's download", ("storage.googleapis.com", "playwright.download.prss.microsoft.com",
                                        "playwright.azureedge.net"))]


def on_ci():
    return os.environ.get("GITHUB_ACTIONS") == "true"


def refused(a):
    """Why this command does not run here ('' where it does): off a CI runner, only when told plainly."""
    if on_ci() or getattr(a, "on_this_machine", False):
        return ""
    return ("ci_proxy.py puts a root certificate into this machine's own store, with its key in a folder: whoever reads "
            "that key can intercept every TLS connection of the machine. It runs on a CI runner (GITHUB_ACTIONS=true), "
            "which is thrown away after the job; here only with --on-this-machine, and `stop` after it")


def state_dir(new=False):
    """The folder of this proxy's state: RUNNER_TEMP's `ci-proxy` on a runner (the job's own), else CI_PROXY_DIR -
    which `start` makes, new and this user's alone, and names - or None where there is none to use."""
    if os.environ.get("RUNNER_TEMP") and on_ci():
        d = os.path.join(os.environ["RUNNER_TEMP"], "ci-proxy")
        os.makedirs(d, exist_ok=True)
        return d
    if new:
        return tempfile.mkdtemp(prefix="ci-proxy-")
    d = os.environ.get("CI_PROXY_DIR") or ""
    return d if d and os.path.isfile(os.path.join(d, "state.json")) else None


def export_env(name, value):
    path = os.environ.get("GITHUB_ENV")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s=%s\n" % (name, value))


def run(cmd, **kw):
    print("$ " + " ".join(cmd))
    sys.stdout.flush()
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, **kw)


def thumbprint(cert):
    """The SHA-1 of a PEM certificate's DER bytes, as the stores name it (certutil, `security -Z`)."""
    with open(cert, encoding="ascii", errors="replace") as fh:
        body = re.search(r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", fh.read(), re.S)
    return hashlib.sha1(base64.b64decode("".join(body.group(1).split()))).hexdigest().upper() if body else ""


def trust_commands(cert, system=None):
    """The commands that put the root certificate into the machine's store - the one place a company's proxy has its
    own - for this system ("nt", "darwin", "linux")."""
    system = system or ("nt" if os.name == "nt" else sys.platform if sys.platform == "darwin" else "linux")
    if system == "nt":
        return [["certutil", "-addstore", "-f", "Root", cert]]
    if system == "darwin":
        return [["sudo", "security", "add-trusted-cert", "-d", "-r", "trustRoot", "-k", MAC_KEYCHAIN, cert]]
    return [["sudo", "cp", cert, LINUX_CERT], ["sudo", "update-ca-certificates"]]


def untrust_commands(cert, sha1, system=None):
    """The commands that take that certificate - by its SHA-1, this run's and no other - out of the store again."""
    system = system or ("nt" if os.name == "nt" else sys.platform if sys.platform == "darwin" else "linux")
    if system == "nt":
        return [["certutil", "-delstore", "Root", sha1]] if sha1 else []
    if system == "darwin":
        # the certificate first: its trust setting's removal may wait for an administrator's answer (untrust)
        return ([["sudo", "security", "delete-certificate", "-Z", sha1, MAC_KEYCHAIN]] if sha1 else []) + (
            [["sudo", "security", "remove-trusted-cert", "-d", cert]] if cert and os.path.isfile(cert) else [])
    return [["sudo", "rm", "-f", LINUX_CERT], ["sudo", "update-ca-certificates", "--fresh"]]


# On a runner each removal is stopped at this many seconds: macOS's `security remove-trusted-cert -d` waits there for
# an administrator's answer that no one gives, and held the job for its 90 minutes
UNDO_SECONDS = 60
_TIMEOUT = subprocess.TimeoutExpired


def untrust(cmds, on_runner):
    """Run the commands that take the certificate out: (what failed, what was left). On a runner each is stopped at
    UNDO_SECONDS; a trust setting whose removal waits for a prompt is named and left - the certificate is out of the
    keychain before it and the CA's key is deleted, so nothing can be signed with it any more. Off a runner a prompt
    is the person's to answer, with no limit."""
    bad, left = [], []
    for c in cmds:
        try:
            p = run(c, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=UNDO_SECONDS if on_runner else None)
        except (_TIMEOUT, OSError) as e:
            why = "no answer in %d s" % UNDO_SECONDS if isinstance(e, _TIMEOUT) else str(e)
            (left if isinstance(e, _TIMEOUT) and "remove-trusted-cert" in c else bad).append("%s (%s)" % (" ".join(c), why))
            continue
        if p.returncode != 0:
            bad.append("%s (%s)" % (" ".join(c), p.stdout.decode("utf-8", "replace").strip()[-160:]))
    return bad, left


def end_process(pid):
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(int(pid), 15)
        except (OSError, ValueError):
            pass


def save_state(d, **kw):
    path = os.path.join(d, "state.json")
    state = {}
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        pass
    state.update(kw)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    return state


def cmd_start(a):
    why = refused(a)
    if why:
        print("REFUSED: " + why)
        return 2
    exe = shutil.which("mitmdump")
    if not exe:
        print("FAIL: mitmdump is not installed")
        return 1
    d = state_dir(new=True)
    conf, log = os.path.join(d, "conf"), os.path.join(d, "proxy-flows.tsv")
    if os.path.isdir(conf):
        shutil.rmtree(conf)                    # a CA left there is not this run's: mitmproxy would take it
    open(log, "w").close()
    env = dict(os.environ, CI_PROXY_LOG=log)
    out = open(os.path.join(d, "mitmdump.log"), "w", encoding="utf-8")
    kw = {"creationflags": 0x00000200 | 0x08000000} if os.name == "nt" else {"start_new_session": True}
    # large bodies are streamed through, not held in memory: the setup moves 400 MB
    p = subprocess.Popen([exe, "--listen-host", "127.0.0.1", "--listen-port", str(a.port), "--set", "confdir=" + conf,
                          "--set", "stream_large_bodies=1m", "--set", "flow_detail=0", "-s",
                          os.path.join(HERE, "ci_proxy_addon.py")], stdin=subprocess.DEVNULL, stdout=out,
                         stderr=subprocess.STDOUT, env=env, **kw)
    save_state(d, pid=p.pid, conf=conf)        # at once: `stop` ends it whatever happens below
    export_env("CI_PROXY_DIR", d)
    cert = os.path.join(conf, "mitmproxy-ca-cert.pem")

    def give_up(msg):
        print("FAIL: " + msg)
        end_process(p.pid)
        shutil.rmtree(conf, ignore_errors=True)
        return 1

    for _ in range(120):
        if os.path.isfile(cert):
            try:
                with socket.create_connection(("127.0.0.1", a.port), timeout=1):
                    break
            except OSError:
                pass
        if p.poll() is not None:
            return give_up("mitmdump ended (exit %s):\n%s" % (p.returncode, open(
                os.path.join(d, "mitmdump.log"), encoding="utf-8", errors="replace").read()[-2000:]))
        time.sleep(0.5)
    else:
        return give_up("mitmdump did not listen in 60 s")
    sha1 = thumbprint(cert)
    save_state(d, cert=cert, sha1=sha1)
    if not all(run(c).returncode == 0 for c in trust_commands(cert)):
        for c in untrust_commands(cert, sha1):          # whatever of it went in
            run(c)
        return give_up("the proxy's root certificate could not be put in the system's store")
    save_state(d, trusted=True)
    proxy = "http://127.0.0.1:%d" % a.port
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        export_env(k, proxy)
    export_env("NO_PROXY", "127.0.0.1,localhost")
    export_env("no_proxy", "127.0.0.1,localhost")
    export_env("CI_PROXY_LOG", log)
    if a.cafile:
        export_env("SSL_CERT_FILE", cert)
    with open(os.path.join(d, "mitmdump.pid"), "w", encoding="utf-8") as fh:
        fh.write(str(p.pid))
    print("mitmdump pid %d listens on %s; its CA (SHA-1 %s) is in the system store (%s)" % (p.pid, proxy, sha1, cert))
    if not on_ci():
        print("its state: CI_PROXY_DIR=%s - give it to `stop`, which takes the certificate out again" % d)
    return 0


def read_log(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            rows = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip()]
    except OSError:
        pass
    return rows


def cmd_report(a):
    d = state_dir()
    if not (os.environ.get("CI_PROXY_LOG") or d):
        print("FAIL: no proxy of this tool's here (CI_PROXY_DIR names the one `start` made)")
        return 1
    rows = read_log(os.environ.get("CI_PROXY_LOG") or os.path.join(d, "proxy-flows.tsv"))
    hosts, refused, errors = {}, {}, []
    for r in rows:
        if r[0] == "flow" and len(r) >= 6:
            h = hosts.setdefault(r[2], [0, 0, {}])
            h[0] += 1
            h[1] += int(r[5]) if r[5].isdigit() else 0
            h[2][r[4]] = h[2].get(r[4], 0) + 1
        elif r[0] == "tls-refused":
            refused[r[2] if len(r) > 2 else "?"] = refused.get(r[2] if len(r) > 2 else "?", 0) + 1
        elif r[0] == "error":
            errors.append(r[2:5])
    print("through the proxy: %d requests to %d hosts, %.0f MB promised" % (
        sum(h[0] for h in hosts.values()), len(hosts), sum(h[1] for h in hosts.values()) / 1048576.0))
    for name, h in sorted(hosts.items(), key=lambda kv: -kv[1][1])[:25]:
        print("  %-48s %5d requests %8.1f MB  statuses %s" % (name, h[0], h[1] / 1048576.0,
                                                           ",".join("%s x%d" % kv for kv in sorted(h[2].items()))))
    bad = []
    for what, names in REQUIRED:
        if not any(n in hosts for n in names):
            bad.append("%s did not go through the proxy (looked for %s)" % (what, ", ".join(names)))
    print("clients that refused the proxy's certificate: %s" % (
        ", ".join("%s x%d" % kv for kv in sorted(refused.items())) or "none"))
    for host, n in sorted(refused.items()):
        # the read's own library (curl_cffi) has CA bundle of its own and falls back to an unverified retry for a
        # public page; an installer that refuses the certificate is what this job is for
        if host and host not in ("example.com", "www.example.com"):
            bad.append("a client refused the certificate for %s (x%d): it does not use the system's store" % (host, n))
    if errors:
        print("failed flows: %d, first: %s" % (len(errors), errors[:3]))
    for b in bad:
        print("FAIL: " + b)
    return 1 if bad else 0


def cmd_stop(a):
    """Undo what `start` did: the proxy's variables off, mitmdump ended, its root certificate out of the store (by
    its SHA-1), its CA and key deleted. The flows and mitmdump's log stay for the job's logs."""
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY", "no_proxy", "SSL_CERT_FILE"):
        export_env(k, "")
    d = state_dir()
    if not d:
        print("no proxy of this tool's to stop here (CI_PROXY_DIR names the one `start` made)")
        return 0
    state = save_state(d)
    end_process(state.get("pid"))
    bad, left = [], []
    if state.get("trusted") or state.get("sha1"):
        bad, left = untrust(untrust_commands(state.get("cert") or "", state.get("sha1") or ""),
                            os.environ.get("GITHUB_ACTIONS") == "true")
        save_state(d, trusted=False)
    shutil.rmtree(state.get("conf") or os.path.join(d, "conf"), ignore_errors=True)       # the CA's key above all
    print("the proxy is off; its root certificate (SHA-1 %s) is out of the system store%s; its CA and key are deleted%s"
          % (state.get("sha1") or "?", "" if not bad else " - NOT for: %s" % "; ".join(bad),
             "" if not left else "; left, waiting for a prompt no one answers here: %s" % "; ".join(left)))
    return 1 if bad else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.set_defaults(fn=cmd_start)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--cafile", action="store_true")
    p.add_argument("--on-this-machine", dest="on_this_machine", action="store_true",
                   help="run off a CI runner too: the root certificate goes into this machine's store until `stop`")
    sub.add_parser("report").set_defaults(fn=cmd_report)
    sub.add_parser("stop").set_defaults(fn=cmd_stop)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
