from functools import lru_cache

import google.auth
from google.auth.transport.requests import Request
from google.cloud import batch_v1
from google.cloud import storage as gcs

from core.batch_jobs import BatchJobBuilder, BatchSubmitter
from core.case_records import FirestoreCaseRecordRepository
from core.cases import CaseRepository
from core.config import Settings
from core.projects import FirestoreProjectRepository
from core.run_repo import FirestoreRunRepository
from core.status import RunStatusService
from core.storage import GcsStorage
from core.uploads import SignedUrlService
from core.users import FirestoreUserRepository


@lru_cache
def settings() -> Settings:
    return Settings()


@lru_cache
def _bucket():
    return gcs.Client().bucket(settings().bucket)


@lru_cache
def _adc():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return creds


def _access_token() -> str:
    creds = _adc()
    if not creds.valid:
        creds.refresh(Request())
    return creds.token


def case_repo() -> CaseRepository:
    return CaseRepository(storage())


def storage() -> GcsStorage:
    return GcsStorage(settings().bucket)


def url_service() -> SignedUrlService:
    # Keyless per-file V4 PUT URLs; the attached SA signs as itself via IAM.
    return SignedUrlService(
        _bucket(),
        signer_email=settings().backend_service_account,
        token_provider=_access_token,
    )


def builder() -> BatchJobBuilder:
    s = settings()
    topic = f"projects/{s.project_id}/topics/{s.pubsub_topic}"
    return BatchJobBuilder(
        bucket=s.bucket,
        image_uri=s.image_uri,
        job_service_account=s.job_service_account,
        pubsub_topic=topic,
    )


def submitter() -> BatchSubmitter:
    s = settings()
    return BatchSubmitter(s.project_id, s.region)


def status_service() -> RunStatusService:
    s = settings()
    return RunStatusService(batch_v1.BatchServiceClient(), storage(), s.project_id, s.region)


@lru_cache
def _firestore():
    from google.cloud import firestore

    return firestore.Client(project=settings().project_id, database=settings().firestore_database)


def case_record_repo() -> FirestoreCaseRecordRepository:
    return FirestoreCaseRecordRepository(_firestore())


def project_repo() -> FirestoreProjectRepository:
    return FirestoreProjectRepository(_firestore())


def run_repo() -> FirestoreRunRepository:
    return FirestoreRunRepository(_firestore())


def user_repo() -> FirestoreUserRepository:
    return FirestoreUserRepository(_firestore())


def batch_state_getter():
    """Return a callable get_state(batch_job_id) -> Batch state name, or None if the
    job no longer exists (deleted). Used by list_runs to reconcile non-terminal runs."""
    from google.api_core.exceptions import NotFound

    client = batch_v1.BatchServiceClient()
    s = settings()
    parent = f"projects/{s.project_id}/locations/{s.region}"

    def _get(batch_job_id: str):
        try:
            job = client.get_job(name=f"{parent}/jobs/{batch_job_id}")
            return job.status.state.name
        except NotFound:
            return None

    return _get
