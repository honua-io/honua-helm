#!/usr/bin/env python3
"""Render regressions for the chart hardening options (honua-helm#138).

Covers the optional server NetworkPolicy, the GP Job admission policy, the
digest-pinned stage overlay, the ingress refusal of /metrics in the stage
and prod overlays, and the ServiceMonitor scrape credential (honua-helm#139). The kind smoke (scripts/gp-kubernetes-jobs-smoke.sh) proves
the admission policy against a live API server.
"""
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = 'honua/ci-values/base.yaml'
STAGE = 'honua/values-stage.yaml'
PROD = 'honua/values-prod.yaml'
GP = 'honua/ci-values/gp-kubernetes-jobs.yaml'
PROD_PIN = ('--set', 'image.tag=v0.0.0-aot')


def render(values, *args):
    result = subprocess.run(
        ['helm', 'template', 'honua', './honua', '-n', 'honua', '-f', values, *args],
        cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def refused(values, *args):
    result = subprocess.run(
        ['helm', 'template', 'honua', './honua', '-n', 'honua', '-f', values, *args],
        cwd=ROOT, text=True, capture_output=True)
    assert result.returncode != 0, 'invalid configuration rendered successfully'
    return result.stderr


def of_kind(manifests, kind):
    return [item for item in manifests if item['kind'] == kind]


def egress_ports(policy):
    return {(port['port'], port['protocol'])
            for rule in policy['spec']['egress'] for port in rule.get('ports', [])}


def check_network_policy():
    assert not of_kind(render(BASE), 'NetworkPolicy'), 'NetworkPolicy must be opt-in'

    [policy] = of_kind(render(STAGE, '--set', 'networkPolicy.enabled=true'), 'NetworkPolicy')
    spec = policy['spec']
    assert spec['podSelector']['matchLabels'] == {
        'app.kubernetes.io/name': 'honua',
        'app.kubernetes.io/instance': 'honua',
        'app.kubernetes.io/component': 'server',
    }
    assert spec['policyTypes'] == ['Ingress', 'Egress']
    [ingress] = spec['ingress']
    assert ingress['ports'] == [{'port': 8080, 'protocol': 'TCP'}]
    assert ingress['from'] == [
        {'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'ingress-nginx'}}},
        {'podSelector': {'matchLabels': {'app.kubernetes.io/instance': 'honua'}}},
    ]
    dns = spec['egress'][0]
    assert dns['to'][0]['podSelector'] == {'matchLabels': {'k8s-app': 'kube-dns'}}
    # The stage overlay's collector is http://otel-collector.observability.svc:4317.
    assert egress_ports(policy) == {
        (53, 'UDP'), (53, 'TCP'), (5432, 'TCP'), (443, 'TCP'), (4317, 'TCP')}
    assert 'to' not in spec['egress'][1], 'empty egress.to allows any destination'
    assert spec['egress'][2] == {'ports': [{'port': 4317, 'protocol': 'TCP'}]}, \
        'the OTLP port is its own rule, outside egress.to'

    [narrowed] = of_kind(render(STAGE, '--set', 'networkPolicy.enabled=true',
                                '--set', 'networkPolicy.egress.to[0].ipBlock.cidr=10.0.0.0/16'),
                         'NetworkPolicy')
    assert 'to' not in narrowed['spec']['egress'][2], 'egress.to does not narrow the OTLP port'


def check_network_policy_options():
    def ports(*args):
        [policy] = of_kind(render(BASE, '--set', 'networkPolicy.enabled=true', *args),
                           'NetworkPolicy')
        return egress_ports(policy)

    assert (4317, 'TCP') not in ports(), 'no OTLP endpoint, no collector port'
    assert ports('--set', 'observability.otlpEndpoint=https://collector.example') \
        == {(53, 'UDP'), (53, 'TCP'), (5432, 'TCP'), (443, 'TCP')}, 'https default port is 443'
    assert (80, 'TCP') in ports('--set', 'observability.otlpEndpoint=http://collector.example')
    assert (4318, 'TCP') not in ports(
        '--set', 'observability.otlpEndpoint=http://collector:4318', '--set', 'networkPolicy.egress.otlp=false')

    [narrowed] = of_kind(render(
        BASE, '--set', 'networkPolicy.enabled=true',
        '--set', 'networkPolicy.egress.to[0].ipBlock.cidr=10.0.0.0/16',
        '--set', 'networkPolicy.egress.dns.enabled=false',
        '--set', 'networkPolicy.egress.extraTo[0].ports[0].port=6443'), 'NetworkPolicy')
    rules = narrowed['spec']['egress']
    assert rules[0]['to'] == [{'ipBlock': {'cidr': '10.0.0.0/16'}}]
    assert rules[1] == {'ports': [{'port': 6443}]}
    assert len(rules) == 2, 'dns.enabled=false drops the DNS rule'

    error = refused(BASE, '--set', 'networkPolicy.enabled=true',
                    '--set', 'networkPolicy.ingress.controller=null',
                    '--set', 'networkPolicy.ingress.allowSameRelease=false')
    assert 'needs at least one ingress peer' in error, error


def check_stage_digest_pin():
    [server] = [item for item in of_kind(render(STAGE), 'Deployment')
                if item['metadata']['name'] == 'honua-honua']
    container = server['spec']['template']['spec']['containers'][0]
    assert container['image'].startswith('ghcr.io/honua-io/honua-server@sha256:'), container['image']
    assert container['imagePullPolicy'] == 'IfNotPresent'
    dev = yaml.safe_load((ROOT / 'honua/values-dev.yaml').read_text())['image']['digest']
    assert container['image'].endswith(dev), 'stage pins the development candidate digest'


def check_metrics_refused_at_ingress():
    for values, extra in ((STAGE, ()), (PROD, PROD_PIN)):
        ingresses = of_kind(render(values, *extra), 'Ingress')
        deny = [item for item in ingresses if item['metadata']['name'].endswith('-deny')]
        assert len(ingresses) == 2 and len(deny) == 1, values
        deny = deny[0]
        assert deny['metadata']['annotations'] == {
            'nginx.ingress.kubernetes.io/denylist-source-range': '0.0.0.0/0,::/0'}
        assert deny['spec']['ingressClassName'] == 'nginx'
        [rule] = deny['spec']['rules']
        assert [path['path'] for path in rule['http']['paths']] == ['/metrics']
        assert rule['http']['paths'][0]['pathType'] == 'Prefix'
        main = next(item for item in ingresses if item is not deny)
        assert rule['host'] == main['spec']['rules'][0]['host'], 'deny rule covers the public host'

    assert len(of_kind(render(BASE, '--set', 'ingress.enabled=true'), 'Ingress')) == 1
    error = refused(STAGE, '--set', 'ingress.className=alb')
    assert 'needs ingress.className nginx' in error, error


def check_gp_admission_policy():
    assert not of_kind(render(GP), 'ValidatingAdmissionPolicy'), 'admission policy must be opt-in'
    assert not of_kind(render(BASE, '--set', 'geoprocessing.kubernetesJobs.admissionPolicy.enabled=true'),
                       'ValidatingAdmissionPolicy'), 'no policy without GP Jobs'

    manifests = render(GP, '--set', 'geoprocessing.kubernetesJobs.admissionPolicy.enabled=true',
                       '--set', 'geoprocessing.kubernetesJobs.namespace=honua-gp',
                       '--set', 'geoprocessing.kubernetesJobs.admissionPolicy.extraImages[0]=registry.example/native@sha256:'
                       + 'a' * 64)
    [policy] = of_kind(manifests, 'ValidatingAdmissionPolicy')
    [binding] = of_kind(manifests, 'ValidatingAdmissionPolicyBinding')
    assert binding['spec'] == {'policyName': policy['metadata']['name'], 'validationActions': ['Deny']}
    spec = policy['spec']
    assert spec['failurePolicy'] == 'Fail'
    assert spec['matchConstraints']['namespaceSelector'] == {
        'matchLabels': {'kubernetes.io/metadata.name': 'honua-gp'}}
    [rule] = spec['matchConstraints']['resourceRules']
    assert rule == {'apiGroups': ['batch'], 'apiVersions': ['v1'], 'resources': ['jobs'],
                    'operations': ['CREATE']}
    [condition] = spec['matchConditions']
    assert condition['expression'] == \
        'request.userInfo.username == "system:serviceaccount:honua:honua-honua"'
    expressions = [item['expression'] for item in spec['validations']]
    configmap = next(item for item in of_kind(manifests, 'ConfigMap')
                     if item['metadata']['name'].endswith('-gp-kubernetes-jobs'))
    worker = configmap['data']['ControlPlane__Kubernetes__DefaultImage']
    assert expressions[0] == ('variables.pod.containers.all(c, c.image in ["%s","registry.example/native@sha256:%s"])'
                              % (worker, 'a' * 64)), expressions[0]
    job_sa = configmap['data']['ControlPlane__Kubernetes__DefaultServiceAccount']
    assert expressions[1].endswith('serviceAccountName == "%s"' % job_sa), expressions[1]
    for needle in ('!has(c.command)', 'initContainers', 'hostNetwork', 'hostPath', 'privileged'):
        assert any(needle in expression for expression in expressions), needle


def check_service_monitor_credentials():
    observability = 'honua/ci-values/observability.yaml'
    [monitor] = of_kind(render(observability), 'ServiceMonitor')
    [endpoint] = monitor['spec']['endpoints']
    assert endpoint['authorization'] == {
        'type': 'ApiKey', 'credentials': {'name': 'honua-metrics-scrape', 'key': 'api-key'}}
    error = refused(observability, '--set', 'metrics.serviceMonitor.credentials.secretName=')
    assert 'metrics.serviceMonitor.credentials.secretName' in error, error
    assert not of_kind(render(BASE), 'ServiceMonitor'), 'ServiceMonitor must stay opt-in'


check_network_policy()
check_network_policy_options()
check_stage_digest_pin()
check_metrics_refused_at_ingress()
check_gp_admission_policy()
check_service_monitor_credentials()
print('chart hardening render regressions passed')
