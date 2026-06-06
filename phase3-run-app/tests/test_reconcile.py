import datetime

from core.reconcile import reconcile_non_terminal
from core.run_repo import InMemoryRunRepository, RunRecord

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _run(repo, job_id, state):
    repo.create(RunRecord(
        batch_job_id=job_id, job_name=job_id, submitted_by="u@lemnisca.bio",
        submitted_at=NOW, region="us-central1", machine_type="c2d-highcpu-8",
        mpi_ranks=4, spot=False, case_ids=["case_0006"], case_names=["c"], state=state,
    ))


def test_deleted_job_marked_cancelled():
    repo = InMemoryRunRepository()
    _run(repo, "gone", "RUNNING")
    changed = reconcile_non_terminal(repo, get_state=lambda jid: None, now=NOW)
    assert changed == 1
    rec = repo.get("gone")
    assert rec.state == "CANCELLED" and rec.finished_at == NOW


def test_terminal_runs_are_skipped_no_batch_call():
    repo = InMemoryRunRepository()
    _run(repo, "done", "SUCCEEDED")
    calls = []

    def spy(jid):
        calls.append(jid)
        return None

    changed = reconcile_non_terminal(repo, get_state=spy, now=NOW)
    assert changed == 0
    assert calls == []  # terminal -> never queried
    assert repo.get("done").state == "SUCCEEDED"


def test_live_state_synced_when_event_was_missed():
    repo = InMemoryRunRepository()
    _run(repo, "j", "SCHEDULED")
    changed = reconcile_non_terminal(repo, get_state=lambda jid: "SUCCEEDED", now=NOW)
    assert changed == 1
    rec = repo.get("j")
    assert rec.state == "SUCCEEDED" and rec.finished_at == NOW


def test_deletion_in_progress_is_not_terminal_and_resolves_to_cancelled():
    # Batch emits DELETION_IN_PROGRESS while deleting; it must NOT be treated as
    # terminal, or reconcile would skip it and the run would freeze there forever.
    from core.run_repo import TERMINAL_STATES
    assert "DELETION_IN_PROGRESS" not in TERMINAL_STATES
    repo = InMemoryRunRepository()
    _run(repo, "deleting", "DELETION_IN_PROGRESS")
    changed = reconcile_non_terminal(repo, get_state=lambda jid: None, now=NOW)
    assert changed == 1
    assert repo.get("deleting").state == "CANCELLED"


def test_unchanged_when_state_matches():
    repo = InMemoryRunRepository()
    _run(repo, "j", "RUNNING")
    changed = reconcile_non_terminal(repo, get_state=lambda jid: "RUNNING", now=NOW)
    assert changed == 0
    assert repo.get("j").state == "RUNNING"
