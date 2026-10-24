# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_state_and_params.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The gripper along a plan, and the parameters of a step that cannot be changed after the plan is proposed."""
import json
from dataclasses import asdict

import pytest

from hydra_umc_semantic_planner.approval import plan_fingerprint as fingerprint
from hydra_umc_semantic_planner.decompose import decompose_goal
from hydra_umc_semantic_planner.primitives import GRIP, INSPECT, MOVE_TO, RELEASE, Params, Plan, Step
from hydra_umc_semantic_planner.validation import gripper_state_issues, is_plan_valid, validate_plan


def plan(*steps: Step) -> Plan:
    return Plan("test", tuple(steps))


def grip(target: str = "bracket") -> Step:
    return Step(GRIP, {"target": target})


def release(target: str = "bracket") -> Step:
    return Step(RELEASE, {"target": target})


def move(location: str = "pickup") -> Step:
    return Step(MOVE_TO, {"location": location})


# ---------------------------------------------------------------------------------------------- the gripper
def test_a_grip_then_a_release_of_the_same_thing_is_fine():
    assert is_plan_valid(plan(move(), grip(), move("assembly_point"), release()))


def test_a_plan_may_end_holding_its_target():
    assert is_plan_valid(plan(move(), grip()))


def test_gripping_with_the_gripper_already_full_is_an_error_at_that_step():
    issues = validate_plan(plan(grip("a"), move(), grip("b")))
    assert [(i.step_index, i.primitive) for i in issues] == [(2, GRIP)]
    assert "already holding 'a'" in issues[0].issue


def test_releasing_with_nothing_held_is_an_error():
    issues = validate_plan(plan(move(), release()))
    assert [(i.step_index, i.primitive) for i in issues] == [(1, RELEASE)]
    assert "nothing is held" in issues[0].issue


def test_releasing_something_else_than_what_is_held_is_an_error_and_the_gripper_stays_full():
    issues = validate_plan(plan(grip("a"), release("b"), grip("c")))
    assert [(i.step_index, i.primitive) for i in issues] == [(1, RELEASE), (2, GRIP)]
    assert "holds 'a', not 'b'" in issues[0].issue


def test_two_pick_and_place_cycles_in_a_row_are_fine():
    assert is_plan_valid(plan(grip("a"), release("a"), grip("b"), release("b")))


def test_a_step_with_an_unusable_target_is_left_to_the_step_check_and_does_not_confuse_the_state():
    broken = plan(Step(GRIP, {}), grip("a"), release("a"))
    issues = validate_plan(broken)
    assert [(i.step_index, i.issue) for i in issues] == [(0, "missing required param 'target'")]
    assert gripper_state_issues(broken) == []


def test_issues_come_out_in_the_order_of_the_steps():
    issues = validate_plan(plan(Step(INSPECT, {}), release(), Step(GRIP, {})))
    assert [i.step_index for i in issues] == sorted(i.step_index for i in issues)


@pytest.mark.parametrize("goal", ["assemble the pcb", "pick up the bracket and place it", "inspect the weld"])
def test_what_the_planner_itself_produces_is_always_valid(goal):
    result = decompose_goal(goal)
    assert is_plan_valid(result)


# ---------------------------------------------------------------------------------------------- the parameters
def test_the_parameters_of_a_step_cannot_be_changed():
    step = grip()
    with pytest.raises(TypeError):
        step.params["target"] = "other"  # type: ignore[index]
    with pytest.raises(TypeError):
        del step.params["target"]  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        step.params._items = {}  # type: ignore[misc]
    with pytest.raises(AttributeError):
        step.params.update({"x": "y"})  # type: ignore[attr-defined]


def test_the_dict_that_built_a_step_cannot_change_it_afterwards():
    source = {"target": "bracket"}
    step = Step(GRIP, source)
    source["target"] = "something else"
    assert step.params["target"] == "bracket"


def test_a_step_is_hashable_and_equal_when_its_content_is():
    assert hash(grip()) == hash(grip())
    assert grip() == grip()
    assert grip("a") != grip("b")
    assert len({grip("a"), grip("a"), grip("b")}) == 2


def test_params_compare_with_plain_dicts_and_read_like_them():
    params = Params({"target": "bracket"})
    assert params == {"target": "bracket"}
    assert dict(params) == {"target": "bracket"}
    assert params.get("missing") is None
    assert list(params.items()) == [("target", "bracket")]
    assert len(params) == 1 and "target" in params


def test_the_json_of_a_plan_is_what_it_always_was():
    result = decompose_goal("pick up the bracket and place it")
    text = json.dumps([asdict(step) for step in result.steps])
    assert json.loads(text)[1] == {"primitive": GRIP, "params": {"target": "bracket"}}


def test_the_fingerprint_does_not_change_with_the_new_type():
    steps = (Step(MOVE_TO, {"location": "a"}), Step(GRIP, {"target": "b"}))
    assert fingerprint(Plan("g", steps)) == fingerprint(Plan("g", tuple(Step(s.primitive, dict(s.params)) for s in steps)))
