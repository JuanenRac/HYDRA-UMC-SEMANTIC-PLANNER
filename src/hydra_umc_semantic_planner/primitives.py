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

import copy
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

MOVE_TO = "MOVE_TO"
GRIP = "GRIP"
RELEASE = "RELEASE"
INSPECT = "INSPECT"
WAIT = "WAIT"

ALL_PRIMITIVES = (MOVE_TO, GRIP, RELEASE, INSPECT, WAIT)


class Params(Mapping[str, Any]):
    """The parameters of a Step: read-only and hashable.

    A frozen dataclass whose field is a dict is frozen only on the surface: the dict could still be changed after a plan was proposed
    (the fingerprint would notice, but the type promised more than it kept), and the Step could not be hashed. A `Params` cannot be
    assigned to, deletes nothing, compares equal to a plain dict with the same items, and `dataclasses.asdict` turns it back into
    a dict, so the JSON of a plan is what it always was.
    """

    __slots__ = ("_items",)
    _items: dict[str, Any]

    def __init__(self, items: Mapping[str, Any] | None = None) -> None:
        object.__setattr__(self, "_items", dict(items or {}))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Params is read-only")

    def __getitem__(self, key: str) -> Any:
        return self._items[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return hash(frozenset((key, repr(value)) for key, value in self._items.items()))

    def __repr__(self) -> str:
        return f"Params({self._items!r})"

    def __deepcopy__(self, memo: dict[int, object]) -> dict[str, Any]:
        # what dataclasses.asdict() ends up with: a plain dict (so json.dumps works)
        return copy.deepcopy(self._items, memo)


@dataclass(frozen=True)
class Step:
    """One real command primitive with its real parameters (read-only: see `Params`)."""

    primitive: str
    params: Params = field(default_factory=Params)

    def __post_init__(self) -> None:
        if not isinstance(self.params, Params):
            object.__setattr__(self, "params", Params(self.params))


@dataclass(frozen=True)
class Plan:
    """A real, ordered sequence of Steps decomposed from one goal."""

    goal: str
    steps: tuple[Step, ...]
