"""Independent Foundry trace verifier using public CometBFT RPC, never the Foundry DB.

The selected RPC is a trust boundary (not a light client). Genesis and attestor are
operator-pinned arguments, never accepted merely because a downloaded proof says so.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import urllib.parse
import uuid

from trace_protocol import decode, event_set, memo_hash

CHAIN_ID = "luxartium-local-1"
MAX_TRANSACTIONS = 100_000
MAX_PROOF_BYTES = 64 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def varint(raw, offset):
    result = 0
    for shift in range(0, 70, 7):
        require(offset < len(raw), "TRUNCATED_PROTOBUF")
        value = raw[offset]
        offset += 1
        result |= (value & 127) << shift
        if not value & 128:
            return result, offset
    raise ValueError("INVALID_PROTOBUF_VARINT")


def fields(raw):
    require(len(raw) <= 65_536, "TRANSACTION_TOO_LARGE")
    result, offset = {}, 0
    while offset < len(raw):
        key, offset = varint(raw, offset)
        number, wire = key >> 3, key & 7
        require(number > 0, "INVALID_PROTOBUF_FIELD")
        if wire == 2:
            size, offset = varint(raw, offset)
            require(size <= len(raw) - offset, "TRUNCATED_PROTOBUF")
            value, offset = raw[offset:offset + size], offset + size
        elif wire == 0:
            value, offset = varint(raw, offset)
        else:
            raise ValueError("UNSUPPORTED_PROTOBUF_FIELD")
        result.setdefault(number, []).append(value)
    return result


def one(record, key, default=None):
    values = record.get(key, [])
    require(len(values) <= 1, "DUPLICATE_PROTOBUF_FIELD")
    return values[0] if values else default


def string(record, key, default=None):
    value = one(record, key, default)
    require(isinstance(value, bytes), "MISSING_PROTOBUF_STRING")
    return value.decode("utf-8", errors="strict")


def coins(record, key):
    values = record.get(key, [])
    require(len(values) == 1 and isinstance(values[0], bytes), "SINGLE_NATIVE_COIN_REQUIRED")
    coin = fields(values[0])
    require(set(coin) == {1, 2}, "INVALID_NATIVE_COIN")
    denomination, amount = string(coin, 1), string(coin, 2)
    require(denomination == "uluxar" and re.fullmatch(r"[1-9][0-9]{0,15}", amount), "INVALID_NATIVE_AMOUNT")
    return int(amount)


def decode_transfer(raw):
    envelope = fields(raw)
    require(set(envelope) == {1, 2, 3} and len(envelope[3]) == 1, "SINGLE_SIGNED_TRANSFER_REQUIRED")
    body = fields(one(envelope, 1))
    require(set(body) <= {1, 2, 3} and not one(body, 3, 0), "UNSUPPORTED_TRANSACTION_BODY")
    messages = body.get(1, [])
    require(len(messages) == 1, "SINGLE_SIGNED_TRANSFER_REQUIRED")
    message = fields(messages[0])
    require(set(message) == {1, 2} and string(message, 1) == "/cosmos.bank.v1beta1.MsgSend", "NATIVE_SEND_REQUIRED")
    send = fields(one(message, 2))
    require(set(send) == {1, 2, 3}, "INVALID_SEND_FIELDS")
    auth = fields(one(envelope, 2))
    require(set(auth) <= {1, 2} and len(auth.get(1, [])) == 1, "SINGLE_SIGNER_REQUIRED")
    fee = fields(one(auth, 2))
    require(set(fee) <= {1, 2, 3, 4} and not one(fee, 3, b"") and not one(fee, 4, b""), "UNSUPPORTED_FEE_PAYER")
    return {"sender": string(send, 1), "recipient": string(send, 2), "amount_uluxar": coins(send, 3),
            "fee_uluxar": coins(fee, 1), "memo": string(body, 2, b"")}


class RPC:
    def __init__(self, url):
        require(re.fullmatch(r"https?://[^/?#]+", url) is not None, "INVALID_RPC_ORIGIN")
        self.url = url

    def __call__(self, path):
        request = urllib.request.Request(self.url + "/" + path, headers={"User-Agent": "LuxartiumTraceVerifier/1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        require(len(raw) <= 8 * 1024 * 1024, "RPC_RESPONSE_TOO_LARGE")
        return json.loads(raw)


def read_transactions(hashes, rpc, expected_genesis):
    genesis = rpc("genesis")["result"]["genesis"]
    canonical = json.dumps(genesis, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    require(genesis.get("chain_id") == CHAIN_ID and hashlib.sha256(canonical.encode()).hexdigest() == expected_genesis, "WRONG_GENESIS")
    records, positions, blocks = [], set(), {}
    for digest in hashes:
        require(isinstance(digest, str) and re.fullmatch(r"[A-F0-9]{64}", digest), "INVALID_TRANSACTION_HASH")
        result = rpc("tx?hash=0x" + digest)["result"]
        raw = base64.b64decode(result["tx"], validate=True)
        require(hashlib.sha256(raw).hexdigest().upper() == digest and result["hash"] == digest, "TRANSACTION_HASH_MISMATCH")
        require(int(result["tx_result"]["code"]) == 0, "FAILED_CHAIN_TRANSACTION")
        position = int(result["height"]), int(result["index"])
        require(position[0] > 0 and position[1] >= 0 and position not in positions, "TRANSACTION_POSITION_OR_DUPLICATE")
        positions.add(position)
        if position[0] not in blocks:
            blocks[position[0]] = rpc("block?height=" + str(position[0]))["result"]["block"]
        block = blocks[position[0]]
        require(block["header"]["chain_id"] == CHAIN_ID and int(block["header"]["height"]) == position[0], "BLOCK_IDENTITY_MISMATCH")
        entries = block["data"]["txs"] or []
        require(0 <= position[1] < len(entries) and entries[position[1]] == result["tx"], "TRANSACTION_NOT_INCLUDED")
        records.append({"hash": digest.lower(), "position": position, **decode_transfer(raw)})
    return sorted(records, key=lambda record: record["position"])


def verify_graph(records, seals, subject, issuer):
    identities, agents, addresses, versions, ancestry, assets = {}, {}, {}, {}, {}, {}
    publications, owners, permissions, rentals, actions, payments, results, refunds, migrations = {}, {}, {}, {}, {}, {}, {}, {}, {}
    event_records, dependencies, payment_records, seen_semantics, verified_seals = {}, {}, {}, set(), {}
    consumed_payments = set()
    seal_specs = {entry["transaction_hash"].lower(): entry["event_hashes"] for entry in seals}
    require(len(seal_specs) == len(seals), "DUPLICATE_SEAL_SPECIFICATION")

    def get(mapping, key, error):
        require(key in mapping, error)
        return mapping[key]

    def account(key):
        return get(identities, key, "MISSING_IDENTITY")

    def payment(hash_value, kind, operation, sender, recipient, amount=None):
        transaction = get(payment_records, hash_value, "MISSING_EARLIER_PAYMENT")
        expected = f"foundry:beta:{kind}:{operation}:"
        require(transaction["memo"].startswith(expected) and re.fullmatch(r"[a-f0-9]{64}", transaction["memo"][len(expected):]), "PAYMENT_OPERATION_MISMATCH")
        require(transaction["sender"] == sender and transaction["recipient"] == recipient and transaction["fee_uluxar"] == 1000, "PAYMENT_PARTIES_MISMATCH")
        require(amount is None or transaction["amount_uluxar"] == amount, "PAYMENT_AMOUNT_MISMATCH")
        require(transaction["amount_uluxar"] > 0, "INVALID_PAYMENT_AMOUNT")
        require(hash_value not in consumed_payments, "PAYMENT_ALREADY_ATTRIBUTED")
        consumed_payments.add(hash_value)
        return transaction

    for record in records:
        memo = record["memo"]
        if not memo.startswith("foundry:t1:"):
            require(re.fullmatch(r"foundry:beta:(action|sale|rent|refund):[0-9a-f-]{36}:[0-9a-f]{64}", memo) is not None, "UNRELATED_PROOF_TRANSACTION")
            payment_records[record["hash"]] = record
            continue
        require(record["sender"] == issuer and record["recipient"] == issuer and record["amount_uluxar"] == 1 and record["fee_uluxar"] == 1000, "WRONG_TRACE_ISSUER_OR_TRANSFER")
        event = decode(memo)
        digest, kind = memo_hash(memo), event["kind"]
        require(digest not in event_records, "DUPLICATE_TRACE_EVENT")
        deps = set()
        def dependency(value):
            deps.add(value[0])
            return value[1]
        if kind == "identity":
            require(event["account_id"] not in identities and event["agent_id"] not in agents and event["address"] not in addresses, "CONFLICTING_IDENTITY")
            identities[event["account_id"]] = (digest, event)
            agents[event["agent_id"]] = (digest, event)
            addresses[event["address"]] = event["account_id"]
        elif kind == "version":
            dependency(get(agents, event["agent_id"], "MISSING_CREATOR_IDENTITY"))
            require(event["version_id"] not in versions, "CONFLICTING_VERSION")
            versions[event["version_id"]] = (digest, event)
        elif kind == "ancestry":
            version = dependency(get(versions, event["version_id"], "MISSING_VERSION"))
            require(event["version_id"] not in ancestry, "CONFLICTING_ANCESTRY")
            for field in ("parent_version_id", "source_version_id"):
                ancestor = event[field]
                if ancestor:
                    old = dependency(get(versions, ancestor, "MISSING_EARLIER_ANCESTOR"))
                    dependency(get(ancestry, ancestor, "MISSING_ANCESTOR_GRAPH"))
                    require(ancestor != event["version_id"], "SELF_ANCESTRY")
                    if field == "parent_version_id":
                        require(old["artwork_id"] == version["artwork_id"] and old["created_at_ms"] <= version["created_at_ms"], "INVALID_LOCAL_ANCESTRY")
            ancestry[event["version_id"]] = (digest, event)
        elif kind == "asset":
            dependency(get(versions, event["version_id"], "MISSING_VERSION"))
            key = event["version_id"], event["asset_id"]
            require(key not in assets, "CONFLICTING_ASSET_BINDING")
            assets[key] = (digest, event)
        elif kind == "migration":
            require(event["migration_id"] not in migrations, "CONFLICTING_MIGRATION")
            migrations[event["migration_id"]] = (digest, event)
        elif kind == "publication":
            version = dependency(get(versions, event["version_id"], "MISSING_VERSION"))
            dependency(get(ancestry, event["version_id"], "MISSING_PUBLICATION_ANCESTRY"))
            creator = dependency(account(event["creator_account_id"]))
            dependency(account(event["owner_account_id"]))
            require(version["agent_id"] == creator["agent_id"] and version["purpose"] == "artwork", "INVALID_PUBLICATION_CREATOR_OR_VERSION")
            require(event["owner_account_id"] == event["creator_account_id"], "INVALID_INITIAL_OWNER")
            require(event["piece_id"] not in publications, "CONFLICTING_PUBLICATION")
            require((event["origin"], event["source_id"]) not in seen_semantics, "DUPLICATE_SOURCE_PUBLICATION")
            seen_semantics.add((event["origin"], event["source_id"]))
            selected_assets = [value for key, value in assets.items() if key[0] == event["version_id"]]
            require(any(value[1]["role"] == "primary" for value in selected_assets), "MISSING_PRIMARY_ASSET")
            for value in selected_assets:
                dependency(value)
            if event["origin"] != "native":
                require(len(migrations) == 1, "MIGRATION_AUTHORIZATION_REQUIRED")
                dependency(next(iter(migrations.values())))
                if event["origin"] == "gallery":
                    require(event["source_id"] == version["artwork_id"], "GALLERY_SOURCE_ARTWORK_MISMATCH")
            else:
                completed = [value for value in results.values() if value[1]["version_id"] == event["version_id"] and value[1]["outcome"] == "succeeded"]
                require(len(completed) == 1, "MISSING_NATIVE_CREATIVE_RESULT")
                result = dependency(completed[0])
                action = dependency(get(actions, result["attempt_id"], "MISSING_ACTION"))
                require(action["workspace_id"] == event["source_id"], "NATIVE_SOURCE_WORKSPACE_MISMATCH")
            publications[event["piece_id"]] = (digest, event)
            owners[event["piece_id"]] = (digest, event["owner_account_id"])
        elif kind == "sale":
            dependency(get(publications, event["piece_id"], "MISSING_PIECE"))
            previous = get(owners, event["piece_id"], "MISSING_OWNER")
            require(previous == (event["previous_ownership_hash"], event["previous_owner_id"]) and event["owner_id"] != previous[1], "OWNERSHIP_PREVIOUS_STATE_MISMATCH")
            deps.add(previous[0])
            buyer = dependency(account(event["owner_id"]))
            seller = dependency(account(event["previous_owner_id"]))
            payment(event["payment_transaction_hash"], "sale", event["payment_id"], buyer["address"], seller["address"])
            require(("trade", event["payment_id"]) not in seen_semantics, "DUPLICATE_TRADE")
            seen_semantics.add(("trade", event["payment_id"]))
            owners[event["piece_id"]] = (digest, event["owner_id"])
        elif kind == "rental":
            piece = dependency(get(publications, event["piece_id"], "MISSING_PIECE"))
            owner = get(owners, event["piece_id"], "MISSING_OWNER")
            deps.add(owner[0])
            require(piece["version_id"] == event["version_id"] and owner[1] == event["owner_account_id"] and owner[1] != event["payer_account_id"], "RENTAL_SOURCE_OR_OWNER_MISMATCH")
            payer = dependency(account(event["payer_account_id"]))
            recipient = dependency(account(event["owner_account_id"]))
            payment(event["payment_transaction_hash"], "rent", event["payment_id"], payer["address"], recipient["address"])
            require(("trade", event["payment_id"]) not in seen_semantics, "DUPLICATE_TRADE")
            seen_semantics.add(("trade", event["payment_id"]))
            rentals[event["payment_id"]] = (digest, event)
        elif kind == "permission":
            piece = dependency(get(publications, event["piece_id"], "MISSING_PIECE"))
            dependency(account(event["account_id"]))
            require(piece["version_id"] == event["version_id"], "PERMISSION_SOURCE_MISMATCH")
            key = event["workspace_id"], event["version_id"], event["account_id"]
            require(key not in permissions, "CONFLICTING_SOURCE_PERMISSION")
            if event["basis"] == "rent":
                rental = dependency(get(rentals, event["authorization_id"], "MISSING_RENTAL_AUTHORIZATION"))
                require(rental["workspace_id"] == event["workspace_id"] and rental["piece_id"] == event["piece_id"] and rental["payer_account_id"] == event["account_id"], "RENTAL_PERMISSION_MISMATCH")
            elif event["basis"] == "owner":
                owner = get(owners, event["piece_id"], "MISSING_OWNER")
                require(owner[1] == event["account_id"], "OWNER_PERMISSION_MISMATCH")
                deps.add(owner[0])
            else:
                dependency(get(migrations, event["authorization_id"], "MISSING_ALPHA_AUTHORIZATION"))
            permissions[key] = (digest, event)
        elif kind == "action":
            dependency(account(event["account_id"]))
            require(event["attempt_id"] not in actions, "CONFLICTING_ACTION")
            actions[event["attempt_id"]] = (digest, event)
        elif kind == "payment":
            action = dependency(get(actions, event["attempt_id"], "MISSING_ACTION"))
            sender = dependency(account(action["account_id"]))
            payment(event["transaction_hash"], "action", event["payment_operation_id"], sender["address"], issuer, 1_000_000)
            require(event["attempt_id"] not in payments, "DUPLICATE_ACTION_PAYMENT")
            payments[event["attempt_id"]] = (digest, event)
        elif kind == "refund":
            action = dependency(get(actions, event["attempt_id"], "MISSING_ACTION"))
            original = dependency(get(payments, event["attempt_id"], "MISSING_ACTION_PAYMENT"))
            recipient = dependency(account(action["account_id"]))
            refund_payment = payment(event["transaction_hash"], "refund", event["refund_operation_id"], issuer, recipient["address"], 1_001_000)
            require(refund_payment["memo"].rsplit(":", 1)[1] == payment_records[original["transaction_hash"]]["memo"].rsplit(":", 1)[1], "REFUND_ACTION_REFERENCE_MISMATCH")
            require(event["attempt_id"] not in refunds, "DUPLICATE_ACTION_REFUND")
            refunds[event["attempt_id"]] = (digest, event)
        elif kind == "result":
            action = dependency(get(actions, event["attempt_id"], "MISSING_ACTION"))
            require(event["attempt_id"] not in results, "CONFLICTING_ACTION_RESULT")
            if event["outcome"] == "payment_failed":
                require(event["attempt_id"] not in payments and event["version_id"] is None, "INVALID_PAYMENT_FAILURE")
            else:
                dependency(get(payments, event["attempt_id"], "MISSING_ACTION_PAYMENT"))
                if event["outcome"] == "refunded":
                    dependency(get(refunds, event["attempt_id"], "MISSING_REFUND"))
                    require(event["version_id"] is None, "REFUNDED_ACTION_HAS_VERSION")
                elif event["version_id"]:
                    version = dependency(get(versions, event["version_id"], "MISSING_RESULT_VERSION"))
                    require(version["agent_id"] == account(action["account_id"])[1]["agent_id"], "RESULT_CREATOR_MISMATCH")
                    lineage = dependency(get(ancestry, event["version_id"], "MISSING_RESULT_ANCESTRY"))
                    if lineage["source_version_id"]:
                        source = lineage["source_version_id"]
                        grant = get(permissions, (action["workspace_id"], source, action["account_id"]), "MISSING_EXACT_SOURCE_PERMISSION")
                        dependency(grant)
            results[event["attempt_id"]] = (digest, event)
        elif kind == "seal":
            selected = get(seal_specs, record["hash"], "MISSING_SEAL_EVENT_LIST")
            require(isinstance(selected, list) and len(selected) <= MAX_TRANSACTIONS and len(set(selected)) == len(selected), "INVALID_SEAL_EVENT_LIST")
            expected_hash, count = event_set(selected)
            require((expected_hash, count) == (event["event_set_hash"], event["event_count"]), "SEAL_SET_MISMATCH")
            selected_set = set(selected)
            for referenced in selected:
                get(event_records, referenced, "MISSING_SEALED_EVENT")
                require(dependencies[referenced] <= selected_set, "INCOMPLETE_SEALED_GRAPH")
            key = event["scope"], event["subject_id"]
            require(key not in verified_seals, "DUPLICATE_SUBJECT_SEAL")
            if event["scope"] == "piece":
                root = get(publications, event["subject_id"], "MISSING_SEALED_PIECE")
                require(root[0] in selected_set, "SEAL_SUBJECT_MISMATCH")
            elif event["scope"] == "identity":
                require(account(event["subject_id"])[0] in selected_set, "SEAL_SUBJECT_MISMATCH")
            elif event["scope"] == "migration":
                migration = get(migrations, event["subject_id"], "MISSING_MIGRATION")
                require(migration[0] in selected_set, "SEAL_SUBJECT_MISMATCH")
                imported = [entry for entry in selected if event_records[entry]["kind"] == "publication" and event_records[entry]["origin"] != "native"]
                identities_count = sum(event_records[entry]["kind"] == "identity" for entry in selected)
                require(len(imported) == migration[1]["publications"] and identities_count == migration[1]["identities"], "MIGRATION_COUNTS_MISMATCH")
            elif event["scope"] == "workspace":
                require(any(event_records[entry].get("workspace_id") == event["subject_id"] for entry in selected), "SEAL_SUBJECT_MISMATCH")
            elif event["scope"] == "trade":
                require(any(event_records[entry].get("payment_id") == event["subject_id"] for entry in selected), "SEAL_SUBJECT_MISMATCH")
            deps.update(selected_set)
            verified_seals[key] = {"transaction_hash": record["hash"].upper(), "event_count": count, "event_set_hash": expected_hash}
        event_records[digest] = event
        dependencies[digest] = deps
    require(set(seal_specs) == {record["hash"] for record in records if record["memo"].startswith("foundry:t1:") and decode(record["memo"])["kind"] == "seal"}, "UNRESOLVED_SEAL_SPECIFICATION")
    root = get(verified_seals, (subject["scope"], subject["id"]), "SUBJECT_NOT_SEALED")
    return {"verified": True, "subject": subject, "seal": root, "snapshot_position": list(records[-1]["position"]),
            "ownership_scope": "supplied sealed history; later chain events require a fresh proof",
            "identities": len(identities), "versions": len(versions),
            "publications": len(publications), "permissions": len(permissions), "rentals": len(rentals), "actions": len(actions),
            "owners": {piece: owner for piece, (_, owner) in owners.items()}, "event_count": len(event_records)}


def verify_proof(proof, rpc, expected_genesis, expected_issuer):
    require(isinstance(expected_genesis, str) and re.fullmatch(r"[a-f0-9]{64}", expected_genesis)
            and isinstance(expected_issuer, str) and re.fullmatch(r"luxar1[0-9a-z]{38}", expected_issuer), "INVALID_TRUST_CONFIGURATION")
    require(isinstance(proof, dict) and set(proof) == {"format", "chain_id", "genesis_hash", "issuer_address", "transactions", "seals", "subject"}, "INVALID_PROOF_SHAPE")
    require(proof["format"] == "foundry-trace-proof-v1" and proof["chain_id"] == CHAIN_ID and proof["genesis_hash"] == expected_genesis and proof["issuer_address"] == expected_issuer, "PROOF_IDENTITY_MISMATCH")
    hashes, seals, subject = proof["transactions"], proof["seals"], proof["subject"]
    require(isinstance(hashes, list) and 0 < len(hashes) <= MAX_TRANSACTIONS
            and all(isinstance(value, str) and re.fullmatch(r"[A-F0-9]{64}", value) for value in hashes)
            and len(set(hashes)) == len(hashes), "INVALID_TRANSACTION_LIST")
    require(isinstance(seals, list) and 0 < len(seals) <= MAX_TRANSACTIONS, "INVALID_SEAL_LIST")
    for seal in seals:
        require(isinstance(seal, dict) and set(seal) == {"transaction_hash", "event_hashes"} and isinstance(seal["transaction_hash"], str) and re.fullmatch(r"[A-F0-9]{64}", seal["transaction_hash"]), "INVALID_SEAL_SHAPE")
        require(isinstance(seal["event_hashes"], list) and 0 < len(seal["event_hashes"]) <= MAX_TRANSACTIONS
                and all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) for value in seal["event_hashes"]), "INVALID_SEAL_EVENT_LIST")
    require(isinstance(subject, dict) and set(subject) == {"scope", "id"} and subject["scope"] in ("piece", "migration", "identity", "workspace", "trade") and str(uuid.UUID(subject["id"])) == subject["id"], "INVALID_PROOF_SUBJECT")
    records = read_transactions(hashes, rpc, expected_genesis)
    return verify_graph(records, seals, subject, expected_issuer)


def verify_latest_ownership(proof, result, rpc, issuer):
    """Scan authoritative history through one pinned current height, without a DB.

    A sealed historical proof alone cannot establish absence of a later sale.
    This optional scan checks every attestor transaction and refuses an omitted
    ownership transition for any piece whose owner the proof reports.
    """
    height = int(rpc("status")["result"]["sync_info"]["latest_block_height"])
    require(height > 0, "INVALID_CURRENT_HEIGHT")
    supplied = set(proof["transactions"])
    pieces = set(result["owners"])
    page, seen = 1, set()
    while True:
        query = f"message.sender='{issuer}' AND tx.height<={height}"
        path = "tx_search?" + urllib.parse.urlencode({"query": json.dumps(query), "prove": "false", "page": page, "per_page": 100, "order_by": json.dumps("asc")})
        data = rpc(path)["result"]
        total = int(data["total_count"])
        require(0 <= total <= MAX_TRANSACTIONS, "CURRENTNESS_SCAN_LIMIT")
        rows = data["txs"] or []
        require(len(rows) <= 100 and (rows or len(seen) == total), "INCOMPLETE_CURRENTNESS_SCAN")
        for row in rows:
            digest = row["hash"]
            require(digest not in seen and re.fullmatch(r"[A-F0-9]{64}", digest), "INVALID_CURRENTNESS_SCAN")
            seen.add(digest)
            if int(row["tx_result"]["code"]) != 0:
                continue
            raw = base64.b64decode(row["tx"], validate=True)
            require(hashlib.sha256(raw).hexdigest().upper() == digest, "TRANSACTION_HASH_MISMATCH")
            transfer = decode_transfer(raw)
            if not transfer["memo"].startswith("foundry:t1:"):
                continue
            require(transfer["sender"] == issuer and transfer["recipient"] == issuer and transfer["amount_uluxar"] == 1 and transfer["fee_uluxar"] == 1000, "INVALID_ATTESTOR_TRACE")
            event = decode(transfer["memo"])
            if event["kind"] in ("publication", "sale") and event["piece_id"] in pieces:
                require(digest in supplied, "STALE_OR_INCOMPLETE_OWNERSHIP_PROOF")
        if len(seen) == total:
            return {**result, "ownership_scope": "all attestor ownership events through verified height", "current_through_height": height}
        require(len(seen) < total, "INVALID_CURRENTNESS_SCAN")
        page += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proof", type=Path)
    parser.add_argument("--rpc", required=True)
    parser.add_argument("--genesis", required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--check-latest", action="store_true", help="Scan all attestor transactions for omitted ownership transitions")
    args = parser.parse_args()
    require(args.proof.stat().st_size <= MAX_PROOF_BYTES, "PROOF_TOO_LARGE")
    proof = json.loads(args.proof.read_text(encoding="utf-8"))
    rpc = RPC(args.rpc)
    result = verify_proof(proof, rpc, args.genesis, args.issuer)
    if args.check_latest:
        result = verify_latest_ownership(proof, result, rpc, args.issuer)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
