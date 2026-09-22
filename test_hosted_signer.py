"""Startup must never repair missing replay state or initialize a new treasury."""
import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import json
import uuid
from types import SimpleNamespace
import unittest
from gateway import BetaSigner, BETA_TREASURY
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


class PublicKeyringNetwork(FixtureNetwork):
    def __init__(self):
        super().__init__()
        self.list_calls = 0
        self.address_calls = 0
        self.transform = lambda rows: rows

    def wallet(self, name):
        address = "luxar1" + hashlib.sha256(name.encode()).hexdigest()[:38]
        self.addresses[name] = address
        self.balances[address] = 0
        return address

    def address(self, name):
        self.address_calls += 1
        return super().address(name)

    def cli(self, args, **kwargs):
        if args[:2] == ["keys", "list"]:
            self.list_calls += 1
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.transform([{"name": name, "address": address} for name, address in self.addresses.items()])))
        return super().cli(args, **kwargs)


class HostedKeyringScaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hosted-public-keyring-")
        self.directory = Path(self.temp.name)
        self.network = PublicKeyringNetwork()
        signer = BetaSigner(self.directory, self.network)
        self.genesis = signer.fingerprint
        treasury = self.network.wallet(BETA_TREASURY)
        signer.db.execute("INSERT INTO beta_config VALUES (1,?)", (treasury,))
        for _ in range(130):
            account = str(uuid.uuid4())
            address = self.network.wallet(signer.key_name(account))
            signer.db.execute("INSERT INTO beta_wallets VALUES (?,?,?,0,NULL)", (account, address, "0" * 64))
        signer.db.commit(); signer.db.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_keyring_check_uses_constant_public_cli_calls_and_keeps_orphans(self):
        self.network.wallet(BetaSigner.key_name(str(uuid.uuid4())))
        signer = HostedBetaSigner(self.directory, self.genesis, self.network)
        try:
            self.assertEqual(self.network.list_calls, 1)
            self.assertEqual(self.network.address_calls, 1)
            self.assertEqual(signer.db.execute("SELECT count(*) FROM beta_wallets").fetchone()[0], 130)
            self.assertEqual(self.network.exports, 0)
        finally:
            signer.db.close()

    def test_missing_and_wrong_saved_wallet_public_address_refuse(self):
        for transform in [lambda rows: rows[:-1], lambda rows: [{**row, "address": "luxar1" + "z" * 38} if i == 1 else row for i, row in enumerate(rows)]]:
            self.network.transform = transform
            with self.assertRaisesRegex(ValueError, "WALLET_IDENTITY_CHANGED"):
                HostedBetaSigner(self.directory, self.genesis, self.network)

    def test_malformed_or_ambiguous_keylist_refuses(self):
        changes = [(lambda rows: rows + [rows[1]], "AMBIGUOUS_SIGNER_KEY"),
                   (lambda rows: [{**row, "address": rows[0]["address"]} if i == 1 else row for i, row in enumerate(rows)], "AMBIGUOUS_SIGNER_KEY"),
                   (lambda rows: rows + [{"name": "faucet", "address": "luxar1" + "z" * 38}], "UNRELATED_KEY_IN_SIGNER"),
                   (lambda rows: rows + [None], "UNRELATED_KEY_IN_SIGNER"),
                   (lambda rows: rows + [{"name": 4, "address": None}], "UNRELATED_KEY_IN_SIGNER")]
        for transform, error in changes:
            with self.subTest(error=error):
                self.network.transform = transform
                with self.assertRaisesRegex(ValueError, error):
                    HostedBetaSigner(self.directory, self.genesis, self.network)

    def test_treasury_retains_independent_direct_identity_check(self):
        original = self.network.address
        self.network.address = lambda name: "changed" if name == BETA_TREASURY else original(name)
        with self.assertRaisesRegex(ValueError, "TREASURY_IDENTITY_CHANGED"):
            HostedBetaSigner(self.directory, self.genesis, self.network)


if __name__ == "__main__":
    unittest.main()
