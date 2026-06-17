import cadquery as cq

from str_cad.schema import STRParams


def impeller_z_positions(p: STRParams) -> list[float]:
    return [
        p.impellers.lowest_clearance_m
        + index * p.impellers.inter_impeller_clearance_m
        for index in range(p.impellers.count)
    ]


def build_shaft(p: STRParams) -> "cadquery.Workplane":
    radius_m = max(0.03, p.impeller_diameter_m / 20)
    return cq.Workplane("XY").circle(radius_m).extrude(p.liquid.height_m)


def build_impellers(p: STRParams) -> list["cadquery.Workplane"]:
    diameter_m = p.impeller_diameter_m
    disc_thickness_m = 0.01
    hub_radius_m = diameter_m / 12
    hub_height_m = max(p.impellers.blade_height_m, disc_thickness_m)
    blade_center_radius_m = diameter_m / 2 - p.impellers.blade_length_m / 2
    impellers = []

    for z_m in impeller_z_positions(p):
        turbine = (
            cq.Workplane("XY")
            .workplane(offset=z_m - disc_thickness_m / 2)
            .circle(0.66 * diameter_m / 2)
            .extrude(disc_thickness_m)
        )
        hub = (
            cq.Workplane("XY")
            .workplane(offset=z_m - hub_height_m / 2)
            .circle(hub_radius_m)
            .extrude(hub_height_m)
        )
        turbine = turbine.union(hub)

        for index in range(p.impellers.blades):
            angle_degrees = 360 * index / p.impellers.blades
            blade = (
                cq.Workplane("XY")
                .box(
                    p.impellers.blade_length_m,
                    disc_thickness_m,
                    p.impellers.blade_height_m,
                )
                .translate((blade_center_radius_m, 0, z_m))
                .rotate((0, 0, 0), (0, 0, 1), angle_degrees)
            )
            turbine = turbine.union(blade)

        impellers.append(turbine)

    return impellers
