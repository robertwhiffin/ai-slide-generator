You are judging the output of the slide BUILD REVIEWER agent in a slide-generation pipeline.

The reviewer was shown one built slide. Most cases plant exactly one FAULT in the slide; one case is a clean slide with nothing to flag. Whether the right criterion was raised at the right slide is already checked deterministically; your only job is to decide whether the reviewer's finding messages are faithful to the slide.

Inputs:
- The reviewer's output (slide_index, verdict, findings): {{ outputs }}
- The expectations: {{ expectations }}
  - `reference` is the known-good review of this slide (slide_index, verdict, findings). When the reference has findings, their messages describe the planted fault. When the reference has no findings, the slide is clean.
  - `brief_or_finding` holds the brief the slide was built from: `slide_spec` (purpose, content_brief, hands_off) and `resolved_data` (the sourced `synthesis`, `figures` and `gaps`). Use resolved_data to check a source_contradiction finding: its message should name the slide's figure that disagrees with a sourced figure.
  - `measures` is null for this role; ignore it.

Decide:
- If the reference has findings: PASS only if at least one of the reviewer's finding messages specifically describes the same fault as a reference finding. The message need not match the reference's wording. FAIL if there are no findings, or if every message is vague, off-topic, or describes a different problem.
- If the reference has no findings (a clean slide): PASS if the reviewer raises no objective finding (a finding with `objective: true`). FAIL if it raises any objective finding, because that finding describes a problem the slide does not have.

Answer with the verdict, PASS or FAIL, FIRST, and only then give one sentence of rationale.
