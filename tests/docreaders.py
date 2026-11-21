"""EPUB, ODT and RTF read with the standard library (scripts/docreaders.py, 2026-11-20): what each
reader keeps - headings, lists, tables, notes, links, pictures, code, code pages - and how it
answers a hostile file: a cut archive, broken XML, an entity bomb, a zip bomb, deep nesting,
garbage. The hostile files of an independent review (2026-11-21) are built here, small, and each
is read in a child Python killed past its time or its memory, so the old code fails them in
seconds. Then the CLI, which reads these formats with these readers alone (pandoc left --setup on
2026-11-21), and the readers' own process: stopped at its time, one clock for a ZIP's documents.
No network.

    python -X utf8 tests/docreaders.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)

from harness import Checks, run_read     # noqa: E402
import docreaders                        # noqa: E402
import pictures                          # noqa: E402

check = Checks()
TMP = tempfile.mkdtemp(prefix="rp-docreaders-")


def path(name):
    return os.path.join(TMP, name)


CONTAINER = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:'
             'container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/'
             'oebps-package+xml"/></rootfiles></container>')


def epub(name, parts, version="3.0", nav=True, extra=(), raw=False, opf=None, container=None):
    """parts: [(file name, body html)], or their whole text with raw=True; a nav document (left out
    of the text) when nav=True; `opf` / `container`: their raw text instead of the usual ones."""
    items, spine = [], []
    for i, (n, _b) in enumerate(parts):
        items.append('<item id="p%d" href="%s" media-type="application/xhtml+xml"/>' % (i, n))
        spine.append('<itemref idref="p%d"/>' % i)
    if nav:
        items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        spine.insert(0, '<itemref idref="nav"/>')
    with zipfile.ZipFile(path(name), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container if container is not None else CONTAINER)
        z.writestr("OEBPS/content.opf", opf if opf is not None else (
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="%s"><metadata/>'
            '<manifest>%s</manifest><spine>%s</spine></package>' % (version, "".join(items), "".join(spine))))
        if nav:
            z.writestr("OEBPS/nav.xhtml", xhtml('<nav epub:type="toc"><ol><li><a href="c1.xhtml">NAV-ONLY-WORD'
                                                '</a></li></ol></nav>'))
        for n, b in parts:
            z.writestr("OEBPS/" + n, b if raw else xhtml(b))
        for n, data in extra:
            z.writestr(n, data)
    return path(name)


def xhtml(body):
    return ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>HEAD-ONLY-WORD</title></head><body>%s'
            '</body></html>' % body)


NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
      'xmlns:xlink="http://www.w3.org/1999/xlink" '
      'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"')


def odt(name, body, styles="", extra=(), raw=None):
    content = raw if raw is not None else (
        '<?xml version="1.0" encoding="UTF-8"?><office:document-content %s><office:automatic-styles>%s'
        '</office:automatic-styles><office:body><office:text>%s</office:text></office:body>'
        '</office:document-content>' % (NS, styles, body))
    with zipfile.ZipFile(path(name), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        if isinstance(content, (str, bytes)):
            z.writestr("content.xml", content)
        else:
            with z.open("content.xml", "w") as fh:
                for piece in content:
                    fh.write(piece)
        for n, data in extra:
            z.writestr(n, data)
    return path(name)


def rtf(name, data):
    with open(path(name), "wb") as fh:
        fh.write(data)
    return path(name)


def timed(fn, *a):
    t0 = time.time()
    out = fn(*a)
    return out, time.time() - t0


def attempt(fn, *a):
    """fn(*a), or the exception it raised: an API the old code lacks fails a check, not the suite."""
    try:
        return fn(*a)
    except Exception as e:                                     # noqa: BLE001
        return e


def peak_alloc(fn, *a):
    """fn(*a) under tracemalloc: (its result, seconds, the peak of what Python allocated, in MB)."""
    tracemalloc.start()
    t0 = time.time()
    try:
        out = fn(*a)
    finally:
        dt = time.time() - t0
        peak = tracemalloc.get_traced_memory()[1] / float(1 << 20)
        tracemalloc.stop()
    return out, dt, peak


# One docreaders.read() in a child Python (-I -B): it ends itself past `mb` MB of peak memory (a
# watcher thread), and the parent kills it past `wall` seconds; it prints its seconds, note and peak.
CHILD = r"""
import json, os, sys, threading, time
sys.path.insert(0, sys.argv[1])
LIMIT = float(sys.argv[6]) * (1 << 20)


def peak():
    try:                                   # Linux: this process's own high-water mark (ru_maxrss
        with open("/proc/self/status") as fh:     # keeps the parent's across exec)
            for ln in fh:
                if ln.startswith("VmHWM:"):
                    return float(ln.split()[1]) * 1024
    except OSError:
        pass
    try:
        import resource
    except ImportError:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD), ("peak", ctypes.c_size_t)] + \
                [("x%d" % i, ctypes.c_size_t) for i in range(7)]
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return float(c.peak)
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return float(r) if sys.platform == "darwin" else r * 1024.0


def watch():
    while True:
        if peak() > LIMIT:
            os._exit(3)
        time.sleep(0.02)


threading.Thread(target=watch, daemon=True).start()
import docreaders
t0 = time.time()
if sys.argv[3] == "zip":                   # readpage's reading of an archive that does not open whole
    import readpage
    got, info = readpage.zip_whole(sys.argv[2], os.path.dirname(sys.argv[5]))
    md, note = json.dumps({"how": info["how"], "members": info["members"], "whole": len(info["whole"]),
                           "broken": info["broken"][-3:], "more": info["more"]}), info["reason"]
else:
    md, note = docreaders.read(sys.argv[2], sys.argv[3], t0 + float(sys.argv[4]))
with open(sys.argv[5], "w", encoding="utf-8", errors="replace") as fh:
    fh.write(md)
print(json.dumps({"secs": round(time.time() - t0, 3), "note": note[:300], "peak": round(peak() / (1 << 20))}))
"""


def hostile(name, kind, secs=3.0, wall=15.0, mb=300):
    """docreaders.read() of path(name) in a child Python, given `secs`, killed past `wall` seconds or
    `mb` MB: (markdown, info) - info has secs, note and peak (MB), or `killed`."""
    out = path(name + ".md")
    cmd = [sys.executable, "-I", "-B", "-c", CHILD, SCRIPTS, path(name), kind, str(secs), out, str(mb)]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=wall)
    except subprocess.TimeoutExpired:
        return "", {"killed": "past %d s" % wall}
    if p.returncode == 3:
        return "", {"killed": "past %d MB after %.1f s" % (mb, time.time() - t0)}
    try:
        info = json.loads(p.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        with open(out, encoding="utf-8") as fh:
            return fh.read(), info
    except (ValueError, IndexError, OSError):
        return "", {"killed": "rc %s: %s" % (p.returncode, p.stderr.decode("utf-8", "replace")[-200:])}


def fine(info, secs, mb=100):
    """A hostile read that ended by itself, inside `secs` and `mb`."""
    return "killed" not in info and info["secs"] < secs and info["peak"] < mb


def show(info, md=""):
    return "%s, %d chars" % (json.dumps(info)[:220], len(md))


# "Linear, not quadratic" is a ratio, never a number of seconds: a slow runner (macOS on Intel took 3.2 s
# for what takes 0.3 s here) makes every time longer, not the ratio between two sizes on the same machine.
# 4 times the size takes about 4 times as long when the work is linear, 16 times when it is quadratic;
# a ratio over 8 fails. A time under FLOOR is noise, so the smaller read counts as FLOOR at least. A
# ratio that fails is measured again, the best of two (a busy machine slows one read, not both). The
# reader's own time budget is BUDGET, which no machine reaches: it is a guard against a hang, not a bound.
RATIO, FLOOR, BUDGET = 8.0, 0.05, 60.0


def judge(hi, lo):
    """Whether `hi` seconds, the larger input, is within RATIO times `lo` seconds, the smaller."""
    return hi <= RATIO * max(lo, FLOOR)


def scaled(make, kind, small, big, mb=250):
    """The files make(big) and make(small) - make(size) writes one and returns its path - read in a child with
    a budget that cannot cut it: (markdown of the big one, its info plus `small` seconds, `ratio`, `linear`)."""
    def read(n):
        return hostile(make(n), kind, BUDGET, BUDGET + 30, mb)
    md, hi = read(big)
    _, lo = read(small)
    runs = [(hi, lo)]
    if "killed" not in hi and "killed" not in lo and not judge(hi["secs"], lo["secs"]):
        runs.append((read(big)[1], read(small)[1]))
        runs = [r for r in runs if "killed" not in r[0] and "killed" not in r[1]] or runs
    hi = min((r[0] for r in runs), key=lambda i: i.get("secs", 1e9))
    lo = min((r[1] for r in runs), key=lambda i: i.get("secs", 1e9))
    if "killed" in hi or "killed" in lo:
        return md, hi if "killed" in hi else lo
    info = dict(hi)
    info.update(small=lo["secs"], ratio=round(hi["secs"] / max(lo["secs"], FLOOR), 1),
                linear=judge(hi["secs"], lo["secs"]))
    return md, info


def fine_scaled(info, mb=100):
    """A scaled read that ended by itself, in linear time, inside `mb` MB."""
    return "killed" not in info and info["linear"] and info["peak"] < mb


def scaled_call(fn, make, small, big):
    """fn(make(small)) and fn(make(big)) in this process: (the big result, "big/small seconds (ratio)", linear)."""
    def run(arg):
        t0 = time.perf_counter()
        out = fn(arg)
        return out, time.perf_counter() - t0
    big_arg, small_arg = make(big), make(small)
    out, hi = run(big_arg)
    lo = run(small_arg)[1]
    if not judge(hi, lo):
        hi, lo = min(hi, run(big_arg)[1]), min(lo, run(small_arg)[1])
    return out, "%.3fs / %.3fs (ratio %.1f)" % (hi, lo, hi / max(lo, FLOOR)), judge(hi, lo)


# ------------------------------------------------ EPUB
p = epub("book.epub", [
    ("c1.xhtml", '<h1><strong>CHAPTER-ONE</strong></h1><p>First <em>FACT-A</em> and <a href="http://example.org/x">'
                 'a link</a> and <a href="c2.xhtml#s">an inside one</a>.<a epub:type="noteref" href="#n1">1</a></p>'
                 '<aside epub:type="footnote" id="n1"><p>NOTE-ONE text.<a epub:type="backlink" href="#r">BACK</a>'
                 '</p></aside><ul><li>item one<ul><li>INNER-ITEM</li></ul></li><li>item two</li></ul>'
                 '<ol start="3"><li>three</li><li>four</li></ol>'
                 '<pre><code class="language-python">x = 1\n  y = 2</code></pre><p>use <code>git log</code>'
                 '</p><img src="../OEBPS/images/pic one.png" alt="A PICTURE"/>'),
    ("c2.xhtml", '<h2 id="s">CHAPTER-TWO</h2><table><thead><tr><th>Name</th><th>Q1</th><th>Q2</th></tr></thead>'
                 '<tbody><tr><td rowspan="2">Harbor</td><td colspan="2">SPAN-BOTH</td></tr><tr><td>7</td><td>8'
                 '</td></tr></tbody></table><nav epub:type="toc"><ol><li>TOC-IN-PAGE</li></ol></nav>'
                 '<p>See <a href="notes.xhtml#e1" epub:type="noteref">2</a> and <a href="#gone" '
                 'epub:type="noteref">9</a>.</p>'),
    ("notes.xhtml", '<section epub:type="endnotes"><ol><li id="e1" epub:type="endnote"><p>ENDNOTE-TEXT here.</p>'
                    '</li></ol></section>'),
    ("layout.xhtml", '<table><tr><td><h2>LAYOUT-HEADING</h2><p>under it</p></td></tr></table>'),
])
md, note = docreaders.read(p, "epub")
check("epub: the spine in order, the nav document and <head> left out",
      md.index("CHAPTER-ONE") < md.index("CHAPTER-TWO") < md.index("ENDNOTE-TEXT")
      and "NAV-ONLY-WORD" not in md and "HEAD-ONLY-WORD" not in md and note == "", repr(note))
check("epub: headings by level, a bold heading not bold twice",
      "# CHAPTER-ONE\n" in md and "## CHAPTER-TWO" in md and "**CHAPTER-ONE**" not in md, "")
check("epub: emphasis, an outside link as a link, an inside one as its words",
      "*FACT-A*" in md and "[a link](http://example.org/x)" in md and "an inside one" in md
      and "c2.xhtml" not in md, "")
check("epub: a footnote called and kept, its backlink gone",
      "[^1]" in md and "[^1]: NOTE-ONE text." in md and "BACK" not in md, "")
check("epub: an endnote in another part is a definition where the book keeps it",
      "[^2]: ENDNOTE-TEXT here." in md, "")
check("epub: a call whose note is missing keeps what the book showed", "[^3]" not in md and " 9." in md, "")
check("epub: nested and numbered lists",
      "- item one\n  - INNER-ITEM\n- item two" in md and "3. three\n4. four" in md, "")
check("epub: code fenced with its language, inline code in backticks",
      "```python\nx = 1\n  y = 2\n```" in md and "`git log`" in md, "")
check("epub: a picture's path is the one inside the archive",
      "![A PICTURE](OEBPS/images/pic%20one.png)" in md, "")
check("epub: a table keeps its grid - merged cells leave their places empty",
      "| Name | Q1 | Q2 |" in md and "| Harbor | SPAN-BOTH |  |" in md and "|  | 7 | 8 |" in md, "")
check("epub: a table of contents inside a page is not repeated", "TOC-IN-PAGE" not in md, "")
check("epub: a one-column layout table gives its blocks, headings and all", "## LAYOUT-HEADING" in md, "")
p2 = epub("old.epub", [("text one.xhtml", "<p>EPUB-TWO-TEXT <b>bold</b></p>")], version="2.0", nav=False)
md2, _n = docreaders.read(p2, "epub")
check("epub 2: no nav document, a part named with a space", "EPUB-TWO-TEXT **bold**" in md2, repr(md2[:80]))

# ------------------------------------------------ ODT
STY = ('<style:style style:name="B" style:family="text"><style:text-properties fo:font-weight="bold"/>'
       '</style:style><style:style style:name="HS" style:family="paragraph" style:default-outline-level="2">'
       '<style:text-properties fo:font-weight="bold"/></style:style>'
       '<text:list-style style:name="N"><text:list-level-style-number text:level="1" style:num-format="1"/>'
       '<text:list-level-style-bullet text:level="2" text:bullet-char="-"/></text:list-style>')
p = odt("doc.odt", (
    '<text:h text:outline-level="1">ODT-HEAD</text:h><text:p text:style-name="HS">NOT-A-HEADING</text:p>'
    '<text:p>Menu <text:span text:style-name="B">Extras</text:span><text:span text:style-name="B">→Options'
    '</text:span> and <text:a xlink:href="https://example.org/">a link</text:a>.<text:note text:note-class='
    '"footnote"><text:note-citation>1</text:note-citation><text:note-body><text:p>ODT-NOTE text.</text:p>'
    '</text:note-body></text:note><text:span><text:tracked-changes/>kept</text:span>'
    '<office:annotation><text:p>COMMENT-WORD</text:p></office:annotation></text:p>'
    '<text:list text:style-name="N"><text:list-item><text:p>first</text:p><text:list><text:list-item>'
    '<text:p>SUB-ITEM</text:p></text:list-item></text:list></text:list-item><text:list-item><text:p>second'
    '</text:p></text:list-item></text:list>'
    '<table:table><table:table-header-rows><table:table-row><table:table-cell><text:p>Region</text:p>'
    '</table:table-cell><table:table-cell table:number-columns-spanned="2"><text:p>Quarters</text:p>'
    '</table:table-cell><table:covered-table-cell/></table:table-row></table:table-header-rows><table:table-row>'
    '<table:table-cell><text:p>North</text:p></table:table-cell><table:table-cell><text:p>1</text:p>'
    '</table:table-cell><table:table-cell><text:p>2</text:p></table:table-cell></table:table-row></table:table>'
    '<text:p><draw:frame draw:name="F1"><draw:image xlink:href="Pictures/p.png"/><svg:title>ODT PICTURE'
    '</svg:title></draw:frame><draw:frame><draw:text-box><text:p>CAPTION-TEXT</text:p></draw:text-box>'
    '</draw:frame><draw:frame><draw:object xlink:href="./Object 1"/><draw:image xlink:href="./Object'
    'Replacements/Object 1"/></draw:frame></text:p>'), STY,
    extra=[("Object 1/content.xml", '<math xmlns="http://www.w3.org/1998/Math/MathML"><semantics><mi>x</mi>'
                                    '<annotation encoding="StarMath 5.0">x over 2 = FORMULA</annotation>'
                                    '</semantics></math>')])
md, note = docreaders.read(p, "odt")
check("odt: a text:h is a heading; a text:p in a heading's style is a bold paragraph",
      "# ODT-HEAD" in md and "**NOT-A-HEADING**" in md and "# NOT-A-HEADING" not in md, "")
check("odt: two bold spans side by side are one bold run", "**Extras→Options**" in md and "****" not in md, "")
check("odt: a link, a footnote at the end, a comment left out",
      "[a link](https://example.org/)" in md and "[^1]" in md and "[^1]: ODT-NOTE text." in md
      and "COMMENT-WORD" not in md and "kept" in md, "")
check("odt: a numbered list holding a bulleted one", "1. first\n   - SUB-ITEM\n2. second" in md, repr(md[:0]))
check("odt: a table with a merged cell keeps its grid",
      "| Region | Quarters |  |" in md and "| North | 1 | 2 |" in md, "")
check("odt: a picture with its title, a text box's text after its paragraph, a formula's source",
      "![ODT PICTURE](Pictures/p.png)" in md and "CAPTION-TEXT" in md and "`x over 2 = FORMULA`" in md
      and "ObjectReplacements" not in md, "")

# ------------------------------------------------ ODS and ODP, as LibreOffice writes them
NS_PRES = NS + (' xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"')


def odf(name, mimetype, body, extra=(), raw=None):
    """An OpenDocument file whose office:body holds `body` (a spreadsheet's or a presentation's), or
    whose content.xml is `raw`."""
    with zipfile.ZipFile(path(name), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), mimetype)
        z.writestr("content.xml", raw if raw is not None else (
            '<?xml version="1.0" encoding="UTF-8"?><office:document-content %s office:version="1.3">'
            '<office:body>%s</office:body></office:document-content>' % (NS_PRES, body)))
        for n, data in extra:
            z.writestr(n, data)
    return path(name)


def cells(*texts, empty_after=1021):
    return "".join('<table:table-cell office:value-type="string"><text:p>%s</text:p></table:table-cell>' % t
                   for t in texts) + '<table:table-cell table:number-columns-repeated="%d"/>' % empty_after


ODS_BODY = ('<office:spreadsheet><table:table table:name="Sales"><table:table-column table:number-columns-repeated="3"/>'
            '<table:table-row>%s</table:table-row><table:table-row>%s</table:table-row>'
            '<table:table-row table:number-rows-repeated="100">%s</table:table-row>'
            '<table:table-row table:number-rows-repeated="1048000"><table:table-cell table:number-columns-repeated="1024"/>'
            '</table:table-row></table:table>'
            '<table:table table:name="Empty"><table:table-row table:number-rows-repeated="1048576">'
            '<table:table-cell table:number-columns-repeated="1024"/></table:table-row></table:table>'
            '<table:table table:name="Notes"><table:table-row><table:table-cell><text:p>ONE-COLUMN-NOTE</text:p>'
            '<office:annotation><text:p>COMMENT-WORD</text:p></office:annotation></table:table-cell></table:table-row>'
            '</table:table></office:spreadsheet>'
            % (cells("Region", "Q1", "Q2"), cells("North", "12", "24"), cells("Zero", "0", "0")))
p = odf("sheet.ods", "application/vnd.oasis.opendocument.spreadsheet", ODS_BODY)
md, note = docreaders.read(p, "ods")
check("ods: each sheet a heading and its table; rows repeated as the sheet says, empty ones and empty sheets left out",
      "## Sales" in md and "| Region | Q1 | Q2 |" in md and "| North | 12 | 24 |" in md
      and md.count("| Zero | 0 | 0 |") == 100 and "Empty" not in md, "%r %r" % (md[:120], note))
check("ods: a sheet of one column is its paragraphs, a cell's comment left out",
      "## Notes" in md and "ONE-COLUMN-NOTE" in md and "COMMENT-WORD" not in md, repr(md[-80:]))
ODP_BODY = (
    '<office:presentation><draw:page draw:name="page1">'
    '<draw:frame presentation:class="title"><draw:text-box><text:p>SLIDE-ONE-TITLE</text:p></draw:text-box></draw:frame>'
    '<draw:frame presentation:class="outline"><draw:text-box><text:list><text:list-item><text:p>first point</text:p>'
    '</text:list-item><text:list-item><text:p>second point</text:p></text:list-item></text:list></draw:text-box>'
    '</draw:frame><draw:frame><draw:image xlink:href="Pictures/chart.png"/><svg:title>THE CHART</svg:title></draw:frame>'
    '<presentation:notes><draw:page-thumbnail draw:page-number="1"/><draw:frame presentation:class="notes">'
    '<draw:text-box><text:p>SPEAKER-NOTE text.</text:p></draw:text-box></draw:frame></presentation:notes></draw:page>'
    '<draw:page draw:name="page2"><draw:frame><table:table><table:table-row><table:table-cell><text:p>CELL-A</text:p>'
    '</table:table-cell><table:table-cell><text:p>CELL-B</text:p></table:table-cell></table:table-row><table:table-row>'
    '<table:table-cell><text:p>CELL-C</text:p></table:table-cell><table:table-cell><text:p>CELL-D</text:p>'
    '</table:table-cell></table:table-row></table:table></draw:frame>'
    '<draw:custom-shape><text:p>SHAPE-TEXT</text:p></draw:custom-shape>'
    '<draw:g><draw:frame><draw:text-box><text:p>GROUPED-TEXT</text:p></draw:text-box></draw:frame></draw:g>'
    '</draw:page></office:presentation>')
p = odf("deck.odp", "application/vnd.oasis.opendocument.presentation", ODP_BODY)
md, note = docreaders.read(p, "odp")
at = [md.find(x) for x in ("## Slide 1", "SLIDE-ONE-TITLE", "- first point\n- second point",
                           "![THE CHART](Pictures/chart.png)", "notes: SPEAKER-NOTE text.", "## Slide 2")]
check("odp: a slide a heading, its title, its list, its picture, then its notes",
      min(at) >= 0 and at == sorted(at), "%s %r %r" % (at, md[:200], note))
check("odp: a table in a frame is a table; a shape's and a group's text are kept",
      "| CELL-A | CELL-B |" in md and "| CELL-C | CELL-D |" in md and "SHAPE-TEXT" in md and "GROUPED-TEXT" in md,
      repr(md[-160:]))

# ------------------------------------------------ RTF
R = (b"{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0\\fswiss\\fcharset0 Arial;}{\\f1\\fcharset204 Times;}"
     b"{\\f2\\fcharset134 SimSun;}{\\f3\\fcharset2 Symbol;}}"
     b"{\\stylesheet{\\s0 Normal;}{\\s1\\outlinelevel0 heading 1;}{\\s2 heading 2;}}"
     b"{\\*\\listtable{\\list\\listtemplateid1{\\listlevel\\levelnfc0}{\\listlevel\\levelnfc23}\\listid7}}"
     b"{\\*\\listoverridetable{\\listoverride\\listid7\\listoverridecount0\\ls1}}"
     b"{\\info{\\title INFO-TITLE}}{\\header HEADER-WORD\\par}"
     b"\\pard\\s1 RTF-HEADING\\par\\pard\\s2 Second level\\par"
     b"\\pard\\plain\\f1 \\'cf\\'f0\\'e8\\'e2\\'e5\\'f2 \\uc1\\u1052\\'cc\\u1080\\'e8\\u1088\\'f0 \\f2 \\'d6\\'d0\\'ce\\'c4"
     b"\\f0  {\\v HIDDEN-WORD}{\\*\\bkmkstart b}{\\pict\\pngblip 89504e47}\\par"
     b"\\pard\\ls1\\ilvl0{\\listtext 1.\\tab}first item\\par\\pard\\ls1\\ilvl1{\\listtext\\f3 \\'b7\\tab}inner item\\par"
     b"\\pard\\ls1\\ilvl0{\\listtext 2.\\tab}second item\\par"
     b"\\pard\\trowd\\cellx3000\\cellx6000\\cellx9000\\intbl{\\b TASK}\\cell NUMBER\\cell STRING\\cell\\row"
     b"\\trowd\\cellx6000\\cellx9000\\intbl Wide label\\cell -\\cell\\row"
     b"\\pard See{\\super\\chftn}{\\footnote\\pard\\plain{\\super\\chftn} RTF-NOTE text.}"
     b" and {\\field{\\*\\fldinst{HYPERLINK \"https://example.org/r\"}}{\\fldrslt{the site}}}"
     b" and {\\field{\\*\\fldinst{HYPERLINK \\\\l \"_Toc1\"}}{\\fldrslt{inside}}}.\\par"
     b"\\pard after \\bin3 {}}x\\par}")
md, note = docreaders.read(rtf("doc.rtf", R), "rtf")
check("rtf: headings from the style sheet, by outline level and by name",
      "# RTF-HEADING" in md and "## Second level" in md, "")
check("rtf: a font's code page (cp1251, GBK) and \\u with its fallback skipped",
      "Привет Мир" in md and "中文" in md and "Ìèð" not in md, repr(md[:200]))
check("rtf: hidden text, the info group, a header, a picture's data, a bookmark left out",
      not any(w in md for w in ("HIDDEN-WORD", "INFO-TITLE", "HEADER-WORD", "89504e47", "bkmk")), "")
check("rtf: lists from \\listtext, numbered and bulleted, nested",
      "1. first item\n   - inner item\n2. second item" in md, "")
check("rtf: a table on its columns - a cell over two columns, a '-' left as it is",
      "| **TASK** | NUMBER | STRING |" in md and "| Wide label |  | - |" in md, "")
check("rtf: a footnote at the end, a hyperlink as a link, an inside link as its words",
      "See[^1]" in md and "[^1]: RTF-NOTE text." in md and "[the site](https://example.org/r)" in md
      and "inside" in md and "_Toc1" not in md, "")
check("rtf: \\binN data jumped over, braces in it and all", "after x" in md, repr(md[-60:]))
md, note = docreaders.read(rtf("garbage.rtf", b"{\\rtf1 " + bytes(range(256)) * 400 + b"}"), "rtf")
check("rtf: binary data after {\\rtf1 is not taken for text",
      md == "" and note.startswith("not text"), repr(note))

# ------------------------------------------------ hostile files
data = open(path("book.epub"), "rb").read()
open(path("cut.epub"), "wb").write(data[:len(data) // 2])
(md, note), secs = timed(docreaders.read, path("cut.epub"), "epub")
check("hostile: a cut archive is named, not a crash", md == "" and "not a whole archive" in note, repr(note))
p = odt("broken.odt", "<text:p>BEFORE-BREAK</text:p><text:p>after</text:bogus>")
md, note = docreaders.read(p, "odt")
check("hostile: XML that breaks keeps what came before it", "BEFORE-BREAK" in md and "breaks" in note, repr(note))
LAUGHS = ('<!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">' + "".join(
    '<!ENTITY %s "%s">' % (chr(98 + i), ("&%s;" % chr(97 + i)) * 10) for i in range(8)) + ']>')
p = odt("laughs.odt", "", raw='<?xml version="1.0"?>%s<office:document-content %s><office:body><office:text>'
        '<text:p>&i;</text:p></office:text></office:body></office:document-content>' % (LAUGHS, NS))
(md, note), secs = timed(docreaders.read, p, "odt")
check("hostile: an entity bomb is refused (a DOCTYPE)", md == "" and "DOCTYPE" in note and secs < 2,
      "%.2fs %r" % (secs, note))
head = ('<?xml version="1.0"?><office:document-content %s><office:body><office:text><text:p>BOMB-START'
        % NS).encode()


def bomb():
    yield head
    for _ in range(64):
        yield b" " * (1 << 20)
    yield b"</text:p></office:text></office:body></office:document-content>"


p = odt("bomb.odt", None, raw=bomb())
(md, note), secs = timed(docreaders.read, p, "odt")
check("hostile: a part that unpacks past the limit is read up to it, quickly",
      "over the size limit" in note and secs < 5, "%.2fs %r" % (secs, note[:80]))
os.environ["READ_PAGE_CACHE"] = os.path.join(TMP, "cache")        # readpage's own folders: ours
import readpage                              # noqa: E402
got, secs = timed(attempt, docreaders.odf_plain, p)
check("the plain OpenDocument reader (when a reader breaks) reads a part past the limit up to it, and says so",
      isinstance(got, tuple) and "BOMB-START" in got[0] and secs < 5 and "size limit" in got[1],
      "%.2fs %r" % (secs, got if not isinstance(got, tuple) else (got[0][:40], got[1])))
p = epub("deep.epub", [("c1.xhtml", "<div><span>" * 50000 + "DEEP" + "</span></div>" * 50000)], nav=False)
(md, note), secs = timed(docreaders.read, p, "epub")
check("hostile: 50 000 nested elements in a page, read in seconds", "DEEP" in md and secs < 10, "%.2fs" % secs)
(md, note), secs = timed(docreaders.read, rtf("braces.rtf", b"{\\rtf1 " + b"{" * 300000 + b"x" + b"}" * 300000 +
                                               b" END}"), "rtf")
check("hostile: 300 000 nested RTF groups, read in seconds", "END" in md and secs < 10, "%.2fs" % secs)
src = zipfile.ZipFile(path("book.epub"))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for i in src.infolist():
        z.writestr(i, src.read(i))
raw = bytearray(buf.getvalue())
k = raw.find(b"OEBPS/c2.xhtml") + 30
raw[k:k + 40] = bytes(b ^ 0x5A for b in raw[k:k + 40])
open(path("damaged.epub"), "wb").write(bytes(raw))
md, note = docreaders.read(path("damaged.epub"), "epub")
check("hostile: a damaged part is named, the others read", "CHAPTER-ONE" in md and "could not be unpacked" in note,
      repr(note))
try:
    readpage.zip_images(path("damaged.epub"), TMP)
    check("hostile: a damaged part does not stop the pictures' order (was: internal error)", True, "")
except Exception as e:                                         # noqa: BLE001
    check("hostile: a damaged part does not stop the pictures' order (was: internal error)", False, repr(e))

# ------------------------------------------------ hostile files: each small, each read in a child
TRAP = "<p>Before the trap: the book's own words.</p>"
TRAP_ODT = "<text:p>Before the trap: the document's own words.</text:p>"
TRAP_RTF = b"{\\rtf1\\ansi Before the trap: the document's own words.\\par "

# what a table builds is capped per table and per document, not per cell or row
row = "<tr>" + '<td rowspan="512" colspan="64">x</td>' * 5 + "</tr>"
epub("spans.epub", [("c1.xhtml", TRAP + "<table>" + row * 20 + "</table>")], nav=False)
md, info = hostile("spans.epub", "epub")
check("an EPUB table whose every cell spans 512 rows and 64 columns stays small (1 KB took 494 MB)",
      fine(info, 3, 80) and "Before the trap" in md and len(md) < 1000000, show(info, md))
row = ('<table:table-row table:number-rows-repeated="64">' + '<table:table-cell table:number-columns-repeated="64">'
       '<text:p>x</text:p></table:table-cell>' * 8 + '</table:table-row>')
odt("repeats.odt", TRAP_ODT + "<table:table>" + row * 313 + "</table:table>")
md, info = hostile("repeats.odt", "odt")
check("an ODT table of rows and cells repeated 64 times each stays small (4.5 KB took 40 s, 164 MB out)",
      fine(info, 3, 120) and "Before the trap" in md and len(md) < 3000000 and "cut" in info.get("note", ""),
      show(info, md))
# a sheet repeats what it holds without the ODT's 64: what it builds is the grid's caps alone
row = ('<table:table-row table:number-rows-repeated="1000000">' + '<table:table-cell table:number-columns-repeated='
       '"100000"><text:p>x</text:p></table:table-cell>' * 8 + '</table:table-row>')
odf("repeats.ods", "application/vnd.oasis.opendocument.spreadsheet",
    '<office:spreadsheet>' + ''.join('<table:table table:name="S%d">%s</table:table>' % (k, row * 50)
                                     for k in range(20)) + '</office:spreadsheet>')
md, info = hostile("repeats.ods", "ods")
check("an ODS of 20 sheets of rows and cells repeated a million and 100 000 times stays small, and says it is cut",
      fine(info, 3, 150) and len(md) < 6000000 and "cut" in info.get("note", ""), show(info, md))
md, info = scaled(lambda n: rtf("cellx.rtf", TRAP_RTF + b"\\trowd\\cellx9000000" +
                                b"".join(b"\\cellx%d" % (20 * (k + 1)) for k in range(n)) +
                                b"\\intbl a\\cell\\row" * n + b"\\pard after\\par}"), "rtf", 750, 3000)
check("an RTF row of 3 000 borders over 3 000 rows is read in linear time (4 000 took 15.9 s)",
      fine_scaled(info, 120) and "Before the trap" in md and "after" in md, show(info, md))
odt("spaces.odt", "<text:p>a%sb</text:p>" % ('<text:s text:c="200"/>' * 50000))
md, info = hostile("spaces.odt", "odt")
check("50 000 runs of 200 spaces in an ODT do not make 10 MB of them", fine(info, 3) and len(md) < 2000000,
      show(info, md))

# no scan is quadratic - tags that never close, a long spine, the tree builder's rules
md, info = scaled(lambda n: epub("noteref.epub", [("c1.xhtml", xhtml(TRAP) + "<a " * n)], nav=False, raw=True),
                  "epub", 2500, 10000)
check("a chapter ending in 10 000 unclosed <a is read in linear time (100 KB took 87.5 s)",
      fine_scaled(info) and "Before the trap" in md, show(info, md))
md, info = scaled(lambda n: epub("opf.epub", [("c1.xhtml", TRAP)], nav=False,
                                 opf='<?xml version="1.0"?><package><manifest>' + "<item " * n),
                  "epub", 10000, 40000)
check("an OPF of 40 000 unclosed <item is read in linear time (400 KB took 20.6 s)",
      fine_scaled(info) and "Before the trap" in md, show(info, md))
md, info = scaled(lambda n: epub("container.epub", [("c1.xhtml", TRAP)], nav=False,
                                 container='<?xml version="1.0"?><container>' + "<rootfile " * n),
                  "epub", 7500, 30000)
check("a container of 30 000 unclosed <rootfile is read in linear time (400 KB took 12.4 s)",
      fine_scaled(info) and "Before the trap" in md, show(info, md))


def spine(n):
    items = "".join('<item id="i%d" href="p%d.xhtml" media-type="application/xhtml+xml"/>' % (k, k) for k in range(n))
    refs = "".join('<itemref idref="i%d"/>' % k for k in range(n))
    return epub("spine.epub", [("p0.xhtml", TRAP)], nav=False,
                opf='<?xml version="1.0"?><package><manifest>%s</manifest><spine>%s</spine></package>' % (items, refs))


md, info = scaled(spine, "epub", 7500, 30000)
check("a spine of 30 000 distinct parts is read in linear time (40 000 took 13.9 s)",
      fine_scaled(info) and "Before the trap" in md, show(info, md))
md, info = scaled(lambda n: epub("button.epub", [("c1.xhtml", TRAP + "<p>open<button>" + "<span>" * n + "<hr>" * (n // 10))],
                                 nav=False), "epub", 12500, 50000)
check("an open <p> under a <button>, 50 000 deep, then 5 000 tags that close a <p> (each walked the stack)",
      fine_scaled(info) and "Before the trap" in md, show(info, md))
md, info = scaled(lambda n: epub("stray.epub", [("c1.xhtml", TRAP + "<p>" + ("a" * 30 + "</x>") * n + "</p>")], nav=False),
                  "epub", 50000, 200000)
check("200 000 stray end tags in a 6 MB paragraph: its text is not copied again at each of them",
      fine_scaled(info) and "aaaa" in md, show(info, md))
md, info = scaled(lambda n: epub("feeds.epub", [("c1.xhtml", TRAP + "<p>" + "<a " * n + "></p>")], nav=False),
                  "epub", 350000, 1400000)
# (it was 3 s and 200 MB, then 6 s and 250 MB: a macOS 26 runner peaked at 201 MB in 1.2 s, a macOS Intel runner took
# 4.1 s and then 3.2 s of a 3 s budget, 2026-11-21. Before the fix the read took 2.5 s on Python 3.13 and 19.7 s on
# 3.9 (KNOWN-ISSUES 153): 1 MB and 4 MB are read on the same machine, a ratio near 4 is linear, near 16 is not)
check("one tag 4 MB long is not scanned again at every 64 KB the parser is fed (4 MB in under 8 times 1 MB)",
      fine_scaled(info, 250) and "Before the trap" in md, show(info, md))

# a run of unclosed ![ is linear, and a book's own Markdown characters stay text
md, info = scaled(lambda n: epub("pics.epub", [("c1.xhtml", TRAP + "<p>" + "![" * n + "</p>")], nav=False),
                  "epub", 2500, 10000)
check("a paragraph of 10 000 unclosed ![ is read in linear time (40 KB took 32.7 s)",
      fine_scaled(info) and "Before the trap" in md, show(info, md))
got, note, linear = scaled_call(lambda s: pictures.links(s[0]) + pictures.links(s[1]),
                                lambda n: ("![" * n, "![](" * n), 2000, 8000)
check("the picture pass is linear on 8 000 unclosed ![ and on 8 000 ![]( (16 KB took 2.2 and 4.5 s)",
      got == [] and linear, note)
got, note, linear = scaled_call(pictures.links, lambda n: "x\n" + "\n" * n + "![a](b.png)", 7500, 30000)
check("30 000 blank lines cost the picture pass's fence scan nothing (it was quadratic)",
      len(got) == 1 and linear, note)
p = epub("literal.epub", [("c1.xhtml", '<p><a href="http://example.org/spi"><img src="images/spi.png" alt="SPI"/>'
                                          '</a></p><p>A literal ![x](y), *****, [z] and _w_.</p>')], nav=False)
md, note = docreaders.read(p, "epub")
links = pictures.links(md)
check("a book's literal ![x](y), *****, [z] and _w_ stay text (they became a picture and emphasis)",
      "!\\[x\\](y)" in md and "\\*\\*\\*\\*\\*" in md and "\\[z\\]" in md and "\\_w\\_" in md and len(links) == 1,
      repr(md[-120:]))
check("a linked picture keeps its address", "[![SPI](OEBPS/images/spi.png)](http://example.org/spi)" in md,
      repr(md[:120]))

# long RTF lists - one join, a level within RTF's 0-8
md, info = scaled(lambda n: rtf("list.rtf", TRAP_RTF + b"\\ls1 " + b"An item of a long list, forty-some characters\\par " * n +
                                b"}"), "rtf", 10000, 40000)
check("an RTF list of 40 000 items is read in linear time (100 000 took 60 s, past the deadline)",
      fine_scaled(info) and md.count("- An item") == 40000, show(info, md))
rtf("ilvl.rtf", TRAP_RTF + b"\\ls1 " + b"".join(b"\\ilvl%d item\\par " % k for k in range(2000)) + b"}")
md, info = hostile("ilvl.rtf", "rtf")
check("\\ilvl0 to \\ilvl1999 do not indent 2 000 levels deep (4 000 gave 16 MB of spaces)",
      fine(info, 2) and md.count("item") == 2000 and len(md) < 200000, show(info, md))
md, info = scaled(lambda n: rtf("counters.rtf", TRAP_RTF + b"".join(b"\\pard\\ls%d{\\listtext 1.\\tab}x\\par " % k
                                                                    for k in range(n)) + b"}"), "rtf", 5000, 20000)
check("20 000 numbered lists of their own are counted in linear time (each looked at every other)",
      fine_scaled(info) and md.count("1. x") == 20000, show(info, md))

# the DOCTYPE guard through a newline, a BOM, UTF-16, a space; in a formula and in styles.xml
BODY = ("<office:document-content %s><office:body><office:text>%s<text:p>&i;</text:p></office:text></office:body>"
        "</office:document-content>" % (NS, TRAP_ODT))
for label, content in (("a newline", '<?xml version="1.0"?>\n' + LAUGHS + BODY),
                       ("a BOM", "﻿" + '<?xml version="1.0"?>' + LAUGHS + BODY),
                       ("UTF-16", ('<?xml version="1.0" encoding="UTF-16"?>' + LAUGHS + BODY).encode("utf-16")),
                       ("a space", " " + LAUGHS + BODY)):
    odt("doctype.odt", "", raw=content)
    md, info = hostile("doctype.odt", "odt", mb=200)
    check("a DOCTYPE after %s is refused before expat reads it" % label,
          fine(info, 2) and md == "" and "DOCTYPE" in info.get("note", ""), show(info, md))
odt("formula.odt", TRAP_ODT + '<text:p><draw:frame><draw:object xlink:href="./Object 1"/></draw:frame></text:p>',
    extra=[("Object 1/content.xml", '<?xml version="1.0"?>\n' + LAUGHS.replace("<!DOCTYPE l", "<!DOCTYPE math") +
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>&i;</mi></math>')])
md, info = hostile("formula.odt", "odt", mb=200)
check("a formula that declares a DOCTYPE is left out, and the note says so (it went silently)",
      fine(info, 2) and "Before the trap" in md and "DOCTYPE" in info.get("note", ""), show(info, md))
odt("styles.odt", TRAP_ODT, extra=[("styles.xml", '<?xml version="1.0"?>\n' + LAUGHS +
                                       "<office:document-styles %s>&i;</office:document-styles>" % NS)])
md, info = hostile("styles.odt", "odt", mb=200)
check("a styles.xml that declares a DOCTYPE is left out, and the note says so (it went silently)",
      fine(info, 2) and "Before the trap" in md and "DOCTYPE" in info.get("note", ""), show(info, md))
p = odt("plain.odt", "", raw='<?xml version="1.0"?>\n' + LAUGHS + BODY)
got = attempt(docreaders.odf_plain, p)
check("the plain OpenDocument reader refuses the DOCTYPE too, and says so",
      isinstance(got, tuple) and got[0] == "" and "DOCTYPE" in got[1], repr(got))
for kind, mime in (("ods", "spreadsheet"), ("odp", "presentation")):
    odf("doctype." + kind, "application/vnd.oasis.opendocument." + mime, "", raw='<?xml version="1.0"?>\n' + LAUGHS + BODY)
    md, info = hostile("doctype." + kind, kind, mb=200)
    check("an %s that declares a DOCTYPE is refused, in the readers' process" % kind.upper(),
          fine(info, 2) and md == "" and "DOCTYPE" in info.get("note", ""), show(info, md))

# one bad element loses that element, not the document; what is lost is named
p = epub("table.epub", [("c1.xhtml", "<p>Chapter one.</p>"),
                           ("c2.xhtml", "<table>" + "<div>" * 1500 + "DEEP-CELL" + "</div>" * 1500 + "</table>")])
md, note = docreaders.read(p, "epub")
check("a table holding 1 500 nested <div> keeps the book, the cell's words too (was: the reader failed)",
      "Chapter one." in md and "DEEP-CELL" in md, repr(note))
p = epub("ul.epub", [("c1.xhtml", "<p>Chapter one.</p>"), ("c2.xhtml", "<ul>" * 1500 + "<li>DEEP-ITEM</li>" +
                                                                 "</ul>" * 1500)])
md, note = docreaders.read(p, "epub")
check("1 500 <ul> nested in each other keep the book (was: the reader failed)",
      "Chapter one." in md and "DEEP-ITEM" in md, repr(note))
for label, body in (("lists", "<text:list><text:list-item>" * 1200 + "<text:p>DEEP</text:p>" +
                     "</text:list-item></text:list>" * 1200),
                    ("cells", "<table:table><table:table-row><table:table-cell>" * 1200 + "<text:p>DEEP</text:p>" +
                     "</table:table-cell></table:table-row></table:table>" * 1200),
                    ("draw:a", "<text:p>" + "<draw:a>" * 1200 + "DEEP" + "</draw:a>" * 1200 + "</text:p>")):
    md, note = docreaders.read(odt("nested.odt", TRAP_ODT + body), "odt")
    check("ODT %s nested 1 200 deep keep the document (was: the reader failed)" % label,
          "Before the trap" in md and "DEEP" in md, repr(note))
p = epub("bogus.epub", [("c1.xhtml", "<p>Chapter one.</p>"), ("c2.xhtml", "<p>two</p><![bogus[ x ]]><p>AFTER</p>")])
md, note = docreaders.read(p, "epub")
check("a bogus <![x[ section keeps the book (Python 3.8 and 3.13.2: the reader failed)",
      "Chapter one." in md and "AFTER" in md, repr(note))
for esc in (b"\\u1114112", b"\\u-70000"):
    md, note = docreaders.read(rtf("u.rtf", TRAP_RTF + b"one bad escape " + esc + b" ends it\\par AFTER}"), "rtf")
    check("an RTF escape %s out of Unicode's range is one U+FFFD (was: the reader failed)" % esc.decode(),
          "Before the trap" in md and "AFTER" in md and "�" in md, repr(note))
real = docreaders._Html.blocks


def broken(self, el, depth=0):
    if self.doc.endswith("c2.xhtml"):
        raise ValueError("a part that breaks")
    return real(self, el, depth)


docreaders._Html.blocks = broken
try:
    md, note = docreaders.read(path("book.epub"), "epub")
finally:
    docreaders._Html.blocks = real
check("a part whose reading breaks is named, and the parts around it are read",
      "CHAPTER-ONE" in md and "ENDNOTE-TEXT" in md and "c2.xhtml" in note, repr(note))

# RTF runs that pile up, emphasis many levels deep, the first loop's clock, the --download promise
rtf("runs.rtf", b"{\\rtf1\\ansi " + b"x\\b x\\b0 " * 400000 + b"}")
md, info = hostile("runs.rtf", "rtf")
check("800 000 runs before one \\par take little memory (2 million took 904 MB)", fine(info, 4, 80), show(info, md))
got, note, linear = scaled_call(docreaders._marks, lambda n: "a" + "\x0e/*\x0f" * n + "\x0e*\x0f" * n + "b", 5000, 20000)
check("20 000 levels of emphasis side by side are joined in one pass (it was one pass a level)",
      got == "ab" and linear, "%s %r" % (note, got[:20]))
got, note, linear = scaled_call(docreaders._one_line, lambda n: "\xa0 " * n + "x", 10000, 40000)
check("a run of 40 000 no-break spaces is one line in linear time (it was quadratic)", got.endswith("x") and linear,
      note)
epub("parts.epub", [("p%05d.xhtml" % k, "<p>part %d</p>" % k) for k in range(20000)], nav=False)
(md, note), secs = timed(docreaders.read, path("parts.epub"), "epub", time.time() - 1)
check("a book out of time stops at once, and does not promise --download for 0 parts read",
      secs < 2 and "time ran out" in note and "--download" not in note, "%.2fs %r" % (secs, note))   # 0.38 s on a macOS Intel runner
TYPES = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
         '<Override PartName="/word/document.xml" ContentType="%s"/></Types>')


def package(types, rels):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", '<w:document xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/main"/>')
    return buf.getvalue()


REL = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Type="%s"/>' \
      '</Relationships>'
dotx = package(TYPES % "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
               REL % "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument")
got = zipfile.ZipFile(io.BytesIO(readpage.office_plain(dotx, "docx"))).read("[Content_Types].xml")
check("office: a template's main part is given the plain type (python-docx refused .dotx/.docm)",
      b"wordprocessingml.document.main+xml" in got and b"template" not in got, got[-120:])
strict = package(TYPES % "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
                 REL % "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument")
z = zipfile.ZipFile(io.BytesIO(readpage.office_plain(strict, "docx")))
check("office: Strict OOXML's namespaces become the transitional ones",
      b"schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" in z.read("_rels/.rels")
      and b"schemas.openxmlformats.org/wordprocessingml/2006/main" in z.read("word/document.xml"), "")
plain = package(TYPES % "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
                REL % "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument")
check("office: a plain package is left byte for byte", readpage.office_plain(plain, "docx") is plain, "")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for i in zipfile.ZipFile(io.BytesIO(dotx)).infolist():
        z.writestr(i.filename, zipfile.ZipFile(io.BytesIO(dotx)).read(i))
    z.writestr("word/media/big.png", b"\x00" * (60 << 20))
got, secs, peak = peak_alloc(readpage.office_plain, buf.getvalue(), "docx")
check("a template's 60 MB picture is not unpacked to give python-docx the plain type (it was, and zipped again)",
      peak < 20 and b"document.main+xml" in zipfile.ZipFile(io.BytesIO(got)).read("[Content_Types].xml"),
      "%.2fs, %.0f MB" % (secs, peak))

# KNOWN-ISSUES 133: an archive's parts are read with a size cap of their own
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("mimetype", b"application/epub+zip" + b" " * (60 << 20))
    z.writestr("OEBPS/content.opf", "<package/>")
got, secs, peak = peak_alloc(readpage.zip_subtype, buf.getvalue())
check("133: an archive's mimetype that unpacks to 60 MB is read up to its first bytes", got == "epub" and peak < 10,
      "%s %.2fs, %.0f MB" % (got, secs, peak))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("word/document.xml", "<w:document/>")
    z.writestr("word/footnotes.xml", "<w:footnotes><w:t>" + "n" * (60 << 20) + "</w:t></w:footnotes>")
got, secs, peak = peak_alloc(readpage.docx_notes, buf.getvalue())
check("133: a docx's footnotes that unpack to 60 MB are read up to a cap", peak < 50, "%.2fs, %.0f MB" % (secs, peak))

# ------------------------------------------------ the CLI: these readers, with a machine's own pandoc there or not
for name, fact in (("book.epub", "ENDNOTE-TEXT"), ("doc.odt", "ODT-NOTE"), ("doc.rtf", "RTF-NOTE"),
                   ("sheet.ods", "ONE-COLUMN-NOTE"), ("deck.odp", "SPEAKER-NOTE")):
    r = run_read(path(name), env={"READ_PAGE_SKIP": "browser", "READ_PAGE_TRACE": "1"})
    text = r.file("content.md")
    check("cli: %s is read by our reader, its notes too" % name,
          r.manifest.get("status") == "ok" and fact in text and b"event=document.own" in r.err,
          "%s %r" % (r.manifest.get("status"), text[:60]))

# ------------------------------------------------ the readers in a process of their own, on one clock
readpage.budget.start(readpage.budget.SECONDS)
DOCS = getattr(readpage, "_DOCS", {})             # the read's converter clock (the old code had none)
DOCS["spent"] = 0.0
got = attempt(readpage.own_doc, path("doc.rtf"), "rtf")
check("a document is read in a process of its own", isinstance(got, tuple) and "RTF-NOTE" in got[0],
      repr(got)[:120])
os.environ["READ_PAGE_TEST_DOC_SLEEP"] = "30"
DOCS["spent"] = readpage.CONVERTER_TIMEOUT - 1.5
got, secs = timed(attempt, readpage.own_doc, path("doc.rtf"), "rtf")
check("a reader still at work when the converter's time is up is stopped, and the note says so",
      isinstance(got, tuple) and got[0] == "" and "did not finish" in got[1] and secs < 4, "%.1fs %r" % (secs, got))
DOCS["spent"] = readpage.CONVERTER_TIMEOUT
got, secs = timed(attempt, readpage.own_doc, path("doc.rtf"), "rtf")
check("with the read's converter time spent on other documents, the next is not read, and named so",
      isinstance(got, tuple) and got[0] == "" and "not read" in got[1] and secs < 0.5, "%.1fs %r" % (secs, got))
with zipfile.ZipFile(path("two.zip"), "w") as z:
    z.write(path("doc.rtf"), "one.rtf")
    z.write(path("doc.rtf"), "two.rtf")
r = run_read(path("two.zip"), env={"READ_PAGE_SKIP": "pandoc,browser", "READ_PAGE_TEST_DOC_SLEEP": "30"})
text = r.file("content.md")
check("a ZIP's documents share the converter's 10 s: the first is stopped at them, the second not read",
      r.seconds < 18 and "did not finish" in text and "two.rtf" in text and "not read" in text,
      "%.1fs %r" % (r.seconds, text[-300:]))
os.environ.pop("READ_PAGE_TEST_DOC_SLEEP")
if os.name == "nt" or sys.platform == "darwin":
    check.skip("the readers' process cannot take more memory than its limit (RLIMIT_AS)",
               "no RLIMIT_AS on Windows; macOS does not hold to it")
else:
    code = ("import sys; sys.path.insert(0, %r); import docreaders; docreaders._limit_memory(200 << 20); "
            "x = bytearray(400 << 20)" % SCRIPTS)
    p = subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True, timeout=60)
    check("the readers' process cannot take more memory than its limit (RLIMIT_AS)",
          p.returncode != 0 and b"MemoryError" in p.stderr, p.stderr[-200:])


# ------------------------------------------------ KNOWN-ISSUES 167: a cut archive read from its members' headers
class Unseekable(io.RawIOBase):
    """What zipfile writes to when it cannot seek: each member's CRC and sizes after its data."""
    def __init__(self):
        self.buf = io.BytesIO()

    def writable(self):
        return True

    def write(self, b):
        return self.buf.write(b)


def cut_archive(name, members, descriptor=False, chunk=1 << 20):
    """An archive of `members` - [(name, bytes, or (a block, times) written in pieces)] - with its
    table of contents cut off; deflated, and with descriptor=True each member's sizes after its data."""
    sink = Unseekable() if descriptor else io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in members:
            if isinstance(data, tuple):
                with z.open(n, "w", force_zip64=True) as fh:
                    for _ in range(data[1]):
                        fh.write(data[0])
            else:
                z.writestr(n, data)
        cut = sink.tell() if not descriptor else len(sink.buf.getvalue())
    raw = (sink.buf if descriptor else sink).getvalue()
    with open(path(name), "wb") as fh:
        fh.write(raw[:cut])                    # where its table of contents would start
    return name


md, info = scaled(lambda n: cut_archive("many.zip", [("m%05d.txt" % k, b"x") for k in range(n)]), "zip", 2500, 10000)
got = json.loads(md) if md.startswith("{") else {}
check("167: a cut archive of 10 000 members is read in linear time, every member whole",
      fine_scaled(info, 150) and got.get("whole") == 10000 and got.get("how") == "cut"
      and "rest were not" not in info.get("note", ""), show(info, md))
cut_archive("more.zip", [("m%05d.txt" % k, b"x") for k in range(12000)])
md, info = hostile("more.zip", "zip", wall=60, mb=150)
got = json.loads(md) if md.startswith("{") else {}
check("167: ... 12 000 members: the first 10 000 are looked at, and the reason says the rest were not",
      fine(info, 30, 150) and got.get("members") == 10000 and "rest were not" in info.get("note", ""), show(info, md))
ZEROS = (b"\x00" * (1 << 20), 256)                # 256 MB of zeros, 256 KB deflated
cut_archive("bomb.zip", [("bomb.bin", ZEROS), ("after.txt", b"AFTER-THE-BOMB")])
md, info = hostile("bomb.zip", "zip", wall=60, mb=200)
got = json.loads(md) if md.startswith("{") else {}
check("167: a member that unpacks to 256 MB is not unpacked past 32 MB, and the member after it is whole",
      fine(info, 20, 200) and got.get("whole") == 1 and "over the size limit" in info.get("note", ""), show(info, md))
cut_archive("bomb-dd.zip", [("first.txt", b"FIRST"), ("bomb.bin", ZEROS), ("after.txt", b"AFTER")], descriptor=True)
md, info = hostile("bomb-dd.zip", "zip", wall=60, mb=200)
got = json.loads(md) if md.startswith("{") else {}
check("167: ... the same with its size after its data: the reading stops there, the members before it whole",
      fine(info, 20, 200) and got.get("whole") == 1 and "not read to its end" in info.get("note", ""), show(info, md))
cut_archive("dd.zip", [("one.txt", b"ONE " * 1000), ("two.txt", b"TWO " * 1000)], descriptor=True)
md, info = hostile("dd.zip", "zip", wall=30, mb=150)
got = json.loads(md) if md.startswith("{") else {}
check("167: members whose sizes follow their data are read whole, by where their data ends",
      fine(info, 10, 150) and got.get("whole") == 2, show(info, md))
cut_archive("total.zip", [("big%d.bin" % k, (b"\x00" * (1 << 20), 30)) for k in range(5)])
md, info = hostile("total.zip", "zip", wall=60, mb=200)
got = json.loads(md) if md.startswith("{") else {}
check("167: five members of 30 MB: four are taken (128 MB in all), the fifth is over the limit, one at a time in memory",
      fine(info, 30, 200) and got.get("whole") == 4 and "over the size limit" in info.get("note", ""), show(info, md))


# ------------------------------------------------ member names in a code page, with no UTF-8 flag
def raw_zip(name, members):
    """An archive whose members' names are the bytes given and carry no UTF-8 flag - what Windows' own
    zipper and many Chinese tools write: each is written under an ASCII stand-in of its length, whose
    bytes are then replaced in the member's header and in the table of contents."""
    buf, stand = io.BytesIO(), []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, (raw, data) in enumerate(members):
            s = ("~%04d" % k).ljust(len(raw), "~").encode("ascii")
            stand.append((s, raw))
            z.writestr(s.decode("ascii"), data)
    out = buf.getvalue()
    for s, raw in stand:
        out = out.replace(s, raw)
    with open(path(name), "wb") as fh:
        fh.write(out)
    return path(name)


def names_of(p, prior=""):
    with zipfile.ZipFile(p) as z:
        codec = attempt(docreaders.fix_zip_names, z, prior) if hasattr(docreaders, "fix_zip_names") else None
        return codec, z.namelist(), [z.read(n) for n in z.namelist()] if not isinstance(codec, Exception) else []


GBK_NAMES = ["说明.txt", "数据/报告（终稿）.csv"]
p = raw_zip("gbk.zip", [(n.encode("gbk"), ("FACT %d" % k).encode()) for k, n in enumerate(GBK_NAMES)] +
            [(b"plain-ascii.txt", b"ASCII")])
codec, names, datas = names_of(p)
check("names: GBK with no UTF-8 flag read as GBK (it was CP437: \"╦╡├≈.txt\"), each member still unpacks",
      codec == "gb18030" and names[:2] == GBK_NAMES and "plain-ascii.txt" in names and datas[:1] == [b"FACT 0"],
      "%r %r" % (codec, names))
for label, members, prior, want in (
        ("UTF-8 with no flag (a macOS or Linux zipper)", [("中文说明.txt".encode("utf-8"), b"x")], "", ["中文说明.txt"]),
        ("a CP437 name of accented letters stays", [("Größe.txt".encode("cp437"), b"x"), (b"ascii.txt", b"y")], "",
         ["Größe.txt", "ascii.txt"]),
        ("Shift-JIS, kana telling it from GBK (表 ends in a backslash byte)",
         [("テスト.txt".encode("cp932"), b"x"), ("表示.txt".encode("cp932"), b"y")], "", ["テスト.txt", "表示.txt"]),
        ("Big5", [("說明文件.txt".encode("big5"), b"x")], "", ["說明文件.txt"]),
        ("Korean on a machine whose code page is Korean", [("보고서.txt".encode("cp949"), b"x")], "cp949", ["보고서.txt"]),
        ("GBK on a machine whose code page is Chinese", [("说明.txt".encode("gbk"), b"x")], "gb18030", ["说明.txt"])):
    codec, names, datas = names_of(raw_zip("names.zip", members), prior)
    check("names: %s" % label, names == want and len(datas) == len(want), "%r %r" % (codec, names))
CHAP = "第一章.xhtml"
p = raw_zip("gbk.epub", [(b"mimetype", b"application/epub+zip"), (b"META-INF/container.xml", CONTAINER.encode()),
                         (b"OEBPS/content.opf", ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                                                 'version="3.0"><manifest><item id="c" href="%s" media-type="application/'
                                                 'xhtml+xml"/></manifest><spine><itemref idref="c"/></spine></package>'
                                                 % CHAP).encode("utf-8")),
                         (("OEBPS/" + CHAP).encode("gbk"), xhtml("<p>GBK-CHAPTER-FACT 第一章的内容。</p>").encode("utf-8"))])
md, note = docreaders.read(p, "epub")
check("names: an EPUB whose chapter is named in GBK, its OPF in UTF-8, is read (the chapter was not found)",
      "GBK-CHAPTER-FACT" in md, "%r %r" % (md[:80], note))
sys.exit(check.done())
