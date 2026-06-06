import datetime

from core.projects import (
    InMemoryProjectRepository,
    ProjectRecord,
    is_valid_project_name,
)

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def test_is_valid_project_name():
    assert is_valid_project_name("turbine-study")
    assert is_valid_project_name("Project_A")
    assert not is_valid_project_name("")
    assert not is_valid_project_name("a/b")
    assert not is_valid_project_name(".")
    assert not is_valid_project_name("..")
    assert not is_valid_project_name(" lead")
    assert not is_valid_project_name("x" * 129)
    assert not is_valid_project_name("bad\nname")


def test_ensure_creates_then_returns_existing():
    repo = InMemoryProjectRepository()
    a = repo.ensure("turbine", "k@lemnisca.bio", NOW)
    assert a.name == "turbine" and a.created_by == "k@lemnisca.bio"
    later = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    b = repo.ensure("turbine", "other@lemnisca.bio", later)
    assert b.created_by == "k@lemnisca.bio" and b.created_at == NOW


def test_get_and_list():
    repo = InMemoryProjectRepository()
    repo.ensure("a", "u@lemnisca.bio", NOW)
    repo.ensure("b", "u@lemnisca.bio", NOW)
    assert repo.get("a").name == "a"
    assert repo.get("missing") is None
    assert sorted(p.name for p in repo.list_all()) == ["a", "b"]
