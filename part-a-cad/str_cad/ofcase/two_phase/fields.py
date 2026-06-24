import pathlib

from .geometry import sparger_inlet_velocity


STATIC_WALLS = {"tankWall", "dishedBottom", "baffles"}
ROTATING_WALL = "shaft"
MRF = "impellers"
TOP = "liquidSurface"

_FIELD_DEFINITIONS = {
    "U.liquid": ("volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)"),
    "U.gas": ("volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)"),
    "T.liquid": ("volScalarField", "[0 0 0 1 0 0 0]", "uniform 300"),
    "T.gas": ("volScalarField", "[0 0 0 1 0 0 0]", "uniform 300"),
    "alpha.gas": ("volScalarField", "[0 0 0 0 0 0 0]", "uniform 0"),
    "alpha.liquid": ("volScalarField", "[0 0 0 0 0 0 0]", "uniform 1"),
    "alphat.liquid": ("volScalarField", "[1 -1 -1 0 0 0 0]", "uniform 0"),
    "k.liquid": ("volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0.1"),
    "epsilon.liquid": ("volScalarField", "[0 2 -3 0 0 0 0]", "uniform 0.1"),
    "nut.liquid": ("volScalarField", "[0 2 -1 0 0 0 0]", "uniform 0"),
    "p": ("volScalarField", "[1 -1 -2 0 0 0 0]", "uniform 0"),
    "p_rgh": ("volScalarField", "[1 -1 -2 0 0 0 0]", "uniform 0"),
}


def _foam_header(field_class: str, object_name: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       {field_class};
    object      {object_name};
}}

"""


def _velocity_condition(field: str, patch_name: str, omega_rad_s: float) -> str:
    if patch_name in STATIC_WALLS:
        return "type noSlip;" if field == "U.liquid" else "type slip;"
    if patch_name == MRF:
        return "type MRFnoSlip;"
    if patch_name == ROTATING_WALL:
        return f"""type rotatingWallVelocity;
        origin (0 0 0);
        axis (0 0 1);
        omega constant {omega_rad_s:.5f};"""
    if patch_name == TOP:
        return """type pressureInletOutletVelocity;
        value uniform (0 0 0);"""
    raise ValueError(f"unsupported patch: {patch_name}")


def _zero_gradient_except_top(patch_name: str, top_condition: str) -> str:
    if patch_name in STATIC_WALLS or patch_name in {MRF, ROTATING_WALL}:
        return "type zeroGradient;"
    if patch_name == TOP:
        return top_condition
    raise ValueError(f"unsupported patch: {patch_name}")


def _scalar_condition(field: str, patch_name: str) -> str:
    if field in {"T.liquid", "T.gas"}:
        return _zero_gradient_except_top(
            patch_name,
            """type inletOutlet;
        inletValue uniform 300;
        value uniform 300;""",
        )

    if field == "alpha.gas":
        return _zero_gradient_except_top(
            patch_name,
            """type inletOutlet;
        phi phi.gas;
        inletValue uniform 0;
        value uniform 0;""",
        )

    if field == "alpha.liquid":
        return _zero_gradient_except_top(
            patch_name,
            """type inletOutlet;
        phi phi.liquid;
        inletValue uniform 1;
        value uniform 1;""",
        )

    if field in {"alphat.liquid", "p"}:
        return "type calculated;\n        value uniform 0;"

    if field == "k.liquid":
        if patch_name == TOP:
            return "type zeroGradient;"
        if patch_name in STATIC_WALLS or patch_name in {MRF, ROTATING_WALL}:
            return "type kqRWallFunction;\n        value uniform 0.1;"
        raise ValueError(f"unsupported patch: {patch_name}")

    if field == "epsilon.liquid":
        if patch_name == TOP:
            return "type zeroGradient;"
        if patch_name in STATIC_WALLS or patch_name in {MRF, ROTATING_WALL}:
            return "type epsilonWallFunction;\n        value uniform 0.1;"
        raise ValueError(f"unsupported patch: {patch_name}")

    if field == "nut.liquid":
        if patch_name == TOP:
            return "type calculated;\n        value uniform 0;"
        if patch_name in STATIC_WALLS or patch_name in {MRF, ROTATING_WALL}:
            return "type nutkWallFunction;\n        value uniform 0;"
        raise ValueError(f"unsupported patch: {patch_name}")

    if field == "p_rgh":
        if patch_name == TOP:
            return """type prghPressure;
        p uniform 0;
        value uniform 0;"""
        if patch_name in STATIC_WALLS or patch_name in {MRF, ROTATING_WALL}:
            return "type fixedFluxPressure;\n        value uniform 0;"
        raise ValueError(f"unsupported patch: {patch_name}")

    raise ValueError(f"unsupported field: {field}")


def _boundary_condition(field: str, patch_name: str, omega_rad_s: float) -> str:
    if field.startswith("U."):
        return _velocity_condition(field, patch_name, omega_rad_s)
    return _scalar_condition(field, patch_name)


def _sparger_condition(field: str, u_super: float) -> str:
    if field == "U.gas":
        return f"""type fixedValue;
        value uniform (0 0 {u_super:.5f});"""
    if field == "U.liquid":
        return "type fixedValue;\n        value uniform (0 0 0);"
    if field == "alpha.gas":
        return "type fixedValue;\n        value uniform 1;"
    if field == "alpha.liquid":
        return "type fixedValue;\n        value uniform 0;"
    if field == "p":
        return "type calculated;\n        value uniform 0;"
    if field == "p_rgh":
        return "type fixedFluxPressure;\n        value uniform 0;"
    if field == "k.liquid":
        return "type fixedValue;\n        value uniform 1e-4;"
    if field == "epsilon.liquid":
        return "type fixedValue;\n        value uniform 1e-4;"
    if field == "nut.liquid":
        return "type calculated;\n        value uniform 0;"
    if field == "alphat.liquid":
        return "type calculated;\n        value uniform 0;"
    if field in {"T.gas", "T.liquid"}:
        return "type zeroGradient;"
    raise ValueError(f"unsupported field for sparger: {field}")


def _boundary_field(field: str, cp, region_names, u_super: float) -> str:
    entries = []
    for name in region_names:
        condition = _boundary_condition(field, name, cp.omega_rad_s)
        entries.append(f"""    {name}
    {{
        {condition}
    }}""")
    entries.append(f"""    sparger
    {{
        {_sparger_condition(field, u_super)}
    }}""")
    return "boundaryField\n{\n" + "\n".join(entries) + "\n}\n"


def write_initial_fields_two_phase(sp, cp, region_names, out_dir) -> pathlib.Path:
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    u_super = sparger_inlet_velocity(sp)

    for field, (field_class, dimensions, internal_field) in _FIELD_DEFINITIONS.items():
        contents = _foam_header(field_class, field) + f"""dimensions      {dimensions};
internalField   {internal_field};

"""
        contents += _boundary_field(field, cp, region_names, u_super)
        (out_dir / field).write_text(contents)

    return out_dir
