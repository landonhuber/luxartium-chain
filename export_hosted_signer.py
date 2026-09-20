"""One-time, offline selective beta migration. Output contains PRIVATE keys.

Stop the gateway first. The same exclusive lock refuses a running source process.
Keep the owner-only output off Git and transfer it only over pinned SSH. A source
fence is installed before export and remains after any error; never clear it once
the destination has accepted writes without transferring the latest state back.
"""
import argparse
from contextlib import closing
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

from admin_auth import assert_plain_path, set_owner_acl
from gateway import BetaSigner, BETA_TREASURY, canonical, exclusive_process
from hosted_signer import REQUIRED_TABLES
from localnet import Network, CHAIN_ID


def private_directory(directory):
    for part in (directory, *directory.parents):
        assert_plain_path(part)
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    if os.name == "nt":
        result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True)
        sid = next(csv.reader(result.stdout.strip().splitlines()))[1]
        if not re.fullmatch(r"S-1-[0-9-]+", sid):
            raise ValueError("OWNER_IDENTITY_UNAVAILABLE")
        set_owner_acl(directory, sid, directory=True)


def export(source, output, expected_genesis, network=None):
    source, output = source.resolve(strict=True), output.absolute()
    for candidate in (source, source / "settlements.sqlite", source / "access.key", source / "signing-moved.json"):
        assert_plain_path(candidate)
    if not re.fullmatch(r"[a-f0-9]{64}", expected_genesis):
        raise ValueError("PIN_EXPECTED_GENESIS")
    network = network or Network()
    with exclusive_process(source / "gateway.lock"):
        if (source / "signing-moved.json").exists():
            raise ValueError("SOURCE_ALREADY_FENCED")
        genesis = network.rpc("genesis")["result"]["genesis"]
        if genesis.get("chain_id") != CHAIN_ID or hashlib.sha256(canonical(genesis).encode()).hexdigest() != expected_genesis:
            raise ValueError("CHAIN_IDENTITY_CHANGED")
        key = (source / "access.key").read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", key):
            raise ValueError("EXISTING_ACCESS_KEY_REQUIRED")
        with closing(sqlite3.connect((source / "settlements.sqlite").as_uri() + "?mode=ro", uri=True)) as database:
            if database.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("INVALID_JOURNAL")
            for table, columns in REQUIRED_TABLES.items():
                database.execute(f"SELECT {columns} FROM {table} LIMIT 0")
            if database.execute("SELECT fingerprint FROM identity").fetchall() != [(expected_genesis,)]:
                raise ValueError("WRONG_JOURNAL_IDENTITY")
            treasury = database.execute("SELECT treasury_address FROM beta_config WHERE id=1").fetchone()
            if not treasury or network.address(BETA_TREASURY) != treasury[0]:
                raise ValueError("TREASURY_IDENTITY_CHANGED")
            wallets = database.execute("SELECT account,address FROM beta_wallets ORDER BY account").fetchall()
            selected = [(BETA_TREASURY, treasury[0]), *[(BetaSigner.key_name(account), address) for account, address in wallets]]
            if any(network.address(name) != address for name, address in selected):
                raise ValueError("WALLET_IDENTITY_CHANGED")
            private_directory(output)
            # Exclusive creation plus held process lock prevents a parallel exporter.
            with (source / "signing-moved.json").open("x", encoding="utf-8") as marker:
                marker.write(canonical({"destination": "dedicated private beta signer", "genesis_hash": expected_genesis}))
                marker.flush()
                os.fsync(marker.fileno())
            # Windows fsync maps to the durable file flush. POSIX also permits
            # explicitly flushing the directory entry before any keys leave.
            if os.name != "nt":
                directory_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(directory_fd)
                finally: os.close(directory_fd)
            with closing(sqlite3.connect(output / "settlements.sqlite")) as target:
                database.backup(target)
            (output / "access.key").write_text(key, encoding="ascii")
            exported = []
            for name, address in selected:
                result = network.cli(["keys", "export", name, "--keyring-backend", "test", "--unarmored-hex", "--unsafe", "--yes"], check=False)
                private_key = result.stdout.strip()
                if result.returncode or not re.fullmatch(r"[a-fA-F0-9]{64}", private_key):
                    raise ValueError("SELECTIVE_KEY_EXPORT_FAILED")
                exported.append({"name": name, "address": address, "private_key_hex": private_key})
            (output / "beta-keys.private.json").write_text(canonical(exported), encoding="utf-8")
            del exported
            for path in output.iterdir():
                if os.name != "nt": path.chmod(0o600)
            report = {"genesis_hash": expected_genesis, "wallets": len(wallets), "exported_keys": len(selected),
                      "journal_sha256": hashlib.sha256((output / "settlements.sqlite").read_bytes()).hexdigest(), "source_fenced": True}
            (output / "report.json").write_text(canonical(report), encoding="utf-8")
            return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--genesis", required=True)
    arguments = parser.parse_args()
    try:
        print(json.dumps(export(arguments.source, arguments.output, arguments.genesis)))
    except Exception:
        raise SystemExit("Signer export refused or incomplete. Inspect the source fence before retrying. No key material was printed.")
