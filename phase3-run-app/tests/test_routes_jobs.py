import os

os.environ["OF_DEV_NO_IAP"] = "1"

from fastapi.testclient import TestClient

from backend import deps
from backend.main import app


class _FakeSubmitter:
    def submit(self, job_name, spec):
        return f"projects/p/locations/us-central1/jobs/{job_name}"


class _FakeStatus:
    def list_runs(self, limit=50):
        from core.status import RunSummary

        return [
            RunSummary(
                job_name="of-case-0001-c2d-highcpu-2-x",
                state="RUNNING",
                case_ids=["case_0001"],
                progress_pct=54,
            )
        ]

    def get_status(self, job_name, case_id, variant):
        return {
            "job_name": job_name,
            "state": "RUNNING",
            "events": [],
            "checkpoint_latest_timestep": 5.4,
        }


app.dependency_overrides[deps.submitter] = lambda: _FakeSubmitter()
app.dependency_overrides[deps.status_service] = lambda: _FakeStatus()
client = TestClient(app)


def test_submit_single():
    r = client.post(
        "/api/jobs",
        json={"case_ids": ["case_0001"], "machine_type": "c2d-highcpu-2"},
    )

    assert r.status_code == 200
    assert "of-case-0001-c2d-highcpu-2-" in r.json()["job_name"]


def test_submit_multi():
    r = client.post(
        "/api/jobs",
        json={
            "case_ids": ["case_0001", "case_0002"],
            "machine_type": "c2d-highcpu-2",
        },
    )

    assert r.status_code == 200
    assert r.json()["job_name"].startswith("of-multi-")


def test_unknown_machine_400():
    r = client.post(
        "/api/jobs",
        json={"case_ids": ["case_0001"], "machine_type": "n2-standard-4"},
    )

    assert r.status_code == 400


def test_list_runs():
    r = client.get("/api/jobs")

    assert r.status_code == 200
    assert r.json()["runs"][0]["state"] == "RUNNING"


def test_run_detail():
    r = client.get(
        "/api/jobs/of-case-0001-c2d-highcpu-2-x"
        "?case_id=case_0001&variant=c2d-highcpu-2"
    )

    assert r.status_code == 200
    assert r.json()["checkpoint_latest_timestep"] == 5.4
