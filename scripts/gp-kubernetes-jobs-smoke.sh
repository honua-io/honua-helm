#!/usr/bin/env bash
# kind smoke for geoprocessing on Kubernetes Jobs (honua-helm#77).
#
# Installs the chart with geoprocessing.kubernetesJobs enabled against an
# existing cluster (kind in CI) with PostGIS and Redis already running in the
# namespace, then proves:
#   1. the post-install RBAC check passes as the server's service account;
#   2. the server's service account can do exactly what the backend needs in
#      the namespace, and nothing it does not (Secrets, other namespaces);
#   3. the server pod mounts its token and loads the GP wiring;
#   4. an asynchronous geometry.buffer submission through OGC API Processes is
#      dispatched by the live server as a batch/v1 Job in the namespace, with
#      the Job service account, the server image and the worker launch env;
#   5. removing the RoleBinding makes the RBAC check fail with
#      HONUA_GP_K8S_RBAC_MISSING.
# The Job's own completion is recorded (worker exit, GP job status) but only
# gated when HONUA_GP_REQUIRE_COMPLETION=true: a worker image must contain the
# worker-only execution profile (honua-server#5780) to run the job it was
# launched for.
set -euo pipefail

namespace="${HONUA_SMOKE_NAMESPACE:-honua-smoke}"
release="${HONUA_SMOKE_RELEASE:-honua}"
evidence="${HONUA_SMOKE_EVIDENCE:-/tmp/honua-gp-smoke}"
digest="${HONUA_IMAGE_DIGEST:?set HONUA_IMAGE_DIGEST}"
repository="${HONUA_IMAGE_REPOSITORY:-ghcr.io/honua-io/honua-server}"
require_completion="${HONUA_GP_REQUIRE_COMPLETION:-false}"
fullname="$release-honua"
server_sa="system:serviceaccount:$namespace:$fullname"
port="${HONUA_SMOKE_PORT:-18080}"
mkdir -p "$evidence"

fail() { echo "gp smoke failed: $*" >&2; exit 1; }
can() { kubectl auth can-i "$@" --as "$server_sa" 2>/dev/null || true; }

helm install "$release" ./honua -n "$namespace" --wait --timeout 10m \
  -f honua/ci-values/upgrade-base.yaml \
  --set image.repository="$repository" --set image.tag= --set image.digest="$digest" \
  --set image.pullPolicy=IfNotPresent \
  --set geoprocessing.kubernetesJobs.enabled=true \
  --set geoprocessing.kubernetesJobs.allowInlineWorkerSecrets=true \
  --set geoprocessing.kubernetesJobs.ttlSecondsAfterFinished=600 | tee "$evidence/helm-install.txt"

# 1. The post-install RBAC check ran as the server and passed.
kubectl logs -n "$namespace" "job/$fullname-gp-rbac-check" | tee "$evidence/rbac-check.log"
grep -q "gp kubernetes jobs rbac check passed" "$evidence/rbac-check.log" || fail "RBAC check did not pass"

# 2. Exactly the backend's permissions.
{
  for verb in create get list watch delete; do echo "$verb jobs.batch: $(can "$verb" jobs.batch -n "$namespace")"; done
  for verb in get list watch; do echo "$verb pods: $(can "$verb" pods -n "$namespace")"; done
  echo "get pods/log: $(can get pods --subresource=log -n "$namespace")"
  echo "get secrets: $(can get secrets -n "$namespace")"
  echo "create deployments: $(can create deployments.apps -n "$namespace")"
  echo "create jobs.batch in default: $(can create jobs.batch -n default)"
  echo "update jobs.batch: $(can update jobs.batch -n "$namespace")"
} | tee "$evidence/can-i.txt"
grep -c ': yes$' "$evidence/can-i.txt" | grep -qx 9 || fail "server service account is missing a backend permission"
grep -c ': no$' "$evidence/can-i.txt" | grep -qx 4 || fail "server service account holds more than the backend needs"

# 3. Server pod wiring.
kubectl get deployment "$fullname" -n "$namespace" -o json > "$evidence/deployment.json"
jq -e '.spec.template.spec.automountServiceAccountToken == true' "$evidence/deployment.json" >/dev/null \
  || fail "server pod does not mount its service account token"
jq -e --arg cm "$fullname-gp-kubernetes-jobs" \
  '[.spec.template.spec.containers[0].envFrom[] | (.configMapRef.name // .secretRef.name)] | index($cm) != null' \
  "$evidence/deployment.json" >/dev/null || fail "server does not load the GP wiring"
kubectl get configmap "$fullname-gp-kubernetes-jobs" -n "$namespace" -o yaml > "$evidence/gp-configmap.yaml"
grep -q 'ControlPlane__ExecutionWorkloads__2__Backend: honua-kubernetes-job' "$evidence/gp-configmap.yaml" \
  || fail "GP workload not registered against honua-kubernetes-job"

# 4. A real GP submission becomes a Kubernetes Job.
kubectl port-forward -n "$namespace" "svc/$fullname" "$port:80" > "$evidence/port-forward.log" 2>&1 &
forward=$!
trap 'kill "$forward" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -fsS -o /dev/null "http://127.0.0.1:$port/healthz/live" && break; sleep 1; done
admin_password="$(kubectl get secret "$fullname-secret" -n "$namespace" -o jsonpath='{.data.HONUA_ADMIN_PASSWORD}' | base64 -d)"
# POINT(0 0) as little-endian WKB.
wkb="$(printf '\001\001\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000' | base64)"
status="$(curl -sS -o "$evidence/submit.json" -w '%{http_code}' \
  -H "Host: $fullname" -H "X-API-Key: $admin_password" -H 'Content-Type: application/json' \
  -H 'Prefer: respond-async' \
  --data "{\"inputs\":{\"wkb\":\"$wkb\",\"srid\":4326,\"distance\":1}}" \
  "http://127.0.0.1:$port/ogc/processes/processes/geometry.buffer/execution")"
echo "submit HTTP $status" | tee "$evidence/submit-status.txt"
cat "$evidence/submit.json"; echo
case "$status" in 200|201|202) ;; *) fail "geometry.buffer submission returned HTTP $status" ;; esac
job_id="$(jq -r '.jobID // .jobId // .id // empty' "$evidence/submit.json")"
[ -n "$job_id" ] || fail "submission returned no job id"

job=""
for _ in $(seq 1 60); do
  job="$(kubectl get jobs -n "$namespace" -l app.kubernetes.io/managed-by=honua-controlplane -o name | head -1)"
  [ -n "$job" ] && break
  sleep 2
done
[ -n "$job" ] || { kubectl logs -n "$namespace" "deployment/$fullname" > "$evidence/server.log" || true; fail "no Kubernetes Job was created for GP job $job_id"; }
kubectl get "$job" -n "$namespace" -o json > "$evidence/gp-job.json"
jq -e --arg sa "$fullname-gp-job" '.spec.template.spec.serviceAccountName == $sa' "$evidence/gp-job.json" >/dev/null \
  || fail "GP Job does not run as the job service account"
jq -e --arg image "$repository@$digest" '.spec.template.spec.containers[0].image == $image' "$evidence/gp-job.json" >/dev/null \
  || fail "GP Job does not run the server image"
jq -e '.spec.backoffLimit == 0 and .spec.ttlSecondsAfterFinished == 600' "$evidence/gp-job.json" >/dev/null \
  || fail "GP Job does not carry the backend's backoff/TTL"
jq -e '.metadata.labels["honua.io/workload-kind"] == "geoprocessing" and (.metadata.labels["honua.io/operation-id"] | length > 0)' \
  "$evidence/gp-job.json" >/dev/null || fail "GP Job lacks the operation labels"
jq -e '[.spec.template.spec.containers[0].env[].name] as $n
       | ($n | index("HONUA_OPERATION_ID")) != null and ($n | index("ConnectionStrings__redis")) != null
         and ($n | index("ConnectionStrings__DefaultConnection")) != null' "$evidence/gp-job.json" >/dev/null \
  || fail "GP Job lacks the launch or worker environment"
echo "GP job $job_id dispatched as $job" | tee "$evidence/dispatch.txt"

# Completion: recorded, gated only when the image carries the worker profile.
outcome="not-observed"
for _ in $(seq 1 90); do
  state="$(kubectl get "$job" -n "$namespace" -o jsonpath='{.status.succeeded}/{.status.failed}')"
  case "$state" in 1/*) outcome="job-succeeded"; break ;; */1) outcome="job-failed"; break ;; esac
  sleep 2
done
kubectl logs -n "$namespace" "$job" --tail=200 > "$evidence/worker.log" 2>&1 || true
curl -sS -H "Host: $fullname" -H "X-API-Key: $admin_password" \
  "http://127.0.0.1:$port/ogc/processes/jobs/$job_id" > "$evidence/gp-job-status.json" || true
echo "worker outcome: $outcome; GP status: $(jq -r '.status // empty' "$evidence/gp-job-status.json" 2>/dev/null)" \
  | tee "$evidence/completion.txt"
if [ "$require_completion" = "true" ]; then
  [ "$outcome" = "job-succeeded" ] || fail "worker Job did not succeed ($outcome)"
  jq -e '.status == "successful"' "$evidence/gp-job-status.json" >/dev/null || fail "GP job did not report successful"
fi
kubectl delete "$job" -n "$namespace" --wait=false >/dev/null 2>&1 || true

# 5. Missing RBAC fails the check by name, not silently.
kubectl delete rolebinding "$fullname-gp-kubernetes-jobs" -n "$namespace"
set +e
helm test "$release" -n "$namespace" --filter "name=$fullname-gp-rbac-check" --timeout 5m > "$evidence/negative-helm-test.txt" 2>&1
negative=$?
set -e
kubectl logs -n "$namespace" "job/$fullname-gp-rbac-check" > "$evidence/negative-rbac-check.log" 2>&1 || true
cat "$evidence/negative-rbac-check.log"
[ "$negative" -ne 0 ] || fail "RBAC check passed without the RoleBinding"
grep -q "HONUA_GP_K8S_RBAC_MISSING: $server_sa cannot create jobs.batch" "$evidence/negative-rbac-check.log" \
  || fail "RBAC check did not name the missing permission"

echo "gp kubernetes jobs smoke passed"
