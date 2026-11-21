"""The block rule: what the extractor dropped goes back. No network.

    python -X utf8 tests/blocks.py

The extractor only suggests. A block of page.md that is not in the text and is prose, code, a
table or a captioned figure goes back after its neighbour that the extractor kept; menus, lists of
links, fragments and cookie banners stay out, and the header says how much stayed out. The test
has no markup of its own: every paragraph, code block and table of page.md is in the text exactly
once.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import blockrule                                             # noqa: E402
from harness import Checks, run_read, serve                  # noqa: E402

check = Checks()

INTRO = ("INTRO-PARA Python is an easy to learn, powerful programming language. It has efficient high-level "
         "data structures and a simple but effective approach to object-oriented programming.")
DROPPED = ("DROPPED-PARA Let us try some simple Python commands. Start the interpreter and wait for the primary "
           "prompt, which should not take long; the operators work just as they do in most other languages.")
KEPT2 = ("KEPT-PARA-TWO Of course, we can use Python for more complicated tasks than adding two and two "
         "together. For instance, we can write an initial part of the Fibonacci series as follows.")
CODE = "```\n>>> DROPPED_CODE = 2 + 2\n>>> 50 - 5*6\n20\n```"
TABLE = "| Operator | Meaning |\n|---|---|\n| + | DROPPED-TABLE addition |\n| - | subtraction |"
MENU = "* [Home](/)\n* [Docs](/docs)\n* [Blog](/blog)\n* [About us](/about)\n* [Download](/dl)"
COOKIE = ("We use cookies to improve your experience. By using this site you accept our cookie policy "
          "and the privacy terms that come with it. [Accept](#) [Settings](#)")
PAGE = "\n\n".join(["[Skip to content](#main)", MENU, "# The Python Tutorial", INTRO,
                    "## 3.1. Using Python as a Calculator", DROPPED, CODE, TABLE, "## 3.2. First Steps", KEPT2,
                    COOKIE, "Share", "© 2001-2026 Python Software Foundation. All rights reserved."])
CONTENT = "\n\n".join(["# The Python Tutorial", INTRO.replace("powerful", "*powerful*"), "## 3.2. First Steps", KEPT2])

WORD = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]|"
                  r"[^\W_぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]+")
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def words(s):
    return [w.lower() for w in WORD.findall(LINK.sub(r"\1", s))]


def grams(ws, k=5):
    k = min(k, len(ws))
    return [" ".join(ws[i:i + k]) for i in range(len(ws) - k + 1)] if k else []


def once_each(text, page):
    """Every paragraph, code block and table of page.md in `text` exactly once: an independent
    check, words and 5-word runs only. Returns the blocks that are missing or doubled."""
    tw = words(text)
    have = {}
    for g in grams(tw):
        have[g] = have.get(g, 0) + 1
    wrong = []
    for b in blockrule.blocks(page):
        ws = words(b)
        if blockrule.kind(b, ws) not in ("prose", "code", "table", "figure"):
            continue
        gs = grams(ws)
        found = sum(1 for g in gs if have.get(g)) / max(1, len(gs))
        twice = sum(1 for g in gs if have.get(g, 0) > 1 and gs.count(g) == 1) / max(1, len(gs))
        if found < 0.5 or twice > 0.5:
            wrong.append("%s %.0f%%/%.0f%%: %s" % ("doubled" if found >= 0.5 else "missing", found * 100, twice * 100,
                                                   re.sub(r"\s+", " ", b)[:50]))
    return wrong


# ------------------------------------------------ the rule on its own
out, info = blockrule.restore(CONTENT, PAGE)
check("every paragraph, code block and table of page.md is in the text once", not once_each(out, PAGE),
      "; ".join(once_each(out, PAGE))[:150])
pos = [out.find(x) for x in ("INTRO-PARA", "## 3.1.", "DROPPED-PARA", "DROPPED_CODE", "DROPPED-TABLE",
                             "## 3.2.", "KEPT-PARA-TWO")]
check("the dropped section goes back after its neighbour, with its heading, in page order",
      all(p >= 0 for p in pos) and pos == sorted(pos), str(pos))
check("menus, the cookie banner, fragments and the footer stay out",
      not any(x in out for x in ("[Home]", "Home", "cookies", "Skip to content", "Share", "©")), "")
check("what the extractor kept is unchanged", out.startswith("# The Python Tutorial\n\n" + INTRO.replace(
      "powerful", "*powerful*")) and out.rstrip().endswith(KEPT2), out[:40])
check("the manifest numbers: blocks put back and what stayed out",
      info.get("restored") == 4 and info.get("outside", 0) >= len(MENU) and info.get("restored_bytes", 0) > len(DROPPED),
      str(info))
again, info2 = blockrule.restore(out, PAGE)
check("a second pass adds nothing", again == out and not info2.get("restored"), str(info2))
same, info3 = blockrule.restore(PAGE, PAGE)
check("a text that already holds everything is left alone", same == PAGE and not info3.get("restored"), "")

lead = "LEAD-PARA " + " ".join("word%d" % i for i in range(40))
out, info = blockrule.restore(CONTENT, "\n\n".join([lead, PAGE]))
check("a dropped block with no kept block before it goes first", out.startswith("LEAD-PARA"), out[:30])
out, info = blockrule.restore(CONTENT, "\n\n".join([PAGE, DROPPED.replace("DROPPED-PARA", "TWICE-PARA"),
                                                   DROPPED.replace("DROPPED-PARA", "TWICE-PARA")]))
check("a paragraph the page repeats goes back once", out.count("TWICE-PARA") == 1, str(out.count("TWICE-PARA")))
links = " ".join("[link number %d](/l%d)" % (i, i) for i in range(12)) + " and a few words of glue here"
privacy = "PRIVACY-ARTICLE " + ("The privacy policy of a company says what it collects, why, and for how long. " * 8)
out, info = blockrule.restore(CONTENT, "\n\n".join([PAGE, links, privacy]))
check("a paragraph made of links stays out", "link number" not in out, "")
check("a long paragraph about privacy is prose, not a banner", "PRIVACY-ARTICLE" in out, "")
jp_kept = "日本語の段落はここにあります。" * 6
jp_drop = "JP-DROP 吾輩は猫である。名前はまだ無い。どこで生れたかとんと見当がつかぬ。何でも薄暗いじめじめした所で泣いていた。"
out, info = blockrule.restore("# 題\n\n" + jp_kept, "# 題\n\n" + jp_kept + "\n\n" + jp_drop)
check("Japanese counts by character: a dropped paragraph goes back", "JP-DROP" in out, str(info))
inner = "\n".join(("Home", "Products", "Pricing", "Docs", "Blog", "Careers", "Contact", "Sign in") * 4)
out, info = blockrule.restore(CONTENT, inner + "\n\n" + PAGE)
check("a browser's menu (short lines, no markup) stays out", "Careers" not in out, "")
fig = "![Speed of each reader](img/speed.png)\nFigure 2. FIGURE-CAPTION median seconds per page for each reader"
out, info = blockrule.restore(CONTENT, PAGE + "\n\n" + fig)
check("a captioned figure goes back; a bare picture is not a block of text", "FIGURE-CAPTION" in out, "")

# ------------------------------------------------ what loses its id before defuddle
import readpage                                              # noqa: E402
CASES_IDS = [
    ('<a href="#next-input-character" id="data-state:next-input-character">t</a>', '<a href="#next-input-character">t</a>'),
    ('<span data-id="x" id="next-y">t</span>', '<span data-id="x">t</span>'),
    ('<a class="footnote-reference brackets" href="#id6" id="id1">1</a>', None),     # docutils: PEP 8
    ('<a id="id1" class="footnote-reference" href="#id6">1</a>', None),               # the class after the id
    ('<sup id="fnref:1"><a href="#fn:1">1</a></sup>', None),
    ('<a role="doc-noteref" id="x1" href="#n1">1</a>', None),
    ('<div id="next-steps"><p>t</p></div>', None),                                    # a block: the block rule's
]
bad = [(src, readpage.inline_ids_off(src)) for src, want in CASES_IDS if readpage.inline_ids_off(src) != (want or src)]
check("an inline element's id goes, a footnote's and a block's stay", not bad, str(bad[:2]))

# ------------------------------------------------ page.md's links are whole addresses
import engines                                               # noqa: E402
BASED = '<head><base href="https://cdn.example.org/docs/"></head><p><a href="guide.html">G</a> <img src="i.png" alt="I"></p>'
if importlib.util.find_spec("html2text"):
    md = engines.html2text_full(BASED, base=engines.page_base(BASED, "https://example.org/a/b"))
    check("html2text resolves links and pictures against <base href>",
          "(https://cdn.example.org/docs/guide.html)" in md and "(https://cdn.example.org/docs/i.png)" in md, md)
else:
    check.skip("html2text resolves links and pictures against <base href>", "no html2text here")
check("without <base href> the base is the page's address",
      engines.page_base("<p>x</p>", "https://example.org/a/b") == "https://example.org/a/b", "")

# ------------------------------------------------ inside a read
EN = ("Reading pages reliably is harder than it looks, because servers lie about what they send and "
      "scripts change what a reader sees after the first paint. ")
NAV = "<nav><ul>" + "".join("<li><a href='/section/%d'>Section %d of the guide</a></li>" % (i, i)
                            for i in range(60)) + "</ul></nav>"
HTML = ("<!doctype html><html><head><meta charset='utf-8'><title>Guide</title></head><body>" + NAV +
        "<main><article><h1>Guide</h1><p>ART-INTRO " + EN * 6 + "</p><h2>Details</h2><p>ART-DETAILS " + EN * 6 +
        "</p></article>"
        "<aside class='sidebar'><h3>Note</h3><p>ASIDE-PARA The sidebar holds a whole paragraph of real advice that a "
        "main-content extractor throws away, although the reader of this guide needs it to set things up "
        "correctly on the first try.</p><pre><code>ASIDE_CODE = configure(retries=3, timeout=20)\nrun(ASIDE_CODE)"
        "</code></pre></aside></main>"
        "<footer><p>We use cookies to improve your experience. By using this site you accept our cookie policy."
        "</p><p>&copy; 2026 Example Inc. All rights reserved.</p></footer></body></html>").encode("utf-8")
# defuddle drops any element whose id or class holds a clutter word ("next-" among them),
# an inline link inside a sentence too; the WHATWG specs give every term's link such an id
SPEC = ("<!doctype html><html><head><meta charset='utf-8'><title>Tokenizer</title></head><body><main><article>"
        "<h1>Tokenizer</h1>" + "".join(
            "<h2>State %d</h2><p>SPEC-%d " % (i, i) + EN * 3 + "Consume the <a href='#next-input-character' "
            "id='state-%d:next-input-character'>next input character</a> and <dfn id='next-step-%d'>step on</dfn>.</p>"
            % (i, i) for i in range(6)) +
        "<section id='next-steps'><h2>Afterwards</h2><p>NEXT-SECTION-PARA When the tokenizer reaches the end "
        "of the input it emits an end-of-file token, the tree builder closes every element still open, and "
        "the document is complete; scripts that were deferred run only after this point.</p></section>"
        "<p>A note<a href='#fn:1' id='fnref:1'>1</a> at the end. " + EN * 2 + "</p>"
        "<ol><li id='fn:1'>NOTE-TEXT the footnote itself. <a href='#fnref:1'>↩</a></li></ol>"
        "</article></main></body></html>").encode("utf-8")
# SQLite's syntax diagrams are inline SVG, which defuddle passes through as markup (13.6 KB
# of path data, a third of lang_with.html's text); an SVG in a code block is an example and stays
DIAGRAM = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 80'>" + "".join(
    "<path d='M%d 10 L%d 40 L%d 70' style='stroke-width:2.16;stroke:rgb(0,0,0);'></path>" % (i, i + 5, i + 9)
    for i in range(0, 600, 12)) + "".join("<text x='%d' y='30'>%s</text>" % (40 * i, w) for i, w in enumerate(
        ("WITH", "RECURSIVE", "cte-table-name", "AS", "(", "select-stmt", ")"))) + "</svg>")
SVGPAGE = ("<!doctype html><html><head><meta charset='utf-8'><title>WITH</title></head><body><main><article>"
           "<h1>The WITH clause</h1><p>SVG-INTRO " + EN * 3 + "</p><p><b>with-clause:</b></p>" + DIAGRAM +
           "<p>SVG-AFTER " + EN * 3 + "</p><pre><code>&lt;svg viewBox=\"0 0 10 10\"&gt;&lt;circle r=\"4\"/&gt;"
           "&lt;/svg&gt; SVG-EXAMPLE</code></pre></article></main></body></html>").encode("utf-8")
# page.md was swapped for the text whenever it had fewer characters, and a text's absolute
# links (defuddle writes them so) outgrow page.md's relative ones: the menus and links were lost
LINKY = ("<!doctype html><html><head><meta charset='utf-8'><title>Linky</title></head><body><nav><ul>" + "".join(
    "<li><a href='/n/%d'>NAV-ITEM %d</a></li>" % (i, i) for i in range(8)) + "</ul></nav><main><article><h1>Linky</h1>"
         + "".join("<p>LINKY-%d %s <a href='/docs/reference/section/%d/subsection/details'>see %d</a>.</p>" % (i, EN, i, i)
                   for i in range(60)) + "</article></main></body></html>").encode("utf-8")
s = serve({"/guide": (200, {"Content-Type": "text/html; charset=utf-8"}, HTML),
           "/spec": (200, {"Content-Type": "text/html; charset=utf-8"}, SPEC),
           "/svg": (200, {"Content-Type": "text/html; charset=utf-8"}, SVGPAGE),
           "/linky": (200, {"Content-Type": "text/html; charset=utf-8"}, LINKY)})
try:
    r = run_read(s.url("/spec"), env={"READ_PAGE_SKIP": "browser"})
    body = r.file("content.md")
    eng = str((r.manifest.get("content") or {}).get("engine") or "")
    if eng != "defuddle":
        check.skip("a link named next-... keeps its words", "not defuddle's text (%s)" % eng)
    else:
        check("a link or term named next-... keeps its words (WHATWG specs lost them 81 times a chapter)",
              body.count("next input character") == 6 and body.count("step on") == 6 and "Consume the:" not in body,
              "%d links, %d terms: %s" % (body.count("next input character"), body.count("step on"),
                                          [ln[:70] for ln in body.split("\n") if "Consume" in ln][:2]))
        check("a section named next-... is back by the block rule, and a footnote is still one",
              "NEXT-SECTION-PARA" in body and "NOTE-TEXT" in body, eng)
    r = run_read(s.url("/svg"), env={"READ_PAGE_SKIP": "browser"})
    body = r.file("content.md")
    eng = str((r.manifest.get("content") or {}).get("engine") or "")
    check("an inline SVG diagram is one line of its labels, not path data; a code block's SVG stays",
          "<path" not in body and "stroke-width" not in body and "SVG-AFTER" in body and "SVG-EXAMPLE" in body
          and ("[diagram: WITH RECURSIVE cte-table-name AS ( select-stmt )]" in body or eng != "defuddle")
          and ("<svg" in body or eng != "defuddle"),
          "%s: %s" % (eng, [ln[:90] for ln in body.split("\n") if "diagram" in ln or "<svg" in ln or "path" in ln][:3]))
    r = run_read(s.url("/linky"), env={"READ_PAGE_SKIP": "browser"})
    page = r.file("page.md")
    check("page.md is the whole page, menu included, though the text's absolute links are longer",
          "NAV-ITEM 5" in page and page != r.file("content.md"),
          "%d vs %d characters" % (len(page), len(r.file("content.md"))))
    r = run_read(s.url("/guide"), env={"READ_PAGE_SKIP": "browser"})
    body, page = r.file("content.md"), r.file("page.md")
    eng = str((r.manifest.get("content") or {}).get("engine") or "")
    if importlib.util.find_spec("html2text"):
        check("page.md's links are whole addresses, as content.md's (an agent joined them itself)",
              "(%s)" % s.url("/section/17") in page and "](/section/" not in page,
              [ln for ln in page.split("\n") if "Section 17" in ln][:1])
    bad = once_each(body, page)
    check("a read: every paragraph, code block and table of page.md is in content.md once", not bad,
          "%s: %s" % (eng, "; ".join(bad)[:140]))
    if eng.split(":")[0] in ("full", "crude"):
        check.skip("a read: the menu stays out of content.md", "no extractor here (%s)" % eng)
    else:
        check("a read: the menu stays out of content.md", "Section 17" not in body, eng)
        a, b, c = body.find("ART-DETAILS"), body.find("ASIDE-PARA"), body.find("ASIDE_CODE")
        check("a read: the sidebar's paragraph and code are back after the article",
              0 <= a < b < c, "%s %s" % (eng, (a, b, c)))
        out_kb = (r.manifest.get("content") or {}).get("outside") or 0
        check("a read: the header says how much stayed out of the text",
              out_kb > 0 and "outside the text" in r.text, "%s B; %s" % (
                  out_kb, [ln for ln in r.text.split("\n")[:8] if "outside" in ln]))
finally:
    s.close()

sys.exit(check.done())
