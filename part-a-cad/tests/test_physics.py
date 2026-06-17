from pathlib import Path
from str_cad.ofcase.caseparams import CaseParams
from str_cad.ofcase.physics import write_physical_properties, write_momentum_transport

def test_physical_properties_has_nu(tmp_path):
    cp = CaseParams.model_validate({"rpm": 90, "viscosity_m2_s": 1.5e-6})
    p = write_physical_properties(cp, tmp_path / "physicalProperties")
    txt = Path(p).read_text()
    assert "viscosityModel" in txt and "nu" in txt
    assert "1.5e-06" in txt or "1.5e-6" in txt

def test_momentum_transport_is_kEpsilon(tmp_path):
    p = write_momentum_transport(tmp_path / "momentumTransport")
    txt = Path(p).read_text()
    assert "RAS" in txt and "kEpsilon" in txt and "turbulence" in txt
