import pathlib

from str_cad.ofcase.mrf import rotor_cylinders
from str_cad.schema import STRParams

from .geometry import sparger_radius


def _foam_header(object_name: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      {object_name};
}}

"""


def _write_dictionary(path, contents: str) -> pathlib.Path:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def write_control_dict(
    cp,
    path,
    *,
    end_time_s=60.0,
    delta_t=0.001,
    write_interval_s=0.5,
) -> pathlib.Path:
    if cp.run.verify:
        end_time_s = cp.run.verify_steps * delta_t
        write_interval_s = end_time_s

    contents = _foam_header("controlDict") + f"""application     foamRun;
solver          multiphaseEuler;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {end_time_s};
deltaT          {delta_t};
adjustTimeStep  yes;
maxCo           1.0;
maxDeltaT       0.01;
writeControl    adjustableRunTime;
writeInterval   {write_interval_s};
purgeWrite      10;
writeFormat     ascii;
writePrecision  6;
writeCompression on;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
"""
    return _write_dictionary(path, contents)


def write_fv_schemes(path) -> pathlib.Path:
    contents = _foam_header("fvSchemes") + """ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes
{
    default                             none;
    div(phi,alpha)                      Gauss vanLeer;
    div(phir,alpha,alpha)               Gauss vanLeer;
    div(alphaRhoPhi,U)                  Gauss limitedLinearV 1;
    div(phi,U)                          Gauss limitedLinearV 1;
    "div\\(alphaRhoPhi,(k|epsilon)\\)"    Gauss limitedLinear 1;
    "div\\(alphaRhoPhi,(h|e)\\)"          Gauss limitedLinear 1;
    div(alphaRhoPhi,K)                  Gauss limitedLinear 1;
    div((((alpha*rho)*nuEff)*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
"""
    return _write_dictionary(path, contents)


def write_fv_solution(path) -> pathlib.Path:
    contents = _foam_header("fvSolution") + """solvers
{
    "alpha.*"   { nAlphaCorr 1; nAlphaSubCycles 2; }
    "p_rgh.*"   { solver GAMG; smoother DIC; tolerance 1e-8; relTol 0; }
    "U.*"       { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-7; relTol 0; minIter 1; }
    "(k|epsilon).*" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-7; relTol 0; minIter 1; }
    "e.*"       { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0; minIter 1; maxIter 10; }
}
PIMPLE
{
    nOuterCorrectors 1; nCorrectors 2; nNonOrthogonalCorrectors 0;
    pRefCell 0; pRefValue 0;
    faceMomentum no; VmDdtCorrection yes; dragCorrection yes;
}
relaxationFactors { equations { ".*" 1; } }
"""
    return _write_dictionary(path, contents)


def _format_point(point: tuple[float, float, float]) -> str:
    return "(" + " ".join(f"{value:.9g}" for value in point) + ")"


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

    r_sparger = sparger_radius(sp)
    zmin = -(sp.tank.diameter_m / 2) - 0.05
    actions.append(
        f"""    {{
        name spargerFaces;
        type faceSet;
        action new;
        source patchToFace;
        sourceInfo
        {{
            patch dishedBottom;
        }}
    }}"""
    )
    actions.append(
        f"""    {{
        name spargerFaces;
        type faceSet;
        action subset;
        source cylinderToFace;
        sourceInfo
        {{
            p1 (0 0 {zmin:g});
            p2 (0 0 0.05);
            radius {r_sparger:g};
        }}
    }}"""
    )

    contents = _foam_header("topoSetDict") + "actions\n(\n" + "\n".join(actions) + "\n);\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def write_create_patch_dict(path) -> pathlib.Path:
    contents = _foam_header("createPatchDict") + """pointSync false;

patches
(
    {
        name            sparger;
        patchInfo { type patch; }
        constructFrom   set;
        set             spargerFaces;
    }
);
"""
    return _write_dictionary(path, contents)


def write_set_fields_dict(sp, path) -> pathlib.Path:
    radius = sparger_radius(sp)
    contents = _foam_header("setFieldsDict") + f"""defaultFieldValues
(
    volScalarFieldValue alpha.gas   0
    volScalarFieldValue alpha.liquid 1
);
regions
(
    cylinderToCell
    {{
        p1      (0 0 0.0);
        p2      (0 0 0.2);
        radius  {radius:g};
        fieldValues
        (
            volScalarFieldValue alpha.gas    0.05
            volScalarFieldValue alpha.liquid 0.95
        );
    }}
);
"""
    return _write_dictionary(path, contents)
