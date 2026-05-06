# Releasing the Honua Helm Chart

This page is the operator runbook for cutting a chart release. The release pipeline lives in
[`.github/workflows/release.yml`](.github/workflows/release.yml) and publishes to
`oci://ghcr.io/honua-io/charts`.

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

The recommended path is `workflow_dispatch` because it forces an explicit
`app_version` input and produces an OCI publish without a GitHub Release. Use
the tag path once you are ready to make the cut public.

### 1. Prepare on `trunk`

1. Bump `version` in `honua/Chart.yaml` to the new chart semver.
2. Bump `appVersion` in `honua/Chart.yaml` to the honua-server release tag the
   chart is validated against (no `v` prefix, e.g. `1.2.3`).
3. Open a PR. CI lints and renders the chart against
   `honua/ci-values/*.yaml`.
4. Merge to `trunk`.

### 2. Dry run via `workflow_dispatch` (optional but recommended)

`Actions → Helm Release → Run workflow` with:

- `chart_version`: e.g. `0.2.0`
- `app_version`: e.g. `1.2.3`

The workflow stamps `Chart.yaml` and `values.yaml`, lints and renders the
chart, packages it, and pushes to `oci://ghcr.io/honua-io/charts`. No GitHub
Release is created on `workflow_dispatch`.

### 3. Tag the cut

```bash
git tag chart-vX.Y.Z
git push origin chart-vX.Y.Z
```

The tag-triggered run derives `chart_version` from the tag and reads
`app_version` from `Chart.yaml`. Both are stamped into the package. The
workflow also creates a GitHub Release named `chart-vX.Y.Z` with the
`.tgz` attached and auto-generated notes.

### Rejection rules

The workflow fails fast (`set -euo pipefail`) when:

- Tag does not match `chart-vX.Y.Z[-suffix]`.
- `chart_version` is not bare SemVer (`X.Y.Z`, optional pre-release/build
  metadata; no `v` prefix).
- `app_version` is empty, `null`, or the placeholder `0.0.0` — operators must
  pin to a real honua-server release before tagging, or supply the value via
  dispatch.
- `app_version` starts with `v` (e.g. `v1.2.3`) or ends with `-aot` (e.g.
  `1.2.3-aot`). Supply the bare server SemVer; the workflow stamps the image
  tag as `v${app_version}-aot`.
- `app_version` is not bare SemVer (`X.Y.Z`, optional pre-release/build
  metadata).
- `helm package` does not produce the expected
  `dist/honua-${chart_version}.tgz`.

## Coupling to honua-server

Every chart release is intended to be validated against a concrete
`honua-server` image digest. Until [honua-helm-2](https://github.com/honua-io/honua-helm/issues/2)
lands install/upgrade smoke against a real cluster, the smoke evidence
captured in the GitHub Release notes is manual. After honua-helm-2 lands, the
release notes will record the digest exercised in smoke.

## OCI vs. classic chart repository

MVP publishes to OCI only. `helm install oci://ghcr.io/honua-io/charts/honua`
works on Helm 3.8 and later. A classic GitHub Pages chart repository will be
considered as a follow-up if marketplace or sales workstreams surface a
customer requirement for `helm repo add`.

## Verification after a cut

```bash
helm registry login ghcr.io
helm pull oci://ghcr.io/honua-io/charts/honua --version X.Y.Z
helm show chart oci://ghcr.io/honua-io/charts/honua --version X.Y.Z
```

Confirm the rendered `Chart.yaml` shows the expected `version` and `appVersion`,
and that `values.yaml` shows the stamped `image.tag`.
