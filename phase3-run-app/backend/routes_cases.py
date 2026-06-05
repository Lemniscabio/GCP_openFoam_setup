import datetime
import json

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import User, current_user
from backend.deps import case_repo, storage, url_service
from backend.schemas import AllocateReq, FinalizeReq

router = APIRouter()


@router.post("/cases:allocate")
def allocate(
    req: AllocateReq,
    user: User = Depends(current_user),
    repo=Depends(case_repo),
    urls=Depends(url_service),
):
    ids = repo.allocate_ids(len(req.cases))
    now = datetime.datetime.now(datetime.timezone.utc)
    cases = []
    for case_id, case in zip(ids, req.cases):
        uploads = urls.put_urls_for_case(case_id, case.files, now)
        cases.append(
            {
                "case_id": case_id,
                "uploads": [
                    {
                        "object_path": upload.object_path,
                        "url": upload.url,
                        "method": upload.method,
                    }
                    for upload in uploads
                ],
            }
        )
    return {"cases": cases}


@router.post("/cases/{case_id}:finalize")
def finalize(
    case_id: str,
    req: FinalizeReq,
    user: User = Depends(current_user),
    repo=Depends(case_repo),
    store=Depends(storage),
):
    if not repo.exists(case_id):
        raise HTTPException(status_code=404, detail="unknown case")
    if not store.list_paths(f"cases/{case_id}/case/"):
        raise HTTPException(status_code=400, detail="case incomplete: missing case/ tree")
    if not store.object_exists(f"cases/{case_id}/case/command.sh"):
        raise HTTPException(status_code=400, detail="case incomplete: missing case/command.sh")

    uploaded_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest = {
        "case_id": case_id,
        "solver_family": "openfoam",
        "openfoam_version": req.openfoam_version,
        "uploaded_by": user.email,
        "uploaded_at_utc": uploaded_at,
    }
    store.upload_bytes(f"cases/{case_id}/manifest.json", json.dumps(manifest).encode())
    store.upload_bytes(f"cases/{case_id}/READY", uploaded_at.encode())
    return {"case_id": case_id, "ready": True}


@router.get("/cases")
def list_cases(user: User = Depends(current_user), repo=Depends(case_repo)):
    return {"cases": [{"case_id": c.case_id, "ready": c.ready} for c in repo.list_cases()]}
