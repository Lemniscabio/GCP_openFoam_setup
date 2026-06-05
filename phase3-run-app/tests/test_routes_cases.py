import os

os.environ["OF_DEV_NO_IAP"] = "1"

import pytest
from fastapi.testclient import TestClient

from backend import deps
from backend.main import app
from core.case_records import InMemoryCaseRecordRepository
from core.cases import CaseRepository
from core.storage import InMemoryStorage

_store = InMemoryStorage()
_case_records = InMemoryCaseRecordRepository()
app.dependency_overrides[deps.case_repo] = lambda: CaseRepository(_store)
app.dependency_overrides[deps.case_record_repo] = lambda: _case_records
app.dependency_overrides[deps.storage] = lambda: _store


class _FakeUrls:
    def put_urls_for_case(self, case_id, files, now):
        from core.uploads import SignedUpload, object_path

        return [
            SignedUpload(
                object_path=object_path(case_id, file),
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
    app.dependency_overrides[deps.storage] = lambda: _store
    app.dependency_overrides[deps.url_service] = lambda: _FakeUrls()


def _seed_uploaded_case(case_id):
    _store.upload_bytes(f"cases/{case_id}/case/system/controlDict", b"x")
    _store.upload_bytes(f"cases/{case_id}/case/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")


def test_allocate_returns_ids_and_urls():
    r = client.post(
        "/api/cases:allocate",
        json={
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


def test_finalize_writes_ready():
    cid = client.post(
        "/api/cases:allocate",
        json={"cases": [{"files": ["0/U"]}]},
    ).json()["cases"][0]["case_id"]
    _seed_uploaded_case(cid)

    r = client.post(f"/api/cases/{cid}:finalize", json={"openfoam_version": "12"})

    assert r.status_code == 200
    assert _store.object_exists(f"cases/{cid}/READY")


def test_finalize_rejects_unknown_case():
    r = client.post("/api/cases/case_999999:finalize", json={"openfoam_version": "12"})

    assert r.status_code == 404
    assert r.json()["detail"] == "unknown case"


def test_finalize_rejects_incomplete_case():
    cid = client.post(
        "/api/cases:allocate",
        json={"cases": [{"files": ["0/U"]}]},
    ).json()["cases"][0]["case_id"]

    r = client.post(f"/api/cases/{cid}:finalize", json={"openfoam_version": "12"})

    assert r.status_code == 400
    assert "case incomplete" in r.json()["detail"]


def test_list_cases():
    assert client.get("/api/cases").status_code == 200


def test_finalize_accepts_optional_name():
    from backend.schemas import FinalizeReq
    req = FinalizeReq(name="Wind Tunnel v3")
    assert req.name == "Wind Tunnel v3"
    # name is optional; omitting it is allowed
    assert FinalizeReq().name is None


def test_finalize_writes_case_record(client, mem_storage, mem_case_records):
    # arrange a reserved+uploaded case
    mem_storage.create_exclusive("cases/case_0006/.reserved", b"")
    mem_storage.upload_bytes("cases/case_0006/case/command.sh", b"# MPI_RANKS")
    r = client.post("/api/cases/case_0006:finalize", json={"name": "Wind Tunnel v3"})
    assert r.status_code == 200
    rec = mem_case_records.get("case_0006")
    assert rec is not None
    assert rec.name == "Wind Tunnel v3"
    assert rec.ready is True
