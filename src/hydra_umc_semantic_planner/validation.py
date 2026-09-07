# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/validation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real precondition validation for a decomposed Plan.

`decompose.py`'s own templates always fill the right params today, so
this never actually rejects anything decompose_goal() itself produces -
its real job is to be the one place that defines what a Step for each
primitive genuinely requires, so a Plan is never handed off to a real
executor (HYDRA-UMC-ORCHESTRATOR, eventually) on the strength of "the
planner that built it happened to get it right" alone. This is also the
real contract a future LLM-based planner (this project's own stated
roadmap) would have to satisfy - it cannot guarantee well-formed params
the way a fixed template can.
"""
from __future__ import annotations

from dataclasses import dataclass

from .primitives import GRIP, INSPECT, MOVE_TO, RELEASE, WAIT, Plan, Step

# The real params each primitive requires to be executable - not every
# key `params` happens to carry, just the ones a real executor could not
# proceed without. WAIT requires none: a bare pause is always well-formed.
REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    MOVE_TO: ("location",),
    GRIP: ("target",),
    RELEASE: ("target",),
    INSPECT: ("target",),
    WAIT: (),
}


@dataclass(frozen=True)
class PlanIssue:
    step_index: int
    primitive: str
    issue: str


def validate_step(step: Step) -> list[str]:
    """Real issues with one Step's own params - empty when the step is
    well-formed. A primitive outside REQUIRED_PARAMS is itself a real
    issue (an executor would not know what it even is)."""
    if step.primitive not in REQUIRED_PARAMS:
        return [f"unknown primitive: {step.primitive!r}"]

    issues: list[str] = []
    for param in REQUIRED_PARAMS[step.primitive]:
        value = step.params.get(param)
        if value is None:
            issues.append(f"missing required param {param!r}")
        elif not isinstance(value, str):
            issues.append(f"required param {param!r} must be text")
        elif not value.strip():
            issues.append(f"required param {param!r} is empty")
    return issues


def validate_plan(plan: Plan) -> list[PlanIssue]:
    """Real precondition validation over every step in `plan`, in order.
    An empty result means every step is genuinely executable as-is."""
    issues: list[PlanIssue] = []
    if not plan.steps:
        return [PlanIssue(step_index=-1, primitive="", issue="plan has no steps")]
    for index, step in enumerate(plan.steps):
        for issue in validate_step(step):
            issues.append(PlanIssue(step_index=index, primitive=step.primitive, issue=issue))
    return issues


def is_plan_valid(plan: Plan) -> bool:
    return not validate_plan(plan)
