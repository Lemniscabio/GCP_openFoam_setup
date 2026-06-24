import math
import re
from pathlib import Path

import pytest

from str_cad.builder import build_from_schema_file
from str_cad.ofcase.build import build_case
from str_cad.ofcase.caseparams import CaseParams


def _build_single_phase_case(tmp_path):
    geo = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    cp = CaseParams.model_validate({"rpm": 100, "viscosity_m2_s": 1e-6})
    return build_case(cp, geo, tmp_path / "case")


def _patch_block(text, patch_name):
    match = re.search(rf"^\s+{re.escape(patch_name)}\s*\{{(?P<body>.*?)^\s+\}}", text, re.M | re.S)
    assert match, f"missing patch block: {patch_name}"
    return match.group("body")


def test_single_phase_case_matches_golden_physics_contract(tmp_path):
    case = _build_single_phase_case(tmp_path)

    physical_properties = (case / "constant/physicalProperties").read_text()
    assert re.search(
        r"nu\s+\[0 2 -1 0 0 0 0\]\s+1e-06;",
        physical_properties,
    )

    momentum_transport = (case / "constant/momentumTransport").read_text()
    assert "simulationType RAS;" in momentum_transport
    assert "model           kEpsilon;" in momentum_transport
    assert "turbulence      on;" in momentum_transport

    mrf_properties = (case / "constant/MRFProperties").read_text()
    assert "cellZone    rotor;" in mrf_properties
    assert "omega       100 [rpm];" in mrf_properties

    u = (case / "0/U").read_text()
    assert "type MRFnoSlip;" in _patch_block(u, "impellers")
    shaft = _patch_block(u, "shaft")
    assert "type rotatingWallVelocity;" in shaft
    omega = re.search(r"omega\s+constant\s+([0-9.eE+-]+);", shaft)
    assert omega
    assert float(omega.group(1)) == pytest.approx(100 * 2 * math.pi / 60)
    assert "type noSlip;" in _patch_block(u, "tankWall")
    assert "type noSlip;" in _patch_block(u, "baffles")
    assert "type slip;" in _patch_block(u, "liquidSurface")

    control_dict = (case / "system/controlDict").read_text()
    assert "application     foamRun;" in control_dict
    assert "solver          incompressibleFluid;" in control_dict
