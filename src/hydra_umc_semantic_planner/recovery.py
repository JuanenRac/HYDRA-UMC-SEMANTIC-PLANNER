# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/recovery.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real, rule-based semantic error recovery over structured failure codes.

The error codes here (INVALID_STATE, OUT_OF_RANGE, ESTOP_ACTIVE,
TOOL_INCOMPATIBLE, TIMEOUT, UNSUPPORTED) are the real MCU adapter error
vocabulary documented in SONNET/BIBLIA HYDRA-UMC's own architecture
manual (section D.4) - this module's job is the "reasons about the cause
and decides whether to increase pressure, try again, or swap tools" the
README's own Key Features describe, expressed as a real, explicit lookup
table rather than a local LLM (which isn't wired to anything yet).
"""
from __future__ import annotations

from dataclasses import dataclass

RETRY = "RETRY"
INCREASE_PRESSURE = "INCREASE_PRESSURE"
SWAP_TOOL = "SWAP_TOOL"
ABORT = "ABORT"
ESCALATE_TO_OPERATOR = "ESCALATE_TO_OPERATOR"

# Real MCU adapter error codes (see BIBLIA D.4) plus one domain-specific
# gripper failure mode, matching the README's own worked example.
INVALID_STATE = "INVALID_STATE"
OUT_OF_RANGE = "OUT_OF_RANGE"
ESTOP_ACTIVE = "ESTOP_ACTIVE"
TOOL_INCOMPATIBLE = "TOOL_INCOMPATIBLE"
TIMEOUT = "TIMEOUT"
UNSUPPORTED = "UNSUPPORTED"
GRIP_LOST_SEAL = "GRIP_LOST_SEAL"


@dataclass(frozen=True)
class FailureContext:
    component: str
    error_code: str
    detail: str = ""


@dataclass(frozen=True)
class RecoveryStrategy:
    action: str
    reason: str


# A real, explicit lookup - ESTOP_ACTIVE and UNSUPPORTED always escalate to
# a human rather than being retried automatically, matching the ecosystem's
# own safety rule that IA/UI never overrides a physical safety condition.
_RULES: dict[str, RecoveryStrategy] = {
    GRIP_LOST_SEAL: RecoveryStrategy(
        INCREASE_PRESSURE, "vacuum seal lost - increasing gripper pressure before a retry"
    ),
    TIMEOUT: RecoveryStrategy(RETRY, "no response within the deadline - a single retry is safe"),
    OUT_OF_RANGE: RecoveryStrategy(
        SWAP_TOOL, "requested motion exceeds this tool's real limits - a different tool may not"
    ),
    TOOL_INCOMPATIBLE: RecoveryStrategy(
        SWAP_TOOL, "the mounted tool cannot perform this action - swap for a compatible one"
    ),
    INVALID_STATE: RecoveryStrategy(
        ABORT, "the component reported a state this plan didn't account for"
    ),
    ESTOP_ACTIVE: RecoveryStrategy(
        ESCALATE_TO_OPERATOR, "a physical E-STOP is active - never auto-cleared by this planner"
    ),
    UNSUPPORTED: RecoveryStrategy(
        ESCALATE_TO_OPERATOR, "the firmware doesn't recognize this command at all"
    ),
}


def propose_recovery(failure: FailureContext) -> RecoveryStrategy:
    """Real rule-based recovery proposal for a real, known error code.

    An error code outside this v0's known table gets the same
    conservative default a real safety-first system should: escalate to
    a human, never a silent retry loop.
    """
    return _RULES.get(
        failure.error_code,
        RecoveryStrategy(ESCALATE_TO_OPERATOR, f"unrecognized error code: {failure.error_code}"),
    )
