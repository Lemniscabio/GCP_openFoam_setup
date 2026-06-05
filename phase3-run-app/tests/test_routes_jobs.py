import os

os.environ["OF_DEV_NO_IAP"] = "1"

import pytest
from fastapi.testclient import TestClient

from backend import deps
from backend.main import app
from core.case_records import InMemoryCaseRecordRepository
from core.run_repo import InMemoryRunRepository
from core.storage import InMemoryStorage
from core.users import InMemoryUserRepository


_store = InMemoryStorage()
_case_records = InMemoryCaseRecordRepository()
_runs = InMemoryRunRepository()
_submissions = []


class _FakeSubmitter:
    def submit(self, job_name, spec):
        _submissions.append((job_name, spec))
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


_users = InMemoryUserRepository()
app.dependency_overrides[deps.submitter] = lambda: _FakeSubmitter()
app.dependency_overrides[deps.status_service] = lambda: _FakeStatus()
app.dependency_overrides[deps.storage] = lambda: _store
app.dependency_overrides[deps.case_record_repo] = lambda: _case_records
app.dependency_overrides[deps.run_repo] = lambda: _runs
# RBAC's current_account eagerly resolves user_repo; override it so tests never build
# a real Firestore client (fails in CI: no ADC). Dev mode returns an active admin.
app.dependency_overrides[deps.user_repo] = lambda: _users
client = TestClient(app)


@pytest.fixture(autouse=True)
def _override_deps():
    app.dependency_overrides[deps.submitter] = lambda: _FakeSubmitter()
    app.dependency_overrides[deps.status_service] = lambda: _FakeStatus()
    app.dependency_overrides[deps.storage] = lambda: _store
    app.dependency_overrides[deps.case_record_repo] = lambda: _case_records
    app.dependency_overrides[deps.run_repo] = lambda: _runs


def _seed_valid_case(case_id):
    _store.upload_bytes(f"cases/{case_id}/case/system/controlDict", b"x")
    _store.upload_bytes(f"cases/{case_id}/case/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")
    _store.upload_bytes(f"cases/{case_id}/manifest.json", b'{"case_id":"x"}')
    _store.upload_bytes(f"cases/{case_id}/READY", b"2026-06-01")


def test_submit_single():
    _seed_valid_case("case_0001")

    r = client.post(
        "/api/jobs",
        json={"case_ids": ["case_0001"], "machine_type": "c2d-highcpu-2"},
    )

    assert r.status_code == 200
    assert "of-case-0001-c2d-highcpu-2-" in r.json()["job_name"]


def test_submit_multi():
    _seed_valid_case("case_0001")
    _seed_valid_case("case_0002")

    r = client.post(
        "/api/jobs",
        json={
            "case_ids": ["case_0001", "case_0002"],
            "machine_type": "c2d-highcpu-2",
        },
    )

    assert r.status_code == 200
    assert r.json()["job_name"].startswith("of-multi-")


def test_submit_rejects_unvalidated_case():
    _submissions.clear()
    _store.upload_bytes("cases/case_0099/.reserved", b"")

    r = client.post(
        "/api/jobs",
        json={"case_ids": ["case_0099"], "machine_type": "c2d-highcpu-2"},
    )

    assert r.status_code == 400
    assert "case_0099" in r.json()["detail"]["errors"]
    assert _submissions == []


def test_unknown_machine_400():
    r = client.post(
        "/api/jobs",
        json={"case_ids": ["case_0001"], "machine_type": "n2-standard-4"},
    )

    assert r.status_code == 400


def test_list_runs():
    import datetime
    from core.run_repo import RunRecord

    _runs.create(
        RunRecord(
            batch_job_id="of-x-running",
            job_name="of-x-running",
            submitted_by="dev@lemnisca.bio",
            submitted_at=datetime.datetime(2100, 1, 1, tzinfo=datetime.timezone.utc),
            region="us-central1",
            machine_type="c2d-highcpu-2",
            mpi_ranks=1,
            spot=False,
            case_ids=["case_0001"],
            case_names=["case_0001"],
            state="RUNNING",
        )
    )
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


def test_submit_writes_run_record(client, valid_case, mem_runs, mem_case_records):
    mem_case_records.upsert_name("case_0006", "Wind Tunnel v3")
    r = client.post("/api/jobs", json={"case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8"})
    assert r.status_code == 200
    batch_job_id = r.json()["batch_job_id"]
    rec = mem_runs.get(batch_job_id)
    assert rec is not None
    assert rec.submitted_by.endswith("@lemnisca.bio")
    assert rec.case_names == ["Wind Tunnel v3"]
    assert rec.machine_type == "c2d-highcpu-8"
    assert rec.state == "SUBMITTED"


def test_list_runs_reads_from_repo(client, mem_runs):
    import datetime
    from core.run_repo import RunRecord
    mem_runs.create(RunRecord(
        batch_job_id="of-x-1", job_name="windtunnel",
        submitted_by="kartikey.attri@lemnisca.bio",
        submitted_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        region="us-central1", machine_type="c2d-highcpu-8", mpi_ranks=4,
        spot=False, case_ids=["case_0006"], case_names=["Wind Tunnel v3"],
        state="RUNNING",
    ))
    r = client.get("/api/jobs")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert runs[0]["batch_job_id"] == "of-x-1"
    assert runs[0]["case_names"] == ["Wind Tunnel v3"]
    assert runs[0]["state"] == "RUNNING"


def test_viewer_cannot_submit(client, valid_case):
    import datetime
    from backend import rbac
    from backend.auth import User
    from backend.main import app
    from core.users import UserRecord
    now = datetime.datetime.now(datetime.timezone.utc)
    app.dependency_overrides[rbac.current_account] = lambda: (
        User(email="v@lemnisca.bio", sub="v"),
        UserRecord(email="v@lemnisca.bio", role="viewer", status="active", requested_at=now),
    )
    r = client.post("/api/jobs", json={"case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8"})
    assert r.status_code == 403
    app.dependency_overrides.pop(rbac.current_account, None)
