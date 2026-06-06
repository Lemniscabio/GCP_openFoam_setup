from core.batch_jobs import BatchJobBuilder

_SCRATCH_BIND_MOUNT = "/mnt/disks/openfoam-scratch:/mnt/disks/openfoam-scratch"

def _build_single():
    return BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_single(
        case_id="case_0042", project="turbine", machine_type="c2d-highcpu-56",
        cpu_milli=56000, memory_mib=114688, mpi_ranks=28,
        job_name="of-case-0042-c2d-highcpu-56-20260601120000",
    )

def test_single_has_no_max_run_duration():
    spec = _build_single()
    assert "maxRunDuration" not in spec["taskGroups"][0]["taskSpec"]  # flaw #1

def test_single_taskcount_and_parallelism_are_one():
    tg = _build_single()["taskGroups"][0]
    assert tg["taskCount"] == 1 and tg["parallelism"] == 1

def test_variant_env_is_machine_type():
    env = _build_single()["taskGroups"][0]["taskSpec"]["environment"]["variables"]
    assert env["VARIANT_ID"] == "c2d-highcpu-56"  # flaw #3
    assert env["CASE_ID"] == "case_0042"
    assert env["BUCKET"] == "of-cases"
    assert env["PROJECT"] == "turbine"

def test_default_provisioning_is_standard():
    pol = _build_single()["allocationPolicy"]["instances"][0]["policy"]
    assert pol["provisioningModel"] == "STANDARD"  # flaw #8 (Spot is opt-in)
    assert pol["machineType"] == "c2d-highcpu-56"

def test_spot_toggle():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_single(
        case_id="case_0042", project="turbine", machine_type="c2d-highcpu-56", cpu_milli=56000,
        memory_mib=114688, mpi_ranks=28, job_name="j", provisioning_model="SPOT")
    assert spec["allocationPolicy"]["instances"][0]["policy"]["provisioningModel"] == "SPOT"

def test_default_disk_is_local_ssd():
    pol = _build_single()["allocationPolicy"]["instances"][0]["policy"]
    assert pol["disks"][0]["newDisk"]["type"] == "local-ssd"

def test_image_tag_recorded():
    spec = _build_single()
    assert spec["taskGroups"][0]["taskSpec"]["runnables"][1]["container"]["imageUri"] == "openfoam:12.0.0"

def test_multi_taskcount_equals_parallelism_equals_case_count():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_multi(
        case_ids=["case_0001", "case_0002", "case_0003"], project="turbine", machine_type="c2d-highcpu-32",
        cpu_milli=32000, memory_mib=65536, mpi_ranks=16,
        job_name="of-multi-c2d-highcpu-32-20260601120000")
    tg = spec["taskGroups"][0]
    assert tg["taskCount"] == 3 and tg["parallelism"] == 3  # flaw #6

def test_multi_passes_case_id_list_and_omits_case_id():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_multi(
        case_ids=["case_0001", "case_0002"], project="turbine", machine_type="c2d-highcpu-32",
        cpu_milli=32000, memory_mib=65536, mpi_ranks=16, job_name="j")
    env = spec["taskGroups"][0]["taskSpec"]["environment"]["variables"]
    assert env["CASE_ID_LIST"] == "case_0001,case_0002"
    assert env["PROJECT"] == "turbine"
    assert "CASE_ID" not in env


def test_c2d_highcpu_32_uses_two_local_ssds_and_raid_script():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_single(
        case_id="case_0042", project="turbine", machine_type="c2d-highcpu-32",
        cpu_milli=32000, memory_mib=65536, mpi_ranks=16, job_name="j")
    disks = spec["allocationPolicy"]["instances"][0]["policy"]["disks"]
    task_spec = spec["taskGroups"][0]["taskSpec"]
    script = task_spec["runnables"][0]["script"]["text"]
    container = task_spec["runnables"][1]["container"]

    assert len(disks) == 2
    assert all(d["newDisk"]["type"] == "local-ssd" for d in disks)
    assert "mdadm" in script
    assert "--raid-devices=2" in script
    assert task_spec["volumes"] == []
    assert container["volumes"] == [_SCRATCH_BIND_MOUNT]


def test_c2d_highcpu_8_uses_one_local_ssd_without_mdadm():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_single(
        case_id="case_0042", project="turbine", machine_type="c2d-highcpu-8",
        cpu_milli=8000, memory_mib=16384, mpi_ranks=4, job_name="j")
    disks = spec["allocationPolicy"]["instances"][0]["policy"]["disks"]
    task_spec = spec["taskGroups"][0]["taskSpec"]
    script = task_spec["runnables"][0]["script"]["text"]
    container = task_spec["runnables"][1]["container"]

    assert len(disks) == 1
    assert disks[0]["newDisk"]["type"] == "local-ssd"
    assert "mdadm" not in script
    assert "mkfs.ext4 -F \"${devices[0]}\"" in script
    assert task_spec["volumes"] == []
    assert container["volumes"] == [_SCRATCH_BIND_MOUNT]


def test_specs_parse_into_batch_job_proto():
    # Regression: built dicts must round-trip into the real Batch Job proto
    # (catches camelCase/field-type mismatches like mountOptions before submit time).
    from google.cloud import batch_v1
    from google.protobuf import json_format
    b = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0")
    single = b.build_single(case_id="case_0042", project="turbine", machine_type="c2d-highcpu-56",
                            cpu_milli=56000, memory_mib=114688, mpi_ranks=28, job_name="j")
    multi = b.build_multi(case_ids=["case_0001", "case_0002"], project="turbine", machine_type="c2d-highcpu-32",
                          cpu_milli=32000, memory_mib=65536, mpi_ranks=16, job_name="j")
    json_format.ParseDict(single, batch_v1.Job()._pb)   # raises ParseError on mismatch
    json_format.ParseDict(multi, batch_v1.Job()._pb)


def test_job_spec_includes_pubsub_notifications():
    from core.batch_jobs import BatchJobBuilder
    b = BatchJobBuilder(
        bucket="buck", image_uri="img:1",
        pubsub_topic="projects/cfd-lemnisca/topics/of-batch-job-state",
    )
    spec = b.build_single(
        case_id="case_0006", project="turbine", machine_type="c2d-highcpu-8",
        cpu_milli=8000, memory_mib=16384, mpi_ranks=4, job_name="j",
    )
    notes = spec["notifications"]
    assert notes[0]["pubsubTopic"] == "projects/cfd-lemnisca/topics/of-batch-job-state"
    assert notes[0]["message"]["type"] == "JOB_STATE_CHANGED"
