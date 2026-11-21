"""mitmdump addon of the proxy job: one tab-separated line per answered request (host, method, status, bytes the
server promised) in the file named by CI_PROXY_LOG, and one per TLS handshake a client refused. Run by mitmproxy
(Python 3.12), never imported by the skill."""
import os
import time

LOG = os.environ.get("CI_PROXY_LOG") or "proxy-flows.tsv"


def _write(kind, *fields):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write("\t".join([kind, "%.1f" % time.time()] + [str(f) for f in fields]) + "\n")


def response(flow):
    size = flow.response.headers.get("content-length") if flow.response is not None else ""
    _write("flow", flow.request.pretty_host, flow.request.method, flow.response.status_code, size or "")


def tls_failed_client(data):
    # a client that does not trust the proxy's certificate: the handshake ends before any request
    _write("tls-refused", getattr(data.conn, "sni", "") or "", str(getattr(data.conn, "error", "") or "")[:200])


def error(flow):
    _write("error", flow.request.pretty_host, flow.request.method, getattr(flow.error, "msg", ""))
