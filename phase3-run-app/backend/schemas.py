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


class ChatMessage(BaseModel):
    role: str  # "user" | "model"
    content: str


class GeometryChatReq(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


class GeometryChatResp(BaseModel):
    reply: str
    spec: dict | None = None  # non-null when a complete, validated spec is ready


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


class GenerateVariationsReq(BaseModel):
    project: str
    params: dict
    case_params: dict | None = None
    files: dict[str, str] | None = None     # edited base files, carried into every variation
    axes: dict[str, list[float]]            # e.g. {"rpm": [50,100], "viscosity_m2_s": [1e-6]}


class GenerateVariationsResp(BaseModel):
    case_ids: list[str]


class SubmitReq(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    machine_type: str
    spot: bool = False
    job_name: str


class SetUserReq(BaseModel):
    role: str | None = None
    status: str | None = None
