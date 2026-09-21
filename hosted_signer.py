"""Beta-only signer sidecar. No Docker socket, validator volume or bootstrap path.

Run in the node's network namespace with only the separate /state volume mounted.
Cloudflared shares that namespace and authenticates Access before this listener.
"""
import hashlib
import hmac
from contextlib import closing
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import threading

from admin_auth import assert_plain_path
from gateway import BetaSigner, BETA_TREASURY, GatewayHandler, canonical, exclusive_process
from localnet import Network, CHAIN_ID

ROUTES = frozenset(("/beta/health", "/beta/provision", "/beta/enroll", "/beta/wallet", "/beta/operation", "/beta/trace"))
KEY_NAME = re.compile(r"(?:foundry-beta|b-[a-f0-9]{32})")
REQUIRED_TABLES = {
    "identity": "fingerprint",
    "operations": "id,payload,sender,recipient,amount,memo,signed,hash,state,result",
    "wallets": "agent,address",
    "beta_wallets": "account,address,delivery_hash,delivery_expires,acknowledged",
    "beta_grants": "account,operation",
    "beta_refunds": "original_operation,operation",
    "beta_intents": "operation,payload",
    "beta_config": "id,treasury_address",
}


class DirectNetwork(Network):
    """The signed binary is local; RPC is loopback inside the shared namespace."""
    def __init__(self, home=Path("/state/keys")):
        super().__init__()
        self.home = home

    def cli(self, args, *, check=True, input_text=None):
        # No agent input is ever executable code or a shell command.
        result = subprocess.run(["/usr/local/bin/luxartiumd", *args, "--home", str(self.home)],
                                input=input_text, text=True, encoding="utf-8", capture_output=True, timeout=30)
        if check and result.returncode:
            # CLI stderr can include signing material: never propagate it to HTTP/logs.
            raise RuntimeError("SIGNER_COMMAND_UNAVAILABLE")
        return result


class HostedBetaSigner(BetaSigner):
    def __init__(self, directory, expected_genesis, network=None):
        network = network or DirectNetwork(directory / "keys")
        path = directory / "settlements.sqlite"
        assert_plain_path(directory)
        assert_plain_path(path)
        if not path.is_file() or not re.fullmatch(r"[a-f0-9]{64}", expected_genesis):
            raise ValueError("EXISTING_SIGNER_STATE_REQUIRED")
        # Open existing state read-only first. Missing state must never initialize/fund.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as existing:
            if existing.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("SIGNER_JOURNAL_INVALID")
            tables = {row[0] for row in existing.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES.keys() <= tables:
                raise ValueError("SIGNER_JOURNAL_INCOMPLETE")
            for table, columns in REQUIRED_TABLES.items():
                # Both identifiers come only from the fixed operator-owned map above.
                existing.execute(f"SELECT {columns} FROM {table} LIMIT 0")
            identity = existing.execute("SELECT fingerprint FROM identity").fetchall()
            treasury = existing.execute("SELECT treasury_address FROM beta_config WHERE id=1").fetchone()
            if identity != [(expected_genesis,)] or not treasury:
                raise ValueError("SIGNER_STATE_IDENTITY_MISMATCH")
            wallets = existing.execute("SELECT account,address FROM beta_wallets").fetchall()
        genesis = network.rpc("genesis")["result"]["genesis"]
        if genesis.get("chain_id") != CHAIN_ID or hashlib.sha256(canonical(genesis).encode()).hexdigest() != expected_genesis:
            raise ValueError("CHAIN_IDENTITY_CHANGED")
        names = json.loads(network.cli(["keys", "list", "--keyring-backend", "test", "--output", "json"]).stdout)
        if not isinstance(names, list) or not names or any(not KEY_NAME.fullmatch(key.get("name", "")) for key in names):
            raise ValueError("UNRELATED_KEY_IN_SIGNER")
        if network.address(BETA_TREASURY) != treasury[0]:
            raise ValueError("TREASURY_IDENTITY_CHANGED")
        for account, address in wallets:
            if network.address(self.key_name(account)) != address:
                raise ValueError("WALLET_IDENTITY_CHANGED")
        super().__init__(directory, network)

    def stdin_cli(self, args, value):
        return self.network.cli(args, input_text=value).stdout.strip()

    def initialize(self):
        raise ValueError("HOSTED_BOOTSTRAP_FORBIDDEN")

    def initialize_beta(self):
        raise ValueError("HOSTED_BOOTSTRAP_FORBIDDEN")


class HostedHandler(GatewayHandler):
    def do_POST(self):
        # Reject duplicate security/framing headers before delegating the proven beta path.
        for name in ("Host", "Content-Length", "Content-Type"):
            if len(self.headers.get_all(name, [])) != 1:
                return self.reply(400, {"error": "INVALID_REQUEST_HEADERS"})
        if len(self.headers.get_all("Authorization", [])) > 1:
            return self.reply(400, {"error": "INVALID_REQUEST_HEADERS"})
        if self.path not in ROUTES:
            return self.reply(404, {"error": "UNSUPPORTED_BETA_ROUTE"})
        super().do_POST()

    def reply(self, status, data):
        if status == 409:
            # JSON/UUID exception strings must not echo submitted content.
            message = data.get("error", "")
            data = {"error": message if re.fullmatch(r"[A-Z][A-Z_]{2,70}", message) else "INVALID_BETA_REQUEST"}
        if len(canonical(data).encode()) > 65536:
            status, data = 503, {"error": "SIGNER_RESPONSE_LIMIT"}
        super().reply(status, data)


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(10)  # Bound request headers as well as the POST body.
        return request, address

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Never log payloads, credential headers or exception tracebacks.
        pass


def serve():
    directory = Path("/state")
    credential = directory / "access.key"
    assert_plain_path(credential)
    key = credential.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", key):
        raise ValueError("EXISTING_SIGNER_CREDENTIAL_REQUIRED")
    with exclusive_process(directory / "gateway.lock"):
        signer = HostedBetaSigner(directory, os.environ.get("LUXARTIUM_GENESIS_HASH", ""))
        with BoundedServer(("127.0.0.1", 4175), HostedHandler) as server:
            server.signer = signer
            server.key_hash = hashlib.sha256(("Bearer " + key).encode()).digest()
            del key
            print("Private beta signer ready; loopback only, existing journal verified.", flush=True)
            try:
                server.serve_forever()
            finally:
                signer.db.close()


if __name__ == "__main__":
    try:
        serve()
    except Exception:
        raise SystemExit("Private beta signer refused startup; verify pinned chain and existing signer state.")
