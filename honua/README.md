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
  tag: "v1.2.3-aot"   # Pin to a release AOT tag
  pullPolicy: IfNotPresent

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

For production, pin to a release tag: `v1.2.3-aot` (AOT) or `v1.2.3` (JIT).

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
| `image.tag` | `latest-aot` | Image tag. AOT recommended. Pin to `vX.Y.Z-aot` for production. |
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
- **Readiness**: `/healthz/ready` (is the database connected?)
- **Startup**: `/healthz/live` with 30 retries (initial boot tolerance)

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
