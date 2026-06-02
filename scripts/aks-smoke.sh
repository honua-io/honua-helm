#!/usr/bin/env bash
#
# aks-smoke.sh — AKS install + upgrade + rollback smoke harness for the Honua
# Helm chart (honua-helm#10).
#
# This is the *harness* the operator runs against a live AKS validation cluster
# that matches the Azure Marketplace customer-operated path. It does not
# provision a cluster and it does not fabricate evidence: every recorded result
# comes from the commands it actually runs against the kubeconfig you supply.
#
# It captures the evidence the issue's acceptance criteria require:
#   - chart version and effective app version
#   - image reference and image digest
#   - the values file / overlay used (install + upgrade)
#   - the cluster / runtime target (current kube-context + AKS node summary)
#   - the exact helm/kubectl commands run (logged with timestamps)
#   - health-check output (`helm test` readiness logs + probe status)
#
# Modes:
#   (default)   run the live AKS smoke against the current kubeconfig context.
#   --dry-run   render + lint + kubeconform only, no cluster needed. Use this in
#               CI or locally to validate the harness and overlays without AKS.
#
# Usage:
#   scripts/aks-smoke.sh \
#     --release honua \
#     --namespace honua \
#     --image-tag v0.3.1-aot \
#     [--image-digest sha256:<64hex>] \
#     [--install-values honua/ci-values/aks-smoke-install.yaml] \
#     [--upgrade-values honua/ci-values/aks-smoke-upgrade.yaml] \
#     [--set key=value ...] \
#     [--evidence-dir evidence/aks-<date>] \
#     [--keep] [--dry-run]
#
# The runtime Secret named by the chosen install overlay (default
# `honua-aks-runtime`) MUST already exist in the target namespace, or be created
# by passing --create-runtime-secret with the connection inputs below. The
# harness never writes secret material to the evidence directory.
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHART_DIR="${REPO_ROOT}/honua"

RELEASE="honua"
NAMESPACE="honua"
INSTALL_VALUES="${CHART_DIR}/ci-values/aks-smoke-install.yaml"
UPGRADE_VALUES="${CHART_DIR}/ci-values/aks-smoke-upgrade.yaml"
IMAGE_REPO="ghcr.io/honua-io/honua-server"
IMAGE_TAG=""
IMAGE_DIGEST=""
RELEASE_ID=""
RELEASE_MANIFEST=""
RELEASE_DIGEST=""
EVIDENCE_DIR=""
TIMEOUT="10m"
DRY_RUN="false"
KEEP="false"
CREATE_RUNTIME_SECRET="false"
RUNTIME_SECRET_NAME=""
declare -a EXTRA_SET=()

# --------------------------------------------------------------------------- #
# Arg parsing
# --------------------------------------------------------------------------- #
die() { echo "ERROR: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --release) RELEASE="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --install-values) INSTALL_VALUES="$2"; shift 2 ;;
    --upgrade-values) UPGRADE_VALUES="$2"; shift 2 ;;
    --image-repo) IMAGE_REPO="$2"; shift 2 ;;
    --image-tag) IMAGE_TAG="$2"; shift 2 ;;
    --image-digest) IMAGE_DIGEST="$2"; shift 2 ;;
    --release-id) RELEASE_ID="$2"; shift 2 ;;
    --release-manifest) RELEASE_MANIFEST="$2"; shift 2 ;;
    --release-digest) RELEASE_DIGEST="$2"; shift 2 ;;
    --evidence-dir) EVIDENCE_DIR="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --set) EXTRA_SET+=("$2"); shift 2 ;;
    --create-runtime-secret) CREATE_RUNTIME_SECRET="true"; shift ;;
    --runtime-secret-name) RUNTIME_SECRET_NAME="$2"; shift 2 ;;
    --keep) KEEP="true"; shift ;;
    --dry-run) DRY_RUN="true"; shift ;;
    -h|--help) sed -n '2,60p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -d "${CHART_DIR}" ] || die "chart directory not found: ${CHART_DIR}"
[ -f "${INSTALL_VALUES}" ] || die "install values not found: ${INSTALL_VALUES}"
[ -f "${UPGRADE_VALUES}" ] || die "upgrade values not found: ${UPGRADE_VALUES}"
command -v helm >/dev/null 2>&1 || die "helm is required on PATH"

if [ -z "${EVIDENCE_DIR}" ]; then
  EVIDENCE_DIR="${REPO_ROOT}/evidence/aks-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "${EVIDENCE_DIR}"
LOG="${EVIDENCE_DIR}/commands.log"
SUMMARY="${EVIDENCE_DIR}/summary.md"

# --------------------------------------------------------------------------- #
# Command runner: echoes, timestamps, tees output into the evidence log.
# --------------------------------------------------------------------------- #
# The command echo and the command's own stderr are appended to the evidence
# log only; the command's stdout is left intact so callers can redirect a clean
# `helm template` render into a file. (Use `run_tee` when you also want stdout
# mirrored to the terminal.)
run() {
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "+ [${ts}] $*" >> "${LOG}"
  echo "+ [${ts}] $*" >&2
  "$@" 2>>"${LOG}"
}

# Like run, but also mirrors stdout to the terminal and the log. Use for steps
# whose stdout is human-facing (lint, helm test, history) rather than captured.
run_tee() {
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "+ [${ts}] $*" | tee -a "${LOG}" >&2
  "$@" 2>&1 | tee -a "${LOG}"
  return "${PIPESTATUS[0]}"
}

# helm --set flags shared by install and upgrade.
build_set_args() {
  local -a a=()
  a+=(--set "image.repository=${IMAGE_REPO}")
  if [ -n "${IMAGE_DIGEST}" ]; then
    a+=(--set "image.digest=${IMAGE_DIGEST}")
    a+=(--set "image.tag=")
    a+=(--set "image.pullPolicy=IfNotPresent")
  elif [ -n "${IMAGE_TAG}" ]; then
    a+=(--set "image.tag=${IMAGE_TAG}")
  fi
  [ -n "${RELEASE_ID}" ] && a+=(--set "release.id=${RELEASE_ID}")
  [ -n "${RELEASE_MANIFEST}" ] && a+=(--set "release.manifest=${RELEASE_MANIFEST}")
  [ -n "${RELEASE_DIGEST}" ] && a+=(--set "release.digest=${RELEASE_DIGEST}")
  local kv
  for kv in "${EXTRA_SET[@]:-}"; do
    [ -n "${kv}" ] && a+=(--set "${kv}")
  done
  printf '%s\n' "${a[@]}"
}

mapfile -t SET_ARGS < <(build_set_args)

# --------------------------------------------------------------------------- #
# Evidence header (filled progressively).
# --------------------------------------------------------------------------- #
CHART_VERSION="$(helm show chart "${CHART_DIR}" 2>/dev/null | awk -F': ' '/^version:/ {print $2}')"
APP_VERSION="$(helm show chart "${CHART_DIR}" 2>/dev/null | awk -F': ' '/^appVersion:/ {print $2}')"

{
  echo "# Honua AKS chart smoke evidence (honua-helm#10)"
  echo
  echo "- Generated (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- Mode: $([ "${DRY_RUN}" = "true" ] && echo 'dry-run (no cluster)' || echo 'live AKS')"
  echo "- Release: \`${RELEASE}\`  Namespace: \`${NAMESPACE}\`"
  echo "- Chart version: \`${CHART_VERSION}\`  App version: \`${APP_VERSION}\`"
  echo "- Image repo: \`${IMAGE_REPO}\`"
  echo "- Image tag: \`${IMAGE_TAG:-<unset>}\`  Image digest: \`${IMAGE_DIGEST:-<unset>}\`"
  echo "- Install overlay: \`${INSTALL_VALUES#"${REPO_ROOT}"/}\`"
  echo "- Upgrade overlay: \`${UPGRADE_VALUES#"${REPO_ROOT}"/}\`"
  echo
} > "${SUMMARY}"

# --------------------------------------------------------------------------- #
# DRY RUN: render + lint + kubeconform, no cluster.
# --------------------------------------------------------------------------- #
if [ "${DRY_RUN}" = "true" ]; then
  echo "== DRY RUN: render + lint only, no AKS cluster contacted ==" | tee -a "${LOG}" >&2
  run_tee helm lint "${CHART_DIR}" -f "${INSTALL_VALUES}" "${SET_ARGS[@]}" \
    || die "lint failed for install overlay"
  run_tee helm lint "${CHART_DIR}" -f "${UPGRADE_VALUES}" "${SET_ARGS[@]}" \
    || die "lint failed for upgrade overlay"

  run helm template "${RELEASE}" "${CHART_DIR}" -n "${NAMESPACE}" \
    -f "${INSTALL_VALUES}" "${SET_ARGS[@]}" \
    > "${EVIDENCE_DIR}/render-install.yaml" \
    || die "install render failed"
  run helm template "${RELEASE}" "${CHART_DIR}" -n "${NAMESPACE}" --is-upgrade \
    -f "${UPGRADE_VALUES}" "${SET_ARGS[@]}" \
    > "${EVIDENCE_DIR}/render-upgrade.yaml" \
    || die "upgrade render failed"

  if command -v kubeconform >/dev/null 2>&1; then
    run_tee kubeconform -strict -ignore-missing-schemas -summary \
      "${EVIDENCE_DIR}/render-install.yaml" || die "kubeconform install failed"
    run_tee kubeconform -strict -ignore-missing-schemas -summary \
      "${EVIDENCE_DIR}/render-upgrade.yaml" || die "kubeconform upgrade failed"
  else
    echo "kubeconform not on PATH; skipped manifest schema validation" | tee -a "${LOG}" >&2
  fi

  {
    echo "## Result"
    echo
    echo "Dry-run validation passed: lint + render + kubeconform for the AKS"
    echo "install and upgrade overlays. NO live AKS install/upgrade was run; this"
    echo "mode never contacts a cluster and produces no live deployment evidence."
  } >> "${SUMMARY}"
  echo
  echo "Dry-run evidence written to: ${EVIDENCE_DIR}"
  exit 0
fi

# --------------------------------------------------------------------------- #
# LIVE AKS path.
# --------------------------------------------------------------------------- #
command -v kubectl >/dev/null 2>&1 || die "kubectl is required for the live smoke"

KCONTEXT="$(kubectl config current-context 2>/dev/null || true)"
[ -n "${KCONTEXT}" ] || die "no current kube-context; set your AKS kubeconfig first"

cleanup() {
  if [ "${KEEP}" = "true" ]; then
    echo "--keep set; leaving release ${RELEASE} in namespace ${NAMESPACE}" | tee -a "${LOG}"
    return
  fi
  echo "== Cleanup: uninstalling ${RELEASE} ==" | tee -a "${LOG}"
  helm uninstall "${RELEASE}" -n "${NAMESPACE}" --wait --timeout "${TIMEOUT}" \
    >>"${LOG}" 2>&1 || true
}
trap cleanup EXIT

echo "== Cluster target ==" | tee -a "${LOG}"
{
  echo
  echo "## Cluster / runtime target"
  echo
  echo "- kube-context: \`${KCONTEXT}\`"
} >> "${SUMMARY}"
run kubectl cluster-info | head -5 || true
run kubectl get nodes -o wide > "${EVIDENCE_DIR}/nodes.txt" || true
# AKS sanity: surface node labels so reviewers can confirm an Azure target.
run kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.labels.kubernetes\.io/hostname}{"\t"}{.metadata.labels.kubernetes\.azure\.com/cluster}{"\t"}{.metadata.labels.node\.kubernetes\.io/instance-type}{"\n"}{end}' \
  > "${EVIDENCE_DIR}/aks-node-labels.txt" 2>/dev/null || true

run kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml \
  | kubectl apply -f - || true

# Optionally create the runtime Secret from connection inputs. Secret material
# is passed via env vars (HONUA_*), never logged, never written to evidence.
if [ "${CREATE_RUNTIME_SECRET}" = "true" ]; then
  SECRET_NAME="${RUNTIME_SECRET_NAME:-honua-aks-runtime}"
  : "${HONUA_DB_CONNECTION:?--create-runtime-secret requires HONUA_DB_CONNECTION env}"
  : "${HONUA_ADMIN_PASSWORD:?--create-runtime-secret requires HONUA_ADMIN_PASSWORD env}"
  : "${HONUA_MASTER_KEY:?--create-runtime-secret requires HONUA_MASTER_KEY env}"
  : "${HONUA_REDIS_CONNECTION:?--create-runtime-secret requires HONUA_REDIS_CONNECTION env}"
  echo "+ creating runtime Secret ${SECRET_NAME} (values not logged)" | tee -a "${LOG}"
  kubectl create secret generic "${SECRET_NAME}" -n "${NAMESPACE}" \
    --from-literal=ConnectionStrings__DefaultConnection="${HONUA_DB_CONNECTION}" \
    --from-literal=HONUA_ADMIN_PASSWORD="${HONUA_ADMIN_PASSWORD}" \
    --from-literal=Security__ConnectionEncryption__MasterKey="${HONUA_MASTER_KEY}" \
    --from-literal=ConnectionStrings__redis="${HONUA_REDIS_CONNECTION}" \
    --dry-run=client -o yaml | kubectl apply -f - >>"${LOG}" 2>&1
fi

# ----- INSTALL ----- #
echo "== Install smoke ==" | tee -a "${LOG}"
run_tee helm install "${RELEASE}" "${CHART_DIR}" -n "${NAMESPACE}" \
  -f "${INSTALL_VALUES}" "${SET_ARGS[@]}" \
  --wait --timeout "${TIMEOUT}" \
  || die "helm install failed"

run helm test "${RELEASE}" -n "${NAMESPACE}" --logs --timeout "${TIMEOUT}" \
  | tee "${EVIDENCE_DIR}/healthcheck-install.log" \
  || die "post-install helm test (readiness health check) failed"

# ----- UPGRADE ----- #
echo "== Upgrade smoke ==" | tee -a "${LOG}"
run_tee helm upgrade "${RELEASE}" "${CHART_DIR}" -n "${NAMESPACE}" \
  -f "${UPGRADE_VALUES}" "${SET_ARGS[@]}" \
  --wait --timeout "${TIMEOUT}" \
  || die "helm upgrade failed"

run helm test "${RELEASE}" -n "${NAMESPACE}" --logs --timeout "${TIMEOUT}" \
  | tee "${EVIDENCE_DIR}/healthcheck-upgrade.log" \
  || die "post-upgrade helm test (readiness health check) failed"

# ----- ROLLBACK ----- #
echo "== Rollback smoke ==" | tee -a "${LOG}"
run_tee helm rollback "${RELEASE}" 1 -n "${NAMESPACE}" --wait --timeout "${TIMEOUT}" \
  || die "helm rollback failed"
run helm test "${RELEASE}" -n "${NAMESPACE}" --logs --timeout "${TIMEOUT}" \
  | tee "${EVIDENCE_DIR}/healthcheck-rollback.log" \
  || die "post-rollback helm test failed"

# ----- EVIDENCE CAPTURE ----- #
echo "== Capturing release evidence ==" | tee -a "${LOG}"
helm history "${RELEASE}" -n "${NAMESPACE}" > "${EVIDENCE_DIR}/helm-history.txt" 2>&1 || true
helm get notes "${RELEASE}" -n "${NAMESPACE}" > "${EVIDENCE_DIR}/helm-notes.txt" 2>&1 || true
helm get values "${RELEASE}" -n "${NAMESPACE}" > "${EVIDENCE_DIR}/helm-values.txt" 2>&1 || true
kubectl get configmap "${RELEASE}-honua-release-info" -n "${NAMESPACE}" -o yaml \
  > "${EVIDENCE_DIR}/release-info.yaml" 2>&1 || true
kubectl get deploy,po,svc -n "${NAMESPACE}" -o wide \
  > "${EVIDENCE_DIR}/workloads.txt" 2>&1 || true
# Probe status / health surfaces straight from the running pods.
kubectl get pods -n "${NAMESPACE}" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' \
  > "${EVIDENCE_DIR}/pod-readiness.txt" 2>&1 || true
kubectl get events -n "${NAMESPACE}" --sort-by=.lastTimestamp \
  > "${EVIDENCE_DIR}/events.txt" 2>&1 || true

# Record the resolved image digest as deployed (authoritative kubelet view).
kubectl get pods -n "${NAMESPACE}" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.imageID}{" "}{end}{"\n"}{end}' \
  > "${EVIDENCE_DIR}/image-ids.txt" 2>&1 || true

{
  echo
  echo "## Result"
  echo
  echo "Live AKS install + upgrade + rollback smoke completed against context"
  echo "\`${KCONTEXT}\`. Evidence files in this directory:"
  echo
  echo '```'
  ls -1 "${EVIDENCE_DIR}"
  echo '```'
  echo
  echo "Health-check output: \`healthcheck-install.log\`, \`healthcheck-upgrade.log\`,"
  echo "\`healthcheck-rollback.log\`. Resolved image digests: \`image-ids.txt\`."
  echo "Release metadata: \`release-info.yaml\`. Command transcript: \`commands.log\`."
} >> "${SUMMARY}"

echo
echo "AKS smoke complete. Evidence written to: ${EVIDENCE_DIR}"
