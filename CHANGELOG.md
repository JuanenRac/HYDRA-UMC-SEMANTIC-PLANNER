# Changelog: HYDRA-UMC-SEMANTIC-PLANNER 🧩

All notable changes to this project will be documented in this file. The
version number follows this ecosystem's "odometer" scheme: PATCH +1 on
every real build, rolling into MINOR past 9 (`0.0.9` -> `0.1.0`); MAJOR is
bumped manually only. See `bump_version.py`.

## [0.0.4] - Real v0 rule-based decomposition and recovery
### Added
- `primitives.py` - a real, closed vocabulary of robotic command primitives (`MOVE_TO`/`GRIP`/`RELEASE`/`INSPECT`/`WAIT`) a `Plan` is made of.
- `decompose.py` - real rule-based task decomposition (`decompose_goal()`) over a small known goal vocabulary (assemble/pick-and-place/inspect). Honestly template-based, not a local LLM - same reasoning as the sibling HYDRA-UMC-VOICE-UI's real rule-based intent parser and HYDRA-UMC-DOCS-QA's real TF-IDF index instead of an embedding model.
- `recovery.py` - real rule-based semantic recovery (`propose_recovery()`) over the real MCU adapter error-code vocabulary documented in `SONNET/BIBLIA HYDRA-UMC`'s own architecture manual (`INVALID_STATE`/`OUT_OF_RANGE`/`ESTOP_ACTIVE`/`TOOL_INCOMPATIBLE`/`TIMEOUT`/`UNSUPPORTED`), plus the README's own worked example (`GRIP_LOST_SEAL` -> increase pressure). `ESTOP_ACTIVE`/`UNSUPPORTED`/unknown codes always escalate to a human, matching the ecosystem's own safety rule that IA/UI never overrides a physical safety condition.
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
