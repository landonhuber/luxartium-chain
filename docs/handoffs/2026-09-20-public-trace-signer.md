# Public trace signer and verifier handoff — 2026-09-20

Implemented, locally verified and **hosted through the coordinated additive
signer upgrade at 2026-09-20 20:41 UTC**. No live artwork trace or migration
transaction was sent by this component task.

Independent parent review returned **APPROVE for the signer component and pinned
image**: exact journal replay, atomic trace uniqueness, startup refusal, mirrored
14-kind codec, receipt validation and hosted route boundary. This approval does
not cover the complete Foundry release. The operator recipe separately received
REVISE for a pre-quiescence snapshot, then APPROVE after fresh post-ingress and
authoritative offline snapshots plus race/refusal tests were added.

The sixth private signer route `/beta/trace` accepts only operation UUID, pinned
genesis and a strict 256-byte ASCII `foundry:t1:` tuple. It signs a one-uluxar
treasury self-transfer, costs only the existing 1,000-uluxar network fee and uses the
existing durable exact-byte journal. A unique event-hash mapping rejects duplicate
events under different operation identities; missing mappings refuse restart.
Existing account cap128, key-delivery state, financial operations and source fence
remain intact. The hosted build now includes the standalone pure Python codec.

Foundry's client exports `BetaChainTraceOperation`, `validateBetaTraceReceipt` and
`BetaChainClient.trace`. The codec gained explicit creative-payment references as
the fourteenth event kind. Both sides enforce exact tuple sizes and canonical bytes.

`trace_verifier.py` independently fetches actual public transaction bytes and block
inclusion, validates pinned genesis/issuer/native transfer/fees, and replays typed
identity, ancestry, asset, ownership, permission, rental, payment/result/refund and
migration graphs. It verifies sealed set counts/hashes and dependency closure.
`--check-latest` scans attestor history through a pinned height and rejects omitted
ownership changes. It uses no Foundry database and no private signer credential.
The selected full-node RPC is trusted; this is not a consensus light client.

Verified evidence:

- All **75 Python unit/HTTP checks** pass, including malformed tuple/privacy,
  missing journal uniqueness mapping, forged issuer, graph omissions/order,
  double-attributed payments, unrelated refunds and publication-source binding
  to the actual Gallery artwork or successful native action workspace.
- Foundry's focused `beta-chain` and `beta-trace` checks pass: fourteen independent
  tuple vectors plus negative cases, bounded/secret-safe client and exact receipts.
- `python verify_trace.py` passed on disposable network
  `luxartium-check-6c9f3e6e400f`, genesis
  `4c5de29dc737f2067ff91806533cfc5a6824ac473fe7ae59465609c11a8a9604`.
  Its 29-transaction public proof contains 24 trace events: two identities, two
  versions, two publications, exact rental permission, two creative attempts,
  successful result, refund and sale. It proved restart replay, currentness/stale
  proof detection, wrong genesis/issuer, omitted records/seals and node restart.
  The final run also enforces the exact native workspace and Gallery artwork
  source links. Its final checkpoint is at height192, seal
  `D125CEC100E557B88239A8CF07C1B3D6FA8CF8C731469FBF15972C039171AC5B`.
  Public evidence is in ignored `build/trace-verification.json`.
- `python verify_hosted_signer.py --image luxartium-beta-signer:trace-review`
  passed selective key/journal export, source fence, private HTTP rejection,
  preserved enrollment/grants, paid action and trace replay across actual isolated
  container restarts, exact duplicate refusal, node namespace recovery and no
  validator-volume mount or exposed signer port.
- Local reviewed image ID:
  `sha256:682c6d2e6be6c1e9322e42319af6e5711b2ff147324b031c7d77eb707069fb87`.
  Embedded chain binary remains
  `9e6525c54904c72f688b4c3d827ddda8fb7b1b0bdc938bd0ac395c1d5dcb6512`.
- Owned disposable Docker chains, signer volumes and test keys were removed.
  An initial failed verifier run left only its stopped synthetic SQLite journal
  directory at `C:\Users\lando\AppData\Local\Temp\foundry-trace-cg3xaudn`.
  Explicit native PowerShell cleanup with resolved-path verification was rejected
  by automatic review with only “blocked by policy”; no workaround was attempted.
  The test harness now closes SQLite before automatic temporary-directory cleanup.

The earlier failures were test defects: a verifier tuple initialization typo,
CometBFT requiring JSON-quoted `order_by`, and a fixed one-second hosted restart
wait. The final code has strict regression cases and bounded health readiness.

The reviewed chain changes were committed and pushed to
`codex/testnet-alpha-transition` at `48131a9` before hosted activation. GitHub
pushes do not deploy this chain. The image contains the reviewed signer runtime;
later verifier-only assertions do not change that image.

The companion [PowerShell recipe](../Upgrade-TraceSigner.ps1.example) has passed
syntax parsing and a synthetic execution test under ignored `build/` for the
read-only plan, controlled upgrade, changed-journal fail-closed, operations arriving
after preflight/during shutdown, and pending-operation refusal before backup or
configuration change. The authoritative baseline is read from the stopped volume. Every
Docker/Python/task command was mocked; fixtures contain no live credentials.
The approved recipe then completed on the dedicated host using its existing
`py -3` reconciler. Its backup preserves the current entire volume; image
restoration instructions explicitly forbid overwriting newer keys or journal
entries with an older snapshot.

Hosted acceptance, all read-only except the controlled sidecar upgrade:

- Preserved **108 wallets and 110 operations**; zero pending operations and zero
  trace operations after all checks. SQLite `quick_check` passed.
- Protected offline backup:
  `C:\Users\lando\.codex\luxartium-beta-hosting-20260920\trace-upgrade-20260920T204151752Z`;
  archive SHA-256
  `8302ece1ef89cfe389c7f454a36843246934c27aebf89fd24901248fb335f463`.
- Same pinned genesis, treasury and validator container; validator started at
  `2026-09-20T01:59:23.172997469Z` and was not restarted. Heights advanced from
  `103919` to `103942`, catching up false, voting power `10000`.
- New signer image is the reviewed `682c6d2e...69fb87` ID above. Only
  `luxartium-beta-signer-state` is mounted. Recovery is enabled; last task result 0.
- HTTPS rejection/acceptance: anonymous 401, Access credential only 403, both
  credentials 200, browser Origin 403, legacy route 404, malformed trace 409 with
  `INVALID_TRACE_EVENT`. The malformed body created no journal entry or transaction.
- Original laptop signing fence parsed and remains present. Pinned SSH host
  fingerprint was verified. No source signer, second writer, chain reset, new
  validator, wallet rotation, Foundry release or live trace was performed.

Public readiness evidence is in ignored `build/hosted-trace-*.json` and
`build/hosted-trace-upgrade-result.txt`; no credentials or backup bytes are there.
