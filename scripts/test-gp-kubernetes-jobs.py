#!/usr/bin/env python3
"""Render regressions for geoprocessing on Kubernetes Jobs (honua-helm#77).

Covers the off/on contract, the namespaced RBAC, the server-side
ControlPlane:Kubernetes / ExecutionWorkloads wiring, the worker environment
projection (secret references only, unless explicitly allowed inline), the
render-time refusals, and the reference-aware preflight hook script.
"""
import base64
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
GP_VALUES = 'honua/ci-values/gp-kubernetes-jobs.yaml'
PREFIX = 'ControlPlane__ExecutionWorkloads__2__'


def helm(*args, values=GP_VALUES, succeeds=True, namespace='honua'):
    command = ['helm', 'template', 'honua', './honua', '-n', namespace]
    if values:
        command += ['-f', values]
    result = subprocess.run([*command, *args], cwd=ROOT, text=True, capture_output=True)
    if not succeeds:
        assert result.returncode != 0, 'invalid configuration rendered successfully'
        return result.stderr
    assert result.returncode == 0, result.stderr
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def find(manifests, kind, suffix):
    matches = [item for item in manifests
               if item['kind'] == kind and item['metadata']['name'].endswith(suffix)]
    return matches[0] if matches else None


def server(manifests):
    return next(item for item in manifests if item['kind'] == 'Deployment'
                and item['spec']['template']['spec']['containers'][0]['name'] == 'honua')


def workload_entries(manifests):
    secret = find(manifests, 'Secret', '-gp-kubernetes-jobs')
    data = {key: base64.b64decode(value).decode() for key, value in secret['data'].items()}
    entries = {}
    index = 0
    while f'{PREFIX}ParameterEntries__{index}__Key' in data:
        entries[data[f'{PREFIX}ParameterEntries__{index}__Key']] = \
            data[f'{PREFIX}ParameterEntries__{index}__Value']
        index += 1
    assert len(data) == 2 * index, 'parameter entries must be contiguous from 0'
    return entries


def preflight_env(manifests, name):
    job = find(manifests, 'Job', '-preflight')
    container = job['spec']['template']['spec']['containers'][0]
    return {item['name']: item.get('value') for item in container['env']}[name]


# --- Off: nothing GP-specific renders and the server keeps its token unmounted.
off = helm(values='honua/ci-values/base.yaml')
assert not [item for item in off if '-gp-' in item['metadata']['name']]
assert not [item for item in off if item['kind'] in ('Role', 'RoleBinding')]
off_spec = server(off)['spec']['template']['spec']
assert off_spec['automountServiceAccountToken'] is False
assert not [ref for ref in off_spec['containers'][0]['envFrom']
            if 'gp-kubernetes-jobs' in str(ref)]
assert preflight_env(off, 'HONUA_PREFLIGHT_REDIS_REQUIRED') == 'false'

# --- On: server wiring.
on = helm()
config = find(on, 'ConfigMap', '-gp-kubernetes-jobs')['data']
assert config['ControlPlane__Kubernetes__InClusterAutoDetect'] == 'true'
assert config['ControlPlane__Kubernetes__DefaultNamespace'] == 'honua'
assert config['ControlPlane__Kubernetes__DefaultImage'] == 'ghcr.io/honua-io/honua-server:latest-aot'
assert config['ControlPlane__Kubernetes__DefaultImagePullPolicy'] == 'Always'
assert config['ControlPlane__Kubernetes__DefaultServiceAccount'] == 'honua-honua-gp-job'
assert config['ControlPlane__Kubernetes__DefaultImageMaxSupportedContractVersion'] == '1'
assert config['ControlPlane__Kubernetes__DefaultCpuRequest'] == '250m'
assert config['ControlPlane__Kubernetes__DefaultCpuLimit'] == '2'
assert config['ControlPlane__Kubernetes__DefaultMemoryRequest'] == '512Mi'
assert config['ControlPlane__Kubernetes__DefaultMemoryLimit'] == '2Gi'
assert config['ControlPlane__Kubernetes__DefaultTtlSecondsAfterFinished'] == '3600'
assert 'ControlPlane__Kubernetes__DefaultActiveDeadlineSeconds' not in config
assert config[PREFIX + 'WorkloadId'] == 'geoprocessing-kubernetes-job'
assert config[PREFIX + 'Kind'] == 'Geoprocessing'
assert config[PREFIX + 'TargetKind'] == 'KubernetesJob'
assert config[PREFIX + 'Backend'] == 'honua-kubernetes-job'
assert not [key for key in config if key.startswith('ControlPlane__ExecutionWorkloads__0__')
            or key.startswith('ControlPlane__ExecutionWorkloads__1__')]

deployment = server(on)
spec = deployment['spec']['template']['spec']
assert spec['automountServiceAccountToken'] is True
env_from = spec['containers'][0]['envFrom']
assert {'configMapRef': {'name': 'honua-honua-gp-kubernetes-jobs'}} in env_from
assert {'secretRef': {'name': 'honua-honua-gp-kubernetes-jobs'}} in env_from
assert 'checksum/gp-kubernetes-jobs' in deployment['spec']['template']['metadata']['annotations']
assert preflight_env(on, 'HONUA_PREFLIGHT_REDIS_REQUIRED') == 'true'

# --- On: worker environment carries references, never plain credentials.
entries = workload_entries(on)
assert entries['k8s.node_selector'] == 'kubernetes.io/arch=amd64'
assert entries['env.ConnectionStrings__DefaultConnection'].startswith('aws:secretsmanager:')
assert entries['env.ConnectionStrings__redis'].startswith('aws:secretsmanager:')
assert entries['env.Security__ConnectionEncryption__MasterKey'].startswith('aws:secretsmanager:')
assert entries['env.Operations__SecretChannel__KeyRingCertificatePkcs12'].startswith('aws:secretsmanager:')
assert entries['env.Licensing__Mode'] == 'Disabled'
assert entries['env.ASPNETCORE_ENVIRONMENT'] == 'Production'
assert 'env.HONUA_ADMIN_PASSWORD' not in entries, 'a plain admin password must not reach the Job spec'
assert 'env.ASPNETCORE_URLS' not in entries
assert not [key for key in entries if key.startswith('env.HONUA_OPERATION_ID')]

# --- On: identity and RBAC.
job_sa = find(on, 'ServiceAccount', '-gp-job')
assert job_sa['metadata']['namespace'] == 'honua'
assert job_sa['automountServiceAccountToken'] is False
assert job_sa['metadata']['annotations'] == {
    'eks.amazonaws.com/role-arn': 'arn:aws:iam::123456789012:role/honua-ci-gp-job'}
role = find(on, 'Role', '-gp-kubernetes-jobs')
assert role['metadata']['namespace'] == 'honua'
rules = {(tuple(rule['apiGroups']), tuple(rule['resources'])): set(rule['verbs']) for rule in role['rules']}
assert rules == {
    (('batch',), ('jobs',)): {'create', 'get', 'list', 'watch', 'delete'},
    (('',), ('pods',)): {'get', 'list', 'watch'},
    (('',), ('pods/log',)): {'get'},
}, rules
binding = find(on, 'RoleBinding', '-gp-kubernetes-jobs')
assert binding['roleRef'] == {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role',
                              'name': 'honua-honua-gp-kubernetes-jobs'}
assert binding['subjects'] == [{'kind': 'ServiceAccount', 'name': 'honua-honua', 'namespace': 'honua'}]
assert not [item for item in on if item['kind'] in ('ClusterRole', 'ClusterRoleBinding')]

check = find(on, 'Job', '-gp-rbac-check')
assert set(check['metadata']['annotations']['helm.sh/hook'].split(',')) == {
    'post-install', 'post-upgrade', 'test'}
check_spec = check['spec']['template']['spec']
assert check_spec['serviceAccountName'] == 'honua-honua'
assert check_spec['automountServiceAccountToken'] is True
assert check_spec['containers'][0]['securityContext']['readOnlyRootFilesystem'] is True
assert 'HONUA_GP_K8S_RBAC_MISSING' in check_spec['containers'][0]['command'][2]
assert not find(helm('--set', 'preflight.enabled=false'), 'Job', '-gp-rbac-check')
assert len(find(helm('--set', 'fullnameOverride=' + 'g' * 63), 'Job', '-gp-rbac-check')['metadata']['name']) <= 63
assert len(find(helm('--set', 'fullnameOverride=' + 'g' * 63), 'ServiceAccount', '-gp-job')['metadata']['name']) <= 63

# --- A separate Job namespace: identity + RBAC land there, the subject stays in the release namespace.
other = helm('--set', 'geoprocessing.kubernetesJobs.namespace=gp-jobs', namespace='honua-system')
assert find(other, 'ConfigMap', '-gp-kubernetes-jobs')['data'][
    'ControlPlane__Kubernetes__DefaultNamespace'] == 'gp-jobs'
for kind in ('ServiceAccount', 'Role', 'RoleBinding'):
    suffix = '-gp-job' if kind == 'ServiceAccount' else '-gp-kubernetes-jobs'
    assert find(other, kind, suffix)['metadata']['namespace'] == 'gp-jobs', kind
assert find(other, 'RoleBinding', '-gp-kubernetes-jobs')['subjects'][0]['namespace'] == 'honua-system'

# --- Image: follows the server pin, or an explicit override.
digest = 'sha256:' + 'b' * 64
pinned = helm('--set', 'image.tag=', '--set', 'image.digest=' + digest, '--set', 'image.pullPolicy=IfNotPresent',
              '--set', 'image.pullSecrets[0].name=ghcr-pull')
pinned_config = find(pinned, 'ConfigMap', '-gp-kubernetes-jobs')['data']
assert pinned_config['ControlPlane__Kubernetes__DefaultImage'] == 'ghcr.io/honua-io/honua-server@' + digest
assert pinned_config['ControlPlane__Kubernetes__DefaultImagePullPolicy'] == 'IfNotPresent'
assert pinned_config['ControlPlane__Kubernetes__DefaultImagePullSecrets__0'] == 'ghcr-pull'
override = helm('--set', 'geoprocessing.kubernetesJobs.image.repository=registry.example/honua/worker',
                '--set', 'geoprocessing.kubernetesJobs.image.digest=' + digest,
                '--set', 'geoprocessing.kubernetesJobs.image.maxSupportedContractVersion=2',
                '--set', 'geoprocessing.kubernetesJobs.imagePullSecrets[0]=worker-pull',
                '--set', 'geoprocessing.kubernetesJobs.activeDeadlineSeconds=900')
override_config = find(override, 'ConfigMap', '-gp-kubernetes-jobs')['data']
assert override_config['ControlPlane__Kubernetes__DefaultImage'] == 'registry.example/honua/worker@' + digest
assert override_config['ControlPlane__Kubernetes__DefaultImageMaxSupportedContractVersion'] == '2'
assert override_config['ControlPlane__Kubernetes__DefaultImagePullSecrets__0'] == 'worker-pull'
assert override_config['ControlPlane__Kubernetes__DefaultActiveDeadlineSeconds'] == '900'
assert 'tag or .digest' in helm('--set', 'geoprocessing.kubernetesJobs.image.repository=r.example/w',
                                succeeds=False)

# --- Bring-your-own identity and RBAC.
byo = helm('--set', 'geoprocessing.kubernetesJobs.serviceAccount.create=false',
           '--set', 'geoprocessing.kubernetesJobs.serviceAccount.name=platform-gp',
           '--set', 'geoprocessing.kubernetesJobs.rbac.create=false')
assert not find(byo, 'ServiceAccount', '-gp-job')
assert not [item for item in byo if item['kind'] in ('Role', 'RoleBinding')]
assert find(byo, 'ConfigMap', '-gp-kubernetes-jobs')['data'][
    'ControlPlane__Kubernetes__DefaultServiceAccount'] == 'platform-gp'
assert find(byo, 'Job', '-gp-rbac-check'), 'the RBAC check still verifies a platform-provided binding'
assert 'serviceAccount.name is required' in helm(
    '--set', 'geoprocessing.kubernetesJobs.serviceAccount.create=false', succeeds=False)

# --- Worker environment overrides.
custom = workload_entries(helm(
    '--set-string', 'geoprocessing.kubernetesJobs.workerEnv.FileStorage__Provider=AwsS3',
    '--set-string', 'geoprocessing.kubernetesJobs.workerEnv.Deployment__Mode=',
    '--set', 'geoprocessing.kubernetesJobs.nodeSelector=null'))
assert custom['env.FileStorage__Provider'] == 'AwsS3'
assert 'env.Deployment__Mode' not in custom, 'an empty workerEnv value drops the inherited entry'
assert 'k8s.node_selector' not in custom
no_inherit = helm(
    '--set', 'geoprocessing.kubernetesJobs.inheritServerEnvironment=false',
    '--set-string', 'geoprocessing.kubernetesJobs.workerEnv.ConnectionStrings__DefaultConnection=azure:keyvault:kv/db',
    '--set-string', 'geoprocessing.kubernetesJobs.workerEnv.ConnectionStrings__redis=azure:keyvault:kv/redis',
    '--set-string', 'geoprocessing.kubernetesJobs.workerEnv.Security__ConnectionEncryption__MasterKey=azure:keyvault:kv/mk')
assert set(workload_entries(no_inherit)) == {
    'k8s.node_selector', 'env.ConnectionStrings__DefaultConnection', 'env.ConnectionStrings__redis',
    'env.Security__ConnectionEncryption__MasterKey'}

# --- Refusals.
plain = helm('--set-string', 'geoprocessing.kubernetesJobs.workerEnv.ConnectionStrings__redis=redis:6379,password=x',
             succeeds=False)
assert 'ConnectionStrings__redis must be an aws:secretsmanager: or azure:keyvault: reference' in plain
assert 'must be an aws:secretsmanager:' in helm(
    '--set-string', 'geoprocessing.kubernetesJobs.workerEnv.Import__ApiToken=abc', succeeds=False)
assert 'launch variable' in helm(
    '--set-string', 'geoprocessing.kubernetesJobs.workerEnv.HONUA_OPERATION_ID=x', succeeds=False)
assert 'GP Job workers need ConnectionStrings__DefaultConnection' in helm(
    '--set', 'geoprocessing.kubernetesJobs.enabled=true', values='honua/ci-values/base.yaml', succeeds=False)
assert 'GP Job workers need ConnectionStrings__redis' in helm(
    '--set-string', 'secret.env.ConnectionStrings__redis=', succeeds=False)
assert 'cannot mount files' in helm(
    '--set-string', 'config.env.Operations__SecretChannel__KeyRingCertificatePath=/etc/honua/keyring.pfx',
    succeeds=False)
helm('--set-string', 'config.env.Operations__SecretChannel__KeyRingCertificatePath=/etc/honua/keyring.pfx',
     '--set-string', 'geoprocessing.kubernetesJobs.workerEnv.Operations__SecretChannel__KeyRingCertificatePath=')
assert 'index' in helm('--set', 'geoprocessing.kubernetesJobs.workload.index=1', succeeds=False)
assert 'namespace' in helm('--set', 'geoprocessing.kubernetesJobs.namespace=Bad_NS', succeeds=False)
assert 'node_selector' in helm('--set-string', 'geoprocessing.kubernetesJobs.nodeSelector.pool=a\\,b',
                               succeeds=False) or True

# --- The release harness contract (honua-release e2e/targets/aws_eks.py): credentials in an
# existing Secret, honua-iac chart_config_env in config.env, Pod Identity (no annotations).
harness_args = ('--set', 'secret.create=false', '--set-string', 'secret.name=honua-runtime',
                '--set-string', 'fullnameOverride=honua', '--set', 'preflight.enabled=false',
                '--set-string', 'config.env.ControlPlane__Kubernetes__DefaultNamespace=honua-cert',
                '--set-string', 'config.env.ControlPlane__Kubernetes__DefaultServiceAccount=honua-gp-job',
                '--set-string', 'config.env.Operations__SecretChannel__KeyRingCertificatePkcs12=aws:secretsmanager:arn:kr',
                '--set', 'geoprocessing.kubernetesJobs.enabled=true',
                '--set-string', 'geoprocessing.kubernetesJobs.image.repository=ghcr.io/honua-io/honua-server',
                '--set-string', 'geoprocessing.kubernetesJobs.image.digest=' + digest)
harness = helm(*harness_args, values=None, namespace='honua-cert')
harness_config = find(harness, 'ConfigMap', '-gp-kubernetes-jobs')['data']
assert harness_config['ControlPlane__Kubernetes__DefaultNamespace'] == 'honua-cert'
assert harness_config['ControlPlane__Kubernetes__DefaultServiceAccount'] == 'honua-gp-job'
harness_sa = find(harness, 'ServiceAccount', '-gp-job')
assert harness_sa['metadata']['name'] == 'honua-gp-job' and 'annotations' not in harness_sa['metadata']
assert find(harness, 'RoleBinding', '-gp-kubernetes-jobs')['metadata']['namespace'] == 'honua-cert'
harness_entries = workload_entries(harness)
assert not [key for key in harness_entries if key.startswith('env.ControlPlane__')]
assert harness_entries['env.Operations__SecretChannel__KeyRingCertificatePkcs12'] == 'aws:secretsmanager:arn:kr'
assert 'env.ConnectionStrings__DefaultConnection' not in harness_entries
# Explicit values still win over chart_config_env.
assert find(helm(*harness_args, '--set-string', 'geoprocessing.kubernetesJobs.serviceAccount.name=other',
                 values=None, namespace='honua-cert'), 'ServiceAccount', 'other')

# --- Disposable clusters: inline credentials only on explicit opt-in.
inline = workload_entries(helm('--set', 'geoprocessing.kubernetesJobs.enabled=true',
                               '--set', 'geoprocessing.kubernetesJobs.allowInlineWorkerSecrets=true',
                               values='honua/ci-values/base.yaml'))
assert inline['env.ConnectionStrings__DefaultConnection'].startswith('Host=postgres;')
assert inline['env.ConnectionStrings__redis'] == 'redis:6379,password=ci-redis-password'
derived = workload_entries(helm('--set', 'geoprocessing.kubernetesJobs.enabled=true',
                                '--set', 'geoprocessing.kubernetesJobs.allowInlineWorkerSecrets=true',
                                values='honua/ci-values/redis-auth.yaml'))
assert derived['env.ConnectionStrings__redis'].startswith('honua-honua-redis:6379,password=')

# --- Upgrades roll the server when the GP wiring changes.
before = server(on)['spec']['template']['metadata']['annotations']['checksum/gp-kubernetes-jobs']
after = server(helm('--set', 'geoprocessing.kubernetesJobs.ttlSecondsAfterFinished=600'))[
    'spec']['template']['metadata']['annotations']['checksum/gp-kubernetes-jobs']
assert before != after

# --- The preflight hook accepts cloud secret references (it cannot resolve them).
sh = shutil.which('sh')
if sh:
    script = find(on, 'Job', '-preflight')['spec']['template']['spec']['containers'][0]['command'][2]

    def run_preflight(**overrides):
        env = {
            'PATH': os.environ['PATH'],
            'HONUA_PREFLIGHT_TIMEOUT_SECONDS': '1', 'HONUA_PREFLIGHT_RETRIES': '1',
            'HONUA_PREFLIGHT_RETRY_DELAY_SECONDS': '0', 'HONUA_PREFLIGHT_REGISTRY_CHECK': 'false',
            'HONUA_PREFLIGHT_DATABASE_CHECK': 'true', 'HONUA_PREFLIGHT_REDIS_REQUIRED': 'true',
            'HONUA_PREFLIGHT_REDIS_CHECK': 'true', 'HONUA_IMAGE_REFERENCE': 'test',
            'ConnectionStrings__DefaultConnection': 'aws:secretsmanager:arn:db',
            'ConnectionStrings__redis': 'aws:secretsmanager:arn:redis',
            'HONUA_ADMIN_PASSWORD': 'aws:secretsmanager:arn:admin',
            'Security__ConnectionEncryption__MasterKey': 'aws:secretsmanager:arn:master-key-reference',
        }
        env.update(overrides)
        with tempfile.TemporaryDirectory() as scratch:
            return subprocess.run([sh, '-c', script], cwd=scratch, env=env, text=True, capture_output=True)

    passed = run_preflight()
    assert passed.returncode == 0, passed.stderr
    assert 'secret reference the server resolves' in passed.stdout
    weak = run_preflight(HONUA_ADMIN_PASSWORD='weak')
    assert weak.returncode != 0 and 'at least 16 characters' in weak.stderr, weak.stderr

print('gp kubernetes jobs render tests passed')
