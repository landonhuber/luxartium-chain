"""HTTP secret isolation and durable retry tests; every key and chain is synthetic."""
import base64
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
import uuid

from gateway import BetaSigner, BETA_TREASURY, GatewayHandler, canonical
from localnet import CHAIN_ID, DENOM, FEE, UNIT

ACCESS = "synthetic-gateway-credential-for-http-tests"
PRIVATE_KEY = "1a" * 32
DELIVERY = "D" * 43


class FixtureNetwork:
    """A controllable chain boundary, with no subprocess or external network access."""

    def __init__(self):
        self.genesis = {"chain_id": CHAIN_ID, "genesis_time": "fixture"}
        self.addresses = {}
        self.balances = {}
        self.exports = 0
        self.signatures = 0
        self.broadcasts = []
        self.accepted = {}
        self.committed = {}
        self.applied = 0
        self.before_broadcast = lambda raw: None
        self.disconnect_before_send = False
        self.lose_response = False

    def wallet(self, name):
        self.addresses[name] = "fixture-address-" + name
        self.balances[self.addresses[name]] = 0
        return self.addresses[name]

    def address(self, name):
        return self.addresses[name]

    def balance(self, address):
        return self.balances[address]

    def cli(self, args, **_):
        if args[:2] == ["keys", "show"]:
            address = self.addresses.get(args[2])
            return SimpleNamespace(returncode=0 if address else 1, stdout=address or "")
        if args[:2] == ["keys", "export"]:
            self.exports += 1
            return SimpleNamespace(returncode=0, stdout=PRIVATE_KEY)
        if args[:3] == ["tx", "bank", "send"]:
            value = {"sender": self.address(args[3]), "recipient": args[4],
                     "amount": int(args[5][:-len(DENOM)]),
                     "memo": args[args.index("--note") + 1]}
            return SimpleNamespace(returncode=0, stdout=canonical(value))
        raise AssertionError("Unexpected fixture CLI action")

    def rpc(self, path):
        if path == "genesis":
            return {"result": {"genesis": dict(self.genesis)}}
        if path.startswith("tx?hash=0x"):
            result = self.committed.get(path.split("0x", 1)[1])
            if result is None:
                raise ValueError("Not committed")
            return {"result": result}
        if path.startswith("broadcast_tx_sync?tx=0x"):
            raw = bytes.fromhex(path.split("0x", 1)[1])
            self.before_broadcast(raw)
            self.broadcasts.append(raw)
            if self.disconnect_before_send:
                self.disconnect_before_send = False
                raise OSError("Synthetic disconnect before network acceptance")
            identity = hashlib.sha256(raw).hexdigest().upper()
            self.accepted[identity] = raw
            if self.lose_response:
                self.lose_response = False
                raise OSError("Synthetic response loss after network acceptance")
            return {"result": {"code": 0, "hash": identity}}
        raise AssertionError("Unexpected fixture RPC path or non-byte broadcast")

    def commit(self):
        for identity, raw in self.accepted.items():
            if identity in self.committed:
                continue
            intent = json.loads(raw)["unsigned"]
            self.balances[intent["sender"]] -= intent["amount"] + FEE
            self.balances[intent["recipient"]] += intent["amount"]
            self.committed[identity] = {"tx": base64.b64encode(raw).decode(),
                                        "tx_result": {"code": 0}, "height": "101"}
            self.applied += 1


class FixtureSigner(BetaSigner):
    def stdin_cli(self, args, value):
        if args[:2] == ["tx", "sign"]:
            self.network.signatures += 1
            # A second signature deliberately changes the bytes, exposing re-sign bugs.
            return canonical({"unsigned": json.loads(value), "signature": self.network.signatures})
        if args[:2] == ["tx", "encode"]:
            return base64.b64encode(value.encode()).decode()
        raise AssertionError("Unexpected fixture signing action")


class GatewayFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="beta-signer-review-")
        self.directory = Path(self.temporary.name)
        self.network = FixtureNetwork()
        self.now = 1000
        self.signer = FixtureSigner(self.directory, self.network, clock=lambda: self.now)
        treasury = self.network.wallet(BETA_TREASURY)
        self.network.balances[treasury] = 100_000 * UNIT
        self.signer.db.execute("INSERT INTO beta_config VALUES (1, ?)", (treasury,))
        self.signer.db.commit()
        self.account = str(uuid.uuid4())
        self.enrollment = {"account_id": self.account, "delivery_token": DELIVERY,
                           "acknowledge": False}

    def tearDown(self):
        self.signer.db.close()
        self.temporary.cleanup()


class GatewayHTTPTests(GatewayFixture):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        self.server.signer = self.signer
        self.server.key_hash = hashlib.sha256(("Bearer " + ACCESS).encode()).digest()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, path, body, overrides=None):
        headers = {"Host": f"127.0.0.1:{self.server.server_port}",
                   "Authorization": "Bearer " + ACCESS, "Content-Type": "application/json"}
        for name, value in (overrides or {}).items():
            if value is None:
                headers.pop(name, None)
            else:
                headers[name] = value
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request("POST", path, body=json.dumps(body).encode(), headers=headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_health_serializes_shared_journal_and_keyring_reads(self):
        class OwnedLock:
            def __init__(self):
                self.lock = threading.Lock()
                self.owner = None

            def __enter__(self):
                self.lock.acquire()
                self.owner = threading.get_ident()

            def __exit__(self, *_):
                self.owner = None
                self.lock.release()

        lock = OwnedLock()
        self.signer.lock = lock
        original_chain, original_treasury = self.signer.assert_chain, self.signer.beta_treasury
        observed = []

        def assert_chain():
            self.assertEqual(lock.owner, threading.get_ident())
            observed.append("chain")
            return original_chain()

        def treasury():
            self.assertEqual(lock.owner, threading.get_ident())
            observed.append("treasury")
            return original_treasury()

        self.signer.assert_chain, self.signer.beta_treasury = assert_chain, treasury
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.request("/beta/health", {}), range(8)))
        for status, headers, raw in responses:
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(json.loads(raw), {"chain_id": CHAIN_ID, "genesis_hash": self.signer.fingerprint,
                                              "treasury_address": self.network.address(BETA_TREASURY),
                                              "welcome_policy": {"state": "legacy", "policy_id": "legacy-flat-500", "snapshot_hash": None, "legacy_inventory_hash": None}})
        self.assertEqual(observed, ["chain", "treasury"] * 8)
        self.assertEqual(self.network.signatures, 0)
        self.assertEqual(self.network.exports, 0)
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM operations").fetchone()[0], 0)

    def test_health_still_rejects_a_changed_treasury(self):
        self.network.addresses[BETA_TREASURY] = "changed-synthetic-treasury"
        status, _, body = self.request("/beta/health", {})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {"error": "TREASURY_IDENTITY_CHANGED"})

    def test_health_still_rejects_a_missing_treasury(self):
        self.signer.db.execute("DELETE FROM beta_config")
        self.signer.db.commit()
        status, _, body = self.request("/beta/health", {})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {"error": "TREASURY_IDENTITY_CHANGED"})

    def test_health_still_rejects_a_changed_genesis(self):
        self.network.genesis["genesis_time"] = "changed-synthetic-genesis"
        status, _, body = self.request("/beta/health", {})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {"error": "CHAIN_IDENTITY_CHANGED"})

    def test_unauthenticated_and_browser_origin_requests_cannot_export_or_enroll(self):
        attempts = ({"Authorization": None}, {"Authorization": "Bearer wrong"},
                    {"Host": f"localhost:{self.server.server_port}"},
                    {"Origin": "https://outside.invalid"}, {"Origin": "null"},
                    {"Origin": f"http://127.0.0.1:{self.server.server_port}"})
        for headers in attempts:
            with self.subTest(headers=headers):
                status, _, body = self.request("/beta/enroll", self.enrollment, headers)
                self.assertEqual(status, 403)
                self.assertNotIn(PRIVATE_KEY.encode(), body)
        self.assertEqual(self.network.exports, 0)
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM beta_wallets").fetchone()[0], 0)

    def test_key_delivery_is_no_store_and_acknowledgement_disables_recovery(self):
        status, headers, body = self.request("/beta/enroll", self.enrollment)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body)["private_key_hex"], PRIVATE_KEY)
        self.assertNotIn("private_key_hex", json.loads(self.request("/beta/wallet", {"account_id": self.account})[2]))
        status, _, body = self.request("/beta/enroll", {**self.enrollment, "delivery_token": "E" * 43})
        self.assertEqual(status, 409)
        self.assertNotIn(PRIVATE_KEY.encode(), body)
        status, _, body = self.request("/beta/enroll", {**self.enrollment, "acknowledge": True})
        self.assertEqual(status, 200)
        self.assertNotIn("private_key_hex", json.loads(body))
        self.assertNotIn("private_key_hex", json.loads(self.request("/beta/enroll", self.enrollment)[2]))
        self.assertEqual(self.network.exports, 1)

    def test_expired_delivery_does_not_export(self):
        self.request("/beta/enroll", self.enrollment)
        self.now += 1800
        status, _, body = self.request("/beta/enroll", self.enrollment)
        self.assertEqual(status, 409)
        self.assertIn(b"KEY_DELIVERY_EXPIRED", body)
        self.assertNotIn(PRIVATE_KEY.encode(), body)
        late_ack = self.request("/beta/enroll", {**self.enrollment, "acknowledge": True})
        self.assertEqual(late_ack[0], 409)
        self.assertNotIn(PRIVATE_KEY.encode(), late_ack[2])
        self.assertEqual(self.network.exports, 1)

    def test_provisioning_preserves_token_without_starting_key_delivery(self):
        body = {"account_id": self.account, "delivery_token": DELIVERY}
        status, headers, encoded = self.request("/beta/provision", body)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("private_key_hex", json.loads(encoded))
        self.assertEqual(self.network.exports, 0)
        self.assertEqual(self.signer.beta_wallet_record(self.account)["delivery_expires"], 0)
        self.now += 2 * 86400
        status, _, _ = self.request("/beta/provision", {**body, "delivery_token": "E" * 43})
        self.assertEqual(status, 409)
        self.assertEqual(self.request("/beta/enroll", {**self.enrollment, "acknowledge": True})[0], 409)
        self.assertEqual(self.network.exports, 0)
        status, _, encoded = self.request("/beta/enroll", self.enrollment)
        self.assertEqual(status, 200)
        deadline = json.loads(encoded)["delivery_expires_at"]
        self.assertEqual(deadline, self.now + 1800)
        self.now += 900
        self.assertEqual(self.request("/beta/provision", body)[0], 200)
        self.assertEqual(json.loads(self.request("/beta/enroll", self.enrollment)[2])["delivery_expires_at"], deadline)
        self.now += 900
        self.assertEqual(self.request("/beta/enroll", self.enrollment)[0], 409)
        self.assertEqual(self.network.exports, 2)

    def test_keyring_identity_change_prevents_export(self):
        self.request("/beta/enroll", self.enrollment)
        self.network.addresses[self.signer.key_name(self.account)] = "different-fixture-address"
        status, _, body = self.request("/beta/enroll", self.enrollment)
        self.assertEqual(status, 409)
        self.assertIn(b"WALLET_IDENTITY_CHANGED", body)
        self.assertNotIn(PRIVATE_KEY.encode(), body)
        self.assertEqual(self.network.exports, 1)

    def test_body_bounds_are_checked_before_key_access(self):
        status, _, _ = self.request("/beta/enroll", {**self.enrollment, "delivery_token": "D" * 2500})
        self.assertEqual(status, 400)
        status, _, _ = self.request("/beta/enroll", self.enrollment, {"Content-Type": "text/plain"})
        self.assertEqual(status, 400)
        self.assertEqual(self.network.exports, 0)


class GatewayRecoveryTests(GatewayFixture):
    def action(self):
        wallet = self.signer.beta_enroll(self.enrollment)
        self.network.balances[wallet["address"]] = 500 * UNIT
        identity = str(uuid.uuid4())
        return {"operation_id": identity, "kind": "action", "from_account_id": self.account,
                "to_account_id": None, "amount_uluxar": str(UNIT),
                "reference_hash": hashlib.sha256(identity.encode()).hexdigest(),
                "reverses_operation_id": None, "genesis_hash": self.signer.fingerprint}

    def reopen(self):
        self.signer.db.close()
        self.signer = FixtureSigner(self.directory, self.network, clock=lambda: self.now)

    def assert_durable_before_broadcast(self, raw):
        # A separate connection only sees committed data, proving commit precedes I/O.
        with closing(sqlite3.connect(self.directory / "settlements.sqlite")) as reader:
            rows = reader.execute("SELECT signed, hash FROM operations").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(base64.b64decode(rows[0][0]), raw)
        self.assertEqual(rows[0][1], hashlib.sha256(raw).hexdigest().upper())

    def assert_one_payment(self, action, first):
        self.network.commit()
        receipt = self.signer.beta_operation(action)
        self.assertEqual(receipt["state"], "committed")
        self.assertEqual(receipt["transaction_hash"], first["transaction_hash"])
        self.assertEqual(receipt["sender"], self.network.address(self.signer.key_name(self.account)))
        self.assertEqual(receipt["recipient"], self.network.address(BETA_TREASURY))
        self.assertEqual(receipt["amount_uluxar"], str(UNIT))
        self.assertTrue(receipt["memo"].endswith(action["reference_hash"]))
        self.assertEqual(self.network.balance(receipt["sender"]), 499 * UNIT - FEE)
        self.assertEqual(self.network.applied, 1)
        self.assertEqual(self.network.signatures, 1)
        self.assertEqual(len(set(self.network.broadcasts)), 1)
        self.assertEqual(self.signer.beta_operation(action), receipt)

    def test_persisted_bytes_survive_disconnect_before_first_acceptance(self):
        action = self.action()
        self.network.before_broadcast = self.assert_durable_before_broadcast
        self.network.disconnect_before_send = True
        first = self.signer.beta_operation(action)
        self.assertEqual(first["state"], "pending")
        self.assertFalse(self.network.accepted)
        self.reopen()
        second = self.signer.beta_operation(action)
        self.assertEqual(second["transaction_hash"], first["transaction_hash"])
        self.assert_one_payment(action, first)

    def test_lost_response_rebroadcasts_the_same_bytes_after_restart(self):
        action = self.action()
        self.network.before_broadcast = self.assert_durable_before_broadcast
        self.network.lose_response = True
        first = self.signer.beta_operation(action)
        self.assertEqual(first["state"], "pending")
        self.assertEqual(len(self.network.accepted), 1)
        self.reopen()
        second = self.signer.beta_operation(action)
        self.assertEqual(second["transaction_hash"], first["transaction_hash"])
        self.assertEqual(len(self.network.broadcasts), 2)
        self.assert_one_payment(action, first)

    def test_a_different_committed_transaction_cannot_settle_the_operation(self):
        action = self.action()
        first = self.signer.beta_operation(action)
        self.network.commit()
        self.network.committed[first["transaction_hash"]]["tx"] = base64.b64encode(b"different fixture bytes").decode()
        with self.assertRaisesRegex(ValueError, "does not match the signed intent"):
            self.signer.beta_operation(action)
        self.assertEqual(self.signer.db.execute("SELECT state FROM operations").fetchone()[0], "pending")


if __name__ == "__main__":
    unittest.main()
