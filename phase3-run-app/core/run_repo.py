import datetime
from dataclasses import dataclass
from typing import Protocol

# Batch job states considered terminal (no further transitions expected).
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "DELETION_IN_PROGRESS", "CANCELLED"}


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
