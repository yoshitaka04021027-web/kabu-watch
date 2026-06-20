# -*- coding: utf-8 -*-

import os
import re
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class StaticContractTests(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
            return f.read()

    def test_local_storage_keys_stay_backward_compatible(self):
        js = self.read("app/static/app.js")
        keys = dict(re.findall(r'const\s+(LS_[A-Z]+)\s*=\s*"([^"]+)"', js))
        self.assertEqual(keys["LS_WATCH"], "jsw_watchlist_v1")
        self.assertEqual(keys["LS_PORT"], "jsw_portfolio_v1")
        self.assertEqual(keys["LS_TAB"], "jsw_active_tab_v1")

    def test_backup_import_still_accepts_legacy_array_payload(self):
        js = self.read("app/static/app.js")
        self.assertIn("const portfolio = Array.isArray(data) ? data : data.portfolio;", js)
        self.assertIn("setPort(portfolio.map((h, i) => ({ ...h, id: h.id || i + 1 })))", js)

    def test_accessibility_landmarks_are_present(self):
        html = self.read("app/static/index.html")
        self.assertIn('role="tablist"', html)
        self.assertIn('role="dialog"', html)
        self.assertIn('aria-live="polite"', html)


if __name__ == "__main__":
    unittest.main()
