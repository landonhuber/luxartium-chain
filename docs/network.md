# Network and monetary settings

| Setting | Value |
|---|---|
| Chain ID | `luxartium-local-1` |
| Binary | `luxartiumd` |
| Native base denomination | `uluxar` |
| Display name / ticker | Luxartium / LUXAR |
| Precision | 6 decimals; 1 LUXAR = 1,000,000 uluxar |
| Account prefix | `luxar1…` |
| Genesis supply | 1,000,000,000,000,000 uluxar = 1 billion LUXAR |
| Validator allocation | 100,000 LUXAR, including 10,000 initially bonded |
| Faucet allocation | 999,900,000 LUXAR |
| Minting | No mint module and no module mint permission |
| Native fee floor | 1,000 uluxar = 0.001 LUXAR |
| Operator transfer gas limit | 200,000 |
| Validator set | One locally controlled staking validator |
| RPC | `http://127.0.0.1:26657` |
| REST | `http://127.0.0.1:1317` |
| gRPC | `127.0.0.1:9090` |
| Docker container / volume | `luxartium-local-1` / `luxartium-local-1-data` |
| Runtime | Unprivileged UID 10001; 2 CPUs, 2 GiB RAM |

The fixed quantity is the **starting supply**. Treasury and faucet distributions
move existing coins. Existing staking slashing and some governance outcomes can
burn coins. There is no custom burn, royalty or treasury split for chain fees.

Gas measures transaction work. The native fee checker enforces a minimum 0.001
LUXAR transaction fee during block execution, plus applicable validator minimum
gas-price requirements in admission. The operator uses a 200,000 gas limit and
1,000 uluxar fee for its bank transfers. Larger messages may need more gas/fees.
Fees follow the SDK distribution module to validator/delegator rewards and its
configured community pool. They are separate from Foundry's 1 LUXAR action charge,
which is an ordinary bank transfer to the Foundry treasury.

Transactions rejected before inclusion do not pay a fee. An included transaction
that passes signature/fee processing but fails message execution can still pay its
fee. A reported unknown outcome includes the transaction hash: query that hash
before retrying to avoid sending twice.

By default all published ports bind to host loopback and P2P is unpublished. An
operator can explicitly enable P2P with `node.py expose-peer --host <interface>`;
RPC, REST and gRPC remain loopback-only. `node.py join` configures a full node's
outbound persistent peer. A local `init` produces a fresh independent genesis with new
keys; matching chain IDs do not make two independently initialized networks the
same chain. The signer pins the genesis fingerprint as well as the chain ID.

Full-node joining is available using the published genesis and an operator-provided
reachable peer. Public network rollout still needs independent validator operators,
persistent hosts, publicly reachable peer configuration, key backup and recovery,
monitoring, upgrade procedures, and separately reviewed RPC exposure. Do not
publish the local Python signer/admin through a tunnel. Cloudflare Workers can
serve a website and a read-only HTTP adapter; the validator needs a separate
persistent Linux host/container.

Read-only operator examples:

```sh
docker exec luxartium-local-1 luxartiumd query bank total --output json --home /chain
docker exec luxartium-local-1 luxartiumd query tx <transaction-hash> --output json --home /chain
docker logs --tail 50 luxartium-local-1
```

Unknown upgrade plans halt the current binary at the configured height. A future
release must implement and verify its own upgrade handler and state migration;
there is no automatic destructive reset or bypass.
