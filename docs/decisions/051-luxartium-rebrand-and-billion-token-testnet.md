# ADR-051: Luxartium and a billion-token local testnet

**Status:** Accepted for implementation, 2026-09-14.
**Authorization:** The owner explicitly requested that all Artogrium/ATGM sites and
integration code become Luxartium, short name luxar, and that the testnet be rebuilt
with a fixed starting quantity of 1,000,000,000 tokens. The owner also authorized
deleting the old test chain because the environment is test/beta.

## Decision

This supersedes the currency names and genesis allocation in ADR-047 through
ADR-050. Their historical documents retain their original names. Other decisions,
including the 500-token beta welcome grant in ADR-050, remain in effect.

Use Luxartium as the network/currency name, LUXAR as its ticker, `luxar` as its
display denomination, `uluxar` as its base denomination, and `luxar1…` for account
addresses. One LUXAR equals 1,000,000 uluxar. The local chain ID is
`luxartium-local-1`, the executable is `luxartiumd`, and the source lives under
`networks/luxartium`. The private operator origin is
`http://admin.luxartium.localhost:4174`.

Create a fresh genesis containing exactly 1,000,000,000 LUXAR
(1,000,000,000,000,000 uluxar): 100,000 LUXAR allocated to the validator, including
10,000 bonded, and 999,900,000 LUXAR allocated to the faucet. Faucet and Foundry
treasury distributions transfer existing coins. No mint module, mint authority,
or automatic inflation is added. Existing fee, slashing, and governance rules
remain; a fixed starting supply does not promise immunity from existing burns.

This is a new history with new test wallet keys and addresses. No old balances,
transactions, or private keys are represented as belonging to the new chain.
After validating the replacement, remove only the explicitly identified old local
container and its owned volume. Preserve the operator login credential separately;
it is not a blockchain key. Existing browser simulation records remain simulated
and display the updated currency; they are not converted to on-chain funds.

## Verification and boundary

Rebuild the image and run the Go configuration/persistence checks, focused operator,
HTTP isolation and exact-amount checks, and disposable-chain transfer/restart and
beta signer acceptance. Verify the saved new node's chain ID, genesis supply,
metadata, address prefix, progressing blocks, and absence of mint authority before
removing the old chain. Check the public home, explorer, admin login and beta UI
under their new branding, including the longer supply display.

The core economy draft remains disabled. No shared database migration, Foundry
agent-facing contract, existing metered creative execution, production chain, or
production deployment is changed by this cutover. Completion of this rebrand is
separate from the full native beta acceptance criteria in ADR-050.
