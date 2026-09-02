{{- define "honua.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "honua.appVersion" -}}
{{- $releaseValues := .Values.release | default dict -}}
{{- default .Chart.AppVersion (get $releaseValues "appVersion") -}}
{{- end -}}

{{- define "honua.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "honua.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "honua.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ include "honua.appVersion" . | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "honua.releaseLabels" -}}
{{- with .Values.release.id }}
honua.io/release-id: {{ . | quote }}
{{- end }}
{{- end -}}

{{- define "honua.imageReference" -}}
{{- $imageValues := .Values.image | default dict -}}
{{- $repository := required "image.repository is required." (get $imageValues "repository") -}}
{{- $digest := trim (default "" (get $imageValues "digest")) -}}
{{- $tag := trim (default "" (get $imageValues "tag")) -}}
{{- if $digest -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else -}}
{{- printf "%s:%s" $repository (required "image.tag is required when image.digest is empty." $tag) -}}
{{- end -}}
{{- end -}}

{{- define "honua.imageRegistryHost" -}}
{{- $repository := required "image.repository is required." .Values.image.repository -}}
{{- $firstPart := first (splitList "/" $repository) -}}
{{- if or (contains "." $firstPart) (contains ":" $firstPart) (eq $firstPart "localhost") -}}
{{- $firstPart -}}
{{- else -}}
registry-1.docker.io
{{- end -}}
{{- end -}}

{{- define "honua.releaseAnnotations" -}}
honua.io/image-reference: {{ include "honua.imageReference" . | quote }}
honua.io/chart-version: {{ .Chart.Version | quote }}
honua.io/app-version: {{ include "honua.appVersion" . | quote }}
{{- with .Values.image.digest }}
honua.io/image-digest: {{ . | quote }}
{{- end }}
{{- with .Values.release.id }}
honua.io/release-id: {{ . | quote }}
{{- end }}
{{- with .Values.release.manifest }}
honua.io/release-manifest: {{ . | quote }}
{{- end }}
{{- with .Values.release.digest }}
honua.io/release-digest: {{ . | quote }}
{{- end }}
{{- end -}}

{{- define "honua.selectorLabels" -}}
app.kubernetes.io/name: {{ include "honua.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "honua.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "honua.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "honua.configmapName" -}}
{{- if .Values.config.name -}}
{{- .Values.config.name -}}
{{- else -}}
{{- printf "%s-config" (include "honua.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "honua.secretName" -}}
{{- if .Values.secret.name -}}
{{- .Values.secret.name -}}
{{- else -}}
{{- printf "%s-secret" (include "honua.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "honua.preflightSecretName" -}}
{{- printf "%s-preflight" (include "honua.fullname" .) -}}
{{- end -}}

{{- define "honua.runtimeEnvironment" -}}
{{- $configValues := .Values.config | default dict -}}
{{- $configEnv := get $configValues "env" | default dict -}}
{{- default "Production" (get $configEnv "ASPNETCORE_ENVIRONMENT") -}}
{{- end -}}

{{- define "honua.requiresRedisConnection" -}}
{{- $mode := lower (trim (default "SingleInstance" (get (.Values.config.env | default dict) "Deployment__Mode"))) -}}
{{- if or .Values.redis.enabled (eq $mode "multinode") -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{- define "honua.usesChartManagedPostgresqlConnection" -}}
{{- $secretValues := .Values.secret | default dict -}}
{{- $secretEnv := get $secretValues "env" | default dict -}}
{{- $conn := trim (default "" (get $secretEnv "ConnectionStrings__DefaultConnection")) -}}
{{- if and .Values.postgresql.enabled .Values.secret.create (not $conn) -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{- define "honua.usesChartManagedRedisConnection" -}}
{{- $secretValues := .Values.secret | default dict -}}
{{- $secretEnv := get $secretValues "env" | default dict -}}
{{- $conn := trim (default "" (get $secretEnv "ConnectionStrings__redis")) -}}
{{- if and .Values.redis.enabled .Values.secret.create (not $conn) -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{- define "honua.preflightDatabaseCheck" -}}
{{- if and .Release.IsInstall (eq (include "honua.usesChartManagedPostgresqlConnection" .) "true") -}}
false
{{- else -}}
true
{{- end -}}
{{- end -}}

{{- define "honua.preflightRedisRequired" -}}
{{- include "honua.requiresRedisConnection" . -}}
{{- end -}}

{{- define "honua.preflightRedisCheck" -}}
{{- if and .Release.IsInstall .Values.redis.enabled -}}
false
{{- else -}}
true
{{- end -}}
{{- end -}}

{{- define "honua.releaseInfoConfigMapName" -}}
{{- printf "%s-release-info" (include "honua.fullname" .) -}}
{{- end -}}

{{- /* Minimum credential lengths, defined once so the render-time validation
       layer has a single source of truth for the thresholds. The preflight Job
       (templates/preflight-job.yaml) enforces the same minimums at install time
       for externally-managed secrets the chart cannot see at render time; keep
       the two in sync. */ -}}
{{- define "honua.minAdminPasswordLength" -}}16{{- end -}}
{{- define "honua.minMasterKeyLength" -}}32{{- end -}}

{{- /* Copy non-empty, non-nil string values from the "src" env dict into the
       "dst" dict, then render nothing. Helm passes dicts by reference, so this
       mutates dst in place. Shared by configmap.yaml and honua.secretData so the
       empty-stripping rule is defined once. */ -}}
{{- define "honua.nonEmptyEnv" -}}
{{- $src := .src | default dict -}}
{{- $dst := .dst -}}
{{- range $key, $value := $src }}
{{- if and (ne (toString $value) "") (ne (toString $value) "<nil>") }}
{{- $_ := set $dst $key (toString $value) }}
{{- end }}
{{- end }}
{{- end -}}

{{- /* Authoritative complexity/length policy for chart-managed secret
       credentials. Invoked from templates/validations.yaml (the validation
       layer) rather than from Secret rendering, so the policy is no longer
       welded to honua.secretData. Only runs for values the chart can see
       (secret.create=true); externally-managed secrets are validated at install
       time by the preflight Job. */ -}}
{{- define "honua.validateSecretComplexity" -}}
{{- $minPassword := int (include "honua.minAdminPasswordLength" .) -}}
{{- $minMasterKey := int (include "honua.minMasterKeyLength" .) -}}
{{- $secretEnv := get (.Values.secret | default dict) "env" | default dict -}}
{{- $adminPassword := toString (default "" (get $secretEnv "HONUA_ADMIN_PASSWORD")) -}}
{{- if $adminPassword -}}
{{- if lt (len $adminPassword) $minPassword -}}
{{- fail (printf "secret.env.HONUA_ADMIN_PASSWORD must be at least %d characters long." $minPassword) -}}
{{- end -}}
{{- if not (regexMatch "[A-Z]" $adminPassword) -}}
{{- fail "secret.env.HONUA_ADMIN_PASSWORD must contain at least one uppercase letter." -}}
{{- end -}}
{{- if not (regexMatch "[a-z]" $adminPassword) -}}
{{- fail "secret.env.HONUA_ADMIN_PASSWORD must contain at least one lowercase letter." -}}
{{- end -}}
{{- if not (regexMatch "[0-9]" $adminPassword) -}}
{{- fail "secret.env.HONUA_ADMIN_PASSWORD must contain at least one digit." -}}
{{- end -}}
{{- if not (regexMatch "[^A-Za-z0-9]" $adminPassword) -}}
{{- fail "secret.env.HONUA_ADMIN_PASSWORD must contain at least one special character." -}}
{{- end -}}
{{- end -}}
{{- $masterKey := toString (default "" (get $secretEnv "Security__ConnectionEncryption__MasterKey")) -}}
{{- if and $masterKey (lt (len $masterKey) $minMasterKey) -}}
{{- fail (printf "secret.env.Security__ConnectionEncryption__MasterKey must be at least %d characters long." $minMasterKey) -}}
{{- end -}}
{{- end -}}

{{- define "honua.secretData" -}}
{{- $data := dict -}}
{{- include "honua.nonEmptyEnv" (dict "src" .Values.secret.env "dst" $data) -}}
{{- if and (not (hasKey $data "ConnectionStrings__DefaultConnection")) .Values.postgresql.enabled }}
{{- $pgHost := include "honua.postgresqlHost" . }}
{{- $pgPort := include "honua.postgresqlPort" . }}
{{- $pgUser := required "postgresql.auth.username is required when postgresql.enabled is true and secret.env.ConnectionStrings__DefaultConnection is not set." .Values.postgresql.auth.username }}
{{- $pgPassword := required "postgresql.auth.password is required when postgresql.enabled is true and secret.env.ConnectionStrings__DefaultConnection is not set." .Values.postgresql.auth.password }}
{{- $pgDatabase := required "postgresql.auth.database is required when postgresql.enabled is true and secret.env.ConnectionStrings__DefaultConnection is not set." .Values.postgresql.auth.database }}
{{- $pgConn := printf "Host=%s;Port=%s;Database=%s;Username=%s;Password=%s" $pgHost $pgPort $pgDatabase $pgUser $pgPassword }}
{{- $_ := set $data "ConnectionStrings__DefaultConnection" $pgConn }}
{{- else if not (hasKey $data "ConnectionStrings__DefaultConnection") }}
{{- required "secret.env.ConnectionStrings__DefaultConnection is required when postgresql.enabled is false. Set it to your PostgreSQL connection string." .Values.secret.env.ConnectionStrings__DefaultConnection }}
{{- end }}
{{- if and (not (hasKey $data "ConnectionStrings__redis")) .Values.redis.enabled }}
{{- $redisHost := include "honua.redisHost" . }}
{{- $redisPort := include "honua.redisPort" . }}
{{- if not .Values.redis.auth.enabled }}
{{- fail "redis.auth.enabled must be true when redis.enabled is true unless secret.env.ConnectionStrings__redis is explicitly provided." }}
{{- end }}
{{- $redisPassword := required "redis.auth.password is required when redis.enabled and redis.auth.enabled are true and secret.env.ConnectionStrings__redis is not set." .Values.redis.auth.password }}
{{- $_ := set $data "ConnectionStrings__redis" (printf "%s:%s,password=%s" $redisHost $redisPort $redisPassword) }}
{{- else if and (not (hasKey $data "ConnectionStrings__redis")) (eq (include "honua.requiresRedisConnection" .) "true") }}
{{- required "secret.env.ConnectionStrings__redis is required for non-development Honua deployments unless redis.enabled derives the connection string." .Values.secret.env.ConnectionStrings__redis }}
{{- end }}
{{- if not (hasKey $data "HONUA_ADMIN_PASSWORD") }}
{{- required "secret.env.HONUA_ADMIN_PASSWORD is required. Set it to a strong admin password." .Values.secret.env.HONUA_ADMIN_PASSWORD }}
{{- end }}
{{- if not (hasKey $data "Security__ConnectionEncryption__MasterKey") }}
{{- required "secret.env.Security__ConnectionEncryption__MasterKey is required. Set it to a secure random string of at least 32 characters." .Values.secret.env.Security__ConnectionEncryption__MasterKey }}
{{- end }}
{{- /* Credential complexity/length policy lives in honua.validateSecretComplexity
       and is enforced from templates/validations.yaml; this helper only resolves
       and renders the Secret payload. */ -}}
{{- range $key := keys $data | sortAlpha }}
{{ $key }}: {{ get $data $key | toString | b64enc }}
{{- end }}
{{- end -}}

{{- define "honua.dependencyFullname" -}}
{{- $chartName := .chartName -}}
{{- $chartValues := default dict .chartValues -}}
{{- $context := .context -}}
{{- if $chartValues.fullnameOverride -}}
{{- $chartValues.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default $chartName $chartValues.nameOverride -}}
{{- if contains $name $context.Release.Name -}}
{{- $context.Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" $context.Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "honua.postgresqlHost" -}}
{{- include "honua.dependencyFullname" (dict "chartName" "postgresql" "chartValues" .Values.postgresql "context" .) -}}
{{- end -}}

{{- define "honua.postgresqlPort" -}}
{{- $postgresqlValues := .Values.postgresql | default dict -}}
{{- $globalValues := get $postgresqlValues "global" | default dict -}}
{{- $globalPostgresqlValues := get $globalValues "postgresql" | default dict -}}
{{- $globalServiceValues := get $globalPostgresqlValues "service" | default dict -}}
{{- $globalPortsValues := get $globalServiceValues "ports" | default dict -}}
{{- $globalPort := get $globalPortsValues "postgresql" -}}
{{- if $globalPort -}}
{{- $globalPort -}}
{{- else -}}
{{- $primaryValues := get $postgresqlValues "primary" | default dict -}}
{{- $primaryServiceValues := get $primaryValues "service" | default dict -}}
{{- $primaryPortsValues := get $primaryServiceValues "ports" | default dict -}}
{{- default 5432 (get $primaryPortsValues "postgresql") -}}
{{- end -}}
{{- end -}}

{{- define "honua.redisHost" -}}
{{- printf "%s-redis" (include "honua.fullname" .) -}}
{{- end -}}

{{- define "honua.redisPort" -}}
6379
{{- end -}}
