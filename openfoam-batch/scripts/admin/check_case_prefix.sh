#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 CASE_ID" >&2
  exit 1
fi

# Edit this one line if the bucket changes.
GCS_BUCKET="openfoam_cases"

CASE_ID="$1"
BUCKET="${GCS_BUCKET}"
PREFIX="gs://${BUCKET}/cases/${CASE_ID}"

required=(
  "case.tar.gz"
  "command.sh"
  "manifest.json"
  "READY"
)

missing=0
for name in "${required[@]}"; do
  if ! gcloud storage ls "${PREFIX}/${name}" >/dev/null 2>&1; then
    echo "MISSING ${PREFIX}/${name}"
    missing=1
  else
    echo "FOUND   ${PREFIX}/${name}"
  fi
done

if gcloud storage ls "${PREFIX}/SHA256SUMS" >/dev/null 2>&1; then
  echo "FOUND   ${PREFIX}/SHA256SUMS"
else
  echo "WARN    ${PREFIX}/SHA256SUMS not found"
fi

exit "${missing}"
