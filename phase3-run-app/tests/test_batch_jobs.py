from core.batch_jobs import BatchJobBuilder

def _build_single():
    return BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_single(
        case_id="case_0042", machine_type="c2d-highcpu-56",
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

def test_default_provisioning_is_standard():
    pol = _build_single()["allocationPolicy"]["instances"][0]["policy"]
    assert pol["provisioningModel"] == "STANDARD"  # flaw #8 (Spot is opt-in)
    assert pol["machineType"] == "c2d-highcpu-56"

def test_spot_toggle():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_single(
        case_id="case_0042", machine_type="c2d-highcpu-56", cpu_milli=56000,
        memory_mib=114688, mpi_ranks=28, job_name="j", provisioning_model="SPOT")
    assert spec["allocationPolicy"]["instances"][0]["policy"]["provisioningModel"] == "SPOT"

def test_default_disk_is_local_ssd():
    pol = _build_single()["allocationPolicy"]["instances"][0]["policy"]
    assert pol["disks"][0]["newDisk"]["type"] == "local-ssd"

def test_image_tag_recorded():
    spec = _build_single()
    assert spec["taskGroups"][0]["taskSpec"]["runnables"][0]["container"]["imageUri"] == "openfoam:12.0.0"

def test_multi_taskcount_equals_parallelism_equals_case_count():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_multi(
        case_ids=["case_0001", "case_0002", "case_0003"], machine_type="c2d-highcpu-32",
        cpu_milli=32000, memory_mib=65536, mpi_ranks=16,
        job_name="of-multi-c2d-highcpu-32-20260601120000")
    tg = spec["taskGroups"][0]
    assert tg["taskCount"] == 3 and tg["parallelism"] == 3  # flaw #6

def test_multi_passes_case_id_list_and_omits_case_id():
    spec = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0").build_multi(
        case_ids=["case_0001", "case_0002"], machine_type="c2d-highcpu-32",
        cpu_milli=32000, memory_mib=65536, mpi_ranks=16, job_name="j")
    env = spec["taskGroups"][0]["taskSpec"]["environment"]["variables"]
    assert env["CASE_ID_LIST"] == "case_0001,case_0002"
    assert "CASE_ID" not in env


def test_specs_parse_into_batch_job_proto():
    # Regression: built dicts must round-trip into the real Batch Job proto
    # (catches camelCase/field-type mismatches like mountOptions before submit time).
    from google.cloud import batch_v1
    from google.protobuf import json_format
    b = BatchJobBuilder(bucket="of-cases", image_uri="openfoam:12.0.0")
    single = b.build_single(case_id="case_0042", machine_type="c2d-highcpu-56",
                            cpu_milli=56000, memory_mib=114688, mpi_ranks=28, job_name="j")
    multi = b.build_multi(case_ids=["case_0001", "case_0002"], machine_type="c2d-highcpu-32",
                          cpu_milli=32000, memory_mib=65536, mpi_ranks=16, job_name="j")
    json_format.ParseDict(single, batch_v1.Job()._pb)   # raises ParseError on mismatch
    json_format.ParseDict(multi, batch_v1.Job()._pb)
