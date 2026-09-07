# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_recovery.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
from __future__ import annotations

from hydra_umc_semantic_planner.recovery import (
    ABORT,
    ESCALATE_TO_OPERATOR,
    ESTOP_ACTIVE,
    GRIP_LOST_SEAL,
    INCREASE_PRESSURE,
    INVALID_STATE,
    RETRY,
    SWAP_TOOL,
    TIMEOUT,
    TOOL_INCOMPATIBLE,
    FailureContext,
    propose_recovery,
)


def test_grip_lost_seal_increases_pressure() -> None:
    strategy = propose_recovery(FailureContext(component="gripper", error_code=GRIP_LOST_SEAL))

    assert strategy.action == INCREASE_PRESSURE


def test_timeout_retries() -> None:
    strategy = propose_recovery(FailureContext(component="mcu", error_code=TIMEOUT))

    assert strategy.action == RETRY


def test_tool_incompatible_swaps_tool() -> None:
    strategy = propose_recovery(FailureContext(component="urtc", error_code=TOOL_INCOMPATIBLE))

    assert strategy.action == SWAP_TOOL


def test_invalid_state_aborts() -> None:
    strategy = propose_recovery(FailureContext(component="arm", error_code=INVALID_STATE))

    assert strategy.action == ABORT


def test_estop_active_never_auto_retries() -> None:
    # Real safety rule: a physical E-STOP is never silently cleared by
    # this planner - it must always escalate to a human.
    strategy = propose_recovery(FailureContext(component="mcu", error_code=ESTOP_ACTIVE))

    assert strategy.action == ESCALATE_TO_OPERATOR


def test_unknown_error_code_escalates_conservatively() -> None:
    strategy = propose_recovery(FailureContext(component="arm", error_code="SOMETHING_NEW"))

    assert strategy.action == ESCALATE_TO_OPERATOR
    assert "SOMETHING_NEW" in strategy.reason
