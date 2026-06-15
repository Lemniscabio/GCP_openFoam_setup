from str_cad.schema import STRParams
from str_cad.geometry.baffles import build_baffles
from tests.test_schema import _valid

def test_four_baffles_returned():
    p = STRParams.model_validate(_valid())
    baffles = build_baffles(p)
    assert len(baffles) == p.baffles.count

def test_baffles_are_symmetric_at_90_degrees():
    p = STRParams.model_validate(_valid())
    centers = [b.val().Center() for b in build_baffles(p)]
    radii = [round((c.x**2 + c.y**2) ** 0.5, 3) for c in centers]
    assert len(set(radii)) == 1

def test_baffle_height_matches_schema():
    p = STRParams.model_validate(_valid())
    b0 = build_baffles(p)[0].val().BoundingBox()
    assert abs(b0.zlen - p.baffles.height_m) <= 0.02 * p.baffles.height_m
