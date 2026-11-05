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
import sys
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import __version__
from .health_route import HealthRouteMixin
from .server_identity import accepts
from .service_metrics import MetricsHandlerMixin
from .approval_policy import ApprovalConfigError, write_require_identity
from .approval import PlanApproval, propose, release_for_execution
from .approval_signing import SignedApproval, verify_approval
from .decompose import MAX_GOAL_CHARS, decompose_goal
from .failure_memory import OUTCOMES, FailureMemory, OutcomeError
from .operation import plan_as_operation
from .plan_simulation import PlanRequestError, SimulationPolicy, simulate_plan
from .recovery import FailureContext, RecoveryPolicy, propose_recovery
from .safety_gate import SafetyGate
from .symbolic import SymbolicPolicy
from .validation import validate_plan
from .voice_intents import VoiceIntentPolicy, goal_for_intent


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    def default(o: object) -> object:
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)  # type: ignore[call-overload]
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


class Handler(HealthRouteMixin, MetricsHandlerMixin, BaseHTTPRequestHandler):
    server: "SemanticPlannerServer"
    metrics_service = "hydra-umc-semantic-planner"
    metrics_version = __version__

    # Seconds a client may stay silent on its connection before the server
    # drops it, so a client that connects and sends nothing cannot hold a
    # handler thread forever. Socket I/O only; never the time a plan takes.
    timeout = 15.0

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # quiet by default, same reasoning as this family's other api.py files

    def _identity_ok(self) -> bool:
        """With the identity of HYDRA-UMC-SERVER on (server_identity.py) nothing is open: the request needs a valid signed token (a viewer may only read). Off: as before, no token at all."""
        return self.server.identity_key is None or accepts(self, "", self.server.identity_key)

    def do_GET(self) -> None:  # noqa: N802
        if self.serve_health():
            return
        if self.serve_metrics(authorized=self._identity_ok()):
            return
        if not self._identity_ok():
            _write_error(self, 401, "a valid identity is required")
            return
        if urlparse(self.path).path == "/stats":
            _write_json(self, 200, {"role": self.server.role})
        elif urlparse(self.path).path == "/settings":
            _write_json(self, 200, self.server.settings_view())
        else:
            _write_error(self, 404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._identity_ok():
            _write_error(self, 401, "a valid identity is required")
            return
        try:
            body = _read_json_body(self)
        except (json.JSONDecodeError, ValueError) as e:
            _write_error(self, 400, f"malformed JSON body: {e}")
            return
        if path == "/settings":
            self._handle_settings(body)
        elif path == "/decompose":
            self._handle_decompose(body)
        elif path == "/recover":
            self._handle_recover(body)
        elif path == "/recover/outcome" and self.server.memory is not None:
            self._handle_outcome(body)
        elif path == "/release":
            self._handle_release(body)
        elif path == "/plan/simulate" and self.server.simulation.enabled:
            self._handle_simulate(body)
        elif path == "/voice/intent" and self.server.voice.enabled:
            self._handle_voice_intent(body)
        else:
            _write_error(self, 404, "not found")

    def _handle_settings(self, body: dict) -> None:
        """`POST /settings` with `{"requireIdentity": true|false, "confirm": true}`: the one switch of the approval that can be changed while the planner runs.
        Only an administrator with a signed token of the SERVER; relaxing it (false) needs `confirm: true`; the change is written to the configuration file."""
        identity = getattr(self, "identity", None)
        if self.server.identity_key is None or identity is None or identity.role != "admin":
            _write_error(self, 403, "the settings can be changed only with the signed token of an administrator of HYDRA-UMC-SERVER")
            return
        if set(body) - {"requireIdentity", "confirm"} or not isinstance(body.get("requireIdentity"), bool):
            _write_error(self, 400, "the body must be an object with requireIdentity (true or false) and, to relax it, confirm: true")
            return
        wanted = body["requireIdentity"]
        if not wanted and self.server.require_identity and body.get("confirm") is not True:
            _write_json(self, 400, {"error": "relaxing the identity of the approval needs confirm: true", "code": "CONFIRMATION_REQUIRED"})
            return
        before = self.server.require_identity
        if wanted != before and self.server.settings_file:
            try:
                write_require_identity(self.server.settings_file, wanted)
            except ApprovalConfigError as error:
                _write_json(self, 409, {"error": str(error), "code": "SETTING_REFUSED"})
                return
        self.server.require_identity = wanted
        if wanted != before:
            print(f"[semantic-planner] {'notice' if wanted else 'WARNING'}: plan_approval.require_identity was set to {str(wanted).lower()} through the settings route by {identity.username}", file=sys.stderr)
        _write_json(self, 200, dict(self.server.settings_view(), changed=wanted != before))

    def _handle_voice_intent(self, body: dict) -> None:
        # An intent already parsed by the voice service becomes the goal of the mission catalogue and then takes the exact path of
        # POST /decompose: a proposal that still needs POST /release. Anything that is not a catalogued mission is an honest miss.
        if "intent" not in body:
            _write_error(self, 400, "missing required field: 'intent'")
            return
        goal, reason = goal_for_intent(body["intent"], self.server.voice)
        if goal is None:
            _write_json(self, 200, {"matched": False, "source": "voice", "steps": [], "issues": [], "reason": reason})
            return
        forwarded = {key: body[key] for key in ("capabilities", "target", "priority") if key in body}
        self._handle_decompose({**forwarded, "goal": goal}, source="voice")

    def _handle_decompose(self, body: dict, source: str | None = None) -> None:
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
        # an optional target for the Operation that expresses the plan (the cell or robot it is meant for) and its priority for the queue
        target = body.get("target")
        if target is not None and not (
            isinstance(target, dict) and all(isinstance(target.get(key), str) and target[key] for key in ("kind", "id"))
        ):
            _write_error(self, 400, "target must be an object with a non-empty kind and id")
            return
        priority = body.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int):
            _write_error(self, 400, "priority must be an integer")
            return
        plan = decompose_goal(goal, self.server.symbolic)
        if plan is None:
            _write_json(self, 200, {"matched": False, "goal": goal, "steps": [], "issues": [], **({"source": source} if source else {})})
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
            # the same proposal as the common Operation of the SDK (status "received"): what the orchestrator and the job dispatcher read
            "operation": plan_as_operation(plan, proposal, target=target, priority=priority),
            **({"source": source} if source else {}),
        })

    def _handle_simulate(self, body: dict) -> None:
        # A dry run only: the verdict says what would break and why; nothing is executed or released. Anything that cannot be understood
        # is a 400, never an "accepted".
        try:
            verdict = simulate_plan(body, self.server.simulation)
        except PlanRequestError as error:
            _write_error(self, 400, str(error))
            return
        except Exception:  # noqa: BLE001 - fail closed: an unexpected failure is a refusal, not a verdict
            _write_error(self, 500, "the plan could not be simulated")
            return
        _write_json(self, 200, verdict)

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
        plan = decompose_goal(goal, self.server.symbolic)
        if plan is None:
            _write_json(self, 200, {"released": False, "reason": "the goal does not decompose into a plan"})
            return
        if self.server.require_identity:
            # The approval is made by a person who is signed in with the common identity: the token of the SERVER says who, and the body cannot say otherwise.
            if self.server.identity_key is None:
                _write_json(self, 200, {"released": False, "reason": "an operator identity is required and no identity key is loaded"})
                return
            identity = getattr(self, "identity", None)
            if identity is None:
                _write_json(self, 200, {"released": False, "reason": "the approval needs the signed token of an operator of HYDRA-UMC-SERVER"})
                return
            if approved_by != identity.username:
                _write_json(self, 200, {"released": False, "reason": "approved_by is not the person who is signed in"})
                return
        if self.server.require_signed and self.server.approval_key is None:
            # Signed approvals are required and no key is loaded: nothing is released, and the reason says why.
            _write_json(self, 200, {"released": False, "reason": "signed approvals are required and no approval key is loaded"})
            return
        if self.server.approval_key is not None:
            # The approval must be signed, current and for this plan and this robot: the words of the request are not enough.
            signed = self._signed_approval(body, fingerprint, approved_by)
            if signed is None:
                return
            ok, why = verify_approval(
                self.server.approval_key, signed, expected_fingerprint=propose(plan).fingerprint,
                expected_robot_id=self.server.robot_id,
            )
            if not ok:
                _write_json(self, 200, {"released": False, "reason": why})
                return
        decision = release_for_execution(
            propose(plan), PlanApproval(fingerprint, approved_by), capabilities=capabilities
        )
        payload = asdict(decision)
        gate = self.server.safety_gate
        if gate is not None and decision.released:
            # Second condition after the person's approval: the safety service must say READY, fresh and (by default) signed.
            # Whatever else it says, or nothing, keeps the plan from being released.
            verdict = gate.check()
            if not verdict.allowed:
                payload = {"released": False, "reason": f"safety gate: {verdict.reason}", "safety_gate": {"allowed": False, "state": verdict.state}}
            else:
                payload["safety_gate"] = {"allowed": True, "state": verdict.state}
        _write_json(self, 200, payload)

    def _signed_approval(self, body: dict, fingerprint: str, approved_by: str) -> SignedApproval | None:
        robot_id = body.get("robot_id", "")
        signature = body.get("signature", "")
        issued = body.get("issued_at_ms")
        expires = body.get("expires_at_ms")
        if not isinstance(robot_id, str) or not isinstance(signature, str):
            _write_error(self, 400, "robot_id and signature must be text")
            return None
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (issued, expires)):
            # a missing or malformed time is a refusal of the release, not a server error
            _write_json(self, 200, {"released": False, "reason": "the approval is not signed with its validity window"})
            return None
        return SignedApproval(fingerprint, approved_by, robot_id, issued, expires, signature)  # type: ignore[arg-type]

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
        memory = self.server.memory
        strategy = memory.propose(failure, self.server.policy) if memory is not None else propose_recovery(failure, self.server.policy)
        _write_json(self, 200, asdict(strategy))

    def _handle_outcome(self, body: dict) -> None:
        # How a proposed recovery ended. Only five short fields are kept (never the free text of a failure) and the memory can only make
        # a later proposal more cautious.
        fields = []
        for name in ("component", "error_code", "action", "outcome"):
            value = self._required_text(body, name)
            if value is None:
                return
            fields.append(value)
        try:
            self.server.memory.record(*fields)  # type: ignore[union-attr]
        except OutcomeError as error:
            _write_error(self, 400, f"{error}; outcome is one of {', '.join(OUTCOMES)}" if "outcome" in str(error) else str(error))
            return
        _write_json(self, 200, {"recorded": True, "entries": self.server.memory.size()})  # type: ignore[union-attr]


class SemanticPlannerServer(ThreadingHTTPServer):
    settings_file: str | None = None
    health_open: bool = False  # GET /health answers only when the operator opens it (health_route.py)
    identity_key: bytes | None = None  # the signing key of HYDRA-UMC-SERVER, when the operator turned its identity on (server_identity.py)
    def __init__(
        self,
        address: tuple[str, int],
        role: str,
        approval_key: object | None = None,  # bytes (HMAC-SHA256 key) or an Ed25519 public key
        robot_id: str = "",
        policy: RecoveryPolicy | None = None,
        simulation: SimulationPolicy | None = None,
        safety_gate: SafetyGate | None = None,
        voice: VoiceIntentPolicy | None = None,
        symbolic: SymbolicPolicy | None = None,
        memory: FailureMemory | None = None,
        require_signed: bool = False,
        require_identity: bool = False,
        settings_file: str | None = None,
    ) -> None:
        super().__init__(address, Handler)
        # `serve` passes True unless the configuration relaxes it: POST /release then needs the token of the SERVER of an operator, and approved_by is that person.
        self.require_identity = require_identity
        # The configuration file `POST /settings` writes to (None: the change lasts until the planner restarts).
        self.settings_file = settings_file
        # `serve` passes True unless the configuration switches signed approvals off (development only); direct callers keep the old default.
        self.require_signed = require_signed
        # With a key, POST /release only releases a plan whose approval is signed with it, for `robot_id`, and current.
        self.approval_key = approval_key
        self.robot_id = robot_id
        self.policy = policy if policy is not None else RecoveryPolicy()
        self.role = role
        # Off by default: with the switch off POST /plan/simulate does not exist (404), exactly as before it was added.
        self.simulation = simulation if simulation is not None else SimulationPolicy()
        # Off by default: without a gate /release answers as before; with one, a plan is released only while the safety service says READY.
        self.safety_gate = safety_gate
        # Off by default: with the switch off POST /voice/intent does not exist (404).
        self.voice = voice if voice is not None else VoiceIntentPolicy()
        # Off by default: without it decompose_goal() uses the rules alone; with it the steps come from a verified symbolic search.
        self.symbolic = symbolic if symbolic is not None else SymbolicPolicy()
        # Off by default (None): without it POST /recover/outcome does not exist (404) and recovery has no memory.
        self.memory = memory

    def settings_view(self) -> dict:
        return {"requireIdentity": self.require_identity, "verifiesTokens": self.identity_key is not None, "persisted": bool(self.settings_file)}
