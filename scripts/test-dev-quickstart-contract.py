"""Development quick start must be PostGIS, digest-pinned, and free of stored credentials."""
import base64
import subprocess

import yaml

FORBIDDEN = (
    'DevAdminPassword1!',
    'honua-dev-password',
    'honua-dev-redis',
    'dev-connection-encryption-master-key-00000001',
    'bitnami/postgresql',
)


def helm(*args):
    result = subprocess.run(
        ['helm', 'template', 'honua-dev', './honua', *args],
        capture_output=True, text=True)
    return result


def render(*args):
    result = helm('-f', 'honua/values-dev.yaml', *args)
    assert result.returncode == 0, result.stderr
    return result.stdout


def documents(text):
    return [document for document in yaml.safe_load_all(text) if document]


def decode(secret, key):
    return base64.b64decode(secret['data'][key]).decode()


def password_from_connection(connection):
    for part in connection.split(';'):
        name, _, value = part.partition('=')
        if name == 'Password':
            return value
    raise AssertionError('connection string has no Password field')


def render_once():
    text = render()
    for forbidden in FORBIDDEN:
        assert forbidden not in text, forbidden
    docs = documents(text)
    app_secret = next(
        document for document in docs
        if document.get('kind') == 'Secret'
        and document['metadata']['name'] == 'honua-dev-honua-secret')
    admin = decode(app_secret, 'HONUA_ADMIN_PASSWORD')
    master = decode(app_secret, 'Security__ConnectionEncryption__MasterKey')
    database = decode(app_secret, 'ConnectionStrings__DefaultConnection')
    redis_connection = decode(app_secret, 'ConnectionStrings__redis')
    assert admin.startswith('Aa1!') and len(admin) >= 16
    assert any(not character.isalnum() for character in admin)
    assert len(master) >= 32 and master.isalnum()
    postgis_secret = next(
        document for document in docs
        if document.get('kind') == 'Secret'
        and document['metadata']['name'].endswith('-postgis'))
    postgis_password = postgis_secret['stringData']['password']
    assert password_from_connection(database) == postgis_password
    assert postgis_password.startswith('Aa1') and ';' not in postgis_password
    redis_secret = next(
        document for document in docs
        if document.get('kind') == 'Secret'
        and document['metadata']['name'].endswith('-redis'))
    redis_password = redis_secret['stringData']['password']
    assert redis_connection.endswith(',password=' + redis_password)
    assert redis_password.startswith('Aa1') and ',' not in redis_password
    postgis = next(
        document for document in docs
        if document.get('kind') == 'Deployment'
        and document['metadata']['name'].endswith('-postgis'))
    postgis_image = postgis['spec']['template']['spec']['containers'][0]['image']
    assert postgis_image.startswith('pgrouting/pgrouting@sha256:')
    assert 'readOnlyRootFilesystem' not in yaml.safe_dump(
        postgis['spec']['template']['spec']['containers'][0].get('securityContext', {}))
    redis = next(
        document for document in docs
        if document.get('kind') == 'Deployment'
        and document['metadata']['name'].endswith('-redis'))
    redis_image = redis['spec']['template']['spec']['containers'][0]['image']
    assert redis_image.startswith('redis@sha256:')
    redis_volumes = {volume['name']: volume for volume in redis['spec']['template']['spec']['volumes']}
    assert 'emptyDir' in redis_volumes['data']
    assert not any(document.get('kind') == 'PersistentVolumeClaim'
                   and document['metadata']['name'].endswith('-redis') for document in docs)
    assert 'checksum/redis-password' not in yaml.safe_dump(redis)
    salted = redis['spec']['template']['metadata']['annotations']['checksum/redis-secret']
    assert salted != __import__('hashlib').sha256(redis_password.encode()).hexdigest()
    for document in docs:
        if document.get('kind') != 'Job':
            continue
        image = document['spec']['template']['spec']['containers'][0]['image']
        assert '@sha256:' in image, image
    test_pod = next(
        document for document in docs
        if document.get('kind') == 'Pod' and document['metadata']['name'].endswith('-test-connection'))
    test_container = test_pod['spec']['containers'][0]
    assert test_container['securityContext']['runAsNonRoot'] is True
    assert test_container['image'].startswith('curlimages/curl@sha256:')
    assert any(volume.get('name') == 'tmp' for volume in test_pod['spec']['volumes'])
    assert 'attempts=60' in test_container['command'][-1]
    notes_src = open('honua/templates/NOTES.txt', encoding='utf-8').read()
    assert 'Password' not in notes_src and 'adminPassword' not in notes_src
    for document in docs:
        if document.get('kind') in ('Secret',):
            continue
        rendered = yaml.safe_dump(document)
        assert admin not in rendered and master not in rendered
        assert postgis_password not in rendered and redis_password not in rendered
    return admin


def main():
    first = render_once()
    second = render_once()
    assert first != second

    upgrade_docs = documents(render('--is-upgrade'))
    preflight = next(
        document for document in upgrade_docs
        if document.get('kind') == 'Job' and document['metadata']['name'].endswith('-preflight'))
    preflight_env = {
        item['name']: item['value']
        for item in preflight['spec']['template']['spec']['containers'][0]['env']
    }
    assert preflight_env['HONUA_PREFLIGHT_DATABASE_CHECK'] == 'false'
    assert preflight_env['HONUA_PREFLIGHT_REDIS_CHECK'] == 'false'

    pdb_text = render('--set', 'podDisruptionBudget.enabled=true')
    pdb = next(document for document in documents(pdb_text)
               if document.get('kind') == 'PodDisruptionBudget')
    assert pdb['spec']['selector']['matchLabels']['app.kubernetes.io/component'] == 'server'
    for document in documents(pdb_text):
        if document.get('kind') not in ('Deployment', 'Job'):
            continue
        labels = document['spec']['template']['metadata'].get('labels', {})
        name = document['metadata']['name']
        if name.endswith('-postgis') or name.endswith('-redis') or document.get('kind') == 'Job':
            assert labels.get('app.kubernetes.io/component') != 'server', name

    production = helm(
        '-f', 'honua/values-dev.yaml',
        '--set', 'config.env.ASPNETCORE_ENVIRONMENT=Production')
    assert production.returncode != 0
    assert 'secret.generateCredentials cannot be used' in production.stderr

    both = helm(
        '-f', 'honua/values-dev.yaml',
        '--set', 'postgresql.enabled=true',
        '--set', 'postgresql.auth.username=honua',
        '--set', 'postgresql.auth.password=honua',
        '--set', 'postgresql.auth.database=honua')
    assert both.returncode != 0
    assert 'cannot both be true' in both.stderr

    release = open('.github/workflows/release.yml', encoding='utf-8').read()
    assert ".image.digest = strenv(SERVER_IMAGE_DIGEST)" in release
    assert ".image.tag = \"\"" in release
    assert ".image.pullPolicy = \"IfNotPresent\"" in release
    print('Development quick start contract passed')


if __name__ == '__main__':
    main()
