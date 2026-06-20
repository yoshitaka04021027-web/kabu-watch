# -*- coding: utf-8 -*-

import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
sys.path.insert(0, APP_DIR)

import app


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.APP_PIN = ""
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path)
            res = conn.getresponse()
            body = res.read()
            return res, body
        finally:
            conn.close()

    def assert_security_headers(self, res):
        self.assertEqual(res.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.getheader("Referrer-Policy"), "no-referrer")
        self.assertEqual(res.getheader("X-Frame-Options"), "DENY")
        csp = res.getheader("Content-Security-Policy")
        self.assertIsNotNone(csp)
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)

    def test_head_root_returns_200_without_body(self):
        res, body = self.request("HEAD", "/")
        self.assertEqual(res.status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(res.getheader("Content-Type"), "text/html; charset=utf-8")
        self.assert_security_headers(res)

    def test_healthz_returns_json_and_security_headers(self):
        res, body = self.request("GET", "/healthz")
        self.assertEqual(res.status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["ok"], True)
        self.assert_security_headers(res)

    def test_bad_recommendation_params_return_400(self):
        res, body = self.request("GET", "/api/recommendations?horizon=daytrade")
        self.assertEqual(res.status, 400)
        self.assertIn("horizon", json.loads(body.decode("utf-8"))["error"])
        self.assert_security_headers(res)

    def test_too_large_top_returns_400(self):
        res, body = self.request("GET", "/api/recommendations?horizon=short&top=999")
        self.assertEqual(res.status, 400)
        self.assertIn("top", json.loads(body.decode("utf-8"))["error"])


if __name__ == "__main__":
    unittest.main()
