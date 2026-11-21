"""The browser's only way out: a SOCKS5 proxy on 127.0.0.1 that this read's
browser alone uses, so that a public page cannot make it reach into the user's own network.

Why not Playwright's request routing, which did this before: it showed Python only the first
URL of a redirect chain. A public page that fetched its own /hop, answered by a 302 to an
internal address, got the internal answer into its text, and a meta refresh to such a /hop made
the internal page itself the text (found 2026-11-06). It also checked a name that Chrome then
resolved again (DNS rebinding), and Chrome without a browser library (--dump-dom) had no check
at all.

Here every connection the browser opens - a page, a script's fetch, a redirect hop, a frame, a
WebSocket - comes through us as "host:port". policy(host, port) resolves the name once, checks
every address, and returns the addresses; the connection goes to exactly those (no second lookup,
so no rebinding window), or is refused with SOCKS reply 2 and recorded. TLS stays end to end:
the site sees the same address and the same browser, nothing is decrypted. Playwright adds
--proxy-bypass-list=<-loopback> (else Chrome sends localhost past any proxy) and, for SOCKS5,
--host-resolver-rules that leave every name to the proxy; the --dump-dom path passes both itself.

Only the standard library, Python 3.8, any OS: Chromium speaks SOCKS5 on all of them.
"""
import socket
import threading
import time

REPLY_OK, REPLY_FAILURE, REPLY_NOT_ALLOWED, REPLY_HOST_UNREACHABLE, REPLY_REFUSED = 0, 1, 2, 4, 5
REPLY_COMMAND, REPLY_ADDRESS = 7, 8
HANDSHAKE_SECONDS = 10.0
CONNECT_SECONDS = 10.0          # all addresses of one name together
ATTEMPT_SECONDS = 5.0           # one address
CHUNK = 65536


class Guard:
    """start() binds 127.0.0.1 on a free port (`port`); close() stops taking connections, and the
    open ones end when the browser closes them. `refused` lists what was not let through:
    [{"host", "port", "why"}]. log(ev, **fields) is told of every connection (the debug log)."""

    def __init__(self, policy, log=None):
        self.policy = policy
        self.log = log or (lambda ev, **kw: None)
        self.refused = []
        self.opened = 0
        self.port = 0
        self.thread = None
        self._sock = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(128)
        self._sock, self.port = s, s.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, name="netguard", daemon=True)
        self.thread.start()
        return self

    @property
    def server(self):
        return "socks5://127.0.0.1:%d" % self.port

    def close(self):
        self._stop.set()
        s = self._sock
        if s is None:
            return
        try:
            # Linux keeps a socket listening while another thread waits in accept() on it: close()
            # alone left the guard taking connections (under its rules) until the read's process
            # ended. shutdown() wakes that accept() with an error (macOS and Windows refuse it: not
            # connected - there close() is enough)
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            s.close()
        except OSError:
            pass

    def _accept(self):
        while not self._stop.is_set():
            try:
                c, _addr = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), name="netguard-conn", daemon=True).start()

    def _serve(self, c):
        up, host, port, t0 = None, "", 0, time.time()
        try:
            c.settimeout(HANDSHAKE_SECONDS)
            ver, n = _recv(c, 2)
            _recv(c, n)                                  # the methods offered: we take "no auth"
            if ver != 5:
                return
            c.sendall(b"\x05\x00")
            ver, cmd, _rsv, atyp = _recv(c, 4)
            if atyp == 1:
                host = socket.inet_ntop(socket.AF_INET, _recv(c, 4))
            elif atyp == 3:
                host = _recv(c, _recv(c, 1)[0]).decode("ascii", "replace")
            elif atyp == 4:
                host = socket.inet_ntop(socket.AF_INET6, _recv(c, 16))
            else:
                _reply(c, REPLY_ADDRESS)
                return
            port = int.from_bytes(_recv(c, 2), "big")
            if cmd != 1:                                 # CONNECT only: no BIND, no UDP
                _reply(c, REPLY_COMMAND)
                return
            why, addrs = self.policy(host, port)
            if why:
                with self._lock:
                    self.refused.append({"host": host, "port": port, "why": why})
                self.log("refused", host=host, port=port, why=why)
                _reply(c, REPLY_NOT_ALLOWED)
                return
            if not addrs:                                # the name does not resolve
                self.log("unresolved", host=host, port=port, ms=int((time.time() - t0) * 1000))
                _reply(c, REPLY_HOST_UNREACHABLE)
                return
            up, err = _connect(addrs, port)
            if up is None:
                self.log("unreachable", host=host, port=port, addrs=addrs, error=err,
                         ms=int((time.time() - t0) * 1000))
                _reply(c, REPLY_REFUSED if "refused" in err.lower() else REPLY_HOST_UNREACHABLE)
                return
            with self._lock:
                self.opened += 1
            _reply(c, REPLY_OK)
            c.settimeout(None)
            up.settimeout(None)
            counts = [0, 0]
            back = threading.Thread(target=_pipe, args=(up, c, counts, 1), name="netguard-pipe", daemon=True)
            back.start()
            _pipe(c, up, counts, 0)
            back.join()
            self.log("closed", host=host, port=port, addr=up.getpeername()[0] if _alive(up) else "",
                     sent=counts[0], received=counts[1], ms=int((time.time() - t0) * 1000))
        except ConnectionError as e:
            # Chrome opens spare connections and drops some unused, before or after asking: not an error
            self.log("dropped", host=host, port=port, error=str(e)[:120])
        except Exception as e:                                          # noqa: BLE001
            self.log("error", host=host, port=port, error="%s: %s" % (type(e).__name__, str(e)[:200]))
        finally:
            for s in (c, up):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass


def _recv(s, n):
    """Exactly n bytes, or an error: a client that stops mid-handshake is gone."""
    buf = b""
    while len(buf) < n:
        part = s.recv(n - len(buf))
        if not part:
            raise ConnectionError("the client closed the handshake")
        buf += part
    return buf


def _reply(c, code):
    try:
        c.sendall(b"\x05" + bytes([code]) + b"\x00\x01" + b"\x00" * 6)
    except OSError:
        pass


def _connect(addrs, port):
    """The first of the checked addresses that answers - IPv4 first, as most networks have it -
    within CONNECT_SECONDS in all. Returns (socket or None, the last error)."""
    end, err = time.time() + CONNECT_SECONDS, "no address"
    for a in sorted(addrs, key=lambda x: ":" in x):
        left = end - time.time()
        if left <= 0:
            break
        try:
            return socket.create_connection((a, port), timeout=min(ATTEMPT_SECONDS, left)), ""
        except OSError as e:
            err = "%s: %s" % (type(e).__name__, str(e)[:120])
    return None, err


def _pipe(src, dst, counts, i):
    try:
        while True:
            data = src.recv(CHUNK)
            if not data:
                break
            dst.sendall(data)
            counts[i] += len(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)               # the other way may still be talking
        except OSError:
            pass


def _alive(s):
    try:
        s.getpeername()
        return True
    except OSError:
        return False


def load_list(path):
    """(names refused, names let through) from a host list: an ad-block DNS filter's `||host^`
    rules and their `@@` exceptions, a hosts file's `0.0.0.0 host` lines, or one name a line. A
    rule with a wildcard, a path or a modifier other than $important is not a host rule: skipped."""
    block, allow = set(), set()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip().lower()
            if not s or s[0] in "!#[":
                continue
            exc = s.startswith("@@")
            if exc:
                s = s[2:]
            if s.startswith("||"):
                s = s[2:]
                s = s[:-len("$important")] if s.endswith("$important") else s
                if not s.endswith("^"):
                    continue
                s = s[:-1]
            else:
                parts = s.split()
                if len(parts) >= 2 and parts[0] in ("0.0.0.0", "127.0.0.1", "::", "::1"):
                    s = parts[1]
                elif len(parts) != 1:
                    continue
            s = s.strip(".")
            if not s or any(ch in s for ch in "*/$|^ ") or "." not in s:
                continue
            (allow if exc else block).add(s)
    return block, allow


def listed(host, block, allow):
    """Whether a name or one of its parent domains is on the list, an exception winning."""
    parts = (host or "").lower().strip(".").split(".")
    for i in range(len(parts) - 1):
        name = ".".join(parts[i:])
        if name in allow:
            return False
        if name in block:
            return True
    return False


def resolve(host, port):
    """Every address of a name, as the browser would have looked them up (one lookup)."""
    out = []
    for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        a = str(info[4][0]).split("%")[0]
        if a not in out:
            out.append(a)
    return out
