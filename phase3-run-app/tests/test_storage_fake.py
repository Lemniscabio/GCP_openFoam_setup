from core.storage import InMemoryStorage

def test_create_exclusive_first_wins():
    s = InMemoryStorage()
    assert s.create_exclusive("cases/case_0001/.reserved", b"") is True
    assert s.create_exclusive("cases/case_0001/.reserved", b"") is False  # already exists

def test_object_exists():
    s = InMemoryStorage()
    s.upload_bytes("cases/case_0001/READY", b"x")
    assert s.object_exists("cases/case_0001/READY") is True
    assert s.object_exists("cases/case_0099/READY") is False

def test_list_case_ids_from_prefixes():
    s = InMemoryStorage()
    s.upload_bytes("cases/turbine/case_0001/READY", b"")
    s.upload_bytes("cases/wing/case_0003/case/system/controlDict", b"")
    s.upload_bytes("results/case_0002/x", b"")  # not a case prefix
    assert sorted(s.list_case_ids()) == ["case_0001", "case_0003"]


def test_list_case_ids_parses_project_depth():
    s = InMemoryStorage()
    s.upload_bytes("cases/turbine/case_0001/case/x", b"")
    s.upload_bytes("cases/wing/case_0002/READY", b"")
    s.upload_bytes("results/turbine/jobx/case_0001/r", b"")
    assert sorted(s.list_case_ids()) == ["case_0001", "case_0002"]

def test_list_paths_returns_matching_prefixes():
    s = InMemoryStorage()
    s.upload_bytes("cases/case_0001/READY", b"")
    s.upload_bytes("cases/case_0001/case/command.sh", b"")
    s.upload_bytes("cases/case_0002/READY", b"")
    assert s.list_paths("cases/case_0001/") == [
        "cases/case_0001/READY",
        "cases/case_0001/case/command.sh",
    ]
