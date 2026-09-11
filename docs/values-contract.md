---
type: reference
title: "values.yaml contract"
description: "Which values are the customer-operated surface and therefore stable, and which are internal wiring that may change without a major bump."
tags: [values, configuration, contract]
---
# Honua Helm Values Contract

This chart keeps the customer-operated surface in these files:

- `honua/values.yaml`: documented baseline defaults. It intentionally leaves
  required runtime secrets empty, so it is not an installable values file by
  itself.
- `honua/values.schema.json`: machine-checked type guards and conditional
  requirements that can be validated while keeping the documented baseline
  lintable. Runtime secret requirements are enforced by template guards.
- `honua/values-dev.yaml`: local and ephemeral development overlay.
- `honua/values-stage.yaml`: staging validation overlay.
- `honua/values-prod.yaml`: production posture overlay.

Apply an environment overlay first, then layer site-specific values after it:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency build honua
helm upgrade --install honua ./honua \
  -f honua/values-prod.yaml \
  -f customer-prod.yaml
```

## Required Values

| Condition | Required values | Evidence |
| --- | --- | --- |
| Image identity | Exactly one of `image.tag` or `image.digest`; when `image.digest` is set, `image.pullPolicy` must be `IfNotPresent` or `Never` | `honua/values.schema.json`, `honua/templates/validations.yaml` |
| Chart-managed Secret (`secret.create=true`) | `secret.env.HONUA_ADMIN_PASSWORD` at least 16 characters with uppercase, lowercase, digit, and special characters; `secret.env.Security__ConnectionEncryption__MasterKey` at least 32 characters long | `honua/templates/secret.yaml` |
| Chart-managed Secret with external PostgreSQL (`postgresql.enabled=false`) | `secret.env.ConnectionStrings__DefaultConnection` | `honua/templates/secret.yaml` |
| Non-development chart-managed Secret without Redis subchart (`config.env.ASPNETCORE_ENVIRONMENT` not `Development` or `Test`, `redis.enabled=false`) | `secret.env.ConnectionStrings__redis` | `honua/templates/secret.yaml` |
| PostgreSQL subchart enabled (`postgresql.enabled=true`) | `postgresql.auth.username`, `postgresql.auth.password`, `postgresql.auth.database` | `honua/values.schema.json`, `honua/templates/secret.yaml` |
| Existing Secret mode (`secret.create=false`) | `secret.name` or at least one `extraEnvFrom` source | `honua/values.schema.json`, `honua/templates/validations.yaml` |
| External runtime environment source | `ConnectionStrings__DefaultConnection`, `HONUA_ADMIN_PASSWORD`, `Security__ConnectionEncryption__MasterKey`; `ConnectionStrings__redis` for non-development deployments | Runtime contract documented here; Kubernetes cannot validate external Secret keys at Helm render time |
| Redis subchart enabled (`redis.enabled=true`) | `redis.auth.enabled=true` | `honua/values.schema.json`, `honua/templates/secret.yaml` |
| Chart-managed Secret with Redis subchart and no explicit `secret.env.ConnectionStrings__redis` | `redis.auth.password` | `honua/values.schema.json`, `honua/templates/secret.yaml` |
| Autoscaling (`autoscaling.enabled=true`) | `autoscaling.targetCPUUtilizationPercentage` or `autoscaling.targetMemoryUtilizationPercentage` greater than `0` | `honua/values.schema.json`, `honua/templates/hpa.yaml` |
| Autoscaling (`autoscaling.enabled=true`) | `config.env.Deployment__Mode` must be `MultiNode` (not `SingleInstance`); MultiNode also requires `ConnectionStrings__redis` and a shared cloud `FileStorage:Provider` of `AwsS3` or `AzureBlob` (`Local` is rejected) | `honua/templates/validations.yaml` (chart-time); MultiNode runtime requirements enforced by Honua Server `ConfigurationValidationService` |
| RollingUpdate (`strategy.type=RollingUpdate`) | At least one of `strategy.rollingUpdate.maxSurge` or `strategy.rollingUpdate.maxUnavailable` must be non-zero | `honua/values.schema.json` |

The PostgreSQL subchart is development-only. It does not include PostGIS, so
production deployments must use an external PostGIS-enabled database and provide
`ConnectionStrings__DefaultConnection` through a Kubernetes Secret or external
environment source.

When `secret.create=false`, the chart only verifies that `secret.name` or
`extraEnvFrom` names a source. It cannot inspect external Secret or ConfigMap
contents during Helm rendering. Redis connection-string derivation from the
Redis subchart only happens when `secret.create=true`.

## Rendered Environment Sources

The Deployment loads environment data with `envFrom`:

- A release-info ConfigMap is always loaded first and exposes
  `HONUA_RELEASE_*`, `HONUA_IMAGE_*`, `HONUA_CHART_VERSION`,
  `HONUA_APP_VERSION`, and Helm release identity.
- `config.create=true` creates a ConfigMap from non-empty `config.env` entries.
- `config.name` references an existing ConfigMap instead of the chart-generated
  name.
- `secret.create=true` creates a Secret from non-empty `secret.env` entries plus
  any derived PostgreSQL or Redis connection strings.
- `secret.name` references an existing Secret instead of the chart-generated
  name.
- `extraEnvFrom` appends additional Kubernetes environment sources and can be
  the only runtime source when `secret.create=false`.

Empty string and null-like values in `config.env` and `secret.env` are omitted
from rendered ConfigMap and Secret data before template-required checks run.

## Optional Values

| Area | Values | Notes |
| --- | --- | --- |
| Image | `image.repository`, `image.tag`, `image.digest`, `image.pullPolicy`, `image.pullSecrets` | Production release lanes should prefer `image.digest` with `image.tag=""`; immutable tags are the fallback. |
| Release evidence | `release.id`, `release.manifest`, `release.digest`, `release.appVersion` | `release.id` and the effective app version must be label-safe; use `release.manifest` for free-form build metadata and `release.digest` for SHA-256 evidence. |
| Upgrade contract | `strategy.*`, `terminationGracePeriodSeconds`, `lifecycle`, `preflight.*` | Default `Recreate` is migration-safe for inline migrations; preflight validates required keys, database and Redis reachability, and optional registry reachability. For `RollingUpdate`/HPA scale-down set a `lifecycle.preStop` sleep so Service endpoint removal propagates before SIGTERM (zero-downtime drain). |
| Naming | `nameOverride`, `fullnameOverride` | Use only for DNS length constraints or platform naming standards. |
| ServiceAccount | `serviceAccount.*` | Token automount stays disabled by default. |
| Routing | `service.*`, `ingress.*` | Ingress class, DNS, TLS, and annotations are platform-specific. |
| Runtime config | `config.create`, `config.name`, `config.env.*` | Non-secret application settings are stored in a ConfigMap unless an external ConfigMap is named. |
| Scheduling | `nodeSelector`, `tolerations`, `affinity`, `podAnnotations`, `podLabels` | Platform placement and metadata hooks. |
| Security | `podSecurityContext`, `securityContext` | Defaults are restricted and should remain the baseline. |
| Resources and probes | `resources`, `livenessProbe`, `readinessProbe`, `startupProbe`, `terminationGracePeriodSeconds` | Tune after observing workload behavior and migration duration. |
| Extensions | `extraEnv`, `extraEnvFrom`, `extraVolumes`, `extraVolumeMounts` | Use for External Secrets Operator, CSI Secret Store, trust bundles, or Downward API. |
| Dependencies | `postgresql.*`, `redis.*` | PostgreSQL subchart is dev-only; Redis can be chart-managed for smoke/dev or supplied externally for non-development durable event storage. |

## Environment Overlays

| Overlay | Purpose | Runtime secret posture | Notes |
| --- | --- | --- | --- |
| `honua/values-dev.yaml` | Local clusters and ephemeral preview namespaces | Chart-managed Secret with development-only strong password and connection-encryption key; PostgreSQL and Redis subcharts enabled | Self-contained for Helm rendering and development smoke. Not for production data because the PostgreSQL subchart is not PostGIS-enabled. |
| `honua/values-stage.yaml` | Release-candidate validation | Existing Secret named `honua-stage-runtime` | Single-instance (`replicaCount: 1`, `Deployment__Mode=SingleInstance`, HPA disabled) so it is internally consistent out of the box. Enables ingress, observability, and OpenTelemetry with staging-sized resources. Override DNS, TLS, image identity, and secret name per environment. For autoscaled HA, opt into MultiNode (see the overlay header). |
| `honua/values-prod.yaml` | Customer-operated production posture | Existing Secret named `honua-prod-runtime` | Single-instance (`replicaCount: 1`, `Deployment__Mode=SingleInstance`, HPA disabled) so it is internally consistent out of the box. Enables ingress, observability, and OpenTelemetry with production-sized resources. Override DNS, TLS, image identity, provider annotations, and secret name per customer. For autoscaled HA, opt into MultiNode (set `Deployment__Mode=MultiNode`, enable autoscaling, and supply Redis + a shared cloud `FileStorage:Provider`; see the overlay header). |

## Breaking Changes Policy

The values contract is stable across compatible chart releases.

- Patch releases may fix templates, docs, or validation messages without changing accepted values.
- Minor releases may add optional values, new overlays, or backward-compatible defaults.
- Major releases are required for removing values, renaming values, changing required value names, changing required external Secret keys, or changing default behavior in a way that breaks an existing install.
- Deprecated values must remain accepted for at least one minor release and must be documented in `docs/MIGRATION.md` with the replacement path.
- Any change to required values must update `honua/values.yaml`,
  `honua/values.schema.json` when the requirement is schema-enforceable without
  invalidating the baseline, `honua/README.md`, and this document in the same
  PR.

## Release-Lane Evidence

This repository owns the Helm chart contract and Helm install/upgrade/rollback
smoke. CI lints and renders the `honua/ci-values/base.yaml` fixture, digest
identity, RollingUpdate, chart-managed PostgreSQL preflight install/upgrade,
and all environment overlays, including the staged upgrade render path. The
cluster-backed install/upgrade/rollback smoke is documented in
`docs/MIGRATION.md`.

Historical ticket #2 smoke evidence is captured in
`docs/smoke/ticket-2-helm-smoke.md`. Ticket #6 evidence is produced by the
current CI workflow's `honua-smoke-evidence` artifact.

Cross-repository release-lane work remains bounded to the owning repos:

- Terraform AWS and Azure end-to-end validation: `honua-terraform#1`, `honua-terraform#2`.
- Marketplace listing packages, private-offer assets, license/entitlement activation, and validation evidence: `honua-marketplace#1`, `honua-marketplace#2`, `honua-marketplace#4`, `honua-marketplace#5`.
- Sales offers aligned to validated marketplace packages: `honua-sales#33`, `honua-sales#34`.
- Helm release-lane coordination outside this values contract: `honua-helm#1`, `honua-helm#6`.
