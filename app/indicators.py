# -*- coding: utf-8 -*-
"""テクニカル指標の計算（標準ライブラリのみ）。

すべて「終値リスト等を渡すと、各日に対応する指標の系列（リスト）を返す」
という方針。先頭の計算不能な部分は None で埋め、長さを入力と揃える。
"""

import math


def sma(values, n):
    """単純移動平均（Simple Moving Average）。"""
    out = [None] * len(values)
    if n <= 0:
        return out
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(values, n):
    """指数移動平均（Exponential Moving Average）。
    初期値は最初のn個の単純平均（一般的な実装）。"""
    out = [None] * len(values)
    if len(values) < n or n <= 0:
        return out
    k = 2.0 / (n + 1.0)
    seed = sum(values[:n]) / n
    out[n - 1] = seed
    prev = seed
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values, n=14):
    """RSI（Wilderの平滑化方式）。0〜100。"""
    out = [None] * len(values)
    if len(values) <= n:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, n + 1):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / n
    avg_loss = losses / n
    out[n] = _rsi_value(avg_gain, avg_loss)
    for i in range(n + 1, len(values)):
        diff = values[i] - values[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain, avg_loss):
    if avg_loss == 0:
        # 上げも下げも無い（完全な横ばい）なら中立の50。下げだけ0なら100。
        return 50.0 if avg_gain == 0 else 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(values, fast=12, slow=26, signal=9):
    """MACD。戻り値: (macd_line, signal_line, histogram) の3系列。"""
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line = [None] * len(values)
    for i in range(len(values)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]
    # signal は macd_line(欠損を除いた部分)のEMA
    valid = [(i, m) for i, m in enumerate(macd_line) if m is not None]
    signal_line = [None] * len(values)
    hist = [None] * len(values)
    if len(valid) >= signal:
        seq = [m for _, m in valid]
        sig_seq = ema(seq, signal)
        for j, (i, _) in enumerate(valid):
            if sig_seq[j] is not None:
                signal_line[i] = sig_seq[j]
                hist[i] = macd_line[i] - sig_seq[j]
    return macd_line, signal_line, hist


def bollinger(values, n=20, k=2.0):
    """ボリンジャーバンド。戻り値: (upper, mid(=SMA), lower)。"""
    if n <= 0:
        return [None] * len(values), [None] * len(values), [None] * len(values)
    mid = sma(values, n)
    upper = [None] * len(values)
    lower = [None] * len(values)
    for i in range(len(values)):
        if i >= n - 1:
            window = values[i - n + 1:i + 1]
            mean = mid[i]
            var = sum((x - mean) ** 2 for x in window) / n
            sd = math.sqrt(var)
            upper[i] = mean + k * sd
            lower[i] = mean - k * sd
    return upper, mid, lower


def atr(highs, lows, closes, n=14):
    """ATR（Average True Range, Wilder平滑化）。ボラティリティの目安。"""
    out = [None] * len(closes)
    # high/low/close の長さが揃わない呼び出しでも壊れないよう共通長で処理する。
    m = min(len(highs), len(lows), len(closes))
    if m <= n:
        return out
    trs = [None]
    for i in range(1, m):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    first = sum(trs[1:n + 1]) / n
    out[n] = first
    prev = first
    for i in range(n + 1, m):
        prev = (prev * (n - 1) + trs[i]) / n
        out[i] = prev
    return out


def slope(values, n):
    """直近n点の線形回帰の傾き（トレンドの向きと強さ）。
    値の単位は「1日あたりの平均変化量」。"""
    pts = [v for v in values[-n:] if v is not None]
    if len(pts) < 2:
        return None
    m = len(pts)
    xs = list(range(m))
    mean_x = sum(xs) / m
    mean_y = sum(pts) / m
    num = sum((xs[i] - mean_x) * (pts[i] - mean_y) for i in range(m))
    den = sum((xs[i] - mean_x) ** 2 for i in range(m))
    if den == 0:
        return None
    return num / den


def last_valid(series):
    """系列の末尾から見て最初の非Noneを返す。"""
    for v in reversed(series):
        if v is not None:
            return v
    return None


def crossed_up(fast_series, slow_series):
    """直近でfastがslowを下から上に抜けたか（ゴールデンクロス）。
    戻り値: クロスが起きてから何日経過したか（0=当日, None=未発生/データ不足）。"""
    return _cross(fast_series, slow_series, up=True)


def crossed_down(fast_series, slow_series):
    """デッドクロス（fastがslowを上から下に抜けた）。"""
    return _cross(fast_series, slow_series, up=False)


def _cross(fast_series, slow_series, up):
    pairs = [
        (i, fast_series[i], slow_series[i])
        for i in range(len(fast_series))
        if fast_series[i] is not None and slow_series[i] is not None
    ]
    if len(pairs) < 2:
        return None
    # 直近から遡ってクロス点を探す（最大60営業日）
    n = len(pairs)
    for back in range(1, min(n, 60) + 1):
        i_cur = n - back
        i_prev = i_cur - 1
        if i_prev < 0:
            break
        _, f_cur, s_cur = pairs[i_cur]
        _, f_prev, s_prev = pairs[i_prev]
        if up and f_prev <= s_prev and f_cur > s_cur:
            return back - 1
        if (not up) and f_prev >= s_prev and f_cur < s_cur:
            return back - 1
    return None
