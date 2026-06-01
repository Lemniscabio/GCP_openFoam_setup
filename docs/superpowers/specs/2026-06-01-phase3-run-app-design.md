# Phase 3 — Run App (GCS upload + Cloud Batch submit) — Design Spec

**Date:** 2026-06-01
**Status:** Design approved; ready for implementation planning
**Author:** kartikey (with Claude as design partner)
**Executor model:** Claude orchestrates/instructs; **Codex implements** in a separate terminal. This spec must therefore be self-contained and unambiguous for a fresh-context executor.

---

## 1. Purpose & context

This is **Phase 3** of a 3-phase agentic automation pipeline (Phase 1: CAD via Salome MCP; Phase 2: CFD via OpenFOAM MCP — both future). Phase 3 is the **human-interaction layer**: turn the current "clone the repo and run `gcloud`/bash scripts in a terminal" workflow into a **web app any org member with IAM access can use** — drag-drop case folders, upload to GCS, browse cases, run them on Cloud Batch, and see status/feedback.

The CLI workflow must keep working unchanged; the web app is **additive**, built on the same engine.

### Non-goals (v1)
- No Phase 1/2 work (only structure the repo so they can attach later).
- No live solver-log streaming inside our UI (deep-link to Cloud Logging instead).
- No database (GCS is the source of truth).
- No Spot-by-default; Spot is an optional per-run toggle.

---

## 2. Architecture

**One Cloud Run service** — FastAPI serves both the static SPA and the REST API — **behind Identity-Aware Proxy (IAP)**. Single gate, no CORS, minimal auth code.

```
Org user (browser)
   │  Google org sign-in handled by IAP (no app auth code)
   ▼
Identity-Aware Proxy  — rejects anyone without roles/iap.httpsResourceAccessor
   ▼
Cloud Run service (1)  — FastAPI, runtime SA (least privilege)
   • serves built static SPA (GET /)
   • REST API (/api/*)
   • verifies IAP JWT, reads user email/sub
   • imports → core/ (pure engine)
   │                                  │
   │ signed POST policy               │ Batch SDK: jobs.create/get/list
   │ (browser PUTs files direct)      │ GCS SDK: list cases, read markers
   ▼                                  ▼
gs://of-cases  (cases/, results/, checkpoints/, submissions/)
                                      │
                                      ▼
                           Cloud Batch → c2d-highcpu VM
                             runs openfoam:12.x.x image (run_case_in_batch.sh)
```

**Key properties**
- Browser never receives GCP credentials. Large case files go **browser → GCS directly** via a signed POST policy (one signature per case). The server never proxies file bytes.
- `core/` is **pure logic** — no HTTP, no `gcloud` shell-outs; uses `google-cloud-storage` + `google-cloud-batch`. Both the FastAPI backend and the CLI import it, so every fix lives in one place.
- **GCS is the single source of truth** for case + run history; Batch API supplies live job state. No DB.

### Repo layout
```
phase3-run-app/
  core/        # pure engine: packaging/listing, GCS, signed policies, Batch config,
               #   submission, status, checkpoint config, case-ID allocator
  backend/     # FastAPI: IAP verify, REST endpoints, signed-policy minting, serves SPA → Cloud Run
  frontend/    # static SPA (batch-launcher.html visual language) → built into backend
  infra/       # Terraform/gcloud: APIs, SAs, IAM, IAP, bucket, Artifact Registry, WIF
  cli/         # thin terminal wrappers over core/ (replaces today's submit_*.sh)
openfoam-batch/
  Dockerfile   # runtime image openfoam:12.x.x  (migrate to Artifact Registry)
  runtime/     # run_case_in_batch.sh (fixed: checkpoint, no maxRunDuration, no preemption trap)
  tests/       # existing bash tests, ported/kept for the runtime script
docs/  data-notes/
# future: phase1-cad/, phase2-cfd/  (can import core/)
```

---

## 3. Core engine (`core/`) + the 8 script-flaw fixes

Single-responsibility modules:

| Module | Responsibility |
|---|---|
| `config.py` (`Settings`) | bucket, project, region, image URI, machine catalog, disk defaults — from env, no scattered literals |
| `naming.py` | pure: canonical case IDs, sanitize, **variant = machine type**, job-name building |
| `cases.py` (`CaseRepository`) | GCS case reads/writes: list, read manifest/markers, prefix-exists, **atomic case-ID allocation** |
| `uploads.py` (`SignedUrlService`) | mint **V4 signed POST policy per case prefix** via IAM `signBlob` (no key files) |
| `batch_jobs.py` (`BatchJobBuilder`, `Submitter`) | build single/multi-task Batch spec; submit via SDK |
| `status.py` (`RunStatusService`) | live state (Batch API) + history (GCS markers), merged |
| `machines.py` (`MachineCatalog`, `Recommender`) | c2d-highcpu catalog; suggestion from prior metrics (stub) |

GCS/Batch clients sit behind interfaces so `core` is unit-testable with fakes.

### The 8 fixes
1. **Remove `maxRunDuration` cap.** `BatchJobBuilder` omits `maxRunDuration` (optional param, default `None`). This is what killed case_0189 (Batch exit `50005` = task timeout, not Spot).
2. **Docker versioning.** Pin immutable `openfoam:12.x.x` (12 = OpenFOAM version, x.x = image revision). No `:latest`, no bare `:12`. Exact tag recorded in run metadata. Build/tag scheme documented in `infra/`.
3. **Variant = machine type.** `naming.variant_for_machine()` derives variant from machine type (e.g. `c2d-highcpu-56`). Variant prompt/param removed. Checkpoint/result paths keyed by `(case, machine)`.
4. **Disk:** default **1×375 GB local SSD**; advanced override = N local SSDs (striped) or sized `pd-ssd`. One typed disk-block builder.
5. **`case_0001` allocator bug.** Root causes in old `next_case_id`: empty/failed `ls` glob → loop runs once on `""` → `max=0` → `case_0001`; only counts cases with `READY`; 50 parallel uploads read the same `max`. New `CaseRepository.allocate_ids(n)`: scan **all** `cases/case_NNNN/` prefixes, then **claim each ID atomically** via GCS create-only precondition (`ifGenerationMatch=0`) on a reservation object → contiguous, collision-free block under concurrency.
6. **Task = parallelism.** `build_multi()` sets `taskCount = parallelism = len(cases)` (one VM per case, concurrent). Unit-tested.
7. **Remove `submit_all_ready`.** Engine exposes exactly `submit_single(case, machine, …)` and `submit_multi(cases, machine, …)`. `submit_all_ready_cases.sh` deleted.
8. **Spot/checkpoint.** `provisioning_model` param (default `STANDARD`, UI toggle for `SPOT`). In `run_case_in_batch.sh`: **fix checkpoint rsync** (sync case dir tree recursively — no `processor*` glob, which `gcloud storage rsync` rejects as "matched more than one URL"); **delete the SIGTERM-as-preemption trap / `preempted.json` / `exit 50001`**; keep periodic checkpoint→GCS + resume-from-latest so it works on Standard *and* Spot.

---

## 4. Data flow

### Canonical storage format: file tree (no input tarball)
```
gs://of-cases/cases/case_0042/
    case/            ← case tree as on disk (0/, constant/, system/, …)
    command.sh
    manifest.json
    READY            ← written last = commit; partial uploads never look ready
```
- **Web** uploads each file directly via the case's signed POST policy (no in-browser tarring).
- **CLI** uses `gcloud storage rsync ./case gs://…/case/` (no tar).
- **Runtime** `rsync`s the tree down (one code path; symmetric with checkpoint rsync).
- **Integrity:** GCS verifies CRC32C per object automatically; `SHA256SUMS` removed. `check_case_prefix` adapts to validate tree + `command.sh` + `manifest.json` + `READY` exist, and `command.sh` references `MPI_RANKS`.

**Data formats by type:** input case = untarred tree (small data); **results = tarred+gzipped on the VM, unchanged** (line 176/182 of `run_case_in_batch.sh` — the big data stays compressed); checkpoints = untarred (incremental rsync, transient, deleted on success). Input-storage increase is trivial (~$/month), mitigable with a GCS lifecycle rule.

### Flow 1 — Upload (drag-drop, parallel)
```
SPA walks dropped folder(s) → file list with relative paths
SPA → POST /api/cases:allocate {count:N}
   backend atomically allocates N case IDs + returns one signed POST policy per case prefix
SPA → browser uploads each file via its case's policy
   client-side bounded-concurrency pool (~10 default), resumable, per-file retry
SPA → POST /api/cases/{id}:finalize
   backend validates structure, writes manifest.json + READY (commit)
```
- **One signature per case** (not per file): a V4 signed POST policy with `starts-with key, "cases/case_NNNN/"` authorizes the whole prefix; size/content-type constrained.
- **Parallelism:** flatten all files of all cases into one work queue; pool runs ~10 concurrent uploads (sweet spot to saturate a typical uplink — GCS isn't the limit, the user's bandwidth is). Signing only exists for the browser; CLI uses SA creds directly.

### Flow 2 — Submit (run)
```
User picks case(s) + machine (c2d-highcpu-*) + advanced (disk, Spot toggle, MPI ranks)
SPA → POST /api/jobs {mode: single|multi, case_ids, machine_type, options}
backend: verify IAP user → core validates case(s) READY
   → BatchJobBuilder.build_single/build_multi
        variant=machine, NO maxRunDuration, disk, provisioning model, checkpoint env, pinned image tag
   → Submitter → batch.jobs.create → write submission marker to GCS
returns job id
```

### Flow 3 — Status / history (polling, no live log layer)
```
SPA polls GET /api/jobs and /api/jobs/{id}
RunStatusService merges:
   • live state (Batch API): QUEUED/RUNNING/SUCCEEDED/FAILED + statusEvents timeline + task counts
   • history + sim-progress (GCS markers): submissions/, results/_SUCCESS|_FAILED, runtime.json,
     checkpoint latest-timestep
GCS = history source of truth; Batch API = live state.
```

### Flow 4 — On the VM (runtime, fixed)
```
rsync case tree down → resume check (restore latest checkpoint, set controlDict startFrom latestTime)
   → periodic checkpoint loop (FIXED: rsync case dir tree → checkpoints/, no processor* glob)
   → run command.sh
   → on finish: tar results → results/ (unchanged), write _SUCCESS/_FAILED, clear checkpoint on success
   (no preemption trap, no maxRunDuration, no exit-50001 special-casing)
```

---

## 5. Security & IAM

Nothing stores credentials in the browser or app. Browser gets only short-lived signed POST policies; backend uses its attached SA.

### APIs to enable (project `project-688a4c78…`)
`run`, `iap`, `iamcredentials`, `storage`, `batch`, `compute`, `artifactregistry`, `cloudbuild`, `cloudresourcemanager`, `logging` (`.googleapis.com`). `iamcredentials` is required for `signBlob`.

### Two dedicated service accounts (namespaced `of-…`, never the default compute SA)
**`of-batch-backend@` (attached to Cloud Run)**
- `roles/iam.serviceAccountTokenCreator` **on itself** — sign POST policies via `signBlob`, no key file
- `roles/storage.objectAdmin` **on `of-cases` bucket only**
- `roles/batch.jobsEditor` (project)
- `roles/iam.serviceAccountUser` **on `of-batch-job@`**

**`of-batch-job@` (Batch VM identity)**
- `roles/storage.objectAdmin` on `of-cases` bucket only
- `roles/batch.agentReporter` (project)
- `roles/logging.logWriter` (project)

### IAP
1. OAuth consent screen → **Internal**.
2. Enable IAP on the Cloud Run service.
3. IAP service agent (`service-PROJECTNUM@gcp-sa-iap.iam.gserviceaccount.com`) → `roles/run.invoker`.
4. Org users via a **Google Group** → `roles/iap.httpsResourceAccessor`.
5. Deploy with `--no-allow-unauthenticated`.
6. Backend verifies `x-goog-iap-jwt-assertion` JWT on every `/api/*` (ES256, `iss=https://cloud.google.com/iap`, `aud`=service id; cache IAP public keys) and reads user email/sub for audit.

### Permissions reality
- **kartikey** (Editor + Cloud Run Admin + Secret Manager Admin) can: enable APIs, create SAs, create bucket, build/deploy Cloud Run.
- **Needs Owner (pushkar)** — Editor cannot: **set IAM role bindings**, **configure IAP**, **set up WIF** (create pool + SA IAM policy). Cleanest: pushkar grants kartikey `roles/resourcemanager.projectIamAdmin` + `roles/iap.admin` once, then kartikey scripts everything in `infra/`.
- **Image registry:** migrate runtime image off personal Docker Hub (`docker.io/kartikeyattri/openfoam`) → **Artifact Registry** in-project (private, IAM-gated).

---

## 6. UI

Reuse `batch-launcher.html` visual language: light frosted-glass (`#f0f0f0` bg + noise/grid), glass panels (`backdrop-blur`, soft shadows, 22px radii), **Manrope** + **JetBrains Mono**, dark terminal footer, pill tabs, segmented controls, two-column "form left / preview right".

**Shift from prototype:** the prototype *generates commands to copy*; the new app **executes**. The dark terminal footer is repurposed to a **light status line + "Copy equivalent CLI" button** (keeps CLI parity transparent), not a streaming console.

### Tabs: `Upload · Cases · Run · Runs`
- **Upload** — drag-drop bulk/single; real per-case + overall progress bars (parallel pool); atomic AUTO IDs.
- **Cases** (new) — browse all GCS cases (id, status, files, size, date); multi-select → Run.
- **Run** — modes **Single / Multi-task only** (All-Ready removed); machine picker (all c2d-highcpu sizes `-2…-112`); **suggested machine** panel (prior metrics, graceful degrade); advanced = disk override, **Spot toggle (off by default)**, MPI ranks. **No variant field, no max-duration.** [Run job] calls API.
- **Runs** (new) — list jobs with live state; **Details** button → drawer.

### Feedback model (simple, no live log layer)
Shown (all cheap sources): job state; status-event **timeline** (Batch API); **multi-task progress** (task counts); **sim-time %** derived from GCS checkpoint latest-timestep ÷ `controlDict` endTime (no log parsing); **checkpoint freshness** (GCS listing); **failure summary** (exit code from GCS marker + Batch status reason). Backend activity = lightweight status line/toasts. **On-click inspection = deep links to Cloud Console / Cloud Logging** — we do not reimplement GCP's log UI. Delivery = **polling** (3–5s; robust under Cloud Run + IAP), not SSE/WebSocket.

Removed vs prototype: All-Ready mode, Variant ID, Max Duration/43200s, c3d preset, SHA256SUMS checks, command-copy-as-primary-action.

---

## 7. Testing

| Layer | Approach | Coverage |
|---|---|---|
| `core/` | **Unit, TDD**, GCS/Batch behind fakes | allocator (case_0001 + 50-parallel concurrency), Batch builder (no maxRunDuration, variant=machine, disk, taskCount==parallelism, Spot toggle), validation — a test per fix |
| `backend/` | Integration (`TestClient`) | IAP JWT verify (valid + forged), endpoint contracts, signed-policy minting (mock signBlob) |
| Runtime `run_case_in_batch.sh` | **Keep & port existing bash tests** (gcloud/foamDictionary stubs) | tree rsync, fixed checkpoint rsync (no glob), removed preemption trap, resume |
| `frontend/` | Light (few component tests) + manual | — |

TDD applies first to the allocator and the checkpoint rsync (the bugs that bit).

---

## 8. CI/CD — GitHub Actions + Workload Identity Federation

- **On PR:** GitHub Actions runs core unit tests + backend tests + `tests/run_all.sh`.
- **On merge to `main`:** build two images (backend app + `openfoam:12.x.x` runtime) → **Artifact Registry**; deploy backend to Cloud Run. **Test step gates deploy.**
- **Keyless auth via WIF** (no SA JSON keys):
  1. Create Workload Identity **Pool**.
  2. Add **Provider** for GitHub OIDC (`token.actions.githubusercontent.com`); attribute mapping `assertion.repository → attribute.repository`; **attribute condition restricting to the specific repo**.
  3. Create a **deploy SA** with deploy roles (Cloud Run admin, Artifact Registry writer, Service Account User on runtime SAs).
  4. Bind `roles/iam.workloadIdentityUser` on the deploy SA to `principalSet://…/attribute.repository/OWNER/REPO`.
  5. Workflow uses `google-github-actions/auth` with provider + SA.
- WIF setup needs Owner/IAM-admin (pushkar or the `projectIamAdmin` grant). Difficulty: medium, front-loaded one-time (~1–2 hr; the `principalSet` string + attribute condition are the finicky parts).
- **Fallback:** Cloud Build (in-project, no WIF) if WIF blocks on the day.

---

## 9. Build order (incremental; each milestone shippable)

```
M1  core/ + runtime fixes + CLI wrappers     ← TDD; fixes all 8 flaws; no CI needed
       ⇒ CLI workflow works, FIXED, before any web app
M2  infra/  (APIs, 2 SAs, IAP, bucket, Artifact Registry, WIF)   ← needs pushkar/Owner; parallel with M1
M3  backend/  (FastAPI over core, IAP verify, signed policies, endpoints)  ⇒ Cloud Run behind IAP
M4  frontend/  (4-tab SPA, parallel upload pool, Runs feedback)  ⇒ served by FastAPI
M5  polish  (suggested-machine w/ graceful degrade, detail drawer, deep links)
```
After **M1** the fixed CLI already delivers value; the web app layers on the same engine; the CLI keeps working throughout.

### Delegated to user (not built here)
- The cells/size/volume **metadata file** (`metrics.json`) for machine suggestion — generated later by **Agent O** (Phase 2 CFD automation). Until then, the Recommender shows prior-run metrics and degrades gracefully.
- Obtaining Owner-level actions (IAM bindings, IAP, WIF) from pushkar, or the `projectIamAdmin` + `iap.admin` grant.

---

## 10. Open items / assumptions
- Same project as BioHermes — all resources namespaced `of-…`; must not weaken BioHermes IAM.
- Machine catalog: all `c2d-highcpu` sizes (`-2, -4, -8, -16, -32, -56, -112`).
- Region default `us-central1` (confirm Batch + c2d-highcpu availability per zone).
- Bucket: `of-cases` (existing).
