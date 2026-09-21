"""Foundry t1 public trace codec. Pure, strict, bounded and compatible with ADR-055."""
import base64
import hashlib
import json
import re
import uuid

PREFIX = "foundry:t1:"
MAX_MEMO = 256
MAX_SAFE = 9007199254740991


def compact(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def expand(value, size):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("INVALID_TRACE_EVENT")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(raw) != size or compact(raw) != value:
        raise ValueError("INVALID_TRACE_EVENT")
    return raw


def identity(value):
    result = uuid.UUID(bytes=expand(value, 16))
    # Match Zod's UUID RFC variant/version validation, including nil/max sentinels.
    if result.int not in (0, (1 << 128) - 1) and (result.variant != uuid.RFC_4122 or result.version not in range(1, 9)):
        raise ValueError("INVALID_TRACE_EVENT")
    return str(result)


def digest(value):
    return expand(value, 32).hex()


def number(value, maximum=MAX_SAFE, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("INVALID_TRACE_EVENT")
    return value


def choice(*values):
    def parse(value):
        if value not in values or not isinstance(value, str):
            raise ValueError("INVALID_TRACE_EVENT")
        return value
    return parse


def nullable(parse):
    return lambda value: None if value is None else parse(value)


def pattern(expression):
    def parse(value):
        if not isinstance(value, str) or not re.fullmatch(expression, value):
            raise ValueError("INVALID_TRACE_EVENT")
        return value
    return parse


SCHEMAS = {
    "i": ("identity", [("agent_id", identity), ("account_id", identity), ("address", pattern(r"luxar1[0-9a-z]{38}"))]),
    "v": ("version", [("version_id", identity), ("artwork_id", identity), ("agent_id", identity), ("manifest_hash", digest), ("purpose", choice("a", "u")), ("created_at_ms", number)]),
    "l": ("ancestry", [("version_id", identity), ("parent_version_id", nullable(identity)), ("source_version_id", nullable(identity))]),
    "b": ("asset", [("version_id", identity), ("asset_id", identity), ("sha256", digest), ("role", choice("primary", "thumbnail", "manifest", "source", "aux"))]),
    "p": ("publication", [("piece_id", identity), ("version_id", identity), ("creator_account_id", identity), ("owner_account_id", identity), ("origin", choice("native", "gallery", "branch")), ("source_id", identity), ("published_at_ms", number)]),
    "g": ("permission", [("workspace_id", identity), ("piece_id", identity), ("version_id", identity), ("account_id", identity), ("basis", choice("owner", "rent", "alpha")), ("authorization_id", identity), ("package_hash", nullable(digest))]),
    "s": ("sale", [("payment_id", identity), ("piece_id", identity), ("previous_owner_id", identity), ("owner_id", identity), ("payment_transaction_hash", digest), ("previous_ownership_hash", digest)]),
    "r": ("rental", [("payment_id", identity), ("piece_id", identity), ("version_id", identity), ("payer_account_id", identity), ("owner_account_id", identity), ("workspace_id", identity), ("payment_transaction_hash", digest)]),
    "a": ("action", [("attempt_id", identity), ("workspace_id", identity), ("account_id", identity), ("tool", pattern(r"[a-z][a-z0-9_]{0,63}")), ("input_hash", digest)]),
    "c": ("payment", [("attempt_id", identity), ("payment_operation_id", identity), ("transaction_hash", digest)]),
    "d": ("result", [("attempt_id", identity), ("version_id", nullable(identity)), ("outcome", choice("succeeded", "refunded", "payment_failed"))]),
    "f": ("refund", [("attempt_id", identity), ("refund_operation_id", identity), ("transaction_hash", digest)]),
    "m": ("migration", [("migration_id", identity), ("authorization_hash", digest), ("inventory_hash", digest), ("recorded_at_ms", number), ("identities", number), ("publications", number)]),
    "z": ("seal", [("subject_id", identity), ("scope", choice("piece", "migration", "workspace", "identity", "trade")), ("event_set_hash", digest), ("event_count", lambda v: number(v, 1_000_000, 1))]),
}


def decode(memo):
    try:
        if not isinstance(memo, str) or not memo.startswith(PREFIX) or len(memo) > MAX_MEMO or not re.fullmatch(r"[\x20-\x7e]+", memo):
            raise ValueError()
        cells = json.loads(memo[len(PREFIX):])
        if not isinstance(cells, list) or not cells or not isinstance(cells[0], str) or cells[0] not in SCHEMAS:
            raise ValueError()
        kind, fields = SCHEMAS[cells[0]]
        if len(cells) != len(fields) + 1 or PREFIX + json.dumps(cells, separators=(",", ":"), ensure_ascii=True) != memo:
            raise ValueError()
        event = {"kind": kind, **{name: parse(value) for (name, parse), value in zip(fields, cells[1:])}}
        if kind == "version":
            event["purpose"] = "artwork" if event["purpose"] == "a" else "utility"
        return event
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError("INVALID_TRACE_EVENT") from None


def memo_hash(memo):
    decode(memo)
    return hashlib.sha256(memo.encode("ascii")).hexdigest()


def event_set(hashes):
    values = sorted(set(hashes))
    if any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value) for value in values):
        raise ValueError("INVALID_TRACE_HASH")
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode("ascii")).hexdigest(), len(values)
