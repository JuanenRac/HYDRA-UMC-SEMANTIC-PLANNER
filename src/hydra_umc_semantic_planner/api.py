# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/api.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Plain JSON/HTTP surface (stdlib http.server) - same convention as this
family's other api.py files. POST /decompose and POST /recover reach the
exact same decompose_goal()/validate_plan()/propose_recovery() functions
the CLI's own `decompose`/`recover` subcommands already run."""
from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .decompose import decompose_goal
from .recovery import FailureContext, propose_recovery
from .validation import validate_plan


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    def default(o: object) -> object:
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        return str(o)
    body = json.dumps(payload, default=default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _write_error(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    _write_json(handler, status, {"error": message})


MAX_BODY_BYTES = 1024 * 1024
# How much of an oversized body this drains before responding - a real,
# reproducible race already found and fixed for this exact class of gap
# in HYDRA-UMC-ANOMALY-DETECTOR (ecosystem-wide software-improvements
# audit): rejecting an over-limit request without reading any of it left
# the client's own send() still in flight when the handler closed the
# connection, so on a body bigger than the OS socket buffer the client
# saw a raw ConnectionAbortedError instead of this clean 400. Draining up
# to this many bytes lets the client finish sending before the response
# goes out, without ever holding more than one bounded read in memory.
DRAIN_CAP_BYTES = MAX_BODY_BYTES * 16


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    try:
        length = int(handler.headers.get("Content-Length", 0))
    except ValueError as error:
        raise ValueError("Content-Length must be an integer") from error
    if length < 0 or length > MAX_BODY_BYTES:
        if 0 <= length <= DRAIN_CAP_BYTES:
            handler.rfile.read(length)
        raise ValueError(f"request body must contain 0-{MAX_BODY_BYTES} bytes")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw)


class Handler(BaseHTTPRequestHandler):
    server: "SemanticPlannerServer"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # quiet by default, same reasoning as this family's other api.py files

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/stats":
            _write_json(self, 200, {"role": self.server.role})
        else:
            _write_error(self, 404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = _read_json_body(self)
        except (json.JSONDecodeError, ValueError) as e:
            _write_error(self, 400, f"malformed JSON body: {e}")
            return
        if path == "/decompose":
            self._handle_decompose(body)
        elif path == "/recover":
            self._handle_recover(body)
        else:
            _write_error(self, 404, "not found")

    def _handle_decompose(self, body: dict) -> None:
        try:
            goal = str(body["goal"])
        except KeyError as e:
            _write_error(self, 400, f"missing required field: {e}")
            return
        plan = decompose_goal(goal)
        if plan is None:
            _write_json(self, 200, {"matched": False, "goal": goal, "steps": [], "issues": []})
            return
        issues = validate_plan(plan)
        _write_json(self, 200, {
            "matched": True,
            "goal": plan.goal,
            "steps": [asdict(s) for s in plan.steps],
            "issues": [asdict(i) for i in issues],
            "valid": not issues,
        })

    def _handle_recover(self, body: dict) -> None:
        try:
            failure = FailureContext(
                component=str(body["component"]),
                error_code=str(body["error_code"]),
                detail=str(body.get("detail", "")),
            )
        except KeyError as e:
            _write_error(self, 400, f"missing required field: {e}")
            return
        strategy = propose_recovery(failure)
        _write_json(self, 200, asdict(strategy))


class SemanticPlannerServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], role: str) -> None:
        super().__init__(address, Handler)
        self.role = role
