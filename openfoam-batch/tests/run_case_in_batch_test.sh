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

start_test "checkpoint_loop function syncs when new processor0 timestep appears"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
CASE_DIR="${SCRATCH_ROOT_TEST}/cx/case"
mkdir -p "${CASE_DIR}/processor0/0" "${CASE_DIR}/system"

# Extract just the function definition (from `checkpoint_loop()` to the next `^}` at column 0).
sed -n '/^checkpoint_loop()/,/^}/p' \
  "${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh" \
  > "${TMPDIR_TEST}/loop.sh"

# Export env vars so the function (which inherits them) sees them when invoked
# as a background job. Plain `VAR=val source ...` only sets them for the source
# call itself; we need them in the calling shell's env.
export BUCKET=tb CASE_ID=cx VARIANT_ID=fixed
export CHECKPOINT_POLL_SEC=1
export CASE_DIR
export CHECKPOINT_PREFIX="gs://tb/checkpoints/cx/fixed/latest"

# shellcheck disable=SC1091
source "${TMPDIR_TEST}/loop.sh"

checkpoint_loop &
LOOP_PID=$!
sleep 2  # one poll cycle: should be a no-op (no new dir relative to startup)

# Now create a "new" timestep dir and wait for the next cycle.
mkdir -p "${CASE_DIR}/processor0/100"
sleep 2

kill "${LOOP_PID}" 2>/dev/null || true
wait "${LOOP_PID}" 2>/dev/null || true

assert_contains "rsync" "$(cat "${GCLOUD_LOG}")" "loop invoked rsync after new timestep dir appeared"
assert_contains "checkpoints/cx/fixed/latest" "$(cat "${GCLOUD_LOG}")" "rsync target prefix"

# Cleanup so subsequent subtests don't see leaked exports.
unset BUCKET CASE_ID VARIANT_ID CHECKPOINT_POLL_SEC CASE_DIR CHECKPOINT_PREFIX
teardown_tmp_workspace

start_test "on_sigterm: final rsync + preempted.json + exit 50001"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
CASE_DIR="${SCRATCH_ROOT_TEST}/cx/case"
STAGE_DIR="${SCRATCH_ROOT_TEST}/cx/stage"
mkdir -p "${CASE_DIR}/processor0/100" "${CASE_DIR}/system" "${STAGE_DIR}"
echo "log so far" > "${STAGE_DIR}/solver.stdout.log"
echo "{}" > "${STAGE_DIR}/runtime.json"

# Extract the on_sigterm function definition.
sed -n '/^on_sigterm()/,/^}/p' \
  "${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh" \
  > "${TMPDIR_TEST}/trap.sh"

export BUCKET=tb CASE_ID=cx VARIANT_ID=fixed JOB_NAME=of-x BATCH_TASK_INDEX=0
export RUN_TS=20260505T000000Z
export CASE_DIR STAGE_DIR
export CHECKPOINT_PREFIX="gs://tb/checkpoints/cx/fixed/latest"
export RESULT_PREFIX="gs://tb/results/cx/fixed/of-x/task_0"
export SOLVER_PGID="" CHECKPOINT_PID=""

# shellcheck disable=SC1091
source "${TMPDIR_TEST}/trap.sh"

# Run in subshell so exit doesn't kill the test.
( on_sigterm ) || rc=$?

# 50001 % 256 = 81; POSIX exit codes are 8-bit, so the subshell returns 81.
# Production exit 50001 is what Google Cloud Batch reads from the process.
assert_eq "81" "${rc:-}" "exit code 81 (50001 % 256 — Batch reads 50001 from its agent)"
assert_contains "rsync" "$(cat "${GCLOUD_LOG}")" "final rsync invoked"
assert_contains "preempted.json" "$(cat "${GCLOUD_LOG}")" "preempted.json uploaded"
assert_contains "attempts/20260505T000000Z" "$(cat "${GCLOUD_LOG}")" "logs copied to attempts dir"

unset BUCKET CASE_ID VARIANT_ID JOB_NAME BATCH_TASK_INDEX RUN_TS \
      CASE_DIR STAGE_DIR CHECKPOINT_PREFIX RESULT_PREFIX SOLVER_PGID CHECKPOINT_PID
teardown_tmp_workspace

start_test "success path includes checkpoint cleanup line"
setup_tmp_workspace
# Grep the script for the cleanup invocation. Full E2E is covered by Task 16.
if ! grep -q 'storage rm -r .*checkpoints/.*latest' \
     "${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh"; then
  printf '  FAIL [%s] cleanup rm -r line missing from runtime\n' "${TEST_NAME}" >&2
  TEST_FAILURES=$((TEST_FAILURES+1))
fi
teardown_tmp_workspace

start_test "always-copy-attempt-logs lines exist"
setup_tmp_workspace
for needle in 'attempts/.*runtime.json' 'attempts/.*solver.stdout.log' 'attempts/.*exit_code.txt'; do
  if ! grep -qE "${needle}" "${REPO_ROOT}/openfoam-batch/scripts/admin/run_case_in_batch.sh"; then
    printf '  FAIL [%s] missing per-attempt copy: %s\n' "${TEST_NAME}" "${needle}" >&2
    TEST_FAILURES=$((TEST_FAILURES+1))
  fi
done
teardown_tmp_workspace

exit "${TEST_FAILURES}"
