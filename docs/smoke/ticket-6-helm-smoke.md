# Ticket 6 Helm Smoke Evidence

Date: 2026-05-30

Scope: operator-ready chart contract for `honua-io/honua-helm#6` — install,
upgrade, `helm test` readiness, rollback, and release-info evidence surfaces
at chart `0.2.0`.

## Tooling

- Chart path: `./honua`
- Chart version: `0.2.0` (`honua/Chart.yaml`)
- App version: `0.0.0` placeholder (stamped at release time by
  `.github/workflows/release.yml`).
- Helm: `azure/setup-helm@bf6a7d3` (latest stable Helm v3 at job time).
- Cluster: `helm/kind-action@0025e74` (kind cluster `honua-smoke`).
- PostGIS dependency: `postgis/postgis:16-3.4-alpine` Deployment+Service in
  namespace `honua-smoke` (the Bitnami PostgreSQL subchart is dev-only and
  ships without PostGIS).
- Redis dependency: `redis:7-alpine` Deployment+Service in namespace
  `honua-smoke` with `requirepass=ci-redis-password`.
- ci-values exercised: `honua/ci-values/upgrade-base.yaml` (install,
  revision 1) and `honua/ci-values/upgrade-target.yaml` (upgrade,
  revision 2).

## Sequence

The `install-upgrade-rollback-smoke` job in `.github/workflows/ci.yml`
executes these steps in a fresh kind cluster after PostGIS and Redis are
rolled out:

```bash
helm install honua ./honua -n honua-smoke -f honua/ci-values/upgrade-base.yaml --wait --timeout 10m
helm test honua -n honua-smoke --logs --timeout 5m | tee /tmp/honua-smoke/test-install.log

helm upgrade honua ./honua -n honua-smoke -f honua/ci-values/upgrade-target.yaml --wait --timeout 10m
helm test honua -n honua-smoke --logs --timeout 5m | tee /tmp/honua-smoke/test-upgrade.log

helm rollback honua 1 -n honua-smoke --wait --timeout 10m
helm test honua -n honua-smoke --logs --timeout 5m | tee /tmp/honua-smoke/test-rollback.log
```

`upgrade-base.yaml` installs `release.id=honua-ci-upgrade-base` with the
default `strategy.type=Recreate`. `upgrade-target.yaml` upgrades to
`release.id=honua-ci-upgrade-target`, `replicaCount: 2`, and an explicit
`strategy.type=RollingUpdate` with `maxSurge: 0`, `maxUnavailable: 1` so the
RollingUpdate path is exercised on a forward-compatible image. The rollback
returns the release to revision 1 (`Recreate` strategy, single replica,
`honua-ci-upgrade-base`).

## Artifacts

The CI job uploads `honua-smoke-evidence` (`actions/upload-artifact`) on
every run, including failure runs. The artifact contains:

| File | Source command | What it proves |
| --- | --- | --- |
| `test-install.log` | `helm test honua --logs` after install | Readiness curl against `/healthz/ready` succeeded on revision 1 and the test pod printed `release.id`, `release.manifest`, `release.digest`, `image.reference`, `chart.version`, `app.version`, and the readiness contract statement. |
| `test-upgrade.log` | `helm test honua --logs` after upgrade | Same surface on revision 2 with the upgrade-target release evidence. |
| `test-rollback.log` | `helm test honua --logs` after rollback | Same surface after `helm rollback honua 1`, demonstrating the prior revision's release evidence is restored. |
| `helm-history.txt` | `helm history honua` | Revision ledger across install → upgrade → rollback (three revisions, status `deployed` on the active one). |
| `helm-notes.txt` | `helm get notes honua` | Helm NOTES output for the active revision including the release evidence block, evidence/rollback commands, and any RollingUpdate or mutable-tag warnings. |
| `release-info.yaml` | `kubectl get configmap honua-honua-release-info -o yaml` | Rendered release-info ConfigMap with `HONUA_RELEASE_*`, `HONUA_IMAGE_*`, `HONUA_CHART_VERSION`, `HONUA_APP_VERSION`, and Helm release identity. |
| `events.txt` | `kubectl get events --sort-by=.lastTimestamp` | Pre-install hook, preflight Job, Deployment, and helm-test Pod events. |
| `pods.txt` | `kubectl get pods -o wide` | Pod state at evidence-capture time, including preflight Job pod and helm-test Pod. |

The `kubectl get events`, `kubectl get pods -o wide`, `helm history`, and
`helm get notes` captures run inside an `if: always()` step so a failed
install, upgrade, or rollback still produces evidence. The CI run URL and
artifact link should be attached to the ticket close-out PR.

## Release evidence surfaces

`helm template honua ./honua -f honua/ci-values/upgrade-base.yaml` renders
the install-time release-info ConfigMap with:

```yaml
data:
  HONUA_RELEASE_ID: "honua-ci-upgrade-base"
  HONUA_RELEASE_MANIFEST: "ci://honua-helm/upgrade-base"
  HONUA_RELEASE_DIGEST: ""
  HONUA_IMAGE_REFERENCE: "ghcr.io/honua-io/honua-server:latest-aot"
  HONUA_IMAGE_DIGEST: ""
  HONUA_CHART_VERSION: "0.2.0"
  HONUA_APP_VERSION: "0.0.0"
  HONUA_HELM_RELEASE: "honua"
  HONUA_HELM_NAMESPACE: "default"
```

`helm template honua ./honua --is-upgrade -f honua/ci-values/upgrade-target.yaml`
renders the upgrade-time release-info ConfigMap with
`HONUA_RELEASE_ID: "honua-ci-upgrade-target"` and
`HONUA_RELEASE_MANIFEST: "ci://honua-helm/upgrade-target"`. Deployment
labels, Pod-template `honua.io/*` annotations, container env, and the
`test-connection` Pod's stdout reflect the same values, so a single
`helm test honua --logs` output is the operator evidence one-liner that
matches the ConfigMap.

## Provenance

- Chart commit: this branch (`feature/6`) at the commit that introduces
  this artifact; chart `version: 0.2.0` and `appVersion: "0.0.0"` per
  `honua/Chart.yaml`.
- Chart.lock dependencies: `postgresql 15.5.38`, `redis 20.13.4`.
- CI workflow: `.github/workflows/ci.yml`,
  `install-upgrade-rollback-smoke` job.
- Smoke artifact: `honua-smoke-evidence` upload from the CI run that
  validates the ticket-6 close-out PR. The CI run URL is attached to the
  ticket close-out comment when the PR merges. This on-disk artifact is
  the durable reference because GitHub Actions artifacts expire on the
  default 90-day retention.

## Scope statement

The kind-backed CI smoke proves:

- The chart installs cleanly from `honua/ci-values/upgrade-base.yaml`
  against PostGIS and Redis services that are real but lightweight.
- The pre-install/pre-upgrade preflight hook completes successfully against
  those endpoints (required-secret keys, PostgreSQL TCP, Redis TCP, and
  registry `/v2/` reachability when enabled).
- The Deployment becomes ready and the `helm test` `test-connection` Pod
  successfully reaches `/healthz/ready`.
- `helm upgrade` to `upgrade-target.yaml` rolls the Deployment to a
  RollingUpdate strategy with `replicaCount: 2`, the new release evidence
  is reflected in the release-info ConfigMap, and `helm test` succeeds on
  the upgraded release.
- `helm rollback honua 1` restores revision 1 and `helm test` succeeds
  against the restored release evidence.

The CI smoke does not prove and does not claim:

- Terraform AWS or Azure marketplace provisioning end-to-end
  (`honua-terraform#1`, `honua-terraform#2`).
- Marketplace listing package, private-offer assets, license/entitlement
  activation, or validation evidence attached to marketplace listings
  (`honua-marketplace#1`, `honua-marketplace#2`, `honua-marketplace#4`,
  `honua-marketplace#5`).
- Sales-offer alignment to validated marketplace packages
  (`honua-sales#33`, `honua-sales#34`).
- The chart-managed Bitnami PostgreSQL subchart against PostGIS-dependent
  migrations. The smoke deliberately uses an external PostGIS Deployment
  because the Bitnami subchart does not include PostGIS; production
  installs must point at a managed PostGIS database.

## Refresh policy

This artifact captures the contract baseline at chart `0.2.0`. Refresh it
on the next minor chart bump or when the install-upgrade-rollback smoke
flow in `.github/workflows/ci.yml` changes materially (different
fixtures, new validations, or different evidence files). Cosmetic CI
changes (Helm version pin bump, comment edits) do not require a refresh.
