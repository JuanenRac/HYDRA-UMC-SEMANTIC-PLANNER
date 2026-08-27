#!/usr/bin/env bash
# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - run.sh
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
# Runs HYDRA-UMC-SEMANTIC-PLANNER's entry point. Run ./build.sh first.
# Forwards all arguments (e.g. "./run.sh decompose \"assemble the pcb\"").
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif [ -f .venv/Scripts/activate ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
fi

python -m hydra_umc_semantic_planner.main "$@"
