# Phase 3 — OpenFOAM Batch Run App

Web app + CLI to **upload OpenFOAM cases to GCS and run them on Cloud Batch**, on a
dedicated GCP project (`cfd-lemnisca`). One Cloud Run service serves the SPA *and* the
API; the same pure-Python `core/` engine backs both the web app and the CLI.

> Phase 3 of a 3-phase pipeline (P1 CAD/Salome MCP, P2 CFD/OpenFOAM MCP — future).
> Design spec: `../docs/superpowers/specs/2026-06-01-phase3-run-app-design.md`.
> Milestone plans: `../docs/superpowers/plans/2026-06-0*-phase3-*.md`.

## Layout
```
core/        pure engine (no HTTP): naming, GCS storage, atomic case-id allocator,
             validation, disk + Batch spec builders, signed URLs, run status, machines
backend/     FastAPI: serves the built SPA at / and the API at /api/*; Google-ID-token auth
frontend/    Vite + React + TS SPA (sign-in → upload → cases → run → runs)
cli/         `of` CLI (upload / validate / list / run) over the same core
infra/       setup + deploy scripts, bucket CORS/lifecycle, (see below)
../openfoam-batch/  the runtime image (Dockerfile + runtime/run_case_in_batch.sh) Batch runs
```

## GCP facts (project `cfd-lemnisca`, # `380489820300`, region `us-central1`)
- **Cloud Run service:** `of-batch-app` — URLs `https://of-batch-app-e3slrac76q-uc.a.run.app` and `…-380489820300.us-central1.run.app`
- **Bucket:** `cfd-lemnisca-cases` (`cases/`, `results/`, `checkpoints/`, `submissions/`)
- **Service accounts:** `of-batch-backend@` (Cloud Run; least-priv, signs upload URLs, submits Batch), `of-batch-job@` (Batch VM identity), `of-ci-deployer@` (GitHub Actions)
- **Artifact Registry:** `us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/` → `of-backend` (web) + `openfoam` (CFD runtime)

## Auth model
- **No IAP** (the one-click Cloud Run IAP is broken on this project — undocumented error 604, root cause = project is under the wrong org; see TODO below).
- Cloud Run is **public ingress**, and the **app enforces auth**: every `/api/*` request needs `Authorization: Bearer <Google ID token>`. `backend/auth.py` verifies it (official `google.oauth2.id_token`) and requires the Workspace **`hd` claim == `lemnisca.bio`** (hd-only — rejects non-org accounts with 403). `/` + `/health` are public.
- Frontend uses **Google Identity Services**; the `OAUTH_CLIENT_ID` is a Web OAuth client (consent screen currently **External**). Session token is kept in `localStorage` with a **hard 60-min cap** (refresh keeps you in; relogin after 60 min).

### ⚠️ TODO: move the project to the `lemnisca.bio` org
`cfd-lemnisca` lives under org `493439251516`, not the lemnisca.bio org `356771806958`.
That mismatch breaks **Internal** OAuth consent + **IAP**. When billing/cross-org friction
is resolved: `gcloud beta projects move cfd-lemnisca --organization=356771806958` (needs Org
Admin on both orgs), then switch consent → **Internal** (edge-blocks non-org users) and retry
IAP. Until then, External + the hd-only app gate is the secure stand-in. (Full detail: spec §11.)

## Environment variables
| Var | Where | Purpose |
|---|---|---|
| `VITE_OAUTH_CLIENT_ID` | **build-time** (Docker `--build-arg`; `frontend/.env.local` for dev) | inlined into the SPA bundle so the browser can start Google sign-in |
| `OF_OAUTH_CLIENT_ID` | backend **runtime** env | audience the backend verifies ID tokens against (same value as above) |
| `OF_ALLOWED_DOMAIN` | backend runtime env | org domain allowed (`lemnisca.bio`) |
| `OF_IMAGE_URI` | backend runtime env | the OpenFOAM **runtime** image Batch jobs use (e.g. `…/openfoam:12.0.1`) |
| `OF_DEV_NO_IAP=1` | local/dev only | bypass auth for local testing (never set in prod) |

## Image versioning (two images, two strategies — on purpose)
- **Backend image (`of-backend`)** — **auto-versioned by CI** with the git commit SHA:
  `of-backend:<github.sha>` (+ `:latest`). Every push to `main` builds a unique, immutable,
  rollback-able image and deploys it. It changes every commit (frontend + API), so SHA tagging fits.
- **OpenFOAM runtime image (`openfoam`)** — **NOT built by CI.** It's the heavy CFD image that
  changes rarely (only when `openfoam-batch/runtime/run_case_in_batch.sh` or its `Dockerfile`
  change), so it uses **manual semantic tags** (`openfoam:12.0.1` — `12` = OpenFOAM version,
  `.0.1` = image revision). The deploy just *references* it via `OF_IMAGE_URI` (the workflow's
  `RUNTIME_IMAGE`). **To change the runtime:** bump the tag, build+push it manually (below),
  and update `RUNTIME_IMAGE` in `.github/workflows/deploy.yml`.

  Rebuild the runtime image (amd64!):
  ```bash
  docker buildx build --platform linux/amd64 -f ../openfoam-batch/Dockerfile \
    -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.2 --push ../openfoam-batch
  ```
  > Always build `linux/amd64` — the Mac defaults to arm64 and Batch rejects it.

## Deploy
### CI (GitHub Actions + Workload Identity Federation) — preferred
`.github/workflows/deploy.yml`: on **PR** runs the test gate (pytest + bash + vitest); on
**push to `main`** authenticates to GCP keyless via **WIF** (pool `of-github-pool`, provider
`github-provider`, SA `of-ci-deployer@`), builds the multi-stage backend image (SPA bundled,
SHA-tagged), and deploys. **One-time setup:** add a repo **variable** `OAUTH_CLIENT_ID`
(Settings → Secrets and variables → Actions → Variables). The repo must be
`Lemniscabio/GCP_openFoam_setup` (the WIF provider is locked to it).

### Manual (fallback)
```bash
# backend (SPA bundled). CLIENT_ID = the web OAuth client id
docker buildx build --platform linux/amd64 --build-arg VITE_OAUTH_CLIENT_ID=CLIENT_ID \
  -f backend/Dockerfile -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:0.x.y --push .
gcloud run deploy of-batch-app --image us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:0.x.y \
  --region us-central1 --service-account of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --update-env-vars OF_OAUTH_CLIENT_ID=CLIENT_ID,OF_ALLOWED_DOMAIN=lemnisca.bio,OF_IMAGE_URI=us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.1 \
  --project cfd-lemnisca
```
Bucket needs CORS for browser uploads: `gcloud storage buckets update gs://cfd-lemnisca-cases --cors-file=infra/of-cases-cors.json`.

## Local development
```bash
# backend tests
cd phase3-run-app && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" -r requirements-backend.txt
OF_DEV_NO_IAP=1 pytest -q
# runtime bash tests
bash ../openfoam-batch/tests/run_all.sh
# frontend (UI work)
cd frontend && npm install && npm run dev -- --port 8080   # http://localhost:8080
```
For the frontend dev server: create `frontend/.env.local` with `VITE_OAUTH_CLIENT_ID=…`, and
ensure the OAuth client's **Authorized JavaScript origins** include `http://localhost:8080`.
`/api/*` calls go same-origin (no local backend) — for full local API, add a Vite proxy to the
deployed Cloud Run URL or run the backend with `OF_DEV_NO_IAP=1`.

## CLI
```bash
of upload --case-dir ./mycase --command-sh ./mycase/command.sh   # uploads case tree (command.sh inside case/)
of validate case_0042
of list
of run --case 0042 --machine c2d-highcpu-56 [--spot]
```
`command.sh` lives **inside** the case tree (`cases/<id>/case/command.sh`); the runtime
rsyncs the tree down and runs it. No `maxRunDuration` (jobs run until done/stopped);
checkpointing is always-on; Spot is opt-in.
