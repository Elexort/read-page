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
import time

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

# ------------------------------------------------ a table a converter kept as HTML (KNOWN-ISSUES 338)
# defuddle writes a table one of whose cells spans rows or columns as its HTML, and the block rule did not know it for
# the rows page.md has: japanrailpass.net's price tables came twice, as page.md's rows and as HTML
try:
    import mdtable                                           # noqa: E402
except ImportError:                                          # the code before it: the checks below fail
    mdtable = None
JR_ROWS = (("7-day", "70,000 YEN", "35,000 YEN", "50,000 YEN", "25,000 YEN"),
           ("14-day", "110,000 YEN", "55,000 YEN", "80,000 YEN", "40,000 YEN"))
JR_HTML = ('<table><tbody><tr><th>Type</th><th colspan="2">Green</th><th colspan="2">Ordinary</th></tr>'
           '<tr><td>Duration</td><td>Adult</td><td>Child</td><td>Adult</td><td>Child</td></tr>'
           + "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in row) for row in JR_ROWS) + "</tbody></table>")
JR_MD = ("| Type | Green |  | Ordinary |  |\n| --- | --- | --- | --- | --- |\n| Duration | Adult | Child | Adult | Child |\n"
         + "\n".join("| %s |" % " | ".join(row) for row in JR_ROWS))
JR_PAGE = ("Type | Green | Ordinary  \n---|---|---  \nDuration | Adult | Child | Adult | Child  \n"
           + "\n".join("%s  " % " | ".join(row) for row in JR_ROWS))
JR_NOTE = ("PRICES-NOTE Children are defined as those aged 6 to 11 at the time of use; for online purchases a child "
           "of 11 on the payment date is a child even if 12 at the time of use.")
JR_TEXT = "\n\n".join(["## JAPAN RAIL PASS prices", "Prices of Exchange Orders", JR_HTML, JR_NOTE])
if mdtable is None:
    check("338: a table defuddle kept as HTML is a Markdown table", False, "no mdtable module")
else:
    got = mdtable.markdown(JR_HTML)
    check("338: a table defuddle kept as HTML is a Markdown table in defuddle's form: a spanning cell's text in the "
          "first column of its span, the columns it spans over empty", got == JR_MD, repr(got)[:300])
    span = mdtable.markdown("<table><tr><th rowspan='2'>Class</th><th>Price</th></tr><tr><td>Adult</td></tr>"
                            "<tr><td>Green | <a href='/g'>car</a></td><td><b>70,000</b></td></tr></table>",
                            "https://example.org/a/")
    check("... a row span keeps the rows below it in their columns; a cell's links, marks and | are Markdown's",
          span == "| Class | Price |\n| --- | --- |\n|  | Adult |\n| Green \\| [car](https://example.org/g) | **70,000** |",
          repr(span))
    fenced = "```html\n%s\n```" % JR_HTML
    check("... a table inside a code block is code: left as it is", mdtable.tables(fenced) == fenced, "")
    out, info = blockrule.restore(mdtable.tables(JR_TEXT), "\n\n".join(["## JAPAN RAIL PASS prices",
                                                                        "Prices of Exchange Orders", JR_PAGE, JR_NOTE]))
    check("338: the block rule takes it for page.md's table: each price once, no HTML (it put page.md's rows back "
          "beside the HTML)", out.count("70,000 YEN") == 1 and out.count("110,000 YEN") == 1 and "<table" not in out
          and not info.get("restored"), "%d, %d | %s" % (out.count("70,000 YEN"), out.count("110,000 YEN"), info))

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

# ------------------------------------------------ tabs, collapsed sections and selects (KNOWN-ISSUES 256-258)
# a tab set's labels were dropped with the buttons that hold them, and a hidden panel came with no word of it or
# not at all: each is a marker now, its state and its name, a hidden panel's text under its own
import answer                                                # noqa: E402
try:
    import tabs                                              # noqa: E402
except ImportError:                                          # the code before the markers: every check below fails
    tabs = None
WORDS = ("plan allows a number of requests a minute and tokens a day, counted for the whole organization "
         "and reset at midnight in the time zone the account was made in. ")
TABS = ("<!doctype html><html><head><meta charset='utf-8'><title>Rate limits</title></head><body><header><nav>"
        "<a href='/'>Home</a><div role='tablist'><button role='tab' aria-selected='true'>MENU-TAB-A</button>"
        "<button role='tab'>MENU-TAB-B</button></div></nav></header><main><article><h1>Rate limits</h1>"
        "<p>TABS-INTRO Rate limits act as control measures on how often a user can reach the service in a given "
        "time; they are counted per organization, not per user, and whichever is reached first applies.</p>"
        "<div class='tabs-container'><div role='tablist' aria-label='Plans'>"
        "<button role='tab' id='t-free' aria-selected='true' aria-controls='p-free'>Free Plan Limits</button>"
        "<button role='tab' id='t-dev' aria-selected='false' aria-controls='p-dev'>Developer Plan Limits</button>"
        "<button role='tab' id='t-batch' aria-selected='false' aria-controls='p-batch'>Batch Limits</button></div>"
        "<div role='tabpanel' id='p-free' aria-labelledby='t-free'><p>FREE-PANEL The free " + WORDS + "</p></div>"
        "<div role='tabpanel' id='p-dev' aria-labelledby='t-dev' hidden><p>DEV-PANEL The developer " + WORDS
        + "</p></div><div role='tabpanel' id='p-batch' aria-labelledby='t-batch' hidden></div></div>"
        "<h2>Models</h2><table><thead><tr data-role='legend'><th colspan='3'><nav><ul><li><button type='button' "
        "class='rounded active'>Free Plan Limits</button></li><li><button type='button' class='rounded'>"
        "Developer Plan Limits</button></li></ul></nav></th></tr><tr><th>Model</th><th>RPM</th><th>TPD</th></tr>"
        "</thead><tbody>" + "".join("<tr><td>TABLE-ROW-%d model</td><td>%d</td><td>500K</td></tr>" % (i, 30 + i)
                                    for i in range(6)) + "</tbody></table>"
        "<details><summary>Specifications</summary><p>SPEC-PARA The device weighs two kilograms, runs for ten "
        "hours on one charge and takes a charger of any brand that gives sixty five watts.</p></details>"
        "<h3><button aria-expanded='false' aria-controls='faq1'>How do I pay?</button></h3>"
        "<div id='faq1' class='accordion-collapse collapse'><p>FAQ-PARA You pay by card or by bank transfer each "
        "month, and the invoice comes by mail on the first working day after the month ends.</p></div>"
        "<p><label for='region'>Region</label> <select id='region'><option>US</option><option selected>EU</option>"
        "<option>APAC</option></select></p>"
        "<h2>Code</h2><div role='tablist'><button role='tab' aria-selected='true' aria-controls='c-py'>Python</button>"
        "<button role='tab' aria-selected='false' aria-controls='c-go'>Go</button></div>"
        "<div role='tabpanel' id='c-py'><pre><code>PY-CODE print('hello')</code></pre></div>"
        "<div role='tabpanel' id='c-go' hidden><pre><code>GO-CODE " + "fmt.Println(\"hello, world\")\n" * 220
        + "</code></pre></div><p>TABS-END The limits above are what the service enforces today; they may change "
        "with notice, and the console shows the ones of your own account at any time.</p></article></main>"
        "<footer><p>&copy; 2026 Example Inc.</p></footer></body></html>")
FILE_LINK = ("<div class='frame frame-default frame-type-uploads'><div role='heading' aria-level='4' class='h4'>%s</div>"
             "<ul class='ce-uploads'><li><a href='/fileadmin/pages/214/%s' target='_blank' class='ce-uploads-link'>"
             "<span class='ce-uploads-fileName i-download'></span><span class='ce-uploads__text'>%s</span></a></li></ul>"
             "</div>")
FILES = ("<!doctype html><html><head><meta charset='utf-8'><title>VPI</title></head><body><main><article><h1>VPI und HVPI"
         "</h1><p>FILES-INTRO Der Verbraucherpreisindex misst die Preisentwicklung eines Warenkorbs, der die Ausgaben "
         "der privaten Haushalte abbildet, und wird jeden Monat veröffentlicht.</p>"
         "<p><button aria-expanded='false' aria-controls='share-1'>Share</button></p><div id='share-1' class='collapse'>"
         "<a href='https://www.facebook.com/sharer'>Facebook</a> <a href='https://x.com/share'>X</a></div>"
         "<div class='accordion__card' id='gtc-hd'><h3 class='accordion__header mb-0' id='ah-2'>"
         "<button class='accordion__toggle collapsed' data-bs-toggle='collapse' data-bs-target='#ab-2' "
         "aria-expanded='false' aria-controls='ab-2'><span class='accordion-text'>Historische Daten</span></button></h3>"
         "<div id='ab-2' class='accordion__body collapse' role='region' aria-labelledby='ah-2'>"
         + FILE_LINK % ("Historische Publikationstermine", "VPI_1977_bis_2025.ods", "Historische Publikationstermine (.ods)")
         + FILE_LINK % ("Harmonisierter Verbraucherpreisindex (HVPI)", "3_HVPI_2015.ods",
                        "Harmonisierter Verbraucherpreisindex, Basis 2015 (.ods)")
         + "</div></div><h2>Methodik</h2><p>FILES-AFTER Die Gewichte des Warenkorbs werden jedes Jahr aus der "
         "Volkswirtschaftlichen Gesamtrechnung neu berechnet, und die Preise erheben Mitarbeiter in zwanzig Städten."
         "</p></article></main></body></html>")
if tabs is None:
    check("tabs.py marks tabs, sections and selects", False, "no tabs module")
else:
    marked, tinfo = tabs.mark(TABS)
    page_marked, pinfo = tabs.mark(TABS, page=True)
    md = tabs.unescape_markers(engines.html2text_full(marked))
    pmd = tabs.unescape_markers(engines.html2text_full(page_marked))

    def at(text, s):
        return text.find(s)
    check("an ARIA tab set: the shown tab's marker, its text, the hidden tab's marker, its text, in that order",
          0 <= at(md, "[tab · shown · Free Plan Limits]") < at(md, "FREE-PANEL") < at(
              md, "[tab · hidden, but extracted · Developer Plan Limits]") < at(md, "DEV-PANEL"),
          [ln for ln in md.split("\n") if "[tab" in ln][:4])
    check("... a tab whose panel the page does not hold is named: loads on click, not extracted",
          "[tab · loads on click, not extracted · Batch Limits]" in md, "")
    check("... the tabs of a menu are no tab set of the text", "[tab · shown · MENU-TAB-A]" not in md, "")
    rows = md.find("TABLE-ROW-0")
    check("a table's own tab buttons (Groq's plans): the shown tab named above the table, the other below it",
          0 <= md.rfind("[tab · shown · Free Plan Limits]", 0, rows) < rows
          < md.find("[tab · loads on click, not extracted · Developer Plan Limits]", rows),
          [ln for ln in md.split("\n") if "Plan Limits]" in ln])
    check("a closed <details>: a section marker, its text after it",
          0 <= at(md, "[section · hidden, but extracted · Specifications]") < at(md, "SPEC-PARA"), "")
    check("a collapsed accordion: a section marker in its heading, its region's text after it",
          0 <= at(md, "### [section · hidden, but extracted · How do I pay?]") < at(md, "FAQ-PARA"),
          [ln for ln in md.split("\n") if "pay?" in ln][:2])
    check("a select: the chosen option, the others, the name", "[select · chosen: EU · also US, APAC · Region]" in md,
          [ln for ln in md.split("\n") if "select" in ln][:2])
    long_m = re.search(r"\[tab · hidden, but extracted · ([\d.]+ KB), too long for here: page\.md from line "
                       r"RPTABLINE[0-9a-f]{10} · Go\]", md)
    check("a hidden panel past %d bytes stays out of the text, its marker says its size and that page.md has it"
          % tabs.PANEL_LIMIT, long_m is not None and "GO-CODE" not in md and "PY-CODE" in md,
          [ln for ln in md.split("\n") if "· Go]" in ln][:1])
    check("... page.md's copy holds it whole under its marker",
          0 <= at(pmd, "[tab · hidden, but extracted · Go]") < at(pmd, "GO-CODE") and "too long" not in pmd, "")
    view = answer.split_long_lines(pmd)
    placed = tabs.place_lines(md, view, pinfo["page_long"])
    n = re.search(r"too long for here: page\.md from line (\d+) · Go\]", placed)
    check("... and the text's marker names the line of page.md where it starts",
          n is not None and "[tab · hidden, but extracted · Go]" in view.split("\n")[int(n.group(1)) - 1],
          n.group(0) if n else [ln for ln in placed.split("\n") if "· Go]" in ln][:1])
    check("the counts for the manifest", tinfo["counts"] == {"tabs": 3, "extracted": 1, "not_extracted": 2, "long": 1,
                                                             "sections": 2, "selects": 1}, str(tinfo["counts"]))
    plain = ("<html><body><main><h1>Plain</h1><p>No tabs here.</p><button aria-expanded='false' aria-controls='m'>"
             "Menu</button><nav id='m'><a href='/a'>A</a> <a href='/b'>B</a></nav><details><summary></summary>"
             "<a href='/c'>C</a></details></main></body></html>")
    check("a page with none of them is left as it is: a menu folded under a button, an icon's popover",
          tabs.mark(plain)[0] == plain, tabs.mark(plain)[1]["counts"])
    # a collapsed section that holds only links lost them: statistik.at's "Historische Daten", two .ods files, came as
    # a heading with nothing under it and no marker - its region is links by half or more, which the rule took for a
    # menu folded away, and defuddle drops the site's file lists (KNOWN-ISSUES 339). A toggle that heads no heading
    # and folds away links (a share menu) is still no section
    marked_f, finfo = tabs.mark(FILES)
    mdf = tabs.unescape_markers(engines.html2text_full(marked_f))
    check("339: an accordion's section whose region is a list of files is a section: its marker in its heading",
          "### [section · hidden, but extracted · Historische Daten]" in mdf
          and "Basis 2015" in " ".join(finfo.get("links") or []),
          "%s | %s" % ([ln for ln in mdf.split("\n") if "Historische Daten" in ln][:1], finfo.get("links")))
    check("... a toggle that heads no heading and folds away links is a menu: no marker", "[section · hidden, but "
          "extracted · Share]" not in mdf and "Share" in mdf, [ln for ln in mdf.split("\n") if "Share" in ln][:2])
    text_f = "\n\n".join(b for b in blockrule.blocks(mdf) if ".ods" not in b and "Publikationstermine" not in b
                         and "(HVPI)" not in b)
    try:
        out_f, _info_f = blockrule.restore(text_f, mdf, keep=finfo.get("links") or [])
    except TypeError as e:                                   # a block rule with no `keep`
        out_f = "TypeError: %s" % e
    a, b, c = (out_f.find("[section · hidden, but extracted · Historische Daten]"),
               out_f.find("VPI_1977_bis_2025.ods"), out_f.find("3_HVPI_2015.ods"))
    check("339: the block rule puts such a section's links back under its marker, when the extractor dropped them",
          0 <= a < b < c and out_f.find("FILES-AFTER") > c, "%s | %s" % ((a, b, c), out_f[:120]))
    # a section's or a panel's tree walked from the head of a list took 11.5 s for 80 000 items (a fast machine),
    # a minute on a weak laptop: the read's whole time, spent before any extractor ran
    # Walked once, four times the items take about four times as long (sixteen when walked so), on any machine
    took = {}
    for kind, frame in (("details", "<details><summary>All items</summary><ul>%s</ul></details>"),
                        ("tab", "<div role='tablist'><button role='tab' aria-selected='true' aria-controls='a'>A"
                                "</button><button role='tab' aria-controls='b'>B</button></div><div role='tabpanel' "
                                "id='a'><p>x</p></div><div role='tabpanel' id='b' hidden><ul>%s</ul></div>")):
        for n_items in (20000, 80000):
            big = frame % "".join("<li>item %d</li>" % i for i in range(n_items))
            t_big = time.time()
            big_info = tabs.mark("<html><body><main><p>Intro.</p>%s</main></body></html>" % big)[1]
            took[kind, n_items] = (round(time.time() - t_big, 2),
                                   big_info["counts"]["sections"] + big_info["counts"]["tabs"])
    check("a closed <details> and a hidden tab of 80 000 items are marked in time that grows as their size does",
          all(took[k, 80000][1] == 1 and (took[k, 80000][0] < 2 or took[k, 80000][0] < 8 * took[k, 20000][0])
              for k in ("details", "tab")), str(took))

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
# a hidden panel too long for the text, beside little else: its marker came back from page.md with nothing under it,
# and its words, counted as the page's alone, made the whole text a fragment (32 %; KNOWN-ISSUES 299)
TABS_LONG = ("<!doctype html><html><head><meta charset='utf-8'><title>Plans</title></head><body><main><article>"
             "<h1>Plans</h1><p>LONG-INTRO " + " ".join([EN] * 4) + "</p><div role='tablist'>"
             "<button role='tab' aria-selected='true' aria-controls='q1'>Free Plan</button>"
             "<button role='tab' aria-selected='false' aria-controls='q2'>Developer Plan</button>"
             "<button role='tab' aria-selected='false' aria-controls='q3'>Batch Plan</button></div>"
             "<div role='tabpanel' id='q1'><p>LONG-FREE " + " ".join([EN] * 3) + "</p></div>"
             "<div role='tabpanel' id='q2' hidden><p>LONG-DEV " + " ".join([EN] * 45) + "</p></div>"
             "<p>LONG-OUTRO " + " ".join([EN] * 3) + "</p></article></main></body></html>").encode("utf-8")
# a price table whose header spans columns, inside the article (japanrailpass.net's, KNOWN-ISSUES 338)
PRICES = ("<!doctype html><html><head><meta charset='utf-8'><title>Prices</title></head><body>" + NAV +
          "<main><article><h1>Types and prices</h1><p>PRICES-INTRO " + EN * 3 + "</p><h2>JAPAN RAIL PASS prices</h2>"
          "<p>Prices of Exchange Orders</p>" + JR_HTML + "<p>" + JR_NOTE + "</p><p>PRICES-END " + EN * 2 + "</p>"
          "</article></main></body></html>").encode("utf-8")
s = serve({"/guide": (200, {"Content-Type": "text/html; charset=utf-8"}, HTML),
           "/prices": (200, {"Content-Type": "text/html; charset=utf-8"}, PRICES),
           "/files": (200, {"Content-Type": "text/html; charset=utf-8"}, FILES.encode("utf-8")),
           "/tabs-long": (200, {"Content-Type": "text/html; charset=utf-8"}, TABS_LONG),
           "/spec": (200, {"Content-Type": "text/html; charset=utf-8"}, SPEC),
           "/svg": (200, {"Content-Type": "text/html; charset=utf-8"}, SVGPAGE),
           "/linky": (200, {"Content-Type": "text/html; charset=utf-8"}, LINKY),
           "/tabs": (200, {"Content-Type": "text/html; charset=utf-8"}, TABS.encode("utf-8"))})
try:
    # a read of a page with tabs: whatever extractor wins, the markers stand where the page has them
    r = run_read(s.url("/tabs"), env={"READ_PAGE_SKIP": "browser"})
    body, page = r.file("content.md"), r.file("page.md")
    eng = str((r.manifest.get("content") or {}).get("engine") or "")
    check("a read: the tab set's markers in content.md, the shown tab's text after its marker, the hidden "
          "tab's text after its own (KNOWN-ISSUES 256)",
          0 <= body.find("[tab · shown · Free Plan Limits]") < body.find("FREE-PANEL")
          < body.find("[tab · hidden, but extracted · Developer Plan Limits]") < body.find("DEV-PANEL"),
          "%s: %s" % (eng, [ln[:60] for ln in body.split("\n") if "[tab" in ln or "PANEL" in ln][:6]))
    check("a read: a tab the page does not hold is named, not extracted (KNOWN-ISSUES 257)",
          "[tab · loads on click, not extracted · Batch Limits]" in body
          and body.find("[tab · loads on click, not extracted · Developer Plan Limits]") > body.find("TABLE-ROW-5"),
          "%s: %s" % (eng, [ln[:70] for ln in body.split("\n") if "click" in ln][:3]))
    check("a read: a closed section and a collapsed accordion are marked, their text after them; a select names "
          "its choice (KNOWN-ISSUES 258)",
          0 <= body.find("[section · hidden, but extracted · Specifications]") < body.find("SPEC-PARA")
          and 0 <= body.find("[section · hidden, but extracted · How do I pay?]") < body.find("FAQ-PARA")
          and "[select · chosen: EU · also US, APAC · Region]" in body,
          "%s: %s" % (eng, [ln[:70] for ln in body.split("\n") if "[section" in ln or "[select" in ln][:3]))
    m_long = re.search(r"too long for here: page\.md from line (\d+) · Go\]", body)
    check("a read: a hidden panel too long for the text names the line of page.md where it is, and is not "
          "put back by the block rule",
          m_long is not None and "GO-CODE" not in body
          and "[tab · hidden, but extracted · Go]" in page.split("\n")[int(m_long.group(1)) - 1],
          "%s: %s" % (eng, [ln[:90] for ln in body.split("\n") if "· Go]" in ln][:1]))
    check("a read: the manifest counts them", ((r.manifest.get("signals") or {}).get("tabs") or {}).get("tabs") == 3,
          str((r.manifest.get("signals") or {}).get("tabs")))
    r = run_read(s.url("/tabs-long"), env={"READ_PAGE_SKIP": "browser"})
    body = r.file("content.md")
    dev = [ln for ln in body.split("\n") if "· Developer Plan]" in ln]
    check("a hidden panel too long for the text: one marker of it in content.md, the one that says where it is - no "
          "copy of page.md's beside the text before it (KNOWN-ISSUES 299)",
          len(dev) == 1 and "too long for here" in dev[0] and "LONG-DEV" not in body, str([x[:70] for x in dev]))
    sig = r.manifest.get("signals") or {}
    check("... and its words count as the text's: no fragment, the answer is content.md",
          not sig.get("fragment") and "maybe a fragment" not in r.text.split("\n")[0]
          and "── content.md: from line 1 of " in r.text,
          "cover %s; %s" % ((r.manifest.get("content") or {}).get("cover"), r.text.split("\n")[0][:90]))
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
    r = run_read(s.url("/prices"), env={"READ_PAGE_SKIP": "browser"})
    body = r.file("content.md")
    eng = str((r.manifest.get("content") or {}).get("engine") or "")
    check("338: a read of a price table whose header spans columns: each price once in content.md, as a Markdown "
          "table, no HTML (defuddle kept it as HTML and the block rule put page.md's rows beside it)",
          body.count("70,000 YEN") == 1 and body.count("110,000 YEN") == 1 and "<table" not in body
          and "PRICES-NOTE" in body, "%s: %d, %d, html %s | %s" % (
              eng, body.count("70,000 YEN"), body.count("110,000 YEN"), "<table" in body,
              [ln[:60] for ln in body.split("\n") if "YEN" in ln][:4]))
    r = run_read(s.url("/files"), env={"READ_PAGE_SKIP": "browser"})
    body = r.file("content.md")
    eng = str((r.manifest.get("content") or {}).get("engine") or "")
    a, b, c, d = (body.find("[section · hidden, but extracted · Historische Daten]"), body.find("VPI_1977_bis_2025.ods"),
                  body.find("3_HVPI_2015.ods"), body.find("FILES-AFTER"))
    check("339: a read: a collapsed section's two .ods links are in content.md under its marker, once each (the text "
          "had its heading with nothing under it)", 0 <= a < b < c < d and body.count("3_HVPI_2015.ods") == 1
          and body.count("VPI_1977_bis_2025.ods") == 1, "%s: %s | %s" % (
              eng, (a, b, c, d), [ln[:70] for ln in body.split("\n") if "Historische" in ln or ".ods" in ln][:4]))
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
