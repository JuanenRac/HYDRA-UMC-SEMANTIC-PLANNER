# Testing strategy: property-based tests and mutation checks of the safety gate

The planner releases nothing unless the safety service says `READY` in a fresh, signed, newer verdict. The gate (`safety_gate.py`) is tested with property-based tests besides the hand-written cases and the stand-in HTTP service.

## Property-based tests

`tests/test_property_safety_gate.py` states rules that must hold for every input and checks them on generated cases. The cases come from a small generator with a fixed seed (`random.Random`), so a run is the same on every machine, nothing extra is installed to run it, and the whole file takes about two seconds. The rules:

| Area | Rule checked on generated inputs |
| --- | --- |
| Verdict | the untouched, fresh, correctly signed `READY` is the only thing released; a change to the state, the source, the counter, the signature, the key id or the algorithm, a missing field and an answer that is not a verdict are all refusals with a reason |
| Freshness | the age limit is exact in both directions (an old verdict and one from the future); a time that cannot be read is refused; a time with no zone is read as UTC and an offset is converted |
| Replay | a counter lower than one already seen is refused and the highest counter never goes back; an equal one (the same verdict read again) is allowed |
| Failure | any failure of the service or of the answer (a network error, a bad JSON, an unexpected exception, a recursion error) is a refusal and never raises |
| States | every state other than `READY` is refused even when perfectly signed |
| Keys | a signature of another key or another key id is refused; with Ed25519 only a signature of exactly 64 bytes by the configured key is accepted |
| Policy | every value outside the range of the settings (address, timeout, age limit, algorithm, switches) is refused, with the documented text; the key is required while signatures are required |

## Mutation checks (local only)

Mutation testing changes the code of a module in small ways (a `<` for a `<=`, a constant, a condition) and runs the tests: a change the tests do not notice is a behaviour nobody checks. It is a measure of the tests, not a part of the build: it is **not** run in the CI, and a run takes several minutes. To repeat it, in a throwaway virtual environment (mutmut 2 counts only the exit code 1 of the test command as a kill, so use a runner that maps every failing exit code to 1):

```
python -m pip install "mutmut<3" pytest cryptography
mutmut run --paths-to-mutate src/hydra_umc_semantic_planner/safety_gate.py --runner "python runner.py tests/test_property_safety_gate.py"
mutmut results
```

The run was limited to the settings of the policy, the signature message, the reading of the time and the check of the verdict (the reading of key files and the HTTP client are marked `# pragma: no mutate` in a scratch copy).

| Target | Mutants | Killed | Left |
| --- | --- | --- | --- |
| `safety_gate.py` (policy, message, time, check, verification) | 156 | 143 (91.7 %) | 13, equivalent or text of a success |

Mutants that survived while the tests were being written showed that the refusal texts, the limits of the policy (an address with `https`, a timeout of exactly 30 seconds), the counter 1, the text under the signature with non-ASCII characters and the Ed25519 path were not pinned; the tests now check them. The 13 mutants left are equivalent changes: the counter returned together with a refusal (never read), the starting value of a counter that is only read when signatures are required, the replacement of a trailing `Z` (Python 3.11 and later read it), the characters stripped from the end of the address (the same result for an address), a check of the length of an Ed25519 signature that the verification repeats, and the text of a success (never read).
