"""Text and addresses outside ASCII, and the user's own language. Standard library only (Python 3.8+).

Four things a reader needs on a machine whose people write Chinese, Japanese, Korean or Russian,
none of which a Latin-1 habit gets right:

- `decode_page`: the text of a body that says what its encoding is, says it wrongly, or says
  nothing - and whether the reading is a guess. GBK and Big5 are told from each other, and from
  Cyrillic and Shift_JIS, by what the decoded text is made of (common characters of the script),
  not by the first codec that does not raise. `charset_normalizer` is a second opinion, when
  it is installed; the core does not need it.
- `iri_to_uri`: a raw `https://例子.测试/页面?q=中文` as the bytes a server wants (host in
  punycode, the rest percent-encoded as UTF-8). Every client of the skill that is handed an
  address goes through it: urllib raises on a non-ASCII character, and a curl built for the ANSI
  code page (Git's) sends the path in GBK.
- the user's languages (`user_langs`): READ_PAGE_LANG, else the operating system's, then English;
  from them the `Accept-Language` every channel sends, the browser's locale, the subtitle tracks
  asked of yt-dlp, and the OCR language packs worth asking for.
- `file_stem`: a name a server chose (Content-Disposition), kept in its own script.
"""
import codecs
import os
import re
import urllib.parse

# ---------------------------------------------------------------- addresses
_RAW = re.compile(r"[^\x21-\x7e]")
_ABS = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*://)([^/?#]*)(.*)$", re.S)
_DOTS = re.compile("[.。．｡]")


def _escape(m):
    return urllib.parse.quote(m.group(0), safe="", errors="replace")


def _host_ascii(host):
    """A host name in punycode (IDNA 2003 first, as the standard library does; a label it refuses -
    too long, empty - is encoded on its own)."""
    if host.isascii():
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    out = []
    for label in _DOTS.split(host):
        if label.isascii():
            out.append(label)
            continue
        try:
            out.append("xn--" + label.lower().encode("punycode").decode("ascii"))
        except UnicodeError:
            return host
    return ".".join(out)


def iri_to_uri(url):
    """`url` as a server can be asked for it: every character outside printable ASCII becomes its
    UTF-8 percent escapes (a space too), the host goes to punycode. What is already escaped, and
    every ASCII character, stays exactly as it was; an ASCII address comes back as it is."""
    url = url or ""
    if not _RAW.search(url):
        return url
    m = _ABS.match(url)
    if not m:
        return _RAW.sub(_escape, url)
    scheme, netloc, rest = m.groups()
    if not netloc.isascii():
        userinfo, at, hostport = netloc.rpartition("@")
        host, port = hostport, ""
        if not hostport.startswith("["):
            h, colon, p = hostport.rpartition(":")
            if colon and (p.isdigit() or not p):
                host, port = h, ":" + p
        netloc = _RAW.sub(_escape, userinfo) + at + _host_ascii(host) + port
    return scheme + netloc + _RAW.sub(_escape, rest)


# ---------------------------------------------------------------- the user's languages
_OS_LANGS = []


def _os_langs():
    """The languages the user set this machine up with, the one it is set to first ("zh-CN", "ru_RU.UTF-8"), then
    the others of their list: ownenv.system_languages (Windows' user locale and language list, the environment's,
    a Mac's own settings), looked up once."""
    if not _OS_LANGS:
        import ownenv
        _OS_LANGS.append(ownenv.system_languages())
    return _OS_LANGS[0]


def _tag(raw):
    """One language tag in the form `ll` or `ll-RR` (or `zh-Hans`, `zh-Hant`), "" for what is no language."""
    parts = [p for p in re.split(r"[-_]", (raw or "").strip()) if p]
    if not parts or not parts[0].isalpha() or not 2 <= len(parts[0]) <= 3:
        return ""
    lang = parts[0].lower()
    rest = []
    for p in parts[1:]:
        if len(p) == 4 and p.isalpha():
            rest.append(p.title())               # a script: Hans, Hant
        elif (len(p) == 2 and p.isalpha()) or (len(p) == 3 and p.isdigit()):
            rest.append(p.upper())               # a region
    return "-".join([lang] + rest[:2])


def explicit_langs():
    """READ_PAGE_LANG ("zh-CN", or "zh-TW,en"): the user's own word, [] when unset."""
    return [t for t in (_tag(x) for x in (os.environ.get("READ_PAGE_LANG") or "").split(",")) if t]


def user_langs():
    """The languages the user reads, the first one their own, English last: READ_PAGE_LANG, else the
    operating system's language, then English."""
    langs = explicit_langs()
    if not langs:
        for t in (_tag(x) for x in _os_langs()):
            if t and t not in langs:
                langs.append(t)
    if not any(t.split("-")[0] == "en" for t in langs):
        langs.append("en")
    return langs


def own_langs():
    """The user's languages that are not English, in their order."""
    return [t for t in user_langs() if t.split("-")[0] != "en"]


def own_lang():
    """The first of the user's languages that is not English ("zh-CN"), or "" for an English reader."""
    return (own_langs() or [""])[0]


def chinese_script(tag):
    """"Hant" for a Chinese tag of Taiwan, Hong Kong or Macau (or written Hant), "Hans" for any other."""
    t = (tag or "").lower()
    if t.split("-")[0] not in ("zh", "yue", "cmn"):
        return ""
    return "Hant" if re.search(r"(^|-)(hant|tw|hk|mo)(-|$)", t) else "Hans"


def accept_language(default=""):
    """The Accept-Language value to send: the user's languages, then English ("zh-CN,zh;q=0.9,en;q=0.8").
    For an English or unknown user it is `default`: the empty string leaves a channel that sends
    a language of its own (a browser's impersonation) as it is."""
    langs = user_langs()
    if own_lang() == "" and not explicit_langs():
        return default
    seq = []
    for t in langs:
        if t.split("-")[0] == "en" and any(s.split("-")[0] == "en" for s in seq):
            continue                                  # en-GB after en-US says nothing more
        for x in ("-".join(p for p in t.split("-") if not (len(p) == 4 and p.isalpha() and len(t.split("-")) > 2)),
                  t.split("-")[0]):
            if x not in seq:
                seq.append(x)
    out = []
    for i, t in enumerate(seq[:6]):
        out.append(t if i == 0 else "%s;q=%.1f" % (t, max(0.1, 1.0 - 0.1 * i)))
    return ",".join(out)


def browser_locale():
    """The locale a browser page is opened in: the user's first language (Accept-Language and navigator.language
    follow it), "en-US" for an English or unknown user."""
    t = user_langs()[0]
    if t.split("-")[0] == "en":
        return t if (explicit_langs() and "-" in t) else "en-US"
    if t.split("-")[0] in ("zh", "yue", "cmn"):
        region = next((x for x in t.split("-")[1:] if x in ("TW", "HK", "MO", "CN", "SG")), "")
        return "zh-" + (region or ("TW" if chinese_script(t) == "Hant" else "CN"))
    if t == "en":
        return "en-US"
    return "-".join(x for x in t.split("-") if not (len(x) == 4 and x.isalpha()))


_SUB_TRACKS = {"Hans": ("zh-Hans", "zh-CN", "zh"), "Hant": ("zh-Hant", "zh-TW", "zh-HK", "zh")}


def sub_langs():
    """The subtitle tracks asked of yt-dlp, as a list: READ_PAGE_SUB_LANGS when it is set, else the user's
    languages - Chinese as YouTube names its tracks - then English."""
    env = (os.environ.get("READ_PAGE_SUB_LANGS") or "").strip()
    if env:
        return [x.strip() for x in env.split(",") if x.strip()]
    out = []
    for t in user_langs():
        script = chinese_script(t)
        for x in (_SUB_TRACKS[script] if script else (t.split("-")[0],)):
            if x not in out:
                out.append(x)
    return out


# ---------------------------------------------------------------- characters of a script
# The common characters of each script, written out: what a decoder reads correctly turns up in
# them all the time (about two thirds of running text), what it reads wrongly almost never does
# (800 of the 21 000 ideographs of the main block). Enough to tell GBK from Big5, and either from
# Shift_JIS and EUC-KR, on a short text - which `charset_normalizer` does not (10 to 20 characters
# of GBK came back as cp949, cp932 or cp1006).
_SIMPLIFIED = (
    "的一是不了人我在有他这为之大来以个中上们到说国和地也子时道出而要于就下得可你年生自会那后能对着事其里所去行过家十用发天如"
    "然作方成者多日都三小军二无同么经法当起与好看学进种将还分此心前面又定见只主没公从知道想些时间问题现在已经因为所以如果但是可以什么"
    "这个我们他们你们自己工作发展社会企业公司市场技术经济政府教育文化信息系统数据产品服务管理研究分析方法结果提供使用需要通过进行开展"
    "建设加强提高实现保护环境安全质量标准规定要求政策国家地区城市农村人民群众领导干部会议活动项目计划目标任务重点内容形式方式过程条件"
    "情况基础关系影响作用意义价值水平能力增长收入价格成本投资资金银行贷款税收财政预算利润客户用户名单姓名电话地址邮件部门职位员工老师"
    "学生学校大学医院医生病人健康生活家庭孩子父母朋友爱情故事世界历史文学艺术音乐电影电视新闻报道网站网络计算机软件程序代码文件文档页面"
    "链接图片视频文本字符编码测试欢迎访问首都北京上海广州深圳中心全多重新最高第两位每各及或且并虽然而因此于是所有另外其中之后之前之间"
    "以上以下以内以外期目前今明昨去月号星期早晚午候开始结束继续完成功败答案回提请谢再见对起关系喜欢希望觉得认为相信解明白记忘读写买卖吃"
    "饭喝水睡觉床走路跑步开车坐飞机火站场酒店餐厅商超市园河山海湖风雨雪云气春夏秋冬东西南北左右后外少长短低快慢旧坏美丑真假错否无去进出"
    "关借还给收送拿放带找做干打让叫被把比跟向往使由将电脑手机互联发布更新版本语言英汉字词句段章节标题作者读者朋友同学老师先生女士小姐"
)
_TRADITIONAL = (
    "的一是不了人我在有他這為之大來以個中上們到說國和地也子時道出而要於就下得可你年生自會那後能對著事其裡所去行過家十用發天如"
    "然作方成者多日都三小軍二無同麼經法當起與好看學進種將還分此心前面又定見只主沒公從知道想些時間問題現在已經因為所以如果但是可以什麼"
    "這個我們他們你們自己工作發展社會企業公司市場技術經濟政府教育文化信息資訊系統數據資料產品服務管理研究分析方法結果提供使用需要通過進行開展"
    "建設加強提高實現保護環境安全質量品質標準規定要求政策國家地區城市農村人民群眾領導幹部會議活動項目計劃目標任務重點內容形式方式過程條件"
    "情況基礎關係影響作用意義價值水平能力增長收入價格成本投資資金銀行貸款稅收財政預算利潤客戶用戶名單姓名電話地址郵件部門職位員工老師"
    "學生學校大學醫院醫生病人健康生活家庭孩子父母朋友愛情故事世界歷史文學藝術音樂電影電視新聞報導網站網路計算機軟體程式代碼檔案文件頁面"
    "連結圖片視頻影片文本字元編碼測試歡迎訪問首都北京上海廣州深圳中心全多重新最高第兩位每各及或且並雖然而因此於是所有另外其中之後之前之間"
    "以上以下以內以外期目前今明昨去月號星期早晚午候開始結束繼續完成功敗答案回提請謝再見對起關係喜歡希望覺得認為相信解明白記忘讀寫買賣吃"
    "飯喝水睡覺床走路跑步開車坐飛機火站場酒店餐廳商超市園河山海湖風雨雪雲氣春夏秋冬東西南北左右後外少長短低快慢舊壞美醜真假錯否無去進出"
    "關借還給收送拿放帶找做幹打讓叫被把比跟向往使由將電腦手機互聯發布更新版本語言英漢字詞句段章節標題作者讀者朋友同學老師先生女士小姐"
    "臺灣許功蓋嘅咗啲喺佢哋嘢乜咩點解邊度"
)
# family names and the given names people have most
_SIMPLIFIED += ("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾萧田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪"
                "范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤伟芳娜敏静丽强磊洋勇艳杰涛超秀娟英华慧巧美玉"
                "兰红霞燕鹏辉宇浩凯俊斌帅飞翔晨阳婷雪琳倩欣怡佳萍")
_TRADITIONAL += ("王李張劉陳楊黃趙吳周徐孫馬朱胡郭何高林羅鄭梁謝宋唐許韓馮鄧曹彭曾蕭田董袁潘於蔣蔡餘杜葉程蘇魏呂丁任沈姚盧姜崔鍾譚陸汪"
                 "範金石廖賈夏韋付方白鄒孟熊秦邱江尹薛閆段雷侯龍史陶黎賀顧毛郝龔邵萬錢嚴覃武戴莫孔向湯偉芳娜敏靜麗強磊洋勇豔傑濤超秀娟英華慧巧美玉"
                 "蘭紅霞燕鵬輝宇浩凱俊斌帥飛翔晨陽婷雪琳倩欣怡佳萍")
_SIMP = frozenset(_SIMPLIFIED)
_TRAD = frozenset(_TRADITIONAL)
_HAN = _SIMP | _TRAD | frozenset(
    "日本人大国中学生年月時分語愛私彼女男子供父母兄弟姉妹先後前今去来行見聞言話思知長高安新古少多小早遅明暗強弱"
    "食飲読書買売会社員仕事電車駅道町村県市区京都府東西南北山川海空天気雨雪花木林森石水火金土曜円万千百十一二三四五六七八九")
# the Hangul syllables a Korean text is made of (150 or so of the 2 350 in KS X 1001 are three
# quarters of it); a Chinese text read as Korean is syllables from all of them, and Hanja
_HANGUL = frozenset(
    "이다의는에을가하고한로지서기어사대인도수리아시자라나들보스으그있않전정일제장주없게부미면해과공운구소오유상내신마성적동국"
    "문같데비등안되많중우위관년개월원방연용여와간직계경세새불합조선각말물외반발영화회후및별생습니요십감확락드겠잠만려담름올바르입력밀번호"
    "혜택받처음것환약취급침검색판지항묻질객센터표메일록민최부터까보통따위때매더가모든런저금오늘제시장소")

_CJK = ("gb18030", "big5hkscs", "cp932", "euc_jp", "cp949")
_CYR = ("windows-1251", "koi8-r")
_CYR_COMMON = frozenset("оеаинтсрвлкмдпуяыьгзбчйхжшюцщэф")

# what a declared label means to a browser (the WHATWG encoding standard): gb2312 and gbk are
# gb18030, big5 is Big5 with Hong Kong's extension, Shift_JIS is Windows-31J, EUC-KR is
# Windows-949. The strict codecs of the same names stop at the first character outside their set.
_LABELS = {}
for _target, _names in (
        ("gb18030", "gb2312 gbk x-gbk gb_2312 gb_2312-80 gb-2312 euc-cn euccn x-euc-cn csgb2312 chinese iso-ir-58 "
                    "cn-gb gb18030"),
        ("big5hkscs", "big5 big5-hkscs big5hkscs cn-big5 x-x-big5 csbig5"),
        ("cp932", "shift_jis shift-jis sjis x-sjis ms_kanji csshiftjis windows-31j ms932 cp932"),
        ("cp949", "euc-kr euckr ks_c_5601-1987 ks_c_5601-1989 korean x-euc-kr windows-949 cp949 uhc")):
    for _n in _names.split():
        _LABELS[_n] = _target
del _target, _names, _n


def codec_of(label):
    """The codec that reads a declared charset label the way a browser does."""
    low = (label or "").strip().strip("\"'").lower()
    return _LABELS.get(low, low)


def _is_han(o):
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FA1F


def native_share(text, codec):
    """(the share of the text's non-ASCII characters that belong to `codec`'s own script, how many there are).
    Belonging: a common ideograph; the kana for the Japanese codecs, the common syllables for Korean;
    CJK and general punctuation, the fullwidth forms. An ideograph outside the common ones, a half-width
    kana, a box-drawing or Cyrillic character is what a wrong decoder makes of the bytes."""
    hits = han = n = 0
    kana = codec in ("cp932", "euc_jp")
    korean = codec == "cp949"
    for c in text:
        if c < "\x80" or c.isspace():
            continue
        n += 1
        o = ord(c)
        if _is_han(o):
            han += 1
            hits += c in _HAN
        elif 0x3040 <= o <= 0x30FF:
            hits += kana
        elif 0xAC00 <= o <= 0xD7A3:
            hits += korean and c in _HANGUL
        elif 0x3000 <= o <= 0x303F or 0xFF01 <= o <= 0xFF5E or 0xFFE0 <= o <= 0xFFE5 or 0x2010 <= o <= 0x2027 or o == 0xB7:
            hits += 1
    if not n:
        return 0.0, 0
    score = hits / float(n)
    if korean:
        # Korean text has next to no Hanja: the same bytes of a Chinese text read as cp949 are
        # Hangul syllables (all of them in the standard set) with a third of Hanja among them
        score *= max(0.0, 1.0 - 2.0 * han / n)
        return score, n
    return score, n


def plausible(text):
    """How much a decoded text reads like its own script: the share of the common lower-case
    letters among Cyrillic ones (KOI8 read as windows-1251 fails it: windows-1251 never raises an
    error, so it used to win every guess). Other scripts pass at 0.5."""
    letters = [c for c in (text or "")[:20000] if c.isalpha()]
    if not letters:
        return 0.5
    cy = [c for c in letters if "Ѐ" <= c <= "ӿ"]
    if len(cy) > len(letters) * 0.3:
        return sum(c in _CYR_COMMON for c in cy) / float(len(cy))
    return 0.5


_TAGS = re.compile(r"<[^<>]{0,400}>")
_CYR_RUN = re.compile("[Ѐ-ӿ]+")
# a Russian word is lower case, Capitalised or UPPER; the same bytes read in the wrong codec
# come out as letters of both cases in one word
_CYR_WORD = re.compile("^(?:[А-ЯЁ]?[а-яё]+|[А-ЯЁ]+)$")


_CYR_VOWEL = re.compile("[аеёиоуыэюяАЕЁИОУЫЭЮЯ]")        # a Russian word of three letters or more has one


def _cyr_score(text):
    """The Cyrillic reading's score on the scale of native_share: 0 when the non-ASCII characters are not
    mostly Cyrillic or the letters are the wrong case, 1 for Russian."""
    text = _TAGS.sub(" ", text)                    # a page's markup is ASCII letters, whatever the text is
    high = sum(1 for c in text if c >= "\x80")
    letters = sum(1 for c in text if c.isalpha())
    cy = [c for c in text if 0x400 <= ord(c) <= 0x4FF]
    if not high or len(cy) < high * 0.6 or len(cy) < letters * 0.3:
        return 0.0
    share = sum(c in _CYR_COMMON for c in cy) / float(len(cy))
    runs = _CYR_RUN.findall(text)
    shaped = sum(1 for r in runs if len(r) <= 30 and _CYR_WORD.match(r)
                 and (len(r) < 3 or _CYR_VOWEL.search(r))) / float(len(runs)) if runs else 0.0
    return max(0.0, min(1.0, (share - 0.5) / 0.4)) * shaped



# ---------------------------------------------------------------- the encoding of a page
WEAK_CHARSETS = {"iso-8859-1", "latin1", "latin-1", "windows-1252", "cp1252", "us-ascii", "ascii"}
BOMS = ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"), (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))
_HIGH = re.compile(rb"[\x80-\xff]")
SAMPLE = 60000                  # bytes of a body the guess reads: from its first non-ASCII byte on
CONFIDENT = 0.5                 # the least share of a script's own characters a reading must have
FAINT = 0.3                     # a smaller one will do when no other reading comes near it
MARGIN = 0.2                    # and how far it must be from the next reading before it is no doubt


class Decoded(tuple):
    """(text, charset, how, doubt): how is "bom", "declared" (the header or the page's own <meta>),
    "utf-8", "detected" (charset_normalizer) or "guessed"; doubt is True when the reading may be wrong."""
    __slots__ = ()

    def __new__(cls, text, charset, how="declared", doubt=False):
        return tuple.__new__(cls, (text, charset, how, doubt))

    text = property(lambda self: self[0])
    charset = property(lambda self: self[1])
    how = property(lambda self: self[2])
    doubt = property(lambda self: self[3])


def ansi_codepage():
    """The Windows ANSI code page (936 on a Chinese machine, 950, 932, 949, 1251 ...), 0 elsewhere."""
    if os.name != "nt":
        return 0
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetACP())
    except (AttributeError, OSError, ValueError):
        return 0


_BY_CODEPAGE = {936: "gb18030", 54936: "gb18030", 950: "big5hkscs", 932: "cp932", 949: "cp949", 1251: "windows-1251"}
_BY_LANG = {"zh-Hans": "gb18030", "zh-Hant": "big5hkscs", "ja": "cp932", "ko": "cp949", "ru": "windows-1251"}


def _preferred():
    """The codec this machine's user most likely has: its ANSI code page, else its language - the tie-break
    when two readings are as good as each other."""
    cp = _BY_CODEPAGE.get(ansi_codepage())
    if cp:
        return cp
    t = own_lang()
    if not t:
        return ""
    return _BY_LANG.get(chinese_script(t) and ("zh-" + chinese_script(t)) or t.split("-")[0], "")


def _sample(body):
    m = _HIGH.search(body)
    return body[m.start():m.start() + SAMPLE] if m else b""


def _read(sample, codec):
    return codecs.getincrementaldecoder(codec)("replace").decode(sample)


def rank(body):
    """[(score, codec, how many characters)], best first, of the readings of a body's non-ASCII
    bytes as the double-byte codecs and the two Cyrillic ones. Equal scores go to the codec this
    machine's user most likely has."""
    sample = _sample(body)
    if not sample:
        return []
    want = _preferred()
    out = []
    for codec in _CJK + _CYR:
        try:
            text = _read(sample, codec)
        except (LookupError, UnicodeError):
            continue
        text = text[:8000]
        if codec in _CYR:
            score, n = _cyr_score(text), sum(1 for c in text if c >= "\x80")
        else:
            score, n = native_share(text, codec)
        out.append((score, codec, n))
    out.sort(key=lambda r: -r[0])
    mine = next((r for r in out if r[1] == want), None)
    if mine is not None and out[0][0] - mine[0] <= 0.05:
        out.remove(mine)                         # as good as the best: this user's own codec wins the tie
        out.insert(0, mine)
    return out


def guess(body):
    """(text, codec, doubt) for a body that does not say what it is in and is not UTF-8, or None when no
    double-byte or Cyrillic reading is good enough (Western text, say). doubt: the reading is a
    close call, or rests on very little text."""
    ranked = rank(body)
    if not ranked:
        return None
    score, codec, n = ranked[0]
    nxt = ranked[1][0] if len(ranked) > 1 else 0.0
    if score < CONFIDENT and not (score >= FAINT and score - nxt >= MARGIN):
        return None
    doubt = score - nxt < MARGIN or n < 6 or score < 0.6
    return body.decode(codec, "replace"), codec, doubt


def decode_page(body, ct=""):
    """The text of `body` in the encoding it really is in, as a Decoded(text, charset, how, doubt).

    A BOM first; then the header's charset, unless it says latin-1 or ascii (servers send that by
    default, it is not a statement); then the page's own <meta>; then UTF-8 - each kept only when the
    text reads like its script; then the bytes themselves: the common characters of the scripts
    (`rank`), then charset_normalizer when it is installed, then a small repair heuristic. A declared
    gb2312, gbk or big5 is read as gb18030 or Big5-HKSCS, as a browser does: a page that says gb2312
    and holds one character the strict codec lacks is still Chinese."""
    body = body or b""
    for bom, cs in BOMS:
        if body.startswith(bom):
            return Decoded(body.decode(cs, "replace"), cs.replace("-sig", ""), "bom")
    head = (re.search(r"charset=[\"']?([\w-]+)", ct or "", re.I) or [None, ""])[1].lower()
    meta = (re.search(rb"charset=[\"']?([\w-]+)", body[:4096], re.I) or [None, b""])[1].decode("ascii", "ignore").lower()
    order = ([head] if head and head not in WEAK_CHARSETS else []) + ([meta] if meta else []) + ["utf-8"]
    declared = order[:-1]
    for cand in order:
        try:
            text = body.decode(codec_of(cand))
        except (LookupError, UnicodeDecodeError):
            continue
        if plausible(text) < 0.5:
            continue
        if codec_of(cand) in _CJK:
            share, n = native_share(text[:8000], codec_of(cand))
            if n >= 16 and share < 0.2:
                continue                         # a label that lies: the bytes are not that script
        return Decoded(text, cand, "declared" if cand in declared else "utf-8")
    # UTF-8 with a character cut in two (a page that stopped at its size limit) is still UTF-8
    text = body.decode("utf-8", "replace")
    good = sum(1 for c in text[:100000] if c >= "\x80" and c != "\N{REPLACEMENT CHARACTER}")
    if good >= 8 and text.count("\N{REPLACEMENT CHARACTER}") <= max(2, good // 50):
        said = any(codec_of(d) in ("utf-8", "utf8") for d in declared)
        return Decoded(text, "utf-8", "declared" if said else "utf-8", not said)
    g = guess(body)
    if g is not None:
        return Decoded(g[0], g[1], "guessed", g[2])
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(body[:200000]).best()
        if best is not None and best.encoding:
            high = len(_HIGH.findall(body[:20000]))
            return Decoded(body.decode(best.encoding, "replace"), best.encoding, "detected", high < 40)
    except Exception:                                         # noqa: BLE001
        pass
    # no charset_normalizer: a declared weak charset still beats a guess; then the last readings
    if head in WEAK_CHARSETS:
        return Decoded(body.decode(head if head not in ("us-ascii", "ascii") else "latin-1", "replace"), head,
                       "declared")
    sample = _sample(body)
    scores = [(_cyr_score(_read(sample, c)[:8000]), c) for c in _CYR] if sample else []
    best = max(scores) if scores else (0.0, "")
    if best[0] > 0:
        return Decoded(body.decode(best[1], "replace"), best[1], "guessed", True)
    return Decoded(body.decode("windows-1252", "replace"), "windows-1252", "guessed", True)


# ---------------------------------------------------------------- the script of a text, for OCR
def script_pack(text):
    """The tesseract language pack the text asks for by its script - chi_sim or chi_tra for ideographs
    (the variant by the characters that only one of them has), jpn where there is kana, kor for Hangul,
    rus for Cyrillic - or "" when it is none of them. The user's language decides when the text cannot."""
    sample = (text or "")[:20000]
    han = kana = hangul = cyr = simp = trad = 0
    for c in sample:
        if c < "Ѐ":
            continue
        o = ord(c)
        if _is_han(o):
            han += 1
            simp += c in _SIMP and c not in _TRAD
            trad += c in _TRAD and c not in _SIMP
        elif 0x3040 <= o <= 0x30FF:
            kana += 1
        elif 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF:
            hangul += 1
        elif 0x0400 <= o <= 0x04FF:
            cyr += 1
    if kana >= 5:
        return "jpn"
    if hangul >= 10:
        return "kor"
    if han >= 20:
        if trad != simp:
            return "chi_tra" if trad > simp else "chi_sim"
        return "chi_tra" if chinese_script(own_lang()) == "Hant" else "chi_sim"
    if cyr > 50:
        return "rus"
    return ""


def locale_packs():
    """The language packs of the user's own languages, in their order ("chi_sim" for a Chinese user; none for an
    English one): the ones `--setup` fetches for them (ownenv.ocr_pack_for, at most ownenv.OCR_MORE_PACKS)."""
    import ownenv
    out = []
    for t in own_langs():
        pack = ownenv.ocr_pack_for(t)
        if pack and pack not in out and len(out) < ownenv.OCR_MORE_PACKS:
            out.append(pack)
    return out


# ---------------------------------------------------------------- names a server chose
def file_stem(stem, limit=40):
    """A file's name from a server, as a name for our disk: letters and digits of any script stay, anything
    else (what a file system refuses, a path's separators) becomes "-"."""
    return re.sub(r"[^\w.\- ]+", "-", stem or "").strip(" .")[:limit]


def header_bytes(raw):
    """One header line as it came over the wire, as text: UTF-8, else the double-byte reading that fits it
    (a raw GBK file name), else Latin-1, which HTTP's own rule is."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    g = guess(raw)
    return g[0] if g is not None else raw.decode("latin-1")


def header_text(value):
    """A header value as text: http.client and some clients decode the bytes as Latin-1, which turns a
    raw UTF-8 or GBK file name into mojibake; the original bytes are read again as UTF-8, else as
    the double-byte reading that fits them (`guess`). Text that is not that kind of mojibake stays as it is."""
    v = value or ""
    if v.isascii():
        return v
    try:
        raw = v.encode("latin-1")
    except UnicodeEncodeError:
        return v
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    g = guess(raw)
    return g[0] if g is not None else v
