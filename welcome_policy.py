"""Explicit, durable welcome campaign authority. No keys, RPC or signing here."""
import hashlib
import json
import re
import sqlite3
import uuid

CAMPAIGN = "welcome-waterfall-v1"
LEGACY = "legacy-flat-500"
UNIT = 1_000_000
MAX_ORDINAL = 9_007_199_254_740_991
MAX_PROFILES = 100_000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def identity(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError("INVALID_WELCOME_AUTHORIZATION") from None
    return value


def amount_for(ordinal):
    if not isinstance(ordinal, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", ordinal) or int(ordinal) > MAX_ORDINAL:
        raise ValueError("INVALID_WELCOME_ORDINAL")
    return str(max(0, 500 - ((int(ordinal) - 1) // 1000) * 100) * UNIT)


def authorization(value):
    fields = {"agent_id", "operation_id", "policy_id", "ordinal", "amount_uluxar"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("INVALID_WELCOME_AUTHORIZATION")
    identity(value["agent_id"]); identity(value["operation_id"])
    if value["operation_id"] in ("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"):
        raise ValueError("INVALID_WELCOME_AUTHORIZATION")
    if value["policy_id"] == LEGACY:
        expected = "500000000"
        if value["ordinal"] is not None:
            raise ValueError("INVALID_WELCOME_ORDINAL")
    elif value["policy_id"] == CAMPAIGN:
        expected = amount_for(value["ordinal"])
    else:
        raise ValueError("INVALID_WELCOME_POLICY")
    if value["amount_uluxar"] != expected:
        raise ValueError("INVALID_WELCOME_AMOUNT")
    return value


def snapshot(value, genesis):
    if not isinstance(value, dict) or set(value) != {"version", "policy_id", "genesis_hash", "legacy_profiles"} or type(value["version"]) is not int or value["version"] != 1 or value["policy_id"] != CAMPAIGN or value["genesis_hash"] != genesis:
        raise ValueError("INVALID_WELCOME_SNAPSHOT")
    rows = value["legacy_profiles"]
    if not isinstance(rows, list) or len(rows) > MAX_PROFILES:
        raise ValueError("INVALID_WELCOME_SNAPSHOT")
    agents, accounts, operations = set(), set(), set()
    previous = ""
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"agent_id", "account_id", "operation_id"}:
            raise ValueError("INVALID_WELCOME_SNAPSHOT")
        agent = identity(row["agent_id"])
        if agent <= previous:
            raise ValueError("WELCOME_SNAPSHOT_NOT_CANONICAL")
        previous = agent; agents.add(agent)
        if (row["account_id"] is None) != (row["operation_id"] is None):
            raise ValueError("INVALID_WELCOME_SNAPSHOT")
        if row["account_id"] is not None:
            account, operation = identity(row["account_id"]), identity(row["operation_id"])
            if account in accounts or operation in operations:
                raise ValueError("WELCOME_SNAPSHOT_DUPLICATE")
            accounts.add(account); operations.add(operation)
    return value


def initialize(database, genesis):
    columns = {row[1] for row in database.execute("PRAGMA table_info(identity)")}
    with database:
        if "welcome_policy_hash" not in columns:
            database.execute("ALTER TABLE identity ADD COLUMN welcome_policy_hash TEXT")
        if "welcome_allocations" not in columns:
            database.execute("ALTER TABLE identity ADD COLUMN welcome_allocations INTEGER NOT NULL DEFAULT 0")
        marker, count = database.execute("SELECT welcome_policy_hash,welcome_allocations FROM identity").fetchone()
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if marker and not {"beta_welcome_campaign", "beta_welcome_allocations"} <= tables:
            raise ValueError("WELCOME_JOURNAL_INCOMPLETE")
        database.execute("CREATE TABLE IF NOT EXISTS beta_welcome_campaign (id INTEGER PRIMARY KEY CHECK(id=1), snapshot TEXT NOT NULL)")
        database.execute("CREATE TABLE IF NOT EXISTS beta_welcome_allocations (account TEXT PRIMARY KEY, agent TEXT UNIQUE NOT NULL, operation TEXT UNIQUE NOT NULL, policy TEXT NOT NULL, ordinal TEXT, payload TEXT NOT NULL, UNIQUE(policy,ordinal))")
    config = database.execute("SELECT snapshot FROM beta_welcome_campaign WHERE id=1").fetchone()
    if not marker:
        if config or count or database.execute("SELECT 1 FROM beta_welcome_allocations LIMIT 1").fetchone():
            raise ValueError("WELCOME_JOURNAL_INCOMPLETE")
        return None
    if not config or hashlib.sha256(config[0].encode()).hexdigest() != marker:
        raise ValueError("WELCOME_JOURNAL_INCOMPLETE")
    value = snapshot(json.loads(config[0]), genesis)
    if canonical(value) != config[0]:
        raise ValueError("WELCOME_JOURNAL_INCOMPLETE")
    allocated = database.execute("SELECT * FROM beta_welcome_allocations").fetchall()
    if len(allocated) != count:
        raise ValueError("WELCOME_JOURNAL_INCOMPLETE")
    legacy = {row["agent_id"]: row for row in value["legacy_profiles"]}
    for row in allocated:
        auth = authorization(json.loads(row["payload"]))
        if canonical(auth) != row["payload"] or (auth["agent_id"], auth["operation_id"], auth["policy_id"], auth["ordinal"]) != (row["agent"], row["operation"], row["policy"], row["ordinal"]):
            raise ValueError("WELCOME_JOURNAL_INCOMPLETE")
        validate_eligibility(legacy, row["account"], auth)
    if database.execute("SELECT 1 FROM beta_wallets w LEFT JOIN beta_welcome_allocations a ON a.account=w.account WHERE a.account IS NULL LIMIT 1").fetchone():
        raise ValueError("WELCOME_JOURNAL_INCOMPLETE")
    return value


def validate_eligibility(legacy, account, auth):
    old = legacy.get(auth["agent_id"])
    if auth["policy_id"] == LEGACY:
        if not old or (old["account_id"] is not None and (old["account_id"], old["operation_id"]) != (account, auth["operation_id"])):
            raise ValueError("LEGACY_WELCOME_NOT_ELIGIBLE")
    elif old:
        raise ValueError("LEGACY_PROFILE_CANNOT_CONSUME_CAMPAIGN")


def bind(database, config, account, value):
    """Called under signer.lock. Persist authorization before any key is created."""
    auth = authorization(value)
    if config is None:
        raise ValueError("WELCOME_CAMPAIGN_NOT_ACTIVE")
    validate_eligibility({row["agent_id"]: row for row in config["legacy_profiles"]}, account, auth)
    rows = database.execute("SELECT * FROM beta_welcome_allocations WHERE account=? OR agent=? OR operation=? OR (policy=? AND ordinal=?)", (account, auth["agent_id"], auth["operation_id"], auth["policy_id"], auth["ordinal"])).fetchall()
    if rows:
        if len(rows) != 1 or rows[0]["account"] != account or rows[0]["payload"] != canonical(auth):
            raise ValueError("WELCOME_ALLOCATION_CONFLICT")
        return
    if database.execute("SELECT 1 FROM operations WHERE id=?", (auth["operation_id"],)).fetchone() or database.execute("SELECT 1 FROM beta_intents WHERE operation=?", (auth["operation_id"],)).fetchone():
        raise ValueError("WELCOME_OPERATION_ALREADY_USED")
    with database:
        database.execute("INSERT INTO beta_welcome_allocations VALUES (?,?,?,?,?,?)", (account, auth["agent_id"], auth["operation_id"], auth["policy_id"], auth["ordinal"], canonical(auth)))
        database.execute("UPDATE identity SET welcome_allocations=welcome_allocations+1")


def activate(database, value, expected_hash, genesis):
    """Offline-only: caller holds the same process lock as the sole signer."""
    value = snapshot(value, genesis)
    encoded = canonical(value)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    if digest != expected_hash:
        raise ValueError("WELCOME_SNAPSHOT_HASH_MISMATCH")
    existing = initialize(database, genesis)
    if existing is not None:
        if canonical(existing) != encoded:
            raise ValueError("WELCOME_CAMPAIGN_ALREADY_ACTIVE")
        return {"policy_id": CAMPAIGN, "snapshot_hash": digest, "replayed": True}
    if database.execute("SELECT 1 FROM operations WHERE state='pending' LIMIT 1").fetchone():
        raise ValueError("WELCOME_ACTIVATION_PENDING_OPERATIONS")
    accounts = {row["account_id"]: row for row in value["legacy_profiles"] if row["account_id"] is not None}
    if any(row[0] not in accounts for row in database.execute("SELECT account FROM beta_wallets")):
        raise ValueError("WELCOME_SNAPSHOT_MISSING_WALLET")
    for account, operation in database.execute("SELECT account,operation FROM beta_grants"):
        if account not in accounts or accounts[account]["operation_id"] != operation:
            raise ValueError("WELCOME_SNAPSHOT_GRANT_MISMATCH")
    for account, row in accounts.items():
        for query in ("SELECT payload FROM operations WHERE id=?", "SELECT payload FROM beta_intents WHERE operation=?"):
            saved = database.execute(query, (row["operation_id"],)).fetchone()
            if saved:
                intent = json.loads(saved[0])
                if intent.get("kind") != "grant" or intent.get("to_account_id") != account or intent.get("amount_uluxar") != "500000000" or "grant_authorization" in intent:
                    raise ValueError("WELCOME_SNAPSHOT_GRANT_MISMATCH")
    with database:
        database.execute("INSERT INTO beta_welcome_campaign VALUES (1,?)", (encoded,))
        for account, row in accounts.items():
            auth = authorization({"agent_id": row["agent_id"], "operation_id": row["operation_id"], "policy_id": LEGACY, "ordinal": None, "amount_uluxar": "500000000"})
            database.execute("INSERT INTO beta_welcome_allocations VALUES (?,?,?,?,?,?)", (account, row["agent_id"], row["operation_id"], LEGACY, None, canonical(auth)))
        database.execute("UPDATE identity SET welcome_policy_hash=?,welcome_allocations=?", (digest, len(accounts)))
    initialize(database, genesis)
    return {"policy_id": CAMPAIGN, "snapshot_hash": digest, "legacy_profiles": len(value["legacy_profiles"]), "legacy_accounts": len(accounts), "replayed": False}


def check_grant(database, config, body):
    auth = body.get("grant_authorization")
    row = database.execute("SELECT payload FROM beta_welcome_allocations WHERE account=?", (body["to_account_id"],)).fetchone()
    if config is None:
        if "grant_authorization" in body or body["amount_uluxar"] != "500000000":
            raise ValueError("INVALID_WELCOME_GRANT")
        return
    if not row:
        raise ValueError("WELCOME_ALLOCATION_REQUIRED")
    saved = json.loads(row[0])
    if saved["operation_id"] != body["operation_id"] or saved["amount_uluxar"] != body["amount_uluxar"] or saved["amount_uluxar"] == "0":
        raise ValueError("WELCOME_ALLOCATION_CONFLICT")
    expected = {key: saved[key] for key in ("policy_id", "ordinal", "amount_uluxar")}
    if (saved["policy_id"] == LEGACY and "grant_authorization" in body) or (saved["policy_id"] == CAMPAIGN and auth != expected):
        raise ValueError("WELCOME_AUTHORIZATION_REQUIRED")
