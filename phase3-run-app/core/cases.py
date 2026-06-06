import re
from dataclasses import dataclass
from core.storage import StorageClient

_CASE_RE = re.compile(r"^case_(\d+)$")

@dataclass
class CaseInfo:
    project: str
    case_id: str
    ready: bool

class CaseRepository:
    def __init__(self, storage: StorageClient) -> None:
        self._s = storage

    def _max_existing(self) -> int:
        max_n = 0
        for cid in self._s.list_case_ids():
            m = _CASE_RE.match(cid)
            if m:
                max_n = max(max_n, int(m.group(1)))
        return max_n

    def allocate_ids(self, project: str, count: int) -> list[str]:
        """Atomically reserve `count` fresh case ids. Robust to empty buckets and
        concurrent allocators: each id is claimed via a create-only marker, and a
        claim that loses the race simply advances to the next number."""
        n = self._max_existing()
        out: list[str] = []
        while len(out) < count:
            n += 1
            cid = f"case_{n:04d}"
            if self._s.create_exclusive(f"cases/{project}/{cid}/.reserved", b""):
                out.append(cid)
        return out

    def exists(self, project: str, case_id: str) -> bool:
        base = f"cases/{project}/{case_id}"
        return self._s.object_exists(f"{base}/READY") or self._s.object_exists(
            f"{base}/.reserved"
        )

    def list_cases(self) -> list[CaseInfo]:
        cases = set()
        for path in self._s.list_paths("cases/"):
            parts = path.split("/")
            if len(parts) >= 4 and parts[1] and parts[2]:
                cases.add((parts[1], parts[2]))
        return [
            CaseInfo(
                project=project,
                case_id=case_id,
                ready=self._s.object_exists(f"cases/{project}/{case_id}/READY"),
            )
            for project, case_id in sorted(cases)
        ]
