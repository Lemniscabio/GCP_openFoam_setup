from pathlib import Path
from str_cad.builder import build_from_schema_file
from str_cad.meshcase import make_mesh_case, REGION_NAMES

def test_mesh_case_has_dicts_and_trisurfaces(tmp_path):
    geo = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    case = make_mesh_case(geo, tmp_path / "case")
    for d in ["controlDict", "blockMeshDict", "snappyHexMeshDict", "fvSchemes", "fvSolution", "meshQualityDict"]:
        assert (Path(case, "system", d)).exists(), d
    tri = Path(case, "constant", "triSurface")
    for name in REGION_NAMES:
        assert (tri / f"{name}.stl").exists(), name

def test_snappy_references_all_regions(tmp_path):
    geo = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    case = make_mesh_case(geo, tmp_path / "case")
    snappy = (Path(case, "system", "snappyHexMeshDict")).read_text()
    for name in REGION_NAMES:
        assert name in snappy, name
