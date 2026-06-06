import dataclasses

from fastapi import APIRouter, Depends

from backend.deps import run_repo
from backend.rbac import current_account

router = APIRouter()


@router.get("/me")
def me(account=Depends(current_account)):
    _user, rec = account
    return {"email": rec.email, "role": rec.role, "status": rec.status}


@router.get("/me/runs")
def my_runs(account=Depends(current_account), runs=Depends(run_repo)):
    return {
        "runs": [
            dataclasses.asdict(record)
            for record in runs.list_by_user(account[0].email)
        ]
    }
