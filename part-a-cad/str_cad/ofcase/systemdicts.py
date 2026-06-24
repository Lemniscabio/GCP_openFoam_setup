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


def write_control_dict(cp, path) -> pathlib.Path:
    end_time = cp.run.verify_steps if cp.run.verify else cp.run.end_time
    write_interval = cp.run.verify_steps if cp.run.verify else cp.run.write_interval
    contents = _foam_header("controlDict") + f"""application     foamRun;
solver          incompressibleFluid;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {end_time};
deltaT          1;
writeControl    timeStep;
writeInterval   {write_interval};
purgeWrite      0;
writeFormat     ascii;
writePrecision  6;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
"""
    return _write_dictionary(path, contents)


def write_fv_schemes(path) -> pathlib.Path:
    contents = _foam_header("fvSchemes") + """ddtSchemes
{
    default steadyState;
}

gradSchemes
{
    default Gauss linear;
}

divSchemes
{
    default none;
    div(phi,U) bounded Gauss limitedLinearV 1;
    div(phi,k) bounded Gauss limitedLinear 1;
    div(phi,epsilon) bounded Gauss limitedLinear 1;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
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
    return _write_dictionary(path, contents)


def write_fv_solution(cp, path) -> pathlib.Path:
    contents = _foam_header("fvSolution") + """solvers
{
    p
    {
        solver GAMG;
        tolerance 1e-08;
        relTol 0.05;
        smoother GaussSeidel;
        nCellsInCoarsestLevel 20;
    }
    U
    {
        solver smoothSolver;
        smoother GaussSeidel;
        nSweeps 2;
        tolerance 1e-07;
        relTol 0.1;
    }
    k
    {
        solver smoothSolver;
        smoother GaussSeidel;
        nSweeps 2;
        tolerance 1e-07;
        relTol 0.1;
    }
    epsilon
    {
        solver smoothSolver;
        smoother GaussSeidel;
        nSweeps 2;
        tolerance 1e-07;
        relTol 0.1;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    pRefCell 0;
    pRefValue 0;
}

relaxationFactors
{
    fields
    {
        p 0.3;
    }
    equations
    {
        U 0.5;
        k 0.5;
        epsilon 0.5;
    }
}
"""
    return _write_dictionary(path, contents)


def write_decompose_par(cp, path) -> pathlib.Path:
    contents = _foam_header("decomposeParDict") + f"""numberOfSubdomains {cp.run.cores};
method scotch;
"""
    return _write_dictionary(path, contents)
