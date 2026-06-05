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
        decided_by=caller.email,
        now=now,
    )
    return dataclasses.asdict(repo.get(email))
