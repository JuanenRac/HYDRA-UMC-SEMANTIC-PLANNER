# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/approval_signing.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""A signed approval: who approved which plan, for which robot, and until when.

Without a signature, "approved by Ana" is only a sentence the caller writes in the request. Here the approval is
an HMAC-SHA256 over the plan's fingerprint, the approver, the robot and the time window, made with a key that
lives in a file of this installation (never in the repository). It cannot be reused for another plan, another
robot or after it expires. A symmetric key proves the approval came from someone holding the installation's key;
it does not tell one person from another, which a key per person would.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path

MIN_KEY_BYTES = 16
# The longest validity an approval may claim, whatever its signer wrote.
MAX_VALIDITY_MS = 3_600_000
DEFAULT_VALIDITY_MS = 300_000
# A clock that is slightly ahead on the signing side is tolerated.
CLOCK_SKEW_MS = 5_000


class ApprovalKeyError(ValueError):
    """The key file is missing, unreadable or too short."""


def load_key(path: str | Path) -> bytes:
    try:
        raw = Path(path).read_bytes().strip()
    except OSError as error:
        raise ApprovalKeyError(f"cannot read the approval key file: {error}") from error
    if len(raw) < MIN_KEY_BYTES:
        raise ApprovalKeyError(f"the approval key must be at least {MIN_KEY_BYTES} bytes")
    return raw


@dataclass(frozen=True)
class SignedApproval:
    plan_fingerprint: str
    approved_by: str
    robot_id: str
    issued_at_ms: int
    expires_at_ms: int
    signature: str = ""


def _message(approval: SignedApproval) -> bytes:
    parts = (
        "hydra-umc-plan-approval-v1",
        approval.plan_fingerprint,
        approval.approved_by,
        approval.robot_id,
        str(approval.issued_at_ms),
        str(approval.expires_at_ms),
    )
    # Length-prefixed fields: no value can swallow its neighbour.
    return b"".join(str(len(part.encode("utf-8"))).encode("ascii") + b":" + part.encode("utf-8") for part in parts)


def sign_approval(
    key: bytes,
    plan_fingerprint: str,
    approved_by: str,
    robot_id: str,
    *,
    validity_ms: int = DEFAULT_VALIDITY_MS,
    now_ms: int | None = None,
) -> SignedApproval:
    if not robot_id.strip():
        raise ValueError("a signed approval names the robot it is for")
    if not approved_by.strip():
        raise ValueError("a signed approval names who approved it")
    if not 0 < validity_ms <= MAX_VALIDITY_MS:
        raise ValueError(f"the validity must be between 1 and {MAX_VALIDITY_MS} ms")
    issued = int(time.time() * 1000) if now_ms is None else now_ms
    unsigned = SignedApproval(plan_fingerprint, approved_by, robot_id, issued, issued + validity_ms)
    signature = hmac.new(key, _message(unsigned), hashlib.sha256).hexdigest()
    return SignedApproval(plan_fingerprint, approved_by, robot_id, unsigned.issued_at_ms, unsigned.expires_at_ms, signature)


def verify_approval(
    key: bytes,
    approval: SignedApproval,
    *,
    expected_fingerprint: str,
    expected_robot_id: str,
    now_ms: int | None = None,
) -> tuple[bool, str]:
    """(True, '') when the approval is genuine, current and for this plan and robot; otherwise (False, why)."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    for name, value in (("issued_at_ms", approval.issued_at_ms), ("expires_at_ms", approval.expires_at_ms)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return False, f"the approval has no valid {name}"
    if not approval.signature:
        return False, "the approval is not signed"
    expected = hmac.new(key, _message(approval), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode("ascii"), approval.signature.encode("utf-8", "replace")):
        return False, "the signature of the approval does not match"
    if approval.expires_at_ms <= approval.issued_at_ms or approval.expires_at_ms - approval.issued_at_ms > MAX_VALIDITY_MS:
        return False, "the validity window of the approval is not acceptable"
    if approval.issued_at_ms > now + CLOCK_SKEW_MS:
        return False, "the approval was issued in the future"
    if now >= approval.expires_at_ms:
        return False, "the approval has expired"
    if approval.plan_fingerprint != expected_fingerprint:
        return False, "the approval is for a different plan"
    if not expected_robot_id or approval.robot_id != expected_robot_id:
        return False, "the approval is for a different robot"
    return True, ""
