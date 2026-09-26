# #268 Task 4 report: bounded cleanup of unpublished candidate runs

**Status: DONE_WITH_CONCERNS.** The concern is a deviation, not a defect. C19e reproduced, and the fix that C19e prescribes (one DELETE whose outer WHERE repeats the recheck) was measured **not** to fix it. The implementation therefore uses two statements: it locks the targets, then deletes them in a second statement that repeats the recheck. See §4.

- TASK4_BASE: `8b897bfe4`
- Branch: `feat/test-evidence-readiness-268`
- Worktree: `.worktrees/issue-268-plan`

## 1. Commits

| SHA | Message | Files |
|---|---|---|
| `3b0d2070a` | feat: bounded cleanup with release-link and eligible-approval exclusions (#268) | `src/services/agent_test_workbench.py`, `tests/integration/test_agent_definition_workbench_postgres.py`, `tests/unit/test_agent_test_workbench.py` |
| `24f2c496c` | test: pin cleanup's window to the case version row (#268) | `tests/integration/test_agent_definition_workbench_postgres.py` (closes the M16 survivor) |
| (this report) | docs: record #268 Task 4 report | this file, force-added |

## 2. What was built

`AgentTestWorkbench.cleanup_unpublished_test_runs(self, session, *, per_case_limit: int = 20) -> int` (C18, exact signature):

1. **Validation first, before the session is touched.** `per_case_limit` must be a strict `int` ≥ 1. A `bool`, `float`, `str`, `None`, 0 or a negative value raises `ValueError`.
2. It calls `_require_no_transaction`, then `with session.begin()`. The method owns its transaction.
3. **First statement:** `self._graph_configuration._lock_current_parents(session, exclusive=False)`. This is L0: release, then draft, `FOR SHARE`.
4. **Target statement** (`_cleanup_targets_statement`):
   - It ranks the deletable candidates of each case **row** with `ROW_NUMBER() OVER (PARTITION BY test_case_id ORDER BY run_at DESC, id DESC)`.
   - It selects the ids with `rn > per_case_limit`, then applies `ORDER BY id FOR UPDATE OF agent_test_run`. That lock is L3, taken in id order.
5. **DELETE statement** (`_cleanup_delete_statement`): `DELETE … WHERE id IN (:locked ids) AND <deletable(agent_test_run)>`. This is the C19e target-row recheck. It returns `rowcount`, and returns 0 without issuing a DELETE when there are no targets.

`deletable(run)` is `run_kind = 'candidate'` (C19a) `AND NOT linked(run)` (C19f) `AND NOT retained_approval(run)`:
- **`linked`** is `EXISTS (SELECT 1 FROM graph_release_test_run WHERE agent_test_run_id = run.id)`.
- **`retained_approval`** is an `EXISTS` over aliased `agent_test_case ⋈ graph_draft_agent ON agent_key`, correlated on `case.id = run.test_case_id`, with these terms:
  - `case.is_active IS true AND case.is_required IS true` (C19c adds these two);
  - **Task 2's unmodified `eligible_approval_clause(run, case, draft_agent)`**, which is reused, not copied.
- **Readiness is untouched:** the shared clause is not changed.

**Protected rows are removed before ranking (C19d).** So the latest N *unprotected* candidates per case row are kept, plus every protected row.

**Scope limits:**
- No case lock (C19g).
- No production caller, route or startup hook (C21).
- No runtime or model call (C27).
- No DDL (C30).

**Lock order** is L0 share, then L3 `FOR UPDATE` in id order. This is a prefix-respecting subsequence of #269's order (C28). Unlike the plan, cleanup takes its L3 row locks in an explicit SELECT before the DELETE.

## 3. Tests

**PostgreSQL** (`tests/integration/test_agent_definition_workbench_postgres.py`), 13 new tests.

Fixture rules:
- `run_at` and any verdict are set at INSERT.
- Links are raw SQL `INSERT INTO graph_release_test_run (…, evidence_kind, source_release_id) VALUES (…, 'approval', NULL)`.
- No run is ever approved by UPDATE.
- The C19e test approves through the real `record_verdict`.

Each assertion below is an exact id list.

- **Plan's five:**
  - 25 unprotected runs: returns 5, keeps `ids[5:]`.
  - Oldest run linked: returns 4, keeps `[ids[0], *ids[5:]]`.
  - Oldest run is an eligible approval: returns 4, same retained shape.
  - Both protections: returns 3.
  - A second call returns 0, with the retained set unchanged.
- **C20.1, stale case version:**
  - v1 is approved outside the window. Readiness first confirms it is the case's `approved` run.
  - A real `update_test_case` then supersedes it to v2.
  - Cleanup returns 5 and the approval is deleted.
- **C20.2, stale hash:** the approval is confirmed by readiness, then a real `save_editable_model_draft` runs. Cleanup returns 5.
- **C20.3, baselines:**
  - 25 `published_baseline` runs, alternately approved and unreviewed, all newer than 4 older candidates.
  - Cleanup returns 0 and every row stays.
  - This also proves that baselines take no window slot.
- **C20.4, optional case:** an approval on an active **optional** case outside the window is deleted. Cleanup returns 5.
- **C19b / S4c, ties:** 21 runs in one transaction tie on `run_at`. The lowest-id tied run (plus the older source run) is deleted.
- **C19d, per case row** (commit 2): 15 runs on v1 and 15 on v2 make two windows, so cleanup returns 0. With `per_case_limit=10`, it deletes 5 + 5.
- **C20.5 / C19e, ordering:**
  1. `record_verdict` approves X, the oldest run at rank 21+. It is paused by an `after_cursor_execute` hook after its UPDATE, before commit, and its PID is captured with `SELECT pg_backend_pid()` on the same connection.
  2. Cleanup starts. Its PID is captured by a `_lock_current_parents` override **before** its first statement.
  3. The test waits, bounded to 10 s, until `writer_pid = ANY(pg_blocking_pids(cleanup_pid))`, and asserts cleanup is not done.
  4. It releases the writer.
  5. It asserts that X survives with verdict `approved`, cleanup returns **4**, and the retained set is `[X, *ids[5:]]`.
  - Every wait has a timeout: writer pause 10 s, blocked observation 10 s, hook release 20 s, both results 10 s. A `finally` block always releases the writer and removes the hook.
- **C20.6, ordering behind a draft save:**
  1. A real draft save is paused right after its L0 `FOR UPDATE` statement, and its PID is captured.
  2. Cleanup is observed blocked by that PID through `pg_blocking_pids`.
  3. After the save commits, the old-hash approval outside the window is deleted, and cleanup returns 5.

**SQLite unit** (`tests/unit/test_agent_test_workbench.py`), 14 new test items:
- **Argument validation**, parametrized: `0, -1, True, False, 1.0, 20.0, "20", None` all raise `ValueError`.
- **Validation happens before the session is touched:** an untouchable session object is used.
- **An open transaction** raises `RuntimeError`.
- **The default limit and a limit of 1** are accepted.
- **Statement sequence:**
  - `_lock_current_parents` is called once with `exclusive=False`;
  - exactly 3 statements are issued: the parent `SELECT`, then the target `SELECT` with `row_number`, then a `DELETE` without `row_number`;
  - exactly 1 of 2 runs is deleted.
- **Compiled SQL:** both the ranked set and the DELETE carry every protection term, the window order, `rn >` and `ORDER BY id FOR UPDATE OF agent_test_run`.
- **C27:** an exploding runtime is used, `get_agent_test_runtime` is monkeypatched to raise, and `_runtime` is patched to raise. Cleanup still succeeds.

RED first: all 12 original PG tests failed with `AttributeError: … no attribute 'cleanup_unpublished_test_runs'`. The 2 ordering tests failed at their bounded `attempted.wait` for the same reason. The unit tests were written before the method existed.

## 4. C19e: reproduced, and the prescribed fix is insufficient

**Measured, not reasoned.** The first implementation was the prescribed single statement:

```sql
DELETE … WHERE id IN (ranked) AND <deletable(agent_test_run)>
```

It went RED on the C20.5 ordering test with `NoResultFound`: X was deleted **even with the outer recheck present**.

**Cause.** `EXPLAIN VERBOSE` was run on a throwaway database `t268_4_explain`, which was created and dropped by me. It shows that PostgreSQL plans each `NOT EXISTS` as a **Nested Loop Anti Join**, with `agent_test_case_2.ctid` and `graph_draft_agent_2.ctid` carried as row marks. EvalPlanQual re-runs the join for the updated target tuple against the *originally fetched* rows of the other relations. For an anti-join whose inner side originally matched nothing, it again finds nothing, so the approved row still qualifies.

**Fix.**
1. Lock the targets with `SELECT … FOR UPDATE` in id order. This waits for the writer.
2. Then issue the DELETE, with the full recheck, as a **new statement**. Its READ COMMITTED snapshot is taken after the lock was granted, so it sees the committed approval.

The DELETE still carries the outer target-row recheck, as C19e asks, and it now works.

**Proofs, each restored from an explicit SHA:**
- **M3:** restore the single-statement version. The ordering test goes RED (`NoResultFound`). This is the reproduction.
- **M2 / S4b:** remove only the DELETE's recheck. The ordering test goes RED (`NoResultFound`), plus the compiled-SQL unit test. Every sequential test stays GREEN, as §12 predicts.
- **M11:** remove `FOR UPDATE` from the target statement. The ordering test goes RED, because the DELETE snapshot predates the commit and the anti-join EPQ problem returns.

**Carried to #269.** Any locking DELETE or UPDATE whose protection is a correlated `NOT EXISTS` over other tables has this hazard under READ COMMITTED. This includes #269's own gate re-checks. #269 should either lock first and re-check in a new statement, or prove its plan with an ordering test.

## 5. Gates

All commands are run from the worktree with `PYTHONPATH=<tree>:<tree>/packages/databricks-tellr`, the pyenv python and `-p no:randomly`.

| Gate | Result |
|---|---|
| Full unit, `DATABASE_URL=sqlite:////tmp/t268-4.sqlite`, `-rf` | **6 failed / 6774 passed / 110 skipped**. These are exactly the 6 baseline nodes, with their causes re-checked: autoscaling `'provisioned' == 'autoscaling'` and `…provisioned … Called 0 times`; chokepoint ×3 `'_FakeSession' object has no attribute 'execute'`; persistence boundary `ConversationGraphReleaseIntegrityError: no active Graph Release`. There is no regression. |
| `tests/integration/test_agent_definition_workbench_postgres.py` | **49 passed, 0 skipped** |
| `tests/integration/test_graph_configuration_constraints_postgres.py` | **66 passed, 0 skipped** |
| `ruff check` on the 3 changed files | clean |
| `ruff format --check` | not a gate. The files were already unformatted at TASK4_BASE (the base `agent_test_workbench.py` also "would reformat"), so I did not reformat them, to keep the diff reviewable. |
| Throwaway databases | Only the 4 pre-existing `tellr_int_*` remain. My `t268_4_explain` was dropped. `ai_slide_generator` was not touched. |
| Environment | no `.venv`, nothing installed, no `uv` |

## 6. Mutation sweep

**Scope for every row:** `tests/unit/test_agent_test_workbench.py` and `tests/integration/test_agent_definition_workbench_postgres.py`, with `-k "cleanup or rechecks"`. That is 27 items after commit 2, and 26 for rows run before it.

Each mutation was applied by an exact-count string replacement (a count other than 1 aborts), then restored with `git checkout 3b0d2070a -- src/services/agent_test_workbench.py`. The src file is identical at `3b0d2070a` and `24f2c496c`, and `git diff --quiet` was confirmed after each restore.

| # | Mutation | Result | RED tests |
|---|---|---|---|
| M1 (S4, controller target) | drop `~_retained_approval` from `_deletable_candidate`, i.e. every cleanup use site; the helper itself is unchanged | RED 5 | compiled-SQL unit test; PG eligible-approval, both-protections, idempotent, C19e ordering |
| M2 (S4b) | DELETE without the target-row recheck | RED 2 | C19e ordering (`NoResultFound`); compiled-SQL unit test |
| M3 | the plan's single-statement DELETE with the outer recheck | RED 1 | C19e ordering (`NoResultFound`). **This is the reproduction.** |
| M4 (S4c) | drop `id DESC` from the window | RED 3 | **PG tie test**, statement-sequence unit test, compiled-SQL unit test |
| M5 | drop `run_kind = 'candidate'` | RED 2 | PG baselines test; compiled-SQL unit test |
| M6 | drop `case.is_active` | RED 2 | PG stale-case-version test; compiled-SQL unit test |
| M7 | drop `case.is_required` | RED 2 | PG optional-case test; compiled-SQL unit test |
| M8 | drop the linked exclusion | RED 4 | PG linked, both, idempotent (FK `23503` from the RESTRICT backstop); compiled-SQL unit test |
| M9 | `exclusive=True` parent lock | RED 1 | statement-sequence unit test (`calls == [False]`) |
| M10 | no parent lock | RED 3 | statement-sequence unit test; PG draft-save ordering; PG C19e ordering (its PID capture is in the lock override) |
| M11 | no `FOR UPDATE` on the targets | RED 2 | PG C19e ordering; compiled-SQL unit test |
| M12 | no `ORDER BY id` on the target lock | RED 1 | compiled-SQL unit test only. There is no behavioural test for lock order, which is deadlock avoidance between two concurrent cleanups. |
| M13 | allow a `bool` | RED 1 | `[True]` (`False` is still refused, by `< 1`) |
| M14 | `< 1` becomes `< 0` | RED 2 | `[0]`; validate-before-session |
| M15 | `rn >` becomes `rn >=` | RED 14 | nearly every test |
| M16 | partition by `agent_key` | RED 1, then RED 2 | first run: compiled-SQL only, a **survivor on behaviour**. Closed by commit 2's per-case-row test, and the re-run is RED 2 (the PG windows test and the compiled-SQL test). |
| M17 | remove the early `return 0` when there are no targets | GREEN | **Equivalent.** An empty `IN` deletes nothing and returns 0. It is kept only to skip a no-op statement. |
| M18 | no `_require_no_transaction` | RED 1 | `test_cleanup_owns_its_transaction` |
| M19 | call `self._runtime()` | RED 1 | C27 test |
| M20 | touch the session before validation | RED 1 | validate-before-session |

The shared `eligible_approval_clause` terms are Task 2's and are not mutated here, because readiness shares them. The compiled-SQL test does assert that each term appears once on both sides. One term cannot be reached by a behaviour test: a run on the *same* case row with a different `test_case_version`. That shape cannot arise through the writers (Task 2 made the same observation).

## 7. Deviations

1. **Two statements rather than one DELETE (C19e).** The reason is in §4. The DELETE still repeats the whole protection predicate on the target row. Before it, a `SELECT … FOR UPDATE` in id order locks the targets. This adds one statement and an explicit L3 lock step, and C28's row for cleanup still holds: L0 share, then L3.
2. **The C20.6 "draft save"** is the real `save_editable_model_draft`, paused right after its L0 `FOR UPDATE` statement, not a hand-built row change. The hash change itself happens after the pause and before commit, and cleanup waits for that commit.
3. **The C20.3 baseline test** is stronger than asked: it adds 4 older candidates, to prove that baselines neither get deleted nor take window slots. Half the baselines are approved.
4. **Extra tests beyond C20:** the tie test (S4c), the per-case-row window test (after M16), a compiled-SQL protection test, a statement-sequence test, and a validate-before-session test.
5. **Early `return 0`** when there are no targets (M17, equivalent).

## 8. Concerns

1. **C19e generalises to #269 (carry it).** In a locking DELETE or UPDATE under READ COMMITTED, a correlated `NOT EXISTS` over other tables is **not** re-evaluated by EPQ against current data when the planner turns it into an anti-join. #269's gate, and any future protected write, must lock first and re-check in a new statement, or prove its plan with an ordering test. PLAN-CORRECTIONS C19e's prescribed fix should be amended to say so.
2. **Visible effect of a concurrent verdict.** A verdict submitted on a run that cleanup has locked and then deletes gets `TestRunNotFound` (the existing 404) once cleanup commits. This is correct: the run is gone. But it is visible to an admin if cleanup is ever wired to run while people review. C21 leaves the caller open (Q1).
3. **The window is off by one in the race.** In the C19e race, cleanup deletes 4, not 5 (X was protected mid-flight). The next call converges. This matches C28's "off by at most one".
4. **Lock order among concurrent cleanups** (`ORDER BY id` before `FOR UPDATE`) is pinned only by compiled SQL (M12).
5. **No production caller** (C21 / Q1): the retention bound is not enforced until Q1 is answered.
