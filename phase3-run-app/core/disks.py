MOUNT_PATH = "/mnt/disks/openfoam-scratch"
_DEVICE = "openfoam-scratch"

def build_disk_spec(local_ssd_count: int = 1, scratch_disk_type: str = "pd-ssd",
                    scratch_disk_gb: int = 200) -> dict:
    """Returns {'disks': [...], 'volumes': [...]} for a Batch instance policy + task spec.
    Default: one 375GB local SSD. Override: N local SSDs, or a sized persistent disk."""
    disks = []
    if local_ssd_count > 0:
        for i in range(1, local_ssd_count + 1):
            disks.append({
                "newDisk": {"type": "local-ssd", "sizeGb": 375},
                "deviceName": f"{_DEVICE}-{i}",
            })
    else:
        disks.append({
            "newDisk": {"type": scratch_disk_type, "sizeGb": scratch_disk_gb},
            "deviceName": f"{_DEVICE}-1",
        })
    volumes = [{
        "deviceName": f"{_DEVICE}-1",
        "mountPath": MOUNT_PATH,
        "mountOptions": "rw,async",
    }]
    return {"disks": disks, "volumes": volumes}
