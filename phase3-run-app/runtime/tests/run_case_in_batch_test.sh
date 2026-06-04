#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib/test_helpers.sh"

SCRIPT_UNDER_TEST="${REPO_ROOT}/openfoam-batch/runtime/run_case_in_batch.sh"

start_test "runtime aborts when SCRATCH_ROOT does not exist"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/does-not-exist" \
BUCKET=test-bucket CASE_ID=case_x VARIANT_ID=fixed JOB_NAME=of-x \
bash "${SCRIPT_UNDER_TEST}" 2>"${TMPDIR_TEST}/stderr" >/dev/null
rc=$?
if [[ "${rc}" -eq 0 ]]; then
  printf '  FAIL expected non-zero exit, got 0\n' >&2
  TEST_FAILURES=$((TEST_FAILURES+1))
fi
assert_contains "SCRATCH_ROOT" "$(cat "${TMPDIR_TEST}/stderr")" "stderr names the missing dir"
teardown_tmp_workspace

start_test "tree download uses recursive rsync from case prefix"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT_TEST}"
SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
BUCKET=tb CASE_ID=case_0001 VARIANT_ID=fixed JOB_NAME=of-x \
bash "${SCRIPT_UNDER_TEST}" >/dev/null 2>&1
assert_contains \
  "gcloud storage rsync --recursive gs://tb/cases/case_0001/case/ ${SCRATCH_ROOT_TEST}/case_0001/case/" \
  "$(cat "${GCLOUD_LOG}")" \
  "case tree rsync recorded"
teardown_tmp_workspace

start_test "runtime does not reference SHA256SUMS"
assert_not_contains "SHA256SUMS" "$(cat "${SCRIPT_UNDER_TEST}")"

start_test "checkpoint rsync uses concrete processor directories"
setup_tmp_workspace
CASE_DIR="${TMPDIR_TEST}/scratch/case_0001/case"
mkdir -p "${CASE_DIR}/processor0/100" "${CASE_DIR}/processor1/100" "${CASE_DIR}/system"
CHECKPOINT_PREFIX="gs://tb/checkpoints/case_0001/fixed/latest"
export CASE_DIR CHECKPOINT_PREFIX

sed -n '/^sync_checkpoint()/,/^}/p' "${SCRIPT_UNDER_TEST}" > "${TMPDIR_TEST}/sync_checkpoint.sh"
source "${TMPDIR_TEST}/sync_checkpoint.sh"
sync_checkpoint

gcloud_calls="$(cat "${GCLOUD_LOG}")"
assert_contains "rsync --recursive ${CASE_DIR}/processor0/ ${CHECKPOINT_PREFIX}/processor0/" "${gcloud_calls}" "processor0 rsync recorded"
assert_contains "rsync --recursive ${CASE_DIR}/processor1/ ${CHECKPOINT_PREFIX}/processor1/" "${gcloud_calls}" "processor1 rsync recorded"
assert_not_contains "processor*" "${gcloud_calls}" "literal processor glob not passed to gcloud"
unset CASE_DIR CHECKPOINT_PREFIX
teardown_tmp_workspace

start_test "no preemption artifacts in runtime script"
runtime_commands="$(grep -v '^[[:space:]]*#' "${SCRIPT_UNDER_TEST}")"
assert_not_contains "preempted.json" "${runtime_commands}"
assert_not_contains "exit 50001" "${runtime_commands}"

start_test "CASE_ID_LIST resolves CASE_ID from BATCH_TASK_INDEX"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT_TEST}"

awk '/^CASE_PREFIX=/ { print; print "echo CASE_ID_RESOLVED=$CASE_ID; exit 0"; next } { print }' \
  "${SCRIPT_UNDER_TEST}" \
  > "${TMPDIR_TEST}/probe.sh"

unset CASE_ID
probe_out="$(CASE_ID_LIST="case_0001,case_0002" BATCH_TASK_INDEX=1 \
  BUCKET=tb VARIANT_ID=fixed JOB_NAME=of-x \
  SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
  bash "${TMPDIR_TEST}/probe.sh" 2>"${TMPDIR_TEST}/probe.err")"

assert_contains "CASE_ID_RESOLVED=case_0002" "${probe_out}" "index 1 -> case_0002"
teardown_tmp_workspace

start_test "results tarball is produced and copied"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
CASE_DIR="${SCRATCH_ROOT_TEST}/case_0001/case"
mkdir -p "${CASE_DIR}" "${TMPDIR_TEST}/bin"
printf '#!/usr/bin/env bash\nexit 0\n' > "${CASE_DIR}/command.sh"
chmod +x "${CASE_DIR}/command.sh"
printf '#!/usr/bin/env bash\nexec "$@"\n' > "${TMPDIR_TEST}/bin/setsid"
chmod +x "${TMPDIR_TEST}/bin/setsid"

PATH="${TMPDIR_TEST}/bin:${PATH}" SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
BUCKET=tb CASE_ID=case_0001 VARIANT_ID=fixed JOB_NAME=of-x \
bash "${SCRIPT_UNDER_TEST}" >/dev/null 2>&1
rc=$?

assert_eq "0" "${rc}" "runtime exits successfully"
if [[ ! -f "${SCRATCH_ROOT_TEST}/case_0001/stage/result.tar.gz" ]]; then
  printf '  FAIL [%s] result.tar.gz was not produced\n' "${TEST_NAME}" >&2
  TEST_FAILURES=$((TEST_FAILURES+1))
fi
assert_contains \
  "gcloud storage cp ${SCRATCH_ROOT_TEST}/case_0001/stage/result.tar.gz gs://tb/results/case_0001/fixed/of-x/task_0/result.tar.gz" \
  "$(cat "${GCLOUD_LOG}")" \
  "result tarball copied to result prefix"
teardown_tmp_workspace

exit "${TEST_FAILURES}"
