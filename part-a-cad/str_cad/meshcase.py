import argparse
import json
import math
import pathlib
import shutil

import trimesh

from .geometry.assembly import REGION_NAMES


def _foam_header(object_name: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      {object_name};
}}

"""


def _combined_bounds(surface_paths: list[pathlib.Path]):
    bounds = [trimesh.load_mesh(path, process=False).bounds for path in surface_paths]
    minimum = bounds[0][0].copy()
    maximum = bounds[0][1].copy()
    for lower, upper in bounds[1:]:
        minimum = minimum.clip(max=lower)
        maximum = maximum.clip(min=upper)
    span = maximum - minimum
    margin = span * 0.1
    return minimum - margin, maximum + margin


def _cell_counts(minimum, maximum) -> tuple[int, int, int]:
    span = maximum - minimum
    cell_size = float(max(span)) / 30
    return tuple(max(1, round(float(length) / cell_size)) for length in span)


def _format_point(point) -> str:
    return "(" + " ".join(f"{float(value):.9g}" for value in point) + ")"


def _control_dict() -> str:
    return _foam_header("controlDict") + """application     foamRun;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         1;
deltaT          1;
writeControl    timeStep;
writeInterval   1;
purgeWrite      0;
writeFormat     ascii;
writePrecision  6;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
"""


def _block_mesh_dict(minimum, maximum, cells) -> str:
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    nx, ny, nz = cells
    return _foam_header("blockMeshDict") + f"""convertToMeters 1;

vertices
(
    ({x0:.9g} {y0:.9g} {z0:.9g})
    ({x1:.9g} {y0:.9g} {z0:.9g})
    ({x1:.9g} {y1:.9g} {z0:.9g})
    ({x0:.9g} {y1:.9g} {z0:.9g})
    ({x0:.9g} {y0:.9g} {z1:.9g})
    ({x1:.9g} {y0:.9g} {z1:.9g})
    ({x1:.9g} {y1:.9g} {z1:.9g})
    ({x0:.9g} {y1:.9g} {z1:.9g})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

edges ();

boundary
(
    allBoundary
    {{
        type patch;
        faces
        (
            (0 4 7 3)
            (1 2 6 5)
            (0 1 5 4)
            (3 7 6 2)
            (0 3 2 1)
            (4 5 6 7)
        );
    }}
);

mergePatchPairs ();
"""


def _snappy_hex_mesh_dict(location_in_mesh) -> str:
    geometry = "\n".join(
        f"""    {name}.stl
    {{
        type triSurfaceMesh;
        name {name};
    }}"""
        for name in REGION_NAMES
    )
    refinement = "\n".join(
        f"""        {name}
        {{
            level ({'2 2' if name in {'shaft', 'impellers'} else '1 1'});
            patchInfo {{ type wall; }}
        }}"""
        for name in REGION_NAMES
    )
    return _foam_header("snappyHexMeshDict") + f"""castellatedMesh true;
snap            true;
addLayers       false;

geometry
{{
{geometry}
}}

castellatedMeshControls
{{
    maxLocalCells       1000000;
    maxGlobalCells      2000000;
    minRefinementCells  0;
    maxLoadUnbalance    0.10;
    nCellsBetweenLevels 3;
    features            ();
    refinementSurfaces
    {{
{refinement}
    }}
    resolveFeatureAngle 30;
    refinementRegions   {{}}
    locationInMesh      {_format_point(location_in_mesh)};
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch     3;
    tolerance        2.0;
    nSolveIter       30;
    nRelaxIter       5;
    nFeatureSnapIter 10;
    implicitFeatureSnap false;
    explicitFeatureSnap true;
    multiRegionFeatureSnap false;
}}

addLayersControls
{{
    relativeSizes true;
    layers {{}}
}}

meshQualityControls
{{
    #include "meshQualityDict"
}}

debug 0;
mergeTolerance 1e-6;
"""


def _fv_schemes() -> str:
    return _foam_header("fvSchemes") + """ddtSchemes
{
    default Euler;
}
gradSchemes
{
    default Gauss linear;
}
divSchemes
{
    default none;
}
laplacianSchemes
{
    default Gauss linear corrected;
}
interpolationSchemes
{
    default linear;
}
snGradSchemes
{
    default corrected;
}
"""


def _fv_solution() -> str:
    return _foam_header("fvSolution") + """solvers
{
}
"""


def _mesh_quality_dict() -> str:
    return _foam_header("meshQualityDict") + """#includeEtc "caseDicts/meshQualityDict"
"""


def make_mesh_case(geometry_dir, case_dir) -> pathlib.Path:
    geometry_dir = pathlib.Path(geometry_dir)
    case_dir = pathlib.Path(case_dir)
    system_dir = case_dir / "system"
    tri_surface_dir = case_dir / "constant" / "triSurface"
    system_dir.mkdir(parents=True, exist_ok=True)
    tri_surface_dir.mkdir(parents=True, exist_ok=True)

    source_paths = [geometry_dir / "geometry" / f"{name}.stl" for name in REGION_NAMES]
    for source in source_paths:
        shutil.copy2(source, tri_surface_dir / source.name)

    minimum, maximum = _combined_bounds(source_paths)
    params = json.loads((geometry_dir / "str-params.json").read_text())
    radius = params["tank"]["diameter_m"] / 2
    liquid_height = params["liquid"]["height_m"]
    radial_position = 0.4 * radius
    location_in_mesh = (
        radial_position * math.cos(math.pi / 4),
        radial_position * math.sin(math.pi / 4),
        0.5 * liquid_height,
    )

    dictionaries = {
        "controlDict": _control_dict(),
        "blockMeshDict": _block_mesh_dict(
            minimum, maximum, _cell_counts(minimum, maximum)
        ),
        "snappyHexMeshDict": _snappy_hex_mesh_dict(location_in_mesh),
        "fvSchemes": _fv_schemes(),
        "fvSolution": _fv_solution(),
        "meshQualityDict": _mesh_quality_dict(),
    }
    for name, contents in dictionaries.items():
        (system_dir / name).write_text(contents)

    return case_dir


def _main() -> None:
    parser = argparse.ArgumentParser(description="Generate an OpenFOAM STR meshing case")
    parser.add_argument("geometry_dir", type=pathlib.Path)
    parser.add_argument("case_dir", type=pathlib.Path)
    args = parser.parse_args()
    print(make_mesh_case(args.geometry_dir, args.case_dir))


if __name__ == "__main__":
    _main()
