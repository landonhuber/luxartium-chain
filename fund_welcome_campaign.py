"""One fixed existing-supply campaign top-up. Default plan never signs/broadcasts.

Use one protected operator directory for this campaign. Prepare durably saves the
exact intent/signature; broadcast only uses those saved bytes. Never re-sign an
uncertain outcome. No faucet key is exported or copied to the hosted signer.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from admin_auth import assert_plain_path
from gateway import canonical, exclusive_process
from localnet import CHAIN_ID, DENOM, FEE, Network, run

GENESIS = "dd59a7a33d4d2796e52f985ff913b1f158fe09fa2d044fc63b17d24d2c0d0707"
DAEMON_IMAGE = "sha256:bcf43413a0ea468c0fd6c48826e64cabe41366987d0a7e7fdbf406f6693ea272"
FAUCET = "luxar17373u6xlx8mcptt6gxvugmcgtd99t2epjefn2y"
TREASURY = "luxar1kyfg7ex2llzrctstgpkh7je50deyyvt9tfayug"
AMOUNT = "1500005000000"
MEMO = "foundry:welcome-waterfall-v1:treasury"
MAX_TRANSACTION_BYTES = 65536


def validate_transaction(value):
    expected = {"@type": "/cosmos.bank.v1beta1.MsgSend", "from_address": FAUCET,
                "to_address": TREASURY, "amount": [{"denom": DENOM, "amount": AMOUNT}]}
    body, fee = value["body"], value["auth_info"]["fee"]
    if body["messages"] != [expected] or body["memo"] != MEMO or body.get("timeout_height", "0") != "0" or body.get("extension_options", []) or body.get("non_critical_extension_options", []):
        raise ValueError("UNEXPECTED_FUNDING_TRANSACTION")
    if fee["amount"] != [{"denom": DENOM, "amount": str(FEE)}] or fee["gas_limit"] != "200000" or fee.get("payer", "") or fee.get("granter", ""):
        raise ValueError("UNEXPECTED_FUNDING_FEE")


def save(path, data):
    with path.open("xb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def read_bounded(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_TRANSACTION_BYTES + 1)
    if len(data) > MAX_TRANSACTION_BYTES:
        raise ValueError("FUNDING_ARTIFACT_TOO_LARGE")
    return data.decode("utf-8")


def cli(network, args, data=None):
    result = run(["docker", "exec", "-i", network.name, "luxartiumd", *args, "--home", "/chain"],
                 input_text=data, check=False, timeout=60)
    if result.returncode:
        raise ValueError("FUNDING_CLI_UNAVAILABLE")
    return result.stdout


def execute(directory, mode="plan", network=None):
    directory = directory.resolve(strict=True)
    assert_plain_path(directory)
    network = network or Network()
    container = network.require_owned("container", network.name)
    if container["Image"] != DAEMON_IMAGE or not container["State"]["Running"]:
        raise ValueError("PINNED_EXISTING_FOLLOWER_REQUIRED")
    genesis = network.rpc("genesis")["result"]["genesis"]
    if hashlib.sha256(canonical(genesis).encode()).hexdigest() != GENESIS or network.address("faucet") != FAUCET:
        raise ValueError("FUNDING_IDENTITY_MISMATCH")
    # The original signer remains fenced; this separate owner faucet operation
    # does not instantiate a signer or regain managed-beta signing authority.
    fence = Path.home() / ".luxartium/gateway/signing-moved.json"
    assert_plain_path(fence)
    if json.loads(read_bounded(fence))["genesis_hash"] != GENESIS:
        raise ValueError("ORIGINAL_SIGNER_FENCE_REQUIRED")
    paths = {name: directory / ("welcome-waterfall-funding." + name) for name in ("intent.json", "signed.json", "tx.base64", "receipt.json")}
    for path in paths.values():
        assert_plain_path(path)
    metadata = {"genesis_hash": GENESIS, "sender": FAUCET, "recipient": TREASURY, "amount_uluxar": AMOUNT, "fee_uluxar": str(FEE), "memo": MEMO}
    if mode == "plan":
        return {"mode": "plan", **metadata, "faucet_balance_uluxar": str(network.balance(FAUCET)), "treasury_balance_uluxar": str(network.balance(TREASURY)), "prior_intent": paths["intent.json"].exists()}
    with exclusive_process(directory / "welcome-funding.lock"):
        if mode == "prepare":
            if any(path.exists() for path in paths.values()):
                raise ValueError("FUNDING_INTENT_EXISTS_RECOVER_SAVED_BYTES")
            if network.balance(FAUCET) < int(AMOUNT) + FEE:
                raise ValueError("FUNDING_RESERVE_INSUFFICIENT")
            unsigned = cli(network, ["tx", "bank", "send", "faucet", TREASURY, AMOUNT + DENOM,
                "--chain-id", CHAIN_ID, "--keyring-backend", "test", "--fees", str(FEE) + DENOM,
                "--gas", "200000", "--note", MEMO, "--generate-only", "--output", "json"])
            if len(unsigned.encode()) > MAX_TRANSACTION_BYTES:
                raise ValueError("FUNDING_ARTIFACT_TOO_LARGE")
            validate_transaction(json.loads(unsigned))
            save(paths["intent.json"], canonical({**metadata, "unsigned": json.loads(unsigned)}).encode())
            signed = cli(network, ["tx", "sign", "/dev/stdin", "--from", "faucet", "--chain-id", CHAIN_ID,
                "--keyring-backend", "test", "--output", "json"], unsigned)
            if len(signed.encode()) > MAX_TRANSACTION_BYTES:
                raise ValueError("FUNDING_ARTIFACT_TOO_LARGE")
            decoded = json.loads(signed); validate_transaction(decoded)
            if len(decoded["signatures"]) != 1:
                raise ValueError("FUNDING_SIGNATURE_REQUIRED")
            save(paths["signed.json"], signed.encode())
            encoded = cli(network, ["tx", "encode", "/dev/stdin"], signed).strip().strip('"')
            raw = base64.b64decode(encoded, validate=True)
            digest = hashlib.sha256(raw).hexdigest().upper()
            save(paths["tx.base64"], (encoded + "\n").encode())
            return {"mode": "prepared", "transaction_hash": digest, "broadcast": False, **metadata}
        if mode not in ("broadcast", "verify"):
            raise ValueError("INVALID_FUNDING_MODE")
        intent = json.loads(read_bounded(paths["intent.json"]))
        if {key: intent[key] for key in metadata} != metadata:
            raise ValueError("FUNDING_INTENT_CHANGED")
        signed = read_bounded(paths["signed.json"])
        validate_transaction(json.loads(signed))
        encoded = read_bounded(paths["tx.base64"]).strip()
        if cli(network, ["tx", "encode", "/dev/stdin"], signed).strip().strip('"') != encoded:
            raise ValueError("FUNDING_SIGNED_BYTES_CHANGED")
        raw = base64.b64decode(encoded, validate=True)
        digest = hashlib.sha256(raw).hexdigest().upper()
        try:
            receipt = network.rpc("tx?hash=0x" + digest)["result"]
        except (OSError, ValueError, KeyError):
            receipt = None
        if receipt:
            if receipt["tx"] != encoded or receipt["hash"].upper() != digest or int(receipt["height"]) <= 0 or int(receipt["tx_result"]["code"]) != 0:
                raise ValueError("FUNDING_TERMINAL_FAILURE_OR_BYTE_MISMATCH")
            report = {"mode": "committed", "transaction_hash": digest, "height": receipt["height"], **metadata}
            if not paths["receipt.json"].exists():
                save(paths["receipt.json"], canonical(report).encode())
            return report
        if mode == "broadcast":
            # Bytes were durably saved before this point. A lost response retains
            # the exact hash and may only replay this same request.
            reply = network.rpc("broadcast_tx_sync?tx=0x" + raw.hex())["result"]
            if reply["hash"].upper() != digest or int(reply["code"]) != 0:
                raise ValueError("FUNDING_BROADCAST_REJECTED_RECONCILE_SAVED_BYTES")
        return {"mode": "pending", "transaction_hash": digest, "confirmation_required": True, **metadata}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "prepare", "broadcast", "verify"), nargs="?", default="plan")
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.directory, args.mode)))
    except Exception:
        raise SystemExit("Funding stopped. Retain the protected journal and query/replay its saved transaction; never create a replacement signature for an unknown outcome.")
