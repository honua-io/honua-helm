#!/usr/bin/env bash
# Out-of-band migration smoke (migrations.job.enabled) against a kind cluster
# that already runs the PostGIS and Redis fixtures from ci.yml.
#
# A fresh release on its own database is installed and then upgraded with the
# migration Job enabled. Each phase must show:
#   * the <release>-honua-migrate hook Job ran the selected image with
#     HONUA_MIGRATE_ONLY=true, succeeded, and printed exactly one
#     honua.migrate-only/v1 summary line with outcome=completed / exitCode=0;
#   * the Deployment carries HONUA_SKIP_MIGRATIONS=true and rolled with the
#     chart-chosen RollingUpdate strategy;
#   * helm test passes against the serving pods.
# The install applies the full journal (journalWasEmpty, non-empty
# appliedScripts); the upgrade finds it current (empty appliedScripts) and rolls
# the Deployment to a second ReplicaSet revision.
#
# The image must ship migrate-only mode (honua-server 4087d93, #6479). Pin it
# with HONUA_MIGRATE_ONLY_IMAGE_DIGEST. When that is empty the script resolves
# HONUA_MIGRATE_ONLY_IMAGE_TAG (default nightly-aot) to its digest and refuses
# unless the image's org.opencontainers.image.revision contains that commit.
set -euo pipefail

namespace="${HONUA_SMOKE_NAMESPACE:-honua-smoke}"
release="${HONUA_MIGRATE_SMOKE_RELEASE:-honua-mj}"
evidence="${HONUA_MIGRATE_SMOKE_EVIDENCE:-/tmp/honua-smoke/migration-job}"
repository_path="honua-io/honua-server"
repository="ghcr.io/${repository_path}"
required_commit="${HONUA_MIGRATE_ONLY_REQUIRED_COMMIT:-4087d93aecf49ac087bfe102358c019ae818ac96}"
database="${HONUA_MIGRATE_SMOKE_DATABASE:-honua_migrate_job}"
fullname="${release}-honua"
job="${fullname}-migrate"

fail() { echo "migration-job smoke failed: $*" >&2; exit 1; }
mkdir -p "$evidence"

resolve_digest() {
  local tag token index amd64 config revision status
  tag="${HONUA_MIGRATE_ONLY_IMAGE_TAG:-nightly-aot}"
  token="$(curl -fsS "https://ghcr.io/token?scope=repository:${repository_path}:pull" | jq -r .token)"
  index="$(curl -fsSI -H "Authorization: Bearer ${token}" \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json' \
    "https://ghcr.io/v2/${repository_path}/manifests/${tag}" | tr -d '\r' | awk 'tolower($1)=="docker-content-digest:" {print $2}')"
  [[ "$index" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "could not resolve ${repository}:${tag}"
  amd64="$(curl -fsS -H "Authorization: Bearer ${token}" \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json' \
    "https://ghcr.io/v2/${repository_path}/manifests/${index}" \
    | jq -r '[.manifests[] | select(.platform.os=="linux" and .platform.architecture=="amd64")][0].digest')"
  config="$(curl -fsS -H "Authorization: Bearer ${token}" \
    -H 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
    "https://ghcr.io/v2/${repository_path}/manifests/${amd64}" | jq -r .config.digest)"
  revision="$(curl -fsSL -H "Authorization: Bearer ${token}" \
    "https://ghcr.io/v2/${repository_path}/blobs/${config}" | jq -r '.config.Labels["org.opencontainers.image.revision"] // empty')"
  [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || fail "${repository}:${tag} carries no org.opencontainers.image.revision label"
  status="$(gh api "repos/${repository_path}/compare/${required_commit}...${revision}" --jq .status)"
  case "$status" in
    identical|ahead) ;;
    *) fail "${repository}:${tag} is ${revision}, which does not contain migrate-only mode (${required_commit}, compare status ${status}); no published image ships it yet, so pin HONUA_MIGRATE_ONLY_IMAGE_DIGEST once one does" ;;
  esac
  jq -n --arg tag "$tag" --arg digest "$index" --arg revision "$revision" --arg requiredCommit "$required_commit" \
    '{resolvedTag:$tag,digest:$digest,revision:$revision,requiredCommit:$requiredCommit}' > "$evidence/image.json"
  echo "$index"
}

digest="${HONUA_MIGRATE_ONLY_IMAGE_DIGEST:-}"
if [[ -z "$digest" ]]; then
  digest="$(resolve_digest)"
  echo "::notice::migration-job smoke resolved ${HONUA_MIGRATE_ONLY_IMAGE_TAG:-nightly-aot} to ${digest}; pin HONUA_MIGRATE_ONLY_IMAGE_DIGEST in ci.yml to make this lane reproducible."
else
  jq -n --arg digest "$digest" '{pinnedDigest:$digest}' > "$evidence/image.json"
fi
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "image digest '${digest}' is not sha256:<64 hex>"

# A database of its own, so the install is a fresh journal (no contract gate)
# and nothing touches the distinct-digest release's schema.
kubectl exec -n "$namespace" deployment/honua-postgis -- psql -U honua -d honua -v ON_ERROR_STOP=1 \
  -c "drop database if exists ${database}" -c "create database ${database}"

connection="Host=honua-postgis;Port=5432;Database=${database};Username=honua;Password=ci-password"
common=(-n "$namespace" --wait --timeout 15m
  -f honua/ci-values/upgrade-base.yaml
  --set image.repository="$repository" --set image.tag= --set image.digest="$digest" --set image.pullPolicy=IfNotPresent
  --set-string secret.env.ConnectionStrings__DefaultConnection="$connection"
  --set-string config.env.Public__BaseUrl="http://${fullname}"
  --set migrations.job.enabled=true)

check_phase() {
  local phase="$1" release_id="$2" expected_revision="$3" dir="$evidence/$1" summary
  mkdir -p "$dir"
  kubectl get job "$job" -n "$namespace" -o json > "$dir/job.json"
  kubectl logs -n "$namespace" "job/$job" > "$dir/job.log" 2>&1
  kubectl get deployment "$fullname" -n "$namespace" -o json > "$dir/deployment.json"
  kubectl get replicaset -n "$namespace" -l app.kubernetes.io/instance="$release" -o json > "$dir/replicasets.json"
  helm get manifest "$release" -n "$namespace" > "$dir/helm-manifest.yaml"
  helm get hooks "$release" -n "$namespace" > "$dir/helm-hooks.yaml"

  jq -e '.status.succeeded == 1' "$dir/job.json" >/dev/null || fail "${phase}: Job ${job} did not succeed"
  jq -e --arg image "${repository}@${digest}" \
    '.spec.template.spec.containers[0] | .image == $image and ([.env[] | select(.name=="HONUA_MIGRATE_ONLY" and .value=="true")] | length == 1)' \
    "$dir/job.json" >/dev/null || fail "${phase}: Job does not run ${repository}@${digest} with HONUA_MIGRATE_ONLY=true"
  jq -e '.spec.backoffLimit == 0 and .spec.template.spec.restartPolicy == "Never"' "$dir/job.json" >/dev/null \
    || fail "${phase}: Job must have backoffLimit 0 and restartPolicy Never"

  grep -F '"format":"honua.migrate-only/v1"' "$dir/job.log" > "$dir/summary.jsonl" || fail "${phase}: no honua.migrate-only/v1 summary line in the Job log"
  [[ "$(wc -l < "$dir/summary.jsonl")" -eq 1 ]] || fail "${phase}: expected exactly one summary line"
  summary="$(cat "$dir/summary.jsonl")"
  jq -e '.outcome == "completed" and .exitCode == 0 and .code == "completed" and .schemaVerified == true and (.schemaNumber | type == "number")' \
    <<<"$summary" >/dev/null || fail "${phase}: summary is not a verified completed run: ${summary}"
  echo "${phase} summary: ${summary}"

  jq -e '.spec.strategy.type == "RollingUpdate"' "$dir/deployment.json" >/dev/null || fail "${phase}: Deployment strategy is not RollingUpdate"
  jq -e '[.spec.template.spec.containers[] | select(.name=="honua") | .env[]? | select(.name=="HONUA_SKIP_MIGRATIONS" and .value=="true")] | length == 1' \
    "$dir/deployment.json" >/dev/null || fail "${phase}: Deployment does not set HONUA_SKIP_MIGRATIONS=true"
  jq -e --arg rev "$expected_revision" '.metadata.annotations["deployment.kubernetes.io/revision"] == $rev' "$dir/deployment.json" >/dev/null \
    || fail "${phase}: Deployment is not at rollout revision ${expected_revision}"
  kubectl get configmap "${fullname}-release-info" -n "$namespace" -o jsonpath='{.data.HONUA_RELEASE_ID}' | grep -qx "$release_id" \
    || fail "${phase}: release-info does not name ${release_id}"
  kubectl rollout status "deployment/$fullname" -n "$namespace" --timeout=5m | tee "$dir/rollout-status.txt"
  helm test "$release" -n "$namespace" --logs --timeout 5m | tee "$dir/helm-test.log"
  jq -n --arg phase "$phase" --argjson summary "$summary" --arg revision "$expected_revision" \
    '{phase:$phase,deploymentRevision:$revision,strategy:"RollingUpdate",skipMigrations:true,migrateOnly:$summary}' > "$dir/result.json"
}

helm install "$release" ./honua "${common[@]}" --set release.id=honua-ci-migrate-install
check_phase install honua-ci-migrate-install 1
jq -e '.journalWasEmpty == true and (.appliedScripts | length) > 0' "$evidence/install/summary.jsonl" >/dev/null \
  || fail "install: a fresh database must apply the full journal"
# NOTES name the Job, the summary command and the typed exit codes.
helm get notes "$release" -n "$namespace" > "$evidence/install/notes.txt"
grep -Fq "job/${job}" "$evidence/install/notes.txt" || fail "NOTES do not name job/${job}"
grep -Fq 'honua.migrate-only/v1' "$evidence/install/notes.txt" || fail "NOTES do not show the summary command"
grep -Fq '5 contract approval needed' "$evidence/install/notes.txt" || fail "NOTES do not list the typed exit codes"
grep -Fq 'Upgrade strategy: RollingUpdate' "$evidence/install/notes.txt" || fail "NOTES do not report RollingUpdate"

helm upgrade "$release" ./honua "${common[@]}" --set release.id=honua-ci-migrate-upgrade
check_phase upgrade honua-ci-migrate-upgrade 2
jq -e '.journalWasEmpty == false and (.appliedScripts | length) == 0' "$evidence/upgrade/summary.jsonl" >/dev/null \
  || fail "upgrade: the journal was already current, so nothing should apply"
[[ "$(jq '[.items[] | select((.metadata.annotations["deployment.kubernetes.io/revision"] // "") != "")] | length' "$evidence/upgrade/replicasets.json")" -ge 2 ]] \
  || fail "upgrade: the Deployment did not roll to a new ReplicaSet"

jq -s '{schemaVersion:1,result:"pass",phases:.}' "$evidence/install/result.json" "$evidence/upgrade/result.json" > "$evidence/summary.json"
cat "$evidence/summary.json"
