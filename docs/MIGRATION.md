# Migration: from `honua-server/infrastructure/helm/honua` to `honua-io/honua-helm`

This page captures where the chart came from, the value-contract continuity
operators can rely on after the split, and the smoke commands used for chart
contract changes.

## Origin

The Honua chart was previously vendored inside the server repository at
`honua-server/infrastructure/helm/honua/`. It moved to `honua-io/honua-helm`
under [honua-server PR #336](https://github.com/honua-io/honua-server/pull/336),
which is also the import reference for this repo's first two commits:

- `2e68ac3` - `chore: initial import from honua-server (#336)`
- `c9c92c2` - `ci: add initial workflows after monorepo split (#336)`

The `infrastructure/helm/` tree in `honua-server` is no longer the source of
truth. It was retired in the `docs: remove stale and migrated artifacts after
repo split` change on the server side.

## Where to file chart issues

File chart issues, RFCs, and discussion in **`honua-io/honua-helm`**:

- Issues: <https://github.com/honua-io/honua-helm/issues>
- Discussions: <https://github.com/honua-io/honua-helm/discussions>

Issues filed against `honua-server` for chart concerns will be redirected here.
Server image, runtime, and migration concerns continue to belong in
`honua-server`.

## Value-contract continuity

The values surface was preserved across the split. Operators upgrading from an
in-monorepo deployment do **not** need value migrations within chart `0.x`.
The stable keys are:

- `image.*`
- `service.*`
- `ingress.*`
- `config.env.*`
- `secret.env.*`
- `extraEnv`
- `extraEnvFrom`
- `postgresql.*` (Bitnami subchart, dev only)
- `redis.*` (Bitnami subchart)

The chart values contract is documented in `docs/values-contract.md` and
enforced where Helm can validate it through `honua/values.schema.json` and
template guards.

Required runtime environment keys:

- `ConnectionStrings__DefaultConnection`
- `HONUA_ADMIN_PASSWORD` with at least 16 characters, including uppercase,
  lowercase, digit, and special characters
- `Security__ConnectionEncryption__MasterKey` with at least 32 characters
- `ConnectionStrings__redis` for non-development deployments when the chart is
  not creating that key from `redis.enabled=true`

For chart-managed secrets, Helm validates required runtime keys through
template guards during rendering. For existing-secret mode, Helm validates that
a source is named, but the external Secret contents must be validated by the
operator or release lane.

## Upgrade path from a monorepo install

If your existing release was installed from
`honua-server/infrastructure/helm/honua`, switch to the published chart with:

```bash
helm registry login ghcr.io
helm upgrade --install honua oci://ghcr.io/honua-io/charts/honua --version X.Y.Z \
  -f your-existing-values.yaml
```

No value-key changes are required within chart `0.x`. Pin `image.tag` to a
concrete `vX.Y.Z-aot` server release. Published chart packages stamp
`image.tag` at package time; see [`../RELEASING.md`](../RELEASING.md).

## Chart 0.2.0 Upgrade Notes

Chart `0.2.0` adds the operator-ready contract for inline migrations, release
evidence, preflight checks, digest-pinned images, and rollback smoke. It does
not remove or rename existing values.

Operators upgrading from `0.1.x` should review these default behavior changes:

- `strategy.type` now defaults to `Recreate`. This is safer for inline
  migrations but causes planned upgrade downtime when desired replicas are
  greater than one.
- `preflight.enabled` defaults to `true`. The hook validates required
  credentials, PostgreSQL TCP reachability, Redis TCP reachability for
  non-development deployments, and registry `/v2/` reachability before apply.
  Initial install skips the PostgreSQL or Redis reachability check only when
  the chart auto-generates that connection string for its own subchart.
- Image identity must set exactly one of `image.tag` or `image.digest`. Digest
  installs must use `image.pullPolicy: IfNotPresent` or `Never`.
- `release.id` and the effective app version (`release.appVersion` or
  `Chart.AppVersion`) must be valid Kubernetes label values.

## Breaking Changes Policy

Future breaking changes must follow this policy:

- Keep deprecated values accepted for at least one minor release when possible.
- Document old value, new value, impact, and removal target in this file.
- Update `honua/values.yaml`, `honua/values.schema.json`, `honua/README.md`,
  and `docs/values-contract.md` in the same PR.
- Use a major chart version for removing values, renaming values, changing
  required external Secret keys, or changing install defaults in a way that
  breaks existing releases.

## Render smoke

Run these targeted client-side checks after values-contract changes:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency build honua

helm lint honua -f honua/ci-values/base.yaml
helm lint honua -f honua/values-dev.yaml
helm lint honua -f honua/values-stage.yaml
helm lint honua -f honua/values-prod.yaml

helm template honua ./honua -f honua/ci-values/base.yaml
helm template honua ./honua -f honua/ci-values/digest.yaml
helm template honua ./honua -f honua/ci-values/rolling-update.yaml
helm template honua ./honua -f honua/ci-values/postgresql.yaml
helm template honua ./honua --is-upgrade -f honua/ci-values/postgresql.yaml
helm template honua-dev ./honua -f honua/values-dev.yaml
helm template honua-stage ./honua -f honua/values-stage.yaml
helm template honua-prod ./honua -f honua/values-prod.yaml
helm template honua-stage ./honua -f honua/values-stage.yaml --is-upgrade
```

These commands prove the chart contract renders and the staged install/upgrade
render paths are syntactically valid. The baseline `honua/values.yaml` is a
documented contract with empty required secret placeholders; use
`honua/ci-values/base.yaml` or an environment overlay for render smoke.

## Install/Upgrade/Rollback Smoke

CI runs a cluster-backed smoke path in `.github/workflows/ci.yml`. It creates a
kind cluster, starts PostGIS and Redis services, installs
`honua/ci-values/upgrade-base.yaml`, runs `helm test`, upgrades with
`honua/ci-values/upgrade-target.yaml`, runs `helm test` again, rolls back to
revision 1, and captures Helm history, NOTES, release-info ConfigMap output,
events, and pod state as evidence.

The historical ticket #2 install/upgrade smoke also requires a Kubernetes
cluster. For a disposable local API-acceptance smoke, use k3d:

```bash
cluster="honua-helm-smoke"
namespace="honua-smoke"

k3d cluster create "$cluster" --agents 0 --wait --timeout 180s
kubectl create namespace "$namespace"
kubectl -n "$namespace" create secret generic honua-stage-runtime \
  --from-literal=ConnectionStrings__DefaultConnection='Host=postgis.internal;Database=honua;Username=honua;Password=smoke' \
  --from-literal=HONUA_ADMIN_PASSWORD='SmokeAdminPassword1!' \
  --from-literal=Security__ConnectionEncryption__MasterKey='smoke-connection-encryption-master-key-0001' \
  --from-literal=ConnectionStrings__redis='redis.internal:6379'

helm upgrade --install honua-stage ./honua -n "$namespace" -f honua/values-stage.yaml --wait=false --timeout 2m
helm upgrade --install honua-stage ./honua -n "$namespace" -f honua/values-stage.yaml --set podLabels.smokeRun=upgrade --wait=false --timeout 2m
helm status honua-stage -n "$namespace"
kubectl get deployment,service,ingress,hpa -n "$namespace"

helm uninstall honua-stage -n "$namespace"
k3d cluster delete "$cluster"
```

The k3d smoke proves Helm can install and upgrade the staged values contract
into a real API server with `--wait=false`. The CI smoke is the current
readiness, test, and rollback evidence path for this chart. Terraform
provisioning, marketplace package validation, and sales-offer alignment remain
release-lane items owned by their respective repositories and tracked in
`docs/values-contract.md`.

## Cross-references

- Server repo: <https://github.com/honua-io/honua-server>
- Chart split PR: <https://github.com/honua-io/honua-server/pull/336>
- Chart feature map: [`features/README.md`](features/README.md)
- Release runbook: [`../RELEASING.md`](../RELEASING.md)
- Install/upgrade smoke evidence: [`smoke/ticket-2-helm-smoke.md`](smoke/ticket-2-helm-smoke.md)
- Install/upgrade/rollback smoke evidence (chart 0.2.0): [`smoke/ticket-6-helm-smoke.md`](smoke/ticket-6-helm-smoke.md)
- Operator-ready chart contract: [`values-contract.md`](values-contract.md)
