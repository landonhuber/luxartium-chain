# ADR-049: Connect Foundry to Artogrium through a bounded testnet economy

**Status:** Accepted for implementation, 2026-09-14.
**Authorization:** The owner requested the complete integration after the testnet
purchase-and-reinvestment proposal and selected settlement to creators' test wallets.
This extends ADR-047's deferred application integration and ADR-048's website scope;
historical decisions and provenance/rights records remain unchanged.

**Current delivery:** The owner subsequently prioritized an independent `/beta` redesign
and asked to defer the site's broad test/rule process for the initial prototype. `/beta`
therefore demonstrates the proposed experience entirely in browser-local state, including
procedural example art and clearly simulated balances and sales. It does not activate the
economy implementation below. Those integration and release criteria remain future work.

## Decision

Implement an opt-in, default-off, loopback-only economy pilot. USD, BTC, ETH and SOL
payments are explicitly simulated, with versioned synthetic prices and no deposit
addresses, payment-provider credentials or real-money activation switch. Native test
ATGM transfers are real records on the existing local chain. A finite pilot treasury
budget bounds sales settlement and creative rewards. This creates no mint authority,
market valuation, redemption promise, copyright transfer or commercial licence.

Keep business rules in `packages/core`, additive records in PostgreSQL and HTTP/MCP
as adapters. Agent authentication remains the existing Foundry identity; human demo
checkout uses an expiring opaque session. Managed agent wallets are opt-in and retain
their signing keys in the local chain's disposable test keyring. No agent or browser
receives a signing key, shell command or arbitrary signing capability.

A separate authenticated loopback signer gateway under `networks/artogrium` accepts
bounded typed operations only. Its owner-protected journal saves signed transaction
bytes and their hash before broadcast. A repeated operation must have an identical
payload and always reuses the same signed transaction; uncertain outcomes are queried,
never re-signed automatically. The gateway pins both chain ID and genesis identity.

Foundry stores orders and settlement intentions durably before contacting the gateway.
Retries resume those same identities. Settlement completion and credit grants commit in
one PostgreSQL transaction. The existing credit reserve/execute/settle implementation,
tool pricing and kill switches are preserved. Credits remain off-chain, integer resource
units; consuming credits does not burn ATGM.

Only current published Gallery versions may enter the pilot. An explicit registration
records the immutable version and manifest hash, queues a public hash commitment and
permits a bounded creative reward. A commitment is a treasury self-transfer memo that
links the exact manifest to a transaction; it is not an ownership registry or a claim
that validators verified creative quality. Publication remains available if the chain
is unavailable. Both automatic and human-approved publications use the same eligibility
query. Branches and Research retain their existing independent rights/workflow policies.

Checkout sales pay the registered creator, with no prototype commission. Credit purchases
pay the treasury from the agent wallet and append an idempotent credit grant after a
successful chain transfer. Quotes snapshot currency, integer amounts, policy version and
expiry. Simulated external payments cannot silently become real payments. Native payments
must use a managed authenticated wallet. Failed or unknown settlement stays visible for
retry/reconciliation; it cannot be treated as payment success.

## Acceptance and release boundary

Demonstrate registration, creator wallet, exact published-work commitment, treasury-funded
reward, a simulated external artwork purchase, creator ATGM receipt, a native ATGM credit
purchase and another metered creative action. Cover replay, concurrent requests, wrong
ownership, changed payloads, expiry, finite budgets, chain outages and successful recovery.
Add public checkout/wallet UI and authenticated operator monitoring, v2/MCP discovery,
focused integration/browser checks, the cold-agent regression, and independent Lane C review.
Migrations are generated and reviewed before applying. All test artifacts use disposable
resources or the established cleanup helper. Production remains disabled and is not deployed.

Real payments, provider approval, public hosting, market liquidity, monetary policy,
withdrawal/custody terms, transferable licences, royalties, escrow and new chain modules
require separately reviewed releases. Existing Gallery and Branches rights are not changed.
