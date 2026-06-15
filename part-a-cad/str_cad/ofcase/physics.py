import pathlib

from str_cad.ofcase.caseparams import CaseParams


def _foam_header(object_name: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      {object_name};
}}

"""


def write_physical_properties(cp: CaseParams, path) -> pathlib.Path:
    path = pathlib.Path(path)
    contents = _foam_header("physicalProperties") + f"""viscosityModel  constant;
nu              [0 2 -1 0 0 0 0] {cp.viscosity_m2_s};
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def write_momentum_transport(path) -> pathlib.Path:
    path = pathlib.Path(path)
    contents = _foam_header("momentumTransport") + """simulationType RAS;

RAS
{
    model           kEpsilon;
    turbulence      on;
    printCoeffs     on;
}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path
