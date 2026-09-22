"""Synthetic owner-operator tests: no Docker, live keys or network calls."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fund_welcome_campaign as funding


class FundingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.genesis = {"chain_id": "synthetic-preserved-chain"}
        genesis_hash = hashlib.sha256(funding.canonical(self.genesis).encode()).hexdigest()
        fence = self.directory / ".luxartium/gateway/signing-moved.json"
        fence.parent.mkdir(parents=True)
        fence.write_text(json.dumps({"genesis_hash": genesis_hash}))
        self.calls = []
        self.broadcasts = []
        self.receipt = None
        self.lost_response = False
        self.check_code = 0
        self._balance = int(funding.AMOUNT) + funding.FEE
        self.tx = {"body": {"messages": [{"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": funding.FAUCET,
            "to_address": funding.TREASURY, "amount": [{"denom": funding.DENOM, "amount": funding.AMOUNT}]}],
            "memo": funding.MEMO, "timeout_height": "0", "extension_options": [], "non_critical_extension_options": []},
            "auth_info": {"fee": {"amount": [{"denom": funding.DENOM, "amount": str(funding.FEE)}], "gas_limit": "200000", "payer": "", "granter": ""}}, "signatures": []}
        self.network = self
        for item in (patch.object(funding, "GENESIS", genesis_hash), patch.object(Path, "home", return_value=self.directory), patch.object(funding, "cli", side_effect=self.cli)):
            item.start(); self.addCleanup(item.stop)
        self.name = "synthetic-owned-follower"

    def require_owned(self, kind, name):
        self.assertEqual((kind, name), ("container", self.name))
        return {"Image": funding.DAEMON_IMAGE, "State": {"Running": True}}

    def address(self, name):
        self.assertEqual(name, "faucet")
        return funding.FAUCET

    def cli(self, network, args, data=None):
        self.calls.append(args[:2])
        if args[:3] == ["tx", "bank", "send"]:
            return json.dumps(self.tx)
        if args[:2] == ["tx", "sign"]:
            self.assertTrue((self.directory / "welcome-waterfall-funding.intent.json").is_file())
            value = json.loads(data); value["signatures"] = ["synthetic-signature"]
            return json.dumps(value)
        if args[:2] == ["tx", "encode"]:
            return base64.b64encode(funding.canonical(json.loads(data)).encode()).decode()
        self.fail("unexpected CLI command")

    def rpc(self, query):
        if query == "genesis":
            return {"result": {"genesis": self.genesis}}
        if query.startswith("tx?hash=0x"):
            if self.receipt is None:
                raise ValueError("synthetic missing transaction")
            return {"result": self.receipt}
        if query.startswith("broadcast_tx_sync?tx=0x"):
            raw = bytes.fromhex(query.split("0x", 1)[1])
            saved = (self.directory / "welcome-waterfall-funding.tx.base64").read_text().strip()
            self.assertEqual(base64.b64encode(raw).decode(), saved)
            self.assertTrue((self.directory / "welcome-waterfall-funding.signed.json").is_file())
            self.broadcasts.append(raw)
            if self.lost_response:
                raise OSError("synthetic lost response")
            return {"result": {"code": self.check_code, "hash": hashlib.sha256(raw).hexdigest().upper()}}
        self.fail("unexpected RPC query")

    def balance(self, address):
        return self._balance

    def execute(self, mode):
        return funding.execute(self.directory, mode, self.network)

    def test_plan_does_not_sign_or_write(self):
        result = self.execute("plan")
        self.assertEqual(result["mode"], "plan")
        self.assertFalse(result["prior_intent"])
        self.assertEqual(self.calls, [])
        self.assertFalse(list(self.directory.glob("welcome-waterfall-funding.*")))

    def test_durable_prepare_lost_response_exact_replay_and_receipt(self):
        result = self.execute("prepare")
        self.assertFalse(result["broadcast"])
        self.assertEqual(self.broadcasts, [])
        with self.assertRaisesRegex(ValueError, "INTENT_EXISTS"):
            self.execute("prepare")
        self.lost_response = True
        with self.assertRaises(OSError):
            self.execute("broadcast")
        self.lost_response = False
        self.assertEqual(self.execute("broadcast")["mode"], "pending")
        self.assertEqual(len(self.broadcasts), 2)
        self.assertEqual(self.broadcasts[0], self.broadcasts[1])
        encoded = base64.b64encode(self.broadcasts[0]).decode()
        self.receipt = {"tx": encoded, "hash": result["transaction_hash"], "height": "12", "tx_result": {"code": 0}}
        self.assertEqual(self.execute("verify")["mode"], "committed")
        self.assertEqual(self.execute("broadcast")["mode"], "committed")
        self.assertEqual(len(self.broadcasts), 2)
        self.assertEqual(self.calls.count(["tx", "sign"]), 1)
        self.assertTrue((self.directory / "welcome-waterfall-funding.receipt.json").is_file())

    def test_changed_saved_payload_refuses_without_broadcast(self):
        self.execute("prepare")
        path = self.directory / "welcome-waterfall-funding.signed.json"
        value = json.loads(path.read_text()); value["body"]["messages"][0]["to_address"] = funding.FAUCET
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_FUNDING_TRANSACTION"):
            self.execute("broadcast")
        self.assertEqual(self.broadcasts, [])

    def test_checktx_rejection_retains_one_signature(self):
        self.execute("prepare"); self.check_code = 5
        with self.assertRaisesRegex(ValueError, "BROADCAST_REJECTED"):
            self.execute("broadcast")
        self.assertEqual(self.calls.count(["tx", "sign"]), 1)
        with self.assertRaisesRegex(ValueError, "INTENT_EXISTS"):
            self.execute("prepare")

    def test_wrong_receipt_hash_code_and_bytes_fail_closed(self):
        result = self.execute("prepare")
        valid = {"tx": (self.directory / "welcome-waterfall-funding.tx.base64").read_text().strip(),
                 "hash": result["transaction_hash"], "height": "1", "tx_result": {"code": 0}}
        for field, value in (("hash", "0" * 64), ("tx", "other"), ("height", "0"), ("tx_result", {"code": 5})):
            self.receipt = copy.deepcopy(valid); self.receipt[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "TERMINAL_FAILURE"):
                self.execute("verify")
        self.assertEqual(self.broadcasts, [])

    def test_partial_prepare_and_insufficient_balance_never_resign(self):
        self._balance = int(funding.AMOUNT)
        with self.assertRaisesRegex(ValueError, "RESERVE_INSUFFICIENT"):
            self.execute("prepare")
        self._balance = int(funding.AMOUNT) + funding.FEE
        (self.directory / "welcome-waterfall-funding.intent.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "INTENT_EXISTS"):
            self.execute("prepare")
        self.assertEqual(self.calls, [])

    def test_absent_source_fence_and_oversized_artifact_rejected(self):
        self.execute("prepare")
        (self.directory / "welcome-waterfall-funding.signed.json").write_bytes(b"x" * (funding.MAX_TRANSACTION_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "ARTIFACT_TOO_LARGE"):
            self.execute("verify")
        (self.directory / ".luxartium/gateway/signing-moved.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.execute("plan")


if __name__ == "__main__":
    unittest.main()
