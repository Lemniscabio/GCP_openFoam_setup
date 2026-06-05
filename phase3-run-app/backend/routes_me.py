from fastapi import APIRouter, Depends

from backend.rbac import current_account

router = APIRouter()


@router.get("/me")
def me(account=Depends(current_account)):
    _user, rec = account
    return {"email": rec.email, "role": rec.role, "status": rec.status}
