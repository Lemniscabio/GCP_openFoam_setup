import json
import os
import pathlib


def write_command_sh(cp, path) -> pathlib.Path:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '''#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${MPI_RANKS:?MPI_RANKS is required}"

if [[ "${OF_RESUME:-0}" != "1" ]]; then
  blockMesh 2>&1 | tee log.blockMesh
  snappyHexMesh -overwrite 2>&1 | tee log.snappyHexMesh
  topoSet 2>&1 | tee log.topoSet
  foamDictionary system/decomposeParDict -entry numberOfSubdomains -set "${MPI_RANKS}" 2>&1 | tee log.foamDictionary
  decomposePar -force 2>&1 | tee log.decomposePar
fi

mpirun --oversubscribe -np "${MPI_RANKS}" foamRun -parallel 2>&1 | tee log.foamRun
reconstructPar 2>&1 | tee log.reconstructPar
'''
    )
    os.chmod(path, 0o755)
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
