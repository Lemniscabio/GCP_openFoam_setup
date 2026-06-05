import datetime

from core.run_repo import TERMINAL_STATES


def reconcile_non_terminal(run_repo, get_state, now: datetime.datetime) -> int:
    """Backstop for Batch -> Pub/Sub: deletions emit no notification, so a deleted
    job's of_runs doc would stay stuck at its last live state forever.

    For each run NOT already in a terminal state, query Batch via
    `get_state(batch_job_id)`:
      - returns None  -> the job no longer exists (deleted) -> mark CANCELLED.
      - returns a state that differs from the record -> sync it (covers any
        Pub/Sub event we missed). update_state is monotonic, so terminal states
        are never regressed.

    Terminal runs are skipped (no Batch call). Returns the number of runs changed.
    """
    changed = 0
    for run in run_repo.list_recent():
        if run.state in TERMINAL_STATES:
            continue
        state = get_state(run.batch_job_id)
        if state is None:
            run_repo.update_state(run.batch_job_id, "CANCELLED", finished_at=now)
            changed += 1
        elif state != run.state:
            finished = now if state in TERMINAL_STATES else None
            run_repo.update_state(run.batch_job_id, state, finished_at=finished)
            changed += 1
    return changed
