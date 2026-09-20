# Validator migration and explorer failover handoff

The existing testnet validator moved from the laptop to the dedicated Windows computer.
The laptop now follows the same chain as a non-voting backup. There is no protocol change,
new genesis, token issuance, wallet migration, or second active copy of the validator key.

## Verified cutover

- Both machines had the same pinned Docker image, genesis, and shared block history.
- The laptop validator stopped cleanly before its full offline config/data snapshot was made.
- Signing state and consensus WAL were included. Account wallet keyrings were excluded.
- Snapshot SHA-256 was checked after encrypted, pinned-host SSH transfer; restored files
  matched the archive before startup, except the deliberately changed networking config.
- The laptop received fresh consensus and P2P identities and restarted with voting power 0.
- Only after that live fencing check did the dedicated validator start. It committed blocks
  beyond the archived signing height 37846. Both nodes subsequently agreed on block and app hashes.
- The dedicated validator retains consensus address
  `01D7BDBDCAC4EE24E68C4AFB87ED2666FDEEC2DE`, power 10000, and P2P ID
  `d9c53a6dd0da926acb389aebf15748bb3f6e1a5c`.
- Laptop P2P ID is `c35c8900ed56c62395dde86d632fb2c6774784c8`, with power 0.
- An independence drill stopped only the laptop backup container. The dedicated validator
  advanced from height 39345 to 39353 and the Worker still served its primary origin. The
  laptop was then restored, synchronized at height 39360, and still had voting power 0.

Both active containers are named `luxartium-local-1` on their respective hosts. The previous
separate dedicated follower `luxartium-full-1` is stopped, restart disabled, volume retained.
The existing laptop wallet keys and Foundry signer journal were not moved or replaced.

## Recovery boundary

The private transfer archive is an **outdated signing-state snapshot** now that the dedicated
validator has signed later blocks. It is not a rollback image. Never restore it to start a
validator on either machine. A future validator move must first stop and fence the currently
active signer, then transfer its latest signing state and database together. Do not run the
same validator identity on two machines.

Private keys, archives, transfer scripts and tokens remain outside Git in restricted operator
directories. This handoff deliberately contains no credential payloads.

## Read hosting and startup

The public website is maintained separately in `luxartium-site`. Its Worker now has two
read origins: dedicated `testnet-primary-read.luxartium.org`, then laptop
`testnet-read.luxartium.org`. It pins chain identity and the first block, bounds all reads,
falls back on primary failure, and labels stale history instead of claiming new blocks exist.
The local browser verified Primary -> Backup -> Primary automatically on an immutable block
page while the dedicated validator continued running.

Dedicated read API and tunnel tasks run at Windows startup as limited LOCAL SERVICE. Only
allowlisted read routes are exposed, with raw RPC, REST, metrics and the adapter itself bound
to loopback. The Docker sign-in task completed with result 0, and the validator container uses
`unless-stopped`. Windows still requires `lando` to sign in after reboot so Docker Desktop can
start. A full Windows reboot was not tested. No laptop read-service autostart was installed.

Read failover does not keep consensus running if the dedicated machine is offline. The
laptop can serve retained history; the sole validator must return for new blocks to resume.
No automatic validator promotion, router port forwarding, public P2P bootstrap, additional
voting validator, or Windows automatic login was configured.

## Validation and review

Website type checks and all 29 tests passed, including Workerd integration. Dry-run build
passed. Independent review approved the migration, service boundary, and failover code.
A separate Workerd stalled-body probe failed over within 4.19 seconds. Browser testing
confirmed automatic source changes without navigating or reloading a block detail page.
See the website repository's `docs/TESTNET-CONNECTION.md` for service names and drill steps.

Website commit `5c8aecf` was pushed to main and its GitHub-triggered Cloudflare build
succeeded (active version prefix `24430d06`). Public API and browser checks confirmed
the dedicated primary, automatic backup selection when only its read API was stopped,
and automatic return after that service was restarted. Both services were restored;
the production network API still reports `PRODUCTION_COMING_SOON`.
