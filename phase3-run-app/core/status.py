import re
from dataclasses import dataclass

_TS_RE = re.compile(r"/processor\d+/(\d+(?:\.\d+)?)/")


def sim_progress_pct(latest_time: float, end_time: float):
    if not end_time or end_time <= 0:
        return None
    return int(max(0.0, min(1.0, latest_time / end_time)) * 100)


def parse_checkpoint_latest_timestep(paths: list[str]) -> float | None:
    times = [float(m.group(1)) for p in paths for m in [_TS_RE.search(p)] if m]
    return max(times) if times else None


@dataclass
class RunSummary:
    job_name: str
    state: str
    case_ids: list[str]
    progress_pct: int | None


class RunStatusService:
    """`batch_client`: batch_v1.BatchServiceClient; `storage`: core StorageClient."""

    def __init__(self, batch_client, storage, project_id: str, region: str) -> None:
        self._b = batch_client
        self._s = storage
        self._parent = f"projects/{project_id}/locations/{region}"

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        jobs = list(self._b.list_jobs(parent=self._parent))
        jobs.sort(
            key=lambda j: j.create_time.timestamp() if j.create_time else 0,
            reverse=True,
        )
        out = []
        for j in jobs[:limit]:
            name = j.name.split("/")[-1]
            out.append(
                RunSummary(
                    job_name=name,
                    state=j.status.state.name,
                    case_ids=[],
                    progress_pct=None,
                )
            )
        return out

    def get_status(self, job_name: str, case_id: str, variant: str) -> dict:
        full = f"{self._parent}/jobs/{job_name}"
        j = self._b.get_job(name=full)
        events = [
            {"time": str(e.event_time), "desc": e.description}
            for e in j.status.status_events
        ]
        cps = self._s.list_paths(f"checkpoints/{case_id}/{variant}/latest/")
        latest = parse_checkpoint_latest_timestep(cps)
        return {
            "job_name": job_name,
            "state": j.status.state.name,
            "events": events,
            "checkpoint_latest_timestep": latest,
        }
