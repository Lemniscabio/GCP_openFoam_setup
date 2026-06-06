# Backend Phase 2 — Read & Download APIs

**Date:** 2026-06-06
**Status:** Approved design (pre-implementation)
**Project:** `cfd-lemnisca` OpenFOAM-on-Batch web app (`phase3-run-app/`)
**Builds on:** Phase 1 (Projects) — `docs/superpowers/specs/2026-06-06-projects-foundation-design.md`

## Context

Phase 1 introduced projects and the `cases/<project>/…` + `results/<project>/<codename>/<case>/`
layout. Phase 2 adds the **read & download APIs** the v2 frontend (Phase 3) needs: list
projects, cases-by-project, a results browser, signed downloads, and admin reporting.
This phase **absorbs the old "Feature B" (monitoring/dashboard)** data layer. Backend only.

**Core model:** Firestore (`of_projects`/`of_cases`/`of_runs`) is the index of *structure +
metadata*; GCS holds the *files*. The two are joined by a deterministic path convention —
`results/<project>/<codename>/<case_id>/…` — which the runtime writes and the backend
reconstructs. There is no foreign key; the path is computed from the Firestore fields.

## Goals

1. Read endpoints for projects, cases (grouped-by-project ready), and a results tree.
2. List a case's result files, and mint **signed GET download URLs** (file / case / all).
3. Admin reporting: all runs (who/when), per-user, plus existing users + projects.
4. One backend-side **`results_prefix(project, codename, case)`** helper as the single
   source for the results path (mirror of the runtime's `RESULT_PREFIX` contract).

## Non-goals (later)

- Frontend (5-section flow, trees, Results browser, Profile/admin dashboard) → **Phase 3**.
- Server-side zipping (rejected; downloads are signed URLs).
- Migrating pre-project data.

## Decisions (locked during brainstorming)

| # | Decision |
|---|---|
| 1 | Results tree shape from **`of_runs`** (Firestore); GCS only for leaf files + downloads. |
| 2 | `GET /api/results` is **separate** from `GET /api/jobs`: results = all historical runs, **no Batch reconcile**; jobs/Status = live + recent + reconcile. |
| 3 | Downloads = **signed GET URLs** (V4, keyless), batched; **never** server-side zip. |
| 4 | Download signing is **restricted to the `results/` prefix** (reject anything else → 400). |
| 5 | Read + download endpoints are `require_active` (org-wide visibility); admin reporting is `require_admin`. |
| 6 | `GET /api/projects` is **lean** (name, created_by, created_at) — no per-project case count (frontend can count from `/api/cases`). |
| 7 | The results path is built by **one** backend helper `results_prefix(...)`; the runtime's `RESULT_PREFIX` is its documented mirror. |

## Endpoints

| Method/Path | Auth | Source | Returns |
|---|---|---|---|
| `GET /api/projects` | active | `of_projects.list_all` | `[{name, created_by, created_at}]` |
| `GET /api/cases` | active | `of_cases.list_all` | `[{case_id, name, project, ready, uploaded_by}]` (Cases tree; group client-side) |
| `GET /api/results` | active | `of_runs.list_all` (no reconcile) | `[{codename, project, case_ids, case_names, state, submitted_by, submitted_at}]` (Results tree) |
| `GET /api/results/files?project=&job=&case=` | active | GCS | `[{name, size}]` under `results/<project>/<job>/<case>/` |
| `POST /api/results/downloads` body `{objects:[...]}` | active | GCS signed GET | `[{object, url}]` (one, a case's files, or all) |
| `GET /api/admin/runs?user=&limit=` | admin | `of_runs` | all runs / per-user (reporting) |
| `GET /api/admin/users` | admin | (exists) | reused unchanged |

## Components & data flow

### 1. Path helper — `core/results_paths.py` (new, tiny)
```python
def results_prefix(project: str, codename: str, case_id: str) -> str:
    return f"results/{project}/{codename}/{case_id}/"
```
Used by `/results/files` (list) and `/results/downloads` (validate). Documented as the mirror
of the runtime's `RESULT_PREFIX` — if one changes, change both.

### 2. Signed GET URLs — `core/uploads.py`
- Add `SignedUrlService.get_url(object_path, now) -> str`: V4 signed **GET** (same keyless
  IAM signing as `put_url`, `method="GET"`).

### 3. Repository read methods
- `core/case_records.py`: `CaseRecordRepository.list_all() -> list[CaseRecord]` (fake + Firestore).
- `core/run_repo.py`: `RunRepository.list_all(limit=200)` and `list_by_user(email, limit=200)`
  (fake + Firestore). (`list_recent` stays for the Status view.)

### 4. GCS file listing with sizes — `core/storage.py`
- Add `list_objects(prefix) -> list[tuple[str, int]]` (name, size) on `GcsStorage` (uses
  `list_blobs` → `(b.name, b.size)`) and the in-memory fake (size = `len(bytes)`).

### 5. Routes
- **`backend/routes_cases.py`**: `GET /api/cases` now reads `of_cases.list_all()` →
  `{case_id, name, project, ready, uploaded_by}`. Add `GET /api/projects` (or a small
  `routes_projects.py`) → `project_repo.list_all()`.
- **`backend/routes_results.py`** (new):
  - `GET /api/results` → `run_repo.list_all()` mapped to the result fields (no reconcile).
  - `GET /api/results/files` → `storage.list_objects(results_prefix(project, job, case))`
    → strip the prefix to relative names + sizes.
  - `POST /api/results/downloads` → for each requested `object`: reject unless it starts with
    `results/`; else `url_service.get_url(object, now)`. Return `[{object, url}]`.
- **`backend/routes_admin.py`**: `GET /api/admin/runs?user=&limit=` → `run_repo.list_by_user(user)`
  if `user` else `run_repo.list_all(limit)`.
- Register new routers in `backend/main.py` (under `/api`, before the static mount).

### 6. `backend/deps.py`
- `url_service()` already provides signing. No new providers (repos already wired in Phase 1/A/C).

## Error handling
- `results/files` with a missing/empty prefix → `[]` (UI shows "no files yet" — e.g. a run that
  hasn't finished or failed before writing).
- `results/downloads` object not under `results/` → 400 "invalid object".
- `results/downloads` object that doesn't exist → still return a signed URL (GET 404s at GCS) OR
  pre-check existence and skip — **decision: pre-check with `object_exists` and omit missing
  objects from the response** (so the UI never hands you a dead link), include a `missing` list.
- Unknown project/case in `results/files` → empty list (not an error).
- Firestore unavailable → 503; never silently empty.

## Testing
- `core/results_paths.py`: `results_prefix` exact string.
- `core/uploads.py`: `get_url` produces a GET-method signed URL (assert via a fake bucket/signer
  like the existing upload tests, or assert the call args).
- `core/case_records.py` / `core/run_repo.py`: `list_all` / `list_by_user` on the fakes.
- `core/storage.py`: in-memory `list_objects` returns names + sizes under a prefix.
- `routes_results`: `/api/results` shape from a seeded `of_runs`; `/api/results/files` lists a
  seeded case; `/api/results/downloads` signs only `results/` objects (400 otherwise) and omits
  missing ones. Use the in-memory fakes + a fake signer in conftest.
- `routes_cases`: `/api/cases` returns project+name; `/api/projects` lists projects.
- `routes_admin`: `/api/admin/runs` all vs `?user=`; non-admin → 403.
- Full suite green (ADC-disabled). Frontend untouched.

## Rollout
- Backend-only, no runtime change → **no image rebuild**. Merge to main → CI deploys.
- Verify live: `GET /api/projects`, `/api/cases`, `/api/results` return data; a
  `POST /api/results/downloads` for a real `results/...` object returns a working signed URL.
