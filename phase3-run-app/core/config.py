import os
from dataclasses import dataclass

# vCPU -> (cpu_milli, memory_mib). c2d-highcpu is 2GB/vCPU.
_C2D_HIGHCPU_VCPUS = [2, 4, 8, 16, 32, 56, 112]


def min_local_ssd_count(vcpus: int) -> int:
    if vcpus <= 0:
        raise ValueError("vcpus must be positive")
    for count in (1, 2, 4, 8):
        if count * 16 >= vcpus:
            return count
    raise ValueError(f"no valid local SSD count for {vcpus} vCPUs")


MACHINE_CATALOG = [
    {
        "name": f"c2d-highcpu-{v}",
        "vcpus": v,
        "cpu_milli": v * 1000,
        "memory_mib": v * 2048,
        "default_mpi_ranks": max(1, v // 2),
        "local_ssd_count": min_local_ssd_count(v),
    }
    for v in _C2D_HIGHCPU_VCPUS
]


def local_ssd_count_for_machine_type(machine_type: str) -> int:
    for machine in MACHINE_CATALOG:
        if machine["name"] == machine_type:
            return machine["local_ssd_count"]
    raise KeyError(machine_type)

@dataclass
class Settings:
    project_id: str = os.environ.get("OF_PROJECT_ID", "cfd-lemnisca")
    region: str = os.environ.get("OF_REGION", "us-central1")
    bucket: str = os.environ.get("OF_BUCKET", "cfd-lemnisca-cases")
    # Full pullable ref so `of run` needs no OF_IMAGE_URI override. Private
    # Artifact Registry in the dedicated cfd-lemnisca project; OF_IMAGE_URI overrides.
    image_uri: str = os.environ.get("OF_IMAGE_URI", "us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.1")
    job_service_account: str = os.environ.get("OF_JOB_SA", "of-batch-job@cfd-lemnisca.iam.gserviceaccount.com")
    backend_service_account: str = os.environ.get("OF_BACKEND_SA", "of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com")
    oauth_client_id: str = os.environ.get("OF_OAUTH_CLIENT_ID", "")
    allowed_domain: str = os.environ.get("OF_ALLOWED_DOMAIN", "lemnisca.bio")
    scratch_root: str = "/mnt/disks/openfoam-scratch"
