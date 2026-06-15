from pathlib import Path
from str_cad.ofcase.caseparams import CaseParams
from str_cad.ofcase.fields import write_initial_fields
from str_cad.geometry.assembly import REGION_NAMES

def _patches_in(text):
    # crude: which region names appear as boundaryField sub-dict keys
    return {r for r in REGION_NAMES if r in text}

def test_every_field_has_an_entry_for_every_patch(tmp_path):
    cp = CaseParams.model_validate({"rpm": 90, "viscosity_m2_s": 1e-6})
    out = write_initial_fields(cp, REGION_NAMES, tmp_path)
    for field in ["U", "p", "k", "epsilon", "nut"]:
        txt = Path(out, field).read_text()
        assert _patches_in(txt) == set(REGION_NAMES), f"{field} missing patches"

def test_rotating_walls_use_MRFnoSlip_and_surface_is_slip(tmp_path):
    cp = CaseParams.model_validate({"rpm": 90, "viscosity_m2_s": 1e-6})
    out = write_initial_fields(cp, REGION_NAMES, tmp_path)
    u = Path(out, "U").read_text()
    assert """    impellers
    {
        type MRFnoSlip;
    }""" in u
    assert """    shaft
    {
        type noSlip;
    }""" in u
    assert "slip" in u               # liquidSurface
