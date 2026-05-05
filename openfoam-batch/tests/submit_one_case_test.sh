#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib/test_helpers.sh"

SCRIPT="${REPO_ROOT}/openfoam-batch/scripts/admin/submit_one_case.sh"

start_test "DRY_RUN local-ssd branch produces valid JSON with local-ssd disk"
setup_tmp_workspace
JSON="$(GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  case_test fixed c2d-standard-16 \
  16000 8 65536 1 43200s 2>"${TMPDIR_TEST}/stderr")"
echo "${JSON}" | jq -e '.taskGroups[0].taskSpec' >/dev/null
assert_eq "0" "$?" "JSON parses"
assert_eq "local-ssd" "$(echo "${JSON}" | jq -r '.allocationPolicy.instances[0].policy.disks[0].newDisk.type')" "disk type local-ssd"
assert_eq "/mnt/disks/openfoam-scratch" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.volumes[0].mountPath')" "mount path"
teardown_tmp_workspace

start_test "DRY_RUN pd-ssd branch (LOCAL_SSD_COUNT=0) attaches pd-ssd newDisk"
setup_tmp_workspace
JSON="$(GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  case_test fixed c3d-standard-8 \
  8000 4 32768 0 43200s 2>"${TMPDIR_TEST}/stderr")"
assert_eq "pd-ssd" "$(echo "${JSON}" | jq -r '.allocationPolicy.instances[0].policy.disks[0].newDisk.type')" "disk type pd-ssd"
assert_eq "200" "$(echo "${JSON}" | jq -r '.allocationPolicy.instances[0].policy.disks[0].newDisk.sizeGb')" "default disk size 200"
assert_eq "/mnt/disks/openfoam-scratch" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.volumes[0].mountPath')" "mount path same"
teardown_tmp_workspace

start_test "SCRATCH_DISK_TYPE and SCRATCH_DISK_GB env vars override defaults"
setup_tmp_workspace
JSON="$(SCRATCH_DISK_TYPE=pd-balanced SCRATCH_DISK_GB=500 \
  GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  case_test fixed c3d-standard-8 \
  8000 4 32768 0 43200s 2>"${TMPDIR_TEST}/stderr")"
assert_eq "pd-balanced" "$(echo "${JSON}" | jq -r '.allocationPolicy.instances[0].policy.disks[0].newDisk.type')" "type override"
assert_eq "500" "$(echo "${JSON}" | jq -r '.allocationPolicy.instances[0].policy.disks[0].newDisk.sizeGb')" "size override"
teardown_tmp_workspace

exit "${TEST_FAILURES}"
