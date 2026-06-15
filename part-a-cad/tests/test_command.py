import json, os, stat
from pathlib import Path
from str_cad.schema import STRParams
from str_cad.ofcase.caseparams import CaseParams
from str_cad.ofcase.command import write_command_sh, write_metadata_json

def _sp():
    return STRParams.model_validate(json.load(open("examples/reactor_30kl.json")))

def test_command_sh_resume_aware_and_executable(tmp_path):
    cp = CaseParams.model_validate({"rpm": 90, "viscosity_m2_s": 1e-6, "run": {"cores": 16}})
    p = Path(write_command_sh(cp, tmp_path / "command.sh"))
    t = p.read_text()
    assert "OF_RESUME" in t
    assert "MPI_RANKS" in t
    assert "foamDictionary system/decomposeParDict -entry numberOfSubdomains -set" in t
    for cmd in ["blockMesh", "snappyHexMesh", "topoSet", "foamRun", "reconstructPar"]:
        assert cmd in t, cmd
    assert os.stat(p).st_mode & stat.S_IXUSR  # executable

def test_metadata_json(tmp_path):
    cp = CaseParams.model_validate({"rpm": 90, "viscosity_m2_s": 1e-6})
    p = write_metadata_json(_sp(), cp, tmp_path / "metadata.json")
    m = json.loads(Path(p).read_text())
    assert m["rpm"] == 90 and m["viscosity_m2_s"] == 1e-6
