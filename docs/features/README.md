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
- Liveness, readiness, and startup probes on the server health endpoints.

## Source Evidence

- Chart source: `honua/`
- Usage and production examples: `honua/README.md`
- Defaults and tunables: `honua/values.yaml`
- Chart metadata and templates: `honua/Chart.yaml`, `honua/templates/`

## Boundary

Reusable cloud infrastructure belongs in `honua-terraform`; this chart owns Kubernetes packaging and values.
