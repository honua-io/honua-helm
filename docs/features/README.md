---
type: index
title: "What this chart packages"
description: "How Honua Server is packaged for Kubernetes: what the chart deploys, what it expects you to provide, and where the operator surface begins."
resource: "https://github.com/honua-io/honua-helm/tree/trunk/honua"
tags: [helm, kubernetes, packaging]
---
# Honua Helm Feature Map

This repository packages Honua Server for Kubernetes.

## Current Chart Capabilities

- Kubernetes Deployment, Service, ingress, config, secret, and probe wiring for Honua Server.
- Optional chart-managed PostGIS (development) and Bitnami PostgreSQL subchart.
- External PostGIS support through secret/config environment values.
- AOT and JIT image tag selection, with AOT as the default chart posture.
- Digest-pinned image rendering for immutable production releases.
- Explicit Deployment strategy defaults for inline migration safety.
- Pre-install/pre-upgrade preflight hook for required credentials, database reachability and registry reachability.
- Release-info ConfigMap, labels, Pod-template annotations, NOTES, and helm-test output for evidence capture.
- CI install/upgrade/rollback smoke workflow with captured release-info and helm-test evidence.
- HorizontalPodAutoscaler support with CPU/memory targets and scale-up/scale-down behavior.
- Production-oriented resource, ingress, TLS, public base URL, observability, and OpenTelemetry values.
- Existing-secret and `extraEnvFrom` modes for customer-managed credentials.
- Documented values contract with Helm schema validation for dependency auth and HPA targets, plus template guards for required runtime secrets.
- Dev, stage, and prod overlay values for release-lane and customer-operated installs.
- Liveness, readiness, and startup probes on the server health endpoints.
- Packaged release pipeline that publishes the chart to `oci://ghcr.io/honua-io/charts` on a `chart-vX.Y.Z` tag, stamps `Chart.yaml` `version`/`appVersion` and `values.yaml` `image.digest` (clearing `image.tag` and setting `image.pullPolicy: IfNotPresent`) at package time, and attaches the `.tgz` to a GitHub Release on tag-triggered runs. `workflow_dispatch` is dry-run only (`chart_version` and `app_version` inputs: validate, stamp, lint, render, and package with no publish).

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

Reusable cloud infrastructure belongs in `honua-iac`; this chart owns Kubernetes packaging and values.
