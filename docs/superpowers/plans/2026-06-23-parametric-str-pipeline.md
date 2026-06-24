# Parametric STR Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `part-a-cad` into a parametric stirred-tank-reactor generator that takes a JSON spec and produces a complete, runnable OpenFOAM case — single-phase OR two-phase — with a variations layer, verified by an on-server smoke run on GCP.

**Architecture:** Extend the existing clean `part-a-cad/str_cad` module (Approach A from the spec). Geometry becomes a family-pluggable registry; `ofcase` dispatches on a `physics` mode (single|two-phase); a `variations` layer replaces the regex sweeper; a `verify` harness submits to GCP via the existing `of` CLI. The hand-built `singlephase/` and `twophase/` dirs are validation **oracles**, not codepaths.

**Tech Stack:** Python 3.11, pydantic v2, CadQuery + trimesh (geometry), pytest. OpenFOAM v12 (on-server only). GCP Cloud Batch via `phase3-run-app`'s `of` CLI (`core/`, `cli/main.py`), project `cfd-lemnisca`.

## Global Constraints

- **All production code is authored by `codex`** (`codex exec`). Claude orchestrates, writes task specs, reviews diffs, runs verification, commits. Claude writes no `str_cad`/`verify` source. (Standing user rule.)
- **`grok` (headless) is the independent reviewer** — OF-v12 dict correctness + adversarial diff vs oracles. Findings only; never edits the repo.
- OpenFOAM target version: **12** (matches reference dicts' header "Version: 12" and image `openfoam:12.0.1`).
- Reference oracles: `singlephase/` (template + fields) and `twophase/` (full Euler-Euler case). Generated output must be **semantically** equivalent to these (dict entries, fields, region/patch names), not byte-identical.
- GCP verification targets **`cfd-lemnisca`** explicitly (bucket `cfd-lemnisca-cases`, region `us-central1`, image `openfoam:12.0.1`) — never the ambient `test-openfoam` gcloud config.
- Backward-compat: existing `part-a-cad` tests must keep passing unless a task explicitly supersedes one (call it out in that task).
- Every derived/defaulted value must be written to the case `metadata.json`.
- TDD: failing test first, minimal code to pass, commit per task. Tests run with `pytest` from `part-a-cad/`.

## How each task runs (the loop protocol)

This plan is executed by the **codex/grok orchestration loop**, so each task's steps are expressed as an orchestration cycle rather than hand-written code (per the standing rule that codex authors all code):

1. **Spec** — Claude writes codex a precise task brief: files, the Interfaces block below, the oracle to match, and the acceptance tests (names + behavior).
2. **Implement (codex, TDD)** — codex writes the failing test(s), runs them red, implements minimal code, runs them green.
3. **Local gate (Claude)** — run the task's acceptance command; confirm green + no regressions (`pytest` in `part-a-cad/`).
4. **Review (grok)** — grok reviews the diff for OF-v12 correctness + oracle fidelity → findings.
5. **Reconcile (Claude)** — material findings go back to codex (step 2); else proceed.
6. **Verify (Claude)** — for tasks that make a case runnable, run the on-server smoke verify (Task 6.x). Otherwise skip.
7. **Commit** — Claude commits with the task's message, ticks the boxes, moves on.

"Interfaces" blocks are the contract codex must hit so neighboring tasks compose. Test code in this plan is the **acceptance intent** (names + assertions codex must satisfy); codex may add more tests but must not weaken these.

---

## Phase 1 — Schema v2 (physics mode, two-phase fields, correlations, metadata)

### Task 1.1: Add physics mode + correlation/default engine to `STRParams`

**Files:**
- Modify: `part-a-cad/str_cad/schema.py`
- Test: `part-a-cad/tests/test_schema.py` (extend)

**Interfaces:**
- Consumes: existing `STRParams`, `Tank`, `Liquid`, `Baffles`, `Shaft`, `Impellers`.
- Produces:
  - `STRParams.physics: Literal["single_phase", "two_phase"]` (required, no default — Tier 1).
  - `STRParams.operating: Operating` where `Operating` has `rpm: float` (required) and, for two-phase, `gas_flow_vvm: float | None` and `sparger: Sparger | None`.
  - `STRParams.derived() -> dict` returning every Tier-2 value the generator computed (blade dims, shaft/hub radii, baffle width, clearances, MRF rotor radius), for metadata logging.
  - All existing computed fields (`impeller_diameter_m`) and validators preserved.

**Oracle:** `part-a-cad/examples/reactor_30kl.json` must still validate (add `"physics": "single_phase"`, `"operating": {"rpm": 90}`); a new `examples/reactor_twophase.json` derived from `twophase/` geometry must validate as `two_phase`.

- [ ] **Step 1 (Spec):** Brief codex: add `physics`, `Operating`, two-phase optional fields, `derived()`, keep existing validators. Tier-1 fields required; Tier-2 auto-filled + overridable.
- [ ] **Step 2 (codex TDD):** Acceptance tests, must pass:
  - `test_physics_required` — `STRParams.model_validate({...without physics...})` raises validation error.
  - `test_two_phase_requires_gas_flow` — `physics="two_phase"` without `operating.gas_flow_vvm` and without sparger raises `SchemaError`.
  - `test_derived_reports_blade_dims` — `derived()` includes `blade_length_m`, `blade_height_m`, `shaft_radius_m`, `baffle_width_m`, `mrf_rotor_radius_m` with correct correlation values (D/4, D/5, D/20, T/12, and the rotor radius used by `meshcase`).
  - `test_single_phase_example_validates` / `test_two_phase_example_validates` — both example JSONs validate.
- [ ] **Step 3 (Local gate):** `cd part-a-cad && pytest tests/test_schema.py -v` → all green; `pytest -q` → no regressions.
- [ ] **Step 4 (grok review):** schema covers Tier-1/2/3 split correctly; correlation constants match STR convention + what `meshcase`/`internals` already assume.
- [ ] **Step 5 (Commit):** `feat(schema): physics mode + correlation engine + derived() for metadata`.

### Task 1.2: Two-phase example fixture from the `twophase/` oracle

**Files:**
- Create: `part-a-cad/examples/reactor_twophase.json`
- Modify: `part-a-cad/examples/reactor_30kl.json` (add `physics`/`operating`)
- Test: `part-a-cad/tests/test_schema.py` (covered by 1.1 example tests)

**Interfaces:**
- Consumes: Task 1.1 schema.
- Produces: a canonical two-phase STR spec whose geometry corresponds to the `twophase/` reactor (impeller count/type, tank dims inferred from `twophase/constant/triSurface/*.stl` bounds + `blockMeshDict`).

- [ ] **Step 1 (Spec):** Brief codex to read `twophase/` geometry (STL bounds via trimesh, `blockMeshDict` extents, `MRFProperties`/`phaseProperties` for phases) and write a matching spec JSON; document inferred values in a top-level `"_provenance"` comment field.
- [ ] **Step 2 (codex):** produce the JSON; it must validate (test from 1.1).
- [ ] **Step 3 (Local gate):** `pytest tests/test_schema.py::test_two_phase_example_validates -v` green.
- [ ] **Step 4 (grok review):** inferred dims/phase setup match the `twophase/` oracle.
- [ ] **Step 5 (Commit):** `feat(examples): two-phase STR spec inferred from twophase oracle`.

---

## Phase 2 — Geometry: parametric STR family + impeller registry

### Task 2.1: Family + impeller-type registry

**Files:**
- Create: `part-a-cad/str_cad/geometry/registry.py`
- Create: `part-a-cad/str_cad/geometry/families/__init__.py`, `families/str/__init__.py`
- Move/rewire: `vessel.py`, `baffles.py`, `internals.py`, `assembly.py` under `families/str/` (keep import shims if existing tests import old paths, OR update tests in same task — call it out).
- Test: `part-a-cad/tests/test_builder.py`, `test_assembly.py`, `test_vessel.py`, `test_baffles.py`, `test_internals.py` (update import paths), `tests/test_registry.py` (new).

**Interfaces:**
- Consumes: `STRParams`.
- Produces:
  - `geometry.registry.get_family(name: str) -> Family` where `Family` exposes `build_fluid_domain(p: STRParams) -> dict[str, cq.Shape]` and `REGION_NAMES: list[str]`.
  - `geometry.registry.get_impeller(type_: str) -> Callable[[STRParams, float], cq.Workplane]` (per-impeller builder dispatched on `impellers.type`); at minimum `"rushton"` registered, with a clear `KeyError`/`SchemaError` for unknown types.
  - `REGION_NAMES` unchanged in value (`tankWall, dishedBottom, baffles, shaft, impellers, liquidSurface`) so `ofcase`/`meshcase` keep working.

**Oracle:** generated STLs for `reactor_30kl.json` must load in trimesh as watertight-enough, non-empty meshes for every region (same regions as today).

- [ ] **Step 1 (Spec):** Brief codex: introduce registry, relocate STR builders behind it, dispatch impeller build on `impellers.type`, preserve `REGION_NAMES` and `build_fluid_domain` behavior.
- [ ] **Step 2 (codex TDD):** Acceptance tests:
  - `test_registry_returns_str_family` — `get_family("stirred_tank_reactor")` returns a family with the 6 region names.
  - `test_unknown_impeller_type_raises` — `get_impeller("nonsense")` raises.
  - `test_existing_geometry_unchanged` — region face-grouping for `reactor_30kl.json` yields the same region keys, each non-empty (regression vs current `assembly.build_fluid_domain`).
- [ ] **Step 3 (Local gate):** `cd part-a-cad && pytest -q` green (all relocated tests updated).
- [ ] **Step 4 (grok review):** registry boundary is clean; "add a new family/impeller = new module, no core edits" holds.
- [ ] **Step 5 (Commit):** `refactor(geometry): family + impeller registry; relocate STR builders`.

### Task 2.2: Parametric correctness — bottom type + impeller type honored

**Files:**
- Modify: `part-a-cad/str_cad/geometry/families/str/vessel.py` (flat vs dished from `tank.bottom`)
- Modify: `families/str/internals.py` (impeller built via registry per `impellers.type`)
- Test: `tests/test_vessel.py`, `tests/test_internals.py` (extend)

**Interfaces:**
- Consumes: Task 2.1 registry, `STRParams`.
- Produces: `build_vessel_shell(p)` branches on `p.tank.bottom in {"dished","flat"}`; impeller builder selected by `p.impellers.type`. No new public signatures.

**Oracle:** `tank.bottom="flat"` produces a flat-bottomed shell (no revolved head); `"dished"` reproduces today's dished head.

- [ ] **Step 1 (Spec):** Brief codex to honor `tank.bottom` and `impellers.type` (today they're ignored).
- [ ] **Step 2 (codex TDD):** Acceptance tests:
  - `test_flat_bottom_has_no_dished_head` — flat-bottom vessel's min-z ≈ 0 (within tol), dished-bottom min-z ≈ -radius.
  - `test_rushton_impeller_blade_count` — built impeller solid has `impellers.blades` blades (face/volume heuristic or blade-count check).
- [ ] **Step 3 (Local gate):** `pytest tests/test_vessel.py tests/test_internals.py -v` green; `pytest -q` no regressions.
- [ ] **Step 4 (grok review):** geometry still meshable (no degenerate flat-bottom edge), CadQuery booleans sound.
- [ ] **Step 5 (Commit):** `feat(geometry): honor tank.bottom and impellers.type`.

---

## Phase 3 — ofcase single-phase: reconcile vs oracle + structured variations

### Task 3.1: Reconcile single-phase generated dicts against `singlephase/` oracle

**Files:**
- Modify: `part-a-cad/str_cad/ofcase/{physics,mrf,fields,systemdicts,command}.py` as needed
- Move: `ofcase/*.py` single-phase writers under `ofcase/single_phase/` + `ofcase/common/` (shared) — keep `build_case` entry working.
- Test: `tests/golden/test_single_phase_golden.py` (new)

**Interfaces:**
- Consumes: Phase 1 schema, Phase 2 geometry, existing `build_case(case_params, geo_dir, out_dir)`.
- Produces: `ofcase.build_case` unchanged signature; outputs reconciled with the `singlephase/` oracle for: `physicalProperties` (nu dimensions + value), `momentumTransport` (RAS model + coeffs), `MRFProperties` (per-active-impeller rotor zones, omega in [rpm]), `0/` fields (U with MRF/rotating BCs, p/k/epsilon/nut), `controlDict`/`fvSchemes`/`fvSolution`.

**Oracle:** `singlephase/template/{0,constant,system}` + the active-impeller logic in `singlephase/generate_cases.py` (which impellers are submerged for a given fill).

- [ ] **Step 1 (Spec):** Brief codex with a field-by-field diff target: enumerate every entry in `singlephase/template` dicts and require the generator to emit semantically equal entries for the matching spec.
- [ ] **Step 2 (codex TDD):** `test_single_phase_golden.py`:
  - generate a case from a spec equivalent to the `singlephase` base geometry; assert each generated dict contains the oracle's key entries (parse with a foam-dict reader, compare entry sets/values for `physicalProperties.nu`, `momentumTransport` model, `MRFProperties` omega + zone names, `0/U` BC types per patch).
  - `test_active_impeller_selection` — for a low fill volume, only submerged impellers get MRF zones + BCs (mirror `active_impellers`).
- [ ] **Step 3 (Local gate):** `pytest tests/golden/test_single_phase_golden.py -v` green; `pytest -q` no regressions.
- [ ] **Step 4 (grok review):** adversarial diff vs `singlephase/template`; flag any OF12 entry that differs in a way that would change the solve.
- [ ] **Step 5 (Commit):** `feat(ofcase): single-phase dicts reconciled with singlephase oracle`.

### Task 3.2: Structured variations layer (replaces the regex sweeper)

**Files:**
- Create: `part-a-cad/str_cad/variations.py`
- Test: `tests/test_variations.py` (new)

**Interfaces:**
- Consumes: `STRParams`, `CaseParams`, `ofcase.build_case`.
- Produces:
  - `expand_variations(base_spec: dict, axes: dict[str, list]) -> list[dict]` — Cartesian product over axes (`rpm`, `viscosity_m2_s`, `fill_volume_m3` for single-phase; `rpm`, `gas_flow_vvm`, `alpha_gas` for two-phase), each a full spec.
  - `generate_sweep(base_spec, axes, out_root) -> dict[str, Path]` — builds a case dir per combo, writes a `runs_map.json` (same shape as today's), returns the map. Pure-Python dict manipulation, **no regex on dict text**.

**Oracle:** functional parity with `singlephase/generate_cases.py` (same combos → same active-impeller decisions + per-case params), but driven by the schema, not text substitution.

- [ ] **Step 1 (Spec):** Brief codex: structured sweep over schema fields; emit one case dir + params.json per combo + a top-level runs_map.json.
- [ ] **Step 2 (codex TDD):** `test_variations.py`:
  - `test_expand_cartesian` — 3 rpm × 2 nu → 6 specs with correct field values.
  - `test_sweep_writes_runs_map` — `generate_sweep` writes N case dirs + runs_map.json with N entries.
  - `test_sweep_matches_active_impellers` — for the legacy fill volumes, active-impeller sets equal `generate_cases.py`'s output.
- [ ] **Step 3 (Local gate):** `pytest tests/test_variations.py -v` green.
- [ ] **Step 4 (grok review):** no text-mutation of dicts; axes cover the variations the spec names.
- [ ] **Step 5 (Commit):** `feat(variations): structured schema-driven sweep layer`.

---

## Phase 4 — ofcase two-phase (Euler-Euler gas/liquid)

### Task 4.1: Two-phase writers + physics dispatch

**Files:**
- Create: `part-a-cad/str_cad/ofcase/two_phase/{__init__,phase_properties,fields,physics,system}.py`
- Modify: `part-a-cad/str_cad/ofcase/build.py` (dispatch on `sp.physics`)
- Test: `tests/golden/test_two_phase_golden.py` (new)

**Interfaces:**
- Consumes: Phase 1 schema (`physics="two_phase"`, `operating.gas_flow_vvm`/sparger), Phase 2 geometry, `build_case`.
- Produces:
  - `build_case` dispatches: `single_phase` → existing writers; `two_phase` → two-phase writers.
  - Two-phase writers emit: `constant/phaseProperties` (basicMultiphaseSystem, `phases (gas liquid)`, diameterModels), `constant/physicalProperties.{gas,liquid}`, `constant/momentumTransport.{gas,liquid}`, `0/{alpha.gas,alpha.liquid,U.gas,U.liquid,p,p_rgh,T.gas,T.liquid,k.liquid,epsilon.liquid,nut.liquid,alphat.liquid}`, `system/setFieldsDict`, `system/mapFieldsDict`, `command.sh` (with `setFields` step).

**Oracle:** the full `twophase/` case — every file under `twophase/{0,constant,system}` is the target for the corresponding generated file (semantic equality of entries, region/phase names, BC structure).

- [ ] **Step 1 (Spec):** Brief codex with a file-by-file mapping: for each `twophase/` file, the generator must emit a semantically equal file parameterized by the spec. Provide the oracle paths.
- [ ] **Step 2 (codex TDD):** `test_two_phase_golden.py`:
  - `test_phase_properties_entries` — generated `phaseProperties` has `type basicMultiphaseSystem`, `phases (gas liquid)`, both phase blocks with diameterModel.
  - `test_per_phase_fields_present` — all `0/` two-phase fields listed above exist with correct `class`/`object` headers and per-patch BC types matching the oracle.
  - `test_command_sh_has_setfields` — two-phase `command.sh` runs `setFields` before `foamRun`.
  - `test_single_phase_still_dispatches` — `physics="single_phase"` path unchanged (regression).
- [ ] **Step 3 (Local gate):** `pytest tests/golden/test_two_phase_golden.py -v` green; `pytest -q` no regressions.
- [ ] **Step 4 (grok review):** **deep** OF12 Euler-Euler review — phase model types, residualAlpha, momentumTransport per phase, p_rgh vs p, alpha BCs, MRF with two phases. This is the highest-risk task; expect ≥1 reconcile cycle.
- [ ] **Step 5 (Commit):** `feat(ofcase): two-phase Euler-Euler writers + physics dispatch`.

---

## Phase 5 — Verification harness (on-server smoke run)

### Task 5.1: `verify` mode controlDict + smoke command

**Files:**
- Modify: `part-a-cad/str_cad/ofcase/common/` controlDict writer + `command.py`
- Test: `tests/test_verify_mode.py` (new)

**Interfaces:**
- Consumes: `CaseParams` (+ a new `Run.verify: bool = False` and small `verify_steps: int`).
- Produces: when `verify=True`, `controlDict` writes a tiny `endTime`/`deltaT` (a few steps) + `writeInterval` = end, so a smoke run completes fast. Otherwise unchanged.

- [ ] **Step 1 (Spec):** Brief codex: add verify flag → tiny run controlDict; keep command.sh pipeline intact (`blockMesh → snappyHexMesh → topoSet → setFields[2ph] → decomposePar → foamRun → reconstructPar`).
- [ ] **Step 2 (codex TDD):** `test_verify_mode.py`:
  - `test_verify_controldict_small_endtime` — verify case `controlDict` endTime ≤ `verify_steps * deltaT`.
  - `test_full_controldict_unchanged` — non-verify path matches Task 3.1 output.
- [ ] **Step 3 (Local gate):** `pytest tests/test_verify_mode.py -v` green.
- [ ] **Step 4 (grok review):** tiny endTime still exercises mesh + solver init (real signal, not a no-op).
- [ ] **Step 5 (Commit):** `feat(ofcase): verify-mode controlDict for smoke runs`.

### Task 5.2: On-server submit + log-parse harness

**Files:**
- Create: `part-a-cad/str_cad/verify/harness.py`, `verify/__init__.py`
- Test: `tests/test_harness.py` (new; mocks subprocess — no real GCP in unit tests)

**Interfaces:**
- Consumes: a generated case dir (with `command.sh`, `metadata.json`), the `of` CLI in `phase3-run-app`.
- Produces:
  - `submit_smoke(case_dir: Path, project: str = "cfd-lemnisca", machine: str = "c2d-highcpu-8") -> SmokeResult`.
  - Internally shells the `of` CLI: upload (`--case-dir`/`--command-sh`/`--project demo`), `validate`, `run --machine ... --project ...`, then polls status + fetches `log.foamRun`.
  - `parse_smoke_log(text: str) -> SmokeResult` with `meshed: bool`, `fields_read: bool`, `time_advanced: bool`, `exit_ok: bool`, `errors: list[str]` (markers: `blockMesh` "End", `snappyHexMesh` "Finished meshing", `foamRun` "Time = " advancing, "FOAM FATAL").
  - `SmokeResult.ok` ⇔ all of meshed/fields_read/time_advanced/exit_ok.

**Oracle:** `phase3-run-app/core/config.py` Settings (defaults already `cfd-lemnisca`); `cli/main.py` command surface (`upload --case-dir --command-sh --project`, `run --case --machine --project`).

- [ ] **Step 1 (Spec):** Brief codex: wrap the `of` CLI; pin `--project cfd-lemnisca`; parse logs into `SmokeResult`. Real GCP calls behind a thin runner so tests can mock it.
- [ ] **Step 2 (codex TDD):** `test_harness.py`:
  - `test_parse_success_log` — a sample successful `log.foamRun` → `SmokeResult.ok is True`.
  - `test_parse_fatal_log` — a log containing `FOAM FATAL ERROR` → `ok False` with the error captured.
  - `test_submit_targets_cfd_lemnisca` — mocked runner asserts `--project cfd-lemnisca` is passed (never `test-openfoam`).
- [ ] **Step 3 (Local gate):** `pytest tests/test_harness.py -v` green.
- [ ] **Step 4 (grok review):** log markers are the right success/failure signals for OF12; project pinning correct.
- [ ] **Step 5 (Commit):** `feat(verify): on-server smoke-run harness via of CLI`.

---

## Phase 6 — End-to-end green on GCP (the exit objective)

> These tasks make real GCP submissions to `cfd-lemnisca`. Claude confirms project + cost expectation before each first-of-kind submission. No new app code unless a verify failure traces to a generator bug (→ back to the owning phase via codex).

### Task 6.1: Single-phase base + 2 variations green on-server

**Files:** none new (uses Phase 3 + Phase 5). Artifacts: generated case dirs + smoke logs saved under `part-a-cad/validation/runs/`.

- [ ] **Step 1:** Generate single-phase base case + 2 variation specs (e.g. two rpm points) via `variations.generate_sweep`, `verify=True`.
- [ ] **Step 2:** `submit_smoke` each to `cfd-lemnisca` (`c2d-highcpu-8`).
- [ ] **Step 3 (Gate):** all 3 `SmokeResult.ok is True`; save logs + a `validation/single_phase_smoke.md` summary (machine, times, markers).
- [ ] **Step 4 (grok review):** logs genuinely show mesh + solver advance, not early exit.
- [ ] **Step 5 (Commit):** `test(verify): single-phase base+2 variations pass on-server (cfd-lemnisca)`.

### Task 6.2: Two-phase base + 2 variations green on-server

**Files:** none new (uses Phase 4 + Phase 5). Artifacts under `part-a-cad/validation/runs/`.

- [ ] **Step 1:** Generate two-phase base + 2 variation specs (e.g. two gas-flow points), `verify=True`.
- [ ] **Step 2:** `submit_smoke` each to `cfd-lemnisca`.
- [ ] **Step 3 (Gate):** all 3 `SmokeResult.ok is True`; save `validation/two_phase_smoke.md`.
- [ ] **Step 4 (grok review):** two-phase solver actually initializes both phases + advances time.
- [ ] **Step 5 (Commit):** `test(verify): two-phase base+2 variations pass on-server (cfd-lemnisca)`.

### Task 6.3: Wire-up docs + finishing

**Files:**
- Modify: `part-a-cad/README` / repo `README.md` (how to generate + verify a case end-to-end)
- Modify: replace `singlephase/run_cases.sh` reference with a pointer to `variations.generate_sweep` (don't delete the oracle dirs).

- [ ] **Step 1:** Document the JSON-spec → case → on-server-verify flow with a copy-paste example for each physics mode.
- [ ] **Step 2 (Gate):** a fresh reader can run the documented commands.
- [ ] **Step 3 (Commit):** `docs: parametric STR pipeline usage + verification`.
- [ ] **Step 4 (Finish):** invoke `superpowers:finishing-a-development-branch` to decide merge/PR.

---

## Self-Review

**Spec coverage:**
- Parametric STR generator → Phases 1–2. ✓
- Single + two-phase case generation → Phases 3 (single), 4 (two-phase). ✓
- Variations layer → Task 3.2. ✓
- Family-pluggable architecture → Task 2.1 registry. ✓
- 3-tier input model + metadata logging → Task 1.1 (`derived()` + required/optional fields). ✓
- References as oracles → golden tests 3.1, 4.1; geometry oracle 2.x. ✓
- On-server verification (cfd-lemnisca, smoke run, base+2 variations/physics) → Phase 5 + 6. ✓
- codex implements / grok reviews / Claude orchestrates → loop protocol + every task's steps. ✓

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to". Test intents are concrete (named + assertions). Code authored by codex per the standing rule — the plan states interfaces + acceptance, which is the contract, not a placeholder. ✓

**Type consistency:** `REGION_NAMES` preserved across Tasks 2.1/3.1/4.1; `build_case(case_params, geo_dir, out_dir)` signature stable; `SmokeResult.ok` defined once (5.2) and used in 6.x; `derived()`/`expand_variations`/`generate_sweep`/`submit_smoke`/`parse_smoke_log` names consistent across references. ✓
