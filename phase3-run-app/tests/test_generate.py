from pathlib import Path

import pytest

from core.case_records import InMemoryCaseRecordRepository
from core.cases import CaseRepository
from core.generate import (
    apply_axis_value,
    apply_file_overlays,
    build_case_local,
    commit_case,
    expand_variation_combos,
    overlay_minus_swept,
    read_case_files,
    read_region_stls,
)
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


def test_read_case_files_returns_editable_dicts_without_stls(tmp_path):
    result = build_case_local(params=GOLDEN_PARAMS, out_dir=tmp_path)
    files = read_case_files(result["case_dir"])
    assert "system/controlDict" in files
    assert "constant/MRFProperties" in files
    assert "command.sh" in files
    assert any(k.startswith("0/") for k in files)
    assert not any(k.startswith("constant/triSurface/") for k in files)  # STLs excluded
    assert "application" in files["system/controlDict"]


def test_apply_file_overlays_overwrites_and_guards(tmp_path):
    result = build_case_local(params=GOLDEN_PARAMS, out_dir=tmp_path)
    case_dir = Path(result["case_dir"])
    apply_file_overlays(case_dir, {"system/controlDict": "EDITED"})
    assert (case_dir / "system" / "controlDict").read_text() == "EDITED"
    with pytest.raises(ValueError):
        apply_file_overlays(case_dir, {"../escape.txt": "x"})   # path traversal
    with pytest.raises(ValueError):
        apply_file_overlays(case_dir, {"system/nope": "x"})     # unknown file
    apply_file_overlays(case_dir, None)  # no-op


def test_expand_variation_combos_cartesian():
    combos = expand_variation_combos({"rpm": [50, 100], "viscosity_m2_s": [1e-6, 1e-5]})
    assert len(combos) == 4
    assert {"rpm": 50, "viscosity_m2_s": 1e-6} in combos


def test_expand_variation_combos_rejects_unknown_axis():
    with pytest.raises(ValueError):
        expand_variation_combos({"fill": [1, 2]})


def test_apply_axis_value_routes_to_fields():
    params, case_params = {}, {}
    apply_axis_value(params, case_params, "rpm", 120)
    assert params["operating"]["rpm"] == 120 and case_params["rpm"] == 120
    apply_axis_value(params, case_params, "viscosity_m2_s", 1e-5)
    assert case_params["viscosity_m2_s"] == 1e-5
    apply_axis_value(params, case_params, "gas_flow_vvm", 0.7)
    assert params["operating"]["gas_flow_vvm"] == 0.7


def test_overlay_minus_swept_excludes_controlled_files():
    files = {
        "system/fvSolution": "x",
        "constant/MRFProperties": "y",
        "constant/physicalProperties": "z",
    }
    out = overlay_minus_swept(files, {"rpm"})
    assert "system/fvSolution" in out            # carried into variations
    assert "constant/MRFProperties" not in out   # rpm-controlled -> regenerated per variation
    assert "constant/physicalProperties" in out  # not rpm-controlled


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
