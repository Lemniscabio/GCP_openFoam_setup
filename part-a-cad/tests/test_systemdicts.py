from pathlib import Path
from str_cad.ofcase.caseparams import CaseParams
from str_cad.ofcase.systemdicts import (write_control_dict, write_fv_schemes,
                                         write_fv_solution, write_decompose_par)

def _cp():
    return CaseParams.model_validate({"rpm": 90, "viscosity_m2_s": 1e-6,
                                      "run": {"end_time": 800, "write_interval": 100, "cores": 16}})

def test_control_dict(tmp_path):
    t = Path(write_control_dict(_cp(), tmp_path / "controlDict")).read_text()
    assert "foamRun" in t and "incompressibleFluid" in t and "800" in t

def test_fv_solution_has_pref_and_simple(tmp_path):
    t = Path(write_fv_solution(_cp(), tmp_path / "fvSolution")).read_text()
    assert "SIMPLE" in t and "pRefCell" in t and "pRefValue" in t and "GAMG" in t

def test_fv_schemes_steady(tmp_path):
    t = Path(write_fv_schemes(tmp_path / "fvSchemes")).read_text()
    assert "steadyState" in t and "div(phi,U)" in t

def test_decompose_par(tmp_path):
    t = Path(write_decompose_par(_cp(), tmp_path / "decomposeParDict")).read_text()
    assert "numberOfSubdomains" in t and "16" in t
