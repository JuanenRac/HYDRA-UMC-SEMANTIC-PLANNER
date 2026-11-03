# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_property_safety_gate.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Property-based tests of the safety gate: nothing is released without a fresh, signed, newer READY verdict.

The cases come from a small generator with a FIXED seed (``random.Random``), so a run is the same everywhere and no test dependency is needed; the number of cases per
property is bounded to keep the file in a few seconds. The safety service is a stand-in function (the ``fetch`` argument of the gate), so no network is used.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import random
import urllib.error

import pytest

from hydra_umc_semantic_planner.safety_gate import (
    DOMAIN,
    SafetyGate,
    SafetyGateConfigError,
    SafetyGatePolicy,
)

SEED = 7001
CASES = 500
KEY = b"s" * 32
NOW_MS = 1_900_000_000_000
POLICY = SafetyGatePolicy(enabled=True, key_file="unused", max_age_ms=2000)


def rng(name: str) -> random.Random:
    return random.Random(f"{SEED}:{name}")


def iso(ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def verdict(state: str = "READY", at_ms: int = NOW_MS, counter: int = 5, key: bytes = KEY, key_id: str = "default") -> dict:
    sdk = {"schema_version": "1.0", "state": state, "source": "hydra-umc-safety-zones", "timestamp_utc": iso(at_ms)}
    body = {"state": sdk, "counter": counter, "key_id": key_id}
    message = DOMAIN + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    sig = hmac.new(key, message, hashlib.sha256).hexdigest()
    return {"sdkSafetyState": sdk, "sdkSafetyStateSignature": {"alg": "HMAC-SHA256", "key_id": key_id, "counter": counter, "sig": sig}}


def gate_for(answer, policy: SafetyGatePolicy = POLICY, now: int = NOW_MS) -> SafetyGate:
    def fetch(url: str, token: str, timeout: float) -> object:
        if isinstance(answer, BaseException):
            raise answer
        return copy.deepcopy(answer)

    return SafetyGate(policy, key=KEY, fetch=fetch, clock_ms=lambda: now)


def test_the_untouched_fresh_ready_is_the_only_thing_released():
    assert gate_for(verdict()).check().allowed
    r = rng("tamper")
    for _ in range(CASES):
        answer = verdict()
        sdk, sig = answer["sdkSafetyState"], answer["sdkSafetyStateSignature"]
        what = r.randrange(10)
        if what == 0:
            sdk["state"] = r.choice(["WARNING", "INHIBITED", "SAFE_STOP", "FAULT", "ready", "READY ", "", None, 1, ["READY"]])
        elif what == 1:
            sdk["source"] = "someone-else"
        elif what == 2:
            sig["counter"] += r.choice([-1, 1, 99])
        elif what == 3:
            sig["sig"] = sig["sig"][:-1] + ("0" if sig["sig"][-1] != "0" else "1")
        elif what == 4:
            sig["key_id"] = r.choice(["other", ""])
        elif what == 5:
            sig["alg"] = r.choice(["none", "Ed25519", "hmac-sha256", None, 3])
        elif what == 6:
            sig.pop(r.choice(["alg", "key_id", "counter", "sig"]))
        elif what == 7:
            answer.pop("sdkSafetyStateSignature")
        elif what == 8:
            sig["counter"] = r.choice([0, -1, True, 1.5, "5", None])
        else:
            answer = r.choice([None, [], "READY", 1, {}, {"sdkSafetyState": "READY"}, {"sdkSafetyState": None}, {"state": "READY"}])
        result = gate_for(answer).check()
        assert not result.allowed and result.reason, (what, answer)


def test_the_age_limit_is_exact_in_both_directions():
    r = rng("age")
    for _ in range(CASES):
        limit = r.choice([1, 100, 2000, 60000])
        policy = SafetyGatePolicy(enabled=True, key_file="unused", max_age_ms=limit)
        skew = r.randrange(-2 * limit - 2, 2 * limit + 3)
        allowed = gate_for(verdict(at_ms=NOW_MS), policy, now=NOW_MS + skew).check().allowed
        assert allowed == (-limit <= skew <= limit), (limit, skew)


def test_a_timestamp_that_cannot_be_read_is_a_refusal():
    r = rng("stamp")
    for _ in range(CASES):
        answer = verdict()
        answer["sdkSafetyState"]["timestamp_utc"] = r.choice([None, 5, "", "yesterday", "2030-13-45T00:00:00Z", [], "x" * 400, "NaN"])
        assert not gate_for(answer).check().allowed


def test_a_replayed_verdict_is_refused_and_the_counter_never_goes_back():
    r = rng("replay")
    for _ in range(40):
        gate = gate_for(verdict(counter=10))
        assert gate.check().allowed
        highest = 10
        for _ in range(12):
            counter = r.randrange(1, 20)
            gate._fetch = lambda url, token, timeout, c=counter: verdict(counter=c)
            allowed = gate.check().allowed
            assert allowed == (counter >= highest), (counter, highest)
            highest = max(highest, counter)


def test_a_failure_of_the_service_or_a_bad_answer_never_raises_and_never_releases():
    r = rng("failure")
    errors = [OSError("down"), urllib.error.URLError("x"), TimeoutError(), ValueError("json"), RuntimeError("boom"), KeyError("k"), RecursionError()]
    for _ in range(CASES):
        answer = r.choice(errors + [None, 5, "x", [], {}, {"sdkSafetyState": {}}, {"sdkSafetyState": {"state": "READY"}}, verdict(state="READY", at_ms=NOW_MS - 10**9)])
        result = gate_for(answer).check()
        assert not result.allowed and result.reason


def test_every_state_other_than_ready_is_refused_even_when_perfectly_signed():
    r = rng("states")
    for _ in range(CASES):
        state = r.choice(["WARNING", "INHIBITED", "SAFE_STOP", "FAULT", "DANGER", "OK", "Ready", "".join(r.choice("ABC_") for _ in range(r.randrange(1, 9)))])
        result = gate_for(verdict(state=state)).check()
        assert not result.allowed
        assert result.state == state


def test_a_signature_made_with_another_key_is_refused():
    r = rng("keys")
    for _ in range(100):
        other = bytes(r.randrange(256) for _ in range(32))
        if other != KEY:
            assert not gate_for(verdict(key=other)).check().allowed


def test_the_configured_key_id_must_match():
    policy = SafetyGatePolicy(enabled=True, key_file="unused", key_id="line-1")
    assert gate_for(verdict(key_id="line-1"), policy).check().allowed
    for kid in ("default", "line-2", "Line-1", "line-1 "):
        assert not gate_for(verdict(key_id=kid), policy).check().allowed


def test_the_policy_refuses_every_value_outside_its_range():
    r = rng("policy")
    odd = [None, True, 0, -1, 0.0, 31, 30.5, 60001, "5", [], "http", "ftp://x", "http://", ""]
    for _ in range(CASES):
        kwargs = {"enabled": True, "key_file": "k"}
        field = r.choice(["timeout_s", "max_age_ms", "url", "algorithm", "require_signature", "enabled"])
        kwargs[field] = r.choice(odd + ["http://127.0.0.1:8108", 2, 2.5, 1, 60000, "HMAC-SHA256", "Ed25519", "md5", False])
        valid = {
            "timeout_s": lambda v: not isinstance(v, bool) and isinstance(v, (int, float)) and 0 < v <= 30,
            "max_age_ms": lambda v: not isinstance(v, bool) and isinstance(v, int) and 1 <= v <= 60000,
            "url": lambda v: isinstance(v, str) and v.split("://")[0] in ("http", "https") and "://" in v and len(v.split("://", 1)[1]) > 0,
            "algorithm": lambda v: v in ("HMAC-SHA256", "Ed25519"),
            "require_signature": lambda v: isinstance(v, bool),
            "enabled": lambda v: isinstance(v, bool),
        }[field](kwargs[field])
        try:
            SafetyGatePolicy(**kwargs)
        except SafetyGateConfigError:
            assert not valid, kwargs
        else:
            assert valid, kwargs
    with pytest.raises(SafetyGateConfigError):
        SafetyGatePolicy(enabled=True, require_signature=True, key_file="")
    assert SafetyGate.from_policy(SafetyGatePolicy()) is None


# --- cases added after a mutation run (a mutant that survived is a behaviour nothing checked) ---------------------------------------------------------
def test_the_reasons_of_a_refused_policy_and_a_refused_answer_are_the_documented_ones():
    def why(**kwargs):
        with pytest.raises(SafetyGateConfigError) as caught:
            SafetyGatePolicy(**{"enabled": True, "key_file": "k", **kwargs})
        return str(caught.value)

    assert why(require_signature="yes") == "safety_gate.require_signature must be true or false"
    assert why(url="ftp://h") == "safety_gate.url must be an http(s) address"
    assert why(token_file=5) == "safety_gate.token_file must be text"
    assert why(timeout_s=0) == "safety_gate.timeout_s must be a number above 0 and at most 30"
    assert why(max_age_ms=0) == "safety_gate.max_age_ms must be a whole number from 1 to 60000"
    assert why(algorithm="md5") == "safety_gate.algorithm must be one of HMAC-SHA256, Ed25519"
    assert why(key_file="") == "safety_gate.key_file is required while safety_gate.require_signature is true"
    assert gate_for(ValueError("x")).check().reason == "the safety service did not answer"
    assert gate_for(RuntimeError("boom")).check().reason == "the safety check failed (RuntimeError)"
    assert gate_for([1]).check().reason == "the safety service did not send a verdict"
    assert gate_for(5).check().reason == "the safety service did not send a verdict"


def test_the_edges_of_the_policy_are_inside():
    for url in ("http://h", "https://h", "https://h:8443/x"):
        SafetyGatePolicy(enabled=True, key_file="k", url=url)
    SafetyGatePolicy(enabled=True, key_file="k", timeout_s=30)
    SafetyGatePolicy(enabled=True, key_file="k", timeout_s=0.001)
    SafetyGatePolicy(enabled=True, key_file="k", max_age_ms=60000)
    SafetyGatePolicy(enabled=True, key_file="k", max_age_ms=1)
    for bad in (30.0001, 31):
        with pytest.raises(SafetyGateConfigError):
            SafetyGatePolicy(enabled=True, key_file="k", timeout_s=bad)


def test_a_signed_verdict_with_non_ascii_text_and_the_ways_of_writing_a_time_are_read_as_signed():
    sdk = {"schema_version": "1.0", "state": "READY", "source": "café-über", "timestamp_utc": iso(NOW_MS)}
    body = {"state": sdk, "counter": 9, "key_id": "default"}
    message = DOMAIN + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    sig = {"alg": "HMAC-SHA256", "key_id": "default", "counter": 9, "sig": hmac.new(KEY, message, hashlib.sha256).hexdigest()}
    assert gate_for({"sdkSafetyState": sdk, "sdkSafetyStateSignature": sig}).check().allowed
    # "Z", an explicit offset and a time with no zone (taken as UTC) all name the same instant
    from datetime import datetime, timezone

    instant = datetime.fromtimestamp(NOW_MS / 1000, tz=timezone.utc)
    for text in (instant.isoformat().replace("+00:00", "Z"), instant.isoformat(), instant.replace(tzinfo=None).isoformat(), instant.isoformat().replace("+00:00", "+00:00")):
        answer = verdict()
        answer["sdkSafetyState"]["timestamp_utc"] = text
        body = {"state": answer["sdkSafetyState"], "counter": 5, "key_id": "default"}
        msg = DOMAIN + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        answer["sdkSafetyStateSignature"]["sig"] = hmac.new(KEY, msg, hashlib.sha256).hexdigest()
        assert gate_for(answer).check().allowed, text
    # an offset that is not UTC is converted: the same wall-clock text one hour off is an hour old
    shifted = verdict()
    shifted["sdkSafetyState"]["timestamp_utc"] = instant.replace(tzinfo=None).isoformat() + "+01:00"
    assert not gate_for(shifted).check().allowed


def test_a_trailing_slash_of_the_address_does_not_double_the_path():
    seen = []

    def fetch(url, token, timeout):
        seen.append((url, token, timeout))
        return verdict()

    for base in ("http://127.0.0.1:8108", "http://127.0.0.1:8108/", "http://127.0.0.1:8108//"):
        SafetyGate(SafetyGatePolicy(enabled=True, key_file="k", url=base, timeout_s=3), key=KEY, token="tok", fetch=fetch, clock_ms=lambda: NOW_MS).check()
    assert [u for u, _, _ in seen] == ["http://127.0.0.1:8108/state"] * 3
    assert seen[0] == ("http://127.0.0.1:8108/state", "tok", 3.0)


def test_the_other_refusals_say_why():
    unreadable = verdict()
    unreadable["sdkSafetyState"]["timestamp_utc"] = "yesterday"
    assert gate_for(unreadable).check().reason == "the verdict has no readable time"
    assert gate_for(verdict(at_ms=NOW_MS - 5000)).check().reason == "the verdict is 5000 ms old (limit 2000 ms)"
    sdk = {"schema_version": "1.0", "source": "x", "timestamp_utc": iso(NOW_MS)}   # signed, fresh, but with no state
    message = DOMAIN + json.dumps({"state": sdk, "counter": 5, "key_id": "default"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    no_state = {"sdkSafetyState": sdk, "sdkSafetyStateSignature": {"alg": "HMAC-SHA256", "key_id": "default", "counter": 5, "sig": hmac.new(KEY, message, hashlib.sha256).hexdigest()}}
    assert not gate_for(no_state).check().allowed
    assert gate_for(no_state).check().reason == "the verdict has no state"
    assert gate_for(verdict(state="WARNING")).check().reason == "the safety state is WARNING, not READY"
    unsigned = verdict()
    del unsigned["sdkSafetyStateSignature"]
    assert gate_for(unsigned).check().reason == "the verdict is not signed"
    other_alg = verdict()
    other_alg["sdkSafetyStateSignature"]["alg"] = "Ed25519"
    assert gate_for(other_alg).check().reason == "the verdict is signed with another algorithm than the one configured"
    bad = verdict()
    bad["sdkSafetyStateSignature"]["counter"] = 0
    assert gate_for(bad).check().reason == "the signature is malformed"
    assert gate_for(verdict()).check().reason == ""


def test_more_refusals_say_why_and_the_counter_one_is_valid():
    for odd in ("5", None, True, 1.5, 0, -3):
        answer = verdict()
        answer["sdkSafetyStateSignature"]["counter"] = odd
        assert gate_for(answer).check().reason == "the signature is malformed", odd
    assert gate_for(verdict(counter=1)).check().allowed
    policy = SafetyGatePolicy(enabled=True, key_file="unused", key_id="line-1")
    assert gate_for(verdict(key_id="other"), policy).check().reason == "the signature was made with another key id"
    forged = verdict()
    forged["sdkSafetyStateSignature"]["sig"] = "0" * 64
    assert gate_for(forged).check().reason == "the signature does not match"


def test_the_ed25519_path_accepts_only_a_signature_of_exactly_64_bytes_by_the_configured_key():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private = ed25519.Ed25519PrivateKey.generate()
    other = ed25519.Ed25519PrivateKey.generate()
    policy = SafetyGatePolicy(enabled=True, key_file="unused", algorithm="Ed25519")

    def signed(key, counter=5):
        sdk = {"schema_version": "1.0", "state": "READY", "source": "x", "timestamp_utc": iso(NOW_MS)}
        message = DOMAIN + json.dumps({"state": sdk, "counter": counter, "key_id": "default"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return {"sdkSafetyState": sdk, "sdkSafetyStateSignature": {"alg": "Ed25519", "key_id": "default", "counter": counter, "sig": key.sign(message).hex()}}

    public_key = private.public_key()

    def gate(answer):
        return SafetyGate(policy, public_key=public_key, fetch=lambda url, token, timeout: copy.deepcopy(answer), clock_ms=lambda: NOW_MS)

    assert gate(signed(private)).check().allowed
    assert gate(signed(private)).check().reason == ""
    wrong = gate(signed(other)).check()
    assert not wrong.allowed and wrong.reason == "the signature does not match"
    r = rng("ed")
    for _ in range(60):
        answer = signed(private)
        raw = bytearray(bytes.fromhex(answer["sdkSafetyStateSignature"]["sig"]))
        kind = r.randrange(4)
        if kind == 0:
            raw[r.randrange(64)] ^= 1 << r.randrange(8)
            text = bytes(raw).hex()
        elif kind == 1:
            text = bytes(raw[:-1]).hex()
        elif kind == 2:
            text = (bytes(raw) + b"\x00").hex()
        else:
            text = r.choice(["", "zz", "0" * 128, "g" * 128])
        answer["sdkSafetyStateSignature"]["sig"] = text
        result = gate(answer).check()
        assert not result.allowed and result.reason == "the signature does not match"
    # without a configured public key nothing is accepted
    assert not SafetyGate(policy, public_key=None, fetch=lambda url, token, timeout: signed(private), clock_ms=lambda: NOW_MS).check().allowed


def test_without_the_signature_requirement_the_counter_is_not_tracked_and_the_rest_still_applies():
    policy = SafetyGatePolicy(enabled=True, require_signature=False)
    gate = gate_for(verdict(), policy)
    assert gate.check().allowed and gate._last_counter == 0
    for state in ("WARNING", "INHIBITED", "SAFE_STOP", "FAULT"):
        assert not gate_for(verdict(state=state), policy).check().allowed
    unsigned = verdict()
    del unsigned["sdkSafetyStateSignature"]
    assert gate_for(unsigned, policy).check().allowed
    unsigned["sdkSafetyState"]["timestamp_utc"] = iso(NOW_MS - 10_000)
    assert not gate_for(unsigned, policy).check().allowed


def test_a_replay_says_so():
    gate = gate_for(verdict(counter=10))
    assert gate.check().allowed
    gate._fetch = lambda url, token, timeout: verdict(counter=9)
    result = gate.check()
    assert not result.allowed and result.reason == "the verdict is older than one already seen (replay)"
