# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - approval, cost limit and explanation tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
from dataclasses import replace

from hydra_umc_semantic_planner.approval import (
    CostLimits,
    PlanApproval,
    estimate_cost,
    explain,
    plan_fingerprint,
    propose,
    release_for_execution,
)
from hydra_umc_semantic_planner.decompose import decompose_goal
from hydra_umc_semantic_planner.primitives import MOVE_TO, Plan, Step


def _proposal(goal="pick the cube and place it"):
    plan = decompose_goal(goal)
    assert plan is not None
    return propose(plan)


def test_a_fingerprint_is_stable_and_changes_with_the_plan():
    a = decompose_goal("inspect the board")
    b = decompose_goal("inspect the board")
    c = decompose_goal("inspect the frame")
    assert plan_fingerprint(a) == plan_fingerprint(b)
    assert plan_fingerprint(a) != plan_fingerprint(c)


def test_the_explanation_lists_every_step_in_order():
    text = explain(decompose_goal("inspect the board"))
    assert text.splitlines()[0].startswith("Goal:")
    assert "1. MOVE_TO" in text and "2. INSPECT" in text


def test_the_cost_is_the_sum_of_the_step_costs():
    plan = Plan("g", (Step(MOVE_TO, {"location": "a"}), Step(MOVE_TO, {"location": "b"})))
    assert estimate_cost(plan) == 6


def test_a_plan_is_not_released_without_an_approval():
    decision = release_for_execution(_proposal(), None)
    assert not decision.released and "approval" in decision.reason


def test_an_approval_of_a_different_plan_releases_nothing():
    proposal = _proposal()
    other = _proposal("inspect the board")
    decision = release_for_execution(proposal, PlanApproval(other.fingerprint, "operator"))
    assert not decision.released and "different plan" in decision.reason


def test_an_approval_that_names_nobody_is_refused():
    proposal = _proposal()
    assert not release_for_execution(proposal, PlanApproval(proposal.fingerprint, "  ")).released


def test_an_approved_plan_within_limits_is_released():
    proposal = _proposal()
    decision = release_for_execution(proposal, PlanApproval(proposal.fingerprint, "operator"))
    assert decision.released and "operator" in decision.reason


def test_the_cost_and_step_limits_are_enforced_even_with_an_approval():
    proposal = _proposal()
    approval = PlanApproval(proposal.fingerprint, "operator")
    assert not release_for_execution(proposal, approval, CostLimits(max_steps=20, max_total_cost=1)).released
    assert not release_for_execution(proposal, approval, CostLimits(max_steps=1, max_total_cost=99)).released


def test_a_tampered_proposal_is_detected():
    proposal = _proposal()
    approval = PlanApproval(proposal.fingerprint, "operator")
    tampered_plan = Plan(proposal.plan.goal, proposal.plan.steps + (Step(MOVE_TO, {"location": "elsewhere"}),))
    tampered = replace(proposal, plan=tampered_plan)
    decision = release_for_execution(tampered, approval)
    assert not decision.released and "no longer matches" in decision.reason


def test_a_missing_explanation_blocks_the_release():
    proposal = replace(_proposal(), explanation=" ")
    decision = release_for_execution(proposal, PlanApproval(proposal.fingerprint, "operator"))
    assert not decision.released and "explanation" in decision.reason
