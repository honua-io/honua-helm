"""Regressions for nightly chart publication (scripts/chart_publication.py, ruling R31).

Needs PyYAML, and helm + yq on PATH with `helm dependency build honua` already run: the end-to-end
case stamps and packages the real chart the way .github/workflows/chart-nightly.yml does.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True  # the import below must not leave scripts/__pycache__ in the tree
sys.path.insert(0, str(ROOT / 'scripts'))
import chart_publication as cp  # noqa: E402

SERVER = 'sha256:' + '1' * 64
OTHER = 'sha256:' + '2' * 64
REVISION = 'a' * 40
TRUNK = cp.TRUNK_WORKFLOW_REF
BRANCH = cp.WORKFLOW_PATH + '@refs/heads/feat/x'
# A honua-helm workflow that calls this one; its run shares the chart-nightly-release group.
CALLER = 'honua-io/honua-helm/.github/workflows/release-train.yml@refs/heads/trunk'
# Another repository's caller: its run evaluates the group in that repository, so it is refused.
FOREIGN_CALLER = 'honua-io/honua-release/.github/workflows/nightly-certification.yml@refs/heads/trunk'


def refused(action, needle):
    try:
        action()
    except cp.Refusal as exc:
        assert needle in str(exc), f'{needle!r} not in {exc}'
        return
    raise AssertionError(f'expected a refusal containing {needle!r}')


def resolve(**overrides):
    arguments = dict(inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.3'},
                     workflow_ref=TRUNK, run_workflow_ref=CALLER, source_revision=REVISION, on_trunk=True)
    arguments.update(overrides)
    return cp.resolve_request(**arguments)


def candidate(label='2026.1-rc.4', helm=REVISION, image=f'ghcr.io/honua-io/honua-server@{SERVER}', digest=SERVER):
    server = {'image': image}
    if digest:
        server['digest'] = digest
    return {'ref': 'refs/nightly-candidates/' + 'c' * 40,
            'manifest': {'platformRelease': label, 'components': {'honua-server': server, 'honua-helm': {'sha': helm}}}}


# R22 version identity: the train's label maps onto the chart version; nothing is invented.
assert cp.platform_version_from_label('2026.1-rc.3') == '2026.1.0-rc.3'
assert cp.platform_version_from_label('2026.1.2-rc.1') == '2026.1.2-rc.1'
assert cp.platform_version_from_label('2026.1') == '2026.1.0'
for label in ('', None, 'honua-2026.1-rc.3', '2026.1-rc.03', '2026.1-nightly.1'):
    refused(lambda: cp.platform_version_from_label(label), 'is not YYYY.N[.P][-rc.N]')

# The release repository: trunk workflow identity, trunk source, R22 version, sha256 digest.
request = resolve()
assert request['repository'] == 'ghcr.io/honua-io/charts/honua' and request['proof'] is False
assert request['ociNamespace'] == 'honua-io/charts' and request['mode'] == 'inputs'
assert request['signingIdentity'] == 'https://github.com/' + TRUNK
assert (request['platformVersion'], request['serverImageDigest']) == ('2026.1.0-rc.3', SERVER)
assert resolve(inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0'})['platformVersion'] == '2026.1.0'
assert resolve(inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.3',
                       'chart_revision': REVISION})['sourceRevision'] == REVISION
refused(lambda: resolve(workflow_ref=BRANCH), 'only ' + TRUNK)
refused(lambda: resolve(workflow_ref='honua-io/honua-release/.github/workflows/x.yml@refs/heads/trunk'),
        'is not ' + cp.WORKFLOW_PATH)
refused(lambda: resolve(on_trunk=False), 'is not on honua-helm trunk')
refused(lambda: resolve(inputs={'server_image_digest': 'sha256:' + 'A' * 64, 'platform_version': '2026.1.0-rc.3'}),
        'is not sha256:')
refused(lambda: resolve(inputs={'server_image_digest': f'ghcr.io/honua-io/honua-server@{SERVER}',
                                'platform_version': '2026.1.0-rc.3'}), 'is not sha256:')
for version in ('2026.1-rc.3', '0.4.0-nightly', 'v2026.1.0-rc.3', '2026.1.0-rc.3+build', '2026.01.0-rc.3'):
    refused(lambda: resolve(inputs={'server_image_digest': SERVER, 'platform_version': version}), 'R22 form')
refused(lambda: resolve(source_revision='abc'), 'is not a 40-hex commit')
# Malformed requests: half a request, a bad revision, or a revision other than the one checked out.
refused(lambda: resolve(inputs={'server_image_digest': SERVER}), 'without platform_version')
refused(lambda: resolve(inputs={'platform_version': '2026.1.0-rc.3'}), 'without server_image_digest')
refused(lambda: resolve(inputs={'chart_revision': REVISION}), 'without server_image_digest')
refused(lambda: resolve(inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.3',
                                'chart_revision': 'trunk'}), 'is not a 40-hex honua-helm commit')
refused(lambda: resolve(inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.3',
                                'chart_revision': 'b' * 40}), 'was requested but')
refused(lambda: resolve(inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.3'},
                        candidate=candidate()), 'not a nightly candidate')
# A caller that names nothing is refused: it never falls through to "the newest candidate".
refused(lambda: resolve(inputs={'server_image_digest': '', 'platform_version': ''}, candidate=candidate()),
        'called this workflow without server_image_digest')
# A caller in another repository is refused for every request: its concurrency group cannot
# serialize it with honua-helm's own nightly, and GHCR cannot refuse a second version-tag push.
refused(lambda: resolve(run_workflow_ref=FOREIGN_CALLER), 'only honua-io/honua-helm runs publish')
refused(lambda: resolve(run_workflow_ref=FOREIGN_CALLER, inputs={'server_image_digest': SERVER,
        'platform_version': '2026.1.0-rc.3', 'chart_revision': REVISION}), 'Dispatch ' + TRUNK)
# `proof` is a dispatch-only input; workflow_call does not declare it, so a caller's run has none.
assert resolve(inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.3'})['proof'] is False

# A proof dispatch may run a branch, from a branch revision, and lands only in the throwaway namespace.
proof = resolve(workflow_ref=BRANCH, run_workflow_ref=BRANCH, on_trunk=False,
                inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.0', 'proof': 'true'})
assert proof['proof'] is True and proof['repository'] == 'ghcr.io/honua-io/charts/honua-ci-proof/honua'
assert proof['signingIdentity'] == 'https://github.com/' + BRANCH
# The trunk workflow's identity never runs code from off trunk, not even for a proof.
refused(lambda: resolve(run_workflow_ref=TRUNK, on_trunk=False,
                        inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.0', 'proof': 'true'}),
        'is not on honua-helm trunk')

# The self-scheduled nightly (no inputs, not called): the newest stamped train candidate supplies
# version, server digest and helm revision.
def nightly(**overrides):
    return resolve(inputs={}, run_workflow_ref=TRUNK, **overrides)


scheduled = nightly(candidate=candidate())
assert (scheduled['platformVersion'], scheduled['serverImageDigest']) == ('2026.1.0-rc.4', SERVER)
assert scheduled['candidateRef'].startswith('refs/nightly-candidates/') and scheduled['mode'] == 'nightly-candidate'
assert nightly(candidate=candidate(digest=None))['serverImageDigest'] == SERVER
refused(lambda: nightly(candidate=None), 'no honua-release nightly candidate')
refused(lambda: nightly(candidate=candidate(helm='b' * 40)), 'pins honua-helm')
refused(lambda: nightly(candidate=candidate(digest=OTHER)), 'disagrees with digest')
refused(lambda: nightly(candidate=candidate(image='ghcr.io/honua-io/honua-server:nightly-x', digest=None)),
        'is not sha256:')
refused(lambda: nightly(candidate=candidate(label='dev-local')), 'platformRelease')

# The OCI platform set is the server index's linux platforms; attestation manifests are not platforms.
index = {'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [
    {'digest': 'sha256:' + '3' * 64, 'platform': {'os': 'linux', 'architecture': 'arm64'}},
    {'digest': 'sha256:' + '4' * 64, 'platform': {'os': 'linux', 'architecture': 'amd64'}},
    {'digest': 'sha256:' + '5' * 64, 'platform': {'os': 'unknown', 'architecture': 'unknown'},
     'annotations': {'vnd.docker.reference.type': 'attestation-manifest'}}]}
architectures, platform_digests = cp.architectures_from_index(index)
assert architectures == ['amd64', 'arm64'] and platform_digests['amd64'] == 'sha256:' + '4' * 64
s390x = json.loads(json.dumps(index))
s390x['manifests'][0]['platform']['architecture'] = 's390x'
refused(lambda: cp.architectures_from_index(s390x), "'s390x' is not exactly one of")
duplicate = json.loads(json.dumps(index))
duplicate['manifests'][0]['platform']['architecture'] = 'amd64'
refused(lambda: cp.architectures_from_index(duplicate), "'amd64' is not exactly one of")
refused(lambda: cp.architectures_from_index({'mediaType': index['mediaType'], 'manifests': index['manifests'][2:]}),
        'serves no linux platform')
single = {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'config': {'digest': 'sha256:' + '6' * 64}}
assert cp.architectures_from_index(single, lambda _: {'os': 'linux', 'architecture': 'amd64'})[0] == ['amd64']
refused(lambda: cp.architectures_from_index(single, lambda _: {'os': 'windows', 'architecture': 'amd64'}),
        'is not linux/')

# A chart manifest has exactly one Helm content layer under the Helm config media type.
layer = {'mediaType': cp.CHART_CONTENT, 'digest': 'sha256:' + '7' * 64}
assert cp.chart_layer({'config': {'mediaType': cp.CHART_CONFIG}, 'layers': [layer]}) == layer['digest']
refused(lambda: cp.chart_layer({'config': {'mediaType': 'application/vnd.oci.image.config.v1+json'},
                                'layers': [layer]}), 'is not a Helm chart config')
refused(lambda: cp.chart_layer({'config': {'mediaType': cp.CHART_CONFIG}, 'layers': [layer, layer]}),
        'carries 2 Helm chart content layers')

assert cp.rendered_images('''
          image: "ghcr.io/honua-io/honua-server@sha256:%s"
        - image: redis:7.4-alpine
          imagePullPolicy: IfNotPresent
''' % ('1' * 64)) == [f'ghcr.io/honua-io/honua-server@{SERVER}', 'redis:7.4-alpine']
redis = cp._image_component('redis:7.4-alpine')
assert redis['name'] == 'docker.io/library/redis' and redis['version'] == '7.4-alpine' and 'hashes' not in redis
server = cp._image_component(f'ghcr.io/honua-io/honua-server@{SERVER}')
assert server['purl'].startswith('pkg:oci/honua-server@sha256%3A') and server['hashes'][0]['content'] == '1' * 64
assert cp._image_component('curlimages/curl:8.5.0')['name'] == 'docker.io/curlimages/curl'

# End to end without a registry: stamp a copy of the real chart, lint, render and package it exactly
# as the workflow does, then check the binding the verifier enforces on the pulled bytes.
with tempfile.TemporaryDirectory() as temp:
    chart_dir = Path(temp) / 'honua'
    shutil.copytree(ROOT / 'honua', chart_dir)
    request = resolve(source_revision=REVISION)
    cp.stamp(str(chart_dir), request)
    assert (ROOT / 'honua' / 'Chart.yaml').read_text().count('appVersion: "0.0.0"') == 1, 'trunk Chart.yaml was edited'
    assert '# ' in (chart_dir / 'values.yaml').read_text(), 'stamping dropped values.yaml comments'
    subprocess.run(['helm', 'lint', str(chart_dir), '-f', str(ROOT / 'honua/ci-values/base.yaml')], check=True,
                   capture_output=True)
    rendered = subprocess.run(['helm', 'template', 'honua', str(chart_dir), '-f', str(ROOT / 'honua/ci-values/base.yaml')],
                              check=True, capture_output=True, text=True).stdout
    assert f'image: "ghcr.io/honua-io/honua-server@{SERVER}"' in rendered, 'rendered server image is not the digest'
    assert 'app.kubernetes.io/version: "2026.1.0-rc.3"' in rendered
    subprocess.run(['helm', 'package', str(chart_dir), '--destination', temp], check=True, capture_output=True)
    package = (Path(temp) / 'honua-2026.1.0-rc.3.tgz').read_bytes()
    # A later run re-packaging the same request builds the same chart (the reuse path compares this).
    (Path(temp) / 'again').mkdir()
    subprocess.run(['helm', 'package', str(chart_dir), '--destination', str(Path(temp) / 'again')], check=True,
                   capture_output=True)
    cp.same_contents((Path(temp) / 'again' / 'honua-2026.1.0-rc.3.tgz').read_bytes(), package)
    chart, values, lock, vendored = cp.read_package(package)
    bound = cp.verify_binding(chart, values, request)
    assert bound['serverImage'] == f'ghcr.io/honua-io/honua-server@{SERVER}' and bound['sourceRevision'] == REVISION
    refused(lambda: cp.verify_binding(chart, values, dict(request, serverImageDigest=OTHER)), 'package binding differs')
    refused(lambda: cp.verify_binding(chart, values, dict(request, platformVersion='2026.1.0-rc.4')),
            'package binding differs')
    refused(lambda: cp.verify_binding(chart, values, dict(request, sourceRevision='b' * 40)), 'package binding differs')

    digest = 'sha256:' + '8' * 64
    images = cp.rendered_images(rendered)
    sbom = cp.build_sbom(package, digest, request, images, now=datetime(2026, 10, 3, tzinfo=timezone.utc))
    assert sbom['bomFormat'] == 'CycloneDX' and sbom['metadata']['timestamp'] == '2026-10-03T00:00:00Z'
    assert sbom['metadata']['component']['hashes'][0]['content'] == hashlib.sha256(package).hexdigest()
    names = {component['name'] for component in sbom['components']}
    assert 'ghcr.io/honua-io/honua-server' in names
    for dependency in lock.get('dependencies') or []:
        assert dependency['name'] in names and vendored[dependency['name']]['version'] == str(dependency['version'])
    assert len(sbom['dependencies'][0]['dependsOn']) == len(sbom['components'])

    # A package whose Chart.lock names a subchart it does not vendor has no truthful SBOM.
    stripped = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(package), mode='r:gz') as source, \
            tarfile.open(fileobj=stripped, mode='w:gz') as target:
        for member in source.getmembers():
            if '/charts/' not in member.name:
                target.addfile(member, source.extractfile(member) if member.isfile() else None)
    if lock.get('dependencies'):
        refused(lambda: cp.build_sbom(stripped.getvalue(), digest, request, images), 'which the package does not vendor')

    receipt = cp.build_receipt(request, digest=digest, package_sha256='sha256:' + hashlib.sha256(package).hexdigest(),
                               architectures=['amd64', 'arm64'], platform_digests=platform_digests,
                               publication='pushed', run={'id': '1'}, verification=['cosign verify: signature'])
    assert receipt['format'] == 'honua.chart-publication/v1'
    assert receipt['platformManifest'] == {
        'sha': REVISION, 'artifact': 'oci-chart:honua', 'artifactVersion': '2026.1.0-rc.3', 'digest': digest,
        'architectures': ['amd64', 'arm64'], 'artifactSha256': 'sha256:' + hashlib.sha256(package).hexdigest(),
        'artifactSourceRevision': REVISION}
    assert receipt['chart']['reference'] == f'ghcr.io/honua-io/charts/honua@{digest}'
    assert receipt['signature']['identity'] == 'https://github.com/' + TRUNK
    assert receipt['serverImage']['platformDigests']['amd64'] == 'sha256:' + '4' * 64

# Each verifier must report a statement about this exact digest, not merely exit 0.
CHART = 'sha256:' + '9' * 64


def envelope(predicate, digest):
    statement = {'_type': 'https://in-toto.io/Statement/v0.1', 'predicateType': predicate,
                 'subject': [{'name': 'ghcr.io/honua-io/charts/honua', 'digest': {'sha256': digest.split(':', 1)[1]}}]}
    return json.dumps({'payloadType': 'application/vnd.in-toto+json', 'signatures': [{}],
                       'payload': cp.base64.b64encode(json.dumps(statement).encode()).decode()})


def signatures(*types, digest=CHART):
    return json.dumps([{'critical': {'type': kind, 'image': {'docker-manifest-digest': digest}}} for kind in types])


def provenance(digest=CHART, predicate=cp.PROVENANCE_PREDICATE):
    return json.dumps([{'verificationResult': {'statement': {
        'predicateType': predicate, 'subject': [{'digest': {'sha256': digest.split(':', 1)[1]}}]}}}])


sbom_lines = envelope(cp.SBOM_PREDICATE, CHART) + '\n'
good = (signatures('https://cyclonedx.org/bom', 'https://sigstore.dev/cosign/sign/v1'), sbom_lines, provenance())
assert len(cp.check_verification(*good, CHART)) == 3
assert cp.check_verification(signatures('cosign container image signature'), *good[1:], CHART)
# cosign 3 lists attestation bundles under `cosign verify` too; they are not a signature.
refused(lambda: cp.check_verification(signatures('https://cyclonedx.org/bom'), *good[1:], CHART), 'no signature over')
refused(lambda: cp.check_verification(signatures('https://sigstore.dev/cosign/sign/v1', digest=OTHER), *good[1:], CHART),
        'no signature over')
refused(lambda: cp.check_verification(good[0], envelope('https://spdx.dev/Document', CHART), good[2], CHART),
        'no CycloneDX statement')
refused(lambda: cp.check_verification(good[0], envelope(cp.SBOM_PREDICATE, OTHER), good[2], CHART),
        'no CycloneDX statement')
refused(lambda: cp.check_verification(*good[:2], provenance(digest=OTHER), CHART), 'no SLSA provenance')
refused(lambda: cp.check_verification(*good[:2], provenance(predicate='https://slsa.dev/provenance/v0.2'), CHART),
        'no SLSA provenance')

# Schedule: the candidate is the honua-release snapshot ref with the newest commit date.
with tempfile.TemporaryDirectory() as temp:
    remote = Path(temp) / 'release'
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')
    git = lambda *a, **k: subprocess.run(['git', '-C', str(remote), *a], check=True, capture_output=True,
                                         text=True, env=dict(env, **k)).stdout.strip()
    subprocess.run(['git', 'init', '--quiet', str(remote)], check=True)
    assert cp.newest_candidate(str(remote), str(Path(temp) / 'empty')) is None
    for label, date in (('2026.1-rc.5', '2026-10-02T11:15:00Z'), ('2026.1-rc.4', '2026-10-01T11:15:00Z')):
        (remote / 'platform-manifest.yaml').write_text(
            f'platformRelease: "{label}"\ncomponents:\n  honua-helm:\n    sha: "{REVISION}"\n')
        git('add', 'platform-manifest.yaml')
        git('commit', '--quiet', '--allow-empty', '-m', label, GIT_COMMITTER_DATE=date, GIT_AUTHOR_DATE=date)
        git('update-ref', f"refs/nightly-candidates/{git('rev-parse', 'HEAD')}", 'HEAD')
    newest = cp.newest_candidate(str(remote), str(Path(temp) / 'work'))
    assert newest['manifest']['platformRelease'] == '2026.1-rc.5', newest
    assert newest['ref'].startswith('refs/nightly-candidates/')

# Transient registry failures are retried; anything else surfaces at once.
calls, sleeps = [], []


def flaky():
    calls.append(1)
    if len(calls) < 3:
        raise cp.urllib.error.URLError('connection reset by peer')
    return 'ok'


assert cp._retry(flaky, sleep=sleeps.append) == 'ok' and sleeps == [10, 30]
calls.clear()


def denied():
    calls.append(1)
    raise cp.urllib.error.HTTPError('https://ghcr.io', 403, 'denied', {}, None)


try:
    cp._retry(denied, sleep=sleeps.append)
except cp.urllib.error.HTTPError:
    assert len(calls) == 1
else:
    raise AssertionError('a 403 is not transient')

# `resolve` as the workflow runs it. In a reusable workflow GITHUB_EVENT_NAME, GITHUB_REF and
# GITHUB_SHA are the caller's, so a call made from the caller's schedule, push or branch dispatch
# must still publish exactly its inputs; only the self-scheduled nightly reads a candidate.
def run_resolve(workdir, *, event, ref, run_workflow_ref, workflow_ref=TRUNK, inputs=None, candidate_file=None):
    names = ('GITHUB_EVENT_NAME', 'GITHUB_REF', 'GITHUB_SHA', 'GITHUB_WORKFLOW_REF', 'GITHUB_OUTPUT',
             *[f'INPUT_{key.upper()}' for key in ('server_image_digest', 'platform_version', 'chart_revision', 'proof')])
    saved = {name: os.environ.get(name) for name in names}
    saved_claims, saved_cwd = cp.oidc_claims, os.getcwd()
    out = Path(workdir) / 'request.json'
    try:
        for name in names:
            os.environ.pop(name, None)
        os.environ.update(GITHUB_EVENT_NAME=event, GITHUB_REF=ref, GITHUB_SHA='f' * 40,
                          GITHUB_WORKFLOW_REF=run_workflow_ref, GITHUB_OUTPUT=str(Path(workdir) / 'outputs'))
        for key, value in (inputs or {}).items():
            os.environ[f'INPUT_{key.upper()}'] = value
        cp.oidc_claims = lambda audience='sigstore': {'job_workflow_ref': workflow_ref, 'event_name': event}
        os.chdir(workdir)
        argv = ['resolve', '--out', str(out)] + (['--candidate', str(candidate_file)] if candidate_file else [])
        if cp.main(argv) != 0:
            return None
        return json.loads(out.read_text())
    finally:
        os.chdir(saved_cwd)
        cp.oidc_claims = saved_claims
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


with tempfile.TemporaryDirectory() as temp:
    helm = Path(temp) / 'helm'
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')
    subprocess.run(['git', 'init', '--quiet', str(helm)], check=True)
    subprocess.run(['git', '-C', str(helm), 'commit', '--quiet', '--allow-empty', '-m', 'trunk'], check=True, env=env)
    head = subprocess.run(['git', '-C', str(helm), 'rev-parse', 'HEAD'], check=True, capture_output=True,
                          text=True).stdout.strip()
    subprocess.run(['git', '-C', str(helm), 'update-ref', 'refs/remotes/origin/trunk', head], check=True)
    wanted = {'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.7', 'chart_revision': head}
    for event, ref in (('schedule', 'refs/heads/trunk'), ('push', 'refs/heads/trunk'),
                       ('workflow_dispatch', 'refs/heads/feat/caller'), ('workflow_call', 'refs/heads/trunk')):
        called = run_resolve(helm, event=event, ref=ref, run_workflow_ref=CALLER, inputs=wanted)
        assert called is not None, f'a call from a caller {event} run was refused'
        assert (called['mode'], called['serverImageDigest'], called['platformVersion'], called['sourceRevision']) == \
            ('inputs', SERVER, '2026.1.0-rc.7', head), (event, called)
        assert called['repository'] == 'ghcr.io/honua-io/charts/honua' and called['proof'] is False
        assert run_resolve(helm, event=event, ref=ref, run_workflow_ref=FOREIGN_CALLER, inputs=wanted) is None, \
            f'a call from another repository\'s {event} run was admitted'
    # A dispatch of this workflow on trunk (how another repository requests a publication) is admitted.
    dispatched = run_resolve(helm, event='workflow_dispatch', ref='refs/heads/trunk', run_workflow_ref=TRUNK,
                             inputs=wanted)
    assert (dispatched['mode'], dispatched['repository']) == ('inputs', 'ghcr.io/honua-io/charts/honua'), dispatched
    # Inputs without chart_revision publish the checked-out default-branch head.
    assert run_resolve(helm, event='schedule', ref='refs/heads/trunk', run_workflow_ref=CALLER,
                       inputs={'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.7'})['sourceRevision'] == head
    # A caller's schedule with no inputs is not this workflow's nightly: refused, no candidate read.
    candidate_file = Path(temp) / 'candidate.json'
    candidate_file.write_text(json.dumps(candidate(helm=head)))
    assert run_resolve(helm, event='schedule', ref='refs/heads/trunk', run_workflow_ref=CALLER,
                       candidate_file=candidate_file) is None
    # This workflow's own schedule (run and job workflow are the same file) publishes the candidate.
    own = run_resolve(helm, event='schedule', ref='refs/heads/trunk', run_workflow_ref=TRUNK,
                      candidate_file=candidate_file)
    assert (own['mode'], own['platformVersion'], own['sourceRevision']) == ('nightly-candidate', '2026.1.0-rc.4', head)
    # Malformed inputs are refused before anything is pushed.
    for bad in ({'server_image_digest': SERVER[:-1], 'platform_version': '2026.1.0-rc.7'},
                {'server_image_digest': SERVER, 'platform_version': '2026.1-rc.7'},
                {'server_image_digest': SERVER, 'platform_version': ''},
                {'server_image_digest': '', 'platform_version': '2026.1.0-rc.7'},
                {'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.7', 'chart_revision': 'HEAD'},
                {'server_image_digest': SERVER, 'platform_version': '2026.1.0-rc.7', 'chart_revision': 'b' * 40}):
        assert run_resolve(helm, event='workflow_call', ref='refs/heads/trunk', run_workflow_ref=CALLER,
                           inputs=bad) is None, bad
    # A caller pinned to anything but @trunk, or a revision off trunk, is refused.
    assert run_resolve(helm, event='workflow_call', ref='refs/heads/trunk', run_workflow_ref=CALLER,
                       workflow_ref=BRANCH, inputs=wanted) is None
    subprocess.run(['git', '-C', str(helm), 'commit', '--quiet', '--allow-empty', '-m', 'branch'], check=True, env=env)
    branch_head = subprocess.run(['git', '-C', str(helm), 'rev-parse', 'HEAD'], check=True, capture_output=True,
                                 text=True).stdout.strip()
    assert run_resolve(helm, event='workflow_call', ref='refs/heads/trunk', run_workflow_ref=CALLER,
                       inputs=dict(wanted, chart_revision=branch_head)) is None

# retry-transient.sh: a retried attempt sees the same stdin as the first (helm registry login
# --password-stdin), and only the successful attempt's stdout reaches the caller (the verify step
# redirects it into JSON files).
with tempfile.TemporaryDirectory() as temp:
    counter = Path(temp) / 'attempts'
    flaky_cmd = Path(temp) / 'flaky.sh'
    flaky_cmd.write_text(f'''#!/usr/bin/env bash
n=$(( $(cat {counter} 2>/dev/null || echo 0) + 1 )); echo "$n" > {counter}
stdin="$(cat)"
printf '{{"attempt":%s,' "$n"
if [[ "$n" -lt 2 ]]; then echo 'connection reset by peer' >&2; exit 1; fi
printf '"stdin":"%s"}}\\n' "$stdin"
''')
    flaky_cmd.chmod(0o755)
    wrapped = subprocess.run([str(ROOT / 'scripts/retry-transient.sh'), str(flaky_cmd)], input='s3cret',
                             capture_output=True, text=True, env=dict(os.environ, RETRY_TRANSIENT_DELAYS='0 0 0 0 0'))
    assert wrapped.returncode == 0, wrapped
    assert json.loads(wrapped.stdout) == {'attempt': 2, 'stdin': 's3cret'}, wrapped.stdout
    # A non-transient failure still returns at once, with its output.
    counter.unlink()
    failing = subprocess.run([str(ROOT / 'scripts/retry-transient.sh'), 'bash', '-c', 'echo out; echo denied >&2; exit 3'],
                             capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert (failing.returncode, failing.stdout) == (3, 'out\n') and 'denied' in failing.stderr, failing


# An existing version is recorded only when its pulled contents are exactly the chart this run built:
# matching Chart.yaml/values.yaml metadata is not enough, an extra template is refused.
def chart_tgz(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime = len(body), len(buffer.getvalue()) + len(name)  # differing metadata
            archive.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


built = {'honua/Chart.yaml': b'name: honua\n', 'honua/templates/deployment.yaml': b'kind: Deployment\n'}
cp.same_contents(chart_tgz(built), chart_tgz(dict(reversed(list(built.items())))))
refused(lambda: cp.same_contents(chart_tgz(dict(built, **{'honua/templates/job.yaml': b'kind: Job\n'})),
                                 chart_tgz(built)), 'honua/templates/job.yaml')
refused(lambda: cp.same_contents(chart_tgz(dict(built, **{'honua/templates/deployment.yaml': b'kind: Pod\n'})),
                                 chart_tgz(built)), 'honua/templates/deployment.yaml')

# SLSA provenance names the honua-helm revision the chart was built from, not only the run's
# GITHUB_SHA (the schedule's trunk tip, or a caller's commit in another repository).
generated = {'buildDefinition': {'buildType': 'https://actions.github.io/buildtypes/workflow/v1',
                                 'externalParameters': {'workflow': {'repository': 'https://github.com/honua-io/honua-release'}},
                                 'resolvedDependencies': [{'uri': 'git+https://github.com/honua-io/honua-release@refs/heads/trunk',
                                                           'digest': {'gitCommit': 'f' * 40}}]},
             'runDetails': {'builder': {'id': 'x'}}}
bound_predicate = cp.provenance_predicate(generated, resolve(source_revision=REVISION))
assert bound_predicate['buildDefinition']['resolvedDependencies'][0]['digest']['gitCommit'] == 'f' * 40
assert {'uri': f'git+{cp.SOURCE_REPOSITORY}', 'name': 'chart-source', 'digest': {'gitCommit': REVISION}} in \
    bound_predicate['buildDefinition']['resolvedDependencies']
assert bound_predicate['buildDefinition']['externalParameters']['chart']['sourceRevision'] == REVISION
refused(lambda: cp.provenance_predicate({}, resolve()), 'no buildDefinition')

assert os.path.exists(ROOT / '.github/workflows/chart-nightly.yml')
print('chart publication: OK')
