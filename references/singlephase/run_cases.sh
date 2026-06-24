#!/usr/bin/env bash

CORES=9

python generate_cases.py --rpm 50 100 150 200 250 --nu 1e-6 1e-5 5e-5 1e-4 2e-4 --fill 22 20 15 --np "$CORES"
