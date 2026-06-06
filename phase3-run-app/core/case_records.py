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
    project: str = ""


class CaseRecordRepository(Protocol):
    def upsert(self, record: CaseRecord) -> None: ...
    def get(self, case_id: str) -> CaseRecord | None: ...
    def list_all(self) -> list["CaseRecord"]: ...
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

    def list_all(self) -> list[CaseRecord]:
        return sorted(self._cases.values(), key=lambda case: case.case_id)

    def names_for(self, case_ids: list[str]) -> list[str]:
        out = []
        for cid in case_ids:
            rec = self._cases.get(cid)
            out.append(rec.name if rec else cid)
        return out


class FirestoreCaseRecordRepository:
    """Production CaseRecordRepository backed by Firestore."""

    COLLECTION = "of_cases"

    def __init__(self, client, collection: str = COLLECTION) -> None:
        self._c = client
        self._col = collection

    def _doc(self, case_id: str):
        return self._c.collection(self._col).document(case_id)

    def upsert(self, record: CaseRecord) -> None:
        self._doc(record.case_id).set(
            {
                "case_id": record.case_id,
                "name": record.name,
                "uploaded_by": record.uploaded_by,
                "uploaded_at": record.uploaded_at,
                "ready": record.ready,
                "project": record.project,
            },
            merge=True,
        )

    def get(self, case_id: str) -> CaseRecord | None:
        snap = self._doc(case_id).get()
        if not snap.exists:
            return None
        d = snap.to_dict()
        return CaseRecord(
            case_id=d["case_id"], name=d.get("name", d["case_id"]),
            uploaded_by=d.get("uploaded_by", "unknown"),
            uploaded_at=d.get("uploaded_at"), ready=d.get("ready", False),
            project=d.get("project", ""),
        )

    def list_all(self) -> list[CaseRecord]:
        out = []
        for snap in self._c.collection(self._col).stream():
            d = snap.to_dict()
            out.append(
                CaseRecord(
                    case_id=d["case_id"],
                    name=d.get("name", d["case_id"]),
                    uploaded_by=d.get("uploaded_by", "unknown"),
                    uploaded_at=d.get("uploaded_at"),
                    ready=d.get("ready", False),
                    project=d.get("project", ""),
                )
            )
        return sorted(out, key=lambda case: case.case_id)

    def names_for(self, case_ids: list[str]) -> list[str]:
        return [(self.get(cid).name if self.get(cid) else cid) for cid in case_ids]
