# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/used_approvals.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The signed approvals that already released a plan (`plan_approval.single_use`).

An approval is valid for a window of time; with the switch on, the one that released a plan is not taken a second time. The list is in memory,
bounded, and a record leaves it when the approval would have expired anyway. A client that repeats its request because the answer was lost gets
the same answer for `RETRY_GRACE_MS`, so a cut in the network does not turn a released plan into a refusal.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

RETRY_GRACE_MS = 2000
MAX_RECORDS = 1024
ALREADY_USED = {"released": False, "reason": "the approval was already used"}


class UsedApprovals:
    def __init__(self, clock: Callable[[], float] = time.time, max_records: int = MAX_RECORDS) -> None:
        self._clock = clock
        self._max = max_records
        self._lock = threading.Lock()
        self._records: OrderedDict[str, tuple[float, int, dict]] = OrderedDict()   # signature -> (first use ms, expires_at_ms, the answer)

    def _now_ms(self) -> float:
        return self._clock() * 1000.0

    def lookup(self, signature: str) -> dict | None:
        """None when the approval was not used. Otherwise the answer to give: the first one inside the retry window, a refusal after it."""
        with self._lock:
            self._forget_old()
            record = self._records.get(signature)
            if record is None:
                return None
            first_ms, _expires, answer = record
            return dict(answer) if self._now_ms() - first_ms <= RETRY_GRACE_MS else dict(ALREADY_USED)

    def remember(self, signature: str, expires_at_ms: int, answer: dict) -> None:
        with self._lock:
            self._forget_old()
            self._records.setdefault(signature, (self._now_ms(), expires_at_ms, dict(answer)))
            while len(self._records) > self._max:
                self._records.popitem(last=False)

    def _forget_old(self) -> None:
        now = self._now_ms()
        for signature in [s for s, (_first, expires, _answer) in self._records.items() if expires < now]:
            del self._records[signature]

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)
