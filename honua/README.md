# Honua Helm Chart

Deploys Honua Server on Kubernetes with optional Bitnami PostgreSQL and Redis subcharts.

> **Preview:** the Helm/Kubernetes deployment path is not qualified for production in 2026.1.

- Publish target: `oci://ghcr.io/honua-io/charts/honua`
- GitHub Releases: <https://github.com/honua-io/honua-helm/releases>
- Versioning and cut procedure: see [`RELEASING.md`](https://github.com/honua-io/honua-helm/blob/trunk/RELEASING.md).

> **Status:** no chart has been published to the OCI registry yet (neither a
> `chart-vX.Y.Z` release has run), so
> the OCI registry commands below do not currently resolve. Availability is
> determined by whether a chart package exists at the OCI reference — check
> with an anonymous `helm show chart oci://ghcr.io/honua-io/charts/honua` — not
> by release tags alone. Until a chart is published, install from a checkout — see the
> [repo README quick start](https://github.com/honua-io/honua-helm#quick-start-development-install).

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

The development overlay pins the 2026.1 candidate server image by digest so the quick start
does not depend on the moving `latest-aot` tag.

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

The dev-only PostgreSQL subchart example runs in `Development`. Production
SingleInstance deployments are also legitimately Redis-free. MultiNode
deployments must enable chart-managed Redis (below) or supply
`secret.env.ConnectionStrings__redis`.

When `postgresql.enabled=true`, `postgresql.auth.username`,
`postgresql.auth.password`, and `postgresql.auth.database` are required. In
chart-managed-secret mode, the chart auto-populates
`ConnectionStrings__DefaultConnection` if you don't supply one.
During the initial install with that auto-generated connection string, preflight
skips PostgreSQL TCP reachability because Helm pre-install hooks run before
subchart Services and Pods are created. Pre-upgrade hooks check the existing
PostgreSQL endpoint.

## Optional chart-managed Redis

```bash
helm upgrade --install honua honua \
  --set redis.enabled=true \
  --set redis.auth.enabled=true \
  --set redis.auth.password="change-me-redis" \
  --set secret.env.ConnectionStrings__DefaultConnection="Host=postgis.internal;Database=honua;Username=honua;Password=<secret>;SSL Mode=Require" \
  --set secret.env.HONUA_ADMIN_PASSWORD="ExampleAdminPassword1!" \
  --set secret.env.Security__ConnectionEncryption__MasterKey="example-connection-encryption-master-key"
```

When `redis.enabled=true`, `redis.auth.enabled` must remain true and
`redis.auth.password` must be nonempty, even with an explicit client connection
string. Delimiter-containing passwords require both the server password and an
explicit, correctly escaped client connection string. In
chart-managed-secret mode, the chart auto-populates `ConnectionStrings__redis`
from `redis.auth.password` unless you set `secret.env.ConnectionStrings__redis`
yourself. Non-development deployments require Redis-backed durable
feature-change event storage, so existing-secret mode must provide the runtime
environment key through the named Secret or `extraEnvFrom`; the chart does not
create it.

Redis stores its append-only data on an 8Gi ReadWriteOnce PVC mounted at `/data`.
Set `redis.persistence.size` and `redis.persistence.storageClass` before installing
(empty storage class uses the cluster default). Pod replacement and image upgrades
reuse the claim; password changes roll the Redis pod. This single-node deployment
has downtime during restarts. Migrating from the former Bitnami subchart creates a
new claim: back up and restore the old Redis data separately before serving traffic.

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

For an atomic guarded upgrade on Helm 3, prefer `--atomic` with an explicit
timeout so a failed rollout auto-rolls-back to the prior revision instead of
leaving a partially-applied Deployment:

```bash
helm upgrade --install honua ./honua -f honua/values-prod.yaml \
  --atomic --timeout 10m
```

`--atomic` waits for the readiness scope described above (startup + migrations
+ dependency checks via `/healthz/ready`, bounded by `startupProbe` and
`readinessProbe`) and automatically runs `helm rollback` to the previous
revision if that wait fails or times out; it implies `--wait`. Size `--timeout`
above the worst-case migration duration for your database, or a slow migration
can be aborted mid-run. `helm history` retains prior revisions (and their
values/manifest) so a subsequent manual `helm rollback` remains available even
without `--atomic`; see [Release evidence and rollback](#release-evidence-and-rollback)
for what that rollback can and cannot restore.

## Deploy target registration

`controlPlane.deployTarget.enabled` (default `true`) registers this chart's
installed Deployment as a stable target with Honua Server's control plane by
rendering `ControlPlane__DeployTargets__0__*` environment variables (consumed
by `ConfigurationDeployTargetRegistry`). Without this, a chart-installed
server registers no deploy target and the `/api/v1/admin/deploy/preflight` and
`deploy.rollback` capability surfaces have nothing to plan against.

The only backend this chart wires up is the Honua GitOps hand-off backend,
`honua-gitops-kubernetes`. That backend always reports
`SupportsRollback=false`: a chart-installed server advertises **manual
recovery only**. Registering a target, or documenting `helm rollback` here,
does not add telemetry-driven automatic rollback — that requires a real
executable backend (for example an Argo Rollouts controller with the matching
RBAC/CRDs), which this chart does not install. The values schema and
`templates/validations.yaml` both reject any other `controlPlane.deployTarget.backend`
value for exactly this reason: no other backend's prerequisites exist in this
chart, so accepting one would advertise a capability the installation cannot
execute.

```yaml
controlPlane:
  deployTarget:
    enabled: true                          # false opts this install out entirely
    targetId: ""                           # empty uses the chart fullname
    backend: "honua-gitops-kubernetes"      # the only supported value
    environment: ""                        # empty uses config.env.ASPNETCORE_ENVIRONMENT
    targetName: ""                         # empty uses the chart fullname
    artifactReference: ""                  # empty uses the rendered image reference
```

## Geoprocessing on Kubernetes Jobs

Preview (2026.2), off by default. With
`geoprocessing.kubernetesJobs.enabled=true`, asynchronous geoprocessing runs as
`batch/v1` Jobs instead of inside the server process. The server's Kubernetes
Job batch compute backend (`KubernetesJobBatchComputeBackend`, backend id
`honua-kubernetes-job`) creates one Job per execution attempt.

Each Job runs the server image in its worker-only profile. The server stamps
`HONUA_OPERATION_ID`, `HONUA_EXECUTION_ATTEMPT` and the other launch variables
on the Job. The worker records the result in the shared Redis job store and
exits.

```yaml
geoprocessing:
  kubernetesJobs:
    enabled: true
    serviceAccount:
      annotations: {}          # IRSA: eks.amazonaws.com/role-arn of the GP job role
```

### What the chart renders

| Object | Purpose |
| --- | --- |
| ConfigMap `<fullname>-gp-kubernetes-jobs` | `ControlPlane__Kubernetes__*` (backend defaults) and `ControlPlane__ExecutionWorkloads__<index>__*` (the GP workload: `TargetKind=KubernetesJob`, `Backend=honua-kubernetes-job`). The server loads it through `envFrom`. |
| Secret `<fullname>-gp-kubernetes-jobs` | The workload's `ParameterEntries`: `k8s.node_selector` and one `env.<NAME>` per worker environment variable. The server loads it through `envFrom`. |
| ServiceAccount `<fullname>-gp-job` | The identity the Job pods run as (`ControlPlane:Kubernetes:DefaultServiceAccount`). No token is mounted. |
| Role + RoleBinding `<fullname>-gp-kubernetes-jobs` | In the Job namespace, for the server's service account: `batch/jobs` create/get/list/watch/delete, `pods` get/list/watch, `pods/log` get. Nothing cluster-wide, no Secrets. |
| Hook Job `<fullname>-gp-rbac-check` | Runs on `post-install`, `post-upgrade` and `helm test`, as the server's service account. It checks each permission above with a SelfSubjectAccessReview. A missing permission fails the release with `HONUA_GP_K8S_RBAC_MISSING`. |

The server Deployment also changes in two ways:

- It mounts its service account token. The backend discovers the API server,
  token and CA in-cluster.
- It treats Redis as required, so the preflight hook checks Redis.

### Values

| Value | Default | Server setting |
| --- | --- | --- |
| `enabled` | `false` | Registers the workload and renders the objects above. |
| `namespace` | release namespace | `ControlPlane:Kubernetes:DefaultNamespace`. Another namespace must already exist; the job ServiceAccount, Role and RoleBinding are rendered into it. |
| `image.repository` / `tag` / `digest` | the chart's server image | `ControlPlane:Kubernetes:DefaultImage`. Keep the default: the server and worker must share the execution contract. |
| `image.pullPolicy` | `image.pullPolicy` | `ControlPlane:Kubernetes:DefaultImagePullPolicy` |
| `image.maxSupportedContractVersion` | `1` | `ControlPlane:Kubernetes:DefaultImageMaxSupportedContractVersion` |
| `imagePullSecrets` | names from `image.pullSecrets` | `ControlPlane:Kubernetes:DefaultImagePullSecrets` |
| `serviceAccount.create` / `name` / `annotations` | `true` / `<fullname>-gp-job` / `{}` | `ControlPlane:Kubernetes:DefaultServiceAccount` |
| `rbac.create` | `true` | Renders the Role and RoleBinding above. The RBAC check still runs when this is `false`. |
| `resources.requests` / `limits` | `250m`/`512Mi`, `2`/`2Gi` | `ControlPlane:Kubernetes:Default{Cpu,Memory}{Request,Limit}` |
| `ttlSecondsAfterFinished` | `3600` | `ControlPlane:Kubernetes:DefaultTtlSecondsAfterFinished`. The server raises any value below 30 to 30. |
| `activeDeadlineSeconds` | unset | `ControlPlane:Kubernetes:DefaultActiveDeadlineSeconds`. A job's own timeout policy wins. |
| `nodeSelector` | `{}` | The workload's `k8s.node_selector` parameter |
| `workload.index` / `id` / `name` | `2` / `geoprocessing-kubernetes-job` / `Geoprocessing (Kubernetes Job)` | `ControlPlane:ExecutionWorkloads:<index>` |
| `inheritServerEnvironment` | `true` | Copies the server's environment into the worker (see below). |
| `workerEnv` | `{}` | Extra worker env. An empty value drops an inherited entry. |
| `allowInlineWorkerSecrets` | `false` | Disposable clusters only (see below). |

The server does not read some Job settings, so the chart does not expose them:

- `backoffLimit` is always `0`. A failed pod fails the Job, and the server's
  reconciler owns retries. Each retry is a fresh Job named `-a<attempt>`.
- The Job spec has no tolerations or affinity. For placement, use
  `nodeSelector` or a namespace default (for example a `PodNodeSelector`
  annotation or a Kyverno policy).
- The Job spec has no volumes, `envFrom` or `secretKeyRef`.

`workload.index` defaults to `2`. The server's `appsettings.json` already
declares `ControlPlane:ExecutionWorkloads:0` (the local baseline) and `:1` (an
AWS Batch placeholder). The AWS Batch entry stays inactive until its ARNs are
set. Keep it that way. If both are active, the server routes GP to the first
non-local workload, which is AWS Batch.

### Worker environment and secrets

The worker composes the same services as the server. It needs the same
database, the Redis job store and the connection-encryption master key.
Redis-backed non-development deployments also need the operation key-ring
certificate.

The server builds the Job pod spec itself. It can set only literal env values,
which it takes from the workload's `env.<NAME>` parameters. It cannot use
`secretKeyRef`, `envFrom` or volumes. It also writes those literal values into
the Job object and the durable job record.

So credentials reach the worker only as **cloud secret references**:
`aws:secretsmanager:<arn>` or `azure:keyvault:<vault>/<secret>`. The worker
resolves them at startup with the job service account's cloud identity. AWS
Batch and Lambda workers use the same reference contract.

With `inheritServerEnvironment: true`, the worker gets:

- every `config.env` entry except `ASPNETCORE_URLS` and the `ControlPlane__*`
  settings (the worker neither serves HTTP nor dispatches jobs);
- the licensing values;
- each `secret.env` entry whose value is a cloud secret reference.

The chart never copies plain `secret.env` values, the chart-derived PostgreSQL
and Redis connection strings, or the contents of an existing Secret
(`secret.create=false`). For those, set references in `workerEnv`.

The chart refuses to render when:

- A worker credential is not a reference. Credentials are
  `ConnectionStrings__*` and any name containing password, master key, API
  key, token, PKCS#12, secret key, private key, license content or the
  audit-chain key.
- The chart manages the Secret (`secret.create=true`) and the worker lacks
  `ConnectionStrings__DefaultConnection`, `ConnectionStrings__redis` or
  `Security__ConnectionEncryption__MasterKey`. With an existing Secret
  (`secret.create=false`) the chart cannot see the server's credentials, so it
  renders, and the install NOTES print a warning naming the missing settings.
  Every GP Job fails until `workerEnv` carries references for them.
- The worker would inherit `Operations__SecretChannel__KeyRingCertificatePath`.
  Job pods cannot mount the file. Supply
  `Operations__SecretChannel__KeyRingCertificatePkcs12` as a reference
  instead, and drop the path with
  `workerEnv.Operations__SecretChannel__KeyRingCertificatePath: ""`.

The worker serves no HTTP, so it does not need `HONUA_ADMIN_PASSWORD`. The
chart never copies a plain admin password. The `HONUA_*` launch variables are
reserved: the chart and the server both reject them in `workerEnv`.

`allowInlineWorkerSecrets: true` copies plain secret values into the Job spec,
including the chart-derived connection strings. Use it only on a throwaway
cluster with no secret store, such as kind in CI. Anyone who can read Jobs in
the namespace, or the job store, can then read those values.

The preflight hook accepts cloud secret references but cannot resolve them,
because it has no cloud identity. For those values it checks presence only and
skips the TCP and complexity checks. The server validates the resolved values
at startup.

### Redis

GP on Kubernetes Jobs requires Redis. Redis is the durable job store, and the
worker refuses to start without it. When the backend is enabled, the chart
requires `ConnectionStrings__redis` for the server, as it does for MultiNode.

- **External Redis** (ElastiCache, MemoryDB, Azure Cache): set
  `ConnectionStrings__redis`. TLS and auth go in the connection string, for
  example `<primary endpoint>:6379,password=<token>,ssl=true`. A secret
  reference in `secret.env.ConnectionStrings__redis` serves the server and the
  workers. A plain string in `secret.env` or an existing Secret serves the
  server only; give the workers a reference in
  `workerEnv.ConnectionStrings__redis`.
- **Chart-managed Redis** (`redis.enabled`): the derived connection string
  carries the password inline. It reaches the workers only with
  `allowInlineWorkerSecrets`. Otherwise, store the connection string in a
  secret manager and set its reference in `workerEnv.ConnectionStrings__redis`.

### EKS: mapping the honua-iac `aws-eks` outputs

The honua-iac `aws-eks` module is the EKS GA certification cell: GP on
Kubernetes Job runners, Redis on or off, and a PostGIS datastore. It creates:

- RDS PostGIS, ElastiCache and the Secrets Manager entries;
- two workload IAM roles, `server` and `gp-job`.

It creates no Kubernetes objects. This chart owns the service accounts and the
Job RBAC.

| `aws-eks` output | Chart value |
| --- | --- |
| `kubernetes_namespace` | `helm install -n <namespace>`. The IAM trust is scoped to this namespace. |
| `server_service_account_name` | `serviceAccount.name`. The chart default is `<fullname>`. |
| `server_service_account_annotations` | `serviceAccount.annotations`. Used for IRSA; empty under Pod Identity. |
| `gp_job_namespace` | `geoprocessing.kubernetesJobs.namespace` |
| `gp_job_service_account_name` | `geoprocessing.kubernetesJobs.serviceAccount.name` |
| `gp_job_service_account_annotations` | `geoprocessing.kubernetesJobs.serviceAccount.annotations` |
| `gp_job_image` | Leave empty to run the chart's server image. Otherwise set `geoprocessing.kubernetesJobs.image.*`. |
| `chart_config_env` | `config.env`, as is. It holds no credentials. It carries `ControlPlane__Kubernetes__{DefaultNamespace,DefaultServiceAccount,DefaultImage}`, the CORS origins, the operation policy rules and operator secret references (key ring, audit-chain key). When the matching `geoprocessing.kubernetesJobs` value is empty, the chart takes the Job namespace, service account name and image from those `ControlPlane__Kubernetes__*` entries, so the ServiceAccount and RBAC it renders match what the server is told. `config.env` loads after the chart's own ConfigMap, so its entries win on the server. |
| `honua_server_environment` | The complete environment: `chart_config_env` plus the credential references. Put the credential references in `secret.env`, or in `geoprocessing.kubernetesJobs.workerEnv` when the credentials themselves live in an existing Secret (`secret.create=false`). The worker needs `ConnectionStrings__DefaultConnection`, `ConnectionStrings__redis` and `Security__ConnectionEncryption__MasterKey`. |
| `gp_job_data_bucket_arn` | The IAM roles grant the worker and server S3 access. Set the server's storage settings in `config.env`; the worker inherits them. |
| `workload_identity_mode` | `pod_identity` (the default): no annotations. The EKS Pod Identity associations name the service accounts, so the names must match. `irsa`: copy the `*_service_account_annotations` outputs. Both `annotations` values are optional and default to `{}`. |

```yaml
serviceAccount:
  name: honua-server                       # server_service_account_name
  annotations: {}                          # server_service_account_annotations (irsa)
secret:
  env:
    ConnectionStrings__DefaultConnection: "aws:secretsmanager:<db_connection arn>"
    HONUA_ADMIN_PASSWORD: "aws:secretsmanager:<admin_password arn>"
    Security__ConnectionEncryption__MasterKey: "aws:secretsmanager:<master_key arn>"
    ConnectionStrings__redis: "aws:secretsmanager:<redis_connection arn>"
    Operations__SecretChannel__KeyRingCertificatePkcs12: "aws:secretsmanager:<key ring arn>"
geoprocessing:
  kubernetesJobs:
    enabled: true
    namespace: ""                          # gp_job_namespace (empty = release namespace)
    serviceAccount:
      name: honua-gp-job                   # gp_job_service_account_name
      annotations: {}                      # gp_job_service_account_annotations (irsa)
```

`honua/ci-values/gp-kubernetes-jobs.yaml` is a rendered example of this shape.

A Redis-off cell cannot run GP on Kubernetes Jobs, because the worker has no
job store. Leave `geoprocessing.kubernetesJobs.enabled=false` there.

### Verifying

```bash
helm test <release>                                   # includes the gp-rbac-check hook
kubectl get jobs -n <gp namespace> -l app.kubernetes.io/managed-by=honua-controlplane
```

Jobs carry the `honua.io/operation-id` and `honua.io/workload-kind=geoprocessing`
labels.

## Preflight hook

`preflight.enabled=true` renders Helm `pre-install,pre-upgrade` hooks that validate required secret keys, PostgreSQL TCP reachability, Redis TCP reachability for non-development deployments, and target image registry reachability before the Deployment is applied. The default timeout is 5 seconds per reachability check. The kubelet remains authoritative for full image pull success, especially for private registries.

For the dev-only PostgreSQL subchart or chart-managed Redis, the initial install preflight validates required secret keys and registry reachability but defers TCP reachability only when the chart auto-generates the subchart connection string. Redis pre-upgrade hooks defer the derived-endpoint probe if the new Service does not yet exist, including migration from the former Bitnami dependency. Once the Service exists, upgrades check it. Supplied connection strings are always checked.

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
| `lifecycle` | `{}` | Container lifecycle hooks passed through verbatim. For zero-downtime `RollingUpdate` / HPA scale-down, set a `preStop` sleep (e.g. `preStop.exec.command: ["/bin/sh","-c","sleep 5"]`) so Service endpoint removal propagates to kube-proxy/ingress before SIGTERM; keep it shorter than `terminationGracePeriodSeconds`. Left empty under the default `Recreate` strategy, where a preStop delay only slows termination. |
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
| `security.requestSecretReferences.allowedEnvironmentVariables` | `[]` | Exact environment variable names a request may name as `env:NAME`. Renders `Security__RequestSecretReferences__AllowedEnvironmentVariables__<n>`. |
| `security.requestSecretReferences.allowedEnvironmentVariablePrefixes` | `[]` | Environment variable name prefixes a request may name as `env:NAME` (never matches a name containing `__`). Renders `Security__RequestSecretReferences__AllowedEnvironmentVariablePrefixes__<n>`. |
| `security.requestSecretReferences.allowedSecretReferencePrefixes` | `[]` | Whole-reference prefixes for the other providers, including the provider segment (e.g. `aws:secretsmanager:honua/imports/`). Renders `Security__RequestSecretReferences__AllowedSecretReferencePrefixes__<n>`. Empty lists keep the server's deny-by-default policy; see the [values contract](../docs/values-contract.md#request-supplied-secret-references). |
| `extraEnv` | `[]` | Additional env vars from external sources (e.g. `valueFrom`). |
| `extraEnvFrom` | `[]` | Additional ConfigMap/Secret sources used by the app and preflight hook. Can satisfy required secret variables when `secret.create=false`. |
| `postgresql.enabled` | false | Enable Bitnami PostgreSQL subchart (dev only). |
 | `redis.enabled` | false | Enable Bitnami Redis subchart. Requires `redis.auth.enabled=true`; chart-managed secrets can derive the Redis connection string from `redis.auth.password`. Non-development installs need either this or an external `ConnectionStrings__redis`. |
 | `controlPlane.deployTarget.enabled` | true | Register this Deployment as a control-plane deploy target. `false` opts out entirely. |
 | `controlPlane.deployTarget.backend` | `honua-gitops-kubernetes` | Deploy backend identifier. Only this truthful hand-off value (`SupportsRollback=false`) is accepted; render fails otherwise. |
 | `controlPlane.deployTarget.targetId` / `targetName` | `""` | Target identity. Empty uses the chart fullname for both. |
 | `controlPlane.deployTarget.environment` | `""` | Target environment label. Empty uses `config.env.ASPNETCORE_ENVIRONMENT`. |
 | `controlPlane.deployTarget.artifactReference` | `""` | Target artifact reference. Empty uses the rendered image reference. |

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

For a Prometheus Operator cluster, enable a `ServiceMonitor` and the
`PrometheusRule`:

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
port/path.

### Alerting (SLO rules + receivers)

The `PrometheusRule` has two rule groups when `metrics.prometheusRule.enabled`:

- **`honua.availability`** — infrastructure alerts on kube-state-metrics
  (`kube_deployment_status_replicas_available == 0`, crash-looping). No
  application metric required.
- **`honua.slo`** (`metrics.prometheusRule.slo.enabled`, default true) —
  request-availability, combined error-rate, and multi-window burn-rate alerts
  built on the server's `honua_request_error_total` counter over the
  `honua_serving_request_duration_ms_count` request total. These deliberately
  **include the GeoServices in-band 200-with-`{error}` signal**: GeoServices returns
  HTTP 200 with an `{error}` body for Esri-client compatibility, so those failures
  are invisible to load-balancer 5xx metrics. The server increments
  `honua_request_error_total` with `in_band="true"` for them, so the budgeted ratio
  is transport 5xx plus in-band errors, and `HonuaGeoServicesInBandErrorRateHigh`
  alerts on the GeoServices-scoped slice directly. Ordinary out-of-band 4xx is
  excluded so routine client probing cannot burn the budget. Series names and scopes
  come from honua-server's `observability/slo-metric-contract.json`.
  Thresholds/windows mirror the honua-devops SLO rules and are fully overridable
  under `metrics.prometheusRule.slo`.

  By default, every application counter selector is scoped with the Prometheus
  Operator target labels `namespace="<release namespace>"` and
  `service="<release fullname>"`. This prevents a rule installed for one tenant
  or release from aggregating another Honua deployment. A non-empty
  `metrics.prometheusRule.slo.metricSelector` replaces the derived selector. Set
  it when an annotation-based or custom scrape configuration uses different
  target labels; the selector must identify only the intended Honua deployment.

Wire delivery with the `AlertmanagerConfig` receiver surface (does **not** deploy
Alertmanager; the Alertmanager Operator merges it by namespace/label selector).
Each SLO alert carries `severity` and `route` labels a route can match on:

```yaml
metrics:
  alertmanagerConfig:
    enabled: true
    labels:
      alertmanagerConfig: honua   # match your Alertmanager alertmanagerConfigSelector
    route:
      receiver: honua-slack
      groupBy: ["alertname", "route"]
      routes:
        - matchers: [{ name: route, value: pagerduty-critical }]
          receiver: honua-pagerduty
    receivers:
      - name: honua-slack
        slackConfigs:
          - apiURL: { name: honua-alertmanager-secrets, key: slackApiUrl }
            channel: "#honua-alerts"
      - name: honua-pagerduty
        pagerdutyConfigs:
          - routingKey: { name: honua-alertmanager-secrets, key: pagerdutyRoutingKey }
```

| Value | Default | Description |
|-------|---------|-------------|
| `observability.otlpEndpoint` | `""` | OTLP collector endpoint; injected as `OTEL_EXPORTER_OTLP_ENDPOINT`. Required (with the scrape options) when observability is enabled. |
| `observability.otlpProtocol` | `grpc` | OTLP protocol (`grpc` or `http/protobuf`). |
| `metrics.serviceMonitor.enabled` | false | Render a Prometheus Operator `ServiceMonitor`. |
| `metrics.serviceAnnotations.enabled` | false | Stamp `prometheus.io/*` scrape annotations on the Service. |
| `metrics.prometheusRule.enabled` | false | Render the `PrometheusRule` (infra + SLO alerts). |
| `metrics.prometheusRule.slo.enabled` | true | Emit the `honua.slo` group (availability / error-rate / burn-rate / in-band). Applies only when `prometheusRule.enabled`. |
| `metrics.prometheusRule.slo.metricSelector` | `""` (automatic) | PromQL label matchers scoping the counters. Empty derives `namespace` and `service` from the Helm release; a non-empty value replaces the derived selector. |
| `metrics.alertmanagerConfig.enabled` | false | Render an `AlertmanagerConfig` (receivers + route). Requires at least one receiver. |

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

For ingress testing on a local Kubernetes cluster, see [K3d + Helm guide](https://github.com/honua-io/honua-server/blob/trunk/docs/internal/contributor/development/k3d-helm.md).

### 2026.1 licensing default

`licensing.mode: Disabled` explicitly sets `Licensing__Mode=Disabled`. With
preflight enabled, an authenticated post-install/post-upgrade Job verifies the
running server reports disabled licensing; `helm test` repeats the assertion.
`licensing.edition` and `licensing.licenseSecretRef` preserve the 2026.2 re-enable
path. See the [values contract](../docs/values-contract.md#licensing-in-20261-and-re-enabling-in-20262)
for credentials, hook timing, private images, and the Enabled configuration.
