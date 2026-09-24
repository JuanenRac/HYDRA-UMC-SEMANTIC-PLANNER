# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/approval.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""What must be true before a plan may reach an executing layer.

A plan is only a proposal. It is released for execution when four things
hold together: it validates, it comes with an explanation a person can
read, its estimated cost is within the limits, and a named person approved
*this exact plan* (the approval carries the plan's fingerprint, so an
approval of one plan can never release another).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .primitives import GRIP, INSPECT, MOVE_TO, RELEASE, WAIT, Plan
from .validation import validate_plan

# Relative cost of each primitive: a unit of "how much this step asks of the machine".
STEP_COST: dict[str, int] = {MOVE_TO: 3, GRIP: 2, RELEASE: 2, INSPECT: 1, WAIT: 1}


def plan_fingerprint(plan: Plan) -> str:
    """A stable identity for a plan: the same goal and steps always give the same value."""
    canonical = json.dumps(
        {"goal": plan.goal, "steps": [[s.primitive, sorted(s.params.items())] for s in plan.steps]},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def estimate_cost(plan: Plan) -> int:
    return sum(STEP_COST.get(step.primitive, 5) for step in plan.steps)


def explain(plan: Plan) -> str:
    """A plain-language, step-by-step account of what the plan will do."""
    lines = [f"Goal: {plan.goal}"]
    for index, step in enumerate(plan.steps, start=1):
        params = ", ".join(f"{k}={v}" for k, v in sorted(step.params.items()))
        lines.append(f"{index}. {step.primitive}" + (f" ({params})" if params else ""))
    return "\n".join(lines)


@dataclass(frozen=True)
class PlanProposal:
    plan: Plan
    fingerprint: str
    explanation: str
    estimated_cost: int


def propose(plan: Plan) -> PlanProposal:
    return PlanProposal(plan, plan_fingerprint(plan), explain(plan), estimate_cost(plan))


@dataclass(frozen=True)
class CostLimits:
    max_steps: int = 20
    max_total_cost: int = 40


@dataclass(frozen=True)
class PlanApproval:
    plan_fingerprint: str
    approved_by: str


@dataclass(frozen=True)
class ReleaseDecision:
    released: bool
    reason: str


def release_for_execution(
    proposal: PlanProposal, approval: PlanApproval | None, limits: CostLimits = CostLimits()
) -> ReleaseDecision:
    if plan_fingerprint(proposal.plan) != proposal.fingerprint:
        return ReleaseDecision(False, "the proposal no longer matches its plan")
    issues = validate_plan(proposal.plan)
    if issues:
        return ReleaseDecision(False, f"the plan is not valid: {issues[0]}")
    if not proposal.explanation.strip():
        return ReleaseDecision(False, "the plan has no explanation")
    if len(proposal.plan.steps) > limits.max_steps:
        return ReleaseDecision(False, f"{len(proposal.plan.steps)} steps exceed the limit of {limits.max_steps}")
    if proposal.estimated_cost > limits.max_total_cost:
        return ReleaseDecision(False, f"estimated cost {proposal.estimated_cost} exceeds the limit of {limits.max_total_cost}")
    if approval is None:
        return ReleaseDecision(False, "no approval was recorded")
    if not approval.approved_by.strip():
        return ReleaseDecision(False, "the approval names nobody")
    if approval.plan_fingerprint != proposal.fingerprint:
        return ReleaseDecision(False, "the approval is for a different plan")
    return ReleaseDecision(True, f"approved by {approval.approved_by}")
