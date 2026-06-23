from __future__ import annotations

import copy
import itertools
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from str_cad.export import export_geometry
from str_cad.ofcase.build import build_case
from str_cad.ofcase.caseparams import CaseParams, Run
from str_cad.schema import STRParams, SchemaError


def expand_variations(base_spec: dict, axes: dict[str, list]) -> list[dict]:
    axis_items = list(axes.items())
    if not axis_items:
        return [copy.deepcopy(base_spec)]

    specs = []
    paths = [path for path, _values in axis_items]
    value_lists = [values for _path, values in axis_items]
    for combo in itertools.product(*value_lists):
        spec = copy.deepcopy(base_spec)
        for path, value in zip(paths, combo):
            _set_dotted_path(spec, path, value)
        specs.append(spec)
    return specs


def generate_sweep(
    base_spec: dict, axes: dict[str, list], out_root: str | Path
) -> dict[str, Any]:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    runs_map: dict[str, Any] = {"_skipped": []}
    for index, spec in enumerate(expand_variations(base_spec, axes)):
        try:
            sp = STRParams.model_validate(spec)
        except SchemaError as exc:
            runs_map["_skipped"].append({"index": index, "reason": str(exc)})
            continue

        case_dir = out_root / str(index)
        geo_dir = case_dir / "geometry-src"
        export_geometry(sp, geo_dir)

        params = _resolved_case_params(spec, sp)
        case_params = CaseParams.model_validate(params)
        build_case(case_params, geo_dir, case_dir)

        params_json = case_params.model_dump(mode="json")
        params_json["derived"] = sp.derived()
        (case_dir / "params.json").write_text(json.dumps(params_json, indent=2))
        runs_map[str(index)] = params_json

    (out_root / "runs_map.json").write_text(json.dumps(runs_map, indent=2))
    return runs_map


def _set_dotted_path(spec: dict, dotted_path: str, value: Any) -> None:
    if not dotted_path:
        raise ValueError("axis path must not be empty")

    current = spec
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        next_value = current.get(part)
        if next_value is None:
            next_value = {}
            current[part] = next_value
        if not isinstance(next_value, dict):
            raise ValueError(f"cannot create nested path below non-dict key: {part}")
        current = next_value
    current[parts[-1]] = value


def _resolved_case_params(spec: Mapping[str, Any], sp: STRParams) -> dict[str, Any]:
    run_spec = spec.get("run", {})
    if run_spec is None:
        run_spec = {}
    if not isinstance(run_spec, Mapping):
        raise ValueError("run must be a mapping when present")

    operating = spec.get("operating") or {}
    if not isinstance(operating, Mapping):
        raise ValueError("operating must be a mapping when present")

    run_keys = {"cores", "end_time", "write_interval", "verify", "verify_steps"}
    run = Run.model_validate({key: run_spec[key] for key in run_keys if key in run_spec})
    return {
        "rpm": operating["rpm"],
        "viscosity_m2_s": run_spec.get("viscosity_m2_s", 1e-6),
        "run": run.model_dump(mode="json"),
    }
