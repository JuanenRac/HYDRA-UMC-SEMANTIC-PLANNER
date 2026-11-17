"""plan_approval.single_use: a signed approval that released a plan is not taken a second time."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.approval import propose
from hydra_umc_semantic_planner.approval_policy import ApprovalConfigError, load_approval_policy
from hydra_umc_semantic_planner.approval_signing import sign_approval
from hydra_umc_semantic_planner.decompose import decompose_goal
from hydra_umc_semantic_planner.used_approvals import ALREADY_USED, RETRY_GRACE_MS, UsedApprovals

KEY = b"k" * 32
GOAL = "inspect the weld"


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


def test_the_list_gives_the_first_answer_inside_the_window_and_a_refusal_after_it() -> None:
    clock = Clock()
    used = UsedApprovals(clock)
    assert used.lookup("sig") is None
    used.remember("sig", int(clock.now * 1000) + 60_000, {"released": True, "reason": "ok"})
    assert used.lookup("sig") == {"released": True, "reason": "ok"}
    clock.now += RETRY_GRACE_MS / 1000 + 0.1
    assert used.lookup("sig") == ALREADY_USED
    clock.now += 61
    assert used.lookup("sig") is None and len(used) == 0       # past its own expiry the record is forgotten


def test_the_list_is_bounded() -> None:
    clock = Clock()
    used = UsedApprovals(clock, max_records=3)
    for index in range(5):
        used.remember(f"s{index}", int(clock.now * 1000) + 60_000, {"released": True})
    assert len(used) == 3 and used.lookup("s0") is None and used.lookup("s4") is not None


def _post(base: str, body: dict) -> dict:
    request = urllib.request.Request(base + "/release", data=json.dumps(body).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


@pytest.mark.parametrize("single_use", [False, True])
def test_the_release_route_takes_a_signed_approval_once_only_with_the_switch(single_use: bool) -> None:
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", KEY, "robot-1", single_use=single_use)
    offset = [0.0]
    server.used_approvals = UsedApprovals(lambda: time.time() + offset[0])
    plan = decompose_goal(GOAL, server.symbolic)
    assert plan is not None
    fingerprint = propose(plan).fingerprint
    approval = sign_approval(KEY, fingerprint, "ana", "robot-1", validity_ms=60_000)
    body = {"goal": GOAL, "approved_by": "ana", "plan_fingerprint": fingerprint, "robot_id": "robot-1",
            "signature": approval.signature, "issued_at_ms": approval.issued_at_ms, "expires_at_ms": approval.expires_at_ms}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        first = _post(base, body)
        assert first["released"] is True
        offset[0] = 10.0   # ten seconds later: past the retry window
        again = _post(base, body)
        assert (again["released"] is False and "already used" in again["reason"]) == single_use
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_the_policy_reads_the_switch(tmp_path: Path) -> None:
    assert load_approval_policy(None).single_use is False
    path = tmp_path / "planner.json"
    path.write_text(json.dumps({"plan_approval": {"single_use": True}}), encoding="utf-8")
    assert load_approval_policy(path).single_use is True
    path.write_text(json.dumps({"plan_approval": {"single_use": "yes"}}), encoding="utf-8")
    with pytest.raises(ApprovalConfigError):
        load_approval_policy(path)
