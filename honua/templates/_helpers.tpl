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

{{- define "honua.releaseInfoConfigMapName" -}}
{{- printf "%s-release-info" (include "honua.fullname" .) -}}
{{- end -}}

{{- define "honua.secretData" -}}
{{- $data := dict -}}
{{- range $key, $value := .Values.secret.env }}
{{- if and (ne (toString $value) "") (ne (toString $value) "<nil>") }}
{{- $_ := set $data $key (toString $value) }}
{{- end }}
{{- end }}
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
{{- end }}
{{- if not (hasKey $data "HONUA_ADMIN_PASSWORD") }}
{{- required "secret.env.HONUA_ADMIN_PASSWORD is required. Set it to a strong admin password." .Values.secret.env.HONUA_ADMIN_PASSWORD }}
{{- end }}
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
{{- $redisBase := include "honua.dependencyFullname" (dict "chartName" "redis" "chartValues" .Values.redis "context" .) -}}
{{- $redisValues := .Values.redis | default dict -}}
{{- $redisArchitecture := default "standalone" (get $redisValues "architecture") -}}
{{- $redisSentinelValues := get $redisValues "sentinel" | default dict -}}
{{- $redisSentinelEnabled := default false (get $redisSentinelValues "enabled") -}}
{{- if and (eq $redisArchitecture "replication") $redisSentinelEnabled -}}
{{- $redisBase -}}
{{- else -}}
{{- printf "%s-master" $redisBase -}}
{{- end -}}
{{- end -}}

{{- define "honua.redisPort" -}}
{{- $redisValues := .Values.redis | default dict -}}
{{- $redisArchitecture := default "standalone" (get $redisValues "architecture") -}}
{{- $redisSentinelValues := get $redisValues "sentinel" | default dict -}}
{{- $redisSentinelEnabled := default false (get $redisSentinelValues "enabled") -}}
{{- if and (eq $redisArchitecture "replication") $redisSentinelEnabled -}}
{{- $redisSentinelServiceValues := get $redisSentinelValues "service" | default dict -}}
{{- $redisSentinelPortsValues := get $redisSentinelServiceValues "ports" | default dict -}}
{{- default 6379 (get $redisSentinelPortsValues "redis") -}}
{{- else -}}
{{- $redisMasterValues := get $redisValues "master" | default dict -}}
{{- $redisMasterServiceValues := get $redisMasterValues "service" | default dict -}}
{{- $redisMasterPortsValues := get $redisMasterServiceValues "ports" | default dict -}}
{{- default 6379 (get $redisMasterPortsValues "redis") -}}
{{- end -}}
{{- end -}}
