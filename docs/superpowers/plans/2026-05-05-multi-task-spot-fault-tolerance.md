# Multi-Task Submit, Spot Fault Tolerance, GCS Layout, Disk Strategy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phases A–D from the spec at `docs/superpowers/specs/2026-05-05-multi-task-spot-design.md` — a third submit mode (single-job/multi-task), task-aware GCS paths, Spot fault tolerance via continuous GCS checkpointing + retry, and pd-ssd-or-local-SSD scratch (no boot-disk fallback).

**Architecture:** All changes are in bash scripts. The runtime container script (`run_case_in_batch.sh`) gains a background checkpoint loop, a SIGTERM trap, resume-from-GCS detection, per-attempt log dirs, task-index resolution from `CASE_ID_LIST`, and removal of the `/tmp` scratch fallback. Submit scripts gain a `DRY_RUN` JSON-only mode (for testing), new env-var knobs (`SCRATCH_DISK_TYPE`, `SCRATCH_DISK_GB`, `MAX_RETRY_COUNT`, `PROVISIONING_MODEL`, `CHECKPOINT_POLL_SEC`), and Spot+retry config in the Batch JSON. A new `submit_one_job_multi_task.sh` adds the third submission mode.

**Tech Stack:** bash 5.x, `gcloud` CLI (storage + batch), `jq` for JSON assertions in tests, `foamDictionary` (OpenFOAM) inside the container, GCP Batch, GCS. Tests are plain bash scripts under `openfoam-batch/tests/` using PATH-stubbing for `gcloud`/`foamDictionary` and `jq` for JSON assertions. No `bats` or `shellcheck` dependency required (both optional).

---

## File Structure

**New:**
- `openfoam-batch/scripts/admin/submit_one_job_multi_task.sh` — third submit mode (Phase A).
- `openfoam-batch/tests/lib/test_helpers.sh` — shared test helpers (PATH stub, temp dirs, asserts).
- `openfoam-batch/tests/lib/stubs/gcloud` — fake `gcloud` that records calls.
- `openfoam-batch/tests/lib/stubs/foamDictionary` — fake `foamDictionary` that records calls.
- `openfoam-batch/tests/submit_one_case_test.sh`
- `openfoam-batch/tests/submit_one_job_multi_task_test.sh`
- `openfoam-batch/tests/run_case_in_batch_test.sh`
- `openfoam-batch/tests/run_all.sh` — convenience runner.

**Modified:**
- `openfoam-batch/scripts/admin/run_case_in_batch.sh` — large changes (Phases A small, B, C, D).
- `openfoam-batch/scripts/admin/submit_one_case.sh` — JSON shape, env vars, dry-run (Phases C, D).
- `openfoam-batch/scripts/admin/submit_all_ready_cases.sh` — pass-through env vars.
- `openfoam-batch/README.md` — docs.

**Untouched:**
- `openfoam-batch/scripts/prof/*` (professor-facing).
- `openfoam-batch/scripts/admin/check_case_prefix.sh`.
- `openfoam-batch/Dockerfile` (no code change; image rebuild required after runtime script changes).

---

## Conventions Used In This Plan

- All paths are repo-relative unless absolute.
- "Run in repo root" means the directory printed by `git rev-parse --show-toplevel`.
- All commits are in the form `type: short description` matching existing repo style (`fix:`, `feat:`, `docs:`).
- Tests live under `openfoam-batch/tests/`. Run via `bash openfoam-batch/tests/run_all.sh`.

---

## Task 1 — Test Scaffolding

**Files:**
- Create: `openfoam-batch/tests/lib/test_helpers.sh`
- Create: `openfoam-batch/tests/lib/stubs/gcloud`
- Create: `openfoam-batch/tests/lib/stubs/foamDictionary`
- Create: `openfoam-batch/tests/run_all.sh`

- [ ] **Step 1: Create the gcloud stub**

`openfoam-batch/tests/lib/stubs/gcloud`:
```bash
#!/usr/bin/env bash
# Fake gcloud: records each invocation to ${GCLOUD_LOG} and returns success
# (or non-zero if ${GCLOUD_FAIL_NEXT}=1, then resets).
# For specific subcommands we emit canned output:
#   "storage ls"  -> exit 0 if path is in ${GCLOUD_LS_HITS} (newline-separated), else exit 1
#   "storage cp"  -> exit 0, record call
#   "storage rm"  -> exit 0, record call
#   "storage rsync" -> exit 0, record call
#   "batch jobs submit" -> exit 0, record call
#   "config set"  -> exit 0
set -u
: "${GCLOUD_LOG:?GCLOUD_LOG must be set}"
printf '%s\n' "gcloud $*" >> "${GCLOUD_LOG}"

if [[ "${GCLOUD_FAIL_NEXT:-0}" == "1" ]]; then
  unset GCLOUD_FAIL_NEXT
  exit 1
fi

case "$1 $2" in
  "storage ls")
    target="${3:-}"
    if [[ -n "${GCLOUD_LS_HITS:-}" ]] && grep -Fxq "${target}" <<< "${GCLOUD_LS_HITS}"; then
      printf '%s\n' "${target}"
      exit 0
    fi
    exit 1
    ;;
  *)
    exit 0
    ;;
esac
```

- [ ] **Step 2: Create the foamDictionary stub**

`openfoam-batch/tests/lib/stubs/foamDictionary`:
```bash
#!/usr/bin/env bash
# Fake foamDictionary: just record the call.
set -u
: "${FOAMDICT_LOG:?FOAMDICT_LOG must be set}"
printf '%s\n' "foamDictionary $*" >> "${FOAMDICT_LOG}"
exit 0
```

- [ ] **Step 3: Create test_helpers.sh**

`openfoam-batch/tests/lib/test_helpers.sh`:
```bash
#!/usr/bin/env bash
# Shared test helpers. Source from each test file.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TESTS_LIB_DIR="${REPO_ROOT}/openfoam-batch/tests/lib"
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
  export GCLOUD_LOG FOAMDICT_LOG
  export PATH="${STUBS_DIR}:${PATH}"
}

teardown_tmp_workspace() {
  rm -rf "${TMPDIR_TEST}"
}
```

- [ ] **Step 4: Make stubs executable**

```bash
chmod +x openfoam-batch/tests/lib/stubs/gcloud openfoam-batch/tests/lib/stubs/foamDictionary
```

- [ ] **Step 5: Create run_all.sh**

`openfoam-batch/tests/run_all.sh`:
```bash
#!/usr/bin/env bash
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
total_failures=0
for f in "${DIR}"/*_test.sh; do
  [[ -f "${f}" ]] || continue
  printf '\n== %s ==\n' "$(basename "${f}")"
  bash "${f}"
  rc=$?
  total_failures=$((total_failures + rc))
done
if [[ "${total_failures}" -gt 0 ]]; then
  printf '\nFAILED: %d test files reported failures\n' "${total_failures}" >&2
  exit 1
fi
printf '\nAll test files passed.\n'
```

- [ ] **Step 6: Make run_all.sh executable**

```bash
chmod +x openfoam-batch/tests/run_all.sh
```

- [ ] **Step 7: Smoke-run the empty harness**

Run: `bash openfoam-batch/tests/run_all.sh`
Expected: prints "All test files passed." (no test files yet, so loop is empty).

- [ ] **Step 8: Commit**

```bash
git add openfoam-batch/tests/
git commit -m "test: add bash test scaffolding for admin scripts

- gcloud and foamDictionary PATH stubs that record calls
- shared assertions and tmp-workspace helpers
- run_all.sh entrypoint
"
```

---

## Task 2 — Phase D: Submit Script Disk Strategy + Dry-Run Mode

Replace the no-disk-block branch (today's `LOCAL_SSD_COUNT=0` path that falls back to `/tmp` on the boot disk) with an attached pd-ssd `newDisk`. Add `DRY_RUN=1` mode so we can JSON-test without calling gcloud.

**Files:**
- Modify: `openfoam-batch/scripts/admin/submit_one_case.sh`
- Test: `openfoam-batch/tests/submit_one_case_test.sh` (new)

- [ ] **Step 1: Write failing test for DRY_RUN mode existence + LOCAL_SSD branch**

Create `openfoam-batch/tests/submit_one_case_test.sh`:
```bash
#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib/test_helpers.sh"

SCRIPT="${REPO_ROOT}/openfoam-batch/scripts/admin/submit_one_case.sh"

run_dry_run() {
  setup_tmp_workspace
  GCLOUD_LS_HITS="" \
  DRY_RUN=1 \
  bash "${SCRIPT}" \
    project-test us-central1 docker.io/test:1 \
    case_test fixed c2d-standard-16 \
    16000 8 65536 1 43200s 2>"${TMPDIR_TEST}/stderr"
}

start_test "DRY_RUN local-ssd branch produces valid JSON with local-ssd disk"
JSON="$(run_dry_run)"
echo "${JSON}" | jq -e '.taskGroups[0].taskSpec' >/dev/null
assert_eq "0" "$?" "JSON parses"
assert_eq "local-ssd" "$(echo "${JSON}" | jq -r '.allocationPolicy.instances[0].policy.disks[0].newDisk.type')" "disk type local-ssd"
assert_eq "/mnt/disks/openfoam-scratch" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.volumes[0].mountPath')" "mount path"
teardown_tmp_workspace

exit "${TEST_FAILURES}"
```

Make executable: `chmod +x openfoam-batch/tests/submit_one_case_test.sh`

- [ ] **Step 2: Run test to verify it fails**

Run: `bash openfoam-batch/tests/submit_one_case_test.sh`
Expected: FAIL — current script doesn't honor `DRY_RUN`, will try to actually submit (or error on stub gcloud).

- [ ] **Step 3: Add DRY_RUN handling and refactor JSON emission**

In `openfoam-batch/scripts/admin/submit_one_case.sh`, replace the section that builds and submits the job. Specifically:

(a) After all positional/`ask` defaults are resolved (around line 53) and after `JOB_NAME` is computed, change the `gcloud config set project` line and the submission to be conditional on `DRY_RUN`:

Find:
```bash
gcloud config set project "${PROJECT_ID}" >/dev/null
```
Replace with:
```bash
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  gcloud config set project "${PROJECT_ID}" >/dev/null
fi
```

Find:
```bash
gcloud batch jobs submit "${JOB_NAME}" \
  --location "${REGION}" \
  --config "${CONFIG_PATH}"
```
Replace with:
```bash
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  cat "${CONFIG_PATH}"
  exit 0
fi

gcloud batch jobs submit "${JOB_NAME}" \
  --location "${REGION}" \
  --config "${CONFIG_PATH}"
```

Find the submission-marker check block (around line 75):
```bash
if gcloud storage ls "${SUBMISSION_MARKER}" >/dev/null 2>&1 && [[ "${FORCE_SUBMIT:-0}" != "1" ]]; then
```
Replace with:
```bash
if [[ "${DRY_RUN:-0}" != "1" ]] \
   && gcloud storage ls "${SUBMISSION_MARKER}" >/dev/null 2>&1 \
   && [[ "${FORCE_SUBMIT:-0}" != "1" ]]; then
```

Find the `check_case_prefix.sh` invocation (line 73):
```bash
"${SCRIPT_DIR}/check_case_prefix.sh" "${CASE_ID}"
```
Replace with:
```bash
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  "${SCRIPT_DIR}/check_case_prefix.sh" "${CASE_ID}"
fi
```

Find the final submission-marker upload (around line 200):
```bash
gcloud storage cp "${META_PATH}" "${SUBMISSION_MARKER}"

echo "Submitted ${JOB_NAME}"
```
Replace with:
```bash
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  gcloud storage cp "${META_PATH}" "${SUBMISSION_MARKER}"
fi

echo "Submitted ${JOB_NAME}"
```

- [ ] **Step 4: Run test, verify local-ssd branch passes**

Run: `bash openfoam-batch/tests/submit_one_case_test.sh`
Expected: PASS for the local-ssd branch test.

- [ ] **Step 5: Add failing test for pd-ssd branch (LOCAL_SSD_COUNT=0)**

Append to `openfoam-batch/tests/submit_one_case_test.sh` (before `exit "${TEST_FAILURES}"`):
```bash
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
```

- [ ] **Step 6: Run, verify pd-ssd test fails**

Run: `bash openfoam-batch/tests/submit_one_case_test.sh`
Expected: pd-ssd assertions FAIL (no disks block emitted today when `LOCAL_SSD_COUNT=0`).

- [ ] **Step 7: Implement pd-ssd branch**

In `openfoam-batch/scripts/admin/submit_one_case.sh`, replace the entire DISKS_BLOCK/VOLUMES_BLOCK construction (lines 83–112) with:

```bash
SCRATCH_DISK_TYPE="${SCRATCH_DISK_TYPE:-pd-ssd}"
SCRATCH_DISK_GB="${SCRATCH_DISK_GB:-200}"

DISKS_BLOCK=$'          "disks": [\n'
if [[ "${LOCAL_SSD_COUNT}" != "0" ]]; then
  for ((i = 1; i <= LOCAL_SSD_COUNT; i++)); do
    DEVICE_NAME="openfoam-scratch-${i}"
    DISKS_BLOCK+=$'            {\n'
    DISKS_BLOCK+=$'              "newDisk": {\n'
    DISKS_BLOCK+=$'                "type": "local-ssd",\n'
    DISKS_BLOCK+=$'                "sizeGb": 375\n'
    DISKS_BLOCK+=$'              },\n'
    DISKS_BLOCK+="              \"deviceName\": \"${DEVICE_NAME}\""$'\n'
    DISKS_BLOCK+=$'            }'
    if (( i < LOCAL_SSD_COUNT )); then
      DISKS_BLOCK+=","
    fi
    DISKS_BLOCK+=$'\n'
  done
else
  DISKS_BLOCK+=$'            {\n'
  DISKS_BLOCK+=$'              "newDisk": {\n'
  DISKS_BLOCK+="                \"type\": \"${SCRATCH_DISK_TYPE}\","$'\n'
  DISKS_BLOCK+="                \"sizeGb\": ${SCRATCH_DISK_GB}"$'\n'
  DISKS_BLOCK+=$'              },\n'
  DISKS_BLOCK+=$'              "deviceName": "openfoam-scratch-1"\n'
  DISKS_BLOCK+=$'            }\n'
fi
DISKS_BLOCK+=$'          ]'

VOLUMES_BLOCK=$(cat <<EOF
        "volumes": [
          {
            "deviceName": "openfoam-scratch-1",
            "mountPath": "/mnt/disks/openfoam-scratch",
            "mountOptions": "rw,async"
          }
        ]
EOF
)
```

Also delete the now-obsolete bootDisk comment block (lines 114–126) entirely.

In the JSON template a few lines below, the conditional emission of DISKS_BLOCK and VOLUMES_BLOCK now always emits (both are always non-empty). Change:
```bash
"machineType": "${MACHINE_TYPE}"$( [[ -n "${DISKS_BLOCK}" ]] && printf ',\n%s' "${DISKS_BLOCK}" )
```
to:
```bash
"machineType": "${MACHINE_TYPE}",
${DISKS_BLOCK}
```

And:
```bash
"maxRunDuration": "${MAX_RUN_DURATION}"$( [[ -n "${VOLUMES_BLOCK}" ]] && printf ',\n%s' "${VOLUMES_BLOCK}" )
```
to:
```bash
"maxRunDuration": "${MAX_RUN_DURATION}",
${VOLUMES_BLOCK}
```

- [ ] **Step 8: Run all submit_one_case tests**

Run: `bash openfoam-batch/tests/submit_one_case_test.sh`
Expected: all PASS.

- [ ] **Step 9: Validate the produced JSON parses with jq for both branches**

Run: `bash openfoam-batch/tests/run_all.sh`
Expected: PASS overall.

- [ ] **Step 10: Commit**

```bash
git add openfoam-batch/scripts/admin/submit_one_case.sh \
        openfoam-batch/tests/submit_one_case_test.sh
git commit -m "feat(submit): pd-ssd scratch + DRY_RUN, drop boot-disk fallback

LOCAL_SSD_COUNT=0 now attaches a configurable pd-ssd newDisk at
/mnt/disks/openfoam-scratch instead of falling back to /tmp on the boot
disk. New env vars: SCRATCH_DISK_TYPE (default pd-ssd), SCRATCH_DISK_GB
(default 200). DRY_RUN=1 prints the Batch JSON without submitting; used
by tests."
```

---

## Task 3 — Phase D: Runtime Mount-Path Consistency

Remove the `/tmp/openfoam-scratch` fallback. Runtime now requires `/mnt/disks/openfoam-scratch` (the submit script always provides it after Task 2).

**Files:**
- Modify: `openfoam-batch/scripts/admin/run_case_in_batch.sh`
- Test: `openfoam-batch/tests/run_case_in_batch_test.sh` (new)

- [ ] **Step 1: Write failing test**

Create `openfoam-batch/tests/run_case_in_batch_test.sh`:
```bash
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
[[ "${rc}" -ne 0 ]] || { printf '  FAIL expected non-zero exit, got %s\n' "${rc}"; TEST_FAILURES=$((TEST_FAILURES+1)); }
assert_contains "SCRATCH_ROOT" "$(cat "${TMPDIR_TEST}/stderr")" "stderr names the missing dir"
teardown_tmp_workspace

exit "${TEST_FAILURES}"
```

Make executable: `chmod +x openfoam-batch/tests/run_case_in_batch_test.sh`

- [ ] **Step 2: Run, verify it fails**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: FAIL — current script silently falls back to `/tmp/openfoam-scratch`, exit code is whatever `gcloud_cp` returns.

- [ ] **Step 3: Replace fallback with hard requirement**

In `openfoam-batch/scripts/admin/run_case_in_batch.sh`, lines 21–24:

Find:
```bash
SCRATCH_ROOT="${SCRATCH_ROOT:-/mnt/disks/openfoam-scratch}"
if [[ ! -d "${SCRATCH_ROOT}" ]]; then
  SCRATCH_ROOT="/tmp/openfoam-scratch"
fi
```

Replace with:
```bash
SCRATCH_ROOT="${SCRATCH_ROOT:-/mnt/disks/openfoam-scratch}"
if [[ ! -d "${SCRATCH_ROOT}" ]]; then
  echo "SCRATCH_ROOT=${SCRATCH_ROOT} does not exist; submit script must mount a scratch volume" >&2
  exit 64
fi
```

- [ ] **Step 4: Run test, verify pass**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openfoam-batch/scripts/admin/run_case_in_batch.sh \
        openfoam-batch/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): require mounted scratch, drop /tmp fallback

The submit script now always attaches a scratch disk (local-ssd or
pd-ssd). The runtime no longer silently falls back to the boot disk
via /tmp; missing SCRATCH_ROOT is a hard error."
```

---

## Task 4 — Phase B: task_<i> Result Path Segment

Add a `task_<BATCH_TASK_INDEX>` segment under `JOB_NAME` in the result path. Always present (single-task = `task_0`).

**Files:**
- Modify: `openfoam-batch/scripts/admin/run_case_in_batch.sh`
- Modify: `openfoam-batch/tests/run_case_in_batch_test.sh`

- [ ] **Step 1: Write failing test**

Append to `openfoam-batch/tests/run_case_in_batch_test.sh` (before `exit`):

```bash
start_test "RESULT_PREFIX includes task_<i> segment"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT}"

# Source-only mode: extract just the path-construction block.
# We simulate by setting env vars and grepping the script for the construction.
# Cleanest: invoke a one-liner that sources the variable construction lines.
BUCKET=tb CASE_ID=cx VARIANT_ID=fixed JOB_NAME=of-x BATCH_TASK_INDEX=2 \
SCRATCH_ROOT="${SCRATCH_ROOT}" \
bash -c '
  set -e
  export PATH="'"${STUBS_DIR}"':${PATH}"
  export GCLOUD_LOG="'"${GCLOUD_LOG}"'"
  # Run the runtime up to (and including) result-prefix construction by
  # exiting after the variable is set. We do that via a wrapper that source-
  # injects an "echo and exit" right after the line.
  awk "/^RESULT_PREFIX=/ { print; print \"echo RESULT_PREFIX=\\\$RESULT_PREFIX; exit 0\"; next } { print }" '"${SCRIPT}"' > "'"${TMPDIR_TEST}"'/runtime_probe.sh"
  bash "'"${TMPDIR_TEST}"'/runtime_probe.sh"
' >"${TMPDIR_TEST}/probe.out" 2>"${TMPDIR_TEST}/probe.err"

assert_contains "RESULT_PREFIX=gs://tb/results/cx/fixed/of-x/task_2" "$(cat "${TMPDIR_TEST}/probe.out")" "task_2 segment present"
teardown_tmp_workspace
```

- [ ] **Step 2: Run, verify it fails**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: FAIL — current `RESULT_PREFIX` (line 27) lacks task segment.

- [ ] **Step 3: Add task_<i> to RESULT_PREFIX**

In `openfoam-batch/scripts/admin/run_case_in_batch.sh`, find:
```bash
RESULT_PREFIX="gs://${BUCKET}/results/${CASE_ID}/${VARIANT_ID}/${JOB_NAME}"
```

Replace with:
```bash
TASK_INDEX="${BATCH_TASK_INDEX:-0}"
RESULT_PREFIX="gs://${BUCKET}/results/${CASE_ID}/${VARIANT_ID}/${JOB_NAME}/task_${TASK_INDEX}"
```

- [ ] **Step 4: Run, verify pass**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: PASS for the new test (other tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add openfoam-batch/scripts/admin/run_case_in_batch.sh \
        openfoam-batch/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): add task_<i> segment to result path

Result path becomes results/CASE_ID/VARIANT_ID/JOB_NAME/task_<i>/.
Single-task jobs always use task_0. Eliminates per-mode special cases
in downstream tooling."
```

---

## Task 5 — Phase A (small piece): CASE_ID_LIST Resolution In Runtime

When `CASE_ID_LIST` is set, runtime resolves `CASE_ID` from `BATCH_TASK_INDEX`.

**Files:**
- Modify: `openfoam-batch/scripts/admin/run_case_in_batch.sh`
- Modify: `openfoam-batch/tests/run_case_in_batch_test.sh`

- [ ] **Step 1: Write failing test**

Append to `openfoam-batch/tests/run_case_in_batch_test.sh`:
```bash
start_test "CASE_ID_LIST resolves CASE_ID from BATCH_TASK_INDEX"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT}"
unset CASE_ID
CASE_ID_LIST="case_a,case_b,case_c" BATCH_TASK_INDEX=1 \
BUCKET=tb VARIANT_ID=fixed JOB_NAME=of-x \
SCRATCH_ROOT="${SCRATCH_ROOT}" \
bash -c '
  awk "/^CASE_PREFIX=/ { print; print \"echo CASE_ID_RESOLVED=\\\$CASE_ID; exit 0\"; next } { print }" '"${SCRIPT}"' > "'"${TMPDIR_TEST}"'/probe.sh"
  bash "'"${TMPDIR_TEST}"'/probe.sh"
' >"${TMPDIR_TEST}/probe.out" 2>"${TMPDIR_TEST}/probe.err"
assert_contains "CASE_ID_RESOLVED=case_b" "$(cat "${TMPDIR_TEST}/probe.out")" "index 1 -> case_b"
teardown_tmp_workspace
```

- [ ] **Step 2: Run, verify fail**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: the new test FAILs because `CASE_ID` is required and unset.

- [ ] **Step 3: Add resolution block**

In `openfoam-batch/scripts/admin/run_case_in_batch.sh`, find:
```bash
: "${CASE_ID:?CASE_ID is required}"
```

Replace with:
```bash
if [[ -n "${CASE_ID_LIST:-}" ]]; then
  IFS=',' read -ra _CASE_LIST <<< "${CASE_ID_LIST}"
  _IDX="${BATCH_TASK_INDEX:-0}"
  CASE_ID="${_CASE_LIST[${_IDX}]:-}"
  if [[ -z "${CASE_ID}" ]]; then
    echo "CASE_ID_LIST set but BATCH_TASK_INDEX=${_IDX} is out of bounds" >&2
    exit 64
  fi
fi
: "${CASE_ID:?CASE_ID is required}"
```

- [ ] **Step 4: Run, verify pass**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openfoam-batch/scripts/admin/run_case_in_batch.sh \
        openfoam-batch/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): resolve CASE_ID from CASE_ID_LIST + BATCH_TASK_INDEX

In multi-task mode the submit script passes CASE_ID_LIST as a comma-
separated list; the runtime indexes into it via BATCH_TASK_INDEX. The
single-case CASE_ID env var path is unchanged."
```

---

## Task 6 — Phase C: Resume Detection + Restore + controlDict Force

Detect resume from GCS existence; rsync checkpoint into case dir; force `startFrom latestTime`.

**Files:**
- Modify: `openfoam-batch/scripts/admin/run_case_in_batch.sh`
- Modify: `openfoam-batch/tests/run_case_in_batch_test.sh`

- [ ] **Step 1: Write failing test for first-run path (no resume)**

Append to `openfoam-batch/tests/run_case_in_batch_test.sh`:
```bash
start_test "first-run: RESUME=0, no checkpoint rsync invoked"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT}"
# Don't add the checkpoint to GCLOUD_LS_HITS -> ls returns 1 -> RESUME=0
unset GCLOUD_LS_HITS
GCLOUD_LS_HITS="" \
BUCKET=tb CASE_ID=cx VARIANT_ID=fixed JOB_NAME=of-x BATCH_TASK_INDEX=0 \
SCRATCH_ROOT="${SCRATCH_ROOT}" \
bash -c '
  awk "/^RESUME=/ { print; print \"echo RESUME=\\\$RESUME; exit 0\"; next } { print }" '"${SCRIPT}"' > "'"${TMPDIR_TEST}"'/probe.sh"
  bash "'"${TMPDIR_TEST}"'/probe.sh"
' >"${TMPDIR_TEST}/probe.out" 2>"${TMPDIR_TEST}/probe.err"
assert_contains "RESUME=0" "$(cat "${TMPDIR_TEST}/probe.out")" "no checkpoint => RESUME=0"
teardown_tmp_workspace

start_test "resume: RESUME=1 when checkpoint exists in GCS"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT}"
GCLOUD_LS_HITS="gs://tb/checkpoints/cx/fixed/latest/" \
BUCKET=tb CASE_ID=cx VARIANT_ID=fixed JOB_NAME=of-x BATCH_TASK_INDEX=0 \
SCRATCH_ROOT="${SCRATCH_ROOT}" \
bash -c '
  awk "/^RESUME=/ { print; print \"echo RESUME=\\\$RESUME; exit 0\"; next } { print }" '"${SCRIPT}"' > "'"${TMPDIR_TEST}"'/probe.sh"
  bash "'"${TMPDIR_TEST}"'/probe.sh"
' >"${TMPDIR_TEST}/probe.out" 2>"${TMPDIR_TEST}/probe.err"
assert_contains "RESUME=1" "$(cat "${TMPDIR_TEST}/probe.out")" "checkpoint present => RESUME=1"
teardown_tmp_workspace
```

- [ ] **Step 2: Run, verify FAIL** (variable not yet defined).

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: probe assertion fails ("RESUME=" line not found).

- [ ] **Step 3: Add resume detection block**

In `openfoam-batch/scripts/admin/run_case_in_batch.sh`, after the `cp "${STAGE_DIR}/command.sh" "${CASE_DIR}/command.sh"` line and `chmod +x` (line ~49, before the `runtime.json` heredoc), insert:

```bash
CHECKPOINT_PREFIX="gs://${BUCKET}/checkpoints/${CASE_ID}/${VARIANT_ID}/latest"
RESUME=0
if gcloud storage ls "${CHECKPOINT_PREFIX}/" >/dev/null 2>&1; then
  RESUME=1
fi

if [[ "${RESUME}" == "1" ]]; then
  echo "Resuming from checkpoint ${CHECKPOINT_PREFIX}"
  gcloud storage rsync --recursive "${CHECKPOINT_PREFIX}/" "${CASE_DIR}/" || true
  if command -v foamDictionary >/dev/null 2>&1; then
    foamDictionary "${CASE_DIR}/system/controlDict" -entry startFrom -set latestTime || true
  fi
fi
```

- [ ] **Step 4: Run, verify both tests pass**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openfoam-batch/scripts/admin/run_case_in_batch.sh \
        openfoam-batch/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): detect resume + restore checkpoint + force latestTime

Pure GCS-existence check on checkpoints/CASE_ID/VARIANT_ID/latest/.
On resume: rsync the prefix into the case dir and force startFrom
latestTime in controlDict (idempotent)."
```

---

## Task 7 — Phase C: Background Checkpoint Loop

Add `checkpoint_loop` function, launch as background, capture PID. Stop in success path.

**Files:**
- Modify: `openfoam-batch/scripts/admin/run_case_in_batch.sh`
- Modify: `openfoam-batch/tests/run_case_in_batch_test.sh`

- [ ] **Step 1: Write failing test for the loop-launch + sync-on-new-dir behavior**

Append to `openfoam-batch/tests/run_case_in_batch_test.sh`:
```bash
start_test "checkpoint_loop function syncs when new processor0 timestep appears"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/scratch"
CASE_DIR="${SCRATCH_ROOT}/cx/case"
mkdir -p "${CASE_DIR}/processor0/0" "${CASE_DIR}/system"

# Source just the function from the runtime script (extract bash function)
# by sourcing a snippet that defines it. To make this self-contained, copy
# the function out into a probe file.
sed -n '/^checkpoint_loop()/,/^}/p' "${SCRIPT}" > "${TMPDIR_TEST}/loop.sh"

# shellcheck disable=SC1091
BUCKET=tb CASE_ID=cx VARIANT_ID=fixed CHECKPOINT_POLL_SEC=1 \
CASE_DIR="${CASE_DIR}" \
source "${TMPDIR_TEST}/loop.sh"

checkpoint_loop &
LOOP_PID=$!
sleep 2  # one poll cycle should be a no-op (no new dir since startup)

# Now create a "new" timestep dir and wait for next cycle
mkdir -p "${CASE_DIR}/processor0/100"
sleep 2

kill "${LOOP_PID}" 2>/dev/null || true
wait "${LOOP_PID}" 2>/dev/null || true

assert_contains "rsync" "$(cat "${GCLOUD_LOG}")" "loop invoked rsync after new timestep dir appeared"
assert_contains "checkpoints/cx/fixed/latest" "$(cat "${GCLOUD_LOG}")" "rsync target prefix"
teardown_tmp_workspace
```

- [ ] **Step 2: Run, verify FAIL** (function not yet defined; `sed -n` returns empty).

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: FAIL.

- [ ] **Step 3: Add checkpoint_loop function and launch it**

In `openfoam-batch/scripts/admin/run_case_in_batch.sh`, after the resume block from Task 6 and before the `cat > "${STAGE_DIR}/runtime.json"` heredoc, insert:

```bash
CHECKPOINT_POLL_SEC="${CHECKPOINT_POLL_SEC:-30}"

checkpoint_loop() {
  local last_seen=""
  while true; do
    sleep "${CHECKPOINT_POLL_SEC}"
    local newest
    newest=$(ls -1 "${CASE_DIR}/processor0" 2>/dev/null \
             | grep -E '^[0-9]+(\.[0-9]+)?$' \
             | sort -n | tail -1)
    if [[ -n "${newest}" && "${newest}" != "${last_seen}" ]]; then
      gcloud storage rsync --recursive \
        "${CASE_DIR}/processor*" \
        "${CHECKPOINT_PREFIX}/" || true
      gcloud storage rsync --recursive \
        "${CASE_DIR}/system" \
        "${CHECKPOINT_PREFIX}/system/" || true
      last_seen="${newest}"
    fi
  done
}
```

Then, after the `cd "${CASE_DIR}"` line (around line 61), and before the solver invocation, insert:

```bash
checkpoint_loop &
CHECKPOINT_PID=$!
```

In the success-path (after solver completes), before `tar -czf` (line ~70), add a stop:

```bash
if [[ -n "${CHECKPOINT_PID:-}" ]]; then
  kill "${CHECKPOINT_PID}" 2>/dev/null || true
  wait "${CHECKPOINT_PID}" 2>/dev/null || true
fi
```

- [ ] **Step 4: Run, verify pass**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openfoam-batch/scripts/admin/run_case_in_batch.sh \
        openfoam-batch/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): event-driven background checkpoint loop

Polls processor0/ every CHECKPOINT_POLL_SEC (default 30) and runs an
additive gcloud storage rsync only when a new timestep dir appears.
No tar, no gzip during the run. Loop is killed before the success-path
result tarball is built."
```

---

## Task 8 — Phase C: SIGTERM Trap + Per-Attempt Logs

Trap installs before solver launch. On SIGTERM: stop solver, final rsync, write `preempted.json`, copy attempt logs, exit 50000.

**Files:**
- Modify: `openfoam-batch/scripts/admin/run_case_in_batch.sh`
- Modify: `openfoam-batch/tests/run_case_in_batch_test.sh`

- [ ] **Step 1: Write failing test**

Append to `openfoam-batch/tests/run_case_in_batch_test.sh`:
```bash
start_test "on_sigterm: final rsync + preempted.json + exit 50000"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/scratch"
CASE_DIR="${SCRATCH_ROOT}/cx/case"
STAGE_DIR="${SCRATCH_ROOT}/cx/stage"
mkdir -p "${CASE_DIR}/processor0/100" "${CASE_DIR}/system" "${STAGE_DIR}"
echo "log so far" > "${STAGE_DIR}/solver.stdout.log"
echo "{}" > "${STAGE_DIR}/runtime.json"

# Extract the on_sigterm function only
sed -n '/^on_sigterm()/,/^}/p' "${SCRIPT}" > "${TMPDIR_TEST}/trap.sh"

# shellcheck disable=SC1091
BUCKET=tb CASE_ID=cx VARIANT_ID=fixed JOB_NAME=of-x BATCH_TASK_INDEX=0 \
RUN_TS=20260505T000000Z \
CASE_DIR="${CASE_DIR}" STAGE_DIR="${STAGE_DIR}" \
CHECKPOINT_PREFIX="gs://tb/checkpoints/cx/fixed/latest" \
RESULT_PREFIX="gs://tb/results/cx/fixed/of-x/task_0" \
SOLVER_PGID="" CHECKPOINT_PID="" \
source "${TMPDIR_TEST}/trap.sh"

# Run with subshell so exit doesn't kill our test
(on_sigterm) || rc=$?
assert_eq "50000" "${rc:-}" "exit code 50000"
assert_contains "rsync" "$(cat "${GCLOUD_LOG}")" "final rsync invoked"
assert_contains "preempted.json" "$(cat "${GCLOUD_LOG}")" "preempted.json uploaded"
assert_contains "attempts/20260505T000000Z" "$(cat "${GCLOUD_LOG}")" "logs copied to attempts dir"
teardown_tmp_workspace
```

- [ ] **Step 2: Run, verify FAIL** (function not defined).

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: FAIL.

- [ ] **Step 3: Add on_sigterm function and install trap**

In `openfoam-batch/scripts/admin/run_case_in_batch.sh`, after the `checkpoint_loop` definition, add:

```bash
on_sigterm() {
  trap '' TERM INT
  if [[ -n "${SOLVER_PGID:-}" ]]; then
    kill -TERM -"${SOLVER_PGID}" 2>/dev/null || true
    wait "${SOLVER_PID:-0}" 2>/dev/null || true
  fi
  if [[ -n "${CHECKPOINT_PID:-}" ]]; then
    kill "${CHECKPOINT_PID}" 2>/dev/null || true
  fi
  gcloud storage rsync --recursive \
    "${CASE_DIR}/processor*" \
    "${CHECKPOINT_PREFIX}/" || true
  gcloud storage rsync --recursive \
    "${CASE_DIR}/system" \
    "${CHECKPOINT_PREFIX}/system/" || true
  cat > "${STAGE_DIR}/preempted.json" <<EOF2
{
  "job_name": "${JOB_NAME}",
  "task_index": "${BATCH_TASK_INDEX:-0}",
  "attempt_ts": "${RUN_TS}",
  "reason": "preempted"
}
EOF2
  gcloud storage cp "${STAGE_DIR}/preempted.json" \
    "${CHECKPOINT_PREFIX}/preempted.json" || true
  if [[ -f "${STAGE_DIR}/solver.stdout.log" ]]; then
    gcloud storage cp "${STAGE_DIR}/solver.stdout.log" \
      "${RESULT_PREFIX}/attempts/${RUN_TS}/solver.stdout.log" || true
  fi
  if [[ -f "${STAGE_DIR}/runtime.json" ]]; then
    gcloud storage cp "${STAGE_DIR}/runtime.json" \
      "${RESULT_PREFIX}/attempts/${RUN_TS}/runtime.json" || true
  fi
  exit 50000
}
```

After `mkdir -p "${STAGE_DIR}" "${CASE_DIR}"` (line ~32), set `RUN_TS`:

```bash
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
```

After the `checkpoint_loop &` launch (Task 7), install the trap:

```bash
trap on_sigterm TERM INT
```

Modify the solver launch to capture process group id. Find:
```bash
set +e
bash ./command.sh 2>&1 | tee "${STAGE_DIR}/solver.stdout.log"
rc=${PIPESTATUS[0]}
set -e
```

Replace with:
```bash
set +e
setsid bash ./command.sh 2>&1 | tee "${STAGE_DIR}/solver.stdout.log" &
SOLVER_PID=$!
SOLVER_PGID=$(ps -o pgid= -p "${SOLVER_PID}" | tr -d ' ' || echo "")
wait "${SOLVER_PID}"
rc=$?
set -e
```

- [ ] **Step 4: Run, verify pass**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openfoam-batch/scripts/admin/run_case_in_batch.sh \
        openfoam-batch/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): SIGTERM trap with final flush + preempted.json

Solver runs under setsid so the trap can SIGTERM the whole process
group. On SIGTERM: final additive rsync, write preempted.json, copy
per-attempt logs to results/.../attempts/<RUN_TS>/, exit 50000 (matched
to lifecyclePolicies in the Batch JSON in a later commit)."
```

---

## Task 9 — Phase C: Success Cleanup + Per-Attempt Logs On Normal Paths

Always copy attempt logs to `attempts/<RUN_TS>/`. On rc=0, delete the checkpoint prefix from GCS.

**Files:**
- Modify: `openfoam-batch/scripts/admin/run_case_in_batch.sh`
- Modify: `openfoam-batch/tests/run_case_in_batch_test.sh`

- [ ] **Step 1: Write failing test**

Append to `openfoam-batch/tests/run_case_in_batch_test.sh`:
```bash
start_test "success path deletes checkpoint prefix"
setup_tmp_workspace
SCRATCH_ROOT="${TMPDIR_TEST}/scratch"
mkdir -p "${SCRATCH_ROOT}"
# Build a fake command.sh that exits 0 quickly
fake_case="${TMPDIR_TEST}/case_pkg"
mkdir -p "${fake_case}"
echo "echo solver" > "${fake_case}/command.sh"
chmod +x "${fake_case}/command.sh"

# We won't run the full runtime end-to-end (too much fakery). Instead,
# verify the cleanup line exists by grepping:
grep -q 'storage rm -r .*checkpoints/.*latest' "${SCRIPT}"
assert_eq "0" "$?" "cleanup rm -r line present in runtime"
teardown_tmp_workspace
```

(We grep rather than execute the full runtime here; full E2E covers the wired-up behavior.)

- [ ] **Step 2: Run, verify FAIL** (line not yet present).

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: FAIL.

- [ ] **Step 3: Add cleanup + per-attempt log copies on both paths**

In `openfoam-batch/scripts/admin/run_case_in_batch.sh`, find the success/fail block near the end:

```bash
if [[ "${rc}" -eq 0 ]]; then
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_SUCCESS"
  gcs_cp "${STAGE_DIR}/_SUCCESS" "${RESULT_PREFIX}/_SUCCESS"
else
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_FAILED"
  gcs_cp "${STAGE_DIR}/_FAILED" "${RESULT_PREFIX}/_FAILED"
fi
```

Replace with:
```bash
# Always copy attempt logs (success or fail).
gcloud storage cp "${STAGE_DIR}/runtime.json" \
  "${RESULT_PREFIX}/attempts/${RUN_TS}/runtime.json" || true
gcloud storage cp "${STAGE_DIR}/solver.stdout.log" \
  "${RESULT_PREFIX}/attempts/${RUN_TS}/solver.stdout.log" || true
gcloud storage cp "${STAGE_DIR}/exit_code.txt" \
  "${RESULT_PREFIX}/attempts/${RUN_TS}/exit_code.txt" || true

if [[ "${rc}" -eq 0 ]]; then
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_SUCCESS"
  gcs_cp "${STAGE_DIR}/_SUCCESS" "${RESULT_PREFIX}/_SUCCESS"
  gcloud storage rm -r "${CHECKPOINT_PREFIX}/" || true
else
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_FAILED"
  gcs_cp "${STAGE_DIR}/_FAILED" "${RESULT_PREFIX}/_FAILED"
  gcloud storage cp "${STAGE_DIR}/_FAILED" \
    "${RESULT_PREFIX}/attempts/${RUN_TS}/_FAILED" || true
fi
```

- [ ] **Step 4: Run, verify pass**

Run: `bash openfoam-batch/tests/run_case_in_batch_test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openfoam-batch/scripts/admin/run_case_in_batch.sh \
        openfoam-batch/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): per-attempt logs + checkpoint cleanup on success

Every terminal outcome copies runtime/solver/exit_code logs to
attempts/<RUN_TS>/. Success additionally removes the GCS checkpoint
prefix. Failure additionally writes _FAILED inside the attempt dir."
```

---

## Task 10 — Phase C: Spot/Retry/InstanceTermination JSON In submit_one_case.sh

Add `provisioningModel`, `maxRetryCount`, `lifecyclePolicies` (retry on exit 50000), `instanceTermination` (120 s) to the Batch JSON.

**Files:**
- Modify: `openfoam-batch/scripts/admin/submit_one_case.sh`
- Modify: `openfoam-batch/tests/submit_one_case_test.sh`

- [ ] **Step 1: Write failing tests**

Append to `openfoam-batch/tests/submit_one_case_test.sh`:
```bash
start_test "default JSON has STANDARD provisioning, maxRetryCount, lifecyclePolicy, 120s termination"
setup_tmp_workspace
JSON="$(GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  case_test fixed c2d-standard-16 \
  16000 8 65536 1 43200s 2>"${TMPDIR_TEST}/stderr")"
assert_eq "STANDARD" "$(echo "${JSON}" | jq -r '.allocationPolicy.instances[0].policy.provisioningModel')" "default STANDARD"
assert_eq "3" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.maxRetryCount')" "default maxRetryCount"
assert_eq "50000" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.lifecyclePolicies[0].actionCondition.exitCodes[0]')" "retry on 50000"
assert_eq "RETRY_TASK" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.lifecyclePolicies[0].action')" "RETRY_TASK action"
assert_eq "120s" "$(echo "${JSON}" | jq -r '.allocationPolicy.instanceTermination.preemptionDelay')" "120s graceful"
teardown_tmp_workspace

start_test "PROVISIONING_MODEL=SPOT and MAX_RETRY_COUNT override"
setup_tmp_workspace
JSON="$(PROVISIONING_MODEL=SPOT MAX_RETRY_COUNT=5 \
  GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  case_test fixed c2d-standard-16 \
  16000 8 65536 1 43200s 2>"${TMPDIR_TEST}/stderr")"
assert_eq "SPOT" "$(echo "${JSON}" | jq -r '.allocationPolicy.instances[0].policy.provisioningModel')" "SPOT"
assert_eq "5" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.maxRetryCount')" "retry override"
teardown_tmp_workspace
```

- [ ] **Step 2: Run, verify FAIL**

Run: `bash openfoam-batch/tests/submit_one_case_test.sh`
Expected: FAIL — fields not present.

- [ ] **Step 3: Add env-var defaults and JSON fields**

In `openfoam-batch/scripts/admin/submit_one_case.sh`, after the `MAX_RUN_DURATION` resolution block, add:

```bash
PROVISIONING_MODEL="${PROVISIONING_MODEL:-STANDARD}"
MAX_RETRY_COUNT="${MAX_RETRY_COUNT:-3}"
PREEMPTION_DELAY="${PREEMPTION_DELAY:-120s}"
```

In the JSON template, modify the `policy` block to include `provisioningModel`. Find:
```bash
        "policy": {
          "machineType": "${MACHINE_TYPE}",
${DISKS_BLOCK}
        }
```
Replace with:
```bash
        "policy": {
          "machineType": "${MACHINE_TYPE}",
          "provisioningModel": "${PROVISIONING_MODEL}",
${DISKS_BLOCK}
        }
```

Inside `taskSpec`, add `maxRetryCount` and `lifecyclePolicies`. Find the closing of `taskSpec` (look for `"maxRunDuration": ...`):
```bash
        "maxRunDuration": "${MAX_RUN_DURATION}",
${VOLUMES_BLOCK}
      }
    }
```
Replace with:
```bash
        "maxRunDuration": "${MAX_RUN_DURATION}",
        "maxRetryCount": ${MAX_RETRY_COUNT},
        "lifecyclePolicies": [
          {
            "actionCondition": { "exitCodes": [50000] },
            "action": "RETRY_TASK"
          }
        ],
${VOLUMES_BLOCK}
      }
    }
```

In `allocationPolicy`, add `instanceTermination`. Find the closing of `allocationPolicy`:
```bash
  "allocationPolicy": {
    "instances": [
      {
        "policy": {
...
        }
      }
    ]
  },
```
Replace with:
```bash
  "allocationPolicy": {
    "instances": [
      {
        "policy": {
...
        }
      }
    ],
    "instanceTermination": {
      "preemptionDelay": "${PREEMPTION_DELAY}"
    }
  },
```

(Leave the `...` exactly as it is in the script — only add the new `instanceTermination` block after the `instances` array.)

- [ ] **Step 4: Run, verify pass**

Run: `bash openfoam-batch/tests/submit_one_case_test.sh`
Expected: PASS.

- [ ] **Step 5: Verify JSON still parses**

Run:
```bash
GCLOUD_LS_HITS="" DRY_RUN=1 bash openfoam-batch/scripts/admin/submit_one_case.sh \
  p us-central1 img:1 case_x fixed c2d-standard-16 16000 8 65536 1 43200s | jq .
```
Expected: well-formed JSON output.

- [ ] **Step 6: Commit**

```bash
git add openfoam-batch/scripts/admin/submit_one_case.sh \
        openfoam-batch/tests/submit_one_case_test.sh
git commit -m "feat(submit): add Spot, retry, and 120s graceful-shutdown to Batch JSON

PROVISIONING_MODEL (default STANDARD, set SPOT to enable spot),
MAX_RETRY_COUNT (default 3), PREEMPTION_DELAY (default 120s).
A lifecyclePolicy retries on exit 50000 (the runtime's preemption
exit code)."
```

---

## Task 11 — submit_all_ready_cases.sh: Pass-Through New Env Vars

The bulk script forwards `PROVISIONING_MODEL`, `MAX_RETRY_COUNT`, etc. to `submit_one_case.sh`. They already inherit naturally via env, but we should document that explicitly and not strip them.

**Files:**
- Modify: `openfoam-batch/scripts/admin/submit_all_ready_cases.sh` (no behavior change; comment + verify env passes through)

- [ ] **Step 1: Inspect current behavior**

Run: `cat openfoam-batch/scripts/admin/submit_all_ready_cases.sh`
Note: env vars naturally inherit because `submit_one_case.sh` is invoked as a child process. No code change needed.

- [ ] **Step 2: Add a documenting comment header**

In `openfoam-batch/scripts/admin/submit_all_ready_cases.sh`, after the `set -euo pipefail` line, insert:

```bash
# Env vars passed through to each submit_one_case.sh invocation:
#   FORCE_SUBMIT, PROVISIONING_MODEL, MAX_RETRY_COUNT, PREEMPTION_DELAY,
#   SCRATCH_DISK_TYPE, SCRATCH_DISK_GB, CHECKPOINT_POLL_SEC, DRY_RUN.
```

- [ ] **Step 3: Commit**

```bash
git add openfoam-batch/scripts/admin/submit_all_ready_cases.sh
git commit -m "docs: list env vars that pass through to submit_one_case.sh"
```

---

## Task 12 — Phase A: New `submit_one_job_multi_task.sh`

Build one Batch job with `taskCount = N`, one VM per task, shared shape.

**Files:**
- Create: `openfoam-batch/scripts/admin/submit_one_job_multi_task.sh`
- Create: `openfoam-batch/tests/submit_one_job_multi_task_test.sh`

- [ ] **Step 1: Write failing test**

Create `openfoam-batch/tests/submit_one_job_multi_task_test.sh`:
```bash
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
# CASE_ID env var must NOT be set in multi-task mode
assert_eq "null" "$(echo "${JSON}" | jq -r '.taskGroups[0].taskSpec.environment.variables.CASE_ID // "null"')" "no single CASE_ID"
teardown_tmp_workspace

start_test "rejects empty case list"
setup_tmp_workspace
GCLOUD_LS_HITS="" DRY_RUN=1 bash "${SCRIPT}" \
  project-test us-central1 docker.io/test:1 \
  fixed c2d-standard-16 \
  16000 8 65536 1 43200s \
  >"${TMPDIR_TEST}/out" 2>"${TMPDIR_TEST}/err" && rc=0 || rc=$?
[[ "${rc}" -ne 0 ]] || { printf '  FAIL expected non-zero exit\n'; TEST_FAILURES=$((TEST_FAILURES+1)); }
teardown_tmp_workspace

exit "${TEST_FAILURES}"
```

Make executable: `chmod +x openfoam-batch/tests/submit_one_job_multi_task_test.sh`

- [ ] **Step 2: Run, verify FAIL** (script doesn't exist).

Run: `bash openfoam-batch/tests/submit_one_job_multi_task_test.sh`
Expected: FAIL — `bash: ...: No such file or directory`.

- [ ] **Step 3: Create the script**

Create `openfoam-batch/scripts/admin/submit_one_job_multi_task.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

sanitize_job_part() {
  local value="$1"
  value="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9-' '-')"
  value="$(printf '%s' "${value}" | sed -E 's/^-+//; s/-+$//; s/-+/-/g')"
  printf '%s\n' "${value}"
}

if [[ $# -lt 11 ]]; then
  cat >&2 <<EOF
Usage: $0 PROJECT_ID REGION IMAGE_URI VARIANT_ID MACHINE_TYPE \\
  CPU_MILLI MPI_RANKS MEMORY_MIB LOCAL_SSD_COUNT MAX_RUN_DURATION \\
  CASE_ID [CASE_ID ...]
EOF
  exit 1
fi

PROJECT_ID="$1"; REGION="$2"; IMAGE_URI="$3"
VARIANT_ID="$4"; MACHINE_TYPE="$5"
CPU_MILLI="$6"; MPI_RANKS="$7"; MEMORY_MIB="$8"
LOCAL_SSD_COUNT="$9"; MAX_RUN_DURATION="${10}"
shift 10
CASE_IDS=("$@")

if [[ ${#CASE_IDS[@]} -eq 0 ]]; then
  echo "At least one CASE_ID is required" >&2
  exit 1
fi

PROVISIONING_MODEL="${PROVISIONING_MODEL:-STANDARD}"
MAX_RETRY_COUNT="${MAX_RETRY_COUNT:-3}"
PREEMPTION_DELAY="${PREEMPTION_DELAY:-120s}"
SCRATCH_DISK_TYPE="${SCRATCH_DISK_TYPE:-pd-ssd}"
SCRATCH_DISK_GB="${SCRATCH_DISK_GB:-200}"

GCS_BUCKET="openfoam_cases"
BUCKET="${GCS_BUCKET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

JOB_TS="$(date +%Y%m%d%H%M%S)"
JOB_VARIANT_ID="$(sanitize_job_part "${VARIANT_ID}")"
JOB_NAME="of-multi-${JOB_VARIANT_ID}-${JOB_TS}"
CONFIG_PATH="${TMP_DIR}/${JOB_NAME}.json"

# Validate every case prefix unless DRY_RUN.
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  for cid in "${CASE_IDS[@]}"; do
    "${SCRIPT_DIR}/check_case_prefix.sh" "${cid}"
  done
  for cid in "${CASE_IDS[@]}"; do
    marker="gs://${BUCKET}/submissions/${cid}/${VARIANT_ID}.latest.json"
    if gcloud storage ls "${marker}" >/dev/null 2>&1 && [[ "${FORCE_SUBMIT:-0}" != "1" ]]; then
      echo "Submission marker exists for case=${cid} variant=${VARIANT_ID}" >&2
      echo "Set FORCE_SUBMIT=1 to override." >&2
      exit 1
    fi
  done
  gcloud config set project "${PROJECT_ID}" >/dev/null
fi

# Build disks block (same logic as submit_one_case.sh).
DISKS_BLOCK=$'          "disks": [\n'
if [[ "${LOCAL_SSD_COUNT}" != "0" ]]; then
  for ((i = 1; i <= LOCAL_SSD_COUNT; i++)); do
    DEVICE_NAME="openfoam-scratch-${i}"
    DISKS_BLOCK+=$'            {\n'
    DISKS_BLOCK+=$'              "newDisk": {\n'
    DISKS_BLOCK+=$'                "type": "local-ssd",\n'
    DISKS_BLOCK+=$'                "sizeGb": 375\n'
    DISKS_BLOCK+=$'              },\n'
    DISKS_BLOCK+="              \"deviceName\": \"${DEVICE_NAME}\""$'\n'
    DISKS_BLOCK+=$'            }'
    if (( i < LOCAL_SSD_COUNT )); then
      DISKS_BLOCK+=","
    fi
    DISKS_BLOCK+=$'\n'
  done
else
  DISKS_BLOCK+=$'            {\n'
  DISKS_BLOCK+=$'              "newDisk": {\n'
  DISKS_BLOCK+="                \"type\": \"${SCRATCH_DISK_TYPE}\","$'\n'
  DISKS_BLOCK+="                \"sizeGb\": ${SCRATCH_DISK_GB}"$'\n'
  DISKS_BLOCK+=$'              },\n'
  DISKS_BLOCK+=$'              "deviceName": "openfoam-scratch-1"\n'
  DISKS_BLOCK+=$'            }\n'
fi
DISKS_BLOCK+=$'          ]'

VOLUMES_BLOCK=$(cat <<EOF
        "volumes": [
          {
            "deviceName": "openfoam-scratch-1",
            "mountPath": "/mnt/disks/openfoam-scratch",
            "mountOptions": "rw,async"
          }
        ]
EOF
)

CASE_ID_LIST_CSV="$(IFS=,; printf '%s' "${CASE_IDS[*]}")"
TASK_COUNT=${#CASE_IDS[@]}

cat > "${CONFIG_PATH}" <<EOF
{
  "taskGroups": [
    {
      "taskCount": ${TASK_COUNT},
      "parallelism": ${TASK_COUNT},
      "taskSpec": {
        "runnables": [
          {
            "container": {
              "imageUri": "${IMAGE_URI}",
              "entrypoint": "/bin/bash",
              "commands": ["-lc", "/opt/openfoam-batch/run_case_in_batch.sh"]
            }
          }
        ],
        "environment": {
          "variables": {
            "BUCKET": "${BUCKET}",
            "CASE_ID_LIST": "${CASE_ID_LIST_CSV}",
            "VARIANT_ID": "${VARIANT_ID}",
            "JOB_NAME": "${JOB_NAME}",
            "CPU_MILLI": "${CPU_MILLI}",
            "MPI_RANKS": "${MPI_RANKS}",
            "SCRATCH_ROOT": "/mnt/disks/openfoam-scratch",
            "CHECKPOINT_POLL_SEC": "${CHECKPOINT_POLL_SEC:-30}"
          }
        },
        "computeResource": {
          "cpuMilli": ${CPU_MILLI},
          "memoryMib": ${MEMORY_MIB}
        },
        "maxRunDuration": "${MAX_RUN_DURATION}",
        "maxRetryCount": ${MAX_RETRY_COUNT},
        "lifecyclePolicies": [
          {
            "actionCondition": { "exitCodes": [50000] },
            "action": "RETRY_TASK"
          }
        ],
${VOLUMES_BLOCK}
      }
    }
  ],
  "allocationPolicy": {
    "instances": [
      {
        "policy": {
          "machineType": "${MACHINE_TYPE}",
          "provisioningModel": "${PROVISIONING_MODEL}",
${DISKS_BLOCK}
        }
      }
    ],
    "instanceTermination": {
      "preemptionDelay": "${PREEMPTION_DELAY}"
    }
  },
  "logsPolicy": { "destination": "CLOUD_LOGGING" },
  "labels": { "app": "openfoam" }
}
EOF

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  cat "${CONFIG_PATH}"
  exit 0
fi

gcloud batch jobs submit "${JOB_NAME}" \
  --location "${REGION}" \
  --config "${CONFIG_PATH}"

# Write one submission marker per case.
for idx in "${!CASE_IDS[@]}"; do
  cid="${CASE_IDS[${idx}]}"
  META_PATH="${TMP_DIR}/marker_${idx}.json"
  cat > "${META_PATH}" <<EOF
{
  "project_id": "${PROJECT_ID}",
  "region": "${REGION}",
  "bucket": "${BUCKET}",
  "case_id": "${cid}",
  "variant_id": "${VARIANT_ID}",
  "job_name": "${JOB_NAME}",
  "task_index": ${idx},
  "machine_type": "${MACHINE_TYPE}",
  "submitted_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
  gcloud storage cp "${META_PATH}" \
    "gs://${BUCKET}/submissions/${cid}/${VARIANT_ID}.latest.json"
done

echo "Submitted ${JOB_NAME} (${TASK_COUNT} tasks)"
```

- [ ] **Step 4: Make executable**

```bash
chmod +x openfoam-batch/scripts/admin/submit_one_job_multi_task.sh
```

- [ ] **Step 5: Run tests, verify pass**

Run: `bash openfoam-batch/tests/submit_one_job_multi_task_test.sh`
Expected: PASS.

- [ ] **Step 6: Run full suite**

Run: `bash openfoam-batch/tests/run_all.sh`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add openfoam-batch/scripts/admin/submit_one_job_multi_task.sh \
        openfoam-batch/tests/submit_one_job_multi_task_test.sh
git commit -m "feat(submit): add submit_one_job_multi_task.sh

Single Batch job with taskCount = parallelism = N, one CASE_ID per
task resolved by the runtime via CASE_ID_LIST + BATCH_TASK_INDEX. All
tasks share machine shape, MPI rank count, scratch disk, retry config
and Spot/STANDARD provisioning. One submission marker is written per
case after a successful submit."
```

---

## Task 13 — README Updates

**Files:**
- Modify: `openfoam-batch/README.md`

- [ ] **Step 1: Add a "Submission Modes" section near the top**

After the existing "Repo Structure" section, insert a new H2 "Submission Modes":

```markdown
## Submission Modes

Three modes, distinguished by how Batch tasks are organized:

| Mode | Script | taskCount | Submitted as | Use case |
|---|---|---|---|---|
| Single job, single task | `scripts/admin/submit_one_case.sh` | 1 | 1 Batch job | One case at a time |
| Multi job, single task | `scripts/admin/submit_all_ready_cases.sh` | 1 each | N Batch jobs | Bulk: every READY case → its own job |
| Single job, multi task | `scripts/admin/submit_one_job_multi_task.sh` | N | 1 Batch job | A named set of cases → one job, one VM per case |

The result path layout is uniform across all three:

`results/CASE_ID/VARIANT_ID/JOB_NAME/task_<i>/...`

Single-task jobs always use `task_0`. Multi-task jobs index `task_<i>` from `BATCH_TASK_INDEX`.
```

- [ ] **Step 2: Add a "Spot VMs and Fault Tolerance" section**

After "Submission Modes":

```markdown
## Spot VMs and Fault Tolerance

Spot is opt-in via env var:

```bash
PROVISIONING_MODEL=SPOT MAX_RETRY_COUNT=3 ./scripts/admin/submit_one_case.sh ...
```

Behavior on a Spot VM:

- Graceful shutdown window is set to 120 seconds via `instanceTermination.preemptionDelay`.
- The runtime continuously rsyncs solver state to `gs://<bucket>/checkpoints/CASE_ID/VARIANT_ID/latest/` (event-driven, additive — no tar/gzip during the run).
- On preemption (SIGTERM): runtime kills the solver, runs one final rsync, writes `preempted.json`, copies attempt logs to `results/.../task_<i>/attempts/<RUN_TS>/`, exits 50000.
- A `lifecyclePolicies` rule classifies exit 50000 as `RETRY_TASK`; Batch reschedules on a fresh VM up to `maxRetryCount` times.
- The retry attempt detects the GCS checkpoint, restores it, forces `startFrom latestTime`, and resumes from where it left off.

The checkpoint is automatically deleted from GCS on a successful run. Orphan checkpoints are cleaned by a one-time bucket lifecycle rule (see "GCS Lifecycle" below).
```

- [ ] **Step 3: Add a "GCS Lifecycle" section**

After the "GCS Layout" section:

```markdown
## GCS Lifecycle Rule

Apply once per bucket:

```bash
cat > /tmp/openfoam-lifecycle.json <<EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": { "type": "Delete" },
        "condition": { "age": 30, "matchesPrefix": ["checkpoints/"] }
      }
    ]
  }
}
EOF
gcloud storage buckets update gs://openfoam_cases \
  --lifecycle-file=/tmp/openfoam-lifecycle.json
```

This deletes any object under `checkpoints/` older than 30 days. `cases/`, `results/`, and `submissions/` are untouched.
```

- [ ] **Step 4: Update existing parameters list to mention new env vars**

In the "Current Parameter Baseline" section, append after the existing list:

```markdown
New env-var knobs (Phase C/D additions):

- `PROVISIONING_MODEL` — `STANDARD` (default) or `SPOT`.
- `MAX_RETRY_COUNT` — Batch task retries on top of the original attempt; default `3`.
- `PREEMPTION_DELAY` — graceful shutdown window for Spot VMs; default `120s`.
- `SCRATCH_DISK_TYPE` — when `LOCAL_SSD_COUNT=0`, the type of the attached scratch PD; default `pd-ssd`.
- `SCRATCH_DISK_GB` — scratch PD size when `LOCAL_SSD_COUNT=0`; default `200`.
- `CHECKPOINT_POLL_SEC` — runtime poll interval for new timestep dirs; default `30`.
- `DRY_RUN=1` — submit scripts print the JSON instead of calling `gcloud batch jobs submit`. Used by tests.
```

- [ ] **Step 5: Replace the "Local SSD note" block**

In the "Current Parameter Baseline" section, replace the entire "Local SSD note" + "Boot disk note" + "Prior reference note" blocks with:

```markdown
Scratch disk note:

- `LOCAL_SSD_COUNT > 0` (only on families that support it, e.g. `c2d`): one or more 375 GB local SSDs attached, mounted at `/mnt/disks/openfoam-scratch`.
- `LOCAL_SSD_COUNT = 0` (e.g. `c3d`, `h3`): one attached pd-ssd of `${SCRATCH_DISK_GB}` GB, mounted at the same path. The boot disk is no longer used as scratch fallback; missing scratch is now a hard error in the runtime.

Prior reference note:

- `c2d-standard-8` took about `1h 24m` for the earlier reference run.
```

- [ ] **Step 6: Add a "Tests" section**

Append a new H2 at the end:

```markdown
## Tests

Local bash tests covering submit-script JSON shape and runtime helper functions:

```bash
bash openfoam-batch/tests/run_all.sh
```

Tests use PATH-stubbed `gcloud` and `foamDictionary`; no GCP credentials needed. End-to-end testing against a real GCP project is manual and documented in the implementation plan.
```

- [ ] **Step 7: Commit**

```bash
git add openfoam-batch/README.md
git commit -m "docs: document multi-task mode, Spot fault tolerance, GCS lifecycle"
```

---

## Task 14 — Image Rebuild + Push

The runtime container must include the updated `run_case_in_batch.sh`. No code change in the Dockerfile, but the image must be rebuilt with a new tag.

**Files:** none

- [ ] **Step 1: Verify the Dockerfile still copies the runtime script**

Run: `grep -n run_case_in_batch openfoam-batch/Dockerfile`
Expected: a `COPY scripts/admin/run_case_in_batch.sh ...` line.

- [ ] **Step 2: Rebuild and push (run from `openfoam-batch/`)**

```bash
cd openfoam-batch
docker buildx build \
  --platform linux/amd64 \
  -t docker.io/kartikeyattri/openfoam:13 \
  --push .
```

(Pick the next tag — `:13` here. Bump on each runtime change.)

Expected: build succeeds, image pushed.

- [ ] **Step 3: No git commit needed for image rebuild itself**

(Image tag is a runtime parameter passed to submit scripts.)

---

## Task 15 — Apply The GCS Lifecycle Rule (One-Time)

**Files:** none

- [ ] **Step 1: Apply the lifecycle rule**

Run:
```bash
cat > /tmp/openfoam-lifecycle.json <<EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": { "type": "Delete" },
        "condition": { "age": 30, "matchesPrefix": ["checkpoints/"] }
      }
    ]
  }
}
EOF
gcloud storage buckets update gs://openfoam_cases \
  --lifecycle-file=/tmp/openfoam-lifecycle.json
```

- [ ] **Step 2: Verify**

Run:
```bash
gcloud storage buckets describe gs://openfoam_cases --format="value(lifecycle)"
```
Expected: output shows the `Delete` rule with `matchesPrefix=checkpoints/` and `age=30`.

---

## Task 16 — End-To-End Smoke Tests (Manual, Against Real GCP)

These can't be automated by the agent. Run each, observe, and only call the migration done after they pass.

**Files:** none

- [ ] **Step 1: Smoke — single-task STANDARD on c2d (regression check)**

```bash
./scripts/admin/submit_one_case.sh \
  project-688a4c78-5d5b-45b3-b5d us-central1 \
  docker.io/kartikeyattri/openfoam:13 \
  case_0002 fixed c2d-standard-16 16000 8 65536 1 43200s
```

Verify:
- Job runs to completion.
- Result lands at `gs://openfoam_cases/results/case_0002/fixed/<JOB_NAME>/task_0/_SUCCESS`.
- An `attempts/<RUN_TS>/` subdir exists with logs.

- [ ] **Step 2: Smoke — single-task STANDARD on c3d (pd-ssd path)**

```bash
LOCAL_SSD_COUNT=0 \
./scripts/admin/submit_one_case.sh \
  project-688a4c78-5d5b-45b3-b5d us-central1 \
  docker.io/kartikeyattri/openfoam:13 \
  case_0003 c3d c3d-standard-8 8000 4 32768 0 43200s
```

Verify:
- Job runs to completion. Inspect Batch logs to confirm scratch is mounted at `/mnt/disks/openfoam-scratch` (no `/tmp` references).
- pd-ssd disk visible in Compute Engine console while the VM is alive.

- [ ] **Step 3: Smoke — multi-task STANDARD with two cases**

```bash
./scripts/admin/submit_one_job_multi_task.sh \
  project-688a4c78-5d5b-45b3-b5d us-central1 \
  docker.io/kartikeyattri/openfoam:13 \
  multitest c2d-standard-16 16000 8 65536 1 43200s \
  case_0002 case_0003
```

Verify:
- One Batch job, two tasks.
- Two VMs come up in parallel.
- Results land at `results/case_0002/multitest/<JOB>/task_0/` and `results/case_0003/multitest/<JOB>/task_1/`.
- Submission markers exist for both: `submissions/case_0002/multitest.latest.json` and `submissions/case_0003/multitest.latest.json`.

- [ ] **Step 4: Smoke — Spot preemption resume**

Submit a longer-running case on Spot:

```bash
PROVISIONING_MODEL=SPOT MAX_RETRY_COUNT=3 \
./scripts/admin/submit_one_case.sh \
  project-688a4c78-5d5b-45b3-b5d us-central1 \
  docker.io/kartikeyattri/openfoam:13 \
  case_0002 spot-resume c2d-standard-16 16000 8 65536 1 43200s
```

Wait until the solver writes its first timestep dir (verify via `gcloud storage ls gs://openfoam_cases/checkpoints/case_0002/spot-resume/latest/processor0/`). Then manually preempt the VM:

```bash
gcloud compute instances list --filter="labels.batch-job-id=<JOB_NAME>"
gcloud compute instances simulate-maintenance-event <INSTANCE_NAME> --zone=<ZONE>
```

Or stop it with:
```bash
gcloud compute instances stop <INSTANCE_NAME> --zone=<ZONE>
```

Verify within ~2 minutes:
- `preempted.json` appears at `gs://.../checkpoints/case_0002/spot-resume/latest/preempted.json`.
- `attempts/<TS>/solver.stdout.log` appears under `task_0/`.
- A new Batch task attempt starts on a different VM.
- The new attempt's `solver.stdout.log` shows OpenFOAM resuming from `latestTime` (look for `Time = <T>` matching the last checkpointed timestep).
- On final success, the `checkpoints/...` prefix is deleted.

- [ ] **Step 5: Smoke — retry budget exhaustion**

Temporarily upload a `command.sh` for a test case that exits non-zero immediately. Submit with `MAX_RETRY_COUNT=2`:

```bash
MAX_RETRY_COUNT=2 \
./scripts/admin/submit_one_case.sh ...
```

Verify:
- Batch attempts 1 + 2 retries = 3 attempts total.
- Three `attempts/<TS>/` subdirs at `results/.../task_0/`.
- `_FAILED` written at the canonical `task_0/` path.
- Checkpoint **not** deleted (retained for inspection).

- [ ] **Step 6: Mark migration complete**

After all six smoke checks pass, the implementation is verified end-to-end.

---

## Self-Review Checklist (For The Plan Author)

- [x] Spec coverage: Phase A (Tasks 5, 12), Phase B (Tasks 4, 8, 9), Phase C (Tasks 6, 7, 8, 9, 10, 11, 15), Phase D (Tasks 2, 3). All four phases addressed.
- [x] No "TBD" / "TODO" / "implement later" placeholders.
- [x] Type/name consistency: `CHECKPOINT_PREFIX`, `RESULT_PREFIX`, `RUN_TS`, `CHECKPOINT_PID`, `SOLVER_PID`, `SOLVER_PGID`, `CASE_ID_LIST`, `BATCH_TASK_INDEX`, `TASK_INDEX` used consistently across tasks.
- [x] All tests have concrete code; commands have expected output.
- [x] Frequent commits: 13 commits across 12 implementation tasks (Tasks 14–16 are operational, no commits).

---

## Open Items For Implementor

1. **Batch JSON field for graceful shutdown** — `allocationPolicy.instanceTermination.preemptionDelay` is the field used in this plan, derived from spec intent and current Batch docs as of writing. Confirm the field name in the implementation against `gcloud batch jobs describe` output on a real Spot job before relying on it; if it differs, update Task 10 and Task 12 JSON accordingly. The exit-code-50000 + lifecyclePolicies path is independently load-bearing, so even if `preemptionDelay` is wrong the resume flow still works (with the default 30 s window).
2. **`setsid` availability** — used in Task 8 to run the solver in its own process group so the trap can SIGTERM the whole tree. Check `which setsid` inside the runtime image; it's normally part of `util-linux`. If absent, add `apt-get install -y util-linux` to the Dockerfile.
3. **Multi-attempt `_FAILED` overwrite policy** — current plan writes `_FAILED` at the canonical path on every non-preempt failure attempt. Successful retry overwrites with `_SUCCESS`. If you ever want "only the final attempt's `_FAILED` is canonical," that's a future change — Batch's lack of attempt-count visibility makes it hard to detect "this is the last attempt" without an external poller.
