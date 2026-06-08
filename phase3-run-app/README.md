# Phase 3 — OpenFOAM Batch Run App

Upload OpenFOAM cases to GCS and run them on Google Cloud Batch — via a web UI **or** the `of` CLI. One Cloud Run service serves the SPA and the API; the same `core/` engine backs both.

> Part of a 3-phase pipeline (P1 CAD/Salome MCP, P2 CFD/OpenFOAM MCP — future).

---

## Quick Start

1. Open the app → sign in with your `@lemnisca.bio` Google account
2. **Upload tab** — drop your case folder → Upload
3. **Cases tab** → select cases → **Run tab** → pick machine → Run job
4. **Runs tab** — live status, polled every 4 s

That's the whole flow. Details below.

---

## Repo Layout

```
phase3-run-app/
  core/        pure engine: naming, GCS storage, case allocator, validation,
               disk + Batch spec builders, signed URLs, run status, machines
  backend/     FastAPI: serves the SPA at / and the API at /api/*
  frontend/    Vite + React + TS SPA (sign-in → upload → cases → run → runs)
  cli/         `of` CLI — same operations as the web app, from the terminal
  infra/       one-time setup + deploy scripts, bucket CORS/lifecycle config
  runtime/     OpenFOAM Batch VM image (Dockerfile + run_case_in_batch.sh + tests)
```

---

## GCP facts

| Thing | Value |
|---|---|
| Project | `cfd-lemnisca` (#`380489820300`) |
| Region | `us-central1` |
| Cloud Run service | `of-batch-app` — `https://of-batch-app-380489820300.us-central1.run.app` |
| Bucket | `cfd-lemnisca-cases` |
| Artifact Registry | `us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/` |
| Service accounts | `of-batch-backend@` (Cloud Run), `of-batch-job@` (Batch VM), `of-ci-deployer@` (GitHub Actions) |

---

## Case folder format

The uploader accepts two shapes:

**Single case** — drop a folder that contains `command.sh` directly:
```
mycase/
  system/
  constant/
  0/
  command.sh      ← must be here
```

**Bulk** — drop a parent folder whose immediate subfolders are cases:
```
foam_runs/
  case_a/
    system/ constant/ 0/ command.sh
  case_b/
    system/ constant/ 0/ command.sh
```

`command.sh` must live **inside** the case folder. The runtime rsyncs the whole tree and runs it. It should contain only solver logic — no GCS download/upload, no `mpirun` argument construction (the runtime injects `MPI_RANKS`).

---

## Using the app

### Upload tab
Drop a case folder (single or bulk). Detected cases appear as a list. Press **Upload case(s)** — files go directly to GCS via signed PUT URLs; nothing passes through the backend server. Progress bar shows during upload.

### Cases tab
Lists all cases in the bucket with READY / incomplete status. Check one or more cases → **Run selected →** to configure a job.

### Run tab
Only reachable after selecting cases. Pick:
- **Machine** — c2d-highcpu presets (2 to 112 vCPU). c2d-highcpu-16 is the proven sweet spot for most cases.
- **Provisioning** — Standard (reliable) or **Spot** (cheaper, resumable via checkpointing).

Press **Run job** → job appears in Runs within seconds.

### Runs tab
Live polling every 4 s. Job name, colored state badge (RUNNING pulses), Console ↗ link to the GCP Batch console. Skeletons show on first load instead of flashing empty.

---

## CLI — full alternative to the web app

The `of` CLI covers every operation the web app does. Useful for scripting, automation, or when you're already in the terminal.

```bash
cd phase3-run-app
pip install -e ".[dev]"
```

| Command | What it does | Web app equivalent |
|---|---|---|
| `of upload --case-dir ./mycase --command-sh ./mycase/command.sh` | Upload one case to GCS | Upload tab |
| `of list` | List all cases + READY status | Cases tab |
| `of validate case_0042` | Check a case is complete before running | Cases tab status |
| `of run --case 0042 --machine c2d-highcpu-56` | Submit a single-case Batch job | Run tab |
| `of run --case 0042 --case 0043 --machine c2d-highcpu-16` | Submit a multi-task job (one VM per case) | Run tab (multi-select) |
| `of run --case 0042 --machine c2d-highcpu-16 --spot` | Same but on Spot VMs | Provisioning toggle |

The CLI uses ADC (`gcloud auth application-default login`) — no OAuth browser flow. Good for headless environments.

---

## Spot VMs + checkpointing

Checkpointing is always on. Every 30 s the runtime rsyncs solver state (`processor*/`) to `gs://cfd-lemnisca-cases/checkpoints/<case_id>/<variant>/latest/`. If the VM is preempted or stopped:

- Batch retries automatically (up to 3 times)
- The next attempt finds the checkpoint, restores it, sets `startFrom latestTime`, resumes
- On clean success the checkpoint is deleted; lifecycle rule cleans up any orphans after 30 days

No `maxRunDuration` — jobs run until done.

> **Checkpointing only works for parallel (decomposed) runs.** It keys entirely off `processor*/` folders: the poll loop watches `processor0` to decide when to checkpoint, and only `processor*/` (plus `system/`) is uploaded. A **serial** case (run without `decomposePar`, so results live in `case/<time>/` instead of `processor*/<time>/`) is silently **not** checkpointed — the loop never fires, and an interrupted serial run resumes from time 0. All our cases run parallel via MPI, so this gap is latent, not active — but anything submitted as a single-process run would have no checkpoint protection.

### ⚠️ Spot in practice — a real interruption, and what broke (forensic, 2026-06-08)

We ran `two-phase-test` (case `case_0012`, variant `c2d-highcpu-56`) on **Spot**. It got interrupted, and the post-mortem surfaced **three separate things** — only one of which was external. If you're relying on Spot, read this.

**Timeline (from Batch logs + the checkpoint objects in GCS):**

| Time (UTC) | Event |
|---|---|
| 6-06 ~10:16 | Job submitted (`case_0012`, `c2d-highcpu-56`, Spot). |
| 6-06 10:16→13:59 | **~3.5 h bouncing QUEUED↔SCHEDULED** — c2d Spot capacity was already scarce *at submit*. |
| 6-06 13:59:13 | Got a Spot VM → RUNNING. Runtime logged `Resuming from …/latest`, rsync'd a pre-existing checkpoint down. |
| 6-06 13:59:46 | Resume-prep step logged `controlDict does not exist` (**non-fatal**, swallowed by `\|\| true`). `command.sh` then ran the full pipeline **from scratch**: `blockMesh → snappyHexMesh -overwrite → topoSet → createPatch → decomposePar -force → foamRun -parallel`, re-meshing ("Create mesh for time = 0", "Deleting polyMesh directory"). |
| 6-06 14:05:45 | Solver started its time loop **from time 0** (adaptive deltaT ≈ 1.5 ms). |
| 6-06 14:05 → 6-07 08:22 | ~18 h of wall-clock to reach **sim-time 3**. Checkpointed incrementally. |
| ~6-07 18:39 | **Spot VM preempted.** The SIGTERM stop-handler trap fired and flushed a final checkpoint (constant/polyMesh + system re-uploaded at 18:39:54). |
| 6-07 18:39 → … | Task = **PENDING**. The managed instance group could not get a replacement Spot `c2d-highcpu-56` anywhere in us-central1 → **67× `GCE_ZONE_RESOURCE_POOL_EXHAUSTED`**. Job stays **RUNNING** (not failed), waiting for capacity. |

**Three findings, ranked by what actually hurts:**

1. **The resume is defeated by a meshing `command.sh` (the real bug).** Checkpointing/preemption-flush/Batch-retry all worked, and the checkpoint (28.8 MiB, fully decomposed, sim-time 3) is intact. But our resume only sets `startFrom latestTime` — it does **not** stop `command.sh` from re-running `blockMesh`/`snappyHexMesh -overwrite`/**`decomposePar -force`**, which **wipe the restored `processor*/<time>` and restart the solver from 0.** A `command.sh` that re-meshes/re-decomposes on every invocation throws away all checkpointed progress. *Resume only saves compute if `command.sh` skips preprocessing when state already exists.*

2. **The `startFrom latestTime` edit silently fails anyway (runtime bug).** The `controlDict does not exist` error was *not* a missing file — `system/controlDict` is in the upload. `foamDictionary` ran from the container's default CWD (`/root`) and mis-resolved the case path (note the `//root//mnt/...` in the error), so the `startFrom` edit never applied. It was swallowed by `\|\| true`, so it never surfaced. Fix: `cd "${CASE_DIR}"` (or pass `-case`) before `foamDictionary`, and stop swallowing the failure.

3. **Spot recovery is hostage to zonal capacity (external, can't fix in code).** A preempted Spot job can only resume *if a replacement VM is available*. `c2d-highcpu` is a constrained family and Spot is the leftover on top of it — us-central1 had a multi-day stockout, so the job sat PENDING for >18 h. The job won't fail (good), but it won't progress either. For anything time-sensitive, use **Standard** provisioning, or expect indefinite PENDING during stockouts. (Cancelling is safe — the checkpoint is keyed by `<case_id>/<variant>` and only deleted on SUCCESS, so it survives.)

**Resubmitting after a cancel:** the checkpoint path is `checkpoints/<case_id>/<variant>/latest` — keyed by **case + machine variant, not by job name/codename**. Cancel + resubmit the *same case on the same variant* and the new job *will* find and restore the checkpoint. ⚠️ Resubmit on a **different machine type** (→ different variant) and it starts from time 0. (Today, per finding #1, the restore is then clobbered by re-meshing regardless — fix #1 + #2 first.)

### How that forensic was done — every log and resource, in order

Reproducible trail for the next person debugging a stuck/interrupted Spot job. Replace the job/case identifiers with your own. (Job UID for the run above: `two-phase-test-30f80879-c013-43aa-86b0`.)

**Code read (this repo):**
- `phase3-run-app/runtime/run_case_in_batch.sh` — checkpoint prefix (`:27`), resume block + the `foamDictionary` bug (`:38–42`), `sync_checkpoint`/poll loop, SIGTERM stop-handler flush, success-deletes-checkpoint (`:147`).
- `phase3-run-app/core/batch_jobs.py` — allocation policy, `provisioningModel`, `maxRetryCount`, no `allowedLocations` in code (`:98–137`).

**GCP — Batch** (`gcloud batch`, project `cfd-lemnisca`, `us-central1`):
- `jobs describe two-phase-test` → state RUNNING; `statusEvents` (the ~3.5 h QUEUED↔SCHEDULED bouncing → RUNNING at 13:59); `allocationPolicy` (`allowedLocations` = us-central1-a/b/c/f; local-SSD disks); env (`BUCKET`, `PROJECT`, `CASE_ID=case_0012`, `VARIANT_ID=c2d-highcpu-56`, `JOB_NAME`); `maxRetryCount=3`.
- `tasks list … two-phase-test` → task state **PENDING**.

**GCP — Cloud Logging** (`gcloud logging read`, `resource.type=batch.googleapis.com/Job`, `labels.job_uid=two-phase-test-30f80879-c013-43aa-86b0`):
- The resume line, the `controlDict` FATAL IO + context, the full preprocessing chain (`blockMesh → snappyHexMesh → topoSet → createPatch → decomposePar -force → foamRun -parallel`), `Starting time loop`, deltaT progression — establishing the from-time-0 restart.

**GCP — GCS** (`gcloud storage ls` / `ls -l` / `cat`):
- `checkpoints/case_0012/c2d-highcpu-56/latest/` recursive → 144 objects / 28.8 MiB, `processor0–27` + `0/` + `constant/` + `system/`, time dirs `0…3`.
- `ls -l` on the checkpoint → object timestamps: `0/` @ 6-06 10:14:59, `processor0/3/` @ 6-07 08:22:53, `processor0/constant/polyMesh` @ 6-07 18:39:54 (the preemption flush).
- `cases/case_0012/case/system/` → confirmed `controlDict` **is** in the upload.
- `cat cases/case_0012/case/command.sh` → the `setup_twophase.py`-generated unconditional mesh+decompose+solve pipeline.

---

## Local development

```bash
# Python (backend + core tests)
cd phase3-run-app
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" -r requirements-backend.txt
OF_DEV_NO_IAP=1 pytest -q

# Runtime bash tests
bash phase3-run-app/runtime/tests/run_all.sh

# Frontend
cd phase3-run-app/frontend
npm install
# create .env.local with: VITE_OAUTH_CLIENT_ID=380489820300-4ja0tnm6p2em05qgpg5krtac6e0f155c.apps.googleusercontent.com
npm run dev    # http://localhost:8080
```

⚠️ **The Vite dev server proxies `/api/*` to the deployed Cloud Run backend.** Uploads and job submissions from local dev hit the **real** bucket and real Batch. Don't use it for bulk testing. Use the CLI with `--dry-run` or a scratch case instead.

Also ensure `http://localhost:8080` is in the OAuth client's **Authorized JavaScript origins** (Google Cloud Console → APIs & Services → Credentials).

---

## Deploy

### CI — preferred (GitHub Actions + Workload Identity Federation)

Every push to `main`:
1. Runs the test gate (pytest + runtime bash tests + vitest)
2. Builds the multi-stage backend image (SPA bundled, tagged with the commit SHA)
3. Deploys to Cloud Run

**One-time prerequisite:** add a repo **Variable** (not secret) in GitHub:
> Settings → Secrets and variables → Actions → **Variables** tab
> `OAUTH_CLIENT_ID` = `380489820300-4ja0tnm6p2em05qgpg5krtac6e0f155c.apps.googleusercontent.com`

Without this the CI build succeeds but the deployed SPA has an empty client ID and sign-in silently fails.

WIF is locked to repo `Lemniscabio/GCP_openFoam_setup`, SA `of-ci-deployer@cfd-lemnisca.iam.gserviceaccount.com`.

### Manual — fallback

```bash
# Set CLIENT_ID to the web OAuth client ID
docker buildx build --platform linux/amd64 \
  --build-arg VITE_OAUTH_CLIENT_ID=CLIENT_ID \
  -f phase3-run-app/backend/Dockerfile \
  -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:manual \
  --push phase3-run-app

gcloud run deploy of-batch-app \
  --image us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:manual \
  --region us-central1 \
  --service-account of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --update-env-vars OF_OAUTH_CLIENT_ID=CLIENT_ID,OF_ALLOWED_DOMAIN=lemnisca.bio,OF_IMAGE_URI=us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.1 \
  --project cfd-lemnisca
```

---

## Runtime image (OpenFOAM on Batch VMs)

The runtime image is **not built by CI** — it changes rarely (only when `runtime/run_case_in_batch.sh` or the Dockerfile changes) and is large. It uses manual semver tags: `openfoam:12.X.Y` (12 = OpenFOAM version, X.Y = image revision).

**When to rebuild:** only when `runtime/run_case_in_batch.sh` changes or you update OpenFOAM.

**When NOT to rebuild:** deploying frontend/backend changes — CI handles those with SHA-tagged `of-backend` images.

```bash
# Always linux/amd64 — Mac defaults to arm64, Batch rejects it
docker buildx build --platform linux/amd64 \
  -f phase3-run-app/runtime/Dockerfile \
  -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.2 \
  --push phase3-run-app/runtime

# Then update RUNTIME_IMAGE in .github/workflows/deploy.yml
```

After bumping the tag, update `RUNTIME_IMAGE` in `.github/workflows/deploy.yml` and redeploy — the Cloud Run service picks it up via `OF_IMAGE_URI`.

---

## Auth and access

- Cloud Run is **public ingress** (IAP is broken — project is under the wrong org; see TODO below)
- Every `/api/*` call needs `Authorization: Bearer <Google ID token>`
- The backend verifies the token and requires **`hd == lemnisca.bio`** — non-org Google accounts get a 403 immediately
- The frontend enforces the same check and shows a "Not authorized" screen for non-org emails
- Sessions persist in `localStorage` with a hard **60-minute cap** — you'll be prompted to sign in again after 60 min

### ⚠️ TODO: move project to the lemnisca.bio org

`cfd-lemnisca` lives under org `493439251516`, not the lemnisca.bio org `356771806958`. This breaks **Internal** OAuth consent and **IAP**. When resolved:

```bash
gcloud beta projects move cfd-lemnisca --organization=356771806958
# then: switch OAuth consent → Internal, retry IAP
```

Until then, External consent + the hd-only gate is the enforced security boundary.

---

## Environment variables

| Var | Where | Purpose |
|---|---|---|
| `VITE_OAUTH_CLIENT_ID` | **build-time** (CI `--build-arg`; `frontend/.env.local` for dev) | Inlined into the SPA so the browser can start Google sign-in |
| `OF_OAUTH_CLIENT_ID` | backend **runtime** env | Audience the backend verifies ID tokens against (same value) |
| `OF_ALLOWED_DOMAIN` | backend runtime env | Org domain enforced (`lemnisca.bio`) |
| `OF_IMAGE_URI` | backend runtime env | OpenFOAM runtime image Batch jobs use |
| `OF_DEV_NO_IAP=1` | local/dev only | Bypass auth for local testing — **never set in prod** |

---

## What NOT to do

- **Don't use `npm run dev` for any real upload testing** — the proxy hits the live backend and bucket. Use a scratch case or the CLI.
- **Don't resubmit a job that's still RUNNING** — two jobs writing to the same checkpoint prefix will corrupt each other. Check Runs tab first.
- **Don't omit the `OAUTH_CLIENT_ID` repo variable before merging to main** — CI will succeed but the deployed app won't let anyone sign in.
- **Don't build the runtime image without `--platform linux/amd64`** — Batch VMs are x86_64; arm64 images (Mac default) fail at pull time with "no matching manifest".
- **Don't set `OF_DEV_NO_IAP=1` in the Cloud Run deploy** — it disables all authentication.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Sign-in button does nothing / "not authorized" screen | Non-`@lemnisca.bio` account, or `OAUTH_CLIENT_ID` missing in CI | Check the account; check the GitHub variable |
| Upload fails with 403 | Bucket CORS not set | `gcloud storage buckets update gs://cfd-lemnisca-cases --cors-file=infra/of-cases-cors.json` |
| Case shows "incomplete" forever | Upload was interrupted before finalize | Re-upload the case (get a new case_id) |
| Job never appears in Runs after clicking Run job | Batch API error or SA permissions | Check Cloud Run logs; verify `of-batch-backend@` has `roles/batch.jobsEditor` |
| Job FAILED immediately | Wrong runtime image arch, or missing `command.sh` in case tree | Check Batch logs in Console; confirm image is `linux/amd64`; validate with `of validate <id>` |
| Local dev: "Unexpected token '<'" / 404 on /api | Vite proxy not running or misconfigured | Confirm `npm run dev` is running on `:8080`; check `vite.config.ts` proxy target |
| Local dev: "google is not defined" | GIS script loaded async, race condition | Fixed in current code (retry loop in `auth.ts`) — hard-refresh to clear cache |
