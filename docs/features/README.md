# Honua Helm Feature Map

This repository packages Honua Server for Kubernetes.

## Current Chart Capabilities

- Kubernetes Deployment, Service, ingress, config, secret, and probe wiring for Honua Server.
- Optional Bitnami PostgreSQL and Redis subcharts for development or simple environments.
- External PostGIS and Redis support through secret/config environment values.
- AOT and JIT image tag selection, with AOT as the default chart posture.
- HorizontalPodAutoscaler support with CPU/memory targets and scale-up/scale-down behavior.
- Production-oriented resource, ingress, TLS, public base URL, observability, and OpenTelemetry values.
- Existing-secret mode for customer-managed credentials.
- Documented values contract with Helm schema validation for required secrets, dependency auth, and HPA targets.
- Dev, stage, and prod overlay values for release-lane and customer-operated installs.
- Liveness, readiness, and startup probes on the server health endpoints.

## Source Evidence

- Chart source: `honua/`
- Usage and production examples: `honua/README.md`
- Defaults and tunables: `honua/values.yaml`
- Values contract and migration policy: `docs/values-contract.md`, `docs/MIGRATION.md`
- Ticket 2 smoke evidence: `docs/smoke/ticket-2-helm-smoke.md`
- Environment overlays: `honua/values-dev.yaml`, `honua/values-stage.yaml`, `honua/values-prod.yaml`
- Chart metadata and templates: `honua/Chart.yaml`, `honua/templates/`

## Boundary

Reusable cloud infrastructure belongs in `honua-terraform`; this chart owns Kubernetes packaging and values.
