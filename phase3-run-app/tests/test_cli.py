from click.testing import CliRunner

from cli import main
from core.storage import InMemoryStorage


class _FakeSubmitter:
    def __init__(self, project_id, region):
        self.project_id = project_id
        self.region = region

    def submit(self, job_name, spec):
        raise AssertionError("submit should not run for invalid cases")


def test_run_rejects_invalid_case_before_submit(monkeypatch):
    store = InMemoryStorage()
    store.upload_bytes("cases/case_0001/.reserved", b"")
    monkeypatch.setattr(main, "GcsStorage", lambda bucket: store)
    monkeypatch.setattr(main, "BatchSubmitter", _FakeSubmitter)

    result = CliRunner().invoke(
        main.cli,
        ["run", "--case", "case_0001", "--machine", "c2d-highcpu-2"],
    )

    assert result.exit_code == 1
    assert "FAIL case_0001" in result.stderr
