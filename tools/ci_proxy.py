"""A TLS-inspecting proxy for the proxy job of install.yml: mitmproxy, its root certificate in the OS's own store.

    python tools/ci_proxy.py start [--port N] [--cafile]
                                                  run mitmdump, trust its CA in the OS store, export the proxy variables
                                                  (--cafile: SSL_CERT_FILE too, for a Python that reads no store - macOS)
    python tools/ci_proxy.py report               what went through it, and which clients refused its certificate
    python tools/ci_proxy.py stop                 the proxy off again (the actions that upload the logs must not use it)

README says that uv, Node and Python all trust the machine's certificate store (`UV_SYSTEM_CERTS=1`,
`NODE_USE_SYSTEM_CA=1`, urllib's own default), so a company's proxy that re-signs every connection works for the
whole `--setup`. Nothing had run it. This does: the root certificate goes into the system store and nowhere else
(no `SSL_CERT_FILE`, no `NODE_EXTRA_CA_CERTS`, no `REQUESTS_CA_BUNDLE`), every download of the setup goes through the
proxy, and the report says which hosts it saw and which client turned its certificate down.

Stdlib only; mitmproxy itself is installed by the workflow (`pip install mitmproxy`, Python 3.12).
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
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


def state_dir():
    d = os.path.join(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir(), "ci-proxy")
    os.makedirs(d, exist_ok=True)
    return d


def export_env(name, value):
    path = os.environ.get("GITHUB_ENV")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s=%s\n" % (name, value))


def run(cmd, **kw):
    print("$ " + " ".join(cmd))
    sys.stdout.flush()
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, **kw)


def trust(cert):
    """The root certificate into the machine's store - the one place a company's proxy has its own."""
    if os.name == "nt":
        return run(["certutil", "-addstore", "-f", "Root", cert]).returncode == 0
    if sys.platform == "darwin":
        return run(["sudo", "security", "add-trusted-cert", "-d", "-r", "trustRoot", "-k",
                    "/Library/Keychains/System.keychain", cert]).returncode == 0
    ok = run(["sudo", "cp", cert, "/usr/local/share/ca-certificates/mitmproxy-ci.crt"]).returncode == 0
    return ok and run(["sudo", "update-ca-certificates"]).returncode == 0


def cmd_start(a):
    d = state_dir()
    conf, log = os.path.join(d, "conf"), os.path.join(d, "proxy-flows.tsv")
    open(log, "w").close()
    exe = shutil.which("mitmdump")
    if not exe:
        print("FAIL: mitmdump is not installed")
        return 1
    env = dict(os.environ, CI_PROXY_LOG=log)
    out = open(os.path.join(d, "mitmdump.log"), "w", encoding="utf-8")
    kw = {"creationflags": 0x00000200 | 0x08000000} if os.name == "nt" else {"start_new_session": True}
    # large bodies are streamed through, not held in memory: the setup moves 400 MB
    p = subprocess.Popen([exe, "--listen-host", "127.0.0.1", "--listen-port", str(a.port), "--set", "confdir=" + conf,
                          "--set", "stream_large_bodies=1m", "--set", "flow_detail=0", "-s",
                          os.path.join(HERE, "ci_proxy_addon.py")], stdin=subprocess.DEVNULL, stdout=out,
                         stderr=subprocess.STDOUT, env=env, **kw)
    cert = os.path.join(conf, "mitmproxy-ca-cert.pem")
    for _ in range(120):
        if os.path.isfile(cert):
            try:
                with socket.create_connection(("127.0.0.1", a.port), timeout=1):
                    break
            except OSError:
                pass
        if p.poll() is not None:
            print("FAIL: mitmdump ended (exit %s):\n%s" % (p.returncode, open(os.path.join(d, "mitmdump.log"),
                                                                           encoding="utf-8", errors="replace").read()[-2000:]))
            return 1
        time.sleep(0.5)
    else:
        print("FAIL: mitmdump did not listen in 60 s")
        return 1
    if not trust(cert):
        print("FAIL: the proxy's root certificate could not be put in the system's store")
        return 1
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
    print("mitmdump pid %d listens on %s; its CA is in the system store (%s)" % (p.pid, proxy, cert))
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
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY", "no_proxy", "SSL_CERT_FILE"):
        export_env(k, "")
    try:
        with open(os.path.join(state_dir(), "mitmdump.pid"), encoding="utf-8") as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return 0
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.set_defaults(fn=cmd_start)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--cafile", action="store_true")
    sub.add_parser("report").set_defaults(fn=cmd_report)
    sub.add_parser("stop").set_defaults(fn=cmd_stop)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
