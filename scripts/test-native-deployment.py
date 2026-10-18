#!/usr/bin/env python3
"""Render native deployment registration, inspect actual RBAC, and reject unsafe inputs."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'ControlPlane__DeployTargets__0__Parameters__'
UID = '12345678-1234-1234-1234-123456789abc'
NATIVE = {
    'image': {'tag': '', 'digest': 'sha256:' + 'a' * 64, 'pullPolicy': 'IfNotPresent'},
    'serviceAccount': {'automount': True},
    'service': {'type': 'LoadBalancer', 'port': 443},
    'strategy': {'type': 'RollingUpdate'},
    'config': {'env': {'HONUA_SKIP_MIGRATIONS': 'true'}},
    'controlPlane': {'deployTarget': {
        'backend': 'honua-kubernetes-deployment',
        'native': {
            'clusterArn': 'arn:aws:eks:us-west-2:123456789012:cluster/evaluator',
            'apiServer': 'https://cluster.example.test', 'caSha256': 'b' * 64,
            'clusterUid': UID, 'deploymentUid': UID, 'serviceUid': UID, 'routeUid': UID,
            'publicUrl': 'https://lb.example.test/honua',
            'functionalQueryPath': '/ogc/features/collections/parcels/items?limit=1',
            'expectedContains': 'FeatureCollection', 'migrationsReady': True,
        },
    }},
}


def render(values, namespace='evaluation', succeeds=True):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as stream:
        json.dump(values, stream)
        stream.flush()
        result = subprocess.run(
            ['helm', 'template', 'honua', './honua', '--namespace', namespace,
             '-f', 'honua/ci-values/base.yaml', '-f', stream.name],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
    if not succeeds:
        assert result.returncode != 0, 'unsafe native registration rendered successfully'
        return result.stderr
    assert result.returncode == 0, result.stderr
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def get(items, kind):
    return next(item for item in items if item['kind'] == kind)


def parameters(items):
    config = next(item for item in items if item['kind'] == 'ConfigMap'
                  and 'ControlPlane__DeployTargets__0__Backend' in item.get('data', {}))
    return {key[len(PREFIX):]: value for key, value in config['data'].items() if key.startswith(PREFIX)}


def refused(path, value, message=None):
    changed = copy.deepcopy(NATIVE)
    target = changed
    keys = path.split('.')
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value
    if path == 'image.digest' and not value:
        changed['image']['tag'] = 'v1.0.0'
    error = render(changed, succeeds=False)
    if message:
        assert message in error, error


manual = render({})
assert not [item for item in manual if item['kind'] in ('Role', 'ClusterRole', 'RoleBinding', 'ClusterRoleBinding')]
assert parameters(manual) == {}
assert get(manual, 'Deployment')['spec']['template']['spec']['automountServiceAccountToken'] is False

native = render(NATIVE)
params = parameters(native)
deployment = get(native, 'Deployment')
service = get(native, 'Service')
assert params['kubernetes.namespace'] == 'evaluation'
assert params['kubernetes.deployment_name'] == deployment['metadata']['name']
assert params['kubernetes.service_name'] == params['kubernetes.route_name'] == service['metadata']['name']
assert params['kubernetes.container_name'] == deployment['spec']['template']['spec']['containers'][0]['name']
assert params['kubernetes.service_port'] == str(service['spec']['ports'][0]['port'])
assert params['kubernetes.target_port'] == str(service['spec']['ports'][0]['targetPort'])
assert params['honua.runtime_kind'] == 'aws-eks'
assert params['telemetry.healthz.url'] == 'https://lb.example.test/honua/healthz/ready'
assert params['telemetry.golden_query.url'] == 'https://lb.example.test/honua/ogc/features/collections/parcels/items?limit=1'
assert get(native, 'ClusterRole')['rules'] == [
    {'apiGroups': [''], 'resources': ['namespaces'], 'resourceNames': ['kube-system'], 'verbs': ['get']}]
rules = get(native, 'Role')['rules']
assert rules == [
    {'apiGroups': ['apps'], 'resources': ['deployments'], 'resourceNames': [deployment['metadata']['name']], 'verbs': ['get', 'patch']},
    {'apiGroups': [''], 'resources': ['services'], 'resourceNames': [service['metadata']['name']], 'verbs': ['get']},
    {'apiGroups': ['apps'], 'resources': ['replicasets'], 'verbs': ['list']},
    {'apiGroups': [''], 'resources': ['pods'], 'verbs': ['list']},
    {'apiGroups': ['discovery.k8s.io'], 'resources': ['endpointslices'], 'verbs': ['list']},
]
for kind in ('RoleBinding', 'ClusterRoleBinding'):
    subject = get(native, kind)['subjects'][0]
    assert subject == {'kind': 'ServiceAccount', 'name': deployment['spec']['template']['spec']['serviceAccountName'], 'namespace': 'evaluation'}
assert get(native, 'ClusterRole')['metadata']['name'] != get(render(NATIVE, 'other'), 'ClusterRole')['metadata']['name']
assert all('argoproj' not in json.dumps(item) for item in native)

byo = copy.deepcopy(NATIVE)
byo['controlPlane']['deployTarget']['native']['rbac'] = {'create': False}
assert not [item for item in render(byo) if item['kind'] in ('Role', 'ClusterRole', 'RoleBinding', 'ClusterRoleBinding')]
byo['controlPlane']['deployTarget']['enabled'] = False
assert not any('ControlPlane__DeployTargets__0__Backend' in item.get('data', {}) for item in render(byo))

n = 'controlPlane.deployTarget.native.'
for field in ('clusterArn', 'apiServer', 'caSha256', 'clusterUid', 'deploymentUid', 'serviceUid', 'routeUid', 'publicUrl', 'functionalQueryPath'):
    refused(n + field, '', 'requires an observed value')
refused('controlPlane.deployTarget.backend', 'honua-kubernetes-argo-rollouts')
refused('image.digest', '', 'image.digest')
refused('controlPlane.deployTarget.artifactReference', 'other@sha256:' + 'c' * 64, 'artifactReference')
refused('serviceAccount.automount', False, 'automount=true')
refused(n + 'migrationsReady', False, 'migrationsReady=true')
refused('config.env.HONUA_SKIP_MIGRATIONS', 'false', 'HONUA_SKIP_MIGRATIONS=true')
refused('strategy.type', 'Recreate', 'RollingUpdate')
refused(n + 'expectedContains', '', 'expectedContains or expectedSha256')
refused(n + 'routeUid', '22345678-1234-1234-1234-123456789abc', 'routeUid equal to serviceUid')
refused('service.type', 'ClusterIP', 'service.type=LoadBalancer')
refused('service.port', 80, 'publicUrl port must match')
for url in ('http://lb.example.test', 'https://user:secret@lb.example.test', 'https://lb.example.test?token=x', 'https://lb.example.test#fragment'):
    refused(n + 'publicUrl', url, 'publicUrl must be HTTPS')
for url in ('http://cluster.example.test', 'https://user:secret@cluster.example.test', 'https://cluster.example.test/api'):
    refused(n + 'apiServer', url, 'apiServer must be an HTTPS API origin')
for path in ('//evil.example/path', '/../secrets', '/%2e%2e/secrets', '/query#fragment'):
    refused(n + 'functionalQueryPath', path, 'must stay beneath publicUrl')

# Custom DNS proof is a complete, protected identity set; resolver selection is
# host configuration and must not become an operation parameter.
custom = copy.deepcopy(NATIVE)
custom['controlPlane']['deployTarget']['native'].update(
    loadBalancerArn='arn:aws:elasticloadbalancing:us-west-2:123456789012:loadbalancer/net/honua/0123456789abcdef',
    dnsZoneId='Z1234567890', dnsRecordName='lb.example.test',
    publicDnsResolvers=['1.1.1.1', '2606:4700:4700::1111'])
custom_rendered = render(custom)
custom_params = parameters(custom_rendered)
assert custom_params['kubernetes.dns_record_name'] == 'lb.example.test'
assert custom_params['kubernetes.dns_zone_id'] == 'Z1234567890'
assert custom_params['kubernetes.load_balancer_arn'].endswith('/net/honua/0123456789abcdef')
assert not any('resolver' in key.lower() for key in custom_params)
config = next(item['data'] for item in custom_rendered if item['kind'] == 'ConfigMap'
              and 'ControlPlane__DeployTargets__0__Backend' in item.get('data', {}))
assert config['ControlPlane__Kubernetes__PublicDns__Resolvers__0'] == '1.1.1.1'
assert config['ControlPlane__Kubernetes__PublicDns__Resolvers__1'] == '2606:4700:4700::1111'
for field, value in (
    ('loadBalancerArn', ''), ('dnsZoneId', ''), ('dnsRecordName', ''), ('publicDnsResolvers', []),
    ('dnsRecordName', 'dualstack.lb.example.test'), ('dnsRecordName', 'other.example.test'),
    ('publicDnsResolvers', ['resolver.example.test']), ('publicDnsResolvers', ['999.1.1.1']),
    ('publicDnsResolvers', ['1.1.1.1'] * 2), ('publicDnsResolvers', ['1.1.1.' + str(i) for i in range(1, 6)]),
    ('loadBalancerArn', 'arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/honua/0123456789abcdef'),
    ('loadBalancerArn', 'arn:aws:elasticloadbalancing:us-west-2:999999999999:loadbalancer/net/honua/0123456789abcdef'),
    ('loadBalancerArn', 'arn:aws-cn:elasticloadbalancing:us-west-2:123456789012:loadbalancer/net/honua/0123456789abcdef'),
):
    invalid = copy.deepcopy(custom)
    invalid['controlPlane']['deployTarget']['native'][field] = value
    render(invalid, succeeds=False)
normalized = copy.deepcopy(custom)
normalized['controlPlane']['deployTarget']['native']['dnsRecordName'] = 'LB.EXAMPLE.TEST.'
render(normalized)

# Chart-derived Ingress host/prefix must actually route the health/query paths.
ingress = copy.deepcopy(custom)
ingress['service']['type'] = 'ClusterIP'
ingress['service']['port'] = 80
ingress['ingress'] = {'enabled': True, 'hosts': [{'host': 'maps.example.test', 'paths': [{'path': '/honua', 'pathType': 'Prefix'}]}]}
ingress['controlPlane']['deployTarget']['native'].update(
    routeKind='Ingress', routeHost='maps.example.test', routePath='/honua', publicUrl='https://maps.example.test/honua', dnsRecordName='maps.example.test')
rendered = render(ingress)
assert get(rendered, 'Role')['rules'][-1] == {'apiGroups': ['networking.k8s.io'], 'resources': ['ingresses'], 'resourceNames': [get(rendered, 'Ingress')['metadata']['name']], 'verbs': ['get']}
assert parameters(rendered)['kubernetes.route_path_type'] == 'Prefix'
ingress['controlPlane']['deployTarget']['native']['routePath'] = '/other'
assert 'exactly one chart-rendered Prefix' in render(ingress, succeeds=False)
ingress['controlPlane']['deployTarget']['native']['routePath'] = '/honua'
ingress['controlPlane']['deployTarget']['native']['publicUrl'] = 'https://maps.example.test/other'
assert 'beneath the selected routePath' in render(ingress, succeeds=False)
print('native Deployment registration, scoped RBAC and refusal checks passed')
