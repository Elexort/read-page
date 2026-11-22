"""Text and addresses outside ASCII, and the user's own language. Standard library only (Python 3.8+).

Four things a reader needs on a machine whose people write Chinese, Japanese, Korean or Russian,
none of which a Latin-1 habit gets right:

- `decode_page`: the text of a body that says what its encoding is, says it wrongly, or says
  nothing - and whether the reading is a guess. GBK and Big5 are told from each other, and from
  Cyrillic and Shift_JIS, by what the decoded text is made of (common characters of the script),
  not by the first codec that does not raise. `charset_normalizer`, when it is installed, reads the
  other single-byte scripts (Greek, Hebrew, Thai ...); the core does not need it.
- `iri_to_uri`: a raw `https://例子.测试/页面?q=中文` as the bytes a server wants, as a browser
  asks for them (host in punycode by UTS 46 - `host_ascii`, the one name the request, the network
  rule and the cookies go by - the rest percent-encoded as UTF-8). Every client of the skill that is
  handed an address goes through it: urllib raises on a non-ASCII character, and a curl built for
  the ANSI code page (Git's) sends the path in GBK. `location` reads a redirect's Location bytes.
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


# UTS 46 non-transitional, as browsers (the WHATWG URL standard) convert a host: ß, final ς and the two joiners
# are kept - IDNA 2003, the standard library's codec, maps them away and sent faß.de to fass.de, another name
_DEVIATIONS = frozenset("ßς\u200c\u200d")
_JOINERS = frozenset("\u200c\u200d")
# letters that join only to the right (Arabic, Persian): a ZWNJ after one of them joins nothing
_RIGHT_JOINING = frozenset("آأؤإاةدذرزوٱٲٳ"
                           "ٵٶٷڈډڊڋڌڍڎڏڐڑڒ"
                           "ړڔڕږڗژڙۀۃۄۅۆۇۈ"
                           "ۉۊۋۍۏےۓەۮۯ")
_RTL = ("R", "AL", "AN")


def _uts46_map(label):
    """A label mapped as UTS 46 does (case folded, compatibility forms to their letters, the characters it ignores
    dropped; ß, ς and the joiners kept), or None for one it disallows (spaces, controls, private use, unassigned
    code points, bidi controls, the other characters stringprep's nameprep prohibits)."""
    import stringprep
    import unicodedata
    out = []
    for c in unicodedata.normalize("NFKC", label):
        if c in _DEVIATIONS:
            out.append(c)
        elif c == "ẞ":
            out.append("ß")                       # capital sharp s is ß (casefold makes it ss)
        elif stringprep.in_table_b1(c) or "\ufe00" <= c <= "\ufe0f" or "\U000e0100" <= c <= "\U000e01ef":
            continue                                   # mapped to nothing: soft hyphen, variation selectors ...
        else:
            out.append(c.casefold())
    label = unicodedata.normalize("NFKC", "".join(out))
    for c in label:
        if c in _DEVIATIONS:
            continue
        if (unicodedata.category(c) == "Cn" or stringprep.in_table_c12(c) or stringprep.in_table_c22(c)
                or stringprep.in_table_c3(c) or stringprep.in_table_c4(c) or stringprep.in_table_c5(c)
                or stringprep.in_table_c6(c) or stringprep.in_table_c7(c) or stringprep.in_table_c8(c)
                or stringprep.in_table_c9(c)):
            return None
    return label


def _joiners_fit(label):
    """CONTEXTJ (RFC 5892): a ZWJ only after a virama; a ZWNJ after a virama, or between two letters that join
    (Persian's می\u200cخواهم) - the joining types approximated by script: a letter of the Arabic or Syriac blocks, not one
    that joins only to the right, before it."""
    import unicodedata

    def joining(c):
        return ("\u0600" <= c <= "\u08ff" or "\ufb50" <= c <= "\ufdff" or "\ufe70" <= c <= "\ufeff") and c.isalpha()
    for i, c in enumerate(label):
        if c not in _JOINERS:
            continue
        before = label[:i].rstrip("".join(x for x in label[:i] if unicodedata.category(x) == "Mn"))
        if i and unicodedata.combining(label[i - 1]) == 9:
            continue                                   # after a virama: either joiner fits
        if c == "\u200d":
            return False
        after = label[i + 1:].lstrip("".join(x for x in label[i + 1:] if unicodedata.category(x) == "Mn"))
        if not (before and after and joining(before[-1]) and before[-1] not in _RIGHT_JOINING and joining(after[0])):
            return False
    return True


def _bidi_fits(labels):
    """The bidi rule of RFC 5893, for a name with a right-to-left label in it (a name with none needs none)."""
    import unicodedata
    if not any(unicodedata.bidirectional(c) in _RTL for lab in labels for c in lab):
        return True
    for lab in labels:
        if not lab:
            continue
        kinds = [unicodedata.bidirectional(c) for c in lab]
        tail = [k for k in kinds if k != "NSM"] or [""]
        if kinds[0] in ("R", "AL"):
            if any(k not in ("R", "AL", "AN", "EN", "ES", "CS", "ET", "ON", "BN", "NSM") for k in kinds):
                return False
            if tail[-1] not in ("R", "AL", "EN", "AN") or ("EN" in kinds and "AN" in kinds):
                return False
        elif kinds[0] == "L":
            if any(k not in ("L", "EN", "ES", "CS", "ET", "ON", "BN", "NSM") for k in kinds) or tail[-1] not in ("L", "EN"):
                return False
        else:
            return False
    return True


def _punycode(host):
    """A host name outside ASCII as the ASCII name a browser asks for (UTS 46 non-transitional, its bidi and
    joiner rules: `faß.de` -> `xn--fa-hia.de`, `σοφός` keeps its final sigma, `שלום1` -> `xn--1-9hcuf1d`), or
    None for a name a browser refuses (a ZWJ between two Latin letters, a Latin letter in a Hebrew label,
    U+200E, a private-use character). The standard library alone; ideographic and fullwidth dots part labels."""
    import unicodedata
    labels = []
    for label in _DOTS.split(host):
        if label.isascii():
            labels.append(label.lower())
            continue
        mapped = _uts46_map(label)
        if mapped is None or _DOTS.search(mapped):
            return None                                # a dot out of a compatibility form (⒈ is "1."): refused
        labels.append(mapped)
    if not _bidi_fits(labels):
        return None
    out = []
    for label in labels:
        if label.isascii():
            out.append(label)
            continue
        if unicodedata.normalize("NFC", label) != label or unicodedata.category(label[0]).startswith("M") \
                or not _joiners_fit(label):
            return None
        try:
            out.append("xn--" + label.encode("punycode").decode("ascii"))
        except UnicodeError:
            return None
    return ".".join(out)


# what no host name holds: the forbidden domain code points of the WHATWG URL standard
_NOT_IN_HOST = re.compile(r"[\x00-\x20#%/:<>?@\[\\\]^|\x7f]")


def host_ascii(host):
    """The name a request for `host` goes to, in ASCII - or None when there is none.

    Every client the skill hands an address to decodes the host's percent-escapes (curl, libcurl and
    urllib alike: `127.0.0.%31` is 127.0.0.1 to all of them), and a name outside ASCII goes out as its
    punycode. This is that name, so it is also the one the network rule must look at. None: escapes
    that are not UTF-8, a name that cannot be converted, a character no host name may hold - such a
    host is refused, never guessed at. Not for an IPv6 literal (`[::1]`)."""
    h = host or ""
    if "%" in h:
        try:
            h = urllib.parse.unquote_to_bytes(h).decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not h.isascii():
        h = _punycode(h)
        if h is None:
            return None
    h = h.lower()
    return None if _NOT_IN_HOST.search(h) else h


# what a browser leaves out of an address (a tab, a line break: a URL copied across a wrapped line), and the
# ASCII it escapes in a web address's path, query and fragment (Chrome's `new URL()`)
_TABS = re.compile(r"[\t\n\r]")
_EDGES = re.compile(r"^[\x00-\x20]+|[\x00-\x20]+$")
_SPECIAL = re.compile(r"(?i)^(?:https?|wss?|ftp)://")
_IN_PATH = re.compile(r'[^\x21-\x7e]|["<>`{}|^]')
_IN_QUERY = re.compile(r"""[^\x21-\x7e]|["<>']""")
_IN_FRAGMENT = re.compile(r'[^\x21-\x7e]|["<>`]')


def iri_to_uri(url):
    """`url` as a server can be asked for it, as a browser asks: every character outside printable ASCII
    becomes its UTF-8 percent escapes (a space too), and so do the few ASCII ones a browser escapes (`"<>`,
    a quote in the query); a tab or a line break is left out, a backslash before the query is a slash; the
    host goes to punycode (host_ascii: the name the network rule checks, escapes in it decoded). What is
    already escaped stays exactly as it was."""
    url = _EDGES.sub("", _TABS.sub("", url or ""))
    special = bool(_SPECIAL.match(url))
    if special:
        cut = min([i for i in (url.find("?"), url.find("#")) if i >= 0] or [len(url)])
        url = url[:cut].replace("\\", "/") + url[cut:]
    m = _ABS.match(url)
    if not m:
        return _RAW.sub(_escape, url) if _RAW.search(url) else url
    scheme, netloc, rest = m.groups()
    userinfo, at, hostport = netloc.rpartition("@")
    if not hostport.startswith("["):
        host, port = hostport, ""
        h, colon, p = hostport.rpartition(":")
        if colon and (p.isdigit() or not p):
            host, port = h, ":" + p
        if not host.isascii() or "%" in host:
            # no ASCII form: the host stays as it is, and the network rule refuses it
            hostport = (host_ascii(host) or host) + port
    if special:
        rest, hsep, frag = rest.partition("#")
        path, qsep, query = rest.partition("?")
        rest = (_IN_PATH.sub(_escape, path) + qsep + _IN_QUERY.sub(_escape, query) + hsep
                + _IN_FRAGMENT.sub(_escape, frag))
    else:
        rest = _RAW.sub(_escape, rest)
    return scheme + _RAW.sub(_escape, userinfo) + at + hostport + rest


_HIGH_BYTE = re.compile(rb"[\x80-\xff]")


def location(raw):
    """A redirect's Location - the header's bytes, as they came - as the address a browser goes to next.
    UTF-8 is read as text: the request sends it as the same UTF-8 escapes, and its host is converted like
    any other. Any other byte above ASCII is percent-encoded as it is (`/caf\\xe9` -> `/caf%E9`, a GBK
    path stays GBK), as browsers do. Never re-read in another encoding. Text (a str) is taken as it is."""
    if isinstance(raw, str):
        return raw.strip()
    raw = (raw or b"").strip()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return _HIGH_BYTE.sub(lambda m: b"%%%02X" % m.group(0)[0], raw).decode("ascii", "replace")


# ---------------------------------------------------------------- the user's languages
_OS_LANGS = []


def _os_langs():
    """The languages the user set this machine up with, the one it is set to first ("zh-CN", "ru_RU.UTF-8"), then
    the others of their list: ownenv.system_languages (Windows' display languages, the environment's, a Mac's own
    settings), looked up once."""
    if not _OS_LANGS:
        import ownenv
        _OS_LANGS.append(ownenv.system_languages())
    return _OS_LANGS[0]


def _tag(raw):
    """One language tag in the form `ll` or `ll-RR` (or `zh-Hans`, `zh-Hant`), "" for what is no language. A POSIX
    locale's codeset and modifier go first (`zh_TW.UTF-8` is zh-TW, `sr_RS@latin` sr-RS)."""
    parts = [p for p in re.split(r"[-_]", (raw or "").strip().split(".")[0].split("@")[0]) if p]
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


def track_names(tag):
    """The names a video site gives the subtitle tracks of a language, best first: Chinese by script
    (`zh-Hant`, `zh-TW`, `zh-HK`, `zh`), any other language by its primary subtag (`en-US` -> `en`)."""
    script = chinese_script(tag)
    return list(_SUB_TRACKS[script]) if script else [(tag or "").split("-")[0]]


def sub_langs():
    """The subtitle tracks asked of yt-dlp, as a list: READ_PAGE_SUB_LANGS when it is set, else the user's
    languages - Chinese as YouTube names its tracks - then English."""
    env = (os.environ.get("READ_PAGE_SUB_LANGS") or "").strip()
    if env:
        return [x.strip() for x in env.split(",") if x.strip()]
    out = []
    for t in user_langs():
        for x in track_names(t):
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
_CYR = ("windows-1251", "koi8-r", "koi8-u")       # KOI8-U is KOI8-R with Ukrainian's і ї є ґ in place of box drawing
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
# a word of three letters or more has a vowel (Russian, Ukrainian, Belarusian, Bulgarian, Serbian)
_CYR_VOWELS = frozenset("аеёиоуыэюяіїєўАЕЁИОУЫЭЮЯІЇЄЎ")
# the ten commonest letters of Russian, two thirds of its letters (three fifths of Ukrainian's, more of
# Bulgarian's and Serbian's); Greek, Hebrew or Thai bytes read as windows-1251 or KOI8 make a third of them
_CYR_TOP = frozenset("оеаинтсрвл")
# what KOI8 reads the bytes 0x80-0xBF as: box drawing, blocks and a few signs. Real text in KOI8 or
# windows-1251 has none; Ukrainian KOI8-U read as KOI8-R, or Thai read as KOI8, is full of them
_KOI8_SIGNS = re.compile("[\u2500-\u259f\u2320\u2321\u2219\u221a\u2248\u2264\u2265]")


_LETTERS = re.compile(r"[^\W\d_]+")              # a run of letters, of any script


def _ramp(x, lo, hi):
    return max(0.0, min(1.0, (x - lo) / float(hi - lo)))


def _cyr_score(text):
    """The Cyrillic reading's score on the scale of native_share: 1 for Russian or Ukrainian prose, 0 when the
    non-ASCII characters are not mostly Cyrillic letters. Three tests, all of which a reading of the wrong
    bytes fails: the letters' frequencies (the ten commonest Russian letters), their case (a word is lower
    case, Capitalised or UPPER; Hebrew or Greek read as KOI8 is all capitals) and words with vowels - and a
    reading with KOI8's box drawing in it is no text at all."""
    text = _TAGS.sub(" ", text)                    # a page's markup is ASCII letters, whatever the text is
    high = sum(1 for c in text if c >= "\x80")
    letters = sum(1 for c in text if c.isalpha())
    cy = [c for c in text if 0x400 <= ord(c) <= 0x4FF]
    if not high or len(cy) < high * 0.6 or len(cy) < letters * 0.3:
        return 0.0
    if len(_KOI8_SIGNS.findall(text)) > high * 0.02:
        return 0.0
    top = sum(c.lower() in _CYR_TOP for c in cy) / float(len(cy))
    # the words a Cyrillic letter is in; one that mixes in Latin letters is no word (Latin-1's été read as
    # KOI8 is "ИtИ")
    runs = [w for w in _LETTERS.findall(text) if _CYR_RUN.search(w)]
    tails = "".join(r[1:] for r in runs)           # what follows a word's first letter is lower case in prose
    lower = sum(c.islower() for c in tails) / float(len(tails)) if tails else 1.0
    shaped = sum(1 for r in runs if len(r) <= 30 and _CYR_RUN.fullmatch(r)
                 and (r.islower() or r.isupper() or (r[0].isupper() and r[1:].islower()))
                 and (len(r) < 3 or any(c in _CYR_VOWELS for c in r))) / float(len(runs)) if runs else 0.0
    return _ramp(top, 0.25, 0.45) * _ramp(lower, 0.5, 0.8) * _ramp(shaped, 0.6, 0.9)



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
    close call, or rests on very little text. A Cyrillic reading must reach CONFIDENT: the bytes of
    every other single-byte script read as letters in windows-1251 or KOI8."""
    ranked = rank(body)
    if not ranked:
        return None
    score, codec, n = ranked[0]
    nxt = ranked[1][0] if len(ranked) > 1 else 0.0
    if score < CONFIDENT and not (codec in _CJK and score >= FAINT and score - nxt >= MARGIN):
        return None
    doubt = score - nxt < MARGIN or n < 6 or score < 0.6
    return body.decode(codec, "replace"), codec, doubt


def _label_lies(body, text, codec):
    """A declared double-byte label over bytes that are plainly another script's: its reading is few of its
    script's common characters and another reading is clearly better (CONFIDENT, and a MARGIN above it). A
    true label over rare characters - a periodic table, the provinces' one-character names - is kept."""
    share, n = native_share(text[:8000], codec)
    if n < 16 or share >= 0.2:
        return False
    try:
        body.decode("utf-8")
        return True                              # UTF-8 bytes (a text in GBK almost never is valid UTF-8)
    except UnicodeDecodeError:
        pass
    scores = dict((c, s) for s, c, _n in rank(body))
    other = max([s for c, s in scores.items() if c != codec] or [0.0])
    return other >= CONFIDENT and other - scores.get(codec, share) >= MARGIN


def _mostly_cyrillic(text):
    high = [c for c in text[:20000] if c >= "\x80" and c.isalpha()]
    return bool(high) and sum(1 for c in high if 0x400 <= ord(c) <= 0x4FF) >= len(high) * 0.6


def _detected(body):
    """charset_normalizer's reading of the body - (text, encoding, coherence) - or None when it is not
    installed or has none. coherence: how well the text fits the language it recognised in it, 0 for
    none - on a few words its codec is then a shot in the dark (big5 for `Привет`, cp1006 for
    `Цена 100 руб.`), and Hebrew read as Cyrillic or Greek scores 0.17-0.36 where real text scores 0.5-0.9."""
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(body[:200000]).best()
        if best is None or not best.encoding:
            return None
        return body.decode(best.encoding, "replace"), best.encoding, float(best.coherence or 0)
    except Exception:                                         # noqa: BLE001
        return None


def decode_page(body, ct=""):
    """The text of `body` in the encoding it really is in, as a Decoded(text, charset, how, doubt).

    A BOM first; then the header's charset, unless it says latin-1 or ascii (servers send that by
    default, it is not a statement); then the page's own <meta>; then UTF-8 - each kept only when the
    text reads like its script (a declared double-byte label unless another reading is clearly better);
    then the bytes themselves: a double-byte reading by the common characters of the scripts (`rank`);
    charset_normalizer when it is installed - for the other single-byte scripts, a Cyrillic reading of
    ours kept when it reads Cyrillic too; then a Cyrillic reading, then windows-1252, both doubtful. A
    declared gb2312, gbk or big5 is read as gb18030 or Big5-HKSCS, as a browser does: a page that says
    gb2312 and holds one character the strict codec lacks is still Chinese."""
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
        if codec_of(cand) in _CJK and _label_lies(body, text, codec_of(cand)):
            continue                             # a label that lies: the bytes are another script's
        return Decoded(text, cand, "declared" if cand in declared else "utf-8")
    # UTF-8 with a character cut in two (a page that stopped at its size limit) is still UTF-8
    text = body.decode("utf-8", "replace")
    good = sum(1 for c in text[:100000] if c >= "\x80" and c != "\N{REPLACEMENT CHARACTER}")
    if good >= 8 and text.count("\N{REPLACEMENT CHARACTER}") <= max(2, good // 50):
        said = any(codec_of(d) in ("utf-8", "utf8") for d in declared)
        return Decoded(text, "utf-8", "declared" if said else "utf-8", not said)
    g = guess(body)
    if g is not None and g[1] in _CJK:
        return Decoded(g[0], g[1], "guessed", g[2])     # charset_normalizer is weak on short CJK text
    # a Cyrillic reading, or none: charset_normalizer knows the other single-byte scripts (Greek, Hebrew,
    # Thai, Arabic, Central European); on Cyrillic, ours tells windows-1251 from KOI8 by the letters
    det = _detected(body)
    if g is not None:
        if det is None or det[2] < 0.1 or det[0] == g[0] or _mostly_cyrillic(det[0]):
            return Decoded(g[0], g[1], "guessed", g[2])
        return Decoded(det[0], det[1], "detected", True)   # it reads another script: the two disagree
    if det is not None:
        text, enc, coherence = det
        high = len(_HIGH.findall(body[:20000]))
        # doubtful: little to go on, a text that fits no language well, or a Cyrillic reading that the
        # letters test refuses (charset_normalizer reads Hebrew as Cyrillic)
        doubt = high < 40 or coherence < 0.25 or (
            _mostly_cyrillic(text) and _cyr_score(_read(_sample(body), enc)[:8000]) < CONFIDENT)
        return Decoded(text, enc, "detected", doubt)
    # no charset_normalizer: a declared weak charset still beats a guess; then the last readings
    if head in WEAK_CHARSETS:
        return Decoded(body.decode(head if head not in ("us-ascii", "ascii") else "latin-1", "replace"), head,
                       "declared")
    sample = _sample(body)
    scores = [(_cyr_score(_read(sample, c)[:8000]), c) for c in _CYR] if sample else []
    best = max(scores, key=lambda r: r[0]) if scores else (0.0, "")
    if best[0] > 0:
        return Decoded(body.decode(best[1], "replace"), best[1], "guessed", True)
    return Decoded(body.decode("windows-1252", "replace"), "windows-1252", "guessed", True)


# ---------------------------------------------------------------- the script of a text, for OCR
# kanji in the forms Japan alone writes (its own simplifications, and characters made in Japan): Chinese has
# 经/經 for 経, 发/發 for 発, 站 for 駅 - a text of kanji with no kana (a headline, an address) is Japanese by them
_JA_ONLY = frozenset("経発気駅県図広売読鉄楽対権歳戦関実険験転辺浜沢栄営単渋両黒拡児恵徳様総緑帰込畑峠枠働"
                     "姫鶏辻匂枡榊栃凪雫")


def script_pack(text):
    """The tesseract language pack the text asks for by its script - chi_sim or chi_tra for ideographs
    (the variant by the characters that only one of them has), jpn where kana is a real part of the
    ideographic text or kanji in Japan's own forms are there, kor for Hangul, rus for Cyrillic - or ""
    when it is none of them. The user's language decides when the text cannot."""
    sample = (text or "")[:20000]
    han = kana = hangul = cyr = simp = trad = ja = 0
    for c in sample:
        if c < "Ѐ":
            continue
        o = ord(c)
        if _is_han(o):
            han += 1
            simp += c in _SIMP and c not in _TRAD
            trad += c in _TRAD and c not in _SIMP
            ja += c in _JA_ONLY
        elif 0x3040 <= o <= 0x30FF:
            kana += 1
        elif 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF:
            hangul += 1
        elif 0x0400 <= o <= 0x04FF:
            cyr += 1
    # five の in a Chinese shop's page are not Japanese: kana is a tenth of Japanese prose's ideographic
    # text at the least (a third, usually)
    if (kana >= 5 and kana >= (han + kana) * 0.1) or (ja >= 3 and ja >= han * 0.03):
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


# the commonest words of each Latin-script language with a tessdata pack, without their accents: tesseract's English
# pack reads `für` as `fur`, and a text has these words whatever it is about. Measured on the English pack's readings
# of 94 scans in 24 languages (2026-11-22): the right language on every page of 10 of the 12 Latin-script ones
# (Turkish and Vietnamese undecided), and none for a page in another script, whose Latin letters are no language's
# words (their best share was 9.5 %); tests/cjk.py has six of them
LATIN_WORDS = {
    "eng": "the of and to in is that for it as was with on by be are this from at or which an its were has have not "
           "but they his her their been also who had",
    "deu": "der die und das ist nicht ein eine zu den von mit sich des auf fur im dem auch es als wird wurde nach bei "
           "aus sind oder werden einer eines zum zur uber",
    "fra": "le la les et de des est un une du que en dans pour qui pas sur au avec par il plus ce sont aux elle ont "
           "cette ses son leur mais comme",
    "spa": "el la de que y en los del se las por un una para con no es al lo como su fue mas pero sus entre esta este "
           "tambien",
    "por": "o a de que e do da em um para com nao uma os no se na por mais as dos como ao foi das sua seu pelo pela "
           "sao tambem",
    "ita": "il di che e la per un non una del le si in sono della con al dei da gli nel alla anche delle piu questo "
           "nella stato",
    "nld": "de het een en van in is dat op te zijn met voor niet aan er ook als door werd wordt bij naar uit maar om "
           "dan worden",
    "pol": "i w na z sie nie do to jest o jak po co ale od jego przez oraz jako ze tak sa dla za ktore",
    "tur": "bir ve bu da de ile ne olarak gibi daha en kadar sonra olan veya icin cok ise ilk her",
    "ind": "yang dan di ini itu dengan untuk dari tidak dalam akan pada adalah ke oleh juga sebagai atau karena",
    "ces": "a se na je v to s o ve z do jako by jsou k pro jeho ze byl ale tak jak ktery",
    "swe": "och i att det som en pa ar av for med till den har de inte om ett var jag",
    "ron": "si de la in cu a care pe din o un este sa mai ca pentru fost sunt al",
    "hun": "a az es hogy nem is egy meg de ez van volt mint csak el ki ami",
    "vie": "va cua la co cac nhung duoc trong cho mot voi khong nguoi nay da",
}
_LATIN_SETS = dict((k, frozenset(v.split())) for k, v in LATIN_WORDS.items())


def latin_pack(text):
    """The tessdata pack of the Latin-script language a text is in ("eng" for English, "deu", "fra" ...), by the
    share of its words that are that language's commonest (LATIN_WORDS): "" for fewer than 30 Latin words, a text
    mostly in another script, a share under 15 %, or two languages within 1.3 times of each other."""
    import unicodedata
    folded = "".join(c for c in unicodedata.normalize("NFKD", (text or "")[:20000]) if not unicodedata.combining(c))
    words = re.findall(r"[^\W\d_]+", folded.lower())
    latin = [w for w in words if w.isascii()]
    if len(latin) < 30 or len(latin) < len(words) * 0.6:
        return ""
    ranked = sorted(((sum(1 for w in latin if w in s), k) for k, s in _LATIN_SETS.items()), reverse=True)
    (best, pack), (second, _other) = ranked[0], ranked[1]
    if best < len(latin) * 0.15 or best < second * 1.3:
        return ""
    return pack


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
# the names Windows keeps for its devices, whatever follows them after a dot (CON.png, COM¹.pdf): such a file
# is a device on Windows 10 and Server, the download lost or written to the console
_DEVICE = re.compile(r"(?i)(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]) *")


def file_stem(stem, limit=40):
    """A file's name from a server, as a name for our disk: letters and digits of any script stay, anything
    else (what a file system refuses, a path's separators) becomes "-"; a device's name gets `file-` before it."""
    s = re.sub(r"[^\w.\- ]+", "-", stem or "").strip(" .")[:limit]
    return "file-" + s if _DEVICE.fullmatch(s.split(".")[0]) else s


def header_bytes(raw):
    """A header (a line, or a value) as it came over the wire, as text - read once, from its bytes: UTF-8, else
    the reading the letters fit (a raw GBK file name), else Latin-1, which HTTP's own rule is. Text that a
    client decoded already is never read again (a right `été.pdf` became `йtй.pdf`)."""
    raw = raw or b""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    g = guess(raw)
    return g[0] if g is not None else raw.decode("latin-1")
