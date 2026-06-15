import math
from str_cad.schema import STRParams
from str_cad.geometry.vessel import build_vessel_shell
from tests.test_schema import _valid

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
