# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/voice_intents.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""From an intent already parsed by HYDRA-UMC-VOICE-UI to a plan proposal.

The voice service turns a transcript into an intent (`{"name": "start_mission", "entities": {"mission_id": "pcb-1"}}`). This module
decides which goal that intent stands for, and nothing else: the goal is then decomposed, validated and proposed by the same code as
`POST /decompose`, so the result is a proposal, never an order, and it is released only by `POST /release` with a person's approval.

Only the intent `start_mission` can become a plan, and only through a catalogue of missions kept in the configuration file
(`voice_intents.mission_goals`: mission id to goal text). A mission that is not in the catalogue is not guessed. `stop` and `status`
are never plans (a stop is never delayed by planning), and any other intent is refused. The route is OFF by default
(`voice_intents.enabled`), and while it is off it does not exist.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .decompose import MAX_GOAL_CHARS
from .recovery import CONFIG_ENV

INTENT_START_MISSION = "start_mission"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_KNOWN_KEYS = {"enabled", "mission_goals"}
MAX_MISSIONS = 500


class VoiceIntentConfigError(ValueError):
    """The `voice_intents` section of the configuration file cannot be used."""


@dataclass(frozen=True)
class VoiceIntentPolicy:
    enabled: bool = False
    mission_goals: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise VoiceIntentConfigError("voice_intents.enabled must be true or false")
        if not isinstance(self.mission_goals, dict) or len(self.mission_goals) > MAX_MISSIONS:
            raise VoiceIntentConfigError(f"voice_intents.mission_goals must be an object with at most {MAX_MISSIONS} entries")
        for mission, goal in self.mission_goals.items():
            if not isinstance(mission, str) or not _ID.match(mission):
                raise VoiceIntentConfigError(f"voice_intents.mission_goals: {mission!r} is not a usable mission id")
            if not isinstance(goal, str) or not goal.strip() or len(goal) > MAX_GOAL_CHARS:
                raise VoiceIntentConfigError(f"voice_intents.mission_goals[{mission!r}] must be a goal of 1 to {MAX_GOAL_CHARS} characters")


def load_voice_policy(path: str | os.PathLike[str] | None = None) -> VoiceIntentPolicy:
    """The `voice_intents` policy of the file `path`, or of the file named by the planner's configuration variable, or the default (off)."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return VoiceIntentPolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise VoiceIntentConfigError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise VoiceIntentConfigError(f"{chosen} must hold a JSON object")
    section = data.get("voice_intents", {})
    if not isinstance(section, dict):
        raise VoiceIntentConfigError("voice_intents must be a JSON object")
    unknown = sorted(set(section) - _KNOWN_KEYS)
    if unknown:
        raise VoiceIntentConfigError(f"voice_intents has unknown keys: {', '.join(unknown)}")
    return VoiceIntentPolicy(**section)


def goal_for_intent(intent: object, policy: VoiceIntentPolicy) -> tuple[str | None, str]:
    """(goal, "") for an intent that stands for a goal of the catalogue, or (None, reason) when it does not."""
    if not isinstance(intent, dict):
        return None, "intent must be an object with a name and entities"
    name = intent.get("name")
    if not isinstance(name, str):
        return None, "intent.name must be text"
    entities = intent.get("entities", {})
    if not isinstance(entities, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in entities.items()):
        return None, "intent.entities must be an object of text values"
    if name != INTENT_START_MISSION:
        return None, f"the intent {name!r} is not turned into a plan (only {INTENT_START_MISSION} is)"
    mission = entities.get("mission_id", "")
    if not _ID.match(mission):
        return None, "the intent names no usable mission"
    goal = policy.mission_goals.get(mission)
    if goal is None:
        return None, f"the mission {mission!r} is not in the catalogue"
    return goal, ""
