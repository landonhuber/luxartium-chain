# Development instructions

Read README.md, docs/extraction.md, docs/network.md and the applicable historical
decisions in docs/decisions before changing protocol or operator behavior.

- Keep chain logic here and the public Luxartium website in its separate repository.
- Preserve exact integer LUXAR accounting, six decimals, the billion-token genesis,
  absence of mint authority and deterministic replay unless the owner authorizes
  a new protocol decision and migration.
- Never commit wallet keys, seeds, credentials, signer journals, chain databases,
  `.env` files or test fixtures containing private delivery material.
- Tests may remove only uniquely named, ownership-label-checked resources created
  by that test. Never reset/delete a saved local network as a test shortcut.
- Keep all current operator, signer and private-console listeners loopback-only.
  Public network hosting or signing changes require a separately reviewed boundary.
- Pin dependencies and Docker images. Do not silently replace a running validator
  when its image differs; design and verify an upgrade path.
- Run focused Python/HTTP checks for operator changes, Node exact-amount checks for
  local console changes, and the Docker Go tests plus disposable-chain acceptance
  for protocol changes. Gateway changes also need disposable signer acceptance.
- GitHub pushes run CI only. Do not automatically deploy a chain or publish keys.
