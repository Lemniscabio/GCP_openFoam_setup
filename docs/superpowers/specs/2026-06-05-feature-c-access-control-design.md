# Feature C — Access Control (RBAC + admin-approval gate)

**Date:** 2026-06-05
**Status:** Approved design (pre-implementation)
**Project:** `cfd-lemnisca` OpenFOAM-on-Batch web app (`phase3-run-app/`)
**Builds on:** Feature A (Firestore) — `docs/superpowers/specs/2026-06-05-firestore-audit-foundation-design.md`

## Context

Today the app authenticates users (`backend/auth.py`: Google ID token + `hd==lemnisca.bio`
Workspace gate) but does **no authorization** — any signed-in `@lemnisca.bio` user can
upload, submit, and view everything. Feature C adds role-based authorization on top of
the existing authentication, with an **admin-approval gate**: a newly signed-in user can
do nothing until an admin approves them and assigns a role.

This is the security layer in the post-MVP roadmap (A → **C** → B; D independent).

## Goals

1. Three roles + an approval lifecycle: `admin`, `runner`, `viewer`; `pending`/`active`/`disabled`.
2. New users land as `pending` and are blocked from all actions until an admin approves.
3. Admins manage users: approve, assign/change role, disable (revoke).
4. No lockout / chicken-and-egg: seed admins are auto-provisioned from config on login.
5. Org-wide visibility: every active user sees all runs/cases (it's an audit tool).
6. Preserve the offline-testable architecture (in-memory fake repository).

## Non-goals (deferred)

- Per-resource ACLs / per-project permissions (roles are coarse by design).
- Monitoring/dashboard views → **Feature B** (C only adds the Admin tab + role-gating).
- GCS naming → **Feature D**.

## Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|---|---|
| 1 | Role + status model | roles `admin`/`runner`/`viewer`; status `pending`/`active`/`disabled` (status separate from role) |
| 2 | Bootstrap | `OF_SEED_ADMINS` config list → auto-ensured `role=admin, status=active` on login |
| 3 | First-login provisioning | auto-create `of_users` doc as `status=pending` if none exists |
| 4 | Visibility scope | all active users (any role) see **all** org runs/cases |
| 5 | Revoke | set `status=disabled` (keep the record); never delete |
| 6 | Disabled UX | distinct "access revoked" message vs the "pending approval" screen |

## Data model — `of_users/{email}` (Firestore, `of_`-prefixed)

```
of_users/{email}             # doc id = lowercased email
  email        string
  role         "admin" | "runner" | "viewer" | null   # null while pending
  status       "pending" | "active" | "disabled"
  requested_at timestamp      # first login
  decided_by   string|null    # admin email who last approved/changed (audit)
  decided_at   timestamp|null
```

## Permission matrix

| Capability | admin | runner | viewer | pending/disabled |
|---|---|---|---|---|
| View cases/runs (`GET /api/cases`, `/api/jobs`, run detail) | ✅ | ✅ | ✅ | ❌ |
| Upload (`/api/cases:allocate`, `:finalize`) + Submit (`POST /api/jobs`) | ✅ | ✅ | ❌ | ❌ |
| Manage users (`/api/admin/users*`) | ✅ | ❌ | ❌ | ❌ |
| `GET /api/me` | ✅ | ✅ | ✅ | ✅ (any authenticated user) |

`GET /api/me` is reachable by any authenticated user (including pending/disabled) so the
SPA can render the correct screen.

## Components & data flow

### 1. `core/users.py`
- `UserRecord` dataclass mirroring the schema.
- `UserRepository` Protocol with `FirestoreUserRepository` (prod) + `InMemoryUserRepository` (tests).
- Methods: `get(email)`, `upsert(record)`, `list_all()`, `set_decision(email, role, status, decided_by)`.
- Pure helper `resolve_on_login(email, seed_admins, existing) -> UserRecord`:
  - if `email in seed_admins` → ensure `role=admin, status=active` (idempotent).
  - elif no existing record → new `status=pending, role=null, requested_at=now`.
  - else → return existing unchanged.

### 2. RBAC dependencies (`backend/rbac.py`)
Built on the existing `current_user` (authentication). Each loads/creates the caller's
`of_users` record (via `resolve_on_login`) and enforces:
- `current_account` → returns `(User, UserRecord)`; auto-provisions on first login. Never 403s by itself.
- `require_active` → 403 unless `status==active`.
- `require_runner` → 403 unless `role in {runner, admin}` and `status==active`.
- `require_admin` → 403 unless `role==admin` and `status==active`.
- Dev mode (`OF_DEV_NO_IAP=1`) → synthesize an active admin so local dev/tests aren't blocked.

Apply to existing routes per the matrix:
- `routes_cases.allocate/finalize` → `require_runner`.
- `routes_jobs.submit` → `require_runner`; `list_runs`/`run_detail` → `require_active`.
- `routes_cases.list_cases` → `require_active`.

### 3. New endpoints (`backend/routes_me.py`, `backend/routes_admin.py`)
- `GET /api/me` → `{email, role, status}` (uses `current_account`, no role gate).
- `GET /api/admin/users` → list all `of_users` (`require_admin`).
- `POST /api/admin/users/{email}` → body `{role?, status?}`; approve / change role / disable
  (`require_admin`). Sets `decided_by=caller`, `decided_at=now`. Guard rails:
  - cannot disable or demote yourself (prevents accidental self-lockout).
  - a seed admin cannot be demoted/disabled (re-promoted on next login anyway; reject explicitly for clarity).

### 4. Config (`core/config.py`)
- `seed_admins: list[str]` from `OF_SEED_ADMINS` (comma-separated; default the two known admins).

### 5. Frontend
- `lib/api.ts`: `getMe()`, `listUsers()`, `setUser(email, {role,status})`.
- On load, call `GET /api/me`; route to:
  - `pending` → "Access pending admin approval" screen.
  - `disabled` → "Access revoked — contact an admin" screen.
  - `active` → app; **viewer** sees Cases/Runs but Upload/Run actions hidden/disabled.
- New **Admin tab** (visible only when `role==admin`): user table (email, status, role, decided_by),
  with approve + role-select + disable controls; pending users sorted first.
- Header shows signed-in email + role chip (the previously-missing "profile").

## Error handling
- Unknown/last-state edge cases: `current_account` upserts a pending record rather than
  failing, so a first-time caller always gets a clean 403 with a "pending" body (not a 500).
- Admin acting on a non-existent target email → 404.
- Self-lockout guard (cannot disable/demote self) → 400.
- Firestore unavailable → 503 with a clear message; never silently allow access (fail closed).
- `require_*` always **fail closed**: any doubt about role/status → deny.

## Testing
- `core/users.py`: `resolve_on_login` for seed-admin / new-user / existing-user; repo CRUD on the fake.
- RBAC deps: pending→403, viewer can GET not POST, runner can POST, admin can manage, dev-mode admin.
- Endpoints: `/api/me` for each status; admin approve flow; self-lockout guard; non-admin → 403 on admin routes.
- Existing 89 tests stay green (routes now require a role — update fixtures to inject an active admin/runner by default).
- Frontend: `getMe` routing (pending/disabled/viewer/admin); admin actions call the right endpoints.

## Rollout / ordering note
Adding `require_*` to existing routes means **every** `/api/*` action needs an `active`
user once deployed. Before/at deploy:
1. Ensure `OF_SEED_ADMINS` is set in the Cloud Run env (so you + gaurav aren't locked out).
2. On first post-deploy login, seed admins become active admins automatically; approve
   everyone else from the Admin tab.

## Open implementation details (resolved at plan time)
- Exact wiring of `current_account` (a dependency returning both `User` and `UserRecord`).
- Whether `/api/me` provisioning writes on every call or only first (write-once via `get`-then-`upsert-if-missing`).
- Frontend route-guard placement (top-level gate in `App.tsx` after `getMe`).
