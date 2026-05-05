#!/usr/bin/env bash
set -euo pipefail

: "${BUCKET:?BUCKET is required}"
if [[ -n "${CASE_ID_LIST:-}" ]]; then
  IFS=',' read -ra _CASE_LIST <<< "${CASE_ID_LIST}"
  _IDX="${BATCH_TASK_INDEX:-0}"
  CASE_ID="${_CASE_LIST[${_IDX}]:-}"
  if [[ -z "${CASE_ID}" ]]; then
    echo "CASE_ID_LIST set but BATCH_TASK_INDEX=${_IDX} is out of bounds" >&2
    exit 64
  fi
fi
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
  echo "SCRATCH_ROOT=${SCRATCH_ROOT} does not exist; submit script must mount a scratch volume" >&2
  exit 64
fi

CASE_PREFIX="gs://${BUCKET}/cases/${CASE_ID}"
TASK_INDEX="${BATCH_TASK_INDEX:-0}"
RESULT_PREFIX="gs://${BUCKET}/results/${CASE_ID}/${VARIANT_ID}/${JOB_NAME}/task_${TASK_INDEX}"
WORK_DIR="${SCRATCH_ROOT}/${CASE_ID}"
STAGE_DIR="${WORK_DIR}/stage"
CASE_DIR="${WORK_DIR}/case"

mkdir -p "${STAGE_DIR}" "${CASE_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"

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

CHECKPOINT_PREFIX="gs://${BUCKET}/checkpoints/${CASE_ID}/${VARIANT_ID}/latest"
RESUME=0
if gcloud storage ls "${CHECKPOINT_PREFIX}/" >/dev/null 2>&1; then
  RESUME=1
fi

if [[ "${RESUME}" == "1" ]]; then
  echo "Resuming from checkpoint ${CHECKPOINT_PREFIX}"
  gcloud storage rsync --recursive "${CHECKPOINT_PREFIX}/" "${CASE_DIR}/" || true
  if command -v foamDictionary >/dev/null 2>&1; then
    foamDictionary "${CASE_DIR}/system/controlDict" -entry startFrom -set latestTime || true
  fi
fi

CHECKPOINT_POLL_SEC="${CHECKPOINT_POLL_SEC:-30}"

checkpoint_loop() {
  local last_seen=""
  while true; do
    sleep "${CHECKPOINT_POLL_SEC}"
    local newest
    newest=$(ls -1 "${CASE_DIR}/processor0" 2>/dev/null \
             | grep -E '^[0-9]+(\.[0-9]+)?$' \
             | sort -n | tail -1)
    if [[ -n "${newest}" && "${newest}" != "${last_seen}" ]]; then
      gcloud storage rsync --recursive \
        "${CASE_DIR}/processor*" \
        "${CHECKPOINT_PREFIX}/" || true
      gcloud storage rsync --recursive \
        "${CASE_DIR}/system" \
        "${CHECKPOINT_PREFIX}/system/" || true
      last_seen="${newest}"
    fi
  done
}

on_sigterm() {
  trap '' TERM INT
  if [[ -n "${SOLVER_PGID:-}" ]]; then
    kill -TERM -"${SOLVER_PGID}" 2>/dev/null || true
    wait "${SOLVER_PID:-0}" 2>/dev/null || true
  fi
  if [[ -n "${CHECKPOINT_PID:-}" ]]; then
    kill "${CHECKPOINT_PID}" 2>/dev/null || true
  fi
  gcloud storage rsync --recursive \
    "${CASE_DIR}/processor*" \
    "${CHECKPOINT_PREFIX}/" || true
  gcloud storage rsync --recursive \
    "${CASE_DIR}/system" \
    "${CHECKPOINT_PREFIX}/system/" || true
  cat > "${STAGE_DIR}/preempted.json" <<EOF2
  {
    "job_name": "${JOB_NAME}",
    "task_index": "${BATCH_TASK_INDEX:-0}",
    "attempt_ts": "${RUN_TS}",
    "reason": "preempted"
  }
EOF2
  gcloud storage cp "${STAGE_DIR}/preempted.json" \
    "${CHECKPOINT_PREFIX}/preempted.json" || true
  if [[ -f "${STAGE_DIR}/solver.stdout.log" ]]; then
    gcloud storage cp "${STAGE_DIR}/solver.stdout.log" \
      "${RESULT_PREFIX}/attempts/${RUN_TS}/solver.stdout.log" || true
  fi
  if [[ -f "${STAGE_DIR}/runtime.json" ]]; then
    gcloud storage cp "${STAGE_DIR}/runtime.json" \
      "${RESULT_PREFIX}/attempts/${RUN_TS}/runtime.json" || true
  fi
  exit 50001
}

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

checkpoint_loop &
CHECKPOINT_PID=$!
trap on_sigterm TERM INT

set +e
setsid bash ./command.sh 2>&1 | tee "${STAGE_DIR}/solver.stdout.log" &
SOLVER_PID=$!
SOLVER_PGID=$(ps -o pgid= -p "${SOLVER_PID}" | tr -d ' ' || echo "")
wait "${SOLVER_PID}"
rc=$?
set -e

printf '%s\n' "${rc}" > "${STAGE_DIR}/exit_code.txt"

if [[ -n "${CHECKPOINT_PID:-}" ]]; then
  kill "${CHECKPOINT_PID}" 2>/dev/null || true
  wait "${CHECKPOINT_PID}" 2>/dev/null || true
fi

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
