import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend import deps, rbac
from backend.auth import User
from core.case_records import CaseRecord, InMemoryCaseRecordRepository
from core.cases import CaseRepository
from core.projects import InMemoryProjectRepository
from core.run_repo import InMemoryRunRepository
from core.storage import InMemoryStorage
from core.users import InMemoryUserRepository, UserRecord


class _TestCaseRecordRepository(InMemoryCaseRecordRepository):
    def upsert_name(self, case_id: str, name: str) -> None:
        self.upsert(
            CaseRecord(
                case_id=case_id,
                name=name,
                uploaded_by="dev@lemnisca.bio",
                uploaded_at=datetime.datetime.now(datetime.timezone.utc),
                ready=True,
                project="turbine",
            )
        )


class _FakeSubmitter:
    def __init__(self) -> None:
        self.submissions = []

    def submit(self, job_name, spec):
        self.submissions.append((job_name, spec))
        return f"projects/p/locations/us-central1/jobs/{job_name}"


class _FakeBuilder:
    def build_single(self, **kwargs):
        return kwargs

    def build_multi(self, **kwargs):
        return kwargs


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


@pytest.fixture
def mem_storage():
    return InMemoryStorage()


@pytest.fixture
def mem_case_records():
    return _TestCaseRecordRepository()


@pytest.fixture
def mem_projects():
    return InMemoryProjectRepository()


@pytest.fixture
def mem_runs():
    return InMemoryRunRepository()


@pytest.fixture
def mem_users():
    return InMemoryUserRepository()


@pytest.fixture
def fake_submitter():
    return _FakeSubmitter()


@pytest.fixture
def valid_case(mem_storage, mem_case_records):
    case_id = "case_0006"
    base = f"cases/turbine/{case_id}"
    mem_storage.upload_bytes(f"{base}/case/system/controlDict", b"x")
    mem_storage.upload_bytes(
        f"{base}/case/command.sh",
        b"mpirun -np ${MPI_RANKS} foamRun -parallel",
    )
    mem_storage.upload_bytes(f"{base}/case/metadata.json", b"{}")
    mem_storage.upload_bytes(f"{base}/manifest.json", b'{"case_id":"case_0006"}')
    mem_storage.upload_bytes(f"{base}/READY", b"2026-06-01")
    mem_case_records.upsert_name(case_id, case_id)
    return case_id


@pytest.fixture
def client(mem_storage, mem_case_records, mem_projects, mem_runs, mem_users, fake_submitter):
    test_app = backend_main.app
    previous = test_app.dependency_overrides.copy()
    test_app.dependency_overrides[deps.storage] = lambda: mem_storage
    test_app.dependency_overrides[deps.case_repo] = lambda: CaseRepository(mem_storage)
    test_app.dependency_overrides[deps.case_record_repo] = lambda: mem_case_records
    test_app.dependency_overrides[deps.project_repo] = lambda: mem_projects
    test_app.dependency_overrides[deps.run_repo] = lambda: mem_runs
    test_app.dependency_overrides[deps.user_repo] = lambda: mem_users
    test_app.dependency_overrides[deps.submitter] = lambda: fake_submitter
    test_app.dependency_overrides[deps.builder] = lambda: _FakeBuilder()
    test_app.dependency_overrides[deps.url_service] = lambda: _FakeUrls()
    # list_runs reconcile needs a Batch state getter; default fake reports RUNNING so
    # existing RUNNING runs are unchanged (deleted-job tests override this to None).
    test_app.dependency_overrides[deps.batch_state_getter] = lambda: (lambda jid: "RUNNING")
    test_app.dependency_overrides[rbac.current_account] = lambda: (
        User(email="dev@lemnisca.bio", sub="d"),
        UserRecord(
            email="dev@lemnisca.bio",
            role="admin",
            status="active",
            requested_at=datetime.datetime.now(datetime.timezone.utc),
        ),
    )
    try:
        with TestClient(test_app) as test_client:
            yield test_client
    finally:
        test_app.dependency_overrides.clear()
        test_app.dependency_overrides.update(previous)


@pytest.fixture
def internal_client(mem_runs):
    from backend.routes_internal import push_claims, router as internal_router

    internal_app = FastAPI()
    internal_app.include_router(internal_router)
    internal_app.dependency_overrides[deps.run_repo] = lambda: mem_runs
    internal_app.dependency_overrides[push_claims] = lambda: {"email": "of-pubsub-push@test"}
    with TestClient(internal_app) as test_client:
        yield test_client


@pytest.fixture
def internal_client_no_auth(mem_runs):
    from backend.routes_internal import push_claims, router as internal_router

    def reject_push():
        raise HTTPException(status_code=403, detail="forbidden")

    internal_app = FastAPI()
    internal_app.include_router(internal_router)
    internal_app.dependency_overrides[deps.run_repo] = lambda: mem_runs
    internal_app.dependency_overrides[push_claims] = reject_push
    with TestClient(internal_app) as test_client:
        yield test_client
