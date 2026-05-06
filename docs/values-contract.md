# Honua Helm Values Contract

This chart keeps the customer-operated surface in these files:

- `honua/values.yaml`: documented baseline defaults.
- `honua/values.schema.json`: machine-checked required values and type guards.
- `honua/values-dev.yaml`: local and ephemeral development overlay.
- `honua/values-stage.yaml`: staging validation overlay.
- `honua/values-prod.yaml`: production posture overlay.

Apply an environment overlay first, then layer site-specific values after it:

```bash
helm dependency update honua
helm upgrade --install honua ./honua \
  -f honua/values-prod.yaml \
  -f customer-prod.yaml
```

## Required Values

| Condition | Required values | Evidence |
| --- | --- | --- |
| Chart-managed Secret (`secret.create=true`) | `secret.env.HONUA_ADMIN_PASSWORD` | `honua/values.schema.json`, `honua/templates/secret.yaml` |
| Chart-managed Secret with external PostgreSQL (`postgresql.enabled=false`) | `secret.env.ConnectionStrings__DefaultConnection` | `honua/values.schema.json`, `honua/templates/secret.yaml` |
| Chart-managed Secret with PostgreSQL subchart (`postgresql.enabled=true`) | `postgresql.auth.username`, `postgresql.auth.password`, `postgresql.auth.database` | `honua/values.schema.json`, `honua/templates/secret.yaml` |
| Existing Secret mode (`secret.create=false`) | `secret.name` or at least one `extraEnvFrom` source | `honua/values.schema.json`, `honua/templates/validations.yaml` |
| Existing Secret runtime contents | `ConnectionStrings__DefaultConnection`, `HONUA_ADMIN_PASSWORD`; optionally `ConnectionStrings__redis` | Runtime contract documented here; Kubernetes cannot validate external Secret keys at Helm render time |
| Redis subchart without explicit `ConnectionStrings__redis` | `redis.auth.enabled=true`, `redis.auth.password` | `honua/values.schema.json`, `honua/templates/secret.yaml` |
| Autoscaling (`autoscaling.enabled=true`) | `autoscaling.targetCPUUtilizationPercentage` or `autoscaling.targetMemoryUtilizationPercentage` greater than `0` | `honua/values.schema.json`, `honua/templates/hpa.yaml` |

The PostgreSQL subchart is development-only. It does not include PostGIS, so
production deployments must use an external PostGIS-enabled database and provide
`ConnectionStrings__DefaultConnection` through a Kubernetes Secret or external
environment source.

## Optional Values

| Area | Values | Notes |
| --- | --- | --- |
| Image | `image.repository`, `image.tag`, `image.pullPolicy`, `image.pullSecrets` | Production release lanes should pin `image.tag` to a published release tag. |
| Naming | `nameOverride`, `fullnameOverride` | Use only for DNS length constraints or platform naming standards. |
| ServiceAccount | `serviceAccount.*` | Token automount stays disabled by default. |
| Routing | `service.*`, `ingress.*` | Ingress class, DNS, TLS, and annotations are platform-specific. |
| Runtime config | `config.create`, `config.name`, `config.env.*` | Non-secret application settings are stored in a ConfigMap unless an external ConfigMap is named. |
| Scheduling | `nodeSelector`, `tolerations`, `affinity`, `podAnnotations`, `podLabels` | Platform placement and metadata hooks. |
| Security | `podSecurityContext`, `securityContext` | Defaults are restricted and should remain the baseline. |
| Resources and probes | `resources`, `livenessProbe`, `readinessProbe`, `startupProbe` | Tune after observing workload behavior. |
| Extensions | `extraEnv`, `extraEnvFrom`, `extraVolumes`, `extraVolumeMounts` | Use for External Secrets Operator, CSI Secret Store, trust bundles, or Downward API. |
| Dependencies | `postgresql.*`, `redis.*` | PostgreSQL subchart is dev-only; Redis subchart is optional. |

## Environment Overlays

| Overlay | Purpose | Runtime secret posture | Notes |
| --- | --- | --- | --- |
| `honua/values-dev.yaml` | Local clusters and ephemeral preview namespaces | Chart-managed Secret with development password; PostgreSQL and Redis subcharts enabled | Self-contained for Helm rendering and development smoke. Not for production data because the PostgreSQL subchart is not PostGIS-enabled. |
| `honua/values-stage.yaml` | Release-candidate validation | Existing Secret named `honua-stage-runtime` | Enables ingress, HPA, observability, and OpenTelemetry with staging-sized resources. Override DNS, TLS, image tag, and secret name per environment. |
| `honua/values-prod.yaml` | Customer-operated production posture | Existing Secret named `honua-prod-runtime` | Enables ingress, HPA, observability, and OpenTelemetry with production-sized resources. Override DNS, TLS, image tag, provider annotations, and secret name per customer. |

## Breaking Changes Policy

The values contract is stable across compatible chart releases.

- Patch releases may fix templates, docs, or validation messages without changing accepted values.
- Minor releases may add optional values, new overlays, or backward-compatible defaults.
- Major releases are required for removing values, renaming values, changing required value names, changing required external Secret keys, or changing default behavior in a way that breaks an existing install.
- Deprecated values must remain accepted for at least one minor release and must be documented in `docs/MIGRATION.md` with the replacement path.
- Any change to required values must update `honua/values.yaml`, `honua/values.schema.json`, `honua/README.md`, and this document in the same PR.

## Release-Lane Evidence

This repository owns the Helm chart contract and Helm install/upgrade smoke. CI
lints and renders the base values plus all environment overlays, including the
staged upgrade render path. The cluster-backed install/upgrade smoke is
documented in `docs/MIGRATION.md`.

Current ticket smoke evidence is captured in
`docs/smoke/ticket-2-helm-smoke.md`.

Cross-repository release-lane work remains bounded to the owning repos:

- Terraform AWS and Azure end-to-end validation: `honua-terraform#1`, `honua-terraform#2`.
- Marketplace listing packages, private-offer assets, license/entitlement activation, and validation evidence: `honua-marketplace#1`, `honua-marketplace#2`, `honua-marketplace#4`, `honua-marketplace#5`.
- Sales offers aligned to validated marketplace packages: `honua-sales#33`, `honua-sales#34`.
- Helm release-lane coordination outside this values contract: `honua-helm#1`, `honua-helm#6`.
