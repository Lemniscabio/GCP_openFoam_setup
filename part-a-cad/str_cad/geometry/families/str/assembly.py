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
    impeller_diameter = p.impeller_diameter_m
    impeller_radius = impeller_diameter / 2
    shaft_radius = max(0.03, p.impeller_diameter_m / 20)
    blade_height = p.impellers.blade_height_m
    impeller_heights = impeller_z_positions(p)
    tolerance = 1e-3 * max(height, 2 * tank_radius, 1.0)
    regions = {name: [] for name in REGION_NAMES}

    for face in build_fluid_solid(p).Faces():
        center = face.Center()
        radial_distance = math.hypot(center.x, center.y)
        geometry_type = face.geomType()
        is_planar_vertical = False

        if geometry_type == "PLANE":
            try:
                is_planar_vertical = abs(face.normalAt().z) > 0.9
            except Exception:
                pass

        if is_planar_vertical and center.z >= height - tolerance:
            region = "liquidSurface"
        elif center.z < -tolerance:
            region = "dishedBottom"
        elif is_planar_vertical and center.z <= tolerance:
            # Flat-bottom disc sits at z~0 (no curved head below 0); it is the
            # vessel bottom, so group it with dishedBottom (the top was already
            # handled above; impeller discs sit at z>tolerance).
            region = "dishedBottom"
        elif radial_distance <= impeller_radius + tolerance and any(
            abs(center.z - z) <= blade_height / 2 + tolerance
            for z in impeller_heights
        ):
            region = "impellers"
        elif geometry_type == "CYLINDER" and radial_distance <= 2 * shaft_radius:
            region = "shaft"
        elif geometry_type == "CYLINDER" and radial_distance >= impeller_diameter:
            region = "tankWall"
        else:
            region = "baffles"

        regions[region].append(face)

    return {
        name: cq.Compound.makeCompound(faces)
        for name, faces in regions.items()
    }
