"""The extractor only suggests. A block of page.md that the text lacks goes back after
its kept neighbour when it is prose, code, a table or a captioned figure; menus, lists of links,
fragments and cookie banners stay out, and the answer says how much stayed out.

    import blockrule; text, info = blockrule.restore(content_md, page_md)

A block is a run of lines between blank lines; a fenced code block is one block, blank lines and
all. A block is in the text when at least half of its 5-word runs are: the two files come from
different converters, so their markup differs and raw substrings do not compare. Words are runs of
letters and digits; Chinese, Japanese and Korean count by character. A heading goes back with the
section it heads. On the 60 extracted pages of a measured corpus 23 change: 22 of the 59 ordinary
ones gain 95 KB in all (+2.1 %), and RFC 9110, where trafilatura kept 5.5 KB of a 470 KB page,
goes from 5.5 to 374 KB. At worst 0.3 s a page. Standard library only.
"""
import re

import pictures

CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯"
WORD = re.compile(r"[%s]|[^\W_%s]+" % (CJK, CJK))
LINK = re.compile(r"!?\[([^\]]*)\]\((?:[^()\\]|\\.|\([^)]*\))*\)")
IMAGE = re.compile(r"!\[[^\]]*\]\((?:[^()\\]|\\.|\([^)]*\))*\)")
ITEM = re.compile(r"\s*([*+-]|\d+[.)])\s")
# what is left of a link html2text broke across lines, and bare addresses: not words
URL_DEBRIS = re.compile(r"\]\([^)\s]*\)?|<?\b(?:https?|ftp)://[^\s>)\]]+>?")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")    # ---|--- under a header
HEADING = re.compile(r"#{1,6}\s+\S")
# a tab's or a section's marker (tabs.py) heads its panel as a heading does, and stands beside it
MARKER = re.compile(r"\\?\[(tab|section|select) · [^\n]*\]\s*$")
# a banner says one of these and is short; a long paragraph about privacy is prose
BOILER = re.compile(r"(?i)cookie|privacy|copyright|©|all rights reserved|subscribe|newsletter|"
                    r"sign(ed)? (in|up|out)|"
                    r"log ?in|terms of (use|service)|follow us|share this|advertis|"
                    r"куки|конфиденциальн|"
                    r"все права защищены|"
                    r"datenschutz|alle rechte vorbehalten|confidentialit|tous droits r|privacidad|derechos reservados|"
                    r"クッキー|個人情報|隐私|版权所有")
K = 5                  # words in a run
PROSE_WORDS = 25       # a paragraph shorter than this is a fragment
BOILER_WORDS = 80      # a banner is shorter than this
BACK = ("prose", "code", "table", "figure")
MAX_PAGE = 4 * 1024 * 1024     # page.md bigger than this is left as it is: the work grows with it


def words(s):
    """The words of a block: a link's text counts, its address and any loose address do not."""
    s = URL_DEBRIS.sub(" ", LINK.sub(r"\1", s or ""))
    return [w.lower() for w in WORD.findall(s)]


def runs(ws, k=K):
    """The k-word runs of a block; a block shorter than k is one run of all its words."""
    k = min(k, len(ws))
    return [" ".join(ws[i:i + k]) for i in range(len(ws) - k + 1)] if k else []


def spans(md):
    """(start, end) of every block in `md`: lines between blank lines, a fenced block whole."""
    out, start, end, fence, pos = [], None, None, "", 0
    for line in (md or "").split("\n"):
        s = line.strip()
        if s.startswith(("```", "~~~")):
            if not fence:
                fence = s[:3]
            elif s.startswith(fence):
                fence = ""
        if s or fence:
            if start is None:
                start = pos
            end = pos + len(line)
        elif start is not None:
            out.append((start, end))
            start = None
        pos += len(line) + 1
    if start is not None:
        out.append((start, end))
    return out


def blocks(md):
    return [md[a:b] for a, b in spans(md)]


def kind(b, ws=None):
    """prose, code, table, figure (they go back); heading (with its section); links, boiler,
    short, image (they stay out)."""
    ws = words(b) if ws is None else ws
    lines = [ln for ln in b.split("\n") if ln.strip()]
    s = b.lstrip()
    if s.startswith(("```", "~~~")):
        return "code"
    if len(lines) == 1 and HEADING.match(s):
        return "heading"
    if len(lines) == 1 and MARKER.match(s):
        return "marker"
    items = [ln for ln in lines if ITEM.match(ln)]
    # the words around the pictures decide: a picture's alt is not a link, and a link that only
    # wraps a picture (a thumbnail to its full size) is not navigation
    has_img = bool(IMAGE.search(b))
    bare = IMAGE.sub(" ", b) if has_img else b
    cw = words(bare) if has_img else ws
    vis = LINK.sub(r"\1", bare)
    linked = sum(len(m.group(1).strip()) for m in LINK.finditer(bare))
    dens = linked / max(1, len(vis.strip()))
    if (len(lines) >= 2 and len(ws) > 5 and len(items) < 0.6 * len(lines) and dens < 0.5
            and all(ln.startswith(("    ", "\t")) for ln in lines)):
        return "code"              # indented code; a nested menu is indented too, but is items or links
    if (sum(1 for ln in lines if ln.lstrip().startswith("|")) >= 2
            or (len(lines) >= 2 and any(TABLE_RULE.match(ln) for ln in lines[:3]))):
        return "links" if dens >= 0.5 else "table"     # a layout table of links is a menu
    # a menu first, pictures or not: GitHub's "Platform" entry has a picture and a few words, and
    # was a "captioned figure" before this came first
    if items and len(items) >= 0.6 * len(lines) and len(cw) / len(items) <= 7:
        return "links"
    if not has_img and len(lines) >= 4 and sorted(len(words(ln)) for ln in lines)[len(lines) // 2] <= 4:
        return "links"             # a menu without markup, as a browser's innerText gives it
    if dens >= 0.5:
        return "links"
    if has_img:
        return "figure" if len(cw) >= 3 else "image"
    if len(ws) >= PROSE_WORDS and dens < 0.3:
        return "boiler" if BOILER.search(b) and len(ws) < BOILER_WORDS else "prose"
    return "short"


def restore(content, page, base="", out=()):
    """The text with the dropped blocks of page.md back in place, and the numbers for the manifest:
    {"restored": blocks put back, "restored_bytes": their size, "pictures": pictures put back,
    "outside": bytes still only in page.md}. A text that already holds every block comes back
    unchanged.

    Pictures follow their blocks: a picture block between shown blocks goes back
    where it stood, and a picture the extractor took out of a paragraph it kept goes back right
    after that paragraph. A picture next to a menu or a footer stays out with it. `base` resolves
    page.md's relative addresses, so the same picture is recognised in both files. `out` are texts
    that stay in page.md alone (a hidden tab panel too long for the text): a block of theirs is not
    put back."""
    info = {"restored": 0, "restored_bytes": 0, "pictures": 0, "outside": 0}
    if not (content or "").strip() or not (page or "").strip() or len(page) > MAX_PAGE:
        return content, info
    pb = blocks(page)
    pw = [words(b) for b in pb]
    cw = words(content)
    have = set(runs(cw))
    away = set()
    for t in out or ():
        away.update(runs(words(t)))
    short = set()
    for n in range(1, K):
        short.update(" ".join(cw[i:i + n]) for i in range(len(cw) - n + 1))
    kinds = [kind(b, ws) for b, ws in zip(pb, pw)]
    shown_pics = {pictures.resolve(src, base) for _a, _b, _alt, src in pictures.links(content)}
    pics = [[(alt, src, pictures.resolve(src, base)) for _a, _b, alt, src in pictures.links(b)] for b in pb]
    kept = []
    for i, ws in enumerate(pw):
        if kinds[i] == "image":                # a picture block is in the text when its pictures are
            kept.append(all(url in shown_pics for _alt, _src, url in pics[i]))
        elif not ws:
            kept.append(None)                  # a rule: nothing to compare
        elif len(ws) < K:
            kept.append(" ".join(ws) in short)
        else:
            rs = runs(ws)
            kept.append(sum(1 for r in rs if r in have) / len(rs) >= 0.5)

    back, seen = [False] * len(pb), set()
    for i, k in enumerate(kinds):
        if kept[i] is False and k in BACK:
            rs = runs(pw[i]) if away else []
            if rs and sum(1 for r in rs if r in away) / len(rs) >= 0.5:
                continue                       # a block of a text that stays in page.md
            key = " ".join(pw[i])
            if key not in seen:                # a paragraph the page repeats goes back once
                seen.add(key)
                back[i] = True
    for i in range(len(pb)):                   # a marker goes with the text beside it, kept or put back
        if kept[i] is False and kinds[i] == "marker":
            near = []
            for step in (1, -1):
                j = i + step
                while 0 <= j < len(pb) and (kinds[j] == "marker" or kept[j] is None):
                    j += step
                if 0 <= j < len(pb):
                    near.append(j)
            back[i] = any(back[j] or (kept[j] and len(pw[j]) >= K) for j in near)
    for i in range(len(pb) - 1, -1, -1):       # backwards: an h2 above an h3 above a paragraph
        if kept[i] is False and kinds[i] == "heading":
            j = i + 1
            while j < len(pb) and (kept[j] is None or kinds[j] == "image"):
                j += 1
            back[i] = j < len(pb) and back[j]

    def shown(j):
        # a fragment of a few words counts as kept whenever its words occur anywhere in the text
        # ("Search"), so only a block of real length vouches for the picture next to it
        return j is not None and bool(back[j] or (kept[j] and len(pw[j]) >= K))

    def text_near(i, step):
        # the nearest block of text: pictures and rules in between are skipped, and so are
        # fragments - but not a menu, however short: that is where the shown text ends
        # (Wikipedia's logo sits between two menus and a "Search" link)
        j = i + step
        while 0 <= j < len(pb) and (kinds[j] == "image" or kept[j] is None
                                     or (len(pw[j]) < K and kinds[j] != "links")):
            j += step
        return j if 0 <= j < len(pb) else None

    placed = set(shown_pics)
    for i in range(len(pb)):
        if back[i]:
            placed.update(url for _alt, _src, url in pics[i])
    for i in range(len(pb)):                   # a picture block goes back with the text around it
        if kinds[i] == "image" and BOILER.search(" ".join(alt for alt, _s, _u in pics[i])):
            continue                           # "Follow us", "Share", "Subscribe": a banner's icon
        if kinds[i] == "image" and kept[i] is False and (shown(text_near(i, -1)) or shown(text_near(i, 1))):
            new = [url for _alt, _src, url in pics[i] if url not in placed]
            if new:
                back[i] = True
                placed.update(new)
    adds = {}                                  # pictures taken out of a paragraph that stayed
    for i in range(len(pb)):
        if kept[i] and kinds[i] != "image":
            lost = [(alt, src, url) for alt, src, url in pics[i] if url not in placed]
            if lost:
                adds[i] = " ".join("![%s](%s)" % (alt, src) for alt, src, _url in lost)
                placed.update(url for _alt, _src, url in lost)
    info["outside"] = sum(len(pb[i].encode("utf-8")) for i in range(len(pb)) if kept[i] is False and not back[i])
    if not any(back) and not adds:
        return content, info

    # which kept block of page.md each block of the text came from: most shared runs, and of
    # equals the first one at or after the last match (repeated sentences stay in order)
    index = {}
    for i, ws in enumerate(pw):
        if kept[i] and kinds[i] != "image":
            for r in set(runs(ws)):
                index.setdefault(r, []).append(i)
    cspans = spans(content)
    last_of, last = {}, 0
    for c, (a, b) in enumerate(cspans):
        counts = {}
        for r in set(runs(words(content[a:b]))):
            hits = index.get(r)
            if hits and len(hits) <= 20:       # a phrase on every card says nothing about where
                for i in hits:
                    counts[i] = counts.get(i, 0) + 1
        if counts:
            top = max(counts.values())
            best = [i for i, n in counts.items() if n == top]
            pick = min([i for i in best if i >= last] or best)
            last_of[pick] = c                  # the last block of the text that came from it
            last = pick

    after, prev = {}, None
    for i in range(len(pb)):
        if kept[i] and i in last_of:
            prev = i
            if i in adds:
                after.setdefault(last_of[i], []).append(adds[i])
                info["pictures"] += adds[i].count("![")
        elif back[i]:
            after.setdefault(last_of[prev] if prev is not None else -1, []).append(pb[i])
            info["restored"] += 1
            info["restored_bytes"] += len(pb[i].encode("utf-8"))
            info["pictures"] += len(pics[i])
    out, pos = [], 0
    if -1 in after and cspans:
        a = cspans[0][0]
        out += [content[:a], "\n\n".join(after[-1]), "\n\n"]
        pos = a
    for c, (a, b) in enumerate(cspans):
        if c in after:
            out += [content[pos:b], "\n\n", "\n\n".join(after[c])]
            pos = b
    out.append(content[pos:])
    return "".join(out), info
