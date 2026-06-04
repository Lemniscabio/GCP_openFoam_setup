#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib/test_helpers.sh"

SCRIPT="${REPO_ROOT}/openfoam-batch/scripts/prof/professor_upload_case.sh"

start_test "bare numeric upload ID is stored under canonical case_ prefix"
setup_tmp_workspace
CASE_DIR="${TMPDIR_TEST}/case"
COMMAND_SH="${TMPDIR_TEST}/command.sh"
mkdir -p "${CASE_DIR}"
printf 'application simpleFoam;\n' > "${CASE_DIR}/controlDict"
printf '#!/usr/bin/env bash\nexit 0\n' > "${COMMAND_SH}"

GCLOUD_LS_HITS="" bash "${SCRIPT}" 0024 "${CASE_DIR}" "${COMMAND_SH}" \
  >"${TMPDIR_TEST}/stdout" 2>"${TMPDIR_TEST}/stderr"

calls="$(cat "${GCLOUD_LOG}")"
assert_contains "gs://of-cases/cases/case_0024/case.tar.gz" "${calls}" "archive destination uses canonical ID"
assert_contains "Uploaded case case_0024" "$(cat "${TMPDIR_TEST}/stdout")" "reported ID is canonical"
teardown_tmp_workspace

exit "${TEST_FAILURES}"
