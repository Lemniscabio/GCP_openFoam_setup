from str_cad.schema import STRParams
from str_cad.geometry.assembly import build_fluid_domain, REGION_NAMES
from tests.test_schema import _valid

EXPECTED = {"tankWall", "dishedBottom", "baffles", "shaft", "impellers", "liquidSurface"}

def test_region_names_are_the_locked_contract():
    assert set(REGION_NAMES) == EXPECTED

def test_assembly_returns_a_surface_per_region():
    p = STRParams.model_validate(_valid())
    domain = build_fluid_domain(p)
    assert set(domain.keys()) == EXPECTED
    for name, shape in domain.items():
        assert shape.Area() > 0, name

    assert domain["baffles"].Area() > 1.0


def test_flat_bottom_fills_dished_bottom_region():
    # Regression: a flat bottom sits at z~0 (no curved head below 0). The classifier
    # must still route the bottom disc into the dishedBottom region, else its STL is
    # empty and meshing fails ("string is not a file: .../dishedBottom.stl").
    spec = _valid()
    spec["tank"]["bottom"] = "flat"
    domain = build_fluid_domain(STRParams.model_validate(spec))
    assert set(domain.keys()) == EXPECTED
    for name, shape in domain.items():
        assert shape.Area() > 0, name


def test_fluid_domain_internals_are_subtracted():
    from str_cad.geometry.vessel import build_vessel_shell
    p = STRParams.model_validate(_valid())
    from str_cad.geometry.assembly import build_fluid_solid
    assert build_fluid_solid(p).Volume() < build_vessel_shell(p).val().Volume()
