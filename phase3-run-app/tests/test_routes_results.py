import datetime as _dt

from core.run_repo import RunRecord

NOW = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)


def _run(repo, job="phoenix", project="turbine"):
    repo.create(
        RunRecord(
            batch_job_id=job,
            job_name=job,
            submitted_by="k@lemnisca.bio",
            submitted_at=NOW,
            region="us-central1",
            machine_type="c2d-highcpu-8",
            mpi_ranks=4,
            spot=False,
            case_ids=["case_0006"],
            case_names=["WT"],
            state="SUCCEEDED",
            project=project,
        )
    )


def test_results_lists_runs(client, mem_runs):
    _run(mem_runs)
    response = client.get("/api/results")
    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["codename"] == "phoenix"
    assert item["project"] == "turbine"
    assert item["case_ids"] == ["case_0006"]


def test_results_files_lists_case(client, mem_storage):
    mem_storage.upload_bytes(
        "results/turbine/phoenix/case_0006/result.tar.gz", b"abcd"
    )
    response = client.get(
        "/api/results/files?project=turbine&job=phoenix&case=case_0006"
    )
    assert response.status_code == 200
    assert {"name": "result.tar.gz", "size": 4} in response.json()["files"]


def test_downloads_signs_results_only(client, mem_storage):
    mem_storage.upload_bytes(
        "results/turbine/phoenix/case_0006/result.tar.gz", b"abcd"
    )
    response = client.post(
        "/api/results/downloads",
        json={
            "objects": [
                "results/turbine/phoenix/case_0006/result.tar.gz",
                "results/turbine/phoenix/case_0006/missing.txt",
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["downloads"]) == 1
    assert body["downloads"][0]["object"].endswith("result.tar.gz")
    assert "missing.txt" in body["missing"][0]


def test_downloads_rejects_non_results_path(client):
    response = client.post(
        "/api/results/downloads",
        json={"objects": ["cases/turbine/case_0006/x"]},
    )
    assert response.status_code == 400
