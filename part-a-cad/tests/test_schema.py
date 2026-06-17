import math
import pytest
from str_cad.schema import STRParams, SchemaError

def _valid():
    return {
        "family": "stirred_tank_reactor",
        "tank": {"diameter_m": 2.09, "height_m": 9.6, "bottom": "dished"},
        "liquid": {"height_m": 6.55},
        "baffles": {"count": 4, "width_m": 0.167, "height_m": 7.5, "arrangement": "symmetric"},
        "shaft": {"central": True},
        "impellers": {"count": 4, "type": "rushton", "blades": 6,
                      "diameter_ratio": 1/3, "blade_height_m": 0.14, "blade_length_m": 0.175,
                      "lowest_clearance_m": 1.12, "inter_impeller_clearance_m": 1.46},
    }

def test_valid_schema_parses():
    p = STRParams.model_validate(_valid())
    assert p.impellers.count == 4

def test_impeller_diameter_derived_from_ratio():
    p = STRParams.model_validate(_valid())
    assert math.isclose(p.impeller_diameter_m, 2.09/3, rel_tol=1e-6)

def test_rushton_blade_dims_validated_against_standard_ratios():
    p = STRParams.model_validate(_valid())
    D = p.impeller_diameter_m
    assert abs(p.impellers.blade_length_m - D/4) <= 0.1 * (D/4)
    assert abs(p.impellers.blade_height_m - D/5) <= 0.1 * (D/5)

def test_liquid_height_must_not_exceed_tank_height():
    bad = _valid(); bad["liquid"]["height_m"] = 12.0
    with pytest.raises(SchemaError):
        STRParams.model_validate(bad)

def test_impellers_must_fit_under_liquid_height():
    bad = _valid(); bad["impellers"]["inter_impeller_clearance_m"] = 3.0
    with pytest.raises(SchemaError):
        STRParams.model_validate(bad)

def test_blade_dims_far_from_standard_rejected():
    bad = _valid(); bad["impellers"]["blade_length_m"] = 0.5
    with pytest.raises(SchemaError):
        STRParams.model_validate(bad)
