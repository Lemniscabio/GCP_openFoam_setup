from core.storage import InMemoryStorage
from core.cases import CaseRepository

def test_allocate_from_empty_starts_at_one():
    repo = CaseRepository(InMemoryStorage())
    assert repo.allocate_ids("turbine", 1) == ["case_0001"]

def test_allocate_continues_after_existing_max():
    s = InMemoryStorage()
    for n in range(1, 31):  # case_0001..case_0030 exist
        s.upload_bytes(f"cases/turbine/case_{n:04d}/READY", b"")
    repo = CaseRepository(s)
    assert repo.allocate_ids("wing", 3) == ["case_0031", "case_0032", "case_0033"]

def test_allocate_skips_reserved_but_not_ready_ids():
    # a half-allocated id with only a .reserved marker must NOT be reused
    s = InMemoryStorage()
    s.create_exclusive("cases/turbine/case_0001/.reserved", b"")
    repo = CaseRepository(s)
    assert repo.allocate_ids("wing", 1) == ["case_0002"]

def test_allocate_50_is_contiguous_and_unique():
    repo = CaseRepository(InMemoryStorage())
    ids = repo.allocate_ids("turbine", 50)
    assert len(set(ids)) == 50
    assert ids[0] == "case_0001" and ids[-1] == "case_0050"


def test_allocate_ids_reserves_under_project_global_numbering():
    s = InMemoryStorage()
    repo = CaseRepository(s)
    ids = repo.allocate_ids("turbine", 2)
    assert ids == ["case_0001", "case_0002"]
    assert s.object_exists("cases/turbine/case_0001/.reserved")
    more = repo.allocate_ids("wing", 1)
    assert more == ["case_0003"]
    assert s.object_exists("cases/wing/case_0003/.reserved")


def test_exists_is_project_scoped():
    s = InMemoryStorage()
    repo = CaseRepository(s)
    repo.allocate_ids("turbine", 1)
    assert repo.exists("turbine", "case_0001") is True
    assert repo.exists("wing", "case_0001") is False
