import pathlib
from typing import Any


def _foam_header(object_name: str, class_name: str = "dictionary") -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       {class_name};
    object      {object_name};
}}

"""


def _write(path, contents: str) -> pathlib.Path:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def _param(sp: Any, name: str, default: float) -> float:
    if isinstance(sp, dict):
        return sp.get(name, default)
    return getattr(sp, name, default)


def write_phase_properties(sp, path) -> pathlib.Path:
    gas_diameter = _param(sp, "gas_bubble_diameter_m", 3e-3)
    liquid_diameter = _param(sp, "liquid_diameter_m", 1e-2)
    contents = _foam_header("phaseProperties") + f"""type basicMultiphaseSystem;

phases (gas liquid);

gas
{{
    type            pureIsothermalPhaseModel;
    diameterModel   constant;
    constantCoeffs
    {{
        d  {gas_diameter:g};
    }}
    residualAlpha   1e-6;
}}
liquid
{{
    type            pureIsothermalPhaseModel;
    diameterModel   constant;
    constantCoeffs
    {{
        d  {liquid_diameter:g};
    }}
    residualAlpha   1e-6;
}}
blending
{{
    default
    {{
        type continuous;
        phase liquid;
    }}
}}
surfaceTension
{{
    gas_liquid
    {{
        type constant;
        sigma 0.072;
    }}
}}
interfaceCompression
{{
    gas_liquid 0;
}}
drag
{{
    gas_dispersedIn_liquid
    {{
        type SchillerNaumann;
    }}
}}
virtualMass
{{
    gas_dispersedIn_liquid
    {{
        type constantCoefficient;
        Cvm 0.5;
    }}
}}
heatTransfer
{{
}}
phaseTransfer
{{
}}
lift
{{
}}
wallLubrication
{{
}}
turbulentDispersion
{{
    gas_dispersedIn_liquid
    {{
        type Burns;
        sigma 0.9;
    }}
}}
"""
    return _write(path, contents)


def write_physical_properties_gas(sp, path) -> pathlib.Path:
    contents = _foam_header("physicalProperties.gas") + """thermoType
{
    type heRhoThermo;
    mixture pureMixture;
    transport const;
    thermo hConst;
    equationOfState rhoConst;
    specie specie;
    energy sensibleInternalEnergy;
}
mixture
{
    specie
    {
        molWeight 28.9;
    }
    equationOfState
    {
        rho 1.2;
    }
    thermodynamics
    {
        Cp 1007;
        hf 0;
    }
    transport
    {
        mu 1.8e-5;
        Pr 0.7;
    }
}
"""
    return _write(path, contents)


def write_physical_properties_liquid(sp, path) -> pathlib.Path:
    contents = _foam_header("physicalProperties.liquid") + """thermoType
{
    type heRhoThermo;
    mixture pureMixture;
    transport const;
    thermo eConst;
    equationOfState rhoConst;
    specie specie;
    energy sensibleInternalEnergy;
}
mixture
{
    specie
    {
        molWeight 18;
    }
    equationOfState
    {
        rho 1000;
    }
    thermodynamics
    {
        Cv 4182;
        hf 0;
    }
    transport
    {
        mu 1e-3;
        Pr 7;
    }
}
"""
    return _write(path, contents)


def write_momentum_transport_gas(path) -> pathlib.Path:
    contents = _foam_header("momentumTransport.gas") + """simulationType  laminar;
"""
    return _write(path, contents)


def write_momentum_transport_liquid(path) -> pathlib.Path:
    contents = _foam_header("momentumTransport.liquid") + """simulationType  RAS;
RAS
{
    model kEpsilon;
    turbulence on;
    printCoeffs on;
}
"""
    return _write(path, contents)


def write_gravity(path) -> pathlib.Path:
    contents = _foam_header("g", "uniformDimensionedVectorField") + """dimensions      [0 1 -2 0 0 0 0];
value           (0 0 -9.81);
"""
    return _write(path, contents)
