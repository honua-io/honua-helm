"""Fail when Helm Release uses a context GitHub rejects before any job starts.

honua-helm#72: every run of .github/workflows/release.yml completed failure
with zero jobs. The workflow file set HELM_REGISTRY_CONFIG from ${{ runner.temp }}
in the verify-public job env. The runner context does not exist at job scope, so
GitHub reports "Unrecognized named-value: 'runner'" and never creates a job.
The value belongs on the pull step, which is where trunk keeps it.

Job-level expressions may use github, inputs, vars, needs, secrets, strategy,
and matrix. Job outputs may also use steps. runner, job, and env are step-scoped,
and steps is not available outside outputs.
https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability
"""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / ".github" / "workflows" / "release.yml"

JOB_CONTEXTS = {"github", "inputs", "vars", "needs", "secrets", "strategy", "matrix"}
OUTPUT_CONTEXTS = JOB_CONTEXTS | {"steps"}
FUNCTIONS = {
    "always",
    "cancelled",
    "contains",
    "endsWith",
    "failure",
    "format",
    "fromJSON",
    "hashFiles",
    "join",
    "startsWith",
    "success",
    "toJSON",
}
EXPRS = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
SKIP_KEYS = {"steps", "container", "services"}

# The expression GitHub rejected on every release.yml run before it was moved
# onto the anonymous pull step.
HISTORICAL_JOB_ENV = """
name: Helm Release
on:
  push:
    tags: ['chart-v*']
jobs:
  verify-public:
    runs-on: ubuntu-latest
    env:
      HELM_REGISTRY_CONFIG: ${{ runner.temp }}/anonymous-registry-config.json
    steps:
      - run: echo ok
"""

JOB_LEVEL_IF = """
name: Helm Release
on: workflow_dispatch
jobs:
  release:
    if: ${{ runner.os == 'Linux' }}
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""


def contexts(expression):
    """Context names an expression reads. Property tails, including hyphens, are not contexts."""
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", " ", expression)
    found = set()
    for part in re.split(r"[^A-Za-z0-9_.-]+", stripped):
        if not part:
            continue
        head = part.split(".", 1)[0]
        if head in FUNCTIONS or head in {"true", "false", "null"}:
            continue
        found.add(head)
    return found


def _walk(node, path, found):
    if isinstance(node, dict):
        for key, value in node.items():
            if path == () and key == "on":
                continue
            if key in SKIP_KEYS:
                continue
            _walk(value, path + (str(key),), found)
        return
    if isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, path + (str(index),), found)
        return
    if isinstance(node, str):
        found.append((path, node))


def startup_errors(document):
    """Expressions that make GitHub fail the workflow at startup, with zero jobs."""
    found = []
    _walk(document, (), found)
    errors = []
    for path, text in found:
        allowed = OUTPUT_CONTEXTS if "outputs" in path else JOB_CONTEXTS
        for expression in EXPRS.findall(text):
            illegal = sorted(contexts(expression) - allowed)
            if illegal:
                where = ".".join(path) or "<root>"
                errors.append(f"{where}: {', '.join(illegal)} in ${{{{{expression}}}}}")
    return errors


def main():
    text = RELEASE.read_text(encoding="utf-8")
    marker = "HELM_REGISTRY_CONFIG: ${{ runner.temp }}/anonymous-registry-config.json"
    if marker not in text:
        raise SystemExit("release.yml no longer pins the anonymous Helm config to runner.temp")
    # The historical failure was this line at job-env indent (6 spaces). Step env is deeper.
    for line in text.splitlines():
        if marker in line and (len(line) - len(line.lstrip(" "))) < 10:
            raise SystemExit("HELM_REGISTRY_CONFIG uses runner.temp above step scope: " + line.strip())

    errors = startup_errors(yaml.safe_load(text))
    if errors:
        raise SystemExit("release.yml still cannot start:\n" + "\n".join(errors))

    historical = startup_errors(yaml.safe_load(HISTORICAL_JOB_ENV))
    if not any("runner" in error and "verify-public.env" in error for error in historical):
        raise SystemExit(f"historical job env was not rejected: {historical}")
    job_if = startup_errors(yaml.safe_load(JOB_LEVEL_IF))
    if not any("runner" in error and error.startswith("jobs.release.if") for error in job_if):
        raise SystemExit(f"job-level if was not rejected: {job_if}")
    print("Helm Release startup expressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
