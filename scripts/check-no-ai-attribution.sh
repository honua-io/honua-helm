#!/usr/bin/env bash
#
# Reject AI/agent attribution in commit messages.
#
# AGENTS.md requires every commit (and PR body) to be authored as the repo owner
# only: no AI/agent co-author trailers (e.g. "Co-Authored-By: Claude ...",
# "Co-Authored-By: Codex ..."), no "Generated with ..." attribution lines, and no
# robot emoji. This script is the enforcement point invoked by CI
# (.github/workflows/commit-policy.yml) and can also be wired as a local
# commit-msg hook.
#
# Usage:
#   scripts/check-no-ai-attribution.sh                      # scan origin/trunk..HEAD
#   scripts/check-no-ai-attribution.sh --range <revrange>   # scan a commit range
#   scripts/check-no-ai-attribution.sh --message-file <path># scan one message file
#                                                           # (for a commit-msg hook)
#
# Dependabot and GitHub Actions bot co-authors are intentionally allowed; the
# policy targets AI coding-assistant attribution, not accepted CI automation.
set -euo pipefail

# Co-Authored-By trailers naming an AI coding assistant or AI vendor.
AI_COAUTHOR='[Cc]o-[Aa]uthored-[Bb]y:.*(Claude|Codex|Copilot|ChatGPT|GPT-|Anthropic|OpenAI|Cursor|Devin|Gemini|Sourcegraph|Tabnine|noreply@anthropic\.com)'
# Any "[bot]" co-author other than the automation we explicitly accept.
BOT_COAUTHOR='[Cc]o-[Aa]uthored-[Bb]y:.*\[bot\]'
ALLOWED_BOTS='dependabot\[bot\]|github-actions\[bot\]'
# "Generated with ..." attribution lines.
GENERATED='[Gg]enerated with'
# Robot emoji (U+1F916), expressed as bytes so this file stays ASCII.
ROBOT=$'\xf0\x9f\xa4\x96'

# Inspect a single commit message (passed on stdin). Echoes a reason and returns
# 1 when forbidden attribution is found; returns 0 when clean.
scan_message() {
  local msg reason="" coauthors line
  msg="$(cat)"

  if printf '%s\n' "$msg" | grep -qE "$AI_COAUTHOR"; then
    reason="AI co-author trailer"
  elif printf '%s\n' "$msg" | grep -qE "$GENERATED"; then
    reason='"Generated with" attribution line'
  elif printf '%s\n' "$msg" | grep -qF "$ROBOT"; then
    reason="robot emoji"
  else
    coauthors="$(printf '%s\n' "$msg" | grep -iE '^co-authored-by:' || true)"
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      if printf '%s' "$line" | grep -qE "$BOT_COAUTHOR" \
        && ! printf '%s' "$line" | grep -qE "$ALLOWED_BOTS"; then
        reason="disallowed bot co-author"
        break
      fi
    done <<EOF
$coauthors
EOF
  fi

  if [ -n "$reason" ]; then
    printf '%s' "$reason"
    return 1
  fi
  return 0
}

mode="range"
arg="origin/trunk..HEAD"
case "${1:-}" in
  --message-file)
    mode="file"; arg="${2:?--message-file requires a path}" ;;
  --range)
    mode="range"; arg="${2:?--range requires a rev-range}" ;;
  "" )
    : ;;
  -h|--help)
    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  * )
    echo "unknown argument: $1" >&2; exit 2 ;;
esac

status=0

if [ "$mode" = "file" ]; then
  if reason="$(scan_message <"$arg")"; then
    echo "Commit message is free of AI/agent attribution."
  else
    echo "error: commit message contains forbidden attribution (${reason})." >&2
    echo "AGENTS.md: author as the repo owner only, with no AI/agent attribution." >&2
    status=1
  fi
  exit "$status"
fi

# Range mode: scan every commit in the range.
commits="$(git rev-list "$arg")"
if [ -z "$commits" ]; then
  echo "No commits to check in range '${arg}'."
  exit 0
fi

while IFS= read -r commit; do
  [ -n "$commit" ] || continue
  if reason="$(git show -s --format='%B' "$commit" | scan_message)"; then
    continue
  fi
  echo "::error::commit ${commit} contains forbidden attribution (${reason})." >&2
  git show -s --format='  %h %s' "$commit" >&2
  status=1
done <<EOF
$commits
EOF

if [ "$status" -ne 0 ]; then
  echo "" >&2
  echo "Forbidden AI/agent attribution found (see above). AGENTS.md requires" >&2
  echo "commits to be authored as the repo owner only, with no AI/agent" >&2
  echo "co-authors, no \"Generated with ...\" lines, and no robot emoji." >&2
  exit 1
fi

echo "Commit messages in '${arg}' are free of AI/agent attribution."
