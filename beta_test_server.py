"""Disposable HTTP signer for native beta integration; stdout is private harness IPC."""
from contextlib import ExitStack, redirect_stdout
from http.server import ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import uuid

from gateway import BetaSigner, GatewayHandler, initialize_treasuries
from localnet import Network, run
from verify import available_ports
import welcome_policy


def main():
    network = Network('luxartium-check-' + uuid.uuid4().hex[:12], available_ports())
    try:
        with redirect_stdout(sys.stderr):
            network.init()
            network.start()
        with ExitStack() as stack:
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='foundry-beta-http-')))
            signer = BetaSigner(directory, network)
            stack.callback(signer.db.close)
            with redirect_stdout(sys.stderr):
                initialize_treasuries(signer)
            if os.environ.get('FOUNDRY_TEST_WELCOME_WATERFALL') == '1':
                profiles = os.environ.get('FOUNDRY_TEST_WELCOME_LEGACY_PROFILES', '[]')
                if len(profiles.encode()) > 16384:
                    raise ValueError('Disposable legacy profile input exceeds fixture bound')
                snapshot = {'version': 1, 'policy_id': welcome_policy.CAMPAIGN, 'genesis_hash': signer.fingerprint,
                            'legacy_profiles': json.loads(profiles)}
                digest = hashlib.sha256(welcome_policy.canonical(snapshot).encode()).hexdigest()
                welcome_policy.activate(signer.db, snapshot, digest, signer.fingerprint)
                signer.welcome_campaign = welcome_policy.initialize(signer.db, signer.fingerprint)
            server = stack.enter_context(ThreadingHTTPServer(('127.0.0.1', 0), GatewayHandler))
            key = secrets.token_urlsafe(32)
            server.signer = signer
            server.key_hash = hashlib.sha256(('Bearer ' + key).encode()).digest()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            # Consumed by the parent process, never forwarded to tool/user output.
            print(json.dumps({'url': 'http://127.0.0.1:' + str(server.server_port), 'key': key, 'genesis': signer.fingerprint,
                              'rpc_url': 'http://127.0.0.1:' + str(network.ports[0]),
                              'issuer_address': signer.beta_treasury(),
                              'welcome_policy': signer.beta_health()['welcome_policy']}), flush=True)
            sys.stdin.readline()
            server.shutdown()
            thread.join()
    finally:
        if network.inspect('container', network.name):
            network.require_owned('container', network.name)
            network.stop()
            run(['docker', 'container', 'rm', network.name])
        if network.inspect('volume', network.volume):
            network.require_owned('volume', network.volume)
            run(['docker', 'volume', 'rm', network.volume])
        print('Disposable beta HTTP signer and wallet volume cleaned up.', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
