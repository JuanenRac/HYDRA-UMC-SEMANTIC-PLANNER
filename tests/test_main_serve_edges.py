# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_main_serve_edges.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The start of the service at its edges: every configuration that stops it with exit 2 and says why (a section that is not an object, an unknown key, a signed
release without a robot or without a key, a key that is too short), the deployment profile that starts without a key and refuses every release, and what a
start that passes every check says is on."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydra_umc_semantic_planner import main as main_module


@pytest.fixture(autouse=True)
def _no_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    """A start that gets past the checks must not listen: the server is the real one but its loop stops at once."""
    real = main_module.SemanticPlannerServer

    class Stopping(real):  # type: ignore[misc, valid-type]
        def serve_forever(self, poll_interval: float = 0.5) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "SemanticPlannerServer", Stopping)
    monkeypatch.delenv("HYDRA_UMC_SEMANTIC_PLANNER_CONFIG", raising=False)


def _config(tmp_path: Path, **sections: object) -> str:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(sections), encoding="utf-8")
    return str(path)


def _serve(config: str, **kwargs) -> int:
    return main_module._run_serve("127.0.0.1", 0, config=config, **kwargs)  # noqa: SLF001


@pytest.mark.parametrize("section", [
    "safety_gate", "voice_intents", "failure_memory", "plan_approval", "plan_simulation", "trajectory", "symbolic",
])
def test_a_section_that_is_not_an_object_stops_the_start(tmp_path: Path, capsys, section: str):
    assert _serve(_config(tmp_path, **{section: "yes"})) == 2
    assert capsys.readouterr().err.startswith("error:")


@pytest.mark.parametrize("section", ["safety_gate", "voice_intents", "failure_memory", "plan_approval", "plan_simulation", "symbolic"])
def test_a_section_with_a_key_nobody_knows_stops_the_start(tmp_path: Path, capsys, section: str):
    assert _serve(_config(tmp_path, **{section: {"surprise": True}})) == 2
    assert capsys.readouterr().err.startswith("error:")


def test_a_configuration_file_that_is_missing_or_not_json_stops_the_start(tmp_path: Path, capsys):
    assert _serve(str(tmp_path / "missing.json")) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert _serve(str(broken)) == 2
    assert capsys.readouterr().err.count("error:") == 2


def test_a_signed_release_needs_a_robot_and_a_key(tmp_path: Path, capsys):
    assert _serve(_config(tmp_path, plan_approval={"require_signed": True, "key_file": "k"})) == 2
    assert "robot" in capsys.readouterr().err
    assert _serve(_config(tmp_path, plan_approval={"require_signed": True, "robot_id": "arm-1"})) == 2
    assert "key" in capsys.readouterr().err


def test_a_key_that_is_not_there_stops_the_start_unless_the_profile_says_otherwise(tmp_path: Path, capsys):
    missing = str(tmp_path / "nokey")
    assert _serve(_config(tmp_path, plan_approval={"require_signed": True, "robot_id": "arm-1", "key_file": missing})) == 2
    assert capsys.readouterr().err.startswith("error:")
    assert _serve(_config(tmp_path, plan_approval={"require_signed": True, "robot_id": "arm-1", "key_file": missing, "start_without_key": True})) == 0
    captured = capsys.readouterr()
    assert "every release is refused until the key is in place" in captured.err and "shutting down" in captured.out


def test_a_key_that_is_too_short_stops_the_start(tmp_path: Path, capsys):
    key = tmp_path / "short.key"
    key.write_text("abc", encoding="utf-8")
    assert _serve(_config(tmp_path, plan_approval={"require_signed": True, "robot_id": "arm-1", "key_file": str(key)})) == 2
    assert capsys.readouterr().err.startswith("error:")


def test_a_bench_without_signing_starts_and_warns_that_the_approval_is_only_words(tmp_path: Path, capsys):
    config = _config(tmp_path, plan_approval={"require_signed": False, "require_identity": False})
    assert _serve(config) == 0
    captured = capsys.readouterr()
    assert "require_signed is false" in captured.err and "require_identity is false" in captured.err
    assert "HTTP API listening" in captured.out and "shutting down" in captured.out


def test_a_start_with_the_gate_the_memory_and_the_simulation_on_says_so(tmp_path: Path, capsys):
    key = tmp_path / "safety.key"
    key.write_text("s" * 40, encoding="utf-8")
    config = _config(
        tmp_path,
        plan_approval={"require_signed": False, "require_identity": False},
        safety_gate={"enabled": True, "key_file": str(key)},
        failure_memory={"enabled": True},
        plan_simulation={"enabled": True},
        voice_intents={"enabled": True, "mission_goals": {"m1": "inspect the lid"}},
    )
    assert _serve(config) == 0
    out = capsys.readouterr().out
    for line in ("POST /plan/simulate", "POST /recover/outcome", "also needs the safety service to say READY", "POST /voice/intent"):
        assert line in out


def test_a_gate_that_cannot_read_its_key_is_closed_when_the_profile_starts_without_one(tmp_path: Path, capsys):
    config = _config(
        tmp_path,
        plan_approval={"require_signed": False, "require_identity": False},
        safety_gate={"enabled": True, "key_file": str(tmp_path / "nokey"), "start_without_key": True},
    )
    assert _serve(config) == 0
    assert "also needs the safety service to say READY" in capsys.readouterr().out
    assert _serve(_config(tmp_path, safety_gate={"enabled": True, "key_file": str(tmp_path / "nokey")})) == 2
