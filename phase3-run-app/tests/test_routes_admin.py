import datetime

import pytest

from core.users import UserRecord

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _pending(repo, email):
    repo.upsert(UserRecord(email=email, role=None, status="pending", requested_at=NOW))


def test_admin_lists_users(client, mem_users):
    _pending(mem_users, "new@lemnisca.bio")
    r = client.get("/api/admin/users")
    assert r.status_code == 200
    assert any(u["email"] == "new@lemnisca.bio" for u in r.json()["users"])


def test_admin_approves_user(client, mem_users):
    _pending(mem_users, "new@lemnisca.bio")
    r = client.post("/api/admin/users/new@lemnisca.bio", json={"role": "runner", "status": "active"})
    assert r.status_code == 200
    rec = mem_users.get("new@lemnisca.bio")
    assert rec.role == "runner" and rec.status == "active"
    assert rec.decided_by == "dev@lemnisca.bio"


def test_cannot_disable_self(client, mem_users):
    mem_users.upsert(UserRecord(email="dev@lemnisca.bio", role="admin", status="active", requested_at=NOW))
    r = client.post("/api/admin/users/dev@lemnisca.bio", json={"status": "disabled"})
    assert r.status_code == 400


def test_cannot_demote_self(client, mem_users):
    mem_users.upsert(UserRecord(email="dev@lemnisca.bio", role="admin", status="active", requested_at=NOW))
    r = client.post("/api/admin/users/dev@lemnisca.bio", json={"role": "runner"})
    assert r.status_code == 400


def test_cannot_demote_or_disable_seed_admin(client, mem_users):
    mem_users.upsert(
        UserRecord(
            email="kartikey.attri@lemnisca.bio",
            role="admin",
            status="active",
            requested_at=NOW,
        )
    )
    demote = client.post("/api/admin/users/kartikey.attri@lemnisca.bio", json={"role": "viewer"})
    disable = client.post("/api/admin/users/kartikey.attri@lemnisca.bio", json={"status": "disabled"})
    assert demote.status_code == 400
    assert disable.status_code == 400


def test_unknown_user_404(client):
    r = client.post("/api/admin/users/ghost@lemnisca.bio", json={"role": "viewer", "status": "active"})
    assert r.status_code == 404


@pytest.mark.parametrize("body", [{"role": "owner"}, {"status": "blocked"}])
def test_bad_role_or_status_400(client, mem_users, body):
    _pending(mem_users, "new@lemnisca.bio")
    r = client.post("/api/admin/users/new@lemnisca.bio", json=body)
    assert r.status_code == 400


def test_non_admin_forbidden(client, mem_users):
    # override current_account to a viewer for this test
    from backend import rbac
    from backend.auth import User
    from backend.main import app

    app.dependency_overrides[rbac.current_account] = lambda: (
        User(email="v@lemnisca.bio", sub="v"),
        UserRecord(email="v@lemnisca.bio", role="viewer", status="active", requested_at=NOW),
    )
    r = client.get("/api/admin/users")
    assert r.status_code == 403
    app.dependency_overrides.pop(rbac.current_account, None)


def test_admin_runs_all_and_by_user(client, mem_runs):
    from core.run_repo import RunRecord

    def make_run(job, submitted_by):
        return RunRecord(
            batch_job_id=job,
            job_name=job,
            submitted_by=submitted_by,
            submitted_at=NOW,
            region="us-central1",
            machine_type="c2d-highcpu-8",
            mpi_ranks=4,
            spot=False,
            case_ids=["case_0006"],
            case_names=["WT"],
            project="turbine",
        )

    mem_runs.create(make_run("phoenix", "k@lemnisca.bio"))
    mem_runs.create(make_run("otter", "g@lemnisca.bio"))
    all_runs = client.get("/api/admin/runs").json()["runs"]
    assert {run["batch_job_id"] for run in all_runs} == {"phoenix", "otter"}
    user_runs = client.get("/api/admin/runs?user=k@lemnisca.bio").json()["runs"]
    assert [run["batch_job_id"] for run in user_runs] == ["phoenix"]


def test_admin_runs_forbidden_for_non_admin(client, mem_runs):
    from backend import rbac
    from backend.auth import User
    from backend.main import app

    app.dependency_overrides[rbac.current_account] = lambda: (
        User(email="v@lemnisca.bio", sub="v"),
        UserRecord(
            email="v@lemnisca.bio",
            role="viewer",
            status="active",
            requested_at=datetime.datetime.now(datetime.timezone.utc),
        ),
    )
    assert client.get("/api/admin/runs").status_code == 403
    app.dependency_overrides.pop(rbac.current_account, None)
