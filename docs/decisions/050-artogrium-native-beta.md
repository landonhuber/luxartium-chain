# ADR-050: Build the beta around native ATGM accounts and paid creative work

**Status:** Accepted for implementation, 2026-09-14.
**Authorization:** The product owner explicitly requested continued implementation until
the complete beta works: email/API signup with a private key and 500 ATGM, on-chain
creative actions, committed final work, owner-controlled rentals and sales, and branch ranking.

## Decision

This supersedes ADR-049's proposed beta journey, welcome allocation and key-delivery
restriction. It does not reinterpret historical Gallery, Branches or Research content.
New beta work is a separate, owner-controlled publication surface built over the existing
creative tools, immutable artwork versions, storage, authentication and metering.

- Humans register through the website and agents through the beta API. Each account
  records an email and receives one 500 ATGM grant from the finite existing testnet
  treasury. Replaying registration, changing clients or recovering an interrupted request
  must not create a second identity or grant. Email is never a public artist identifier.
- Signup delivers the account's API credential and native wallet private key directly
  to the signup caller, with explicit backup acknowledgement. Keys are not emailed,
  logged, returned by ordinary profile reads, or stored in browser local storage. An
  unacknowledged delivery can be recovered briefly only with the original high-entropy
  enrollment secret. Knowing an email or account ID cannot recover its keys.
- The local beta uses managed testnet signing so authenticated agents can run tools
  without putting a blockchain key into a tool payload. The server retains signing
  capability in the existing local test keyring; export is not a claim of exclusive
  user custody. This is explicitly disclosed when joining. Production custody and
  email delivery infrastructure are not implied by this local implementation.
- A creative action transfers 1 ATGM from its account to the Foundry treasury, records
  the exact logical action in its transaction memo, and runs through the same existing
  catalog validation, sandbox, `withMeteredTool`, and version commit. Native network
  fees are recorded separately. Reads and account navigation do not incur action fees.
  A failed action gets an idempotent refund; uncertainty must be reconciled before a
  replacement charge or execution. The existing resource ledger remains a safety
  budget, not a second currency sold alongside ATGM.
- Final commitment selects an immutable artwork version and anchors its manifest hash
  on the chain. A work cannot be offered while that commitment is unconfirmed.
- The current owner decides whether sale and/or rental is enabled and sets the prices.
  Renting pays that owner and grants one isolated continuation workspace from the exact
  committed source, preserving creator attribution. The original remains with its owner.
  Default rent is 10% of the latest completed sale, or the asking price before a first
  sale; a custom rent overrides it. Owners may also build on their own work.
- A confirmed sale pays the previous owner and transfers the exact committed version
  to its buyer. The new owner can enable rentals, set prices, retain it, or resell it.
  Pending payments reserve the relevant offer; a changed owner/price is never silently
  accepted. App ownership is enforced by core/database records bound to chain receipts;
  it is not described as a new NFT or consensus-enforced copyright instrument.
- Branch counts count committed direct continuations, not clicks, rental requests,
  failed actions or private drafts. Discovery ranks higher counts first and also exposes
  the complete ancestry and downstream impact.

## Settlement and rollout

The authenticated loopback gateway retains one signed transaction per durable operation
identity before broadcasting. Retries reuse the bytes and reconcile their chain result.
The journal and application pin both chain ID and genesis fingerprint. Accounts, grants,
refunds and payments have additional semantic uniqueness constraints. Every receipt
must match the expected sender, recipient, amount, operation, chain and exact bytes.
The beta treasury has a distinct wallet and a finite bootstrap transfer from the existing
faucet. No mint authority, chain reset or production deployment is introduced.

Database changes are additive and generated/reviewed before application. Historical
data and existing APIs remain available. Beta endpoints use canonical v2 envelopes;
human and agent adapters invoke the same core methods. The previous browser simulation
is replaced by authoritative server reads as each complete flow becomes executable.

## Completion evidence

Completion requires website and API signup; secret-delivery isolation and replay;
exactly one 500 ATGM grant; actual tool execution and action receipts on the chain;
recovery after interrupted execution; final-version commitment; rental-created lineage;
sales and subsequent owner-controlled rentals; correct default/custom prices; ranking
by committed branch counts; persistence across refresh/restart; and focused negative,
concurrency, browser, cold-agent and independent review checks. A functioning signer,
simulated balance, browsable tool catalog or green unit suite alone is insufficient.
