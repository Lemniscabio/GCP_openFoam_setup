import datetime

import pytest
from fastapi.testclient import TestClient

from backend import deps
from backend.main import app
from core.case_records import CaseRecord, InMemoryCaseRecordRepository
from core.cases import CaseRepository
from core.run_repo import InMemoryRunRepository
from core.storage import InMemoryStorage


class _TestCaseRecordRepository(InMemoryCaseRecordRepository):
    def upsert_name(self, case_id: str, name: str) -> None:
        self.upsert(
            CaseRecord(
                case_id=case_id,
                name=name,
                uploaded_by="dev@lemnisca.bio",
                uploaded_at=datetime.datetime.now(datetime.timezone.utc),
                ready=True,
            )
        )


class _FakeSubmitter:
    def __init__(self) -> None:
        self.submissions = []

    def submit(self, job_name, spec):
        self.submissions.append((job_name, spec))
        return f"projects/p/locations/us-central1/jobs/{job_name}"


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


@pytest.fixture
def mem_storage():
    return InMemoryStorage()


@pytest.fixture
def mem_case_records():
    return _TestCaseRecordRepository()


@pytest.fixture
def mem_runs():
    return InMemoryRunRepository()


@pytest.fixture
def fake_submitter():
    return _FakeSubmitter()


@pytest.fixture
def valid_case(mem_storage):
    case_id = "case_0006"
    mem_storage.upload_bytes(f"cases/{case_id}/case/system/controlDict", b"x")
    mem_storage.upload_bytes(
        f"cases/{case_id}/case/command.sh",
        b"mpirun -np ${MPI_RANKS} foamRun -parallel",
    )
    mem_storage.upload_bytes(f"cases/{case_id}/manifest.json", b'{"case_id":"case_0006"}')
    mem_storage.upload_bytes(f"cases/{case_id}/READY", b"2026-06-01")
    return case_id


@pytest.fixture
def client(mem_storage, mem_case_records, mem_runs, fake_submitter):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[deps.storage] = lambda: mem_storage
    app.dependency_overrides[deps.case_repo] = lambda: CaseRepository(mem_storage)
    app.dependency_overrides[deps.case_record_repo] = lambda: mem_case_records
    app.dependency_overrides[deps.run_repo] = lambda: mem_runs
    app.dependency_overrides[deps.submitter] = lambda: fake_submitter
    app.dependency_overrides[deps.url_service] = lambda: _FakeUrls()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
