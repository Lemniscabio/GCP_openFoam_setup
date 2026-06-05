import datetime

from core.users import (
    UserRecord, InMemoryUserRepository, resolve_on_login,
)

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
SEED = ["kartikey.attri@lemnisca.bio"]


def test_resolve_seed_admin_is_active_admin():
    rec = resolve_on_login("kartikey.attri@lemnisca.bio", SEED, None, NOW)
    assert rec.role == "admin" and rec.status == "active"


def test_resolve_new_user_is_pending():
    rec = resolve_on_login("new@lemnisca.bio", SEED, None, NOW)
    assert rec.status == "pending" and rec.role is None
    assert rec.requested_at == NOW


def test_resolve_existing_user_unchanged():
    existing = UserRecord(email="x@lemnisca.bio", role="viewer", status="active",
                          requested_at=NOW, decided_by="a@b", decided_at=NOW)
    assert resolve_on_login("x@lemnisca.bio", SEED, existing, NOW) == existing


def test_repo_upsert_get_list():
    repo = InMemoryUserRepository()
    repo.upsert(resolve_on_login("new@lemnisca.bio", SEED, None, NOW))
    assert repo.get("new@lemnisca.bio").status == "pending"
    assert [u.email for u in repo.list_all()] == ["new@lemnisca.bio"]


def test_set_decision_updates_role_status_audit():
    repo = InMemoryUserRepository()
    repo.upsert(resolve_on_login("new@lemnisca.bio", SEED, None, NOW))
    repo.set_decision("new@lemnisca.bio", role="runner", status="active",
                      decided_by="kartikey.attri@lemnisca.bio", now=NOW)
    rec = repo.get("new@lemnisca.bio")
    assert rec.role == "runner" and rec.status == "active"
    assert rec.decided_by == "kartikey.attri@lemnisca.bio" and rec.decided_at == NOW
