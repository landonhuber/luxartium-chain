"""Local, read-only Luxartium explorer. Uses public node HTTP APIs; never opens keys."""
from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

ASSETS = Path(__file__).resolve().parent / "operator-ui" / "explorer"
MAX_RESPONSE = 4 * 1024 * 1024
ADDRESS = r"luxar1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38}"
HASH = r"[A-Fa-f0-9]{64}"


class ExplorerError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def positive(value: str, maximum: int = 2**63 - 1) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > maximum:
        raise ExplorerError(400, "Use a valid positive block height or page number.")
    return int(value)


def block_summary(meta: dict) -> dict:
    header = meta["header"]
    return {"height": header["height"], "time": header["time"],
            "hash": meta["block_id"]["hash"], "transactions": meta["num_txs"],
            "proposer": header["proposer_address"]}


def tx_summary(tx: dict) -> dict:
    actions = [a["value"] for event in tx["tx_result"].get("events", [])
               if event["type"] == "message" for a in event.get("attributes", [])
               if a["key"] == "action"]
    return {"hash": tx["hash"], "height": tx["height"], "index": tx["index"],
            "code": int(tx["tx_result"].get("code", 0)), "actions": actions}


class ChainReader:
    def __init__(self, rpc_port: int = 26657, rest_port: int = 1317):
        self.rpc_port = rpc_port
        self.rest_port = rest_port
        # Fixed loopback destinations, no inherited proxy or upstream redirects.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def read(self, port: int, path: str, params: dict | None = None) -> dict:
        url = f"http://127.0.0.1:{port}/{path}"
        if params:
            url += "?" + urlencode(params)
        try:
            with self.opener.open(Request(url, headers={"Accept": "application/json"}), timeout=5) as response:
                payload = response.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                raise ExplorerError(502, "This node response exceeds the local explorer's size limit.")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("Expected object")
            if value.get("error"):
                raise ExplorerError(404, "The requested record is unavailable on this node.")
            return value
        except HTTPError as error:
            if error.code in (400, 404):
                raise ExplorerError(error.code, "The requested record was not found or the address is invalid.") from None
            raise ExplorerError(502, "The node could not answer this query.") from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise ExplorerError(503, "The local node is unavailable. Start Luxartium and try again.") from None
        except (ValueError, UnicodeError):
            raise ExplorerError(502, "The node returned an unreadable response.") from None

    def rpc(self, method: str, params: dict | None = None) -> dict:
        return self.read(self.rpc_port, method, params)["result"]

    def rest(self, path: str, params: dict | None = None) -> dict:
        return self.read(self.rest_port, path, params)

    def transactions(self, query: str = "tx.height>=1", page: int = 1, limit: int = 12) -> dict:
        result = self.rpc("tx_search", {"query": json.dumps(query), "page": page,
                                       "per_page": limit, "order_by": '"desc"'})
        return {"items": [tx_summary(tx) for tx in result.get("txs") or []],
                "total": result["total_count"], "page": page, "page_size": limit}

    def blocks(self, before: int | None = None) -> dict:
        status = self.rpc("status")["sync_info"]
        latest, earliest = int(status["latest_block_height"]), int(status["earliest_block_height"])
        height = min(before, latest) if before is not None else latest
        if height < earliest:
            raise ExplorerError(404, "This block is outside the node's retained history.")
        minimum = max(earliest, height - 11)
        result = self.rpc("blockchain", {"minHeight": minimum, "maxHeight": height})
        return {"items": [block_summary(meta) for meta in result.get("block_metas") or []],
                "latest": str(latest), "earliest": str(earliest),
                "next_before": str(minimum - 1) if minimum > earliest else None}

    def overview(self) -> dict:
        status = self.rpc("status")
        supply = self.rest("cosmos/bank/v1beta1/supply/by_denom", {"denom": "uluxar"})["amount"]
        validators = self.rpc("validators", {"per_page": 1})
        return {"chain_id": status["node_info"]["network"], "height": status["sync_info"]["latest_block_height"],
                "time": status["sync_info"]["latest_block_time"], "catching_up": status["sync_info"]["catching_up"],
                "supply": supply, "validators": validators["total"], "blocks": self.blocks(),
                "transactions": self.transactions(limit=6)}

    def block(self, height: int) -> dict:
        result = self.rpc("block", {"height": height})
        block = result["block"]
        txs = block["data"].get("txs") or []
        return {"hash": result["block_id"]["hash"], "header": block["header"],
                "transactions": [hashlib.sha256(base64.b64decode(tx, validate=True)).hexdigest().upper() for tx in txs]}

    def account(self, address: str) -> dict:
        balance = self.rest(f"cosmos/bank/v1beta1/balances/{address}/by_denom", {"denom": "uluxar"})["balance"]
        # Both searches are bounded. Keep this explicitly recent indexed activity,
        # rather than claiming a complete account ledger or a transfer-only history.
        sent = self.transactions(f"message.sender='{address}'")
        received = self.transactions(f"transfer.recipient='{address}'")
        unique = {tx["hash"]: tx for tx in sent["items"] + received["items"]}
        activity = sorted(unique.values(), key=lambda tx: (int(tx["height"]), int(tx["index"])), reverse=True)[:12]
        return {"address": address, "balance": balance, "transactions": activity,
                "activity_limit": 12}

    def api(self, path: str, query: dict[str, list[str]]) -> dict:
        allowed = {"/api/blocks": {"before"}, "/api/transactions": {"page"}}.get(path, set())
        if any(key not in allowed or len(values) != 1 for key, values in query.items()):
            raise ExplorerError(400, "Unsupported query parameters.")
        if path == "/api/overview":
            return self.overview()
        if path == "/api/blocks":
            return self.blocks(positive(query["before"][0]) if "before" in query else None)
        if path == "/api/transactions":
            return self.transactions(page=positive(query.get("page", ["1"])[0], 100_000))
        if match := re.fullmatch(r"/api/block/([1-9][0-9]{0,18})", path):
            return self.block(positive(match[1]))
        if match := re.fullmatch(r"/api/tx/(" + HASH + r")", path):
            return self.rest("cosmos/tx/v1beta1/txs/" + match[1].upper())
        if match := re.fullmatch(r"/api/account/(" + ADDRESS + r")", path):
            return self.account(match[1])
        raise ExplorerError(404, "That explorer route does not exist.")


class ExplorerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, reader: ChainReader | None = None):
        self.reader = reader or ChainReader()
        super().__init__(("127.0.0.1", port), ExplorerHandler)


class ExplorerHandler(BaseHTTPRequestHandler):
    server_version = "LuxartiumExplorer/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Avoid recording user search strings or node payloads in server logs.
        pass

    def reply(self, status: int, payload: bytes, content_type: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json(self, status: int, data: dict):
        self.reply(status, json.dumps(data).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in hosts or (origin is not None and origin != "http://" + self.headers.get("Host", "")):
            self.json(403, {"error": "This explorer is available only from its local origin."})
            return
        try:
            if len(self.path) > 512:
                raise ExplorerError(414, "The request is too long.")
            url = urlsplit(self.path)
            if url.scheme or url.netloc:
                raise ExplorerError(400, "Use a local explorer path.")
            if url.path.startswith("/api/"):
                data = self.server.reader.api(url.path, parse_qs(url.query, keep_blank_values=True, max_num_fields=4))
                self.json(200, data)
                return
            files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                     "/style.css": ("style.css", "text/css"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            if url.path not in files or url.query:
                raise ExplorerError(404, "That page does not exist.")
            name, content_type = files[url.path]
            self.reply(200, (ASSETS / name).read_bytes(), content_type + "; charset=utf-8")
        except ExplorerError as error:
            self.json(error.status, {"error": str(error)})
        except (ValueError, KeyError, TypeError, OSError):
            self.json(502, {"error": "Explorer data is temporarily unavailable. Try again."})

    def do_POST(self):
        self.json(405, {"error": "The explorer is read-only."})

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


def serve(port: int = 4173):
    if port < 1024 or port > 65535:
        raise ValueError("Choose an explorer port between 1024 and 65535.")
    with ExplorerServer(port) as server:
        print(f"Luxartium explorer: http://127.0.0.1:{port} (read-only; Ctrl+C to stop)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
