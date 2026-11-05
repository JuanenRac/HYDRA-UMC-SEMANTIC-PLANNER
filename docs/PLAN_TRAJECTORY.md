# Plan as a trajectory (kinematic check)

`POST /plan/trajectory-check` turns the MOVE_TO steps of a plan into a sampled trajectory and has HYDRA-UMC-PHYSICS-REPLICA check it, **before anything is
executed**. It never executes, queues or releases anything: every answer says `"executable": false, "executed": false`. Releasing a plan stays with `POST /release`.

## How the plan becomes a trajectory

1. Only the MOVE_TO steps of the robot named by `plan_trajectory.robot` are used; the robots of other steps are listed in `skipped_robots`.
2. The location of each move comes from the catalogue of the request (`constraints.locations`, millimetres; `mm_to_m` converts to metres).
3. The replica solves the position of the tool frame (`POST /ik`, joint `target`), starting from the joints reached by the previous move (the first from `start_joints`).
4. The joint positions are joined by straight lines in joint space and sampled `samples_per_segment` times per move; a move lasts its `duration_s`, or the distance over `speed_mm_s`.
5. The samples go to `POST /check-trajectory` of the replica.

Assumptions, also written in every answer: only the position of the tool is solved (not its orientation), and the path between two poses is a straight line in joint space, not in Cartesian space.

## Switch

Off by default: the route answers `404`. In the configuration file (`--config FILE` on `serve`):

```json
{ "plan_trajectory": { "enabled": true, "url": "http://127.0.0.1:8118", "token_file": "/etc/hydra-umc/replica.token",
  "robot": "robot-1", "target": "tool", "start_joints": { "shoulder": 0.0, "elbow": 0.0 }, "samples_per_segment": 10, "max_moves": 100, "mm_to_m": 0.001, "timeout_s": 5.0 } }
```

The replica must run with `serve --urdf ROBOT.urdf` and `"ik": {"enabled": true}`. `robot`, `target` and `start_joints` are required while it is enabled (the request may carry its own `start_joints`). The token is read from its file and never printed.

## Verdict

`accepted` only when every goal was reached **and** the replica says `ok` **and** `complete`. Otherwise `rejected` with one violation per problem:
`goal_unreachable`, `location_unknown`, `trajectory_limit` (with the value and the limit of the replica) or `check_incomplete` (a check was switched off or could not run: an unchecked trajectory is never read as a clear one).
A request that cannot be understood is a `400`; the replica not answering, refusing or answering something else is a `502`.
