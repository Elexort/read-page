"""EPUB, ODT and RTF read with the standard library (scripts/docreaders.py, 2026-11-20): what each
reader keeps - headings, lists, tables, notes, links, pictures, code, code pages - and how it
answers a hostile file: a cut archive, broken XML, an entity bomb, a zip bomb, deep nesting,
garbage. Then the CLI with READ_PAGE_SKIP=pandoc, which puts these readers in pandoc's place.
No network.

    python -X utf8 tests/docreaders.py
"""
import io
import os
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from harness import Checks, run_read     # noqa: E402
import docreaders                        # noqa: E402

check = Checks()
TMP = tempfile.mkdtemp(prefix="rp-docreaders-")


def path(name):
    return os.path.join(TMP, name)


def epub(name, parts, version="3.0", nav=True, extra=()):
    """parts: [(file name, body html)]; a nav document (left out of the text) when nav=True."""
    items, spine = [], []
    for i, (n, _b) in enumerate(parts):
        items.append('<item id="p%d" href="%s" media-type="application/xhtml+xml"/>' % (i, n))
        spine.append('<itemref idref="p%d"/>' % i)
    if nav:
        items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        spine.insert(0, '<itemref idref="nav"/>')
    with zipfile.ZipFile(path(name), "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:'
                   'names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                   'version="%s"><metadata/><manifest>%s</manifest><spine>%s</spine></package>'
                   % (version, "".join(items), "".join(spine)))
        if nav:
            z.writestr("OEBPS/nav.xhtml", xhtml('<nav epub:type="toc"><ol><li><a href="c1.xhtml">NAV-ONLY-WORD'
                                                '</a></li></ol></nav>'))
        for n, b in parts:
            z.writestr("OEBPS/" + n, xhtml(b))
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
got, secs = timed(readpage.odf_text, p)
check("hostile: the old ODT reader no longer unpacks a part whole", got == "" and secs < 5, "%.2fs" % secs)
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

# ------------------------------------------------ office files pandoc read and the office readers refused
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

# ------------------------------------------------ the CLI with these readers in pandoc's place
for name, fact in (("book.epub", "ENDNOTE-TEXT"), ("doc.odt", "ODT-NOTE"), ("doc.rtf", "RTF-NOTE")):
    r = run_read(path(name), env={"READ_PAGE_SKIP": "pandoc,browser"})
    text = r.file("content.md")
    check("cli without pandoc: %s is read, its notes too" % name,
          r.manifest.get("status") == "ok" and fact in text, "%s %r" % (r.manifest.get("status"), text[:60]))
sys.exit(check.done())
