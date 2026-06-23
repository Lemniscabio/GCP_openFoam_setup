from collections.abc import Callable
from dataclasses import dataclass

import cadquery as cq

from str_cad.schema import STRParams
from str_cad.geometry.families.str.assembly import REGION_NAMES, build_fluid_domain
from str_cad.geometry.families.str.internals import build_rushton_impeller


@dataclass(frozen=True)
class Family:
    REGION_NAMES: list[str]
    build_fluid_domain: Callable[[STRParams], dict[str, cq.Shape]]


_FAMILIES = {
    "stirred_tank_reactor": Family(
        REGION_NAMES=REGION_NAMES,
        build_fluid_domain=build_fluid_domain,
    ),
}

_IMPELLERS = {
    "rushton": build_rushton_impeller,
}


def get_family(name: str) -> Family:
    try:
        return _FAMILIES[name]
    except KeyError as exc:
        raise KeyError(f"unknown geometry family: {name!r}") from exc


def get_impeller(type_: str) -> Callable[[STRParams, float], cq.Workplane]:
    try:
        return _IMPELLERS[type_]
    except KeyError as exc:
        raise KeyError(f"unknown impeller type: {type_!r}") from exc
