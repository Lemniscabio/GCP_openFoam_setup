import base64
import copy
import datetime
import tempfile

from fastapi import APIRouter, Depends, HTTPException
from str_cad.ofcase.caseparams import CaseParamsError
from str_cad.schema import SchemaError

from backend.deps import (
    case_record_repo,
    case_repo,
    project_repo,
    storage,
)
from backend.rbac import require_runner
from backend.schemas import (
    GenerateCreateReq,
    GenerateCreateResp,
    GeneratePreviewReq,
    GeneratePreviewResp,
    GenerateVariationsReq,
    GenerateVariationsResp,
)
from core.generate import (
    MAX_VARIATIONS,
    apply_axis_value,
    apply_file_overlays,
    build_case_local,
    commit_case,
    expand_variation_combos,
    overlay_minus_swept,
    read_case_files,
    read_region_stls,
)
from core.projects import is_valid_project_name

router = APIRouter()


@router.post("/generate/preview", response_model=GeneratePreviewResp)
def preview(
    req: GeneratePreviewReq,
    account=Depends(require_runner),
):
    if req.params is None:
        raise HTTPException(status_code=400, detail="params is required")

    try:
        with tempfile.TemporaryDirectory() as out_dir:
            result = build_case_local(
                params=req.params,
                case_params=req.case_params,
                out_dir=out_dir,
            )
            stls = {
                region: base64.b64encode(blob).decode("ascii")
                for region, blob in read_region_stls(
                    result["geometry_dir"]
                ).items()
            }
            return {
                "str_params": result["str_params"],
                "case_params": result["case_params"],
                "stls": stls,
                "files": read_case_files(result["case_dir"]),
            }
    except (SchemaError, CaseParamsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate/create", response_model=GenerateCreateResp)
def create(
    req: GenerateCreateReq,
    account=Depends(require_runner),
    store=Depends(storage),
    repo=Depends(case_repo),
    records=Depends(case_record_repo),
    projects=Depends(project_repo),
):
    user = account[0]
    if not is_valid_project_name(req.project):
        raise HTTPException(status_code=400, detail="invalid project name")

    try:
        with tempfile.TemporaryDirectory() as out_dir:
            result = build_case_local(
                params=req.params,
                case_params=req.case_params,
                out_dir=out_dir,
            )
            apply_file_overlays(result["case_dir"], req.files)
            projects.ensure(
                req.project,
                user.email,
                datetime.datetime.now(datetime.timezone.utc),
            )
            case_id = commit_case(
                result["case_dir"],
                req.project,
                user.email,
                storage=store,
                case_repo=repo,
                case_record_repo=records,
            )
    except (SchemaError, CaseParamsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"case_id": case_id}


@router.post("/generate/variations", response_model=GenerateVariationsResp)
def variations(
    req: GenerateVariationsReq,
    account=Depends(require_runner),
    store=Depends(storage),
    repo=Depends(case_repo),
    records=Depends(case_record_repo),
    projects=Depends(project_repo),
):
    user = account[0]
    if not is_valid_project_name(req.project):
        raise HTTPException(status_code=400, detail="invalid project name")

    combos = expand_variation_combos(req.axes)
    if not combos:
        raise HTTPException(status_code=400, detail="provide at least one variation axis with values")
    if len(combos) > MAX_VARIATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"{len(combos)} variations requested; limit is {MAX_VARIATIONS}",
        )

    # The user's base-case edits carry into every variation, except files the swept
    # axes regenerate (those keep their per-variation value).
    overlay = overlay_minus_swept(req.files, set(req.axes))
    case_ids: list[str] = []
    try:
        projects.ensure(req.project, user.email, datetime.datetime.now(datetime.timezone.utc))
        for combo in combos:
            params = copy.deepcopy(req.params)
            case_params = copy.deepcopy(req.case_params) if req.case_params else {}
            for axis, value in combo.items():
                apply_axis_value(params, case_params, axis, value)
            with tempfile.TemporaryDirectory() as out_dir:
                result = build_case_local(params=params, case_params=case_params, out_dir=out_dir)
                apply_file_overlays(result["case_dir"], overlay)
                case_ids.append(
                    commit_case(
                        result["case_dir"], req.project, user.email,
                        storage=store, case_repo=repo, case_record_repo=records,
                    )
                )
    except (SchemaError, CaseParamsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"case_ids": case_ids}
