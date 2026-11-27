#!/usr/bin/env python3
"""Render regressions for opt-in support telemetry push and artifact digest stamping.

Covers:
  - Baseline default values render cleanly with zero SupportTelemetry__* env vars
    and no HONUA_ARTIFACT_DIGEST / HONUA_PLATFORM_LOCK_DIGEST when unset.
  - Digest-pinned images automatically stamp HONUA_ARTIFACT_DIGEST from image.digest
    even while supportTelemetry.enabled is false; release.artifactDigest overrides
    image.digest and release.platformLockDigest stamps HONUA_PLATFORM_LOCK_DIGEST.
  - Enabling supportTelemetry with existingSecret renders SupportTelemetry__* env
    vars with SupportTelemetry__ApiKey projected strictly via secretKeyRef (never
    plaintext) and stamps HONUA_ARTIFACT_DIGEST when image.digest is set.
  - Invalid configurations (missing secret/endpoint, http without allowHttp,
    embedded credentials, plaintext apiKey field, out-of-range interval, duplicate
    env keys, malformed digests) are rejected at lint/render time.
  - SupportTelemetry__ApiKey never leaks into scoped GP Job worker ConfigMaps/Secrets.
"""
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = 'honua/ci-values/base.yaml'
DIGEST = 'honua/ci-values/digest.yaml'
SUPPORT_TELEMETRY = 'honua/ci-values/support-telemetry.yaml'
GP = 'honua/ci-values/gp-kubernetes-jobs.yaml'


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
    assert result.returncode != 0, f'invalid configuration rendered successfully: {args}'
    return result.stderr


def server_env(manifests):
    [deployment] = [
        item for item in manifests
        if item['kind'] == 'Deployment' and item['metadata']['name'] == 'honua-honua'
    ]
    container = deployment['spec']['template']['spec']['containers'][0]
    return {entry['name']: entry for entry in container.get('env', [])}


def check_defaults_emit_no_support_telemetry():
    env = server_env(render(BASE))
    telemetry_keys = [k for k in env if k.startswith('SupportTelemetry__')]
    assert not telemetry_keys, f'expected zero SupportTelemetry__* keys by default, got {telemetry_keys}'
    assert 'HONUA_ARTIFACT_DIGEST' not in env, 'tag-only base render should not stamp HONUA_ARTIFACT_DIGEST'
    assert 'HONUA_PLATFORM_LOCK_DIGEST' not in env, 'base render should not stamp HONUA_PLATFORM_LOCK_DIGEST'


def check_digest_stamping_without_support_telemetry():
    env = server_env(render(DIGEST))
    assert not [k for k in env if k.startswith('SupportTelemetry__')], \
        'digest.yaml must keep supportTelemetry disabled'
    assert env['HONUA_ARTIFACT_DIGEST'] == {
        'name': 'HONUA_ARTIFACT_DIGEST',
        'value': 'sha256:' + 'a' * 64,
    }
    assert 'HONUA_PLATFORM_LOCK_DIGEST' not in env

    override_digest = 'sha256:' + 'd' * 64
    lock_digest = 'sha256:' + 'e' * 64
    env_override = server_env(render(
        DIGEST,
        '--set', f'release.artifactDigest={override_digest}',
        '--set', f'release.platformLockDigest={lock_digest}',
    ))
    assert env_override['HONUA_ARTIFACT_DIGEST']['value'] == override_digest, \
        'explicit release.artifactDigest must override image.digest'
    assert env_override['HONUA_PLATFORM_LOCK_DIGEST']['value'] == lock_digest

    env_tag_override = server_env(render(
        BASE,
        '--set', f'release.artifactDigest={override_digest}',
    ))
    assert env_tag_override['HONUA_ARTIFACT_DIGEST']['value'] == override_digest


def check_support_telemetry_enabled_rendering():
    env = server_env(render(SUPPORT_TELEMETRY))
    assert env['SupportTelemetry__Enabled'] == {'name': 'SupportTelemetry__Enabled', 'value': 'true'}
    assert env['SupportTelemetry__EndpointUrl'] == {
        'name': 'SupportTelemetry__EndpointUrl',
        'value': 'https://support.honua.io/api/v1/telemetry/ingest',
    }
    assert env['SupportTelemetry__AllowHttp'] == {'name': 'SupportTelemetry__AllowHttp', 'value': 'false'}
    assert env['SupportTelemetry__ApiKey'] == {
        'name': 'SupportTelemetry__ApiKey',
        'valueFrom': {
            'secretKeyRef': {
                'name': 'honua-support-telemetry-api-key',
                'key': 'api-key',
            },
        },
    }
    assert 'value' not in env['SupportTelemetry__ApiKey'], 'API key must never be a literal value'
    assert env['SupportTelemetry__InstanceId'] == {
        'name': 'SupportTelemetry__InstanceId',
        'value': 'ci-cluster-west-1',
    }
    assert env['SupportTelemetry__InstanceUrl'] == {
        'name': 'SupportTelemetry__InstanceUrl',
        'value': 'https://gis.example.com',
    }
    assert env['SupportTelemetry__IntervalSeconds'] == {
        'name': 'SupportTelemetry__IntervalSeconds',
        'value': '120',
    }
    assert env['SupportTelemetry__IncludeOpsFindings'] == {
        'name': 'SupportTelemetry__IncludeOpsFindings',
        'value': 'true',
    }
    assert env['HONUA_ARTIFACT_DIGEST'] == {
        'name': 'HONUA_ARTIFACT_DIGEST',
        'value': 'sha256:' + 'a' * 64,
    }
    assert env['HONUA_PLATFORM_LOCK_DIGEST'] == {
        'name': 'HONUA_PLATFORM_LOCK_DIGEST',
        'value': 'sha256:' + 'b' * 64,
    }

    # Optional fields omitted when empty; boolean false and allowHttp=true preserved.
    env_minimal = server_env(render(
        BASE,
        '--set', 'supportTelemetry.enabled=true',
        '--set', 'supportTelemetry.endpointUrl=http://honua-support.internal:8080/api/v1/telemetry/ingest',
        '--set', 'supportTelemetry.allowHttp=true',
        '--set', 'supportTelemetry.existingSecret=my-telemetry-secret',
        '--set', 'supportTelemetry.existingSecretKey=token',
        '--set', 'supportTelemetry.includeOpsFindings=false',
    ))
    assert env_minimal['SupportTelemetry__AllowHttp']['value'] == 'true'
    assert env_minimal['SupportTelemetry__IncludeOpsFindings']['value'] == 'false'
    assert env_minimal['SupportTelemetry__IntervalSeconds']['value'] == '60'
    assert env_minimal['SupportTelemetry__ApiKey']['valueFrom']['secretKeyRef'] == {
        'name': 'my-telemetry-secret',
        'key': 'token',
    }
    assert 'SupportTelemetry__InstanceId' not in env_minimal
    assert 'SupportTelemetry__InstanceUrl' not in env_minimal


def check_invalid_configurations_refused():
    # Missing endpointUrl
    refused(
        BASE,
        '--set', 'supportTelemetry.enabled=true',
        '--set', 'supportTelemetry.existingSecret=my-secret',
    )
    # Missing existingSecret
    refused(
        BASE,
        '--set', 'supportTelemetry.enabled=true',
        '--set', 'supportTelemetry.endpointUrl=https://support.honua.io/api/v1/telemetry/ingest',
    )
    # Plain http without allowHttp
    refused(
        BASE,
        '--set', 'supportTelemetry.enabled=true',
        '--set', 'supportTelemetry.endpointUrl=http://support.honua.io/api/v1/telemetry/ingest',
        '--set', 'supportTelemetry.existingSecret=my-secret',
    )
    # Embedded credentials in endpointUrl
    refused(
        BASE,
        '--set', 'supportTelemetry.enabled=true',
        '--set', 'supportTelemetry.endpointUrl=https://user:pass@support.honua.io/api/v1/telemetry/ingest',
        '--set', 'supportTelemetry.existingSecret=my-secret',
    )
    # Plaintext apiKey field rejected by additionalProperties: false
    refused(
        BASE,
        '--set', 'supportTelemetry.apiKey=never-allow-plaintext',
    )
    # Out-of-range intervalSeconds
    refused(
        SUPPORT_TELEMETRY,
        '--set', 'supportTelemetry.intervalSeconds=5',
    )
    refused(
        SUPPORT_TELEMETRY,
        '--set', 'supportTelemetry.intervalSeconds=3601',
    )
    # Duplicate SupportTelemetry__* in config.env / secret.env / extraEnv
    refused(
        SUPPORT_TELEMETRY,
        '--set', 'config.env.SupportTelemetry__Enabled=false',
    )
    refused(
        SUPPORT_TELEMETRY,
        '--set', 'secret.env.SupportTelemetry__ApiKey=plaintext',
    )
    refused(
        SUPPORT_TELEMETRY,
        '--set', 'extraEnv[0].name=SupportTelemetry__EndpointUrl',
        '--set', 'extraEnv[0].value=https://other.example/ingest',
    )
    # Malformed digests
    refused(
        BASE,
        '--set', 'release.artifactDigest=sha256:not-valid',
    )
    refused(
        BASE,
        '--set', 'release.platformLockDigest=sha256:not-valid',
    )


def check_gp_worker_does_not_receive_support_telemetry_secret():
    manifests = render(
        GP,
        '--set', 'supportTelemetry.enabled=true',
        '--set', 'supportTelemetry.endpointUrl=https://support.honua.io/api/v1/telemetry/ingest',
        '--set', 'supportTelemetry.existingSecret=honua-support-telemetry-api-key',
    )
    for item in manifests:
        name = item['metadata']['name']
        if item['kind'] in ('ConfigMap', 'Secret') and 'gp-' in name:
            serialized = yaml.safe_dump(item)
            assert 'SupportTelemetry__ApiKey' not in serialized, \
                f'SupportTelemetry__ApiKey leaked into GP resource {item["kind"]}/{name}'


check_defaults_emit_no_support_telemetry()
check_digest_stamping_without_support_telemetry()
check_support_telemetry_enabled_rendering()
check_invalid_configurations_refused()
check_gp_worker_does_not_receive_support_telemetry_secret()
print('support telemetry and artifact digest render regressions passed')
