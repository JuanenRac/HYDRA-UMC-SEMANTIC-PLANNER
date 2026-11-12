# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_docs_qa.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What the documentation says about an error code rides along with a recovery proposal, as advice that changes nothing."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hydra_umc_semantic_planner.api import SemanticPlannerServer
from hydra_umc_semantic_planner.docs_qa import (
    DocsQaClient,
    DocsQaConfigError,
    DocsQaPolicy,
    load_docs_qa_policy,
)
from hydra_umc_semantic_planner.recovery import FailureContext, propose_recovery


class _FakeDocsQa(BaseHTTPRequestHandler):
    """A DOCS-QA that answers from a table kept on the server object; records what it was asked."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.server.requests.append((self.path, self.headers.get("Authorization", "")))  # type: ignore[attr-defined]
        mode = self.server.mode  # type: ignore[attr-defined]
        if mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()
            return
        if mode == "error":
            self.send_response(500)
            self.end_headers()
            return
        if mode == "huge":
            body = b'{"matches": [], "pad": "' + b"x" * (70 * 1024) + b'"}'
        elif mode == "garbage":
            body = b"not json"
        elif mode == "empty":
            body = b'{"matches": []}'
        elif mode == "wrongshape":
            body = b'{"matches": "none"}'
        elif mode == "badentries":
            body = b'{"matches": [{"name": 5, "text": "x"}, "nope"]}'
        else:
            body = json.dumps({"matches": [
                {"name": "TIMEOUT", "value": 5, "text": "No answer\x1b[31m within\nthe deadline. " + "long " * 400, "citation": "docs/ERRORS.md#timeout"},
            ]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _docs_qa(mode: str = "ok"):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDocsQa)
    server.mode = mode  # type: ignore[attr-defined]
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _client(url: str, **overrides: object) -> DocsQaClient:
    client = DocsQaClient.from_policy(DocsQaPolicy(enabled=True, url=url, **overrides))  # type: ignore[arg-type]
    assert client is not None
    return client


def test_off_by_default_there_is_no_client() -> None:
    assert DocsQaPolicy().enabled is False
    assert DocsQaClient.from_policy(DocsQaPolicy()) is None


def test_a_known_code_is_answered_cleaned_and_cut() -> None:
    with _docs_qa() as (fake, url):
        result = _client(url, max_answer_chars=120).lookup("TIMEOUT")
    assert result["status"] == "answered"
    assert result["text"].startswith("TIMEOUT (0x05): No answer")
    assert "\x1b" not in result["text"] and "\n" not in result["text"]
    assert 100 < len(result["text"]) <= 120 and result["text"].endswith("...")
    assert result["sources"] == ["docs/ERRORS.md#timeout"]
    assert fake.requests == [("/error?code=TIMEOUT", "")]


def test_the_token_goes_in_the_header_and_never_in_the_answer(tmp_path: Path) -> None:
    token = tmp_path / "token.txt"
    token.write_text("s3cret-token\n", encoding="utf-8")
    with _docs_qa() as (fake, url):
        result = _client(url, token_file=str(token)).lookup("TIMEOUT")
    assert fake.requests[0][1] == "Bearer s3cret-token"
    assert "s3cret" not in json.dumps(result)


def test_an_unreadable_token_file_is_refused_when_the_client_is_built(tmp_path: Path) -> None:
    with pytest.raises(DocsQaConfigError):
        DocsQaClient.from_policy(DocsQaPolicy(enabled=True, token_file=str(tmp_path / "missing")))


@pytest.mark.parametrize("mode,status", [
    ("empty", "not_found"), ("error", "unavailable"), ("garbage", "unavailable"), ("huge", "unavailable"),
    ("wrongshape", "unavailable"), ("badentries", "unavailable"), ("redirect", "unavailable"),
])
def test_every_failure_is_a_status_never_an_exception(mode: str, status: str) -> None:
    with _docs_qa(mode) as (_, url):
        result = _client(url).lookup("TIMEOUT")
    assert result == {"status": status, "text": "", "sources": []}


def test_a_closed_port_is_unavailable() -> None:
    with _docs_qa() as (_, url):
        pass
    assert _client(url, timeout_s=0.5).lookup("TIMEOUT")["status"] == "unavailable"


def test_a_code_that_is_not_a_code_is_not_sent() -> None:
    with _docs_qa() as (fake, url):
        client = _client(url)
        for bad in ("", "a b", "../x", "A" * 65, "x&y=1", "x\n"):
            assert client.lookup(bad)["status"] == "not_found"
    assert fake.requests == []


@pytest.mark.parametrize("url", [
    "ftp://127.0.0.1", "http://", "http://user:pw@127.0.0.1", "http://127.0.0.1/?a=1", "http://example.com", "http://10.0.0.5:8109",
])
def test_an_unsafe_address_is_refused(url: str) -> None:
    with pytest.raises(DocsQaConfigError):
        DocsQaPolicy(enabled=True, url=url)


def test_a_remote_address_needs_the_explicit_switch() -> None:
    assert DocsQaPolicy(enabled=True, url="https://docs.example.com", allow_remote=True).url.startswith("https://")
    assert DocsQaPolicy(url="http://[::1]:8109").enabled is False
    assert DocsQaPolicy(url="http://localhost:8109").enabled is False


@pytest.mark.parametrize("field,value", [
    ("enabled", "yes"), ("allow_remote", 1), ("timeout_s", 0), ("timeout_s", 31), ("timeout_s", True),
    ("max_answer_chars", 10), ("max_answer_chars", 5000), ("max_answer_chars", True), ("token_file", 5),
])
def test_bad_values_are_refused(field: str, value: object) -> None:
    with pytest.raises(DocsQaConfigError):
        DocsQaPolicy(**{field: value})  # type: ignore[arg-type]


def test_the_configuration_file_section(tmp_path: Path) -> None:
    path = tmp_path / "planner.json"
    path.write_text(json.dumps({"docs_qa": {"enabled": True, "url": "http://127.0.0.1:9999", "timeout_s": 1}}), encoding="utf-8")
    policy = load_docs_qa_policy(path)
    assert policy.enabled and policy.url.endswith(":9999") and policy.timeout_s == 1
    path.write_text(json.dumps({"docs_qa": {"surprise": 1}}), encoding="utf-8")
    with pytest.raises(DocsQaConfigError, match="unknown keys"):
        load_docs_qa_policy(path)
    path.write_text(json.dumps({"docs_qa": []}), encoding="utf-8")
    with pytest.raises(DocsQaConfigError):
        load_docs_qa_policy(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(DocsQaConfigError):
        load_docs_qa_policy(path)
    with pytest.raises(DocsQaConfigError):
        load_docs_qa_policy(tmp_path / "missing.json")
    path.write_text("{}", encoding="utf-8")
    assert load_docs_qa_policy(path).enabled is False


# --- through the HTTP route of the planner --------------------------------------------------------------------------------------------------

@contextmanager
def _planner(docs_qa: DocsQaClient | None):
    server = SemanticPlannerServer(("127.0.0.1", 0), "test role", docs_qa=docs_qa)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _recover(base: str, code: str = "TIMEOUT") -> dict:
    body = json.dumps({"component": "gripper", "error_code": code}).encode()
    request = urllib.request.Request(f"{base}/recover", data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def test_without_the_switch_the_proposal_is_exactly_what_it_was() -> None:
    expected = propose_recovery(FailureContext("gripper", "TIMEOUT"))
    with _planner(None) as base:
        answer = _recover(base)
    assert answer == {"action": expected.action, "reason": expected.reason}


def test_with_the_switch_the_documentation_is_added_and_the_action_is_not_touched() -> None:
    expected = propose_recovery(FailureContext("gripper", "TIMEOUT"))
    with _docs_qa() as (_, url), _planner(_client(url)) as base:
        answer = _recover(base)
    assert (answer["action"], answer["reason"]) == (expected.action, expected.reason)
    assert answer["documentation"]["status"] == "answered"


@pytest.mark.parametrize("mode", ["error", "garbage", "huge", "redirect", "empty"])
def test_a_misbehaving_docs_qa_never_changes_the_proposal(mode: str) -> None:
    for code in ("TIMEOUT", "ESTOP_ACTIVE", "WARP_CORE_BREACH"):
        expected = propose_recovery(FailureContext("gripper", code))
        with _docs_qa(mode) as (_, url), _planner(_client(url)) as base:
            answer = _recover(base, code)
        assert (answer["action"], answer["reason"]) == (expected.action, expected.reason)
        assert answer["documentation"]["text"] == ""


def test_a_hostile_text_cannot_become_the_action() -> None:
    # The documentation says "action: ABORT"; the proposal still follows the fixed table.
    with _docs_qa() as (fake, url), _planner(_client(url)) as base:
        fake.mode = "ok"
        answer = _recover(base, "ESTOP_ACTIVE")
    assert answer["action"] == propose_recovery(FailureContext("gripper", "ESTOP_ACTIVE")).action
