# Feature D — Results Layout + Job Codenames Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace verbose auto job names with one-word codenames and reorganize `results/` to `results/{singlecase|multicase}/<codename>/<case_id>/` (machine + task_x dropped).

**Architecture:** A codename is the job name, the results folder, and the Batch job ID — one value. Uniqueness is guaranteed by an atomic create-only reservation in the permanent `of_runs` collection (never reused → no suffix). A bundled ~1,500-word list powers a suggest endpoint + shuffle. `cases/` and `checkpoints/` are unchanged.

**Tech Stack:** Python 3.12, FastAPI, google-cloud-firestore, pytest; React/TS (Vitest); bash runtime.

**Spec:** `docs/superpowers/specs/2026-06-06-feature-d-results-naming-design.md`

**Working dir:** `phase3-run-app/`. **Python tests:** `OF_DEV_NO_IAP=1 .venv/bin/pytest -q` (run with ADC disabled before merging: `env -u GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_CONFIG=/tmp/empty-gcloud OF_DEV_NO_IAP=1 .venv/bin/pytest -q`).

---

## File Structure

**Create:** `core/codenames.py` (wordlist + `is_valid_codename` + `suggest_unused`); `tests/test_codenames.py`.
**Modify:** `core/run_repo.py` (`try_reserve` + `existing_ids`); `backend/schemas.py` (`SubmitReq.job_name`); `backend/routes_jobs.py` (suggest endpoint + codename submit); `cli/main.py` (`--job-name`); `runtime/run_case_in_batch.sh` (RESULT_PREFIX); `runtime/tests/run_case_in_batch_test.sh`; `frontend/src/lib/api.ts`; `frontend/src/views/RunView.tsx`; `.github/workflows/deploy.yml` (RUNTIME_IMAGE bump). Tests: `tests/test_run_repo.py`, `tests/test_routes_jobs.py`, `tests/conftest.py` if needed.

---

## Task 1: Codename wordlist + helpers

**Files:** Create `core/codenames.py`, `tests/test_codenames.py`.

- [ ] **Step 1: Write the failing test** — create `tests/test_codenames.py`:
```python
import re

from core.codenames import WORDLIST, is_valid_codename, suggest_unused

_RE = re.compile(r"^[a-z][a-z0-9]{1,9}$")  # wordlist entries are pure single words


def test_wordlist_is_large_and_clean():
    assert len(WORDLIST) >= 1000
    assert len(WORDLIST) == len(set(WORDLIST))        # unique
    assert all(_RE.match(w) for w in WORDLIST)        # one word, short, lowercase


def test_is_valid_codename():
    assert is_valid_codename("phoenix")
    assert is_valid_codename("wind-tunnel-v3")        # custom slug allowed
    assert not is_valid_codename("Phoenix")           # caps
    assert not is_valid_codename("wind tunnel")       # space
    assert not is_valid_codename("3phoenix")          # must start with a letter
    assert not is_valid_codename("a")                 # too short
    assert not is_valid_codename("x" * 40)            # too long


def test_suggest_unused_avoids_used():
    used = {WORDLIST[0], WORDLIST[1]}
    for _ in range(50):
        assert suggest_unused(used) not in used


def test_suggest_unused_exhaustion_appends_suffix():
    name = suggest_unused(set(WORDLIST))              # everything used
    assert name.endswith("-2") or re.match(r".+-\d+$", name)
    assert is_valid_codename(name)
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_codenames.py -q` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement** — create `core/codenames.py`. Build `WORDLIST` to **≥1,000 (target ~1,500)** words meeting: one word, lowercase a–z only, 2–10 chars, ≤2 syllables, easy to pronounce, fun. Seed across vibes (critters, elements, stones, tasty, punchy, short-myth) and expand. Start from this seed and extend it to ≥1,000 unique entries:
```python
import random
import re

# One-word, easy-to-say codenames (≤2 syllables). Expand this to ~1500 unique words.
WORDLIST = [
    # critters
    "falcon", "raven", "lynx", "otter", "gecko", "panda", "robin", "koala", "wolf", "finch",
    "tiger", "puma", "heron", "ferret", "moose", "bison", "crane", "newt", "hawk", "swan",
    # elements / weather
    "ember", "frost", "storm", "blaze", "flint", "spark", "dusk", "comet", "nova", "flare",
    "gale", "haze", "drift", "thaw", "mist", "glow", "surge", "bolt", "rain", "snow",
    # stones / colors
    "jade", "onyx", "opal", "ruby", "amber", "cobalt", "slate", "coral", "pearl", "azure",
    "indigo", "ivory", "crimson", "teal", "olive", "umber", "sienna", "ochre", "mauve", "rust",
    # tasty
    "mango", "cocoa", "maple", "basil", "plum", "kiwi", "pepper", "melon", "mocha", "guava",
    "peach", "cherry", "lemon", "honey", "ginger", "nutmeg", "clove", "sage", "thyme", "berry",
    # punchy
    "turbo", "ninja", "rocket", "disco", "mojo", "banjo", "tango", "bongo", "pixel", "zippy",
    "rumble", "dynamo", "jet", "nitro", "vibe", "groove", "funk", "boom", "dash", "zoom",
    # short myth
    "atlas", "titan", "thor", "juno", "echo", "iris", "nyx", "zeus", "odin", "hera",
    "apollo", "luna", "helios", "ares", "freya", "loki", "isis", "rhea", "vega", "orion",
]
# NOTE: extend WORDLIST to >=1000 unique entries matching ^[a-z][a-z0-9]{1,9}$.

_CODENAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,38}$")  # custom slugs may include hyphens


def is_valid_codename(s: str) -> bool:
    return bool(_CODENAME_RE.match(s))


def suggest_unused(existing: set[str]) -> str:
    pool = [w for w in WORDLIST if w not in existing]
    if pool:
        return random.choice(pool)
    base = random.choice(WORDLIST)  # exhausted: append a numeric suffix
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"
```

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_codenames.py -q` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add core/codenames.py tests/test_codenames.py
git commit -m "feat(core): codename wordlist + suggest/validate helpers"
```

---

## Task 2: RunRepository — atomic reserve + existing_ids

**Files:** Modify `core/run_repo.py`; Test `tests/test_run_repo.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_run_repo.py`:
```python
def test_try_reserve_is_exclusive():
    repo = InMemoryRunRepository()
    assert repo.try_reserve(_rec(job_id="phoenix")) is True
    # second reservation of the same id fails
    assert repo.try_reserve(_rec(job_id="phoenix")) is False


def test_existing_ids():
    repo = InMemoryRunRepository()
    repo.try_reserve(_rec(job_id="phoenix"))
    repo.try_reserve(_rec(job_id="otter"))
    assert repo.existing_ids() == {"phoenix", "otter"}
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_run_repo.py -q` → FAIL (no `try_reserve`).

- [ ] **Step 3: Implement** — in `core/run_repo.py`:

Add to the `RunRepository` Protocol:
```python
    def try_reserve(self, record: "RunRecord") -> bool:
        """Atomically create the record only if its batch_job_id is unused.
        Returns True if reserved, False if the id already exists."""
        ...
    def existing_ids(self) -> set[str]: ...
```
Add to `InMemoryRunRepository`:
```python
    def try_reserve(self, record):
        if record.batch_job_id in self._runs:
            return False
        self._runs[record.batch_job_id] = record
        return True

    def existing_ids(self):
        return set(self._runs.keys())
```
Add to `FirestoreRunRepository`:
```python
    def try_reserve(self, record):
        from google.api_core.exceptions import AlreadyExists
        try:
            self._doc(record.batch_job_id).create({
                "batch_job_id": record.batch_job_id, "job_name": record.job_name,
                "submitted_by": record.submitted_by, "submitted_at": record.submitted_at,
                "region": record.region, "machine_type": record.machine_type,
                "mpi_ranks": record.mpi_ranks, "spot": record.spot,
                "case_ids": record.case_ids, "case_names": record.case_names,
                "state": record.state, "finished_at": record.finished_at,
            })
            return True
        except AlreadyExists:
            return False

    def existing_ids(self):
        return {d.id for d in self._c.collection(self._col).select([]).stream()}
```

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_run_repo.py -q` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add core/run_repo.py tests/test_run_repo.py
git commit -m "feat(core): RunRepository try_reserve + existing_ids"
```

---

## Task 3: SubmitReq requires job_name

**Files:** Modify `backend/schemas.py`; Test `tests/test_routes_jobs.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_routes_jobs.py`:
```python
def test_submit_requires_job_name(client, valid_case):
    # job_name omitted -> 422 (Pydantic required field)
    r = client.post("/api/jobs", json={"case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py::test_submit_requires_job_name -q` → FAIL (200/400, not 422).

- [ ] **Step 3: Implement** — in `backend/schemas.py`, update `SubmitReq`:
```python
class SubmitReq(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    machine_type: str
    spot: bool = False
    job_name: str
```

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py::test_submit_requires_job_name -q` → PASS.

> Other submit tests in this file will now 422 (they omit job_name). They are fixed in Task 5 by adding `"job_name": "<codename>"` to their payloads. If you run the whole file between tasks, expect those to fail until Task 5.

- [ ] **Step 5: Commit**:
```bash
git add backend/schemas.py tests/test_routes_jobs.py
git commit -m "feat(schemas): SubmitReq requires job_name codename"
```

---

## Task 4: `GET /api/job-name/suggest`

**Files:** Modify `backend/routes_jobs.py`; Test `tests/test_routes_jobs.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_routes_jobs.py`:
```python
def test_suggest_job_name_returns_unused_valid(client, mem_runs):
    from core.codenames import is_valid_codename
    from core.run_repo import RunRecord
    import datetime as _dt
    mem_runs.try_reserve(RunRecord(
        batch_job_id="phoenix", job_name="phoenix", submitted_by="d@lemnisca.bio",
        submitted_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc), region="us-central1",
        machine_type="c2d-highcpu-8", mpi_ranks=4, spot=False, case_ids=["case_0006"],
        case_names=["c"]))
    r = client.get("/api/job-name/suggest")
    assert r.status_code == 200
    name = r.json()["name"]
    assert is_valid_codename(name) and name != "phoenix"
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py::test_suggest_job_name_returns_unused_valid -q` → FAIL (404).

- [ ] **Step 3: Implement** — in `backend/routes_jobs.py`, add imports and the route:
```python
from backend.rbac import require_active, require_runner
from core.codenames import is_valid_codename, suggest_unused
```
```python
@router.get("/job-name/suggest")
def suggest_job_name(account=Depends(require_active), runs=Depends(run_repo)):
    return {"name": suggest_unused(runs.existing_ids())}
```

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py::test_suggest_job_name_returns_unused_valid -q` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add backend/routes_jobs.py tests/test_routes_jobs.py
git commit -m "feat(api): GET /api/job-name/suggest"
```

---

## Task 5: Submit uses the codename (validate, dedupe, reserve)

**Files:** Modify `backend/routes_jobs.py`; Test `tests/test_routes_jobs.py`.

- [ ] **Step 1: Fix existing submit tests + add new ones** — in `tests/test_routes_jobs.py`, add `"job_name": "<unique>"` to every existing `POST /api/jobs` payload (e.g. `test_submit_single` → `"job_name": "phoenix"`, `test_submit_multi` → `"job_name": "otter"`, etc.; use a distinct codename per test). Then add:
```python
def test_submit_uses_codename_as_id_and_folder(client, valid_case, mem_runs):
    r = client.post("/api/jobs", json={
        "case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8", "job_name": "phoenix"})
    assert r.status_code == 200
    assert r.json()["batch_job_id"] == "phoenix"
    rec = mem_runs.get("phoenix")
    assert rec is not None and rec.job_name == "phoenix"


def test_submit_rejects_invalid_job_name(client, valid_case):
    r = client.post("/api/jobs", json={
        "case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8", "job_name": "Bad Name!"})
    assert r.status_code == 400


def test_submit_rejects_taken_job_name(client, valid_case, mem_runs):
    body = {"case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8", "job_name": "phoenix"}
    assert client.post("/api/jobs", json=body).status_code == 200
    assert client.post("/api/jobs", json=body).status_code == 400  # taken


def test_submit_dedupes_case_ids(client, valid_case, mem_runs):
    r = client.post("/api/jobs", json={
        "case_ids": ["case_0006", "case_0006"], "machine_type": "c2d-highcpu-8",
        "job_name": "otter"})
    assert r.status_code == 200
    assert mem_runs.get("otter").case_ids == ["case_0006"]
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py -q` → FAIL (codename not used as id; invalid/taken not rejected).

- [ ] **Step 3: Implement** — in `backend/routes_jobs.py`, rewrite the body of `submit`. Remove the `build_job_name` import and the `timestamp`/`build_job_name` lines. New flow (replace from after the machine lookup through the return):
```python
    job_name = req.job_name.strip().lower()
    if not is_valid_codename(job_name):
        raise HTTPException(status_code=400, detail="invalid job name (use a short slug like 'phoenix')")

    # dedupe case ids, preserving order
    case_ids = list(dict.fromkeys(canonical_case_id(c) for c in req.case_ids))

    errors = {}
    for case_id in case_ids:
        result = validate_case(store, case_id)
        if not result.ok:
            errors[case_id] = result.errors
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    provisioning_model = "SPOT" if req.spot else "STANDARD"
    common = {
        "cpu_milli": machine["cpu_milli"], "memory_mib": machine["memory_mib"],
        "mpi_ranks": machine["default_mpi_ranks"], "provisioning_model": provisioning_model,
        "local_ssd_count": machine["local_ssd_count"],
    }

    record = RunRecord(
        batch_job_id=job_name, job_name=job_name, submitted_by=user.email,
        submitted_at=datetime.datetime.now(datetime.timezone.utc), region=Settings().region,
        machine_type=req.machine_type, mpi_ranks=machine["default_mpi_ranks"], spot=req.spot,
        case_ids=case_ids, case_names=records.names_for(case_ids),
    )
    if not runs.try_reserve(record):
        raise HTTPException(status_code=400, detail="job name already used; pick another")

    if len(case_ids) == 1:
        spec = b.build_single(case_id=case_ids[0], machine_type=req.machine_type,
                              job_name=job_name, **common)
    else:
        spec = b.build_multi(case_ids=case_ids, machine_type=req.machine_type,
                             job_name=job_name, **common)
    name = sub.submit(job_name, spec)
    return {"job_name": job_name, "batch_job_id": job_name, "name": name, "submitted_by": user.email}
```
(Reservation creates the `of_runs` doc before submit; if the Batch submit later fails, reconcile will resolve that doc to CANCELLED — acceptable.) Remove the now-unused `build_job_name` import; keep `canonical_case_id`.

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py -q` → PASS (all, including fixed payloads).

- [ ] **Step 5: Remove the dead helper** — in `core/naming.py`, delete `build_job_name` (no longer referenced; `cli` is updated in Task 6). Run `grep -rn build_job_name phase3-run-app` and confirm only `cli/main.py` remains (fixed next task) — if so, proceed.

- [ ] **Step 6: Commit**:
```bash
git add backend/routes_jobs.py core/naming.py tests/test_routes_jobs.py
git commit -m "feat(jobs): codename job names (validate, dedupe, atomic reserve)"
```

---

## Task 6: CLI `--job-name`

**Files:** Modify `cli/main.py`; Test `tests/test_cli.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_cli.py` a test that invoking `run` without `--job-name` still produces a valid codename and one with `--job-name foo` uses `foo`. Mirror the existing CLI test style (Click `CliRunner`, fakes for storage/submitter). Assert the submitted job name passed to the fake submitter is a valid codename (and equals `foo` when provided).

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_cli.py -q` → FAIL.

- [ ] **Step 3: Implement** — in `cli/main.py` `run`:
  - add option `@click.option("--job-name", default=None, help="one-word codename (auto if omitted)")`.
  - after computing `ids`, compute the codename:
```python
    from core.codenames import is_valid_codename, suggest_unused
    job_name = (job_name or suggest_unused(set())).strip().lower()
    if not is_valid_codename(job_name):
        click.echo(f"invalid --job-name {job_name!r}", err=True); raise SystemExit(2)
```
  - replace the `build_job_name(...)` calls with `job_name`; drop the `build_job_name` import and the `_now_ts()` name usage for the job id (timestamps no longer name the job).

> CLI uniqueness: the CLI is a thin local tool; `suggest_unused(set())` just picks any word. The authoritative reservation is the API path. (CLI submit does not write `of_runs`, consistent with today.)

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_cli.py -q` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add cli/main.py tests/test_cli.py
git commit -m "feat(cli): --job-name codename (auto if omitted)"
```

---

## Task 7: Runtime RESULT_PREFIX new layout

**Files:** Modify `runtime/run_case_in_batch.sh`; Test `runtime/tests/run_case_in_batch_test.sh`. Run: `bash phase3-run-app/runtime/tests/run_all.sh`.

- [ ] **Step 1: Write the failing test** — in `runtime/tests/run_case_in_batch_test.sh`, add a check that the results upload targets the new path. Following the file's existing stub/assert style, assert the `gcloud storage cp ... result.tar.gz` destination matches `gs://tb/results/singlecase/<JOB_NAME>/<CASE_ID>/result.tar.gz` (single-case run) and contains **no** `/task_` and **no** machine segment.

- [ ] **Step 2: Run → fail**: `bash phase3-run-app/runtime/tests/run_all.sh` → the new assertion FAILS (still old path).

- [ ] **Step 3: Implement** — in `runtime/run_case_in_batch.sh`, replace the results-path lines. Change:
```bash
TASK_INDEX="${BATCH_TASK_INDEX:-0}"
RESULT_PREFIX="gs://${BUCKET}/results/${CASE_ID}/${VARIANT_ID}/${JOB_NAME}/task_${TASK_INDEX}"
```
to:
```bash
RESULT_MODE=$([[ -n "${CASE_ID_LIST:-}" ]] && echo multicase || echo singlecase)
RESULT_PREFIX="gs://${BUCKET}/results/${RESULT_MODE}/${JOB_NAME}/${CASE_ID}"
```
Leave `CHECKPOINT_PREFIX` (uses `VARIANT_ID`) unchanged. `VARIANT_ID` is still required for checkpoints, so keep its `: "${VARIANT_ID:?...}"` guard.

- [ ] **Step 4: Run → pass**: `bash phase3-run-app/runtime/tests/run_all.sh` → all pass.

- [ ] **Step 5: Commit**:
```bash
git add runtime/run_case_in_batch.sh runtime/tests/run_case_in_batch_test.sh
git commit -m "feat(runtime): results/{singlecase|multicase}/<job>/<case> layout"
```

---

## Task 8: Frontend API client

**Files:** Modify `frontend/src/lib/api.ts`; Test `frontend/src/tests/api.test.ts`. Run: `cd frontend && npx vitest run`.

- [ ] **Step 1: Write the failing test** — append to `frontend/src/tests/api.test.ts` (adapt to the file's `ApiClient` construction + fetch-mock style):
```ts
it("submit sends job_name; suggestJobName GETs the suggest endpoint", async () => {
  const calls: any[] = [];
  globalThis.fetch = vi.fn(async (url: any, init: any) => {
    calls.push({ url: String(url), method: init?.method, body: init?.body });
    return new Response(JSON.stringify({ name: "phoenix", job_name: "phoenix" }), { status: 200 });
  }) as any;
  const { ApiClient } = await import("../lib/api");
  const api = new ApiClient("", "tok", globalThis.fetch as any);   // match real constructor
  await api.suggestJobName();
  await api.submit(["case_0006"], "c2d-highcpu-8", false, "phoenix");
  const suggest = calls.find((c) => c.url.includes("/api/job-name/suggest"));
  const submit = calls.find((c) => c.url.endsWith("/api/jobs") && c.method === "POST");
  expect(suggest.method).toBe("GET");
  expect(JSON.parse(submit.body).job_name).toBe("phoenix");
});
```

- [ ] **Step 2: Run → fail**: `cd frontend && npx vitest run src/tests/api.test.ts` → FAIL.

- [ ] **Step 3: Implement** — in `frontend/src/lib/api.ts`, update `submit` and add `suggestJobName`:
```ts
  submit(case_ids: string[], machine_type: string, spot: boolean, job_name: string) {
    return this.req("POST", "/api/jobs", { case_ids, machine_type, spot, job_name });
  }
  suggestJobName() {
    return this.req("GET", "/api/job-name/suggest");
  }
```

- [ ] **Step 4: Run → pass**: `cd frontend && npx vitest run` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add frontend/src/lib/api.ts frontend/src/tests/api.test.ts
git commit -m "feat(frontend): api submit job_name + suggestJobName"
```

---

## Task 9: Frontend Run view — codename field

**Files:** Modify `frontend/src/views/RunView.tsx`.

- [ ] **Step 1: Implement** — add a required **Job name** field to `RunView`:
  - `const [jobName, setJobName] = useState("");`
  - On mount, `useEffect(() => { api.suggestJobName().then((r) => setJobName(r.name)).catch(() => {}); }, []);`
  - Render a text input bound to `jobName` + a **shuffle** button that re-calls `api.suggestJobName()` and sets it.
  - Validity: `const validName = /^[a-z][a-z0-9-]{1,38}$/.test(jobName);` show a hint when invalid.
  - Gate submit: `const canSubmit = caseIds.length > 0 && validName && role !== "viewer";` (keep the existing viewer/role gate).
  - Pass it through: `await api.submit(caseIds, machine, spot, jobName);`
  Match the existing `RunView` styling (presets/inputs) and keep the role-based disable from Feature C.

- [ ] **Step 2: Verify**: `cd frontend && npx vitest run && npm run build` → both pass.

- [ ] **Step 3: Commit**:
```bash
git add frontend/src/views/RunView.tsx
git commit -m "feat(frontend): required one-word job codename field + shuffle"
```

---

## Task 10: Bump runtime image pin

**Files:** Modify `.github/workflows/deploy.yml`.

- [ ] **Step 1: Implement** — in `.github/workflows/deploy.yml`, bump the runtime image pin:
```yaml
  RUNTIME_IMAGE: us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.3
```
(from `:12.0.2`). This must point at the image rebuilt in the rollout step below.

- [ ] **Step 2: Validate YAML**: `phase3-run-app/.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('yaml ok')"` → `yaml ok`.

- [ ] **Step 3: Commit**:
```bash
git add .github/workflows/deploy.yml
git commit -m "ci: pin runtime image openfoam:12.0.3 (new results layout)"
```

---

## Final verification + rollout

- [ ] Python (ADC disabled, mirrors CI): `env -u GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_CONFIG=/tmp/empty-gcloud OF_DEV_NO_IAP=1 .venv/bin/pytest -q` — all green.
- [ ] Runtime: `bash phase3-run-app/runtime/tests/run_all.sh` — green.
- [ ] Frontend: `cd frontend && npx vitest run && npm run build` — green.
- [ ] **Rollout (manual, billable):** rebuild the runtime image with the new `RESULT_PREFIX`, linux/amd64, and push it as `openfoam:12.0.3`:
  ```bash
  docker buildx build --platform linux/amd64 \
    -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.3 \
    -f phase3-run-app/runtime/Dockerfile --push phase3-run-app/runtime
  ```
  Then merge to `main`; CI builds/deploys the backend with `OF_IMAGE_URI=...:12.0.3`.
- [ ] **Verify live:** submit a job with codename (e.g. `phoenix`) on `c2d-highcpu-8` Standard; confirm results land at `gs://cfd-lemnisca-cases/results/singlecase/phoenix/case_0006/` (no `task_`/machine), and the Runs tab shows the codename.
