import json
from pathlib import Path

import pytest

from str_cad.geometry.families.str.internals import build_impellers
from str_cad.geometry.registry import get_family, get_impeller
from str_cad.schema import STRParams


EXPECTED_REGION_NAMES = [
    "tankWall",
    "dishedBottom",
    "baffles",
    "shaft",
    "impellers",
    "liquidSurface",
]


def _reactor_30kl() -> STRParams:
    data = json.loads(Path("examples/reactor_30kl.json").read_text())
    return STRParams.model_validate(data)


def test_registry_returns_str_family():
    family = get_family("stirred_tank_reactor")
    assert family.REGION_NAMES == EXPECTED_REGION_NAMES


def test_unknown_family_raises():
    with pytest.raises(KeyError):
        get_family("nope")


def test_unknown_impeller_type_raises():
    with pytest.raises(KeyError):
        get_impeller("nonsense")


def test_rushton_registered():
    assert callable(get_impeller("rushton"))


def test_build_impellers_unchanged():
    p = _reactor_30kl()

    impellers = build_impellers(p)
    assert len(impellers) == p.impellers.count

    domain = get_family("stirred_tank_reactor").build_fluid_domain(p)
    assert list(domain.keys()) == EXPECTED_REGION_NAMES
    for name, shape in domain.items():
        assert shape.Area() > 0, name
