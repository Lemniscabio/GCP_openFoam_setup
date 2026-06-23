from pathlib import Path

from str_cad.verify.harness import parse_smoke_log, submit_smoke


SUCCESS_LOG = """
blockMesh
End

snappyHexMesh
Finished meshing

foamRun
Create mesh
Time = 0.001
Time = 0.002
End
"""


def test_parse_success_log():
    result = parse_smoke_log(SUCCESS_LOG)

    assert result.ok is True
    assert result.raw_markers["time_steps"] == 2


def test_parse_fatal_log():
    result = parse_smoke_log(
        """
blockMesh
End
Finished meshing
Create mesh
--> FOAM FATAL ERROR:
bad turbulence model
file: constant/turbulenceProperties
"""
    )

    assert result.ok is False
    assert result.exit_ok is False
    assert "FOAM FATAL ERROR" in result.errors[0]
    assert "bad turbulence model" in result.errors[0]


def test_parse_missing_time():
    result = parse_smoke_log(
        """
blockMesh
End
snappyHexMesh
Mesh Information
foamRun
Reading field U
"""
    )

    assert result.ok is False
    assert result.time_advanced is False


def test_submit_targets_cfd_lemnisca(tmp_path):
    calls = []
    case_dir = _case_dir(tmp_path)

    def runner(args):
        calls.append(args)
        if args[:2] == ["of", "upload"]:
            return "Uploaded reactor-foo to gs://cfd-lemnisca-cases/cases/cfd-lemnisca/reactor-foo\n"
        if args[:2] == ["of", "run"]:
            return "Submitted projects/cfd-lemnisca/locations/us-central1/jobs/foo\n"
        raise AssertionError(args)

    result = submit_smoke(case_dir, runner=runner, log_fetcher=lambda _project, _cid: SUCCESS_LOG)

    assert result.case_id == "reactor-foo"
    assert result.job_name == "foo"
    assert result.ok is True
    for call in calls:
        assert call[:1] == ["of"]
        assert _option_value(call, "--project") == "cfd-lemnisca"


def test_submit_passes_machine(tmp_path):
    calls = []
    case_dir = _case_dir(tmp_path)

    def runner(args):
        calls.append(args)
        if args[:2] == ["of", "upload"]:
            return "Uploaded reactor-foo to gs://bucket/path\n"
        return "Submitted foo\n"

    submit_smoke(case_dir, runner=runner, log_fetcher=lambda _project, _cid: SUCCESS_LOG)

    run_call = next(call for call in calls if call[:2] == ["of", "run"])
    assert _option_value(run_call, "--machine") == "c2d-highcpu-8"


def _case_dir(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "command.sh").write_text("#!/usr/bin/env bash\n")
    return case_dir


def _option_value(args: list[str], option: str) -> str:
    return args[args.index(option) + 1]
