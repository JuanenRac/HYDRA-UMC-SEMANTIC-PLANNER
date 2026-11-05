# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/approval_policy.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The `plan_approval` section of the configuration: are the approvals of a plan signed, and with what.

Signed is the default. `require_signed` set to false is a switch for development only: the approval is then the words of the
request, as it was before signatures existed. The key lives in a file outside the repository (`key_file`); the robot the service
releases plans for (`robot_id`) is part of what the approval signs.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .approval_signing import ALGORITHMS, HMAC

CONFIG_ENV = "HYDRA_UMC_SEMANTIC_PLANNER_CONFIG"
_KNOWN_KEYS = {"require_signed", "require_identity", "algorithm", "key_file", "robot_id", "start_without_key"}


class ApprovalConfigError(ValueError):
    """The plan_approval section is not valid."""


@dataclass(frozen=True)
class ApprovalPolicy:
    require_signed: bool = True
    algorithm: str = HMAC
    # HMAC-SHA256: the shared key file. Ed25519: the PEM public key file (the private key stays with whoever signs).
    key_file: str = ""
    robot_id: str = ""
    # When true, a key that cannot be read does not stop the planner from starting; every release is then refused with the reason.
    start_without_key: bool = False
    # The approval is made by a person who is signed in: POST /release needs the signed token of HYDRA-UMC-SERVER of an operator or an administrator
    # (the common identity of the family), and `approved_by` must be that person. Signed is the default; false is a switch for a bench without the SERVER.
    require_identity: bool = True

    def __post_init__(self) -> None:
        for name in ("require_signed", "start_without_key", "require_identity"):
            if not isinstance(getattr(self, name), bool):
                raise ApprovalConfigError(f"plan_approval.{name} must be true or false")
        for name in ("key_file", "robot_id"):
            if not isinstance(getattr(self, name), str):
                raise ApprovalConfigError(f"plan_approval.{name} must be text")
        if self.algorithm not in ALGORITHMS:
            raise ApprovalConfigError(f"plan_approval.algorithm must be one of {', '.join(ALGORITHMS)}")


def write_require_identity(path: str | os.PathLike[str], value: bool) -> None:
    """Writes `plan_approval.require_identity` into the configuration file `path` so that a change made while the planner runs survives a restart.
    Atomic (temporary file, then replace); the rest of the file is kept as it is. Raises ApprovalConfigError (nothing is written) when the file cannot be used."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("the file must hold a JSON object")
        section = data.setdefault("plan_approval", {})
        if not isinstance(section, dict):
            raise ValueError("plan_approval must be a JSON object")
        section["require_identity"] = bool(value)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError) as error:
        raise ApprovalConfigError(f"the configuration file cannot be written: {error}") from error


def load_approval_policy(path: str | os.PathLike[str] | None = None) -> ApprovalPolicy:
    """The `plan_approval` policy of the file `path`, or of the file named by the planner's configuration variable, or the default (signed)."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return ApprovalPolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ApprovalConfigError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise ApprovalConfigError(f"{chosen} must hold a JSON object")
    section = data.get("plan_approval", {})
    if not isinstance(section, dict):
        raise ApprovalConfigError("plan_approval must be a JSON object")
    unknown = sorted(set(section) - _KNOWN_KEYS)
    if unknown:
        raise ApprovalConfigError(f"plan_approval has unknown keys: {', '.join(unknown)}")
    return ApprovalPolicy(**section)
