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
import sys

from . import __version__
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


def _run_decompose(goal: str) -> int:
    plan = decompose_goal(goal)
    if plan is None:
        print(f'No matching task template for: "{goal}"')
        print("(v0 is a real rule-based planner over a small template vocabulary - an honest miss, not a guess.)")
        return 0

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "decompose":
        return _run_decompose(args.goal)
    if args.command == "recover":
        return _run_recover(args.component, args.error_code, args.detail)

    _print_identity()
    return 0


if __name__ == "__main__":
    sys.exit(main())
