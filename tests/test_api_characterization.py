# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_api_characterization.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Characterization of the HTTP surface as it behaves with no configuration: these fix what the service answers today, so adding a route
(the plan simulation, off by default) cannot change any of it."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from test_api import _get, _post, running_server


def _raw_post(url: str, data: bytes) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_stats_answers_the_role_only() -> None:
    with running_server() as base:
        status, body = _get(f"{base}/stats")
        assert status == 200
        assert body == {"role": "test role"}


def test_unknown_routes_are_404() -> None:
    with running_server() as base:
        assert _get(f"{base}/nothing") == (404, {"error": "not found"})
        assert _post(f"{base}/nothing", {}) == (404, {"error": "not found"})


def test_plan_simulate_does_not_exist_by_default() -> None:
    with running_server() as base:
        assert _post(f"{base}/plan/simulate", {"steps": []}) == (404, {"error": "not found"})
        assert _get(f"{base}/plan/simulate") == (404, {"error": "not found"})


def test_a_body_that_is_not_an_object_is_400_on_every_post_route() -> None:
    with running_server() as base:
        for route in ("/decompose", "/recover", "/release", "/nothing"):
            status, body = _raw_post(f"{base}{route}", b"[1, 2]")
            assert status == 400
            assert "must be an object" in body["error"]


def test_malformed_json_is_400() -> None:
    with running_server() as base:
        status, body = _raw_post(f"{base}/decompose", b"{not json")
        assert status == 400
        assert body["error"].startswith("malformed JSON body")


def test_decompose_requires_a_text_goal() -> None:
    with running_server() as base:
        assert _post(f"{base}/decompose", {}) == (400, {"error": "missing required field: 'goal'"})
        assert _post(f"{base}/decompose", {"goal": 3}) == (400, {"error": "goal must be text"})


def test_decompose_never_marks_a_plan_executable() -> None:
    with running_server() as base:
        status, body = _post(f"{base}/decompose", {"goal": "assemble the housing"})
        assert status == 200
        assert body["executable"] is False
        assert body["requires_approval"] is True
        assert body["operation"]["status"] == "received"


def test_recover_rejects_a_bad_attempt() -> None:
    with running_server() as base:
        status, _ = _post(f"{base}/recover", {"component": "gripper", "error_code": "TIMEOUT", "attempt": 0})
        assert status == 400


def test_release_with_a_wrong_fingerprint_releases_nothing() -> None:
    with running_server() as base:
        status, body = _post(f"{base}/release", {"goal": "assemble the housing", "approved_by": "ana", "plan_fingerprint": "0" * 64})
        assert status == 200
        assert body["released"] is False
