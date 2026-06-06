import datetime

from core.run_repo import FirestoreRunRepository, RunRecord, InMemoryRunRepository


def _rec(job_id="of-multi-x-20260101", state="SUBMITTED"):
    return RunRecord(
        batch_job_id=job_id,
        job_name="windtunnel-v3",
        project="turbine",
        submitted_by="kartikey.attri@lemnisca.bio",
        submitted_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        region="us-central1",
        machine_type="c2d-highcpu-32",
        mpi_ranks=16,
        spot=False,
        case_ids=["case_0006"],
        case_names=["Wind Tunnel v3"],
        state=state,
        finished_at=None,
    )


def test_create_then_get():
    repo = InMemoryRunRepository()
    repo.create(_rec())
    got = repo.get("of-multi-x-20260101")
    assert got.job_name == "windtunnel-v3"
    assert got.state == "SUBMITTED"
    assert got.project == "turbine"


def test_list_orders_newest_first():
    repo = InMemoryRunRepository()
    repo.create(_rec(job_id="a", state="SUBMITTED"))
    later = _rec(job_id="b")
    later.submitted_at = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    repo.create(later)
    ids = [r.batch_job_id for r in repo.list_recent(limit=10)]
    assert ids == ["b", "a"]


def test_update_state_sets_finished_at_on_terminal():
    repo = InMemoryRunRepository()
    repo.create(_rec())
    fin = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    repo.update_state("of-multi-x-20260101", "SUCCEEDED", finished_at=fin)
    got = repo.get("of-multi-x-20260101")
    assert got.state == "SUCCEEDED"
    assert got.finished_at == fin


def test_update_state_is_monotonic_never_regresses_terminal():
    repo = InMemoryRunRepository()
    repo.create(_rec())
    repo.update_state("of-multi-x-20260101", "SUCCEEDED", finished_at=None)
    repo.update_state("of-multi-x-20260101", "RUNNING", finished_at=None)  # late/duplicate
    assert repo.get("of-multi-x-20260101").state == "SUCCEEDED"


def test_get_missing_returns_none():
    assert InMemoryRunRepository().get("nope") is None


def test_try_reserve_is_exclusive():
    repo = InMemoryRunRepository()
    assert repo.try_reserve(_rec(job_id="phoenix")) is True
    # second reservation of the same id fails
    assert repo.try_reserve(_rec(job_id="phoenix")) is False


def test_existing_ids():
    repo = InMemoryRunRepository()
    repo.try_reserve(_rec(job_id="phoenix"))
    repo.try_reserve(_rec(job_id="otter"))
    assert repo.existing_ids() == {"phoenix", "otter"}


def test_firestore_shape_round_trip_includes_project():
    got = FirestoreRunRepository._from_dict({
        **_rec().__dict__,
        "project": "turbine",
    })
    assert got.project == "turbine"


def test_list_all_and_by_user():
    repo = InMemoryRunRepository()
    first = _rec(job_id="phoenix")
    first.submitted_by = "k@lemnisca.bio"
    second = _rec(job_id="otter")
    second.submitted_by = "g@lemnisca.bio"
    repo.create(first)
    repo.create(second)
    assert {record.batch_job_id for record in repo.list_all()} == {
        "phoenix",
        "otter",
    }
    assert [
        record.batch_job_id for record in repo.list_by_user("k@lemnisca.bio")
    ] == ["phoenix"]
