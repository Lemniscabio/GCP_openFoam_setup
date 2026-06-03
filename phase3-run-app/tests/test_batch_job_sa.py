from core.batch_jobs import BatchJobBuilder


def test_single_sets_job_service_account():
    spec = BatchJobBuilder(
        bucket="b",
        image_uri="img",
        job_service_account="of-batch-job@cfd-lemnisca.iam.gserviceaccount.com",
    ).build_single(
        case_id="case_0001",
        machine_type="c2d-highcpu-2",
        cpu_milli=2000,
        memory_mib=4096,
        mpi_ranks=1,
        job_name="j",
    )
    assert (
        spec["allocationPolicy"]["serviceAccount"]["email"]
        == "of-batch-job@cfd-lemnisca.iam.gserviceaccount.com"
    )


def test_multi_sets_job_service_account():
    spec = BatchJobBuilder(
        bucket="b",
        image_uri="img",
        job_service_account="of-batch-job@cfd-lemnisca.iam.gserviceaccount.com",
    ).build_multi(
        case_ids=["case_0001", "case_0002"],
        machine_type="c2d-highcpu-2",
        cpu_milli=2000,
        memory_mib=4096,
        mpi_ranks=1,
        job_name="j",
    )
    assert spec["allocationPolicy"]["serviceAccount"]["email"].startswith("of-batch-job@")
