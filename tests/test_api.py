# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_api.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real end-to-end HTTP tests: a real SemanticPlannerServer (ThreadingHTTPServer)
hit with real urllib requests - same convention as this family's other
test_api.py files, reusing this repo's own tests/test_cli.py fixtures."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

from hydra_umc_semantic_planner.api import SemanticPlannerServer


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(url: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@contextmanager
def running_server() -> Iterator[str]:
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_decompose_real_goal() -> None:
    with running_server() as base:
        status, body = _post(f"{base}/decompose", {"goal": "assemble the housing"})
        assert status == 200
        assert body["matched"] is True
        primitives = [s["primitive"] for s in body["steps"]]
        assert "MOVE_TO" in primitives
        assert "GRIP" in primitives
        assert "RELEASE" in primitives
        assert body["valid"] is True


def test_decompose_unmatched_goal() -> None:
    with running_server() as base:
        status, body = _post(f"{base}/decompose", {"goal": "write a poem"})
        assert status == 200
        assert body["matched"] is False
        assert body["steps"] == []


def test_decompose_missing_field() -> None:
    with running_server() as base:
        status, body = _post(f"{base}/decompose", {})
        assert status == 400


def test_recover_known_error_code() -> None:
    # propose_recovery()'s own reason is a fixed lookup string per error
    # code (recovery.py's own _STRATEGIES table) - it never echoes back
    # 'detail', the same way the CLI's "Recovery: ..." print line doesn't
    # either (only its separate "Failure: ..." line shows detail, for a
    # human reading stdout - this API has no reason to echo an unused
    # input back).
    with running_server() as base:
        status, body = _post(f"{base}/recover", {
            "component": "gripper", "error_code": "GRIP_LOST_SEAL", "detail": "vacuum gripper lost seal",
        })
        assert status == 200
        assert body["action"] == "INCREASE_PRESSURE"
        assert "vacuum seal lost" in body["reason"]


def test_recover_missing_field() -> None:
    with running_server() as base:
        status, body = _post(f"{base}/recover", {"component": "gripper"})
        assert status == 400


def test_stats() -> None:
    with running_server() as base:
        status, body = _get(f"{base}/stats")
        assert status == 200
        assert body == {"role": "test role"}


def test_not_found() -> None:
    with running_server() as base:
        status, body = _get(f"{base}/nope")
        assert status == 404
