import base64
import datetime
import json

from core.run_repo import RunRecord


def _envelope(batch_job_id, state):
    body = {
        "name": f"projects/p/locations/us-central1/jobs/{batch_job_id}",
        "status": {"state": state},
    }
    data = base64.b64encode(json.dumps(body).encode()).decode()
    return {"message": {"data": data, "attributes": {"newJobState": state}}}


def test_event_updates_run_state(internal_client, mem_runs):
    mem_runs.create(
        RunRecord(
            batch_job_id="of-x-1",
            job_name="wt",
            submitted_by="kartikey.attri@lemnisca.bio",
            submitted_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            region="us-central1",
            machine_type="c2d-highcpu-8",
            mpi_ranks=4,
            spot=False,
            case_ids=["case_0006"],
            case_names=["wt"],
        )
    )
    r = internal_client.post(
        "/internal/batch-events",
        json=_envelope("of-x-1", "SUCCEEDED"),
        headers={"Authorization": "Bearer good"},
    )
    assert r.status_code == 204
    rec = mem_runs.get("of-x-1")
    assert rec.state == "SUCCEEDED"
    assert rec.finished_at is not None


def test_unknown_job_id_upserts(internal_client, mem_runs):
    r = internal_client.post(
        "/internal/batch-events",
        json=_envelope("of-new", "RUNNING"),
        headers={"Authorization": "Bearer good"},
    )
    assert r.status_code == 204
    assert mem_runs.get("of-new").state == "RUNNING"


def test_terminal_state_not_regressed(internal_client, mem_runs):
    internal_client.post(
        "/internal/batch-events",
        json=_envelope("of-x-2", "SUCCEEDED"),
        headers={"Authorization": "Bearer good"},
    )
    internal_client.post(
        "/internal/batch-events",
        json=_envelope("of-x-2", "RUNNING"),
        headers={"Authorization": "Bearer good"},
    )
    assert mem_runs.get("of-x-2").state == "SUCCEEDED"


def test_unauthenticated_rejected(internal_client_no_auth):
    r = internal_client_no_auth.post(
        "/internal/batch-events",
        json=_envelope("of-x-1", "RUNNING"),
    )
    assert r.status_code in (401, 403)
