#!/usr/bin/env bash
set -euo pipefail

namespace="${HONUA_SMOKE_NAMESPACE:-honua-smoke}"
release="${HONUA_SMOKE_RELEASE:-honua}"
evidence="${HONUA_SMOKE_EVIDENCE:-/tmp/honua-smoke}"
digest_a="${HONUA_IMAGE_DIGEST_A:?set HONUA_IMAGE_DIGEST_A}"
digest_b="${HONUA_IMAGE_DIGEST_B:?set HONUA_IMAGE_DIGEST_B}"
repository="${HONUA_IMAGE_REPOSITORY:-ghcr.io/honua-io/honua-server}"

[[ "$digest_a" =~ ^sha256:[0-9a-f]{64}$ && "$digest_b" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$digest_a" != "$digest_b" ]] || { echo "distinct-digest smoke refuses identical A/B digests" >&2; exit 1; }
mkdir -p "$evidence"

assert_equal() { [[ "$1" == "$2" ]] || { echo "expected '$1', observed '$2'" >&2; return 1; }; }

capture_phase() {
  local phase="$1" expected_digest="$2" expected_release="$3" dir="$evidence/$1"
  mkdir -p "$dir"
  date -u +%FT%TZ > "$dir/timestamp.txt"
  helm get manifest "$release" -n "$namespace" > "$dir/helm-manifest.yaml"
  helm get values "$release" -n "$namespace" --all -o yaml > "$dir/helm-values.yaml"
  helm history "$release" -n "$namespace" -o json > "$dir/helm-history.json"
  kubectl get configmap "$release-honua-release-info" -n "$namespace" -o yaml > "$dir/release-info.yaml"
  kubectl get deployment "$release-honua" -n "$namespace" -o json > "$dir/deployment.json"
  kubectl get replicaset -n "$namespace" -l app.kubernetes.io/instance="$release" -o json > "$dir/replicasets.json"
  kubectl get pods -n "$namespace" -l app.kubernetes.io/instance="$release" -o json > "$dir/pods.json"
  helm test "$release" -n "$namespace" --logs --timeout 5m | tee "$dir/helm-test.log"

  local rendered image_id marker marker_sha seed_count config_checksum secret_checksum
  rendered="$(jq -r '.spec.template.spec.containers[] | select(.name=="honua") | .image' "$dir/deployment.json")"
  assert_equal "$repository@$expected_digest" "$rendered"
  image_id="$(jq -r '[.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status=="True")) | .status.containerStatuses[] | select(.name=="honua") | .imageID] | unique | if length == 1 then .[0] else error("ready pods do not have one imageID") end' "$dir/pods.json")"
  marker="$(kubectl exec -n "$namespace" deployment/"$release-honua" -- printenv HONUA_RELEASE_ID)"
  assert_equal "$expected_release" "$marker"
  marker_sha="$(printf '%s' "$marker" | sha256sum | awk '{print $1}')"
  seed_count="$(kubectl exec -n "$namespace" deployment/honua-postgis -- psql -U honua -d honua -Atc 'select count(*) from public.helm_rollback_seed')"
  assert_equal "1" "$seed_count"
  config_checksum="$(jq -r '.spec.template.metadata.annotations["checksum/config"]' "$dir/deployment.json")"
  secret_checksum="$(jq -r '.spec.template.metadata.annotations["checksum/secret"]' "$dir/deployment.json")"
  jq -n --arg phase "$phase" --arg expectedDigest "$expected_digest" --arg renderedImage "$rendered" \
    --arg imageID "$image_id" --arg releaseID "$marker" --arg markerSha256 "$marker_sha" \
    --arg seedCount "$seed_count" --arg configChecksum "$config_checksum" --arg secretChecksum "$secret_checksum" \
    '{phase:$phase,expectedDigest:$expectedDigest,renderedImage:$renderedImage,imageID:$imageID,releaseID:$releaseID,functionalMarkerSha256:$markerSha256,seededRows:($seedCount|tonumber),configChecksum:$configChecksum,secretChecksum:$secretChecksum}' > "$dir/summary.json"
}

common=(-n "$namespace" --wait --timeout 10m --set image.repository="$repository" --set image.tag= --set image.pullPolicy=IfNotPresent)
helm install "$release" ./honua -f honua/ci-values/upgrade-base.yaml --set image.digest="$digest_a" "${common[@]}"
kubectl exec -n "$namespace" deployment/honua-postgis -- psql -U honua -d honua -v ON_ERROR_STOP=1 -c \
  "create table public.helm_rollback_seed(id integer primary key, marker text not null); insert into public.helm_rollback_seed values (1, 'seeded-before-upgrade');"
capture_phase install "$digest_a" honua-ci-upgrade-base

helm upgrade "$release" ./honua -f honua/ci-values/upgrade-target.yaml --set image.digest="$digest_b" "${common[@]}"
capture_phase upgrade "$digest_b" honua-ci-upgrade-target

helm rollback "$release" 1 -n "$namespace" --wait --timeout 10m
capture_phase rollback "$digest_a" honua-ci-upgrade-base

image_a="$(jq -r .imageID "$evidence/install/summary.json")"
image_b="$(jq -r .imageID "$evidence/upgrade/summary.json")"
image_rollback="$(jq -r .imageID "$evidence/rollback/summary.json")"
[[ "$image_a" != "$image_b" ]] || { echo "kubelet used the same imageID for A and B" >&2; exit 1; }
assert_equal "$image_a" "$image_rollback"
if jq -e --arg b "$image_b" '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status=="True")) | .status.containerStatuses[] | select(.name=="honua" and .imageID==$b)' "$evidence/rollback/pods.json" >/dev/null; then
  echo "a ready rollback pod still serves digest B" >&2; exit 1
fi

if assert_equal "$image_a" "$image_b" >/dev/null 2>&1; then
  echo "negative fixture failed to detect a non-restored image" >&2; exit 1
fi
printf '%s\n' 'PASS: deliberately wrong rollback identity was rejected' > "$evidence/negative-fixture.txt"
jq -s '{schemaVersion:1,result:"pass",distinctDigests:true,phases:.}' \
  "$evidence/install/summary.json" "$evidence/upgrade/summary.json" "$evidence/rollback/summary.json" > "$evidence/summary.json"
