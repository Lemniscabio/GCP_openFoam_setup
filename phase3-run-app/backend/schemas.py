from pydantic import BaseModel, Field


class CaseUpload(BaseModel):
    files: list[str] = Field(min_length=1)


class AllocateReq(BaseModel):
    project: str
    cases: list[CaseUpload] = Field(min_length=1, max_length=200)


class FinalizeReq(BaseModel):
    openfoam_version: str = "12"
    name: str | None = None
    project: str


class GeneratePreviewReq(BaseModel):
    params: dict | None = None
    case_params: dict | None = None


class GeneratePreviewResp(BaseModel):
    str_params: dict
    case_params: dict
    stls: dict[str, str]
    files: dict[str, str] = {}  # generated OpenFOAM text files (relpath -> content)


class GenerateCreateReq(BaseModel):
    project: str
    params: dict
    case_params: dict | None = None
    files: dict[str, str] | None = None  # user-edited file overlays applied before commit


class GenerateCreateResp(BaseModel):
    case_id: str


class SubmitReq(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    machine_type: str
    spot: bool = False
    job_name: str


class SetUserReq(BaseModel):
    role: str | None = None
    status: str | None = None
