# -*- coding: utf-8 -*-
"""ニュース取得レイヤー（ファンダメンタル情報）。

Google ニュースの RSS 検索（APIキー不要・無料）から、日本株に影響しそうな
最新の記事を取得する。標準ライブラリのみ使用。

各記事には、初心者向けに「なぜ株価に効くのか」を表す簡単なヒントを付ける。
"""

import json
import os
import time
import threading
import datetime
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

CACHE_TTL = 15 * 60  # ニュースは15分キャッシュ

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh)", "Accept": "*/*"}
_GNEWS = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"

_lock = threading.Lock()

# 市況ニュースのカテゴリ（キー, ラベル, 検索クエリ）
# 前半は基本のテーマ、後半は最新のトレンド（人気テーマ）。チップは自動で表示される。
CATEGORIES = [
    # --- 基本 ---
    ("main", "主要", "日経平均 OR 日本株 OR 東証 株式市場"),
    ("earnings", "決算・業績", "日本株 決算 OR 業績 OR 増配 OR 自社株買い"),
    ("macro", "金利・為替", "日銀 OR 金利 OR 円相場 OR ドル円 日本株"),
    ("economy", "経済・景気", "日本 経済 OR 景気 OR 物価"),
    # --- 最新トレンドテーマ ---
    ("ai", "AI・生成AI", "生成AI OR AI関連株 日本"),
    ("semi", "半導体", "半導体 関連株 日本 OR 半導体製造装置"),
    ("defense", "防衛", "防衛 関連株 OR 防衛費 日本"),
    ("inbound", "インバウンド", "インバウンド 関連株 OR 訪日外国人"),
    ("datacenter", "データセンター・電力", "データセンター OR 電力需要 関連株 日本"),
    ("nuclear", "原子力・SMR", "原子力 OR 原発 OR SMR 関連株 日本"),
    ("ev", "EV・電池", "EV OR 全固体電池 株 日本"),
    ("robot", "ロボット・自動化", "ロボット OR 産業用ロボット OR 自動化 関連株 日本"),
    ("governance", "東証改革・株主還元", "PBR OR 東証改革 OR 株主還元 OR 物言う株主"),
    ("nisa", "新NISA・個人投資家", "新NISA OR 個人投資家 日本株"),
    ("green", "脱炭素・再エネ", "脱炭素 OR 再生可能エネルギー OR 水素 関連株"),
    ("space", "宇宙", "宇宙 関連株 日本 OR ロケット銘柄"),
    ("bio", "バイオ・創薬", "バイオ OR 創薬 関連株 日本"),
    ("quantum", "量子コンピュータ", "量子コンピュータ 関連株 日本"),
    ("cyber", "サイバーセキュリティ", "サイバーセキュリティ 関連株 日本"),
    ("disaster", "防災・国土強靱化", "国土強靱化 OR 防災 OR 減災 関連株"),
]
_CAT_MAP = {key: (label, query) for key, label, query in CATEGORIES}

# Yahoo!ファイナンス等の「ニュースではない株価ページ」を除外するための語
_NOISE = ("株価・株式情報", "指数情報・推移", "値動きの背景をAIが解説",
          "：今の株価", "の株価・株式", "株価予想")

# 初心者向け「なぜ重要か」ヒント（キーワード → 解説）。上から順に最初に一致したものを使う。
_HINTS = [
    # --- 相場全体を動かすマクロ要因 ---
    (("利上げ", "利下げ", "金利", "日銀", "金融政策", "国債"),
     "金利の動きは、銀行・保険（上がると有利）や不動産・高配当株（上がると不利）など幅広い銘柄に影響します。"),
    (("円安", "円高", "為替", "ドル円", "円相場"),
     "円安は輸出企業（自動車・電機など）に追い風、輸入が多い企業には逆風になりやすいです。"),
    (("米国", "FRB", "NYダウ", "ナスダック", "アメリカ", "トランプ", "関税"),
     "日本株は前日のアメリカ市場の影響を強く受けます。米株高なら買われやすい傾向があります。"),
    # --- 最新トレンドテーマ ---
    (("防衛", "防衛費", "安全保障", "ミサイル"),
     "防衛費の増額方針を背景に、防衛関連（重工・電機・機械）が注目される国策テーマです。"),
    (("インバウンド", "訪日", "観光", "免税"),
     "訪日客の増加は、百貨店・鉄道・ホテル・化粧品など消費関連株の追い風になります。"),
    (("データセンター", "電力需要", "送電", "電線", "電源", "電力株"),
     "AIの普及でデータセンターの電力需要が急増。電力・電線・電源・冷却の関連企業が注目されています。"),
    (("原子力", "原発", "SMR", "核融合"),
     "電力需要増と脱炭素を背景に原子力が再評価。重電・建設・素材など関連企業が動きやすいテーマです。"),
    (("全固体電池", "EV", "電気自動車", "蓄電池", "リチウム"),
     "EVシフトや次世代電池の進展は、自動車・電池・部材メーカーの将来性を左右します。"),
    (("ロボット", "自動化", "省人化", "ヒューマノイド"),
     "人手不足を背景に、産業用ロボットや自動化（FA）関連の需要が拡大しています。"),
    (("PBR", "東証改革", "物言う株主", "アクティビスト"),
     "東証が促す『PBR1倍割れ』改善で、増配・自社株買いなど株主還元を強める企業が見直されるテーマです。"),
    (("NISA", "個人投資家"),
     "新NISAで個人マネーが株式に流入。高配当株や優良株への資金流入が話題になりやすいテーマです。"),
    (("脱炭素", "再生可能エネルギー", "再エネ", "水素", "洋上風力", "アンモニア"),
     "脱炭素の流れは、再エネ・水素・蓄電など環境関連企業の長期的な追い風になります。"),
    (("宇宙", "ロケット", "衛星"),
     "宇宙開発は国策でも注目される長期テーマ。ロケットや衛星の関連企業が物色されます。"),
    (("バイオ", "創薬", "新薬", "治験", "臨床"),
     "新薬の成功や提携は株価を大きく動かす一方、失敗リスクも大きい値動きの荒いテーマです。"),
    (("量子",),
     "量子コンピュータは次世代の長期テーマ。実用化は途上で、思惑で大きく動きやすい点に注意です。"),
    (("サイバー", "セキュリティ"),
     "サイバー攻撃の増加で防御需要が拡大。セキュリティ関連企業への注目が続くテーマです。"),
    (("防災", "減災", "国土強靱化", "地震", "インフラ老朽化"),
     "災害やインフラ老朽化への対策は、建設・土木・点検関連の需要につながる国策テーマです。"),
    (("半導体", "生成AI", "AI"),
     "半導体・AI関連は世界的な需要やアメリカのハイテク株の動きで大きく上下しやすい分野です。"),
    # --- 個別銘柄の材料 ---
    (("決算", "業績", "最高益", "増益", "減益", "上方修正", "下方修正"),
     "決算は株価が大きく動きやすいタイミング。予想を上回ると買われ、下回ると売られやすくなります。"),
    (("増配", "自社株買い", "株主還元", "配当"),
     "株主還元（増配・自社株買い）の強化は、株価にプラスに働きやすい好材料です。"),
    (("原油", "資源", "商品", "インフレ", "物価"),
     "資源・物価の動きは、商社やエネルギー関連、コスト負担の大きい企業の業績に影響します。"),
    (("提携", "買収", "M&A", "新製品", "新工場", "受注", "TOB"),
     "提携・買収・新製品などの発表は、その企業の将来の成長期待を変え、株価を動かすことがあります。"),
    (("不祥事", "リコール", "減配", "赤字", "訴訟", "不正", "下方"),
     "業績悪化や不祥事はネガティブ材料。短期的に売られやすいので保有銘柄なら要注意です。"),
]


def _hint_for(title):
    for keys, text in _HINTS:
        if any(k in title for k in keys):
            return text
    return None


def _cache_path(key):
    safe = "news_" + urllib.parse.quote(key, safe="")
    return os.path.join(CACHE_DIR, safe + ".json")


def _read_cache(key):
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if int(time.time()) - data.get("fetched_at", 0) < CACHE_TTL:
            return data
    except Exception:
        return None
    return None


def _write_cache(key, items):
    try:
        path = _cache_path(key)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": int(time.time()), "items": items},
                      f, ensure_ascii=False, allow_nan=False)
        os.replace(tmp, path)
    except Exception:
        pass


def _relative(pub):
    """RFC822 の pubDate を「○時間前」と JST 表示文字列にする。"""
    if not pub:
        return None, None
    try:
        dt = parsedate_to_datetime(pub)
    except Exception:
        return None, pub
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    sec = (now - dt).total_seconds()
    if sec < 0:
        sec = 0
    if sec < 3600:
        rel = "%d分前" % max(1, int(sec // 60))
    elif sec < 86400:
        rel = "%d時間前" % int(sec // 3600)
    else:
        rel = "%d日前" % int(sec // 86400)
    jst = dt.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
    return rel, jst.strftime("%m/%d %H:%M")


def _clean_title(title, source):
    """Google ニュースは題名末尾に ' - 媒体名' を付けるので取り除く。"""
    if not title:
        return ""
    if source and title.endswith(" - " + source):
        return title[: -(len(source) + 3)].strip()
    return title.strip()


def _is_valid_url(url):
    return isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))


def _safe_fromstring(raw):
    """XML を安全に解析する。

    標準ライブラリの xml.etree は外部実体(XXE)や実体展開爆弾(billion laughs)に
    対して脆弱になり得る。defusedxml は使えない（pip不可）ため、DTD/実体宣言を
    含むフィードを解析前に拒否することで簡易的に防ぐ。正規の RSS には現れない。"""
    head = raw[:2048].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("unsafe XML (DOCTYPE/ENTITY rejected)")
    return ET.fromstring(raw)


def _fetch(query, limit=20):
    """RSS を取得して記事リストに整形（dedupe・ノイズ除去・ヒント付与）。"""
    url = _GNEWS.format(q=urllib.parse.quote(query))
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    root = _safe_fromstring(raw)

    out = []
    seen = set()
    for it in root.findall(".//item"):
        title = it.findtext("title") or ""
        link = it.findtext("link") or ""
        if not _is_valid_url(link):
            continue
        if any(n in title for n in _NOISE):
            continue
        src_el = it.find("source")
        source = src_el.text if src_el is not None else None
        clean = _clean_title(title, source)
        norm = clean.replace(" ", "").lower()
        if not clean or norm in seen:
            continue
        seen.add(norm)
        rel, when = _relative(it.findtext("pubDate"))
        out.append({
            "title": clean,
            "link": link,
            "source": source or "ニュース",
            "relative": rel,
            "time": when,
            "hint": _hint_for(clean),
        })
        if len(out) >= limit:
            break
    return out


def _get(key, query, limit=20, force=False):
    with _lock:
        cached = None if force else _read_cache(key)
        if cached:
            return {"items": cached["items"], "cache": "hit",
                    "updated": _fmt(cached["fetched_at"])}
        try:
            items = _fetch(query, limit=limit)
            _write_cache(key, items)
            return {"items": items, "cache": "miss", "updated": _fmt(int(time.time()))}
        except Exception as e:
            # 取得失敗時、古いキャッシュがあれば出す
            path = _cache_path(key)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        old = json.load(f)
                    return {"items": old.get("items", []), "cache": "stale",
                            "updated": _fmt(old.get("fetched_at", 0)), "error": str(e)}
                except Exception:
                    pass
            return {"items": [], "cache": "error", "error": str(e), "updated": None}


def _fmt(ts):
    if not ts:
        return None
    jst = datetime.datetime.fromtimestamp(ts, datetime.timezone(datetime.timedelta(hours=9)))
    return jst.strftime("%Y-%m-%d %H:%M")


def market_news(category="main", limit=20, force=False):
    label, query = _CAT_MAP.get(category, _CAT_MAP["main"])
    res = _get("cat_" + category, query, limit=limit, force=force)
    res["category"] = category
    res["label"] = label
    return res


def stock_news(name, limit=8):
    """銘柄名に関するニュース。"""
    q = "%s 株" % name
    return _get("stock_" + name, q, limit=limit)


def categories():
    return [{"key": k, "label": label} for k, label, _ in CATEGORIES]
