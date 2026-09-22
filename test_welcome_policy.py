"""Bounded synthetic policy, concurrency, recovery and zero-enrollment tests."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import uuid
import unittest

from gateway import BETA_TREASURY, canonical
from test_beta_gateway import GatewayFixture, FixtureSigner, DELIVERY
from welcome_policy import CAMPAIGN, LEGACY, amount_for, activate, initialize
from activate_welcome_policy import run as activate_file


def new_id():
    return str(uuid.uuid4())


class WelcomePolicyTests(GatewayFixture):
    def start_policy(self, rows=()):
        value = {"version": 1, "policy_id": CAMPAIGN, "genesis_hash": self.signer.fingerprint,
                 "legacy_profiles": sorted(rows, key=lambda row: row["agent_id"])}
        digest = hashlib.sha256(canonical(value).encode()).hexdigest()
        result = activate(self.signer.db, value, digest, self.signer.fingerprint)
        self.signer.welcome_campaign = initialize(self.signer.db, self.signer.fingerprint)
        return value, digest, result

    def provision(self, ordinal="1", agent=None, account=None, operation=None, policy=CAMPAIGN):
        account = account or new_id()
        auth = {"agent_id": agent or new_id(), "operation_id": operation or new_id(), "policy_id": policy,
                "ordinal": ordinal, "amount_uluxar": amount_for(ordinal) if policy == CAMPAIGN else "500000000"}
        body = {"account_id": account, "delivery_token": DELIVERY, "welcome_grant": auth}
        self.signer.beta_provision(body)
        return body

    def transfer(self, enrollment):
        auth = enrollment["welcome_grant"]
        body = {"operation_id": auth["operation_id"], "kind": "grant", "from_account_id": None,
                "to_account_id": enrollment["account_id"], "amount_uluxar": auth["amount_uluxar"],
                "reference_hash": "a" * 64, "reverses_operation_id": None, "genesis_hash": self.signer.fingerprint}
        if auth["policy_id"] == CAMPAIGN:
            body["grant_authorization"] = {key: auth[key] for key in ("policy_id", "ordinal", "amount_uluxar")}
        return body

    def restart(self):
        self.signer.db.close()
        self.signer = FixtureSigner(self.directory, self.network, clock=lambda: self.now)

    def test_exact_tiers_and_budget(self):
        for ordinal, expected in [(1, 500), (1000, 500), (1001, 400), (2000, 400), (2001, 300), (3000, 300),
                                  (3001, 200), (4000, 200), (4001, 100), (5000, 100), (5001, 0), (9007199254740991, 0)]:
            self.assertEqual(amount_for(str(ordinal)), str(expected * 1_000_000))
        self.assertEqual(sum(int(amount_for(str(n))) for n in range(1, 5001)), 1_500_000_000_000)
        for value in [0, True, "0", "01", "-1", "1.2", "1e3", "9007199254740992", "1" * 50, None]:
            with self.assertRaisesRegex(ValueError, "INVALID_WELCOME_ORDINAL"):
                amount_for(value)

    def test_explicit_activation_and_no_flat_fallback(self):
        with self.assertRaisesRegex(ValueError, "NOT_ACTIVE"):
            self.provision()
        self.start_policy()
        with self.assertRaisesRegex(ValueError, "ALLOCATION_REQUIRED"):
            self.signer.beta_provision({"account_id": new_id(), "delivery_token": DELIVERY})
        with self.assertRaisesRegex(ValueError, "WALLET_NOT_FOUND"):
            self.signer.beta_enroll({"account_id": new_id(), "delivery_token": DELIVERY, "acknowledge": False})
        row = self.provision("1001")
        transfer = self.transfer(row)
        with self.assertRaisesRegex(ValueError, "AUTHORIZATION_REQUIRED"):
            self.signer.beta_operation({key: value for key, value in transfer.items() if key != "grant_authorization"})
        with self.assertRaisesRegex(ValueError, "ALLOCATION_CONFLICT"):
            self.signer.beta_operation({**transfer, "amount_uluxar": "500000000"})
        self.assertEqual(self.network.signatures, 0)

    def test_all_positive_tiers_replay_exact_signed_bytes_after_restart(self):
        self.start_policy()
        for ordinal in ("1", "1001", "2001", "3001", "4001"):
            row = self.provision(ordinal)
            body = self.transfer(row)
            self.network.lose_response = True
            first = self.signer.beta_operation(body)
            signature_count = self.network.signatures
            saved = self.signer.db.execute("SELECT signed FROM operations WHERE id=?", (body["operation_id"],)).fetchone()[0]
            self.restart()
            second = self.signer.beta_operation(body)
            self.assertEqual(first["transaction_hash"], second["transaction_hash"])
            self.assertEqual(self.network.signatures, signature_count)
            self.assertEqual(saved, self.signer.db.execute("SELECT signed FROM operations WHERE id=?", (body["operation_id"],)).fetchone()[0])
            self.network.commit()
            settled = self.signer.beta_operation(body)
            self.assertEqual(settled["state"], "committed")
            self.assertEqual(settled["amount_uluxar"], amount_for(ordinal))
            self.assertEqual(self.signer.beta_operation(body), settled)
            with self.assertRaisesRegex(ValueError, "IDEMPOTENCY_CONFLICT"):
                self.signer.beta_operation({**body, "reference_hash": "b" * 64})

    def test_zero_entitlement_delivers_keys_without_transfer(self):
        self.start_policy()
        row = self.provision("5001")
        self.restart()
        request = {key: row[key] for key in ("account_id", "delivery_token")}
        first = self.signer.beta_enroll({**request, "acknowledge": False})
        self.assertEqual(first["balance_uluxar"], "0")
        self.assertEqual(len(first["private_key_hex"]), 64)
        self.assertEqual(self.signer.beta_enroll({**request, "acknowledge": False})["private_key_hex"], first["private_key_hex"])
        self.signer.beta_enroll({**request, "acknowledge": True})
        self.assertNotIn("private_key_hex", self.signer.beta_enroll({**request, "acknowledge": False}))
        with self.assertRaisesRegex(ValueError, "INVALID_AMOUNT"):
            self.signer.beta_operation(self.transfer(row))
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM operations").fetchone()[0], 0)
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM beta_grants").fetchone()[0], 0)
        self.assertEqual(self.network.signatures, 0)

    def test_existing_grant_and_old_profile_without_wallet_keep_flat_eligibility(self):
        old_agent, future_agent, operation = new_id(), new_id(), new_id()
        self.signer.beta_provision({"account_id": self.account, "delivery_token": DELIVERY})
        old = {"account_id": self.account, "welcome_grant": {"operation_id": operation, "policy_id": LEGACY, "ordinal": None, "amount_uluxar": "500000000"}}
        body = self.transfer(old)
        self.signer.beta_operation(body); self.network.commit(); receipt = self.signer.beta_operation(body)
        self.start_policy([{"agent_id": old_agent, "account_id": self.account, "operation_id": operation},
                           {"agent_id": future_agent, "account_id": None, "operation_id": None}])
        self.restart()
        self.assertEqual(self.signer.beta_operation(body), receipt)
        future = self.provision(None, agent=future_agent, policy=LEGACY)
        self.signer.beta_operation(self.transfer(future)); self.network.commit()
        self.assertEqual(self.signer.beta_operation(self.transfer(future))["amount_uluxar"], "500000000")
        with self.assertRaisesRegex(ValueError, "LEGACY_WELCOME_NOT_ELIGIBLE"):
            self.provision(None, policy=LEGACY)
        with self.assertRaisesRegex(ValueError, "LEGACY_PROFILE_CANNOT_CONSUME_CAMPAIGN"):
            self.provision("1", agent=future_agent)
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM beta_welcome_allocations WHERE policy=?", (CAMPAIGN,)).fetchone()[0], 0)

    def test_new_core_legacy_provision_recovers_before_and_after_activation(self):
        row = self.provision(None, policy=LEGACY)
        self.assertEqual(self.signer.beta_provision(row)["account_id"], row["account_id"])
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM beta_welcome_allocations").fetchone()[0], 0)
        self.start_policy([{"agent_id": row["welcome_grant"]["agent_id"], "account_id": row["account_id"], "operation_id": row["welcome_grant"]["operation_id"]}])
        self.restart()
        self.assertEqual(self.signer.beta_provision(row)["account_id"], row["account_id"])
        body = self.transfer(row)
        self.signer.beta_operation(body); self.network.commit()
        self.assertEqual(self.signer.beta_operation(body)["amount_uluxar"], "500000000")

    def test_concurrent_unique_allocations_exceed_old_cap_and_cannot_rebind(self):
        self.start_policy()
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda ordinal: self.provision(str(ordinal)), range(1, 131)))
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM beta_wallets").fetchone()[0], 130)
        self.assertEqual(self.signer.db.execute("SELECT welcome_allocations FROM identity").fetchone()[0], 130)
        self.signer.beta_provision(rows[0])
        with self.assertRaisesRegex(ValueError, "ALLOCATION_CONFLICT"):
            self.provision("1")
        with self.assertRaisesRegex(ValueError, "ALLOCATION_CONFLICT"):
            self.provision("131", agent=rows[0]["welcome_grant"]["agent_id"])
        self.restart()
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM beta_wallets").fetchone()[0], 130)

    def test_same_ordinal_race_has_one_immutable_winner(self):
        self.start_policy()
        def call(_):
            try:
                return self.provision("2001")
            except ValueError as error:
                self.assertEqual(str(error), "WELCOME_ALLOCATION_CONFLICT")
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(call, range(8)))
        self.assertEqual(sum(row is not None for row in results), 1)
        self.assertEqual(self.signer.db.execute("SELECT count(*) FROM beta_wallets").fetchone()[0], 1)

    def test_missing_allocation_or_table_refuses_startup(self):
        self.start_policy(); self.provision("5001")
        self.signer.db.execute("DELETE FROM beta_welcome_allocations"); self.signer.db.commit()
        with self.assertRaisesRegex(ValueError, "WELCOME_JOURNAL_INCOMPLETE"):
            self.restart()
        self.signer = FixtureSigner.__new__(FixtureSigner)
        # tearDown needs a closable handle after the rejected startup.
        import sqlite3
        self.signer.db = sqlite3.connect(self.directory / "settlements.sqlite")
        self.signer.db.execute("DROP TABLE beta_welcome_campaign"); self.signer.db.commit()
        with self.assertRaisesRegex(ValueError, "WELCOME_JOURNAL_INCOMPLETE"):
            FixtureSigner(self.directory, self.network)

    def test_activation_snapshot_is_exact_idempotent_and_offline_dry_run(self):
        value = {"version": 1, "policy_id": CAMPAIGN, "genesis_hash": self.signer.fingerprint, "legacy_profiles": []}
        digest = hashlib.sha256(canonical(value).encode()).hexdigest()
        path = self.directory / "public-snapshot.json"; path.write_text(canonical(value))
        report = activate_file(self.directory, path, digest, self.signer.fingerprint)
        self.assertFalse(report["applied"])
        self.assertIsNone(initialize(self.signer.db, self.signer.fingerprint))
        self.assertTrue(activate_file(self.directory, path, digest, self.signer.fingerprint, True)["applied"])
        self.assertTrue(activate_file(self.directory, path, digest, self.signer.fingerprint, True)["replayed"])
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            activate_file(self.directory, path, "0" * 64, self.signer.fingerprint, True)

    def test_snapshot_cannot_omit_existing_wallet_or_rebind_existing_grant(self):
        self.signer.beta_provision({"account_id": self.account, "delivery_token": DELIVERY})
        with self.assertRaisesRegex(ValueError, "MISSING_WALLET"):
            self.start_policy()
        operation = new_id()
        self.signer.db.execute("INSERT INTO beta_grants VALUES (?,?)", (self.account, operation)); self.signer.db.commit()
        with self.assertRaisesRegex(ValueError, "GRANT_MISMATCH"):
            self.start_policy([{"agent_id": new_id(), "account_id": self.account, "operation_id": new_id()}])

    def test_health_binds_both_exact_activation_hashes_after_restart(self):
        self.assertEqual(self.signer.beta_health()["welcome_policy"], {"state": "legacy", "policy_id": LEGACY, "snapshot_hash": None, "legacy_inventory_hash": None})
        value, digest, _ = self.start_policy([{"agent_id": new_id(), "account_id": None, "operation_id": None}])
        self.restart()
        self.assertEqual(self.signer.beta_health()["welcome_policy"], {"state": "active", "policy_id": CAMPAIGN, "snapshot_hash": digest,
                         "legacy_inventory_hash": hashlib.sha256(canonical(value["legacy_profiles"]).encode()).hexdigest()})

    def test_activation_refuses_pending_signatures_and_migrated_source(self):
        row = self.provision(None, policy=LEGACY)
        self.signer.beta_operation(self.transfer(row))
        old = {"agent_id": row["welcome_grant"]["agent_id"], "account_id": row["account_id"], "operation_id": row["welcome_grant"]["operation_id"]}
        with self.assertRaisesRegex(ValueError, "PENDING_OPERATIONS"):
            self.start_policy([old])
        self.network.commit(); self.signer.beta_operation(self.transfer(row))
        value = {"version": 1, "policy_id": CAMPAIGN, "genesis_hash": self.signer.fingerprint, "legacy_profiles": [old]}
        digest = hashlib.sha256(canonical(value).encode()).hexdigest()
        path = self.directory / "public-snapshot.json"; path.write_text(canonical(value))
        (self.directory / "signing-moved.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "MIGRATED"):
            activate_file(self.directory, path, digest, self.signer.fingerprint, True)
        self.assertIsNone(initialize(self.signer.db, self.signer.fingerprint))


if __name__ == "__main__":
    unittest.main()
