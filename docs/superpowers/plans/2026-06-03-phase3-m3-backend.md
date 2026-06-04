# Phase 3 — M3: Backend (FastAPI over core) + Deploy + CI — Implementation Plan

> **For agentic workers:** Tasks 1–9 are code (TDD) → driven via `codex exec`, orchestrator reviews `git diff` + runs the test command between tasks. Tasks 10–12 are a deploy/IAP/CI **runbook** (human-run on real GCP, Owner). Steps use `- [ ]`.
>
> **Reference:** spec `docs/superpowers/specs/2026-06-01-phase3-run-app-design.md`; M1 plan (engine) `2026-06-01-phase3-m1-core-engine.md`; project = **cfd-lemnisca** (# 380489820300), bucket **cfd-lemnisca-cases**.

**Goal:** A FastAPI service over the `core/` engine that serves the SPA + a REST API, verifies IAP identity, mints signed upload policies, submits Batch jobs (as the `of-batch-job` SA), and reports run status — deployed to Cloud Run behind IAP, with keyless GitHub Actions CI.

**Tech Stack:** FastAPI, uvicorn, `google-cloud-storage`/`-batch`, PyJWT + cryptography (IAP JWT), httpx (key fetch), pytest + FastAPI TestClient.

**Architecture:** One Cloud Run service (runtime SA `of-batch-backend@`). FastAPI serves built static SPA at `/` and JSON API at `/api/*`. Every `/api/*` call passes an IAP-JWT dependency that extracts the user. Uploads go **browser→GCS** via a per-case V4 signed POST policy the backend mints with `of-batch-backend`'s `signBlob`. GCS is source of truth; Batch API gives live state.

---

## File Structure
```
phase3-run-app/
  core/
    uploads.py        # NEW — SignedPolicyService (V4 POST policy via IAM signBlob)
    status.py         # NEW — RunStatusService (Batch state + GCS markers + sim%)
    batch_jobs.py     # MODIFY — set allocationPolicy.serviceAccount (job SA)
    config.py         # MODIFY — add job_service_account
  backend/
    __init__.py
    main.py           # FastAPI app, static mount, router include
    iap.py            # IAP JWT verification dependency -> User
    deps.py           # builds Settings + core services (DI)
    schemas.py        # pydantic request/response models
    routes_cases.py   # /api/cases:allocate, /finalize, GET /api/cases
    routes_jobs.py    # POST /api/jobs, GET /api/jobs, GET /api/jobs/{id}
  backend/static/     # built SPA lands here (M4); placeholder index.html for now
  backend/Dockerfile  # container for Cloud Run
  tests/
    test_uploads.py test_status.py test_batch_job_sa.py
    test_iap.py test_routes_cases.py test_routes_jobs.py
  requirements-backend.txt   # fastapi, uvicorn, pyjwt[crypto], httpx
.github/workflows/deploy.yml # CI (WIF → build → deploy)
```

---

### Task 1: Wire the job service account into BatchJobBuilder

**Files:** Modify `core/config.py`, `core/batch_jobs.py`; Test `tests/test_batch_job_sa.py`

- [ ] **Step 1: Failing test**
```python
# tests/test_batch_job_sa.py
from core.batch_jobs import BatchJobBuilder

def test_single_sets_job_service_account():
    spec = BatchJobBuilder(bucket="b", image_uri="img",
                           job_service_account="of-batch-job@cfd-lemnisca.iam.gserviceaccount.com").build_single(
        case_id="case_0001", machine_type="c2d-highcpu-2", cpu_milli=2000,
        memory_mib=4096, mpi_ranks=1, job_name="j")
    assert spec["allocationPolicy"]["serviceAccount"]["email"] == "of-batch-job@cfd-lemnisca.iam.gserviceaccount.com"

def test_multi_sets_job_service_account():
    spec = BatchJobBuilder(bucket="b", image_uri="img",
                           job_service_account="of-batch-job@cfd-lemnisca.iam.gserviceaccount.com").build_multi(
        case_ids=["case_0001","case_0002"], machine_type="c2d-highcpu-2", cpu_milli=2000,
        memory_mib=4096, mpi_ranks=1, job_name="j")
    assert spec["allocationPolicy"]["serviceAccount"]["email"].startswith("of-batch-job@")
```

- [ ] **Step 2: Run → fail** `cd phase3-run-app && .venv/bin/pytest tests/test_batch_job_sa.py -v` → TypeError (no such kwarg).

- [ ] **Step 3: Implement** — in `core/batch_jobs.py`, add `job_service_account: str | None = None` to `BatchJobBuilder.__init__` (store `self._job_sa`). In both `build_single`/`build_multi`, after building `allocationPolicy`, add the SA when set:
```python
        alloc = {"instances": [self._instance_policy(machine_type, provisioning_model, disk["disks"])]}
        if self._job_sa:
            alloc["serviceAccount"] = {"email": self._job_sa}
```
and use `alloc` as the `allocationPolicy` value in the returned dict (both methods). In `core/config.py` add to `Settings`:
```python
    job_service_account: str = os.environ.get("OF_JOB_SA", "of-batch-job@cfd-lemnisca.iam.gserviceaccount.com")
```

- [ ] **Step 4: Run → pass** `.venv/bin/pytest tests/test_batch_job_sa.py tests/test_batch_jobs.py -v` (new + existing builder tests green).

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(core): run Batch jobs as of-batch-job SA (least privilege)"`

---

### Task 2: `core/uploads.py` — SignedUrlService (keyless per-file V4 PUT URLs) — DONE

> **Built 2026-06-03 (differs from original plan):** google-cloud-storage 3.x removed `generate_signed_post_policy_v4`, so instead of one POST policy per case we mint one **V4 signed PUT URL per file** via the official `Blob.generate_signed_url` (keyless: `service_account_email` + `access_token`). No hand-rolled signing. API: `SignedUrlService(bucket, signer_email, token_provider).put_urls_for_case(case_id, relative_paths, now)`. Allocate (Task 6) takes the per-case file list and returns per-file URLs. Original POST-policy description below kept for context.

**Files:** Create `core/uploads.py`; Test `tests/test_uploads.py`

The browser uploads each file with one signed POST policy scoped to the case prefix. Signing uses the backend SA's IAM `signBlob` (no key file): `google-cloud-storage`'s `Bucket.generate_signed_post_policy_v4(...)` with `credentials` that support IAM signing (the attached SA + `access_token`).

- [ ] **Step 1: Failing test (structure, with a fake signer)**
```python
# tests/test_uploads.py
from core.uploads import build_post_policy_conditions, case_prefix

def test_case_prefix():
    assert case_prefix("case_0042") == "cases/case_0042/"

def test_policy_conditions_scope_prefix_and_limit_size():
    conds = build_post_policy_conditions("case_0042", max_bytes=5_000_000_000)
    # must restrict key to the case's tree and cap size
    assert ["starts-with", "$key", "cases/case_0042/case/"] in conds
    assert ["content-length-range", 0, 5_000_000_000] in conds
```

- [ ] **Step 2: Run → fail** `.venv/bin/pytest tests/test_uploads.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement `core/uploads.py`**
```python
# core/uploads.py
import datetime
from dataclasses import dataclass

DEFAULT_TTL = datetime.timedelta(minutes=30)
DEFAULT_MAX_BYTES = 5_000_000_000  # 5 GB per object cap

def case_prefix(case_id: str) -> str:
    return f"cases/{case_id}/"

def build_post_policy_conditions(case_id: str, max_bytes: int = DEFAULT_MAX_BYTES) -> list:
    """V4 POST policy conditions scoping uploads to this case's case/ tree + size cap."""
    return [
        ["starts-with", "$key", f"cases/{case_id}/case/"],
        ["content-length-range", 0, max_bytes],
    ]

@dataclass
class SignedPolicy:
    url: str
    fields: dict       # form fields the browser must POST alongside the file
    case_id: str

class SignedPolicyService:
    """Mints one V4 signed POST policy per case prefix using the attached SA's
    IAM signBlob (keyless). `bucket` is a google.cloud.storage.Bucket."""
    def __init__(self, bucket, signer_email: str, ttl: datetime.timedelta = DEFAULT_TTL):
        self._bucket = bucket
        self._signer_email = signer_email
        self._ttl = ttl

    def for_case(self, case_id: str, now: datetime.datetime) -> SignedPolicy:
        # blob_name acts as the default key; starts-with condition allows the whole tree.
        policy = self._bucket.generate_signed_post_policy_v4(
            blob_name=f"cases/{case_id}/case/",
            expiration=now + self._ttl,
            conditions=build_post_policy_conditions(case_id),
            service_account_email=self._signer_email,  # triggers IAM signBlob signing
        )
        return SignedPolicy(url=policy["url"], fields=policy["fields"], case_id=case_id)
```

- [ ] **Step 4: Run → pass** `.venv/bin/pytest tests/test_uploads.py -v`.

- [ ] **Step 5: Verify the real signing API offline** (catches lib-version mismatch like the mountOptions bug):
Run: `.venv/bin/python -c "from google.cloud import storage; import inspect; print('generate_signed_post_policy_v4' in dir(storage.Bucket)); print(inspect.signature(storage.Bucket.generate_signed_post_policy_v4))"`
Expected: `True` and a signature containing `blob_name, expiration, conditions, ... service_account_email`. If the param name differs in the installed version, adjust `for_case` accordingly and note the deviation.

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat(core): SignedPolicyService — per-case V4 POST upload policy (keyless signBlob)"`

---

### Task 3: `core/status.py` — RunStatusService

**Files:** Create `core/status.py`; Test `tests/test_status.py`

Merges Batch live state + GCS markers. Sim-progress is derived from the latest checkpoint timestep ÷ controlDict endTime (GCS-only; no log parsing).

- [ ] **Step 1: Failing test (pure helpers, with fakes)**
```python
# tests/test_status.py
from core.status import sim_progress_pct, parse_checkpoint_latest_timestep

def test_progress_pct():
    assert sim_progress_pct(latest_time=5.4, end_time=10.0) == 54
    assert sim_progress_pct(latest_time=0.0, end_time=10.0) == 0
    assert sim_progress_pct(latest_time=5.4, end_time=0.0) is None  # unknown endTime

def test_parse_latest_timestep_from_checkpoint_listing():
    paths = ["checkpoints/case_0001/c2d-highcpu-2/latest/processor0/5.4/p",
             "checkpoints/case_0001/c2d-highcpu-2/latest/processor0/2.0/p"]
    assert parse_checkpoint_latest_timestep(paths) == 5.4
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `core/status.py`**
```python
# core/status.py
import re
from dataclasses import dataclass

_TS_RE = re.compile(r"/processor\d+/(\d+(?:\.\d+)?)/")

def sim_progress_pct(latest_time: float, end_time: float):
    if not end_time or end_time <= 0:
        return None
    return int(max(0.0, min(1.0, latest_time / end_time)) * 100)

def parse_checkpoint_latest_timestep(paths: list[str]) -> float | None:
    times = [float(m.group(1)) for p in paths for m in [_TS_RE.search(p)] if m]
    return max(times) if times else None

@dataclass
class RunSummary:
    job_name: str
    state: str            # QUEUED/RUNNING/SUCCEEDED/FAILED
    case_ids: list[str]
    progress_pct: int | None

class RunStatusService:
    """`batch_client`: batch_v1.BatchServiceClient; `storage`: core StorageClient."""
    def __init__(self, batch_client, storage, project_id: str, region: str):
        self._b = batch_client; self._s = storage
        self._parent = f"projects/{project_id}/locations/{region}"

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        jobs = list(self._b.list_jobs(parent=self._parent))
        jobs.sort(key=lambda j: j.create_time.timestamp() if j.create_time else 0, reverse=True)
        out = []
        for j in jobs[:limit]:
            name = j.name.split("/")[-1]
            out.append(RunSummary(job_name=name, state=j.status.state.name, case_ids=[], progress_pct=None))
        return out

    def get_status(self, job_name: str, case_id: str, variant: str) -> dict:
        full = f"{self._parent}/jobs/{job_name}"
        j = self._b.get_job(name=full)
        events = [{"time": str(e.event_time), "desc": e.description} for e in j.status.status_events]
        cps = self._s.list_paths(f"checkpoints/{case_id}/{variant}/latest/")
        latest = parse_checkpoint_latest_timestep(cps)
        return {
            "job_name": job_name, "state": j.status.state.name, "events": events,
            "checkpoint_latest_timestep": latest,
        }
```

- [ ] **Step 4: Run → pass.**  - [ ] **Step 5: Commit** `git commit -m "feat(core): RunStatusService (Batch state + checkpoint sim-progress)"`

---

### Task 4: Backend scaffold + dependencies

**Files:** Create `backend/__init__.py`, `backend/deps.py`, `backend/main.py`, `backend/static/index.html`, `requirements-backend.txt`

- [ ] **Step 1: requirements-backend.txt**
```
fastapi>=0.110
uvicorn[standard]>=0.29
pyjwt[crypto]>=2.8
httpx>=0.27
```
Install: `cd phase3-run-app && .venv/bin/pip install -r requirements-backend.txt`

- [ ] **Step 2: `backend/deps.py`** (build core services once)
```python
# backend/deps.py
from functools import lru_cache
from google.cloud import storage as gcs, batch_v1
from core.config import Settings
from core.storage import GcsStorage
from core.cases import CaseRepository
from core.uploads import SignedUrlService
from core.batch_jobs import BatchJobBuilder, BatchSubmitter
from core.status import RunStatusService
import google.auth
from google.auth.transport.requests import Request

@lru_cache
def settings() -> Settings: return Settings()

@lru_cache
def _bucket(): return gcs.Client().bucket(settings().bucket)

@lru_cache
def _adc():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return creds

def _access_token() -> str:
    creds = _adc()
    if not creds.valid:
        creds.refresh(Request())
    return creds.token

def case_repo() -> CaseRepository: return CaseRepository(GcsStorage(settings().bucket))
def url_service() -> SignedUrlService:
    # keyless per-file V4 PUT URLs; the attached SA signs as itself via IAM
    return SignedUrlService(_bucket(), signer_email=settings().backend_service_account,
                            token_provider=_access_token)
def builder() -> BatchJobBuilder:
    s = settings()
    return BatchJobBuilder(bucket=s.bucket, image_uri=s.image_uri, job_service_account=s.job_service_account)
def submitter() -> BatchSubmitter:
    s = settings(); return BatchSubmitter(s.project_id, s.region)
def status_service() -> RunStatusService:
    s = settings(); return RunStatusService(batch_v1.BatchServiceClient(), GcsStorage(s.bucket), s.project_id, s.region)
```
Also add to `core/config.py` `Settings`: `backend_service_account: str = os.environ.get("OF_BACKEND_SA", "of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com")`.

- [ ] **Step 3: `backend/main.py`**
```python
# backend/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from backend.routes_cases import router as cases_router
from backend.routes_jobs import router as jobs_router

app = FastAPI(title="OpenFOAM Batch")
app.include_router(cases_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")

@app.get("/healthz")
def healthz(): return {"ok": True}

_static = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
```

- [ ] **Step 4:** `backend/static/index.html` = minimal placeholder `<!doctype html><title>OpenFOAM Batch</title><h1>OpenFOAM Batch — API up. SPA in M4.</h1>`. Create empty `backend/__init__.py`.

- [ ] **Step 5: Smoke** `cd phase3-run-app && .venv/bin/python -c "import backend.main; print('app ok')"` → `app ok` (routers import; will fail until Tasks 6–8 create the routers — so create empty routers first OR do this smoke after Task 8). Defer this smoke to Task 8.

- [ ] **Step 6: Commit** `git commit -m "feat(backend): FastAPI scaffold + DI wiring + static mount"`

---

### Task 5: `backend/iap.py` — IAP JWT verification dependency

**Files:** Create `backend/iap.py`; Test `tests/test_iap.py`

Validates the `x-goog-iap-jwt-assertion` header: ES256, `iss=https://cloud.google.com/iap`, `aud` = the IAP audience, and returns the user. Public keys cached from `https://www.gstatic.com/iap/verify/public_key`.

- [ ] **Step 1: Failing test** (inject a fake verifier so no network/keys in unit tests)
```python
# tests/test_iap.py
import pytest
from backend.iap import User, extract_user_from_claims

def test_extract_user():
    u = extract_user_from_claims({"email": "a@lemnisca.bio", "sub": "123"})
    assert u == User(email="a@lemnisca.bio", sub="123")

def test_missing_email_rejected():
    with pytest.raises(ValueError):
        extract_user_from_claims({"sub": "123"})
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `backend/iap.py`**
```python
# backend/iap.py
import os, time, functools
import jwt, httpx
from dataclasses import dataclass
from fastapi import Header, HTTPException

_IAP_KEYS_URL = "https://www.gstatic.com/iap/verify/public_key"
_ISS = "https://cloud.google.com/iap"

@dataclass(frozen=True)
class User:
    email: str
    sub: str

def extract_user_from_claims(claims: dict) -> "User":
    email = claims.get("email")
    if not email:
        raise ValueError("IAP JWT missing email claim")
    return User(email=email, sub=claims.get("sub", ""))

@functools.lru_cache
def _keys() -> dict:
    return httpx.get(_IAP_KEYS_URL, timeout=10).json()

def verify_iap_jwt(token: str, audience: str) -> "User":
    kid = jwt.get_unverified_header(token)["kid"]
    key = _keys()[kid]
    claims = jwt.decode(token, key, algorithms=["ES256"], audience=audience,
                        issuer=_ISS, options={"require": ["exp", "iat", "aud", "iss"]})
    return extract_user_from_claims(claims)

# FastAPI dependency. OF_IAP_AUDIENCE is set at deploy time (Task 10).
async def current_user(x_goog_iap_jwt_assertion: str = Header(default="")) -> "User":
    aud = os.environ.get("OF_IAP_AUDIENCE", "")
    if not x_goog_iap_jwt_assertion or not aud:
        # Local/dev (no IAP in front): allow a dev identity only when explicitly enabled.
        if os.environ.get("OF_DEV_NO_IAP") == "1":
            return User(email="dev@lemnisca.bio", sub="dev")
        raise HTTPException(status_code=401, detail="missing IAP assertion")
    try:
        return verify_iap_jwt(x_goog_iap_jwt_assertion, aud)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid IAP JWT: {e}")
```

- [ ] **Step 4: Run → pass** `.venv/bin/pytest tests/test_iap.py -v`.

- [ ] **Step 5: Commit** `git commit -m "feat(backend): IAP JWT verification dependency"`

---

### Task 6: `routes_cases.py` — allocate, finalize, list

**Files:** Create `backend/schemas.py`, `backend/routes_cases.py`; Test `tests/test_routes_cases.py`

- [ ] **Step 1: Failing test** (override deps with fakes; `OF_DEV_NO_IAP=1`)
```python
# tests/test_routes_cases.py
import os; os.environ["OF_DEV_NO_IAP"] = "1"
from fastapi.testclient import TestClient
from backend.main import app
from backend import deps
from core.storage import InMemoryStorage
from core.cases import CaseRepository

_store = InMemoryStorage()
app.dependency_overrides[deps.case_repo] = lambda: CaseRepository(_store)

class _FakeUrls:
    def put_urls_for_case(self, case_id, files, now):
        from core.uploads import SignedUpload, object_path
        return [SignedUpload(object_path=object_path(case_id, f), url=f"https://signed/{case_id}/{f}") for f in files]
app.dependency_overrides[deps.url_service] = lambda: _FakeUrls()
client = TestClient(app)

def test_allocate_returns_ids_and_urls():
    r = client.post("/api/cases:allocate", json={"cases": [{"files": ["0/U"]}, {"files": ["0/U", "system/controlDict"]}, {"files": ["0/p"]}]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["cases"]) == 3
    assert body["cases"][0]["case_id"].startswith("case_")
    assert body["cases"][1]["uploads"][1]["url"].startswith("https://signed/")

def test_finalize_writes_ready():
    cid = client.post("/api/cases:allocate", json={"cases": [{"files": ["0/U"]}]}).json()["cases"][0]["case_id"]
    r = client.post(f"/api/cases/{cid}:finalize", json={"openfoam_version": "12"})
    assert r.status_code == 200
    assert _store.object_exists(f"cases/{cid}/READY")

def test_list_cases():
    assert client.get("/api/cases").status_code == 200
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `backend/schemas.py`**
```python
# backend/schemas.py
from pydantic import BaseModel, Field

class CaseUpload(BaseModel):
    files: list[str] = Field(min_length=1)   # relative paths within the case dir (e.g. "0/U")

class AllocateReq(BaseModel):
    cases: list[CaseUpload] = Field(min_length=1, max_length=200)

class FinalizeReq(BaseModel):
    openfoam_version: str = "12"

class SubmitReq(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    machine_type: str
    spot: bool = False
```

- [ ] **Step 4: Implement `backend/routes_cases.py`**
```python
# backend/routes_cases.py
import json, datetime
from fastapi import APIRouter, Depends
from backend.deps import case_repo, url_service, settings
from backend.iap import current_user, User
from backend.schemas import AllocateReq, FinalizeReq
from core.storage import GcsStorage

router = APIRouter()

@router.post("/cases:allocate")
def allocate(req: AllocateReq, user: User = Depends(current_user),
             repo=Depends(case_repo), urls=Depends(url_service)):
    ids = repo.allocate_ids(len(req.cases))
    now = datetime.datetime.utcnow()
    out = []
    for cid, case in zip(ids, req.cases):
        uploads = urls.put_urls_for_case(cid, case.files, now)
        out.append({"case_id": cid,
                    "uploads": [{"object_path": u.object_path, "url": u.url, "method": u.method} for u in uploads]})
    return {"cases": out}

@router.post("/cases/{case_id}:finalize")
def finalize(case_id: str, req: FinalizeReq, user: User = Depends(current_user)):
    storage = GcsStorage(settings().bucket)
    manifest = json.dumps({"case_id": case_id, "solver_family": "openfoam",
                           "openfoam_version": req.openfoam_version,
                           "uploaded_by": user.email,
                           "uploaded_at_utc": datetime.datetime.utcnow().isoformat() + "Z"})
    storage.upload_bytes(f"cases/{case_id}/manifest.json", manifest.encode())
    storage.upload_bytes(f"cases/{case_id}/READY", (datetime.datetime.utcnow().isoformat() + "Z").encode())
    return {"case_id": case_id, "ready": True}

@router.get("/cases")
def list_cases(user: User = Depends(current_user), repo=Depends(case_repo)):
    return {"cases": [{"case_id": c.case_id, "ready": c.ready} for c in repo.list_cases()]}
```
(Note: `finalize` uses `GcsStorage` directly; in tests it writes to real GCS unless overridden. For the unit test, override `current_user` is automatic via `OF_DEV_NO_IAP`; for `finalize`'s storage, the test asserts on `_store` — so refactor `finalize` to take a `repo`/storage dep too. Add `storage=Depends(...)` returning `GcsStorage` in prod and override with `_store` in test. Implement a `deps.storage()` returning `GcsStorage(settings().bucket)` and depend on it here, so the test can override it to `_store`.)

- [ ] **Step 5: Run → pass.**  - [ ] **Step 6: Commit** `git commit -m "feat(backend): /api/cases allocate, finalize, list"`

---

### Task 7: `routes_jobs.py` — submit

**Files:** Create `backend/routes_jobs.py`; Test add to `tests/test_routes_jobs.py`

- [ ] **Step 1: Failing test** (fake submitter/builder/repo; `OF_DEV_NO_IAP=1`)
```python
# tests/test_routes_jobs.py
import os; os.environ["OF_DEV_NO_IAP"] = "1"
from fastapi.testclient import TestClient
from backend.main import app
from backend import deps

class _FakeSubmitter:
    def submit(self, job_name, spec): return f"projects/p/locations/us-central1/jobs/{job_name}"
app.dependency_overrides[deps.submitter] = lambda: _FakeSubmitter()
client = TestClient(app)

def test_submit_single():
    r = client.post("/api/jobs", json={"case_ids": ["case_0001"], "machine_type": "c2d-highcpu-2"})
    assert r.status_code == 200 and "of-case-0001-c2d-highcpu-2-" in r.json()["job_name"]

def test_submit_multi():
    r = client.post("/api/jobs", json={"case_ids": ["case_0001","case_0002"], "machine_type": "c2d-highcpu-2"})
    assert r.status_code == 200 and r.json()["job_name"].startswith("of-multi-")

def test_unknown_machine_400():
    r = client.post("/api/jobs", json={"case_ids": ["case_0001"], "machine_type": "n2-standard-4"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `backend/routes_jobs.py`**
```python
# backend/routes_jobs.py
import datetime
from fastapi import APIRouter, Depends, HTTPException
from backend.deps import builder, submitter, status_service
from backend.iap import current_user, User
from backend.schemas import SubmitReq
from core.machines import MachineCatalog
from core.naming import canonical_case_id, build_job_name

router = APIRouter()

@router.post("/jobs")
def submit(req: SubmitReq, user: User = Depends(current_user),
           b=Depends(builder), sub=Depends(submitter)):
    try:
        m = MachineCatalog().get(req.machine_type)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unknown machine {req.machine_type}")
    ids = [canonical_case_id(c) for c in req.case_ids]
    ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    prov = "SPOT" if req.spot else "STANDARD"
    common = dict(cpu_milli=m["cpu_milli"], memory_mib=m["memory_mib"],
                  mpi_ranks=m["default_mpi_ranks"], provisioning_model=prov)
    if len(ids) == 1:
        jn = build_job_name(ids[0], req.machine_type, ts)
        spec = b.build_single(case_id=ids[0], machine_type=req.machine_type, job_name=jn, **common)
    else:
        jn = build_job_name(None, req.machine_type, ts, multi=True)
        spec = b.build_multi(case_ids=ids, machine_type=req.machine_type, job_name=jn, **common)
    name = sub.submit(jn, spec)
    return {"job_name": jn, "name": name, "submitted_by": user.email}
```

- [ ] **Step 4: Run → pass.**  - [ ] **Step 5: Commit** `git commit -m "feat(backend): POST /api/jobs (single/multi submit)"`

---

### Task 8: `routes_jobs.py` — list runs + detail; backend smoke

**Files:** Modify `backend/routes_jobs.py`; Test add to `tests/test_routes_jobs.py`

- [ ] **Step 1: Failing test** (fake status_service)
```python
# add to tests/test_routes_jobs.py
class _FakeStatus:
    def list_runs(self, limit=50): 
        from core.status import RunSummary
        return [RunSummary(job_name="of-case-0001-c2d-highcpu-2-x", state="RUNNING", case_ids=["case_0001"], progress_pct=54)]
    def get_status(self, job_name, case_id, variant):
        return {"job_name": job_name, "state": "RUNNING", "events": [], "checkpoint_latest_timestep": 5.4}
app.dependency_overrides[deps.status_service] = lambda: _FakeStatus()

def test_list_runs():
    r = client.get("/api/jobs")
    assert r.status_code == 200 and r.json()["runs"][0]["state"] == "RUNNING"

def test_run_detail():
    r = client.get("/api/jobs/of-case-0001-c2d-highcpu-2-x?case_id=case_0001&variant=c2d-highcpu-2")
    assert r.status_code == 200 and r.json()["checkpoint_latest_timestep"] == 5.4
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — append to `backend/routes_jobs.py`:
```python
@router.get("/jobs")
def list_runs(user: User = Depends(current_user), st=Depends(status_service)):
    return {"runs": [r.__dict__ for r in st.list_runs()]}

@router.get("/jobs/{job_name}")
def run_detail(job_name: str, case_id: str, variant: str,
               user: User = Depends(current_user), st=Depends(status_service)):
    return st.get_status(job_name, case_id, variant)
```

- [ ] **Step 4: Run full suite + app smoke**
`cd phase3-run-app && OF_DEV_NO_IAP=1 .venv/bin/pytest -q` (all green) and `.venv/bin/python -c "import backend.main; print('app ok')"`.

- [ ] **Step 5: Commit** `git commit -m "feat(backend): GET /api/jobs list + detail"`

---

### Task 9: Backend Dockerfile

**Files:** Create `backend/Dockerfile`, `backend/.dockerignore`

- [ ] **Step 1: `backend/Dockerfile`** (built from `phase3-run-app/` context)
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements-backend.txt ./
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir -r requirements-backend.txt
COPY core ./core
COPY backend ./backend
ENV PORT=8080
CMD ["sh","-c","uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
```
- [ ] **Step 2:** `backend/.dockerignore`: `.venv\n__pycache__\ntests\n*.pyc`
- [ ] **Step 3: Build locally to verify** `docker build -f phase3-run-app/backend/Dockerfile -t of-backend:dev phase3-run-app` → builds clean.
- [ ] **Step 4: Commit** `git commit -m "feat(backend): Cloud Run Dockerfile"`

---

### Task 10 (RUNBOOK, Owner): Deploy to Cloud Run + enable IAP

Single-line commands (paste-safe). Project `cfd-lemnisca`.

- [ ] **Step 1: Build+push backend image to AR (amd64)**
```
docker buildx build --platform linux/amd64 -f phase3-run-app/backend/Dockerfile -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:0.1.0 --push phase3-run-app
```
- [ ] **Step 2: Deploy to Cloud Run as the backend SA, no public access**
```
gcloud run deploy of-batch-app --image us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:0.1.0 --region us-central1 --service-account of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com --no-allow-unauthenticated --project cfd-lemnisca
```
- [ ] **Step 3: Enable IAP on the service**
```
gcloud beta run services update of-batch-app --region us-central1 --iap --project cfd-lemnisca
```
- [ ] **Step 4: Grant the IAP service agent run.invoker**
```
gcloud run services add-iam-policy-binding of-batch-app --region us-central1 --member="serviceAccount:service-380489820300@gcp-sa-iap.iam.gserviceaccount.com" --role="roles/run.invoker" --project cfd-lemnisca
```
- [ ] **Step 5: Grant the whole org access via IAP**
```
gcloud beta iap web add-iam-policy-binding --resource-type=cloud-run --service=of-batch-app --region=us-central1 --member="domain:lemnisca.bio" --role="roles/iap.httpsResourceAccessor" --project cfd-lemnisca
```
- [ ] **Step 6: Set the IAP audience env on the service** so `backend/iap.py` can verify (`OF_IAP_AUDIENCE`). The audience format for Cloud Run + IAP is `/projects/380489820300/global/backendServices/<id>` (one-click IAP) — fetch it from the IAP settings/console, then:
```
gcloud run services update of-batch-app --region us-central1 --update-env-vars OF_IAP_AUDIENCE=<AUDIENCE> --project cfd-lemnisca
```
- [ ] **Step 7: Verify** — open the service URL in a browser (must be a `lemnisca.bio` account), confirm the IAP sign-in then the placeholder page; `curl` without auth → 403.

---

### Task 11 (RUNBOOK): GitHub Actions CI via WIF

**Files:** Create `.github/workflows/deploy.yml`

- [ ] **Step 1: Workflow** (test-gated; keyless via the `of-github-pool` provider from M2)
```yaml
name: deploy
on:
  push: { branches: [main] }
  pull_request: {}
permissions: { contents: read, id-token: write }
jobs:
  test-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Tests (gate)
        run: |
          cd phase3-run-app
          pip install -e ".[dev]" -r requirements-backend.txt
          OF_DEV_NO_IAP=1 pytest -q
          cd .. && bash openfoam-batch/tests/run_all.sh
      - id: auth
        if: github.ref == 'refs/heads/main'
        uses: google-github-actions/auth@v2
        with:
          project_id: cfd-lemnisca
          workload_identity_provider: projects/380489820300/locations/global/workloadIdentityPools/of-github-pool/providers/github-provider
          service_account: of-ci-deployer@cfd-lemnisca.iam.gserviceaccount.com
      - if: github.ref == 'refs/heads/main'
        uses: google-github-actions/setup-gcloud@v2
      - name: Build + deploy
        if: github.ref == 'refs/heads/main'
        run: |
          gcloud auth configure-docker us-central1-docker.pkg.dev --quiet
          docker buildx build --platform linux/amd64 -f phase3-run-app/backend/Dockerfile \
            -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:${{ github.sha }} --push phase3-run-app
          gcloud run deploy of-batch-app --image us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:${{ github.sha }} \
            --region us-central1 --service-account of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com \
            --no-allow-unauthenticated --project cfd-lemnisca
```
- [ ] **Step 2:** Push a branch + open a PR → confirm the test job runs (no deploy on PR). Merge → confirm deploy job authenticates via WIF and updates the service.
- [ ] **Step 3: Commit** `git add .github/workflows/deploy.yml && git commit -m "ci: test-gated Cloud Run deploy via WIF"`

---

## Self-Review
- **Spec §2 one Cloud Run service serving SPA+API behind IAP** → Tasks 4, 10. ✓
- **Signed POST policy per case (keyless)** → Task 2 + Task 6 allocate. ✓
- **IAP JWT verify, read user** → Task 5, used in all routes. ✓
- **Jobs run as of-batch-job SA** → Task 1. ✓
- **Endpoints: allocate/finalize/list/submit/runs/detail** → Tasks 6–8. ✓
- **Status from Batch + GCS markers + sim%** → Task 3, Task 8. ✓
- **Deploy + domain IAP binding** → Task 10 (domain:lemnisca.bio). ✓
- **CI via WIF (of-github-pool)** → Task 11. ✓
- **Out of scope (M4):** the real SPA (placeholder served now); polling UI, detail drawer, suggested-machine UI.
- **Placeholder/verify notes:** Task 2 Step 5 and Task 6 Step 4 flag lib/DI specifics to confirm at implementation; not vague TODOs.
- **Type consistency:** `SignedPolicy.{url,fields}`, `RunSummary` fields, `User.{email,sub}`, `Settings.{backend_service_account,job_service_account}` used consistently across deps/routes/tests.

## Execution Handoff
Tasks 1–9 via `codex exec` (orchestrator reviews + runs `OF_DEV_NO_IAP=1 pytest -q` between tasks). Tasks 10–11 are human-run on `cfd-lemnisca` (Owner) after M2 setup completes. The `OF_IAP_AUDIENCE` value (Task 10 Step 6) is the one piece fetched from the live IAP config.
