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


class SubmitReq(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    machine_type: str
    spot: bool = False
    job_name: str


class SetUserReq(BaseModel):
    role: str | None = None
    status: str | None = None
