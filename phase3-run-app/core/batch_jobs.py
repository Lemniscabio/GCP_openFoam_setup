from core.naming import variant_for_machine
from core.disks import build_disk_spec

class BatchJobBuilder:
    def __init__(self, bucket: str, image_uri: str) -> None:
        self._bucket = bucket
        self._image = image_uri

    def _task_spec(self, env: dict, cpu_milli: int, memory_mib: int,
                   volumes: list[dict], max_retry_count: int) -> dict:
        # NOTE: deliberately NO maxRunDuration (flaw #1 — jobs run until done or stopped).
        return {
            "runnables": [{
                "container": {
                    "imageUri": self._image,
                    "entrypoint": "/bin/bash",
                    "commands": ["-lc", "/opt/openfoam-batch/run_case_in_batch.sh"],
                }
            }],
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
                     local_ssd_count: int = 1, scratch_disk_type: str = "pd-ssd",
                     scratch_disk_gb: int = 200) -> dict:
        variant = variant_for_machine(machine_type)
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
        task_spec = self._task_spec(env, cpu_milli, memory_mib, disk["volumes"], max_retry_count)
        return {
            "taskGroups": [{"taskCount": 1, "parallelism": 1, "taskSpec": task_spec}],
            "allocationPolicy": {"instances": [
                self._instance_policy(machine_type, provisioning_model, disk["disks"])]},
            "logsPolicy": {"destination": "CLOUD_LOGGING"},
            "labels": {"app": "openfoam"},
        }

    def build_multi(self, *, case_ids: list[str], machine_type: str, cpu_milli: int,
                    memory_mib: int, mpi_ranks: int, job_name: str,
                    provisioning_model: str = "STANDARD", max_retry_count: int = 3,
                    local_ssd_count: int = 1, scratch_disk_type: str = "pd-ssd",
                    scratch_disk_gb: int = 200) -> dict:
        if not case_ids:
            raise ValueError("build_multi requires at least one case id")
        variant = variant_for_machine(machine_type)
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
        task_spec = self._task_spec(env, cpu_milli, memory_mib, disk["volumes"], max_retry_count)
        return {
            "taskGroups": [{"taskCount": n, "parallelism": n, "taskSpec": task_spec}],
            "allocationPolicy": {"instances": [
                self._instance_policy(machine_type, provisioning_model, disk["disks"])]},
            "logsPolicy": {"destination": "CLOUD_LOGGING"},
            "labels": {"app": "openfoam"},
        }
