"""Startup must never repair missing replay state or initialize a new treasury."""
import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from gateway import BetaSigner
from hosted_signer import HostedBetaSigner, REQUIRED_TABLES
from test_beta_gateway import FixtureNetwork


class HostedStartupTests(unittest.TestCase):
    def test_missing_replay_tables_refuse_without_repair(self):
        for missing in REQUIRED_TABLES:
            with self.subTest(table=missing), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                signer = BetaSigner(directory, FixtureNetwork())
                fingerprint = signer.fingerprint
                signer.db.close()
                path = directory / "settlements.sqlite"
                with closing(sqlite3.connect(path)) as database:
                    database.execute(f"DROP TABLE {missing}")
                    database.commit()
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError, "SIGNER_JOURNAL_INCOMPLETE"):
                    HostedBetaSigner(directory, fingerprint, FixtureNetwork())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
                with closing(sqlite3.connect(path)) as database:
                    self.assertIsNone(database.execute("SELECT name FROM sqlite_master WHERE name=?", (missing,)).fetchone())

    def test_missing_file_stays_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(ValueError, "EXISTING_SIGNER_STATE_REQUIRED"):
                HostedBetaSigner(directory, "a" * 64, FixtureNetwork())
            self.assertFalse((directory / "settlements.sqlite").exists())

    def test_malformed_replay_schema_refuses_without_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            signer = BetaSigner(directory, FixtureNetwork())
            fingerprint = signer.fingerprint
            signer.db.close()
            path = directory / "settlements.sqlite"
            with closing(sqlite3.connect(path)) as database:
                database.execute("DROP TABLE beta_intents")
                database.execute("CREATE TABLE beta_intents (operation TEXT PRIMARY KEY)")
                database.commit()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(sqlite3.OperationalError):
                HostedBetaSigner(directory, fingerprint, FixtureNetwork())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
