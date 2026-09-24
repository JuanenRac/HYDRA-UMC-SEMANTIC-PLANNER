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

`capabilities` (see `validate_step`/`validate_plan`) is the real,
bounded half of this idea this module can honestly close today - a
static, pre-execution check against a declared robot/cell capability
catalog, no live executor needed. The idea's other half, POSTcondition
verification (did GRIP actually end up holding `target`, did MOVE_TO
actually reach `location`), is deliberately NOT attempted here: it needs
real feedback from a live executor this project doesn't have yet
(HYDRA-UMC-ORCHESTRATOR, per this module's own docstring above) -
fabricating a postcondition schema nobody could ever actually verify
would be worse than not having one.
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


def validate_step(step: Step, capabilities: frozenset[str] | None = None) -> list[str]:
    """Real issues with one Step's own params - empty when the step is
    well-formed. A primitive outside REQUIRED_PARAMS is itself a real
    issue (an executor would not know what it even is).

    `capabilities` is an optional, real declared-capability catalog
    for the specific robot/cell this Plan would run on - a fixed
    template producing a well-formed GRIP step is not enough if the
    target robot never declared it has a gripper at all. `None` (the
    default) means "no catalog supplied", so every existing caller keeps
    validating exactly as it did before this parameter existed - this is
    additive, not a stricter default.
    """
    if step.primitive not in REQUIRED_PARAMS:
        return [f"unknown primitive: {step.primitive!r}"]

    issues: list[str] = []
    if capabilities is not None and step.primitive not in capabilities:
        issues.append(f"primitive {step.primitive!r} is not in this robot/cell's declared capabilities")
    for param in REQUIRED_PARAMS[step.primitive]:
        value = step.params.get(param)
        if value is None:
            issues.append(f"missing required param {param!r}")
        elif not isinstance(value, str):
            issues.append(f"required param {param!r} must be text")
        elif not value.strip():
            issues.append(f"required param {param!r} is empty")
    return issues


def validate_plan(plan: Plan, capabilities: frozenset[str] | None = None) -> list[PlanIssue]:
    """Real precondition validation over every step in `plan`, in order.
    An empty result means every step is genuinely executable as-is on a
    robot/cell with `capabilities` (or on any robot/cell, when
    `capabilities` is omitted - see `validate_step`'s own header)."""
    issues: list[PlanIssue] = []
    if not plan.steps:
        return [PlanIssue(step_index=-1, primitive="", issue="plan has no steps")]
    for index, step in enumerate(plan.steps):
        for issue in validate_step(step, capabilities):
            issues.append(PlanIssue(step_index=index, primitive=step.primitive, issue=issue))
    return issues


def is_plan_valid(plan: Plan, capabilities: frozenset[str] | None = None) -> bool:
    return not validate_plan(plan, capabilities)
