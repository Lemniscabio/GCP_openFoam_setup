from functools import lru_cache

import google.auth
from google.auth.transport.requests import Request
from google.cloud import batch_v1
from google.cloud import storage as gcs

from core.batch_jobs import BatchJobBuilder, BatchSubmitter
from core.cases import CaseRepository
from core.config import Settings
from core.status import RunStatusService
from core.storage import GcsStorage
from core.uploads import SignedUrlService


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
    return BatchJobBuilder(bucket=s.bucket, image_uri=s.image_uri, job_service_account=s.job_service_account)


def submitter() -> BatchSubmitter:
    s = settings()
    return BatchSubmitter(s.project_id, s.region)


def status_service() -> RunStatusService:
    s = settings()
    return RunStatusService(batch_v1.BatchServiceClient(), storage(), s.project_id, s.region)
