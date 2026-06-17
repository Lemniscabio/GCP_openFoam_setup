import math
import pytest
from str_cad.ofcase.caseparams import CaseParams, CaseParamsError
from str_cad.geometry.assembly import REGION_NAMES

def _valid():
    return {"rpm": 90, "viscosity_m2_s": 1e-6}

def test_valid_parses_with_defaults():
    cp = CaseParams.model_validate(_valid())
    assert cp.run.cores == 28
    assert set(cp.patch_roles.keys()) == set(REGION_NAMES)

def test_omega_from_rpm():
    cp = CaseParams.model_validate(_valid())
    assert math.isclose(cp.omega_rad_s, 90 * 2 * math.pi / 60, rel_tol=1e-9)

def test_liquidSurface_default_is_slip():
    cp = CaseParams.model_validate(_valid())
    assert cp.patch_roles["liquidSurface"] == "slip"
    assert cp.patch_roles["tankWall"] == "wall"

def test_negative_rpm_rejected():
    bad = _valid(); bad["rpm"] = -5
    with pytest.raises(CaseParamsError):
        CaseParams.model_validate(bad)

def test_unknown_patch_role_rejected():
    bad = _valid(); bad["patch_roles"] = {"tankWall": "banana"}
    with pytest.raises(CaseParamsError):
        CaseParams.model_validate(bad)
