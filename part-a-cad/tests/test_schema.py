import math
import json
from pathlib import Path

import pytest

from str_cad.ofcase.mrf import rotor_cylinders
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

def test_physics_defaults_to_single_phase():
    p = STRParams.model_validate(_valid())
    assert p.physics == "single_phase"

def test_physics_accepts_two_phase():
    spec = _valid()
    spec["physics"] = "two_phase"
    spec["operating"] = {"rpm": 120, "gas_flow_vvm": 0.5}
    p = STRParams.model_validate(spec)
    assert p.physics == "two_phase"

def test_two_phase_requires_gas_input():
    spec = _valid()
    spec["physics"] = "two_phase"
    spec["operating"] = {"rpm": 120}
    with pytest.raises(SchemaError, match="two_phase.*gas_flow_vvm.*sparger"):
        STRParams.model_validate(spec)

@pytest.mark.parametrize(
    "operating",
    [
        {"sparger": {}},
        {"gas_flow_vvm": 0},
        {"gas_flow_vvm": -1},
    ],
)
def test_two_phase_requires_usable_gas_input(operating):
    spec = _valid()
    spec["physics"] = "two_phase"
    spec["operating"] = operating
    with pytest.raises(SchemaError, match="two_phase.*usable gas input"):
        STRParams.model_validate(spec)

def test_two_phase_accepts_sparger_ring_diameter():
    spec = _valid()
    spec["physics"] = "two_phase"
    spec["operating"] = {"sparger": {"ring_diameter_m": 0.5}}
    p = STRParams.model_validate(spec)
    assert p.operating.sparger.ring_diameter_m == pytest.approx(0.5)

def test_two_phase_example_validates():
    spec = json.loads(Path("examples/reactor_twophase.json").read_text())
    p = STRParams.model_validate(spec)
    assert p.physics == "two_phase"

def test_two_phase_example_geometry_matches_oracle():
    spec = json.loads(Path("examples/reactor_twophase.json").read_text())
    p = STRParams.model_validate(spec)

    assert p.tank.diameter_m == 2.09
    assert p.liquid.height_m == 6.55
    assert p.impellers.count == 4
    assert p.operating.rpm == 100

def test_two_phase_missing_operating_raises():
    spec = _valid()
    spec["physics"] = "two_phase"
    with pytest.raises(SchemaError, match="two_phase physics requires an `operating` block"):
        STRParams.model_validate(spec)

def test_derived_reports_correlations():
    spec = json.loads(Path("examples/reactor_30kl.json").read_text())
    spec["impellers"].pop("blade_length_m")
    spec["impellers"].pop("blade_height_m")
    p = STRParams.model_validate(spec)
    derived = p.derived()
    D = p.impeller_diameter_m

    assert {
        "blade_length_m",
        "blade_height_m",
        "shaft_radius_m",
        "hub_radius_m",
        "baffle_width_m",
        "mrf_rotor_radius_m",
        "mesh_refinement_radius_m",
    } <= derived.keys()
    assert derived["blade_length_m"] == pytest.approx(D / 4)
    assert derived["blade_height_m"] == pytest.approx(D / 5)
    assert derived["shaft_radius_m"] == pytest.approx(max(0.03, D / 20))
    assert derived["hub_radius_m"] == pytest.approx(D / 12)
    assert derived["baffle_width_m"] == pytest.approx(p.baffles.width_m)
    assert derived["mesh_refinement_radius_m"] == pytest.approx(0.65 * D)

    override_spec = json.loads(Path("examples/reactor_30kl.json").read_text())
    override_p = STRParams.model_validate(override_spec)
    override_d = override_p.impeller_diameter_m
    override_spec["impellers"]["blade_length_m"] = 1.09 * (override_d / 4)
    override_p = STRParams.model_validate(override_spec)
    assert override_p.derived()["blade_length_m"] == pytest.approx(
        override_spec["impellers"]["blade_length_m"]
    )

def test_baffle_width_omitted_fills_standard_width_and_derived_reports_it():
    spec = _valid()
    spec["baffles"].pop("width_m")
    p = STRParams.model_validate(spec)

    assert p.baffles.width_m == pytest.approx(p.tank.diameter_m / 12)
    assert p.derived()["baffle_width_m"] == pytest.approx(p.tank.diameter_m / 12)

def test_mrf_rotor_radius_matches_writer():
    spec = json.loads(Path("examples/reactor_30kl.json").read_text())
    p = STRParams.model_validate(spec)
    writer_radius = rotor_cylinders(p)[0]["radius"]

    assert p.derived()["mrf_rotor_radius_m"] == pytest.approx(writer_radius)
