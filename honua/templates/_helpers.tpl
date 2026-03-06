{{- define "honua.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
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
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
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
