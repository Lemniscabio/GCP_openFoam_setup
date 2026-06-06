import datetime
import json

from fastapi import APIRouter, Depends, HTTPException

from backend.deps import case_record_repo, case_repo, project_repo, storage, url_service
from backend.rbac import require_active, require_runner
from backend.schemas import AllocateReq, FinalizeReq
from core.case_records import CaseRecord
from core.projects import is_valid_project_name
from core.validation import validate_case

router = APIRouter()


@router.post("/cases:allocate")
def allocate(
    req: AllocateReq,
    account=Depends(require_runner),
    repo=Depends(case_repo),
    projects=Depends(project_repo),
    urls=Depends(url_service),
):
    user = account[0]
    now = datetime.datetime.now(datetime.timezone.utc)
    if not is_valid_project_name(req.project):
        raise HTTPException(status_code=400, detail="invalid project name")
    projects.ensure(req.project, user.email, now)
    ids = repo.allocate_ids(req.project, len(req.cases))
    cases = []
    for case_id, case in zip(ids, req.cases):
        uploads = urls.put_urls_for_case(req.project, case_id, case.files, now)
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
    account=Depends(require_runner),
    repo=Depends(case_repo),
    records=Depends(case_record_repo),
    store=Depends(storage),
):
    user = account[0]
    if not is_valid_project_name(req.project):
        raise HTTPException(status_code=400, detail="invalid project name")
    if not repo.exists(req.project, case_id):
        raise HTTPException(status_code=404, detail="unknown case")

    now = datetime.datetime.now(datetime.timezone.utc)
    uploaded_at = now.isoformat()
    base = f"cases/{req.project}/{case_id}"
    manifest = {
        "case_id": case_id,
        "solver_family": "openfoam",
        "openfoam_version": req.openfoam_version,
        "uploaded_by": user.email,
        "uploaded_at_utc": uploaded_at,
    }
    store.upload_bytes(f"{base}/manifest.json", json.dumps(manifest).encode())
    store.upload_bytes(f"{base}/READY", uploaded_at.encode())
    result = validate_case(store, req.project, case_id)
    if not result.ok:
        raise HTTPException(
            status_code=400,
            detail=f"case incomplete: {'; '.join(result.errors)}",
        )
    records.upsert(
        CaseRecord(
            case_id=case_id,
            name=(req.name or case_id),
            project=req.project,
            uploaded_by=user.email,
            uploaded_at=now,
            ready=True,
        )
    )
    return {"case_id": case_id, "ready": True}


@router.get("/cases")
def list_cases(account=Depends(require_active), repo=Depends(case_repo)):
    return {
        "cases": [
            {"case_id": case.case_id, "project": case.project, "ready": case.ready}
            for case in repo.list_cases()
        ]
    }
