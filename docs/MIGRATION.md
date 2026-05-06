# Honua Helm Migration Notes

## Values Contract

The chart values contract is documented in `docs/values-contract.md` and enforced
where Helm can validate it through `honua/values.schema.json` and template
guards.

Required runtime environment keys:

- `ConnectionStrings__DefaultConnection`
- `HONUA_ADMIN_PASSWORD`
- `ConnectionStrings__redis` when Redis is used and the chart is not creating
  that key in a chart-managed Secret

For chart-managed secrets, Helm validates required runtime keys through template
guards during rendering. For existing-secret mode, Helm validates that a source
is named, but the external Secret contents must be validated by the operator or
release lane.

## Breaking Changes

No breaking value migrations are introduced for chart `0.1.0`.

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
helm template honua-dev ./honua -f honua/values-dev.yaml
helm template honua-stage ./honua -f honua/values-stage.yaml
helm template honua-prod ./honua -f honua/values-prod.yaml
helm template honua-stage ./honua -f honua/values-stage.yaml --is-upgrade
```

These commands prove the chart contract renders and the staged install/upgrade
render paths are syntactically valid. The baseline `honua/values.yaml` is a
documented contract with empty required secret placeholders; use
`honua/ci-values/base.yaml` or an environment overlay for render smoke.

## Install/Upgrade Smoke

Ticket #2's Helm release-lane install/upgrade smoke requires a Kubernetes
cluster. For a disposable local smoke, use k3d:

```bash
cluster="honua-helm-smoke"
namespace="honua-smoke"

k3d cluster create "$cluster" --agents 0 --wait --timeout 180s
kubectl create namespace "$namespace"
kubectl -n "$namespace" create secret generic honua-stage-runtime \
  --from-literal=ConnectionStrings__DefaultConnection='Host=postgis.internal;Database=honua;Username=honua;Password=smoke' \
  --from-literal=HONUA_ADMIN_PASSWORD='smoke-admin-password' \
  --from-literal=ConnectionStrings__redis='redis.internal:6379'

helm upgrade --install honua-stage ./honua -n "$namespace" -f honua/values-stage.yaml --wait=false --timeout 2m
helm upgrade --install honua-stage ./honua -n "$namespace" -f honua/values-stage.yaml --set podLabels.smokeRun=upgrade --wait=false --timeout 2m
helm status honua-stage -n "$namespace"
kubectl get deployment,service,ingress,hpa -n "$namespace"

helm uninstall honua-stage -n "$namespace"
k3d cluster delete "$cluster"
```

The smoke proves Helm can install and upgrade the staged values contract into a
real API server. Runtime readiness, Terraform provisioning, marketplace package
validation, and sales-offer alignment are release-lane items owned by their
respective repositories and tracked in `docs/values-contract.md`.
