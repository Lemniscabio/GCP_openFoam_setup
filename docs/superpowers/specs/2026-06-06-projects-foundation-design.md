# Backend Phase 1 — Projects & GCS restructure

**Date:** 2026-06-06
**Status:** Approved design (pre-implementation)
**Project:** `cfd-lemnisca` OpenFOAM-on-Batch web app (`phase3-run-app/`)

## Context

This is the first backend phase of the app "v2" (Projects + connected 5-section UI +
Results browser). Today there is no project concept: cases are global `cases/case_xxxx/`
and results (post-Feature-D) are `results/{singlecase|multicase}/<codename>/<case>/`.

Phase 1 introduces **Projects** as a real entity and nests cases + results under a
project in GCS, and makes `metadata.json` a required case file. It is the foundation the
read APIs (Phase 2) and the new frontend (Phase 3) build on. Phase 1 is backend +
runtime only — no UI work here.

## Goals

1. A real **Project** entity; every new case and run belongs to exactly one project.
2. `cases/<project>/case_xxxx/` and `results/<project>/<codename>/<case_xxxx>/` layouts.
3. `metadata.json` becomes a required case file (present + valid JSON), exposed in results
   outside `result.tar.gz`.
4. Jobs are **single-project** (all cases in a job come from one project).
5. One runtime rebuild (`openfoam:12.0.4`) covering both path changes + metadata-out-of-tar.

## Non-goals (later phases)

- Read/list APIs (projects list, cases-by-project tree, results-tree, downloads) → **Phase 2**.
- Any frontend (5-section flow, modals, trees, Profile, Results browser, pre-upload modal) → **Phase 3**.
- Migrating existing pre-project `cases/`/`results/` data (left as-is).

## Decisions (locked during brainstorming)

| # | Decision |
|---|---|
| 1 | Project identity = **slug-only**: the user-entered name **is** the GCS path segment. Validated as a safe path segment (non-empty, no `/`, not `.`/`..`, no control chars, ≤128 chars). No display/slug split. |
| 2 | Projects are a **real entity** — `of_projects` collection. Created on first upload that names them (pick-or-create). |
| 3 | Case IDs stay **globally unique** (`case_0001` exists once, ever) and belong to exactly one project. |
| 4 | `<codename>` in the results path **is the Feature-D job name** (one-word, mandatory, globally unique). |
| 5 | **Single-project jobs**: a job's cases all come from one project → `PROJECT` is one value for the job. |
| 6 | `metadata.json` **required** in the case dir (present + parseable JSON; content opaque). |
| 7 | `metadata.json` exposed in results **outside** `result.tar.gz` (alongside manifest/runtime/logs). |
| 8 | `checkpoints/` layout **unchanged** (`checkpoints/<case>/<variant>/latest/`; global IDs keep it unambiguous). |
| 9 | Existing pre-project data left as-is. One runtime rebuild → `openfoam:12.0.4`. |

## GCS layout

```
cases/<project>/case_xxxx/case/...            (+ manifest.json, READY, metadata.json beside case/)
results/<project>/<codename>/case_xxxx/       (+ result.tar.gz, manifest.json, runtime.json,
                                               solver.stdout.log, exit_code.txt, metadata.json,
                                               _SUCCESS|_FAILED)
checkpoints/<case_xxxx>/<variant>/latest/...  (UNCHANGED)
```

## Data model (Firestore)

```
of_projects/<project>     name (=id), created_by, created_at
of_cases/<case_id>         + project           (existing: name, uploaded_by, uploaded_at, ready)
of_runs/<codename>         + project           (existing fields)
```

## Components & data flow

### 1. `core/projects.py` (new)
- `ProjectRecord` (name, created_by, created_at).
- `ProjectRepository` Protocol + `FirestoreProjectRepository` + `InMemoryProjectRepository`
  (methods: `get(name)`, `ensure(name, user, now) -> ProjectRecord` create-or-get via
  atomic create-only, `list_all()` [used by Phase 2]).
- `is_valid_project_name(s) -> bool`: non-empty, `len<=128`, no `/`, not `.`/`..`,
  no control chars (`\x00-\x1f`), no leading/trailing whitespace.

### 2. `core/cases.py`
- All paths gain the project segment: reservation marker `cases/<project>/<id>/.reserved`,
  `exists`, etc. `allocate_ids(project, count)` keeps **global** numbering — `_max_existing`
  scans `cases/*/case_xxxx/` across all projects via `list_case_ids()` (updated to parse the
  project level).

### 3. `core/storage.py`
- `list_case_ids()` updated for the new depth: a path `cases/<project>/case_xxxx/...` yields
  `case_xxxx`. Add `list_paths` usage already exists. (In-memory fake updated to match.)

### 4. `core/uploads.py`
- `case_prefix(project, case_id)` → `cases/<project>/<case_id>/`;
  `object_path(project, case_id, rel)` → `cases/<project>/<case_id>/case/<rel>`.

### 5. `core/validation.py`
- `validate_case(storage, project, case_id)`: base `cases/<project>/<case_id>`; still requires
  `manifest.json`, `READY`, the `case/` tree, and `case/command.sh`; **adds** `case/metadata.json`
  required AND parseable as JSON (error if missing or not valid JSON).

### 6. `core/case_records.py`
- `CaseRecord` gains `project`. Firestore + fake updated.

### 7. `backend/schemas.py` + `backend/routes_cases.py`
- `AllocateReq` gains required `project: str`; `FinalizeReq` gains required `project: str`.
  Both reject if `not is_valid_project_name(project)`.
- `allocate`: `project_repo.ensure(project, user)`, then reserve cases under the project
  (GCS markers `cases/<project>/<id>/.reserved`), return signed PUT URLs to
  `cases/<project>/<id>/case/...`. (`of_cases` is not written yet — same as today.)
- `finalize`: takes `project` in the body (the client knows it from upload); validates with it
  (`validate_case(store, project, case_id)`, now incl. metadata.json); writes manifest/READY;
  and writes the `of_cases` record **with `project`**. So `of_cases.project` is the source of
  truth for a case's project from finalize onward.
- `submit` (routes_jobs) reads each case's `project` from `of_cases` (written at finalize) —
  it does not take project in the request.

### 8. `backend/routes_jobs.py`
- `submit`: resolve each case's `project` from `of_cases`; **enforce all cases share one project**
  (400 if mixed); pass `PROJECT` into the builder/run record; store `project` on `of_runs`.

### 9. `core/batch_jobs.py`
- Pass `PROJECT` env to the runtime (single value, since single-project jobs).

### 10. `runtime/run_case_in_batch.sh`
- `CASE_PREFIX="gs://${BUCKET}/cases/${PROJECT}/${CASE_ID}"`.
- `RESULT_PREFIX="gs://${BUCKET}/results/${PROJECT}/${JOB_NAME}/${CASE_ID}"` (drop the
  `singlecase|multicase` segment from Feature D — superseded by `<project>`).
- Copy `case/metadata.json` to `${RESULT_PREFIX}/metadata.json` (separate upload, not only in
  the tar). `CHECKPOINT_PREFIX` unchanged. Requires the `PROJECT` env (guarded `: "${PROJECT:?}"`).
- **Runtime rebuild → `openfoam:12.0.4`**, `RUNTIME_IMAGE` bump in `deploy.yml`.

### 11. `backend/deps.py`
- `project_repo()` provider (Firestore).

### 12. `cli/main.py`
- Upload path: accept a required `--project`; thread through allocation + paths. Submit path:
  resolve project from `of_cases` (or accept `--project`) for the run.

## Error handling
- Invalid project name → 400 with the rule.
- Missing/invalid `metadata.json` → validation error at finalize/submit (and client pre-checks in Phase 3).
- Mixed-project job → 400 "all cases in a job must share one project."
- `project_repo.ensure` is create-only/idempotent (atomic) — concurrent first-uploads are safe.
- Existing pre-project cases have no `project`; they remain readable but can't be re-run without
  a project + metadata.json (acceptable per "leave as-is").

## Testing
- `core/projects.py`: `is_valid_project_name` (accept/reject cases incl. `/`, `..`, control chars);
  `ensure` create-or-get + atomicity on the fake.
- `core/cases.py`: `allocate_ids(project, n)` reserves under `cases/<project>/…`, numbering stays
  global across projects.
- `core/validation.py`: requires + parses `metadata.json`; rejects missing/invalid JSON; project-scoped base.
- `routes_cases`: allocate requires/validates project + creates it; finalize stores `project`.
- `routes_jobs`: submit resolves project, rejects mixed-project jobs, stores `project` on the run.
- `runtime/run_case_in_batch_test.sh`: `CASE_PREFIX`/`RESULT_PREFIX` include `<project>`, no
  `singlecase|multicase`; `metadata.json` copied to results separately; checkpoints unchanged.
- Full suites green (python ADC-disabled, runtime bash). Frontend untouched this phase.

## Rollout
1. Ship backend (CI deploys). Submit/upload now require a project + metadata.json.
2. Rebuild runtime `openfoam:12.0.4` (linux/amd64) with the new paths + metadata-out, push, bump
   `RUNTIME_IMAGE` in `deploy.yml`, redeploy. (Build the image **before** merging the deploy.yml
   bump, same ordering rule as Feature D.)
3. Old data untouched.
