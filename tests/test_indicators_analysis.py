# -*- coding: utf-8 -*-

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
sys.path.insert(0, APP_DIR)

import analysis
import indicators


def sample_stock(days=260, step=1.0, fundamentals=None):
    closes = [100.0 + i * step for i in range(days)]
    return {
        "code": "TEST",
        "name": "テスト銘柄",
        "sector": "テスト",
        "price": closes[-1],
        "prev_close": closes[-2],
        "week52_high": max(closes),
        "week52_low": min(closes),
        "dates": [f"2026-01-{(i % 28) + 1:02d}" for i in range(days)],
        "open": closes[:],
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": [1000 + (i % 7) * 20 for i in range(days)],
        "fundamentals": fundamentals or {},
    }


class IndicatorTests(unittest.TestCase):
    def test_sma_keeps_length_and_calculates_window_average(self):
        self.assertEqual(indicators.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_rsi_handles_flat_series_as_neutral(self):
        values = [100.0] * 20
        self.assertEqual(indicators.rsi(values, 14)[14], 50.0)

    def test_crossed_up_detects_recent_cross(self):
        fast = [1, 1, 3]
        slow = [2, 2, 2]
        self.assertEqual(indicators.crossed_up(fast, slow), 0)


class AnalysisTests(unittest.TestCase):
    def test_analyze_stock_returns_long_term_indicators_with_enough_data(self):
        snap = analysis.analyze_stock(sample_stock())
        self.assertEqual(snap["n_days"], 260)
        self.assertIsNotNone(snap["indicators"]["sma200"])
        self.assertIn(snap["short"]["verdict"], {"強い注目候補", "やや良好", "中立", "やや弱い", "弱い"})

    def test_long_score_uses_available_fundamentals_without_penalizing_missing_fields(self):
        stock = sample_stock(fundamentals={
            "trailing_pe": 18.2,
            "price_to_book": 1.4,
            "dividend_yield_pct": 2.3,
            "roe_pct": 12.5,
        })
        snap = analysis.analyze_stock(stock)
        active_labels = [r["label"] for r in snap["long"]["reasons"] if r["active"]]
        self.assertIn("PERが極端に高すぎない", active_labels)
        self.assertIn("ROEが良好", active_labels)


if __name__ == "__main__":
    unittest.main()
