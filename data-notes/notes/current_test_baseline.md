# Benchmark Log Template

Use this file as a reusable experiment log for machine-size and MPI-scaling comparisons.

The intent is:

- keep one shared place for all benchmark runs
- log each experiment as `test1`, `test2`, ..., `testN`
- paste the exact machine specs and command used
- record raw metrics from the run
- compute speedup, efficiency, and cost
- compare multiple configurations later and choose the best tradeoff

## Shared Context

- GCP project ID: `project-688a4c78-5d5b-45b3-b5d`
- GCS bucket: `openfoam_cases`
- Batch region: `us-central1`
- current image under test: `docker.io/kartikeyattri/openfoam:12`

## Measurement Command

Use this inside the case directory when measuring solver scaling directly:

```bash
/usr/bin/time -v mpirun -np <N> simpleFoam -parallel > log.<N> 2>&1
```

Example:

```bash
/usr/bin/time -v mpirun -np 32 simpleFoam -parallel > log.32 2>&1
```

This captures:

- wall-clock time
- CPU usage
- maximum resident set size
- system-level timing details

## Metrics To Record

From each `log.<N>` file, extract:

- elapsed wall-clock time
- percent CPU used
- maximum resident set size

Suggested comparison table:

| MPI Ranks | Runtime (min) | CPU % | Peak Memory (MB) | Speedup vs 8 | Efficiency vs 8 | Cost / Simulation |
| --- | --- | --- | --- | --- | --- | --- |
| 8 |  |  |  | 1.00 | 1.00 |  |
| 16 |  |  |  |  |  |  |
| 32 |  |  |  |  |  |  |
| 64 |  |  |  |  |  |  |

## Formulas

Baseline:

- use `8` ranks as the reference point unless explicitly stated otherwise

Speedup:

```text
Speedup = Time_at_8 / Time_at_N
```

Parallel efficiency:

```text
Efficiency = Speedup / (N / 8)
```

Example:

- if `8 ranks = 120 min`
- and `32 ranks = 45 min`

then:

```text
Speedup = 120 / 45 = 2.67
Efficiency = 2.67 / (32 / 8) = 2.67 / 4 = 0.667 = 66.7%
```

Interpretation guide:

| Efficiency | Meaning |
| --- | --- |
| > 70% | Excellent scaling |
| 50-70% | Acceptable |
| 30-50% | Marginal |
| < 30% | Wasteful |

When efficiency drops sharply, that is the likely scaling ceiling.

## Cost Calculation

For each tested configuration:

```text
Cost per simulation = VM hourly price x runtime in hours
```

Example:

- if a VM costs `$1.20/hour`
- and runtime is `2 hours`

then:

```text
Cost per simulation = $2.40
```

Choose the final configuration based on whichever matters more:

- lowest cost per simulation
- lowest turnaround time

## Logged Tests

### test1

- date: `2026-04-08`
- source: prior successful Batch run
- job name: `openfoam-20260408-134733`
- job uid: `openfoam-20260408-a2294ca1-a5bf-48a900`
- result: `Succeeded`
- execution mode: `Batch`
- image: `docker.io/kartikeyattri/openfoam`
- machine type: `c2d-standard-8`
- vCPU: `8`
- physical cores intended for MPI: `4`
- CPU milli: `unknown`
- MPI ranks: `unknown`
- memory: `31.25 GB`
- local/persistent disk: `100 GB`
- disk type: `pd-ssd`
- batch region: `us-central1`
- runtime: `1 hour 24 minutes`
- wall-clock runtime (min): `84`
- cost_per_hour: `$0.36`
- estimated_cost_per_simulation: ``
- speedup_vs_8: `1.00` if treated as 8-core baseline
- efficiency_vs_8: `1.00` if treated as 8-core baseline
- exact command used: `unknown from this note`
- notes:
  - successful reference run shown from the Batch job details page
  - runnable used `docker.io/kartikeyattri/openfoam`
  - storage in this run was `100 GB pd-ssd`

### test2

- date: `2026-04-10`
- source: successful Batch run
- job name: `of-case-0002-fixed-20260410053921`
- job uid: `of-case-0002-fixed-dc90c669-6857-41bd0`
- result: `Succeeded`
- execution mode: `Batch`
- image: `docker.io/kartikeyattri/openfoam:12`
- machine type: `c2d-standard-16`
- vCPU: `16`
- physical cores intended for MPI: `8`
- CPU milli: `16000`
- MPI ranks: `8`
- memory: `64 GB`
- local/persistent disk: `100 GB`
- disk type: `local-ssd`
- batch region: `us-central1`
- runtime: `52 minutes 30 seconds`
- wall-clock runtime (min): `52.5`
- cost_per_hour: `$0.73`
- estimated_cost_per_simulation:
- speedup_vs_8: `84 / 52.5 = 1.60` if compared against `test1`
- efficiency_vs_8: `1.60 / (8 / 8) = 1.00` if compared against `test1` as the 8-core baseline
- exact command used:
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
- notes:
  - successful Batch run after fixing image architecture to `linux/amd64`
  - successful Batch run after correcting `MPI_RANKS` from `16` to `8`

### testN template

Copy this block for each new experiment.

```text
### testN

- date:
- source:
- job name:
- job uid:
- result:
- execution mode: Batch or Local
- image:
- machine type:
- vCPU:
- physical cores intended for MPI:
- CPU milli:
- MPI ranks:
- memory:
- local/persistent disk:
- disk type:
- batch region:
- runtime:
- wall-clock runtime (min):
- cost_per_hour:
- estimated_cost_per_simulation:
- speedup_vs_8:
- efficiency_vs_8:
- exact command used:
- notes:
```

## Current Notes

- Batch job names are generated as `of-<case-id>-<label>-<timestamp>`
- case IDs like `case_0002` are sanitized to Batch-safe job names like `case-0002`
- `MPI_RANKS` must be provided explicitly and is not derived from `CPU_MILLI`
- for `c2d-standard-16`, current intended Batch setting is `CPU_MILLI=16000` and `MPI_RANKS=8`
