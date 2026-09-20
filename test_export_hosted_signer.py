"""Migration ordering checks using disposable files and synthetic wallet material."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch

import export_hosted_signer as exporter
from gateway import BetaSigner, BETA_TREASURY, exclusive_process
from test_beta_gateway import FixtureNetwork


class ExportOrderingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="luxartium-export-review-")
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name).resolve()
        self.output = self.source / "private-export"
        self.fence = self.source / "signing-moved.json"
        self.network = FixtureNetwork()
        for name in (BETA_TREASURY, "faucet", "foundry-pilot"):
            self.network.wallet(name)
        signer = BetaSigner(self.source, self.network)
        self.genesis = signer.fingerprint
        signer.db.execute("INSERT INTO beta_config VALUES (1, ?)", (self.network.address(BETA_TREASURY),))
        signer.db.commit()
        self.account = "00000000-0000-4000-8000-000000000123"
        signer.beta_provision({"account_id": self.account, "delivery_token": "D" * 43})
        signer.db.close()
        (self.source / "access.key").write_text("T" * 43, encoding="ascii")
        # ACL implementation is separately reviewed; this test never runs whoami/Docker.
        directory = patch.object(exporter, "private_directory", side_effect=lambda path: path.mkdir(mode=0o700))
        directory.start()
        self.addCleanup(directory.stop)
        subprocess_guard = patch("subprocess.run", side_effect=AssertionError("Real subprocess forbidden"))
        subprocess_guard.start()
        self.addCleanup(subprocess_guard.stop)

    def test_durable_fence_precedes_journal_backup_and_selective_key_export(self):
        events = []
        real_fsync, real_connect, real_cli = os.fsync, sqlite3.connect, self.network.cli
        test = self

        def observed_fsync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                events.append("directory_fsync")
            else:
                # Reading through another handle proves buffered marker bytes were flushed.
                test.assertEqual(json.loads(test.fence.read_text())["genesis_hash"], test.genesis)
                events.append("fence_fsync")
            return real_fsync(descriptor)

        class ObservedConnection(sqlite3.Connection):
            def backup(self, target, **kwargs):
                test.assertIn("fence_fsync", events)
                if os.name != "nt":
                    test.assertIn("directory_fsync", events)
                events.append("journal_backup")
                return super().backup(target, **kwargs)

        def observed_cli(args, **kwargs):
            test.assertIn("journal_backup", events)
            test.assertEqual(args[:2], ["keys", "export"])
            events.append("export:" + args[2])
            return real_cli(args, **kwargs)

        with ExitStack() as stack:
            stack.enter_context(patch.object(exporter.os, "fsync", side_effect=observed_fsync))
            stack.enter_context(patch.object(exporter.sqlite3, "connect",
                                             side_effect=lambda *args, **kwargs: real_connect(*args, factory=ObservedConnection, **kwargs)))
            stack.enter_context(patch.object(self.network, "cli", side_effect=observed_cli))
            report = exporter.export(self.source, self.output, self.genesis, self.network)

        expected = ["fence_fsync"] + (["directory_fsync"] if os.name != "nt" else [])
        expected += ["journal_backup", "export:" + BETA_TREASURY, "export:" + BetaSigner.key_name(self.account)]
        self.assertEqual(events, expected)
        self.assertTrue(report["source_fenced"])
        self.assertEqual(report["exported_keys"], 2)
        self.assertEqual([entry["name"] for entry in json.loads((self.output / "beta-keys.private.json").read_text())],
                         [BETA_TREASURY, BetaSigner.key_name(self.account)])
        with self.assertRaisesRegex(ValueError, "SIGNER_MIGRATED_USE_CURRENT_HOST"):
            BetaSigner(self.source, self.network)

    def test_failed_fence_flush_exports_nothing_and_keeps_source_fenced(self):
        with patch.object(exporter.os, "fsync", side_effect=OSError("synthetic flush failure")):
            with self.assertRaisesRegex(OSError, "synthetic flush failure"):
                exporter.export(self.source, self.output, self.genesis, self.network)
        self.assertTrue(self.fence.exists())
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.network.exports, 0)
        with self.assertRaisesRegex(ValueError, "SIGNER_MIGRATED_USE_CURRENT_HOST"):
            BetaSigner(self.source, self.network)

    def test_running_source_lock_prevents_export(self):
        with exclusive_process(self.source / "gateway.lock"):
            with self.assertRaises(OSError):
                exporter.export(self.source, self.output, self.genesis, self.network)
        self.assertFalse(self.fence.exists())
        self.assertFalse(self.output.exists())
        self.assertEqual(self.network.exports, 0)


if __name__ == "__main__":
    unittest.main()
