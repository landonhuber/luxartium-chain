# How Luxartium works today

**Reference date: September 19, 2026 (America/Phoenix).** Live chain data was read at
2026-09-20 02:29 UTC, height 39,610. This document describes the current testnet,
not promises about a future production network. Values may change through later
transactions, governance or a reviewed software upgrade.

Evidence: [saved public state](testnet-state-2026-09-19.json), the running binary,
[application modules](../app/app.go), [fee rules](../app/config.go),
[network configuration](../localnet.py), and the Foundry native-beta implementation.
The snapshot contains public chain data only. No configuration or economic rule was
changed to prepare this reference.

## 1. What exists

Luxartium is an independent Cosmos SDK blockchain using CometBFT consensus. It is
not an Ethereum token, Solana token, Bitcoin sidechain or mining network. Its
native currency is LUXAR. The pinned stack is Cosmos SDK 0.55.0 / CometBFT 0.40.0.

| Component | Current role |
| --- | --- |
| Dedicated Windows computer, serverOffice | Sole active validator; commits new blocks |
| Laptop | Synchronized full node; zero consensus voting power; backup explorer reads |
| luxartium.org | Public information website; production sections say Coming soon |
| luxartium.org/testnet/explorer/ | Read-only view of this testnet, dedicated node first and laptop second |
| AI Art Foundry native beta | Local application using LUXAR transfers and artwork hash commitments |
| Foundry signer | Private managed test-wallet service on the laptop; separate from validator signing |

The chain ID remains `luxartium-local-1`. Moving the validator preserved the original
genesis, balances, history and validator identity. The laptop now has different
consensus and P2P identities, so it is not a second active copy of the validator key.

Two computers do not mean two validators or two independent operators. This is
currently an owner-controlled, single-validator testnet with a replicated history.
It is not yet a decentralized production network.

## 2. How a transaction becomes final

1. A wallet signs a transaction: for example, transferring LUXAR to another address.
2. A node checks the signature, account sequence, balance, fee and gas requirements.
3. An active validator proposes a block. Validators execute the deterministic chain
   rules and exchange consensus votes.
4. A valid block becomes committed when **more than two-thirds of active validator
   voting power** precommits it. All synchronized nodes apply the same results.
5. The explorer reads the committed record. It neither approves transactions nor
   produces blocks.

The quorum is based on voting power, not number of machines, people or wallets.
There is no proof-of-work mining and no GPU competition. More CPU does not buy votes.
With multiple validators, proposal responsibility rotates according to the consensus
rules and voting power; the explorer's preferred source is not a protocol leader.
CometBFT provides immediate commitment under its consensus assumptions; an ordinary
follower does not independently choose a competing history.
See the [pinned CometBFT consensus specification](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/consensus/consensus.md).

The node configuration targets approximately one-second commits. This is a local
test setting, not a throughput or uptime guarantee. Empty blocks can advance the
chain, but they do not create new LUXAR.

## 3. Nodes, validators and the meaning of voting

| Role | Runs a node? | Signs consensus votes? | Receives protocol rewards? |
| --- | --- | --- | --- |
| Ordinary wallet holder | No | No | No, merely holding LUXAR pays nothing |
| Non-voting full node | Yes | No | No automatic node-hosting payment |
| Active validator | Yes | Yes, with its consensus key | Fee-based validator rewards |
| Delegator | No requirement | No; the selected validator signs | Share of that validator's fee rewards |
| Governance voter | No requirement | Votes on proposals, not individual blocks | No separate payment for casting a governance vote |

There are **two separate voting systems**. Consensus voting selects/commits blocks
and is performed automatically by active validator software. Governance voting
decides proposals and is submitted as signed transactions by stake holders.
Foundry artwork likes, ratings and branch rankings are neither of these.

The current validator has 10,000 LUXAR bonded, consensus power 10,000, is not jailed,
and has all current voting power. Its on-chain moniker remains `local-validator`;
the dedicated node's networking moniker is `serveroffice-validator`. These names
describe different records and do not imply different validators.

Public validator operator address:
`luxarvaloper1u6dxvdpk0v8ey4npsksw6mrphclhg02v68mgau`.

## 4. What happens when a computer goes offline

| Event | New blocks | Explorer |
| --- | --- | --- |
| Laptop off; dedicated validator healthy | Continue | Reads dedicated machine |
| Dedicated read API/tunnel fails; its validator keeps working | Continue | Falls back to synchronized laptop |
| Dedicated validator off; laptop on | Stop | Can show laptop's retained history, labeled stale after 30 seconds |
| Both nodes unavailable | Stop | Information website remains online; chain queries show unavailable |

There is no automatic promotion of the laptop to validator. Explorer failover only
changes where data is read. It cannot replace missing consensus power. A full node
cannot register itself as a new validator while the chain is halted, because that
registration itself needs a committed transaction.

The dedicated read API and tunnel start with Windows. Docker Desktop starts when
`lando` signs in; the validator container resumes with Docker. Unattended recovery
through a complete Windows reboot has not been demonstrated. The laptop's signer,
Foundry services and wallet operations were not migrated, so keeping the blockchain
online does not by itself keep the whole Foundry application online.

The Worker validates chain ID, denomination and block-1 hash. It tries the dedicated
origin first, allows four seconds per source, then tries the laptop as needed.
Both origins publish only allowlisted reads. Public HTTPS explorer connectivity is
separate from P2P node connectivity; public Internet P2P forwarding is not configured.

## 5. Supply, denominations and custody

| Setting | Current value |
| --- | --- |
| Currency | Luxartium / LUXAR |
| Base unit | `uluxar` |
| Precision | 6 decimal places; 1 LUXAR = 1,000,000 uluxar |
| Genesis supply | 1,000,000,000 LUXAR |
| Observed current supply | 1,000,000,000 LUXAR |
| Initial validator-wallet allocation | 100,000 LUXAR, of which 10,000 was bonded |
| Initial faucet allocation | 999,900,000 LUXAR |
| Minting/inflation | No mint module, mint authority or automatic issuance |

The initial allocations are not statements of today's spendable wallet balances.
Faucet grants, treasury funding and payments move existing tokens. Genesis supply
includes bonded tokens; staking did not create an additional 10,000 LUXAR.

The billion-token quantity is a fixed **starting supply**. Existing slashing and
some governance outcomes can burn tokens, so supply can decline. There is no
ordinary transaction or administrator mint button that increases supply. Adding
issuance would require a deliberate protocol change; this guide does not propose it.

The faucet, Foundry treasury and governance community pool are different accounts.
They are not interchangeable names for a single reserve. Most initial supply was
assigned to an operator-controlled faucet, so initial distribution is highly
concentrated. Bonded stake currently represents only 0.001% of the starting supply.

Validator consensus keys sign blocks. Wallet/operator keys authorize transfers,
staking and governance. P2P keys identify nodes. Copying one is not equivalent to
copying the others. The migration moved the consensus identity and its latest signing
state, not the laptop's account wallet keyring or Foundry signer journal.

## 6. Gas and fees

Gas measures the computational work a transaction is allowed to perform. LUXAR pays
the transaction fee; gas units themselves are not a second coin. The application
enforces at least **1,000 uluxar = 0.001 LUXAR** per transaction, and rejects fees in
other denominations. Validator admission settings can require additional fees.

Current operator and Foundry bank transfers specify a 200,000 gas limit and a
0.001 LUXAR fee. This is not a universal gas limit for every possible staking or
governance message. A larger operation may need a higher limit or fee. The declared
fee is charged; unused gas does not create an automatic refund of part of that fee.

Transactions rejected before inclusion do not pay a committed fee. An included
transaction that passes signature/fee processing but fails message execution can
still consume its fee. The Foundry's failed-action refund is a separate application
transfer, not a built-in blockchain gas refund.

## 7. What validators and delegators earn

Fee distribution is already wired into the running chain. It is not merely a
roadmap item. There is **no newly minted block subsidy, guaranteed APR, payment for
holding a wallet, or automatic reward for running a non-voting full node**.

Current parameters:

- Community tax: **2%** of distributable fees to the on-chain community pool.
- Remaining fee allocation: validator rewards through the SDK distribution rules.
- Current validator commission: **10%** of its reward allocation.
- Remaining validator rewards: shared among its delegators, including self-delegation.
- Current commission ceiling: **20%**; maximum change **1 percentage point per day**.
- Chain-wide minimum commission: **0%**. New validators can choose their own valid
  commission terms; they do not automatically inherit this validator's 10% rate.
- Separate base/bonus proposer reward parameters are both **0**.

For a 0.001 LUXAR fee with the current sole validator participating, the illustrative
split is 0.000020 to the community pool and 0.000980 to validator rewards. At 10%
commission, 0.000098 is commission and 0.000882 is the delegator portion. The current
operator also owns all self-delegation, so both validator portions accrue to that
operator through separate reward accounting. They are not extra rewards on top of
the original fee. Rounding/dust and withdrawal timing matter at base-unit precision.

Live evidence at height 39,610: community pool **80 uluxar (0.000080 LUXAR)**;
validator outstanding rewards **3,920 uluxar (0.003920 LUXAR)**; of that total,
commission **392 uluxar (0.000392 LUXAR)**. The commission is included in outstanding
rewards, not an additional 392 uluxar. These tiny accrued amounts demonstrate fee
accounting, not a meaningful income projection.

Rewards accrue in distribution accounting and require withdrawal to become spendable.
They do not automatically compound into bonded stake. Withdrawals are transactions
with fees, so withdrawing tiny rewards can cost more than the amount collected.
The Foundry's 1 LUXAR action payment is not part of this validator fee split.
See the pinned [distribution implementation](https://github.com/cosmos/cosmos-sdk/blob/v0.55.0/x/distribution/keeper/allocation.go)
and [reward accounting specification](https://github.com/cosmos/cosmos-sdk/blob/v0.55.0/x/distribution/README.md).

## 8. Staking and becoming a consensus voter

Staking is enabled. It locks LUXAR as security for a validator. Delegation associates
that stake with a validator without giving the validator the delegator's wallet key.
It increases the validator's consensus power and exposes that delegation to slashing.

Current staking configuration:

| Setting | Value |
| --- | --- |
| Staking token | LUXAR (`uluxar`) |
| Maximum active validators | 100; currently only 1 exists |
| Unbonding period | 21 days |
| Maximum concurrent unbonding/redelegation entries | 7 for the relevant delegation relationship |
| Consensus power reduction | 1 power unit per 1,000,000 uluxar, rounded down |
| Current validator's minimum self-delegation field | 1 uluxar |
| Current actual self-delegation | 10,000 LUXAR |
| Consensus-key rotation module fee | 1 LUXAR, separate from the transaction fee |

The current minimum-self-delegation field is not a claim that one micro-unit gives a
positive consensus vote. At the default power conversion, at least one whole LUXAR
is needed for nonzero power; active-set eligibility and other validation still apply.
The existing 10,000 LUXAR bond was an initial choice, not a universal joining fee.

To operate a new validator, someone would:

1. Join and synchronize the existing chain using the published genesis and a reachable peer.
2. Generate their own distinct consensus key and fund an operator wallet with test LUXAR.
3. Choose their moniker, commission terms and minimum self-delegation.
4. Submit a valid `staking create-validator` transaction with self-delegation and fee.
5. Qualify for the active set by bonded stake, then stay online and sign correctly.

The standard staking module is present; no custom operator whitelist was added.
Eligible validators are selected by stake, up to the configured active-set limit.
However, public peer access, a reviewed validator onboarding runbook and a friendly
staking interface are not yet delivered. `node.py join` only creates a full node.
Nobody has been promoted by this documentation task.

A person who wants to participate without hosting a validator can delegate to an
active validator and vote on governance proposals. Spending and staking use the same
fungible LUXAR. There is no special rule making welcome-grant LUXAR non-voting.
Future grant/faucet distribution therefore affects potential stake and governance
control and needs to be designed alongside validator onboarding.

Unbonding initiates the 21-day wait; tokens are not spendable during it. Completion
needs chain progress. Redelegation moves stake between validators subject to the
SDK's restrictions and continuing exposure to earlier offenses.
See the [pinned staking specification](https://github.com/cosmos/cosmos-sdk/blob/v0.55.0/x/staking/README.md).

## 9. Slashing and validator penalties

These rules are already enabled, even though this is a testnet:

| Rule | Current value |
| --- | --- |
| Signing window | 100 committed blocks |
| Minimum signed fraction | 50% |
| Excessive downtime slash | 1% of slashable stake |
| Downtime jail period | 10 minutes before unjail eligibility |
| Double-sign slash | 5% of slashable stake; validator tombstoned |

After the initial tracking window, more than 50 misses in the relevant 100-block
window triggers the configured downtime response. Jail removes a validator from
the active set. Downtime recovery requires the appropriate unjail transaction after
the waiting period and satisfaction of the remaining conditions; time alone does
not automatically restore the validator.

Delegators share the staking risk. Double-signing can occur if two machines run the
same consensus key independently. This is why migration fenced the laptop and why
old signing-state backups must not be restarted as a casual failover mechanism.

Downtime tracking counts committed blocks, not wall-clock seconds. If the only
validator is off and the entire chain halts, there are no advancing blocks to fill
a missing-signature window. Do not interpret the rule as an automatic deduction
every ten minutes of a whole-chain outage.
See the [pinned slashing specification](https://github.com/cosmos/cosmos-sdk/blob/v0.55.0/x/slashing/README.md).

## 10. Governance: becoming a proposal voter

Governance is also enabled, with no proposals present in the observed snapshot.
Voting power comes from stake delegated to active validators, not an unspent wallet
balance and not one vote per person. A delegator can vote directly; their direct
vote overrides the selected validator's vote for that delegated portion. Otherwise
the validator's vote can represent that portion. Today all bonded stake belongs to
the one operator, so governance is effectively controlled by that operator.

| Parameter | Current value |
| --- | --- |
| Regular proposal deposit | 1 LUXAR total to enter voting |
| Deposit collection period | 2 days |
| Regular voting period | 2 days |
| Participation quorum | At least 33.4% of active bonded voting power |
| Approval threshold | More than 50% of non-abstaining voting power cast |
| Veto threshold | More than 33.4% of voting power cast |
| Expedited proposal deposit | 10 LUXAR |
| Expedited voting period | 1 day |
| Expedited approval threshold | More than 66.7% of non-abstaining voting power cast |

Voting choices include Yes, No, No with veto and Abstain; weighted choices are
supported. Ordinary transaction fees are separate from proposal deposits.
Deposits are not all permanent fees: return/burn outcomes depend on the proposal.
Current settings do not burn deposits merely for failure to reach quorum or failure
to enter voting; veto burning is enabled. Proposal cancellation also has a configured
50% deduction ratio. These are test settings, not finalized production economics.

Supported governance messages can change module parameters or authorize supported
community spending. An upgrade proposal does not magically install new software:
operators must deploy a compatible reviewed binary and migration. The current
binary halts for an unknown upgrade plan. Governance cannot invoke an absent mint
module, NFT module or smart-contract runtime.
See the [pinned voting/tally implementation](https://github.com/cosmos/cosmos-sdk/blob/v0.55.0/x/gov/keeper/tally.go).

## 11. How AI Art Foundry uses this chain

The native beta is implemented and tested locally; the public Foundry beta remains
the deployed design preview until the private signer/native service is hosted.
Website availability and a public explorer do not imply public native checkout.

| Action | Current native-beta behavior |
| --- | --- |
| Signup | One 500 LUXAR grant from the finite beta treasury; the older 25-token plan was superseded |
| Paid creative action | 1 LUXAR to Foundry treasury, plus 0.001 LUXAR sender network fee |
| Failed creative execution | Application refunds the action payment and sender fee with replay protection |
| Final version commitment | Treasury sponsors a transaction anchoring the manifest digest in its memo |
| Sale | Buyer pays current owner; confirmed receipt authorizes app ownership transfer |
| Rental | Renter pays current owner and receives one continuation workspace; original ownership stays |
| Default rent | 10% of latest completed sale, or asking price before the first sale; owner can override |

The beta treasury bootstrap is 100,000 LUXAR transferred from the existing faucet.
That is a finite working balance, not a protocol inflation budget. Enrollment uses
managed test wallets: users can receive their keys, while the private signer retains
signing capability. This is not exclusive user custody.

The blockchain currently records native transfers and transaction memos containing
operation/manifest references. Foundry retains artwork files, manifests, lineage,
ownership records and marketplace permissions off-chain and binds them to receipts.
The commitment is a hash anchor, implemented using a one-uluxar treasury self-transfer
plus fee. It is not a native NFT mint, and full image/metadata files are not embedded
in the chain. The hash helps detect changes to the committed manifest; it does not
by itself prove artistic authorship, ownership rights or preservation of the files.

There is no chain-level automatic creator royalty, branch reward, reward for likes,
action-fee burn, or Foundry-revenue share paid to validators. Sale and rental receipts
pay the current owner under Foundry's application rules. Earlier simulated or bounded
pilot economics must not be confused with protocol rewards.

## 12. What can be configured, and what needs building

| Capability | Status / work needed |
| --- | --- |
| Additional full nodes | Released joining mechanism; needs a reachable peer |
| Additional independent validators | Staking protocol exists; needs funded distinct keys, reviewed onboarding and actual activation |
| Delegation, withdrawal, unbonding, governance voting | Standard chain messages exist; no polished public wallet/staking/governance UI |
| Community tax, validator limit, unbonding and slash parameters | Governance-configurable within the existing module rules |
| Current validator commission | Operator transaction, constrained by recorded limits |
| Minimum 0.001 LUXAR fee | Hardcoded application rule; changing it needs a software upgrade |
| Better node availability | Independent always-on hosts, monitoring, recovery drills and voting-power distribution |
| Grants for validator operators | Could transfer an explicitly budgeted existing treasury allocation; no recurring program configured |
| Guaranteed staking APR / inflationary reward | Not configured; no inflation module exists |
| Public native Foundry payments | Needs secure hosted signer/custody and deployment of the native service |
| NFTs / independently enforced artwork ownership | Requires additional protocol/contract work and migration design |
| Ethereum or Solana artwork export | Roadmap only; no bridge, export lock or wrapped asset implemented |
| USD/BTC/ETH/SOL purchase conversion | No live exchange/on-ramp or guaranteed exchange rate in this setup |

Ethereum/Solana export does not inherently require issuing LUXAR on those chains.
It would need destination-chain gas, a destination asset representation, and a
verified locking/export protocol. That remains a separate design, not a feature of
the present hash-commitment system.

The existing distribution CLI also exposes funding a validator rewards pool with
existing coins. That capability does not schedule payments, create new tokens or
establish a promised return. A recurring incentive program still needs explicit policy.

## 13. A sensible path from this testnet

These are recommendations, not changes applied by this document:

1. Stabilize the dedicated host, backups, monitoring and reboot recovery. Add a cloud
   peer on a different power/Internet connection and publish an appropriate P2P endpoint.
2. Test creating a distinct validator, delegating, collecting fees, voting and unbonding
   on a disposable network before admitting additional operators to this saved chain.
3. Choose the desired failure model and stake distribution. Two equal validators
   need both online. Three equal validators also cannot lose one and retain **more
   than** two-thirds. Four equal validators retain 75% after one is lost. Seven equal
   validators retain about 71.4% after two are lost. Independence and stake distribution
   matter as much as the count; multiple home machines share outage risks.
4. Decide production token distribution and security funding together. Fee-only rewards
   are currently tiny. An explicit finite treasury subsidy can fund early operators
   without inflation, but requires a budget, criteria and delivery mechanism.
5. Review production commission, slash, unbonding and governance settings instead of
   treating SDK/test defaults as a completed economic policy. Add user interfaces and
   publish the rules before inviting public stake.

Retaining over two-thirds on the dedicated machine lets it run while smaller validators
are off, but makes its own outage fatal to block production. That tradeoff cannot be
fixed by calling the other nodes backups. True validator redundancy needs an appropriate
active set, not copied validator keys or automatic explorer switching.

## 14. Re-checking this reference

Use read-only queries against either synchronized node. On each current machine the
active node's REST service is `http://127.0.0.1:1317` and RPC is on port 26657.

```powershell
(Invoke-RestMethod 'http://127.0.0.1:26657/status').result.validator_info
Invoke-RestMethod 'http://127.0.0.1:1317/cosmos/staking/v1beta1/params'
Invoke-RestMethod 'http://127.0.0.1:1317/cosmos/staking/v1beta1/validators'
Invoke-RestMethod 'http://127.0.0.1:1317/cosmos/distribution/v1beta1/params'
Invoke-RestMethod 'http://127.0.0.1:1317/cosmos/slashing/v1beta1/params'
Invoke-RestMethod 'http://127.0.0.1:1317/cosmos/gov/v1/params/voting'
Invoke-RestMethod 'https://luxartium.org/testnet/api/overview'
```

These commands do not stake, vote, spend or change the chain. Detailed node migration
and signing recovery notes are in [the migration handoff](VALIDATOR-MOVE-2026-09-19.md).
Public explorer service operations are in the separate website repository's
`docs/TESTNET-CONNECTION.md`. Update this reference and take a fresh public-state
snapshot after changing validator membership, parameters or economic behavior.
