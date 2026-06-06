def test_me_returns_role_and_status(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "dev@lemnisca.bio"
    assert body["role"] == "admin"
    assert body["status"] == "active"


def test_me_runs_returns_only_my_runs(client, mem_runs):
    import datetime as _dt

    from core.run_repo import RunRecord

    def mk(job, who):
        return RunRecord(
            batch_job_id=job,
            job_name=job,
            submitted_by=who,
            submitted_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
            region="us-central1",
            machine_type="c2d-highcpu-8",
            mpi_ranks=4,
            spot=False,
            case_ids=["case_0006"],
            case_names=["WT"],
            project="turbine",
        )

    mem_runs.create(mk("phoenix", "dev@lemnisca.bio"))
    mem_runs.create(mk("otter", "someone@lemnisca.bio"))
    r = client.get("/api/me/runs")
    assert r.status_code == 200
    assert [x["batch_job_id"] for x in r.json()["runs"]] == ["phoenix"]
