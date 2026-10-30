# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_operation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""A plan as the common Operation of the SDK: its shape, its identity, the HTTP answer, and (when the SDK is next to this repository) the SDK's own validator."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hydra_umc_semantic_planner.approval import propose
from hydra_umc_semantic_planner.decompose import decompose_goal
from hydra_umc_semantic_planner.operation import plan_as_operation

from test_api import _post, running_server

REQUIRED = ("schema_version", "operation_id", "correlation_id", "kind", "target", "status", "requested_at_utc", "updated_at_utc", "params")
FIXED_NOW = datetime(2024, 1, 1, 12, 30, 5, tzinfo=timezone.utc)


def _operation(**kwargs):
    plan = decompose_goal("assemble the housing")
    assert plan is not None
    return plan, propose(plan), plan_as_operation(plan, propose(plan), clock=lambda: FIXED_NOW, **kwargs)


def test_the_plan_is_an_operation_of_the_common_contract() -> None:
    plan, proposal, operation = _operation()
    assert all(key in operation for key in REQUIRED)
    assert operation["schema_version"] == "1.0"
    assert operation["kind"] == "execute_plan"
    assert operation["status"] == "received"  # nothing is authorized, queued or sent
    assert operation["requested_at_utc"] == operation["updated_at_utc"] == "2024-01-01T12:30:05Z"
    assert operation["target"] == {"kind": "cell", "id": "unassigned"}
    assert re.fullmatch(r"plan-[0-9a-f]{32}", operation["operation_id"])
    assert operation["correlation_id"] == proposal.fingerprint
    params = operation["params"]
    assert params["goal"] == plan.goal and params["fingerprint"] == proposal.fingerprint
    assert [step["primitive"] for step in params["steps"]] == [step.primitive for step in plan.steps]
    assert params["requires_approval"] is True and params["priority"] == 0
    json.dumps(operation)  # it travels as JSON


def test_the_same_plan_is_the_same_operation_and_another_plan_is_not() -> None:
    _, _, first = _operation()
    _, _, again = _operation()
    assert first["operation_id"] == again["operation_id"]
    other = decompose_goal("inspect the board")
    assert other is not None
    assert plan_as_operation(other, propose(other))["operation_id"] != first["operation_id"]


def test_the_target_and_the_priority_are_taken_and_checked() -> None:
    _, _, operation = _operation(target={"kind": "robot", "id": "arm-1"}, priority=7)
    assert operation["target"] == {"kind": "robot", "id": "arm-1"}
    assert operation["params"]["priority"] == 7
    plan = decompose_goal("assemble the housing")
    for bad in ({"kind": "robot"}, {"kind": "", "id": "x"}, {"kind": "robot", "id": 3}):
        with pytest.raises(ValueError):
            plan_as_operation(plan, propose(plan), target=bad)
    for bad in (True, "1", 1.5):
        with pytest.raises(ValueError):
            plan_as_operation(plan, propose(plan), priority=bad)


def test_the_http_answer_carries_the_operation_of_the_proposal() -> None:
    with running_server() as base:
        status, body = _post(f"{base}/decompose", {"goal": "assemble the housing", "target": {"kind": "cell", "id": "cell-2"}, "priority": 4})
        assert status == 200
        operation = body["operation"]
        assert operation["status"] == "received" and operation["target"]["id"] == "cell-2"
        assert operation["params"]["fingerprint"] == body["fingerprint"] and operation["params"]["priority"] == 4
        assert body["executable"] is False  # expressing a proposal as an operation does not release it
        status, again = _post(f"{base}/decompose", {"goal": "assemble the housing"})
        assert again["operation"]["operation_id"] == operation["operation_id"]
        # a goal the planner does not understand has no plan and so no operation
        _, unmatched = _post(f"{base}/decompose", {"goal": "xyzzy"})
        assert "operation" not in unmatched


@pytest.mark.parametrize("target", ["cell-2", {"kind": "cell"}, {"kind": "", "id": "x"}, []])
def test_a_wrong_target_is_a_400(target) -> None:
    with running_server() as base:
        status, body = _post(f"{base}/decompose", {"goal": "assemble the housing", "target": target})
        assert status == 400 and "target" in body["error"]


@pytest.mark.parametrize("priority", [True, "high", 1.5])
def test_a_wrong_priority_is_a_400(priority) -> None:
    with running_server() as base:
        status, body = _post(f"{base}/decompose", {"goal": "assemble the housing", "priority": priority})
        assert status == 400 and "priority" in body["error"]


def test_the_sdk_validator_accepts_the_operation_when_the_sdk_is_next_to_this_repository() -> None:
    root = Path(os.environ.get("HYDRA_UMC_SDK_ROOT", str(Path(__file__).resolve().parents[2] / "HYDRA-UMC-SDK")))
    source = root / "clients" / "python" / "src"
    if not source.is_dir():
        pytest.skip(f"no SDK checkout at {root}")
    sys.path.insert(0, str(source))
    try:
        from hydra_umc_sdk import validate
    finally:
        sys.path.remove(str(source))
    _, _, operation = _operation()
    validate("Operation", operation)
