# Phase 3 — Frontend v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the SPA into a connected 5-section flow (Upload→Cases→Submit→Status→Results) with a Results browser and a header Profile, reconnected to the Phase 1/2 project APIs.

**Architecture:** Navigable tabs + a small shared flow state (`activeProject`, `selectedCaseIds`) lifted in `App.tsx`. Project-first upload; project→case and results trees; confirmation modals; signed-URL downloads. Two tiny backend reads ride along (`/api/me/runs`, case metadata).

**Tech Stack:** React + TypeScript + Vite + Vitest; FastAPI (2 small endpoints).

**Spec:** `docs/superpowers/specs/2026-06-06-phase3-frontend-v2-design.md`

**Working dirs:** backend `phase3-run-app/` (python), frontend `phase3-run-app/frontend/`.
**Python tests:** `env -u GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_CONFIG=/tmp/empty-gcloud OF_DEV_NO_IAP=1 .venv/bin/pytest -q`. **Frontend:** `cd frontend && npx vitest run` and `npm run build`.

> NOTE on React-view tasks (5–10): full pixel JSX isn't reproduced — each task gives the
> exact behavior, state, API calls, and structure, and says to **match the existing view's
> styling/components** (read the current `views/*.tsx`, `components/ui/*`, `styles.css`). Tasks
> 1–4 (backend + api client + a pure helper) are full TDD with complete code.
>
> NOTE on build-green timing: Tasks 5–10 are an **interdependent UI cluster** — `App.tsx`
> (Task 5) imports views that are created/renamed across Tasks 6–10 (e.g. `SubmitView` lands in
> Task 8, `ResultsView`/`ProfileView` in 9–10). So `npm run build` will be RED between Tasks 5
> and 10; that's expected. Keep **Vitest green throughout** (api/casecheck tests are
> independent), and require `npm run build` GREEN only at the **end (Task 10 / final gate)**.
> Commit per task regardless. (To minimize red time you may stub the not-yet-built views as
> empty components in Task 5 and flesh them out in their tasks.)

---

## File Structure

**Create:** `backend/routes_me.py` route addition (or extend existing `routes_me.py`); `frontend/src/lib/casecheck.ts`; `frontend/src/views/ResultsView.tsx`; `frontend/src/views/ProfileView.tsx`; tests.
**Modify:** `backend/routes_me.py`, `backend/routes_cases.py`; `frontend/src/lib/api.ts` (+ `lib/client.ts` types); `frontend/src/App.tsx`; `frontend/src/components/AppShell.tsx`; `frontend/src/views/UploadView.tsx`, `CasesView.tsx`, `RunView.tsx`→`SubmitView.tsx`; remove `AdminView` usage (fold into ProfileView).

---

## Task 1: Backend — `GET /api/me/runs`

**Files:** Modify `backend/routes_me.py`; Test `tests/test_routes_me.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_routes_me.py`:
```python
def test_me_runs_returns_only_my_runs(client, mem_runs):
    import datetime as _dt
    from core.run_repo import RunRecord
    def mk(job, who):
        return RunRecord(batch_job_id=job, job_name=job, submitted_by=who,
            submitted_at=_dt.datetime(2026,1,1,tzinfo=_dt.timezone.utc), region="us-central1",
            machine_type="c2d-highcpu-8", mpi_ranks=4, spot=False, case_ids=["case_0006"],
            case_names=["WT"], project="turbine")
    mem_runs.create(mk("phoenix", "dev@lemnisca.bio"))   # the dev/admin default account
    mem_runs.create(mk("otter", "someone@lemnisca.bio"))
    r = client.get("/api/me/runs")
    assert r.status_code == 200
    assert [x["batch_job_id"] for x in r.json()["runs"]] == ["phoenix"]
```
(The conftest `client` default account is `dev@lemnisca.bio`.)

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `backend/routes_me.py`:
```python
import dataclasses
from backend.deps import run_repo

@router.get("/me/runs")
def my_runs(account=Depends(current_account), runs=Depends(run_repo)):
    return {"runs": [dataclasses.asdict(r) for r in runs.list_by_user(account[0].email)]}
```
(`current_account` already imported for `/api/me`; `account[0]` is the `User`.)

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add backend/routes_me.py tests/test_routes_me.py
git commit -m "feat(api): GET /api/me/runs (my activity)"
```

---

## Task 2: Backend — `GET /api/cases/{case_id}/metadata`

**Files:** Modify `backend/routes_cases.py`; Test `tests/test_routes_cases.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_routes_cases.py`:
```python
def test_case_metadata_returns_parsed_json(client, mem_storage):
    mem_storage.upload_bytes("cases/turbine/case_0006/case/metadata.json", b'{"author":"k"}')
    r = client.get("/api/cases/case_0006/metadata?project=turbine")
    assert r.status_code == 200
    assert r.json()["metadata"] == {"author": "k"}


def test_case_metadata_404_when_absent(client):
    r = client.get("/api/cases/case_0006/metadata?project=turbine")
    assert r.status_code == 404


def test_case_metadata_400_bad_project(client):
    r = client.get("/api/cases/case_0006/metadata?project=bad/name")
    assert r.status_code == 400
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — in `backend/routes_cases.py`:
```python
import json
from core.projects import is_valid_project_name

@router.get("/cases/{case_id}/metadata")
def case_metadata(case_id: str, project: str,
                  account=Depends(require_active), store=Depends(storage)):
    if not is_valid_project_name(project):
        raise HTTPException(status_code=400, detail="invalid project")
    path = f"cases/{project}/{case_id}/case/metadata.json"
    if not store.object_exists(path):
        raise HTTPException(status_code=404, detail="no metadata.json")
    return {"metadata": json.loads(store.read_text(path))}
```
(Ensure `require_active`, `storage`, `HTTPException` imported.)

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add backend/routes_cases.py tests/test_routes_cases.py
git commit -m "feat(api): GET /api/cases/{id}/metadata"
```

---

## Task 3: API client — project + new reads

**Files:** Modify `frontend/src/lib/api.ts`; Test `frontend/src/tests/api.test.ts`.

- [ ] **Step 1: Write the failing test** — append to `frontend/src/tests/api.test.ts` (match the file's fetch-mock + `ApiClient` construction style):
```ts
it("v2 endpoints: project on allocate/finalize + new reads", async () => {
  const calls: any[] = [];
  globalThis.fetch = vi.fn(async (url: any, init: any) => {
    calls.push({ url: String(url), method: init?.method, body: init?.body });
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  }) as any;
  const { ApiClient } = await import("../lib/api");
  const api = new ApiClient("", () => "tok");
  await api.allocate("turbine", [{ files: ["0/U"] }]);
  await api.finalize("case_0006", { name: "WT", project: "turbine" });
  await api.getProjects();
  await api.getResults();
  await api.getResultFiles("turbine", "phoenix", "case_0006");
  await api.postDownloads(["results/turbine/phoenix/case_0006/result.tar.gz"]);
  await api.getMyRuns();
  await api.getCaseMetadata("turbine", "case_0006");
  const find = (frag: string) => calls.find((c) => c.url.includes(frag));
  expect(JSON.parse(find(":allocate").body).project).toBe("turbine");
  expect(JSON.parse(find(":finalize").body).project).toBe("turbine");
  expect(find("/api/projects").method).toBe("GET");
  expect(find("/api/results/files").url).toContain("project=turbine");
  expect(find("/api/results/downloads").method).toBe("POST");
  expect(find("/api/me/runs").method).toBe("GET");
  expect(find("/metadata").url).toContain("project=turbine");
});
```

- [ ] **Step 2: Run → fail**: `cd frontend && npx vitest run src/tests/api.test.ts`.

- [ ] **Step 3: Implement** — in `frontend/src/lib/api.ts`, change `allocate`/`finalize` and add methods:
```ts
  allocate(project: string, cases: { files: string[] }[]) {
    return this.req("POST", "/api/cases:allocate", { project, cases });
  }
  finalize(caseId: string, body: { name?: string; openfoam_version?: string; project: string }) {
    return this.req("POST", `/api/cases/${caseId}:finalize`, {
      openfoam_version: body.openfoam_version ?? "12",
      project: body.project,
      ...(body.name !== undefined ? { name: body.name } : {}),
    });
  }
  getProjects() { return this.req("GET", "/api/projects"); }
  getResults() { return this.req("GET", "/api/results"); }
  getResultFiles(project: string, job: string, caseId: string) {
    const q = new URLSearchParams({ project, job, case: caseId });
    return this.req("GET", `/api/results/files?${q}`);
  }
  postDownloads(objects: string[]) {
    return this.req("POST", "/api/results/downloads", { objects });
  }
  getMyRuns() { return this.req("GET", "/api/me/runs"); }
  getCaseMetadata(project: string, caseId: string) {
    const q = new URLSearchParams({ project });
    return this.req("GET", `/api/cases/${caseId}/metadata?${q}`);
  }
```
Add types as needed (`ProjectInfo`, `ResultRun`, etc.). Update `lib/client.ts` if it re-exports.

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add frontend/src/lib/api.ts frontend/src/lib/client.ts frontend/src/tests/api.test.ts
git commit -m "feat(frontend): api client project + v2 reads"
```

---

## Task 4: Pre-upload validation helper

**Files:** Create `frontend/src/lib/casecheck.ts`, `frontend/src/tests/casecheck.test.ts`.

- [ ] **Step 1: Write the failing test** — create `frontend/src/tests/casecheck.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { missingRequiredFiles } from "../lib/casecheck";

describe("missingRequiredFiles", () => {
  it("flags cases missing command.sh or metadata.json", () => {
    const cases = [
      { name: "caseA", files: ["system/controlDict", "command.sh", "metadata.json"] },
      { name: "caseB", files: ["command.sh"] },            // missing metadata.json
      { name: "caseC", files: ["0/U"] },                   // missing both
    ];
    expect(missingRequiredFiles(cases)).toEqual([
      { name: "caseB", missing: ["metadata.json"] },
      { name: "caseC", missing: ["command.sh", "metadata.json"] },
    ]);
  });
  it("returns [] when all good", () => {
    expect(missingRequiredFiles([{ name: "a", files: ["command.sh", "metadata.json"] }])).toEqual([]);
  });
});
```

- [ ] **Step 2: Run → fail**.

- [ ] **Step 3: Implement** — create `frontend/src/lib/casecheck.ts`:
```ts
const REQUIRED = ["command.sh", "metadata.json"];

export type CaseFiles = { name: string; files: string[] };
export type MissingReport = { name: string; missing: string[] };

export function missingRequiredFiles(cases: CaseFiles[]): MissingReport[] {
  const out: MissingReport[] = [];
  for (const c of cases) {
    const basenames = new Set(c.files.map((f) => f.split("/").pop()));
    const missing = REQUIRED.filter((r) => !basenames.has(r));
    if (missing.length) out.push({ name: c.name, missing });
  }
  return out;
}
```

- [ ] **Step 4: Run → pass**; **Step 5: Commit**:
```bash
git add frontend/src/lib/casecheck.ts frontend/src/tests/casecheck.test.ts
git commit -m "feat(frontend): pre-upload required-file check"
```

---

## Task 5: Nav + flow state (AppShell + App.tsx)

**Files:** Modify `frontend/src/components/AppShell.tsx`, `frontend/src/App.tsx`.

- [ ] **Step 1: Implement** (UI; verify via `npm run build` + manual). Behavior:
  - `AppShell`: `Tab = "upload" | "cases" | "submit" | "status" | "results"`; `TABS` =
    `01 Upload, 02 Cases, 03 Submit, 04 Status, 05 Results` (remove `admin`). Keep the
    role filter (hide Upload/Submit actions for viewers — they can still see the tabs but
    actions are gated in the views). Make the **header profile block a button** that calls a
    new `onProfile()` prop.
  - `App.tsx`: lift flow state `const [activeProject, setActiveProject] = useState<string|null>(null)`
    and `const [selectedCaseIds, setSelectedCaseIds] = useState<string[]>([])`; add
    `const [view, setView] = useState<"section"|"profile">("section")`. Header profile click →
    `setView("profile")`. Render `ProfileView` when `view==="profile"`, else the active section.
    Wire sections:
    - `UploadView` `onUploaded={(project, ids) => { setActiveProject(project); setSelectedCaseIds(ids); setTab("cases"); }}`
    - `CasesView` `activeProject selectedCaseIds onChange={setSelectedCaseIds} onActiveProject={setActiveProject} onSubmit={() => setTab("submit")}`
    - `SubmitView` `project={activeProject} caseIds={selectedCaseIds} onSubmitted={() => setTab("status")}`
    - `status` → `RunsView`; `results` → `ResultsView`.
  - Remove the `admin` tab/route (AdminView content lives in ProfileView now).

- [ ] **Step 2: Verify** `cd frontend && npm run build` succeeds; **Step 3: Commit**:
```bash
git add frontend/src/components/AppShell.tsx frontend/src/App.tsx
git commit -m "feat(frontend): 5-section nav + flow state + Profile route"
```

---

## Task 6: UploadView — project + pre-upload modal

**Files:** Modify `frontend/src/views/UploadView.tsx`.

- [ ] **Step 1: Implement.** Behavior:
  - Add a **Project** combobox at the top: loads `api.getProjects()`; user picks one or types a
    new name. Validate client-side (`/^[^/]+$/`, non-empty, not `.`/`..`, length ≤128); block
    upload until valid + at least one case selected.
  - After grouping files into cases (existing `groupIntoCases`), on **Upload click** run
    `missingRequiredFiles(cases)`; if non-empty, open a **blocking modal** listing the bad
    cases and do not upload.
  - On confirm: `api.allocate(project, cases.map(c => ({files: c.files.map(f=>f.relPath)})))`
    → existing PUT pool → `api.finalize(caseId, {name: c.name, project})` per case.
  - On success: call `props.onUploaded(project, uploadedCaseIds)`.
  - Keep the existing per-case name field + drag/drop + progress.

- [ ] **Step 2: Verify** build + `npx vitest run`; **Step 3: Commit**:
```bash
git add frontend/src/views/UploadView.tsx
git commit -m "feat(frontend): Upload project field + pre-upload validation modal"
```

---

## Task 7: CasesView — project tree + auto-select + metadata

**Files:** Modify `frontend/src/views/CasesView.tsx`.

- [ ] **Step 1: Implement.** Behavior:
  - `api.listCases()` → group by `project` into a **parent/child tree** (project node → case
    rows with name + ready badge).
  - Expand/focus `props.activeProject`; **auto-check** `props.selectedCaseIds`.
  - **Single-project selection:** checking a case under project P sets active project = P;
    checking a case under a different project switches active project to the new one and clears
    prior checks. Call `props.onChange(ids)` + `props.onActiveProject(project)`.
  - Expanding a case lazily calls `api.getCaseMetadata(project, caseId)` and shows the JSON
    (pretty-printed); cache per case; show "no metadata" on 404.
  - "Submit selected" button (enabled when ≥1 selected and `canRun`) → `props.onSubmit()`.

- [ ] **Step 2: Verify** build; **Step 3: Commit**:
```bash
git add frontend/src/views/CasesView.tsx
git commit -m "feat(frontend): Cases project tree + auto-select + lazy metadata"
```

---

## Task 8: SubmitView (rename RunView) — confirmation modal

**Files:** Rename `frontend/src/views/RunView.tsx` → `frontend/src/views/SubmitView.tsx`; update imports.

- [ ] **Step 1: Implement.** Behavior:
  - Props `{ project, caseIds, canSubmit, onSubmitted }`. Show project + selected case names,
    machine picker (existing), Spot toggle, codename field + shuffle (existing from D).
  - **Run job → confirmation modal** summarizing project, cases, machine, mpi ranks, codename,
    Spot. On confirm → `api.submit(caseIds, machine, spot, jobName)` → `onSubmitted()`.
  - Keep the `canSubmit` viewer gate (disabled + "Read-only" for viewers).

- [ ] **Step 2: Verify** build + `npx vitest run`; **Step 3: Commit**:
```bash
git mv frontend/src/views/RunView.tsx frontend/src/views/SubmitView.tsx 2>/dev/null || true
git add -A frontend/src/views
git commit -m "feat(frontend): SubmitView with confirmation modal"
```

---

## Task 9: ResultsView (new) — tree + downloads

**Files:** Create `frontend/src/views/ResultsView.tsx`.

- [ ] **Step 1: Implement.** Behavior:
  - `api.getResults()` → build tree **project → codename → case** (show `state`, `submitted_by`,
    `submitted_at` inline on the codename/case rows).
  - Expand a case → `api.getResultFiles(project, codename, caseId)` → list `{name, size}`
    (human-readable sizes).
  - Download controls: per-file, **Download case** (all of a case's files), **Download all**
    (every file across the run's cases). Each opens a **confirmation modal** with the count,
    then `api.postDownloads(objectPaths)` → for each `{object, url}` trigger a browser download
    (create an `<a download>` per url, or open sequentially); show `missing` as a small notice.
  - Build object paths as `results/<project>/<codename>/<case>/<name>` (matches the backend).

- [ ] **Step 2: Verify** build; **Step 3: Commit**:
```bash
git add frontend/src/views/ResultsView.tsx
git commit -m "feat(frontend): Results browser with signed downloads"
```

---

## Task 10: ProfileView (new) — identity + my runs + admin sections

**Files:** Create `frontend/src/views/ProfileView.tsx`; remove `AdminView` import from `App.tsx` (content moves here; you may keep `AdminView.tsx` and embed it, or inline its table).

- [ ] **Step 1: Implement.** Behavior:
  - Props `{ me, onBack }` (back to sections).
  - **Everyone:** identity card (email, role, status) + **My runs** (`api.getMyRuns()`) as a list
    (codename, project, state, submitted_at).
  - **Admin only (`me.role === "admin"`):** a **Users** section (reuse the existing `AdminView`
    table: `listUsers` + `setUser` with the self/seed-admin error messages surfaced) and a
    **Reporting** section (`api.getProjects()` list + all/per-user runs via a new
    `api.getAdminRuns(user?)` → `GET /api/admin/runs`). Add `getAdminRuns` to `api.ts` if not
    present (`this.req("GET", \`/api/admin/runs${user ? \`?user=${encodeURIComponent(user)}\` : ""}\`)`).
  - Header profile block (Task 5) routes here; provide a way back to the sections.

- [ ] **Step 2: Verify** build + `npx vitest run`; **Step 3: Commit**:
```bash
git add frontend/src/views/ProfileView.tsx frontend/src/views/AdminView.tsx frontend/src/lib/api.ts frontend/src/App.tsx
git commit -m "feat(frontend): Profile page (identity + my runs + admin sections)"
```

---

## Final verification + rollout
- [ ] Python (ADC-disabled): `env -u GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_CONFIG=/tmp/empty-gcloud OF_DEV_NO_IAP=1 .venv/bin/pytest -q` — green.
- [ ] Frontend: `cd frontend && npx vitest run && npm run build` — green.
- [ ] **No runtime rebuild.** Merge to main → CI builds the SPA into the backend image + deploys.
- [ ] **Live smoke (makes the app usable again):** sign in → Upload to a project (with
  `command.sh`+`metadata.json`; try a missing one to see the modal block) → Cases tree shows it,
  metadata on expand → Submit (confirm modal) on **Standard** → Status shows it → Results lists
  files + a download works → Profile shows my runs (+ admin sections for an admin).
