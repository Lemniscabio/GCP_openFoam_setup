"""Keyless, per-file signed upload URLs for browser -> GCS uploads.

The browser has no GCP credentials, so the backend hands it a short-lived V4
signed PUT URL for each file. Signing is keyless: the attached service account
(`signer_email`) signs via IAM using its own OAuth access token (it must hold
roles/iam.serviceAccountTokenCreator on itself). No private key files, no
hand-rolled crypto — uses the official google-cloud-storage Blob.generate_signed_url.
"""
import datetime
from dataclasses import dataclass

DEFAULT_TTL = datetime.timedelta(minutes=30)


def case_prefix(project: str, case_id: str) -> str:
    return f"cases/{project}/{case_id}/"


def object_path(project: str, case_id: str, relative_path: str) -> str:
    """Map a case file under cases/<project>/<id>/case/."""
    return f"cases/{project}/{case_id}/case/{relative_path.lstrip('/')}"


@dataclass
class SignedUpload:
    object_path: str
    url: str
    method: str = "PUT"


class SignedUrlService:
    """Mints V4 signed PUT URLs, one per object, keyless.

    bucket: a google.cloud.storage.Bucket.
    signer_email: the SA that signs (needs Token Creator on itself).
    token_provider: a 0-arg callable returning a fresh OAuth access token for that SA.
    """

    def __init__(self, bucket, signer_email: str, token_provider,
                 ttl: datetime.timedelta = DEFAULT_TTL):
        self._bucket = bucket
        self._signer_email = signer_email
        self._token = token_provider
        self._ttl = ttl

    def put_url(self, obj_path: str, now: datetime.datetime) -> SignedUpload:
        url = self._bucket.blob(obj_path).generate_signed_url(
            version="v4",
            expiration=now + self._ttl,
            method="PUT",
            service_account_email=self._signer_email,  # keyless IAM signing
            access_token=self._token(),
        )
        return SignedUpload(object_path=obj_path, url=url)

    def get_url(self, obj_path: str, now: datetime.datetime) -> str:
        return self._bucket.blob(obj_path).generate_signed_url(
            version="v4",
            expiration=now + self._ttl,
            method="GET",
            service_account_email=self._signer_email,
            access_token=self._token(),
        )

    def put_urls_for_case(
        self,
        project: str,
        case_id: str,
        relative_paths: list[str],
        now: datetime.datetime,
    ) -> list[SignedUpload]:
        return [
            self.put_url(object_path(project, case_id, path), now)
            for path in relative_paths
        ]
