<!-- =============================================================================
HYDRA-UMC-SEMANTIC-PLANNER - Public recovery error contract
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Public Recovery Contract

## Purpose

This document defines the public error vocabulary consumed by
`recovery.py`. It is intentionally self-contained: callers do not need a
private design document to encode or interpret a recovery request.

## Error codes and default action

| Error code | Meaning | Planner action |
|---|---|---|
| `INVALID_STATE` | The reported component state is incompatible with the plan. | `ABORT` |
| `OUT_OF_RANGE` | The request exceeds the declared tool range. | `SWAP_TOOL` |
| `ESTOP_ACTIVE` | A physical emergency stop is active. | `ESCALATE_TO_OPERATOR` |
| `TOOL_INCOMPATIBLE` | The mounted tool cannot perform the request. | `SWAP_TOOL` |
| `TIMEOUT` | No response arrived before the declared deadline. | `RETRY` once |
| `UNSUPPORTED` | The downstream component does not implement the request. | `ESCALATE_TO_OPERATOR` |
| `GRIP_LOST_SEAL` | A declared gripper vacuum seal was lost. | `INCREASE_PRESSURE`, then evaluate again |

Unknown codes always produce `ESCALATE_TO_OPERATOR`. The planner proposes a
recovery; it never clears an emergency stop, changes a physical safety system
or sends motion directly.

## Compatibility rules

- New codes require a documented meaning, a deterministic default action and
  a negative test for unrecognised consumers.
- Existing code meanings and safe defaults are immutable within a minor
  release line.
- Callers must treat an unknown code as unsafe and await an operator or a
  versioned adapter update.
