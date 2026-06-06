# Phase 3 — Frontend v2 (connected 5-section flow + Results browser + Profile)

**Date:** 2026-06-06
**Status:** Approved design (pre-implementation)
**Project:** `cfd-lemnisca` OpenFOAM-on-Batch web app (`phase3-run-app/frontend/`)
**Builds on:** Phase 1 (Projects) + Phase 2 (Read/Download APIs).

## Context

The backend v2 (Phases 1–2) is deployed but the **frontend is out of sync**: `UploadView`/
`api.ts` don't send `project`, so the live upload/submit flow is broken. Phase 3 redesigns
the UI into a connected, project-organized 5-section flow with a Results browser and a
role-aware Profile, and **reconnects** it to the new APIs. It also folds in the small
"my runs" + "case metadata" reads.

## Goals

1. 5 navigable sections — **Upload → Cases → Submit → Status → Results** — with shared
   "flow" state so they feel connected (not isolated tabs).
2. Project-first upload (mandatory) with a **pre-upload validation modal**.
3. Cases as a **project → case tree**, auto-selecting just-uploaded cases, showing each
   case's `metadata.json`.
4. **Submit confirmation modal** before launching a job.
5. A new **Results browser** (tree + per-file/case/all downloads behind a confirm modal).
6. A **Profile page** (via the header): identity + my runs; admin-only user management +
   reporting. The old Admin tab is removed from the nav.

## Non-goals
- Backend beyond the two tiny reads below (Phases 1–2 cover the rest).
- Visual companion / pixel mockups (declined; follow the existing batch-launcher aesthetic).

## Decisions (locked during brainstorming)

| # | Decision |
|---|---|
| 1 | **Navigable tabs + shared flow state** (not a strict wizard). |
| 2 | Profile reached via the **header profile block**, not a 6th tab; **Admin tab removed**, content moves into Profile (admin-only). |
| 3 | **My runs** via a new `GET /api/me/runs`; **not** by reusing `/api/results`. |
| 4 | **Soft active-project context**: upload sets the current project (default focus + default submit project); trees still show all projects and you can switch freely. |
| 5 | `metadata.json` shown **lazily on case-expand** via `GET /api/cases/{case_id}/metadata?project=` (not loaded for the whole list). |

## Two small backend additions (ride along — bundling the SPA rebuilds the backend image anyway)

1. `GET /api/me/runs` — `require_active` → `run_repo.list_by_user(account.user.email)` →
   `{runs: [...]}`. (Reuses Phase 2's `list_by_user`.)
2. `GET /api/cases/{case_id}/metadata?project=<p>` — `require_active`; reads
   `cases/<project>/<case_id>/case/metadata.json` via `storage.read_text`; returns
   `{metadata: <parsed json>}` or 404 if absent. Validate `project` with
   `is_valid_project_name` (400 otherwise).

## Shared flow state (`App.tsx`)

A small lifted state object (or a React context) — no new library:
```
{ activeProject: string | null, selectedCaseIds: string[] }
```
- Upload success → `activeProject = <project>`, `selectedCaseIds = <new case ids>`, go to Cases.
- Cases → reads/writes `selectedCaseIds`; switching the focused project updates `activeProject`.
- Submit → uses `activeProject` + `selectedCaseIds`.
Single-project enforcement is naturally satisfied: selection is scoped to one project in the
Cases tree (selecting a case in a different project replaces/zeros the prior selection, or the
UI restricts multi-select to within one project — see Cases below).

## Sections

### 1. Upload (`UploadView`)
- **Project field (mandatory):** a combobox — pick an existing project (`GET /api/projects`)
  or type a new name; validated client-side against `^[^/]+$`, non-empty, not `.`/`..`,
  ≤128 chars (mirror of backend `is_valid_project_name`). Submit blocked until valid.
- Folder drop/select (existing). Group into cases (existing `groupIntoCases`).
- **Pre-upload modal:** before uploading, scan each detected case's files; if any case lacks
  `command.sh` or `metadata.json`, show a blocking modal listing the offending case(s); do not
  upload. (Backend still validates at finalize.)
- On confirm: `allocate(project, cases)` → PUT pool (existing) → `finalize(project, caseId, {name})`
  per case. On success: set flow state (activeProject, selectedCaseIds = uploaded ids) → go to Cases.

### 2. Cases (`CasesView`)
- `GET /api/cases` → group by `project` into a **parent/child tree** (project → cases with
  name/ready). Focus/expand `activeProject`; **auto-select** `selectedCaseIds`.
- Selection is **single-project**: selecting cases under a project sets `activeProject` to it;
  selecting a case under a different project switches `activeProject` and clears the prior
  selection (so a job is always one project).
- Expanding a case lazily calls `GET /api/cases/{case}/metadata?project=` and shows the JSON.
- "Submit selected" → go to Submit (selection carried).

### 3. Submit (`SubmitView`, renamed from `RunView`)
- Shows `activeProject` + selected case(s) (names), machine picker (existing), Spot toggle,
  codename field + shuffle (existing from D).
- **Run job → confirmation modal** summarizing: project, case names, machine, mpi ranks,
  codename, Spot. Confirm → `submit(case_ids, machine, spot, job_name)` → go to Status.
- Keep the viewer/role gate (viewers can't submit).

### 4. Status (`RunsView`, renamed "Status")
- Unchanged behavior: `GET /api/jobs` (live + reconcile), the auto-updated list.

### 5. Results (`ResultsView`, new)
- `GET /api/results` → build a tree **project → codename(job) → case** (with `state`,
  `submitted_by`, `submitted_at` shown inline).
- Expand a case → `GET /api/results/files?project=&job=&case=` → list files (name + size).
- **Download actions:** per file, "download case" (all files of a case), "download all"
  (all files across the job's cases) → **confirmation modal** → `POST /api/results/downloads`
  with the object list → for each returned `{object,url}` trigger a browser download; show any
  `missing` items as a notice.

### Profile (`ProfileView`, new — via header)
- Clicking the header profile block routes to Profile (App state `view: "profile" | section`).
- **Everyone:** identity (email, role, status) + **My runs** (`GET /api/me/runs`) as a list.
- **Admin only:** **Users** (table from `listUsers`; approve / role-select / disable via
  `setUser`, with the self/seed-admin guard messages surfaced) + **Reporting** (projects from
  `GET /api/projects`; all/per-user runs from `GET /api/admin/runs`).

## `api.ts` changes
- `allocate(project, cases)` and `finalize(caseId, {name, openfoam_version, project})` — add `project`.
- Add: `getProjects()`, `getResults()`, `getResultFiles(project, job, case)`,
  `postDownloads(objects)`, `getMyRuns()`, `getCaseMetadata(project, caseId)`.
- `submit(...)` already sends `job_name`.

## Error handling
- Invalid project name (client) → inline error, submit disabled.
- Pre-upload missing files → blocking modal, no upload.
- `finalize`/`submit` 400/422 → surface the backend message (project/metadata/validation).
- `getCaseMetadata` 404 → "no metadata.json" (shouldn't happen post-validation, but handle).
- Downloads `missing` list → small "N file(s) unavailable" notice; still download the rest.
- Role gates: viewers see read-only (no Upload action, no Submit, no admin Profile sections).

## Testing
- Vitest (existing `src/tests/`): `api.ts` new methods send the right method/path/body
  (`allocate`/`finalize` include `project`; `getResults`/`getResultFiles`/`postDownloads`/
  `getMyRuns`/`getCaseMetadata`).
- A pre-upload-validation unit test (given a FileList missing `metadata.json` → modal/blocked).
- Backend: `GET /api/me/runs` (active user gets own runs; viewer allowed) and
  `GET /api/cases/{case}/metadata` (returns parsed JSON; 404 absent; 400 bad project) — pytest
  with in-memory fakes; full suite green ADC-disabled.
- `npm run build` succeeds.
- Manual smoke after deploy (below).

## Rollout
- Frontend + the two tiny backend reads. **No runtime rebuild** (no `run_case_in_batch.sh`
  change). Merge → CI builds the SPA into the backend image + deploys.
- **Smoke (this finally makes the live app usable again):** sign in → Upload to a project
  (with `command.sh`+`metadata.json`) → Cases shows it in the project tree, metadata visible →
  Submit (confirm modal) on Standard → Status shows it → Results lists files + a download works →
  Profile shows my runs (and admin sections for admins).
