# Honua Helm Chart

Deploys Honua Server on Kubernetes with optional Bitnami PostgreSQL and Redis subcharts.

## Quick start

For local development and Helm smoke testing, use the development overlay:

```bash
helm dependency update honua
helm upgrade --install honua honua -f honua/values-dev.yaml
```

## Values contract and overlays

The operator values contract is documented in:

- `values.yaml` for baseline defaults and inline value comments. It is not an
  installable values file by itself because required runtime secrets are empty.
- `values.schema.json` for Helm type checks and conditional validation that can
  run against the documented baseline.
- `../docs/values-contract.md` for required vs optional values, overlay usage, and release-lane boundaries.
- `../docs/MIGRATION.md` for breaking changes policy and install/upgrade smoke commands.

Environment overlays are provided for common release lanes:

| Overlay | Purpose |
|---------|---------|
| `values-dev.yaml` | Local and ephemeral development installs with bundled PostgreSQL and Redis dependencies. |
| `values-stage.yaml` | Staging validation with existing-secret mode, ingress, HPA, observability, and OpenTelemetry. |
| `values-prod.yaml` | Customer-operated production posture with existing-secret mode, ingress, HPA, observability, and OpenTelemetry. |

Layer a site-specific file after the environment overlay:

```bash
helm upgrade --install honua honua \
  -f honua/values-prod.yaml \
  -f customer-prod.yaml
```

## Production example

Start from `honua/values-prod.yaml`, then create a customer-specific override:

```yaml
image:
  repository: ghcr.io/honua-io/honua-server
  tag: ""   # Leave empty when digest is set
  digest: "sha256:<64 lowercase hex characters>"
  pullPolicy: IfNotPresent

release:
  id: "honua-2026-05-preview"
  manifest: "https://example.com/release/honua-2026-05-preview.json"
  digest: "sha256:<64 lowercase hex characters>"

strategy:
  type: Recreate

resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: "2"
    memory: 2Gi

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 20
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60

ingress:
  className: nginx   # or alb, traefik, etc.
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: gis.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: honua-tls
      hosts:
        - gis.example.com

config:
  env:
    Public__BaseUrl: "https://gis.example.com"

secret:
  create: false
  name: honua-prod-runtime

preflight:
  enabled: true
```

The `honua-prod-runtime` Secret must contain:

- `ConnectionStrings__DefaultConnection`
- `HONUA_ADMIN_PASSWORD`
- `ConnectionStrings__redis` when Redis is used

```bash
helm dependency update honua
helm upgrade --install honua honua -f honua/values-prod.yaml -f customer-prod.yaml
```

## External PostGIS database (recommended for production)

For production, point `ConnectionStrings__DefaultConnection` at a managed PostGIS database (e.g., Amazon RDS, Azure Flexible Server) rather than using the Bitnami subchart.

> The Bitnami PostgreSQL subchart **does not include PostGIS**. Honua requires PostGIS for migrations and spatial queries. For anything beyond local development, use an external PostGIS-enabled database.

## PostgreSQL subchart (dev only)

```bash
helm upgrade --install honua honua \
  --set postgresql.enabled=true \
  --set postgresql.auth.username=honua \
  --set postgresql.auth.password=honua \
  --set postgresql.auth.database=honua \
  --set secret.env.HONUA_ADMIN_PASSWORD="change-me"
```

When `postgresql.enabled=true`, `postgresql.auth.username`,
`postgresql.auth.password`, and `postgresql.auth.database` are required. In
chart-managed-secret mode, the chart auto-populates
`ConnectionStrings__DefaultConnection` if you don't supply one.

## Redis subchart

```bash
helm upgrade --install honua honua \
  --set redis.enabled=true \
  --set redis.auth.enabled=true \
  --set redis.auth.password="change-me-redis" \
  --set secret.env.ConnectionStrings__DefaultConnection="Host=postgis.internal;Database=honua;Username=honua;Password=<secret>;SSL Mode=Require" \
  --set secret.env.HONUA_ADMIN_PASSWORD="change-me"
```

When `redis.enabled=true`, `redis.auth.enabled` must remain true. In
chart-managed-secret mode, the chart auto-populates `ConnectionStrings__redis`
from `redis.auth.password` unless you set `secret.env.ConnectionStrings__redis`
yourself. Existing-secret mode must provide the runtime environment key through
the named Secret or `extraEnvFrom`; the chart does not create it.

## AOT vs JIT images

The chart defaults to AOT (`latest-aot`). AOT images start faster and use less memory. To use JIT instead:

```bash
helm upgrade --install honua honua \
  --set image.tag=latest
```

For production, pin by digest when possible:

```yaml
image:
  repository: ghcr.io/honua-io/honua-server
  tag: ""
  digest: "sha256:<64 lowercase hex characters>"
  pullPolicy: IfNotPresent
```

If you cannot pin by digest, use an immutable release tag: `v1.2.3-aot` (AOT) or `v1.2.3` (JIT).

## Upgrade and migration contract

Honua Server runs database migrations inline during startup behind a PostgreSQL advisory lock. The chart defaults the Deployment strategy to `Recreate` so old pods stop before new pods start during a migrating upgrade.

Use `RollingUpdate` only when the migration set is forward and backward compatible across the old and new Honua images:

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 0
    maxUnavailable: 1
```

Readiness at `/healthz/ready` is the chart signal that startup and migrations completed.

## Preflight hook

`preflight.enabled=true` renders Helm `pre-install,pre-upgrade` hooks that validate required secret keys, PostgreSQL TCP reachability, and target image registry reachability before the Deployment is applied. The kubelet remains authoritative for full image pull success, especially for private registries.

Disable only when an external controller or restricted network policy prevents the hook from reaching the database or registry:

```yaml
preflight:
  enabled: false
```

## Release evidence and rollback

Set release metadata so operators can capture what is running:

```yaml
release:
  id: "honua-2026-05-preview"
  manifest: "https://example.com/release/honua-2026-05-preview.json"
  digest: "sha256:<64 lowercase hex characters>"
```

The chart writes this metadata to Deployment/Pod labels and annotations, the release-info ConfigMap, the container environment, Helm NOTES, and `helm test` output.

Capture evidence and rollback with:

```bash
kubectl get configmap honua-honua-release-info -o yaml
helm test honua
helm history honua
helm rollback honua <revision>
```

Rollback redeploys the prior Helm revision. The chart cannot downgrade database schema; restore from backup or roll forward if the prior app image is not compatible with the migrated schema.

## Using an existing secret

Instead of chart-managed secrets, reference a pre-existing Kubernetes secret:

```yaml
secret:
  create: false
  name: my-honua-secret   # Must contain ConnectionStrings__DefaultConnection and HONUA_ADMIN_PASSWORD
```

You may also set `secret.create=false` and provide only `extraEnvFrom` sources.
In that mode the referenced sources must expose `ConnectionStrings__DefaultConnection`,
`HONUA_ADMIN_PASSWORD`, and `ConnectionStrings__redis` when Redis is used.

## Key values

| Value | Default | Description |
|-------|---------|-------------|
| `replicaCount` | 1 | Number of pods. Use 3+ for production. |
| `image.tag` | `latest-aot` | Image tag. AOT recommended. Leave empty when `image.digest` is set. |
| `image.digest` | `""` | Immutable image digest. Preferred for production and rollback evidence. |
| `release.id` | `""` | Operator release identifier surfaced in labels, annotations, ConfigMap, NOTES, and tests. |
| `release.manifest` | `""` | URL, path, or commit for the release manifest. |
| `release.digest` | `""` | Digest of the release manifest or release bundle. |
| `strategy.type` | `Recreate` | Upgrade strategy. `Recreate` is safe for inline migrations. |
| `preflight.enabled` | true | Enable pre-install/pre-upgrade validation hook. |
| `terminationGracePeriodSeconds` | 60 | Pod shutdown grace period for lock release and clean termination. |
| `resources` | 250m/512Mi request, 2 CPU/2Gi limit | CPU/memory requests and limits. Tune for production. |
| `autoscaling.enabled` | false | Enable HPA. |
| `autoscaling.targetCPUUtilizationPercentage` | `70` | CPU utilization threshold for scale decisions. |
| `autoscaling.targetMemoryUtilizationPercentage` | `80` | Memory utilization threshold for scale decisions. |
| `autoscaling.behavior` | scale up/down policies | autoscaling/v2 behavior policies and stabilization windows. |
| `ingress.enabled` | false | Enable ingress. |
| `config.env.*` | N/A | Non-secret environment variables stored in a ConfigMap. |
| `secret.create` | true | Create a chart-managed Secret. Set false for customer-managed secrets. |
| `secret.env.*` | N/A | Secret environment variables stored in a chart-managed Secret. |
| `secret.name` | `""` | Reference an existing secret instead of chart-managed secret data. |
| `extraEnv` | `[]` | Additional env vars from external sources (e.g. `valueFrom`). |
| `extraEnvFrom` | `[]` | Additional env source refs; also valid for existing-secret mode. |
| `postgresql.enabled` | false | Enable Bitnami PostgreSQL subchart (dev only). |
| `redis.enabled` | false | Enable Bitnami Redis subchart. Requires `redis.auth.enabled=true`; chart-managed secrets can derive the Redis connection string from `redis.auth.password`. |

See `values.yaml` and `../docs/values-contract.md` for the complete reference.

## Health checks

The chart configures probes on:
- **Liveness**: `/healthz/live` (is the process alive?)
- **Readiness**: `/healthz/ready` (startup, dependencies, and migrations are complete)
- **Startup**: `/healthz/live` with 60 retries (migration and cold-start tolerance)

The full operator contract is documented in [`docs/contract.md`](../docs/contract.md).

## Geospatial HPA tuning guidance

The default HPA thresholds are tuned for mixed geospatial workloads:
- `targetCPUUtilizationPercentage: 70` for CPU-heavy spatial predicates and tile generation.
- `targetMemoryUtilizationPercentage: 80` for bursty map rendering and large feature payloads.
- `scaleUp` stabilization of 60s with 50% growth to react quickly to traffic ramps.
- `scaleDown` stabilization of 300s with 10% shrink to avoid thrash after short spikes.

For dataset-specific tuning:
- Increase `maxReplicas` only after validating PostgreSQL connection limits.
- Raise memory targets (for example 85-90) if large map exports are common and pod OOM is not observed.
- Reduce `scaleDown` aggressiveness further for workloads with repeated 3-10 minute query bursts.

## Local validation

```bash
helm dependency update honua
helm lint honua
helm lint honua -f honua/ci-values/base.yaml
helm lint honua -f honua/values-dev.yaml
helm lint honua -f honua/values-stage.yaml
helm lint honua -f honua/values-prod.yaml
helm template honua honua -f honua/ci-values/base.yaml
helm template honua-dev honua -f honua/values-dev.yaml
helm template honua-stage honua -f honua/values-stage.yaml
helm template honua-prod honua -f honua/values-prod.yaml
helm template honua-stage honua -f honua/values-stage.yaml --is-upgrade
helm test honua  # After install, runs the test hook
```

For install/upgrade smoke against a real API server, see `../docs/MIGRATION.md`.
Running `helm template honua honua` without a values file fails by design because
the baseline contract leaves required runtime secrets empty.

For ingress testing on a local Kubernetes cluster, see [K3d + Helm guide](https://github.com/honua-io/honua-server/blob/trunk/docs/contributor/development/k3d-helm.md).
