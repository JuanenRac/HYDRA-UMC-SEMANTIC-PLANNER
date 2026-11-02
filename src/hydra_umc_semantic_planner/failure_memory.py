# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/failure_memory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A small, bounded memory of how the recoveries that were proposed ended.

A caller that applied a proposed recovery reports its outcome (`POST /recover/outcome`): which component, which error code, which action
and whether it worked. The memory keeps only that: the component name, the error code, the action, the outcome and when it happened. It
never keeps the free text of a failure (`detail`), an operator name or an address, so nothing in it identifies a person.

It is bounded twice: at most `max_entries` records (the oldest go first) and none older than `ttl_s` seconds. It is OFF by default and
it can only make a recovery MORE conservative: when an action has failed `min_failures` times with no success in the records still alive
for the same component and error code, the proposal becomes `ESCALATE_TO_OPERATOR`. It never turns an escalation or an abort into a
retry, and it never adds an action the rules do not already propose.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .recovery import (
    CONFIG_ENV,
    ESCALATE_TO_OPERATOR,
    FailureContext,
    RecoveryPolicy,
    RecoveryStrategy,
    propose_recovery,
)

OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_FAILURE = "FAILURE"
OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_FAILURE)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_KNOWN_KEYS = {"enabled", "max_entries", "ttl_s", "min_failures", "path"}
HARD_MAX_ENTRIES = 10000


class FailureMemoryConfigError(ValueError):
    """The `failure_memory` section of the configuration file cannot be used."""


@dataclass(frozen=True)
class FailureMemoryPolicy:
    enabled: bool = False
    max_entries: int = 200
    ttl_s: int = 7 * 24 * 3600
    min_failures: int = 3
    # Optional file that keeps the records between runs; empty means memory only.
    path: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise FailureMemoryConfigError("failure_memory.enabled must be true or false")
        for name in ("max_entries", "ttl_s", "min_failures"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise FailureMemoryConfigError(f"failure_memory.{name} must be an integer of at least 1")
        if self.max_entries > HARD_MAX_ENTRIES:
            raise FailureMemoryConfigError(f"failure_memory.max_entries must be at most {HARD_MAX_ENTRIES}")
        if not isinstance(self.path, str):
            raise FailureMemoryConfigError("failure_memory.path must be text")


def load_memory_policy(path: str | os.PathLike[str] | None = None) -> FailureMemoryPolicy:
    """The `failure_memory` policy of the file `path`, or of the file named by the planner's variable, or the default (off)."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return FailureMemoryPolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FailureMemoryConfigError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise FailureMemoryConfigError(f"{chosen} must hold a JSON object")
    section = data.get("failure_memory", {})
    if not isinstance(section, dict):
        raise FailureMemoryConfigError("failure_memory must be a JSON object")
    unknown = sorted(set(section) - _KNOWN_KEYS)
    if unknown:
        raise FailureMemoryConfigError(f"failure_memory has unknown keys: {', '.join(unknown)}")
    return FailureMemoryPolicy(**section)


class OutcomeError(ValueError):
    """An outcome report that cannot be recorded."""


class FailureMemory:
    """Thread-safe, bounded, expiring record of recovery outcomes."""

    def __init__(self, policy: FailureMemoryPolicy, clock: Callable[[], float] = time.time) -> None:
        self.policy = policy
        self._clock = clock
        self._lock = threading.Lock()
        # (timestamp, component, error_code, action, outcome), oldest first
        self._records: list[tuple[float, str, str, str, str]] = []
        self._load()

    def _prune(self, now: float) -> None:
        cutoff = now - self.policy.ttl_s
        self._records = [r for r in self._records if r[0] > cutoff]
        if len(self._records) > self.policy.max_entries:
            self._records = self._records[-self.policy.max_entries:]

    def record(self, component: str, error_code: str, action: str, outcome: str) -> None:
        if not isinstance(component, str) or not _NAME.match(component):
            raise OutcomeError("component must be a short name (letters, digits, '_', '-', '.')")
        if not isinstance(error_code, str) or not _NAME.match(error_code):
            raise OutcomeError("error_code must be a short code")
        if not isinstance(action, str) or not _NAME.match(action):
            raise OutcomeError("action must be a short name")
        if outcome not in OUTCOMES:
            raise OutcomeError(f"outcome must be one of {', '.join(OUTCOMES)}")
        with self._lock:
            now = self._clock()
            self._records.append((now, component, error_code, action, outcome))
            self._prune(now)
            self._save()

    def counts(self, component: str, error_code: str, action: str) -> tuple[int, int]:
        """(successes, failures) of `action` for this component and code among the live records."""
        with self._lock:
            self._prune(self._clock())
            ok = bad = 0
            for _, comp, code, act, outcome in self._records:
                if comp == component and code == error_code and act == action:
                    if outcome == OUTCOME_SUCCESS:
                        ok += 1
                    else:
                        bad += 1
            return ok, bad

    def size(self) -> int:
        with self._lock:
            self._prune(self._clock())
            return len(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records = []
            self._save()

    def propose(self, failure: FailureContext, policy: RecoveryPolicy | None = None) -> RecoveryStrategy:
        """The rule-based proposal, made more conservative when the memory shows that action keeps failing."""
        strategy = propose_recovery(failure, policy)
        if strategy.action == ESCALATE_TO_OPERATOR or not _NAME.match(failure.component):
            return strategy
        ok, bad = self.counts(failure.component, failure.error_code, strategy.action)
        if ok == 0 and bad >= self.policy.min_failures:
            return RecoveryStrategy(
                ESCALATE_TO_OPERATOR,
                f"{strategy.action} failed {bad} times for {failure.error_code} on {failure.component} and never worked - a person has to look at it",
            )
        return strategy

    # -- optional persistence (never anything but the five fields of a record) --
    def _load(self) -> None:
        if not self.policy.path:
            return
        try:
            data = json.loads(Path(self.policy.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, list):
            return
        for item in data:
            if (
                isinstance(item, list) and len(item) == 5 and isinstance(item[0], (int, float))
                and all(isinstance(x, str) and _NAME.match(x) for x in item[1:4]) and item[4] in OUTCOMES
            ):
                self._records.append((float(item[0]), item[1], item[2], item[3], item[4]))
        self._prune(self._clock())

    def _save(self) -> None:
        if not self.policy.path:
            return
        target = Path(self.policy.path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump([list(r) for r in self._records], handle)
            os.replace(tmp, target)
        except OSError:
            pass  # the memory keeps working in RAM; losing the file only loses what was learned
