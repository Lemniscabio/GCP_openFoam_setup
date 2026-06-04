# GCP OpenFOAM Setup

OpenFOAM CFD automation on Google Cloud — upload cases, run on Cloud Batch, get results back in GCS.

## What's here

```
phase3-run-app/    ← THE ACTIVE SYSTEM — web app + CLI + runtime
benchmarks/        ← historical machine comparison runs (bench_1.html, bench_2.html)
.github/workflows/ ← CI/CD (test gate + deploy to Cloud Run on push to main)
```

## Active system: Phase 3

**[phase3-run-app/README.md](phase3-run-app/README.md)** — everything you need:
quick start, case format, CLI reference, deploy, auth, troubleshooting.

The short version:
- Web app at `https://of-batch-app-380489820300.us-central1.run.app` — sign in with `@lemnisca.bio`, drag-drop upload, click to run
- `of` CLI for the same operations from the terminal
- GCP project: `cfd-lemnisca`, bucket: `cfd-lemnisca-cases`, region: `us-central1`
- CI deploys on push to `main` via Workload Identity Federation

## Benchmarks

`benchmarks/` contains HTML dashboards from machine selection runs used to pick c2d-highcpu as the standard machine family. Open in a browser — no server needed.

| File | What it covers |
|---|---|
| `bench_1.html` | c2d vs c3d, MPI=cores vs MPI=vCPU, scaling efficiency |
| `bench_2.html` | 16 vCPU family comparison: c2d / c4d / c2 / c3d |
