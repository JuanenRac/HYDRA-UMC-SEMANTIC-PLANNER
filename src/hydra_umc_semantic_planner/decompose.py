# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/decompose.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real, rule-based task decomposition over a small known goal vocabulary.

Honestly template-based, not a local LLM - the same reasoning as the
sibling HYDRA-UMC-VOICE-UI's real rule-based intent parser and
HYDRA-UMC-DOCS-QA's real TF-IDF index instead of an embedding model: a
real, testable kernel today that a future LLM-based planner can replace
behind the same `decompose_goal()` contract.
"""
from __future__ import annotations

import re

from .primitives import GRIP, INSPECT, MOVE_TO, RELEASE, Plan, Step

# (goal keyword pattern, template builder) - first match wins, same
# first-match-wins contract as the sibling VOICE-UI's intent rules.
_TEMPLATES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bassemble\b", re.IGNORECASE), "assemble"),
    (re.compile(r"\bpick\b.*\bplace\b", re.IGNORECASE), "pick_and_place"),
    (re.compile(r"\binspect\b", re.IGNORECASE), "inspect"),
)


def _extract_target(goal: str) -> str:
    """Real, simple heuristic: the last real word of the goal is the target."""
    words = re.findall(r"[a-zA-Z0-9_-]+", goal)
    return words[-1] if words else "target"


def _build_plan(template: str, target: str) -> tuple[Step, ...]:
    if template == "assemble":
        return (
            Step(MOVE_TO, {"location": "pickup"}),
            Step(GRIP, {"target": target}),
            Step(MOVE_TO, {"location": "assembly_point"}),
            Step(RELEASE, {"target": target}),
        )
    if template == "pick_and_place":
        return (
            Step(MOVE_TO, {"location": "pickup"}),
            Step(GRIP, {"target": target}),
            Step(MOVE_TO, {"location": "destination"}),
            Step(RELEASE, {"target": target}),
        )
    if template == "inspect":
        return (
            Step(MOVE_TO, {"location": target}),
            Step(INSPECT, {"target": target}),
        )
    raise ValueError(f"unknown template: {template}")


def decompose_goal(goal: str) -> Plan | None:
    """Real rule-based decomposition of `goal` into a sequence of Steps.

    Returns `None` for a real, honest miss - a goal outside this v0's
    known vocabulary is never silently forced into the wrong template.
    """
    for pattern, template in _TEMPLATES:
        if pattern.search(goal):
            target = _extract_target(goal)
            return Plan(goal=goal, steps=_build_plan(template, target))
    return None
