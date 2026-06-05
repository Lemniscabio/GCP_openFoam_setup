from pydantic import BaseModel, Field


class CaseUpload(BaseModel):
    files: list[str] = Field(min_length=1)


class AllocateReq(BaseModel):
    cases: list[CaseUpload] = Field(min_length=1, max_length=200)


class FinalizeReq(BaseModel):
    openfoam_version: str = "12"
    name: str | None = None


class SubmitReq(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    machine_type: str
    spot: bool = False
