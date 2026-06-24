import math

from str_cad.schema import STRParams


def sparger_radius(sp: STRParams) -> float:
    sparger = sp.operating.sparger if sp.operating is not None else None
    if sparger is not None and sparger.ring_diameter_m is not None:
        return sparger.ring_diameter_m / 2
    return 0.67 * sp.tank.diameter_m / 2


def sparger_inlet_velocity(sp: STRParams) -> float:
    r_tank = sp.tank.diameter_m / 2
    v_liquid = math.pi * r_tank**2 * sp.liquid.height_m
    q = sp.operating.gas_flow_vvm * v_liquid / 60.0
    area = math.pi * sparger_radius(sp) ** 2
    return q / area