#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib/test_helpers.sh"

SCRIPT="${REPO_ROOT}/openfoam-batch/scripts/admin/submit_one_job_multi_task.sh"

start_test "DRY_RUN multi-task: taskCount = parallelism = number of cases"
setup_tmp_workspace
JSON="$(GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  fixed c2d-standard-16 \
  16000 8 65536 1 43200s \
  case_a case_b case_c 2>"${TMPDIR_TEST}/stderr")"
assert_eq "3" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskCount')" "taskCount=3"
assert_eq "3" "$(echo "${JSON}" | jq -r '.taskGroups[0].parallelism')" "parallelism=3"
assert_eq "case_a,case_b,case_c" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.environment.variables.CASE_ID_LIST')" "CASE_ID_LIST"
assert_eq "fixed" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.environment.variables.VARIANT_ID')" "shared variant"
# CASE_ID env var must NOT be set in multi-task mode (single-task path stays clean)
assert_eq "null" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.environment.variables.CASE_ID // "null"')" "no single CASE_ID"
teardown_tmp_workspace

start_test "rejects empty case list"
setup_tmp_workspace
GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  fixed c2d-standard-16 \
  16000 8 65536 1 43200s \
  >"${TMPDIR_TEST}/out" 2>"${TMPDIR_TEST}/err" && rc=0 || rc=$?
if [[ "${rc}" -eq 0 ]]; then
  printf '  FAIL [%s] expected non-zero exit\n' "${TEST_NAME}" >&2
  TEST_FAILURES=$((TEST_FAILURES+1))
fi
teardown_tmp_workspace

exit "${TEST_FAILURES}"
