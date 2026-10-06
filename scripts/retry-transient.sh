#!/usr/bin/env bash
# Run a command and retry it only when it failed on a transient network error (about five minutes
# of backoff). Any other failure, such as a refused push or a failed verification, returns at once.
#
# Every attempt sees the same stdin (buffered once, so `--password-stdin` survives a retry), and only
# the final attempt's stdout reaches the caller, so a redirect into a JSON file never holds the
# partial output of a failed attempt. Failed attempts' stdout goes to stderr for the log.
set -uo pipefail

read -r -a delays <<< "${RETRY_TRANSIENT_DELAYS:-10 30 60 120 90}"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
if [[ -t 0 ]]; then
  : > "${work}/stdin"
else
  cat > "${work}/stdin"
fi
last="${#delays[@]}"
for (( attempt = 0; attempt <= last; attempt++ )); do
  "$@" < "${work}/stdin" > "${work}/stdout" 2> "${work}/stderr"
  status=$?
  cat "${work}/stderr" >&2
  if [[ "${status}" -eq 0 ]]; then
    cat "${work}/stdout"
    exit 0
  fi
  if [[ "${attempt}" -eq "${last}" ]] || ! grep -qiE 'connection reset|could not resolve host|no such host|i/o timeout|tls handshake timeout|error connecting|connection refused|unexpected eof|502 bad gateway|503 service unavailable|504 gateway|too many requests' "${work}/stderr"; then
    cat "${work}/stdout"
    exit "${status}"
  fi
  cat "${work}/stdout" >&2
  echo "transient failure (attempt $((attempt + 1))); retrying in ${delays[${attempt}]}s" >&2
  sleep "${delays[${attempt}]}"
done
