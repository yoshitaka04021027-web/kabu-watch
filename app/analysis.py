# -*- coding: utf-8 -*-
"""銘柄分析・シグナル生成・初心者向け解説。

重要: 本モジュールが返す「スコア」「おすすめ」「売却シグナル」は、
公開されている株価データとテクニカル指標にもとづく機械的な目安であり、
将来の値上がり・値下がりを保証するものではない。投資勧誘・助言ではない。
"""

import indicators as ind
import math


def _pct(a, b):
    """bに対するaの割合(%)。bが0/NoneならNone。"""
    if not b:
        return None
    return (a - b) / b * 100.0


def analyze_stock(stock):
    """1銘柄の指標スナップショット + 3つの時間軸スコアを計算して返す。"""
    closes = stock["close"]
    highs = stock["high"]
    lows = stock["low"]
    vols = stock["volume"]
    price = stock.get("price") or (closes[-1] if closes else None)

    snap = {
        "code": stock.get("code"),
        "name": stock.get("name"),
        "sector": stock.get("sector"),
        "price": price,
        "currency": stock.get("currency", "JPY"),
        "prev_close": stock.get("prev_close"),
        "week52_high": stock.get("week52_high"),
        "week52_low": stock.get("week52_low"),
        "market_time": stock.get("market_time"),
        "n_days": len(closes),
        "cache": stock.get("_cache"),
        "cache_age_sec": stock.get("_cache_age_sec"),
        "fetched_at": stock.get("fetched_at"),
        "data_source": stock.get("data_source") or "Yahoo Finance chart",
        "data_error": stock.get("_error"),
        "fundamentals_error": stock.get("_fundamentals_error") or (stock.get("fundamentals") or {}).get("_error"),
        "fundamentals": _round_fundamentals(stock.get("fundamentals") or {}),
    }

    if not closes or len(closes) < 30 or price is None:
        snap["insufficient"] = True
        snap["short"] = _empty_horizon("短期")
        snap["mid"] = _empty_horizon("中期")
        snap["long"] = _empty_horizon("長期")
        return snap

    # --- 指標群 ---
    sma5 = ind.sma(closes, 5)
    sma25 = ind.sma(closes, 25)
    sma75 = ind.sma(closes, 75)
    sma200 = ind.sma(closes, 200)
    rsi14 = ind.rsi(closes, 14)
    macd_line, signal_line, hist = ind.macd(closes)
    up_bb, mid_bb, low_bb = ind.bollinger(closes, 20, 2)
    atr14 = ind.atr(highs, lows, closes, 14)

    v_sma5 = ind.last_valid(ind.sma(vols, 5))
    v_sma25 = ind.last_valid(ind.sma(vols, 25))

    L = {
        "sma5": ind.last_valid(sma5),
        "sma25": ind.last_valid(sma25),
        "sma75": ind.last_valid(sma75),
        "sma200": ind.last_valid(sma200),
        "rsi": ind.last_valid(rsi14),
        "macd": ind.last_valid(macd_line),
        "signal": ind.last_valid(signal_line),
        "hist": ind.last_valid(hist),
        "bb_up": ind.last_valid(up_bb),
        "bb_low": ind.last_valid(low_bb),
        "atr": ind.last_valid(atr14),
    }

    change = _pct(price, snap["prev_close"]) if snap["prev_close"] else None
    pos52 = None
    if snap["week52_high"] and snap["week52_low"] and snap["week52_high"] != snap["week52_low"]:
        pos52 = (price - snap["week52_low"]) / (snap["week52_high"] - snap["week52_low"]) * 100.0
        # リアルタイム株価が52週高値を更新中だと100超になり得るため0〜100に収める。
        pos52 = max(0.0, min(100.0, pos52))

    vol_ratio = (v_sma5 / v_sma25) if (v_sma5 and v_sma25) else None
    slope25 = ind.slope(sma25, 10)
    slope75 = ind.slope([x for x in sma75 if x is not None], 20) if any(x is not None for x in sma75) else None
    slope200 = ind.slope([x for x in sma200 if x is not None], 20) if any(x is not None for x in sma200) else None

    gc_25_75 = ind.crossed_up(sma25, sma75)
    dc_25_75 = ind.crossed_down(sma25, sma75)
    gc_macd = ind.crossed_up(macd_line, signal_line)
    dc_macd = ind.crossed_down(macd_line, signal_line)

    atr_pct = (L["atr"] / price * 100.0) if (L["atr"] and price) else None

    snap["indicators"] = {
        "change_pct": _round(change),
        "rsi": _round(L["rsi"]),
        "sma5": _round(L["sma5"]),
        "sma25": _round(L["sma25"]),
        "sma75": _round(L["sma75"]),
        "sma200": _round(L["sma200"]),
        "macd": _round(L["macd"], 2),
        "macd_signal": _round(L["signal"], 2),
        "macd_hist": _round(L["hist"], 2),
        "bb_upper": _round(L["bb_up"]),
        "bb_lower": _round(L["bb_low"]),
        "atr": _round(L["atr"], 2),
        "atr_pct": _round(atr_pct),
        "pos52": _round(pos52),
        "vol_ratio": _round(vol_ratio, 2),
    }

    ctx = {
        "price": price, "L": L, "rsi": L["rsi"], "change": change, "pos52": pos52,
        "vol_ratio": vol_ratio, "slope25": slope25, "slope75": slope75,
        "slope200": slope200, "gc_25_75": gc_25_75, "dc_25_75": dc_25_75,
        "gc_macd": gc_macd, "dc_macd": dc_macd, "atr_pct": atr_pct,
        "fund": snap["fundamentals"],
    }

    snap["short"] = _score_short(ctx)
    snap["mid"] = _score_mid(ctx)
    snap["long"] = _score_long(ctx)
    # チャート描画用に終値（直近120日）と日付を軽量で同梱
    snap["spark"] = closes[-120:]
    snap["spark_dates"] = stock["dates"][-120:]
    return snap


def _empty_horizon(label):
    return {"label": label, "score": None, "verdict": "データ不足",
            "reasons": [], "summary": "分析に必要な日数のデータが取得できませんでした。"}


# ---------------------------------------------------------------------------
# スコアリング: 各時間軸ごとに「条件 → 加点/減点 + 初心者向け解説」を組み立てる
# ---------------------------------------------------------------------------

def _factor(label, detail, met, weight, good=True):
    """1つの判断材料。met=Trueなら weight 点（goodならプラス、悪材料ならマイナス）。"""
    return {
        "label": label,
        "detail": detail,
        "met": bool(met),
        "weight": weight,
        "good": good,
        "points": (weight if good else -weight) if met else 0,
    }


def _finalize(label, horizon_desc, factors):
    pos_total = sum(f["weight"] for f in factors if f["good"])
    achieved = sum(f["points"] for f in factors)
    # 50 を「中立」の基準点とする。強気材料が揃うほど100へ、弱気材料が勝つほど0へ。
    # 何のシグナルも出ていない横ばい銘柄は 0（弱い）ではなく 50（中立）になる。
    if pos_total == 0:
        score = 50
    else:
        score = round(50.0 + 50.0 * (achieved / pos_total))
    score = max(0, min(100, score))

    verdict, tone = _verdict_from_score(score)
    reasons = [
        {"label": f["label"], "detail": f["detail"],
         "type": ("good" if f["good"] else "bad"), "active": f["met"]}
        for f in factors
    ]
    actives = [f for f in factors if f["met"]]
    summary = _build_summary(label, horizon_desc, score, verdict, actives)
    return {"label": label, "horizon": horizon_desc, "score": score,
            "verdict": verdict, "tone": tone, "reasons": reasons, "summary": summary}


def _verdict_from_score(score):
    if score >= 70:
        return "強い注目候補", "strong"
    if score >= 55:
        return "やや良好", "buy"
    if score >= 45:
        return "中立", "neutral"
    if score >= 30:
        return "やや弱い", "weak"
    return "弱い", "bearish"


def _build_summary(label, horizon_desc, score, verdict, actives):
    good = [f["label"] for f in actives if f["good"]]
    bad = [f["label"] for f in actives if not f["good"]]
    parts = [f"【{label}（{horizon_desc}）】総合スコア {score}/100：{verdict}。"]
    if good:
        parts.append("プラス材料：" + "、".join(good) + "。")
    if bad:
        parts.append("注意点：" + "、".join(bad) + "。")
    if not good and not bad:
        parts.append("目立ったシグナルはありません。")
    return " ".join(parts)


def _score_short(c):
    """短期（数日〜2,3週間）：勢い・モメンタム重視。"""
    L, price, rsi = c["L"], c["price"], c["rsi"]
    factors = [
        _factor(
            "株価が5日移動平均より上",
            "5日移動平均線は『直近5日間の平均値段』。今の株価がこれより上だと、ここ数日は買いの勢いが強い状態です。",
            L["sma5"] is not None and price > L["sma5"], 18),
        _factor(
            "株価が25日移動平均より上",
            "25日移動平均線は約1か月の平均。これより上なら短期トレンドは上向きと判断できます。",
            L["sma25"] is not None and price > L["sma25"], 16),
        _factor(
            "MACDが上向きサイン（ゴールデンクロス）",
            "MACDは2本の線で勢いの変化を見る指標。下の線(シグナル)を上に抜けると『上昇に転じたサイン』とされます。",
            c["gc_macd"] is not None and c["gc_macd"] <= 8, 18),
        _factor(
            "MACDがプラス圏で上昇基調",
            "MACDの棒(ヒストグラム)がプラスだと、上昇の勢いが続いていることを示します。",
            L["hist"] is not None and L["hist"] > 0, 12),
        _factor(
            "RSIが上昇基調(50〜70)",
            "RSIは『買われすぎ・売られすぎ』を0〜100で表す指標。50〜70は、勢いはあるがまだ過熱しすぎていない健全な状態です。",
            rsi is not None and 50 <= rsi <= 70, 14),
        _factor(
            "出来高が増加（注目度アップ）",
            "出来高は売買された株数。直近5日平均が約1か月平均を上回ると、その銘柄への注目が高まっているサインです。",
            c["vol_ratio"] is not None and c["vol_ratio"] >= 1.2, 12),
        _factor(
            "短期トレンドが上向き",
            "直近の25日線の傾きが上向きで、短期的な方向性が上向きであることを示します。",
            c["slope25"] is not None and c["slope25"] > 0, 10),
        # 悪材料（減点）
        _factor(
            "RSIが高すぎる（買われすぎ・過熱）",
            "RSIが70を超えると『買われすぎ』。短期的に上がりすぎで、近いうちに反落（一時的な下げ）の可能性があります。",
            rsi is not None and rsi > 70, 16, good=False),
        _factor(
            "MACDが売りサイン（デッドクロス）",
            "MACDが下に抜けると『下落に転じたサイン』。短期の勢いが弱まっている合図です。",
            c["dc_macd"] is not None and c["dc_macd"] <= 5, 14, good=False),
    ]
    return _finalize("短期", "数日〜2・3週間", factors)


def _score_mid(c):
    """中期（1〜6か月）：トレンドの方向と質を重視。"""
    L, price, rsi = c["L"], c["price"], c["rsi"]
    factors = [
        _factor(
            "中期トレンドが上昇（25日線 > 75日線）",
            "短い平均線(25日)が長い平均線(75日)より上にあると、1〜数か月の中期トレンドが上向きと判断できます。",
            L["sma25"] is not None and L["sma75"] is not None and L["sma25"] > L["sma75"], 18),
        _factor(
            "株価が75日移動平均より上",
            "75日移動平均は約3〜4か月の平均。これより上なら中期的に買い手が優勢です。",
            L["sma75"] is not None and price > L["sma75"], 16),
        _factor(
            "ゴールデンクロス発生（25日線が75日線を上抜け）",
            "中期の上昇転換を示す代表的なサイン。最近これが起きていれば、上昇トレンドの初期段階かもしれません。",
            c["gc_25_75"] is not None and c["gc_25_75"] <= 25, 18),
        _factor(
            "75日線が上向き",
            "中期の平均線そのものが右肩上がりで、トレンドが継続していることを示します。",
            c["slope75"] is not None and c["slope75"] > 0, 14),
        _factor(
            "RSIが健全（40〜65）",
            "中期では40〜65が理想。極端な過熱でも売られすぎでもなく、上昇余地を残した状態です。",
            rsi is not None and 40 <= rsi <= 65, 12),
        _factor(
            "MACDがプラス圏",
            "中期の勢いがプラス方向にあることを示します。",
            L["macd"] is not None and L["macd"] > 0, 10),
        _factor(
            "52週レンジで上位（高値更新に近い強さ）",
            "過去1年の値幅の中で上の方にいると、強い銘柄である証拠。ただし高すぎると割高な点に注意。",
            c["pos52"] is not None and c["pos52"] >= 55, 12),
        # 悪材料
        _factor(
            "デッドクロス（25日線が75日線を下抜け）",
            "中期の下落転換を示すサイン。トレンドが下向きに変わった可能性があります。",
            c["dc_25_75"] is not None and c["dc_25_75"] <= 25, 18, good=False),
        _factor(
            "高値圏で過熱（52週レンジ上限付近 & RSI高）",
            "1年の高値圏でRSIも高いと、短期的な買われすぎで反落リスクがあります。",
            c["pos52"] is not None and c["pos52"] > 92 and rsi is not None and rsi > 70, 12, good=False),
    ]
    return _finalize("中期", "1〜6か月", factors)


def _score_long(c):
    """長期（半年〜数年）：大きなトレンドと底堅さを重視。"""
    L, price, rsi = c["L"], c["price"], c["rsi"]
    factors = [
        _factor(
            "長期トレンドが上昇（株価が200日線より上）",
            "200日移動平均は約1年の平均で、長期投資家が最も重視する線。これより上なら長期トレンドは上向きです。",
            L["sma200"] is not None and price > L["sma200"], 22),
        _factor(
            "200日線が上向き",
            "1年の平均線そのものが右肩上がりなら、長期で着実に成長している企業の可能性が高いです。",
            c["slope200"] is not None and c["slope200"] > 0, 18),
        _factor(
            "強い並び（株価 > 75日線 > 200日線）",
            "短・中・長期の線がきれいに上から株価→75日→200日の順に並ぶ状態は『パーフェクトオーダー』と呼ばれ、強い上昇トレンドの典型です。",
            L["sma75"] is not None and L["sma200"] is not None and price > L["sma75"] > L["sma200"], 18),
        _factor(
            "52週安値から十分に上昇（底堅い）",
            "1年の最安値からしっかり上昇していれば、下値が固く上昇基調にあると考えられます。",
            c["pos52"] is not None and c["pos52"] >= 40, 12),
        _factor(
            "値動きが極端に荒くない（安定）",
            "1日の値動きの幅(ATR)が株価の5%以内なら、長期で安心して持ちやすい比較的安定した銘柄です。",
            c["atr_pct"] is not None and c["atr_pct"] <= 5, 10),
        # 悪材料
        _factor(
            "長期トレンドが下向き（200日線より下）",
            "株価が1年の平均線より下にあると、長期トレンドは下向き。長期保有には慎重さが必要です。",
            L["sma200"] is not None and price < L["sma200"], 22, good=False),
        _factor(
            "52週安値圏（下落が続いている）",
            "1年の安値付近にあると、まだ下落が続いている可能性があります。安いからと安易に飛びつくのは危険です。",
            c["pos52"] is not None and c["pos52"] < 20, 12, good=False),
    ] + _fundamental_factors(c.get("fund") or {})
    return _finalize("長期", "半年〜数年", factors)


def _round(v, n=1):
    if v is None:
        return None
    try:
        f = float(v)
        if not math.isfinite(f):
            return None
        return round(f, n)
    except (TypeError, ValueError):
        return None


def _round_fundamentals(f):
    keys = {
        "trailing_pe": 1,
        "forward_pe": 1,
        "price_to_book": 1,
        "dividend_yield_pct": 2,
        "payout_ratio_pct": 1,
        "roe_pct": 1,
        "profit_margin_pct": 1,
        "revenue_growth_pct": 1,
        "earnings_growth_pct": 1,
        "debt_to_equity": 1,
        "beta": 2,
    }
    out = {
        "market_cap": f.get("market_cap"),
        "market_cap_display": f.get("market_cap_display"),
        "source": f.get("source"),
        "cache": f.get("_cache"),
    }
    for k, n in keys.items():
        out[k] = _round(f.get(k), n)
    return out


def _fundamental_factors(f):
    """取れた指標だけを長期評価に足す。欠損は評価対象外にしてスコアを不当に下げない。"""
    factors = []
    pe = f.get("trailing_pe") or f.get("forward_pe")
    pbr = f.get("price_to_book")
    div = f.get("dividend_yield_pct")
    roe = f.get("roe_pct")
    rev = f.get("revenue_growth_pct")
    earn = f.get("earnings_growth_pct")
    debt = f.get("debt_to_equity")
    if pe is not None:
        factors.append(_factor(
            "PERが極端に高すぎない",
            "PERは利益に対して株価が何倍まで買われているかの目安。極端に高い場合は期待先行で反落しやすい点に注意します。",
            0 < pe <= 35, 6))
        factors.append(_factor(
            "PERが高水準（期待先行に注意）",
            "PERが非常に高い場合、将来成長への期待がかなり織り込まれている可能性があります。",
            pe >= 50, 6, good=False))
    if pbr is not None:
        factors.append(_factor(
            "PBRが過度に割高ではない",
            "PBRは純資産に対する株価の倍率です。業種差はありますが、極端な高さでなければ長期保有の負担は比較的小さめです。",
            0 < pbr <= 4, 5))
    if div is not None:
        factors.append(_factor(
            "配当利回りがある",
            "配当利回りがある銘柄は、値上がり益だけでなく配当も長期リターンの支えになります。",
            div >= 1.5, 5))
    if roe is not None:
        factors.append(_factor(
            "ROEが良好",
            "ROEは自己資本を使って利益を生む力の目安。8%以上なら資本効率は比較的良好と見ます。",
            roe >= 8, 7))
    if rev is not None:
        factors.append(_factor(
            "売上成長がプラス",
            "売上が伸びている企業は、事業規模の拡大が株価の長期的な支えになりやすいです。",
            rev > 0, 5))
    if earn is not None:
        factors.append(_factor(
            "利益成長がプラス",
            "利益が伸びていると、配当や投資余力が増えやすく、長期評価の支えになります。",
            earn > 0, 6))
        factors.append(_factor(
            "利益成長がマイナス",
            "利益が落ちている場合、株価が上がっていても業績面の裏付けが弱くなる点に注意です。",
            earn < 0, 6, good=False))
    if debt is not None:
        factors.append(_factor(
            "負債比率が高め",
            "Debt/Equityが高い場合、金利上昇や景気悪化の局面で財務負担が重くなりやすいです。",
            debt >= 200, 5, good=False))
    return factors


# ---------------------------------------------------------------------------
# 保有銘柄の売却判定
# ---------------------------------------------------------------------------

def evaluate_holding(holding, snap):
    """保有銘柄に対して『売るべきか』を判定し、初心者向けに理由を説明する。

    holding: {code, name, shares, buy_price, buy_date, target_price?, stop_loss_pct?}
    snap: analyze_stock の結果
    """
    price = snap.get("price")
    buy = holding.get("buy_price")
    shares = holding.get("shares") or 0
    stop_pct = holding.get("stop_loss_pct")
    if stop_pct in (None, ""):
        stop_pct = 8.0  # 既定の損切りライン: -8%
    stop_pct = float(stop_pct)
    target = holding.get("target_price")

    ind_ = snap.get("indicators", {})
    sma25 = ind_.get("sma25")
    sma75 = ind_.get("sma75")
    sma200 = ind_.get("sma200")
    rsi = ind_.get("rsi")

    pl_pct = _pct(price, buy) if (price and buy) else None
    pl_per_share = (price - buy) if (price and buy) else None
    pl_total = (pl_per_share * shares) if (pl_per_share is not None and shares) else None

    reasons = []   # 各シグナル: {label, detail, severity}
    # severity: "danger"(損切り), "warn"(売却/利確検討), "info"(注意), "good"(継続材料)

    # 1) 損切りライン割れ
    if pl_pct is not None and pl_pct <= -stop_pct:
        reasons.append({
            "label": f"損切りライン(-{stop_pct:.0f}%)を下回っています",
            "detail": (
                f"買った値段より{abs(pl_pct):.1f}%下がっています。株式投資で最も大切なのは"
                "『損失を小さく抑えること』です。あらかじめ決めた損切りラインを割ったら、"
                "感情で粘らず一度売って仕切り直すのが基本とされています（損切り・ロスカット）。"),
            "severity": "danger",
        })

    # 2) 200日線割れ（長期トレンド崩れ）
    if price and sma200 and price < sma200:
        reasons.append({
            "label": "長期トレンドの節目（200日線）を下回っています",
            "detail": (
                "200日移動平均線は約1年の平均で、長期トレンドの分かれ目です。"
                "ここを下回ると長期の上昇基調が崩れた可能性があり、長く持つ前提が変わってきます。"),
            "severity": "warn",
        })

    # 3) デッドクロス相当（25日線 < 75日線）= 中期トレンド転換
    if sma25 and sma75 and sma25 < sma75:
        reasons.append({
            "label": "中期トレンドが下向きに転換（25日線 < 75日線）",
            "detail": (
                "短い平均線(25日)が長い平均線(75日)を下回る『デッドクロス』の状態です。"
                "数か月単位のトレンドが下向きに変わったサインとされ、利益が乗っているなら"
                "確保（利確）を、含み損なら撤退を検討する場面です。"),
            "severity": "warn",
        })

    # 4) 短期の勢い喪失（25日線割れ）
    elif price and sma25 and price < sma25:
        reasons.append({
            "label": "短期の勢いが弱まっています（25日線割れ）",
            "detail": (
                "株価が25日移動平均線を下回りました。短期的な買いの勢いが落ちている合図です。"
                "すぐ売る必要はありませんが、下げが続かないか注視しましょう。"),
            "severity": "info",
        })

    # 5) 買われすぎ（RSI高）＋ 含み益 → 利確検討
    if rsi is not None and rsi >= 75 and pl_pct is not None and pl_pct > 0:
        reasons.append({
            "label": "買われすぎ（RSIが高い）＋利益が出ている",
            "detail": (
                f"RSIが{rsi:.0f}と『買われすぎ』の水準です。短期的に上がりすぎていて反落しやすい"
                "状態なので、利益が出ている今のうちに一部を売って利益を確定（利確）する選択肢があります。"),
            "severity": "warn",
        })

    # 6) 目標株価に到達
    if target and price and price >= float(target):
        reasons.append({
            "label": f"目標株価({float(target):,.0f}円)に到達しました",
            "detail": (
                "自分で決めた目標値段に届きました。『どこで売るか』を最初に決めて、その通りに"
                "実行するのは初心者が最も成功しやすい方法のひとつです。計画通り利確を検討しましょう。"),
            "severity": "warn",
        })

    # 継続材料（売る理由が無いことを安心して伝える）
    if price and sma75 and price > sma75 and (sma25 and sma75 and sma25 >= sma75):
        reasons.append({
            "label": "トレンドは依然として上向き",
            "detail": (
                "株価は中期の平均線(75日)より上で、トレンドも上向きを保っています。"
                "慌てて売る理由は今のところ見当たりません。"),
            "severity": "good",
        })

    verdict, tone = _holding_verdict(reasons, pl_pct)
    summary = _holding_summary(holding, snap, verdict, pl_pct, pl_total, reasons, stop_pct, target)

    # 参考ライン
    stop_price = buy * (1 - stop_pct / 100.0) if buy else None

    return {
        "code": holding.get("code"),
        "name": holding.get("name") or snap.get("name"),
        "shares": shares,
        "buy_price": buy,
        "buy_date": holding.get("buy_date"),
        "price": price,
        "pl_pct": _round(pl_pct),
        "pl_per_share": _round(pl_per_share),
        "pl_total": _round(pl_total, 0),
        "target_price": float(target) if target else None,
        "stop_loss_pct": stop_pct,
        "stop_price": _round(stop_price, 0),
        "verdict": verdict,
        "tone": tone,
        "reasons": reasons,
        "summary": summary,
        "indicators": ind_,
        "spark": snap.get("spark"),
        "spark_dates": snap.get("spark_dates"),
    }


def _holding_verdict(reasons, pl_pct):
    sev = {r["severity"] for r in reasons}
    if "danger" in sev:
        return "損切り検討", "danger"
    warns = [r for r in reasons if r["severity"] == "warn"]
    if warns:
        if len(warns) >= 2:
            return "売却検討", "warn"
        # 単独の警告。「利確系（目標到達・買われすぎ）かつ含み益」なら利確寄りの表現に。
        # 200日線割れ・デッドクロス等の撤退系や、含み損のときは「売却検討」とする。
        profit_kw = ("利確", "買われすぎ", "目標株価", "到達")
        is_profit = (pl_pct is not None and pl_pct > 0 and
                     any(k in warns[0]["label"] for k in profit_kw))
        if is_profit:
            return "一部利確・売却検討", "warn"
        return "売却検討", "warn"
    if "info" in sev:
        return "様子見（注意）", "info"
    return "保有継続", "good"


def _holding_summary(holding, snap, verdict, pl_pct, pl_total, reasons, stop_pct, target):
    name = holding.get("name") or snap.get("name") or holding.get("code")
    head = f"「{name}」の判定：{verdict}。"
    if pl_pct is not None:
        sign = "＋" if pl_pct >= 0 else "－"
        money = ""
        if pl_total is not None:
            money = f"（概算損益 {('+' if pl_total >= 0 else '')}{pl_total:,.0f}円）"
        head += f" 現在の損益は{sign}{abs(pl_pct):.1f}%{money}。"
    triggers = [r["label"] for r in reasons if r["severity"] in ("danger", "warn")]
    if triggers:
        head += " 売却を検討する理由：" + "／".join(triggers) + "。"
    elif verdict == "保有継続":
        head += f" 今は売りのサインは出ていません。損切りライン(買値の-{stop_pct:.0f}%)を下回ったら見直しましょう。"
    return head


def recommend(snapshots, horizon, top_n=10, min_score=0):
    """スナップショット群を指定時間軸スコアで降順ソートして返す。"""
    key = horizon if horizon in ("short", "mid", "long") else "mid"
    scored = []
    for s in snapshots:
        if s.get("insufficient"):
            continue
        h = s.get(key) or {}
        sc = h.get("score")
        if sc is None or sc < min_score:
            continue
        scored.append((sc, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for sc, s in scored[:top_n]:
        h = s[key]
        out.append({
            "code": s.get("code"),
            "name": s.get("name"),
            "sector": s.get("sector"),
            "price": s.get("price"),
            "change_pct": s.get("indicators", {}).get("change_pct"),
            "score": sc,
            "verdict": h.get("verdict"),
            "tone": h.get("tone"),
            "summary": h.get("summary"),
            "reasons": [r for r in h.get("reasons", []) if r["active"]],
            "all_reasons": h.get("reasons", []),
            "indicators": s.get("indicators", {}),
            "fundamentals": s.get("fundamentals", {}),
            "cache": s.get("cache"),
            "cache_age_sec": s.get("cache_age_sec"),
            "fetched_at": s.get("fetched_at"),
            "data_source": s.get("data_source"),
            "data_error": s.get("data_error"),
            "fundamentals_error": s.get("fundamentals_error"),
            "n_days": s.get("n_days"),
            "spark": s.get("spark"),
            "spark_dates": s.get("spark_dates"),
            "week52_high": s.get("week52_high"),
            "week52_low": s.get("week52_low"),
        })
    return out
