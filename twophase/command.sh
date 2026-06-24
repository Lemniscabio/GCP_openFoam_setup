#!/usr/bin/env bash
set -euo pipefail

: "${MPI_RANKS:?MPI_RANKS is required}"

LOGFILE="log.foamRun"

foamDictionary system/decomposeParDict -entry numberOfSubdomains -set "${MPI_RANKS}"
decomposePar > log.decomposePar 2>&1
mpirun --oversubscribe -np "${MPI_RANKS}" foamRun -parallel 2>&1 | tee "${LOGFILE}"
reconstructPar -latestTime
