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

The default Deployment strategy is:

```yaml
strategy:
  type: Recreate
```

`Recreate` is the safe default for inline migrations because it scales old
pods down before new pods start. This prevents old and new Honua versions from
serving against the same database while a migration is in progress.

Operators may opt into `RollingUpdate` only when the target migration set is
forward and backward compatible across the old and new images:

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 0
    maxUnavailable: 1
```

## Health And Probes

The chart relies on these Honua health endpoints:

- `/healthz/live`: process liveness.
- `/healthz/ready`: readiness after dependencies and startup work are ready.

The readiness contract is stability-bearing: `/healthz/ready` must not return
success until Honua startup and migrations are complete. The Helm test hook
polls this endpoint and emits release metadata so test logs can be used as
deployment evidence.

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
- `HONUA_ADMIN_PASSWORD` is present.
- The PostgreSQL host and port parsed from the connection string accept TCP
  connections.
- The target image registry `/v2/` endpoint is reachable when
  `preflight.registryCheck.enabled=true`.

For chart-managed Secrets, a temporary hook Secret is rendered from the same
helper as the runtime Secret. For externally managed Secrets, the Job reads
from `secret.name` and `extraEnvFrom`.

The preflight registry check does not authenticate to the registry or replace
the kubelet's image pull. The kubelet remains authoritative for full image
pull success, including private registry credentials and node-level pull
policy behavior.

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

The chart surfaces release evidence in:

- Deployment labels and annotations;
- Pod labels and annotations;
- `honua.io/*` annotations for image and release identity;
- the release-info ConfigMap;
- the Honua container environment via the release-info ConfigMap;
- `helm test` output;
- Helm NOTES.

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
