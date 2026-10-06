#!/usr/bin/env python3
"""Nightly chart publication by digest (ruling R31, honua-release#231 WI-6).

.github/workflows/chart-nightly.yml calls these subcommands. The workflow owns the order and the
registry writes (helm push, cosign); this file owns every decision that must fail closed: which
request is publishable, what the server image's platform set is, whether the bytes pulled back by
digest are the bytes packaged, and the receipt the release resolver reads.
docs/release/CHART-PUBLICATION.md describes the contract.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

import yaml

REGISTRY = 'ghcr.io'
CHART_NAME = 'honua'
RELEASE_NAMESPACE = 'honua-io/charts'
PROOF_NAMESPACE = 'honua-io/charts/honua-ci-proof'
SERVER_REPOSITORY = 'honua-io/honua-server'
SOURCE_REPOSITORY = 'https://github.com/honua-io/honua-helm'
WORKFLOW_PATH = 'honua-io/honua-helm/.github/workflows/chart-nightly.yml'
TRUNK_WORKFLOW_REF = f'{WORKFLOW_PATH}@refs/heads/trunk'
OIDC_ISSUER = 'https://token.actions.githubusercontent.com'
RECEIPT_FORMAT = 'honua.chart-publication/v1'
CHART_CONTENT = 'application/vnd.cncf.helm.chart.content.v1.tar+gzip'
CHART_CONFIG = 'application/vnd.cncf.helm.config.v1+json'
INDEX_TYPES = ('application/vnd.oci.image.index.v1+json',
               'application/vnd.docker.distribution.manifest.list.v2+json')
MANIFEST_TYPES = ('application/vnd.oci.image.manifest.v1+json',
                  'application/vnd.docker.distribution.manifest.v2+json')
ARCHITECTURES = ('amd64', 'arm64')  # platform-lock.v1 $defs/artifact/properties/architectures
DIGEST_RE = re.compile(r'sha256:[0-9a-f]{64}\Z')
REVISION_RE = re.compile(r'[0-9a-f]{40}\Z')
# R22: imaged components take the lock's platform version, 2026.1.0-rc.N (GA 2026.1.0).
PLATFORM_VERSION_RE = re.compile(r'\d{4}\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-rc\.(0|[1-9]\d*))?\Z')
# The nightly train's label (mint_nightly_lock.next_label): 2026.1-rc.N or 2026.1.Z-rc.N.
PLATFORM_LABEL_RE = re.compile(r'(\d{4}\.(?:0|[1-9]\d*))(\.(?:0|[1-9]\d*))?(-rc\.(?:0|[1-9]\d*))?\Z')
# Transient network failures are retried for up to about five minutes.
DELAYS = (0, 10, 30, 60, 120, 60)


class Refusal(Exception):
    """A request or artifact that must not be published or recorded."""


def platform_version_from_label(label):
    """`2026.1-rc.3` (the train's label) is chart version `2026.1.0-rc.3`; never invents a number."""
    match = PLATFORM_LABEL_RE.fullmatch(str(label or ''))
    if not match:
        raise Refusal(f'platformRelease {label!r} is not YYYY.N[.P][-rc.N]')
    return f"{match.group(1)}{match.group(2) or '.0'}{match.group(3) or ''}"


def require_platform_version(value):
    if not PLATFORM_VERSION_RE.fullmatch(str(value or '')):
        raise Refusal(f'platform_version {value!r} is not the R22 form YYYY.N.P[-rc.N], e.g. 2026.1.0-rc.3')
    return value


def require_digest(value, what='server_image_digest'):
    if not DIGEST_RE.fullmatch(str(value or '')):
        raise Refusal(f'{what} {value!r} is not sha256:<64 lowercase hex>')
    return value


def resolve_request(*, inputs, workflow_ref, run_workflow_ref, source_revision, on_trunk, candidate=None):
    """Decide what this run may publish, before anything is pushed.

    The mode comes from the inputs, never from the event name: in a reusable workflow
    `github.event_name`, `GITHUB_REF` and `GITHUB_SHA` are the caller's. A non-empty
    `server_image_digest` publishes exactly that request; no inputs at all is the self-scheduled
    nightly, which publishes the newest stamped candidate.

    `workflow_ref` is the OIDC `job_workflow_ref` claim: the identity Fulcio will put in the signing
    certificate. Only the trunk workflow may publish the release repository, so a branch dispatch,
    or a caller that pinned this reusable workflow to anything but @trunk, is refused here and not
    discovered after the push by a failing `cosign verify`. `run_workflow_ref` is `GITHUB_WORKFLOW_REF`,
    the top-level workflow of the run; it differs from `workflow_ref` exactly when this workflow was
    called, and a caller must always name what it publishes.
    """
    server_digest = str(inputs.get('server_image_digest') or '')
    version = str(inputs.get('platform_version') or '')
    chart_revision = str(inputs.get('chart_revision') or '')
    proof = str(inputs.get('proof', '')).lower() == 'true'
    called = run_workflow_ref != workflow_ref
    if server_digest:
        mode = 'inputs'
        if candidate is not None:
            raise Refusal('a request with server_image_digest publishes exactly that request, not a nightly candidate')
        if not version:
            raise Refusal('server_image_digest was given without platform_version')
    else:
        mode = 'nightly-candidate'
        if version or chart_revision:
            raise Refusal('platform_version or chart_revision was given without server_image_digest; '
                          'a request names the server image digest, the platform version and optionally the revision')
        if called:
            raise Refusal(f'{run_workflow_ref} called this workflow without server_image_digest and platform_version; '
                          'only the self-scheduled nightly publishes the newest stamped candidate')
        if candidate is None:
            raise Refusal('no honua-release nightly candidate is stamped (refs/nightly-candidates/*); '
                          'a scheduled run publishes only a stamped candidate and never invents a version')
        components = candidate['manifest'].get('components') or {}
        server, helm = components.get('honua-server') or {}, components.get('honua-helm') or {}
        image = str(server.get('image', ''))
        server_digest = server.get('digest') or (image.split('@', 1)[1] if '@' in image else '')
        if image and '@' in image and image.split('@', 1)[1] != server_digest:
            raise Refusal(f"candidate {candidate['ref']}: honua-server image {image} disagrees with digest {server_digest}")
        version = platform_version_from_label(candidate['manifest'].get('platformRelease'))
        chart_revision = str(helm.get('sha', ''))
        if chart_revision != source_revision:
            raise Refusal(f"candidate {candidate['ref']} pins honua-helm {chart_revision!r}, "
                          f'checked out {source_revision!r}')
    require_digest(server_digest)
    require_platform_version(version)
    if chart_revision and not REVISION_RE.fullmatch(chart_revision):
        raise Refusal(f'chart_revision {chart_revision!r} is not a 40-hex honua-helm commit')
    if not REVISION_RE.fullmatch(source_revision or ''):
        raise Refusal(f'source revision {source_revision!r} is not a 40-hex commit')
    if chart_revision and chart_revision != source_revision:
        raise Refusal(f'chart_revision {chart_revision} was requested but {source_revision} is checked out')
    if not str(workflow_ref).startswith(WORKFLOW_PATH + '@'):
        raise Refusal(f'job_workflow_ref {workflow_ref!r} is not {WORKFLOW_PATH}')
    if not proof and workflow_ref != TRUNK_WORKFLOW_REF:
        raise Refusal(f'only {TRUNK_WORKFLOW_REF} publishes the release repository; this run is '
                      f'{workflow_ref} (dispatch with proof=true to exercise a branch)')
    # The trunk workflow runs only trunk code with its identity, proof or not; a branch proof runs
    # the branch's own workflow and may package the branch.
    if workflow_ref == TRUNK_WORKFLOW_REF and not on_trunk:
        raise Refusal(f'source revision {source_revision} is not on honua-helm trunk')
    namespace = PROOF_NAMESPACE if proof else RELEASE_NAMESPACE
    return {
        'mode': mode,
        'proof': proof,
        'serverImageDigest': server_digest,
        'platformVersion': version,
        'sourceRevision': source_revision,
        'ociNamespace': namespace,
        'repository': f'{REGISTRY}/{namespace}/{CHART_NAME}',
        'signingIdentity': f'https://github.com/{workflow_ref}',
        'candidateRef': (candidate or {}).get('ref', ''),
    }


def oidc_claims(audience='sigstore'):
    """The claims of this job's own OIDC token (read for its identity; never verified or logged)."""
    url, token = os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL'), os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN')
    if not url or not token:
        raise Refusal('no OIDC token is available; the job needs permissions.id-token: write')
    request = urllib.request.Request(f'{url}&audience={audience}', headers={'Authorization': f'Bearer {token}'})
    jwt = json.loads(_retry(lambda: urllib.request.urlopen(request, timeout=30).read()))['value']
    payload = jwt.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))


def _transient(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (429, 500, 502, 503, 504)
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def _retry(action, sleep=time.sleep):
    for index, delay in enumerate(DELAYS):
        if delay:
            sleep(delay)
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - classified below
            if index == len(DELAYS) - 1 or not _transient(exc):
                raise
            print(f'transient registry failure, retrying: {exc}', file=sys.stderr)
    raise AssertionError('unreachable')


class Registry:
    """A minimal OCI distribution client: content is fetched by digest and re-hashed on arrival."""

    def __init__(self, repository, user=None, password=None):
        self.repository = repository
        query = urllib.parse.urlencode({'service': REGISTRY, 'scope': f'repository:{repository}:pull'})
        headers = {}
        if user and password:
            headers['Authorization'] = 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()
        request = urllib.request.Request(f'https://{REGISTRY}/token?{query}', headers=headers)
        self.token = json.loads(_retry(lambda: urllib.request.urlopen(request, timeout=30).read()))['token']

    def _open(self, path, accept=None, method='GET'):
        headers = {'Authorization': f'Bearer {self.token}'}
        if accept:
            headers['Accept'] = ', '.join(accept)
        request = urllib.request.Request(f'https://{REGISTRY}/v2/{self.repository}/{path}',
                                         headers=headers, method=method)
        return _retry(lambda: urllib.request.urlopen(request, timeout=120))

    def tag_digest(self, tag):
        """The digest a tag names, or None when the registry proves it absent (404)."""
        try:
            response = self._open(f'manifests/{tag}', INDEX_TYPES + MANIFEST_TYPES, method='HEAD')
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise Refusal(f'could not prove {self.repository}:{tag} absent (HTTP {exc.code})') from exc
        return require_digest(response.headers.get('Docker-Content-Digest'), f'{self.repository}:{tag} digest')

    def manifest(self, digest):
        response = self._open(f'manifests/{require_digest(digest, "manifest digest")}', INDEX_TYPES + MANIFEST_TYPES)
        body = response.read()
        actual = 'sha256:' + hashlib.sha256(body).hexdigest()
        if actual != digest:
            raise Refusal(f'{self.repository}@{digest} served a manifest hashing to {actual}')
        return json.loads(body)

    def blob(self, digest):
        body = self._open(f'blobs/{require_digest(digest, "blob digest")}').read()
        actual = 'sha256:' + hashlib.sha256(body).hexdigest()
        if actual != digest:
            raise Refusal(f'{self.repository} blob {digest} hashed to {actual}')
        return body


def architectures_from_index(document, config_for=None):
    """The linux platform set an image index serves, and each platform's manifest digest.

    Attestation manifests (`unknown/unknown`) are not platforms. A single-platform manifest is read
    through its config. An architecture outside the lock's enum is refused rather than dropped.
    """
    platform_digests = {}
    if document.get('mediaType') in INDEX_TYPES or 'manifests' in document:
        for entry in document.get('manifests') or []:
            platform = entry.get('platform') or {}
            if platform.get('os') == 'unknown' or (entry.get('annotations') or {}).get(
                    'vnd.docker.reference.type') == 'attestation-manifest':
                continue
            if platform.get('os') != 'linux':
                raise Refusal(f"server index serves non-linux platform {platform}")
            arch = platform.get('architecture')
            if arch not in ARCHITECTURES or arch in platform_digests:
                raise Refusal(f'server index platform {arch!r} is not exactly one of {ARCHITECTURES}')
            platform_digests[arch] = require_digest(entry.get('digest'), f'{arch} manifest digest')
    else:
        config = config_for(document['config']['digest']) if config_for else {}
        arch = config.get('architecture')
        if config.get('os') != 'linux' or arch not in ARCHITECTURES:
            raise Refusal(f"server image platform {config.get('os')}/{arch} is not linux/{ARCHITECTURES}")
        platform_digests[arch] = None
    if not platform_digests:
        raise Refusal('server image serves no linux platform')
    return sorted(platform_digests), platform_digests


def chart_layer(manifest):
    if (manifest.get('config') or {}).get('mediaType') != CHART_CONFIG:
        raise Refusal(f"manifest config {manifest.get('config')} is not a Helm chart config")
    layers = [layer for layer in manifest.get('layers') or [] if layer.get('mediaType') == CHART_CONTENT]
    if len(layers) != 1:
        raise Refusal(f'manifest carries {len(layers)} Helm chart content layers, expected exactly 1')
    return layers[0]['digest']


def read_package(package):
    """Chart.yaml, values.yaml, Chart.lock and the vendored subcharts of a packaged chart.

    Each subchart maps to its version and a content digest: the sha256 of an archived subchart, or
    for an unpacked one the sha256 over its sorted `path NUL sha256(file)` lines.
    """
    with tarfile.open(fileobj=io.BytesIO(package), mode='r:gz') as archive:
        files = {member.name: archive.extractfile(member).read() for member in archive.getmembers() if member.isfile()}
    for required in ('Chart.yaml', 'values.yaml'):
        if f'{CHART_NAME}/{required}' not in files:
            raise Refusal(f'package has no {CHART_NAME}/{required}')
    chart = yaml.safe_load(files[f'{CHART_NAME}/Chart.yaml'])
    values = yaml.safe_load(files[f'{CHART_NAME}/values.yaml'])
    lock = yaml.safe_load(files.get(f'{CHART_NAME}/Chart.lock', b'')) or {}
    vendored, unpacked = {}, {}
    prefix = f'{CHART_NAME}/charts/'
    for name, body in files.items():
        if not name.startswith(prefix):
            continue
        relative = name[len(prefix):]
        if '/' not in relative and relative.endswith('.tgz'):
            with tarfile.open(fileobj=io.BytesIO(body), mode='r:gz') as archive:
                inner = next(m for m in archive.getmembers() if m.name.count('/') == 1 and m.name.endswith('/Chart.yaml'))
                sub = yaml.safe_load(archive.extractfile(inner).read())
            vendored[sub['name']] = {'version': str(sub['version']), 'sha256': hashlib.sha256(body).hexdigest()}
        elif '/' in relative:
            unpacked.setdefault(relative.split('/', 1)[0], {})[relative] = body
    for directory, members in unpacked.items():
        if f'{directory}/Chart.yaml' not in members:
            continue
        sub = yaml.safe_load(members[f'{directory}/Chart.yaml'])
        listing = ''.join(f'{path}\0{hashlib.sha256(members[path]).hexdigest()}\n' for path in sorted(members))
        vendored[sub['name']] = {'version': str(sub['version']), 'sha256': hashlib.sha256(listing.encode()).hexdigest()}
    return chart, values, lock, vendored


def stamp(chart_dir, request):
    """Stamp version, appVersion and the server digest binding into a copy of the chart for packaging.

    Trunk's Chart.yaml is never edited: this runs on the job's checkout only. yq keeps the comments
    of the packaged values.yaml, which operators read.
    """
    env = dict(os.environ,
               VERSION=request['platformVersion'],
               DIGEST=request['serverImageDigest'],
               IMAGE=f"{REGISTRY}/{SERVER_REPOSITORY}@{request['serverImageDigest']}",
               REVISION=request['sourceRevision'])
    for path, expression in (
            ('Chart.yaml', '.version = strenv(VERSION) | .appVersion = strenv(VERSION)'
                           ' | .annotations."honua.io/server-image" = strenv(IMAGE)'
                           ' | .annotations."honua.io/server-image-digest" = strenv(DIGEST)'
                           ' | .annotations."honua.io/source-revision" = strenv(REVISION)'),
            ('values.yaml', '.image.repository = "ghcr.io/honua-io/honua-server" | .image.tag = ""'
                            ' | .image.digest = strenv(DIGEST) | .image.pullPolicy = "IfNotPresent"')):
        subprocess.run(['yq', '-i', expression, os.path.join(chart_dir, path)], check=True, env=env)


def binding(chart, values):
    annotations = chart.get('annotations') or {}
    image = values.get('image') or {}
    return {
        'version': str(chart.get('version')),
        'appVersion': str(chart.get('appVersion')),
        'serverImageDigest': annotations.get('honua.io/server-image-digest'),
        'serverImage': annotations.get('honua.io/server-image'),
        'sourceRevision': annotations.get('honua.io/source-revision'),
        'imageDigest': image.get('digest'),
        'imageTag': image.get('tag'),
        'imagePullPolicy': image.get('pullPolicy'),
        'imageRepository': image.get('repository'),
    }


def verify_binding(chart, values, expected):
    """The package names the requested version and binds appVersion to the exact server digest."""
    actual = binding(chart, values)
    server_image = f"{REGISTRY}/{SERVER_REPOSITORY}@{expected['serverImageDigest']}"
    wanted = {
        'version': expected['platformVersion'],
        'appVersion': expected['platformVersion'],
        'serverImageDigest': expected['serverImageDigest'],
        'serverImage': server_image,
        'sourceRevision': expected['sourceRevision'],
        'imageDigest': expected['serverImageDigest'],
        'imageTag': '',
        'imagePullPolicy': 'IfNotPresent',
        'imageRepository': f'{REGISTRY}/{SERVER_REPOSITORY}',
    }
    mismatched = {key: (actual.get(key), value) for key, value in wanted.items() if actual.get(key) != value}
    if mismatched:
        raise Refusal('package binding differs (actual, expected): ' + json.dumps(mismatched, sort_keys=True))
    return actual


def package_files(package):
    """Every member of a packaged chart: regular files by sha256 of their bytes, anything else by type.

    Tar and gzip metadata (mtimes, member order) are left out, so a re-packaging of the same chart
    compares equal and any added, removed or changed file does not.
    """
    members = {}
    with tarfile.open(fileobj=io.BytesIO(package), mode='r:gz') as archive:
        for member in archive.getmembers():
            if member.isfile():
                members[member.name] = 'sha256:' + hashlib.sha256(archive.extractfile(member).read()).hexdigest()
            elif not member.isdir():
                members[member.name] = f'type:{member.type!r}->{member.linkname}'
    return members


def same_contents(pulled, packaged):
    """The pulled chart holds exactly the files of the chart this run built, byte for byte."""
    actual, expected = package_files(pulled), package_files(packaged)
    differing = sorted(name for name in actual.keys() | expected.keys() if actual.get(name) != expected.get(name))
    if differing:
        raise Refusal('the published chart is not the chart this run built; differing members: ' + ', '.join(differing))


def provenance_predicate(predicate, request):
    """Bind the SLSA provenance GitHub generates to the honua-helm revision the chart was built from.

    actions/attest-build-provenance derives resolvedDependencies from the run's GITHUB_SHA: the
    scheduled trunk tip, or a caller's commit in another repository. That entry stays (it is the
    workflow that ran); the chart's source revision is added beside it and named in externalParameters.
    """
    definition = predicate.get('buildDefinition')
    if not isinstance(definition, dict):
        raise Refusal('the generated provenance predicate has no buildDefinition')
    bound = json.loads(json.dumps(predicate))
    definition = bound['buildDefinition']
    definition.setdefault('externalParameters', {})['chart'] = {
        'repository': request['repository'],
        'version': request['platformVersion'],
        'sourceRepository': SOURCE_REPOSITORY,
        'sourceRevision': request['sourceRevision'],
        'serverImageDigest': request['serverImageDigest'],
    }
    definition.setdefault('resolvedDependencies', []).append(
        {'uri': f'git+{SOURCE_REPOSITORY}', 'name': 'chart-source', 'digest': {'gitCommit': request['sourceRevision']}})
    return bound


def pull_and_verify(registry, digest, expected):
    """Pull the chart back by digest, re-hash every object, and check its binding."""
    manifest = registry.manifest(digest)
    package = registry.blob(chart_layer(manifest))
    chart, values, _, _ = read_package(package)
    verify_binding(chart, values, expected)
    return package


def rendered_images(text):
    images = set()
    for line in text.splitlines():
        match = re.match(r'\s*-?\s*image:\s*"?([^"\s]+)"?\s*$', line)
        if match:
            images.add(match.group(1))
    return sorted(images)


def _image_component(reference):
    """A CycloneDX container component for an image reference as the chart renders it."""
    name, _, digest = reference.partition('@')
    tag = ''
    if ':' in name.rsplit('/', 1)[-1]:
        name, tag = name.rsplit(':', 1)
    host = name.split('/', 1)[0]
    if '/' in name and ('.' in host or ':' in host or host == 'localhost'):
        repository = name
    else:
        repository = 'docker.io/' + (name if '/' in name else f'library/{name}')
    qualifiers = {'repository_url': repository}
    if tag:
        qualifiers['tag'] = tag
    version = digest or tag
    component = {
        'type': 'container', 'bom-ref': f'image:{reference}', 'name': repository, 'version': version,
        'purl': f"pkg:oci/{repository.rsplit('/', 1)[-1]}@{urllib.parse.quote(version, safe='')}?"
                + urllib.parse.urlencode(qualifiers),
    }
    if digest:
        component['hashes'] = [{'alg': 'SHA-256', 'content': digest.split(':', 1)[1]}]
    return component


def build_sbom(package, digest, request, images, now=None):
    """A CycloneDX 1.5 SBOM of the published chart: the chart, its vendored subcharts, the images it deploys."""
    chart, _, lock, vendored = read_package(package)
    version = str(chart['version'])
    package_sha = hashlib.sha256(package).hexdigest()
    chart_ref = f"{request['repository']}@{digest}"
    components, depends = [], []
    for dependency in lock.get('dependencies') or []:
        sub = vendored.get(dependency['name'])
        if not sub or sub['version'] != str(dependency['version']):
            raise Refusal(f"Chart.lock names {dependency['name']} {dependency['version']}, which the package does "
                          f'not vendor (vendored: {sub})')
        ref = f"chart:{dependency['name']}@{dependency['version']}"
        components.append({
            'type': 'application', 'bom-ref': ref, 'name': dependency['name'], 'version': str(dependency['version']),
            'purl': f"pkg:helm/{dependency['name']}@{dependency['version']}?"
                    + urllib.parse.urlencode({'repository_url': dependency['repository']}),
            'hashes': [{'alg': 'SHA-256', 'content': sub['sha256']}],
        })
        depends.append(ref)
    for image in images:
        component = _image_component(image)
        components.append(component)
        depends.append(component['bom-ref'])
    return {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.5',
        'serialNumber': f'urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, chart_ref)}',
        'version': 1,
        'metadata': {
            'timestamp': (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'tools': {'components': [{'type': 'application', 'name': 'honua-helm scripts/chart_publication.py'}]},
            'component': {
                'type': 'application', 'bom-ref': 'chart', 'name': CHART_NAME, 'version': version,
                'purl': f'pkg:oci/{CHART_NAME}@{urllib.parse.quote(digest, safe="")}?'
                        + urllib.parse.urlencode({'repository_url': request['repository'], 'tag': version}),
                'hashes': [{'alg': 'SHA-256', 'content': package_sha}],
                'externalReferences': [{'type': 'vcs', 'url': f"{SOURCE_REPOSITORY}/tree/{request['sourceRevision']}"}],
            },
        },
        'components': components,
        'dependencies': [{'ref': 'chart', 'dependsOn': depends}],
    }


SIGNATURE_TYPES = ('https://sigstore.dev/cosign/sign/v1', 'cosign container image signature')
SBOM_PREDICATE = 'https://cyclonedx.org/bom'
PROVENANCE_PREDICATE = 'https://slsa.dev/provenance/v1'


def _statement_names(statement, digest):
    return any((subject.get('digest') or {}).get('sha256') == digest.split(':', 1)[1]
               for subject in statement.get('subject') or [])


def check_verification(cosign_verify, cosign_verify_sbom, gh_attestation_verify, digest):
    """Exit 0 is not enough: each verifier must have reported a statement about this exact digest.

    cosign 3 lists every bundle that verifies for the identity, attestations included, so the plain
    signature is required by type. `cosign verify-attestation` prints one DSSE envelope per line.
    """
    signatures = json.loads(cosign_verify)
    if not any((item.get('critical') or {}).get('type') in SIGNATURE_TYPES
               and ((item.get('critical') or {}).get('image') or {}).get('docker-manifest-digest') == digest
               for item in signatures):
        raise Refusal(f'cosign verify reported no signature over {digest}')
    statements = [json.loads(base64.b64decode(json.loads(line)['payload']))
                  for line in cosign_verify_sbom.splitlines() if line.strip()]
    if not any(statement.get('predicateType') == SBOM_PREDICATE and _statement_names(statement, digest)
               for statement in statements):
        raise Refusal(f'cosign verify-attestation reported no CycloneDX statement about {digest}')
    attestations = json.loads(gh_attestation_verify)
    if not any(((item.get('verificationResult') or {}).get('statement') or {}).get('predicateType') == PROVENANCE_PREDICATE
               and _statement_names(item['verificationResult']['statement'], digest) for item in attestations):
        raise Refusal(f'gh attestation verify reported no SLSA provenance about {digest}')
    return ['cosign verify: signature', 'cosign verify-attestation: ' + SBOM_PREDICATE,
            'gh attestation verify: ' + PROVENANCE_PREDICATE]


def build_receipt(request, *, digest, package_sha256, architectures, platform_digests, publication, run, verification):
    """The record the release resolver reads; `platformManifest` uses the lock generator's field names."""
    return {
        'format': RECEIPT_FORMAT,
        'proof': request['proof'],
        'publication': publication,
        'chart': {
            'name': CHART_NAME,
            'repository': request['repository'],
            'reference': f"{request['repository']}@{digest}",
            'version': request['platformVersion'],
            'appVersion': request['platformVersion'],
            'digest': digest,
            'sha256': package_sha256,
            'architectures': architectures,
            'sourceRepository': SOURCE_REPOSITORY,
            'sourceRevision': request['sourceRevision'],
        },
        'serverImage': {
            'repository': f'{REGISTRY}/{SERVER_REPOSITORY}',
            'digest': request['serverImageDigest'],
            'architectures': architectures,
            'platformDigests': {arch: value for arch, value in platform_digests.items() if value},
        },
        'signature': {
            'keyless': True,
            'issuer': OIDC_ISSUER,
            'identity': request['signingIdentity'],
            'attestations': [SBOM_PREDICATE, PROVENANCE_PREDICATE],
            'verifiedBy': verification,
        },
        'mode': request['mode'],
        'candidateRef': request['candidateRef'],
        'run': run,
        'platformManifest': {
            'sha': request['sourceRevision'],
            'artifact': f'oci-chart:{CHART_NAME}',
            'artifactVersion': request['platformVersion'],
            'digest': digest,
            'architectures': architectures,
            'artifactSha256': package_sha256,
            'artifactSourceRevision': request['sourceRevision'],
        },
    }


def _write_outputs(values):
    path = os.environ.get('GITHUB_OUTPUT')
    lines = [f'{key}={value}' for key, value in values.items()]
    if path:
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


def _git(*args):
    for index, delay in enumerate(DELAYS):
        if delay:
            time.sleep(delay)
        result = subprocess.run(['git', *args], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        transient = any(term in result.stderr.lower() for term in (
            'could not resolve host', 'connection reset', 'timed out', 'error connecting', 'unable to access',
            'the remote end hung up', 'early eof', 'tls'))
        if index == len(DELAYS) - 1 or not transient:
            raise Refusal(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    raise AssertionError('unreachable')


def newest_candidate(remote, workdir):
    """The newest stamped honua-release nightly candidate snapshot, or None when none exists."""
    refs = [line.split('\t', 1)[1] for line in _git('ls-remote', remote, 'refs/nightly-candidates/*').splitlines() if line]
    if not refs:
        return None
    os.makedirs(workdir, exist_ok=True)
    _git('-C', workdir, 'init', '--quiet')
    _git('-C', workdir, 'fetch', '--quiet', '--depth=1', '--no-tags', remote,
         *[f'+{ref}:{ref}' for ref in refs])
    newest = _git('-C', workdir, 'for-each-ref', '--sort=-committerdate', '--count=1',
                  '--format=%(refname)', 'refs/nightly-candidates/').strip()
    manifest = yaml.safe_load(_git('-C', workdir, 'show', f'{newest}:platform-manifest.yaml'))
    return {'ref': newest, 'manifest': manifest}


def command_candidate(args):
    candidate = newest_candidate(args.remote, args.workdir)
    if candidate is None:
        raise Refusal('no honua-release nightly candidate is stamped (refs/nightly-candidates/*); nothing to publish')
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(candidate, handle, indent=2, sort_keys=True)
    helm = (candidate['manifest'].get('components') or {}).get('honua-helm') or {}
    _write_outputs({'candidate_ref': candidate['ref'], 'source_revision': helm.get('sha', '')})


def command_resolve(args):
    candidate = None
    if args.candidate:
        with open(args.candidate, encoding='utf-8') as handle:
            candidate = json.load(handle)
    inputs = {key: os.environ.get(f'INPUT_{key.upper()}', '') for key in
              ('server_image_digest', 'platform_version', 'chart_revision', 'proof')}
    head = _git('rev-parse', 'HEAD').strip()
    on_trunk = subprocess.run(['git', 'merge-base', '--is-ancestor', head, 'origin/trunk']).returncode == 0
    workflow_ref = oidc_claims().get('job_workflow_ref', '')
    request = resolve_request(inputs=inputs, workflow_ref=workflow_ref,
                              run_workflow_ref=os.environ.get('GITHUB_WORKFLOW_REF', ''),
                              source_revision=head, on_trunk=on_trunk, candidate=candidate)
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(request, handle, indent=2, sort_keys=True)
    _write_outputs({
        'mode': request['mode'],
        'proof': str(request['proof']).lower(),
        'server_image_digest': request['serverImageDigest'],
        'platform_version': request['platformVersion'],
        'source_revision': request['sourceRevision'],
        'oci_namespace': request['ociNamespace'],
        'repository': request['repository'],
        'signing_identity': request['signingIdentity'],
    })


def _load(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def _registry(repository):
    return Registry(repository, os.environ.get('GITHUB_ACTOR'), os.environ.get('GH_TOKEN'))


def command_stamp(args):
    stamp(args.chart, _load(args.request))


def command_inspect_server(args):
    request = _load(args.request)
    registry = _registry(SERVER_REPOSITORY)
    document = registry.manifest(request['serverImageDigest'])
    architectures, platform_digests = architectures_from_index(
        document, lambda digest: json.loads(registry.blob(digest)))
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump({'architectures': architectures, 'platformDigests': platform_digests}, handle, indent=2)
    _write_outputs({'architectures': json.dumps(architectures, separators=(',', ':'))})


def command_lookup(args):
    """Prove the version absent, or that an earlier run published exactly this binding."""
    request = _load(args.request)
    registry = _registry(request['repository'].split('/', 1)[1])
    digest = registry.tag_digest(request['platformVersion'])
    if digest is None:
        _write_outputs({'state': 'absent', 'digest': ''})
        return
    try:
        pull_and_verify(registry, digest, request)
    except Refusal as exc:
        raise Refusal(f"{request['repository']}:{request['platformVersion']} already exists at {digest} "
                      f'with a different binding; chart versions are immutable. {exc}') from exc
    _write_outputs({'state': 'existing', 'digest': digest})


def command_verify(args):
    """Pull by digest, re-hash, and compare with the chart this run packaged.

    A version this run pushed must be the packaged bytes. An existing version must hold exactly the
    packaged chart's files (tar metadata aside): matching Chart.yaml and values.yaml alone could hide
    an extra template, and this run must not sign or record bytes it did not build.
    """
    request = _load(args.request)
    registry = _registry(request['repository'].split('/', 1)[1])
    require_digest(args.digest, 'chart digest')
    tagged = registry.tag_digest(request['platformVersion'])
    if tagged != args.digest:
        raise Refusal(f"{request['repository']}:{request['platformVersion']} names {tagged}, not {args.digest}")
    package = pull_and_verify(registry, args.digest, request)
    pulled_sha = 'sha256:' + hashlib.sha256(package).hexdigest()
    with open(args.packaged, 'rb') as handle:
        packaged = handle.read()
    packaged_sha = 'sha256:' + hashlib.sha256(packaged).hexdigest()
    if args.publication == 'pushed' and packaged_sha != pulled_sha:
        raise Refusal(f'pulled package hashes to {pulled_sha}, packaged bytes to {packaged_sha}')
    same_contents(package, packaged)
    with open(args.out, 'wb') as handle:
        handle.write(package)
    _write_outputs({'sha256': pulled_sha})


def command_sbom(args):
    request = _load(args.request)
    with open(args.package, 'rb') as handle:
        package = handle.read()
    images = set()
    for path in args.rendered:
        with open(path, encoding='utf-8') as handle:
            images.update(rendered_images(handle.read()))
    server_image = f"{REGISTRY}/{SERVER_REPOSITORY}@{request['serverImageDigest']}"
    if server_image not in images:
        raise Refusal(f'the packaged chart does not render {server_image}; rendered {sorted(images)}')
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(build_sbom(package, args.digest, request, sorted(images)), handle, indent=2)


def command_provenance_predicate(args):
    with open(args.predicate, encoding='utf-8') as handle:
        predicate = json.load(handle)
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(provenance_predicate(predicate, _load(args.request)), handle, sort_keys=True)


def command_receipt(args):
    request = _load(args.request)
    server = _load(args.server)
    texts = []
    for path in (args.cosign_verify, args.cosign_verify_sbom, args.gh_attestation_verify):
        with open(path, encoding='utf-8') as handle:
            texts.append(handle.read())
    verification = check_verification(*texts, require_digest(args.digest, 'chart digest'))
    run = {
        'repository': os.environ.get('GITHUB_REPOSITORY'),
        'id': os.environ.get('GITHUB_RUN_ID'),
        'attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'event': os.environ.get('GITHUB_EVENT_NAME'),  # the top-level run's event: a caller's when called
        'runWorkflowRef': os.environ.get('GITHUB_WORKFLOW_REF'),
        'url': f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}",
        'workflowRef': request['signingIdentity'].removeprefix('https://github.com/'),
    }
    receipt = build_receipt(request, digest=require_digest(args.digest, 'chart digest'),
                            package_sha256=require_digest(args.sha256, 'package sha256'),
                            architectures=server['architectures'], platform_digests=server['platformDigests'],
                            publication=args.publication, run=run, verification=verification)
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps(receipt['platformManifest'], indent=2, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    candidate = sub.add_parser('candidate')
    candidate.add_argument('--remote', default='https://github.com/honua-io/honua-release')
    candidate.add_argument('--workdir', required=True)
    candidate.add_argument('--out', required=True)
    candidate.set_defaults(func=command_candidate)
    resolve = sub.add_parser('resolve')
    resolve.add_argument('--candidate')
    resolve.add_argument('--out', required=True)
    resolve.set_defaults(func=command_resolve)
    stamp_parser = sub.add_parser('stamp')
    stamp_parser.add_argument('--request', required=True)
    stamp_parser.add_argument('--chart', required=True)
    stamp_parser.set_defaults(func=command_stamp)
    inspect = sub.add_parser('inspect-server')
    inspect.add_argument('--request', required=True)
    inspect.add_argument('--out', required=True)
    inspect.set_defaults(func=command_inspect_server)
    lookup = sub.add_parser('lookup')
    lookup.add_argument('--request', required=True)
    lookup.set_defaults(func=command_lookup)
    verify = sub.add_parser('verify')
    verify.add_argument('--request', required=True)
    verify.add_argument('--digest', required=True)
    verify.add_argument('--packaged', required=True)
    verify.add_argument('--publication', choices=('pushed', 'existing'), required=True)
    verify.add_argument('--out', required=True)
    verify.set_defaults(func=command_verify)
    sbom = sub.add_parser('sbom')
    sbom.add_argument('--request', required=True)
    sbom.add_argument('--package', required=True)
    sbom.add_argument('--digest', required=True)
    sbom.add_argument('--rendered', nargs='+', required=True)
    sbom.add_argument('--out', required=True)
    sbom.set_defaults(func=command_sbom)
    predicate = sub.add_parser('provenance-predicate')
    predicate.add_argument('--request', required=True)
    predicate.add_argument('--predicate', required=True)
    predicate.add_argument('--out', required=True)
    predicate.set_defaults(func=command_provenance_predicate)
    receipt = sub.add_parser('receipt')
    receipt.add_argument('--request', required=True)
    receipt.add_argument('--server', required=True)
    receipt.add_argument('--digest', required=True)
    receipt.add_argument('--sha256', required=True)
    receipt.add_argument('--publication', choices=('pushed', 'existing'), required=True)
    receipt.add_argument('--cosign-verify', required=True)
    receipt.add_argument('--cosign-verify-sbom', required=True)
    receipt.add_argument('--gh-attestation-verify', required=True)
    receipt.add_argument('--out', required=True)
    receipt.set_defaults(func=command_receipt)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Refusal as exc:
        print(f'::error::{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
