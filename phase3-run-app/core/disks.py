MOUNT_PATH = "/mnt/disks/openfoam-scratch"
_DEVICE = "openfoam-scratch"
_BIND_MOUNT = f"{MOUNT_PATH}:{MOUNT_PATH}"

def build_disk_spec(local_ssd_count: int = 1, scratch_disk_type: str = "pd-ssd",
                    scratch_disk_gb: int = 200) -> dict:
    """Returns disk policy, Batch volumes, and container bind mounts for scratch."""
    disks = []
    if local_ssd_count > 0:
        for i in range(1, local_ssd_count + 1):
            disks.append({
                "newDisk": {"type": "local-ssd", "sizeGb": 375},
                "deviceName": f"{_DEVICE}-{i}",
            })
        return {
            "disks": disks,
            "volumes": [],
            "container_volumes": [_BIND_MOUNT],
            "local_ssd_count": local_ssd_count,
            "mount_path": MOUNT_PATH,
        }
    else:
        disks.append({
            "newDisk": {"type": scratch_disk_type, "sizeGb": scratch_disk_gb},
            "deviceName": f"{_DEVICE}-1",
        })
        volumes = [{
            "deviceName": f"{_DEVICE}-1",
            "mountPath": MOUNT_PATH,
            "mountOptions": ["rw", "async"],  # Batch proto field is repeated (list), not a string
        }]
        return {
            "disks": disks,
            "volumes": volumes,
            "container_volumes": [],
            "local_ssd_count": 0,
            "mount_path": MOUNT_PATH,
        }
