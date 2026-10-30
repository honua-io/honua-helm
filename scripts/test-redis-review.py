"""Render regressions for managed Redis storage, rotation, naming and preflight."""
import base64
import hashlib
import subprocess

import yaml


def render(*args, valid=True, stderr_contains='password'):
    result = subprocess.run(
        ['helm', 'template', 'r' * 53, './honua', '-f',
         'honua/ci-values/redis-auth.yaml', *args], capture_output=True, text=True)
    assert (result.returncode == 0) == valid, result.stderr
    if not valid:
        assert stderr_contains in result.stderr, result.stderr
    return result.stdout


def server_deployment(text):
    documents = [document for document in yaml.safe_load_all(text) if document]
    return next(deployment for deployment in documents
                if deployment.get('kind') == 'Deployment'
                and deployment['spec']['template']['spec']['containers'][0]['name'] == 'honua')


def resource(text, kind):
    return next(doc for doc in text.split('\n---') if f'kind: {kind}\n' in doc
                and '# Source: honua/templates/redis.yaml' in doc)


def field(text, key):
    return next(line.strip().split(': ', 1)[1] for line in text.splitlines()
                if line.strip().startswith(key + ': '))


first = render('--is-upgrade')
documents = [document for document in yaml.safe_load_all(first) if document]
services = [document for document in documents if document.get('kind') == 'Service']
deployments = [document for document in documents if document.get('kind') == 'Deployment']
server = next(deployment for deployment in deployments
              if deployment['spec']['template']['spec']['containers'][0]['name'] == 'honua')
application_services = [service for service in services
                        if service['metadata']['name'] == server['metadata']['name']]
assert application_services
for service in application_services:
    selector = service['spec']['selector']
    assert selector['app.kubernetes.io/component'] == 'server'
    matching_deployments = [
        deployment for deployment in deployments
        if selector.items() <= deployment['spec']['template']['metadata']['labels'].items()
    ]
    assert matching_deployments == [server], (
        f"application Service selector also matches "
        f"{[deployment['metadata']['name'] for deployment in matching_deployments if deployment != server]}"
    )
service_name = field(resource(first, 'Service'), 'name')
assert len(service_name) <= 63 and service_name.endswith('-redis')
assert field(resource(first, 'PersistentVolumeClaim'), 'name') == service_name
assert 'storage: "8Gi"' in resource(first, 'PersistentVolumeClaim')
assert 'storageClassName:' not in resource(first, 'PersistentVolumeClaim')
deployment = resource(first, 'Deployment')
assert f'claimName: {service_name}' in deployment
assert 'mountPath: /data' in deployment and 'type: Recreate' in deployment
assert base64.b64encode(f'{service_name}:6379,password=ci-redis-password'.encode()).decode() in first
assert 'name: HONUA_PREFLIGHT_REDIS_CHECK\n              value: "false"' in first
# The Redis pod is hardened and never carries the password in argv or probe commands.
redis_documents = [document for document in yaml.safe_load_all(first) if document]
redis_deployment = next(document for document in redis_documents
                        if document.get('kind') == 'Deployment'
                        and document['metadata']['name'] == service_name)
redis_pod = redis_deployment['spec']['template']['spec']
assert redis_pod['automountServiceAccountToken'] is False
assert redis_pod['securityContext']['seccompProfile'] == {'type': 'RuntimeDefault'}
assert redis_pod['securityContext']['fsGroup'] == 1000
redis_container = redis_pod['containers'][0]
redis_security = redis_container['securityContext']
assert redis_security['runAsNonRoot'] is True and redis_security['runAsUser'] == 999
assert redis_security['allowPrivilegeEscalation'] is False
assert redis_security['readOnlyRootFilesystem'] is True
assert redis_security['capabilities'] == {'drop': ['ALL']}
assert redis_security['seccompProfile'] == {'type': 'RuntimeDefault'}
mounts = {mount['mountPath']: mount['name'] for mount in redis_container['volumeMounts']}
volumes = {volume['name']: volume for volume in redis_pod['volumes']}
assert 'persistentVolumeClaim' in volumes[mounts['/data']]
assert 'emptyDir' in volumes[mounts['/tmp']]
config_volume = volumes[mounts['/usr/local/etc/redis']]['secret']
assert config_volume['secretName'] == service_name
assert config_volume['items'] == [{'key': 'redis.conf', 'path': 'redis.conf'}]
assert redis_container['args'] == [
    'redis-server', '/usr/local/etc/redis/redis.conf', '--appendonly', 'yes',
    '--maxmemory', '200mb']
assert [env['name'] for env in redis_container['env']] == ['REDISCLI_AUTH']
for probe in ('readinessProbe', 'livenessProbe'):
    assert redis_container[probe]['exec']['command'] == ['sh', '-c', 'redis-cli ping | grep -q PONG']
assert 'ci-redis-password' not in yaml.safe_dump(redis_deployment)
redis_secret = next(document for document in redis_documents
                    if document.get('kind') == 'Secret' and document['metadata']['name'] == service_name)
assert redis_secret['stringData']['password'] == 'ci-redis-password'
assert redis_secret['stringData']['redis.conf'] == 'requirepass "ci-redis-password"\n'
overridden = yaml.safe_dump(next(
    document for document in yaml.safe_load_all(render(
        '--set', 'redis.securityContext.runAsUser=1999', '--set', 'redis.podSecurityContext.fsGroup=1999'))
    if document and document.get('kind') == 'Deployment' and document['metadata']['name'] == service_name))
assert 'runAsUser: 1999' in overridden and 'fsGroup: 1999' in overridden
rotated = render('--set-string', 'redis.auth.password=rotated-password')
assert field(deployment, 'checksum/redis-secret') != field(resource(rotated, 'Deployment'), 'checksum/redis-secret')
assert hashlib.sha256(b'ci-redis-password').hexdigest() not in deployment
assert field(resource(rotated, 'PersistentVolumeClaim'), 'name') == service_name
custom = render('--set', 'redis.persistence.size=16Gi', '--set', 'redis.persistence.storageClass=fast')
assert 'storage: "16Gi"' in custom and 'storageClassName: "fast"' in custom
explicit = render('--set-string', 'secret.env.ConnectionStrings__redis=external:6379')
assert 'name: HONUA_PREFLIGHT_REDIS_CHECK\n              value: "true"' in explicit
render('--set-string', 'secret.env.ConnectionStrings__redis=external:6379', '--set', 'redis.auth.password=', valid=False)
render('--set', 'secret.create=false', '--set', 'secret.name=existing', '--set', 'redis.auth.password=', valid=False)
render('--set-string', 'redis.auth.password=a=b', '--set-string', 'secret.env.ConnectionStrings__redis=external:6379')
render('--set-string', 'fullnameOverride=' + 'x' * 63)

labeled = render('--set', 'podLabels.team=platform')
labeled_server = server_deployment(labeled)
assert labeled_server['spec']['template']['metadata']['labels']['team'] == 'platform'
assert labeled_server['spec']['template']['metadata']['labels']['app.kubernetes.io/component'] == 'server'
labeled_service = next(
    document for document in yaml.safe_load_all(labeled)
    if document and document.get('kind') == 'Service'
    and document['metadata']['name'] == labeled_server['metadata']['name'])
assert labeled_service['spec']['selector']['app.kubernetes.io/component'] == 'server'
assert labeled_service['spec']['selector'].items() <= labeled_server['spec']['template']['metadata']['labels'].items()

reserved_label = '{"app.kubernetes.io/component":"worker"}'
render('--set-json', f'podLabels={reserved_label}', valid=False, stderr_contains='app.kubernetes.io/component')
render('--skip-schema-validation', '--set-json', f'podLabels={reserved_label}',
       valid=False, stderr_contains='podLabels must not set app.kubernetes.io/component')

# The render guard rejects the reserved key before YAML is emitted. Keep the
# pinned component label after podLabels so a bypassed guard cannot override it.
deployment_template = open('honua/templates/deployment.yaml', encoding='utf-8').read()
pod_labels_at = deployment_template.index('with .Values.podLabels')
component_at = deployment_template.index('app.kubernetes.io/component: server', pod_labels_at)
assert component_at > pod_labels_at

print('Redis review regressions passed')
