# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/symbolic.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A small symbolic planner (PDDL-lite) that stands behind `decompose_goal()`.

A goal sentence is still read by the rules of `decompose.py` into a template, an object and a destination. With the switch on, that
reading becomes a PROBLEM (facts that hold, facts that must hold) and a breadth-first search over a closed set of operators finds the
shortest sequence of steps. Every operator has preconditions, some of them negated ("the gripper is NOT holding anything"), and
add/delete effects. The search is deterministic, bounded (`max_nodes`, `max_plan_length`), and the plan it returns is replayed from
the start state, operator by operator, before it is handed back: a plan whose replay breaks a precondition or misses the goal is
discarded.

The planner only PROPOSES. What it returns is the same `Plan` as the rules give, which still goes through validation, a proposal with a
fingerprint and `POST /release` with a person's approval (and the safety gate when it is on). Nothing here releases or executes.
"""
from __future__ import annotations

import json
import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .primitives import GRIP, INSPECT, MOVE_TO, RELEASE, Plan, Step
from .recovery import CONFIG_ENV

Fact = tuple[str, ...]

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_KNOWN_KEYS = {"enabled", "max_nodes", "max_plan_length", "start_location", "pickup_location", "assembly_location", "destination_location"}


class SymbolicConfigError(ValueError):
    """The `symbolic_planner` section of the configuration file cannot be used."""


@dataclass(frozen=True)
class SymbolicPolicy:
    enabled: bool = False
    max_nodes: int = 5000
    max_plan_length: int = 12
    start_location: str = "home"
    pickup_location: str = "pickup"
    assembly_location: str = "assembly_point"
    destination_location: str = "destination"

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise SymbolicConfigError("symbolic_planner.enabled must be true or false")
        for name in ("max_nodes", "max_plan_length"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SymbolicConfigError(f"symbolic_planner.{name} must be an integer of at least 1")
        if self.max_nodes > 1_000_000 or self.max_plan_length > 64:
            raise SymbolicConfigError("symbolic_planner.max_nodes (at most 1000000) or max_plan_length (at most 64) is too large")
        for name in ("start_location", "pickup_location", "assembly_location", "destination_location"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _NAME.match(value):
                raise SymbolicConfigError(f"symbolic_planner.{name} must be a short name")


def load_symbolic_policy(path: str | os.PathLike[str] | None = None) -> SymbolicPolicy:
    """The `symbolic_planner` policy of the file `path`, or of the file named by the planner's variable, or the default (off)."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return SymbolicPolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SymbolicConfigError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise SymbolicConfigError(f"{chosen} must hold a JSON object")
    section = data.get("symbolic_planner", {})
    if not isinstance(section, dict):
        raise SymbolicConfigError("symbolic_planner must be a JSON object")
    unknown = sorted(set(section) - _KNOWN_KEYS)
    if unknown:
        raise SymbolicConfigError(f"symbolic_planner has unknown keys: {', '.join(unknown)}")
    return SymbolicPolicy(**section)


@dataclass(frozen=True)
class Operator:
    """A grounded operator: positive and negated preconditions, facts it adds and facts it deletes."""

    name: str
    step: Step
    pre: frozenset[Fact]
    pre_not: frozenset[Fact]
    add: frozenset[Fact]
    delete: frozenset[Fact]

    def applicable(self, state: frozenset[Fact]) -> bool:
        return self.pre <= state and not (self.pre_not & state)

    def apply(self, state: frozenset[Fact]) -> frozenset[Fact]:
        return (state - self.delete) | self.add


@dataclass(frozen=True)
class Problem:
    objects: tuple[str, ...]
    locations: tuple[str, ...]
    init: frozenset[Fact]
    goal: frozenset[Fact]
    goal_not: frozenset[Fact] = frozenset()


def operators(problem: Problem) -> tuple[Operator, ...]:
    """Every operator of the closed domain, grounded over the locations and objects of the problem."""
    ops: list[Operator] = []
    for src in problem.locations:
        for dst in problem.locations:
            if src != dst:
                ops.append(Operator(
                    f"move {src} {dst}", Step(MOVE_TO, {"location": dst}),  # type: ignore[arg-type]
                    frozenset({("at", src)}), frozenset({("at", dst)}),
                    frozenset({("at", dst)}), frozenset({("at", src)}),
                ))
    for obj in problem.objects:
        for loc in problem.locations:
            ops.append(Operator(
                f"grip {obj} {loc}", Step(GRIP, {"target": obj}),  # type: ignore[arg-type]
                frozenset({("at", loc), ("obj_at", obj, loc), ("gripper_empty",)}), frozenset(),
                frozenset({("holding", obj)}), frozenset({("obj_at", obj, loc), ("gripper_empty",)}),
            ))
            ops.append(Operator(
                f"release {obj} {loc}", Step(RELEASE, {"target": obj}),  # type: ignore[arg-type]
                frozenset({("at", loc), ("holding", obj)}), frozenset(),
                frozenset({("obj_at", obj, loc), ("gripper_empty",)}), frozenset({("holding", obj)}),
            ))
            ops.append(Operator(
                f"inspect {obj} {loc}", Step(INSPECT, {"target": obj}),  # type: ignore[arg-type]
                frozenset({("at", loc), ("obj_at", obj, loc)}), frozenset({("holding", obj)}),
                frozenset({("inspected", obj)}), frozenset(),
            ))
    return tuple(ops)


def search(problem: Problem, policy: SymbolicPolicy) -> tuple[Operator, ...] | None:
    """The shortest sequence of operators from the start to the goal, or None (no plan within the bounds)."""
    ops = operators(problem)

    def reached(state: frozenset[Fact]) -> bool:
        return problem.goal <= state and not (problem.goal_not & state)

    if reached(problem.init):
        return ()
    seen = {problem.init}
    queue: deque[tuple[frozenset[Fact], tuple[Operator, ...]]] = deque([(problem.init, ())])
    nodes = 0
    while queue:
        state, path = queue.popleft()
        if len(path) >= policy.max_plan_length:
            continue
        for op in ops:
            if not op.applicable(state):
                continue
            nxt = op.apply(state)
            if nxt in seen:
                continue
            nodes += 1
            if nodes > policy.max_nodes:
                return None
            if reached(nxt):
                return path + (op,)
            seen.add(nxt)
            queue.append((nxt, path + (op,)))
    return None


def verify(problem: Problem, plan: tuple[Operator, ...]) -> bool:
    """Replay `plan` from the start state: every precondition (and negation) must hold at its turn and the goal at the end."""
    state = problem.init
    for op in plan:
        if not op.applicable(state):
            return False
        state = op.apply(state)
    return problem.goal <= state and not (problem.goal_not & state)


def problem_for(template: str, target: str, destination: str | None, policy: SymbolicPolicy) -> Problem | None:
    """The problem a template stands for, or None for a template this domain does not know."""
    if not _NAME.match(target) or (destination is not None and not _NAME.match(destination)):
        return None
    start = policy.start_location
    if template == "inspect":
        locations = tuple(dict.fromkeys((start, target)))
        init = frozenset({("at", start), ("gripper_empty",), ("obj_at", target, target)})
        return Problem((target,), locations, init, frozenset({("inspected", target)}))
    if template == "assemble":
        locations = tuple(dict.fromkeys((start, policy.pickup_location, policy.assembly_location)))
        init = frozenset({("at", start), ("gripper_empty",), ("obj_at", target, policy.pickup_location)})
        return Problem((target,), locations, init, frozenset({("obj_at", target, policy.assembly_location)}))
    if template == "pick_and_place":
        place = destination or policy.destination_location
        locations = tuple(dict.fromkeys((start, policy.pickup_location, place)))
        init = frozenset({("at", start), ("gripper_empty",), ("obj_at", target, policy.pickup_location)})
        return Problem((target,), locations, init, frozenset({("obj_at", target, place)}))
    return None


def plan_symbolically(goal: str, template: str, target: str, destination: str | None, policy: SymbolicPolicy) -> Plan | None:
    """A verified plan for the problem, or None: no plan within the bounds, or one whose replay fails, is an honest miss."""
    problem = problem_for(template, target, destination, policy)
    if problem is None:
        return None
    found = search(problem, policy)
    if not found or not verify(problem, found):
        return None
    return Plan(goal=goal, steps=tuple(op.step for op in found))
