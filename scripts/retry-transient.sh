#!/usr/bin/env bash
# Run a command and retry it only when it failed on a transient network error (about five minutes
# of backoff). Any other failure, such as a refused push or a failed verification, returns at once.
set -uo pipefail

delays=(10 30 60 120 90)
log="$(mktemp)"
trap 'rm -f "${log}"' EXIT
for attempt in 0 1 2 3 4 5; do
  "$@" 2>"${log}"
  status=$?
  cat "${log}" >&2
  if [[ "${status}" -eq 0 ]]; then
    exit 0
  fi
  if [[ "${attempt}" -eq 5 ]] || ! grep -qiE 'connection reset|could not resolve host|no such host|i/o timeout|tls handshake timeout|error connecting|connection refused|unexpected eof|502 bad gateway|503 service unavailable|504 gateway|too many requests' "${log}"; then
    exit "${status}"
  fi
  echo "transient failure (attempt $((attempt + 1))); retrying in ${delays[${attempt}]}s" >&2
  sleep "${delays[${attempt}]}"
done
