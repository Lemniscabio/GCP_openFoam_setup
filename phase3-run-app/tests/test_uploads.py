import datetime
from core.uploads import SignedUrlService, object_path, case_prefix


def test_case_prefix():
    assert case_prefix("turbine", "case_0042") == "cases/turbine/case_0042/"


def test_object_path_maps_under_case_tree():
    assert object_path("turbine", "case_0042", "system/fvSolution") == \
        "cases/turbine/case_0042/case/system/fvSolution"
    assert object_path("turbine", "case_0042", "/0/U") == \
        "cases/turbine/case_0042/case/0/U"


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
    ups = svc.put_urls_for_case("turbine", "case_0007", ["0/U", "system/controlDict"], datetime.datetime(2026, 6, 3, 12, 0, 0))
    assert [u.object_path for u in ups] == ["cases/turbine/case_0007/case/0/U", "cases/turbine/case_0007/case/system/controlDict"]


def test_object_path_includes_project():
    assert case_prefix("turbine", "case_0001") == "cases/turbine/case_0001/"
    assert object_path("turbine", "case_0001", "system/controlDict") == \
        "cases/turbine/case_0001/case/system/controlDict"


def test_get_url_signs_a_GET():
    class _Blob:
        def __init__(self):
            self.kw = None

        def generate_signed_url(self, **kw):
            self.kw = kw
            return "https://signed-get"

    class _Bucket:
        def __init__(self):
            self.b = _Blob()

        def blob(self, _path):
            return self.b

    bkt = _Bucket()
    svc = SignedUrlService(bkt, "sa@x.iam.gserviceaccount.com", lambda: "tok")
    url = svc.get_url(
        "results/turbine/phoenix/case_0006/result.tar.gz",
        datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    assert url == "https://signed-get"
    assert bkt.b.kw["method"] == "GET"
    assert bkt.b.kw["version"] == "v4"


def test_get_url_threads_response_disposition():
    bkt = _FakeBucket()
    svc = SignedUrlService(bkt, "sa@x.iam.gserviceaccount.com", lambda: "tok")

    svc.get_url(
        "results/turbine/phoenix/case_0006/result.tar.gz",
        datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        disposition='attachment; filename="result.tar.gz"',
    )

    assert bkt.blobs[
        "results/turbine/phoenix/case_0006/result.tar.gz"
    ].kwargs["response_disposition"] == 'attachment; filename="result.tar.gz"'
