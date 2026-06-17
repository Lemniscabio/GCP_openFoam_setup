import json
import str_cad.extract as extract
from str_cad.schema import STRParams

GOLDEN = {
    "family": "stirred_tank_reactor",
    "tank": {"diameter_m": 2.09, "height_m": 9.6, "bottom": "dished"},
    "liquid": {"height_m": 6.55},
    "baffles": {"count": 4, "width_m": 0.167, "height_m": 7.5, "arrangement": "symmetric"},
    "shaft": {"central": True},
    "impellers": {"count": 4, "type": "rushton", "blades": 6, "diameter_ratio": 0.3333333,
                  "blade_height_m": 0.14, "blade_length_m": 0.175,
                  "lowest_clearance_m": 1.12, "inter_impeller_clearance_m": 1.46},
}

class _FakeResp:
    text = json.dumps(GOLDEN)

class _FakeModels:
    def generate_content(self, **kwargs):  # accept model=, contents=, config=
        return _FakeResp()

class _FakeClient:
    def __init__(self, *a, **k): self.models = _FakeModels()

def test_extract_returns_validated_strparams(monkeypatch):
    monkeypatch.setattr(extract.genai, "Client", _FakeClient)
    p = extract.extract_str_params("Make a 30 kL Rushton stirred tank ...", api_key="fake")
    assert isinstance(p, STRParams)
    assert p.tank.diameter_m == 2.09
    assert p.impellers.count == 4

def test_extract_runs_schema_validators(monkeypatch):
    bad = dict(GOLDEN); bad = json.loads(json.dumps(GOLDEN))
    bad["liquid"]["height_m"] = 20.0   # > tank height -> SchemaError from STRParams
    class _BadResp: text = json.dumps(bad)
    class _BadModels:
        def generate_content(self, **k): return _BadResp()
    class _BadClient:
        def __init__(self,*a,**k): self.models=_BadModels()
    monkeypatch.setattr(extract.genai, "Client", _BadClient)
    import pytest
    from str_cad.schema import SchemaError
    with pytest.raises(SchemaError):
        extract.extract_str_params("bad reactor", api_key="fake")
