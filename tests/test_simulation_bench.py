# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_simulation_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Simulation bench: the real safety gate, goal decomposition and failure memory against a simulated safety service and a simulated stream of failures.

The safety service is a small HTTP server that answers `GET /state` the way the real one does, signed with the shared key, and that a scenario can make go wrong
on purpose: old verdicts, forged ones, replays, another state, garbage, redirects, answers that are too large, a service that is not there. The gate under test is
the real one, with its real HTTP fetch. The goals are drawn from a fixed seed. Nothing here says how the real safety service behaves in a cell: that needs a cell."""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hydra_umc_semantic_planner.decompose import MAX_GOAL_CHARS, decompose_goal
from hydra_umc_semantic_planner.failure_memory import FailureMemory, FailureMemoryPolicy
from hydra_umc_semantic_planner.recovery import ESCALATE_TO_OPERATOR, FailureContext
from hydra_umc_semantic_planner.safety_gate import DOMAIN, HMAC, MAX_RESPONSE_BYTES, READY, SafetyGate, SafetyGatePolicy

SEED = 20260101
KEY = "k" * 40
NOW_MS = 1_800_000_000_000


def _stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _signed(state: str, counter: int, *, at_ms: int = NOW_MS, key: str = KEY, key_id: str = "cell-1") -> dict:
    sdk_state = {"state": state, "timestamp_utc": _stamp(at_ms)}
    body = {"state": sdk_state, "counter": counter, "key_id": key_id}
    message = DOMAIN + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    signature = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {"sdkSafetyState": sdk_state, "sdkSafetyStateSignature": {"alg": HMAC, "counter": counter, "key_id": key_id, "sig": signature}}


class SafetyStandIn(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.respond: Callable[[], tuple[int, bytes, dict[str, str]]] = lambda: (200, json.dumps(_signed(READY, 1)).encode(), {})
        self.tokens: list[str | None] = []
        self.paths: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    server: SafetyStandIn

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.server.tokens.append(self.headers.get("Authorization"))
        self.server.paths.append(self.path)
        status, body, headers = self.server.respond()
        try:
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass


@contextmanager
def _service() -> Iterator[tuple[SafetyStandIn, str]]:
    server = SafetyStandIn()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _gate(url: str, *, token: str = "", clock: int = NOW_MS, **over) -> SafetyGate:
    policy = SafetyGatePolicy(enabled=True, url=url, key_file="key", timeout_s=2.0, max_age_ms=2000, **over)
    return SafetyGate(policy, key=KEY.encode(), token=token, clock_ms=lambda: clock)


def _answer(payload: object, status: int = 200, headers: dict[str, str] | None = None) -> Callable[[], tuple[int, bytes, dict[str, str]]]:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return lambda: (status, body, headers or {})


def test_a_fresh_signed_ready_verdict_over_real_http_releases_and_carries_the_token() -> None:
    with _service() as (server, url):
        server.respond = _answer(_signed(READY, 7))
        result = _gate(url, token="secret-token").check()
        assert result.allowed and result.state == READY and result.reason == ""
        assert server.tokens == ["Bearer secret-token"] and server.paths == ["/state"]


@pytest.mark.parametrize("state", ["WARNING", "INHIBITED", "SAFE_STOP", "FAULT", "UNKNOWN", ""])
def test_every_state_but_ready_keeps_the_plan_in_and_says_which(state: str) -> None:
    with _service() as (server, url):
        server.respond = _answer(_signed(state, 3))
        result = _gate(url).check()
        assert not result.allowed and (state in result.reason or state == "")


def test_a_verdict_that_is_too_old_or_from_the_future_is_refused() -> None:
    with _service() as (server, url):
        server.respond = _answer(_signed(READY, 2, at_ms=NOW_MS - 5000))
        assert "old" in _gate(url).check().reason
        server.respond = _answer(_signed(READY, 3, at_ms=NOW_MS + 60_000))
        assert not _gate(url).check().allowed
        server.respond = _answer(_signed(READY, 4, at_ms=NOW_MS - 1500))
        assert _gate(url).check().allowed  # inside the limit


def test_forged_and_unsigned_verdicts_are_refused() -> None:
    with _service() as (server, url):
        server.respond = _answer(_signed(READY, 1, key="x" * 40))
        assert _gate(url).check().reason == "the signature does not match"
        unsigned = _signed(READY, 1)
        del unsigned["sdkSafetyStateSignature"]
        server.respond = _answer(unsigned)
        assert _gate(url).check().reason == "the verdict is not signed"
        tampered = _signed("WARNING", 1)
        tampered["sdkSafetyState"]["state"] = READY  # the state was changed after signing
        server.respond = _answer(tampered)
        assert _gate(url).check().reason == "the signature does not match"
        server.respond = _answer(_signed(READY, 1, key_id="other"))
        assert _gate(url, key_id="cell-1").check().reason == "the signature was made with another key id"


def test_a_replayed_older_verdict_is_refused_after_a_newer_one_was_seen() -> None:
    with _service() as (server, url):
        gate = _gate(url)
        server.respond = _answer(_signed(READY, 10))
        assert gate.check().allowed
        server.respond = _answer(_signed(READY, 9))
        assert "replay" in gate.check().reason
        server.respond = _answer(_signed(READY, 11))
        assert gate.check().allowed


def test_a_service_that_is_not_there_or_answers_garbage_is_a_refusal_never_an_exception() -> None:
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{holder.getsockname()[1]}"
    assert _gate(dead).check().reason == "the safety service did not answer"
    with _service() as (server, url):
        for response in (_answer(b"not json"), _answer(b"[]"), _answer({"sdkSafetyState": "READY"}), _answer({}), _answer({"sdkSafetyState": {"state": READY}}),
                         _answer({"x": 1}, status=500), _answer(b"", status=204)):
            server.respond = response
            result = _gate(url).check()
            assert not result.allowed and result.reason


def test_an_answer_over_the_limit_and_a_redirect_are_refused() -> None:
    with _service() as (server, url):
        server.respond = _answer(b"{" + b" " * (MAX_RESPONSE_BYTES + 10) + b"}")
        assert not _gate(url).check().allowed
        server.respond = _answer(b"", status=302, headers={"Location": url + "/elsewhere"})
        assert not _gate(url).check().allowed
        assert server.paths == ["/state", "/state"]  # the redirect was not followed


def test_the_signature_can_be_switched_off_but_the_age_still_counts() -> None:
    with _service() as (server, url):
        unsigned = _signed(READY, 1)
        del unsigned["sdkSafetyStateSignature"]
        server.respond = _answer(unsigned)
        assert _gate(url, require_signature=False).check().allowed
        unsigned_old = _signed(READY, 1, at_ms=NOW_MS - 10_000)
        del unsigned_old["sdkSafetyStateSignature"]
        server.respond = _answer(unsigned_old)
        assert not _gate(url, require_signature=False).check().allowed


def test_a_stream_of_verdicts_from_a_cell_that_trips_and_recovers_releases_only_while_ready() -> None:
    rng = random.Random(SEED)
    states = [rng.choice([READY, READY, READY, "WARNING", "SAFE_STOP", "INHIBITED"]) for _ in range(40)]
    with _service() as (server, url):
        gate = _gate(url)
        released = []
        for counter, state in enumerate(states, start=1):
            server.respond = _answer(_signed(state, counter))
            released.append(gate.check().allowed)
    assert released == [state == READY for state in states]


# ----------------------------------------------------------------------------------------------------------------------------- the goals
def _goal(rng: random.Random) -> str:
    verbs = ["pick the {o} and place it on the shelf", "assemble the {o}", "inspect the {o}", "please inspect the {o} carefully", "pick up the {o} then place it at the bench"]
    return rng.choice(verbs).format(o=rng.choice(["bracket", "housing", "pcb-3", "lid", "motor_a"]))


def test_every_goal_that_is_understood_becomes_a_plan_of_catalogue_steps_only_and_the_same_goal_the_same_plan() -> None:
    rng = random.Random(SEED)
    for _ in range(60):
        goal = _goal(rng)
        plan = decompose_goal(goal)
        assert plan is not None, goal
        assert plan == decompose_goal(goal)
        assert len(plan.steps) in (2, 4)


@pytest.mark.parametrize("negation", ["do not", "never", "don't", "without", "cancel", "stop", "nunca", "evita", "sin"])
def test_a_goal_that_forbids_or_cancels_is_never_turned_into_a_plan(negation: str) -> None:
    rng = random.Random(SEED)
    for _ in range(10):
        assert decompose_goal(f"{negation} {_goal(rng)}") is None


def test_goals_that_say_nothing_or_too_much_are_an_honest_miss() -> None:
    assert decompose_goal("") is None and decompose_goal("   ") is None
    assert decompose_goal("make me a coffee") is None
    assert decompose_goal("inspect it") is None
    assert decompose_goal("inspect " + "x" * MAX_GOAL_CHARS) is None
    assert decompose_goal("assemble the lid and inspect the lid") is None  # two templates: ambiguous, refused


# ------------------------------------------------------------------------------------------------------------------------ the failure memory
class _Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def test_a_component_that_keeps_failing_the_same_recovery_is_handed_to_a_person_and_a_success_gives_the_default_back() -> None:
    clock = _Clock()
    memory = FailureMemory(FailureMemoryPolicy(enabled=True, min_failures=3), clock)
    failure = FailureContext("gripper-1", "TIMEOUT")
    first = memory.propose(failure)
    assert first.action != ESCALATE_TO_OPERATOR
    for _ in range(3):
        memory.record("gripper-1", "TIMEOUT", first.action, "FAILURE")
        clock.now += 1
    assert memory.propose(failure).action == ESCALATE_TO_OPERATOR
    assert memory.propose(FailureContext("gripper-2", "TIMEOUT")).action == first.action  # another component is untouched
    memory.record("gripper-1", "TIMEOUT", first.action, "SUCCESS")
    assert memory.propose(failure).action == first.action


def test_old_failures_are_forgotten_and_the_memory_is_bounded() -> None:
    clock = _Clock()
    memory = FailureMemory(FailureMemoryPolicy(enabled=True, max_entries=20, ttl_s=100, min_failures=3), clock)
    rng = random.Random(SEED)
    for _ in range(200):
        memory.record(f"arm-{rng.randrange(3)}", "TIMEOUT", "RETRY", rng.choice(["SUCCESS", "FAILURE"]))
        clock.now += 1
    assert memory.size() <= 20
    clock.now += 1000
    assert memory.size() == 0


def test_the_memory_kept_in_a_file_comes_back_after_a_restart_and_a_damaged_file_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    clock = _Clock()
    memory = FailureMemory(FailureMemoryPolicy(enabled=True, path=str(path)), clock)
    for _ in range(3):
        memory.record("gripper-1", "TIMEOUT", "RETRY", "FAILURE")
    again = FailureMemory(FailureMemoryPolicy(enabled=True, path=str(path)), clock)
    assert again.counts("gripper-1", "TIMEOUT", "RETRY") == (0, 3)
    path.write_text("{ this is not json", encoding="utf-8")
    assert FailureMemory(FailureMemoryPolicy(enabled=True, path=str(path)), clock).size() == 0
