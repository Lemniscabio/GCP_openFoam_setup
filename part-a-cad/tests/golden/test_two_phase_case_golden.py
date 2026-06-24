from pathlib import Path

from str_cad.builder import build_from_schema_file
from str_cad.ofcase.build import build_case
from str_cad.ofcase.caseparams import CaseParams


def _case_params():
    return CaseParams.model_validate({"rpm": 100, "viscosity_m2_s": 1e-6})


def test_two_phase_case_builds_full_openfoam_case(tmp_path):
    geo_dir = build_from_schema_file(Path("examples/reactor_twophase.json"), tmp_path / "geo")
    case_dir = build_case(_case_params(), geo_dir, tmp_path / "case")

    control_dict = (case_dir / "system/controlDict").read_text()
    assert "solver          multiphaseEuler;" in control_dict
    assert "adjustTimeStep  yes;" in control_dict

    fv_schemes = (case_dir / "system/fvSchemes").read_text()
    assert "div(phi,alpha)                      Gauss vanLeer;" in fv_schemes

    fv_solution = (case_dir / "system/fvSolution").read_text()
    assert "PIMPLE" in fv_solution
    assert '"alpha.*"' in fv_solution

    set_fields = (case_dir / "system/setFieldsDict").read_text()
    assert "cylinderToCell" in set_fields
    assert "volScalarFieldValue alpha.gas    0.05" in set_fields

    assert "basicMultiphaseSystem" in (case_dir / "constant/phaseProperties").read_text()
    assert (case_dir / "constant/g").exists()
    assert "cellZone    rotor;" in (case_dir / "constant/MRFProperties").read_text()

    assert (case_dir / "0/U.liquid").exists()
    assert (case_dir / "0/alpha.gas").exists()
    assert (case_dir / "0/p_rgh").exists()

    command = (case_dir / "command.sh").read_text()
    assert "setFields" in command
    assert "foamRun" in command


def test_single_phase_case_still_uses_single_phase_dispatch(tmp_path):
    geo_dir = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    case_dir = build_case(_case_params(), geo_dir, tmp_path / "case")

    control_dict = (case_dir / "system/controlDict").read_text()
    assert "solver          incompressibleFluid;" in control_dict
