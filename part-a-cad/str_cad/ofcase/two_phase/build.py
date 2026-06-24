import json
import pathlib

from str_cad.geometry.assembly import REGION_NAMES
from str_cad.meshcase import make_mesh_case
from str_cad.ofcase.command import write_metadata_json, write_two_phase_command_sh
from str_cad.ofcase.mrf import write_mrf_properties
from str_cad.ofcase.systemdicts import write_decompose_par
from str_cad.schema import STRParams

from .fields import write_initial_fields_two_phase
from .physics import (
    write_gravity,
    write_momentum_transport_gas,
    write_momentum_transport_liquid,
    write_phase_properties,
    write_physical_properties_gas,
    write_physical_properties_liquid,
)
from .systemdicts import (
    write_control_dict,
    write_create_patch_dict,
    write_fv_schemes,
    write_fv_solution,
    write_set_fields_dict,
    write_toposet_dict,
)


def build_two_phase_case(case_params, geo_dir, out_dir) -> pathlib.Path:
    geo_dir = pathlib.Path(geo_dir)
    out_dir = pathlib.Path(out_dir)
    sp = STRParams.model_validate(json.loads((geo_dir / "str-params.json").read_text()))

    make_mesh_case(geo_dir, out_dir)

    system_dir = out_dir / "system"
    constant_dir = out_dir / "constant"
    write_control_dict(case_params, system_dir / "controlDict")
    write_fv_schemes(system_dir / "fvSchemes")
    write_fv_solution(system_dir / "fvSolution")
    write_set_fields_dict(sp, system_dir / "setFieldsDict")
    write_toposet_dict(sp, system_dir / "topoSetDict")
    write_create_patch_dict(system_dir / "createPatchDict")
    write_decompose_par(case_params, system_dir / "decomposeParDict")

    write_phase_properties(sp, constant_dir / "phaseProperties")
    write_physical_properties_gas(sp, constant_dir / "physicalProperties.gas")
    write_physical_properties_liquid(sp, constant_dir / "physicalProperties.liquid")
    write_momentum_transport_gas(constant_dir / "momentumTransport.gas")
    write_momentum_transport_liquid(constant_dir / "momentumTransport.liquid")
    write_gravity(constant_dir / "g")
    write_mrf_properties(sp, case_params, constant_dir / "MRFProperties")

    write_initial_fields_two_phase(sp, case_params, REGION_NAMES, out_dir / "0")
    write_two_phase_command_sh(case_params, out_dir / "command.sh")
    write_metadata_json(
        sp,
        case_params,
        out_dir / "metadata.json",
        extra={"derived": sp.derived(), "physics": "two_phase"},
    )
    return out_dir
