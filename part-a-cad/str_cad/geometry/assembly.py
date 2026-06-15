import math

import cadquery as cq

from str_cad.schema import STRParams


REGION_NAMES = [
    "tankWall",
    "dishedBottom",
    "baffles",
    "shaft",
    "impellers",
    "liquidSurface",
]


def build_fluid_solid(p: STRParams) -> "cadquery.Solid":
    """Build the vessel liquid region with all internal solids removed."""
    from .baffles import build_baffles
    from .internals import build_impellers, build_shaft
    from .vessel import build_vessel_shell

    result = build_vessel_shell(p)
    for solid in [build_shaft(p), *build_impellers(p), *build_baffles(p)]:
        result = result.cut(solid)
    return result.val()


def build_fluid_domain(p: STRParams) -> dict[str, "cadquery.Shape"]:
    """Group every fluid-boundary face into one named boundary region."""
    from .internals import impeller_z_positions

    height = p.liquid.height_m
    tank_radius = p.tank.diameter_m / 2
    impeller_radius = p.impeller_diameter_m / 2
    shaft_radius = max(0.03, p.impeller_diameter_m / 20)
    blade_height = p.impellers.blade_height_m
    impeller_heights = impeller_z_positions(p)
    tolerance = 1e-3 * max(height, p.tank.diameter_m, 1.0)
    wall_tolerance = max(tolerance, 0.75 * p.baffles.width_m)
    regions = {name: [] for name in REGION_NAMES}

    for face in build_fluid_solid(p).Faces():
        center = face.Center()
        radial_distance = math.hypot(center.x, center.y)

        if center.z >= height - tolerance:
            region = "liquidSurface"
        elif center.z < -tolerance:
            region = "dishedBottom"
        elif radial_distance >= tank_radius - wall_tolerance:
            region = "tankWall"
        elif radial_distance <= shaft_radius + tolerance:
            region = "shaft"
        elif radial_distance <= impeller_radius + tolerance and any(
            abs(center.z - z) <= blade_height + tolerance
            for z in impeller_heights
        ):
            region = "impellers"
        else:
            region = "baffles"

        regions[region].append(face)

    return {
        name: cq.Compound.makeCompound(faces)
        for name, faces in regions.items()
    }
