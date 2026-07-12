# honua-helm

[![Helm CI](https://github.com/honua-io/honua-helm/actions/workflows/ci.yml/badge.svg)](https://github.com/honua-io/honua-helm/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/honua-io/honua-helm/badge)](https://scorecard.dev/viewer/?uri=github.com/honua-io/honua-helm)

The Kubernetes deploy path for [Honua Server](https://github.com/honua-io/honua-server) — a
cloud-native geospatial server that exposes one shared capability set through many protocol
adapters (GeoServices REST, OGC API, classic OGC WMS/WFS/WMTS/WCS, STAC, OData v4, vector
tiles, MCP, gRPC), backed by PostGIS. This repository contains the **`honua` Helm chart**:
the server Deployment plus Service, Ingress, HPA, PodDisruptionBudget, pre-install/pre-upgrade
preflight validation hooks, release-evidence resources, Prometheus/OpenTelemetry observability
wiring, and optional Bitnami PostgreSQL and Redis subcharts for development.

## Status

Pre-1.0. Chart releases are cut from `chart-vX.Y.Z` tags and published to
`oci://ghcr.io/honua-io/charts/honua` by [`release.yml`](.github/workflows/release.yml) — no
release has been cut yet, so install from a checkout (below) until the first published version
lands. Value keys under `image`, `service`, `ingress`, `config.env`, `secret.env`,
`postgresql`, and `redis` are stable within a chart major version; the guarantee is formalized
in [docs/values-contract.md](docs/values-contract.md) and [docs/MIGRATION.md](docs/MIGRATION.md).

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Kubernetes cluster + `kubectl` | CI smoke-tests against [kind](https://kind.sigs.k8s.io/). |
| Helm 3.8+ | 3.8 for OCI registry support once published cuts exist. |
| PostGIS database | Required beyond local dev — the bundled Bitnami PostgreSQL subchart does **not** include PostGIS. Use managed PostGIS (RDS, Azure Flexible Server, ...) in production. |
| Redis | Required for all non-`Development` deployments (durable feature-change events); the Bitnami subchart or an external endpoint both work. |
| Network access | `charts.bitnami.com` for subchart dependencies, `ghcr.io` for the server image. |

## Quick start (development install)

```bash
git clone https://github.com/honua-io/honua-helm.git
cd honua-helm
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency build honua                                # uses the committed Chart.lock
helm upgrade --install honua honua -f honua/values-dev.yaml
helm test honua
```

The dev overlay is self-contained: bundled (non-PostGIS) PostgreSQL and Redis, dev-grade
secrets, `ASPNETCORE_ENVIRONMENT=Development`. Do not use it for real data. Readiness at
`/healthz/ready` signals that startup and database migrations completed.

Note that `helm template honua honua` with **no** values file fails by design: the baseline
`values.yaml` is a documented contract that intentionally leaves runtime secrets empty. Always
layer an environment overlay (`values-dev/stage/prod.yaml`) plus a site-specific values file.

## Key values

Every install must provide (via chart-managed `secret.env.*` or an existing Secret):

- `ConnectionStrings__DefaultConnection` — PostGIS connection string
- `HONUA_ADMIN_PASSWORD` — at least 16 chars with upper/lower/digit/special
- `Security__ConnectionEncryption__MasterKey` — at least 32 chars
- `ConnectionStrings__redis` — required for non-`Development` deployments

Common tunables: `ingress.*` (host, TLS, class), `image.tag`/`image.digest` (pin a
`vX.Y.Z-aot` tag or digest in production; the `latest-aot` default is dev-only),
`postgresql.enabled`/`redis.enabled` (Bitnami subcharts), `secret.create=false` +
`secret.name` for existing-secret mode, and `preflight.enabled` (default on: validates
secrets, database/Redis reachability, and registry reachability before apply). The full
values reference, production example, observability/alerting setup, and HPA tuning guidance
live in the chart README: **[honua/README.md](honua/README.md)**.

## Upgrades

Honua Server runs database migrations inline at startup behind a PostgreSQL advisory lock.
The chart defaults `strategy.type` to `Recreate` so old pods stop before new ones start during
a migrating upgrade; use `RollingUpdate` only when the migration set is forward and backward
compatible. `helm rollback` restores the prior release but cannot downgrade database schema.
Details: [docs/contract.md](docs/contract.md) (operator contract) and
[honua/README.md](honua/README.md) (upgrade and rollback commands). Operators moving from the
old in-monorepo chart (`honua-server/infrastructure/helm/honua`) need no value migrations
within chart 0.x — see [docs/MIGRATION.md](docs/MIGRATION.md).

## Repository layout

| Path | Contents |
|------|----------|
| [`honua/`](honua/) | Chart source: `Chart.yaml`, baseline `values.yaml` + schema, dev/stage/prod overlays, templates, CI value files |
| [`honua/README.md`](honua/README.md) | Detailed chart usage, production example, full values reference |
| [`docs/`](docs/) | [Operator contract](docs/contract.md), [values contract](docs/values-contract.md), [migration policy](docs/MIGRATION.md), [feature map](docs/features/README.md), smoke evidence |
| [`RELEASING.md`](RELEASING.md) | Release runbook: chart cuts, versioning (`chart-vX.Y.Z` here vs `vX.Y.Z` in honua-server), OCI publish |
| [`.github/workflows/`](.github/workflows/) | Helm CI (lint + render + kind install/upgrade/rollback smoke), release, AKS smoke, security |

## Documentation

- Chart usage and values reference: [honua/README.md](honua/README.md)
- Honua Server Kubernetes deploy guide: [docs/guides/deploy/kubernetes.md](https://github.com/honua-io/honua-server/blob/trunk/docs/guides/deploy/kubernetes.md)
- Hosted platform docs: <https://honua.gitbook.io/honuaio/>

## Related Honua repositories

| Repo | What it is |
|------|------------|
| [honua-server](https://github.com/honua-io/honua-server) | The multi-protocol geospatial server this chart deploys |
| [honua-console](https://github.com/honua-io/honua-console) | Unified web console (Studio, Catalog, Operate, Share) |
| [honua-sdk-js](https://github.com/honua-io/honua-sdk-js) | JavaScript/TypeScript SDKs + MCP server |
| [honua-sdk-python](https://github.com/honua-io/honua-sdk-python) | Python SDK |
| [honua-esri-assess](https://github.com/honua-io/honua-esri-assess) | Esri footprint assessment CLI for migration discovery |

## Security

Report vulnerabilities to <security@honua.io> — see the
[org security policy](https://github.com/honua-io/.github/blob/main/SECURITY.md). Do not open
public issues for security reports.

## License

[Apache-2.0](LICENSE) for this chart repository. Honua Server itself is distributed under the
Elastic License 2.0 — see the [honua-server license](https://github.com/honua-io/honua-server/blob/trunk/LICENSE).
