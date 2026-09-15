"""Read-only explorer integration checks against controlled public API responses."""
import base64
import hashlib
from http.client import HTTPConnection
import json
import threading
import unittest
from unittest.mock import patch

from explorer import ChainReader, ExplorerError, ExplorerServer, positive, tx_summary

ALICE = "luxar1qvt6tulyepwn387kr7n5c6m3hs9yh6rclr4v6g"
TXHASH = "A" * 64


class ReaderTests(unittest.TestCase):
    def test_positive_bounds(self):
        self.assertEqual(positive("156"), 156)
        for value in ("0", "-1", "1e3", "01", "9223372036854775808", "1&height=2"):
            with self.subTest(value=value), self.assertRaises(ExplorerError):
                positive(value)

    def test_routes_cannot_forward_arbitrary_node_requests(self):
        reader = ChainReader()
        with patch.object(reader, "read") as read:
            for path, query in (("/api/broadcast_tx_commit", {}), ("/api/tx/../status", {}),
                                ("/api/overview", {"url": ["http://example.com"]}),
                                ("/api/blocks", {"before": ["1", "2"]}),
                                ("/api/account/" + ALICE + "' OR tx.height>0", {})):
                with self.subTest(path=path), self.assertRaises(ExplorerError):
                    reader.api(path, query)
            read.assert_not_called()

    def test_block_hashes_actual_transaction_bytes(self):
        reader = ChainReader()
        raw = b"a serialized transaction"
        with patch.object(reader, "rpc", return_value={"block_id": {"hash": "BLOCK"},
             "block": {"header": {"height": "156"}, "data": {"txs": [base64.b64encode(raw).decode()]}}}):
            self.assertEqual(reader.block(156)["transactions"], [hashlib.sha256(raw).hexdigest().upper()])

    def test_failed_transaction_preserves_execution_code(self):
        result = tx_summary({"hash": TXHASH, "height": "9", "index": 0,
                             "tx_result": {"code": 5, "events": []}})
        self.assertEqual(result["code"], 5)
        self.assertEqual(result["actions"], [])

    def test_account_keeps_exact_units_and_deduplicates_activity(self):
        reader = ChainReader()
        tx = {"hash": TXHASH, "height": "9", "index": 0}
        with patch.object(reader, "rest", return_value={"balance": {"amount": "9007199254740993", "denom": "uluxar"}}), \
             patch.object(reader, "transactions", return_value={"items": [tx], "total": "1"}) as search:
            result = reader.account(ALICE)
        self.assertEqual(result["balance"]["amount"], "9007199254740993")
        self.assertEqual(result["transactions"], [tx])
        self.assertEqual(search.call_count, 2)

    def test_blocks_respect_retained_history(self):
        reader = ChainReader()
        with patch.object(reader, "rpc", return_value={"sync_info": {"latest_block_height": "80", "earliest_block_height": "40"}}) as rpc:
            with self.assertRaises(ExplorerError) as error:
                reader.blocks(39)
            self.assertEqual(error.exception.status, 404)
            self.assertEqual(rpc.call_count, 1)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = ChainReader()
        cls.server = ExplorerServer(0, cls.reader)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, method="GET", headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_exact_static_allowlist_and_browser_policy(self):
        for path in ("/", "/app.js", "/style.css", "/favicon.svg"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
                self.assertEqual(headers["Cache-Control"], "no-store")
        for path in ("/../localnet.py", "/build/localnet.json", "/%2e%2e/localnet.py", "/.env", "/workspace.js", "/admin/workspace.js"):
            self.assertEqual(self.request(path)[0], 404)

    def test_cross_origin_and_rebinding_hosts_rejected(self):
        self.assertEqual(self.request("/api/overview", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("/api/overview", headers={"Origin": "https://evil.example"})[0], 403)

    def test_mutating_methods_never_reach_node(self):
        with patch.object(self.reader, "api") as api:
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                self.assertEqual(self.request("/api/overview", method)[0], 405)
            api.assert_not_called()

    def test_offline_node_gives_useful_error_and_site_still_loads(self):
        with patch.object(self.reader, "api", side_effect=ExplorerError(503, "The local node is unavailable.")):
            status, _, body = self.request("/api/overview")
            self.assertEqual(status, 503)
            self.assertIn("unavailable", json.loads(body)["error"])
            self.assertEqual(self.request("/")[0], 200)

    def test_response_preserves_integer_strings(self):
        with patch.object(self.reader, "api", return_value={"amount": "9007199254740993"}):
            status, _, body = self.request("/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["amount"], "9007199254740993")


if __name__ == "__main__":
    unittest.main()
