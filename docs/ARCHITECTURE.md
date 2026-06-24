# Pipeline Architecture — 3D geometry → OpenFOAM case → GCP run

This document explains the **whole** stirred-tank-reactor (STR) CFD automation pipeline, in
three parts:

1. **CAD / geometry** — `part-a-cad/` — a JSON reactor spec becomes parametric 3D geometry (STLs).
2. **OpenFOAM case generation** — `part-a-cad/str_cad/ofcase/` + `variations.py` + `verify/` — the
   geometry becomes a complete, runnable OpenFOAM case (single-phase or two-phase), plus sweeps and verification.
3. **GCP execution** — `phase3-run-app/` — the case is uploaded, run on Google Cloud Batch, and its
   results/checkpoints land back in Cloud Storage, fronted by a Cloud Run web app + `of` CLI.

The three parts are deliberately decoupled and communicate through **files**: Part 1 emits STLs +
`str-params.json`; Part 2 consumes those and emits a full OpenFOAM case directory (with a
`command.sh` that knows how to run it); Part 3 ships that directory to a VM and executes `command.sh`.

```
JSON spec ──▶ [Part 1: CadQuery] ──▶ region STLs + str-params.json
          ──▶ [Part 2: ofcase]   ──▶ OpenFOAM case dir (0/, constant/, system/, command.sh, metadata.json)
          ──▶ [Part 3: GCP]      ──▶ Cloud Batch VM runs command.sh ──▶ results/ + checkpoints/ in GCS
```

---

# PART 1 — CAD / Geometry (`part-a-cad/str_cad`)

**Job:** turn a small JSON spec into the **fluid-domain** geometry of a baffled stirred tank, exported
as one STL per boundary region, ready for `snappyHexMesh`.

**Stack:** Python 3.11 · **CadQuery** (Python API over the OpenCASCADE / OCCT kernel) for solid
modeling · **trimesh** for STL post-processing/validation · **pydantic v2** for the schema.

## 1.1 The spec and the 3-tier input model (`schema.py`)

The input is one JSON object validated into `STRParams` (pydantic). Inputs are deliberately tiered so
a user specifies the *reactor*, not every dimension:

- **Tier 1 — required (defines the reactor):** `family`, `physics` (`single_phase`|`two_phase`),
  `tank{diameter_m, height_m, bottom}` (`bottom` = `dished`|`flat`), `liquid{height_m}`,
  `baffles{count, height_m, arrangement}`, `shaft{central}`,
  `impellers{count, type, blades, diameter_ratio, lowest_clearance_m, inter_impeller_clearance_m}`,
  and `operating{rpm}` (+ for two-phase a gas input: `gas_flow_vvm` or `sparger{ring_diameter_m}`).
- **Tier 2 — derived correlations (omittable, overridable, logged):** computed in `STRParams.derived()`:
  - impeller diameter `D = diameter_ratio · tank.diameter_m` (`impeller_diameter_m`, a pydantic
    `computed_field`);
  - blade length `D/4`, blade height `D/5` (auto-filled by the `_fill_blade_dimensions` validator if
    absent, and constrained to within 10 % of those values if supplied);
  - shaft radius `max(0.03, D/20)`, impeller hub radius `D/12`;
  - baffle width `T/12` (auto-filled by `_fill_baffle_width` if omitted; `T` = tank diameter);
  - MRF rotor-zone radius `0.55 D` (the radius used by the MRF cell-zone writer; this is the single
    source of truth — the MRF writer reads it back from `derived()`);
  - mesh-refinement radius `0.65 D` (the snappy refinement region around the impeller column).
- **Tier 3 — advanced overrides:** any Tier-2 value can be set explicitly; solver/scheme knobs live in
  Part 2's `CaseParams`.

**Validation** (`_check_cross_fields`, run from an overridden `model_validate`): liquid height ≤ tank
height; impellers must fit below the liquid; blade dims within 10 % of correlation; and for two-phase,
a **usable** gas input must exist (`gas_flow_vvm > 0`, or a sparger with `ring_diameter_m > 0`) — an
empty `sparger{}` is rejected. Extra top-level keys (e.g. `_provenance`, `run`) are ignored by pydantic,
which is exploited later by the variations layer.

## 1.2 Family + impeller registry (`geometry/registry.py`)

The pluggability mechanism. `get_family(name)` returns a small `Family` object exposing `REGION_NAMES`
and `build_fluid_domain(p)`; `get_impeller(type_)` returns a per-impeller builder. The stirred-tank
family is registered as `"stirred_tank_reactor"` and the `"rushton"` impeller builder is registered.
**Adding a new impeller type or reactor family = registering a new function/module here — no change to
the pipeline core.** The concrete builders live under `geometry/families/str/`; the old module paths
(`geometry/assembly.py`, `vessel.py`, …) are thin re-export shims so all consumers keep importing the
same names.

## 1.3 Building the fluid solid (`geometry/families/str/`)

The geometry produced is the **liquid region** (the fluid the solver meshes), i.e. the vessel interior
with all wetted internals subtracted:

- **`vessel.py — build_vessel_shell(p)`**: a cylinder of radius `T/2` extruded to the liquid height.
  For `bottom == "dished"` a bottom head is added by drawing an arc in the XZ plane from the rim `(R,0)`
  through `(R/√2, −R/√2)` to the axis `(0,−R)` and **revolving it 360°** about the Z axis (a
  hemispherical head, deepest point at `z = −R`); for `"flat"` the bare cylinder (closed flat bottom at
  `z = 0`) is returned. Unknown bottoms raise `SchemaError`.
- **`internals.py — build_shaft(p)`**: a central cylinder, radius `max(0.03, D/20)`, full liquid height.
- **`internals.py — build_impellers(p)`** via `get_impeller("rushton")`: at each axial position
  (`impeller_z_positions` = `lowest_clearance + i·inter_impeller_clearance`) a **Rushton disc turbine**:
  a thin disc (radius `0.66·D/2`, thickness 10 mm), a hub (radius `D/12`), and `blades` rectangular
  blades (length `blade_length`, height `blade_height`) placed at `D/2 − blade_length/2` and rotated to
  `360·i/blades` degrees, all unioned.
- **`baffles.py — build_baffles(p)`**: `count` rectangular plates (width `baffle_width`, thickness 20 mm,
  height `baffle_height`) at the wall, evenly spaced in angle.
- **`assembly.py — build_fluid_solid(p)`**: `vessel_shell` minus (`shaft` ∪ impellers ∪ baffles) — a
  single CadQuery boolean cut chain, yielding the fluid solid.

## 1.4 Boundary-region classification (`assembly.py — build_fluid_domain`)

`snappyHexMesh` needs each boundary surface tagged so the solver can apply BCs. The fluid solid's faces
are iterated and each is classified by geometry type + position into one of six **regions**
(`REGION_NAMES`): `tankWall, dishedBottom, baffles, shaft, impellers, liquidSurface`. The rules
(with a position tolerance scaled to the vessel size):

- planar face with near-vertical normal at the top (`z ≈ liquid_height`) → `liquidSurface`;
- face center below `z < 0` → `dishedBottom`;
- within impeller radius and within ±½ blade-height of an impeller plane → `impellers`;
- cylindrical and near the axis → `shaft`; cylindrical and near the wall → `tankWall`;
- otherwise → `baffles`.

Each region's faces are merged into one `cq.Compound`. **Consequence (a known simplification):** all N
impellers fall into a single `impellers` region → one merged impeller patch downstream (one combined
torque, not per-impeller).

## 1.5 STL export (`export.py`)

Each region compound is exported with `cq.Shape.exportStl` (linear tolerance 1e-4, angular 0.1), then
**re-loaded in trimesh** to drop degenerate faces and unreferenced vertices and re-exported — this
cleans the tessellation so `snappyHexMesh` gets watertight, non-degenerate surfaces. Output:
`<out>/geometry/<region>.stl` (6 files) plus `<out>/str-params.json` (the validated spec, the contract
for Part 2).

## 1.6 Meshing dictionaries (`meshcase.py — make_mesh_case`)

Generates the meshing half of the OpenFOAM case from the STLs (this is shared by single- and two-phase):

- copies the region STLs into `constant/triSurface/`;
- computes a **bounding box** over all STLs (+10 % margin) and a **background `blockMeshDict`**: one
  `hex` block sized to the box with cell count `≈ span / 0.12 m` per axis (≈12 cm base cells), one
  `allBoundary` patch;
- **`snappyHexMeshDict`**: `castellatedMesh` + `snap` (no add-layers). Each region STL is a
  `triSurfaceMesh` and a `refinementSurface` (the rotating/internal surfaces `shaft`/`impellers`/
  `baffles` get surface level `(2 3)`, the rest `(1 1)`). A `searchableCylinder` **rotorColumn**
  (radius `0.65 D`, spanning the impeller stack ± a blade height) is a `refinementRegion` (`inside`,
  level 2) so the mesh is finer through the swept impeller volume. `locationInMesh` is placed off-axis
  inside the liquid (`0.4 R` at 45°, mid-height) so the mesher keeps the fluid side;
- a standard **`meshQualityDict`** (maxNonOrtho 65, skewness, min vol/twist, etc.).

---

# PART 2 — OpenFOAM case generation (`ofcase/`, `variations.py`, `verify/`)

**Job:** from the geometry + an operating point, write **every** OpenFOAM dictionary so the case runs,
choosing the physics (single-phase RANS MRF, or two-phase Euler–Euler), plus a `command.sh` that runs
the full pipeline. Validated against the hand-built `references/singlephase/` and
`references/twophase/` reference cases ("golden oracles"). Target solver: **OpenFOAM 12**
(`foamRun` with selectable solver modules).

## 2.1 Operating point (`ofcase/caseparams.py`)

`CaseParams`: `rpm` (with `omega_rad_s = rpm·2π/60` as a computed field), `viscosity_m2_s`,
`patch_roles` (defaults: `liquidSurface` = slip, everything else = wall), and a nested `Run`
(`end_time`, `write_interval`, `cores`, plus `verify: bool` / `verify_steps: int` for smoke runs).
`build_case(case_params, geo_dir, out_dir)` loads `str-params.json`, runs `make_mesh_case`, then
**dispatches on `sp.physics`** to the single-phase or two-phase writers.

## 2.2 Single-phase physics (incompressible RANS + MRF)

A steady, single-phase, turbulent stirred tank using the **MRF (Multiple Reference Frame / "frozen
rotor")** approach.

- **`physics.py`**: `physicalProperties` (Newtonian `nu` with the right dimensions) and
  `momentumTransport` (`RAS`, model **k-ε**, turbulence on).
- **`systemdicts.py`**: `controlDict` (`application foamRun; solver incompressibleFluid;`,
  steady iteration count), `fvSchemes` (`ddt steadyState`, bounded Gauss `limitedLinearV/limitedLinear`
  divergence for U/k/ε), `fvSolution` (GAMG for `p`, smoothSolvers for U/k/ε, `SIMPLE` block with
  `pRefCell/pRefValue`, relaxation factors), and `decomposeParDict` (`scotch`).
- **`mrf.py`**: this is the rotation model.
  - `rotor_cylinders(sp)` = one short cylinder (radius `0.55 D`, height `1.5·blade_height`) **per
    impeller**; `write_toposet_dict` unions them all into a **single `rotor` cellZone** via `topoSet`
    (`cylinderToCell` → one `cellSet` → one `cellZoneSet`).
  - `write_mrf_properties` writes one `MRF{ cellZone rotor; omega N [rpm]; }`. Because there's exactly
    one MRF zone, the impeller wall BC needs no explicit zone name.
- **`fields.py`** writes `0/{U,p,k,epsilon,nut}` with per-region BCs by role:
  - walls (`tankWall`/`dishedBottom`/`baffles`): `U noSlip`, `p zeroGradient`, k/ε/nut **wall functions**
    (`kqRWallFunction`/`epsilonWallFunction`/`nutkWallFunction`);
  - `impellers`: `U MRFnoSlip` (no-slip in the rotating frame);
  - `shaft`: `U rotatingWallVelocity` (origin, axis Z, `omega = omega_rad_s`) — the shaft physically
    spins along its full length (the MRF zone only covers the impeller disks, so the inter-impeller
    shaft would otherwise be static — this was a real bug we fixed);
  - `liquidSurface`: `U slip` (rigid-lid free surface).
- **`command.py`** writes `command.sh`: `blockMesh → snappyHexMesh -overwrite → topoSet →
  (set numberOfSubdomains = MPI_RANKS) → decomposePar -force → mpirun -np N foamRun -parallel →
  reconstructPar`, with an `OF_RESUME` fast-path that skips meshing on a checkpoint resume.

## 2.3 Two-phase physics (Euler–Euler gas–liquid, `multiphaseEuler`)

A transient, two-fluid (gas + liquid) model for an aerated/sparged tank.

- **`two_phase/physics.py`**:
  - `phaseProperties`: `basicMultiphaseSystem`, `phases (gas liquid)`, each a
    `pureIsothermalPhaseModel` with a constant bubble/droplet diameter (gas 3 mm, liquid 10 mm);
    interphase closures: **drag** `SchillerNaumann` (gas-dispersed-in-liquid), **virtual mass**
    (`Cvm 0.5`), **turbulent dispersion** `Burns` (`σ 0.9`), **surface tension** 0.072 N/m, blending
    `continuous` in liquid.
  - per-phase `physicalProperties`: liquid = water (`rho 1000`, `eConst`, `mu 1e-3`, `Pr 7`), gas = air
    (`rho 1.2`, `hConst`, `mu 1.8e-5`); per-phase `momentumTransport`: **liquid k-ε**, **gas laminar**;
    plus `constant/g` (gravity, required for `p_rgh`).
- **`two_phase/fields.py`** writes 12 fields: `U.gas/U.liquid` (vector), `alpha.gas/alpha.liquid`
  (phase fractions), `p`, `p_rgh`, `k.liquid`, `epsilon.liquid`, `nut.liquid`, `alphat.liquid`,
  `T.gas/T.liquid`. BCs by role:
  - walls: `U.liquid noSlip` / `U.gas slip`; α `zeroGradient`; `p_rgh fixedFluxPressure`; k/ε/nut wall
    functions on the liquid;
  - `impellers`: `MRFnoSlip`; `shaft`: `rotatingWallVelocity`;
  - `liquidSurface` (the top, an outlet): `U pressureInletOutletVelocity`, α `inletOutlet`
    (`phi.gas`/`phi.liquid`), `p_rgh prghPressure` — gas escapes, no liquid leaves.
- **`two_phase/systemdicts.py`**: `controlDict` (`solver multiphaseEuler`, **transient**:
  `deltaT 0.001`, `adjustTimeStep yes`, `maxCo 1.0`, `maxDeltaT 0.01`, `writeControl adjustableRunTime`),
  `fvSchemes` (`ddt Euler`; `vanLeer` for α advection; phase-aware `div(alphaRhoPhi,…)` schemes),
  `fvSolution` (MULES `nAlphaSubCycles`, GAMG for `p_rgh`, `PIMPLE` with `nCorrectors 2`,
  `faceMomentum`, `VmDdtCorrection`, `dragCorrection`), and `setFieldsDict`.
- **Gas initialization (`setFields`)**: a low gas pocket (`cylinderToCell`, α.gas = 0.05) is seeded so
  the first MULES step doesn't see a hard 0→1 jump.

### 2.3.1 Parametric sparging (continuous gas inlet)

Real continuous sparging is added with the **oracle's proven post-mesh method** — no sparger geometry:

- **`two_phase/systemdicts.py` topoSet**: in addition to the rotor cellZone, a `spargerFaces` **faceSet**
  is built from the bottom-wall patch (`patchToFace` on `dishedBottom`) intersected with a sparger
  cylinder (`cylinderToFace`, radius = `sparger_radius(sp)`, low Z column).
- **`createPatchDict`** (`write_create_patch_dict`): turns `spargerFaces` into a new `sparger` patch.
- **`command.sh`** gains `createPatch -overwrite` between `topoSet` and `setFields`.
- **Gas-inlet BCs** on `sparger` in all 12 fields: `U.gas = (0 0 U_super)`, `U.liquid = (0 0 0)`,
  `alpha.gas = 1`, `alpha.liquid = 0`, `p_rgh fixedFluxPressure`, k/ε = small fixed values, etc.
- **`sparger_inlet_velocity(sp)`**: superficial gas velocity from VVM —
  `V_liquid = π·(T/2)²·H`, `Q = gas_flow_vvm · V_liquid / 60`, `U_super = Q / (π·r_sparger²)`. (For the
  reference reactor: 0.5 vvm → 0.122 m/s, matching the oracle's 0.119 m/s.)

`createPatch` honors the pre-existing `sparger` boundaryField entries in the `0/` files, so the patch is
born with the gas-inlet BCs. Verified: gas fraction reaches 1 at the inlet and the gas inventory grows
over time (true continuous injection, not a depleting pocket).

## 2.4 Variations / parameter sweeps (`variations.py`)

- `expand_variations(base_spec, axes)` — Cartesian product over **dotted-path axes** (e.g.
  `{"operating.rpm": [60,100,180], "run.viscosity_m2_s": [1e-6,1e-5]}`), deep-copying the base spec and
  setting each path.
- `generate_sweep(base_spec, axes, out_root)` — for each combo: validate → (skip + record in
  `_skipped` if `SchemaError`, e.g. fill too low for the impellers) → `export_geometry` → derive
  `CaseParams` (rpm from `operating.rpm`, viscosity/cores/**verify** from an optional `run` block) →
  `build_case` → write `params.json`; emits a `runs_map.json`. **No regex/text substitution** on
  dictionaries (it replaced a brittle text-mangling sweeper).

## 2.5 Verification (`verify/harness.py`)

The acceptance signal: a case is "good" if it is **structurally valid and runs a few timesteps**.

- **Verify-mode `controlDict`** (`Run.verify`): shrinks the run to `verify_steps` (single-phase
  iterations) or `verify_steps · deltaT` (two-phase seconds) so a smoke run finishes fast.
- **`parse_smoke_log(text)`** → `SmokeResult{meshed, fields_read, time_advanced, exit_ok, errors}` with
  `.ok` = all true. Markers: blockMesh `End` + snappy "Finished meshing"; solver "Create mesh"/
  "Reading field"; ≥1 `Time = ` line; absence of `FOAM FATAL`.
- **`submit_smoke(case_dir, project="cfd-lemnisca", …)`** orchestrates the `of` CLI
  (`upload → run`) and parses the fetched logs — the on-server path (Part 3).
- **Local verification** (what we actually used): run the generated `command.sh` steps in the
  `kartikeyattri/openfoam:12` Docker image and feed the logs to `parse_smoke_log`. Both physics pass
  (single-phase rpm 100/60; two-phase rpm 100/130; plus the sparged case).

## 2.6 CFD modeling choices & limitations (be explicit)

- **MRF, not sliding mesh (AMI):** steady frozen-rotor; good for power/flow-field/dispersion trends, not
  transient blade-passing.
- **Single merged impeller patch:** one combined torque, not per-impeller; all impellers share one MRF
  zone at one ω.
- **Rushton-only:** the only registered impeller builder (dispatch exists for more).
- **Fixed air/water, isothermal:** `pureIsothermalPhaseModel`, fixed properties, fixed 3 mm bubbles; no
  energy/mass-transfer/reaction yet.
- **Sparger = flat bottom-center inlet disc**, not a discrete ring of orifices.
- **Hemispherical dished bottom** (depth = R), not a shallow torispherical head.
- Each is an additive plug-in (new impeller/family/physics/schema field), not a rewrite.

---

# PART 3 — GCP execution (`phase3-run-app/`)

**Job:** take a generated case directory and run it on **Google Cloud Batch**, durably, with
checkpoint/resume, state tracking, results retrieval, auth, and CI/CD. This is the most production-
hardened part. Project `cfd-lemnisca`, region `us-central1`, bucket `cfd-lemnisca-cases`.

**GCP services:** Cloud Run (web app), Cloud Batch (compute), Cloud Storage (cases/results/checkpoints),
Firestore (run/case/user/project records), Pub/Sub (Batch job-state events), Google OAuth ID-token +
hosted-domain (auth), Artifact Registry (runtime image), Workload Identity Federation (keyless CI).
Two entrypoints: the **`of` CLI**
(`cli/main.py`) and the **FastAPI web app** (`backend/`) — both sit on the same `core/` library.

## 3.1 Storage layout (the contract, `core/storage.py`, `uploads.py`, `results_paths.py`)

All state is bucket-relative paths in `cfd-lemnisca-cases`:

- `cases/<project>/<case_id>/case/…` — the uploaded case tree (incl. `command.sh`, `metadata.json`);
- `cases/<project>/<case_id>/{manifest.json, READY, .reserved}` — case metadata + readiness markers;
- `case-ids/<case_id>` — global create-only markers for atomic id allocation;
- `results/<project>/<codename>/<case_id>/…` — per-run outputs (tarball, logs, markers);
- `checkpoints/<case_id>/<variant>/latest/…` — rsynced solver state for resume.

`StorageClient` is a `Protocol` with a real `GcsStorage` and an `InMemoryStorage` test fake.
`create_exclusive` uses GCS `if_generation_match=0` for **atomic create-only** writes (the basis of
id allocation and idempotency).

## 3.2 Case identity, validation, upload (`cases.py`, `validation.py`, `generate.py`, `cli/main.py`)

- **`CaseRepository.allocate_ids`**: atomic `case_NNNN` allocation — scans existing cases + the
  `case-ids/` registry for the max, then claims the next via `create_exclusive` markers; a lost race
  just advances to the next number (concurrency-safe, empty-bucket-safe).
- **Upload paths:**
  - **CLI** (`of upload`): `gcloud storage rsync` the case tree to `…/case/`, copy `command.sh`, write
    `manifest.json` + `READY`, then validate.
  - **Browser** (`generate.py` + `uploads.py`): the backend mints **per-file V4 signed PUT URLs**
    (`SignedUrlService`, **keyless** — the backend SA signs via IAM `signBlob` using its own OAuth
    token, holding Token Creator on itself); the browser PUTs files directly to GCS.
  - **Generate-then-commit** (`generate.py`): `build_case_local` can build a case from a prompt
    (Gemini → `STRParams` via `str_cad.extract`) or explicit params, then `commit_case` uploads it and
    records it.
- **`validate_case`**: a case is runnable only if `manifest.json`, `READY`, `case/command.sh`
  (referencing `MPI_RANKS`), and a valid `case/metadata.json` all exist.

## 3.3 Batch job spec (`core/batch_jobs.py`, `disks.py`, `machines.py`, `config.py`, `naming.py`)

`BatchJobBuilder` builds the Cloud Batch `Job` JSON; `BatchSubmitter` submits it via `batch_v1`.

- **Task group:** `build_single` (1 case → `taskCount 1`) or `build_multi` (N cases → `taskCount N`,
  `parallelism N`; the runtime resolves its case from `CASE_ID_LIST[BATCH_TASK_INDEX]`).
- **Runnables:** an optional **local-SSD mount script** (formats one SSD, or RAID-0 stripes several via
  `mdadm`, mounting `/mnt/disks/openfoam-scratch`), then the **container runnable** (the OpenFOAM image,
  entrypoint runs `/opt/openfoam-batch/run_case_in_batch.sh`).
- **Compute:** `computeResource{cpuMilli, memoryMib}`; instance policy `{machineType,
  provisioningModel}` (STANDARD or SPOT) with disks. **Machine catalog** (`config.py`): `c2d-highcpu-{2…112}`
  (2 GB/vCPU, default MPI ranks = vCPU/2, local-SSD count sized to vCPU). Scratch is local-SSD (375 GB
  each) or a `pd-ssd` (`disks.py`).
- **Env to the VM:** `BUCKET, PROJECT, CASE_ID(_LIST), VARIANT_ID, JOB_NAME, CPU_MILLI, MPI_RANKS,
  SCRATCH_ROOT`.
- **Naming:** `canonical_case_id` (`case_0001`), `variant_for_machine` (sanitized machine type, used in
  the checkpoint path), and **codenames** (`codenames.py`: a curated wordlist → human job names like
  `falcon`).
- **Logs/notifications:** `logsPolicy CLOUD_LOGGING`; optional Pub/Sub notification on
  `JOB_STATE_CHANGED`. (Known flaw, flagged in code: **no `maxRunDuration`** — a job runs until done or
  manually stopped.)

## 3.4 The VM runtime (`runtime/run_case_in_batch.sh`, `runtime/Dockerfile`)

The script the Batch VM actually runs (inside the OpenFOAM image: `microfluidica/openfoam:12` + the
`gcloud` CLI, OF env via `BASH_ENV`):

1. **Resolve case** (from `CASE_ID` or `CASE_ID_LIST[BATCH_TASK_INDEX]`), set up scratch dirs, derive
   `CASE_PREFIX`, `RESULT_PREFIX`, `CHECKPOINT_PREFIX`.
2. **Download** the case tree (`gcloud storage rsync`) + `manifest.json`; `chmod +x command.sh`.
3. **Resume-from-checkpoint**: if `checkpoints/<case>/<variant>/latest/` exists, rsync it down; if a
   decomposed mesh (`processor0/constant/polyMesh`) is present, set `OF_RESUME=1` and flip
   `controlDict startFrom latestTime` so the solver continues.
4. **Background checkpoint loop**: every `CHECKPOINT_POLL_SEC` (30 s) detect the newest written time
   directory and `rsync` the `processor*/` (or serial time) dirs + `system/` up to the checkpoint
   prefix.
5. **Run the solver**: `setsid bash ./command.sh` in its own process group, teeing stdout to a log;
   capture the exit code. A `TERM/INT` trap flushes a final checkpoint (so a manual stop can resume).
6. **Publish results**: tar the case → upload `manifest.json`, `runtime.json`, `solver.stdout.log`,
   `exit_code.txt`, `result.tar.gz`, `metadata.json` to `RESULT_PREFIX`; write `_SUCCESS` (and **delete
   the checkpoint**) on rc 0, else `_FAILED`. Exit with the solver's rc.

## 3.5 State tracking, events, reconciliation (`run_repo.py`, `status.py`, `reconcile.py`)

- **`RunRepository`** (Firestore `of_runs`, `InMemory` fake): a `RunRecord` per Batch job
  (`state: SUBMITTED → RUNNING → SUCCEEDED|FAILED|CANCELLED`). `try_reserve` is an atomic create;
  `update_state` is a Firestore **transaction** that is **monotonic** — a terminal state is never
  regressed (handles duplicate/late events).
- **Pub/Sub webhook** (`backend/routes_internal.py` `/internal/batch-events`, auth via
  `pubsub_auth.py`): Batch `JOB_STATE_CHANGED` events advance the record.
- **`reconcile_non_terminal`**: a backstop because **job deletion emits no event** — for each
  non-terminal run it queries Batch; if the job is gone → `CANCELLED`, else syncs any missed state.
  (`DELETION_IN_PROGRESS` is deliberately treated as non-terminal so deleted jobs resolve correctly.)
- **`RunStatusService`** (`status.py`): lists Batch jobs / reads one job's status events, and computes
  **progress %** by parsing the latest checkpoint time directory against the case's end time.

## 3.6 Results retrieval (`archives.py`, `backend/routes_results.py`)

Results live in GCS as a tarball + logs. The backend can stream a **zip** of selected result objects
(`build_zip`, streaming `ZIP_STORED` straight from GCS to the response) and mint **signed GET URLs**
(`SignedUrlService.get_url`, optional content-disposition) for direct browser download.

## 3.7 Web app, auth, RBAC (`backend/`)

- **FastAPI** (`main.py`) mounts routers under `/api` (`cases`, `generate`, `jobs`, `me`, `admin`,
  `results`), an unprefixed `/internal` (Pub/Sub push), `/health`, and serves the built SPA from
  `static/`.
- **Auth = Google OAuth ID-token + hosted-domain enforcement** (`backend/auth.py`). IAP is **not** used:
  IAP's domain restriction requires the Cloud Run service to live in an org that owns the domain, and
  this project's org is not `lemnisca.bio`. Instead the browser does Google Sign-In and sends the
  resulting **OAuth2 ID token** as `Authorization: Bearer …`; the backend verifies it against
  `OF_OAUTH_CLIENT_ID` and `user_from_idinfo` enforces `email_verified` **and** that the token's **`hd`
  (Google Workspace hosted-domain) claim equals `lemnisca.bio`** (`OF_ALLOWED_DOMAIN`). Requiring `hd`
  is stronger than an email-suffix match — personal/non-Workspace accounts have no `hd` and are rejected
  outright, so no look-alike address can slip through. A `OF_DEV_NO_IAP` env flag bypasses auth for
  local dev. (`backend/iap.py` is a dormant alternative IAP-JWT path, not the deployed one.)
- **RBAC** (`users.py`, `rbac.py`): `of_users` records with roles `admin|runner|viewer` and status
  `pending|active|disabled`. `resolve_on_login` ensures **seed admins** are always admin/active and
  brand-new users land as `pending` (an admin approves them). Routes enforce role.
- **Projects** (`projects.py`): `of_projects` namespacing of cases/runs.

## 3.8 Infrastructure & CI/CD (`infra/`, `.github/workflows/deploy.yml`)

- **`infra/setup-cfd-lemnisca.sh`** (idempotent project bootstrap): enable APIs; create the Artifact
  Registry repo and **build/push the runtime image `linux/amd64`** (arm64 fails Batch's image pull —
  a documented gotcha); create **service accounts** (`of-batch-backend`, `of-batch-job`,
  `of-pubsub-push`, `of-ci-deployer`); create Firestore + the Pub/Sub topic & **push subscription**
  (authenticated push to `/internal/batch-events`); apply **least-privilege IAM** (backend: Batch
  jobsEditor + actAs the job SA + Token Creator on itself + datastore.user + bucket objectAdmin; job SA:
  batch.agentReporter + logWriter + artifactregistry.reader + pubsub.publisher + bucket objectAdmin);
  create the bucket with a **lifecycle** policy (cases → NEARLINE @60 d, results → COLDLINE @180 d);
  set up **Workload Identity Federation** (`of-github-pool` + `github-provider`, locked to the repo) so
  GitHub Actions deploys **keylessly**.
- **CI/CD**: on PRs/`main`, a `test` job runs pytest (core + backend) + runtime bash tests + frontend
  vitest; on `main`, a `deploy` job authenticates via WIF, builds the multi-stage backend image (SPA
  bundled, tagged by commit SHA), and deploys to Cloud Run.

## 3.9 Known limitations of the GCP layer

Honest operational caveats (visible in the code/comments): no `maxRunDuration` on Batch jobs (a job runs
until done or manually stopped); the checkpoint prefix is shared per (case, machine), so concurrent runs
of the same case could collide; multi-case runs fan out all tasks with no concurrency cap; the default
`maxRetryCount 3` reruns *any* solver failure, not just preemption/interruption; the stop handler may
target the `tee` process group rather than the solver's; and runs-polling lists every Batch job
frequently. These are operational hardening items, not correctness bugs in the generated CFD.

---

# How the three parts compose (end-to-end)

1. **Author a spec** (JSON) → **Part 1** builds geometry STLs + `str-params.json`.
2. **Part 2** `build_case` meshes + writes the full OpenFOAM case (physics-dispatched) + `command.sh` +
   `metadata.json`; optionally `generate_sweep` fans out variations; `verify` confirms it runs (locally
   on Docker, or on-server).
3. **Part 3** `of upload` (or the web app) stores the case in GCS, `of run` submits a Cloud Batch job;
   the VM runs `command.sh`, checkpoints to GCS, and publishes results; Firestore tracks state, the web
   app shows progress and serves result downloads.

The seam between every stage is **files in a known layout**, which is what lets the parts evolve
independently — and what lets Part 2's generated case be validated against the hand-built reference
cases before it ever touches the cloud.
