# Releasing the Honua Helm Chart

This page is the operator runbook for cutting a chart release. The release pipeline lives in
[`.github/workflows/release.yml`](.github/workflows/release.yml) and publishes public tag-triggered
cuts to `oci://ghcr.io/honua-io/charts`.

## Versioning model

The chart carries two versions in `honua/Chart.yaml`. They move on independent cadences:

| Field | Meaning | Cadence |
|-------|---------|---------|
| `version` | Chart semver. Bump for any chart change (templates, default values, schema). | Independent — bump per chart change. Breaking value-contract changes bump major. |
| `appVersion` | The honua-server release the chart is validated against. Equals the upstream server semver (no `v` prefix, no `-aot` suffix), e.g. `1.2.3`. | Tracks honua-server release tags. |

Tag schemes are deliberately decoupled:

- Chart releases use `chart-vX.Y.Z` in this repo.
- Server releases use `vX.Y.Z` in `honua-server`.

### Image tag stamping

The chart's checked-in `values.yaml` ships `image.tag: "latest-aot"` for local
development ergonomics. The release workflow stamps `image.tag` to
`v${app_version}-aot` at package time, so an operator who installs the published
OCI chart without overrides gets an immutable, version-pinned image. AOT is the
chart's default posture; operators that need JIT can override `image.tag` at
install time.

## Cut procedure

The canonical public release path is the tag-triggered run, which publishes to
OCI, verifies the exact chart bytes through an anonymous pull, and then creates
the matching GitHub Release. `workflow_dispatch` is dry-run only: it validates
inputs, verifies the honua-server
image, builds dependencies from `Chart.lock`, stamps the chart, lints,
renders, and packages the chart — but cannot publish or attest it. There is no
manual republish path: an existing OCI version fails the release preflight so
the chart-version → digest contract cannot be overwritten.

### 1. Prepare on `trunk`

1. Bump `version` in `honua/Chart.yaml` to the new chart semver.
2. Bump `appVersion` in `honua/Chart.yaml` to the honua-server release tag the
   chart is validated against (no `v` prefix, e.g. `1.2.3`).
3. Open a PR. CI lints and renders the chart against
   `honua/ci-values/*.yaml`.
4. Merge to `trunk`.

### 2. Dry run via `workflow_dispatch` (recommended)

`Actions → Helm Release → Run workflow` with:

- `chart_version`: e.g. `0.2.0`
- `app_version`: e.g. `1.2.3`

The workflow resolves the inputs, verifies that
`ghcr.io/honua-io/honua-server:v${app_version}-aot` exists and resolves to a
single `sha256` digest, builds dependencies, stamps `Chart.yaml` and
`values.yaml`, lints, renders, and packages the `.tgz`. The run then stops and
emits a "dry run (no publish)" step summary — no
chart is pushed to OCI and no GitHub Release is created. Use this to
validate inputs without consuming a chart version.

### 3. Tag the cut

```bash
git tag -s chart-vX.Y.Z -m "Honua chart X.Y.Z"
git push origin chart-vX.Y.Z
```

The tag must be annotated, signed, and reported as verified by GitHub. The
tag-triggered run derives `chart_version` from the tag and reads
`app_version` from `Chart.yaml`. Both are stamped into the package, the
workflow proves the version is absent, and the chart is pushed once to
`oci://ghcr.io/honua-io/charts`. A fresh job with no registry login pulls the
same version and requires its SHA-256 to match the packaged bytes. Only then is
a GitHub Release named `chart-vX.Y.Z` created with the `.tgz`, checksum, and
release notes attached.

For the first chart package, GHCR may create `charts/honua` as private even
though this source repository is public. If the anonymous-pull job fails for
that reason, an organization package administrator must change
`charts/honua` visibility to **Public**, then use **Re-run failed jobs**. Do not
rerun the successful publish job or push the tag again. Publication itself
uses the job-scoped `GITHUB_TOKEN` with `packages: write`; no long-lived
registry credential is required.

If GHCR accepted the chart but the publish job itself failed before recording
the digest, do not rerun that job against the same version. Confirm the package
exists, advance the chart version, and cut a new signed tag; the preflight will
not treat a pre-existing version as an artifact built by a later run.

### Rejection rules

The workflow fails fast (`set -euo pipefail`) when:

- Tag does not match `chart-vX.Y.Z[-suffix]`.
- Tag is lightweight, unsigned, or its signature is not verified by GitHub.
- `chart_version` is not bare SemVer (`X.Y.Z`, optional pre-release; no `v`
  prefix and no `+` build metadata).
- `app_version` is empty, `null`, or the placeholder `0.0.0` — operators must
  pin to a real honua-server release before tagging, or supply the value via
  dispatch.
- `app_version` starts with `v` (e.g. `v1.2.3`) or ends with `-aot` (e.g.
  `1.2.3-aot`). Supply the bare server SemVer; the workflow stamps the image
  tag as `v${app_version}-aot`.
- `app_version` is not bare SemVer (`X.Y.Z`, optional pre-release; no `+`
  build metadata). Build metadata is rejected because the workflow stamps the
  image tag as `v${app_version}-aot`, and Docker/OCI references do not allow
  `+`.
- The honua-server image at `ghcr.io/honua-io/honua-server:v${app_version}-aot`
  does not exist or is not readable. The workflow runs
  `docker buildx imagetools inspect` against the stamped reference and
  captures one resolved `sha256` digest before packaging, so a chart cannot be
  published pinned to a non-existent server image or ambiguous manifest output.
- `helm package` does not produce the expected
  `dist/honua-${chart_version}.tgz`.
- `helm push` succeeds without returning a single `sha256` OCI digest for the
  published chart.
- The chart version already exists in GHCR.
- The published `.tgz` cannot be pulled anonymously or differs byte-for-byte
  from the packaged and attested artifact.

## Coupling to honua-server

Every chart release is validated against a concrete `honua-server` image
digest before publishing. The release workflow runs
`docker buildx imagetools inspect ghcr.io/honua-io/honua-server:v${app_version}-aot`
after resolving versions and fails fast if the manifest is missing or
unreadable, or if Docker does not return a single `sha256` digest. The resolved
digest is recorded in the workflow step summary and in the GitHub Release notes
(under "Server image digest"), so each published chart traces back to the exact
server image bytes it was packaged against.

Cluster-validated install/upgrade smoke ([honua-helm-2](https://github.com/honua-io/honua-helm/issues/2))
is the next layer on top of this existence check. Until honua-helm-2 lands,
end-to-end smoke evidence (e.g., a real `helm upgrade --install` against a
test cluster) remains a manual step the operator attaches alongside the
auto-generated digest line.

## Subchart pinning

Release packaging runs `helm dependency build honua`, which consumes the
committed `honua/Chart.lock` rather than re-resolving the version ranges in
`honua/Chart.yaml`. The published `.tgz` therefore embeds exactly the Bitnami
`postgresql` and `redis` subchart versions recorded in the lock. Bumping a
subchart is a deliberate PR that runs `helm dependency update` and updates
`Chart.lock`; CI then validates the new lock via `helm dependency build` on
the next render.

## OCI vs. classic chart repository

MVP publishes to OCI only. Helm 3.8 and later can install the OCI reference
directly with the complete `helm upgrade --install honua
oci://ghcr.io/honua-io/charts/honua --version X.Y.Z ...` form documented in
[`honua/README.md`](honua/README.md). A classic GitHub Pages chart repository
will be considered as a follow-up if marketplace or sales workstreams surface a
customer requirement for `helm repo add`.

## Verification after a cut

```bash
tmp_dir="$(mktemp -d)"
export HELM_REGISTRY_CONFIG="${tmp_dir}/registry.json"
helm pull oci://ghcr.io/honua-io/charts/honua --version X.Y.Z
helm show chart oci://ghcr.io/honua-io/charts/honua --version X.Y.Z
```

Confirm the rendered `Chart.yaml` shows the expected `version` and `appVersion`,
and that `values.yaml` shows the stamped `image.tag`. Do not log in for this
check: anonymous success is the public-install evidence.
