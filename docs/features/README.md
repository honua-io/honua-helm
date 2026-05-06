# Honua Helm Feature Map

This repository packages Honua Server for Kubernetes.

## Current Chart Capabilities

- Kubernetes Deployment, Service, ingress, config, secret, and probe wiring for Honua Server.
- Optional Bitnami PostgreSQL and Redis subcharts for development or simple environments.
- External PostGIS and Redis support through secret/config environment values.
- AOT and JIT image tag selection, with AOT as the default chart posture.
- Digest-pinned image rendering for immutable production releases.
- Explicit Deployment strategy defaults for inline migration safety.
- Pre-install/pre-upgrade preflight hook for required credentials, database reachability, Redis reachability, and registry reachability.
- Release-info ConfigMap, labels, Pod-template annotations, NOTES, and helm-test output for evidence capture.
- CI install/upgrade/rollback smoke workflow with captured release-info and helm-test evidence.
- HorizontalPodAutoscaler support with CPU/memory targets and scale-up/scale-down behavior.
- Production-oriented resource, ingress, TLS, public base URL, observability, and OpenTelemetry values.
- Existing-secret and `extraEnvFrom` modes for customer-managed credentials.
- Documented values contract with Helm schema validation for dependency auth and HPA targets, plus template guards for required runtime secrets.
- Dev, stage, and prod overlay values for release-lane and customer-operated installs.
- Liveness, readiness, and startup probes on the server health endpoints.
- Packaged release pipeline that publishes the chart to `oci://ghcr.io/honua-io/charts` on a `chart-vX.Y.Z` tag, stamps `Chart.yaml` `version`/`appVersion` and `values.yaml` `image.tag` at package time, and attaches the `.tgz` to a GitHub Release on tag-triggered runs. `workflow_dispatch` defaults to a real dry run (validate + package, no publish); operators opt into a publish-without-Release path via the `publish: true` input.

## Source Evidence

- Chart source: `honua/`
- Usage and production examples: `honua/README.md`
- Operator chart contract: `docs/contract.md`
- Defaults and tunables: `honua/values.yaml`
- Values contract and migration policy: `docs/values-contract.md`, `docs/MIGRATION.md`
- Ticket 2 smoke evidence: `docs/smoke/ticket-2-helm-smoke.md`
- Environment overlays: `honua/values-dev.yaml`, `honua/values-stage.yaml`, `honua/values-prod.yaml`
- Chart metadata and templates: `honua/Chart.yaml`, `honua/templates/`
- Release pipeline and versioning: `.github/workflows/release.yml`, `RELEASING.md`
- Origin and value-contract continuity from the monorepo split: `docs/MIGRATION.md`

## Boundary

Reusable cloud infrastructure belongs in `honua-terraform`; this chart owns Kubernetes packaging and values.
