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

start_test "bare numeric case IDs are canonicalized before CASE_ID_LIST is emitted"
setup_tmp_workspace
JSON="$(GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  fixed c2d-standard-16 \
  16000 8 65536 1 43200s \
  0001 0024 case_0027 2>"${TMPDIR_TEST}/stderr")"
assert_eq "case_0001,case_0024,case_0027" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.environment.variables.CASE_ID_LIST')" "canonical CASE_ID_LIST"
teardown_tmp_workspace

start_test "SKIP_VERIFY=1 submits named cases without running prefix verification"
setup_tmp_workspace
OUT="$(GCLOUD_LS_HITS="" SKIP_VERIFY=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  sweep75 c2d-standard-16 \
  16000 8 65536 1 43200s \
  case_0028 case_0029 2>"${TMPDIR_TEST}/stderr")"
assert_contains "Submitted of-multi-sweep75-" "${OUT}" "submission reaches Batch submit"
assert_not_contains "/cases/case_0028/" "$(cat "${GCLOUD_LOG}")" "case_0028 validation skipped"
assert_not_contains "/cases/case_0029/" "$(cat "${GCLOUD_LOG}")" "case_0029 validation skipped"
assert_contains "gcloud batch jobs submit" "$(cat "${GCLOUD_LOG}")" "Batch job submitted"
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
