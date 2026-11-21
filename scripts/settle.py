"""When a rendered page is done. A pure rule over what the browser step sees on each poll,
so it is tested without a browser.

Measured 2026-11-06 on 67 sites (SPAs, walls, heavy news and shop pages), on a 20-core Windows
machine and on an emulated Celeron: one load each was watched for 20-25 s and the text at each
candidate rule's stop compared with the text at the end.
- A rule that ignored scripts in flight and looked at the network only at the poll it stopped on
  lost text on 8 of 67 pages on the fast machine: Steam, AliExpress and Rutube fetch their data a
  moment after a burst of scripts; rbc.ru answers 401 and fills the page 3 s after
  DOMContentLoaded.
- On the weak laptop the page's own scripts hold the probe: Steam's polls came 3.7 s apart, rbc's
  1.4 s. A late poll is a busy page, not a quiet one; counted as quiet it cut Steam, rbc, VK and
  gosuslugi.ru.
- With scripts counted, a quiet *window* and late polls as activity: the fast machine lost 0 of 67
  (p50 5.4 s from the launch, p90 8.9; the old rule 6.3 / 9.6 and 2 lost); weak 3 of 67 (p50 12.0,
  p90 18.6; the old rule lost 12, mostly to its 10 s budget). The 2 s "whatever is in flight" rule
  lost nothing that 3 or 5 s kept, and lets go of pages whose analytics never end.

Done when, after DOMContentLoaded:
  settled     the text is not empty and unchanged for STABLE s, nothing in flight for QUIET s, and
              the mount node is neither empty nor a "Loading..." placeholder
  busy        the text unchanged for BUSY s, whatever is in flight (analytics that never end)
  error-page  status >= 400, unchanged and quiet for ERROR s, no challenge script running
  empty       no text EMPTY s after DOMContentLoaded, nothing in flight for QUIET s, and no empty
              mount node waiting to be filled (web.telegram.org keeps one empty: it waits it out)
A poll that comes more than GAP s after the one before means the page's scripts held the probe:
the network is not quiet and the text not stable across it.
"""
import re

STABLE = 1.0
QUIET = 1.0
BUSY = 2.0
ERROR = 1.5
EMPTY = 3.0
GAP = 0.5
# what holds the page open: a script that loads a script that fetches the data counts as one chain
BUSY_TYPES = ("xhr", "fetch", "document", "script")
PLACEHOLDER = re.compile(r"(?i)\b(loading|please wait|загрузка|подождите)\b|(\.\.\.|…)\s*$")

# one look per poll: the body's text length, the mount node, and a challenge still running
PROBE = """() => { const q = ['#app', '#root', '#__next', '#___gatsby', '#svelte', 'main', '[role=main]'];
  let m = [-1, ''];
  for (const s of q) { const e = document.querySelector(s);
    if (e) { const t = (e.innerText || '').trim(); m = [t.length, t.slice(0, 60)]; break; } }
  const cur = document.body ? document.body.innerText.length : 0;
  const chl = !!(window._cf_chl_opt || document.querySelector(
    'script[src*="/cdn-cgi/challenge-platform/"], #challenge-form, iframe[src*="captcha"]'));
  return [cur, m[0], m[1], chl]; }"""


class Settle:
    def __init__(self, dcl, status=0):
        self.dcl = dcl
        self.status = status or 0
        self.prev = -1
        self.since = dcl            # when the text last changed
        self.busy_at = dcl          # when something was last in flight, or the page held the probe
        self.last = dcl             # the previous poll

    def see(self, t, chars, mount_size, mount_head, challenge, in_flight):
        """One poll at time t: the reason the page is done, or ""."""
        if chars != self.prev:
            self.prev, self.since = chars, t
        if in_flight:
            self.busy_at = t
        if t - self.last > GAP:                 # the page's scripts held this poll back
            self.busy_at = t
            self.since = max(self.since, t)
        self.last = t
        stable, quiet = t - self.since, t - self.busy_at
        pending = mount_size >= 0 and (mount_size < 80 or (
            mount_size < 400 and bool(PLACEHOLDER.search(mount_head or ""))))
        if chars > 0 and stable >= STABLE and quiet >= QUIET and not pending:
            return "settled"
        if chars > 0 and stable >= BUSY and not pending:
            return "busy"
        if self.status >= 400 and stable >= ERROR and quiet >= ERROR and not challenge:
            return "error-page"
        if chars == 0 and t - self.dcl >= EMPTY and quiet >= QUIET and not pending:
            # an empty #app / #root is a page still to be filled, by a timer if not the network
            return "empty"
        return ""
