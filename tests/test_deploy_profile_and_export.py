# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_deploy_profile_and_export.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The deployment profile (safety gate on, key outside the repository) and the export of the recovery memory to a simulated data lake."""
from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from test_safety_gate_and_voice import KEY, _post, _release, fake_safety, planner

from hydra_umc_semantic_planner import main as main_module
from hydra_umc_semantic_planner.failure_memory import FailureMemory, FailureMemoryConfigError, FailureMemoryPolicy, load_memory_policy
from hydra_umc_semantic_planner.recovery_export import ExportConfigError, ExportPolicy, RecoveryExporter, parse_export_policy
from hydra_umc_semantic_planner.safety_gate import ClosedGate, SafetyGate, SafetyGateConfigError, load_gate_policy

PROFILE = Path(__file__).resolve().parent.parent / "configs" / "deploy-cm5.json"


def _profile(tmp_path: Path, url: str, key_file: str) -> Path:
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    data["safety_gate"]["url"] = url
    data["safety_gate"]["key_file"] = key_file
    target = tmp_path / "profile.json"
    target.write_text(json.dumps(data), encoding="utf-8")
    return target


def test_the_profile_turns_the_gate_on_and_the_general_default_stays_off() -> None:
    policy = load_gate_policy(PROFILE)
    assert policy.enabled is True and policy.require_signature is True and policy.start_without_key is True
    assert policy.key_file.startswith("/etc/")  # outside the repository
    assert load_gate_policy(PROFILE.parent / "semantic-planner.json").enabled is False


def test_gate_on_with_a_valid_signature_releases(tmp_path: Path) -> None:
    key_file = tmp_path / "safety.key"
    key_file.write_text(KEY.decode(), encoding="utf-8")
    with fake_safety() as (url, _):
        gate = SafetyGate.from_policy(load_gate_policy(_profile(tmp_path, url, str(key_file))))
        assert gate is not None and not isinstance(gate, ClosedGate)
        with planner(safety_gate=gate) as base:
            assert _release(base)["released"] is True


def test_gate_on_with_no_answer_refuses(tmp_path: Path) -> None:
    key_file = tmp_path / "safety.key"
    key_file.write_text(KEY.decode(), encoding="utf-8")
    gate = SafetyGate.from_policy(load_gate_policy(_profile(tmp_path, "http://127.0.0.1:1", str(key_file))))
    with planner(safety_gate=gate) as base:
        body = _release(base)
        assert body["released"] is False and "did not answer" in body["reason"]


def test_gate_on_with_an_invalid_signature_refuses(tmp_path: Path) -> None:
    key_file = tmp_path / "safety.key"
    key_file.write_text(KEY.decode(), encoding="utf-8")
    with fake_safety() as (url, server):
        server.key = b"x" * 32  # the safety service signs with another key
        gate = SafetyGate.from_policy(load_gate_policy(_profile(tmp_path, url, str(key_file))))
        with planner(safety_gate=gate) as base:
            body = _release(base)
            assert body["released"] is False and "signature does not match" in body["reason"]


def test_missing_key_keeps_the_planner_up_but_refuses_every_release(tmp_path: Path) -> None:
    gate = SafetyGate.from_policy(load_gate_policy(_profile(tmp_path, "http://127.0.0.1:1", str(tmp_path / "absent.key"))))
    assert isinstance(gate, ClosedGate)
    with planner(safety_gate=gate) as base:
        status, proposal = _post(f"{base}/decompose", {"goal": "assemble the housing"})
        assert status == 200 and proposal["executable"] is False  # proposals keep working
        body = _release(base)
        assert body["released"] is False and "cannot verify verdicts" in body["reason"]
        assert "safety key" in body["reason"] and str(tmp_path) not in body["reason"]  # the reason says what, never where


def test_missing_key_without_the_profile_switch_is_an_error_at_start(tmp_path: Path) -> None:
    config = tmp_path / "plain.json"
    config.write_text(json.dumps({"safety_gate": {"enabled": True, "key_file": str(tmp_path / "absent.key")}}), encoding="utf-8")
    with pytest.raises(SafetyGateConfigError):
        SafetyGate.from_policy(load_gate_policy(config))


def test_main_starts_with_the_profile_and_a_missing_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seen: dict = {}

    class Stop(Exception):
        pass

    def fake_server(*args: object) -> None:
        seen["gate"] = args[6]
        raise Stop

    original = main_module.SemanticPlannerServer
    main_module.SemanticPlannerServer = fake_server  # type: ignore[assignment,misc]
    try:
        with pytest.raises(Stop):
            main_module._run_serve("127.0.0.1", 0, config=str(_profile(tmp_path, "http://127.0.0.1:1", str(tmp_path / "absent.key"))))
    finally:
        main_module.SemanticPlannerServer = original  # type: ignore[misc]
    assert isinstance(seen["gate"], ClosedGate)


# -- export of the recovery memory ----------------------------------------------------------------------------------------------


class FakeLake(ThreadingHTTPServer):
    """What HYDRA-UMC-DATALAKE accepts on POST /ingest/batch and answers on GET /query (paged by X-Next-Cursor)."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _LakeHandler)
        self.points: list[dict] = []
        self.status = 202
        self.tokens: list[str] = []
        self.posts = 0
        self.page = 2


class _LakeHandler(BaseHTTPRequestHandler):
    server: FakeLake

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def _send(self, status: int, body: object, headers: dict[str, str] | None = None) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        self.server.posts += 1
        self.server.tokens.append(self.headers.get("Authorization", ""))
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.server.status != 202:
            self._send(self.server.status, {"error": "no"})
            return
        for sample in body["samples"]:
            for field, value in sample["fields"].items():
                self.server.points.append(
                    {"sourceId": sample["sourceId"], "kind": sample["kind"], "field": field, "timestamp": sample["timestamp"], "value": float(value)}
                )
        self._send(202, {"accepted": len(body["samples"]), "written": len(body["samples"])})

    def do_GET(self) -> None:  # noqa: N802
        params = parse_qs(urlparse(self.path).query)
        offset = int(params.get("cursor", ["0"])[0])
        window = self.server.points[offset: offset + self.server.page]
        headers = {"X-Next-Cursor": str(offset + self.server.page)} if offset + self.server.page < len(self.server.points) else {}
        self._send(200, window, headers)


@contextmanager
def fake_lake() -> Iterator[tuple[str, FakeLake]]:
    server = FakeLake()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _memory(url: str, now: list[float], **export: object) -> tuple[FailureMemory, RecoveryExporter]:
    export_policy = ExportPolicy(enabled=True, url=url, retries=1, retry_delay_s=0.05, timeout_s=2.0, **export)  # type: ignore[arg-type]
    memory = FailureMemory(FailureMemoryPolicy(enabled=True, min_failures=3, export=export_policy), clock=lambda: now[0])
    exporter = RecoveryExporter(export_policy, clock=lambda: now[0])
    memory.exporter = exporter
    exporter.start()
    return memory, exporter


def test_export_is_off_by_default_and_sends_nothing_else() -> None:
    assert FailureMemoryPolicy().export.enabled is False
    assert RecoveryExporter.from_policy(ExportPolicy()) is None
    now = [1_800_000_000.0]
    with fake_lake() as (url, lake):
        memory, exporter = _memory(url, now)
        memory.record("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")
        memory.record("arm-1", "E_TIMEOUT", "RETRY", "SUCCESS")
        assert exporter.flush()
        exporter.stop()
        assert [(p["sourceId"], p["kind"], p["field"], p["value"]) for p in lake.points] == [
            ("semantic-planner", "recovery_outcome", "arm-1/E_TIMEOUT/RETRY", 0.0),
            ("semantic-planner", "recovery_outcome", "arm-1/E_TIMEOUT/RETRY", 1.0),
        ]
        assert exporter.sent == 2 and not lake.tokens[0]


def test_a_restart_reads_failures_back_and_escalates() -> None:
    now = [1_800_000_000.0]
    with fake_lake() as (url, lake):
        memory, exporter = _memory(url, now)
        for _ in range(3):
            now[0] += 1
            memory.record("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")
        assert exporter.flush()
        exporter.stop()
        assert len(lake.points) == 3
        # a new process: empty memory, same data lake
        fresh_policy = FailureMemoryPolicy(enabled=True, min_failures=3, export=ExportPolicy(enabled=True, url=url))
        fresh = FailureMemory(fresh_policy, clock=lambda: now[0])
        reader = RecoveryExporter(fresh_policy.export, clock=lambda: now[0])
        assert fresh.merge_failures(reader.load(fresh_policy.ttl_s, fresh_policy.max_entries)) == 3
        assert fresh.counts("arm-1", "E_TIMEOUT", "RETRY") == (0, 3)
        assert fresh.merge_failures(reader.load(fresh_policy.ttl_s, fresh_policy.max_entries)) == 0  # no double counting


def test_what_is_read_back_is_not_trusted() -> None:
    now = [1_800_000_000.0]
    ms = int(now[0] * 1000)
    good = {"sourceId": "semantic-planner", "kind": "recovery_outcome", "field": "arm-1/E_TIMEOUT/RETRY", "timestamp": ms, "value": 0.0}
    with fake_lake() as (url, lake):
        lake.page = 100
        lake.points = [
            good,
            {**good, "value": 1.0},                                     # a success is never taken back (it could relax an escalation)
            {**good, "sourceId": "someone-else"},
            {**good, "kind": "joint_temp"},
            {**good, "field": "arm-1/E_TIMEOUT"},                       # not three parts
            {**good, "field": "arm 1/E/RETRY; rm -rf"},                 # not a short name
            {**good, "value": 0.5},
            {**good, "value": True},
            {**good, "timestamp": "now"},
            {**good, "timestamp": ms + 10_000_000},                     # in the future: would never expire
            {**good, "timestamp": ms - 8 * 24 * 3600 * 1000},           # older than the ttl
            "not an object",
            None,
        ]
        reader = RecoveryExporter(ExportPolicy(enabled=True, url=url), clock=lambda: now[0])
        records = reader.load(7 * 24 * 3600, 200)
        assert len(records) == 1 and records[0][1:] == ("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")
        assert reader.ignored_on_load == 11  # the 11 bad ones; the success is valid and is simply not taken back


def test_a_corrupt_record_never_relaxes_an_escalation() -> None:
    now = [1_800_000_000.0]
    memory = FailureMemory(FailureMemoryPolicy(enabled=True, min_failures=2), clock=lambda: now[0])
    memory.record("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")
    memory.record("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")
    before = memory.counts("arm-1", "E_TIMEOUT", "RETRY")
    ms = int(now[0] * 1000)
    ok_success = ("semantic-planner", "recovery_outcome")
    with fake_lake() as (url, lake):
        lake.points = [
            {"sourceId": ok_success[0], "kind": ok_success[1], "field": "arm-1/E_TIMEOUT/RETRY", "timestamp": ms + 1, "value": 1.0},
            {"sourceId": ok_success[0], "kind": ok_success[1], "field": "garbage", "timestamp": ms + 2, "value": 1.0},
        ]
        reader = RecoveryExporter(ExportPolicy(enabled=True, url=url), clock=lambda: now[0])
        memory.merge_failures(reader.load(memory.policy.ttl_s, memory.policy.max_entries))
    assert memory.counts("arm-1", "E_TIMEOUT", "RETRY") == before


def test_a_data_lake_that_is_down_does_not_block_and_is_counted() -> None:
    now = [1_800_000_000.0]
    memory, exporter = _memory("http://127.0.0.1:1", now, queue_max=3)
    for _ in range(10):
        memory.record("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")  # returns at once
    assert exporter.flush(10.0)
    exporter.stop()
    assert exporter.sent == 0 and exporter.failed + exporter.dropped == 10
    assert exporter.load(3600, 10) == []  # unreachable: empty, no exception


def test_retries_are_bounded_and_a_refusal_is_not_retried() -> None:
    now = [1_800_000_000.0]
    with fake_lake() as (url, lake):
        lake.status = 503
        memory, exporter = _memory(url, now)
        memory.record("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")
        assert exporter.flush()
        assert lake.posts == 2 and exporter.failed == 1  # one try and one retry (retries=1)
        lake.status = 401
        memory.record("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")
        assert exporter.flush()
        exporter.stop()
        assert lake.posts == 3  # a 401 is not sent again


def test_policy_rules_for_the_address_and_the_token(tmp_path: Path) -> None:
    ExportPolicy(enabled=True, url="http://127.0.0.1:8095")
    ExportPolicy(enabled=True, url="http://localhost:8095")
    with pytest.raises(ExportConfigError):
        ExportPolicy(enabled=True, url="http://192.168.0.5:8095", token_file="t")  # not local: TLS or allow_plaintext
    with pytest.raises(ExportConfigError):
        ExportPolicy(enabled=True, url="https://lake.example:8095")  # not local: a token is needed
    ExportPolicy(enabled=True, url="https://lake.example:8095", token_file="t")
    ExportPolicy(enabled=True, url="http://192.168.0.5:8095", token_file="t", allow_plaintext=True)
    for bad in ({"url": "ftp://x"}, {"queue_max": 0}, {"retries": 99}, {"timeout_s": 0}, {"kind": "bad kind"}, {"enabled": "yes"}, {"nope": 1}):
        with pytest.raises(ExportConfigError):
            parse_export_policy(bad)
    token = tmp_path / "token"
    token.write_text("secret-token-of-the-lake\n", encoding="utf-8")
    exporter = RecoveryExporter.from_policy(ExportPolicy(enabled=True, url="https://lake.example", token_file=str(token)))
    assert exporter is not None and exporter._token == "secret-token-of-the-lake"
    with pytest.raises(ExportConfigError) as caught:
        RecoveryExporter.from_policy(ExportPolicy(enabled=True, url="https://lake.example", token_file=str(tmp_path / "absent")))
    assert str(tmp_path) not in str(caught.value)


def test_the_token_is_sent_as_a_bearer_header() -> None:
    now = [1_800_000_000.0]
    with fake_lake() as (url, lake):
        policy = ExportPolicy(enabled=True, url=url, retry_delay_s=0.05)
        exporter = RecoveryExporter(policy, token="abc-token", clock=lambda: now[0])
        exporter.start()
        exporter.enqueue("arm-1", "E_TIMEOUT", "RETRY", "FAILURE")
        assert exporter.flush()
        exporter.stop()
        assert lake.tokens == ["Bearer abc-token"]


def test_configuration_file_section(tmp_path: Path) -> None:
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"failure_memory": {"enabled": True, "export": {"enabled": True, "retries": 5}}}), encoding="utf-8")
    policy = load_memory_policy(config)
    assert policy.export.enabled is True and policy.export.retries == 5 and policy.export.url == "http://127.0.0.1:8095"
    config.write_text(json.dumps({"failure_memory": {"export": 3}}), encoding="utf-8")
    with pytest.raises(ExportConfigError):
        load_memory_policy(config)
    assert issubclass(ExportConfigError, ValueError) and FailureMemoryConfigError
    assert load_memory_policy(PROFILE.parent / "semantic-planner.json").export.enabled is False
