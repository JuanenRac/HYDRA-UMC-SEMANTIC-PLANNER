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


def test_non_text_required_param_is_a_real_issue_not_an_exception() -> None:
    issues = validate_step(Step(GRIP, {"target": 42}))

    assert issues == ["required param 'target' must be text"]


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


def test_empty_plan_is_not_execution_ready() -> None:
    issues = validate_plan(Plan(goal="empty", steps=()))

    assert issues[0].step_index == -1
    assert issues[0].issue == "plan has no steps"


# I38: a real, declared capability catalog for the target robot/cell -
# a well-formed step (right params) is not enough if the robot that
# would run it never declared it can even do that primitive.
def test_a_primitive_outside_the_declared_capabilities_is_a_real_issue() -> None:
    issues = validate_step(Step(GRIP, {"target": "bracket"}), capabilities=frozenset({MOVE_TO, WAIT}))

    assert issues == ["primitive 'GRIP' is not in this robot/cell's declared capabilities"]


def test_a_primitive_inside_the_declared_capabilities_has_no_capability_issue() -> None:
    issues = validate_step(Step(GRIP, {"target": "bracket"}), capabilities=frozenset({GRIP, MOVE_TO}))

    assert issues == []


def test_omitting_capabilities_validates_exactly_as_before_the_parameter_existed() -> None:
    # None (the default) must never behave like "declares nothing" -
    # every existing caller that never passes capabilities keeps
    # validating only params, unaffected by this feature.
    assert validate_step(Step(GRIP, {"target": "bracket"})) == []
    assert validate_step(Step(GRIP, {"target": "bracket"}), capabilities=None) == []


def test_a_capability_gap_and_a_missing_param_are_both_reported_together() -> None:
    issues = validate_step(Step(GRIP, {}), capabilities=frozenset({MOVE_TO}))

    assert issues == [
        "primitive 'GRIP' is not in this robot/cell's declared capabilities",
        "missing required param 'target'",
    ]


def test_validate_plan_applies_the_same_capability_catalog_to_every_step() -> None:
    plan = Plan(
        goal="test",
        steps=(
            Step(MOVE_TO, {"location": "pickup"}),
            Step(GRIP, {"target": "bracket"}),
        ),
    )

    issues = validate_plan(plan, capabilities=frozenset({MOVE_TO}))

    assert len(issues) == 1
    assert issues[0].step_index == 1
    assert issues[0].primitive == GRIP
    assert "declared capabilities" in issues[0].issue


def test_is_plan_valid_respects_the_declared_capability_catalog() -> None:
    plan = Plan(goal="test", steps=(Step(GRIP, {"target": "bracket"}),))

    assert is_plan_valid(plan, capabilities=frozenset({GRIP})) is True
    assert is_plan_valid(plan, capabilities=frozenset({MOVE_TO})) is False


def test_every_real_decompose_goal_template_passes_its_own_precondition_check() -> None:
    # decompose.py's templates should always be self-consistent with
    # validation.py's own REQUIRED_PARAMS - a real regression test that
    # would catch either file drifting out of sync with the other.
    for goal in ("assemble the pcb", "pick up the bracket and place it", "inspect the weld"):
        plan = decompose_goal(goal)
        assert plan is not None
        assert is_plan_valid(plan), f"real template for {goal!r} failed its own precondition check"
