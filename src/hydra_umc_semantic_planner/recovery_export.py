# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/recovery_export.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Sends the outcomes of the recoveries to HYDRA-UMC-DATALAKE and, at start, reads them back, so the memory survives a restart.

It is OFF by default (`failure_memory.export.enabled`). It uses only the ingestion contract of the data lake (`POST /ingest/batch`, and
`GET /query` to read back): one sample per outcome, of kind `recovery_outcome`, with the field `component/error_code/action` and the value
1 (SUCCESS) or 0 (FAILURE). Nothing else leaves the machine: never the free text of a failure, never a name or an address.

The data lake is local by default (loopback). Another address needs a token file and TLS, or `allow_plaintext` said on purpose, like the
other clients of the ecosystem. The sending has its own thread, a bounded queue (the oldest sample is dropped when it is full) and a
bounded number of retries, so a slow or missing data lake never delays an answer of the planner.

What is read back is not trusted: a record that is malformed, from another source, in the future, older than `ttl_s` or not a failure is
ignored and counted. Only FAILURE records are taken back, so a reload can only make a recovery more cautious, never relax an escalation.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

LOOPBACK = ("127.0.0.1", "::1", "localhost")
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
BATCH = 50
MAX_PAGES = 20
PAGE_LIMIT = 1000
FUTURE_SKEW_S = 300
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_KNOWN_KEYS = {
    "enabled", "url", "token_file", "allow_plaintext", "source_id", "kind", "timeout_s", "queue_max", "retries", "retry_delay_s", "load_on_start",
}


class ExportConfigError(ValueError):
    """The `failure_memory.export` section of the configuration file, or its token file, cannot be used."""


@dataclass(frozen=True)
class ExportPolicy:
    enabled: bool = False
    url: str = "http://127.0.0.1:8095"
    token_file: str = ""
    allow_plaintext: bool = False
    source_id: str = "semantic-planner"
    kind: str = "recovery_outcome"
    timeout_s: float = 3.0
    queue_max: int = 500
    retries: int = 3
    retry_delay_s: float = 2.0
    load_on_start: bool = True

    def __post_init__(self) -> None:
        for name in ("enabled", "allow_plaintext", "load_on_start"):
            if not isinstance(getattr(self, name), bool):
                raise ExportConfigError(f"failure_memory.export.{name} must be true or false")
        for name in ("url", "token_file", "source_id", "kind"):
            if not isinstance(getattr(self, name), str):
                raise ExportConfigError(f"failure_memory.export.{name} must be text")
        parsed = urlparse(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ExportConfigError("failure_memory.export.url must be an http(s) address")
        if not _NAME.match(self.source_id) or not _NAME.match(self.kind):
            raise ExportConfigError("failure_memory.export.source_id and kind must be short names")
        for name, high in (("timeout_s", 30), ("retry_delay_s", 600)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= high:
                raise ExportConfigError(f"failure_memory.export.{name} must be a number above 0 and at most {high}")
        for name, low, high in (("queue_max", 1, 10000), ("retries", 0, 10)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ExportConfigError(f"failure_memory.export.{name} must be a whole number from {low} to {high}")
        if self.enabled and (parsed.hostname or "") not in LOOPBACK:
            if not self.token_file:
                raise ExportConfigError("failure_memory.export.token_file is required for a data lake that is not on this machine")
            if parsed.scheme != "https" and not self.allow_plaintext:
                raise ExportConfigError("a data lake that is not on this machine needs https, or failure_memory.export.allow_plaintext set on purpose")


def parse_export_policy(section: object) -> ExportPolicy:
    if section is None:
        return ExportPolicy()
    if not isinstance(section, dict):
        raise ExportConfigError("failure_memory.export must be a JSON object")
    unknown = sorted(set(section) - _KNOWN_KEYS)
    if unknown:
        raise ExportConfigError(f"failure_memory.export has unknown keys: {', '.join(unknown)}")
    return ExportPolicy(**section)


def field_name(component: str, error_code: str, action: str) -> str:
    return f"{component}/{error_code}/{action}"


Transport = Callable[[str, str, str, "bytes | None", float], "tuple[int, dict[str, str], object]"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None


def _http(method: str, url: str, token: str, body: bytes | None, timeout_s: float) -> tuple[int, dict[str, str], object]:
    request = urllib.request.Request(url, data=body, method=method, headers={"Accept": "application/json"})
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout_s) as response:  # noqa: S310 - scheme checked by the policy
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status, headers = response.status, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as error:
        return error.code, {}, None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("the answer is too large")
    return status, headers, json.loads(raw) if raw else None


class RecoveryExporter:
    """Bounded queue, own thread, bounded retries. `enqueue()` never blocks and never raises."""

    def __init__(
        self,
        policy: ExportPolicy,
        *,
        token: str = "",
        transport: Transport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.policy = policy
        self._token = token
        self._transport = transport or _http
        self._clock = clock
        self._queue: deque[dict] = deque()
        self._cond = threading.Condition()
        self._stop = False
        self._sleeper = sleep
        self._sequence = 0
        self._thread: threading.Thread | None = None
        self.sent = 0
        self.dropped = 0
        self.failed = 0
        self.ignored_on_load = 0
        self.loaded = 0

    @classmethod
    def from_policy(cls, policy: ExportPolicy) -> "RecoveryExporter | None":
        if not policy.enabled:
            return None
        token = ""
        if policy.token_file:
            try:
                token = Path(policy.token_file).read_text(encoding="utf-8").splitlines()[0].strip()
            except (OSError, IndexError) as error:
                raise ExportConfigError("cannot read the data lake token file") from error
        return cls(policy, token=token)

    # -- sending ---------------------------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="recovery-export", daemon=True)
            self._thread.start()

    def stop(self, wait_s: float = 2.0) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(wait_s)

    def enqueue(self, component: str, error_code: str, action: str, outcome: str, when_s: float | None = None) -> None:
        stamp = int((self._clock() if when_s is None else when_s) * 1000)
        with self._cond:
            self._sequence += 1
            sample = {
                "sourceId": self.policy.source_id,
                "kind": self.policy.kind,
                "timestamp": stamp,
                "sequence": self._sequence,
                "fields": {field_name(component, error_code, action): 1 if outcome == "SUCCESS" else 0},
            }
            if len(self._queue) >= self.policy.queue_max:
                self._queue.popleft()
                self.dropped += 1
            self._queue.append(sample)
            self._cond.notify()

    def pending(self) -> int:
        with self._cond:
            return len(self._queue)

    def flush(self, wait_s: float = 5.0) -> bool:
        """Waits until the queue is empty (for tests and for a clean stop). True when it is."""
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            with self._cond:
                if not self._queue and self._inflight == 0:
                    return True
            time.sleep(0.01)
        return False

    _inflight = 0

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._stop:
                    self._cond.wait()
                if self._stop and not self._queue:
                    return
                batch = [self._queue.popleft() for _ in range(min(BATCH, len(self._queue)))]
                self._inflight = len(batch)
            try:
                self._send(batch)
            finally:
                with self._cond:
                    self._inflight = 0
            if self._stop:
                with self._cond:
                    self.dropped += len(self._queue)
                    self._queue.clear()
                return

    def _wait(self, seconds: float) -> None:
        if self._sleeper is not None:
            self._sleeper(seconds)
            return
        with self._cond:
            if not self._stop:
                self._cond.wait(seconds)

    def _send(self, batch: list[dict]) -> None:
        url = self.policy.url.rstrip("/") + "/ingest/batch"
        body = json.dumps({"samples": batch}, separators=(",", ":")).encode("utf-8")
        for attempt in range(self.policy.retries + 1):
            try:
                status, _, _ = self._transport("POST", url, self._token, body, float(self.policy.timeout_s))
            except (OSError, ValueError, urllib.error.URLError):
                status = 0
            if status == 202:
                self.sent += len(batch)
                return
            if status in (400, 401, 403, 413):  # the data lake will not take it however many times it is sent
                break
            if attempt < self.policy.retries and not self._stop:
                self._wait(float(self.policy.retry_delay_s))
            elif self._stop:
                break
        self.failed += len(batch)

    # -- reading back ------------------------------------------------------------------------------------------------------------
    def load(self, ttl_s: int, max_records: int) -> list[tuple[float, str, str, str, str]]:
        """The FAILURE records the data lake still holds, as (seconds, component, error_code, action, "FAILURE"), oldest first.

        Never raises: a data lake that cannot be reached gives an empty list. Whatever is not a clean record is counted in
        `ignored_on_load` and dropped.
        """
        now = self._clock()
        params: dict[str, str | int] = {
            "sourceId": self.policy.source_id,
            "kind": self.policy.kind,
            "start": int((now - ttl_s) * 1000),
            "limit": PAGE_LIMIT,
        }
        records: list[tuple[float, str, str, str, str]] = []
        cursor = ""
        for _ in range(MAX_PAGES):
            query = dict(params)
            if cursor:
                query["cursor"] = cursor
            url = self.policy.url.rstrip("/") + "/query?" + urlencode(query)
            try:
                status, headers, data = self._transport("GET", url, self._token, None, float(self.policy.timeout_s))
            except (OSError, ValueError, urllib.error.URLError):
                break
            if status != 200 or not isinstance(data, list):
                break
            for item in data:
                record = self._clean(item, now, ttl_s)
                if record is None:
                    self.ignored_on_load += 1
                elif record[4] == "FAILURE":
                    records.append(record)
                    self.loaded += 1
            cursor = headers.get("x-next-cursor", "")
            if not cursor:
                break
        records.sort(key=lambda r: r[0])
        return records[-max_records:]

    def _clean(self, item: object, now: float, ttl_s: int) -> tuple[float, str, str, str, str] | None:
        if not isinstance(item, dict):
            return None
        if item.get("sourceId") != self.policy.source_id or item.get("kind") != self.policy.kind:
            return None
        stamp, value, name = item.get("timestamp"), item.get("value"), item.get("field")
        if isinstance(stamp, bool) or not isinstance(stamp, int) or isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        seconds = stamp / 1000
        if seconds <= now - ttl_s or seconds > now + FUTURE_SKEW_S:
            return None
        if value not in (0, 1) or not isinstance(name, str):
            return None
        parts = name.split("/")
        if len(parts) != 3 or not all(_NAME.match(p) for p in parts):
            return None
        return seconds, parts[0], parts[1], parts[2], "SUCCESS" if value == 1 else "FAILURE"
