# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_cli.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
from __future__ import annotations

import pytest

from hydra_umc_semantic_planner.main import main


def test_bare_invocation_prints_identity(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "HYDRA-UMC-SEMANTIC-PLANNER v" in captured.out


def test_decompose_real_goal(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["decompose", "assemble the housing"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "MOVE_TO" in captured.out
    assert "GRIP" in captured.out
    assert "RELEASE" in captured.out


def test_decompose_unmatched_goal(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["decompose", "write a poem"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No matching task template" in captured.out


def test_recover_known_error_code(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        ["recover", "--component", "gripper", "--error-code", "GRIP_LOST_SEAL", "--detail", "vacuum gripper lost seal"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "INCREASE_PRESSURE" in captured.out
    assert "vacuum gripper lost seal" in captured.out
