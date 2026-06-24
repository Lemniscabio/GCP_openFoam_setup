# Reference cases — and how to add a new case type

This folder holds the **known-good, hand-built OpenFOAM cases** that the parametric
generator in [`../part-a-cad`](../part-a-cad) was built from and is validated against.

| Folder | What it is |
|---|---|
| [`singlephase/`](singlephase) | Single-phase MRF stirred tank (template dicts + `generate_cases.py`). |
| [`twophase/`](twophase) | Two-phase gas–liquid Euler–Euler case (`multiphaseEuler`; full `0/`, `constant/`, `system/`, pre-built `polyMesh`). |

These are **reference data**, not part of the runtime. The generator produces cases that
are checked against them by the golden tests in `../part-a-cad/tests/golden/`.

---

## How to add a new case type (e.g. a new reactor family or physics mode)

This is a recipe for a **developer or a coding agent (codex)** — the runtime chat agent in
the web app only fills the geometry spec for *existing* families; it does not add new types.

The pipeline is family/physics-pluggable: you add modules behind registries, you do not
edit the core. The five steps:

### 1. Add the reference case

Drop a complete, known-good OpenFOAM case under `references/<name>/` (mesh + `0/` +
`constant/` + `system/` + a `command.sh`). This is your ground-truth target — everything
below is validated against it.

### 2. Register the geometry

In `../part-a-cad/str_cad/geometry/registry.py`:
- **New impeller type:** write a builder and register it under its name in `_IMPELLERS`
  (e.g. `"pbt"`). Specs then set `impellers.type` to that name.
- **New reactor family:** add a `geometry/families/<name>/` module exposing
  `REGION_NAMES` and `build_fluid_domain(p)`, and register it in `_FAMILIES`.

If the new type needs new spec fields, extend `../part-a-cad/str_cad/schema.py` (and its
correlations in `derived()`), keeping new fields optional/defaulted so existing specs
stay valid.

### 3. Add the OpenFOAM-case writers

In `../part-a-cad/str_cad/ofcase/`:
- For a new **physics mode**, add an `ofcase/<physics>/` package (mirroring
  `single_phase/` and `two_phase/`) with its `constant/`, `0/`, and `system/` writers,
  and a `build_<physics>_case`.
- Wire it into the `build_case` dispatch (`ofcase/build.py`) on `sp.physics` (or the
  family).
- Reproduce the reference dicts faithfully, parameterized by the spec. Pre-extract any
  measurements from the reference STLs/dicts and hand them to the writer — don't hardcode.

### 4. Expose its variations

In `../part-a-cad/str_cad/variations.py`, add the new **geometry-fixed** operating axes
(e.g. a new operating parameter) to `VARIATION_AXES` + `apply_axis_value` +
`_AXIS_CONTROLLED_FILES`, and surface them in the web UI's variations section. Keep axes
geometry-fixed (rpm/viscosity/gas-style) so edits carry into every variation.

### 5. Add golden tests

In `../part-a-cad/tests/golden/`, add a `test_<name>_golden.py` that builds a case from a
spec equivalent to the new reference and asserts the generated dicts/fields/BCs match the
reference (semantic equality, not byte-for-byte). Then verify it runs — locally on the
`kartikeyattri/openfoam:12` docker image (see `../docs/ARCHITECTURE.md`) or on-server.

---

See [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) for the full pipeline walkthrough.
