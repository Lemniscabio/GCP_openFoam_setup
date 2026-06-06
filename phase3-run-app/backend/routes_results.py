import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.deps import run_repo, storage, url_service
from backend.rbac import require_active
from core.results_paths import results_prefix

router = APIRouter()


class DownloadsReq(BaseModel):
    objects: list[str]


@router.get("/results")
def list_results(account=Depends(require_active), runs=Depends(run_repo)):
    return {
        "results": [
            {
                "codename": run.batch_job_id,
                "project": run.project,
                "state": run.state,
                "case_ids": run.case_ids,
                "case_names": run.case_names,
                "submitted_by": run.submitted_by,
                "submitted_at": str(run.submitted_at),
            }
            for run in runs.list_all()
        ]
    }


@router.get("/results/files")
def result_files(
    project: str,
    job: str,
    case: str,
    account=Depends(require_active),
    store=Depends(storage),
):
    prefix = results_prefix(project, job, case)
    files = [
        {"name": name[len(prefix):], "size": size}
        for name, size in store.list_objects(prefix)
        if name != prefix
    ]
    return {"files": files}


@router.post("/results/downloads")
def downloads(
    req: DownloadsReq,
    account=Depends(require_active),
    store=Depends(storage),
    urls=Depends(url_service),
):
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    missing = []
    for obj in req.objects:
        if not obj.startswith("results/"):
            raise HTTPException(status_code=400, detail=f"invalid object: {obj}")
        if not store.object_exists(obj):
            missing.append(obj)
            continue
        out.append({"object": obj, "url": urls.get_url(obj, now)})
    return {"downloads": out, "missing": missing}
