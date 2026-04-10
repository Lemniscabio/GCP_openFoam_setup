#!/usr/bin/env bash
set -euo pipefail

# The Batch submitter exports MPI_RANKS from the selected hardware variant.
: "${MPI_RANKS:?MPI_RANKS is required}"

foamDictionary system/decomposeParDict -entry numberOfSubdomains -set "${MPI_RANKS}"
decomposePar -force
mpirun --oversubscribe -np "${MPI_RANKS}" simpleFoam -parallel
reconstructPar