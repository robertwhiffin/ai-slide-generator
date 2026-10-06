# Judge Prompt — Data Analyst Pack

You are judging the quality of the data analyst skill's output. Evaluate the candidate output against the reference.

## Expectations and Outputs

Your task: compare {{ outputs }} (the candidate's actual output) against {{ expectations }} (the reference, the known-good answer). 

## Verdict — FIRST, then Rationale

**Output your verdict FIRST as PASS or FAIL (a single word).** Then explain your rationale below.

---

## Scoring Rules

### For success outcomes

When the reference shows `outcome: "success"`:

1. **Faithful synthesis** — The synthesis must be faithful to the data_request. Check:
   - Does the synthesis use figures stated in the data_request? Good.
   - Does the synthesis invent new numbers not in the request? FAIL (it invent a number).
   - Are all stated figures from the request represented in the synthesis? 
2. **Conflict handling** — If the data_request mentions conflicting figures (e.g., "Survey A says 8 MB, but Survey B says 15 MB"):
   - The synthesis must flag the conflict; use words like "conflict", "disagree", or "differ".
   - Do NOT resolve the conflict by picking one value or averaging without flagging it.
   - A synthesis that picks one value (e.g., "it is 8 MB") without acknowledging the disagreement FAILS.
3. **Multiple sources** — For requests citing two or more sources, verify the synthesis cites both (or at least acknowledges both in the synthesis).
4. **Reference vs. candidate** — If the candidate is success with a faithful, conflict-aware synthesis that does not invent figures, PASS. Otherwise, FAIL.

### For missing_data outcomes

When the reference shows `outcome: "missing_data"`:

- The candidate must also show `outcome: "missing_data"`.
- The candidate may describe the gap similarly or differently (we do not judge the wording of gap exactly).
- If the candidate claims success or no_tool, FAIL.

### For no_tool outcomes

When the reference shows `outcome: "no_tool"`:

- The candidate must also show `outcome: "no_tool"`.
- If the candidate claims success or missing_data, FAIL.

---

## Example

**Reference:** `outcome: "success"`, synthesis says "Survey A reports 8 MB, Survey B reports 15 MB. There is a conflict that needs investigation.", sources: ["Survey A", "Survey B"].

- **Candidate A:** synthesis says "The typical usage is about 11 MB (average of the two)." → FAIL (averaged without flagging conflict, invented a number).
- **Candidate B:** synthesis says "Survey A: 8 MB, Survey B: 15 MB. Measurements differ." → PASS (faithful, cites both, flags conflict).
- **Candidate C:** `outcome: "missing_data"` → FAIL (wrong outcome).

---

## Summary

1. For success: synthesis is faithful, no invented figures, conflicts are flagged (not resolved).
2. For missing_data: candidate shows missing_data.
3. For no_tool: candidate shows no_tool.
