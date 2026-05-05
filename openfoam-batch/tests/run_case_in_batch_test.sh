#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib/test_helpers.sh"

SCRIPT="${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh"

start_test "runtime aborts when SCRATCH_ROOT does not exist"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/does-not-exist" \
BUCKET=test-bucket CASE_ID=case_x VARIANT_ID=fixed JOB_NAME=of-x \
bash "${SCRIPT}" 2>"${TMPDIR_TEST}/stderr" >/dev/null
rc=$?
if [[ "${rc}" -eq 0 ]]; then
  printf '  FAIL expected non-zero exit, got 0\n' >&2
  TEST_FAILURES=$((TEST_FAILURES+1))
fi
assert_contains "SCRATCH_ROOT" "$(cat "${TMPDIR_TEST}/stderr")" "stderr names the missing dir"
teardown_tmp_workspace

exit "${TEST_FAILURES}"
