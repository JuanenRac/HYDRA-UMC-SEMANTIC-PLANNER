# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_safety_gate_and_voice.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The safety gate before a release (fail closed, a real HTTP stand-in for the safety service) and the route that turns a voice intent into a proposal."""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hydra_umc_semantic_planner import main as main_module
from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.safety_gate import (
    DOMAIN,
    SafetyGate,
    SafetyGateConfigError,
    SafetyGatePolicy,
    load_gate_policy,
)
from hydra_umc_semantic_planner.voice_intents import (
    VoiceIntentConfigError,
    VoiceIntentPolicy,
    goal_for_intent,
    load_voice_policy,
)

KEY = b"s" * 32
GOAL = "assemble the housing"


def _message(state: dict, counter: int, key_id: str) -> bytes:
    body = {"state": state, "counter": counter, "key_id": key_id}
    return DOMAIN + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class FakeSafety(ThreadingHTTPServer):
    """What HYDRA-UMC-SAFETY-ZONES answers on GET /state, with a verdict the test can change."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _SafetyHandler)
        self.state = "READY"
        self.counter = 1000
        self.signed = True
        self.timestamp: str | None = None
        self.status = 200
        self.requests = 0
        self.key = KEY

    def verdict(self) -> dict:
        sdk = {
            "schema_version": "1.0",
            "state": self.state,
            "source": "hydra-umc-safety-zones",
            "timestamp_utc": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }
        out: dict = {"sdkSafetyState": sdk, "reason": "test"}
        if self.signed:
            sig = hmac.new(self.key, _message(sdk, self.counter, "k1"), hashlib.sha256).hexdigest()
            out["sdkSafetyStateSignature"] = {"alg": "HMAC-SHA256", "key_id": "k1", "counter": self.counter, "sig": sig}
        return out


class _SafetyHandler(BaseHTTPRequestHandler):
    server: FakeSafety

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.server.requests += 1
        body = json.dumps(self.server.verdict()).encode()
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def fake_safety() -> Iterator[tuple[str, FakeSafety]]:
    server = FakeSafety()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _gate(url: str, **overrides: object) -> SafetyGate:
    policy = SafetyGatePolicy(enabled=True, url=url, key_file="unused", **overrides)  # type: ignore[arg-type]
    return SafetyGate(policy, key=KEY)


def test_ready_signed_fresh_verdict_allows() -> None:
    with fake_safety() as (url, _):
        assert _gate(url).check().allowed is True


@pytest.mark.parametrize("state", ["WARNING", "INHIBITED", "SAFE_STOP", "FAULT", "ready", "whatever"])
def test_any_state_but_ready_refuses(state: str) -> None:
    with fake_safety() as (url, server):
        server.state = state
        result = _gate(url).check()
        assert result.allowed is False


def test_unreachable_service_refuses() -> None:
    result = _gate("http://127.0.0.1:1", timeout_s=0.5).check()
    assert (result.allowed, result.reason) == (False, "the safety service did not answer")


def test_http_error_and_garbage_refuse() -> None:
    with fake_safety() as (url, server):
        server.status = 500
        assert _gate(url).check().allowed is False


def test_unsigned_forged_old_and_replayed_verdicts_refuse() -> None:
    with fake_safety() as (url, server):
        gate = _gate(url)
        server.signed = False
        assert "not signed" in gate.check().reason
        server.signed = True
        server.key = b"x" * 32
        assert "does not match" in gate.check().reason
        server.key = KEY
        server.timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        assert "old" in gate.check().reason
        server.timestamp = None
        assert gate.check().allowed is True
        server.counter = 5  # older than the one just seen
        assert "replay" in gate.check().reason


def test_signature_can_be_switched_off_but_age_still_counts() -> None:
    with fake_safety() as (url, server):
        gate = SafetyGate(SafetyGatePolicy(enabled=True, url=url, require_signature=False))
        server.signed = False
        assert gate.check().allowed is True
        server.timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        assert gate.check().allowed is False


def test_policy_validation_and_defaults(tmp_path: Path) -> None:
    assert SafetyGatePolicy().enabled is False
    assert SafetyGate.from_policy(SafetyGatePolicy()) is None
    with pytest.raises(SafetyGateConfigError):
        SafetyGatePolicy(enabled=True)  # signatures are required by default, so a key is needed
    with pytest.raises(SafetyGateConfigError):
        SafetyGatePolicy(url="ftp://x")
    with pytest.raises(SafetyGateConfigError):
        SafetyGatePolicy(max_age_ms=0)
    short = tmp_path / "short.key"
    short.write_text("abc", encoding="utf-8")
    with pytest.raises(SafetyGateConfigError):
        SafetyGate.from_policy(SafetyGatePolicy(enabled=True, key_file=str(short)))
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"safety_gate": {"enabled": False, "surprise": 1}}), encoding="utf-8")
    with pytest.raises(SafetyGateConfigError):
        load_gate_policy(str(cfg))


def test_gate_agrees_with_the_real_safety_service_signer() -> None:
    sibling = Path(__file__).resolve().parents[2] / "HYDRA-UMC-SAFETY-ZONES" / "src"
    if not sibling.is_dir():
        pytest.skip("HYDRA-UMC-SAFETY-ZONES is not next to this repository")
    sys.path.insert(0, str(sibling))
    try:
        from hydra_umc_safety_zones.signing import StateSigner  # noqa: PLC0415
    finally:
        sys.path.remove(str(sibling))
    signer = StateSigner(KEY, "k1")
    with fake_safety() as (url, server):
        sdk = server.verdict()["sdkSafetyState"]
        signature = signer.sign(sdk)
        gate = _gate(url)
        ok, why, _ = gate._verify(sdk, signature)  # noqa: SLF001
        assert (ok, why) == (True, "")


def _post(url: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


@contextmanager
def planner(**kwargs: object) -> Iterator[str]:
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", **kwargs)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _release(base: str) -> dict:
    _, proposal = _post(f"{base}/decompose", {"goal": GOAL})
    status, body = _post(f"{base}/release", {"goal": GOAL, "approved_by": "ana", "plan_fingerprint": proposal["fingerprint"]})
    assert status == 200
    return body


def test_release_without_a_gate_is_unchanged() -> None:
    with planner() as base:
        body = _release(base)
        assert body["released"] is True and "safety_gate" not in body


def test_release_follows_the_safety_state() -> None:
    with fake_safety() as (url, server), planner(safety_gate=_gate(url)) as base:
        body = _release(base)
        assert body["released"] is True and body["safety_gate"] == {"allowed": True, "state": "READY"}
        server.state = "SAFE_STOP"
        body = _release(base)
        assert body["released"] is False and body["reason"].startswith("safety gate:")
        server.shutdown()
        server.server_close()
        body = _release(base)
        assert body["released"] is False and "did not answer" in body["reason"]


def test_gate_is_not_asked_when_the_person_has_not_approved() -> None:
    with fake_safety() as (url, server), planner(safety_gate=_gate(url)) as base:
        status, body = _post(f"{base}/release", {"goal": GOAL, "approved_by": "ana", "plan_fingerprint": "0" * 64})
        assert status == 200 and body["released"] is False and server.requests == 0


def test_voice_intent_route_is_off_by_default() -> None:
    with planner() as base:
        assert _post(f"{base}/voice/intent", {"intent": {"name": "start_mission", "entities": {"mission_id": "m1"}}})[0] == 404


def test_voice_intent_becomes_a_proposal_never_an_order() -> None:
    policy = VoiceIntentPolicy(enabled=True, mission_goals={"housing-1": GOAL})
    with planner(voice=policy) as base:
        status, body = _post(f"{base}/voice/intent", {"intent": {"name": "start_mission", "entities": {"mission_id": "housing-1"}}})
        assert status == 200
        assert body["matched"] is True and body["source"] == "voice" and body["goal"] == GOAL
        assert body["executable"] is False and body["requires_approval"] is True
        # the proposal is released by the usual approval, not by the voice
        status, released = _post(f"{base}/release", {"goal": body["goal"], "approved_by": "ana", "plan_fingerprint": body["fingerprint"]})
        assert released["released"] is True


@pytest.mark.parametrize(
    "intent",
    [
        {"name": "stop", "entities": {}},
        {"name": "status", "entities": {"robot_id": "1"}},
        {"name": "go_home", "entities": {}},
        {"name": "start_mission", "entities": {}},
        {"name": "start_mission", "entities": {"mission_id": "unknown"}},
        {"name": "start_mission", "entities": {"mission_id": "../x"}},
        {"name": 5},
        "start_mission",
    ],
)
def test_voice_intents_that_are_not_catalogued_missions_are_a_miss(intent: object) -> None:
    policy = VoiceIntentPolicy(enabled=True, mission_goals={"housing-1": GOAL})
    goal, reason = goal_for_intent(intent, policy)
    assert goal is None and reason
    with planner(voice=policy) as base:
        status, body = _post(f"{base}/voice/intent", {"intent": intent})
        assert status == 200 and body["matched"] is False and body["steps"] == []


def test_voice_route_needs_an_intent_and_policy_is_validated(tmp_path: Path) -> None:
    with planner(voice=VoiceIntentPolicy(enabled=True)) as base:
        assert _post(f"{base}/voice/intent", {})[0] == 400
    with pytest.raises(VoiceIntentConfigError):
        VoiceIntentPolicy(mission_goals={"bad id": GOAL})
    with pytest.raises(VoiceIntentConfigError):
        VoiceIntentPolicy(mission_goals={"ok": ""})
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"voice_intents": {"enabled": True, "mission_goals": {"m1": GOAL}}}), encoding="utf-8")
    assert load_voice_policy(str(cfg)).mission_goals == {"m1": GOAL}


def test_serve_refuses_an_enabled_gate_without_a_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"safety_gate": {"enabled": True}}), encoding="utf-8")
    assert main_module._run_serve("127.0.0.1", 0, config=str(cfg)) == 2  # noqa: SLF001
    assert "key_file" in capsys.readouterr().err
