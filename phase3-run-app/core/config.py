import os
from dataclasses import dataclass

# vCPU -> (cpu_milli, memory_mib). c2d-highcpu is 2GB/vCPU.
_C2D_HIGHCPU_VCPUS = [2, 4, 8, 16, 32, 56, 112]

MACHINE_CATALOG = [
    {
        "name": f"c2d-highcpu-{v}",
        "vcpus": v,
        "cpu_milli": v * 1000,
        "memory_mib": v * 2048,
        "default_mpi_ranks": max(1, v // 2),
    }
    for v in _C2D_HIGHCPU_VCPUS
]

@dataclass
class Settings:
    project_id: str = os.environ.get("OF_PROJECT_ID", "project-688a4c78-5d5b-45b3-b5d")
    region: str = os.environ.get("OF_REGION", "us-central1")
    bucket: str = os.environ.get("OF_BUCKET", "of-cases")
    # Full pullable ref so `of run` needs no OF_IMAGE_URI override. Migrate to
    # Artifact Registry in M2; OF_IMAGE_URI still overrides for ad-hoc tags.
    image_uri: str = os.environ.get("OF_IMAGE_URI", "docker.io/kartikeyattri/openfoam:12.0.0")
    scratch_root: str = "/mnt/disks/openfoam-scratch"
