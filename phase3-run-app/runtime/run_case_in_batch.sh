#!/usr/bin/env bash
set -euo pipefail

canonical_case_id() {
  local value="$1"
  if [[ "${value}" =~ ^[0-9]+$ ]]; then printf 'case_%04d\n' "$((10#${value}))"; return; fi
  printf '%s\n' "${value}"
}

: "${BUCKET:?BUCKET is required}"
: "${PROJECT:?PROJECT is required}"
if [[ -n "${CASE_ID_LIST:-}" ]]; then
  IFS=',' read -ra _CASE_LIST <<< "${CASE_ID_LIST}"
  _IDX="${BATCH_TASK_INDEX:-0}"
  CASE_ID="$(canonical_case_id "${_CASE_LIST[${_IDX}]:-}")"
  [[ -n "${CASE_ID}" ]] || { echo "BATCH_TASK_INDEX=${_IDX} out of bounds" >&2; exit 64; }
fi
: "${CASE_ID:?CASE_ID is required}"
CASE_ID="$(canonical_case_id "${CASE_ID}")"
: "${VARIANT_ID:?VARIANT_ID is required}"
: "${JOB_NAME:?JOB_NAME is required}"
SCRATCH_ROOT="${SCRATCH_ROOT:-/mnt/disks/openfoam-scratch}"
[[ -d "${SCRATCH_ROOT}" ]] || { echo "SCRATCH_ROOT=${SCRATCH_ROOT} missing" >&2; exit 64; }

CASE_PREFIX="gs://${BUCKET}/cases/${PROJECT}/${CASE_ID}"
RESULT_PREFIX="gs://${BUCKET}/results/${PROJECT}/${JOB_NAME}/${CASE_ID}"
CHECKPOINT_PREFIX="gs://${BUCKET}/checkpoints/${CASE_ID}/${VARIANT_ID}/latest"
WORK_DIR="${SCRATCH_ROOT}/${CASE_ID}"; STAGE_DIR="${WORK_DIR}/stage"; CASE_DIR="${WORK_DIR}/case"
mkdir -p "${STAGE_DIR}" "${CASE_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"

echo "Downloading case tree from ${CASE_PREFIX}/case/"
gcloud storage rsync --recursive "${CASE_PREFIX}/case/" "${CASE_DIR}/"   # tree incl. command.sh
gcloud storage cp "${CASE_PREFIX}/manifest.json" "${STAGE_DIR}/manifest.json"
chmod +x "${CASE_DIR}/command.sh"   # command.sh comes down inside the case tree

resume_from_checkpoint() {
  OF_RESUME=0
  export OF_RESUME

  if gcloud storage ls "${CHECKPOINT_PREFIX}/" >/dev/null 2>&1; then
    echo "Resuming from ${CHECKPOINT_PREFIX}"
    gcloud storage rsync --recursive "${CHECKPOINT_PREFIX}/" "${CASE_DIR}/"

    if [[ -d "${CASE_DIR}/processor0/constant/polyMesh" ]]; then
      OF_RESUME=1
      export OF_RESUME

      if ! command -v foamDictionary >/dev/null 2>&1; then
        echo "foamDictionary is required to set startFrom latestTime on resume" >&2
        exit 70
      fi
      if ! ( cd "${CASE_DIR}" && foamDictionary system/controlDict -entry startFrom -set latestTime ); then
        echo "Failed to set startFrom latestTime in system/controlDict on resume" >&2
        exit 70
      fi
    else
      echo "WARNING: checkpoint present but no decomposed mesh; treating as fresh run" >&2
    fi
  fi
}

resume_from_checkpoint

CHECKPOINT_POLL_SEC="${CHECKPOINT_POLL_SEC:-30}"
CHECKPOINT_SYNC_FAILURES=0

checkpoint_rsync() {
  local src="$1" dst="$2"
  if ! gcloud storage rsync --recursive "${src}" "${dst}"; then
    CHECKPOINT_SYNC_FAILURES=$((CHECKPOINT_SYNC_FAILURES + 1))
    echo "checkpoint sync failed (${CHECKPOINT_SYNC_FAILURES}): ${src} -> ${dst}" >&2
  fi
}

numeric_time_dirs() {
  local p name
  for p in "$@"; do
    [[ -d "${p}" ]] || continue
    name="$(basename "${p}")"
    [[ "${name}" =~ ^[0-9]+([.][0-9]+)?$ ]] && printf '%s\n' "${name}"
  done
}

newest_checkpoint_time() {
  {
    numeric_time_dirs "${CASE_DIR}/processor0"/*/
    numeric_time_dirs "${CASE_DIR}"/*/
  } | sort -n | tail -1
}

sync_checkpoint() {   # FIXED: iterate real processor dirs; no quoted-glob passed to gcloud
  local p name has_processors=0
  for p in "${CASE_DIR}"/processor*/; do
    [[ -d "${p}" ]] || continue
    has_processors=1
    name="$(basename "${p}")"
    checkpoint_rsync "${p}" "${CHECKPOINT_PREFIX}/${name}/"
  done
  if [[ "${has_processors}" -eq 0 ]]; then
    for p in "${CASE_DIR}"/*/; do
      [[ -d "${p}" ]] || continue
      name="$(basename "${p}")"
      [[ "${name}" =~ ^[0-9]+([.][0-9]+)?$ ]] || continue
      checkpoint_rsync "${p}" "${CHECKPOINT_PREFIX}/${name}/"
    done
    [[ -d "${CASE_DIR}/constant" ]] && \
      checkpoint_rsync "${CASE_DIR}/constant" "${CHECKPOINT_PREFIX}/constant/"
  fi
  [[ -d "${CASE_DIR}/system" ]] && \
    checkpoint_rsync "${CASE_DIR}/system" "${CHECKPOINT_PREFIX}/system/"
}

checkpoint_loop() {
  local last="" newest
  while true; do
    sleep "${CHECKPOINT_POLL_SEC}"
    newest="$(newest_checkpoint_time || true)"
    if [[ -z "${newest}" ]]; then
      echo "No checkpointable state yet"
      continue
    fi
    if [[ -n "${newest}" && "${newest}" != "${last}" ]]; then sync_checkpoint; last="${newest}"; fi
  done
}

# Minimal stop handler: flush a final checkpoint so a manual stop / interruption can resume.
# NOT preemption-specific: no preempted.json, no exit 50001.
on_term() {
  trap '' TERM INT
  [[ -n "${SOLVER_PGID:-}" ]] && kill -TERM -"${SOLVER_PGID}" 2>/dev/null || true
  [[ -n "${CHECKPOINT_PID:-}" ]] && kill "${CHECKPOINT_PID}" 2>/dev/null || true
  sync_checkpoint
  exit 143
}

cat > "${STAGE_DIR}/runtime.json" <<EOF
{"case_id":"${CASE_ID}","variant_id":"${VARIANT_ID}","job_name":"${JOB_NAME}","hostname":"$(hostname)","started_at_utc":"$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
EOF

cd "${CASE_DIR}"
checkpoint_loop & CHECKPOINT_PID=$!
trap on_term TERM INT

set +e
setsid bash ./command.sh > >(tee "${STAGE_DIR}/solver.stdout.log") 2>&1 &
SOLVER_PID=$!
SOLVER_PGID="$(ps -o pgid= -p "${SOLVER_PID}" | tr -d ' ' || true)"
wait "${SOLVER_PID}"; rc=$?
set -e

printf '%s\n' "${rc}" > "${STAGE_DIR}/exit_code.txt"
[[ -n "${CHECKPOINT_PID:-}" ]] && { kill "${CHECKPOINT_PID}" 2>/dev/null || true; wait "${CHECKPOINT_PID}" 2>/dev/null || true; }

# results tarball — UNCHANGED behavior
tar -czf "${STAGE_DIR}/result.tar.gz" -C "${CASE_DIR}" .
gcloud storage cp "${STAGE_DIR}/manifest.json"      "${RESULT_PREFIX}/manifest.json"
gcloud storage cp "${STAGE_DIR}/runtime.json"       "${RESULT_PREFIX}/runtime.json"
gcloud storage cp "${STAGE_DIR}/solver.stdout.log"  "${RESULT_PREFIX}/solver.stdout.log"
gcloud storage cp "${STAGE_DIR}/exit_code.txt"      "${RESULT_PREFIX}/exit_code.txt"
gcloud storage cp "${STAGE_DIR}/result.tar.gz"      "${RESULT_PREFIX}/result.tar.gz"
gcloud storage cp "${CASE_DIR}/metadata.json"        "${RESULT_PREFIX}/metadata.json" || true

if [[ "${rc}" -eq 0 ]]; then
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_SUCCESS"
  gcloud storage cp "${STAGE_DIR}/_SUCCESS" "${RESULT_PREFIX}/_SUCCESS"
  gcloud storage rm -r "${CHECKPOINT_PREFIX}/" || true
else
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_FAILED"
  gcloud storage cp "${STAGE_DIR}/_FAILED" "${RESULT_PREFIX}/_FAILED"
fi
exit "${rc}"
