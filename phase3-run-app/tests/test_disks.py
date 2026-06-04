from core.disks import build_disk_spec

def test_default_is_one_local_ssd():
    spec = build_disk_spec()  # defaults
    assert spec["disks"][0]["newDisk"]["type"] == "local-ssd"
    assert spec["disks"][0]["newDisk"]["sizeGb"] == 375
    assert len(spec["disks"]) == 1
    assert spec["volumes"][0]["mountPath"] == "/mnt/disks/openfoam-scratch"

def test_multiple_local_ssds():
    spec = build_disk_spec(local_ssd_count=3)
    assert len(spec["disks"]) == 3
    assert all(d["newDisk"]["type"] == "local-ssd" for d in spec["disks"])

def test_pd_ssd_override():
    spec = build_disk_spec(local_ssd_count=0, scratch_disk_type="pd-ssd", scratch_disk_gb=500)
    assert len(spec["disks"]) == 1
    assert spec["disks"][0]["newDisk"]["type"] == "pd-ssd"
    assert spec["disks"][0]["newDisk"]["sizeGb"] == 500
