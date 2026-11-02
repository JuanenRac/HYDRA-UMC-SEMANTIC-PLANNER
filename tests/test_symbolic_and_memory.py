# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_symbolic_and_memory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The symbolic planner behind decompose_goal() and the bounded memory of recovery outcomes."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.decompose import decompose_goal
from hydra_umc_semantic_planner.failure_memory import (
    FailureMemory,
    FailureMemoryConfigError,
    FailureMemoryPolicy,
    OutcomeError,
    load_memory_policy,
)
from hydra_umc_semantic_planner.recovery import ESCALATE_TO_OPERATOR, RETRY, FailureContext, propose_recovery
from hydra_umc_semantic_planner.symbolic import (
    Problem,
    SymbolicConfigError,
    SymbolicPolicy,
    load_symbolic_policy,
    operators,
    problem_for,
    search,
    verify,
)

ON = SymbolicPolicy(enabled=True)
GOALS = ["assemble the housing", "pick up the cap and place it on tray", "inspect the weld", "pick the cap and place it in bin"]


@pytest.mark.parametrize("goal", GOALS)
def test_symbolic_plan_equals_the_rules_plan(goal: str) -> None:
    # the symbolic route reaches the same steps as the templates for every goal of the vocabulary, so enabling it changes nothing visible
    assert decompose_goal(goal, ON) == decompose_goal(goal)
    assert decompose_goal(goal, ON) is not None


def test_off_by_default_and_misses_stay_misses() -> None:
    assert SymbolicPolicy().enabled is False
    for goal in ("do not assemble the housing", "dance", "assemble it", "x" * 600):
        assert decompose_goal(goal, ON) is None


def test_search_is_bounded() -> None:
    problem = problem_for("pick_and_place", "cap", "bin", ON)
    assert problem is not None
    assert search(problem, SymbolicPolicy(enabled=True, max_plan_length=3)) is None
    assert search(problem, SymbolicPolicy(enabled=True, max_nodes=2)) is None
    assert len(search(problem, ON) or ()) == 4


def test_negated_precondition_forces_a_release_before_inspecting() -> None:
    init = frozenset({("at", "home"), ("holding", "cap")})
    problem = Problem(("cap",), ("home",), init, frozenset({("inspected", "cap")}))
    found = search(problem, ON)
    assert found is not None
    assert [op.step.primitive for op in found] == ["RELEASE", "INSPECT"]  # inspecting needs "not holding"
    assert search(Problem(("cap",), ("home",), init, frozenset({("inspected", "cap")})), SymbolicPolicy(enabled=True, max_plan_length=1)) is None


def test_verify_rejects_a_broken_or_incomplete_plan() -> None:
    problem = problem_for("inspect", "weld", None, ON)
    assert problem is not None
    plan = search(problem, ON)
    assert plan is not None and verify(problem, plan)
    assert not verify(problem, plan[::-1])
    assert not verify(problem, plan[:1])
    assert not verify(problem, operators(problem)[:0])


def test_pick_and_place_to_the_pickup_is_a_miss() -> None:
    assert decompose_goal("pick the cap and place it on pickup", ON) is None


def test_symbolic_config(tmp_path) -> None:
    assert load_symbolic_policy().enabled is False
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"symbolic_planner": {"enabled": True, "max_nodes": 10}}), encoding="utf-8")
    assert load_symbolic_policy(cfg).max_nodes == 10
    for bad in ({"enabled": "yes"}, {"max_nodes": 0}, {"nope": 1}, {"start_location": "a b"}, {"max_plan_length": 999}):
        cfg.write_text(json.dumps({"symbolic_planner": bad}), encoding="utf-8")
        with pytest.raises(SymbolicConfigError):
            load_symbolic_policy(cfg)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _memory(clock: Clock | None = None, **kwargs) -> FailureMemory:
    return FailureMemory(FailureMemoryPolicy(enabled=True, **kwargs), clock or Clock())


def test_memory_only_makes_recovery_more_cautious() -> None:
    memory = _memory()
    failure = FailureContext("gripper-1", "TIMEOUT")
    assert memory.propose(failure).action == RETRY
    for _ in range(3):
        memory.record("gripper-1", "TIMEOUT", "RETRY", "FAILURE")
    assert memory.propose(failure).action == ESCALATE_TO_OPERATOR
    assert memory.propose(FailureContext("gripper-2", "TIMEOUT")).action == RETRY  # another component is unaffected
    memory.record("gripper-1", "TIMEOUT", "RETRY", "SUCCESS")
    assert memory.propose(failure).action == RETRY  # one success is enough to keep the default
    # an escalation or an abort is never relaxed
    for _ in range(5):
        memory.record("arm", "ESTOP_ACTIVE", "ESCALATE_TO_OPERATOR", "SUCCESS")
    assert memory.propose(FailureContext("arm", "ESTOP_ACTIVE")).action == ESCALATE_TO_OPERATOR
    assert propose_recovery(FailureContext("arm", "OUT_OF_RANGE")).action == "ABORT"
    assert memory.propose(FailureContext("arm", "OUT_OF_RANGE")).action == "ABORT"


def test_memory_is_bounded_and_expires() -> None:
    clock = Clock()
    memory = _memory(clock, max_entries=3, ttl_s=100)
    for _ in range(10):
        memory.record("a", "TIMEOUT", "RETRY", "FAILURE")
    assert memory.size() == 3
    clock.now += 101
    assert memory.size() == 0
    assert memory.counts("a", "TIMEOUT", "RETRY") == (0, 0)


def test_memory_refuses_free_text_and_bad_outcomes() -> None:
    memory = _memory()
    for args in (("john doe", "TIMEOUT", "RETRY", "FAILURE"), ("a", "bad code", "RETRY", "FAILURE"), ("a", "TIMEOUT", "RETRY", "MAYBE"), ("", "TIMEOUT", "RETRY", "FAILURE")):
        with pytest.raises(OutcomeError):
            memory.record(*args)
    assert memory.size() == 0


def test_memory_persists_only_the_five_fields(tmp_path) -> None:
    path = tmp_path / "m.json"
    memory = FailureMemory(FailureMemoryPolicy(enabled=True, path=str(path)))
    memory.record("gripper-1", "TIMEOUT", "RETRY", "FAILURE")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored) == 1 and len(stored[0]) == 5
    again = FailureMemory(FailureMemoryPolicy(enabled=True, path=str(path)))
    assert again.counts("gripper-1", "TIMEOUT", "RETRY") == (0, 1)
    path.write_text("not json", encoding="utf-8")
    assert FailureMemory(FailureMemoryPolicy(enabled=True, path=str(path))).size() == 0


def test_memory_config(tmp_path) -> None:
    assert load_memory_policy().enabled is False
    cfg = tmp_path / "c.json"
    for bad in ({"enabled": 1}, {"max_entries": 0}, {"ttl_s": True}, {"max_entries": 10**6}, {"other": 1}):
        cfg.write_text(json.dumps({"failure_memory": bad}), encoding="utf-8")
        with pytest.raises(FailureMemoryConfigError):
            load_memory_policy(cfg)


@contextmanager
def _serve(**kwargs):
    server = SemanticPlannerServer(("127.0.0.1", 0), "test", **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _post(base: str, path: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_outcome_route_is_absent_while_the_memory_is_off() -> None:
    with _serve() as base:
        status, _ = _post(base, "/recover/outcome", {"component": "a", "error_code": "TIMEOUT", "action": "RETRY", "outcome": "FAILURE"})
        assert status == 404


def test_http_memory_changes_the_next_recover() -> None:
    with _serve(memory=_memory()) as base:
        body = {"component": "gripper-1", "error_code": "TIMEOUT"}
        assert _post(base, "/recover", body)[1]["action"] == RETRY
        for _ in range(3):
            status, answer = _post(base, "/recover/outcome", {**body, "action": "RETRY", "outcome": "FAILURE"})
            assert status == 200 and answer["recorded"] is True
        assert _post(base, "/recover", body)[1]["action"] == ESCALATE_TO_OPERATOR
        assert _post(base, "/recover/outcome", {**body, "action": "RETRY", "outcome": "MAYBE"})[0] == 400
        assert _post(base, "/recover/outcome", {**body, "action": "RETRY"})[0] == 400


def test_http_symbolic_still_only_proposes() -> None:
    with _serve(symbolic=ON) as base:
        status, answer = _post(base, "/decompose", {"goal": "assemble the housing"})
        assert status == 200 and answer["matched"] is True
        assert answer["executable"] is False and answer["requires_approval"] is True
        assert [s["primitive"] for s in answer["steps"]] == ["MOVE_TO", "GRIP", "MOVE_TO", "RELEASE"]
        # a release still needs the person's approval of this very fingerprint
        released = _post(base, "/release", {"goal": "assemble the housing", "approved_by": "ana", "plan_fingerprint": "0" * 64})
        assert released[1]["released"] is False
