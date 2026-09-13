"""Render regressions for managed Redis storage, rotation, naming and preflight."""
import base64
import subprocess


def render(*args, valid=True):
    result = subprocess.run(
        ['helm', 'template', 'r' * 53, './honua', '-f',
         'honua/ci-values/redis-auth.yaml', *args], capture_output=True, text=True)
    assert (result.returncode == 0) == valid, result.stderr
    if not valid:
        assert 'password' in result.stderr, result.stderr
    return result.stdout


def resource(text, kind):
    return next(doc for doc in text.split('\n---') if f'kind: {kind}\n' in doc
                and '# Source: honua/templates/redis.yaml' in doc)


def field(text, key):
    return next(line.strip().split(': ', 1)[1] for line in text.splitlines()
                if line.strip().startswith(key + ': '))


first = render('--is-upgrade')
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
rotated = render('--set-string', 'redis.auth.password=rotated-password')
assert field(deployment, 'checksum/redis-password') != field(resource(rotated, 'Deployment'), 'checksum/redis-password')
assert field(resource(rotated, 'PersistentVolumeClaim'), 'name') == service_name
custom = render('--set', 'redis.persistence.size=16Gi', '--set', 'redis.persistence.storageClass=fast')
assert 'storage: "16Gi"' in custom and 'storageClassName: "fast"' in custom
explicit = render('--set-string', 'secret.env.ConnectionStrings__redis=external:6379')
assert 'name: HONUA_PREFLIGHT_REDIS_CHECK\n              value: "true"' in explicit
render('--set-string', 'secret.env.ConnectionStrings__redis=external:6379', '--set', 'redis.auth.password=', valid=False)
render('--set', 'secret.create=false', '--set', 'secret.name=existing', '--set', 'redis.auth.password=', valid=False)
render('--set-string', 'redis.auth.password=a=b', '--set-string', 'secret.env.ConnectionStrings__redis=external:6379')
render('--set-string', 'fullnameOverride=' + 'x' * 63)
print('Redis review regressions passed')
