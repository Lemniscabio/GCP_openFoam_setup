#!/usr/bin/env bash
set -euo pipefail

ask() {
  local prompt="$1"
  local default_value="${2:-}"
  local value=""

  if [[ -n "${default_value}" ]]; then
    read -rp "${prompt} [${default_value}]: " value
    printf '%s\n' "${value:-$default_value}"
  else
    read -rp "${prompt}: " value
    printf '%s\n' "${value}"
  fi
}

sanitize_job_part() {
  local value="$1"
  value="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9-' '-')"
  value="$(printf '%s' "${value}" | sed -E 's/^-+//; s/-+$//; s/-+/-/g')"
  printf '%s\n' "${value}"
}

if [[ $# -gt 11 ]]; then
  echo "Usage: $0 [PROJECT_ID] [REGION] [IMAGE_URI] [CASE_ID] [VARIANT_ID] [MACHINE_TYPE] [CPU_MILLI] [MPI_RANKS] [MEMORY_MIB] [LOCAL_SSD_COUNT] [MAX_RUN_DURATION]" >&2
  exit 1
fi

PROJECT_ID="${1:-}"
REGION="${2:-}"
IMAGE_URI="${3:-}"
CASE_ID="${4:-}"
VARIANT_ID="${5:-}"
MACHINE_TYPE="${6:-}"
CPU_MILLI="${7:-}"
MPI_RANKS="${8:-}"
MEMORY_MIB="${9:-}"
LOCAL_SSD_COUNT="${10:-}"
MAX_RUN_DURATION="${11:-}"

PROJECT_ID="${PROJECT_ID:-$(ask "GCP project ID" "project-688a4c78-5d5b-45b3-b5d")}"
REGION="${REGION:-$(ask "GCP region" "us-central1")}"
IMAGE_URI="${IMAGE_URI:-$(ask "Container image URI" "docker.io/kartikeyattri/openfoam")}"
CASE_ID="${CASE_ID:-$(ask "Case ID" "case_0002")}"
VARIANT_ID="${VARIANT_ID:-$(ask "Variant label" "fixed")}"
MACHINE_TYPE="${MACHINE_TYPE:-$(ask "Machine type" "c2d-standard-16")}"
CPU_MILLI="${CPU_MILLI:-$(ask "CPU milli" "16000")}"
MPI_RANKS="${MPI_RANKS:-$(ask "MPI ranks" "8")}"
MEMORY_MIB="${MEMORY_MIB:-$(ask "Memory MiB" "65536")}"
LOCAL_SSD_COUNT="${LOCAL_SSD_COUNT:-$(ask "Local SSD count" "1")}"
MAX_RUN_DURATION="${MAX_RUN_DURATION:-$(ask "Max run duration" "43200s")}"
PROVISIONING_MODEL="${PROVISIONING_MODEL:-STANDARD}"
MAX_RETRY_COUNT="${MAX_RETRY_COUNT:-3}"

# Edit this one line if the bucket changes.
GCS_BUCKET="openfoam_cases"
BUCKET="${GCS_BUCKET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d)"
JOB_TS="$(date +%Y%m%d%H%M%S)"
JOB_CASE_ID="$(sanitize_job_part "${CASE_ID}")"
JOB_VARIANT_ID="$(sanitize_job_part "${VARIANT_ID}")"
JOB_NAME="of-${JOB_CASE_ID}-${JOB_VARIANT_ID}-${JOB_TS}"
SUBMISSION_MARKER="gs://${BUCKET}/submissions/${CASE_ID}/${VARIANT_ID}.latest.json"
CONFIG_PATH="${TMP_DIR}/${JOB_NAME}.json"
META_PATH="${TMP_DIR}/${JOB_NAME}.meta.json"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

if [[ "${DRY_RUN:-0}" != "1" ]]; then
  "${SCRIPT_DIR}/check_case_prefix.sh" "${CASE_ID}"
fi

if [[ "${DRY_RUN:-0}" != "1" ]] \
   && gcloud storage ls "${SUBMISSION_MARKER}" >/dev/null 2>&1 \
   && [[ "${FORCE_SUBMIT:-0}" != "1" ]]; then
  echo "Submission marker exists for case=${CASE_ID} variant=${VARIANT_ID}" >&2
  echo "Set FORCE_SUBMIT=1 if you want to submit again." >&2
  exit 1
fi

if [[ "${DRY_RUN:-0}" != "1" ]]; then
  gcloud config set project "${PROJECT_ID}" >/dev/null
fi

SCRATCH_DISK_TYPE="${SCRATCH_DISK_TYPE:-pd-ssd}"
SCRATCH_DISK_GB="${SCRATCH_DISK_GB:-200}"

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

cat > "${CONFIG_PATH}" <<EOF
{
  "taskGroups": [
    {
      "taskCount": 1,
      "parallelism": 1,
      "taskSpec": {
        "runnables": [
          {
            "container": {
              "imageUri": "${IMAGE_URI}",
              "entrypoint": "/bin/bash",
              "commands": [
                "-lc",
                "/opt/openfoam-batch/run_case_in_batch.sh"
              ]
            }
          }
        ],
        "environment": {
          "variables": {
            "BUCKET": "${BUCKET}",
            "CASE_ID": "${CASE_ID}",
            "VARIANT_ID": "${VARIANT_ID}",
            "JOB_NAME": "${JOB_NAME}",
            "CPU_MILLI": "${CPU_MILLI}",
            "MPI_RANKS": "${MPI_RANKS}",
            "SCRATCH_ROOT": "/mnt/disks/openfoam-scratch"
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
  "logsPolicy": {
    "destination": "CLOUD_LOGGING"
  },
  "labels": {
    "app": "openfoam"
  }
}
EOF

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  cat "${CONFIG_PATH}"
  exit 0
fi

gcloud batch jobs submit "${JOB_NAME}" \
  --location "${REGION}" \
  --config "${CONFIG_PATH}"

cat > "${META_PATH}" <<EOF
{
  "project_id": "${PROJECT_ID}",
  "region": "${REGION}",
  "bucket": "${BUCKET}",
  "case_id": "${CASE_ID}",
  "variant_id": "${VARIANT_ID}",
  "job_name": "${JOB_NAME}",
  "machine_type": "${MACHINE_TYPE}",
  "submitted_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

if [[ "${DRY_RUN:-0}" != "1" ]]; then
  gcloud storage cp "${META_PATH}" "${SUBMISSION_MARKER}"
fi

echo "Submitted ${JOB_NAME}"
