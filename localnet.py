#!/usr/bin/env python3
"""Local Docker operator for Luxartium. No Foundry credentials or dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
IMAGE = "luxartium-local:0.1.0"
CHAIN_ID = "luxartium-local-1"
DENOM = "uluxar"
UNIT = 1_000_000
FEE = 1_000
SUPPLY = 1_000_000_000 * UNIT
LABEL = "io.aiartfoundry.luxartium"
LABEL_VALUE = "localnet-v1"


def run(args: list[str], *, input_text: str | None = None, check: bool = True,
        timeout: int = 120) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, input=input_text, text=True, encoding="utf-8",
                            capture_output=True, timeout=timeout)
    if check and result.returncode:
        # Do not echo command arguments: future wallet commands may contain secrets.
        raise RuntimeError((result.stderr or result.stdout).strip()[-4000:])
    return result


def source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted([ROOT / "Dockerfile", ROOT / "go.mod", ROOT / "go.sum",
                        *ROOT.glob("app/*.go"), *ROOT.glob("cmd/**/*.go")]):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def build() -> None:
    subprocess.run(["docker", "build", "--label", f"{LABEL}={LABEL_VALUE}",
                    "--label", f"{LABEL}.source={source_hash()}", "-t", IMAGE, str(ROOT)],
                   check=True)


def native_amount(value: str) -> int:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?", value):
        raise ValueError("Use a positive LUXAR amount with at most six decimal places.")
    whole, _, fraction = value.partition(".")
    amount = int(whole) * UNIT + int(fraction.ljust(6, "0") or "0")
    if amount <= 0 or amount > SUPPLY:
        raise ValueError("Amount must be positive and no greater than the test supply.")
    return amount


class Network:
    def __init__(self, name: str = CHAIN_ID, ports: tuple[int, int, int] = (26657, 1317, 9090)):
        if not re.fullmatch(r"luxartium-(?:local-1|full-1|check-[a-f0-9]{12})", name):
            raise ValueError("Unsupported local network name")
        self.name = name
        self.volume = name + "-data"
        self.ports = ports

    def inspect(self, kind: str, name: str) -> dict | None:
        result = run(["docker", kind, "inspect", name], check=False)
        if result.returncode:
            if "no such" in result.stderr.lower():
                return None
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)[0]

    def require_owned(self, kind: str, name: str) -> dict:
        data = self.inspect(kind, name)
        labels = (data or {}).get("Labels") if kind == "volume" else (data or {}).get("Config", {}).get("Labels")
        if not data or not labels or labels.get(LABEL) != LABEL_VALUE:
            raise RuntimeError(f"Refusing an absent or unrelated {kind}: {name}")
        return data

    def require_image(self) -> None:
        data = self.inspect("image", IMAGE)
        if not data or data.get("Config", {}).get("Labels", {}).get(LABEL + ".source") != source_hash():
            raise RuntimeError("Luxartium image is missing or older than its source. Run the build command.")

    def offline(self, args: list[str], *, entrypoint: str | None = None,
                input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.require_owned("volume", self.volume)
        cmd = ["docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=64m",
               "--mount", f"type=volume,source={self.volume},target=/chain"]
        if input_text is not None:
            cmd.append("-i")
        if entrypoint:
            cmd += ["--entrypoint", entrypoint]
        return run(cmd + [IMAGE] + args, input_text=input_text, check=check)

    def read_config(self, filename: str) -> str:
        if filename not in ("genesis.json", "config.toml", "app.toml"):
            raise ValueError("Only public configuration may be read")
        return self.offline([f"/chain/config/{filename}"], entrypoint="cat").stdout

    def write_config(self, filename: str, contents: str) -> None:
        if filename not in ("genesis.json", "config.toml", "app.toml"):
            raise ValueError("Only public configuration may be written")
        if self.inspect("container", self.name):
            raise RuntimeError("Configuration cannot be rewritten after the node is created")
        self.offline(["-c", f"umask 077; cat > /chain/config/{filename}"],
                     entrypoint="sh", input_text=contents)

    def init(self) -> None:
        self.require_image()
        if self.inspect("volume", self.volume) or self.inspect("container", self.name):
            raise RuntimeError("Local chain already exists. Init never overwrites state or keys; use start.")
        run(["docker", "volume", "create", "--label", f"{LABEL}={LABEL_VALUE}", self.volume])
        self.offline(["-c", "chmod 700 /chain"], entrypoint="sh")
        self.offline(["init", "local-validator", "--chain-id", CHAIN_ID, "--default-denom", DENOM, "--home", "/chain"])
        genesis = json.loads(self.read_config("genesis.json"))
        state = genesis["app_state"]
        state["staking"]["params"]["bond_denom"] = DENOM
        state["gov"]["params"]["min_deposit"] = [{"denom": DENOM, "amount": "1000000"}]
        state["gov"]["params"]["expedited_min_deposit"] = [{"denom": DENOM, "amount": "10000000"}]
        state["bank"]["denom_metadata"] = [{
            "description": "Disposable Luxartium testnet currency; no mainnet redemption promise.",
            "denom_units": [{"denom": DENOM, "exponent": 0, "aliases": []},
                            {"denom": "luxar", "exponent": 6, "aliases": ["LUXAR"]}],
            "base": DENOM, "display": "luxar", "name": "Luxartium", "symbol": "LUXAR",
            "uri": "", "uri_hash": "",
        }]
        self.write_config("genesis.json", json.dumps(genesis))
        config = self.read_config("config.toml")
        config = config.replace('timeout_commit = "5s"', 'timeout_commit = "1s"')
        self.write_config("config.toml", config)
        for name, amount in (("validator", 100_000 * UNIT), ("faucet", SUPPLY - 100_000 * UNIT)):
            self.offline(["keys", "add", name, "--no-backup", "--keyring-backend", "test", "--home", "/chain", "--output", "json"])
            address = self.offline(["keys", "show", name, "-a", "--keyring-backend", "test", "--home", "/chain"]).stdout.strip()
            self.offline(["genesis", "add-genesis-account", address, f"{amount}{DENOM}", "--home", "/chain"])
        self.offline(["genesis", "gentx", "validator", f"{10_000 * UNIT}{DENOM}", "--chain-id", CHAIN_ID,
                      "--keyring-backend", "test", "--home", "/chain"])
        self.offline(["genesis", "collect-gentxs", "--home", "/chain"])
        self.offline(["genesis", "validate-genesis", "--home", "/chain"])
        print(f"Initialized {self.name}: 1,000,000,000 test LUXAR, no automatic issuance.", flush=True)

    def start(self) -> None:
        self.require_image()
        self.require_owned("volume", self.volume)
        existing = self.inspect("container", self.name)
        if existing:
            self.require_owned("container", self.name)
            image = self.inspect("image", IMAGE)
            if existing["Image"] != image["Id"]:
                raise RuntimeError("Existing node uses a different image. A reviewed upgrade is required.")
            run(["docker", "start", self.name])
        else:
            rpc, api, grpc = self.ports
            run(["docker", "run", "-d", "--name", self.name, "--label", f"{LABEL}={LABEL_VALUE}",
                 "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                 "--tmpfs", "/tmp:rw,nosuid,size=64m", "--memory", "2g", "--cpus", "2",
                 "-e", "GOMAXPROCS=2", "--mount", f"type=volume,source={self.volume},target=/chain",
                 "-p", f"127.0.0.1:{rpc}:26657", "-p", f"127.0.0.1:{api}:1317",
                 "-p", f"127.0.0.1:{grpc}:9090", IMAGE,
                 "start", "--home", "/chain", "--rpc.laddr", "tcp://0.0.0.0:26657",
                 "--api.address", "tcp://0.0.0.0:1317", "--grpc.address", "0.0.0.0:9090",
                 "--log_level", "warn"])
        self.wait_height(1)

    def stop(self) -> None:
        self.require_owned("container", self.name)
        run(["docker", "stop", "--time", "30", self.name], timeout=45)

    def rpc(self, path: str) -> dict:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.ports[0]}/{path}", timeout=4) as response:
            return json.load(response)

    def wait_height(self, minimum: int, timeout: int = 60) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = self.rpc("status")["result"]
                if status["node_info"]["network"] != CHAIN_ID:
                    raise RuntimeError("Unexpected chain identity on the local RPC port")
                height = int(status["sync_info"]["latest_block_height"])
                if height >= minimum:
                    return height
            except (OSError, urllib.error.URLError, ValueError, KeyError):
                pass
            time.sleep(1)
        raise RuntimeError(f"Node did not reach height {minimum}; inspect docker logs {self.name}.")

    def cli(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.require_owned("container", self.name)
        return run(["docker", "exec", self.name, "luxartiumd", *args, "--home", "/chain"], check=check)

    def wallet(self, name: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name):
            raise ValueError("Wallet names must use lowercase letters, digits and hyphens.")
        self.cli(["keys", "add", name, "--no-backup", "--keyring-backend", "test", "--output", "json"])
        return self.address(name)

    def address(self, name: str) -> str:
        return self.cli(["keys", "show", name, "-a", "--keyring-backend", "test"]).stdout.strip()

    def balance(self, address: str) -> int:
        result = json.loads(self.cli(["query", "bank", "balances", address, "--output", "json"]).stdout)
        return sum(int(c["amount"]) for c in result["balances"] if c["denom"] == DENOM)

    def send(self, sender: str, recipient: str, amount: int, *, fee: int = FEE) -> dict:
        result = self.cli(["tx", "bank", "send", sender, recipient, f"{amount}{DENOM}",
                           "--chain-id", CHAIN_ID, "--keyring-backend", "test", "--fees", f"{fee}{DENOM}",
                           "--gas", "200000", "--broadcast-mode", "sync", "--yes", "--output", "json"])
        response = json.loads(result.stdout)
        if int(response.get("code", 0)) != 0:
            raise RuntimeError("Transaction rejected: " + response.get("raw_log", "unknown failure"))
        txhash = response["txhash"]
        committed = self.wait_tx(txhash)
        if int(committed.get("code", 0)) != 0:
            raise RuntimeError(f"Transaction {txhash} failed after inclusion; inspect its result for fee disposition: " + committed.get("raw_log", "unknown failure"))
        return committed

    def wait_tx(self, txhash: str) -> dict:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            query = self.cli(["query", "tx", txhash, "--output", "json"], check=False)
            if query.returncode == 0:
                return json.loads(query.stdout)
            time.sleep(1)
        raise RuntimeError(f"Transaction outcome unknown: {txhash}. Query it before retrying.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "init", "start", "stop", "status", "verify", "sites", "admin-key"):
        sub.add_parser(command)
    explorer = sub.add_parser("explorer", help="Serve the read-only local block explorer")
    explorer.add_argument("--port", type=int, default=4173)
    for command in ("wallet", "address", "balance"):
        p = sub.add_parser(command)
        p.add_argument("name" if command != "balance" else "address")
    p = sub.add_parser("fund")
    p.add_argument("address")
    p.add_argument("amount", help="Amount in LUXAR, at most six decimals")
    p = sub.add_parser("send")
    p.add_argument("sender")
    p.add_argument("recipient")
    p.add_argument("amount", help="Amount in LUXAR, at most six decimals")
    args = parser.parse_args()
    network = Network()
    if args.command == "build":
        build()
    elif args.command == "sites":
        from sites import serve_sites
        serve_sites()
    elif args.command == "admin-key":
        from admin_auth import owner_access_key
        print(owner_access_key())
    elif args.command == "explorer":
        from explorer import serve
        serve(args.port)
    elif args.command == "verify":
        from verify import verify
        verify()
    elif args.command in ("init", "start", "stop"):
        getattr(network, args.command)()
        print(args.command + " complete")
    elif args.command == "status":
        print(json.dumps(network.rpc("status")["result"], indent=2))
    elif args.command in ("wallet", "address"):
        print(getattr(network, args.command)(args.name))
    elif args.command == "balance":
        print(json.dumps({"uluxar": str(network.balance(args.address))}))
    else:
        sender = "faucet" if args.command == "fund" else args.sender
        recipient = args.address if args.command == "fund" else args.recipient
        tx = network.send(sender, recipient, native_amount(args.amount))
        print(json.dumps({"txhash": tx["txhash"], "height": tx["height"], "fee_uluxar": str(FEE)}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Luxartium: {error}", file=sys.stderr)
        sys.exit(1)
