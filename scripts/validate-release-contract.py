"""Fail closed when Helm publication loses its immutable/public gates."""

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = {
        "GitHub-verified signed tag": ".verification.verified",
        "existing-version rejection": "Refuse an existing OCI chart version",
        "absence must be proven": "Could not prove OCI chart version",
        "provenance attestation": "actions/attest-build-provenance@v3",
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
    if missing or present:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if present:
            details.append("forbidden: " + ", ".join(present))
        raise SystemExit("Helm release contract failed (" + "; ".join(details) + ")")
    print("Helm release contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
