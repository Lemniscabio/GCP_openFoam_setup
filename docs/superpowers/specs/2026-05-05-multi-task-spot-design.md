# Multi-Task Submit, GCS Layout, Spot Fault Tolerance, and Disk Strategy

Date: 2026-05-05
Status: Approved design (pending spec review)

## Goal

Extend the OpenFOAM Batch workflow with a third submission mode (single-job, multi-task), reorganize result/checkpoint paths so the layout works across all three modes without collisions, make every mode fault-tolerant under Spot VM preemption, and pick a scratch-disk strategy that is durable-by-design (durability via GCS, not via disk).

## Scope

This spec covers four phases:

- **Phase A** — New `submit_one_job_multi_task.sh` script (single Batch job, `taskCount = N`, one task per case).
- **Phase B** — GCS path layout changes that work for all three modes (single/single, multi/single, single/multi).
- **Phase C** — Spot fault tolerance: continuous GCS checkpoint, SIGTERM trap, automatic Batch retry, resume-from-checkpoint flow.
- **Phase D** — Scratch disk strategy: always `newDisk`, always pd-ssd in the no-local-SSD branch, no boot-disk fallback.

Out of scope: Filestore/NFS, hyperdisk, GCS FUSE, regional/multi-region buckets, IAM rework beyond the minimum needed, changes to the professor upload script.

## Existing System (recap)

Today the repo supports two submission modes:

1. **Single job, single task** — `submit_one_case.sh`: one Batch job with `taskCount=1`, runs one `CASE_ID`.
2. **Multi job, single task** — `submit_all_ready_cases.sh`: loops over READY cases, calls `submit_one_case.sh` once per case → N independent Batch jobs.

The runtime container entrypoint `run_case_in_batch.sh` downloads the case from GCS, runs the professor's `command.sh`, tars the result and uploads it back. There is no checkpointing, no preemption handling, no retry-aware resume.

Result path today:

```
results/CASE_ID/VARIANT_ID/JOB_NAME/{manifest.json, runtime.json, solver.stdout.log, exit_code.txt, result.tar.gz, _SUCCESS|_FAILED}
```

Scratch storage: local-SSD when `LOCAL_SSD_COUNT > 0`, otherwise a fallback to `/tmp/openfoam-scratch` on the 30 GB default boot disk.

## Phase A — Single-Job Multi-Task Submit Script

### New file

`scripts/admin/submit_one_job_multi_task.sh`

### CLI

```
submit_one_job_multi_task.sh \
  PROJECT_ID REGION IMAGE_URI VARIANT_ID MACHINE_TYPE \
  CPU_MILLI MPI_RANKS MEMORY_MIB LOCAL_SSD_COUNT MAX_RUN_DURATION \
  CASE_ID [CASE_ID ...]
```

The trailing variadic list of `CASE_ID`s is the only structural difference vs. `submit_one_case.sh`. The single `CASE_ID` slot disappears; `VARIANT_ID` is shared across all cases in the submission. All resource/shape parameters are shared across all tasks in the job.

### Behavior

1. Validate inputs. Abort with a non-zero exit if any of the following fail:
   - At least one `CASE_ID` provided.
   - For every `CASE_ID`: `check_case_prefix.sh` passes (i.e. all required objects + `READY` exist).
   - Pre-existing submission marker check per case: if `submissions/CASE_ID/VARIANT_ID.latest.json` exists for any case in the list, abort unless `FORCE_SUBMIT=1`.
2. Build one Batch job JSON:
   - `taskGroups[0].taskCount = len(CASE_IDS)`.
   - `taskGroups[0].parallelism = len(CASE_IDS)` (one VM per task).
   - One shared `machineType`, `cpuMilli`, `memoryMib`, disk policy, `maxRunDuration`.
   - `taskSpec.maxRetryCount: ${MAX_RETRY_COUNT:-3}` (configurable via env var).
   - Environment variables include both:
     - `CASE_ID_LIST="case_a,case_b,case_c"` (comma-separated, position = task index).
     - `BUCKET`, `VARIANT_ID`, `JOB_NAME`, `CPU_MILLI`, `MPI_RANKS`, `SCRATCH_ROOT` (same as today).
   - The single-CASE_ID `CASE_ID` env var is NOT set in this mode; the runtime resolves the case from `CASE_ID_LIST[BATCH_TASK_INDEX]`.
3. Submit the job with `gcloud batch jobs submit`.
4. After successful submission, write one submission marker per case:
   - Path: `submissions/CASE_ID/VARIANT_ID.latest.json` for each case.
   - Each marker carries: `project_id`, `region`, `bucket`, `case_id`, `variant_id`, `job_name`, `task_index`, `machine_type`, `submitted_at_utc`.

### Job naming

`of-multi-${SANITIZED_VARIANT}-${TS}` — case IDs are too many to fit in the job name. The `CASE_ID` is preserved per-task in the result path and submission markers.

### Runtime impact

`run_case_in_batch.sh` resolves `CASE_ID` at startup:

```bash
if [[ -n "${CASE_ID_LIST:-}" ]]; then
  IFS=',' read -ra CASE_LIST <<< "${CASE_ID_LIST}"
  CASE_ID="${CASE_LIST[${BATCH_TASK_INDEX:?}]}"
fi
: "${CASE_ID:?CASE_ID is required}"
```

The same script handles all three modes; existing single-case env var usage continues to work when `CASE_ID_LIST` is unset.

### Sanity constraints

- All CASE_IDs in a single submission share the same `VARIANT_ID`. Different variants → separate submissions.
- All CASE_IDs share the same machine shape, MPI rank count, and disk config. Mixed shapes → separate submissions.

## Phase B — GCS Path Layout

### Result path (every mode)

```
results/CASE_ID/VARIANT_ID/JOB_NAME/task_<BATCH_TASK_INDEX>/
  manifest.json
  runtime.json
  solver.stdout.log
  exit_code.txt
  result.tar.gz
  _SUCCESS | _FAILED
  attempts/<UTC_TS>/
    runtime.json
    solver.stdout.log
    exit_code.txt
    _FAILED
```

Rules:

- `task_<INDEX>` is **always present**, including in single-task jobs (always `task_0`). Eliminates per-mode special-cases.
- The flat top-level files (`result.tar.gz`, `_SUCCESS`/`_FAILED`, `manifest.json`, `runtime.json`, `solver.stdout.log`, `exit_code.txt`) are the **canonical final outcome** of the task. Overwritten by whichever attempt is final.
- `attempts/<UTC_TS>/` is written on every attempt (success or fail) and contains a per-attempt copy of `runtime.json`, `solver.stdout.log`, `exit_code.txt`. Only failed attempts also write a `_FAILED` marker inside their attempt dir. This preserves forensic history without duplicating the (large) `result.tar.gz` per attempt.

### Checkpoint path

```
checkpoints/CASE_ID/VARIANT_ID/latest/
  processor0/<times>/...
  processor1/<times>/...
  ...
  system/controlDict
  system/...
  preempted.json
```

Rules:

- Keyed by `(CASE_ID, VARIANT_ID)` only. **Not** `JOB_NAME`-scoped, because resume happens in a different job/VM (potentially with a different `JOB_NAME`) than the one that wrote the checkpoint.
- `preempted.json` is written by the SIGTERM trap. Its presence is informational; resume detection is a pure existence check on the prefix.

### Submissions path (unchanged)

```
submissions/CASE_ID/VARIANT_ID.latest.json
```

For multi-task submissions, one marker is written per case in the list; each marker carries the shared `JOB_NAME` plus the per-case `task_index`.

### Cases path (unchanged)

```
cases/CASE_ID/{case.tar.gz, command.sh, manifest.json, SHA256SUMS, READY}
```

## Phase C — Spot Fault Tolerance

### Job-level config (Batch JSON)

- `allocationPolicy.instances[].policy.provisioningModel: "SPOT"` (configurable; STANDARD remains the default until a `--spot` flag or `PROVISIONING_MODEL` env var is set).
- `taskSpec.maxRetryCount: ${MAX_RETRY_COUNT:-3}`.
- `taskSpec.lifecyclePolicies` retries on **exit code 50001** (Batch's documented Spot-preemption exit code; the trap exits with this code).
- **Preemption window is whatever Batch's default is** (currently 30 s for Spot). GCP Batch's `InstancePolicy` does not expose `scheduling.gracefulShutdown` or `scheduling.preemptionNoticeDuration` — extending the window to 120 s requires switching from the inline `policy` to an `instanceTemplate` reference, which is a substantial refactor (out of scope; tracked as a deferred upgrade). The design is built around the 30 s default: the continuous rsync minimizes the SIGTERM-to-flush data volume so 30 s is enough for typical cases.

### Runtime — checkpoint side-process

A bash function in `run_case_in_batch.sh`, launched as a background job after case extraction and before `command.sh` starts. Pseudocode:

```bash
checkpoint_loop() {
  local last_seen=""
  while true; do
    sleep "${CHECKPOINT_POLL_SEC:-30}"
    local newest
    newest=$(ls -1 "${CASE_DIR}/processor0" 2>/dev/null \
             | grep -E '^[0-9]+(\.[0-9]+)?$' \
             | sort -n | tail -1)
    if [[ -n "${newest}" && "${newest}" != "${last_seen}" ]]; then
      gcloud storage rsync --recursive \
        "${CASE_DIR}/processor*" \
        "gs://${BUCKET}/checkpoints/${CASE_ID}/${VARIANT_ID}/latest/"
      gcloud storage rsync --recursive \
        "${CASE_DIR}/system" \
        "gs://${BUCKET}/checkpoints/${CASE_ID}/${VARIANT_ID}/latest/system/"
      last_seen="${newest}"
    fi
  done
}
```

Properties:

- **Event-driven, not timer-driven.** The poller wakes every `CHECKPOINT_POLL_SEC` (default 30 s), but only uploads when a new timestep dir has appeared in `processor0/`. No work when the solver hasn't produced new data.
- **Additive, no deletion.** No `--delete-unmatched-destination-objects`. Older timestep dirs in GCS are preserved across cycles. Same code path serves steady-state and transient runs; transient cases gain full timestep history as a side benefit.
- **No tar, no gzip during the run.** `gcloud storage rsync` ships raw files; rsync skips identical destinations so each cycle only transfers truly-new files.
- **Re-entrant safe.** A single instance of the background loop runs per task. If a sync is still in-flight when the next poll fires, the next poll's check returns the same `newest` and is a no-op.

### SIGTERM trap (preemption handler)

Behavior on `SIGTERM` (and `SIGINT` for safety):

1. Stop the solver process group (kill `mpirun` / `command.sh`).
2. Run **one final** event-driven rsync (same commands as the loop).
3. Write `preempted.json` to the checkpoint dir with `{ job_name, task_index, attempt_ts, reason: "preempted" }`.
4. Copy the attempt's logs to `results/.../task_<i>/attempts/${RUN_TS}/{runtime.json, solver.stdout.log, exit_code.txt}`. No `_FAILED` marker at the top level (this is a preemption, not a failure).
5. Exit non-zero so Batch reschedules a retry on a new VM.

The 30 s default Spot window is sufficient for these five steps in typical cases: the continuous loop has already shipped most data, so the final flush is just the delta since the last successful sync (typically tens of MB to a few hundred MB). For very large or slow-network cases, more than one writeInterval of work may be lost on preemption — accepted trade-off given Batch's inability to extend the window.

### Resume detection

Pure GCS existence check at the start of `run_case_in_batch.sh`:

```bash
RESUME=0
if gcloud storage ls "gs://${BUCKET}/checkpoints/${CASE_ID}/${VARIANT_ID}/latest/" >/dev/null 2>&1; then
  RESUME=1
fi
```

No reliance on Batch attempt-index env vars (Batch does not expose this cleanly). The `(CASE_ID, VARIANT_ID)` pair is the resume identity.

### Resume execution

1. Always: download `case.tar.gz`, `command.sh`, `manifest.json`, verify `SHA256SUMS`, extract.
2. If `RESUME=1`:
   - `gcloud storage rsync` the checkpoint into `${CASE_DIR}` (overlays `processor*/` and `system/`).
   - `foamDictionary system/controlDict -entry startFrom -set latestTime` (idempotent — applied unconditionally is also safe).
3. Run `command.sh` as today.

The solver picks up from `latestTime` automatically once `processor*/<latestTime>/` is populated.

### Cleanup

- **On success (rc=0):** `gcloud storage rm -r "gs://${BUCKET}/checkpoints/${CASE_ID}/${VARIANT_ID}/latest/" || true` at the end of the runtime script. Leading-edge cleanup of the resume payload, which is now redundant with `result.tar.gz`.
- **On preempt or non-zero exit:** keep the checkpoint. It is either the resume payload (preempt → next attempt) or post-mortem evidence (failure).
- **Bucket-level lifecycle rule (one-time bucket configuration):** scope = `prefix: "checkpoints/"`, condition = `age > 30 days`, action = delete. Catches orphans from abandoned cases and crashed cleanups. Does not affect `cases/`, `results/`, or `submissions/`.

### Per-attempt log housekeeping

- At runtime start: `RUN_TS=$(date -u +%Y%m%dT%H%M%SZ)`.
- On every terminal outcome (success, normal failure, preemption):
  - Copy `runtime.json`, `solver.stdout.log`, `exit_code.txt` to `results/.../task_<i>/attempts/${RUN_TS}/`.
- On success only:
  - Copy the same three files plus `result.tar.gz` and `_SUCCESS` to the canonical `task_<i>/` path (overwriting any prior attempt's outcome).
- On final non-success (last retry exhausted):
  - Copy logs and `_FAILED` to the canonical `task_<i>/` path.

## Phase D — Disk Strategy

### Decision

Scratch is **always ephemeral, always per-VM** (`newDisk`). Durability is provided exclusively by the Phase C GCS checkpoint. Disk choice is purely a question of capacity and I/O performance during the run.

### Two-tier scratch

| `LOCAL_SSD_COUNT` | Tier | Mechanism |
|---|---|---|
| `> 0` | Local SSD (375 GB per device) | `newDisk: { type: "local-ssd", sizeGb: 375 }` × N |
| `= 0` | Attached pd-ssd | `newDisk: { type: "${SCRATCH_DISK_TYPE:-pd-ssd}", sizeGb: ${SCRATCH_DISK_GB:-200} }` |

In both cases the scratch device is mounted at `/mnt/disks/openfoam-scratch` via the existing `volumes` block. The runtime's `SCRATCH_ROOT=/mnt/disks/openfoam-scratch` is now true unconditionally — the `/tmp/openfoam-scratch` boot-disk fallback in `run_case_in_batch.sh` is **removed**.

### Boot disk

Stays at the GCP Batch default (30 GB pd-balanced). Solver scratch never touches it. The commented-out `bootDisk` block in `submit_one_case.sh` is removed.

### New CLI knobs

Added to both `submit_one_case.sh` and `submit_one_job_multi_task.sh`:

- `SCRATCH_DISK_TYPE` (env var, default `pd-ssd`) — only consulted when `LOCAL_SSD_COUNT=0`. Allows `pd-balanced` for cheaper/slower runs.
- `SCRATCH_DISK_GB` (env var, default `200`) — only consulted when `LOCAL_SSD_COUNT=0`.
- `MAX_RETRY_COUNT` (env var, default `3`) — for the new Batch retry behavior.
- `PROVISIONING_MODEL` (env var, default `STANDARD`; set to `SPOT` to enable Spot).
- `CHECKPOINT_POLL_SEC` (env var, default `30`) — runtime poll interval.

### Updated machine-family compatibility

| Family | Default scratch | Notes |
|---|---|---|
| `c2d` | `LOCAL_SSD_COUNT=1` → local-ssd 375 GB | unchanged |
| `c3d` | `LOCAL_SSD_COUNT=0` → pd-ssd 200 GB attached | replaces boot-disk fallback |
| `h3` | `LOCAL_SSD_COUNT=0` → pd-ssd 200 GB attached | replaces boot-disk fallback |

### Known characteristic, not a bug

pd-ssd small-file IOPS are meaningfully lower than local-SSD for the bursty per-rank field-write pattern at writeInterval boundaries. For benchmarking parity across families, expect c3d/h3 wall-clock to be modestly higher than raw vCPU count would predict. Documented behavior, not in scope to fix in this round. Future upgrade paths if it becomes a bottleneck: hyperdisk-extreme, or pinning to local-SSD-supporting families.

## Component Boundaries

After this work, the system has these units, each with a single purpose:

- **`scripts/prof/professor_upload_case.sh`** — professor case upload. Unchanged.
- **`scripts/prof/command.sh`** — professor case logic. Unchanged.
- **`scripts/admin/check_case_prefix.sh`** — admin pre-submit validation. Unchanged.
- **`scripts/admin/submit_one_case.sh`** — single-job-single-task submit. Updated to use the new disk policy and accept the new env vars (`SCRATCH_DISK_TYPE`, `SCRATCH_DISK_GB`, `MAX_RETRY_COUNT`, `PROVISIONING_MODEL`, `CHECKPOINT_POLL_SEC`). Boot-disk fallback comment block removed.
- **`scripts/admin/submit_all_ready_cases.sh`** — multi-job-single-task submit (loop). Updated to pass through the new env vars.
- **`scripts/admin/submit_one_job_multi_task.sh`** — **NEW.** Single-job-multi-task submit.
- **`scripts/admin/run_case_in_batch.sh`** — Batch runtime. Updated for: `CASE_ID_LIST` resolution from `BATCH_TASK_INDEX`, checkpoint loop background process, SIGTERM trap, resume detection + restore, per-attempt log paths, `task_<INDEX>` segment in result paths, removal of `/tmp/openfoam-scratch` fallback.
- **`Dockerfile`** — unchanged structurally (still copies `run_case_in_batch.sh` into the image). Image rebuild + push required.

## GCS State Machine (Per Case, Per Variant)

```
                          (no marker)
                              │
                              │ submit_*.sh writes
                              ▼
              submissions/CASE_ID/VARIANT_ID.latest.json
                              │
                              │ runtime starts on Batch VM
                              ▼
                        runtime running
                ┌─────────────┼─────────────┐
                │             │             │
            (writes)      (SIGTERM)      (rc=0)
                │             │             │
                ▼             ▼             ▼
         checkpoints/   checkpoints/   results/.../task_<i>/
         (incremental)  (final flush + (_SUCCESS,
                        preempted.json) result.tar.gz)
                                            +
                                       checkpoints/ removed
```

Retries reuse the same `submissions/` marker; each attempt writes its own `attempts/<UTC_TS>/` subtree under the result path. The canonical top-level `task_<i>/` files reflect the final outcome.

## Failure Modes And Handling

| Failure | Detection | Handling |
|---|---|---|
| Spot preemption | SIGTERM | Trap → final rsync → preempted.json → exit non-zero → Batch retry → next attempt resumes from checkpoint |
| Solver crash (non-preempt) | rc != 0, no SIGTERM | Logs to `attempts/<TS>/`, no checkpoint cleanup; Batch retry → next attempt resumes from checkpoint (likely re-fails unless intermittent) |
| Retry budget exhausted | Batch reports `FAILED` after `maxRetryCount` | Last attempt's logs + `_FAILED` at canonical path; checkpoint retained for manual inspection until lifecycle rule removes it |
| GCS rsync transient failure | `gcloud storage rsync` non-zero exit | Logged, but the loop continues; next cycle retries the upload (rsync is idempotent) |
| `decomposePar` runs on resume | `command.sh` runs `decomposePar -force` even when resuming | Acceptable: `decomposePar` overwrites the checkpoint-restored `processor*/0/` content but does **not** touch later timestep dirs. Solver still resumes from `latestTime`. This is a known minor inefficiency, not a correctness issue. |

## Testing Plan (high level)

Detailed test plan is the responsibility of the implementation plan. At spec level:

1. End-to-end smoke for each mode on STANDARD provisioning (verifies path layout + retry config doesn't break the happy path).
2. Forced preemption test on Spot: short case + manual VM termination during a writeInterval gap → verify resume produces correct final result.
3. Multi-task happy path: 2–3 cases in one submission → verify `task_<i>/` separation, all `_SUCCESS` markers written.
4. Retry-budget-exhausted test: deliberately broken `command.sh` → verify `_FAILED` at canonical path and per-attempt logs preserved.
5. Lifecycle-rule verification: confirm checkpoints older than 30 days are deleted, others retained.

## Non-Goals / Explicit Deferrals

- Mixed machine shapes within one multi-task job. (Out of scope; one shape per submission.)
- Existing-disk PD reuse on retry. (Decided against; complexity vs. marginal benefit.)
- 120 s Spot preemption notice via `scheduling.preemptionNoticeDuration`. (Decided against; requires moving from inline `InstancePolicy` to `instanceTemplate`, which forces machineType + scratch-disk config into N pre-created templates. Deferred until measured preemption losses justify it.)
- Filestore/NFS/hyperdisk. (Future, only if pd-ssd I/O proves bottleneck.)
- Steady-state-only checkpoint pruning. (Decided against; additive sync serves both regimes uniformly.)
- Boot disk size/type changes. (Boot disk no longer touches scratch; default 30 GB pd-balanced is sufficient.)
- IAM rework beyond ensuring the default Compute Engine SA can read/write `cases/`, `results/`, `submissions/`, and `checkpoints/`.

## Open Questions

None at spec time. All clarifying decisions captured.
