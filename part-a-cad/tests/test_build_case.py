from pathlib import Path
from str_cad.builder import build_from_schema_file
from str_cad.ofcase.caseparams import CaseParams
from str_cad.ofcase.build import build_case
from str_cad.geometry.assembly import REGION_NAMES

def test_build_case_full_tree(tmp_path):
    geo = build_from_schema_file(Path("examples/reactor_30kl.json"), tmp_path / "geo")
    cp = CaseParams.model_validate({"rpm": 90, "viscosity_m2_s": 1e-6, "run": {"cores": 4}})
    case = build_case(cp, geo, tmp_path / "case")
    must = ["0/U","0/p","0/k","0/epsilon","0/nut",
            "constant/physicalProperties","constant/momentumTransport","constant/MRFProperties",
            "system/controlDict","system/fvSchemes","system/fvSolution","system/topoSetDict",
            "system/decomposeParDict","system/blockMeshDict","system/snappyHexMeshDict",
            "command.sh","metadata.json"]
    for f in must:
        assert Path(case, f).exists(), f
    for r in REGION_NAMES:
        assert Path(case, "constant/triSurface", f"{r}.stl").exists(), r
    u = Path(case, "0/U").read_text()
    assert all(r in u for r in REGION_NAMES)
