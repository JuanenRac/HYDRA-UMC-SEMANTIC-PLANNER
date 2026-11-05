# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_settings_route.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""An administrator reads and changes the identity switch of the approval while the planner runs, with a confirmation, and the change reaches the configuration file."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from hydra_umc_semantic_planner import server_identity
from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.approval_policy import load_approval_policy

KEY = b"a-signing-key-of-the-server-0123456789"


@contextmanager
def _server(settings_file: Path | None, *, require_identity: bool = True, key: bytes | None = KEY):
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", require_identity=require_identity, settings_file=str(settings_file) if settings_file else None)
    server.identity_key = key
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _call(url: str, body: dict | None, bearer: str | None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "planner.json"
    path.write_text(json.dumps({"plan_approval": {"require_signed": False, "require_identity": True}, "other": {"kept": 1}}), encoding="utf-8")
    return path


def test_anyone_signed_in_reads_the_switch(tmp_path: Path) -> None:
    with _server(_config(tmp_path)) as (_, base):
        viewer = server_identity.sign_token(KEY, username="vic", role="viewer")
        assert _call(f"{base}/settings", None, viewer) == (200, {"requireIdentity": True, "verifiesTokens": True, "persisted": True})
        assert _call(f"{base}/settings", None, None)[0] == 401


def test_only_an_administrator_changes_it(tmp_path: Path) -> None:
    with _server(_config(tmp_path)) as (server, base):
        operator = server_identity.sign_token(KEY, username="ana", role="operator")
        assert _call(f"{base}/settings", {"requireIdentity": False, "confirm": True}, operator)[0] == 403
        viewer = server_identity.sign_token(KEY, username="vic", role="viewer")
        assert _call(f"{base}/settings", {"requireIdentity": False, "confirm": True}, viewer)[0] == 401
        assert server.require_identity is True


def test_relaxing_needs_a_confirmation_and_is_written_to_the_file(tmp_path: Path) -> None:
    path = _config(tmp_path)
    with _server(path) as (server, base):
        admin = server_identity.sign_token(KEY, username="root", role="admin")
        status, answer = _call(f"{base}/settings", {"requireIdentity": False}, admin)
        assert status == 400 and answer["code"] == "CONFIRMATION_REQUIRED" and server.require_identity is True
        status, answer = _call(f"{base}/settings", {"requireIdentity": False, "confirm": True}, admin)
        assert status == 200 and answer["requireIdentity"] is False and answer["changed"] is True
        assert server.require_identity is False
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["plan_approval"]["require_identity"] is False and saved["other"] == {"kept": 1} and saved["plan_approval"]["require_signed"] is False
        assert load_approval_policy(path).require_identity is False
        # tightening again needs no confirmation
        status, answer = _call(f"{base}/settings", {"requireIdentity": True}, admin)
        assert status == 200 and answer["requireIdentity"] is True and load_approval_policy(path).require_identity is True


def test_a_malformed_body_or_an_unwritable_file_changes_nothing(tmp_path: Path) -> None:
    with _server(_config(tmp_path)) as (server, base):
        admin = server_identity.sign_token(KEY, username="root", role="admin")
        assert _call(f"{base}/settings", {"requireIdentity": "no"}, admin)[0] == 400
        assert _call(f"{base}/settings", {"requireIdentity": False, "confirm": True, "extra": 1}, admin)[0] == 400
        assert server.require_identity is True
    with _server(tmp_path / "missing.json") as (server, base):
        admin = server_identity.sign_token(KEY, username="root", role="admin")
        status, answer = _call(f"{base}/settings", {"requireIdentity": False, "confirm": True}, admin)
        assert status == 409 and answer["code"] == "SETTING_REFUSED" and server.require_identity is True


def test_without_the_identity_key_the_switch_cannot_be_changed(tmp_path: Path) -> None:
    with _server(_config(tmp_path), key=None) as (server, base):
        assert _call(f"{base}/settings", {"requireIdentity": False, "confirm": True}, None)[0] == 403
        assert server.require_identity is True
