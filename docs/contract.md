# Honua Helm Chart Operator Contract

This document defines the operator-facing contract for the Honua Helm chart.
It is intended for release, GitOps, marketplace, and customer-operated
deployments that need predictable upgrade and rollback behavior.

## Ownership

The chart owns Kubernetes resources needed to run Honua Server: Deployment,
Service, optional Ingress, ServiceAccount, ConfigMap, Secret, release-info
ConfigMap, Helm test hook, and Helm preflight hooks.

The chart does not own database backups, database schema downgrade tooling,
cluster ingress controllers, external DNS, certificate issuers, external
Secret controllers, or cloud marketplace entitlement flows.

## Migrations

Honua Server runs database migrations inline during application startup.
Migrations are serialized by the server with a PostgreSQL advisory lock. The
chart does not run a separate migration Job because Honua Server does not
currently expose a migrate-only mode.

The chart default keeps `config.env.HONUA_SKIP_MIGRATIONS=false`. If an
operator overrides this to `true`, the chart does not provide an alternate
migration path; the operator owns schema convergence before serving traffic.

The default Deployment strategy is:

```yaml
strategy:
  type: Recreate
```

`Recreate` is the safe default for inline migrations because it scales old
pods down before new pods start. This prevents old and new Honua versions from
serving against the same database while a migration is in progress.
When desired replicas are greater than one, this safety property causes planned
upgrade downtime while old pods are stopped and replacement pods start.

Operators may opt into `RollingUpdate` only when the target migration set is
forward and backward compatible across the old and new images:

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 0
    maxUnavailable: 1
```

When `strategy.type=RollingUpdate`, the values schema rejects a zero rollout
budget where both `maxSurge` and `maxUnavailable` are `0`, `"0"`, or `"0%"`.
At least one of those values must allow Kubernetes to make rollout progress.

## Health And Probes

The chart relies on these Honua health endpoints:

- `/healthz/live`: process liveness.
- `/healthz/ready`: readiness after dependencies and startup work are ready.

The readiness contract is stability-bearing: `/healthz/ready` must not return
success until Honua startup and migrations are complete. The Helm test hook
polls this endpoint and emits release metadata so test logs can be used as
deployment evidence.

Honua readiness checks migration state before runtime dependencies. Migration
failure or in-progress migration state keeps the pod not ready; successful or
explicitly skipped migrations allow database and other dependency checks to run.

Probe defaults are migration-tolerant:

```yaml
startupProbe:
  periodSeconds: 10
  failureThreshold: 60
livenessProbe:
  periodSeconds: 15
  failureThreshold: 6
terminationGracePeriodSeconds: 60
```

Operators can extend probes in values for large databases or long migration
windows without forking the chart.

## Preflight Hook

When `preflight.enabled=true`, the chart renders Helm `pre-install` and
`pre-upgrade` hooks before the Deployment is applied.

The preflight Job validates:

- `ConnectionStrings__DefaultConnection` is present.
- `HONUA_ADMIN_PASSWORD` is present, at least 16 characters long, and includes
  uppercase, lowercase, digit, and special characters.
- `Security__ConnectionEncryption__MasterKey` is present and at least 32
  characters long.
- `ConnectionStrings__redis` is present for non-development deployments,
  because Honua Server requires durable feature-change event storage outside
  Development/Test environments.
- The PostgreSQL host and port parsed from the connection string accept TCP
  connections. During the initial install only, this reachability check is
  skipped when the chart auto-generates the connection string for its own
  PostgreSQL subchart because Helm pre-install hooks run before subchart
  Services and Pods are created; pre-upgrade hooks check the existing database.
- The Redis host and port parsed from `ConnectionStrings__redis` accept TCP
  connections. During the initial install only, this reachability check is
  skipped when the chart auto-generates the connection string for its own Redis
  subchart for the same Helm hook ordering reason.
- The target image registry `/v2/` endpoint is reachable when
  `preflight.registryCheck.enabled=true`.

For chart-managed Secrets, a temporary hook Secret is rendered from the same
helper as the runtime Secret. For externally managed environment sources, the
Job reads from `secret.name` when provided and from every `extraEnvFrom` source.
When `secret.create=false`, values validation requires either `secret.name` or
at least one `extraEnvFrom` source.

The default hook image is `curlimages/curl:8.5.0`, and the default reachability
timeout is `preflight.timeoutSeconds=5`. Operators can set
`preflight.registryCheck.enabled=false` to keep secret and database checks while
skipping the registry `/v2/` check.

The preflight registry check does not authenticate to the registry or replace
the kubelet's image pull. The kubelet remains authoritative for full image
pull success, including private registry credentials and node-level pull
policy behavior.

## Secret and Config Rotation

The chart injects runtime credentials and settings through `envFrom`
(`secretRef` / `configMapRef`), which Kubernetes reads only when a container
starts. To make in-place edits roll the pods, the Deployment stamps a
`checksum/config` and `checksum/secret` annotation derived from the
**chart-managed** ConfigMap and Secret. A `helm upgrade` that changes
`config.env` or `secret.env` therefore changes the pod spec and triggers a
controlled rollout.

That checksum covers only chart-managed objects. It does **not** cover
externally-managed sources -- `secret.create=false` with `secret.name` (for
example the production `honua-prod-runtime` Secret), `config.create=false`, an
External Secrets Operator source, or anything supplied via `extraEnvFrom`. The
chart cannot see those contents at render time, so rotating such a Secret or
ConfigMap in place produces a byte-identical Deployment, performs no rollout,
and leaves the running pods on the previous credentials.

After rotating an externally-managed Secret or ConfigMap, force a rollout
explicitly:

```bash
kubectl rollout restart deployment/<release>-honua -n <namespace>
```

or change a value under `podAnnotations` (for example a rotation timestamp) so
the upgrade renders a new pod spec and Kubernetes performs a controlled
rollout. The preflight Job validates external secret keys at install time, but
it does not trigger a rollout for content-only rotations.

## Image Identity

Production deployments should pin by digest:

```yaml
image:
  repository: ghcr.io/honua-io/honua-server
  tag: ""
  digest: sha256:<64 lowercase hex characters>
  pullPolicy: IfNotPresent
```

The chart renders digest-pinned images as:

```text
repository@sha256:...
```

The values schema and template validations enforce:

- exactly one of `image.tag` or `image.digest`;
- digest format `sha256:<64 lowercase hex characters>`;
- `image.pullPolicy` is `IfNotPresent` or `Never` when `image.digest` is set.

Mutable tags such as `latest` and `latest-aot` remain available for development
but are not rollback-safe evidence.

## Release Evidence

The `release` block carries operator-supplied evidence metadata:

```yaml
release:
  id: honua-2026-05-preview
  manifest: https://example.invalid/release/honua-2026-05-preview.json
  digest: sha256:<64 lowercase hex characters>
  appVersion: ""
```

`release.id` and the effective app version are rendered as Kubernetes label
values. The effective app version is `release.appVersion` when set, otherwise
`Chart.AppVersion`. The schema and template validation limit these values to 63
characters and permit letters, numbers, `_`, `.`, and `-`, with a letter or
number at both ends. SemVer build metadata with `+` is not label-safe; put
free-form build evidence in `release.manifest` and use `release.digest` for the
associated SHA-256 evidence.

`release.digest`, when set, uses the same `sha256:<64 lowercase hex characters>`
format as `image.digest`.

The chart surfaces release evidence in:

- Deployment labels and annotations;
- Pod labels and annotations;
- Pod-template `honua.io/*` annotations for image, chart, app, and release
  identity;
- the release-info ConfigMap;
- the Honua container environment via the release-info ConfigMap;
- `helm test` output;
- Helm NOTES.

Chart and app version evidence are included on the Pod template annotations so
evidence-only changes that affect `HONUA_CHART_VERSION` or `HONUA_APP_VERSION`
roll pods and refresh the release-info environment.

Capture the current release evidence with:

```bash
kubectl get configmap <release>-honua-release-info -o yaml
helm test <release>
```

## Rollback

Rollback is a Helm release operation:

```bash
helm history <release>
helm rollback <release> <revision>
```

Digest-pinned values make rollback deterministic because the previous Helm
revision points back to the previous image digest.

The chart cannot guarantee database schema downgrade compatibility. If a
migration is not backward compatible with the rolled-back Honua image, the
operator must restore the database from a backup or roll forward to a
compatible image.

## Contract Versioning

Values and behavior described in this document are stability-bearing. A
breaking change to migration semantics, readiness semantics, image identity
rules, preflight behavior, or release evidence surfaces requires at least a
minor chart version bump and explicit upgrade notes.
