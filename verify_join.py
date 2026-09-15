"""Two-node sync on a disposable network; never changes the saved validator."""
import hashlib
import json
import time
import uuid

from localnet import LABEL, LABEL_VALUE, Network, ROOT, UNIT, run
from node import FullNode, expose_peer
from verify import available_ports, require


def verify():
    leader = Network("luxartium-check-" + uuid.uuid4().hex[:12], available_ports())
    follower = FullNode("luxartium-check-" + uuid.uuid4().hex[:12], available_ports())
    bridge = "luxartium-join-check-" + uuid.uuid4().hex[:12]
    bridge_created = False
    for node in (leader, follower):
        if node.inspect("container", node.name) or node.inspect("volume", node.volume):
            raise RuntimeError("Unexpected test-resource collision")
    try:
        leader.init()
        leader.start()
        leader_before = leader.rpc("status")["result"]
        original_genesis = leader.read_config("genesis.json")
        original_image = leader.require_owned("container", leader.name)["Image"]
        expose_peer(leader, "127.0.0.1", available_ports()[0])
        exposed = leader.require_owned("container", leader.name)
        require(exposed["Image"] == original_image and leader.read_config("genesis.json") == original_genesis
                and leader.rpc("status")["result"]["node_info"]["id"] == leader_before["node_info"]["id"],
                "enabling P2P preserves validator image, public identity and exact genesis")
        require(all(binding["HostIp"] == "127.0.0.1" for key, entries in exposed["HostConfig"]["PortBindings"].items()
                    if key != "26656/tcp" for binding in entries), "enabling P2P leaves query ports on loopback")
        run(["docker", "network", "create", "--label", f"{LABEL}={LABEL_VALUE}", bridge])
        bridge_created = True
        run(["docker", "network", "connect", bridge, leader.name])
        leader_id = leader.cli(["comet", "show-node-id"]).stdout.strip()
        genesis = leader.read_config("genesis.json").encode()
        digest = hashlib.sha256(genesis).hexdigest()
        follower.join(genesis, digest, [leader_id + "@" + leader.name + ":26656"])
        try:
            follower.join(genesis, digest, [leader_id + "@" + leader.name + ":26656"])
            raise AssertionError("A second join overwrote full-node state")
        except RuntimeError as error:
            require("already exists" in str(error), "join refuses existing full-node keys and history")
        follower.start(docker_network=bridge)
        follower.wait_height(leader.wait_height(3), timeout=120)
        first = follower.rpc("status")["result"]
        leader_status = leader.rpc("status")["result"]
        require(first["node_info"]["id"] != leader_id, "joining node has its own unique P2P identity")
        require(first["validator_info"]["address"] != leader_status["validator_info"]["address"] and first["validator_info"]["voting_power"] == "0",
                "joining full node has a different validator key and zero voting power")
        require(follower.read_config("genesis.json").encode() == genesis, "joining node uses the exact published genesis bytes")
        require(follower.rpc("genesis")["result"]["genesis"] == leader.rpc("genesis")["result"]["genesis"], "both nodes report the same genesis identity")
        address = leader.wallet("join-recipient")
        transfer = leader.send("faucet", address, 7 * UNIT)
        follower.wait_height(int(transfer["height"]) + 1, timeout=120)
        require(follower.balance(address) == 7 * UNIT, "follower independently serves the committed transfer balance")
        remembered = json.loads(follower.cli(["query", "tx", transfer["txhash"], "--output", "json"]).stdout)
        require(remembered["txhash"] == transfer["txhash"], "follower indexes the existing network transaction")
        height = int(transfer["height"])
        leader_block = leader.rpc("block?height=" + str(height))["result"]
        follower_block = follower.rpc("block?height=" + str(height))["result"]
        require(leader_block["block_id"]["hash"] == follower_block["block_id"]["hash"], "same-height blocks match on both nodes")
        follower.stop()
        follower.start(docker_network=bridge)
        follower.wait_height(height + 2, timeout=120)
        require(follower.balance(address) == 7 * UNIT and follower.rpc("status")["result"]["node_info"]["id"] == first["node_info"]["id"],
                "joined node retains its identity and synchronized balance after restart")
        evidence = {"result": "PASS", "leader": leader.name, "follower": follower.name, "genesis_sha256": digest,
                    "follower_node_id": first["node_info"]["id"], "follower_voting_power": "0",
                    "transaction_hash": transfer["txhash"], "matching_block_hash": leader_block["block_id"]["hash"]}
        (ROOT / "build").mkdir(exist_ok=True)
        (ROOT / "build/join-verification.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    finally:
        for node in (follower, leader):
            if node.inspect("container", node.name):
                node.require_owned("container", node.name)
                node.stop()
                run(["docker", "container", "rm", node.name])
            if node.inspect("volume", node.volume):
                node.require_owned("volume", node.volume)
                run(["docker", "volume", "rm", node.volume])
        if bridge_created:
            network = json.loads(run(["docker", "network", "inspect", bridge]).stdout)[0]
            if network.get("Labels", {}).get(LABEL) != LABEL_VALUE:
                raise RuntimeError("Refusing to remove unrelated Docker network")
            run(["docker", "network", "rm", bridge])
        require(all(node.inspect("container", node.name) is None and node.inspect("volume", node.volume) is None for node in (follower, leader)),
                "both disposable nodes and wallet volumes cleaned up")


if __name__ == "__main__":
    verify()
