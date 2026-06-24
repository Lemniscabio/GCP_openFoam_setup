# part-a-cad

part-a-cad turns a JSON reactor spec into a complete OpenFOAM stirred-tank-reactor case (single-phase OR two-phase Euler-Euler), with a variations sweep and local/on-server verification. The hand-built ../singlephase and ../twophase dirs are the reference oracles.

## 1. Input spec (3 tiers)

**Tier 1 (required)**

- `family`
- `physics`: `"single_phase"` or `"two_phase"`
- `tank`: `{ diameter_m, height_m, bottom: "dished" | "flat" }`
- `liquid`: `{ height_m }`
- `baffles`: `{ count, height_m, arrangement, width_m? }` (width_m defaults to T/12)
- `shaft`: `{ central }`
- `impellers`: `{ count, type: "rushton", blades, diameter_ratio, lowest_clearance_m, inter_impeller_clearance_m, blade_height_m?, blade_length_m? }`
- `operating`: `{ rpm, ... }`; for `two_phase` also a gas input: `gas_flow_vvm > 0` **or** `sparger: { ring_diameter_m }`

**Tier 2 (auto-filled correlations)** — overridable; all logged via `STRParams.derived()` into case `metadata.json`:

- `blade_length_m = D/4`
- `blade_height_m = D/5`
- `shaft_radius = max(0.03, D/20)`
- `hub_radius = D/12`
- `baffle_width = T/12`
- `mrf_rotor_radius = 0.55D`
- `mesh_refinement_radius = 0.65D`

See `examples/reactor_30kl.json` (single-phase) and `examples/reactor_twophase.json` (two-phase).

## 2. Generate a case (Python API)

```python
import json
from str_cad.schema import STRParams
from str_cad.export import export_geometry
from str_cad.ofcase.build import build_case
from str_cad.ofcase.caseparams import CaseParams

sp = STRParams.model_validate(json.load(open("examples/reactor_30kl.json")))
export_geometry(sp, "out/geo")                       # writes STLs + str-params.json
cp = CaseParams.model_validate({"rpm": 100, "viscosity_m2_s": 1e-6,
                                "run": {"verify": True, "verify_steps": 5}})
build_case(cp, "out/geo", "out")                     # full OF case; dispatches on sp.physics
```

Swap to `examples/reactor_twophase.json` for a two-phase (multiphaseEuler) case — same calls.

## 3. Variations sweep

```python
from str_cad.variations import generate_sweep
base = json.load(open("examples/reactor_30kl.json")); base["run"] = {"verify": True, "verify_steps": 5}
runs = generate_sweep(base, {"operating.rpm": [60, 100, 180]}, "out/sweep")
# builds out/sweep/<n>/ per combo + runs_map.json (invalid combos go to runs_map["_skipped"])
```

Axes are dotted paths into the spec (`operating.rpm`, `run.viscosity_m2_s`, `liquid.height_m`, `operating.gas_flow_vvm`).

## 4. Verify locally on OpenFOAM (docker)

Image `kartikeyattri/openfoam:12` (entrypoint `/bin/bash -c`, single-arg command, `--platform linux/amd64`).

Serial smoke run:

```bash
docker run --rm --platform linux/amd64 -v "$PWD/out":/case kartikeyattri/openfoam:12 \
  'cd /case && blockMesh >log.blockMesh 2>&1 && snappyHexMesh -overwrite >log.snappyHexMesh 2>&1 \
   && topoSet >log.topoSet 2>&1 && foamRun >log.foamRun 2>&1'   # add `setFields >log.setFields 2>&1 &&` before foamRun for two-phase
```

Then judge the run:

```python
from str_cad.verify.harness import parse_smoke_log
r = parse_smoke_log(open("out/log.blockMesh").read()+open("out/log.snappyHexMesh").read()+open("out/log.foamRun").read())
print(r.ok)   # True when meshed + fields read + time advanced + no FOAM FATAL
```

Note rpm/nu/gas variations don't change geometry → reuse `constant/polyMesh` across a sweep to skip re-meshing.

## 5. On-server (GCP) verification

`str_cad.verify.harness.submit_smoke(case_dir, project="cfd-lemnisca")` uploads+runs via the `of` CLI and parses logs into a `SmokeResult`.

(Caveat: `_default_log_fetcher` GCS path is unverified against the live results layout — confirm before relying on it.)

## 6. Tests

`.venv/bin/python -m pytest -q` (94 tests). Golden tests in `tests/golden/` assert generated dicts/fields against the oracles.
