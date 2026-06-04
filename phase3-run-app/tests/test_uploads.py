import datetime
from core.uploads import SignedUrlService, object_path, case_prefix


def test_case_prefix():
    assert case_prefix("case_0042") == "cases/case_0042/"


def test_object_path_maps_under_case_tree():
    assert object_path("case_0042", "system/fvSolution") == "cases/case_0042/case/system/fvSolution"
    assert object_path("case_0042", "/0/U") == "cases/case_0042/case/0/U"


class _FakeBlob:
    def __init__(self, name):
        self.name = name
        self.kwargs = None

    def generate_signed_url(self, **kw):
        self.kwargs = kw
        return f"https://signed.example/{self.name}"


class _FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, name):
        return self.blobs.setdefault(name, _FakeBlob(name))


def test_put_url_is_keyless_v4_put():
    bkt = _FakeBucket()
    svc = SignedUrlService(bkt, signer_email="of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com",
                           token_provider=lambda: "tok-123")
    up = svc.put_url("cases/case_0042/case/0/U", datetime.datetime(2026, 6, 3, 12, 0, 0))
    assert up.method == "PUT"
    assert up.url == "https://signed.example/cases/case_0042/case/0/U"
    kw = bkt.blobs["cases/case_0042/case/0/U"].kwargs
    assert kw["version"] == "v4"
    assert kw["method"] == "PUT"
    assert kw["service_account_email"] == "of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com"
    assert kw["access_token"] == "tok-123"   # keyless


def test_put_urls_for_case_maps_all_files():
    bkt = _FakeBucket()
    svc = SignedUrlService(bkt, signer_email="sa@x.iam.gserviceaccount.com", token_provider=lambda: "t")
    ups = svc.put_urls_for_case("case_0007", ["0/U", "system/controlDict"], datetime.datetime(2026, 6, 3, 12, 0, 0))
    assert [u.object_path for u in ups] == ["cases/case_0007/case/0/U", "cases/case_0007/case/system/controlDict"]
