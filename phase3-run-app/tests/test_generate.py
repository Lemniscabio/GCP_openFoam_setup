from core.case_records import InMemoryCaseRecordRepository
from core.cases import CaseRepository
from core.generate import build_case_local, commit_case, read_region_stls
from core.storage import InMemoryStorage


GOLDEN_PARAMS = {
    "family": "stirred_tank_reactor",
    "tank": {"diameter_m": 2.09, "height_m": 9.6, "bottom": "dished"},
    "liquid": {"height_m": 6.55},
    "baffles": {
        "count": 4,
        "width_m": 0.167,
        "height_m": 7.5,
        "arrangement": "symmetric",
    },
    "shaft": {"central": True},
    "impellers": {
        "count": 4,
        "type": "rushton",
        "blades": 6,
        "diameter_ratio": 1 / 3,
        "blade_height_m": 0.14,
        "blade_length_m": 0.175,
        "lowest_clearance_m": 1.12,
        "inter_impeller_clearance_m": 1.46,
    },
}


def test_build_case_local_from_params_creates_openfoam_case(tmp_path):
    result = build_case_local(params=GOLDEN_PARAMS, out_dir=tmp_path)

    case_dir = result["case_dir"]
    expected_files = [
        "0/U",
        "constant/MRFProperties",
        "system/controlDict",
        "command.sh",
        "metadata.json",
    ]
    for relative_path in expected_files:
        assert (case_dir / relative_path).is_file(), relative_path

    stls = list((case_dir / "constant" / "triSurface").glob("*.stl"))
    assert len(stls) == 6
    assert result["str_params"]["tank"]["diameter_m"] == 2.09
    assert result["case_params"]["rpm"] == 90


def test_read_region_stls_returns_six_non_empty_blobs(tmp_path):
    result = build_case_local(params=GOLDEN_PARAMS, out_dir=tmp_path)

    regions = read_region_stls(result["geometry_dir"])

    assert len(regions) == 6
    assert all(isinstance(blob, bytes) and blob for blob in regions.values())


def test_commit_case_uploads_tree_and_registers_ready_record(tmp_path):
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "nested").mkdir()
    (case_dir / "system" / "controlDict").write_text("application foamRun;")
    (case_dir / "command.sh").write_text("mpirun -np ${MPI_RANKS} foamRun -parallel")
    (case_dir / "metadata.json").write_text('{"source":"generated"}')
    (case_dir / "nested" / "extra.bin").write_bytes(b"extra")
    storage = InMemoryStorage()
    case_repo = CaseRepository(storage)
    records = InMemoryCaseRecordRepository()

    case_id = commit_case(
        case_dir,
        "generated-cases",
        "builder@lemnisca.bio",
        storage=storage,
        case_repo=case_repo,
        case_record_repo=records,
    )

    base = f"cases/generated-cases/{case_id}"
    assert case_id == "case_0001"
    assert storage.object_exists(f"{base}/case/system/controlDict")
    assert storage.object_exists(f"{base}/case/nested/extra.bin")
    assert storage.object_exists(f"{base}/manifest.json")
    assert storage.object_exists(f"{base}/READY")
    record = records.get(case_id)
    assert record is not None
    assert record.uploaded_by == "builder@lemnisca.bio"
    assert record.project == "generated-cases"
    assert record.ready is True
