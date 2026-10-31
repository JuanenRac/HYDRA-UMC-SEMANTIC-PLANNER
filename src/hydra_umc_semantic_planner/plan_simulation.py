# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/plan_simulation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Dry-run of a plan against declared constraints, before anything is executed.

`simulate_plan` takes a list of steps (the primitives of `primitives.py`, each with the robot that runs it, the steps it depends on, the
resources it holds and, optionally, its duration) and a set of constraints (workspace box, catalogue of named locations, robots available,
maximum times). It walks the steps with a simulated clock (integer milliseconds, no wall clock, no sleeping) and a small state per robot
(position, what the gripper holds) and answers a verdict: `accepted` or `rejected`, with one violation for EVERY rule broken (which rule,
which step, which value, which limit) and, where a correction follows from the rule, a deterministic suggestion.

It never executes anything and never releases a plan: the answer always says `executable: false`, and the release of a plan stays with
`POST /release`. An input that cannot be understood (wrong types, unknown keys, too many steps) raises `PlanRequestError`: the caller
answers 400, never an "accepted".
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .primitives import GRIP, MOVE_TO, RELEASE, Params, Step
from .recovery import CONFIG_ENV
from .validation import REQUIRED_PARAMS, validate_step

# Rule names, as they appear in a violation.
RULE_PRIMITIVE = "unknown_primitive"
RULE_PARAMS = "step_params"
RULE_ROBOT = "robot_unavailable"
RULE_DEPENDENCY = "dependency_order"
RULE_LOCATION = "location_unknown"
RULE_WORKSPACE = "workspace_limit"
RULE_GRIPPER = "gripper_state"
RULE_RESOURCE = "resource_conflict"
RULE_STEP_TIME = "step_time_limit"
RULE_PLAN_TIME = "plan_time_limit"

_STEP_KEYS = {"id", "primitive", "params", "robot", "depends_on", "resources", "duration_s"}
_CONSTRAINT_KEYS = {"workspace", "locations", "robots", "max_step_s", "max_total_s", "speed_mm_s"}
_BODY_KEYS = {"steps", "constraints"}


class PlanRequestError(ValueError):
    """The request cannot be understood (the caller answers 400); never turned into a verdict."""


class SimulationConfigError(ValueError):
    """The `plan_simulation` section of the configuration file cannot be used."""


@dataclass(frozen=True)
class SimulationPolicy:
    """Settings of the plan simulation; they come from the configuration file, never from the code.

    `enabled` is the switch: off (the default) the route does not exist and the service answers exactly as before.
    """

    enabled: bool = False
    max_steps: int = 200
    speed_mm_s: float = 100.0
    default_step_s: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise SimulationConfigError("plan_simulation.enabled must be true or false")
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or not 1 <= self.max_steps <= 10000:
            raise SimulationConfigError("plan_simulation.max_steps must be an integer from 1 to 10000")
        for name in ("speed_mm_s", "default_step_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise SimulationConfigError(f"plan_simulation.{name} must be a number above 0")


def load_simulation_policy(path: str | os.PathLike[str] | None = None) -> SimulationPolicy:
    """The `plan_simulation` policy of the file `path`, or of the file named by the planner's configuration variable, or the default (off)."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return SimulationPolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SimulationConfigError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise SimulationConfigError(f"{chosen} must hold a JSON object")
    section = data.get("plan_simulation", {})
    if not isinstance(section, dict):
        raise SimulationConfigError("plan_simulation must be a JSON object")
    unknown = sorted(set(section) - {"enabled", "max_steps", "speed_mm_s", "default_step_s"})
    if unknown:
        raise SimulationConfigError(f"plan_simulation has unknown keys: {', '.join(unknown)}")
    return SimulationPolicy(**section)


class SimClock:
    """A simulated clock in integer milliseconds: it only moves when told to. Nothing here reads or waits for real time."""

    def __init__(self, start_ms: int = 0) -> None:
        self.now_ms = start_ms

    def advance_to(self, when_ms: int) -> int:
        if when_ms < self.now_ms:
            raise ValueError("the simulated clock does not go back")
        self.now_ms = when_ms
        return self.now_ms


@dataclass(frozen=True)
class Violation:
    rule: str
    step_index: int
    step_id: str
    message: str
    value: Any = None
    limit: Any = None
    suggestion: str | None = None


@dataclass
class _Robot:
    free_ms: int = 0
    position: tuple[float, float, float] | None = None
    holding: str | None = None


@dataclass
class _Parsed:
    index: int
    step_id: str
    step: Step
    robot: str
    depends_on: tuple[str, ...]
    resources: tuple[str, ...]
    duration_ms: int | None


@dataclass
class _Constraints:
    workspace: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None
    locations: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    robots: list[str] | None = None
    max_step_ms: int | None = None
    max_total_ms: int | None = None
    speed_mm_s: float | None = None


def _ms(seconds: float) -> int:
    return int(math.ceil(seconds * 1000 - 1e-9))


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PlanRequestError(f"{what} must be a finite number")
    return float(value)


def _positive(value: object, what: str) -> float:
    number = _number(value, what)
    if number <= 0:
        raise PlanRequestError(f"{what} must be above 0")
    return number


def _point(value: object, what: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise PlanRequestError(f"{what} must be a list of three numbers [x, y, z]")
    return (_number(value[0], what), _number(value[1], what), _number(value[2], what))


def _text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanRequestError(f"{what} must be non-empty text")
    return value


def _text_list(value: object, what: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PlanRequestError(f"{what} must be a list of text")
    return tuple(_text(item, f"{what} item") for item in value)


def _parse_constraints(raw: object) -> _Constraints:
    if not isinstance(raw, dict):
        raise PlanRequestError("constraints must be an object")
    unknown = sorted(set(raw) - _CONSTRAINT_KEYS)
    if unknown:
        raise PlanRequestError(f"constraints has unknown keys: {', '.join(unknown)}")
    result = _Constraints()
    if "workspace" in raw:
        box = raw["workspace"]
        if not isinstance(box, dict) or set(box) != {"min", "max"}:
            raise PlanRequestError("workspace must be an object with min and max")
        low, high = _point(box["min"], "workspace.min"), _point(box["max"], "workspace.max")
        if any(a > b for a, b in zip(low, high, strict=True)):
            raise PlanRequestError("workspace.min must not be above workspace.max on any axis")
        result.workspace = (low, high)
    if "locations" in raw:
        places = raw["locations"]
        if not isinstance(places, dict):
            raise PlanRequestError("locations must be an object of name -> [x, y, z]")
        result.locations = {_text(name, "location name"): _point(point, f"location {name!r}") for name, point in places.items()}
    if "robots" in raw:
        result.robots = list(_text_list(raw["robots"], "robots"))
    if "max_step_s" in raw:
        result.max_step_ms = _ms(_positive(raw["max_step_s"], "max_step_s"))
    if "max_total_s" in raw:
        result.max_total_ms = _ms(_positive(raw["max_total_s"], "max_total_s"))
    if "speed_mm_s" in raw:
        result.speed_mm_s = _positive(raw["speed_mm_s"], "speed_mm_s")
    return result


def _parse_steps(raw: object, policy: SimulationPolicy) -> list[_Parsed]:
    if not isinstance(raw, list) or not raw:
        raise PlanRequestError("steps must be a non-empty list")
    if len(raw) > policy.max_steps:
        raise PlanRequestError(f"a plan to simulate has at most {policy.max_steps} steps")
    parsed: list[_Parsed] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PlanRequestError(f"step {index} must be an object")
        unknown = sorted(set(item) - _STEP_KEYS)
        if unknown:
            raise PlanRequestError(f"step {index} has unknown keys: {', '.join(unknown)}")
        step_id = _text(item.get("id", f"s{index}"), f"step {index} id")
        if step_id in seen:
            raise PlanRequestError(f"step id {step_id!r} is repeated")
        seen.add(step_id)
        primitive = _text(item.get("primitive"), f"step {index} primitive")
        params = item.get("params", {})
        if not isinstance(params, dict):
            raise PlanRequestError(f"step {index} params must be an object")
        duration = item.get("duration_s")
        parsed.append(_Parsed(
            index=index,
            step_id=step_id,
            step=Step(primitive, Params(params)),
            robot=_text(item.get("robot"), f"step {index} robot"),
            depends_on=_text_list(item.get("depends_on", []), f"step {index} depends_on"),
            resources=_text_list(item.get("resources", []), f"step {index} resources"),
            duration_ms=None if duration is None else _ms(_positive(duration, f"step {index} duration_s")),
        ))
    return parsed


def _outside(point: tuple[float, float, float], box: tuple[tuple[float, float, float], tuple[float, float, float]]) -> list[str]:
    low, high = box
    return [axis for axis, value, lo, hi in zip("xyz", point, low, high, strict=True) if value < lo or value > hi]


def _clamp(point: tuple[float, float, float], box: tuple[tuple[float, float, float], tuple[float, float, float]]) -> list[float]:
    low, high = box
    return [min(max(value, lo), hi) for value, lo, hi in zip(point, low, high, strict=True)]


def simulate_plan(body: object, policy: SimulationPolicy) -> dict[str, Any]:
    """The verdict on the plan in `body` (`steps`, optional `constraints`). Raises `PlanRequestError` for an input that is not understood."""
    if not isinstance(body, dict):
        raise PlanRequestError("the request must be an object")
    unknown = sorted(set(body) - _BODY_KEYS)
    if unknown:
        raise PlanRequestError(f"the request has unknown keys: {', '.join(unknown)}")
    constraints = _parse_constraints(body.get("constraints", {}))
    steps = _parse_steps(body.get("steps"), policy)
    speed = constraints.speed_mm_s if constraints.speed_mm_s is not None else policy.speed_mm_s

    ids = {parsed.step_id: parsed for parsed in steps}
    violations: list[Violation] = []
    robots: dict[str, _Robot] = {}
    ends: dict[str, int] = {}
    intervals: dict[str, list[tuple[int, int, str]]] = {}
    timeline: list[dict[str, Any]] = []
    clock = SimClock()

    def violate(parsed: _Parsed, rule: str, message: str, value: Any = None, limit: Any = None, suggestion: str | None = None) -> None:
        violations.append(Violation(rule, parsed.index, parsed.step_id, message, value, limit, suggestion))

    for parsed in steps:
        step = parsed.step
        if step.primitive not in REQUIRED_PARAMS:
            violate(parsed, RULE_PRIMITIVE, f"unknown primitive {step.primitive!r}", step.primitive, sorted(REQUIRED_PARAMS),
                    f"use one of: {', '.join(sorted(REQUIRED_PARAMS))}")
        else:
            for issue in validate_step(step):
                violate(parsed, RULE_PARAMS, issue, step.primitive, None)

        if constraints.robots is not None and parsed.robot not in constraints.robots:
            options = sorted(constraints.robots)
            violate(parsed, RULE_ROBOT, f"robot {parsed.robot!r} is not available", parsed.robot, options,
                    f"assign the step to {options[0]!r}" if options else "no robot is available")

        earliest = 0
        for dep in parsed.depends_on:
            if dep not in ids:
                violate(parsed, RULE_DEPENDENCY, f"depends on unknown step {dep!r}", dep, sorted(ids), f"remove the dependency on {dep!r} or add that step before this one")
            elif dep not in ends:
                where = "itself" if dep == parsed.step_id else f"step {dep!r}, which comes later"
                violate(parsed, RULE_DEPENDENCY, f"depends on {where}: a step runs after what it depends on", dep, "earlier step",
                        f"move step {dep!r} before {parsed.step_id!r}" if dep != parsed.step_id else f"remove the dependency of {dep!r} on itself")
            else:
                earliest = max(earliest, ends[dep])

        robot = robots.setdefault(parsed.robot, _Robot())
        start = max(robot.free_ms, earliest)

        # place on the workspace and the catalogue of locations; a move takes distance / speed
        duration = parsed.duration_ms
        location = step.params.get("location") if step.primitive == MOVE_TO else None
        if isinstance(location, str) and location.strip():
            point = constraints.locations.get(location)
            if point is None:
                if constraints.locations:
                    violate(parsed, RULE_LOCATION, f"location {location!r} is not in the catalogue of locations", location, sorted(constraints.locations),
                            "use a location of the catalogue: " + ", ".join(sorted(constraints.locations)))
            else:
                if constraints.workspace is not None:
                    bad = _outside(point, constraints.workspace)
                    if bad:
                        violate(parsed, RULE_WORKSPACE, f"location {location!r} is outside the workspace on {', '.join(bad)}", list(point),
                                {"min": list(constraints.workspace[0]), "max": list(constraints.workspace[1])},
                                f"clamp {location!r} to {_clamp(point, constraints.workspace)}")
                if duration is None and robot.position is not None:
                    duration = _ms(math.dist(robot.position, point) / speed)
                robot.position = point
        if duration is None:
            duration = _ms(policy.default_step_s)
        end = start + duration

        if constraints.max_step_ms is not None and duration > constraints.max_step_ms:
            violate(parsed, RULE_STEP_TIME, f"the step takes {duration} ms, above the {constraints.max_step_ms} ms allowed", duration, constraints.max_step_ms,
                    f"reduce the duration of the step by {duration - constraints.max_step_ms} ms")

        # the gripper of each robot, along the plan (the same rule as the validator, per robot)
        target = step.params.get("target")
        if step.primitive in (GRIP, RELEASE) and isinstance(target, str) and target.strip():
            if step.primitive == GRIP:
                if robot.holding is not None:
                    violate(parsed, RULE_GRIPPER, f"robot {parsed.robot!r} already holds {robot.holding!r}", robot.holding, None,
                            f"release {robot.holding!r} before gripping {target!r}")
                else:
                    robot.holding = target
            elif robot.holding is None:
                violate(parsed, RULE_GRIPPER, f"robot {parsed.robot!r} holds nothing: there is nothing to release of {target!r}", None, target,
                        f"grip {target!r} before releasing it")
            elif robot.holding != target:
                violate(parsed, RULE_GRIPPER, f"robot {parsed.robot!r} holds {robot.holding!r}, not {target!r}", robot.holding, target,
                        f"release {robot.holding!r} first")
            else:
                robot.holding = None

        # a resource is held by one step at a time
        for resource in parsed.resources:
            for other_start, other_end, other_id in intervals.get(resource, []):
                if start < other_end and other_start < end:
                    violate(parsed, RULE_RESOURCE, f"resource {resource!r} is held by step {other_id!r} from {other_start} to {other_end} ms; this step needs it from {start} to {end} ms",
                            resource, other_id, f"make step {parsed.step_id!r} depend on {other_id!r} (it would start at {max(start, other_end)} ms)")
                    break
            intervals.setdefault(resource, []).append((start, end, parsed.step_id))

        robot.free_ms = end
        ends[parsed.step_id] = end
        timeline.append({"step_id": parsed.step_id, "index": parsed.index, "robot": parsed.robot, "primitive": step.primitive, "start_ms": start, "end_ms": end})

    makespan = max(ends.values())
    clock.advance_to(makespan)
    if constraints.max_total_ms is not None and makespan > constraints.max_total_ms:
        last = timeline[max(range(len(timeline)), key=lambda i: timeline[i]["end_ms"])]
        violations.append(Violation(RULE_PLAN_TIME, last["index"], last["step_id"],
                                    f"the plan ends at {makespan} ms, above the {constraints.max_total_ms} ms allowed", makespan, constraints.max_total_ms,
                                    f"shorten the plan by {makespan - constraints.max_total_ms} ms or run independent steps on other robots"))

    violations.sort(key=lambda found: (found.step_index, found.rule))
    return {
        "verdict": "rejected" if violations else "accepted",
        "executable": False,
        "executed": False,
        "violations": [vars(found) for found in violations],
        "timeline": timeline,
        "makespan_ms": makespan,
        "simulated_clock_ms": clock.now_ms,
    }
