# Local Foundry signer integration

The saved Foundry beta signer moved to the dedicated machine on 2026-09-20.
Its source journal is fenced. See [hosted operation and recovery](HOSTED-BETA-SIGNER.md)
before starting a signer; the local setup below describes development usage.

`gateway.py` is an optional trusted operator process, not a public wallet service.
It connects to the saved local chain and listens only at `127.0.0.1:4175`. Foundry
business rules, authentication, account records, jobs, ownership and artwork
storage remain in the separate AI Art Foundry application.

Start it from this repository after the chain is running:

```sh
python gateway.py
```

On first use it creates a protected credential and journal under
`~/.luxartium/gateway/` and funds finite pilot/beta treasuries by transferring
existing faucet coins. Windows paths use owner-only ACLs; POSIX paths use owner
permissions. The gateway prints public genesis information, never its access key.
The key file is `~/.luxartium/gateway/access.key`; read it privately in your own
terminal when configuring the Foundry server. Never embed it in frontend code.
Only one gateway process may use a journal directory at a time.

The current HTTP boundary requires an exact `Host: 127.0.0.1:4175`, bearer
authentication, no browser Origin, and bounded JSON POST bodies. GET is refused.
The supported native-beta routes are `/beta/health`, `/beta/provision`,
`/beta/enroll`, `/beta/wallet`, and `/beta/operation`. The legacy bounded pilot
routes remain `/health`, `/wallet`, and `/operation`. `test_beta_gateway.py` and
`verify_beta_gateway.py` are executable examples of request and receipt contracts.

Native operations support one 500 LUXAR welcome grant per account, 1 LUXAR action
payments, refunds, direct owner sale/rental payments, and manifest hash commitments.
Each durable operation ID binds to one exact payload and signed transaction.
The protected SQLite journal saves signed bytes before broadcast. Retrying reuses
those bytes and reconciles their chain result; it does not generate a new transfer.
The gateway verifies chain ID and genesis identity before signing/replay.

Enrollment supports bounded one-time private-key delivery and explicit backup
acknowledgement. The server still retains managed signing capability in the local
test keyring; key export is not exclusive user custody. No keys are emailed.

The server's presence alone does not implement marketplace ownership, licensing,
rentals or rankings. Those policies are enforced by Foundry core/database records
and must be connected to validated chain receipts. The gateway must remain private
while any remotely hosted Foundry integration is designed and reviewed. The local
development origin restrictions are deliberate and are not production hosting.

To verify the signer without touching saved wallets, run
`python verify_beta_gateway.py`. It creates a uniquely named disposable chain and
private temporary journal, checks actual transfers and replay, and removes its
own resources. Its `build/beta-gateway-verification.json` output contains public
addresses/hashes only and is ignored by Git.
