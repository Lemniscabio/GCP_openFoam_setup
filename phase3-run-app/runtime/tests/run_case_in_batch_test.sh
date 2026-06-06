#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib/test_helpers.sh"

SCRIPT_UNDER_TEST="${REPO_ROOT}/phase3-run-app/runtime/run_case_in_batch.sh"

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

awk '/^CHECKPOINT_POLL_SEC=/{emit=1} /^# Minimal stop handler/{emit=0} emit {print}' \
  "${SCRIPT_UNDER_TEST}" > "${TMPDIR_TEST}/checkpoint_functions.sh"
source "${TMPDIR_TEST}/checkpoint_functions.sh"
sync_checkpoint

gcloud_calls="$(cat "${GCLOUD_LOG}")"
assert_contains "rsync --recursive ${CASE_DIR}/processor0/ ${CHECKPOINT_PREFIX}/processor0/" "${gcloud_calls}" "processor0 rsync recorded"
assert_contains "rsync --recursive ${CASE_DIR}/processor1/ ${CHECKPOINT_PREFIX}/processor1/" "${gcloud_calls}" "processor1 rsync recorded"
assert_not_contains "processor*" "${gcloud_calls}" "literal processor glob not passed to gcloud"
unset CASE_DIR CHECKPOINT_PREFIX
teardown_tmp_workspace

start_test "newest checkpoint time handles missing processor0 and serial dirs"
setup_tmp_workspace
CASE_DIR="${TMPDIR_TEST}/scratch/case_0001/case"
mkdir -p "${CASE_DIR}"
CHECKPOINT_PREFIX="gs://tb/checkpoints/case_0001/fixed/latest"
export CASE_DIR CHECKPOINT_PREFIX

awk '/^CHECKPOINT_POLL_SEC=/{emit=1} /^# Minimal stop handler/{emit=0} emit {print}' \
  "${SCRIPT_UNDER_TEST}" > "${TMPDIR_TEST}/checkpoint_functions.sh"
source "${TMPDIR_TEST}/checkpoint_functions.sh"

newest="$(newest_checkpoint_time)"
assert_eq "" "${newest}" "empty case has no checkpoint time"
mkdir -p "${CASE_DIR}/1" "${CASE_DIR}/3.5" "${CASE_DIR}/processor0/2"
newest="$(newest_checkpoint_time)"
assert_eq "3.5" "${newest}" "serial and processor0 times are compared"
unset CASE_DIR CHECKPOINT_PREFIX
teardown_tmp_workspace

start_test "checkpoint loop survives with no checkpointable state"
setup_tmp_workspace
CASE_DIR="${TMPDIR_TEST}/scratch/case_0001/case"
mkdir -p "${CASE_DIR}"
CHECKPOINT_PREFIX="gs://tb/checkpoints/case_0001/fixed/latest"
export CASE_DIR CHECKPOINT_PREFIX

awk '/^CHECKPOINT_POLL_SEC=/{emit=1} /^# Minimal stop handler/{emit=0} emit {print}' \
  "${SCRIPT_UNDER_TEST}" > "${TMPDIR_TEST}/checkpoint_functions.sh"
source "${TMPDIR_TEST}/checkpoint_functions.sh"
CHECKPOINT_POLL_SEC=0.1 checkpoint_loop >"${TMPDIR_TEST}/loop.out" 2>&1 &
loop_pid=$!
sleep 0.25
if ! kill -0 "${loop_pid}" 2>/dev/null; then
  printf '  FAIL [%s] checkpoint loop exited early\n' "${TEST_NAME}" >&2
  TEST_FAILURES=$((TEST_FAILURES+1))
fi
kill "${loop_pid}" 2>/dev/null || true
wait "${loop_pid}" 2>/dev/null || true
assert_contains "No checkpointable state yet" "$(cat "${TMPDIR_TEST}/loop.out")" "empty checkpoint state is logged"
unset CASE_DIR CHECKPOINT_PREFIX
teardown_tmp_workspace

start_test "serial checkpoint sync uploads time dirs system and constant"
setup_tmp_workspace
CASE_DIR="${TMPDIR_TEST}/scratch/case_0001/case"
mkdir -p "${CASE_DIR}/1" "${CASE_DIR}/2.5" "${CASE_DIR}/system" "${CASE_DIR}/constant"
CHECKPOINT_PREFIX="gs://tb/checkpoints/case_0001/fixed/latest"
export CASE_DIR CHECKPOINT_PREFIX

awk '/^CHECKPOINT_POLL_SEC=/{emit=1} /^# Minimal stop handler/{emit=0} emit {print}' \
  "${SCRIPT_UNDER_TEST}" > "${TMPDIR_TEST}/checkpoint_functions.sh"
source "${TMPDIR_TEST}/checkpoint_functions.sh"
sync_checkpoint

gcloud_calls="$(cat "${GCLOUD_LOG}")"
assert_contains "rsync --recursive ${CASE_DIR}/1/ ${CHECKPOINT_PREFIX}/1/" "${gcloud_calls}" "serial time 1 rsync recorded"
assert_contains "rsync --recursive ${CASE_DIR}/2.5/ ${CHECKPOINT_PREFIX}/2.5/" "${gcloud_calls}" "serial time 2.5 rsync recorded"
assert_contains "rsync --recursive ${CASE_DIR}/system ${CHECKPOINT_PREFIX}/system/" "${gcloud_calls}" "serial system rsync recorded"
assert_contains "rsync --recursive ${CASE_DIR}/constant ${CHECKPOINT_PREFIX}/constant/" "${gcloud_calls}" "serial constant rsync recorded"
unset CASE_DIR CHECKPOINT_PREFIX
teardown_tmp_workspace

start_test "checkpoint write failures are counted and echoed"
setup_tmp_workspace
CASE_DIR="${TMPDIR_TEST}/scratch/case_0001/case"
mkdir -p "${CASE_DIR}/processor0/100" "${CASE_DIR}/system"
CHECKPOINT_PREFIX="gs://tb/checkpoints/case_0001/fixed/latest"
export CASE_DIR CHECKPOINT_PREFIX GCLOUD_FAIL_NEXT=1

awk '/^CHECKPOINT_POLL_SEC=/{emit=1} /^# Minimal stop handler/{emit=0} emit {print}' \
  "${SCRIPT_UNDER_TEST}" > "${TMPDIR_TEST}/checkpoint_functions.sh"
source "${TMPDIR_TEST}/checkpoint_functions.sh"
sync_checkpoint 2>"${TMPDIR_TEST}/sync.err"

assert_contains "checkpoint sync failed" "$(cat "${TMPDIR_TEST}/sync.err")" "sync failure echoed"
assert_eq "2" "${CHECKPOINT_SYNC_FAILURES}" "sync failures counted"
unset CASE_DIR CHECKPOINT_PREFIX GCLOUD_FAIL_NEXT
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
gcloud_calls="$(cat "${GCLOUD_LOG}")"
assert_contains \
  "gcloud storage cp ${SCRATCH_ROOT_TEST}/case_0001/stage/result.tar.gz gs://tb/results/singlecase/of-x/case_0001/result.tar.gz" \
  "${gcloud_calls}" \
  "result tarball copied to single-case result prefix"
assert_not_contains "/task_" "${gcloud_calls}" "result path omits task segment"
assert_not_contains "/results/case_0001/fixed/" "${gcloud_calls}" "result path omits variant segment"
teardown_tmp_workspace

start_test "checkpoint restore failure aborts before solver"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
CASE_DIR="${SCRATCH_ROOT_TEST}/case_0001/case"
mkdir -p "${CASE_DIR}"
printf '#!/usr/bin/env bash\ntouch solver-ran\nexit 0\n' > "${CASE_DIR}/command.sh"
chmod +x "${CASE_DIR}/command.sh"

GCLOUD_LS_HITS="gs://tb/checkpoints/case_0001/fixed/latest/" \
GCLOUD_FAIL_CHECKPOINT_RSYNC=1 \
SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
BUCKET=tb CASE_ID=case_0001 VARIANT_ID=fixed JOB_NAME=of-x \
bash "${SCRIPT_UNDER_TEST}" >/dev/null 2>"${TMPDIR_TEST}/stderr"
rc=$?

if [[ "${rc}" -eq 0 ]]; then
  printf '  FAIL [%s] expected restore failure to exit non-zero\n' "${TEST_NAME}" >&2
  TEST_FAILURES=$((TEST_FAILURES+1))
fi
if [[ -f "${CASE_DIR}/solver-ran" ]]; then
  printf '  FAIL [%s] solver ran after restore failure\n' "${TEST_NAME}" >&2
  TEST_FAILURES=$((TEST_FAILURES+1))
fi
teardown_tmp_workspace

start_test "solver nonzero exit records failure and keeps checkpoint"
setup_tmp_workspace
SCRATCH_ROOT_TEST="${TMPDIR_TEST}/scratch"
CASE_DIR="${SCRATCH_ROOT_TEST}/case_0001/case"
mkdir -p "${CASE_DIR}" "${TMPDIR_TEST}/bin"
printf '#!/usr/bin/env bash\necho solver-start\nexit 7\n' > "${CASE_DIR}/command.sh"
chmod +x "${CASE_DIR}/command.sh"
printf '#!/usr/bin/env bash\nexec "$@"\n' > "${TMPDIR_TEST}/bin/setsid"
chmod +x "${TMPDIR_TEST}/bin/setsid"

PATH="${TMPDIR_TEST}/bin:${PATH}" SCRATCH_ROOT="${SCRATCH_ROOT_TEST}" \
BUCKET=tb CASE_ID=case_0001 VARIANT_ID=fixed JOB_NAME=of-x \
bash "${SCRIPT_UNDER_TEST}" >"${TMPDIR_TEST}/stdout" 2>&1
rc=$?

assert_eq "7" "${rc}" "runtime returns solver exit code"
assert_eq "7" "$(cat "${SCRATCH_ROOT_TEST}/case_0001/stage/exit_code.txt")" "exit_code.txt records solver rc"
assert_contains "solver-start" "$(cat "${TMPDIR_TEST}/stdout")" "solver output streamed to stdout"
assert_contains "solver-start" "$(cat "${SCRATCH_ROOT_TEST}/case_0001/stage/solver.stdout.log")" "solver output written to log"
gcloud_calls="$(cat "${GCLOUD_LOG}")"
assert_contains "storage cp ${SCRATCH_ROOT_TEST}/case_0001/stage/_FAILED gs://tb/results/singlecase/of-x/case_0001/_FAILED" "${gcloud_calls}" "_FAILED copied"
assert_not_contains "_SUCCESS" "${gcloud_calls}" "_SUCCESS not copied"
assert_not_contains "storage rm -r gs://tb/checkpoints/case_0001/fixed/latest/" "${gcloud_calls}" "checkpoint not deleted on failure"
teardown_tmp_workspace

exit "${TEST_FAILURES}"
