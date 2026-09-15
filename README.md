# Luxartium chain

Luxartium's standalone blockchain engine, Docker node, local operator tools and
AI Art Foundry testnet signer. Native currency is **LUXAR**, with **six decimals**:
1 LUXAR = 1,000,000 `uluxar`. Genesis creates exactly **1,000,000,000 LUXAR**.
There is no mint module, mint authority or automatic inflation.

This is a working **single-validator local testnet**, not a public network or
mainnet. **Production is coming soon.** Test tokens have no promised monetary
value or mainnet conversion.

The public website and explorer are maintained separately in
[luxartium-site](https://github.com/landonhuber/luxartium-site) for
[luxartium.org](https://luxartium.org). This repository runs the chain; a Cloudflare
Worker hosts HTTP content and cannot run this persistent Go/CometBFT validator.

## Join the existing testnet

Download the [latest testnet release](https://github.com/landonhuber/luxartium-chain/releases/latest).
It includes `luxartium-testnet.zip`, a prebuilt Linux x86-64 Docker image and
`SHA256SUMS`. Docker Desktop runs that same Linux image on Windows x86-64.
Follow [the full-node guide](docs/join-testnet.md) to use the published genesis and
an operator-provided reachable peer. Joining generates your own node keys and
synchronizes the **same** chain; it does not create new LUXAR or grant validator
voting power. A seed reachable from the public Internet is not yet provided.

## Run a fresh independent development network

Install Docker with Linux containers enabled and Python 3.10 or newer. Node.js 22+
is needed only for the small local-console JavaScript check. All Python tools use
the standard library; Go is built inside the pinned Docker image.

```sh
git clone https://github.com/landonhuber/luxartium-chain.git
cd luxartium-chain
python localnet.py build
python localnet.py verify
python localnet.py init
python localnet.py start
python localnet.py status
```

On systems where Python is named `python3`, use that command throughout.
`build` downloads pinned dependencies, tests the Go application and builds
`luxartiumd`. The first build can take several minutes. `verify` uses its own
uniquely named Docker container and volume; it does not touch a saved chain.

`init` creates a new independent local history and refuses existing state, even
after interrupted initialization. It does **not** join somebody else's network.
To join the existing testnet instead, use `node.py join` as described above.
Validator onboarding remains separate. See [network settings](docs/network.md).

If this computer already runs the Foundry local chain, **skip `init`**. This
extraction preserves the same image identity, source fingerprint and Docker names.
Use `status` to read that existing chain. See [extraction and migration](docs/extraction.md)
before moving any running process.

```sh
python localnet.py stop
python localnet.py start
```

Stop preserves keys, balances and history in `luxartium-local-1-data`. Never delete
that volume to upgrade code. Source/image mismatches are refused; a protocol upgrade
needs an explicitly reviewed migration.

## Wallets and transfers

```sh
python localnet.py wallet alice
python localnet.py wallet bob
python localnet.py address alice
python localnet.py address bob
python localnet.py fund <alice-address> 100
python localnet.py send alice <bob-address> 12.5
python localnet.py balance <bob-address>
```

Replace address placeholders with the public addresses printed above. Amounts are
exact LUXAR values with at most six fractional digits. Balance output is integer
`uluxar`. Funding transfers existing faucet coins; it does not mint. A normal
operator transfer adds a fee of 0.001 LUXAR, paid in LUXAR and distributed through
the SDK's fee distribution module. [Fees and supply details](docs/network.md).

The SDK `test` keyring is unencrypted and intended only for disposable test funds.
Anyone controlling Docker can access those keys. Wallet creation suppresses seed
output. Never reuse a production wallet or place valuable funds here.

## Local operator console and Foundry signer

```sh
python localnet.py sites
```

The compatibility console serves public local information on `127.0.0.1:4172`, a
read-only explorer on `127.0.0.1:4173`, and a private workspace at
`http://admin.luxartium.localhost:4174/admin/`. In your own terminal,
`python localnet.py admin-key` prints the local operator login key. Do not paste
that key into an issue or commit it. All listeners are loopback-only; these Python
servers are not the public website hosting configuration.

`python localnet.py explorer --port 4183` serves only the local explorer.
The static console snapshot lives in `operator-ui/`; it is retained so operators
can inspect local nodes without a website checkout. Public site updates belong in
the separate website repository.

The optional `python gateway.py` starts Foundry's authenticated local signer on
`127.0.0.1:4175` and funds finite pilot/beta treasury wallets from the faucet. It
does not start a public service. [Signer integration and custody](docs/signer.md)
explains its private journal, replay rules, credential path and endpoint boundary.

## Develop and verify

```sh
python -m unittest discover -s . -p 'test_*.py' -v
node --test test_explorer_ui.mjs
python localnet.py build
python localnet.py verify
python verify_beta_gateway.py
python verify_join.py
```

These are the same checks run by GitHub Actions on pushes and pull requests.
The Docker build runs `go test -mod=readonly -p 4 ./...` and compiles the node.
Acceptance tests initialize separate chains, sign actual transfers, check exact
fees, pin genesis, verify replay, second-node synchronization and restart, then remove only their own labeled
test containers and volumes. Public evidence goes to ignored `build/` files.
No CI secret or saved wallet is required. CI does not deploy a node or publish an
image. `python verify_explorer.py` is an additional read-only check against an
already-running saved localnet with an existing transfer; it is not a CI prerequisite.

Source changes use branches and pull requests. Updating this GitHub repository
does not automatically replace a running validator. Pin a reviewed revision and
plan state migrations before changing an existing chain's binary.

## Source and license notices

The engine was extracted from `networks/luxartium` in AI Art Foundry without
modifying its protocol code or the running chain. The pinned stack is Cosmos SDK
v0.55.0 / CometBFT v0.40.0 with Go 1.26.8. Upstream application/CLI wiring retains
[NOTICE](NOTICE) and [LICENSE.cosmos-sdk](LICENSE.cosmos-sdk). That upstream
license notice does not grant a new license to unrelated original project code.
Historical decisions are preserved in [docs/decisions](docs/decisions); their
Foundry paths describe the source project at the time of the decision.
