# Part B — OpenFOAM Case Generator Implementation Plan

> **For agentic workers:** Executed by driving **`codex exec` task-by-task** (Claude pre-provisions
> env + orchestrates/reviews; codex writes code). Each task ends green before the next. The proven
> codex loop: Claude pre-installs deps, hands codex ONE tiny task (write files + run pytest +
> commit), foreground, logged (no `tail` pipe).

**Goal:** Turn `(STR geometry from Part A) + (case params: RPM, viscosity)` into a complete, runnable
**OpenFOAM v12 single-phase MRF** case (the `0/ constant/ system/ command.sh metadata.json` tree)
that conforms to the Part C filesystem and actually runs (`foamRun` advances).

**Architecture:** Deterministic templating — **no LLM in the generation path** (inputs are numbers).
Reuses Part A's `STRParams`, `impeller_z_positions`, `REGION_NAMES`, and `meshcase.py` (mesh
scaffolding). Adds the physics layer: MRF rotor cell-zone via `topoSet cylinderToCell`, `0/` fields
per patch, `constant/` properties, real `system/` solver dicts, resume-aware `command.sh`.

**Tech Stack:** Python 3.11, pydantic v2, foamlib (dict read/round-trip + parse for the consistency
check), pytest. OpenFOAM v12 image `kartikeyattri/openfoam:12` for the smoke test (Claude runs it).

**Spec:** `docs/superpowers/specs/2026-06-15-parts-a-b-str-pipeline-design.md` (D8, D11, D14).

> **v12 CORRECTIONS (from the `incompressibleFluid/mixerVessel2DMRF` tutorial in the image — our exact
> case type; mirror it):** MRF is defined in **`constant/MRFProperties`** (NOT an fvModel — D8 was
> wrong). Turbulence model = **`kEpsilon`** (fields `k`, `epsilon`, `nut`; NOT kOmegaSST/omega) to
> match the proven tutorial. `omega` is written with **`[rpm]` units directly** (`omega 90 [rpm];`),
> no rad/s conversion needed in the dict. Rotor (rotating) walls use **`MRFnoSlip`** in `0/U`;
> stationary walls `noSlip`; `liquidSurface` `slip`. `nu` is dimensioned: `nu [0 2 -1 0 0 0 0] <val>;`.
> Tasks below are adjusted accordingly (B2 MRFProperties, B3 kEpsilon, B4 fields = U/p/k/epsilon/nut).

**Colocation decision:** Part B lives as a subpackage **`str_cad/ofcase/`** in the existing
`part-a-cad/` package + venv (shares `STRParams`/`meshcase`; avoids cross-package plumbing and the
codex-hang risk of multi-venv setup). It's a pragmatic colocation — can be split into its own
package during app integration. Add `foamlib` to the venv.

**Out of scope (later plans):** Part A LLM extraction (#2); app/Part-C integration (#4); two-phase
aeration (deferred). Convergence *quality* tuning beyond "it runs + a few stable iterations".

---

## File structure (all under `part-a-cad/str_cad/ofcase/`)

```
ofcase/
  __init__.py
  caseparams.py    # CaseParams pydantic model (rpm, viscosity, run{}, patch_roles) + validators
  mrf.py           # rotor cylinders from STRParams -> system/topoSetDict + constant/fvModels (MRF)
  physics.py       # constant/physicalProperties (nu) + constant/momentumTransport (kOmegaSST)
  fields.py        # 0/{U,p,k,omega,nut} with one boundaryField entry per REGION patch
  systemdicts.py   # real system/{controlDict,fvSchemes,fvSolution,decomposeParDict}
  command.py       # command.sh (resume-aware OF_RESUME gate) + metadata.json
  build.py         # build_case(str_params, case_params, geo_dir, out_dir) -> full case tree
tests/
  test_caseparams.py test_mrf.py test_physics.py test_fields.py
  test_systemdicts.py test_command.py test_build_case.py
```

## Pre-provision (Claude, before codex): `uv pip install --python part-a-cad/.venv/bin/python foamlib`

---

### Task B1: CaseParams schema

**Files:** Create `ofcase/__init__.py`, `ofcase/caseparams.py`; Test `tests/test_caseparams.py`

- Build `CaseParams` (pydantic v2): `rpm: float`, `viscosity_m2_s: float` (kinematic ν, default
  1e-6), `run: Run{end_time:int=5000, write_interval:int=500, cores:int=28}`,
  `patch_roles: dict[str,str]` defaulting to `{tankWall:wall, dishedBottom:wall, baffles:wall,
  shaft:wall, impellers:wall, liquidSurface:slip}`. A `CaseParamsError(ValueError)`.
  `omega_rad_s` computed property = `rpm * 2*pi/60`.
- **Key test asserts:** valid parse; `omega_rad_s` for rpm=90 ≈ 9.4248; `rpm<0` → error;
  unknown patch role value (not in {wall,slip,inlet,outlet}) → error; default patch_roles has all 6
  REGION_NAMES.
- Run from part-a-cad: `cd part-a-cad && .venv/bin/python -m pytest tests/test_caseparams.py -v`
- Commit: `feat(part-b): CaseParams schema`

### Task B2: MRF rotor zone (topoSet + fvModels)

**Files:** Create `ofcase/mrf.py`; Test `tests/test_mrf.py`

- `rotor_cylinders(sp: STRParams) -> list[dict]`: one cylinder per impeller from
  `impeller_z_positions(sp)` — each `{p1:(0,0,z-h/2), p2:(0,0,z+h/2), radius: 0.55*D}` where
  `h = blade_height_m * 1.5` (a touch taller than blades) and `D = impeller_diameter_m` (radius a
  bit larger than the blade tip so the zone encloses the impeller). One shaft → **all impellers in
  ONE cellZone `rotor`**.
- `write_toposet_dict(sp, path)`: a v12 `system/topoSetDict` with N `cylinderToCell` actions all
  `new`/`add` into cellSet `rotor`, then a `cellSet`→`cellZoneSet` action making zone `rotor`.
- `write_fvmodels(sp, cp, path)`: `constant/fvModels` with one `MRF` fvModel —
  `type MRF; cellZone rotor; origin (0 0 0); axis (0 0 1); omega <cp.omega_rad_s>;`
- **Key test asserts:** `rotor_cylinders` length == impeller count; radius > D/2; topoSetDict text
  contains `cylinderToCell` ×count and `rotor`; fvModels text contains `MRF`, `cellZone rotor`, and
  the numeric omega for rpm=90.
- Commit: `feat(part-b): MRF rotor cellZone (topoSet) + fvModels`

### Task B3: constant/ physics dicts

**Files:** Create `ofcase/physics.py`; Test `tests/test_physics.py`

- `write_physical_properties(cp, path)`: `constant/physicalProperties` —
  `viscosityModel constant; nu <cp.viscosity_m2_s>;` (v12 incompressible form).
- `write_momentum_transport(path)`: `constant/momentumTransport` —
  `simulationType RAS; RAS { model kOmegaSST; turbulence on; printCoeffs on; }`.
- **Key test asserts:** physicalProperties text has `nu` and the value; momentumTransport has
  `kOmegaSST` and `RAS`.
- Commit: `feat(part-b): constant physical + momentumTransport`

### Task B4: 0/ fields per patch

**Files:** Create `ofcase/fields.py`; Test `tests/test_fields.py`

- `write_initial_fields(cp, region_names, path)`: write `0/U`, `0/p`, `0/k`, `0/omega`, `0/nut`.
  Each field has internalField + a `boundaryField` with **one entry per region patch**, by role:
  - wall patches: `U` → `noSlip`; `p` → `zeroGradient`; `k` → `kqRWallFunction`; `omega` →
    `omegaWallFunction`; `nut` → `nutkWallFunction` (all with sensible value seeds).
  - slip patches (liquidSurface): `slip` for every field.
  - internalField seeds: `U (0 0 0)`; `p 0`; `k`, `omega`, `nut` small positive constants
    (e.g. k 0.01, omega 10, nut 0) — PoC seeds.
- **Key test asserts (the load-bearing one):** for each of the 5 field files, the set of patch names
  in its `boundaryField` **equals `set(REGION_NAMES)`** (no missing/extra patch — the #1 silent OF
  failure). liquidSurface entry is `slip` in U; wall patches use the wall functions.
- Commit: `feat(part-b): 0/ fields with per-patch boundary conditions`

### Task B5: system/ solver dicts

**Files:** Create `ofcase/systemdicts.py`; Test `tests/test_systemdicts.py`

- `write_control_dict(cp, path)`: `system/controlDict` — `application foamRun; solver
  incompressibleFluid; startFrom startTime; startTime 0; stopAt endTime; endTime <cp.run.end_time>;
  deltaT 1; writeControl timeStep; writeInterval <cp.run.write_interval>; ...` (steady-style: deltaT
  1 iteration).
- `write_fv_schemes(path)`: `system/fvSchemes` — steady incompressible defaults
  (`ddtSchemes { default steadyState; }`, bounded upwind divSchemes for U/k/omega, linear laplacian,
  etc.).
- `write_fv_solution(path)`: `system/fvSolution` — solvers for p (GAMG), U/k/omega (smoothSolver),
  `SIMPLE { nNonOrthogonalCorrectors 1; pRefCell 0; pRefValue 0; residualControl {...} }` and
  `relaxationFactors`. **pRefCell/pRefValue are required (closed domain, no fixed-pressure patch).**
- `write_decompose_par(cp, path)`: `system/decomposeParDict` — `numberOfSubdomains <cp.run.cores>;
  method hierarchical;` (or scotch).
- **Key test asserts:** controlDict has `foamRun` + `incompressibleFluid` + the endTime; fvSolution
  has `pRefCell` + `pRefValue` + `SIMPLE`; decomposeParDict numberOfSubdomains == cores.
- Commit: `feat(part-b): system solver dicts (controlDict/fvSchemes/fvSolution/decomposePar)`

### Task B6: command.sh + metadata.json

**Files:** Create `ofcase/command.py`; Test `tests/test_command.py`

- `write_command_sh(cp, path)`: generate `command.sh` matching Part C's runtime contract —
  **resume-aware**: preprocessing gated behind `if [[ "${OF_RESUME:-0}" != "1" ]]; then ... fi`
  (runs `blockMesh`, `snappyHexMesh -overwrite`, `topoSet`, `decomposePar`); ALWAYS runs the solver
  (`mpirun -np <cores> foamRun -parallel` or serial `foamRun` if cores==1) and
  `reconstructPar` (all times). `set -e`. Make it executable (0o755).
- `write_metadata_json(sp, cp, path)`: `metadata.json` (required by Part C) — embed the STR params +
  case params (rpm, viscosity), valid JSON.
- **Key test asserts:** command.sh contains the `OF_RESUME` gate, `foamRun`, `reconstructPar`, and is
  executable; metadata.json parses and has `rpm` + `viscosity_m2_s`.
- Commit: `feat(part-b): resume-aware command.sh + metadata.json`

### Task B7: build_case orchestrator + mesh refinement bump

**Files:** Create `ofcase/build.py`; modify `str_cad/meshcase.py` (refinement); Test `tests/test_build_case.py`

- `build_case(str_params, case_params, geo_dir, out_dir)`: call `meshcase.make_mesh_case(geo_dir,
  out_dir)` for the mesh scaffold, then OVERWRITE the stub `system/{controlDict,fvSchemes,fvSolution}`
  with the real ones (B5), and write `system/topoSetDict`, `system/decomposeParDict`,
  `constant/{physicalProperties,momentumTransport,fvModels}`, `0/*` (B2–B4), `command.sh`,
  `metadata.json` (B6). Return out_dir.
- **Mesh refinement bump (the deferred tuning):** in `meshcase.py`, raise `refinementSurfaces` levels
  for the thin features — `baffles` and `shaft` → `level (3 4)` (was 1/2) and `impellers` →
  `(2 3)`; add `features`/`explicitFeatureSnap` so thin plates are captured. Keep tankWall/
  dishedBottom/liquidSurface modest. (Update test_mesh_case expectations accordingly.)
- **Key test asserts:** build_case produces every file (`0/U`,...,`constant/fvModels`,
  `system/topoSetDict`, `command.sh`, `metadata.json`, `constant/triSurface/*.stl`); the patch set in
  `0/U` boundaryField == REGION_NAMES; metadata.json valid.
- Commit: `feat(part-b): build_case orchestrator + thin-feature mesh refinement`

### Task B8: real OpenFOAM smoke test (Claude runs — acceptance gate)

- Claude (not codex) regenerates the golden case via `build_case` and runs in Docker
  (`kartikeyattri/openfoam:12`, `--platform linux/amd64`):
  `blockMesh → snappyHexMesh -overwrite → topoSet → checkMesh → foamRun` for a SMALL endTime
  (override to ~20 iterations) on **1 core** (serial, to keep the smoke fast).
- **Acceptance:** `topoSet` creates cellZone `rotor` with >0 cells; `checkMesh` = Mesh OK with 6
  patches; `foamRun` starts, reads MRF, and advances ≥10 iterations with **finite, decreasing-ish
  residuals** (no FOAM FATAL ERROR, no divergence to NaN). Record the verdict; fix any v12-syntax or
  BC issues by driving codex.

---

## Self-review (done)

- **Spec coverage:** D8 (incompressibleFluid + kOmegaSST + MRF fvModel + pRefCell) → B3/B4/B5/B2;
  D11 (RPM→omega, viscosity→nu; v12 modular form) → B1/B2/B3/B5; D5/contract (per-patch BCs from
  region names) → B4; Part C contract (command.sh resume gate + metadata.json) → B6. The baffles
  under-resolution follow-up → B7 refinement bump.
- **Placeholders:** none — each task names concrete files, functions, and key assertions; OF dict
  bodies are codex's to write against the stated v12 requirements + the smoke gate (B8).
- **Type consistency:** `CaseParams`, `omega_rad_s`, `rotor_cylinders`, `build_case`,
  `REGION_NAMES`, `impeller_z_positions` used consistently; reuses Part A names.
