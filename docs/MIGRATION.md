# Honua Helm Migration Notes

## Values Contract

The chart values contract is documented in `docs/values-contract.md` and enforced
where Helm can validate it through `honua/values.schema.json` and template
guards.

Required runtime environment keys:

- `ConnectionStrings__DefaultConnection`
- `HONUA_ADMIN_PASSWORD` with at least 16 characters, including uppercase,
  lowercase, digit, and special characters
- `Security__ConnectionEncryption__MasterKey` with at least 32 characters
- `ConnectionStrings__redis` for non-development deployments when the chart is
  not creating that key from `redis.enabled=true`

For chart-managed secrets, Helm validates required runtime keys through template
guards during rendering. For existing-secret mode, Helm validates that a source
is named, but the external Secret contents must be validated by the operator or
release lane.

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
- Update `honua/values.yaml`, `honua/values.schema.json`, `honua/README.md`, and
  `docs/values-contract.md` in the same PR.
- Use a major chart version for removing values, renaming values, changing
  required external Secret keys, or changing install defaults in a way that
  breaks existing releases.

## Render Smoke

Run these targeted client-side checks after values-contract changes:

```bash
helm dependency update honua

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
