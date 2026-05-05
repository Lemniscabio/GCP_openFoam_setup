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

start_test "RESULT_PREFIX includes task_<i> segment"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT_TEST}"

# Build a probe by injecting an exit immediately after RESULT_PREFIX is set.
awk '/^RESULT_PREFIX=/ { print; print "echo RESULT_PREFIX=$RESULT_PREFIX; exit 0"; next } { print }' \
  "${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh" \
  > "${TMPDIR_TEST}/runtime_probe.sh"

probe_out="$(BUCKET=tb CASE_ID=cx VARIANT_ID=fixed JOB_NAME=of-x BATCH_TASK_INDEX=2 \
  SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
  bash "${TMPDIR_TEST}/runtime_probe.sh" 2>"${TMPDIR_TEST}/probe.err")"

assert_contains "RESULT_PREFIX=gs://tb/results/cx/fixed/of-x/task_2" "${probe_out}" "task_2 segment present"
teardown_tmp_workspace

start_test "CASE_ID_LIST resolves CASE_ID from BATCH_TASK_INDEX"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT_TEST}"

# Probe: insert exit immediately after the line that sets CASE_PREFIX
# (which is computed from CASE_ID — so by then CASE_ID must be resolved).
awk '/^CASE_PREFIX=/ { print; print "echo CASE_ID_RESOLVED=$CASE_ID; exit 0"; next } { print }' \
  "${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh" \
  > "${TMPDIR_TEST}/probe.sh"

unset CASE_ID
probe_out="$(CASE_ID_LIST="case_a,case_b,case_c" BATCH_TASK_INDEX=1 \
  BUCKET=tb VARIANT_ID=fixed JOB_NAME=of-x \
  SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
  bash "${TMPDIR_TEST}/probe.sh" 2>"${TMPDIR_TEST}/probe.err")"

assert_contains "CASE_ID_RESOLVED=case_b" "${probe_out}" "index 1 -> case_b"
teardown_tmp_workspace

start_test "first-run: RESUME=0 when no checkpoint exists in GCS"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT_TEST}"

# Probe strategy: inject "set +e" after "set -euo pipefail" so intermediate
# failures (tar, cp on stub-downloaded files) don't abort before the resume
# block is reached. Then inject echo/exit AFTER the closing "fi" of the
# resume detection if-block (anchored by the state: saw RESUME=0, next fi).
awk '
  /^set -euo pipefail/ { print; print "set +e"; next }
  /^RESUME=0$/ { print; saw_resume=1; next }
  saw_resume && /^fi$/ { print; print "echo RESUME_VALUE=$RESUME; exit 0"; saw_resume=0; next }
  { print }
' "${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh" \
  > "${TMPDIR_TEST}/probe.sh"

# GCLOUD_LS_HITS empty -> stub returns 1 for storage ls -> RESUME=0
probe_out="$(GCLOUD_LS_HITS="" \
  BUCKET=tb CASE_ID=cx VARIANT_ID=fixed JOB_NAME=of-x BATCH_TASK_INDEX=0 \
  SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
  bash "${TMPDIR_TEST}/probe.sh" 2>"${TMPDIR_TEST}/probe.err")"
assert_contains "RESUME_VALUE=0" "${probe_out}" "no checkpoint => RESUME=0"
teardown_tmp_workspace

start_test "resume: RESUME=1 when checkpoint exists in GCS"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT_TEST}"

awk '
  /^set -euo pipefail/ { print; print "set +e"; next }
  /^RESUME=0$/ { print; saw_resume=1; next }
  saw_resume && /^fi$/ { print; print "echo RESUME_VALUE=$RESUME; exit 0"; saw_resume=0; next }
  { print }
' "${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh" \
  > "${TMPDIR_TEST}/probe.sh"

# GCLOUD_LS_HITS contains the checkpoint path -> stub returns 0 -> RESUME=1
probe_out="$(GCLOUD_LS_HITS="gs://tb/checkpoints/cx/fixed/latest/" \
  BUCKET=tb CASE_ID=cx VARIANT_ID=fixed JOB_NAME=of-x BATCH_TASK_INDEX=0 \
  SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
  bash "${TMPDIR_TEST}/probe.sh" 2>"${TMPDIR_TEST}/probe.err")"
assert_contains "RESUME_VALUE=1" "${probe_out}" "checkpoint present => RESUME=1"
teardown_tmp_workspace

exit "${TEST_FAILURES}"
