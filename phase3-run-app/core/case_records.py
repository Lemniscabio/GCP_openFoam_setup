import datetime
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CaseRecord:
    case_id: str          # doc id
    name: str
    uploaded_by: str
    uploaded_at: datetime.datetime
    ready: bool = False


class CaseRecordRepository(Protocol):
    def upsert(self, record: CaseRecord) -> None: ...
    def get(self, case_id: str) -> CaseRecord | None: ...
    def names_for(self, case_ids: list[str]) -> list[str]:
        """Return the friendly name for each id, falling back to the id itself
        when no record exists."""
        ...


class InMemoryCaseRecordRepository:
    """Test fake."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}

    def upsert(self, record: CaseRecord) -> None:
        self._cases[record.case_id] = record

    def get(self, case_id: str) -> CaseRecord | None:
        return self._cases.get(case_id)

    def names_for(self, case_ids: list[str]) -> list[str]:
        out = []
        for cid in case_ids:
            rec = self._cases.get(cid)
            out.append(rec.name if rec else cid)
        return out
