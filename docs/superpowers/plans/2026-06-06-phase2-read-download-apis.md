# Backend Phase 2 — Read & Download APIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read APIs (projects, cases-by-project, results tree) and signed-URL downloads, plus admin reporting — the data layer for the v2 frontend.

**Architecture:** Firestore (`of_projects`/`of_cases`/`of_runs`) supplies structure + metadata; GCS supplies files. They join by the deterministic path `results/<project>/<codename>/<case>/`, centralized in one backend helper. Backend only — no runtime change.

**Tech Stack:** Python 3.12, FastAPI, google-cloud-firestore, google-cloud-storage, pytest.

**Spec:** `docs/superpowers/specs/2026-06-06-phase2-read-download-apis-design.md`

**Working dir:** `phase3-run-app/`. **Python tests (ADC-disabled, mirrors CI):** `env -u GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_CONFIG=/tmp/empty-gcloud OF_DEV_NO_IAP=1 .venv/bin/pytest -q`.

---

## File Structure

**Create:** `core/results_paths.py`, `backend/routes_results.py`, `tests/test_results_paths.py`, `tests/test_routes_results.py`.
**Modify:** `core/uploads.py`, `core/storage.py`, `core/case_records.py`, `core/run_repo.py`, `backend/routes_cases.py`, `backend/routes_admin.py`, `backend/main.py`, `tests/conftest.py`, and affected tests.

---

## Task 1: `results_prefix` path helper

**Files:** Create `core/results_paths.py`, `tests/test_results_paths.py`.

- [ ] **Step 1: Write the failing test** — create `tests/test_results_paths.py`:
```python
from core.results_paths import results_prefix


def test_results_prefix():
    assert results_prefix("turbine", "phoenix", "case_0006") == \
        "results/turbine/phoenix/case_0006/"
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — create `core/results_paths.py`:
```python
def results_prefix(project: str, codename: str, case_id: str) -> str:
    """Bucket-relative prefix for one case's results. MIRROR of the runtime's
    RESULT_PREFIX in runtime/run_case_in_batch.sh — if one changes, change both."""
    return f"results/{project}/{codename}/{case_id}/"
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/results_paths.py tests/test_results_paths.py
git commit -m "feat(core): results_prefix path helper"
```

---

## Task 2: Signed GET URLs

**Files:** Modify `core/uploads.py`; Test `tests/test_uploads.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_uploads.py`:
```python
def test_get_url_signs_a_GET():
    import datetime
    from core.uploads import SignedUrlService

    class _Blob:
        def __init__(self): self.kw = None
        def generate_signed_url(self, **kw): self.kw = kw; return "https://signed-get"

    class _Bucket:
        def __init__(self): self.b = _Blob()
        def blob(self, _p): return self.b

    bkt = _Bucket()
    svc = SignedUrlService(bkt, "sa@x.iam.gserviceaccount.com", lambda: "tok")
    url = svc.get_url("results/turbine/phoenix/case_0006/result.tar.gz",
                      datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    assert url == "https://signed-get"
    assert bkt.b.kw["method"] == "GET"
    assert bkt.b.kw["version"] == "v4"
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `core/uploads.py` add to `SignedUrlService`:
```python
    def get_url(self, obj_path: str, now: datetime.datetime) -> str:
        return self._bucket.blob(obj_path).generate_signed_url(
            version="v4",
            expiration=now + self._ttl,
            method="GET",
            service_account_email=self._signer_email,
            access_token=self._token(),
        )
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/uploads.py tests/test_uploads.py
git commit -m "feat(uploads): signed GET URLs for downloads"
```

---

## Task 3: `list_objects` (names + sizes) on storage

**Files:** Modify `core/storage.py`; Test `tests/test_storage_fake.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_storage_fake.py`:
```python
def test_list_objects_returns_name_and_size():
    s = InMemoryStorage()
    s.upload_bytes("results/turbine/phoenix/case_0006/result.tar.gz", b"abcd")
    s.upload_bytes("results/turbine/phoenix/case_0006/metadata.json", b"{}")
    s.upload_bytes("results/turbine/phoenix/case_0007/x", b"zz")  # different case
    got = dict(s.list_objects("results/turbine/phoenix/case_0006/"))
    assert got == {
        "results/turbine/phoenix/case_0006/result.tar.gz": 4,
        "results/turbine/phoenix/case_0006/metadata.json": 2,
    }
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — add `list_objects` to the `StorageClient` Protocol, `InMemoryStorage`, and `GcsStorage`:
```python
# Protocol
    def list_objects(self, prefix: str) -> list[tuple[str, int]]: ...

# InMemoryStorage
    def list_objects(self, prefix):
        return sorted((p, len(d)) for p, d in self._objs.items() if p.startswith(prefix))

# GcsStorage
    def list_objects(self, prefix):
        return [(b.name, b.size or 0)
                for b in self._client.list_blobs(self._bucket_name, prefix=prefix)]
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/storage.py tests/test_storage_fake.py
git commit -m "feat(storage): list_objects with sizes"
```

---

## Task 4: `CaseRecordRepository.list_all`

**Files:** Modify `core/case_records.py`; Test `tests/test_case_records.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_case_records.py`:
```python
def test_list_all():
    repo = InMemoryCaseRecordRepository()
    repo.upsert(_rec("case_0006", "WT v3"))
    repo.upsert(_rec("case_0007", "Nozzle"))
    ids = sorted(r.case_id for r in repo.list_all())
    assert ids == ["case_0006", "case_0007"]
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — add to the `CaseRecordRepository` Protocol `def list_all(self) -> list["CaseRecord"]: ...`; on `InMemoryCaseRecordRepository`:
```python
    def list_all(self):
        return sorted(self._cases.values(), key=lambda c: c.case_id)
```
on `FirestoreCaseRecordRepository`:
```python
    def list_all(self):
        out = []
        for snap in self._c.collection(self._col).stream():
            d = snap.to_dict()
            out.append(CaseRecord(
                case_id=d["case_id"], name=d.get("name", d["case_id"]),
                uploaded_by=d.get("uploaded_by", "unknown"), uploaded_at=d.get("uploaded_at"),
                ready=d.get("ready", False), project=d.get("project", ""),
            ))
        return sorted(out, key=lambda c: c.case_id)
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/case_records.py tests/test_case_records.py
git commit -m "feat(core): CaseRecordRepository.list_all"
```

---

## Task 5: `RunRepository.list_all` + `list_by_user`

**Files:** Modify `core/run_repo.py`; Test `tests/test_run_repo.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_run_repo.py`:
```python
def test_list_all_and_by_user():
    repo = InMemoryRunRepository()
    a = _rec(job_id="phoenix"); a.submitted_by = "k@lemnisca.bio"
    b = _rec(job_id="otter"); b.submitted_by = "g@lemnisca.bio"
    repo.create(a); repo.create(b)
    assert {r.batch_job_id for r in repo.list_all()} == {"phoenix", "otter"}
    assert [r.batch_job_id for r in repo.list_by_user("k@lemnisca.bio")] == ["phoenix"]
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — add to the `RunRepository` Protocol:
```python
    def list_all(self, limit: int = 200) -> list["RunRecord"]: ...
    def list_by_user(self, email: str, limit: int = 200) -> list["RunRecord"]: ...
```
on `InMemoryRunRepository`:
```python
    def list_all(self, limit=200):
        return self.list_recent(limit)

    def list_by_user(self, email, limit=200):
        return [r for r in self.list_recent(10_000) if r.submitted_by == email][:limit]
```
on `FirestoreRunRepository` (reuse the ordered query, plus a `where` for by-user):
```python
    def list_all(self, limit=200):
        return self.list_recent(limit)

    def list_by_user(self, email, limit=200):
        from google.cloud.firestore import Query  # type: ignore
        q = (self._c.collection(self._col)
             .where("submitted_by", "==", email)
             .order_by("submitted_at", direction=Query.DESCENDING).limit(limit))
        return [self._from_dict(d.to_dict()) for d in q.stream()]
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/run_repo.py tests/test_run_repo.py
git commit -m "feat(core): RunRepository list_all + list_by_user"
```

---

## Task 6: `GET /api/cases` (project+name) + `GET /api/projects`

**Files:** Modify `backend/routes_cases.py`; Test `tests/test_routes_cases.py`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_routes_cases.py` (use the conftest `client` + `mem_case_records` + a `mem_projects` fixture):
```python
def test_list_cases_returns_project_and_name(client, mem_case_records):
    import datetime as _dt
    from core.case_records import CaseRecord
    mem_case_records.upsert(CaseRecord(case_id="case_0006", name="WT v3",
        uploaded_by="k@lemnisca.bio", uploaded_at=_dt.datetime(2026,1,1,tzinfo=_dt.timezone.utc),
        ready=True, project="turbine"))
    r = client.get("/api/cases")
    assert r.status_code == 200
    c = r.json()["cases"][0]
    assert c["case_id"] == "case_0006" and c["project"] == "turbine" and c["name"] == "WT v3"


def test_list_projects(client, mem_projects):
    import datetime as _dt
    mem_projects.ensure("turbine", "k@lemnisca.bio", _dt.datetime(2026,1,1,tzinfo=_dt.timezone.utc))
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert any(p["name"] == "turbine" for p in r.json()["projects"])
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `backend/routes_cases.py`:
  - Change `list_cases` to read `of_cases`:
```python
import dataclasses
from backend.deps import case_record_repo, project_repo

@router.get("/cases")
def list_cases(account=Depends(require_active), records=Depends(case_record_repo)):
    return {"cases": [dataclasses.asdict(c) for c in records.list_all()]}
```
  - Add the projects route:
```python
@router.get("/projects")
def list_projects(account=Depends(require_active), projects=Depends(project_repo)):
    return {"projects": [dataclasses.asdict(p) for p in projects.list_all()]}
```
(`require_active` from `backend.rbac`; ensure imports.)

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add backend/routes_cases.py tests/test_routes_cases.py
git commit -m "feat(api): GET /api/cases (project+name) and GET /api/projects"
```

---

## Task 7: Results routes (`/api/results`, `/files`, `/downloads`)

**Files:** Create `backend/routes_results.py`, `tests/test_routes_results.py`; Modify `backend/main.py`, `tests/conftest.py`.

- [ ] **Step 1: conftest** — add `get_url` to the shared `_FakeUrls` so the download route works under test:
```python
    def get_url(self, obj_path, now):
        return f"https://signed-get/{obj_path}"
```
(The `client` fixture already overrides `deps.url_service` and `deps.storage`/`run_repo`.)

- [ ] **Step 2: Write failing tests** — create `tests/test_routes_results.py`:
```python
import datetime as _dt
from core.run_repo import RunRecord

NOW = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)


def _run(repo, job="phoenix", project="turbine"):
    repo.create(RunRecord(batch_job_id=job, job_name=job, submitted_by="k@lemnisca.bio",
        submitted_at=NOW, region="us-central1", machine_type="c2d-highcpu-8", mpi_ranks=4,
        spot=False, case_ids=["case_0006"], case_names=["WT"], state="SUCCEEDED", project=project))


def test_results_lists_runs(client, mem_runs):
    _run(mem_runs)
    r = client.get("/api/results")
    assert r.status_code == 200
    item = r.json()["results"][0]
    assert item["codename"] == "phoenix" and item["project"] == "turbine"
    assert item["case_ids"] == ["case_0006"]


def test_results_files_lists_case(client, mem_storage):
    mem_storage.upload_bytes("results/turbine/phoenix/case_0006/result.tar.gz", b"abcd")
    r = client.get("/api/results/files?project=turbine&job=phoenix&case=case_0006")
    assert r.status_code == 200
    files = r.json()["files"]
    assert {"name": "result.tar.gz", "size": 4} in files


def test_downloads_signs_results_only(client, mem_storage):
    mem_storage.upload_bytes("results/turbine/phoenix/case_0006/result.tar.gz", b"abcd")
    r = client.post("/api/results/downloads", json={"objects": [
        "results/turbine/phoenix/case_0006/result.tar.gz",
        "results/turbine/phoenix/case_0006/missing.txt",  # not in storage -> omitted
    ]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["downloads"]) == 1
    assert body["downloads"][0]["object"].endswith("result.tar.gz")
    assert "missing.txt" in body["missing"][0]


def test_downloads_rejects_non_results_path(client):
    r = client.post("/api/results/downloads", json={"objects": ["cases/turbine/case_0006/x"]})
    assert r.status_code == 400
```

- [ ] **Step 3: Run → fail**.

- [ ] **Step 4: Implement** — create `backend/routes_results.py`:
```python
import dataclasses
import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.deps import run_repo, storage, url_service
from backend.rbac import require_active
from core.results_paths import results_prefix

router = APIRouter()


class DownloadsReq(BaseModel):
    objects: list[str]


@router.get("/results")
def list_results(account=Depends(require_active), runs=Depends(run_repo)):
    out = []
    for r in runs.list_all():
        out.append({
            "codename": r.batch_job_id, "project": r.project, "state": r.state,
            "case_ids": r.case_ids, "case_names": r.case_names,
            "submitted_by": r.submitted_by, "submitted_at": str(r.submitted_at),
        })
    return {"results": out}


@router.get("/results/files")
def result_files(project: str, job: str, case: str,
                 account=Depends(require_active), store=Depends(storage)):
    prefix = results_prefix(project, job, case)
    files = [{"name": name[len(prefix):], "size": size}
             for name, size in store.list_objects(prefix) if name != prefix]
    return {"files": files}


@router.post("/results/downloads")
def downloads(req: DownloadsReq, account=Depends(require_active),
              store=Depends(storage), urls=Depends(url_service)):
    now = datetime.datetime.now(datetime.timezone.utc)
    out, missing = [], []
    for obj in req.objects:
        if not obj.startswith("results/"):
            raise HTTPException(status_code=400, detail=f"invalid object: {obj}")
        if not store.object_exists(obj):
            missing.append(obj)
            continue
        out.append({"object": obj, "url": urls.get_url(obj, now)})
    return {"downloads": out, "missing": missing}
```
Register in `backend/main.py` (under `/api`, before the static mount):
```python
from backend.routes_results import router as results_router
app.include_router(results_router, prefix="/api")
```

- [ ] **Step 5: Run → pass**; **Step 6: Commit**:
```bash
git add backend/routes_results.py backend/main.py tests/conftest.py tests/test_routes_results.py
git commit -m "feat(api): results listing + files + signed downloads"
```

---

## Task 8: `GET /api/admin/runs` (reporting)

**Files:** Modify `backend/routes_admin.py`; Test `tests/test_routes_admin.py`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_routes_admin.py`:
```python
def test_admin_runs_all_and_by_user(client, mem_runs):
    import datetime as _dt
    from core.run_repo import RunRecord
    def mk(job, who):
        return RunRecord(batch_job_id=job, job_name=job, submitted_by=who,
            submitted_at=_dt.datetime(2026,1,1,tzinfo=_dt.timezone.utc), region="us-central1",
            machine_type="c2d-highcpu-8", mpi_ranks=4, spot=False, case_ids=["case_0006"],
            case_names=["WT"], project="turbine")
    mem_runs.create(mk("phoenix", "k@lemnisca.bio"))
    mem_runs.create(mk("otter", "g@lemnisca.bio"))
    allr = client.get("/api/admin/runs").json()["runs"]
    assert {r["batch_job_id"] for r in allr} == {"phoenix", "otter"}
    mine = client.get("/api/admin/runs?user=k@lemnisca.bio").json()["runs"]
    assert [r["batch_job_id"] for r in mine] == ["phoenix"]


def test_admin_runs_forbidden_for_non_admin(client, mem_runs):
    from backend import rbac
    from backend.auth import User
    from backend.main import app
    from core.users import UserRecord
    import datetime as _dt
    app.dependency_overrides[rbac.current_account] = lambda: (
        User(email="v@lemnisca.bio", sub="v"),
        UserRecord(email="v@lemnisca.bio", role="viewer", status="active",
                   requested_at=_dt.datetime.now(_dt.timezone.utc)))
    assert client.get("/api/admin/runs").status_code == 403
    app.dependency_overrides.pop(rbac.current_account, None)
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `backend/routes_admin.py`:
```python
import dataclasses
from backend.deps import run_repo

@router.get("/admin/runs")
def admin_runs(user: str | None = None, limit: int = 200,
               account=Depends(require_admin), runs=Depends(run_repo)):
    records = runs.list_by_user(user, limit) if user else runs.list_all(limit)
    return {"runs": [dataclasses.asdict(r) for r in records]}
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add backend/routes_admin.py tests/test_routes_admin.py
git commit -m "feat(admin): GET /api/admin/runs reporting (all + by user)"
```

---

## Final verification + rollout
- [ ] Full suite (ADC-disabled): `env -u GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_CONFIG=/tmp/empty-gcloud OF_DEV_NO_IAP=1 .venv/bin/pytest -q` — all green.
- [ ] Route smoke: `OF_DEV_NO_IAP=1 .venv/bin/python -c "from backend.main import app; ps=[r.path for r in app.routes]; assert all(p in ps for p in ('/api/projects','/api/results','/api/results/files','/api/results/downloads','/api/admin/runs')); print('routes ok')"`.
- [ ] **Backend-only — no runtime rebuild.** Merge to `main`; CI deploys.
- [ ] **Verify live:** `GET /api/projects`, `/api/cases`, `/api/results` return data; `POST /api/results/downloads` for a real `results/...` object returns a usable signed URL.
