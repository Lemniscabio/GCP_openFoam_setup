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

def test_fluid_domain_internals_are_subtracted():
    from str_cad.geometry.vessel import build_vessel_shell
    p = STRParams.model_validate(_valid())
    from str_cad.geometry.assembly import build_fluid_solid
    assert build_fluid_solid(p).Volume() < build_vessel_shell(p).val().Volume()
