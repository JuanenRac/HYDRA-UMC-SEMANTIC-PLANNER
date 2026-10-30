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
| `OUT_OF_RANGE` | The request exceeds the declared tool range. | `ABORT` (`SWAP_TOOL` by configuration) |
| `ESTOP_ACTIVE` | A physical emergency stop is active. | `ESCALATE_TO_OPERATOR` |
| `TOOL_INCOMPATIBLE` | The mounted tool cannot perform the request. | `SWAP_TOOL` |
| `TIMEOUT` | No response arrived before the declared deadline. | `RETRY` once |
| `UNSUPPORTED` | The downstream component does not implement the request. | `ESCALATE_TO_OPERATOR` |
| `GRIP_LOST_SEAL` | A declared gripper vacuum seal was lost. | `INCREASE_PRESSURE`, then evaluate again |

Unknown codes always produce `ESCALATE_TO_OPERATOR`. The planner proposes a
recovery; it never clears an emergency stop, changes a physical safety system
or sends motion directly.

## Configuration

`configs/semantic-planner.json` holds the recovery policy. It is read from the
file given with `--config` (`recover`, `serve`) or named by the variable
`HYDRA_UMC_SEMANTIC_PLANNER_CONFIG`; without either, the safe defaults apply.

| Key | Values | Default |
|---|---|---|
| `recovery.out_of_range_action` | `ABORT`, `SWAP_TOOL` | `ABORT` |

`ABORT` stops the action: a motion beyond the real limits of the tool is not
retried by itself. `SWAP_TOOL` restores the earlier contract for installations
that rely on it. Any other value is refused and the command exits with an error.

## Compatibility rules

- New codes require a documented meaning, a deterministic default action and
  a negative test for unrecognised consumers.
- Existing code meanings and safe defaults are immutable within a minor
  release line; the only change is the default action of `OUT_OF_RANGE`,
  which is now `ABORT` and can be set back to `SWAP_TOOL` in the configuration.
- Callers must treat an unknown code as unsafe and await an operator or a
  versioned adapter update.
