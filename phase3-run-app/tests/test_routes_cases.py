import os

os.environ["OF_DEV_NO_IAP"] = "1"

from fastapi.testclient import TestClient

from backend import deps
from backend.main import app
from core.cases import CaseRepository
from core.storage import InMemoryStorage

_store = InMemoryStorage()
app.dependency_overrides[deps.case_repo] = lambda: CaseRepository(_store)
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

    r = client.post(f"/api/cases/{cid}:finalize", json={"openfoam_version": "12"})

    assert r.status_code == 200
    assert _store.object_exists(f"cases/{cid}/READY")


def test_list_cases():
    assert client.get("/api/cases").status_code == 200
