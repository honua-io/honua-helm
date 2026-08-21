"""Fail closed when Helm publication loses its immutable/public gates."""

import re
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml"


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
