"""Authenticated local signer; durable transfers and scoped beta key delivery (ADR-050)."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.parse
import uuid

from admin_auth import owner_access_key, assert_plain_path
from localnet import Network, CHAIN_ID, DENOM, FEE, UNIT, run
from trace_protocol import decode as decode_trace, memo_hash as trace_memo_hash
import welcome_policy

PORT = 4175
TREASURY = "foundry-pilot"
BOOTSTRAP = "00000000-0000-4000-8000-000000000001"
BETA_TREASURY = "foundry-beta"
BETA_BOOTSTRAP = "00000000-0000-4000-8000-000000000002"
BETA_WELCOME = 500 * UNIT
BETA_TREASURY_FUNDING = 100_000 * UNIT


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Invalid operation or agent identity")
    return value


@contextmanager
def exclusive_process(path):
    assert_plain_path(path)
    with path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if __import__("os").name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Signer:
    def __init__(self, directory, network=None):
        # A migrated journal must never become a second writer after a reboot.
        fence = directory / "signing-moved.json"
        assert_plain_path(fence)
        if fence.exists():
            raise ValueError("SIGNER_MIGRATED_USE_CURRENT_HOST")
        self.network = network or Network()
        self.lock = threading.Lock()
        genesis = self.network.rpc("genesis")["result"]["genesis"]
        self.fingerprint = hashlib.sha256(canonical(genesis).encode()).hexdigest()
        if genesis["chain_id"] != CHAIN_ID:
            raise ValueError("Wrong chain")
        path = directory / "settlements.sqlite"
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            assert_plain_path(candidate)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS identity (fingerprint TEXT PRIMARY KEY)")
        old = self.db.execute("SELECT fingerprint FROM identity").fetchone()
        if old and old[0] != self.fingerprint:
            raise ValueError("Journal belongs to a different genesis")
        self.db.execute("INSERT OR IGNORE INTO identity (fingerprint) VALUES (?)", (self.fingerprint,))
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL, sender TEXT NOT NULL, recipient TEXT NOT NULL, amount INTEGER NOT NULL, memo TEXT NOT NULL, signed TEXT NOT NULL, hash TEXT UNIQUE NOT NULL, state TEXT NOT NULL, result TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS wallets (agent TEXT PRIMARY KEY, address TEXT UNIQUE NOT NULL)")
        self.db.commit()

    def ensure_key(self, name):
        found = self.network.cli(["keys", "show", name, "-a", "--keyring-backend", "test"], check=False)
        if found.returncode == 0:
            return found.stdout.strip()
        return self.network.wallet(name)

    def wallet(self, agent):
        identifier(agent)
        with self.lock:
            row = self.db.execute("SELECT address FROM wallets WHERE agent=?", (agent,)).fetchone()
            if row:
                address = row[0]
            else:
                if self.db.execute("SELECT count(*) FROM wallets").fetchone()[0] >= 128:
                    raise ValueError("Pilot wallet capacity reached")
                address = self.ensure_key("a-" + agent.replace("-", ""))
                self.db.execute("INSERT INTO wallets VALUES (?, ?)", (agent, address))
                self.db.commit()
            return {"address": address, "balance_uluxar": str(self.network.balance(address)),
                    "chain_id": CHAIN_ID, "genesis_hash": self.fingerprint}

    def stdin_cli(self, args, value):
        self.network.require_owned("container", self.network.name)
        return run(["docker", "exec", "-i", self.network.name, "luxartiumd", *args,
                    "--home", "/chain"], input_text=value, timeout=30).stdout.strip()

    def assert_chain(self):
        # A running gateway must also detect a node replaced after startup.
        genesis = self.network.rpc("genesis")["result"]["genesis"]
        if genesis.get("chain_id") != CHAIN_ID or hashlib.sha256(canonical(genesis).encode()).hexdigest() != self.fingerprint:
            raise ValueError("CHAIN_IDENTITY_CHANGED")

    def confirmed(self, row):
        try:
            result = self.network.rpc("tx?hash=0x" + row["hash"])["result"]
        except (OSError, ValueError, KeyError):
            return None
        # Committed byte identity binds every signed message, fee and memo to this intent.
        raw = base64.b64decode(result["tx"], validate=True)
        if hashlib.sha256(raw).hexdigest().upper() != row["hash"] or result["tx"] != row["signed"]:
            raise ValueError("Committed transaction does not match the signed intent")
        state = "committed" if int(result["tx_result"]["code"]) == 0 else "failed"
        receipt = {"state": state, "operation_id": row["id"], "transaction_hash": row["hash"], "height": result["height"],
                   "sender": row["sender"], "recipient": row["recipient"], "amount_uluxar": str(row["amount"]),
                   "fee_uluxar": str(FEE), "memo": row["memo"], "chain_id": CHAIN_ID,
                   "genesis_hash": self.fingerprint}
        self.db.execute("UPDATE operations SET state=?, result=? WHERE id=?", (state, canonical(receipt), row["id"]))
        self.db.commit()
        return receipt

    def execute(self, operation, payload, sender_name, recipient, amount, memo):
        """Caller holds process-wide lock. This journal is the only signing path."""
        self.assert_chain()
        serialized = canonical(payload)
        row = self.db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
        if row and row["payload"] != serialized:
            raise ValueError("IDEMPOTENCY_CONFLICT")
        if row and row["result"]:
            return json.loads(row["result"])
        sender = self.network.address(sender_name)
        if not row:
            for pending in self.db.execute("SELECT * FROM operations WHERE sender=? AND state='pending'", (sender,)).fetchall():
                if not self.confirmed(pending):
                    return {"state": "pending", "reason": "An earlier transfer from this wallet is awaiting confirmation."}
            if sender_name == TREASURY:
                allocated = self.db.execute("SELECT coalesce(sum(amount + ?), 0) FROM operations WHERE sender=?", (FEE, sender)).fetchone()[0]
                if allocated + amount + FEE > 1000 * UNIT:
                    raise ValueError("Pilot treasury budget exhausted")
            if self.network.balance(sender) < amount + FEE:
                raise ValueError("Insufficient test LUXAR including transaction fee")
            unsigned = self.network.cli(["tx", "bank", "send", sender_name, recipient, f"{amount}{DENOM}",
                "--chain-id", CHAIN_ID, "--keyring-backend", "test", "--fees", f"{FEE}{DENOM}",
                "--gas", "200000", "--note", memo, "--generate-only", "--output", "json"]).stdout
            signed_json = self.stdin_cli(["tx", "sign", "/dev/stdin", "--from", sender_name,
                "--chain-id", CHAIN_ID, "--keyring-backend", "test", "--output", "json"], unsigned)
            signed = self.stdin_cli(["tx", "encode", "/dev/stdin"], signed_json).strip('"')
            txhash = hashlib.sha256(base64.b64decode(signed, validate=True)).hexdigest().upper()
            self.db.execute("INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL)",
                            (operation, serialized, sender, recipient, amount, memo, signed, txhash))
            self.db.commit()  # Durable bytes BEFORE the first broadcast, including bootstrap.
            row = self.db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
        receipt = self.confirmed(row)
        if receipt:
            return receipt
        try:
            # GET quoted strings are UTF-8 bytes, not base64. Send the actual signed bytes.
            # https://github.com/cometbft/cometbft/blob/main/docs/core/using-cometbft.md#formatting
            self.network.rpc("broadcast_tx_sync?tx=0x" + base64.b64decode(row["signed"], validate=True).hex())
        except (OSError, ValueError, KeyError):
            pass  # Unknown outcome retains exactly these bytes and their identity.
        return {"state": "pending", "transaction_hash": row["hash"], "chain_id": CHAIN_ID,
                "genesis_hash": self.fingerprint}

    def initialize(self):
        with self.lock:
            address = self.ensure_key(TREASURY)
            result = self.execute(BOOTSTRAP, {"bootstrap": self.fingerprint}, "faucet", address,
                                  1001 * UNIT, "foundry:testnet-pilot-treasury:v1")
            return {"treasury_address": address, **result}

    def operation(self, body):
        if not isinstance(body, dict) or set(body) != {"operation_id", "kind", "agent_id", "amount_uluxar", "manifest_hash", "genesis_hash"}:
            raise ValueError("Unsupported operation shape")
        operation, agent = identifier(body["operation_id"]), identifier(body["agent_id"])
        if operation == BOOTSTRAP or body["genesis_hash"] != self.fingerprint:
            raise ValueError("Wrong network or reserved operation")
        kind = body["kind"]
        if kind not in ("sale", "reward", "credits", "anchor"):
            raise ValueError("Unsupported action")
        amount_text = body["amount_uluxar"]
        if not isinstance(amount_text, str) or not re.fullmatch(r"[1-9][0-9]{0,8}", amount_text):
            raise ValueError("Invalid amount")
        amount = int(amount_text)
        if amount > 100 * UNIT:
            raise ValueError("Operation exceeds pilot limit")
        manifest = body["manifest_hash"]
        if not isinstance(manifest, str) or (manifest and not re.fullmatch(r"sha256:[a-f0-9]{64}", manifest)):
            raise ValueError("Invalid commitment")
        if kind == "anchor" and (amount != 1 or not manifest):
            raise ValueError("Invalid anchor")
        with self.lock:
            wallet = self.db.execute("SELECT address FROM wallets WHERE agent=?", (agent,)).fetchone()
            if not wallet:
                raise ValueError("Managed wallet must exist")
            sender = "a-" + agent.replace("-", "") if kind == "credits" else TREASURY
            recipient = self.network.address(TREASURY) if kind in ("credits", "anchor") else wallet[0]
            memo = f"foundry:{kind}:{operation}" + (":" + manifest if manifest else "")
            return self.execute(operation, body, sender, recipient, amount, memo)


class BetaSigner(Signer):
    """Typed beta transfers. Business ownership/offer checks remain in Foundry core."""

    def __init__(self, directory, network=None, clock=time.time):
        super().__init__(directory, network)
        self.clock = clock
        self.db.execute("CREATE TABLE IF NOT EXISTS beta_wallets (account TEXT PRIMARY KEY, address TEXT UNIQUE NOT NULL, delivery_hash TEXT NOT NULL, delivery_expires INTEGER NOT NULL, acknowledged INTEGER)")
        self.db.execute("CREATE TABLE IF NOT EXISTS beta_grants (account TEXT PRIMARY KEY, operation TEXT UNIQUE NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS beta_refunds (original_operation TEXT PRIMARY KEY, operation TEXT UNIQUE NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS beta_intents (operation TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS beta_trace_events (memo_hash TEXT PRIMARY KEY, operation TEXT UNIQUE NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS beta_config (id INTEGER PRIMARY KEY CHECK(id=1), treasury_address TEXT NOT NULL)")
        self.db.commit()
        try:
            self.assert_trace_journal()
            self.welcome_campaign = welcome_policy.initialize(self.db, self.fingerprint)
        except Exception:
            self.db.close()
            raise

    def assert_trace_journal(self):
        # Legacy journals have zero trace intents. Once traces exist, losing their
        # uniqueness index must refuse startup rather than re-attest under new IDs.
        trace_intents = {}
        for row in self.db.execute("SELECT operation,payload FROM beta_intents"):
            payload = json.loads(row["payload"])
            if "memo" in payload:
                if set(payload) != {"operation_id", "genesis_hash", "memo"} or payload["operation_id"] != row["operation"] or payload["genesis_hash"] != self.fingerprint:
                    raise ValueError("TRACE_JOURNAL_INVALID")
                digest = trace_memo_hash(payload["memo"])
                if digest in trace_intents:
                    raise ValueError("TRACE_JOURNAL_INVALID")
                trace_intents[digest] = row["operation"]
        saved_traces = {row["memo_hash"]: row["operation"] for row in self.db.execute("SELECT memo_hash,operation FROM beta_trace_events")}
        if saved_traces != trace_intents:
            raise ValueError("TRACE_JOURNAL_INVALID")

    @staticmethod
    def key_name(account):
        return "b-" + identifier(account).replace("-", "")

    def initialize_beta(self):
        with self.lock:
            address = self.ensure_key(BETA_TREASURY)
            self.db.execute("INSERT OR IGNORE INTO beta_config VALUES (1, ?)", (address,))
            self.db.commit()
            if self.beta_treasury() != address:
                raise ValueError("TREASURY_IDENTITY_CHANGED")
            result = self.execute(BETA_BOOTSTRAP, {"beta_bootstrap": self.fingerprint}, "faucet", address,
                                  BETA_TREASURY_FUNDING, "foundry:beta:treasury:v1")
            return {"treasury_address": address, **result}

    def beta_health(self):
        # Health shares the same SQLite connection and keyring as signing. Its
        # execute/fetch sequence must use the same lock as every other request.
        with self.lock:
            self.assert_chain()
            return {"chain_id": CHAIN_ID, "genesis_hash": self.fingerprint,
                    "treasury_address": self.beta_treasury(),
                    "welcome_policy": {"state": "active" if self.welcome_campaign else "legacy",
                        "policy_id": welcome_policy.CAMPAIGN if self.welcome_campaign else welcome_policy.LEGACY,
                        "snapshot_hash": self.db.execute("SELECT welcome_policy_hash FROM identity").fetchone()[0],
                        "legacy_inventory_hash": hashlib.sha256(canonical(self.welcome_campaign["legacy_profiles"]).encode()).hexdigest() if self.welcome_campaign else None}}

    def beta_treasury(self):
        row = self.db.execute("SELECT treasury_address FROM beta_config WHERE id=1").fetchone()
        if not row or row[0] != self.network.address(BETA_TREASURY):
            raise ValueError("TREASURY_IDENTITY_CHANGED")
        return row[0]

    def beta_wallet_record(self, account):
        row = self.db.execute("SELECT * FROM beta_wallets WHERE account=?", (identifier(account),)).fetchone()
        if not row:
            raise ValueError("BETA_WALLET_NOT_FOUND")
        return row

    def beta_wallet_public(self, row):
        if self.network.address(self.key_name(row["account"])) != row["address"]:
            raise ValueError("WALLET_IDENTITY_CHANGED")
        return {"account_id": row["account"], "address": row["address"],
                "balance_uluxar": str(self.network.balance(row["address"])),
                "chain_id": CHAIN_ID, "genesis_hash": self.fingerprint,
                "custody": "managed_local_test_keyring"}

    def beta_wallet(self, account):
        with self.lock:
            self.assert_chain()
            return self.beta_wallet_public(self.beta_wallet_record(account))

    def claim_beta_wallet(self, account, digest, create=True):
        row = self.db.execute("SELECT * FROM beta_wallets WHERE account=?", (account,)).fetchone()
        if row is None:
            if not create:
                raise ValueError("BETA_WALLET_NOT_FOUND")
            if self.welcome_campaign and not self.db.execute("SELECT 1 FROM beta_welcome_allocations WHERE account=?", (account,)).fetchone():
                raise ValueError("WELCOME_ALLOCATION_REQUIRED")
            if not self.welcome_campaign and self.db.execute("SELECT count(*) FROM beta_wallets").fetchone()[0] >= 128:
                raise ValueError("BETA_WALLET_CAPACITY")
            address = self.ensure_key(self.key_name(account))
            # Zero means public provisioning only: key delivery has not started.
            self.db.execute("INSERT INTO beta_wallets VALUES (?, ?, ?, 0, NULL)", (account, address, digest))
            self.db.commit()
            row = self.beta_wallet_record(account)
        if not hmac.compare_digest(row["delivery_hash"], digest):
            raise ValueError("KEY_DELIVERY_FORBIDDEN")
        return row

    def beta_provision(self, body):
        fields = {"account_id", "delivery_token"}
        if not isinstance(body, dict) or set(body) not in (fields, fields | {"welcome_grant"}):
            raise ValueError("INVALID_ENROLLMENT")
        account, token = identifier(body["account_id"]), body["delivery_token"]
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ValueError("INVALID_ENROLLMENT")
        with self.lock:
            self.assert_chain()
            if "welcome_grant" in body:
                if self.welcome_campaign:
                    welcome_policy.bind(self.db, self.welcome_campaign, account, body["welcome_grant"])
                elif welcome_policy.authorization(body["welcome_grant"])["policy_id"] != welcome_policy.LEGACY:
                    raise ValueError("WELCOME_CAMPAIGN_NOT_ACTIVE")
            return self.beta_wallet_public(self.claim_beta_wallet(account, hashlib.sha256(token.encode()).hexdigest()))

    def beta_enroll(self, body):
        if not isinstance(body, dict) or set(body) != {"account_id", "delivery_token", "acknowledge"}:
            raise ValueError("INVALID_ENROLLMENT")
        account = identifier(body["account_id"])
        token = body["delivery_token"]
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token) or type(body["acknowledge"]) is not bool:
            raise ValueError("INVALID_ENROLLMENT")
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            self.assert_chain()
            row = self.claim_beta_wallet(account, digest, not body["acknowledge"] and not self.welcome_campaign)
            public = self.beta_wallet_public(row)
            if row["delivery_expires"] == 0:
                if body["acknowledge"]:
                    raise ValueError("KEY_DELIVERY_NOT_STARTED")
                self.db.execute("UPDATE beta_wallets SET delivery_expires=? WHERE account=?", (int(self.clock()) + 1800, account))
                self.db.commit()
                row = self.beta_wallet_record(account)
            result = {**public, "delivery_expires_at": row["delivery_expires"]}
            if row["acknowledged"] is not None:
                return {**result, "key_delivery": "acknowledged"}
            if row["delivery_expires"] <= self.clock():
                raise ValueError("KEY_DELIVERY_EXPIRED")
            if body["acknowledge"]:
                self.db.execute("UPDATE beta_wallets SET acknowledged=? WHERE account=?", (int(self.clock()), account))
                self.db.commit()
                return {**result, "key_delivery": "acknowledged"}
            # Capture internally; neither stdout logging nor subprocess errors may expose a key.
            exported = self.network.cli(["keys", "export", self.key_name(account), "--keyring-backend", "test",
                                         "--unarmored-hex", "--unsafe", "--yes"], check=False)
            private_key = exported.stdout.strip()
            if exported.returncode != 0 or not re.fullmatch(r"[a-fA-F0-9]{64}", private_key):
                raise ValueError("KEY_DELIVERY_UNAVAILABLE")
            return {**result, "key_delivery": "awaiting_acknowledgement", "private_key_hex": private_key.lower()}

    def beta_trace(self, body):
        if not isinstance(body, dict) or set(body) != {"operation_id", "genesis_hash", "memo"}:
            raise ValueError("INVALID_TRACE_OPERATION")
        operation = identifier(body["operation_id"])
        if operation in (BOOTSTRAP, BETA_BOOTSTRAP) or body["genesis_hash"] != self.fingerprint:
            raise ValueError("WRONG_NETWORK")
        decode_trace(body["memo"])
        digest = trace_memo_hash(body["memo"])
        with self.lock:
            self.assert_chain()
            if self.db.execute("SELECT 1 FROM beta_welcome_allocations WHERE operation=?", (operation,)).fetchone():
                raise ValueError("WELCOME_OPERATION_RESERVED")
            treasury = self.beta_treasury()
            intent = self.db.execute("SELECT payload FROM beta_intents WHERE operation=?", (operation,)).fetchone()
            existing = self.db.execute("SELECT payload FROM operations WHERE id=?", (operation,)).fetchone()
            if any(row and row[0] != canonical(body) for row in (intent, existing)):
                raise ValueError("IDEMPOTENCY_CONFLICT")
            saved = self.db.execute("SELECT memo_hash,operation FROM beta_trace_events WHERE memo_hash=? OR operation=?", (digest, operation)).fetchall()
            if any(row[0] != digest or row[1] != operation for row in saved):
                raise ValueError("TRACE_EVENT_ALREADY_BOUND")
            self.db.execute("INSERT OR IGNORE INTO beta_trace_events VALUES (?, ?)", (digest, operation))
            self.db.execute("INSERT OR IGNORE INTO beta_intents VALUES (?, ?)", (operation, canonical(body)))
            self.db.commit()
            result = self.execute(operation, body, BETA_TREASURY, treasury, 1, body["memo"])
            return {**result, "operation_id": operation, "chain_id": CHAIN_ID, "genesis_hash": self.fingerprint}

    def beta_operation(self, body):
        fields = {"operation_id", "kind", "from_account_id", "to_account_id", "amount_uluxar", "reference_hash", "reverses_operation_id", "genesis_hash"}
        if not isinstance(body, dict) or set(body) not in (fields, fields | {"grant_authorization"}):
            raise ValueError("INVALID_BETA_OPERATION")
        operation = identifier(body["operation_id"])
        if operation in (BOOTSTRAP, BETA_BOOTSTRAP) or body["genesis_hash"] != self.fingerprint:
            raise ValueError("WRONG_NETWORK_OR_RESERVED_OPERATION")
        kind = body["kind"]
        if "grant_authorization" in body and kind != "grant":
            raise ValueError("INVALID_WELCOME_AUTHORIZATION")
        if kind not in ("grant", "action", "refund", "sale", "rent", "commit"):
            raise ValueError("INVALID_BETA_OPERATION")
        amount_text, reference = body["amount_uluxar"], body["reference_hash"]
        if not isinstance(amount_text, str) or not re.fullmatch(r"[1-9][0-9]{0,11}", amount_text):
            raise ValueError("INVALID_AMOUNT")
        amount = int(amount_text)
        if amount > BETA_TREASURY_FUNDING or not isinstance(reference, str) or not re.fullmatch(r"[a-f0-9]{64}", reference):
            raise ValueError("INVALID_AMOUNT_OR_REFERENCE")
        source, destination, reversal = body["from_account_id"], body["to_account_id"], body["reverses_operation_id"]
        for account in (source, destination):
            if account is not None:
                identifier(account)
        if kind != "refund" and reversal is not None:
            raise ValueError("INVALID_REVERSAL")
        if kind == "grant" and (source is not None or destination is None):
            raise ValueError("INVALID_WELCOME_GRANT")
        if kind == "action" and (source is None or destination is not None or amount != UNIT):
            raise ValueError("INVALID_ACTION_PAYMENT")
        if kind in ("sale", "rent") and (source is None or destination is None or source == destination):
            raise ValueError("INVALID_OWNER_PAYMENT")
        if kind == "commit" and (source is not None or destination is not None or amount != 1):
            raise ValueError("INVALID_COMMITMENT")
        if kind == "refund" and (source is not None or destination is None or amount != UNIT + FEE or reversal is None):
            raise ValueError("INVALID_REFUND")
        with self.lock:
            self.assert_chain()
            if kind == "grant":
                welcome_policy.check_grant(self.db, self.welcome_campaign, body)
            elif self.db.execute("SELECT 1 FROM beta_welcome_allocations WHERE operation=?", (operation,)).fetchone():
                raise ValueError("WELCOME_OPERATION_RESERVED")
            sender_name = self.key_name(source) if source else BETA_TREASURY
            if source:
                if self.beta_wallet_record(source)["address"] != self.network.address(sender_name):
                    raise ValueError("WALLET_IDENTITY_CHANGED")
            treasury = self.beta_treasury()
            recipient = self.beta_wallet_record(destination)["address"] if destination else treasury
            existing = self.db.execute("SELECT payload FROM operations WHERE id=?", (operation,)).fetchone()
            if existing and existing["payload"] != canonical(body):
                raise ValueError("IDEMPOTENCY_CONFLICT")
            intent = self.db.execute("SELECT payload FROM beta_intents WHERE operation=?", (operation,)).fetchone()
            if intent and intent[0] != canonical(body):
                raise ValueError("IDEMPOTENCY_CONFLICT")
            if kind == "grant":
                row = self.db.execute("SELECT account, operation FROM beta_grants WHERE account=? OR operation=?", (destination, operation)).fetchone()
                if row and (row[0] != destination or row[1] != operation):
                    raise ValueError("WELCOME_ALREADY_CLAIMED")
                self.db.execute("INSERT OR IGNORE INTO beta_grants VALUES (?, ?)", (destination, operation))
            if kind == "refund":
                identifier(reversal)
                original = self.db.execute("SELECT * FROM operations WHERE id=?", (reversal,)).fetchone()
                if not original or original["state"] != "committed" or original["sender"] != recipient or json.loads(original["payload"]).get("kind") != "action":
                    raise ValueError("REFUND_REQUIRES_COMMITTED_ACTION")
                row = self.db.execute("SELECT original_operation, operation FROM beta_refunds WHERE original_operation=? OR operation=?", (reversal, operation)).fetchone()
                if row and (row[0] != reversal or row[1] != operation):
                    raise ValueError("ACTION_ALREADY_REFUNDED")
                self.db.execute("INSERT OR IGNORE INTO beta_refunds VALUES (?, ?)", (reversal, operation))
            self.db.execute("INSERT OR IGNORE INTO beta_intents VALUES (?, ?)", (operation, canonical(body)))
            self.db.commit()
            result = self.execute(operation, body, sender_name, recipient, amount, f"foundry:beta:{kind}:{operation}:{reference}")
            return {**result, "operation_id": operation, "chain_id": CHAIN_ID, "genesis_hash": self.fingerprint}


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        self.connection.settimeout(10)
        try:
            expected = hashlib.sha256(self.headers.get("Authorization", "").encode()).digest()
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or self.headers.get("Origin") or not hmac.compare_digest(expected, self.server.key_hash):
                return self.reply(403, {"error": "Gateway authentication required"})
            length = self.headers.get("Content-Length", "")
            if self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding") or not re.fullmatch(r"[0-9]{1,4}", length) or not 0 < int(length) <= 2048:
                return self.reply(400, {"error": "A bounded JSON body is required"})
            body = json.loads(self.rfile.read(int(length)))
            if self.path == "/health" and body == {}:
                result = {"chain_id": CHAIN_ID, "genesis_hash": self.server.signer.fingerprint,
                          "treasury_address": self.server.signer.network.address(TREASURY)}
            elif self.path == "/wallet" and isinstance(body, dict) and set(body) == {"agent_id"}:
                result = self.server.signer.wallet(body["agent_id"])
            elif self.path == "/operation":
                result = self.server.signer.operation(body)
            elif self.path == "/beta/provision":
                result = self.server.signer.beta_provision(body)
            elif self.path == "/beta/enroll":
                result = self.server.signer.beta_enroll(body)
            elif self.path == "/beta/wallet" and isinstance(body, dict) and set(body) == {"account_id"}:
                result = self.server.signer.beta_wallet(body["account_id"])
            elif self.path == "/beta/operation":
                result = self.server.signer.beta_operation(body)
            elif self.path == "/beta/trace":
                result = self.server.signer.beta_trace(body)
            elif self.path == "/beta/health" and body == {}:
                result = self.server.signer.beta_health()
            else:
                return self.reply(404, {"error": "Unsupported gateway operation"})
            self.reply(200, result)
        except ValueError as error:
            self.reply(409, {"error": str(error)[:180]})
        except Exception:
            self.reply(503, {"error": "Local signer unavailable; retry the same operation identity"})

    def reply(self, status, data):
        raw = canonical(data).encode()
        self.send_response(status)
        # Workerd pools a socket unless its close is explicit, even for HTTP/1.0.
        # This handler serves one bounded request per connection.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.reply(405, {"error": "Authenticated POST only"})


def initialize_treasuries(signer):
    for name, initialize in (("Pilot", signer.initialize), ("Beta", signer.initialize_beta)):
        deadline = time.monotonic() + 90
        while True:
            result = initialize()
            if result["state"] == "committed":
                print(name + " treasury initialization: committed", flush=True)
                break
            if result["state"] == "failed" or time.monotonic() >= deadline:
                raise RuntimeError(name + " treasury funding not confirmed; restart to reconcile the same transfer")
            time.sleep(1)


def serve():
    key = owner_access_key("gateway")
    directory = Path.home() / ".luxartium/gateway"
    with exclusive_process(directory / "gateway.lock"):
        signer = BetaSigner(directory)
        initialize_treasuries(signer)
        print("Genesis fingerprint:", signer.fingerprint, flush=True)
        with ThreadingHTTPServer(("127.0.0.1", PORT), GatewayHandler) as server:
            server.signer = signer
            server.key_hash = hashlib.sha256(("Bearer " + key).encode()).digest()
            del key
            print(f"Local signer listening on 127.0.0.1:{PORT}", flush=True)
            try:
                server.serve_forever()
            finally:
                signer.db.close()


if __name__ == "__main__":
    serve()
