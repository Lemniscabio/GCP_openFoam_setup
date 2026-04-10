#!/usr/bin/env bash
set -euo pipefail

: "${BUCKET:?BUCKET is required}"
: "${CASE_ID:?CASE_ID is required}"
: "${VARIANT_ID:?VARIANT_ID is required}"
: "${JOB_NAME:?JOB_NAME is required}"

gcs_cp() {
  local src="$1"
  local dst="$2"
  local output=""

  echo "Copy ${src} -> ${dst}"
  if ! output="$(gcloud storage cp "${src}" "${dst}" 2>&1)"; then
    printf '%s\n' "${output}" >&2
    return 1
  fi
}

SCRATCH_ROOT="${SCRATCH_ROOT:-/mnt/disks/openfoam-scratch}"
if [[ ! -d "${SCRATCH_ROOT}" ]]; then
  SCRATCH_ROOT="/tmp/openfoam-scratch"
fi

CASE_PREFIX="gs://${BUCKET}/cases/${CASE_ID}"
RESULT_PREFIX="gs://${BUCKET}/results/${CASE_ID}/${VARIANT_ID}/${JOB_NAME}"
WORK_DIR="${SCRATCH_ROOT}/${CASE_ID}"
STAGE_DIR="${WORK_DIR}/stage"
CASE_DIR="${WORK_DIR}/case"

mkdir -p "${STAGE_DIR}" "${CASE_DIR}"

echo "Downloading case inputs from ${CASE_PREFIX}"
gcs_cp "${CASE_PREFIX}/case.tar.gz" "${STAGE_DIR}/case.tar.gz"
gcs_cp "${CASE_PREFIX}/command.sh" "${STAGE_DIR}/command.sh"
gcs_cp "${CASE_PREFIX}/manifest.json" "${STAGE_DIR}/manifest.json"

if gcloud storage ls "${CASE_PREFIX}/SHA256SUMS" >/dev/null 2>&1; then
  gcs_cp "${CASE_PREFIX}/SHA256SUMS" "${STAGE_DIR}/SHA256SUMS"
  (
    cd "${STAGE_DIR}"
    sha256sum -c SHA256SUMS
  )
fi

tar -xzf "${STAGE_DIR}/case.tar.gz" -C "${CASE_DIR}"
cp "${STAGE_DIR}/command.sh" "${CASE_DIR}/command.sh"
chmod +x "${CASE_DIR}/command.sh"

cat > "${STAGE_DIR}/runtime.json" <<EOF
{
  "case_id": "${CASE_ID}",
  "variant_id": "${VARIANT_ID}",
  "job_name": "${JOB_NAME}",
  "hostname": "$(hostname)",
  "started_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

cd "${CASE_DIR}"

set +e
bash ./command.sh 2>&1 | tee "${STAGE_DIR}/solver.stdout.log"
rc=${PIPESTATUS[0]}
set -e

printf '%s\n' "${rc}" > "${STAGE_DIR}/exit_code.txt"

tar -czf "${STAGE_DIR}/result.tar.gz" -C "${CASE_DIR}" .

gcs_cp "${STAGE_DIR}/manifest.json" "${RESULT_PREFIX}/manifest.json"
gcs_cp "${STAGE_DIR}/runtime.json" "${RESULT_PREFIX}/runtime.json"
gcs_cp "${STAGE_DIR}/solver.stdout.log" "${RESULT_PREFIX}/solver.stdout.log"
gcs_cp "${STAGE_DIR}/exit_code.txt" "${RESULT_PREFIX}/exit_code.txt"
gcs_cp "${STAGE_DIR}/result.tar.gz" "${RESULT_PREFIX}/result.tar.gz"

if [[ "${rc}" -eq 0 ]]; then
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_SUCCESS"
  gcs_cp "${STAGE_DIR}/_SUCCESS" "${RESULT_PREFIX}/_SUCCESS"
else
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_FAILED"
  gcs_cp "${STAGE_DIR}/_FAILED" "${RESULT_PREFIX}/_FAILED"
fi

exit "${rc}"
