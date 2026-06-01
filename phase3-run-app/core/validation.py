from dataclasses import dataclass, field
from core.storage import StorageClient

@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

# objects that must exist under cases/<id>/
_REQUIRED = ["command.sh", "manifest.json", "READY"]

def validate_case(storage: StorageClient, case_id: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    base = f"cases/{case_id}"

    for name in _REQUIRED:
        if not storage.object_exists(f"{base}/{name}"):
            errors.append(f"missing required object: {name}")

    # at least one file under the case/ tree
    if not any(p.startswith(f"{base}/case/") for p in _all_paths(storage)):
        errors.append("missing case/ tree (no case files uploaded)")

    if storage.object_exists(f"{base}/command.sh"):
        cmd = storage.read_text(f"{base}/command.sh")
        if "MPI_RANKS" not in cmd:
            warnings.append("command.sh does not reference MPI_RANKS (hardcoded -np?)")

    return ValidationResult(ok=(len(errors) == 0), errors=errors, warnings=warnings)

def _all_paths(storage: StorageClient) -> list[str]:
    # InMemoryStorage exposes _objs; GcsStorage implements list_paths(prefix)
    if hasattr(storage, "_objs"):
        return list(storage._objs.keys())  # type: ignore[attr-defined]
    return storage.list_paths("cases/")  # type: ignore[attr-defined]
