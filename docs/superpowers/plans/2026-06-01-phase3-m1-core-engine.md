# Phase 3 — M1: Core Engine + Runtime Fixes + CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Executor:** Each task is handed to `codex exec "<task>"` from a separate terminal by the orchestrator, who reviews `git diff` + tests between tasks. Every task is self-contained — assume fresh context per task.

**Goal:** Build the pure `core/` Python engine and a thin CLI that replace the bash submit/upload logic, fixing all 8 known flaws, and fix the Batch runtime script (`run_case_in_batch.sh`) — so the terminal workflow works correctly before any web app exists.

**Architecture:** A pure-logic Python package (`phase3-run-app/core/`) with GCS/Batch access behind small `Protocol` interfaces (real impls + in-memory fakes for tests). A thin CLI (`phase3-run-app/cli/`) wires the engine to the terminal. The Batch VM script (`openfoam-batch/runtime/run_case_in_batch.sh`) is fixed: file-tree download, correct checkpoint rsync, no preemption trap, no `maxRunDuration`.

**Tech Stack:** Python 3.11+, `pytest`, `google-cloud-storage`, `google-cloud-batch`, `click` (CLI), bash + existing test harness (`openfoam-batch/tests/lib`).

**Reference spec:** `docs/superpowers/specs/2026-06-01-phase3-run-app-design.md`

---

## File Structure

```
phase3-run-app/
  pyproject.toml                 # package + deps + pytest config
  core/
    __init__.py
    config.py                    # Settings, MACHINE_CATALOG, disk defaults
    naming.py                    # canonical_case_id, sanitize_job_part, variant_for_machine, build_job_name
    storage.py                   # StorageClient Protocol, GcsStorage (real), InMemoryStorage (fake)
    cases.py                     # CaseRepository: allocate_ids (atomic), list_cases, exists
    validation.py                # validate_case (replaces check_case_prefix.sh)
    disks.py                     # build_disk_block (local-ssd default + overrides)
    batch_jobs.py                # BatchJobBuilder.build_single/build_multi, BatchSubmitter
    machines.py                  # MachineCatalog, Recommender (stub)
  cli/
    __init__.py
    main.py                      # `of` CLI: upload, run, validate, list
  tests/
    __init__.py
    test_naming.py
    test_storage_fake.py
    test_cases.py
    test_validation.py
    test_disks.py
    test_batch_jobs.py
    test_machines.py
openfoam-batch/
  runtime/run_case_in_batch.sh   # fixed (moved from scripts/admin/)
  tests/run_case_in_batch_test.sh # updated to new behavior
```

Conventions:
- All object paths are **relative to the bucket** (e.g. `cases/case_0042/READY`). The storage impl knows the bucket.
- Case IDs are zero-padded 4-digit: `case_0042`.
- All functions that need "now" take a `ts: str` parameter (testability) — no hidden clock in core.

---

### Task 1: Scaffold the Python package

**Files:**
- Create: `phase3-run-app/pyproject.toml`
- Create: `phase3-run-app/core/__init__.py` (empty)
- Create: `phase3-run-app/cli/__init__.py` (empty)
- Create: `phase3-run-app/tests/__init__.py` (empty)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "of-batch-core"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "google-cloud-storage>=2.16",
  "google-cloud-batch>=0.17",
  "click>=8.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
of = "cli.main:cli"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[tool.setuptools.packages.find]
where = ["."]
include = ["core*", "cli*"]
```

- [ ] **Step 2: Create the three empty `__init__.py` files**

```bash
mkdir -p phase3-run-app/core phase3-run-app/cli phase3-run-app/tests
touch phase3-run-app/core/__init__.py phase3-run-app/cli/__init__.py phase3-run-app/tests/__init__.py
```

- [ ] **Step 3: Create venv and install (dev)**

Run (from `phase3-run-app/`):
```bash
cd phase3-run-app && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```
Expected: installs without error; `pytest` available.

- [ ] **Step 4: Commit**

```bash
git add phase3-run-app/pyproject.toml phase3-run-app/core/__init__.py phase3-run-app/cli/__init__.py phase3-run-app/tests/__init__.py
git commit -m "chore(phase3): scaffold core engine python package"
```

---

### Task 2: `naming.py` — pure ID/variant/job-name helpers

**Files:**
- Create: `phase3-run-app/core/naming.py`
- Test: `phase3-run-app/tests/test_naming.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_naming.py
from core.naming import canonical_case_id, sanitize_job_part, variant_for_machine, build_job_name

def test_numeric_id_zero_padded():
    assert canonical_case_id("42") == "case_0042"

def test_already_canonical_passthrough():
    assert canonical_case_id("case_0042") == "case_0042"

def test_sanitize_lowercases_and_dashes():
    assert sanitize_job_part("C2D-Highcpu_56") == "c2d-highcpu-56"

def test_variant_is_machine_type():
    assert variant_for_machine("c2d-highcpu-56") == "c2d-highcpu-56"

def test_build_job_name_single():
    assert build_job_name("case_0042", "c2d-highcpu-56", "20260601120000") \
        == "of-case-0042-c2d-highcpu-56-20260601120000"

def test_build_job_name_multi():
    assert build_job_name(None, "c2d-highcpu-32", "20260601120000", multi=True) \
        == "of-multi-c2d-highcpu-32-20260601120000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.naming'`

- [ ] **Step 3: Implement `naming.py`**

```python
# core/naming.py
import re

def canonical_case_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return f"case_{int(value):04d}"
    return value

def sanitize_job_part(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value

def variant_for_machine(machine_type: str) -> str:
    return sanitize_job_part(machine_type)

def build_job_name(case_id: str | None, machine_type: str, ts: str, multi: bool = False) -> str:
    machine = sanitize_job_part(machine_type)
    if multi:
        return f"of-multi-{machine}-{ts}"
    return f"of-{sanitize_job_part(case_id)}-{machine}-{ts}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_naming.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/naming.py phase3-run-app/tests/test_naming.py
git commit -m "feat(core): naming helpers (variant=machine, job names)"
```

---

### Task 3: `storage.py` — StorageClient interface + in-memory fake

**Files:**
- Create: `phase3-run-app/core/storage.py`
- Test: `phase3-run-app/tests/test_storage_fake.py`

This defines the seam that makes `core` testable. `create_exclusive` is the atomic primitive that fixes the `case_0001` race (real impl uses `if_generation_match=0`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_storage_fake.py
from core.storage import InMemoryStorage

def test_create_exclusive_first_wins():
    s = InMemoryStorage()
    assert s.create_exclusive("cases/case_0001/.reserved", b"") is True
    assert s.create_exclusive("cases/case_0001/.reserved", b"") is False  # already exists

def test_object_exists():
    s = InMemoryStorage()
    s.upload_bytes("cases/case_0001/READY", b"x")
    assert s.object_exists("cases/case_0001/READY") is True
    assert s.object_exists("cases/case_0099/READY") is False

def test_list_case_ids_from_prefixes():
    s = InMemoryStorage()
    s.upload_bytes("cases/case_0001/READY", b"")
    s.upload_bytes("cases/case_0003/case/system/controlDict", b"")
    s.upload_bytes("results/case_0002/x", b"")  # not a case prefix
    assert sorted(s.list_case_ids()) == ["case_0001", "case_0003"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage_fake.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `storage.py`**

```python
# core/storage.py
from typing import Protocol

class StorageClient(Protocol):
    def object_exists(self, path: str) -> bool: ...
    def create_exclusive(self, path: str, data: bytes) -> bool:
        """Create object only if it does not exist. True if created, False if it already existed."""
        ...
    def upload_bytes(self, path: str, data: bytes) -> None: ...
    def read_text(self, path: str) -> str: ...
    def list_case_ids(self) -> list[str]:
        """Return every case id that has any object under cases/<id>/."""
        ...

class InMemoryStorage:
    """Test fake. Stores objects in a dict keyed by path."""
    def __init__(self) -> None:
        self._objs: dict[str, bytes] = {}

    def object_exists(self, path: str) -> bool:
        return path in self._objs

    def create_exclusive(self, path: str, data: bytes) -> bool:
        if path in self._objs:
            return False
        self._objs[path] = data
        return True

    def upload_bytes(self, path: str, data: bytes) -> None:
        self._objs[path] = data

    def read_text(self, path: str) -> str:
        return self._objs[path].decode("utf-8")

    def list_case_ids(self) -> list[str]:
        ids = set()
        for path in self._objs:
            if path.startswith("cases/"):
                parts = path.split("/")
                if len(parts) >= 3 and parts[1]:
                    ids.add(parts[1])
        return sorted(ids)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage_fake.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/storage.py phase3-run-app/tests/test_storage_fake.py
git commit -m "feat(core): StorageClient protocol + in-memory fake"
```

---

### Task 4: `cases.py` — atomic case-ID allocator (fixes flaw #5)

**Files:**
- Create: `phase3-run-app/core/cases.py`
- Test: `phase3-run-app/tests/test_cases.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cases.py
from core.storage import InMemoryStorage
from core.cases import CaseRepository

def test_allocate_from_empty_starts_at_one():
    repo = CaseRepository(InMemoryStorage())
    assert repo.allocate_ids(1) == ["case_0001"]

def test_allocate_continues_after_existing_max():
    s = InMemoryStorage()
    for n in range(1, 31):  # case_0001..case_0030 exist
        s.upload_bytes(f"cases/case_{n:04d}/READY", b"")
    repo = CaseRepository(s)
    assert repo.allocate_ids(3) == ["case_0031", "case_0032", "case_0033"]

def test_allocate_skips_reserved_but_not_ready_ids():
    # a half-allocated id with only a .reserved marker must NOT be reused
    s = InMemoryStorage()
    s.create_exclusive("cases/case_0001/.reserved", b"")
    repo = CaseRepository(s)
    assert repo.allocate_ids(1) == ["case_0002"]

def test_allocate_50_is_contiguous_and_unique():
    repo = CaseRepository(InMemoryStorage())
    ids = repo.allocate_ids(50)
    assert len(set(ids)) == 50
    assert ids[0] == "case_0001" and ids[-1] == "case_0050"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cases.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `cases.py`**

```python
# core/cases.py
import re
from dataclasses import dataclass
from core.storage import StorageClient

_CASE_RE = re.compile(r"^case_(\d+)$")

@dataclass
class CaseInfo:
    case_id: str
    ready: bool

class CaseRepository:
    def __init__(self, storage: StorageClient) -> None:
        self._s = storage

    def _max_existing(self) -> int:
        max_n = 0
        for cid in self._s.list_case_ids():
            m = _CASE_RE.match(cid)
            if m:
                max_n = max(max_n, int(m.group(1)))
        return max_n

    def allocate_ids(self, count: int) -> list[str]:
        """Atomically reserve `count` fresh case ids. Robust to empty buckets and
        concurrent allocators: each id is claimed via a create-only marker, and a
        claim that loses the race simply advances to the next number."""
        n = self._max_existing()
        out: list[str] = []
        while len(out) < count:
            n += 1
            cid = f"case_{n:04d}"
            if self._s.create_exclusive(f"cases/{cid}/.reserved", b""):
                out.append(cid)
        return out

    def exists(self, case_id: str) -> bool:
        return self._s.object_exists(f"cases/{case_id}/READY") or \
               self._s.object_exists(f"cases/{case_id}/.reserved")

    def list_cases(self) -> list[CaseInfo]:
        out = []
        for cid in self._s.list_case_ids():
            out.append(CaseInfo(case_id=cid, ready=self._s.object_exists(f"cases/{cid}/READY")))
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cases.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/cases.py phase3-run-app/tests/test_cases.py
git commit -m "feat(core): atomic case-id allocator (fixes case_0001 reuse + race)"
```

---

### Task 5: `validation.py` — case validation (replaces check_case_prefix.sh)

**Files:**
- Create: `phase3-run-app/core/validation.py`
- Test: `phase3-run-app/tests/test_validation.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validation.py
from core.storage import InMemoryStorage
from core.validation import validate_case

def _seed_valid(s):
    s.upload_bytes("cases/case_0001/case/system/controlDict", b"x")
    s.upload_bytes("cases/case_0001/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")
    s.upload_bytes("cases/case_0001/manifest.json", b'{"case_id":"case_0001"}')
    s.upload_bytes("cases/case_0001/READY", b"2026-06-01")

def test_valid_case_passes():
    s = InMemoryStorage(); _seed_valid(s)
    result = validate_case(s, "case_0001")
    assert result.ok is True and result.errors == []

def test_missing_ready_fails():
    s = InMemoryStorage(); _seed_valid(s)
    s._objs.pop("cases/case_0001/READY")
    result = validate_case(s, "case_0001")
    assert result.ok is False
    assert any("READY" in e for e in result.errors)

def test_command_without_mpi_ranks_warns():
    s = InMemoryStorage(); _seed_valid(s)
    s.upload_bytes("cases/case_0001/command.sh", b"mpirun -np 8 foamRun -parallel")
    result = validate_case(s, "case_0001")
    assert result.ok is True
    assert any("MPI_RANKS" in w for w in result.warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `validation.py`**

```python
# core/validation.py
from dataclasses import dataclass, field
from core.storage import StorageClient

@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

# objects that must exist under cases/<id>/
_REQUIRED = ["command.sh", "manifest.json", "READY"]

def validate_case(storage: StorageClient, case_id: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    base = f"cases/{case_id}"

    for name in _REQUIRED:
        if not storage.object_exists(f"{base}/{name}"):
            errors.append(f"missing required object: {name}")

    # at least one file under the case/ tree
    if not any(p.startswith(f"{base}/case/") for p in _all_paths(storage)):
        errors.append("missing case/ tree (no case files uploaded)")

    if storage.object_exists(f"{base}/command.sh"):
        cmd = storage.read_text(f"{base}/command.sh")
        if "MPI_RANKS" not in cmd:
            warnings.append("command.sh does not reference MPI_RANKS (hardcoded -np?)")

    return ValidationResult(ok=(len(errors) == 0), errors=errors, warnings=warnings)

def _all_paths(storage: StorageClient) -> list[str]:
    # InMemoryStorage exposes _objs; GcsStorage implements list_paths(prefix)
    if hasattr(storage, "_objs"):
        return list(storage._objs.keys())  # type: ignore[attr-defined]
    return storage.list_paths("cases/")  # type: ignore[attr-defined]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_validation.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/validation.py phase3-run-app/tests/test_validation.py
git commit -m "feat(core): case validation (replaces check_case_prefix.sh)"
```

---

### Task 6: `disks.py` — disk block builder (fixes flaw #4)

**Files:**
- Create: `phase3-run-app/core/disks.py`
- Test: `phase3-run-app/tests/test_disks.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_disks.py
from core.disks import build_disk_spec

def test_default_is_one_local_ssd():
    spec = build_disk_spec()  # defaults
    assert spec["disks"][0]["newDisk"]["type"] == "local-ssd"
    assert spec["disks"][0]["newDisk"]["sizeGb"] == 375
    assert len(spec["disks"]) == 1
    assert spec["volumes"][0]["mountPath"] == "/mnt/disks/openfoam-scratch"

def test_multiple_local_ssds():
    spec = build_disk_spec(local_ssd_count=3)
    assert len(spec["disks"]) == 3
    assert all(d["newDisk"]["type"] == "local-ssd" for d in spec["disks"])

def test_pd_ssd_override():
    spec = build_disk_spec(local_ssd_count=0, scratch_disk_type="pd-ssd", scratch_disk_gb=500)
    assert len(spec["disks"]) == 1
    assert spec["disks"][0]["newDisk"]["type"] == "pd-ssd"
    assert spec["disks"][0]["newDisk"]["sizeGb"] == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_disks.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `disks.py`**

```python
# core/disks.py
MOUNT_PATH = "/mnt/disks/openfoam-scratch"
_DEVICE = "openfoam-scratch"

def build_disk_spec(local_ssd_count: int = 1, scratch_disk_type: str = "pd-ssd",
                    scratch_disk_gb: int = 200) -> dict:
    """Returns {'disks': [...], 'volumes': [...]} for a Batch instance policy + task spec.
    Default: one 375GB local SSD. Override: N local SSDs, or a sized persistent disk."""
    disks = []
    if local_ssd_count > 0:
        for i in range(1, local_ssd_count + 1):
            disks.append({
                "newDisk": {"type": "local-ssd", "sizeGb": 375},
                "deviceName": f"{_DEVICE}-{i}",
            })
    else:
        disks.append({
            "newDisk": {"type": scratch_disk_type, "sizeGb": scratch_disk_gb},
            "deviceName": f"{_DEVICE}-1",
        })
    volumes = [{
        "deviceName": f"{_DEVICE}-1",
        "mountPath": MOUNT_PATH,
        "mountOptions": "rw,async",
    }]
    return {"disks": disks, "volumes": volumes}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_disks.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/disks.py phase3-run-app/tests/test_disks.py
git commit -m "feat(core): disk spec builder (local-ssd default + overrides)"
```

---

### Task 7: `config.py` — Settings + machine catalog

**Files:**
- Create: `phase3-run-app/core/config.py`
- Test: `phase3-run-app/tests/test_machines.py` (catalog tested with machines in Task 8; here just a smoke test inline)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from core.config import Settings, MACHINE_CATALOG

def test_settings_defaults():
    s = Settings()
    assert s.bucket == "of-cases"
    assert s.region == "us-central1"
    assert s.image_uri.startswith("openfoam:12")

def test_machine_catalog_is_all_c2d_highcpu():
    names = [m["name"] for m in MACHINE_CATALOG]
    assert names == ["c2d-highcpu-2","c2d-highcpu-4","c2d-highcpu-8",
                     "c2d-highcpu-16","c2d-highcpu-32","c2d-highcpu-56","c2d-highcpu-112"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `config.py`**

```python
# core/config.py
import os
from dataclasses import dataclass

# vCPU -> (cpu_milli, memory_mib). c2d-highcpu is 2GB/vCPU.
_C2D_HIGHCPU_VCPUS = [2, 4, 8, 16, 32, 56, 112]

MACHINE_CATALOG = [
    {
        "name": f"c2d-highcpu-{v}",
        "vcpus": v,
        "cpu_milli": v * 1000,
        "memory_mib": v * 2048,
        "default_mpi_ranks": max(1, v // 2),
    }
    for v in _C2D_HIGHCPU_VCPUS
]

@dataclass
class Settings:
    project_id: str = os.environ.get("OF_PROJECT_ID", "project-688a4c78-5d5b-45b3-b5d")
    region: str = os.environ.get("OF_REGION", "us-central1")
    bucket: str = os.environ.get("OF_BUCKET", "of-cases")
    image_uri: str = os.environ.get("OF_IMAGE_URI", "openfoam:12.0.0")
    scratch_root: str = "/mnt/disks/openfoam-scratch"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/config.py phase3-run-app/tests/test_config.py
git commit -m "feat(core): Settings + c2d-highcpu machine catalog"
```

---

### Task 8: `machines.py` — catalog lookup + recommender stub

**Files:**
- Create: `phase3-run-app/core/machines.py`
- Test: `phase3-run-app/tests/test_machines.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_machines.py
from core.machines import MachineCatalog, Recommender

def test_lookup_returns_specs():
    m = MachineCatalog().get("c2d-highcpu-56")
    assert m["vcpus"] == 56 and m["cpu_milli"] == 56000 and m["memory_mib"] == 114688

def test_unknown_machine_raises():
    import pytest
    with pytest.raises(KeyError):
        MachineCatalog().get("n2-standard-4")

def test_recommender_returns_none_without_metrics():
    # metadata file (cells/size/volume) is delegated to Agent O; degrade gracefully
    assert Recommender().suggest(prior_runs=[]) is None

def test_recommender_picks_machine_of_largest_prior_run():
    prior = [{"machine_type": "c2d-highcpu-16"}, {"machine_type": "c2d-highcpu-56"}]
    assert Recommender().suggest(prior_runs=prior) == "c2d-highcpu-56"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_machines.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `machines.py`**

```python
# core/machines.py
from core.config import MACHINE_CATALOG

class MachineCatalog:
    def __init__(self) -> None:
        self._by_name = {m["name"]: m for m in MACHINE_CATALOG}

    def all(self) -> list[dict]:
        return list(MACHINE_CATALOG)

    def get(self, name: str) -> dict:
        return self._by_name[name]  # raises KeyError if unknown

class Recommender:
    """v1 stub. Until Agent O emits cells/size/volume metadata, suggest the largest
    machine used by prior runs of this case; None if no history."""
    def __init__(self) -> None:
        self._cat = MachineCatalog()

    def suggest(self, prior_runs: list[dict]) -> str | None:
        machines = [r["machine_type"] for r in prior_runs if r.get("machine_type") in self._cat._by_name]
        if not machines:
            return None
        return max(machines, key=lambda n: self._cat.get(n)["vcpus"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_machines.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/machines.py phase3-run-app/tests/test_machines.py
git commit -m "feat(core): machine catalog lookup + recommender stub"
```

---

### Task 9: `batch_jobs.py` — single-task spec builder (fixes #1, #3, #8)

**Files:**
- Create: `phase3-run-app/core/batch_jobs.py`
- Test: `phase3-run-app/tests/test_batch_jobs.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_batch_jobs.py
from core.batch_jobs import BatchJobBuilder

def _build_single():
    return BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_single(
        case_id="case_0042", machine_type="c2d-highcpu-56",
        cpu_milli=56000, memory_mib=114688, mpi_ranks=28,
        job_name="of-case-0042-c2d-highcpu-56-20260601120000",
    )

def test_single_has_no_max_run_duration():
    spec = _build_single()
    assert "maxRunDuration" not in spec["taskGroups"][0]["taskSpec"]  # flaw #1

def test_single_taskcount_and_parallelism_are_one():
    tg = _build_single()["taskGroups"][0]
    assert tg["taskCount"] == 1 and tg["parallelism"] == 1

def test_variant_env_is_machine_type():
    env = _build_single()["taskGroups"][0]["taskSpec"]["environment"]["variables"]
    assert env["VARIANT_ID"] == "c2d-highcpu-56"  # flaw #3
    assert env["CASE_ID"] == "case_0042"
    assert env["BUCKET"] == "of-cases"

def test_default_provisioning_is_standard():
    pol = _build_single()["allocationPolicy"]["instances"][0]["policy"]
    assert pol["provisioningModel"] == "STANDARD"  # flaw #8 (Spot is opt-in)
    assert pol["machineType"] == "c2d-highcpu-56"

def test_spot_toggle():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_single(
        case_id="case_0042", machine_type="c2d-highcpu-56", cpu_milli=56000,
        memory_mib=114688, mpi_ranks=28, job_name="j", provisioning_model="SPOT")
    assert spec["allocationPolicy"]["instances"][0]["policy"]["provisioningModel"] == "SPOT"

def test_default_disk_is_local_ssd():
    pol = _build_single()["allocationPolicy"]["instances"][0]["policy"]
    assert pol["disks"][0]["newDisk"]["type"] == "local-ssd"

def test_image_tag_recorded():
    spec = _build_single()
    assert spec["taskGroups"][0]["taskSpec"]["runnables"][0]["container"]["imageUri"] == "openfoam:12.0.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_batch_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `batch_jobs.py` (single only for now)**

```python
# core/batch_jobs.py
from core.naming import variant_for_machine
from core.disks import build_disk_spec

class BatchJobBuilder:
    def __init__(self, bucket: str, image_uri: str) -> None:
        self._bucket = bucket
        self._image = image_uri

    def _task_spec(self, env: dict, cpu_milli: int, memory_mib: int,
                   volumes: list[dict], max_retry_count: int) -> dict:
        # NOTE: deliberately NO maxRunDuration (flaw #1 — jobs run until done or stopped).
        return {
            "runnables": [{
                "container": {
                    "imageUri": self._image,
                    "entrypoint": "/bin/bash",
                    "commands": ["-lc", "/opt/openfoam-batch/run_case_in_batch.sh"],
                }
            }],
            "environment": {"variables": env},
            "computeResource": {"cpuMilli": cpu_milli, "memoryMib": memory_mib},
            "maxRetryCount": max_retry_count,
            "volumes": volumes,
        }

    def _instance_policy(self, machine_type: str, provisioning_model: str, disks: list[dict]) -> dict:
        return {"policy": {
            "machineType": machine_type,
            "provisioningModel": provisioning_model,
            "disks": disks,
        }}

    def build_single(self, *, case_id: str, machine_type: str, cpu_milli: int,
                     memory_mib: int, mpi_ranks: int, job_name: str,
                     provisioning_model: str = "STANDARD", max_retry_count: int = 3,
                     local_ssd_count: int = 1, scratch_disk_type: str = "pd-ssd",
                     scratch_disk_gb: int = 200) -> dict:
        variant = variant_for_machine(machine_type)
        disk = build_disk_spec(local_ssd_count, scratch_disk_type, scratch_disk_gb)
        env = {
            "BUCKET": self._bucket,
            "CASE_ID": case_id,
            "VARIANT_ID": variant,
            "JOB_NAME": job_name,
            "CPU_MILLI": str(cpu_milli),
            "MPI_RANKS": str(mpi_ranks),
            "SCRATCH_ROOT": "/mnt/disks/openfoam-scratch",
        }
        task_spec = self._task_spec(env, cpu_milli, memory_mib, disk["volumes"], max_retry_count)
        return {
            "taskGroups": [{"taskCount": 1, "parallelism": 1, "taskSpec": task_spec}],
            "allocationPolicy": {"instances": [
                self._instance_policy(machine_type, provisioning_model, disk["disks"])]},
            "logsPolicy": {"destination": "CLOUD_LOGGING"},
            "labels": {"app": "openfoam"},
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_batch_jobs.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/batch_jobs.py phase3-run-app/tests/test_batch_jobs.py
git commit -m "feat(core): single-task Batch spec builder (no maxRunDuration, variant=machine, spot toggle)"
```

---

### Task 10: `batch_jobs.py` — multi-task builder (fixes #6)

**Files:**
- Modify: `phase3-run-app/core/batch_jobs.py`
- Test: `phase3-run-app/tests/test_batch_jobs.py` (add cases)

- [ ] **Step 1: Add failing tests**

```python
# append to tests/test_batch_jobs.py
def test_multi_taskcount_equals_parallelism_equals_case_count():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_multi(
        case_ids=["case_0001", "case_0002", "case_0003"], machine_type="c2d-highcpu-32",
        cpu_milli=32000, memory_mib=65536, mpi_ranks=16,
        job_name="of-multi-c2d-highcpu-32-20260601120000")
    tg = spec["taskGroups"][0]
    assert tg["taskCount"] == 3 and tg["parallelism"] == 3  # flaw #6

def test_multi_passes_case_id_list_and_omits_case_id():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_multi(
        case_ids=["case_0001", "case_0002"], machine_type="c2d-highcpu-32",
        cpu_milli=32000, memory_mib=65536, mpi_ranks=16, job_name="j")
    env = spec["taskGroups"][0]["taskSpec"]["environment"]["variables"]
    assert env["CASE_ID_LIST"] == "case_0001,case_0002"
    assert "CASE_ID" not in env
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_batch_jobs.py -k multi -v`
Expected: FAIL — `AttributeError: 'BatchJobBuilder' object has no attribute 'build_multi'`

- [ ] **Step 3: Add `build_multi` to `BatchJobBuilder`**

```python
# add method inside class BatchJobBuilder in core/batch_jobs.py
    def build_multi(self, *, case_ids: list[str], machine_type: str, cpu_milli: int,
                    memory_mib: int, mpi_ranks: int, job_name: str,
                    provisioning_model: str = "STANDARD", max_retry_count: int = 3,
                    local_ssd_count: int = 1, scratch_disk_type: str = "pd-ssd",
                    scratch_disk_gb: int = 200) -> dict:
        if not case_ids:
            raise ValueError("build_multi requires at least one case id")
        variant = variant_for_machine(machine_type)
        disk = build_disk_spec(local_ssd_count, scratch_disk_type, scratch_disk_gb)
        env = {
            "BUCKET": self._bucket,
            "CASE_ID_LIST": ",".join(case_ids),  # runtime resolves CASE_ID via BATCH_TASK_INDEX
            "VARIANT_ID": variant,
            "JOB_NAME": job_name,
            "CPU_MILLI": str(cpu_milli),
            "MPI_RANKS": str(mpi_ranks),
            "SCRATCH_ROOT": "/mnt/disks/openfoam-scratch",
        }
        n = len(case_ids)
        task_spec = self._task_spec(env, cpu_milli, memory_mib, disk["volumes"], max_retry_count)
        return {
            "taskGroups": [{"taskCount": n, "parallelism": n, "taskSpec": task_spec}],
            "allocationPolicy": {"instances": [
                self._instance_policy(machine_type, provisioning_model, disk["disks"])]},
            "logsPolicy": {"destination": "CLOUD_LOGGING"},
            "labels": {"app": "openfoam"},
        }
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_batch_jobs.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/batch_jobs.py phase3-run-app/tests/test_batch_jobs.py
git commit -m "feat(core): multi-task Batch spec builder (taskCount==parallelism)"
```

---

### Task 11: `GcsStorage` + `BatchSubmitter` (real GCP adapters)

**Files:**
- Modify: `phase3-run-app/core/storage.py` (add `GcsStorage`)
- Modify: `phase3-run-app/core/batch_jobs.py` (add `BatchSubmitter`)

These wrap the real SDKs; not unit-tested (no GCP in CI) — verified manually in Task 14's smoke run. Keep them thin.

- [ ] **Step 1: Add `GcsStorage` to `storage.py`**

```python
# append to core/storage.py
from google.cloud import storage as _gcs  # type: ignore

class GcsStorage:
    """Real StorageClient backed by google-cloud-storage. Paths are bucket-relative."""
    def __init__(self, bucket: str) -> None:
        self._bucket_name = bucket
        self._client = _gcs.Client()
        self._bucket = self._client.bucket(bucket)

    def object_exists(self, path: str) -> bool:
        return self._bucket.blob(path).exists(self._client)

    def create_exclusive(self, path: str, data: bytes) -> bool:
        blob = self._bucket.blob(path)
        try:
            blob.upload_from_string(data, if_generation_match=0)  # atomic create-only
            return True
        except Exception as e:  # google.api_core.exceptions.PreconditionFailed (412)
            if getattr(e, "code", None) == 412 or "PreconditionFailed" in type(e).__name__:
                return False
            raise

    def upload_bytes(self, path: str, data: bytes) -> None:
        self._bucket.blob(path).upload_from_string(data)

    def read_text(self, path: str) -> str:
        return self._bucket.blob(path).download_as_text()

    def list_paths(self, prefix: str) -> list[str]:
        return [b.name for b in self._client.list_blobs(self._bucket_name, prefix=prefix)]

    def list_case_ids(self) -> list[str]:
        ids = set()
        for name in self.list_paths("cases/"):
            parts = name.split("/")
            if len(parts) >= 3 and parts[1]:
                ids.add(parts[1])
        return sorted(ids)
```

- [ ] **Step 2: Add `BatchSubmitter` to `batch_jobs.py`**

```python
# append to core/batch_jobs.py
from google.cloud import batch_v1  # type: ignore
from google.protobuf import json_format  # type: ignore

class BatchSubmitter:
    """Submits a built spec dict via the Batch API."""
    def __init__(self, project_id: str, region: str) -> None:
        self._project = project_id
        self._region = region
        self._client = batch_v1.BatchServiceClient()

    def submit(self, job_name: str, spec: dict) -> str:
        job = json_format.ParseDict(spec, batch_v1.Job()._pb)
        parent = f"projects/{self._project}/locations/{self._region}"
        created = self._client.create_job(batch_v1.CreateJobRequest(
            parent=parent, job_id=job_name, job=batch_v1.Job.wrap(job)))
        return created.name
```

- [ ] **Step 3: Verify import (no GCP call)**

Run: `python -c "import core.storage, core.batch_jobs; print('ok')"`
Expected: prints `ok` (imports succeed; SDKs installed).

- [ ] **Step 4: Run full unit suite (must still pass)**

Run: `pytest -v`
Expected: PASS (all prior tests green; fakes untouched).

- [ ] **Step 5: Commit**

```bash
git add phase3-run-app/core/storage.py phase3-run-app/core/batch_jobs.py
git commit -m "feat(core): real GcsStorage + BatchSubmitter adapters"
```

---

### Task 12: CLI — `of validate` and `of list`

**Files:**
- Create: `phase3-run-app/cli/main.py`

- [ ] **Step 1: Implement the CLI skeleton with `validate` and `list`**

```python
# cli/main.py
import json
import click
from core.config import Settings
from core.storage import GcsStorage
from core.cases import CaseRepository
from core.validation import validate_case

@click.group()
@click.pass_context
def cli(ctx):
    ctx.obj = Settings()

@cli.command(name="list")
@click.pass_obj
def list_cases(settings: Settings):
    """List all cases in the bucket."""
    repo = CaseRepository(GcsStorage(settings.bucket))
    for c in repo.list_cases():
        click.echo(f"{c.case_id}\t{'READY' if c.ready else 'incomplete'}")

@cli.command()
@click.argument("case_id")
@click.pass_obj
def validate(settings: Settings, case_id: str):
    """Validate an uploaded case (replaces check_case_prefix.sh)."""
    result = validate_case(GcsStorage(settings.bucket), case_id)
    for e in result.errors:
        click.echo(f"FAIL: {e}", err=True)
    for w in result.warnings:
        click.echo(f"WARN: {w}", err=True)
    if not result.ok:
        raise SystemExit(1)
    click.echo(f"OK: {case_id}")
```

- [ ] **Step 2: Verify CLI loads**

Run: `cd phase3-run-app && of --help`
Expected: shows `list` and `validate` commands.

- [ ] **Step 3: Commit**

```bash
git add phase3-run-app/cli/main.py
git commit -m "feat(cli): of list + of validate"
```

---

### Task 13: CLI — `of upload` (file-tree rsync) and `of run`

**Files:**
- Modify: `phase3-run-app/cli/main.py`

- [ ] **Step 1: Add `upload` and `run` commands**

```python
# add to cli/main.py (imports at top)
import subprocess, datetime
from core.cases import CaseRepository
from core.batch_jobs import BatchJobBuilder, BatchSubmitter
from core.machines import MachineCatalog
from core.naming import canonical_case_id, build_job_name
from core.storage import GcsStorage

def _now_ts() -> str:
    return datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")

@cli.command()
@click.option("--case-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--command-sh", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--case-id", default="AUTO", help="explicit id or AUTO")
@click.option("--openfoam-version", default="12")
@click.pass_obj
def upload(settings: Settings, case_dir, command_sh, case_id, openfoam_version):
    """Upload a local case as a file tree (no tar)."""
    storage = GcsStorage(settings.bucket)
    repo = CaseRepository(storage)
    cid = repo.allocate_ids(1)[0] if case_id.upper() == "AUTO" else canonical_case_id(case_id)
    base = f"gs://{settings.bucket}/cases/{cid}"
    # rsync the case tree (no tarring)
    subprocess.run(["gcloud", "storage", "rsync", "--recursive", case_dir, f"{base}/case/"], check=True)
    subprocess.run(["gcloud", "storage", "cp", command_sh, f"{base}/command.sh"], check=True)
    manifest = json.dumps({
        "case_id": cid, "solver_family": "openfoam", "openfoam_version": openfoam_version,
        "uploaded_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
    })
    storage.upload_bytes(f"cases/{cid}/manifest.json", manifest.encode())
    storage.upload_bytes(f"cases/{cid}/READY", (datetime.datetime.utcnow().isoformat() + "Z").encode())
    click.echo(f"Uploaded {cid} to {base}")

@cli.command()
@click.option("--case", "cases", multiple=True, required=True, help="case id (repeatable)")
@click.option("--machine", required=True)
@click.option("--spot/--standard", default=False)
@click.pass_obj
def run(settings: Settings, cases, machine, spot):
    """Submit a single-task (1 case) or multi-task (N cases) Batch job."""
    spec_machine = MachineCatalog().get(machine)
    builder = BatchJobBuilder(bucket=settings.bucket, image_uri=settings.image_uri)
    submitter = BatchSubmitter(settings.project_id, settings.region)
    prov = "SPOT" if spot else "STANDARD"
    ts = _now_ts()
    ids = [canonical_case_id(c) for c in cases]
    common = dict(cpu_milli=spec_machine["cpu_milli"], memory_mib=spec_machine["memory_mib"],
                  mpi_ranks=spec_machine["default_mpi_ranks"], provisioning_model=prov)
    if len(ids) == 1:
        job_name = build_job_name(ids[0], machine, ts)
        spec = builder.build_single(case_id=ids[0], machine_type=machine, job_name=job_name, **common)
    else:
        job_name = build_job_name(None, machine, ts, multi=True)
        spec = builder.build_multi(case_ids=ids, machine_type=machine, job_name=job_name, **common)
    name = submitter.submit(job_name, spec)
    click.echo(f"Submitted {name}")
```

- [ ] **Step 2: Verify CLI loads**

Run: `cd phase3-run-app && of --help && of run --help`
Expected: shows `upload` and `run`; `run` shows `--case`, `--machine`, `--spot/--standard`.

- [ ] **Step 3: Run full unit suite**

Run: `cd phase3-run-app && pytest -v`
Expected: PASS (all green).

- [ ] **Step 4: Commit**

```bash
git add phase3-run-app/cli/main.py
git commit -m "feat(cli): of upload (tree rsync) + of run (single/multi, spot toggle)"
```

---

### Task 14: Fix the Batch runtime script `run_case_in_batch.sh` (fixes #8 + tree)

**Files:**
- Create: `openfoam-batch/runtime/run_case_in_batch.sh` (the fixed script)
- Delete: `openfoam-batch/scripts/admin/run_case_in_batch.sh`
- Reference current (buggy) version: `openfoam-batch/scripts/admin/run_case_in_batch.sh`

Changes vs current: (a) download the `case/` **tree** via rsync instead of `case.tar.gz`+untar; (b) drop `SHA256SUMS` handling; (c) **fix checkpoint rsync** — loop per `processor*` dir (no quoted-glob that `gcloud storage rsync` rejects); (d) **remove the preemption trap** (`preempted.json`, `exit 50001`) — replace with a minimal final-flush-on-TERM that still lets a manual stop resume; (e) results tar stays unchanged.

- [ ] **Step 1: Write the fixed script**

```bash
# openfoam-batch/runtime/run_case_in_batch.sh
#!/usr/bin/env bash
set -euo pipefail

canonical_case_id() {
  local value="$1"
  if [[ "${value}" =~ ^[0-9]+$ ]]; then printf 'case_%04d\n' "$((10#${value}))"; return; fi
  printf '%s\n' "${value}"
}

: "${BUCKET:?BUCKET is required}"
if [[ -n "${CASE_ID_LIST:-}" ]]; then
  IFS=',' read -ra _CASE_LIST <<< "${CASE_ID_LIST}"
  _IDX="${BATCH_TASK_INDEX:-0}"
  CASE_ID="$(canonical_case_id "${_CASE_LIST[${_IDX}]:-}")"
  [[ -n "${CASE_ID}" ]] || { echo "BATCH_TASK_INDEX=${_IDX} out of bounds" >&2; exit 64; }
fi
: "${CASE_ID:?CASE_ID is required}"
CASE_ID="$(canonical_case_id "${CASE_ID}")"
: "${VARIANT_ID:?VARIANT_ID is required}"
: "${JOB_NAME:?JOB_NAME is required}"
SCRATCH_ROOT="${SCRATCH_ROOT:-/mnt/disks/openfoam-scratch}"
[[ -d "${SCRATCH_ROOT}" ]] || { echo "SCRATCH_ROOT=${SCRATCH_ROOT} missing" >&2; exit 64; }

CASE_PREFIX="gs://${BUCKET}/cases/${CASE_ID}"
TASK_INDEX="${BATCH_TASK_INDEX:-0}"
RESULT_PREFIX="gs://${BUCKET}/results/${CASE_ID}/${VARIANT_ID}/${JOB_NAME}/task_${TASK_INDEX}"
CHECKPOINT_PREFIX="gs://${BUCKET}/checkpoints/${CASE_ID}/${VARIANT_ID}/latest"
WORK_DIR="${SCRATCH_ROOT}/${CASE_ID}"; STAGE_DIR="${WORK_DIR}/stage"; CASE_DIR="${WORK_DIR}/case"
mkdir -p "${STAGE_DIR}" "${CASE_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"

echo "Downloading case tree from ${CASE_PREFIX}/case/"
gcloud storage rsync --recursive "${CASE_PREFIX}/case/" "${CASE_DIR}/"   # tree, not tar.gz
gcloud storage cp "${CASE_PREFIX}/command.sh" "${CASE_DIR}/command.sh"
gcloud storage cp "${CASE_PREFIX}/manifest.json" "${STAGE_DIR}/manifest.json"
chmod +x "${CASE_DIR}/command.sh"

# resume from checkpoint if present
if gcloud storage ls "${CHECKPOINT_PREFIX}/" >/dev/null 2>&1; then
  echo "Resuming from ${CHECKPOINT_PREFIX}"
  gcloud storage rsync --recursive "${CHECKPOINT_PREFIX}/" "${CASE_DIR}/" || true
  command -v foamDictionary >/dev/null 2>&1 && \
    foamDictionary "${CASE_DIR}/system/controlDict" -entry startFrom -set latestTime || true
fi

CHECKPOINT_POLL_SEC="${CHECKPOINT_POLL_SEC:-30}"
sync_checkpoint() {   # FIXED: iterate real processor dirs; no quoted-glob passed to gcloud
  local p name
  for p in "${CASE_DIR}"/processor*/; do
    [[ -d "${p}" ]] || continue
    name="$(basename "${p}")"
    gcloud storage rsync --recursive "${p}" "${CHECKPOINT_PREFIX}/${name}/" || true
  done
  [[ -d "${CASE_DIR}/system" ]] && \
    gcloud storage rsync --recursive "${CASE_DIR}/system" "${CHECKPOINT_PREFIX}/system/" || true
}

checkpoint_loop() {
  local last="" newest
  while true; do
    sleep "${CHECKPOINT_POLL_SEC}"
    newest="$(ls -1 "${CASE_DIR}/processor0" 2>/dev/null | grep -E '^[0-9]+(\.[0-9]+)?$' | sort -n | tail -1)"
    if [[ -n "${newest}" && "${newest}" != "${last}" ]]; then sync_checkpoint; last="${newest}"; fi
  done
}

# Minimal stop handler: flush a final checkpoint so a manual stop / interruption can resume.
# NOT preemption-specific: no preempted.json, no exit 50001.
on_term() {
  trap '' TERM INT
  [[ -n "${SOLVER_PGID:-}" ]] && kill -TERM -"${SOLVER_PGID}" 2>/dev/null || true
  [[ -n "${CHECKPOINT_PID:-}" ]] && kill "${CHECKPOINT_PID}" 2>/dev/null || true
  sync_checkpoint
  exit 143
}

cat > "${STAGE_DIR}/runtime.json" <<EOF
{"case_id":"${CASE_ID}","variant_id":"${VARIANT_ID}","job_name":"${JOB_NAME}","hostname":"$(hostname)","started_at_utc":"$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
EOF

cd "${CASE_DIR}"
checkpoint_loop & CHECKPOINT_PID=$!
trap on_term TERM INT

set +e
setsid bash ./command.sh 2>&1 | tee "${STAGE_DIR}/solver.stdout.log" &
SOLVER_PID=$!
SOLVER_PGID="$(ps -o pgid= -p "${SOLVER_PID}" | tr -d ' ' || echo "")"
wait "${SOLVER_PID}"; rc=$?
set -e

printf '%s\n' "${rc}" > "${STAGE_DIR}/exit_code.txt"
[[ -n "${CHECKPOINT_PID:-}" ]] && { kill "${CHECKPOINT_PID}" 2>/dev/null || true; wait "${CHECKPOINT_PID}" 2>/dev/null || true; }

# results tarball — UNCHANGED behavior
tar -czf "${STAGE_DIR}/result.tar.gz" -C "${CASE_DIR}" .
gcloud storage cp "${STAGE_DIR}/manifest.json"      "${RESULT_PREFIX}/manifest.json"
gcloud storage cp "${STAGE_DIR}/runtime.json"       "${RESULT_PREFIX}/runtime.json"
gcloud storage cp "${STAGE_DIR}/solver.stdout.log"  "${RESULT_PREFIX}/solver.stdout.log"
gcloud storage cp "${STAGE_DIR}/exit_code.txt"      "${RESULT_PREFIX}/exit_code.txt"
gcloud storage cp "${STAGE_DIR}/result.tar.gz"      "${RESULT_PREFIX}/result.tar.gz"

if [[ "${rc}" -eq 0 ]]; then
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_SUCCESS"
  gcloud storage cp "${STAGE_DIR}/_SUCCESS" "${RESULT_PREFIX}/_SUCCESS"
  gcloud storage rm -r "${CHECKPOINT_PREFIX}/" || true
else
  date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/_FAILED"
  gcloud storage cp "${STAGE_DIR}/_FAILED" "${RESULT_PREFIX}/_FAILED"
fi
exit "${rc}"
```

- [ ] **Step 2: Remove the old script and point the Dockerfile at the new path**

```bash
git rm openfoam-batch/scripts/admin/run_case_in_batch.sh
chmod +x openfoam-batch/runtime/run_case_in_batch.sh
```
Then in `openfoam-batch/Dockerfile`, update the COPY line to the new path:
```dockerfile
COPY runtime/run_case_in_batch.sh /opt/openfoam-batch/run_case_in_batch.sh
RUN chmod +x /opt/openfoam-batch/run_case_in_batch.sh
```

- [ ] **Step 3: Commit**

```bash
git add openfoam-batch/runtime/run_case_in_batch.sh openfoam-batch/Dockerfile
git commit -m "fix(runtime): tree download, correct checkpoint rsync, drop preemption trap"
```

---

### Task 15: Update the runtime bash tests to the new behavior

**Files:**
- Modify: `openfoam-batch/tests/run_case_in_batch_test.sh`
- Reference harness: `openfoam-batch/tests/lib/test_helpers.sh`, `openfoam-batch/tests/lib/stubs/gcloud`

The current tests assert the OLD behavior (tar download, `processor*` glob, `preempted.json`, `exit 50001`). Update them to assert the NEW behavior.

- [ ] **Step 1: Update assertions to the new script**

Replace the tests that reference removed behavior with these (keep the existing harness/`start_test`/`assert_*` helpers):

1. **Tree download** — assert the script runs `gcloud storage rsync --recursive gs://${BUCKET}/cases/${CASE_ID}/case/ <CASE_DIR>/` (was `cp case.tar.gz` + `tar -xzf`). Grep the recorded gcloud calls (`GCLOUD_LOG`) for `rsync --recursive` with a `/case/` source.
2. **No SHA256SUMS** — assert the script does NOT reference `SHA256SUMS`.
3. **Checkpoint rsync has no glob** — assert no recorded gcloud arg contains the literal `processor*`; instead assert a per-dir source like `<CASE_DIR>/processor0/`.
4. **No preemption artifacts** — assert the script contains neither `preempted.json` nor `exit 50001`.
5. **CASE_ID_LIST resolution** — keep the existing test: with `CASE_ID_LIST=case_0001,case_0002` and `BATCH_TASK_INDEX=1`, resolved `CASE_ID` is `case_0002`.
6. **Results tar unchanged** — assert it still produces `result.tar.gz` and copies it to `${RESULT_PREFIX}/result.tar.gz`.

Use the existing `grep`/`assert_contains`/`assert_not_contains` patterns from `test_helpers.sh`. Example for #4:
```bash
start_test "no preemption artifacts in runtime script"
assert_not_contains "$(cat "${SCRIPT_UNDER_TEST}")" "preempted.json"
assert_not_contains "$(cat "${SCRIPT_UNDER_TEST}")" "exit 50001"
```
(Set `SCRIPT_UNDER_TEST=openfoam-batch/runtime/run_case_in_batch.sh`.)

- [ ] **Step 2: Run the bash tests**

Run: `bash openfoam-batch/tests/run_all.sh`
Expected: PASS — all runtime tests green against the new script.

- [ ] **Step 3: Commit**

```bash
git add openfoam-batch/tests/run_case_in_batch_test.sh
git commit -m "test(runtime): update bash tests for tree download + fixed checkpoint + no preemption"
```

---

### Task 16: Delete superseded scripts + update README

**Files:**
- Delete: `openfoam-batch/scripts/admin/submit_all_ready_cases.sh` (flaw #7)
- Delete: `openfoam-batch/scripts/admin/submit_one_case.sh`, `submit_one_job_multi_task.sh`, `check_case_prefix.sh` (superseded by core/CLI)
- Delete: `openfoam-batch/scripts/prof/professor_upload_case.sh` (superseded by `of upload`)
- Modify: `README.md` and any test files referencing the deleted scripts

- [ ] **Step 1: Remove the superseded bash scripts**

```bash
git rm openfoam-batch/scripts/admin/submit_all_ready_cases.sh \
       openfoam-batch/scripts/admin/submit_one_case.sh \
       openfoam-batch/scripts/admin/submit_one_job_multi_task.sh \
       openfoam-batch/scripts/admin/check_case_prefix.sh \
       openfoam-batch/scripts/prof/professor_upload_case.sh
git rm openfoam-batch/tests/submit_one_case_test.sh \
       openfoam-batch/tests/submit_one_job_multi_task_test.sh \
       openfoam-batch/tests/professor_upload_case_test.sh
```

- [ ] **Step 2: Update `README.md`**

Replace the "Submission Modes" / script-list sections with the new model: two modes only (single-task, multi-task) via `of run`; upload via `of upload`; validate via `of validate`; runtime image runs `openfoam-batch/runtime/run_case_in_batch.sh`. State that Spot is an opt-in flag and there is no `maxRunDuration`.

- [ ] **Step 3: Verify nothing else references the deleted scripts**

Run: `grep -rn "submit_all_ready\|submit_one_case\|submit_one_job_multi_task\|professor_upload_case\|check_case_prefix" --include='*.sh' --include='*.md' . | grep -v docs/superpowers`
Expected: no results (or only historical doc references you intentionally keep).

- [ ] **Step 4: Run both test suites**

Run: `cd phase3-run-app && pytest -v && cd .. && bash openfoam-batch/tests/run_all.sh`
Expected: PASS (python + bash green).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove superseded bash scripts (single source = core/CLI); update README"
```

---

## Self-Review

**Spec coverage (M1 scope):**
- Flaw #1 (no maxRunDuration) → Task 9 (`test_single_has_no_max_run_duration`). ✓
- Flaw #2 (image `12.x.x`) → Task 7 (`Settings.image_uri="openfoam:12.0.0"`) + recorded in spec via Task 9 image assertion. ✓
- Flaw #3 (variant=machine) → Task 2 + Task 9 (`test_variant_env_is_machine_type`). ✓
- Flaw #4 (local-ssd default + override) → Task 6 + Task 9. ✓
- Flaw #5 (case_0001 atomic allocator) → Task 4 (4 tests incl. empty-bucket + 50-contiguous). ✓
- Flaw #6 (task==parallelism) → Task 10. ✓
- Flaw #7 (remove submit_all_ready) → Task 16. ✓
- Flaw #8 (spot toggle + fixed checkpoint + no preemption trap) → Task 9 (toggle) + Task 14 (runtime). ✓
- File-tree upload format → Task 13 (`of upload` rsync) + Task 14 (runtime tree download). ✓
- Validation replaces check_case_prefix → Task 5 + Task 12. ✓
- Two modes only → Task 13 + Task 16. ✓

**Out of M1 scope (later plans):** signed POST policies, IAP/JWT, FastAPI backend, SPA, infra/IAM, WIF/CI, Artifact Registry migration, suggested-machine wired to real metrics. (M2–M5.)

**Placeholder scan:** no TBD/TODO; every code step has complete code. ✓

**Type consistency:** `StorageClient` methods (`object_exists`, `create_exclusive`, `upload_bytes`, `read_text`, `list_case_ids`, plus `list_paths` on real impl) used consistently across cases/validation/CLI. `BatchJobBuilder.build_single/build_multi` signatures match CLI call sites in Task 13 (`cpu_milli`, `memory_mib`, `mpi_ranks`, `provisioning_model`). ✓

---

## Execution Handoff

Implemented via `codex exec` per task (orchestrator reviews `git diff` + runs the listed test command between tasks). Verification gates: `pytest -v` (python) and `bash openfoam-batch/tests/run_all.sh` (runtime). A real-GCP smoke test (`of upload` + `of run` against a throwaway `case_test` prefix) is run manually after Task 13 once `gcloud`/ADC auth is confirmed.
