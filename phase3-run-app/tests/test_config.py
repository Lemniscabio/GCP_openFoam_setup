from core.config import Settings, MACHINE_CATALOG, min_local_ssd_count

def test_settings_defaults():
    s = Settings()
    assert s.bucket == "cfd-lemnisca-cases"
    assert s.region == "us-central1"
    # full pullable ref (registry/repo:tag), pinned to OpenFOAM v12
    assert "/openfoam:12.0." in s.image_uri   # OpenFOAM v12, any image revision

def test_auth_defaults():
    s = Settings()
    assert s.allowed_domain == "lemnisca.bio"
    assert s.oauth_client_id == ""

def test_machine_catalog_is_all_c2d_highcpu():
    names = [m["name"] for m in MACHINE_CATALOG]
    assert names == ["c2d-highcpu-2","c2d-highcpu-4","c2d-highcpu-8",
                     "c2d-highcpu-16","c2d-highcpu-32","c2d-highcpu-56","c2d-highcpu-112"]

def test_min_local_ssd_count_for_c2d_highcpu_sizes():
    expected = {
        2: 1,
        4: 1,
        8: 1,
        16: 1,
        32: 2,
        56: 4,
        112: 8,
    }
    for vcpus, count in expected.items():
        assert min_local_ssd_count(vcpus) == count

def test_machine_catalog_exposes_local_ssd_count():
    counts = {m["name"]: m["local_ssd_count"] for m in MACHINE_CATALOG}
    assert counts == {
        "c2d-highcpu-2": 1,
        "c2d-highcpu-4": 1,
        "c2d-highcpu-8": 1,
        "c2d-highcpu-16": 1,
        "c2d-highcpu-32": 2,
        "c2d-highcpu-56": 4,
        "c2d-highcpu-112": 8,
    }

def test_settings_have_pubsub_and_firestore_defaults():
    from core.config import Settings
    s = Settings()
    assert s.pubsub_topic == "of-batch-job-state"
    assert s.firestore_database == "(default)"
    assert s.pubsub_push_sa.endswith("@cfd-lemnisca.iam.gserviceaccount.com")

def test_seed_admins_parsed_from_env(monkeypatch):
    monkeypatch.setenv("OF_SEED_ADMINS", "a@lemnisca.bio, b@lemnisca.bio")
    from importlib import reload
    import core.config as cfg
    reload(cfg)
    assert cfg.Settings().seed_admins == ["a@lemnisca.bio", "b@lemnisca.bio"]
