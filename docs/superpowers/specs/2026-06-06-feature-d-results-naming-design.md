# Feature D — Human-friendly GCS results layout + one-word job codenames

**Date:** 2026-06-06
**Status:** Approved design (pre-implementation)
**Project:** `cfd-lemnisca` OpenFOAM-on-Batch web app (`phase3-run-app/`)

## Context

Today the GCS results layout is verbose and redundant, and the job name is an
auto-generated machine string. From the runtime:

```
results/<case_id>/<machine>/<job_name>/task_<N>/
```
where `job_name = of-<case>-<machine>-<timestamp>` — so `case` appears 3×, `machine`
2×, plus an always-`task_0` folder for single-case runs. It reads "computer-like."

Feature D makes the results layout human-friendly and replaces the auto job name with a
short, memorable, **one-word codename** the user picks (or accepts a suggestion).
`cases/` and `checkpoints/` layouts are **unchanged**.

## Goals

1. Reorganize `results/` to a clean, job-centric layout; drop the redundant `<machine>`
   and `task_<N>` folders.
2. Make the job name a **mandatory, user-facing one-word codename** with a pre-filled,
   never-collides suggestion + shuffle + custom entry.
3. Bundle a curated ~1,500-word codename list (fun, ≤2 syllables, easy to pronounce).
4. Guarantee global uniqueness of codenames so result folders never clobber and Batch
   job IDs never collide.

## Non-goals

- Migrating existing results under the old layout (left as-is; new runs use the new one).
- Changing `cases/` or `checkpoints/` layouts.
- Renaming past `of_runs` documents (old verbose IDs stay; new runs use codenames).

## Decisions (locked during brainstorming)

| # | Decision |
|---|---|
| 1 | Results layout is **job-centric**: `results/{singlecase\|multicase}/<codename>/<case_id>/` |
| 2 | **Drop `<machine>` and `task_<N>`** from the results path (machine kept in `of_runs`/manifest) |
| 3 | Job name = a **single-word codename**; mandatory at submit |
| 4 | Codenames are **globally unique and permanent** (audited in `of_runs`, never reused) → used directly as folder **and** Batch job ID, **no suffix** |
| 5 | Default = a random **unused** codename (shuffle for another); user may type a custom slug |
| 6 | Multi-case jobs **dedupe** case IDs at submit (so each case folder is unique within a job) |

> Refinement vs. the earlier "invisible timestamp suffix" idea: because `of_runs` is a
> permanent audit log and we reserve codenames atomically, a codename is never reused —
> so we can use it cleanly everywhere with **no suffix**, which better matches the
> "one word" goal. (Exhaustion fallback below.)

## Results layout

```
results/singlecase/<codename>/<case_id>/        e.g. results/singlecase/phoenix/case_0006/
results/multicase/<codename>/<case_id>/         e.g. results/multicase/otter/case_0006/
                                                      results/multicase/otter/case_0007/
```
- `singlecase` vs `multicase` chosen at runtime by whether `CASE_ID_LIST` is set.
- Each case folder holds the same artifacts as today (`manifest.json`, `runtime.json`,
  `solver.stdout.log`, `exit_code.txt`, `result.tar.gz`, `_SUCCESS`/`_FAILED`).
- `cases/<case_id>/…` and `checkpoints/<case_id>/<variant>/latest/…` are **unchanged**.

## Job codename model

- **codename** = the job name: one word, lowercased, `^[a-z][a-z0-9-]{1,38}$`. It is the
  display name, the results folder, **and** the Batch job ID — one value everywhere.
- **Uniqueness (atomic):** at submit, reserve the codename by an atomic create-only write
  (mirrors `CaseRepository.allocate_ids`' `create_exclusive` pattern) keyed in `of_runs`.
  If it already exists → reject (custom) or the suggester picks another (default). Because
  `of_runs` never deletes, a codename is permanently consumed → Batch never sees a reused
  job ID, and result folders never clobber.
- **Default suggestion:** `GET /api/job-name/suggest` returns a random codename not present
  in `of_runs`. Frontend uses it to pre-fill + power a shuffle button.
- **Custom entry:** the user may type their own; validated against the slug regex and the
  uniqueness check. Invalid → 400 with the rule; taken → 400 "name already used."
- **Exhaustion fallback:** if (improbably) all ~1,500 words are consumed, the suggester
  appends a numeric suffix (`phoenix-2`); still a valid slug.

## Wordlist

- `core/codenames.py` — a curated list of ~1,500 words meeting: **one word, ≤2 syllables,
  easy to pronounce, fun/creative** (vibes: critters, elements, stones, tasty, punchy,
  short-myth). Single source of truth for both suggestion and (implicitly) what users see.
- Helpers: `suggest_unused(existing: set[str]) -> str`, `is_valid_codename(s: str) -> bool`.

## Components & data flow

1. **`core/codenames.py`** (new) — wordlist + `suggest_unused` + `is_valid_codename`.
2. **`core/naming.py`** — replace `build_job_name(...)` usage: the codename IS the job name
   (no machine/timestamp construction). Keep `canonical_case_id`, `variant_for_machine`,
   `sanitize_job_part` (still used for checkpoints/variant).
3. **`backend/schemas.py`** — `SubmitReq` gains required `job_name: str`.
4. **`backend/routes_jobs.py`**:
   - `submit`: dedupe `case_ids`; validate + atomically reserve `job_name`; use it as the
     Batch job ID and the `of_runs` doc key; store it as the display name. (RBAC unchanged.)
   - new `GET /api/job-name/suggest` (requires an active user) → `{name: "<unused codename>"}`.
5. **`core/batch_jobs.py`** — pass the codename as the `JOB_NAME` env to the runtime (it
   already does); no machine/task in the result path means the builder is otherwise unchanged.
6. **`runtime/run_case_in_batch.sh`** — change `RESULT_PREFIX` to
   `gs://${BUCKET}/results/${MODE}/${JOB_NAME}/${CASE_ID}` where
   `MODE=$( [[ -n "${CASE_ID_LIST:-}" ]] && echo multicase || echo singlecase )`; drop the
   `task_${TASK_INDEX}` segment and the `${VARIANT_ID}` segment from results. `VARIANT_ID`
   stays for the (unchanged) checkpoint path. **Requires a runtime image rebuild → `openfoam:12.0.3`** and a `RUNTIME_IMAGE` bump in `deploy.yml`.
7. **`cli/main.py`** — `run` accepts an **optional** `--job-name`; if omitted, it
   auto-picks an unused codename from the wordlist. Either way the codename is validated
   + reserved like the API path.
8. **Frontend** (`Run` view + `lib/api.ts`): a **required job-name field** pre-filled via
   `GET /api/job-name/suggest`, a **shuffle** button (re-calls suggest), and free-text
   custom entry with inline validation; submit is blocked until non-empty + valid.

## Error handling
- Empty/invalid job name → 400 (and the SPA blocks submit client-side too).
- Taken job name → 400 "name already used" (atomic reserve lost the race or reused).
- Duplicate case IDs in a multi-job → silently de-duplicated before building tasks.
- Reserve succeeds but Batch submit fails → release/ignore the reservation is unnecessary
  (the codename stays consumed; harmless — it just won't be re-suggested). Log it.

## Testing
- `core/codenames.py`: every word matches the slug regex + length; `suggest_unused`
  never returns a used name; exhaustion appends a numeric suffix.
- `core/naming.py`: codename validation accepts good slugs, rejects spaces/caps/symbols.
- `routes_jobs`: submit rejects empty/invalid/taken names; dedupes cases; `of_runs` keyed
  by codename; `GET /api/job-name/suggest` returns an unused, valid name.
- `runtime/run_case_in_batch_test.sh`: `RESULT_PREFIX` has the new
  `results/{singlecase|multicase}/<job>/<case>` shape, no `task_`/machine segments;
  checkpoints unchanged.
- Frontend: suggest pre-fills, shuffle re-fetches, invalid/empty blocks submit.
- Full suites stay green (ADC disabled for the python run, per the CI gotcha).

## Rollout
1. Ship backend + frontend (CI auto-deploys) — submit now requires a codename.
2. Rebuild the **runtime image `openfoam:12.0.3`** (linux/amd64) with the new
   `RESULT_PREFIX`, push, and bump `RUNTIME_IMAGE` in `deploy.yml` → redeploy. Until the
   runtime image is bumped, new jobs would still write the old results path, so the runtime
   rebuild is part of shipping D (not optional).
3. Old results under the previous layout remain untouched.
