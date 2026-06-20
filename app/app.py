# -*- coding: utf-8 -*-
"""日本株ウォッチ — ローカルWebアプリ本体。

標準ライブラリだけで動くシンプルなHTTPサーバ。
  python3 app.py
を実行するとローカルサーバが立ち上がり、ブラウザが自動で開く。

提供API:
  GET  /api/market                  日経平均・ドル円などの市況
  GET  /api/recommendations?horizon=short|mid|long&top=10
  GET  /api/stock/<code>            1銘柄の詳細分析
  GET  /api/search?q=...            銘柄検索
  GET  /api/watchlist               ウォッチリスト取得
  POST /api/watchlist {code}        追加
  DEL  /api/watchlist/<code>        削除
  GET  /api/portfolio               保有銘柄＋売却判定
  POST /api/portfolio {...}         保有追加
  PUT  /api/portfolio/<id> {...}    保有更新
  DEL  /api/portfolio/<id>          保有削除
"""

import json
import os
import socket
import sys
import threading
import webbrowser
import base64
import hmac
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

import data
import analysis
import storage
import stocks
import news

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.realpath(os.path.join(BASE_DIR, "static"))
PORT = int(os.environ.get("PORT", "8765"))
# 既定はこのMacだけに公開する。iPhoneなど同じWi-Fiから使うときだけ HOST=0.0.0.0 で起動する。
HOST = os.environ.get("HOST", "127.0.0.1")
MAX_BODY = 1 << 20  # リクエストボディ上限 1MB
APP_PIN = os.environ.get("APP_PIN", "").strip()

_pool = ThreadPoolExecutor(max_workers=5)

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net data:; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class ClientError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _int_param(qs, name, default, minimum=None, maximum=None):
    raw = (qs.get(name, [str(default)])[0] or str(default)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ClientError(f"{name} は整数で指定してください")
    if minimum is not None and value < minimum:
        raise ClientError(f"{name} は {minimum} 以上で指定してください")
    if maximum is not None and value > maximum:
        raise ClientError(f"{name} は {maximum} 以下で指定してください")
    return value


def _authorized(auth_header):
    """APP_PIN が設定されている場合だけ、HTTP Basic 認証でアプリ全体を保護する。"""
    if not APP_PIN:
        return True
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
        user, _, password = raw.partition(":")
    except Exception:
        return False
    return hmac.compare_digest(password, APP_PIN) or hmac.compare_digest(user, APP_PIN)


# --- 銘柄群をまとめて取得して分析する ---

def _snapshot_for(code, force=False):
    try:
        stock = data.get_stock(code, force=force)
        return analysis.analyze_stock(stock)
    except Exception as e:
        return {"code": stocks.to_code(code), "name": stocks.name_of(stocks.to_code(code)) or code,
                "insufficient": True, "error": str(e)}


def _snapshots_for(codes, force=False):
    results = list(_pool.map(lambda c: _snapshot_for(c, force), codes))
    return results


# --- 各APIハンドラ ---

def api_market(qs):
    """市況: 日経平均・TOPIX連動ETF・ドル円。"""
    items = []
    targets = [
        ("^N225", "日経平均株価", "指数"),
        ("USDJPY=X", "ドル円（円/ドル）", "為替"),
    ]

    def fetch(sym_label):
        sym, label, kind = sym_label
        try:
            d = data.get_stock(sym)
            price = d.get("price")
            prev = d.get("prev_close")
            chg = ((price - prev) / prev * 100.0) if (price and prev) else None
            return {"symbol": sym, "label": label, "kind": kind,
                    "price": price, "change_pct": round(chg, 2) if chg is not None else None}
        except Exception as e:
            return {"symbol": sym, "label": label, "kind": kind, "error": str(e)}

    items = list(_pool.map(fetch, targets))
    return {"items": items, "updated": _now_str()}


def api_recommendations(qs):
    horizon = (qs.get("horizon", ["mid"])[0] or "mid").lower()
    if horizon not in ("short", "mid", "long"):
        raise ClientError("horizon は short / mid / long のいずれかで指定してください")
    top = _int_param(qs, "top", 12, minimum=1, maximum=50)
    force = qs.get("force", ["0"])[0] == "1"
    # クライアント（iPhone等）が自分のウォッチリストを渡せる。無ければ既定リスト。
    codes_param = (qs.get("codes", [""])[0] or "").strip()
    if codes_param:
        wl = [c.strip() for c in codes_param.split(",") if c.strip()][:60]
    else:
        wl = list(stocks.DEFAULT_WATCHLIST)
    snaps = _snapshots_for(wl, force=force)
    recs = analysis.recommend(snaps, horizon, top_n=top, min_score=0)
    errors = [s.get("code") for s in snaps if s.get("error")]
    return {"horizon": horizon, "count": len(recs), "items": recs,
            "watchlist_size": len(wl), "errors": errors, "updated": _now_str()}


def api_stock(code, qs):
    snap = _snapshot_for(code, force=(qs.get("force", ["0"])[0] == "1"))
    return snap


def api_search(qs):
    q = qs.get("q", [""])[0]
    return {"results": stocks.search(q)}


def api_master():
    """銘柄マスター全件（名前→コード変換・入力補完に使う）。"""
    return {"items": [{"code": c, "name": n, "sector": s} for c, n, s in stocks.MASTER]}


def api_news(qs):
    """市況ニュース（ファンダメンタル情報）。カテゴリ指定可。"""
    cat = (qs.get("cat", ["main"])[0] or "main")
    force = qs.get("force", ["0"])[0] == "1"
    res = news.market_news(cat, limit=24, force=force)
    res["categories"] = news.categories()
    return res


def api_stock_news(qs):
    """銘柄に関するニュース。code か name を受け付ける。"""
    code = (qs.get("code", [""])[0] or "").strip()
    name = (qs.get("name", [""])[0] or "").strip()
    if code and not name:
        name = stocks.name_of(stocks.to_code(code)) or code
    if not name:
        return {"items": [], "error": "code または name が必要です"}
    res = news.stock_news(name, limit=8)
    res["name"] = name
    return res


def api_watchlist_get():
    wl = storage.get_watchlist()
    detailed = [{"code": c, "name": stocks.name_of(c) or c,
                 "sector": stocks.sector_of(c)} for c in wl]
    return {"items": detailed}


def api_portfolio_get(qs):
    pf = storage.get_portfolio()
    force = qs.get("force", ["0"])[0] == "1"
    if not pf:
        return {"items": [], "totals": _empty_totals(), "updated": _now_str()}

    def eval_one(h):
        try:
            stock = data.get_stock(h["code"], force=force)
            snap = analysis.analyze_stock(stock)
            res = analysis.evaluate_holding(h, snap)
            res["id"] = h.get("id")
            res["memo"] = h.get("memo", "")
            return res
        except Exception as e:
            return {"id": h.get("id"), "code": h.get("code"),
                    "name": h.get("name"), "error": str(e),
                    "verdict": "データ取得失敗", "tone": "info",
                    "memo": h.get("memo", ""),
                    "reasons": [], "summary": "株価データを取得できませんでした。時間をおいて更新してください。"}

    items = list(_pool.map(eval_one, pf))
    totals = _portfolio_totals(items)
    return {"items": items, "totals": totals, "updated": _now_str()}


def _num(v, default=None):
    """文字列等を数値に。NaN/Infは _read_json_body 側で None 化済み。"""
    if v in (None, ""):
        return default
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return default


def _normalize_holding(h):
    """クライアントから送られた保有データを安全な数値・形に整える。"""
    code = stocks.to_code(str(h.get("code", "")).strip())
    return {
        "id": h.get("id"),
        "code": code,
        "name": h.get("name") or stocks.name_of(code) or code,
        "shares": _num(h.get("shares"), 0),
        "buy_price": _num(h.get("buy_price"), 0),
        "buy_date": h.get("buy_date"),
        "target_price": _num(h.get("target_price")),
        "stop_loss_pct": _num(h.get("stop_loss_pct")),
        "memo": h.get("memo", ""),
    }


def _evaluate_holdings(holdings, force=False):
    """保有銘柄リスト（クライアント保存）を評価して売買判定を返す。状態を持たない。"""
    if not holdings:
        return {"items": [], "totals": _empty_totals(), "updated": _now_str()}

    def eval_one(h):
        try:
            stock = data.get_stock(h["code"], force=force)
            snap = analysis.analyze_stock(stock)
            res = analysis.evaluate_holding(h, snap)
            res["id"] = h.get("id")
            res["memo"] = h.get("memo", "")
            return res
        except Exception as e:
            return {"id": h.get("id"), "code": h.get("code"),
                    "name": h.get("name"), "error": str(e),
                    "verdict": "データ取得失敗", "tone": "info",
                    "memo": h.get("memo", ""),
                    "reasons": [], "summary": "株価データを取得できませんでした。時間をおいて更新してください。"}

    items = list(_pool.map(eval_one, holdings))
    return {"items": items, "totals": _portfolio_totals(items), "updated": _now_str()}


def api_defaults():
    """初期ウォッチリスト（クライアントが最初に取り込む用）。"""
    return {"watchlist": list(stocks.DEFAULT_WATCHLIST)}


def _empty_totals():
    return {"cost": 0, "value": 0, "pl_total": 0, "pl_pct": None, "count": 0}


def _portfolio_totals(items):
    cost = 0.0
    value = 0.0
    for it in items:
        bp = it.get("buy_price")
        sh = it.get("shares")
        pr = it.get("price")
        if bp and sh:
            cost += bp * sh
        if pr and sh:
            value += pr * sh
    pl = value - cost
    pl_pct = (pl / cost * 100.0) if cost else None
    return {"cost": round(cost), "value": round(value), "pl_total": round(pl),
            "pl_pct": round(pl_pct, 2) if pl_pct is not None else None,
            "count": len(items)}


# --- HTTPハンドラ本体 ---

class Handler(BaseHTTPRequestHandler):
    server_version = "JStockWatch/1.0"

    def log_message(self, fmt, *args):
        # 標準のアクセスログは簡潔に
        sys.stderr.write("[server] %s\n" % (fmt % args))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status=200, content_type="text/plain; charset=utf-8", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self._send_security_headers()
        self.end_headers()

    def _send_security_headers(self):
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)

    def _require_auth(self):
        if _authorized(self.headers.get("Authorization")):
            return True
        body = "認証が必要です。".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="JStockWatch"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)
        return False

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except (TypeError, ValueError):
            return {}
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, MAX_BODY))  # 上限を超える分は読まない
        try:
            # NaN/Infinity は None に正規化（不正JSON混入対策）
            return json.loads(raw.decode("utf-8"), parse_constant=lambda c: None)
        except Exception:
            return {}

    def _handle_get(self, head_only=False):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/healthz":
                if head_only:
                    return self._send_empty(200, "application/json; charset=utf-8")
                return self._send_json({"ok": True, "service": "JStockWatch"})
            if head_only:
                if path == "/" or path == "/index.html":
                    return self._send_static_head("index.html")
                if path.startswith("/static/"):
                    return self._send_static_head(path[len("/static/"):])
                if path.startswith("/api/") or path in ("/api/market", "/api/recommendations"):
                    return self._send_empty(405)
                return self._send_empty(404)
            if path == "/" or path == "/index.html":
                return self._serve_static("index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/"):])
            if path == "/api/market":
                return self._send_json(api_market(qs))
            if path == "/api/recommendations":
                return self._send_json(api_recommendations(qs))
            if path == "/api/search":
                return self._send_json(api_search(qs))
            if path == "/api/master":
                return self._send_json(api_master())
            if path == "/api/defaults":
                return self._send_json(api_defaults())
            if path == "/api/news":
                return self._send_json(api_news(qs))
            if path == "/api/stock-news":
                return self._send_json(api_stock_news(qs))
            if path == "/api/watchlist":
                return self._send_json(api_watchlist_get())
            if path == "/api/portfolio":
                return self._send_json(api_portfolio_get(qs))
            if path.startswith("/api/stock/"):
                code = unquote(path[len("/api/stock/"):])
                return self._send_json(api_stock(code, qs))
            return self._send_json({"error": "not found", "path": path}, 404)
        except BrokenPipeError:
            pass
        except ClientError as e:
            self._send_json({"error": e.message}, e.status)
        except Exception as e:
            sys.stderr.write("[error] %s: %s\n" % (self.path, e))
            self._send_json({"error": "サーバ内部でエラーが発生しました"}, 500)

    # ---- HEAD ----
    def do_HEAD(self):
        return self._handle_get(head_only=True)

    # ---- GET ----
    def do_GET(self):
        return self._handle_get(head_only=False)

    # ---- POST ----
    def do_POST(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json_body()
            if path == "/api/portfolio/evaluate":
                holdings = body.get("holdings") or []
                norm = [_normalize_holding(h) for h in holdings if h.get("code")]
                return self._send_json(_evaluate_holdings(norm, force=bool(body.get("force"))))
            if path == "/api/watchlist":
                code = (body.get("code") or "").strip()
                if not code:
                    return self._send_json({"error": "code required"}, 400)
                return self._send_json({"items_codes": storage.add_to_watchlist(code)})
            if path == "/api/portfolio":
                if not body.get("code") or body.get("buy_price") in (None, "") or body.get("shares") in (None, ""):
                    return self._send_json({"error": "code, shares, buy_price は必須です"}, 400)
                item = storage.add_holding(body)
                return self._send_json({"item": item})
            return self._send_json({"error": "not found"}, 404)
        except ClientError as e:
            self._send_json({"error": e.message}, e.status)
        except Exception as e:
            sys.stderr.write("[error] %s: %s\n" % (self.path, e))
            self._send_json({"error": "サーバ内部でエラーが発生しました"}, 500)

    # ---- PUT ----
    def do_PUT(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json_body()
            if path.startswith("/api/portfolio/"):
                id_str = path[len("/api/portfolio/"):]
                if not id_str.isdigit():
                    return self._send_json({"error": "invalid id"}, 400)
                hid = int(id_str)
                updated = storage.update_holding(hid, body)
                if updated is None:
                    return self._send_json({"error": "not found"}, 404)
                return self._send_json({"item": updated})
            return self._send_json({"error": "not found"}, 404)
        except ClientError as e:
            self._send_json({"error": e.message}, e.status)
        except Exception as e:
            sys.stderr.write("[error] %s: %s\n" % (self.path, e))
            self._send_json({"error": "サーバ内部でエラーが発生しました"}, 500)

    # ---- DELETE ----
    def do_DELETE(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/portfolio/"):
                id_str = path[len("/api/portfolio/"):]
                if not id_str.isdigit():
                    return self._send_json({"error": "invalid id"}, 400)
                storage.remove_holding(int(id_str))
                return self._send_json({"ok": True})
            if path.startswith("/api/watchlist/"):
                code = unquote(path[len("/api/watchlist/"):])
                return self._send_json({"items_codes": storage.remove_from_watchlist(code)})
            return self._send_json({"error": "not found"}, 404)
        except ClientError as e:
            self._send_json({"error": e.message}, e.status)
        except Exception as e:
            sys.stderr.write("[error] %s: %s\n" % (self.path, e))
            self._send_json({"error": "サーバ内部でエラーが発生しました"}, 500)

    # ---- 静的ファイル（パストラバーサル対策つき） ----
    def _serve_static(self, rel):
        rel = rel.lstrip("/")
        full = _safe_static_path(rel)
        if not full:
            return self._send_json({"error": "forbidden"}, 403)
        if not os.path.isfile(full):
            return self._send_json({"error": "not found"}, 404)
        try:
            return self._send_file(full, _content_type(full))
        except OSError:
            return self._send_json({"error": "not found"}, 404)

    def _send_static_head(self, rel):
        rel = rel.lstrip("/")
        full = _safe_static_path(rel)
        if not full:
            return self._send_empty(403, "application/json; charset=utf-8")
        if not os.path.isfile(full):
            return self._send_empty(404, "application/json; charset=utf-8")
        try:
            size = os.path.getsize(full)
        except OSError:
            return self._send_empty(404, "application/json; charset=utf-8")
        self.send_response(200)
        self.send_header("Content-Type", _content_type(full))
        self.send_header("Content-Length", str(size))
        self._send_security_headers()
        self.end_headers()


def _safe_static_path(rel):
    # realpath でシンボリックリンクも解決し、区切り文字付きで厳密に内包判定する
    # （末尾セパレータが無いと static_secret のような兄弟ディレクトリを誤許可するため）
    full = os.path.realpath(os.path.join(STATIC_DIR, rel))
    if full != STATIC_DIR and not full.startswith(STATIC_DIR + os.sep):
        return None
    return full


_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _content_type(path):
    _, ext = os.path.splitext(path.lower())
    return _CTYPES.get(ext, "application/octet-stream")


def _now_str():
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _lan_ip():
    """このMacのLAN内IPアドレスを推定する（外部通信はしない）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # ルート決定のみ。実際の送信はしない
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    local_url = "http://127.0.0.1:%d/" % PORT
    ip = _lan_ip() if HOST == "0.0.0.0" else None
    print("=" * 60)
    print("  日本株ウォッチ を起動しました")
    print("  このMacで開く : " + local_url)
    if ip:
        print("  iPhone等で開く: http://%s:%d/" % (ip, PORT))
        print("    ※ iPhoneがこのMacと同じWi-Fiに繋がっている必要があります")
        print("    ※ 上のURLをiPhoneのSafariのアドレス欄に入力してください")
    print("  PIN保護      : " + ("有効" if APP_PIN else "無効"))
    print("  終了するには、このウィンドウで Ctrl + C")
    print("=" * 60)

    # ローカル起動時のみブラウザを自動で開く（クラウド等のブラウザ無し環境では無視）
    def _open_browser():
        try:
            if os.environ.get("NO_BROWSER") != "1":
                webbrowser.open(local_url)
        except Exception:
            pass
    threading.Timer(1.0, _open_browser).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します。")
        httpd.shutdown()
        _pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
