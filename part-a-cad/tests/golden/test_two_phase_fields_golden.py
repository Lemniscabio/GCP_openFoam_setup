import json
import math
import re
from pathlib import Path

import pytest

from str_cad.geometry.assembly import REGION_NAMES
from str_cad.ofcase.caseparams import CaseParams
from str_cad.ofcase.two_phase.fields import write_initial_fields_two_phase
from str_cad.schema import STRParams


EXPECTED_FIELDS = {
    "U.liquid": "volVectorField",
    "U.gas": "volVectorField",
    "T.liquid": "volScalarField",
    "T.gas": "volScalarField",
    "alpha.gas": "volScalarField",
    "alpha.liquid": "volScalarField",
    "alphat.liquid": "volScalarField",
    "k.liquid": "volScalarField",
    "epsilon.liquid": "volScalarField",
    "nut.liquid": "volScalarField",
    "p": "volScalarField",
    "p_rgh": "volScalarField",
}


def _patch_block(text, patch_name):
    match = re.search(
        rf"^\s+{re.escape(patch_name)}\s*\{{(?P<body>.*?)^\s+\}}",
        text,
        re.M | re.S,
    )
    assert match, f"missing patch block: {patch_name}"
    return match.group("body")


def _write_two_phase_fields(tmp_path):
    schema = json.loads(Path("examples/reactor_twophase.json").read_text())
    STRParams.model_validate(schema)
    cp = CaseParams.model_validate({"rpm": 100, "viscosity_m2_s": 1e-6})
    return write_initial_fields_two_phase(None, cp, REGION_NAMES, tmp_path / "0")


def test_two_phase_initial_fields_exist_with_headers(tmp_path):
    out = _write_two_phase_fields(tmp_path)

    for field, field_class in EXPECTED_FIELDS.items():
        path = out / field
        assert path.exists(), f"missing field: {field}"
        text = path.read_text()
        assert f"class       {field_class};" in text
        assert f"object      {field};" in text


def test_two_phase_velocity_boundary_contract(tmp_path):
    out = _write_two_phase_fields(tmp_path)

    u_liquid = (out / "U.liquid").read_text()
    assert "type noSlip;" in _patch_block(u_liquid, "tankWall")
    shaft = _patch_block(u_liquid, "shaft")
    assert "type rotatingWallVelocity;" in shaft
    omega = re.search(r"omega\s+constant\s+([0-9.eE+-]+);", shaft)
    assert omega
    assert float(omega.group(1)) == pytest.approx(100 * 2 * math.pi / 60)
    assert "type MRFnoSlip;" in _patch_block(u_liquid, "impellers")
    assert "type pressureInletOutletVelocity;" in _patch_block(
        u_liquid,
        "liquidSurface",
    )

    u_gas = (out / "U.gas").read_text()
    assert "type slip;" in _patch_block(u_gas, "tankWall")


def test_two_phase_scalar_boundary_contract(tmp_path):
    out = _write_two_phase_fields(tmp_path)

    alpha_gas = (out / "alpha.gas").read_text()
    alpha_top = _patch_block(alpha_gas, "liquidSurface")
    assert "type inletOutlet;" in alpha_top
    assert "phi phi.gas;" in alpha_top
    assert "type zeroGradient;" in _patch_block(alpha_gas, "tankWall")

    p_rgh = (out / "p_rgh").read_text()
    assert "type prghPressure;" in _patch_block(p_rgh, "liquidSurface")
    assert "type fixedFluxPressure;" in _patch_block(p_rgh, "tankWall")

    k_liquid = (out / "k.liquid").read_text()
    assert "type kqRWallFunction;" in _patch_block(k_liquid, "tankWall")
    assert "type zeroGradient;" in _patch_block(k_liquid, "liquidSurface")


def test_two_phase_p_is_calculated_on_every_patch(tmp_path):
    out = _write_two_phase_fields(tmp_path)
    p = (out / "p").read_text()

    for patch in REGION_NAMES:
        assert "type calculated;" in _patch_block(p, patch)
