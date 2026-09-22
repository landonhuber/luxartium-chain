"""Offline welcome-policy activation. Stop ingress/recovery/signer and back up first.

This utility never signs, exports keys, funds a wallet, or modifies the validator.
Default mode validates a copy in memory; --apply is the explicit durable cutover.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from admin_auth import assert_plain_path
from gateway import exclusive_process
from welcome_policy import activate, canonical


def run(directory, source, expected_hash, genesis, apply=False):
    directory, source = directory.resolve(strict=True), source.resolve(strict=True)
    for path in (directory, source, directory / "settlements.sqlite"):
        assert_plain_path(path)
    fence = directory / "signing-moved.json"
    assert_plain_path(fence)
    if fence.exists():
        raise ValueError("SIGNER_MIGRATED_USE_CURRENT_HOST")
    if source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("WELCOME_SNAPSHOT_TOO_LARGE")
    value = json.loads(source.read_text(encoding="utf-8"))
    if hashlib.sha256(canonical(value).encode()).hexdigest() != expected_hash:
        raise ValueError("WELCOME_SNAPSHOT_HASH_MISMATCH")
    with exclusive_process(directory / "gateway.lock"):
        database = sqlite3.connect((directory / "settlements.sqlite").as_uri() + "?mode=rw", uri=True)
        database.row_factory = sqlite3.Row
        try:
            if database.execute("PRAGMA quick_check").fetchall()[0][0] != "ok" or database.execute("SELECT fingerprint FROM identity").fetchone()[0] != genesis:
                raise ValueError("WELCOME_JOURNAL_IDENTITY_MISMATCH")
            if apply:
                database.execute("PRAGMA synchronous=FULL")
                report = activate(database, value, expected_hash, genesis)
            else:
                with closing(sqlite3.connect(":memory:")) as copy:
                    copy.row_factory = sqlite3.Row
                    database.backup(copy)
                    report = activate(copy, value, expected_hash, genesis)
            return {"applied": apply, "genesis_hash": genesis, **report}
        finally:
            database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--genesis", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.directory, args.snapshot, args.snapshot_sha256, args.genesis, args.apply)))
    except Exception:
        raise SystemExit("Welcome policy activation refused. Verify frozen snapshot, sole-writer stop and journal; no keys were exported.")
