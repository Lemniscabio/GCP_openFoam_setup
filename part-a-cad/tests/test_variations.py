import copy
import json
import re
from pathlib import Path

from str_cad.variations import expand_variations, generate_sweep
from tests.test_schema import _valid


def _control_value(control_dict: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}\s+([^;]+);", control_dict, re.M)
    assert match, f"missing controlDict key: {key}"
    return match.group(1).strip()


def test_expand_cartesian():
    base = _valid()
    base["operating"] = {"rpm": 90}
    original = copy.deepcopy(base)

    specs = expand_variations(
        base,
        {
            "operating.rpm": [50, 100, 150],
            "run.viscosity_m2_s": [1e-6, 1e-5],
        },
    )

    assert len(specs) == 6
    assert [(s["operating"]["rpm"], s["run"]["viscosity_m2_s"]) for s in specs] == [
        (50, 1e-6),
        (50, 1e-5),
        (100, 1e-6),
        (100, 1e-5),
        (150, 1e-6),
        (150, 1e-5),
    ]
    assert base == original


def test_expand_creates_nested_paths():
    base = _valid()

    specs = expand_variations(base, {"run.viscosity_m2_s": [1e-6]})

    assert specs[0]["run"]["viscosity_m2_s"] == 1e-6
    assert "run" not in base


def test_sweep_writes_runs_map(tmp_path):
    base = json.loads(Path("examples/reactor_30kl.json").read_text())

    runs_map = generate_sweep(
        base,
        {"operating.rpm": [50, 100]},
        tmp_path / "sweep",
    )

    assert set(runs_map.keys()) == {"0", "1", "_skipped"}
    assert runs_map["_skipped"] == []
    assert Path(tmp_path, "sweep", "runs_map.json").exists()
    for index in ("0", "1"):
        case_dir = tmp_path / "sweep" / index
        assert Path(case_dir, "system", "controlDict").exists()
        assert Path(case_dir, "constant", "MRFProperties").exists()
        assert Path(case_dir, "params.json").exists()


def test_sweep_skips_invalid_combo(tmp_path):
    base = json.loads(Path("examples/reactor_30kl.json").read_text())

    runs_map = generate_sweep(
        base,
        {"liquid.height_m": [6.55, 0.5]},
        tmp_path / "sweep",
    )

    assert "0" in runs_map
    assert "1" not in runs_map
    assert runs_map["_skipped"] == [
        {"index": 1, "reason": "impellers must fit below the liquid height"}
    ]
    assert Path(tmp_path, "sweep", "0", "system", "controlDict").exists()
    assert not Path(tmp_path, "sweep", "1").exists()


def test_sweep_propagates_verify(tmp_path):
    base = json.loads(Path("examples/reactor_30kl.json").read_text())
    base["run"] = {"verify": True, "verify_steps": 5}

    generate_sweep(base, {"operating.rpm": [100]}, tmp_path / "sweep")

    control_dict = (tmp_path / "sweep" / "0" / "system" / "controlDict").read_text()
    assert _control_value(control_dict, "endTime") == "5"
