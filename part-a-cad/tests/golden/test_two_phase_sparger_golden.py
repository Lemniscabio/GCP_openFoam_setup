import json
import re
from pathlib import Path

import pytest

from str_cad.builder import build_from_schema_file
from str_cad.ofcase.build import build_case
from str_cad.ofcase.caseparams import CaseParams
from str_cad.ofcase.two_phase.geometry import sparger_inlet_velocity
from str_cad.schema import STRParams


def _case_params():
    return CaseParams.model_validate({"rpm": 100, "viscosity_m2_s": 1e-6})


def _load_twophase_sp():
    schema = json.loads(Path("examples/reactor_twophase.json").read_text())
    return STRParams.model_validate(schema)


def _patch_block(text, patch_name):
    match = re.search(
        rf"^\s+{re.escape(patch_name)}\s*\{{(?P<body>.*?)^\s+\}}",
        text,
        re.M | re.S,
    )
    assert match, f"missing patch block: {patch_name}"
    return match.group("body")


def _build_two_phase_case(tmp_path):
    geo_dir = build_from_schema_file(
        Path("examples/reactor_twophase.json"), tmp_path / "geo"
    )
    return build_case(_case_params(), geo_dir, tmp_path / "case")


def _build_single_phase_case(tmp_path):
    geo_dir = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    return build_case(_case_params(), geo_dir, tmp_path / "case")


def test_sparger_inlet_velocity_sanity():
    sp = _load_twophase_sp()
    u_super = sparger_inlet_velocity(sp)
    assert 0.08 < u_super < 0.20


def test_two_phase_sparger_case_contract(tmp_path):
    sp = _load_twophase_sp()
    u_super = sparger_inlet_velocity(sp)
    case_dir = _build_two_phase_case(tmp_path)

    topo_set = (case_dir / "system/topoSetDict").read_text()
    assert "spargerFaces" in topo_set
    assert "patchToFace" in topo_set
    assert "cylinderToFace" in topo_set
    assert "dishedBottom" in topo_set
    assert "cellZoneSet" in topo_set
    assert "rotor" in topo_set

    create_patch = (case_dir / "system/createPatchDict").read_text()
    assert "name            sparger" in create_patch
    assert "set             spargerFaces" in create_patch

    u_gas = (case_dir / "0/U.gas").read_text()
    sparger_u = _patch_block(u_gas, "sparger")
    assert "fixedValue" in sparger_u
    assert f"(0 0 {u_super:.5f})" in sparger_u

    alpha_gas = (case_dir / "0/alpha.gas").read_text()
    sparger_alpha = _patch_block(alpha_gas, "sparger")
    assert "fixedValue" in sparger_alpha
    assert "uniform 1" in sparger_alpha

    p_rgh = (case_dir / "0/p_rgh").read_text()
    sparger_p_rgh = _patch_block(p_rgh, "sparger")
    assert "fixedFluxPressure" in sparger_p_rgh

    command = (case_dir / "command.sh").read_text()
    topo_idx = command.index("topoSet")
    create_patch_idx = command.index("createPatch -overwrite")
    set_fields_idx = command.index("setFields")
    assert topo_idx < create_patch_idx < set_fields_idx


def test_single_phase_case_unchanged_by_sparger(tmp_path):
    case_dir = _build_single_phase_case(tmp_path)

    assert not (case_dir / "system/createPatchDict").exists()

    u = (case_dir / "0/U").read_text()
    assert "sparger" not in u