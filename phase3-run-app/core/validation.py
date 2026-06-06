import json
from dataclasses import dataclass, field
from core.storage import StorageClient

@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

# sibling objects (written by finalize / CLI) that must exist under cases/<id>/
_REQUIRED = ["manifest.json", "READY"]

def validate_case(
    storage: StorageClient, project: str, case_id: str
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    base = f"cases/{project}/{case_id}"

    for name in _REQUIRED:
        if not storage.object_exists(f"{base}/{name}"):
            errors.append(f"missing required object: {name}")

    # at least one file under the case/ tree
    if not any(p.startswith(f"{base}/case/") for p in _all_paths(storage)):
        errors.append("missing case/ tree (no case files uploaded)")

    # command.sh lives INSIDE the case tree (so the runtime's tree-rsync brings it down)
    cmd_path = f"{base}/case/command.sh"
    if not storage.object_exists(cmd_path):
        errors.append("missing case/command.sh")
    else:
        cmd = storage.read_text(cmd_path)
        if "MPI_RANKS" not in cmd:
            warnings.append("command.sh does not reference MPI_RANKS (hardcoded -np?)")

    meta_path = f"{base}/case/metadata.json"
    if not storage.object_exists(meta_path):
        errors.append("missing case/metadata.json")
    else:
        try:
            json.loads(storage.read_text(meta_path))
        except Exception:  # noqa: BLE001
            errors.append("case/metadata.json is not valid JSON")

    return ValidationResult(ok=(len(errors) == 0), errors=errors, warnings=warnings)

def _all_paths(storage: StorageClient) -> list[str]:
    return storage.list_paths("cases/")
