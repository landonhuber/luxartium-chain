# Private Foundry testnet signer — 2026-09-20

The dedicated Windows validator host also runs a separate managed test-wallet
signer. Foundry is hosted on Cloudflare and calls that service; wallet keys and
the durable signing journal reside on the dedicated machine, not in a Worker.
This changes neither the chain nor its validator set. The laptop is a non-voter.

## Boundary

- `luxartium-beta-signer` uses only `luxartium-beta-signer-state`; it has no
  validator volume, faucet key, Docker socket or published port.
- `luxartium-beta-tunnel` connects the exact private hostname
  `foundry-signer-testnet.luxartium.org` to `127.0.0.1:4175` in the node's network
  namespace. It validates the Cloudflare Access application JWT at the origin.
- The Access application admits one Foundry service credential. The signer also
  requires its independent bearer key. Browser Origin headers and legacy routes
  are refused. Public explorer tunnels cannot reach this service.
- The original laptop signer has a durable `signing-moved.json` fence. Never remove
  it to start another writer. The destination imported the existing treasury key
  and operation journal together; it did not bootstrap another treasury.

Chain: `luxartium-local-1`; canonical genesis SHA-256:
`dd59a7a33d4d2796e52f985ff913b1f158fe09fa2d044fc63b17d24d2c0d0707`.
Initial signer image:
`sha256:11465597fca45ee90659b341ded1ef5ac107b2877d5de43ba15ea18f12902f64`.
The pinned connector digest is recorded in `hosted_operator.py`.

## Startup and recovery

The Windows task **Luxartium Private Beta Signer Recovery** invokes the private
operator wrapper every minute while the operator is signed in. It runs
`hosted_operator.py --config <private operator-config.json>`. The reconciler
checks the exact node image, genesis and owned state volume. When the node's
network namespace changes, it recreates only the two sidecars against that node.
It never initializes, replaces or restarts the validator.

The operator configuration and tunnel token are in the owner's protected
`.codex/luxartium-beta-hosting-20260920` directory on the dedicated machine.
`operator-last-run.txt` contains a credential-free readiness result. Check the
scheduled task's last result, both sidecar states, current chain height and an
authenticated `/beta/health` request. A successful HTTP check alone does not prove
blocks are advancing. Do not log HTTP credentials, bodies or wallet delivery data.

Docker Desktop still requires the Windows operator to sign in after a restart.
The task does not provide unattended pre-login Docker startup. A validator outage
pauses new blocks because this testnet still has one voting validator; restarting
the signer or serving explorer history does not change that fact.

## Credentials, backups and rollback

The Access service credential expires **2027-09-20**. Rotate it before that date,
update the Foundry Worker secret pair privately, verify authenticated health, then
retire the old credential. Keep the independent signer bearer in the Worker's
secret store. Neither credential belongs in source, command arguments or browsers.

Before a signer update or host move, stop the connector, stop the signer and take
a protected offline backup of the entire signer volume, including every account
key and the latest SQLite journal. Record the pinned image, genesis and backup
digest separately. The original cutover export is not a current backup after new
accounts or operations exist. Restore only with the original writer stopped and
fenced. Never combine older journal state with newer keys or run two copies.

A website rollback can leave this private signer and its state intact. To move
signing back to the laptop, transfer the latest complete state first, validate all
wallet identities and pending operation receipts, fence the dedicated writer, and
only then activate one restored writer. Do not simply remove the laptop fence or
restore the original cutover snapshot.

## Verification

Seventeen focused Python tests pass. Disposable real-chain acceptance passed
selective export/import, durable source refusal, preserved addresses/grants,
transfer replay, signer restart and ordered node/sidecar recovery. Live checks
returned anonymous 401, Access-only 403, both credentials 200, browser-Origin 403
and legacy-route 404. The actual Foundry `BetaChainClient` in Workerd verified the
pinned chain and treasury over HTTPS. Stopping the signer and invoking its task
restored both sidecars without interrupting validator uptime.

See [decision 053](decisions/053-private-hosted-beta-signer.md) and the separate
Foundry repository's release handoff for application deployment evidence.
