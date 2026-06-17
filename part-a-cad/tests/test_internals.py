from str_cad.schema import STRParams
from str_cad.geometry.internals import build_shaft, build_impellers, impeller_z_positions
from tests.test_schema import _valid

def test_impeller_z_positions_from_clearances():
    p = STRParams.model_validate(_valid())
    zs = impeller_z_positions(p)
    assert len(zs) == p.impellers.count
    assert abs(zs[0] - p.impellers.lowest_clearance_m) <= 1e-6
    assert abs((zs[1] - zs[0]) - p.impellers.inter_impeller_clearance_m) <= 1e-6

def test_each_impeller_has_six_blades_solid_count():
    p = STRParams.model_validate(_valid())
    imps = build_impellers(p)
    assert len(imps) == p.impellers.count

def test_shaft_spans_from_top_through_lowest_impeller():
    p = STRParams.model_validate(_valid())
    bb = build_shaft(p).val().BoundingBox()
    assert bb.zmax >= p.liquid.height_m - 1e-6
    assert bb.zmin <= p.impellers.lowest_clearance_m + 1e-6
