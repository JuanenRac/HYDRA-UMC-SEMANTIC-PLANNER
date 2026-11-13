# Simulation bench

The planner can run without a safety service, a robot or a cell. The simulated path is a small HTTP stand-in of the safety service that answers `GET /state` the way the real one does, signed with the shared key, and that each scenario can make go wrong on purpose (old verdicts, forged ones, replays, another state, garbage, redirects, answers over the limit, a service that is not there), the real safety gate with its real HTTP fetch, goals drawn from a fixed seed, and a stream of failures for the memory of recoveries.

## Run it

```
python -m pytest -q tests/test_simulation_bench.py
```

## What the scenarios check

| Scenario | What it shows |
|----------|---------------|
| a fresh signed READY verdict over real HTTP | the plan is released and the token is sent as a bearer token |
| every state but READY | nothing is released and the reason names the state |
| a verdict too old or from the future | refused; one inside the limit is accepted |
| forged, unsigned, tampered and another key id | each is refused with its own reason |
| a replayed older verdict | refused after a newer one was seen |
| a service that is not there, garbage, an error status | a refusal and never an exception |
| an answer over the limit, a redirect | refused; the redirect is not followed |
| the signature switched off | the age still counts |
| forty verdicts of a cell that trips and recovers | the plan is released exactly while the cell is READY |
| sixty goals drawn from a seed | each becomes a plan of catalogue steps only, and the same goal gives the same plan |
| goals that forbid or cancel (nine words in two languages) | never a plan |
| empty, unknown, too long and ambiguous goals | an honest miss |
| a component that keeps failing the same recovery | it is handed to a person, another component is untouched, a success gives the default back |
| old failures and a long stream | forgotten, and the memory stays bounded |
| the memory kept in a file | it comes back after a restart and a damaged file starts empty |

The workflow named "Simulation bench" runs the bench on every change, so the simulated path has its own visible job.

## What it cannot show

The real safety service in a real cell, its timing, its keys in production and a robot that moves need the hardware. The status of the repository therefore stays at "simulated" for the hardware row until a person has run the service on the bench.
