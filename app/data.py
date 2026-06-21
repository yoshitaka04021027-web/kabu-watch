# -*- coding: utf-8 -*-
"""株価データ取得レイヤー。

Yahoo Finance の chart API から日次OHLCVを取得する。
APIキー不要・無料。ただしレート制限があるため、取得結果はローカルに
キャッシュし、一定時間内は再利用する（毎日のデータなので頻繁な再取得は不要）。
標準ライブラリのみ使用（pip install 不要）。
"""

import json
import os
import time
import threading
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar

import stocks

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# キャッシュ有効時間（秒）。日次データなので30分で十分。
CACHE_TTL = 30 * 60

# Yahoo はUser-Agentが無いと 429 を返す。さらに長いChrome系UAも弾かれるため、
# 実測で安定して通る短いUA + Accept: */* を使う。
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh)",
    "Accept": "*/*",
}

_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval={interval}"
_FUND_API = (
    "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    "?modules=price,summaryDetail,defaultKeyStatistics,financialData"
)
_QUOTE_API = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
FUNDAMENTAL_TTL = 12 * 60 * 60

# 同一シンボルの同時取得を防ぐロック群
_locks = {}
_locks_guard = threading.Lock()


def _lock_for(symbol):
    with _locks_guard:
        if symbol not in _locks:
            _locks[symbol] = threading.Lock()
        return _locks[symbol]


def _cache_path(symbol, suffix="quote"):
    safe = symbol.replace("/", "_").replace("\\", "_")
    return os.path.join(CACHE_DIR, safe + "_" + suffix + ".json")


def _read_cache(symbol, suffix="quote"):
    path = _cache_path(symbol, suffix)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(symbol, payload, suffix="quote"):
    try:
        path = _cache_path(symbol, suffix)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, allow_nan=False)
        os.replace(tmp, path)  # アトミックに差し替え（中断による破損を防ぐ）
    except Exception:
        pass  # キャッシュ書き込み失敗は致命的ではない


def _http_get(url, retries=3):
    """リトライ付きHTTP GET。429/5xx は指数バックオフで再試行。
    待機は「次の試行がある場合のみ」行い、429 は Retry-After ヘッダも尊重する。"""
    last_err = None
    for attempt in range(retries):
        is_last = attempt >= retries - 1
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504) and not is_last:
                try:
                    retry_after = int(e.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    retry_after = 0
                # サーバ指定の待機を尊重しつつ上限10秒。
                time.sleep(max(1.2 * (attempt + 1), min(retry_after, 10)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if is_last:
                break
            time.sleep(1.0 * (attempt + 1))
            continue
    raise last_err if last_err else RuntimeError("fetch failed")


def _parse_chart(raw):
    """Yahoo chart JSON を扱いやすい辞書に整形。欠損(None)行は除去。"""
    d = json.loads(raw)
    chart = d.get("chart", {})
    if chart.get("error"):
        err = chart["error"]
        if isinstance(err, dict):
            raise ValueError(err.get("description") or err.get("code") or "chart error")
        raise ValueError(str(err))
    result = (chart.get("result") or [None])[0]
    if not result:
        raise ValueError("no result")

    meta = result.get("meta", {})
    # 取引所のタイムゾーン補正（JSTなら32400秒）。サーバのTZに依存せず日付を出す。
    gmtoffset = meta.get("gmtoffset") or 0
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    dates, o, h, l, c, v = [], [], [], [], [], []
    for i, ts in enumerate(timestamps):
        cl = closes[i] if i < len(closes) else None
        if cl is None:  # 休場日などはスキップ
            continue
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(ts + gmtoffset)))
        o.append(opens[i] if i < len(opens) and opens[i] is not None else cl)
        h.append(highs[i] if i < len(highs) and highs[i] is not None else cl)
        l.append(lows[i] if i < len(lows) and lows[i] is not None else cl)
        c.append(cl)
        v.append(volumes[i] if i < len(volumes) and volumes[i] is not None else 0)

    price = meta.get("regularMarketPrice")
    if price is None and c:
        price = c[-1]

    # 前日比は「直近2営業日の終値」で計算する。
    # meta.chartPreviousClose は range=1y だと1年前の値になり誤るため使わない。
    if len(c) >= 2:
        prev_close = c[-2]
    else:
        prev_close = meta.get("chartPreviousClose")

    return {
        "symbol": meta.get("symbol"),
        "name": meta.get("longName") or meta.get("shortName") or meta.get("symbol"),
        "currency": meta.get("currency"),
        "price": price,
        "prev_close": prev_close,
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "week52_high": meta.get("fiftyTwoWeekHigh"),
        "week52_low": meta.get("fiftyTwoWeekLow"),
        "market_time": meta.get("regularMarketTime"),
        "exchange": meta.get("fullExchangeName"),
        "dates": dates,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "fetched_at": int(time.time()),
    }


def fetch_chart(symbol, range_="2y", interval="1d"):
    """1銘柄の日次データを取得（生フェッチ、キャッシュ無視）。"""
    url = _API.format(symbol=urllib.parse.quote(symbol, safe="^=.-"),
                      range=range_, interval=interval)
    raw = _http_get(url)
    return _parse_chart(raw)


def _raw(obj, *path):
    cur = obj
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    if isinstance(cur, dict) and "raw" in cur:
        return cur.get("raw")
    return cur


def _fmt_large(v):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    unit = ""
    for unit, div in (("兆", 1_000_000_000_000), ("億", 100_000_000), ("万", 10_000)):
        if abs(v) >= div:
            return round(v / div, 1), unit
    return round(v, 1), unit


# --- quoteSummary 用の crumb/cookie 認証セッション ---
# quoteSummary / quote エンドポイントは crumb(トークン)+cookie が必須。
# 一度取得して使い回し、401/403 のときだけ取り直す。
_fund_lock = threading.Lock()
_fund_session = {"opener": None, "crumb": None, "ts": 0}
_FUND_CRUMB_TTL = 3600


def _new_fund_session():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    for u in ("https://fc.yahoo.com", "https://finance.yahoo.com"):
        try:
            opener.open(urllib.request.Request(u, headers=_HEADERS), timeout=15)
        except Exception:
            pass
    crumb = opener.open(urllib.request.Request(
        "https://query1.finance.yahoo.com/v1/test/getcrumb", headers=_HEADERS),
        timeout=15).read().decode("utf-8").strip()
    if not crumb or len(crumb) > 40 or "<" in crumb:
        raise ValueError("crumb取得失敗")
    return opener, crumb


def _get_fund_session(force=False):
    with _fund_lock:
        s = _fund_session
        if not force and s["opener"] and s["crumb"] and time.time() - s["ts"] < _FUND_CRUMB_TTL:
            return s["opener"], s["crumb"]
        opener, crumb = _new_fund_session()
        s.update(opener=opener, crumb=crumb, ts=time.time())
        return opener, crumb


def _fund_http_get(url):
    """crumb/cookie 付きで取得。401/403 なら crumb を取り直して一度だけ再試行。"""
    last = None
    for attempt in range(2):
        opener, crumb = _get_fund_session(force=(attempt > 0))
        full = url + ("&" if "?" in url else "?") + "crumb=" + urllib.parse.quote(crumb, safe="")
        try:
            return opener.open(urllib.request.Request(full, headers=_HEADERS), timeout=20).read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (401, 403):
                continue
            raise
        except Exception as e:
            last = e
            continue
    raise last if last else RuntimeError("fundamentals fetch failed")


def fetch_fundamentals(symbol):
    """Yahoo quoteSummary から取れる範囲の簡易ファンダメンタル指標を取得する。"""
    url = _FUND_API.format(symbol=urllib.parse.quote(symbol, safe="^=.-"))
    try:
        raw = _fund_http_get(url)
    except Exception:
        return fetch_quote_fundamentals(symbol)
    d = json.loads(raw)
    err = (d.get("quoteSummary") or {}).get("error")
    if err:
        raise ValueError(err.get("description") if isinstance(err, dict) else str(err))
    result = ((d.get("quoteSummary") or {}).get("result") or [None])[0]
    if not result:
        raise ValueError("no fundamentals")
    sd = result.get("summaryDetail") or {}
    ks = result.get("defaultKeyStatistics") or {}
    fd = result.get("financialData") or {}
    price = result.get("price") or {}
    market_cap = _raw(price, "marketCap") or _raw(sd, "marketCap")
    cap = _fmt_large(market_cap) if market_cap is not None else None
    cap_value, cap_unit = cap if cap else (None, None)
    return {
        "market_cap": market_cap,
        "market_cap_display": (f"{cap_value}{cap_unit}円" if cap_value is not None else None),
        "trailing_pe": _raw(sd, "trailingPE"),
        "forward_pe": _raw(sd, "forwardPE"),
        "price_to_book": _raw(ks, "priceToBook"),
        "dividend_yield_pct": _pct_unit(_raw(sd, "dividendYield")),
        "payout_ratio_pct": _pct_unit(_raw(sd, "payoutRatio")),
        "roe_pct": _pct_unit(_raw(fd, "returnOnEquity")),
        "profit_margin_pct": _pct_unit(_raw(fd, "profitMargins")),
        "revenue_growth_pct": _pct_unit(_raw(fd, "revenueGrowth")),
        "earnings_growth_pct": _pct_unit(_raw(fd, "earningsGrowth")),
        "debt_to_equity": _raw(fd, "debtToEquity"),
        "beta": _raw(sd, "beta"),
        "fetched_at": int(time.time()),
        "source": "Yahoo Finance quoteSummary",
    }


def fetch_quote_fundamentals(symbol):
    """quoteSummary が拒否された場合の軽量フォールバック。取れる項目は少ない。"""
    url = _QUOTE_API.format(symbol=urllib.parse.quote(symbol, safe="^=.-"))
    raw = _fund_http_get(url)
    d = json.loads(raw)
    result = ((d.get("quoteResponse") or {}).get("result") or [None])[0]
    if not result:
        raise ValueError("no quote fundamentals")
    market_cap = result.get("marketCap")
    cap = _fmt_large(market_cap) if market_cap is not None else None
    cap_value, cap_unit = cap if cap else (None, None)
    return {
        "market_cap": market_cap,
        "market_cap_display": (f"{cap_value}{cap_unit}円" if cap_value is not None else None),
        "trailing_pe": result.get("trailingPE"),
        "forward_pe": result.get("forwardPE"),
        "price_to_book": result.get("priceToBook"),
        "dividend_yield_pct": _pct_maybe_percent(result.get("dividendYield") or result.get("trailingAnnualDividendYield")),
        "payout_ratio_pct": None,
        "roe_pct": None,
        "profit_margin_pct": None,
        "revenue_growth_pct": None,
        "earnings_growth_pct": None,
        "debt_to_equity": None,
        "beta": result.get("beta"),
        "fetched_at": int(time.time()),
        "source": "Yahoo Finance quote",
    }


def _pct_unit(v):
    if v is None:
        return None
    try:
        return float(v) * 100.0
    except (TypeError, ValueError):
        return None


def _pct_maybe_percent(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 1 else f * 100.0


def get_fundamentals(symbol, force=False):
    cached = _read_cache(symbol, "fundamentals")
    if cached and not force:
        age = int(time.time()) - cached.get("fetched_at", 0)
        if age < FUNDAMENTAL_TTL:
            cached["_cache"] = "hit"
            return cached
    try:
        data = fetch_fundamentals(symbol)
        _write_cache(symbol, data, "fundamentals")
        data["_cache"] = "miss"
        return data
    except Exception as e:
        if cached:
            cached["_cache"] = "stale"
            cached["_error"] = str(e)
            return cached
        raise


def get_stock(code_or_symbol, range_="2y", force=False):
    """銘柄データを取得。キャッシュが新しければ再利用。
    取得失敗時はキャッシュがあればそれを返す（古くてもゼロよりマシ）。"""
    symbol = stocks.to_symbol(code_or_symbol)
    with _lock_for(symbol):
        cache_suffix = "quote_" + range_
        cached = _read_cache(symbol, cache_suffix)
        if cached and not force:
            age = int(time.time()) - cached.get("fetched_at", 0)
            if age < CACHE_TTL and cached.get("close"):
                cached["_cache"] = "hit"
                cached["_cache_age_sec"] = age
                if not cached.get("fundamentals"):
                    try:
                        cached["fundamentals"] = get_fundamentals(symbol, force=force)
                        _write_cache(symbol, cached, cache_suffix)
                    except Exception as fe:
                        cached["_fundamentals_error"] = str(fe)
                return cached
        try:
            data = fetch_chart(symbol, range_=range_)
            # マスターに日本語名があれば優先
            jp = stocks.name_of(stocks.to_code(symbol))
            if jp:
                data["name"] = jp
            data["code"] = stocks.to_code(symbol)
            data["sector"] = stocks.sector_of(stocks.to_code(symbol))
            try:
                data["fundamentals"] = get_fundamentals(symbol, force=force)
            except Exception as fe:
                data["fundamentals"] = {}
                data["_fundamentals_error"] = str(fe)
            data["data_source"] = "Yahoo Finance chart"
            data["range"] = range_
            _write_cache(symbol, data, cache_suffix)
            data["_cache"] = "miss"
            data["_cache_age_sec"] = 0
            return data
        except Exception as e:
            if cached and cached.get("close"):
                cached["_cache"] = "stale"
                cached["_error"] = str(e)
                cached["_cache_age_sec"] = int(time.time()) - cached.get("fetched_at", 0)
                return cached
            raise
