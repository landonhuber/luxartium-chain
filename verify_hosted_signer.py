"""Disposable real-chain acceptance for isolated signer state, HTTP and replay."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import uuid

from gateway import BetaSigner, BETA_TREASURY, BETA_WELCOME, exclusive_process
from localnet import Network, run, UNIT, FEE
from verify import available_ports, require
from verify_beta_gateway import settled
from export_hosted_signer import export

LABEL = "org.luxartium.signer-test"
IMAGE = "luxartium-beta-signer:0.1.0"


def verify():
    identity = uuid.uuid4().hex[:12]
    network = Network("luxartium-check-" + identity, available_ports())
    container, volume = "luxartium-signer-check-" + identity, "luxartium-signer-check-" + identity + "-data"
    signer = None
    created_volume = False
    created_container = False
    token = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="luxartium-private-signer-check-") as temporary:
        directory = Path(temporary)
        try:
            if network.inspect("container", network.name) or network.inspect("volume", network.volume) or network.inspect("container", container) or network.inspect("volume", volume):
                raise RuntimeError("Disposable resource collision")
            network.init()
            network.start()
            signer = BetaSigner(directory, network)
            settled(signer.initialize_beta)
            account = str(uuid.uuid4())
            delivery = {"account_id": account, "delivery_token": secrets.token_urlsafe(32)}
            original_wallet = signer.beta_provision(delivery)
            genesis = signer.fingerprint
            def operation(kind, source, destination, amount):
                op = str(uuid.uuid4())
                return {"operation_id": op, "kind": kind, "from_account_id": source,
                        "to_account_id": destination, "amount_uluxar": str(amount),
                        "reference_hash": hashlib.sha256(op.encode()).hexdigest(),
                        "reverses_operation_id": None, "genesis_hash": genesis}
            grant = operation("grant", None, account, BETA_WELCOME)
            original_grant = settled(lambda: signer.beta_operation(grant))
            genesis = signer.fingerprint
            # A consistent journal and selective keys, never the validator's whole volume.
            signer.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            signer.db.close()
            signer = None
            (directory / "access.key").write_text(token, encoding="ascii")
            exported_directory = directory / "private-export"
            export_report = export(directory, exported_directory, genesis, network)
            require(export_report["exported_keys"] == 2, "selective exporter includes treasury and beta wallet only")
            try:
                BetaSigner(directory, network)
                raise AssertionError("Fenced source was permitted to restart")
            except ValueError as error:
                require(str(error) == "SIGNER_MIGRATED_USE_CURRENT_HOST", "source fence survives restart")
            run(["docker", "volume", "create", "--label", LABEL + "=" + identity, volume])
            created_volume = True
            mount = ["--mount", f"type=volume,source={volume},target=/state"]
            helper = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", *mount,
                      "--entrypoint", "python", IMAGE, "-c"]
            # New Docker volumes inherit the image's /state UID 10001 permissions.
            for filename in ("settlements.sqlite", "access.key"):
                import base64
                encoded = base64.b64encode((exported_directory / filename).read_bytes()).decode()
                run(helper + ["import base64,sys,pathlib; p=pathlib.Path('/state/'+sys.argv[1]); p.write_bytes(base64.b64decode(sys.stdin.read())); p.chmod(0o600)", filename], input_text=encoded)
            for exported_key in json.loads((exported_directory / "beta-keys.private.json").read_text()):
                name, private = exported_key["name"], exported_key["private_key_hex"]
                result = run(["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", *mount,
                              "--entrypoint", "luxartiumd", IMAGE, "keys", "import-hex", name,
                              "--keyring-backend", "test", "--home", "/state/keys"], input_text=private + "\n", check=False)
                del private
                require(result.returncode == 0, "selective beta key import")
            run(["docker", "run", "-d", "--name", container, "--label", LABEL + "=" + identity,
                 "--network", "container:" + network.name, "--read-only", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "256m", "--cpus", "1",
                 *mount, "-e", "LUXARTIUM_GENESIS_HASH=" + genesis, IMAGE])
            created_container = True
            def request(path, body, *, authorized=True, origin=None):
                program = """import sys,json,urllib.request,urllib.error
p=json.load(sys.stdin)
h={'Content-Type':'application/json'}
if p['token']: h['Authorization']='Bearer '+p['token']
if p['origin']: h['Origin']=p['origin']
r=urllib.request.Request('http://127.0.0.1:4175'+p['path'],data=json.dumps(p['body']).encode(),headers=h)
try:
 with urllib.request.urlopen(r,timeout=40) as response: print(json.dumps({'status':response.status,'body':json.load(response)}))
except urllib.error.HTTPError as response: print(json.dumps({'status':response.code,'body':json.load(response)}))
"""
                result = run(["docker", "exec", "-i", container, "python", "-c", program],
                             input_text=json.dumps({"path": path, "body": body, "token": token if authorized else None, "origin": origin}))
                return json.loads(result.stdout)
            for attempt in range(30):
                try:
                    health = request("/beta/health", {})
                    if health["status"] == 200:
                        break
                except RuntimeError:
                    pass
                time.sleep(.3)
            else:
                raise AssertionError("Isolated signer did not become ready")
            require(health["body"]["genesis_hash"] == genesis, "pinned chain health")
            require(request("/beta/health", {}, authorized=False)["status"] == 403, "unauthenticated request denied")
            require(request("/beta/health", {}, origin="https://aiartfoundry.com")["status"] == 403, "browser origin denied")
            for path in ("/health", "/wallet", "/operation", "/beta/health?x=1"):
                require(request(path, {})["status"] == 404, "legacy and nonexact routes denied")
            require(request("/beta/provision", {"account_id": "private-invalid-value", "delivery_token": "x" * 43})["body"] == {"error": "INVALID_BETA_REQUEST"}, "malformed input never echoed")
            same = request("/beta/operation", grant)
            require(same["status"] == 200 and same["body"]["transaction_hash"] == original_grant["transaction_hash"], "migration retains original grant bytes")
            require(request("/beta/wallet", {"account_id": account})["body"]["address"] == original_wallet["address"], "migrated wallet preserved")
            receipt = request("/beta/enroll", {**delivery, "acknowledge": False})["body"]
            require(len(receipt.get("private_key_hex", "")) == 64, "private delivery only through original enrollment secret")
            del receipt
            request("/beta/enroll", {**delivery, "acknowledge": True})
            require("private_key_hex" not in request("/beta/enroll", {**delivery, "acknowledge": False})["body"], "acknowledgement survives hosted delivery")
            action = {**grant, "operation_id": str(uuid.uuid4()), "kind": "action", "from_account_id": account, "to_account_id": None, "amount_uluxar": str(UNIT)}
            pending = request("/beta/operation", action)["body"]
            require(pending["state"] in ("pending", "committed"), "real isolated signature broadcast")
            run(["docker", "restart", container])
            time.sleep(1)
            paid = settled(lambda: request("/beta/operation", action)["body"])
            require(paid["transaction_hash"] == pending["transaction_hash"], "restart preserves exact signed bytes")
            require(int(request("/beta/wallet", {"account_id": account})["body"]["balance_uluxar"]) == BETA_WELCOME - UNIT - FEE, "one exact creative payment plus gas")
            fresh = str(uuid.uuid4())
            fresh_delivery = {"account_id": fresh, "delivery_token": secrets.token_urlsafe(32)}
            new_wallet = request("/beta/provision", fresh_delivery)
            require(new_wallet["status"] == 200 and new_wallet["body"]["balance_uluxar"] == "0", "fresh isolated wallet provisioned without a grant")
            fresh_grant = operation("grant", None, fresh, BETA_WELCOME)
            funded = settled(lambda: request("/beta/operation", fresh_grant)["body"])
            require(request("/beta/operation", fresh_grant)["body"]["transaction_hash"] == funded["transaction_hash"], "fresh welcome grant is exact-byte idempotent")
            require(request("/beta/operation", operation("grant", None, fresh, BETA_WELCOME))["status"] == 409, "another welcome identity cannot double-fund")
            # Restart the actual node while its signer sidecar holds the namespace.
            run(["docker", "restart", network.name])
            network.wait_height(2)
            # Docker gives the node a new network namespace. Reattach the sidecar;
            # the operator reconciler performs the same ordered recovery in service.
            run(["docker", "restart", container])
            for attempt in range(30):
                try:
                    if request("/beta/health", {})["status"] == 200:
                        break
                except RuntimeError:
                    pass
                time.sleep(.3)
            else:
                raise AssertionError("Sidecar could not reattach after node restart")
            require(True, "ordered node/signer restart restores loopback namespace")
            require(request("/beta/wallet", {"account_id": fresh})["body"]["balance_uluxar"] == str(BETA_WELCOME), "node restart preserves one fresh wallet grant")
            facts = network.inspect("container", container)
            require(len(facts["Mounts"]) == 1 and facts["Mounts"][0]["Name"] == volume, "only isolated signer state mounted")
            require(facts["HostConfig"]["ReadonlyRootfs"] and not facts["HostConfig"].get("PortBindings"), "read-only runtime with no exposed ports")
            print("PASS isolated hosted signer: selective keys, pinned existing state, private HTTP, legacy rejection, enrollment, one real payment, restart replay; validator volume never mounted.")
        finally:
            if signer:
                signer.db.close()
            if created_container:
                facts = network.inspect("container", container)
                if facts and facts["Config"]["Labels"].get(LABEL) == identity:
                    run(["docker", "rm", "-f", container])
            if created_volume:
                facts = network.inspect("volume", volume)
                if facts and facts["Labels"].get(LABEL) == identity:
                    run(["docker", "volume", "rm", volume])
            if network.inspect("container", network.name):
                network.require_owned("container", network.name)
                run(["docker", "rm", "-f", network.name])
            if network.inspect("volume", network.volume):
                network.require_owned("volume", network.volume)
                run(["docker", "volume", "rm", network.volume])


if __name__ == "__main__":
    verify()
