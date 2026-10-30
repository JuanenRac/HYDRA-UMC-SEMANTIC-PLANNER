# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/operation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""A plan as the common Operation of the SDK (`operation.schema.json`).

The planner proposes; a plan is not an order. To hand a proposal to the rest of the ecosystem (the orchestrator, the job dispatcher) it is
expressed as the one shape they all read: an Operation with `kind` `execute_plan`, the `target` it is meant for, `status` `received` (the
first state of the contract: nothing has been authorized, queued or sent) and the steps in `params`. Nothing in it makes the plan
executable: the release of a plan (`POST /release`) is still what decides.

The keys of `params` that the orchestrator and the dispatcher read when they take the operation as a job are `priority`, `required_tool`,
`location` and `depends_on`; a plan sets `priority` and leaves the rest to the caller. The steps, the goal and the fingerprint travel with it.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable

from .approval import PlanProposal
from .primitives import Plan

OPERATION_KIND = "execute_plan"
SCHEMA_VERSION = "1.0"
DEFAULT_TARGET = {"kind": "cell", "id": "unassigned"}


def _utc(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_as_operation(
    plan: Plan,
    proposal: PlanProposal,
    *,
    target: dict[str, str] | None = None,
    priority: int = 0,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """The Operation that expresses `plan` (whose proposal carries its fingerprint). `target` is `{"kind": ..., "id": ...}` (the cell or robot the plan is for)."""

    target = dict(target) if target is not None else dict(DEFAULT_TARGET)
    if not all(isinstance(target.get(key), str) and target[key] for key in ("kind", "id")):
        raise ValueError("target needs a non-empty kind and id")
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError("priority must be an integer")
    now = _utc(clock)
    return {
        "schema_version": SCHEMA_VERSION,
        # one operation per distinct plan: the same plan proposed twice is the same operation, so a consumer that deduplicates by id keeps one
        "operation_id": f"plan-{proposal.fingerprint[:32]}",
        "correlation_id": proposal.fingerprint,
        "kind": OPERATION_KIND,
        "target": {"kind": target["kind"], "id": target["id"]},
        "status": "received",
        "status_reason": "proposed by the semantic planner; not released",
        "requested_at_utc": now,
        "updated_at_utc": now,
        "params": {
            "goal": plan.goal,
            "steps": [asdict(step) for step in plan.steps],
            "fingerprint": proposal.fingerprint,
            "requires_approval": True,
            "priority": priority,
        },
    }
