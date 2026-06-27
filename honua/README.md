# Honua Helm Chart

Deploys Honua Server on Kubernetes with optional Bitnami PostgreSQL and Redis subcharts.

- Source of truth: `oci://ghcr.io/honua-io/charts/honua`
- GitHub Releases: <https://github.com/honua-io/honua-helm/releases>
- Versioning and cut procedure: see [`RELEASING.md`](https://github.com/honua-io/honua-helm/blob/trunk/RELEASING.md).

## Install (published chart)

```bash
helm registry login ghcr.io
helm upgrade --install honua oci://ghcr.io/honua-io/charts/honua --version X.Y.Z \
  --set config.env.ASPNETCORE_ENVIRONMENT="Development" \
  --set secret.env.ConnectionStrings__DefaultConnection="Host=postgres;Database=honua;Username=honua;Password=honua" \
  --set secret.env.HONUA_ADMIN_PASSWORD="ExampleAdminPassword1!" \
  --set secret.env.Security__ConnectionEncryption__MasterKey="example-connection-encryption-master-key"
```

The chart enforces its values contract at render time, so the install above sets
all required secrets: `HONUA_ADMIN_PASSWORD` must be at least 16 characters with
upper/lower/digit/special, and `Security__ConnectionEncryption__MasterKey` must
be at least 32 characters. `ASPNETCORE_ENVIRONMENT=Development` keeps this a
minimal evaluation install; non-development deployments additionally require
`ConnectionStrings__redis`. For production, install from `values-prod.yaml` with
a pinned image (see [Production example](#production-example)).

Published chart cuts pin `image.tag` to a concrete `vX.Y.Z-aot` server release;
the local repo default `latest-aot` is dev-only.

## Upgrade

```bash
helm registry login ghcr.io
helm pull oci://ghcr.io/honua-io/charts/honua --version X.Y.Z   # optional, to inspect
helm upgrade --install honua oci://ghcr.io/honua-io/charts/honua --version X.Y.Z \
  -f values-prod.yaml
```

Value keys under `image`, `service`, `ingress`, `config.env`, `secret.env`,
`postgresql`, and `redis` are stable within a chart major version. Operators
upgrading from in-monorepo deployments do not need value migrations within
chart 0.x — see [`docs/MIGRATION.md`](https://github.com/honua-io/honua-helm/blob/trunk/docs/MIGRATION.md). The
operator-ready values contract that formalizes this guarantee is tracked in
[honua-helm#6](https://github.com/honua-io/honua-helm/issues/6).

## Versioning

Chart `version` (semver) bumps independently of honua-server. Chart
`appVersion` mirrors the honua-server release the chart is validated against.
Tag scheme: `chart-vX.Y.Z` here, `vX.Y.Z` in honua-server. Full procedure
in [`RELEASING.md`](https://github.com/honua-io/honua-helm/blob/trunk/RELEASING.md).

## Quick start (from a checkout)

For local development and Helm smoke testing, use the development overlay:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency build honua
helm upgrade --install honua honua -f honua/values-dev.yaml
```

For direct installs with external data services, the default preflight hook
checks the configured PostgreSQL/PostGIS and Redis hosts before the Deployment
is applied.

`helm dependency build` uses the committed `Chart.lock`, matching CI and release packaging.

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
| `values-stage.yaml` | Staging validation with existing-secret mode, ingress, observability, and OpenTelemetry. Single-instance (`replicaCount: 1`, `Deployment__Mode=SingleInstance`, HPA disabled); opt into MultiNode for autoscaled HA. |
| `values-prod.yaml` | Customer-operated production posture with existing-secret mode, ingress, observability, and OpenTelemetry. Single-instance (`replicaCount: 1`, `Deployment__Mode=SingleInstance`, HPA disabled); opt into MultiNode for autoscaled HA. |

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

# The shipped prod/stage overlays run single-instance (Deployment__Mode=SingleInstance,
# HPA disabled) and are consistent out of the box. To run autoscaled HA, opt into
# MultiNode here. The chart fails at render time if autoscaling is enabled while
# Deployment__Mode is SingleInstance, so these settings must change together.
# MultiNode additionally requires ConnectionStrings__redis (runtime Secret) and a
# shared cloud FileStorage:Provider of AwsS3 or AzureBlob (Local is rejected).
config:
  env:
    Deployment__Mode: "MultiNode"

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 20
  targetCPUUtilizationPercentage: 70
  # Memory scaling is off by default (0). The .NET server-GC heap rarely returns
  # committed memory to the OS, so a memory target tends to peg replicas at
  # maxReplicas and never scale down. Set this > 0 only after confirming memory
  # tracks load for your workload.
  targetMemoryUtilizationPercentage: 0
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
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency build honua
helm upgrade --install honua honua -f honua/values-prod.yaml -f customer-prod.yaml
```

## External PostGIS database (recommended for production)

For production, point `ConnectionStrings__DefaultConnection` at a managed PostGIS database (e.g., Amazon RDS, Azure Flexible Server) rather than using the Bitnami subchart.

> The Bitnami PostgreSQL subchart **does not include PostGIS**. Honua requires PostGIS for migrations and spatial queries. For anything beyond local development, use an external PostGIS-enabled database.

## PostgreSQL subchart (dev only)

```bash
helm upgrade --install honua honua \
  --set config.env.ASPNETCORE_ENVIRONMENT=Development \
  --set postgresql.enabled=true \
  --set postgresql.auth.username=honua \
  --set postgresql.auth.password=honua \
  --set postgresql.auth.database=honua \
  --set secret.env.HONUA_ADMIN_PASSWORD="ExampleAdminPassword1!" \
  --set secret.env.Security__ConnectionEncryption__MasterKey="example-connection-encryption-master-key"
```

The dev-only PostgreSQL subchart example runs in `Development` so it does not
require Redis. For non-development environments, enable Redis (below) or supply
`secret.env.ConnectionStrings__redis`.

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
| `image.tag` | `latest-aot` | Image tag. AOT recommended. Pin to `vX.Y.Z-aot` for production; leave empty when `image.digest` is set. |
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
| `preflight.retries` | 3 | Attempts per reachability probe (database/Redis/registry) before the hook fails. The hook runs with `backoffLimit: 0`, so in-script retries absorb transient DNS/egress/registry blips. Set to 1 to disable. |
| `preflight.retryDelaySeconds` | 3 | Delay between preflight reachability probe attempts. |
| `preflight.registryCheck.enabled` | true | Check the target image registry `/v2/` endpoint before apply. |
| `terminationGracePeriodSeconds` | 60 | Pod shutdown grace period for lock release and clean termination. |
| `tmpVolume.enabled` | true | Mount a writable `/tmp` emptyDir. Required because `readOnlyRootFilesystem` is true and the server writes temp files; disable only if the image never writes to disk. |
| `tmpVolume.sizeLimit` | `""` | Optional `emptyDir` size cap for `/tmp` (e.g. `1Gi`). |
| `affinity` | `{}` | Pod affinity rules. When empty, the chart applies a soft pod anti-affinity spreading replicas across nodes for multi-replica workloads (`autoscaling.enabled` or `replicaCount > 1`). |
| `resources` | requests `250m`/`512Mi`, limits `2`/`2Gi` | CPU/memory requests and limits. Tune for production workloads. |
| `autoscaling.enabled` | false | Enable HPA. Requires `config.env.Deployment__Mode=MultiNode` (plus Redis and a shared cloud `FileStorage:Provider`); render fails if enabled while mode is `SingleInstance`. |
| `autoscaling.targetCPUUtilizationPercentage` | `70` | CPU utilization threshold for scale decisions. |
| `autoscaling.targetMemoryUtilizationPercentage` | `0` | Memory utilization threshold. `0` disables memory-based scaling (the default), because the .NET server-GC heap rarely releases committed memory and a memory target tends to peg replicas at `maxReplicas`. Opt in (`> 0`) only after confirming memory tracks load. |
| `autoscaling.behavior` | scale up/down policies | autoscaling/v2 behavior policies and stabilization windows. |
| `podDisruptionBudget.enabled` | `null` | Render a PodDisruptionBudget. `null` auto-enables it for multi-replica workloads (`autoscaling.enabled` or `replicaCount > 1`); set `true`/`false` to force. |
| `podDisruptionBudget.minAvailable` | `null` | Minimum available pods during voluntary disruptions. Mutually exclusive with `maxUnavailable`. |
| `podDisruptionBudget.maxUnavailable` | `null` | Maximum unavailable pods during voluntary disruptions. Defaults to `25%` when both fields are unset. |
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

## Observability and metrics

Honua Server emits OpenTelemetry traces and metrics when
`config.env.HONUA_OPENTELEMETRY` (or `HONUA_OBSERVABILITY`) is `"true"` (the
default in the stage and prod overlays). That telemetry needs a **receiver**, so
the chart fails render when observability is enabled without one. Configure at
least one of the following.

### OpenTelemetry collector (OTLP, push)

```yaml
config:
  env:
    HONUA_OPENTELEMETRY: "true"
observability:
  otlpEndpoint: "http://otel-collector.observability.svc:4317"
  otlpProtocol: "grpc"   # or "http/protobuf" (port 4318)
```

When `observability.otlpEndpoint` is set the chart injects the standard
`OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_PROTOCOL` environment
variables so the server's OpenTelemetry SDK exports to the collector.

### Prometheus (scrape)

For a Prometheus Operator cluster, enable a `ServiceMonitor` and the baseline
`PrometheusRule` availability alerts:

```yaml
metrics:
  serviceMonitor:
    enabled: true
    path: /metrics
    interval: 30s
    labels:
      release: kube-prometheus-stack   # match your Prometheus ruleSelector/serviceMonitorSelector
  prometheusRule:
    enabled: true
    labels:
      release: kube-prometheus-stack
```

For a non-Operator Prometheus that discovers targets via annotations, use
`metrics.serviceAnnotations.enabled: true` instead, which stamps
`prometheus.io/scrape`, `prometheus.io/port`, and `prometheus.io/path` on the
Service.

The `ServiceMonitor`/`PrometheusRule` resources require the Prometheus Operator
CRDs and a server build that exposes a Prometheus endpoint at the configured
port/path. The shipped `PrometheusRule` alerts on availability
(`kube_deployment_status_replicas_available == 0`) and crash-looping via
kube-state-metrics, so it does not depend on any application metric being
emitted. Application-level alerts (for example a GeoServices in-band error-rate
alert) are added once the server exposes the corresponding metric.

| Value | Default | Description |
|-------|---------|-------------|
| `observability.otlpEndpoint` | `""` | OTLP collector endpoint; injected as `OTEL_EXPORTER_OTLP_ENDPOINT`. Required (with the scrape options) when observability is enabled. |
| `observability.otlpProtocol` | `grpc` | OTLP protocol (`grpc` or `http/protobuf`). |
| `metrics.serviceMonitor.enabled` | false | Render a Prometheus Operator `ServiceMonitor`. |
| `metrics.serviceAnnotations.enabled` | false | Stamp `prometheus.io/*` scrape annotations on the Service. |
| `metrics.prometheusRule.enabled` | false | Render the baseline availability `PrometheusRule`. |

## Geospatial HPA tuning guidance

The default HPA thresholds are tuned for mixed geospatial workloads:
- `targetCPUUtilizationPercentage: 70` for CPU-heavy spatial predicates and tile generation.
- `targetMemoryUtilizationPercentage: 0` (memory scaling off) by default. The .NET
  server-GC heap holds onto committed memory and rarely releases it to the OS, so a
  memory utilization target tends to ratchet replicas up to `maxReplicas` and never
  scale them back down, defeating elastic scale-down. Scale on CPU and opt into
  memory scaling deliberately (see below).
- `scaleUp` stabilization of 60s with 50% growth to react quickly to traffic ramps.
- `scaleDown` stabilization of 300s with 10% shrink to avoid thrash after short spikes.

For dataset-specific tuning:
- Increase `maxReplicas` only after validating PostgreSQL connection limits.
- Enable memory-based scaling (`targetMemoryUtilizationPercentage` > 0, for example
  80-90) only if large map exports are common, the workload's memory actually
  tracks load, and you have confirmed it scales back down rather than pegging at
  `maxReplicas`.
- Reduce `scaleDown` aggressiveness further for workloads with repeated 3-10 minute query bursts.

## Local validation

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency build honua
helm lint honua
helm lint honua -f honua/ci-values/base.yaml
helm lint honua -f honua/values-dev.yaml
helm lint honua -f honua/values-stage.yaml
# values-prod.yaml clears image.tag to force an explicit pin; supply one to lint/template it.
helm lint honua -f honua/values-prod.yaml --set image.tag=v0.0.0-aot
helm template honua honua -f honua/ci-values/base.yaml
helm template honua honua -f honua/ci-values/digest.yaml
helm template honua honua -f honua/ci-values/rolling-update.yaml
helm template honua honua -f honua/ci-values/postgresql.yaml
helm template honua honua --is-upgrade -f honua/ci-values/postgresql.yaml
helm template honua-dev honua -f honua/values-dev.yaml
helm template honua-stage honua -f honua/values-stage.yaml
helm template honua-prod honua -f honua/values-prod.yaml --set image.tag=v0.0.0-aot
helm template honua-stage honua -f honua/values-stage.yaml --is-upgrade
helm test honua  # After install, runs the test hook
```

For install/upgrade smoke against a real API server, see `../docs/MIGRATION.md`.
Running `helm template honua honua` without a values file fails by design because
the baseline contract leaves required runtime secrets empty.

For ingress testing on a local Kubernetes cluster, see [K3d + Helm guide](https://github.com/honua-io/honua-server/blob/trunk/docs/contributor/development/k3d-helm.md).
