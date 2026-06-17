import json
from pathlib import Path
from str_cad.schema import STRParams
from str_cad.ofcase.caseparams import CaseParams
from str_cad.ofcase.mrf import rotor_cylinders, write_toposet_dict, write_mrf_properties

def _sp():
    return STRParams.model_validate(json.load(open("examples/reactor_30kl.json")))

def test_one_cylinder_per_impeller():
    sp = _sp()
    cyls = rotor_cylinders(sp)
    assert len(cyls) == sp.impellers.count
    assert all(c["radius"] > sp.impeller_diameter_m / 2 for c in cyls)

def test_toposet_dict_has_cylinder_actions_and_rotor_zone(tmp_path):
    sp = _sp()
    p = write_toposet_dict(sp, tmp_path / "topoSetDict")
    txt = Path(p).read_text()
    assert txt.count("cylinderToCell") == sp.impellers.count
    assert "rotor" in txt and "setToCellZone" in txt

def test_mrf_properties_has_rpm(tmp_path):
    sp = _sp(); cp = CaseParams.model_validate({"rpm": 90, "viscosity_m2_s": 1e-6})
    p = write_mrf_properties(sp, cp, tmp_path / "MRFProperties")
    txt = Path(p).read_text()
    assert "MRF" in txt and "cellZone" in txt and "rotor" in txt
    assert "[rpm]" in txt and "90" in txt
