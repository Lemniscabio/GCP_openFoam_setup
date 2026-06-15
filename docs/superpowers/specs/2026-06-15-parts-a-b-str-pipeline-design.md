# Parts A & B — Stirred-Tank-Reactor CAD→OpenFOAM pipeline

**Date:** 2026-06-15
**Status:** Approved design (pre-implementation)
**Project:** `cfd-lemnisca` OpenFOAM-on-Batch web app — Parts A (CAD/geometry) & B (case generation)

## Context

The product is a 3-part agentic CFD pipeline:

- **Part A — CAD/geometry agent**: natural-language prompt → 3D geometry (STL).
- **Part B — OpenFOAM case-generation agent**: geometry + a small set of schema-validated
  inputs → a complete, runnable OpenFOAM case.
- **Part C — GCP runner**: already built, deployed, and in use (upload → Cloud Batch →
  results in GCS). C's sole remaining limitation is Spot zonal capacity exhaustion.

This spec designs A and B from scratch. The first target is a **single-phase, proof-of-concept
stirred-tank reactor (STR)** driven from a prompt like:

> "Make a 30 kL stirred tank reactor… dished bottom, diameter 2.09 m, height 9.6 m, four
> vertical baffles (width 0.167 m, height 7.5 m), central shaft with four Rushton disc
> turbines (six blades, blade height 0.14 m, length 0.175 m), impeller/tank diameter ratio
> 1/3, lowermost impeller 1.12 m from bottom, inter-impeller clearance 1.46 m, liquid
> height 6.55 m."

### Grounding (research, 2026-06)

- **Meshing decision is OpenFOAM-native** (`blockMesh` → `snappyHexMesh` → `checkMesh`),
  not Salome's mesher. Rationale: hex-dominant cells solve better (less numerical diffusion,
  fewer cells, easier convergence) and the whole toolchain stays in OpenFOAM. Accepted
  trade-off: snappy's boundary-layer (`addLayers`) step is less reliable than a dedicated
  mesher — acceptable for bulk-mixing PoC cases.
- **The agentic-OpenFOAM research field** (Foam-Agent, MetaOpenFOAM, ChatCFD, NL2FOAM) solves
  *fuzzy NL → case*, a problem we do **not** have: Part B's inputs are schema-validated, and
  the geometry is a single parametric family. Foam-Agent is a **reference only** (dict-writing
  patterns, repair-loop design), never a dependency.
- **OpenFOAM v12 is modular** (`foamRun` + a solver module + `fvModels`/`fvConstraints`). LLM
  corpora are overwhelmingly v10-era (`simpleFoam`/`interFoam`); templates must enforce v12 form.

## The core reframe

Both parts collapse to **one** reliable pattern:

> **LLM extracts parameters from the prompt → a validated schema → a deterministic, hand-written
> builder fills a template.**

The LLM never writes geometry code or OpenFOAM dictionaries from scratch in production. It does
**NL → structured-parameter extraction** (which LLMs are reliable at). Hand-written, tested
builders do the rest.

- **Part A is the only genuinely "agentic" part** (prompt is fuzzy-in / structured-out).
- **Part B has no LLM in its generation path** — its inputs are a handful of numbers; it is
  `setup_twophase.py` generalized behind a schema.

The geometry is **not arbitrary CAD** — it is the **stirred-tank-reactor family**: one topology,
different numbers (tank D/H, dish, N baffles, N Rushton impellers, blade dims, clearances,
liquid height). This is why a parametric script builder fits and generative text-to-CAD does not
(can't guarantee exact dimensions, named regions, or repeatability).

## Goals

1. Prompt → validated STR schema → named multi-region STL (Part A).
2. STL + `{RPM, viscosity}` → complete v12 single-phase MRF case tree conforming to the Part C
   filesystem (Part B).
3. A clean **contract chain** A→B→C so each part is independently testable and swappable.
4. Single-phase MRF PoC that exercises every mechanical stage of the pipeline end to end.

## Non-goals (deferred)

- **Two-phase / aerated** physics (`multiphaseEuler`, sparger inlet, degassing outlet,
  `alpha` fields, aeration-rate variation) — designed-for but not built (see "Multiphase path").
- **AMI / sliding-mesh** rotation (MRF only for now).
- A full **run-and-repair reviewer loop** (validation gates only; borrow Foam-Agent's pattern later).
- **Per-impeller** patch splitting (group baffles/impellers for the PoC).
- Geometry families other than STR.

## Architecture

```
PROMPT ──(LLM extract)──▶ STR-schema ──(deterministic builder: CadQuery/Salome)──▶ named STL   [PART A]
                                                                                       │
named STL + {RPM, viscosity} + patch-role map ──(deterministic foamlib template)──▶ case tree   [PART B]
                                                                                       │
                                            blockMesh → snappyHexMesh → checkMesh → foamRun       [PART C]
```

**The contract chain (the load-bearing thread):**
Part A names the STL regions → Part B turns those names into mesh patches and writes one boundary
condition per patch from the schema → Part C runs it. **STL region names are the A↔B join.**

## Decisions register (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| D1 | A = LLM-assisted geometry; **B = deterministic template, no LLM in generation path** | B's inputs are numbers, not fuzzy intent |
| D2 | Unifying pattern: **LLM only extracts params → schema; builders are hand-written** | LLMs reliable at extraction, flaky at raw code |
| D3 | Geometry is the **STR family** → parametric builder, **not generative text-to-CAD** | Need exact dims, named regions, repeatability |
| D4 | Builder tool: **default CadQuery** (Cloud-Run-friendly, pure-Python, testable); bake-off vs the contact's proven **Salome** STR recipe; **swappable behind the STL contract** | Decision not locked; interface fixed so the builder can change without touching B |
| D5 | **Part A output = one STL file per named region** (see contract below) + `str-params.json` | snappy assigns patches from STL region names; per-file is most robust |
| D6 | **Single-phase, closed tank** for the PoC — no inlet/outlet; top = `slip` lid; two-phase deferred | Debug plumbing on the simplest physics |
| D7 | Rotation = **MRF**; rotor cellZones built by **`topoSet cylinderToCell`** from schema numbers (in Part B), not emitted as geometry | MRF needs cellZones not surfaces; numbers suffice |
| D8 | Part B physics template = **`incompressibleFluid`** (v12), `kOmegaSST` + wall functions, **MRF as a v12 `fvModel`** on rotor zones, closed-domain pressure reference (`pRefCell`/`pRefValue`) | Standard single-phase stirred-tank setup |
| D9 | **Meshing runs as a Batch job**, not in Cloud Run | snappy is minutes–hours, memory-heavy |
| D10 | Validation gates = `checkMesh` + dict-parse + **`0/`-vs-`polyMesh/boundary` patch-name consistency**; full repair loop deferred | Catch the common silent failures cheaply |
| D11 | PoC variations = **RPM** (→ MRF angular velocity) + **viscosity** (→ `physicalProperties`); aeration deferred | Aeration is a two-phase quantity |
| D12 | **Foam-Agent = reference only**, not a dependency | Our scope is narrower than what it solves |
| D13 | **Schema-first**: the STR-geometry schema and the case-params schema are the two core artifacts (the user-facing contracts) | Everything else hangs off them |
| D14 | Schema **accommodates** sparger-inlet/outlet patch roles, left unset in the PoC | Additive path to multiphase |
| D15 | **Group** all baffles into one patch and all impellers into one patch for the PoC | Split per-impeller later for per-impeller torque/power |
| D16 | Builder **encodes Rushton standard ratios** (impeller D = tankD/3; blade length = D/4; blade height = D/5) as defaults + validators | Catch self-inconsistent prompts; fill omitted dims |

## Part A — output contract (single-phase MRF STR)

Part A emits a directory of per-region STL files plus the validated schema:

```
geometry/
  tankWall.stl       → patch  type wall   (cylindrical side, to liquid height)
  dishedBottom.stl   → patch  type wall   (torispherical/dished bottom head)
  baffles.stl        → patch  type wall   (all 4 baffles, one group — D15)
  shaft.stl          → patch  type wall   (central shaft)
  impellers.stl      → patch  type wall   (all 4 Rushton turbines, one group — D15)
  liquidSurface.stl  → patch  type slip   (lid at liquid height = free-surface approximation)
str-params.json      → validated STR schema (seeds Part C metadata.json)
```

Everything else is **computed by Part B from the schema — no geometry needed**:

- `locationInMesh` — a point in the liquid (e.g. r ≈ 0.4·R, mid-height, between two baffles).
- 4 MRF rotor cellZones — `topoSet cylinderToCell` from impeller positions + rotor radius.
- background `blockMeshDict` box — from the STL bounding box.

## The two schemas (sketch — to be finalized in the plan)

### STR-geometry schema (Part A input → builder input)

```jsonc
{
  "family": "stirred_tank_reactor",
  "tank":     { "diameter_m": 2.09, "height_m": 9.6, "bottom": "dished" },
  "liquid":   { "height_m": 6.55 },
  "baffles":  { "count": 4, "width_m": 0.167, "height_m": 7.5, "arrangement": "symmetric" },
  "shaft":    { "central": true },
  "impellers": {
    "count": 4, "type": "rushton", "blades": 6,
    "diameter_ratio": 0.3333, "blade_height_m": 0.14, "blade_length_m": 0.175,
    "lowest_clearance_m": 1.12, "inter_impeller_clearance_m": 1.46
  }
  // multiphase-only fields (D14) left unset in PoC: sparger {...}, outlet {...}
}
```

### Case-params schema (Part B input)

```jsonc
{
  "physics": "single_phase",            // PoC; "two_phase_euler" later
  "rpm": 90,                            // → MRF rotor angular velocity (D11)
  "viscosity_m2_s": 1.0e-6,            // → physicalProperties (D11)
  "patch_roles": {                      // mostly trivial for a closed tank
    "tankWall": "wall", "dishedBottom": "wall", "baffles": "wall",
    "shaft": "wall", "impellers": "wall", "liquidSurface": "slip"
    // multiphase (D14): "sparger": "inlet", "liquidSurface": "outlet"
  },
  "mesh": { "base_cell_m": null, "refinement_level": 2, "boundary_layers": false },
  "run":  { "end_time": 5000, "write_interval": 100, "cores": 28 }
}
```

## Build plan

1. **Finalize the two schemas** (Pydantic models + validators, incl. Rushton-ratio checks — D16).
2. **Deterministic STR builder** (parametric) → named multi-region STL. Acceptance: its output
   passes `snappyHexMesh` + `checkMesh` cleanly. *(Bake-off: CadQuery vs the contact's Salome
   recipe — winner = clean, named, snappy-meshable STL.)*
3. **LLM extraction layer**: prompt → STR-schema (validated; rejects inconsistent prompts).
4. **Part B template engine** (foamlib), generalized from `setup_twophase.py`: schema + STL →
   `0/ constant/ system/ command.sh metadata.json`, v12 modular form, MRF `fvModel`, `topoSet`
   rotor zones, computed `locationInMesh` + `blockMeshDict`.
5. **Wire meshing as a Batch step** (D9) on the Part C compute path.
6. **Integrate** into the app + Part C (three.js STL preview, schema-form UI, submit).

## Validation gates (D10)

- `checkMesh` passes (no errors; warnings triaged).
- Every dict parses (foamlib round-trip).
- **Every patch in `constant/polyMesh/boundary` has a matching entry in every `0/` field**, and
  vice versa — the #1 silent failure mode.
- All solver/scheme syntax is **v12 modular** (no `simpleFoam`-style application keys).

## Multiphase path (deferred — additive, not a rewrite)

When aeration is added, the single-phase contract **extends**:

| Aspect | Single-phase (now) | Two-phase aerated (later) |
|---|---|---|
| Solver module | `incompressibleFluid` | `multiphaseEuler` (dispersed bubbles) |
| Geometry (D5) | walls + slip lid | **adds `sparger` gas-inlet** (bottom) + **degassing outlet** (top; slip lid → outlet) |
| Fields | `U, p, k, omega, nut` | + `alpha.air`, phase fields |
| New variation | — | **aeration rate** → sparger inlet flow |

The schema is designed once (D14); the PoC simply leaves the multiphase fields unset.

## Open items to refine during planning

- Bake-off result (D4): CadQuery vs Salome — which becomes the default builder.
- Whether the contact's proven recipe is Salome-geometry-only or geometry+mesh (affects how much
  of their workflow transfers, given the OpenFOAM-meshing decision).
- Mesh sizing strategy: fixed `refinement_level` vs computed base cell size from tank dimensions.
- Whether meshing is a separate Batch job or a pre-step of the solve job.
