import re
from pathlib import Path

from str_cad.builder import build_from_schema_file
from str_cad.ofcase.build import build_case
from str_cad.ofcase.caseparams import CaseParams, Run


def _control_value(control_dict: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}\s+([^;]+);", control_dict, re.M)
    assert match, f"missing controlDict key: {key}"
    return match.group(1).strip()


def _case_params(run: Run | None = None) -> CaseParams:
    return CaseParams.model_validate(
        {"rpm": 100, "viscosity_m2_s": 1e-6, "run": run or Run()}
    )


def test_single_phase_verify_small_endtime(tmp_path):
    geo_dir = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    case_dir = build_case(
        _case_params(Run(verify=True, verify_steps=5)),
        geo_dir,
        tmp_path / "case",
    )

    control_dict = (case_dir / "system/controlDict").read_text()
    assert _control_value(control_dict, "endTime") == "5"
    assert _control_value(control_dict, "writeInterval") == "5"


def test_single_phase_full_unchanged(tmp_path):
    geo_dir = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    case_dir = build_case(_case_params(), geo_dir, tmp_path / "case")

    control_dict = (case_dir / "system/controlDict").read_text()
    assert _control_value(control_dict, "endTime") == str(Run().end_time)


def test_two_phase_verify_small_endtime(tmp_path):
    geo_dir = build_from_schema_file(
        Path("examples/reactor_twophase.json"), tmp_path / "geo"
    )
    case_dir = build_case(
        _case_params(Run(verify=True, verify_steps=5)),
        geo_dir,
        tmp_path / "case",
    )

    control_dict = (case_dir / "system/controlDict").read_text()
    assert float(_control_value(control_dict, "endTime")) <= 0.01
    assert _control_value(control_dict, "solver") == "multiphaseEuler"


def test_two_phase_full_unchanged(tmp_path):
    geo_dir = build_from_schema_file(
        Path("examples/reactor_twophase.json"), tmp_path / "geo"
    )
    case_dir = build_case(_case_params(), geo_dir, tmp_path / "case")

    control_dict = (case_dir / "system/controlDict").read_text()
    assert _control_value(control_dict, "endTime") == "60.0"
