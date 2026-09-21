# Trace signer upgrade and verification

Prepared 2026-09-20. Implementation does not imply a hosted upgrade or live artwork
transactions. Execute this procedure only as the coordinated reviewed release.

## Contract

`POST /beta/trace` uses the same Access, bearer, pinned host, Origin rejection and
bounds as the five existing routes. Body has exactly `operation_id` (UUID),
`genesis_hash` (lowercase hex64) and `memo` (canonical printable ASCII t1 tuple).
The response is the existing pending/committed/failed beta receipt shape. Confirmed
receipts must bind exact operation/genesis/memo, treasury sender and recipient,
amount `1` and fee `1000` uluxar. Foundry exposes
`BetaChainClient.trace(operation, treasuryAddress)`, `BetaChainTraceOperation`
and `validateBetaTraceReceipt`.

The fourteen event kinds are identity, version, ancestry, asset, publication,
permission, sale, rental, action, payment, result, refund, migration and seal.
Precise tuples are in `trace_protocol.py` and Foundry's `trace.ts`. Creative payment
is `["c",attempt_id,operation_id,tx_hash]`, with compact UUID22 and SHA-25643 cells.

## Controlled upgrade

The staged [PowerShell recipe](Upgrade-TraceSigner.ps1.example) defaults to a
read-only plan and requires `-Execute` for the coordinated upgrade. It pins the
reviewed image and existing node, locks recovery, backs up the entire stopped
signer volume under restrictive Windows ACLs, calls the existing reconciler and
checks all prior wallet/journal mappings. Its authoritative baseline comes from
the stopped volume, after recovery is disabled and external ingress is stopped;
it includes any already-admitted handler that finished during shutdown. Both the
post-ingress and offline checks reject unresolved pending operations before a
backup or configuration change. Post-upgrade validation failure stops
both owned sidecars and leaves scheduled recovery disabled. Its synthetic test
passed plan, upgrade, late-operation races, pending-operation refusal and
mapping-mismatch failure paths with all Docker, Python
and scheduled-task commands mocked. Independent operator review and actual
dedicated-host validation remain release steps; this is not a claim of deployment.

1. Record reviewed revisions, test evidence, image digest and unchanged chain-binary
   digest. Build only `hosted.Dockerfile`, including `trace_protocol.py`. Never replace
   the validator for this signer change.
2. Reconcile pending payments. Record current genesis, treasury, all wallet mappings
   and pending signed hashes. The previous 108-wallet report is not a current backup.
   Keep cap128 and the original laptop fence.
3. Disable **Luxartium Private Beta Signer Recovery** on the dedicated host. Coordinate
   `reconcile.lock`, let an active invocation finish, stop connector then signer and
   confirm both stay stopped. Never start a second writer.
4. Take a protected offline backup of the entire current signer volume: keys, bearer,
   SQLite journal and WAL/SHM together. Record its digest separately. Never combine
   old journals with current keys.
5. Change only the pinned signer image in the dedicated private operator configuration.
   Reconcile the sidecars against the existing node namespace. Startup additively
   creates the trace index; it never creates another treasury or wallet.
6. Verify current mappings, pending receipts, health, anonymous/access-only/Origin
   rejection, six-route allowlist and malformed trace rejection without a new operation.
   Then permit coordinated application release and the authorized trace batch.
7. Re-enable recovery on the dedicated host only. Record advancing height, unchanged
   validator uptime, exact revision/image and read reconciliation. Keep laptop fenced.

Website rollback leaves the signer/current journal intact. Signer rollback must
preserve all newer keys and journal state; never restore a pre-upgrade snapshot after
a new transaction. Pause trace dispatch before selecting an old signer image, since
it cannot emit trace events. Confirmed chain history is never rolled back.

## Independent public proof

Proof JSON has exactly `format: "foundry-trace-proof-v1"`, `chain_id`,
`genesis_hash`, `issuer_address`, `transactions` (unique uppercase transaction hashes),
`seals` (`transaction_hash`, `event_hashes`), and `subject` (`scope`, `id`).
Seal hashes are lowercase SHA-256 of exact memo strings. The verifier derives actual
transaction order from block height/index; caller array order is irrelevant. Include
referenced payment transactions and every recursive event dependency. Every supplied
seal requires a matching list. Migration seals verify declared identity/import counts.
Bounds: 100,000 transactions, 64 MiB proof file, 8 MiB RPC body, 64 KiB decoded tx.

```powershell
python trace_verifier.py proof.json --rpc http://127.0.0.1:26657 --genesis <pinned-genesis> --issuer <pinned-treasury> --check-latest
```

The RPC, genesis and issuer are operator trust inputs, not merely downloaded values.
The verifier independently checks successful raw transaction inclusion and transfer
parties. Reported owners apply to the supplied historical snapshot; check later
history before asserting current ownership. `--check-latest` performs that check:
it pins the current height, scans every attestor transaction up to that height,
and refuses a proof that omits a publication or sale for any reported piece.

Run focused Python tests, `python verify_beta_gateway.py` and `python verify_trace.py`
before release. The trace rehearsal uses unique owned disposable resources and
tests migration, rental permission, native branching, sale, refund, exact replay,
forged issuer, missing graph events, seal omission and chain restart. It removes
only those test resources. Evidence is written without secrets under ignored `build/`.
