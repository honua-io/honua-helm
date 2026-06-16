# AKS Chart Smoke Runbook (honua-helm#10)

This runbook covers the **AKS-specific** install + upgrade smoke for the Honua
Helm chart, on the Azure Marketplace customer-operated deployment path. It is
the AKS-specific tracker referenced by
`honua-sales/docs/user/AZURE_MARKETPLACE_DEPLOYMENT_PATH.md`.

The generic cross-provider install/upgrade/rollback smoke runs in CI on `kind`
(`.github/workflows/ci.yml`, job `install-upgrade-rollback-smoke`). This runbook
is the AKS overlay of that contract: the same chart, validated against a real
AKS cluster so the marketplace listing does not publish on ambiguous Kubernetes
evidence.

## What is automated here

- `honua/ci-values/aks-smoke-install.yaml` — install baseline for the
  customer-operated AKS path (external PostGIS + Redis, pre-created runtime
  Secret, migration-safe `Recreate` strategy, preflight + registry check on).
- `honua/ci-values/aks-smoke-upgrade.yaml` — upgrade target overlay applied as
  the `helm upgrade` step (scales replicas, rotates release evidence metadata).
- `scripts/aks-smoke.sh` — the parameterized harness that runs install →
  `helm test` → upgrade → `helm test` → rollback → `helm test`, then captures
  the evidence the issue's acceptance criteria require. It supports a `--dry-run`
  mode (render + lint + kubeconform, no cluster) that runs in CI so the AKS
  overlays cannot rot.
- `.github/workflows/aks-smoke.yml` — operator-triggered workflow with two
  `workflow_dispatch` modes: `dry-run` (no cluster, no secrets) and `live` (real
  AKS, gated behind the `aks-smoke` GitHub Environment). The live path logs in to
  Azure via OIDC (`azure/login`, no client secret), pulls AKS credentials, and
  runs the harness against the cluster.
- `ci.yml` (job `lint-chart`) invokes `scripts/aks-smoke.sh --dry-run` on every
  push/PR, so the harness itself — not just the overlays — is exercised
  continuously and cannot rot.

The harness does **not** provision AKS and does **not** fabricate results. Every
recorded value comes from a command it actually ran against the kubeconfig you
supply.

## Running it from GitHub Actions

Dry-run (anyone, no secrets) — Actions → "AKS Chart Smoke" → Run workflow →
`mode = dry-run`. This renders, lints, and kubeconform-validates the AKS
overlays and uploads the evidence; it never contacts a cluster.

Live (operator) — first configure the `aks-smoke` GitHub Environment:

- Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (an
  OIDC app federated to this repo, see below), plus `HONUA_DB_CONNECTION`,
  `HONUA_REDIS_CONNECTION`, `HONUA_ADMIN_PASSWORD`, `HONUA_MASTER_KEY`.
- Variables: `AKS_RESOURCE_GROUP`, `AKS_CLUSTER_NAME`.

The OIDC app needs a federated credential whose subject is
`repo:honua-io/honua-helm:environment:aks-smoke` and AKS cluster-user access
(e.g. the "Azure Kubernetes Service Cluster User Role" + a namespace-scoped
RBAC role). Then dispatch with `mode = live` and an `image_digest` for
listing-submission evidence.

## Prerequisites (operator)

1. An AKS validation cluster matching the customer-operated path. Reuse the
   `honua-terraform#2` validation cluster when it provisions AKS; otherwise
   record the temporary AKS setup in the evidence directory.
2. `az aks get-credentials ...` so `kubectl config current-context` points at
   the AKS cluster.
3. An external PostGIS database and Redis reachable from the cluster (Bitnami
   PostgreSQL has no PostGIS; the overlays disable both subcharts).
4. The runtime Secret in the target namespace, either pre-created or created by
   the harness with `--create-runtime-secret` and the `HONUA_*` env inputs.

## Run

Dry-run first (no cluster), to validate overlays and the harness:

```bash
scripts/aks-smoke.sh --dry-run --image-tag <vX.Y.Z-aot>
```

Live AKS install + upgrade + rollback smoke:

```bash
export HONUA_DB_CONNECTION='Host=pg.example.com;Port=5432;Database=honua;Username=honua;Password=...'
export HONUA_REDIS_CONNECTION='redis.example.com:6379,password=...'
export HONUA_ADMIN_PASSWORD='...'        # >=16 chars, mixed case + digit + special
export HONUA_MASTER_KEY='...'            # >=32 chars

scripts/aks-smoke.sh \
  --release honua \
  --namespace honua \
  --image-digest sha256:<64hex> \
  --release-id <listing-release-id> \
  --release-manifest <release-manifest-url> \
  --release-digest sha256:<64hex> \
  --create-runtime-secret \
  --evidence-dir evidence/aks-<date>
```

Pin by digest for listing-submission evidence. Use `--image-tag` only for
pre-submission validation. Secret material is passed via env vars and is never
written to the evidence directory or the command log.

## Acceptance-criteria mapping

| Issue AC | Where it is satisfied |
| --- | --- |
| Clean AKS install smoke passes for the listing chart version | `helm install` step + post-install `helm test`; `helm-history.txt`, `healthcheck-install.log` |
| Chart upgrade smoke passes against the same AKS path | `helm upgrade` step + post-upgrade `helm test`; `healthcheck-upgrade.log` |
| Evidence records chart version | `summary.md`, `release-info.yaml` (`HONUA_CHART_VERSION`) |
| Evidence records image digests | `image-ids.txt` (kubelet-resolved `imageID`), `release-info.yaml`, `summary.md` |
| Evidence records values file / overlay | `summary.md` (overlay paths), `helm-values.txt` |
| Evidence records cluster / runtime target | `summary.md` (kube-context), `nodes.txt`, `aks-node-labels.txt` |
| Evidence records commands | `commands.log` (timestamped transcript) |
| Evidence records health-check output | `healthcheck-{install,upgrade,rollback}.log`, `pod-readiness.txt` |
| Failures owned by another repo are filed/linked there | Operator files in the owning repo; link back here |

## Evidence directory layout

```
evidence/aks-<date>/
  summary.md                    header + AC-mapped result
  commands.log                  timestamped command transcript
  nodes.txt, aks-node-labels.txt  cluster/runtime target
  helm-history.txt              install/upgrade/rollback revisions
  helm-notes.txt, helm-values.txt
  release-info.yaml             chart/app version, image + release digests
  workloads.txt, pod-readiness.txt, image-ids.txt
  healthcheck-install.log
  healthcheck-upgrade.log
  healthcheck-rollback.log
  events.txt
```

The default `evidence/` directory is gitignored. To retain a run as release
evidence, copy the directory under a committed path or attach it to the issue.

## Scope boundaries

This smoke proves Helm install/upgrade/rollback acceptance, chart-rendered
Kubernetes API acceptance, preflight validation, and `/healthz/ready` readiness
(which signals Honua startup and migrations completed) on AKS. It does not
validate Terraform provisioning, marketplace package publication, sales-offer
alignment, or any application behavior beyond the readiness contract. Failures
in those areas are filed and linked in their owning repositories.
