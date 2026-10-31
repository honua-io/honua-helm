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

{{- /* repository + optional digest. A digest wins over the tag so a moving tag cannot
       change the bytes. Pass digest as "" to force the tag (airgap overrides). */ -}}
{{- define "honua.referencedImage" -}}
{{- $repository := required "image repository is required." .repository -}}
{{- $digest := trim (default "" .digest) -}}
{{- $tag := trim (default "" .tag) -}}
{{- if $digest -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else -}}
{{- printf "%s:%s" $repository (required "image tag is required when digest is empty." $tag) -}}
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

{{- /* Whether the application Service should require app.kubernetes.io/component=server.
       Fresh installs and client-side renders do: lookup does not see a live
       Deployment, and new pods are created with the label. On upgrade, Helm
       applies Services before Deployments. If the live pod template does not
       already have the label, keep the previous selector for this upgrade so
       existing server pods stay selected; the Deployment template still gains
       the label. The following upgrade sees the label and narrows the selector. */ -}}
{{- define "honua.applicationServiceSelectsServerComponent" -}}
{{- $select := true -}}
{{- if .Release.IsUpgrade -}}
{{- $deploy := lookup "apps/v1" "Deployment" .Release.Namespace (include "honua.fullname" .) -}}
{{- if $deploy -}}
{{- $liveLabels := dig "spec" "template" "metadata" "labels" dict $deploy -}}
{{- $component := "" -}}
{{- if hasKey $liveLabels "app.kubernetes.io/component" -}}
{{- $component = index $liveLabels "app.kubernetes.io/component" -}}
{{- end -}}
{{- if ne (toString $component) "server" -}}
{{- $select = false -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if $select }}true{{ else }}false{{ end -}}
{{- end -}}

{{- /* PDB spec.selector is immutable. New releases select only server pods so
       preflight Jobs and chart-managed Redis/PostGIS are not disruption-budgeted.
       An existing PDB keeps the selector it already has. */ -}}
{{- define "honua.pdbSelectsServerComponent" -}}
{{- $live := lookup "policy/v1" "PodDisruptionBudget" .Release.Namespace (include "honua.fullname" .) -}}
{{- if and .Release.IsUpgrade $live -}}
{{- $labels := dig "spec" "selector" "matchLabels" dict $live -}}
{{- $component := "" -}}
{{- if hasKey $labels "app.kubernetes.io/component" -}}
{{- $component = index $labels "app.kubernetes.io/component" -}}
{{- end -}}
{{- if eq (toString $component) "server" -}}
true
{{- else -}}
false
{{- end -}}
{{- else -}}
{{- include "honua.applicationServiceSelectsServerComponent" . -}}
{{- end -}}
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
{{- if or .Values.redis.enabled (eq $mode "multinode") (eq (include "honua.gpJobs.enabled" .) "true") -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{- define "honua.usesChartManagedPostgresqlConnection" -}}
{{- $secretValues := .Values.secret | default dict -}}
{{- $secretEnv := get $secretValues "env" | default dict -}}
{{- $conn := trim (default "" (get $secretEnv "ConnectionStrings__DefaultConnection")) -}}
{{- $postgis := .Values.postgis | default dict -}}
{{- $managed := or .Values.postgresql.enabled (dig "enabled" false $postgis) -}}
{{- if and $managed .Values.secret.create (not $conn) -}}
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

{{- define "honua.managedDatabaseHost" -}}
{{- $postgis := .Values.postgis | default dict -}}
{{- if dig "enabled" false $postgis -}}
{{- include "honua.postgisHost" . -}}
{{- else if .Values.postgresql.enabled -}}
{{- include "honua.postgresqlHost" . -}}
{{- end -}}
{{- end -}}

{{- define "honua.preflightDatabaseCheck" -}}
{{- $managed := eq (include "honua.usesChartManagedPostgresqlConnection" .) "true" -}}
{{- $postgis := .Values.postgis | default dict -}}
{{- $postgisOn := dig "enabled" false $postgis -}}
{{- $host := include "honua.managedDatabaseHost" . -}}
{{- /* Bitnami upgrades keep the existing check: that Service is already there.
       PostGIS skips until lookup sees the new Service, including the upgrade
       that first replaces Bitnami. helm template has no cluster, so that
       upgrade render skips; a live upgrade with the Service present checks. */ -}}
{{- if and $managed (or .Release.IsInstall (and $postgisOn (not (lookup "v1" "Service" .Release.Namespace $host)))) -}}
false
{{- else -}}
true
{{- end -}}
{{- end -}}

{{- define "honua.preflightRedisRequired" -}}
{{- include "honua.requiresRedisConnection" . -}}
{{- end -}}

{{- define "honua.preflightRedisCheck" -}}
{{- $managed := eq (include "honua.usesChartManagedRedisConnection" .) "true" -}}
{{- if and $managed (or .Release.IsInstall (not (lookup "v1" "Service" .Release.Namespace (include "honua.redisHost" .)))) -}}
false
{{- else -}}
true
{{- end -}}
{{- end -}}

{{- define "honua.releaseInfoConfigMapName" -}}
{{- printf "%s-release-info" (include "honua.fullname" .) -}}
{{- end -}}

{{- define "honua.deployTargetConfigMapName" -}}
{{- printf "%s-deploy-target" (include "honua.fullname" .) -}}
{{- end -}}

{{- define "honua.deployTargetId" -}}
{{- $deployTarget := get (.Values.controlPlane | default dict) "deployTarget" | default dict -}}
{{- default (include "honua.fullname" .) (trim (default "" (get $deployTarget "targetId"))) -}}
{{- end -}}

{{- define "honua.deployTargetName" -}}
{{- $deployTarget := get (.Values.controlPlane | default dict) "deployTarget" | default dict -}}
{{- default (include "honua.fullname" .) (trim (default "" (get $deployTarget "targetName"))) -}}
{{- end -}}

{{- define "honua.deployTargetEnvironment" -}}
{{- $deployTarget := get (.Values.controlPlane | default dict) "deployTarget" | default dict -}}
{{- default (include "honua.runtimeEnvironment" .) (trim (default "" (get $deployTarget "environment"))) -}}
{{- end -}}

{{- define "honua.deployTargetBackend" -}}
{{- $deployTarget := get (.Values.controlPlane | default dict) "deployTarget" | default dict -}}
{{- default "honua-gitops-kubernetes" (trim (default "" (get $deployTarget "backend"))) -}}
{{- end -}}

{{- define "honua.deployTargetArtifactReference" -}}
{{- $deployTarget := get (.Values.controlPlane | default dict) "deployTarget" | default dict -}}
{{- default (include "honua.imageReference" .) (trim (default "" (get $deployTarget "artifactReference"))) -}}
{{- end -}}

{{- /* controlPlane.telemetryConnections as a list (empty when unset). */ -}}
{{- define "honua.telemetryConnections" -}}
{{- toJson ((get (.Values.controlPlane | default dict) "telemetryConnections") | default list) -}}
{{- end -}}

{{- /* The deploy-target ConfigMap carries both the chart's deploy target
       registration and any chart-declared ControlPlane:TelemetryConnections, so
       it renders when either is in use. */ -}}
{{- define "honua.controlPlaneConfigMap.enabled" -}}
{{- $connections := include "honua.telemetryConnections" . | fromJsonArray -}}
{{- if or .Values.controlPlane.deployTarget.enabled (gt (len $connections) 0) -}}true{{- end -}}
{{- end -}}

{{- /* Deploy target parameters rendered as
       ControlPlane:DeployTargets:0:ParameterEntries (dotted keys such as
       telemetry.connection cannot be environment variable names).
       telemetry.connection comes first, then controlPlane.deployTarget.telemetry.parameters
       in key order. Returns a JSON list of {key, value}. */ -}}
{{- define "honua.deployTargetParameterEntries" -}}
{{- $deployTarget := get (.Values.controlPlane | default dict) "deployTarget" | default dict -}}
{{- $telemetry := get $deployTarget "telemetry" | default dict -}}
{{- $entries := list -}}
{{- $connection := trim (toString (default "" (get $telemetry "connection"))) -}}
{{- if $connection -}}
{{- $entries = append $entries (dict "key" "telemetry.connection" "value" $connection) -}}
{{- end -}}
{{- $parameters := get $telemetry "parameters" | default dict -}}
{{- range $key := keys $parameters | sortAlpha -}}
{{- $entries = append $entries (dict "key" $key "value" (toString (get $parameters $key))) -}}
{{- end -}}
{{- toJson $entries -}}
{{- end -}}

{{- /* Database:MigrationSafety environment rendered from migrationSafety.*.
       Empty strings and a null enforce render nothing, so the server keeps its
       own defaults (ContractApplyPolicy=Gate, Enforce=true, no backup command).
       Returns a JSON object of env name -> value. */ -}}
{{- define "honua.migrationSafetyEnv" -}}
{{- $ms := .Values.migrationSafety | default dict -}}
{{- $env := dict -}}
{{- $policy := trim (toString (default "" (get $ms "contractApplyPolicy"))) -}}
{{- if $policy -}}
{{- $_ := set $env "Database__MigrationSafety__ContractApplyPolicy" $policy -}}
{{- end -}}
{{- $backup := trim (toString (default "" (get $ms "backupCommand"))) -}}
{{- if $backup -}}
{{- $_ := set $env "Database__MigrationSafety__BackupCommand" $backup -}}
{{- end -}}
{{- $enforce := get $ms "enforce" -}}
{{- if kindIs "bool" $enforce -}}
{{- $_ := set $env "Database__MigrationSafety__Enforce" (toString $enforce) -}}
{{- end -}}
{{- toJson $env -}}
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
{{- /* A cloud secret reference is validated by the server once resolved. */ -}}
{{- if and $adminPassword (ne (include "honua.isSecretReference" $adminPassword) "true") -}}
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
{{- if and $masterKey (ne (include "honua.isSecretReference" $masterKey) "true") (lt (len $masterKey) $minMasterKey) -}}
{{- fail (printf "secret.env.Security__ConnectionEncryption__MasterKey must be at least %d characters long." $minMasterKey) -}}
{{- end -}}
{{- end -}}

{{- define "honua.secretData" -}}
{{- $data := dict -}}
{{- include "honua.nonEmptyEnv" (dict "src" .Values.secret.env "dst" $data) -}}
{{- $postgis := .Values.postgis | default dict -}}
{{- if and (not (hasKey $data "ConnectionStrings__DefaultConnection")) (dig "enabled" false $postgis) }}
{{- $pgUser := required "postgis.auth.username is required when postgis.enabled is true and secret.env.ConnectionStrings__DefaultConnection is not set." (dig "auth" "username" "" $postgis) }}
{{- $pgDatabase := required "postgis.auth.database is required when postgis.enabled is true and secret.env.ConnectionStrings__DefaultConnection is not set." (dig "auth" "database" "" $postgis) }}
{{- $pgPassword := include "honua.postgisPassword" . }}
{{- $pgConn := printf "Host=%s;Port=%s;Database=%s;Username=%s;Password=%s" (include "honua.postgisHost" .) (include "honua.postgisPort" .) $pgDatabase $pgUser $pgPassword }}
{{- $_ := set $data "ConnectionStrings__DefaultConnection" $pgConn }}
{{- else if and (not (hasKey $data "ConnectionStrings__DefaultConnection")) .Values.postgresql.enabled }}
{{- $pgHost := include "honua.postgresqlHost" . }}
{{- $pgPort := include "honua.postgresqlPort" . }}
{{- $pgUser := required "postgresql.auth.username is required when postgresql.enabled is true and secret.env.ConnectionStrings__DefaultConnection is not set." .Values.postgresql.auth.username }}
{{- $pgPassword := required "postgresql.auth.password is required when postgresql.enabled is true and secret.env.ConnectionStrings__DefaultConnection is not set." .Values.postgresql.auth.password }}
{{- $pgDatabase := required "postgresql.auth.database is required when postgresql.enabled is true and secret.env.ConnectionStrings__DefaultConnection is not set." .Values.postgresql.auth.database }}
{{- $pgConn := printf "Host=%s;Port=%s;Database=%s;Username=%s;Password=%s" $pgHost $pgPort $pgDatabase $pgUser $pgPassword }}
{{- $_ := set $data "ConnectionStrings__DefaultConnection" $pgConn }}
{{- else if not (hasKey $data "ConnectionStrings__DefaultConnection") }}
{{- required "secret.env.ConnectionStrings__DefaultConnection is required when postgresql.enabled and postgis.enabled are false. Set it to your PostgreSQL connection string." .Values.secret.env.ConnectionStrings__DefaultConnection }}
{{- end }}
{{- if and (not (hasKey $data "ConnectionStrings__redis")) .Values.redis.enabled }}
{{- $redisHost := include "honua.redisHost" . }}
{{- $redisPort := include "honua.redisPort" . }}
{{- if not .Values.redis.auth.enabled }}
{{- fail "redis.auth.enabled must be true when redis.enabled is true unless secret.env.ConnectionStrings__redis is explicitly provided." }}
{{- end }}
{{- $redisPassword := include "honua.redisPassword" . }}
{{- $_ := set $data "ConnectionStrings__redis" (printf "%s:%s,password=%s" $redisHost $redisPort $redisPassword) }}
{{- else if and (not (hasKey $data "ConnectionStrings__redis")) (eq (include "honua.requiresRedisConnection" .) "true") }}
{{- required "secret.env.ConnectionStrings__redis is required for non-development Honua deployments unless redis.enabled derives the connection string." .Values.secret.env.ConnectionStrings__redis }}
{{- end }}
{{- if not (hasKey $data "HONUA_ADMIN_PASSWORD") }}
{{- $_ := set $data "HONUA_ADMIN_PASSWORD" (include "honua.adminPassword" .) }}
{{- end }}
{{- if not (hasKey $data "Security__ConnectionEncryption__MasterKey") }}
{{- $_ := set $data "Security__ConnectionEncryption__MasterKey" (include "honua.masterKey" .) }}
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
{{- printf "%s-redis" (include "honua.fullname" . | trunc 57 | trimSuffix "-") -}}
{{- end -}}

{{- define "honua.redisPort" -}}
6379
{{- end -}}

{{- /* Stable for one render. Reused from the live Secret on upgrade so a
       generated credential is not rotated by a later helm upgrade. */ -}}
{{- define "honua.lookupSecretKey" -}}
{{- $existing := lookup "v1" "Secret" .namespace .name -}}
{{- if and $existing $existing.data (hasKey $existing.data .key) -}}
{{- index $existing.data .key | b64dec -}}
{{- end -}}
{{- end -}}

{{- define "honua.adminPassword" -}}
{{- if not (hasKey .Values "_honuaResolved") -}}
{{- $_ := set .Values "_honuaResolved" dict -}}
{{- end -}}
{{- if hasKey (index .Values "_honuaResolved") "adminPassword" -}}
{{- index (index .Values "_honuaResolved") "adminPassword" -}}
{{- else -}}
{{- $value := toString (default "" (get (.Values.secret.env | default dict) "HONUA_ADMIN_PASSWORD")) -}}
{{- if not $value -}}
{{- if not .Values.secret.generateCredentials -}}
{{- fail "secret.env.HONUA_ADMIN_PASSWORD is required. Set it to a strong admin password, or set secret.generateCredentials for a development install." -}}
{{- end -}}
{{- $value = include "honua.lookupSecretKey" (dict "namespace" .Release.Namespace "name" (include "honua.secretName" .) "key" "HONUA_ADMIN_PASSWORD") -}}
{{- if not $value -}}
{{- $value = printf "Aa1!%s" (randAlphaNum 24) -}}
{{- end -}}
{{- end -}}
{{- $_ := set (index .Values "_honuaResolved") "adminPassword" $value -}}
{{- $value -}}
{{- end -}}
{{- end -}}

{{- define "honua.masterKey" -}}
{{- if not (hasKey .Values "_honuaResolved") -}}
{{- $_ := set .Values "_honuaResolved" dict -}}
{{- end -}}
{{- if hasKey (index .Values "_honuaResolved") "masterKey" -}}
{{- index (index .Values "_honuaResolved") "masterKey" -}}
{{- else -}}
{{- $value := toString (default "" (get (.Values.secret.env | default dict) "Security__ConnectionEncryption__MasterKey")) -}}
{{- if not $value -}}
{{- if not .Values.secret.generateCredentials -}}
{{- fail "secret.env.Security__ConnectionEncryption__MasterKey is required. Set it to a secure random string of at least 32 characters, or set secret.generateCredentials for a development install." -}}
{{- end -}}
{{- $value = include "honua.lookupSecretKey" (dict "namespace" .Release.Namespace "name" (include "honua.secretName" .) "key" "Security__ConnectionEncryption__MasterKey") -}}
{{- if not $value -}}
{{- $value = randAlphaNum 48 -}}
{{- end -}}
{{- end -}}
{{- $_ := set (index .Values "_honuaResolved") "masterKey" $value -}}
{{- $value -}}
{{- end -}}
{{- end -}}

{{- define "honua.redisPassword" -}}
{{- if not (hasKey .Values "_honuaResolved") -}}
{{- $_ := set .Values "_honuaResolved" dict -}}
{{- end -}}
{{- if hasKey (index .Values "_honuaResolved") "redisPassword" -}}
{{- index (index .Values "_honuaResolved") "redisPassword" -}}
{{- else -}}
{{- $value := toString (default "" .Values.redis.auth.password) -}}
{{- if not $value -}}
{{- if not .Values.secret.generateCredentials -}}
{{- fail "redis.auth.password is required when redis.enabled is true unless secret.generateCredentials is true or secret.env.ConnectionStrings__redis is set." -}}
{{- end -}}
{{- $value = include "honua.lookupSecretKey" (dict "namespace" .Release.Namespace "name" (include "honua.redisHost" .) "key" "password") -}}
{{- if not $value -}}
{{- $value = printf "Aa1%s" (randAlphaNum 32) -}}
{{- end -}}
{{- end -}}
{{- $_ := set (index .Values "_honuaResolved") "redisPassword" $value -}}
{{- $value -}}
{{- end -}}
{{- end -}}

{{- define "honua.postgisHost" -}}
{{- printf "%s-postgis" (include "honua.fullname" . | trunc 55 | trimSuffix "-") -}}
{{- end -}}

{{- define "honua.postgisPort" -}}
5432
{{- end -}}

{{- define "honua.postgisPassword" -}}
{{- if not (hasKey .Values "_honuaResolved") -}}
{{- $_ := set .Values "_honuaResolved" dict -}}
{{- end -}}
{{- if hasKey (index .Values "_honuaResolved") "postgisPassword" -}}
{{- index (index .Values "_honuaResolved") "postgisPassword" -}}
{{- else -}}
{{- $postgis := .Values.postgis | default dict -}}
{{- $value := toString (default "" (dig "auth" "password" "" $postgis)) -}}
{{- if not $value -}}
{{- if not .Values.secret.generateCredentials -}}
{{- fail "postgis.auth.password is required when postgis.enabled is true unless secret.generateCredentials is true or secret.env.ConnectionStrings__DefaultConnection is set." -}}
{{- end -}}
{{- $value = include "honua.lookupSecretKey" (dict "namespace" .Release.Namespace "name" (include "honua.postgisHost" .) "key" "password") -}}
{{- if not $value -}}
{{- $value = printf "Aa1%s" (randAlphaNum 32) -}}
{{- end -}}
{{- end -}}
{{- $_ := set (index .Values "_honuaResolved") "postgisPassword" $value -}}
{{- $value -}}
{{- end -}}
{{- end -}}

{{- /* ---------------------------------------------------------------------
       Geoprocessing on Kubernetes Jobs (geoprocessing.kubernetesJobs).
       --------------------------------------------------------------------- */ -}}

{{- define "honua.gpJobs.values" -}}
{{- $gp := get (.Values.geoprocessing | default dict) "kubernetesJobs" | default dict -}}
{{- toJson $gp -}}
{{- end -}}

{{- define "honua.gpJobs.enabled" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- if eq (toString (default false (get $gp "enabled"))) "true" -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- /* A ControlPlane__Kubernetes__<Name> value supplied through config.env
       (for example honua-iac's chart_config_env). The chart keeps its objects
       and the server setting consistent with it when the matching
       geoprocessing.kubernetesJobs value is left empty. */ -}}
{{- define "honua.gpJobs.configEnv" -}}
{{- $configEnv := get (.context.Values.config | default dict) "env" | default dict -}}
{{- trim (toString (default "" (get $configEnv (printf "ControlPlane__Kubernetes__%s" .name)))) -}}
{{- end -}}

{{- define "honua.gpJobs.namespace" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- $fromConfig := include "honua.gpJobs.configEnv" (dict "context" . "name" "DefaultNamespace") -}}
{{- default (default .Release.Namespace $fromConfig) (trim (default "" (get $gp "namespace"))) -}}
{{- end -}}

{{- define "honua.gpJobs.serviceAccountName" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- $sa := get $gp "serviceAccount" | default dict -}}
{{- $name := trim (default "" (get $sa "name")) -}}
{{- $fromConfig := include "honua.gpJobs.configEnv" (dict "context" . "name" "DefaultServiceAccount") -}}
{{- if $name -}}
{{- $name -}}
{{- else if $fromConfig -}}
{{- $fromConfig -}}
{{- else -}}
{{- printf "%s-gp-job" (include "honua.fullname" . | trunc 56 | trimSuffix "-") -}}
{{- end -}}
{{- end -}}

{{- define "honua.gpJobs.resourceName" -}}
{{- printf "%s-gp-kubernetes-jobs" (include "honua.fullname" . | trunc 43 | trimSuffix "-") -}}
{{- end -}}

{{- /* Worker image: the chart's server image unless an override is given. */ -}}
{{- define "honua.gpJobs.image" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- $img := get $gp "image" | default dict -}}
{{- $repository := trim (default "" (get $img "repository")) -}}
{{- $tag := trim (default "" (get $img "tag")) -}}
{{- $digest := trim (default "" (get $img "digest")) -}}
{{- $fromConfig := include "honua.gpJobs.configEnv" (dict "context" . "name" "DefaultImage") -}}
{{- if and (not $repository) (not $tag) (not $digest) $fromConfig -}}
{{- $fromConfig -}}
{{- else if and (not $repository) (not $tag) (not $digest) -}}
{{- include "honua.imageReference" . -}}
{{- else -}}
{{- $repository = default .Values.image.repository $repository -}}
{{- if $digest -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else -}}
{{- printf "%s:%s" $repository (required "geoprocessing.kubernetesJobs.image.tag or .digest is required when geoprocessing.kubernetesJobs.image.repository is set." $tag) -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "honua.gpJobs.imagePullPolicy" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- $img := get $gp "image" | default dict -}}
{{- default .Values.image.pullPolicy (trim (default "" (get $img "pullPolicy"))) -}}
{{- end -}}

{{- define "honua.gpJobs.imagePullSecrets" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- $names := list -}}
{{- range (get $gp "imagePullSecrets" | default list) -}}
{{- if kindIs "map" . -}}
{{- $names = append $names (get . "name") -}}
{{- else -}}
{{- $names = append $names (toString .) -}}
{{- end -}}
{{- end -}}
{{- if not $names -}}
{{- range (.Values.image.pullSecrets | default list) -}}
{{- if kindIs "map" . -}}
{{- $names = append $names (get . "name") -}}
{{- else -}}
{{- $names = append $names (toString .) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- toJson $names -}}
{{- end -}}

{{- /* A worker setting is sensitive when it carries a credential. Those may
       only reach a Job as a cloud secret reference: the server writes Job env
       as literal values into the pod spec and the durable job record. */ -}}
{{- define "honua.gpJobs.isSensitiveName" -}}
{{- if or (hasPrefix "ConnectionStrings__" .) (regexMatch "(?i)(password|masterkey|apikey|token|pkcs12|secretkey|privatekey|licensecontent|chainverification__key)" .) -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- define "honua.isSecretReference" -}}
{{- if regexMatch "^(aws:secretsmanager:|azure:keyvault:).+" (trim (toString .)) -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- /* Effective worker environment (name => value) as JSON. Order of
       precedence, lowest first: config.env, licensing values, reference-valued
       (or, with allowInlineWorkerSecrets, all) secret.env entries and the
       chart-derived Redis/PostgreSQL connection strings, then workerEnv. */ -}}
{{- /* envFrom mode (honua-server >= bebaada00, server#5796): the server
       renders ControlPlane:Kubernetes:DefaultEnvFrom{Secrets,ConfigMaps} as
       container envFrom on every Job, so workers read the same Secret and
       ConfigMap the server mounts and the kubelet resolves the values. The
       references must name objects in the Job namespace, so the mode applies
       only when the Jobs run in the release namespace. */ -}}
{{- define "honua.gpJobs.envFromMode" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- $on := eq (toString (ternary true (get $gp "envFromServer") (not (hasKey $gp "envFromServer")))) "true" -}}
{{- if and $on (eq (include "honua.gpJobs.namespace" .) .Release.Namespace) -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- /* Worker environment scope (honua-helm#110). "worker" (the default) gives
       each Job only the settings a worker host needs: the server's
       non-credential configuration plus the database, Redis job store,
       connection-encryption master key, operation key ring, licensing and
       file storage credentials. Server-only credentials (the admin password,
       the audit-chain key, OIDC signing keys, SMTP and API keys) never reach
       a worker, so the job identity need not be able to read them. "server"
       restores the pre-#110 behaviour: the worker imports the server's whole
       runtime Secret, ConfigMap and extraEnvFrom sources. */ -}}
{{- define "honua.gpJobs.scoped" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- if eq (toString (default "worker" (get $gp "environmentScope"))) "server" -}}false{{- else -}}true{{- end -}}
{{- end -}}

{{- define "honua.gpJobs.workerEnvName" -}}
{{- printf "%s-gp-worker-env" (include "honua.fullname" . | trunc 49 | trimSuffix "-") -}}
{{- end -}}

{{- /* workerSecretKeys, plus the target of every env:<NAME> reference a
       worker credential in config.env or secret.env points at, since the
       worker resolves that reference from its own environment. */ -}}
{{- define "honua.gpJobs.workerSecretKeys" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- $keys := list -}}
{{- range (get $gp "workerSecretKeys" | default list) -}}
{{- $keys = append $keys (toString .) -}}
{{- end -}}
{{- $settings := dict -}}
{{- include "honua.nonEmptyEnv" (dict "src" (get (.Values.secret | default dict) "env") "dst" $settings) -}}
{{- include "honua.nonEmptyEnv" (dict "src" (get (.Values.config | default dict) "env") "dst" $settings) -}}
{{- range $key, $value := $settings -}}
{{- if and (hasPrefix "env:" $value) (eq (include "honua.gpJobs.isWorkerCredential" (dict "name" $key "extra" $keys)) "true") -}}
{{- $target := trim (trimPrefix "env:" $value) -}}
{{- if and $target (not (has $target $keys)) -}}
{{- $keys = append $keys $target -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- toJson $keys -}}
{{- end -}}

{{- /* A credential a worker host needs: the database, the Redis job store,
       the connection-encryption master key, the operation key ring,
       licensing, file storage, or a name listed in workerSecretKeys.
       Called with (dict "name" <key> "extra" <workerSecretKeys>). */ -}}
{{- define "honua.gpJobs.isWorkerCredential" -}}
{{- if or (has .name .extra) (regexMatch "^(ConnectionStrings__(DefaultConnection|redis)|(Security__ConnectionEncryption|Operations__SecretChannel|Licensing|FileStorage)__[A-Za-z0-9_.-]+)$" .name) -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- /* A setting that carries or points at a credential: a sensitive name
       (honua.gpJobs.isSensitiveName, plus secret/signing-key/credential
       names) or a cloud secret reference value. Called with
       (dict "name" <key> "value" <value>). */ -}}
{{- define "honua.gpJobs.isCredential" -}}
{{- if or (eq (include "honua.gpJobs.isSensitiveName" .name) "true") (regexMatch "(?i)(secret|signingkey|credential)" .name) (eq (include "honua.isSecretReference" .value) "true") -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- /* Scoped worker ConfigMap data (name => value): the non-empty config.env
       entries, minus the server listener, the control-plane settings and every
       credential a worker does not need. */ -}}
{{- define "honua.gpJobs.workerConfigData" -}}
{{- $extra := include "honua.gpJobs.workerSecretKeys" . | fromJsonArray -}}
{{- $src := dict -}}
{{- $out := dict -}}
{{- if .Values.config.create -}}
{{- include "honua.nonEmptyEnv" (dict "src" .Values.config.env "dst" $src) -}}
{{- end -}}
{{- range $key, $value := $src -}}
{{- $credential := eq (include "honua.gpJobs.isCredential" (dict "name" $key "value" $value)) "true" -}}
{{- $allowed := eq (include "honua.gpJobs.isWorkerCredential" (dict "name" $key "extra" $extra)) "true" -}}
{{- if and (ne $key "ASPNETCORE_URLS") (not (hasPrefix "ControlPlane__" $key)) (or (not $credential) $allowed) -}}
{{- $_ := set $out $key $value -}}
{{- end -}}
{{- end -}}
{{- toJson $out -}}
{{- end -}}

{{- /* Scoped worker Secret data (name => plain value): only the worker
       credentials from the chart-managed runtime Secret, including the
       chart-derived PostgreSQL and Redis connection strings. The runtime
       Secret is the credential store, so this is a strict allowlist. */ -}}
{{- define "honua.gpJobs.workerSecretData" -}}
{{- $extra := include "honua.gpJobs.workerSecretKeys" . | fromJsonArray -}}
{{- $out := dict -}}
{{- if .Values.secret.create -}}
{{- range $line := splitList "\n" (include "honua.secretData" .) -}}
{{- if contains ": " $line -}}
{{- $parts := splitn ": " 2 (trim $line) -}}
{{- if eq (include "honua.gpJobs.isWorkerCredential" (dict "name" $parts._0 "extra" $extra)) "true" -}}
{{- $_ := set $out $parts._0 (b64dec $parts._1) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- toJson $out -}}
{{- end -}}

{{- /* Scoped mode with an existing runtime Secret (secret.create=false): the
       chart cannot read or filter it, so each worker credential is taken by
       key (secretKeyRef) instead of importing the whole Secret: the database,
       Redis and master key, plus workerSecretKeys. A key the worker already
       gets from the scoped ConfigMap or a workerEnv literal is skipped.
       Result: name => "<secret>:<key>". */ -}}
{{- define "honua.gpJobs.workerSecretKeyRefs" -}}
{{- $refs := dict -}}
{{- if and (not .Values.secret.create) .Values.secret.name -}}
{{- $config := include "honua.gpJobs.workerConfigData" . | fromJson -}}
{{- $literals := include "honua.gpJobs.workerEnv" . | fromJson -}}
{{- if .Values.licensing.licenseSecretRef.name -}}
{{- $_ := set $literals "Licensing__LicenseContent" "" -}}
{{- end -}}
{{- $keys := concat (list "ConnectionStrings__DefaultConnection" "ConnectionStrings__redis" "Security__ConnectionEncryption__MasterKey") (include "honua.gpJobs.workerSecretKeys" . | fromJsonArray) -}}
{{- range $key := $keys -}}
{{- if and (not (hasKey $config $key)) (not (hasKey $literals $key)) -}}
{{- $_ := set $refs $key (printf "%s:%s" $.Values.secret.name $key) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- toJson $refs -}}
{{- end -}}

{{- /* "<name>" or "<name>:<prefix>" entries for one envFrom kind
       ("secretRef" or "configMapRef"). With environmentScope=server they are
       the server Deployment's sources, in its order. Scoped, they are the
       chart's worker Secret and ConfigMap (an existing ConfigMap, config.name
       with config.create=false, is imported whole because the chart cannot
       filter it), then each workerExtraEnvFrom source. */ -}}
{{- define "honua.gpJobs.envFromSources" -}}
{{- $kind := .kind -}}
{{- $root := .context -}}
{{- $scoped := eq (include "honua.gpJobs.scoped" $root) "true" -}}
{{- $gp := include "honua.gpJobs.values" $root | fromJson -}}
{{- $names := list -}}
{{- if eq $kind "secretRef" -}}
{{- if and $scoped $root.Values.secret.create -}}
{{- $names = append $names (include "honua.gpJobs.workerEnvName" $root) -}}
{{- else if and (not $scoped) (or $root.Values.secret.create $root.Values.secret.name) -}}
{{- $names = append $names (include "honua.secretName" $root) -}}
{{- end -}}
{{- else -}}
{{- if and $scoped $root.Values.config.create -}}
{{- $names = append $names (include "honua.gpJobs.workerEnvName" $root) -}}
{{- else if or $root.Values.config.create $root.Values.config.name -}}
{{- $names = append $names (include "honua.configmapName" $root) -}}
{{- end -}}
{{- end -}}
{{- $sources := ternary (get $gp "workerExtraEnvFrom" | default list) ($root.Values.extraEnvFrom | default list) $scoped -}}
{{- range $sources -}}
{{- $ref := get . $kind -}}
{{- if and $ref (get $ref "name") -}}
{{- $entry := toString (get $ref "name") -}}
{{- with get . "prefix" -}}{{- $entry = printf "%s:%s" $entry . -}}{{- end -}}
{{- $names = append $names $entry -}}
{{- end -}}
{{- end -}}
{{- toJson $names -}}
{{- end -}}

{{- define "honua.gpJobs.workerEnv" -}}
{{- $gp := include "honua.gpJobs.values" . | fromJson -}}
{{- $allowInline := eq (toString (default false (get $gp "allowInlineWorkerSecrets"))) "true" -}}
{{- $envFromMode := eq (include "honua.gpJobs.envFromMode" .) "true" -}}
{{- $scoped := eq (include "honua.gpJobs.scoped" .) "true" -}}
{{- $extra := include "honua.gpJobs.workerSecretKeys" . | fromJsonArray -}}
{{- $env := dict -}}
{{- if eq (toString (ternary true (get $gp "inheritServerEnvironment") (not (hasKey $gp "inheritServerEnvironment")))) "true" -}}
{{- if $envFromMode -}}
{{- /* The Secret and ConfigMap arrive through envFrom; only the values the
       Deployment sets directly (not through envFrom) are copied. */ -}}
{{- $_ := set $env "Licensing__Mode" (toString .Values.licensing.mode) -}}
{{- with .Values.licensing.edition -}}
{{- $_ := set $env "Licensing__Edition" (toString .) -}}
{{- end -}}
{{- with trim (toString (default "" (dig "otlpEndpoint" "" (.Values.observability | default dict)))) -}}
{{- $_ := set $env "OTEL_EXPORTER_OTLP_ENDPOINT" . -}}
{{- $_ := set $env "OTEL_EXPORTER_OTLP_PROTOCOL" (toString (default "grpc" (dig "otlpProtocol" "grpc" ($.Values.observability | default dict)))) -}}
{{- end -}}
{{- else -}}
{{- if $scoped -}}
{{- $env = include "honua.gpJobs.workerConfigData" . | fromJson -}}
{{- else if .Values.config.create -}}
{{- include "honua.nonEmptyEnv" (dict "src" .Values.config.env "dst" $env) -}}
{{- end -}}
{{- $_ := set $env "Licensing__Mode" (toString .Values.licensing.mode) -}}
{{- with .Values.licensing.edition -}}
{{- $_ := set $env "Licensing__Edition" (toString .) -}}
{{- end -}}
{{- if .Values.secret.create -}}
{{- $secretEnv := dict -}}
{{- if $allowInline -}}
{{- range $line := splitList "\n" (include "honua.secretData" .) -}}
{{- if contains ": " $line -}}
{{- $parts := splitn ": " 2 (trim $line) -}}
{{- $_ := set $secretEnv $parts._0 (b64dec $parts._1) -}}
{{- end -}}
{{- end -}}
{{- else -}}
{{- include "honua.nonEmptyEnv" (dict "src" .Values.secret.env "dst" $secretEnv) -}}
{{- end -}}
{{- range $key, $value := $secretEnv -}}
{{- if and (or $allowInline (eq (include "honua.isSecretReference" $value) "true")) (or (not $scoped) (eq (include "honua.gpJobs.isWorkerCredential" (dict "name" $key "extra" $extra)) "true")) -}}
{{- $_ := set $env $key $value -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- /* The server's listener and its control-plane settings do not apply to a
       worker, which neither serves HTTP nor dispatches jobs. */ -}}
{{- $_ := unset $env "ASPNETCORE_URLS" -}}
{{- range $key := keys $env -}}
{{- if hasPrefix "ControlPlane__" $key -}}
{{- $_ := unset $env $key -}}
{{- end -}}
{{- end -}}
{{- /* An explicit empty workerEnv value clears the variable: it drops an
       inherited literal, and in envFrom mode it renders an empty literal,
       which wins over the same key from envFrom. */ -}}
{{- range $key, $value := (get $gp "workerEnv" | default dict) -}}
{{- if or (eq (toString $value) "") (eq (toString $value) "<nil>") -}}
{{- if $envFromMode -}}
{{- $_ := set $env $key "" -}}
{{- else -}}
{{- $_ := unset $env $key -}}
{{- end -}}
{{- else -}}
{{- $_ := set $env $key (toString $value) -}}
{{- end -}}
{{- end -}}
{{- toJson $env -}}
{{- end -}}
