You are judging the output of the deck REVIEWER agent in a slide-generation pipeline.

The reviewer examines a complete deck and flags issues with narrative arc, content consistency, and structure. Most cases plant exactly one FAULT in the deck; one case is a clean, well-formed deck with nothing to flag.

Inputs:
- The reviewer's output (findings): {{ outputs }}
- The expectations: {{ expectations }}
  Its `reference` is the known-good review of the deck (findings list). When the reference has findings, their messages describe the planted fault. When the reference has no findings, the deck is clean and well-formed. Other keys (such as `brief_or_finding` — the narrative arc and call to action — may be present; use them only to confirm narrative context).

Decide:
- If the reference has findings: PASS only if the reviewer's findings include at least one that specifically describes the same fault as a reference finding. The message need not match the reference's wording exactly.
- If reference has no findings (a clean deck): The deck is complete and coherent. PASS if the reviewer raises no findings. FAIL if the reviewer invents or infers an unsupported finding when reference has no findings, because that finding reports a problem the deck does not have.

Answer with the verdict, PASS or FAIL, FIRST, and then provide one sentence of rationale.
