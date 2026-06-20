# -*- coding: utf-8 -*-
"""ローカル保存（ポートフォリオ・ウォッチリスト）。

データは app/data/ 配下のJSONファイルに保存。DBサーバ不要。
スレッドセーフにするため読み書きをロックで保護する。
"""

import json
import math
import os
import threading
import time

import stocks

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")

_lock = threading.Lock()


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(tmp, path)  # アトミックに置き換え


# --- ウォッチリスト ---

def get_watchlist():
    with _lock:
        wl = _load(WATCHLIST_FILE, None)
        if not wl:
            wl = list(stocks.DEFAULT_WATCHLIST)
            _save(WATCHLIST_FILE, wl)
        return wl


def add_to_watchlist(code):
    code = stocks.to_code(code)
    with _lock:
        wl = _load(WATCHLIST_FILE, None) or list(stocks.DEFAULT_WATCHLIST)
        if code not in wl:
            wl.append(code)
            _save(WATCHLIST_FILE, wl)
        return wl


def remove_from_watchlist(code):
    code = stocks.to_code(code)
    with _lock:
        wl = _load(WATCHLIST_FILE, None) or list(stocks.DEFAULT_WATCHLIST)
        wl = [c for c in wl if c != code]
        _save(WATCHLIST_FILE, wl)
        return wl


# --- ポートフォリオ（保有銘柄） ---

def get_portfolio():
    with _lock:
        return _load(PORTFOLIO_FILE, [])


def add_holding(rec):
    """rec: {code, name, shares, buy_price, buy_date, target_price?, stop_loss_pct?, memo?}"""
    with _lock:
        pf = _load(PORTFOLIO_FILE, [])
        new_id = (max([h.get("id", 0) for h in pf]) + 1) if pf else 1
        code = stocks.to_code(rec.get("code", ""))
        item = {
            "id": new_id,
            "code": code,
            "name": rec.get("name") or stocks.name_of(code) or code,
            "shares": _num(rec.get("shares"), 0),
            "buy_price": _num(rec.get("buy_price"), 0),
            "buy_date": rec.get("buy_date") or time.strftime("%Y-%m-%d"),
            "target_price": _num(rec.get("target_price"), None),
            "stop_loss_pct": _num(rec.get("stop_loss_pct"), None),
            "memo": rec.get("memo", ""),
            "created_at": int(time.time()),
        }
        pf.append(item)
        _save(PORTFOLIO_FILE, pf)
        return item


def update_holding(holding_id, fields):
    with _lock:
        pf = _load(PORTFOLIO_FILE, [])
        for h in pf:
            if h.get("id") == holding_id:
                for k in ("shares", "buy_price", "target_price", "stop_loss_pct"):
                    if k in fields:
                        h[k] = _num(fields[k], None)
                for k in ("name", "buy_date", "memo"):
                    if k in fields:
                        h[k] = fields[k]
                _save(PORTFOLIO_FILE, pf)
                return h
        return None


def remove_holding(holding_id):
    with _lock:
        pf = _load(PORTFOLIO_FILE, [])
        pf = [h for h in pf if h.get("id") != holding_id]
        _save(PORTFOLIO_FILE, pf)
        return pf


def _num(v, default):
    if v in (None, ""):
        return default
    try:
        f = float(v)
        if not math.isfinite(f):  # NaN / Infinity を弾く（不正JSON混入対策）
            return default
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return default
