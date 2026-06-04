#!/usr/bin/env bash
set -euo pipefail

sanitize_job_part() {
  local value="$1"
  value="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9-' '-')"
  value="$(printf '%s' "${value}" | sed -E 's/^-+//; s/-+$//; s/-+/-/g')"
  printf '%s\n' "${value}"
}

if [[ $# -lt 11 ]]; then
  cat >&2 <<EOF
Usage: $0 PROJECT_ID REGION IMAGE_URI VARIANT_ID MACHINE_TYPE \\
  CPU_MILLI MPI_RANKS MEMORY_MIB LOCAL_SSD_COUNT MAX_RUN_DURATION \\
  CASE_ID [CASE_ID ...]
EOF
  exit 1
fi

PROJECT_ID="$1"; REGION="$2"; IMAGE_URI="$3"
VARIANT_ID="$4"; MACHINE_TYPE="$5"
CPU_MILLI="$6"; MPI_RANKS="$7"; MEMORY_MIB="$8"
LOCAL_SSD_COUNT="$9"; MAX_RUN_DURATION="${10}"
shift 10
CASE_IDS=("$@")

if [[ ${#CASE_IDS[@]} -eq 0 ]]; then
  echo "At least one CASE_ID is required" >&2
  exit 1
fi

PROVISIONING_MODEL="${PROVISIONING_MODEL:-STANDARD}"
MAX_RETRY_COUNT="${MAX_RETRY_COUNT:-3}"
SCRATCH_DISK_TYPE="${SCRATCH_DISK_TYPE:-pd-ssd}"
SCRATCH_DISK_GB="${SCRATCH_DISK_GB:-200}"

GCS_BUCKET="openfoam_cases"
BUCKET="${GCS_BUCKET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

JOB_TS="$(date +%Y%m%d%H%M%S)"
JOB_VARIANT_ID="$(sanitize_job_part "${VARIANT_ID}")"
JOB_NAME="of-multi-${JOB_VARIANT_ID}-${JOB_TS}"
CONFIG_PATH="${TMP_DIR}/${JOB_NAME}.json"

# Validate every case prefix unless DRY_RUN.
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  for cid in "${CASE_IDS[@]}"; do
    "${SCRIPT_DIR}/check_case_prefix.sh" "${cid}"
  done
  for cid in "${CASE_IDS[@]}"; do
    marker="gs://${BUCKET}/submissions/${cid}/${VARIANT_ID}.latest.json"
    if gcloud storage ls "${marker}" >/dev/null 2>&1 && [[ "${FORCE_SUBMIT:-0}" != "1" ]]; then
      echo "Submission marker exists for case=${cid} variant=${VARIANT_ID}" >&2
      echo "Set FORCE_SUBMIT=1 to override." >&2
      exit 1
    fi
  done
  gcloud config set project "${PROJECT_ID}" >/dev/null
fi

# Build disks block (same logic as submit_one_case.sh).
DISKS_BLOCK=$'          "disks": [\n'
if [[ "${LOCAL_SSD_COUNT}" != "0" ]]; then
  for ((i = 1; i <= LOCAL_SSD_COUNT; i++)); do
    DEVICE_NAME="openfoam-scratch-${i}"
    DISKS_BLOCK+=$'            {\n'
    DISKS_BLOCK+=$'              "newDisk": {\n'
    DISKS_BLOCK+=$'                "type": "local-ssd",\n'
    DISKS_BLOCK+=$'                "sizeGb": 375\n'
    DISKS_BLOCK+=$'              },\n'
    DISKS_BLOCK+="              \"deviceName\": \"${DEVICE_NAME}\""$'\n'
    DISKS_BLOCK+=$'            }'
    if (( i < LOCAL_SSD_COUNT )); then
      DISKS_BLOCK+=","
    fi
    DISKS_BLOCK+=$'\n'
  done
else
  DISKS_BLOCK+=$'            {\n'
  DISKS_BLOCK+=$'              "newDisk": {\n'
  DISKS_BLOCK+="                \"type\": \"${SCRATCH_DISK_TYPE}\","$'\n'
  DISKS_BLOCK+="                \"sizeGb\": ${SCRATCH_DISK_GB}"$'\n'
  DISKS_BLOCK+=$'              },\n'
  DISKS_BLOCK+=$'              "deviceName": "openfoam-scratch-1"\n'
  DISKS_BLOCK+=$'            }\n'
fi
DISKS_BLOCK+=$'          ]'

VOLUMES_BLOCK=$(cat <<EOF
        "volumes": [
          {
            "deviceName": "openfoam-scratch-1",
            "mountPath": "/mnt/disks/openfoam-scratch",
            "mountOptions": "rw,async"
          }
        ]
EOF
)

CASE_ID_LIST_CSV="$(IFS=,; printf '%s' "${CASE_IDS[*]}")"
TASK_COUNT=${#CASE_IDS[@]}

cat > "${CONFIG_PATH}" <<EOF
{
  "taskGroups": [
    {
      "taskCount": ${TASK_COUNT},
      "parallelism": ${TASK_COUNT},
      "taskSpec": {
        "runnables": [
          {
            "container": {
              "imageUri": "${IMAGE_URI}",
              "entrypoint": "/bin/bash",
              "commands": ["-lc", "/opt/openfoam-batch/run_case_in_batch.sh"]
            }
          }
        ],
        "environment": {
          "variables": {
            "BUCKET": "${BUCKET}",
            "CASE_ID_LIST": "${CASE_ID_LIST_CSV}",
            "VARIANT_ID": "${VARIANT_ID}",
            "JOB_NAME": "${JOB_NAME}",
            "CPU_MILLI": "${CPU_MILLI}",
            "MPI_RANKS": "${MPI_RANKS}",
            "SCRATCH_ROOT": "/mnt/disks/openfoam-scratch",
            "CHECKPOINT_POLL_SEC": "${CHECKPOINT_POLL_SEC:-30}"
          }
        },
        "computeResource": {
          "cpuMilli": ${CPU_MILLI},
          "memoryMib": ${MEMORY_MIB}
        },
        "maxRunDuration": "${MAX_RUN_DURATION}",
        "maxRetryCount": ${MAX_RETRY_COUNT},
        "lifecyclePolicies": [
          {
            "actionCondition": { "exitCodes": [50001] },
            "action": "RETRY_TASK"
          }
        ],
${VOLUMES_BLOCK}
      }
    }
  ],
  "allocationPolicy": {
    "instances": [
      {
        "policy": {
          "machineType": "${MACHINE_TYPE}",
          "provisioningModel": "${PROVISIONING_MODEL}",
${DISKS_BLOCK}
        }
      }
    ]
  },
  "logsPolicy": { "destination": "CLOUD_LOGGING" },
  "labels": { "app": "openfoam" }
}
EOF

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  cat "${CONFIG_PATH}"
  exit 0
fi

gcloud batch jobs submit "${JOB_NAME}" \
  --location "${REGION}" \
  --config "${CONFIG_PATH}"

# Write one submission marker per case.
for idx in "${!CASE_IDS[@]}"; do
  cid="${CASE_IDS[${idx}]}"
  META_PATH="${TMP_DIR}/marker_${idx}.json"
  cat > "${META_PATH}" <<EOF
{
  "project_id": "${PROJECT_ID}",
  "region": "${REGION}",
  "bucket": "${BUCKET}",
  "case_id": "${cid}",
  "variant_id": "${VARIANT_ID}",
  "job_name": "${JOB_NAME}",
  "task_index": ${idx},
  "machine_type": "${MACHINE_TYPE}",
  "submitted_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
  gcloud storage cp "${META_PATH}" \
    "gs://${BUCKET}/submissions/${cid}/${VARIANT_ID}.latest.json"
done

echo "Submitted ${JOB_NAME} (${TASK_COUNT} tasks)"
