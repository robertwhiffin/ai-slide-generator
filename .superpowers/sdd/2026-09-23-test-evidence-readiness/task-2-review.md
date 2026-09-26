# #268 Task 2 review: readiness query service

**Reviewer:** independent task reviewer. **Range:** `c410f34d5..6caac0247` (HEAD `905209759` adds docs only).
**Read:** `task-2-brief-raw.md`, `PLAN-CORRECTIONS.md` C9–C14, C27, C28, §11–§12, `progress.md` (Q2, Q3, Task 2), `task-2-report.md`, the source diff, the readiness tests, #269's PLAN-CORRECTIONS C1/C29/C30, its plan's gate (`:465-500`, `:705-760`), preview (`:799-810`) and handoff-retry row (`:223`), and #269's `progress.md`.

## Spec Compliance — PASS

| Requirement | Where | Verdict |
|---|---|---|
| C10 two entry points; route entry owns txn + L0 share; binding never begins/commits, refuses without txn | `draft_readiness`, `readiness_under_parent_lock` | PASS (binding identity pinned by `test_the_locked_entry_point_runs_inside_the_callers_exclusive_lock`) |
| C11 one shared predicate (candidate, case id+version, role, current draft hash, approved, completed, passing) | `eligible_approval_clause` over `_current_candidate_evidence_clause` | PASS — the compiled PostgreSQL SQL carries all nine terms in both subqueries (six identity terms in the newest-run lookup) |
| C11 any eligible approval ⇒ `approved`, `run_id` = newest eligible (`run_at DESC, id DESC`) | `_readiness_statement`, `_case_readiness` | PASS |
| C11 fallback map from newest current candidate run | `_case_readiness` | PASS (rejected branch redundant, M17 equivalent — agreed) |
| C11 only changed roles block; changed predicate = `ModelAgentNodeSnapshot.changed` | `readiness_under_parent_lock` | PASS — same `candidate_hash != revision.content_hash` as `graph_configuration_workbench.py:325` |
| C11 changed role with no active required case ⇒ `missing_required_case`, not ready, in `blocking_agents` | same | PASS |
| C11 one statement, correlated scalar subqueries, no LATERAL, no case lock | `_readiness_statement` | PASS |
| C12 `run_kind='candidate'` in both lookups | shared identity clause | PASS |
| C13 fixture rules (real save / supersede / no run UPDATE / increasing `run_at` / ties) and its three extra tests; >20-runs test moved to Task 4 | tests | PASS |
| C14 types (frozen, tuples, `__test__ = False`, `missing_required_case`, snake_case literal) | dataclasses | PASS |
| C27 no runtime/model | both entries | PASS |
| Q3 stale-candidate / retired-version approvals ignored | identity terms; retired rows not listed; supersede ⇒ new id | PASS (tests: stale-hash, other-case-version, v1→v2 supersede) |
| Q2 worst-first badge | — | N/A for Task 2: there is no role-level status in the result; the per-case statuses Task 6 needs (C25) are all present |

Checked against #267's data: candidate runs store the draft's `candidate_hash` at run time (`execute_candidate_run` `_RunIdentity`), a supersede retires row *n* and inserts a new id (so the case-id term alone also covers PG supersede, as the implementer's M3 note says), and `run_kind` is DDL-limited to `candidate`/`published_baseline`. The predicate matches all three.

## Strengths
- A single identity clause feeds both lookups, so hash/kind/version edits cannot drift between "eligible" and "newest" (C12/S2 rationale holds; both plan targets and the controller's version target RED).
- The compiled-SQL term-list test closes the DDL-implied survivors (completed/passing) that behaviour tests cannot reach.
- The binding test asserts transaction *identity*, not just `in_transaction()` — this is what catches a "begin its own transaction" regression (see R3a).
- The report's C29 analysis is honest about the staleness window, and it says outright that readiness must not be the gate.

## Issues

### Critical
None.

### Important
**I1 — the "readiness is informational, never the gate" constraint was not carried to #269, and it is not in the code.** `progress.md` Task 2 says "Carried to #269's ledger". Grepping `.worktrees/issue-269-plan/.superpowers/sdd/2026-09-25-graph-release-publication/{progress.md,PLAN-CORRECTIONS.md}` for `readiness_under_parent_lock` or `informational` finds nothing. #269's Q4 is still open, and so is its Task 0-B re-probe. The `readiness_under_parent_lock` docstring says the method takes no lock, but it does not say it must not decide publication or choose the evidence to link. #269's own plan leaves room for that shortcut: its gate is ~40 lines of locking, while readiness already returns `all_ready`, `blocking_agents` and a per-case `run_id` that is exactly "the newest eligible approval" #269 links. **Fix:** add one docstring paragraph, and record the forbid-list below in #269's ledger (the controller must write it; this reviewer may not touch that worktree).

**What #269's plan must forbid:**
1. Using `all_ready`, `blocking_agents`, `missing_required_case` or `cases[].status` as the publish/refuse decision.
2. Linking `TestCaseReadinessItem.run_id`. It is read with no L3 lock, so a verdict can flip approved→rejected and commit between the read and the link insert; the C14 trigger only freezes verdicts that are already linked.
3. Skipping or short-circuiting the gate's own C29 sequence (unfiltered L2 `FOR SHARE` in id order → fresh re-select of active required cases → L3 `FOR UPDATE` on runs → re-verify) because readiness "already said ready".
4. Calling readiness after any publication write in the same transaction. After the rebase, readiness reads the transaction's own new `base_release_id`/hashes and reports every role unchanged and `all_ready=True`. autoflush would also flush pending ORM state into its reads.

Readiness may only feed the preview body and the `publication_not_ready` body.

### Minor
- **M1 — the L0 precondition cannot be checked.** `readiness_under_parent_lock` checks only `in_transaction()`. The draft/base hashes (separate statements) and the statement's own `graph_draft_agent` join are consistent only if L0 is held. A caller that is in a transaction but holds no L0 gets silent skew. Keep the precondition documented; if #269 wants it enforced, it can pass the locked `(release, draft)` rows in.
- **M2 — the 409 body can contradict the gaps.** Inside #269's gate, readiness runs after the gate's L3 query, on a newer snapshot. Case rows are frozen by the gate's L2 lock, because `create_test_case`/supersede serialize on `_lock_role_rows`. Runs are not: a new run, or a verdict on a run the gate did not lock, can commit in between. So `readiness` may show a case `approved` (or a different newest status) that `locked_gaps` lists as `no_eligible_approval`. The disagreement only ever runs in that safe direction. Record it for #269's UI copy/tests; not a #268 defect.
- **M3 — `.correlate(AgentTestCase, GraphDraftAgent)` is an equivalent mutant (R1).** SQLAlchemy auto-correlates the ON-clause scalar subquery, and the compiled PostgreSQL SQL is byte-identical without it. Keep it as documentation; its guard is real — `.correlate(None)` REDs 4 (R1b).
- **M4 — handoff error (accepted).** `draft_readiness` propagates `GraphConfigurationIntegrityError("…parent snapshot is inconsistent")`, which is exactly `read_workbench`'s behaviour. #269 Task 2 puts the retry inside `_lock_current_parents` itself (#269 plan `:223`), so readiness inherits it on rebase with no #268 change. Task 3's route must map it identically to the workbench read; this is already carried in the ledger.
- **M5 — (product note, not a defect).** Eligibility is content-hash identity, with no `compared_release_id` term. If a role is edited back to content approved under an older base, those old approvals count again. This is what C11 specifies and what #269's gate does too; flag it only if product wants evidence scoped per base release.

## Sabotage evidence
Temp worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-268-2` (detached at `6caac0247`), pytest run from inside it, whole file, `-q -p no:randomly`, `DATABASE_URL=sqlite:////tmp/rev-268-2.sqlite`. Baseline before any mutation: unit 231 passed, PG workbench file 36 passed with 0 skips. Each mutation used a Python exact-string replace that asserted `count == 1`. Each restore was `git checkout -- src/services/agent_test_workbench.py`, followed by `git diff --quiet` → CLEAN and marker `grep -c` → 0.

| # | Mutation | Anchor | Marker `grep -c` | RED | Notes |
|---|---|---|---|---|---|
| R1 | drop `.correlate(AgentTestCase, GraphDraftAgent)` in `_newest_run_id` | 1 | `REV268_2_M1` = 1 | **GREEN** 231/231 unit; PG 36/36 | Equivalent mutant: the compiled PG SQL is identical with and without it (diffed). Not a test gap. |
| R1b | `.correlate(None)` (a real de-correlation) | 1 | `REV268_2_M1b` = 1 | 4/231: `test_approving_v1_then_superseding_it_needs_a_test_for_v2`, `test_a_run_of_another_case_does_not_count`, `test_one_blocking_changed_role_makes_the_draft_not_ready`, `test_only_active_required_cases_are_listed_in_id_order` | Proves correlation is guarded |
| R2a | swap the eligible/newest run tuples in `_case_readiness` | 1 | `REV268_2_M2a` = 1 | 17/231: `test_a_completed_passing_unreviewed_run_is_awaiting_review_and_blocks`, `test_a_rejected_run_is_test_failed_and_blocks`, `test_an_older_approval_beats_a_newer_rerun_of_the_same_hash[unreviewed,rejected,model_error]`, `test_without_an_approval_the_newest_candidate_run_decides[rerun-after-reject,reject-after-run,model-error,checks-failed,incomplete]`, `test_without_an_approval_a_tied_run_at_is_decided_by_the_higher_id`, `test_without_an_approval_run_at_outranks_a_higher_id`, `test_an_approval_that_differs_in_one_identity_term_is_never_found[stale-hash,other-case-version,baseline-kind,other-role]`, `test_a_run_of_another_case_does_not_count` | — |
| R2b | swap the condition: `if row.newest_id is not None` ⇒ approved | 1 | `REV268_2_M2b` = 1 | 14/231: the R2a set minus the three `older_approval_beats…` params | — |
| R3a | the binding begins its own transaction: `session.commit(); session.begin()` after the guard | 1 | `REV268_2_M3a` = 1 | 39/231. The precise catch is `test_the_locked_entry_point_runs_inside_the_callers_exclusive_lock` (`assert session.get_transaction() is transaction` fails). The other 38 fail through `draft_readiness`'s `with session.begin()` (`InvalidRequestError: Can't operate on closed transaction inside context manager`) | This is the transaction guard that protects #269 |
| R3c | the binding opens a SAVEPOINT (`session.begin_nested()`) | 1 | `REV268_2_M3c` = 1 | 1/231: `test_readiness_writes_nothing_and_reads_cases_and_runs_in_one_statement` (`SAVEPOINT sa_savepoint_1` is not a SELECT) | A subtler own-transaction variant is still caught |

After all restores: `git diff --quiet 6caac0247` CLEAN; unit **231 passed**; PG `tests/integration/test_agent_definition_workbench_postgres.py` **36 passed, 0 skips** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`). `test ! -e .venv` held before and after. The temp worktree was removed with `git worktree remove` + `prune`, and the path no longer exists. Nothing was installed, `ai_slide_generator` was not touched, and no other worktree was modified.

## #269 fit (named risks)
- **Deadlock:** none possible from readiness. `readiness_under_parent_lock` issues only plain SELECTs, and a PostgreSQL plain SELECT never waits on row locks. It is safe inside #269's L0-exclusive transaction, and safe before or after the C29 L2/L3 locks. Because it takes no lock, it cannot invert #269's global order (C28).
- **C29-safety argument:** it holds. Under READ COMMITTED one statement has one snapshot shared by its correlated subqueries, and no row goes through EvalPlanQual re-checking. So a supersede is seen whole or not at all. Two caveats: M1 (the L0 precondition cannot be checked) and M2 (inside the gate, readiness's snapshot is newer than the gate's view). The argument proves only that readiness is consistent, not that it is current. That is exactly why I1's forbid-list is needed.
- **Handoff:** acceptable (M4).
- **Read-only:** confirmed. All statements are SELECT (unit capture plus the PG shape test), there is no runtime (C27 tests), and there is no model.

## Task quality — PASS (with I1 to action before #269 Task 0-B)
The code is small, and every branch is explained by a correction. The tests are behaviour-first, with structural tests only where behaviour cannot reach. The mutation evidence is broad (27 implementer mutations plus 6 of mine, with 2 equivalents correctly identified). The only substantive gap is I1, a hand-off/documentation gap at the #269 boundary; the code itself has none.
