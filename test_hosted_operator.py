"""Exercise private sidecar reconciliation without Docker, RPC or saved state."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gateway import canonical
import hosted_operator as operator
from localnet import LABEL, LABEL_VALUE, Network


class HostedOperatorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="luxartium-operator-review-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.token = self.directory / "tunnel.token"
        self.token.write_text("SYNTHETIC-TEST-ONLY-NOT-A-CREDENTIAL", encoding="utf-8")
        self.genesis = {"chain_id": "luxartium-local-1", "app_state": {"fixture": True}}
        self.config = {
            "signer_image": "sha256:" + "a" * 64,
            "genesis_hash": hashlib.sha256(canonical(self.genesis).encode()).hexdigest(),
            "tunnel_token_file": str(self.token),
        }
        self.config_path = self.directory / "config.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.state_path = self.directory / "runtime.json"
        self.network = Network()
        self.node = {
            "Id": "b" * 64,
            "Image": operator.NODE_IMAGE,
            "Config": {"Labels": {LABEL: LABEL_VALUE}},
            "State": {"Running": True, "StartedAt": "2026-09-20T01:00:00Z"},
        }
        self.volume = {"Name": operator.VOLUME, "Labels": {operator.LABEL: operator.VALUE}}
        self.objects = {
            ("container", self.network.name): self.node,
            ("volume", operator.VOLUME): self.volume,
        }
        for name in (operator.SIGNER, operator.CONNECTOR):
            self.objects[("container", name)] = {
                "Config": {"Labels": {operator.LABEL: operator.VALUE}},
                "State": {"Running": True},
            }
        # Keep the actual require_owned implementation, with only external I/O mocked.
        self.network.inspect = Mock(side_effect=lambda kind, name: self.objects.get((kind, name)))
        self.network.rpc = Mock(return_value={"result": {"genesis": self.genesis}})
        factory = patch.object(operator, "Network", return_value=self.network)
        factory.start()
        self.addCleanup(factory.stop)
        commands = patch.object(operator, "run", return_value=None)
        self.run = commands.start()
        self.addCleanup(commands.stop)
        # An accidental path around these mocks must fail instead of invoking Docker.
        subprocess_guard = patch("subprocess.run", side_effect=AssertionError("Real subprocess forbidden"))
        subprocess_guard.start()
        self.addCleanup(subprocess_guard.stop)

    def stamp(self):
        return {
            "node_id": self.node["Id"],
            "node_started_at": self.node["State"]["StartedAt"],
            "configuration_sha256": hashlib.sha256(self.config_path.read_bytes()).hexdigest(),
        }

    def save_stamp(self):
        self.state_path.write_text(json.dumps(self.stamp()), encoding="utf-8")

    def commands(self):
        return [call.args[0] for call in self.run.call_args_list]

    def assert_isolated_starts(self, commands):
        self.assertEqual(len(commands), 2)
        for command, name in zip(commands, (operator.SIGNER, operator.CONNECTOR)):
            self.assertEqual(command[:2], ["docker", "run"])
            self.assertEqual(command[command.index("--name") + 1], name)
            self.assertEqual(command[command.index("--network") + 1], "container:" + self.node["Id"])
            self.assertIn("--read-only", command)
            self.assertEqual(command[command.index("--cap-drop") + 1], "ALL")
            self.assertEqual(command[command.index("--security-opt") + 1], "no-new-privileges")
            self.assertEqual(command[command.index("--label") + 1], operator.LABEL + "=" + operator.VALUE)
            self.assertNotIn("--privileged", command)
            self.assertNotIn("--publish", command)
            self.assertNotIn("-p", command)
            self.assertNotIn("docker.sock", " ".join(command))
            self.assertNotIn(self.network.volume, " ".join(command))
        signer, connector = commands
        self.assertEqual(signer.count("--mount"), 1)
        self.assertEqual(signer[signer.index("--mount") + 1],
                         f"type=volume,source={operator.VOLUME},target=/state")
        self.assertEqual(signer[-1], self.config["signer_image"])
        self.assertEqual(signer[signer.index("--env") + 1],
                         "LUXARTIUM_GENESIS_HASH=" + self.config["genesis_hash"])
        self.assertEqual(connector.count("--mount"), 1)
        self.assertEqual(connector[connector.index("--mount") + 1],
                         f"type=bind,source={self.token},target=/run/tunnel-token,readonly")
        self.assertIn(operator.CONNECTOR_IMAGE, connector)
        self.assertEqual(connector[-2:], ["--token-file", "/run/tunnel-token"])
        self.assertNotIn(self.token.read_text(), " ".join(connector))

    def test_healthy_same_generation_is_a_noop(self):
        self.save_stamp()
        before = self.state_path.read_bytes()
        original = deepcopy(self.objects)
        self.assertIn("already match", operator.reconcile(self.config_path))
        self.run.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(self.objects, original)
        self.network.rpc.assert_called_once_with("genesis")

    def test_unrelated_sidecar_refuses_before_any_mutation(self):
        self.save_stamp()
        before = self.state_path.read_bytes()
        for name in (operator.SIGNER, operator.CONNECTOR):
            with self.subTest(name=name):
                labels = self.objects[("container", name)]["Config"]["Labels"]
                labels[operator.LABEL] = "another-owner"
                with self.assertRaisesRegex(ValueError, "unrelated sidecar"):
                    operator.reconcile(self.config_path)
                self.run.assert_not_called()
                self.assertEqual(self.state_path.read_bytes(), before)
                labels[operator.LABEL] = operator.VALUE

    def test_unrelated_or_missing_volume_is_never_created_or_replaced(self):
        self.save_stamp()
        before = self.state_path.read_bytes()
        for volume in (None, {"Labels": {operator.LABEL: "another-owner"}}, {"Labels": {}}):
            with self.subTest(volume=volume):
                self.objects[("volume", operator.VOLUME)] = volume
                with self.assertRaisesRegex(ValueError, "isolated signer volume"):
                    operator.reconcile(self.config_path)
                self.run.assert_not_called()
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_unrelated_or_missing_node_is_never_started(self):
        for node in (None, {"Config": {"Labels": {LABEL: "another-owner"}}}):
            with self.subTest(node=node):
                self.objects[("container", self.network.name)] = node
                with self.assertRaisesRegex(RuntimeError, "absent or unrelated"):
                    operator.reconcile(self.config_path)
                self.run.assert_not_called()
                self.assertFalse(self.state_path.exists())

    def test_wrong_image_stopped_node_or_wrong_genesis_refuses(self):
        original = deepcopy(self.node)
        for failure in ("image", "stopped", "genesis"):
            with self.subTest(failure=failure):
                self.node.clear()
                self.node.update(deepcopy(original))
                self.network.rpc.return_value = {"result": {"genesis": self.genesis}}
                if failure == "image":
                    self.node["Image"] = "sha256:" + "c" * 64
                elif failure == "stopped":
                    self.node["State"]["Running"] = False
                else:
                    self.network.rpc.return_value = {"result": {"genesis": {"chain_id": "unrelated"}}}
                with self.assertRaises(ValueError):
                    operator.reconcile(self.config_path)
                self.run.assert_not_called()
                self.assertFalse(self.state_path.exists())

    def test_restart_or_replacement_reattaches_only_sidecars_and_keeps_volume(self):
        for changed in ("started_at", "node_id"):
            with self.subTest(changed=changed):
                self.save_stamp()
                if changed == "started_at":
                    self.node["State"]["StartedAt"] = "2026-09-20T02:00:00Z"
                else:
                    self.node["Id"] = "d" * 64
                original = deepcopy(self.objects)
                self.run.reset_mock()
                self.assertIn("reattached", operator.reconcile(self.config_path))
                commands = self.commands()
                self.assertEqual(commands[:2], [
                    ["docker", "rm", "-f", operator.CONNECTOR],
                    ["docker", "rm", "-f", operator.SIGNER],
                ])
                self.assert_isolated_starts(commands[2:])
                self.assertEqual(self.objects, original)
                self.assertEqual(json.loads(self.state_path.read_text()), self.stamp())

    def test_missing_sidecar_recreates_pair_without_removing_absent_container(self):
        self.save_stamp()
        del self.objects[("container", operator.CONNECTOR)]
        original = deepcopy(self.objects)
        operator.reconcile(self.config_path)
        commands = self.commands()
        self.assertEqual(commands[0], ["docker", "rm", "-f", operator.SIGNER])
        self.assert_isolated_starts(commands[1:])
        self.assertEqual(self.objects, original)

    def test_stopped_sidecar_recreates_pair_even_when_generation_matches(self):
        self.save_stamp()
        self.objects[("container", operator.SIGNER)]["State"]["Running"] = False
        operator.reconcile(self.config_path)
        commands = self.commands()
        self.assertEqual(commands[:2], [
            ["docker", "rm", "-f", operator.CONNECTOR],
            ["docker", "rm", "-f", operator.SIGNER],
        ])
        self.assert_isolated_starts(commands[2:])

    def test_partial_start_failure_does_not_commit_generation_and_can_retry(self):
        self.save_stamp()
        before = self.state_path.read_bytes()
        self.node["State"]["StartedAt"] = "2026-09-20T03:00:00Z"
        self.run.side_effect = [None, None, None, RuntimeError("synthetic connector start failure")]
        with self.assertRaisesRegex(RuntimeError, "synthetic connector"):
            operator.reconcile(self.config_path)
        self.assertEqual(self.state_path.read_bytes(), before)
        # Model Docker's partial result: signer exists, connector creation failed.
        del self.objects[("container", operator.CONNECTOR)]
        self.run.reset_mock(side_effect=True)
        operator.reconcile(self.config_path)
        commands = self.commands()
        self.assertEqual(commands[0], ["docker", "rm", "-f", operator.SIGNER])
        self.assert_isolated_starts(commands[1:])
        self.assertEqual(json.loads(self.state_path.read_text()), self.stamp())

    def test_missing_runtime_cache_safely_recreates_owned_sidecars(self):
        self.assertFalse(self.state_path.exists())
        operator.reconcile(self.config_path)
        commands = self.commands()
        self.assertEqual(commands[:2], [
            ["docker", "rm", "-f", operator.CONNECTOR],
            ["docker", "rm", "-f", operator.SIGNER],
        ])
        self.assert_isolated_starts(commands[2:])
        self.assertEqual(json.loads(self.state_path.read_text()), self.stamp())

    def test_truncated_runtime_cache_refuses_without_touching_running_sidecars(self):
        self.state_path.write_text('{"node_id":', encoding="utf-8")
        before = self.state_path.read_bytes()
        with self.assertRaises(json.JSONDecodeError):
            operator.reconcile(self.config_path)
        self.run.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
