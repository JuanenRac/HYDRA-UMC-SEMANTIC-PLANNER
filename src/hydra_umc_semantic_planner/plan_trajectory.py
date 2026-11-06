# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/plan_trajectory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""From a plan to a trajectory, and the kinematic check of that trajectory by HYDRA-UMC-PHYSICS-REPLICA, before anything is executed.

`check_plan_trajectory` takes the same body as `plan_simulation` (steps and a catalogue of named locations in millimetres). Each MOVE_TO of
the robot the URDF belongs to becomes a goal for the position of the tool frame: the replica solves it with `POST /ik` (starting from the
joints reached by the previous move), the joint positions that come out are joined with straight lines in joint space, sampled over the
time of the step, and the whole sampled trajectory goes to `POST /check-trajectory` (limits of position, speed, acceleration, and the
checks the replica has switched on).

The verdict is `accepted` only when every goal was reached AND the replica says the trajectory is `ok` AND `complete`. A goal out of
reach, a limit broken, or a check that was switched off or could not run, is `rejected` with the reason; the replica not answering is an
error (never a verdict). The answer always says `executable: false`: it only informs the person who approves, and the release of a plan
stays with `POST /release`. Only the position of the tool is solved (the replica does not solve the orientation), and the path between two
poses is a joint-space line, not a Cartesian one: both are said in the answer.

A request may also ask for an orientation of a location (`orientations`, name -> quaternion `[w, x, y, z]`). The replica cannot solve it, so
the planner asks `POST /fk` for the pose of the tool frame at the joints that were reached for the position and compares the rotation with
the one asked for (`orientation_tolerance_rad`). If it matches, the goal is counted in `orientations_verified`; if it does not, the goal
is NOT shown to be reachable with that orientation: it goes to `unchecked` and the verdict is `unchecked` (never `accepted`), unless
something else is broken, which is `rejected`.

The switch is `plan_trajectory.enabled` in the configuration file and is OFF by default (the route then does not exist). Address, token
file, tool frame, starting joints, sampling and timeout are configuration values, not code.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .plan_simulation import PlanRequestError, SimulationPolicy, _ms, _parse_constraints, _parse_steps
from .primitives import MOVE_TO
from .recovery import CONFIG_ENV

RULE_UNREACHABLE = "goal_unreachable"
RULE_LOCATION = "location_unknown"
RULE_LIMIT = "trajectory_limit"
RULE_INCOMPLETE = "check_incomplete"
RULE_ORIENTATION = "orientation_unchecked"
MAX_RESPONSE_BYTES = 1024 * 1024
_KNOWN_KEYS = {"enabled", "url", "token_file", "timeout_s", "robot", "target", "start_joints", "samples_per_segment", "max_moves", "mm_to_m", "orientation_tolerance_rad"}
_BODY_KEYS = {"steps", "constraints", "start_joints", "orientations"}


class TrajectoryConfigError(ValueError):
    """The `plan_trajectory` section of the configuration file, or the token file it names, cannot be used."""


class TrajectoryServiceError(RuntimeError):
    """The replica did not give a usable answer; the caller answers 502, never a verdict."""


def _joints(value: object, what: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise TrajectoryConfigError(f"{what} must be a non-empty object of joint name -> radians (or metres)")
    out: dict[str, float] = {}
    for name, position in value.items():
        if not isinstance(name, str) or not name.strip():
            raise TrajectoryConfigError(f"{what} has a joint without a name")
        if isinstance(position, bool) or not isinstance(position, (int, float)) or not math.isfinite(position):
            raise TrajectoryConfigError(f"{what}.{name} must be a finite number")
        out[name] = float(position)
    return out


@dataclass(frozen=True)
class TrajectoryPolicy:
    """Settings of the check. `enabled` is the switch: off (the default) `POST /plan/trajectory-check` does not exist (404)."""

    enabled: bool = False
    url: str = "http://127.0.0.1:8118"
    token_file: str = ""
    timeout_s: float = 5.0
    robot: str = ""
    target: str = "tool"
    start_joints: dict[str, float] = field(default_factory=dict)
    samples_per_segment: int = 10
    max_moves: int = 100
    mm_to_m: float = 0.001
    orientation_tolerance_rad: float = 0.05

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TrajectoryConfigError("plan_trajectory.enabled must be true or false")
        if not isinstance(self.url, str) or urlparse(self.url).scheme not in ("http", "https") or not urlparse(self.url).hostname:
            raise TrajectoryConfigError("plan_trajectory.url must be an http(s) address")
        for name in ("token_file", "robot", "target"):
            if not isinstance(getattr(self, name), str):
                raise TrajectoryConfigError(f"plan_trajectory.{name} must be text")
        timeout = self.timeout_s
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise TrajectoryConfigError("plan_trajectory.timeout_s must be a number above 0 and at most 60")
        for name, low, high in (("samples_per_segment", 2, 500), ("max_moves", 1, 1000)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise TrajectoryConfigError(f"plan_trajectory.{name} must be a whole number from {low} to {high}")
        scale = self.mm_to_m
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
            raise TrajectoryConfigError("plan_trajectory.mm_to_m must be a number above 0")
        tolerance = self.orientation_tolerance_rad
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not 0 < tolerance <= math.pi:
            raise TrajectoryConfigError("plan_trajectory.orientation_tolerance_rad must be a number above 0 and at most pi")
        if self.start_joints:
            _joints(self.start_joints, "plan_trajectory.start_joints")
        if self.enabled:
            if not self.robot.strip():
                raise TrajectoryConfigError("plan_trajectory.robot must name the robot the URDF of the replica belongs to")
            if not self.target.strip():
                raise TrajectoryConfigError("plan_trajectory.target must name the joint whose frame is the tool")


def load_trajectory_policy(path: str | os.PathLike[str] | None = None) -> TrajectoryPolicy:
    """The `plan_trajectory` policy of the file `path`, or of the file named by the planner's configuration variable, or the default (off)."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return TrajectoryPolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TrajectoryConfigError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise TrajectoryConfigError(f"{chosen} must hold a JSON object")
    section = data.get("plan_trajectory", {})
    if not isinstance(section, dict):
        raise TrajectoryConfigError("plan_trajectory must be a JSON object")
    unknown = sorted(set(section) - _KNOWN_KEYS)
    if unknown:
        raise TrajectoryConfigError(f"plan_trajectory has unknown keys: {', '.join(unknown)}")
    return TrajectoryPolicy(**section)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None


Transport = Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]]


class ReplicaClient:
    """Posts JSON to the replica. The bearer token is read from its file once and never printed."""

    def __init__(self, policy: TrajectoryPolicy, token: str = "") -> None:
        self.policy = policy
        self._token = token

    @classmethod
    def from_policy(cls, policy: TrajectoryPolicy) -> ReplicaClient | None:
        if not policy.enabled:
            return None
        token = ""
        if policy.token_file:
            try:
                token = Path(policy.token_file).read_text(encoding="utf-8").splitlines()[0].strip()
            except (OSError, IndexError) as error:
                raise TrajectoryConfigError("cannot read the token file of plan_trajectory") from error
        return cls(policy, token)

    def __call__(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            self.policy.url.rstrip("/") + path, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=float(self.policy.timeout_s)) as response:  # noqa: S310 - scheme checked by the policy
                status, raw = response.status, response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.URLError) as error:
            raise TrajectoryServiceError("the physics replica did not answer") from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise TrajectoryServiceError("the answer of the physics replica is too large")
        try:
            answer = json.loads(raw)
        except ValueError as error:
            raise TrajectoryServiceError("the physics replica did not send JSON") from error
        if not isinstance(answer, dict):
            raise TrajectoryServiceError("the physics replica did not send an object")
        return status, answer


def _quaternion(value: object, what: str) -> tuple[float, float, float, float]:
    """A rotation as [w, x, y, z], normalised; anything else is a bad request."""
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in value):
        raise PlanRequestError(f"{what} must be a quaternion [w, x, y, z] of four finite numbers")
    norm = math.sqrt(sum(float(n) ** 2 for n in value))
    if norm < 1e-9:
        raise PlanRequestError(f"{what} must not be the zero quaternion")
    w, x, y, z = (float(n) / norm for n in value)
    return w, x, y, z


def _parse_orientations(raw: object, locations: dict[str, Any]) -> dict[str, tuple[float, float, float, float]]:
    if not isinstance(raw, dict):
        raise PlanRequestError("orientations must be an object of location name -> [w, x, y, z]")
    out: dict[str, tuple[float, float, float, float]] = {}
    for name, value in raw.items():
        if name not in locations:
            raise PlanRequestError(f"orientations names the location {name!r}, which is not in the catalogue of locations")
        out[name] = _quaternion(value, f"orientation of {name!r}")
    return out


def _rotation_error(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """The angle in radians between two unit quaternions (q and -q are the same rotation)."""
    dot = abs(sum(p * q for p, q in zip(a, b, strict=True)))
    return 2.0 * math.acos(min(1.0, dot))


def _tool_quaternion(answer: dict[str, Any], target: str) -> tuple[float, float, float, float]:
    poses = answer.get("poses")
    for pose in poses if isinstance(poses, list) else []:
        if isinstance(pose, dict) and pose.get("joint") == target and isinstance(pose.get("quaternion"), dict):
            quaternion = pose["quaternion"]
            try:
                return _quaternion([quaternion["w"], quaternion["x"], quaternion["y"], quaternion["z"]], "the quaternion of the replica")
            except (KeyError, PlanRequestError) as error:
                raise TrajectoryServiceError("the physics replica sent a pose without a usable rotation") from error
    raise TrajectoryServiceError("the physics replica did not send the pose of the tool frame")


def _violation(rule: str, index: int, step_id: str, message: str, value: Any = None, limit: Any = None) -> dict[str, Any]:
    return {"rule": rule, "step_index": index, "step_id": step_id, "message": message, "value": value, "limit": limit}


def check_plan_trajectory(body: object, policy: TrajectoryPolicy, transport: Transport, sim_policy: SimulationPolicy | None = None) -> dict[str, Any]:
    """The verdict on the trajectory of the plan in `body`. Raises `PlanRequestError` for an input that is not understood and
    `TrajectoryServiceError` when the replica gives no usable answer."""
    if not isinstance(body, dict):
        raise PlanRequestError("the request must be an object")
    unknown = sorted(set(body) - _BODY_KEYS)
    if unknown:
        raise PlanRequestError(f"the request has unknown keys: {', '.join(unknown)}")
    constraints = _parse_constraints(body.get("constraints", {}))
    steps = _parse_steps(body.get("steps"), sim_policy or SimulationPolicy(enabled=True))
    try:
        start = _joints(body["start_joints"], "start_joints") if "start_joints" in body else dict(policy.start_joints)
        if not start:
            raise TrajectoryConfigError("the starting joints are missing")
    except TrajectoryConfigError as error:
        raise PlanRequestError(f"{error}: give start_joints in the request or in plan_trajectory.start_joints") from error
    speed = constraints.speed_mm_s if constraints.speed_mm_s is not None else (sim_policy.speed_mm_s if sim_policy else 100.0)
    default_ms = _ms(sim_policy.default_step_s if sim_policy else 1.0)
    orientations = _parse_orientations(body["orientations"], constraints.locations) if "orientations" in body else {}

    violations: list[dict[str, Any]] = []
    unchecked: list[dict[str, Any]] = []
    verified = 0
    skipped: list[str] = []
    waypoints: list[tuple[str, int, dict[str, float], int]] = []  # (step id, index, joints reached, segment ms)
    current = dict(start)
    position: tuple[float, float, float] | None = None
    moves = 0
    for parsed in steps:
        if parsed.step.primitive != MOVE_TO:
            continue
        if parsed.robot != policy.robot:
            if parsed.robot not in skipped:
                skipped.append(parsed.robot)
            continue
        location = parsed.step.params.get("location")
        point = constraints.locations.get(location) if isinstance(location, str) else None
        if point is None:
            violations.append(_violation(RULE_LOCATION, parsed.index, parsed.step_id, f"location {location!r} is not in the catalogue of locations", location, sorted(constraints.locations)))
            continue
        moves += 1
        if moves > policy.max_moves:
            raise PlanRequestError(f"a plan to check has at most {policy.max_moves} moves of the robot")
        goal = [coordinate * policy.mm_to_m for coordinate in point]
        status, answer = transport("/ik", {"target": policy.target, "goal": goal, "joints": current})
        if status != 200:
            raise TrajectoryServiceError(f"the physics replica refused the inverse kinematics (HTTP {status}, {answer.get('code', 'no code')})")
        if answer.get("reached") is not True or not isinstance(answer.get("joints"), dict):
            violations.append(_violation(RULE_UNREACHABLE, parsed.index, parsed.step_id, f"location {location!r} cannot be reached by the robot", answer.get("residual"), "tolerance of the replica"))
            continue
        reached = {name: float(value) for name, value in answer["joints"].items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
        if set(reached) != set(current):
            raise TrajectoryServiceError("the inverse kinematics answered other joints than the ones given")
        wanted = orientations.get(location) if isinstance(location, str) else None
        if wanted is not None:
            # The replica solves the position only: read the rotation it ended with and compare; a mismatch is "not shown", not "impossible".
            status, fk = transport("/fk", {"joints": reached})
            if status != 200:
                raise TrajectoryServiceError(f"the physics replica refused the forward kinematics (HTTP {status}, {fk.get('code', 'no code')})")
            angle = _rotation_error(wanted, _tool_quaternion(fk, policy.target))
            if angle <= policy.orientation_tolerance_rad:
                verified += 1
            else:
                unchecked.append(_violation(RULE_ORIENTATION, parsed.index, parsed.step_id, f"the orientation asked for at {location!r} is not shown to be reachable: the replica solves only the position", angle, policy.orientation_tolerance_rad))
        duration = parsed.duration_ms
        if duration is None:
            duration = _ms(math.dist(position, point) / speed) if position is not None else default_ms
        waypoints.append((parsed.step_id, parsed.index, reached, max(duration, 1)))
        current, position = reached, point
    if not waypoints and not violations:
        raise PlanRequestError("the plan has no MOVE_TO of the robot " + repr(policy.robot) + " to check")

    samples: list[dict[str, Any]] = [{"t": 0.0, "joints": dict(start)}]
    previous, clock_ms = dict(start), 0
    for _step_id, _index, reached, duration in waypoints:
        for k in range(1, policy.samples_per_segment + 1):
            fraction = k / policy.samples_per_segment
            samples.append({"t": (clock_ms + duration * fraction) / 1000.0,
                            "joints": {name: previous[name] + (reached[name] - previous[name]) * fraction for name in previous}})
        previous, clock_ms = reached, clock_ms + duration

    check: dict[str, Any] = {}
    if len(samples) >= 2 and waypoints:
        status, check = transport("/check-trajectory", {"samples": samples})
        if status != 200:
            raise TrajectoryServiceError(f"the physics replica refused the check of the trajectory (HTTP {status}, {check.get('code', 'no code')})")
        for found in check.get("violations", []) if isinstance(check.get("violations"), list) else []:
            if isinstance(found, dict):
                where = _segment_of(found.get("sample"), waypoints, policy.samples_per_segment)
                violations.append(_violation(RULE_LIMIT, where[1], where[0], f"{found.get('kind', 'limit')} of joint {found.get('joint')!r} is out of its limit", found.get("value"), found.get("limit")))
        if check.get("ok") is not True and not any(v["rule"] == RULE_LIMIT for v in violations):
            violations.append(_violation(RULE_LIMIT, waypoints[0][1], waypoints[0][0], "the physics replica does not approve the trajectory"))
        if check.get("complete") is not True:
            violations.append(_violation(RULE_INCOMPLETE, waypoints[-1][1], waypoints[-1][0], "a check of the replica was switched off or could not run: the trajectory is not shown to be clear", check.get("notes")))

    violations.sort(key=lambda found: (found["step_index"], found["rule"]))
    unchecked.sort(key=lambda found: found["step_index"])
    return {
        "verdict": "rejected" if violations else ("unchecked" if unchecked else "accepted"),
        "unchecked": unchecked,
        "orientations_requested": len(orientations),
        "orientations_verified": verified,
        "executable": False,
        "executed": False,
        "violations": violations,
        "moves_checked": len(waypoints),
        "samples": len(samples),
        "complete": bool(check.get("complete")) if waypoints else False,
        "skipped_robots": skipped,
        "assumptions": ["only the position of the tool is solved, not its orientation (an orientation asked for is only compared with the one reached)", "the path between two poses is a straight line in joint space"],
    }


def _segment_of(sample: object, waypoints: list[tuple[str, int, dict[str, float], int]], per_segment: int) -> tuple[str, int]:
    """The step whose segment holds the sample index the replica names (sample 0 is the starting pose: it belongs to the first move)."""
    if isinstance(sample, bool) or not isinstance(sample, int) or sample < 1:
        return waypoints[0][0], waypoints[0][1]
    segment = min((sample - 1) // per_segment, len(waypoints) - 1)
    return waypoints[segment][0], waypoints[segment][1]
