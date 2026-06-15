import json
import os
import stat
import pathlib


def write_command_sh(cp, path) -> pathlib.Path:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''#!/bin/bash
set -e

CORES={cp.run.cores}

if [[ "${{OF_RESUME:-0}}" != "1" ]]; then
    blockMesh
    snappyHexMesh -overwrite
    topoSet
    if [[ "$CORES" -gt 1 ]]; then
        decomposePar -force
    fi
fi

if [[ "$CORES" -gt 1 ]]; then
    mpirun -np "$CORES" foamRun -parallel
    reconstructPar
else
    foamRun
fi
'''
    )
    os.chmod(
        path,
        stat.S_IRUSR
        | stat.S_IWUSR
        | stat.S_IXUSR
        | stat.S_IRGRP
        | stat.S_IXGRP
        | stat.S_IROTH
        | stat.S_IXOTH,
    )
    return path


def write_metadata_json(sp, cp, path) -> pathlib.Path:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "rpm": cp.rpm,
        "viscosity_m2_s": cp.viscosity_m2_s,
        "str": sp.model_dump(mode="json"),
        "case": cp.model_dump(mode="json"),
    }
    path.write_text(json.dumps(metadata, indent=2) + "\n")
    return path
