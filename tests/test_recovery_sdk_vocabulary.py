# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_recovery_sdk_vocabulary.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The recovery table of the planner must say what the vocabulary of the SDK says (mcu_errors)."""
from __future__ import annotations

from hydra_umc_semantic_planner import recovery
from hydra_umc_sdk import mcu_errors


def test_every_code_of_the_sdk_vocabulary_has_the_same_default_action() -> None:
    for entry in mcu_errors.MCU_ERROR_CODES:
        strategy = recovery.propose_recovery(recovery.FailureContext(component="x", error_code=entry.code))
        assert strategy.action == entry.default_action, entry.code


def test_the_planner_knows_no_code_the_sdk_does_not_define() -> None:
    known = {entry.code for entry in mcu_errors.MCU_ERROR_CODES}
    assert set(recovery._RULES) == known


def test_a_code_outside_the_vocabulary_escalates_in_both() -> None:
    unknown = "NOT_A_REAL_CODE"
    assert not mcu_errors.is_known_mcu_error(unknown)
    strategy = recovery.propose_recovery(recovery.FailureContext(component="x", error_code=unknown))
    assert strategy.action == mcu_errors.default_mcu_error_action(unknown) == recovery.ESCALATE_TO_OPERATOR


def test_the_action_names_are_the_same_words() -> None:
    assert {recovery.RETRY, recovery.INCREASE_PRESSURE, recovery.SWAP_TOOL, recovery.ABORT, recovery.ESCALATE_TO_OPERATOR} == set(
        mcu_errors.RECOVERY_ACTIONS
    )


def test_the_reasons_cover_exactly_the_vocabulary() -> None:
    assert set(recovery._REASONS) == {entry.code for entry in mcu_errors.MCU_ERROR_CODES}


def test_the_planner_takes_the_actions_from_the_sdk_at_run_time(monkeypatch) -> None:
    import importlib

    patched = tuple(
        mcu_errors.McuErrorCode(e.code, e.meaning, mcu_errors.ABORT if e.code == "TIMEOUT" else e.default_action)
        for e in mcu_errors.MCU_ERROR_CODES
    )
    monkeypatch.setattr(mcu_errors, "MCU_ERROR_CODES", patched)
    monkeypatch.setattr(mcu_errors, "_BY_CODE", {e.code: e for e in patched})
    try:
        reloaded = importlib.reload(recovery)
        assert reloaded.propose_recovery(reloaded.FailureContext(component="x", error_code="TIMEOUT")).action == mcu_errors.ABORT
    finally:
        monkeypatch.undo()
        importlib.reload(recovery)
