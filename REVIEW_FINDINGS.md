# Repository Audit Findings

## Executive summary

- No Critical findings. The highest risks are operational correctness and cost controls, not a direct unauthenticated remote code path.
- The backend can mark any `case_id` as `READY` and can submit jobs for any `case_id` without checking reservation, uploaded files, `command.sh`, or `validate_case()`.
- Checkpoints are keyed only by `case_id` + machine-derived `variant`, so two runs of the same case on the same machine write the same checkpoint prefix and can corrupt or resume from each other.
- Batch specs deliberately omit `maxRunDuration`, so a hung solver or stalled `command.sh` can run until manually stopped.
- Multi-case jobs set `parallelism == taskCount` with no server-side cap, so a large request can fan out into many expensive VMs at once.
- The checkpoint loop still only watches `processor0`; serial runs, or parallel runs before `processor0` exists, silently stop checkpointing.
- Default Batch retries rerun every non-zero solver failure up to three times, even when the failure is deterministic rather than preemption-related.
- The one-time infra setup script points at a non-existent runtime Dockerfile path, and the shell infra scripts continue after failures because they do not use `set -e`.
- Existing tests pass in the repo venv, runtime bash tests pass, and frontend tests pass, but several tests explicitly assert risky behavior such as no `maxRunDuration` and full fan-out parallelism.

## Findings table

| ID | Severity | File:line | Issue (one line) | Why it matters | Suggested fix | Confidence |
|---|---|---:|---|---|---|---|
| F-001 | High | `backend/routes_cases.py:56`, `backend/routes_jobs.py:26`, `cli/main.py:86` | Case readiness is not enforced before finalization or job submission. | A caller can mark an empty/arbitrary case as `READY` and submit a Batch VM that fails immediately or runs against unintended objects. | Persist expected upload manifests at allocation; finalize only reserved cases whose expected files exist; call `validate_case()` before every API/CLI submit. | High |
| F-002 | High | `core/naming.py:15`, `runtime/run_case_in_batch.sh:27` | Checkpoint prefix is shared by all jobs for the same case and machine. | Concurrent reruns or double-clicked submits write the same `checkpoints/<case>/<machine>/latest/` tree and can corrupt resumes. | Include `JOB_NAME` or a run UUID in checkpoint paths, or add a server-side case/machine lock and explicit resume source. | High |
| F-003 | High | `core/batch_jobs.py:78` | Batch jobs have no `maxRunDuration`. | A hung solver, blocked network call, or bad script can burn VM cost indefinitely until someone notices and stops it. | Add a configurable timeout per job/machine/case size; expose it in API/CLI and set Batch `maxRunDuration`. | High |
| F-004 | High | `core/batch_jobs.py:159`, `backend/schemas.py:17` | Multi-case runs fan out all tasks concurrently with no cap. | A large `case_ids` list can schedule dozens/hundreds of VMs at once, exhausting quota or causing a cost spike. | Add `max_length` on submit, cap `parallelism`, and make concurrency an explicit validated setting. | High |
| F-005 | High | `runtime/run_case_in_batch.sh:61` | Checkpoint loop silently exits/no-ops when `processor0` is absent. | Serial cases are never checkpointed, and parallel cases are unprotected until `processor0` has a numeric time directory. | Detect both serial time directories and `processor*/`; avoid `set -e` termination on empty `grep`; log when no checkpointable state exists. | High |
| F-006 | High | `core/batch_jobs.py:100`, `core/batch_jobs.py:87` | Default retries rerun every solver failure, not just interruption/preemption. | A deterministic bad `command.sh` or invalid case can consume four attempts and may resume from stale/partial checkpoints. | Default standard jobs to zero retries; classify retryable interruption exits explicitly; use retry policies tied to Spot/preemption only. | Medium |
| F-007 | High | `cli/main.py:60`, `cli/main.py:63` | CLI explicit `--case-id` uploads can overwrite existing cases. | A typo or reused ID can replace another case tree and mark it `READY` without an exclusive reservation. | For explicit IDs, require `create_exclusive()` or `--force`; refuse if `repo.exists(case_id)` is true. | High |
| F-008 | High | `infra/setup-cfd-lemnisca.sh:52` | Setup script builds a non-existent runtime image path. | Fresh setup fails at the runtime image build step because `openfoam-batch/Dockerfile` is not in this repo. | Use `phase3-run-app/runtime/Dockerfile` and build context `phase3-run-app/runtime`, matching the README. | High |
| F-009 | Medium | `core/uploads.py:20`, `backend/routes_cases.py:24` | Signed upload object names accept arbitrary relative paths. | API callers can create objects with `..`, empty segments, control characters, or names that may behave badly when later `rsync`ed. | Validate file paths as POSIX relative paths: no empty segments, no `.`/`..`, no leading slash, no control chars, and reasonable length. | Medium |
| F-010 | Medium | `core/uploads.py:47`, `frontend/src/lib/upload.ts:31` | Signed PUT URLs do not constrain size, checksum, or content type. | Any authenticated user with a URL can upload unexpectedly huge or corrupt objects, causing storage cost and runtime failures. | Store expected file sizes/checksums from allocation; enforce upload limits where possible and validate object metadata before finalize. | Medium |
| F-011 | Medium | `runtime/run_case_in_batch.sh:40`, `runtime/run_case_in_batch.sh:51` | Checkpoint restore and checkpoint writes swallow `gcloud` failures. | A job can silently start from missing/partial state or lose checkpoint updates while logs only show best-effort behavior. | Fail restore when a checkpoint prefix exists but cannot be copied; count/report checkpoint upload failures and surface them in runtime metadata. | High |
| F-012 | Medium | `runtime/run_case_in_batch.sh:85`, `runtime/run_case_in_batch.sh:87` | Stop handler likely records the pipeline/`tee` process group, not the solver process group. | Manual stops may not signal the actual solver cleanly before final checkpoint sync, risking partial or stale checkpoints. | Launch the solver in a named process/session whose PID/PGID is captured directly; test TERM handling with a long-running fake solver. | Medium |
| F-013 | Medium | `core/status.py:35`, `frontend/src/views/RunsView.tsx:37` | Runs polling lists every Batch job every 4 seconds. | With job history and multiple users, each UI tab repeatedly pages all jobs, increasing latency and API load. | Use Batch pagination/page size/filtering, cache status briefly, and lower or back off polling when idle. | High |
| F-014 | Medium | `infra/deploy-cfd-lemnisca.sh:6`, `infra/setup-cfd-lemnisca.sh:11` | Infra scripts omit `set -e`. | A failed build/deploy/IAM command can be followed by later steps, leaving a partially configured environment that looks successful. | Use `set -euo pipefail`; add explicit checks around intentionally idempotent commands. | High |
| F-015 | Medium | `infra/deploy-cfd-lemnisca.sh:39`, `backend/main.py:6` | Manual IAP deploy instructions do not match the active auth dependency. | The script tells operators to set `OF_IAP_AUDIENCE`, but API routes use `backend.auth.current_user` and require Bearer Google ID tokens. | Remove or rewrite the IAP script, or wire routes to `backend.iap.current_user` for IAP deployments. | High |
| F-016 | Medium | `.github/workflows/deploy.yml:53`, `.github/workflows/deploy.yml:65` | CI does not fail fast when `OAUTH_CLIENT_ID` is missing. | The build/deploy can succeed while the SPA has no client ID and all users see a sign-in configuration error. | Add an early shell guard that exits if `${{ vars.OAUTH_CLIENT_ID }}` is empty. | High |
| F-017 | Medium | `infra/setup-cfd-lemnisca.sh:85`, `infra/setup-cfd-lemnisca.sh:87` | Backend and job service accounts get bucket-wide `storage.objectAdmin`. | Either identity can delete or overwrite all cases, checkpoints, and results; compromise blast radius is the whole bucket. | Use least-privilege custom roles and IAM Conditions/prefix separation where possible. | Medium |
| F-018 | Low | `backend/iap.py:20` | IAP user extraction does not enforce domain/hosted-domain. | If the unused IAP dependency is later wired in with broader IAP IAM, app-level domain checks disappear. | Mirror `backend.auth.user_from_idinfo()` domain policy or make IAP IAM scope explicit in code/tests. | Medium |
| F-019 | Low | `core/storage.py:3`, `core/validation.py:37` | `StorageClient` protocol omits `list_paths()` despite validation/status depending on it. | Type checks and fakes cannot express the real interface; future storage implementations can fail at runtime. | Add `list_paths(prefix: str)` to the protocol and implement it on `InMemoryStorage`. | High |
| F-020 | Low | `frontend/src/lib/api.ts:45` | `runDetail()` query parameters are not URL-encoded. | A job, case, or variant containing query delimiters can produce malformed requests. | Use `URLSearchParams` for `case_id` and `variant`. | Medium |
| F-021 | Low | `frontend/src/lib/auth.ts:21` | Bearer ID tokens are persisted in `localStorage`. | Any future XSS bug can read the token for the rest of the session. | Prefer in-memory/session storage, shorten token lifetime, and add strict CSP if persistence is required. | Medium |
| F-022 | Low | `phase3-run-app/frontend/vite.config.ts:10` | Local Vite dev proxies to the production backend by default. | Local UI experiments can upload to the real bucket and submit real Batch jobs. | Default to a local/scratch API or require an explicit `VITE_API_TARGET` opt-in for production. | High |

## Detailed findings

### F-001: Case readiness is not enforced before finalization or submission

`backend/routes_cases.py:56` writes `manifest.json` and `READY` for whatever `case_id` appears in the path. It does not check that the ID was reserved, that the allocated uploads completed, or that `case/command.sh` exists. `backend/routes_jobs.py:26` then canonicalizes submitted IDs and builds a Batch job without calling `CaseRepository.exists()` or `validate_case()`. The CLI has the same submit gap at `cli/main.py:86`. A direct API caller can `POST /api/cases/case_9999:finalize` and then submit a VM that downloads an empty/malformed case tree. Fix this by recording expected files during allocation, verifying them on finalize, and validating every case before API/CLI submission.

### F-002: Checkpoint prefix is shared by all jobs for the same case and machine

`variant_for_machine()` returns only the sanitized machine type (`core/naming.py:15`), and the runtime checkpoint prefix is `checkpoints/${CASE_ID}/${VARIANT_ID}/latest` (`runtime/run_case_in_batch.sh:27`). Two jobs for `case_0001` on `c2d-highcpu-56` write the same checkpoint tree even though their result prefixes differ by `JOB_NAME`. The README already warns not to resubmit a running job, which confirms this is a known operational footgun rather than an enforced invariant. Either include `JOB_NAME`/run UUID in the checkpoint prefix, or add backend locks and make resume targets explicit.

### F-003: Batch jobs have no `maxRunDuration`

`core/batch_jobs.py:78` explicitly omits `maxRunDuration`. A hung solver, infinite loop in `command.sh`, deadlocked `mpirun`, or blocked GCS call can keep expensive Batch VMs alive until manual intervention. This should be a validated job setting with a conservative default and an override for exceptional cases. The current test at `tests/test_batch_jobs.py:12` asserts the risky behavior instead of guarding a timeout.

### F-004: Multi-case runs fan out all tasks concurrently with no cap

`build_multi()` sets `parallelism` equal to `len(case_ids)` at `core/batch_jobs.py:159`, and `SubmitReq.case_ids` has only `min_length=1` at `backend/schemas.py:17`. The upload allocation route caps cases at 200, but submit has no comparable limit and API callers are not constrained by the UI. A request with many cases can attempt to schedule many VMs immediately. Add server-side `max_length`, validate against quota/cost policy, and set a separate bounded `parallelism`.

### F-005: Checkpoint loop silently exits/no-ops when `processor0` is absent

The checkpoint loop computes `newest` with `ls "${CASE_DIR}/processor0" | grep ...` at `runtime/run_case_in_batch.sh:61` while the script has `set -euo pipefail`. If `processor0` does not exist or contains no numeric time directories, the command substitution can return non-zero and kill the background checkpoint loop. Even if it stayed alive, `sync_checkpoint()` only uploads `processor*/` plus `system/` at lines 48-54, so serial time directories under `case/<time>/` are never checkpointed. Handle serial and parallel layouts explicitly, and make empty state a logged condition rather than a silent background-loop exit.

### F-006: Default retries rerun every solver failure, not just interruption/preemption

`build_single()` and `build_multi()` default `max_retry_count=3` (`core/batch_jobs.py:100`, `core/batch_jobs.py:132`), and `_task_spec()` passes that directly to Batch (`core/batch_jobs.py:87`). The runtime comments at `runtime/run_case_in_batch.sh:66` note there is no preemption-specific exit handling. That means ordinary solver failures, missing files, or bad scripts are retried repeatedly. Use zero retries for standard deterministic failures, or return a special retryable exit only when the VM was interrupted/preempted.

### F-007: CLI explicit `--case-id` uploads can overwrite existing cases

When `--case-id` is not `AUTO`, `cli/main.py:60` canonicalizes the ID and proceeds. It does not reserve the ID or check whether it already exists before `gcloud storage rsync` at line 63 and writing `READY` at line 70. An operator can accidentally overwrite another case tree by reusing an ID. Require an exclusive marker for explicit IDs too, or add a loud `--force` path.

### F-008: Setup script builds a non-existent runtime image path

`infra/setup-cfd-lemnisca.sh:52` uses `-f "${REPO_ROOT}/openfoam-batch/Dockerfile"` and line 53 uses `"${REPO_ROOT}/openfoam-batch"` as the build context. The tracked runtime files live under `phase3-run-app/runtime/`. Fresh setup will fail at the runtime image build step. Update the script to match the README's runtime build command.

### F-009: Signed upload object names accept arbitrary relative paths

`object_path()` only strips leading slashes (`core/uploads.py:20`), and `allocate()` passes `case.files` directly into signed URL generation (`backend/routes_cases.py:24`). Browser folder uploads usually produce safe paths, but API callers can request names containing `..`, empty segments, control characters, or odd object names that later interact badly with `gcloud storage rsync`. Validate uploaded file paths as normalized relative POSIX paths before signing.

### F-010: Signed PUT URLs do not constrain size, checksum, or content type

`SignedUrlService.put_url()` signs a bare PUT at `core/uploads.py:47`, and the browser uploads the raw `File` body at `frontend/src/lib/upload.ts:31`. There is no expected size/checksum metadata and no finalize-time verification, so an authenticated user can upload oversized or corrupt objects and still finalize. Capture expected metadata during allocation and verify object size/hash before writing `READY`.

### F-011: Checkpoint restore and checkpoint writes swallow `gcloud` failures

When a checkpoint prefix exists, the restore `rsync` is followed by `|| true` at `runtime/run_case_in_batch.sh:40`. Checkpoint writes also ignore failures at lines 51 and 54. If permissions, transient network, or malformed object names break restore/write, the run continues with missing or stale state. Restores from an advertised checkpoint should fail loudly if copy fails; checkpoint write failures should be counted and surfaced in `runtime.json` or logs.

### F-012: Stop handler likely records the pipeline/`tee` process group, not the solver process group

The solver is launched as `setsid bash ./command.sh 2>&1 | tee ... &` at `runtime/run_case_in_batch.sh:85`. `$!` is then stored at line 86 and its PGID captured at line 87. In bash, `$!` for a background pipeline is typically the last pipeline process (`tee`), while `setsid bash` creates a separate session for the solver. The TERM handler at line 70 may signal the wrong process group. Capture the solver PID/PGID directly and add a runtime test that sends TERM to a long-running fake solver.

### F-013: Runs polling lists every Batch job every 4 seconds

The frontend polls every 4 seconds (`frontend/src/views/RunsView.tsx:37`). Each backend call materializes every Batch job with `list(self._b.list_jobs(...))` at `core/status.py:35`, sorts them client-side, then slices. As job history grows, every open tab does full-list work repeatedly. Use server-side pagination/page size, cache status briefly, and back off polling for idle tabs.

### F-014: Infra scripts omit `set -e`

Both `infra/deploy-cfd-lemnisca.sh:6` and `infra/setup-cfd-lemnisca.sh:11` use `set -uo pipefail`, not `set -euo pipefail`. A failed Docker build, deploy, IAM command, or bucket update can be followed by later steps. That creates partial environments that appear to have completed. Add `set -e` and wrap only intentionally idempotent commands with explicit `|| echo "(exists)"`.

### F-015: Manual IAP deploy instructions do not match the active auth dependency

`infra/deploy-cfd-lemnisca.sh:39` tells operators to set `OF_IAP_AUDIENCE`, and lines 41-48 say the app verifies IAP JWTs. The active FastAPI routes are imported from `backend.main.py:6` and those routers depend on `backend.auth.current_user`, which checks `Authorization: Bearer ...`, not `X-Goog-IAP-JWT-Assertion`. This script is stale relative to the current public-ingress OAuth design. Remove it, or wire a true IAP deployment mode.

### F-016: CI does not fail fast when `OAUTH_CLIENT_ID` is missing

The workflow passes `${{ vars.OAUTH_CLIENT_ID }}` into the frontend build at `.github/workflows/deploy.yml:53` and runtime env at line 65, but there is no guard that the variable is set. The README notes the deployed app becomes unusable with an empty client ID. Add an early step like `test -n '${{ vars.OAUTH_CLIENT_ID }}'` before building.

### F-017: Backend and job service accounts get bucket-wide `storage.objectAdmin`

`infra/setup-cfd-lemnisca.sh:85` and line 87 grant both service accounts `roles/storage.objectAdmin` on the bucket. The job identity needs broad enough write/read access for cases, results, and checkpoints, but objectAdmin also allows deleting or overwriting everything in the bucket. Reduce blast radius with custom roles and prefix-level IAM Conditions where practical.

### F-018: IAP user extraction does not enforce domain/hosted-domain

`backend/iap.py:20` accepts any IAP JWT with an `email` claim. If this currently unused dependency is later wired in, the app-level `hd == lemnisca.bio` enforcement from `backend/auth.py:23` does not carry over. Either remove the unused IAP module or add equivalent domain/hosted-domain checks and tests.

### F-019: `StorageClient` protocol omits `list_paths()`

The protocol in `core/storage.py:3` lists `object_exists`, `create_exclusive`, `upload_bytes`, `read_text`, and `list_case_ids`, but `core/validation.py:37` dynamically calls `storage.list_paths("cases/")` for non-memory storage. `RunStatusService` also calls `list_paths()` when checking checkpoints. Add `list_paths(prefix: str)` to the protocol and implement it on the fake so storage implementations are type-checkable and testable.

### F-020: `runDetail()` query parameters are not URL-encoded

`frontend/src/lib/api.ts:45` interpolates `caseId` and `variant` directly into a query string. Current values are usually sanitized machine/case IDs, but the backend accepts these as free strings and future variants may contain delimiters. Build the URL with `URLSearchParams`.

### F-021: Bearer ID tokens are persisted in `localStorage`

`frontend/src/lib/auth.ts:21` stores the Google ID token in `localStorage`. That keeps sessions across refreshes, but any future XSS can read the bearer token until expiry. Consider in-memory/session-only storage, a stricter CSP, or a backend session cookie if persistence is required.

### F-022: Local Vite dev proxies to production by default

`phase3-run-app/frontend/vite.config.ts:10` defaults `VITE_API_TARGET` to the deployed Cloud Run service. The README warns this can hit the real bucket and real Batch jobs during local UI work. Use a local/scratch default and require an explicit opt-in to production.

## Per-file coverage checklist

| File | Status |
|---|---|
| `.github/workflows/deploy.yml` | findings: F-016 |
| `README.md` | clean |
| `benchmarks/bench_1.html` | skipped-trivial |
| `benchmarks/bench_2.html` | skipped-trivial |
| `phase3-run-app/.dockerignore` | skipped-trivial |
| `phase3-run-app/.gitignore` | skipped-trivial |
| `phase3-run-app/README.md` | findings: F-002, F-003, F-005, F-022 |
| `phase3-run-app/backend/.dockerignore` | skipped-trivial |
| `phase3-run-app/backend/Dockerfile` | clean |
| `phase3-run-app/backend/__init__.py` | clean |
| `phase3-run-app/backend/auth.py` | clean |
| `phase3-run-app/backend/deps.py` | clean |
| `phase3-run-app/backend/iap.py` | findings: F-018 |
| `phase3-run-app/backend/main.py` | findings: F-015 |
| `phase3-run-app/backend/routes_cases.py` | findings: F-001, F-009 |
| `phase3-run-app/backend/routes_jobs.py` | findings: F-001 |
| `phase3-run-app/backend/schemas.py` | findings: F-004 |
| `phase3-run-app/backend/static/index.html` | skipped-trivial |
| `phase3-run-app/cli/__init__.py` | clean |
| `phase3-run-app/cli/main.py` | findings: F-001, F-007 |
| `phase3-run-app/core/__init__.py` | clean |
| `phase3-run-app/core/batch_jobs.py` | findings: F-002, F-003, F-004, F-006 |
| `phase3-run-app/core/cases.py` | clean |
| `phase3-run-app/core/config.py` | clean |
| `phase3-run-app/core/disks.py` | clean |
| `phase3-run-app/core/machines.py` | clean |
| `phase3-run-app/core/naming.py` | findings: F-002 |
| `phase3-run-app/core/status.py` | findings: F-013, F-019 |
| `phase3-run-app/core/storage.py` | findings: F-019 |
| `phase3-run-app/core/uploads.py` | findings: F-009, F-010 |
| `phase3-run-app/core/validation.py` | findings: F-019 |
| `phase3-run-app/frontend/.gitignore` | skipped-trivial |
| `phase3-run-app/frontend/README.md` | skipped-trivial |
| `phase3-run-app/frontend/components.json` | skipped-trivial |
| `phase3-run-app/frontend/eslint.config.js` | skipped-trivial |
| `phase3-run-app/frontend/index.html` | clean |
| `phase3-run-app/frontend/package-lock.json` | skipped-trivial |
| `phase3-run-app/frontend/package.json` | clean |
| `phase3-run-app/frontend/public/favicon.svg` | skipped-trivial |
| `phase3-run-app/frontend/public/icons.svg` | skipped-trivial |
| `phase3-run-app/frontend/src/App.css` | skipped-trivial |
| `phase3-run-app/frontend/src/App.tsx` | clean |
| `phase3-run-app/frontend/src/assets/hero.png` | skipped-trivial |
| `phase3-run-app/frontend/src/assets/react.svg` | skipped-trivial |
| `phase3-run-app/frontend/src/assets/vite.svg` | skipped-trivial |
| `phase3-run-app/frontend/src/components/AppShell.tsx` | clean |
| `phase3-run-app/frontend/src/components/SignInGate.tsx` | clean |
| `phase3-run-app/frontend/src/components/ui/badge.tsx` | clean |
| `phase3-run-app/frontend/src/components/ui/button.tsx` | clean |
| `phase3-run-app/frontend/src/components/ui/progress.tsx` | clean |
| `phase3-run-app/frontend/src/components/ui/separator.tsx` | clean |
| `phase3-run-app/frontend/src/index.css` | skipped-trivial |
| `phase3-run-app/frontend/src/lib/api.ts` | findings: F-020 |
| `phase3-run-app/frontend/src/lib/auth.ts` | findings: F-021 |
| `phase3-run-app/frontend/src/lib/client.ts` | clean |
| `phase3-run-app/frontend/src/lib/machines.ts` | clean |
| `phase3-run-app/frontend/src/lib/motion.ts` | clean |
| `phase3-run-app/frontend/src/lib/upload.ts` | findings: F-010 |
| `phase3-run-app/frontend/src/lib/utils.ts` | clean |
| `phase3-run-app/frontend/src/main.tsx` | clean |
| `phase3-run-app/frontend/src/styles.css` | skipped-trivial |
| `phase3-run-app/frontend/src/tests/api.test.ts` | findings: F-020 coverage gap |
| `phase3-run-app/frontend/src/tests/auth.test.ts` | findings: F-021 coverage note |
| `phase3-run-app/frontend/src/tests/upload.test.ts` | clean |
| `phase3-run-app/frontend/src/views/CasesView.tsx` | clean |
| `phase3-run-app/frontend/src/views/RunView.tsx` | clean |
| `phase3-run-app/frontend/src/views/RunsView.tsx` | findings: F-013 |
| `phase3-run-app/frontend/src/views/UploadView.tsx` | findings: F-009, F-010 |
| `phase3-run-app/frontend/tsconfig.app.json` | skipped-trivial |
| `phase3-run-app/frontend/tsconfig.json` | skipped-trivial |
| `phase3-run-app/frontend/tsconfig.node.json` | skipped-trivial |
| `phase3-run-app/frontend/vite.config.ts` | findings: F-022 |
| `phase3-run-app/infra/deploy-cfd-lemnisca.sh` | findings: F-014, F-015 |
| `phase3-run-app/infra/of-cases-cors.json` | clean |
| `phase3-run-app/infra/setup-cfd-lemnisca.sh` | findings: F-008, F-014, F-017 |
| `phase3-run-app/pyproject.toml` | clean |
| `phase3-run-app/requirements-backend.txt` | clean |
| `phase3-run-app/runtime/Dockerfile` | clean |
| `phase3-run-app/runtime/run_case_in_batch.sh` | findings: F-002, F-005, F-011, F-012 |
| `phase3-run-app/runtime/tests/lib/stubs/foamDictionary` | clean |
| `phase3-run-app/runtime/tests/lib/stubs/gcloud` | clean |
| `phase3-run-app/runtime/tests/lib/test_helpers.sh` | clean |
| `phase3-run-app/runtime/tests/run_all.sh` | clean |
| `phase3-run-app/runtime/tests/run_case_in_batch_test.sh` | findings: F-005, F-012 coverage gaps |
| `phase3-run-app/tests/__init__.py` | clean |
| `phase3-run-app/tests/test_auth.py` | clean |
| `phase3-run-app/tests/test_auth_gate.py` | clean |
| `phase3-run-app/tests/test_batch_job_sa.py` | clean |
| `phase3-run-app/tests/test_batch_jobs.py` | findings: F-003, F-004, F-006 assertions |
| `phase3-run-app/tests/test_cases.py` | clean |
| `phase3-run-app/tests/test_config.py` | clean |
| `phase3-run-app/tests/test_disks.py` | clean |
| `phase3-run-app/tests/test_iap.py` | findings: F-018 coverage gap |
| `phase3-run-app/tests/test_machines.py` | clean |
| `phase3-run-app/tests/test_naming.py` | findings: F-002 coverage gap |
| `phase3-run-app/tests/test_routes_cases.py` | findings: F-001, F-009 coverage gaps |
| `phase3-run-app/tests/test_routes_jobs.py` | findings: F-001, F-004 coverage gaps |
| `phase3-run-app/tests/test_status.py` | findings: F-005 coverage gap |
| `phase3-run-app/tests/test_storage_fake.py` | findings: F-019 coverage gap |
| `phase3-run-app/tests/test_uploads.py` | findings: F-009, F-010 coverage gaps |
| `phase3-run-app/tests/test_validation.py` | clean |

## Verification

- `phase3-run-app/.venv/bin/python -m pytest -q`: 63 passed, 1 warning.
- `bash phase3-run-app/runtime/tests/run_all.sh`: passed.
- `npm test -- --run` in `phase3-run-app/frontend`: 3 test files / 10 tests passed.
