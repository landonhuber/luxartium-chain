# Join Luxartium Testnet from another computer

**Testnet is available. Production/mainnet is coming soon.** This joins the same
chain as the founding node using its exact public genesis. It creates independent
keys for your full node and downloads existing blocks. Your node verifies and
serves that history; it does not automatically become a voting validator.

## Download and start

Prerequisites: Docker with Linux containers running, Python 3.10+, enough disk for
the chain history, and a network route to the peer provided by the operator.
The configured node allows 2 CPUs and 2 GiB RAM; Docker itself needs additional
host resources. Windows Docker Desktop and Linux x86-64 use the prebuilt image.
Other architectures can build the Dockerfile from the same source.

1. Download `luxartium-testnet.zip`, `luxartium-testnet-linux-amd64.docker.tar.gz`
   and `SHA256SUMS` from the [latest release](https://github.com/landonhuber/luxartium-chain/releases/latest).
2. Compare the downloaded hashes with `SHA256SUMS`. On Windows use
   `Get-FileHash <downloaded-file> -Algorithm SHA256`; Linux can use
   `sha256sum -c SHA256SUMS` from the folder containing both downloads.
3. Extract `luxartium-testnet.zip` and open a terminal in its
   `luxartium-testnet` directory. Load the downloaded image with Docker:

```sh
docker load -i /path/to/luxartium-testnet-linux-amd64.docker.tar.gz
```

If you prefer building, run `python localnet.py build` instead. That image contains
the same reviewed source; the first build takes several minutes.

4. Replace `YOUR_PEER_HOST` below with the founding node's LAN address or another
   reachable peer hostname supplied by its operator. The node ID shown is the
   current founding node's public identity. This is not a wallet/private key.

```sh
python node.py join --genesis https://luxartium.org/testnet/genesis.json --genesis-sha256 db5f3fce89288b58f0627f185197b3aa3c82aae72c0b4caf602134b34aeb6374 --peer d9c53a6dd0da926acb389aebf15748bb3f6e1a5c@YOUR_PEER_HOST:26656
python node.py start
python node.py status
```

On Linux, use `python3` where appropriate. The status contains `latest_block_height`,
`catching_up`, your node ID and `voting_power: "0"`. Initial synchronization can
take time. Compare a known block hash with the explorer or founding node to verify
you are following the same history. Local RPC is `http://127.0.0.1:26667/status`,
REST is `http://127.0.0.1:1327`, and gRPC is `127.0.0.1:9091`.

If ports need changing, supply the same global options when starting/querying:
`python node.py --rpc-port 26767 --rest-port 1427 --grpc-port 9191 start`.

Do **not** run `localnet.py init` to join. That creates a separate genesis.
Do **not** copy the founding validator's private key, chain volume or wallets.
`node.py join` refuses an existing full-node volume and never touches the saved
founding validator named `luxartium-local-1`.

## Pause and resume

```sh
python node.py stop
python node.py start
python node.py status
docker logs --tail 50 luxartium-full-1
```

State remains in the private Docker volume `luxartium-full-1-data`. The join command
is one-time initialization; use start after Docker/computer restarts. Do not remove
the volume unless you deliberately intend to lose that node's local state and keys.

## Same LAN versus a Linux cloud host

For a second computer on the same LAN, the founding operator must allow inbound
TCP26656 through the host firewall and publish that port on its LAN interface.
No port-forwarding or public RPC is needed for a follower to make that outbound
connection. The second node does not need an inbound host port for this initial
one-peer synchronization path.

A cloud host cannot normally reach a home/private LAN address. It needs a peer
that is reachable from that host: for example, a deliberately configured public
P2P endpoint with router forwarding, or a private routed network/VPN between both
machines. The release does not claim a public Internet seed exists. A DNS record
for a website or ordinary Cloudflare HTTP proxy does not provide CometBFT P2P TCP.
Keep signer, admin, RPC and wallet services private while arranging peer access.

## Operator: publish peer access without replacing the chain

First confirm the saved validator is running. On the founding machine only:

```sh
python node.py expose-peer --host YOUR_LAN_INTERFACE_IP --port 26656
```

This command has a brief validator interruption. It stops the existing container,
keeps it as a rollback container, and creates its replacement using the **exact
same image and named volume** with the explicit P2P bind. After blocks advance it
removes the stopped old container. On startup failure it restores the original.
It never deletes a chain volume or creates a new genesis. Query ports retain their
127.0.0.1 bindings. Custom container commands/mounts or alternate P2P bindings are
refused for manual review. The host firewall is configured separately.

Publish only public network documents with:

```sh
python node.py export --peer-host YOUR_REACHABLE_HOST:26656 --public-base-url https://luxartium.org/testnet --output build/public-network
```

Export produces `genesis.json` and `network.json`. The genesis contains public
chain configuration and initial transactions, not private validator keys. The
manifest records both the SHA-256 of the **downloaded genesis file bytes** and
the RPC's canonical genesis fingerprint, which differ because the SDK wraps the
configuration differently. It also records the public P2P node ID.

Do not publish a private LAN address as an Internet seed. For a LAN-only setup,
publish just `genesis.json` and provide the peer separately. Once an actually
reachable public peer exists, publish the manifest too; new users can then run
`python node.py join --network https://luxartium.org/testnet/network.json`.

## Verification

`python verify_join.py` starts two disposable Docker nodes, exposes only the test
leader's P2P port, joins using its exact genesis, checks unique node/validator keys
and zero follower voting power, compares block hashes and a real transfer balance,
and verifies follower restart persistence. It removes only its own labeled test
nodes, volumes and network. This test does not claim the user's LAN/router/firewall
has been checked; test reachability from the actual second machine separately.
