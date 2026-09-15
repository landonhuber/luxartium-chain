# Standalone repository boundary

This repository was extracted on 2026-09-15 from AI Art Foundry's
`networks/luxartium` directory. The Foundry checkout was left in place so the
running development chain, signer, local websites and application keep their
existing launch paths. No volume, wallet, account, genesis or transaction history
was copied into this repository.

The Go application and command files, `go.mod`, `go.sum`, Dockerfile and monetary
constants are unchanged. The operator's content-derived image fingerprint remains
identical. Docker image names, ownership labels, chain ID, container/volume names,
and `~/.luxartium` credential/journal locations retain compatibility with the
running development installation.

The former public home/explorer and private operator frontend are retained under
`operator-ui/` as a loopback-only compatibility console. `sites.py`, `explorer.py`
and the JavaScript amount check use that location. This is a deliberately retained
snapshot, not the public website deployment source. New public website/explorer
changes belong in `landonhuber/luxartium-site`, which needs no Go module, wallet,
signer credential or Docker access.

Future chain development should use this repository. Until Foundry's local launch
scripts are moved to a pinned checkout/release here, the original copy is a
transitional runtime copy. Avoid independently changing both copies and assuming
that a push upgrades the other. Foundry communicates with the signer over HTTP;
neither project imports the other's application code.

## Move an existing local operator to this checkout

1. Verify this checkout is the reviewed revision you intend to run. Compare its
   protocol source fingerprint with the installed image. `status` is read-only.
2. Do not call `init` for the existing chain and do not delete its Docker volume.
3. Stop only the old signer/site processes you intend to replace. Start
   `python gateway.py` or `python localnet.py sites` here. Their existing private
   credential/journal locations are reused; simultaneous listeners would compete
   for the same ports.
4. No saved validator restart is required by this extraction. A changed protocol
   source/image later requires its own reviewed migration, not an automatic swap.

No production node or public network is provisioned by this extraction. GitHub
Actions builds and tests a disposable network; it never deploys a running validator.
Historical ADRs under `docs/decisions/` are preserved verbatim for provenance and
retain source-project paths and earlier currency names where applicable.
