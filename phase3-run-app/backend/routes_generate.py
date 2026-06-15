import base64
import datetime
import tempfile

from fastapi import APIRouter, Depends, HTTPException
from google.genai.errors import APIError
from str_cad.ofcase.caseparams import CaseParamsError
from str_cad.schema import SchemaError

from backend.deps import (
    case_record_repo,
    case_repo,
    gemini_api_key,
    project_repo,
    storage,
)
from backend.rbac import require_runner
from backend.schemas import (
    GenerateCreateReq,
    GenerateCreateResp,
    GeneratePreviewReq,
    GeneratePreviewResp,
)
from core.generate import build_case_local, commit_case, read_region_stls
from core.projects import is_valid_project_name

router = APIRouter()


@router.post("/generate/preview", response_model=GeneratePreviewResp)
def preview(
    req: GeneratePreviewReq,
    account=Depends(require_runner),
    gemini_key=Depends(gemini_api_key),
):
    if (req.prompt is None) == (req.params is None):
        raise HTTPException(
            status_code=400,
            detail="exactly one of prompt or params is required",
        )

    try:
        with tempfile.TemporaryDirectory() as out_dir:
            result = build_case_local(
                prompt=req.prompt,
                params=req.params,
                case_params=req.case_params,
                gemini_key=gemini_key,
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
            }
    except (SchemaError, CaseParamsError, APIError, ValueError) as exc:
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
