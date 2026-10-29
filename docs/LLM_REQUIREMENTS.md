<!--
=============================================================================
HYDRA-UMC-SEMANTIC-PLANNER - Requirements before a language model is connected
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
CC BY-SA 4.0 - see LICENSE.md
=============================================================================
-->

# Requirements before a language model is connected

The planner is rule-based today: it matches a goal against a closed set of templates and builds a plan from a closed set of primitives (`move_to`, `grip`, `release`, `inspect`, `wait`). **No language model is connected, and none may be until every requirement below is met and has a test.** The rules exist so that a model, which can be talked into things by the text it reads, never becomes the thing that decides what a robot does.

1. **The output is constrained to the closed vocabulary.** A model answers in JSON that is validated against a schema (grammar-constrained decoding where the runtime offers it, validation after the fact always): only the primitives above, with the parameters each one declares. Anything else is refused, never repaired.
2. **Targets and locations come from the catalogue of the cell.** A `target` or a `location` is an entry of an allow-list that the cell provides, never free text from the model or from the person.
3. **The text of the person and the instructions of the system are kept apart.** Untrusted content (documents found by DOCS-QA, text read from an image, a transcript of speech) is never put into the prompt without being marked as data, and never as an instruction.
4. **Limits are recomputed outside the model.** The checks of `validation.py` (shape of every step, capabilities, gripper state) and the cost limits of `approval.py` run in code on the plan after the model has produced it, with the same limits as for a rule-based plan; the model is never asked whether its own plan is within them.
5. **A person approves the exact plan, never the model.** As today, a plan is released for execution only with the approval of a named person for that exact plan (the approval carries the fingerprint of the plan). If a primitive that applies force, goes faster than the limit of the cell or drives a cutting or laser tool is ever added, it needs its own explicit, signed approval on top of that.
6. **The explanation of a plan is produced by code from the plan.** The text that tells the operator what the plan will do is generated from the validated steps, never by the model, so that the explanation cannot differ from what is executed.
7. **A refusal is the default.** A goal that is negated, that fits more than one template or that has no object is refused today and stays refused with a model; the model may suggest a rephrasing, never guess.

Until a model exists these are the acceptance criteria for connecting one; changing any of them is a decision about the safety of the cell, not a detail of the integration.
