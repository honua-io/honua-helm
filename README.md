# Helm Charts

- `honua/` - main chart for Honua Server.

Repository layout is intentionally flat after extraction from the monorepo:
- chart source: `honua/`
- CI workflows: `.github/workflows/`
- Chart usage: `honua/README.md`
- Feature map: [docs/features/README.md](docs/features/README.md)
- Values contract and migration policy: `docs/values-contract.md`, `docs/MIGRATION.md`
- Release runbook (chart cuts, versioning, OCI publish): [RELEASING.md](RELEASING.md)
- Migration from `honua-server/infrastructure/helm/honua`: [docs/MIGRATION.md](docs/MIGRATION.md)
- license: `LICENSE`

The baseline values contract intentionally leaves runtime secrets empty; use an
environment overlay or site-specific values file for installs and render smoke.
The operator-ready chart contract is in [docs/contract.md](docs/contract.md).

Published chart is at `oci://ghcr.io/honua-io/charts/honua`.
