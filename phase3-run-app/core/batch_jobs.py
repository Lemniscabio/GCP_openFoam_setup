from core.naming import variant_for_machine
from core.disks import build_disk_spec
from core.config import local_ssd_count_for_machine_type

class BatchJobBuilder:
    def __init__(self, bucket: str, image_uri: str, job_service_account: str | None = None) -> None:
        self._bucket = bucket
        self._image = image_uri
        self._job_sa = job_service_account

    def _local_ssd_mount_script(self, local_ssd_count: int, mount_path: str) -> str:
        if local_ssd_count == 1:
            return f"""#!/bin/bash
set -euo pipefail
MOUNT_PATH="{mount_path}"
LOCAL_SSD_COUNT=1
shopt -s nullglob
devices=(/dev/disk/by-id/google-local-nvme-ssd-*)
if [ "${{#devices[@]}}" -eq 0 ]; then
  devices=(/dev/disk/by-id/google-local-ssd-*)
fi
shopt -u nullglob
if [ "${{#devices[@]}}" -lt "${{LOCAL_SSD_COUNT}}" ]; then
  echo "expected ${{LOCAL_SSD_COUNT}} local SSD device(s), found ${{#devices[@]}}"
  exit 1
fi
devices=("${{devices[@]:0:${{LOCAL_SSD_COUNT}}}}")
mkdir -p "${{MOUNT_PATH}}"
mkfs.ext4 -F "${{devices[0]}}"
mount "${{devices[0]}}" "${{MOUNT_PATH}}"
chmod a+w "${{MOUNT_PATH}}"
"""
        return f"""#!/bin/bash
set -euo pipefail
MOUNT_PATH="{mount_path}"
LOCAL_SSD_COUNT={local_ssd_count}
shopt -s nullglob
devices=(/dev/disk/by-id/google-local-nvme-ssd-*)
if [ "${{#devices[@]}}" -eq 0 ]; then
  devices=(/dev/disk/by-id/google-local-ssd-*)
fi
shopt -u nullglob
if [ "${{#devices[@]}}" -lt "${{LOCAL_SSD_COUNT}}" ]; then
  echo "expected ${{LOCAL_SSD_COUNT}} local SSD device(s), found ${{#devices[@]}}"
  exit 1
fi
devices=("${{devices[@]:0:${{LOCAL_SSD_COUNT}}}}")
mkdir -p "${{MOUNT_PATH}}"
if ! command -v mdadm >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get -y install mdadm
  fi
fi
if ! command -v mdadm >/dev/null 2>&1; then
  echo "mdadm is required to stripe local SSD scratch disks"
  exit 1
fi
mdadm --create /dev/md0 --level=0 --raid-devices={local_ssd_count} "${{devices[@]}}"
mkfs.ext4 -F /dev/md0
mount /dev/md0 "${{MOUNT_PATH}}"
chmod a+w "${{MOUNT_PATH}}"
"""

    def _container_runnable(self, container_volumes: list[str]) -> dict:
        container = {
            "imageUri": self._image,
            "entrypoint": "/bin/bash",
            "commands": ["-lc", "/opt/openfoam-batch/run_case_in_batch.sh"],
        }
        if container_volumes:
            container["volumes"] = container_volumes
        return {"container": container}

    def _task_spec(self, env: dict, cpu_milli: int, memory_mib: int,
                   volumes: list[dict], container_volumes: list[str],
                   local_ssd_count: int, mount_path: str, max_retry_count: int) -> dict:
        # NOTE: deliberately NO maxRunDuration (flaw #1 — jobs run until done or stopped).
        runnables = []
        if local_ssd_count > 0:
            runnables.append({"script": {"text": self._local_ssd_mount_script(local_ssd_count, mount_path)}})
        runnables.append(self._container_runnable(container_volumes))
        return {
            "runnables": runnables,
            "environment": {"variables": env},
            "computeResource": {"cpuMilli": cpu_milli, "memoryMib": memory_mib},
            "maxRetryCount": max_retry_count,
            "volumes": volumes,
        }

    def _instance_policy(self, machine_type: str, provisioning_model: str, disks: list[dict]) -> dict:
        return {"policy": {
            "machineType": machine_type,
            "provisioningModel": provisioning_model,
            "disks": disks,
        }}

    def build_single(self, *, case_id: str, machine_type: str, cpu_milli: int,
                     memory_mib: int, mpi_ranks: int, job_name: str,
                     provisioning_model: str = "STANDARD", max_retry_count: int = 3,
                     local_ssd_count: int | None = None, scratch_disk_type: str = "pd-ssd",
                     scratch_disk_gb: int = 200) -> dict:
        variant = variant_for_machine(machine_type)
        if local_ssd_count is None:
            local_ssd_count = local_ssd_count_for_machine_type(machine_type)
        disk = build_disk_spec(local_ssd_count, scratch_disk_type, scratch_disk_gb)
        env = {
            "BUCKET": self._bucket,
            "CASE_ID": case_id,
            "VARIANT_ID": variant,
            "JOB_NAME": job_name,
            "CPU_MILLI": str(cpu_milli),
            "MPI_RANKS": str(mpi_ranks),
            "SCRATCH_ROOT": "/mnt/disks/openfoam-scratch",
        }
        task_spec = self._task_spec(
            env, cpu_milli, memory_mib, disk["volumes"], disk["container_volumes"],
            disk["local_ssd_count"], disk["mount_path"], max_retry_count,
        )
        alloc = {"instances": [self._instance_policy(machine_type, provisioning_model, disk["disks"])]}
        if self._job_sa:
            alloc["serviceAccount"] = {"email": self._job_sa}
        return {
            "taskGroups": [{"taskCount": 1, "parallelism": 1, "taskSpec": task_spec}],
            "allocationPolicy": alloc,
            "logsPolicy": {"destination": "CLOUD_LOGGING"},
            "labels": {"app": "openfoam"},
        }

    def build_multi(self, *, case_ids: list[str], machine_type: str, cpu_milli: int,
                    memory_mib: int, mpi_ranks: int, job_name: str,
                    provisioning_model: str = "STANDARD", max_retry_count: int = 3,
                    local_ssd_count: int | None = None, scratch_disk_type: str = "pd-ssd",
                    scratch_disk_gb: int = 200) -> dict:
        if not case_ids:
            raise ValueError("build_multi requires at least one case id")
        variant = variant_for_machine(machine_type)
        if local_ssd_count is None:
            local_ssd_count = local_ssd_count_for_machine_type(machine_type)
        disk = build_disk_spec(local_ssd_count, scratch_disk_type, scratch_disk_gb)
        env = {
            "BUCKET": self._bucket,
            "CASE_ID_LIST": ",".join(case_ids),  # runtime resolves CASE_ID via BATCH_TASK_INDEX
            "VARIANT_ID": variant,
            "JOB_NAME": job_name,
            "CPU_MILLI": str(cpu_milli),
            "MPI_RANKS": str(mpi_ranks),
            "SCRATCH_ROOT": "/mnt/disks/openfoam-scratch",
        }
        n = len(case_ids)
        task_spec = self._task_spec(
            env, cpu_milli, memory_mib, disk["volumes"], disk["container_volumes"],
            disk["local_ssd_count"], disk["mount_path"], max_retry_count,
        )
        alloc = {"instances": [self._instance_policy(machine_type, provisioning_model, disk["disks"])]}
        if self._job_sa:
            alloc["serviceAccount"] = {"email": self._job_sa}
        return {
            "taskGroups": [{"taskCount": n, "parallelism": n, "taskSpec": task_spec}],
            "allocationPolicy": alloc,
            "logsPolicy": {"destination": "CLOUD_LOGGING"},
            "labels": {"app": "openfoam"},
        }

from google.cloud import batch_v1  # type: ignore
from google.protobuf import json_format  # type: ignore

class BatchSubmitter:
    """Submits a built spec dict via the Batch API."""
    def __init__(self, project_id: str, region: str) -> None:
        self._project = project_id
        self._region = region
        self._client = batch_v1.BatchServiceClient()

    def submit(self, job_name: str, spec: dict) -> str:
        job = json_format.ParseDict(spec, batch_v1.Job()._pb)
        parent = f"projects/{self._project}/locations/{self._region}"
        created = self._client.create_job(batch_v1.CreateJobRequest(
            parent=parent, job_id=job_name, job=batch_v1.Job.wrap(job)))
        return created.name
