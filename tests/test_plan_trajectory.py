# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_plan_trajectory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The plan as a trajectory checked by the physics replica: a fake replica, the verdict rules, the switch and the HTTP route."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from test_api import _post

from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.plan_simulation import PlanRequestError
from hydra_umc_semantic_planner.plan_trajectory import (
    ReplicaClient,
    TrajectoryConfigError,
    TrajectoryPolicy,
    TrajectoryServiceError,
    check_plan_trajectory,
    load_trajectory_policy,
)

START = {"j1": 0.0, "j2": 0.0}
POLICY = TrajectoryPolicy(enabled=True, robot="r1", target="tool", start_joints=START, samples_per_segment=4)
LOCATIONS = {"a": [100, 0, 0], "b": [200, 0, 0], "out": [9000, 0, 0]}


def plan(*places: str, robot: str = "r1") -> dict[str, Any]:
    return {"steps": [{"primitive": "MOVE_TO", "robot": robot, "params": {"location": place}} for place in places],
            "constraints": {"locations": LOCATIONS, "speed_mm_s": 100}}


class FakeReplica:
    """A replica of one joint per millimetre: j1 = x / 100 (radians), j2 = 0. Records what it is asked."""

    def __init__(self, check: dict[str, Any] | None = None, ik_status: int = 200) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.check = check if check is not None else {"ok": True, "complete": True, "violations": []}
        self.ik_status = ik_status

    def __call__(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.calls.append((path, payload))
        if path == "/ik":
            if self.ik_status != 200:
                return self.ik_status, {"code": "ik_off"}
            x = payload["goal"][0]
            if x > 1.0:
                return 200, {"reached": False, "residual": x - 1.0, "iterations": 200, "timed_out": False}
            return 200, {"reached": True, "residual": 0.0, "iterations": 3, "timed_out": False, "joints": {"j1": x * 10, "j2": 0.0}}
        return 200, self.check


def test_accepted_when_reached_and_checked_complete() -> None:
    fake = FakeReplica()
    verdict = check_plan_trajectory(plan("a", "b"), POLICY, fake)
    assert verdict["verdict"] == "accepted" and verdict["executable"] is False and verdict["executed"] is False
    assert verdict["moves_checked"] == 2 and verdict["samples"] == 1 + 2 * 4 and verdict["complete"] is True
    ik_calls = [payload for path, payload in fake.calls if path == "/ik"]
    assert ik_calls[0]["goal"] == pytest.approx([0.1, 0.0, 0.0]) and ik_calls[0]["joints"] == START
    assert ik_calls[1]["joints"] == {"j1": pytest.approx(1.0), "j2": 0.0}  # the second goal starts from the joints reached by the first
    samples = fake.calls[-1][1]["samples"]
    times = [sample["t"] for sample in samples]
    assert times == sorted(set(times)) and samples[0]["joints"] == START and samples[-1]["joints"]["j1"] == pytest.approx(2.0)


def test_goal_out_of_reach_is_rejected_with_the_step() -> None:
    verdict = check_plan_trajectory(plan("a", "out"), POLICY, FakeReplica())
    assert verdict["verdict"] == "rejected"
    found = [v for v in verdict["violations"] if v["rule"] == "goal_unreachable"]
    assert len(found) == 1 and found[0]["step_index"] == 1


def test_unknown_location_is_rejected() -> None:
    verdict = check_plan_trajectory(plan("a", "nowhere"), POLICY, FakeReplica())
    assert [v["rule"] for v in verdict["violations"]] == ["location_unknown"]


def test_limit_broken_names_the_segment() -> None:
    check = {"ok": False, "complete": True, "violations": [{"kind": "velocity", "joint": "j1", "sample": 6, "t": 1.0, "value": 3.0, "limit": 2.0}]}
    verdict = check_plan_trajectory(plan("a", "b"), POLICY, FakeReplica(check))
    assert verdict["verdict"] == "rejected"
    limit = [v for v in verdict["violations"] if v["rule"] == "trajectory_limit"][0]
    assert limit["step_index"] == 1 and limit["value"] == 3.0 and limit["limit"] == 2.0


def test_ok_but_not_complete_is_never_accepted() -> None:
    verdict = check_plan_trajectory(plan("a"), POLICY, FakeReplica({"ok": True, "complete": False, "violations": [], "notes": ["no collision shapes"]}))
    assert verdict["verdict"] == "rejected" and verdict["complete"] is False
    assert [v["rule"] for v in verdict["violations"]] == ["check_incomplete"]


def test_other_robots_are_skipped_and_named() -> None:
    body = plan("a")
    body["steps"].append({"primitive": "MOVE_TO", "robot": "r2", "params": {"location": "b"}})
    verdict = check_plan_trajectory(body, POLICY, FakeReplica())
    assert verdict["verdict"] == "accepted" and verdict["skipped_robots"] == ["r2"] and verdict["moves_checked"] == 1


def test_a_plan_without_moves_of_the_robot_is_a_bad_request() -> None:
    with pytest.raises(PlanRequestError, match="no MOVE_TO"):
        check_plan_trajectory(plan("a", robot="r2"), POLICY, FakeReplica())
    with pytest.raises(PlanRequestError, match="unknown keys"):
        check_plan_trajectory({**plan("a"), "extra": 1}, POLICY, FakeReplica())
    with pytest.raises(PlanRequestError, match="starting joints"):
        check_plan_trajectory(plan("a"), TrajectoryPolicy(enabled=True, robot="r1"), FakeReplica())


def test_the_replica_refusing_is_an_error_not_a_verdict() -> None:
    with pytest.raises(TrajectoryServiceError, match="ik_off"):
        check_plan_trajectory(plan("a"), POLICY, FakeReplica(ik_status=404))


def test_ik_that_answers_other_joints_is_an_error() -> None:
    def odd(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return 200, {"reached": True, "joints": {"zz": 1.0}}
    with pytest.raises(TrajectoryServiceError):
        check_plan_trajectory(plan("a"), POLICY, odd)


def test_request_start_joints_override_the_configured_ones() -> None:
    fake = FakeReplica()
    check_plan_trajectory({**plan("a"), "start_joints": {"j1": 0.5, "j2": 0.0}}, POLICY, fake)
    assert fake.calls[0][1]["joints"] == {"j1": 0.5, "j2": 0.0}


def test_policy_is_validated_and_off_by_default(tmp_path: Path) -> None:
    assert load_trajectory_policy().enabled is False
    for bad in ({"enabled": "yes"}, {"url": "ftp://x"}, {"timeout_s": 0}, {"samples_per_segment": 1}, {"mm_to_m": -1}, {"enabled": True}, {"surprise": 1}):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"plan_trajectory": bad}), encoding="utf-8")
        with pytest.raises(TrajectoryConfigError):
            load_trajectory_policy(path)
    good = tmp_path / "g.json"
    good.write_text(json.dumps({"plan_trajectory": {"enabled": True, "robot": "r1", "start_joints": START}}), encoding="utf-8")
    assert load_trajectory_policy(good).robot == "r1"


def test_a_token_file_that_cannot_be_read_stops_the_start(tmp_path: Path) -> None:
    with pytest.raises(TrajectoryConfigError):
        ReplicaClient.from_policy(TrajectoryPolicy(enabled=True, robot="r1", start_joints=START, token_file=str(tmp_path / "missing")))
    assert ReplicaClient.from_policy(TrajectoryPolicy()) is None


class _Replica(BaseHTTPRequestHandler):
    seen: list[tuple[str, str | None]] = []

    def do_POST(self) -> None:  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((self.path, self.headers.get("Authorization")))
        if self.path == "/ik":
            out: dict[str, Any] = {"reached": True, "joints": {"j1": payload["goal"][0] * 10, "j2": 0.0}}
        else:
            out = {"ok": True, "complete": True, "violations": []}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args: object) -> None:
        return


def test_real_http_client_sends_the_token_and_the_route_answers(tmp_path: Path) -> None:
    replica = HTTPServer(("127.0.0.1", 0), _Replica)
    threading.Thread(target=replica.serve_forever, daemon=True).start()
    token = tmp_path / "token"
    token.write_text("s3cret\n", encoding="utf-8")
    policy = TrajectoryPolicy(enabled=True, url=f"http://127.0.0.1:{replica.server_address[1]}", token_file=str(token), robot="r1", start_joints=START)
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", trajectory=policy, replica=ReplicaClient.from_policy(policy))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, verdict = _post(f"{base}/plan/trajectory-check", plan("a", "b"))
        assert status == 200 and verdict["verdict"] == "accepted"
        assert ("/ik", "Bearer s3cret") in _Replica.seen and ("/check-trajectory", "Bearer s3cret") in _Replica.seen
        assert _post(f"{base}/plan/trajectory-check", {"steps": "no"})[0] == 400
    finally:
        server.shutdown()
        server.server_close()
        replica.shutdown()
        replica.server_close()


def test_route_is_404_when_off_and_502_when_the_replica_is_down() -> None:
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert _post(f"http://127.0.0.1:{server.server_address[1]}/plan/trajectory-check", plan("a")) == (404, {"error": "not found"})
    finally:
        server.shutdown()
        server.server_close()
    policy = TrajectoryPolicy(enabled=True, url="http://127.0.0.1:9", robot="r1", start_joints=START, timeout_s=1)
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", trajectory=policy, replica=ReplicaClient(policy))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, error = _post(f"http://127.0.0.1:{server.server_address[1]}/plan/trajectory-check", plan("a"))
        assert status == 502 and "did not answer" in error["error"]
    finally:
        server.shutdown()
        server.server_close()
