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
