# Part A — CadQuery STR Geometry Builder Implementation Plan

> **For agentic workers:** This plan is executed by driving **`codex exec` task-by-task** (this
> project's rule: all code-writing goes to codex; Claude orchestrates + reviews between tasks).
> Steps use checkbox (`- [ ]`) syntax for tracking. Each task ends green (tests pass) before the
> next starts.

**Goal:** A deterministic, parametric CadQuery builder that turns a validated stirred-tank-reactor
(STR) schema into the locked Part A output contract — 6 named per-region STL files +
`str-params.json` — that passes `snappyHexMesh` + `checkMesh` cleanly.

**Architecture:** Pure-Python CadQuery (OCCT kernel), no GUI, no LLM. A Pydantic schema validates
+ fills STR parameters (Rushton standard ratios as defaults/validators). Component builders
(vessel, baffles, shaft+impellers) produce solids; an assembly step forms the single-phase liquid
fluid domain and tags named surface regions; an exporter writes one STL per region. This is the
**CadQuery half of the D4 bake-off** — if it can't produce a clean snappy-meshable named STL, the
contract stays fixed and we swap the builder to Salome behind it.

**Tech Stack:** Python 3.11, `cadquery` (≥2.4), `pydantic` (v2), `trimesh` (STL/watertight checks),
`pytest`. OpenFOAM `blockMesh`/`snappyHexMesh`/`checkMesh` for the acceptance gate (installed locally).

**Spec:** `docs/superpowers/specs/2026-06-15-parts-a-b-str-pipeline-design.md` (D3, D4, D5, D13, D16).

**Out of scope (separate plans):** the LLM prompt→schema extraction layer (plan #2); Part B case
generation + meshing-as-Batch (plan #3); app/Part-C integration (plan #4).

---

## File structure

```
part-a-cad/
  pyproject.toml                 # package + deps (cadquery, pydantic, trimesh, pytest)
  str_cad/
    __init__.py
    schema.py                    # STRParams Pydantic model + Rushton-ratio validators (D16)
    geometry/
      __init__.py
      vessel.py                  # cylindrical side + dished bottom head
      baffles.py                 # N symmetric vertical baffles
      internals.py               # central shaft + N Rushton turbines (disc, 6 blades, hub)
      assembly.py                # liquid fluid domain + named region tagging (D5)
    export.py                    # per-region STL writer + str-params.json
    builder.py                   # orchestrator: STRParams -> geometry/ dir
  examples/
    reactor_30kl.json            # the golden prompt's parameters (acceptance fixture)
  validation/
    blockMeshDict.template       # background box (filled from STL bbox)
    snappyHexMeshDict.template   # geometry{} + refinement, locationInMesh placeholder
    run_mesh_check.sh            # blockMesh -> snappyHexMesh -> checkMesh on builder output
  tests/
    test_schema.py
    test_vessel.py
    test_baffles.py
    test_internals.py
    test_assembly.py
    test_export.py
    test_builder.py
```

Each file has one responsibility; component builders are independent and unit-testable in isolation.

---

## Conventions for every task

- **TDD:** write the failing test first, watch it fail, have codex implement the minimal body,
  watch it pass, commit.
- **Geometry tests assert measurable properties** (bounding box, volume, solid/face/region counts,
  watertightness) — never "looks right".
- **Commit** after each green task: `git add part-a-cad && git commit -m "<msg>"`.
- Run tests with `cd part-a-cad && pytest tests/<file> -v`.

---

### Task 1: Package scaffold + STR schema with Rushton validators

**Files:**
- Create: `part-a-cad/pyproject.toml`, `part-a-cad/str_cad/__init__.py`, `part-a-cad/str_cad/schema.py`
- Test: `part-a-cad/tests/test_schema.py`

- [ ] **Step 1: Write the failing tests** (defines the schema contract — D16)

```python
# tests/test_schema.py
import math
import pytest
from str_cad.schema import STRParams, SchemaError

def _valid():
    return {
        "family": "stirred_tank_reactor",
        "tank": {"diameter_m": 2.09, "height_m": 9.6, "bottom": "dished"},
        "liquid": {"height_m": 6.55},
        "baffles": {"count": 4, "width_m": 0.167, "height_m": 7.5, "arrangement": "symmetric"},
        "shaft": {"central": True},
        "impellers": {"count": 4, "type": "rushton", "blades": 6,
                      "diameter_ratio": 1/3, "blade_height_m": 0.14, "blade_length_m": 0.175,
                      "lowest_clearance_m": 1.12, "inter_impeller_clearance_m": 1.46},
    }

def test_valid_schema_parses():
    p = STRParams.model_validate(_valid())
    assert p.impellers.count == 4

def test_impeller_diameter_derived_from_ratio():
    p = STRParams.model_validate(_valid())
    assert math.isclose(p.impeller_diameter_m, 2.09/3, rel_tol=1e-6)

def test_rushton_blade_dims_validated_against_standard_ratios():
    # standard Rushton: blade_length ~ D/4, blade_height ~ D/5; tolerate +/-10%
    p = STRParams.model_validate(_valid())
    D = p.impeller_diameter_m
    assert abs(p.impellers.blade_length_m - D/4) <= 0.1 * (D/4)
    assert abs(p.impellers.blade_height_m - D/5) <= 0.1 * (D/5)

def test_liquid_height_must_not_exceed_tank_height():
    bad = _valid(); bad["liquid"]["height_m"] = 12.0
    with pytest.raises(SchemaError):
        STRParams.model_validate(bad)

def test_impellers_must_fit_under_liquid_height():
    # lowest_clearance + (count-1)*inter_clearance must stay below liquid height
    bad = _valid(); bad["impellers"]["inter_impeller_clearance_m"] = 3.0
    with pytest.raises(SchemaError):
        STRParams.model_validate(bad)

def test_blade_dims_far_from_standard_rejected():
    bad = _valid(); bad["impellers"]["blade_length_m"] = 0.5
    with pytest.raises(SchemaError):
        STRParams.model_validate(bad)
```

- [ ] **Step 2: Run, verify failure** — `pytest tests/test_schema.py -v` → FAIL (no module).
- [ ] **Step 3: codex implements `schema.py`** — `STRParams` (nested models: `Tank`, `Liquid`,
  `Baffles`, `Shaft`, `Impellers`), a computed `impeller_diameter_m = tank.diameter_m *
  impellers.diameter_ratio`, a `SchemaError` raised by `@model_validator` for: liquid ≤ tank
  height; impeller stack fits under liquid height; blade length within ±10% of D/4 and blade
  height within ±10% of D/5 (D16). Missing blade dims default to D/4, D/5.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(part-a): STR Pydantic schema + Rushton validators`.

---

### Task 2: Vessel builder (cylindrical side + dished bottom)

**Files:** Create `part-a-cad/str_cad/geometry/__init__.py`, `vessel.py`; Test `tests/test_vessel.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vessel.py
import math
from str_cad.schema import STRParams
from str_cad.geometry.vessel import build_vessel_shell
from tests.test_schema import _valid

def test_vessel_bounding_box_matches_diameter_and_liquid_height():
    p = STRParams.model_validate(_valid())
    shell = build_vessel_shell(p)            # returns a cadquery Workplane/Solid
    bb = shell.val().BoundingBox()
    assert math.isclose(bb.xlen, p.tank.diameter_m, rel_tol=0.02)
    assert math.isclose(bb.ylen, p.tank.diameter_m, rel_tol=0.02)
    # liquid domain only: top capped at liquid height, bottom is the dished head (z<0 dish depth)
    assert bb.zmax <= p.liquid.height_m + 1e-6

def test_vessel_volume_close_to_liquid_volume():
    p = STRParams.model_validate(_valid())
    shell = build_vessel_shell(p)
    r = p.tank.diameter_m / 2
    cyl_vol = math.pi * r**2 * p.liquid.height_m
    # dished bottom adds a little; allow generous band but reject a plain box / wrong scale
    assert 0.9 * cyl_vol <= shell.val().Volume() <= 1.3 * cyl_vol
```

- [ ] **Step 2: Run, verify failure.**
- [ ] **Step 3: codex implements `build_vessel_shell(p: STRParams)`** — the liquid fluid region:
  a cylinder (radius `tank.diameter_m/2`, from the dish tangent line up to `liquid.height_m`)
  fused with a dished bottom head (torispherical or 2:1 elliptical via `revolve` of the head
  profile). Returns a `cadquery.Workplane` of one solid. Axis = Z, origin at vessel centerline,
  z=0 at the cylinder/dish tangent.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(part-a): vessel shell (cyl + dished bottom)`.

---

### Task 3: Baffles builder

**Files:** Create `part-a-cad/str_cad/geometry/baffles.py`; Test `tests/test_baffles.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_baffles.py
from str_cad.schema import STRParams
from str_cad.geometry.baffles import build_baffles
from tests.test_schema import _valid

def test_four_baffles_returned():
    p = STRParams.model_validate(_valid())
    baffles = build_baffles(p)               # list[cadquery.Workplane], one per baffle
    assert len(baffles) == p.baffles.count

def test_baffles_are_symmetric_at_90_degrees():
    p = STRParams.model_validate(_valid())
    centers = [b.val().Center() for b in build_baffles(p)]
    # all at (nearly) the same radius from axis, angularly evenly spaced
    radii = [round((c.x**2 + c.y**2) ** 0.5, 3) for c in centers]
    assert len(set(radii)) == 1

def test_baffle_height_matches_schema():
    p = STRParams.model_validate(_valid())
    b0 = build_baffles(p)[0].val().BoundingBox()
    assert abs(b0.zlen - p.baffles.height_m) <= 0.02 * p.baffles.height_m
```

- [ ] **Step 2: Run, verify failure.**
- [ ] **Step 3: codex implements `build_baffles(p)`** — `count` rectangular plates, thickness
  small (e.g. 0.02 m default constant), radial width `baffles.width_m`, height `baffles.height_m`,
  outer edge near the wall, evenly spaced at `360/count` degrees, returned as a list of solids.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(part-a): symmetric baffles`.

---

### Task 4: Shaft + Rushton impellers builder

**Files:** Create `part-a-cad/str_cad/geometry/internals.py`; Test `tests/test_internals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_internals.py
from str_cad.schema import STRParams
from str_cad.geometry.internals import build_shaft, build_impellers, impeller_z_positions
from tests.test_schema import _valid

def test_impeller_z_positions_from_clearances():
    p = STRParams.model_validate(_valid())
    zs = impeller_z_positions(p)
    assert len(zs) == p.impellers.count
    assert abs(zs[0] - p.impellers.lowest_clearance_m) <= 1e-6
    assert abs((zs[1] - zs[0]) - p.impellers.inter_impeller_clearance_m) <= 1e-6

def test_each_impeller_has_six_blades_solid_count():
    p = STRParams.model_validate(_valid())
    imps = build_impellers(p)                 # list[cadquery.Workplane], one fused turbine per impeller
    assert len(imps) == p.impellers.count

def test_shaft_spans_from_top_through_lowest_impeller():
    p = STRParams.model_validate(_valid())
    bb = build_shaft(p).val().BoundingBox()
    assert bb.zmax >= p.liquid.height_m - 1e-6
    assert bb.zmin <= p.impellers.lowest_clearance_m + 1e-6
```

- [ ] **Step 2: Run, verify failure.**
- [ ] **Step 3: codex implements** `impeller_z_positions` (`lowest_clearance + i*inter_clearance`),
  `build_shaft` (thin axial cylinder), `build_impellers` (per z: a Rushton turbine = central disc
  + hub + `blades` flat blades in a polar array, sized from `impeller_diameter_m`, `blade_height_m`,
  `blade_length_m`). Each turbine returned as one fused solid.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(part-a): shaft + Rushton impellers`.

---

### Task 5: Fluid-domain assembly + named region tagging (D5)

**Files:** Create `part-a-cad/str_cad/geometry/assembly.py`; Test `tests/test_assembly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assembly.py
from str_cad.schema import STRParams
from str_cad.geometry.assembly import build_fluid_domain, REGION_NAMES
from tests.test_schema import _valid

EXPECTED = {"tankWall", "dishedBottom", "baffles", "shaft", "impellers", "liquidSurface"}

def test_region_names_are_the_locked_contract():
    assert set(REGION_NAMES) == EXPECTED

def test_assembly_returns_a_surface_per_region():
    p = STRParams.model_validate(_valid())
    domain = build_fluid_domain(p)            # -> dict[str, cadquery.Shape] (one shell per region)
    assert set(domain.keys()) == EXPECTED
    for name, shape in domain.items():
        assert shape.Area() > 0, name

def test_fluid_domain_internals_are_subtracted():
    # the liquid solid (pre-surface-split) must have less volume than the bare vessel shell
    from str_cad.geometry.vessel import build_vessel_shell
    p = STRParams.model_validate(_valid())
    from str_cad.geometry.assembly import build_fluid_solid
    assert build_fluid_solid(p).Volume() < build_vessel_shell(p).val().Volume()
```

- [ ] **Step 2: Run, verify failure.**
- [ ] **Step 3: codex implements** `build_fluid_solid(p)` = vessel shell minus (shaft ∪ impellers ∪
  baffles) capped at `liquid.height_m`; `REGION_NAMES` = the 6 locked names; `build_fluid_domain(p)`
  returns the boundary split into the 6 named surface groups by face selection (outer cylinder →
  `tankWall`, dish faces → `dishedBottom`, top cap → `liquidSurface`, and the subtracted-internal
  faces → `baffles`/`shaft`/`impellers`).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(part-a): fluid domain + named region split`.

---

### Task 6: Per-region STL export + str-params.json + watertight check

**Files:** Create `part-a-cad/str_cad/export.py`; Test `tests/test_export.py`

- [ ] **Step 1: Write the failing test** (uses `trimesh` to assert manifold/watertight STL)

```python
# tests/test_export.py
import json, trimesh
from pathlib import Path
from str_cad.schema import STRParams
from str_cad.export import export_geometry
from tests.test_schema import _valid

EXPECTED_FILES = {"tankWall.stl","dishedBottom.stl","baffles.stl","shaft.stl",
                  "impellers.stl","liquidSurface.stl"}

def test_export_writes_all_region_stls_and_params(tmp_path):
    p = STRParams.model_validate(_valid())
    out = export_geometry(p, tmp_path)
    files = {f.name for f in Path(out, "geometry").glob("*.stl")}
    assert files == EXPECTED_FILES
    params = json.loads(Path(out, "str-params.json").read_text())
    assert params["family"] == "stirred_tank_reactor"

def test_combined_surfaces_form_a_watertight_fluid_domain(tmp_path):
    p = STRParams.model_validate(_valid())
    out = export_geometry(p, tmp_path)
    meshes = [trimesh.load(str(f)) for f in Path(out,"geometry").glob("*.stl")]
    combined = trimesh.util.concatenate(meshes)
    combined.merge_vertices()
    assert combined.is_watertight, "fluid domain boundary is not closed -> snappy will fail"
```

- [ ] **Step 2: Run, verify failure.**
- [ ] **Step 3: codex implements `export_geometry(p, out_dir)`** — writes `geometry/<region>.stl`
  for each of the 6 regions (binary STL, mm or m units consistent with the validation dicts) and
  `str-params.json` (the validated schema dump). Returns `out_dir`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(part-a): per-region STL export + watertight check`.

---

### Task 7: Builder orchestrator + golden-reactor example

**Files:** Create `part-a-cad/str_cad/builder.py`, `part-a-cad/examples/reactor_30kl.json`;
Test `tests/test_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_builder.py
import json
from pathlib import Path
from str_cad.builder import build_from_schema_file

def test_build_golden_reactor(tmp_path):
    out = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path)
    assert (Path(out, "geometry", "tankWall.stl")).exists()
    # sanity: ~30 kL liquid volume from the example (33 m^3 cylinder per spec)
    params = json.loads(Path(out, "str-params.json").read_text())
    assert params["tank"]["diameter_m"] == 2.09
```

- [ ] **Step 2: Run, verify failure.**
- [ ] **Step 3: codex implements** `examples/reactor_30kl.json` (the golden prompt's exact numbers)
  and `build_from_schema_file(path, out_dir)` = load JSON → `STRParams.model_validate` →
  `export_geometry`. Add a `python -m str_cad.builder <schema.json> <out_dir>` CLI entry.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(part-a): builder orchestrator + golden reactor example`.

---

### Task 8: snappyHexMesh + checkMesh acceptance gate (the D4 verdict)

**Files:** Create `part-a-cad/validation/{blockMeshDict.template,snappyHexMeshDict.template,run_mesh_check.sh}`

- [ ] **Step 1: Write `run_mesh_check.sh`** — given a builder output dir: compute the STL bounding
  box, fill `blockMeshDict.template` (background box slightly larger than bbox) and
  `snappyHexMeshDict.template` (`geometry{}` referencing the 6 STLs with `name <region>`; a
  `locationInMesh` point in the liquid — e.g. `(0 0 <liquid_height/2>)` offset off-axis to avoid
  the shaft; `castellatedMesh true`, `snap true`, `addLayers false` for the PoC), then run
  `blockMesh`, `snappyHexMesh -overwrite`, `checkMesh`.
- [ ] **Step 2: Run the gate on the golden reactor**

```bash
cd part-a-cad
python -m str_cad.builder examples/reactor_30kl.json /tmp/str_out
bash validation/run_mesh_check.sh /tmp/str_out
```

Expected: `blockMesh` OK; `snappyHexMesh` completes; **`checkMesh` reports `Mesh OK`** with the
6 patches present (`tankWall`, `dishedBottom`, `baffles`, `shaft`, `impellers`, `liquidSurface`)
and no failed checks. Triage warnings; fail on errors.

- [ ] **Step 3: Record the verdict** — if `checkMesh` passes, D4 resolves to **CadQuery** for the
  builder. If it fails on geometry codex cannot fix (e.g. dished-head face selection, blade
  watertightness), record the failure mode in the spec's "Open items" and escalate to the Salome
  builder behind the same `export_geometry` contract.
- [ ] **Step 4: Commit** — `feat(part-a): snappy+checkMesh acceptance gate + D4 verdict`.

---

## Self-review (done)

- **Spec coverage:** D3/D13 (parametric STR family, schema-first) → Task 1; D16 (Rushton ratios) →
  Task 1; D5 (6-region named STL contract) → Tasks 5–6; D6 (single-phase liquid domain, slip lid)
  → Tasks 2 + 5; D4 (CadQuery default + bake-off verdict, swappable behind the contract) → Task 8.
  Not in this plan by design: D7/D8/D9/D10/D11/D12/D14/D15 belong to Part B / integration plans.
- **Placeholder scan:** none — every task has concrete tests + a named implementation contract;
  geometry bodies are deliberately codex's to write (per the all-code-to-codex rule), specified by
  measurable acceptance, not left vague.
- **Type consistency:** `STRParams`, `impeller_diameter_m`, `REGION_NAMES` (the 6 locked names),
  `build_vessel_shell`/`build_baffles`/`build_shaft`/`build_impellers`/`build_fluid_solid`/
  `build_fluid_domain`/`export_geometry`/`build_from_schema_file` are used consistently across tasks.
```
