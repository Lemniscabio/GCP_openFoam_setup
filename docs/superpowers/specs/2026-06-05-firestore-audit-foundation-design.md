# Feature A — Firestore Audit & Persistence Foundation

**Date:** 2026-06-05
**Status:** Approved design (pre-implementation)
**Project:** `cfd-lemnisca` OpenFOAM-on-Batch web app (`phase3-run-app/`)

## Context

The app (FastAPI backend on Cloud Run + React SPA) lets domain-authenticated users
upload OpenFOAM cases to GCS and run them on Google Cloud Batch. Today there is **no
database**: run status is derived live by listing Batch jobs (`core/status.py:list_runs`),
which means:

- No record of **who** submitted a run, **when**, or with what parameters
  (`list_runs` even returns `case_ids=[]`).
- History disappears once Batch purges old jobs.
- No place to attach user roles/approvals (needed for Feature C) or richer
  monitoring (Feature B).

Feature A is the **foundation**: a Firestore-backed persistence + audit layer that
records every run and every case, with guaranteed run-state updates via Pub/Sub.
Features C (access control) and B (monitoring) build on it. Feature D (GCS naming)
is independent.

## Goals

1. Persist an immutable audit record for every submitted run (who/when/what).
2. Persist a record for every uploaded case, including a human-friendly name.
3. Keep each run's live state (RUNNING/SUCCEEDED/FAILED) accurate **even if nobody
   opens the dashboard**, via Batch → Pub/Sub notifications.
4. Add no standing infrastructure cost (Firestore free tier) and minimal ops.
5. Preserve the existing offline-testable architecture (in-memory fakes).

## Non-goals (deferred)

- Roles, approval gates, view-only vs run permissions → **Feature C**.
- Dashboard UI, granular run/case monitoring views → **Feature B**.
- Human-friendly GCS paths and mandatory user-entered job names → **Feature D**.
  (A captures `job_name`/`name` fields now; D makes naming mandatory + restructures GCS.)

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Data store | **Firestore Native mode**, `(default)` DB, single-region `us-central1` | ~$0 at this scale (free tier: 50k reads/20k writes/1 GiB/day), no VPC connector/proxy, scales to zero. Verified vs official docs. |
| Collection naming | `of_`-prefixed (`of_runs`, `of_cases`) | Honors the "namespace everything `of-`" rule in case the project is ever shared. |
| Run-state updates | **Batch → Pub/Sub push** (Option 2) | Captures terminal state always, not only when someone reads the dashboard. |
| `of_runs` doc key | **`batch_job_id`** (the unique Batch job name) | Pub/Sub messages reference the Batch job UID/name → handler does an O(1) doc update. Friendly `job_name` is a field. |
| Test strategy | In-memory fake repositories | Matches existing `InMemoryStorage` pattern; unit tests stay offline. |

## Verified facts (official Google docs)

- Firestore free **daily** quota on the `(default)` DB: 50,000 reads, 20,000 writes,
  20,000 deletes, 1 GiB stored, 10 GiB/mo egress.
  (firebase.google.com/docs/firestore/quotas, cloud.google.com/firestore/pricing)
- Cloud Run → Firestore: client library via ADC, **no VPC connector**; backend SA
  needs `roles/datastore.user`. (cloud.google.com/run/docs/using-gcp-services)
- Only **one free database per project** — must be `(default)`.
- Batch Pub/Sub notifications: job spec `notifications` field with
  `message.type = JOB_STATE_CHANGED`; the **job SA** needs `roles/pubsub.publisher`
  on the topic; Batch publishes on each state change with the job UID + new state.
  (cloud.google.com/batch/docs/enable-notifications)

## Data model

### `of_runs/{batch_job_id}`
```
batch_job_id   string   # doc id; the unique Batch job name (e.g. of-multi-...-20260604133156)
job_name       string   # user-facing/friendly name (mandatory enforcement is Feature D)
submitted_by   string   # user email from the auth token
submitted_at   timestamp
region         string   # e.g. "us-central1"
machine_type   string   # e.g. "c2d-highcpu-32"
mpi_ranks      int
spot           bool
case_ids       array<string>   # ["case_0006","case_0007"]
case_names     array<string>   # resolved from of_cases at submit time
state          string   # SUBMITTED -> SCHEDULED/RUNNING -> SUCCEEDED/FAILED (from Batch)
finished_at    timestamp|null
```

### `of_cases/{case_id}`
```
case_id        string   # doc id (e.g. case_0006)
name           string   # human-friendly, user-entered at upload
uploaded_by    string   # user email
uploaded_at    timestamp
ready          bool      # set true at finalize
```

## Components & data flow

### 1. Repository layer (`core/`)
- `RunRepository` interface with two impls:
  - `FirestoreRunRepository` (prod; `google-cloud-firestore`).
  - `InMemoryRunRepository` (tests).
- `CaseRecordRepository` (the new Firestore-backed case *metadata*; distinct from the
  existing GCS-marker `CaseRepository` used for ID allocation). Same fake/real split.
- Both injected via `backend/deps.py`.

### 2. Write on case finalize (`backend/routes_cases.py`)
- `finalize` already validates the uploaded tree (F-001 fix). It additionally writes
  `of_cases/{case_id}` with `name` (new field), `uploaded_by`, `uploaded_at`, `ready=true`.
- The case **name** is supplied by the client: add `name` to the allocate/finalize
  request schema (`backend/schemas.py`) and capture it in the frontend upload flow
  (`frontend/src/views/UploadView.tsx` + `lib/upload.ts`).
- **Name is optional in A**, defaulting to the `case_id` when omitted, so A never
  blocks an upload. (Making a friendly name mandatory belongs to Feature D's naming pass.)

### 3. Write on submit (`backend/routes_jobs.py`)
- After a successful Batch submit, write `of_runs/{batch_job_id}` with all immutable
  facts, `state="SUBMITTED"`, resolving `case_names` from `of_cases`.
- The Batch job spec (`core/batch_jobs.py`) gains a `notifications` block pointing at
  the `of-batch-job-state` topic with `message.type = JOB_STATE_CHANGED`.

### 4. State updates (Pub/Sub push handler)
- New topic `of-batch-job-state`; a **push** subscription targets a new backend route
  `POST /internal/batch-events`.
- The handler:
  - verifies the request bears a valid **OIDC token from the dedicated push SA**
    (NOT the `current_user` Bearer flow — this route is exempt from the user gate),
  - parses the Batch notification (job UID/name + new state),
  - updates `of_runs/{batch_job_id}.state` and, on terminal states, `finished_at`.
- Reads (`list_runs`) now come from `of_runs` (ordered by `submitted_at desc`),
  so the dashboard no longer depends on Batch retention.

### 5. Infra (`infra/setup-cfd-lemnisca.sh`)
- Enable Firestore (Native, `us-central1`, `(default)`).
- Create topic `of-batch-job-state` + push subscription to the Cloud Run URL
  `/internal/batch-events` with a push-auth SA.
- IAM grants:
  - backend SA: `roles/datastore.user`.
  - job SA: `roles/pubsub.publisher` on the topic.
  - push subscription SA: token-creator/invoker as required for OIDC push to Cloud Run.

## Error handling

- **Firestore write failure on submit:** the Batch job has already been created — do
  NOT fail the user request after submit. Log the error and return success with a
  warning flag; a missing `of_runs` doc is self-healing on the first Pub/Sub event
  (handler upserts). (Order: submit Batch job first, then write doc.)
- **Pub/Sub handler, unknown `batch_job_id`:** upsert a minimal doc (don't drop the
  event); log for investigation.
- **Duplicate/late Pub/Sub deliveries:** handler is idempotent — only advances state
  monotonically (never overwrites a terminal state with a non-terminal one).
- **Bad/unauthenticated push request:** return 401/403; never process.
- **Firestore unavailable on read:** dashboard surfaces a clear error; does not crash.

## Testing

- Unit tests with in-memory repos for: of_cases written at finalize (with name);
  of_runs written at submit (fields + case_name resolution); list_runs reads from repo.
- Pub/Sub handler tests: valid event advances state + sets finished_at; unknown id
  upserts; terminal-state idempotency; unauthenticated request rejected.
- Schema tests: `name` required/handled in allocate/finalize.
- Keep existing 68 python tests + runtime bash tests green.
- Frontend: upload flow includes and sends `name`.

## Open implementation details (resolved at plan time, not blocking design)

- Exact Batch notification message field names (job UID vs name) — confirm against the
  Python `batch_v1` types when wiring the handler.
- Firestore composite index for `of_runs` ordered queries (declare as needed).
- Whether to also persist `of_users` now (empty stub) to smooth the C handoff — likely
  yes, but C owns its schema.
