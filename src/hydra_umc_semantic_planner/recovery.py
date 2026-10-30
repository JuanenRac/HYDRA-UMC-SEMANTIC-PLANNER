# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/recovery.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real, rule-based semantic error recovery over structured failure codes.

The error codes here (INVALID_STATE, OUT_OF_RANGE, ESTOP_ACTIVE,
TOOL_INCOMPATIBLE, TIMEOUT, UNSUPPORTED) are the MCU adapter error
vocabulary. This module's job is the "reasons about the cause
and decides whether to increase pressure, try again, or swap tools" the
README's own Key Features describe, expressed as a real, explicit lookup
table rather than a local LLM (which isn't wired to anything yet).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

RETRY = "RETRY"
INCREASE_PRESSURE = "INCREASE_PRESSURE"
SWAP_TOOL = "SWAP_TOOL"
ABORT = "ABORT"
ESCALATE_TO_OPERATOR = "ESCALATE_TO_OPERATOR"

# Public recovery-contract error codes plus one domain-specific gripper failure
# mode. See docs/RECOVERY_CONTRACT.md; no private design document is required.
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
    # 1 the first time this component reports the failure, 2 the second, and
    # so on. The caller owns the count; recovery itself keeps no memory.
    attempt: int = 1


@dataclass(frozen=True)
class RecoveryStrategy:
    action: str
    reason: str


# What an out-of-range request does. New installations abort: a motion beyond
# the real limits of the tool must not be retried with another tool by itself.
# "SWAP_TOOL" is the earlier behaviour, kept for installations that rely on it.
OUT_OF_RANGE_ACTIONS = (ABORT, SWAP_TOOL)
CONFIG_ENV = "HYDRA_UMC_SEMANTIC_PLANNER_CONFIG"


class PolicyError(ValueError):
    """The recovery policy file cannot be used."""


@dataclass(frozen=True)
class RecoveryPolicy:
    """Recovery settings; they come from the configuration file, never from the code."""

    out_of_range_action: str = ABORT

    def __post_init__(self) -> None:
        if self.out_of_range_action not in OUT_OF_RANGE_ACTIONS:
            raise PolicyError(
                f"out_of_range_action must be one of {', '.join(OUT_OF_RANGE_ACTIONS)}, got {self.out_of_range_action!r}"
            )


def load_policy(path: str | os.PathLike[str] | None = None) -> RecoveryPolicy:
    """The policy of the file `path`, or of the file named by HYDRA_UMC_SEMANTIC_PLANNER_CONFIG, or the safe default."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return RecoveryPolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PolicyError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise PolicyError(f"{chosen} must hold a JSON object")
    recovery = data.get("recovery", {})
    if not isinstance(recovery, dict):
        raise PolicyError("recovery must be a JSON object")
    action = recovery.get("out_of_range_action", ABORT)
    if not isinstance(action, str):
        raise PolicyError("out_of_range_action must be text")
    return RecoveryPolicy(out_of_range_action=action.strip().upper())


# A real, explicit lookup - ESTOP_ACTIVE and UNSUPPORTED always escalate to
# a human rather than being retried automatically, matching the ecosystem's
# own safety rule that IA/UI never overrides a physical safety condition.
_RULES: dict[str, RecoveryStrategy] = {
    GRIP_LOST_SEAL: RecoveryStrategy(
        INCREASE_PRESSURE, "vacuum seal lost - increasing gripper pressure before a retry"
    ),
    TIMEOUT: RecoveryStrategy(RETRY, "no response within the deadline - a single retry is safe"),
    OUT_OF_RANGE: RecoveryStrategy(
        ABORT, "requested motion exceeds this tool's real limits - the action is aborted, not retried"
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


# Most times an automatic recovery is proposed for the same failure before a
# person has to look at it.
MAX_AUTOMATIC_ATTEMPTS: dict[str, int] = {TIMEOUT: 1, GRIP_LOST_SEAL: 3}


_LEGACY_OUT_OF_RANGE = RecoveryStrategy(
    SWAP_TOOL, "requested motion exceeds this tool's real limits - a different tool may not"
)


def propose_recovery(failure: FailureContext, policy: RecoveryPolicy | None = None) -> RecoveryStrategy:
    """Real rule-based recovery proposal for a real, known error code.

    An error code outside this v0's known table gets the same
    conservative default a real safety-first system should: escalate to
    a human, never a silent retry loop.
    """
    if failure.error_code == OUT_OF_RANGE and policy is not None and policy.out_of_range_action == SWAP_TOOL:
        return _LEGACY_OUT_OF_RANGE
    limit = MAX_AUTOMATIC_ATTEMPTS.get(failure.error_code)
    if limit is not None and failure.attempt > limit:
        return RecoveryStrategy(
            ESCALATE_TO_OPERATOR,
            f"{failure.error_code} repeated {failure.attempt} times - automatic recovery is limited to {limit}",
        )
    return _RULES.get(
        failure.error_code,
        RecoveryStrategy(ESCALATE_TO_OPERATOR, f"unrecognized error code: {failure.error_code}"),
    )
