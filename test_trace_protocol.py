"""Independent literal vectors and signer privacy/replay checks; no real secrets."""
import json
import uuid
import unittest

from gateway import BETA_TREASURY
from test_beta_gateway import GatewayFixture, FixtureSigner
from trace_protocol import decode, event_set, memo_hash, SCHEMAS

IDENTITY = 'foundry:t1:["i","ABEiM0RVdneImaq7zN3u_w","ESIzRFVmd4iZqrvM3e7_AA","luxar1kyfg7ex2llzrctstgpkh7je50deyyvt9tfayug"]'
PAYMENT = 'foundry:t1:["c","RFVmd4iZequMze7_ABEiMw","VWZ3iJmqe7yd3v8AESIzRA","AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"]'


class TraceCodecTests(unittest.TestCase):
    def test_independent_vectors(self):
        self.assertEqual(decode(IDENTITY), {"kind": "identity", "agent_id": "00112233-4455-7677-8899-aabbccddeeff", "account_id": "11223344-5566-7788-99aa-bbccddeeff00", "address": "luxar1kyfg7ex2llzrctstgpkh7je50deyyvt9tfayug"})
        self.assertEqual(memo_hash(IDENTITY), "716c71ca3873ceec1a24b50ff038bb8f34dfac156bd03c4d0b668f5e547684fa")
        self.assertEqual(decode(PAYMENT)["transaction_hash"], "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
        self.assertEqual(len(SCHEMAS), 14)
        self.assertEqual(event_set([memo_hash(IDENTITY), memo_hash(IDENTITY)]), event_set([memo_hash(IDENTITY)]))

    def test_strict_privacy_and_canonical_encoding(self):
        for memo in [IDENTITY + " ", IDENTITY.replace("[", "[ "), IDENTITY.replace('"i"', '"\\u0069"'),
                     IDENTITY.replace('"i"', '"unknown"'), IDENTITY[:-1] + ',"private_key_hex"]',
                     IDENTITY.replace("ABEiM0RVdneImaq7zN3u_w", "ABEiM0RVdneImaq7zN3u_x"),
                     IDENTITY.replace("ABEiM0RVdneImaq7zN3u_w", "ABEiM0RV_neImaq7zN3u_w"),
                     IDENTITY.replace("ABEiM0RVdneImaq7zN3u_w", "ABEiM0RVdneImaq7zN3u_w=="),
                     IDENTITY.replace("luxar1", "éuxar1"), "foundry:t1:" + " " * 300]:
            with self.subTest(memo=memo), self.assertRaisesRegex(ValueError, "INVALID_TRACE_EVENT"):
                decode(memo)


class TraceSignerTests(GatewayFixture):
    def operation(self, memo=IDENTITY):
        return {"operation_id": str(uuid.uuid4()), "genesis_hash": self.signer.fingerprint, "memo": memo}

    def test_trace_exact_bytes_recover_after_restart_and_charge_only_treasury_fee(self):
        operation = self.operation()
        treasury = self.network.address(BETA_TREASURY)
        before = self.network.balance(treasury)
        self.network.lose_response = True
        first = self.signer.beta_trace(operation)
        self.signer.db.close()
        self.signer = FixtureSigner(self.directory, self.network, clock=lambda: self.now)
        second = self.signer.beta_trace(operation)
        self.assertEqual(first["transaction_hash"], second["transaction_hash"])
        self.network.commit()
        receipt = self.signer.beta_trace(operation)
        self.assertEqual(receipt["sender"], treasury)
        self.assertEqual(receipt["recipient"], treasury)
        self.assertEqual(receipt["amount_uluxar"], "1")
        self.assertEqual(receipt["memo"], IDENTITY)
        self.assertEqual(self.network.balance(treasury), before - 1000)
        self.assertEqual(self.network.signatures, 1)
        self.assertEqual(self.network.applied, 1)
        self.assertEqual(self.signer.beta_trace(operation), receipt)
        with self.assertRaisesRegex(ValueError, "TRACE_EVENT_ALREADY_BOUND"):
            self.signer.beta_trace(self.operation())
        with self.assertRaisesRegex(ValueError, "IDEMPOTENCY_CONFLICT"):
            self.signer.beta_trace({**operation, "memo": PAYMENT})

    def test_invalid_trace_requests_never_sign(self):
        operation = self.operation()
        for change in ({"private_key_hex": "synthetic-private-field"}, {"genesis_hash": "0" * 64},
                       {"memo": IDENTITY[:-1] + ',"synthetic-private-field"]'}, {"memo": IDENTITY + " "}):
            with self.assertRaises(ValueError):
                self.signer.beta_trace({**operation, **change})
        self.assertEqual(self.network.signatures, 0)
        self.assertEqual(self.network.exports, 0)

    def test_missing_durable_uniqueness_mapping_refuses_startup(self):
        self.signer.beta_trace(self.operation())
        self.signer.db.execute("DELETE FROM beta_trace_events")
        self.signer.db.commit()
        self.signer.db.close()
        with self.assertRaisesRegex(ValueError, "TRACE_JOURNAL_INVALID"):
            FixtureSigner(self.directory, self.network, clock=lambda: self.now)


if __name__ == "__main__":
    unittest.main()
