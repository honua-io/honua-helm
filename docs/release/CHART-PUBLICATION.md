---
type: reference
title: "Nightly chart publication by digest"
description: "How the nightly job publishes the chart to GHCR by digest with keyless signing, and the receipt fields the platform release resolver reads."
resource: "https://github.com/honua-io/honua-helm/blob/trunk/.github/workflows/chart-nightly.yml"
tags: [release, oci, signing, provenance, contract]
---
# Nightly chart publication by digest

`.github/workflows/chart-nightly.yml` publishes the chart for a platform candidate. It follows
ruling R31 of the 2026.1 release plan:

- The chart is pushed to `oci://ghcr.io/honua-io/charts/honua` and identified by its digest.
- `appVersion` is bound to the honua-server image digest.
- The chart is signed keyless with cosign, using the job's GitHub OIDC identity. No signing key
  exists.

The platform release resolver reads the receipt this job writes. It does not read
`honua/Chart.yaml`.

The tag-triggered `release.yml` cut described in [RELEASING.md](../../RELEASING.md) is a separate
path, and this job does not change it.

## What one run does

1. **Resolve and authorize.** The job decides what it may publish before it pushes anything.
   The mode comes from the inputs, never from the event name. In a reusable workflow
   `github.event_name`, `github.ref` and `github.sha` belong to the caller:
   - A non-empty `server_image_digest` publishes exactly that request. `platform_version` is then
     required, and `chart_revision` is optional.
   - No inputs is this workflow's own scheduled nightly, which publishes the newest stamped
     candidate. A caller that passes no inputs is refused. So is half a request, such as a
     `platform_version` or `chart_revision` without a digest.
   - The revision checked out is `chart_revision`, or honua-helm's default-branch head read from the
     GitHub API. When the trunk workflow runs, the revision must be on `trunk`. The workflow's own
     steps check this before any checked-out file runs, for proof runs too.

   The request must also pass these checks:
   - `platform_version` must have the R22 form `YYYY.N.P[-rc.N]`, for example `2026.1.0-rc.3`.
   - `server_image_digest` must be `sha256:<64 hex>`.
   - For the release repository, the source revision must be on honua-helm `trunk`.
   - The OIDC `job_workflow_ref` must be exactly
     `honua-io/honua-helm/.github/workflows/chart-nightly.yml@refs/heads/trunk`. This is the
     identity that Fulcio certifies.

   A branch dispatch, or a caller that pins this reusable workflow to anything but `@trunk`, is
   refused here. It is not left for a failing verification to discover after the push.
2. **Read the platform set.** The job fetches the server image index at the digest. Its `linux`
   platforms, which must be `amd64` and/or `arm64`, become the chart's `architectures`. A chart
   artifact has no platform of its own. It runs wherever the image it binds runs.
3. **Stamp and package.** The job writes these values into its own checkout, never into `trunk`:
   - In `Chart.yaml`: `version` and `appVersion` become the platform version. Three annotations
     are added: `honua.io/server-image`, `honua.io/server-image-digest` and
     `honua.io/source-revision`.
   - In `values.yaml`: `image.digest` becomes the server digest, `image.tag` becomes `""` and
     `image.pullPolicy` becomes `IfNotPresent`.

   The job then lints the chart, renders it, requires the rendered image to be the digest
   reference, and packages it.
4. **Push once.** The only tag written is the immutable chart version. The job first proves the
   version is absent (HTTP 404) and then pushes. If the version already exists, the job re-verifies
   it and records it, but only when its pulled bytes carry the same version, appVersion, server
   digest and source revision. Otherwise it refuses. No floating tag is moved; channel tags belong
   to promotion. cosign stores signatures and attestations under `sha256-<digest>` tags, which are
   addressed by digest.
5. **Verify by digest.** The job:
   - reads the version tag's digest from the registry, not from `helm push` output;
   - fetches the manifest by digest and checks that it hashes to that digest;
   - fetches the chart layer and checks that it hashes to its layer digest;
   - requires the layer bytes to equal the packaged bytes.

   The binding is then checked again on the pulled package.
6. **Sign and attest.** The job runs these steps against `repository@digest`:
   - `cosign sign`, keyless;
   - `cosign attest --type cyclonedx`, which attaches an SBOM of the chart, its vendored subcharts
     and every image it renders;
   - `actions/attest-build-provenance`, which attaches SLSA v1 provenance and pushes it to the
     registry.

   Then `cosign verify`, `cosign verify-attestation` and `gh attestation verify` must all pass.
7. **Record.** The job writes the receipt, uploads the artifact and sets the job outputs.

## Triggers

| Trigger | Inputs | Publishes |
| --- | --- | --- |
| `schedule`, 13:45 UTC daily | none | The newest stamped release-train candidate: the `refs/nightly-candidates/*` snapshot in honua-release with the newest commit date. The chart version is that snapshot's `platformRelease` label (`2026.1-rc.N` → `2026.1.0-rc.N`). The server digest is its `components.honua-server` image digest. The source revision is its `components.honua-helm.sha`. If no candidate is stamped, the run fails and publishes nothing. It never invents a version. |
| `workflow_call` | `server_image_digest`, `platform_version`, optional `chart_revision` (default: honua-helm default-branch head, read from the API) | Exactly that request, to the release repository, whatever event started the caller. Call it as `uses: honua-io/honua-helm/.github/workflows/chart-nightly.yml@trunk`. The caller job needs `contents: read`, `packages: write`, `id-token: write` and `attestations: write`. Its token must have write access to the `charts/honua` package. |
| `workflow_dispatch` | as `workflow_call`, plus `proof` | With `proof: false`, from `trunk` only: the release repository. With `proof: true`, from any branch: the throwaway `ghcr.io/honua-io/charts/honua-ci-proof/honua`, which the `delete-proof` job deletes once the run finishes. A branch proof must pass its own head as `chart_revision`, because the default is the default-branch head. |

## What the release resolver reads

The run uploads one artifact:

- named `chart-publication-<version>`, or `chart-publication-proof-<version>` for a proof run;
- in the caller's run for `workflow_call`;
- in this repository's run for `schedule` and `workflow_dispatch`.

It holds `chart-publication.json` (`format: honua.chart-publication/v1`) and these supporting
files:

- the pulled package;
- `sbom.cdx.json`;
- the `cosign verify`, `cosign verify-attestation` and `gh attestation verify` outputs;
- the resolved `request.json` and `server.json`.

`platformManifest` holds the fields the platform lock generator reads for
`components.honua-helm`. The names match the generator's, so the resolver copies them unchanged:

| Receipt field | Lock field (`components.honua-helm.artifacts[0]`) | Meaning |
| --- | --- | --- |
| `platformManifest.artifactVersion` | `version` | Chart version, which is the R22 platform version. |
| `platformManifest.digest` | `digest` | OCI manifest digest of the chart. |
| `platformManifest.architectures` | `architectures` | Platform set of the bound server image (`amd64`, `arm64`). |
| `platformManifest.artifactSha256` | `sha256` | sha256 of the chart package pulled back by digest. |
| `platformManifest.artifactSourceRevision` | `sourceRevision` | honua-helm commit the package was built from. |
| `platformManifest.sha` | `components.honua-helm.sha` | The same commit. A lock binds the chart only when this equals its pinned honua-helm revision. |

The rest of the receipt is for verification and audit:

- `chart.reference` is the full digest reference to pull and verify.
- `serverImage.digest` and `serverImage.platformDigests` record the server image the chart binds.
  The resolver must check that `serverImage.digest` equals the lock's honua-server digest.
- `signature.identity` and `signature.issuer` are the exact keyless identity to verify against.
- `publication` is `pushed` or `existing`.
- `candidateRef` is the honua-release snapshot that a scheduled run published.
- `run` holds the producing run.

The same values are job outputs, so a calling workflow does not have to download the artifact:

- `chart_reference`
- `chart_digest`
- `chart_sha256`
- `chart_version`
- `source_revision`
- `architectures` (a JSON array)
- `receipt_artifact`

## Verifying a published chart

### At pull time

Before you install or mirror a chart, resolve its version to a digest and verify the signature on
that digest. The identity is exact. Do not use `--certificate-identity-regexp`, because a regular
expression would also accept a branch run of the same workflow:

```bash
digest=$(oras resolve ghcr.io/honua-io/charts/honua:<version>)   # or the receipt's chart.digest
cosign verify "ghcr.io/honua-io/charts/honua@${digest}" \
  --certificate-identity https://github.com/honua-io/honua-helm/.github/workflows/chart-nightly.yml@refs/heads/trunk \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
helm pull oci://ghcr.io/honua-io/charts/honua --version <version>
sha256sum honua-<version>.tgz   # must equal the receipt's platformManifest.artifactSha256
```

The signing identity is always the trunk workflow, including when the release train calls it as
a reusable workflow. The certificate names the called workflow, not the caller's workflow.

### Full verification

Every check below runs against the digest, never the version tag:

```bash
ref=ghcr.io/honua-io/charts/honua@sha256:<digest>
cosign verify "$ref" \
  --certificate-identity https://github.com/honua-io/honua-helm/.github/workflows/chart-nightly.yml@refs/heads/trunk \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
cosign verify-attestation "$ref" --type cyclonedx \
  --certificate-identity https://github.com/honua-io/honua-helm/.github/workflows/chart-nightly.yml@refs/heads/trunk \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
gh attestation verify "oci://$ref" --owner honua-io \
  --signer-workflow honua-io/honua-helm/.github/workflows/chart-nightly.yml
helm pull oci://ghcr.io/honua-io/charts/honua --version <version>   # then compare sha256 with the receipt
```

## Operator prerequisites

The job cannot meet these itself:

- **Public package.** The first push creates `charts/honua` with the organisation's default
  visibility. An administrator must make the package public before anonymous pulls succeed. The
  job's own checks authenticate with its token, so they do not depend on this.
- **Cross-repository caller.** A `workflow_call` from another repository, such as the release
  train, runs with that repository's `GITHUB_TOKEN`. The `charts/honua` package must grant that
  repository write access under *Manage Actions access*. Without it, the push is refused.
