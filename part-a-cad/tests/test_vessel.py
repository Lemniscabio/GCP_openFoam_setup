import json
import math
from pathlib import Path

import pytest

from str_cad.geometry.internals import build_impellers
from str_cad.schema import STRParams
from str_cad.schema import SchemaError
from str_cad.geometry.vessel import build_vessel_shell
from tests.test_schema import _valid


def _reactor_30kl_with(**overrides):
    data = json.loads(Path("examples/reactor_30kl.json").read_text())
    for section, values in overrides.items():
        data[section].update(values)
    return STRParams.model_validate(data)


def test_vessel_bounding_box_matches_diameter_and_liquid_height():
    p = STRParams.model_validate(_valid())
    shell = build_vessel_shell(p)
    bb = shell.val().BoundingBox()
    assert math.isclose(bb.xlen, p.tank.diameter_m, rel_tol=0.02)
    assert math.isclose(bb.ylen, p.tank.diameter_m, rel_tol=0.02)
    assert bb.zmax <= p.liquid.height_m + 1e-6

def test_vessel_volume_close_to_liquid_volume():
    p = STRParams.model_validate(_valid())
    shell = build_vessel_shell(p)
    r = p.tank.diameter_m / 2
    cyl_vol = math.pi * r**2 * p.liquid.height_m
    assert 0.9 * cyl_vol <= shell.val().Volume() <= 1.3 * cyl_vol


def test_flat_bottom_has_no_dished_head():
    flat = _reactor_30kl_with(tank={"bottom": "flat"})
    flat_shell = build_vessel_shell(flat)
    flat_bb = flat_shell.val().BoundingBox()

    assert flat_shell.val().isValid()
    assert flat_bb.zmin >= -1e-6

    dished = _reactor_30kl_with(tank={"bottom": "dished"})
    dished_shell = build_vessel_shell(dished)
    dished_bb = dished_shell.val().BoundingBox()

    assert dished_bb.zmin < -0.5 * (dished.tank.diameter_m / 2)


def test_unknown_bottom_raises():
    p = _reactor_30kl_with(tank={"bottom": "conical"})

    with pytest.raises(SchemaError):
        build_vessel_shell(p)


def test_rushton_respects_blade_count():
    six_blades = _reactor_30kl_with(impellers={"blades": 6})
    three_blades = _reactor_30kl_with(impellers={"blades": 3})

    six_blade_volume = build_impellers(six_blades)[0].val().Volume()
    three_blade_volume = build_impellers(three_blades)[0].val().Volume()

    assert six_blade_volume > three_blade_volume
