"""Actual bank signing, tier replay and unfunded key delivery on an owned chain."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import uuid

from gateway import BetaSigner, BETA_TREASURY, canonical
from localnet import Network, FEE, ROOT, UNIT, run
from verify import available_ports, require
from verify_beta_gateway import settled, rejects
from welcome_policy import CAMPAIGN, activate, amount_for, initialize


def verify():
    network = Network("luxartium-check-" + uuid.uuid4().hex[:12], available_ports())
    if network.inspect("container", network.name) or network.inspect("volume", network.volume):
        raise RuntimeError("Disposable resource collision")
    evidence = {"test_network": network.name, "tiers": [], "daemon_unchanged": True}
    signer = None
    try:
        network.init(); network.start()
        with ExitStack() as stack:
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="welcome-gateway-")))
            stack.callback(lambda: signer.db.close() if signer else None)
            signer = BetaSigner(directory, network)
            settled(signer.initialize_beta)
            treasury = signer.beta_treasury()
            initial_balance = network.balance(treasury)
            value = {"version": 1, "policy_id": CAMPAIGN, "genesis_hash": signer.fingerprint, "legacy_profiles": []}
            digest = hashlib.sha256(canonical(value).encode()).hexdigest()
            activate(signer.db, value, digest, signer.fingerprint)
            signer.welcome_campaign = initialize(signer.db, signer.fingerprint)
            evidence.update(genesis_hash=signer.fingerprint, snapshot_hash=digest)
            grant_sum = 0
            for ordinal in ("1", "1001", "2001", "3001", "4001", "5001"):
                account, operation, agent = (str(uuid.uuid4()) for _ in range(3))
                auth = {"agent_id": agent, "operation_id": operation, "policy_id": CAMPAIGN,
                        "ordinal": ordinal, "amount_uluxar": amount_for(ordinal)}
                token = secrets.token_urlsafe(32)
                provision = {"account_id": account, "delivery_token": token, "welcome_grant": auth}
                wallet = signer.beta_provision(provision)
                require(wallet["balance_uluxar"] == "0", "public provisioning starts unfunded")
                delivery = {"account_id": account, "delivery_token": token, "acknowledge": False}
                body = {"operation_id": operation, "kind": "grant", "from_account_id": None, "to_account_id": account,
                        "amount_uluxar": auth["amount_uluxar"], "reference_hash": hashlib.sha256(operation.encode()).hexdigest(),
                        "reverses_operation_id": None, "genesis_hash": signer.fingerprint,
                        "grant_authorization": {key: auth[key] for key in ("policy_id", "ordinal", "amount_uluxar")}}
                before_count = signer.db.execute("SELECT count(*) FROM operations").fetchone()[0]
                if auth["amount_uluxar"] != "0":
                    first = signer.beta_operation(body)
                    saved = signer.db.execute("SELECT signed FROM operations WHERE id=?", (operation,)).fetchone()[0]
                    signer.db.close(); signer = BetaSigner(directory, network)
                    receipt = settled(lambda: signer.beta_operation(body))
                    require(first["transaction_hash"] == receipt["transaction_hash"], "restart preserves exact signed transaction")
                    require(saved == signer.db.execute("SELECT signed FROM operations WHERE id=?", (operation,)).fetchone()[0], "restart never signs replacement bytes")
                    require(signer.beta_operation(body) == receipt, "completed tier grant replays")
                    require(int(receipt["amount_uluxar"]) == int(auth["amount_uluxar"]), "exact tier amount committed")
                    evidence["tiers"].append({"ordinal": ordinal, "amount_uluxar": auth["amount_uluxar"], "transaction_hash": receipt["transaction_hash"], "height": receipt["height"]})
                    grant_sum += int(auth["amount_uluxar"])
                else:
                    rejects(lambda: signer.beta_operation(body), "INVALID_AMOUNT")
                    require(signer.db.execute("SELECT count(*) FROM operations").fetchone()[0] == before_count, "zero allocation never creates a fake transaction")
                delivered = signer.beta_enroll(delivery)
                require(len(delivered["private_key_hex"]) == 64, "funded and zero wallets both deliver native keys")
                require(delivered["balance_uluxar"] == auth["amount_uluxar"], "wallet has only its exact welcome amount")
                signer.beta_enroll({**delivery, "acknowledge": True})
                require("private_key_hex" not in signer.beta_enroll(delivery), "acknowledged keys remain private")
                rejects(lambda: signer.beta_provision({**provision, "account_id": str(uuid.uuid4())}), "WELCOME_ALLOCATION_CONFLICT")
                rejects(lambda: signer.beta_operation({key: value for key, value in body.items() if key != "grant_authorization"}), "INVALID_AMOUNT" if ordinal == "5001" else "WELCOME_AUTHORIZATION_REQUIRED")
                del delivered, token, delivery, provision
            require(initial_balance - network.balance(treasury) == grant_sum + 5 * FEE, "treasury pays exactly five grants and five normal fees")
            require(signer.db.execute("SELECT count(*) FROM beta_welcome_allocations").fetchone()[0] == 6, "six immutable allocations survive restart")
            evidence.update(zero_wallet_enrolled=True, signed_grants=5, grant_sum_uluxar=str(grant_sum), fees_uluxar=str(5 * FEE), passed=True)
            (ROOT / "build").mkdir(exist_ok=True)
            (ROOT / "build/welcome-gateway-acceptance.json").write_text(json.dumps(evidence, indent=2))
            print("PASS actual welcome signer: five exact tiers, durable signed replay/restart, zero-funded key enrollment and no zero transaction.")
    finally:
        if network.inspect("container", network.name):
            network.require_owned("container", network.name); network.stop(); run(["docker", "container", "rm", network.name])
        if network.inspect("volume", network.volume):
            network.require_owned("volume", network.volume); run(["docker", "volume", "rm", network.volume])
        print("Owned welcome test chain and wallet state cleaned.")


if __name__ == "__main__":
    verify()
