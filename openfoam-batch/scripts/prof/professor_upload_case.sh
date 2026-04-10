#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "Usage: $0 CASE_ID|AUTO CASE_DIR COMMAND_SH [OPENFOAM_VERSION]" >&2
  exit 1
fi

# Edit this one line if the bucket changes.
GCS_BUCKET="openfoam_cases"

CASE_ID="$1"
CASE_DIR="$2"
COMMAND_SH="$3"
OPENFOAM_VERSION="${4:-12}"
BUCKET="${GCS_BUCKET}"

PREFIX="gs://${BUCKET}/cases/${CASE_ID}"
TMP_DIR="$(mktemp -d)"
ARCHIVE_PATH="${TMP_DIR}/case.tar.gz"
MANIFEST_PATH="${TMP_DIR}/manifest.json"
READY_PATH="${TMP_DIR}/READY"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

next_case_id() {
  local ready_list id n max
  ready_list="$(gcloud storage ls "gs://${BUCKET}/cases/*/READY" 2>/dev/null || true)"
  max=0

  while read -r obj; do
    [[ -z "${obj}" ]] && continue
    id="$(basename "$(dirname "${obj}")")"
    if [[ "${id}" =~ ^case_([0-9]+)$ ]]; then
      n=$((10#${BASH_REMATCH[1]}))
      if (( n > max )); then
        max="${n}"
      fi
    fi
  done <<< "${ready_list}"

  printf 'case_%04d\n' "$((max + 1))"
}

if [[ ! -d "${CASE_DIR}" ]]; then
  echo "Case directory not found: ${CASE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${COMMAND_SH}" ]]; then
  echo "command.sh not found: ${COMMAND_SH}" >&2
  exit 1
fi

if [[ "${CASE_ID}" == "AUTO" || "${CASE_ID}" == "auto" ]]; then
  CASE_ID="$(next_case_id)"
  PREFIX="gs://${BUCKET}/cases/${CASE_ID}"
  echo "Auto-assigned CASE_ID=${CASE_ID}"
fi

if gcloud storage ls "${PREFIX}/*" >/dev/null 2>&1; then
  echo "Case prefix already exists: ${PREFIX}" >&2
  echo "Use a new CASE_ID (or AUTO) to keep cases immutable." >&2
  exit 1
fi

tar -C "${CASE_DIR}" -czf "${ARCHIVE_PATH}" .
cp "${COMMAND_SH}" "${TMP_DIR}/command.sh"
chmod +x "${TMP_DIR}/command.sh"

cat > "${MANIFEST_PATH}" <<EOF
{
  "case_id": "${CASE_ID}",
  "solver_family": "openfoam",
  "openfoam_version": "${OPENFOAM_VERSION}",
  "case_archive": "case.tar.gz",
  "command_script": "command.sh",
  "uploaded_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

(
  cd "${TMP_DIR}"
  sha256sum case.tar.gz command.sh > SHA256SUMS
)

date -u +%Y-%m-%dT%H:%M:%SZ > "${READY_PATH}"

gcloud storage cp "${ARCHIVE_PATH}"     "${PREFIX}/case.tar.gz"
gcloud storage cp "${TMP_DIR}/command.sh"  "${PREFIX}/command.sh"
gcloud storage cp "${MANIFEST_PATH}"    "${PREFIX}/manifest.json"
gcloud storage cp "${TMP_DIR}/SHA256SUMS"  "${PREFIX}/SHA256SUMS"
gcloud storage cp "${READY_PATH}"       "${PREFIX}/READY"

echo "Uploaded case ${CASE_ID} to ${PREFIX}"
