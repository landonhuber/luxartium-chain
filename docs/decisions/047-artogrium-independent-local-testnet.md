# ADR-047: Artogrium begins as an independent local sovereign testnet

**Status:** Accepted and implemented; local acceptance verified, 2026-09-13.
**Authorization:** The product owner requested a native Artogrium blockchain independent
of application economic design, then explicitly instructed implementation of the proposed
v0.1 testnet and wallet/transfer/native-fee/restart acceptance test.

## Decision

Keep the protocol in `networks/artogrium`, a separate Go module and local Linux process.
This narrowly extends ADR-001's TypeScript/npm runtime boundary for the explicitly requested
Cosmos SDK / CometBFT network. Docker provides Linux on the Windows development host. The
Foundry's existing npm development lanes do not acquire a chain dependency. No existing
application service is extracted, and no code imports between the chain and the Foundry.

The initial network is `artogrium-local-1`, with one locally controlled staking validator.
It is a functional sovereign development chain, not a decentralized or public testnet.
Accounts use the `artogrium` address prefix. Integer `uatgm` is the base denomination;
1 ATGM = 1,000,000 uatgm. Transfers and transaction fees use this native denomination.

Use the pinned Cosmos SDK v0.55.0 / CometBFT v0.40.0 stack. Adapt only the necessary
upstream application wiring; retain its license and attribution. Register auth, bank,
staking, distribution, slashing, evidence, consensus, genutil, governance and upgrade.
There is no mint module and no module has mint authority. Genesis creates 1,000,000 test
ATGM: 100,000 for the local validator (10,000 bonded), 900,000 for the local faucet.
The operator faucet transfers from its account, never mints. Fees follow SDK distribution;
testnet slashing/governance burn behavior is not a final monetary policy.

Governance authority controls supported parameter and upgrade messages. The single local
validator initially controls voting power; there is no public participation claim. The
upgrade module coordinates future software changes; future handlers and migrations must be
implemented and tested for each release. Unknown upgrade plans halt rather than being skipped.

Keys and chain state remain in a private Docker named volume outside Git. Local disposable
wallets use the SDK test keyring, explicitly unsuitable for valuable funds. RPC, REST and
gRPC publish only on host loopback (the container listeners serve Docker port forwarding).
Initializing an occupied volume is refused, and no reset/delete command
is supplied. Tests create and clean up only their own uniquely named container and volume.

## Scope and verification

The acceptance test creates two wallets, funds one from the faucet, signs and commits a
native transfer, measures the exact sender/recipient/fee changes, queries the transaction,
rejects invalid transactions, and verifies balances and continued blocks after restart.
It also verifies native metadata, stake denomination, supply and absent mint authority.

This is Lane C: include focused protocol tests, a live local integration test, a handoff,
and independent review. The existing Foundry cold-agent suite is not applicable because
the Foundry API, discovery, creative loop, publication path and their infrastructure are
unchanged. No shared Foundry database or existing ledger is used by these tests.

Proof of Creative Work, Studio Credit conversion, agent custody, artwork registration,
licensing, rewards, bridges, exchange trading, external hosting and production deployment
remain separate decisions. Test supply and balances make no mainnet allocation or redemption
promise. ADR-004 credit accounting, ADR-005 provenance and existing rights snapshots retain
their current authority. This release transfers no artwork or application truth onto a chain.
