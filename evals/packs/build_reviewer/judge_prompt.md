You are judging the output of the slide BUILD REVIEWER agent in a slide-generation pipeline.

The reviewer was shown one built slide that contains a planted FAULT. Whether the right criterion was raised at the right slide is already checked deterministically; your only job is to decide whether the reviewer's finding messages actually describe the planted fault.

Inputs:
- The reviewer's output (slide_index, verdict, findings): {{ outputs }}
- The expectations, which carry the planted fault, the expected criterion and position, and the known-good reference findings: {{ expectations }}

Decide whether at least one finding's message specifically describes the planted fault (compare with the reference findings and the fault description in the expectations). The message need not match the reference's wording. Fail if there are no findings, or if every message is vague, off-topic, or describes a different problem.

Answer with the verdict, PASS or FAIL, FIRST, and only then give one sentence of rationale.
