import json
from pathlib import Path
from str_cad.builder import build_from_schema_file

def test_build_golden_reactor(tmp_path):
    out = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path)
    assert (Path(out, "geometry", "tankWall.stl")).exists()
    params = json.loads(Path(out, "str-params.json").read_text())
    assert params["tank"]["diameter_m"] == 2.09
