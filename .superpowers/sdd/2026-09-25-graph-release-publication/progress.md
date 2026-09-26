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

## Controller rulings on the corrections pass — 2026-09-25
Corrections pass `818aa7de7`: 28 corrections. Accepted departures: I5 is Phase B (binds Task 6); C2 uses FOR SHARE on both parents as the first statement of `_validate_current_graph` rather than REPEATABLE READ (the implementer probed RR breaking `test_graph_configuration_bootstrap_postgres.py:105`).
Ruling: C1 knock-on — #267's case writer must REFUSE deactivating or retiring a role's last active required case (ordered 422), preserving the bootstrap invariant at `graph_configuration_bootstrap.py:196-198`. Carry into #267's corrections at its Task 0. Cost if wrong: an admin action makes the next boot exit.
Carry-forward to #267's corrections (binding): (a) correction 13 — the test-run executor commits or releases every lock before any model call; (b) the C1 knock-on above; (c) the builder smoke-case payload at `graph_configuration_seed.py:23-35` must match the production builder allowlist (see the builder fix branch ledger).
Deferred to Task 0-B: correction 19's two outcomes (#268 cleanup vs unlinked approvals outside the latest 20 runs), Q2, Q4, Q8, Q9; Q7 to #270.

## Task 0 (phases A and B together) — 2026-09-26
All four predecessors are merged locally (#264 `c040dbde0`, #266 `e91fcd856`, #267 `a08389ec3`, #268 `16aa02b76`); reviewed heads `e3aa3650c`, `3189ad5ad`, `adbc6fef7`, `dd129b832`, each proved an ancestor of HEAD and of `feat/langgraph-core` (`predecessor-heads.md`).
Bases: `TASK1_BASE` = `INTEGRATION_BASE` = `cd63aa09b` (plan/ledger docs on `16aa02b76`), written once, read-only. SAME COMMIT on purpose: no Tasks 1-3 exist to rebase because the predecessors integrated before Phase A started; Task 9's diff is `INTEGRATION_BASE..HEAD` = Tasks 1-8 (C55).
Deferred answers (from code): Q2 cleanup = L0 both parents FOR SHARE -> L3 FOR UPDATE ORDER BY id -> DELETE in a new statement (C40). Q4 = `AgentTestWorkbench().readiness_under_parent_lock` via `get_agent_test_workbench` (C39). Q8 = a new version is a new row/new id, old retired in the same txn (C42). Q9 = neither the case writers (L2 FOR UPDATE, every role row, id order) nor the verdict writer (L3 only) takes L0 (C41). C19 = outcome (a) (C43). C13 re-probe closed by an existing GREEN PG test (C50). Fake adapter `tests/fixtures/deterministic_model_adapter.py:85`. #268 shipped no publication code and no Review & Publish page (Q1 held; no stop). Forbidden allowed list is 7 (`forbiddenActionNames.ts:36-44`; lengths `AgentDefinitionWorkbench.test.tsx:378`, `agent-definition-workbench.spec.ts:1518`); #269 makes it 8 (C44).
Corrections 34-55 appended (22 new; errata to C7, C17, C31 as C44, C36, C35). Probe run: FastAPI `include_router` copies routes at call time (late-decorated routes absent) -> C35.
Baseline by cause (`reports/preflight.md`): focused unit 1009/0/0; PG 11 files all green, zero skips; full unit 6 failed / 6784 / 110 = the known six by node and first line; Vitest workbench 622; typecheck clean.
OPEN FOR CONTROLLER: C48 (Q3 trigger makes #268's verdict route 500 on a published run; proposed typed `linked_to_release` refusal) must be ruled before Task 4.
Gate: Task 1 GO once its brief carries C2-C6, C8-C9, C17+C36, C23-C25, C37 (and C1/C10 Phase A parts).

## Task 0 — 2026-09-26
Task 0 (phases A+B together; Opus) DONE at `f1ec89d98`: TASK1_BASE = INTEGRATION_BASE = `cd63aa09b` (C55: all predecessors merged before any Phase A work); `predecessor-heads.md` (#264 `c040dbde0`/`e3aa3650c`, #266 `e91fcd856`/`3189ad5ad`, #267 `a08389ec3`/`adbc6fef7`, #268 `16aa02b76`/`dd129b832`, ancestry proven); corrections 34–55 + per-task self-consistency + producer/consumer tables. Baseline: focused unit 1009/0/0; 11 PG files zero skips all green; full unit 6 (baseline nodes/causes) / 6784 / 110; workbench Vitest 622; typecheck 0.
Q2/Q4/Q8/Q9 answered from code (C39–C42). C19 = outcome (a) (C43).
Ruling (C48): ADOPT the proposed typed refusal — `record_verdict` re-checks the link in a NEW statement after the L3 lock (C33) → `IneligibleForApprovalError(reason="linked_to_release")` → 422 `ineligible_for_approval` with the stated message; Python literal + schema + message table in Task 4, TS reasons in Task 6 (parity pinned by the #268 join test). The C14 trigger stays the backstop. — an unexplained 500 on a normal UI action is worse than editing three merged #268 files. — cost if wrong: small, three files.
Ruling (C47): accepted as reasoned; Task 4's RED must record the observed cause.
Concern 3 (builder approvability under the fake adapter): carried to Task 8's brief as a re-probe.
Task 0: complete. GO for Task 1 (TASK_BASE `f1ec89d98`).
