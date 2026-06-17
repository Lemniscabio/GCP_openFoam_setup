# Parts A & B — Complete Walkthrough (every step, every logic, what + how)

**Date:** 2026-06-15. Companion to the design spec
(`specs/2026-06-15-parts-a-b-str-pipeline-design.md`). This documents the **as-built** code so you
can reason about improvements. Read top-to-bottom or jump by section.

---

## 0. The big picture — one data flow

```
 PROMPT (natural language)
   │   str_cad/extract.py        ── Gemini structured output ──►  STRExtraction (wire schema)
   ▼
 STRParams  (str_cad/schema.py)  ── validated geometry parameters (the "what to build")
   │
   │   str_cad/builder.py → export.py → geometry/*.stl  +  str-params.json     [PART A geometry]
   ▼
 6 named STL surfaces  (tankWall, dishedBottom, baffles, shaft, impellers, liquidSurface)
   │                                                  + CaseParams (rpm, viscosity)
   │   str_cad/ofcase/build.py                                                  [PART B case]
   ▼
 Full OpenFOAM v12 case tree:  0/  constant/  system/  command.sh  metadata.json
   │
   │   core/generate.py:commit_case → GCS  cases/<project>/case_xxxx/case/      [INTEGRATION]
   ▼
 Part C (Cloud Batch) runs command.sh:
   blockMesh → snappyHexMesh → topoSet → decomposePar → foamRun → reconstructPar → results to GCS
```

**The two load-bearing contracts (the spine of the whole system):**

1. **A→B contract = STL region names.** Part A emits exactly 6 STL files whose *filenames are the
   patch names*. snappyHexMesh turns each STL into a mesh patch of that name. Part B writes one
   boundary condition per patch, keyed by those same names. Change a name in one place and you must
   change it in all three — so the list `REGION_NAMES` is the single source of truth, imported
   everywhere.
2. **B→C contract = the case tree + `command.sh` + `metadata.json`.** Part C's runtime knows nothing
   about stirred tanks; it just downloads the case dir, runs `command.sh` (which must be resume-aware
   and read `MPI_RANKS`), and uploads results. `metadata.json` is required and opaque.

**The one unifying design rule:** the LLM only ever does *natural-language → structured parameters*.
Every geometry vertex and every dictionary keyword is produced by **deterministic, hand-written,
tested code**. The LLM never writes geometry or OpenFOAM syntax.

---

## 1. Coordinate convention (used by all of Part A)

- Axis of rotation = **Z**, vessel centerline on Z.
- **z = 0** is the tangent line where the cylinder meets the dished bottom.
- Cylinder occupies **z ∈ [0, liquid_height]**; the dished head is **z < 0** (down to −tank_radius).
- All lengths in **meters** (snappy/blockMesh use `convertToMeters 1`).

Everything downstream (rotor cylinders, locationInMesh, refinement region) is computed in this frame.

---

## 2. PART A — `str_cad/schema.py` (the parameter contract)

Pydantic v2 models. `STRParams` has nested `Tank`, `Liquid`, `Baffles`, `Shaft`, `Impellers`.

**Computed field** `impeller_diameter_m = tank.diameter_m × impellers.diameter_ratio` — the impeller
diameter D is *derived*, not entered (ratio is the standard 1/3).

**Blade-dimension defaulting** (`@model_validator(mode="after") _fill_blade_dimensions`): if
`blade_length_m`/`blade_height_m` are omitted they default to **D/4** and **D/5** (standard Rushton
proportions). Runs *after* base parsing, *before* cross-field checks.

**The `SchemaError` propagation trick** (important): pydantic v2 wraps any `ValueError` raised inside
a validator into a `ValidationError`. We want a *clean* `SchemaError` to surface. So `model_validate`
is **overridden as a classmethod**: it calls `super().model_validate(...)` (normal parsing +
defaulting), then calls `_check_cross_fields()` which raises `SchemaError` **outside** any validator,
so it propagates uncaught. This is mirrored in `CaseParams`.

**Cross-field validators** (`_check_cross_fields`, each raises `SchemaError`):
- liquid height ≤ tank height,
- impeller stack fits under liquid: `lowest_clearance + (count-1)·inter_clearance < liquid_height`,
- blade length within ±10% of D/4, blade height within ±10% of D/5 (catches a self-inconsistent
  prompt, e.g. Gemini hallucinating a wrong blade size).

**Why this matters:** this schema is the *gate*. A physically impossible reactor is rejected here,
before any geometry is built. Improvement ideas live here (more ratios, more impeller types, ranges).

---

## 3. PART A geometry builders

### 3.1 `geometry/vessel.py` — `build_vessel_shell(p)`
The **liquid region as one solid**:
- `cylinder` = a circle of radius R extruded up by `liquid_height` (z ∈ [0, H]).
- `head` = a dished bottom built by drawing a quarter-circle profile in the XZ plane
  (`moveTo(0,0) → lineTo(R,0) → threePointArc(midpoint (R/√2, −R/√2), end (0,−R)) → close`) and
  **`revolve(360°)` about Z** → a hemisphere of radius R sitting below z=0.
- returns `cylinder.union(head)` — one watertight solid.

**HOW (cadquery):** `Workplane` is a fluent CAD builder over the OpenCASCADE kernel; `.circle().extrude()`
makes a prism, `.revolve()` spins a 2-D profile into a solid of revolution, `.union()` is a boolean
fuse. *Note:* the "dished" bottom is currently a true hemisphere, not an ASME torispherical/2:1
elliptical head — an approximation flagged for improvement.

### 3.2 `geometry/baffles.py` — `build_baffles(p)`
Returns a **list of `count` rectangular plates**. Each plate: `box(width_m, 0.02, height_m)`
(thickness hardcoded 0.02 m), translated to `center_radius = R − width/2` (outer edge near the wall),
lifted so its base is at z=0, then **`.rotate()` about Z by `360°·i/count`** → evenly spaced,
symmetric. Wall-mounted, vertical, full-band flat baffles only.

### 3.3 `geometry/internals.py` — shaft + Rushton turbines
- `impeller_z_positions(p)` = `[lowest_clearance + i·inter_clearance for i in range(count)]` — the
  axial heights of the impellers. **Used in 3 places** (geometry, MRF rotor zones, mesh refinement
  region) — a key shared quantity.
- `build_shaft(p)` = a thin vertical cylinder, radius `max(0.03, D/20)`, from z=0 up to `liquid_height`.
- `build_impellers(p)` = one fused **Rushton disc turbine per z**: a central **disc** (radius
  0.66·D/2, thickness 0.01), a **hub** cylinder, and **`blades` flat blades** (`box(blade_length,
  0.01, blade_height)`) placed at `blade_center_radius = D/2 − blade_length/2` and arrayed by
  `.rotate()` at `360°·i/blades`. All fused into one solid. *(Standard Rushton disc is 0.75·D; we use
  0.66·D — minor approximation.)*

### 3.4 `geometry/assembly.py` — the fluid domain + the 6-region split (the clever part)
- `REGION_NAMES` = the 6 patch names. **Single source of truth**, imported by export, meshcase,
  fields, caseparams.
- `build_fluid_solid(p)` = `vessel_shell` **minus** (shaft ∪ all impellers ∪ all baffles) via boolean
  `.cut()`. This is the actual water volume: the vessel interior with the internals carved out.
- `build_fluid_domain(p)` = **classify every boundary face of that solid into exactly one of the 6
  named regions**, then group each region's faces into a `cq.Compound`. This is what makes snappy able
  to name patches. Classification is **first-match-wins** on each face's center `c`, radial distance
  `r = √(cx²+cy²)`, and `face.geomType()`:
  1. planar face with |normal_z|>0.9 and `c.z ≥ H − tol` → **liquidSurface** (the flat top lid)
  2. `c.z < −tol` → **dishedBottom** (anything below the tangent line)
  3. `r ≤ impeller_radius` AND `c.z` within `blade_height/2` of some impeller height → **impellers**
  4. `geomType == CYLINDER` AND `r ≤ 2·shaft_radius` → **shaft**
  5. `geomType == CYLINDER` AND `r ≥ D` → **tankWall**
  6. else → **baffles**

  **Why by face *type* not just radius:** the original version used radius alone and mislabeled the
  flat baffle side-faces as `tankWall` (their centroids sit at nearly the same radius as a tank-wall
  arc centroid). Classifying the wall as `CYLINDER` and baffles as the leftover `PLANE` faces fixed
  it. `tol = 1e-3 × max(H, 2R, 1)` scales the tolerance to the model size.

  **Invariant that guarantees a watertight mesh:** every face is assigned to exactly one region, so
  the union of the 6 region-surfaces == the full closed boundary of the fluid solid.

### 3.5 `export.py` — STL out + watertight guarantee
- `_export_region(shape, path)`: `shape.exportStl(tolerance=1e-4, angularTolerance=0.1)` (fine
  tessellation so adjacent regions share vertices and the combined surface stays closed), then
  **trimesh post-process**: drop degenerate faces, remove unreferenced vertices, re-export.
- `export_geometry(p, out_dir)`: writes `geometry/<region>.stl` for all 6 + `str-params.json` (the
  validated schema dump, which later seeds `metadata.json`). Returns `out_dir`.
- **Watertightness is verified in tests**: load all 6 STLs, concatenate, `merge_vertices`, assert
  `is_watertight` — because a leak makes snappy fail or produce garbage.

### 3.6 `builder.py` — `build_from_schema_file(path, out_dir)`
Thin orchestrator: load JSON → `STRParams.model_validate` → `export_geometry`. Plus a
`python -m str_cad.builder <schema.json> <out_dir>` CLI. The 2.6 MB `dishedBottom.stl` comes from the
fine tessellation (improvement target: coarsen).

---

## 4. PART A — `meshcase.py` (turns STLs into a runnable mesh case)

`make_mesh_case(geometry_dir, case_dir)` builds the *mesh-generation* half of the case (Part B later
overwrites the physics dicts). Steps:

1. **Copy** the 6 STLs into `constant/triSurface/`.
2. **`_combined_bounds`** — load all 6 STLs with trimesh, take the min/max corner, pad by **10%** each
   side → the background block that encloses the geometry.
3. **`_cell_counts`** — `n_axis = max(1, round(span_axis / 0.12))` → background cells ≈ **0.12 m**.
   For the golden reactor this is ~ (21, 21, 76). *(This base size + the rotor refinement is what
   makes the MRF zone resolvable — see §9.)*
4. **`blockMeshDict`** — a single 8-vertex hex block over the padded bbox with those cell counts, one
   `allBoundary` patch (snappy creates the real patches).
5. **`snappyHexMeshDict`** — the heart:
   - `geometry{}`: each region as v12 syntax `name { type triSurfaceMesh; file "name.stl"; }` **plus**
     a `rotorColumn` `searchableCylinder` spanning `[min(impeller_z)−blade_h, max+blade_h]`, radius
     `0.65·D` (the refinement region around the impeller column).
   - `refinementSurfaces`: `shaft/impellers/baffles → level (2 3)` (thin features need fine cells),
     others `(1 1)`.
   - `refinementRegions`: `rotorColumn { mode inside; levels ((1e15 2)); }` → level-2 everywhere
     inside that cylinder, so the MRF zone has enough cells.
   - `locationInMesh`: a point **inside the liquid, off-axis** — `(0.4R·cos45°, 0.4R·sin45°, 0.5H)` —
     placed between baffles and clear of the shaft so snappy keeps the correct (fluid) region.
   - `castellatedMesh true; snap true; addLayers false` (no boundary layers in the PoC).
6. **`meshQualityDict`** — inline standard OpenFOAM quality limits (NOT `#includeEtc`, which failed in
   the runtime image — a fixed gotcha).
7. **`controlDict`/`fvSchemes`/`fvSolution`** — minimal valid stubs here; **Part B overwrites** the
   real ones.

---

## 5. PART A LLM — `extract.py` (the only "agentic" piece)

- Defines a **wire schema** `STRExtraction` (same fields as `STRParams` but **no validators, no
  computed fields** — it's just the JSON shape Gemini fills).
- `extract_str_params(prompt, api_key, model="gemini-2.5-flash")`: calls
  `genai.Client(...).models.generate_content(contents=prompt, config={system_instruction=SYSTEM,
  response_mime_type="application/json", response_schema=STRExtraction})` → Gemini returns JSON matching
  the schema → `json.loads(resp.text)` → **`STRParams.model_validate(data)`** runs the real validators
  (Rushton ratios, fit checks).
- `SYSTEM` instruction pins: lengths in meters; `family="stirred_tank_reactor"`; `type="rushton"`;
  default diameter_ratio 1/3; leave blade dims null if unstated (downstream fills D/4, D/5).
- **Two-layer design:** Gemini does fuzzy→structured; our schema does structured→validated. A bad
  extraction is caught by the same `SchemaError` gate as a bad manual input.

---

## 6. PART B — the case generator (`str_cad/ofcase/`)

### 6.1 `caseparams.py`
- `CaseParams`: `rpm`, `viscosity_m2_s` (default 1e-6), `run{end_time=5000, write_interval=500,
  cores=28}`, `patch_roles` (default: every region `wall` except `liquidSurface` `slip`).
- computed `omega_rad_s = rpm·2π/60` (kept for reference; the dict actually uses `[rpm]` units).
- same `model_validate`-override + `CaseParamsError` pattern: rpm ≥ 0; patch roles ∈
  {wall, slip, inlet, outlet} (inlet/outlet reserved for the future multiphase sparger).

### 6.2 `mrf.py` — the rotating-frame setup
- `rotor_cylinders(sp)`: one cylinder per impeller, height `1.5·blade_height`, **radius `0.55·D`**
  (a bit larger than the blade tip so the zone fully encloses the impeller), centered at each impeller z.
- `write_toposet_dict(sp, path)`: a `system/topoSetDict` whose `actions(...)` list runs
  `cylinderToCell` for each impeller — first action `new`, rest `add` — accumulating into one
  `cellSet rotor`, then a final `setToCellZone` converts it to **cellZone `rotor`**. So all 4
  impellers live in **one merged MRF zone** (reference design uses 4 separate zones — a fidelity
  difference, see §10).
- `write_mrf_properties(sp, cp, path)`: `constant/MRFProperties` with
  `MRF { cellZone rotor; origin (0 0 0); axis (0 0 1); omega <rpm> [rpm]; }`. **This is the v12 way**
  (MRF is *not* an fvModel in v12).

### 6.3 `physics.py`
- `physicalProperties`: `viscosityModel constant; nu [0 2 -1 0 0 0 0] <viscosity>;` (kinematic ν).
- `momentumTransport`: `simulationType RAS; RAS { model kEpsilon; turbulence on; printCoeffs on; }`.

### 6.4 `fields.py` — the `0/` initial+boundary conditions (the contract enforcement point)
- `_FIELD_DEFINITIONS`: the 5 solved fields with their `class`, `dimensions`, `internalField` seed —
  `U (0 0 0)`, `p 0`, `k 1`, `epsilon 20`, `nut 0`.
- `_boundary_condition(field, role, rotating)` — the **BC matrix**:
  - role `slip` (liquidSurface): `U slip`, `p/k/epsilon zeroGradient`, `nut calculated`.
  - role `wall`: `U` → **`MRFnoSlip` if rotating else `noSlip`**; `p zeroGradient`;
    `k kqRWallFunction`; `epsilon epsilonWallFunction`; `nut nutkWallFunction`.
- `write_initial_fields(cp, region_names, out_dir, rotating_patches=("impellers",))`: writes one field
  file per `_FIELD_DEFINITIONS`, each with a `boundaryField` containing **one entry per region** — so
  the patch set in every `0/` field == `REGION_NAMES` (the #1 OpenFOAM silent-failure guard).
  - **`rotating_patches=("impellers",)`**: only the impellers spin (`MRFnoSlip`). The **shaft is
    `noSlip`** (stationary) — a deliberate simplification; the proven reference spins the shaft with
    `rotatingWallVelocity` (fidelity gap, §10).

### 6.5 `systemdicts.py` — the solver dicts
- `controlDict`: **`application foamRun; solver incompressibleFluid;`** (v12 modular), `endTime`,
  `deltaT 1` (steady iterations), `writeInterval`.
- `fvSchemes`: `ddt steadyState`, `grad Gauss linear`, **bounded** divergence schemes for U/k/epsilon
  (`bounded Gauss limitedLinear[V]`) for robustness, `laplacian Gauss linear corrected`.
- `fvSolution`: `p` → **GAMG** (multigrid, good for pressure), `U/k/epsilon` → smoothSolver;
  `SIMPLE { nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 0; }` — **pRefCell/pRefValue are
  essential**: a closed domain has no fixed-pressure boundary, so pressure is pinned at one cell;
  relaxation factors p 0.3, U/k/epsilon 0.5 (steady-state under-relaxation).
- `decomposeParDict`: `numberOfSubdomains <cores>; method scotch;` — **overwritten at runtime** by
  command.sh (see 6.6).

### 6.6 `command.py` — the run script + metadata
- `write_command_sh`: a **resume-aware, rank-aware** bash script:
  - `: "${MPI_RANKS:?...}"` — requires the rank count the runtime injects (matches the machine).
  - `if [[ "${OF_RESUME:-0}" != "1" ]]; then` gate around preprocessing: `blockMesh`,
    `snappyHexMesh -overwrite`, `topoSet`, **`foamDictionary system/decomposeParDict -entry
    numberOfSubdomains -set "${MPI_RANKS}"`** (so decomposition matches the machine), `decomposePar
    -force`. On a resume, all of that is skipped (mesh restored from checkpoint).
  - always: `mpirun --oversubscribe -np "${MPI_RANKS}" foamRun -parallel` then `reconstructPar`.
  - **`--oversubscribe` + dynamic MPI_RANKS** is the fix for the "not enough slots" failure caused by
    the earlier hardcoded core count.
- `write_metadata_json`: required by Part C — embeds `rpm`, `viscosity_m2_s`, the full `str` params,
  and the `case` params. Opaque to C.

### 6.7 `build.py` — `build_case(case_params, geo_dir, out_dir)` (orchestration)
Order matters:
1. load `str-params.json` → `STRParams`.
2. `make_mesh_case(geo_dir, out_dir)` — lays down the mesh scaffold (triSurface + blockMesh + snappy +
   meshQuality + stub control/schemes/solution).
3. **Overwrite** `system/{controlDict, fvSchemes, fvSolution}` with the real solver dicts; write
   `system/topoSetDict`, `system/decomposeParDict`.
4. Write `constant/{physicalProperties, momentumTransport, MRFProperties}`.
5. Write `0/` fields, `command.sh`, `metadata.json`.
Result: a complete, runnable v12 MRF case.

---

## 7. INTEGRATION layer (Parts A+B → the Part C web app)

### 7.1 `core/generate.py`
- `build_case_local(prompt|params, case_params, gemini_key, out_dir)`: resolves `STRParams` (from
  prompt via Gemini, or from params), resolves `CaseParams` (defaults rpm=90), writes
  `geo/str-params.json`, runs `build_from_schema_file` (geometry) then `build_case` (the case). Returns
  `{str_params, case_params, case_dir, geometry_dir}`.
- `read_region_stls(geometry_dir)` → `{region: bytes}` for the preview.
- `commit_case(case_dir, project, uploaded_by, storage, case_repo, case_record_repo)`: **mirrors the
  existing upload `finalize`** so a generated case is indistinguishable from an uploaded one —
  allocates a global `case_id`, uploads the whole tree to `cases/<project>/<case_id>/case/`, writes
  `manifest.json` + `READY`, runs `validate_case`, and registers the `of_cases` record. Returns the id.

### 7.2 `backend/routes_generate.py`
- `POST /api/generate/preview` (require_runner): exactly one of `prompt`/`params`; builds in a temp
  dir; returns `str_params`, `case_params`, and the 6 STLs **base64-encoded**. Schema/CaseParams/Gemini
  errors → HTTP 400. No GCS write.
- `POST /api/generate/create` (require_runner): builds from the (already-resolved) `params` — **no
  second Gemini call** — `projects.ensure(...)`, then `commit_case(...)` → `{case_id}`.

### 7.3 Frontend (`StlViewer.tsx`, `GenerateView.tsx`)
- `StlViewer`: three.js — decode each base64 STL, parse with `STLLoader`, group all meshes, **recenter
  the group to origin**, fit the camera to the **bounding sphere** with the real aspect; **outer
  shell (tankWall/dishedBottom/liquidSurface) rendered transparent with white edge outlines**, internals
  opaque → you see inside; OrbitControls; fullscreen toggle.
- `GenerateView`: prompt textarea → `generatePreview` → shows the 3-D model + editable resolved params
  + a case-config panel; project picker → `generateCreate` → jumps to Cases. New first nav tab.
- From Cases onward it's the **existing** Part C flow (Submit → Batch → Status → Results), untouched.

---

## 8. The CFD/physics logic (the WHY behind the dicts)

- **MRF (Multiple Reference Frame), a.k.a. "frozen rotor":** instead of physically rotating the
  impeller mesh in time, the cells inside the `rotor` cellZone are solved in a **rotating reference
  frame** — the momentum equation there gains Coriolis + centrifugal source terms, and the impeller
  walls (`MRFnoSlip`) are treated as moving with that frame. It's **steady-state** and cheap, gives a
  good *time-averaged* flow field, but cannot capture the transient impeller–baffle interaction. The
  zone must (a) enclose the impeller and (b) be well resolved — hence the rotor refinement region.
- **Why a cellZone, not geometry:** MRF acts on a *volume* of cells, defined at runtime by `topoSet`
  `cylinderToCell` from the impeller positions+radius. So Part A never needs to emit a rotor solid.
- **kEpsilon + wall functions:** a RANS turbulence model; `k` (turbulent kinetic energy) and `epsilon`
  (dissipation) get the wall-function BCs at walls (`kqRWallFunction`/`epsilonWallFunction`/
  `nutkWallFunction`), valid for **y⁺ ≈ 30–300**. We don't control y⁺ (no boundary layers), so wall
  quantities are not quantitatively trustworthy yet.
- **Closed-domain pressure reference:** no inlet/outlet → pressure is only defined up to a constant →
  `pRefCell/pRefValue` pin it, else the solver is singular.
- **slip lid:** `liquidSurface` as `slip` (or `symmetry` in the reference) approximates a **flat,
  non-deforming free surface** — valid for a baffled tank where the vortex is suppressed.

---

## 9. Why the mesh sizing is the way it is (a hard-won lesson)

The first runs failed with **"Continuity error cannot be removed by adjusting the outflow"** because
the rotor cellZone had only ~200 cells (base mesh too coarse, ~0.3 m). MRF on a closed domain needs the
rotor zone well-resolved or the imposed frame velocity injects an unbalanceable flux. Fix:
- base cell ≈ **0.12 m** (→ (21,21,76) for the golden tank), and
- a **`rotorColumn` level-2 refinement region** spanning the impeller column,
→ rotor zone ≈ **60 000 cells**, and `foamRun` then advances cleanly. This is encoded in `meshcase.py`.

---

## 10. Known simplifications & gaps (improvement backlog)

**Geometry (A):**
- Hemispherical bottom (not torispherical/2:1 elliptical).
- Rushton disc 0.66·D (standard 0.75·D); single shaft, central only; all impellers identical.
- Baffles flat/vertical/full-band only; `dishedBottom.stl` is 2.6 MB (over-tessellated).
- Only the STR family; no CAD import.

**Physics (B) — fidelity vs the proven reference (`~/Desktop/singlephase_3/foam_runs/0`):**
- **Shaft is `noSlip` (stationary); reference uses `rotatingWallVelocity` (spinning).** ← biggest gap.
- **One merged MRF zone; reference uses 4 per-impeller zones** (and per-impeller `MRFZoneName` +
  per-impeller patches → per-impeller torque).
- liquidSurface `slip` vs reference `symmetry` (near-equivalent).
- No `constant/g`; reference includes gravity.
- Reference renames the blockMesh top face to the liquid level via `createPatchDict` (no
  liquidSurface STL); we carve liquidSurface from an STL.

**Method / trust:**
- No mesh-independence study, no y⁺ control/report, not converged-to-tolerance.
- No post-processing (power number, torque, pumping number) — the obvious **Np ≈ 5** sanity check for
  a standard Rushton is not yet computed.
- No error-recovery loop if snappy/foamRun fails on an unusual parameter set.
- Single-phase only; **no aeration (multiphase), no heat, no non-Newtonian, no scalar/mixing-time**.

**Ops:**
- Local backend must set `OF_IMAGE_URI` to the current runtime tag (config default is the stale
  pre-projects `12.0.1`).
- Part C runtime retries on the same VM fail at the SSD-mount step ("already mounted") — wasted
  retries; pre-existing, worth fixing.

---

## 11. Failure/fix history (every real bug we hit end-to-end)

1. **`#includeEtc meshQualityDict`** failed in the runtime image → inlined the defaults.
2. **v12 snappy geometry syntax** — old `name { ... }` → must be `name { type triSurfaceMesh; file
   "x.stl"; }`.
3. **baffles patch missing** — radius-based face classification mislabeled baffle sides as tankWall →
   classify by `geomType()` (CYLINDER=wall, PLANE=baffles).
4. **MRF continuity error** — coarse mesh → finer base (0.12 m) + rotor refinement region.
5. **case path 404 in Batch** — local backend used stale `openfoam:12.0.1` (pre-projects, no project
   segment in the download path) → set `OF_IMAGE_URI=…:12.0.5`.
6. **"not enough slots" at foamRun** — `command.sh` hardcoded 28 cores → read `${MPI_RANKS}` +
   `--oversubscribe`, set `decomposeParDict` dynamically. (Only fixed for *newly generated* cases.)
