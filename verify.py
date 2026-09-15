"""Acceptance test on a fresh, independently named chain; never uses the saved localnet."""
from __future__ import annotations

import json
import socket
import time
import urllib.request
import uuid

from localnet import Network, UNIT, DENOM, FEE, SUPPLY, CHAIN_ID, ROOT, run


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    print("PASS " + message, flush=True)


def available_ports() -> tuple[int, int, int]:
    sockets = [socket.socket() for _ in range(3)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return tuple(sock.getsockname()[1] for sock in sockets)
    finally:
        for sock in sockets:
            sock.close()


def verify() -> None:
    network = Network("luxartium-check-" + uuid.uuid4().hex[:12], available_ports())
    if network.inspect("volume", network.volume) or network.inspect("container", network.name):
        raise RuntimeError("Unexpected test-resource collision; no resources changed")
    evidence: dict = {"chain_id": CHAIN_ID, "test_network": network.name}
    try:
        network.init()
        try:
            network.init()
            raise AssertionError("second initialization unexpectedly succeeded")
        except RuntimeError as error:
            require("already exists" in str(error), "reinitialization refuses existing keys and state")
        genesis = json.loads(network.read_config("genesis.json"))
        state = genesis["app_state"]
        require("mint" not in state, "no mint module or automatic inflation")
        require(state["staking"]["params"]["bond_denom"] == DENOM, "staking uses native Luxartium")
        require(state["staking"]["params"]["key_rotation_fee"]["denom"] == DENOM,
                "validator key-rotation fee uses the native staking denomination")
        metadata = state["bank"]["denom_metadata"][0]
        require(metadata["base"] == DENOM and metadata["symbol"] == "LUXAR" and
                metadata["denom_units"][1]["exponent"] == 6, "LUXAR metadata has six decimal places")
        network.start()
        info = network.require_owned("container", network.name)
        bindings = info["HostConfig"]["PortBindings"]
        require(all(binding["HostIp"] == "127.0.0.1" for entries in bindings.values() for binding in entries),
                "all published ports are bound to host loopback")
        alice = network.wallet("alice")
        bob = network.wallet("bob")
        require(alice.startswith("luxar1") and bob.startswith("luxar1") and alice != bob,
                "two distinct native wallets created")
        faucet = network.address("faucet")
        before_faucet = network.balance(faucet)
        funding = network.send("faucet", alice, 100 * UNIT)
        require(network.balance(alice) == 100 * UNIT and network.balance(faucet) == before_faucet - 100 * UNIT - FEE,
                "faucet transfers existing coins and pays the exact native fee")
        transfer = network.send("alice", bob, 12_500_000)
        require(network.balance(alice) == 87_499_000 and network.balance(bob) == 12_500_000,
                "12.5 LUXAR transfer debits Alice by amount plus 0.001 LUXAR and credits Bob exactly")
        require(transfer["tx"]["auth_info"]["fee"]["amount"] == [{"denom": DENOM, "amount": str(FEE)}],
                "committed transaction records its native fee")
        module_accounts = json.loads(network.cli(["query", "auth", "module-accounts", "--output", "json"]).stdout)
        require(all("minter" not in account.get("permissions", []) for account in module_accounts["accounts"]),
                "live module accounts have no mint permission")
        supply = json.loads(network.cli(["query", "bank", "total", "--output", "json"]).stdout)["supply"]
        require(supply == [{"denom": DENOM, "amount": str(SUPPLY)}], "total supply remains 1,000,000,000 LUXAR after transactions")
        for name, args in [
            ("insufficient native fee", ["tx", "bank", "send", "bob", alice, f"1{DENOM}", "--fees", f"999{DENOM}"]),
            ("external fee denomination", ["tx", "bank", "send", "bob", alice, f"1{DENOM}", "--fees", "1000stake"]),
            ("wrong chain signature", ["tx", "bank", "send", "bob", alice, f"1{DENOM}", "--fees", f"{FEE}{DENOM}"]),
        ]:
            chain = "luxartium-wrong-1" if name == "wrong chain signature" else CHAIN_ID
            result = network.cli(args + ["--chain-id", chain, "--keyring-backend", "test", "--gas", "200000",
                                         "--broadcast-mode", "sync", "--yes", "--output", "json"], check=False)
            rejected = result.returncode != 0
            if not rejected:
                rejected = int(json.loads(result.stdout).get("code", 0)) != 0
            require(rejected, name + " rejected")
        require(network.balance(alice) == 87_499_000 and network.balance(bob) == 12_500_000,
                "transactions rejected before inclusion do not change balances")
        overspend = json.loads(network.cli(["tx", "bank", "send", "bob", alice, f"{1000 * UNIT}{DENOM}",
            "--fees", f"{FEE}{DENOM}", "--chain-id", CHAIN_ID, "--keyring-backend", "test", "--gas", "200000",
            "--broadcast-mode", "sync", "--yes", "--output", "json"]).stdout)
        require(int(overspend.get("code", 0)) == 0, "valid overspend signature is admitted for block execution")
        failed = network.wait_tx(overspend["txhash"])
        require(int(failed["code"]) != 0 and network.balance(alice) == 87_499_000 and network.balance(bob) == 12_499_000,
                "committed overspend fails without transferring funds and charges only its native execution fee")
        before_height = network.wait_height(1)
        network.stop()
        network.start()
        after_height = network.wait_height(before_height + 2)
        require(network.balance(alice) == 87_499_000 and network.balance(bob) == 12_499_000,
                "wallet balances survive node restart")
        require(network.address("alice") == alice and network.address("bob") == bob, "wallet identities survive node restart")
        remembered = json.loads(network.cli(["query", "tx", transfer["txhash"], "--output", "json"]).stdout)
        require(remembered["txhash"] == transfer["txhash"] and after_height > before_height,
                "transaction history persists and new blocks commit after restart")
        after_restart = network.send("bob", alice, UNIT)
        require(network.balance(alice) == 88_499_000 and network.balance(bob) == 11_498_000,
                "a retained wallet can sign and transfer after restart")
        with urllib.request.urlopen(f"http://127.0.0.1:{network.ports[1]}/cosmos/bank/v1beta1/balances/{bob}", timeout=10) as response:
            rest = json.load(response)
        require(rest["balances"] == [{"denom": DENOM, "amount": "11498000"}], "REST API agrees with committed wallet balance")
        evidence.update({"result": "PASS", "genesis_supply_uluxar": str(SUPPLY), "fee_uluxar": str(FEE),
                         "alice": alice, "bob": bob, "funding_tx": funding["txhash"], "transfer_tx": transfer["txhash"],
                         "failed_overspend_tx": failed["txhash"], "post_restart_tx": after_restart["txhash"], "height_before_restart": before_height,
                         "height_after_restart": after_height})
    finally:
        # Only exact UUID-named resources created for this test may be removed.
        if network.inspect("container", network.name):
            network.require_owned("container", network.name)
            network.stop()
            run(["docker", "container", "rm", network.name])
        if network.inspect("volume", network.volume):
            network.require_owned("volume", network.volume)
            run(["docker", "volume", "rm", network.volume])
        require(network.inspect("container", network.name) is None and network.inspect("volume", network.volume) is None,
                "disposable test node and wallet volume cleaned up")
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build/verification.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Luxartium acceptance test passed.", flush=True)


if __name__ == "__main__":
    verify()
