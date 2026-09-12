#!/usr/bin/env python3
"""Render the chart and execute its real hook against independent HTTP fixtures."""
import copy
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(*args, succeeds=True):
    result = subprocess.run(
        ['helm', 'template', 'honua', './honua', '-f', 'honua/ci-values/base.yaml', *args],
        cwd=ROOT, text=True, capture_output=True,
    )
    if not succeeds:
        assert result.returncode != 0, 'invalid configuration rendered successfully'
        return result.stderr
    assert result.returncode == 0, result.stderr
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def container(manifests, kind, suffix=''):
    resource = next(item for item in manifests if item['kind'] == kind and item['metadata']['name'].endswith(suffix))
    return resource['spec']['template']['spec']['containers'][0]


def env_values(container):
    return {item['name']: item.get('value', item.get('valueFrom')) for item in container['env']}


base = render()
assert env_values(container(base, 'Deployment'))['Licensing__Mode'] == 'Disabled'
for args in [('--is-upgrade',), ('-f', 'honua/ci-values/external-secret.yaml'),
             ('--set', 'config.create=false'),
             ('--set', 'config.env.Licensing__Mode=Enabled'),
             ('-f', 'honua/ci-values/upgrade-base.yaml'),
             ('-f', 'honua/ci-values/upgrade-target.yaml')]:
    assert env_values(container(render(*args), 'Deployment'))['Licensing__Mode'] == 'Disabled'

enabled = render('-f', 'honua/ci-values/licensing-enabled.yaml')
env = env_values(container(enabled, 'Deployment'))
assert env['Licensing__Mode'] == 'Enabled'
assert env['Licensing__Edition'] == 'Pro'
assert env['Licensing__LicenseContent'] == {'secretKeyRef': {'name': 'honua-license', 'key': 'signed-license.json'}}
assert not any(item['metadata']['name'].endswith('-preflight-license-status') for item in enabled)
assert not any(item['metadata']['name'].endswith('-preflight-license-status') for item in render('--set', 'preflight.enabled=false'))
assert 'mode' in render('--set', 'licensing.mode=Disable', succeeds=False)
assert 'extraEnv' in render('--set', 'extraEnv[0].name=Licensing__Mode', '--set', 'extraEnv[0].value=Enabled', succeeds=False)

hook = next(item for item in base if item['metadata']['name'].endswith('-preflight-license-status'))
assert set(hook['metadata']['annotations']['helm.sh/hook'].split(',')) == {'post-install', 'post-upgrade', 'test'}
long_name = render('--set', 'fullnameOverride=' + 'h' * 50)
long_hook = next(item for item in long_name if item['metadata']['name'].endswith('-preflight-license-status'))
assert len(long_hook['metadata']['name']) <= 63
assert all(len(value) <= 63 for value in long_hook['spec']['template']['metadata']['labels'].values())
service = next(item for item in base if item['kind'] == 'Service')
assert not all(hook['spec']['template']['metadata']['labels'].get(key) == value
               for key, value in service['spec']['selector'].items()), 'hook must not receive application traffic'
hook_container = container(base, 'Job', '-preflight-license-status')
assert hook_container['envFrom'] == [{'secretRef': {'name': 'honua-honua-secret'}}]
for args, expected in [
    (('--set', 'config.env.Public__BaseUrl=https://public.example:8443'), 'public.example:8443'),
    (('--set', 'ingress.enabled=true', '--set', 'ingress.hosts[0].host=ingress.example'), 'ingress.example'),
    (('--set', 'config.env.Public__BaseUrl=https://public.example', '--set', 'preflight.licenseStatusHost=allowed.example'), 'allowed.example'),
    (('-f', 'honua/ci-values/upgrade-base.yaml'), 'honua-honua'),
    (('-f', 'honua/ci-values/upgrade-target.yaml'), 'honua-honua'),
]:
    assert env_values(container(render(*args), 'Job', '-preflight-license-status'))['HONUA_LICENSE_STATUS_HOST'] == expected
private = container(render('--set', 'preflight.licenseStatusImage.repository=registry.example/python',
                           '--set', 'image.pullSecrets[0].name=registry-key'), 'Job', '-preflight-license-status')
assert private['image'] == 'registry.example/python:3.12-alpine'

# Hand-authored from the server API contract, never captured from chart output.
good = {'success': True, 'data': {'mode': 'disabled', 'validationState': 'Disabled', 'isValid': True}}
password = 'FixtureAdminPassword1!'
requests = []
reply = [200, json.dumps(good)]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append((self.path, self.headers.get('X-API-Key'), self.headers.get('Host')))
        self.send_response(reply[0])
        if reply[0] == 302:
            self.send_header('Location', '/credential-must-not-follow')
        self.end_headers()
        self.wfile.write(reply[1].encode())

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
env = os.environ | env_values(hook_container) | {
    'HONUA_ADMIN_PASSWORD': password,
    'HONUA_LICENSE_STATUS_URL': f'http://127.0.0.1:{server.server_port}/api/v1/admin/license/status',
    'HONUA_LICENSE_STATUS_HOST': 'honua.example.test',
    'HONUA_LICENSE_STATUS_ATTEMPTS': '1', 'HONUA_LICENSE_STATUS_DELAY': '0',
}


def run_case(name, status, body, passes=False, missing_password=False):
    reply[:] = [status, body if isinstance(body, str) else json.dumps(body)]
    case_env = env.copy()
    if missing_password:
        del case_env['HONUA_ADMIN_PASSWORD']
    requests.clear()
    result = subprocess.run(hook_container['command'], env=case_env, capture_output=True, text=True, timeout=10)
    assert (result.returncode == 0) == passes, (name, result.stdout, result.stderr)
    assert password not in result.stdout + result.stderr
    if not missing_password:
        assert requests == [('/api/v1/admin/license/status', password, 'honua.example.test')], requests
    if passes:
        assert 'license status check passed: mode=disabled' in result.stdout
    print(f'PASS: {name}')


try:
    run_case('disabled license accepted', 200, good, passes=True)
    for key, value in [('mode', 'enabled'), ('validationState', 'Valid'), ('isValid', False)]:
        bad = copy.deepcopy(good)
        bad['data'][key] = value
        run_case(f'incorrect {key} rejected', 200, bad)
    for body in [{}, {'success': False, 'data': good['data']}, {'success': True, 'data': {}},
                 {'success': True, 'data': None}, [], 'not JSON']:
        run_case(f'invalid payload {body!r} rejected', 200, body)
    for status in [204, 302, 400, 401, 403, 404, 503]:
        run_case(f'HTTP {status} rejected', status, good)
    run_case('missing admin secret rejected', 200, good, missing_password=True)
finally:
    server.shutdown()
    server.server_close()
print('Licensing render and hook execution contract passed.')
