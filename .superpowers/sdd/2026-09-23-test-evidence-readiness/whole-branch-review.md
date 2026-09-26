# #268 whole-branch review: test evidence, verdicts and draft readiness

- **Reviewer:** final whole-branch reviewer (Opus).
- **Range:** `82309f48d..9a55508a9` (34 files, +8585/−131). Diff: `/tmp/wbr-268.diff`.
- **Branch and worktree:** `feat/test-evidence-readiness-268`, `.worktrees/issue-268-plan`.
- **What I read:**
  - `progress.md` (all of it);
  - `PLAN-CORRECTIONS.md` (all of it);
  - task reports 1–4 and 6, and `task-2-review.md`;
  - issue #268's acceptance criteria;
  - #269's C29, C32 and C33;
  - the whole source diff: the service, routes and schemas, the TS client, the reducer and hook, the panel and workbench, the guard fixture, and the join tests.

## Verdict: **MERGE AFTER FIXES**

- **Findings:** 0 Critical, 0 Important, 5 Minor.
- **Required fix:** one, N1. It is Minor, but the ledger already commits it to this wave.
- **Recommended fix:** m2, in the same wave.
- **Everything else:** accepted or parked, as listed below.
- The backend has no cross-cutting defect. There is ONE eligibility clause, the lock order is acyclic, and every writer is atomic.

---

## 1. Writer-by-writer comparison

Every path that writes `agent_test_run` verdict columns or deletes `agent_test_run` rows, plus #267's run and case writers.

### #268 writers and readers

**`record_verdict`** (`agent_test_workbench.py:1471`)
- **Transaction:** its own. It calls `_require_no_transaction`, then `with session.begin()`. It validates before touching the session.
- **Locks, in order:** L3 only: `SELECT … WHERE id=:id FOR UPDATE`, with `populate_existing` (`:531`).
- **Predicates:**
  - the row exists, or 404;
  - `execution_status='completed'`, or `not_completed`;
  - for `approved`, also `deterministic_checks_passed`, or `checks_failed`;
  - an identical `(verdict, reviewer, notes)` writes nothing.
- **Write:** one Core UPDATE of exactly the four verdict columns, with `verdict_at=now()`.
- **Re-check after the wait (C33):** yes. Every predicate is on the locked row itself. `FOR UPDATE` returns the committed version, and `populate_existing` defeats the identity map. The predicate columns are immutable anyway (C24 trigger).
- **Tests:**
  - `test_postgres_verdict_waits_on_the_run_row_lock_and_decides_on_the_fresh_row`, observed by PID;
  - `test_the_lock_read_refreshes_a_run_already_cached_in_the_session`.

**`draft_readiness`** (`:1534`)
- **Transaction:** its own.
- **Locks, in order:** L0 release, then draft, `FOR SHARE` (`_lock_current_parents(exclusive=False)`). After that, plain SELECTs.
- **Predicates:** the shared `eligible_approval_clause`, plus `_current_candidate_evidence_clause` for the newest-run fallback.
- **Re-check after the wait (C33):** N/A. It makes no write and takes no row lock after L0, so there is no EPQ. It reads one statement snapshot (C11). The snapshot is consistent but can be stale, which is C32.

**`readiness_under_parent_lock`** (`:1543`)
- **Transaction:** the caller's. It raises unless `in_transaction()`.
- **Locks:** none; the caller holds L0.
- **Predicates:** the same as `draft_readiness`.
- **Re-check (C33):** N/A, because it is informational (C32).

**`cleanup_unpublished_test_runs`** (`:1634`)
- **Transaction:** its own. It validates first.
- **Locks, in order:**
  1. L0 release, then draft, `FOR SHARE`;
  2. L3: the target runs `FOR UPDATE OF agent_test_run ORDER BY id` (`_cleanup_targets_statement`, `:737`);
  3. the DELETE's own locks, on rows it already holds.
- **Predicates:** `_deletable_candidate`, which is:
  - `run_kind='candidate'`;
  - AND NOT `_linked_run`;
  - AND NOT `_retained_approval`. That is `EXISTS(case ⋈ draft_agent, is_active, is_required, **eligible_approval_clause**)`.

  Ranking is `row_number() OVER (PARTITION BY test_case_id ORDER BY run_at DESC, id DESC)`, taking `rn > limit`.
- **Re-check (C33):** yes, in a NEW statement (`_cleanup_delete_statement`, `:763`). Its fresh snapshot sees any verdict that committed during the step-2 wait. The single-statement form was measured to fail (Task 4 M3, reviewer `.offset(0)` probe). Pinned by the PG ordering test.

### #267 writers, for comparison

**`_persist_run`** (the #267 run insert)
- **Transaction:** its own, with a retry once on the parent handoff.
- **Locks, in order:** L0 release, then draft, `FOR SHARE`. Then the INSERT, whose FK checks take implicit `KEY SHARE` on the case, release and revision rows.
- **Predicates:** none on other runs. The currency flags are informational.
- **Re-check (C33):** N/A, because it only inserts.

**`create_test_case`, `update_test_case`, `deactivate_test_case`** (#267, L2)
- **Transaction:** their own.
- **Locks, in order:** L2 only: the role's case rows, unfiltered, in id order, `FOR UPDATE`. They take no L0.
- **Predicates:** their required-coverage rules, evaluated on a re-read after the lock.
- **Re-check (C33):** yes: the lock is unfiltered and the re-read is a new statement.

### One eligibility predicate

`grep -n eligible_approval_clause` finds:
- its definition at `:640`;
- readiness's use at `:693`;
- cleanup's use at `:723`.

There is no other copy:
- The only other `verdict == 'approved'` in the diff is the writer's own `if verdict == "approved"` guard.
- `_current_candidate_evidence_clause` is the identity half, and `eligible_approval_clause` composes it. It is not a divergent copy.
- Cleanup adds `is_active`/`is_required`, which readiness applies in its outer WHERE, so the two readers select the same cases.

Sabotage S1 (§9) proves that a diverged copy is caught.

## 2. Lock order

Global order: L0 release → L0 draft → L1 draft agents → L2 case rows → L3 run rows.

**`record_verdict` (#268)**
- Order: L3 (1 row).
- Waits on: #269 gate L3 or cleanup L3.
- Can hold while waiting? No; it holds nothing before its L3.

**`draft_readiness` (#268)**
- Order: L0 S, then plain reads.
- Waits on: a draft save (L0 X) or publication (L0 X).
- Can hold while waiting? No.

**`readiness_under_parent_lock` (#268)**
- Order: none.
- Waits on: nothing.

**cleanup (#268)**
- Order: L0 S, then L3 X in id order.
- Waits on: a verdict writer's L3, or another cleanup's L3 (both in id order).
- Can hold while waiting? It holds L0 S while waiting on L3. No L3 holder ever waits on L0: the verdict writer takes no L0, and a second cleanup already holds L0 S, which is compatible.

**#267 run insert**
- Order: L0 S, then an implicit KEY SHARE on the case row.
- Waits on: a case writer's L2 FOR UPDATE. The case writer takes no L0, so there is no cycle.

**#267 case writers**
- Order: L2 X, unfiltered, in id order.
- Waits on: another case writer, or #269's L2 share.
- Can hold while waiting? L2 only, and nothing that waits back on it.

**draft save (#267/#266)**
- Order: L0 X, then L1.
- Waits on: L0 S holders (readiness, cleanup, run insert).

**#269 publication (planned)**
- Order: L0 X → L1 → L2 S (unfiltered, C29) → L3 X in id order (C33 addendum).
- Waits on: case writers (L2), a verdict writer (L3).
- Holds L0 X while waiting on L2/L3. Neither the case writers nor the verdict writer ever request L0.

**Ruling: deadlock-free.**
- Every #268 path takes a prefix-respecting subsequence of the global order.
- L3 multi-row lockers (cleanup, and #269's gate and linker) all lock in `ORDER BY id`.
- The only holders that wait "downward" are the ones that hold L0: cleanup and publication. The rows they wait on are held by writers that never ask for L0.
- Publication and cleanup exclude each other at L0, so the RESTRICT FK from `graph_release_test_run` never races a cleanup DELETE.

## 3. Rollback guarantee

- **`record_verdict`:** one UPDATE inside `with session.begin()`.
  - Every refusal raises inside the block: `TestRunNotFound`, `IneligibleForApprovalError`.
  - `VerdictRejected` is raised before the block.
  - An `IntegrityError` (DDL checks, a trigger) propagates out of the context manager, which rolls back. Pinned: `test_postgres_a_verdict_trigger_error_surfaces_as_the_integrity_error` asserts the four columns are still NULL.
  - No partial verdict is possible: it is one statement over four columns.
- **cleanup:** the target SELECT and the DELETE run in one transaction. The DELETE is one statement, so it is all or nothing. It catches no exception.
- **readiness:** writes nothing.
- **Route:** `record_agent_test_run_verdict` catches only `VerdictRejected`, `TestRunNotFound` and `IneligibleForApprovalError`. None of them is an `IntegrityError` superclass, so an `IntegrityError` becomes a 500 (C7). Readiness catches only `GraphConfigurationIntegrityError`, which is not a DB error.
- **Nothing swallows an `IntegrityError`.** #267's `_persist_run` maps `SQLAlchemyError` to `TestRunUnavailable`; that is #267's existing contract and outside #268's writers.

**Ruling:** every #268 writer leaves the database unchanged on failure.

## 4. Contract parity

**Evidence (with the four verdict keys)**
- **Python:** `TestRunEvidenceResponse` is `extra=forbid`. The four keys are required and nullable, with `verdict: Literal[approved, rejected] | None`.
- **TypeScript:** `TEST_RUN_KEYS` requires exact keys. `isVerdictRecord`:
  - requires verdict, reviewer and time all null or all set;
  - requires notes to be null when there is no verdict;
  - requires `verdict ∈ TEST_RUN_VERDICTS`.
- **Join:** `test_the_client_run_keys_are_exactly_the_server_evidence_fields` pins the four keys, and `test_the_client_verdict_choices_are_the_servers` pins the choices.
- **Ruling:** TS is stricter on pairing, which the service guarantees. Nothing is loosened.

**Readiness**
- **Python:** three `extra=forbid` models. They use snake_case, have no aliases, and `status` is a 4-code Literal, with `ge` bounds and `AgentKey`/sha patterns.
- **TypeScript:** three exact-key lists, the codes and the sha pattern, positive and non-negative ints that match `ge=1`/`ge=0`, plus a case-inside-its-own-role check and a role-unique check.
- **Join:** `test_draft_readiness_client_join.py`: the three key sets, strict snake_case on both sides, and the status codes.
- **Ruling:** TS is stricter (role nesting, uniqueness). Nothing is loosened or aliased (`grep alias` in the diff: none).

**Verdict request**
- **Python:** `VerdictRequest(_StrictDraftRequest)` is `extra=forbid, strict=True`, with `{verdict: str, notes: str | None}` and both keys required.
- **TypeScript:** `VERDICT_REQUEST_KEYS` always sends `notes`, null when absent.
- **Join:** `test_the_client_verdict_body_is_exactly_the_server_request`.
- **Ruling:** parity.

**Refusals**
- **Python:**
  - 404 `{"detail":"Test run not found"}`;
  - 403 `{detail}`;
  - 422 `ineligible_for_approval {code, reason, message}`;
  - 422 `invalid_verdict {code, errors[]}`.
- **TypeScript:** `parseTestRunVerdictFailure` requires exact keys for each, and each reason must be one of the two.
- **Join:** the reasons and codes join; the 404 detail joins; the served fixture messages join.
- **Ruling:** parity.

## 5. Frontend

- **One reducer:** `draftEditorReducer` wraps `reduceDraftEditor`. The refresh counter is applied in that single wrapper.
- **One counter:** `nextRequestIdRef` is shared by readiness, test operations and history.
- **One gate:** `verdict` is in `TEST_OPERATIONS`, and `startTestOperation` refuses while any operation holds the gate. Readiness is ungated and uncounted in `operationsDisabled`.
- **Forbidden-action guard:**
  - `'Approve run'` and `'Reject run'` are appended as exact whole names; `forbidsActionName` normalizes whitespace, then does an exact `includes`.
  - The stems are untouched: the diff changes no stem line.
  - Both lengths are 7 (`AgentDefinitionWorkbench.test.tsx:378`, `agent-definition-workbench.spec.ts:1518`).
  - The negative assertions `Approve run and publish` and `Approve all` are present at both sites.
  - The nav badge is now outside the button (`aria-describedby`), so no control's text is "…Approved".
- **Readiness freshness:**
  - A response is dropped unless its request id is the latest.
  - A response is dropped as `stale` when `draft_lock_version` differs from the saved lock.
  - `draftStatus` also requires `readiness.candidate_hash === entry.saved.candidate_hash`, so a stale answer never paints Approved for a changed hash. The E2E "a readiness answer read at another lock never paints Approved" pins this.
  - Gaps: m2 and m3.

## 6. Readiness is informational (C32)

- **Backend:** readiness has no caller in `src/` except the GET route. No writer consults it: the verdict writer and cleanup use the shared SQL clause directly, not the readiness result.
- **Frontend:** readiness feeds only `draftStatus` (the badge text) in `AgentDefinitionWorkbench.tsx` and `DefinitionEditor.tsx`. No control's `disabled` reads `ready`, `all_ready`, `blocking` or `blocking_agents`: `grep` over `frontend/src` minus tests and the API module finds none.
- **Documentation:** the `readiness_under_parent_lock` docstring carries the four C32 prohibitions, and #269 C32 is written.

**Ruling:** confirmed. Nothing in #268 treats readiness as a gate.

## 7. Findings

### Critical
None.

### Important
None.

### Minor

**N1 — `recordVerdict` returns `true` when the reducer rejects an incoherent 200** (`useDraftEditor.ts:506`, with `draftEditorState.ts:1605`)
- The client throws on a `run_id`/`verdict` mismatch, but the reducer also requires `agent_key`. On a server bug, the notes clear under the invalid-response alert.
- **FIX NOW, as the ledger already committed:** return `recorded.agent_key === agentKey`, and add a Vitest test with a 200 whose `agent_key` is another role (the notes must survive).

**m2 — a probe or source-recovery 409 adopts a new lock without a readiness refresh** (`draftEditorState.ts:1273`)
- `mergeConflict` installs `conflict.server.draft` (a new `lock_version`) for `probeConflicted` and `sourceRecoveryConflicted`. `READINESS_REFRESH_OPERATIONS` excludes `probe` and `sourceRecovery`, so no fresh read is requested.
- The badges keep the previous lock's answer until the next write. It is safe per role, because of the hash check, and it is informational. But it is exactly the "adopted another admin's save" case, where a refresh matters.
- **Recommended fix, same wave:** request a refresh whenever `next.draft.lock_version !== state.draft.lock_version`, or add the conflict actions to the counter. Test: a probe 409 adoption issues one readiness GET.

**m3 — a failed readiness refetch keeps the previous answer on screen** (`draftEditorState.ts:1634`)
- Example: the admin rejects the only approved run, the verdict succeeds, and the readiness GET fails. The badge still says "Approved", because the hash has not changed.
- **PARK:** informational under C32, and #269's page re-reads anyway. If fixed, `readinessLoadFailed` after a write-requested refresh should clear `data`, so the badge falls to "Needs test".

**m4 — cleanup can delete one run too many in a race**
- The window is chosen before the L3 wait. If a run inside the retained window is approved while cleanup waits, it becomes protected and no longer takes a slot, but the run just past the window is still deleted.
- Only unprotected, unapproved runs are ever lost, and retention is a bound (C28).
- **ACCEPT.**

**m5 — cleanup's parent-handoff is not retried** (unlike `_persist_run`)
- With no caller (Q1), this is moot. #269 Task 2 moves the retry into `_lock_current_parents`.
- **ACCEPT; inherited on rebase.**

## 8. Parked and open items: adjudication

| Item | Ruling |
|---|---|
| Task 2 M1: the L0 precondition cannot be checked in code | **PARK** to #269. It is documented, and #269 C32 is the binding consumer; #269 may pass the locked rows in if it wants enforcement. |
| Task 2 M2: inside the gate, the readiness body may show `approved` where the gate lists a gap | **ACCEPT.** It is the safe direction only, and it is recorded in #269 C32 for its UI copy. |
| Task 2 M3–M5 | **ACCEPT.** M3 is an equivalent mutant, and its de-correlation guard REDs. M4 is closed by Task 3's 500 mapping. M5 is product-scoped (C11). |
| Task 3 M2: `verdict: str`, not a Literal | **ACCEPT.** The writer validates it and reports the ordered issues together; the response side is a Literal. |
| Task 3 M3: `notes` is required but nullable | **ACCEPT.** The client always sends it (`?? null`), and the join test pins it. |
| Task 4 M1: the unbatched target list, and one long L0-share transaction | **PARK** to Q1. It has no caller. Batch it (for example 500 ids per transaction) when a trigger is chosen, because a long L0 share delays draft saves and publication. The expanding `IN` is also bounded by SQLite's variable limit if cleanup ever runs there. |
| Task 4 M2: the no-runtime test never reached the DELETE | **CLOSED** (`e756a768d`). The test now deletes exactly one run with `per_case_limit=1`. |
| Task 4 M3: lock order is pinned only by compiled SQL | **ACCEPT.** A behavioural two-cleanup deadlock test is flaky by nature. Id-order L3 locking is carried to #269 (C33 addendum). |
| Task 6 I1, I2, m1–m5 | **CLOSED** in fix round 1; the scoped re-review passed. |
| Task 6 N1 | **FIX NOW** (see §7). |
| Q1: cleanup has no caller | **PARK, and flag to the user.** AC7's retention bound is implemented and tested but not enforced in production until a trigger is chosen. |
| Q2: worst-first badge | **ACCEPT** the default. |
| Q3: verdicts allowed on stale-candidate or retired-version runs; readiness ignores them | **ACCEPT.** Pinned by `test_a_verdict_on_a_stale_candidate_run_is_recorded` and the retired-version test. |
| Q5: show the newest completed baseline with its own verdict label | **ACCEPT.** |
| Q6: baseline runs are never cleaned | **ACCEPT.** Pinned by the 25-baselines test. |
| Q7: no withdrawal, only a flip | **ACCEPT.** |

## 9. Sabotage (cross-cutting, on the executed path)

Temp worktree: `/Users/robert.whiffin/Documents/slide-gen-branch-eval/wbr-268`, detached at `9a55508a9`. Pytest ran from inside it. Every edit was an exact-string replace with `assert count == 1`. It was removed afterwards (`git worktree remove`, `prune`), and the path is gone.

**S1 — cleanup's retained-approval clause diverges from readiness's.**
- **Change:** in `_retained_approval`, the call `eligible_approval_clause(run, case, draft_agent)` became an inline copy with the `candidate_hash` term dropped. Readiness's use of the shared clause was left unchanged.
- **Anchor:** count 1. **Marker:** `WBR268_S1_DIVERGE`, count 1, at `:723`, which is inside `_deletable_candidate` and so used by both cleanup statements.
- **RED:**
  - unit `test_agent_test_workbench.py`: 1 of 245 failed (`test_the_cleanup_statements_carry_every_protection_on_both_sides`);
  - PG workbench: 2 of 49 failed (`test_postgres_cleanup_deletes_a_stale_hash_approval_after_a_real_save`, `test_postgres_cleanup_waits_behind_a_draft_save_and_uses_its_new_hash`).
- **Restore:** `git checkout`. Porcelain was clean and the marker count was 0.
- **GREEN:** unit 245, PG 49.

**S2 — the verdict writer commits before the lock and gate.**
- **Change:** a separate `with session.begin()` that does the four-column UPDATE, placed before the locked transaction.
- **Anchor:** count 1. **Marker:** `WBR268_S2_EARLY_COMMIT`, count 1, at `:1498`.
- **RED:**
  - unit (workbench and routes files): 12 of 684 failed. They include:
    - `not_completed_for_either_verdict` ×4;
    - `checks_failed` (IntegrityError instead of the refusal);
    - identical re-submit;
    - lock-refresh;
    - `rejected_failing_run_cannot_flip`;
    - `reads_no_parent_or_case_lock_statement`;
    - route 422s ×3.
  - PG: 2 of 49 failed (`verdict_writes_the_four_columns_from_the_database_clock`, `verdict_waits_on_the_run_row_lock_and_decides_on_the_fresh_row`).
- **Restore:** `git checkout`. Porcelain was clean and the marker count was 0.
- **GREEN:** unit 684, PG 49.

## 10. Gates at HEAD `9a55508a9`

**Full unit** (`DATABASE_URL=sqlite:////tmp/wbr-268.sqlite`, `-q -p no:randomly -rf`): **6 failed / 6784 passed / 110 skipped.** These are exactly the baseline six, by node and cause:
- `test_deploy_autoscaling` ×2: `'provisioned' == 'autoscaling'`, and `…provisioned` called 0 times;
- the chokepoint ×3: `_FakeSession` has no `execute`;
- the persistence boundary ×1: "no active Graph Release".

**PostgreSQL**, one file per invocation, `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, 0 skips in every file:
- `test_agent_definition_workbench_postgres`: 49
- `test_graph_configuration_constraints_postgres`: 66
- `test_persisted_graph_runtime_failures_postgres`: 7
- `test_mixed_release_collaboration_acceptance_postgres`: 26
- `test_graph_configuration_bootstrap_postgres`: 3
- `test_agent_schema_overlay_postgres`: 10

The diff touches only the workbench PG file, which is already enrolled in CI's `integration-graph` step. No new PG file was added, so no CI edit is needed.

**Frontend:**
- Vitest: 16 files, 726 passed.
- `tsc -b`: clean.
- ESLint on the 13 changed frontend files: clean (exit 0). The whole-repo `eslint .` shows 94 errors, all in files #268 does not touch.

**Playwright** (`tests/e2e/agent-definition-workbench.spec.ts`): **78 passed.** The dev server was started by Playwright and stopped, and nothing is left listening on :3000.

**Hygiene:**
- There is no `.venv` and nothing was installed.
- `tellr_int_*` databases: the same 4 older ones before and after, so nothing leaked. `ai_slide_generator` was not touched.
- The tree is clean apart from this file, which is not committed.
