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
