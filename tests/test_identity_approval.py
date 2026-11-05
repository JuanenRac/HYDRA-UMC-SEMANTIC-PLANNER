# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_identity_approval.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The approval of a plan is made by a person who is signed in with the common identity: the token of HYDRA-UMC-SERVER of an operator, and approved_by is that person."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from hydra_umc_semantic_planner import server_identity
from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.approval_policy import ApprovalConfigError, ApprovalPolicy, load_approval_policy

KEY = b"a-signing-key-of-the-server-0123456789"


@contextmanager
def _server(*, require_identity: bool, key: bytes | None = KEY):
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", require_identity=require_identity)
    server.identity_key = key
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post(url: str, body: dict, bearer: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _release_body(base: str, bearer: str | None, approved_by: str) -> dict:
    fingerprint = _post(f"{base}/decompose", {"goal": "inspect the weld"}, bearer)[1]["fingerprint"]
    return {"goal": "inspect the weld", "approved_by": approved_by, "plan_fingerprint": fingerprint}


def test_the_policy_asks_for_the_identity_by_default_and_can_be_relaxed(tmp_path: Path) -> None:
    assert ApprovalPolicy().require_identity is True
    path = tmp_path / "planner.json"
    path.write_text(json.dumps({"plan_approval": {"require_identity": False}}), encoding="utf-8")
    assert load_approval_policy(path).require_identity is False
    path.write_text(json.dumps({"plan_approval": {"require_identity": "no"}}), encoding="utf-8")
    with pytest.raises(ApprovalConfigError):
        load_approval_policy(path)


def test_an_operator_releases_in_their_own_name() -> None:
    with _server(require_identity=True) as base:
        operator = server_identity.sign_token(KEY, username="ana", role="operator")
        status, answer = _post(f"{base}/release", _release_body(base, operator, "ana"), operator)
        assert status == 200 and answer["released"] is True


def test_the_body_cannot_name_somebody_else() -> None:
    with _server(require_identity=True) as base:
        operator = server_identity.sign_token(KEY, username="ana", role="operator")
        status, answer = _post(f"{base}/release", _release_body(base, operator, "boss"), operator)
        assert status == 200 and answer["released"] is False and "not the person who is signed in" in answer["reason"]


def test_a_viewer_or_no_token_releases_nothing() -> None:
    with _server(require_identity=True) as base:
        viewer = server_identity.sign_token(KEY, username="vic", role="viewer")
        assert _post(f"{base}/release", {"goal": "x", "approved_by": "vic", "plan_fingerprint": "f" * 64}, viewer)[0] == 401
        assert _post(f"{base}/release", {"goal": "x", "approved_by": "vic", "plan_fingerprint": "f" * 64})[0] == 401


def test_without_the_identity_key_every_release_is_refused_with_the_reason() -> None:
    with _server(require_identity=True, key=None) as base:
        body = _release_body(base, None, "ana")
        status, answer = _post(f"{base}/release", body)
        assert status == 200 and answer["released"] is False and "no identity key" in answer["reason"]


def test_relaxed_it_is_the_words_of_the_request_as_before() -> None:
    with _server(require_identity=False, key=None) as base:
        status, answer = _post(f"{base}/release", _release_body(base, None, "ana"))
        assert status == 200 and answer["released"] is True
