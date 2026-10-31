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

# Longest goal this planner will look at. A goal is a short sentence; anything
# longer is refused (an honest miss) instead of being scanned.
MAX_GOAL_CHARS = 512

# (goal keyword pattern, template name). Every template that matches counts:
# a goal that fits more than one template is ambiguous and is refused rather
# than silently reduced to the first one.
_TEMPLATES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bassemble\b", re.IGNORECASE), "assemble"),
    (re.compile(r"\bpick\b[^.]*?\bplace\b", re.IGNORECASE), "pick_and_place"),
    (re.compile(r"\binspect\b", re.IGNORECASE), "inspect"),
)

# A goal that forbids, cancels or conditions the action is never turned into a
# plan for that action.
_NEGATIONS = re.compile(
    r"\b(?:not|never|don['’]?t|cannot|can['’]?t|no|without|avoid|cancel|stop|"
    r"nunca|jam[aá]s|sin|evita|cancela|para)\b",
    re.IGNORECASE,
)

_ARTICLES = frozenset({"the", "a", "an", "this", "that", "my", "our", "el", "la", "los", "las", "un", "una"})
# Words that can never be the object of an action: pronouns, adverbs and
# connectors. A goal whose "object" is one of these is not understood.
_NOT_AN_OBJECT = frozenset({
    "it", "them", "this", "that", "these", "those", "anything", "something", "everything",
    "now", "then", "later", "carefully", "slowly", "quickly", "please", "again", "first",
    "and", "or", "but", "to", "in", "on", "into", "onto", "at", "up", "down", "out", "with",
    "of", "for", "from", "by", "there", "here", "next", "also", "too",
})
_WORD = re.compile(r"[a-zA-Z0-9_-]+")


def _object_after(words: list[str], start: int) -> str | None:
    """The object that follows `start`: skips one article, takes the first word that can be an object."""
    index = start
    if index < len(words) and words[index].lower() in _ARTICLES:
        index += 1
    if index < len(words) and words[index].lower() not in _NOT_AN_OBJECT:
        return words[index]
    return None


def _find_word(words: list[str], target: str, start: int = 0) -> int | None:
    for index in range(start, len(words)):
        if words[index].lower() == target:
            return index
    return None


def _extract_target(goal: str, template: str) -> tuple[str, str | None] | None:
    """(target, destination) from the position of the verb, or None when no real object follows it."""
    words = _WORD.findall(goal)
    verb = {"assemble": "assemble", "inspect": "inspect", "pick_and_place": "pick"}[template]
    at = _find_word(words, verb)
    if at is None:
        return None
    start = at + 1
    if template == "pick_and_place" and start < len(words) and words[start].lower() == "up":
        start += 1
    target = _object_after(words, start)
    if target is None:
        return None
    destination = None
    if template == "pick_and_place":
        place = _find_word(words, "place", start)
        if place is not None:
            index = place + 1
            if index < len(words) and words[index].lower() == "it":
                index += 1
            if index < len(words) and words[index].lower() in {"on", "in", "into", "onto", "at", "to"}:
                destination = _object_after(words, index + 1)
    return target, destination


def _build_plan(template: str, target: str, destination: str | None = None) -> tuple[Step, ...]:
    if template == "assemble":
        return (
            Step(MOVE_TO, {"location": "pickup"}),  # type: ignore[arg-type]
            Step(GRIP, {"target": target}),  # type: ignore[arg-type]
            Step(MOVE_TO, {"location": "assembly_point"}),  # type: ignore[arg-type]
            Step(RELEASE, {"target": target}),  # type: ignore[arg-type]
        )
    if template == "pick_and_place":
        return (
            Step(MOVE_TO, {"location": "pickup"}),  # type: ignore[arg-type]
            Step(GRIP, {"target": target}),  # type: ignore[arg-type]
            Step(MOVE_TO, {"location": destination or "destination"}),  # type: ignore[arg-type]
            Step(RELEASE, {"target": target}),  # type: ignore[arg-type]
        )
    if template == "inspect":
        return (
            Step(MOVE_TO, {"location": target}),  # type: ignore[arg-type]
            Step(INSPECT, {"target": target}),  # type: ignore[arg-type]
        )
    raise ValueError(f"unknown template: {template}")


def decompose_goal(goal: str) -> Plan | None:
    """Real rule-based decomposition of `goal` into a sequence of Steps.

    Returns `None` for a real, honest miss - a goal outside this v0's
    known vocabulary is never silently forced into the wrong template.
    That includes a goal that is negated or cancelled, one that matches more
    than one template, one without a real object, and one longer than
    `MAX_GOAL_CHARS`.
    """
    if len(goal) > MAX_GOAL_CHARS or _NEGATIONS.search(goal):
        return None
    matched = [template for pattern, template in _TEMPLATES if pattern.search(goal)]
    if len(matched) != 1:
        return None
    extracted = _extract_target(goal, matched[0])
    if extracted is None:
        return None
    target, destination = extracted
    return Plan(goal=goal, steps=_build_plan(matched[0], target, destination))
