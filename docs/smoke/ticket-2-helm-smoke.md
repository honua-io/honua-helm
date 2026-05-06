# Ticket 2 Helm Smoke Evidence

Date: 2026-05-06

Scope: values contract, dev/stage/prod overlays, and stage install/upgrade smoke
for `honua-io/honua-helm#2`.

## Tooling

- Helm: `v3.16.4`
- k3d: local disposable cluster using `rancher/k3s:v1.31.5-k3s1`
- Chart path: `./honua`
- Smoke overlay: `honua/values-stage.yaml`

## Targeted Checks

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency build honua
jq empty honua/values.schema.json
helm lint honua
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

Result: schema parse passed; all five lint runs reported `0 chart(s) failed`;
the CI base fixture, dev, stage, prod, and stage upgrade renders completed
without errors.

## Install/Upgrade Smoke

The stage overlay was installed and upgraded in a disposable k3d cluster with a
pre-created `honua-stage-runtime` Secret.

```text
Release "honua-stage" does not exist. Installing it now.
STATUS: deployed
REVISION: 1

Release "honua-stage" has been upgraded. Happy Helming!
STATUS: deployed
REVISION: 2

deployment.apps/honua-stage-honua
service/honua-stage-honua
ingress.networking.k8s.io/honua-stage-honua
horizontalpodautoscaler.autoscaling/honua-stage-honua
```

The smoke uses `--wait=false`, so it proves Helm install/upgrade and Kubernetes
API acceptance of the chart resources. It does not claim application readiness,
database reachability, image pull success, Terraform provisioning, marketplace
package validation, or sales-offer alignment.
