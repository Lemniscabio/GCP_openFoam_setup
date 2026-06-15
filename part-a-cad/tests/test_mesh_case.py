from pathlib import Path

import numpy as np

from str_cad.builder import build_from_schema_file
from str_cad.meshcase import _cell_counts, make_mesh_case, REGION_NAMES

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


def test_background_mesh_uses_roughly_012m_cells():
    minimum = np.array((0.0, 0.0, 0.0))
    maximum = np.array((2.4, 2.4, 9.0))

    assert _cell_counts(minimum, maximum) == (20, 20, 75)


def test_snappy_refines_impeller_column_and_thin_surfaces(tmp_path):
    geo = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    case = make_mesh_case(geo, tmp_path / "case")
    snappy = (Path(case, "system", "snappyHexMeshDict")).read_text()

    assert """    rotorColumn
    {
        type searchableCylinder;
        point1 (0 0 0.98);
        point2 (0 0 5.64);
        radius 0.452833333;
    }""" in snappy
    assert """    refinementRegions
    {
        rotorColumn
        {
            mode inside;
            levels ((1e15 2));
        }
    }""" in snappy
    for name in ("impellers", "baffles", "shaft"):
        assert f"""        {name}
        {{
            level (2 3);
            patchInfo {{ type wall; }}
        }}""" in snappy
    for name in ("tankWall", "dishedBottom", "liquidSurface"):
        assert f"""        {name}
        {{
            level (1 1);
            patchInfo {{ type wall; }}
        }}""" in snappy


def test_mesh_quality_dict_uses_inline_v12_defaults(tmp_path):
    geo = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    case = make_mesh_case(geo, tmp_path / "case")
    mesh_quality = (Path(case, "system", "meshQualityDict")).read_text()
    body = mesh_quality.split("}\n\n", 1)[1]

    assert body == """maxNonOrtho         65;
maxBoundarySkewness 20;
maxInternalSkewness 4;
maxConcave          80;
minVol              1e-13;
minTetQuality       1e-15;
minArea             -1;
minTwist            0.02;
minDeterminant      0.001;
minFaceWeight       0.05;
minVolRatio         0.01;
minTriangleTwist    -1;
nSmoothScale        4;
errorReduction      0.75;
relaxed { maxNonOrtho 75; }
"""


def test_snappy_geometry_uses_v12_named_regions(tmp_path):
    geo = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    case = make_mesh_case(geo, tmp_path / "case")
    snappy = (Path(case, "system", "snappyHexMeshDict")).read_text()

    for name in REGION_NAMES:
        assert f'''    {name}
    {{
        type triSurfaceMesh;
        file "{name}.stl";
    }}''' in snappy
        assert f"    {name}.stl\n" not in snappy
        assert f"        name {name};" not in snappy
