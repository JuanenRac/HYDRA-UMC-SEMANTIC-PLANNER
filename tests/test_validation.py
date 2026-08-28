# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_validation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
from __future__ import annotations

from hydra_umc_semantic_planner.decompose import decompose_goal
from hydra_umc_semantic_planner.primitives import GRIP, INSPECT, MOVE_TO, RELEASE, WAIT, Plan, Step
from hydra_umc_semantic_planner.validation import is_plan_valid, validate_plan, validate_step


def test_well_formed_step_has_no_issues() -> None:
    assert validate_step(Step(MOVE_TO, {"location": "pickup"})) == []


def test_missing_required_param_is_a_real_issue() -> None:
    issues = validate_step(Step(MOVE_TO, {}))

    assert issues == ["missing required param 'location'"]


def test_empty_required_param_is_a_real_issue() -> None:
    issues = validate_step(Step(GRIP, {"target": "   "}))

    assert issues == ["required param 'target' is empty"]


def test_unknown_primitive_is_a_real_issue() -> None:
    issues = validate_step(Step("TELEPORT", {}))

    assert issues == ["unknown primitive: 'TELEPORT'"]


def test_wait_requires_no_params() -> None:
    assert validate_step(Step(WAIT, {})) == []


def test_validate_plan_reports_every_bad_step_with_its_real_index() -> None:
    plan = Plan(
        goal="test",
        steps=(
            Step(MOVE_TO, {"location": "pickup"}),
            Step(GRIP, {}),
            Step(RELEASE, {"target": ""}),
        ),
    )

    issues = validate_plan(plan)

    assert len(issues) == 2
    assert issues[0].step_index == 1
    assert issues[0].primitive == GRIP
    assert issues[1].step_index == 2
    assert issues[1].primitive == RELEASE


def test_is_plan_valid_true_for_a_well_formed_plan() -> None:
    plan = Plan(goal="test", steps=(Step(INSPECT, {"target": "weld"}),))

    assert is_plan_valid(plan) is True


def test_is_plan_valid_false_for_a_malformed_plan() -> None:
    plan = Plan(goal="test", steps=(Step(INSPECT, {}),))

    assert is_plan_valid(plan) is False


def test_every_real_decompose_goal_template_passes_its_own_precondition_check() -> None:
    # decompose.py's templates should always be self-consistent with
    # validation.py's own REQUIRED_PARAMS - a real regression test that
    # would catch either file drifting out of sync with the other.
    for goal in ("assemble the pcb", "pick up the bracket and place it", "inspect the weld"):
        plan = decompose_goal(goal)
        assert plan is not None
        assert is_plan_valid(plan), f"real template for {goal!r} failed its own precondition check"
