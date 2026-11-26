#!/usr/bin/env python3
"""read-page - read a URL or a document, and prove what was obtained.

usage: python -X utf8 readpage.py URL [--allow-external] [--force-external] [--alternate]
                                   [--download] [--deny-images] [--screenshots [N]]
                                   [--refresh] [--clear-cookies] [--file content.md|page.md]
                                   [--from N] [--json] [--dir DIR] [--caps]

Prints the answer (a header, then the text: whole when it fits the output budget, else an
outline, the first block and the line to go on from with --from); --json prints the manifest
instead. Writes content.md, page.md, the raw response and manifest.json into the working
folder (the per-URL cache entry, or --dir). Never returns a partial page
silently: it reports which engine produced the text, whether it may be only a fragment of the
page, and what to try next.

Every limit lives in this file, so the CLI and the MCP server (scripts/mcp_server.py) share
one policy: MAX_DOWNLOAD, MAX_PAGE_BYTES, MEDIA_LIMIT, the timeouts and the attempts (the answer
budget lives in answer.py).
"""
import os
import sys

if __name__ == "__main__":
    # The skill's own environment (readpage.py --setup): the run goes on under its Python before
    # the imports below cost anything here. ownenv is small and compiled each time: no .pyc of it
    # beside the scripts before _pycache_home() below points them out of the skill's folder.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _dwb, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    import ownenv
    sys.dont_write_bytecode = _dwb
    if os.name == "posix":
        os.umask(0o077)       # main()'s, from the start: the .pyc written into the cache are this user's
    ownenv.use(__file__, sys.argv[1:])

import argparse                                                     # noqa: E402
import array                                                        # noqa: E402
import base64                                                       # noqa: E402
import contextlib                                                   # noqa: E402
import hashlib                                                      # noqa: E402
import io                                                           # noqa: E402
import ipaddress                                                    # noqa: E402
import json                                                         # noqa: E402
import math                                                         # noqa: E402
import posixpath                                                    # noqa: E402
import queue                                                        # noqa: E402
import re                                                           # noqa: E402
import shutil                                                       # noqa: E402
import socket                                                       # noqa: E402
import stat                                                         # noqa: E402
import struct                                                       # noqa: E402
import subprocess                                                   # noqa: E402
import tempfile                                                     # noqa: E402
import threading                                                    # noqa: E402
import time                                                         # noqa: E402
import unicodedata                                                  # noqa: E402
import zlib                                                         # noqa: E402
import urllib.error                                                 # noqa: E402
import urllib.parse                                                 # noqa: E402
from html import unescape                                           # noqa: E402
import urllib.request                                               # noqa: E402

def _pycache_home():
    """Where Python keeps this skill's compiled modules: out of the skill's folder, which some
    harnesses show the agent file by file, and in a folder only this user can write - a .pyc planted by someone else would run as our
    code. In the environment (readpage.py --setup) it is the environment's own folder, with everything else the
    skill keeps there, so that deleting that one folder removes it; without one, the user's temp folder.
    None when there is no such folder: then nothing is cached. The environment's folder on a mount with no Unix modes
    (WSL's /mnt/c, exFAT: every folder looks writable by all) is not one: the temp folder's is, then - reads ran with
    no bytecode at all there, 0.25 s more each."""
    mod = sys.modules.get("ownenv")              # imported (and use() run) before this by the CLI and the MCP server
    env = mod.status() if mod is not None else {}
    bases = [os.path.join(env["home"], "cache")] if env.get("used") and env.get("home") else []
    temp = tempfile.gettempdir()                 # a user's own folder on Windows and macOS
    bases.append(os.path.join(temp, "read-page-%d" % os.getuid()) if os.name == "posix" else temp)   # cache_root()'s
    for base in bases:
        path = os.path.join(base, "pycache")
        try:
            os.makedirs(base, mode=0o700, exist_ok=True)
            os.makedirs(path, mode=0o700, exist_ok=True)
            if os.name == "posix" and any(not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022
                                          for st in (os.lstat(p) for p in (base, path))):
                continue
            return path
        except OSError:
            continue
    return None


if __name__ == "__main__" and any(ownenv.meant_setup(a) for a in sys.argv[1:]):
    # --setup runs from outside the environment, once: what it compiled (the skill's modules, into the temp folder)
    # served nothing, and stayed outside the folder it names
    sys.dont_write_bytecode = True
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
elif not sys.pycache_prefix:
    _PYC = _pycache_home()
    if _PYC:
        sys.pycache_prefix = _PYC
        os.environ.setdefault("PYTHONPYCACHEPREFIX", _PYC)     # the extractors' processes too
    else:
        sys.dont_write_bytecode = True
        os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # `python -I` drops the script dir
import ownenv                                                       # noqa: E402
import answer                                                       # noqa: E402
import blockrule                                                    # noqa: E402
import budget                                                       # noqa: E402
import ddworker                                                     # noqa: E402
import debuglog                                                     # noqa: E402
import docreaders                                                   # noqa: E402
import engines                                                      # noqa: E402
import intl                                                         # noqa: E402
import netguard                                                     # noqa: E402
import pdftables                                                    # noqa: E402
import pictures                                                     # noqa: E402
import screens                                                      # noqa: E402
import settle                                                       # noqa: E402
import siteapi                                                      # noqa: E402
import subtitles                                                    # noqa: E402
from engines import (crude_text, html2text_full, readability_text,  # noqa: E402,F401
                     trafilatura_text, visible_len, visible_text)

SCHEMA = 1
VERSION = "0.4.6"
BUILD = 12         # bump when the manifest shape or the cache key changes
CACHE_TTL = 900                    # a page answer is fresh for 15 minutes
COOKIE_TTL = 6 * 3600             # a host's cookies live 6 hours; 2-24 h via READ_PAGE_COOKIE_HOURS
_cookie_hours = os.environ.get("READ_PAGE_COOKIE_HOURS", "").strip()
if _cookie_hours:
    try:
        COOKIE_TTL = int(max(2.0, min(24.0, float(_cookie_hours))) * 3600)
    except ValueError:
        pass
UA = "read-page/0.4 (agent skill)"

# ---------------------------------------------------------------- limits (one policy)
# These are the numbers an agent may hit; the MCP server imports them instead of
# repeating them, so a CLI run and an MCP call can never disagree.
MAX_DOWNLOAD = 250 * 1024 * 1024   # cap per download WITHOUT --download; --download has no cap
MAX_PAGE_BYTES = 64 * 1024 * 1024  # HTML/text larger than this is not parsed in memory
MAX_REDIRECTS = 8
MEDIA_LIMIT = 100 * 1024 * 1024    # cap per image/audio/video file WITHOUT --download
PAGE_LIMIT = MAX_DOWNLOAD          # total picture budget for one page WITHOUT --download
SPOOL_INMEM = 8 * 1024 * 1024      # bodies up to this stay in memory, bigger ones go to disk

# Every step has its own bound and there is no whole-run deadline: a stopwatch cannot
# tell a slow success from a hang, but a step can. Worst case, all of them in a row:
# HTTP 20 + converters 10 + browser 20 + readers 20 + archive 20 + pictures 4, about 105 s - under
# the 120 s an agent's shell tool waits by default. --download lifts the bounds on purpose.
HTTP_CONNECT_TIMEOUT = 7.5         # TCP/TLS connect, one attempt
HTTP_STEP_SECONDS = 45             # a fuse for the HTTP step; the read's deadline ends it first
HTTP_RESERVE_TAILS = 2.3           # the HTTP step leaves the extraction and the tail 2.3 tails (14 s)
HTTP_LOW_SPEED = (1024, 10)        # below 1 KB/s for 10 s in a row the transfer is cut, partial kept
HTTP_ATTEMPTS = 2                  # TLS fingerprints; a 3rd only if both answered a plain 403
BROWSER_STEP_SECONDS = 25          # the browser step: launch, load, settle; a second browser only when one fails to start
READER_SECONDS = 12                # one remote reader (Firecrawl, Jina), connect included
READERS_STEP_SECONDS = 20          # all of them; the next one only while time is left
ARCHIVE_STEP_SECONDS = 20          # Wayback: the CDX lookup and the snapshot together
CONVERTER_TIMEOUT = 10             # defuddle / pdftotext / a machine's markitdown or pandoc each, and our
                                   # EPUB/ODT/RTF readers for all the read's documents; defuddle takes ~1 s
PICTURE_ORDER_SECONDS = 10         # an archive's pictures put in reading order (a book's spine); ms for a real one
OCR_TIMEOUT = 30                   # tesseract on one rendered page of a scan
OCR_LANGS = os.environ.get("READ_PAGE_OCR_LANGS", "eng")
OCR_MAX_PAGES = 3
VIDEO_TIMEOUT = 20                 # yt-dlp, network-bound
IMAGE_TIMEOUT = 4                  # one picture: a connection that says nothing for 4 s is stuck
IMAGE_WORKERS = 32                 # a browser opens many connections; so do we
# An answer's pictures, the text's first; with --download: no limit. 6 s, not 4:
# with no limit, 129 reads of picture-heavy pages on a fast machine and on an emulated weak laptop took p50
# 1.1 s, p95 2.6, at most 5.8. A 4 s phase would have cut 3 (2.3 %), the only fuse of a read that
# fired that often: twice pictures still arriving (NASA, 34 of 34 in 5.2-5.4 s, a 14 MB photo
# among them), once one stuck that IMAGE_TIMEOUT ended at 5.8 s. 6 s cuts none of them; a stuck
# picture stays IMAGE_TIMEOUT's, and any picture without a file is fetched again when printed.
IMAGE_PHASE_SECONDS = 6
# A picture that failed (a dead host, a server error, a dropped connection) is asked once more, by a
# window printed this long after (every answer from the cache asked dmoz's dead picture
# hosts again, 0.55 s instead of 0.23; a host that never answers would have cost the whole phase).
# One the phase cut, one never printed and one --deny-images named are asked whenever printed.
PICTURE_RETRY_AFTER = 30

ACCEPT = "text/markdown, text/html;q=0.9, text/plain;q=0.8, */*;q=0.5"
HTML_ACCEPT = "text/html,application/xhtml+xml,*/*;q=0.8"
# Order matters: newest first, then older pinned fingerprints that sites have not blocked yet.
IMPERSONATIONS = ("chrome151", "firefox135", "safari184", "chrome124")   # HTTP_ATTEMPTS cap
IMPERSONATIONS_MAC = ("safari184", "chrome151_macos", "firefox135", "chrome124")


def curl_cffi_requests():
    """curl_cffi.requests without the extras it imports for itself: its Response.markdown() pulls
    markdownify, bs4, chardet and readability in at import (0.2 s on a fast machine, about 0.8 s on a weak
    laptop) behind an ImportError guard, and this skill never calls it. A None in sys.modules
    makes that import fail for the moment curl_cffi loads; the names are free again after."""
    mod = sys.modules.get("curl_cffi.requests")
    if mod is not None:
        return mod
    stubbed = [n for n in ("markdownify", "readability") if n not in sys.modules]
    for n in stubbed:
        sys.modules[n] = None
    try:
        from curl_cffi import requests as cr
    finally:
        for n in stubbed:
            if sys.modules.get(n, 0) is None:
                del sys.modules[n]
    return cr


def impersonations():
    """Which fingerprints to try, in order, for this machine and this curl_cffi build.

    Measured 30.10 on 14 sites (npm, medium, reddit, x, glassdoor, indeed, amazon, booking,
    zillow, walmart, tiktok, instagram, cloudflare docs, pypi): newest chrome (136-152) and edge
    are rejected by npm/medium; chrome151 passes 12/14, firefox135 adds amazon, safari184 covers
    the rest. Four attempts at most, one is enough on 12 of 14. Random fingerprints are not used:
    sites keep allowlists, so only real versions from curl_cffi's own target list can pass.
    """
    want = IMPERSONATIONS_MAC if sys.platform == "darwin" else IMPERSONATIONS
    try:
        have = {e.value for e in curl_cffi_requests().BrowserType}
    except Exception:                                      # noqa: BLE001
        return ("chrome124", "chrome120")
    out = tuple(x for x in want if x in have)
    return out or ("chrome124", "chrome120")


SKIP = engines.SKIP           # READ_PAGE_SKIP: one set, shared with the extractors' module

# A page that says in its title, its heading or its first lines that it is not there, and has
# few words: a soft 404 (the server answers 200). `404` and the English words count on a page under
# SOFT_404_WORDS; the phrases of NOTFOUND_PHRASES, in about twenty languages, are a template's own
# sentence, so a title or heading that says one counts on a page up to SOFT_404_TITLE_WORDS (a 404
# page often carries a menu: Tweakers 62 words, Taobao 123, Almasry Alyoum 173 of the probes).
NOTFOUND_MARKERS = ("page not found", "not found", "404", "does not exist", "no longer available")
SOFT_404_WORDS = 40
SOFT_404_TITLE_WORDS = 200
NOTFOUND_PHRASES = (
    # en
    "page cannot be found", "page can't be found", "page could not be found", "page you requested",
    "page you are looking for", "page you're looking for", "this page doesn't exist", "this page isn't available",
    "we couldn't find that page", "we can't find that page",
    # ru, uk
    "страница не найдена", "страница не существует", "страницы не существует", "страницы нет", "такой страницы нет",
    "запрашиваемая страница не найдена", "запрашиваемой страницы не существует", "ошибка 404",
    "сторінку не знайдено", "сторінка не знайдена", "сторінки не існує", "сторінка не існує", "такої сторінки немає",
    "помилка 404",
    # de, fr, es, pt, it, nl
    "seite nicht gefunden", "seite wurde nicht gefunden", "seite konnte nicht gefunden werden", "seite existiert nicht",
    "seite gibt es nicht", "seite ist nicht mehr verfügbar", "fehler 404", "404-fehler",
    "page introuvable", "page non trouvée", "cette page n'existe pas", "la page demandée n'existe pas",
    "page inexistante", "erreur 404", "cette page est introuvable",
    "página no encontrada", "la página no existe", "esta página no existe", "página no disponible",
    "no se ha encontrado la página", "no se encontró la página", "no se pudo encontrar la página", "error 404",
    "página não encontrada", "página não existe", "esta página não existe", "página inexistente",
    "não foi possível encontrar a página", "página indisponível", "erro 404",
    "pagina non trovata", "la pagina non esiste", "questa pagina non esiste", "pagina inesistente",
    "pagina non disponibile", "errore 404",
    "pagina niet gevonden", "pagina kon niet worden gevonden", "pagina kan helaas niet worden gevonden",
    "pagina kon niet gevonden worden", "pagina bestaat niet", "deze pagina bestaat niet", "pagina is niet gevonden",
    "pagina niet beschikbaar", "pagina kon niet geladen worden", "fout 404",
    # pl, cs, tr, sv
    "strona nie została znaleziona", "nie znaleziono strony", "strona nie istnieje", "ta strona nie istnieje",
    "strona nie jest dostępna", "błąd 404",
    "stránka nenalezena", "stránka nebyla nalezena", "stránku se nepodařilo najít", "stránka neexistuje",
    "tato stránka neexistuje", "chyba 404",
    "sayfa bulunamadı", "sayfa bulunamadi", "sayfa mevcut değil", "sayfa mevcut degil", "aradığınız sayfa",
    "aradiginiz sayfa", "hata 404", "404 hatası",
    "sidan hittades inte", "sidan kunde inte hittas", "sidan finns inte", "sidan existerar inte", "fel 404",
    # ja, zh, ko
    "ページが見つかりません", "お探しのページ", "お探しのコンテンツ", "ページが表示できません", "ページにアクセスできません", "ページは存在しません", "ページが存在しません", "存在しないページ",
    "エラー404", "404エラー",
    "页面不存在", "找不到页面", "找不到该页面", "找不到此页面", "页面未找到", "页面找不到", "没有找到页面", "页面无法访问",
    "页面走丢", "页面没有找到", "您访问的页面", "你访问的页面", "404 页面", "404页面", "404 错误", "404错误", "网页不存在", "文章不存在",
    "数据不存在",
    "頁面不存在", "找不到頁面", "找不到網頁", "頁面未找到", "您訪問的頁面", "404 頁面", "404頁面", "404 錯誤", "404錯誤",
    "網頁不存在",
    "페이지를 찾을 수 없", "페이지가 없어요", "페이지가 존재하지 않", "존재하지 않는 페이지", "요청하신 페이지", "삭제되었거나 존재하지 않",
    "404 오류", "에러 404",
    # ar, hi, id, vi
    "الصفحة غير موجودة", "لم يتم العثور على الصفحة", "الصفحة المطلوبة غير", "الصفحه المطلوبه غير", "الصفحة التي تبحث عنها", "الصفحة غير متاحة", "الصفحه غير متاحه",
    "تعذر العثور على الصفحة", "خطأ 404",
    "पृष्ठ नहीं मिला", "पेज नहीं मिला", "पृष्ठ मौजूद नहीं", "पेज मौजूद नहीं", "त्रुटि 404",
    "halaman tidak ditemukan", "halaman yang anda cari", "halaman tidak tersedia", "halaman tidak ada",
    "halaman yang diminta tidak", "kesalahan 404",
    "không tìm thấy trang", "trang không tồn tại", "trang không được tìm thấy", "trang bạn tìm không", "nội dung không tìm thấy", "nội dung không tồn tại", "lỗi 404",
)

# Walls. First what a server says without words: a header, a challenge in the markup.
WALL_HEADERS = (("cf-mitigated", "challenge"), ("x-vercel-mitigated", ""), ("x-amzn-waf-action", ""))
WALL_MARKUP = ("/cdn-cgi/challenge-platform/", "cf_chl_opt", "id=\"challenge-form\"", "id='challenge-form'",
               "captcha-delivery.com", "px-captcha", "_incapsula_resource", "awswaf", "aws-waf-token",
               "anubis_challenge", "within.website/x/cmd/anubis")
# Then the words, in about twenty languages, translated once here and never at read time. A strong
# phrase counts in the title, the first heading or the first lines of a short page; a weak one
# ("just a moment") only when it is all the title says, or on a page of a few words. Prose that
# quotes them on a long page is an article about walls, not a wall (medium.com answers 200 with
# "Sorry, you have been blocked", 599 characters; an article on paywalls is 2 000 words).
WALL_STRONG = (
    # en
    "verify you are human", "verifying you are human", "verify that you are human", "verify you're human",
    "please verify you are a human", "checking your browser", "checking if the site connection is secure",
    "you have been blocked", "why have i been blocked", "access denied", "access to this page has been denied",
    "attention required", "making sure you're not a bot", "making sure you are not a bot", "are you a robot",
    "unusual traffic", "too many requests", "request blocked", "performing security verification",
    "ddos protection", "client challenge", "enable javascript and cookies to continue", "human verification",
    "pardon our interruption", "press & hold", "cf-browser-verification", "unable to access",
    # ru, uk
    "подтвердите, что вы человек", "проверка браузера", "проверяем ваш браузер", "проверка вашего браузера",
    "вы заблокированы", "доступ запрещён", "доступ запрещен", "доступ ограничен", "слишком много запросов",
    "необычный трафик", "подозрительный трафик", "вы не робот", "я не робот",
    "підтвердьте, що ви людина", "перевірка браузера", "вас заблоковано", "доступ заборонено",
    "забагато запитів", "незвичний трафік", "ви не робот",
    # de, fr, es, pt, it, nl
    "bestätigen sie, dass sie ein mensch sind", "bestätigen, dass sie ein mensch sind",
    "überprüfung ihres browsers", "ihr browser wird überprüft", "sie wurden blockiert", "zugriff verweigert",
    "zu viele anfragen", "ungewöhnlicher datenverkehr", "sind sie ein roboter",
    "vérifiez que vous êtes humain", "vérification que vous êtes humain", "vérifier que vous êtes un humain",
    "vérification de votre navigateur", "vous avez été bloqué", "accès refusé", "trop de requêtes",
    "trafic inhabituel", "êtes-vous un robot",
    "verifica que eres humano", "verificando que eres humano", "verifique que es humano",
    "comprobando su navegador", "comprobando tu navegador", "has sido bloqueado", "ha sido bloqueado",
    "acceso denegado", "demasiadas solicitudes", "tráfico inusual", "eres un robot",
    "verifique se você é humano", "verificando se você é humano", "confirme que você é humano",
    "verificando seu navegador", "você foi bloqueado", "acesso negado", "muitas solicitações",
    "tráfego incomum", "tráfego invulgar", "você é um robô",
    "verifica di essere umano", "verifica che sei umano", "conferma di essere un essere umano",
    "verifica del browser", "controllo del browser", "sei stato bloccato", "accesso negato",
    "troppe richieste", "traffico insolito", "sei un robot",
    "bevestig dat u een mens bent", "bevestig dat je een mens bent", "uw browser wordt gecontroleerd",
    "u bent geblokkeerd", "je bent geblokkeerd", "toegang geweigerd", "te veel verzoeken",
    "ongebruikelijk verkeer", "bent u een robot",
    # pl, cs, tr, sv
    "potwierdź, że jesteś człowiekiem", "sprawdzanie przeglądarki", "zostałeś zablokowany", "odmowa dostępu",
    "dostęp zabroniony", "zbyt wiele żądań", "nietypowy ruch", "czy jesteś robotem",
    "ověřte, že jste člověk", "kontrola prohlížeče", "byli jste zablokováni", "přístup odepřen",
    "příliš mnoho požadavků", "neobvyklý provoz",
    "insan olduğunuzu doğrulayın", "tarayıcınız kontrol ediliyor", "tarayıcınızı kontrol ediyoruz",
    "engellendiniz", "erişim engellendi", "erişim reddedildi", "çok fazla istek", "olağandışı trafik",
    "robot musunuz",
    "bekräfta att du är människa", "bekräfta att du är en människa", "kontrollerar din webbläsare",
    "du har blockerats", "åtkomst nekad", "för många förfrågningar", "ovanlig trafik", "är du en robot",
    # ja, zh, ko
    "人間であることを確認", "ブラウザを確認しています", "ブラウザをチェックしています", "ブロックされました",
    "アクセスが拒否されました", "アクセス拒否", "リクエストが多すぎます", "通常と異なるトラフィック",
    "ロボットではありません",
    "确认您是真人", "验证您是真人", "确认你是真人", "验证你是真人", "确认您是人类", "验证您是人类",
    "確認您是真人", "驗證您是真人", "確認您是人類", "正在检查您的浏览器", "正在檢查您的瀏覽器",
    "您已被阻止", "您已被封锁", "访问被拒绝", "拒绝访问", "拒絕存取", "存取被拒", "请求过多", "請求過多",
    "异常流量", "異常流量", "人机验证", "人機驗證",
    "사람인지 확인", "브라우저를 확인", "차단되었습니다", "액세스가 거부", "접근이 거부",
    "요청이 너무 많습니다", "비정상적인 트래픽", "로봇이 아닙니다",
    # ar, hi, id, vi
    "تحقق من أنك إنسان", "التحقق من أنك إنسان", "التحقق من متصفحك", "لقد تم حظرك", "تم رفض الوصول",
    "طلبات كثيرة جدًا", "حركة مرور غير عادية", "هل أنت روبوت",
    "सत्यापित करें कि आप इंसान हैं", "पुष्टि करें कि आप इंसान हैं", "आपके ब्राउज़र की जाँच",
    "आपको ब्लॉक कर दिया गया है", "पहुंच अस्वीकृत", "बहुत सारे अनुरोध", "असामान्य ट्रैफ़िक",
    "verifikasi bahwa anda manusia", "memverifikasi bahwa anda manusia", "memeriksa browser anda",
    "anda telah diblokir", "akses ditolak", "terlalu banyak permintaan", "lalu lintas tidak biasa",
    "apakah anda robot",
    "xác minh bạn là con người", "đang kiểm tra trình duyệt", "bạn đã bị chặn", "truy cập bị từ chối",
    "quá nhiều yêu cầu", "lưu lượng truy cập bất thường", "bạn có phải là robot",
)
WALL_WEAK = (
    "just a moment", "one moment", "please wait", "something went wrong", "security check",
    "один момент", "одну минуту", "подождите", "что-то пошло не так", "одну мить", "щось пішло не так",
    "einen moment", "nur einen moment", "etwas ist schiefgelaufen", "un instant", "un moment",
    "une erreur s'est produite", "un momento", "algo salió mal", "um momento", "só um momento",
    "algo deu errado", "un attimo", "qualcosa è andato storto", "een ogenblik", "even geduld",
    "er is iets misgegaan", "chwileczkę", "coś poszło nie tak", "okamžik", "něco se pokazilo",
    "bir dakika", "lütfen bekleyin", "bir şeyler ters gitti", "ett ögonblick", "något gick fel",
    "しばらくお待ちください", "問題が発生しました", "请稍候", "請稍候", "出了点问题", "出错了",
    "잠시만 기다려", "문제가 발생했습니다", "لحظة واحدة", "حدث خطأ ما", "एक क्षण", "कुछ गलत हो गया",
    "tunggu sebentar", "terjadi kesalahan", "vui lòng chờ", "đã xảy ra lỗi",
)
# A script sets a cookie and reloads; a client that did neither gets these words (PubMed, 2026-11-20:
# HTTP 203 and 14 words that read as `ok`; NCBI Bookshelf 34). A help page about cookies says them
# in its title as well (127 words read as `blocked`), so they count only on a page of a few words.
# English only: the one seen.
WALL_COOKIES = ("cookies must be enabled", "please enable cookies")
WALL_COOKIES_WORDS = 60
# ... and up to 150 on a page with no sections of its own: a block page in Cloudflare's wording is
# 102 words of one paragraph (served with 200 it read as `ok`), the help page has three of steps
WALL_COOKIES_PLAIN = 150
_SECTION = re.compile(r"<h[2-6]\b")
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")


def fold(s):
    """Lower case without accents or marks: one phrase list matches ÜBERPRÜFUNG, İnsan and Tiếng."""
    s = unicodedata.normalize("NFKD", (s or "").casefold())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


_WALL_STRONG = tuple(fold(p) for p in WALL_STRONG)
_WALL_WEAK = tuple(fold(p) for p in WALL_WEAK)
_WALL_COOKIES = tuple(fold(p) for p in WALL_COOKIES)
_NOTFOUND_MARKERS = tuple(fold(p) for p in NOTFOUND_MARKERS)
_NOTFOUND_PHRASES = tuple(fold(p) for p in NOTFOUND_PHRASES)


def _lead(text, n):
    """The first n characters of a text as a reader sees them: a picture marker and a link's address left out."""
    t = pictures.MARK.sub(" ", (text or "")[:2000])
    t = re.sub(r"\]\([^)\s]*(?:\s+\"[^\"]*\")?\)", "]", t)
    return fold(re.sub(r"\s+", " ", t).strip()[:n])


def soft_404_marker(title, heading, text, words):
    """The phrase that makes a 200 answer a page that is not there ("" when none does): a marker in
    the title, the heading or the first lines of a page under SOFT_404_WORDS, or a phrase of a 404
    template there, or in the first lines, of a page under SOFT_404_TITLE_WORDS."""
    if words >= SOFT_404_TITLE_WORDS:
        return ""
    t, hd = fold(title), fold(heading)
    if words < SOFT_404_WORDS:
        first, marks = _lead(text, 160), _NOTFOUND_MARKERS + _NOTFOUND_PHRASES
    else:
        first, marks = _lead(text, 300), _NOTFOUND_PHRASES
    for m in marks:
        if m in t or m in hd or m in first:
            return m
    return ""


def words_of(text):
    """Words, with Chinese and Japanese counted by character: they put no spaces between words,
    and a 2 000-character article must not look like a page of 40 words."""
    t = text or ""
    cjk = len(_CJK.findall(t))
    return len(_CJK.sub(" ", t).split()) + cjk


def _bare(s, phrase):
    """The title (or heading) says the phrase and nothing else: "Just a moment...", "Один момент…"."""
    return re.sub(r"^[\W_]+|[\W_]+$", "", s or "") == phrase


def wall_signal(headers, html, title, heading, text, words):
    """Why this page is a wall ("" when it is not): what the server says without
    words first (a header, a challenge in the markup), then a phrase where a wall puts it."""
    h = {str(k).lower(): str(v or "").lower() for k, v in (headers or {}).items()}
    for name, value in WALL_HEADERS:
        if name in h and (not value or value in h[name]):
            return "the server marks it as a challenge (%s: %s)" % (name, h[name][:40])
    low = (html or "")[:30000].lower()
    if words < 300:
        for mark in WALL_MARKUP:
            if mark in low:
                return "a challenge in the page markup (%s)" % mark.strip("/\"'=")
    t, hd = fold(title), fold(heading)
    first, body = fold((text or "")[:200]), fold((text or "")[:2000])

    def said(p):           # the page's own words where it said it, else the phrase
        return next((x.strip() for x in (title, heading) if x and p in fold(x)), p)[:80]

    for p in _WALL_STRONG:
        # the title or heading of a page under 300 words; its first lines under 100 (a 190-word
        # page of docs may open with "an access denied page..."); anywhere under 40
        if ((words < 300 and (p in t or p in hd)) or (words < 100 and p in first)
                or (words < 40 and p in body)):
            return "a challenge page: %s" % said(p)
    few = words < WALL_COOKIES_WORDS or (words < WALL_COOKIES_PLAIN and not _SECTION.search(low))
    for p in _WALL_COOKIES:
        if (few and (p in t or p in hd or p in first)) or (words < 40 and p in body):
            return "a challenge page: %s" % said(p)
    for p in _WALL_WEAK:
        if (words < 300 and (_bare(t, p) or _bare(hd, p))) or (words < 40 and p in body):
            return "a challenge page: %s" % said(p)
    return ""


SOURCE_NAMES = {"http": "server", "browser": "browser", "archive": "archive", "reader": "reader"}


def code_status(code):
    """What an HTTP code alone says about the text it came with: `ok` needs a
    successful answer from the tier whose text this is."""
    if not code or 200 <= code < 400:
        return ""
    if code in (401, 407):
        return "login_required"
    if code in (403, 419, 429, 451):
        return "blocked"
    if code in (404, 410):
        return "not_found"
    return "error"


_DATA_URI = re.compile(r"data:[\w.+/-]*(?:;[\w.+=-]+)*,[^\s)\"'<>]{200,}")


def short_data(uri):
    """A data: URI as its type, size and hash: the payload itself is a picture, not text."""
    head = (uri or "").split(",", 1)[0]
    return "%s,<%s sha1:%s>" % (head, human_bytes(max(0, len(uri) - len(head) - 1)),
                                hashlib.sha1((uri or "").encode("utf-8", "replace")).hexdigest()[:8])


def short_data_uris(text):
    return _DATA_URI.sub(lambda m: short_data(m.group(0)), text or "")


def image_ref_name(url):
    """The file name a picture reference gives: its path's last part, `inline-<hash>.<ext>` for a
    data: URI (whose "path" is the base64 payload)."""
    if (url or "").startswith("data:"):
        mime = url[5:].split(",", 1)[0].split(";")[0].lower()
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
               "image/svg+xml": ".svg"}.get(mime, ".png")
        return "inline-%s%s" % (hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:8], ext)
    return os.path.basename(urllib.parse.urlparse(url or "").path) or "image"

if hasattr(sys.stdout, "reconfigure"):
    # LF only: Python on Windows writes CRLF, one byte more per line than the budget counts
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")


# ---------------------------------------------------------------- infrastructure

def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_view(path, text):
    """content.md and page.md: no line longer than a reader shows, so "from line N" works, and no
    data: payload (a megabyte of base64 is a picture, not text: its type, size and hash stay)."""
    write_text(path, answer.split_long_lines(short_data_uris(text)))


def replace_file(src, dst, tries=40):
    """os.replace that waits out Windows: a file another process has open for reading cannot be
    replaced, and the old code swallowed that and lost the write (cookies, found with four writers
    on two slow cores). Such a reader is done in milliseconds. Returns whether it went through."""
    for _ in range(tries):
        try:
            os.replace(src, dst)
            return True
        except PermissionError:
            time.sleep(0.025)
    try:
        os.unlink(src)
    except OSError:
        pass
    return False


def write_bytes(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def trace(event, **kw):
    """One event of the read: in the debug log with READ_PAGE_DEBUG (debuglog.py, whole values),
    and one greppable line on stderr with READ_PAGE_TRACE=1 (RP_LOG event=<name> k=v k=v)."""
    if debuglog.enabled():
        debuglog.log("event", name=str(event), **{k: (debuglog.mask_url(v) if k in ("url", "target", "final") else v)
                                                  for k, v in kw.items()})
    if not os.environ.get("READ_PAGE_TRACE"):
        return
    parts = ["RP_LOG", "event=" + str(event)]
    for k, v in kw.items():
        s = str(v).replace("\n", " ").replace("\t", " ")[:120]
        parts.append("%s=%s" % (k, s))
    sys.stderr.write(" ".join(parts) + "\n")
    sys.stderr.flush()


def lib_versions():
    """The versions of the libraries a read leans on, for the debug log (importlib.metadata)."""
    out = {}
    try:
        from importlib import metadata as md
    except ImportError:                                       # Python 3.7: not worth a backport
        return out
    for name in ("curl_cffi", "patchright", "playwright", "trafilatura", "readability-lxml", "html2text",
                 "lxml", "pymupdf", "pymupdf4llm", "markitdown", "pillow", "yt-dlp"):
        try:
            out[name] = md.version(name)
        except Exception:                                     # noqa: BLE001
            pass
    return out


def now():
    return time.time()


def cache_root():
    """Where results live: READ_PAGE_CACHE, else the OS temp folder (tempfile.gettempdir()).

    One URL gets one directory, named by sha1(url|BUILD): different documents never share a
    folder, the same page keeps its files for 15 minutes, and prune_cache() drops entries older
    than a day. Flags are not part of the name: the same page read with and without pictures is
    the same content, and pictures already on disk are a bonus, not a different answer.

    The cache holds page text and session cookies, so on a shared /tmp it belongs to one user:
    `read-page-<uid>`, 0700, files 0600 (main() sets the umask). A folder of that name that is a
    link, belongs to someone else or cannot be closed is not used: this run gets a fresh private
    folder instead (mkdtemp), so nobody can read our pages or plant an answer in them. Windows
    keeps it in the user's own temp folder.
    """
    base = os.environ.get("READ_PAGE_CACHE")
    if base:
        os.makedirs(base, mode=0o700, exist_ok=True)
        return base
    return _own_root()


_OWN_ROOT = []


def _own_root():
    if _OWN_ROOT and os.path.isdir(_OWN_ROOT[0]):
        return _OWN_ROOT[0]
    tmp = tempfile.gettempdir()
    if os.name != "posix":
        root = os.path.join(tmp, "read-page")
        os.makedirs(root, exist_ok=True)
    else:
        uid = os.getuid()
        root = os.path.join(tmp, "read-page-%d" % uid)
        try:
            os.makedirs(root, mode=0o700, exist_ok=True)
            st = os.lstat(root)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != uid:
                raise PermissionError("not this user's folder")
            if stat.S_IMODE(st.st_mode) & 0o077:
                os.chmod(root, 0o700)
        except OSError:
            root = tempfile.mkdtemp(prefix="read-page-")
    _OWN_ROOT[:] = [root]
    return root


def foreign_binary(path):
    """A tool that belongs to the other side of WSL.

    WSL puts the Windows PATH on ours, so `which defuddle` finds the npm shim under /mnt/c. A
    Windows process started from Linux costs its full timeout (measured: 20 s for defuddle, every
    call) and maps paths differently. A native run must use native tools.
    """
    p = str(path or "").replace("\\", "/").lower()
    if not p:
        return False
    wsl = bool(os.environ.get("WSL_DISTRO_NAME"))
    if not wsl:
        try:
            wsl = "microsoft" in os.uname().release.lower()
        except (AttributeError, OSError):
            wsl = False
    if not wsl:
        return False
    return p.startswith("/mnt/") or p.endswith((".exe", ".cmd", ".bat", ".ps1"))


def cmd_line(cmd):
    """The command line cmd.exe runs for a .cmd/.bat and its arguments, or None where an argument cannot
    be passed through it safely. list2cmdline quotes for the C runtime, which is not cmd.exe's reading:
    an `&`, `|`, `<`, `>`, `^` or a parenthesis outside quotes is cmd's own syntax (a profile folder with
    an `&` in its name split the command). Such an argument goes in quotes; a `%` (expanded even inside
    them) or a quote or a line break in an argument has no safe way through, and the call is refused."""
    out = []
    for a in (str(x) for x in cmd):
        if any(c in a for c in '%"\r\n\0'):
            return None
        q = subprocess.list2cmdline([a])
        if re.search(r"[&|<>^()!,;=]", a) and not q.startswith('"'):
            q = '"%s"' % (a + "\\" * (len(a) - len(a.rstrip("\\"))))     # a trailing \ before the quote doubles
        out.append(q)
    return " ".join(out)


def ascii_stage_root():
    """An ASCII-only folder of this user's own for programs that take their arguments in the ANSI code page
    (pdftotext, tesseract, lynx): under the cache when its path is ASCII, else its 8.3 short name, else the
    environment's folder (READ_PAGE_HOME) when its path is ASCII. "" when there is none (none of them is ASCII
    and writable): a document is never copied into a folder the machine's other users read (C:\\Users\\Public,
    C:\\ProgramData), and the program then gets the path as it is. Off Windows (for a library that takes a path
    as UTF-8, lib_paths): under the cache, else under this user's own folder in the temp folder (_own_root), the
    first whose path's bytes are its UTF-8."""
    if os.name != "nt":
        for root in (cache_root(), _own_root()):
            if not ownenv.utf8_clean(root):
                continue
            folder = os.path.join(root, "tmp")
            try:
                os.makedirs(folder, mode=0o700, exist_ok=True)
                return folder
            except OSError:
                continue
        return ""
    base = cache_root()
    roots = [base, ownenv.ascii_path(base)]
    if sys.version_info >= (3, 13):
        # READ_PAGE_HOME may be a folder every user reads (C:\read-page inherits C:\'s rights): only where
        # os.mkdir(..., 0o700) makes each stage folder this user's alone (Python 3.13 and later do on Windows)
        roots.append(os.path.join(ownenv.home(), "cache"))
    for root in roots:
        if not root or not root.isascii():
            continue
        folder = os.path.join(root, "tmp")
        try:
            os.makedirs(folder, exist_ok=True)
            return folder
        except OSError:
            continue
    return ""


STAGE_STALE = 3600              # a stage folder untouched this long belongs to a read that is gone


def prune_stages(folder, older=STAGE_STALE):
    """Remove the stage folders under `folder` (cache/tmp) that nothing has touched for an hour: a read killed
    while a document was staged left its copy there, and nothing else ever removed it. A folder counts as
    touched when it or a file in it changed (a download in progress writes its body)."""
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        p = os.path.join(folder, name)
        try:
            if not os.path.isdir(p) or os.path.islink(p):
                continue
            newest = max([os.path.getmtime(p)] + [e.stat().st_mtime for e in os.scandir(p)])
            if now() - newest > older:
                _rmtree_own(p)
        except OSError:
            continue


def _rmtree_own(path):
    """Remove a stage folder, a read-only file of ours in it too (a copy: one link) - never changing a file that
    has another name somewhere (a link to the user's own document keeps its attributes)."""
    for top, dirs, files in os.walk(path, topdown=False):
        for name in files:
            p = os.path.join(top, name)
            try:
                os.unlink(p)
            except OSError:
                try:
                    if os.stat(p).st_nlink == 1:
                        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
                        os.unlink(p)
                except OSError:
                    pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(top, name))
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def narrow_paths(ins, outs=()):
    """(inputs, outputs, done) for a program that takes narrow arguments: on Windows a path with a character outside
    ASCII - under a profile named in Chinese, Cyrillic, or a name whose second byte in Big5 is 0x5C -
    is read by such a program in the ANSI code page, or not at all. Each such input is linked (copied when it is
    read-only, or when it cannot be linked) into an ASCII folder of the user's alone under a name of ours, each such
    output is a name in it; `done()` moves the outputs to their real places and removes the folder, and a folder
    a killed read left is pruned. Anywhere else, or when every path is ASCII, nothing changes."""
    if os.name != "nt":
        return [str(x) for x in ins], [str(x) for x in outs], (lambda: None)
    return _staged(ins, outs, str.isascii)


def lib_paths(ins, outs=()):
    """narrow_paths for a library that takes a path as UTF-8 - PyMuPDF, and our readers' processes, which get it in
    JSON: under a POSIX locale of another code set (LC_ALL=zh_CN.GBK) a name outside ASCII is that code set's bytes,
    which such a library cannot open (PyMuPDF: "Failed to open file", in Python's UTF-8 mode or not; KNOWN-ISSUES
    175). Such an input is linked or copied under a name of ours into a folder whose path is ASCII; anywhere else -
    Windows, a UTF-8 locale - nothing changes."""
    return _staged(ins, outs, ownenv.utf8_clean)


@contextlib.contextmanager
def lib_path(path):
    """`with lib_path(p) as at:` - `at` is a path to p's file that a library taking UTF-8 opens (lib_paths), for
    the block's length."""
    ins, _outs, done = lib_paths([path])
    try:
        yield ins[0]
    finally:
        done()


def _staged(ins, outs, fits):
    ins, outs = [str(x) for x in ins], [str(x) for x in outs]
    if all(fits(x) for x in ins + outs):
        return ins, outs, (lambda: None)
    root = ascii_stage_root()
    if not root:
        return ins, outs, (lambda: None)
    prune_stages(root)
    stage = os.path.join(root, os.urandom(6).hex())
    try:
        os.mkdir(stage, 0o700)
    except OSError:
        return ins, outs, (lambda: None)
    new_ins, new_outs = [], []
    for i, x in enumerate(ins):
        if fits(x):
            new_ins.append(x)
            continue
        ext = os.path.splitext(x)[1]
        dst = os.path.join(stage, "in%d%s" % (i, ext if ext.isascii() else ""))
        try:
            if not os.access(x, os.W_OK):
                # a read-only file (a CD's, a mail's, some archives'): a link would share its read-only
                # attribute, which no rmtree removes - the stage stayed, the document with it
                raise OSError("read-only: copied")
            os.link(x, dst)
        except OSError:
            try:
                shutil.copyfile(x, dst)
            except OSError:
                dst = x
        new_ins.append(dst)
    for j, x in enumerate(outs):
        ext = os.path.splitext(x)[1]
        new_outs.append(x if fits(x) else os.path.join(stage, "out%d%s" % (j, ext if ext.isascii() else "")))

    def done():
        for real, staged in zip(outs, new_outs):
            if staged != real and os.path.exists(staged):
                try:
                    replace_file(staged, real)
                except OSError as e:
                    debuglog.exc("narrow paths: output", e)
        _rmtree_own(stage)
    return new_ins, new_outs, done


def run_tool(cmd, timeout=120):
    """Run a converter. On Windows a .cmd/.bat needs cmd.exe (its arguments quoted for cmd, cmd_line); a
    real program gets an argv list, so a path with a quote or an ampersand can never become part of a
    command line."""
    first = str(cmd[0]).lower()
    if os.name == "nt" and first.endswith((".cmd", ".bat")):
        line = cmd_line(cmd)
        if line is None:
            return -1, b"", b"an argument cmd.exe cannot be given safely (a %, a quote or a line break)"
        return run(line, timeout=timeout, shell=True)
    return run([str(x) for x in cmd], timeout=timeout)


def run(cmd, timeout=120, shell=False, input_bytes=None, cwd=None):
    """Run a command; never raise on a non-zero exit.

    The timeout has to bound the call for real: a browser or a converter that spawns children
    keeps the output pipe open, so `subprocess.run(timeout=)` can wait far past the timeout while
    draining. The child is put in its own process group and the whole group is killed.
    """
    popen_kw = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    try:
        # a Python program among them (yt-dlp, markitdown, an engine's own command) writes UTF-8, which is what
        # its output is read as: else it writes the ANSI code page on Windows, a locale's on POSIX (GBK)
        p = subprocess.Popen(cmd, shell=shell, cwd=cwd, env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                             stdin=subprocess.PIPE if input_bytes is not None else None,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kw)
    except Exception as e:                                    # noqa: BLE001
        debuglog.exc("run: process start", e)
        return -1, b"", str(e).encode()
    _CHILDREN.add(p)
    try:
        out, err = p.communicate(input_bytes, timeout=timeout)
        return p.returncode, out or b"", err or b""
    except subprocess.TimeoutExpired:
        kill_tree(p)
        try:
            out, err = p.communicate(timeout=3)
            return -1, out or b"", err or b""
        except Exception:                                     # noqa: BLE001
            return -1, b"", b"timeout after %ss" % str(timeout).encode()
    finally:
        _CHILDREN.discard(p)


# The processes run() started, each in a session of its own (so a timeout kills its whole tree).
# A session of its own is also out of reach of a kill aimed at our process group: on SIGTERM -
# the MCP server cancelling a call - each one's tree is killed here before we go.
_CHILDREN = set()


def _on_term(signum, frame):
    for p in list(_CHILDREN):
        kill_tree(p)
    os._exit(143)


def kill_tree(p):
    """Kill the process and everything it started."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(p.pid), 9)
    except Exception:                                         # noqa: BLE001
        try:
            p.kill()
        except Exception:                                     # noqa: BLE001
            pass


_WHICH = {}


def which(name):
    """A tool's path, looked up once per process for a given PATH: on Windows each lookup walks
    every PATH folder with every PATHEXT ending, and a read asked ~13 times (0.2 s on a fast machine,
    about 0.8 s on a weak laptop)."""
    key = (name, os.environ.get("PATH", ""), os.environ.get("PATHEXT", ""))
    if key not in _WHICH:
        _WHICH[key] = _which(name)
    return _WHICH[key]


def _which(name):
    p = shutil.which(name)
    if p and not foreign_binary(p):
        return p
    if p:
        p = ""                                   # found, but it belongs to the other world
    if os.name == "nt":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        dirs = [os.path.join(os.environ.get("APPDATA", ""), "npm"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links"),
                os.path.join(os.environ.get("APPDATA", ""), "Python",
                             "Python3%d%d" % sys.version_info[:2], "Scripts"),
                os.path.join(pf, "Tesseract-OCR"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR")]
        exts = (".exe", ".cmd", ".bat")
    else:
        # npm-global, pip --user, homebrew, local installs: often not on PATH in GUI sessions
        dirs = [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/bin"),
                "/opt/homebrew/bin", "/usr/local/bin", "/snap/bin"]
        exts = ("",)
    for d in dirs:
        for ext in exts:
            c = os.path.join(d, name + ext)
            if d and os.path.isfile(c):
                return c
    return None


def browsers():
    """Every Chromium-family browser on this machine, in the order we would try them.

    One entry per program that is really on disk: a Playwright channel ("chrome", "msedge",
    their beta/dev/canary) is listed only when its executable exists - before, every channel was
    listed, so a machine without a browser reported one, and Chrome came twice (as the "chrome"
    channel and as its own path), which doubled the browser step. channel= is what Playwright is
    given; path= is the same program, for a direct run.
    """
    out, seen = [], set()

    def add(name, path=None, channel=None, kind="path"):
        if not path or not os.path.exists(path) or (kind == "path" and not os.path.isfile(path)):
            return
        if foreign_binary(path):
            return
        real = os.path.normcase(os.path.realpath(path))
        if real in seen:
            return
        seen.add(real)
        out.append({"name": name, "path": path, "channel": channel,
                    "kind": "channel" if channel else kind})

    def first(*paths):
        return next((p for p in paths if p and os.path.isfile(p)), None)

    env = os.environ.get("READ_PAGE_CHROME")
    if env and os.path.isfile(env):
        add("env", path=env)

    if os.name == "nt":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        lad = os.environ.get("LOCALAPPDATA", "")

        def win(vendor, product, exe, *roots):
            return first(*(os.path.join(r, vendor, product, "Application", exe) for r in roots if r))

        add("chrome", win("Google", "Chrome", "chrome.exe", pf, pf86, lad), channel="chrome")
        add("edge", win("Microsoft", "Edge", "msedge.exe", pf86, pf), channel="msedge")
        add("brave", os.path.join(pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"))
        add("vivaldi", os.path.join(lad, "Vivaldi", "Application", "vivaldi.exe"))
        add("opera", os.path.join(lad, "Programs", "Opera", "opera.exe"))
        add("opera-gx", os.path.join(lad, "Programs", "Opera GX", "opera.exe"))
        add("yandex", os.path.join(lad, "Yandex", "YandexBrowser", "Application", "browser.exe"))
        add("chrome-beta", win("Google", "Chrome Beta", "chrome.exe", pf, lad), channel="chrome-beta")
        add("chrome-dev", win("Google", "Chrome Dev", "chrome.exe", pf, lad), channel="chrome-dev")
        add("chrome-canary", win("Google", "Chrome SxS", "chrome.exe", lad), channel="chrome-canary")
        add("msedge-beta", win("Microsoft", "Edge Beta", "msedge.exe", pf86, pf), channel="msedge-beta")
        add("msedge-dev", win("Microsoft", "Edge Dev", "msedge.exe", pf86, pf), channel="msedge-dev")
        add("msedge-canary", win("Microsoft", "Edge SxS", "msedge.exe", lad), channel="msedge-canary")
    elif sys.platform == "darwin":
        def mac(app):
            return "/Applications/%s.app/Contents/MacOS/%s" % (app, app)

        add("chrome", mac("Google Chrome"), channel="chrome")
        add("edge", mac("Microsoft Edge"), channel="msedge")
        for name, app in (("brave", "Brave Browser"), ("vivaldi", "Vivaldi"), ("opera", "Opera"),
                          ("yandex", "Yandex"), ("chromium", "Chromium")):
            add(name, mac(app))
        add("chrome-beta", mac("Google Chrome Beta"), channel="chrome-beta")
        add("chrome-canary", mac("Google Chrome Canary"), channel="chrome-canary")
    else:
        add("chrome", first(shutil.which("google-chrome"), shutil.which("google-chrome-stable"),
                            "/opt/google/chrome/chrome"), channel="chrome")
        add("edge", first(shutil.which("microsoft-edge"), shutil.which("microsoft-edge-stable"),
                          "/opt/microsoft/msedge/msedge"), channel="msedge")
        for n in ("chromium", "chromium-browser", "brave-browser", "vivaldi", "opera", "yandex-browser"):
            add(n, shutil.which(n))
        for n, p in (("chromium-snap", "/snap/bin/chromium"),
                     ("chrome-flatpak", "/var/lib/flatpak/exports/bin/com.google.Chrome"),
                     ("chromium-flatpak", "/var/lib/flatpak/exports/bin/org.chromium.Chromium")):
            add(n, p)

    # Playwright/Patchright's own download, when nothing else is installed. Current builds are
    # Chrome for Testing (chrome-win64, chrome-linux64, chrome-mac-arm64/...); older ones and
    # Linux arm64 kept chrome-win, chrome-linux and chrome-mac. Only the old names were looked
    # for, so a machine with Playwright's Chromium alone had no browser (found 2026-11-05).
    pw_dirs = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "",
               os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
               os.path.expanduser("~/.cache/ms-playwright"),
               os.path.expanduser("~/Library/Caches/ms-playwright")]
    cft = "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    for base in pw_dirs:
        if base in ("", "0") or not os.path.isdir(base):
            continue
        for d in sorted(os.listdir(base), reverse=True):
            if d.startswith("chromium-"):
                for exe in ("chrome-win64/chrome.exe", "chrome-win/chrome.exe",
                            "chrome-linux64/chrome", "chrome-linux-arm64/chrome", "chrome-linux/chrome",
                            "chrome-mac-arm64/" + cft, "chrome-mac-x64/" + cft,
                            "chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
                    p = os.path.join(base, d, exe)
                    if os.path.isfile(p):
                        add("playwright-bundled", p)
            if d.startswith("webkit-") and sys.platform == "darwin":
                add("webkit", os.path.join(base, d), kind="webkit")      # Playwright's own WebKit
    for base in pw_dirs:                  # the headless shell last: a text-only Chromium
        if base in ("", "0") or not os.path.isdir(base):
            continue
        for d in sorted(os.listdir(base), reverse=True):
            if d.startswith("chromium_headless_shell-"):
                for sub in ("chrome-headless-shell-win64", "chrome-headless-shell-linux64",
                            "chrome-headless-shell-linux-arm64", "chrome-headless-shell-mac-arm64",
                            "chrome-headless-shell-mac-x64", "chrome-linux"):
                    for exe in ("chrome-headless-shell.exe", "chrome-headless-shell", "headless_shell"):
                        p = os.path.join(base, d, sub, exe)
                        if os.path.isfile(p):
                            add("playwright-shell", p)
    return out


CAPS_TTL = 3600                    # an hour; a change on PATH, in site-packages or tessdata at once
READER_KEY_NAMES = ("FIRECRAWL_API_KEY", "JINA_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY")


_CAPS_RUN = {}            # this run's caps(): checking the kept one costs a PATH walk (3 ms)


def caps(fresh=False):
    """Which engines this machine has. Asking costs ~0.3 s on Windows (every tool name x every
    PATH folder x every PATHEXT ending), so the answer is kept for an hour - but only while
    nothing it was read from changed: PATH, the modification time of every PATH folder, the
    site-packages folders, the Python, the tessdata folder. An install changes one of those, so
    the next run sees it; that is what the old day-long cache got wrong after `pip install
    curl_cffi` or a tesseract language pack. The setup report and --caps always ask fresh."""
    path = os.path.join(cache_root(), "caps.json")
    if not fresh:
        try:
            with open(path, encoding="utf-8") as fh:
                kept = json.load(fh)
            d = kept.get("caps") or {}
            if (now() - float(kept.get("at") or 0) < CAPS_TTL and kept.get("key") == _caps_key(d)
                    and all(os.path.exists(b.get("path") or "") for b in d.get("browsers") or [])):
                d["keys"] = _keys_now()            # a key exported a minute ago counts
                return d
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    d = _caps_now()
    try:
        tmp = path + ".%d.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"at": now(), "key": _caps_key(d), "caps": d}, fh)
        replace_file(tmp, path)
    except OSError:
        pass
    return d


def _keys_now():
    return {k: bool(os.environ.get(k)) for k in READER_KEY_NAMES}


def _caps_key(d):
    """What caps() was read from; a change in any of it means something was installed."""
    import site
    import sysconfig
    parts = [sys.executable, sys.version, os.environ.get("PATH", ""), os.environ.get("PATHEXT", ""),
             os.environ.get("TESSDATA_PREFIX", ""), os.environ.get("READ_PAGE_OCR_LANGS", ""),
             os.environ.get("READ_PAGE_SKIP", "")]
    dirs = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    paths = sysconfig.get_paths()
    dirs += [paths.get("purelib") or "", paths.get("platlib") or ""]
    try:
        dirs.append(site.getusersitepackages())
    except Exception:                                         # noqa: BLE001
        pass
    if (d or {}).get("tessdata"):
        dirs.append(d["tessdata"])
    for p in dirs:
        try:
            parts.append("%s=%d" % (p, os.stat(p).st_mtime_ns))
        except OSError:
            parts.append(p + "=-")
    return hashlib.sha1("\n".join(parts).encode("utf-8", "replace")).hexdigest()


def _caps_now():
    """Which engines this machine has, asked now."""
    import importlib.util as u

    def have(mod):
        try:
            return u.find_spec(mod) is not None
        except Exception:                                     # noqa: BLE001
            return False

    found = {}
    for name in ("defuddle", "markitdown", "pandoc", "pdftotext", "yt-dlp", "curl", "tesseract", "lynx", "w3m"):
        if name in ("markitdown", "pandoc") and name in SKIP:
            continue                                      # READ_PAGE_SKIP: the converter is not there
        p = which(name)                                   # once a name: each costs a PATH walk
        if p:
            found[name] = p
    langs = tesseract_langs(found.get("tesseract")) if found.get("tesseract") else []
    libs = {m: have(m) for m in ("trafilatura", "html2text", "pymupdf", "curl_cffi", "patchright", "playwright",
                                 "markdownify", "readability", "youtube_transcript_api", "PIL", "tesserocr",
                                 "pymupdf4llm", "onnxruntime")}
    ocr_error = ""
    if libs["tesserocr"]:
        # tesserocr carries tesseract itself; its languages are the packs in READ_PAGE_TESSDATA
        # (--setup's tessdata). It counts only once tesseract has started on one of them: a path
        # it cannot open (Windows, outside ASCII) or a damaged pack lists fine and reads nothing
        _mod, _where, packs, ocr_error = _tess_ready()
        if _mod is None:
            libs["tesserocr"] = False
        elif packs:
            _TESSDATA["dir"] = os.environ.get("READ_PAGE_TESSDATA") or _where
            langs = sorted(set(langs) | set(packs))
    d = {
        "at": now(),
        "python": sys.version.split()[0],
        "libs": libs,
        "ocr_langs": langs,
        "ocr_error": ocr_error,
        "tessdata": _TESSDATA.get("dir") or "",
        "cli": found,
        "browsers": browsers(),
        "keys": _keys_now(),
    }
    d["chrome"] = next((b["path"] for b in d["browsers"] if b.get("path")), None)
    return d


def os_install(what):
    """The command a user on *this* OS would actually type, not a Windows line everywhere: winget, brew,
    or the Linux's own package manager (ownenv.system_install)."""
    return ownenv.system_install(what)


SETUP = "readpage.py --setup"


def setup_rows(c):
    """(name, ok, fix, gain) for every optional engine: the single source of the setup report.

    tests/setup_audit.py reads this list, so an engine cannot be detected here and forgotten in
    the report, or recommended there and never detected - the two failures this table exists to
    prevent. `gain` says what the engine buys, never that it is required. ok is None for a
    fallback the engines here make unneeded (lynx beside the extractors, pdftotext beside pymupdf).
    The fix is `readpage.py --setup` for whatever it installs on this machine, else
    the machine's own command; what the last --setup could not do names its own (ownenv.fix).
    """
    libs, cli = c["libs"], c["cli"]
    brs = c.get("browsers") or []
    driver = bool(libs.get("patchright") or libs.get("playwright"))
    langs = [x for x in (c.get("ocr_langs") or []) if x != "osd"]
    tess = bool(cli.get("tesseract") or libs.get("tesserocr"))
    fix = ownenv.fix
    if not brs:
        bfix = "%s, then pip install patchright" % os_install("chromium")
    elif not driver:
        bfix = "pip install patchright"          # a Chromium is already on the machine
    else:
        bfix = ""
    extractors = bool(cli.get("defuddle") or libs.get("trafilatura") or libs.get("readability"))
    rows = [
        ("curl", bool(cli.get("curl")), os_install("curl"),
         "the last-resort fetch when nothing else answers"),
        ("curl_cffi", bool(libs.get("curl_cffi")), fix("curl_cffi", "pip install curl_cffi"),
         "passes TLS walls (npm, Medium, Reddit); about 3x faster"),
        ("defuddle", bool(cli.get("defuddle")), fix("defuddle", "npm install -g defuddle"),
         "best text on docs pages; keeps picture positions"),
        ("trafilatura", bool(libs.get("trafilatura")), fix("trafilatura", "pip install trafilatura"),
         "a second extractor to compare against"),
        ("html2text", bool(libs.get("html2text")), fix("html2text", "pip install html2text"),
         "full-page fallback when the clean ones come back short"),
        ("readability", bool(libs.get("readability")), fix("readability", "pip install readability-lxml"),
         "a light second extractor when trafilatura is not there"),
        ("lynx", True if (cli.get("lynx") or cli.get("w3m")) else None if extractors else False,
         os_install("lynx"), "a text-only render of a hostile page, where no extractor is"),
        ("browser", bool(brs) and driver, fix("browser", bfix) if bfix else "",
         "JavaScript pages, hash routes, and the second chance for late data"),
        ("pymupdf", bool(libs.get("pymupdf")), fix("pymupdf", "pip install pymupdf"),
         "PDF text with layout, and the scanned-PDF path; SVG to PNG for MCP inline_images"),
        # the model is onnxruntime's too: without it pymupdf4llm imports and lays out nothing
        ("pymupdf4llm", bool(libs.get("pymupdf4llm")) and libs.get("onnxruntime") is not False,
         fix("pymupdf4llm", "pip install pymupdf4llm" if not libs.get("pymupdf4llm") else "pip install onnxruntime"),
         "a PDF's tables as tables (a small layout model); --alternate: a PDF as Markdown with headings"),
        # Pillow is not built in (markitdown[all] brings it through python-pptx)
        ("pillow", bool(libs.get("PIL")), fix("pillow", "pip install pillow"),
         "MCP inline_images: GIF, WebP, AVIF and BMP as PNG, big pictures scaled to 1 568 px"),
        # neither markitdown nor pandoc (2026-11-21) is recommended any more: the office readers and
        # our EPUB, ODT and RTF readers read what they did, and better - one on the machine is still
        # the last resort for an office file, never a row of its own
        ("pdftotext", True if cli.get("pdftotext") else None if libs.get("pymupdf") else False,
         os_install("poppler"), "PDF text on machines without pymupdf"),
        ("tesseract", tess, (ownenv.ocr_fix(c.get("ocr_error")) if not tess else "")
         or fix("tesseract", os_install("tesseract")),
         ("OCR is installed but %s" % c["ocr_error"] if c.get("ocr_error") and not tess else
          "text from scanned pages, up to %d per document, and --ocr N" % OCR_MAX_PAGES)),
        ("yt-dlp", bool(cli.get("yt-dlp")), fix("yt-dlp", "pip install yt-dlp"),
         "video subtitles and thumbnails"),
    ]
    # the reader runs neither LibreOffice nor ffmpeg, so the report names neither;
    # a language pack beyond English is a real gap, but only where OCR works at all
    if tess:
        at = [n for n, _ok, _f, _g in rows].index("tesseract") + 1
        packs = fix("ocr-langs", "download a language's .traineddata (rus, deu, jpn...) into tessdata - "
                                 "github.com/tesseract-ocr/tessdata_fast - and name it in READ_PAGE_OCR_LANGS")
        if packs == SETUP:
            packs += (" --ocr-langs eng+hin (the packs every environment gets - fourteen languages, the vertical "
                      "packs of Chinese, Japanese and Korean, Fraktur's - and the user's own come by themselves; the "
                      "flag names others)")
        # after --setup the choice is made (English and the user's languages): the row is not a nag then
        rows.insert(at, ("ocr-langs", True if any(x != "eng" for x in langs) else (
            None if (ownenv.status().get("used") and ownenv.load().get("ocr_langs")) else False), packs,
                         "a scan in another language; tesseract alone reads English"))
    return rows


def setup_report(c):
    """`readpage.py` with no URL: what this machine can do, and what would make it stronger.

    `readpage.py --setup` installs every engine it can into the skill's own environment (a
    folder of the user's, no admin rights); running it is the user's consent, it asks nothing
    more. Apart from it the report names only what --setup cannot do here - the machine's own
    software, with this OS's command - and keys, which are always the user's own. Every line is
    measured, not promised.
    """
    rows = setup_rows(c)
    have = [name for name, ok, _f, _g in rows if ok]
    miss = [(name, fix, gain) for name, ok, fix, gain in rows if ok is False and fix]
    brs = c.get("browsers") or []
    langs = [x for x in (c.get("ocr_langs") or []) if x != "osd"]
    keys = c["keys"]
    env = ownenv.status()
    info = ownenv.load(env.get("home") or ownenv.home())

    lines = ["read-page %s (schema %d) - no URL given, so this is the setup report"
             % (VERSION, SCHEMA),
             "%s - python %s - cache %s"
             % ({"nt": "windows", "darwin": "macos"}.get(
                 "nt" if os.name == "nt" else sys.platform, "linux"), c["python"], cache_root())]
    where = env.get("home") or ownenv.home()
    if env.get("used"):
        lines.append("environment: %s, set up %s (%s brings it up to date; deleting the folder "
                     "removes it)" % (where, str(info.get("built") or "?")[:10], SETUP))
    elif info.get("python"):
        lines.append("environment: %s, not used: %s" % (where, env.get("why") or "?"))
    else:
        lines.append("environment: none yet - %s installs the engines below into %s (%s)"
                     % (SETUP, where, ownenv.SIZE_NOTE))
    disk = info.get("disk") if isinstance(info.get("disk"), dict) else {}
    if info.get("python") and disk.get("folder"):
        def size(n):
            return "%.1f GB" % (n / 1073741824.0) if n >= 1073741824 else "%d MB" % round(n / 1048576.0)
        cache = ("; uv's cache is %s%s" % (size(disk["cache"]), (", %s of it in no environment" % size(disk["cache_alone"]))
                                           if isinstance(disk.get("cache_alone"), int) else "")) if disk.get("cache") else ""
        lines.append("disk      : %s in the folder%s" % (size(disk["folder"]), cache))
    if info.get("python") and info.get("sources"):
        import envsetup                          # its redact: a setup.json of an older --setup showed more of an address
        lines.append("sources   : set on this machine when --setup last ran - they send it elsewhere than its defaults, or skip a check:")
        lines += ["  " + envsetup.redact(x) for x in info["sources"]]
    lines.append("")
    lines.append("works now : %s" % (", ".join(have) or "nothing beyond the standard library"))
    if brs:
        fams = sorted({(b.get("name") or "?").split("-")[0] for b in brs})
        lines.append("browsers  : %s" % ", ".join(fams))
    if langs:
        # osd: tesseract's script detection, which picks each scanned page's packs from these
        lines.append("ocr langs : %s%s" % ("+".join(langs), ", each scanned page read with its script's (osd)"
                                           if "osd" in (c.get("ocr_langs") or []) else ""))
    if miss:
        lines += ["", "worth adding - each line says what it buys, not a requirement:"]
        width = max(len(n) for n, _f, _g in miss)
        for name, fix, gain in miss:
            lines.append("  %-*s  %s" % (width, name, gain))
            lines.append("  %-*s  %s" % (width, "", fix))
    lines += ["", "keys (the user's own, never fetched or guessed):"]
    # the readers' order; only with --allow-external, and only when the page did not
    # read locally. Without any key the chain is Jina's free tier, then defuddle.md
    for name, what in (("FIRECRAWL_API_KEY", "first reader, one credit per page; opens the most walls"),
                       ("JINA_API_KEY", "second; works without a key, the key lifts its rate limit"),
                       ("EXA_API_KEY", "third, one credit per page"),
                       ("TAVILY_API_KEY", "fourth, one credit per page")):
        lines.append("  %-18s %s - %s" % (name, "set" if keys.get(name) else "not set", what))
    if any(fix.startswith(SETUP) for _n, fix, _g in miss):
        lines += ["", "%s installs every line that names it, at once, with no admin rights; ask the" % SETUP,
                  "user once - their yes is all it needs. Other lines are the machine's own software:",
                  "ask before running them. Then run this report again - it reads the machine fresh."]
    elif miss:
        lines += ["", "This report installs nothing. Ask the user before running any line above,",
                  "then run the report again - it reads the machine fresh every time."]
    else:
        lines += ["", "Nothing is missing. This report installs nothing; it reads the machine",
                  "fresh every time."]
    if env.get("used"):
        # the one thing that runs unasked: a video read refreshes yt-dlp ("installs by itself" was untrue)
        lines += ["A video read in the environment updates yt-dlp by itself, in the background, every three days;",
                  "READ_PAGE_SKIP=update turns that off."]
    return "\n".join(lines + [""])


CACHE_KEEP_HOURS = 24            # a page folder, pictures included


def prune_cache(pages_root, keep=CACHE_KEEP_HOURS):
    """Delete cache entries older than a day. Called at most once an hour.

    Results live in the cache directory (pictures included), so without this the folder grows by
    tens of megabytes per browsed news site and never shrinks.
    """
    stamp = os.path.join(pages_root, ".prune")
    try:
        if os.path.exists(stamp) and now() - os.path.getmtime(stamp) < 3600:
            return
        open(stamp, "w").close()
        for name in os.listdir(pages_root):
            d = os.path.join(pages_root, name)
            if not os.path.isdir(d):
                continue
            try:
                if now() - os.path.getmtime(d) > keep * 3600:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                continue
        trace("cache.prune", dir=pages_root, keep_hours=keep)
        drop_old_picture_stores()
        prune_stages(os.path.join(cache_root(), "tmp"))      # what a killed read left staged
    except Exception as _dbg_e:                                          # noqa: BLE001
        debuglog.exc("cache prune", _dbg_e)


def drop_old_picture_stores():
    """0.4 kept every site's pictures for 7 days in hosts/<host>/assets. Pages share pictures by
    hard links now, so an old store is only disk space; the host folder stays, it
    holds the cookies."""
    root = os.path.join(cache_root(), "hosts")
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        shutil.rmtree(os.path.join(root, name, "assets"), ignore_errors=True)
        try:
            os.unlink(os.path.join(root, name, "assets.json"))
        except OSError:
            pass


def mode_key(allow_external=False, alternate=False, download=False, shots=0):
    """Which flags produced this answer. Stored in the manifest, not in the folder name.

    One URL keeps one folder: pictures from an earlier run are reused, so "read it again with
    images" costs one local pass, not a second download. A cached answer is only *served* when
    the flags that change the text match; otherwise the same folder is re-read in place.
    """
    return "%s|%s|%s|%s" % ("x" if allow_external else "-", "a" if alternate else "-",
                            "d" if download else "-", "s%d" % shots if shots else "-")


def page_dir(url):
    """pages/<host>-<key>: the pages of one site are found by their name, so a
    picture one of them downloaded is linked, not fetched again."""
    key = hashlib.sha1((url + "|" + str(BUILD)).encode()).hexdigest()[:16]
    return os.path.join(cache_root(), "pages", pictures.folder_prefix(host_of(url)) + "-" + key)


# outline.tsv and parts/ are 0.4 files: no longer written, still ours to clear from an old folder
ARTEFACTS = ("content.md", "page.md", "manifest.json", "outline.tsv", "img", "parts", "shots",
             "cookies.jar")


def prune_unreferenced(workdir, manifest):
    """After a re-read: delete our own files that the new manifest no longer references."""
    keep = {"manifest.json", "content.md", "page.md"}
    for p in (manifest.get("files") or {}).values():
        # a list too: a scan's pages (page-01.png ...) went at every read of a file on this machine, which is a
        # --refresh, while the manifest and the advice named them
        for x in (p if isinstance(p, list) else [p]):
            if isinstance(x, str):
                keep.add(os.path.basename(x))
    for e in (manifest.get("images") or []):
        if isinstance(e, dict) and e.get("file"):
            keep.add(e["file"].replace("/", os.sep))
    for name in os.listdir(workdir):
        p = os.path.join(workdir, name)
        # never guess by a `raw.*` mask: a user's own raw.txt is not ours to delete
        ours = (name.startswith("page-") or name in ("outline.tsv", "_pdf.txt", "_doc.md")
                or name.endswith(".part"))
        if os.path.isfile(p) and ours and name not in keep and within(workdir, p):
            try:
                os.unlink(p)
            except OSError:
                pass
    for sub in ("img", "parts"):
        d = os.path.join(workdir, sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            rel = (sub + "/" + name).replace("/", os.sep)
            if rel in keep:
                continue
            p = os.path.join(d, name)
            if os.path.isfile(p) and within(workdir, p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


PAGE_LOCK_SECONDS = 150    # the worst read is ~115 s; a second call for the same page waits for it


@contextlib.contextmanager
def file_lock(path, seconds=5.0):
    """An exclusive lock between processes on `path` (msvcrt on Windows, fcntl elsewhere). After
    `seconds` the work goes on without it: a lost update is better than a hung read."""
    fh, locked = None, False
    try:
        fh = open(path, "a+b")
        end = time.monotonic() + seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as e:
                # held by another process: wait. Locking not supported here (a network share, a
                # WSL /mnt drive): go on at once, never wait 150 s for a lock that cannot exist
                import errno
                held = isinstance(e, BlockingIOError) or e.errno in (
                    errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, getattr(errno, "EDEADLK", -1),
                    getattr(errno, "EDEADLOCK", -1))
                if not held or time.monotonic() > end:
                    break
                time.sleep(0.02)
    except OSError:
        pass
    try:
        yield locked
    finally:
        if fh is not None:
            if locked:
                try:
                    if os.name == "nt":
                        import msvcrt
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            fh.close()


_HELD = []


def hold_lock(path, seconds):
    """Take a lock until release_locks(), which main() calls whatever happens."""
    cm = file_lock(path, seconds)
    cm.__enter__()
    _HELD.append(cm)


def release_locks():
    while _HELD:
        try:
            _HELD.pop().__exit__(None, None, None)
        except Exception:                                     # noqa: BLE001
            pass


def within(root, path):
    """True when `path` really resolves inside `root` (symlinks cannot sneak a delete out)."""
    try:
        r = os.path.realpath(root)
        p = os.path.realpath(path)
        return p == r or p.startswith(r + os.sep)
    except OSError:
        return False


def reset_dir(workdir):
    """--refresh: the old answer must not survive, pictures included.

    Only files this skill wrote are removed. A previous manifest names them; without one, only
    the well-known artefact names go. `--dir` may point at a real folder with the user's own
    `raw.txt` in it - that file is not ours and stays.
    """
    ours = set()
    try:
        old = json.load(open(os.path.join(workdir, "manifest.json"), encoding="utf-8"))
        for p in (old.get("files") or {}).values():
            if isinstance(p, str):
                ours.add(os.path.basename(p))
        for e in (old.get("images") or []):
            if isinstance(e, dict) and e.get("file"):
                ours.add(os.path.basename(e["file"]))
        if isinstance(old.get("_raw_name"), str):
            ours.add(os.path.basename(old["_raw_name"]))
    except Exception:                                          # noqa: BLE001
        pass
    for name in ARTEFACTS:
        p = os.path.join(workdir, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.exists(p):
            try:
                os.unlink(p)
            except OSError:
                pass
    for name in list(ours) + ["_pdf.txt", "_doc.md"]:
        p = os.path.join(workdir, name)
        if os.path.isfile(p) and within(workdir, p):
            try:
                os.unlink(p)
            except OSError:
                pass


# what a repeat within 15 minutes may be served from the cache: real answers only. A network
# failure, a wall (often a rate limit), an error page or a stub may be gone a minute later
CACHED_STATUSES = ("ok", "media_only", "not_found", "login_required")
# an answer a reader or the archive gave because the live page did not answer or answered 5xx
RESCUED_TTL = 60


def cached(url, refresh):
    d = page_dir(url)
    meta_path = os.path.join(d, "manifest.json")
    if refresh or not os.path.isfile(meta_path):
        return None
    try:
        m = json.load(open(meta_path, encoding="utf-8"))
        if now() - m.get("_cached_at", 0) > CACHE_TTL:
            return None
        if m.get("status") not in CACHED_STATUSES:
            return None              # a failure is not an answer: the next call asks again
        if (m.get("signals") or {}).get("rescued_after") and now() - m.get("_cached_at", 0) > RESCUED_TTL:
            return None              # a rescue after a moment's failure: ask the live page again
        files = {}
        for k, v in (m.get("_files") or {}).items():
            if isinstance(v, list):
                files[k] = [os.path.join(d, x) for x in v if os.path.exists(os.path.join(d, x))]
            elif os.path.exists(os.path.join(d, v)):
                files[k] = os.path.join(d, v)
        m["files"] = files
        m["dir"] = d
        m["cache"] = "hit"
        return d, m
    except Exception as _dbg_e:                                         # noqa: BLE001
        debuglog.exc("cache read", _dbg_e)
        return None


def stamp_read(manifest):
    """The 15 minutes count from the read or a 304, not from the last time a copy was shown: a
    cached answer, a --from block or a picture top-up must not keep an old copy fresh forever."""
    if not (manifest.get("cache") == "hit" and manifest.get("_cached_at")):
        manifest["_cached_at"] = now()


def store_cache(workdir, manifest, url):
    """Keep the artifacts for 15 minutes so a follow-up call (another question) is free."""
    d = page_dir(url)
    try:
        os.makedirs(d, exist_ok=True)
        prune_cache(os.path.dirname(d))
        same = os.path.normcase(os.path.abspath(workdir)) == os.path.normcase(os.path.abspath(d))
        rel = {}
        for k, p in (manifest.get("files") or {}).items():
            if isinstance(p, list):
                # a list - a scan's pages, the screenshots in shots/ - each by its place in the folder (the list
                # stopped the whole step with a TypeError: nothing was kept)
                kept = []
                for x in p:
                    r = _cache_rel(workdir, x)
                    if r and not same:
                        os.makedirs(os.path.dirname(os.path.join(d, r)), exist_ok=True)
                        shutil.copyfile(x, os.path.join(d, r))
                    if r:
                        kept.append(r)
                rel[k] = kept
                continue
            if p and os.path.isfile(p):
                base = os.path.basename(p)
                if not same:
                    shutil.copyfile(p, os.path.join(d, base))
                rel[k] = base
        img = os.path.join(workdir, "img")
        if os.path.isdir(img) and not same:
            # hardlink when the cache and the workdir share a volume: a picture-heavy page copies
            # tens of megabytes, and the copy alone was 3-4 s of the answer (tomsguide, 30.10)
            dest = os.path.join(d, "img")
            os.makedirs(dest, exist_ok=True)
            for name in os.listdir(img):
                src_p, dst_p = os.path.join(img, name), os.path.join(dest, name)
                if os.path.exists(dst_p):
                    continue
                try:
                    os.link(src_p, dst_p)
                except OSError:
                    shutil.copyfile(src_p, dst_p)
        manifest["_files"] = rel
        manifest["_raw_name"] = rel.get("raw", "raw.bin")
        stamp_read(manifest)
        write_manifest(os.path.join(d, "manifest.json"), manifest)
    except Exception as _dbg_e:                                         # noqa: BLE001
        debuglog.exc("cache write", _dbg_e)


def _cache_rel(workdir, p):
    """A file of a read's folder as the cache keeps it: its place in the folder (shots/01.png), "" for one that is
    not there or not in it."""
    if not (isinstance(p, str) and os.path.isfile(p)):
        return ""
    try:
        r = os.path.relpath(os.path.abspath(p), os.path.abspath(workdir))
    except ValueError:                                  # another drive (Windows)
        return ""
    return "" if r == os.pardir or r.startswith(os.pardir + os.sep) or os.path.isabs(r) else r


def moved_files(files, src, dst):
    """A manifest's files for the folder `dst` that holds what `src` held: each at its place in `dst` where it is
    there (a list's - a scan's pages, the screenshots in shots/ - each; a list was a TypeError), else as it was."""
    def one(p):
        if not isinstance(p, str):
            return p
        q = os.path.join(dst, _cache_rel(src, p) or os.path.basename(p))
        return q if os.path.exists(q) else p
    return dict((k, [one(x) for x in v] if isinstance(v, list) else one(v)) for k, v in (files or {}).items())


_COOKIE_STATS = {"sent": 0, "stored": 0}       # per run, reported as signals.cookies
# per run: what each host's cookies were before this read touched them ("before": the names, by
# the host a request went to; "disk": the jar's entries - value, expiry -, by the host whose jar it
# is), the names this read stored that were not there ("new") and every name it stored ("set").
# A wall's own cookies are not a session: they are neither kept nor blamed (drop_wall_cookies).
_COOKIE_RUN = {"before": {}, "disk": {}, "new": {}, "set": {}}


def _cookie_run_reset():
    for part in _COOKIE_RUN.values():
        part.clear()


def host_of(url):
    """The URL's host, lower case, as the request names it (intl.host_ascii: punycode, escapes decoded): the one
    name its cookies, its cache folder and the network rule go by - a server sets a cookie for its punycode."""
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    if h and (not h.isascii() or "%" in h) and ":" not in h:
        h = intl.host_ascii(h) or h
    return h


def host_dir(url):
    host = host_of(url) or str(url).strip().lower()   # a bare host name is accepted too
    return os.path.join(cache_root(), "hosts", hashlib.sha1(host.encode()).hexdigest()[:16])


def cookie_paths(url):
    d = host_dir(url)
    return os.path.join(d, "cookies.json"), os.path.join(d, "cookies.txt")


def _host_chain(host):
    """The host and its parents, down to two labels. A cookie may be set one level up."""
    parts = [p for p in (host or "").split(".") if p]
    if len(parts) < 2:
        return [host]
    return [".".join(parts[i:]) for i in range(len(parts) - 2, -1, -1)]


def _domain_ok(host, dom):
    """RFC 6265 matching: the exact host, or a subdomain of the cookie's Domain."""
    if not dom:
        return True
    return host == dom or host.endswith("." + dom)


def _jar_read(host):
    """The stored jar of one host, in the current shape, whatever shape was on disk."""
    path = os.path.join(host_dir(host), "cookies.json")
    try:
        if now() - os.path.getmtime(path) > COOKIE_TTL:
            return {}
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return {}                                  # no jar for this host yet: the usual case
    except Exception as _dbg_e:                                          # noqa: BLE001
        debuglog.exc("cookies: jar read", _dbg_e)
        return {}
    items = raw.get("cookies") if isinstance(raw, dict) and "cookies" in raw else raw
    out = {}
    for name, v in (items or {}).items():
        if isinstance(v, dict):
            out[str(name)] = {"v": str(v.get("v", "")), "d": str(v.get("d") or ""),
                              "e": int(v.get("e") or 0), "p": str(v.get("p") or "/"),
                              "s": bool(v.get("s")), "h": host}
        else:                                    # 0.4.1 and older: a flat name -> value map
            out[str(name)] = {"v": str(v), "d": "", "e": 0, "p": "/", "s": False, "h": host}
    return out


def _jar_write(host, jar):
    d = host_dir(host)
    path = os.path.join(d, "cookies.json")
    try:
        os.makedirs(d, exist_ok=True)
        tmp = path + ".%d.%d.tmp" % (os.getpid(), threading.get_ident())   # never shared
        clean = {k: {kk: vv for kk, vv in e.items() if kk != "h"} for k, e in jar.items()}
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "cookies": clean}, fh)
        replace_file(tmp, path)               # a reader of the jar in another process is waited out
    except OSError:
        pass


def load_cookies(url):
    """Every cookie that applies to this host: its own plus the ones set higher up."""
    host = host_of(url)
    jar = {}
    for h in _host_chain(host):
        for name, e in _jar_read(h).items():
            if _domain_ok(host, e["d"] or e["h"]):
                jar[name] = e
    out = {k: e for k, e in jar.items() if e["v"] and not (e["e"] and e["e"] < now())}
    if host not in _COOKIE_RUN["before"]:
        # the first look of this read at the host: what it holds from earlier reads
        mine = set()
        for h in _host_chain(host):
            mine |= _COOKIE_RUN["new"].get(h, set())
        _COOKIE_RUN["before"][host] = set(out) - mine
    return out


def had_session():
    """This read sent cookies that an earlier read had stored (not the ones it got on the way)."""
    return any(_COOKIE_RUN["before"].values())


def save_cookies(url, jar, set_from=None):
    """Merge into the jar of the host that set the cookie (not the URL we started from).

    Two runs on one host would otherwise overwrite each other: the file is re-read and only
    the names we have are replaced.
    """
    host = host_of(set_from or url)
    if not host or not jar:
        return
    try:
        os.makedirs(host_dir(host), exist_ok=True)
    except OSError:
        pass
    # read, merge and write under one lock: MCP runs four reads at once, and two of them on
    # one site each wrote back the jar they had read, losing the other's cookies
    # 10 s: four processes saving 30 cookies each on two slow cores queued past 5 s
    with file_lock(os.path.join(host_dir(host), "cookies.lock"), seconds=10.0):
        disk = _jar_read(host)
        # the jar's entries before this read's first save: a wall that re-sets or expires one of
        # them is undone (drop_wall_cookies), not only a name it brought
        old = _COOKIE_RUN["disk"].setdefault(host, {k: dict(e) for k, e in disk.items()})
        _COOKIE_RUN["new"].setdefault(host, set()).update(n for n in jar if n not in old)
        _COOKIE_RUN["set"].setdefault(host, set()).update(jar)
        for name, e in jar.items():
            if not e.get("v") or (e.get("e") and e["e"] < now()):
                disk.pop(name, None)
            else:
                disk[name] = e
        live = {k: e for k, e in disk.items() if not (e["e"] and e["e"] < now())}
        _jar_write(host, live)
        # counted here, under the lock: a read of the jar outside it made another writer's
        # replace fail on Windows
        _COOKIE_STATS["stored"] = len(live) + sum(1 for h in _host_chain(host) if h != host for _ in _jar_read(h))


def drop_wall_cookies():
    """A read that ended at a wall keeps none of the cookies it got there: a challenge's own
    cookie is no session, and on the next read it looked like a stale one (the advice said
    --clear-cookies on 9 of 11 walled reads in a measured run, 2026-11-19). What the jars held before
    stays as it was - its values too: a wall that re-set the session's own cookie (sid=good to
    sid=anon; Cloudflare's __cf_bm comes with every answer) or expired it had the last word
    (2026-11-21). Only the names this read set are put back; another read's are left alone."""
    for host, names in list(_COOKIE_RUN["set"].items()):
        if not names:
            continue
        before = _COOKIE_RUN["disk"].get(host) or {}
        try:
            with file_lock(os.path.join(host_dir(host), "cookies.lock"), seconds=10.0):
                disk = _jar_read(host)
                live = dict(disk)
                for k in names:
                    if k in before:
                        live[k] = dict(before[k])     # the session as it was before the wall
                    else:
                        live.pop(k, None)             # the wall's own
                if live == disk:
                    continue
                if live:
                    _jar_write(host, live)
                else:
                    os.unlink(os.path.join(host_dir(host), "cookies.json"))
        except Exception as _dbg_e:                                         # noqa: BLE001
            debuglog.exc("cookies: a wall's own dropped", _dbg_e)
    _COOKIE_STATS["stored"] = 0


def cookie_header(jar):
    return "; ".join("%s=%s" % (k, e["v"]) for k, e in (jar or {}).items() if e.get("v"))


def cookies_for_url(url):
    """What we may send to this exact URL (host, path and scheme checked)."""
    p = urllib.parse.urlparse(url)
    return cookies_for(load_cookies(url), (p.hostname or ""), p.path or "/", p.scheme or "https")


def pw_cookies(url):
    """The site's stored cookies in the shape Playwright wants.

    A cookie that carried a Domain attribute goes in as `domain`, a host-only cookie as `url`:
    that is how Playwright tells "sent to subdomains too" from "this host only", which our jar
    keeps in `d` and `h`.
    """
    host = host_of(url)
    p = urllib.parse.urlparse(url)
    scheme = p.scheme or "https"
    netloc = p.netloc or host                     # keep the port: a cookie url must match it
    out = []
    for name, e in (cookies_for_url(url) or {}).items():
        dom = (e.get("d") or "").lstrip(".")
        if not dom and not host:
            continue
        exp = int(e.get("e") or 0)
        ck = {"name": name, "value": e.get("v") or "",
              "secure": bool(e.get("s")), "httpOnly": False}
        if dom:
            # a Domain cookie: Playwright needs domain *and* path, and no url
            ck["domain"] = dom
            ck["path"] = e.get("p") or "/"
        else:
            # host-only: Playwright takes it as a url, and then refuses a separate path
            ck["url"] = "%s://%s%s" % (scheme, netloc, e.get("p") or "/")
        if exp > int(now()):
            ck["expires"] = exp
        out.append(ck)
    return out


def save_browser_cookies(ctx, url):
    """Cookies the browser tier set go back into the same per-host jar as the HTTP tiers."""
    jar = {}
    try:
        for c in ctx.cookies() or []:
            if not c.get("name"):
                continue
            exp = int(float(c.get("expires") or 0))
            if exp and exp < now():                    # already expired: do not store it
                continue
            dom = str(c.get("domain") or "")
            jar[c["name"]] = {"v": c.get("value") or "",
                              "d": dom.lstrip(".") if dom.startswith(".") else "",
                              "e": exp, "p": c.get("path") or "/",
                              "s": bool(c.get("secure")), "h": host_of(url)}
    except Exception as _dbg_e:                                  # noqa: BLE001
        debuglog.exc("cookies: browser jar", _dbg_e)
        return 0
    if jar:
        try:
            save_cookies(url, jar, set_from=url)
        except Exception as _dbg_e:                              # noqa: BLE001
            debuglog.exc("cookies: browser save", _dbg_e)
            return 0
    return len(jar)


def cookies_for(jar, host, path="/", scheme="https"):
    """The subset of a jar that may be sent to this host, path and scheme."""
    out = {}
    for k, e in (jar or {}).items():
        if not e.get("v"):
            continue
        if not _domain_ok(host, e.get("d") or e.get("h") or ""):
            continue
        if not _path_ok(path, e.get("p") or "/"):
            continue
        if e.get("s") and scheme != "https":
            continue
        out[k] = e
    return out


def _path_ok(path, cpath):
    """RFC 6265 path match: equal, or a prefix that ends at a path separator."""
    p, c = path or "/", cpath or "/"
    if p == c:
        return True
    if not p.startswith(c):
        return False
    return c.endswith("/") or p[len(c):len(c) + 1] == "/"


def write_netscape(path, jar, host):
    """Hand the shared jar to plain curl (it has no json reader)."""
    lines = ["# Netscape HTTP Cookie File"]
    for name, e in (jar or {}).items():
        dom = e.get("d") or e.get("h") or host
        sub = "TRUE" if e.get("d") else "FALSE"
        lines.append("\t".join([("." + dom if sub == "TRUE" else dom), sub,
                                e.get("p") or "/", "TRUE" if e.get("s") else "FALSE",
                                str(max(0, int(e.get("e") or 0))), name, e.get("v", "")]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def read_netscape(path, host):
    """What curl wrote back, in our shape, so both HTTP tiers share one jar."""
    jar = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("#") or not line.strip():
                    continue
                f = line.rstrip("\n").split("\t")
                if len(f) < 7:
                    continue
                dom, sub, path, sec, exp, name, value = f[:7]
                dom = dom.strip().lstrip(".").lower()
                jar[name] = {"v": value, "d": dom if sub.strip().upper() == "TRUE" else "",
                             "e": int(exp) if exp.strip().isdigit() else 0,
                             "p": path or "/", "s": sec.strip().upper() == "TRUE", "h": host}
    except OSError:
        pass
    return jar


def clear_cookies(url):
    """Forget this site: the host's jar and the jars of its parents that may cover it."""
    host = host_of(url)
    for h in _host_chain(host):
        for p in cookie_paths("http://" + h + "/"):
            try:
                os.unlink(p)
            except OSError:
                pass


def load_manifest(workdir):
    try:
        with open(os.path.join(workdir, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                          # noqa: BLE001
        return {}


def write_manifest(path, m):
    """manifest.json: UTF-8, or escaped where it holds a path whose bytes are no UTF-8 - a folder named in GBK
    under a POSIX locale of that code set is a str with lone surrogates in Python's UTF-8 mode, which a file of
    UTF-8 cannot hold (the write failed, and the folder kept no manifest; KNOWN-ISSUES 175). The escapes read
    back as the same path."""
    text = json.dumps(m, ensure_ascii=False, indent=1)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(m, ensure_ascii=True, indent=1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def shown_paths(m):
    """The manifest an answer prints: its folder and files as the user's locale names them (ownenv.shown) - under
    zh_CN.GBK the folder `资料`, where the bytes printed as `????` (or the answer stopped: no UTF-8 holds them)."""
    out = dict(m)
    if isinstance(out.get("dir"), str):
        out["dir"] = ownenv.shown(out["dir"])
    if isinstance(out.get("files"), dict):
        out["files"] = dict((k, [ownenv.shown(x) for x in v] if isinstance(v, list) else ownenv.shown(v))
                            for k, v in out["files"].items())
    return out


def clear_text_artifacts(workdir):
    """A re-read in the same folder: the old text must not survive, the files may."""
    for name in ("content.md", "page.md", "outline.tsv"):
        p = os.path.join(workdir, name)
        if os.path.isfile(p):
            try:
                os.unlink(p)
            except OSError:
                pass
    shutil.rmtree(os.path.join(workdir, "parts"), ignore_errors=True)


def materialize(src, dst):
    """A cache hit while --dir asked for a folder: copy our artefacts there and use it."""
    os.makedirs(dst, exist_ok=True)
    for name in ("content.md", "page.md", "manifest.json"):
        p = os.path.join(src, name)
        if os.path.isfile(p):
            try:
                shutil.copyfile(p, os.path.join(dst, name))
            except OSError:
                pass
    for name in os.listdir(src):
        if name.startswith("raw.") or name.startswith("page-"):
            p = os.path.join(src, name)
            if os.path.isfile(p):
                try:
                    shutil.copyfile(p, os.path.join(dst, name))
                except OSError:
                    pass
    for sub in ("img", "parts", "shots"):         # shots/: the screenshots, which the cache keeps too
        s, d = os.path.join(src, sub), os.path.join(dst, sub)
        if os.path.isdir(s):
            os.makedirs(d, exist_ok=True)
            for name in os.listdir(s):
                try:
                    shutil.copyfile(os.path.join(s, name), os.path.join(d, name))
                except OSError:
                    pass
    return dst


# ---------------------------------------------------------------- fetching

def too_large_out(size, limit, what="file"):
    """A fetch result for a body over the cap: no body, both sizes, and the reason."""
    return {"too_large": True, "size": int(size or 0), "limit": int(limit or 0),
            "error": "the %s is %s, over the %s cap" % (what, human_bytes(int(size or 0)),
                                                       human_bytes(int(limit or 0)))}


WALL_HEADER_NAMES = ("cf-mitigated", "x-vercel-mitigated", "x-amzn-waf-action", "retry-after", "server")


def wall_headers(headers):
    """The response headers wall_signal() looks at, from any header object."""
    out = {}
    for name in WALL_HEADER_NAMES:
        try:
            v = headers.get(name)
        except Exception:                                      # noqa: BLE001
            v = None
        if v:
            out[name] = str(v)[:200]
    return out


DISK_FLOOR = 1024 ** 3                # a download stops when less than this is free
DISK_CHECK = 64 * 1024 * 1024         # bytes written between two looks at the free space


def disk_low(path):
    """True when the disk under `path` has less than DISK_FLOOR free (0 = unknown, not low)."""
    free = free_bytes(path)
    return 0 < free < DISK_FLOOR


def spool_to_file(chunks, dest_dir, keep_in_mem=None, state=None):
    """Write an iterable of chunks to a temp file; return (bytes|b"", path, size, head).

    Small bodies stay in memory; a big one is flushed to disk and never held whole. On disk the
    free space is looked at when the body first goes there and every 64 MB after: below 1 GB the
    download stops and `state["cut"]` says "disk" (--download has no size limit,
    only the disk has one).
    """
    keep = SPOOL_INMEM if keep_in_mem is None else keep_in_mem
    fd, path = tempfile.mkstemp(dir=dest_dir, suffix=".part")
    size, head, buf, on_disk, checked = 0, b"", [], False, 0
    fh = os.fdopen(fd, "wb")
    try:
        for chunk in chunks:
            if not chunk:
                continue
            if size < 512:
                head += chunk[:512 - size]
            size += len(chunk)
            if on_disk:
                fh.write(chunk)
            else:
                buf.append(chunk)
                if size > keep:
                    fh.write(b"".join(buf))
                    buf = []
                    on_disk = True
            if on_disk and size - checked >= (DISK_CHECK if checked else 0):
                checked = size
                if disk_low(dest_dir):
                    if state is not None:
                        state["cut"] = "disk"
                    break
    finally:
        fh.close()
    if not on_disk:
        os.unlink(path)
        return b"".join(buf), "", size, head
    return b"", path, size, head[:512]


def body_bytes(f, limit=None):
    """The body as bytes, reading from disk when the fetch spooled it."""
    if f.get("body"):
        return f["body"]
    path = f.get("path")
    if not path or not os.path.exists(path):
        return b""
    with open(path, "rb") as fh:
        return fh.read() if limit is None else fh.read(limit)


def take_body(f, dest):
    """Move the spooled body to `dest` (or write the bytes); return dest."""
    path = f.get("path")
    if path and os.path.exists(path):
        try:
            if os.path.exists(dest):
                os.unlink(dest)
            shutil.move(path, dest)
            f["path"] = ""
            return dest
        except OSError:
            shutil.copyfile(path, dest)
            try:
                os.unlink(path)
            except OSError:
                pass
            f["path"] = ""
            return dest
    write_bytes(dest, f.get("body") or b"")
    return dest


def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def download_limit(download):
    """--download means no size cap at all; without it one attempt stops at MAX_DOWNLOAD."""
    return None if download else MAX_DOWNLOAD


def _cffi_get(url, imp, accept=None, verify=True, download=False, headers=None, deadline=None):
    """One impersonated attempt. A seam, so a test can prove the rotation without a wall.

    With stream=True a (connect, read) tuple means "less than 1 byte a second for `read` s": a
    trickle never ends. So the read side is the speed floor instead - below 1 KB/s for 10 s in a
    row the transfer is cut and what arrived is kept - and the step's deadline bounds the rest
    (the reading loop checks it). --download lifts both: "take whatever the URL serves".
    """
    cr = curl_cffi_requests()
    left = HTTP_STEP_SECONDS if deadline is None else max(1.0, deadline - now())
    timeout = (min(HTTP_CONNECT_TIMEOUT, left), 86400)
    opts = {}
    if not download:
        try:
            from curl_cffi import CurlOpt
            opts = {CurlOpt.LOW_SPEED_LIMIT: HTTP_LOW_SPEED[0], CurlOpt.LOW_SPEED_TIME: HTTP_LOW_SPEED[1]}
            if deadline is not None:
                # curl itself ends the transfer at the step's end: the reading loop only looked at
                # the clock when a chunk came, so a slow server overran it by up to the floor's 10 s
                opts[CurlOpt.TIMEOUT_MS] = int(left * 1000)
        except ImportError:
            timeout = (min(HTTP_CONNECT_TIMEOUT, left), HTTP_LOW_SPEED[1])
    h = {"Accept": accept or ACCEPT}
    lang = intl.accept_language()            # "" for an English reader: the impersonation sends its own
    if lang:
        h["Accept-Language"] = lang
    h.update(headers or {})
    kw = {"curl_options": opts} if opts else {}
    return cr.get(intl.iri_to_uri(url), impersonate=imp, timeout=timeout, allow_redirects=False, verify=verify,
                  headers=h, stream=True, **kw)


def raw_header(headers, name):
    """A response header's value as the bytes that came over the wire (b"" when there is none):
    curl_cffi keeps them (`.raw`); http.client decodes them as Latin-1, which gives them back."""
    want = name.lower().encode("ascii")
    pairs = getattr(headers, "raw", None)
    if isinstance(pairs, list):
        for k, v in pairs:
            if isinstance(k, bytes) and k.strip().lower() == want:
                return (v or b"").strip()
        return b""
    v = headers.get(name) if headers is not None else None
    if v is None:
        return b""
    if isinstance(v, bytes):
        return v.strip()
    enc = getattr(headers, "encoding", None)          # a client that says how it decoded them
    try:
        return str(v).strip().encode(enc if isinstance(enc, str) and enc else "latin-1")
    except (LookupError, UnicodeEncodeError):
        return str(v).strip().encode("utf-8")


def _cffi_follow(url, imp, accept=None, verify=True, download=False, headers=None, deadline=None):
    """GET with redirects followed by hand, so every hop can be checked for a private target.

    Cookies set by one hop are sent to the next (many sites set a session cookie, then redirect).
    They live in the host folder for 6 hours and are reused by later runs. A cookie carries the
    Domain it was set for (or none: "this host only") and its own expiry; an empty value deletes
    the name. --clear-cookies starts from an empty jar.
    """
    cur, hops = url, 0
    jar = load_cookies(url)
    while True:
        hdrs = dict(headers or {}) if cur == url else {}
        cur_p = urllib.parse.urlparse(cur)
        sent = cookies_for(jar, host_of(cur), cur_p.path or "/", cur_p.scheme or "https")
        if sent:
            hdrs["Cookie"] = cookie_header(sent)
            _COOKIE_STATS["sent"] += 1
        if deadline is not None and deadline - now() < 1:
            raise RuntimeError("the time for the page ran out")
        r = _cffi_get(cur, imp, accept, verify, download, hdrs, deadline=deadline)
        try:
            fresh, here = {}, host_of(cur)
            # curl_cffi iterates cookie *names*; the objects with Domain/Path/Secure live in .jar
            jar_obj = getattr(r.cookies, "jar", None)
            if jar_obj is not None:
                pairs = [(c.name, getattr(c, "value", ""), getattr(c, "domain", ""),
                          getattr(c, "path", "/") or "/", bool(getattr(c, "secure", False)),
                          getattr(c, "expires", 0)) for c in jar_obj]
            else:
                pairs = [(k, v, "", "/", False, 0) for k, v in (r.cookies or {}).items()]
            for name, value, dom, cpath, secure, exp in pairs:
                if not name:
                    continue
                dom = (dom or "").lstrip(".").lower()
                try:
                    exp = int(exp or 0)
                except (TypeError, ValueError):
                    exp = 0
                fresh[name] = {"v": value or "",
                               "d": dom if (dom and dom != here) else "",
                               "e": exp if exp > 0 else 0,
                               "p": cpath or "/", "s": secure, "h": here}
                if fresh[name]["v"]:
                    jar[name] = fresh[name]
                else:
                    jar.pop(name, None)
            if fresh:
                save_cookies(url, fresh, set_from=cur)
        except Exception as _dbg_e:                            # noqa: BLE001
            debuglog.exc("cookies: save after a hop", _dbg_e)
        if r.status_code in (301, 302, 303, 307, 308):
            loc = intl.location(raw_header(r.headers, "location"))
            if not loc:
                return r, cur
            nxt = urllib.parse.urljoin(cur, loc)
            why = hop_refused(url, nxt)
            if why:
                raise RuntimeError("a redirect points at %s; refused (%s)" % (nxt[:120], why))
            hops += 1
            if hops > MAX_REDIRECTS:
                raise RuntimeError("more than %d redirects" % MAX_REDIRECTS)
            cur = nxt
            continue
        return r, cur


def _spool_curl_cffi(r, limit, download, spool_dir, deadline=None):
    """Turn a streamed curl_cffi response into (bytes|b"", path, size, head, cut), honouring the cap.

    `cut` says why the transfer ended early, "" when it did not: "slow" (the server stopped
    sending: below the speed floor), "step" (still arriving when the step's time ran out),
    "broken" (the connection broke). What arrived is kept in every case.
    """
    if not hasattr(r, "iter_content"):                 # a test double, or plain requests
        data = getattr(r, "content", b"") or b""
        return data, "", len(data), data[:512], ""
    got, cut = 0, ""

    def gen():
        nonlocal got, cut
        try:
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                if limit is not None and got + len(chunk) > limit:
                    return
                got += len(chunk)
                yield chunk
                if deadline is not None and now() > deadline:
                    cut = "step"                   # a trickle above the speed floor: the step ends
                    return
        except Exception as e:                     # noqa: BLE001
            debuglog.exc("http: stream", e)
            cut = cut_reason(str(e))
            return

    st = {"cut": ""}
    body, path, size, head = spool_to_file(gen(), spool_dir, state=st)
    return body, path, size, head, cut or st["cut"]


def cut_said(f, size=None):
    """The cut transfer in words, with how much arrived (and of how much, when the server said)."""
    n = int(size if size is not None else (f.get("size") or 0))
    if f.get("cut") == "disk" and not n:
        return "the disk has less than 1 GB free, so the download did not start"
    got = human_bytes(n)
    whole = int(f.get("expected") or 0)
    got += " of %s" % human_bytes(whole) if whole else ""
    return {"slow": "the server stopped sending after %s",
            "step": "the time for the page ran out after %s",
            "disk": "the disk has less than 1 GB free, so the download stopped after %s"}.get(
        f.get("cut") or "", "the connection broke after %s") % got


def cut_transfer(manifest, f, what):
    """A file cut in transit, said as a status. Why it was cut decides it: a file still arriving when the time for it
    ran out is too big for one call (`too_large`: --download takes it whole); a server that stopped sending, or a
    connection that broke, is a failure (`error`) - a file stuck at 1 KB is not "too large". `what` names the
    file in the reason ("PDF", "video file")."""
    got, whole = int(f.get("size") or 0), int(f.get("expected") or 0)
    of = " of %s" % human_bytes(whole) if whole else ""
    if f.get("cut") == "step":
        manifest["status"] = "too_large"
        manifest["signals"]["limit"] = ("the %s was still arriving when the time for it ran out "
                                        "(%d s): %s%s" % (what, int(round((f.get("ms") or 0) / 1000.0)),
                                                          human_bytes(got), of))
        manifest["advice"] = "rerun with --download: no time limit, the file arrives whole"
    else:
        manifest["status"] = "error"
        manifest["signals"]["status_reason"] = (
            "the server stopped sending the %s after %s%s" if f.get("cut") == "slow" else
            "the connection broke after %s%s of the %s") % (
            (what, human_bytes(got), of) if f.get("cut") == "slow" else (human_bytes(got), of, what))
        manifest["advice"] = ("try again in a minute; --download waits as long as the server "
                              "takes, with no time limit")


def cut_reason(message):
    """Why curl stopped a transfer, from its message: the speed floor (the server stopped sending),
    the time bound (still arriving), or anything else (the connection broke)."""
    low = (message or "").lower()
    if "too slow" in low or "less than" in low and "bytes/sec" in low:
        return "slow"
    if "timed out" in low or "timeout" in low or "(28)" in low:
        return "step"
    return "broken"


def local_path(arg):
    """An existing file on this machine named by a path or a file:// URL, else "". A path given as text in the
    user's locale (an MCP client's) and a file:// URL's escapes are the file system's bytes where its locale is
    not UTF-8 (KNOWN-ISSUES 175)."""
    a = (arg or "").strip()
    if not a:
        return ""
    try:
        if a.lower().startswith("file:"):
            raw = urllib.parse.urlparse(a).path
            # the escapes are the name's bytes on disk (local_url writes them so): a GBK name is no UTF-8
            a = (os.fsdecode(urllib.parse.unquote_to_bytes(raw)) if os.name != "nt"
                 else urllib.request.url2pathname(raw))
        p = ownenv.fs_path(os.path.abspath(os.path.expanduser(a)))
        return p if os.path.isfile(p) else ""
    except (OSError, ValueError):
        return ""


def local_url(path):
    """The file:// address a local read is filed under."""
    import pathlib
    return pathlib.Path(path).resolve().as_uri()


LOCAL_TYPES = {".html": "text/html", ".htm": "text/html", ".xhtml": "text/html", ".md": "text/markdown",
               ".markdown": "text/markdown", ".txt": "text/plain", ".json": "application/json",
               ".xml": "text/xml", ".csv": "text/plain", ".pdf": "application/pdf", ".rtf": "application/rtf",
               ".odt": "application/vnd.oasis.opendocument.text"}


def read_local_file(path, workdir):
    """A file on this machine as an HTTP step would have answered it: a copy goes into the work
    folder (the pipeline moves the body it gets; the user's file must stay where it is)."""
    out = {"status": 200, "ct": LOCAL_TYPES.get(os.path.splitext(path)[1].lower(), ""), "body": b"", "path": "",
           "final": local_url(path), "error": "", "size": 0, "head": b"", "engine": "file", "headers": {}}
    t = now()
    try:
        size = os.path.getsize(path)
        if size <= SPOOL_INMEM:
            with open(path, "rb") as fh:
                out["body"] = fh.read()
        else:
            spool = os.path.join(workdir, ".local.%d.part" % os.getpid())
            shutil.copyfile(path, spool)
            out["path"] = spool
        with open(path, "rb") as fh:
            out["head"] = fh.read(512)
        out["size"] = size
    except OSError as e:
        out.update(status=0, error="%s: %s" % (type(e).__name__, str(e)[:160]))
    out["ms"] = int((now() - t) * 1000)
    return out


def http_deadline(download):
    """When the HTTP step must end. A slow but moving transfer is not cut by a fixed total: a
    machine on a slow link needs longer (p99 8.6 s at 1 Mbit/s and +300 ms, 16 s at worst). A
    stalled one is cut by the connect timeout and the speed floor; the rest by the read's deadline,
    less what the extraction and the tail need. --download: no bound."""
    if download:
        return None
    fuse = now() + HTTP_STEP_SECONDS
    end = budget.until(budget.tail() * HTTP_RESERVE_TAILS)
    return fuse if end is None else min(fuse, end)


def fetch_http(url, download=False, workdir=None, validators=None):
    """One URL, one step: every attempt, fingerprint, fallback and the https upgrade share
    the time http_deadline() gives; what arrived by then is kept as partial. --download has no
    bound."""
    t0 = now()
    deadline = http_deadline(download)
    out = _fetch_http(url, download, workdir, validators, deadline)
    cut = out.get("cut") or ""
    end = ("ok" if (out.get("body") or out.get("path") or out.get("not_modified") or out.get("too_large"))
           and not cut else
           budget.ended(HTTP_STEP_SECONDS, None if deadline is None else deadline - t0) if cut == "step" else
           "stall" if cut == "slow" else "fail")
    budget.record("http", t0, end, own=None if download else HTTP_STEP_SECONDS,
                  given=None if deadline is None else deadline - t0,
                  note="%s %s %s%s" % (out.get("engine") or "", out.get("status") or "-",
                                       human_bytes(int(out.get("size") or 0)),
                                       (" " + str(out.get("error"))[:80]) if out.get("error") else ""))
    return out


def _fetch_http(url, download, workdir, validators, deadline):
    out = _fetch_once(url, download, workdir, validators, deadline=deadline)
    if out.get("status") in (502, 503, 504) and (deadline is None or deadline - now() > 4):
        # a gateway that lost its upstream, a server restarting: one more try a second later,
        # inside the same step. The first answer stays if the second is no better.
        time.sleep(1.0)
        again = _fetch_once(url, download, workdir, validators, deadline=deadline)
        if again.get("status") and again["status"] < 500 and (again.get("body") or again.get("path")):
            if out.get("path") and os.path.exists(out["path"]):
                os.unlink(out["path"])
            again["retried"] = "HTTP %s, then %s" % (out["status"], again["status"])
            out = again
        elif again.get("path") and os.path.exists(again["path"]):
            os.unlink(again["path"])
    # a scheme that never answered is worth one upgrade attempt: http -> https
    if (not out.get("body") and not out.get("path") and not out.get("too_large")
            and url.lower().startswith("http://") and not host_is_private(url) and out.get("error")
            and not urllib.parse.urlparse(url).port         # a port of its own: https there is no better
            and re.search(r"(resolve host|failed to connect|could not connect|timed out|timeout)",
                          out["error"], re.I)
            and (deadline is None or deadline - now() > 2)):
        up = _fetch_once("https://" + url[7:], download, workdir, validators, deadline=deadline)
        if up.get("body") or up.get("path"):
            up["scheme_upgrade"] = True
            return up
    return out


def _check_space(size, download):
    """Refuse before writing when the disk cannot hold the file (never monkey with the OS)."""
    if not size:
        return ""
    free = free_bytes(cache_root())
    if size > free - 64 * 1024 * 1024:
        return ("the file is %s, the disk has %s free" % (human_bytes(size), human_bytes(free)))
    return ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib must not follow a redirect itself: every hop goes through hop_refused()."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENERS = {}


def opener(handler):
    """A urllib opener, built on first use: building one loads the system's certificate store
    (0.07 s on Windows), and most reads never use urllib for a page or a picture."""
    if handler not in _OPENERS:
        _OPENERS[handler] = urllib.request.build_opener(handler)
    return _OPENERS[handler]


def _fetch_urllib(url, download, spool_dir, cond, deadline, out, t):
    """The HTTP step with the standard library only: the same redirect checks, the same speed
    floor (a socket that stays silent for 10 s) and the same step deadline as the curl channels."""
    limit = download_limit(download)
    cur, hops = url, 0
    out["engine"] = "http:urllib"
    while True:
        left = HTTP_STEP_SECONDS if deadline is None else deadline - now()
        if not download and left < 1:
            out["error"] = out.get("error") or "the time for the page ran out"
            break
        p = urllib.parse.urlparse(cur)
        headers = {"Accept": ACCEPT, "User-Agent": UA, "Accept-Language": intl.accept_language("en-US,en;q=0.9")}
        headers.update(cond)
        sent = cookies_for(load_cookies(cur), host_of(cur), p.path or "/", p.scheme or "https")
        if sent:
            headers["Cookie"] = cookie_header(sent)
            _COOKIE_STATS["sent"] += 1
        try:
            # one socket timeout for the connect and for every read: silence for 10 s is the floor
            r = opener(_NoRedirect).open(urllib.request.Request(intl.iri_to_uri(cur), headers=headers),
                                    timeout=max(1.0, min(HTTP_LOW_SPEED[1], left)))
        except urllib.error.HTTPError as e:
            r = e                                  # a 3xx, 4xx or 5xx still has headers and a body
        except Exception as e:                     # noqa: BLE001
            out["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
            break
        code = getattr(r, "code", None) or getattr(r, "status", 0) or 0
        if code in (301, 302, 303, 307, 308):
            loc = intl.location(raw_header(r.headers, "Location"))
            r.close()
            if not loc:
                out["error"] = "a redirect without a Location"
                break
            nxt = urllib.parse.urljoin(cur, loc)
            why = hop_refused(url, nxt)
            if why:
                out["error"] = "a redirect points at %s; refused (%s)" % (nxt[:120], why)
                break
            hops += 1
            if hops > MAX_REDIRECTS:
                out["error"] = "more than %d redirects" % MAX_REDIRECTS
                break
            cur = nxt
            continue
        if code == 304:
            r.close()
            out.update(status=304, not_modified=True, final=cur)
            break
        expected = r.headers.get("Content-Length") or ""
        state = {"cut": ""}

        def chunks():
            got = 0
            read = getattr(r, "read1", None) or r.read
            try:
                while True:
                    chunk = read(65536)
                    if not chunk:
                        return
                    if limit is not None and got + len(chunk) > limit:
                        return
                    got += len(chunk)
                    yield chunk
                    if deadline is not None and now() > deadline:
                        state["cut"] = "step"
                        return
            except Exception as e:                 # noqa: BLE001
                debuglog.exc("http: urllib stream", e)
                state["cut"] = "slow" if "timed out" in str(e).lower() else "broken"

        body, path, size, head = spool_to_file(chunks(), spool_dir, state=state)
        try:
            r.close()
        except Exception:                          # noqa: BLE001
            pass
        if limit is not None and size >= limit:
            if path and os.path.exists(path):
                os.unlink(path)
            out.update(too_large_out(size, limit, "file"))
            out["final"] = cur
            break
        out.update(status=code, ct=r.headers.get("Content-Type", "") or "", body=body, path=path,
                   size=size, head=head, final=cur, partial=bool(state["cut"]), cut=state["cut"],
                   etag=r.headers.get("ETag", "") or "", last_modified=r.headers.get("Last-Modified", "") or "",
                   disposition=intl.header_bytes(raw_header(r.headers, "Content-Disposition")),
                   headers=wall_headers(r.headers), expected=int(expected) if expected.isdigit() else 0)
        break
    out["ms"] = int((now() - t) * 1000)
    return out


def refused_fingerprint(code):
    """A 4xx that another fingerprint (then plain curl) may get past; 404 and 410 are answers."""
    return bool(code) and 400 <= code < 500 and code not in (404, 410)


def _fetch_once(url, download=False, workdir=None, validators=None, plain_only=False, deadline=None):
    limit = download_limit(download)
    spool_dir = workdir or cache_root()
    cond = {}
    v = (validators or {}).get(url) or {}
    if v.get("etag"):
        cond["If-None-Match"] = v["etag"]
    if v.get("last_modified"):
        cond["If-Modified-Since"] = v["last_modified"]
    out = {"engine": None, "status": None, "ct": "", "body": b"", "path": "", "size": 0,
           "head": b"", "final": url, "error": "", "ms": 0}
    t = now()
    # TLS impersonation is pointless (and slow to fail) on internal hosts: use plain curl there
    if (_CAPS_RUN.get("c") or caps())["libs"].get("curl_cffi") and not host_is_private(url) and not plain_only:
        try:
            r, tries, failure, final = None, impersonations(), "", url
            codes = []
            for imp in tries:
                if codes and deadline is not None and deadline - now() < 2:
                    break                       # the step's time is spent: keep the answer we have
                if len(codes) >= HTTP_ATTEMPTS + 1:
                    break
                if len(codes) >= HTTP_ATTEMPTS and any(code != 403 for code in codes):
                    break                       # only a second plain 403 earns a third family
                try:
                    # no custom User-Agent: curl_cffi already sends the browser's own headers, and a
                    # bot UA on top of a Firefox handshake is exactly what npm/medium rejected.
                    r, final = _cffi_follow(url, imp, download=download, headers=cond, deadline=deadline)
                except Exception as e:                       # noqa: BLE001
                    failure = "%s: %s" % (type(e).__name__, str(e)[:160])
                    trace("http.error", imp=imp, error=failure, url=url)
                    # A public page may use a certificate this machine does not trust (Russian
                    # sites with the national CA). Reading public text is worth taking it
                    # unverified, and we say so in signals.tls.
                    if re.search(r"(?i)certificate|SSL", failure):
                        try:
                            r, final = _cffi_follow(url, imp, verify=False, download=download, deadline=deadline,
                                                    headers=cond)
                            trace("http.unverified", imp=imp, status=r.status_code, url=url)
                            if r.status_code == 406:
                                r, final = _cffi_follow(url, imp, HTML_ACCEPT, verify=False, deadline=deadline,
                                                        download=download)
                            if not refused_fingerprint(r.status_code):
                                out["tls_unverified"] = True
                                break
                        except Exception as e2:              # noqa: BLE001
                            failure = "%s: %s" % (type(e2).__name__, str(e2)[:160])
                    # a fingerprint does not fix a dead connection: one timeout is enough
                    break
                trace("http.attempt", imp=imp, status=r.status_code, url=url)
                if r.status_code == 406:                     # the site refuses our Accept list
                    try:
                        r, final = _cffi_follow(url, imp, HTML_ACCEPT, download=download, deadline=deadline)
                        trace("http.accept", imp=imp, status=r.status_code, url=url)
                    except Exception as _dbg_e:                        # noqa: BLE001
                        debuglog.exc("http: 406 retry", _dbg_e)
                codes.append(r.status_code)
                if not refused_fingerprint(r.status_code) or imp == tries[-1]:
                    break
            if r is None:
                raise RuntimeError(failure or "curl_cffi refused every impersonation")
            if r.status_code == 304:
                out.update(engine="http:curl_cffi", status=304, ct=r.headers.get("content-type", ""),
                           not_modified=True, final=final, ms=int((now() - t) * 1000))
                return out
            cl = ""
            try:
                cl = str(r.headers.get("content-length") or "")
            except Exception:                                # noqa: BLE001
                pass
            known = int(cl) if cl.isdigit() else 0
            if limit is not None and known > limit:
                out.update(too_large_out(known, limit, "file"))
                out["final"] = final
                return out
            if download:
                why = _check_space(known, download)
                if why:
                    out["error"] = why
                    out["final"] = final
                    return out
            body, path, size, head, cut = _spool_curl_cffi(r, limit, download, spool_dir, deadline)
            try:
                r.close()                   # a cut transfer leaves the connection open
            except Exception:                            # noqa: BLE001
                pass
            if limit is not None and size >= limit:
                if path and os.path.exists(path):
                    os.unlink(path)
                out.update(too_large_out(size, limit, "file"))
                out["final"] = final
                return out
            out.update(engine="http:curl_cffi", status=r.status_code,
                       ct=r.headers.get("content-type", ""), body=body, path=path,
                       size=size, head=head, final=final, partial=bool(cut), cut=cut, expected=known,
                       etag=(r.headers.get("etag") or ""),
                       last_modified=(r.headers.get("last-modified") or ""),
                       disposition=intl.header_bytes(raw_header(r.headers, "content-disposition")),
                       headers=wall_headers(r.headers))
            out["ms"] = int((now() - t) * 1000)
            if refused_fingerprint(r.status_code) and r.status_code != 406:
                # every fingerprint was refused; a plain client is sometimes let in (Hacker News
                # answers 419 to a browser's handshake and the page to curl): one plain attempt
                alt = _fetch_once(url, download, workdir, validators, plain_only=True, deadline=deadline)
                if alt.get("status") and 200 <= alt["status"] < 400 and (alt.get("body") or alt.get("path")):
                    if path and os.path.exists(path):
                        os.unlink(path)
                    alt["fallback"] = "every fingerprint got HTTP %d; plain curl got %d" % (
                        r.status_code, alt["status"])
                    return alt
                if alt.get("path") and os.path.exists(alt["path"]):
                    os.unlink(alt["path"])
            return out
        except Exception as e:                                # noqa: BLE001
            debuglog.exc("http: curl_cffi", e)
            out["error"] = str(e)[:200]
            # A dead connection is not a fingerprint problem and plain curl would wait the same
            # timeout for the same answer. A TLS-level reset is different: another stack can pass.
            if re.search(r"(?i)(28|timed? ?out|could not connect|failed to connect|resolve host|"
                         r"connection refused|network is unreachable|redirect)", out["error"]):
                out["ms"] = int((now() - t) * 1000)
                return out
    curl = which("curl") or which("curl.exe")
    if curl:
        cur, hops, retried = url, 0, False
        while True:
            left = HTTP_STEP_SECONDS if deadline is None else deadline - now()
            if not download and left < 1:
                out["error"] = out.get("error") or "the time for the page ran out"
                out["ms"] = int((now() - t) * 1000)
                return out
            # curl.exe on Windows receives argv in the ANSI code page, so a Cyrillic folder in
            # -o/-D fails with status 000 and no error text at all. curl therefore runs inside a
            # staging folder and only ever sees ASCII names; Python moves the body into place.
            stage = os.path.join(cache_root(), "tmp", os.urandom(8).hex())
            try:
                os.makedirs(stage, exist_ok=True)
            except OSError:
                stage = cache_root()
            dst = os.path.join(spool_dir, "dl-" + os.path.basename(stage) + ".part")
            if download and disk_low(stage):
                # below the floor nothing starts (--max-filesize needs room to give)
                if os.path.normcase(stage) != os.path.normcase(cache_root()):
                    shutil.rmtree(stage, ignore_errors=True)
                out.update(cut="disk", partial=True, final=cur, engine="http:curl",
                           error="the disk has less than 1 GB free")
                return out
            jar_path = os.path.join(stage, "cookies.txt")
            # curl gets only what may go to this hop: path and Secure are filtered here, not left
            # to curl's own jar reader
            cur_p = urllib.parse.urlparse(cur)
            try:
                write_netscape(jar_path,
                               cookies_for(load_cookies(cur), host_of(cur),
                                           cur_p.path or "/", cur_p.scheme or "https"),
                               host_of(cur))
            except OSError:
                pass
            if cookies_for(load_cookies(cur), host_of(cur), cur_p.path or "/",
                           cur_p.scheme or "https"):
                _COOKIE_STATS["sent"] += 1
            # http(s) only, whatever a server answers: curl itself also speaks file://, ftp://, ...
            cmd = [curl, "-sS", "--proto", "=http,https", "--proto-redir", "=http,https",
                   "--compressed", "--connect-timeout", "%.1f" % min(HTTP_CONNECT_TIMEOUT, max(1.0, left)),
                   "-b", "cookies.txt", "-c", "cookies.txt",
                   "-o", "body.part", "-D", "body.hdr",
                   "-w", "%{http_code}|%{content_type}|%{redirect_url}|%{size_download}",
                   "-H", "Accept: " + ACCEPT, "-H", "Accept-Language: " + intl.accept_language("en-US,en;q=0.9"),
                   "-A", UA, intl.iri_to_uri(cur)]
            for k, v in cond.items():
                cmd[-1:-1] = ["-H", "%s: %s" % (k, v)]
            if download:
                # no read timeout at all: the flag means it; only the disk stops it
                # (curl 8.4+ also stops a stream with no length at --max-filesize)
                room = free_bytes(stage) - DISK_FLOOR
                if room > 0:
                    cmd[1:1] = ["--max-filesize", str(room)]
            else:
                # the same bounds as curl_cffi: the speed floor, and what is left of the step
                cmd[1:1] = ["--max-time", "%d" % max(1, int(left)), "--max-filesize", str(MAX_DOWNLOAD),
                            "--speed-limit", str(HTTP_LOW_SPEED[0]), "--speed-time", str(HTTP_LOW_SPEED[1])]
            rc, so, se = run(cmd, cwd=stage)
            try:                                    # what the server set, back into the shared jar
                back = read_netscape(jar_path, host_of(cur))
                if back:
                    save_cookies(url, back, set_from=cur)
            except OSError:
                pass
            etag = last_modified = disposition = expected = ""
            raw_loc = b""
            seen_headers = {}
            try:
                with open(os.path.join(stage, "body.hdr"), "rb") as fh:
                    for rawline in fh:
                        if rawline[:9].lower() == b"location:":
                            raw_loc = rawline[9:].strip()       # as the bytes came: intl.location
                        line = intl.header_bytes(rawline)
                        low = line.lower()
                        if low.startswith("etag:"):
                            etag = line.split(":", 1)[1].strip()
                        elif low.startswith("last-modified:"):
                            last_modified = line.split(":", 1)[1].strip()
                        elif low.startswith("content-disposition:"):
                            disposition = line.split(":", 1)[1].strip()
                        elif low.startswith("content-length:"):
                            expected = line.split(":", 1)[1].strip()
                        name = low.split(":", 1)[0].strip()
                        if name in WALL_HEADER_NAMES and ":" in line:
                            seen_headers[name] = line.split(":", 1)[1].strip()[:200]
            except OSError:
                pass
            p = ""
            part = os.path.join(stage, "body.part")
            if os.path.exists(part):
                try:
                    os.replace(part, dst)
                    p = dst
                except OSError:
                    p = ""
            shutil.rmtree(stage, ignore_errors=True)
            code, ct, redir, size = "", "", "", ""
            try:
                code, ct, redir, size = so.decode("utf-8", "replace").split("|", 3)
            except Exception as _dbg_e:                                # noqa: BLE001
                debuglog.exc("http: curl output", _dbg_e)
                out["error"] = (se or b"").decode("utf-8", "replace")[:200]
            if rc != 0 and not code.strip("0|"):
                if rc in (52, 56) and not retried and (download or deadline is None or deadline - now() > 2):
                    # the connection was dropped (an empty reply, a reset): one more try on a new
                    # connection - a server restarting or a flaky proxy usually answers it
                    retried = True
                    if p and os.path.exists(p):
                        os.unlink(p)
                    continue
                # curl itself failed (a bad path, a missing library, a refusal): say so instead of
                # returning an empty body with `status 0` and no reason
                detail = (se or b"").decode("utf-8", "replace").strip()[:160]
                out["error"] = "curl exit %d%s" % (rc, (": " + detail) if detail else "")
                out["ms"] = int((now() - t) * 1000)
                return out
            if code == "304":
                if os.path.exists(p):
                    os.unlink(p)
                out.update(engine="http:curl", status=304, not_modified=True, final=cur,
                           ms=int((now() - t) * 1000))
                return out
            if code in ("301", "302", "303", "307", "308") and (redir.strip() or raw_loc):
                # the Location itself, as on the other channels (curl's own redirect_url re-encodes it)
                nxt = urllib.parse.urljoin(cur, intl.location(raw_loc)) if raw_loc else redir.strip()
                if os.path.exists(p):
                    os.unlink(p)
                why = hop_refused(url, nxt)
                if why:
                    out["error"] = "a redirect points at %s; refused (%s)" % (nxt[:120], why)
                    return out
                hops += 1
                if hops > MAX_REDIRECTS:
                    out["error"] = "more than %d redirects" % MAX_REDIRECTS
                    return out
                cur = nxt
                continue
            known = int(size) if (size or "").isdigit() else 0
            if rc == 63 or (not download and known > MAX_DOWNLOAD):
                if os.path.exists(p):
                    os.unlink(p)
                out.update(too_large_out(known, MAX_DOWNLOAD, "file"))
                return out
            if download:
                why = _check_space(known, download)
                if why:
                    if os.path.exists(p):
                        os.unlink(p)
                    out["error"] = why
                    return out
            head = b""
            real = known or (os.path.getsize(p) if p and os.path.exists(p) else 0)
            if p and os.path.exists(p):
                with open(p, "rb") as fh:
                    head = fh.read(512)
            keep_bytes = b""
            path = p
            if real == 0:
                if p and os.path.exists(p):
                    os.unlink(p)
                path = ""
            elif real <= SPOOL_INMEM:
                with open(p, "rb") as fh:
                    keep_bytes = fh.read()
                os.unlink(p)
                path = ""
            out.update(engine="http:curl", status=int(code or 0), ct=ct, body=keep_bytes,
                       path=path, size=real, head=head, final=cur,
                       etag=etag, last_modified=last_modified, disposition=disposition,
                       headers=seen_headers, partial=bool(rc not in (0,) and real),
                       cut=("disk" if rc == 63 and download else       # --max-filesize: the disk floor
                            cut_reason((se or b"").decode("utf-8", "replace") + " (%d)" % rc)
                            if rc not in (0,) and real else ""),
                       expected=int(expected) if expected.isdigit() else 0)
            out["ms"] = int((now() - t) * 1000)
            return out
    if not curl and not out.get("engine"):
        # neither curl_cffi nor curl: the standard library reads the page - "core is stdlib
        # only" has to be true, and "the host did not answer" was a lie when nothing was asked
        return _fetch_urllib(url, download, spool_dir, cond, deadline, out, t)
    if (out.get("body") or out.get("path")) and out.get("error"):
        out["partial"] = True                      # the body is usable, the transfer was not whole
    out["ms"] = int((now() - t) * 1000)
    return out


WEAK_CHARSETS = intl.WEAK_CHARSETS
_BOMS = intl.BOMS
plausible = intl.plausible
decode_page = intl.decode_page


def smart_decode(body, ct=""):
    """The page's text in the encoding it really is in, and that encoding's name: intl.decode_page,
    which also says how it knows (a header, the bytes' own look) and whether the reading may be wrong."""
    got = intl.decode_page(body, ct)
    return got[0], got[1]


def note_charset(manifest, got):
    """What a reader of the manifest needs of a page's encoding: its name, and - when the page did not
    say it, so the text was read by a guess - that, and whether the guess is a doubtful one. A silent
    wrong reading is what a Chinese or Japanese page used to get on a machine without charset_normalizer.
    The answer's first line says it (`charset gb18030 (guessed, doubtful)`); `advice` is left to what
    an agent can do, and there is nothing to do about a page that names no encoding."""
    manifest["url"]["charset"] = got.charset
    if got.how in ("guessed", "detected") or (got.how == "utf-8" and got.doubt):
        manifest["signals"]["charset_guess"] = got.charset + (" (doubtful)" if got.doubt else "")


def title_of(html):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip() if m else ""


def first_heading(html):
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html or "")
    if not m:
        return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip()


def looks_binary(body):
    """Not HTML, not a known format, mostly control bytes: there is no text to read."""
    head = (body or b"")[:4096]
    if not head:
        return False
    if any(head.startswith(bom) for bom, _cs in _BOMS):
        return False                         # UTF-16 text is full of zero bytes and is still text
    if b"\x00" in head:
        return True
    ctrl = sum(1 for b in head if b < 9 or 13 < b < 32)
    return ctrl / len(head) > 0.10


# ---------------------------------------------------------------- extraction
# visible_text, visible_len, crude_text, html2text_full, readability_text and trafilatura_text
# live in engines.py: xchild.py runs them in a process the read can stop.

def with_base(html, url):
    """The page with a <base href> to its own address, unless it has one: a file given to an
    extractor has no address, and every relative link became about:blank/..."""
    if not url or not html or re.search(r"(?i)<base\b[^>]*href", html[:20000]):
        return html
    tag = '<base href="%s">' % url.replace('"', "%22")
    m = re.search(r"(?i)<head\b[^>]*>", html[:20000])
    return html[:m.end()] + tag + html[m.end():] if m else tag + html


# defuddle drops any element whose id or class holds one of its clutter words, an inline link inside
# a sentence too; "next-" is one of them (for "next post" boxes), and the WHATWG specs give each
# term's link an id like "data-state:next-input-character": the parsing chapter read "Consume the:"
# 81 times. An inline element's id is no text, so it goes before defuddle sees the page; a
# footnote's stays (defuddle finds footnotes by it). A block that goes this way is the block
# rule's: it comes back from page.md. Classes stay: code languages and math use them.
_INLINE_TAG = re.compile(r"(?i)<(?:a|abbr|b|cite|code|dfn|em|i|kbd|mark|q|samp|small|span|strong|sub|sup|time|var)"
                         r"\b[^>]*>")
_ID_ATTR = re.compile(r"(?i)\s+id\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)")
_NOTE_ID = re.compile(r"(?i)^[\"']?(?:fn|footnote|ref|ftnt|cite|easy-footnote|_ftn|note|bib)")
# docutils (PEP 8) marks a footnote's reference by its class, its id is "id1": such a tag keeps it
_NOTE_TAG = re.compile(r"(?i)footnote|citation|noteref|biblioref")


def inline_ids_off(html):
    if not html or " id" not in html:
        return html

    def one(m):
        tag = m.group(0)
        idm = _ID_ATTR.search(tag)
        if not idm or _NOTE_ID.match(idm.group(1)) or _NOTE_TAG.search(tag):
            return tag
        return tag[:idm.start()] + tag[idm.end():]
    return _INLINE_TAG.sub(one, html)


# An inline <svg> that an extractor passed through as markup (defuddle keeps it): SQLite's syntax
# diagrams were 13.6 KB of path data, a third of lang_with.html's text. Its labels are the
# diagram's words, so it becomes one line of them; one without labels (an icon) goes. A code block
# keeps its markup: there an SVG is the example.
_SVG = re.compile(r"(?is)<svg\b.*?</svg>")
_SVG_LABEL = re.compile(r"(?is)<text\b[^>]*>(.*?)</text>")
_FENCE = re.compile(r"(?m)^[ \t]*(```|~~~)")


def inline_svg_text(md):
    if not md or "<svg" not in md.lower():
        return md

    def one(m):
        labels = [re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", t))).strip() for t in _SVG_LABEL.findall(m.group(0))]
        labels = [t for t in labels if t]
        return "[diagram: %s]" % " ".join(labels)[:600] if labels else ""
    parts = re.split(r"(?ms)(^[ \t]*(?:```|~~~).*?^[ \t]*(?:```|~~~)[^\n]*$)", md)
    return "".join(p if _FENCE.match(p or "") else _SVG.sub(one, p) for p in parts)


_DD = {"worker": None, "spawn": None}     # this read's defuddle worker (ddworker.py)


def defuddle_worker(wait=True):
    """Start this read's defuddle worker once, as early as possible: it loads while the HTTP
    request is in flight. The process starts in a thread (a Windows process start is 0.1 s the HTTP
    request need not wait for). wait=True returns the worker, None when defuddle is off, missing,
    or not an install we recognise."""
    if _DD["spawn"] is None:
        def spawn():
            if "defuddle" in SKIP:
                return
            dist, node = ddworker.locate(which("defuddle"), which("node"))
            if not dist:
                return
            popen_kw = {"start_new_session": True} if os.name != "nt" else {
                "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
            try:
                _DD["worker"] = ddworker.Worker(node, dist, popen_kw, on_start=_CHILDREN.add)
            except OSError as e:
                trace("defuddle.worker", error=str(e)[:120])
        _DD["spawn"] = threading.Thread(target=spawn, daemon=True)
        _DD["spawn"].start()
    if wait:
        _DD["spawn"].join(30)
    return _DD["worker"]


def defuddle_close():
    t = _DD["spawn"]
    if t is not None:
        t.join(30)
    w, _DD["worker"], _DD["spawn"] = _DD["worker"], None, None
    if w:
        _CHILDREN.discard(w.p)
        w.close()


class _Done:
    """A finished job: what defuddle_start returns when there is nothing to wait for."""

    def __init__(self, text, why=""):
        self.text, self.why = text, why

    def result(self, seconds):
        return self.text, self.why


def defuddle_cli_command(cli, src, node=None):
    """defuddle's command for one saved page: node on its cli.js when this is an install we recognise
    (ddworker.locate) - never through the npm shim, a .cmd on Windows that cmd.exe would read - else the
    CLI as it is."""
    dist, node = ddworker.locate(cli, node or which("node"))
    if dist and os.path.isfile(os.path.join(dist, "cli.js")):
        return [node, os.path.join(dist, "cli.js"), "parse", src, "--markdown"]
    return [cli, "parse", src, "--markdown"]


def defuddle_start(html, workdir, url=""):
    """Send the page to defuddle and return at once; .result(seconds) gives (markdown, why).
    The worker when there is one, else the CLI in a thread, so Python works on the page meanwhile."""
    if "defuddle" in SKIP:
        return _Done("", "off")
    page = with_base(inline_ids_off(html), url)
    w = defuddle_worker()
    if w and w.alive():
        return w.submit(page)
    p = which("defuddle")
    if not p:
        return _Done("", "not installed")
    box = {}

    def cli():
        src = os.path.join(workdir, "_defuddle_input.%d.html" % threading.get_ident())
        try:
            with open(src, "w", encoding="utf-8") as f:
                f.write(page)
            rc, so, se = run_tool(defuddle_cli_command(p, src),
                                  timeout=budget.cap(CONVERTER_TIMEOUT, floor=1.0))
            box["v"] = (so.decode("utf-8", "replace") if rc == 0 else "", "" if rc in (0, 1) else "rc %s" % rc)
        finally:
            try:
                os.unlink(src)                 # a scratch copy is not a result file
            except OSError:
                pass

    t = threading.Thread(target=cli, daemon=True)
    t.start()

    class _Cli:
        def result(self, seconds):
            t.join(max(0.05, seconds))
            return box.get("v") or (None, "no answer in %.0f s" % seconds)
    return _Cli()


def defuddle_text(html, workdir, url=""):
    """defuddle's markdown for one page, "" when it has none or ran out of time."""
    text, _why = defuddle_start(html, workdir, url).result(budget.cap(CONVERTER_TIMEOUT * 6, floor=1.0))
    return text or ""


def in_child(name, html, url, seconds):
    """One engine of engines.py in a process of its own (xchild.py): (text, why). A process still
    working after `seconds` is killed, so a huge page costs the deadline, not minutes."""
    data = html.encode("utf-8", "replace")
    # -E -B as the model's process: a caller's PYTHONPATH stays out of the engines here too
    cmd = [sys.executable, "-E", "-B", "-X", "utf8",
           os.path.join(os.path.dirname(os.path.abspath(__file__)), "xchild.py"), name, url or ""]
    t0 = now()
    rc, so, se = run(cmd, timeout=max(0.5, seconds), input_bytes=data)
    if rc != 0:
        budget.record(name, t0, budget.ended(EXTRACT_FUSE, seconds) if rc == -1 else "fail",
                      own=EXTRACT_FUSE, given=seconds, note="%d KB of HTML" % (len(data) // 1024))
        return "", ("no answer in %.0f s" % seconds) if rc == -1 else "failed: %s" % se[-160:].decode(
            "utf-8", "replace").strip()
    try:
        text = json.loads(so.decode("utf-8", "replace")).get("text") or ""
    except ValueError:
        budget.record(name, t0, "fail", own=EXTRACT_FUSE, given=seconds, note="unreadable answer")
        return "", "unreadable answer"
    budget.record(name, t0, "ok", own=EXTRACT_FUSE, given=seconds,
                  note="%d KB of HTML, %d words" % (len(data) // 1024, len(text.split())))
    return text, ""


def others(html, url, seconds, names=("readability", "trafilatura")):
    """readability and trafilatura side by side, each in its own process, both within `seconds`:
    {name: (text, why)}."""
    out = {}
    ts = []
    for n in names:
        if n in SKIP:
            continue

        def go(n=n):
            out[n] = in_child(n, html, url, seconds)
        t = threading.Thread(target=go, daemon=True)
        t.start()
        ts.append(t)
    for t in ts:
        t.join(seconds + 5)
    return out


def text_browser(html, workdir):
    """lynx / w3m: whole-page text with no Python or Node at all. Used before the tag stripper."""
    src = os.path.join(workdir, "_text_browser.html")
    try:
        with open(src, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as _dbg_e:                                         # noqa: BLE001
        debuglog.exc("text browser", _dbg_e)
        return "", ""
    if not (which("lynx") or which("w3m")):
        return "", ""
    narrowed, _outs, narrow_done = narrow_paths([src])
    try:
        for name in ("lynx", "w3m"):
            exe = which(name)
            if not exe:
                continue
            if name == "lynx":
                args = [exe, "-dump", "-nolist", "-assume_charset=utf-8", "-display_charset=utf-8", narrowed[0]]
            else:
                args = [exe, "-dump", "-T", "text/html", "-I", "utf-8", "-O", "utf-8", narrowed[0]]
            rc, so, se = run(args, timeout=budget.cap(60, floor=1.0))
            if rc == 0 and so.strip():
                return so.decode("utf-8", "replace"), name
    finally:
        narrow_done()
    return "", ""


def _ld_objects(node, acc):
    if isinstance(node, dict):
        acc.append(node)
        for v in node.values():
            _ld_objects(v, acc)
    elif isinstance(node, list):
        for v in node:
            _ld_objects(v, acc)


def page_meta(html, url):
    """Who/what/when, straight from the page, so a citation does not need a second request."""
    out = {"title": "", "description": "", "canonical": "", "author": "",
           "published": "", "lang": "", "site": ""}

    def clean(s, n=400):
        return unescape(re.sub(r"\s+", " ", s or "")).strip()[:n]

    if not html:
        return {}
    mt = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if mt:
        out["title"] = clean(mt.group(1), 300)
    ml = re.search(r"(?is)<html\b[^>]*\blang\s*=\s*[\"']([^\"']+)", html)
    if ml:
        out["lang"] = clean(ml.group(1), 20)
    mc = re.search(r"(?is)<link\b[^>]*rel\s*=\s*[\"'][^\"']*canonical[^\"']*[\"'][^>]*>", html)
    if mc:
        mh = re.search(r"href\s*=\s*[\"']([^\"']+)", mc.group(0))
        if mh:
            out["canonical"] = clean(mh.group(1))
    meta = {}
    for tag in re.findall(r"(?is)<meta\b[^>]*>", html)[:200]:
        kv = dict((k.lower(), v) for k, v in
                  re.findall(r"([\w:-]+)\s*=\s*[\"']([^\"']*)[\"']", tag))
        key = (kv.get("property") or kv.get("name") or kv.get("itemprop") or "").lower()
        if key and kv.get("content"):
            meta.setdefault(key, clean(kv["content"]))
    out["description"] = meta.get("description") or meta.get("og:description") or ""
    out["author"] = meta.get("author") or meta.get("article:author") or ""
    out["published"] = (meta.get("article:published_time") or meta.get("datepublished")
                        or meta.get("date") or meta.get("publish-date") or "")
    out["site"] = meta.get("og:site_name") or ""
    if not (out["title"] and out["author"] and out["published"]):
        acc = []
        for block in re.findall(r"(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html)[:5]:
            try:
                _ld_objects(json.loads(unescape(block.strip())), acc)
            except Exception:                                 # noqa: BLE001
                continue
        for it in acc:
            a = it.get("author")
            if isinstance(a, list) and a:
                a = a[0]
            if isinstance(a, dict):
                a = a.get("name")
            out["title"] = out["title"] or clean(it.get("headline") or it.get("name") or "")
            out["author"] = out["author"] or clean(a or "")
            out["published"] = out["published"] or clean(it.get("datePublished")
                                                          or it.get("dateModified") or "")
            out["description"] = out["description"] or clean(it.get("description") or "")
    if not out["canonical"]:
        out["canonical"] = url
    return dict((k, v) for k, v in out.items() if v)


def page_meta_image(html):
    """The page's own picture (og:image, twitter:image): a video's cover."""
    for tag in re.findall(r"(?is)<meta\b[^>]*>", html or "")[:300]:
        kv = dict((k.lower(), v) for k, v in re.findall(r"([\w:-]+)\s*=\s*[\"']([^\"']*)[\"']", tag))
        key = (kv.get("property") or kv.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image") and kv.get("content"):
            return unescape(kv["content"]).strip()
    return ""


MAIN_BLOCK = re.compile(r"(?is)<(main|article)\b[^>]*>(.*?)</\1>|"
                        r"<div[^>]+(?:id|class)=\"[^\"]*(?:content|main|listing|catalog|"
                        r"products?|items?|grid)[^\"]*\"[^>]*>(.*?)</div>")


def main_block(html, base=""):
    """The biggest main container as markdown, plus how many links it holds.

    Catalogs and listings (24 product cards, a price grid) are exactly what main-content
    extractors throw away: they keep prose, and a shop page is links. Measured: velogrand.ru
    347 words from trafilatura, 1 012 words from the container — the cards live in the latter.
    """
    best = ""
    for m in MAIN_BLOCK.finditer(html or ""):
        body = m.group(2) or m.group(3) or ""
        if len(body) > len(best):
            best = body
    if not best or len(best) < 2000:
        return "", 0
    return html2text_full(best, base=base), len(re.findall(r"(?i)<a\b", best))


def text_score(md):
    """How good a candidate text is: words plus a little for structure.

    Length alone prefers a bag of comments over a shorter article with headings; the heading
    count is a cheap proxy for "this is a document, not a list of leftovers".
    """
    words = len((md or "").split())
    heads = len(re.findall(r"(?m)^#{1,6}\s+\S", md or ""))
    return words + 2 * heads


# the engines that choose what to keep; `full` and `crude` keep everything, so nothing is dropped
EXTRACTORS = ("defuddle", "readability", "trafilatura", "lynx", "w3m", "main")


HUGE_HTML = 3 * 1024 * 1024    # characters of HTML; above it the whole page is the text
EXTRACT_FUSE = 120             # one extractor at most, with no deadline (--download)


def is_huge(html):
    """Over HUGE_HTML of markup once scripts and styles are out. A news front page is 6 MB of HTML
    and 1 MB without its inline scripts and JSON (CNN: 17 thousand characters of text) - an
    ordinary page for defuddle; the HTML spec is 16 MB either way."""
    return len(html) > HUGE_HTML and len(engines.drop_blocks(html, ("script", "style"))) > HUGE_HTML


def huge_page(html, url, inner=None):
    """Above HUGE_HTML no article extractor runs. On the biggest pages measured (the HTML spec
    16 MB, ECMAScript 7.8, the Emacs manual 5.8, the Kubernetes API 5.6) content.md came out at
    95-100 % of page.md after 27-155 s on a fast machine (2-10 minutes on a weak laptop), and page.md alone
    takes seconds. page.md comes from html2text in a process the deadline can stop; crude_text
    runs beside it (0.7 s for 16 MB), so a weak laptop that cannot finish html2text in time
    still has the page's text."""
    if inner and len(inner) > 500:
        page, why = inner, ""
    else:
        got = others(html, url, budget.cap(EXTRACT_FUSE, floor=1.0), names=("html2text", "crude"))
        page, why = got.get("html2text") or ("", "not run")
        if not page.strip():
            page = (got.get("crude") or ("", ""))[0]
    trace("extract.huge", chars=len(html), page=len(page), why=why)
    return page, ("full" if page.strip() else ""), ({"full": page} if page.strip() else {}), page


def extract(html, url, c, workdir, inner=None, want_all=False, page_html="", after=None):
    """Candidates + the primary pick. Returns (primary, engine, candidates, page).

    defuddle (this read's worker) works on the page while Python makes page.md, the main block
    and the visible length beside it. readability and trafilatura run only when defuddle is
    missing, weak, or --alternate was asked, side by side in processes the deadline can stop.
    `after` is the launch of a browser started early for this page: they wait for it (at most
    LAUNCH_WAIT s), so on a weak laptop they take the CPU while the page loads, not while Chrome
    starts - the same text, decided the same way.
    page.md is html2text's markdown of the page: of the visible DOM when a browser ran
    (`page_html`: headings, links, pictures, tables and code kept, what the page hides left out),
    of the HTML otherwise; the browser's innerText only when neither works. A page over HUGE_HTML
    is its own page.md (huge_page).
    """
    html = pictures.real_srcs(html)       # a lazy picture's real address, for every extractor
    if not want_all and is_huge(html):
        return huge_page(html, url, inner)
    t_dd = now()
    job = defuddle_start(html, workdir, url)
    t_py = now()
    vis = visible_len(html)
    base = engines.page_base(html, url)   # page.md's links are whole addresses, as content.md's
    main_md, main_links = main_block(html, base)
    page = html2text_full(page_html, base=base) if page_html else ""
    if len(page.strip()) < 200:
        page = inner if (inner and len(inner) > 500) else html2text_full(html, vis, base=base)
    budget.record("page.md", t_py, note="%d KB of HTML, beside defuddle" % (len(html) // 1024))
    dd_cap = budget.cap(EXTRACT_FUSE, floor=0.5)
    dd, dd_why = job.result(dd_cap)
    budget.record("defuddle", t_dd, "ok" if dd is not None else (
        budget.ended(EXTRACT_FUSE, dd_cap) if "no answer" in (dd_why or "") else "fail"),
        own=EXTRACT_FUSE, given=dd_cap,
        note="%s, %d KB of HTML, %d words%s" % ("worker" if isinstance(job, ddworker.Job) else "cli",
                                                len(html) // 1024, len((dd or "").split()),
                                                (", " + dd_why) if dd_why else ""))
    # defuddle still working when the time ran out: page.md is the answer (the rest would not
    # finish either), not the tag-stripped crude text
    late = dd is None and "no answer" in (dd_why or "")
    if dd is None:
        trace("extract.defuddle", failed=dd_why)
        if late:
            _DD["late"] = True
    dd = dd or ""
    cands = {}
    if dd.strip():
        cands["defuddle"] = dd
    cover_dd = (len(dd) / vis) if vis else 0.0
    if (want_all or not dd.strip() or cover_dd < 0.5) and budget.left() > 1:
        if after is not None:
            # on a weak laptop two extractor processes beside Chrome's start fight it for the CPU;
            # after the launch the browser mostly waits for the network, and they run in that time
            after.wait(max(0.0, min(LAUNCH_WAIT, budget.left() - 1)))
        got = others(html, url, budget.cap(EXTRACT_FUSE, floor=0.5))
        rd = (got.get("readability") or ("", ""))[0]
        if rd.strip():
            cands["readability"] = rd
            if not dd.strip():
                cover_dd = (len(rd) / vis) if vis else 0.0
        tr = (got.get("trafilatura") or ("", ""))[0]
        if tr.strip():
            cands["trafilatura"] = tr
    if not cands and not late and budget.left() > 1:
        tb, which_tb = text_browser(html, workdir)
        if tb.strip():
            cands[which_tb] = tb
    if not cands and not late:
        crude = crude_text(html)
        if crude.strip():
            cands["crude"] = crude
    if main_md and main_links >= 30:
        best_clean = max((len(v.split()) for k, v in cands.items()
                          if k in ("defuddle", "readability", "trafilatura", "lynx", "w3m")), default=0)
        if best_clean and len(main_md.split()) >= best_clean * 1.5:
            cands["main"] = main_md
            trace("extract.main", words=len(main_md.split()), links=main_links, best=best_clean)
    if page.strip():
        cands["full"] = page
    pool = [n for n in EXTRACTORS if n in cands]
    if pool and cover_dd >= 0.5 and "defuddle" in cands and "main" not in cands:
        primary_name, why = "defuddle", "defuddle covered half the visible text or more"
    elif pool:
        primary_name = max(pool, key=lambda n: text_score(cands[n]))   # best-structured clean text
        why = "the best score (words + 2 a heading) of the clean texts"
    elif "crude" in cands:
        primary_name, why = "crude", "no extractor found text; tags stripped"
    else:
        primary_name, why = ("full" if cands else ""), ("only page.md" if cands else "nothing at all")
    if debuglog.enabled():
        debuglog.log("decide", what="extraction", html_chars=len(html), visible_chars=vis,
                     defuddle_cover=round(cover_dd, 3), late=late, waited_for_browser=after is not None,
                     candidates={k: {"chars": len(v), "words": len(v.split()), "score": text_score(v)}
                                 for k, v in cands.items()},
                     pick=primary_name, why=why)
    return cands.get(primary_name, ""), primary_name, cands, page


# ---------------------------------------------------------------- browser

BROWSER_TRIES = 3              # browsers that may fail to *start*; one that loaded the page is the answer
# per browser, from the start of the load to "done" (settle.py); a timeout still yields the DOM.
# 20 s: on an emulated Celeron VK and Airbnb filled their pages 12-13 s after DOMContentLoaded,
# which itself came 4.5 s (p50) after the request; on a fast machine the rule lets go at p50 5.4 s anyway
BROWSER_TIMEOUT_MS = 20000
SHOT_WIDTH = 1280              # pages are laid out for this width; nothing is scaled after
SHOT_HEIGHT = 1568             # the long edge a vision host keeps without resizing
# the DOM as page.md sees it: what the page shows, without what it hides (menus folded away,
# templates, the cookie dialog's other tabs); Chrome 105+ has checkVisibility
VISIBLE_DOM = """() => {
  const src = document.documentElement, copy = src.cloneNode(true);
  if (typeof src.checkVisibility !== 'function') return '';
  const a = src.querySelectorAll('body *'), b = copy.querySelectorAll('body *');
  if (a.length !== b.length) return '';
  for (let i = a.length - 1; i >= 0; i--) {
    if (a[i].checkVisibility({checkVisibilityCSS: true, visibilityProperty: true})) continue;
    if (getComputedStyle(a[i]).display === 'contents') continue;     // no box of its own, children shown
    if (b[i].parentNode) b[i].parentNode.removeChild(b[i]);
  }
  return '<!DOCTYPE html>' + copy.outerHTML; }"""


def browser_reserve():
    """What the browser leaves before the deadline: the rendered DOM's extraction and the tail."""
    return budget.tail() * 1.5


_BROWSER_THREADS = []           # a browser closes in its own thread while the read goes on
_RENDER_STOP = threading.Event()   # set when a render started early turns out not to be needed
_BROWSER_UP = threading.Event()    # set once this read's browser has a page open, or has failed to
LAUNCH_WAIT = 3.0                  # what the HTTP pass's slower extractors wait for that at most


def browsers_close(seconds=10.0):
    """Wait for the browsers still closing (their cookies are saved before they go)."""
    end = now() + seconds
    for t in list(_BROWSER_THREADS):
        t.join(max(0.0, end - now()))
    _BROWSER_THREADS[:] = [t for t in _BROWSER_THREADS if t.is_alive()]


def apply_shots(manifest, workdir, entries, needed, why=""):
    """Put the pictures into the manifest: files, per-picture facts, the screens they hold, and how
    many screens the page has when that is more (the deadline, or N smaller than the page). `why`:
    what failed when a capture took no picture or stopped early (screens.capture) - the answer says it."""
    if why:
        manifest["signals"]["screenshots_failed"] = why
    if not entries:
        return
    manifest["files"]["screenshots"] = [os.path.join(workdir, e["file"]) for e in entries]
    manifest["screenshots"] = entries
    manifest["signals"]["screenshots"] = len(entries)
    taken = sum(len(e.get("screens") or [1]) for e in entries)
    manifest["signals"]["screens"] = taken
    if needed > taken:
        manifest["signals"]["screens_needed"] = needed
    if any(e.get("format") == "jpg" for e in entries):
        manifest["signals"]["screenshots_format"] = "JPEG q95 where the PNG was over 3.75 MB"


def capture_shots(page, workdir, want):
    """The first `want` screens of the page (screens.py): (entries, screens the page has, why it stopped -
    "" unless a step of the page failed)."""
    t_sc = now()
    entries, needed, taken, why = screens.capture(page, workdir, want, seconds_left=lambda: budget.left())
    budget.record("screens", t_sc, "fail" if why else "deadline" if taken < min(want, needed) else "ok",
                  note="%d of %d asked, the page has %d%s" % (taken, want, needed, "; " + why if why else ""))
    trace("shots", pictures=len(entries), screens=taken, needed=needed, glue=screens.glue_tool() or "-", why=why)
    return entries, needed, why


def pdf_shots(path, workdir, want):
    """A scan or a PDF as 1280 x 1568 pictures, two screens each: pymupdf renders them, nothing
    is scaled. `want` counts screens, like a page's; PNG, or JPEG q95 over 3.75 MB."""
    if want <= 0:
        return [], 0
    with lib_path(path) as at:              # PyMuPDF takes the path as UTF-8 (KNOWN-ISSUES 175)
        return _pdf_shots(at, workdir, want)


def _pdf_shots(path, workdir, want):
    try:
        import pymupdf
    except Exception as _dbg_e:                                     # noqa: BLE001
        debuglog.exc("pdf shots: import", _dbg_e)
        return [], 0
    try:
        doc = pymupdf.open(path)
    except Exception as _dbg_e:                                     # noqa: BLE001
        debuglog.exc("pdf shots: open", _dbg_e)
        return [], 0
    shots = os.path.join(workdir, "shots")
    try:
        os.makedirs(shots, exist_ok=True)
    except OSError:
        return [], 0
    needed, entries, taken = 0, [], 0
    for page in doc:
        try:
            zoom = SHOT_WIDTH / float(page.rect.width or 1)
            total_pt = float(page.rect.height or 1)
        except Exception:                                 # noqa: BLE001
            continue
        needed += max(1, -(-int(total_pt * zoom) // screens.SCREEN_H))
        per_tile_pt = SHOT_HEIGHT / zoom
        n = max(1, int((total_pt + per_tile_pt - 1) // per_tile_pt))
        for i in range(n):
            if taken >= want:
                continue
            y0 = i * per_tile_pt
            rect = pymupdf.Rect(0, y0, page.rect.width, min(y0 + per_tile_pt, total_pt))
            try:
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect)
                data, fmt = pix.tobytes("png"), "png"
                if len(data) > screens.MAX_BYTES:
                    data, fmt = pix.tobytes("jpg", jpg_quality=screens.JPEG_Q), "jpg"
            except Exception:                             # noqa: BLE001
                continue
            rel = "shots/%02d.%s" % (len(entries) + 1, fmt)
            try:
                with open(os.path.join(workdir, rel.replace("/", os.sep)), "wb") as fh:
                    fh.write(data)
            except OSError:
                continue
            k = max(1, -(-int(pix.height) // screens.SCREEN_H))
            entries.append({"file": rel, "width": int(pix.width), "height": int(pix.height),
                            "bytes": len(data), "format": fmt, "screens": list(range(taken + 1, taken + k + 1))})
            taken += k
    try:
        doc.close()
    except Exception:                                     # noqa: BLE001
        pass
    return entries, needed


_CHROME_ERROR = re.compile(r"id=\"main-frame-error\"|class=\"neterror\"|<body[^>]*class=\"[^\"]*neterror", re.I)


# a static page that admits it is not ready yet: a mount node that is empty or says "Loading..."
STATIC_SHELL = re.compile(r"(?is)<(div|main)\b[^>]*\bid=[\"'](root|app|__next|___gatsby|svelte)[\"'][^>]*>\s*</\1>"
                          r"|<(main|div|section)\b[^>]*>\s*(loading|please wait|загрузка|подождите)[\s.…]*</\3>")
# A page of a few words that ships its content as data for its own scripts is an app with a
# teaser: the browser has the rest. Measured on 168 HTML pages (2026-11-19): four
# were under 200 words beside 40 KB+ of such data and no browser had run - it then gave 30, 9 and
# 5 times the text on three (soundcloud 50 -> 1 526 words, aliexpress 79 -> 680, ivi 163 -> 809)
# and the same on one (a GitHub issue). No wider rule held: of 26 more script-heavy pages under
# 2 000 words the browser added half as much again on four and lost text on two.
THIN_APP_WORDS = 200
THIN_APP_STATE = 40000
_STATE_GLOBAL = re.compile(r"__NEXT_DATA__|__NUXT__|__INITIAL_STATE__|__APOLLO_STATE__|__PRELOADED_STATE__"
                           r"|window\.__[A-Za-z_]+\s*=\s*[\[{]")


def shipped_state(html):
    """Bytes of the data a page carries for its own scripts to draw: an inline script that is
    JSON, or one that starts by filling a framework's state. Not JSON-LD, which is for search
    engines and drawn by no script (a product page of 144 words with its reviews as 63 KB of it
    went to the browser for 3.2 s and the same words, 2026-11-21)."""
    n = 0
    for m in re.finditer(r"(?is)<script\b([^>]*)>(.*?)</script>", html or ""):
        body = m.group(2)
        if re.search(r"(?i)\btype\s*=\s*[\"']?application/ld\+json", m.group(1)):
            continue
        if len(body) >= 1000 and (re.match(r"\s*[\[{]", body) or _STATE_GLOBAL.search(body[:400])):
            n += len(body)
    return n


def browser_error_page(html, inner, landed):
    """The browser's own page instead of the site's ("This site can't be reached", ERR_...,
    "HTTP ERROR 503"): its code, or "" for a real page."""
    if not ((landed or "").startswith("chrome-error://") or _CHROME_ERROR.search((html or "")[:30000])):
        return ""
    m = re.search(r"(ERR_[A-Z_]+|HTTP ERROR \d{3})", (inner or "") + " " + (html or "")[:30000])
    return m.group(1) if m else "a browser error page"


def guard_requests(ctx, url, text_only=False):
    """A public page's scripts, frames, meta refreshes and sockets may not reach the local network
    or a non-web scheme: such a request is aborted and counted (signals.browser_blocked), so a
    page cannot read an internal service through our browser and hand it back as its text. An
    internal page may use internal resources. Returns the list the blocked URLs land in.
    text_only: the media and fonts a text render does not need are aborted in the same round trip
    (pictures never start: the browser is launched with them off)."""
    blocked = []
    if host_is_private(url):
        return blocked

    def check(route):
        q = route.request
        target = q.url
        try:
            if text_only and q.resource_type in ("image", "media", "font"):
                route.abort("blockedbyclient")
                return
            why = "" if target.startswith(("data:", "blob:", "about:")) else hop_refused(url, target)
            if why:
                blocked.append(target[:200])
                trace("browser.blocked", url=target[:120], why=why)
                route.abort("blockedbyclient")
            else:
                route.continue_()
        except Exception as _dbg_e:                                      # noqa: BLE001
            debuglog.exc("guard: route", _dbg_e)

    ctx.route("**/*", check)

    def check_socket(ws):
        target = ws.url
        web = ("http" + target[2:]) if target.lower().startswith("ws") else target   # wss -> https
        try:
            if hop_refused(url, web):
                blocked.append(target[:200])
                ws.close()
            else:
                ws.connect_to_server()
        except Exception as _dbg_e:                                      # noqa: BLE001
            debuglog.exc("guard: websocket", _dbg_e)

    if hasattr(ctx, "route_web_socket"):                       # Playwright 1.48+
        try:
            ctx.route_web_socket(re.compile(".*"), check_socket)
        except Exception as _dbg_e:                                      # noqa: BLE001
            debuglog.exc("guard: websocket route", _dbg_e)
    return blocked


WALL_LOAD_SECONDS = 10.0       # a page HTTP met as a wall: at most this long to DOMContentLoaded


def render(url, c, shots=0, shot_dir="", wall=False):
    """The page in a browser: up to BROWSER_TRIES browsers that fail to start, BROWSER_TIMEOUT_MS
    for the load and the settle rule (settle.py) in the one that starts; a timeout keeps the DOM.

    The browser runs in a thread of its own, and the answer comes as soon as the DOM is taken:
    saving the site's cookies and closing the browser (0.2 s on a fast machine, 0.8 s on a weak laptop) go on
    while the read extracts the text; browsers_close() waits for them at the end. A text-only
    render (no screenshots) loads no pictures, media or fonts: 8 % of the browser's CPU on a fast machine."""
    if "browser" in SKIP:
        _BROWSER_UP.set()
        return None, "disabled by READ_PAGE_SKIP"
    if not (c.get("browsers") or []):
        _BROWSER_UP.set()                          # nothing to wait for
        return None, "no browser found"
    box, ready = {}, threading.Event()
    t0 = now()
    step_cap = budget.cap(BROWSER_STEP_SECONDS, browser_reserve(), floor=1.0)
    t = threading.Thread(target=_render_thread, args=(url, c, shots, shot_dir, box, ready, wall), daemon=True)
    t.start()
    _BROWSER_THREADS.append(t)
    # the thread bounds itself (launch, load and the settle rule); this wait is the backstop for a
    # page whose scripts hold the browser for good, and it never runs past half the tail
    ready.wait(max(1.0, min(step_cap + 5, budget.left(budget.tail() * 0.5))))
    out = box.get("out")
    if out:
        reason = str(out.get("waited") or "")
        load_cap = float(out.get("load_cap") or BROWSER_TIMEOUT_MS / 1000.0)
        # cut: the settle rule ran out of time, or DOMContentLoaded never came (a wall gets 10 s)
        end = (budget.ended(BROWSER_TIMEOUT_MS / 1000.0, load_cap) if reason.startswith("deadline")
               else "fail" if out.get("error_page") else "cap" if out.get("partial") else "ok")
        budget.record("browser", t0, end, own=BROWSER_STEP_SECONDS, given=step_cap,
                      note="%s; %s; %s%s" % (out.get("engine"), out.get("phases") or "", reason,
                                             "; no DOMContentLoaded" if out.get("partial") else ""))
        return out, ""
    err = box.get("err") or "the browser did not answer in time"
    budget.record("browser", t0, budget.ended(BROWSER_STEP_SECONDS, step_cap) if "in time" in err else "fail",
                  own=BROWSER_STEP_SECONDS, given=step_cap, note=err)
    return None, err


def _render_thread(url, c, shots, shot_dir, box, ready, wall=False):
    try:
        _render(url, c, shots, shot_dir, box, ready, wall)
    except Exception as e:                                     # noqa: BLE001
        debuglog.exc("browser: thread", e)
        box.setdefault("err", "%s: %s" % (type(e).__name__, str(e)[:120]))
    finally:
        _BROWSER_UP.set()                                      # however it ended, none waits on it
        ready.set()
        g = box.get("guard")
        if g is not None:
            g.close()                                          # the browser is closed by now


def _render(url, c, shots, shot_dir, box, ready, wall=False):
    libs = c["libs"]
    want = (c.get("libs", {}).get("patchright") and "patchright") or \
           ("playwright" if libs.get("playwright") else "")
    if "playwright" in SKIP:
        want = ""                               # READ_PAGE_SKIP=playwright: Chrome's --dump-dom path
    errors = []
    text_only = not (shots and shot_dir)
    cands = c.get("browsers") or []
    if text_only and want:
        # A/B 2026-11-06, read-page's own browser step on 67 sites: Playwright's headless shell
        # took p50 4.6 s against Chrome's 5.2 on a fast machine and 6.4 against 13.2 on an emulated Celeron
        # (faster on all 36 pages there), with the same text and the same walls. A text-only
        # render takes it first when it is installed; screenshots keep a full Chrome.
        cands = ([b for b in cands if b.get("name") == "playwright-shell"]
                 + [b for b in cands if b.get("name") != "playwright-shell"])

    # Our way out for a public page (netguard): every connection checked once, on the addresses it
    # goes to. It steps aside for an internal page (its own resources are inside), a machine whose
    # browser has a proxy of its own, READ_PAGE_SKIP=netguard and WebKit; the request rule is the
    # guard there, with a watch for a redirect hop that answered from inside.
    public = not host_is_private(url)
    aside = ("an internal page" if not public else "READ_PAGE_SKIP=netguard" if "netguard" in SKIP
             else system_proxy())
    guard = None
    if not aside:
        try:
            guard = netguard.Guard(browser_policy, log=lambda ev, **kw: debuglog.log("net", ev=ev, **kw)).start()
        except OSError as e:
            aside = "the guard could not start: %s" % str(e)[:80]
            debuglog.exc("netguard: start", e)
    inside_watch = [] if (public and guard is None) else None
    box["guard"] = guard
    debuglog.log("decide", what="browser guard", mode="netguard" if guard else "request rule" if public else "none",
                 why=aside or "a public page", port=guard.port if guard else None)

    def grab(page, t0, label):
        # A timeout is not a failure: a page that paints slowly still has a DOM, and half a
        # page beats "empty". We keep it and flag `partial`. One budget per browser covers the
        # load and the settle rule (settle.py, measured on 67 sites on a fast machine and on a weak laptop).
        partial = False
        load_cap = min(BROWSER_TIMEOUT_MS / 1000.0, max(1.0, budget.left(browser_reserve())))
        t_page = now()
        end = t_page + load_cap
        inflight = set()
        try:
            page.on("request", lambda q: inflight.add(q) if q.resource_type in settle.BUSY_TYPES else None)
            page.on("requestfinished", lambda q: inflight.discard(q))
            page.on("requestfailed", lambda q: inflight.discard(q))
            if inside_watch is not None:
                # the request rule sees only a redirect chain's first URL: a hop that answered
                # from inside the network is caught here, and the DOM is then not used
                page.on("response", lambda r: inside_watch.append(r.url) if hop_refused(url, r.url) else None)
            if debuglog.enabled():
                # every response and failure the page meets, redirect hops included
                page.on("response", lambda r: debuglog.log(
                    "net", ev="response", url=debuglog.mask_url(r.url), status=r.status,
                    type=r.request.resource_type, method=r.request.method,
                    hop_from=debuglog.mask_url(r.request.redirected_from.url) if r.request.redirected_from else ""))
                page.on("requestfailed", lambda q: debuglog.log(
                    "net", ev="failed", url=debuglog.mask_url(q.url), type=q.resource_type, failure=q.failure or ""))
        except Exception as _dbg_e:                            # noqa: BLE001
            debuglog.exc("browser: request listeners", _dbg_e)
        try:
            # a wall's challenge that has not even loaded in 10 s is looping (wildberries once held
            # the whole 20 s); a page that loads keeps the full budget for the settle rule
            resp = page.goto(url, wait_until="domcontentloaded", timeout=max(1000, int(
                min(end - now(), WALL_LOAD_SECONDS if wall else 1e9) * 1000)))
        except Exception as _dbg_e:                            # noqa: BLE001
            debuglog.exc("browser: goto", _dbg_e)
            partial = True
            resp = None
        status = resp.status if resp else 0
        loaded = now()
        debuglog.log("browser", what="loaded", status=status, no_dcl=partial, load_s=round(loaded - t_page, 2),
                     cap_s=round(load_cap, 1), wall_cap_s=WALL_LOAD_SECONDS if wall else None,
                     url=debuglog.mask_url(url))
        rule = settle.Settle(loaded, status)
        waited = ""
        polls = late_polls = 0
        last_key, last_t = None, loaded
        while now() < end:
            page.wait_for_timeout(100)
            try:
                chars, msize, mhead, chl = page.evaluate(settle.PROBE)
            except Exception as _dbg_e:                    # the page navigated under us (SPA redirect)
                debuglog.exc("browser: settle probe", _dbg_e)
                page.wait_for_timeout(300)
                continue
            t_poll = now()
            waited = rule.see(t_poll, int(chars or 0), int(msize if msize is not None else -1),
                              mhead or "", bool(chl), bool(inflight))
            if debuglog.enabled():
                # every change the settle rule saw: text, mount node, a challenge, the network
                # going busy or quiet, a poll the page's scripts held back
                polls += 1
                late = t_poll - last_t > settle.GAP
                late_polls += int(late)
                key = (int(chars or 0), int(msize if msize is not None else -1), bool(chl), bool(inflight))
                if key != last_key or late or waited:
                    debuglog.log("browser", what="poll", at=round(t_poll - loaded, 2), chars=key[0], mount=key[1],
                                 mount_head=(mhead or "")[:60], challenge=key[2], inflight=len(inflight), late=late,
                                 stable=round(t_poll - rule.since, 2), quiet=round(t_poll - rule.busy_at, 2),
                                 done=waited or "")
                last_key = key
            last_t = t_poll
            if waited:
                break
        waited = "%s %.1f s" % (waited or "deadline", now() - loaded)
        debuglog.log("browser", what="settled", waited=waited, polls=polls, late_polls=late_polls,
                     inflight_left=len(inflight), inflight_types=sorted({q.resource_type for q in list(inflight)}))
        t_dom = now()
        html = inner = visible = ""
        for attempt in (1, 2):
            try:
                html = page.content()
                inner = page.evaluate("document.body ? document.body.innerText : ''")
                break
            except Exception as _dbg_e:                    # navigation in flight: settle and try once more
                debuglog.exc("browser: content", _dbg_e)
                page.wait_for_timeout(500)
        try:
            visible = page.evaluate(VISIBLE_DOM) or ""
        except Exception as _dbg_e:                        # noqa: BLE001
            debuglog.exc("browser: visible DOM", _dbg_e)
            visible = ""
        shot_entries, shot_needed, shot_why = ([], 0, "")
        if shots and shot_dir and not _RENDER_STOP.is_set():
            shot_entries, shot_needed, shot_why = capture_shots(page, shot_dir, shots)
            if shot_entries and not html:
                try:                                        # the DOM the tiles show, for the text
                    html = page.content()
                    inner = page.evaluate("document.body ? document.body.innerText : ''")
                except Exception as _dbg_e:                           # noqa: BLE001
                    debuglog.exc("browser: content after shots", _dbg_e)
        try:
            landed = page.url or ""
        except Exception:                                   # noqa: BLE001
            landed = ""
        phases = "start %.1f, load %.1f, settle %.1f, dom %.1f s" % (
            t_page - t0, loaded - t_page, t_dom - loaded, now() - t_dom)
        inside = sorted(set(inside_watch or []))
        return {"html": html, "inner": inner, "visible": visible, "waited": waited,
                "shots": shot_entries, "shots_needed": shot_needed, "shots_why": shot_why,
                "status": status or None, "final": landed, "load_cap": load_cap, "phases": phases,
                "error_page": browser_error_page(html, inner, landed), "inside": inside,
                "partial": partial, "engine": label, "ms": int((now() - t0) * 1000)}

    if want:
        mod = "patchright.sync_api" if want == "patchright" else "playwright.sync_api"
        try:
            from importlib import import_module
            sync_playwright = import_module(mod).sync_playwright
        except Exception as e:                                # noqa: BLE001
            debuglog.exc("browser: import", e)
            box["err"] = "cannot import %s: %s" % (mod, str(e)[:80])
            return
        step_end = now() + budget.cap(BROWSER_STEP_SECONDS, browser_reserve())
        args = ["--blink-settings=imagesEnabled=false"] if text_only else []
        if guard is not None:
            # behind netguard the request rule is gone: fonts and media are off by flags, and
            # WebRTC may not open UDP of its own past the proxy
            args = args + ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"] + (
                ["--disable-remote-fonts", "--autoplay-policy=user-gesture-required"] if text_only else [])
        for b in cands[:BROWSER_TRIES]:
            if errors and now() > step_end - 5:
                break                                 # the step's time is spent
            t0 = now()
            started = False
            try:
                with sync_playwright() as pw:
                    launch_ms = int(max(1.0, min(20.0, step_end - now())) * 1000)
                    debuglog.log("browser", what="launch", name=b.get("name"), kind=b.get("kind"),
                                 path=b.get("path") or b.get("channel"), lib=want, text_only=text_only, args=args,
                                 timeout_ms=launch_ms, driver_s=round(now() - t0, 2))
                    # Playwright adds --proxy-bypass-list=<-loopback> (Chrome would send localhost past
                    # any proxy) and, for SOCKS5, host resolver rules that leave every name to it
                    proxy = {"server": guard.server} if guard is not None else None
                    if b.get("kind") == "webkit":
                        br = pw.webkit.launch(timeout=launch_ms)
                    elif b.get("kind") == "channel":
                        br = pw.chromium.launch(channel=b["channel"], args=args, timeout=launch_ms, proxy=proxy)
                    else:
                        br = pw.chromium.launch(executable_path=b["path"], args=args, timeout=launch_ms, proxy=proxy)
                    started = True
                    # service workers are off: a request one of them makes is not routed
                    # screenshots: a laptop's window and reduced motion (screens.py)
                    # the locale is the browser's Accept-Language too (one tag: Chromium sends it in place of
                    # any header given beside it, and navigator.languages says the same)
                    ctx = br.new_context(locale=intl.browser_locale(), service_workers="block", **(
                        {"viewport": {"width": screens.SCREEN_W, "height": screens.SCREEN_H},
                         "reduced_motion": "reduce"} if not text_only else {}))
                    blocked = (guard_requests(ctx, url, text_only=text_only)
                               if guard is None or b.get("kind") == "webkit" else [])
                    try:                             # the session the HTTP tiers already hold
                        ck = pw_cookies(url)
                        if ck:
                            ctx.add_cookies(ck)
                            _COOKIE_STATS["sent"] += 1     # only once the context really has it
                    except Exception as e:           # noqa: BLE001
                        debuglog.exc("browser: cookies in", e)
                        trace("browser.cookies.failed", error=str(e)[:120])
                    page = ctx.new_page()
                    _BROWSER_UP.set()                # started: the HTTP pass's slower extractors go
                    if debuglog.enabled():
                        debuglog.log("browser", what="page open", name=b.get("name"), open_s=round(now() - t0, 2),
                                     guard=not host_is_private(url), cookies=bool(_COOKIE_STATS["sent"]))
                    try:
                        out = grab(page, t0, "browser:%s:%s" % (want, b["name"]))
                        out["blocked"] = list(blocked) + (
                            ["%s:%s (%s)" % (x["host"], x["port"], x["why"]) for x in guard.refused]
                            if guard is not None else [])
                        out["guard"] = "netguard" if guard is not None else "request rule" if public else ""
                        box["out"] = out
                        ready.set()                  # the read goes on; the browser closes here
                    finally:
                        save_browser_cookies(ctx, url)   # a cookie set in JS is the site's session
                        ctx.close()
                        br.close()
                return
            except Exception as e:                            # noqa: BLE001
                debuglog.exc("browser: launch or page", e)
                errors.append("%s: %s" % (b["name"], str(e)[:70]))
                if "out" in box:
                    return                            # it failed while closing: the DOM is taken
                if started:
                    # it started and failed on the page: another Chromium build fails the same way,
                    # and a second try doubled the worst case
                    box["err"] = "; ".join(errors)[:300]
                    return
    # no browser library (or none would start): the first Chromium executable directly
    _BROWSER_UP.set()                       # one process to the end: nothing to wait for
    step_end = now() + budget.cap(BROWSER_STEP_SECONDS, browser_reserve())
    for b in cands[:BROWSER_TRIES]:
        if not b.get("path"):
            continue
        if errors and now() > step_end - 5:
            break
        # a throwaway profile: without --user-data-dir Chrome writes an ordinary one into HOME
        # (or opens the user's own), and a reader has no business there
        profile = tempfile.mkdtemp(prefix="rp-chrome-")
        t1 = now()
        try:
            via = ([] if guard is None else
                   ["--proxy-server=" + guard.server, "--proxy-bypass-list=<-loopback>",
                    "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
            debuglog.log("browser", what="launch", name=b.get("name"), path=b.get("path"), lib="--dump-dom",
                         guard=guard is not None)
            rc, so, se = run([b["path"], "--headless=new", "--no-first-run", "--disable-gpu",
                              "--user-data-dir=" + profile] + via +
                             ["--virtual-time-budget=8000", "--dump-dom", url],
                             timeout=budget.cap(15, browser_reserve(), floor=1.0))
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        if rc == 0 and so.strip():
            dom = so.decode("utf-8", "replace")
            box["out"] = {"html": dom, "inner": "", "status": None, "final": url,
                          "error_page": browser_error_page(dom, "", url),
                          "engine": "browser:cli:%s" % b["name"], "ms": int((now() - t1) * 1000)}
            return
        errors.append("%s: cli failed" % b["name"])
        if now() - t1 > 3:
            break                     # it ran and gave nothing: not a start-up failure
    box["err"] = "; ".join(errors)[:300]


# ---------------------------------------------------------------- documents

def magic(body):
    if body[:4] == b"%PDF":
        return "pdf"
    if body[:2] == b"PK":
        return "zip"
    if body[:5] == b"{\\rtf":
        return "rtf"
    return ""


def zip_subtype(src):
    """docx / xlsx / pptx / epub / other, from the archive's own table of contents."""
    try:
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(src)) if isinstance(src, (bytes, bytearray)) else zipfile.ZipFile(src)
        names = z.namelist()
    except Exception:                                         # noqa: BLE001
        return "other"
    if any(n.startswith("word/") for n in names):
        return "docx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    # an archive's own `mimetype` says what it is - an OpenDocument file has one too, and was
    # taken for an EPUB before the value was read. Its first bytes are all of it (one that unpacked
    # to gigabytes was read whole, KNOWN-ISSUES 133)
    try:
        kind = zip_part(z, "mimetype", 256).decode("ascii", "replace").strip() if "mimetype" in names else ""
    except Exception:                                         # noqa: BLE001
        kind = ""
    if kind == "application/epub+zip" or (not kind and any(n.endswith(".opf") for n in names)):
        return "epub"
    for sub, mime in (("odt", "opendocument.text"), ("ods", "opendocument.spreadsheet"),
                      ("odp", "opendocument.presentation")):
        if mime in kind:
            return sub
    if not kind and "content.xml" in names and "META-INF/manifest.xml" in names:
        return "odt"
    return "other"


# ---------------------------------------------------------------- an archive that does not open whole
# zipfile reads an archive by its table of contents, which is at its end: a file cut short has none,
# and one that is no ZIP at all has none either. Both were answered "no converter for this file
# type", after a machine's markitdown had spent its 4 s on them (KNOWN-ISSUES 167). A cut or damaged
# archive's members are read one after another from their own headers instead, and the whole ones
# go into an archive of their own, which the readers take as they take any; a file that is no ZIP
# is named for what it is. What one archive may unpack is capped as the readers' parts are, and so
# is the work of looking at it: every byte unpacked counts, a member kept or not (members past the
# size limit or with a wrong CRC were each unpacked to 32 MB and thrown away uncounted - 2 000 of
# them, 62 MB of file, held the read 44 s), and the read's clock is looked at every member.
ZIP_WHOLE_PART = 32 * 1024 * 1024      # one member of an archive read so, unpacked
ZIP_WHOLE_TOTAL = 128 * 1024 * 1024    # all of them together
ZIP_WHOLE_SPENT = 2 * ZIP_WHOLE_TOTAL  # every byte unpacked (or read) to judge the members, kept or not
ZIP_WHOLE_MEMBERS = 10000              # members looked at; past them the rest is not
_ZIP_LOCAL = struct.Struct("<4sHHHHHIIIHH")      # a member's own header (30 bytes)
_ZIP_TOC = (b"PK\x01\x02", b"PK\x05\x06", b"PK\x06\x06")   # the table of contents: its entries, its end


class _PerThread(object):
    """A dict of the thread that uses it: the archive's background read (archived_text -> doc_text) has
    its own, so a live archive's broken state and an archived copy's are never mixed (they shared one)."""

    def __init__(self):
        self._local = threading.local()

    def _d(self):
        d = getattr(self._local, "d", None)
        if d is None:
            d = self._local.d = {}
        return d

    def get(self, key, default=None):
        return self._d().get(key, default)

    def __getitem__(self, key):
        return self._d()[key]

    def __setitem__(self, key, value):
        self._d()[key] = value

    def clear(self):
        self._d().clear()


_ZIPS = _PerThread()                   # "read": what was wrong with the read's own archive, or None
# what a file whose name or type says ZIP may really be, by its first bytes
NOT_ZIP = ((b"\x1f\x8b", "a gzip file"), (b"7z\xbc\xaf\x27\x1c", "a 7-Zip archive"),
           (b"Rar!\x1a\x07", "a RAR archive"), (b"BZh", "a bzip2 file"), (b"\xfd7zXZ\x00", "an xz file"),
           (b"\x28\xb5\x2f\xfd", "a zstd file"), (b"MSCF", "a Windows cabinet file"),
           (b"\x89PNG", "a PNG picture"), (b"\xff\xd8\xff", "a JPEG picture"), (b"GIF8", "a GIF picture"),
           (b"MZ", "a Windows program"), (b"\x7fELF", "a Linux program"))
OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# the streams that say what an OLE2 compound file holds (their names are UTF-16 in its directory)
OLE2_KINDS = (("EncryptedPackage", "a password-protected Office file (its document is encrypted)"),
              ("WordDocument", "a Word 97-2003 document (.doc)"),
              ("Workbook", "an Excel 97-2003 workbook (.xls)"),
              ("PowerPoint Document", "a PowerPoint 97-2003 presentation (.ppt)"))


def not_zip(path):
    """What a file whose name or type says ZIP is, when it does not start like one: a phrase ("a
    Word 97-2003 document (.doc)", "text"), or "" when it starts as a ZIP does."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8192)
            if head[:8] == OLE2:
                fh.seek(0)
                body = fh.read(64 * 1024 * 1024)       # the directory may stand anywhere: a linear find
                for stream, what in OLE2_KINDS:
                    if (stream.encode("utf-16-le") + b"\x00\x00") in body:
                        return what
                return "an OLE2 compound file (an old Office format)"
    except OSError:
        return ""
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return ""
    if not head:
        return "an empty file"
    for magic_bytes, what in NOT_ZIP:
        if head.startswith(magic_bytes):
            return what
    if head[257:262] == b"ustar":
        return "a tar archive"
    if not looks_binary(head):
        return "text"
    return "data of no type this skill knows"


def _zip64_sizes(extra, usize, csize):
    """The sizes a member's own header gives, its ZIP64 field (0x0001) read: (unpacked, packed,
    whether it has that field - then the sizes after its data are 8 bytes each)."""
    i = 0
    while i + 4 <= len(extra):
        tag, n = struct.unpack("<HH", extra[i:i + 4])
        if tag == 1:
            vals = extra[i + 4:i + 4 + n]
            k = 0
            if usize == 0xFFFFFFFF and len(vals) >= k + 8:
                usize = struct.unpack("<Q", vals[k:k + 8])[0]
                k += 8
            if csize == 0xFFFFFFFF and len(vals) >= k + 8:
                csize = struct.unpack("<Q", vals[k:k + 8])[0]
            return usize, csize, True
        i += 4 + n
    return usize, csize, False


def _inflate(fh, csize, room, keep=False):
    """A deflated member's data from `fh` (at its start): (data, packed length, why, unpacked).
    csize None: its length is not in its header (a data descriptor follows the data), the stream's
    end tells it. why is "" for data that ends where the stream does, "cut", "breaks" or "over"
    (more than `room` bytes unpacked: read no further); `unpacked` is what was unpacked, kept or
    not. `keep`: a member the file ends in gives what it unpacked up to there ("cut"). The file is
    read 64 KB at first, then twice as much each time up to 1 MB: a small member whose size follows
    its data was read a megabyte ahead (10 000 of them in 700 KB took 2.7 s)."""
    d = zlib.decompressobj(-zlib.MAX_WBITS)
    out, n, used, step = [], 0, 0, 1 << 16
    left = csize
    try:
        while not d.eof:
            want = step if left is None else min(step, left)
            step = min(step * 2, 1 << 20)
            chunk = fh.read(want) if want else b""
            if not chunk:
                cut = left is None or left
                return b"".join(out) if keep and cut else b"", used, "cut" if cut else "breaks", n
            used += len(chunk)
            if left is not None:
                left -= len(chunk)
            data = chunk
            while data and not d.eof:
                piece = d.decompress(data, room + 1 - n)
                out.append(piece)
                n += len(piece)
                if n > room:
                    return b"", used, "over", n
                data = d.unconsumed_tail
    except zlib.error:
        return b"", used, "breaks", n
    return b"".join(out), used - len(d.unused_data), "", n


def _read_counted(fh, cap, meter):
    """Up to `cap` bytes of an open member, a megabyte at a time, each counted in meter[0] as it
    comes: a member whose CRC fails at its end has been unpacked all the same."""
    parts = []
    while cap > 0:
        b = fh.read(min(cap, 1 << 20))
        if not b:
            break
        meter[0] += len(b)
        cap -= len(b)
        parts.append(b)
    return b"".join(parts)


def _end_record(fh, size):
    """Whether the file's last 64 KB (and the 22 bytes of the record) hold a table of contents' end
    record: without one the file is cut, not damaged, where its table of contents stands."""
    back = min(size, 65536 + 22)
    fh.seek(size - back)
    return b"PK\x05\x06" in fh.read(back)


class _ZipOut(object):
    """A new archive at `dest`, stored, written a member at a time: one member is in memory, never
    all (an office package's index parts wait in files beside it - they were kept in memory, 128 MB
    of them at most); the file is made at the first member. An office package is made to hold
    together from the parts it has, as python-docx, python-pptx and openpyxl give up on one that
    does not (_package_close): each relationship to a part it lacks is taken out, and so are the
    sheets and slides of the main part whose relationship went; what is missing of its index - its
    content types, its root relationships, a workbook's list of sheets - is written from the parts
    there (openpyxl writes them last: a workbook it made, cut anywhere in its sheets, had none). A
    workbook's shared strings are made to hold what its sheets ask for (_strings_close), and the
    member the archive was cut in, `partial`, is taken as far as it arrived (_PART_IN_PART)."""

    def __init__(self, dest):
        self.dest, self.w, self.names, self.held = dest, None, [], []
        self.partial, self.lost = "", None     # the member read up to the cut; what lost strings cost
        self.strings = array.array("q")      # the shared strings a workbook's sheets hold, by index

    def add(self, name, data, partial=False):
        """One member; `partial`: what arrived of the one the archive was cut in (a sheet of it is
        taken up to its last whole row). False when nothing of it can be read."""
        sheet = bool(_XL_SHEET.match(name))
        if partial and sheet:
            data = _cut_sheet(data)
            if data is None:
                return False
        if partial:
            self.partial = name
        self.names.append(name)
        if sheet:
            self.strings.extend(int(m.group(1)) for m in _SHARED_CELL.finditer(data))
        if name.endswith(".rels") or name in _PACKAGE_INDEX or name == _XL_STRINGS:
            spill = "%s.%d.part" % (self.dest, len(self.held))
            with open(spill, "wb") as fh:
                fh.write(data)
            self.held.append((name, spill))
            return True
        self._write(name, data)
        return True

    def _write(self, name, data):
        import zipfile
        if self.w is None:
            self.w = zipfile.ZipFile(self.dest, "w", zipfile.ZIP_STORED)
        self.w.writestr(zipfile.ZipInfo(name), data)

    def close(self):
        try:
            names = set(self.names)
            kind = next((k for k, top in (("docx", "word/"), ("xlsx", "xl/"), ("pptx", "ppt/"))
                         if any(n.startswith(top) for n in names)), "")
            if kind:
                _package_close(self, kind, names)
            else:
                for name, spill in self.held:
                    with open(spill, "rb") as fh:
                        self._write(name, fh.read())
            if self.w is not None:
                self.w.close()
        finally:
            for _name, spill in self.held:
                try:
                    os.unlink(spill)
                except OSError:
                    pass


# what a package's index is made of: held back until every member is known (_ZipOut)
_PACKAGE_INDEX = ("[Content_Types].xml", "xl/workbook.xml", "ppt/presentation.xml")
# the members a reader can take as far as they arrived, the archive cut in them (zip_salvage): an
# OpenDocument file's content.xml (our readers read XML that breaks up to where it breaks), a
# workbook's shared strings and its sheets (made whole again: _cut_sheet, _strings_close)
_PART_IN_PART = re.compile(r"(?:content\.xml|xl/sharedStrings\.xml|xl/worksheets/sheet\d{1,6}\.xml)$")
_XL_STRINGS = "xl/sharedStrings.xml"
_XL_SHEET = re.compile(r"xl/worksheets/sheet\d{1,6}\.xml$")
_XL_MAIN = b"http://schemas.openxmlformats.org/spreadsheetml/2006/main"
# a cell whose value is a shared string, and its index: <c r="A1" s="3" t="s"><v>12</v>
_SHARED_CELL = re.compile(rb"<(?:\w{1,32}:)?c\b(?=[^<>]{0,%d}?\bt=[\"']s[\"'])[^<>]{0,%d}>\s*<(?:\w{1,32}:)?v>\s*(\d{1,10})\s*<"
                          % (docreaders.TAG_MAX, docreaders.TAG_MAX))
LOST_TEXT = "[lost]"                   # a cell whose shared string was lost with the archive's cut
LOST_MAX = 1 << 20                     # stand-ins made at most (23 MB of XML): a real table past it is rare


def _cut_sheet(data):
    """A worksheet the archive was cut in: its rows up to the last whole one, its sheetData and its
    root closed again (openpyxl reads no XML that breaks); None when the cut came before its rows."""
    root = re.search(rb"<(\w{1,32}:)?worksheet\b[^<>]{0,%d}>" % TAG_MAX, data)
    if not root:
        return None
    p = root.group(1) or b""
    last = None
    for last in re.finditer(rb"</%srow\s*>" % re.escape(p), data):
        pass
    if last is not None:
        return data[:last.end()] + b"</%ssheetData></%sworksheet>" % (p, p)
    rows = re.search(rb"<%ssheetData\b[^<>]{0,%d}?(/?)>" % (re.escape(p), TAG_MAX), data)
    if not rows:
        return None
    return data[:rows.end()] + (b"" if rows.group(1) else b"</%ssheetData>" % p) + b"</%sworksheet>" % p


def _strings_close(out, names):
    """A workbook's shared strings made to hold what its sheets ask for: the part as it is when whole;
    cut short, its entries up to the last whole one; lost, none - and a LOST_TEXT for every index
    past them that a sheet holds. openpyxl stopped at the first index it did not have, and a cut
    workbook read nothing: of 9 Excel workbooks cut at 21 points each, 47 % of the cuts lost the
    part whole (it comes after the sheets) and 8 % cut it (2026-11-26). out.lost says what it
    cost; the names, with the part's when it is made here."""
    held = dict(out.held)
    data = None
    if _XL_STRINGS in held:
        with open(held[_XL_STRINGS], "rb") as fh:
            data = fh.read()
    top = max(out.strings) + 1 if out.strings else 0
    if data is not None and out.partial != _XL_STRINGS:
        out._write(_XL_STRINGS, data)                         # whole: as it came
        return names
    if data is None and not top:
        return names                                          # none, and no sheet asks for one
    lost = b"<si><t>%s</t></si>" % LOST_TEXT.encode("ascii")
    head, p, kept = b"", b"", 0
    if data is not None:
        root = re.search(rb"<(\w{1,32}:)?sst\b[^<>]{0,%d}?(/?)>" % TAG_MAX, data)
        p = (root.group(1) or b"") if root else b""
        last = None
        for last in re.finditer(rb"</%ssi\s*>" % re.escape(p), data):
            kept += 1
        head = data[:last.end()] if last is not None else data[:root.end()] if root and not root.group(2) else b""
        if p:
            lost = lost.replace(b"<", b"<" + p).replace(b"<" + p + b"/", b"</" + p)
    if not head:
        head, p = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="%s">' % _XL_MAIN, b""
        lost = b"<si><t>%s</t></si>" % LOST_TEXT.encode("ascii")
    need = max(0, top - kept)
    cells = sum(1 for k in out.strings if k >= kept)
    if need > LOST_MAX:
        # a sheet names a string far past the table: one index of ten digits asked for 220 GB of stand-ins, and the
        # MemoryError read as "damaged, before its first member". None is made: the strings that arrived stay, and
        # openpyxl stops at a cell past them, as it did before stand-ins were made at all
        out.lost = {"cells": cells, "strings": 0, "kept": kept, "too_far": need}
        need = 0
    else:
        out.lost = {"cells": cells, "strings": need, "kept": kept}
    out._write(_XL_STRINGS, head + lost * need + b"</%ssst>" % p)
    return names | {_XL_STRINGS}
_PACKAGE_MAIN = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
_OOXML = "application/vnd.openxmlformats-officedocument."
_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
# a part's content type by its name, for a package whose [Content_Types].xml is lost: the parts the
# readers take by their type (a slide that is no slide part is a part they cannot read)
_PART_TYPES = (
    (r"word/document\.xml", "wordprocessingml.document.main+xml"), (r"word/styles\.xml", "wordprocessingml.styles+xml"),
    (r"word/numbering\.xml", "wordprocessingml.numbering+xml"), (r"word/settings\.xml", "wordprocessingml.settings+xml"),
    (r"word/footnotes\.xml", "wordprocessingml.footnotes+xml"), (r"word/endnotes\.xml", "wordprocessingml.endnotes+xml"),
    (r"word/comments\.xml", "wordprocessingml.comments+xml"), (r"word/header\d*\.xml", "wordprocessingml.header+xml"),
    (r"word/footer\d*\.xml", "wordprocessingml.footer+xml"), (r"word/fontTable\.xml", "wordprocessingml.fontTable+xml"),
    (r"word/webSettings\.xml", "wordprocessingml.webSettings+xml"),
    (r"xl/workbook\.xml", "spreadsheetml.sheet.main+xml"), (r"xl/worksheets/sheet\d+\.xml", "spreadsheetml.worksheet+xml"),
    (r"xl/sharedStrings\.xml", "spreadsheetml.sharedStrings+xml"), (r"xl/styles\.xml", "spreadsheetml.styles+xml"),
    (r"ppt/presentation\.xml", "presentationml.presentation.main+xml"), (r"ppt/slides/slide\d+\.xml", "presentationml.slide+xml"),
    (r"ppt/slideLayouts/slideLayout\d+\.xml", "presentationml.slideLayout+xml"),
    (r"ppt/slideMasters/slideMaster\d+\.xml", "presentationml.slideMaster+xml"),
    (r"ppt/notesSlides/notesSlide\d+\.xml", "presentationml.notesSlide+xml"),
    (r"ppt/notesMasters/notesMaster\d+\.xml", "presentationml.notesMaster+xml"),
    (r"ppt/presProps\.xml", "presentationml.presProps+xml"), (r"ppt/viewProps\.xml", "presentationml.viewProps+xml"),
    (r"ppt/tableStyles\.xml", "presentationml.tableStyles+xml"), (r"(?:word|xl|ppt)/theme/theme\d+\.xml", "theme+xml"),
    (r"docProps/app\.xml", "extended-properties+xml"))
_DEFAULT_TYPES = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml",
                  "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp",
                  "tif": "image/tiff", "tiff": "image/tiff", "emf": "image/x-emf", "wmf": "image/x-wmf",
                  "svg": "image/svg+xml", "bin": "application/vnd.openxmlformats-officedocument.oleObject"}


def _package_close(out, kind, names):
    """An office package's held parts written, its index made to hold together (_ZipOut)."""
    if kind == "xlsx":
        names = _strings_close(out, names)
        # an external link whose own relationships are lost counts as lost: openpyxl takes the first of
        # them, and a whole workbook whose links' relationships came after the cut read nothing
        names = names - {n for n in names if re.match(r"xl/externalLinks/externalLink\d+\.xml$", n) and
                         "xl/externalLinks/_rels/%s.rels" % posixpath.basename(n) not in names}
    held = dict(out.held)

    def part(name):
        with open(held[name], "rb") as fh:
            return fh.read()
    main = _PACKAGE_MAIN[kind]
    dropped, sheets = {}, sorted((n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                                 key=lambda n: int(re.sub(r"\D", "", posixpath.basename(n)) or 0))
    made = []                        # index parts written here, as the package lacked them
    if kind == "xlsx" and sheets and (main not in names or "xl/_rels/workbook.xml.rels" not in names):
        # a workbook whose list of sheets, or the list's relationships, is lost: one of the sheets
        # there, in their order, named as the list named them when it is there
        titles = re.findall(rb'(?is)<(?:\w{1,32}:)?sheet\b[^<>]{0,%d}?\bname\s*=\s*"([^"<>]*)"' % TAG_MAX,
                            part(main)) if main in names else []
        titles = [t.decode("utf-8", "replace") for t in titles] if len(titles) == len(sheets) else []
        entries, rels = [], []
        for k, sheet in enumerate(sheets, 1):
            name = unescape(titles[k - 1]) if titles else "Sheet%d" % k
            entries.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (_xml_attr(name), k, k))
            rels.append('<Relationship Id="rId%d" Type="%sworksheet" Target="%s"/>' % (
                k, _RELS, posixpath.relpath(sheet, "xl")))
        k = len(sheets)
        for extra, rtype in (("xl/sharedStrings.xml", "sharedStrings"), ("xl/styles.xml", "styles")):
            if extra in names:
                k += 1
                rels.append('<Relationship Id="rId%d" Type="%s%s" Target="%s"/>' % (k, _RELS, rtype, extra[3:]))
        held.pop(main, None)
        names = names | {main, "xl/_rels/workbook.xml.rels"}
        dropped["xl/_rels/workbook.xml.rels"] = None          # written here, not from the package's own
        made.append((main, ('<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/'
                            'spreadsheetml/2006/main" xmlns:r="%s"><sheets>%s</sheets></workbook>'
                            % (_RELS[:-1], "".join(entries))).encode("utf-8")))
        made.append(("xl/_rels/workbook.xml.rels", _rels_doc(rels)))
    for name, _spill in out.held:
        if name.endswith(".rels") and name not in dropped:
            data, gone = _rels_kept(name, part(name), names)
            dropped[name] = gone
            out._write(name, data)
    # the main part names its sheets and slides by relationship: one whose relationship went goes too,
    # and so does a workbook's external link or pivot cache (openpyxl stopped at one: "'NoneType' object
    # has no attribute 'Target'", and a government workbook of 5 external links read nothing)
    rels_of_main = posixpath.join(posixpath.dirname(main), "_rels", posixpath.basename(main) + ".rels")
    if main in held:
        data = part(main)
        gone = dropped.get(rels_of_main) or set()
        if gone:
            data = re.sub(rb"(?is)<(?:\w{1,32}:)?(?:sheet|sldId|sldMasterId|notesMasterId|handoutMasterId|"
                          rb"externalReference|pivotCache)\b[^<>]{0,%d}?"
                          rb"\b\w{1,32}:id\s*=\s*\"([^\"<>]*)\"[^<>]{0,%d}?/>" % (TAG_MAX, TAG_MAX),
                          lambda m: b"" if m.group(1).decode("utf-8", "replace") in gone else m.group(0), data)
        out._write(main, data)
    for name, data in made:
        out._write(name, data)
    if "_rels/.rels" not in names and main in names:
        out._write("_rels/.rels", _rels_doc(['<Relationship Id="rId1" Type="%sofficeDocument" Target="%s"/>'
                                             % (_RELS, main)]))
        names = names | {"_rels/.rels"}
    if "[Content_Types].xml" in held:
        out._write("[Content_Types].xml", part("[Content_Types].xml"))
    else:
        exts = sorted({n.rsplit(".", 1)[-1].lower() for n in names if "." in posixpath.basename(n)} & set(_DEFAULT_TYPES))
        over = []
        for n in sorted(names):
            for pattern, ctype in _PART_TYPES:
                if re.match(pattern + "$", n):
                    over.append('<Override PartName="/%s" ContentType="%s%s"/>' % (_xml_attr(n), _OOXML, ctype))
                    break
        if "docProps/core.xml" in names:
            over.append('<Override PartName="/docProps/core.xml" '
                        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>')
        out._write("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types">%s%s</Types>' % ("".join('<Default Extension="%s" ContentType="%s"/>' % (e, _DEFAULT_TYPES[e])
                                                     for e in exts), "".join(over))).encode("utf-8"))


def _rels_doc(rels):
    return ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships">%s</Relationships>' % "".join(rels)).encode("utf-8")


def _xml_attr(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def _rels_kept(name, data, names):
    """A package's .rels with every relationship to a part the archive lacks taken out: (its bytes,
    the ids of the relationships taken out)."""
    folder = posixpath.dirname(posixpath.dirname(name))     # word/_rels/document.xml.rels -> word
    gone = set()

    def keep(m):
        tag = m.group(0).decode("utf-8", "replace")
        target = _attr(tag, "Target") or ""
        if (_attr(tag, "TargetMode") or "").lower() == "external" or not target:
            return m.group(0)
        part = posixpath.normpath(target.lstrip("/") if target.startswith("/") else
                                  posixpath.join(folder, urllib.parse.unquote(target))).lstrip("/")
        if part in names:
            return m.group(0)
        gone.add(_attr(tag, "Id") or "")
        return b""
    data = re.sub(rb"(?is)<Relationship\b[^<>]{0,%d}/>|<Relationship\b[^<>]{0,%d}>\s*</Relationship\s*>"
                  % (TAG_MAX, TAG_MAX), keep, data)
    return data, gone


def zip_salvage(path, dest, until=None):
    """The members of an archive zipfile cannot open, read in order from their own headers: the
    whole ones - stored or deflated, their CRC right, within ZIP_WHOLE_PART and ZIP_WHOLE_TOTAL -
    are written to a new archive at `dest` (not written when none is whole), and the one the file
    was cut in as far as it arrived, where a reader can take one in part (_PART_IN_PART). Returns
    {"how": "cut" | "damaged", "members": how many were found, "whole": their names, "broken":
    [(name, why)], "at": the byte where the reading stopped, "size": the file's, "more": a reason
    the rest was not looked at, or "", "all_members": True when the reading reached the table of
    contents, so no member is missing after the last one read, "partial": the member read in part
    or "", "lost": what a workbook's lost shared strings cost (_strings_close) or None}. Linear:
    each member is read once, its data at most
    up to the caps, and what is unpacked to judge them up to ZIP_WHOLE_SPENT in all; `until` (a
    time.time()) ends the reading at the member it passes."""
    size = os.path.getsize(path)
    found, looked, whole, broken, total, spent, seen = 0, 0, [], [], 0, 0, set()
    how, at, more, toc = "cut", size, "", False
    out = _ZipOut(dest)
    prior = docreaders.machine_cjk()          # a name with no UTF-8 flag: its code page (fix_zip_names)
    oem = docreaders.machine_oem()
    spent_said = ("%s unpacked to look at the members before it; the rest were not looked at"
                  % human_bytes(ZIP_WHOLE_SPENT))
    with open(path, "rb") as fh:
        pos = 0
        while True:
            if pos > size:
                break                              # a member's size runs past the end of the file: cut
            fh.seek(pos)
            head = fh.read(30)
            member = head[:4] == b"PK\x03\x04"
            if looked >= ZIP_WHOLE_MEMBERS and member:
                # folder entries count too: an archive of nothing but them is not walked to its end either
                more = "%d members looked at; the rest were not" % ZIP_WHOLE_MEMBERS
                break
            if member and spent >= ZIP_WHOLE_SPENT:
                more = spent_said
                break
            if member and until is not None and time.time() > until:
                more = "the time for it ran out after %d members; the rest were not looked at" % looked
                break
            if head[:4] in _ZIP_TOC or (0 < len(head) < 4 and any(s.startswith(head) for s in _ZIP_TOC)):
                # its table of contents: every member stands before it. With no end record in the
                # file's last 64 KB the file is cut inside it, its members all there; with one,
                # zipfile could not read what is there
                toc, at = True, pos
                how = "damaged" if _end_record(fh, size) else "cut"
                break
            if len(head) < 30 or not member:
                if len(head) < 30 and b"PK\x03\x04".startswith(head[:4]):
                    at = pos                       # the file ends here, or in a member's header
                else:
                    how, at = "damaged", pos       # bytes that start no member where one should start
                break
            _s, _v, flags, method, _t, _d, crc, csize, usize, nlen, xlen = _ZIP_LOCAL.unpack(head)
            raw_name, extra = fh.read(nlen), fh.read(xlen)
            codec = "utf-8" if flags & 0x800 else (docreaders.names_codec([raw_name], prior, oem) or "cp437")
            name = docreaders.zip_name(raw_name, codec)
            if len(raw_name) < nlen or len(extra) < xlen:
                if len(raw_name) == nlen:          # cut in the middle of a member's header, its name there
                    broken.append((name, "cut"))
                    found += 0 if name.endswith("/") else 1
                at = pos
                break
            usize, csize, zip64 = _zip64_sizes(extra, usize, csize)
            start = pos + 30 + nlen + xlen
            folder = name.endswith("/")
            looked += 1
            found += 0 if folder else 1
            descriptor = bool(flags & 8)           # its CRC and sizes follow its data
            end = None if descriptor else start + csize        # where the next member starts
            limit = min(ZIP_WHOLE_PART, ZIP_WHOLE_TOTAL - total)
            room = min(limit, ZIP_WHOLE_SPENT - spent)
            why, data = "", b""
            in_part = not folder and bool(_PART_IN_PART.match(name))   # a reader takes it as far as it goes
            if flags & 1:
                why = "encrypted"
            elif method not in (0, 8):
                why = "packed in a way this skill does not unpack (method %d)" % method
            elif method == 0 and descriptor:
                why = "its size is not in its header"
            elif method == 0:
                if end > size:
                    why = "cut"                    # its data runs past the end of the file
                    if in_part:
                        data = fh.read(min(size - start, room))
                        spent += len(data)
                elif csize > limit:
                    why = "over the size limit"
                elif csize > room:
                    why = "spent"
                else:
                    data = fh.read(csize)
                    spent += len(data)
                    why = "cut" if len(data) < csize else ""
            else:
                data, packed, why, unpacked = _inflate(fh, None if descriptor else csize, room, keep=in_part)
                spent += unpacked
                if why == "over" and room < limit:
                    why = "spent"
                why = {"over": "over the size limit", "breaks": "its data breaks"}.get(why, why)
                if descriptor and not why:
                    fh.seek(start + packed)
                    tail = fh.read(24)
                    k = 4 if tail[:4] == b"PK\x07\x08" else 0
                    width = 8 if zip64 else 4
                    if len(tail) < k + 4 + 2 * width:
                        why = "cut"
                    else:
                        crc = struct.unpack("<I", tail[k:k + 4])[0]
                        end = start + packed + k + 4 + 2 * width
                elif not descriptor and not why and packed < csize:
                    # the stream ended before the size its header gives: a member's header right
                    # after it is the next one (the members after a wrong size were lost)
                    fh.seek(start + packed)
                    if fh.read(4) == b"PK\x03\x04":
                        end = start + packed
            if why == "spent":
                broken.append((name, "not looked at"))
                more = spent_said
                break
            if why == "cut":
                # the member the archive was cut in: one a reader can take in part is taken as far as it
                # arrived - an Excel workbook's sheets come before its shared strings, and an ODS has its
                # every sheet in its content.xml, which Excel writes first and LibreOffice last
                if in_part and data and name not in seen and out.add(name, data, partial=True):
                    seen.add(name)
                    total += len(data)
                    broken.append((name, "cut, read up to the cut"))
                else:
                    broken.append((name, "cut"))
                break
            if end is None:
                # its end is known only where its data ends, and its data was not read to the end
                broken.append((name, why))
                more = "a member whose size is not in its header was not read to its end, nor what follows it"
                how, at = "damaged" if why == "its data breaks" else how, pos
                break
            if not why and not folder and zlib.crc32(data) & 0xFFFFFFFF != crc:
                why = "its CRC does not match its data"
            if why:
                broken.append((name, why))
            elif not folder and name not in seen:
                seen.add(name)
                out.add(name, data)
                whole.append(name)
                total += len(data)
            data = b""
            pos = end
    out.close()
    return {"how": how, "members": found, "whole": whole, "broken": broken, "at": at, "size": size,
            "more": more, "all_members": toc, "partial": out.partial, "lost": out.lost}


def zip_mend(path, dest, until=None):
    """An archive zipfile opens, whose members do not all unpack (a CRC that does not match, data
    that breaks): the ones that do, within the caps, go into a new archive at `dest`. Returns what
    zip_salvage() does, "how" being "damaged"; nothing is written when every member unpacks. What
    is unpacked counts against ZIP_WHOLE_SPENT whether the member unpacks or not (200 members whose
    CRC fails at their end were each unpacked whole: 9 s for a 6.5 MB file), and `until` ends it."""
    import zipfile
    whole, broken, total, spent, seen, more = [], [], 0, 0, set(), ""
    out = _ZipOut(dest)
    with zipfile.ZipFile(path) as z:
        docreaders.fix_zip_names(z)
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > ZIP_WHOLE_MEMBERS:
            more = "%d members looked at; the rest were not" % ZIP_WHOLE_MEMBERS
        for k, i in enumerate(infos[:ZIP_WHOLE_MEMBERS]):
            limit = min(ZIP_WHOLE_PART, ZIP_WHOLE_TOTAL - total)
            room = min(limit, ZIP_WHOLE_SPENT - spent)
            if i.file_size > limit:
                broken.append((i.filename, "over the size limit"))
                continue
            if i.file_size > room:
                more = ("%s unpacked to look at the members before it; the rest were not looked at"
                        % human_bytes(ZIP_WHOLE_SPENT))
                break
            if until is not None and time.time() > until:
                more = "the time for it ran out after %d members; the rest were not looked at" % k
                break
            meter = [0]
            try:
                with z.open(i) as fh:
                    data = _read_counted(fh, room + 1, meter)
            except Exception as e:                            # noqa: BLE001  (bad CRC, data that breaks)
                spent += meter[0]
                broken.append((i.filename, "it does not unpack (%s)" % (str(e)[:60] or type(e).__name__)))
                continue
            spent += meter[0]
            if len(data) > room:
                broken.append((i.filename, "over the size limit"))
                continue
            if i.filename not in seen:
                seen.add(i.filename)
                out.add(i.filename, data)
                whole.append(i.filename)
                total += len(data)
    out.close()
    damaged = [b for b in broken if b[1] != "over the size limit"]
    if not damaged and os.path.exists(dest):
        os.unlink(dest)                                       # every member unpacks: nothing to mend
    return {"how": "damaged", "members": len(infos), "whole": whole if damaged else [],
            "broken": damaged, "at": 0, "size": os.path.getsize(path), "more": more, "all_members": not more,
            "partial": "", "lost": out.lost if damaged else None}


def zip_whole(path, workdir):
    """(the archive to read, what is wrong with it): `path` and None when zipfile opens it; else the
    archive of its whole members (zip_salvage), or None when none is whole or the file is no ZIP.
    What is wrong is a dict with "how" ("cut", "damaged" or "not a ZIP"), "what" for a file that
    is no ZIP, and "reason", the line an answer gives."""
    import zipfile
    try:
        with zipfile.ZipFile(path):
            return path, None
    except Exception as e:                                    # noqa: BLE001
        debuglog.exc("zip: does not open", e)
    what = not_zip(path)
    if what:
        return None, {"how": "not a ZIP", "what": what, "reason": "not a ZIP archive: the file is %s" % what}
    dest = os.path.join(workdir, "_whole-%s.zip" % hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:8])
    try:
        info = zip_salvage(path, dest, zip_until())
    except Exception as e:                                    # noqa: BLE001
        debuglog.exc("zip: salvage", e)
        info = {"how": "damaged", "members": 0, "whole": [], "broken": [], "at": 0, "size": 0, "more": "",
                "all_members": False}
    info["reason"] = zip_reason(info)
    info["path"] = dest if info["whole"] else ""
    trace("zip.salvage", how=info["how"], members=info["members"], whole=len(info["whole"]),
          broken=len(info["broken"]), at=info["at"], more=info["more"][:60])
    return info["path"] or None, info


def zip_until():
    """When the reading of an archive's members stops: the converter's seconds from now, or what
    the read's deadline leaves; None with --download."""
    return None if budget.unlimited() else now() + budget.cap(CONVERTER_TIMEOUT, floor=1.0)


def zip_reason(info):
    """The reason line of an archive that is not whole: what happened, and how many members are whole."""
    toc = info.get("all_members") and info["at"]
    if info["how"] == "cut":
        where = ("cut in its table of contents, after %s" if toc else "cut after %s") % human_bytes(info["size"])
    elif info["at"]:
        where = ("its table of contents is damaged, at byte %s of %s" if toc else "damaged at byte %s of %s") % (
            exact_bytes(info["at"]), exact_bytes(info["size"]))
    else:
        where = "damaged"
    n, found = len(info["whole"]), info["members"]
    if not found:
        if info.get("more"):                     # folder entries alone, up to the members looked at
            return "not a whole archive: %s; no file among the members looked at - %s" % (where, info["more"])
        return "not a whole archive: %s, before its first member" % where
    bad = info["broken"][:3]
    return "not a whole archive: %s; %d of the %d members found are whole%s%s" % (
        where, n, found, " (%s)" % "; ".join("%s: %s" % b for b in bad) if bad else "",
        "; " + info["more"] if info.get("more") else "")


def zip_advice(info, local, words=None, transit="", step=False):
    """The advice line for an archive that is not whole or no ZIP: what of it the answer holds, and
    what gets the rest - a whole copy of a file on this machine, another fetch of a server's. One
    cut or damaged in its table of contents alone, every member there and whole, has no rest.
    `words`: the document's own words the readers gave (0: the whole members gave no text).
    `transit`: the transfer's cut in words (cut_said) when the archive was cut on its way here, not
    on the server - `step` when it was still arriving as its time ran out."""
    part, lost = info.get("partial") or "", (info.get("lost") or {}).get("cells") or 0
    # what of the member it was cut in was read, and the cells whose text was in a part that is lost
    upto = ", %s as far as it arrived" % part if part else ""
    strings = ("; the text of %d of its cells was in a part that is lost (the workbook's shared strings): each "
               "reads %s" % (lost, LOST_TEXT)) if lost else ""
    if transit and info["how"] == "cut":
        n = len(info["whole"])
        read = "whole, but no text could be read from them" if n and words == 0 else "whole and read here"
        held = ("the archive's members all arrived %s, its table of contents did not" % read
                if info.get("all_members") and not info["broken"] and n else
                "%d of the archive's members %s %s%s, what came after %s did not arrive" % (
                    n, "is" if n == 1 else "are", read, upto, "it" if n == 1 and not part else "them") if n else
                "no member of the archive arrived whole%s" % upto)
        return "%s: %s%s; %s" % (transit, held, strings, "--download has no time limit, and the file arrives whole"
                                 if step else "--refresh tries again, and --download waits as long as the server takes")
    if info["how"] == "not a ZIP":
        what = info["what"]
        if what.startswith("a password-protected"):
            return ("the file is password-protected: this skill cannot open it; a copy saved without the "
                    "password can be read")
        if "97-2003" in what or what.startswith("an OLE2"):
            return ("the file is %s, not the ZIP-based file its name or type says: this skill does not read "
                    "that format; a copy saved as .docx, .xlsx or .pptx, or as PDF, can be read" % what)
        if what == "text":
            return "the file is text, not the archive its name or type says: its text is the answer"
        return "the file is %s, not the archive its name or type says: there is no document in it to read" % what
    n = len(info["whole"])
    bad = [b[0] for b in info["broken"]]
    are, them = ("is", "it") if n == 1 else ("are", "them")
    # what the readers made of the whole members: their text, or none (an office package whose
    # parts do not hold together, a sheet whose strings were in a part that is lost)
    read = "whole, but no text could be read from %s" % them if n and words == 0 else "whole and read here"
    if info.get("all_members") and not info["broken"] and n:
        # every member is there and whole: only the table of contents is cut or damaged
        every = "its one member is %s" % read if n == 1 else "all %d of its members are %s" % (n, read)
        if info["how"] == "cut":
            return "the archive is cut in its table of contents, after its members: %s" % every
        return "the archive's table of contents is damaged, not its members: %s" % every
    if info["how"] == "cut":
        held = ("%d of its members %s %s%s, what came after %s is missing" % (n, are, read, upto, "them" if part else them)
                if n else "no member of it is whole%s" % upto)
        what = "cut after %s" % human_bytes(info["size"])
    else:
        held = ("%d member%s not unpack (%s)%s" % (
            len(bad), " does" if len(bad) == 1 else "s do", ", ".join(bad[:3]) + (", ..." if len(bad) > 3 else ""),
            ", the other %d %s %s" % (n, are, read) if n else ", and no other is whole")
            if bad else "%d of its members %s %s" % (n, are, read))
        what = "damaged"
    rest = ("a whole copy of the file is needed for the rest" if local else
            "--refresh fetches it again, and the same bytes come back while the server's copy is %s" % info["how"])
    return "the archive is %s: %s%s; %s" % (what, held, strings, rest)


OFFICE_MAIN = {
    "docx": (rb"application/vnd\.ms-word\.(?:document\.macroEnabled|template\.macroEnabledTemplate)\.main\+xml|"
             rb"application/vnd\.openxmlformats-officedocument\.wordprocessingml\.template\.main\+xml",
             b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
    "pptx": (rb"application/vnd\.ms-powerpoint\.(?:slideshow|template)\.macroEnabled\.main\+xml|"
             rb"application/vnd\.openxmlformats-officedocument\.presentationml\.(?:slideshow|template)\.main\+xml",
             b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml")}


def office_plain(data, sub):
    """A package as python-docx and python-pptx take it: the main part of a macro-enabled file, a
    template or a slideshow (.docm .dotx .dotm .ppsx .ppsm .potx .potm) given the plain type, and
    Strict OOXML's namespaces the transitional ones. They refused these, and pandoc read them
    (2026-11-20, measured on variants of a plain package); unchanged bytes when nothing is to do.
    Only the XML parts are carried, unzipped: a picture, a font or a macro is an empty part here
    (the text needs none of them, and the pictures come from the file itself), so a package's
    media are never unpacked and zipped again in memory (up to 256 MB of them were)."""
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = [i for i in z.infolist() if i.filename.endswith((".xml", ".rels"))]
    if sum(i.file_size for i in xml) > MAX_PAGE_BYTES:
        return data                      # what the parts unpack to is read nowhere here
    names = set(z.namelist())
    if "[Content_Types].xml" not in names:
        return data
    types = zip_part(z, "[Content_Types].xml", MAX_PAGE_BYTES)
    rels = zip_part(z, "_rels/.rels", MAX_PAGE_BYTES) if "_rels/.rels" in names else b""
    pattern, plain = OFFICE_MAIN.get(sub, (None, None))
    other = bool(pattern and re.search(pattern, types))
    strict = b"purl.oclc.org/ooxml/" in rels
    if not (other or strict):
        return data
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as w:
        for info in z.infolist():
            if info.is_dir():
                continue
            part = zip_part(z, info.filename, MAX_PAGE_BYTES) if info.filename.endswith((".xml", ".rels")) else b""
            if info.filename == "[Content_Types].xml" and other:
                part = re.sub(pattern, plain, part)
            if strict and info.filename.endswith((".xml", ".rels")):
                part = re.sub(rb"http://purl\.oclc\.org/ooxml/(\w+)/", rb"http://schemas.openxmlformats.org/\1/2006/",
                              part)
            w.writestr(zipfile.ZipInfo(info.filename, info.date_time), part)
    return out.getvalue()


_OFFICE = _PerThread()    # the thread's last office_fast(): "damaged", "missing" (its library), "error"
OFFICE_LIBS = {"docx": "python-docx", "xlsx": "openpyxl", "pptx": "python-pptx"}
M_OMATH, M_OMATH_PARA = docreaders.M_NS + "oMath", docreaders.M_NS + "oMathPara"


# what holds a paragraph's runs besides the paragraph: python-docx's text reads its runs and its
# hyperlinks' alone, so a tracked insertion's text, a smart tag's, a field's, an inline content
# control's - and a formula in any of them - were lost (a deletion, w:del, is left out, as Word
# shows the document with its changes accepted)
_DOCX_WRAPS = ("hyperlink", "ins", "moveTo", "smartTag", "customXml", "sdt", "sdtContent", "fldSimple", "dir", "bdo")


def docx_para(p, qn):
    """A python-docx paragraph's text with its formulas where they stand: python-docx's text holds no
    m:oMath (a DOCX that is one formula read as nothing, KNOWN-ISSUES 165). Each formula is one line
    (docreaders.omml_text) in backticks, as an ODT's is; one that is a paragraph of its own is that
    paragraph. The runs and formulas inside a hyperlink, an insertion, a smart tag, a field or a
    content control are read where they stand. A paragraph with none of them and no formula is
    python-docx's text, untouched."""
    el = p._p
    w_r, wraps = qn("w:r"), {qn("w:" + t) for t in _DOCX_WRAPS}
    w_link = qn("w:hyperlink")
    if next(el.iter(M_OMATH), None) is None and not any(ch.tag in wraps and ch.tag != w_link for ch in el.iterchildren()):
        return p.text
    from docx.text.run import Run
    out, math_last = [], [False]

    def walk(node):
        for ch in node.iterchildren():
            if ch.tag in (M_OMATH, M_OMATH_PARA):
                maths = [ch] if ch.tag == M_OMATH else list(ch.iterchildren(M_OMATH))
                said = [docreaders._code(t) for t in (docreaders.omml_text(m).strip() for m in maths) if t]
                if not said:
                    continue
                if out and not out[-1][-1:].isspace():
                    out.append(" ")
                out.append(" ".join(said))
                math_last[0] = True
            elif ch.tag == w_r:
                t = Run(ch, p).text
                if t and math_last[0] and not t[:1].isspace() and t[:1] not in ".,;:!?)]":
                    out.append(" ")
                out.append(t)
                math_last[0] = math_last[0] and not t
            elif ch.tag in wraps:
                walk(ch)
    walk(el)
    return "".join(out)


def office_fast(path, sub):
    """The fast path: a library that reads the format directly, no markitdown startup.

    The libraries check the file extension, and our download is raw.zip - so feed them bytes.
    What stopped it is in _OFFICE: a member that does not unpack ("damaged"), or the library not
    installed here ("missing", its name on PyPI).
    """
    import io
    import zipfile
    _OFFICE.clear()
    try:
        data = open(path, "rb").read()
    except Exception:                                         # noqa: BLE001
        return ""
    try:
        data = office_plain(data, sub)
    except Exception as e:                                    # noqa: BLE001
        debuglog.exc("office: plain", e)
    try:
        if sub == "docx":
            import docx
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            d = docx.Document(io.BytesIO(data))
            media = {}                     # relationship id -> the picture's name in the package
            try:
                for rid, rel in d.part.rels.items():
                    if "image" in str(rel.reltype):
                        media[rid] = "word/" + str(rel.target_ref).replace("../", "").lstrip("/")
            except Exception:                                 # noqa: BLE001
                media = {}
            w_p, w_tbl, w_sdt, w_box = qn("w:p"), qn("w:tbl"), qn("w:sdt"), qn("w:txbxContent")
            fallback = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
            wps_box = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}txbx"
            parts = []

            def blocks(el):
                # the body in its own order: paragraphs, tables where they stand, the text of a
                # content control (forms, templates) and of a text box right after its anchor -
                # python-docx's paragraphs hold neither, and markitdown read them (2026-11-19)
                for child in el.iterchildren():
                    if child.tag == w_p:
                        text = docx_para(Paragraph(child, d), qn)
                        if text.strip():
                            parts.append(text)
                        # a picture stands in its paragraph; doc_pictures() makes it a marker
                        pics = ["![](%s)" % media[r] for r in re.findall(r'r:embed="([^"]+)"', child.xml)
                                if r in media]
                        if pics:
                            parts.append(" ".join(pics))
                        for box in child.iter(w_box):
                            # Word keeps a VML copy of a drawing's text box as the fallback: once
                            if not any(a.tag == fallback for a in box.iterancestors()) or \
                                    not any(True for _ in child.iter(wps_box)):
                                blocks(box)
                    elif child.tag == w_tbl:
                        for row in Table(child, d).rows:
                            parts.append(" | ".join("\n".join(docx_para(p, qn) for p in cell.paragraphs).strip()
                                                    for cell in row.cells))
                    elif child.tag == w_sdt:
                        content = child.find(qn("w:sdtContent"))
                        if content is not None:
                            blocks(content)
            blocks(d.element.body)
            notes = docx_notes(data)
            if notes:
                parts.append("Notes\n\n" + notes)
            return "\n\n".join(parts)
        if sub == "xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets:
                out.append("## " + ws.title)
                for row in ws.iter_rows(values_only=True):
                    cells = ["" if v is None else str(v) for v in row]
                    if any(cells):
                        out.append(" | ".join(cells))
            return "\n".join(out)
        if sub == "pptx":
            from pptx import Presentation
            out = []

            def shapes(slide, group):
                # a group's shapes and a table's cells hold text too (markitdown read them)
                for shape in group:
                    if getattr(shape, "shapes", None) is not None and shape.shape_type == 6:   # a group
                        shapes(slide, shape.shapes)
                        continue
                    if shape.has_text_frame and shape.text_frame.text.strip():
                        out.append(shape.text_frame.text)
                    if getattr(shape, "has_table", False) and shape.has_table:
                        for row in shape.table.rows:
                            out.append(" | ".join(cell.text.strip() for cell in row.cells))
                    rid = getattr(getattr(shape, "_element", None), "blip_rId", None)
                    if rid:                # a picture on the slide, where the slide has it
                        try:
                            out.append("![](%s)" % str(slide.part.related_part(rid).partname).lstrip("/"))
                        except Exception:                     # noqa: BLE001
                            pass
            for i, slide in enumerate(Presentation(io.BytesIO(data)).slides, 1):
                out.append("## Slide %d" % i)
                shapes(slide, slide.shapes)
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
                    out.append("notes: " + slide.notes_slide.notes_text_frame.text)
            return "\n".join(out)
    except ImportError as e:
        debuglog.exc("office: library", e)
        _OFFICE["missing"] = OFFICE_LIBS.get(sub, "")
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError) as e:
        # a member that does not unpack, or one where the table of contents says no member starts
        # (zipfile seeks before the file's start: "negative seek value"); a ValueError of the
        # library's own costs a look at every member (zip_mend), which then finds none to mend
        debuglog.exc("office: damaged", e)
        _OFFICE["damaged"] = str(e)[:120] or type(e).__name__
        _OFFICE["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    except Exception as e:                                    # noqa: BLE001
        debuglog.exc("office: reader", e)
        _OFFICE["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return ""


OCR_RENDER_DPI = 150                    # a scanned page's picture for OCR


def render_pdf_pages(path, workdir, pages=3, dpi=OCR_RENDER_DPI):
    """PNG of the first pages, for a model that can look. Returns the file paths. PyMuPDF opens the document by a
    path it takes as UTF-8, and the pictures are written by Python, which writes any path (KNOWN-ISSUES 175)."""
    try:
        import pymupdf
        with lib_path(path) as at:
            doc = pymupdf.open(at)
            out = []
            for i, page in enumerate(doc, 1):
                if i > pages:
                    break
                data = page.get_pixmap(dpi=dpi).tobytes("png")
                fn = os.path.join(workdir, "page-%02d.png" % i)
                with open(fn, "wb") as fh:
                    fh.write(data)
                out.append(fn)
            doc.close()
        return out
    except Exception as _dbg_e:                                         # noqa: BLE001
        debuglog.exc("pdf pages", _dbg_e)
        return []


_TESSDATA = {}                       # where the packs are: a new pack changes that folder (caps)


def tesseract_langs(exe=None):
    """The language packs this tesseract really has. An installer ships eng+osd only."""
    exe = exe or which("tesseract")
    if not exe:
        return []
    rc, so, _se = run_tool([exe, "--list-langs"], timeout=20)
    if rc != 0:
        return []
    out = []
    for line in so.decode("utf-8", "replace").splitlines():
        low = line.strip().lower()
        if not low or low.startswith("list of available"):
            m = re.search(r'"([^"]+)"', line)          # List of available languages in "/usr/share/.../"
            if m:
                _TESSDATA["dir"] = m.group(1)
            continue
        out.append(line.strip())
    return out


_OCR_STATE = {"why": ""}             # tesserocr is installed but does not start: why (the last try)


def _tess_dir(td):
    """The tessdata folder as tesserocr can open it: on Windows a path outside ASCII by its short name
    (ownenv.ascii_path); "" when it has none."""
    return ownenv.ascii_path(td) if td else td


def _tess_ready():
    """tesserocr that really starts: (module, tessdata folder, languages, why). A listing of the folder
    proves nothing - a path tesseract cannot open, a pack cut short, a wheel with no data all list fine
    and fail at the first picture - so tesseract is started once on one pack. module is None, with why
    "", when tesserocr is not installed; why ("does not start: ...") names what stops an installed one."""
    try:
        import tesserocr
    except Exception as e:                                    # noqa: BLE001  (not installed)
        debuglog.exc("ocr: tesserocr", e)
        return None, "", [], ""
    td = os.environ.get("READ_PAGE_TESSDATA") or ""
    try:
        with ownenv.tess_dir(td) as api_dir:          # where a narrow path cannot open it, from its parent
            if td and not api_dir:
                raise OSError(ownenv.NONASCII_WHY % td)
            where, have = tesserocr.get_languages(api_dir) if td else tesserocr.get_languages()
            have = [x for x in have if x]
            if not have:
                raise OSError("no language data in %s" % (td or "its default folder"))
            lang = "eng" if "eng" in have else next((x for x in have if x != "osd"), have[0])
            with tesserocr.PyTessBaseAPI(path=where, lang=lang):
                pass
        return tesserocr, td or where, have, ""        # the folder itself: every start goes through tess_dir
    except Exception as e:                                    # noqa: BLE001
        debuglog.exc("ocr: tesserocr start", e)
        return None, "", [], "does not start: %s" % (short_reason(e) or type(e).__name__)


def short_reason(e, limit=200):
    """An error's text on one line, at most `limit` characters: where it is longer, its start and its end - the end
    of such a text says what is wrong ("... a folder whose name has characters outside ASCII that OCR cannot
    open", what ownenv.ocr_fix finds the fix by), and a long path in its middle cut that off."""
    s = " ".join(str(e).split())
    if len(s) <= limit:
        return s
    head = (limit - 5) // 2
    return s[:head] + " ... " + s[-(limit - 5 - head):]


def _tesserocr():
    """tesserocr with language data - the OCR --setup installs, tesseract 5.5.4 in-process:
    (module, tessdata folder, languages), or None. _OCR_STATE says why when it is installed and fails."""
    if "tesseract" in SKIP or "ocr" in SKIP:
        return None
    mod, where, have, why = _tess_ready()
    _OCR_STATE["why"] = why
    return (mod, where, have) if mod else None


OCR_DARK_ON_LIGHT = 120      # the second pass of a picture's OCR: darker than this is ink (ocr_picture)


def _ocr_own_packs():
    """The language packs of the user's own languages, and those `--setup --ocr-langs` was named (setup.json's
    ocr_named; an older one's ocr_langs beyond English), unless the user named the languages for the read."""
    if "READ_PAGE_OCR_LANGS" in os.environ:
        return []
    own = intl.locale_packs()
    env = ownenv.status()
    if env.get("used"):
        info = ownenv.load(env.get("home"))
        kept = info.get("ocr_named") if isinstance(info.get("ocr_named"), list) else [
            x for x in (info.get("ocr_langs") or []) if x != "eng"]
        own += [x for x in kept if isinstance(x, str) and x not in own and x not in ("eng", "osd")]
    return own


# A scanned page's script, as tesseract's own detection (OSD: osd.traineddata, which --setup fetches) names it, and the
# packs that read it: the user's own pack of the script first, else the first one installed. A script with no pack
# here, or none named, leaves the page to English and the user's own packs. Latin is English's, and the language of
# its text (intl.latin_pack) has the page read again with that language's pack.
OCR_SCRIPT_PACKS = {
    "Cyrillic": ("rus", "ukr", "bel", "bul", "srp", "mkd", "kaz", "kir", "tgk", "mon"),
    "Han": ("chi_sim", "chi_tra"), "Japanese": ("jpn",), "Hiragana": ("jpn",), "Katakana": ("jpn",),
    "Korean": ("kor",), "Hangul": ("kor",), "Arabic": ("ara", "fas", "urd", "pus", "uig", "snd"),
    "Devanagari": ("hin", "mar", "nep", "san"), "Greek": ("ell",), "Hebrew": ("heb", "yid"), "Thai": ("tha",),
    "Bengali": ("ben", "asm"), "Tamil": ("tam",), "Telugu": ("tel",), "Kannada": ("kan",), "Malayalam": ("mal",),
    "Gujarati": ("guj",), "Gurmukhi": ("pan",), "Oriya": ("ori",), "Sinhala": ("sin",), "Armenian": ("hye",),
    "Georgian": ("kat",), "Ethiopic": ("amh", "tir"), "Khmer": ("khm",), "Lao": ("lao",), "Myanmar": ("mya",),
    "Tibetan": ("bod",), "Syriac": ("syr",), "Thaana": ("div",),
    "Fraktur": ("frk",),                   # OSD's own name for black letter: German print to the 1940s
}
# The confidence OSD gives its script from which the script chooses the packs, and a pack it needs and this machine
# lacks is named; below it the page is read as one whose script nobody told. Measured on 160 synthetic scans in 24
# languages and up to 9 fonts (2026-11-22): 7 of 90 Latin pages were taken for Cyrillic, at 0.2-1.4, and Cyrillic pages
# gave 3.7-60; Han's is low by OSD's own rule - its characters count for Japanese and Korean too - 0.5-1.4 on Chinese
# pages, Japanese 2.0-2.7, Korean 0.8-1.6; Greek 0.5-10.3 on 13 of 14 Greek pages (the other taken for Cyrillic, 2.9),
# and no Latin or Cyrillic page of the 112 was taken for Greek; Arabic, Hebrew, Devanagari and Thai 9-210; no page was
# taken for any script but Latin, Cyrillic or its own. Fraktur (2026-11-23): 2.7-49 on 11 of 17 German pages printed
# in it (the other six Latin or Cyrillic), and once 1.8 on an Italian print of 1533 in italics - no other page of 320.
OCR_SCRIPT_TRUST = {"Cyrillic": 3.0, "Greek": 0.4, "Han": 0.3, "Japanese": 0.3, "Hiragana": 0.3, "Katakana": 0.3,
                    "Korean": 0.3, "Hangul": 0.3, "Fraktur": 2.5}
OCR_SCRIPT_TRUST_ELSE = 1.0
# Packs that read a page alone, without English beside it: they read the English words in a Chinese or Japanese text
# themselves (12-16 of 13-17 terms on a page, as many as with English beside them), and English beside them made the
# rest worse and slower (CER 1.6 against 2.2 %, 2.0 against 3.3, 1.3 against 1.5; about 0.7 s more a page). kor is
# not one: alone it read none of 14 English terms in a Korean text (with English beside it 10-11). frk reads its
# Antiqua words itself (with English beside it 0.1-0.8 points worse on 7 of 11 Fraktur pages).
OCR_ALONE = ("chi_sim", "chi_tra", "jpn", "frk")
# OSD names Han, not which Chinese: on 16 Chinese pages (8 with English words in the text) chi_sim's mean word
# confidence was 88-91 on simplified ones and 79-87 on traditional ones (where it misread a fifth to a third of the
# characters), chi_tra's 86-90 on simplified ones (a fifth to a quarter misread) and 88-92 on its own; on 8 Japanese
# pages both were 44-56, jpn 90-92. chi_sim reads a Han page first; under OCR_HAN_SURE chi_tra reads it too, and
# under OCR_HAN_JAPANESE (no Chinese page's best reading was) jpn; a reading is kept when it is OCR_HAN_MARGIN more
# confident than the best before it.
OCR_HAN_SURE = 90
OCR_HAN_JAPANESE = 70
OCR_HAN_MARGIN = 3
# A page printed in vertical columns - Chinese, Japanese and Korean books, old and new - read as nothing with the
# horizontal packs (95-121 % CER on 27 real pages and 10 synthetic ones, 2026-11-23). Tesseract's own layout finds such
# columns written top to bottom whatever pack reads them (0.83-1.00 of the characters on 35 of the 37 pages, the other
# two read as nothing at all; none on 241 horizontal pages): from OCR_VERTICAL_SHARE such a page, whose script OSD names
# Han, Japanese or Korean or whose reading is unsure of itself (under OCR_UNSURE: OSD took 4 of the 27 for Latin), is
# read again with the vertical packs in an order by its script (OCR_VERTICAL_PACKS), each while the best is unsure and
# no less sure than the first reading - a page on its side that OSD could not turn is laid out vertically too, and the
# vertical packs read it less surely than its own -, and the most confident kept. Tesseract's layout finds the columns
# (the default page mode): one block of vertical text assumed for the whole page (PSM 5) read the 27 real pages at 79 %
# CER against 67, running a page's tiers together.
OCR_VERTICAL_SHARE = 0.5
OCR_UNSURE = 60
# each vertical pack with the confidence of the best reading so far under which it reads the page too: a Han page in
# the Han packs' order and by their measures (chi_sim_vert's confidence tells a traditional page, chi_tra_vert's does
# not tell a simplified one: 84 on a simplified page it read at 27 % CER), a Japanese or Korean page its own first, a
# page OSD called anything else (four of them were Japanese) jpn_vert first
OCR_VERTICAL_PACKS = {"Han": (("chi_sim_vert", 0), ("chi_tra_vert", OCR_HAN_SURE), ("jpn_vert", OCR_HAN_JAPANESE),
                              ("kor_vert", OCR_UNSURE)),
                      "Japanese": (("jpn_vert", 0), ("chi_tra_vert", OCR_UNSURE), ("kor_vert", OCR_UNSURE)),
                      "Korean": (("kor_vert", 0), ("jpn_vert", OCR_UNSURE), ("chi_tra_vert", OCR_UNSURE))}
OCR_VERTICAL_ELSE = (("jpn_vert", 0), ("chi_tra_vert", OCR_UNSURE), ("kor_vert", OCR_UNSURE),
                     ("chi_sim_vert", OCR_UNSURE))
# A scan whose script OSD is unsure of, or one it calls Latin whose reading is unsure of itself, is read again with the
# likeliest other scripts' packs - OSD's own answer's, then the scripts OSD took for it on the real and synthetic scans
# measured (2026-11-23: Hebrew for Arabic, Greek for Latin and Cyrillic, Thai for Cyrillic, Fraktur and Han for
# Latin, Latin for Cyrillic) -, at most OCR_UNSURE_TRIES of them, while the best reading is under OCR_UNSURE, and the
# most confident is kept (by OCR_HAN_MARGIN). Mean word confidence (2026-11-23): 180 horizontal pages read with their
# own pack 42-95 - under 64 only where the reading itself is poor, 37-88 % CER -, English on 104 pages of another
# script 12-54.
OCR_UNSURE_TRIES = 3
OCR_SCRIPT_TAKEN = {"Latin": ("Fraktur", "Greek", "Han", "Cyrillic"), "Cyrillic": ("Latin", "Greek", "Thai"),
                    "Greek": ("Latin", "Cyrillic"), "Arabic": ("Hebrew",), "Hebrew": ("Arabic",),
                    "Han": ("Japanese", "Korean"), "Japanese": ("Han", "Korean"), "Korean": ("Han", "Japanese")}
_CJK_SCRIPTS = {"Han": "Han", "Japanese": "Japanese", "Hiragana": "Japanese", "Katakana": "Japanese",
                "Korean": "Korean", "Hangul": "Korean"}


def _pack_script(pack):
    """The script a pack reads ("Latin" for any pack of no script in OCR_SCRIPT_PACKS)."""
    base = pack[:-5] if pack.endswith("_vert") else pack
    return next((s for s, packs in OCR_SCRIPT_PACKS.items() if base in packs), "Latin")


def _ocr_plan(have, page_text="", script=None):
    """(the packs to read with, the packs the read needs and this machine lacks).

    The user's word first: what READ_PAGE_OCR_LANGS names, and the pack of the page text's script beside it. Else the
    page's own: the pack of its text's script (Chinese, Japanese, Korean, Russian text: intl.script_pack), English and
    the user's own packs beside it; or the pack of the script OSD saw on a scan (`script`: its name and confidence;
    OCR_SCRIPT_PACKS, OCR_SCRIPT_TRUST), English beside it unless the pack reads alone (OCR_ALONE); a scan OSD saw as
    Latin, English and the user's Latin-script packs. Where neither tells, English and the user's own packs
    (intl.locale_packs, and those --setup was named). Only packs this machine has are used. A pack the user named,
    the text called for or the script needs, and that is not here, is reported; the user's own are only wishes."""
    asked = [x.strip() for x in OCR_LANGS.split("+") if x.strip()]
    hint = intl.script_pack(page_text)
    if "READ_PAGE_OCR_LANGS" in os.environ:
        want, need = asked + [x for x in [hint] if x and x not in asked], asked + [hint]
    else:
        own = _ocr_own_packs()
        name, conf = script or ("", 0.0)
        trusted = not hint and conf >= OCR_SCRIPT_TRUST.get(name, OCR_SCRIPT_TRUST_ELSE)
        packs = OCR_SCRIPT_PACKS.get(name, ()) if trusted else ()
        # the user's own pack of the script first (a Ukrainian's ukr, a Taiwanese's chi_tra), else its first one here
        pick = next((x for x in own if x in packs and (not have or x in have)), "") or next(
            (x for x in packs if not have or x in have), "")
        need = [hint or (packs[0] if packs and not pick else "")]
        # a page whose text is in a Latin-script language: its pack, when it is here (a wish, never reported)
        latin = "" if hint else intl.latin_pack(page_text)
        if latin and latin != "eng" and (not have or latin in have):
            hint = latin
        if hint:
            want = [hint, "eng"] + own
        elif pick:
            want = [pick] + ([] if pick in OCR_ALONE else ["eng"])
        elif trusted and name == "Latin":
            want = ["eng"] + [x for x in own if _pack_script(x) == "Latin"]
        else:
            want = ["eng"] + own + need
    want = [x for i, x in enumerate(want) if x and x not in want[:i]]
    use = [x for x in want if not have or x in have]
    lost = [x for x in want if have and x not in have and x in need]
    return (use or (["eng"] if "eng" in have else [x for x in have if x != "osd"][:1] or ["eng"])), lost


def _ocr_langs(have, page_text):
    """The packs to read with: _ocr_plan's first half."""
    return _ocr_plan(have, page_text)[0]


def _ocr_tsv(tsv):
    """tesseract's TSV: the text line by line, and each word's confidence."""
    lines, confs, key = [], [], None
    for row in (tsv or "").splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        try:
            confs.append(float(f[10]))
        except ValueError:
            continue
        if (f[2], f[3], f[4]) != key:
            key = (f[2], f[3], f[4])
            lines.append([])
        lines[-1].append(f[11].strip())
    return "\n".join(" ".join(ws) for ws in lines), confs


def svg_text(path):
    """An SVG drawing's labels: its <text> elements in order - read, not recognised."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            s = fh.read(4_000_000)
    except OSError:
        return ""
    out = []
    for m in re.finditer(r"(?is)<text\b[^>]*>(.*?)</text>", s):
        t = re.sub(r"\s+", " ", unescape(re.sub(r"(?s)<[^>]+>", " ", m.group(1)))).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def ocr_picture(path, page_text=""):
    """The text drawn in a picture, for a model that cannot see it (--ocr N: models that cannot
    see spent 18 to 84 calls reading one figure with tesseract by hand).

    Two passes - the picture in grey, and dark against light at OCR_DARK_ON_LIGHT - and the one with
    more words read at confidence 80+ is kept: on five figures of a blog post the second pass read
    four better (a diagram on coloured boxes: 7 -> 14 of its 16 labels) and the grey one the fifth;
    a picture twice the size read no better at three times the time. A dark picture is inverted
    first; an SVG drawing gives its <text> elements. tesserocr in-process when it is there (the same
    engine, no process to start), else tesseract's command. (text, info): info names the engine,
    languages, pass and seconds - or why there is no text."""
    t0 = now()
    if path.lower().endswith(".svg"):
        txt = svg_text(path)
        return txt, ({"engine": "the drawing's own text", "seconds": round(now() - t0, 2)} if txt
                     else {"why": "an SVG drawing with no text in it"})
    if "tesseract" in SKIP or "ocr" in SKIP:
        return "", {"why": "OCR is off here (READ_PAGE_SKIP)"}
    passes = []
    try:
        from PIL import Image, ImageOps, ImageStat
        im = Image.open(path)
        im.load()
        g = im.convert("L")
        if ImageStat.Stat(g).mean[0] < 100:
            g = ImageOps.invert(g)                      # light text on a dark picture
        passes = [("grey", g), ("dark on light", g.point(lambda v: 255 if v > OCR_DARK_ON_LIGHT else 0))]
    except ImportError:
        passes = [("as it is", None)]                   # no Pillow: one pass of the file itself
    except Exception as e:                               # noqa: BLE001
        return "", {"why": "not a picture OCR can open: %s" % str(e)[:80]}
    tessdata = os.environ.get("READ_PAGE_TESSDATA") or ""
    exe = which("tesseract")
    if not tessdata and exe and os.path.isdir(os.path.join(os.path.dirname(exe), "tessdata")):
        tessdata = os.path.join(os.path.dirname(exe), "tessdata")
    best = None                                          # (good words, text, pass)
    engine, langs, broken, lost = "", [], "", []
    try:
        import tesserocr
        if passes and passes[0][1] is not None:
            # the path as tesserocr opens it (Windows, outside ASCII: the short name); an installed
            # tesserocr that cannot start is said so below, not taken for a missing one
            with ownenv.tess_dir(tessdata) as api_dir:
                if tessdata and not api_dir:
                    raise OSError(ownenv.NONASCII_WHY % tessdata)
                where, have = tesserocr.get_languages(api_dir) if tessdata else tesserocr.get_languages()
                langs, lost = _ocr_plan(have, page_text)
                api = tesserocr.PyTessBaseAPI(path=where, lang="+".join(langs))
            try:
                for name, img in passes:
                    api.SetImage(img)
                    txt = api.GetUTF8Text()
                    good = sum(1 for c in api.AllWordConfidences() if c >= 80)
                    if best is None or good > best[0]:
                        best = (good, txt, name)
            finally:
                api.End()
            engine = "tesserocr"
    except ImportError as e:                             # not installed
        debuglog.exc("ocr: tesserocr", e)
        best = None
    except Exception as e:                               # noqa: BLE001  (no packs, a path or a pack it cannot open)
        debuglog.exc("ocr: tesserocr", e)
        best, broken = None, "tesserocr is installed but does not start: %s" % short_reason(e, 160)
    if best is None:
        if not exe:
            return "", {"why": broken or "no OCR engine here: tesseract, or tesserocr from pip"}
        langs, lost = _ocr_plan(tesseract_langs(exe), page_text)
        extra = (["--tessdata-dir", _tess_dir(os.environ["READ_PAGE_TESSDATA"]) or os.environ["READ_PAGE_TESSDATA"]]
                 if os.environ.get("READ_PAGE_TESSDATA") else [])
        for name, img in passes:
            src = path
            if img is not None:
                fd, src = tempfile.mkstemp(suffix=".png", dir=ascii_stage_root() or None)
                os.close(fd)
                img.save(src)
            shown, _outs, narrow_done = narrow_paths([src])
            try:
                rc, so, _se = run_tool([exe, shown[0], "stdout", "-l", "+".join(langs), "--psm", "3"] + extra + ["tsv"],
                                       timeout=budget.cap(OCR_TIMEOUT, floor=2.0))
            finally:
                narrow_done()
                if src != path:
                    try:
                        os.unlink(src)
                    except OSError:
                        pass
            if rc != 0:
                continue
            txt, confs = _ocr_tsv(so.decode("utf-8", "replace"))
            good = sum(1 for c in confs if c >= 80)
            if best is None or good > best[0]:
                best = (good, txt, name)
        engine = "tesseract"
    if best is None:
        return "", {"why": "tesseract read nothing from it"}
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(ln.rstrip() for ln in (best[1] or "").splitlines())).strip()
    info = {"engine": engine, "langs": "+".join(langs), "pass": best[2], "seconds": round(now() - t0, 2)}
    if lost:
        info["note"] = "no %s language data here: %s" % ("/".join(lost), ocr_pack_fix(lost))
    return text, info


def ocr_pack_fix(packs):
    """The line that gives these OCR packs: --setup fetches English and the user's own languages, and what
    --ocr-langs names - so the command names them (`readpage.py --setup --ocr-langs eng+jpn`: a flag, which every
    shell runs as it is; a POSIX shell's `READ_PAGE_OCR_LANGS=... cmd` is no command in PowerShell or cmd)."""
    packs = [p for p in packs if p][:3]
    files = ", ".join("%s.traineddata" % p for p in packs)
    if ownenv.problem("ocr-langs"):
        return "%s: %s" % (files, ownenv.problem("ocr-langs"))
    if ownenv.gives("ocr-langs"):
        return "%s: %s --ocr-langs %s" % (files, SETUP, "+".join(["eng"] + [p for p in packs if p != "eng"]))
    return "%s into tessdata (github.com/tesseract-ocr/tessdata_fast), or READ_PAGE_OCR_LANGS" % files


def ocr_answer(workdir, manifest, n):
    """--ocr N: picture N of the page (downloaded now when it is still an address) and its text."""
    entries = [e for e in (manifest.get("images") or []) if isinstance(e, dict)]
    e = next((x for x in entries if x.get("n") == n), None)
    if e is None:
        return manifest, {"n": n, "why": "this page has no picture #%d (%d in all)" % (n, len(entries)), "text": ""}
    if not e.get("file") and str(e.get("url") or "").startswith(("http://", "https://")):
        url = (manifest.get("url") or {}).get("requested") or (manifest.get("url") or {}).get("final") or ""
        try:
            manifest = _window_round(workdir, manifest, url, "content.md", 1, {n}, manifest.get("files") or {},
                                     IMAGE_PHASE_SECONDS, IMAGE_PHASE_SECONDS)
            if url:
                store_cache(workdir, manifest, url)
        except Exception as ex:                          # noqa: BLE001
            debuglog.exc("ocr: download", ex)
        e = next((x for x in manifest.get("images") or [] if isinstance(x, dict) and x.get("n") == n), e)
    if not e.get("file"):
        return manifest, {"n": n, "why": "picture #%d is not on disk: %s" % (n, e.get("why") or "not downloaded"),
                          "text": ""}
    path = e["file"] if os.path.isabs(e["file"]) else os.path.join(workdir, e["file"])
    page_text = ""
    try:
        with open(os.path.join(workdir, "content.md"), encoding="utf-8", errors="replace") as fh:
            page_text = fh.read(20000)
    except OSError:
        pass
    text, info = ocr_picture(path, page_text)
    info.update(n=n, file=e["file"], text=text)
    return manifest, info


def _turned(img, turn):
    """A picture turned `turn` degrees clockwise (90, 180, 270)."""
    from PIL import Image
    ops = getattr(Image, "Transpose", Image)                 # Pillow 9.1 and later name them there
    return img.transpose(getattr(ops, {90: "ROTATE_270", 180: "ROTATE_180", 270: "ROTATE_90"}[turn]))


def _tess_page(api, png, turn=0):
    """A rendered page to tesserocr: by its path where the library can open it (the file's own resolution: the page's
    150 dpi), else as a picture with its resolution given - tesserocr hands a picture over re-saved without it, and
    tesseract took 70 dpi for a page rendered at 150. `turn`: degrees clockwise that set the page upright first."""
    if str(png).isascii() and not turn:
        api.SetImageFile(png)
        return
    try:
        from PIL import Image
    except ImportError:                                  # no Pillow: the page as it is
        shown, _outs, narrow_done = narrow_paths([png])
        try:
            api.SetImageFile(shown[0])
        finally:
            narrow_done()
        return
    with Image.open(png) as shot:
        shot.load()
        dpi = (shot.info.get("dpi") or (OCR_RENDER_DPI,))[0]
        api.SetImage(_turned(shot, turn) if turn else shot)  # no path for the library to open in the ANSI code page
        api.SetSourceResolution(int(round(float(dpi))) or OCR_RENDER_DPI)


def _vertical_share(api, mod):
    """The share of a reading's characters in the blocks tesseract's layout found written top to bottom (columns of
    Chinese, Japanese or Korean - or a page on its side); 0.0 when it cannot say."""
    try:
        level = getattr(getattr(mod, "RIL", None), "BLOCK", 0)
        it = api.GetIterator()
        vert = total = 0
        while it is not None:
            n = len("".join((it.GetUTF8Text(level) or "").split()))
            total += n
            if it.Orientation()[1] == 2:                    # WritingDirection.TOP_TO_BOTTOM
                vert += n
            if not it.Next(level):
                break
        return vert / float(total) if total else 0.0
    except Exception as e:                                   # noqa: BLE001  (an older tesserocr, a fake one)
        debuglog.exc("ocr: layout", e)
        return 0.0


def _osd_text(text):
    """(script, confidence) from tesseract's OSD report (`--psm 0`: "Script: Latin", "Script confidence: 2.5")."""
    m = re.search(r"(?m)^Script: *(\S+)", text or "")
    c = re.search(r"(?m)^Script confidence: *([0-9.]+)", text or "")
    try:
        return (m.group(1), float(c.group(1))) if m and c else ("", 0.0)
    except ValueError:
        return "", 0.0


# A page scanned on its side or upside down read as garbage. OSD answers the page's orientation too - the quarter turn
# it sees, and its confidence - and the page is turned upright by it from OCR_TURN_TRUST. Measured (2026-11-23) on 42
# copies of 14 real and synthetic pages in eight scripts, each turned 90, 180 and 270 degrees: OSD was right on 37, at
# 3.6-22 (34 from 5.0), and wrong under 3.7; of 278 upright pages it named a turn for 11, under 3.3 but for two pages of
# a magazine set in Fraktur (6.9, 9.4), which the reading's own confidence sets right (ocr_pages).
OCR_TURN_TRUST = 5.0


def _turn_of(deg, conf):
    """Degrees clockwise that set a page upright, from OSD's orientation (the page's own turn clockwise, in degrees) and
    its confidence: 0 for an upright page, and for one OSD is not that sure of."""
    try:
        deg, conf = int(float(deg or 0)) % 360, float(conf or 0.0)
    except (TypeError, ValueError):
        return 0
    return (360 - deg) % 360 if deg in (90, 180, 270) and conf >= OCR_TURN_TRUST else 0


def _osd_turn(text):
    """The turn that sets a page upright from tesseract's OSD report (`--psm 0`: "Orientation in degrees: 90",
    "Orientation confidence: 12.3"); 0 when it is upright, unsure or untold."""
    m = re.search(r"(?m)^Orientation in degrees: *([0-9]+)", text or "")
    c = re.search(r"(?m)^Orientation confidence: *([0-9.]+)", text or "")
    return _turn_of(m.group(1), c.group(1)) if m and c else 0


def ocr_pages(paths):
    """Text from rendered pages, plus what happened with the languages.

    A scanned PDF has no text layer, so the only way to read it locally is to look at the page. Each page is read with
    the packs of its own script (_ocr_plan): tesseract's script detection (OSD, osd.traineddata) names it, and a Latin
    page whose words are another language's (intl.latin_pack) is read again with that language's pack when it is
    here - never with every pack at once, which was slower and worse. READ_PAGE_OCR_LANGS, when set, decides for every
    page; READ_PAGE_TESSDATA points at a tessdata folder outside the install. A pack the page needs and the machine
    lacks is reported instead of failing silently: tesseract would answer with garbage or nothing at all. tesserocr
    (--setup's) reads in-process; tesseract's command is the fallback.
    """
    lib = _tesserocr()
    exe = None if (lib or "tesseract" in SKIP or "ocr" in SKIP) else which("tesseract")
    info = {"have": lib[2] if lib else tesseract_langs(exe) if exe else [], "used": [], "missing": [],
            "engine": "tesserocr" if lib else "tesseract"}
    if not (lib or exe) or not paths:
        if not lib and not exe and _OCR_STATE["why"] and "tesseract" not in SKIP and "ocr" not in SKIP:
            info["error"] = "tesserocr is installed but " + _OCR_STATE["why"]    # not an OCR that found nothing
        return "", info
    have = info["have"]
    _use, info["missing"] = _ocr_plan(have, "")
    info["maybe"] = [x for x in _ocr_own_packs() if have and x not in have]        # a wish of the user's languages
    # the script of each page, unless the user named the packs; osd.traineddata is --setup's (an installer's too)
    auto = "READ_PAGE_OCR_LANGS" not in os.environ
    detect = auto and "osd" in have
    extra = (["--tessdata-dir", _tess_dir(os.environ["READ_PAGE_TESSDATA"]) or os.environ["READ_PAGE_TESSDATA"]]
             if os.environ.get("READ_PAGE_TESSDATA") else [])
    info["timeouts"] = []
    pages = list(enumerate(paths[:OCR_MAX_PAGES], 1))
    secs = budget.cap(OCR_TIMEOUT, floor=1.0)
    t_ocr = now()
    done, plans, turns = {}, {}, {}

    @contextlib.contextmanager
    def for_command(png, turn):
        """The page as the tesseract command opens it: a copy turned upright beside it while it is read (removed
        after; the page as it is without Pillow), by a path it can take in the ANSI code page."""
        src = png
        if turn:
            try:
                from PIL import Image
                src = os.path.splitext(png)[0] + "-upright.png"
                with Image.open(png) as shot:
                    shot.load()
                    _turned(shot, turn).save(src, dpi=shot.info.get("dpi") or (OCR_RENDER_DPI, OCR_RENDER_DPI))
            except Exception as e:                           # noqa: BLE001  (no Pillow, no room: the page as it is)
                debuglog.exc("ocr: turn", e)
                src = png
        shown, _outs, narrow_done = narrow_paths([src])
        try:
            yield shown[0]
        finally:
            narrow_done()
            if src != png:
                try:
                    os.unlink(src)
                except OSError:
                    pass

    def osd(png, turn=0):
        """(script, confidence, turn) of a page - turn: the degrees clockwise that set it upright (_turn_of) -,
        ("", 0.0, 0) when OSD cannot tell (too few letters). `turn`: the page is turned so first."""
        try:
            if not lib:
                with for_command(png, turn) as shown:
                    rc, so, _se = run_tool([exe, shown, "stdout", "--psm", "0"] + extra, timeout=min(secs, 10.0))
                said = so.decode("utf-8", "replace") if rc == 0 else ""
                return _osd_text(said) + (_osd_turn(said),)
            with ownenv.tess_dir(lib[1]) as tdir:
                api = lib[0].PyTessBaseAPI(path=tdir, lang="osd", psm=0)       # PSM.OSD_ONLY
            with api:
                _tess_page(api, png, turn)
                got = api.DetectOrientationScript() or {}
            return (str(got.get("script_name") or ""), float(got.get("script_conf") or 0.0),
                    _turn_of(got.get("orient_deg"), got.get("orient_conf")))
        except Exception as e:                               # noqa: BLE001  (no script told: the page's plan without it)
            debuglog.exc("ocr: osd", e)
            return "", 0.0, 0

    def read(png, use, limit, turn=0, scored=False):
        """(rc, text, error, the mean confidence of its words - -1 from the command -, the share of its characters
        the layout found written top to bottom - 0 from the command). `turn`: degrees clockwise that set the page
        upright before it is read. The command reads a page turned, or one `scored`, as TSV: its words' confidences
        check OSD's turn."""
        if not lib:
            with for_command(png, turn) as shown:
                cmd = [exe, shown, "stdout", "-l", "+".join(use)] + extra
                if not (turn or scored):
                    return tuple(run_tool(cmd, timeout=limit)) + (-1, 0.0)
                rc, so, se = run_tool(cmd + ["tsv"], timeout=limit)
            txt, confs = _ocr_tsv(so.decode("utf-8", "replace"))
            return rc, txt.encode("utf-8"), se, (int(sum(confs) / len(confs)) if confs else -1), 0.0
        # tesserocr (--setup's OCR) in-process: it lets the other threads run while it reads, and
        # its own clock stops a page at the step's seconds
        try:
            with ownenv.tess_dir(lib[1]) as tdir:            # started from the folder's parent where a narrow path fails
                api = lib[0].PyTessBaseAPI(path=tdir, lang="+".join(use))
            with api:
                _tess_page(api, png, turn)
                try:
                    api.Recognize(int(limit * 1000))
                except TypeError:
                    pass
                text = (api.GetUTF8Text() or "").encode("utf-8")
                try:
                    conf = int(api.MeanTextConf())
                except (AttributeError, TypeError, ValueError):
                    conf = -1
                return 0, text, b"", conf, _vertical_share(api, lib[0])
        except Exception as e:                               # noqa: BLE001
            debuglog.exc("ocr: tesserocr page", e)
            return 1, b"", str(e).encode("utf-8", "replace"), -1, 0.0

    def one(n, png):
        t_page = now()
        script, conf, turn = osd(png) if detect else ("", 0.0, 0)
        if turn:                                         # a page on its side or upside down is read upright, and its
            upright = osd(png, turn)                     # script told upright (a Greek page turned: 0.3, upright 1.3)
            if upright[0]:
                script, conf = upright[0], upright[1]
        script = (script, conf)
        turns[n] = turn
        use, lost = _ocr_plan(have, "", script)
        # a Han page: chi_sim reads it first whatever the user's own - its confidence tells a traditional page and
        # chi_tra's does not tell a simplified one (OCR_HAN_SURE) - and chi_tra again where chi_sim is unsure
        han = bool(lib) and use in (["chi_sim"], ["chi_tra"]) and "chi_sim" in have
        if han:
            use = ["chi_sim"]
        plans[n] = (use, lost, script)
        t_read = now()
        got = read(png, use, max(1.0, secs - (t_read - t_page)), turn)
        once = now() - t_read

        def room():
            """The page's time allows one more reading."""
            return now() - t_page + once < secs

        # OSD's turn is checked where the page read turned is unsure of itself: OSD took upright pages of a magazine
        # set in Fraktur for upside down (at 6.9 and 9.4; at 11.0 rendered again), and was as sure of them turned; read
        # as they lay they were the surer (50 and 51 against 33 and 29), and turned copies read turned at 64-93. The
        # check is made whatever time is left (a slow machine's turned reading can take most of it): the page read
        # as it lies, even cut short, is better than one read upside down
        if turn and got[0] == 0 and 0 <= got[3] < OCR_UNSURE:
            as_is = read(png, use, max(1.0, secs - (now() - t_page)), 0, True)
            if as_is[0] == 0 and as_is[3] >= got[3] + OCR_HAN_MARGIN:
                got, turn, turns[n] = as_is, 0, 0
        first = got

        def han_order(got, use):
            """... then chi_tra, and jpn for a Japanese page OSD took for Han (kanji-heavy text: its kana are what make
            it Japanese to OSD), each while the best reading is that unsure and the page's time allows one more."""
            for alt, sure in (("chi_tra", OCR_HAN_SURE), ("jpn", OCR_HAN_JAPANESE)):
                if alt not in have or not 0 <= got[3] < sure:
                    continue
                if not room():
                    break
                other = read(png, [alt], max(1.0, secs - (now() - t_page)), turn)
                if other[0] == 0 and other[3] >= got[3] + OCR_HAN_MARGIN:
                    got, use = other, [alt]
            return got, use

        # a page in vertical columns (OCR_VERTICAL_SHARE): the vertical packs, its script's first
        cjk = _CJK_SCRIPTS.get(script[0], "")
        vertical = auto and got[0] == 0 and got[4] >= OCR_VERTICAL_SHARE and (cjk or 0 <= got[3] < OCR_UNSURE)
        if han and got[0] == 0 and not vertical:
            got, use = han_order(got, use)
            plans[n] = (use, lost, script)
        if vertical:
            best = None
            for pack, under in OCR_VERTICAL_PACKS.get(cjk, OCR_VERTICAL_ELSE):
                if pack not in have or best is not None and best[0][3] >= under:
                    continue
                if best is not None and best[0][3] < first[3] or not room():
                    break                                # read less surely than the page's own: not vertical CJK
                other = read(png, [pack], max(1.0, secs - (now() - t_page)), turn)
                if other[0] == 0 and (best is None or other[3] >= best[0][3]):
                    best = (other, [pack])
            if best is not None and best[0][3] >= first[3]:
                got, plans[n] = best[0], (best[1], lost, script)
        # a script OSD is unsure of, or a Latin reading unsure of itself: the likeliest other scripts' packs
        elif auto and got[0] == 0 and 0 <= got[3] < OCR_UNSURE and (
                script[0] == "Latin" or script[1] < OCR_SCRIPT_TRUST.get(script[0], OCR_SCRIPT_TRUST_ELSE)):
            tried = [plans[n][0]]
            for name in [script[0]] + list(OCR_SCRIPT_TAKEN.get(script[0], ())):
                if got[3] >= OCR_UNSURE or len(tried) > OCR_UNSURE_TRIES or not room():
                    break
                cand, gap = _ocr_plan(have, "", (name, 1e9))
                if gap or cand in tried or (name != "Latin" and _pack_script(cand[0]) == "Latin"):
                    continue                             # its pack is not here, or it is a reading already made
                tried.append(cand)
                other = read(png, cand, max(1.0, secs - (now() - t_page)), turn)
                if other[0] == 0 and cand in (["chi_sim"], ["chi_tra"]):
                    other, cand = han_order(other, cand)
                if other[0] == 0 and other[3] >= got[3] + OCR_HAN_MARGIN:
                    got, plans[n] = other, (cand, lost, script)
        # a page whose words are a Latin-script language with a pack here that it was not read with: read again with
        # it, English beside it, while the page's time allows the same again
        lang = intl.latin_pack(got[1].decode("utf-8", "replace")) if got[0] == 0 and auto else ""
        took = now() - t_page
        if lang and lang not in plans[n][0] and lang in have and took * 2 < secs and not any(
                x.endswith("_vert") or x == "frk" for x in plans[n][0]):     # Fraktur's German is frk's own
            again = read(png, [lang, "eng"], max(1.0, secs - took), turn)
            if again[0] == 0 and again[1].strip():
                got, plans[n] = again, ([lang, "eng"], lost, script)
        done[n] = got[:3]

    # the pages side by side: three took 1.3-1.5 s together, 0.7-1.5 s each in a row
    threads = [threading.Thread(target=one, args=pg, daemon=True) for pg in pages]
    for t in threads:
        t.start()
    for t in threads:
        t.join(secs + 5)
    out = []
    for n, _png in pages:
        rc, so, _se = done.get(n) or (-1, b"", b"")
        if rc == 0 and so.strip():
            out.append(so.decode("utf-8", "replace").strip())
        elif rc == -1:
            # a page that did not finish in time: the other pages are kept, and the answer
            # names this one instead of leaving a silent gap
            info["timeouts"].append(n)
            out.append("[page %d: OCR did not finish in %d s]" % (n, int(secs)))
    # the packs the pages were read with, and those their scripts needed and this machine lacks, page by page
    scripts = []
    for n, _png in pages:
        use, lost, script = plans.get(n) or (_use, [], ("", 0.0))
        info["used"] += [x for x in use if x not in info["used"]]
        info["missing"] += [x for x in lost if x not in info["missing"]]
        scripts.append(("%s %.1f" % script if script[0] else "?") + (
            " turned %d" % turns[n] if turns.get(n) else ""))
    budget.record("ocr", t_ocr, budget.ended(OCR_TIMEOUT, secs) if info["timeouts"] else "ok",
                  own=OCR_TIMEOUT, given=secs, note="%s, %d pages, %d late, %s; osd: %s" % (
                      info["engine"], len(pages), len(info["timeouts"]), "+".join(info["used"]),
                      ", ".join(scripts) if detect else "none"))
    return "\n\n".join(out), info


# Our readers of EPUB, OpenDocument (ODT, ODS, ODP) and RTF (docreaders.py) run in a process of their
# own: a file of a few KB made them take gigabytes or minutes (2026-11-21), and in this process nothing
# could stop them. They stop themselves at their time; the process is killed at it, and its memory is
# held where the OS can hold it (docreaders._limit_memory). All the read's documents share the
# converter's time - a ZIP's 30 gave each one its own 10 s - and with --download there is no limit.
_DOCS = {"spent": 0.0}             # the read's converter clock for these documents


def own_doc(path, kind, pictures=None):
    """An EPUB, ODT, ODS, ODP or RTF through docreaders.py in its own process: (markdown, note).
    `pictures`: a folder an RTF's pictures are written to (rtf_images() takes them from there)."""
    unlimited = budget.unlimited()
    left = CONVERTER_TIMEOUT - _DOCS["spent"]
    if not unlimited and left < 0.2:
        return "", ("not read: the %d s this read has for its documents were spent on the others; --download "
                    "reads them all" % CONVERTER_TIMEOUT)
    secs = None if unlimited else budget.cap(left, floor=min(left, 1.0))
    t0 = now()
    # the reading stops a little before the kill, and what was read is written between the two
    until, kill = (0.0, 0.0) if secs is None else (t0 + secs - min(2.0, secs * 0.4), t0 + secs)
    # -I -S: the standard library alone, nothing of the caller's environment or site; the start of a
    # process is the cost (0.1 s on Windows, measured 2026-11-21: 0.01 s less than -E -B)
    cmd = [sys.executable, "-I", "-S", "-B", "-X", "utf8",
           os.path.join(os.path.dirname(os.path.abspath(__file__)), "docreaders.py"),
           kind, path, "%.3f" % until, "%.3f" % kill] + ([pictures] if pictures else [])
    rc, so, se = run(cmd, timeout=secs)
    dt = now() - t0
    _DOCS["spent"] += dt
    if rc == -1 and (secs is None or dt < secs - 0.05):
        return "", "the reader failed: its process did not start (%s)" % se.decode("utf-8", "replace")[:120]
    if rc == -1:
        budget.record("docreader", t0, budget.ended(CONVERTER_TIMEOUT, secs), own=CONVERTER_TIMEOUT, given=secs,
                      note=kind)
        return "", "the %s reader did not finish in %.0f s and was stopped" % (kind.upper(), secs or 0)
    try:
        if rc != 0:
            raise ValueError("exit code %s" % rc)
        res = json.loads(so.decode("utf-8", "replace"))
        md, why = res.get("md") or "", res.get("note") or ""
    except ValueError as e:
        err = [ln for ln in se.decode("utf-8", "replace").splitlines() if ln.strip()]
        budget.record("docreader", t0, "fail", own=CONVERTER_TIMEOUT, given=secs, note=kind)
        return "", "the reader failed: %s" % (err[-1].strip() if err else str(e))[:160]
    budget.record("docreader", t0, "ok", own=CONVERTER_TIMEOUT, given=secs,
                  note="%s, %d words" % (kind, len(md.split())))
    # whether the process's memory was held (docreaders._limit_memory): a Job Object that could not be
    # set left the reader with no limit, and nothing said so
    held = res.get("limit")
    if held is False and sys.platform != "darwin":
        debuglog.log("docreader", what="its memory is not held: the OS refused the limit", kind=kind)
    trace("document.own", kind=kind, words=len(md.split()), note=why[:120],
          memory="held" if held else "not held")
    return md, why


def pandoc_md(exe, path, fmt, secs):
    """pandoc -> the Markdown an agent reads ("" when it fails). gfm keeps what Markdown cannot say
    as HTML; -raw_html instead turns a table with merged or multi-paragraph cells into "[TABLE]",
    its text gone (2026-11-19). So: gfm, lines unwrapped, then clean_pandoc()."""
    rc, so, _se = run([exe, path] + (["-f", fmt] if fmt else []) + ["-t", "gfm", "--wrap=none"], timeout=secs)
    return clean_pandoc(so.decode("utf-8", "replace")) if rc == 0 and so.strip() else ""


_TAG = re.compile(r"(?<!\\)</?[a-zA-Z][\w:-]*(?:\s[^<>]*)?/?>")
_BLOCK_END = re.compile(r"</(?:p|div|li|dt|dd|h[1-6]|blockquote|section|figure|figcaption|article|aside|"
                        r"header|footer|tr|ul|ol|dl|details|summary)\s*>|<br\s*/?>", re.I)


def clean_pandoc(md):
    """pandoc's HTML leftovers out of its Markdown, code untouched (2026-11-19, on 12 EPUBs: a poem
    came back with every line in a div, +39 % of noise words; Pro Git's examples as raw
    <pre><code>; an HTML book's examples lost their tags to a cleanup that did not spare code).
    Fenced and inline code stay as they are; a raw <pre><code> becomes a fenced block; a table one
    row a line, cells joined by | (the office readers' form); a picture ![alt](src), so it becomes
    a marker; a link [text](address); any other tag goes, its text stays."""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")      # pandoc on Windows: CRLF
    out, prose, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if m:
            # a fenced block, verbatim to its own closing fence (CommonMark: one opened by four
            # backticks holds a line of three)
            out.append(_clean_prose("\n".join(prose)))
            prose, block, fence = [], [line], m.group(1)
            i += 1
            while i < len(lines):
                block.append(lines[i])
                c = re.match(r"^ {0,3}(`{3,}|~{3,})\s*$", lines[i])
                i += 1
                if c and c.group(1)[0] == fence[0] and len(c.group(1)) >= len(fence):
                    break
            out.append("\n".join(block))
            continue
        if re.match(r"(?i)^ {0,3}<pre\b", line):
            # a raw <pre> block, to its </pre> - a fence line inside it is its text, not a fence
            out.append(_clean_prose("\n".join(prose)))
            prose, block = [], [line]
            while "</pre>" not in lines[i].lower() and i + 1 < len(lines):
                i += 1
                block.append(lines[i])
            i += 1
            out.append(_clean_prose("\n".join(block)))
            continue
        prose.append(line)
        i += 1
    out.append(_clean_prose("\n".join(prose)))
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "\n".join(out)).strip() + "\n"


def _clean_prose(text):
    def pre(m):
        body = unescape(_TAG.sub("", m.group(1)))
        fence = "`" * max([3] + [len(r) + 1 for r in re.findall(r"`{3,}", body)])
        return "\n\n%s\n%s\n%s\n\n" % (fence, body.strip("\n"), fence)

    def table(m):
        rows = []
        for tr in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", m.group(0)):
            cells = [re.sub(r"\s+", " ", unescape(_TAG.sub(" ", cell))).strip()
                     for cell in re.findall(r"(?is)<t[hd]\b[^>]*>(.*?)</t[hd]>", tr)]
            if any(cells):
                rows.append(" | ".join(cells))
        return "\n\n%s\n\n" % "\n".join(rows)

    def img(m):
        src = re.search(r'(?i)\bsrc="([^"]*)"', m.group(0))
        alt = re.search(r'(?i)\balt="([^"]*)"', m.group(0))
        return "![%s](%s)" % (unescape(alt.group(1)) if alt else "", src.group(1)) if src else ""

    def link(m):
        a = re.match(r"(?is)<a\b([^>]*)>(.*?)</a>", m.group(0))
        href = re.search(r'(?i)\bhref="([^"]*)"', a.group(1))
        inner = a.group(2)
        return "[%s](%s)" % (inner, unescape(href.group(1))) if href and inner.strip() else inner

    def outside_code(pattern, fn, s):
        # code spans and fenced blocks pass whole; a tag that starts before a backtick is taken
        # whole too (an alt text with `iss53` in it cut the tag in two)
        rx = re.compile(r"(?P<tick>`+)(?:.+?)(?P=tick)|(?P<hit>%s)" % pattern, re.I | re.S)
        return rx.sub(lambda m: fn(m) if m.group("hit") is not None else m.group(0), s)
    text = re.sub(r"(?is)<pre\b[^>]*>\s*(?:<code\b[^>]*>)?(.*?)(?:</code>)?\s*</pre>", pre, text)
    text = outside_code(r"<script\b.*?</script>|<style\b.*?</style>", lambda m: "", text)   # a nav page's script
    text = outside_code(r"<table\b.*?</table>", table, text)
    text = outside_code(r"<img\b[^>]*>", img, text)
    text = outside_code(r"<a\b[^>]*>.*?</a>", link, text)
    text = outside_code(_BLOCK_END.pattern, lambda m: "\n", text)
    text = outside_code(_TAG.pattern, lambda m: "", text)
    return outside_code(r"&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]*);", lambda m: unescape(m.group(0)), text)


ZIP_TEXT = (".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".ini", ".cfg", ".log",
            ".html", ".htm", ".rst", ".py", ".js", ".ts", ".css", ".sql", ".sh", ".bat", ".ps1", ".toml")
ZIP_DOCS = (".pdf", ".docx", ".xlsx", ".pptx", ".epub", ".odt", ".rtf")


def zip_text(path, c, workdir, broken=()):
    """A plain archive (not an office file or a book): what is in it, and the text of what can be
    read - text files as they are, documents through the same converters, one level deep. 30
    members at most, none over 20 MB unpacked, 60 MB in all; a member is unpacked under a name of
    our own, never its path. A document that gives no text says why under its name (its reader
    stopped, the read's converter time spent on the others), and so does a member that does not
    unpack. `broken`: [(name, why)] of a cut archive's members that are not whole, listed after the
    whole ones."""
    import zipfile
    out, read = [], 0
    try:
        with zipfile.ZipFile(path) as z:
            docreaders.fix_zip_names(z)                # names in GBK, Shift-JIS... with no UTF-8 flag
            infos = [i for i in z.infolist() if not i.is_dir()]
            listed = ["- %s (%s)" % (i.filename, human_bytes(i.file_size)) for i in infos[:200]]
            if len(infos) > 200:
                listed.append("- ... and %d more" % (len(infos) - 200))
            listed += ["- %s (not read: %s)" % b for b in list(broken)[:20]]
            out.append("Files in the archive (%d%s):\n\n%s" % (
                len(infos), ", and %d that are not whole" % len(broken) if broken else "", "\n".join(listed)))
            for n, i in enumerate(infos[:30], 1):
                ext = os.path.splitext(i.filename.lower())[1]
                if ext not in ZIP_TEXT + ZIP_DOCS or i.file_size > 20 * 1024 * 1024 or read > 60 * 1024 * 1024:
                    continue
                try:
                    data = z.read(i)
                except Exception as e:                        # noqa: BLE001  (a CRC that does not match, data that breaks)
                    out.append("## %s\n\n(it does not unpack: %s)" % (i.filename, str(e)[:80] or type(e).__name__))
                    continue
                read += len(data)
                if ext in ZIP_TEXT:
                    text, _enc = smart_decode(data, "")
                    if ext in (".html", ".htm"):
                        text = visible_text(text)
                else:
                    member = os.path.join(workdir, "_zip%02d%s" % (n, ext))
                    with open(member, "wb") as fh:
                        fh.write(data)
                    kind, _ = detect_kind(data[:4096], "", member)
                    nested = kind == "zip" and zip_subtype(member) == "other"     # one level deep
                    text, why = (doc_text(member, kind, c, workdir, name=i.filename)
                                 if kind in ("pdf", "zip", "rtf") and not nested else ("", ""))
                    if not text.strip() and why:
                        text = "(%s)" % why
                if text.strip():
                    out.append("## %s\n\n%s" % (i.filename, text.strip()))
    except Exception as e:                                    # noqa: BLE001
        debuglog.exc("zip: members", e)
    return "\n\n".join(out)


# ---------------------------------------------------------------- a PDF's tables
# PyMuPDF's text has a table one cell a line, and a reader has to guess which number belongs to
# which row. Measured 2026-11-19 on 94 tables of 9 arXiv papers whose cells are known (their HTML
# on ar5iv: 889 rows) and 17 tables printed from HTML (250 rows), counting the rows that come out
# as a table row with each cell its own: PyMuPDF's line-based find_tables() 2 % of the papers'
# rows (9 % with refine) and 65 % of the printed ones, with tables made of figures (a sentence, a
# letter a column); pdfplumber 0-17 % and thousands of rows that are no table; pymupdf4llm without
# its layout model 2 %; with the model 68 % and 99 %. So the pages that look like they hold a
# table go through that model (pdftables.py, in a process of its own), and its tables - its grid
# filled with the page's own words - stand where the blocks they cover stood; the rest of the page
# is PyMuPDF's text as before. Not find_tables() with the model switched on: its cells come out
# scrambled there (610.01 as "61001 .", PyMuPDF 1.28.2).
PDF_TABLES_SECONDS = 10        # the model's time in a read, all its documents together
PDF_TABLE_CAPTION = pdftables.CAPTION
PDF_TABLE_NUMBER = re.compile(r"(?m)^\s*[-+−–±$€£]?\s?\(?\d[\d.,]*\)?\s?[%‰KMBkmb]?\s*$")
PDF_TABLE_NUMBERS = 12         # lines that are one short number: a table's cells, one a line
PDF_TABLE_RULES = 8            # horizontal rulings among the page's drawings
# What the model would take too long over for a read's time (2026-11-20, 398 pages of 29 PDFs and
# synthetic pages): vector paths - 20 010 separate strokes, a scatter plot drawn point by point,
# held it 20-27 s, while no page of the corpus has over 4 975 - and the words of the page's largest
# text block (2 000 of 3 pt numbers 0.56 s, 3 000 1.8 s, 6 000 9.6 s; the corpus' largest 976). A
# page over either is not asked and is named; --download asks it. The counts do not catch every
# slow page (2 010 strokes took 11 s): the model's process is killed when the time is up.
PDF_TABLE_PATHS = 8000
PDF_TABLE_WORDS = 2000
PDF_TABLES_AHEAD = 2           # pages sent to the model before their answers: it never waits for one
PDF_MARKDOWN_WARMUP = 2        # --alternate: the first call's pages, which give the model's rate here
PDF_MARKDOWN_CALL = 10         # ... and the most of one call after it: the time's end costs one call
PDF_MARKDOWN_PAGE = 0.5        # a page's seconds when no call said its rate
_PDF = {}                      # what the read did about tables, all its PDFs, for the manifest
_TABLES = {"spent": 0.0, "worker": None}       # the read's tables clock and its model's process
_TABLES_LOCK = threading.RLock()


def tables_reset():
    """A read starts: the tables clock and the manifest's tables at nothing."""
    with _TABLES_LOCK:
        _PDF.clear()
        _TABLES["spent"] = 0.0


class TablesWorker:
    """The read's layout model in a process of its own (pdftables.py): pages go in, each page's
    answer comes out as it is done, and the read takes what came by its time. The model's call
    cannot be interrupted, so a process still at it then is killed."""

    def __init__(self):
        popen_kw = {"start_new_session": True} if os.name != "nt" else {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        # -E: a caller's PYTHONPATH stays out of the model, as the hop keeps it out of the read (a
        # folder of another Python's PyMuPDF cost every PDF its tables); -B, as the hop passes it.
        # --parent: it ends with this read, however the read ends
        self.p = subprocess.Popen([sys.executable, "-E", "-B", "-X", "utf8",
                                   os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdftables.py"),
                                   "--parent", str(os.getpid())],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  **popen_kw)
        _CHILDREN.add(self.p)
        self.q = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        try:
            for line in self.p.stdout:
                try:
                    self.q.put(json.loads(line.decode("utf-8", "replace")))
                except ValueError:
                    continue
        except (OSError, ValueError):
            pass
        self.q.put({"gone": True})

    def send(self, req):
        try:
            self.p.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
            self.p.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def get(self, until):
        """The next answer by the moment `until` (now() based), None when none came. A read with
        no deadline waits in steps: a lock's wait has a ceiling (Windows: 49 days, not 1e9 s)."""
        while True:
            left = until - now()
            try:
                return self.q.get(timeout=max(0.0, min(left, 3600.0)))
            except queue.Empty:
                if left <= 3600.0:
                    return None

    def kill(self):
        try:
            self.p.kill()                    # one process, no children of its own: no taskkill's 0.1 s
            self.p.wait(5)
        except Exception as e:                                # noqa: BLE001
            debuglog.exc("pdf: tables worker", e)
            kill_tree(self.p)
        _CHILDREN.discard(self.p)

    def close(self):
        try:
            self.p.stdin.close()             # the end of its requests: it ends by itself
            self.p.wait(2)
        except Exception:                                     # noqa: BLE001
            self.kill()
        _CHILDREN.discard(self.p)


def tables_worker():
    """This read's model process, started at its first page; None when it cannot start."""
    if _TABLES["worker"] is None:
        try:
            _TABLES["worker"] = TablesWorker()
        except OSError as e:
            debuglog.exc("pdf: tables worker", e)
            return None
    return _TABLES["worker"]


def tables_close(kill=False):
    w, _TABLES["worker"] = _TABLES["worker"], None
    if w:
        w.kill() if kill else w.close()


def pdf_table_page(page, text, drawings=True):
    """Does the page look like it holds a table: a caption line (Table 3, TABLE IV, Таблица 2), a
    run of lines that are one number, or rulings among its drawings (the list itself, when the
    caller has it). On 398 pages these chose 49 % and had 94 % of the pages where the model then
    found a table; a page chosen for nothing costs its seconds."""
    if PDF_TABLE_CAPTION.search(text) or len(PDF_TABLE_NUMBER.findall(text)) >= PDF_TABLE_NUMBERS:
        return True
    if not drawings:
        return False
    n = 0
    try:
        for d in (drawings if isinstance(drawings, list) else page.get_cdrawings()):
            r = d.get("rect")
            if r and r[2] - r[0] >= 40 and r[3] - r[1] <= 2.5:
                n += 1
                if n >= PDF_TABLE_RULES:
                    return True
    except Exception as e:                                     # noqa: BLE001
        debuglog.exc("pdf: drawings", e)
    return False


def pdf_heavy(page, drawings):
    """Why the model would take too long over this page for a read's time, "" when it would not."""
    if len(drawings) > PDF_TABLE_PATHS:
        return "%d vector paths" % len(drawings)
    try:
        big = max([len(b[4].split()) for b in page.get_text("blocks") if b[6] == 0] or [0])
    except Exception as e:                                     # noqa: BLE001
        debuglog.exc("pdf: blocks", e)
        big = 0
    return "%d words in one block" % big if big > PDF_TABLE_WORDS else ""


def _drawings(page):
    try:
        return page.get_cdrawings()
    except Exception as e:                                     # noqa: BLE001
        debuglog.exc("pdf: drawings", e)
        return []


def pdf_tables(path, doc, pages):
    """The tables of the pages that look like they hold one, put into `pages` (each page's plain
    text) in place. The model has PDF_TABLES_SECONDS a read for all its documents, or what the
    read has left - and all the time it needs in a read with no deadline (--download); a page too
    heavy for that time is not asked, and the pages not laid out stay plain and are named: those
    the time did not reach, and those after the model's process stopped (`stopped`, with `error`).
    Returns {"pages", "left", "heavy", "stopped", "more", "tables", "asked", "secs", "of", "error"}
    with page numbers from 1, {} when no page looks like it (then the model is not started)."""
    with _TABLES_LOCK:
        t_start = now()
        unlimited = budget.unlimited()
        secs = 1e9 if unlimited else budget.cap(max(0.0, PDF_TABLES_SECONDS - _TABLES["spent"]))
        end = t_start + secs
        info = {"pages": [], "left": [], "heavy": [], "tables": 0, "asked": 0, "of": len(pages)}
        sent, named, state = [], [], {"stop": "", "by_text": 0}   # asked and not answered; named

        def answer(a):
            if a is None:
                return
            if a.get("gone") or a.get("fatal"):
                # the model does not load here, or its process ended: no page fares better
                info["error"] = (a.get("fatal") or "the model's process ended")[:160]
                state["stop"] = "error"
                return
            p = a.get("page")
            if not isinstance(p, int) or p not in sent:
                return
            sent.remove(p)
            info["asked"] += 1
            if a.get("error"):
                info["error"] = ("page %d: %s" % (p + 1, a["error"]))[:160]   # this page only
                trace("pdf.tables", page=p + 1, error=a["error"][:120])
            elif a.get("text") and a.get("n"):
                pages[p] = a["text"]
                info["pages"].append(p + 1)
                info["tables"] += int(a["n"])
            for note in a.get("notes") or []:
                trace("pdf.tables", page=p + 1, note=note)

        w = None
        for i in range(len(pages)):
            while w is not None and not state["stop"]:
                a = w.get(0)                  # what came meanwhile
                if a is None:
                    break
                answer(a)
            if state["stop"] or now() >= end:
                # no time, or no model, for one more page: the rest is named by the text's own
                # signs, which cost nothing (a page's drawings can take a tenth of a second)
                state["stop"] = state["stop"] or "time"
                state["by_text"] += 1
                if pdf_table_page(None, pages[i], drawings=False):
                    named.append(i + 1)
                continue
            page = doc[i]
            draw = _drawings(page)
            if not pdf_table_page(page, pages[i], drawings=draw):
                continue
            why = "" if unlimited else pdf_heavy(page, draw)
            if why:
                info["left"].append(i + 1)
                info["heavy"].append(i + 1)
                trace("pdf.tables", page=i + 1, heavy=why)
                continue
            if w is None:
                w = tables_worker()
                if w is None:
                    info["error"] = "the model's process did not start"
                    state["stop"] = "error"
                    named.append(i + 1)
                    continue
            while len(sent) >= PDF_TABLES_AHEAD and not state["stop"]:
                a = w.get(end)
                if a is None:
                    state["stop"] = "time"
                answer(a)
            if state["stop"]:
                named.append(i + 1)
                continue
            if not w.send({"path": path, "pages": [i]}):
                # it has ended: what it said before it went (a model that does not load) is the why
                while not state["stop"]:
                    answer(w.get(min(end, now() + 2.0)) or {"gone": True})
                named.append(i + 1)
                continue
            sent.append(i)
        while sent and w is not None and not state["stop"]:
            a = w.get(end)
            if a is None:
                state["stop"] = "time"
            answer(a)
        if sent and w is not None:
            # the model is still at a page, or has stopped: its process goes, the pages are named
            tables_close(kill=True)
            named += [p + 1 for p in sent]
        elif state["stop"] == "error":
            tables_close(kill=True)
        info["left"] = sorted(set(info["left"]) | set(named))
        if state["stop"] == "error" and named:
            info["stopped"] = sorted(set(named))
        if state["by_text"] and state["stop"] == "time":
            info["more"] = True               # rulings alone were not looked for after the time
        info["secs"] = round(now() - t_start, 2)
        _TABLES["spent"] += info["secs"]
        if not (info["asked"] or info["left"] or info.get("error")):
            return {}
        budget.record("pdf-tables", t_start, "fail" if info.get("error") and not info["asked"] else
                      "ok" if not info["left"] else budget.ended(PDF_TABLES_SECONDS, secs),
                      own=PDF_TABLES_SECONDS, given=None if secs >= 1e9 else secs,
                      note="%d tables on %d of %d pages asked%s%s" % (
                          info["tables"], len(info["pages"]), info["asked"],
                          ", %d pages not laid out" % len(info["left"]) if info["left"] else "",
                          ", " + info["error"] if info.get("error") else ""))
        return info


def pdf_markdown(path, doc, pages):
    """--alternate: pymupdf4llm's Markdown of the document - headings, its tables in its own way -
    in the model's process, within what the read has left (a PDF of 600 pages took 114 s at one
    go). A warm-up call of two pages gives the model's rate here; then calls of ten pages at most,
    each to fit what is left, so the time's end costs one small call (four reads at once on two
    slow cores - 0.9 s a page and more - lost every page to a call of 57, 2026-11-21). A page too
    heavy for a read's time, and the pages no call reached, stay PyMuPDF's text and are named.
    With no deadline (--download), one call: the headings of the whole document as one.
    Returns (text or None, info) - None when no page was laid out; info says why either way."""
    with _TABLES_LOCK:
        t_start = now()
        unlimited = budget.unlimited()
        secs = 1e9 if unlimited else budget.cap(1e9)
        end = t_start + secs
        # its pages are every page but those left: not listed (a long document's list is long)
        info = {"left": [], "heavy": [], "asked": 0, "of": len(pages), "markdown": True}
        md, rate, i, failed = {}, None, 0, False
        w = tables_worker()
        if w is None:
            info["error"], failed = "the model's process did not start", True
        while w is not None and i < len(pages):
            left = end - now()
            if unlimited:
                n = len(pages) - i
            elif rate is None:
                n = PDF_MARKDOWN_WARMUP
            else:
                n = min(PDF_MARKDOWN_CALL, int(max(0.0, left * 0.9) / rate))
            if n < 1 or left <= 0:
                break
            chunk = []
            for k in range(i, min(len(pages), i + n)):
                why = "" if unlimited else pdf_heavy(doc[k], _drawings(doc[k]))
                if why:
                    info["heavy"].append(k + 1)
                    trace("pdf.markdown", page=k + 1, heavy=why)
                else:
                    chunk.append(k)
            i += n
            if not chunk:
                continue
            sent = w.send({"path": path, "pages": chunk, "markdown": True})
            want, stop, each = set(chunk), False, []
            while want:
                # a process that has ended said why before it went (a model that does not load)
                a = w.get(end if sent else min(end, now() + 2.0))
                if a is None and not sent:
                    a = {"gone": True}
                if a is None or a.get("gone") or a.get("fatal"):
                    if a is not None:
                        info["error"], failed = (a.get("fatal") or "the model's process ended")[:160], True
                    stop = True
                    break
                p = a.get("page")
                if p in want:
                    want.discard(p)
                    info["asked"] += 1
                    if a.get("error"):
                        info["error"] = ("page %d: %s" % (p + 1, a["error"]))[:160]
                    else:
                        md[p] = a.get("text") or ""
                    if a.get("s"):
                        each.append(float(a["s"]))
            if stop:
                tables_close(kill=True)
                break
            # the model's own seconds a page, from the child's clock: no process start, no load
            rate = max(0.01, max(each) if each else rate or PDF_MARKDOWN_PAGE)
        info["left"] = sorted(set(info["heavy"]) | {k + 1 for k in range(len(pages)) if k not in md})
        if failed and info["left"]:
            info["stopped"] = [p for p in info["left"] if p not in set(info["heavy"])]
        info["secs"] = round(now() - t_start, 2)
        budget.record("pdf-markdown", t_start, "fail" if failed else "ok" if not info["left"] else "deadline",
                      given=None if secs >= 1e9 else secs,
                      note="%d of %d pages laid out%s" % (len(md), len(pages),
                                                         ", " + info["error"] if info.get("error") else ""))
        if not md:
            return None, info
        return "".join(md[k] if k in md else pages[k] + "\n\n" for k in range(len(pages))), info


PAGE_LISTS = ("pages", "left", "heavy", "stopped")


def tables_merge(info, name=""):
    """One PDF's tables into the read's: the read's own document at the top, a PDF inside an
    archive under `files` by its name; the counts and seconds are the read's."""
    if not info:
        return
    with _TABLES_LOCK:
        if name:
            _PDF.setdefault("files", []).append(dict({"name": name[:120]}, **{
                k: info[k] for k in PAGE_LISTS + ("tables", "of", "more") if info.get(k)}))
        else:
            for k in PAGE_LISTS + ("of", "markdown", "more"):
                if info.get(k):
                    _PDF[k] = info[k]
        for k in ("tables", "asked"):
            if info.get(k):
                _PDF[k] = _PDF.get(k, 0) + info[k]
        if info.get("secs"):
            _PDF["secs"] = round(_PDF.get("secs", 0) + info["secs"], 2)
        if info.get("error") and not _PDF.get("error"):
            _PDF["error"] = info["error"]


TABLES_KEYS = ("pages", "left", "heavy", "more", "tables", "asked", "secs", "of", "error", "files", "markdown")


def tables_signal():
    """signals.tables of this read, or {} when the step did nothing worth a word. Its page lists
    are ranges, as the advice writes them ("28-600"): grid600's list of 573 numbers made the
    object 2 966 characters of every MCP answer (2026-11-21)."""
    with _TABLES_LOCK:
        if not (_PDF.get("asked") or _PDF.get("left") or _PDF.get("error")
                or any(f.get("left") for f in _PDF.get("files") or [])):
            return {}
        out = {}
        for k in TABLES_KEYS:
            v = _PDF.get(k)
            if not v:
                continue
            if k in PAGE_LISTS:
                v = page_ranges(v)
            elif k == "files":
                v = [{kk: page_ranges(vv) if kk in PAGE_LISTS else vv for kk, vv in f.items() if kk != "stopped"}
                     for f in v]
            out[k] = v
        return out


def page_ranges(nums):
    """[2, 3, 4, 9] -> "2-4, 9"."""
    out, run = [], []
    for n in sorted(set(nums)) + [None]:
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(str(run[0]) if len(run) == 1 else "%d-%d" % (run[0], run[-1]))
        run = [n]
    return ", ".join(out)


def tables_advice(info):
    """What to say when pages that look like a table were not laid out - the time for tables ran
    out, a page was too heavy for a read's time, the model stopped: which pages (of which PDF in an
    archive), and the flag that gives the model the time, with what that would take here by the
    pages it did. `info` is the read's own (page lists as lists), not the manifest's ranges."""
    info = info or {}
    docs = [info] + list(info.get("files") or [])
    parts, n_left, heavy_any, late_any = [], 0, False, False
    for f in docs:
        left = f.get("left") or []
        heavy, stopped = set(f.get("heavy") or []), set(f.get("stopped") or [])
        late = [p for p in left if p not in heavy and p not in stopped]
        where = " of %s" % f["name"] if f.get("name") else ""
        n_left += len(left)
        heavy_any, late_any = heavy_any or bool(heavy), late_any or bool(late)
        if late:
            parts.append(("page%s %s%s" % ("s" if len(late) > 1 else "", page_ranges(late), where),
                          "the time for %s ran out%s" % ("the layout" if info.get("markdown") else "tables",
                                                         "; maybe more after it, judged by their text alone"
                                                         if f.get("more") else "")))
        if heavy:
            parts.append(("page%s %s%s" % ("s" if len(heavy) > 1 else "", page_ranges(heavy), where),
                          "too heavy to lay out in a read's time"))
        if stopped:
            parts.append(("page%s %s%s" % ("s" if len(stopped) > 1 else "", page_ranges(stopped), where),
                          "the layout model did not work: %s" % (info.get("error") or "")[:100]))
    if not parts:
        return ""
    asked, secs = info.get("asked") or 0, info.get("secs") or 0
    took = (" (about %d s here)" % max(1, int(round(secs / asked * (asked + n_left))))
            if asked and secs and late_any and not heavy_any and not info.get("stopped") else "")
    if len(parts) > 3:                       # an archive of many PDFs: the first two, and a count
        more = len(parts) - 2
        parts = parts[:2] + [("%d more of the archive's PDFs" % more if all(f.get("name") for f in docs[1:])
                              else "%d more" % more, "")]
    are = "is" if info.get("markdown") and n_left == 1 else "are"   # "the tables ... are"

    def said(what):
        if len(parts) == 1:
            return "%s %s %s (%s)" % (parts[0][0], are, what, parts[0][1])
        return "%s %s %s" % ("; ".join("%s (%s)" % p if p[1] else p[0] for p in parts), are, what)
    flag = (": --download has no time limit and lays %s%s" % ("out every page" if info.get("markdown")
                                                             else "them all out", took)
            if late_any or heavy_any else "")
    if info.get("markdown"):
        return said("PyMuPDF's plain text, not Markdown") + flag
    return "the tables on " + said("still one cell a line") + flag


def doc_text(path, kind, c, workdir, alternate=False, name=""):
    """PDF / DOCX / PPTX / XLSX / EPUB / ODT / RTF / a plain ZIP -> text, plus a note when a text
    layer is missing. EPUB, ODT and RTF are our own readers' (docreaders.py, the standard library
    alone, in a process of their own): measured against pandoc on 52 files they lose nothing it
    kept and keep what it lost (references/documents.md), so --setup installs no pandoc, and no
    markitdown either. A machine's own pandoc, then its markitdown, are the last resort for an
    office file the office readers cannot read. `name`: a file's name inside an archive (its
    tables are reported by it, and so is an archive of it that is not whole).

    An archive that does not open whole is read from its members that are (zip_whole); an office
    file whose members do not all unpack, from the ones that do (zip_mend). What was wrong with the
    read's own document is _ZIPS["read"], which its answer's status and advice are made of; a
    member's goes into its note. A file that is no ZIP is named for what it is (text is its text),
    and no machine's pandoc or markitdown is asked about either: they read archives as zipfile does.

    PyMuPDF and our readers' processes take the path as UTF-8: a file under a name of another code set's bytes is
    read through a link of ours (lib_path; KNOWN-ISSUES 175)."""
    with lib_path(path) as at:
        return _doc_text_at(at, kind, c, workdir, alternate, name)


def _doc_text_at(path, kind, c, workdir, alternate, name):
    src, broke = path, None
    if kind == "zip":
        path, broke = zip_whole(path, workdir)
        if not name:
            _ZIPS["read"] = broke
        if path is None:
            text = ""
            if broke.get("what") == "text":
                try:
                    with open(src, "rb") as fh:
                        text = smart_decode(fh.read(MAX_PAGE_BYTES), "")[0]
                except OSError:
                    text = ""
            return text, (broke["reason"] if name else "")
    state = {"broke": broke}
    text, note = _doc_text(path, kind, c, workdir, alternate, name, state)
    if state["broke"] is not broke and not name:
        _ZIPS["read"] = state["broke"]
    if name and state["broke"]:
        note = "; ".join(x for x in (state["broke"]["reason"], note) if x)
        zip_copy_gone(state["broke"], broke)       # a member's copy is read: it goes (the read's own after its pictures)
    return text, note


def zip_copy_gone(*infos):
    """The archives made of a cut or damaged one's whole members (_whole-*.zip, _mended-*.zip), once read:
    they stayed in the page's folder for its day, up to 128 MB each."""
    for info in infos:
        p = (info or {}).get("path") or ""
        if p and os.path.basename(p).startswith(("_whole-", "_mended-")):
            try:
                os.unlink(p)
            except OSError:
                pass


def _by_headers(path, workdir, state):
    """An archive zipfile opens, none of whose members a reader could unpack where its table of
    contents says they start (its offsets are wrong): its members read from their own headers, as
    a cut archive's are (zip_salvage). The copy's path, state["broke"] set; None when none is whole."""
    if state["broke"]:
        return None
    dest = os.path.join(workdir, "_whole-%s.zip" % hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:8])
    try:
        info = zip_salvage(path, dest, zip_until())
    except Exception as e:                                    # noqa: BLE001
        debuglog.exc("zip: by headers", e)
        return None
    if not info["whole"]:
        return None
    info["reason"], info["path"] = zip_reason(info), dest
    state["broke"] = info
    trace("zip.salvage", how=info["how"], members=info["members"], whole=len(info["whole"]),
          broken=len(info["broken"]), at=info["at"], more=info["more"][:60])
    return dest


def _doc_text(path, kind, c, workdir, alternate, name, state):
    """doc_text() of an archive that opens; state["broke"] is what was wrong with it, and an office
    file whose members do not all unpack sets it (zip_mend)."""
    note = ""
    sub = zip_subtype(path) if kind == "zip" else ""
    secs = budget.cap(CONVERTER_TIMEOUT, floor=1.0)
    if sub in ("docx", "xlsx", "pptx"):
        fast = office_fast(path, sub)
        if len(fast.strip()) <= 5 and not state["broke"] and _OFFICE.get("damaged"):
            # a member python-docx, python-pptx or openpyxl met does not unpack: the ones that do
            dest = os.path.join(workdir, "_mended-%s.zip" % hashlib.sha1(
                os.path.abspath(path).encode("utf-8")).hexdigest()[:8])
            salvaged = None
            try:
                info = zip_mend(path, dest, zip_until())
                if info["broken"] and not info["whole"]:
                    # not one member unpacks where the table of contents says it starts - its offsets
                    # are wrong (python-docx answered "negative seek value") while the members' own
                    # headers are right: they are read as a cut archive's are
                    salvaged = zip_salvage(path, dest, zip_until())
                    if salvaged["whole"]:
                        info = salvaged
            except Exception as e:                            # noqa: BLE001
                debuglog.exc("zip: mend", e)
                info = None
            if info and (info["broken"] or info is salvaged):
                info["reason"] = zip_reason(info)
                info["path"] = dest if info["whole"] else ""
                state["broke"] = info
                trace("zip.mend", members=info["members"], whole=len(info["whole"]), broken=len(info["broken"]))
                if not info["whole"]:
                    return "", ""
                path = dest
                fast = office_fast(path, sub)
        if len(fast.strip()) > 5:
            return fast, ""
    if kind == "rtf" or sub in ("odt", "ods", "odp"):
        # our reader's answer stands: a reader that breaks gives its plain text itself, in its own
        # process (the old plain readers here read a part whole, or in quadratic time; a sheet or a
        # slide deck was its paragraphs in this process, with no clock and no kill)
        # the read's own RTF writes its pictures out (a member of an archive's are passed over), into a
        # folder of this read's alone (an earlier read's, killed, may have left some)
        pics = os.path.join(workdir, RTF_PICTURES) if kind == "rtf" and not name else None
        if pics:
            shutil.rmtree(pics, ignore_errors=True)
        md, why = own_doc(path, "rtf" if kind == "rtf" else sub, pics)
        again = _by_headers(path, workdir, state) if kind == "zip" and not md.strip() and \
            "could not be unpacked" in why else None
        if again:
            md, why = own_doc(again, sub, pics)
        return md, why or ("" if md.strip() else "no text in this %s" % (sub or kind).upper())
    if kind == "pdf":
        if c["libs"].get("pymupdf"):
            text = None
            try:
                import pymupdf
                doc = pymupdf.open(path)
                pages = [p.get_text() for p in doc]
                text = "\n\f\n".join(pages)
            except Exception as e:                            # noqa: BLE001
                debuglog.exc("document: converter", e)
                note = str(e)[:100]
            if text is not None and len(text.strip()) < 20 * max(1, len(pages)):
                # a scan, with --alternate too: no layout tool finds text that is not there (its
                # three words once stood for the document, and the pages were never read)
                return text, "no text layer: this PDF is a scan; render pages to images and look at them"
            model = c["libs"].get("pymupdf4llm") and c["libs"].get("onnxruntime") is not False
            if text is not None and alternate and model:
                # with --alternate, pymupdf4llm's Markdown of the document - headings, every
                # table - when it is installed; 0.2-0.5 s a page, so not what a plain read does,
                # and within the read's time (pages it did not reach stay plain, named). Its text
                # only when it kept the document's words. No OCR of its own: a scan was answered
                # above, and ours reads it
                md, minfo = None, {}
                try:
                    md, minfo = pdf_markdown(path, doc, pages)
                except Exception as e:                            # noqa: BLE001
                    debuglog.exc("pdf: pymupdf4llm", e)
                    trace("pdf.pymupdf4llm", error=str(e)[:120])
                if md and len(md.split()) * 2 >= len(text.split()):
                    tables_merge(minfo, name)
                    return md, ""
                if minfo and not md:
                    # no page came as Markdown - its time ran out, or the model did not work: the
                    # read says which (it said nothing, and the advice spoke of tables), and the
                    # tables step would find no time or no model either
                    tables_merge(minfo, name)
                    return text, note
            elif text is not None and alternate:
                # pymupdf4llm 1.28 does not import without onnxruntime: --alternate is PyMuPDF's
                # text here, and says so (`improve` below names what installs the model)
                every = list(range(1, len(pages) + 1))
                tables_merge({"markdown": True, "of": len(pages), "left": every, "stopped": every,
                              "error": "pymupdf4llm %s" % ("needs onnxruntime, which is not installed here"
                                                           if c["libs"].get("pymupdf4llm") else
                                                           "is not installed here")}, name)
            if text is not None and "tables" not in SKIP:
                # the model needs onnxruntime too; a caps answer kept from before it was asked
                # about has no word on it, and the model's process says so if it is missing
                if model:
                    try:
                        info = pdf_tables(path, doc, pages)
                        tables_merge(info, name)
                        if info.get("pages"):
                            text = "\n\f\n".join(pages)
                    except Exception as e:                        # noqa: BLE001
                        debuglog.exc("pdf: tables", e)
                else:
                    # no model here: how many pages it would have been asked about (the answer's
                    # `improve` names what installs it)
                    wanted = sum(1 for p in pages[:400] if pdf_table_page(None, p, drawings=False))
                    if wanted:
                        with _TABLES_LOCK:
                            _PDF["wanted"] = _PDF.get("wanted", 0) + wanted
            if text is not None:
                return text, note
        if c["cli"].get("pdftotext"):
            outp = os.path.join(workdir, "_pdf.txt")
            pdf_in, pdf_out, pdf_done = narrow_paths([path], [outp])
            try:
                run([c["cli"]["pdftotext"], "-enc", "UTF-8", pdf_in[0], pdf_out[0]], timeout=secs)
            finally:
                pdf_done()
            if os.path.exists(outp):
                text = open(outp, encoding="utf-8", errors="replace").read()
                if len(text.strip()) < 20:
                    # the same verdict pymupdf reaches: nothing to read, so this is a scan.
                    # Without it a scan on a machine without pymupdf was just `empty`.
                    note = ("no text layer: this PDF is a scan; render pages to images "
                            "and look at them")
                return text, note
    if sub == "other":
        # a plain archive: its files and their text (a cut one's members that are not whole listed)
        text = zip_text(path, c, workdir, (state["broke"] or {}).get("broken") or ())
        if text.strip():
            return text, note
    elif sub == "epub":
        md, why = own_doc(path, "epub")
        again = _by_headers(path, workdir, state) if not md.strip() and "could not be unpacked" in why else None
        if again:
            md, why = own_doc(again, "epub")
        if md.strip() or not why.startswith("the reader failed"):
            return md, why or note or ("" if md.strip() else "no text in this EPUB")
        note = note or why
    if state["broke"]:
        return "", note                                 # what is whole of it has been read
    if kind == "zip" and sub not in ("other", "epub") and c["cli"].get("pandoc"):
        # a machine's own pandoc: the last resort for an office file the office readers cannot read
        # (a DOCX that is one formula; --setup installs none)
        md = pandoc_md(c["cli"]["pandoc"], path, sub if sub in ("docx", "pptx", "xlsx") else "", secs)
        if md.strip():
            return md, note
    if c["cli"].get("markitdown"):                      # a machine's own markitdown: the last resort
        outp = os.path.join(workdir, "_doc.md")
        rc, so, se = run_tool([c["cli"]["markitdown"], path, "-o", outp], timeout=secs)
        if rc == 0 and os.path.exists(outp):
            return open(outp, encoding="utf-8", errors="replace").read(), note
    if sub in OFFICE_LIBS:
        # the office reader and what it said: "no converter (pymupdf)" was said of a DOCX, whose reader
        # pymupdf is not
        lib = OFFICE_LIBS[sub]
        return "", note or ("no converter for this file type: %s is not installed here" % lib if _OFFICE.get("missing")
                            else "%s could not read it: %s" % (lib, _OFFICE.get("error") or "it gave no text"))
    return "", note or "no converter for this file type (pymupdf)"


# ---------------------------------------------------------------- external

def external_read(url, c, refresh=False):
    """The public readers in the order of READERS, inside one step of READERS_STEP_SECONDS.
    Returns (text, engine, status, note).

    The first reader with real text ends the chain, so no credit is spent after it. A wall, too
    little text, the service's own error, or no answer in READER_SECONDS moves on to the next one;
    a 404 or 410 that a reader saw ends the chain, since every reader would see it. A reader that
    is still sending when its time runs out keeps what arrived, in case nobody does better (the
    note then starts with "cut:"). `status` is what the page answered the reader, when one said.

    refresh=True asks the readers not to answer from their own cache: after a 404 we want to know
    what the page does *now*, not what a reader remembered.
    """
    if "external" in SKIP:
        return "", "external:disabled", None, "disabled by READ_PAGE_SKIP"
    # urllib's timeout is per socket operation, not per request: a reader that trickles would hold
    # the call for minutes, so each one runs under bounded()
    step_end = now() + budget.cap(READERS_STEP_SECONDS)
    notes, tried, status, spare = [], [], None, None
    no_key = [n for n in READERS if n in KEY_NEEDED and not os.environ.get(READER_KEYS[n])]
    walled = ""                    # a paid reader that reached the page and met its wall
    for name in READERS:
        if name in no_key:
            continue
        if walled and name in KEY_NEEDED:
            # the next paid reader would meet the same wall: in measurements Exa and Tavily never
            # gave text where Firecrawl and the free Jina did not, and a glass wall cost three
            # credits. A reader that failed for its own reason (no credit, timeout) is replaced.
            notes.append("%s: not asked, %s met the wall" % (name, walled))
            continue
        left = step_end - now()
        if left < READER_MIN_LEFT:
            notes.append("no time left for " + name)
            break
        tried.append(name)
        seconds = min(READER_SECONDS, left)
        got = []
        t_r = now()
        res, e = bounded(seconds, READER_CALLS[name], url, os.environ.get(READER_KEYS.get(name, ""), ""),
                         seconds, refresh, got)
        budget.record("reader:" + name, t_r,
                      (budget.ended(READER_SECONDS, seconds) if isinstance(e, TimeoutError) else "fail")
                      if e is not None else ("ok" if not (res[2] or (res[1] and res[1] >= 400)) else "fail"),
                      own=READER_SECONDS, given=seconds,
                      note=str(e)[:80] if e is not None else ("HTTP %s " % res[1] if res[1] else "") + (res[2] or "text"))
        if e is not None:
            part = b"".join(list(got)).decode("utf-8", "replace")
            if name in STREAMED and spare is None and not reader_text_why(part.split("Markdown Content:", 1)[-1]):
                spare = (part, name)
            notes.append("%s: %s" % (name, str(e)[:80] or type(e).__name__))
            continue
        text, st, why = res
        if st and st >= 400:
            status = status or st
            notes.append("%s: the page answered it %s" % (name, st))
            if st in (404, 410):
                break
            if name in KEY_NEEDED and st in (401, 403, 407, 419, 429, 451):
                walled = walled or name
            continue
        if why:
            notes.append("%s: %s" % (name, why))
            if name in KEY_NEEDED and why.startswith("reached a wall"):
                walled = walled or name
            continue
        return text, "reader:" + name, st or 200, ""
    if spare:
        return (spare[0], "reader:" + spare[1], 200,
                "cut: %s was still sending after %d s; the text may stop early" % (spare[1], READER_SECONDS))
    if no_key:
        notes.append("no key for " + ", ".join(no_key))
    return "", "reader:" + ("/".join(tried) or "none"), status, "; ".join(notes)[:400]


def reader_text_why(text, title=""):
    """Why a reader's answer is not the page's text, or "" when it is (a reader that met the
    page's wall sends the wall)."""
    wall = wall_signal({}, "", title or "", "", text or "", words_of(text or ""))
    if wall:
        return "reached a wall: " + wall
    if len((text or "").strip()) < 300 and words_of(text or "") < 40:
        return "returned too little"
    return ""


def _titled(text, title):
    """A reader's text with the page's title on top when the text has no heading of its own."""
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    if title and (text or "").strip() and not re.search(r"(?m)^#{1,2}\s+\S", text[:3000]):
        return "# %s\n\n%s" % (title, text.lstrip())
    return text


def _json(body):
    try:
        d = json.loads((body or b"").decode("utf-8", "replace"))
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def _service_said(code, body):
    d = _json(body)
    msg = d.get("error") or d.get("message") or d.get("detail") or ""
    if isinstance(msg, dict):
        msg = msg.get("message") or msg.get("error") or ""
    return "the service answered %s%s" % (code, ": " + re.sub(r"\s+", " ", str(msg))[:80] if msg else "")


def _reader_call(endpoint, payload, headers, seconds, got, method="POST"):
    """One request to a reader's service: (its HTTP code, the body). What arrived so far is in
    `got`, so a slow reader's text is kept when its time runs out."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    h = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers)
    req = urllib.request.Request(endpoint, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, seconds)) as r:
            read_into(r, got)
            return r.status, b"".join(got)
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(4000)
        except Exception:                                     # noqa: BLE001
            return e.code, b""


def _firecrawl(url, key, seconds, refresh, got):
    code, body = _reader_call(FIRECRAWL_URL, dict({"url": url, "formats": ["markdown"], "onlyMainContent": True},
                                                  **({"maxAge": 0} if refresh else {})),
                              {"Authorization": "Bearer " + key}, seconds, got)
    if code >= 400:
        return "", None, _service_said(code, body)
    data = _json(body).get("data") or {}
    meta = data.get("metadata") or {}
    st = meta.get("statusCode") if isinstance(meta.get("statusCode"), int) else None
    if st and st >= 400:
        return "", st, ""
    md = data.get("markdown") or ""
    return _titled(md, meta.get("title")), st, reader_text_why(md, meta.get("title"))


def _jina(url, key, seconds, refresh, got):
    # POST with the address in the body: in a GET path a #/ route is cut off and a Cyrillic
    # address fails with 'ascii' codec errors before anything is sent
    end = now() + seconds
    base = {"Accept": "text/plain"}
    if key:
        base["Authorization"] = "Bearer " + key

    def ask(no_cache):
        del got[:]
        h = dict(base, **({"X-No-Cache": "true"} if refresh or no_cache else {}))
        code, body = _reader_call(JINA_URL, {"url": url}, h, end - now(), got)
        return code, body.decode("utf-8", "replace")

    code, txt = ask(False)
    if code < 400 and "cached snapshot" in txt[:600].lower() and end - now() > 3:
        code2, fresh = ask(True)              # Jina says this is its own old copy: ask for the page now
        if code2 < 400 and len(fresh) > 500:
            code, txt = code2, fresh
    if code >= 400:
        return "", None, _service_said(code, txt.encode("utf-8"))
    m = re.search(r"Warning: Target URL returned error (\d{3})", txt[:600])
    if m:
        return "", int(m.group(1)), ""
    title = (re.search(r"(?m)^Title:\s*(.*)$", txt[:2000]) or [None, ""])[1]
    return txt, 200, reader_text_why(txt.split("Markdown Content:", 1)[-1], title)


def _exa(url, key, seconds, refresh, got):
    code, body = _reader_call(EXA_URL, dict({"urls": [url], "text": True},
                                            **({"livecrawl": "always"} if refresh else {})),
                              {"x-api-key": key}, seconds, got)
    if code >= 400:
        return "", None, _service_said(code, body)
    d = _json(body)
    said = (d.get("statuses") or [{}])[0] or {}
    if said.get("status") == "error":
        err = said.get("error") or {}
        hs = err.get("httpStatusCode")
        if isinstance(hs, int) and hs >= 400:
            return "", hs, ""
        return "", None, "no text (%s)" % (err.get("tag") or "error")
    res = (d.get("results") or [{}])[0] or {}
    text = res.get("text") or ""
    return _titled(text, res.get("title")), 200, reader_text_why(text, res.get("title"))


def _tavily(url, key, seconds, refresh, got):
    code, body = _reader_call(TAVILY_URL, {"urls": [url], "format": "markdown"},
                              {"Authorization": "Bearer " + key}, seconds, got)
    if code >= 400:
        return "", None, _service_said(code, body)
    d = _json(body)
    res = (d.get("results") or [{}])[0] or {}
    text = res.get("raw_content") or ""
    if not text.strip():
        fail = (d.get("failed_results") or [{}])[0] or {}
        return "", None, "no text (%s)" % re.sub(r"\s+", " ", str(fail.get("error") or "nothing returned"))[:60]
    return _titled(text, res.get("title")), 200, reader_text_why(text, res.get("title"))


def _defuddle_md(url, key, seconds, refresh, got):
    # the address goes in the path, encoded; a #fragment never reaches a server anyway
    target = urllib.parse.quote(url.split("#")[0], safe=":/?&=%@+,;~!$'()*")
    code, body = _reader_call(DEFUDDLE_MD_URL + target, None, {"Accept": "text/markdown, text/plain;q=0.9"},
                              seconds, got, method="GET")
    if code >= 400:
        return "", None, "the service answered %s" % code
    txt, title = body.decode("utf-8", "replace"), ""
    m = re.match(r"(?s)\A﻿?---\r?\n(.*?)\r?\n---[ \t]*\r?\n", txt)
    if m:                                     # YAML front matter: the title is worth keeping
        t = re.search(r"(?m)^title:\s*(.*?)\s*$", m.group(1))
        title = t.group(1).strip().strip("\"'") if t else ""
        txt = txt[m.end():].lstrip("\n")
    return _titled(txt, title), 200, reader_text_why(txt, title)


def read_into(r, chunks, size=16384):
    """Read a response chunk by chunk into a list another thread can look at: when the step's
    time runs out, what arrived is still there to use. read1() returns what has arrived;
    read(n) would wait for all n bytes and hold a stalled server's 3 000 bytes back."""
    read = getattr(r, "read1", None) or r.read
    while True:
        chunk = read(size)
        if not chunk:
            return
        chunks.append(chunk)


FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"
JINA_URL = "https://r.jina.ai/"
EXA_URL = "https://api.exa.ai/contents"
TAVILY_URL = "https://api.tavily.com/extract"
DEFUDDLE_MD_URL = "https://defuddle.md/"
WAYBACK_URL = "https://web.archive.org"
# Measured on 14 hard pages: Firecrawl opened 11, Exa 10, Jina 8,
# Tavily 7, defuddle.md 4. Exa is third so its credits go to search. A reader
# that needs a key and has none is skipped; Jina works without one (a lower rate limit) and
# defuddle.md needs none, so without keys the chain is Jina, then defuddle.md.
READERS = ("firecrawl", "jina", "exa", "tavily", "defuddle.md")
READER_KEYS = {"firecrawl": "FIRECRAWL_API_KEY", "jina": "JINA_API_KEY", "exa": "EXA_API_KEY",
               "tavily": "TAVILY_API_KEY"}
KEY_NEEDED = ("firecrawl", "exa", "tavily")
STREAMED = ("jina", "defuddle.md")           # plain text: a part that arrived is still text
READER_MIN_LEFT = 2                          # seconds left in the step that are worth a request
READER_CALLS = {"firecrawl": _firecrawl, "jina": _jina, "exa": _exa, "tavily": _tavily,
                "defuddle.md": _defuddle_md}
SITE_API_SECONDS = 10                        # a site's own API, then the ordinary path


class Background:
    """fn(*a) in a thread from now on; result() waits for it (the rescue tiers start
    together on HTTP's signals). fn bounds itself by the read's deadline."""

    def __init__(self, fn, *a):
        self.box = {}
        self.t = threading.Thread(target=self._run, args=(fn, a), daemon=True)
        self.t.start()

    def _run(self, fn, a):
        try:
            self.box["v"] = fn(*a)
        except Exception as e:                                 # noqa: BLE001
            debuglog.exc("background tier", e)
            self.box["e"] = e

    def result(self):
        # fn ends by the deadline less the tail on its own; this wait never runs past the deadline
        self.t.join(max(1.0, budget.cap(120, reserve=0)))
        if "e" in self.box:
            raise self.box["e"]
        if "v" not in self.box:
            raise TimeoutError("no answer before the deadline")
        return self.box["v"]


def bounded(seconds, fn, *a, **k):
    """fn(*a, **k) for at most `seconds`: (result, None), or (None, the exception), or (None, a
    TimeoutError) when it took longer. The call itself keeps running in a daemon thread until its
    own socket gives up; the step does not wait for it."""
    box = {}

    def run_it():
        try:
            box["v"] = fn(*a, **k)
        except Exception as e:                                 # noqa: BLE001
            debuglog.exc("bounded call", e)
            box["e"] = e

    t = threading.Thread(target=run_it, daemon=True)
    t.start()
    t.join(max(0.1, seconds))
    if t.is_alive():
        return None, TimeoutError("no answer in %d s" % max(1, int(seconds)))
    return box.get("v"), box.get("e")


def wayback(url):
    """The newest archived copy: (bytes, content type, engine, timestamp or the reason there is none).

    One step of ARCHIVE_STEP_SECONDS for the CDX lookup and the snapshot together: the CDX API
    itself sometimes takes a minute, and two requests of 20 s each were 40 s. A snapshot that is
    still arriving when the time runs out is kept as it is (engine "archive:wayback:partial")."""
    snap_state = {"chunks": [], "ct": "", "ts": "", "enc": ""}
    secs = budget.cap(ARCHIVE_STEP_SECONDS, budget.tail() * 1.5, floor=1.0)   # its snapshot is extracted after

    def lookup():
        q = ("%s/cdx/search/cdx?url=%s&filter=statuscode:200&limit=-1&fl=timestamp,original"
             % (WAYBACK_URL, urllib.parse.quote(url, safe="")))
        with urllib.request.urlopen(q, timeout=max(1.0, secs)) as r:
            rows = [l.split() for l in r.read().decode("utf-8", "replace").splitlines() if l.strip()]
        if not rows:
            return b"", "", "never archived"
        ts, orig = rows[-1][0], rows[-1][1]
        snap = "%s/web/%sid_/%s" % (WAYBACK_URL, ts, intl.iri_to_uri(orig))
        req = urllib.request.Request(snap, headers={"Accept": ACCEPT, "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=max(1.0, secs)) as r:
            snap_state.update(ct=r.headers.get("content-type", ""), ts=ts, enc=r.headers.get("content-encoding", ""))
            read_into(r, snap_state["chunks"])
        return b"".join(snap_state["chunks"]), snap_state["ct"], ts

    t_a = now()
    got, e = bounded(secs, lookup)
    budget.record("archive", t_a, (budget.ended(ARCHIVE_STEP_SECONDS, secs) if isinstance(e, TimeoutError) else "fail")
                  if e is not None else "ok", own=ARCHIVE_STEP_SECONDS, given=secs,
                  note=str(e)[:80] if e is not None else str(got[2])[:40])
    if e is not None:
        body = b"".join(list(snap_state["chunks"]))
        if body and snap_state["ts"] and len(body) > 2000:
            body, why = unpacked(body, snap_state["enc"])
            if body:
                return body, snap_state["ct"], "archive:wayback:partial", snap_state["ts"]
            return b"", "", "archive:wayback", why
        return b"", "", "archive:wayback", str(e)[:100]
    body, ct, ts = got
    if not body:
        return body, ct, "archive:wayback", ts
    body, why = unpacked(body, snap_state["enc"])
    return (body, ct, "archive:wayback", ts) if body else (b"", "", "archive:wayback", why)


def unpacked(body, enc=""):
    """(the body as plain bytes, why not). Wayback's id_ mode hands an archived page as its site sent
    it - gzipped, as often as not, with or without a Content-Encoding header - and urllib unpacks
    nothing: Crunchbase's copy was decoded as KOI8-R, and 199 KB of mojibake came back as `ok` (stage
    9). gzip and deflate are unpacked, a cut stream as far as it goes; brotli or zstd without their
    modules, or a stream that is not what it says, is no text at all rather than the wrong text."""
    enc = (enc or "").strip().lower()
    gz = body[:2] == b"\x1f\x8b"
    try:
        if gz or enc in ("gzip", "x-gzip"):
            if not gz:
                return body, ""                    # the header said gzip, the bytes are plain
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            return d.decompress(body) + d.flush(), ""
        if enc == "deflate":
            try:
                return zlib.decompress(body), ""
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS), ""
        if enc in ("br", "zstd"):
            mod = None
            for name in (("brotli", "brotlicffi") if enc == "br" else ("zstandard",)):
                try:
                    mod = __import__(name)
                    break
                except ImportError:
                    pass
            if mod is None:
                return b"", "the archived copy is %s-compressed, and this machine cannot unpack it" % enc
            if enc == "br":
                return mod.decompress(body), ""
            return mod.ZstdDecompressor().decompressobj().decompress(body), ""
    except Exception as e:                       # noqa: BLE001 - zlib, brotli, zstandard each have their own
        debuglog.exc("archive: unpack", e)
        return b"", "the archived copy is %s but does not unpack: %s" % (enc or "gzip", str(e)[:60])
    return body, ""


def archived_text(url, c, workdir):
    """The archive's copy through the same type detection as a live answer: a PDF or an
    office file goes to the document readers, only HTML is decoded and extracted.
    Returns (text, engine, page_text, html, timestamp, engine_or_reason)."""
    body, ct, aeng, ats = wayback(url)
    if not body:
        # a copy that would not unpack says so in the chain, as a cut document does below
        return "", "", "", "", "", ("%s (%s)" % (aeng, ats)) if "unpack" in str(ats) else aeng
    kind, _ = detect_kind(body[:512], ct, urllib.parse.urlparse(url).path)
    if kind in ("pdf", "zip") and aeng.endswith(":partial"):
        return "", "", "", "", "", "archive:wayback (the archived document was cut by the time bound)"
    if kind in ("pdf", "zip"):
        sub = zip_subtype(body) if kind == "zip" else "pdf"
        path = os.path.join(workdir, "archive.%s" % (sub if sub != "other" else "zip"))
        write_bytes(path, body)
        text, _note = doc_text(path, kind, c, workdir)
        return text, "document", text, "", ats, aeng
    html, _ = smart_decode(body, ct)
    text, eng, _cands, page = extract(html, url, c, workdir)
    return text, eng, page, html, ats, aeng


# a video's own address, not every page of a video site: vimeo.com/about is a page
VIDEO_URL = re.compile(
    r"(youtube\.com/(watch\?|shorts/|live/|embed/)|youtu\.be/[\w-]{6,}|"
    r"tiktok\.com/@[^/?#]+/video/\d+|vm\.tiktok\.com/\w+|"
    r"vimeo\.com/(\d+|channels/[^/?#]+/\d+|groups/[^/?#]+/videos/\d+)|player\.vimeo\.com/video/\d+|"
    r"(vk\.com|vkvideo\.ru)/(video|clip)-?\d+_\d+|"
    r"rutube\.ru/(video|shorts)/[0-9a-f]{32}|"
    r"dailymotion\.com/video/x\w+|dai\.ly/x\w+|"
    r"twitch\.tv/videos/\d+|clips\.twitch\.tv/[\w-]+|twitch\.tv/[^/?#]+/clip/[\w-]+|"
    r"ok\.ru/video/\d+)", re.I)

PRIVATE_SUFFIX = (".local", ".localhost", ".internal", ".intranet", ".lan", ".corp", ".home",
                  ".localdomain", ".svc", ".cluster.local", ".in-addr.arpa", ".ip6.arpa")
METADATA_HOSTS = ("metadata.google.internal", "metadata.goog", "instance-data",
                  "metadata.azure.com", "fd00:ec2::254")
SHARED_NETS = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("192.0.0.0/24"))
# The reader rule (url_has_secret), measured on 249 public URLs (1.2 % flagged) and 11 known
# secret shapes (all caught): query keys that carry credentials, link-sharing places, opaque runs.
SECRET_KEYS = re.compile(r"^(token|access_token|id_token|auth|auth_token|authorization|api_?key|apikey|key|"
                         r"secret|client_secret|password|passwd|pwd|sig|signature|session|sessionid|sid|"
                         r"x-amz-signature|x-goog-signature|sv|se)$", re.I)
SHARED_PATH = re.compile(r"(?i)/(share|shared|invite|invitation|reset|magic|unsubscribe|confirm|verify|"
                         r"webhooks?|hooks|services)/[^/]{16,}")
LINK_HOSTS = {"docs.google.com": r"^/(document|spreadsheets|presentation|forms)/d/",
              "drive.google.com": r"^/(file/d/|open)", "www.dropbox.com": r"^/(s|scl)/",
              "hooks.slack.com": r"^/", "discord.com": r"^/api/webhooks/"}
_RESOLVED = {}             # host -> (time, why): the network rule asks DNS once a minute per host
# what a *name* may not resolve to: the networks that are really inside. Narrower than the rule
# for an address literal on purpose: a proxy with a fake-IP DNS (Clash, Surge, sing-box) answers
# 198.18.0.0/15 for every name, and Python counts that benchmarking range as private
INTERNAL_NETS = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.168.0.0/16", "::/128", "::1/128", "fc00::/7", "fe80::/10", "fec0::/10"))


def _ip_reason(host):
    """Why an IP literal is not public (empty string when it is)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        return "internal or loopback host"
    for net in SHARED_NETS:
        if ip.version == net.version and ip in net:
            return "internal or loopback host"
    return ""


def _host_forms(host):
    """The host as written, plus the integer forms a browser also accepts (2130706433, 0x7f.0.0.1)."""
    h = (host or "").strip().strip("[]").rstrip(".").lower()
    out = [h]
    parts = h.split(".")
    if 1 <= len(parts) <= 4 and all(re.fullmatch(r"0x[0-9a-f]+|[0-9]+", q) for q in parts):
        try:
            vals = []
            for q in parts:
                if q.startswith("0x"):
                    vals.append(int(q, 16))
                elif len(q) > 1 and q.startswith("0"):
                    vals.append(int(q, 8))
                else:
                    vals.append(int(q, 10))
            n = 0
            for v in vals:
                n = (n << 8) + v
            if 0 <= n <= 2 ** 32 - 1:
                out.append(str(ipaddress.IPv4Address(n)))
        except ValueError:
            pass
    return out


def _resolves_private(host):
    """Why a host name points into the local network by the addresses it resolves to ("" when
    none does, or when it does not resolve: such a request fails on its own). A name Python cannot
    look up at all (a label over 63 characters, an empty one) is refused: the request's own lookup
    is not Python's."""
    hit = _RESOLVED.get(host)
    if hit and now() - hit[0] < 60:
        return hit[1]
    why = ""
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])   # an IPv6 zone is not part of it
            if ip.version == 6 and ip.ipv4_mapped is not None:
                ip = ip.ipv4_mapped
            if any(ip.version == net.version and ip in net for net in INTERNAL_NETS):
                why = "internal or loopback host (%s resolves to %s)" % (host, ip)
                break
    except UnicodeError:
        why = "a host name that cannot be looked up (%s)" % host[:60]
    except (OSError, ValueError):
        why = ""
    _RESOLVED[host] = (now(), why)
    return why


def host_is_private(url):
    """Why the host of this URL is not on the public internet ("" when it is): the network rule.

    It decides what the reader may connect to - redirects, pictures, the browser's requests - and
    that an internal host never goes to a remote reader. Only the host counts: an IP literal in
    any form a browser accepts (2130706433, 0x7f.0.0.1, [::ffff:127.0.0.1]), an internal name
    (localhost, *.local, metadata), or a name that resolves to such an address (localtest.me).
    The host is the one the request goes to (intl.iri_to_uri: escapes decoded, a name outside
    ASCII in punycode); a host that has no such form is refused. The path and the query are the
    reader rule's business (url_has_secret).
    """
    p = urllib.parse.urlparse(intl.iri_to_uri(url or ""))
    host = p.hostname or ""
    if not host:
        return "no host"
    low = host.strip("[]").rstrip(".").lower()
    if ":" not in low and intl.host_ascii(low) != low:
        return "a host name that has no ASCII form (%s)" % host[:60]
    if low and low == os.environ.get("READ_PAGE_TEST_PUBLIC_HOST", "").strip().lower():
        return ""      # tests only: this one address counts as public, so the main channel runs offline
    if low == "localhost" or low in METADATA_HOSTS or low.endswith(PRIVATE_SUFFIX):
        return "internal or loopback host"
    forms = _host_forms(host)
    for form in forms:
        why = _ip_reason(form)
        if why:
            return why
    for form in forms:
        try:
            ipaddress.ip_address(form)
            return ""                                    # a public address literal
        except ValueError:
            pass
    return _resolves_private(low)


def url_has_secret(url):
    """Why this URL may carry a secret ("" when it does not): the reader rule.

    Such a URL is read locally like any other; it only stays away from remote readers unless
    --force-external says it is safe to send. Narrow on purpose: credentials, a query key that
    names a credential, a link-sharing place, an opaque run of 32+ characters. A slug with a
    digit (python3-tips, oauth2-server, Windows_11) is a slug.
    """
    p = urllib.parse.urlsplit(url or "")
    if p.username or p.password:
        return "credentials in the URL"
    for k, _v in urllib.parse.parse_qsl(p.query, keep_blank_values=True):
        if SECRET_KEYS.match(k):
            return "a %s= parameter" % k
    rule = LINK_HOSTS.get((p.hostname or "").lower())
    if rule and re.search(rule, p.path or ""):
        return "an unlisted link"
    if SHARED_PATH.search(p.path or ""):
        return "a sharing or reset link"
    for seg in (p.path or "").split("/"):
        for run in re.findall(r"[A-Za-z0-9]{32,}", seg):
            if re.search(r"\d", run) and re.search(r"[A-Za-z]", run) and _entropy(run) >= 3.0:
                return "an opaque token of %d characters" % len(run)
    return ""


def _entropy(s):
    n = float(len(s))
    return -sum(c / n * math.log2(c / n) for c in (s.count(x) for x in set(s)))


def privacy_note(internal_why, secret_why, allow, force):
    """The one line `privacy.why` says about remote readers for this URL."""
    if internal_why:
        if allow or force:
            return ("%s refused: an internal host (%s) never goes to a remote reader, which could "
                    "not open it anyway" % ("--force-external" if force else "--allow-external", internal_why))
        return "internal host (%s): remote readers are never used" % internal_why
    if secret_why:
        if force:
            return "sent by --force-external although the URL may carry a secret (%s)" % secret_why
        if allow:
            return ("--allow-external ignored: the URL may carry a secret (%s); --force-external "
                    "sends it anyway" % secret_why)
        return "sensitive: the URL may carry a secret (%s); remote readers are not used" % secret_why
    if force:
        return "allowed by --force-external"
    return "allowed by --allow-external" if allow else "sensitive: third-party readers are not used"


def hop_refused(origin, target):
    """Why a request that `origin` leads to may not go to `target` ("" when it may): a redirect,
    a picture, a meta refresh or a browser request. Only http(s) ever, on every hop; and a
    public page never reaches into the local network. A private page may stay private."""
    scheme = (urllib.parse.urlparse(target or "").scheme or "").lower()
    if scheme not in ("http", "https"):
        return "a %s URL is not a web address" % ((scheme + ":") if scheme else "schemeless")
    why = host_is_private(target)
    if why and not host_is_private(origin):
        return why
    return ""


def browser_policy(host, port):
    """netguard's rule for a public page's browser, once per connection: (why not, the addresses to
    connect to). hop_refused's rule, decided on the very addresses the browser will use: an
    internal name or address literal is refused; a name is resolved once, refused when any of its
    addresses is inside (INTERNAL_NETS, as for a redirect), and the connection goes to exactly
    those addresses - no second lookup a rebinding DNS could answer differently. An empty list
    with no reason means the name did not resolve."""
    low = (host or "").strip().strip("[]").rstrip(".").lower()
    if not low:
        return "no host", []
    if ":" not in low and intl.host_ascii(low) != low:
        # Chrome hands over the ASCII name it asks for; anything else is converted as a request
        # would be, and a name that has no ASCII form is refused
        low = (intl.host_ascii(low) or "").rstrip(".")
        if not low:
            return "a host name that has no ASCII form (%s)" % (host or "")[:60], []
    test_public = os.environ.get("READ_PAGE_TEST_PUBLIC_HOST", "").strip().lower()
    if low == test_public:
        return "", [low]          # tests only: this one address counts as public
    if low == "localhost" or low in METADATA_HOSTS or low.endswith(PRIVATE_SUFFIX):
        return "internal or loopback host", []
    forms = _host_forms(low)
    for form in forms:
        why = _ip_reason(form)
        if why:
            return why, []
    for form in forms:
        try:
            ipaddress.ip_address(form)
            return "", [form]                              # a public address literal
        except ValueError:
            pass
    blocklist = _test_blocklist()                          # READ_PAGE_TEST_BLOCKLIST, a measurement only
    if blocklist and netguard.listed(low, *blocklist):
        return "on the test block list", []
    fixed = _test_hosts().get(low)                         # READ_PAGE_TEST_HOSTS, tests only
    try:
        addrs = [fixed] if fixed else netguard.resolve(low, port)
    except (OSError, UnicodeError):
        return "", []
    for a in addrs:
        if test_public and a == test_public:
            continue                                       # tests only, as above
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            return "an address that is no address (%s)" % a[:60], []
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if any(ip.version == net.version and ip in net for net in INTERNAL_NETS):
            return "internal or loopback host (%s resolves to %s)" % (low, ip), []
    return "", addrs


_BLOCKLIST = {}


def _test_blocklist():
    """READ_PAGE_TEST_BLOCKLIST=path: a host list (an ad-block DNS filter, a hosts file) whose names
    the browser's guard refuses before any lookup, to measure what blocking ads and trackers would
    change on a machine that blocks nothing (one that already blocks ads at DNS shows no difference). For
    measurements only, until they say the browser should have such a list."""
    path = (os.environ.get("READ_PAGE_TEST_BLOCKLIST") or "").strip()
    if not path:
        return None
    if path not in _BLOCKLIST:
        try:
            _BLOCKLIST[path] = netguard.load_list(path)
        except OSError as e:
            debuglog.exc("test block list", e)
            _BLOCKLIST[path] = None
    return _BLOCKLIST[path]


def _test_hosts():
    """READ_PAGE_TEST_HOSTS=name=address,...: names the browser's guard resolves to a fixed
    address, so a test can show a public-looking name that points inside. Tests only."""
    out = {}
    for item in (os.environ.get("READ_PAGE_TEST_HOSTS") or "").split(","):
        name, _, addr = item.partition("=")
        if name.strip() and addr.strip():
            out[name.strip().lower()] = addr.strip()
    return out


def system_proxy():
    """Why this machine's browser goes through a proxy of its own ("" when it does not): the
    environment's, Windows' or macOS' settings, or a proxy auto-config script. Then our guard
    steps aside - the browser keeps the way out it has - and the request rule guards it."""
    try:
        found = {k for k, v in urllib.request.getproxies().items() if v and k in ("http", "https", "all")}
    except Exception:                                                  # noqa: BLE001
        found = set()
    if found:
        return "a proxy is set for %s" % ", ".join(sorted(found))
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
                pac = winreg.QueryValueEx(k, "AutoConfigURL")[0]
            if pac:
                return "a proxy auto-config script is set"
        except OSError:
            pass
    return ""


def origin_of(url):
    """`scheme://host[:port]/`: the Referer a browser sends to another site by default."""
    p = urllib.parse.urlparse(url or "")
    return "%s://%s/" % (p.scheme, p.netloc.rsplit("@", 1)[-1]) if p.scheme and p.netloc else ""


def detect_kind(body, ct, path):
    """Returns (kind, conflict). Magic wins, then Content-Type, then the extension."""
    m = magic(body)
    low = (ct or "").lower()
    by_ct = "pdf" if "pdf" in low else "rtf" if "rtf" in low else \
        "zip" if re.search(r"(officedocument|opendocument|epub|zip)", low) else ""
    by_ext = ""
    for ext in (".pdf", ".docx", ".pptx", ".xlsx", ".epub", ".odt", ".ods", ".odp", ".rtf"):
        if (path or "").lower().endswith(ext):
            by_ext = "pdf" if ext == ".pdf" else "rtf" if ext == ".rtf" else "zip"
    kind = m or by_ct or by_ext
    if kind in ("pdf", "zip") and body[:512].lstrip()[:1] == b"<":
        return "html", True                          # a binary type in the header, an error page in the body
    return kind, bool(m and by_ct and m != by_ct)


def _cue_seconds(stamp):
    """00:01:02.500 -> 62.5"""
    parts = stamp.strip().replace(",", ".").split(":")
    try:
        nums = [float(x) for x in parts]
    except ValueError:
        return 0.0
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def vtt_to_text(vtt, block_seconds=30):
    """Cues -> readable text with a timestamp per block.

    A cue every two seconds is noise in a prompt, and dropping the timestamps entirely made a
    transcript impossible to cite ("at 12:40 he says..."). So cues are grouped: a new block starts
    when the cue gap is longer than 2 s or the block already covers `block_seconds`.

    YouTube's automatic captions roll - each cue holds the line before and the new one - and are read line by line
    (`subtitles.rolled_cues`): every line once, a line said twice twice, and the gap is the time since the line before
    was last spoken, the cues of such a track having none.
    """
    rolled = subtitles.rolled_cues(vtt)
    cues = [(start, text, since) for start, _end, text, since in rolled] if rolled is not None else []
    lines = [] if rolled is not None else (vtt or "").splitlines()
    for i, line in enumerate(lines):
        if "-->" not in line:
            continue
        try:
            start = line.split("-->")[0].strip()
        except IndexError:
            continue
        text = []
        for nxt in lines[i + 1:]:
            if "-->" in nxt or re.match(r"^(WEBVTT|Kind:|Language:|NOTE|\d+\s*$)", nxt):
                break
            clean = re.sub(r"<[^>]+>", "", nxt).strip()
            if clean:
                text.append(clean)
        if text:
            cues.append((_cue_seconds(start), " ".join(text), None))
    out, block, block_start, last = [], [], None, None
    for sec, text, since in cues:
        if block_start is None:
            block_start = sec
        ref = last if since is None else since
        gap = (sec - ref) if ref is not None else 0.0
        if block and (gap > 2.0 or sec - block_start >= block_seconds):
            out.append((block_start, block))
            block, block_start = [], sec
        if rolled is not None or not block or block[-1] != text:
            block.append(text)
        last = sec
    if block:
        out.append((block_start, block))
    rendered = []
    for sec, words in out:
        stamp = "%d:%02d" % (int(sec) // 60, int(sec) % 60)
        if sec >= 3600:
            stamp = "%d:%02d:%02d" % (int(sec) // 3600, (int(sec) % 3600) // 60, int(sec) % 60)
        rendered.append("[%s] %s" % (stamp, " ".join(words)))
    return "\n\n".join(rendered)


SUB_FORMATS = "vtt/srt/best"      # a site without VTT gives SRT (RuTube), else the best it has: subtitles.py reads them
SUB_LIMIT = 16 * 1024 * 1024      # characters of a subtitle file read: a ten-hour video's track is a few MB
_VIDEO = {"kind": "", "advice": "", "fix": ""}     # what video_text() learned about a failure, for the answer's advice


def video_text(url, c, workdir):
    """Subtitle transcript via yt-dlp (works for YouTube, TikTok, VK, Vimeo, RuTube, ...): (text, title, note) -
    the note says why there is no text, or which track the text is (`en`, `fr, automatic`, `zh-Hans,
    machine-translated from en`). The user's languages are asked for, and the track the video speaks in
    (`<lang>-orig`, YouTube's speech recognition): YouTube offers a machine translation into every language,
    which is read only when the video has nothing else (pick_subtitle). A human track in the language the speaker
    uses is asked for once more when the first call brought only a machine's (own_tracks)."""
    _VIDEO.update(kind="", advice="", fix="")
    yt = c["cli"].get("yt-dlp")
    if not yt:
        return "", "", "yt-dlp is not installed"
    asked = intl.sub_langs()
    langs = ",".join(asked)
    sub_arg = langs if os.environ.get("READ_PAGE_SUB_LANGS") else langs + ",.*-orig"
    extra = []
    jar = cookies_for_url(url)
    if jar:                                   # age-gated and members-only videos need the session
        ck = os.path.join(workdir, "cookies.txt")
        try:
            write_netscape(ck, jar, host_of(url))
            extra = ["--cookies", ck]
            _COOKIE_STATS["sent"] += 1
        except OSError:
            extra = []
    video_secs = budget.cap(VIDEO_TIMEOUT, floor=1.0)
    t_yt = now()
    node, ours = which("node"), os.environ.get("READ_PAGE_ENV") or ""
    if node and ours and os.path.normcase(yt).startswith(os.path.normcase(ours)):
        # YouTube's player challenges need a JavaScript runtime, and yt-dlp looks only for deno by
        # itself: the environment's yt-dlp (always a recent one: an old one does not know the flag)
        # is told its Node; the solver came with yt-dlp[default]
        extra = ["--js-runtimes", "node:" + node] + extra
    if ours and os.path.normcase(yt).startswith(os.path.normcase(ours)):
        # its own cache (the player's solved challenges) in the one folder, not in ~/.cache/yt-dlp
        extra = ["--cache-dir", os.path.join(ours, "cache", "yt-dlp")] + extra
    # --ignore-errors: a track that cannot be fetched is a warning, not the end of the call. YouTube answers 429 to
    # a machine translation (the user's `en` for a Russian talk is one), and yt-dlp then stopped with nothing
    # written - no track of the others, no info file: a Russian talk read by an English user was "no subtitles"
    rc, so, se = run([yt, "--skip-download", "--ignore-errors", "--write-subs", "--write-auto-subs",
                      "--sub-langs", sub_arg, "--sub-format", SUB_FORMATS, "--write-info-json"]
                     + extra + ["-o", os.path.join(workdir, "video.%(ext)s"), url],
                     timeout=video_secs)
    files = os.listdir(workdir)
    info = read_info(workdir, files)
    kinds = subtitle_kinds(info)
    spoken = spoken_language(info)
    sub = pick_subtitle(files, asked, kinds, spoken)
    kind = kinds.get(subtitles.track_of(sub)[0], "")
    if info and rc != -1 and kind != "human" and not os.environ.get("READ_PAGE_SUB_LANGS"):
        # no track of the user's and none in English, only a machine translation or a dub's speech, or only
        # speech recognition while the speaker's own language has a human track: the video's own language,
        # when its info names one
        own = own_tracks(info, kinds, asked, track_langs(files), human_only=bool(sub) and kind in ("", "auto"))
        left = video_secs - (now() - t_yt)
        if own and left > 3:
            rc2, so2, se2 = run([yt, "--skip-download", "--ignore-errors", "--write-subs", "--write-auto-subs",
                                 "--sub-langs", own, "--sub-format", SUB_FORMATS] + extra
                                + ["-o", os.path.join(workdir, "video.%(ext)s"), url], timeout=max(1.0, left))
            se = (se or b"") + b"\n" + (se2 or b"")
            files = os.listdir(workdir)
            got = pick_subtitle(files, own.split(",") + asked, kinds, spoken)
            if got and got != sub:
                sub = got
            langs = "%s, then %s" % (langs, own)
    budget.record("yt-dlp", t_yt, budget.ended(VIDEO_TIMEOUT, video_secs) if rc == -1 else "ok" if sub else "fail",
                  own=VIDEO_TIMEOUT, given=video_secs, note="subtitles" if sub else "no subtitles")
    title = (info.get("title") or "") + (" — " + info["uploader"] if info.get("uploader") else "") if info else ""
    if not sub:
        if rc == -1:
            # killed by the time bound before any subtitle file was written: that is not "this
            # video has no subtitles", and saying so would send the caller the wrong way
            _VIDEO.update(kind="timeout", fix="read it again, with --refresh",
                          advice="yt-dlp did not finish in %d s, so this video's subtitles are not known: read it "
                                 "again, with --refresh" % video_secs)
            return "", title, "yt-dlp did not finish in %d s; no subtitles arrived yet" % video_secs
        why, msg = ytdlp_why(se)
        if why == "upcoming":
            # YouTube answers a video that has not started yet with an error and no track at all
            _VIDEO.update(kind=why, fix="read it again after it has started, with --refresh",
                          advice="the video has not started yet (%s): it has no subtitles until it has aired; read "
                                 "it again after that, with --refresh" % msg)
            return "", title, "the video has not started yet (%s)" % msg
        if why == "limit":
            _VIDEO.update(kind=why, fix="try again in a few minutes, with --refresh",
                          advice="the site refused the request for subtitles (%s): try again in a few minutes, with "
                                 "--refresh" % msg)
            return "", title, "the site refused the request for subtitles (%s)" % msg
        if why == "error":
            _VIDEO.update(kind=why, advice="yt-dlp stopped with: %s; this video's subtitles are not known" % msg)
            return "", title, "yt-dlp stopped with: %s" % msg
        return "", title, "no subtitles in %s (set READ_PAGE_SUB_LANGS to change)" % langs
    lang, ext = subtitles.track_of(sub)
    with open(os.path.join(workdir, sub), encoding="utf-8-sig", errors="replace") as fh:
        raw = fh.read(SUB_LIMIT)                 # a site's file, whatever its size: the read holds this much at most
    vtt = subtitles.to_vtt(raw, ext)
    rolled = subtitles.unrolled(vtt)             # YouTube's rolling captions, each line once; "" for any other track
    try:
        if rolled:
            with open(os.path.join(workdir, "transcript.vtt"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(rolled)
        elif ext == "vtt":
            shutil.copyfile(os.path.join(workdir, sub), os.path.join(workdir, "transcript.vtt"))
        elif vtt:
            with open(os.path.join(workdir, "transcript.vtt"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(vtt)
    except OSError:
        pass
    text = vtt_to_text(vtt)
    return text, title, track_note(lang, kinds) if text else "subtitles were empty"


def ytdlp_why(se):
    """What yt-dlp's last error line says: (kind, message). kind: "upcoming" (a premiere or a live event that has
    not started: no stream and no track exist yet), "limit" (the site refused for too many requests: an error, or the
    warning of a track it would not give), "error" (anything else it said), "" when it said nothing of the kind."""
    text = (se or b"").decode("utf-8", "replace").splitlines()
    lines = [x.strip() for x in text if x.strip().startswith(("ERROR:", "yt-dlp: error:"))]
    if not lines:
        lines = [x.strip() for x in text if x.strip().startswith("WARNING: Unable to download video subtitles")
                 and re.search(r"\b429\b|(?i:too many requests)", x)]
    if not lines:
        return "", ""
    msg = re.sub(r"^(?:ERROR:|WARNING:|yt-dlp: error:)\s*(?:\[[^\]]*\]\s*)?(?:[^\s:]+:\s+)?", "", lines[-1])
    msg = re.sub(r"\s+", " ", msg).strip()[:200]
    if re.search(r"(?i)premieres? (?:in|on|will)\b|will begin\b|is_upcoming", msg):
        return "upcoming", msg
    if re.search(r"(?i)\b429\b|too many requests", msg):
        return "limit", msg
    return "error", msg


def read_info(workdir, files):
    """yt-dlp's info file for the video as a dict; {} without it, or one that does not read."""
    name = next((f for f in files if f.endswith(".info.json")), "")
    try:
        with open(os.path.join(workdir, name), encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def track_langs(files):
    """The languages of the subtitle files in the folder."""
    return set(subtitles.track_of(f)[0] for f in files if subtitles.track_of(f)[0])


def _base_lang(tag):
    return (tag or "").split("-")[0].lower()


def spoken_language(d):
    """The language the speaker uses, from yt-dlp's info. A dubbed video offers audio in several languages, one marked
    original, and `language` names the default track, which can be a dub's (`en` for a Chinese news video whose
    original is `zh-Hant`): the original's language wins, else `language`."""
    for f in d.get("formats") or []:
        if isinstance(f, dict) and f.get("language") and "original" in str(f.get("format_note") or "").lower():
            return str(f["language"])
    return str(d.get("language") or "")


def is_dubbed(d):
    """True when the video's audio comes in more than one language: some of it is a dub."""
    return len(set(_base_lang(f["language"]) for f in d.get("formats") or []
                   if isinstance(f, dict) and f.get("language"))) > 1


_AUTO_NAME = re.compile(r"(?i)\b(?:auto|авто)\b|automatic|автоматич|自动|自動")
# what yt-dlp lists among a video's subtitles that is no subtitles: YouTube's live chat replay, Bilibili's comments
NOT_SUBTITLES = ("live_chat", "danmaku")


def subtitle_kinds(d):
    """{language: kind} of the tracks yt-dlp's info lists: "human" (the video's own subtitles), "auto" (speech
    recognition in the language spoken), "dub <language>" (speech recognition of a dub: the audio the track was made
    from is not the speaker's `<language>`), "translated from <lang>" (YouTube's machine translation: its address
    asks for `tlang=`). {} without the info. A site's own subtitles that are named automatic (RuTube: `Русский • Авто`)
    are speech recognition too."""
    out = {}
    if not isinstance(d, dict):
        return out
    spoken, dubbed = spoken_language(d), is_dubbed(d)
    autos = d.get("automatic_captions") if isinstance(d.get("automatic_captions"), dict) else {}
    for lang, fmts in autos.items():
        urls = [str(x.get("url") or "") for x in (fmts if isinstance(fmts, list) else []) if isinstance(x, dict)]
        tr = next((u for u in urls if re.search(r"[?&]tlang=", u)), "")
        if tr:
            src = (re.search(r"[?&]lang=([^&#]+)", tr) or [None, d.get("language") or ""])[1]
            out[str(lang)] = "translated" + (" from " + urllib.parse.unquote(src) if src else "")
            continue
        m = re.search(r"[?&]lang=([^&#]+)", next((u for u in urls if u), ""))
        src = urllib.parse.unquote(m.group(1)) if m else (str(lang)[:-5] if str(lang).endswith("-orig") else str(lang))
        out[str(lang)] = "dub " + spoken if dubbed and spoken and _base_lang(src) != _base_lang(spoken) else "auto"
    subs = d.get("subtitles") if isinstance(d.get("subtitles"), dict) else {}
    for lang, fmts in subs.items():
        if lang in NOT_SUBTITLES:
            continue
        names = [str(x.get("name") or "") for x in (fmts if isinstance(fmts, list) else []) if isinstance(x, dict)]
        # yt-dlp takes a language's own subtitles over its automatic ones
        out[str(lang)] = "auto" if names and all(_AUTO_NAME.search(n) for n in names) else "human"
    return out


def track_note(lang, kinds):
    """How the answer names the track it read: `en`, `fr, automatic`, `en, automatic, of a dub (original audio
    zh-Hant)`, `zh-Hans, machine-translated from en`."""
    kind = (kinds or {}).get(lang, "")
    name = lang[:-5] if lang.endswith("-orig") else lang
    if kind == "auto":
        return "subtitles %s, automatic" % name
    if kind.startswith("dub"):
        return "subtitles %s, automatic, of a dub (original audio %s)" % (name, kind[4:])
    if kind.startswith("translated"):
        return "subtitles %s, machine-translated%s" % (lang, kind[len("translated"):])
    return "subtitles %s" % lang


def pick_subtitle(files, langs, kinds=None, spoken=""):
    """The subtitle file to read of those yt-dlp wrote (`video.<lang>.<ext>`, subtitles.EXTS): a human track, in the
    order of `langs`; else the words as spoken - speech recognition in one of `langs`, then the video's own
    (`-orig`), the speaker's language first; else the speech recognition of a dub; a machine translation only when
    there is nothing else (YouTube makes one into every language: the user's first language was taken, an English
    talk read in YouTube's Chinese). A language with several files is read in the best format. With no kinds known,
    by `langs` alone."""
    best = {}
    for f in sorted(files):
        lang, ext = subtitles.track_of(f)
        if lang and (lang not in best or subtitles.EXTS.index(ext) < subtitles.EXTS.index(subtitles.track_of(best[lang])[1])):
            best[lang] = f
    want = [x.lower() for x in langs]
    kinds = dict((str(k).lower(), v) for k, v in (kinds or {}).items())

    def order(lang):
        low = lang.lower()
        kind = kinds.get(low, "")
        tier = 0 if kind == "human" else 2 if kind.startswith("dub") else 3 if kind.startswith("translated") else 1
        pos = want.index(low) if low in want else len(want) + (0 if low.endswith("-orig") else 1)
        theirs = 0 if spoken and _base_lang(low[:-5] if low.endswith("-orig") else low) == _base_lang(spoken) else 1
        return tier, pos, theirs, lang
    return best[min(best, key=order)] if best else ""


def track_for(keys, spoken):
    """Which of `keys`, the names of a video's tracks, is the language `spoken`: the name itself, a name that language
    goes by on a video site (`zh-Hant` -> `zh-TW`, `en-US` -> `en`), else a regional or script variant of it
    (`en-GB`, `pt-BR`). Not one of several named tracks of a language (`en-uYU-mmqFLq8`: a broadcaster's CC1,
    DTVCC1 - each a long live-caption track, 15 s to fetch, no way to tell which)."""
    keys = [str(k) for k in keys]
    if not spoken:
        return ""
    for n in [spoken] + intl.track_names(spoken):
        if n in keys:
            return n
    return next((k for k in keys if _base_lang(k) == _base_lang(spoken)
                 and re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,4})?", k)), "")


def own_tracks(d, kinds, asked, have=(), human_only=False):
    """The subtitle tracks named for the video itself in yt-dlp's info - the human track in the language the speaker
    uses, the track in that language, the first human track, speech recognition in the original language - that
    the user's list did not ask for and the folder does not have yet; "" when there are none. A Chinese video said
    `no subtitles in en,ru`. `human_only`: just the human track in the speaker's language (the first call brought
    speech recognition, and a human track is better than a machine's). Never a machine translation or a dub's."""
    subs = d.get("subtitles") if isinstance(d.get("subtitles"), dict) else {}
    autos = d.get("automatic_captions") if isinstance(d.get("automatic_captions"), dict) else {}
    spoken = spoken_language(d)
    cands = [track_for([k for k in subs if kinds.get(str(k)) == "human"], spoken)]
    if not human_only:
        cands += [spoken if kinds.get(spoken) in ("human", "auto") else ""]
        cands += [k for k in subs if str(k) in kinds][:1]           # the first of the video's own subtitles
        cands += [k for k in autos if str(k).endswith("-orig") and kinds.get(str(k)) == "auto"][:1]
    found = []
    for k in cands:
        if k and isinstance(k, str) and k not in asked and k not in have and k not in found and (k in subs or k in autos):
            found.append(k)
    return ",".join(found[:2])


def youtube_id(url):
    """The 11-character id of a YouTube watch, short, embed, live or youtu.be address, or ""."""
    m = re.search(r"(?i)(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{11})", url or "")
    return m.group(1) if m else ""


def transcript_video(url, workdir):
    """Without markitdown: YouTube's own caption track through youtube-transcript-api - the
    library markitdown's YouTube reader used - when yt-dlp gave none: (text, why), the text in
    yt-dlp's form (timestamped blocks), transcript.vtt beside it. READ_PAGE_SUB_LANGS first, else
    whatever track the video has."""
    vid = youtube_id(url)
    if not vid:
        return "", ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:                                         # noqa: BLE001  (not installed)
        return "", ""
    langs = intl.sub_langs()
    box = {}

    def fetch():
        try:
            api = YouTubeTranscriptApi()
            try:
                got = api.fetch(vid, languages=langs)
            except Exception:                                 # noqa: BLE001  (no track in those languages)
                got = next(iter(api.list(vid))).fetch()
            box["cues"] = [(float(s.start), float(s.duration), s.text) for s in got]
        except Exception as e:                                # noqa: BLE001
            box["why"] = "%s: %s" % (type(e).__name__, str(e).strip().splitlines()[0][:120] if str(e).strip() else "")
    t0, secs = now(), budget.cap(VIDEO_TIMEOUT, floor=1.0)
    th = threading.Thread(target=fetch, daemon=True)
    th.start()
    th.join(secs)
    cues = box.get("cues") or []
    budget.record("transcript-api", t0, "ok" if cues else budget.ended(VIDEO_TIMEOUT, secs) if th.is_alive()
                  else "fail", own=VIDEO_TIMEOUT, given=secs, note="%d cues" % len(cues))
    if not cues:
        return "", box.get("why") or ("no answer in %d s" % secs if th.is_alive() else "no transcript")

    def stamp(t):
        return "%02d:%02d:%06.3f" % (int(t) // 3600, (int(t) % 3600) // 60, t % 60)
    vtt = "WEBVTT\n\n" + "\n\n".join("%s --> %s\n%s" % (stamp(a), stamp(a + max(0.01, d)), (t or "").replace("\n", " "))
                                     for a, d, t in cues if (t or "").strip())
    try:
        with open(os.path.join(workdir, "transcript.vtt"), "w", encoding="utf-8") as fh:
            fh.write(vtt + "\n")
    except OSError:
        pass
    return vtt_to_text(vtt), ""


def markitdown_video(url, c):
    """markitdown's YouTube reader, when yt-dlp gave no transcript: (markdown, why). Only a
    YouTube address, and only a transcript counts - the title and description alone are what the
    page itself gives."""
    exe = c["cli"].get("markitdown")
    if not exe or not re.search(r"(?i)(youtube\.com|youtu\.be)/", url):
        return "", ""
    t_md, secs = now(), budget.cap(VIDEO_TIMEOUT, floor=1.0)
    rc, so, se = run_tool([exe, url], timeout=secs)
    md = so.decode("utf-8", "replace") if rc == 0 else ""
    budget.record("markitdown-video", t_md, budget.ended(VIDEO_TIMEOUT, secs) if rc == -1 else
                  "ok" if rc == 0 else "fail", own=VIDEO_TIMEOUT, given=secs,
                  note="transcript" if re.search(r"(?m)^#+ *Transcript", md) else "no transcript")
    if re.search(r"(?m)^#+ *Transcript", md):
        return md.strip(), ""
    return "", "markitdown found no transcript" if rc == 0 else "markitdown failed"


def gaps(c, ctx):
    """missing = a capability this page needed and the machine lacks; improve = works, but worse.

    Hints that belong to *this* page go first: a scan without OCR used to lose its `ocr` hint to
    three generic "install curl_cffi" lines, because the list was truncated at three.
    """
    libs, cli = c["libs"], c["cli"]
    fix = ownenv.fix                 # `readpage.py --setup` where it installs the engine here
    spec_m, spec_i, gen_m, gen_i = [], [], [], []
    if not (libs.get("curl_cffi") or cli.get("curl")):
        gen_m.append({"what": "http-client", "fix": fix("curl_cffi", "pip install curl_cffi"),
                      "gain": "fetch at all (urllib only)"})
    elif not libs.get("curl_cffi"):
        gen_i.append({"what": "http-client", "fix": fix("curl_cffi", "pip install curl_cffi"),
                      "gain": "passes TLS walls (npm, Medium, Reddit); 3x faster"})
    if not (cli.get("defuddle") or libs.get("trafilatura") or libs.get("html2text")):
        gen_m.append({"what": "extractor", "fix": fix("defuddle", "npm install -g defuddle"),
                      "gain": "page text instead of a tag strip"})
    elif not cli.get("defuddle"):
        gen_i.append({"what": "extractor", "recommended": True, "fix": fix("defuddle", "npm install -g defuddle"),
                      "gain": "1.5-3x more text on docs pages (4807 vs 1659 chars)"})
    if ctx.get("need_browser") and (ctx.get("browser_disabled") or not c.get("browsers")):
        spec_m.append({"what": "browser", "fix": fix("browser", "install Chrome or Edge, then pip install patchright"),
                       "gain": "JavaScript pages and hash routes (this page needs it)"})
    # kind_doc: a PDF, which pymupdf, pdftotext or a machine's markitdown read. An EPUB, ODT or RTF is
    # our readers' (the standard library), an archive that is cut or no ZIP no engine's: nothing to install
    # (the gap was named for any archive, and pymupdf reads none of them here)
    if ctx.get("kind_doc") and not (libs.get("pymupdf") or cli.get("markitdown") or cli.get("pdftotext")):
        spec_m.append({"what": "documents", "fix": fix("pymupdf", "pip install pymupdf"),
                       "gain": "reading this file type"})
    elif ctx.get("office_lib") and not (cli.get("markitdown") or cli.get("pandoc")):
        # a DOCX, XLSX or PPTX whose library did not import here (python-docx, openpyxl, python-pptx),
        # on a machine with neither of the last resorts
        spec_m.append({"what": "documents", "fix": fix(ctx["office_lib"], "pip install " + ctx["office_lib"]),
                       "gain": "reading this file type (%s)" % ctx["office_lib"]})
    if ctx.get("no_text_layer") and c.get("ocr_error") and not (cli.get("tesseract") or libs.get("tesserocr")):
        # OCR is installed and cannot start: a gap of this scan, said as one - not an `empty` with no word of it
        spec_m.append({"what": "ocr", "fix": ownenv.ocr_fix(c["ocr_error"]) or fix("tesseract", "reinstall tesseract"),
                       "gain": "OCR is installed but " + c["ocr_error"]})
    elif ctx.get("no_text_layer") and not (cli.get("tesseract") or libs.get("tesserocr")):
        spec_i.append({"what": "ocr", "fix": fix("tesseract", "tesseract (or a vision model)"),
                       "gain": "text from scanned pages; a vision model can read the rendered page instead"})
    if ctx.get("ocr_missing"):
        spec_i.insert(0, {"what": "ocr-language",
                          "fix": ocr_pack_fix(ctx["ocr_missing"]),
                          "gain": "tesseract has %s; a page in another language reads as garbage"
                                  % ("+".join([x for x in (c.get("ocr_langs") or [])
                                               if x != "osd"] or ["no pack"]))})
    if ctx.get("pdf_tables") and not (libs.get("pymupdf4llm") and libs.get("onnxruntime") is not False):
        # the layout model is pymupdf4llm's with onnxruntime: without it pymupdf4llm still imports
        spec_i.append({"what": "tables", "fix": fix("pymupdf4llm", "pip install pymupdf4llm" if not libs.get(
                           "pymupdf4llm") else "pip install onnxruntime"),
                       "gain": "a PDF's tables as tables (%d page%s here look%s like one, read a cell a line)"
                               % (ctx["pdf_tables"], "" if ctx["pdf_tables"] == 1 else "s",
                                  "s" if ctx["pdf_tables"] == 1 else "")})
    if ctx.get("blocked") and not any(c["keys"].get(READER_KEYS[n]) for n in KEY_NEEDED):
        spec_i.append({"what": "blocked-pages", "fix": "FIRECRAWL_API_KEY",
                       "gain": "pages no local engine can read (Stack Overflow class)"})
    if ctx.get("video") and not cli.get("yt-dlp"):
        spec_m.append({"what": "video", "fix": fix("yt-dlp", "pip install yt-dlp"), "gain": "subtitle transcript"})
    return (spec_m + gen_m)[:3], (spec_i + gen_i)[:3]




# ---------------------------------------------------------------- media, login, google

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".ico", ".svg"}
AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}
VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}


def looks_html(body):
    head = (body or b"")[:1024].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or (
        head.startswith(b"<") and b"<body" in (body or b"")[:4096].lower())


def magic_media(body):
    b = body or b""
    if b[:8] == b"\x89PNG\r\n\x1a\n" or b[:3] == b"\xff\xd8\xff":
        return "image"
    if b[:6] in (b"GIF87a", b"GIF89a") or (b[:4] == b"RIFF" and b[8:12] == b"WEBP"):
        return "image"
    if b[:2] == b"BM" or b[:4] in (b"II*\x00", b"MM\x00*"):
        return "image"
    if b[:4] == b"RIFF" and b[8:12] == b"WAVE":
        return "audio"
    if b[:3] == b"ID3" or b[:4] == b"fLaC" or b[:4] == b"OggS" or b[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return "audio"
    if b[4:8] == b"ftyp" or b[:4] == b"\x1aE\xdf\xa3":
        return "video"
    return ""


def media_kind(body, ct, path):
    if looks_html(body):
        return ""
    m = magic_media(body)
    if m:
        return m
    low = (ct or "").lower()
    for k in ("image", "audio", "video"):
        if low.startswith(k + "/"):
            return k
    ext = os.path.splitext(path or "")[1].lower()
    if ext in IMG_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    return ""


def media_note(path, kind, size, ct):
    """content.md for a URL that is a file: one honest line, no invented content. The path as the user's locale
    names it (a folder named in GBK under that locale: its bytes are no UTF-8, and the note was not written)."""
    path = ownenv.shown(path)
    return ("This URL is a file, not a page: %s (%s, %s%s).\n"
            "The file itself: %s\n"
            "Read it from that path; there is no page text to quote.\n"
            % (os.path.basename(path), human_bytes(size), kind,
               ", " + ct.split(";")[0] if ct else "", path))


def save_media(f, workdir, kind):
    ct = (f["ct"] or "").split(";")[0].strip().lower()
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
           "image/svg+xml": ".svg", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
           "image/avif": ".avif", "image/bmp": ".bmp",
           "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/wav": ".wav",
           "video/mp4": ".mp4", "video/webm": ".webm"}.get(ct, "")
    if not ext and kind == "image":
        # the address's own ending, else ".png": an SVG or an icon was saved as raw.png
        # (an agent's offline copy of gov.uk)
        ext = pictures.ext_of(f.get("final") or f.get("url") or "", ct)
    if not ext:
        ext = {"image": ".png", "audio": ".mp3", "video": ".mp4"}[kind]
    # the server's own name wins when it sends one: "report.pdf", not "raw.pdf"
    name = disposition_name(f.get("disposition") or "")
    given = os.path.splitext(os.path.basename(name))[1].lower()
    if re.match(r"^\.[A-Za-z0-9]{1,6}$", given):
        ext = given
    stem = intl.file_stem(os.path.splitext(os.path.basename(name))[0])
    if not stem:
        return take_body(f, os.path.join(workdir, "raw" + ext))
    return take_body(f, os.path.join(workdir, server_file_name(workdir, stem, ext)))


SERVICE_NAMES = ("content.md", "page.md", "manifest.json", "cookies.jar", "transcript.vtt",
                 "stderr.log", "outline.tsv", "img", "shots", "parts")


def server_file_name(workdir, stem, ext):
    """A name a server chose (Content-Disposition) never replaces anything: not our own files,
    not what the user keeps in --dir. Only our previous download of the same URL may be
    replaced; anything else gets -2, -3 ..."""
    ours = set()
    for v in (load_manifest(workdir).get("files") or {}).values():
        if isinstance(v, str):
            ours.add(os.path.basename(v).lower())
    cand, n = stem + ext, 1
    while True:
        low = cand.lower()
        taken = (low in SERVICE_NAMES or low.startswith(("raw.", "page-", "_"))
                 or (os.path.exists(os.path.join(workdir, cand)) and low not in ours))
        if not taken:
            return cand
        n += 1
        cand = "%s-%d%s" % (stem, n, ext)


DOCX_NOTES = 8 * 1024 * 1024       # a docx's footnotes or endnotes, read up to this (KNOWN-ISSUES 133)
_W_T = re.compile(r"<w:t(?:\s[^<>]{0,8192})?>([^<]*)</w:t>")


def docx_notes(data):
    """Footnotes and endnotes live outside the body: python-docx does not see them. Each part is
    read up to DOCX_NOTES, and a w:t is matched in linear time (`<w:t[^>]*>(.*?)</w:t>` ran to the
    end of the part from every w:t that never closed)."""
    import zipfile
    out = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        for name in ("word/footnotes.xml", "word/endnotes.xml"):
            if name not in z.namelist():
                continue
            xml = zip_part(z, name, DOCX_NOTES).decode("utf-8", "replace")
            texts = _W_T.findall(xml)
            line = " ".join(unescape(x) for x in texts).strip()
            line = re.sub(r"\s+", " ", line)
            if len(line) > 40:                     # skip separator footnotes
                out.append(line)
    except Exception:                              # noqa: BLE001
        return ""
    return "\n\n".join(out)


LOGIN_URL = re.compile(r"(^|/)(login|log-in|signin|sign-in|auth|sso|session)(/|$|\?)|accounts\.google\.com", re.I)
# What a wall says in a sentence, in about twenty languages: "sign in to continue", "subscribe to read",
# "for subscribers only". Not a word that prose uses: they count on a page of under LOGIN_PHRASE_WORDS
# words (a teaser and a subscribe box are one; an article that quotes one is not).
LOGIN_PHRASE_WORDS = 80
LOGIN_PHRASES = (
    # en
    "sign in to continue", "log in to continue", "login to continue", "sign in to view", "log in to view",
    "sign in to read", "log in to read", "sign in to see", "log in to see", "sign in to access", "log in to access",
    "subscribe to continue", "subscribe to read", "subscribe to unlock", "subscribe to keep reading",
    "unlock this article", "already a subscriber", "already a paid subscriber", "create an account to continue",
    "create a free account to continue", "register to continue", "register to read", "sign up to read",
    "for subscribers only", "this article is for subscribers", "this post is for paid subscribers",
    "you must be logged in", "you must be signed in", "you must log in", "you need to log in", "you need to sign in",
    "login required",
    "please log in", "please sign in",
    # ru, uk
    "войдите, чтобы", "войдите чтобы", "требуется вход", "авторизуйтесь, чтобы", "авторизуйтесь чтобы",
    "для продолжения войдите", "для продолжения необходимо войти", "необходимо авторизоваться", "требуется авторизация",
    "необходима авторизация", "только для подписчиков", "доступно по подписке", "подпишитесь, чтобы",
    "оформите подписку, чтобы",
    "увійдіть, щоб", "увійдіть щоб", "авторизуйтесь, щоб", "потрібна авторизація", "необхідно авторизуватися",
    "лише для передплатників", "тільки для передплатників", "передплатіть, щоб", "підпишіться, щоб",
    # de, fr, es, pt, it, nl
    "melden sie sich an, um", "melden sie sich an um", "loggen sie sich ein, um", "bitte melden sie sich an",
    "bitte loggen sie sich ein", "nur für abonnenten", "sie müssen angemeldet sein",
    "sie müssen eingeloggt sein", "jetzt weiterlesen mit",
    "connectez-vous pour continuer", "connectez-vous pour accéder", "connectez-vous pour voir",
    "connectez-vous pour lire", "identifiez-vous pour", "veuillez vous connecter", "vous devez être connecté",
    "abonnez-vous pour lire", "abonnez-vous pour continuer", "réservé aux abonnés", "article réservé aux",
    "inicia sesión para", "iniciar sesión para continuar", "debes iniciar sesión", "necesitas iniciar sesión",
    "suscríbete para", "solo para suscriptores", "exclusivo para suscriptores", "regístrate para continuar",
    "faça login para", "faça o login para", "entre para continuar", "assine para ler", "assine para continuar",
    "exclusivo para assinantes", "para continuar lendo", "já é assinante", "você precisa estar logado",
    "inicie sessão para",
    "accedi per continuare", "accedi per leggere", "accedi per visualizzare", "effettua l'accesso per",
    "abbonati per leggere", "abbonati per continuare", "riservato agli abbonati", "per continuare a leggere",
    "devi effettuare l'accesso", "registrati per continuare",
    "log in om verder", "log in om te", "inloggen om", "meld u aan om", "word abonnee om", "alleen voor abonnees",
    "bent u abonnee", "ben je al abonnee", "u moet ingelogd zijn", "je moet ingelogd zijn",
    # pl, cs, tr, sv
    "zaloguj się, aby", "zaloguj się, żeby", "zaloguj się aby", "tylko dla prenumeratorów", "tylko dla subskrybentów",
    "wykup dostęp", "musisz być zalogowany",
    "přihlaste se pro pokračování", "pro pokračování se přihlaste", "přihlaste se, abyste", "pouze pro předplatitele",
    "musíte být přihlášeni",
    "devam etmek için giriş", "devam etmek için oturum", "görüntülemek için giriş", "okumak için giriş",
    "okumak için abone", "abonelere özel", "yalnızca abonelere", "giriş yapmanız gerekiyor",
    "logga in för att", "bli prenumerant", "endast för prenumeranter", "prenumerera för att", "du måste logga in",
    # ja, zh, ko
    "ログインして続き", "ログインしてください", "ログインが必要", "続きを読むには", "続きをみるには", "会員登録が必要",
    "会員限定", "有料会員限定", "有料記事", "購読者限定", "この記事は有料",
    "登录后查看", "登录后可见", "登录后阅读", "登录后继续", "登录查看", "请先登录", "请登录后", "登入後", "請先登入",
    "請登入後", "付费阅读", "付費閱讀", "订阅后阅读", "訂閱後閱讀", "仅限订阅", "僅限訂閱", "会员专享", "會員專享",
    "仅限会员", "僅限會員", "开通会员", "解锁全文", "解鎖全文", "付费内容", "付費內容",
    "로그인이 필요", "로그인 후", "로그인하세요", "로그인해 주세요", "로그인하시기 바랍니다", "구독 후", "구독자 전용",
    "구독자만", "유료 회원", "회원 전용", "유료 콘텐츠", "프리미엄 콘텐츠",
    # ar, hi, id, vi
    "سجل الدخول للمتابعة", "سجّل الدخول للمتابعة", "سجل دخولك", "يرجى تسجيل الدخول", "يجب تسجيل الدخول",
    "للمشتركين فقط", "اشترك للقراءة", "اشترك للاستمرار", "محتوى حصري للمشتركين",
    "जारी रखने के लिए लॉग इन", "पढ़ना जारी रखने के लिए", "आगे पढ़ने के लिए", "देखने के लिए लॉग इन", "सब्सक्राइबर्स के लिए",
    "केवल सदस्यों के लिए", "लॉगिन करना होगा",
    "masuk untuk melanjutkan", "login untuk melanjutkan", "login untuk melihat", "masuk untuk melihat", "silakan masuk",
    "silakan login", "berlangganan untuk membaca", "berlangganan untuk melanjutkan", "khusus pelanggan",
    "hanya untuk pelanggan", "anda harus login", "anda harus masuk",
    "đăng nhập để tiếp tục", "đăng nhập để xem", "đăng nhập để đọc", "vui lòng đăng nhập", "bạn cần đăng nhập",
    "bạn phải đăng nhập", "đăng ký để đọc", "dành cho thành viên",
)
# The words of a sign-in form, one language by one: weak on a page of a few words by themselves,
# medium beside a password field (a form of Facebook's is 55-66 words, Instagram's 40-48).
LOGIN_FORM_WORDS = 120
LOGIN_HINTS = (
    "sign in", "log in", "login", "sign up", "log into",
    "войти", "войдите", "авторизуйтесь", "зарегистрир", "забыли пароль",
    "увійти", "увійдіть", "авторизуйтесь", "зареєстру", "забули пароль",
    "anmelden", "einloggen", "registrieren", "passwort vergessen",
    "se connecter", "connectez-vous", "identifiez-vous", "s'identifier", "mot de passe oublié",
    "iniciar sesión", "inicia sesión", "iniciar sesion", "regístrate", "olvidaste tu contraseña",
    "fazer login", "faça login", "iniciar sessão", "esqueceu a senha", "entrar no", "entrar na",
    "accedi a", "accedi con", "accedi o registrati", "effettua l'accesso", "password dimenticata",
    "inloggen", "aanmelden", "wachtwoord vergeten",
    "zaloguj", "nie pamiętasz hasła",
    "přihlásit", "přihlášení", "přihlaste", "zapomenuté heslo",
    "giriş yap", "oturum aç", "üye ol", "şifremi unuttum",
    "logga in", "inloggning", "glömt lösenord",
    "ログイン", "サインイン", "会員登録", "新規登録", "お申し込み", "有料会員",
    "登录", "登錄", "登入", "登录/注册", "注册/登录", "免费注册", "立即注册", "订阅", "忘记密码", "忘記密碼",
    "로그인", "회원가입", "비밀번호 찾기",
    "تسجيل الدخول", "تسجيل دخول", "إنشاء حساب", "نسيت كلمة",
    "लॉग इन", "लॉगिन", "साइन इन", "साइन अप", "पासवर्ड भूल",
    "masuk ke", "lupa kata sandi", "lupa password", "daftar akun", "daftar sekarang",
    "đăng nhập", "đăng ký tài khoản", "quên mật khẩu",
)
_LOGIN_PHRASES = tuple(fold(p) for p in LOGIN_PHRASES)
_LOGIN_HINTS = tuple(fold(p) for p in LOGIN_HINTS)
PASSWORD = re.compile(r"(?is)<input[^>]+type\s*=\s*[\"']?password")


def login_words(text):
    """The size of a short text for the sign-in rules: Chinese and Japanese count two characters to a word,
    as a sign-in form of 70 words is 140 characters of either (words_of counts each: a 2 000-character
    article must not look short, and the rules here are about pages that are)."""
    t = text or ""
    cjk = len(_CJK.findall(t))
    return len(_CJK.sub(" ", t).split()) + (cjk + 1) // 2


def login_state(html, text, status, final, requested):
    """strong = definitely a wall, medium = very likely, weak = just a mention."""
    if status == 401:
        return "strong", "HTTP 401"
    if final and requested and final != requested and LOGIN_URL.search(final):
        return "strong", "redirected to " + final[:100]
    body = text or ""
    words = login_words(body)
    pwd = bool(PASSWORD.search(html or ""))
    if pwd and words < 40:
        return "medium", "password form and little text"
    low = fold(body) if words < max(LOGIN_PHRASE_WORDS, LOGIN_FORM_WORDS) else ""
    if words < LOGIN_PHRASE_WORDS and any(p in low for p in _LOGIN_PHRASES):
        return "medium", "text asks to sign in or subscribe"
    if pwd and words < LOGIN_FORM_WORDS and any(p in low for p in _LOGIN_HINTS):
        return "medium", "a password form and a sign-in phrase on a short page"
    # A password field or a "sign in" note on a long page is a header modal, not a wall: 27 835
    # characters of a shop came with a login dialog and the advice "text may be partial" was noise.
    # The same rule keeps a newsletter page (a form plus 90 words) out of `login_required`.
    if words < 40:
        head = fold(body[:max(1, len(body) // 4)])
        if pwd or any(p in head for p in _LOGIN_HINTS):
            return "weak", "login mentioned on a short page"
    return "", ""


# A paywall written in JavaScript hides text the server sent: the HTML carries the article, a script
# covers it. What the HTML says about it is in the words schema.org gave publishers (Google asks a
# paywalled page for `isAccessibleForFree: false`, and for `hasPart` with the `cssSelector` of the part
# that is hidden). A container's class (`paywall`, `meteredContent`, `piano`) is no such word: free
# pages carry them too (NPR's `piano`, Bhaskar's `paywallBlockedContent`, Le Monde's comment wall).
_LD_JSON = re.compile(r"(?is)<script\b[^>]*\btype\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script\s*>")
_FREE_ATTR = re.compile(r"(?is)<[a-z]+\b[^>]*\bitemprop\s*=\s*[\"']isAccessibleForFree[\"'][^>]*>")
_FREE_WORD = re.compile(r"(?i)isAccessibleForFree")
_FREE_FALSE = re.compile(r"(?i)isAccessibleForFree[\"']?\s*:\s*[\"']?\s*false")
_CONTENT_FALSE = re.compile(r"(?i)\bcontent\s*=\s*[\"']\s*false\s*[\"']")
_WORK_TYPES = frozenset(("CreativeWork", "Report", "Review", "Recipe", "Course", "Book", "Episode", "Clip",
                         "VideoObject", "AudioObject", "MediaObject", "ImageObject", "Dataset", "Comment"))
PAYWALL_SCAN = 4000000                 # characters of a page looked at


def _not_free(v):
    return v is False or (isinstance(v, str) and v.strip().lower() == "false")


def _is_work(types):
    """A creative work (an article, a page, a video): schema.org's isAccessibleForFree is also
    an Event's and a Place's, where false means a ticket, not a paywall."""
    kinds = [types] if isinstance(types, str) else [t for t in (types or []) if isinstance(t, str)]
    return not kinds or any(t in _WORK_TYPES or t.endswith(("Article", "Posting", "Page", "PageElement"))
                            for t in kinds)


def _ld_nodes(x, depth=0):
    if depth > 8:
        return
    if isinstance(x, list):
        for i in x[:400]:
            yield from _ld_nodes(i, depth + 1)
    elif isinstance(x, dict):
        yield x
        for v in x.values():
            if isinstance(v, (dict, list)):
                yield from _ld_nodes(v, depth + 1)


def paywall_signal(html):
    """Why a page says it is paywalled ("" when it does not): schema.org's `isAccessibleForFree: false`
    on a creative work in the page's JSON-LD or microdata, with the selectors of the hidden parts."""
    page = (html or "")[:PAYWALL_SCAN]
    if not _FREE_WORD.search(page):
        return ""
    marked, parts = False, []
    for blob in _LD_JSON.findall(page):
        if not _FREE_WORD.search(blob):
            continue
        try:
            data = json.loads(blob.strip().strip("﻿"), strict=False)
        except ValueError:
            # a script the publisher wrote by hand: its own word is still its own word
            marked = marked or bool(_FREE_FALSE.search(blob))
            continue
        for node in _ld_nodes(data):
            if _not_free(node.get("isAccessibleForFree")) and _is_work(node.get("@type")):
                marked = True
                sel = node.get("cssSelector")
                for one in ([sel] if isinstance(sel, str) else sel if isinstance(sel, list) else []):
                    if isinstance(one, str) and one.strip() and one.strip()[:60] not in parts:
                        parts.append(one.strip()[:60])
    if not marked:
        marked = any(_CONTENT_FALSE.search(tag) for tag in _FREE_ATTR.findall(page))
    if not marked:
        return ""
    return "the page says it is paywalled (schema.org isAccessibleForFree: false%s)" % (
        "; hidden part: " + ", ".join(parts[:3]) if parts else "")


def google_export(url):
    """A public Google Doc is a JS shell; its export endpoint is the document itself."""
    p = urllib.parse.urlparse(url)
    if (p.hostname or "").lower() not in ("docs.google.com", "drive.google.com"):
        return ""
    m = re.match(r"^/(document|spreadsheets|presentation)/d/([A-Za-z0-9_-]{10,})", p.path or "")
    if not m:
        return ""
    fmt = {"document": "docx", "spreadsheets": "xlsx", "presentation": "pptx"}[m.group(1)]
    return "https://docs.google.com/%s/d/%s/export?format=%s" % (m.group(1), m.group(2), fmt)


def meta_refresh_target(html, base):
    """A `<meta http-equiv="refresh">` target: a redirect that arrives as a 200."""
    m = re.search(r"(?is)<meta\b[^>]*http-equiv\s*=\s*[\"']?\s*refresh[^>]*>", html or "")
    if not m:
        return ""
    c = re.search(r"(?i)content\s*=\s*[\"']([^\"']*)", m.group(0))
    if not c:
        return ""
    u = re.search(r"(?i)url\s*=\s*['\"]?([^'\"\s;>]+)", c.group(1))
    return urllib.parse.urljoin(base, unescape(u.group(1))) if u else ""


def disposition_name(value):
    """`filename` or `filename*` from a Content-Disposition header, or "": a name in any script and any
    charset the header names (`filename*=GBK''%CD%BC.png`). `value` is text, read from the header's bytes
    once where it came in (intl.header_bytes: UTF-8, else a GBK or Big5 reading, else Latin-1)."""
    v = value or ""
    m = re.search(r"(?i)filename\*\s*=\s*([^;]+)", v)
    if m:
        raw = m.group(1).strip().strip('"')
        charset = "utf-8"
        if "'" in raw:
            parts = raw.split("'", 2)
            if len(parts) == 3:
                charset, raw = parts[0] or "utf-8", parts[2]
        try:
            return urllib.parse.unquote(raw, encoding=intl.codec_of(charset), errors="replace")
        except Exception:                                     # noqa: BLE001  (a charset Python does not have)
            return urllib.parse.unquote(raw, errors="replace")
    m = re.search(r'(?i)filename\s*=\s*"([^"]*)"', v) or re.search(r"(?i)filename\s*=\s*([^;]+)", v)
    return m.group(1).strip() if m else ""


def human_bytes(n):
    if n >= 1024 * 1024:
        v = n / 1048576.0
        return ("%.1fM" % v) if v < 10 else ("%dM" % round(v))
    if n >= 1024:
        return "%dK" % (n // 1024)
    return "%dB" % n


def exact_bytes(n):
    return "{:,}".format(int(n)).replace(",", " ")


def _img_dims(b):
    try:
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
        if b[:3] == b"\xff\xd8\xff":
            i = 2
            while i + 9 < len(b):
                if b[i] != 0xFF:
                    i += 1
                    continue
                t = b[i + 1]
                if t == 0xFF:
                    i += 1
                elif t == 0x00 or 0xD0 <= t <= 0xD7:
                    i += 2
                elif 0xC0 <= t <= 0xCF and t not in (0xC4, 0xC8, 0xCC):
                    return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
                else:
                    i += 2 + int.from_bytes(b[i + 2:i + 4], "big")
        if b[:3] == b"GIF":
            return int.from_bytes(b[6:8], "little"), int.from_bytes(b[8:10], "little")
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            ch = b[12:16]
            if ch == b"VP8X":
                return int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
            if ch == b"VP8 ":
                return (int.from_bytes(b[26:28], "little") & 0x3FFF,
                        int.from_bytes(b[28:30], "little") & 0x3FFF)
            if ch == b"VP8L":
                bits = int.from_bytes(b[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except Exception:                              # noqa: BLE001
        pass
    return 0, 0


def _attr(tag, name):
    m = re.search(r"(?is)\b%s\s*=\s*[\"']([^\"']*)" % re.escape(name), tag)
    return unescape(m.group(1)).strip() if m else ""


def image_base(html, url):
    """<base href> is what a browser resolves relative URLs against; honour it."""
    return engines.page_base(html, url)


def html_image_refs(html, base):
    base = image_base(html, base)
    html = pictures.real_srcs(html)       # a lazy picture's placeholder is not the picture
    out = []
    for tag in re.findall(r"(?is)<img\b[^>]*>", html or ""):
        src = _attr(tag, "src") or _attr(tag, "data-src") or _attr(tag, "data-original")
        srcset = _attr(tag, "srcset") or _attr(tag, "data-srcset")
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            src = src or first
        if not src or src.startswith("javascript:"):
            continue
        out.append((urllib.parse.urljoin(base, src), _attr(tag, "alt")))
    for tag in re.findall(r"(?is)<source\b[^>]*>", html or ""):
        srcset = _attr(tag, "srcset")
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            out.append((urllib.parse.urljoin(base, first), ""))
    return out


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """A picture may redirect only to http(s) (urllib alone would follow ftp://), and a picture
    of a public page never into the local network. `inside` is set for a private page."""
    inside = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib has percent-encoded the Location's bytes as they came (as a browser does); the host
        # checked and the host asked for are then one name: a request decodes the escapes in a host
        newurl = intl.iri_to_uri(newurl)
        why = hop_refused("http://localhost/" if self.inside else req.full_url, newurl)
        if why:
            raise urllib.error.HTTPError(newurl, code, "redirect refused: " + why, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _InsideRedirect(_CheckedRedirect):
    inside = True



def _fetch_image(ref, base, limit=MEDIA_LIMIT, allow_private=False, known=None):
    """One picture: {"data", "ct", "etag", "last_modified"}, or {"unchanged": True, "file": ...}
    after a 304, or {"why": ...} - the reason goes into the marker. limit=None means no limit
    (--download). allow_private is set when the page itself is private, so a local documentation
    server can use its own pictures."""
    url, alt = ref
    # read(None) is "all of it" on every Python; read(-1) is that from 3.10 on, but 3.9's
    # http.client makes a bytearray(-1) of it - every --download picture failed with "negative count"
    want = None if limit is None else limit + 1
    img_opener = opener(_InsideRedirect if allow_private else _CheckedRedirect)
    prev = (known or {}).get(url) or {}
    cond = {}
    if prev.get("etag"):
        cond["If-None-Match"] = prev["etag"]
    if prev.get("last_modified"):
        cond["If-Modified-Since"] = prev["last_modified"]
    try:
        if url.startswith("data:"):
            head, _, payload = url.partition(",")
            data = base64.b64decode(payload) if "base64" in head else urllib.parse.unquote_to_bytes(payload)
            return {"data": data, "ct": head.split(";")[0][5:], "etag": "", "last_modified": ""}
        # only http(s), even on a private page (<img src="file:///..."> must not read the disk);
        # a public page (or something injected into it) must not make us fetch 127.0.0.1 or a
        # cloud metadata endpoint. The text still names the picture, the file is not taken.
        why = hop_refused("http://localhost/" if allow_private else base, url)
        if why:
            trace("image.refused", url=url[:120], why=why)
            return {"why": "refused: " + why}
        headers = {"User-Agent": UA, "Accept": "image/*,*/*;q=0.8"}
        cj = cookie_header(cookies_for_url(url))    # a hotlink-guard checks the session cookie
        if cj:
            headers["Cookie"] = cj
            _COOKIE_STATS["sent"] += 1
        headers.update(cond)
        req = urllib.request.Request(intl.iri_to_uri(url), headers=headers)
        try:
            with img_opener.open(req, timeout=IMAGE_TIMEOUT) as r:
                data = r.read(want)
                ct = r.headers.get("content-type", "")
                etag = r.headers.get("etag", "") or ""
                last_modified = r.headers.get("last-modified", "") or ""
        except urllib.error.HTTPError as e:
            if e.code == 304 and prev.get("file"):
                return {"unchanged": True, "file": prev["file"],
                        "etag": e.headers.get("etag", "") or prev.get("etag", ""),
                        "last_modified": prev.get("last_modified", "")}
            if e.code not in (403, 401):
                return {"why": str(e.code)}
            # a hotlink guard wants to see the site: the origin only, as a browser sends it to
            # another site - never the page's path or query (a token in it is not theirs). An
            # internal page names nothing to an outside host, and https never tells http.
            ref = origin_of(base)
            if (allow_private and not host_is_private(url)) or (
                    base.lower().startswith("https:") and url.lower().startswith("http:")):
                ref = ""
            if not ref:
                return {"why": str(e.code)}
            req = urllib.request.Request(intl.iri_to_uri(url), headers={"User-Agent": UA, "Referer": ref,
                                                       "Accept": "image/*,*/*;q=0.8",
                                                       **({"Cookie": cj} if cj else {}), **cond})
            with img_opener.open(req, timeout=IMAGE_TIMEOUT) as r:
                data = r.read(want)
                ct = r.headers.get("content-type", "")
                etag = r.headers.get("etag", "") or ""
                last_modified = r.headers.get("last-modified", "") or ""
        if limit is not None and len(data) > limit:
            return {"why": "over %s" % human_bytes(limit)}
        if not data:
            return {"why": "empty"}
        return {"data": data, "ct": ct, "etag": etag, "last_modified": last_modified}
    except urllib.error.HTTPError as e:
        return {"why": str(e.code)}
    except Exception as e:                         # noqa: BLE001
        msg = str(getattr(e, "reason", "") or e)
        return {"why": "timeout" if "timed out" in msg.lower() else re.sub(r"\s+", " ", msg)[:60] or "failed"}


def fetch_pictures(refs, base, workdir, seconds=IMAGE_PHASE_SECONDS, limit=MEDIA_LIMIT,
                   page_private=False, known=None, phase=None):
    """{url: result} for every ref; a picture another page of this host already has comes from
    that page's folder ({"link": path}), the rest from the network in parallel.
    seconds=None (--download) waits for every picture; otherwise what is not done by then is
    {"why": "no time (N s)"}: the text comes first. N is the whole phase (`phase`), of which a
    later round of a window has only the rest."""
    out = {}
    try:
        near = pictures.siblings(os.path.join(cache_root(), "pages"), pictures.folder_prefix(host_of(base)),
                                 workdir)
    except Exception as _dbg_e:                                          # noqa: BLE001
        debuglog.exc("pictures: siblings", _dbg_e)
        near = {}
    todo = []
    for url, alt in refs:
        if url in out:
            continue
        if url in near and not (known or {}).get(url):
            out[url] = {"link": near[url]}
        else:
            todo.append((url, alt))
    if not todo:
        return out
    # daemon threads, not ThreadPoolExecutor: at interpreter exit a pool joins its workers, and a
    # slow picture host would hold the whole answer (theguardian: 4 s of extra wait)
    q, done, lock, stop = queue.Queue(), {}, threading.Lock(), threading.Event()

    def worker():
        while True:
            item = q.get()
            if item is None:
                return
            if stop.is_set():
                continue
            t_img = time.monotonic()
            res = _fetch_image(item, base, limit, page_private, known)
            if debuglog.enabled():
                got_ = res or {}
                debuglog.log("picture", url="data:" if item[0].startswith("data:") else debuglog.mask_url(item[0][:300]),
                             ms=int((time.monotonic() - t_img) * 1000), bytes=len(got_.get("data") or b""),
                             unchanged=bool(got_.get("unchanged")), why=got_.get("why") or "")
            with lock:
                done[item[0]] = res or {"why": "failed"}

    workers = min(IMAGE_WORKERS, len(todo))
    for _ in range(workers):
        threading.Thread(target=worker, daemon=True).start()
    for ref in todo:
        q.put(ref)
    for _ in range(workers):
        q.put(None)
    end = None if seconds is None else time.monotonic() + seconds
    while len(done) < len(todo) and (end is None or time.monotonic() < end):
        time.sleep(0.02)
    stop.set()                                     # nothing new starts after the deadline
    with lock:
        for url, _alt in todo:
            if url not in done:
                debuglog.log("picture", url=debuglog.mask_url(url[:300]), why="no time", phase_s=phase or seconds)
            out[url] = done.get(url) or {"why": "no time (%d s)" % max(1, round(phase or seconds or 0))}
    return out


def _picture_entry(n, url, alt, res, workdir, where, budget_left):
    """Write one picture as img/NN-words.ext and describe it. Returns (entry, bytes written)."""
    e = {"n": n, "url": short_data(url) if url.startswith("data:") else url, "alt": alt or "", "in": where}
    res = res or {"why": "failed"}
    src = res.get("link") or (os.path.join(workdir, res["file"].replace("/", os.sep)) if res.get("unchanged") else "")
    data = res.get("data")
    if not data and not (src and os.path.isfile(src)):
        e["why"] = res.get("why") or "failed"
        why = str(e["why"])
        if retryable(why) and why not in (PENDING, "--deny-images") and not why.startswith("no time"):
            e["failed_at"] = int(time.time())          # asked again once, PICTURE_RETRY_AFTER later
        return e, 0
    if data:
        head, size = data[:4096], len(data)
    else:
        with open(src, "rb") as fh:
            head = fh.read(4096)
        size = os.path.getsize(src)
    if size > budget_left:
        e["why"] = "the page's picture budget (%s) is spent" % human_bytes(PAGE_LIMIT)
        return e, 0
    ext = pictures.ext_of(url, res.get("ct") or "")
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif head[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif head[:4] == b"GIF8":
        ext = ".gif"
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        ext = ".webp"
    rel = pictures.file_name(n, alt, url, ext)
    dest = os.path.join(workdir, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    same_file = bool(src) and os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dest))
    k = 1
    while not same_file and os.path.exists(dest) and not _same_bytes(dest, data, src):
        # another page read into the same --dir has its own 01-logo.png: a path an earlier
        # answer printed keeps pointing at that picture, so this one gets -2 (the number stays)
        k += 1
        stem, dot_ext = os.path.splitext(pictures.file_name(n, alt, url, ext))
        rel = "%s-%d%s" % (stem, k, dot_ext)
        dest = os.path.join(workdir, rel.replace("/", os.sep))
    if same_file or os.path.exists(dest):
        pass                                       # already there, these very bytes
    elif src:
        how = pictures.link_or_copy(src, dest)
        if res.get("link") and (os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(src))))
                                != os.path.normcase(os.path.abspath(workdir))):
            e["reused"] = how                      # another page of this host had it
    else:
        tmp = dest + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    w, h = _img_dims(head)
    e.update(file=rel, bytes=size, dims="%dx%d" % (w, h) if w and h else "?")
    if res.get("unchanged"):
        e["revalidated"] = True                    # a 304: the file on disk is still the page's
    if res.get("etag"):
        e["etag"] = res["etag"]
    if res.get("last_modified"):
        e["last_modified"] = res["last_modified"]
    return e, size


def _same_bytes(path, data, src):
    """True when the file at `path` holds these bytes (`data`, or the file `src`)."""
    try:
        if src and os.path.isfile(src):
            if os.path.samefile(path, src):
                return True
            with open(src, "rb") as fh:
                data = fh.read()
        if data is None or os.path.getsize(path) != len(data):
            return False
        with open(path, "rb") as fh:
            return fh.read() == data
    except OSError:
        return False


def tracking_pixel(res, workdir):
    """A 1x1 or 2x2 picture is a counter or a spacer: shown nowhere."""
    head = (res or {}).get("data") or b""
    if not head and (res or {}).get("link") and os.path.isfile(res["link"]):
        with open(res["link"], "rb") as fh:
            head = fh.read(4096)
    w, h = _img_dims(head[:4096]) if head else (0, 0)
    return bool(w and h and w <= 2 and h <= 2)


def picture_phase(text, page_text, html, base, workdir, manifest, args, deny, known=None, view="",
                  page_private=False):
    """The last step on any path (extractor, reader, a site's API, the
    browser): every picture link of the text becomes a numbered marker in its place, the files go
    to img/ - those of the printed view only; with --download every picture of the page, while
    the text stays the same. Returns (text, page_text)."""
    sig = manifest.setdefault("signals", {})
    text_refs = pictures.refs(text, base)
    page_refs = pictures.refs(page_text, base) if page_text else []
    html_refs = html_image_refs(html, base) if html else []
    # a picture the page itself sizes 1-2 px (a counter, a spacer) gets no number: numbers are
    # given before any download now, and a counter found later would leave a gap
    pixels = html_pixels(html, base)
    text_refs = [r for r in text_refs if r[0] not in pixels]
    page_refs = [r for r in page_refs if r[0] not in pixels]
    in_text = {u for u, _a in text_refs}
    others = {u for u, _a in page_refs + html_refs if u not in in_text and not u.startswith("data:")}
    if others:
        sig["images_outside"] = len(others)
    # A picture on a private address that a public page names is refused when it is fetched
    # (_fetch_image) and counted there: checking every picture of the page up front asked DNS for
    # each host in a row - 14 hosts, a second on ESPN - for pictures most of which are never fetched
    want, seen = [], set()
    # every picture of content.md, then page.md's own, is numbered from the first call:
    # the manifest lists them all, and a call downloads those of the lines it prints (finish)
    groups = [(text_refs, "text"), (page_refs, "page")]
    if args.download:
        groups.append((html_refs, "page"))
    for refs_, where in groups:
        for url, alt in refs_:
            if url and url not in seen:
                seen.add(url)
                want.append((url, alt, where))
    if not want:
        return text, page_text
    # a document's own pictures (a docx's, an EPUB's: doc_pictures) are placed, numbered and on
    # disk already, and those it holds no file for say why; the links its text still has - an
    # address of their own - are numbered after them, and the document's stay in the manifest (one
    # missing picture dropped them all, and --refresh deleted their files)
    placed = [e for e in (manifest.get("images") or []) if isinstance(e, dict) and (e.get("file") or e.get("why"))]
    first = max([int(e.get("n") or 0) for e in placed] + [0]) + 1
    if deny or not args.download:
        why = "--deny-images" if deny else PENDING
        entries = [{"n": i, "url": short_data(u) if u.startswith("data:") else u, "alt": a or "", "in": w,
                    "why": why} for i, (u, a, w) in enumerate(want, first)]
        for e in entries:                       # what a --refresh may revalidate instead of fetching
            k = (known or {}).get(e["url"])
            if k and (k.get("etag") or k.get("last_modified")):
                e.update(etag=k.get("etag") or "", last_modified=k.get("last_modified") or "",
                         prev_file=k.get("file") or "")
        by_url = {u: e for (u, _a, _w), e in zip(want, entries)}
        if deny:
            sig["images_denied"] = len([e for e in entries if e["in"] == "text"])
        manifest["images"] = placed + entries
        text, page_text = (pictures.mark(text, base, by_url, pixels),
                           pictures.mark(page_text or "", base, by_url, pixels))
        picture_lines(entries, text, page_text)
        return text, page_text
    # only --download comes here: every picture of the page, no time and no size limit
    t_pic = now()
    got = fetch_pictures([(u, a) for u, a, _w in want], base, workdir, seconds=None, limit=None,
                         page_private=page_private, known=known)
    budget.record("pictures", t_pic, note="--download: %d" % len(want))
    private = sum(1 for u, _a, _w in want if str((got.get(u) or {}).get("why") or "").startswith("refused"))
    if private:
        sig["images_private_skipped"] = private
    entries, by_url, drop, n, spent = [], {}, set(), first - 1, 0
    byte_budget = float("inf")
    for url, alt, where in want:
        res = got.get(url)
        if tracking_pixel(res, workdir):
            drop.add(url)
            continue
        n += 1
        e, size = _picture_entry(n, url, alt, res, workdir, where, byte_budget - spent)
        spent += size
        entries.append(e)
        by_url[url] = e
    cut = sum(1 for e in entries if str(e.get("why") or "").startswith("no time"))
    if cut:
        sig["images_truncated"] = cut
    reused = sum(1 for e in entries if e.get("reused"))
    if reused:
        sig["images_reused"] = reused
    manifest["images"] = placed + entries
    trace("images", n=len(entries), files=sum(1 for e in entries if e.get("file")), cut=cut, reused=reused,
          dropped=len(drop), outside=len(others))
    return pictures.mark(text, base, by_url, drop), pictures.mark(page_text or "", base, by_url, drop)


PENDING = "not printed yet"


def html_pixels(html, base):
    """The pictures a page sizes 1-2 px in its own markup: counters and spacers, known before
    any download."""
    out = set()
    for tag in re.findall(r"(?is)<img\b[^>]*>", (html or "")[:3000000])[:3000]:
        w, h = _attr(tag, "width"), _attr(tag, "height")
        if w.isdigit() and h.isdigit() and int(w) <= 2 and int(h) <= 2:
            src = _attr(tag, "src")
            if src and not src.startswith("data:"):
                out.add(pictures.resolve(src, base))
    return out


def retryable(why):
    """A picture without a file that a printed window should fetch: never asked for yet, cut by
    the 6 s phase, lost to the network, a server error, or named by a --deny-images run. Not one
    the server refused for good (404), an address refused as private, or one over a limit."""
    w = str(why or "")
    if w in (PENDING, "--deny-images", "timeout", "failed") or w.startswith("no time"):
        return True
    if w.isdigit():
        return w.startswith("5") or w in ("408", "429")
    return bool(w) and not w.startswith(("refused", "over ", "empty", "the page's picture budget"))


def retry_due(e):
    """A failed picture is asked once more, by a window printed PICTURE_RETRY_AFTER after the
    failure; the read that has just failed it is not repeated by every answer from the cache."""
    t = e.get("failed_at")
    return not e.get("retried") and (not t or time.time() - float(t) >= PICTURE_RETRY_AFTER)


def picture_lines(entries, text, page_text):
    """Each entry's line: in content.md for a picture of the text, in page.md for page.md's own."""
    first = {}
    for key, body in (("text", text), ("page", page_text)):
        for i, line in enumerate((body or "").split("\n"), 1):
            for m in re.finditer(r"\[img #(\d+)", line):
                first.setdefault((key, int(m.group(1))), i)
    for e in entries:
        ln = first.get((e.get("in") or "text", e.get("n")))
        if ln:
            e["line"] = ln


def window_pictures(workdir, manifest, url, view, start, public):
    """A call downloads the pictures of the lines it prints that
    have no file yet - never printed, cut by the 6 s phase, lost to the network, or named by a
    --deny-images run - and rewrites their markers in place; no line moves. A picture outside
    every printed window stays a numbered address. Moscow's first read took 8.6 s with its 146
    pictures and 4.5 s without them; a window of it holds a handful."""
    files = manifest.get("files") or {}
    path = files.get("content" if view == "content.md" else "page") or os.path.join(workdir, view)
    if not os.path.isfile(path):
        return manifest
    asked = set()
    for rnd in range(3):
        # a downloaded marker is shorter than a waiting one, so the window can grow once its
        # pictures are in: look again, while there is time
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        _, nxt = answer.render(public, text, view, start or 1, cli_next)
        lines = text.split("\n")
        shown = "\n".join(lines[(start or 1) - 1:(nxt or len(lines) + 1) - 1])
        nums = {int(x) for x in re.findall(r"\[img #(\d+)", shown)} - asked
        if rnd == 0:
            phase = budget.cap(IMAGE_PHASE_SECONDS, budget.tail() * 0.3, floor=0.5)
            phase_end = now() + phase
        if not nums or phase_end - now() < 0.5:
            break
        asked |= nums
        manifest = _window_round(workdir, manifest, url, view, start, nums, files, phase_end - now(), phase)
    return manifest


def _window_round(workdir, manifest, url, view, start, nums, files, seconds, phase):
    """One round of a window's pictures: `seconds` is what is left of the shared `phase`."""
    entries = [dict(e) for e in (manifest.get("images") or []) if isinstance(e, dict)]
    todo = [e for e in entries if e.get("n") in nums and not e.get("file") and retryable(e.get("why"))
            and retry_due(e) and str(e.get("url") or "").startswith(("http://", "https://"))]
    if not todo:
        return manifest
    base = (manifest.get("url") or {}).get("final") or url
    known = {e["url"]: {"etag": e.get("etag") or "", "last_modified": e.get("last_modified") or "",
                        "file": e.get("prev_file") or ""} for e in todo if e.get("prev_file")}
    t_pic = now()
    got = fetch_pictures([(e["url"], e.get("alt") or "") for e in todo], base, workdir,
                         seconds=seconds, page_private=bool(host_is_private(base)), known=known, phase=phase)
    late = sum(1 for e in todo if str((got.get(e["url"]) or {}).get("why") or "").startswith("no time"))
    private = sum(1 for e in todo if str((got.get(e["url"]) or {}).get("why") or "").startswith("refused"))
    if private:
        # a public page naming 127.0.0.1 or a metadata endpoint: the marker stays, the request
        # is never made
        sg = manifest.setdefault("signals", {})
        sg["images_private_skipped"] = int(sg.get("images_private_skipped") or 0) + private
    # a later round ends with the phase it shares: "deadline" only when the read's deadline had
    # shortened that phase
    budget.record("pictures", t_pic, budget.ended(IMAGE_PHASE_SECONDS, phase) if late else "ok",
                  own=IMAGE_PHASE_SECONDS, given=seconds,
                  note="%s: %d asked, %d with a file, %d cut" % (
                      view, len(todo), sum(1 for e in todo if (got.get(e["url"]) or {}).get("data")
                                          or (got.get(e["url"]) or {}).get("link")
                                          or (got.get(e["url"]) or {}).get("unchanged")), late))
    old_marks = {e["n"]: pictures.marker(e) for e in todo}
    spent = sum(int(e.get("bytes") or 0) for e in entries)
    fresh, gone = {}, set()
    for e in todo:
        res = got.get(e["url"])
        if tracking_pixel(res, workdir):
            gone.add(e["n"])                       # a counter pixel: its marker goes, its line stays
            continue
        new, size = _picture_entry(e["n"], e["url"], e.get("alt"), res, workdir, e.get("in", "text"),
                                   PAGE_LIMIT - spent)
        spent += size
        if e.get("line"):
            new["line"] = e["line"]
        if e.get("failed_at") and new.get("failed_at"):
            new["retried"] = True                  # failed twice: printed again, it is not asked
        fresh[e["n"]] = new
    entries = [fresh.get(e.get("n"), e) for e in entries if e.get("n") not in gone]
    for key in ("content", "page"):
        p = files.get(key) or os.path.join(workdir, key + ".md")
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        new_body = body
        for num, old in old_marks.items():
            new_body = new_body.replace(old, "" if num in gone else pictures.marker(fresh[num]))
        if new_body != body:
            write_view(p, new_body)
    sig = manifest.setdefault("signals", {})
    cut = sum(1 for e in fresh.values() if str(e.get("why") or "").startswith("no time"))
    if cut:
        sig["images_truncated"] = cut
    else:
        sig.pop("images_truncated", None)
    reused = sum(1 for e in entries if e.get("reused"))
    if reused:
        sig["images_reused"] = reused
    if not any(e.get("why") == "--deny-images" for e in entries):
        sig.pop("images_denied", None)
    manifest["images"] = entries
    trace("images.window", view=view, start=start or 1, asked=len(todo),
          files=sum(1 for e in fresh.values() if e.get("file")), cut=cut, dropped=len(gone))
    return manifest


_OWN_ADDRESS = re.compile(r"(?i)^\s*(?:[a-z][a-z0-9+.-]{0,31}:|//)")      # a picture's address of its own


def doc_pictures(text, entries, workdir, left=None):
    """A document's pictures (DOCX, PPTX, EPUB in document order): where the text names
    one (`![](word/media/image1.png)`, a converter's `![](images/x.png)`), its marker stands there;
    the others are listed after the text in document order. Files become img/NN-words.ext.
    `left`: {name: why} of the pictures the archive or our RTF reader holds that were left out
    (zip_images, rtf_images): a tracking pixel's link goes, a copy's is its picture's marker,
    another's is a marker that says why, numbered after the others - and so is a link to a
    picture the document does not hold. A name inside the document never stays a link for the
    picture phase, which resolved it against the document's address and asked its server for a
    file under a name the reader had made up (`rtf-pict-0003.png`). Returns (text, entries)."""
    by_zip, gone = {}, {}
    for e in entries:
        z = e.pop("_zip", "") or ""
        by_zip.setdefault(z, e)
        by_zip.setdefault(posixpath.basename(z), e)
    for name, why in (left or {}).items():
        gone.setdefault(name, why)
        gone.setdefault(posixpath.basename(name), why)

    def find(src):
        """(the entry of a picture the text names, or None and why it has none)."""
        key = urllib.parse.unquote(src).lstrip("./")
        e = by_zip.get(key) or by_zip.get(posixpath.basename(key))
        why, seen = gone.get(key) or gone.get(posixpath.basename(key)), set()
        while e is None and isinstance(why, tuple) and why[1] not in seen:      # a copy: its picture's
            seen.add(why[1])
            e, why = by_zip.get(why[1]), gone.get(why[1])
        return e, (None if isinstance(why, tuple) else why)
    links = pictures.links(text)
    placed = []
    for _a, _b, alt, src in links:
        e, _why = find(src)
        if e is not None and not any(e is x for x in placed):
            placed.append(e)
            if alt and not e.get("alt"):
                e["alt"] = alt
    rest = [e for e in entries if not any(e is x for x in placed)]
    for n, e in enumerate(placed + rest, 1):
        old = os.path.join(workdir, e["file"].replace("/", os.sep))
        rel = pictures.file_name(n, e.get("alt"), e["file"], os.path.splitext(e["file"])[1].lower())
        new = os.path.join(workdir, rel.replace("/", os.sep))
        if os.path.normcase(old) != os.path.normcase(new) and os.path.isfile(old):
            os.replace(old, new)
        e.update(n=n, file=rel, url=e.get("url") or "", **{"in": "text" if n <= len(placed) else "list"})
    by_src, drop, absent = {}, set(), []
    for _a, _b, alt, src in links:
        if src in by_src or src in drop:
            continue
        e, why = find(src)
        if e is not None:
            by_src[src] = e
        elif why == "a tracking pixel":
            drop.add(src)                          # a counter or a spacer: shown nowhere, as on a page
        elif not _OWN_ADDRESS.match(src):
            absent.append({"n": len(placed) + len(rest) + len(absent) + 1, "url": urllib.parse.unquote(src).strip(),
                           "alt": alt or "", "in": "text", "why": why or "not in the document"})
            by_src[src] = absent[-1]
    text = pictures.mark(text, "", by_src, drop)
    if rest:
        text = (text or "").rstrip() + "\n\n" + pictures.unplaced_list(rest)
    return text, placed + rest + absent


RTF_PICTURES = "_rtf-pictures"      # the folder of a read where our RTF reader writes its pictures


def rtf_images(folder, workdir, left=None):
    """The pictures our RTF reader wrote (docreaders' rtf-pict-NNNN.png and .jpg, KNOWN-ISSUES 166)
    as a document's pictures, in its order: into img/, an entry each for doc_pictures(), which puts
    each one's marker where the text names it. A tracking pixel is left out, and named in `left`
    (doc_pictures takes its link out); the folder goes. Each file is read for its own size: read
    for 100 MB, a 100-byte file cost 17 ms, and 1 000 pictures 17 s."""
    out = []
    left = {} if left is None else left
    try:
        names = sorted(n for n in os.listdir(folder) if re.match(r"^rtf-pict-\d{4}\.(?:png|jpg)$", n))
    except OSError:
        return out
    for name in names:
        src = os.path.join(folder, name)
        try:
            with open(src, "rb") as fh:
                data = fh.read(min(os.fstat(fh.fileno()).st_size, MEDIA_LIMIT) + 1)
        except OSError:
            left[name] = "it could not be read"
            continue
        w, h = _img_dims(data)
        if not data or len(data) > MEDIA_LIMIT or (w and h and w <= 2 and h <= 2):
            left[name] = "a tracking pixel" if data and w and h and w <= 2 and h <= 2 else \
                "empty" if not data else "over the size limit"
            continue
        os.makedirs(os.path.join(workdir, "img"), exist_ok=True)
        os.replace(src, os.path.join(workdir, "img", name))
        out.append({"file": "img/" + name, "bytes": len(data), "dims": "%dx%d" % (w, h) if w and h else "?",
                    "alt": "", "_zip": name, "order": len(out) + 1})
    shutil.rmtree(folder, ignore_errors=True)
    return out


def zip_images(path, workdir, limit=PAGE_LIMIT, left=None):
    """DOCX/EPUB keep pictures inside the package (word/media, OEBPS/images/...).

    Positions cannot be recovered without parsing document.xml, so the pictures land in img/
    and in the manifest, but no markers appear in the text. `limit` is what the archive may
    unpack in all: every byte read counts, a picture kept or not (40 copies of a 63 MB picture
    in 2.5 MB of EPUB were each unpacked and hashed, a counter pixel that is a gigabyte of
    zeros the same), and a copy of a picture already unpacked - the same declared size and CRC -
    is not unpacked again. `left` gets {name: why} of each picture left out - ("same", the name
    of the picture it is a copy of) for a copy - so doc_pictures() never leaves its link for the
    picture phase to ask the document's server for.
    """
    import zipfile
    left = {} if left is None else left
    try:
        z = zipfile.ZipFile(path)
        docreaders.fix_zip_names(z)                  # the names an EPUB's spine gives, in a code page with no flag
    except Exception:                                # noqa: BLE001
        return []
    imgdir = os.path.join(workdir, "img")
    out, seen, used, total, unpacked = [], {}, set(), 0, {}
    names = z.namelist()
    # a docx names its pictures in document.xml, an EPUB in its spine: reading order, and for an
    # EPUB the pictures its pages show wherever they are kept (a.png at the root, jacket/). The
    # order is the read's step like any other: its own cap, or less when the deadline is nearer
    order = []
    if any(os.path.splitext(n)[1].lower() in IMG_EXT for n in names):
        t_ord = now()
        secs = budget.cap(PICTURE_ORDER_SECONDS, floor=0.5)
        try:
            order = docx_image_order(z, t_ord + secs) or epub_image_order(z, t_ord + secs)
        except Exception as e:                       # noqa: BLE001
            debuglog.exc("pictures: order", e)
        cut = not order and now() - t_ord >= secs
        budget.record("picture-order", t_ord, budget.ended(PICTURE_ORDER_SECONDS, secs) if cut else "ok",
                      own=PICTURE_ORDER_SECONDS, given=secs, note="%d pictures" % len(order))
    shown = set(order)
    for name in names:
        ext = os.path.splitext(name)[1].lower()
        # an ODT keeps its pictures in Pictures/ (LibreOffice) or media/ (Word); Thumbnails/ is
        # the file manager's preview
        if ext not in IMG_EXT or not (name in shown or re.search(
                r"(?i)(word/media/|/images?/|/media/|^Pictures/|^media/)", name)):
            continue
        try:
            info = z.getinfo(name)
            if info.file_size > MEDIA_LIMIT or total + info.file_size > limit:
                # a zip bomb is refused before it is read
                left[name] = "over the size limit" if info.file_size > MEDIA_LIMIT else \
                    "the archive's pictures are over %s" % human_bytes(limit)
                continue
            if (info.file_size, info.CRC) in unpacked:
                left[name] = ("same", unpacked[(info.file_size, info.CRC)])
                continue                             # the same bytes again: not read a second time
            if info.file_size > 64 * 1024 * 1024 and info.compress_size * 100 < info.file_size:
                left[name] = "not a picture: it unpacks to %s" % human_bytes(info.file_size)
                continue                             # >100x compression ratio: not a picture
            with z.open(name) as fh:
                data = fh.read(MEDIA_LIMIT + 1)
        except Exception:                            # noqa: BLE001
            left[name] = "it does not unpack"
            continue
        total += len(data)
        if not data or len(data) > MEDIA_LIMIT or total > limit:
            left[name] = "empty" if not data else "over the size limit" if len(data) > MEDIA_LIMIT else \
                "the archive's pictures are over %s" % human_bytes(limit)
            continue
        unpacked[(info.file_size, info.CRC)] = name
        w, h = _img_dims(data)
        if w and h and w <= 2 and h <= 2:            # tracking pixel
            left[name] = "a tracking pixel"
            continue
        digest = hashlib.sha1(data).hexdigest()
        if digest in seen:
            left[name] = ("same", seen[digest])
            continue
        seen[digest] = name
        os.makedirs(imgdir, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(name))[:60] or "image"
        base = os.path.splitext(stem)[0] or "image"
        file_name, n = base + ext, 1
        while file_name.lower() in used:
            n += 1
            file_name = "%s-%d%s" % (base, n, ext)
        used.add(file_name.lower())
        rel = "img/" + file_name
        with open(os.path.join(workdir, rel.replace("/", os.sep)), "wb") as fh:
            fh.write(data)
        out.append({"file": rel, "bytes": len(data),
                    "dims": "%dx%d" % (w, h) if w and h else "?", "alt": "", "_zip": name})
    if order:
        rank = {n: i for i, n in enumerate(order)}
        out.sort(key=lambda e: rank.get(e.get("_zip"), len(rank) + 1))
        for i, e in enumerate(out):
            e["order"] = i + 1
    return out                    # `_zip` stays: doc_pictures() finds each picture's place by it


# A tag that never closes costs a scan this much and no more: `[^>]*` runs to the end of the file
# from every `<x ` that has no `>`, so a few KB of them took minutes. A tag is no longer than
# TAG_MAX, and no `<` is inside one (XML does not allow it in a name or a value).
TAG_MAX = 8192
_ROOTFILE = re.compile(r'(?is)<rootfile\b[^<>]{0,%d}?full-path\s*=\s*"([^"<>]+)"' % TAG_MAX)
_ITEM = re.compile(r"(?is)<item\b[^<>]{0,%d}>" % TAG_MAX)
_ITEMREF = re.compile(r"(?is)<itemref\b[^<>]{0,%d}>" % TAG_MAX)
_IMG_SRC = re.compile(r'(?is)<(?:img|image)\b[^<>]{0,%d}(?:src|xlink:href)\s*=\s*"([^"<>]+)"' % TAG_MAX)
_RELATION = re.compile(r"(?is)<Relationship\b[^<>]{0,%d}>" % TAG_MAX)
_BLIP = re.compile(r'(?is)<a:blip\b[^<>]{0,%d}r:embed\s*=\s*"([^"<>]+)"' % TAG_MAX)


def _on_clock(matches, until, every=256):
    """`matches`, the clock read at every `every`-th of them: TimeoutError once `until` (a
    time.time() moment, or None for no limit) has passed."""
    for n, m in enumerate(matches):
        if until is not None and not n % every and time.time() > until:
            raise TimeoutError("the picture order ran out of time")
        yield m


def docx_image_order(z, until=None):
    """The order pictures appear in a docx: word/media names, from document.xml relations.
    [] when `until` passes first: the order is the document's, or none."""
    try:
        doc = zip_part(z, "word/document.xml").decode("utf-8", "replace")
        rels = zip_part(z, "word/_rels/document.xml.rels").decode("utf-8", "replace")
    except Exception:                  # noqa: BLE001  (missing, or damaged: zlib.error)
        return []
    targets, order, named = {}, [], set()
    try:
        for m in _on_clock(_RELATION.finditer(rels), until):
            rid, target = _attr(m.group(0), "Id"), _attr(m.group(0), "Target")
            if rid and target and "media/" in target:
                targets[rid] = "word/" + target.replace("../", "").lstrip("/")
        for m in _on_clock(_BLIP.finditer(doc), until):
            name = targets.get(m.group(1))
            if name and name not in named:
                named.add(name)
                order.append(name)
    except TimeoutError:
        return []
    return order


ZIP_PART = 32 * 1024 * 1024        # what one part of a package is read up to for its pictures' order


def zip_part(z, name, cap=ZIP_PART):
    """A part of a zip package, read up to `cap` whatever its header says: a chapter that unpacks
    to 1 GB was read whole here for its pictures' order, 2 GB of memory (2026-11-20)."""
    with z.open(name) as fh:
        return fh.read(cap)


def epub_image_order(z, until=None):
    """The order pictures appear in an EPUB: the spine, then every <img> inside each document.

    A docx names its pictures in document.xml; an EPUB does the same through the spine of the
    package document, so both land in the reading order the book actually has. A chapter the
    spine names again is not scanned again. [] when `until` passes first.
    """
    try:
        container = zip_part(z, "META-INF/container.xml", 1 << 20).decode("utf-8", "replace")
    except Exception:                  # noqa: BLE001
        return []
    m = _ROOTFILE.search(container)
    if not m:
        return []
    opf_path = m.group(1).lstrip("/")
    opf_dir = posixpath.dirname(opf_path)
    try:
        opf = zip_part(z, opf_path).decode("utf-8", "replace")
    except Exception:                  # noqa: BLE001
        return []
    href, order, named, scanned, total = {}, [], set(), set(), 0
    try:
        for m in _on_clock(_ITEM.finditer(opf), until):
            iid, h = _attr(m.group(0), "id"), _attr(m.group(0), "href")
            if iid and h:
                href[iid] = h
        for m in _on_clock(_ITEMREF.finditer(opf), until, 1):
            doc = href.get(_attr(m.group(0), "idref"))
            if not doc or total > 4 * ZIP_PART:
                continue
            doc_path = posixpath.normpath(posixpath.join(
                opf_dir, urllib.parse.unquote(doc.split("#")[0])))
            if doc_path in scanned:
                continue
            scanned.add(doc_path)
            try:
                body = zip_part(z, doc_path).decode("utf-8", "replace")
            except Exception:          # noqa: BLE001  (a damaged part: its pictures are not ordered)
                continue
            total += len(body)
            for r in _on_clock(_IMG_SRC.finditer(body), until):
                name = posixpath.normpath(posixpath.join(
                    posixpath.dirname(doc_path), urllib.parse.unquote(r.group(1).split("#")[0])))
                if name not in named:
                    named.add(name)
                    order.append(name)
    except TimeoutError:
        return []
    return order


# ---------------------------------------------------------------- main

VIEWS = ("content.md", "page.md")


_REAL_STDERR = None        # the caller's stderr while quiet_stderr() holds fd 2


def quiet_stderr():
    """Send everything bound for stderr to a log while the page is read; returns the undo.

    The answer budget counts stderr (Codex joins it with stdout), so one library warning or a
    line from a browser driver could push a good answer over the limit. Messages meant for the
    caller still reach the real stderr through say_error(). READ_PAGE_TRACE keeps stderr as is.
    """
    global _REAL_STDERR
    if os.environ.get("READ_PAGE_TRACE") or _REAL_STDERR is not None:
        return lambda: None
    try:
        sys.stderr.flush()
        root = cache_root()
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, "stderr.log")
        log = open(path, "wb" if os.path.isfile(path) and os.path.getsize(path) > (1 << 20) else "ab")
        saved = os.dup(2)
        os.dup2(log.fileno(), 2)
    except Exception:                                          # noqa: BLE001
        return lambda: None
    _REAL_STDERR = saved

    def restore():
        global _REAL_STDERR
        try:
            sys.stderr.flush()
            os.dup2(saved, 2)
            os.close(saved)
            log.close()
        except Exception:                                      # noqa: BLE001
            pass
        _REAL_STDERR = None
    return restore


def say_error(msg):
    data = ("read-page: %s\n" % msg).encode("utf-8", "replace")
    try:
        os.write(_REAL_STDERR if _REAL_STDERR is not None else 2, data)
    except OSError:
        pass


def usage_error(msg):
    """A call that cannot be served as asked: exit 2, the reason on stderr."""
    say_error(msg)
    return 2


def _target_like(s):
    """A URL, a bare host with a path, or a file on this machine: what the read is about."""
    s = s or ""
    return ("://" in s or s.lower().startswith(("www.", "file:")) or os.path.exists(s)
            or bool(re.match(r"(?i)^[a-z0-9.-]+\.[a-z]{2,}(?:[/:?#]|$)", s)))


_edits = ownenv.edits       # ownenv's: its hop must know a misspelled --setup before this file is read


def typo_fixed(name, known):
    """A flag (or an MCP argument) misspelled by a letter or two is the one meant, silently
    (`--screenshot` does what `--screenshots` does): one edit for a short name, two for a
    longer one, and only when one name is that near - --allow-images is not "meant" as
    --deny-images. No abbreviations still: a prefix like --allow stays unknown."""
    if name in known:
        return name
    body = name.lstrip("-").lower()
    near = [k for k in known if _edits(body, k.lstrip("-")) <= (1 if len(body) <= 6 else 2)]
    return near[0] if len(near) == 1 else name


def ignored_flags(extra, args, known):
    """What the call had that is not a flag of ours, as notes for the answer's header; the read goes
    on without it (a model invented `--to 407` from `--from`, and the whole call failed).
    A stray word taken for the URL while the URL itself stood further on is put right first. A
    misspelled flag never gets here: typo_fixed made it the flag meant."""
    extra = list(extra)
    if args.url and not _target_like(args.url):
        real = [x for x in extra if not x.startswith("-") and _target_like(x)]
        if real:
            extra[extra.index(real[0])] = args.url
            args.url = real[0]
    notes, i = [], 0
    while i < len(extra):
        tok = extra[i]
        if tok.startswith("-") and "=" not in tok and i + 1 < len(extra) and not extra[i + 1].startswith("-"):
            item, i = "%s %s" % (tok, extra[i + 1]), i + 2
        else:
            item, i = tok, i + 1
        flag = item.split("=")[0].split(" ")[0]
        if not flag.startswith("-"):
            notes.append("%s (not a flag; one URL a call)" % item)
        elif flag in ("--to", "--till", "--until", "--end", "--lines", "--limit", "--max-lines"):
            notes.append("%s (no such flag: an answer prints what fits and names the next line, --from N)" % item)
        else:
            notes.append("%s (no such flag)" % item)
    return notes


def main(argv=None):
    # no abbreviations: one name per action. A flag that is not ours does not stop the
    # read: the answer says it was left out (ignored_flags)
    ap = argparse.ArgumentParser(add_help=True, allow_abbrev=False)
    ap.add_argument("url", nargs="?")
    ap.add_argument("--version", action="store_true", help="print the skill version and exit")
    ap.add_argument("--caps", action="store_true", help="print what this machine has and exit")
    ap.add_argument("--setup", action="store_true",
                    help="install every engine into the skill's own environment, a folder of the user's "
                         "(no admin rights; asks nothing - running it is the consent), or bring it up to date")
    ap.add_argument("--ocr-langs", dest="ocr_langs", default="", metavar="eng+hin",
                    help="with --setup: the OCR language packs to fetch besides the fourteen it fetches for everyone "
                         "and the user's own (kept for the next --setup; each scanned page is read with its script's)")
    ap.add_argument("--allow-external", dest="allow_external", action="store_true",
                    help="allow egress: public readers and archives may be used")
    ap.add_argument("--force-external", dest="force_external", action="store_true",
                    help="use a reader even when the local text looks complete or the URL may carry a "
                         "secret (implies --allow-external; an internal host is never sent)")
    ap.add_argument("--alternate", action="store_true",
                    help="re-read locally by other means: browser and every extractor, keep the best")
    ap.add_argument("--download", action="store_true",
                    help="no size and no time limit, every picture of the page; only free disk space stops it")
    ap.add_argument("--deny-images", dest="deny_images", action="store_true",
                    help="download no picture; the markers say not downloaded and keep the address")
    ap.add_argument("--screenshots", nargs="?", const="2", default="",
                    help="also capture the page as images: the first N screens of a 1280x784 window "
                         "(default 2), two glued into one 1280x1568 picture when Pillow or PyMuPDF is "
                         "there; nothing is scaled down")
    ap.add_argument("--refresh", action="store_true", help="ignore the 15-minute page cache")
    ap.add_argument("--clear-cookies", dest="clear_cookies", action="store_true",
                    help="forget this site's stored cookies before reading (they otherwise live 6 hours)")
    ap.add_argument("--file", default="", metavar="{content.md,page.md}",
                    help="which text to print: content.md (the text, default) or page.md (the whole page)")
    ap.add_argument("--from", dest="from_line", default="0", metavar="N",
                    help="print the block that starts at line N of the saved copy (no network)")
    ap.add_argument("--json", action="store_true", help="print the manifest instead of the text")
    ap.add_argument("--ocr", default="", metavar="N",
                    help="print the text drawn in picture N (the number on its marker) instead of the "
                         "page's text: for a model that cannot see pictures")
    ap.add_argument("--dir", default="")
    known = [s for a in ap._actions for s in a.option_strings if s.startswith("--")]
    argv = [(typo_fixed(t.partition("=")[0], known) + t.partition("=")[1] + t.partition("=")[2])
            if t.startswith("--") else t for t in (sys.argv[1:] if argv is None else argv)]
    args, extra = ap.parse_known_args(argv)
    args.ignored = ignored_flags(extra, args, known)
    # a value we cannot use is left out the same way: the read goes on with the default
    view = (args.file or "").strip().lower()
    view = {"page": "page.md", "content": "content.md", "text": "content.md"}.get(view, view)
    if view and view not in VIEWS:
        args.ignored.append("--file %s (content.md or page.md)" % args.file)
        view = ""
    args.file = view
    try:
        args.from_line = int(str(args.from_line).strip())
    except ValueError:
        args.ignored.append("--from %s (a line number)" % args.from_line)
        args.from_line = 0
    if args.from_line < 0:
        args.ignored.append("--from %d (a line number, 1 or more)" % args.from_line)
        args.from_line = 0
    try:
        args.ocr = int(str(args.ocr).strip() or 0)
    except ValueError:
        args.ignored.append("--ocr %s (a picture's number, from its marker)" % args.ocr)
        args.ocr = 0
    if args.ocr < 0:
        args.ignored.append("--ocr %d (a picture's number, 1 or more)" % args.ocr)
        args.ocr = 0
    if args.setup:
        if args.ocr_langs.strip():
            # the packs named for this --setup, the way READ_PAGE_OCR_LANGS names them - in every shell alike
            # (`READ_PAGE_OCR_LANGS=eng+jpn readpage.py --setup` is a POSIX shell's line, not PowerShell's or cmd's)
            os.environ["READ_PAGE_OCR_LANGS"] = "+".join(x for x in re.split(r"[+,\s]+", args.ocr_langs) if x)
        return ownenv.setup(os.path.abspath(__file__), VERSION)
    if args.ocr_langs.strip():
        args.ignored.append("--ocr-langs %s (for --setup: the OCR packs it fetches)" % args.ocr_langs)
    # files of a read (pages, cookies, pictures, the stderr log) are this user's only: 0600,
    # folders 0700
    mask = os.umask(0o077) if os.name == "posix" else None
    if os.name == "posix" and threading.current_thread() is threading.main_thread():
        import signal
        signal.signal(signal.SIGTERM, _on_term)   # a cancelled MCP call: curl and the rest go too
    restore = quiet_stderr()
    try:
        return read(args)
    finally:
        defuddle_close()                        # this read's worker ends with it
        tables_close()                          # and its layout model's process
        # a browser still closing saves the site's cookies; a hung one does not hold the exit
        browsers_close(min(10.0, max(1.0, budget.left(0))))
        release_locks()                         # the page folder's lock, whatever happened
        restore()
        if mask is not None:
            os.umask(mask)


def read(args):
    """One read: the page, its files, the answer. stderr stays quiet here (quiet_stderr)."""
    shots_want = 0
    if args.screenshots:
        try:
            shots_want = max(0, int(str(args.screenshots).strip()))
        except (TypeError, ValueError):
            shots_want = 2                     # "yes" means two screens; a number is a count

    t0 = now()
    budget.start(None if args.download else budget.SECONDS)
    debuglog.begin()
    tables_reset()
    _DOCS["spent"] = 0.0                       # the read's converter clock for EPUB, ODT and RTF
    _ZIPS.clear()
    _OFFICE.clear()
    _CAPS_RUN.clear()
    _RENDER_STOP.clear()
    _BROWSER_UP.clear()
    _COOKIE_STATS["sent"] = _COOKIE_STATS["stored"] = 0
    _cookie_run_reset()
    if args.version:
        print("read-page %s (schema %d, cache build %d)" % (VERSION, SCHEMA, BUILD))
        return 0
    if args.caps:
        c = caps(fresh=True)                   # run after an install: never the kept answer
        env = ownenv.status()
        out = {"python": c["python"], "libs": c["libs"], "cli": {k: v for k, v in c["cli"].items()},
               "browsers": c["browsers"], "keys": c["keys"],
               "ocr_langs": c.get("ocr_langs") or [],
               "cache": cache_root(),
               # the skill's own environment (--setup): where, whether this run is in it, why not
               "env": {"home": env.get("home") or ownenv.home(), "used": bool(env.get("used")),
                       "why": env.get("why") or "", "python": sys.executable}}
        if c.get("ocr_error"):
            out["ocr_error"] = c["ocr_error"]      # tesserocr is installed and does not start
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    if not args.url:
        print(setup_report(caps(fresh=True)))  # no URL: the "what is missing" report, asked now
        return 0
    url = args.url
    # a file on this machine (a path or a file:// URL) goes through the same
    # converters, with no network at all: no reader, archive, browser or picture download
    local = local_path(url)
    if local:
        url = local_url(local)
        scheme = "file"
    else:
        scheme = (urllib.parse.urlparse(url).scheme or "").lower()
    if not local and not scheme and re.match(r"^[\w-]+(\.[\w-]+)+([/:?#]|$)", url):
        url = "https://" + url                  # "example.com/a" is a host, not a scheme
        scheme = "https"
    if scheme not in ("http", "https", "file"):
        return usage_error("%s is neither an http(s) URL nor a file on this machine" % (
            ("a %s: address" % scheme) if len(scheme) > 1 else repr(args.url[:120])))
    if scheme == "file" and not local:
        return usage_error("no such file: %s" % args.url[:200])
    # one read of a page at a time: a second call for the same page (MCP runs four at once) waits
    # and then gets the cached answer, instead of writing the same folder and deleting the
    # other's .part files
    if debuglog.enabled():
        debuglog.log("run", version=VERSION, schema=SCHEMA, build=BUILD, url=debuglog.mask_url(url),
                     local=bool(local), deadline=None if args.download else budget.SECONDS,
                     flags={k: (debuglog.mask_url(v) if k == "url" else v) for k, v in vars(args).items()
                            if v not in (None, False, "", 0, [])},
                     cache=cache_root(), machine=debuglog.environment())
    try:
        lock_dir = args.dir or page_dir(url)
        os.makedirs(lock_dir, exist_ok=True)
        debuglog.bind(lock_dir, host_of(url))      # READ_PAGE_DEBUG: the log starts in the read's folder
        t_lock = now()
        hold_lock(os.path.join(lock_dir, ".lock"), PAGE_LOCK_SECONDS)
        if now() - t_lock > 0.2:
            debuglog.log("decide", what="page lock", waited=round(now() - t_lock, 2),
                         why="another read of this page held its folder")
    except OSError as e:
        debuglog.exc("page lock", e)
    if args.from_line and not args.refresh:
        # a continuation reads the copy the first answer came from: no network, no cache expiry,
        # so the line numbers it was given still point at the same text
        saved = args.dir or page_dir(url)
        prev = load_manifest(saved)
        if prev and os.path.isfile(os.path.join(saved, answer_view(prev, saved, args.file, True))):
            prev["dir"] = saved
            prev["cache"] = "hit"
            return finish(saved, prev, t0, args)
    if local:
        args.refresh = True                  # a file is read as it is now; it may have changed
    trace("start", url=url, alternate=args.alternate, force=args.force_external,
          allow=args.allow_external, download=args.download)
    # Two rules. An internal host never goes to a remote reader, whatever
    # the flags: the reader cannot open it, and its name is ours. A URL that may carry a secret
    # stays local unless --force-external, the explicit "I know, send it", which wins over that
    # heuristic; --allow-external only says "public if it looks public". The manifest records it.
    internal_why = "a file on this machine" if local else host_is_private(url)
    secret_why = "" if internal_why else url_has_secret(url)
    asked_out = bool(args.allow_external or args.force_external)
    if internal_why:
        external_allowed, override = False, False
    elif args.force_external:
        external_allowed, override = True, bool(secret_why)
    else:
        external_allowed = bool(args.allow_external and not secret_why)
        override = False
    # the flag that would take this URL to a reader: none for an internal host or once allowed
    out_flag = "" if (external_allowed or internal_why) else (
        "--force-external" if secret_why else "--allow-external")
    # what this call's flags met; a cached answer gets it too, since it was read with other flags
    privacy = {"mode": "public" if external_allowed else "sensitive",
               "refused": [] if external_allowed else ["external"],
               "why": privacy_note(internal_why, secret_why, args.allow_external, args.force_external)}
    if override:
        privacy["override"] = True
        privacy["conflict"] = ["force_external wins", "secret heuristic ignored"]
    elif internal_why and asked_out:
        # the action asked for cannot be done: say so in the manifest, keep the local result
        privacy["conflict"] = ["%s refused" % ("force_external" if args.force_external else "allow_external"),
                               "internal host"]
    if args.clear_cookies:
        clear_cookies(url)                     # explicit: forget this site's stored cookies
        _COOKIE_STATS["sent"] = _COOKIE_STATS["stored"] = 0
        _cookie_run_reset()
    deny_images = args.deny_images or "images" in SKIP or bool(local)   # a local read asks no network
    mode = mode_key(external_allowed, args.alternate, args.download, shots_want)
    hit = cached(url, args.refresh)

    known_images = {}
    if args.refresh:
        prev_imgs = hit[1] if hit else load_manifest(args.dir or page_dir(url))
        for e in (prev_imgs.get("images") or []):
            if isinstance(e, dict) and e.get("url"):
                known_images[e["url"]] = {"etag": e.get("etag") or "",
                                          "last_modified": e.get("last_modified") or "",
                                          "file": e.get("file") or ""}
    reread_in_place = False
    if hit and (hit[1].get("_mode") or "") != mode:
        reread_in_place = True        # same folder, different flags
        hit = None
    if hit:
        workdir, manifest = hit
        if args.dir and os.path.normcase(os.path.abspath(args.dir)) != os.path.normcase(os.path.abspath(workdir)):
            src, workdir = workdir, materialize(workdir, args.dir)     # --dir asked for a folder: honour it
            manifest["dir"] = workdir
            manifest["files"] = moved_files(manifest.get("files"), src, workdir)
        trace("cache", hit=1, dir=workdir, status=manifest.get("status"))
        manifest["elapsed_ms"] = int((now() - t0) * 1000)
        manifest["cache"] = "hit"
        manifest["privacy"] = dict(privacy)          # this call's flags, not the ones it was read with
        return finish(workdir, manifest, t0, args, (manifest.get("files") or {}).get("content"))

    c = caps()                             # a miss only: a cached answer never asks
    _CAPS_RUN["c"] = c                     # and once a run: the HTTP attempts take this one
    if debuglog.enabled():
        debuglog.log("caps", python=c.get("python"), libs=c.get("libs"),
                     cli={k: v for k, v in (c.get("cli") or {}).items() if v},
                     browsers=[{"name": b.get("name"), "kind": b.get("kind"), "path": b.get("path") or b.get("channel")}
                               for b in (c.get("browsers") or [])],
                     keys=sorted(k for k, v in (c.get("keys") or {}).items() if v),
                     ocr_langs=c.get("ocr_langs") or [], versions=lib_versions())
    if not VIDEO_URL.search(url) and not siteapi.which(url) and not re.search(
            r"(?i)\.(pdf|docx?|xlsx?|pptx?|epub|odt|rtf|zip|png|jpe?g|gif|webp|mp[34]|webm)$",
            urllib.parse.urlparse(url).path):
        # it loads while the HTTP request is in flight; not for a video, whose subtitles usually
        # need no extractor (on one weak core it slowed yt-dlp down); it starts later if they do
        defuddle_worker(wait=False)
    workdir = args.dir or page_dir(url)
    trace("dir", workdir=workdir, explicit=bool(args.dir), refresh=bool(args.refresh))
    os.makedirs(workdir, exist_ok=True)
    # The browser starts with the read only when it will surely be needed: a #/ route (only a
    # browser can read it), --screenshots, --alternate. Not for every read: on an emulated Celeron
    # a browser launching beside reads that never use it took them from 5.5 to 11.9 s (p50); on a fast
    # machine it would save 0.7 s. A wall or a shell starts it right after HTTP (below).
    early_render = None
    if (not local and (args.alternate or shots_want or re.search(r"#!?/", url)) and "browser" not in SKIP
            and not VIDEO_URL.search(url) and not re.search(
                r"(?i)\.(pdf|docx?|xlsx?|pptx?|epub|odt|rtf|zip|png|jpe?g|gif|webp|mp[34]|webm)$",
                urllib.parse.urlparse(url).path)):
        early_render = Background(render, url, c, shots_want, workdir)
    prev = load_manifest(workdir)
    prev_mode_ok = bool(prev) and (prev.get("_mode") or "") == mode
    validators = {}
    if args.refresh and prev_mode_ok and (prev.get("url") or {}).get("etag"):
        validators[url] = {"etag": prev["url"].get("etag") or "",
                           "last_modified": prev["url"].get("last_modified") or ""}
    if args.refresh:
        pass                               # revalidate in place; stale files are pruned at finish
    elif reread_in_place:
        clear_text_artifacts(workdir)      # new flags: new text, keep the downloaded files
    for sub in ("", "img"):                # a killed run must not leave a .part behind
        d = os.path.join(workdir, sub) if sub else workdir
        for stale in (os.listdir(d) if os.path.isdir(d) else []):
            if stale.endswith(".part") and within(workdir, os.path.join(d, stale)):
                try:
                    os.unlink(os.path.join(d, stale))
                except OSError:
                    pass
    manifest = {
        "schema": SCHEMA,
        "generator": "read-page",
        "_mode": mode,
        "_view": prev.get("_view") if prev.get("_view") in VIEWS else None,     # see answer_view
        "status": "error",
        "url": {"requested": url},
        "content": {},
        "candidates": [],
        "signals": {},
        "chain": {"tried": [], "skipped": []},
        "files": {},
        "missing": [],
        "improve": [],
        "advice": "",
        "cache": "miss",
        "privacy": dict(privacy),
    }

    # ---------------------------------------------------------------- video
    page_http = None                       # the page's own request, started beside a slower tier
    video_advice = ""                      # a video that gave no subtitles for a reason of its own: what to do
    if VIDEO_URL.search(url):
        # the watch page (its cover, or the page itself when there are no subtitles) comes in
        # while yt-dlp works: 1-2 s of a video read, no longer one after the other
        page_http = Background(fetch_http, url, args.download, workdir, validators)
        text, title, note = video_text(url, c, workdir)
        manifest["chain"]["tried"].append("video:yt-dlp")
        v_engine = "video:yt-dlp"
        track = note if text else ""                   # which subtitle track: the answer's first line names it
        ownenv.refresh_ytdlp()        # its own update, every few days, apart from this read (never pinned)
        if not text and _VIDEO["kind"] != "upcoming":
            # YouTube's own caption track by another road when yt-dlp got none or is not
            # installed - youtube-transcript-api (--setup's), else a machine's own markitdown. Not for a
            # video that has not started: no road has a track yet, and each costs seconds
            mt, why = transcript_video(url, workdir)
            if why or mt:
                manifest["chain"]["tried"].append("video:transcript-api")
            if mt:
                text, v_engine = mt, "video:transcript-api"
            else:
                mt, why = markitdown_video(url, c)
                if why or mt:
                    manifest["chain"]["tried"].append("video:markitdown")
                if mt:
                    text, v_engine = mt, "video:markitdown"
                    title = title or (re.search(r"(?m)^## (.+)$", mt) or [None, ""])[1].strip()
        if text:
            # the video's own cover on top of the transcript, as picture #1; the dozens of other
            # thumbnails on a watch page are not this text's. Video is touched only
            # lightly here; it gets its own pass later.
            vf = page_http.result()
            if vf.get("body") or vf.get("path"):
                v_html, _ = smart_decode(body_bytes(vf), vf["ct"])
                cover = page_meta_image(v_html)
                if cover:
                    text = "![%s](%s)\n\n%s" % (title or "cover", cover, text)
                    text, _ = picture_phase(text, "", "", vf["final"] or url, workdir, manifest, args, deny_images,
                                            page_private=bool(host_is_private(vf["final"] or url)))
            page_path = os.path.join(workdir, "page.md")
            content_path = os.path.join(workdir, "content.md")
            write_view(content_path, text)
            write_view(page_path, text)
            manifest["status"] = "ok"
            manifest["content"] = {"engine": v_engine, "chars": len(text),
                                   "words": len(text.split()), "title": title}
            if track and v_engine == "video:yt-dlp":
                manifest["content"]["track"] = track
            manifest["page"] = {"title": title} if title else {}
            manifest["files"] = {"content": content_path, "page": page_path}
            m, im = gaps(c, {"video": True, "need_browser": False})
            manifest["missing"] += m
            manifest["improve"] += im
            manifest["elapsed_ms"] = int((now() - t0) * 1000)
            store_cache(workdir, manifest, url)
            return finish(workdir, manifest, t0, args, manifest.get("files", {}).get("content"))
        # no subtitles: the page is still a page - a description, comments, a channel page.
        # It is read like any other below, and the manifest says why there is no transcript.
        manifest["signals"]["no_transcript"] = note
        video_advice = _VIDEO["advice"]
        fix = (ownenv.fix("yt-dlp", "pip install yt-dlp") if not c["cli"].get("yt-dlp")
               else _VIDEO["fix"] if _VIDEO["kind"] else "set READ_PAGE_SUB_LANGS")
        manifest["missing"].append(dict({"what": "transcript", "note": note}, **({"fix": fix} if fix else {})))

    # ---------------------------------------------------------------- the site's own API
    # Only where the ordinary path fails in measurements: Stack Exchange and npm answer with a wall,
    # Hacker News' page lacks the comments' text, X is a script shell, PubMed answers a client that
    # did not run its script with a cookie wall. The site's API answers first, with no flag
    # (fxtwitter learns only the post number, NCBI the record's); a failure is the
    # ordinary path. --alternate and --screenshots ask for the page itself.
    api_hit = None if (args.alternate or shots_want or "api" in SKIP) else siteapi.which(url)
    if api_hit:
        # not with the page's own request beside it: the API answers on its own nearly always,
        # and that request would be one more to the site and CPU on a weak laptop for nothing
        t_api, api_cap = now(), budget.cap(SITE_API_SECONDS, floor=1.0)
        got = siteapi.read(url, api_cap)
        budget.record("api:" + api_hit[0], t_api, "ok" if got else (
            budget.ended(SITE_API_SECONDS, api_cap) if now() - t_api >= api_cap - 0.3 else "fail"),
            own=SITE_API_SECONDS, given=api_cap)
        if not got:
            manifest["chain"]["tried"].append("api:%s:failed" % api_hit[0])
        else:
            md, aeng, raw_json = got
            # a post's photos, a README's diagrams: markers like any other text's
            md, _ = picture_phase(md, "", "", url, workdir, manifest, args, deny_images)
            content_path = os.path.join(workdir, "content.md")
            page_path = os.path.join(workdir, "page.md")
            raw_path = os.path.join(workdir, "raw.json")
            write_view(content_path, md)
            write_view(page_path, md)
            write_text(raw_path, raw_json)
            title = (re.search(r"(?m)^#\s+(.+)$", md) or [None, ""])[1].strip()
            manifest["status"] = "ok"
            manifest["url"]["final"] = url
            manifest["content"] = {"engine": aeng, "quality": "high", "chars": len(md), "words": len(md.split()),
                                   "headings": len(re.findall(r"(?m)^#{1,6}\s+\S", md)),
                                   "large": len(md) > 60000}
            manifest["page"] = dict({"canonical": url}, **({"title": title} if title else {}))
            manifest["files"] = {"content": content_path, "page": page_path, "raw": raw_path}
            manifest["chain"]["tried"].append(aeng)
            manifest["signals"]["status_reason"] = "%d words, engine %s" % (words_of(md), aeng)
            manifest["dir"] = workdir
            manifest["elapsed_ms"] = int((now() - t0) * 1000)
            store_cache(workdir, manifest, url)
            return finish(workdir, manifest, t0, args, content_path)

    # ---------------------------------------------------------------- HTTP
    gurl = google_export(url)
    if gurl:
        f = fetch_http(gurl, args.download, workdir)
        manifest["chain"]["tried"].append("google:export")
        bad = (not (f.get("body") or f.get("path"))) or bool(f["status"] and f["status"] >= 400) or \
            (f["ct"] or "").lower().startswith("text/html") or \
            "accounts.google.com" in (f["final"] or "")
        if bad:
            f2 = fetch_http(url, args.download, workdir)
            if f2.get("body") or f2.get("path"):
                f = f2
                manifest["chain"]["tried"].append("google:page")
    else:
        f = (read_local_file(local, workdir) if local else page_http.result() if page_http is not None
             else fetch_http(url, args.download, workdir, validators))
        manifest["chain"]["tried"].append(f["engine"] or "http")
    if f.get("not_modified") and prev_mode_ok:
        # the server hashed the page for us: nothing changed, the old answer is still true
        prev["cache"] = "revalidated"
        prev["signals"] = dict(prev.get("signals") or {}, revalidated=True)
        old_dir, prev["dir"] = prev.get("dir") or workdir, workdir
        prev["elapsed_ms"] = int((now() - t0) * 1000)
        prev["files"] = moved_files(prev.get("files"), old_dir, workdir)
        store_cache(workdir, prev, url)
        return finish(workdir, prev, t0, args, (prev.get("files") or {}).get("content"))
    if f.get("etag") or f.get("last_modified"):
        manifest["url"]["etag"] = f.get("etag") or ""
        manifest["url"]["last_modified"] = f.get("last_modified") or ""
    if f.get("scheme_upgrade"):
        manifest["chain"]["tried"].append("http→https")
    size = int(f.get("size") or len(f.get("body") or b""))
    manifest["url"].update(final=f["final"], http_status=f["status"], content_type=f["ct"],
                           bytes=size)
    if f.get("too_large"):
        size, limit = int(f.get("size") or 0), int(f.get("limit") or MAX_DOWNLOAD)
        manifest["status"] = "too_large"
        manifest["signals"]["limit"] = "the response is %s (%s bytes); the download cap is %s" % (
            human_bytes(size), exact_bytes(size), human_bytes(limit))
        manifest["advice"] = ("this URL serves more than %s; the cap keeps one call inside memory"
                              % human_bytes(limit))
        manifest["elapsed_ms"] = int((now() - t0) * 1000)
        store_cache(workdir, manifest, url)
        return finish(workdir, manifest, t0, args, None)
    if f.get("cut") == "disk":
        # --download has no size limit, the disk has one. What arrived is not kept:
        # a half file on a nearly full disk only makes it fuller
        if f.get("path") and os.path.exists(f["path"]):
            os.unlink(f["path"])
        manifest["status"] = "error"
        manifest["signals"]["status_reason"] = cut_said(f, size)
        manifest["advice"] = ("free some disk space and read again, or give --dir a folder on a disk with "
                              "room (the cache is in %s)" % cache_root())
        manifest["elapsed_ms"] = int((now() - t0) * 1000)
        return finish(workdir, manifest, t0, args, None)
    if f.get("partial"):
        manifest["signals"]["partial"] = True      # a body that arrived before a timeout
    if f.get("tls_unverified"):
        manifest["signals"]["tls"] = "certificate not trusted by this machine; the page was read unverified"
    trace("http", engine=f["engine"], status=f["status"], ct=f["ct"], bytes=size,
          disk=bool(f.get("path")), final=f["final"], error=f["error"], ms=f.get("ms"),
          partial=bool(f.get("partial")), cut=f.get("cut") or "", fallback=f.get("fallback") or "",
          tls_unverified=bool(f.get("tls_unverified")), https_upgrade=bool(f.get("scheme_upgrade")),
          expected=f.get("expected"), headers=f.get("headers") or {})
    network_fail = bool(not (f.get("body") or f.get("path")) and (f["error"] or not f["status"]))
    if network_fail:
        manifest["signals"]["network"] = f["error"] or "no response from the host"

    # ---------------------------------------------------------------- rescue tiers, at once
    # When HTTP's answer says the page will need rescuing, the next
    # tools start together instead of one after another - readers and the archive took 20 s each
    # in a row. Only on signals that make sure they are used: a dead host or a 5xx (readers and
    # the archive), a wall's status or header (readers, beside the browser), a 404 (the archive;
    # a reader then only confirms, and only with --refresh), --force-external (readers).
    early = {}
    if external_allowed:
        down = network_fail or (f["status"] or 0) >= 500
        walled = (f["status"] in (401, 403, 407, 419, 429, 451)
                  or bool(wall_signal(f.get("headers"), "", "", "", "", 0)))
        if down or walled or args.force_external:
            early["readers"] = Background(external_read, url, c, args.refresh)
        if down or f["status"] in (404, 410):
            early["archive"] = Background(archived_text, url, c, workdir)
        if early:
            trace("rescue.early", tiers=",".join(sorted(early)))

    kind, type_conflict = detect_kind(f.get("head") or body_bytes(f, 512), f["ct"],
                                      urllib.parse.urlparse(url).path)
    shot_entries, shot_needed, shot_why = [], 0, ""      # filled by the browser tier or by pdf_shots()
    if type_conflict:
        manifest["signals"]["type_conflict"] = True

    mkind = (media_kind(f.get("head") or body_bytes(f, 512), f["ct"],
                        urllib.parse.urlparse(url).path)
             if not network_fail and not (f["status"] or 0) >= 400 else "")
    if mkind:
        manifest["content"] = {"kind": mkind, "engine": "file", "chars": 0}
        if f.get("partial"):
            # a file cut in transit is not a file read: saved as `media_only` it was taken for the whole one, and a
            # video's cut ends where its bytes end (a fragmented MP4 - YouTube's DASH - then plays only as a
            # stream, the rest not at all). Said as a document's cut is, with what to do; what arrived is not kept
            cut_transfer(manifest, f, "image" if mkind == "image" else "%s file" % mkind)
            trace("media", kind=mkind, bytes=size, cut=f.get("cut") or "broken")
            if f.get("path") and os.path.exists(f["path"]):
                os.unlink(f["path"])
            manifest["elapsed_ms"] = int((now() - t0) * 1000)
            return finish(workdir, manifest, t0, args, None)
        if size > MEDIA_LIMIT and not args.download:
            content_path = os.path.join(workdir, "content.md")
            write_text(content_path, "This URL is a file of %s (%s, %s) and it is above the %s "
                                     "limit, so it was not saved.\nRerun with --download to take it."
                                     % (human_bytes(size), exact_bytes(size), mkind,
                                        human_bytes(MEDIA_LIMIT)))
            manifest["files"] = {"content": content_path}
            manifest["status"] = "too_large"
            trace("media", kind=mkind, bytes=size, oversize=1)
            manifest["signals"]["limit"] = "file is %s (%s bytes), above the %s limit" % (
                human_bytes(size), exact_bytes(size), human_bytes(MEDIA_LIMIT))
            manifest["advice"] = "rerun with --download to take the whole file"
        else:
            p = save_media(f, workdir, mkind)
            trace("media", kind=mkind, bytes=size, file=p)
            content_path = os.path.join(workdir, "content.md")
            write_text(content_path, media_note(p, mkind, size, f.get("ct") or ""))
            page_path = os.path.join(workdir, "page.md")
            write_text(page_path, media_note(p, mkind, size, f.get("ct") or ""))
            manifest["files"] = {"content": content_path, "page": page_path, "raw": p, "media": p}
            manifest["status"] = "media_only"
            manifest["advice"] = ""
        manifest["elapsed_ms"] = int((now() - t0) * 1000)
        store_cache(workdir, manifest, url)
        return finish(workdir, manifest, t0, args, None)

    raw_name, text, page_text, engine, visible, html = "raw.bin", "", "", "", None, ""
    route_skipped = False                  # a #/ route's landing page, left for the browser
    browser_inside = ""                    # where the browser reached inside, when its text was dropped
    visible_words = None
    rendered_pages = []
    no_text_layer = ""
    ocr_missing = []
    pdf_tables_wanted = 0          # pages that look like a table, on a machine without the model

    # an archive cut in transit is read as a cut archive is, from the members that arrived whole (it
    # was answered too_large or error with nothing read); the transfer's cut decides its status and
    # advice below when they hold few words
    transit = cut_said(f, size) if kind == "zip" and f.get("partial") and int(f.get("size") or 0) else ""
    if kind in ("pdf", "zip") and f.get("partial") and not transit:
        # a PDF cut by the step's bound is not mended: it needs its cross-reference table at
        # the end (arXiv: 0 pages from 10-75 % of the bytes). Why it was cut decides the status: a
        # file still arriving when the 20 s ran out is too big for one call (`too_large`); a
        # server that stopped sending, or a connection that broke, is a failure (`error`) - a
        # document stuck at 1 KB is not "too large".
        cut_transfer(manifest, f, "PDF" if kind == "pdf" else "document")
        if f.get("path") and os.path.exists(f["path"]):
            os.unlink(f["path"])
        manifest["elapsed_ms"] = int((now() - t0) * 1000)
        return finish(workdir, manifest, t0, args, None)
    if kind in ("pdf", "zip", "rtf"):
        if kind in ("pdf", "rtf"):
            raw_name = "raw." + kind
        else:
            sub = zip_subtype(f.get("path") or f.get("body") or b"")
            raw_name = "raw.%s" % (sub if sub != "other" else "zip")
        raw_path = take_body(f, os.path.join(workdir, raw_name))
        t_doc = now()
        text, note = doc_text(raw_path, kind, c, workdir, alternate=args.alternate)
        budget.record("document", t_doc, "ok" if text.strip() else "fail", own=CONVERTER_TIMEOUT,
                      note="%s, %d words%s" % (raw_name, len(text.split()), (", " + note) if note else ""))
        if shots_want and kind == "pdf":
            shot_entries, shot_needed = pdf_shots(raw_path, workdir, shots_want)
        elif shots_want and kind == "zip":
            # docx/xlsx/pptx/epub have no rendered pages: say it instead of returning nothing
            manifest["signals"]["screenshot_unsupported"] = (
                "this is an archive (docx/xlsx/pptx/epub); --screenshots covers pages and PDFs")
        broke = _ZIPS.get("read")              # an archive that does not open whole: what of it is
        read_path = (broke or {}).get("path") or raw_path
        manifest["chain"]["tried"].append("document:" + ("pymupdf" if kind == "pdf" else
                                                         "not-zip" if broke and broke["how"] == "not a ZIP"
                                                         else zip_subtype(read_path)))
        if tables_signal():
            # the layout model was asked, or pages were left for it (in a PDF of an archive too)
            manifest["chain"]["tried"].append("tables:pymupdf4llm")
        if broke:
            manifest["signals"]["broken_archive"] = dict(
                {k: broke[k] for k in ("how", "what", "all_members", "partial") if broke.get(k)},
                **({} if broke["how"] == "not a ZIP" else dict({
                    "members": broke["members"], "whole": len(broke["whole"]),
                    "not_whole": ["%s: %s" % b for b in broke["broken"][:20]]},
                    **({"lost_strings": broke["lost"]["cells"]} if (broke.get("lost") or {}).get("cells") else {}))))
        if kind in ("zip", "rtf"):
            # an archive's pictures, or the ones our RTF reader wrote out; the names of those left out
            left = {}
            zimg = zip_images(read_path, workdir, left=left) if kind == "zip" else \
                rtf_images(os.path.join(workdir, RTF_PICTURES), workdir, left)
            ordered = any(e.get("order") for e in zimg)
            # a picture the text names stands there; the rest follow in document order; a name inside
            # the document that has no picture here says why, and is never asked of the server
            text, zimg = doc_pictures(text, zimg, workdir, left)
            if zimg:
                manifest["images"] = zimg
                if ordered:
                    manifest["signals"]["images_ordered"] = True
        zip_copy_gone(broke)                   # read, its pictures too
        engine = "document"
        no_text_layer = note if "text layer" in note else ""
        if no_text_layer or note.startswith("no converter"):
            manifest["missing"].append({"what": "text layer" if no_text_layer else "converter", "note": note})
        elif note:
            # what a reader says of the document it read - parts it left out or could not unpack, a
            # table cut at its caps, pictures no browser or model shows, its time run out, its own
            # error: not a converter this machine lacks, which `missing: converter` had said
            manifest["signals"]["document_note"] = note[:400]
        if no_text_layer and kind == "pdf":
            rendered = render_pdf_pages(raw_path, workdir)
            if rendered:
                rendered_pages = rendered
                manifest["signals"]["scanned"] = True
                otext, oinfo = ocr_pages(rendered)
                ocr_missing = oinfo.get("missing") or []
                if oinfo.get("maybe") and not otext.strip():
                    # nothing came out of the scan, and the user's own language has no pack here
                    ocr_missing = ocr_missing + [x for x in oinfo["maybe"] if x not in ocr_missing]
                if oinfo.get("used"):
                    manifest["signals"]["ocr_langs"] = "+".join(oinfo["used"])
                if ocr_missing:
                    manifest["signals"]["ocr_missing_langs"] = ocr_missing
                if oinfo.get("timeouts"):
                    manifest["signals"]["ocr_timeouts"] = oinfo["timeouts"]
                    manifest["signals"]["partial"] = True     # a page is missing; the rest is kept
                if oinfo.get("error"):
                    manifest["signals"]["ocr_error"] = oinfo["error"]
                if otext.strip():
                    text = (text.strip() + "\n\n" + otext).strip() if text.strip() else otext
                    page_text = text
                    engine = "document:ocr"
                    manifest["signals"]["ocr_pages"] = min(len(rendered), OCR_MAX_PAGES)
                    manifest["chain"]["tried"].append("ocr:tesseract")
                    manifest["missing"][-1]["note"] = (
                        "no text layer: this PDF is a scan; the text comes from OCR of the "
                        "first %d pages" % min(len(rendered), OCR_MAX_PAGES))
                else:
                    manifest["missing"][-1]["note"] = (
                        "no text layer: this PDF is a scan; look at the rendered pages in "
                        "files.pages, or %s for OCR" % ownenv.fix("tesseract", "install tesseract"))
        page_text = text
    else:
        if size > MAX_PAGE_BYTES:
            # the file itself was downloaded whole (that is what --download promises); what is
            # impossible is holding a 100 MB+ document as one Python string
            manifest["status"] = "too_large"
            manifest["signals"]["limit"] = ("the page is %s (%s bytes); text parsing stops at %s"
                                            % (human_bytes(size), exact_bytes(size),
                                               human_bytes(MAX_PAGE_BYTES)))
            manifest["advice"] = ("the download is complete (raw.*), but this text is too big to "
                                  "parse in one piece")
            raw_path = take_body(f, os.path.join(workdir, "raw.html"))
            manifest["files"] = {"raw": raw_path}
            manifest["elapsed_ms"] = int((now() - t0) * 1000)
            store_cache(workdir, manifest, url)
            return finish(workdir, manifest, t0, args, None)
        body_bytes_all = body_bytes(f)
        decoded = decode_page(body_bytes_all, f["ct"])
        body_text = decoded.text
        note_charset(manifest, decoded)
        if looks_binary(f.get("head") or body_bytes_all[:4096]) and not looks_html(body_bytes_all):
            # not HTML, not a known format, mostly control bytes: nothing to read, say so
            manifest["signals"]["binary"] = True
            body_text = ""
        is_text = bool(f["ct"]) and any(x in f["ct"].lower() for x in ("markdown", "json", "plain", "xml"))
        if is_text and body_text.lstrip()[:1] != "<":
            raw_name = "raw.txt"
            text = body_text
            page_text = body_text
            engine = "server:" + f["ct"].split(";")[0].split("/")[-1]
            manifest["chain"]["tried"].append(engine)
        else:
            raw_name = "raw.html"
            html = body_text
            vis_text = visible_text(html)
            visible, visible_words = len(vis_text), len(vis_text.split())
            if visible < 400:
                # A stub that only says "it moved": the status was 200, so the redirect is ours to
                # follow. One hop, checked like any other redirect (a public page stays public).
                hop = meta_refresh_target(html, f["final"] or url)
                if hop and hop != (f["final"] or url) and not hop_refused(f["final"] or url, hop):
                    nxt = fetch_http(hop, args.download, workdir)
                    if nxt.get("body") or nxt.get("path"):
                        trace("meta.refresh", url=hop[:120])
                        manifest["signals"]["meta_refresh"] = hop
                        manifest["chain"]["tried"].append("meta-refresh")
                        f = nxt
                        html = smart_decode(body_bytes(f), f.get("ct"))[0]
                        vis_text = visible_text(html)
                        visible, visible_words = len(vis_text), len(vis_text.split())
            # a wall says it in a header, its markup, its title/heading, or is a short page with
            # the words in it; prose that quotes the same words keeps its own title and runs long
            wall_seen = wall_signal(f.get("headers"), html, title_of(html), first_heading(html),
                                    vis_text, words_of(vis_text))
            looks_blocked = bool(wall_seen)
            looks_shell = visible < 300 and len(re.findall(r"(?i)<script\b", html)) >= 3
            # a few words and a script, and not a 404/410/5xx: the browser reads it whatever the
            # extractors find. crates.io and AliExpress have two scripts, Telegram one, so they are
            # no shell above; their browser waited 0.6-1.2 s on a fast machine, 2.4-3.4 s on a weak laptop, for
            # three extractors to find nothing in 1-5 KB
            dead = (f["status"] in (404, 410) or (f["status"] or 0) >= 500) and not looks_blocked
            tiny_app = visible < 300 and not dead and bool(re.search(r"(?i)<script\b", html))
            # the browser will surely be needed: it starts now, beside the extraction
            if early_render is None and not local and "browser" not in SKIP and not f.get("partial") and (
                    looks_shell or tiny_app or STATIC_SHELL.search(html[:200000])
                    or (looks_blocked and visible < 400)):
                early_render = Background(render, url, c, shots_want, workdir,
                                          bool(looks_blocked or (f["status"] or 0) >= 400))
            if debuglog.enabled():
                static_hit = bool(STATIC_SHELL.search(html[:200000]))
                debuglog.log("decide", what="after HTTP", status=f["status"], html_chars=len(html),
                             visible_chars=visible, visible_words=visible_words,
                             scripts=len(re.findall(r"(?i)<script\b", html)), wall=str(wall_seen or ""),
                             shell=looks_shell, tiny_app=tiny_app, dead=dead, static_shell=static_hit,
                             route=bool(re.search(r"#!?/", url)), early_browser=early_render is not None,
                             why=("a shell: under 300 characters and 3+ scripts" if looks_shell else
                                  "a tiny page with a script" if tiny_app else
                                  "an empty mount node or a Loading... placeholder" if static_hit else
                                  "a wall with under 400 characters" if (looks_blocked and visible < 400) else
                                  "started with the read" if early_render is not None else "no early browser"))
            if (looks_shell and not looks_blocked) or (early_render is not None and re.search(r"#!?/", url)):
                # a shell has no text to extract; a *wall* does - "Just a moment..." is content the
                # caller is entitled to see, and skipping it left an empty answer when the browser
                # tier then failed. A #/ route's HTTP text is the landing page, which the
                # browser's replaces: not extracted while the browser works
                manifest["chain"]["skipped"].append({
                    "tier": "extract", "why": "javascript shell" if looks_shell else "a #/ route: the browser reads it"})
                route_skipped = not looks_shell
            elif not html.strip():
                # nothing arrived (a host that did not answer): no extractor has anything to read,
                # and three of them cost a second on a fast machine, three on a weak laptop
                manifest["chain"]["skipped"].append({"tier": "extract", "why": "no body"})
            else:
                text, engine, cands, page_text = extract(
                    html, f["final"] or url, c, workdir, want_all=args.alternate,
                    after=_BROWSER_UP if early_render is not None else None)
                trace("extract", engine=engine, chars=len(text),
                      cands=",".join("%s:%d" % (k, len(v)) for k, v in (cands or {}).items()),
                      visible=visible)
                manifest["chain"]["tried"].append("extract:" + (engine or "none"))
                manifest["candidates"] = [{"engine": k, "chars": len(v)} for k, v in cands.items()]
                if _DD.pop("late", False):
                    manifest["signals"]["extract_late"] = ("defuddle did not finish before the read's "
                                                           "deadline; the text is the whole page")
                if engine == "full" and not args.alternate and is_huge(html):
                    manifest["signals"]["huge"] = (
                        "the page is %s of HTML; above %s its whole text is the answer and no "
                        "extractor runs (--alternate runs them)" % (human_bytes(len(html)), human_bytes(HUGE_HTML)))
                if args.alternate and cands:
                    clean = {k: v for k, v in cands.items() if k != "full"} or cands
                    engine = max(clean, key=lambda k: len(clean[k]))
                    text = cands[engine]

    # ---------------------------------------------------------------- signals
    # Thresholds are word-based and look at the title/heading, not at raw length. Measured
    # failure of the old character thresholds: a 51-character status page became `empty`, a
    # 781-character article about 404s became `not_found`, a 688-character page quoting
    # "access denied" became `blocked`, and a newsletter form became `login_required`.
    title = title_of(html)
    h1 = first_heading(html)
    word_count = words_of(text)
    # which tier's text the answer is and what that tier was told: `ok` needs a successful answer
    # from it. The browser, an archive or a reader may replace the HTTP text below.
    source, source_code = "http", f["status"]
    code_from = ""                                     # set when the code is not the text tier's own
    wall_http = wall_signal(f.get("headers"), html, title, h1, text, word_count)
    block_words = bool(wall_http)
    blocked_http = bool(f["status"] in (401, 403, 407, 419, 429, 451) or wall_http)
    if blocked_http:
        manifest["signals"]["blocked_http"] = True
    if f["status"] and f["status"] >= 400:
        manifest["signals"]["http_status"] = f["status"]
    if f["status"] in (404, 410) or (f["status"] == 200 and soft_404_marker(title, h1, text, word_count)):
        manifest["signals"]["soft_404"] = True


    # ---------------------------------------------------------------- render
    is_page = kind in ("", "html")
    # A #/ or #! address is a route the server never sees: only a browser can read it. A
    # static page whose mount node is empty or says "Loading..." will be filled later, however
    # long its menu is. A transfer the server itself cut (a trickle, a stall) is not a shell:
    # the browser would wait for the same slow server, so it runs only when asked.
    # A page without a single script cannot change in a browser (a static page, an RFC): its short
    # text is all there is, and 4 of 22 browser runs in measurements were such pages. A wall
    # still goes to the browser (its challenge may pass there), and so does an empty mount node (a
    # members-only shell renders once the browser's second request carries the cookie).
    hash_route = bool(re.search(r"#!?/", url)) and is_page
    static_shell = bool(html and STATIC_SHELL.search(html[:200000]))
    has_scripts = bool(html and re.search(r"(?i)<script\b", html))
    thin_app = bool(html and is_page and has_scripts and len(text) >= 400 and word_count < THIN_APP_WORDS
                    and shipped_state(html) >= THIN_APP_STATE)
    weak_http = bool(html and not network_fail and not f.get("partial") and (
        static_shell or len(text) < 400 or thin_app
        or ((visible or 0) > 3000 and len(text) < (visible or 0) * 0.05)))
    # a 404, 410 or 5xx is the server's answer, and a browser gets the same one (a 404 took 4.4 s
    # of browser for its error page); the archive and the readers are the rescue there - unless
    # the answer is a wall's challenge, which may pass in a browser
    dead_answer = (f["status"] in (404, 410) or (f["status"] or 0) >= 500) and not wall_http
    text_reason = bool(hash_route or (weak_http and not dead_answer and (has_scripts or static_shell or blocked_http)))
    need_browser = not local and ((bool(shots_want) and is_page and not network_fail) or args.alternate or (
        bool(html) and not network_fail and text_reason))
    if debuglog.enabled():
        debuglog.log("decide", what="browser needed", need=need_browser, http_chars=len(text or ""),
                     http_words=words_of(text), visible_chars=visible, weak_http=weak_http,
                     weak_why=("" if not weak_http else "an empty mount node or a Loading... placeholder" if static_shell
                               else "text under 400 characters" if len(text) < 400
                               else "under %d words beside the data the page ships for its scripts" % THIN_APP_WORDS
                               if thin_app else "text under 5 % of the visible page"),
                     has_scripts=has_scripts, wall_http=str(wall_http or ""), blocked_http=blocked_http,
                     dead_answer=dead_answer, route=hash_route, text_reason=text_reason, screenshots=shots_want,
                     alternate=bool(args.alternate), network_fail=network_fail, partial=bool(f.get("partial")),
                     early=early_render is not None)
    if early_render is not None and not need_browser:
        _RENDER_STOP.set()                 # started on a signal, not needed after all: no screenshots,
        del _BROWSER_THREADS[:]            # and the exit does not wait for it
    if weak_http and not need_browser:
        manifest["chain"]["skipped"].append({"tier": "browser", "why": (
            "HTTP %s: the server's own answer" % f["status"]) if dead_answer else "no script on the page"})
    if need_browser:
        r, err = early_render.result() if early_render is not None else render(
            url, c, shots=shots_want, shot_dir=workdir, wall=bool(blocked_http))
        trace("render", ok=bool(r), engine=(r or {}).get("engine"), err=err, waited=(r or {}).get("waited"))
        if r and r.get("inside"):
            # the request rule saw only a redirect chain's first URL, and its watch saw a response
            # from inside the network: whatever came from there may be in the DOM, so none of it is
            # used (netguard, the usual way out, refuses such a connection before it opens)
            manifest["chain"]["tried"].append(r["engine"])
            browser_inside = ", ".join(sorted({urllib.parse.urlparse(u).netloc for u in r["inside"]}))[:120]
            manifest["chain"]["skipped"].append({"tier": "browser", "why": (
                "the page reached into the local network (%s); its text is not used"
                % ", ".join(debuglog.mask_url(u)[:80] for u in r["inside"][:3]))})
            manifest["signals"]["browser_blocked"] = len(r.get("blocked") or []) + len(r["inside"])
            manifest["signals"]["browser_inside"] = browser_inside
            shot_entries, shot_needed = [], 0
            shot_why = "the page reached into the local network; its screens are not used" if shots_want else ""
        elif r and r.get("error_page"):
            # Chrome's own page ("This site can't be reached", ERR_..., HTTP ERROR 503) is not the
            # site's: never its text
            manifest["chain"]["tried"].append(r["engine"])
            manifest["chain"]["skipped"].append({"tier": "browser", "why": "error page: " + r["error_page"]})
            manifest["signals"]["render_error"] = r["error_page"]
            if r.get("status"):
                manifest["signals"]["render_status"] = r["status"]
            if r.get("blocked"):
                manifest["signals"]["browser_blocked"] = len(r["blocked"])
            shot_entries, shot_needed, shot_why = r.get("shots") or [], r.get("shots_needed") or 0, r.get("shots_why") or ""
        elif r:
            manifest["chain"]["tried"].append(r["engine"])
            vis2 = visible_text(r["html"])
            visible2, words2 = len(vis2), len(vis2.split())
            t2, eng2, cands2, page2 = extract(r["html"], r.get("final") or url, c, workdir, inner=r.get("inner"),
                                              page_html=r.get("visible") or "", want_all=args.alternate)
            b_words = words_of(t2)
            b_wall = wall_signal({}, r["html"], title_of(r["html"]), first_heading(r["html"]), t2, b_words)
            if args.alternate:
                take = len(t2) > len(text)           # every means, the fullest text
            elif hash_route:
                take = bool(t2.strip())              # the route's text; the HTTP text is the landing page
            elif text_reason:
                # the browser ran because the HTTP text was weak, so its text replaces it - unless it
                # is a wall the HTTP text was not (openai, apnews: a bot check in the browser where
                # curl had the page) or has fewer words. Length decides nothing else: where both
                # texts were good, "longer wins" chose wrong in 3 of 6 real differences.
                # A wall from the browser stays out only when HTTP had a real text: an empty shell
                # whose browser met a 403 is a wall, not an empty page (figma)
                take = (bool(t2.strip()) and (not b_wall or bool(wall_http) or len(text) < 400)
                        and b_words >= word_count)
            else:
                take = False                         # screenshots only: the HTTP text stays
            if debuglog.enabled():
                debuglog.log("decide", what="browser text", take=take, browser_words=b_words, http_words=word_count,
                             browser_chars=len(t2), http_chars=len(text or ""), browser_wall=str(b_wall or ""),
                             http_wall=str(wall_http or ""), engine=eng2, render_status=r.get("status"),
                             landed=debuglog.mask_url(r.get("final") or ""), waited=r.get("waited"),
                             rule=("alternate: the fuller text" if args.alternate else "a #/ route: the route's text"
                                   if hash_route else "the HTTP text was weak" if text_reason else "screenshots only"))
            if take:
                text, engine, page_text, html, visible = t2, eng2, page2, r["html"], visible2
                visible_words = words2
                source, source_code = "browser", r.get("status")
                if source_code is None and f["status"]:
                    # Chrome's --dump-dom (no Playwright) knows no HTTP status: the server's answer to
                    # the same address stands - a 419 "Sorry." page was `empty`, not `blocked`
                    source_code, code_from = f["status"], "http"
                manifest["signals"].pop("partial", None)   # the HTTP cut no longer describes the text
                manifest["candidates"] = [{"engine": k, "chars": len(v)} for k, v in cands2.items()]
            if r.get("status"):
                manifest["signals"]["render_status"] = r["status"]
            if r.get("partial"):
                manifest["signals"]["render_partial"] = True
            shot_entries, shot_needed, shot_why = r.get("shots") or [], r.get("shots_needed") or 0, r.get("shots_why") or ""
            if r.get("waited"):
                manifest["signals"]["browser_waited"] = r["waited"]
            if r.get("blocked"):
                manifest["signals"]["browser_blocked"] = len(r["blocked"])
            if not take and text_reason and not args.alternate:
                manifest["chain"]["skipped"].append({"tier": "browser", "why": (
                    "its text is a wall the HTTP text was not" if b_wall and not wall_http else
                    "its text has fewer words than the HTTP text")})
        else:
            manifest["chain"]["skipped"].append({"tier": "browser", "why": err})

    if route_skipped and not (text or "").strip() and html:
        # the browser did not read the route (none would start, or it failed): the landing page
        # is still better than nothing, and the answer says it is the server's page
        text, engine, cands, page_text = extract(html, f["final"] or url, c, workdir)
        manifest["chain"]["tried"].append("extract:" + (engine or "none"))
        manifest["candidates"] = [{"engine": k, "chars": len(v)} for k, v in cands.items()]

    # ---------------------------------------------------------------- archive first for dead pages
    # a 404 is not a wall: the archived copy is free and usually right, a reader would cost a credit
    archive_tried = False                  # one archive step per run: it may take 20 s
    if (manifest["signals"].get("soft_404") and external_allowed and f["status"] in (404, 410)):
        archive_tried = True
        t3, eng3, page3, a_html, ats, aeng = (early.pop("archive").result() if "archive" in early
                                              else archived_text(url, c, workdir))
        manifest["chain"]["tried"].append(aeng)
        if t3:
            if len(t3) > len(text):
                text, engine, page_text, html = t3, eng3 + "(" + str(ats) + ")", page3, a_html
                source, source_code = "archive", 200
                manifest["signals"].pop("partial", None)
                if aeng.endswith(":partial"):
                    manifest["signals"]["partial"] = True     # the snapshot was cut, kept as is
                vis3 = visible_text(a_html) if a_html else t3
                visible, visible_words = len(vis3), len(vis3.split())
                manifest["archive"] = {"engine": "wayback", "timestamp": str(ats),
                                       "url": "https://web.archive.org/web/%s/%s" % (ats, url),
                                       "why": "the live page answered %s" % (f["status"] or "nothing")}
                manifest["signals"]["archived"] = str(ats)

    # ---------------------------------------------------------------- external
    # A host that did not answer, or answered 5xx, goes to the readers and then the archive when
    # that is allowed: a reader's own copy or the archive often has the page (dmoz.org is
    # dead, Jina still has it; lib.ru was down and readable). The readers' step is bounded (20 s),
    # so the minute velosite.ru once cost is no longer a risk.
    server_down = bool(network_fail or (f["status"] or 0) >= 500)
    want_external = external_allowed and (
        server_down or blocked_http or block_words or len(text) < 400 or
        manifest["signals"].get("soft_404") or args.force_external)
    if want_external and (not manifest["signals"].get("archived") or args.refresh):
        ext, eeng, est, enote = (early.pop("readers").result() if "readers" in early
                                 else external_read(url, c, refresh=args.refresh))
        if manifest.get("archive"):
            # the archive is already the answer; the reader only tells us what the live page does
            # now. 404/410 there confirms the archive is all there is, and we say so.
            manifest["archive"]["checked_live"] = {"engine": eeng,
                                                   "status": est,
                                                   "result": "gone" if est in (404, 410) or not ext
                                                   else "text available"}
            if ext and len(ext) > len(text):
                text, engine = ext, eeng
                page_text = page_text or ext
                source, source_code = "reader", est or 200
                manifest["signals"].pop("partial", None)
                if (enote or "").startswith("cut:"):
                    manifest["signals"]["partial"] = True   # a slow reader, its text kept
                manifest["archive"]["superseded_by"] = eeng
        manifest["chain"]["tried"].append(eeng)
        if ext and len(ext) > len(text):
            text, engine = ext, eeng
            page_text = page_text or ext
            source, source_code = "reader", est or 200
            manifest["signals"].pop("partial", None)
            if (enote or "").startswith("cut:"):
                manifest["signals"]["partial"] = True       # a slow reader, its text kept
        if est and est >= 400:
            manifest["signals"]["external_status"] = est
        if not ext:
            manifest["signals"]["external"] = enote or "no reader produced text"
    elif blocked_http and not external_allowed:
        manifest["chain"]["skipped"].append({"tier": "external", "why": "sensitive: " + manifest["privacy"]["why"]})

    # ---------------------------------------------------------------- archive
    still_down = server_down and source == "http"          # no reader rescued it
    if (external_allowed and not archive_tried and not manifest["signals"].get("archived")
            and ((manifest["signals"].get("soft_404") and (f["status"] in (404, 410) or len(text) < 1000))
                 or still_down)):
        t3, eng3, page3, a_html, ats, aeng = (early.pop("archive").result() if "archive" in early
                                              else archived_text(url, c, workdir))
        manifest["chain"]["tried"].append(aeng)
        if t3:
            if len(t3) > len(text) or still_down:
                text, engine, page_text, html = t3, eng3 + "(" + str(ats) + ")", page3, a_html
                source, source_code = "archive", 200
                manifest["signals"].pop("partial", None)
                if aeng.endswith(":partial"):
                    manifest["signals"]["partial"] = True     # the snapshot was cut, kept as is
                vis3 = visible_text(a_html) if a_html else t3
                visible, visible_words = len(vis3), len(vis3.split())
                manifest["archive"] = {"engine": "wayback", "timestamp": str(ats),
                                       "url": "https://web.archive.org/web/%s/%s" % (ats, url),
                                       "why": "the live page answered %s" % (f["status"] or "nothing")}
                manifest["signals"]["archived"] = str(ats)

    if source in ("reader", "archive") and server_down:
        # the text is a rescue because the live page did not answer, or answered 5xx, which may be
        # over in a minute: the cache keeps it a minute, not fifteen (runoob timed out
        # once, and every read for 15 minutes got the archive copy of January)
        manifest["signals"]["rescued_after"] = ("no answer" if network_fail
                                                else "HTTP %s" % (f["status"] or "?"))

    # ---------------------------------------------------------------- dropped blocks
    # The extractor only suggests: a paragraph, code, a table or a captioned figure of page.md
    # that it threw away goes back after its kept neighbour (Python's tutorial lost all of 3.1),
    # and so do the pictures of the blocks shown. Menus, link lists, fragments and
    # banners stay in page.md, and the header says how much.
    pic_base = image_base(html, f["final"] or url) if html else (f["final"] or url)
    text = inline_svg_text(text)
    restored = {}
    if (html and text and page_text and source in ("http", "browser", "archive")
            and str(engine or "").split("(")[0].split(":")[0] in EXTRACTORS):
        t_bl = now()
        text, restored = blockrule.restore(text, page_text, base=pic_base)
        budget.record("blocks", t_bl, note="+%d blocks" % (restored.get("restored") or 0))
        if restored.get("restored") or restored.get("pictures"):
            manifest["chain"]["tried"].append("blocks:+%d" % (restored.get("restored") or 0))

    # ---------------------------------------------------------------- pictures
    # The last step on any path - the extractor's text, a reader's, the archive's: each picture
    # link becomes a numbered marker in its place, and the text's pictures are downloaded within
    # 6 s (--download: every picture of the page, no limit). page.md's own pictures come when
    # page.md is printed (finish()).
    text, page_text = picture_phase(text, page_text, html, pic_base, workdir, manifest, args, deny_images,
                                    known=known_images, page_private=bool(host_is_private(f["final"] or url)))

    # ---------------------------------------------------------------- artefacts
    manifest["page"] = page_meta(html, url)
    # words, not characters: a page with 10 000 short comments used to look like a fragment
    text_words = len((text or "").split())
    cover = round(min(1.0, text_words / visible_words), 3) if visible_words else None
    # "fragment" means more content exists that we did not take. A low cover alone is not enough:
    # nav-heavy pages (github trending, k8s docs) keep 10-30 % of the visible text legitimately.
    # So require either a single clean extractor, or extractors disagreeing by ~2x.
    # Conservative on purpose: a false "fragment" costs one read of page.md (a file already on
    # disk), a missed fragment costs a wrong answer. extractors_agree is extra context, not a gate.
    clean = sorted((c.get("chars") or 0) for c in manifest.get("candidates") or []
                   if c.get("engine") not in ("full", "crude"))
    agree = bool(len(clean) >= 2 and clean[-1] / max(1, clean[-2]) < 1.8)
    fragment = bool(cover is not None and cover < 0.35 and len(text) > 200)
    js_shell = bool(html and len(text) < 400 and (visible or 0) > 500)
    if blocked_http and source != "http":
        manifest["signals"]["note"] = "the HTTP tier was blocked; the %s produced this text" % (
            SOURCE_NAMES.get(source, source))
    elif server_down and source != "http":
        manifest["signals"]["note"] = "the host %s; the %s produced this text" % (
            "did not answer" if network_fail else "answered %s" % f["status"], SOURCE_NAMES.get(source, source))
    # recompute from the *final* text: a render or a reader may have replaced the first candidate
    # (medium.com: the wall page was skipped as blocked, the browser then produced the same wall,
    # and the earlier flag no longer described the text we are about to return). A challenge says
    # it in a header, its markup, its <title> or <h1> ("Just a moment...") or is only a few words;
    # a page *about* walls quotes the same strings in prose and runs long.
    word_count = words_of(text)
    wall_why = wall_signal(f.get("headers") if source == "http" else {}, html,
                           title_of(html) if html else title, first_heading(html) if html else h1,
                           text, word_count)
    by_code = code_status(source_code)
    # the same, from the final text: a page that is a script's shell to the server and says "page
    # not found" only once the browser has drawn it (Kinopoisk, Taobao, Tencent) has no marker in
    # the first text
    soft_final = bool(source in ("http", "browser") and source_code == 200 and html
                      and soft_404_marker(title_of(html), first_heading(html), text, word_count))
    if soft_final:
        manifest["signals"]["soft_404"] = True
    if wall_why:
        manifest["signals"]["block_text"] = True      # the status came from the page, not the code
    manifest["signals"]["blocked"] = bool(wall_why) or by_code == "blocked"

    raw_path = os.path.join(workdir, raw_name)
    if html:
        write_text(raw_path, html)
    elif (f.get("body") or f.get("path")) and kind not in ("pdf", "zip"):
        raw_path = take_body(f, raw_path)

    content_path = os.path.join(workdir, "content.md")
    write_view(content_path, text or "")
    page_path = os.path.join(workdir, "page.md")
    # page.md is the whole page; the text stands in only when it is no page (a script shell the
    # browser filled, a site API's own page): fewer than half the text's words. Characters were
    # compared before, and the text's long absolute links made 7 HTML pages of a measured run
    # (SQLite, namu.wiki, opennet...) lose their menus and links to a copy of the text.
    whole = bool(page_text) and (len(page_text) >= len(text or "")          # no counting on a 16 MB spec
                                 or len(blockrule.words(page_text)) * 2 >= len(blockrule.words(text or "")))
    write_view(page_path, page_text if whole else (text or ""))

    quality = {"defuddle": "high", "trafilatura": "high", "readability": "medium",
               "lynx": "medium", "w3m": "medium",
               "crude": "low", "full": "low"}.get((engine or "").split(":")[0], "high")
    manifest["content"] = {
        "engine": engine,
        "quality": quality,
        "chars": len(text or ""),
        "words": len((text or "").split()),
        "headings": len(re.findall(r"(?m)^#{1,6}\s+\S", text or "")),
        "cover": cover,
        "large": len(text or "") > 60000,
    }
    if restored.get("restored"):
        manifest["content"].update(restored=restored["restored"], restored_bytes=restored["restored_bytes"])
    if restored.get("outside"):
        manifest["content"]["outside"] = restored["outside"]
    manifest["signals"].update({"fragment": fragment, "js_shell": js_shell})
    if len(clean) >= 2:
        manifest["signals"]["extractors_agree"] = agree
    manifest["files"] = {"content": content_path, "page": page_path, "raw": raw_path}
    apply_shots(manifest, workdir, shot_entries, shot_needed, shot_why)
    if rendered_pages:
        manifest["files"]["pages"] = rendered_pages
    manifest["dir"] = workdir

    # ---------------------------------------------------------------- login
    state, why = login_state(html, text, f["status"], f["final"], url)
    trace("login", state=state or "-", why=why)
    if state == "weak":
        manifest["signals"]["login_hint"] = why
    pay_why = paywall_signal(html) if is_page and html else ""

    # ---------------------------------------------------------------- a PDF's tables
    # the read's documents together - the PDF itself, the PDFs of an archive, an archived copy:
    # the pages laid out, those left with why, the model's seconds, its error
    tables_said = tables_signal()
    if tables_said:
        manifest["signals"]["tables"] = tables_said
        if "tables:pymupdf4llm" not in manifest["chain"]["tried"]:
            manifest["chain"]["tried"].append("tables:pymupdf4llm")
    pdf_tables_wanted = _PDF.get("wanted") or 0

    # ---------------------------------------------------------------- status, advice
    # `ok` needs a successful answer from the tier whose text this is: an error page's
    # own words are kept and shown, but a 500 with 200 words of apology is not the page.
    # A document's words are its own: the markers of its pictures and the list of those with no place
    # in the text are this skill's (a deck whose slides were all lost was `ok` on its 9 pictures' 60)
    doc_engine = str(engine or "").startswith("document")
    word_count = words_of(pictures.unmarked(text) if doc_engine else text)
    cut = bool(manifest["signals"].get("partial"))
    error_why = ""
    # an archive that is cut, damaged or no ZIP at all: what was read of it is the text
    broke = _ZIPS.get("read") if kind == "zip" and source == "http" else None
    complete = bool(broke and broke.get("all_members") and not broke.get("broken"))   # only its index is broken
    if broke and (broke.get("lost") or {}).get("cells"):
        # a cut workbook's cells whose text was lost read LOST_TEXT: the skill's words, not the document's
        word_count = words_of((pictures.unmarked(text) if doc_engine else text).replace(LOST_TEXT, " "))
    if network_fail and source == "http":          # no reader or archive answered for it
        manifest["status"] = "error"
        error_why = "the host did not answer" + (": " + str(f.get("error"))[:160] if f.get("error") else "")
    elif cut and word_count < 40 and transit and f.get("cut") == "step":
        # an archive still arriving when its time ran out, its whole members a few words: too big for one call
        manifest["status"] = "too_large"
        manifest["signals"]["limit"] = "the document was still arriving when the time for it ran out (%d s): %s" % (
            int(round((f.get("ms") or 0) / 1000.0)), cut_said(f, size).split(" after ", 1)[-1])
    elif cut and word_count < 40:
        # a few words and a broken connection are not a page
        manifest["status"] = "error"
        error_why = "%s; what arrived is a stub" % cut_said(f, size)
    elif state in ("strong", "medium") and word_count < 200:
        manifest["status"] = "login_required"
    elif by_code == "login_required":
        manifest["status"] = "login_required"
        why = why or "HTTP %s" % source_code
    elif manifest["signals"]["blocked"]:
        manifest["status"] = "blocked"
    elif (f["status"] in (404, 410) and not manifest.get("archive")) or by_code == "not_found":
        # a real 404 is a 404 whatever the size of its error page: python.org answers with a
        # 3 200-character navigation frame, and the listing fallback happily extracted it.
        # With a working archive copy the page *is* readable, and `archive` says where it came from.
        manifest["status"] = "not_found"
    elif soft_final or (manifest["signals"].get("soft_404") and word_count < SOFT_404_WORDS):
        manifest["status"] = "not_found"
    elif by_code == "error":
        manifest["status"] = "error"
        error_why = "HTTP %s from the %s; its own page is the text" % (source_code, SOURCE_NAMES.get(code_from or source, source))
    elif broke and broke["how"] != "not a ZIP" and word_count < 40 and not complete:
        # the members that are whole hold a few words or none: not the document (40, as a transfer cut)
        manifest["status"] = "error"
        error_why = broke["reason"]
    elif not (text or "").strip():
        manifest["status"] = "empty"
    elif word_count < 5 and not str(engine or "").startswith("server:") and not (doc_engine and word_count):
        # a five-word HTML page is a shell or an error stub; a short answer from a JSON/text
        # API *is* the answer (a DOI resolver returns 143 characters of citation metadata), and so
        # are a document's few words of its own (a DOCX that is one formula: `E = mc^2`)
        manifest["status"] = "empty"
    else:
        manifest["status"] = "ok"

    if pay_why and manifest["status"] == "ok":
        # the text is there and may be cut: a signal, and the advice says so; not a wall
        manifest["signals"]["paywall"] = pay_why
    reasons = {
        "error": error_why or "the host did not answer",
        "login_required": "a login was detected: " + (why or "account wall"),
        "blocked": wall_why or "HTTP %s from the %s" % (source_code, SOURCE_NAMES.get(code_from or source, source)),
        "not_found": ("HTTP %s" % f["status"]) if f["status"] in (404, 410)
                     else "the text says the page is not there",
        "empty": ("binary body" if manifest["signals"].get("binary") else
                  broke["reason"] if broke else ("no text found (%d words)" % word_count)),
        "media_only": "the URL is a file, not a page",
        "too_large": ((manifest["signals"].get("limit") or "over the limit")),
        "ok": "%d words, engine %s" % (word_count, engine or "?"),
    }
    manifest["signals"]["status_reason"] = reasons.get(manifest["status"], "")
    if debuglog.enabled():
        debuglog.log("decide", what="status", status=manifest["status"], reason=manifest["signals"]["status_reason"],
                     words=word_count, source=source, source_code=source_code, by_code=by_code, engine=engine,
                     network_fail=network_fail, cut=cut, login=state or "", login_why=why or "",
                     blocked=bool(manifest["signals"].get("blocked")), soft_404=bool(manifest["signals"].get("soft_404")),
                     archive=bool(manifest.get("archive")))
    # what this read has done already: the advice names no step that would only repeat it
    browser_ran = any(str(t).startswith("browser") for t in manifest["chain"]["tried"])
    readers_ran = any(str(t).startswith("reader:") for t in manifest["chain"]["tried"])
    browser_here = bool(c.get("browsers")) and "browser" not in SKIP and not local
    if manifest.get("archive"):
        a = manifest["archive"]
        ts = str(a.get("timestamp") or "")
        day = "%s-%s-%s" % (ts[:4], ts[4:6], ts[6:8]) if len(ts) >= 8 else ts
        live = (a.get("checked_live") or {}).get("result")
        # "gone" only for a 404/410: a page that did not answer, or answered 5xx, may be back in a
        # minute, and the agent should know --refresh asks it (runoob "gone" after a timeout)
        gone = f["status"] in (404, 410)
        state = ("is gone (HTTP %s)" % f["status"] if gone else "did not answer" if network_fail
                 else "answered HTTP %s" % (f["status"] or "?"))
        manifest["advice"] = ("the live page %s; this text is the %s archive copy of %s%s%s"
                              % (state, a.get("engine", "web"), day,
                                 "; a fresh reader also found nothing" if live == "gone" else "",
                                 "" if gone else "; --refresh asks the live page again"))
    elif browser_inside and source in ("http", "browser"):
        # the browser's text was dropped for the user's safety: say it outright, and what
        # reads the page another way - a remote reader has no local network to reach
        manifest["advice"] = ("the browser's text was not used: the page reached into the local network "
                              "(%s) through a redirect%s" % (
                                  browser_inside,
                                  "; rerun with %s to read it through a remote reader instead%s" % (
                                      out_flag, " (the URL may carry a secret: %s)" % secret_why if secret_why else "")
                                  if out_flag else ""))
    elif manifest["status"] == "blocked":
        # --alternate is not named for a wall: on 8 walls in a read of 238 pages it opened none
        # (the browser had been at 6 already and met the same wall at the other 2), and agents
        # at a wall spent a call on it because this line said so (2026-11-19)
        if internal_why:
            manifest["advice"] = "an internal host (%s) never goes to a remote reader%s" % (
                internal_why, "" if browser_ran or not browser_here
                else "; --alternate re-reads it in the browser")
        elif out_flag:
            manifest["advice"] = "rerun with %s to try a public reader%s" % (
                out_flag, " (the URL may carry a secret: %s)" % secret_why if secret_why else "")
        elif not readers_ran and not args.force_external and "external" not in SKIP:
            manifest["advice"] = "the readers were not asked: rerun with --force-external"
        else:
            manifest["advice"] = ("a wall: %s stopped too, so no flag opens this page now - use another "
                                  "source, or see \"When nothing works\" in SKILL.md" % (
                                      "the browser and the public readers were" if browser_ran and readers_ran
                                      else "the public readers were" if readers_ran else "the browser was"
                                      if browser_ran else "every engine here was"))
    elif manifest["status"] == "login_required":
        manifest["advice"] = "this page needs an account; this skill cannot sign in"
    elif manifest["status"] == "not_found":
        manifest["advice"] = ("the page is gone; the archive was tried" if external_allowed else
                              "the page is gone; rerun with %s to try the archive" % out_flag if out_flag
                              else "the page is gone")
    elif broke:
        manifest["advice"] = zip_advice(broke, local, word_count, transit, f.get("cut") == "step")
    elif manifest["status"] == "empty":
        if manifest["signals"].get("binary"):
            manifest["advice"] = "the response is binary, not a page; there is no text to read"
        elif manifest["signals"].get("ocr_error"):
            manifest["advice"] = ("this PDF is a scan and OCR does not start here (%s): look at the rendered "
                                  "pages in files.pages" % manifest["signals"]["ocr_error"])
        elif browser_ran or not browser_here:
            # the browser has rendered it (or none is here): --alternate would only do it again
            manifest["advice"] = (("the page has no text as rendered: --screenshots shows what it draws"
                                   if browser_ran else "no text in it" if local else "the server's page has no text")
                                  + (", or rerun with %s to try a public reader" % out_flag if out_flag else ""))
        else:
            manifest["advice"] = "try --alternate (it renders the page in the browser)" + (
                " or " + out_flag if out_flag else "")
    elif manifest["status"] == "error" and network_fail:
        # a dropped connection was already tried once more; say what is left to try
        manifest["advice"] = ("the host did not answer: check the address, or try again in a minute "
                              "(a failure is not cached)%s"
                              % (", or rerun with %s to try a reader or the archive" % out_flag
                                 if out_flag else ""))
    elif manifest["status"] == "error" and cut:
        manifest["advice"] = ("%s before the page arrived: --refresh tries again, --download waits as "
                              "long as the server takes" % cut_said(f, size))
    elif manifest["status"] == "error" and by_code == "error" and not network_fail:
        manifest["advice"] = ("the server answered HTTP %s; its own page is the text. Retry later%s"
                              % (source_code, ", or rerun with %s for an archived copy" % out_flag
                                 if out_flag else ""))
    elif cut and source != "http":
        manifest["advice"] = ("the %s was still sending when its time ran out, so the text may stop "
                              "early: --refresh tries again" % SOURCE_NAMES.get(source, source))
    elif cut:
        manifest["advice"] = ("%s, so the text may stop early: --refresh tries again, --download "
                              "waits as long as the server takes" % cut_said(f, size))
    elif manifest["signals"].get("paywall"):
        manifest["advice"] = ("the page says it is paywalled (schema.org isAccessibleForFree: false): the text is what "
                              "the server sent and may be only the part open to everyone, or the whole article a "
                              "script hides; this skill cannot subscribe")
        if fragment:
            manifest["advice"] += "; " + fragment_advice(cover)
    elif fragment:
        manifest["advice"] = fragment_advice(cover)
    elif state == "weak":
        manifest["advice"] = "the page mentions signing in; the text may be partial"
    elif manifest["status"] == "ok" and tables_said and tables_advice(_PDF):
        manifest["advice"] = tables_advice(_PDF)            # the read's own lists, not the ranges
    if video_advice:
        # why the video gave no subtitles comes first: what follows is only what its page says
        manifest["advice"] = video_advice + ("; " + manifest["advice"] if manifest["advice"] else "")
    if _COOKIE_STATS["sent"] or _COOKIE_STATS["stored"]:
        manifest["signals"]["cookies"] = {"sent": _COOKIE_STATS["sent"],
                                          "stored": _COOKIE_STATS["stored"]}
    # A wall can be our own stale session, not the site's doing. Say so where it can help: when
    # the site's cookies of an earlier read were sent - not the ones this read got from the wall
    # itself, which are dropped (they are no session, and would look like one next time).
    if manifest["status"] in ("blocked", "login_required"):
        if _COOKIE_STATS["sent"] and had_session():
            manifest["advice"] = ((manifest["advice"] or "").rstrip(".")
                                  + "; a stale session cookie of this site can cause this: "
                                    "rerun with --clear-cookies")
        drop_wall_cookies()
        if "cookies" in manifest["signals"]:
            manifest["signals"]["cookies"]["stored"] = len(load_cookies(url))

    m, im = gaps(c, {"need_browser": need_browser, "browser_disabled": "browser" in SKIP,
                     "kind_doc": kind == "pdf", "office_lib": _OFFICE.get("missing") if kind == "zip" else "",
                     "blocked": blocked_http, "no_text_layer": bool(no_text_layer),
                     "ocr_missing": ocr_missing, "pdf_tables": pdf_tables_wanted,
                     "video": bool(VIDEO_URL.search(url))})
    manifest["missing"] = (manifest.get("missing") or []) + m
    manifest["improve"] = im
    if shot_entries and not screens.glue_tool() and kind not in ("pdf",):
        # without a picture library each screen comes alone: twice the pictures, the same tokens
        manifest["improve"].append({"what": "screenshots", "fix": ownenv.fix("pillow", "pip install pillow"),
                                    "note": "two screens then come as one 1280x1568 picture"})

    manifest["elapsed_ms"] = int((now() - t0) * 1000)
    trace("status", status=manifest["status"], chars=len(text or ""), cover=cover,
          fragment=manifest["signals"].get("fragment"), blocked=manifest["signals"].get("blocked"),
          advice=manifest["advice"], ms=manifest["elapsed_ms"])
    store_cache(workdir, manifest, url)
    trace("phase", stored=int((now() - t0) * 1000))
    rc = finish(workdir, manifest, t0, args, content_path)
    trace("phase", total=int((now() - t0) * 1000))
    return rc


def fragment_advice(cover):
    """What a suspected fragment's answer does, in the first line's measure: the share of the page's words."""
    return ("content.md holds %d%% of the page's words, so the answer shows page.md, the whole page (the extracted "
            "text may have missed part of it)" % int(round((cover or 0) * 100)))


def _prune(node):
    """The manifest is a contract for an agent: empty strings, lists and dicts are noise."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            v2 = _prune(v)
            if v2 not in ("", None, [], {}):
                out[k] = v2
        return out
    if isinstance(node, list):
        return [_prune(x) for x in node]
    return node


def finish(workdir, manifest, t0, args=None, content_path=None):
    try:
        os.unlink(os.path.join(workdir, "cookies.jar"))     # a session cookie is not a result
    except OSError:
        pass
    manifest["elapsed_ms"] = int((now() - t0) * 1000)
    manifest["dir"] = manifest.get("dir") or workdir
    sig = manifest.setdefault("signals", {})
    sig.pop("env_failed", None)
    if ownenv.status().get("failed"):
        # the environment's Python started and failed: this read ran in the machine's, and says so
        sig["env_failed"] = ownenv.status().get("why") or "its Python failed"
    if manifest.get("status") not in (None, "ok") and not sig.get("status_reason"):
        # an early exit (a cap hit before any text) skips the reasons table: name the rule here,
        # so every status but ok has its reason line
        sig["status_reason"] = sig.get("limit") or sig.get("network") or manifest.get("advice") or manifest["status"]
    stamp_read(manifest)
    as_json = args is not None and getattr(args, "json", False)
    continuing = args is not None and bool(getattr(args, "from_line", 0))
    view = answer_view(manifest, workdir, getattr(args, "file", "") if args is not None else "", continuing)
    ocr_n = (getattr(args, "ocr", 0) or 0) if args is not None else 0
    ocr = None
    if ocr_n:
        # --ocr N answers with picture N's text: the window's other pictures are not wanted
        manifest, ocr = ocr_answer(workdir, manifest, ocr_n)
    elif (args is not None and not (getattr(args, "deny_images", False) or "images" in SKIP)
            and not str((manifest.get("url") or {}).get("final") or "").startswith("file:")):
        # the pictures of the lines this answer prints: the first read's
        # window, a continuation's, page.md's when page.md is printed. The page is not read again
        # and no line moves: a marker is rewritten on its own line
        url = (manifest.get("url") or {}).get("requested") or (manifest.get("url") or {}).get("final") or ""
        before = json.dumps(manifest.get("images"), sort_keys=True)
        try:
            manifest = window_pictures(workdir, manifest, url, view, getattr(args, "from_line", 0) or 1,
                                       shown_paths(_prune({k: v for k, v in manifest.items() if not k.startswith("_")})))
        except Exception as e:                                 # noqa: BLE001
            debuglog.exc("pictures: window", e)
            trace("images.window", error=str(e)[:120])
        if url and json.dumps(manifest.get("images"), sort_keys=True) != before:
            store_cache(workdir, manifest, url)
    if args is not None and getattr(args, "refresh", False):
        try:
            # after the window's pictures: a picture a 304 confirmed keeps its file
            prune_unreferenced(workdir, manifest)
        except Exception as _dbg_e:                                      # noqa: BLE001
            debuglog.exc("finish: prune", _dbg_e)
    if not as_json and not ocr_n:
        manifest["_view"] = view              # the file read last (answer_view); a picture's text is not one
    public = shown_paths(_prune({k: v for k, v in manifest.items() if not k.startswith("_")}))
    if getattr(args, "ignored", None):
        # this call's left-out flags: the answer and --json say so, the saved manifest does not
        # (a later call from the cache did not have them)
        public["ignored"] = list(args.ignored)
    if ocr is not None:
        # the picture's text is this call's answer; --json carries it for MCP, the file does not
        public["ocr"] = {k: v for k, v in ocr.items() if k != "text" or as_json}
    if debuglog.enabled():
        # READ_PAGE_DEBUG=1: the end of the log - never the answer or the manifest, which MCP hands
        # to the model
        imgs = [e for e in (manifest.get("images") or []) if isinstance(e, dict)]
        bs = budget.summary()
        debuglog.log("summary", status=public.get("status"), cache=public.get("cache"), view=view,
                     content=public.get("content"), signals=public.get("signals"), chain=public.get("chain"),
                     candidates=public.get("candidates"), advice=public.get("advice"), missing=public.get("missing"),
                     improve=public.get("improve"), files=sorted((public.get("files") or {}).keys()),
                     url={k: (debuglog.mask_url(v) if isinstance(v, str) else v) for k, v in (public.get("url") or {}).items()},
                     images={"listed": len(imgs), "with_file": sum(1 for e in imgs if e.get("file")),
                             "why": sorted({str(e.get("why")) for e in imgs if e.get("why")})[:12]},
                     elapsed=bs["elapsed"], deadline=bs["deadline"], left=bs["left"],
                     steps_cut=[st for st in bs["steps"] if st.get("end") != "ok"])
    try:
        write_manifest(os.path.join(workdir, "manifest.json"), manifest)
    except Exception as _dbg_e:                                         # noqa: BLE001
        debuglog.exc("finish: manifest write", _dbg_e)
    if as_json:
        sys.stdout.write(json.dumps(public, ensure_ascii=False, indent=1) + "\n")
    else:
        text = ""
        path = os.path.join(workdir, view)
        if ocr is not None:
            out, _ = answer.render(public, ocr.get("text") or "", "img #%d text" % ocr_n, 1, ocr_next)
            sys.stdout.write(out)
            sys.stdout.flush()
            return 0
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        out, _ = answer.render(public, text, view, getattr(args, "from_line", 0) or 1, cli_next)
        sys.stdout.write(out)
    sys.stdout.flush()
    return 0                           # an answer was printed, whatever its status


def answer_view(manifest, workdir, asked="", continuing=False):
    """The saved text an answer prints. Named with --file: that one, and it stays the file being
    read. A continuation (--from) with no name goes on in the file read last (`_view`, kept in
    the manifest), so a forgotten --file never switches texts under the line numbers. A new
    reading (no --from) starts at page.md for a fragment, else at content.md."""
    if asked:
        return asked
    last = (manifest or {}).get("_view")
    if continuing and last in VIEWS and os.path.isfile(os.path.join(workdir, last)):
        return last
    if (manifest.get("signals") or {}).get("fragment") and os.path.isfile(os.path.join(workdir, "page.md")):
        return "page.md"
    return "content.md"


def remember_view(workdir, view):
    """The MCP server renders its own answer: it keeps the file a reading started with here."""
    m = load_manifest(workdir)
    if not m or view not in VIEWS or m.get("_view") == view:
        return
    m["_view"] = view
    try:
        write_manifest(os.path.join(workdir, "manifest.json"), m)
    except OSError:
        pass


def cli_next(n, total, view):
    # the file is named even when it is the default: a continuation never depends on a guess
    return "── next: line %d of %d → the same command with --from %d --file %s ──" % (n, total, n, view)


def ocr_next(n, total, view):
    # a picture's text longer than an answer: rare (a page photographed); the picture itself has it
    return "── %s goes on past line %d of %d: open the picture itself ──" % (view, n - 1, total)


def serve_once():
    """The MCP server's spare: a process with its imports done (curl_cffi among them)
    waits for one call's arguments, a JSON list on one stdin line, reads that page and exits. One
    call per process, so nothing of one read reaches the next. A closed stdin means "not needed"."""
    try:
        curl_cffi_requests()
    except Exception:                                          # noqa: BLE001
        pass
    line = sys.stdin.readline()
    if not line.strip():
        return 0
    argv = json.loads(line)
    sys.argv = [sys.argv[0]] + [str(a) for a in argv]
    return main(sys.argv[1:])


if __name__ == "__main__":
    # An unexpected exception in one tier still ends in an answer, not a bare traceback
    # (velosite.ru + --allow-external, 30.10); exit 1 says the reader broke, not the page.
    try:
        sys.exit(serve_once() if sys.argv[1:] == ["--serve-once"] else main())
    except SystemExit:
        raise
    except Exception as e:                                     # noqa: BLE001
        asked = next((a for a in sys.argv[1:] if not a.startswith("-")), "")
        why = "internal error (%s: %s)" % (type(e).__name__, str(e)[:200])
        if "--json" in sys.argv[1:]:
            sys.stdout.write(json.dumps({"schema": SCHEMA, "status": "error",
                                         "url": {"requested": asked}, "dir": "",
                                         "signals": {"status_reason": "internal error: %s" % type(e).__name__},
                                         "advice": why + "; rerun with --refresh"},
                                        ensure_ascii=False, indent=1) + "\n")
        else:
            sys.stdout.write("read-page · error · %s\nadvice: rerun with --refresh; if it repeats, "
                             "this page breaks the reader\n" % why)
        sys.exit(1)
