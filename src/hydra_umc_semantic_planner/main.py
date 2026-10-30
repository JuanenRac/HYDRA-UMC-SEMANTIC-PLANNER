# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/main.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Entry point for HYDRA-UMC-SEMANTIC-PLANNER.

Bare invocation prints identity/version/role, unchanged from the
scaffolding stage. The real v0 work lives behind two subcommands: real
rule-based task decomposition (decompose.py) and real rule-based
semantic error recovery over structured failure codes (recovery.py) -
neither is the local-LLM reasoning the README's own roadmap describes.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .api import SemanticPlannerServer
from .approval_signing import ApprovalKeyError, load_key, sign_approval
from .decompose import decompose_goal
from .recovery import FailureContext, propose_recovery
from .validation import validate_plan

PROJECT_NAME = "HYDRA-UMC-SEMANTIC-PLANNER"
ROLE = (
    "Semantic Planner (Hailo-10) - decomposes high-level goals into "
    "robotic primitives and recovers from execution failures."
)


def _print_identity() -> None:
    print(f"{PROJECT_NAME} v{__version__}")
    print(ROLE)


# Exit status for a goal that did not decompose: 0 is a plan, 1 a failed validation.
EXIT_NO_PLAN = 3


def _run_decompose(goal: str) -> int:
    plan = decompose_goal(goal)
    if plan is None:
        print(f'No matching task template for: "{goal}"')
        print("(v0 is a real rule-based planner over a small template vocabulary - an honest miss, not a guess.)")
        return EXIT_NO_PLAN

    issues = validate_plan(plan)
    if issues:
        # A real, honest refusal: never hand off a plan that fails its
        # own preconditions as if it were execution-ready. decompose_goal()
        # never actually produces one of these today (its templates
        # always fill the right params) - this is the contract a future
        # LLM-based planner (this project's own roadmap) would have to
        # satisfy, since it cannot guarantee well-formed params the way a
        # fixed template can.
        print(f'Plan for: "{goal}" FAILED precondition validation:')
        for issue in issues:
            print(f"  step {issue.step_index} ({issue.primitive}): {issue.issue}")
        return 1

    print(f'Plan for: "{goal}"')
    for index, step in enumerate(plan.steps, start=1):
        params = ", ".join(f"{key}={value}" for key, value in step.params.items())
        print(f"  {index}. {step.primitive}({params})")
    return 0


def _run_recover(component: str, error_code: str, detail: str) -> int:
    failure = FailureContext(component=component, error_code=error_code, detail=detail)
    strategy = propose_recovery(failure)
    print(f"Failure: {component} reported {error_code}" + (f" ({detail})" if detail else ""))
    print(f"Recovery: {strategy.action} - {strategy.reason}")
    return 0


def _run_serve(addr: str, port: int, approval_key_file: str | None = None, robot_id: str = "") -> int:
    approval_key = None
    if approval_key_file:
        if not robot_id.strip():
            print("error: --approval-key-file needs --robot-id: a signed approval is for one robot", file=sys.stderr)
            return 2
        try:
            approval_key = load_key(approval_key_file)
        except ApprovalKeyError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    server = SemanticPlannerServer((addr, port), ROLE, approval_key, robot_id)
    print(f"[semantic-planner] HTTP API listening on {addr}:{port}")
    print("[semantic-planner] POST /decompose, POST /recover, POST /release, GET /stats")
    if approval_key is not None:
        print(f"[semantic-planner] POST /release needs an approval signed for robot {robot_id!r}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[semantic-planner] shutting down")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hydra-umc-semantic-planner", description=ROLE)
    subparsers = parser.add_subparsers(dest="command")

    decompose_parser = subparsers.add_parser(
        "decompose", help="Real rule-based task decomposition into robotic primitives."
    )
    decompose_parser.add_argument("goal", help="High-level goal, e.g. \"assemble the pcb\".")

    recover_parser = subparsers.add_parser(
        "recover", help="Real rule-based semantic recovery for a structured failure code."
    )
    recover_parser.add_argument("--component", required=True, help="Component that reported the failure.")
    recover_parser.add_argument("--error-code", required=True, help="Structured error code (e.g. TIMEOUT).")
    recover_parser.add_argument("--detail", default="", help="Optional human-readable detail.")

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run decompose/recover as a JSON/HTTP API (POST /decompose, POST /recover) "
             "- the exact same functions the CLI subcommands above already run.",
    )
    serve_parser.add_argument("--addr", default="127.0.0.1", help="address to bind the HTTP API to")
    serve_parser.add_argument("--port", type=int, default=8109, help="port for the HTTP API")

    serve_parser.add_argument(
        "--approval-key-file", default=None,
        help="file with the key that signs approvals; with it POST /release only releases a plan whose approval is "
             "signed, current and for --robot-id (off by default: the approval is the words of the request)",
    )
    serve_parser.add_argument("--robot-id", default="", help="the robot this service releases plans for (needed with --approval-key-file)")

    sign_parser = subparsers.add_parser(
        "sign-approval",
        help="Sign the approval of the plan of a goal, for POST /release of a service started with --approval-key-file.",
    )
    sign_parser.add_argument("goal", help="The goal whose plan is approved.")
    sign_parser.add_argument("--approved-by", required=True, help="Who approves the plan.")
    sign_parser.add_argument("--robot-id", required=True, help="The robot the approval is for.")
    sign_parser.add_argument("--key-file", required=True, help="File with the signing key.")
    sign_parser.add_argument("--valid-seconds", type=int, default=300, help="How long the approval is valid (default 300, at most 3600).")

    return parser


def _run_sign(args: argparse.Namespace) -> int:
    from .approval import propose

    plan = decompose_goal(args.goal)
    if plan is None:
        print(f'error: no plan for "{args.goal}"', file=sys.stderr)
        return 1
    try:
        key = load_key(args.key_file)
        signed = sign_approval(
            key, propose(plan).fingerprint, args.approved_by, args.robot_id, validity_ms=args.valid_seconds * 1000
        )
    except (ApprovalKeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "goal": args.goal, "plan_fingerprint": signed.plan_fingerprint, "approved_by": signed.approved_by,
        "robot_id": signed.robot_id, "issued_at_ms": signed.issued_at_ms, "expires_at_ms": signed.expires_at_ms,
        "signature": signed.signature,
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "decompose":
        return _run_decompose(args.goal)
    if args.command == "recover":
        return _run_recover(args.component, args.error_code, args.detail)
    if args.command == "serve":
        return _run_serve(args.addr, args.port, args.approval_key_file, args.robot_id)
    if args.command == "sign-approval":
        return _run_sign(args)

    _print_identity()
    return 0


if __name__ == "__main__":
    sys.exit(main())
