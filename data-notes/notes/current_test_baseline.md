# Current Test Baseline

Captured from the first working upload/test loop.

- GCP project ID: `project-688a4c78-5d5b-45b3-b5d`
- Batch container image: `docker.io/kartikeyattri/openfoam`
- Final VM shape under test: `c2d-standard-16`
- Core: 8
- CPU milli: `16000`
- Memory MiB: `65536`
- Local SSD size GB: `100`
- Observed prior reference run: `c2d-standard-8` took `1h 24m`

(  scripts/submit_one_case.sh \
    project-688a4c78-5d5b-45b3-b5d \
    us-central1 \
    docker.io/kartikeyattri/openfoam \
    case_0002 \
    fixed \
    c2d-standard-16 \
    16000 \
    65536 \
    100 \
    43200s)
