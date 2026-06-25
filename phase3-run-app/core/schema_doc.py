"""Compact description of the STRParams geometry spec for the chat agent.

The agent produces an STRParams JSON spec — the same object the form produces. It needs
the *shape* of that spec, not the geometry code. The two example specs below are derived
by validating minimal inputs through the real STRParams model, so the correlations
(blade=D/4, baffle=T/12, ...) are filled by the actual schema and never drift from code.
"""
import json

from str_cad.schema import STRParams

# Minimal inputs -> the validator fills blade/baffle correlations, giving honest examples.
_SINGLE_INPUT = {
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
_TWO_INPUT = {
    **_SINGLE_INPUT,
    "physics": "two_phase",
    "operating": {"rpm": 100, "gas_flow_vvm": 0.5},
}

_GUIDE = """\
You collect the parameters for a stirred-tank-reactor geometry and produce ONE JSON spec
(an STRParams object). You never compute physics or mesh — you only fill the spec; a
deterministic generator builds the geometry and OpenFOAM case from it.

REQUIRED fields (ask the user for anything missing that is not auto-filled below):
- physics: "single_phase" or "two_phase"
- tank.diameter_m, tank.height_m, tank.bottom ("dished" or "flat")
- liquid.height_m
- baffles.count, baffles.height_m, baffles.arrangement (usually "symmetric")
- shaft.central (true for a central shaft — the only supported option)
- impellers.count, impellers.type ("rushton" is the only supported type),
  impellers.blades, impellers.diameter_ratio (D/T, e.g. 0.333),
  impellers.lowest_clearance_m, impellers.inter_impeller_clearance_m
- operating.rpm
- TWO-PHASE ONLY: operating.gas_flow_vvm (> 0), and optionally
  operating.sparger.ring_diameter_m

AUTO-FILLED if the user does not give them (do NOT ask unless the user raises them):
- impellers.blade_length_m -> D/4 and impellers.blade_height_m -> D/5
  (D = impeller diameter = tank.diameter_m * impellers.diameter_ratio)
- baffles.width_m -> tank.diameter_m / 12
You may omit these from the spec; the generator fills them.

CONSTRAINTS (the spec is rejected if violated — make sure your spec satisfies them):
- liquid.height_m must be <= tank.height_m
- impellers must fit below the liquid:
  lowest_clearance_m + (count - 1) * inter_impeller_clearance_m < liquid.height_m
- impellers.diameter_ratio should be between 0 and ~0.7

family is always "stirred_tank_reactor"."""


def str_params_schema_doc() -> str:
    """Full guidance block the chat agent receives as system knowledge."""
    return "\n\n".join(
        [
            _GUIDE,
            "Example single-phase spec:\n" + json.dumps(_single_example(), indent=2),
            "Example two-phase spec:\n" + json.dumps(_two_example(), indent=2),
        ]
    )


def _single_example() -> dict:
    return STRParams.model_validate(_SINGLE_INPUT).model_dump(mode="json")


def _two_example() -> dict:
    return STRParams.model_validate(_TWO_INPUT).model_dump(mode="json")
