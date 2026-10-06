"""Fail closed when Helm publication loses its immutable/public gates.

release.yml is the tag-triggered cut. chart-nightly.yml is the nightly publication by digest
(ruling R31): keyless signing only, one immutable version tag, verification by digest.
"""

import re
from pathlib import Path


WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "release.yml"
NIGHTLY = WORKFLOWS / "chart-nightly.yml"

NIGHTLY_REQUIRED = {
    "keyless OIDC identity": "id-token: write",
    "authorization before push": "chart_publication.py resolve",
    "absence or same binding proven": "chart_publication.py lookup",
    "push only when absent": "if: steps.lookup.outputs.state == 'absent'",
    "pull by digest and re-hash": "chart_publication.py verify",
    "keyless signature": "cosign sign --yes",
    "SBOM attestation": "cosign attest --yes --type cyclonedx",
    "provenance predicate": "actions/attest-build-provenance/predicate@977bb373ede98d70efdf65b84cb5f73e068dcc2a # v3.0.0",
    "provenance bound to the source revision": "chart_publication.py provenance-predicate",
    "provenance attestation": "actions/attest@daf44fb950173508f38bd2406030372c1d1162b1 # v3.0.0",
    "provenance in the registry": "push-to-registry: true",
    "exact provenance identity": '--cert-identity "${IDENTITY}"',
    "exact signing identity": '--certificate-identity "${IDENTITY}"',
    "signature verification": "cosign verify ",
    "receipt": "chart_publication.py receipt",
    "proof cleanup": "name: Delete the throwaway proof package",
}
NIGHTLY_FORBIDDEN = {
    "signing key": "--key",
    "signing key secret": "COSIGN_PRIVATE_KEY",
    "signing key password": "COSIGN_PASSWORD",
    "mutable duplicate bypass": "--skip-duplicate",
    "floating tag": "oras tag",
    "channel tag copy": "imagetools create",
    "branch registration trigger": "TEMPORARY",
}


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = {
        "GitHub-verified signed tag": ".verification.verified",
        "existing-version rejection": "Refuse an existing OCI chart version",
        "absence must be proven": "Could not prove OCI chart version",
        "provenance attestation": "actions/attest-build-provenance@977bb373ede98d70efdf65b84cb5f73e068dcc2a # v3.0.0",
        "anonymous Helm config": "HELM_REGISTRY_CONFIG: ${{ runner.temp }}/anonymous-registry-config.json",
        "anonymous pull job": "name: Verify anonymous OCI pull",
        "byte equality": "sha256sum --check",
        "release waits for public proof": "needs: [package-and-publish, verify-public]",
        "release verifies tag": "--verify-tag",
    }
    missing = [name for name, marker in required.items() if marker not in text]
    forbidden = {
        "manual publish input": "inputs.publish",
        "manual-or-tag publish condition": "github.event_name == 'push' ||",
        "mutable duplicate bypass": "--skip-duplicate",
    }
    present = [name for name, marker in forbidden.items() if marker in text]
    unpinned_actions = [
        line.strip()
        for line in text.splitlines()
        if "uses:" in line and not re.search(r"@[0-9a-f]{40}\s+#\s+v\S+$", line)
    ]
    nightly = NIGHTLY.read_text(encoding="utf-8")
    missing += ["chart-nightly.yml " + name for name, marker in NIGHTLY_REQUIRED.items() if marker not in nightly]
    present += ["chart-nightly.yml " + name for name, marker in NIGHTLY_FORBIDDEN.items() if marker in nightly]
    unpinned_actions += [
        line.strip()
        for line in nightly.splitlines()
        if re.match(r"\s*(-\s+)?uses:", line) and not re.search(r"@[0-9a-f]{40}\s+#\s+v\S+$", line)
    ]
    if missing or present or unpinned_actions:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if present:
            details.append("forbidden: " + ", ".join(present))
        if unpinned_actions:
            details.append("unpinned actions: " + ", ".join(unpinned_actions))
        raise SystemExit("Helm release contract failed (" + "; ".join(details) + ")")
    print("Helm release contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
