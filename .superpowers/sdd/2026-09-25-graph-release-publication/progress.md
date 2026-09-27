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

## Task 1 — 2026-09-26
Task 1: implementer DONE_WITH_CONCERNS at `3851c9aa4` (TASK_BASE `2322a4291`): `256f2233c` publication core (`src/services/graph_configuration_publication.py`, shared helpers extracted in draft/content/bootstrap, `_await_blocked_by` in `postgres_concurrency_helpers.py:215`, PG file enrolled in integration-graph). Gates: focused unit 937; full unit 6 (baseline nodes/causes) / 6819 / 110; PG publication 9, bootstrap 3, workbench 49, overlay 10, constraints 66 — zero skips; ruff clean (pre-existing I001 in test_ci_collects at base). 29 mutations: 26 RED, M12 equivalent, M13/M23 defensive-unreachable.
Concern 1 (L0 statement's release-before-draft order is planner-determined, not text-determined; M25 left the behavioural test GREEN): to the reviewer — judge whether every L0 taker shares the one helper (then order agrees across callers) or the lock must split into two statements.
Concern 3 (C8 M04 prediction partly wrong — PendingRollbackError): recorded; correction to C8's prediction text only.
Deviation: `_await_blocked_by` created in Task 1 (C53 said Task 2) — ACCEPTED; Task 2 must reuse it.
Task 1: controller sabotage (fresh; not in M01–M29) — stale-lock check skipped when no role changed (`CTRL269_1_ORDER`, anchor 1): unit file 34/34 GREEN, PG file 9/9 GREEN — SURVIVED. A stale `expected_lock_version` whose server draft now equals the published release returns `NothingToPublish`, not `PublicationConflict`; the precedence (stale before nothing-to-publish) is unpinned. FINDING for the fix round: add a test (another admin saves then reverts to published content → the stale publisher gets `PublicationConflict`). Restored from pinned HEAD, clean, marker 0.
Task 1: review (Opus): spec PASS, quality APPROVE WITH MINOR FIXES — 0 Critical, 0 Important, 3 Minor. m1 = CTRL269_1_ORDER (brief Step 4 fixes stale-before-changed; only the pin is missing). m2 PG file never asserts persisted `previous_release_id` (reviewer S1 survived PG; RED unit 2/34). m3 `test_parent_lock_statement_takes_release_before_draft` HANGS on failure (pool shutdown waits on the blocked publisher; holder rolled back only in the outer finally). Reviewer S2 (draft-save error order) RED 1/634. Temp worktree removed; its hang leaked `tellr_int_c8e85e5c36f549ff`, proven the reviewer's, dropped; list back to the 4 older DBs.
Ruling (concern 1): ACCEPT, no split — the reviewer's probe P1 shows the L0 order follows the `FOR UPDATE OF` list (statement text), not FROM/join order (the implementer's M25 flipped only FROM). All L0 takers use `_lock_current_parents` (`graph_configuration_workbench.py:188`); session creation locks only the release. Pin now: the FOR SHARE path renders the same `OF` order. Task 2 (bootstrap L0) and #270 rollback must call the helper — add a grep-based test that no other `with_for_update` targets GraphRelease+GraphDraft.
Task 1: fix round 1/5 dispatched (resume implementer): m1, m2, m3 (+ bounded lock_timeout), the OF-order pin for FOR SHARE, the one-helper grep test.
Task 1: fix round 1/5 (5 addressed, 0 open; `df4d4118d`, test-only — `git diff --stat 6fe29ead3 df4d4118d -- src` empty): m1 stale-with-nothing-changed conflict test; m2 persisted lineage asserts; m3 holder rolled back in inner finally + `lock_timeout 30s` + bounded future (pre-fix copy proved the hang; leaked `tellr_int_cd98b01737cd428d` proven the implementer's, dropped); FOR SHARE OF-order PG test; AST scanner `tests/unit/test_graph_parent_lock_is_single_sourced.py` with non-vacuity test. Gates: focused 940; full unit 6 (baseline) / 6822 / 110; PG publication 10 zero skips; ruff clean. Mutations F1–F5 RED.
Controller re-check: CTRL269_1_ORDER re-applied → RED 1/35 (`test_stale_lock_with_nothing_changed_is_a_conflict_not_nothing_to_publish`); restored clean.
Ruling: no scoped re-review subagent — test-only diff, every finding independently mutated RED, and the controller's own target re-run RED. Cost if wrong: small.
Task 1: complete (commits `2322a4291..df4d4118d`, review clean after 1 fix round).

## Task 2 — 2026-09-27
Task 2: implementer DONE_WITH_CONCERNS at `06e5b757e` (TASK_BASE `5c3cfd827`): `ccd77756d` one-rescan handoff in `_lock_current_parents` (`_MAX_PARENT_LOCK_SCANS = 2`, diagnosis byte-identical) + race tests + C9 test; `7abacf86d` C2 boot lock (`_lock_current_parents(exclusive=False)` first in `_validate_current_graph`) + two C2 race tests; `3f8cc4191` boot-lock shape pin (closed M6); `672d49734` C49 diagnosis pin (closed M9). `_await_blocked_by` reused unchanged. Gates: PG publication 21, bootstrap 3, workbench 49, overlay 10, constraints 66 + the other 10 integration-graph files — zero skips; focused unit 909; full unit 6 (baseline) / 6822 / 110; ruff clean. Pre-fix REDs matched C18 and C2 predictions. Mutations M1–M9: all RED except M4 (equivalent). The plan's controller sabotage (M1) and C2's (M5) were run by the implementer — SPENT.
Ruling: concern (C49 seam table / C51 lock table are plan-document edits) — carried to the whole-branch review; no plan edits. Concern (conversation creation waits for boot validation) — accepted cost of C2.
Task 2: controller sabotage (fresh) — readers never rescan (`not exclusive` added to the break condition; `CTRL269_2_READERS`, anchor 1). PG publication file: RED 2/21 (`test_publication_first_then_workbench_read_sees_new_release`, `test_boot_validation_queued_behind_publication_sees_new_release`). Restored from pinned HEAD, clean, marker 0.
Task 2: review (Opus): spec PASS, quality PASS — 0 Critical, 0 Important, 3 Minor. Reviewer sabotage: S1 rescan result discarded → RED 5/21 (the C18 set + queued boot); S2 C2 lock in a separate transaction → RED 2/21 in 74 s (C2's predicted error; boot never blocked), no hang. Named risks clear: one rescan suffices except a double publication (needs a second publisher holding the post-v2 lock — accepted bound, same as `MAX_ACTIVE_RELEASE_LOCK_SCANS` `conversation_pins.py:55`; surfaces as the byte-identical diagnosis); no stale identity map (every caller locks first in a fresh txn, `expire_on_commit=True`); bootstrap advisory → L0 order deadlock-free; first boot takes no L0; C49 pin genuinely coupled. Temp worktree removed; no DB leaked.
Ruling: M-a (shape test cannot detect a separate-transaction lock) — accepted, the race test catches it (S2). M-b (C49 seam table / C51 lock table) — carried to the whole-branch review. M-c — ledgered here (double-publication bound above).
Task 2: complete (commits `5c3cfd827..672d49734`, review clean, no fix round).

## Task 3 — 2026-09-27
Task 3: implementer DONE_WITH_CONCERNS at `bac431068` (TASK_BASE `8a31338c6`): `fd0d3ce76` test-only (`git diff 8a31338c6 HEAD -- src` empty) — `tests/integration/test_graph_release_session_ordering_postgres.py` (29: 7 publication-first, 7 creation-first, 14 half-written-publication C8-3, 1 sequential; all 7 creators), enrolled in integration-graph + CI pin. Gates: new 29, publication 21, mixed creation 14, pin creation 2, pin acceptance 1, CI collection 16 — zero skips; no DB leaked. Mutations: plan reviewer sabotage `MAX_ACTIVE_RELEASE_LOCK_SCANS = 1` RED 14/29 (SPENT); raw COMMIT after v2 insert RED 14/29 (440 s bounded); creator locks first release RED 15/29; publisher parent lock shared RED 14/29; commit-on-raise weak (PendingRollbackError) — replaced by the raw-COMMIT one.
Deviation: publisher PID via `before_cursor_execute` on its first statement (so C6's sabotage still records a PID) — ACCEPTED.
Concern 1 re-probed by controller: `tests/unit/test_usage_service.py` 20/20 alone at 00:09 UTC; its `NOW = datetime.utcnow()` is fixed at import (`:80`), so a full run crossing UTC midnight fails it — PRE-EXISTING flake, not #269. Candidate GitHub issue (user to file; GitHub is read-only here).
Task 3: controller sabotage (C6, re-aimed) — publisher reads the release unlocked and locks only `graph_draft` (`CTRL269_3_C6`, anchor 1). New PG file: RED 14/29 — primary `test_publication_first_each_creator_pins_exact_new_release[×7]` "was never blocked by the paused publisher"; secondary `test_creation_first_publisher_waits_and_creator_keeps_v1[×7]` at the `pg_stat_activity` query assertion — exactly as C6 predicts. Restored from `bac431068`, clean, marker 0.
Task 3: review (Sonnet): spec PASS, quality PASS — 0/0/0. Reviewer sabotage (harness non-vacuity): publisher pause never set → RED 21/29 (publication-first ×7, partial-release ×14; the 7 creation-first + 1 sequential do not wait on the pause), restored GREEN 29/29. Creator coverage matches every `lock_active_graph_release` call site (`session_manager.py:759, :897, :1245`). Waits bounded; holders released in inner finally; C5 satisfied; C24 imports, no duplicate helper; CI enrolment `test.yml:466` + pin. Temp worktree removed; no DB leaked.
Task 3: complete (commits `8a31338c6..fd0d3ce76`, review clean, no fix round).
