# Firestore Audit & Persistence Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Firestore-backed persistence/audit layer that records every case and every run, with guaranteed run-state updates via Batch→Pub/Sub.

**Architecture:** Two `of_`-prefixed Firestore collections (`of_runs` keyed by Batch job id, `of_cases` keyed by case id). Backend writes records at submit/finalize; a Pub/Sub push endpoint updates run state on Batch job-state changes. Repositories follow the existing Protocol + in-memory-fake pattern so unit tests stay offline.

**Tech Stack:** Python 3.12, FastAPI, `google-cloud-firestore`, `google-cloud-batch`, Pydantic, pytest. Frontend: React/TS (Vitest). Infra: bash + gcloud.

**Spec:** `docs/superpowers/specs/2026-06-05-firestore-audit-foundation-design.md`

**Working directory for all paths below:** `phase3-run-app/`
**Run python tests with:** `OF_DEV_NO_IAP=1 .venv/bin/pytest -q`

---

## File Structure

**Create:**
- `core/run_repo.py` — `RunRepository` Protocol, `RunRecord` dataclass, `InMemoryRunRepository`, `FirestoreRunRepository`.
- `core/case_records.py` — `CaseRecordRepository` Protocol, `CaseRecord` dataclass, `InMemoryCaseRecordRepository`, `FirestoreCaseRecordRepository`.
- `backend/routes_internal.py` — `POST /internal/batch-events` Pub/Sub push handler.
- `backend/pubsub_auth.py` — verify the OIDC token on Pub/Sub push requests.
- `tests/test_run_repo.py`, `tests/test_case_records.py`, `tests/test_routes_internal.py`, `tests/test_pubsub_auth.py`.

**Modify:**
- `requirements-backend.txt` — add `google-cloud-firestore`.
- `core/config.py` — add `pubsub_topic`, `pubsub_push_sa`, `firestore_database` settings.
- `backend/schemas.py` — add `name` to case allocate/finalize.
- `core/batch_jobs.py` — add `notifications` block to job spec; return `batch_job_id`.
- `backend/routes_cases.py` — write `of_cases` at finalize.
- `backend/routes_jobs.py` — write `of_runs` at submit; resolve `case_names`; return `batch_job_id`.
- `backend/deps.py` — provide `run_repo()`, `case_record_repo()`.
- `backend/main.py` — include internal router.
- `frontend/src/views/UploadView.tsx`, `frontend/src/lib/upload.ts`, `frontend/src/lib/api.ts` — capture + send case `name`.
- `infra/setup-cfd-lemnisca.sh` — Firestore, topic, push subscription, IAM.

---

## Task 1: Add Firestore dependency + settings

**Files:**
- Modify: `requirements-backend.txt`
- Modify: `core/config.py:18-31` (the `Settings` dataclass)
- Test: `tests/test_config.py`

- [ ] **Step 1: Add the dependency**

Add this line to `requirements-backend.txt`:
```
google-cloud-firestore>=2.16
```
Then install: `.venv/bin/pip install -r requirements-backend.txt`

- [ ] **Step 2: Write the failing test**

Append to `tests/test_config.py`:
```python
def test_settings_have_pubsub_and_firestore_defaults():
    from core.config import Settings
    s = Settings()
    assert s.pubsub_topic == "of-batch-job-state"
    assert s.firestore_database == "(default)"
    assert s.pubsub_push_sa.endswith("@cfd-lemnisca.iam.gserviceaccount.com")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_config.py::test_settings_have_pubsub_and_firestore_defaults -q`
Expected: FAIL (AttributeError: pubsub_topic).

- [ ] **Step 4: Add the settings fields**

In `core/config.py`, inside the `Settings` dataclass (after `scratch_root`), add:
```python
    firestore_database: str = os.environ.get("OF_FIRESTORE_DB", "(default)")
    pubsub_topic: str = os.environ.get("OF_PUBSUB_TOPIC", "of-batch-job-state")
    pubsub_push_sa: str = os.environ.get(
        "OF_PUBSUB_PUSH_SA", "of-pubsub-push@cfd-lemnisca.iam.gserviceaccount.com"
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add requirements-backend.txt core/config.py tests/test_config.py
git commit -m "feat(config): add Firestore + Pub/Sub settings"
```

---

## Task 2: RunRepository interface + in-memory fake

**Files:**
- Create: `core/run_repo.py`
- Test: `tests/test_run_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_repo.py`:
```python
import datetime

from core.run_repo import RunRecord, InMemoryRunRepository


def _rec(job_id="of-multi-x-20260101", state="SUBMITTED"):
    return RunRecord(
        batch_job_id=job_id,
        job_name="windtunnel-v3",
        submitted_by="kartikey.attri@lemnisca.bio",
        submitted_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        region="us-central1",
        machine_type="c2d-highcpu-32",
        mpi_ranks=16,
        spot=False,
        case_ids=["case_0006"],
        case_names=["Wind Tunnel v3"],
        state=state,
        finished_at=None,
    )


def test_create_then_get():
    repo = InMemoryRunRepository()
    repo.create(_rec())
    got = repo.get("of-multi-x-20260101")
    assert got.job_name == "windtunnel-v3"
    assert got.state == "SUBMITTED"


def test_list_orders_newest_first():
    repo = InMemoryRunRepository()
    repo.create(_rec(job_id="a", state="SUBMITTED"))
    later = _rec(job_id="b")
    later.submitted_at = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    repo.create(later)
    ids = [r.batch_job_id for r in repo.list_recent(limit=10)]
    assert ids == ["b", "a"]


def test_update_state_sets_finished_at_on_terminal():
    repo = InMemoryRunRepository()
    repo.create(_rec())
    fin = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    repo.update_state("of-multi-x-20260101", "SUCCEEDED", finished_at=fin)
    got = repo.get("of-multi-x-20260101")
    assert got.state == "SUCCEEDED"
    assert got.finished_at == fin


def test_update_state_is_monotonic_never_regresses_terminal():
    repo = InMemoryRunRepository()
    repo.create(_rec())
    repo.update_state("of-multi-x-20260101", "SUCCEEDED", finished_at=None)
    repo.update_state("of-multi-x-20260101", "RUNNING", finished_at=None)  # late/duplicate
    assert repo.get("of-multi-x-20260101").state == "SUCCEEDED"


def test_get_missing_returns_none():
    assert InMemoryRunRepository().get("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_run_repo.py -q`
Expected: FAIL (ModuleNotFoundError: core.run_repo).

- [ ] **Step 3: Write the implementation**

Create `core/run_repo.py`:
```python
import datetime
from dataclasses import dataclass, field
from typing import Protocol

# Batch job states considered terminal (no further transitions expected).
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "DELETION_IN_PROGRESS", "CANCELLED"}


@dataclass
class RunRecord:
    batch_job_id: str          # doc id
    job_name: str
    submitted_by: str
    submitted_at: datetime.datetime
    region: str
    machine_type: str
    mpi_ranks: int
    spot: bool
    case_ids: list[str]
    case_names: list[str]
    state: str = "SUBMITTED"
    finished_at: datetime.datetime | None = None


class RunRepository(Protocol):
    def create(self, record: RunRecord) -> None: ...
    def get(self, batch_job_id: str) -> RunRecord | None: ...
    def list_recent(self, limit: int = 50) -> list[RunRecord]: ...
    def update_state(
        self, batch_job_id: str, state: str,
        finished_at: datetime.datetime | None = None,
    ) -> None:
        """Advance a run's state. Idempotent: a record already in a terminal state
        is never moved back to a non-terminal one (handles late/duplicate events).
        Upserts a minimal record if the id is unknown."""
        ...


class InMemoryRunRepository:
    """Test fake. Stores RunRecords in a dict keyed by batch_job_id."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create(self, record: RunRecord) -> None:
        self._runs[record.batch_job_id] = record

    def get(self, batch_job_id: str) -> RunRecord | None:
        return self._runs.get(batch_job_id)

    def list_recent(self, limit: int = 50) -> list[RunRecord]:
        ordered = sorted(self._runs.values(), key=lambda r: r.submitted_at, reverse=True)
        return ordered[:limit]

    def update_state(self, batch_job_id, state, finished_at=None) -> None:
        rec = self._runs.get(batch_job_id)
        if rec is None:
            # unknown id: upsert a minimal placeholder so the event is not lost
            rec = RunRecord(
                batch_job_id=batch_job_id, job_name=batch_job_id,
                submitted_by="unknown",
                submitted_at=datetime.datetime.now(datetime.timezone.utc),
                region="", machine_type="", mpi_ranks=0, spot=False,
                case_ids=[], case_names=[],
            )
            self._runs[batch_job_id] = rec
        if rec.state in TERMINAL_STATES and state not in TERMINAL_STATES:
            return  # never regress a terminal state
        rec.state = state
        if finished_at is not None:
            rec.finished_at = finished_at
```

- [ ] **Step 4: Run test to verify it passes**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_run_repo.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add core/run_repo.py tests/test_run_repo.py
git commit -m "feat(core): RunRepository interface + in-memory fake"
```

---

## Task 3: FirestoreRunRepository (real implementation)

**Files:**
- Modify: `core/run_repo.py` (append the Firestore impl)

> No offline unit test (requires Firestore/emulator). It is exercised via the same
> `RunRepository` interface the in-memory fake validates. Optionally run against the
> Firestore emulator manually (see Task 15 notes).

- [ ] **Step 1: Append the Firestore implementation to `core/run_repo.py`**

```python
class FirestoreRunRepository:
    """Production RunRepository backed by Firestore Native mode."""

    COLLECTION = "of_runs"

    def __init__(self, client, collection: str = COLLECTION) -> None:
        self._c = client
        self._col = collection

    def _doc(self, batch_job_id: str):
        return self._c.collection(self._col).document(batch_job_id)

    def create(self, record: RunRecord) -> None:
        self._doc(record.batch_job_id).set(
            {
                "batch_job_id": record.batch_job_id,
                "job_name": record.job_name,
                "submitted_by": record.submitted_by,
                "submitted_at": record.submitted_at,
                "region": record.region,
                "machine_type": record.machine_type,
                "mpi_ranks": record.mpi_ranks,
                "spot": record.spot,
                "case_ids": record.case_ids,
                "case_names": record.case_names,
                "state": record.state,
                "finished_at": record.finished_at,
            }
        )

    def get(self, batch_job_id: str) -> RunRecord | None:
        snap = self._doc(batch_job_id).get()
        if not snap.exists:
            return None
        return self._from_dict(snap.to_dict())

    def list_recent(self, limit: int = 50) -> list[RunRecord]:
        from google.cloud.firestore import Query  # type: ignore
        q = (
            self._c.collection(self._col)
            .order_by("submitted_at", direction=Query.DESCENDING)
            .limit(limit)
        )
        return [self._from_dict(d.to_dict()) for d in q.stream()]

    def update_state(self, batch_job_id, state, finished_at=None) -> None:
        from google.cloud import firestore  # type: ignore

        @firestore.transactional
        def _txn(txn):
            ref = self._doc(batch_job_id)
            snap = ref.get(transaction=txn)
            cur = snap.to_dict() if snap.exists else None
            if cur and cur.get("state") in TERMINAL_STATES and state not in TERMINAL_STATES:
                return
            data = {"state": state}
            if finished_at is not None:
                data["finished_at"] = finished_at
            if not snap.exists:
                data["batch_job_id"] = batch_job_id
                data["job_name"] = batch_job_id
            txn.set(ref, data, merge=True)

        _txn(self._c.transaction())

    @staticmethod
    def _from_dict(d: dict) -> RunRecord:
        return RunRecord(
            batch_job_id=d["batch_job_id"],
            job_name=d.get("job_name", d["batch_job_id"]),
            submitted_by=d.get("submitted_by", "unknown"),
            submitted_at=d.get("submitted_at"),
            region=d.get("region", ""),
            machine_type=d.get("machine_type", ""),
            mpi_ranks=d.get("mpi_ranks", 0),
            spot=d.get("spot", False),
            case_ids=d.get("case_ids", []),
            case_names=d.get("case_names", []),
            state=d.get("state", "SUBMITTED"),
            finished_at=d.get("finished_at"),
        )
```

- [ ] **Step 2: Sanity import check**

Run: `OF_DEV_NO_IAP=1 .venv/bin/python -c "from core.run_repo import FirestoreRunRepository; print('ok')"`
Expected: `ok` (no import errors).

- [ ] **Step 3: Commit**

```bash
git add core/run_repo.py
git commit -m "feat(core): FirestoreRunRepository implementation"
```

---

## Task 4: CaseRecordRepository interface + in-memory fake

**Files:**
- Create: `core/case_records.py`
- Test: `tests/test_case_records.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_case_records.py`:
```python
import datetime

from core.case_records import CaseRecord, InMemoryCaseRecordRepository


def _rec(case_id="case_0006", name="Wind Tunnel v3"):
    return CaseRecord(
        case_id=case_id, name=name,
        uploaded_by="kartikey.attri@lemnisca.bio",
        uploaded_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        ready=True,
    )


def test_upsert_then_get():
    repo = InMemoryCaseRecordRepository()
    repo.upsert(_rec())
    got = repo.get("case_0006")
    assert got.name == "Wind Tunnel v3"
    assert got.ready is True


def test_names_for_resolves_in_order_with_fallback():
    repo = InMemoryCaseRecordRepository()
    repo.upsert(_rec("case_0006", "Wind Tunnel v3"))
    # case_0007 not recorded -> falls back to the id
    assert repo.names_for(["case_0006", "case_0007"]) == ["Wind Tunnel v3", "case_0007"]


def test_get_missing_returns_none():
    assert InMemoryCaseRecordRepository().get("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_case_records.py -q`
Expected: FAIL (ModuleNotFoundError: core.case_records).

- [ ] **Step 3: Write the implementation**

Create `core/case_records.py`:
```python
import datetime
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CaseRecord:
    case_id: str          # doc id
    name: str
    uploaded_by: str
    uploaded_at: datetime.datetime
    ready: bool = False


class CaseRecordRepository(Protocol):
    def upsert(self, record: CaseRecord) -> None: ...
    def get(self, case_id: str) -> CaseRecord | None: ...
    def names_for(self, case_ids: list[str]) -> list[str]:
        """Return the friendly name for each id, falling back to the id itself
        when no record exists."""
        ...


class InMemoryCaseRecordRepository:
    """Test fake."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}

    def upsert(self, record: CaseRecord) -> None:
        self._cases[record.case_id] = record

    def get(self, case_id: str) -> CaseRecord | None:
        return self._cases.get(case_id)

    def names_for(self, case_ids: list[str]) -> list[str]:
        out = []
        for cid in case_ids:
            rec = self._cases.get(cid)
            out.append(rec.name if rec else cid)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_case_records.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add core/case_records.py tests/test_case_records.py
git commit -m "feat(core): CaseRecordRepository interface + in-memory fake"
```

---

## Task 5: FirestoreCaseRecordRepository (real implementation)

**Files:**
- Modify: `core/case_records.py` (append)

- [ ] **Step 1: Append the Firestore implementation**

```python
class FirestoreCaseRecordRepository:
    """Production CaseRecordRepository backed by Firestore."""

    COLLECTION = "of_cases"

    def __init__(self, client, collection: str = COLLECTION) -> None:
        self._c = client
        self._col = collection

    def _doc(self, case_id: str):
        return self._c.collection(self._col).document(case_id)

    def upsert(self, record: CaseRecord) -> None:
        self._doc(record.case_id).set(
            {
                "case_id": record.case_id,
                "name": record.name,
                "uploaded_by": record.uploaded_by,
                "uploaded_at": record.uploaded_at,
                "ready": record.ready,
            },
            merge=True,
        )

    def get(self, case_id: str) -> CaseRecord | None:
        snap = self._doc(case_id).get()
        if not snap.exists:
            return None
        d = snap.to_dict()
        return CaseRecord(
            case_id=d["case_id"], name=d.get("name", d["case_id"]),
            uploaded_by=d.get("uploaded_by", "unknown"),
            uploaded_at=d.get("uploaded_at"), ready=d.get("ready", False),
        )

    def names_for(self, case_ids: list[str]) -> list[str]:
        return [(self.get(cid).name if self.get(cid) else cid) for cid in case_ids]
```

- [ ] **Step 2: Sanity import check**

Run: `OF_DEV_NO_IAP=1 .venv/bin/python -c "from core.case_records import FirestoreCaseRecordRepository; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add core/case_records.py
git commit -m "feat(core): FirestoreCaseRecordRepository implementation"
```

---

## Task 6: Add `name` to the case allocate/finalize schemas

**Files:**
- Modify: `backend/schemas.py:4-13`
- Test: `tests/test_routes_cases.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes_cases.py`:
```python
def test_finalize_accepts_optional_name():
    from backend.schemas import FinalizeReq
    req = FinalizeReq(name="Wind Tunnel v3")
    assert req.name == "Wind Tunnel v3"
    # name is optional; omitting it is allowed
    assert FinalizeReq().name is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_cases.py::test_finalize_accepts_optional_name -q`
Expected: FAIL (unexpected kwarg `name`).

- [ ] **Step 3: Add the field**

In `backend/schemas.py`, change `FinalizeReq`:
```python
class FinalizeReq(BaseModel):
    openfoam_version: str = "12"
    name: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_cases.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/schemas.py tests/test_routes_cases.py
git commit -m "feat(schemas): optional case name on finalize"
```

---

## Task 7: Write `of_cases` at finalize

**Files:**
- Modify: `backend/routes_cases.py:41-58` (the `finalize` route)
- Modify: `backend/deps.py` (add `case_record_repo`)
- Test: `tests/test_routes_cases.py`

- [ ] **Step 1: Add the dependency provider (temporary in-memory default for tests)**

In `backend/deps.py`, add at the end:
```python
from core.case_records import FirestoreCaseRecordRepository
from core.run_repo import FirestoreRunRepository


@lru_cache
def _firestore():
    from google.cloud import firestore
    return firestore.Client(project=settings().project_id, database=settings().firestore_database)


def case_record_repo() -> FirestoreCaseRecordRepository:
    return FirestoreCaseRecordRepository(_firestore())


def run_repo() -> FirestoreRunRepository:
    return FirestoreRunRepository(_firestore())
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_routes_cases.py` (uses FastAPI dependency override with the in-memory fake — match the existing override style already used in this test file):
```python
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
```

> If `tests/test_routes_cases.py` does not already expose `client`, `mem_storage`,
> and a fake-repo fixture, add pytest fixtures at the top of the file that build a
> `TestClient` with `app.dependency_overrides` set to `InMemoryStorage`,
> `InMemoryCaseRecordRepository`, and (where needed) `InMemoryRunRepository`
> instances. Reuse the override pattern already present for `storage`.

- [ ] **Step 3: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_cases.py::test_finalize_writes_case_record -q`
Expected: FAIL (no case record written / fixture missing).

- [ ] **Step 4: Update the finalize route**

In `backend/routes_cases.py`, update imports and the `finalize` signature/body:
```python
import datetime
import json

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import User, current_user
from backend.deps import case_repo, case_record_repo, storage, url_service
from backend.schemas import AllocateReq, FinalizeReq
from core.case_records import CaseRecord
```
```python
@router.post("/cases/{case_id}:finalize")
def finalize(
    case_id: str,
    req: FinalizeReq,
    user: User = Depends(current_user),
    repo=Depends(case_repo),
    records=Depends(case_record_repo),
    store=Depends(storage),
):
    if not repo.exists(case_id):
        raise HTTPException(status_code=404, detail="unknown case")
    if not store.list_paths(f"cases/{case_id}/case/"):
        raise HTTPException(status_code=400, detail="case incomplete: missing case/ tree")
    if not store.object_exists(f"cases/{case_id}/case/command.sh"):
        raise HTTPException(status_code=400, detail="case incomplete: missing case/command.sh")

    now = datetime.datetime.now(datetime.timezone.utc)
    uploaded_at = now.isoformat()
    manifest = {
        "case_id": case_id,
        "solver_family": "openfoam",
        "openfoam_version": req.openfoam_version,
        "uploaded_by": user.email,
        "uploaded_at_utc": uploaded_at,
    }
    store.upload_bytes(f"cases/{case_id}/manifest.json", json.dumps(manifest).encode())
    store.upload_bytes(f"cases/{case_id}/READY", uploaded_at.encode())
    records.upsert(CaseRecord(
        case_id=case_id, name=(req.name or case_id),
        uploaded_by=user.email, uploaded_at=now, ready=True,
    ))
    return {"case_id": case_id, "ready": True}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_cases.py -q`
Expected: PASS (all, including the new one).

- [ ] **Step 6: Commit**

```bash
git add backend/routes_cases.py backend/deps.py tests/test_routes_cases.py
git commit -m "feat(cases): persist of_cases record at finalize"
```

---

## Task 8: Add Pub/Sub notifications to the Batch job spec

**Files:**
- Modify: `core/batch_jobs.py` (`build_single`/`build_multi` job dict + constructor)
- Test: `tests/test_batch_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_batch_jobs.py`:
```python
def test_job_spec_includes_pubsub_notifications():
    from core.batch_jobs import BatchJobBuilder
    b = BatchJobBuilder(
        bucket="buck", image_uri="img:1",
        pubsub_topic="projects/cfd-lemnisca/topics/of-batch-job-state",
    )
    spec = b.build_single(
        case_id="case_0006", machine_type="c2d-highcpu-8",
        cpu_milli=8000, memory_mib=16384, mpi_ranks=4, job_name="j",
    )
    notes = spec["notifications"]
    assert notes[0]["pubsubTopic"] == "projects/cfd-lemnisca/topics/of-batch-job-state"
    assert notes[0]["message"]["type"] == "JOB_STATE_CHANGED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_batch_jobs.py::test_job_spec_includes_pubsub_notifications -q`
Expected: FAIL (unexpected kwarg `pubsub_topic` / no `notifications` key).

- [ ] **Step 3: Implement**

In `core/batch_jobs.py`, add `pubsub_topic` to the constructor:
```python
    def __init__(self, bucket: str, image_uri: str, job_service_account: str | None = None,
                 pubsub_topic: str | None = None) -> None:
        self._bucket = bucket
        self._image = image_uri
        self._job_sa = job_service_account
        self._pubsub_topic = pubsub_topic
```
Add a helper:
```python
    def _notifications(self) -> list[dict]:
        if not self._pubsub_topic:
            return []
        return [{"pubsubTopic": self._pubsub_topic, "message": {"type": "JOB_STATE_CHANGED"}}]
```
In BOTH `build_single` and `build_multi`, add `"notifications": self._notifications()` to the returned job dict (alongside `taskGroups`, `allocationPolicy`, `logsPolicy`, `labels`). Example for the return dict:
```python
        return {
            "taskGroups": [{"taskCount": 1, "parallelism": 1, "taskSpec": task_spec}],
            "allocationPolicy": alloc,
            "logsPolicy": {"destination": "CLOUD_LOGGING"},
            "labels": {"app": "openfoam"},
            "notifications": self._notifications(),
        }
```

- [ ] **Step 4: Verify the spec still parses into the Batch proto**

Run:
```bash
OF_DEV_NO_IAP=1 .venv/bin/python -c "
from core.batch_jobs import BatchJobBuilder
from google.cloud import batch_v1
from google.protobuf import json_format
b = BatchJobBuilder('buck','img:1', pubsub_topic='projects/p/topics/t')
spec = b.build_single(case_id='case_0006', machine_type='c2d-highcpu-8', cpu_milli=8000, memory_mib=16384, mpi_ranks=4, job_name='j')
json_format.ParseDict(spec, batch_v1.Job()._pb); print('proto OK')
"
```
Expected: `proto OK` (confirms `notifications`/`pubsubTopic`/`message.type` are valid Batch fields).

- [ ] **Step 5: Run tests**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_batch_jobs.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/batch_jobs.py tests/test_batch_jobs.py
git commit -m "feat(batch): emit Pub/Sub JOB_STATE_CHANGED notifications"
```

---

## Task 9: Write `of_runs` at submit + resolve case names + wire topic

**Files:**
- Modify: `backend/routes_jobs.py:14-54` (the `submit` route)
- Modify: `backend/deps.py` (`builder()` passes `pubsub_topic`)
- Test: `tests/test_routes_jobs.py`

- [ ] **Step 1: Update `builder()` to pass the topic**

In `backend/deps.py`, change `builder()`:
```python
def builder() -> BatchJobBuilder:
    s = settings()
    topic = f"projects/{s.project_id}/topics/{s.pubsub_topic}"
    return BatchJobBuilder(
        bucket=s.bucket, image_uri=s.image_uri,
        job_service_account=s.job_service_account, pubsub_topic=topic,
    )
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_routes_jobs.py` (using the in-memory run-repo + case-record fixtures; mirror the existing submit-test setup that stubs the submitter and validates cases):
```python
def test_submit_writes_run_record(client, valid_case, mem_runs, mem_case_records):
    mem_case_records.upsert_name("case_0006", "Wind Tunnel v3")  # helper in fixture
    r = client.post("/api/jobs", json={"case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8"})
    assert r.status_code == 200
    batch_job_id = r.json()["batch_job_id"]
    rec = mem_runs.get(batch_job_id)
    assert rec is not None
    assert rec.submitted_by.endswith("@lemnisca.bio")
    assert rec.case_names == ["Wind Tunnel v3"]
    assert rec.machine_type == "c2d-highcpu-8"
    assert rec.state == "SUBMITTED"
```

> The fixtures `valid_case`, `mem_runs`, `mem_case_records` set up a TestClient with
> `app.dependency_overrides` for `storage`, `case_record_repo`, `run_repo`, and a stub
> `submitter` whose `submit()` returns a deterministic Batch job name. `valid_case`
> uploads `cases/case_0006/{READY,manifest.json,case/command.sh}` so `validate_case`
> passes. `upsert_name` is a tiny convenience added in the fixture that calls
> `InMemoryCaseRecordRepository.upsert(CaseRecord(...))`.

- [ ] **Step 3: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py::test_submit_writes_run_record -q`
Expected: FAIL (no `batch_job_id` in response / no run record).

- [ ] **Step 4: Update the submit route (injected deps; persist AFTER submit, never fail the request on a Firestore error)**

In `backend/routes_jobs.py`, update the imports:
```python
import logging
from backend.deps import builder, case_record_repo, run_repo, status_service, storage, submitter
from core.config import Settings
from core.run_repo import RunRecord
```
Change the `submit` signature to inject the repos (so tests can override them):
```python
@router.post("/jobs")
def submit(
    req: SubmitReq,
    user: User = Depends(current_user),
    b=Depends(builder),
    store=Depends(storage),
    records=Depends(case_record_repo),
    runs=Depends(run_repo),
    sub=Depends(submitter),
):
```
The body up to and including `name = sub.submit(job_name, spec)` is unchanged (machine
lookup, `validate_case`, build spec, submit). Then, AFTER the Batch job is created,
persist the audit record — wrapped so a Firestore failure cannot fail a request whose
Batch job already exists (per spec error handling; the Pub/Sub handler self-heals via
upsert if this write is lost):
```python
    try:
        runs.create(RunRecord(
            batch_job_id=job_name,
            job_name=job_name,
            submitted_by=user.email,
            submitted_at=datetime.datetime.now(datetime.timezone.utc),
            region=Settings().region,
            machine_type=req.machine_type,
            mpi_ranks=machine["default_mpi_ranks"],
            spot=req.spot,
            case_ids=case_ids,
            case_names=records.names_for(case_ids),
        ))
    except Exception:  # noqa: BLE001 — Batch job already submitted; don't fail the user
        logging.exception("failed to persist of_runs record for %s", job_name)
    return {"job_name": job_name, "batch_job_id": job_name, "name": name, "submitted_by": user.email}
```

- [ ] **Step 5: Run tests**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/routes_jobs.py backend/deps.py tests/test_routes_jobs.py
git commit -m "feat(jobs): persist of_runs record at submit"
```

---

## Task 10: List runs from Firestore

**Files:**
- Modify: `backend/routes_jobs.py` (`list_runs` GET `/jobs`)
- Test: `tests/test_routes_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes_jobs.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py::test_list_runs_reads_from_repo -q`
Expected: FAIL (list_runs still uses Batch status_service).

- [ ] **Step 3: Implement**

In `backend/routes_jobs.py`, replace the `list_runs` route:
```python
import dataclasses

@router.get("/jobs")
def list_runs(user: User = Depends(current_user), runs=Depends(run_repo)):
    return {"runs": [dataclasses.asdict(r) for r in runs.list_recent()]}
```

- [ ] **Step 4: Run tests**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routes_jobs.py tests/test_routes_jobs.py
git commit -m "feat(jobs): list runs from Firestore run repo"
```

---

## Task 11: Pub/Sub push OIDC verification

**Files:**
- Create: `backend/pubsub_auth.py`
- Test: `tests/test_pubsub_auth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pubsub_auth.py`:
```python
import pytest
from backend.pubsub_auth import verify_push_token, PushAuthError


def test_rejects_missing_token():
    with pytest.raises(PushAuthError):
        verify_push_token(authorization=None, expected_sa="of-pubsub-push@x.iam.gserviceaccount.com",
                          verifier=lambda tok, aud: {})


def test_rejects_wrong_service_account():
    def fake_verifier(token, audience):
        return {"email": "attacker@evil.com", "email_verified": True}
    with pytest.raises(PushAuthError):
        verify_push_token(authorization="Bearer xyz",
                          expected_sa="of-pubsub-push@x.iam.gserviceaccount.com",
                          verifier=fake_verifier)


def test_accepts_correct_service_account():
    def fake_verifier(token, audience):
        return {"email": "of-pubsub-push@x.iam.gserviceaccount.com", "email_verified": True}
    claims = verify_push_token(authorization="Bearer xyz",
                               expected_sa="of-pubsub-push@x.iam.gserviceaccount.com",
                               verifier=fake_verifier)
    assert claims["email"].startswith("of-pubsub-push@")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_pubsub_auth.py -q`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement**

Create `backend/pubsub_auth.py`:
```python
"""Verify the OIDC token Pub/Sub attaches to push requests.

The verifier is injected so unit tests stay offline; production passes a verifier
backed by google.oauth2.id_token.verify_oauth2_token."""


class PushAuthError(Exception):
    pass


def verify_push_token(authorization: str | None, expected_sa: str, verifier) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise PushAuthError("missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = verifier(token, None)
    except Exception as e:  # noqa: BLE001
        raise PushAuthError(f"invalid token: {e}") from e
    if claims.get("email") != expected_sa or not claims.get("email_verified", False):
        raise PushAuthError("token not from the expected push service account")
    return claims


def google_verifier(token: str, audience):
    from google.oauth2 import id_token
    from google.auth.transport import requests as g_requests
    return id_token.verify_oauth2_token(token, g_requests.Request(), audience)
```

- [ ] **Step 4: Run tests**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_pubsub_auth.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/pubsub_auth.py tests/test_pubsub_auth.py
git commit -m "feat(auth): Pub/Sub push OIDC verification"
```

---

## Task 12: Pub/Sub push handler `POST /internal/batch-events`

**Files:**
- Create: `backend/routes_internal.py`
- Test: `tests/test_routes_internal.py`

Background — Pub/Sub push envelope shape:
```json
{"message": {"data": "<base64>", "attributes": {"...": "..."}}, "subscription": "..."}
```
Batch notification attributes include the new job state and the job's identifier. The
handler decodes the JSON body in `message.data` (the Batch `Job` resource) to read the
job `name` (`.../jobs/<batch_job_id>`) and `status.state`. Map `status.state` to the
record state string; treat `SUCCEEDED`/`FAILED`/`CANCELLED`/`DELETION_IN_PROGRESS` as
terminal and set `finished_at`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_routes_internal.py`:
```python
import base64
import datetime
import json

from core.run_repo import RunRecord


def _envelope(batch_job_id, state):
    body = {"name": f"projects/p/locations/us-central1/jobs/{batch_job_id}",
            "status": {"state": state}}
    data = base64.b64encode(json.dumps(body).encode()).decode()
    return {"message": {"data": data, "attributes": {"newJobState": state}}}


def test_event_updates_run_state(internal_client, mem_runs):
    mem_runs.create(RunRecord(
        batch_job_id="of-x-1", job_name="wt",
        submitted_by="kartikey.attri@lemnisca.bio",
        submitted_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        region="us-central1", machine_type="c2d-highcpu-8", mpi_ranks=4,
        spot=False, case_ids=["case_0006"], case_names=["wt"],
    ))
    r = internal_client.post("/internal/batch-events", json=_envelope("of-x-1", "SUCCEEDED"),
                             headers={"Authorization": "Bearer good"})
    assert r.status_code == 204
    rec = mem_runs.get("of-x-1")
    assert rec.state == "SUCCEEDED"
    assert rec.finished_at is not None


def test_unknown_job_id_upserts(internal_client, mem_runs):
    r = internal_client.post("/internal/batch-events", json=_envelope("of-new", "RUNNING"),
                             headers={"Authorization": "Bearer good"})
    assert r.status_code == 204
    assert mem_runs.get("of-new").state == "RUNNING"


def test_terminal_state_not_regressed(internal_client, mem_runs):
    internal_client.post("/internal/batch-events", json=_envelope("of-x-2", "SUCCEEDED"),
                         headers={"Authorization": "Bearer good"})
    internal_client.post("/internal/batch-events", json=_envelope("of-x-2", "RUNNING"),
                         headers={"Authorization": "Bearer good"})
    assert mem_runs.get("of-x-2").state == "SUCCEEDED"


def test_unauthenticated_rejected(internal_client_no_auth):
    r = internal_client_no_auth.post("/internal/batch-events",
                                     json=_envelope("of-x-1", "RUNNING"))
    assert r.status_code in (401, 403)
```

> Fixtures: `internal_client` builds a TestClient with `app` including the internal
> router, `run_repo` overridden to a shared `InMemoryRunRepository` (`mem_runs`), and
> the push-auth dependency overridden to accept `Authorization: Bearer good`.
> `internal_client_no_auth` overrides the auth dependency to raise `PushAuthError`.

- [ ] **Step 2: Run test to verify it fails**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_internal.py -q`
Expected: FAIL (ModuleNotFoundError: backend.routes_internal).

- [ ] **Step 3: Implement**

Create `backend/routes_internal.py`:
```python
import base64
import datetime
import json

from fastapi import APIRouter, Depends, Request, Response

from backend.deps import run_repo, settings
from backend.pubsub_auth import PushAuthError, verify_push_token, google_verifier
from core.run_repo import TERMINAL_STATES

router = APIRouter()


def push_claims(request: Request) -> dict:
    """FastAPI dependency: verify the Pub/Sub push OIDC token. Overridable in tests."""
    s = settings()
    try:
        return verify_push_token(
            authorization=request.headers.get("Authorization"),
            expected_sa=s.pubsub_push_sa,
            verifier=google_verifier,
        )
    except PushAuthError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/internal/batch-events", status_code=204)
async def batch_events(
    request: Request,
    _claims=Depends(push_claims),
    runs=Depends(run_repo),
):
    envelope = await request.json()
    msg = envelope.get("message", {})
    raw = base64.b64decode(msg.get("data", "")) if msg.get("data") else b"{}"
    job = json.loads(raw or b"{}")
    name = job.get("name", "")
    batch_job_id = name.split("/")[-1] if name else msg.get("attributes", {}).get("JobUID", "")
    state = (job.get("status", {}) or {}).get("state") or msg.get("attributes", {}).get("newJobState", "")
    if not batch_job_id or not state:
        return Response(status_code=204)  # ack malformed messages; nothing to do
    finished = datetime.datetime.now(datetime.timezone.utc) if state in TERMINAL_STATES else None
    runs.update_state(batch_job_id, state, finished_at=finished)
    return Response(status_code=204)
```

- [ ] **Step 4: Run tests**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_internal.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/routes_internal.py tests/test_routes_internal.py
git commit -m "feat(internal): Pub/Sub push handler updates run state"
```

---

## Task 13: Wire the internal router into the app

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_routes_internal.py` (already covers via fixtures); add a smoke test

- [ ] **Step 1: Include the router (mounted BEFORE the static catch-all)**

In `backend/main.py`, add the import and include line (note: NOT under `/api`, and it must be registered before the `app.mount("/", StaticFiles...)` line so the route isn't shadowed):
```python
from backend.routes_internal import router as internal_router
...
app.include_router(cases_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(internal_router)  # /internal/* — no /api prefix, before static mount
```

- [ ] **Step 2: Smoke test the route exists**

Run:
```bash
OF_DEV_NO_IAP=1 .venv/bin/python -c "
from backend.main import app
paths = [r.path for r in app.routes]
assert '/internal/batch-events' in paths, paths
print('route registered')
"
```
Expected: `route registered`.

- [ ] **Step 3: Run the full python suite**

Run: `OF_DEV_NO_IAP=1 .venv/bin/pytest -q`
Expected: PASS (all tests).

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(app): mount internal Pub/Sub router"
```

---

## Task 14: Frontend — capture and send the case name

**Files:**
- Modify: `frontend/src/lib/api.ts` (finalize call sends `name`)
- Modify: `frontend/src/lib/upload.ts` (thread `name` through)
- Modify: `frontend/src/views/UploadView.tsx` (text input per case)
- Test: `frontend/src/tests/upload.test.ts`

- [ ] **Step 1: Write the failing test**

In `frontend/src/tests/upload.test.ts`, add a test asserting the finalize request body includes `name`. Match the existing fetch-mock style in that file:
```ts
it("sends the case name on finalize", async () => {
  const calls: any[] = [];
  globalThis.fetch = vi.fn(async (url: any, init: any) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ case_id: "case_0006", ready: true }), { status: 200 });
  }) as any;
  const { finalizeCase } = await import("../lib/api");
  await finalizeCase("case_0006", { name: "Wind Tunnel v3", openfoam_version: "12" });
  const finalizeCall = calls.find((c) => c.url.includes(":finalize"));
  expect(JSON.parse(finalizeCall.init.body).name).toBe("Wind Tunnel v3");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/upload.test.ts`
Expected: FAIL (`finalizeCase` does not send `name` / wrong signature).

- [ ] **Step 3: Implement the API + upload changes**

In `frontend/src/lib/api.ts`, ensure the finalize function accepts and sends `name`:
```ts
export async function finalizeCase(
  caseId: string,
  body: { name?: string; openfoam_version?: string },
) {
  return apiFetch(`/api/cases/${caseId}:finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
```
In `frontend/src/lib/upload.ts`, thread a `name` argument through the upload-then-finalize flow to `finalizeCase`.

- [ ] **Step 4: Add the input to the UI**

In `frontend/src/views/UploadView.tsx`, add a controlled text input ("Case name") per case being uploaded, defaulting to empty, and pass its value into the upload flow's `name`. Keep it optional (empty is allowed; backend falls back to the case id).

- [ ] **Step 5: Run frontend tests**

Run: `cd frontend && npx vitest run`
Expected: PASS (all, including the new one).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/upload.ts frontend/src/views/UploadView.tsx frontend/src/tests/upload.test.ts
git commit -m "feat(frontend): capture and send case name on upload"
```

---

## Task 15: Infra — Firestore, Pub/Sub topic + push subscription, IAM

**Files:**
- Modify: `infra/setup-cfd-lemnisca.sh`

> No automated test. Each step lists the exact gcloud command + how to verify. Use the
> project's existing variables (`PROJECT_ID`, `REGION`, service-account vars) already
> defined in the script. The backend SA is `of-batch-backend@cfd-lemnisca.iam...`,
> the job SA is `of-batch-job@cfd-lemnisca.iam...` (confirm against the script).

- [ ] **Step 1: Enable Firestore (Native, single-region)**

Add to `infra/setup-cfd-lemnisca.sh`:
```bash
gcloud firestore databases create --location="${REGION}" --type=firestore-native \
  --project="${PROJECT_ID}" 2>/dev/null || echo "(firestore default db exists)"
```
Verify: `gcloud firestore databases describe --database="(default)" --project="${PROJECT_ID}"`.

- [ ] **Step 2: Grant the backend SA Firestore access**

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${BACKEND_SA}" --role="roles/datastore.user"
```

- [ ] **Step 3: Create the Pub/Sub topic**

```bash
gcloud pubsub topics create of-batch-job-state --project="${PROJECT_ID}" \
  2>/dev/null || echo "(topic exists)"
```

- [ ] **Step 4: Let the job SA publish to the topic**

```bash
gcloud pubsub topics add-iam-policy-binding of-batch-job-state \
  --member="serviceAccount:${JOB_SA}" --role="roles/pubsub.publisher" \
  --project="${PROJECT_ID}"
```

- [ ] **Step 5: Create the push-auth service account**

```bash
gcloud iam service-accounts create of-pubsub-push \
  --display-name="Pub/Sub push to backend" --project="${PROJECT_ID}" \
  2>/dev/null || echo "(push SA exists)"
```

- [ ] **Step 6: Allow the push SA to invoke the Cloud Run backend**

```bash
gcloud run services add-iam-policy-binding "${SERVICE}" \
  --member="serviceAccount:of-pubsub-push@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker" --region="${REGION}" --project="${PROJECT_ID}"
```

- [ ] **Step 7: Create the push subscription with OIDC auth**

```bash
BACKEND_URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" \
  --format='value(status.url)' --project="${PROJECT_ID}")"
gcloud pubsub subscriptions create of-batch-job-state-push \
  --topic=of-batch-job-state \
  --push-endpoint="${BACKEND_URL}/internal/batch-events" \
  --push-auth-service-account="of-pubsub-push@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "(subscription exists)"
```
Verify end-to-end after deploy: submit a tiny job, watch the `of_runs` doc transition
`SUBMITTED → RUNNING → SUCCEEDED` in the Firestore console.

- [ ] **Step 8: Commit**

```bash
git add infra/setup-cfd-lemnisca.sh
git commit -m "infra: Firestore + Pub/Sub topic/subscription + IAM for run state"
```

---

## Final verification

- [ ] Run the full python suite: `OF_DEV_NO_IAP=1 .venv/bin/pytest -q` — expect all green (≥ existing 68 + new tests).
- [ ] Run runtime bash tests: `bash phase3-run-app/runtime/tests/run_all.sh` — expect pass.
- [ ] Run frontend tests: `cd frontend && npx vitest run` — expect pass.
- [ ] Deploy to a test Cloud Run revision and submit one small `c2d-highcpu-8` job; confirm the `of_runs` doc is created at submit and reaches `SUCCEEDED` via Pub/Sub without opening the Batch console.

---

## Notes on local development / Firestore emulator (optional)

For integration testing the Firestore impls without touching prod:
```bash
gcloud emulators firestore start --host-port=localhost:8085
export FIRESTORE_EMULATOR_HOST=localhost:8085
```
The `google-cloud-firestore` client auto-detects `FIRESTORE_EMULATOR_HOST`. Unit tests
in this plan use the in-memory fakes and need no emulator.
