# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/safety_gate.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A safety check before a plan is released: the planner asks HYDRA-UMC-SAFETY-ZONES for its last verdict (`GET /state`) and
releases nothing unless that verdict is READY.

The gate is closed by default in the one way that matters: when it is switched on, anything that is not a clear, fresh READY is a
refusal. The safety service not answering, an answer that is not a verdict, a verdict that is old, one whose signature is missing or
does not match, one older than a verdict already seen (a replay), and every state other than READY (WARNING, INHIBITED, SAFE_STOP,
FAULT...) all keep the plan from being released, with the reason. A person's approval is still required: this gate adds a second
condition, it never replaces the first.

The switch is `safety_gate.enabled` in the configuration file and is OFF by default, so a planner without a safety service behaves
as it always did. With it on, signatures are required by default (`require_signature`), because an unsigned "READY" can be answered
by anyone who can reach the network. Every value (address, timeout, age limit, key file, algorithm) comes from the configuration file.
The HMAC key and the bearer token are read from files and never printed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .recovery import CONFIG_ENV

HMAC = "HMAC-SHA256"
ED25519 = "Ed25519"
ALGORITHMS = (HMAC, ED25519)
# Must stay equal to the domain string under which HYDRA-UMC-SAFETY-ZONES signs its verdicts.
DOMAIN = b"hydra-umc-safety-state-v1\n"
MIN_KEY_CHARS = 32
MAX_RESPONSE_BYTES = 64 * 1024
READY = "READY"
_KNOWN_KEYS = {"enabled", "url", "token_file", "timeout_s", "max_age_ms", "require_signature", "algorithm", "key_file", "key_id", "start_without_key"}


class SafetyGateConfigError(ValueError):
    """The `safety_gate` section of the configuration file, or a key file it names, cannot be used."""


@dataclass(frozen=True)
class SafetyGatePolicy:
    """Settings of the gate. `enabled` is the switch: off (the default) the gate does not exist and /release answers as before."""

    enabled: bool = False
    url: str = "http://127.0.0.1:8108"
    token_file: str = ""
    timeout_s: float = 2.0
    max_age_ms: int = 2000
    require_signature: bool = True
    algorithm: str = HMAC
    key_file: str = ""
    key_id: str = ""
    # Deployment profile: when true, a key or token file that cannot be read does not stop the planner from starting; the gate then
    # refuses every release with the reason (the planner keeps answering /decompose and the proposals). Off: a bad file is an error at start.
    start_without_key: bool = False

    def __post_init__(self) -> None:
        for name in ("enabled", "require_signature", "start_without_key"):
            if not isinstance(getattr(self, name), bool):
                raise SafetyGateConfigError(f"safety_gate.{name} must be true or false")
        if not isinstance(self.url, str) or urlparse(self.url).scheme not in ("http", "https") or not urlparse(self.url).hostname:
            raise SafetyGateConfigError("safety_gate.url must be an http(s) address")
        for name in ("token_file", "key_file", "key_id"):
            if not isinstance(getattr(self, name), str):
                raise SafetyGateConfigError(f"safety_gate.{name} must be text")
        timeout = self.timeout_s
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
            raise SafetyGateConfigError("safety_gate.timeout_s must be a number above 0 and at most 30")
        age = self.max_age_ms
        if isinstance(age, bool) or not isinstance(age, int) or not 1 <= age <= 60_000:
            raise SafetyGateConfigError("safety_gate.max_age_ms must be a whole number from 1 to 60000")
        if self.algorithm not in ALGORITHMS:
            raise SafetyGateConfigError(f"safety_gate.algorithm must be one of {', '.join(ALGORITHMS)}")
        if self.enabled and self.require_signature and not self.key_file:
            raise SafetyGateConfigError("safety_gate.key_file is required while safety_gate.require_signature is true")


def load_gate_policy(path: str | os.PathLike[str] | None = None) -> SafetyGatePolicy:
    """The `safety_gate` policy of the file `path`, or of the file named by the planner's configuration variable, or the default (off)."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return SafetyGatePolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SafetyGateConfigError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise SafetyGateConfigError(f"{chosen} must hold a JSON object")
    section = data.get("safety_gate", {})
    if not isinstance(section, dict):
        raise SafetyGateConfigError("safety_gate must be a JSON object")
    unknown = sorted(set(section) - _KNOWN_KEYS)
    if unknown:
        raise SafetyGateConfigError(f"safety_gate has unknown keys: {', '.join(unknown)}")
    return SafetyGatePolicy(**section)


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str
    state: str = ""


def _message(state: dict, counter: int, key_id: str) -> bytes:
    body = {"state": state, "counter": counter, "key_id": key_id}
    return DOMAIN + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _age_ms(sdk_state: dict, now_ms: int) -> float | None:
    raw = sdk_state.get("timestamp_utc")
    if not isinstance(raw, str):
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return now_ms - stamp.timestamp() * 1000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None


def _http_fetch(url: str, token: str, timeout_s: float) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=timeout_s) as response:  # noqa: S310 - scheme checked by the policy
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("the answer is too large")
    return json.loads(raw)


class SafetyGate:
    """Asks the safety service whether the cell is READY. `check()` never raises: any failure is a refusal."""

    def __init__(
        self,
        policy: SafetyGatePolicy,
        *,
        key: bytes | None = None,
        public_key: object | None = None,
        token: str = "",
        fetch: Callable[[str, str, float], object] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.policy = policy
        self._key = key
        self._public_key = public_key
        self._token = token
        self._fetch = fetch or _http_fetch
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._last_counter = 0
        self._lock = threading.Lock()

    @classmethod
    def from_policy(cls, policy: SafetyGatePolicy) -> "SafetyGate | None":
        """The gate of a policy, or None while the switch is off. Reads the key and the token once; a file that cannot be used is an error at start."""
        if not policy.enabled:
            return None
        try:
            return cls._build(policy)
        except SafetyGateConfigError as error:
            if policy.start_without_key:
                return ClosedGate(policy, str(error))
            raise

    @classmethod
    def _build(cls, policy: SafetyGatePolicy) -> "SafetyGate":
        key: bytes | None = None
        public_key: object | None = None
        if policy.key_file:
            if policy.algorithm == HMAC:
                try:
                    text = Path(policy.key_file).read_text(encoding="utf-8").strip()
                except OSError as error:
                    raise SafetyGateConfigError(f"cannot read the safety key file: {error.strerror or type(error).__name__}") from error
                if len(text) < MIN_KEY_CHARS:
                    raise SafetyGateConfigError(f"the safety key must hold at least {MIN_KEY_CHARS} characters")
                key = text.encode("utf-8")
            else:
                try:
                    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
                    from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: PLC0415
                except ImportError as error:
                    raise SafetyGateConfigError("Ed25519 needs the cryptography package (pip install cryptography)") from error
                try:
                    public_key = serialization.load_pem_public_key(Path(policy.key_file).read_bytes())
                except (OSError, ValueError, TypeError) as error:
                    raise SafetyGateConfigError("the safety public key file cannot be read as a PEM public key") from error
                if not isinstance(public_key, ed25519.Ed25519PublicKey):
                    raise SafetyGateConfigError("the safety public key file does not hold an Ed25519 key")
        token = ""
        if policy.token_file:
            try:
                token = Path(policy.token_file).read_text(encoding="utf-8").splitlines()[0].strip()
            except (OSError, IndexError) as error:
                raise SafetyGateConfigError("cannot read the safety token file") from error
        return cls(policy, key=key, public_key=public_key, token=token)

    def check(self) -> GateResult:
        try:
            return self._check()
        except Exception as error:  # noqa: BLE001 - fail closed: whatever went wrong is a refusal
            return GateResult(False, f"the safety check failed ({type(error).__name__})")

    def _check(self) -> GateResult:
        policy = self.policy
        try:
            answer = self._fetch(policy.url.rstrip("/") + "/state", self._token, float(policy.timeout_s))
        except (OSError, ValueError, urllib.error.URLError):
            return GateResult(False, "the safety service did not answer")
        if not isinstance(answer, dict) or not isinstance(answer.get("sdkSafetyState"), dict):
            return GateResult(False, "the safety service did not send a verdict")
        sdk_state: dict = answer["sdkSafetyState"]
        now = self._clock_ms()
        age = _age_ms(sdk_state, now)
        if age is None:
            return GateResult(False, "the verdict has no readable time")
        if age > policy.max_age_ms or age < -policy.max_age_ms:
            return GateResult(False, f"the verdict is {int(age)} ms old (limit {policy.max_age_ms} ms)")
        counter = 0
        if policy.require_signature:
            ok, why, counter = self._verify(sdk_state, answer.get("sdkSafetyStateSignature"))
            if not ok:
                return GateResult(False, why)
        state = sdk_state.get("state")
        if not isinstance(state, str):
            return GateResult(False, "the verdict has no state")
        if state != READY:
            return GateResult(False, f"the safety state is {state}, not {READY}", state)
        if counter:
            with self._lock:
                self._last_counter = max(self._last_counter, counter)
        return GateResult(True, "", state)

    def _verify(self, sdk_state: dict, signature: object) -> tuple[bool, str, int]:
        if not isinstance(signature, dict):
            return False, "the verdict is not signed", 0
        if signature.get("alg") != self.policy.algorithm:
            return False, "the verdict is signed with another algorithm than the one configured", 0
        counter, sig, kid = signature.get("counter"), signature.get("sig"), signature.get("key_id")
        if not isinstance(counter, int) or isinstance(counter, bool) or counter < 1 or not isinstance(sig, str) or not isinstance(kid, str):
            return False, "the signature is malformed", 0
        if self.policy.key_id and kid != self.policy.key_id:
            return False, "the signature was made with another key id", 0
        message = _message(sdk_state, counter, kid)
        if self.policy.algorithm == HMAC:
            if self._key is None or not hmac.compare_digest(hmac.new(self._key, message, hashlib.sha256).hexdigest(), sig):
                return False, "the signature does not match", 0
        else:
            try:
                raw = bytes.fromhex(sig)
                if len(raw) != 64 or self._public_key is None:
                    raise ValueError
                self._public_key.verify(raw, message)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - a bad signature, a bad key and a malformed value are all "does not match"
                return False, "the signature does not match", 0
        with self._lock:
            if counter < self._last_counter:
                return False, "the verdict is older than one already seen (replay)", 0
        return True, "", counter


class ClosedGate(SafetyGate):
    """The gate of a deployment whose key or token file cannot be used: it exists, so /release is still guarded, and it refuses every release."""

    def __init__(self, policy: SafetyGatePolicy, why: str) -> None:
        super().__init__(policy)
        self.why = why

    def check(self) -> GateResult:
        return GateResult(False, f"the safety gate cannot verify verdicts: {self.why}")
