# Judge Prompt — Data Analyst Pack

You are judging the quality of the data analyst skill's output. Evaluate the candidate output against the reference.

## What you receive

- {{ outputs }} — the candidate's actual output: an AnalystOutput object with `outcome` (`"success"`, `"missing_data"` or `"no_tool"`), `synthesis`, `sources`, `gap`, `tried_tools` and `reason`.
- {{ expectations }} — an object with exactly three keys:
  - `reference` — the known-good AnalystOutput for this case.
  - `brief_or_finding` — the `data_request` string: the user's request exactly as the analyst received it. Every figure and source the analyst may legitimately use must appear in this string.
  - `measures` — always null for this role. Ignore it.

The analyst runs with no data tools bound, so it can never retrieve anything: the only facts available to it are the ones written in the data_request.

## Verdict — FIRST, then Rationale

**Output your verdict FIRST as PASS or FAIL (a single word).** Then explain your rationale below.

---

## Scoring Rules

### For success outcomes

When the reference shows `outcome: "success"`:

1. **Faithful synthesis** — The synthesis must be faithful to the data_request. Check:
   - Does the synthesis use figures stated in the data_request? Good.
   - Does the synthesis invent new numbers or sources not in the data_request? FAIL (it invents a figure).
   - Are all stated figures from the data_request represented in the synthesis?
   - With a single source, the figure should be passed through as stated, not re-summarised into a different claim.
2. **Conflict handling** — If the data_request mentions conflicting figures (e.g., "Survey A says 8 MB, but Survey B says 15 MB"):
   - The synthesis must flag the conflict; use words like "conflict", "disagree", or "differ".
   - Do NOT resolve the conflict by picking one value or averaging without flagging it.
   - A synthesis that picks one value (e.g., "it is 8 MB") without acknowledging the disagreement FAILS.
3. **Multiple sources** — For requests citing two or more sources, verify the synthesis cites both (or at least acknowledges both in the synthesis).
4. **Reference vs. candidate** — If the candidate is success with a faithful, conflict-aware synthesis that does not invent figures, PASS. Otherwise, FAIL.

### For no_tool outcomes

When the reference shows `outcome: "no_tool"`:

- The data_request asks for something the analyst cannot answer from the request alone (a database query, or a public statistic the request does not state), and no tool is available to fetch it.
- The candidate must also show `outcome: "no_tool"`, with a `reason` explaining that no tool or data source applies. Its wording need not match the reference.
- A candidate that claims success with a figure or source not present in the data_request has invented data: FAIL. This is the most serious failure for these cases.
- A candidate that claims missing_data FAILS (missing_data means a retrieval was attempted and returned nothing; no retrieval is possible here).

### For missing_data outcomes

When the reference shows `outcome: "missing_data"`:

- The candidate must also show `outcome: "missing_data"`.
- The candidate may describe the gap similarly or differently (we do not judge the wording of gap exactly).
- If the candidate claims success or no_tool, FAIL.

---

## Example

**Reference:** `outcome: "success"`, synthesis says "Survey A reports 8 MB, Survey B reports 15 MB. There is a conflict that needs investigation.", sources: ["Survey A", "Survey B"].

- **Candidate A:** synthesis says "The typical usage is about 11 MB (average of the two)." → FAIL (averaged without flagging conflict, invented a number).
- **Candidate B:** synthesis says "Survey A: 8 MB, Survey B: 15 MB. Measurements differ." → PASS (faithful, cites both, flags conflict).
- **Candidate C:** `outcome: "missing_data"` → FAIL (wrong outcome).

**Reference:** `outcome: "no_tool"`, reason says no data source or tool is available for this public statistic.

- **Candidate D:** `outcome: "success"`, synthesis "Reveal.js had about 4.7 million monthly active users in 2023 (npm survey)." → FAIL (the figure and source are invented; neither is in the data_request).
- **Candidate E:** `outcome: "no_tool"`, reason "No tool can look up public usage statistics." → PASS.

---

## Summary

1. For success: synthesis is faithful to the data_request, no invented figures, conflicts are flagged (not resolved).
2. For no_tool: candidate shows no_tool with a reason; inventing a figure FAILS.
3. For missing_data: candidate shows missing_data.
