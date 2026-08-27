@echo off
REM =============================================================================
REM HYDRA-UMC-SEMANTIC-PLANNER - run.bat
REM Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
REM GPL-3.0 - see LICENSE
REM =============================================================================
REM Runs HYDRA-UMC-SEMANTIC-PLANNER's entry point. Run build.bat first.
REM Forwards all arguments (e.g. "run.bat decompose ""assemble the pcb""").
cd /d "%~dp0"

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

python -m hydra_umc_semantic_planner.main %*
pause
