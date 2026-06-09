import os

os.environ["OF_DEV_NO_IAP"] = "1"

import pytest
import datetime
from fastapi.testclient import TestClient

from backend import deps
from backend.main import app
from core.case_records import CaseRecord, InMemoryCaseRecordRepository
from core.projects import InMemoryProjectRepository
from core.run_repo import InMemoryRunRepository
from core.storage import InMemoryStorage
from core.users import InMemoryUserRepository


_store = InMemoryStorage()
_case_records = InMemoryCaseRecordRepository()
_runs = InMemoryRunRepository()
_projects = InMemoryProjectRepository()
_submissions = []


class _FakeSubmitter:
    def submit(self, job_name, spec):
        _submissions.append((job_name, spec))
        return f"projects/p/locations/us-central1/jobs/{job_name}"


class _FakeBuilder:
    def build_single(self, **kwargs):
        return kwargs

    def build_multi(self, **kwargs):
        return kwargs


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
app.dependency_overrides[deps.project_repo] = lambda: _projects
app.dependency_overrides[deps.run_repo] = lambda: _runs
app.dependency_overrides[deps.builder] = lambda: _FakeBuilder()
# RBAC's current_account eagerly resolves user_repo; override it so tests never build
# a real Firestore client (fails in CI: no ADC). Dev mode returns an active admin.
app.dependency_overrides[deps.user_repo] = lambda: _users
# list_runs reconcile needs a Batch state getter; fake reports RUNNING (no real client).
app.dependency_overrides[deps.batch_state_getter] = lambda: (lambda jid: "RUNNING")
app.dependency_overrides[deps.batch_events_getter] = lambda: (lambda jid: [])
client = TestClient(app)


@pytest.fixture(autouse=True)
def _override_deps():
    app.dependency_overrides[deps.submitter] = lambda: _FakeSubmitter()
    app.dependency_overrides[deps.status_service] = lambda: _FakeStatus()
    app.dependency_overrides[deps.storage] = lambda: _store
    app.dependency_overrides[deps.case_record_repo] = lambda: _case_records
    app.dependency_overrides[deps.project_repo] = lambda: _projects
    app.dependency_overrides[deps.run_repo] = lambda: _runs
    app.dependency_overrides[deps.builder] = lambda: _FakeBuilder()
    app.dependency_overrides[deps.batch_events_getter] = lambda: (lambda jid: [])


def _seed_valid_case(case_id, project="turbine"):
    base = f"cases/{project}/{case_id}"
    _store.upload_bytes(f"{base}/case/system/controlDict", b"x")
    _store.upload_bytes(f"{base}/case/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")
    _store.upload_bytes(f"{base}/case/metadata.json", b"{}")
    _store.upload_bytes(f"{base}/manifest.json", b'{"case_id":"x"}')
    _store.upload_bytes(f"{base}/READY", b"2026-06-01")
    _case_records.upsert(CaseRecord(
        case_id=case_id,
        name=case_id,
        uploaded_by="dev@lemnisca.bio",
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        ready=True,
        project=project,
    ))


def test_submit_single():
    _seed_valid_case("case_0001")

    r = client.post(
        "/api/jobs",
        json={
            "case_ids": ["case_0001"],
            "machine_type": "c2d-highcpu-2",
            "job_name": "phoenix",
        },
    )

    assert r.status_code == 200
    assert r.json()["job_name"] == "phoenix"


def test_submit_multi():
    _seed_valid_case("case_0001")
    _seed_valid_case("case_0002")

    r = client.post(
        "/api/jobs",
        json={
            "case_ids": ["case_0001", "case_0002"],
            "machine_type": "c2d-highcpu-2",
            "job_name": "otter",
        },
    )

    assert r.status_code == 200
    assert r.json()["job_name"] == "otter"


def test_submit_rejects_unvalidated_case():
    _submissions.clear()
    _store.upload_bytes("cases/turbine/case_0099/.reserved", b"")
    _case_records.upsert(CaseRecord(
        case_id="case_0099", name="case_0099", uploaded_by="dev@lemnisca.bio",
        uploaded_at=datetime.datetime.now(datetime.timezone.utc), project="turbine",
    ))

    r = client.post(
        "/api/jobs",
        json={
            "case_ids": ["case_0099"],
            "machine_type": "c2d-highcpu-2",
            "job_name": "raven",
        },
    )

    assert r.status_code == 400
    assert "case_0099" in r.json()["detail"]["errors"]
    assert _submissions == []


def test_unknown_machine_400():
    r = client.post(
        "/api/jobs",
        json={
            "case_ids": ["case_0001"],
            "machine_type": "n2-standard-4",
            "job_name": "falcon",
        },
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


def test_job_events_returns_batch_events(client):
    events = [
        {"type": "JOB_STATE_CHANGED", "description": "Job queued", "event_time": "2026-06-09T10:00:00+00:00"},
        {"type": "JOB_STATE_CHANGED", "description": "Job running", "event_time": "2026-06-09T10:01:00+00:00"},
    ]
    client.app.dependency_overrides[deps.batch_events_getter] = lambda: (lambda job: events)

    response = client.get("/api/jobs/phoenix/events")

    assert response.status_code == 200
    assert response.json() == {"events": events}


def test_job_events_returns_empty_list_when_job_is_aged_out(client):
    client.app.dependency_overrides[deps.batch_events_getter] = lambda: (lambda job: [])

    response = client.get("/api/jobs/phoenix/events")

    assert response.status_code == 200
    assert response.json() == {"events": []}


def test_job_log_returns_stored_text(client, mem_storage):
    path = "results/turbine/phoenix/case_0006/solver.stdout.log"
    mem_storage.upload_bytes(path, b"solver output\n")

    response = client.get("/api/jobs/phoenix/log?project=turbine&case=case_0006")

    assert response.status_code == 200
    assert response.json() == {"text": "solver output\n", "truncated": False, "missing": False}


def test_job_log_reports_missing_object(client):
    response = client.get("/api/jobs/phoenix/log?project=turbine&case=case_9999")

    assert response.status_code == 200
    assert response.json() == {"text": "", "truncated": False, "missing": True}


def test_job_log_returns_last_256_kib(client, mem_storage):
    cap = 256 * 1024
    text = "prefix" + ("x" * cap)
    path = "results/turbine/phoenix/case_0006/solver.stdout.log"
    mem_storage.upload_bytes(path, text.encode())

    response = client.get("/api/jobs/phoenix/log?project=turbine&case=case_0006")

    assert response.status_code == 200
    assert response.json() == {"text": "x" * cap, "truncated": True, "missing": False}


def test_job_log_rejects_path_components(client):
    response = client.get("/api/jobs/phoenix/log?project=../secrets&case=case_0006")

    assert response.status_code == 400


def test_submit_writes_run_record(client, valid_case, mem_runs, mem_case_records):
    mem_case_records.upsert_name("case_0006", "Wind Tunnel v3")
    r = client.post("/api/jobs", json={
        "case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8", "job_name": "ember"})
    assert r.status_code == 200
    batch_job_id = r.json()["batch_job_id"]
    rec = mem_runs.get(batch_job_id)
    assert rec is not None
    assert rec.submitted_by.endswith("@lemnisca.bio")
    assert rec.case_names == ["Wind Tunnel v3"]
    assert rec.machine_type == "c2d-highcpu-8"
    assert rec.state == "SUBMITTED"
    assert rec.project == "turbine"


def test_submit_rejects_cases_from_multiple_projects():
    _seed_valid_case("case_0101", "turbine")
    _seed_valid_case("case_0102", "wing")
    response = client.post("/api/jobs", json={
        "case_ids": ["case_0101", "case_0102"],
        "machine_type": "c2d-highcpu-2",
        "job_name": "mixedprojects",
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "all cases in a job must share one project"


def test_submit_rejects_case_missing_project():
    _seed_valid_case("case_0103")
    record = _case_records.get("case_0103")
    record.project = ""
    response = client.post("/api/jobs", json={
        "case_ids": ["case_0103"],
        "machine_type": "c2d-highcpu-2",
        "job_name": "missingproject",
    })
    assert response.status_code == 400


def test_reconcile_marks_deleted_run_cancelled(client, mem_runs):
    import datetime as _dt
    from backend import deps
    from backend.main import app as _app
    from core.run_repo import RunRecord
    mem_runs.create(RunRecord(
        batch_job_id="of-gone-1", job_name="gone", submitted_by="dev@lemnisca.bio",
        submitted_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc), region="us-central1",
        machine_type="c2d-highcpu-8", mpi_ranks=4, spot=False, case_ids=["case_0006"],
        case_names=["c"], state="RUNNING",
    ))
    # simulate the job having been deleted in Batch (get_state -> None)
    _app.dependency_overrides[deps.batch_state_getter] = lambda: (lambda jid: None)
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert mem_runs.get("of-gone-1").state == "CANCELLED"


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
    r = client.post("/api/jobs", json={
        "case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8", "job_name": "frost"})
    assert r.status_code == 403
    app.dependency_overrides.pop(rbac.current_account, None)


def test_submit_requires_job_name(client, valid_case):
    # job_name omitted -> 422 (Pydantic required field)
    r = client.post("/api/jobs", json={"case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8"})
    assert r.status_code == 422


def test_suggest_job_name_returns_unused_valid(client, mem_runs):
    from core.codenames import is_valid_codename
    from core.run_repo import RunRecord
    import datetime as _dt
    mem_runs.try_reserve(RunRecord(
        batch_job_id="phoenix", job_name="phoenix", submitted_by="d@lemnisca.bio",
        submitted_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc), region="us-central1",
        machine_type="c2d-highcpu-8", mpi_ranks=4, spot=False, case_ids=["case_0006"],
        case_names=["c"]))
    r = client.get("/api/job-name/suggest")
    assert r.status_code == 200
    name = r.json()["name"]
    assert is_valid_codename(name) and name != "phoenix"


def test_submit_uses_codename_as_id_and_folder(client, valid_case, mem_runs):
    r = client.post("/api/jobs", json={
        "case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8", "job_name": "phoenix"})
    assert r.status_code == 200, r.text
    assert r.json()["batch_job_id"] == "phoenix"
    rec = mem_runs.get("phoenix")
    assert rec is not None and rec.job_name == "phoenix"


def test_submit_rejects_invalid_job_name(client, valid_case):
    r = client.post("/api/jobs", json={
        "case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8", "job_name": "Bad Name!"})
    assert r.status_code == 400


def test_submit_rejects_taken_job_name(client, valid_case, mem_runs):
    body = {"case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8", "job_name": "phoenix"}
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 200, response.text
    assert client.post("/api/jobs", json=body).status_code == 400  # taken


def test_submit_dedupes_case_ids(client, valid_case, mem_runs):
    r = client.post("/api/jobs", json={
        "case_ids": ["case_0006", "case_0006"], "machine_type": "c2d-highcpu-8",
        "job_name": "otter"})
    assert r.status_code == 200, r.text
    assert mem_runs.get("otter").case_ids == ["case_0006"]
