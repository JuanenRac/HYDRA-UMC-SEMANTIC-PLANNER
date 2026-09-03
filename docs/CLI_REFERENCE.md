# HYDRA-UMC-SEMANTIC-PLANNER — CLI Reference

`hydra-umc-semantic-planner` is a Python console script
(`src/hydra_umc_semantic_planner/main.py`, installed as an entry point
via `pyproject.toml`). Real v0 is two rule-based (not local-LLM) engines:
`decompose` turns a high-level goal into a sequence of robotic
primitives over a small known template vocabulary, and `recover`
proposes a recovery strategy for a structured MCU-adapter failure code
via an explicit lookup table. The local-LLM reasoning the project
README's own roadmap describes isn't wired up yet — both subcommands are
real, testable kernels a future LLM-based planner can replace behind the
same function contracts. Every example below was captured from a real
run of the installed CLI — not written from memory.

## Usage

```
$ hydra-umc-semantic-planner -h
usage: hydra-umc-semantic-planner [-h] {decompose,recover,serve} ...

Semantic Planner (Hailo-10) - decomposes high-level goals into robotic
primitives and recovers from execution failures.

positional arguments:
  {decompose,recover,serve}
    decompose          Real rule-based task decomposition into robotic
                       primitives.
    recover            Real rule-based semantic recovery for a structured
                       failure code.
    serve              Run 'decompose'/'recover' as a JSON/HTTP API - the
                       exact same decompose_goal()/validate_plan()/
                       propose_recovery() functions the CLI already runs.

options:
  -h, --help           show this help message and exit
```

Bare invocation (no subcommand) prints identity/version/role and exits `0`:

```
$ hydra-umc-semantic-planner
HYDRA-UMC-SEMANTIC-PLANNER v0.0.7
Semantic Planner (Hailo-10) - decomposes high-level goals into robotic primitives and recovers from execution failures.
```

## Commands

### `decompose <goal>`

```
$ hydra-umc-semantic-planner decompose -h
usage: hydra-umc-semantic-planner decompose [-h] goal

positional arguments:
  goal        High-level goal, e.g. "assemble the pcb".

options:
  -h, --help  show this help message and exit
```

Three real templates are matched by keyword, first match wins:
`assemble` (contains "assemble"), `pick_and_place` (contains "pick" ...
"place"), and `inspect` (contains "inspect"). The target is a real,
simple heuristic — the goal's **last** word:

```
$ hydra-umc-semantic-planner decompose "assemble the pcb"
Plan for: "assemble the pcb"
  1. MOVE_TO(location=pickup)
  2. GRIP(target=pcb)
  3. MOVE_TO(location=assembly_point)
  4. RELEASE(target=pcb)
```

```
$ hydra-umc-semantic-planner decompose "inspect the weld"
Plan for: "inspect the weld"
  1. MOVE_TO(location=weld)
  2. INSPECT(target=weld)
```

The "last word is the target" heuristic is honestly naive — worth
showing where it produces a target you might not expect:

```
$ hydra-umc-semantic-planner decompose "pick up the bolt and place it in the bin"
Plan for: "pick up the bolt and place it in the bin"
  1. MOVE_TO(location=pickup)
  2. GRIP(target=bin)
  3. MOVE_TO(location=destination)
  4. RELEASE(target=bin)
```

(The real target grabbed by a robot here is the goal sentence's last
word, "bin" — the intended object, "bolt", isn't it. A future NLP-based
target extractor is real, later work this v0 keyword/last-word heuristic
stands in for.)

**A real, honest miss** — a goal outside the small known vocabulary
returns no plan rather than guessing one, and still exits `0`:

```
$ hydra-umc-semantic-planner decompose "make me a sandwich"
No matching task template for: "make me a sandwich"
(v0 is a real rule-based planner over a small template vocabulary - an honest miss, not a guess.)
```

### `recover --component COMPONENT --error-code ERROR_CODE [--detail DETAIL]`

```
$ hydra-umc-semantic-planner recover -h
usage: hydra-umc-semantic-planner recover [-h] --component COMPONENT
                                          --error-code ERROR_CODE
                                          [--detail DETAIL]

options:
  -h, --help            show this help message and exit
  --component COMPONENT
                        Component that reported the failure.
  --error-code ERROR_CODE
                        Structured error code (e.g. TIMEOUT).
  --detail DETAIL       Optional human-readable detail.
```

`--error-code` is looked up in a real, explicit table covering the MCU
adapter's real error vocabulary (`INVALID_STATE`, `OUT_OF_RANGE`,
`ESTOP_ACTIVE`, `TOOL_INCOMPATIBLE`, `TIMEOUT`, `UNSUPPORTED`) plus one
domain-specific gripper failure mode (`GRIP_LOST_SEAL`).

A transient failure gets a safe retry:

```
$ hydra-umc-semantic-planner recover --component gripper_mcu --error-code TIMEOUT
Failure: gripper_mcu reported TIMEOUT
Recovery: RETRY - no response within the deadline - a single retry is safe
```

`--detail` is optional, and appears in parentheses when given:

```
$ hydra-umc-semantic-planner recover --component gripper --error-code GRIP_LOST_SEAL --detail "vacuum dropped below 40kPa"
Failure: gripper reported GRIP_LOST_SEAL (vacuum dropped below 40kPa)
Recovery: INCREASE_PRESSURE - vacuum seal lost - increasing gripper pressure before a retry
```

A real physical E-STOP is never auto-cleared by this planner — it always
escalates to a human, matching the ecosystem's own safety rule that no
software layer overrides a physical safety condition:

```
$ hydra-umc-semantic-planner recover --component base_mcu --error-code ESTOP_ACTIVE
Failure: base_mcu reported ESTOP_ACTIVE
Recovery: ESCALATE_TO_OPERATOR - a physical E-STOP is active - never auto-cleared by this planner
```

An error code outside the known table gets the same conservative
default — escalate, never a silent retry loop:

```
$ hydra-umc-semantic-planner recover --component arm_mcu --error-code WARP_CORE_BREACH
Failure: arm_mcu reported WARP_CORE_BREACH
Recovery: ESCALATE_TO_OPERATOR - unrecognized error code: WARP_CORE_BREACH
```

A real usage error — a missing required flag, argparse's own error path
(exit code `2`):

```
$ hydra-umc-semantic-planner recover --component gripper
usage: hydra-umc-semantic-planner recover [-h] --component COMPONENT
                                          --error-code ERROR_CODE
                                          [--detail DETAIL]
hydra-umc-semantic-planner recover: error: the following arguments are required: --error-code
$ echo $?
2
```

### `serve [--addr ADDR] [--port PORT]`

```
$ hydra-umc-semantic-planner serve -h
usage: hydra-umc-semantic-planner serve [-h] [--addr ADDR] [--port PORT]

options:
  -h, --help   show this help message and exit
  --addr ADDR  address to bind the HTTP API to (default: 127.0.0.1)
  --port PORT  port for the HTTP API (default: 8109)
```

Runs the exact same `decompose_goal()`/`validate_plan()`/
`propose_recovery()` functions as `decompose`/`recover`, over a plain
stdlib `http.server` JSON API. Binds to loopback (`127.0.0.1:8109`) by
default, matching the `systemd/hydra-umc-semantic-planner.service` unit.

* **`GET /stats`** — `{"role": "..."}`, a liveness/identity check.
* **`POST /decompose`** — body `{"goal": "..."}`. Responds `200` with
  `{"matched", "goal", "steps", "issues", "valid"}` — `matched: false`
  for an honest miss (same as the CLI's own "no matching task template"
  case), never a `4xx`.
* **`POST /recover`** — body `{"component": "...", "error_code": "...",
  "detail": "..."}` (`detail` optional). Responds `200` with the real
  `RecoveryStrategy`. Either route responds `400` with
  `{"error": "..."}` for a malformed JSON body or a missing required
  field.

## Validation contract

`validate_plan()`/`validate_step()` fail closed on malformed input, not
just on a well-formed-but-incomplete plan: a required param that isn't
text (e.g. `null`, a number) is reported as `required param 'X' must be
text` rather than raising while calling `.strip()` on it, and a plan with
zero steps is always reported invalid (`plan has no steps`) rather than
being treated as trivially valid. This matters for any caller other than
`decompose_goal()` itself feeding `validate_plan()` a hand-built or
externally-sourced `Plan` — `decompose.py`'s own templates never produce
either case, so this is defensive robustness at the library boundary, not
a behavior change visible from the CLI/HTTP examples above.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | `decompose`/`recover` both always succeed, including an honest "no matching template" miss from `decompose` |
| `2` | argparse usage error — a missing/malformed required flag |

## Not yet implemented

The real local-LLM reasoning the project README's roadmap describes —
open-vocabulary goal decomposition and free-form failure diagnosis — is
not wired up. Both subcommands here are real, explicit, rule-based
kernels (a small goal-template table, an explicit error-code lookup
table) that a future LLM-based planner is meant to sit behind, not
replace at the CLI surface.
