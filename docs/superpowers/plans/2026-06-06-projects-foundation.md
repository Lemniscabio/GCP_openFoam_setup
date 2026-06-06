# Backend Phase 1 — Projects & GCS Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a Project entity and nest cases + results under a project in GCS (`cases/<project>/case_xxxx/`, `results/<project>/<codename>/<case_xxxx>/`), require a `metadata.json` case file, and make jobs single-project.

**Architecture:** A new `of_projects` collection + a `project` field threaded through case allocation, uploads, validation, records, submit, and the runtime. Project names are slug-only (the user-entered name is the GCS path segment). Backend + runtime only.

**Tech Stack:** Python 3.12, FastAPI, google-cloud-firestore, pytest; bash runtime.

**Spec:** `docs/superpowers/specs/2026-06-06-projects-foundation-design.md`

**Working dir:** `phase3-run-app/`. **Python tests (ADC-disabled, mirrors CI):** `env -u GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_CONFIG=/tmp/empty-gcloud OF_DEV_NO_IAP=1 .venv/bin/pytest -q`.

---

## File Structure

**Create:** `core/projects.py`, `tests/test_projects.py`.
**Modify:** `core/storage.py`, `core/cases.py`, `core/uploads.py`, `core/validation.py`, `core/case_records.py`, `core/run_repo.py`, `core/batch_jobs.py`, `backend/schemas.py`, `backend/deps.py`, `backend/routes_cases.py`, `backend/routes_jobs.py`, `runtime/run_case_in_batch.sh`, `runtime/tests/run_case_in_batch_test.sh`, `cli/main.py`, `.github/workflows/deploy.yml`, and the affected tests + `tests/conftest.py`.

---

## Task 1: `core/projects.py` — entity + repo + validation

**Files:** Create `core/projects.py`, `tests/test_projects.py`.

- [ ] **Step 1: Write the failing test** — create `tests/test_projects.py`:
```python
import datetime

from core.projects import (
    ProjectRecord, InMemoryProjectRepository, is_valid_project_name,
)

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def test_is_valid_project_name():
    assert is_valid_project_name("turbine-study")
    assert is_valid_project_name("Project_A")
    assert not is_valid_project_name("")
    assert not is_valid_project_name("a/b")        # no slash
    assert not is_valid_project_name(".")
    assert not is_valid_project_name("..")
    assert not is_valid_project_name(" lead")      # leading space
    assert not is_valid_project_name("x" * 129)    # too long
    assert not is_valid_project_name("bad\nname")  # control char


def test_ensure_creates_then_returns_existing():
    repo = InMemoryProjectRepository()
    a = repo.ensure("turbine", "k@lemnisca.bio", NOW)
    assert a.name == "turbine" and a.created_by == "k@lemnisca.bio"
    later = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    b = repo.ensure("turbine", "other@lemnisca.bio", later)
    assert b.created_by == "k@lemnisca.bio" and b.created_at == NOW  # unchanged


def test_get_and_list():
    repo = InMemoryProjectRepository()
    repo.ensure("a", "u@lemnisca.bio", NOW)
    repo.ensure("b", "u@lemnisca.bio", NOW)
    assert repo.get("a").name == "a"
    assert repo.get("missing") is None
    assert sorted(p.name for p in repo.list_all()) == ["a", "b"]
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_projects.py -q` → FAIL.

- [ ] **Step 3: Implement** — create `core/projects.py`:
```python
import datetime
import re
from dataclasses import dataclass
from typing import Protocol

_BAD = re.compile(r"[\x00-\x1f/]")


def is_valid_project_name(s: str) -> bool:
    if not s or len(s) > 128:
        return False
    if s in (".", ".."):
        return False
    if s != s.strip():
        return False
    return not _BAD.search(s)


@dataclass
class ProjectRecord:
    name: str
    created_by: str
    created_at: datetime.datetime


class ProjectRepository(Protocol):
    def get(self, name: str) -> ProjectRecord | None: ...
    def ensure(self, name: str, user: str, now: datetime.datetime) -> ProjectRecord: ...
    def list_all(self) -> list[ProjectRecord]: ...


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._p: dict[str, ProjectRecord] = {}

    def get(self, name):
        return self._p.get(name)

    def ensure(self, name, user, now):
        if name not in self._p:
            self._p[name] = ProjectRecord(name=name, created_by=user, created_at=now)
        return self._p[name]

    def list_all(self):
        return sorted(self._p.values(), key=lambda p: p.name)


class FirestoreProjectRepository:
    COLLECTION = "of_projects"

    def __init__(self, client, collection: str = COLLECTION) -> None:
        self._c = client
        self._col = collection

    def _doc(self, name):
        return self._c.collection(self._col).document(name)

    def get(self, name):
        snap = self._doc(name).get()
        if not snap.exists:
            return None
        d = snap.to_dict()
        return ProjectRecord(name=d["name"], created_by=d.get("created_by", "unknown"),
                             created_at=d.get("created_at"))

    def ensure(self, name, user, now):
        from google.api_core.exceptions import AlreadyExists
        try:
            self._doc(name).create({"name": name, "created_by": user, "created_at": now})
        except AlreadyExists:
            pass
        return self.get(name)

    def list_all(self):
        out = [self.get(s.id) for s in self._c.collection(self._col).select([]).stream()]
        return sorted([p for p in out if p], key=lambda p: p.name)
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/projects.py tests/test_projects.py
git commit -m "feat(core): Project entity + repository + name validation"
```

---

## Task 2: `list_case_ids` for the new `cases/<project>/<id>/` depth

**Files:** Modify `core/storage.py`; Test `tests/test_storage_fake.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_storage_fake.py`:
```python
def test_list_case_ids_parses_project_depth():
    s = InMemoryStorage()
    s.upload_bytes("cases/turbine/case_0001/case/x", b"")
    s.upload_bytes("cases/wing/case_0002/READY", b"")
    s.upload_bytes("results/turbine/jobx/case_0001/r", b"")  # not a case path
    assert sorted(s.list_case_ids()) == ["case_0001", "case_0002"]
```

- [ ] **Step 2: Run → fail** (old parser keyed on `parts[1]` = the project now).

- [ ] **Step 3: Implement** — in `core/storage.py`, update `InMemoryStorage.list_case_ids` and `GcsStorage.list_case_ids` to read the case id at depth 2 (`cases/<project>/<case_id>/...`). For the in-memory fake:
```python
    def list_case_ids(self):
        ids = set()
        for path in self._objs:
            parts = path.split("/")
            if len(parts) >= 4 and parts[0] == "cases" and parts[1] and parts[2]:
                ids.add(parts[2])
        return sorted(ids)
```
Apply the equivalent depth-2 parse in `GcsStorage.list_case_ids` (it lists `cases/` prefixes — take the third segment).

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/storage.py tests/test_storage_fake.py
git commit -m "feat(storage): parse case ids under cases/<project>/<id>/"
```

---

## Task 3: `core/cases.py` — project-scoped allocation (global numbering)

**Files:** Modify `core/cases.py`; Test `tests/test_cases.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_cases.py`:
```python
def test_allocate_ids_reserves_under_project_global_numbering():
    s = InMemoryStorage()
    repo = CaseRepository(s)
    ids = repo.allocate_ids("turbine", 2)
    assert ids == ["case_0001", "case_0002"]
    assert s.object_exists("cases/turbine/case_0001/.reserved")
    # numbering is global across projects
    more = repo.allocate_ids("wing", 1)
    assert more == ["case_0003"]
    assert s.object_exists("cases/wing/case_0003/.reserved")


def test_exists_is_project_scoped():
    s = InMemoryStorage()
    repo = CaseRepository(s)
    repo.allocate_ids("turbine", 1)
    assert repo.exists("turbine", "case_0001") is True
    assert repo.exists("wing", "case_0001") is False
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `core/cases.py`:
```python
    def allocate_ids(self, project: str, count: int) -> list[str]:
        n = self._max_existing()
        out: list[str] = []
        while len(out) < count:
            n += 1
            cid = f"case_{n:04d}"
            if self._s.create_exclusive(f"cases/{project}/{cid}/.reserved", b""):
                out.append(cid)
        return out

    def exists(self, project: str, case_id: str) -> bool:
        base = f"cases/{project}/{case_id}"
        return self._s.object_exists(f"{base}/READY") or self._s.object_exists(f"{base}/.reserved")
```
`_max_existing()` keeps scanning `list_case_ids()` (now global across projects from Task 2). `list_cases()` is reworked in Phase 2; for now update it to read `cases/<project>/<id>/` and include the project on `CaseInfo` (add `project: str` to the dataclass), or leave it returning ids — minimal: add `project` to `CaseInfo` and populate from the path.

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/cases.py tests/test_cases.py
git commit -m "feat(core): project-scoped case allocation (global numbering)"
```

---

## Task 4: `core/uploads.py` — project in object paths

**Files:** Modify `core/uploads.py`; Test `tests/test_uploads.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_uploads.py`:
```python
def test_object_path_includes_project():
    from core.uploads import object_path, case_prefix
    assert case_prefix("turbine", "case_0001") == "cases/turbine/case_0001/"
    assert object_path("turbine", "case_0001", "system/controlDict") == \
        "cases/turbine/case_0001/case/system/controlDict"
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `core/uploads.py`:
```python
def case_prefix(project: str, case_id: str) -> str:
    return f"cases/{project}/{case_id}/"


def object_path(project: str, case_id: str, relative_path: str) -> str:
    return f"cases/{project}/{case_id}/case/{relative_path.lstrip('/')}"
```
And `SignedUrlService.put_urls_for_case(self, project, case_id, relative_paths, now)` → `object_path(project, case_id, rp)`.

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/uploads.py tests/test_uploads.py
git commit -m "feat(uploads): project-scoped object paths"
```

---

## Task 5: `core/validation.py` — project base + required metadata.json

**Files:** Modify `core/validation.py`; Test `tests/test_validation.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_validation.py`:
```python
def test_validate_requires_metadata_json_valid(tmp_path=None):
    from core.storage import InMemoryStorage
    from core.validation import validate_case
    s = InMemoryStorage()
    base = "cases/turbine/case_0001"
    s.upload_bytes(f"{base}/manifest.json", b"{}")
    s.upload_bytes(f"{base}/READY", b"x")
    s.upload_bytes(f"{base}/case/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")
    # no metadata.json yet -> invalid
    r = validate_case(s, "turbine", "case_0001")
    assert not r.ok and any("metadata.json" in e for e in r.errors)
    # invalid JSON -> invalid
    s.upload_bytes(f"{base}/case/metadata.json", b"not json")
    assert not validate_case(s, "turbine", "case_0001").ok
    # valid JSON -> ok
    s.upload_bytes(f"{base}/case/metadata.json", b'{"author":"k"}')
    assert validate_case(s, "turbine", "case_0001").ok
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `core/validation.py`, change the signature to `validate_case(storage, project, case_id)`, set `base = f"cases/{project}/{case_id}"`, and after the command.sh check add:
```python
    import json
    meta_path = f"{base}/case/metadata.json"
    if not storage.object_exists(meta_path):
        errors.append("missing case/metadata.json")
    else:
        try:
            json.loads(storage.read_text(meta_path))
        except Exception:  # noqa: BLE001
            errors.append("case/metadata.json is not valid JSON")
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/validation.py tests/test_validation.py
git commit -m "feat(validation): project-scoped base + required metadata.json"
```

---

## Task 6: `project` field on CaseRecord + RunRecord

**Files:** Modify `core/case_records.py`, `core/run_repo.py`; Tests `tests/test_case_records.py`, `tests/test_run_repo.py`.

- [ ] **Step 1: Write failing tests** — assert `CaseRecord(..., project="turbine").project == "turbine"` and `RunRecord(..., project="turbine").project == "turbine"`, and that the Firestore-shape round-trips include `project` (extend the existing fake-based tests).

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — add `project: str = ""` to both `CaseRecord` and `RunRecord` dataclasses; include `"project"` in the Firestore `set`/`create`/`_from_dict` mappings in `FirestoreCaseRecordRepository`, `FirestoreRunRepository` (create + try_reserve + _from_dict).

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add core/case_records.py core/run_repo.py tests/test_case_records.py tests/test_run_repo.py
git commit -m "feat(core): project field on CaseRecord and RunRecord"
```

---

## Task 7: Schemas + deps provider

**Files:** Modify `backend/schemas.py`, `backend/deps.py`.

- [ ] **Step 1** — in `backend/schemas.py`:
```python
class AllocateReq(BaseModel):
    project: str
    cases: list[CaseUpload] = Field(min_length=1, max_length=200)


class FinalizeReq(BaseModel):
    openfoam_version: str = "12"
    name: str | None = None
    project: str
```

- [ ] **Step 2** — in `backend/deps.py` add:
```python
from core.projects import FirestoreProjectRepository

def project_repo() -> FirestoreProjectRepository:
    return FirestoreProjectRepository(_firestore())
```

- [ ] **Step 3: Import check** + **Commit**:
```bash
OF_DEV_NO_IAP=1 .venv/bin/python -c "from backend.deps import project_repo; from backend.schemas import AllocateReq; print('ok')"
git add backend/schemas.py backend/deps.py
git commit -m "feat(api): project on allocate/finalize + project_repo provider"
```

---

## Task 8: `routes_cases` — allocate + finalize with project

**Files:** Modify `backend/routes_cases.py`; Modify `tests/conftest.py` (add `mem_projects` + override); Test `tests/test_routes_cases.py`.

- [ ] **Step 1: conftest** — add a `mem_projects` fixture (`InMemoryProjectRepository`) and, in the `client` fixture, `test_app.dependency_overrides[deps.project_repo] = lambda: mem_projects`. Also fix the module-level `test_routes_cases.py` setup to override `deps.project_repo` (same trap as before) and update `_FakeUrls.put_urls_for_case` to accept `(project, case_id, files, now)`.

- [ ] **Step 2: Write failing tests** — in `tests/test_routes_cases.py`: allocate with a valid project returns ids + reserves under `cases/<project>/`; allocate with invalid project → 400; finalize with project writes `of_cases` record carrying `project`; finalize rejects a case missing `metadata.json`.

- [ ] **Step 3: Implement** — in `backend/routes_cases.py`:
  - `allocate`: validate `is_valid_project_name(req.project)` (else 400); `projects.ensure(req.project, user.email, now)`; `repo.allocate_ids(req.project, len(req.cases))`; `urls.put_urls_for_case(req.project, case_id, case.files, now)`; return as today.
  - `finalize`: validate `is_valid_project_name(req.project)`; `repo.exists(req.project, case_id)` else 404; `validate_case(store, req.project, case_id)` must be ok (returns errors → 400); write manifest/READY under `cases/<project>/<id>/`; `records.upsert(CaseRecord(case_id=..., name=..., project=req.project, ...))`.
  - Inject `projects=Depends(project_repo)`.

- [ ] **Step 4: Run → pass** (`tests/test_routes_cases.py`); **Step 5: Commit**:
```bash
git add backend/routes_cases.py tests/conftest.py tests/test_routes_cases.py
git commit -m "feat(cases): allocate/finalize create + record project"
```

---

## Task 9: `routes_jobs` — resolve project, single-project enforce

**Files:** Modify `backend/routes_jobs.py`; Test `tests/test_routes_jobs.py`.

- [ ] **Step 1: Write failing tests** — single-case submit stores `project` on the run (resolved from `of_cases`); a job whose cases span two projects → 400.

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `submit` (`backend/routes_jobs.py`), after dedupe/validate, resolve project from `of_cases`:
```python
    projects_seen = {records.get(cid).project for cid in case_ids if records.get(cid)}
    if len(projects_seen) != 1 or "" in projects_seen:
        raise HTTPException(status_code=400, detail="all cases in a job must share one project")
    project = projects_seen.pop()
```
Validate each case with the resolved project: `validate_case(store, project, cid)`. Pass `project=project` into `build_single`/`build_multi`, and set `project=project` on the `RunRecord`. (`records` is the `case_record_repo` dependency already injected.)

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add backend/routes_jobs.py tests/test_routes_jobs.py
git commit -m "feat(jobs): resolve + enforce single project per job"
```

---

## Task 10: `batch_jobs` — PROJECT env

**Files:** Modify `core/batch_jobs.py`; Test `tests/test_batch_jobs.py`.

- [ ] **Step 1: Write failing test** — `build_single(..., project="turbine")` puts `"PROJECT": "turbine"` in the task env; proto still parses.

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — add `project: str` as a required kwarg to `build_single` and `build_multi`, and add `"PROJECT": project` to the `env` dict in both.

- [ ] **Step 4: Run → pass** + proto-parse check; **Step 5: Commit**:
```bash
git add core/batch_jobs.py tests/test_batch_jobs.py
git commit -m "feat(batch): pass PROJECT env to runtime"
```

---

## Task 11: Runtime — project paths + metadata-out-of-tar

**Files:** Modify `runtime/run_case_in_batch.sh`, `runtime/tests/run_case_in_batch_test.sh`.

- [ ] **Step 1: Write failing test** — assert `CASE_PREFIX`/`RESULT_PREFIX` include `${PROJECT}` and that `metadata.json` is copied to the result prefix; add a `PROJECT` env to the test invocations.

- [ ] **Step 2: Run → fail** (`bash phase3-run-app/runtime/tests/run_all.sh`).

- [ ] **Step 3: Implement** — in `runtime/run_case_in_batch.sh`:
  - add guard `: "${PROJECT:?PROJECT is required}"`.
  - `CASE_PREFIX="gs://${BUCKET}/cases/${PROJECT}/${CASE_ID}"`.
  - `RESULT_PREFIX="gs://${BUCKET}/results/${PROJECT}/${JOB_NAME}/${CASE_ID}"` (drop the `RESULT_MODE` singlecase/multicase segment introduced in Feature D).
  - after the existing result uploads, add: `gcloud storage cp "${CASE_DIR}/metadata.json" "${RESULT_PREFIX}/metadata.json" || true` (metadata.json lives in the case tree; expose it separately).
  - `CHECKPOINT_PREFIX` unchanged.

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add runtime/run_case_in_batch.sh runtime/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): project-scoped paths + metadata.json beside results"
```

---

## Task 12: CLI `--project`

**Files:** Modify `cli/main.py`; Test `tests/test_cli.py`.

- [ ] **Step 1: Write failing test** — `upload` requires `--project` and writes under `cases/<project>/`; `run` resolves project (from of_cases, or a `--project` passthrough) and submits.

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — add `@click.option("--project", required=True)` to the upload command; thread it into `allocate_ids`, `object_path`, `validate_case`, and the `cases/<project>/...` rsync/READY writes. For `run`, pass `project=` through to `build_single`/`build_multi` (resolve from the case record or require `--project`).

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add cli/main.py tests/test_cli.py
git commit -m "feat(cli): --project for upload + run"
```

---

## Task 13: Bump runtime image pin

**Files:** Modify `.github/workflows/deploy.yml`.

- [ ] **Step 1** — bump `RUNTIME_IMAGE` `openfoam:12.0.3` → `openfoam:12.0.4`.
- [ ] **Step 2: Validate YAML**: `phase3-run-app/.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('yaml ok')"`.
- [ ] **Step 3: Commit**:
```bash
git add .github/workflows/deploy.yml
git commit -m "ci: pin runtime image openfoam:12.0.4 (project paths)"
```

---

## Final verification + rollout
- [ ] Python (ADC-disabled): `env -u GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_CONFIG=/tmp/empty-gcloud OF_DEV_NO_IAP=1 .venv/bin/pytest -q` — all green.
- [ ] Runtime: `bash phase3-run-app/runtime/tests/run_all.sh` — green.
- [ ] **Rollout (manual, billable, before merging the deploy bump):** rebuild + push the runtime image:
  ```bash
  docker buildx build --platform linux/amd64 \
    -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.4 \
    -f phase3-run-app/runtime/Dockerfile --push phase3-run-app/runtime
  ```
  Then merge to `main`; CI deploys the backend with `OF_IMAGE_URI=...:12.0.4`.
- [ ] **Verify live:** upload a case under a project (with `metadata.json`), submit on Standard; confirm `cases/<project>/case_xxxx/` and `results/<project>/<codename>/case_xxxx/` (+ separate `metadata.json`).
