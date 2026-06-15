import pathlib


_FIELD_DEFINITIONS = {
    "U": ("volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)"),
    "p": ("volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0"),
    "k": ("volScalarField", "[0 2 -2 0 0 0 0]", "uniform 1"),
    "epsilon": ("volScalarField", "[0 2 -3 0 0 0 0]", "uniform 20"),
    "nut": ("volScalarField", "[0 2 -1 0 0 0 0]", "uniform 0"),
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


def _boundary_condition(field: str, role: str, rotating: bool) -> str:
    if role == "slip":
        return {
            "U": "type slip;",
            "p": "type zeroGradient;",
            "k": "type zeroGradient;",
            "epsilon": "type zeroGradient;",
            "nut": "type calculated;\n        value uniform 0;",
        }[field]

    if role != "wall":
        raise ValueError(f"unsupported patch role: {role}")

    if field == "U":
        return "type MRFnoSlip;" if rotating else "type noSlip;"

    return {
        "p": "type zeroGradient;",
        "k": "type kqRWallFunction;\n        value uniform 1;",
        "epsilon": "type epsilonWallFunction;\n        value uniform 20;",
        "nut": "type nutkWallFunction;\n        value uniform 0;",
    }[field]


def _boundary_field(field: str, cp, region_names, rotating_patches) -> str:
    entries = []
    for name in region_names:
        condition = _boundary_condition(
            field, cp.patch_roles[name], name in rotating_patches
        )
        entries.append(f"""    {name}
    {{
        {condition}
    }}""")
    return "boundaryField\n{\n" + "\n".join(entries) + "\n}\n"


def write_initial_fields(
    cp, region_names, out_dir, rotating_patches=("impellers",)
) -> pathlib.Path:
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for field, (field_class, dimensions, internal_field) in _FIELD_DEFINITIONS.items():
        contents = _foam_header(field_class, field) + f"""dimensions      {dimensions};
internalField   {internal_field};

"""
        contents += _boundary_field(field, cp, region_names, rotating_patches)
        (out_dir / field).write_text(contents)

    return out_dir
