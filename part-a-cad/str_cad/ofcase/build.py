import argparse
import json
import pathlib

from str_cad.geometry.assembly import REGION_NAMES
from str_cad.meshcase import make_mesh_case
from str_cad.schema import STRParams

from .caseparams import CaseParams
from .command import write_command_sh, write_metadata_json
from .fields import write_initial_fields
from .mrf import write_mrf_properties, write_toposet_dict
from .physics import write_momentum_transport, write_physical_properties
from .systemdicts import (
    write_control_dict,
    write_decompose_par,
    write_fv_schemes,
    write_fv_solution,
)


def build_case(case_params, geo_dir, out_dir) -> pathlib.Path:
    geo_dir = pathlib.Path(geo_dir)
    out_dir = pathlib.Path(out_dir)
    schema = json.loads((geo_dir / "str-params.json").read_text())
    sp = STRParams.model_validate(schema)
    if sp.physics == "two_phase":
        from .two_phase.build import build_two_phase_case

        return build_two_phase_case(case_params, geo_dir, out_dir)

    make_mesh_case(geo_dir, out_dir)

    system_dir = out_dir / "system"
    constant_dir = out_dir / "constant"
    write_control_dict(case_params, system_dir / "controlDict")
    write_fv_schemes(system_dir / "fvSchemes")
    write_fv_solution(case_params, system_dir / "fvSolution")
    write_toposet_dict(sp, system_dir / "topoSetDict")
    write_decompose_par(case_params, system_dir / "decomposeParDict")
    write_physical_properties(case_params, constant_dir / "physicalProperties")
    write_momentum_transport(constant_dir / "momentumTransport")
    write_mrf_properties(sp, case_params, constant_dir / "MRFProperties")
    write_initial_fields(case_params, REGION_NAMES, out_dir / "0")
    write_command_sh(case_params, out_dir / "command.sh")
    write_metadata_json(sp, case_params, out_dir / "metadata.json")
    return out_dir


def _main() -> None:
    parser = argparse.ArgumentParser(description="Generate a complete OpenFOAM STR case")
    parser.add_argument("geo_dir", type=pathlib.Path)
    parser.add_argument("out_dir", type=pathlib.Path)
    parser.add_argument("rpm", type=float, nargs="?", default=90)
    parser.add_argument("viscosity", type=float, nargs="?", default=1e-6)
    args = parser.parse_args()

    case_params = CaseParams.model_validate(
        {"rpm": args.rpm, "viscosity_m2_s": args.viscosity}
    )
    print(build_case(case_params, args.geo_dir, args.out_dir))


if __name__ == "__main__":
    _main()
