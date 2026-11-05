# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- **The identity of HYDRA-UMC-SERVER, off by default (`serve --identity-key-file FILE`, or `HYDRA_UMC_SEMANTIC_PLANNER_IDENTITY_KEY_FILE`):** the service verifies the signed token (HS256 JWT with `exp`, `username` and `role`) that the server issues at login and accepts it next to its own token. A viewer may read but not change, and a request with no credential is refused even on loopback, `GET /health` and `GET /stats` included: nothing is open. An address that is not loopback no longer needs a token of the service. The key is the signing key of the server, read from a file that only the group of the service may read, at least 32 characters; without the switch nothing changes. `server_identity.py` is the canonical copy of the SDK, and `python -m hydra_umc_semantic_planner.server_identity probe --port PORT` is the probe of a container, which signs a short-lived token of its own with the same key file.

- **The recovery table is checked against the shared vocabulary of the SDK:** `tests/test_recovery_sdk_vocabulary.py` compares every code and default action of the planner with `hydra_umc_sdk.mcu_errors` (4 tests), so a code added or changed in one place and not in the other fails the CI. The service itself still runs with no dependency; the `dev` extra installs the SDK client from its published tag.

- **The manifest declares the uniform `GET /health` route:** `service.health_path` is `/health` now. The route stays closed (404) until the service switch opens it, and the health checks of the server and of the family ask `/stats` after a 404 on `/health`.

## [0.1.9] - Behaviour change: approvals are signed by default. serve now requires a signed approval (HMAC-SHA256 over the plan fingerprint, the approver, the robot and the time window; Ed25519 optional with planapproval.algorithm) and... (and 2 more changes)

- **Behaviour change: approvals are signed by default.** `serve` now requires a signed approval (HMAC-SHA256 over the plan fingerprint, the approver, the robot and the time window; Ed25519 optional with `plan_approval.algorithm`) and refuses to start without a key and a robot, instead of accepting the words of the request. The new `plan_approval` section of the configuration file sets `require_signed` (true by default; `false` is for development only and is announced at start), `algorithm`, `key_file` (outside the repository), `robot_id` and `start_without_key` (the service starts without the key and refuses every release with the reason). The deployment profile turns it on with `/etc/hydra-umc/plan-approval.key`; the general file keeps it off for a planner started by hand. `sign-approval` takes `--algorithm`. 7 new tests.

- **Property-based tests of the safety gate:** `tests/test_property_safety_gate.py` (seeded generated cases, no new dependency; the Ed25519 case is skipped where `cryptography` is not installed) checks that only the untouched, fresh, correctly signed `READY` verdict releases a plan, that any change to the state, the source, the counter, the signature, the key id or the algorithm, any missing field and any answer that is not a verdict is a refusal with a reason, that the age limit is exact in both directions, that a replayed counter is refused, that every state other than `READY` is refused even when signed, that a failure of the service never raises and never releases, and that every value outside the range of the settings is refused. A local mutation run of `safety_gate.py` left 12 of 156 mutants, all of them equivalent changes; the method and the figures are in `docs/TESTING_STRATEGY.md`. The mutation run is not part of the CI.
- **A uniform `GET /health`, closed by default:** `serve --health-open` (or `HYDRA_UMC_SEMANTIC_PLANNER_HEALTH_OPEN=1`) makes the service answer `GET /health` with `{"status": "ok", "service": ..., "version": ...}`, the same body in every service of the family, so a watchdog reads the health of any of them the same way. Without the switch the route answers `404` like a route that does not exist. This service has no bearer token, so it answers only a caller on loopback. The body carries no path, configuration or secret; the health path the manifest declares does not change.

## [0.1.8] - A safety gate before the release of a plan that is on in the deployment profile of the CM5, a memory of recoveries that can be kept in the data lake, a symbolic planner, a voice intent route and a recovery that only tightens

- **Symbolic planning behind `decompose_goal()` (off by default).** With `symbolic_planner.enabled` set to `true` in the configuration file, the goal that the rules understood becomes a small PDDL-lite problem (preconditions, negated preconditions, add and delete effects over a closed set of operators) and the steps come from a deterministic breadth-first search bounded by `max_nodes` and `max_plan_length`. The plan is replayed from the start state and discarded if any precondition breaks; when nothing is found the answer is a miss, never the template. It only proposes: validation, the fingerprint, the person's approval and the safety gate of `POST /release` are unchanged. The start, pickup, assembly and destination locations are configuration values. 11 tests.

- **A bounded memory of how recoveries ended (off by default).** With `failure_memory.enabled` set to `true`, `POST /recover/outcome` records the component, the error code, the action and SUCCESS or FAILURE of a proposed recovery, and nothing else (never the free text of a failure). The memory keeps at most `max_entries` records for at most `ttl_s` seconds and may be kept in a file (`path`). An action that failed `min_failures` times and never worked is proposed as `ESCALATE_TO_OPERATOR`; the memory can only make a recovery more cautious, never relax an escalation or an abort. Without the switch the route answers 404 and `POST /recover` is unchanged.

- **Changed: the safety gate is ON in the deployment profile.** The new profile `configs/deploy-cm5.json`, which the systemd unit selects through `HYDRA_UMC_SEMANTIC_PLANNER_CONFIG`, sets `safety_gate.enabled` to `true`: a plan is released only while HYDRA-UMC-SAFETY-ZONES answers with a fresh, READY and validly signed verdict, and the verification key is read from `/etc/hydra-umc/safety-state.key`, outside the repository. The general file `configs/semantic-planner.json` keeps the gate off, so a planner started by hand for development behaves as before; the difference between the deployment profile and development is described in the documentation. 8 tests (valid signature, no answer, invalid signature, missing key).

- **A missing safety key no longer stops the planner in the deployment profile.** With `safety_gate.start_without_key` set to `true` (the profile does; the default is `false`), a key or token file that cannot be read leaves the planner running with a gate that refuses every `POST /release` and says why, while `POST /decompose` and the proposals keep working. Without the switch a bad file is still an error at start.

- **The memory of recoveries can be exported to a local data lake and read back (off by default).** With `failure_memory.export.enabled` set to `true`, each recorded outcome is sent to HYDRA-UMC-DATALAKE through `POST /ingest/batch` (kind `recovery_outcome`, field `component/error_code/action`, value 1 or 0; never the free text of a failure) by a thread of its own, with a bounded queue and bounded retries, so a slow or missing data lake never delays an answer. The address is loopback by default; another address needs `token_file` and https, or `allow_plaintext` set on purpose. At start (`load_on_start`) the memory reads the failures back with `GET /query`: every record is validated, a corrupt, foreign, future or expired one is ignored and counted, only failures are taken, and a record already held is not counted twice, so a reload can only make a recovery more cautious. Every value is in `failure_memory.export` of `configs/semantic-planner.json`. 8 tests against a simulated data lake.

## [0.1.7] - A fail-closed safety gate before the release of a plan and a voice intent route that only proposes

- **Safety gate before a release (off by default).** With `safety_gate.enabled` set to `true` in the configuration file, `POST /release` also asks HYDRA-UMC-SAFETY-ZONES for its last verdict (`GET /state`) and releases nothing unless that verdict is READY, fresh (`max_age_ms`, default 2000) and, by default, signed (`require_signature`; HMAC-SHA256 with `key_file`, or Ed25519 with a public key). It fails closed: a safety service that does not answer, an answer that is not a verdict, an old, unsigned, forged or replayed verdict and every state other than READY keep the plan from being released, with the reason in the answer, and a person's approval is still required. The gate is asked only after that approval has passed. A planner started with the gate on and no key refuses to start. Without the switch `/release` answers exactly as before. 28 tests, including one against the real signer of the safety service.

- **A voice intent becomes a proposal (off by default).** With `voice_intents.enabled` set to `true`, `POST /voice/intent` takes an intent already parsed by HYDRA-UMC-VOICE-UI (`{"name": "start_mission", "entities": {"mission_id": "..."}}`), looks the mission up in the catalogue `voice_intents.mission_goals` of the configuration file and answers the same proposal as `POST /decompose` (`executable` false, `requires_approval` true, `source` `voice`), which only `POST /release` can release. A mission that is not in the catalogue is a miss, never a guess; `stop`, `status` and any other intent never become plans. With the switch off the route answers 404.

- **`GET /metrics` in the text format of Prometheus:** the version, the uptime, the responses by class of status (2xx to 5xx) and the health, the aggregate of the checks of the service; only numbers about the service, never a path, an address, a token or a body. Open like `/stats`. The code is the canonical `service_metrics.py` of HYDRA-UMC-SDK, copied byte for byte. 3 tests against a real server.

## [0.1.6] - Plans that can be simulated before they are run

- **Plans can be simulated before they are run:** `POST /plan/simulate` checks a list of steps (robot, dependencies, resources, duration) against declared constraints (workspace box, catalogue of locations, robots available, maximum step and plan time) and walks it on a simulated clock with a small state per robot (position, gripper). The answer is a verdict with EVERY broken rule (rule, step, value, limit) and, where one follows, a deterministic suggestion; it never executes or releases anything (`executable: false`). The route is off by default (`plan_simulation.enabled` in the configuration file): with the switch off it answers `404` as before. An input that is not understood is a `400`, never an `accepted`. See `docs/PLAN_SIMULATION.md`.

## [0.1.5] - A plan expressed as the common Operation of the SDK, out-of-range actions aborted, signed approvals and the universal README

- **A plan is expressed as the common Operation of the SDK:** `POST /decompose` answers with `operation` (`kind` `execute_plan`, `status` `received`, the `target` and `priority` of the request, the steps, the goal and the fingerprint in `params`; the same plan is the same `operation_id`), the shape that the orchestrator and the job dispatcher take as a mission or a job. It does not release anything: `executable` stays `false` until `POST /release`.
- **An out-of-range action is aborted:** `OUT_OF_RANGE` now proposes `ABORT` instead of `SWAP_TOOL`. The earlier action stays available with `recovery.out_of_range_action` set to `SWAP_TOOL` in the configuration file (`configs/semantic-planner.json`, `--config FILE` on `recover` and `serve`, or `HYDRA_UMC_SEMANTIC_PLANNER_CONFIG`); an unknown value is refused.

- **Approvals can be signed, with an expiry and a robot:** `serve --approval-key-file FILE --robot-id ROBOT` (off by default) makes `POST /release` ask for `robot_id`, `issued_at_ms`, `expires_at_ms` and an HMAC-SHA256 `signature` over the plan fingerprint, the approver, the robot and the time window (one hour at most). An approval that is unsigned, altered, expired, for another plan or for another robot releases nothing. The new `sign-approval` command produces the fields. Without the switch the behaviour is unchanged.

- **README in the universal layout:** the README and its seven translations follow the layout that the four families share (22 sections in a fixed order), with an architecture picture and a repository-structure picture drawn from `docs/architecture.json` and `docs/structure.json`; the CI validator checks both pictures and the file tree.

- **The layout of the README is checked in the CI:** the validator runs `tools/universal_readme_check.py` and lists, as a warning, what differs from the universal layout of the README.
- `docs/LLM_REQUIREMENTS.md` lists what must hold, and be tested, before a language model is connected to the planner: closed vocabulary, targets from the catalogue of the cell, untrusted text kept apart, limits and approval outside the model, explanation produced by code.

## [0.1.4] - The gripper is followed along the plan and the parameters of a step cannot be changed

- **The gripper is followed along the plan.** `validate_plan` walks the steps with a symbolic gripper (empty at the start): a GRIP while it already holds something, and a RELEASE with nothing held or of something other than what is held, are issues at their own step (`gripper_state_issues`). A plan may end holding its target; what the templates produce is always valid.
- **The parameters of a step cannot be changed.** `Step.params` is a read-only, hashable `Params` (a plain dict is accepted and copied; `dataclasses.asdict` and JSON give the dict they always gave; the fingerprint of a plan is unchanged), so a step can be hashed and a plan cannot be edited after it was proposed.

- The manifest declares the health route of the service (`/stats`), so the service registry, the ecosystem status of the server and the watchdog know where to probe it.
- Building no longer changes the version; raising it is the explicit `bump` command (`python tools/hydra_project_tool.py bump`). The build scripts only report the version they built, and CI fails if a build script runs a bump.
- The build and run scripts use the Python of the `.venv` directly instead of an activate script, and create the venv with the `py` launcher when there is one; CI fails if a script activates a venv.
- The banner follows the animated style of the ecosystem banners, with the name, the kind and the technologies of the project.
- Added `tools/hydra_project_tool.py`: the same `validate`, `test`, `version`, `status` and `bump` commands in every repository. The checks run with `HYDRA_UMC_CI=1` and fail if the version changes; only `bump` changes it.

## [0.1.3]

- Maturity is functional: nothing here has been verified on real hardware yet.
- The READMEs say, in the eight languages, what is planned and what has only been tested against fakes, emulators or fixtures, and carry a short safety and security status note.

## [0.1.2] - Safer goal parsing, recomputed release checks, bounded recovery

- **Negated or ambiguous goals no longer become plans:** "do not pick ...", "never assemble ..." used to produce the plan for the forbidden action, and a goal fitting several templates silently used the first one. Negated goals (English and Spanish), goals matching more than one template and goals without a real object now get no plan.
- **The object is read after the verb:** the target used to be the last word of the sentence ("bin", "now", "carefully"). It is now the word after the verb (and the destination after `place`); pronouns, adverbs and connectors are never an object.
- **Goal length is bounded:** goals longer than 512 characters are refused (`400` over HTTP), and the pick/place pattern no longer backtracks quadratically, which let a 1 MiB request keep the service busy for minutes.
- **Release recomputes what it checks:** `release_for_execution()` recomputes the cost and compares the explanation with the one derived from the plan instead of trusting the proposal, and accepts the robot's declared `capabilities`.
- **Decompositions are proposals:** `POST /decompose` answers `executable: false` with the plan fingerprint, estimated cost and explanation; the new `POST /release` checks the approval fingerprint against the plan before it is released.
- **Recovery is bounded:** `FailureContext.attempt` (and `attempt` on `POST /recover`) makes `TIMEOUT` and `GRIP_LOST_SEAL` escalate to the operator after 1 and 3 automatic attempts.
- **Stricter input and exit codes:** `goal`, `component`, `error_code` and `detail` must be text (no more `"None"`), and `decompose` exits `3` when no plan is found (71 tests).
- **Docs:** README title, badges and package description no longer claim an LLM or a Hailo-10 target that does not exist yet; the limits of the rule-based planner and the new API are documented in all languages.

## [0.1.1] - Non-object JSON bodies are a 400, idle connections dropped, Portuguese README

- **A non-object JSON body crashed the handler:** `POST /decompose` and `POST /recover` read the body with `json.loads()` and indexed it as an object, so valid JSON that is not an object (a list, a string, `null`, a number, a boolean) raised a `TypeError` nothing caught - the handler thread died with a traceback and the client got no response at all. It is now a `400` ("the JSON body must be an object"), and the server keeps answering afterwards (confirmed against the real server with five body shapes on both routes).
- **Idle connections are dropped:** the HTTP handler had no connection timeout, so a client that opened a connection and sent nothing held a handler thread forever. A silent client is now dropped after 15 seconds; the limit covers socket I/O only.
- **Tests:** new tests cover the five non-object bodies on both routes and the dropped idle connection (59 tests).
- **Docs:** the README test count and the sample version line are corrected, and a README in Portuguese (`README_por.md`) joins the other translations.

## [0.1.0] - Approval, cost limits and explanation before execution

- `approval.py`: `propose()` turns a plan into a proposal with a stable fingerprint, a
  step-by-step explanation and an estimated cost. `release_for_execution()` releases it only
  when the plan validates, has an explanation, is within the step and cost limits and carries
  an approval by a named person for *that exact plan* (the approval holds the fingerprint, so
  it cannot release another plan and a tampered proposal is detected). Ten new tests.

## [0.0.9] - stricter untrusted plan validation

- **New `Dockerfile`**, closing the real gap HYDRA-UMC-COGNITIVE-NODE's
  own `docker-compose.yml` named ("do not have published Dockerfiles
  yet"). Same `--addr`/`--port` CLI the real CM5 systemd unit
  (`systemd/hydra-umc-semantic-planner.service`) already runs, bound to
  `0.0.0.0` instead of `127.0.0.1` - a container's own network namespace
  is the real isolation boundary here, not the loopback bind, and
  `127.0.0.1` inside a container would be unreachable from
  HYDRA-UMC-COGNITIVE-NODE's own container over the compose network.
  Non-root. Not build-tested (no Docker runtime on this dev machine) -
  every path/flag matches the one already verified live on the real CM5.
- **`api.py`'s `_read_json_body()` now caps request bodies** (`MAX_BODY_BYTES`,
  1 MiB) - found on code review: this
  endpoint used to read `Content-Length` bytes with no upper bound before
  parsing, so a malformed or oversized header let a caller force unbounded
  memory buffering. An over-limit request is drained (up to `DRAIN_CAP_BYTES`)
  before the clean 400 is sent, avoiding a real `ConnectionAbortedError` race
  where the client's own send() is still in flight when the handler closes
  the connection - same root cause and same fix already shipped for this
  exact gap in HYDRA-UMC-ANOMALY-DETECTOR. New end-to-end regression test
  against a live server, not just the helper function in isolation.
- Required primitive parameters must now be text; invalid external plan data
  is reported as a `PlanIssue` rather than raising while calling `.strip()`.
- Empty plans are explicitly invalid and cannot be presented as executable.
- **`.github/workflows/ci.yml`** - the real `tests/` pytest suite is now
  actually installed and run in CI. The baseline workflow's Python
  handling previously only compile-checked (`py_compile`) every `.py`
  file and validated the manifest/docs - it never ran `pytest`, so a
  regression in `tests/` could be merged without CI ever failing.
  CI-only fix, no runtime code changed, no version bump.

## [0.0.8]

- **An optional, real declared-capability catalog reaches
  `validate_plan()`/`validate_step()`/`POST /decompose`.** A well-formed
  step (right params) was never enough on its own - a fixed template
  producing a real `GRIP` step doesn't know whether the robot that would
  actually run it ever declared it has a gripper at all. New optional
  `capabilities: frozenset[str] | None` parameter (`"capabilities"` in
  the `POST /decompose` JSON body, a list of primitive names): when
  supplied, a step whose primitive isn't declared is a real, distinct
  issue (`"primitive 'X' is not in this robot/cell's declared
  capabilities"`), reported alongside any param issues on that same
  step. Omitted (the default, and every pre-existing caller) validates
  params only, exactly as before this parameter existed.

  Deliberately NOT attempted here: real POSTcondition verification (did
  `GRIP` actually end up holding its target) - that needs live feedback
  from a real executor (HYDRA-UMC-ORCHESTRATOR) this project doesn't
  have yet; fabricating a postcondition schema nobody could verify would
  be worse than not having one. See `validation.py`'s own updated header
  comment.

  10 new tests (6 in `test_validation.py`, 4 real end-to-end HTTP tests
  in `test_api.py`), 47 total. Confirmed via a real git-stash-based
  regression check that they fail against the pre-fix source.
  `docs/CLI_REFERENCE.md` updated with the new field's real contract.

## [0.0.7] - Real v0: JSON/HTTP server mode, plus CM5 deployment

- **`api.py`** (new) - `POST /decompose` and `POST /recover` reach the
  exact same `decompose_goal()`/`validate_plan()`/`propose_recovery()`
  functions the CLI's own subcommands already run. Real gap this closes:
  this project's own rule-based decomposition/recovery logic was only
  ever reachable as a one-shot CLI.
- **`main.py`** - new `serve` subcommand (`--addr`/`--port`, default
  `127.0.0.1:8109`).
- **`systemd/hydra-umc-semantic-planner.service`** (new) - loopback-only
  unit for `HYDRA-UMC-OS/provisioning/install_semantic_planner.sh` (new,
  that repo), same stdlib "copy src/ + PYTHONPATH" shape as
  `install_datalake.sh`.
- 7 new tests (`tests/test_api.py`, real end-to-end HTTP, reusing this
  repo's own `tests/test_cli.py` fixture shapes) - 36 total.

## [0.0.6] - Removed a private-document reference from public source/README

- **`recovery.py`/`README.md`** - both named a private internal design
  document (section D.4) as the source of the recovery error-code
  vocabulary. New `docs/RECOVERY_CONTRACT.md` makes that vocabulary
  public and self-contained instead - no private document is needed to
  encode or interpret a recovery request.
- **`tools/ci_validate.py`** - the public/private documentation boundary
  check only ever looked for one private marker; extended to also reject
  the private design document's own name, so this class of leak is
  caught automatically going forward. New `validate_local_markdown_links()`
  also rejects a relative Markdown link whose target file doesn't exist.
  `CI_VALIDATION=PASS`.
- 27/27 tests passing.

- Build version synchronized with `hydra-umc.project.json` and the repository-native version source.

## [0.0.5] - Deterministic-plan guarantees, precondition validation, property tests

- **Real precondition validation** (`validation.py`, new) - `REQUIRED_PARAMS` defines what each real primitive genuinely needs (`MOVE_TO` needs `location`; `GRIP`/`RELEASE`/`INSPECT` need `target`; `WAIT` needs nothing), and `validate_plan()`/`validate_step()`/`is_plan_valid()` check every step of a `Plan` against it. Wired into the `decompose` subcommand: a plan that fails its own preconditions is now refused (exit 1, every issue listed) instead of being handed off as execution-ready. `decompose.py`'s real templates never actually trigger this today - a regression test proves it - but it is the real contract a future LLM-based planner (this project's own roadmap) would have to satisfy, since it can't guarantee well-formed params the way a fixed template can.
- **Real property tests for `decompose_goal()`** - a determinism property (the same goal decomposed twice always produces the identical plan), a fuzz property (500 random strings, fixed seed for reproducibility, over 0-40 characters: never crashes, and any plan it does return always passes its own precondition check), and a fixed corpus of real invalid-goal edge cases (empty/whitespace-only, punctuation noise, and near-miss words that contain a known keyword only as a substring of a longer word, verified directly against the real compiled patterns rather than assumed).
- 13 new tests (`test_validation.py` new, plus additions to `test_decompose.py`/`test_cli.py`) = 27 total.
- Real verification: ran `decompose` live against a real goal (passes validation unchanged) and an unmatched goal (unchanged honest miss).

## [0.0.4] - Real v0 rule-based decomposition and recovery
- `primitives.py` - a real, closed vocabulary of robotic command primitives (`MOVE_TO`/`GRIP`/`RELEASE`/`INSPECT`/`WAIT`) a `Plan` is made of.
- `decompose.py` - real rule-based task decomposition (`decompose_goal()`) over a small known goal vocabulary (assemble/pick-and-place/inspect). Honestly template-based, not a local LLM - same reasoning as the sibling HYDRA-UMC-VOICE-UI's real rule-based intent parser and HYDRA-UMC-DOCS-QA's real TF-IDF index instead of an embedding model.
- `recovery.py` - real rule-based semantic recovery (`propose_recovery()`) over the MCU adapter error-code vocabulary (`INVALID_STATE`/`OUT_OF_RANGE`/`ESTOP_ACTIVE`/`TOOL_INCOMPATIBLE`/`TIMEOUT`/`UNSUPPORTED`), plus the README's own worked example (`GRIP_LOST_SEAL` -> increase pressure). `ESTOP_ACTIVE`/`UNSUPPORTED`/unknown codes always escalate to a human, matching the ecosystem safety rule that AI/UI never overrides a physical safety condition.
- `main.py` - two new subcommands: `decompose "<goal>"` and `recover --component X --error-code Y [--detail "..."]`. Bare invocation is unchanged: identity/version/role.
- 14 new real tests (`tests/`) - decomposition coverage for every template plus an unmatched-goal case, recovery coverage for every rule including the safety-critical `ESTOP_ACTIVE` case and an unknown-code fallback, and a real end-to-end CLI round-trip for both subcommands.

## [0.0.3]
- Copyright/license header on every source file and build/run script.
- `CHANGELOG.md` (this file).
- Extended documentation across `README.md` and its 4 translations:
  advanced technical/architecture section, detailed build/run
  troubleshooting, and a full "Related Projects" section.

- Inline comments explaining the *why* behind non-obvious decisions
  (versioning scheme, src-layout, why this child has no hardware/
  firmware/os/models of its own).

## [0.0.0]
- Initial Python scaffolding: `pyproject.toml` (setuptools, src-layout),
  `src/hydra_umc_semantic_planner/__init__.py` + `main.py` (real entry
  point - prints identity/version/role, exits 0).
- `bump_version.py` - version bump applied to
  `pyproject.toml` and mirrored into `__init__.py`.
- `build.sh` / `build.bat` - create/activate a venv, install the package
  editable, verify it compiles and imports.
- `run.sh` / `run.bat` - run the entry point.
