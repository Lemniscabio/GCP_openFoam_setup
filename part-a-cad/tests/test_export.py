import json, trimesh
from pathlib import Path
from str_cad.schema import STRParams
from str_cad.export import export_geometry
from tests.test_schema import _valid

EXPECTED_FILES = {"tankWall.stl","dishedBottom.stl","baffles.stl","shaft.stl",
                  "impellers.stl","liquidSurface.stl"}

def test_export_writes_all_region_stls_and_params(tmp_path):
    p = STRParams.model_validate(_valid())
    out = export_geometry(p, tmp_path)
    files = {f.name for f in Path(out, "geometry").glob("*.stl")}
    assert files == EXPECTED_FILES
    params = json.loads(Path(out, "str-params.json").read_text())
    assert params["family"] == "stirred_tank_reactor"

def test_large_vessel_export_is_bounded(tmp_path):
    # Regression: STL deflection tolerance must scale with vessel size. At a fixed
    # 1e-4 m a 20 m dished bottom exploded to ~24 MB / ~40 s and timed out the web
    # preview (HTTP 503). Scaling keeps it bounded.
    spec = _valid()
    spec["tank"]["diameter_m"] = 20.0
    spec["impellers"].pop("blade_length_m", None)
    spec["impellers"].pop("blade_height_m", None)
    out = export_geometry(STRParams.model_validate(spec), tmp_path)
    dished = Path(out, "geometry", "dishedBottom.stl")
    assert dished.is_file()
    # ~24 MB at the old fixed tolerance; scaled export keeps it well under that.
    assert dished.stat().st_size < 16_000_000, dished.stat().st_size


def test_combined_surfaces_form_a_watertight_fluid_domain(tmp_path):
    p = STRParams.model_validate(_valid())
    out = export_geometry(p, tmp_path)
    meshes = [trimesh.load(str(f)) for f in Path(out,"geometry").glob("*.stl")]
    combined = trimesh.util.concatenate(meshes)
    combined.merge_vertices()
    assert combined.is_watertight, "fluid domain boundary is not closed -> snappy will fail"
