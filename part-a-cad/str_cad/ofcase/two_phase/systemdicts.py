import pathlib


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


def _seed_radius(sp) -> float:
    sparger = sp.operating.sparger if sp.operating is not None else None
    if sparger is not None and sparger.ring_diameter_m is not None:
        return sparger.ring_diameter_m / 2
    return 0.67 * sp.tank.diameter_m / 2


def write_set_fields_dict(sp, path) -> pathlib.Path:
    radius = _seed_radius(sp)
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
