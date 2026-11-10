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
#   4. an asynchronous managed buffer or native conversion through OGC API Processes is
#      dispatched by the live server as a batch/v1 Job in the namespace, with
#      the Job service account, the selected image and the worker env;
#   5. removing the RoleBinding makes the RBAC check fail with
#      HONUA_GP_K8S_RBAC_MISSING.
# Completion, result semantics, and secret-backed worker configuration are required.
set -euo pipefail

namespace="${HONUA_SMOKE_NAMESPACE:-honua-smoke}"
release="${HONUA_SMOKE_RELEASE:-honua}"
evidence="${HONUA_SMOKE_EVIDENCE:-/tmp/honua-gp-smoke}"
digest="${HONUA_IMAGE_DIGEST:?set HONUA_IMAGE_DIGEST}"
repository="${HONUA_IMAGE_REPOSITORY:-ghcr.io/honua-io/honua-server}"
# Legacy dispatch-only mode must not produce a green smoke receipt.
[ "${HONUA_GP_REQUIRE_COMPLETION:-true}" = true ] || { echo "completion is required" >&2; exit 1; }
[ "${HONUA_GP_SERVER_ENVFROM:-true}" = true ] || { echo "envFrom is required" >&2; exit 1; }
runtime_profile="${HONUA_GP_RUNTIME_PROFILE:-managed}"
worker_repository="${HONUA_GP_WORKER_REPOSITORY:-$repository}"
worker_digest="${HONUA_GP_WORKER_DIGEST:-}"
worker_tag="${HONUA_GP_WORKER_TAG:-}"
if [ "$runtime_profile" = native ]; then
  [ -n "${HONUA_GP_WORKER_REPOSITORY:-}" ] && { [ -n "$worker_digest" ] || [ -n "$worker_tag" ]; } \
    || { echo "native mode requires an explicit heavy worker image" >&2; exit 1; }
else
  [ "$runtime_profile" = managed ] || { echo "unknown runtime profile" >&2; exit 1; }
  worker_digest="${worker_digest:-$digest}"
fi
worker_image="$worker_repository${worker_digest:+@$worker_digest}"
[ -n "$worker_digest" ] || worker_image="$worker_repository:$worker_tag"
fullname="$release-honua"
server_sa="system:serviceaccount:$namespace:$fullname"
port="${HONUA_SMOKE_PORT:-18080}"
mkdir -p "$evidence"

fail() { echo "gp smoke failed: $*" >&2; exit 1; }
can() { kubectl auth can-i "$@" --as "$server_sa" 2>/dev/null || true; }

# Production secret-channel encryption requires a private certificate. Generate a
# disposable key outside the evidence directory and transport it via the runtime
# Secret (never command-line literal values or captured manifests).
keyring_dir="$(mktemp -d)"
chmod 700 "$keyring_dir"
forward=""
cleanup() {
  [ -z "$forward" ] || kill "$forward" 2>/dev/null || true
  rm -rf "$keyring_dir"
}
trap cleanup EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj '/CN=gp-smoke' \
  -keyout "$keyring_dir/key.pem" -out "$keyring_dir/cert.pem" 2>/dev/null
openssl pkcs12 -export -passout pass: -inkey "$keyring_dir/key.pem" \
  -in "$keyring_dir/cert.pem" -out "$keyring_dir/keyring.pfx"
base64 -w0 "$keyring_dir/keyring.pfx" > "$keyring_dir/keyring.b64"

helm install "$release" ./honua -n "$namespace" --wait --timeout 10m \
  -f honua/ci-values/upgrade-base.yaml \
  --set image.repository="$repository" --set image.tag= --set image.digest="$digest" \
  --set image.pullPolicy=IfNotPresent \
  --set geoprocessing.kubernetesJobs.enabled=true \
  --set-string config.env.Public__BaseUrl="http://$fullname" \
  --set geoprocessing.kubernetesJobs.workload.runtimeProfile="$runtime_profile" \
  --set geoprocessing.kubernetesJobs.image.repository="$worker_repository" \
  --set geoprocessing.kubernetesJobs.image.tag="$worker_tag" \
  --set geoprocessing.kubernetesJobs.image.digest="$worker_digest" \
  --set-string config.env.Operations__SecretChannel__KeyRingCertificatePkcs12=env:GP_SMOKE_KEYRING_PFX \
  --set-file secret.env.GP_SMOKE_KEYRING_PFX="$keyring_dir/keyring.b64" \
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

for _ in $(seq 1 30); do curl -fsS -o /dev/null "http://127.0.0.1:$port/healthz/live" && break; sleep 1; done
admin_password="$(kubectl get secret "$fullname-secret" -n "$namespace" -o jsonpath='{.data.HONUA_ADMIN_PASSWORD}' | base64 -d)"
if [ "$runtime_profile" = native ]; then
  process=gdal.ogr2ogr
  payload="$(python3 - <<'NATIVE'
import base64, json
csv = 'WKT,name,value\n"POINT Z (12.25 -4.5 7.75)",alpha,17\n"POINT Z (-23.5 8.25 -2.5)",beta,29\n'
print(json.dumps({"inputs": {"source": base64.b64encode(csv.encode()).decode(), "sourceFormat": "CSV", "targetFormat": "GeoJSON"}}))
NATIVE
)"
else
  process=geometry.buffer
  payload='{"inputs":{"wkb":"AQEAAAAAAAAAAAAAAAAAAAAAAAAA","srid":3857,"distance":500,"geodesic":false}}'
fi
status="$(curl -sS -o "$evidence/submit.json" -w '%{http_code}' \
  -H "Host: $fullname" -H "X-API-Key: $admin_password" -H 'Content-Type: application/json' \
  -H 'Prefer: respond-async' \
  --data "$payload" \
  "http://127.0.0.1:$port/ogc/processes/processes/$process/execution")"
echo "submit HTTP $status" | tee "$evidence/submit-status.txt"
cat "$evidence/submit.json"; echo
case "$status" in 201|202) ;; *) fail "GP submission returned HTTP $status" ;; esac
job_id="$(jq -r '.jobID // .jobId // .id // empty' "$evidence/submit.json")"
[ -n "$job_id" ] || fail "submission returned no job id"

job=""
for _ in $(seq 1 60); do
  job="$(kubectl get jobs -n "$namespace" -o name \
    -l "app.kubernetes.io/managed-by=honua-controlplane,honua.io/operation-id=$(printf '%s' "$job_id" | tr '[:upper:]' '[:lower:]')" | head -1)"
  [ -n "$job" ] && break
  sleep 2
done
[ -n "$job" ] || { kubectl logs -n "$namespace" "deployment/$fullname" > "$evidence/server.log" || true; fail "no Kubernetes Job was created for GP job $job_id"; }
kubectl get "$job" -n "$namespace" -o json > "$evidence/gp-job.json"
jq -e --arg sa "$fullname-gp-job" '.spec.template.spec.serviceAccountName == $sa' "$evidence/gp-job.json" >/dev/null \
  || fail "GP Job does not run as the job service account"
jq -e --arg image "$worker_image" '.spec.template.spec.containers[0].image == $image' "$evidence/gp-job.json" >/dev/null \
  || fail "GP Job does not run the selected worker image"
jq -e '.spec.backoffLimit == 0 and .spec.ttlSecondsAfterFinished == 600' "$evidence/gp-job.json" >/dev/null \
  || fail "GP Job does not carry the backend's backoff/TTL"
jq -e '.metadata.labels["honua.io/workload-kind"] == "geoprocessing" and (.metadata.labels["honua.io/operation-id"] | length > 0)' \
  "$evidence/gp-job.json" >/dev/null || fail "GP Job lacks the operation labels"
# The worker imports the scoped worker Secret and ConfigMap by name (honua-helm#110); no
# credential value is written into the Job, and the worker Secret has no admin password.
jq -e --arg worker "$fullname-gp-worker-env" \
  '[.spec.template.spec.containers[0].envFrom[]? | (.secretRef.name // empty)] == [$worker]
   and [.spec.template.spec.containers[0].envFrom[]? | (.configMapRef.name // empty)] == [$worker]
   and ([.spec.template.spec.containers[0].env[]? | select(.name | test("ConnectionStrings|MasterKey|PASSWORD"))] | length) == 0' \
  "$evidence/gp-job.json" >/dev/null || fail "GP Job does not import the scoped worker Secret and ConfigMap through envFrom"
kubectl get secret "$fullname-gp-worker-env" -n "$namespace" -o json \
  | jq -e '(.data | has("HONUA_ADMIN_PASSWORD") | not) and (.data | has("ConnectionStrings__DefaultConnection"))
           and (.data | has("GP_SMOKE_KEYRING_PFX"))' >/dev/null \
  || fail "the GP worker Secret is not scoped to the worker credentials"
jq -r '[.spec.template.spec.containers[0].env[].name | select(startswith("HONUA_"))] | join(",")' "$evidence/gp-job.json" \
  | tee "$evidence/launch-variables.txt"
# The worker launch contract (HONUA_OPERATION_ID, HONUA_EXECUTION_ATTEMPT, ...) is stamped by
# server images that carry honua-server#5780; older images stamp only HONUA_CONTRACT_VERSION and
# their Job boots a full server instead of a single-job worker.
grep -q 'HONUA_OPERATION_ID' "$evidence/launch-variables.txt" || fail "GP Job lacks HONUA_OPERATION_ID"
grep -q 'HONUA_EXECUTION_ATTEMPT' "$evidence/launch-variables.txt" || fail "GP Job lacks HONUA_EXECUTION_ATTEMPT"
echo "GP job $job_id dispatched as $job" | tee "$evidence/dispatch.txt"

# Completion and output semantics are required for every supported image.
outcome="not-observed"
for _ in $(seq 1 90); do
  state="$(kubectl get "$job" -n "$namespace" -o jsonpath='{.status.succeeded}/{.status.failed}')"
  case "$state" in 1/*) outcome="job-succeeded"; break ;; */1) outcome="job-failed"; break ;; esac
  sleep 2
done
kubectl logs -n "$namespace" "$job" --tail=200 > "$evidence/worker.log" 2>&1 || true
status="$(curl -sS -o "$evidence/gp-job-status.json" -w '%{http_code}' \
  -H "Host: $fullname" -H "X-API-Key: $admin_password" \
  "http://127.0.0.1:$port/ogc/processes/jobs/$job_id")"
[ "$status" = 200 ] || fail "job status returned HTTP $status"
echo "worker outcome: $outcome; GP status: $(jq -r '.status // empty' "$evidence/gp-job-status.json")" \
  | tee "$evidence/completion.txt"
[ "$outcome" = "job-succeeded" ] || fail "worker Job did not succeed ($outcome)"
jq -e --arg id "$job_id" '.status == "successful" and .jobID == $id' \
  "$evidence/gp-job-status.json" >/dev/null || fail "GP job did not report successful for the submitted job"
kubectl get pods -n "$namespace" -l "job-name=${job#*/}" -o json > "$evidence/worker-pods.json"
jq -e '.items | length > 0 and all(.[]; .status.phase == "Succeeded" and
  all(.status.containerStatuses[]; .state.terminated.exitCode == 0))' \
  "$evidence/worker-pods.json" >/dev/null || fail "worker containers did not exit successfully"
status="$(curl -sS -o "$evidence/gp-results.json" -w '%{http_code}' \
  -H "Host: $fullname" -H "X-API-Key: $admin_password" \
  "http://127.0.0.1:$port/ogc/processes/jobs/$job_id/results")"
[ "$status" = 200 ] || fail "results returned HTTP $status"
if [ "$runtime_profile" = native ]; then
  python3 scripts/validate-gp-native.py "$evidence/gp-results.json" | tee "$evidence/geometry-oracle.json"
else
  python3 scripts/validate-gp-buffer.py "$evidence/gp-results.json" | tee "$evidence/geometry-oracle.json"
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
