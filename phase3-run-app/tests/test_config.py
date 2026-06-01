from core.config import Settings, MACHINE_CATALOG

def test_settings_defaults():
    s = Settings()
    assert s.bucket == "of-cases"
    assert s.region == "us-central1"
    assert s.image_uri.startswith("openfoam:12")

def test_machine_catalog_is_all_c2d_highcpu():
    names = [m["name"] for m in MACHINE_CATALOG]
    assert names == ["c2d-highcpu-2","c2d-highcpu-4","c2d-highcpu-8",
                     "c2d-highcpu-16","c2d-highcpu-32","c2d-highcpu-56","c2d-highcpu-112"]
