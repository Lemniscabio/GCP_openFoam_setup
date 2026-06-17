import cadquery as cq

from str_cad.schema import STRParams


def build_baffles(p: STRParams) -> list["cadquery.Workplane"]:
    radius = p.tank.diameter_m / 2
    center_radius = radius - p.baffles.width_m / 2
    thickness_m = 0.02
    baffles = []

    for index in range(p.baffles.count):
        angle_degrees = 360 * index / p.baffles.count
        baffle = (
            cq.Workplane("XY")
            .box(p.baffles.width_m, thickness_m, p.baffles.height_m)
            .translate((center_radius, 0, p.baffles.height_m / 2))
            .rotate((0, 0, 0), (0, 0, 1), angle_degrees)
        )
        baffles.append(baffle)

    return baffles
