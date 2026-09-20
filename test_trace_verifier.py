"""Graph attacks against independently assembled public trace records."""
import copy
import base64
import hashlib
import unittest
import uuid
import urllib.parse

from trace_protocol import compact, event_set, memo_hash
from trace_verifier import verify_graph, decode_transfer, verify_proof, verify_latest_ownership
from verify_trace import encode, cid, chash

ISSUER = "luxar1" + "q" * 38
WALLET = "luxar1" + "p" * 38
IDS = {key: str(uuid.uuid5(uuid.NAMESPACE_URL, "trace-fixture/" + key)) for key in ("agent", "account", "migration", "art", "version", "asset", "piece", "other", "workspace", "rent")}


def record(memo, height):
    return {"hash": hashlib.sha256((memo + str(height)).encode()).hexdigest(), "position": (height, 0),
            "sender": ISSUER, "recipient": ISSUER, "amount_uluxar": 1, "fee_uluxar": 1000, "memo": memo}


def raw_transfer(memo):
    def integer(value):
        result = bytearray()
        while value > 127:
            result.append((value & 127) | 128)
            value >>= 7
        return bytes(result) + bytes([value])
    def cell(number, value):
        return integer(number * 8 + 2) + integer(len(value)) + value
    coin = lambda amount: cell(1, b"uluxar") + cell(2, str(amount).encode())
    send = cell(1, ISSUER.encode()) + cell(2, ISSUER.encode()) + cell(3, coin(1))
    body = cell(1, cell(1, b"/cosmos.bank.v1beta1.MsgSend") + cell(2, send)) + cell(2, memo.encode())
    auth = cell(1, b"fixture-signer") + cell(2, cell(1, coin(1000)) + b"\x10" + integer(200000))
    return cell(1, body) + cell(2, auth) + cell(3, b"fixture-signature")


def fixture():
    memos = [
        encode("i", cid(IDS["agent"]), cid(IDS["account"]), WALLET),
        encode("m", cid(IDS["migration"]), chash("1" * 64), chash("2" * 64), 2000, 1, 1),
        encode("v", cid(IDS["version"]), cid(IDS["art"]), cid(IDS["agent"]), chash("3" * 64), "a", 1000),
        encode("l", cid(IDS["version"]), None, None),
        encode("b", cid(IDS["version"]), cid(IDS["asset"]), chash("4" * 64), "primary"),
        encode("p", cid(IDS["piece"]), cid(IDS["version"]), cid(IDS["account"]), cid(IDS["account"]), "gallery", cid(IDS["art"]), 1500),
    ]
    digests = [memo_hash(memo) for memo in memos]
    digest, count = event_set(digests)
    memos.append(encode("z", cid(IDS["migration"]), "migration", chash(digest), count))
    records = [record(memo, index + 1) for index, memo in enumerate(memos)]
    return records, [{"transaction_hash": records[-1]["hash"].upper(), "event_hashes": digests}], {"scope": "migration", "id": IDS["migration"]}


class TraceGraphTests(unittest.TestCase):
    def test_complete_migration_graph(self):
        records, seals, subject = fixture()
        result = verify_graph(records, seals, subject, ISSUER)
        self.assertTrue(result["verified"])
        self.assertEqual(result["owners"], {IDS["piece"]: IDS["account"]})
        self.assertEqual(result["seal"]["event_count"], 6)

    def test_wrong_issuer_even_with_exact_memo_is_not_authoritative(self):
        records, seals, subject = fixture()
        for changed in ({"sender": WALLET}, {"recipient": WALLET}, {"amount_uluxar": 2}, {"fee_uluxar": 1}):
            modified = copy.deepcopy(records)
            modified[0].update(changed)
            with self.assertRaisesRegex(ValueError, "WRONG_TRACE_ISSUER_OR_TRANSFER"):
                verify_graph(modified, seals, subject, ISSUER)

    def test_chain_order_and_ancestry_omissions_fail(self):
        records, seals, subject = fixture()
        reordered = [records[2], *records[:2], *records[3:]]
        with self.assertRaisesRegex(ValueError, "MISSING_CREATOR_IDENTITY"):
            verify_graph(reordered, seals, subject, ISSUER)
        with self.assertRaisesRegex(ValueError, "MISSING_PUBLICATION_ANCESTRY"):
            verify_graph([*records[:3], *records[4:]], seals, subject, ISSUER)
        with self.assertRaisesRegex(ValueError, "MISSING_PRIMARY_ASSET"):
            verify_graph([*records[:4], *records[5:]], seals, subject, ISSUER)

    def test_seal_can_not_omit_or_invent_dependency(self):
        records, seals, subject = fixture()
        with self.assertRaisesRegex(ValueError, "SEAL_SET_MISMATCH"):
            verify_graph(records, [{**seals[0], "event_hashes": seals[0]["event_hashes"][1:]}], subject, ISSUER)
        omitted = seals[0]["event_hashes"][1:]
        digest, count = event_set(omitted)
        forged_seal = record(encode("z", cid(IDS["migration"]), "migration", chash(digest), count), 7)
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_SEALED_GRAPH"):
            verify_graph([*records[:-1], forged_seal], [{"transaction_hash": forged_seal["hash"].upper(), "event_hashes": omitted}], subject, ISSUER)

    def test_duplicate_and_conflicting_identity_fail(self):
        records, seals, subject = fixture()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_TRACE_EVENT"):
            verify_graph([records[0], *records], seals, subject, ISSUER)
        changed = record(encode("i", cid(IDS["other"]), cid(IDS["account"]), WALLET), 2)
        with self.assertRaisesRegex(ValueError, "CONFLICTING_IDENTITY"):
            verify_graph([records[0], changed, *records[1:]], seals, subject, ISSUER)

    def test_self_parent_and_missing_permission_fail(self):
        records, seals, subject = fixture()
        modified = copy.deepcopy(records)
        modified[3] = record(encode("l", cid(IDS["version"]), cid(IDS["version"]), None), 4)
        with self.assertRaisesRegex(ValueError, "MISSING_ANCESTOR_GRAPH"):
            verify_graph(modified, seals, subject, ISSUER)
        permission = record(encode("g", cid(IDS["workspace"]), cid(IDS["piece"]), cid(IDS["version"]), cid(IDS["account"]), "rent", cid(IDS["rent"]), None), 8)
        with self.assertRaisesRegex(ValueError, "MISSING_RENTAL_AUTHORIZATION"):
            verify_graph([*records, permission], seals, subject, ISSUER)

    def test_native_publication_cannot_skip_paid_result(self):
        records, seals, subject = fixture()
        records[5] = record(encode("p", cid(IDS["piece"]), cid(IDS["version"]), cid(IDS["account"]), cid(IDS["account"]), "native", cid(IDS["art"]), 1500), 6)
        with self.assertRaisesRegex(ValueError, "MISSING_NATIVE_CREATIVE_RESULT"):
            verify_graph(records, seals, subject, ISSUER)

    def test_publication_source_is_bound_to_actual_artwork_or_paid_workspace(self):
        records, seals, subject = fixture()
        records[5] = record(encode("p", cid(IDS["piece"]), cid(IDS["version"]), cid(IDS["account"]), cid(IDS["account"]), "gallery", cid(IDS["other"]), 1500), 6)
        with self.assertRaisesRegex(ValueError, "GALLERY_SOURCE_ARTWORK_MISMATCH"):
            verify_graph(records, seals, subject, ISSUER)
        records = records[:5]
        attempt, operation = str(uuid.uuid4()), str(uuid.uuid4())
        paid_hash = "a" * 64
        records.extend([
            record(encode("a", cid(attempt), cid(IDS["workspace"]), cid(IDS["account"]), "create_svg", chash("9" * 64)), 6),
            {"hash": paid_hash, "position": (7, 0), "sender": WALLET, "recipient": ISSUER,
             "amount_uluxar": 1_000_000, "fee_uluxar": 1000, "memo": f"foundry:beta:action:{operation}:" + "c" * 64},
            record(encode("c", cid(attempt), cid(operation), chash(paid_hash)), 8),
            record(encode("d", cid(attempt), cid(IDS["version"]), "succeeded"), 9),
            record(encode("p", cid(IDS["piece"]), cid(IDS["version"]), cid(IDS["account"]), cid(IDS["account"]), "native", cid(IDS["workspace"]), 1500), 10),
        ])
        digests = [memo_hash(item["memo"]) for item in records if item["memo"].startswith("foundry:t1:")]
        digest, count = event_set(digests)
        records.append(record(encode("z", cid(IDS["piece"]), "piece", chash(digest), count), 11))
        seals = [{"transaction_hash": records[-1]["hash"].upper(), "event_hashes": digests}]
        subject = {"scope": "piece", "id": IDS["piece"]}
        self.assertTrue(verify_graph(records, seals, subject, ISSUER)["verified"])
        records[-2] = record(encode("p", cid(IDS["piece"]), cid(IDS["version"]), cid(IDS["account"]), cid(IDS["account"]), "native", cid(IDS["other"]), 1500), 10)
        with self.assertRaisesRegex(ValueError, "NATIVE_SOURCE_WORKSPACE_MISMATCH"):
            verify_graph(records, seals, subject, ISSUER)

    def test_one_payment_cannot_fund_two_actions_or_unrelated_refund(self):
        records, seals, subject = fixture()
        attempt, other, operation, refund = [str(uuid.uuid4()) for _ in range(4)]
        paid_hash, refund_hash = "a" * 64, "b" * 64
        action = record(encode("a", cid(attempt), cid(IDS["workspace"]), cid(IDS["account"]), "create_svg", chash("9" * 64)), 8)
        paid = {"hash": paid_hash, "position": (9, 0), "sender": WALLET, "recipient": ISSUER,
                "amount_uluxar": 1_000_000, "fee_uluxar": 1000, "memo": f"foundry:beta:action:{operation}:" + "c" * 64}
        paid_event = record(encode("c", cid(attempt), cid(operation), chash(paid_hash)), 10)
        second_action = record(encode("a", cid(other), cid(IDS["workspace"]), cid(IDS["account"]), "create_svg", chash("8" * 64)), 11)
        reused = record(encode("c", cid(other), cid(operation), chash(paid_hash)), 12)
        with self.assertRaisesRegex(ValueError, "PAYMENT_ALREADY_ATTRIBUTED"):
            verify_graph([*records, action, paid, paid_event, second_action, reused], seals, subject, ISSUER)
        refunded = {"hash": refund_hash, "position": (11, 0), "sender": ISSUER, "recipient": WALLET,
                    "amount_uluxar": 1_001_000, "fee_uluxar": 1000, "memo": f"foundry:beta:refund:{refund}:" + "d" * 64}
        refund_event = record(encode("f", cid(attempt), cid(refund), chash(refund_hash)), 12)
        with self.assertRaisesRegex(ValueError, "REFUND_ACTION_REFERENCE_MISMATCH"):
            verify_graph([*records, action, paid, paid_event, refunded, refund_event], seals, subject, ISSUER)

    def test_untrusted_proof_shape_rejected_before_rpc(self):
        with self.assertRaisesRegex(ValueError, "INVALID_PROOF_SHAPE"):
            verify_proof({"format": "foundry-trace-proof-v1", "credential": "synthetic"}, lambda _: self.fail("no RPC"), "a" * 64, ISSUER)
        with self.assertRaises(ValueError):
            decode_transfer(b"not a protobuf transaction")

    def test_latest_scan_refuses_omitted_sale_and_uses_quoted_rpc_string(self):
        records, seals, subject = fixture()
        result = verify_graph(records, seals, subject, ISSUER)
        publication = raw_transfer(records[5]["memo"])
        digest = hashlib.sha256(publication).hexdigest().upper()
        sale = raw_transfer(encode("s", cid(IDS["rent"]), cid(IDS["piece"]), cid(IDS["account"]), cid(IDS["other"]), chash("a" * 64), chash(memo_hash(records[5]["memo"]))))
        sale_digest = hashlib.sha256(sale).hexdigest().upper()
        rows = [{"hash": digest, "tx": base64.b64encode(publication).decode(), "tx_result": {"code": 0}},
                {"hash": sale_digest, "tx": base64.b64encode(sale).decode(), "tx_result": {"code": 0}}]
        def rpc(path):
            if path == "status":
                return {"result": {"sync_info": {"latest_block_height": "42"}}}
            query = urllib.parse.parse_qs(path.split("?", 1)[1])
            self.assertEqual(query["order_by"], ['"asc"'])
            self.assertIn("tx.height<=42", query["query"][0])
            return {"result": {"total_count": "2", "txs": rows}}
        with self.assertRaisesRegex(ValueError, "STALE_OR_INCOMPLETE_OWNERSHIP_PROOF"):
            verify_latest_ownership({"transactions": [digest]}, result, rpc, ISSUER)
        self.assertEqual(verify_latest_ownership({"transactions": [digest, sale_digest]}, result, rpc, ISSUER)["current_through_height"], 42)


if __name__ == "__main__":
    unittest.main()
