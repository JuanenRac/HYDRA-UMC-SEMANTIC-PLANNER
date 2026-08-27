# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_decompose.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
from __future__ import annotations

from hydra_umc_semantic_planner.decompose import decompose_goal
from hydra_umc_semantic_planner.primitives import GRIP, INSPECT, MOVE_TO, RELEASE


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
