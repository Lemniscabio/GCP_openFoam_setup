# App v2 Roadmap — Projects, Connected UI, Results Browser

**Created:** 2026-06-06
**Purpose:** Durable, high-level plan for the "v2" evolution so any phase can be picked up
fresh. Each phase gets its **own** brainstorm → spec → plan → codex-execute cycle when it's
about to be built (full specs/plans are written just-in-time, not up front, because they're
interactive and depend on the prior phase's API shapes).

## Vision

Evolve the app from isolated tabs over global cases into a **project-organized, connected
5-section transaction** (Upload → Cases → Submit → Status → Results) with a results browser
and a role-aware Profile/admin dashboard.

## Phases

### Phase 1 — Projects & GCS restructure (backend + runtime) — IN PROGRESS (2026-06-06)
Spec: `docs/superpowers/specs/2026-06-06-projects-foundation-design.md`
Plan: `docs/superpowers/plans/2026-06-06-projects-foundation.md`
- `of_projects` entity; `cases/<project>/case_xxxx/`, `results/<project>/<codename>/<case_xxxx>/`.
- `metadata.json` required case file (present + valid JSON), exposed in results outside the tar.
- Single-project jobs; `of_cases`/`of_runs` gain `project`; checkpoints unchanged.
- Runtime rebuild `openfoam:12.0.4` (+ deploy.yml pin). Old data left as-is.

### Phase 2 — Read & download APIs (backend) — PENDING
*(Absorbs the old "Feature B" monitoring/dashboard.)*
- List projects; cases **grouped by project** (tree for the Cases view).
- Results-tree listing (project → job → case → files).
- **Signed-URL downloads** (per file / per case / all) — no server-side zip (cases already
  have `result.tar.gz`; signed URLs offload to GCS, avoid Cloud Run memory/timeout).
- Admin reporting: all users, all projects, **who-ran-what/when**, per-user data.

### Phase 3 — Frontend v2 — PENDING
- 5-section nav: Upload → Cases → Submit → Status → Results, as one **connected transaction**
  (project + selections carried across steps).
- Upload: **mandatory project** + **pre-upload modal** that blocks if `command.sh`/`metadata.json`
  missing (client-side fail-fast; backend still authoritative).
- Cases: parent/child tree (project → cases), **auto-select** the just-uploaded cases; show each
  case's `metadata.json`.
- Submit: shows project + case(s); **confirmation modal** with job metadata before submitting.
- Status: unchanged.
- Results (new): parent/child tree, **download file / case / all** with a confirmation modal.
- **Profile page** (role-specific); the Admin tab **moves into** it. Admin view = users, projects,
  who-ran-what, per-user data.

## Locked decisions (apply across phases)
- **Projects:** real `of_projects` entity; **slug-only** names (user-entered = GCS path segment,
  validated; no display/slug split).
- **Case IDs:** globally unique (`case_0001` once, ever); a case belongs to exactly one project.
- **Job name = the one-word codename** (Feature D); globally unique; results folder segment.
- **Jobs are single-project** (all cases from one project).
- **`metadata.json`** required per case (opaque JSON the user writes; shown in Cases).
- **Downloads:** signed URLs, never server-side zip.
- **Status pipeline:** keep Pub/Sub + reconcile (debugged); `of_runs` is the durable audit log.
- **Old pre-project data:** left as-is (not migrated).
- **Rollout rule:** rebuild + push the runtime image *before* merging any `RUNTIME_IMAGE` bump.

## Status snapshot (2026-06-06)
- ✅ Feature A (Firestore audit), C (RBAC), D (codenames + results layout) — deployed.
- 🔄 Phase 1 — implemented via codex; pending runtime `12.0.4` rebuild + merge.
- ⏳ Phase 2, Phase 3 — pending (spec/plan each when started).
