# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_signed_approval.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""A signed approval is tied to a plan, a robot and a time window; without a valid one nothing is released."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from hydra_umc_semantic_planner import main as main_module
from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.approval_signing import (
    MAX_VALIDITY_MS,
    ApprovalKeyError,
    load_key,
    sign_approval,
    verify_approval,
)

KEY = b"k" * 32
FP = "a" * 64
NOW = 1_700_000_000_000


def _signed(**overrides):
    base = sign_approval(KEY, FP, "ana", "robot-1", validity_ms=60_000, now_ms=NOW)
    return replace(base, **overrides)


def _verify(approval, **overrides):
    arguments = {"expected_fingerprint": FP, "expected_robot_id": "robot-1", "now_ms": NOW + 1000}
    arguments.update(overrides)
    return verify_approval(KEY, approval, **arguments)


def test_a_fresh_signed_approval_verifies() -> None:
    assert _verify(_signed()) == (True, "")


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"signature": ""}, "not signed"),
        ({"signature": "0" * 64}, "does not match"),
        ({"approved_by": "mallory"}, "does not match"),
        ({"robot_id": "robot-2"}, "does not match"),
        ({"plan_fingerprint": "b" * 64}, "does not match"),
        ({"expires_at_ms": NOW + 10_000_000}, "does not match"),
    ],
)
def test_any_change_to_the_approval_breaks_the_signature(change: dict, text: str) -> None:
    ok, why = _verify(_signed(**change))
    assert not ok and text in why


def test_an_expired_or_future_approval_is_refused() -> None:
    assert "expired" in _verify(_signed(), now_ms=NOW + 61_000)[1]
    assert "future" in _verify(_signed(), now_ms=NOW - 60_000)[1]


def test_it_is_for_one_plan_and_one_robot() -> None:
    assert "different plan" in _verify(_signed(), expected_fingerprint="c" * 64)[1]
    assert "different robot" in _verify(_signed(), expected_robot_id="robot-2")[1]
    assert "different robot" in _verify(_signed(), expected_robot_id="")[1]


def test_the_validity_has_a_ceiling_and_a_signer_cannot_get_around_it() -> None:
    with pytest.raises(ValueError):
        sign_approval(KEY, FP, "ana", "robot-1", validity_ms=MAX_VALIDITY_MS + 1)
    with pytest.raises(ValueError):
        sign_approval(KEY, FP, "ana", "", now_ms=NOW)
    # someone with the key who writes a too-long window is still refused by the verifier
    from hydra_umc_semantic_planner.approval_signing import SignedApproval, _message
    import hashlib
    import hmac

    long_window = SignedApproval(FP, "ana", "robot-1", NOW, NOW + MAX_VALIDITY_MS + 1)
    signature = hmac.new(KEY, _message(long_window), hashlib.sha256).hexdigest()
    ok, why = _verify(replace(long_window, signature=signature))
    assert not ok and "window" in why


def test_the_key_file_must_exist_and_be_long_enough(tmp_path: Path) -> None:
    with pytest.raises(ApprovalKeyError):
        load_key(tmp_path / "missing")
    short = tmp_path / "short"
    short.write_bytes(b"abc")
    with pytest.raises(ApprovalKeyError):
        load_key(short)


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


@contextmanager
def _server(**kwargs):
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_with_a_key_the_words_of_the_request_are_not_enough() -> None:
    with _server(approval_key=KEY, robot_id="robot-1") as base:
        fingerprint = _post(f"{base}/decompose", {"goal": "inspect the weld"})["fingerprint"]
        plain = {"goal": "inspect the weld", "approved_by": "ana", "plan_fingerprint": fingerprint}
        assert _post(f"{base}/release", plain)["released"] is False
        signed = sign_approval(KEY, fingerprint, "ana", "robot-1")
        full = {**plain, "robot_id": "robot-1", "issued_at_ms": signed.issued_at_ms,
                "expires_at_ms": signed.expires_at_ms, "signature": signed.signature}
        assert _post(f"{base}/release", full)["released"] is True
        assert _post(f"{base}/release", {**full, "robot_id": "robot-2"})["released"] is False
        assert _post(f"{base}/release", {**full, "signature": "0" * 64})["released"] is False
        assert _post(f"{base}/release", {**full, "expires_at_ms": "soon"})["released"] is False
        old = sign_approval(KEY, fingerprint, "ana", "robot-1", validity_ms=1000, now_ms=1_000_000)
        stale = {**full, "issued_at_ms": old.issued_at_ms, "expires_at_ms": old.expires_at_ms, "signature": old.signature}
        assert "expired" in _post(f"{base}/release", stale)["reason"]


def test_without_a_key_nothing_changes() -> None:
    with _server() as base:
        fingerprint = _post(f"{base}/decompose", {"goal": "inspect the weld"})["fingerprint"]
        body = {"goal": "inspect the weld", "approved_by": "ana", "plan_fingerprint": fingerprint}
        assert _post(f"{base}/release", body)["released"] is True


def test_the_command_signs_and_the_service_needs_a_robot_with_a_key(tmp_path: Path, capsys) -> None:
    key_file = tmp_path / "approval.key"
    key_file.write_bytes(KEY)
    code = main_module.main(["sign-approval", "inspect the weld", "--approved-by", "ana", "--robot-id", "robot-1", "--key-file", str(key_file)])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and len(printed["signature"]) == 64 and printed["robot_id"] == "robot-1"
    assert main_module.main(["serve", "--approval-key-file", str(key_file)]) == 2
    assert main_module.main(["serve", "--approval-key-file", str(tmp_path / "none"), "--robot-id", "r"]) == 2
