"""Public network inputs and separation from the saved validator."""
import hashlib
import json
import unittest

from localnet import CHAIN_ID, DENOM, SUPPLY
from node import FullNode, peer_address, public_url, validate_genesis


class JoinTests(unittest.TestCase):
    def test_saved_validator_cannot_be_targeted(self):
        with self.assertRaises(ValueError):
            FullNode("luxartium-local-1")

    def test_public_downloads_cannot_send_credentials_or_downgrade_to_remote_http(self):
        for value in ("http://example.com/genesis.json", "https://user:secret@example.com/g", "file:///etc/passwd", "https://example.com/#key"):
            with self.assertRaises(ValueError):
                public_url(value)
        self.assertEqual(public_url("https://luxartium.org/testnet/genesis.json"), "https://luxartium.org/testnet/genesis.json")
        public_url("http://127.0.0.1:8080/genesis.json")

    def test_peer_requires_node_identity_and_bounded_host_port(self):
        valid = "a" * 40 + "@testnet.example.com:26656"
        self.assertEqual(peer_address(valid), valid)
        for value in ("testnet.example.com:26656", "a" * 40 + "@x:99999", "a" * 40 + "@x:1,other", "a" * 40 + "@x/path:1"):
            with self.assertRaises(ValueError):
                peer_address(value)

    def test_genesis_checksum_chain_denom_and_supply_are_pinned(self):
        genesis = {"chain_id": CHAIN_ID, "app_state": {"staking": {"params": {"bond_denom": DENOM}},
                   "bank": {"balances": [{"coins": [{"denom": DENOM, "amount": str(SUPPLY)}]}]}}}
        raw = json.dumps(genesis).encode()
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(validate_genesis(raw, digest), genesis)
        with self.assertRaises(ValueError):
            validate_genesis(raw + b" ", digest)
        genesis["chain_id"] = "another-chain"
        raw = json.dumps(genesis).encode()
        with self.assertRaises(ValueError):
            validate_genesis(raw, hashlib.sha256(raw).hexdigest())
        genesis["chain_id"] = CHAIN_ID
        genesis["app_state"]["mint"] = {}
        raw = json.dumps(genesis).encode()
        with self.assertRaises(ValueError):
            validate_genesis(raw, hashlib.sha256(raw).hexdigest())
