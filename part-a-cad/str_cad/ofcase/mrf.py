import pathlib

from str_cad.geometry.internals import impeller_z_positions
from str_cad.ofcase.caseparams import CaseParams
from str_cad.schema import STRParams


def _foam_header(object_name: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      {object_name};
}}

"""


def _format_point(point: tuple[float, float, float]) -> str:
    return "(" + " ".join(f"{value:.9g}" for value in point) + ")"


def rotor_cylinders(sp: STRParams) -> list[dict]:
    height = sp.impellers.blade_height_m * 1.5
    diameter = sp.impeller_diameter_m
    return [
        {
            "point1": (0.0, 0.0, z - height / 2),
            "point2": (0.0, 0.0, z + height / 2),
            "radius": 0.55 * diameter,
        }
        for z in impeller_z_positions(sp)
    ]


def write_toposet_dict(sp: STRParams, path) -> pathlib.Path:
    path = pathlib.Path(path)
    actions = []
    for index, cylinder in enumerate(rotor_cylinders(sp)):
        action = "new" if index == 0 else "add"
        actions.append(
            f"""    {{
        name rotor;
        type cellSet;
        action {action};
        source cylinderToCell;
        point1 {_format_point(cylinder['point1'])};
        point2 {_format_point(cylinder['point2'])};
        radius {cylinder['radius']:.9g};
    }}"""
        )

    actions.append(
        """    {
        name rotor;
        type cellZoneSet;
        action new;
        source setToCellZone;
        set rotor;
    }"""
    )
    contents = _foam_header("topoSetDict") + "actions\n(\n" + "\n".join(actions) + "\n);\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def write_mrf_properties(
    sp: STRParams, cp: CaseParams, path
) -> pathlib.Path:
    path = pathlib.Path(path)
    contents = _foam_header("MRFProperties") + f"""MRF
{{
    cellZone    rotor;
    origin      (0 0 0);
    axis        (0 0 1);
    omega       {cp.rpm:g} [rpm];
}}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path
