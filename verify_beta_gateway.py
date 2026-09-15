"""Real signer acceptance on a disposable chain. Never publishes credentials or uses localnet."""
import hashlib
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import time
import uuid

from gateway import BetaSigner, BETA_WELCOME, BETA_TREASURY_FUNDING, BETA_TREASURY, canonical
from localnet import Network, UNIT, FEE, ROOT, run
from verify import available_ports, require


def rejects(call, code):
    try:
        call()
    except ValueError as error:
        require(code in str(error), code + " rejected")
    else:
        raise AssertionError(code + " was accepted")


def settled(call):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        result = call()
        if result["state"] == "committed":
            return result
        if result["state"] == "failed":
            raise AssertionError("Test transaction failed on chain")
        time.sleep(0.5)
    raise AssertionError("Test transaction did not settle; its existing journal must be inspected")


def verify():
    network = Network("luxartium-check-" + uuid.uuid4().hex[:12], available_ports())
    if network.inspect("container", network.name) or network.inspect("volume", network.volume):
        raise RuntimeError("Test resource collision")
    evidence = {"test_network": network.name, "transactions": {}}
    signer = None
    try:
        network.init()
        network.start()
        with ExitStack() as cleanup:
            temporary = cleanup.enter_context(tempfile.TemporaryDirectory(prefix="foundry-beta-gateway-"))
            cleanup.callback(lambda: signer.db.close() if signer else None)
            directory = Path(temporary)
            clock = [100_000]
            signer = BetaSigner(directory, network, clock=lambda: clock[0])
            funding = settled(signer.initialize_beta)
            treasury = funding["treasury_address"]
            evidence["genesis_hash"] = signer.fingerprint
            evidence["transactions"]["bootstrap"] = funding["transaction_hash"]
            require(network.balance(treasury) == BETA_TREASURY_FUNDING, "beta treasury funded with existing test coins")
            require(settled(signer.initialize_beta)["transaction_hash"] == funding["transaction_hash"], "bootstrap replays the same transaction")
            accounts = [str(uuid.uuid4()) for _ in range(3)]
            deliveries = [{"account_id": account, "delivery_token": __import__("secrets").token_urlsafe(32), "acknowledge": False} for account in accounts]
            wallets = [signer.beta_enroll(delivery) for delivery in deliveries]
            require(all(len(wallet.get("private_key_hex", "")) == 64 for wallet in wallets), "signup callers receive native private keys")
            replay = signer.beta_enroll(deliveries[0])
            require(replay["address"] == wallets[0]["address"] and replay["private_key_hex"] == wallets[0]["private_key_hex"], "interrupted key delivery recovers the same wallet")
            rejects(lambda: signer.beta_enroll({**deliveries[0], "delivery_token": "x" * 43}), "KEY_DELIVERY_FORBIDDEN")
            signer.beta_enroll({**deliveries[0], "acknowledge": True})
            require("private_key_hex" not in signer.beta_enroll(deliveries[0]) and "private_key_hex" not in signer.beta_wallet(accounts[0]), "acknowledged keys never appear in ordinary wallet reads or delivery replay")
            real_address, real_cli = network.address, network.cli
            exports = []
            def changed_address(name):
                return real_address(signer.key_name(accounts[0])) if name == signer.key_name(accounts[1]) else real_address(name)
            def track_exports(args, **kwargs):
                if args[:2] == ["keys", "export"]:
                    exports.append(True)
                return real_cli(args, **kwargs)
            network.address, network.cli = changed_address, track_exports
            rejects(lambda: signer.beta_enroll(deliveries[1]), "WALLET_IDENTITY_CHANGED")
            require(not exports, "keyring identity mismatch prevents private-key export")
            network.address, network.cli = real_address, real_cli
            # Only public records enter evidence; discard the delivered secret material.
            del replay, wallets

            def operation(kind, source, destination, amount, reversal=None):
                identity = str(uuid.uuid4())
                return {"operation_id": identity, "kind": kind, "from_account_id": source,
                        "to_account_id": destination, "amount_uluxar": str(amount),
                        "reference_hash": hashlib.sha256(identity.encode()).hexdigest(),
                        "reverses_operation_id": reversal, "genesis_hash": signer.fingerprint}

            grants = [operation("grant", None, account, BETA_WELCOME) for account in accounts]
            for index, grant in enumerate(grants):
                receipt = settled(lambda: signer.beta_operation(grant))
                evidence["transactions"][f"grant_{index}"] = receipt["transaction_hash"]
                require(int(signer.beta_wallet(accounts[index])["balance_uluxar"]) == BETA_WELCOME, f"account {index} receives exactly 500 LUXAR")
            same = settled(lambda: signer.beta_operation(grants[0]))
            require(same["transaction_hash"] == evidence["transactions"]["grant_0"], "signup grant replay cannot double-pay")
            rejects(lambda: signer.beta_operation(operation("grant", None, accounts[0], BETA_WELCOME)), "WELCOME_ALREADY_CLAIMED")
            rejects(lambda: signer.beta_operation({**grants[0], "reference_hash": "f" * 64}), "IDEMPOTENCY_CONFLICT")
            rejects(lambda: signer.beta_operation({**grants[0], "amount_uluxar": "500000001"}), "INVALID_WELCOME_GRANT")

            action = operation("action", accounts[0], None, UNIT)
            before_treasury = network.balance(treasury)
            pending = signer.beta_operation(action)
            require(pending["state"] in ("pending", "committed"), "action signs and journals before responding")
            signer.db.close()
            signer = BetaSigner(directory, network, clock=lambda: clock[0])
            paid = settled(lambda: signer.beta_operation(action))
            evidence["transactions"]["action"] = paid["transaction_hash"]
            require(paid["transaction_hash"] == pending["transaction_hash"], "gateway restart reuses the exact signed transaction")
            require(network.balance(treasury) == before_treasury + UNIT and int(signer.beta_wallet(accounts[0])["balance_uluxar"]) == BETA_WELCOME - UNIT - FEE,
                    "creative action pays 1 LUXAR to Foundry with network fee recorded separately")
            require(paid["memo"].endswith(action["reference_hash"]) and paid["operation_id"] == action["operation_id"], "chain receipt binds the exact logical creative action")

            refund = operation("refund", None, accounts[0], UNIT + FEE, action["operation_id"])
            refunded = settled(lambda: signer.beta_operation(refund))
            evidence["transactions"]["refund"] = refunded["transaction_hash"]
            require(int(signer.beta_wallet(accounts[0])["balance_uluxar"]) == BETA_WELCOME, "failed-action refund restores the action price and its fee")
            rejects(lambda: signer.beta_operation(operation("refund", None, accounts[1], UNIT + FEE, action["operation_id"])), "REFUND_REQUIRES_COMMITTED_ACTION")
            rejects(lambda: signer.beta_operation(operation("refund", None, accounts[0], UNIT + FEE, action["operation_id"])), "ACTION_ALREADY_REFUNDED")

            sale = operation("sale", accounts[1], accounts[0], 20 * UNIT)
            evidence["transactions"]["sale"] = settled(lambda: signer.beta_operation(sale))["transaction_hash"]
            rent = operation("rent", accounts[2], accounts[1], 2 * UNIT)
            evidence["transactions"]["rent"] = settled(lambda: signer.beta_operation(rent))["transaction_hash"]
            require(int(signer.beta_wallet(accounts[0])["balance_uluxar"]) == 520 * UNIT and int(signer.beta_wallet(accounts[1])["balance_uluxar"]) == 482 * UNIT - FEE,
                    "buyer pays seller, then receives rent directly as the new owner")
            commit = operation("commit", None, None, 1)
            anchored = settled(lambda: signer.beta_operation(commit))
            evidence["transactions"]["commit"] = anchored["transaction_hash"]
            require(anchored["sender"] == treasury and anchored["recipient"] == treasury and anchored["memo"].endswith(commit["reference_hash"]), "final-version hash can be anchored without charging the artist")
            rejects(lambda: signer.beta_operation({**rent, "genesis_hash": "0" * 64}), "WRONG_NETWORK")
            real_rpc = network.rpc
            def changed_chain(path):
                data = real_rpc(path)
                if path == "genesis":
                    data["result"]["genesis"]["genesis_time"] = "2000-01-01T00:00:00Z"
                return data
            network.rpc = changed_chain
            rejects(lambda: signer.beta_operation(rent), "CHAIN_IDENTITY_CHANGED")
            network.rpc = real_rpc
            clock[0] += 1801
            rejects(lambda: signer.beta_enroll(deliveries[2]), "KEY_DELIVERY_EXPIRED")
            evidence["result"] = "PASS"
            signer.db.close()
            signer = None
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
        require(network.inspect("container", network.name) is None and network.inspect("volume", network.volume) is None,
                "disposable beta chain and keys cleaned up")
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build/beta-gateway-verification.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    verify()
