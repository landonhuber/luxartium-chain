"""Reconcile only the two private beta sidecars; never initialize/restart a node.

Invoke periodically after Docker sign-in. Node restarts change network namespaces,
so both sidecars must be recreated against the current node before reads resume.
The operator process is privileged; the HTTP signing runtime has no Docker socket.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from admin_auth import assert_plain_path
from gateway import exclusive_process
from localnet import Network, run

LABEL = "org.luxartium.private-beta"
VALUE = "signer-v1"
SIGNER = "luxartium-beta-signer"
CONNECTOR = "luxartium-beta-tunnel"
VOLUME = "luxartium-beta-signer-state"
NODE_IMAGE = "sha256:bcf43413a0ea468c0fd6c48826e64cabe41366987d0a7e7fdbf406f6693ea272"
CONNECTOR_IMAGE = "cloudflare/cloudflared@sha256:b269e8abd07a5bf6f3f4be65d5050b2174eca89c56a0241a8ff32a16aec454e4"


def reconcile(config_path):
    config_path = config_path.resolve(strict=True)
    assert_plain_path(config_path.parent)
    assert_plain_path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if set(config) != {"signer_image", "genesis_hash", "tunnel_token_file"}:
        raise ValueError("Unsupported private signer configuration")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", config["signer_image"]) or not re.fullmatch(r"[a-f0-9]{64}", config["genesis_hash"]):
        raise ValueError("Pin the exact signer image and genesis")
    token = Path(config["tunnel_token_file"]).resolve(strict=True)
    if token.parent != config_path.parent:
        raise ValueError("Tunnel credential must remain in the private operator directory")
    assert_plain_path(token)
    network = Network()
    with exclusive_process(config_path.parent / "reconcile.lock"):
        node = network.require_owned("container", network.name)
        if node["Image"] != NODE_IMAGE or not node["State"]["Running"]:
            raise ValueError("Expected existing testnet node is not running")
        # No sidecar starts against an unavailable/wrong node.
        genesis = network.rpc("genesis")["result"]["genesis"]
        from gateway import canonical
        if hashlib.sha256(canonical(genesis).encode()).hexdigest() != config["genesis_hash"]:
            raise ValueError("Pinned genesis mismatch")
        volume = network.inspect("volume", VOLUME)
        if not volume or volume.get("Labels", {}).get(LABEL) != VALUE:
            raise ValueError("Existing isolated signer volume is required")
        existing = {}
        for name in (SIGNER, CONNECTOR):
            item = network.inspect("container", name)
            if item and item["Config"].get("Labels", {}).get(LABEL) != VALUE:
                raise ValueError("Refusing an unrelated sidecar container")
            existing[name] = item
        state_path = config_path.parent / "runtime.json"
        assert_plain_path(state_path)
        previous = json.loads(state_path.read_text()) if state_path.exists() else None
        stamp = {"node_id": node["Id"], "node_started_at": node["State"]["StartedAt"],
                 "configuration_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()}
        healthy = all(item and item["State"]["Running"] for item in existing.values())
        if previous == stamp and healthy:
            return "Private beta sidecars already match the running node."
        # Stop the connector first, then the signer; keep the durable volume intact.
        for name in (CONNECTOR, SIGNER):
            if existing[name]:
                run(["docker", "rm", "-f", name])
        common = ["--detach", "--restart", "unless-stopped", "--network", "container:" + node["Id"],
                  "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                  "--pids-limit", "64", "--label", LABEL + "=" + VALUE]
        run(["docker", "run", *common, "--name", SIGNER, "--memory", "256m", "--cpus", "1",
             "--mount", f"type=volume,source={VOLUME},target=/state", "--env", "LUXARTIUM_GENESIS_HASH=" + config["genesis_hash"],
             config["signer_image"]])
        run(["docker", "run", *common, "--name", CONNECTOR, "--memory", "128m", "--cpus", "0.5",
             "--mount", f"type=bind,source={token},target=/run/tunnel-token,readonly",
             CONNECTOR_IMAGE, "tunnel", "--no-autoupdate", "--metrics", "127.0.0.1:20242", "--loglevel", "warn",
             "run", "--token-file", "/run/tunnel-token"])
        state_path.write_text(json.dumps(stamp), encoding="utf-8")
        return "Private beta sidecars reattached; node and signer state preserved."


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(reconcile(args.config))
    except Exception:
        raise SystemExit("Private beta sidecars are not ready; inspect pinned configuration and Docker availability. No node initialization was attempted.")
