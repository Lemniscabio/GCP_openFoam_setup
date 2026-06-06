from click.testing import CliRunner

from cli import main
from core.codenames import is_valid_codename
from core.storage import InMemoryStorage


class _FakeSubmitter:
    def __init__(self, project_id, region):
        self.project_id = project_id
        self.region = region

    def submit(self, job_name, spec):
        raise AssertionError("submit should not run for invalid cases")


def test_run_rejects_invalid_case_before_submit(monkeypatch):
    store = InMemoryStorage()
    store.upload_bytes("cases/turbine/case_0001/.reserved", b"")
    monkeypatch.setattr(main, "GcsStorage", lambda bucket: store)
    monkeypatch.setattr(main, "BatchSubmitter", _FakeSubmitter)

    result = CliRunner().invoke(
        main.cli,
        ["run", "--project", "turbine", "--case", "case_0001", "--machine", "c2d-highcpu-2"],
    )

    assert result.exit_code == 1
    assert "FAIL case_0001" in result.stderr


def test_run_auto_suggests_or_uses_job_name(monkeypatch):
    store = InMemoryStorage()
    store.upload_bytes("cases/turbine/case_0001/case/system/controlDict", b"x")
    store.upload_bytes("cases/turbine/case_0001/case/command.sh", b"foamRun")
    store.upload_bytes("cases/turbine/case_0001/case/metadata.json", b"{}")
    store.upload_bytes("cases/turbine/case_0001/manifest.json", b'{}')
    store.upload_bytes("cases/turbine/case_0001/READY", b"ready")
    submitted = []

    class _CapturingSubmitter:
        def __init__(self, project_id, region):
            pass

        def submit(self, job_name, spec):
            submitted.append(job_name)
            return job_name

    monkeypatch.setattr(main, "GcsStorage", lambda bucket: store)
    monkeypatch.setattr(main, "BatchSubmitter", _CapturingSubmitter)
    runner = CliRunner()

    automatic = runner.invoke(
        main.cli,
        ["run", "--project", "turbine", "--case", "case_0001", "--machine", "c2d-highcpu-2"],
    )
    explicit = runner.invoke(
        main.cli,
        [
            "run", "--project", "turbine", "--case", "case_0001", "--machine", "c2d-highcpu-2",
            "--job-name", "foo",
        ],
    )

    assert automatic.exit_code == 0
    assert explicit.exit_code == 0
    assert is_valid_codename(submitted[0])
    assert submitted[1] == "foo"


def test_upload_requires_project(tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    command = tmp_path / "command.sh"
    command.write_text("foamRun")
    result = CliRunner().invoke(main.cli, [
        "upload", "--case-dir", str(case_dir), "--command-sh", str(command),
    ])
    assert result.exit_code == 2
    assert "--project" in result.output


def test_upload_writes_under_project(monkeypatch, tmp_path):
    store = InMemoryStorage()
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "metadata.json").write_text("{}")
    command = tmp_path / "command.sh"
    command.write_text("mpirun -np ${MPI_RANKS} foamRun -parallel")
    calls = []

    def fake_run(args, check):
        calls.append(args)
        if args[2] == "rsync":
            store.upload_bytes("cases/turbine/case_0001/case/metadata.json", b"{}")
        else:
            store.upload_bytes(
                "cases/turbine/case_0001/case/command.sh",
                command.read_bytes(),
            )

    monkeypatch.setattr(main, "GcsStorage", lambda bucket: store)
    monkeypatch.setattr(main.subprocess, "run", fake_run)
    result = CliRunner().invoke(main.cli, [
        "upload", "--project", "turbine", "--case-dir", str(case_dir),
        "--command-sh", str(command),
    ])
    assert result.exit_code == 0, result.output
    assert store.object_exists("cases/turbine/case_0001/READY")
    assert calls[0][-1].endswith("/cases/turbine/case_0001/case/")
