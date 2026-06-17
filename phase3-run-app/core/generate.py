import datetime
import json
from pathlib import Path
from typing import Any

from str_cad.builder import build_from_schema_file
from str_cad.geometry.assembly import REGION_NAMES
from str_cad.ofcase.build import build_case
from str_cad.ofcase.caseparams import CaseParams
from str_cad.schema import STRParams

from core.case_records import CaseRecord, CaseRecordRepository
from core.cases import CaseRepository
from core.projects import is_valid_project_name
from core.storage import StorageClient
from core.validation import validate_case

DEFAULT_RPM = 90
DEFAULT_OPENFOAM_VERSION = "12"


def build_case_local(
    *,
    prompt: str | None = None,
    params: Any | None = None,
    case_params: Any | None = None,
    gemini_key: str | None = None,
    out_dir: str | Path,
) -> dict:
    str_params = _resolve_str_params(prompt, params, gemini_key)
    resolved_case_params = _resolve_case_params(case_params)
    output_dir = Path(out_dir)
    geometry_root = output_dir / "geo"
    case_dir = output_dir / "case"
    geometry_root.mkdir(parents=True, exist_ok=True)

    params_path = geometry_root / "str-params.json"
    params_path.write_text(
        json.dumps(str_params.model_dump(mode="json"), indent=2)
    )
    build_from_schema_file(params_path, geometry_root)
    build_case(resolved_case_params, geometry_root, case_dir)

    return {
        "str_params": str_params.model_dump(mode="json"),
        "case_params": resolved_case_params.model_dump(mode="json"),
        "case_dir": case_dir,
        "geometry_dir": geometry_root / "geometry",
    }


def read_region_stls(geometry_dir: str | Path) -> dict[str, bytes]:
    geometry_dir = Path(geometry_dir)
    return {
        region: (geometry_dir / f"{region}.stl").read_bytes()
        for region in REGION_NAMES
    }


def commit_case(
    case_dir: str | Path,
    project: str,
    uploaded_by: str,
    *,
    storage: StorageClient,
    case_repo: CaseRepository,
    case_record_repo: CaseRecordRepository,
) -> str:
    if not is_valid_project_name(project):
        raise ValueError("invalid project name")

    source_dir = Path(case_dir)
    if not source_dir.is_dir():
        raise ValueError(f"case directory does not exist: {source_dir}")

    case_id = case_repo.allocate_ids(project, 1)[0]
    now = datetime.datetime.now(datetime.timezone.utc)
    uploaded_at = now.isoformat()
    base = f"cases/{project}/{case_id}"

    for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
        relative_path = source.relative_to(source_dir).as_posix()
        storage.upload_bytes(f"{base}/case/{relative_path}", source.read_bytes())

    manifest = {
        "case_id": case_id,
        "solver_family": "openfoam",
        "openfoam_version": DEFAULT_OPENFOAM_VERSION,
        "uploaded_by": uploaded_by,
        "uploaded_at_utc": uploaded_at,
    }
    storage.upload_bytes(f"{base}/manifest.json", json.dumps(manifest).encode())
    storage.upload_bytes(f"{base}/READY", uploaded_at.encode())

    result = validate_case(storage, project, case_id)
    if not result.ok:
        raise ValueError(f"case incomplete: {'; '.join(result.errors)}")

    case_record_repo.upsert(
        CaseRecord(
            case_id=case_id,
            name=case_id,
            project=project,
            uploaded_by=uploaded_by,
            uploaded_at=now,
            ready=True,
        )
    )
    return case_id


def _resolve_str_params(
    prompt: str | None, params: Any | None, gemini_key: str | None
) -> STRParams:
    if prompt:
        from str_cad.extract import extract_str_params

        return extract_str_params(prompt, api_key=gemini_key)
    if params is not None:
        return STRParams.model_validate(params)
    raise ValueError("prompt or params is required")


def _resolve_case_params(case_params: Any | None) -> CaseParams:
    if case_params is None:
        values = {}
    elif hasattr(case_params, "model_dump"):
        values = case_params.model_dump(mode="python")
    else:
        values = dict(case_params)
    values.setdefault("rpm", DEFAULT_RPM)
    return CaseParams.model_validate(values)
