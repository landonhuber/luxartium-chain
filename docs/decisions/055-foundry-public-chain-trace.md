# Decision 055: Typed Foundry public application trace

Authorized by the Foundry owner on 2026-09-20 as part of the complete Alpha-to-beta
testnet transition. This extends decision 053 with the sixth authenticated POST
route `/beta/trace`. It changes no chain binary, genesis, validator, coin supply,
account cap, public listener, key delivery, custody or existing payment economics.

Each request has exactly `operation_id`, pinned `genesis_hash`, and a canonical
`foundry:t1:` memo. `trace_protocol.py` defines fourteen strict tuple kinds shared
with Foundry's pure TypeScript codec. All are bounded to 256 printable ASCII bytes.
There is no arbitrary memo or arbitrary object payload. The event publishes public
IDs, hashes, timestamps and allowlisted enums; never secrets or raw inputs.

The sole writer signs a one-uluxar treasury self-transfer with its normal
1,000-uluxar fee. It journals exact signed bytes before broadcast. The same operation
replays those bytes; changing the body conflicts. A durable unique memo-hash binding
refuses the same event under another operation ID, even after restart. Treasury
self-transfers lose only the network fee.

Only successful transfers signed by the separately pinned Foundry attestor treasury
are authoritative application events. Another wallet's matching memo is not an
ownership statement. `trace_verifier.py` reads raw transaction bytes and block
inclusion from a selected public RPC, parses the native transfer/fee, checks genesis,
and reconstructs graph and sealed event sets without Foundry database access.
The RPC is an explicit trust boundary; this is not a consensus light client.
A downloaded proof is a historical sealed snapshot, not proof that no later
transfer has occurred. Current ownership requires checking newer chain events.

The signer enforces protocol shape and issuance identity; Foundry core enforces
permission, ownership, offers and durable semantic state. The independent verifier
checks identity/version ancestry, creator ownership, exact rental sources, actual
sale/rental/action/refund payments, previous ownership references, source permissions,
creative results and seal dependency closure.

Existing journals upgrade additively with `beta_trace_events`. A journal with trace
intents and missing/inconsistent hash bindings refuses startup. All keys and current
SQLite state must be backed up together. The original source fence remains. New
software is installed only by the reviewed sole-writer upgrade procedure; a source
push does not upgrade a running signer.
