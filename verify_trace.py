"""Real disposable-chain trace rehearsal. Does not read or modify the saved network."""
import base64
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from gateway import BetaSigner, BETA_TREASURY, BETA_WELCOME, canonical
from localnet import Network, ROOT, UNIT, run
from trace_protocol import compact, decode, event_set, memo_hash
from trace_verifier import verify_proof, verify_latest_ownership
from verify import available_ports, require
from verify_beta_gateway import settled, rejects


def cid(value):
    return compact(uuid.UUID(value).bytes)


def chash(value):
    return compact(bytes.fromhex(value))


def encode(*cells):
    memo = "foundry:t1:" + json.dumps(cells, separators=(",", ":"))
    decode(memo)
    return memo


def verify():
    network = Network("luxartium-check-" + uuid.uuid4().hex[:12], available_ports())
    require(not network.inspect("container", network.name) and not network.inspect("volume", network.volume), "unique disposable resources")
    evidence = {"network": network.name, "checks": []}
    signer = None
    try:
        network.init()
        network.start()
        with ExitStack() as cleanup:
            temporary = cleanup.enter_context(tempfile.TemporaryDirectory(prefix="foundry-trace-"))
            cleanup.callback(lambda: signer.db.close() if signer else None)
            directory = Path(temporary)
            signer = BetaSigner(directory, network)
            treasury = settled(signer.initialize_beta)["treasury_address"]
            ids = {name: str(uuid.uuid4()) for name in ("alice", "bob", "agent_alice", "agent_bob", "migration", "artwork", "version", "asset", "piece", "branch", "branch_version", "branch_asset", "branch_piece", "workspace", "attempt", "rent", "sale", "failed", "refund")}
            for name in ("alice", "bob"):
                signer.beta_provision({"account_id": ids[name], "delivery_token": __import__("secrets").token_urlsafe(32)})
                body = {"operation_id": str(uuid.uuid4()), "kind": "grant", "from_account_id": None, "to_account_id": ids[name], "amount_uluxar": str(BETA_WELCOME), "reference_hash": "1" * 64, "reverses_operation_id": None, "genesis_hash": signer.fingerprint}
                settled(lambda body=body: signer.beta_operation(body))
            transactions, memos, seal_specs = [], [], []
            def trace(memo):
                operation = {"operation_id": str(uuid.uuid4()), "genesis_hash": signer.fingerprint, "memo": memo}
                receipt = settled(lambda: signer.beta_trace(operation))
                transactions.append(receipt["transaction_hash"])
                memos.append(memo)
                return receipt
            def transfer(kind, source, destination, amount, operation, reverse=None):
                body = {"operation_id": operation, "kind": kind, "from_account_id": source, "to_account_id": destination, "amount_uluxar": str(amount), "reference_hash": "2" * 64, "reverses_operation_id": reverse, "genesis_hash": signer.fingerprint}
                receipt = settled(lambda: signer.beta_operation(body))
                transactions.append(receipt["transaction_hash"])
                return receipt["transaction_hash"].lower()
            def seal(scope, subject, selected):
                digest, count = event_set([memo_hash(value) for value in selected])
                receipt = trace(encode("z", cid(subject), scope, chash(digest), count))
                seal_specs.append({"transaction_hash": receipt["transaction_hash"], "event_hashes": [memo_hash(value) for value in selected]})

            # Deliberately lose response before acceptance and reopen the persisted journal.
            identity_memo = encode("i", cid(ids["agent_alice"]), cid(ids["alice"]), signer.beta_wallet(ids["alice"])["address"])
            pending_operation = {"operation_id": str(uuid.uuid4()), "genesis_hash": signer.fingerprint, "memo": identity_memo}
            original_rpc = network.rpc
            interrupted = [False]
            def interrupted_rpc(path):
                if path.startswith("broadcast_tx_sync") and not interrupted[0]:
                    interrupted[0] = True
                    raise OSError("synthetic lost send")
                return original_rpc(path)
            before = network.balance(treasury)
            network.rpc = interrupted_rpc
            pending = signer.beta_trace(pending_operation)
            network.rpc = original_rpc
            signer.db.close()
            signer = BetaSigner(directory, network)
            receipt = settled(lambda: signer.beta_trace(pending_operation))
            require(receipt["transaction_hash"] == pending["transaction_hash"], "trace restart replays exact signed bytes")
            require(network.balance(treasury) == before - 1000, "trace charges treasury fee only")
            rejects(lambda: signer.beta_trace({**pending_operation, "operation_id": str(uuid.uuid4())}), "TRACE_EVENT_ALREADY_BOUND")
            rejects(lambda: signer.beta_trace({**pending_operation, "memo": identity_memo + " "}), "INVALID_TRACE_EVENT")
            transactions.append(receipt["transaction_hash"])
            memos.append(identity_memo)
            trace(encode("i", cid(ids["agent_bob"]), cid(ids["bob"]), signer.beta_wallet(ids["bob"])["address"]))
            trace(encode("m", cid(ids["migration"]), chash("a" * 64), chash("b" * 64), 1789920000000, 2, 1))
            trace(encode("v", cid(ids["version"]), cid(ids["artwork"]), cid(ids["agent_alice"]), chash("c" * 64), "a", 1000))
            trace(encode("l", cid(ids["version"]), None, None))
            trace(encode("b", cid(ids["version"]), cid(ids["asset"]), chash("d" * 64), "primary"))
            publication_memo = encode("p", cid(ids["piece"]), cid(ids["version"]), cid(ids["alice"]), cid(ids["alice"]), "gallery", cid(ids["artwork"]), 2000)
            trace(publication_memo)
            seal("piece", ids["piece"], memos[:])
            migration_memos = [value for value in memos if decode(value)["kind"] != "seal"]
            seal("migration", ids["migration"], migration_memos)

            rent_hash = transfer("rent", ids["bob"], ids["alice"], 2 * UNIT, ids["rent"])
            trace(encode("r", cid(ids["rent"]), cid(ids["piece"]), cid(ids["version"]), cid(ids["bob"]), cid(ids["alice"]), cid(ids["workspace"]), chash(rent_hash)))
            trace(encode("g", cid(ids["workspace"]), cid(ids["piece"]), cid(ids["version"]), cid(ids["bob"]), "rent", cid(ids["rent"]), chash("e" * 64)))
            trace(encode("a", cid(ids["attempt"]), cid(ids["workspace"]), cid(ids["bob"]), "create_svg", chash("f" * 64)))
            action_hash = transfer("action", ids["bob"], None, UNIT, ids["attempt"])
            trace(encode("c", cid(ids["attempt"]), cid(ids["attempt"]), chash(action_hash)))
            trace(encode("v", cid(ids["branch_version"]), cid(ids["branch"]), cid(ids["agent_bob"]), chash("3" * 64), "a", 3000))
            trace(encode("l", cid(ids["branch_version"]), None, cid(ids["version"])))
            trace(encode("b", cid(ids["branch_version"]), cid(ids["branch_asset"]), chash("4" * 64), "primary"))
            trace(encode("d", cid(ids["attempt"]), cid(ids["branch_version"]), "succeeded"))
            trace(encode("p", cid(ids["branch_piece"]), cid(ids["branch_version"]), cid(ids["bob"]), cid(ids["bob"]), "native", cid(ids["workspace"]), 4000))
            sale_hash = transfer("sale", ids["bob"], ids["alice"], 20 * UNIT, ids["sale"])
            trace(encode("s", cid(ids["sale"]), cid(ids["piece"]), cid(ids["alice"]), cid(ids["bob"]), chash(sale_hash), chash(memo_hash(publication_memo))))
            trace(encode("a", cid(ids["failed"]), cid(ids["workspace"]), cid(ids["bob"]), "create_svg", chash("5" * 64)))
            failed_payment = transfer("action", ids["bob"], None, UNIT, ids["failed"])
            trace(encode("c", cid(ids["failed"]), cid(ids["failed"]), chash(failed_payment)))
            refund_hash = transfer("refund", None, ids["bob"], UNIT + 1000, ids["refund"], ids["failed"])
            trace(encode("f", cid(ids["failed"]), cid(ids["refund"]), chash(refund_hash)))
            trace(encode("d", cid(ids["failed"]), None, "refunded"))
            seal("workspace", ids["workspace"], [value for value in memos if decode(value)["kind"] != "seal"])
            proof = {"format": "foundry-trace-proof-v1", "chain_id": "luxartium-local-1", "genesis_hash": signer.fingerprint, "issuer_address": treasury,
                     "transactions": transactions, "seals": seal_specs, "subject": {"scope": "workspace", "id": ids["workspace"]}}
            result = verify_proof(proof, network.rpc, signer.fingerprint, treasury)
            require(result["owners"][ids["piece"]] == ids["bob"] and result["rentals"] == 1 and result["versions"] == 2, "DB-free replay reconstructs migration, rental, branch, sale and refund")
            require(verify_latest_ownership(proof, result, network.rpc, treasury)["current_through_height"] > 0, "full attestor scan verifies current ownership without database")
            earlier = {**proof, "transactions": transactions[:transactions.index(seal_specs[0]["transaction_hash"]) + 1],
                       "seals": seal_specs[:1], "subject": {"scope": "piece", "id": ids["piece"]}}
            earlier_result = verify_proof(earlier, network.rpc, signer.fingerprint, treasury)
            rejects(lambda: verify_latest_ownership(earlier, earlier_result, network.rpc, treasury), "STALE_OR_INCOMPLETE_OWNERSHIP_PROOF")
            rejects(lambda: verify_proof(proof, network.rpc, "0" * 64, treasury), "PROOF_IDENTITY_MISMATCH")
            rejects(lambda: verify_proof({**proof, "genesis_hash": "0" * 64}, network.rpc, "0" * 64, treasury), "WRONG_GENESIS")
            require(verify_proof({**proof, "transactions": transactions[::-1]}, network.rpc, signer.fingerprint, treasury) == result, "proof list permutation uses actual chain ordering")
            rejects(lambda: verify_proof({**proof, "transactions": transactions[1:]}, network.rpc, signer.fingerprint, treasury), "MISSING_CREATOR_IDENTITY")
            changed_seals = [{**entry, "event_hashes": entry["event_hashes"][1:]} if index == 0 else entry for index, entry in enumerate(seal_specs)]
            rejects(lambda: verify_proof({**proof, "seals": changed_seals}, network.rpc, signer.fingerprint, treasury), "SEAL_SET_MISMATCH")
            # A valid blockchain transaction from a wallet is not an attestor event.
            forged_memo = encode("i", cid(str(uuid.uuid4())), cid(str(uuid.uuid4())), signer.beta_wallet(ids["bob"])["address"])
            forged_id = str(uuid.uuid4())
            with signer.lock:
                forged = signer.execute(forged_id, {"fixture": "forgery"}, signer.key_name(ids["bob"]), treasury, 1, forged_memo)
            while forged["state"] == "pending":
                __import__("time").sleep(0.5)
                with signer.lock:
                    forged = signer.execute(forged_id, {"fixture": "forgery"}, signer.key_name(ids["bob"]), treasury, 1, forged_memo)
            rejects(lambda: verify_proof({**proof, "transactions": transactions + [forged["transaction_hash"]]}, network.rpc, signer.fingerprint, treasury), "WRONG_TRACE_ISSUER_OR_TRANSFER")
            signer.db.close()
            signer = None
            network.stop()
            network.start()
            require(verify_proof(proof, network.rpc, proof["genesis_hash"], treasury)["verified"], "independent verification survives chain restart")
            evidence.update({"result": "PASS", "genesis_hash": proof["genesis_hash"], "verification": result, "transaction_count": len(transactions), "proof": proof,
                             "checks": ["exact-byte restart replay", "treasury fee only", "duplicate event refusal", "strict memo privacy",
                                        "DB-free migration/rental/branch/sale/refund graph", "current ownership scan", "stale proof refusal",
                                        "wrong genesis refusal", "actual chain ordering", "missing event refusal", "omitted seal member refusal",
                                        "forged issuer refusal", "chain restart", "owned disposable cleanup"]})
    finally:
        if signer:
            signer.db.close()
        if network.inspect("container", network.name):
            network.require_owned("container", network.name)
            network.stop()
            run(["docker", "container", "rm", network.name])
        if network.inspect("volume", network.volume):
            network.require_owned("volume", network.volume)
            run(["docker", "volume", "rm", network.volume])
        require(not network.inspect("container", network.name) and not network.inspect("volume", network.volume), "owned disposable chain and private signer files cleaned up")
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build/trace-verification.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    verify()
