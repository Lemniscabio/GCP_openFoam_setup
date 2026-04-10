# Run Locally

Use this note to reproduce case execution locally with the same Docker image that GCP Batch uses.

## Purpose

This is useful when:

- a Batch job fails and you want faster iteration locally
- you want to compare MPI rank counts before resubmitting to GCP
- you want to confirm whether a failure is infrastructure-related or solver-related

The extra Batch runner script inside the image does not affect this local workflow unless you explicitly call it.

## Local Run Command

Run this from inside the OpenFOAM case directory.

Assumptions:

- the case directory already contains `command.sh`
- `command.sh` has execute permission
- the image tag is `docker.io/kartikeyattri/openfoam:12`

```bash
docker run --rm -it \
  --platform linux/amd64 \
  --entrypoint /bin/bash \
  -e MPI_RANKS=10 \
  -v "$PWD":/case \
  -w /case \
  docker.io/kartikeyattri/openfoam:12 \
  -lc './command.sh'
```

## Notes

- for local Mac testing, set `MPI_RANKS` to the local value you want to test
- for GCP `c2d-standard-16`, current intended `MPI_RANKS` is `8`
- local testing should run `command.sh` directly, not `/opt/openfoam-batch/run_case_in_batch.sh`

## Professor Upload Command

Run from the infra repo root:

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
./scripts/prof/professor_upload_case.sh AUTO /path/to/case ./scripts/prof/command.sh
```

Example result:

- uploaded case ID: `case_0002`

## Admin Verification Command

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
./scripts/admin/check_case_prefix.sh case_0002
```

## Admin Batch Submit Command

Current exact command for the `c2d-standard-16` test:

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
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

To force a rerun for the same case label:

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
FORCE_SUBMIT=1 ./scripts/admin/submit_one_case.sh \
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

## Image Build Command

Build from the infra repo root:

```bash
cd /Users/kartikey/Desktop/temp/openfoam-batch
docker buildx build \
  --platform linux/amd64 \
  -t docker.io/kartikeyattri/openfoam:12 \
  --push .
```
