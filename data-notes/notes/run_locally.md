To run locally use the following command in the case directory.(assuming you have command.sh in that case directory with executable permission)

docker run --rm -it \
    --platform linux/amd64 \
    --entrypoint /bin/bash \
    -e MPI_RANKS=10 \
    -v "$PWD":/case \
    -w /case \
    docker.io/kartikeyattri/openfoam:12 \
    -lc './command.sh'