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

from .approval import PlanApproval, propose, release_for_execution
from .decompose import MAX_GOAL_CHARS, decompose_goal
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
# in HYDRA-UMC-ANOMALY-DETECTOR: rejecting an over-limit request without
# reading any of it left the client's own send() still in flight when the
# handler closed the
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
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        # valid JSON that is not an object (a list, a string, null, a number) used to reach
        # `body["goal"]` and raise a TypeError nothing caught: the handler thread died with
        # a traceback and the client got no response at all
        raise ValueError("the JSON body must be an object")
    return parsed


class Handler(BaseHTTPRequestHandler):
    server: "SemanticPlannerServer"

    # Seconds a client may stay silent on its connection before the server
    # drops it, so a client that connects and sends nothing cannot hold a
    # handler thread forever. Socket I/O only; never the time a plan takes.
    timeout = 15.0

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
        elif path == "/release":
            self._handle_release(body)
        else:
            _write_error(self, 404, "not found")

    def _handle_decompose(self, body: dict) -> None:
        goal = self._required_text(body, "goal")
        if goal is None:
            return
        if len(goal) > MAX_GOAL_CHARS:
            _write_error(self, 400, f"goal must be at most {MAX_GOAL_CHARS} characters")
            return
        # an optional real declared-capability catalog for the
        # target robot/cell - omitted (the default, and every existing
        # caller) means "no catalog supplied", validating exactly as
        # before this field existed. See validation.py's own header.
        capabilities: frozenset[str] | None = None
        if "capabilities" in body:
            raw = body["capabilities"]
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                _write_error(self, 400, "capabilities must be a list of strings")
                return
            capabilities = frozenset(raw)
        plan = decompose_goal(goal)
        if plan is None:
            _write_json(self, 200, {"matched": False, "goal": goal, "steps": [], "issues": []})
            return
        issues = validate_plan(plan, capabilities)
        proposal = propose(plan)
        _write_json(self, 200, {
            "matched": True,
            "goal": plan.goal,
            "steps": [asdict(s) for s in plan.steps],
            "issues": [asdict(i) for i in issues],
            "valid": not issues,
            # A decomposition is a proposal, never an order: the steps may only
            # be executed once POST /release answers released=true.
            "executable": False,
            "requires_approval": True,
            "fingerprint": proposal.fingerprint,
            "estimated_cost": proposal.estimated_cost,
            "explanation": proposal.explanation,
        })

    def _handle_release(self, body: dict) -> None:
        goal = self._required_text(body, "goal")
        if goal is None:
            return
        approved_by = self._required_text(body, "approved_by")
        if approved_by is None:
            return
        fingerprint = self._required_text(body, "plan_fingerprint")
        if fingerprint is None:
            return
        if len(goal) > MAX_GOAL_CHARS:
            _write_error(self, 400, f"goal must be at most {MAX_GOAL_CHARS} characters")
            return
        capabilities: frozenset[str] | None = None
        if "capabilities" in body:
            raw = body["capabilities"]
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                _write_error(self, 400, "capabilities must be a list of strings")
                return
            capabilities = frozenset(raw)
        plan = decompose_goal(goal)
        if plan is None:
            _write_json(self, 200, {"released": False, "reason": "the goal does not decompose into a plan"})
            return
        decision = release_for_execution(
            propose(plan), PlanApproval(fingerprint, approved_by), capabilities=capabilities
        )
        _write_json(self, 200, asdict(decision))

    def _required_text(self, body: dict, field: str) -> str | None:
        """The text value of `field`, or None after answering 400 when it is missing or not text."""
        if field not in body:
            _write_error(self, 400, f"missing required field: {field!r}")
            return None
        value = body[field]
        if not isinstance(value, str):
            _write_error(self, 400, f"{field} must be text")
            return None
        return value

    def _handle_recover(self, body: dict) -> None:
        component = self._required_text(body, "component")
        if component is None:
            return
        error_code = self._required_text(body, "error_code")
        if error_code is None:
            return
        detail = body.get("detail", "")
        attempt = body.get("attempt", 1)
        if not isinstance(detail, str):
            _write_error(self, 400, "detail must be text")
            return
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            _write_error(self, 400, "attempt must be an integer of at least 1")
            return
        failure = FailureContext(component=component, error_code=error_code, detail=detail, attempt=attempt)
        strategy = propose_recovery(failure)
        _write_json(self, 200, asdict(strategy))


class SemanticPlannerServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], role: str) -> None:
        super().__init__(address, Handler)
        self.role = role
