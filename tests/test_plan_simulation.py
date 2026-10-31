# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_plan_simulation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The plan simulation: verdicts and explanations, the simulated clock, properties with a fixed seed, the switch and the HTTP route."""
from __future__ import annotations

import copy
import json
import random
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from test_api import _post
from test_api_characterization import _raw_post

from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.main import main
from hydra_umc_semantic_planner.plan_simulation import (
    PlanRequestError,
    SimClock,
    SimulationConfigError,
    SimulationPolicy,
    load_simulation_policy,
    simulate_plan,
)

ON = SimulationPolicy(enabled=True)

CONSTRAINTS: dict[str, Any] = {
    "workspace": {"min": [0, 0, 0], "max": [500, 500, 300]},
    "locations": {"home": [0, 0, 100], "bin": [200, 0, 100], "bench": [200, 300, 100], "far": [900, 0, 100]},
    "robots": ["r1", "r2"],
    "speed_mm_s": 100,
}


def step(primitive: str, robot: str = "r1", sid: str | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"primitive": primitive, "robot": robot, **extra}
    if sid:
        out["id"] = sid
    return out


def move(place: str, robot: str = "r1", **extra: Any) -> dict[str, Any]:
    return step("MOVE_TO", robot, params={"location": place}, **extra)


def rules(verdict: dict[str, Any]) -> list[str]:
    return [found["rule"] for found in verdict["violations"]]


def run(steps: list[dict[str, Any]], constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    return simulate_plan({"steps": steps, "constraints": CONSTRAINTS if constraints is None else constraints}, ON)


# --- verdicts -------------------------------------------------------------------------------------------------------------------------


def test_a_good_plan_is_accepted_with_its_timeline() -> None:
    verdict = run([
        move("home", sid="a"),
        move("bin", sid="b"),
        step("GRIP", params={"target": "pcb"}, sid="c", duration_s=0.5),
        move("bench", sid="d"),
        step("RELEASE", params={"target": "pcb"}, sid="e", duration_s=0.5),
    ])
    assert verdict["verdict"] == "accepted"
    assert verdict["violations"] == []
    assert verdict["executable"] is False and verdict["executed"] is False
    # first move has no known start: default 1 s; home->bin 200 mm at 100 mm/s = 2 s; bin->bench 300 mm = 3 s
    assert [(t["step_id"], t["start_ms"], t["end_ms"]) for t in verdict["timeline"]] == [
        ("a", 0, 1000), ("b", 1000, 3000), ("c", 3000, 3500), ("d", 3500, 6500), ("e", 6500, 7000)]
    assert verdict["makespan_ms"] == verdict["simulated_clock_ms"] == 7000


def test_workspace_limit_names_rule_step_value_and_a_clamp() -> None:
    verdict = run([move("home"), move("far")])
    assert verdict["verdict"] == "rejected"
    found = verdict["violations"][0]
    assert found["rule"] == "workspace_limit" and found["step_index"] == 1
    assert found["value"] == [900.0, 0.0, 100.0] and found["limit"]["max"] == [500.0, 500.0, 300.0]
    assert found["suggestion"] == "clamp 'far' to [500.0, 0.0, 100.0]"


def test_unknown_location_unknown_primitive_and_missing_param() -> None:
    verdict = run([move("nowhere"), step("DANCE"), step("GRIP", params={})])
    assert rules(verdict) == ["location_unknown", "unknown_primitive", "step_params"]
    assert verdict["violations"][0]["suggestion"].startswith("use a location of the catalogue")


def test_robot_not_available_suggests_the_first_available() -> None:
    verdict = run([move("home", robot="r9")])
    found = verdict["violations"][0]
    assert found["rule"] == "robot_unavailable" and found["value"] == "r9" and found["suggestion"] == "assign the step to 'r1'"


def test_dependencies_must_point_to_earlier_steps() -> None:
    verdict = run([move("home", sid="a", depends_on=["b"]), move("bin", sid="b"), move("bin", sid="c", depends_on=["zz"])])
    assert rules(verdict) == ["dependency_order", "dependency_order"]
    assert "comes later" in verdict["violations"][0]["message"]
    assert "unknown step" in verdict["violations"][1]["message"]


def test_a_dependency_delays_the_start_on_another_robot() -> None:
    verdict = run([move("home", sid="a", duration_s=4), move("bin", robot="r2", sid="b", depends_on=["a"], duration_s=1)])
    assert verdict["verdict"] == "accepted"
    assert verdict["timeline"][1]["start_ms"] == 4000


def test_the_gripper_is_followed_per_robot() -> None:
    verdict = run([
        step("GRIP", "r1", params={"target": "a"}),
        step("GRIP", "r2", params={"target": "b"}),  # another robot: fine
        step("GRIP", "r1", params={"target": "c"}),
        step("RELEASE", "r2", params={"target": "zz"}),
    ])
    assert rules(verdict) == ["gripper_state", "gripper_state"]
    assert verdict["violations"][0]["step_index"] == 2 and "already holds 'a'" in verdict["violations"][0]["message"]
    assert verdict["violations"][0]["suggestion"] == "release 'a' before gripping 'c'"
    assert verdict["violations"][1]["suggestion"] == "release 'b' first"


def test_a_resource_held_by_two_robots_at_once_is_a_conflict_with_a_correction() -> None:
    verdict = run([
        move("home", "r1", sid="a", resources=["fixture"], duration_s=5),
        move("bin", "r2", sid="b", resources=["fixture"], duration_s=1),
    ])
    found = verdict["violations"][0]
    assert found["rule"] == "resource_conflict" and found["step_id"] == "b" and found["limit"] == "a"
    assert found["suggestion"] == "make step 'b' depend on 'a' (it would start at 5000 ms)"
    fixed = run([
        move("home", "r1", sid="a", resources=["fixture"], duration_s=5),
        move("bin", "r2", sid="b", resources=["fixture"], duration_s=1, depends_on=["a"]),
    ])
    assert fixed["verdict"] == "accepted"


def test_time_limits_explain_by_how_much() -> None:
    verdict = run([move("home", duration_s=3), move("bin", duration_s=9)], {"max_step_s": 5, "max_total_s": 10})
    assert rules(verdict) == ["plan_time_limit", "step_time_limit"]
    assert verdict["violations"][1]["suggestion"] == "reduce the duration of the step by 4000 ms"
    assert verdict["violations"][0]["value"] == 12000 and verdict["violations"][0]["limit"] == 10000


def test_every_rejection_is_listed_not_only_the_first() -> None:
    verdict = run([move("far", robot="r9"), step("DANCE")])
    assert {"workspace_limit", "robot_unavailable", "unknown_primitive"} <= set(rules(verdict))


# --- fail closed ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    None, [], "x", 3, {}, {"steps": []}, {"steps": "x"}, {"steps": [1]}, {"steps": [{"primitive": "WAIT"}]},
    {"steps": [{"primitive": "WAIT", "robot": "r1", "extra": 1}]},
    {"steps": [{"primitive": "WAIT", "robot": "r1", "duration_s": -1}]},
    {"steps": [{"primitive": "WAIT", "robot": "r1", "duration_s": True}]},
    {"steps": [{"primitive": "WAIT", "robot": "r1", "duration_s": float("nan")}]},
    {"steps": [{"primitive": "WAIT", "robot": "r1", "depends_on": "a"}]},
    {"steps": [{"primitive": "WAIT", "robot": "r1", "params": []}]},
    {"steps": [{"primitive": "WAIT", "robot": "r1", "id": "a"}, {"primitive": "WAIT", "robot": "r1", "id": "a"}]},
    {"steps": [{"primitive": "WAIT", "robot": "r1"}], "constraints": []},
    {"steps": [{"primitive": "WAIT", "robot": "r1"}], "constraints": {"bogus": 1}},
    {"steps": [{"primitive": "WAIT", "robot": "r1"}], "constraints": {"workspace": {"min": [5, 0, 0], "max": [1, 0, 0]}}},
    {"steps": [{"primitive": "WAIT", "robot": "r1"}], "constraints": {"locations": {"a": [1, 2]}}},
    {"steps": [{"primitive": "WAIT", "robot": "r1"}], "constraints": {"max_total_s": 0}},
    {"steps": [{"primitive": "WAIT", "robot": "r1"}], "extra": 1},
])
def test_malformed_input_is_refused_never_accepted(body: object) -> None:
    with pytest.raises(PlanRequestError):
        simulate_plan(body, ON)


def test_too_many_steps_is_refused() -> None:
    with pytest.raises(PlanRequestError, match="at most 3 steps"):
        simulate_plan({"steps": [step("WAIT")] * 4}, SimulationPolicy(enabled=True, max_steps=3))


# --- the simulated clock --------------------------------------------------------------------------------------------------------------


def test_the_clock_only_moves_when_told_and_never_back() -> None:
    clock = SimClock()
    assert clock.advance_to(500) == 500
    with pytest.raises(ValueError):
        clock.advance_to(100)


def test_a_long_plan_simulates_without_reading_or_waiting_for_real_time(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> float:
        raise AssertionError("the simulation touched real time")

    for name in ("time", "monotonic", "sleep", "perf_counter"):
        monkeypatch.setattr(time, name, forbidden)
    verdict = run([step("WAIT", params={}, duration_s=3600) for _ in range(50)])
    assert verdict["makespan_ms"] == 50 * 3600 * 1000


# --- properties, fixed seed -----------------------------------------------------------------------------------------------------------


def _random_valid_plan(rng: random.Random) -> tuple[list[dict[str, Any]], int]:
    names = ["home", "bin", "bench"]
    steps: list[dict[str, Any]] = []
    total = 0
    for n in range(rng.randint(1, 12)):
        if rng.random() < 0.5:
            ms = rng.randint(1, 5000)
            steps.append(step("WAIT", params={}, sid=f"w{n}", duration_s=ms / 1000))
        else:
            ms = rng.randint(1, 5000)
            steps.append(move(rng.choice(names), sid=f"m{n}", duration_s=ms / 1000))
        total += ms
    return steps, total


def test_property_valid_sequential_plans_are_accepted_and_add_up() -> None:
    rng = random.Random(20241031)
    for _ in range(300):
        steps, total = _random_valid_plan(rng)
        verdict = run(steps)
        assert verdict["verdict"] == "accepted", verdict["violations"]
        assert verdict["makespan_ms"] == total
        ends = [t["end_ms"] for t in verdict["timeline"]]
        assert ends == sorted(ends)
        assert verdict["executable"] is False and verdict["executed"] is False


def test_property_a_location_outside_the_workspace_is_always_found_at_its_step() -> None:
    rng = random.Random(7)
    for _ in range(200):
        steps, _ = _random_valid_plan(rng)
        at = rng.randrange(len(steps))
        steps[at] = move("far", sid=f"bad{at}")
        verdict = run(steps)
        assert verdict["verdict"] == "rejected"
        assert any(f["rule"] == "workspace_limit" and f["step_index"] == at for f in verdict["violations"])


def test_property_the_verdict_is_deterministic_and_does_not_change_the_input() -> None:
    rng = random.Random(99)
    for _ in range(100):
        steps, _ = _random_valid_plan(rng)
        if rng.random() < 0.5:
            steps.append(move("far", robot=rng.choice(["r1", "r9"])))
        before = copy.deepcopy(steps)
        assert json.dumps(run(steps), sort_keys=True) == json.dumps(run(steps), sort_keys=True)
        assert steps == before


def test_property_random_garbage_is_refused_or_judged_but_never_crashes_or_accepts_nonsense() -> None:
    rng = random.Random(5)
    atoms: list[Any] = [None, True, 0, -3, 2.5, "x", "", [], {}, [1, 2, 3], {"a": 1}, float("inf")]

    def junk(depth: int = 0) -> Any:
        if depth > 2 or rng.random() < 0.5:
            return rng.choice(atoms)
        if rng.random() < 0.5:
            return [junk(depth + 1) for _ in range(rng.randint(0, 3))]
        return {rng.choice(["steps", "constraints", "primitive", "robot", "id", "params", "depends_on", "x"]): junk(depth + 1) for _ in range(rng.randint(0, 4))}

    for _ in range(500):
        body = junk()
        try:
            verdict = simulate_plan(body, ON)
        except PlanRequestError:
            continue
        assert verdict["verdict"] in ("accepted", "rejected") and verdict["executable"] is False


# --- configuration and switch ---------------------------------------------------------------------------------------------------------


def test_the_policy_is_off_by_default_and_read_from_the_configuration_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYDRA_UMC_SEMANTIC_PLANNER_CONFIG", raising=False)
    assert load_simulation_policy().enabled is False
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"plan_simulation": {"enabled": True, "max_steps": 5}}), encoding="utf-8")
    policy = load_simulation_policy(cfg)
    assert policy.enabled is True and policy.max_steps == 5
    cfg.write_text(json.dumps({"recovery": {"out_of_range_action": "ABORT"}}), encoding="utf-8")
    assert load_simulation_policy(cfg).enabled is False


@pytest.mark.parametrize("section", [{"enabled": "yes"}, {"max_steps": 0}, {"max_steps": True}, {"speed_mm_s": -1}, {"default_step_s": "1"}, {"bogus": 1}, 3])
def test_a_bad_configuration_is_refused(tmp_path: Path, section: object) -> None:
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"plan_simulation": section}), encoding="utf-8")
    with pytest.raises(SimulationConfigError):
        load_simulation_policy(cfg)


def test_the_shipped_configuration_file_keeps_the_switch_off() -> None:
    shipped = Path(__file__).resolve().parents[1] / "configs" / "semantic-planner.json"
    assert load_simulation_policy(shipped).enabled is False


def test_serve_refuses_a_bad_plan_simulation_section(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"plan_simulation": {"max_steps": -1}}), encoding="utf-8")
    assert main(["serve", "--config", str(cfg), "--port", "0"]) == 2
    assert "plan_simulation.max_steps" in capsys.readouterr().err


# --- HTTP -----------------------------------------------------------------------------------------------------------------------------


def _server(simulation: SimulationPolicy | None) -> tuple[SemanticPlannerServer, str]:
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", simulation=simulation)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_http_route_is_404_when_off_and_answers_when_on() -> None:
    body = {"steps": [step("WAIT", params={}, duration_s=2)]}
    for off in (None, SimulationPolicy(enabled=False)):
        server, base = _server(off)
        try:
            assert _post(f"{base}/plan/simulate", body) == (404, {"error": "not found"})
        finally:
            server.shutdown()
            server.server_close()
    server, base = _server(ON)
    try:
        status, verdict = _post(f"{base}/plan/simulate", body)
        assert status == 200 and verdict["verdict"] == "accepted" and verdict["makespan_ms"] == 2000
        status, error = _post(f"{base}/plan/simulate", {"steps": "no"})
        assert status == 400 and "steps" in error["error"]
        status, error = _raw_post(f"{base}/plan/simulate", b"[1]")
        assert status == 400
        # the other routes answer as before
        assert _post(f"{base}/decompose", {"goal": "assemble the housing"})[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_http_unexpected_failure_is_a_refusal_not_a_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    from hydra_umc_semantic_planner import api

    def boom(*_: object) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(api, "simulate_plan", boom)
    server, base = _server(ON)
    try:
        status, body = _post(f"{base}/plan/simulate", {"steps": [step("WAIT")]})
        assert status == 500 and "verdict" not in body
    finally:
        server.shutdown()
        server.server_close()
