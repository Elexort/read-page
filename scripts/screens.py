"""Screenshots as screens.

The old way cut the full page into 1280x1568 clips: 10-49 s a tile on long pages, no tile at all
on some, and the pictures of tiles 2-3 blank (9 of 12 pages had them unloaded at capture time).
Now the page is laid out in a laptop's window, 1280x784, and scrolled screen by screen:
- per screen: scroll, one wait for the screen's pictures and a quiet page (no DOM change for
  150 ms; at most 0.6 s - measured p50 0.14 s, p90 0.26, a never-loading picture reaches the cap),
  hide the bars, capture;
- bars: a header-like bar (top <= 5 px, at least half the width, at most 160 px tall) stays on
  screen 1 and is hidden from screen 2 on; every other fixed or sticky element is hidden at once,
  by opacity (visibility leaked children and left a 57-280 px empty band at the top of screen 1);
- a page that scrolls an inner block instead of the window (Spotify) is scrolled by that block;
- `--screenshots N` counts screens. With Pillow or PyMuPDF two screens become one 1280x1568
  picture (the long edge a vision host keeps); without them the screens come one by one;
- PNG, one capture; a picture over 3.75 MB is re-encoded once as JPEG q95 (noise, the worst
  case, is 5.76 MB as PNG and 2.25 MB as JPEG q95);
- the context asks for reduced motion and animations are stopped, so a section is not caught
  halfway through its entrance;
- the read's deadline ends the loop: what was taken is kept, and the answer says K of N;
- a step of the page that fails (the setup, a screen) ends the loop too, and the answer says which step and what
  it said (`signals.screenshots_failed`), so a capture that took no picture says why.
"""
import io
import os
import time

SCREEN_W, SCREEN_H = 1280, 784
MAX_BYTES = int(3.75 * 1024 * 1024)
JPEG_Q = 95
WAIT_CAP = 0.6
QUIET_MS = 150

STYLE = "*{animation:none!important;transition:none!important;caret-color:transparent!important}"
WATCH_JS = """() => { if (window.__rpWatch) return; window.__rpWatch = 1; window.__rpMut = performance.now();
  new MutationObserver(() => { window.__rpMut = performance.now(); }).observe(document.documentElement,
  {subtree: true, childList: true, attributes: true, attributeFilter: ['style', 'class', 'src', 'hidden']}); }"""
STATE_JS = """() => { let p = 0; for (const img of document.images) { const r = img.getBoundingClientRect();
  if (r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth || r.width < 2 || r.height < 2) continue;
  if (!img.complete) p++; }
  return [p, performance.now() - (window.__rpMut || 0), document.fonts ? document.fonts.status : 'loaded']; }"""
HIDE_JS = """(screen) => {
  let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (screen === 1) {
      const r = el.getBoundingClientRect();
      if (r.top <= 5 && r.width >= innerWidth * 0.5 && r.height > 0 && r.height <= 160) continue;
    }
    el.style.setProperty('opacity', '0', 'important'); n++;
  }
  return n; }"""
SCROLLER_JS = """() => {
  const se = document.scrollingElement || document.documentElement;
  if (se.scrollHeight > innerHeight + 50) return ['', se.scrollHeight];
  let best = null, bestH = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (el.clientHeight < innerHeight * 0.5 || el.clientWidth < innerWidth * 0.5) continue;
    const oy = getComputedStyle(el).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 200 && el.scrollHeight > bestH) {
      best = el; bestH = el.scrollHeight; }
  }
  if (!best) return ['', se.scrollHeight];
  best.setAttribute('data-rp-scroller', '1');
  return ['inner', best.scrollHeight]; }"""
SCROLL_JS = """([inner, y]) => {
  const el = inner ? document.querySelector('[data-rp-scroller]') : null;
  if (el) { el.scrollTop = y; return el.scrollTop; }
  window.scrollTo({top: y, behavior: 'instant'}); return window.scrollY; }"""
FRAMES_JS = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"


def glue_tool():
    """What can glue two screens and re-encode a picture: "pillow", "pymupdf" or "" (also with
    READ_PAGE_SKIP=glue, which the tests use to stand for a machine with neither)."""
    if "glue" in (os.environ.get("READ_PAGE_SKIP") or "").split(","):
        return ""
    for name in ("PIL.Image", "pymupdf"):
        try:
            __import__(name)
            return "pillow" if name.startswith("PIL") else "pymupdf"
        except Exception:                                     # noqa: BLE001
            continue
    return ""


def _wait_ready(page, cap=WAIT_CAP):
    """One wait for the screen's pictures, the fonts and a quiet page, at most `cap` seconds."""
    t = time.perf_counter()
    while time.perf_counter() - t < cap:
        try:
            pending, quiet, fonts = page.evaluate(STATE_JS)
        except Exception:                                     # noqa: BLE001
            return
        if pending == 0 and quiet >= QUIET_MS and fonts == "loaded":
            return
        page.wait_for_timeout(25)


def _glue(parts, tool):
    """Screens (PNG bytes, the overlap to cut from the top of each) as one picture: (bytes, w, h, fmt)."""
    if tool == "pillow":
        from PIL import Image
        ims = [Image.open(io.BytesIO(b)).convert("RGB") for b, _cut in parts]
        ims = [im.crop((0, cut, im.width, im.height)) if cut else im for im, (_b, cut) in zip(ims, parts)]
        out = Image.new("RGB", (max(im.width for im in ims), sum(im.height for im in ims)), "white")
        y = 0
        for im in ims:
            out.paste(im, (0, y))
            y += im.height
        buf = io.BytesIO()
        out.save(buf, "PNG")
        data, fmt = buf.getvalue(), "png"
        if len(data) > MAX_BYTES:
            buf = io.BytesIO()
            out.save(buf, "JPEG", quality=JPEG_Q)
            data, fmt = buf.getvalue(), "jpg"
        return data, out.width, out.height, fmt
    import pymupdf
    pix = [pymupdf.Pixmap(b) for b, _cut in parts]
    w = max(p.width for p in pix)
    h = sum(p.height - cut for p, (_b, cut) in zip(pix, parts))
    out = pymupdf.Pixmap(pix[0].colorspace, pymupdf.IRect(0, 0, w, h), pix[0].alpha)
    out.clear_with(255)
    y = 0
    for p, (_b, cut) in zip(pix, parts):
        p.set_origin(0, y - cut)
        out.copy(p, pymupdf.IRect(0, y, p.width, y + p.height - cut))
        y += p.height - cut
    data, fmt = out.tobytes("png"), "png"
    if len(data) > MAX_BYTES:
        data, fmt = out.tobytes("jpg", jpg_quality=JPEG_Q), "jpg"
    return data, w, h, fmt


def _alone(png, tool, page):
    """One screen as it is; over MAX_BYTES once as JPEG q95 (by the glue tool, else by Chrome)."""
    if len(png) <= MAX_BYTES:
        return png, "png"
    if tool == "pillow":
        from PIL import Image
        buf = io.BytesIO()
        Image.open(io.BytesIO(png)).convert("RGB").save(buf, "JPEG", quality=JPEG_Q)
        return buf.getvalue(), "jpg"
    if tool == "pymupdf":
        import pymupdf
        return pymupdf.Pixmap(png).tobytes("jpg", jpg_quality=JPEG_Q), "jpg"
    try:
        return page.screenshot(type="jpeg", quality=JPEG_Q), "jpg"
    except Exception:                                         # noqa: BLE001
        return png, "png"


def _why(step, e):
    """A step's failure as one line: the step, the error's name and the first line of what it said."""
    said = " ".join(str(e).split("\n", 1)[0].split())[:160]
    return "%s: %s%s" % (step, type(e).__name__, (": " + said) if said else "")


def capture(page, workdir, want, seconds_left=lambda: 1e9, per_screen=1.5):
    """The first `want` screens of the page into workdir/shots: (entries, screens the page has,
    screens taken, why). Each entry is one picture: {file, width, height, bytes, format, screens}.
    `why` is "" unless a step of the page failed - the setup, or a screen - and then it names the step and
    the error: a capture that took nothing, or stopped early, never does it in silence. The read's deadline
    that ends the loop is no failure."""
    if want <= 0:
        return [], 0, 0, ""
    step = "adding the style"
    try:
        page.add_style_tag(content=STYLE)
        step = "measuring the page"
        page.evaluate(WATCH_JS)
        inner, height = page.evaluate(SCROLLER_JS)
        vh = int(page.evaluate("() => innerHeight") or SCREEN_H)
    except Exception as e:                                    # noqa: BLE001
        return [], 0, 0, _why(step, e)
    height = max(int(height or 0), 1)
    needed = max(1, -(-height // vh))
    shots = os.path.join(workdir, "shots")
    os.makedirs(shots, exist_ok=True)
    tool = glue_tool()
    screens = []                                   # (png, overlap with the screen before)
    why = ""
    for i in range(min(want, needed)):
        if i and seconds_left() < per_screen:
            break                                  # the deadline: keep what was taken
        step = "scrolling"
        try:
            at = int(page.evaluate(SCROLL_JS, [bool(inner), i * vh]) or 0)
            page.evaluate(FRAMES_JS)
            step = "waiting for the screen"
            _wait_ready(page)
            step = "hiding the bars"
            page.evaluate(HIDE_JS, i + 1)
            page.evaluate(FRAMES_JS)
            step = "capturing"
            png = page.screenshot(type="png")
        except Exception as e:                                # noqa: BLE001
            why = _why("screen %d, %s" % (i + 1, step), e)
            break
        # the last screen of a page stops where the page ends: the part screen i-1 showed is cut
        screens.append((png, max(0, i * vh - at) if i else 0))
    entries = []
    groups = [screens[k:k + 2] for k in range(0, len(screens), 2)] if tool else [[s] for s in screens]
    first = 1
    for g in groups:
        if len(g) == 2:
            data, w, h, fmt = _glue(g, tool)
        else:
            png, cut = g[0]
            if cut and tool:
                data, w, h, fmt = _glue([g[0]], tool)
            else:
                data, fmt = _alone(png, tool, page)
                w, h = SCREEN_W, vh
        rel = "shots/%02d.%s" % (len(entries) + 1, fmt)
        with open(os.path.join(workdir, rel.replace("/", os.sep)), "wb") as fh:
            fh.write(data)
        entries.append({"file": rel, "width": int(w), "height": int(h), "bytes": len(data), "format": fmt,
                        "screens": list(range(first, first + len(g)))})
        first += len(g)
    return entries, needed, len(screens), why
