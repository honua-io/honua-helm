# Honua Helm Chart

Deploys Honua Server on Kubernetes with optional Bitnami PostgreSQL and Redis subcharts.

## Quick start

For local development and Helm smoke testing, use the development overlay:

```bash
helm dependency update honua
helm upgrade --install honua honua -f honua/values-dev.yaml
```

For direct installs with external data services, the default preflight hook
checks the configured PostgreSQL/PostGIS and Redis hosts before the Deployment
is applied.

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
  appVersion: "2026.05.0"   # Optional label-safe evidence override

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
- `HONUA_ADMIN_PASSWORD` with at least 16 characters, including uppercase,
  lowercase, digit, and special characters
- `Security__ConnectionEncryption__MasterKey` with at least 32 characters
- `ConnectionStrings__redis` for non-development deployments

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
  --set secret.env.HONUA_ADMIN_PASSWORD="ExampleAdminPassword1!" \
  --set secret.env.Security__ConnectionEncryption__MasterKey="example-connection-encryption-master-key"
```

When `postgresql.enabled=true`, `postgresql.auth.username`,
`postgresql.auth.password`, and `postgresql.auth.database` are required. In
chart-managed-secret mode, the chart auto-populates
`ConnectionStrings__DefaultConnection` if you don't supply one.
During the initial install with that auto-generated connection string, preflight
skips PostgreSQL TCP reachability because Helm pre-install hooks run before
subchart Services and Pods are created. Pre-upgrade hooks check the existing
PostgreSQL endpoint.

## Redis subchart

```bash
helm upgrade --install honua honua \
  --set redis.enabled=true \
  --set redis.auth.enabled=true \
  --set redis.auth.password="change-me-redis" \
  --set secret.env.ConnectionStrings__DefaultConnection="Host=postgis.internal;Database=honua;Username=honua;Password=<secret>;SSL Mode=Require" \
  --set secret.env.HONUA_ADMIN_PASSWORD="ExampleAdminPassword1!" \
  --set secret.env.Security__ConnectionEncryption__MasterKey="example-connection-encryption-master-key"
```

When `redis.enabled=true`, `redis.auth.enabled` must remain true. In
chart-managed-secret mode, the chart auto-populates `ConnectionStrings__redis`
from `redis.auth.password` unless you set `secret.env.ConnectionStrings__redis`
yourself. Non-development deployments require Redis-backed durable
feature-change event storage, so existing-secret mode must provide the runtime
environment key through the named Secret or `extraEnvFrom`; the chart does not
create it.

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

The chart default keeps `config.env.HONUA_SKIP_MIGRATIONS=false`. If you set it to `true`, the chart does not run an alternate migration job; you own schema convergence before traffic reaches the deployment.

Use `RollingUpdate` only when the migration set is forward and backward compatible across the old and new Honua images:

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 0
    maxUnavailable: 1
```

The values schema rejects `RollingUpdate` when both `maxSurge` and
`maxUnavailable` are zero, including string and percent forms such as `"0"` and
`"0%"`.

Readiness at `/healthz/ready` is the chart signal that startup and migrations completed.

## Preflight hook

`preflight.enabled=true` renders Helm `pre-install,pre-upgrade` hooks that validate required secret keys, PostgreSQL TCP reachability, Redis TCP reachability for non-development deployments, and target image registry reachability before the Deployment is applied. The default timeout is 5 seconds per reachability check. The kubelet remains authoritative for full image pull success, especially for private registries.

For the dev-only PostgreSQL subchart or chart-managed Redis, the initial install preflight validates required secret keys and registry reachability but defers TCP reachability only when the chart auto-generates the subchart connection string. Pre-upgrade hooks, and installs with a supplied connection string, check the configured endpoint.

Disable only when an external controller or restricted network policy prevents the hook from reaching the database or registry:

```yaml
preflight:
  enabled: false
```

To keep secret and database checks but skip the registry `/v2/` check:

```yaml
preflight:
  registryCheck:
    enabled: false
```

## Release evidence and rollback

Set release metadata so operators can capture what is running:

```yaml
release:
  id: "honua-2026-05-preview"
  manifest: "https://example.com/release/honua-2026-05-preview.json"
  digest: "sha256:<64 lowercase hex characters>"
  appVersion: "2026.05.0"
```

`release.id` and the effective app version (`release.appVersion`, or `Chart.AppVersion` when the override is empty) are used as Kubernetes label values, so keep them 63 characters or less and use only letters, numbers, `_`, `.`, or `-`, starting and ending with a letter or number. Put free-form build metadata in `release.manifest` and use `release.digest` for the associated SHA-256 evidence.

The chart writes this metadata to Deployment/Pod labels and annotations, Pod-template `honua.io/*` annotations, the release-info ConfigMap, the container environment, Helm NOTES, and `helm test` output. Chart/app evidence changes roll pods so `HONUA_CHART_VERSION` and `HONUA_APP_VERSION` in the container environment refresh.

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
  name: my-honua-secret   # Must contain ConnectionStrings__DefaultConnection, HONUA_ADMIN_PASSWORD, and Security__ConnectionEncryption__MasterKey
```

You may also set `secret.create=false` and provide only `extraEnvFrom` sources.
In that mode the referenced sources must expose `ConnectionStrings__DefaultConnection`,
`HONUA_ADMIN_PASSWORD`, `Security__ConnectionEncryption__MasterKey`, and
`ConnectionStrings__redis` for non-development deployments.

For example, another controller can own the Secret while the chart consumes it
through `extraEnvFrom`:

```yaml
secret:
  create: false
extraEnvFrom:
  - secretRef:
      name: my-honua-secret
```

With `preflight.enabled=true`, the preflight Job reads the same external Secret
and `extraEnvFrom` sources and fails if `ConnectionStrings__DefaultConnection`
or `HONUA_ADMIN_PASSWORD` are missing, if `HONUA_ADMIN_PASSWORD` does not meet
production strength rules, or if
`Security__ConnectionEncryption__MasterKey` is missing or shorter than 32
characters. For non-development deployments, it also fails if
`ConnectionStrings__redis` is missing or the Redis endpoint is unreachable.

## Key values

| Value | Default | Description |
|-------|---------|-------------|
| `replicaCount` | 1 | Number of pods. Use 3+ for production. |
| `image.tag` | `latest-aot` | Image tag. AOT recommended. Leave empty when `image.digest` is set. |
| `image.digest` | `""` | Immutable image digest. Preferred for production and rollback evidence. |
| `image.pullPolicy` | `Always` | Pull policy. Must be `IfNotPresent` or `Never` when `image.digest` is set. |
| `release.id` | `""` | Operator release identifier surfaced in labels, annotations, ConfigMap, NOTES, and tests. |
| `release.manifest` | `""` | URL, path, or commit for the release manifest. |
| `release.digest` | `""` | `sha256:<64 lowercase hex characters>` digest of the release manifest or bundle. |
| `release.appVersion` | `""` | Optional label-safe evidence override for `app.kubernetes.io/version`, Pod-template annotations, and release-info output. |
| `strategy.type` | `Recreate` | Upgrade strategy. `Recreate` is safe for inline migrations. |
| `strategy.rollingUpdate` | `maxSurge: 0`, `maxUnavailable: 1` | RollingUpdate settings used only when `strategy.type=RollingUpdate`; both values cannot be zero. |
| `preflight.enabled` | true | Enable pre-install/pre-upgrade validation hook. |
| `preflight.timeoutSeconds` | 5 | Timeout for database and registry reachability checks. |
| `preflight.registryCheck.enabled` | true | Check the target image registry `/v2/` endpoint before apply. |
| `terminationGracePeriodSeconds` | 60 | Pod shutdown grace period for lock release and clean termination. |
| `resources` | requests `250m`/`512Mi`, limits `2`/`2Gi` | CPU/memory requests and limits. Tune for production workloads. |
| `autoscaling.enabled` | false | Enable HPA. |
| `autoscaling.targetCPUUtilizationPercentage` | `70` | CPU utilization threshold for scale decisions. |
| `autoscaling.targetMemoryUtilizationPercentage` | `80` | Memory utilization threshold for scale decisions. |
| `autoscaling.behavior` | scale up/down policies | autoscaling/v2 behavior policies and stabilization windows. |
| `ingress.enabled` | false | Enable ingress. |
| `config.env.*` | N/A | Non-secret environment variables stored in a ConfigMap. |
| `secret.env.*` | N/A | Secret environment variables stored in a chart-managed Secret. |
| `secret.create` | true | Create the runtime Secret and preflight hook Secret from `secret.env`. |
| `secret.name` | `""` | Reference an existing secret instead of chart-managed secret data. Required when `secret.create=false` unless `extraEnvFrom` supplies the required variables. |
| `extraEnv` | `[]` | Additional env vars from external sources (e.g. `valueFrom`). |
| `extraEnvFrom` | `[]` | Additional ConfigMap/Secret sources used by the app and preflight hook. Can satisfy required secret variables when `secret.create=false`. |
| `postgresql.enabled` | false | Enable Bitnami PostgreSQL subchart (dev only). |
| `redis.enabled` | false | Enable Bitnami Redis subchart. Requires `redis.auth.enabled=true`; chart-managed secrets can derive the Redis connection string from `redis.auth.password`. Non-development installs need either this or an external `ConnectionStrings__redis`. |

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
helm lint honua -f honua/ci-values/base.yaml
helm lint honua -f honua/values-dev.yaml
helm lint honua -f honua/values-stage.yaml
helm lint honua -f honua/values-prod.yaml
helm template honua honua -f honua/ci-values/base.yaml
helm template honua honua -f honua/ci-values/digest.yaml
helm template honua honua -f honua/ci-values/rolling-update.yaml
helm template honua honua -f honua/ci-values/postgresql.yaml
helm template honua honua --is-upgrade -f honua/ci-values/postgresql.yaml
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
