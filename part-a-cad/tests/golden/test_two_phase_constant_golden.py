import re
from types import SimpleNamespace

from str_cad.ofcase.two_phase.physics import (
    write_gravity,
    write_momentum_transport_gas,
    write_momentum_transport_liquid,
    write_phase_properties,
    write_physical_properties_gas,
    write_physical_properties_liquid,
)


def test_phase_properties_matches_two_phase_constant_contract(tmp_path):
    path = write_phase_properties(SimpleNamespace(), tmp_path / "constant/phaseProperties")
    text = path.read_text()

    assert "type basicMultiphaseSystem;" in text
    assert "phases (gas liquid);" in text
    assert re.search(
        r"gas\s*\{.*type\s+pureIsothermalPhaseModel;.*diameterModel\s+constant;",
        text,
        re.S,
    )
    assert re.search(
        r"liquid\s*\{.*type\s+pureIsothermalPhaseModel;.*diameterModel\s+constant;",
        text,
        re.S,
    )
    assert "SchillerNaumann" in text
    assert "Burns" in text


def test_physical_properties_gas_matches_two_phase_constant_contract(tmp_path):
    path = write_physical_properties_gas(SimpleNamespace(), tmp_path / "constant/physicalProperties.gas")
    text = path.read_text()

    assert re.search(r"rho\s+1\.2;", text)
    assert re.search(r"molWeight\s+28\.9;", text)
    assert re.search(r"mu\s+1\.8e-5;", text)


def test_physical_properties_liquid_matches_two_phase_constant_contract(tmp_path):
    path = write_physical_properties_liquid(
        SimpleNamespace(),
        tmp_path / "constant/physicalProperties.liquid",
    )
    text = path.read_text()

    assert re.search(r"rho\s+1000;", text)
    assert re.search(r"thermo\s+eConst;", text)
    assert re.search(r"Cv\s+4182;", text)


def test_momentum_transport_files_match_two_phase_constant_contract(tmp_path):
    gas = write_momentum_transport_gas(tmp_path / "constant/momentumTransport.gas").read_text()
    liquid = write_momentum_transport_liquid(tmp_path / "constant/momentumTransport.liquid").read_text()

    assert "simulationType  laminar;" in gas
    assert "kEpsilon" in liquid


def test_gravity_matches_two_phase_constant_contract(tmp_path):
    text = write_gravity(tmp_path / "constant/g").read_text()

    assert "class       uniformDimensionedVectorField;" in text
    assert "(0 0 -9.81)" in text
