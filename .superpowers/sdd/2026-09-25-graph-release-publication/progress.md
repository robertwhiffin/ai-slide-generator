# SDD ledger — plan: docs/superpowers/plans/2026-09-25-graph-release-publication.md

Plan drafted 2026-09-25 by a planning agent at `b9cc4cb27` on `plan/publish-release-269` (base `c040dbde0`), 949 lines, Tasks 0-9. Not yet plan-reviewed; not executable until #266, #267, #268 integrate and Task 0 phase B runs.
Unverified by the planner: `_lock_current_parents` (`graph_configuration_workbench.py:209-227`) raising an integrity error (500) instead of 409 when a save/read queues behind a committing publication — reasoned, not probed; Task 2's RED must prove it. Every #267/#268 shape is assumed from the user's draft plans.
Ruling: Q1 — #269 owns the publication transaction, evidence linking and the Review & Publish page; #268 delivers readiness, verdicts and cleanup only. Its draft Tasks 5-6 that extend a publication transaction and a Review & Publish page are to be re-scoped in #268's own PLAN-CORRECTIONS (not by editing the user's draft plan file). Cost if wrong: #268 and #269 both build part of one transaction.
Ruling: Q3 — a verdict on a run already linked to a release is immutable (enforced by #269's trigger step). Cost if wrong: published evidence can be retroactively changed.
Ruling: Q5 — a changed role with no active required case is a readiness gap (publication refused with an ordered issue), not an integrity error; link only the newest eligible approval per required case, never optional cases. Cost if wrong: a missing case 500s instead of explaining itself.
Ruling: Q6 — keep `409 nothing_to_publish`; successful publish returns 200 to match existing admin writes; release note max 2000 characters. Cost if wrong: a status-code change at the wire, cheap before any client exists.
Deferred to Task 0 phase B (need #267/#268 as built): Q2 cleanup lock order, Q4 which readiness callable binds inside the transaction, Q8 test-case versioning identity, Q9 whether case/verdict writers take the draft lock. Deferred to #270: Q7 rollback draft-content semantics.
Before execution: an independent plan review (doc review loop) against the issue, design and code.

## Plan review 1 — 2026-09-25 (plan at `d04b07aa5`, code at `c040dbde0`)

**Verdict:** APPROVE WITH CORRECTIONS. **Counts:** Critical 2, Important 12, Minor 14. Every finding became one numbered correction in `PLAN-CORRECTIONS.md`, which overrides the plan. The plan file is unchanged.

**Confirmed `_lock_current_parents` claim (reviewer's two-session PostgreSQL probe, throwaway database dropped):**
- Setup: the publisher held `_lock_current_parents(exclusive=True)`, closed v1, inserted v2 with seven mappings, rebased the draft and committed.
- Result: both waiters, the `read_workbench` FOR SHARE reader and the draft-writer FOR UPDATE writer, were proven blocked with the publisher's PID in `pg_blocking_pids(waiter)`. After the commit, each got zero rows (the qual was re-checked against the closed row, and v2 is not in the statement's snapshot) and raised `GraphConfigurationIntegrityError("graph configuration parent snapshot is inconsistent")`, which the route maps to HTTP 500.
- Consequence: Task 2's RED cause and its one-retry fix are sound.

**Deadlock probe (reviewer):**
- Setup: session X held `graph_draft FOR SHARE`, and the L0 statement waited on the draft.
- While waiting, L0 already held the active `graph_release` row: `SKIP LOCKED` from a third session returned nothing. So the order is release before draft.
- X then requested `FOR KEY SHARE` on the release (the analogue of the `compared_release_id` FK check), and PostgreSQL raised `DeadlockDetected`.
- This is the basis for Correction 13: #267's run executor must commit or release every lock before any model call, and this must be carried into #267's own corrections.

**Corrections-author probes (`/tmp/corr269/`, throwaway database dropped):**
- SQLite loads `effective_from` naive, and comparing it with the aware timestamp raises `TypeError` (I1).
- A publication committed between `_validate_current_graph`'s reads makes bootstrap raise "release mapping rows do not belong to the complete release history" (C2).
- A REPEATABLE READ snapshot is fixed when the advisory-lock statement starts, which would break the two-bootstrap test. So C2 uses FOR SHARE parent locks instead.
- A trigger `WHEN (EXISTS …)` is rejected with `FeatureNotSupported`, while a body check with a column-only `WHEN` works (I12).

**Corrections 1–28:** 1–2 = C1–C2, 3–14 = I1–I12, 15–28 = M1–M14.
- **Blocking before Task 1 (Phase A):**
  - 2, 3, 4, 5, 6, 8 (parts 1 and 3), 9;
  - plus the Phase A parts of 1 (the `PublicationGap` type and wire) and 10 (the Q6 note cap, the Q1 record).
- **Blocking before Task 4 (Phase B):**
  - 1 (the gate, tests and sabotage);
  - 7 (the Task 6 exemption);
  - 8 (part 2, evidence-link injection);
  - 10, 11, 12, 13, 14.
- **Non-blocking:** 15–28, applied in the task each one names.

**Outstanding:**
- Carry Correction 13's ruling and Correction 1's last-required-case boot hazard into #267's PLAN-CORRECTIONS.
- At Task 0-B, record #268's retention rule for an unlinked approval outside the latest 20 (Correction 19).
- Q2, Q4, Q8 and Q9 stay deferred to Task 0-B, and Q7 to #270.
