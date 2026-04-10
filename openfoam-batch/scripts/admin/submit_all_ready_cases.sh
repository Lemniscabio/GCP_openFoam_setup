#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 9 ]]; then
  echo "Usage: $0 PROJECT_ID REGION IMAGE_URI MACHINE_TYPE CPU_MILLI MPI_RANKS MEMORY_MIB LOCAL_SSD_COUNT MAX_RUN_DURATION" >&2
  exit 1
fi

PROJECT_ID="$1"
REGION="$2"
IMAGE_URI="$3"
MACHINE_TYPE="$4"
CPU_MILLI="$5"
MPI_RANKS="$6"
MEMORY_MIB="$7"
LOCAL_SSD_COUNT="$8"
MAX_RUN_DURATION="$9"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Edit this one line if the bucket changes.
GCS_BUCKET="openfoam_cases"
BUCKET="${GCS_BUCKET}"

READY_LIST="$(gcloud storage ls "gs://${BUCKET}/cases/*/READY" 2>/dev/null || true)"
if [[ -z "${READY_LIST}" ]]; then
  echo "No READY cases found in gs://${BUCKET}/cases/"
  exit 0
fi

while read -r READY_OBJECT; do
  [[ -z "${READY_OBJECT}" ]] && continue
  CASE_ID="$(basename "$(dirname "${READY_OBJECT}")")"

  "${SCRIPT_DIR}/submit_one_case.sh" \
    "${PROJECT_ID}" \
    "${REGION}" \
    "${IMAGE_URI}" \
    "${CASE_ID}" \
    "fixed" \
    "${MACHINE_TYPE}" \
    "${CPU_MILLI}" \
    "${MPI_RANKS}" \
    "${MEMORY_MIB}" \
    "${LOCAL_SSD_COUNT}" \
    "${MAX_RUN_DURATION}"
done <<< "${READY_LIST}"
