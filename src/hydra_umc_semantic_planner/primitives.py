# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/primitives.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real, closed vocabulary of robotic command primitives a Plan is made of.

A small, honest set - real task decomposition v0 only needs to sequence
these, not the full command surface a real HYDRA-UMC-ORCHESTRATOR
integration would eventually need.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MOVE_TO = "MOVE_TO"
GRIP = "GRIP"
RELEASE = "RELEASE"
INSPECT = "INSPECT"
WAIT = "WAIT"

ALL_PRIMITIVES = (MOVE_TO, GRIP, RELEASE, INSPECT, WAIT)


@dataclass(frozen=True)
class Step:
    """One real command primitive with its real parameters."""

    primitive: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    """A real, ordered sequence of Steps decomposed from one goal."""

    goal: str
    steps: tuple[Step, ...]
