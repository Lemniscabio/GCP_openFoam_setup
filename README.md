# OpenFOAM Batch Workflow

This repo is the infrastructure side of one specific workflow:

1. A professor prepares an OpenFOAM case locally.
2. The professor uploads that case to GCS using the professor-side upload script.
3. An admin verifies the uploaded case and submits a GCP Batch job.
4. The Batch job downloads the case, runs the uploaded `command.sh`, and writes results back to GCS.

This README is intentionally detailed. It documents the current structure, what each file does, why the supporting files exist, and the main operational pitfalls.

## Repo Structure

The repo is split by responsibility:

```text
openfoam-batch/
  Dockerfile
  README.md
  scripts/
    admin/
      check_case_prefix.sh
      run_case_in_batch.sh
      submit_all_ready_cases.sh
      submit_one_case.sh
    prof/
      command.sh
      professor_upload_case.sh
```

Meaning:

- `scripts/prof/` is professor-facing.
- `scripts/admin/` is operator/runtime-facing.
- `Dockerfile` builds the runtime image used by GCP Batch.

The professor should only need:

- `scripts/prof/professor_upload_case.sh`
- `scripts/prof/command.sh`

The admin should use:

- `scripts/admin/check_case_prefix.sh`
- `scripts/admin/submit_one_case.sh`
- `scripts/admin/submit_all_ready_cases.sh`

The Batch VM itself runs:

- `scripts/admin/run_case_in_batch.sh`

## What Each Script Does

### `scripts/prof/professor_upload_case.sh`

Professor-side upload helper.

It:

- accepts a case directory and a `command.sh`
- creates `case.tar.gz`
- creates `manifest.json`
- creates `SHA256SUMS`
- uploads all objects to GCS
- uploads `READY` last

It also supports auto-generated case IDs by passing `AUTO`.

Example:

```bash
./scripts/prof/professor_upload_case.sh AUTO /path/to/case ./scripts/prof/command.sh
```

### `scripts/prof/command.sh`

Professor-provided case execution logic.

This file should contain only the case-specific CFD commands. It should not contain GCS download logic, result upload logic, or batch orchestration logic.

Current template:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${MPI_RANKS:?MPI_RANKS is required}"

foamDictionary system/decomposeParDict -entry numberOfSubdomains -set "${MPI_RANKS}"
decomposePar -force
mpirun --oversubscribe -np "${MPI_RANKS}" simpleFoam -parallel
reconstructPar
```

Important:

- `MPI_RANKS` is not set by the upload script.
- `MPI_RANKS` is set later by the admin submission script through the Batch task environment.
- `MPI_RANKS` is an explicit admin input and is not derived automatically from `CPU_MILLI`.
- The current working directory when `command.sh` runs is the extracted OpenFOAM case root.

### `scripts/admin/check_case_prefix.sh`

Admin-side verification helper.

It checks that the required GCS objects exist for a case:

- `case.tar.gz`
- `command.sh`
- `manifest.json`
- `READY`
- `SHA256SUMS`

This is for validation before submission. The professor does not need this script.

Example:

```bash
./scripts/admin/check_case_prefix.sh case_0002
```

### `scripts/admin/submit_one_case.sh`

Admin-side single-case launcher.

It:

- verifies the case exists in GCS
- constructs the Batch job JSON
- sets the Batch runtime environment variables
- submits one GCP Batch job
- writes a submission marker to GCS

This is the script you use first to validate the full workflow.

### `scripts/admin/submit_all_ready_cases.sh`

Admin-side bulk launcher.

It:

- scans GCS for all `READY` cases
- submits one separate Batch job per ready case
- uses the same fixed machine shape for every case

This is not a multi-task Batch array design. It is a simple “one case -> one job” loop.

### `scripts/admin/run_case_in_batch.sh`

Batch runtime wrapper.

This script is not meant to be run manually. It runs inside the Batch VM/container.

It:

- downloads the case inputs from GCS
- verifies `SHA256SUMS`
- extracts the case into local scratch storage
- runs the uploaded `command.sh`
- captures logs and exit code
- uploads compressed results back to GCS

This is the reason the runtime image must contain a copy of this file.

## Why A Separate Runtime Script Exists

`command.sh` and `run_case_in_batch.sh` solve different problems.

`command.sh` is the case logic:

- decomposition
- solver run
- reconstruction

`run_case_in_batch.sh` is the platform logic:

- download from GCS
- verify inputs
- extract archive
- enter case directory
- execute `command.sh`
- collect outputs
- upload results

Keeping them separate is the better design because:

- professor owns case logic only
- admin owns infrastructure/runtime logic
- less duplication
- easier debugging
- cleaner future changes

Without a separate runtime script, all orchestration would have to be embedded inline in the Batch job definition, which is harder to maintain.

## GCS Layout

Current expected bucket layout:

```text
gs://openfoam_cases/
  cases/
    CASE_ID/
      case.tar.gz
      command.sh
      manifest.json
      SHA256SUMS
      READY
  submissions/
    CASE_ID/
      fixed.latest.json
  results/
    CASE_ID/
      fixed/
        JOB_NAME/
          manifest.json
          runtime.json
          solver.stdout.log
          exit_code.txt
          result.tar.gz
          _SUCCESS | _FAILED
```

## Why `READY` Exists

`READY` is just a small GCS object uploaded last.

It is not a directory and not a special GCS feature. It is simply a normal object used as a completion marker.

Reason:

- GCS uploads happen object by object
- a case prefix can be partially uploaded
- the admin submit script needs a way to know “this case is complete and safe to run”

So the upload flow is:

1. upload `case.tar.gz`
2. upload `command.sh`
3. upload `manifest.json`
4. upload `SHA256SUMS`
5. upload `READY` last

That means `READY` tells the admin side:

- upload is complete
- required files should already exist
- the case is eligible for submission

## Why `SHA256SUMS` Exists

`SHA256SUMS` is an integrity file.

It contains SHA-256 hashes for the uploaded payload files, currently:

- `case.tar.gz`
- `command.sh`

Reason:

- the Batch job downloads files from GCS
- before running the simulation, it should verify that the downloaded files are exactly the same bytes that were uploaded

This is mainly for integrity and reproducibility, not for end-user security.

If the checksum check fails, the Batch job stops before running OpenFOAM.

## Why The Case Is Tarred

The case is uploaded as `case.tar.gz` for workflow reliability.

This is not mainly because the case is “too big”. The important reasons are:

- an OpenFOAM case is a directory tree, not a single file
- one archive is easier to upload and download than many small files
- one archive is easier to checksum
- one archive is easier to treat as an immutable case package

No CFD case information is inherently lost by creating `case.tar.gz`, assuming creation and extraction succeed.

Tar + gzip preserves:

- file contents
- directory structure
- filenames
- normal permissions

## Runtime Image

The Batch runtime image must include:

- OpenFOAM
- `gcloud storage`
- `python3` if your case workflow needs it
- `/opt/openfoam-batch/run_case_in_batch.sh`

The current `Dockerfile` does exactly that by copying the admin runtime script into the image:

```dockerfile
COPY scripts/admin/run_case_in_batch.sh /opt/openfoam-batch/run_case_in_batch.sh
```

That is why the image must be built from this repo root.

### Build Command

Run from:

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
```

Build and push:

```bash
docker buildx build \
  --platform linux/amd64 \
  -t docker.io/kartikeyattri/openfoam:12 \
  --push .
```

### Why `linux/amd64` Matters

Your GCP Batch VMs are `x86_64` machines. In practice, Batch expects a `linux/amd64` container image here.

Because you are building from a Mac, if you push only an Apple Silicon image, Batch can fail with:

```text
no matching manifest for linux/amd64 in the manifest list entries
```

So the safe build command is the `docker buildx build --platform linux/amd64 ... --push .` form above.

## Batch Service Account Behavior

The current scripts do not explicitly set a custom service account in the Batch job JSON.

That means GCP Batch uses the project’s default Compute Engine service account.

Important distinction:

- your local `gcloud auth login` lets you submit jobs from your laptop
- the Batch VM still needs its own identity to read inputs and write results

So even though you do not pass a service account into the scripts anymore, the Batch VM still runs under a service account identity.

That default service account needs permission to:

- read from `gs://openfoam_cases/cases/...`
- write to `gs://openfoam_cases/results/...`
- write submission metadata

## End-To-End Flow

### Professor Flow

Run:

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
./scripts/prof/professor_upload_case.sh AUTO /path/to/case ./scripts/prof/command.sh
```

This:

- auto-assigns a case ID like `case_0002`
- uploads the case package
- uploads `READY` last

### Admin Flow For One Case

Verify:

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
./scripts/admin/check_case_prefix.sh case_0002
```

Submit:

```bash
./scripts/admin/submit_one_case.sh \
  project-688a4c78-5d5b-45b3-b5d \
  us-central1 \
  docker.io/kartikeyattri/openfoam:12 \
  case_0002 \
  fixed \
  c2d-standard-16 \
  16000 \
  8 \
  65536 \
  100 \
  43200s
```

This creates one separate Batch job for one case.

### Admin Flow For All Ready Cases

Submit every ready case on the same fixed VM shape:

```bash
./scripts/admin/submit_all_ready_cases.sh \
  project-688a4c78-5d5b-45b3-b5d \
  us-central1 \
  docker.io/kartikeyattri/openfoam:12 \
  c2d-standard-16 \
  16000 \
  8 \
  65536 \
  100 \
  43200s
```

This creates one separate Batch job per ready case.

It does not create a single multi-case Batch job.

## One Job Per Case

Current model:

- one uploaded case
- one Batch job
- one task per job
- one fixed VM shape

`submit_all_ready_cases.sh` simply loops over ready cases and repeatedly calls `submit_one_case.sh`.

So:

- 1 ready case -> 1 Batch job
- 10 ready cases -> 10 Batch jobs

Inside each job:

- `taskCount = 1`
- `parallelism = 1`

The MPI parallelism for OpenFOAM happens inside the container through `mpirun`, not through Batch task arrays.

## Current Parameter Baseline

Current test baseline:

- project ID: `project-688a4c78-5d5b-45b3-b5d`
- bucket: `openfoam_cases`
- image: `docker.io/kartikeyattri/openfoam:12`
- region: `us-central1`
- machine type: `c2d-standard-16`
- CPU milli: `16000`
- MPI ranks: `8`
- memory MiB: `65536`
- local SSD GB: `100`
- max run duration: `43200s`

Prior reference note:

- `c2d-standard-8` took about `1h 24m` for the earlier reference run

Run commands and operator snippets are recorded in [run_commands.md](/Users/kartikey/Desktop/temp/data-notes/notes/run_commands.md).
Benchmark logging and scaling/cost comparison notes are recorded in [current_test_baseline.md](/Users/kartikey/Desktop/temp/data-notes/notes/current_test_baseline.md).

## Path Dependencies

Some files in this repo are path-dependent. If you rename or move folders, update these references before rebuilding or running anything:

- [Dockerfile](/Users/kartikey/Desktop/temp/openfoam-batch/Dockerfile) copies `scripts/admin/run_case_in_batch.sh` into the image
- [README.md](/Users/kartikey/Desktop/temp/openfoam-batch/README.md) contains example command paths for `scripts/prof/...` and `scripts/admin/...`
- your shell commands must match the real script paths after any reorganization

Quick verification after moving files:

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
test -f scripts/prof/professor_upload_case.sh
test -f scripts/prof/command.sh
test -f scripts/admin/check_case_prefix.sh
test -f scripts/admin/run_case_in_batch.sh
test -f scripts/admin/submit_one_case.sh
test -f scripts/admin/submit_all_ready_cases.sh
```

## Main Failure Modes To Check First

If a job fails, check these in order:

1. Wrong image architecture
   Example error:
   `no matching manifest for linux/amd64 in the manifest list entries`
2. Missing runner script inside the image
   Example symptom:
   Batch cannot execute `/opt/openfoam-batch/run_case_in_batch.sh`
3. GCS permission problems for the default Compute Engine service account
4. Failure inside the professor’s `command.sh`
5. Case-specific OpenFOAM failure

Useful commands:

```bash
gcloud batch jobs describe JOB_NAME --location us-central1
```

```bash
gcloud logging read \
  'logName="projects/project-688a4c78-5d5b-45b3-b5d/logs/batch_agent_logs" AND labels.job_uid="JOB_UID"' \
  --limit=50 \
  --format="value(textPayload)"
```

```bash
gcloud storage ls gs://openfoam_cases/results/CASE_ID/fixed/JOB_NAME/
```

## IAM Summary

Minimum practical roles:

- your local user:
  - `roles/batch.jobsEditor`
  - `roles/iam.serviceAccountUser`
- professor uploader:
  - `roles/storage.objectUser`
- default Compute Engine service account:
  - permission to read case inputs from GCS
  - permission to write results/submission metadata to GCS

## Final Operational Model

This repo is not for storing case data long-term.

Recommended separation:

- `openfoam-batch/` -> infra repo
- local case folders elsewhere -> working CFD data
- GCS -> case exchange + result store

The intended workflow is:

- professor uploads cases
- admin validates and submits
- Batch executes one job per case
- results return to GCS
