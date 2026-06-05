# Feature C — Access Control (RBAC + approval gate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add role-based authorization with an admin-approval gate on top of the existing Google-ID-token authentication.

**Architecture:** A Firestore `of_users` collection (role `admin`/`runner`/`viewer`, status `pending`/`active`/`disabled`) read by FastAPI RBAC dependencies that gate every `/api/*` route per a permission matrix. Seed admins are auto-provisioned from config; new users land `pending`. Admin endpoints + an Admin tab manage users. Follows the existing Protocol + in-memory-fake pattern.

**Tech Stack:** Python 3.12, FastAPI, `google-cloud-firestore`, Pydantic, pytest; React/TS (Vitest).

**Spec:** `docs/superpowers/specs/2026-06-05-feature-c-access-control-design.md`

**Working dir for all paths:** `phase3-run-app/`. **Python tests:** `OF_DEV_NO_IAP=1 .venv/bin/pytest -q`.

---

## File Structure

**Create:**
- `core/users.py` — `UserRecord`, `UserRepository` Protocol, `InMemoryUserRepository`, `FirestoreUserRepository`, `resolve_on_login()`.
- `backend/rbac.py` — `current_account`, `require_active`, `require_runner`, `require_admin`.
- `backend/routes_me.py` — `GET /api/me`.
- `backend/routes_admin.py` — `GET/POST /api/admin/users`.
- `tests/test_users.py`, `tests/test_rbac.py`, `tests/test_routes_me.py`, `tests/test_routes_admin.py`.

**Modify:**
- `core/config.py` — `seed_admins` setting.
- `backend/deps.py` — `user_repo()` provider.
- `backend/routes_cases.py`, `backend/routes_jobs.py` — gate with `require_*`.
- `backend/main.py` — include `routes_me`, `routes_admin`.
- `tests/conftest.py` — default-inject an active admin; add `mem_users` fixture.
- `frontend/src/lib/api.ts` — `getMe()`, `listUsers()`, `setUser()`.
- `frontend/src/App.tsx` — top-level access gate (pending/disabled/viewer/admin) + role chip.
- `frontend/src/views/AdminView.tsx` (new) — user management table.

---

## Task 1: Add `seed_admins` config

**Files:** Modify `core/config.py`; Test `tests/test_config.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_config.py`:
```python
def test_seed_admins_parsed_from_env(monkeypatch):
    monkeypatch.setenv("OF_SEED_ADMINS", "a@lemnisca.bio, b@lemnisca.bio")
    from importlib import reload
    import core.config as cfg
    reload(cfg)
    assert cfg.Settings().seed_admins == ["a@lemnisca.bio", "b@lemnisca.bio"]
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_config.py::test_seed_admins_parsed_from_env -q` → FAIL (no `seed_admins`).

- [ ] **Step 3: Implement** — in `core/config.py`, add a module helper above `Settings` and a field. After the imports:
```python
def _parse_seed_admins() -> list[str]:
    raw = os.environ.get(
        "OF_SEED_ADMINS", "kartikey.attri@lemnisca.bio,gaurav.deshmukh@lemnisca.bio"
    )
    return [e.strip().lower() for e in raw.split(",") if e.strip()]
```
Inside the `Settings` dataclass add:
```python
    seed_admins: list[str] = field(default_factory=_parse_seed_admins)
```
Ensure `from dataclasses import dataclass, field` is imported (add `field`).

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_config.py -q` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add core/config.py tests/test_config.py
git commit -m "feat(config): OF_SEED_ADMINS list"
```

---

## Task 2: UserRecord + UserRepository + in-memory fake + resolve_on_login

**Files:** Create `core/users.py`; Test `tests/test_users.py`.

- [ ] **Step 1: Write the failing test** — create `tests/test_users.py`:
```python
import datetime

from core.users import (
    UserRecord, InMemoryUserRepository, resolve_on_login,
)

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
SEED = ["kartikey.attri@lemnisca.bio"]


def test_resolve_seed_admin_is_active_admin():
    rec = resolve_on_login("kartikey.attri@lemnisca.bio", SEED, None, NOW)
    assert rec.role == "admin" and rec.status == "active"


def test_resolve_new_user_is_pending():
    rec = resolve_on_login("new@lemnisca.bio", SEED, None, NOW)
    assert rec.status == "pending" and rec.role is None
    assert rec.requested_at == NOW


def test_resolve_existing_user_unchanged():
    existing = UserRecord(email="x@lemnisca.bio", role="viewer", status="active",
                          requested_at=NOW, decided_by="a@b", decided_at=NOW)
    assert resolve_on_login("x@lemnisca.bio", SEED, existing, NOW) == existing


def test_repo_upsert_get_list():
    repo = InMemoryUserRepository()
    repo.upsert(resolve_on_login("new@lemnisca.bio", SEED, None, NOW))
    assert repo.get("new@lemnisca.bio").status == "pending"
    assert [u.email for u in repo.list_all()] == ["new@lemnisca.bio"]


def test_set_decision_updates_role_status_audit():
    repo = InMemoryUserRepository()
    repo.upsert(resolve_on_login("new@lemnisca.bio", SEED, None, NOW))
    repo.set_decision("new@lemnisca.bio", role="runner", status="active",
                      decided_by="kartikey.attri@lemnisca.bio", now=NOW)
    rec = repo.get("new@lemnisca.bio")
    assert rec.role == "runner" and rec.status == "active"
    assert rec.decided_by == "kartikey.attri@lemnisca.bio" and rec.decided_at == NOW
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_users.py -q` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement** — create `core/users.py`:
```python
import datetime
from dataclasses import dataclass
from typing import Protocol

ROLES = {"admin", "runner", "viewer"}
STATUSES = {"pending", "active", "disabled"}


@dataclass
class UserRecord:
    email: str
    role: str | None
    status: str
    requested_at: datetime.datetime
    decided_by: str | None = None
    decided_at: datetime.datetime | None = None


def resolve_on_login(email, seed_admins, existing, now) -> UserRecord:
    """Pure: decide the user's record at login time.
    - seed admins are always ensured admin/active (idempotent)
    - brand-new users become pending
    - everyone else is returned unchanged"""
    email = email.lower()
    if email in seed_admins:
        if existing and existing.role == "admin" and existing.status == "active":
            return existing
        return UserRecord(
            email=email, role="admin", status="active",
            requested_at=(existing.requested_at if existing else now),
            decided_by="seed", decided_at=now,
        )
    if existing is None:
        return UserRecord(email=email, role=None, status="pending", requested_at=now)
    return existing


class UserRepository(Protocol):
    def get(self, email: str) -> UserRecord | None: ...
    def upsert(self, record: UserRecord) -> None: ...
    def list_all(self) -> list[UserRecord]: ...
    def set_decision(self, email: str, role: str | None, status: str,
                     decided_by: str, now: datetime.datetime) -> None: ...


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}

    def get(self, email):
        return self._users.get(email.lower())

    def upsert(self, record):
        self._users[record.email.lower()] = record

    def list_all(self):
        return sorted(self._users.values(), key=lambda u: u.email)

    def set_decision(self, email, role, status, decided_by, now):
        rec = self._users[email.lower()]
        rec.role = role
        rec.status = status
        rec.decided_by = decided_by
        rec.decided_at = now
```

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_users.py -q` → PASS (5 passed).

- [ ] **Step 5: Commit**:
```bash
git add core/users.py tests/test_users.py
git commit -m "feat(core): UserRepository + resolve_on_login + in-memory fake"
```

---

## Task 3: FirestoreUserRepository

**Files:** Modify `core/users.py` (append). No offline unit test (same approach as Feature A's Firestore repos).

- [ ] **Step 1: Append** to `core/users.py`:
```python
class FirestoreUserRepository:
    COLLECTION = "of_users"

    def __init__(self, client, collection: str = COLLECTION) -> None:
        self._c = client
        self._col = collection

    def _doc(self, email: str):
        return self._c.collection(self._col).document(email.lower())

    def get(self, email):
        snap = self._doc(email).get()
        if not snap.exists:
            return None
        d = snap.to_dict()
        return UserRecord(
            email=d["email"], role=d.get("role"), status=d.get("status", "pending"),
            requested_at=d.get("requested_at"), decided_by=d.get("decided_by"),
            decided_at=d.get("decided_at"),
        )

    def upsert(self, record):
        self._doc(record.email).set({
            "email": record.email.lower(), "role": record.role, "status": record.status,
            "requested_at": record.requested_at, "decided_by": record.decided_by,
            "decided_at": record.decided_at,
        }, merge=True)

    def list_all(self):
        out = []
        for snap in self._c.collection(self._col).stream():
            d = snap.to_dict()
            out.append(UserRecord(
                email=d["email"], role=d.get("role"), status=d.get("status", "pending"),
                requested_at=d.get("requested_at"), decided_by=d.get("decided_by"),
                decided_at=d.get("decided_at"),
            ))
        return sorted(out, key=lambda u: u.email)

    def set_decision(self, email, role, status, decided_by, now):
        self._doc(email).set({
            "role": role, "status": status, "decided_by": decided_by, "decided_at": now,
        }, merge=True)
```

- [ ] **Step 2: Import check**: `OF_DEV_NO_IAP=1 .venv/bin/python -c "from core.users import FirestoreUserRepository; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**:
```bash
git add core/users.py
git commit -m "feat(core): FirestoreUserRepository"
```

---

## Task 4: `user_repo()` dependency provider

**Files:** Modify `backend/deps.py`.

- [ ] **Step 1: Add provider** — in `backend/deps.py`, add near the other repo providers:
```python
from core.users import FirestoreUserRepository


def user_repo() -> FirestoreUserRepository:
    return FirestoreUserRepository(_firestore())
```
(`_firestore()` already exists from Feature A.)

- [ ] **Step 2: Import check**: `OF_DEV_NO_IAP=1 .venv/bin/python -c "from backend.deps import user_repo; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**:
```bash
git add backend/deps.py
git commit -m "feat(deps): user_repo provider"
```

---

## Task 5: RBAC dependencies

**Files:** Create `backend/rbac.py`; Test `tests/test_rbac.py`.

- [ ] **Step 1: Write the failing test** — create `tests/test_rbac.py`:
```python
import datetime

import pytest
from fastapi import HTTPException

from backend.rbac import _enforce  # pure helper exercised directly
from core.users import UserRecord

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _rec(role, status="active"):
    return UserRecord(email="u@lemnisca.bio", role=role, status=status, requested_at=NOW)


def test_active_required():
    with pytest.raises(HTTPException) as e:
        _enforce(_rec("runner", status="pending"), need="active")
    assert e.value.status_code == 403


def test_runner_allows_runner_and_admin():
    _enforce(_rec("runner"), need="runner")
    _enforce(_rec("admin"), need="runner")
    with pytest.raises(HTTPException):
        _enforce(_rec("viewer"), need="runner")


def test_admin_only():
    _enforce(_rec("admin"), need="admin")
    with pytest.raises(HTTPException):
        _enforce(_rec("runner"), need="admin")


def test_active_allows_any_active_role():
    for r in ("admin", "runner", "viewer"):
        _enforce(_rec(r), need="active")
```

- [ ] **Step 2: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_rbac.py -q` → FAIL.

- [ ] **Step 3: Implement** — create `backend/rbac.py`:
```python
import datetime
import os

from fastapi import Depends, HTTPException

from backend.auth import User, current_user
from backend.deps import settings, user_repo
from core.users import UserRecord, resolve_on_login


def _enforce(rec: UserRecord, need: str) -> UserRecord:
    """need in {'active','runner','admin'}. Fail closed."""
    if rec.status != "active":
        raise HTTPException(status_code=403, detail=f"access {rec.status}")
    if need == "runner" and rec.role not in ("runner", "admin"):
        raise HTTPException(status_code=403, detail="requires runner role")
    if need == "admin" and rec.role != "admin":
        raise HTTPException(status_code=403, detail="requires admin role")
    return rec


def current_account(
    user: User = Depends(current_user),
    repo=Depends(user_repo),
    s=Depends(settings),
):
    """Return (User, UserRecord), auto-provisioning on first login. Never 403s."""
    now = datetime.datetime.now(datetime.timezone.utc)
    if os.environ.get("OF_DEV_NO_IAP") == "1":
        return user, UserRecord(email=user.email, role="admin", status="active", requested_at=now)
    existing = repo.get(user.email)
    resolved = resolve_on_login(user.email, s.seed_admins, existing, now)
    if resolved != existing:
        repo.upsert(resolved)
    return user, resolved


# NOTE: `settings` in deps.py is a zero-arg provider; FastAPI's Depends(settings)
# injects the resolved Settings INSTANCE, so use `s.seed_admins` (not `s()`).


def require_active(account=Depends(current_account)):
    _enforce(account[1], "active")
    return account


def require_runner(account=Depends(current_account)):
    _enforce(account[1], "runner")
    return account


def require_admin(account=Depends(current_account)):
    _enforce(account[1], "admin")
    return account
```
NOTE: `Depends(settings)` injects the resolved `Settings` instance (FastAPI calls the
provider), so read `s.seed_admins` directly. Confirm `deps.settings` is the zero-arg
provider it appears to be.

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_rbac.py -q` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add backend/rbac.py tests/test_rbac.py
git commit -m "feat(rbac): current_account + require_active/runner/admin"
```

---

## Task 6: `GET /api/me`

**Files:** Create `backend/routes_me.py`; Test `tests/test_routes_me.py`. Also extend `tests/conftest.py` with a `mem_users` fixture + override.

- [ ] **Step 1: Add the `mem_users` fixture + client wiring** — in `tests/conftest.py`, add:
```python
from core.users import InMemoryUserRepository
from backend import rbac


@pytest.fixture
def mem_users():
    return InMemoryUserRepository()
```
Find the existing `client` fixture (it builds a `TestClient(app)` and sets `app.dependency_overrides`). Add overrides so routes use the fakes:
```python
    app.dependency_overrides[deps.user_repo] = lambda: mem_users
    # default account = active admin unless a test overrides current_account
    app.dependency_overrides[rbac.current_account] = lambda: (
        __import__("backend.auth", fromlist=["User"]).User(email="dev@lemnisca.bio", sub="d"),
        __import__("core.users", fromlist=["UserRecord"]).UserRecord(
            email="dev@lemnisca.bio", role="admin", status="active",
            requested_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ),
    )
```
> Match the exact construction style already used in `conftest.py` (it imports these at top). Prefer adding clean top-level imports for `User`/`UserRecord`/`datetime` rather than the inline `__import__` shown above — that's only to make the dependency explicit.

- [ ] **Step 2: Write the failing test** — create `tests/test_routes_me.py`:
```python
def test_me_returns_role_and_status(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "dev@lemnisca.bio"
    assert body["role"] == "admin"
    assert body["status"] == "active"
```

- [ ] **Step 3: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_me.py -q` → FAIL (404 / no route).

- [ ] **Step 4: Implement** — create `backend/routes_me.py`:
```python
from fastapi import APIRouter, Depends

from backend.rbac import current_account

router = APIRouter()


@router.get("/me")
def me(account=Depends(current_account)):
    _user, rec = account
    return {"email": rec.email, "role": rec.role, "status": rec.status}
```
Register it in `backend/main.py` (with the other `/api` routers — see Task 9; for this task's test, also add the include now):
```python
from backend.routes_me import router as me_router
app.include_router(me_router, prefix="/api")
```

- [ ] **Step 5: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_me.py -q` → PASS.

- [ ] **Step 6: Commit**:
```bash
git add backend/routes_me.py backend/main.py tests/conftest.py tests/test_routes_me.py
git commit -m "feat(api): GET /api/me + test fixtures for users/account"
```

---

## Task 7: Admin user-management endpoints

**Files:** Create `backend/routes_admin.py`; Modify `backend/schemas.py`; Test `tests/test_routes_admin.py`.

- [ ] **Step 1: Add the request schema** — in `backend/schemas.py`:
```python
class SetUserReq(BaseModel):
    role: str | None = None      # "admin" | "runner" | "viewer"
    status: str | None = None    # "active" | "disabled" | "pending"
```

- [ ] **Step 2: Write the failing test** — create `tests/test_routes_admin.py`:
```python
import datetime

from core.users import UserRecord

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _pending(repo, email):
    repo.upsert(UserRecord(email=email, role=None, status="pending", requested_at=NOW))


def test_admin_lists_users(client, mem_users):
    _pending(mem_users, "new@lemnisca.bio")
    r = client.get("/api/admin/users")
    assert r.status_code == 200
    assert any(u["email"] == "new@lemnisca.bio" for u in r.json()["users"])


def test_admin_approves_user(client, mem_users):
    _pending(mem_users, "new@lemnisca.bio")
    r = client.post("/api/admin/users/new@lemnisca.bio", json={"role": "runner", "status": "active"})
    assert r.status_code == 200
    rec = mem_users.get("new@lemnisca.bio")
    assert rec.role == "runner" and rec.status == "active"
    assert rec.decided_by == "dev@lemnisca.bio"


def test_cannot_disable_self(client, mem_users):
    mem_users.upsert(UserRecord(email="dev@lemnisca.bio", role="admin", status="active", requested_at=NOW))
    r = client.post("/api/admin/users/dev@lemnisca.bio", json={"status": "disabled"})
    assert r.status_code == 400


def test_unknown_user_404(client):
    r = client.post("/api/admin/users/ghost@lemnisca.bio", json={"role": "viewer", "status": "active"})
    assert r.status_code == 404


def test_non_admin_forbidden(client, mem_users):
    # override current_account to a viewer for this test
    from backend import rbac
    from backend.auth import User
    from backend.main import app
    app.dependency_overrides[rbac.current_account] = lambda: (
        User(email="v@lemnisca.bio", sub="v"),
        UserRecord(email="v@lemnisca.bio", role="viewer", status="active", requested_at=NOW),
    )
    r = client.get("/api/admin/users")
    assert r.status_code == 403
    app.dependency_overrides.pop(rbac.current_account, None)
```

- [ ] **Step 3: Run → fail**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_admin.py -q` → FAIL.

- [ ] **Step 4: Implement** — create `backend/routes_admin.py`:
```python
import dataclasses
import datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.deps import settings, user_repo
from backend.rbac import require_admin
from backend.schemas import SetUserReq
from core.users import ROLES, STATUSES

router = APIRouter()


@router.get("/admin/users")
def list_users(account=Depends(require_admin), repo=Depends(user_repo)):
    return {"users": [dataclasses.asdict(u) for u in repo.list_all()]}


@router.post("/admin/users/{email}")
def set_user(
    email: str,
    req: SetUserReq,
    account=Depends(require_admin),
    repo=Depends(user_repo),
    s=Depends(settings),
):
    caller = account[0]
    email = email.lower()
    if req.role is not None and req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"bad role {req.role}")
    if req.status is not None and req.status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"bad status {req.status}")
    target = repo.get(email)
    if target is None:
        raise HTTPException(status_code=404, detail="unknown user")
    demote = req.role is not None and req.role != "admin"
    disable = req.status == "disabled"
    if email == caller.email.lower() and (disable or demote):
        raise HTTPException(status_code=400, detail="cannot disable or demote yourself")
    if email in s.seed_admins and (disable or demote):
        raise HTTPException(status_code=400, detail="cannot demote/disable a seed admin")
    now = datetime.datetime.now(datetime.timezone.utc)
    repo.set_decision(
        email,
        role=req.role if req.role is not None else target.role,
        status=req.status if req.status is not None else target.status,
        decided_by=caller.email, now=now,
    )
    return dataclasses.asdict(repo.get(email))
```
Register in `backend/main.py` (Task 9). For this task's tests, add the include now:
```python
from backend.routes_admin import router as admin_router
app.include_router(admin_router, prefix="/api")
```

- [ ] **Step 5: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_admin.py -q` → PASS (5 passed).

- [ ] **Step 6: Commit**:
```bash
git add backend/routes_admin.py backend/schemas.py backend/main.py tests/test_routes_admin.py
git commit -m "feat(admin): user list + approve/role/disable with guard rails"
```

---

## Task 8: Gate existing routes with `require_*`

**Files:** Modify `backend/routes_cases.py`, `backend/routes_jobs.py`; update `tests/conftest.py` if needed.

- [ ] **Step 1: Write the failing test** — append to `tests/test_routes_jobs.py`:
```python
def test_viewer_cannot_submit(client, valid_case):
    import datetime
    from backend import rbac
    from backend.auth import User
    from backend.main import app
    from core.users import UserRecord
    now = datetime.datetime.now(datetime.timezone.utc)
    app.dependency_overrides[rbac.current_account] = lambda: (
        User(email="v@lemnisca.bio", sub="v"),
        UserRecord(email="v@lemnisca.bio", role="viewer", status="active", requested_at=now),
    )
    r = client.post("/api/jobs", json={"case_ids": ["case_0006"], "machine_type": "c2d-highcpu-8"})
    assert r.status_code == 403
    app.dependency_overrides.pop(rbac.current_account, None)
```

- [ ] **Step 2: Run → fail**: route still uses `current_user`, so a viewer is allowed → test FAILS (got 200/400, expected 403).

- [ ] **Step 3: Implement** — change the gated routes to depend on `require_*` and read the user from the account tuple.

In `backend/routes_jobs.py`:
- imports: `from backend.rbac import require_active, require_runner` (drop `current_user` import if now unused).
- `submit(...)`: replace `user: User = Depends(current_user)` with `account=Depends(require_runner)` and add `user = account[0]` as the first line of the body. Keep all `user.email` references.
- `list_runs(...)` and `run_detail(...)`: replace `user: User = Depends(current_user)` with `account=Depends(require_active)` (they don't need `user`).

In `backend/routes_cases.py`:
- `allocate` and `finalize`: `account=Depends(require_runner)`, `user = account[0]`.
- `list_cases`: `account=Depends(require_active)`.

- [ ] **Step 4: Run → pass**: `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_routes_jobs.py tests/test_routes_cases.py -q` → PASS (the default `client` fixture's active-admin override keeps existing tests green; the viewer test gets 403).

- [ ] **Step 5: Full suite**: `OF_DEV_NO_IAP=1 .venv/bin/pytest -q` → PASS.

- [ ] **Step 6: Commit**:
```bash
git add backend/routes_cases.py backend/routes_jobs.py tests/test_routes_jobs.py
git commit -m "feat(rbac): gate cases/jobs routes by role"
```

---

## Task 9: Confirm router registration + app smoke test

**Files:** Modify `backend/main.py` (ensure both new routers included exactly once, before the static mount).

- [ ] **Step 1: Ensure includes** — `backend/main.py` includes (after cases/jobs, before `app.mount("/", StaticFiles...)`):
```python
app.include_router(me_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
```
(If Tasks 6/7 already added them, just de-duplicate.)

- [ ] **Step 2: Smoke test**:
```bash
OF_DEV_NO_IAP=1 .venv/bin/python -c "
from backend.main import app
paths=[r.path for r in app.routes]
for p in ('/api/me','/api/admin/users','/api/admin/users/{email}'): assert p in paths, (p, paths)
print('routes ok')
"
```
Expected: `routes ok`.

- [ ] **Step 3: Full suite + commit**:
```bash
OF_DEV_NO_IAP=1 .venv/bin/pytest -q   # expect all green
git add backend/main.py
git commit -m "chore(app): register me/admin routers"
```

---

## Task 10: Frontend API client methods

**Files:** Modify `frontend/src/lib/api.ts`; Test `frontend/src/tests/api.test.ts`. Run with `cd frontend && npx vitest run`.

- [ ] **Step 1: Write the failing test** — append to `frontend/src/tests/api.test.ts` (adapt `ApiClient` construction + the fetch-mock to the file's existing style):
```ts
it("getMe GETs /api/me and setUser POSTs the role/status", async () => {
  const calls: any[] = [];
  globalThis.fetch = vi.fn(async (url: any, init: any) => {
    calls.push({ url: String(url), method: init?.method, body: init?.body });
    return new Response(JSON.stringify({ email: "x@lemnisca.bio", role: "viewer", status: "active" }), { status: 200 });
  }) as any;
  const { ApiClient } = await import("../lib/api");
  const api = new ApiClient(() => "tok");           // match the real constructor signature
  await api.getMe();
  await api.setUser("x@lemnisca.bio", { role: "runner", status: "active" });
  const me = calls.find((c) => c.url.includes("/api/me"));
  const set = calls.find((c) => c.url.includes("/api/admin/users/"));
  expect(me.method).toBe("GET");
  expect(set.method).toBe("POST");
  expect(JSON.parse(set.body)).toEqual({ role: "runner", status: "active" });
});
```

- [ ] **Step 2: Run → fail**: `cd frontend && npx vitest run src/tests/api.test.ts` → FAIL.

- [ ] **Step 3: Implement** — in `frontend/src/lib/api.ts`, add to `ApiClient` (using the existing private `req` helper):
```ts
  getMe() {
    return this.req("GET", "/api/me");
  }
  listUsers() {
    return this.req("GET", "/api/admin/users");
  }
  setUser(email: string, body: { role?: string; status?: string }) {
    return this.req("POST", `/api/admin/users/${encodeURIComponent(email)}`, body);
  }
```
Add a type near the top:
```ts
export type Me = { email: string; role: string | null; status: string };
export type ManagedUser = { email: string; role: string | null; status: string; decided_by: string | null };
```

- [ ] **Step 4: Run → pass**: `cd frontend && npx vitest run` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add frontend/src/lib/api.ts frontend/src/tests/api.test.ts
git commit -m "feat(frontend): api client me/listUsers/setUser"
```

---

## Task 11: Frontend access gate + role chip

**Files:** Modify `frontend/src/App.tsx` (and `AppShell`/header as needed).

- [ ] **Step 1: Implement the gate** — after sign-in, call `api.getMe()` once and store `me`. Branch:
  - `me.status === "pending"` → render a centered card: "Access pending admin approval" (sign-out button only).
  - `me.status === "disabled"` → render: "Access revoked — contact an admin."
  - `me.status === "active"` → render the app. Pass `me.role` down so:
    - **viewer**: hide/disable the Upload tab and the Run/Submit actions (read-only).
    - **admin**: show the Admin tab (Task 12).
  - Header: show `me.email` + a small role chip.
  Follow the existing `SignInGate`/`AppShell` patterns; keep the batch-launcher aesthetic.

- [ ] **Step 2: Verify build + tests**: `cd frontend && npx vitest run && npm run build` → both succeed.

- [ ] **Step 3: Commit**:
```bash
git add frontend/src
git commit -m "feat(frontend): access gate (pending/disabled/viewer) + role chip"
```

---

## Task 12: Frontend Admin tab

**Files:** Create `frontend/src/views/AdminView.tsx`; wire into `AppShell` tabs (admin-only).

- [ ] **Step 1: Implement** — `AdminView` calls `api.listUsers()` on mount, renders a table (email, status, role, decided_by) with **pending users sorted first**. Per row: a role `<select>` (admin/runner/viewer) and buttons **Approve** (`setUser(email,{role,status:"active"})`), **Disable** (`setUser(email,{status:"disabled"})`); refresh after each action. Show the row's own email-vs-self and seed-admin cases gracefully (the backend returns 400; surface the message). Match existing view styling (see `RunsView.tsx`).

- [ ] **Step 2: Show the tab only for admins** — in `AppShell`, render the Admin tab only when `me.role === "admin"`.

- [ ] **Step 3: Verify**: `cd frontend && npx vitest run && npm run build` → succeed.

- [ ] **Step 4: Commit**:
```bash
git add frontend/src
git commit -m "feat(frontend): Admin tab for user management"
```

---

## Task 13: Deploy config — seed admins env var

**Files:** Modify `.github/workflows/deploy.yml`.

- [ ] **Step 1: Add the env var to the Cloud Run deploy** — in `.github/workflows/deploy.yml`, in the `gcloud run deploy` `--update-env-vars` list, append:
```
,OF_SEED_ADMINS=kartikey.attri@lemnisca.bio,gaurav.deshmukh@lemnisca.bio
```
> CAUTION: `--update-env-vars` is comma-separated, and the value itself contains a comma. Use the `^@^` custom delimiter form to avoid mis-splitting, e.g. prefix the whole list with `^@^` and separate vars with `@`:
> `--update-env-vars "^@^OF_OAUTH_CLIENT_ID=...@OF_ALLOWED_DOMAIN=...@OF_IMAGE_URI=...@OF_SEED_ADMINS=kartikey.attri@lemnisca.bio,gaurav.deshmukh@lemnisca.bio"`
> Verify the exact rewrite against the current deploy.yml line and keep all existing vars.

- [ ] **Step 2: Validate workflow YAML**: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))" && echo "yaml ok"` (or `bash -n` is N/A for YAML; use the python check).

- [ ] **Step 3: Commit**:
```bash
git add .github/workflows/deploy.yml
git commit -m "ci: set OF_SEED_ADMINS on Cloud Run deploy"
```

---

## Final verification
- [ ] `OF_DEV_NO_IAP=1 .venv/bin/pytest -q` — all green (89 prior + new).
- [ ] `cd frontend && npx vitest run` — green.
- [ ] `bash phase3-run-app/runtime/tests/run_all.sh` — green (unchanged by C).
- [ ] After deploy: confirm `OF_SEED_ADMINS` is set; sign in as a seed admin → land in the app as admin; sign in as a fresh `@lemnisca.bio` account → "pending"; approve it from the Admin tab → it can act per its role.
