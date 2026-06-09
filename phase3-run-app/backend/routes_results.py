import datetime
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.deps import run_repo, storage, url_service
from backend.rbac import require_active
from core.archives import build_zip
from core.results_paths import results_prefix

router = APIRouter()
_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class DownloadsReq(BaseModel):
    objects: list[str]


class ArchiveReq(BaseModel):
    project: str
    job: str
    case: str | None = None


def _validated_archive_prefix(req: ArchiveReq) -> tuple[str, str]:
    components = [req.project, req.job]
    if req.case is not None:
        components.append(req.case)
    if any(".." in value for value in components) or not all(
        _PATH_COMPONENT.fullmatch(value) for value in components
    ):
        raise HTTPException(status_code=400, detail="invalid result path component")
    base_prefix = f"results/{req.project}/{req.job}/"
    source_prefix = f"{base_prefix}{req.case}/" if req.case else base_prefix
    return base_prefix, source_prefix


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
        basename = obj.rsplit("/", 1)[-1]
        disposition = f'attachment; filename="{basename}"'
        out.append({
            "object": obj,
            "url": urls.get_url(obj, now, disposition=disposition),
        })
    return {"downloads": out, "missing": missing}


@router.post("/results/archive")
def archive_results(
    req: ArchiveReq,
    account=Depends(require_active),
    store=Depends(storage),
    urls=Depends(url_service),
):
    base_prefix, source_prefix = _validated_archive_prefix(req)
    entries = [
        (object_path[len(base_prefix):], object_path)
        for object_path, _size in store.list_objects(source_prefix)
        if object_path != source_prefix and object_path[len(base_prefix):]
    ]
    if not entries:
        raise HTTPException(status_code=404, detail="no result objects found")

    dest_path = f"downloads/{req.job}/{uuid.uuid4().hex}.zip"
    # This synchronous stream-through build may approach Cloud Run's request timeout
    # for very large jobs; async archive creation is intentionally deferred.
    missing = build_zip(store, dest_path, entries)
    name = f"{req.case}.zip" if req.case else f"{req.job}.zip"
    now = datetime.datetime.now(datetime.timezone.utc)
    disposition = f'attachment; filename="{name}"'
    return {
        "url": urls.get_url(dest_path, now, disposition=disposition),
        "missing": missing,
    }
