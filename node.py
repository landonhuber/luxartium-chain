#!/usr/bin/env python3
"""Join the existing Luxartium testnet as a full node; never clone validator keys."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid
import urllib.parse
import urllib.request

from localnet import CHAIN_ID, DENOM, IMAGE, LABEL, LABEL_VALUE, Network, SUPPLY, run

MAX_GENESIS_BYTES = 16 * 1024 * 1024
MAX_NETWORK_BYTES = 16 * 1024


def public_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        raise ValueError("Use an HTTPS public URL without credentials or a fragment")
    local = parsed.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("Remote downloads require HTTPS; HTTP is allowed only on loopback")
    return value


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_document(source: str, limit: int) -> bytes:
    if source.startswith(("https://", "http://")):
        opener = urllib.request.build_opener(PublicRedirect())
        request = urllib.request.Request(public_url(source), headers={"User-Agent": "LuxartiumNode/0.1 (+https://luxartium.org)", "Accept": "application/json"})
        with opener.open(request, timeout=30) as response:
            raw = response.read(limit + 1)
    else:
        with Path(source).open("rb") as handle:
            raw = handle.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("Public network document is empty or exceeds its size limit")
    return raw


def peer_address(value: str) -> str:
    match = re.fullmatch(r"([a-f0-9]{40})@([a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?):([0-9]{1,5})", value)
    if not match or not 1 <= int(match[3]) <= 65535 or ".." in match[2]:
        raise ValueError("A peer must be its 40-character node ID followed by @host:port")
    return value


def validate_genesis(raw: bytes, expected_sha256: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("The expected genesis SHA-256 must be 64 lowercase hexadecimal characters")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Downloaded genesis does not match its published SHA-256")
    genesis = json.loads(raw)
    if not isinstance(genesis, dict) or genesis.get("chain_id") != CHAIN_ID:
        raise ValueError("Genesis is not for the Luxartium testnet")
    state = genesis.get("app_state", {})
    if not isinstance(state, dict) or "mint" in state or state.get("staking", {}).get("params", {}).get("bond_denom") != DENOM:
        raise ValueError("Genesis has unexpected native denomination or mint configuration")
    bank = state.get("bank", {})
    supply = sum(int(coin["amount"]) for row in bank.get("balances", []) for coin in row.get("coins", []) if coin["denom"] == DENOM)
    if supply != SUPPLY:
        raise ValueError("Genesis must begin with exactly one billion LUXAR")
    return genesis


def resolve_network(source: str) -> tuple[bytes, str, list[str]]:
    document = json.loads(read_document(source, MAX_NETWORK_BYTES))
    if not isinstance(document, dict) or document.get("format_version") != 1 or document.get("chain_id") != CHAIN_ID:
        raise ValueError("Unsupported Luxartium testnet network manifest")
    peers = document.get("persistent_peers")
    if not isinstance(peers, list) or not 1 <= len(peers) <= 8 or not all(isinstance(peer, str) for peer in peers):
        raise ValueError("The network manifest must publish one to eight persistent peers")
    peers = [peer_address(peer) for peer in peers]
    genesis_url = document.get("genesis_url")
    if not isinstance(genesis_url, str):
        raise ValueError("The network manifest must publish its genesis URL")
    raw = read_document(public_url(genesis_url), MAX_GENESIS_BYTES)
    digest = document.get("genesis_sha256")
    if not isinstance(digest, str):
        raise ValueError("The network manifest must publish its genesis SHA-256")
    validate_genesis(raw, digest)
    return raw, digest, peers


class FullNode(Network):
    def __init__(self, name="luxartium-full-1", ports=(26667, 1327, 9091)):
        if name != "luxartium-full-1" and not re.fullmatch(r"luxartium-check-[a-f0-9]{12}", name):
            raise ValueError("Full-node commands may not operate on the saved validator")
        if len(set(ports)) != 3 or any(not 1024 <= port <= 65535 for port in ports):
            raise ValueError("Choose three distinct local ports between 1024 and 65535")
        super().__init__(name, ports)

    def join(self, raw: bytes, digest: str, peers: list[str]) -> None:
        validate_genesis(raw, digest)
        if not 1 <= len(peers) <= 8:
            raise ValueError("Choose one to eight persistent peers")
        peers = [peer_address(peer) for peer in peers]
        self.require_image()
        if self.inspect("volume", self.volume) or self.inspect("container", self.name):
            raise RuntimeError("Full-node state already exists. Join never overwrites keys or history; use start.")
        run(["docker", "volume", "create", "--label", f"{LABEL}={LABEL_VALUE}", self.volume])
        self.offline(["-c", "chmod 700 /chain"], entrypoint="sh")
        # SDK init generates independent node/validator keys. No faucet wallets,
        # genesis validators, account grants or gentxs are created for a follower.
        self.offline(["init", "full-node", "--chain-id", CHAIN_ID, "--default-denom", DENOM, "--home", "/chain"])
        self.write_config("genesis.json", raw.decode("utf-8"))
        config = self.read_config("config.toml")
        for key, value in (("persistent_peers", '"' + ",".join(peers) + '"'), ("addr_book_strict", "false"), ("pex", "false")):
            config, count = re.subn(r"(?m)^" + key + r" = .*?$", key + " = " + value, config)
            if count != 1:
                raise RuntimeError("Unexpected node configuration layout; join stopped without starting a node")
        self.write_config("config.toml", config)
        self.offline(["genesis", "validate-genesis", "--home", "/chain"])
        print(f"Joined configuration for {self.name}; run start to synchronize existing testnet history.", flush=True)

    def start(self, *, docker_network: str | None = None) -> None:
        self.require_image()
        self.require_owned("volume", self.volume)
        existing = self.inspect("container", self.name)
        if existing:
            self.require_owned("container", self.name)
            if existing["Image"] != self.inspect("image", IMAGE)["Id"]:
                raise RuntimeError("Existing full node uses a different image; a reviewed upgrade is required")
            run(["docker", "start", self.name])
        else:
            rpc, api, grpc = self.ports
            args = ["docker", "run", "-d", "--name", self.name, "--label", f"{LABEL}={LABEL_VALUE}",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                    "--tmpfs", "/tmp:rw,nosuid,size=64m", "--memory", "2g", "--cpus", "2", "-e", "GOMAXPROCS=2",
                    "--mount", f"type=volume,source={self.volume},target=/chain",
                    "-p", f"127.0.0.1:{rpc}:26657", "-p", f"127.0.0.1:{api}:1317", "-p", f"127.0.0.1:{grpc}:9090"]
            if docker_network:
                # Used by the disposable two-node acceptance network.
                args += ["--network", docker_network]
            run(args + [IMAGE, "start", "--home", "/chain", "--rpc.laddr", "tcp://0.0.0.0:26657",
                        "--api.address", "tcp://0.0.0.0:1317", "--grpc.address", "0.0.0.0:9090", "--log_level", "warn"])
        print(f"Full node running. Local RPC: http://127.0.0.1:{self.ports[0]}/status; initial sync may take time.", flush=True)


def export_network(network: Network, output: Path, peer_host: str, base_url: str) -> None:
    base_url = public_url(base_url).rstrip("/")
    node_id = network.cli(["comet", "show-node-id"]).stdout.strip()
    peer = peer_address(node_id + "@" + peer_host)
    raw = network.read_config("genesis.json").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    validate_genesis(raw, digest)
    rpc_genesis = network.rpc("genesis")["result"]["genesis"]
    fingerprint = hashlib.sha256(json.dumps(rpc_genesis, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    document = {"format_version": 1, "network": "Luxartium Testnet", "chain_id": CHAIN_ID,
                "genesis_url": base_url + "/genesis.json", "genesis_sha256": digest,
                "genesis_fingerprint": fingerprint, "persistent_peers": [peer],
                "currency": "LUXAR", "decimals": 6, "genesis_supply_uluxar": str(SUPPLY)}
    output.mkdir(parents=True, exist_ok=True)
    # Exclusive creation refuses to silently replace previously published genesis.
    with (output / "genesis.json").open("xb") as handle:
        handle.write(raw)
    with (output / "network.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=2) + "\n")
    print("Exported public genesis and network manifest; no private keys were read or copied.", flush=True)
    print("Genesis file SHA-256: " + digest, flush=True)


def expose_peer(network: Network, host: str, port: int) -> None:
    """Recreate only the container, preserving its exact image and chain volume."""
    ipaddress.IPv4Address(host)
    if not 1024 <= port <= 65535:
        raise ValueError("Choose a P2P port between 1024 and 65535")
    current = network.require_owned("container", network.name)
    network.require_owned("volume", network.volume)
    if not current["State"]["Running"]:
        raise RuntimeError("Start the existing validator before enabling peer access")
    mounts = current.get("Mounts", [])
    if len(mounts) != 1 or mounts[0].get("Name") != network.volume or mounts[0].get("Destination") != "/chain":
        raise RuntimeError("Unexpected container mounts; refusing automatic recreation")
    bindings = current["HostConfig"]["PortBindings"]
    existing = bindings.get("26656/tcp")
    if existing:
        if existing == [{"HostIp": host, "HostPort": str(port)}]:
            print("Peer port already has this binding; no container changed.", flush=True)
            return
        raise RuntimeError("A different P2P binding already exists; review it before changing exposure")
    expected = {f"{internal}/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(external)}]
                for internal, external in zip((26657, 1317, 9090), network.ports)}
    if bindings != expected or current["Config"]["Entrypoint"] != ["luxartiumd"]:
        raise RuntimeError("Unexpected query-port or entrypoint configuration; refusing automatic recreation")
    expected_command = ["start", "--home", "/chain", "--rpc.laddr", "tcp://0.0.0.0:26657",
                        "--api.address", "tcp://0.0.0.0:1317", "--grpc.address", "0.0.0.0:9090", "--log_level", "warn"]
    if current["Config"]["Cmd"] != expected_command or current["HostConfig"]["NetworkMode"] not in ("default", "bridge"):
        raise RuntimeError("Custom node command or network detected; review that setup manually")
    image_id = exact_runtime_image(network, current)
    before_height = network.wait_height(1)
    backup = network.name + "-peer-backup-" + uuid.uuid4().hex[:8]
    network.stop()
    run(["docker", "rename", network.name, backup])
    created_id = None
    try:
        rpc, api, grpc = network.ports
        created_id = run(["docker", "create", "--name", network.name, "--label", f"{LABEL}={LABEL_VALUE}",
                         "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                         "--tmpfs", "/tmp:rw,nosuid,size=64m", "--memory", "2g", "--cpus", "2", "-e", "GOMAXPROCS=2",
                         "--mount", f"type=volume,source={network.volume},target=/chain",
                         "-p", f"127.0.0.1:{rpc}:26657", "-p", f"127.0.0.1:{api}:1317", "-p", f"127.0.0.1:{grpc}:9090",
                         "-p", f"{host}:{port}:26656", image_id, *expected_command,
                         "--p2p.laddr", "tcp://0.0.0.0:26656"]).stdout.strip()
        run(["docker", "start", network.name])
        network.wait_height(before_height + 1)
    except Exception:
        if created_id:
            created = network.require_owned("container", network.name)
            if created["Id"] != created_id:
                raise RuntimeError("Container identity changed during peer exposure; automatic rollback stopped")
            run(["docker", "stop", "--time", "30", network.name])
            run(["docker", "container", "rm", network.name])
        original = network.require_owned("container", backup)
        if original["Id"] != current["Id"]:
            raise RuntimeError("Backup container identity changed; automatic rollback stopped")
        run(["docker", "rename", backup, network.name])
        run(["docker", "start", network.name])
        raise
    original = network.require_owned("container", backup)
    if original["Id"] != current["Id"]:
        raise RuntimeError("Backup container identity changed; leaving it stopped for inspection")
    run(["docker", "container", "rm", backup])
    print(f"P2P enabled at {host}:{port}; saved image, volume and identities retained. Query ports remain loopback-only.", flush=True)


def exact_runtime_image(network: Network, current: dict) -> str:
    """Allow refreshed build attestations only when the actual platform image is identical."""
    network.require_image()
    available = network.inspect("image", IMAGE)
    if current["Image"] == available["Id"]:
        return available["Id"]
    old_manifest = (current.get("ImageManifestDescriptor") or {}).get("digest")
    if not old_manifest:
        raise RuntimeError("Saved image differs and its platform manifest cannot be verified")
    # Docker's containerd image store can replace an index containing unchanged
    # platform bytes when only build-provenance metadata changes. Create, never
    # start, an unmounted probe to learn the selected platform manifest.
    name = "luxartium-image-check-" + uuid.uuid4().hex[:12]
    probe_id = run(["docker", "create", "--name", name, "--label", f"{LABEL}={LABEL_VALUE}",
                    "--network", "none", "--read-only", "--cap-drop", "ALL", available["Id"], "version"]).stdout.strip()
    try:
        probe = network.require_owned("container", name)
        if probe["Id"] != probe_id or (probe.get("ImageManifestDescriptor") or {}).get("digest") != old_manifest:
            raise RuntimeError("Protocol/runtime image differs; a reviewed upgrade is required")
        return available["Id"]
    finally:
        probe = network.require_owned("container", name)
        if probe["Id"] == probe_id:
            run(["docker", "container", "rm", name])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-port", type=int, default=26667)
    parser.add_argument("--rest-port", type=int, default=1327)
    parser.add_argument("--grpc-port", type=int, default=9091)
    sub = parser.add_subparsers(dest="command", required=True)
    join = sub.add_parser("join", help="Initialize a unique full node using the existing public genesis")
    source = join.add_mutually_exclusive_group(required=True)
    source.add_argument("--network", help="HTTPS network manifest URL or local manifest file")
    source.add_argument("--genesis", help="Genesis file path or HTTPS URL (advanced)")
    join.add_argument("--genesis-sha256")
    join.add_argument("--peer", action="append", default=[])
    for command in ("start", "stop", "status"):
        sub.add_parser(command)
    export = sub.add_parser("export", help="Export only public saved-validator genesis and node ID")
    export.add_argument("--peer-host", required=True, help="Reachable hostname or IPv4 plus :26656")
    export.add_argument("--public-base-url", required=True, help="HTTPS folder where genesis.json will be hosted")
    export.add_argument("--output", required=True, type=Path)
    expose = sub.add_parser("expose-peer", help="Enable saved-validator P2P only, preserving its image and chain volume")
    expose.add_argument("--host", required=True, help="Explicit IPv4 interface to bind (for example a LAN address)")
    expose.add_argument("--port", type=int, default=26656)
    args = parser.parse_args()
    if args.command == "export":
        export_network(Network(), args.output, args.peer_host, args.public_base_url)
        return
    if args.command == "expose-peer":
        expose_peer(Network(), args.host, args.port)
        return
    node = FullNode(ports=(args.rpc_port, args.rest_port, args.grpc_port))
    if args.command == "join":
        if args.network:
            if args.genesis_sha256 or args.peer:
                parser.error("--network supplies its own genesis checksum and peers")
            raw, digest, peers = resolve_network(args.network)
        else:
            if not args.genesis_sha256 or not args.peer:
                parser.error("--genesis requires --genesis-sha256 and at least one --peer")
            raw, digest, peers = read_document(args.genesis, MAX_GENESIS_BYTES), args.genesis_sha256, args.peer
        node.join(raw, digest, peers)
    elif args.command == "status":
        status = node.rpc("status")["result"]
        print(json.dumps({"chain_id": status["node_info"]["network"], "node_id": status["node_info"]["id"],
                          "sync": status["sync_info"], "voting_power": status["validator_info"]["voting_power"]}, indent=2))
    else:
        getattr(node, args.command)()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print("Luxartium full node: " + str(error), file=sys.stderr)
        sys.exit(1)
