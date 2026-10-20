ci: document the lint job's checkout pin

## Summary

All workflow-fixable Scorecard findings in this repo are already closed. Trunk 7b0ed89 (2026-10-20) has 0 Dependabot alerts and only the repo-policy Scorecard checks open (BranchProtection, CodeReview, CII-Best-Practices). TokenPermissions, SAST and Fuzzing are no longer reported. The org pin checker (honua-release `tools/check_action_pins.py`) still rejected one pin.

## Changes Made

- `ci.yml`: the checkout pin had no version comment. It now has `# v7.0.1`, the label every other use of that SHA in this repo carries. No SHA changes.

## Breaking Changes

None.

## Testing

- honua-release `tools/check_action_pins.py` (trunk 4642e4d, with the reusable-workflow reachability check enabled) passes on all workflows. It failed on `ci.yml:25` before this change.
- actionlint 1.7.12 passes.
- `git diff --check` passes.

No alert was dismissed.
