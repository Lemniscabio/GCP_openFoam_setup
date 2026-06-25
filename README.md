# Stirred-Tank-Reactor CFD pipeline

End-to-end automation for stirred-tank-reactor CFD: a JSON reactor spec becomes parametric 3D
geometry, then a complete OpenFOAM case (single-phase or two-phase Euler–Euler), which runs on
Google Cloud Batch with results/checkpoints in Cloud Storage.

## Creating geometry: chat or form

In the web app's **Generate** tab you create a reactor geometry either by **chatting** with an
assistant (describe the reactor in plain language; it asks for anything missing, then builds it)
or by switching to **"Do it manually"** for the structured form. Both produce the same validated
`STRParams` spec and feed the identical preview → inspect/edit case files → create / variations
flow. The assistant only fills the geometry spec — it never computes physics or geometry; the
deterministic generator does that, and the spec is validated against the real schema before
anything is built (so it can't hand off an invalid spec).

**Known limitation (intentional):** the assistant asks for the full geometry — it does **not**
infer dimensions from a target volume (e.g. "make a 100 kL reactor"). A volume underdetermines the
geometry (any diameter/height/impeller layout can hit the same volume), so it asks for the actual
dimensions rather than guessing. (It *can* report the volume of a spec it already has.) Inferring a
full geometry from a volume via standard stirred-tank design heuristics is a possible future
enhancement, deliberately not enabled.

## 📐 Architecture

**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — the deep, whole-pipeline technical reference,
in three parts: **CAD/geometry** (CadQuery), **OpenFOAM case generation** (single- + two-phase,
sparging, variations, verification), and **GCP execution** (Cloud Batch, runtime, state, auth,
infra). Start here to understand how anything works.

## What's here

```
part-a-cad/        ← CAD + OpenFOAM case generator (JSON spec → geometry → case → variations → verify)
references/        ← reference cases (singlephase, twophase) + recipe to add a new case type
phase3-run-app/    ← GCP run system — web app + CLI + Cloud Batch runtime
benchmarks/        ← historical machine comparison runs (bench_1.html, bench_2.html, etc)
docs/              ← architecture, specs, and plans
.github/workflows/ ← CI/CD (test gate + deploy to Cloud Run on push to main)
```

## Reference cases (`references/`)

`references/singlephase/` and `references/twophase/` are the **ground-truth references this
version of the generator was built from and validated against**. The parametric generator
in `part-a-cad` was authored by reading these cases (their dictionaries, fields, MRF setup,
and — for two-phase — the Euler–Euler `phaseProperties`, `setFields`, and the
`topoSet`+`createPatch` sparger method), and its output is checked against them by the
golden tests in `part-a-cad/tests/golden/`.

**[`references/README.md`](references/README.md)** also documents the step-by-step recipe to
**add a new case type** (new reactor family or physics mode) — geometry registry, OF-case
writers, variation params, golden tests.

## Active system: Phase 3

**[phase3-run-app/README.md](phase3-run-app/README.md)** — everything you need:
quick start, case format, CLI reference, deploy, auth, troubleshooting.

The short version:
- Web app at `https://of-batch-app-380489820300.us-central1.run.app` — sign in with your `@lemnisca.bio` Google Workspace account (auth is Google OAuth ID-token with **hosted-domain (`hd`) enforcement**, not IAP), drag-drop upload, click to run
- `of` CLI for the same operations from the terminal
- GCP project: `cfd-lemnisca`, bucket: `cfd-lemnisca-cases`, region: `us-central1`
- CI deploys on push to `main` via Workload Identity Federation

## CI/CD — `.github/workflows/deploy.yml`

Two jobs, triggered on every push/PR:

| Job | Trigger | What it does |
|---|---|---|
| `test` | every PR + push to `main` | pytest (core + backend) + runtime bash tests + vitest (frontend) |
| `deploy` | push to `main` only (after `test` passes) | Authenticates to GCP via **Workload Identity Federation** (no stored keys), builds the multi-stage backend Docker image (SPA bundled, tagged with commit SHA), deploys to Cloud Run |

WIF pool: `of-github-pool`, provider: `github-provider`, SA: `of-ci-deployer@cfd-lemnisca.iam.gserviceaccount.com`. Locked to repo `Lemniscabio/GCP_openFoam_setup`.

**One-time prerequisite before first deploy:** add repo Variable `OAUTH_CLIENT_ID` in GitHub → Settings → Secrets and variables → Actions → Variables tab.

## Benchmarks

`benchmarks/` contains HTML dashboards from machine selection runs used to pick c2d-highcpu as the standard machine family. Open in a browser — no server needed.

| File | What it covers |
|---|---|
| `bench_1.html` | c2d vs c3d across 8–16 vCPU, MPI=cores vs MPI=vCPU, scaling efficiency |
| `bench_2.html` | 16 vCPU family shootout: c2d / c4d / c2 / c3d — c2d wins on both runtime and cost |
