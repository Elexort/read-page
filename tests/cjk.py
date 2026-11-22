"""Chinese, Japanese, Korean and Russian input on any machine: what a Chinese Windows does to the core.
No network.

    python -X utf8 tests/cjk.py

On a machine whose people write Chinese (ANSI code page 936, Big5's 950, Shift_JIS's 932, 949) nothing in
the skill may depend on the locale's code page or on a pure-ASCII address, name or folder. This suite is the
whole of it, offline, and passes the same on every OS:

- a GBK, Big5, Shift_JIS, EUC-KR or KOI8 page that says nothing about its encoding is read right, with
  charset_normalizer installed and without it (the core before `--setup`), short texts too - and a reading
  that is a guess says so in the manifest;
- a declared gb2312 that holds one character outside GB2312 is still Chinese;
- the MCP server's standard input is UTF-8 whatever the locale (a Chinese URL, a Chinese folder);
- a raw non-ASCII address reaches the server as UTF-8 through each HTTP channel (curl_cffi, curl, urllib) and
  for a picture, and a redirect's raw Location goes where a browser goes;
- a server's Chinese file name (Content-Disposition, GBK bytes too) is kept;
- OCR asks for the language pack of the user's language and of the text's script, and names a missing one;
- a tool that takes narrow arguments is given an ASCII path;
- the languages that are sent - Accept-Language, the subtitle tracks, the browser's locale - are the user's own;
- a home folder, a cache and a folder for the answer, all in Chinese.

On Windows `tools`-less way to make the code page real: run this file with a python.exe whose manifest says
`<activeCodePage>zh-CN</activeCodePage>` (GetACP() is then 936 for that process).
"""
import contextlib
import importlib.util
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
MCP = os.path.join(SCRIPTS, "mcp_server.py")

from harness import PUBLIC, SCRIPT, Checks, serve                 # noqa: E402

check = Checks()
for _name in ("READ_PAGE_LANG", "READ_PAGE_SUB_LANGS", "READ_PAGE_OCR_LANGS"):
    os.environ.pop(_name, None)            # a suite sees only what it sets
ROOT = tempfile.mkdtemp(prefix="rp-cjk-")
# Windows paths are wide, and a UTF-8 file system is UTF-8: a folder named in Chinese reaches a child as it is. Under
# a POSIX locale that is not UTF-8 (LC_ALL=zh_CN.GBK) the children, started with -X utf8, read their arguments and
# environment as UTF-8 and the file system holds GBK (KNOWN-ISSUES 175, planned): the folders there are ASCII.
UTF8_PATHS = os.name == "nt" or sys.getfilesystemencoding().lower().replace("-", "") == "utf8"


def named(chinese, ascii_name):
    return chinese if UTF8_PATHS else ascii_name




def png(w, h, rgb=(200, 30, 30)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- texts
ZH_S = ("北京是中华人民共和国的首都，也是全国的政治中心和文化中心。这座城市拥有三千多年的历史，故宫、长城和颐和园每年吸引着"
        "数以百万计的游客。近年来，随着经济的快速发展，市民的生活水平不断提高，地铁线路已经覆盖了大部分城区。")
ZH_T = ("臺北是臺灣的首府，也是全國的經濟與文化中心。這座城市擁有許多著名的景點，例如故宮博物院、臺北一百零一大樓和各式各樣"
        "的夜市。許多遊客來到這裡，品嚐道地的小吃，感受濃厚的人情味。功蓋天下，淚眼擺渡。")
JA = ("吾輩は猫である。名前はまだ無い。どこで生れたかとんと見当がつかぬ。何でも薄暗いじめじめした所でニャーニャー泣いていた事"
      "だけは記憶している。")
KO = "대한민국의 수도는 서울이며 역사가 깊고 많은 유명한 명소와 풍부한 문화유산을 가지고 있습니다. 문의해 주셔서 감사합니다."
RU = ("Съешь же ещё этих мягких французских булок, да выпей чаю. Широкая электрификация южных губерний даст "
      "мощный толчок подъёму сельского хозяйства.")
DE = "Über die Brücke führt ein schmaler Weg, der Bäcker verkauft frische Brötchen für drei Euro."
ELEMENTS = "氢氦锂铍硼碳氮氧氟氖钠镁铝硅磷硫氯氩钾钙钪钛钒铬锰铁钴镍铜锌镓锗砷硒溴氪铷锶钇锆铌钼锝钌铑钯银镉铟锡锑碲碘氙"
PROVINCES = "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼港澳台"
EL = ("Η Αθήνα είναι η πρωτεύουσα και η μεγαλύτερη πόλη της Ελλάδας. Η πόλη έχει μακρά ιστορία και πολλά αρχαία "
      "μνημεία, όπως η Ακρόπολη και ο Παρθενώνας. Κάθε χρόνο εκατομμύρια επισκέπτες έρχονται για να δουν τα μουσεία "
      "και τους δρόμους της παλιάς πόλης.")
HE = ("ירושלים היא בירת ישראל והעיר הגדולה ביותר במדינה. בעיר יש אתרים היסטוריים רבים, ומיליוני תיירים מבקרים בה "
      "בכל שנה. רוב התושבים מדברים עברית, ורבים מדברים גם ערבית ואנגלית.")
TH = ("กรุงเทพมหานครเป็นเมืองหลวงและเมืองที่ใหญ่ที่สุดของประเทศไทย เมืองนี้ตั้งอยู่ริมแม่น้ำเจ้าพระยา และมีวัดที่สวยงามมากมาย "
      "นักท่องเที่ยวจำนวนมากมาเยี่ยมชมพระบรมมหาราชวังทุกปี")
UK = ("Київ є столицею та найбільшим містом України. Місто розташоване на березі Дніпра, і в ньому є багато "
      "старовинних церков, музеїв та парків. Щороку сюди приїжджають тисячі туристів із різних країн світу.")
AR = ("القاهرة هي عاصمة مصر وأكبر مدنها، وتقع على ضفاف نهر النيل. يعيش فيها ملايين الناس، وفيها كثير من المساجد "
      "والمتاحف القديمة. يزورها السياح من جميع أنحاء العالم كل عام.")
CS = ("Praha je hlavní a největší město České republiky. Leží na řece Vltavě a každý rok ji navštíví miliony "
      "turistů, kteří obdivují Pražský hrad, Karlův most a Staroměstské náměstí.")
HU = ("Budapest Magyarország fővárosa és legnagyobb városa. A Duna két partján fekszik, és sok szép épülete, hídja "
      "és fürdője van, amelyeket évente turisták milliói látogatnak meg.")
SHORT = {                                     # what a CSV, a one-line text file and a fragment are
    "a two-row CSV": ("姓名,电话\n张伟,13800000000\n李娜,13900000000\n", "gbk"),
    "a one-line text": ("你好，世界！这是一个测试。", "gbk"),
    "an HTML fragment": ("<p>欢迎访问我们的网站</p>", "gbk"),
    "a Big5 line": ("歡迎蒞臨本公司網站，請聯絡客服人員。", "big5"),
    "a Shift_JIS line": ("お問い合わせありがとうございます。", "shift_jis"),
    "an EUC-KR line": ("안녕하세요 여러분, 환영합니다.", "euc-kr"),
}
LONG = [("simplified Chinese in GBK", ZH_S, "gbk"), ("simplified Chinese in GB18030", ZH_S, "gb18030"),
        ("traditional Chinese in Big5", ZH_T, "big5"), ("Japanese in Shift_JIS", JA, "shift_jis"),
        ("Japanese in EUC-JP", JA, "euc_jp"), ("Korean in EUC-KR", KO, "euc-kr"),
        ("Russian in windows-1251", RU, "cp1251"), ("Russian in KOI8-R", RU, "koi8-r"),
        ("German in windows-1252", DE, "cp1252")]


def module():
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-cjk-cache-", dir=ROOT)   # removed with ROOT
    spec = importlib.util.spec_from_file_location("rp_cjk_%d" % len(sys.modules), SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextlib.contextmanager
def without_charset_normalizer():
    """What a machine that never ran --setup has: the import fails."""
    old = sys.modules.get("charset_normalizer", False)
    sys.modules["charset_normalizer"] = None
    try:
        yield
    finally:
        if old is False:
            sys.modules.pop("charset_normalizer", None)
        else:
            sys.modules["charset_normalizer"] = old


def has_charset_normalizer():
    return importlib.util.find_spec("charset_normalizer") is not None


def attempt(fn, *a):
    try:
        return fn(*a)
    except Exception as e:                                    # noqa: BLE001
        return "%s: %s" % (type(e).__name__, e)


mod = module()

# ---------------------------------------------------------------- 1. text decoding
shapes = [("core, no charset_normalizer", without_charset_normalizer)]
if has_charset_normalizer():
    shapes.append(("with charset_normalizer", contextlib.nullcontext))
else:
    check.skip("decoding with charset_normalizer", "it is not installed here")
for shape, ctx in shapes:
    with ctx():
        for name, text, enc in LONG:
            got = attempt(lambda: mod.smart_decode(text.encode(enc), "text/html"))
            ok = isinstance(got, tuple) and text in got[0]
            check("decode, %s: %s, nothing declared" % (shape, name), ok,
                  got[1] if isinstance(got, tuple) and ok else (got[0][:24] if isinstance(got, tuple) else got))
        for name, (text, enc) in SHORT.items():
            got = attempt(lambda: mod.smart_decode(text.encode(enc), ""))
            ok = isinstance(got, tuple) and text in got[0]
            check("decode, %s: %s" % (shape, name), ok,
                  got[1] if isinstance(got, tuple) and ok else (got[0][:24] if isinstance(got, tuple) else got))
        page = ("<html><head><title>公司</title></head><body><p>%s</p></body></html>" % ZH_S).encode("gbk")
        got = attempt(lambda: mod.smart_decode(page, "text/html"))
        check("decode, %s: a whole GBK page with markup" % shape, isinstance(got, tuple) and ZH_S in got[0],
              str(got[1] if isinstance(got, tuple) else got))
        # a page that says gb2312 and holds characters GB2312 lacks (browsers read gb2312 as gb18030)
        rare = "镕基喆㎡〇的故事是这样的：他在二〇〇八年来到北京，住在一百二十平方米(120㎡)的房子里，经常和朋友喝茶聊天。"
        for label in ("gb2312", "GBK", "x-gbk"):
            got = attempt(lambda: mod.smart_decode(rare.encode("gb18030"), "text/html; charset=" + label))
            check("decode, %s: declared %s with characters outside GB2312" % (shape, label),
                  isinstance(got, tuple) and rare in got[0], str(got[:1] if not isinstance(got, tuple) else got[1]))
        meta = ("<html><head><meta http-equiv='Content-Type' content='text/html; charset=big5'></head><body>%s"
                "</body></html>" % ZH_T).encode("big5hkscs")
        got = attempt(lambda: mod.smart_decode(meta, "text/html"))
        check("decode, %s: Big5 declared in <meta>" % shape, isinstance(got, tuple) and ZH_T in got[0], "")
        got = attempt(lambda: mod.smart_decode(ZH_S.encode("utf-8")[:-1], "text/html"))
        check("decode, %s: UTF-8 cut in the middle of a character stays UTF-8" % shape,
              isinstance(got, tuple) and ZH_S[:-1] in got[0], str(got[1] if isinstance(got, tuple) else got))
        got = attempt(lambda: mod.smart_decode(("<p>%s</p>" % ZH_S).encode("gbk"), "text/html; charset=utf-8"))
        check("decode, %s: a UTF-8 label on GBK bytes does not win" % shape,
              isinstance(got, tuple) and ZH_S in got[0], str(got[1] if isinstance(got, tuple) else got))
        # a true label over characters none of which is common: kept (it was dropped for a guess)
        for label, body, ct, want in (
                ("<meta charset=gb2312> over a periodic table", ("<meta charset=gb2312><p>%s</p>" % ELEMENTS).encode("gbk"),
                 "text/html", ELEMENTS),
                ("a gb2312 header over the provinces' one-character names", ("<p>%s</p>" % PROVINCES).encode("gbk"),
                 "text/html; charset=gb2312", PROVINCES)):
            d = attempt(mod.decode_page, body, ct)
            check("decode, %s: %s is read as declared" % (shape, label),
                  want in getattr(d, "text", "") and getattr(d, "how", "") == "declared",
                  "%s/%s" % (getattr(d, "charset", d), getattr(d, "how", "")))
        got = attempt(lambda: mod.smart_decode(("<p>%s</p>" % ZH_S).encode("gbk"), "text/html; charset=big5"))
        check("decode, %s: a big5 label on GBK bytes does not win" % shape,
              isinstance(got, tuple) and ZH_S in got[0], str(got[1] if isinstance(got, tuple) else got))

# a document's own XML part (EPUB, ODT) that says gb2312 and holds a character GB2312 lacks: read as a browser
# reads it, not U+FFFD throughout
part = ('<?xml version="1.0" encoding="gb2312"?><p>%s</p>' % rare).encode("gb18030")
got = attempt(mod.docreaders._decode, part)
check("a document's XML part declared gb2312 with characters outside GB2312 is read whole", rare in str(got),
      str(got)[:60])

# a PDF table's caption stays text where it stood: in Chinese, Japanese and Korean too
caption = getattr(mod.pdftables, "CAPTION", None)
said = {x: bool(caption and caption.match(x)) for x in ("表 3 各地区人口", "表3：主要指标", "表３　売上高", "表一 年度预算",
                                                       "表 2-1 结果", "표 2 연도별 매출", "Table 4: results",
                                                       "表3所示的数据说明了", "表面上看")}
check("a table's caption is known in Chinese, Japanese and Korean (表 3, 表3, 表一, 표 2), not a sentence about it",
      all(said[x] for x in list(said)[:7]) and not any(said[x] for x in list(said)[7:]), str(said))

# a guess says that it is one
d = attempt(lambda: mod.decode_page(ZH_S.encode("gbk"), ""))
check("a decode by guess is named as one (how=guessed)", getattr(d, "how", "") == "guessed", str(getattr(d, "how", d)))
d = attempt(lambda: mod.decode_page(ZH_S.encode("gbk"), "text/html; charset=gbk"))
check("a declared charset is not a guess", getattr(d, "how", "") == "declared" and not getattr(d, "doubt", True), "")
d = attempt(lambda: mod.decode_page("你好".encode("gbk"), ""))
check("two characters of undeclared GBK are read, and the reading is called doubtful",
      getattr(d, "text", "") == "你好" and getattr(d, "doubt", False) is True, str(getattr(d, "text", d)))
d = attempt(lambda: mod.decode_page(ZH_S.encode("gbk"), ""))
check("a whole undeclared page is not doubtful", getattr(d, "doubt", True) is False, "")

# the other single-byte scripts: their bytes are letters in windows-1251 and KOI8 too, and were read as Cyrillic
# (Greek, Hebrew) or box drawing (Thai, Ukrainian's KOI8-U), with charset_normalizer installed as well - it was
# never asked. A reading that may be wrong says so; with charset_normalizer it is the right one.
WEST = [("Greek", "cp1253", EL), ("Greek", "iso-8859-7", EL), ("Hebrew", "cp1255", HE), ("Thai", "cp874", TH),
        ("Ukrainian", "koi8-u", UK), ("Ukrainian", "cp1251", UK), ("Arabic", "cp1256", AR), ("Czech", "cp1250", CS),
        ("Hungarian", "cp1250", HU)]
for shape, ctx in shapes:
    with ctx():
        silent, wrong = [], []
        for lang, enc, text in WEST:
            d = attempt(mod.decode_page, text.encode(enc), "")
            right = getattr(d, "text", None) == text
            if not right and not getattr(d, "doubt", False):
                silent.append("%s %s -> %s" % (lang, enc, getattr(d, "charset", d)))
            # with charset_normalizer: all but Hebrew (a doubt is enough there) and Hungarian (it takes cp1252)
            if not right and (lang == "Ukrainian" or (shape != shapes[0][0] and lang not in ("Hebrew", "Hungarian"))):
                wrong.append("%s %s -> %s" % (lang, enc, getattr(d, "charset", d)))
        check("decode, %s: Greek, Hebrew, Thai, Arabic, Czech, Hungarian, Ukrainian prose - a wrong reading is "
              "never silent" % shape, not silent, "; ".join(silent[:3]))
        check("decode, %s: %s" % (shape, "Ukrainian in KOI8-U and windows-1251 is read right" if shape == shapes[0][0]
                                  else "and each is read right (Hebrew: or doubtful)"), not wrong, "; ".join(wrong[:3]))

# ---------------------------------------------------------------- 2. pages through the CLI


def html(body, title="测试", extra=""):
    return ("<!doctype html><html><head>%s<title>%s</title></head><body><article><h1>%s</h1><p>%s</p></article>"
            "</body></html>" % (extra, title, title, body))


def cli(url, *flags, env=None, root=None, timeout=240):
    """One CLI read into a folder of its own; (rc, stdout bytes, manifest dict, folder)."""
    root = root or tempfile.mkdtemp(prefix="rp-cjk-run-", dir=ROOT)
    out = os.path.join(root, "out")
    e = dict(os.environ)
    e["READ_PAGE_CACHE"] = os.path.join(root, "cache")
    e["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    e["READ_PAGE_SKIP"] = ",".join(x for x in (e.get("READ_PAGE_SKIP", "").split(",") + ["env"]) if x)
    for k in ("FIRECRAWL_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "JINA_API_KEY"):
        e.pop(k, None)
    e.update(env or {})
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, url, "--dir", out] + list(flags),
                       capture_output=True, timeout=timeout, env=e)
    man = {}
    mp = os.path.join(out, "manifest.json")
    if os.path.isfile(mp):
        with open(mp, encoding="utf-8") as f:
            man = json.load(f)
    return p.returncode, p.stdout, man, out


def content(folder, name="content.md"):
    p = os.path.join(folder, name)
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


HTML_H = {"Content-Type": "text/html"}
body_s = "".join("<p>%s</p>" % s for s in ZH_S.split("。") if s)
srv = serve({
    "/gbk": (200, HTML_H, html(ZH_S).encode("gbk")),
    "/big5": (200, HTML_H, html(ZH_T, "臺北").encode("big5hkscs")),
    "/gbk-header": (200, {"Content-Type": "text/html; charset=gb2312"}, html(ZH_S + "镕喆", "文档").encode("gb18030")),
    "/plain-gbk": (200, {"Content-Type": "text/plain"}, ZH_S.encode("gbk")),
    "/utf8": (200, {"Content-Type": "text/html; charset=utf-8"}, html(ZH_S).encode("utf-8")),
    "/tiny-gbk": (200, HTML_H, "<html><body><p>你好</p></body></html>".encode("gbk")),
    "/few-gbk": (200, HTML_H, html(("Reading pages reliably is harder than it looks, because servers lie about what "
                                     "they send. " * 12) + "你好", "Notes").encode("gbk")),
    "/koi8u": (200, {"Content-Type": "text/plain"}, (UK + "\n").encode("koi8-u") * 3),
    "/hebrew": (200, {"Content-Type": "text/plain"}, (HE + "\n").encode("cp1255") * 3),
})
try:
    for path, want, label in (("/gbk", "中华人民共和国", "an undeclared GBK page"),
                              ("/big5", "臺灣的首府", "an undeclared Big5 page"),
                              ("/gbk-header", "镕喆", "a GB2312 page with characters outside GB2312"),
                              ("/plain-gbk", "中华人民共和国", "text/plain in GBK")):
        rc, out, man, folder = cli(srv.url(path))
        text = content(folder)
        check("CLI: %s is read right" % label, man.get("status") == "ok" and want in text,
              "%s %s" % (man.get("status"), text[:30].replace("\n", " ")))
    rc, out, man, folder = cli(srv.url("/gbk"))
    sig = (man.get("signals") or {}).get("charset_guess", "")
    check("CLI: a guessed charset is in the manifest's signals", "gb18030" in sig and "doubtful" not in sig, sig)
    check("CLI: and in the answer's first line, as a guess",
          "charset gb18030 (guessed)" in out.decode("utf-8", "replace").split("\n")[0],
          out.decode("utf-8", "replace").split("\n")[0][:120])
    rc, out, man, folder = cli(srv.url("/utf8"))
    check("CLI: a UTF-8 page has no guess to name", "charset_guess" not in (man.get("signals") or {}), "")
    rc, out, man, folder = cli(srv.url("/gbk-header"))
    check("CLI: a declared charset has no guess to name", "charset_guess" not in (man.get("signals") or {}), "")
    rc, out, man, folder = cli(srv.url("/tiny-gbk"))
    sig = (man.get("signals") or {}).get("charset_guess", "")
    first = out.decode("utf-8", "replace").split("\n")[0]
    check("CLI: a doubtful reading says so in the manifest and the answer's first line, not `ok` in silence",
          "doubtful" in sig and "guessed, doubtful" in first, "%s | %s" % (sig, first[:100]))
    rc, out, man, folder = cli(srv.url("/few-gbk"))
    check("... and on a page that is `ok` it leaves `advice` to what an agent can do (nothing can be done about it)",
          man.get("status") == "ok" and "doubtful" in str((man.get("signals") or {}).get("charset_guess"))
          and "encoding" not in str(man.get("advice") or ""), "%s %s" % (man.get("status"), str(man.get("advice"))[:100]))
    rc, out, man, folder = cli(srv.url("/koi8u"))
    check("CLI: an undeclared Ukrainian text in KOI8-U is read right (it was KOI8-R: box drawing)",
          man.get("status") == "ok" and "Київ є столицею" in content(folder),
          "%s %s" % ((man.get("url") or {}).get("charset"), content(folder)[:30].replace("\n", " ")))
    rc, out, man, folder = cli(srv.url("/hebrew"))
    first = out.decode("utf-8", "replace").split("\n")[0]
    check("CLI: an undeclared Hebrew text is read right, or its first line says the reading is doubtful",
          "ירושלים" in content(folder) or "doubtful" in first, "%s | %s" % ((man.get("url") or {}).get("charset"), first[:100]))
finally:
    srv.close()

# a file saved the way Excel on a Chinese Windows saves a CSV, in a folder named in Chinese
work = os.path.join(ROOT, named("文件夹", "folder"))
os.makedirs(work, exist_ok=True)
csv_path = os.path.join(work, named("客户名单.csv", "customers.csv"))
csv_text = "姓名,电话,城市\n张伟,13800000000,北京\n李娜,13900000000,上海\n王芳,13700000000,广州\n"
with open(csv_path, "wb") as f:
    f.write(csv_text.encode("gbk"))
txt_path = os.path.join(work, named("说明.txt", "note.txt"))
with open(txt_path, "wb") as f:
    f.write("这是一个测试。你好，世界！".encode("gbk"))
for path, want, label in ((csv_path, "李娜", "a GBK CSV"), (txt_path, "你好，世界", "a one-line GBK text")):
    rc, out, man, folder = cli(path)
    text = content(folder)
    check("CLI: %s in a Chinese folder, a local file, is read right" % label, want in text,
          "%s %s" % (man.get("status"), text[:30].replace("\n", " ")))

# ---------------------------------------------------------------- 3. addresses
cases = [("http://127.0.0.1:8080/页面?q=中文#片段", "http://127.0.0.1:8080/%E9%A1%B5%E9%9D%A2?q=%E4%B8%AD%E6%96%87#%E7%89%87%E6%AE%B5"),
         ("https://例子.测试/页面", "https://xn--fsqu00a.xn--0zwm56d/%E9%A1%B5%E9%9D%A2"),
         ("https://baike.baidu.com/item/中国", "https://baike.baidu.com/item/%E4%B8%AD%E5%9B%BD"),
         ("http://用户@例子.测试:8080/a b", "http://%E7%94%A8%E6%88%B7@xn--fsqu00a.xn--0zwm56d:8080/a%20b"),
         ("https://example.com/a%20b/%E4%B8%AD?x=1&y=中", "https://example.com/a%20b/%E4%B8%AD?x=1&y=%E4%B8%AD"),
         ("https://example.com/plain?a=b#c", "https://example.com/plain?a=b#c"),
         ("https://пример.рф/путь", "https://xn--e1afmkfd.xn--p1ai/%D0%BF%D1%83%D1%82%D1%8C"),
         # as a browser asks (Chrome's `new URL()`): a tab or a line break is left out, a backslash before the query
         # is a slash (the host ended at it), and the ASCII a browser escapes is escaped
         ("https://example.com/a\tb\nc/中", "https://example.com/abc/%E4%B8%AD"),
         ("https://例子.测试\\页面\\a", "https://xn--fsqu00a.xn--0zwm56d/%E9%A1%B5%E9%9D%A2/a"),
         ('https://example.com/<中>"`{}|^', "https://example.com/%3C%E4%B8%AD%3E%22%60%7B%7D%7C%5E"),
         ("https://example.com/中?a='b'&c=<d>\"e`f{g}", "https://example.com/%E4%B8%AD?a=%27b%27&c=%3Cd%3E%22e`f{g}"),
         ('https://example.com/中#a b%20c<>`"', "https://example.com/%E4%B8%AD#a%20b%20c%3C%3E%60%22"),
         ("  https://example.com/x  ", "https://example.com/x"),
         ("https://example.com/path\\to?q=a\\b#f\\g", "https://example.com/path/to?q=a\\b#f\\g"),
         ("https://example.com/%zz/中?x=%", "https://example.com/%zz/%E4%B8%AD?x=%")]
intl = attempt(lambda: __import__("intl"))
for raw, want in cases:
    got = attempt(lambda: intl.iri_to_uri(raw))
    check("iri_to_uri: %s" % raw[:44], got == want, str(got)[:90] if got != want else "")

# a host as a browser names it (UTS 46 non-transitional; each answer is Chrome's `new URL()`): IDNA 2003, the
# standard library's, sent faß.de to fass.de - another name, another site - and let through what a browser refuses
IDN = [("faß.de", "xn--fa-hia.de"), ("straße.de", "xn--strae-oqa.de"), ("σοφός.gr", "xn--0xagbn4a.gr"),
       ("ẞ.de", "xn--zca.de"), ("i❤.ws", "xn--i-7iq.ws"), ("例子。测试", "xn--fsqu00a.xn--0zwm56d"),
       ("ＥＸＡＭＰＬＥ.com", "example.com"), ("שלום1.com", "xn--1-9hcuf1d.com"), ("مثال1.com", "xn--1-ymcl5hc.com"),
       ("می\u200cخواهم.ir", "xn--mgbn2ecje63gr19l.ir"), ("क्\u200dष.in", "xn--11b2ezcw70k.in"),
       ("a\u200db.com", None), ("a\u200cb.com", None), ("שלוםa.com", None), ("a\u200eb.com", None), ("\ue000.com", None),
       ("́abc.com", None), ("⒈.com", None), ("שלום.1abc.com", None)]
wrong = [(h, attempt(intl.host_ascii, h)) for h, want in IDN if attempt(intl.host_ascii, h) != want]
check("a host goes out as a browser's name for it, and one a browser refuses has none (%d hosts)" % len(IDN),
      not wrong, str(wrong[:3]))
check("... the same name for a page's folder", mod.pictures.folder_prefix("faß.de") == "xn--fa-hia.de",
      mod.pictures.folder_prefix("faß.de"))
# the cookie jar is keyed by that name: a server sets its cookie for its punycode, and a jar keyed by the Unicode
# name never sent it back
jar = {"sid": {"v": "1", "d": "xn--fsqu00a.xn--0zwm56d", "e": 0, "p": "/", "s": False, "h": "xn--fsqu00a.xn--0zwm56d"}}
got = attempt(lambda: mod.cookies_for(jar, mod.host_of("http://例子.测试/a"), "/a", "http"))
check("a cookie an IDN site set for its punycode name goes back to it", isinstance(got, (list, dict)) and bool(got)
      and "sid" in str(got), str(got)[:80])


def accept_server():
    seen = []

    def page(h):
        seen.append({"path": h.path, "lang": h.headers.get("Accept-Language", ""), "ua": h.headers.get("User-Agent", "")})
        body = html("页面的正文，这是一个用来测试地址的页面。" * 5, "地址测试").encode("utf-8")
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(body)
        h.close_connection = True
    return seen, page


@contextlib.contextmanager
def channel(kind):
    """Force one HTTP channel of the page fetch: kind None is curl_cffi, "curl" the command, "urllib" the standard
    library. Yields False when this machine cannot give that channel (the check is then skipped)."""
    real_which = mod.which
    mod._CAPS_RUN.clear()
    ok = True
    if kind is None:
        ok = bool(mod.caps()["libs"].get("curl_cffi"))
    else:
        c = mod.caps()
        c["libs"]["curl_cffi"] = False
        mod._CAPS_RUN["c"] = c
        if kind == "urllib":
            mod.which = lambda n: None if "curl" in str(n) else real_which(n)
        else:
            ok = bool(real_which("curl"))
    try:
        yield ok
    finally:
        mod.which = real_which
        mod._CAPS_RUN.clear()


CHANNELS = [("curl_cffi", None), ("curl", "curl"), ("urllib", "urllib")]
seen, page = accept_server()
asrv = serve({"/%E9%A1%B5%E9%9D%A2": page, "/p": page})
url = asrv.url("/页面?q=中文")
try:
    for name, kind in CHANNELS:
        with channel(kind) as ok:
            if not ok:
                check.skip("address through %s" % name, "not available here")
                continue
            seen.clear()
            got = attempt(lambda: mod._fetch_once(url))
            check("a raw Chinese address through %s arrives as UTF-8 percent escapes" % name,
                  isinstance(got, dict) and got.get("status") == 200 and bool(seen)
                  and seen[0]["path"] == "/%E9%A1%B5%E9%9D%A2?q=%E4%B8%AD%E6%96%87",
                  (seen[0]["path"] if seen else str(got if not isinstance(got, dict) else (got.get("error") or got.get("status")))))
    # every channel sends the user's languages
    for lang, want, label in (("zh-CN", "zh-CN,zh;q=0.9,en;q=0.8", "the user's (zh-CN), then English"),
                              ("en", "en", "English for an English user, not nothing")):
        os.environ["READ_PAGE_LANG"] = lang
        for name, kind in CHANNELS:
            with channel(kind) as ok:
                if not ok:
                    continue
                seen.clear()
                got = attempt(lambda: mod._fetch_once(asrv.url("/p")))
                check("Accept-Language through %s is %s" % (name, label),
                      bool(seen) and seen[0]["lang"].startswith(want), seen[0]["lang"] if seen else str(got)[:80])
finally:
    os.environ.pop("READ_PAGE_LANG", None)
    asrv.close()

# a picture whose address has Chinese in it
pic = png(100, 80, (0, 0, 200))
img_log = []


def pic_route(h):
    img_log.append(h.path)
    h.send_response(200)
    h.send_header("Content-Type", "image/png")
    h.send_header("Content-Length", str(len(pic)))
    h.send_header("Connection", "close")
    h.end_headers()
    h.wfile.write(pic)
    h.close_connection = True


isrv = serve({
    "/doc": (200, {"Content-Type": "text/html; charset=utf-8"},
             html("文章的正文。" * 40 + '<img src="/图片/封面.png" alt="天安门">' + "更多的正文。" * 40, "带图片的文章").encode("utf-8")),
    "/%E5%9B%BE%E7%89%87/%E5%B0%81%E9%9D%A2.png": pic_route,
})
try:
    rc, out, man, folder = cli(isrv.url("/doc"), "--download")
    imgs = man.get("images") or []
    first = imgs[0] if imgs else {}
    check("a picture whose address has Chinese in it is downloaded",
          bool(first.get("file")) and os.path.isfile(os.path.join(folder, first["file"])) and bool(img_log),
          str(first.get("why") or first.get("file") or "no picture listed"))
    check("... and the server was asked for it in UTF-8", img_log[:1] == ["/%E5%9B%BE%E7%89%87/%E5%B0%81%E9%9D%A2.png"],
          str(img_log[:1]))
    del img_log[:]
    got = attempt(mod._fetch_image, (isrv.url("/图片/封面.png"), "天安门"), isrv.url("/doc"))
    check("a picture's raw Chinese address is fetched (it was `ordinal not in range(128)`)",
          isinstance(got, dict) and bool(got.get("data")) and img_log[:1] == ["/%E5%9B%BE%E7%89%87/%E5%B0%81%E9%9D%A2.png"],
          str(got.get("why") if isinstance(got, dict) else got)[:80])
    rc, out, man, folder = cli(isrv.url("/doc"), "--download", env={"READ_PAGE_SKIP": "defuddle,env"})
    first = (man.get("images") or [{}])[0]
    check("... with an extractor that keeps the page's own spelling of the address too",
          bool(first.get("file")), str(first.get("why") or first.get("file")))
finally:
    isrv.close()

# a redirect's Location is bytes, and a browser sends them on as they came: UTF-8 as its own escapes, any other
# byte above ASCII percent-encoded as it is - never read again in another encoding (`/café` in raw UTF-8 was
# asked for as `/caf%D0%B9`, a Cyrillic path, and the read ended not_found). What Chrome asked the same server for:
LOCATIONS = [(b"/caf\xe9", "/caf%E9"), (b"/caf\xc3\xa9", "/caf%C3%A9"), (b"/\xc3\xa9t\xc3\xa9", "/%C3%A9t%C3%A9"),
             (b"/\xd2\xb3\xc3\xe6", "/%D2%B3%C3%E6"), (b"/caf%C3%A9", "/caf%C3%A9"),
             (b"/\xe4\xb8\xad%E4%B8%AD", "/%E4%B8%AD%E4%B8%AD"), (b"/%\xe4\xb8\xad", "/%%E4%B8%AD"), (b"/\xff", "/%FF")]


def raw_redirect(location):
    def route(h):
        h.wfile.write(b"HTTP/1.1 302 Found\r\nLocation: " + location + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        h.close_connection = True
    return route


lroutes = {"/r%d" % i: raw_redirect(raw) for i, (raw, _want) in enumerate(LOCATIONS)}
lroutes.update({"/img-r%d" % i: raw_redirect(raw) for i, (raw, _want) in enumerate(LOCATIONS)})
lroutes["/to-annee"] = raw_redirect("/année".encode("utf-8"))
lroutes["/ann%C3%A9e"] = (200, {"Content-Type": "text/html; charset=utf-8"},
                          html("La bonne année, une page assez longue pour être lue. " * 12, "Année").encode("utf-8"))
lsrv = serve(lroutes)
try:
    for name, kind in CHANNELS:
        with channel(kind) as ok:
            if not ok:
                check.skip("a raw Location through %s" % name, "not available here")
                continue
            wrong = []
            for i, (raw, want) in enumerate(LOCATIONS):
                for _try in range(2):             # a connection the test server dropped is asked once more
                    del lsrv.log[:]
                    got = attempt(lambda: mod._fetch_once(lsrv.url("/r%d" % i)))
                    asked = [e["path"] for e in lsrv.log][1:2]
                    if asked:
                        break
                if asked != [want]:
                    wrong.append("%r -> %s" % (raw, asked[0] if asked else "nothing (%s)" % (
                        got.get("error") if isinstance(got, dict) else got)))
            check("a redirect's raw Location through %s goes where a browser goes (%d Locations)" % (name, len(LOCATIONS)),
                  not wrong, "; ".join(wrong[:3]))
    wrong = []
    for i, (raw, want) in enumerate(LOCATIONS):
        del lsrv.log[:]
        attempt(mod._fetch_image, (lsrv.url("/img-r%d" % i), ""), lsrv.url("/"))
        asked = [e["path"] for e in lsrv.log][1:2]
        if asked != [want]:
            wrong.append("%r -> %s" % (raw, asked[0] if asked else "nothing"))
    check("... and for a picture", not wrong, "; ".join(wrong[:3]))
    rc, out, man, folder = cli(lsrv.url("/to-annee"))
    check("CLI: a redirect to /année (raw UTF-8) lands on that page",
          man.get("status") == "ok" and "La bonne année" in content(folder),
          "%s %s" % (man.get("status"), (man.get("url") or {}).get("final")))
finally:
    lsrv.close()

# ---------------------------------------------------------------- 4. a server's Chinese file name


def download(disposition_line):
    body = png(30, 30)

    def route(h):
        h.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n" + disposition_line
                      + b"\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        h.close_connection = True
    return route


name = "图片说明"
dsrv = serve({
    "/dl1": download(("Content-Disposition: attachment; filename*=UTF-8''%s.png" % "%E5%9B%BE%E7%89%87%E8%AF%B4%E6%98%8E").encode()),
    "/dl2": download(b'Content-Disposition: attachment; filename="' + (name + ".png").encode("gbk") + b'"'),
    "/dl3": download(b'Content-Disposition: attachment; filename="' + (name + ".png").encode("utf-8") + b'"'),
    "/dl4": download(b"Content-Disposition: attachment; filename*=GBK''" + b"%CD%BC%C6%AC%CB%B5%C3%F7.png"),
    "/dl5": download(b'Content-Disposition: attachment; filename="' + "été.png".encode("utf-8") + b'"'),
    "/dl6": download(b'Content-Disposition: attachment; filename="' + "été.png".encode("latin-1") + b'"'),
})
try:
    for path, label in (("/dl1", "filename* in UTF-8"), ("/dl2", "raw GBK bytes in filename="),
                        ("/dl3", "raw UTF-8 bytes in filename="), ("/dl4", "filename* in GBK")):
        rc, out, man, folder = cli(dsrv.url(path))
        media = os.path.basename((man.get("files") or {}).get("media") or "")
        check("a server's Chinese file name is kept: %s" % label, media == name + ".png",
              "%r" % media)
        for chan, kind in CHANNELS:
            with channel(kind) as ok:
                if not ok:
                    continue
                got = attempt(lambda: mod._fetch_once(dsrv.url(path)))
                said = mod.disposition_name(got.get("disposition") or "") if isinstance(got, dict) else got
                check("... through %s too: %s" % (chan, label), said == name + ".png", repr(said))
    # a name that was right is not read again by a guess (été.pdf became йtй.pdf, raw UTF-8 on every channel)
    wrong = []
    for path, label in (("/dl5", "raw UTF-8"), ("/dl6", "raw Latin-1")):
        for chan, kind in CHANNELS:
            with channel(kind) as ok:
                if not ok:
                    continue
                got = attempt(lambda: mod._fetch_once(dsrv.url(path)))
                said = mod.disposition_name(got.get("disposition") or "") if isinstance(got, dict) else got
                if said != "été.png":
                    wrong.append("%s %s: %r" % (label, chan, said))
    check("a Latin file name (été.png, raw UTF-8 or raw Latin-1) is kept on every channel", not wrong, "; ".join(wrong[:3]))
finally:
    dsrv.close()
check("disposition_name reads filename* with its own charset",
      attempt(lambda: mod.disposition_name("attachment; filename*=GBK''%CD%BC%C6%AC.png")) == "图片.png", "")

# ---------------------------------------------------------------- 5. the MCP server's standard input


def mcp_session(messages, env_extra=None, timeout=180, first=b""):
    e = dict(os.environ)
    e.update({"PYTHONUTF8": "0", "PYTHONIOENCODING": "gbk", "READ_PAGE_TEST_PUBLIC_HOST": PUBLIC,
              "READ_PAGE_CACHE": os.path.join(ROOT, "mcp-cache"),
              "READ_PAGE_SKIP": ",".join(x for x in (e.get("READ_PAGE_SKIP", "").split(",") + ["env"]) if x)})
    e.update(env_extra or {})
    data = first + b"".join(json.dumps(m, ensure_ascii=False).encode("utf-8") + b"\n" for m in messages)
    p = subprocess.run([sys.executable, MCP], input=data, capture_output=True, timeout=timeout, env=e)
    out = {}
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        out[m.get("id")] = m
    return out, p.stderr.decode("utf-8", "replace")


seen, page = accept_server()
msrv = serve({"/%E9%A1%B5%E9%9D%A2": page})
mcp_cache = os.path.join(ROOT, named("目录", "dir"), named("缓存", "cache"))             # a profile's cache named in Chinese: the folders it hands out are
try:
    out, err = mcp_session([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "read_url", "arguments": {"url": msrv.url("/页面")}}},
    ], {"READ_PAGE_CACHE": mcp_cache})
    res = (out.get(2) or {}).get("result") or {}
    said = "".join(b.get("text", "") for b in res.get("content") or [])
    check("MCP: a Chinese URL on stdin reaches the reader as it is (the code page is not the locale's)",
          bool(seen) and seen[0]["path"] == "/%E9%A1%B5%E9%9D%A2" and "页面的正文" in said,
          (seen[0]["path"] if seen else (said[:80] or err[-160:])))
    folder = (res.get("structuredContent") or {}).get("dir") or ""
    out, err = mcp_session([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "read", "arguments": {"dir": folder}}},
    ], {"READ_PAGE_CACHE": mcp_cache})
    said = "".join(b.get("text", "") for b in ((out.get(2) or {}).get("result") or {}).get("content") or [])
    check("MCP: the Chinese folder the last answer named, sent back on stdin, is the folder that is read",
          named("缓存", "cache") in folder and "页面的正文" in said, (said[:100] or err[-160:] or folder))
    # a UTF-8 BOM before the first line (a file saved with one, piped in): the first message was a parse error
    out, err = mcp_session([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
    ], first=b"\xef\xbb\xbf")
    check("MCP: a UTF-8 BOM before the first line is not part of it", "result" in (out.get(1) or {}),
          str(out.get(1) or err[-160:])[:120])
finally:
    msrv.close()

# ---------------------------------------------------------------- 6. OCR languages
packs = ["eng", "osd", "chi_sim", "chi_tra", "jpn", "kor", "rus"]
plan = getattr(mod, "_ocr_plan", None)


def plan_of(have, text, lang=""):
    os.environ["READ_PAGE_LANG"] = lang or "en"          # "an English user": the machine's own language must not leak in
    try:
        return plan(have, text)
    finally:
        os.environ.pop("READ_PAGE_LANG", None)


if plan is None:
    check("OCR: the language of the text and of the user is chosen (_ocr_plan)", False, "readpage has no _ocr_plan")
else:
    for label, text, lang, want_use, want_missing in (
            ("simplified Chinese text", ZH_S * 3, "", ["eng", "chi_sim"], []),
            ("traditional Chinese text", ZH_T * 3, "", ["eng", "chi_tra"], []),
            ("Japanese text", JA * 3, "", ["eng", "jpn"], []),
            ("Korean text", KO * 3, "", ["eng", "kor"], []),
            ("English text for an English user", "A plain English page about reading. " * 10, "", ["eng"], []),
            ("English text for a Chinese user (zh-CN)", "A plain English page about reading. " * 10, "zh-CN", ["eng", "chi_sim"], []),
            ("no text for a Taiwanese user (zh-TW)", "", "zh-TW", ["eng", "chi_tra"], []),
            ("no text for a Japanese user", "", "ja-JP", ["eng", "jpn"], []),
            ("no text for a Russian user", "", "ru-RU", ["eng", "rus"], [])):
        got = attempt(plan_of, packs, text, lang)
        check("OCR packs: %s" % label, got == (want_use, want_missing), str(got))
    got = attempt(plan_of, ["eng", "osd"], ZH_S * 3, "")
    check("OCR packs: a Chinese text with no Chinese pack uses what there is and names the pack that is missing",
          got == (["eng"], ["chi_sim"]), str(got))
    # five の on a Chinese shop's page made it Japanese; a Japanese headline of kanji alone was Chinese
    shop = ZH_S * 3 + "本店の新品、我の店、美の时光、爱の礼物、家の味道"
    heads = "経済産業省発表　東京駅前再開発計画　県立図書館新設　大阪市営地下鉄延伸　国際関係研究所報告"
    got = (attempt(plan_of, packs, shop, ""), attempt(plan_of, packs, heads, ""))
    check("OCR packs: a few kana in a Chinese text do not make it Japanese; kanji in Japan's own forms do",
          got == ((["eng", "chi_sim"], []), (["eng", "jpn"], [])), str(got))
    got = attempt(plan_of, ["eng", "osd"], "", "zh-CN")
    check("OCR packs: a Chinese user's missing pack is a maybe, not a gap of this page",
          isinstance(got, tuple) and got[0] == ["eng"] and got[1] == [], str(got))
    os.environ["READ_PAGE_OCR_LANGS"] = "eng"
    try:
        got = attempt(plan_of, packs, "", "zh-CN")
    finally:
        os.environ.pop("READ_PAGE_OCR_LANGS", None)
    check("OCR packs: READ_PAGE_OCR_LANGS set by the user is the user's own word (no pack added for the locale)",
          got == (["eng"], []), str(got))

mod2 = module()
mod2.which = lambda name: "tesseract" if name == "tesseract" else None
mod2.tesseract_langs = lambda exe=None: ["eng", "chi_sim"]
mod2._tesserocr = lambda: None
asked = []
mod2.run_tool = lambda cmd, timeout=120: (asked.append(cmd), (0, "识别的文字".encode("utf-8"), b""))[1]
os.environ["READ_PAGE_LANG"] = "zh-CN"
try:
    text, info = attempt(lambda: mod2.ocr_pages([os.path.join(ROOT, "p1.png")]))
except Exception as e:                                       # noqa: BLE001
    text, info = "", {"error": str(e)}
finally:
    os.environ.pop("READ_PAGE_LANG", None)
check("OCR of a scan for a Chinese user asks tesseract for eng+chi_sim",
      bool(asked) and "eng+chi_sim" in asked[0], str(asked[:1]))
mod2.tesseract_langs = lambda exe=None: ["eng"]
os.environ["READ_PAGE_LANG"] = "zh-CN"
try:
    text, info = mod2.ocr_pages([os.path.join(ROOT, "p1.png")])
except Exception as e:                                       # noqa: BLE001
    text, info = "", {"error": str(e)}
finally:
    os.environ.pop("READ_PAGE_LANG", None)
check("OCR of a scan for a Chinese user without the pack names it", info.get("maybe") == ["chi_sim"], str(info.get("maybe")))
c0 = mod2.caps()
m_, im_ = mod2.gaps(c0, {"ocr_missing": ["chi_sim"], "no_text_layer": True})
check("`improve` names the missing pack", any(i.get("what") == "ocr-language" and "chi_sim" in (i.get("fix") or "")
                                              for i in im_), str([i.get("fix") for i in im_ if i.get("what") == "ocr-language"]))

# tesserocr: a page rendered at 150 dpi keeps its resolution. Pillow's picture reaches tesseract re-saved without
# it (70 dpi assumed), so a path tesserocr can open goes as the file, and a picture as a picture with its dpi
calls = []


class FakeTess(object):
    def __init__(self, path=None, lang=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def SetImageFile(self, p):
        calls.append(("file", p))

    def SetImage(self, img):
        calls.append(("image",))

    def SetSourceResolution(self, n):
        calls.append(("dpi", n))

    def Recognize(self, ms=0):
        pass

    def GetUTF8Text(self):
        return "page text"


mod3 = module()
tess_home = tempfile.mkdtemp(prefix="rp-tess-", dir=ROOT)
mod3._tesserocr = lambda: (types.SimpleNamespace(PyTessBaseAPI=FakeTess), tess_home, ["eng"])
seen_ocr = {}
os.environ["READ_PAGE_LANG"] = "en"
try:
    for label, folder, fname in (("ascii", next((d for d in (ROOT, tempfile.gettempdir()) if d.isascii()), ""),
                                  "rp-scan-%d.png" % os.getpid()),
                                 ("wide", ROOT if UTF8_PATHS else "", "扫描页.png")):
        if not folder:
            continue
        page_png = os.path.join(folder, fname)
        with open(page_png, "wb") as f:
            f.write(png(40, 40))
        del calls[:]
        attempt(mod3.ocr_pages, [page_png])
        seen_ocr[label] = (page_png, list(calls))
        os.unlink(page_png)
finally:
    os.environ.pop("READ_PAGE_LANG", None)
if "ascii" in seen_ocr:
    check("tesserocr reads a page it can open by path from the file (its own resolution)",
          seen_ocr["ascii"][1][:1] == [("file", seen_ocr["ascii"][0])], str(seen_ocr["ascii"][1]))
if "wide" not in seen_ocr or importlib.util.find_spec("PIL") is None:
    check.skip("tesserocr: a page under a path outside ASCII keeps its 150 dpi", "no such path or no Pillow here")
else:
    check("tesserocr: a page under a path outside ASCII goes as a picture and keeps its 150 dpi",
          seen_ocr["wide"][1][:2] == [("image",), ("dpi", 150)], str(seen_ocr["wide"][1]))

# ---------------------------------------------------------------- 7. tools with narrow arguments
# a Python program the skill runs (yt-dlp, markitdown) writes its output in the ANSI code page on Windows, a
# locale's on POSIX, and the output is read as UTF-8: a Chinese title came out as other characters
tool = os.path.join(ROOT, "tool_%d.py" % os.getpid())
with open(tool, "w", encoding="utf-8") as f:
    f.write("import sys\nsys.stdout.write(sys.stdout.encoding.lower().replace('_', '-') + ' ' + '中文标题')\n")
saved_env = {k: os.environ.pop(k) for k in ("PYTHONUTF8", "PYTHONIOENCODING") if k in os.environ}
try:
    rc_, so_, se_ = mod.run([sys.executable, tool], timeout=60)
finally:
    os.environ.update(saved_env)
check("a Python program the skill runs writes UTF-8, which its output is read as",
      so_.decode("utf-8", "replace") == "utf-8 中文标题", so_.decode("utf-8", "replace")[:60] or se_[-120:].decode("utf-8", "replace"))

narrow = getattr(mod, "narrow_paths", None)
if os.name != "nt":
    check.skip("narrow paths (Windows only: elsewhere a path is bytes)", "this is not Windows")
    check("narrow paths: off Windows a path stays as it is",
          narrow is not None and narrow(["/tmp/a/中文.pdf"], ["/tmp/a/出.txt"])[:2] == (["/tmp/a/中文.pdf"], ["/tmp/a/出.txt"]),
          "readpage has no narrow_paths")
elif narrow is None:
    check("narrow paths: a Chinese path is given to pdftotext as an ASCII one", False, "readpage has no narrow_paths")
else:
    cn = os.path.join(ROOT, "許功蓋", "文档")
    os.makedirs(cn, exist_ok=True)
    pdf = os.path.join(cn, "文件.pdf")
    with open(pdf, "wb") as f:
        f.write(b"%PDF-1.4\n")
    out_txt = os.path.join(cn, "_pdf.txt")
    ins, outs, done = narrow([pdf], [out_txt])
    ok = ins[0].isascii() and outs[0].isascii() and os.path.isfile(ins[0])
    check("narrow paths: a file under a Chinese (and a CP950 trail-0x5C) folder is given as an ASCII path",
          ok, "%s | %s" % (ins[0], outs[0]))
    with open(outs[0], "wb") as f:
        f.write("文字".encode("utf-8"))
    done()
    check("narrow paths: what the tool wrote comes back to the real place", os.path.isfile(out_txt)
          and open(out_txt, "rb").read().decode("utf-8") == "文字", "")
    ascii_root = mod.ascii_stage_root()
    check("narrow paths: an ASCII folder for them exists (the cache's, its short name, or a public one)",
          bool(ascii_root) and ascii_root.isascii() and os.path.isdir(ascii_root), ascii_root)
    plain = os.path.join(ascii_root, "plain-%d.pdf" % os.getpid())
    with open(plain, "wb") as f:
        f.write(b"%PDF-1.4\n")
    ins, outs, done = narrow([plain], [plain + ".txt"])
    check("narrow paths: an ASCII path stays as it is", ins == [plain] and outs == [plain + ".txt"], str(ins))
    done()
    os.unlink(plain)
    # a profile named in Chinese on a volume with no 8.3 names: a document is never copied into a folder of the
    # machine's other users (C:\Users\Public, C:\ProgramData), only into one of this user's own, or nowhere
    real_cache, real_short, real_home = mod.cache_root, mod.ownenv.ascii_path, mod.ownenv.home
    no_short = os.path.join(ROOT, "許功蓋", "cache")
    os.makedirs(no_short, exist_ok=True)
    try:
        mod.cache_root = lambda: no_short
        mod.ownenv.ascii_path = lambda p: p
        mod.ownenv.home = lambda: os.path.join(ROOT, "許功蓋", "home")
        shared_root = mod.ascii_stage_root()
        ins, outs, done = narrow([pdf], [out_txt])
        done()
        # an ASCII folder for the stand-in home (this suite's own folder is under a Chinese TEMP in the
        # Chinese-Windows job): a test folder, removed below
        own_home = next((os.path.join(b, "rp-ascii-home-%d" % os.getpid()) for b in
                         (ROOT, tempfile.gettempdir(), os.environ.get("RUNNER_TEMP"), os.environ.get("PUBLIC"))
                         if b and b.isascii() and os.path.isdir(b)), "")
        mod.ownenv.home = lambda: own_home
        home_root = mod.ascii_stage_root() if own_home else ""
    finally:
        mod.cache_root, mod.ownenv.ascii_path, mod.ownenv.home = real_cache, real_short, real_home
        if own_home:
            shutil.rmtree(own_home, ignore_errors=True)
    shared = [x for x in (os.environ.get("PUBLIC"), os.environ.get("ProgramData")) if x]
    check("narrow paths: with no ASCII folder of the user's own, nothing is copied into a folder other users read "
          "(the program gets the path as it is)",
          shared_root == "" and ins == [pdf] and not any(os.path.normcase(r) in os.path.normcase(ins[0]) for r in shared),
          "%r %r" % (shared_root, ins))
    if not own_home:
        check.skip("... and an environment folder with an ASCII path (READ_PAGE_HOME) is one of the user's own",
                   "no ASCII folder on this machine to stand in for one")
    elif sys.version_info < (3, 13):
        # READ_PAGE_HOME may be a folder every user reads (C:\read-page); a stage folder can be made this
        # user's alone only by Python 3.13's os.mkdir(..., 0o700)
        check("... and an environment folder with an ASCII path (READ_PAGE_HOME) is not used before Python 3.13 "
              "(its stage folders could not be the user's alone)", home_root == "", home_root)
    else:
        check("... and an environment folder with an ASCII path (READ_PAGE_HOME) is used, each stage the user's alone",
              bool(home_root) and os.path.normcase(home_root).startswith(os.path.normcase(own_home)), home_root)
    # a read-only document (a CD's, a mail's, some archives'): copied, never linked - a link shared its read-only
    # attribute, the stage could not be removed, and the document stayed in the cache, one link more each read
    ro = os.path.join(cn, "只读.pdf")
    with open(ro, "wb") as f:
        f.write(b"%PDF-1.4\n% read-only\n")
    os.chmod(ro, stat.S_IREAD)
    try:
        ins, outs, done = narrow([ro], [])
        links_during = os.stat(ro).st_nlink
        done()
        stage_gone = ins[0] != ro and not os.path.exists(os.path.dirname(ins[0]))
        links_after = os.stat(ro).st_nlink
    finally:
        os.chmod(ro, stat.S_IWRITE | stat.S_IREAD)
    check("narrow paths: a read-only document is copied, not linked, and its stage folder goes",
          links_during == 1 and links_after == 1 and stage_gone, "links %s/%s, stage %s" % (links_during, links_after, ins[0]))
    # a stage a killed read left behind is gone an hour later
    stale = os.path.join(mod.ascii_stage_root(), "0badc0ffee00")
    os.makedirs(stale, exist_ok=True)
    with open(os.path.join(stale, "in0.pdf"), "wb") as f:
        f.write(b"%PDF-1.4\n")
    hour_ago = time.time() - 2 * 3600
    os.utime(os.path.join(stale, "in0.pdf"), (hour_ago, hour_ago))
    os.utime(stale, (hour_ago, hour_ago))
    ins, outs, done = narrow([pdf], [out_txt])
    done()
    check("narrow paths: a stage folder a killed read left is removed (it was never pruned)", not os.path.exists(stale), stale)

# ---------------------------------------------------------------- 8. what is sent in the user's name
sub = getattr(intl, "sub_langs", None)
if sub is None:
    check("subtitle tracks follow the user's language", False, "no intl.sub_langs")
else:
    for lang, want in (("", ["en"]), ("zh-CN", ["zh-Hans", "zh-CN", "zh", "en"]),
                       ("zh-TW", ["zh-Hant", "zh-TW", "zh-HK", "zh", "en"]), ("ja-JP", ["ja", "en"]), ("ru-RU", ["ru", "en"])):
        os.environ["READ_PAGE_LANG"] = lang or "en"
        got = sub()
        os.environ.pop("READ_PAGE_LANG", None)
        check("subtitle tracks for %s" % (lang or "an English user"), got == want, str(got))
    os.environ["READ_PAGE_SUB_LANGS"] = "fr,de"
    os.environ["READ_PAGE_LANG"] = "zh-CN"
    check("READ_PAGE_SUB_LANGS, when set, is the user's own word", sub() == ["fr", "de"], str(sub()))
    os.environ.pop("READ_PAGE_SUB_LANGS")
    os.environ.pop("READ_PAGE_LANG")
    seen_cmd = {}
    real_run = mod.run
    mod.run = lambda cmd, timeout=120, **kw: (seen_cmd.update(cmd=cmd), (1, b"", b""))[1]
    c1 = mod.caps()
    c1["cli"]["yt-dlp"] = "yt-dlp"
    os.environ["READ_PAGE_LANG"] = "zh-CN"
    try:
        mod.video_text("https://example.org/v", c1, tempfile.mkdtemp(prefix="rp-vid-", dir=ROOT))
    finally:
        mod.run = real_run
        os.environ.pop("READ_PAGE_LANG", None)
    cmd = seen_cmd.get("cmd") or []
    check("yt-dlp is asked for the user's subtitle tracks first, then the track the video speaks in",
          "--sub-langs" in cmd and cmd[cmd.index("--sub-langs") + 1] == "zh-Hans,zh-CN,zh,en,.*-orig",
          str(cmd[cmd.index("--sub-langs"):][:2] if "--sub-langs" in cmd else cmd))
vid = tempfile.mkdtemp(prefix="rp-vid2-", dir=ROOT)
calls = []


def fake_yt(cmd, timeout=120, **kw):
    calls.append(cmd)
    lang = cmd[cmd.index("--sub-langs") + 1]
    if len(calls) == 1:                                       # the first ask: no track of the user's, the info says Japanese
        with open(os.path.join(vid, "video.info.json"), "w", encoding="utf-8") as f:
            json.dump({"title": "動画", "language": "ja", "subtitles": {"ja": [{}]}, "automatic_captions": {"en": [{}]}}, f)
        return 0, b"", b""
    with open(os.path.join(vid, "video.%s.vtt" % lang), "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nこんにちは世界\n")
    return 0, b"", b""


real_run = mod.run
mod.run = fake_yt
c2 = mod.caps()
c2["cli"]["yt-dlp"] = "yt-dlp"
os.environ["READ_PAGE_LANG"] = "zh-CN"
try:
    got = attempt(mod.video_text, "https://example.org/v", c2, vid)
finally:
    mod.run = real_run
    os.environ.pop("READ_PAGE_LANG", None)
check("a video with none of the user's subtitle tracks is asked for its own language once more",
      len(calls) == 2 and calls[1][calls[1].index("--sub-langs") + 1] == "ja" and isinstance(got, tuple) and "こんにちは" in got[0],
      str(got)[:80] if not isinstance(got, tuple) else got[2][:80])

# YouTube offers its machine translation of a video's captions into every language, and yt-dlp lists it among the
# automatic captions: a Chinese or Russian reader of an English talk was handed YouTube's translation
TIMEDTEXT = "https://www.youtube.com/api/timedtext?v=x&lang=en&fmt=vtt"


def tracks_video(info, written):
    """video_text on a stand-in yt-dlp that writes `info` and the vtt files `written` ({lang: words})."""
    folder = tempfile.mkdtemp(prefix="rp-vid3-", dir=ROOT)

    def yt(cmd, timeout=120, **kw):
        with open(os.path.join(folder, "video.info.json"), "w", encoding="utf-8") as f:
            json.dump(info, f)
        for lang, words in written.items():
            with open(os.path.join(folder, "video.%s.vtt" % lang), "w", encoding="utf-8") as f:
                f.write("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n%s\n" % words)
        return 0, b"", b""
    real = mod.run
    mod.run = yt
    os.environ["READ_PAGE_LANG"] = "zh-CN"
    try:
        return attempt(mod.video_text, "https://example.org/v", c2, folder)
    finally:
        mod.run = real
        os.environ.pop("READ_PAGE_LANG", None)


auto = {"en": [{"url": TIMEDTEXT}], "en-orig": [{"url": TIMEDTEXT}], "zh-Hans": [{"url": TIMEDTEXT + "&tlang=zh-Hans"}]}
got = tracks_video({"title": "A talk", "language": "en", "subtitles": {}, "automatic_captions": auto},
                   {"zh-Hans": "机器翻译的字幕", "en": "the words as spoken", "en-orig": "the words as spoken"})
check("an English talk is read in its own words, not YouTube's Chinese translation, and the answer says which track",
      isinstance(got, tuple) and "the words as spoken" in got[0] and got[2] == "subtitles en, automatic", str(got)[:120])
got = tracks_video({"title": "A talk", "language": "en", "subtitles": {"zh-CN": [{}], "en": [{}]},
                    "automatic_captions": auto}, {"zh-Hans": "机器翻译的字幕", "zh-CN": "人工字幕", "en": "human words"})
check("... a human track in the user's language comes first", isinstance(got, tuple) and "人工字幕" in got[0]
      and got[2] == "subtitles zh-CN", str(got)[:120])
got = tracks_video({"title": "A talk", "language": "en", "subtitles": {},
                    "automatic_captions": {"zh-Hans": [{"url": TIMEDTEXT + "&tlang=zh-Hans"}]}}, {"zh-Hans": "机器翻译的字幕"})
check("... and a machine translation, when there is nothing else, is read and named so",
      isinstance(got, tuple) and "机器翻译" in got[0] and got[2] == "subtitles zh-Hans, machine-translated from en",
      str(got)[:120])
loc = getattr(intl, "browser_locale", None)
for lang, want in (("", "en-US"), ("zh-CN", "zh-CN"), ("zh-TW", "zh-TW"), ("zh-HK", "zh-HK"), ("ja-JP", "ja-JP"), ("ru", "ru")):
    os.environ["READ_PAGE_LANG"] = lang or "en"
    got = attempt(loc) if loc else "no intl.browser_locale"
    os.environ.pop("READ_PAGE_LANG", None)
    check("the browser's locale for %s" % (lang or "an English user"), got == want, str(got))

# a POSIX locale names its codeset: `zh_TW.UTF-8` (Linux, a Mac's terminal) was read as zh - Simplified Chinese,
# the zh-CN browser, gb18030 ties and chi_sim - because the codeset was split off after the region
wrong = [(raw, attempt(intl._tag, raw)) for raw, want in (("zh_TW.UTF-8", "zh-TW"), ("zh_HK.Big5-HKSCS", "zh-HK"),
                                                         ("pt_BR.UTF-8", "pt-BR"), ("sr_RS@latin", "sr-RS"),
                                                         ("zh-Hant-TW", "zh-Hant-TW"), ("ja_JP.eucJP", "ja-JP"))
         if attempt(intl._tag, raw) != want]
check("a locale's codeset and modifier are not its region (zh_TW.UTF-8 is zh-TW)", not wrong, str(wrong))


def through_os(langs):
    """intl's view of a machine whose own list is `langs` (READ_PAGE_LANG unset): locale, header, tracks."""
    saved = list(intl._OS_LANGS)
    intl._OS_LANGS[:] = [list(langs)]
    try:
        return intl.browser_locale(), intl.accept_language(), intl.sub_langs()
    finally:
        intl._OS_LANGS[:] = saved


got = attempt(through_os, ["zh_TW.UTF-8"])
check("... so LANG=zh_TW.UTF-8 is a Taiwanese reader: zh-TW, Traditional tracks first",
      isinstance(got, tuple) and got[0] == "zh-TW" and got[1].startswith("zh-TW,zh;q=0.9") and got[2][0] == "zh-Hant",
      str(got))
# Windows: the user locale is the regional format (an English UI with German formats is de-DE): the display
# languages decide, the locale only when there are none
real_sl, real_ol = mod.ownenv.system_language, mod.ownenv._os_languages
try:
    mod.ownenv.system_language = lambda env=None: "de-DE"
    mod.ownenv._os_languages = lambda: ["en-US"]
    win = attempt(mod.ownenv.system_languages, os.environ, True)
    mod.ownenv._os_languages = lambda: []
    win_none = attempt(mod.ownenv.system_languages, os.environ, True)
finally:
    mod.ownenv.system_language, mod.ownenv._os_languages = real_sl, real_ol
got = attempt(through_os, win if isinstance(win, list) else [])
check("Windows with German formats and English as its display language reads as English (it sent de-DE first)",
      win == ["en-US"] and isinstance(got, tuple) and got == ("en-US", "", ["en"]), "%s %s" % (win, got))
check("... and the user locale counts when the display languages cannot be read",
      isinstance(win_none, list) and win_none[:1] == ["de-DE"], str(win_none))

# ---------------------------------------------------------------- 9. a home folder, a cache and an answer in Chinese
home = os.path.join(ROOT, named("用户", "users"), named("张三", "zhang"))
cache = os.path.join(home, named("缓存", "cache"), "read-page")
tmp = os.path.join(home, named("临时", "tmp"))
for d in (home, cache, tmp):
    os.makedirs(d, exist_ok=True)
hsrv = serve({"/gbk": (200, HTML_H, html(ZH_S).encode("gbk")),
              "/doc": (200, {"Content-Type": "text/html; charset=utf-8"},
                       html("文章的正文。" * 40 + '<img src="/img.png" alt="图">' + "更多的正文。" * 40, "文章").encode("utf-8")),
              "/img.png": (200, {"Content-Type": "image/png"}, png(100, 80))})
try:
    env = {"HOME": home, "USERPROFILE": home, "READ_PAGE_HOME": os.path.join(home, ".read-page"),
           "READ_PAGE_CACHE": cache, "TEMP": tmp, "TMP": tmp, "TMPDIR": tmp, "LOCALAPPDATA": os.path.join(home, "AppData"),
           "PYTHONUTF8": "0", "PYTHONIOENCODING": "gbk"}
    answers = os.path.join(home, named("答案", "answers"))
    os.makedirs(answers, exist_ok=True)
    rc, out, man, folder = cli(hsrv.url("/gbk"), env=env, root=answers)
    check("a Chinese home, cache and answer folder: a GBK page is read, the files are there",
          man.get("status") == "ok" and "中华人民共和国" in content(folder) and os.path.isfile(os.path.join(folder, "page.md")),
          "%s rc=%s %s" % (man.get("status"), rc, out[-120:].decode("utf-8", "replace")))
    rc, out, man, folder = cli(hsrv.url("/doc"), "--download", env=env, root=answers)
    got = [e.get("file") for e in man.get("images") or []]
    check("... and a picture lands in it", bool(got) and all(os.path.isfile(os.path.join(folder, g)) for g in got if g),
          str(got))
    check("... and the answer names that folder in Chinese", "files: " in out.decode("utf-8", "replace")
          and named("张三", "zhang") in out.decode("utf-8", "replace"), out.decode("utf-8", "replace")[:160])
finally:
    hsrv.close()

shutil.rmtree(ROOT, ignore_errors=True)
sys.exit(check.done())
