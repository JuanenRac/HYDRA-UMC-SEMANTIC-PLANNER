# Plan simulation (dry run)

`POST /plan/simulate` checks a plan against declared constraints and runs it step by step on a simulated clock, **before anything is executed**.
It never executes, queues or releases anything: every answer says `"executable": false, "executed": false`. Releasing a plan stays with
`POST /release`. It uses no language model and reads no real clock: time is a counter of integer milliseconds that only moves when the
simulation moves it.

## Switch

The route is off by default: with the switch off the service answers exactly as before (`404 not found` for `/plan/simulate`). Turn it on in the
configuration file (`--config FILE` on `serve`, or `HYDRA_UMC_SEMANTIC_PLANNER_CONFIG`):

```json
{
  "plan_simulation": {
    "enabled": false,
    "max_steps": 200,
    "speed_mm_s": 100.0,
    "default_step_s": 1.0
  }
}
```

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | the switch; `false` means the route does not exist |
| `max_steps` | `200` | most steps a request may hold (1 to 10000); more is a 400 |
| `speed_mm_s` | `100.0` | speed used to time a move when the request does not give one |
| `default_step_s` | `1.0` | duration of a step that gives none (and of a first move, whose start is unknown) |

A configuration with a wrong type, an out-of-range value or an unknown key stops `serve` with exit status 2.

## Request

```json
{
  "steps": [
    {"id": "a", "primitive": "MOVE_TO", "robot": "r1", "params": {"location": "bin"}},
    {"id": "b", "primitive": "GRIP", "robot": "r1", "params": {"target": "pcb"}, "duration_s": 0.5, "depends_on": ["a"], "resources": ["fixture"]}
  ],
  "constraints": {
    "workspace": {"min": [0, 0, 0], "max": [500, 500, 300]},
    "locations": {"bin": [200, 0, 100]},
    "robots": ["r1", "r2"],
    "max_step_s": 30,
    "max_total_s": 120,
    "speed_mm_s": 100
  }
}
```

A step has a `primitive` of the closed vocabulary (`MOVE_TO`, `GRIP`, `RELEASE`, `INSPECT`, `WAIT`) with the `params` each one needs (the same
rule as `validate_plan`), the `robot` that runs it, and optionally an `id` (default `s<index>`), `depends_on` (ids of earlier steps), `resources`
(held for the duration of the step) and `duration_s`. All `constraints` are optional; locations are in millimetres. A move without `duration_s`
takes distance / speed from the position the robot reached by its previous move.

## Rules, in the verdict

| Rule | Broken when | Suggestion |
|---|---|---|
| `unknown_primitive` | the primitive is not in the vocabulary | the list of primitives |
| `step_params` | a required param is missing, empty or not text | none |
| `robot_unavailable` | the robot is not in `constraints.robots` | the first available robot |
| `dependency_order` | a step depends on an unknown, later or its own id | move the step or drop the dependency |
| `location_unknown` | the location is not in the catalogue | the catalogue |
| `workspace_limit` | the location is outside the workspace | the location clamped into the box |
| `gripper_state` | a GRIP while that robot holds something, or a RELEASE of something it does not hold | the missing RELEASE or GRIP |
| `resource_conflict` | two steps hold one resource at overlapping simulated times | add a dependency on the step holding it, with the new start |
| `step_time_limit` | a step lasts more than `max_step_s` | by how many ms to cut it |
| `plan_time_limit` | the plan ends after `max_total_s` | by how many ms to cut it |

Each step starts when its robot is free and the steps it depends on have ended.

## Answer

```json
{
  "verdict": "rejected",
  "executable": false,
  "executed": false,
  "violations": [
    {"rule": "workspace_limit", "step_index": 1, "step_id": "b", "message": "...", "value": [900.0, 0.0, 100.0], "limit": {"min": [0.0, 0.0, 0.0], "max": [500.0, 500.0, 300.0]}, "suggestion": "clamp 'far' to [500.0, 0.0, 100.0]"}
  ],
  "timeline": [{"step_id": "a", "index": 0, "robot": "r1", "primitive": "MOVE_TO", "start_ms": 0, "end_ms": 1000}],
  "makespan_ms": 1000,
  "simulated_clock_ms": 1000
}
```

Every broken rule is listed, not only the first. The suggestions are deterministic: the same request gives the same answer.

## Failing closed

A request that cannot be understood (not an object, unknown keys, wrong types, non-finite or non-positive numbers, repeated ids, an empty
or too long list of steps) is answered `400` with the reason, never with a verdict. An unexpected failure inside the simulation is a `500` without a
verdict. There is no path that answers `accepted` for an input that was not understood.

## Limits

The model is deliberately simple: straight-line moves at constant speed, one position and one gripper per robot, no kinematics, no collision
between robots, no real-time feedback. An `accepted` verdict means the plan breaks none of the declared rules, not that it is safe to run.
