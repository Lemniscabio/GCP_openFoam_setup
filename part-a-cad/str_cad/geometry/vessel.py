import math

import cadquery as cq

from str_cad.schema import STRParams


def build_vessel_shell(p: STRParams) -> "cadquery.Workplane":
    radius = p.tank.diameter_m / 2
    cylinder = cq.Workplane("XY").circle(radius).extrude(p.liquid.height_m)
    head = (
        cq.Workplane("XZ")
        .moveTo(0, 0)
        .lineTo(radius, 0)
        .threePointArc(
            (radius / math.sqrt(2), -radius / math.sqrt(2)),
            (0, -radius),
        )
        .close()
        .revolve(360, (0, 0), (0, 1))
    )
    return cylinder.union(head)
