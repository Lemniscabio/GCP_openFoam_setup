#!/usr/bin/env bash
# Shared test helpers. Source from each test file.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
TESTS_LIB_DIR="${REPO_ROOT}/phase3-run-app/runtime/tests/lib"
STUBS_DIR="${TESTS_LIB_DIR}/stubs"

# Failures
TEST_FAILURES=0
TEST_NAME=""

assert_eq() {
  local expected="$1"
  local actual="$2"
  local msg="${3:-assert_eq}"
  if [[ "${expected}" != "${actual}" ]]; then
    printf '  FAIL [%s] %s: expected %q got %q\n' "${TEST_NAME}" "${msg}" "${expected}" "${actual}" >&2
    TEST_FAILURES=$((TEST_FAILURES + 1))
  fi
}

assert_contains() {
  local needle="$1"
  local haystack="$2"
  local msg="${3:-assert_contains}"
  if ! grep -Fq "${needle}" <<< "${haystack}"; then
    printf '  FAIL [%s] %s: %q not found in:\n%s\n' "${TEST_NAME}" "${msg}" "${needle}" "${haystack}" >&2
    TEST_FAILURES=$((TEST_FAILURES + 1))
  fi
}

assert_not_contains() {
  local needle="$1"
  local haystack="$2"
  local msg="${3:-assert_not_contains}"
  if grep -Fq "${needle}" <<< "${haystack}"; then
    printf '  FAIL [%s] %s: %q unexpectedly found\n' "${TEST_NAME}" "${msg}" "${needle}" >&2
    TEST_FAILURES=$((TEST_FAILURES + 1))
  fi
}

start_test() {
  TEST_NAME="$1"
  printf '  -> %s\n' "${TEST_NAME}"
}

setup_tmp_workspace() {
  TMPDIR_TEST="$(mktemp -d)"
  GCLOUD_LOG="${TMPDIR_TEST}/gcloud.log"
  FOAMDICT_LOG="${TMPDIR_TEST}/foamDictionary.log"
  : > "${GCLOUD_LOG}"
  : > "${FOAMDICT_LOG}"
  export TMPDIR_TEST GCLOUD_LOG FOAMDICT_LOG
  if [[ ":${PATH}:" != *":${STUBS_DIR}:"* ]]; then
    export PATH="${STUBS_DIR}:${PATH}"
  fi
}

teardown_tmp_workspace() {
  rm -rf "${TMPDIR_TEST}"
}
