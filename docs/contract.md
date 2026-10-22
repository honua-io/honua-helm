---
type: reference
title: "Operator contract"
description: "The operator-facing contract this chart honours: what is guaranteed across upgrades, what may change, and what an operator is responsible for."
resource: "https://github.com/honua-io/honua-helm/blob/trunk/honua/values.yaml"
tags: [contract, operator, upgrades]
---
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

The chart supports two migration paths. With the default
`migrations.job.enabled: false`, Honua Server runs database migrations inline
during application startup, serialized by a PostgreSQL advisory lock, and the
effective strategy is `Recreate`. With `migrations.job.enabled: true`, a
`pre-install,pre-upgrade` hook Job runs the same image in migrate-only mode
(`HONUA_MIGRATE_ONLY=true`, honua-server#6479) with the Deployment's
configuration and `migrationSafety.*` env. The Job applies the migrations under
every `Database:MigrationSafety` gate, prints one `honua.migrate-only/v1` JSON
summary line to stdout and exits with a typed code. It has `backoffLimit: 0`,
`restartPolicy: Never`, `activeDeadlineSeconds` (default 1800) and
`hook-delete-policy: before-hook-creation`. Helm applies the Deployment only
after it exits `0`; the Deployment then carries `HONUA_SKIP_MIGRATIONS=true`
and an effective strategy of `RollingUpdate` unless `strategy.type` is set. A
non-zero exit fails the install or upgrade with the Deployment unchanged. Exit
`5` means a reviewed contract migration needs `HONUA_APPROVE_CONTRACT_MIGRATIONS`
set to the printed nonce for one upgrade. The chart README lists every exit
code.

The Job is off by default for now and becomes the recommended production path.
It requires a server image at or after the first release that ships
`HONUA_MIGRATE_ONLY` (today: the next release after 2026.1); an older image
ignores the switch, serves, and the hook fails at `activeDeadlineSeconds`.

The chart owns `HONUA_SKIP_MIGRATIONS` while the Job is enabled and
`HONUA_MIGRATE_ONLY` always: render fails when either is set in `config.env`,
`secret.env` or `extraEnv` (and `HONUA_MIGRATE_ONLY` in the GP worker env). The
chart does not set `HONUA_SKIP_MIGRATIONS` on the inline path. If an operator
sets it there through an external source, nothing converges the schema, and the
operator owns that before serving traffic.

### Contract-phase migrations

The server classifies schema-narrowing migrations as contract phase. Values
under `migrationSafety.*` render `Database__MigrationSafety__*` env on the
server container only when set:

| Value | Server setting | Empty / null means |
| --- | --- | --- |
| `migrationSafety.contractApplyPolicy` | `ContractApplyPolicy` (`Gate` or `Auto`) | server default `Gate`: on an existing database, pending reviewed contract migrations are refused until `HONUA_APPROVE_CONTRACT_MIGRATIONS` carries the one-shot nonce printed in the refusal |
| `migrationSafety.backupCommand` | `BackupCommand` | no hook. When set, the server runs the shell command inside its container just before contract migrations apply on an existing database. A non-zero exit aborts. The tool must exist in the image or a mounted volume. |
| `migrationSafety.enforce` | `Enforce` | server default `true`: contract migrations without the compatibility-review marker are rejected |

`HONUA_APPROVE_CONTRACT_MIGRATIONS` is not a chart value. Set the nonce through
`secret.env` or `extraEnv` for the single upgrade that needs it, then remove it.
Render fails when a `Database__MigrationSafety__*` key set by these values is
also present in `config.env`, `secret.env` or `extraEnv`.

`helm rollback` is safe only when the previous image recognizes every applied
migration. Otherwise its pods refuse to start with `schema_reader_incompatible`,
and recovery is a database restore or a roll forward. The chart cannot
downgrade the schema, and `helm rollback` runs no pre-upgrade hook. Images at
schema 135 and later (honua-server#6478) record forward-compatibility
declarations, and a rolled-back image at schema 135 or later that migrates
inline accepts an expand-only migration it does not ship once it verifies that
declaration, so such a rollback needs no restore. Images at schema 134 and
earlier, journals written before 135, contract scripts and scripts marked
reader-incompatible still refuse. Pods with `HONUA_SKIP_MIGRATIONS=true` never
accept declarations and keep the strict check. See the chart README,
"Upgrades: expand/contract".

The default `strategy.type` is empty, which the chart resolves to `Recreate`
on the inline path and `RollingUpdate` when `migrations.job.enabled` is true.
An explicit `Recreate` or `RollingUpdate` always wins.

`Recreate` is the safe default for inline migrations because it scales old
pods down before new pods start. This prevents old and new Honua versions from
serving against the same database while a migration is in progress.
When desired replicas are greater than one, this safety property causes planned
upgrade downtime while old pods are stopped and replacement pods start.

Operators may opt into `RollingUpdate` only when the target migration set is
forward and backward compatible across the old and new images. In practice
that means an expand-only release whose migrations the previous version can
read. This holds on the migration-Job path too: the Job removes the race
between migrating pods, but old pods still serve the migrated schema until
they are replaced.

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
`templates/validations.yaml` applies the same rule when the chart chooses
`RollingUpdate`.

## Upgrade Execution

For Helm 3, the recommended guarded upgrade path is:

```bash
helm upgrade --install <release> ./honua -f <values> --atomic --timeout 10m
```

`--atomic` implies `--wait` and automatically runs `helm rollback` to the
previous revision if the upgrade does not reach a ready state before
`--timeout` elapses. The readiness scope that gates `--wait`/`--atomic` is the
`/healthz/ready` contract in [Health And Probes](#health-and-probes): startup,
migrations, and dependency checks must all complete. Size `--timeout` above
the worst-case migration duration; migrations run inline in the new pod
during a `Recreate` rollout, and a timeout that is too tight aborts a slow but
otherwise successful migrating upgrade. With `migrations.job.enabled`, also size
it above `migrations.job.activeDeadlineSeconds`, because Helm waits for the
hook Job before it applies the Deployment.

Migration compatibility is the operator's responsibility, not something the
chart can verify: `RollingUpdate` requires forward/backward-compatible
migrations across the old and new images (see Migrations above), while
`Recreate` tolerates a breaking migration because old pods are fully stopped
first.

`helm history <release>` retains prior revisions (manifest, values, and
chart/app version) up to Helm's `--history-max` limit (default 10, set at
install/upgrade time). Old Helm revisions are release-metadata retention only
-- they do not retain database state or, for externally-managed
Secrets/ConfigMaps, their prior content (see Secret and Config Rotation
below). Digest-pinned `image.digest` values make the retained revision's
*application artifact* identity exact; this is distinct from the release
evidence retention described here.

## Deploy Target Registration

`controlPlane.deployTarget.enabled` (default `true`) renders
`ControlPlane__DeployTargets__0__*` environment variables identifying this
chart's Deployment as a stable deploy target for Honua Server's control
plane (`ConfigurationDeployTargetRegistry`). Without this, a chart-installed
server registers no deploy target, and the control plane's
`/api/v1/admin/deploy/preflight` and `deploy.rollback` capability surfaces
have nothing to plan against.

The registered `Backend` is always `honua-gitops-kubernetes`, the Honua
GitOps hand-off backend. That backend's `GetCapabilitiesAsync` always returns
`SupportsRollback=false`, and its `RollbackAsync` always returns
`ManualInterventionRequired` -- it hands the desired revision to an external
GitOps controller and cannot itself revert a running workload. Registering
this target, or documenting `helm rollback` in this contract, therefore does
not advertise telemetry-driven automatic rollback. Recovery for a
chart-installed server is the manual `helm rollback` procedure described
below; an operator wanting executable automatic recovery needs a real
backend with the matching controller and RBAC/CRDs installed and configured
as a distinct deploy target, which this chart does not provide.

The values schema and `templates/validations.yaml` both reject any
`controlPlane.deployTarget.backend` value other than
`honua-gitops-kubernetes`, and reject an empty resolved `targetId`,
`targetName`, or `environment`. This keeps the registration truthful: an
operator cannot configure the chart to claim a backend whose prerequisites it
does not install, and the chart cannot silently register an unusable target.
Set `controlPlane.deployTarget.enabled=false` to opt an installation out of
registration entirely.

### Deploy telemetry connections

`controlPlane.telemetryConnections` (default `[]`) declares Prometheus query
connections (`ControlPlane__TelemetryConnections__<n>__*`) in the same
`<fullname>-deploy-target` ConfigMap. The ConfigMap renders whenever target
registration is on or connections are declared. An auth header value is never
written to the ConfigMap. It is projected from an existing Secret through
`secretKeyRef` (`authHeaderSecretRef`). A `baseUrl` must be `https://` unless
the connection sets `allowPrivateNetworks: true`, which mirrors the server's
SSRF guard and is required for an in-cluster `http://` Prometheus.

`controlPlane.deployTarget.telemetry.connection` sets the chart target's
`telemetry.connection` parameter (`ControlPlane__DeployTargets__0__ParameterEntries__*`).
It must name a declared `connectionId`. `telemetry.parameters` carries other
`telemetry.*` keys, for example `telemetry.prometheus.job`. A telemetry
connection does not change the backend's `SupportsRollback=false`: recovery
stays manual.

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

CI proves that restoration with `scripts/distinct-digest-smoke.sh`: revisions
1 and 2 use distinct immutable server digests, a durable database row is seeded
before upgrade, and each phase captures manifests, values, workload
UIDs/imageIDs, release metadata, checksums, Helm-test logs, and a runtime marker
checksum. Rollback must restore revision 1's kubelet imageID and runtime marker
while preserving the seed; a deliberate non-restoration assertion must fail.

The chart cannot guarantee database schema downgrade compatibility. If a
migration is not backward compatible with the rolled-back Honua image, the
operator must restore the database from a backup or roll forward to a
compatible image.

CI also runs the out-of-band path in kind: a fresh install and an upgrade with
`migrations.job.enabled=true` must each run the `<release>-honua-migrate` hook
Job to exit `0`, print the `honua.migrate-only/v1` summary line, and leave the
Deployment on `RollingUpdate` with `HONUA_SKIP_MIGRATIONS=true`.
That lane runs the customer-facing image: the honua-server digest of the latest
published honua-io/honua-release release, falling back to `nightly-aot` only
while no published release ships migrate-only mode. The step summary names
the image used, and the lane fails rather than skips when no image qualifies.

Rollback targets must include the server's schema-reader guard (schema 135 or
later across additive migrations), a contract-phase migration is never rolled
back without restoring the pre-upgrade backup, and rollback targets are pinned
by digest. `honua-2026.1` is unguarded and not a safe rollback target across
any migration (honua-server#6484). See the chart README, "Rollback target
eligibility".

## Contract Versioning

Values and behavior described in this document are stability-bearing. A
breaking change to migration semantics, readiness semantics, image identity
rules, preflight behavior, or release evidence surfaces requires at least a
minor chart version bump and explicit upgrade notes.
