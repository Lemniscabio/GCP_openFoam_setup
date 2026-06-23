# Parametric STR Pipeline — Design

**Date:** 2026-06-23
**Status:** Approved for planning
**Owner:** Kartikey (liable orchestrator: Claude/Opus; implementer: codex; reviewer: grok)

## Problem

The repo is a makeshift end-to-end pipeline: 3D geometry generation → OpenFOAM case
generation → run on GCP. The GCP run layer (`phase3-run-app/`) is solid. The geometry
and case-generation layers are **narrow and disconnected**:

- `part-a-cad/` is a clean, tested generative module, but only does **single-phase**,
  only builds a fixed Rushton-ish impeller (ignores `impellers.type`, `tank.bottom`,
  `baffles.arrangement`), and is decoupled from the cases actually run.
- `singlephase/generate_cases.py` is a brittle **regex sweeper** over a *frozen* STL
  geometry with hardcoded constants (`TANK_RADIUS=1.04`, fixed impeller z-positions).
  It varies only rpm/nu/fill — never geometry.
- `twophase/` is a fully hand-built Euler-Euler gas/liquid case with **no generator and
  no geometry generation** at all.

So "geometry generation → case generation with variations" is half-built for
single-phase and absent for two-phase.

## Goal

A **parametric stirred-tank-reactor (STR) generator** that takes a JSON spec and produces
a complete, runnable OpenFOAM case — single-phase **or** two-phase — with a variations
(sweep) layer. The existing `singlephase/` and `twophase/` directories become the two
**reference members + validation oracles**. Architecture is **family-pluggable** so new
reactor families / physics modes drop in later without rewriting the core.

### Non-goals (YAGNI)

- Arbitrary/unbounded reactor CAD (heat exchangers, packed beds, tubular). Scope is the
  STR family, built so new families *can* be added later.
- Full physical/numerical validation against experimental data. Verification is a
  structural-validity + short on-server smoke run (see Verification).
- Reworking the GCP run layer (`phase3-run-app/`) — it is reused, not changed.

## Success criteria (exit objective)

> For **single-phase** AND **two-phase**, the pipeline goes `JSON spec → geometry →
> OpenFOAM case → structurally valid → mesh + run N timesteps green on GCP`, proven on a
> **base case plus a couple of variations** per physics type (e.g. 2–3 points across the
> rpm/nu/fill or gas-flow/phase-frac axes), with the existing `singlephase/`/`twophase/`
> dirs matched as oracles.

"100% accuracy" is operationalized as:
1. **Structural validity** — correct OF dict syntax, all required files present, mesh
   checks (`checkMesh`-level) pass.
2. **Runs on-server** — case meshes and advances a few solver timesteps to completion
   with exit 0 on GCP (no local OpenFOAM exists).

Proven on a **base case plus a couple of variations** per physics type; the remaining
sweep points inherit the result.

## Input model (3 tiers)

Not hardcoded. The generator derives sensible values and logs every derived value to
`metadata.json`.

- **Tier 1 — Required** (defines the reactor): physics mode (`single_phase`|`two_phase`);
  tank diameter/height/bottom; liquid fill; impeller type/count/diameter_ratio; rpm; for
  two-phase: gas superficial velocity / sparger inlet + per-phase fluid properties.
- **Tier 2 — Derived by STR correlations** (omittable, auto-filled, overridable): blade
  length ≈ D/4, blade height ≈ D/5, shaft radius ≈ D/20, hub radius ≈ D/12, baffle width
  ≈ T/12 (count 4, full-height), standard clearances, MRF rotor-zone radius, mesh cell
  sizing, verify-run timestep/endTime.
- **Tier 3 — Advanced overrides**: everything in Tier 2 plus solver/scheme/turbulence
  knobs.

Every derived value is written to `metadata.json` — no silent magic.

## Architecture

Unify on `part-a-cad` (Approach A). The authored reference cases are **oracles** for the
`ofcase` writers, kept as clean generators (not text templates).

```
part-a-cad/str_cad/
  schema.py            # + physics mode, two-phase fields, correlation/default engine
  geometry/
    families/str/      # stirred-tank family (today's code, made truly parametric)
      vessel, bottom (dished|flat), shaft, baffles
      impellers/       # plugin per type: rushton, pbt, ... (dispatch on impellers.type)
    registry.py        # family registry -> "add a reactor type" = drop a module here
  ofcase/
    single_phase/      # today's writers
    two_phase/         # NEW: phaseProperties, alpha/U.gas/U.liquid, per-phase
                       #      momentumTransport & physicalProperties, setFieldsDict,
                       #      mapFieldsDict
    common/            # shared system dicts, MRF, topoSet, fields base
  variations.py        # sweep layer (rpm/nu/fill | gas-flow/phase-frac); replaces the
                       # regex sweeper in singlephase/generate_cases.py
  verify/
    harness.py         # submit one representative case per physics to GCP, mesh + run N
                       # steps, parse logs for success
tests/
  golden/              # assertions vs singlephase/ + twophase/ reference oracles
```

**Pluggability principle:** adding a reactor type or physics mode = adding a module behind
a registry; never editing the pipeline core. The two reference cases are fixtures, not
codepaths.

### Data flow

`JSON spec → STRParams (schema, correlations) → geometry.build (family registry) → STL
export → ofcase.build (physics dispatch: single|two-phase) → variations expansion →
verify.harness (on-server smoke run on GCP)`.

## Orchestration model (the loop)

| Agent | Role |
|---|---|
| **Claude (Opus)** | Orchestrator + liable reviewer. Owns backlog, writes task specs, reviews every diff, runs/reads verification, decides done, commits. Writes **no** production code. |
| **codex** (`codex exec`) | Sole implementer. All Python: geometry, schema, ofcase, variations, verify, tests. Per-task spec + acceptance criteria. |
| **grok** (headless) | Independent domain critic: (a) OF-v12 correctness of generated dicts; (b) adversarial diff vs golden references. Findings only — never edits the repo. |

grok reviews rather than co-implements so an *independent* model adversarially checks the
subtle CFD setup, giving errors uncorrelated with the implementer.

### One loop iteration

1. Pick top backlog slice; write codex a precise spec (files, oracle, acceptance tests).
2. codex implements + writes/extends tests.
3. Run tests + structural validation locally (no OF needed).
4. grok reviews diff (OF12 correctness + golden fidelity) → findings.
5. Reconcile; material findings → back to codex.
6. If slice makes a case runnable → on-server smoke verify.
7. Review evidence → mark done → commit → next slice.

Self-paced loop (codex/grok/GCP runs are variable length), one backlog item per iteration,
until the exit objective is met.

## Verification (on-server)

No local OpenFOAM → reuse `phase3-run-app`'s existing Batch path. Verification is a
**smoke run**, not a full solve:

- A `verify` controlDict override sets a tiny `endTime` / few timesteps + minimal write.
- Pipeline: `blockMesh → snappyHexMesh → createPatch → topoSet → decomposePar →
  foamRun (N steps) → reconstructPar`.
- Success = exit 0 + expected log markers (mesh OK, fields read, time advanced).
- Failures feed back as the error signal codex fixes.
- Run on one single-phase + one two-phase base case plus a couple of variations each.

**Target GCP project: `cfd-lemnisca`** (bucket `cfd-lemnisca-cases`, region `us-central1`).
The active local gcloud config is `test-openfoam` (`project-688a4c78-…`), so the harness
must explicitly target `cfd-lemnisca` rather than relying on the ambient default.

## Backlog (ordered)

1. **Schema v2** — physics mode, two-phase fields, correlation/default engine, metadata
   logging. Oracle: both reference JSONs.
2. **Geometry** — STR family truly parametric + impeller-type registry; STL export
   validity. Oracle: existing STLs (mesh-ability).
3. **ofcase single-phase** — reconcile generated dicts vs `singlephase/` oracle; structured
   variations replace the regex sweeper.
4. **ofcase two-phase** — new writers vs `twophase/` oracle.
5. **verify/harness** — on-server smoke-run submission + log parsing.
6. **End-to-end green** — base case + a couple of variations per physics verified on-server.

## Risks

- **Generated geometry meshes worse than authored STLs** — mitigate by validating STL
  export + mesh-ability against the authored geometry early (backlog item 2).
- **Two-phase dict fidelity** — Euler-Euler setup is subtle; grok adversarial review +
  golden diff against `twophase/` mitigates.
- **GCP project ambiguity** — resolved: verification targets `cfd-lemnisca` explicitly,
  not the ambient `test-openfoam` config.
- **On-server verify cost/latency** — kept to smoke runs (few timesteps), one case per
  physics.

## Testing

- Unit tests per module (codex writes alongside implementation).
- Golden tests (`tests/golden/`) diff generated dicts/geometry against the reference cases.
- Structural validation gate before any on-server run.
- On-server smoke run as the final acceptance signal per physics type.
