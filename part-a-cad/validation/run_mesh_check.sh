#!/usr/bin/env bash
set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <builder_geometry_dir> <case_dir>" >&2
    exit 2
fi

geometry_dir=$1
case_dir=$2

python -m str_cad.meshcase "$geometry_dir" "$case_dir"
blockMesh -case "$case_dir"
snappyHexMesh -overwrite -case "$case_dir"
checkMesh -case "$case_dir"
