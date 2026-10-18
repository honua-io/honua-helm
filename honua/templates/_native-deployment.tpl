{{- define "honua.validateNativeDeployment" -}}
{{- $n := .Values.controlPlane.deployTarget.native -}}
{{- range $key := list "clusterArn" "apiServer" "caSha256" "clusterUid" "deploymentUid" "serviceUid" "routeUid" "publicUrl" "functionalQueryPath" -}}
{{- if not (trim (get $n $key)) -}}
{{- fail (printf "controlPlane.deployTarget.native.%s requires an observed value before native registration." $key) -}}
{{- end -}}
{{- end -}}
{{- if not .Values.image.digest -}}
{{- fail "Native Deployment registration requires image.digest for an immutable baseline." -}}
{{- end -}}
{{- if ne (include "honua.deployTargetArtifactReference" .) (include "honua.imageReference" .) -}}
{{- fail "Native Deployment artifactReference must equal the chart's rendered immutable image." -}}
{{- end -}}
{{- if not .Values.serviceAccount.automount -}}
{{- fail "Native Deployment registration requires serviceAccount.automount=true for projected credentials." -}}
{{- end -}}
{{- if or (not $n.migrationsReady) (ne (toString (get .Values.config.env "HONUA_SKIP_MIGRATIONS")) "true") (ne .Values.strategy.type "RollingUpdate") -}}
{{- fail "Native Deployment registration requires native.migrationsReady=true, config.env.HONUA_SKIP_MIGRATIONS=true and strategy.type=RollingUpdate; converge a compatible schema before enabling it." -}}
{{- end -}}
{{- if and (not $n.expectedContains) (not $n.expectedSha256) -}}
{{- fail "Native Deployment registration requires expectedContains or expectedSha256 for a functional query." -}}
{{- end -}}
{{- $url := urlParse $n.publicUrl -}}
{{- if or (ne $url.scheme "https") $url.userinfo $url.query $url.fragment (not $url.host) -}}
{{- fail "Native Deployment publicUrl must be HTTPS without user information, query or fragment." -}}
{{- end -}}
{{- $dnsProof := or (eq $n.routeKind "Ingress") $n.loadBalancerArn $n.dnsZoneId $n.dnsRecordName (gt (len $n.publicDnsResolvers) 0) -}}
{{- if $dnsProof -}}
{{- if or (not $n.loadBalancerArn) (not $n.dnsZoneId) (not $n.dnsRecordName) (eq (len $n.publicDnsResolvers) 0) -}}
{{- fail "Native custom-domain/Ingress registration requires loadBalancerArn, dnsZoneId, dnsRecordName and publicDnsResolvers together." -}}
{{- end -}}
{{- $hostname := first (splitList ":" $url.host) | lower | trimSuffix "." -}}
{{- if ne ($n.dnsRecordName | lower | trimSuffix ".") $hostname -}}
{{- fail "Native dnsRecordName must exactly match the publicUrl hostname." -}}
{{- end -}}
{{- $cluster := splitList ":" $n.clusterArn -}}
{{- $lb := splitList ":" $n.loadBalancerArn -}}
{{- if or (ne (index $cluster 1) (index $lb 1)) (ne (index $cluster 3) (index $lb 3)) (ne (index $cluster 4) (index $lb 4)) -}}
{{- fail "Native loadBalancerArn must match clusterArn partition, region and account." -}}
{{- end -}}
{{- end -}}
{{- $api := urlParse $n.apiServer -}}
{{- if or (ne $api.scheme "https") $api.userinfo $api.query $api.fragment (not $api.host) (not (has $api.path (list "" "/"))) -}}
{{- fail "Native Deployment apiServer must be an HTTPS API origin without credentials or path." -}}
{{- end -}}
{{- if or (not (hasPrefix "/" $n.functionalQueryPath)) (hasPrefix "//" $n.functionalQueryPath) (contains "#" $n.functionalQueryPath) (contains ".." $n.functionalQueryPath) (contains "\\" $n.functionalQueryPath) (contains "%" (first (splitList "?" $n.functionalQueryPath))) -}}
{{- fail "Native Deployment functionalQueryPath must stay beneath publicUrl (no fragments, traversal, encoded paths or authority overrides)." -}}
{{- end -}}
{{- if eq $n.routeKind "LoadBalancerService" -}}
{{- if or (ne .Values.service.type "LoadBalancer") (ne $n.routeUid $n.serviceUid) -}}
{{- fail "LoadBalancerService registration requires service.type=LoadBalancer and routeUid equal to serviceUid." -}}
{{- end -}}
{{- $publicPort := "443" -}}
{{- if contains ":" $url.host -}}
{{- $publicPort = last (splitList ":" $url.host) -}}
{{- end -}}
{{- if ne $publicPort (toString .Values.service.port) -}}
{{- fail "LoadBalancerService publicUrl port must match service.port; configure TLS on that listener." -}}
{{- end -}}
{{- else if eq $n.routeKind "Ingress" -}}
{{- if or (not .Values.ingress.enabled) (not $n.routeHost) (not (has $url.host (list $n.routeHost (printf "%s:443" $n.routeHost)))) -}}
{{- fail "Ingress registration requires an enabled chart Ingress and a matching routeHost on HTTPS port 443." -}}
{{- end -}}
{{- $matches := 0 -}}
{{- range .Values.ingress.hosts -}}
{{- if eq .host $n.routeHost -}}
{{- range .paths -}}
{{- if and (eq .path $n.routePath) (eq (default "Prefix" .pathType) "Prefix") -}}
{{- $matches = add1 $matches -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if ne (int $matches) 1 -}}
{{- fail "Native Ingress registration must select exactly one chart-rendered Prefix host/path." -}}
{{- end -}}
{{- $basePath := trimSuffix "/" $url.path -}}
{{- $routePath := trimSuffix "/" $n.routePath -}}
{{- if and (ne $basePath $routePath) (not (hasPrefix (printf "%s/" $routePath) $basePath)) -}}
{{- fail "Native Ingress publicUrl must be beneath the selected routePath." -}}
{{- end -}}
{{- else -}}
{{- fail "Native Deployment routeKind must be LoadBalancerService or Ingress." -}}
{{- end -}}
{{- end -}}

{{- define "honua.nativeDeploymentRbacName" -}}
{{- printf "%s-deploy-%s" (include "honua.fullname" . | trunc 39 | trimSuffix "-") (sha256sum (printf "%s/%s" .Release.Namespace .Release.Name) | trunc 12) -}}
{{- end -}}
