# AGENTS.md

## Overview

This repository is the Helm chart for **Honua Server**, a geospatial/GIS
application that runs on Kubernetes. The single chart (`honua/`) deploys the
Honua Server Deployment with optional Bitnami PostgreSQL and Redis subcharts,
plus supporting resources (Service, Ingress, HPA, ConfigMaps, Secrets, a
pre-install/pre-upgrade preflight validation Job, and a Helm test hook).

The chart was extracted from the `honua-server` monorepo and is published to
`oci://ghcr.io/honua-io/charts/honua`. The repo layout is intentionally flat:
chart source in `honua/`, CI in `.github/workflows/`, docs in `docs/`.

Honua Server runs database migrations inline during startup behind a PostgreSQL
advisory lock; the chart defaults the Deployment strategy to `Recreate` so old
pods stop before new pods start during a migrating upgrade.

## Tech Stack

- **Helm** chart, `apiVersion: v2`, `type: application` (see `honua/Chart.yaml`).
- Chart `version` and `appVersion` are defined in `honua/Chart.yaml`, which is the
  single source of truth; `appVersion` is a `"0.0.0"` placeholder stamped at
  release. Do not restate the concrete version here or elsewhere in docs.
- Subchart dependencies (Bitnami, from `https://charts.bitnami.com/bitnami`):
  - `postgresql` `>=12.0.0 <16.0.0` (gated by `postgresql.enabled`, dev only —
    Bitnami PostgreSQL does NOT include PostGIS, which Honua requires).
  - `Chart.lock` pins `postgresql 15.5.38`.
- Optional chart-managed Redis uses the Docker Official `redis` image directly;
  it is not a subchart dependency.
- Values validation via `honua/values.schema.json` (JSON Schema) plus
  `fail`-based template guards in `honua/templates/validations.yaml`.
- CI uses Helm (`azure/setup-helm`), `kind` (`helm/kind-action`), `kubectl`, and
  `yq` (release workflow). Target server image: `ghcr.io/honua-io/honua-server`.

## Setup

Requires `helm` and network access to `charts.bitnami.com`. Add the Bitnami repo
and build subchart dependencies from the committed `Chart.lock` before linting
or templating:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency build honua
```

`helm dependency build` uses the committed `Chart.lock` (matching CI and release
packaging). Use `helm dependency update honua` only when intentionally changing
pinned subchart versions. Built subchart tarballs land in `honua/charts/`, which
is gitignored.

## Commands

Run all commands from the repo root. The chart path is `honua` and CI value
files live under `honua/ci-values/`.

Lint:

```bash
helm lint honua -f honua/ci-values/base.yaml
helm lint honua -f honua/values-dev.yaml
helm lint honua -f honua/values-stage.yaml
helm lint honua -f honua/values-prod.yaml
```

Render / template (smoke):

```bash
helm template honua ./honua -f honua/ci-values/base.yaml
helm template honua-dev ./honua -f honua/values-dev.yaml
helm template honua ./honua --is-upgrade -f honua/ci-values/postgresql.yaml
```

Install / upgrade / test / rollback (against a real cluster):

```bash
helm upgrade --install honua honua -f honua/values-dev.yaml
helm test honua                 # runs the test-connection hook after install
helm history honua
helm rollback honua <revision>
```

Package & publish (normally via CI, not by hand):

```bash
helm package honua --destination dist/
helm push dist/honua-<version>.tgz oci://ghcr.io/honua-io/charts
```

There is no separate unit-test framework. "Tests" are the `helm lint` /
`helm template` guard assertions in `.github/workflows/ci.yml` and the in-cluster
`install-upgrade-rollback-smoke` job, plus the Helm `helm test` hook
(`honua/templates/tests/test-connection.yaml`).

## Architecture

- **Deployment** (`templates/deployment.yaml`) — runs the Honua Server container.
  Probes: liveness `/healthz/live`, readiness `/healthz/ready` (signals startup
  + migrations complete), startup `/healthz/live` with 60 retries.
- **Preflight Job** (`templates/preflight-job.yaml` + `preflight-secret.yaml`) —
  Helm `pre-install,pre-upgrade` hook that validates required secret keys,
  PostgreSQL/Redis TCP reachability, and image registry `/v2/` reachability
  before the Deployment is applied. Gated by `preflight.enabled` (default true).
- **Secrets / Config** — chart-managed runtime Secret (`secret.yaml`, from
  `secret.env`) and ConfigMap (`configmap.yaml`, from `config.env`); or
  existing-secret mode via `secret.create=false` + `secret.name` / `extraEnvFrom`.
- **Release evidence** (`release-info-configmap.yaml`, `_helpers.tpl`) — stamps
  `release.id`/manifest/digest/appVersion into labels, `honua.io/*` annotations,
  a release-info ConfigMap, container env, NOTES, and `helm test` output.
- **Validations** (`templates/validations.yaml`) — `fail`-based guards that
  reject invalid configs (e.g. RollingUpdate with zero rollout budget, digest +
  `pullPolicy: Always`, empty image identity, weak `HONUA_ADMIN_PASSWORD`,
  short `Security__ConnectionEncryption__MasterKey`, missing Redis connection).
- **Other**: `service.yaml`, `ingress.yaml`, `hpa.yaml`, `serviceaccount.yaml`,
  `NOTES.txt`.

## Directory Layout

```
honua/                     Chart source
  Chart.yaml               Chart + subchart deps, version, appVersion
  Chart.lock               Pinned subchart versions (committed; used by CI)
  values.yaml              Baseline contract (NOT installable: required secrets empty)
  values-dev/stage/prod.yaml  Environment overlays
  values.schema.json       JSON Schema type/conditional validation
  templates/               Manifests + _helpers.tpl + validations.yaml
  templates/tests/         helm test hook (test-connection.yaml)
  ci-values/               Value files exercised by CI (base, digest, postgresql, ...)
  README.md                Detailed chart usage + full values reference
docs/                      contract.md, values-contract.md, MIGRATION.md, features/, smoke/
.github/workflows/         ci.yml (lint+render+smoke), release.yml (package+publish)
RELEASING.md               Release runbook (chart cuts, versioning, OCI publish)
```

## Conventions & Gotchas

- **`helm template honua honua` with no values file fails by design** — the
  baseline `values.yaml` leaves required runtime secrets empty. Always pass an
  overlay or ci-values file.
- Required secret env keys: `ConnectionStrings__DefaultConnection`,
  `HONUA_ADMIN_PASSWORD` (>=16 chars, mixed case + digit + special),
  `Security__ConnectionEncryption__MasterKey` (>=32 chars), and
  `ConnectionStrings__redis` for non-development deployments.
- `image.tag` defaults to `latest-aot` (dev-only). Release CI stamps a concrete
  `vX.Y.Z-aot` tag. Pin by digest in production; `image.pullPolicy` must be
  `IfNotPresent` or `Never` when `image.digest` is set.
- `strategy.type` defaults to `Recreate` (safe for inline migrations). Use
  `RollingUpdate` only with forward/backward-compatible migrations; the schema
  rejects `RollingUpdate` when both `maxSurge` and `maxUnavailable` are zero
  (including `"0"` / `"0%"`).
- `release.id` and the effective app version are used as Kubernetes label
  values: <=63 chars, only letters/numbers/`_`/`.`/`-`, start/end alphanumeric,
  no `+` build metadata. Put free-form build info in `release.manifest`.
- Bitnami PostgreSQL has no PostGIS — for anything beyond local dev, point
  `ConnectionStrings__DefaultConnection` at an external PostGIS database.
- Versioning: chart tagged with a signed annotated `chart-vX.Y.Z` here; release workflow validates
  SemVer (no `v` prefix, no `+`), verifies the server image exists, then stamps
  `Chart.yaml` version/appVersion and `values.yaml` `image.tag` before packaging,
  refuses an existing OCI version, and requires an anonymous byte-identical pull
  before creating the GitHub Release. Manual dispatch is dry-run only.
  See `RELEASING.md`.
- When changing pinned subchart versions, update both `Chart.yaml` ranges and
  `Chart.lock` (`helm dependency update`), since CI builds from the lock.
- Do not build/run the project as part of documentation work; CI requires
  network access to Bitnami and ghcr.io.

## Shared dev-environment rules (multi-agent WSL)

This machine runs many agents concurrently (**Codex + Claude**, often via agentflow with multiple tabs/agents). To prevent host lockups and lost work, every agent MUST follow these:

1. **Heavy builds/tests are throttled by a shared lock.** `dotnet` and `npm` are PATH-shimmed, so their build/test/publish/pack and ci/install/test/run-build/run-test subcommands automatically run under a global semaphore (default 1 concurrent, `HONUA_BUILD_SLOTS`). For other heavy tools, call the wrapper explicitly: `with-build-lock pytest ...`, `with-build-lock cargo build`, `with-build-lock make build`. The lock is shared across ALL of this user's processes (every Codex/Claude tab, agentflow children). Do not bypass it for compiles or test suites. Long-running servers (`dotnet run`, `npm run dev`) are intentionally NOT locked — never wrap those.

2. **Commit and push when you finish a task** so your worktree can be reclaimed. An hourly job (`honua-clean`) removes a worktree ONLY when it is clean AND fully pushed (merged, remote-gone, or idle >=2d). Dirty or unpushed worktrees are NEVER touched — but uncommitted/unpushed work blocks reclamation and is at risk if the instance is reset. Build artifacts (bin/obj and untracked node_modules) are reclaimed automatically and safely.

3. **Commit hygiene — no agent attribution.** Author every commit as the repo owner only (git identity: Mike McDougall <mike@honua.io>). Do **NOT** add any agent/tool attribution to commits: no `Co-Authored-By: Claude ...`, no `Co-Authored-By: Codex ...` (or other bot co-authors), and no "Generated with Claude Code" / "Generated with Codex" / "🤖" lines in the message or PR body. Write a plain, descriptive commit message and stop.

   This is enforced in CI: `.github/workflows/commit-policy.yml` runs `scripts/check-no-ai-attribution.sh` over every pull request and fails if any commit message carries AI/agent attribution (Dependabot and GitHub Actions bot co-authors are allowed). To catch it before you push, wire the same check as a local `commit-msg` hook:

   ```bash
   ln -s ../../scripts/check-no-ai-attribution.sh .git/hooks/commit-msg
   # or, if your git does not run the script directly:
   printf '#!/bin/sh\nexec scripts/check-no-ai-attribution.sh --message-file "$1"\n' > .git/hooks/commit-msg
   chmod +x .git/hooks/commit-msg
   ```
