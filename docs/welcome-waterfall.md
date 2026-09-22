# Welcome waterfall signer

This is an additive signer/application campaign on the existing testnet. It does
not change the validator, binary, genesis, balances already issued, coin supply,
fees, custody, private key delivery or public trace protocol. The independent
native-module branch is not part of this release.

New profiles allocated after explicit activation receive the following immutable
entitlement. Ordinals 1–1000 receive 500 LUXAR, 1001–2000 receive 400, 2001–3000
receive 300, 3001–4000 receive 200 and 4001–5000 receive 100. Later profiles receive
zero. Total campaign grants are 1,500,000 LUXAR; 5,000 ordinary transfers cost an
additional 5 LUXAR in existing network fees. No money is minted.

## Contract

Foundry allocates a profile's ordinal transactionally in its database. The signer
does not infer one from wallet counts or request arrival order. Concurrent requests
may arrive out of order. The signer stores unique profile, account, operation and
campaign ordinal bindings, validates the fixed schedule, and cannot use one slot
twice. An abandoned slot is never recycled or renumbered.

`POST /beta/provision` retains `account_id` and `delivery_token`, adding optional
`welcome_grant` with exactly:

```json
{
  "agent_id": "<public profile UUID>",
  "operation_id": "<persistent grant operation UUID>",
  "policy_id": "welcome-waterfall-v1",
  "ordinal": "1001",
  "amount_uluxar": "400000000"
}
```

Positive campaign `/beta/operation` grants add `grant_authorization` with exactly
`policy_id`, `ordinal` and `amount_uluxar`, matching provision. All original
operation fields and signed memo syntax remain. Changed bodies conflict; retries
reconcile the original durable signed bytes. The amount and standard fee remain
bound to the actual bank transaction.

Legacy eligibility is a frozen list of **all prior profiles**, including those
without a beta wallet yet. Their provision authorization uses `legacy-flat-500`,
null ordinal and `500000000`. Their transfers retain the original body without
`grant_authorization`, preserving saved operation identities and exact replay.
After activation an unknown profile cannot request a flat legacy grant, and a
legacy profile cannot consume a new campaign slot.

Before activation, an explicitly valid legacy provision envelope is accepted
under the existing flat-grant/cap behavior without allocating a campaign slot.
This allows a newly deployed application to finish already accepted enrollments
while profile admission is frozen. Campaign envelopes still fail before activation.

Zero entitlements are durably allocated and provisioned but never sent to
`/beta/operation`. The existing `/beta/enroll` delivery/acknowledgement flow works
for a zero-balance wallet. There is no transaction, receipt or network fee for a
zero grant. The allocation's operation ID is reserved and cannot become another
kind of transfer or trace. After activation enrollment cannot create a wallet
without prior authorized provisioning. The obsolete 128 beta-wallet cap is
removed only when this explicit allocation authority is active; request byte,
concurrency, timeout and secret-delivery boundaries remain.

Hosted startup compares the journal's saved wallet addresses against one complete
public SDK keyring listing, rejecting malformed, missing or ambiguous identities.
It retains a separate direct treasury-key comparison and runtime per-wallet checks.
This avoids a new CLI process for each of thousands of accounts; it neither
exports private material nor weakens the pinned public wallet/address comparison.

`/beta/health` adds `welcome_policy`:

```json
{"state":"active","policy_id":"welcome-waterfall-v1","snapshot_hash":"<64 lowercase hex>","legacy_inventory_hash":"<64 lowercase hex>"}
```

Before activation it reports `state:legacy`, `policy_id:legacy-flat-500` and null
hashes. Foundry must compare active policy and frozen inventory hash before
explicitly reopening enrollment. Older compatible reads ignore the new field.

## Explicit cutover, not deployment-time inference

1. Pass focused/full Python, actual disposable signing and Foundry Worker checks,
   and independent review. Pin the resulting **signer-only** image. Preserve the
   old daemon image `sha256:bcf43413a0ea468c0fd6c48826e64cabe41366987d0a7e7fdbf406f6693ea272`
   and its binary hash `9e6525c54904c72f688b4c3d827ddda8fb7b1b0bdc938bd0ac395c1d5dcb6512`.
2. Apply the reviewed additive schema and set the admission limit to zero, then
   apply a **provisional** policy freeze. The old fixed-window admission limiter
   does not by itself reliably block the first request from a new IP at zero.
   Deploy the compatible application while frozen, verify its exact revision is
   serving 100%, and drain old requests. Invoke the new writer-aware freeze again
   to export the **final authoritative** public legacy inventory. Never activate
   the signer or application from a provisional inventory. Recheck all captured
   account/delivery bindings. Canonical JSON uses sorted object keys,
   compact separators and profiles sorted by UUID. Each row is exactly
   `{account_id:UUID|null,agent_id:UUID,operation_id:UUID|null}`. The `account_id`
   and `operation_id` bindings are both present or both null. Pin the SHA-256 of
   this array.
3. Wrap the array in `{version:1,policy_id:"welcome-waterfall-v1",genesis_hash,
   legacy_profiles:[...]}` and pin its separate canonical SHA-256. The CLI checks
   the complete wrapper; health publishes both wrapper and inventory hashes.
4. Use `docs/Upgrade-WelcomeSigner.ps1.example`, with the reviewed exact image,
   final snapshot path, wrapper hash and inventory hash. Its default read-only
   plan validates the public snapshot; `-Execute` performs the cutover only after
   the final application freeze has been verified. It follows the hosted
   single-writer procedure: disable recovery, acquire its
   reconciler lock, stop connector ingress, obtain a fresh baseline and require
   no signed pending operations, stop signer, and back up the entire current
   signer volume including keys, journal and campaign records. Preserve the
   source-laptop fence. Never restore an old journal after new signatures exist.
5. Stage the new signer image and public snapshot. With the signer still stopped,
   run the image's `activate_welcome_policy.py` as the same unprivileged UID against
   the same signer state volume. Default validates an in-memory copy:

   ```sh
   python /app/activate_welcome_policy.py --directory /state --snapshot /run/welcome-snapshot.json --snapshot-sha256 <wrapper-sha256> --genesis <preserved-genesis>
   ```

   Repeat the exact invocation with `--apply` only for the coordinated activation.
   The snapshot is mounted read-only. No validator volume or key export is needed.
   The tool takes the same `gateway.lock`, requires existing state, checks every
   existing wallet/grant mapping, refuses pending operations or a migrated source,
   and refuses a different snapshot after activation. Exact activation replays.
6. Update only the hosted operator's pinned signer image and restart the same
   single signer/connector. Verify unchanged
   genesis, treasury, existing wallet mappings and daemon uptime; verify active
   policy and both exact hashes, then restore its existing recovery task. The old
   image must not be restored after campaign
   activation because it lacks the policy boundary. A website rollback may leave
   the new signer installed, but enrollment stays frozen until compatible.
7. Fund the campaign using the owner's existing faucet wallet, not the hosted
   signer. The approved top-up is 1,500,005 LUXAR. The original non-voting laptop
   still has the faucet key and can use standard CLI generation/signing against
   the preserved chain. Save and fsync the exact signed bytes/hash before broadcast;
   an uncertain response must query/rebroadcast those bytes, never re-sign.
   No faucet key is copied to the signer or dedicated validator. Use one protected
   operator directory for the campaign and `fund_welcome_campaign.py`:

   ```powershell
   python fund_welcome_campaign.py plan --directory <protected-campaign-directory>
   python fund_welcome_campaign.py prepare --directory <same-directory>
   python fund_welcome_campaign.py broadcast --directory <same-directory>
   python fund_welcome_campaign.py verify --directory <same-directory>
   ```

   `plan` is read-only; `prepare` signs but cannot broadcast. `broadcast` first
   queries the saved hash and only sends the exact saved bytes when unconfirmed.
   A lost response is recovered with `verify` or the same `broadcast` command.
   Never use another directory to prepare a replacement funding transaction.
   Partial preparation or a failed receipt requires operator reconciliation;
   no path silently creates a new signature. This is a standard bank transfer,
   not an on-chain campaign mint or a new faucet authority.
8. Verify funding receipt/balances and deployment, compare active signer inventory
   to the same final Foundry freeze, and explicitly activate the matching
   application policy **while admissions remain frozen**. Verify its matching
   hashes and only then explicitly unfreeze the application policy. Restore the
   normal admission limit of 15 only after those checks and
   unfreeze have succeeded. Do not silently resume flat grants on an incompatible
   deployment.

Activation writes new SQLite tables plus a policy marker/count in the existing
identity table. Startup rejects missing campaign tables, a changed snapshot,
missing allocations and wallets without policy bindings. Keys/journal/policy must
always be backed up and restored together. No HTTP endpoint activates the policy.

## Disposable verification

`python -m unittest discover -s . -p 'test_*.py' -q` covers exact schedule/budget,
concurrent allocation uniqueness, more than 128 wallets, legacy eligibility,
partial-restore refusal, same-byte replay/restart and zero funded key delivery.
`python verify_welcome_gateway.py` exercises actual five-tier transfers and a
zero-wallet enrollment on its own labeled chain, then cleans only owned resources.

The fixture-only `beta_test_server.py` supports
`FOUNDRY_TEST_WELCOME_WATERFALL=1` and optional bounded JSON
`FOUNDRY_TEST_WELCOME_LEGACY_PROFILES` (default `[]`). It activates the same policy
after disposable treasury initialization and before serving HTTP. The private IPC
handshake includes policy/hash status. Neither environment setting affects the
hosted runtime or authorizes production activation.

At the 2026-09-22 read-only baseline the live signer was the health-fixed
`sha256:b101ee0df9e10e534a25833eb4a97adf3ad3f5794f5e747aed255574133882ff`,
with 108 wallets, 108 grants and 4,178 committed operations. The earlier
`682c6d...` image in the initial trace handoff was subsequently superseded.
This document is a prepared procedure; no campaign funding or live activation
is claimed by its creation.

## Release acceptance recorded before activation

The reviewed signer-only candidate is
`sha256:9c44771b91b286f8722fd12b594f5cf10eb7c58641f380bb46dbfe42d2fb6f8c`.
The embedded daemon remains the exact old binary pinned above. The image runs as
UID 10001. Independent review matched the image's gateway, hosted signer, policy
and activation utility hashes to the reviewed source.

- Full local Python suite: **104 tests passed**. The final mount/generation
  guard's actual Windows mocked test was rerun after that suite and passed.
- Same-image focused Python: **33 tests passed** (policy, HTTP and hosted signer).
- Actual disposable waterfall: all five tier transfers, exact signed replay after
  restart and zero-funded key enrollment passed; only five real grant transfers
  and their ordinary fees existed. The owned chain was removed.
- Final same-image hosted acceptance: selective key migration, original fence and
  grants, private HTTP denial cases, actual paid action and trace, exact signed
  replay, signer restart and ordered isolated node/signer restart all passed.
  The owned `1e1dbbcb7bfc` containers and volumes were removed. A prior attempt
  timed out at Docker restart and was not counted as passing; its separately
  labeled resources were checked and removed before the successful rerun.
- Independent review: **APPROVE** for policy/recovery, batched public-key startup
  validation and the operator/funding slice. Eight operator tests cover durable
  funding replay and the actual Windows recipe with external commands mocked.
  Wrong state mounts, changed signer generations, pending transactions, wrong
  inventory hashes and failed activation cannot proceed to an unverified writer.

The candidate archive was staged and loaded on the dedicated host without
changing the configured or running signer, recovery task or validator. Its archive
SHA-256 is `57cc55a644ab0a2246595d5934f7495abce684ed708dacd8175898362ae62c05`.
This is image availability, not activation. The application deploy/gates, final
authoritative freeze inventory, consistent backup, funding and coordinated
activation/unfreeze remain separate release gates.
