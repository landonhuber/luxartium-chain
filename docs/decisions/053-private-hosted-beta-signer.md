# Decision 053: Private hosted Foundry beta signing

Accepted for implementation, 2026-09-19. The owner authorized the public native
Foundry beta goal. Release requires independent boundary review and acceptance.
This prospectively extends the local-only signer of decision 050; no chain protocol,
economics, genesis, validator or public explorer changes are part of this release.

The signer runs in a separate unprivileged read-only container. Its only persistent
mount contains the beta treasury/accounts, independent bearer credential and existing
SQLite operation journal. It has no Docker socket, validator volume, faucet key or
pilot keys. It uses the exact existing node binary (verified SHA-256); no chain
initialization or treasury funding is exposed by this runtime.

It shares the node's network namespace for loopback RPC and binds its own listener
only to 127.0.0.1:4175. A separate Cloudflared connector shares that namespace;
no signer port is published to the LAN or internet. Only five exact beta POST paths
are accepted, with bounded headers/body/response, timeout, concurrency limit,
independent bearer authentication and browser-Origin rejection. Other legacy signer
routes remain confined to the original local operator runtime.

The dedicated HTTPS hostname is foundry-signer-testnet.luxartium.org. Cloudflare
Access permits only a Foundry service token, and the tunnel validates the Access
application JWT before forwarding. Foundry pins this exact HTTPS destination,
rejects redirects and checks chain/genesis and receipt identities. Keys and request
bodies are never logged. The public explorer has no route to this signer.

The journal and selectively exported beta keyring move together under an exclusive
source lock. Source signing is fenced before destination activation. Startup refuses
missing state, a new treasury, unrelated keys or mismatched genesis; it never creates
a replacement network or faucet allocation. One signer is active. Rollback transfers
the latest journal and all newer beta keys back, rather than restoring a stale copy.

This remains managed testnet custody, not production wallet security or mainnet.
The operator OS/Docker administrators remain trusted. A stopped validator pauses
settlement; neither explorer fallback nor signer restart creates voting redundancy.
