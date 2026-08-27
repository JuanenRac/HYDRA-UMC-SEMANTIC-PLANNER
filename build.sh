#!/usr/bin/env bash
# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - build.sh
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
# Builds HYDRA-UMC-SEMANTIC-PLANNER: creates/activates a venv, installs the
# project (editable, with dev extras), verifies it compiles/imports
# cleanly, and runs the real test suite. Run this before run.sh.
#
# Usage:
#   chmod +x build.sh   (one-time)
#   ./build.sh
set -euo pipefail
cd "$(dirname "$0")"

# Keep the window open if this was double-clicked (e.g. from a file
# manager) instead of run from an already-open terminal - fires on
# success AND on a `set -e` early exit alike, but only prompts when
# stdin is actually a terminal (never in CI/piped/non-interactive runs).
trap '[ -t 0 ] && read -r -p "Press Enter to close..." _' EXIT

echo
echo " ==============================================================="
echo "  H Y D R A - U M C - S E M A N T I C - P L A N N E R  -  build"
echo " ==============================================================="
echo "  LLM-based mission planner & error-recovery system (Hailo-10)"
echo "  Author:  JuanenRac (Electro Hobby 3D)"
echo "  License: GPL-3.0 (see LICENSE.md)"
echo " ==============================================================="
echo

echo "[1/5] Bumping version number (odometer bump, see bump_version.py)..."
python3 bump_version.py || exit 1
python3 "$(dirname "$0")/bump_manifest_version.py" --sync || exit 1
echo "      Done."
echo

echo "[2/5] Creating/activating virtual environment..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
# venv layout differs by OS: bin/activate on Linux/macOS, Scripts/activate
# on Windows (also true for a Windows Python venv used from Git Bash).
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
elif [ -f .venv/Scripts/activate ]; then
    source .venv/Scripts/activate
else
    echo "ERROR: could not find the venv activate script." >&2
    exit 1
fi
echo "      Done."
echo

echo "[3/5] Installing project (editable, with dev extras) into the venv..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -e ".[dev]"
echo "      Done."
echo

echo "[4/5] Verifying the package compiles/imports without errors..."
python -m py_compile src/hydra_umc_semantic_planner/__init__.py src/hydra_umc_semantic_planner/main.py src/hydra_umc_semantic_planner/primitives.py src/hydra_umc_semantic_planner/decompose.py src/hydra_umc_semantic_planner/recovery.py
python -c "import hydra_umc_semantic_planner; print('import OK - version', hydra_umc_semantic_planner.__version__)"
echo "      Done."
echo

echo "[5/5] Running the real test suite (pytest)..."
python -m pytest tests/ -q
echo "      Done."
echo

echo " ==============================================================="
echo "  Build complete. Run ./run.sh to execute the entry point."
echo " ==============================================================="
echo
