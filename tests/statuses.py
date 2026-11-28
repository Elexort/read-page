"""Honest statuses. No network. The browser's error page is in browser_live.py.

    python -X utf8 tests/statuses.py

Every check reads the manifest and the files of a run. A status is a promise: `ok` only when some
tier got a successful answer, a wall is `blocked` in any of twenty languages, and an article that
merely talks about walls stays `ok`.
"""
import base64
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import advsrv                                                # noqa: E402
from harness import PUBLIC, SCRIPT, Checks, run_read         # noqa: E402

check = Checks()
H = {"Content-Type": "text/html; charset=utf-8"}
LONG_EN = ("Reading pages reliably is harder than it looks, because servers lie about what they "
           "send and scripts change what a reader sees after the first paint. ") * 30


def page(title, body):
    return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title></head><body>%s</body></html>"
            % (title, body)).encode("utf-8")


def status(r):
    return r.manifest.get("status")


def reason(r):
    return str((r.manifest.get("signals") or {}).get("status_reason") or "")


# one wall phrase per language, as the walls write it, and a sentence of ordinary prose around it
WALLS = {
    "en": ("Verify you are human", "Sites sometimes ask a visitor to verify you are human before they show a page."),
    "ru": ("Подтвердите, что вы человек", "Иногда сайт просит: подтвердите, что вы человек, и только потом показывает текст."),
    "uk": ("Підтвердьте, що ви людина", "Іноді сайт просить: підтвердьте, що ви людина, і лише потім показує текст."),
    "de": ("Bestätigen Sie, dass Sie ein Mensch sind", "Manche Seiten verlangen: Bestätigen Sie, dass Sie ein Mensch sind, bevor sie den Text zeigen."),
    "fr": ("Vérifiez que vous êtes humain", "Certains sites demandent : vérifiez que vous êtes humain, puis affichent la page."),
    "es": ("Verifica que eres humano", "Algunos sitios piden: verifica que eres humano, y luego muestran la página."),
    "pt": ("Verifique se você é humano", "Alguns sites pedem: verifique se você é humano, e depois mostram a página."),
    "it": ("Verifica di essere umano", "Alcuni siti chiedono: verifica di essere umano, e poi mostrano la pagina."),
    "nl": ("Bevestig dat u een mens bent", "Sommige sites vragen: bevestig dat u een mens bent, en tonen dan de pagina."),
    "pl": ("Potwierdź, że jesteś człowiekiem", "Niektóre strony proszą: potwierdź, że jesteś człowiekiem, a potem pokazują tekst."),
    "cs": ("Ověřte, že jste člověk", "Některé stránky žádají: ověřte, že jste člověk, a teprve potom ukážou text."),
    "tr": ("İnsan olduğunuzu doğrulayın", "Bazı siteler önce insan olduğunuzu doğrulayın der, sonra sayfayı gösterir."),
    "sv": ("Bekräfta att du är människa", "Vissa sajter ber dig: bekräfta att du är människa, och visar sedan sidan."),
    "ja": ("人間であることを確認してください", "サイトによっては、人間であることを確認してくださいと表示してからページを見せる。"),
    "zh": ("确认您是真人", "有些网站会先要求确认您是真人，然后才显示页面内容。"),
    "ko": ("사람인지 확인하십시오", "어떤 사이트는 먼저 사람인지 확인하십시오라고 요청한 뒤 페이지를 보여 준다."),
    "ar": ("تحقق من أنك إنسان", "تطلب بعض المواقع أولاً: تحقق من أنك إنسان، ثم تعرض الصفحة."),
    "hi": ("सत्यापित करें कि आप इंसान हैं", "कुछ साइटें पहले कहती हैं कि सत्यापित करें कि आप इंसान हैं, फिर पेज दिखाती हैं।"),
    "id": ("Verifikasi bahwa Anda manusia", "Beberapa situs meminta: verifikasi bahwa Anda manusia, lalu menampilkan halaman."),
    "vi": ("Xác minh bạn là con người", "Một số trang yêu cầu: xác minh bạn là con người, rồi mới hiển thị trang."),
}
FILLER = {lang: (sentence + " ") * 3 for lang, (_, sentence) in WALLS.items()}


class Flip:
    """Answers `first` while `failing` is set, then `then`: a failure that must not stay in the
    cache. A switch, not a counter: one run may make several requests (fingerprints, plain curl)."""

    def __init__(self, first, then):
        self.first, self.then, self.failing = first, then, True

    def __call__(self, h):
        if self.failing and self.first == "drop":
            h.close_connection = True
            h.connection.close()
            return
        code, body = (self.first if self.failing else self.then)
        h.send_response(code)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(body)
        h.close_connection = True


def hn(h):
    """Hacker News in 2026: 419 to a browser fingerprint, the page to a plain client."""
    plain = "read-page" in (h.headers.get("User-Agent") or "")
    body = page("Hacker News", "<article><h1>Hacker News</h1><p>HN-MARKER " + LONG_EN + "</p></article>") \
        if plain else b"Sorry."
    h.send_response(200 if plain else 419)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Connection", "close")
    h.end_headers()
    h.wfile.write(body)
    h.close_connection = True


def stub_cut(h):
    """A promise of 5 000 bytes and two words, then the connection dies."""
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", "5000")
    h.end_headers()
    h.wfile.write(b"<html><body><p>Hello there")
    h.wfile.flush()
    h.close_connection = True


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAEklEQVR4nGP8z8DAwMDAwMAAAAwGAgH/pVPoAAAAAElFTkSuQmCC")
BIG_DATA = "data:image/png;base64," + base64.b64encode(PNG + os.urandom(60000)).decode()

s = advsrv.start()
r_ = s.public.routes
r_.update({
    "/stub-cut": stub_cut,
    "/400": (400, H, page("Bad Request", "<h1>Bad Request</h1><p>" + LONG_EN[:400] + "</p>")),
    "/401": (401, H, page("Unauthorized", "<h1>Unauthorized</h1><p>" + LONG_EN[:600] + "</p>")),
    "/407": (407, H, page("Proxy Authentication Required", "<h1>Proxy</h1><p>" + LONG_EN[:600] + "</p>")),
    "/403-long": (403, H, page("Forbidden", "<article><h1>Forbidden</h1><p>" + LONG_EN + "</p></article>")),
    "/419": (419, H, b"Sorry."),
    "/451": (451, H, page("Unavailable For Legal Reasons", "<h1>Unavailable</h1><p>" + LONG_EN[:600] + "</p>")),
    "/503-wall": (503, H, page("Just a moment...", "<h1>Just a moment...</h1><p>Checking your browser before "
                                                   "accessing the site.</p>")),
    "/hn": hn,
    "/cf-header": (200, dict(H, **{"cf-mitigated": "challenge"}),
                   page("Welcome", "<article><h1>Welcome</h1><p>" + LONG_EN + "</p></article>")),
    "/challenge-markup": (200, H, page("Loading", "<div id='challenge-form'></div><script src='/cdn-cgi/"
                                       "challenge-platform/h/b/orchestrate/chl_page/v1'></script>"
                                       "<p>One more step before you continue.</p>")),
    "/datadome": (200, H, page("example.com", "<script src='https://ct.captcha-delivery.com/c.js'></script>"
                               "<p>Please wait while we check.</p>")),
    # PubMed's challenge (2026-11-20): HTTP 203, the host for a title, a script that sets a cookie
    # and reloads, and these words for a client that did neither. It read as `ok`, 14 words
    "/cookie-wall": (203, H, page("pubmed.example", "<script>document.cookie='ncbi_pass=1';location.reload()"
                                  "</script><div id='cookie-required' hidden><h1>Cookies must be enabled</h1>"
                                  "<p>Enable cookies for <span>pubmed.example</span> and reload this page to "
                                  "continue.</p></div><footer><p><a href='/vdp'>Vulnerability Disclosure</a>"
                                  "</p></footer>")),
    "/cookie-help": (200, H, page("Why cookies must be enabled for this shop",
                                  "<article><h1>Why cookies must be enabled for this shop</h1><p>" + LONG_EN
                                  + "</p></article>")),
    # a block page in Cloudflare's wording, 102 words of one paragraph with the phrase in its title,
    # served with 200: `ok` while the phrase counted under 60 words only (2026-11-21)
    "/cookie-wall-102": (200, H, page("Please enable cookies.", "<h1>Please enable cookies.</h1><p>Sorry, you have "
                                      "been blocked. You are unable to access shop.example. Why have I been blocked? "
                                      "This website is using a security service to protect itself from online attacks. "
                                      "The action you just performed triggered the security solution. There are several "
                                      "actions that could trigger this block including submitting a certain word or "
                                      "phrase, a SQL command or malformed data. What can I do to resolve this? You can "
                                      "email the site owner to let them know you were blocked. Please include what you "
                                      "were doing when this page came up and the Ray ID found at the bottom of this "
                                      "page.</p>")),
    # a short help page about the same: 127 words, the phrase in its title and heading. It read as
    # `blocked`, "a challenge page" (2026-11-20)
    "/cookie-help-short": (200, H, page(
        "Please enable cookies | Example Help Center",
        "<header><a href='/'>Example Help Center</a></header><main><article><h1>Please enable cookies</h1>"
        "<p>Our checkout keeps your basket in a cookie, so the shop cannot work when your browser blocks "
        "cookies. Here is how to allow them for our site in the common browsers.</p><h2>Chrome</h2><p>Open "
        "Settings, then Privacy and security, then Third-party cookies. Choose Allow third-party cookies, or "
        "add our address under Sites allowed to use third-party cookies.</p><h2>Firefox</h2><p>Open Settings, "
        "then Privacy and Security. Under Enhanced Tracking Protection choose Standard, or add an exception "
        "for our address under Cookies and Site Data.</p><h2>Safari</h2><p>Open Settings, then Privacy, and "
        "clear Block all cookies. Reload the shop afterwards; your basket comes back when you sign in "
        "again.</p><p>Still stuck? Write to our support team and tell us which browser and version you "
        "use.</p></article></main>")),
    "/title-long": (200, H, page("Access denied: a short history of paywalls",
                                 "<article><h1>Access denied: a short history of paywalls</h1><p>"
                                 + LONG_EN + "</p></article>")),
    "/moment-long": (200, H, page("Just a moment of silence",
                                  "<article><h1>Just a moment of silence</h1><p>" + LONG_EN + "</p></article>")),
    "/inline": (200, H, page("Inline", "<article><h1>Inline picture</h1><p>" + LONG_EN
                             + "</p><img src='%s' alt='inline'><p>INLINE-MARKER after the picture.</p></article>"
                             % BIG_DATA)),
    "/flip-drop": Flip("drop", (200, page("Back", "<article><h1>Back</h1><p>FLIP-OK " + LONG_EN + "</p></article>"))),
    "/flip-503": Flip((503, page("Maintenance", "<h1>Back soon</h1><p>" + LONG_EN[:500] + "</p>")),
                      (200, page("Back", "<article><h1>Back</h1><p>FLIP-OK " + LONG_EN + "</p></article>"))),
    "/flip-429": Flip((429, page("Too Many Requests", "<h1>Too Many Requests</h1>")),
                      (200, page("Back", "<article><h1>Back</h1><p>FLIP-OK " + LONG_EN + "</p></article>"))),
})
for lang, (phrase, sentence) in WALLS.items():
    r_["/wall/" + lang] = (200, H, page(phrase, "<h1>%s</h1><p>%s</p>" % (phrase, phrase)))
    prose = " ".join([FILLER[lang]] * 12)
    r_["/article/" + lang] = (200, H, page("Article " + lang, "<article><h1>Article</h1><p>%s</p></article>" % prose))

# What a sign-in wall says, one sentence a language, as walls word it ("sign in to continue"), and a
# sentence of prose that quotes it. A wall is the sentence on a page of a few words; an article that
# quotes it is not one.
SIGNIN = {
    "en": ("Sign in to continue", "Many sites show a box that says sign in to continue, and that is all the page they send."),
    "ru": ("Войдите, чтобы продолжить", "Многие сайты показывают окно «войдите, чтобы продолжить», и это всё, что они отдают."),
    "uk": ("Увійдіть, щоб продовжити", "Багато сайтів показують вікно «увійдіть, щоб продовжити», і це все, що вони віддають."),
    "de": ("Melden Sie sich an, um fortzufahren", "Viele Seiten zeigen ein Fenster mit melden Sie sich an, um fortzufahren, und mehr nicht."),
    "fr": ("Connectez-vous pour continuer", "Beaucoup de sites affichent une fenêtre qui dit connectez-vous pour continuer, et rien de plus."),
    "es": ("Inicia sesión para continuar", "Muchos sitios muestran un cuadro que dice inicia sesión para continuar, y nada más."),
    "pt": ("Faça login para continuar", "Muitos sites mostram uma caixa que diz faça login para continuar, e nada mais."),
    "it": ("Accedi per continuare", "Molti siti mostrano una finestra che dice accedi per continuare, e nient'altro."),
    "nl": ("Log in om verder te gaan", "Veel sites tonen een venster met log in om verder te gaan, en verder niets."),
    "pl": ("Zaloguj się, aby kontynuować", "Wiele stron pokazuje okno z napisem zaloguj się, aby kontynuować, i nic więcej."),
    "cs": ("Pro pokračování se přihlaste", "Mnoho stránek ukazuje okno s větou pro pokračování se přihlaste, a nic víc."),
    "tr": ("Devam etmek için giriş yapın", "Birçok site devam etmek için giriş yapın yazan bir pencere gösterir, başka bir şey değil."),
    "sv": ("Logga in för att fortsätta", "Många sajter visar en ruta som säger logga in för att fortsätta, och inget mer."),
    "ja": ("続きを読むにはログインしてください", "多くのサイトは続きを読むにはログインしてくださいと書かれた枠を出し、それ以外は何も渡さない。"),
    "zh": ("请登录后查看全文", "许多网站会显示一个写着请登录后查看全文的框，除此之外什么也不给。"),
    "ko": ("계속 읽으려면 로그인이 필요합니다", "많은 사이트가 계속 읽으려면 로그인이 필요합니다라고 적힌 상자만 보여 준다."),
    "ar": ("يرجى تسجيل الدخول للمتابعة", "تعرض مواقع كثيرة مربعا يقول يرجى تسجيل الدخول للمتابعة ولا شيء غير ذلك."),
    "hi": ("जारी रखने के लिए लॉग इन करें", "कई साइटें एक बॉक्स दिखाती हैं जिसमें जारी रखने के लिए लॉग इन करें लिखा होता है, बस।"),
    "id": ("Masuk untuk melanjutkan", "Banyak situs menampilkan kotak yang berbunyi masuk untuk melanjutkan, dan tidak lebih."),
    "vi": ("Đăng nhập để tiếp tục", "Nhiều trang hiển thị một khung ghi đăng nhập để tiếp tục, và không gì hơn."),
}
# a subscription wall: the sentence a paywall puts where the article was
SUBSCRIBE = {
    "en": "Subscribe to read the full story", "ru": "Материал доступен только для подписчиков",
    "de": "Dieser Artikel ist nur für Abonnenten", "fr": "Article réservé aux abonnés",
    "es": "Contenido exclusivo para suscriptores", "pt": "Conteúdo exclusivo para assinantes",
    "it": "Questo articolo è riservato agli abbonati", "ja": "この記事は有料会員限定です", "zh": "订阅后阅读全文",
    "ko": "이 기사는 구독자 전용입니다", "ar": "هذا المحتوى للمشتركين فقط", "id": "Konten ini khusus pelanggan",
}
# the label of a sign-in form, and the language names a form of this kind lists beside it
FORM = {
    "en": "Log in to your account", "ru": "Войти в аккаунт", "uk": "Увійти до облікового запису",
    "de": "Bei Ihrem Konto anmelden", "fr": "Se connecter à votre compte", "es": "Iniciar sesión en tu cuenta",
    "pt": "Entrar na sua conta", "it": "Accedi a Facebook", "nl": "Inloggen op uw account", "pl": "Zaloguj się do konta",
    "cs": "Přihlášení k účtu", "tr": "Hesabınıza giriş yapın", "sv": "Logga in på ditt konto", "ja": "アカウントにログイン",
    "zh": "登录您的账户", "ko": "계정에 로그인", "ar": "تسجيل الدخول إلى حسابك", "hi": "अपने खाते में लॉग इन करें",
    "id": "Masuk ke akun Anda", "vi": "Đăng nhập vào tài khoản",
}
LANGNAMES = ("English Español Français Deutsch Русский Português Italiano Nederlands Polski Čeština Türkçe Svenska "
             "日本語 中文 한국어 العربية हिन्दी Bahasa Tiếng ")


def form_page(label, extra=""):
    return page(label, "<h1>%s</h1><p>%s</p><form action='/x' method='post'><input type='email' name='e'>"
                       "<input type='password' name='p'></form><p>%s</p>" % (label, LANGNAMES * 2, extra))


# "page not found", a template's sentence a language; a 404 page with menus around it; an article that quotes it
NOTFOUND = {
    "en": "Page cannot be found", "ru": "Страница не найдена", "uk": "Сторінку не знайдено", "de": "Seite nicht gefunden",
    "fr": "Page introuvable", "es": "Página no encontrada", "pt": "Página não encontrada", "it": "Pagina non trovata",
    "nl": "Pagina niet gevonden", "pl": "Strona nie istnieje", "cs": "Stránka nenalezena", "tr": "Sayfa bulunamadı",
    "sv": "Sidan hittades inte", "ja": "ページが見つかりません", "zh": "页面不存在", "ko": "페이지를 찾을 수 없습니다",
    "ar": "الصفحة غير موجودة", "hi": "पृष्ठ नहीं मिला", "id": "Halaman tidak ditemukan", "vi": "Không tìm thấy trang",
}
ZH_NOTFOUND = ("找不到页面", "您访问的页面不存在", "404 页面", "頁面不存在", "找不到網頁", "您訪問的頁面不存在")
QUOTING = ("A server may answer 200 and print «%s» on a page: this article explains how soft 404 pages are made, "
           "why crawlers read them as pages, and what a client can do to tell them from the real ones. ")
MENU = ("Home News Sport Weather Shop Contact About Careers Help Terms Privacy Cookies Sitemap Search Login Basket " * 8)
for lang in SIGNIN:
    wall, quoted = SIGNIN[lang]
    r_["/signin/" + lang] = (200, H, page(wall, "<h1>%s</h1><p>%s</p>" % (wall, wall)))
    r_["/signin-article/" + lang] = (200, H, page("Article", "<article><h1>Article</h1><p>%s</p></article>"
                                                  % (" ".join([quoted] * 12))))
    r_["/form/" + lang] = (200, H, form_page(FORM[lang]))
    r_["/missing/" + lang] = (200, H, page(NOTFOUND[lang], "<h1>%s</h1><p>%s</p>" % (NOTFOUND[lang], NOTFOUND[lang])))
    r_["/missing-menu/" + lang] = (200, H, page(NOTFOUND[lang] + " | Example", "<nav>%s</nav><h1>%s</h1>" % (MENU, NOTFOUND[lang])))
    r_["/missing-article/" + lang] = (200, H, page("Article", "<article><h1>Article</h1><p>%s</p></article>"
                                                   % ((QUOTING % NOTFOUND[lang]) * 6)))
for lang, sentence in SUBSCRIBE.items():
    r_["/subscribe/" + lang] = (200, H, page(sentence, "<h1>%s</h1><p>%s</p>" % (sentence, sentence)))
for i, phrase in enumerate(ZH_NOTFOUND):
    r_["/missing-zh/%d" % i] = (200, H, page(phrase, "<h1>%s</h1><p>%s</p>" % (phrase, phrase)))
# a password field and a short page of prose that is not about signing in: no wall; a long page with a login box: no wall
r_["/form-other"] = (200, H, form_page("Newsletter settings", "Choose how often we write to you and which topics you "
                                       "want: the weekly digest, the monthly report, or nothing at all."))
r_["/form-other-ja"] = (200, H, form_page("設定", "ニュースレターの配信頻度と話題を選んでください。週刊、月刊、または配信なし。"))
r_["/form-long"] = (200, H, page("Shop", "<header><a href='/login'>Log in</a><form><input type='password'></form></header>"
                                 "<article><h1>Shop</h1><p>" + LONG_EN + "</p></article>"))
r_["/missing-long-title"] = (200, H, page("Page not found: a short history of 404 pages",
                                          "<article><h1>Page not found: a short history of 404 pages</h1><p>"
                                          + LONG_EN + "</p></article>"))
# a page of the shell kind: the server sends no words, a script draws "Страница не найдена"
r_["/missing-js"] = (200, H, page("App", "<div id='app'></div><script>document.getElementById('app').innerHTML="
                                  "'<h1>Страница не найдена</h1><p>Вернитесь на главную.</p>'</script>"))


def ld(node, body="", head=""):
    """A page whose JSON-LD is `node` and whose body is an article."""
    return page("Story", "%s<script type='application/ld+json'>%s</script><article><h1>Story</h1><p>%s</p></article>"
                % (head, json.dumps(node), body or LONG_EN))


# a signed-in page whose content its scripts fetch: the HTML says what it is and "Loading organization limits..."
# where the content goes (console.groq.com/settings/limits read `ok` with that alone; KNOWN-ISSUES 259)
LOADING_NAV = "<nav>" + "".join("<a href='/s%d'>Settings section %d</a> " % (i, i) for i in range(12)) + "</nav>"
r_.update({
    "/loading-stub": (200, H, page("Limits", LOADING_NAV + "<main><h2>Organization Limits</h2><p>Base rate limits for "
                                             "your organization. These can be customized per project. If you need "
                                             "higher rate limits, you can purchase a subscription.</p><div><span>"
                                             "Loading organization limits...</span></div></main><script>window.x=1"
                                             "</script>")),
    # an article whose comments are what loads: the article is the page
    "/loading-comments": (200, H, page("Story", "<article><h1>Story</h1><p>" + LONG_EN + "</p></article><section>"
                                                "<h2>Comments</h2><p>Loading comments...</p></section>")),
})
# a Chinese and a Japanese article with a list's placeholder after it: their words are counted by character, as
# words_of counts them - by spaces the 1 690 characters of the first were 36 words, and it read `empty` (KNOWN-ISSUES 290)
ZH_PARA = ("北京是中华人民共和国的首都，也是全国的政治、文化和国际交往中心。这座城市有三千多年的建城史，历史上曾是多个朝代的"
           "都城，留下了故宫、天坛、颐和园等大量文物古迹。今天的北京既保留着传统的胡同和四合院，也有现代化的商务区和科技园区，"
           "每年吸引数以千万计的游客前来参观。")
JA_PARA = ("東京は日本の首都であり、政治、経済、文化の中心地です。江戸時代から続く歴史を持ち、浅草寺や皇居などの名所が数多く"
           "あります。現在では世界有数の大都市として、多くの人々が暮らし、働いています。")
r_.update({
    "/loading-zh": (200, H, page("北京", "<main><article><h1>北京</h1>" + "".join(
        "<h2>第%d节</h2><p>%s</p>" % (i, ZH_PARA) for i in range(1, 13))
        + "<div id='list-more'><p>加载中...</p></div></article></main>")),
    "/loading-ja": (200, H, page("東京", "<main><article><h1>東京</h1>" + "".join(
        "<h2>第%d節</h2><p>%s</p>" % (i, JA_PARA) for i in range(1, 13))
        + "<div id='more'><p>読み込み中...</p></div></article></main>")),
    # a short page of a tool's documentation whose code shows the tool's output: the code is its text (KNOWN-ISSUES 297)
    "/loading-code": (200, H, page("mytool sync", "<main><article><h1>mytool sync</h1><p>Run the sync command once after "
                                   "you install the tool. It reads your configuration file, fetches the remote index "
                                   "and writes a local copy, so later commands work offline. The output looks like "
                                   "this:</p><pre><code>$ mytool sync\nLoading configuration...\nFetched 1 204 entries\n"
                                   "Done.</code></pre><p>If the index cannot be reached, the command keeps the copy "
                                   "you already have and says so.</p></article></main>")),
})

# a paywall written in JavaScript: the article is in the HTML, the schema says it is not free
ART = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": "Story"}
r_.update({
    "/pw-ld": (200, H, ld(dict(ART, isAccessibleForFree=False))),
    "/pw-string": (200, H, ld(dict(ART, isAccessibleForFree="False"))),
    "/pw-part": (200, H, ld(dict(ART, isAccessibleForFree="False", hasPart={
        "@type": "WebPageElement", "isAccessibleForFree": "False", "cssSelector": ".paywall"}))),
    "/pw-graph": (200, H, ld({"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "name": "Site"}, dict(ART, isAccessibleForFree=False)]})),
    "/pw-micro": (200, H, page("Story", "<article itemscope itemtype='https://schema.org/NewsArticle'>"
                                        "<meta itemprop='isAccessibleForFree' content='False'><h1>Story</h1><p>"
                                        + LONG_EN + "</p></article>")),
    # the first 100 words of a story and a box under them: the text is there, cut
    "/pw-teaser": (200, H, ld(dict(ART, isAccessibleForFree=False),
                              LONG_EN[:700] + " Subscribe to continue reading this article.")),
    # a short article between two long menus: a fragment of the page as well as paywalled; the advice says both
    "/pw-fragment": (200, H, page("Story", "<script type='application/ld+json'>%s</script><header><nav><ul>%s</ul></nav>"
                                           "</header><article><h1>Story</h1><p>%s</p></article><footer><ul>%s</ul></footer>"
                                  % (json.dumps(dict(ART, isAccessibleForFree=False)), "<li><a href='/p'>Section of the "
                                     "site menu and its sub pages</a></li>" * 400, LONG_EN[:700],
                                     "<li><a href='/p'>Section of the site menu and its sub pages</a></li>" * 400))),
    "/pw-free": (200, H, ld(dict(ART, isAccessibleForFree=True))),
    "/pw-event": (200, H, ld({"@context": "https://schema.org", "@type": "MusicEvent", "name": "Concert",
                              "isAccessibleForFree": False})),
    "/pw-code": (200, H, page("Marking a paywall", "<article><h1>Marking a paywall</h1><p>Mark a paywalled page like this:"
                                                   "</p><pre><code>{&quot;isAccessibleForFree&quot;: false, &quot;hasPart&quot;: "
                                                   "{&quot;cssSelector&quot;: &quot;.paywall&quot;}}</code></pre><p>"
                              + LONG_EN + "</p></article>")),
    "/pw-class": (200, H, page("Story", "<div class='paywall'></div><div class='meteredContent'></div><article><h1>Story"
                                        "</h1><p>" + LONG_EN + "</p></article>")),
})


# an article its script holds for a viewer to draw: Aliyun's developer articles keep it as a Lake document (Yuque's
# format) in a JavaScript string, beside an empty <div id="lark-content"> the site's viewer draws it into; the server's
# HTML, and a headless browser whose viewer did not draw it, had the site's menus and footer alone (KNOWN-ISSUES 334)
def js_string(s):
    """The source of a JavaScript string in single quotes, written as the site writes it: quotes and slashes escaped,
    every character past ASCII a \\u escape."""
    out = []
    for ch in s:
        out.append("\\" + ch if ch in "\\'\"/" else "\\n" if ch == "\n" else
                   "\\u%04X" % ord(ch) if ord(ch) > 127 else ch)
    return "".join(out)


def lake_card(name, value, kind="block"):
    return '<card type="%s" name="%s" value="data:%s"></card>' % (kind, name, urllib.parse.quote(json.dumps(value)))


LAKE_DOC = ('<!doctype lake><meta name="doc-version" content="1" /><meta name="viewport" content="adapt" />'
            '<p data-lake-id="p0"><a href="https://so.example/anaconda">anaconda</a><span class="lake-fontsize-12">，'
            'windows系统，安装完ssl后，请求https地址，一直报以下错误：</span></p>'
            + lake_card("codeblock", {"mode": "plain", "code": "Traceback (most recent call last):\n  File \"F:\\work\\"
                                      "csdn.py\", line 3, in <module>\n    import ssl\nImportError: DLL load failed: "
                                      "找不到指定的模块。"})
            + '<p data-lake-id="p1">网上的方法尝试了很多，大多都是在Linux系统下的配置。</p><p data-lake-id="p2">最后发现在'
            'windows系统中是因为anaconda安装时少配了一个环境变量。</p>'
            + lake_card("image", {"src": "https://img.example/lake/path-dialog.png", "name": "环境变量对话框"})
            + '<p data-lake-id="p3">需要配置一下三个系统环境变量：</p>'
            + lake_card("codeblock", {"mode": "plain", "code": "F:\\gongju\\Anaconda3\nF:\\gongju\\Anaconda3\\Scripts\n"
                                      "F:\\gongju\\Anaconda3\\Library\\bin"})
            + lake_card("table", {"html": "<table class=\"lake-table\"><tbody><tr><td><p>版本</p></td><td><p>"
                                          "Anaconda3 2023.03</p></td></tr><tr><td><p>系统</p></td><td><p>Windows 10"
                                          "</p></td></tr></tbody></table>"})
            + lake_card("hr", {})
            + '<p data-lake-id="p4">配置完成后重启命令行，import ssl 不再报错。LAKE-END</p>')
LAKE_MENU = "".join("<li><a href='/group/%d'>云计算产品与服务%d</a></li>" % (i, i) for i in range(160))


def lake_page(inner="", script=True):
    """An article page of that kind: the menus, the title, the empty viewer's element (or `inner` in it, as a viewer
    that drew it leaves it), the footer, and the script with the document."""
    doc = ("<script>window.GLOBAL_CONFIG = {\"larkContent\": ''};\nGLOBAL_CONFIG.larkContent = '%s';</script>"
           % js_string(LAKE_DOC)) if script else ""
    return page("python3在windows系统下报ImportError: DLL load failed-开发者社区",
                "<header><nav><ul>%s</ul></nav></header>%s<div class='content-wrapper'><h1 class='article-title'>"
                "python3在windows系统下报ImportError: DLL load failed: 找不到指定的模块。</h1><div class='article-desc'>"
                "<b>简介：</b><span>python3在windows系统下报ImportError</span></div><div class='article-content'>"
                "<div class='article-inner' id='lark-content'>%s</div></div></div><footer><ul>%s</ul><p>LAKE-FOOTER "
                "© 2009-现在 版权所有</p></footer>" % (LAKE_MENU, doc, inner, LAKE_MENU))


r_.update({
    "/lake": (200, H, lake_page()),
    # the viewer drew it (a browser where it ran): the document is in its element already
    "/lake-drawn": (200, H, lake_page(inner="<p>需要配置一下三个系统环境变量：</p><pre><code>F:\\gongju\\Anaconda3\n"
                                            "F:\\gongju\\Anaconda3\\Library\\bin</code></pre><p>LAKE-END</p>")),
})

try:
    # ------------------------------------------------ a cut transfer says so
    for path in ("/truncated", "/stall"):
        r = run_read(s.public.url(path))
        sig = r.manifest.get("signals") or {}
        check("%s: signals.partial, and the answer says how to get the rest" % path,
              sig.get("partial") is True and ("--refresh" in (r.manifest.get("advice") or "")
                                             or "--download" in (r.manifest.get("advice") or "")),
              "%s partial=%s advice=%s" % (status(r), sig.get("partial"), (r.manifest.get("advice") or "")[:60]))
        check("%s: the first line of the answer says partial" % path,
              " partial" in r.text.split("\n")[0], r.text.split("\n")[0][:90])
    r = run_read(s.public.url("/stub-cut"))
    check("two words and a broken connection are not a page", status(r) != "ok",
          "%s: %s" % (status(r), reason(r)[:60]))

    # ------------------------------------------------ the code of the tier that gave the text
    expect = {"/500": "error", "/503": "error", "/400": "error", "/401": "login_required",
              "/407": "login_required", "/403-long": "blocked", "/419": "blocked", "/451": "blocked",
              "/503-wall": "blocked", "/404": "not_found"}
    r_["/404"] = (404, H, page("Not Found", "<h1>Not Found</h1><p>" + LONG_EN[:600] + "</p>"))
    for path, want in expect.items():
        r = run_read(s.public.url(path))
        check("%s -> %s" % (path, want), status(r) == want, "%s: %s" % (status(r), reason(r)[:60]))
    # with no Playwright the browser is Chrome's --dump-dom, which knows no HTTP status; the
    # server's code must still decide (it was `empty` on the CI runners: Chrome, no Playwright)
    r = run_read(s.public.url("/419"), env={"READ_PAGE_SKIP": "playwright"})
    tried = " ".join((r.manifest.get("chain") or {}).get("tried") or [])
    if "browser:cli" not in tried:
        check.skip("/419 through Chrome's --dump-dom", "no Chrome here (%s)" % tried)
    else:
        check("/419 through Chrome's --dump-dom -> blocked, the code named as the server's",
              status(r) == "blocked" and "from the server" in reason(r), "%s: %s" % (status(r), reason(r)[:60]))
    r = run_read(s.public.url("/500"))
    check("an error page's own text is kept",       # the body: trafilatura drops the <h1>
          "servers are having trouble" in r.file("content.md") and "500" in reason(r), reason(r)[:60])
    r = run_read(s.public.url("/hn"))
    check("a 419 to every fingerprint, then plain curl gets the page", status(r) == "ok"
          and "HN-MARKER" in r.file("content.md"), "%s %s" % (status(r), (r.manifest.get("chain") or {}).get("tried")))

    # ------------------------------------------------ walls without words, then in twenty languages
    for path in ("/anubis", "/xwrong", "/cf-header", "/challenge-markup", "/datadome"):
        r = run_read(s.public.url(path))
        check("%s is a wall" % path, status(r) == "blocked", "%s: %s" % (status(r), reason(r)[:60]))
    for path in ("/title-long", "/moment-long", "/cookie-help"):
        r = run_read(s.public.url(path))
        check("%s: a long article with the words in its title is an article" % path, status(r) == "ok",
              "%s: %s" % (status(r), reason(r)[:60]))
    r = run_read(s.public.url("/cookie-wall"))
    check("/cookie-wall: \"Cookies must be enabled ... reload this page\" is a wall, not a page of 14 words",
          status(r) == "blocked", "%s: %s | %r" % (status(r), reason(r)[:60], r.file("content.md")[:60]))
    r = run_read(s.public.url("/cookie-help-short"))
    check("/cookie-help-short: a help page of 127 words titled \"Please enable cookies\" is a page, not a wall",
          status(r) == "ok" and "Third-party cookies" in r.file("content.md"),
          "%s: %s" % (status(r), reason(r)[:60]))
    r = run_read(s.public.url("/cookie-wall-102"))
    check("/cookie-wall-102: a cookie wall of 102 words with no sections, served with 200, is a wall",
          status(r) == "blocked", "%s: %s" % (status(r), reason(r)[:60]))
    walls_missed, articles_hit = [], []
    for lang in WALLS:
        if status(run_read(s.public.url("/wall/" + lang))) != "blocked":
            walls_missed.append(lang)
        if status(run_read(s.public.url("/article/" + lang))) != "ok":
            articles_hit.append(lang)
    check("a wall is blocked in all %d languages" % len(WALLS), not walls_missed, "missed: %s" % walls_missed)
    check("an article that quotes the wall is ok in all %d languages" % len(WALLS), not articles_hit,
          "wrong: %s" % articles_hit)

    # ------------------------------------------------ a sign-in wall in twenty languages
    NO_BROWSER = {"READ_PAGE_SKIP": "browser"}    # these pages are judged on their HTTP text; one read below needs the browser
    walls_missed = [lang for lang in SIGNIN if status(run_read(s.public.url("/signin/" + lang), env=NO_BROWSER)) != "login_required"]
    check("\"sign in to continue\" is login_required in all %d languages" % len(SIGNIN), not walls_missed,
          "missed: %s" % walls_missed)
    walls_missed = [lang for lang in SUBSCRIBE
                    if status(run_read(s.public.url("/subscribe/" + lang), env=NO_BROWSER)) != "login_required"]
    check("\"for subscribers only\" is login_required in %d languages" % len(SUBSCRIBE), not walls_missed,
          "missed: %s" % walls_missed)
    # Facebook's form is 55-66 words and Instagram's 40-48: a password field and the form's own sign-in
    # label, on a page of a few dozen words. Two of them in the twenty languages read as `ok` before.
    walls_missed = [lang for lang in FORM if status(run_read(s.public.url("/form/" + lang), env=NO_BROWSER)) != "login_required"]
    check("a password form and its sign-in label are login_required in all %d languages" % len(FORM), not walls_missed,
          "missed: %s" % walls_missed)
    for path, what in (("/form-other", "a password field and a page about newsletter settings"),
                       ("/form-other-ja", "a password field and Japanese prose that does not say sign in"),
                       ("/form-long", "a shop's page with a login box in its header")):
        r = run_read(s.public.url(path), env=NO_BROWSER)
        check("%s is a page, not a sign-in wall" % what, status(r) == "ok", "%s: %s" % (status(r), reason(r)[:60]))
    for lang in ("en", "zh"):
        r = run_read(s.public.url("/signin-article/" + lang), env=NO_BROWSER)
        check("an article that quotes \"%s\" is ok (%s)" % (SIGNIN[lang][0], lang), status(r) == "ok",
              "%s: %s" % (status(r), reason(r)[:60]))

    # ------------------------------------------------ a page that says it is not there, twenty languages and Chinese
    missed = [lang for lang in NOTFOUND if status(run_read(s.public.url("/missing/" + lang), env=NO_BROWSER)) != "not_found"]
    check("a soft 404 (200, a few words, \"page not found\") is not_found in all %d languages" % len(NOTFOUND),
          not missed, "missed: %s" % missed)
    missed = [p for p in ZH_NOTFOUND if status(run_read(s.public.url("/missing-zh/%d" % ZH_NOTFOUND.index(p)), env=NO_BROWSER)) != "not_found"]
    check("Chinese soft 404s (找不到页面, 您访问的页面不存在, 404 页面, 頁面不存在, ...) are not_found", not missed,
          "missed: %s" % missed)
    for lang in ("ru", "zh", "ar"):
        r = run_read(s.public.url("/missing-menu/" + lang), env=NO_BROWSER)
        check("a 404 template under its menu (140 words) is not_found when its title says so (%s)" % lang,
              status(r) == "not_found", "%s: %s" % (status(r), reason(r)[:60]))
    for lang in ("en", "ja"):
        r = run_read(s.public.url("/missing-article/" + lang), env=NO_BROWSER)
        check("an article that quotes \"%s\" is ok" % NOTFOUND[lang], status(r) == "ok",
              "%s: %s" % (status(r), reason(r)[:60]))
    r = run_read(s.public.url("/missing-long-title"), env=NO_BROWSER)
    check("a long article titled \"Page not found: ...\" is an article", status(r) == "ok",
          "%s: %s" % (status(r), reason(r)[:60]))
    # a shell the server sends with no words: the page is "not found" only once a script has drawn it
    r = run_read(s.public.url("/missing-js"))
    tried = " ".join((r.manifest.get("chain") or {}).get("tried") or [])
    if "browser" not in tried:
        check.skip("a soft 404 a script draws", "no browser here (%s)" % tried)
    else:
        check("a soft 404 that only the browser's page says is not_found", status(r) == "not_found",
              "%s: %s | %r" % (status(r), reason(r)[:60], r.file("content.md")[:60]))

    # ------------------------------------------------ the same words, decided in the process
    spec_w = importlib.util.spec_from_file_location("rp_status_walls", SCRIPT)
    mod_w = importlib.util.module_from_spec(spec_w)
    spec_w.loader.exec_module(mod_w)
    fp_login = [lang for lang, (_w, quoted) in SIGNIN.items()
                if mod_w.login_state("", " ".join([quoted] * 12), 200, "http://x/", "http://x/")[0]]
    check("an article that quotes the sign-in sentence gets no login state at all, in all %d languages" % len(SIGNIN), not fp_login,
          "wrong: %s" % fp_login)
    fp_404 = [lang for lang in NOTFOUND
              if mod_w.soft_404_marker("Article", "Article", (QUOTING % NOTFOUND[lang]) * 6,
                                       mod_w.words_of((QUOTING % NOTFOUND[lang]) * 6))]
    check("an article that quotes the not-found sentence is no 404, in all %d languages" % len(NOTFOUND), not fp_404,
          "wrong: %s" % fp_404)
    check("a page about a word is not a 404: a dictionary entry for `404` is 150 words of prose",
          not mod_w.soft_404_marker("404 - Wiktionary", "404", "404 is a number. " * 50, 150))

    # ------------------------------------------------ a page whose content is still loading (KNOWN-ISSUES 259)
    r = run_read(s.public.url("/loading-stub"), env=NO_BROWSER)
    check("a page that shows only a loading message where its content goes is no plain ok: empty, its reason "
          "quotes the message",
          status(r) == "empty" and "Loading organization limits..." in reason(r),
          "%s | %s | %s" % (status(r), reason(r)[:90], (r.manifest.get("advice") or "")[:60]))
    check("... and the advice says the content did not come, and that a sign-in is often why",
          "did not arrive" in (r.manifest.get("advice") or "") and "sign" in (r.manifest.get("advice") or ""),
          (r.manifest.get("advice") or "")[:160])
    r = run_read(s.public.url("/loading-comments"), env=NO_BROWSER)
    check("an article whose comments are loading is ok: the article is the page",
          status(r) == "ok" and "loading" not in (r.manifest.get("advice") or "").lower(), status(r))
    for path in ("/loading-zh", "/loading-ja"):
        r = run_read(s.public.url(path), env=NO_BROWSER)
        check("%s: an article with a loading line after it is ok, its words counted by character (290)" % path,
              status(r) == "ok" and not (r.manifest.get("signals") or {}).get("loading"),
              "%s | %s" % (status(r), reason(r)[:90]))
    r = run_read(s.public.url("/loading-code"), env=NO_BROWSER)
    check("a short page whose code shows `Loading configuration...` is ok: code is its text (297)",
          status(r) == "ok" and not (r.manifest.get("signals") or {}).get("loading"), "%s | %s" % (status(r), reason(r)[:90]))

    # ------------------------------------------------ a deep address that lands on the site's home page (KNOWN-ISSUES 260)
    home = ("<!doctype html><html><head><meta charset='utf-8'><title>Home</title></head><body><main><h1>Welcome</h1>"
            "<p>HOME-PAGE " + LONG_EN[:600] + "</p></main></body></html>").encode("utf-8")
    from harness import serve                                # noqa: E402
    rs = serve({"/": (200, H, home), "/pricing": (308, {"Location": "/"}, b""),
                "/index.html": (301, {"Location": "/"}, b""), "/en/": (301, {"Location": "/"}, b""),
                "/docs/a": (301, {"Location": "/docs/b"}, b""), "/docs/b": (200, H, home)})
    try:
        r = run_read(rs.url("/pricing"), env=NO_BROWSER)
        adv = r.manifest.get("advice") or ""
        check("a deep address redirected to the site's home page: the advice says so, and that the page may be gone",
              status(r) == "ok" and "home page" in adv and "may be gone" in adv
              and (r.manifest.get("signals") or {}).get("redirect_root"), adv[:160])
        quiet = []
        for path in ("/index.html", "/en/", "/docs/a"):
            r = run_read(rs.url(path), env=NO_BROWSER)
            if "home page" in (r.manifest.get("advice") or "") or (r.manifest.get("signals") or {}).get("redirect_root"):
                quiet.append(path)
        check("... not for an address that is the home page by another name (/index.html, /en/), nor a page that moved",
              not quiet, str(quiet))
    finally:
        rs.close()

    # ------------------------------------------------ a paywall written in JavaScript
    for path, want in (("/pw-ld", ""), ("/pw-string", ""), ("/pw-part", ".paywall"), ("/pw-graph", ""), ("/pw-micro", ""),
                       ("/pw-teaser", "")):
        r = run_read(s.public.url(path), env=NO_BROWSER)
        sig = str((r.manifest.get("signals") or {}).get("paywall") or "")
        check("%s: the article is there (ok), and the answer says the page is paywalled" % path,
              status(r) == "ok" and "isAccessibleForFree" in sig and want in sig
              and "paywalled" in (r.manifest.get("advice") or ""),
              "%s | %s | %s" % (status(r), sig[:70], (r.manifest.get("advice") or "")[:50]))
    r = run_read(s.public.url("/pw-fragment"), env=NO_BROWSER)
    check("a paywalled page that is also a fragment of its page: the advice says both",
          "paywalled" in (r.manifest.get("advice") or "") and "of the page's words" in (r.manifest.get("advice") or ""),
          (r.manifest.get("advice") or "")[:120])
    # a paywall's teaser is short beside the site's menus: the answer showed page.md and its next: line led on through
    # the menus, and a model could not tell whether the article is hidden or not in the page (KNOWN-ISSUES 261)
    first = r.text.split("\n")[0]
    check("a paywalled fragment: the first line says the rest of the article is not in the page",
          "· paywalled: the rest of the article is not in the page ·" in first and "maybe a fragment" not in first,
          first[:140])
    check("... the answer shows the article's text, not page.md, and no next: line leads on through the menus",
          "── content.md:" in r.text and "--file page.md" not in r.text and "── page.md:" not in r.text,
          [ln[:80] for ln in r.text.split("\n") if ln.startswith("──")])
    check("... the advice says the rest is not in the page, and what page.md holds instead",
          "the rest of the article is not in the page" in (r.manifest.get("advice") or "")
          and "menus and links" in (r.manifest.get("advice") or ""), (r.manifest.get("advice") or "")[:200])
    r = run_read(s.public.url("/pw-ld"), env=NO_BROWSER)
    check("a paywalled page keeps its text: content.md has the article, not a stub",
          "servers lie about what they send" in r.file("content.md"), r.file("content.md")[:60])
    for path, what in (("/pw-free", "isAccessibleForFree: true"), ("/pw-event", "a ticketed event (isAccessibleForFree: false)"),
                       ("/pw-code", "an article that prints the markup in a <pre>"),
                       ("/pw-class", "a container named paywall and no schema")):
        r = run_read(s.public.url(path), env=NO_BROWSER)
        check("%s is no paywall" % what, status(r) == "ok" and not (r.manifest.get("signals") or {}).get("paywall")
              and "paywall" not in (r.manifest.get("advice") or ""),
              "%s | %s" % (status(r), (r.manifest.get("signals") or {}).get("paywall")))

    # ------------------------------------------------ an article its script holds for a viewer to draw (Lake)
    r = run_read(s.public.url("/lake"), "--deny-images", env=NO_BROWSER)
    content, first, sig = r.file("content.md"), r.text.split("\n")[0], r.manifest.get("signals") or {}
    check("334: an article the page holds as a Lake document in a script string is read - its paragraphs, code, "
          "picture and table, the escapes undone - and the manifest says it was drawn from the script",
          status(r) == "ok" and "最后发现在windows系统中是因为anaconda安装时少配了一个环境变量" in content
          and "ImportError: DLL load failed: 找不到指定的模块。" in content and "Anaconda3\\Library\\bin" in content
          and "环境变量对话框" in content and "Anaconda3 2023.03" in content and "LAKE-END" in content
          and "\\u" not in content and '\\"' not in content and "<card" not in content
          and sig.get("script_document") == "lake", "%s | %s | %r" % (status(r), sig.get("script_document"), content[:160]))
    check("... its code blocks are code: the traceback and the three PATH entries, each in a block of its own",
          bool(re.search(r"```[^\n]*\nTraceback \(most recent call last\):\n  File \"F:\\work\\csdn\.py\"", content))
          and bool(re.search(r"```[^\n]*\nF:\\gongju\\Anaconda3\nF:\\gongju\\Anaconda3\\Scripts\n", content)),
          [ln for ln in content.split("\n") if "Traceback" in ln or "gongju" in ln][:4])
    check("... the text holds the whole document, so it is no fragment however long the site's menus are, and the "
          "answer shows content.md", "maybe a fragment" not in first and sig.get("fragment") is False
          and "── content.md:" in r.text, "%s | cover %s" % (first[:120], (r.manifest.get("content") or {}).get("cover")))
    page_md = r.file("page.md")
    at = [page_md.find(x) for x in ("找不到指定的模块。", "最后发现在windows系统中", "LAKE-FOOTER")]
    check("... and page.md has it where the viewer draws it, between the title and the footer",
          -1 not in at and at == sorted(at), str(at))
    r = run_read(s.public.url("/lake-drawn"), "--deny-images", env=NO_BROWSER)
    content = r.file("content.md")
    check("334: a page whose viewer drew its document already is read as it is: the article once, nothing drawn twice",
          status(r) == "ok" and content.count("Library\\bin") == 1 and content.count("LAKE-END") == 1
          and not (r.manifest.get("signals") or {}).get("script_document"),
          "%d, %d | %s" % (content.count("Library\\bin"), content.count("LAKE-END"),
                           (r.manifest.get("signals") or {}).get("script_document")))

    # ------------------------------------------------ an archived PDF goes through the document path
    spec = importlib.util.spec_from_file_location("rp_status_a8", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    os.environ["READ_PAGE_TEST_PUBLIC_HOST"] = PUBLIC
    os.environ["READ_PAGE_CACHE"] = tempfile.mkdtemp(prefix="rp-status-")
    spec.loader.exec_module(mod)
    try:
        import pymupdf
        doc = pymupdf.open()
        pg = doc.new_page()
        pg.insert_text((72, 72), "ARCHIVED-PDF-MARKER a document that only the archive still has.", fontsize=11)
        for i in range(30):
            pg.insert_text((72, 100 + 18 * i), "Line %d of the archived report, ordinary prose for the reader." % i,
                           fontsize=10)
        pg = doc.new_page()                                  # and a table, whose layout is the read's too
        pg.insert_text((72, 80), "Table 1: Archived results by region", fontsize=10)
        pg.draw_line((72, 92), (470, 92))
        for k, row in enumerate([("Region", "North", "South")] + [("Area %d" % n, "%d.25" % (n * 7), "%d.75" % (n * 3))
                                                                  for n in range(1, 7)]):
            for x, cell in zip((76, 230, 360), row):
                pg.insert_text((x, 106 + 18 * k), cell, fontsize=10)
        pg.draw_line((72, 112), (470, 112))
        pg.draw_line((72, 236), (470, 236))
        pdf = doc.tobytes()
        mod.wayback = lambda url: (pdf, "application/pdf", "archive:wayback", "20200101000000")
        out = io.StringIO()
        old, sys.stdout = sys.stdout, out
        try:
            mod.main([s.public.url("/404"), "--allow-external", "--json", "--dir", tempfile.mkdtemp(prefix="rp-a8-")])
        finally:
            sys.stdout = old
        m = json.loads(out.getvalue() or "{}")
        text = open(os.path.join(m.get("dir") or "", "content.md"), encoding="utf-8").read() if m.get("dir") else ""
        check("an archived PDF is read as a PDF, not decoded as HTML",
              "ARCHIVED-PDF-MARKER" in text and "%PDF" not in text, "%s %s" % (m.get("status"), text[:60]))
        tab = (m.get("signals") or {}).get("tables") or {}
        if importlib.util.find_spec("pymupdf4llm") and importlib.util.find_spec("onnxruntime"):
            check("an archived PDF's tables are the read's: laid out, and in the manifest",
                  tab.get("pages") == "2" and any(ln.startswith("|") and "Area 1" in ln and "7.25" in ln and "3.75" in ln
                                                  for ln in text.splitlines()), "%s %r" % (tab, text[-300:]))
        else:
            check.skip("an archived PDF's tables", "no layout model in the suite's Python")
    except ImportError:
        check.skip("an archived PDF", "pymupdf is not installed here")

    # ------------------------------------------------ an archived page that comes gzipped
    # Wayback's id_ hands the payload as the site sent it; urllib unpacks nothing, and Crunchbase's
    # copy was decoded as KOI8-R: 199 KB of mojibake answered as `ok`
    import gzip as _gzip
    from harness import serve as _serve
    arch_page = ("<!doctype html><html><head><meta charset='utf-8'><title>Archived</title></head><body><article>"
                 "<h1>Archived</h1>" + "<p>ARCHIVE-GZ-MARKER Эту страницу хранит только архив, и она пришла сжатой.</p>" * 30
                 + "</article></body></html>").encode("utf-8")

    def cdx(h):
        import urllib.parse as _up
        want = _up.parse_qs(_up.urlsplit(h.path).query).get("url", [""])[0]
        body = ("20200101000000 %s\n" % want).encode("utf-8")
        h.send_response(200)
        h.send_header("Content-Type", "text/plain")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)
    snap = "/web/20200101000000id_/https://example.com/"
    arch = _serve({"/cdx/search/cdx": cdx,
                   snap + "gz-header": (200, {"Content-Type": "text/html", "Content-Encoding": "gzip"}, _gzip.compress(arch_page)),
                   snap + "gz-bare": (200, {"Content-Type": "text/html"}, _gzip.compress(arch_page)),
                   snap + "br": (200, {"Content-Type": "text/html", "Content-Encoding": "br"}, os.urandom(3000))})
    spec_gz = importlib.util.spec_from_file_location("rp_status_gz", SCRIPT)
    mod_gz = importlib.util.module_from_spec(spec_gz)          # the check above replaced its module's wayback()
    spec_gz.loader.exec_module(mod_gz)
    try:
        mod_gz.WAYBACK_URL = arch.url("")
        mod_gz.budget.start(mod_gz.budget.SECONDS)
        got = {k: mod_gz.archived_text("https://example.com/" + k, mod_gz.caps(), tempfile.mkdtemp(prefix="rp-gz-"))
               for k in ("gz-header", "gz-bare", "br")}
        ok_gz = all("ARCHIVE-GZ-MARKER" in (got[k][0] or "") and "Эту страницу хранит" in got[k][0]
                    for k in ("gz-header", "gz-bare"))
        check("an archived page sent gzipped, with the header or without it, is read as its text",
              ok_gz, "; ".join("%s: %r" % (k, (got[k][0] or got[k][5])[:60]) for k in ("gz-header", "gz-bare")))
        check("one that cannot be unpacked is no text, with the reason, not mojibake",
              not got["br"][0] and "unpack" in (got["br"][5] or ""), repr(got["br"][5])[:100])
    finally:
        arch.close()

    # ------------------------------------------------ too big is a status, not a crash
    mod.MAX_DOWNLOAD = 1000
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        mod.main([s.public.url("/gallery"), "--json", "--refresh", "--dir", tempfile.mkdtemp(prefix="rp-a9-")])
    finally:
        sys.stdout = old
    m = json.loads(out.getvalue() or "{}")
    limit = str((m.get("signals") or {}).get("limit") or "")
    check("a body over the cap is too_large, with the cap named",
          m.get("status") == "too_large" and "cap" in limit, "%s: %s" % (m.get("status"), limit[:70]))

    # ------------------------------------------------ no data: payload anywhere
    for flags in ((), ("--deny-images",)):
        r = run_read(s.public.url("/inline"), *flags)
        blob = r.text + "".join(r.file(n) for n in ("content.md", "page.md", "manifest.json"))
        run = max([len(x) for x in re.findall(r"[A-Za-z0-9+/=]{100,}", blob)] or [0])
        check("%s: no base64 payload in the answer, the text or the manifest" % (" ".join(flags) or "pictures on"),
              run < 300 and "INLINE-MARKER" in r.file("content.md"), "longest base64-like run %d" % run)

    # ------------------------------------------------ a failure is not kept for 15 minutes
    for path in ("/flip-drop", "/flip-503", "/flip-429"):
        r_[path].failing = True
        first = run_read(s.public.url(path))
        r_[path].failing = False
        again = run_read(s.public.url(path), reuse=first)
        check("%s: the failure is not served from the cache" % path,
              status(first) != "ok" and status(again) == "ok" and "FLIP-OK" in again.file("content.md"),
              "%s then %s (%s)" % (status(first), status(again), again.manifest.get("cache")))
    first = run_read(s.public.url("/404"))
    again = run_read(s.public.url("/404"), reuse=first)
    check("not_found is a real answer and is kept", again.manifest.get("cache") == "hit", str(again.manifest.get("cache")))

    # ------------------------------------------------ advice never repeats the flag just given
    r = run_read(s.public.url("/wall/en") + "?token=abc123", "--allow-external")
    check("a refused --allow-external is not advised again", "--allow-external" not in (r.manifest.get("advice") or "")
          and "--force-external" in (r.manifest.get("advice") or ""), (r.manifest.get("advice") or "")[:80])
finally:
    s.stop()

sys.exit(check.done())
