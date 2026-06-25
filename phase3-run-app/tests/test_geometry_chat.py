from core.geometry_chat import run_geometry_chat
from core.schema_doc import str_params_schema_doc

_VALID_SPEC = {
    "family": "stirred_tank_reactor",
    "physics": "single_phase",
    "tank": {"diameter_m": 2.09, "height_m": 9.6, "bottom": "dished"},
    "liquid": {"height_m": 6.55},
    "baffles": {"count": 4, "height_m": 7.5, "arrangement": "symmetric"},
    "shaft": {"central": True},
    "impellers": {
        "count": 4, "type": "rushton", "blades": 6, "diameter_ratio": 0.3333333,
        "lowest_clearance_m": 1.12, "inter_impeller_clearance_m": 1.46,
    },
    "operating": {"rpm": 100},
}


def _gen_returning(*texts):
    """A fake generator that returns the given texts in order across calls."""
    calls = list(texts)

    def gen(_messages, _system):
        return calls.pop(0)

    return gen


def test_schema_doc_lists_required_fields_and_correlations():
    doc = str_params_schema_doc()
    for token in ["physics", "tank.diameter_m", "diameter_ratio", "gas_flow_vvm",
                  "D/4", "tank.diameter_m / 12", "two_phase"]:
        assert token in doc, token


def test_clarifying_turn_returns_no_spec():
    out = run_geometry_chat(
        [{"role": "user", "content": "make me a reactor"}],
        api_key="x",
        generate=_gen_returning("How many impellers, and what tank diameter?"),
    )
    assert out["spec"] is None
    assert "impellers" in out["reply"].lower()


def test_finalized_turn_returns_validated_spec():
    import json
    reply = "Building a 4-impeller dished tank.\n```json\n" + json.dumps(_VALID_SPEC) + "\n```"
    out = run_geometry_chat(
        [{"role": "user", "content": "30kL dished tank, 4 rushton, 100 rpm"}],
        api_key="x",
        generate=_gen_returning(reply),
    )
    assert out["spec"] is not None
    assert out["spec"]["tank"]["diameter_m"] == 2.09
    assert out["spec"]["physics"] == "single_phase"
    assert "```" not in out["reply"]  # json block stripped from the human reply


def test_invalid_spec_is_retried_then_recovers():
    import json
    bad = dict(_VALID_SPEC, liquid={"height_m": 99})  # liquid > tank height -> invalid
    bad_reply = "ok\n```json\n" + json.dumps(bad) + "\n```"
    good_reply = "fixed\n```json\n" + json.dumps(_VALID_SPEC) + "\n```"
    out = run_geometry_chat(
        [{"role": "user", "content": "build it"}],
        api_key="x",
        generate=_gen_returning(bad_reply, good_reply),  # first invalid, then corrected
    )
    assert out["spec"] is not None
    assert out["spec"]["liquid"]["height_m"] == 6.55


def test_persistently_invalid_gives_up_gracefully():
    import json
    bad = dict(_VALID_SPEC, liquid={"height_m": 99})
    bad_reply = "```json\n" + json.dumps(bad) + "\n```"
    out = run_geometry_chat(
        [{"role": "user", "content": "build it"}],
        api_key="x",
        generate=_gen_returning(bad_reply, bad_reply, bad_reply),
    )
    assert out["spec"] is None
    assert "manually" in out["reply"].lower()
