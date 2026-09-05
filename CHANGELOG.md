# Changelog: HYDRA-UMC-SEMANTIC-PLANNER 🧩

All notable changes to this project will be documented in this file. The
version number follows this ecosystem's "odometer" scheme: PATCH +1 on
every real build, rolling into MINOR past 9 (`0.0.9` -> `0.1.0`); MAJOR is
bumped manually only. See `bump_version.py`.

## [Unreleased] - stricter untrusted plan validation

- **`api.py`'s `_read_json_body()` now caps request bodies** (`MAX_BODY_BYTES`,
  1 MiB) - found in an ecosystem-wide software-improvements audit: this
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
### Added
- `primitives.py` - a real, closed vocabulary of robotic command primitives (`MOVE_TO`/`GRIP`/`RELEASE`/`INSPECT`/`WAIT`) a `Plan` is made of.
- `decompose.py` - real rule-based task decomposition (`decompose_goal()`) over a small known goal vocabulary (assemble/pick-and-place/inspect). Honestly template-based, not a local LLM - same reasoning as the sibling HYDRA-UMC-VOICE-UI's real rule-based intent parser and HYDRA-UMC-DOCS-QA's real TF-IDF index instead of an embedding model.
- `recovery.py` - real rule-based semantic recovery (`propose_recovery()`) over the MCU adapter error-code vocabulary (`INVALID_STATE`/`OUT_OF_RANGE`/`ESTOP_ACTIVE`/`TOOL_INCOMPATIBLE`/`TIMEOUT`/`UNSUPPORTED`), plus the README's own worked example (`GRIP_LOST_SEAL` -> increase pressure). `ESTOP_ACTIVE`/`UNSUPPORTED`/unknown codes always escalate to a human, matching the ecosystem safety rule that AI/UI never overrides a physical safety condition.
- `main.py` - two new subcommands: `decompose "<goal>"` and `recover --component X --error-code Y [--detail "..."]`. Bare invocation is unchanged: identity/version/role.
- 14 new real tests (`tests/`) - decomposition coverage for every template plus an unmatched-goal case, recovery coverage for every rule including the safety-critical `ESTOP_ACTIVE` case and an unknown-code fallback, and a real end-to-end CLI round-trip for both subcommands.

## [0.0.3]
### Added
- Copyright/license header on every source file and build/run script.
- `CHANGELOG.md` (this file).
- Extended documentation across `README.md` and its 4 translations:
  advanced technical/architecture section, detailed build/run
  troubleshooting, and a full "Related Projects" section.

### Changed
- Inline comments explaining the *why* behind non-obvious decisions
  (versioning scheme, src-layout, why this child has no hardware/
  firmware/os/models of its own).

## [0.0.0]
### Added
- Initial Python scaffolding: `pyproject.toml` (setuptools, src-layout),
  `src/hydra_umc_semantic_planner/__init__.py` + `main.py` (real entry
  point - prints identity/version/role, exits 0).
- `bump_version.py` - odometer-style version bump applied to
  `pyproject.toml` and mirrored into `__init__.py`.
- `build.sh` / `build.bat` - create/activate a venv, install the package
  editable, verify it compiles and imports.
- `run.sh` / `run.bat` - run the entry point.
