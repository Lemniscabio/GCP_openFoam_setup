import datetime

from core.case_records import (
    CaseRecord,
    FirestoreCaseRecordRepository,
    InMemoryCaseRecordRepository,
)


def _rec(case_id="case_0006", name="Wind Tunnel v3"):
    return CaseRecord(
        case_id=case_id, name=name,
        project="turbine",
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
    assert got.project == "turbine"


def test_names_for_resolves_in_order_with_fallback():
    repo = InMemoryCaseRecordRepository()
    repo.upsert(_rec("case_0006", "Wind Tunnel v3"))
    # case_0007 not recorded -> falls back to the id
    assert repo.names_for(["case_0006", "case_0007"]) == ["Wind Tunnel v3", "case_0007"]


def test_get_missing_returns_none():
    assert InMemoryCaseRecordRepository().get("nope") is None


class _Snap:
    def __init__(self, data=None):
        self.exists = data is not None
        self._data = data

    def to_dict(self):
        return self._data


class _Doc:
    def __init__(self):
        self.data = None

    def set(self, data, merge=False):
        self.data = data

    def get(self):
        return _Snap(self.data)


class _Collection:
    def __init__(self):
        self.docs = {}

    def document(self, doc_id):
        return self.docs.setdefault(doc_id, _Doc())


class _Firestore:
    def __init__(self):
        self.collection_value = _Collection()

    def collection(self, _name):
        return self.collection_value


def test_firestore_round_trip_includes_project():
    repo = FirestoreCaseRecordRepository(_Firestore())
    repo.upsert(_rec())
    assert repo.get("case_0006").project == "turbine"
