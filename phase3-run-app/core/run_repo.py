import datetime
from dataclasses import dataclass
from typing import Protocol

# Batch job states considered terminal (no further transitions expected).
# NOTE: DELETION_IN_PROGRESS is deliberately NOT terminal — it's a transient state
# Batch emits while deleting a job. Treating it as terminal froze deleted runs there
# forever (reconcile skips terminal runs). Left non-terminal, reconcile sees the job
# vanish from Batch and resolves it to CANCELLED.
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


@dataclass
class RunRecord:
    batch_job_id: str          # doc id
    job_name: str
    submitted_by: str
    submitted_at: datetime.datetime
    region: str
    machine_type: str
    mpi_ranks: int
    spot: bool
    case_ids: list[str]
    case_names: list[str]
    state: str = "SUBMITTED"
    finished_at: datetime.datetime | None = None


class RunRepository(Protocol):
    def create(self, record: RunRecord) -> None: ...
    def get(self, batch_job_id: str) -> RunRecord | None: ...
    def list_recent(self, limit: int = 50) -> list[RunRecord]: ...
    def update_state(
        self, batch_job_id: str, state: str,
        finished_at: datetime.datetime | None = None,
    ) -> None:
        """Advance a run's state. Idempotent: a record already in a terminal state
        is never moved back to a non-terminal one (handles late/duplicate events).
        Upserts a minimal record if the id is unknown."""
        ...


class InMemoryRunRepository:
    """Test fake. Stores RunRecords in a dict keyed by batch_job_id."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create(self, record: RunRecord) -> None:
        self._runs[record.batch_job_id] = record

    def get(self, batch_job_id: str) -> RunRecord | None:
        return self._runs.get(batch_job_id)

    def list_recent(self, limit: int = 50) -> list[RunRecord]:
        ordered = sorted(self._runs.values(), key=lambda r: r.submitted_at, reverse=True)
        return ordered[:limit]

    def update_state(self, batch_job_id, state, finished_at=None) -> None:
        rec = self._runs.get(batch_job_id)
        if rec is None:
            # unknown id: upsert a minimal placeholder so the event is not lost
            rec = RunRecord(
                batch_job_id=batch_job_id, job_name=batch_job_id,
                submitted_by="unknown",
                submitted_at=datetime.datetime.now(datetime.timezone.utc),
                region="", machine_type="", mpi_ranks=0, spot=False,
                case_ids=[], case_names=[],
            )
            self._runs[batch_job_id] = rec
        if rec.state in TERMINAL_STATES and state not in TERMINAL_STATES:
            return  # never regress a terminal state
        rec.state = state
        if finished_at is not None:
            rec.finished_at = finished_at


class FirestoreRunRepository:
    """Production RunRepository backed by Firestore Native mode."""

    COLLECTION = "of_runs"

    def __init__(self, client, collection: str = COLLECTION) -> None:
        self._c = client
        self._col = collection

    def _doc(self, batch_job_id: str):
        return self._c.collection(self._col).document(batch_job_id)

    def create(self, record: RunRecord) -> None:
        self._doc(record.batch_job_id).set(
            {
                "batch_job_id": record.batch_job_id,
                "job_name": record.job_name,
                "submitted_by": record.submitted_by,
                "submitted_at": record.submitted_at,
                "region": record.region,
                "machine_type": record.machine_type,
                "mpi_ranks": record.mpi_ranks,
                "spot": record.spot,
                "case_ids": record.case_ids,
                "case_names": record.case_names,
                "state": record.state,
                "finished_at": record.finished_at,
            }
        )

    def get(self, batch_job_id: str) -> RunRecord | None:
        snap = self._doc(batch_job_id).get()
        if not snap.exists:
            return None
        return self._from_dict(snap.to_dict())

    def list_recent(self, limit: int = 50) -> list[RunRecord]:
        from google.cloud.firestore import Query  # type: ignore
        q = (
            self._c.collection(self._col)
            .order_by("submitted_at", direction=Query.DESCENDING)
            .limit(limit)
        )
        return [self._from_dict(d.to_dict()) for d in q.stream()]

    def update_state(self, batch_job_id, state, finished_at=None) -> None:
        from google.cloud import firestore  # type: ignore

        @firestore.transactional
        def _txn(txn):
            ref = self._doc(batch_job_id)
            snap = ref.get(transaction=txn)
            cur = snap.to_dict() if snap.exists else None
            if cur and cur.get("state") in TERMINAL_STATES and state not in TERMINAL_STATES:
                return
            data = {"state": state}
            if finished_at is not None:
                data["finished_at"] = finished_at
            if not snap.exists:
                data["batch_job_id"] = batch_job_id
                data["job_name"] = batch_job_id
            txn.set(ref, data, merge=True)

        _txn(self._c.transaction())

    @staticmethod
    def _from_dict(d: dict) -> RunRecord:
        return RunRecord(
            batch_job_id=d["batch_job_id"],
            job_name=d.get("job_name", d["batch_job_id"]),
            submitted_by=d.get("submitted_by", "unknown"),
            submitted_at=d.get("submitted_at"),
            region=d.get("region", ""),
            machine_type=d.get("machine_type", ""),
            mpi_ranks=d.get("mpi_ranks", 0),
            spot=d.get("spot", False),
            case_ids=d.get("case_ids", []),
            case_names=d.get("case_names", []),
            state=d.get("state", "SUBMITTED"),
            finished_at=d.get("finished_at"),
        )
