# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_decompose.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
from __future__ import annotations

import random
import string

from hydra_umc_semantic_planner.decompose import decompose_goal
from hydra_umc_semantic_planner.primitives import GRIP, INSPECT, MOVE_TO, RELEASE
from hydra_umc_semantic_planner.validation import is_plan_valid


def test_assemble_goal_produces_pick_and_place_sequence() -> None:
    plan = decompose_goal("assemble the pcb")

    assert plan is not None
    primitives = [step.primitive for step in plan.steps]
    assert primitives == [MOVE_TO, GRIP, MOVE_TO, RELEASE]
    assert plan.steps[1].params["target"] == "pcb"


def test_pick_and_place_goal() -> None:
    plan = decompose_goal("pick up the bracket and place it")

    assert plan is not None
    primitives = [step.primitive for step in plan.steps]
    assert primitives == [MOVE_TO, GRIP, MOVE_TO, RELEASE]


def test_inspect_goal_produces_move_and_inspect() -> None:
    plan = decompose_goal("inspect the weld")

    assert plan is not None
    primitives = [step.primitive for step in plan.steps]
    assert primitives == [MOVE_TO, INSPECT]
    assert plan.steps[1].params["target"] == "weld"


def test_unmatched_goal_returns_none() -> None:
    assert decompose_goal("compose a symphony") is None


def test_decompose_goal_is_deterministic() -> None:
    # Property: the exact same goal decomposed twice must produce the
    # exact same plan, every time - no hidden randomness/state. Checked
    # across every real known template, not just one.
    for goal in ("assemble the pcb", "pick up the bracket and place it", "inspect the weld", "compose a symphony"):
        first = decompose_goal(goal)
        second = decompose_goal(goal)
        assert first == second


# A deliberately varied, deterministic corpus of goals that must NEVER
# match any real template - empty/whitespace-only input, punctuation and
# unicode noise, and near-misses that contain a known keyword only as a
# substring of a longer word (\b requires a real word boundary on both
# sides of the matched keyword itself, so "reassembling"/"disinspecting"
# do not false-positive on "assemble"/"inspect" - verified directly
# against the real compiled patterns before writing this fixture).
_INVALID_GOALS: tuple[str, ...] = (
    "",
    "   ",
    "\t\n",
    "compose a symphony",
    "reboot the controller",
    "!!!???...",
    "cafe uber naive test",
    "reassembling old memories",
    "disinspecting nothing",
)


def test_property_invalid_goals_always_return_none_never_crash() -> None:
    for goal in _INVALID_GOALS:
        assert decompose_goal(goal) is None, f"expected an honest miss for {goal!r}"


def test_property_random_fuzz_goals_never_crash_and_are_always_well_formed() -> None:
    # A real, reproducible (fixed seed) property test over random noise:
    # decompose_goal() must never raise, and whatever it returns - a
    # real Plan or an honest None - must never be a malformed plan that
    # would fail its own precondition check.
    rng = random.Random(1337)
    alphabet = string.ascii_letters + string.digits + " _-"
    for _ in range(500):
        length = rng.randint(0, 40)
        goal = "".join(rng.choice(alphabet) for _ in range(length))
        plan = decompose_goal(goal)
        if plan is not None:
            assert is_plan_valid(plan), f"random goal {goal!r} produced a malformed plan"


def test_negated_goals_never_become_a_plan() -> None:
    for goal in (
        "do NOT pick the knife and place it on the table",
        "never assemble anything",
        "don't inspect the motor",
        "nunca montes la pieza, no assemble it",
    ):
        assert decompose_goal(goal) is None, goal


def test_the_target_is_the_object_not_the_last_word() -> None:
    plan = decompose_goal("pick the bolt and place it in the bin")
    assert plan is not None
    assert plan.steps[1].params["target"] == "bolt"
    assert plan.steps[2].params["location"] == "bin"
    for goal, expected in (("inspect the motor now", "motor"), ("assemble the gearbox carefully", "gearbox")):
        plan = decompose_goal(goal)
        assert plan is not None
        assert plan.steps[-1].params.get("target", plan.steps[1].params.get("target")) == expected


def test_goals_without_a_real_object_or_matching_several_templates_are_refused() -> None:
    assert decompose_goal("assemble it") is None
    assert decompose_goal("inspect now") is None
    assert decompose_goal("inspect the arm then assemble the gripper") is None


def test_a_very_long_goal_is_refused_quickly() -> None:
    import time

    started = time.monotonic()
    assert decompose_goal("pick " * 100_000) is None
    assert decompose_goal("pick " * 90 + "x") is None
    assert time.monotonic() - started < 1.0
