import datetime

from core.case_records import CaseRecord, InMemoryCaseRecordRepository


def _rec(case_id="case_0006", name="Wind Tunnel v3"):
    return CaseRecord(
        case_id=case_id, name=name,
        uploaded_by="kartikey.attri@lemnisca.bio",
        uploaded_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        ready=True,
    )


def test_upsert_then_get():
    repo = InMemoryCaseRecordRepository()
    repo.upsert(_rec())
    got = repo.get("case_0006")
    assert got.name == "Wind Tunnel v3"
    assert got.ready is True


def test_names_for_resolves_in_order_with_fallback():
    repo = InMemoryCaseRecordRepository()
    repo.upsert(_rec("case_0006", "Wind Tunnel v3"))
    # case_0007 not recorded -> falls back to the id
    assert repo.names_for(["case_0006", "case_0007"]) == ["Wind Tunnel v3", "case_0007"]


def test_get_missing_returns_none():
    assert InMemoryCaseRecordRepository().get("nope") is None
