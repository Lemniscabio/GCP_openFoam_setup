import os

os.environ["OF_DEV_NO_IAP"] = "1"

import pytest
from fastapi.testclient import TestClient

from backend import deps
from backend.main import app
from core.case_records import InMemoryCaseRecordRepository
from core.cases import CaseRepository
from core.projects import InMemoryProjectRepository
from core.storage import InMemoryStorage
from core.users import InMemoryUserRepository

_store = InMemoryStorage()
_case_records = InMemoryCaseRecordRepository()
_projects = InMemoryProjectRepository()
_users = InMemoryUserRepository()
app.dependency_overrides[deps.case_repo] = lambda: CaseRepository(_store)
app.dependency_overrides[deps.case_record_repo] = lambda: _case_records
app.dependency_overrides[deps.project_repo] = lambda: _projects
app.dependency_overrides[deps.storage] = lambda: _store
# RBAC's current_account eagerly resolves user_repo; without this override FastAPI
# would build a real Firestore client (fails in CI: no ADC). Dev mode still returns
# an active admin so the role gates pass.
app.dependency_overrides[deps.user_repo] = lambda: _users


class _FakeUrls:
    def put_urls_for_case(self, project, case_id, files, now):
        from core.uploads import SignedUpload, object_path

        return [
            SignedUpload(
                object_path=object_path(project, case_id, file),
                url=f"https://signed/{case_id}/{file}",
            )
            for file in files
        ]


app.dependency_overrides[deps.url_service] = lambda: _FakeUrls()
client = TestClient(app)


@pytest.fixture(autouse=True)
def _override_deps():
    app.dependency_overrides[deps.case_repo] = lambda: CaseRepository(_store)
    app.dependency_overrides[deps.case_record_repo] = lambda: _case_records
    app.dependency_overrides[deps.project_repo] = lambda: _projects
    app.dependency_overrides[deps.storage] = lambda: _store
    app.dependency_overrides[deps.url_service] = lambda: _FakeUrls()
    app.dependency_overrides[deps.user_repo] = lambda: _users


def _seed_uploaded_case(case_id, project="turbine"):
    base = f"cases/{project}/{case_id}/case"
    _store.upload_bytes(f"{base}/system/controlDict", b"x")
    _store.upload_bytes(f"{base}/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")
    _store.upload_bytes(f"{base}/metadata.json", b"{}")


def test_allocate_returns_ids_and_urls():
    r = client.post(
        "/api/cases:allocate",
        json={
            "project": "turbine",
            "cases": [
                {"files": ["0/U"]},
                {"files": ["0/U", "system/controlDict"]},
                {"files": ["0/p"]},
            ]
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert len(body["cases"]) == 3
    assert body["cases"][0]["case_id"].startswith("case_")
    assert body["cases"][1]["uploads"][1]["url"].startswith("https://signed/")
    assert _store.object_exists(f"cases/turbine/{body['cases'][0]['case_id']}/.reserved")


def test_allocate_rejects_invalid_project():
    response = client.post(
        "/api/cases:allocate",
        json={"project": "bad/name", "cases": [{"files": ["0/U"]}]},
    )
    assert response.status_code == 400


def test_finalize_writes_ready():
    cid = client.post(
        "/api/cases:allocate",
        json={"project": "turbine", "cases": [{"files": ["0/U"]}]},
    ).json()["cases"][0]["case_id"]
    _seed_uploaded_case(cid)

    r = client.post(f"/api/cases/{cid}:finalize", json={"openfoam_version": "12", "project": "turbine"})

    assert r.status_code == 200
    assert _store.object_exists(f"cases/turbine/{cid}/READY")


def test_finalize_rejects_unknown_case():
    r = client.post("/api/cases/case_999999:finalize", json={"openfoam_version": "12", "project": "turbine"})

    assert r.status_code == 404
    assert r.json()["detail"] == "unknown case"


def test_finalize_rejects_incomplete_case():
    cid = client.post(
        "/api/cases:allocate",
        json={"project": "turbine", "cases": [{"files": ["0/U"]}]},
    ).json()["cases"][0]["case_id"]

    r = client.post(f"/api/cases/{cid}:finalize", json={"openfoam_version": "12", "project": "turbine"})

    assert r.status_code == 400
    assert "case incomplete" in r.json()["detail"]


def test_list_cases():
    assert client.get("/api/cases").status_code == 200


def test_finalize_accepts_optional_name():
    from backend.schemas import FinalizeReq
    req = FinalizeReq(name="Wind Tunnel v3", project="turbine")
    assert req.name == "Wind Tunnel v3"
    # name is optional; omitting it is allowed
    assert FinalizeReq(project="turbine").name is None


def test_finalize_writes_case_record(client, mem_storage, mem_case_records):
    # arrange a reserved+uploaded case
    mem_storage.create_exclusive("cases/turbine/case_0006/.reserved", b"")
    mem_storage.upload_bytes("cases/turbine/case_0006/case/command.sh", b"# MPI_RANKS")
    mem_storage.upload_bytes("cases/turbine/case_0006/case/metadata.json", b"{}")
    r = client.post("/api/cases/case_0006:finalize", json={"name": "Wind Tunnel v3", "project": "turbine"})
    assert r.status_code == 200
    rec = mem_case_records.get("case_0006")
    assert rec is not None
    assert rec.name == "Wind Tunnel v3"
    assert rec.ready is True
    assert rec.project == "turbine"


def test_finalize_rejects_missing_metadata():
    response = client.post(
        "/api/cases:allocate",
        json={"project": "turbine", "cases": [{"files": ["command.sh"]}]},
    )
    case_id = response.json()["cases"][0]["case_id"]
    _store.upload_bytes(
        f"cases/turbine/{case_id}/case/command.sh",
        b"mpirun -np ${MPI_RANKS} foamRun -parallel",
    )
    response = client.post(
        f"/api/cases/{case_id}:finalize", json={"project": "turbine"}
    )
    assert response.status_code == 400
    assert "metadata.json" in response.json()["detail"]
