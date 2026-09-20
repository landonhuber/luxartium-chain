# Public trace signer and verifier handoff — 2026-09-20

Implemented and locally verified; **not hosted or used for live artwork migration**.

Independent parent review returned **APPROVE for the signer component and pinned
image**: exact journal replay, atomic trace uniqueness, startup refusal, mirrored
14-kind codec, receipt validation and hosted route boundary. This approval does
not yet cover the operator upgrade recipe or the complete Foundry release.

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

- All **74 Python unit/HTTP checks** pass, including malformed tuple/privacy,
  missing journal uniqueness mapping, forged issuer, graph omissions/order,
  double-attributed payments and unrelated refunds.
- Foundry's focused `beta-chain` and `beta-trace` checks pass: fourteen independent
  tuple vectors plus negative cases, bounded/secret-safe client and exact receipts.
- `python verify_trace.py` passed on disposable network
  `luxartium-check-073ad4f0dcb6`, genesis
  `68827429bba32331000839835cb66163cea613eb3aad67a78bb5a7f78933348b`.
  Its 29-transaction public proof contains 24 trace events: two identities, two
  versions, two publications, exact rental permission, two creative attempts,
  successful result, refund and sale. It proved restart replay, currentness/stale
  proof detection, wrong genesis/issuer, omitted records/seals and node restart.
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

Use [the upgrade runbook](../TRACE-SIGNER-UPGRADE.md) only after the coordinated
application, migration and independent release review. No chain reset, live key
export, hosted update, production push or live trace transaction occurred here.

The companion [PowerShell recipe](../Upgrade-TraceSigner.ps1.example) has passed
syntax parsing and a synthetic execution test under ignored `build/` for the
read-only plan, controlled upgrade, changed-journal fail-closed, operations arriving
after preflight/during shutdown, and pending-operation refusal before backup or
configuration change. The authoritative baseline is read from the stopped volume. Every
Docker/Python/task command was mocked; fixtures contain no live credentials.
Actual hosted operation is still pending. Its backup preserves the current entire
volume; image restoration instructions explicitly forbid overwriting newer keys
or journal entries with an older snapshot.
