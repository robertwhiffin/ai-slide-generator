# #268 Task 2 report: readiness query service

**Status:** DONE_WITH_CONCERNS (the concerns are listed below; none blocks).
**TASK_BASE:** `c410f34d5da504e916a3a57272e7388539f9f523`.
**Commits:**
- `eddf8cad0` feat: draft readiness query per role and case (#268)
- `d3f64c3db` test: pin the readiness predicate terms and run ordering (#268)
- the commit that adds this report

## What was built (`src/services/agent_test_workbench.py`)

### Types (C14)
- `TestCaseReadinessItem` (with `__test__ = False`), `AgentReadinessItem` (adds `missing_required_case`) and `DraftReadinessResult`.
- All three are frozen, and their collections are tuples.
- `ReadinessStatus` holds the snake_case status literals.

### Shared predicate (C11, C19c)
- The one shared predicate is the module-level `eligible_approval_clause(run, case, draft_agent)`. Task 4 can import it from the same module, with no cycle.
- It is built on the private `_current_candidate_evidence_clause`, which holds the six identity terms:
  - `run_kind='candidate'`
  - case id
  - case version
  - `run.agent_key = case.agent_key`
  - `draft_agent.agent_key = case.agent_key`
  - `candidate_hash = draft hash`
- The eligible clause adds three terms: approved, completed, and `checks_passed IS true`.
- The newest-run lookup uses the same six identity terms. So one edit to the hash or kind term hits both lookups (C12 / S2).

### One statement (`_readiness_statement`)
- It reads the active required `agent_test_case` rows, joined to `graph_draft_agent` by role.
- It has two LEFT JOINs to `agent_test_run`, each on `id = (correlated scalar subquery ORDER BY run_at DESC, id DESC LIMIT 1)`: one for the newest eligible approval and one for the newest current candidate run.
- It takes no row lock and uses no LATERAL, so it is portable to SQLite.

### Status map
- Any eligible approval gives `approved`, and `run_id` is that approval.
- Otherwise the newest current candidate run decides:
  - no run gives `needs_test`;
  - `rejected` gives `test_failed`;
  - no verdict, completed and passed gives `awaiting_review`;
  - anything else gives `test_failed`.

### Blocking and readiness
- `blocking` is true when the role is changed and the case is not approved.
- `is_changed_from_base` is `draft.candidate_hash != base-release revision.content_hash`. This is the workbench snapshot's own predicate, and a test compares it with `read_workbench`.
- `missing_required_case` is true when the role is changed and has no case.
- `ready` is true when the role is not missing a required case and no case blocks.
- `blocking_agents` lists the roles that are not ready.
- `all_ready` is true when `blocking_agents` is empty.

### `draft_readiness(session)` (C10)
- It calls `_require_no_transaction`.
- Then, inside `with session.begin()`, it calls `_lock_current_parents(exclusive=False)` and returns `readiness_under_parent_lock`.

### `readiness_under_parent_lock(session)` (C10, #269's Q4 binding)
- It raises `RuntimeError` unless `session.in_transaction()`.
- It never begins, commits or rolls back.
- It reads `graph_draft`, the draft hashes and the base-release hashes as columns, with no lock.
- It checks the seven-role set and raises `GraphConfigurationIntegrityError` if either set is incomplete.
- It runs the one statement.
- Neither entry point touches a runtime (C27).

## RED before implementation
- **Unit** (`/tmp/t268-2/red-unit.txt`, `red-causes.txt`): 43 failed and the 186 existing tests passed. Every failure was an `AttributeError`: no `draft_readiness`, `readiness_under_parent_lock`, `eligible_approval_clause` or `TestCaseReadinessItem`. Names are resolved at call time, so no test failed at collection.
- **PostgreSQL** (`/tmp/t268-2/red-pg.txt`): these tests were written after the unit GREEN. To get their RED, I put back the TASK_BASE copy of the source file, ran them, and restored the file. All 5 failed; 4 of them with `AttributeError: 'AgentTestWorkbench' object has no attribute 'draft_readiness'`.
- The 2 structural tests in `d3f64c3db` were added after the mutation sweep. Their RED is the M7–M10 and M26 rows below.

## Tests added
- **Unit** (`tests/unit/test_agent_test_workbench.py`), 45 tests:
  - the plan's Step 1 status tests;
  - C13's three tests: older approval plus newer rerun (×3 parametrized), supersede v1 to v2, and ORM-retired `missing_required_case`;
  - `run_at` / id ordering and ties;
  - one mismatch test for each identity term;
  - the C12 baseline-approval test;
  - changed-only blocking, and the optional or inactive cases that are not listed;
  - the result's identity, including the changed predicate matching `read_workbench`;
  - the types;
  - both entry points (the lock taken once, shared; refusals; running inside the caller's exclusive lock with the same transaction object);
  - read-only, one-statement capture;
  - the shared clause, both as a query and as its exact term list;
  - the statement ordering;
  - C27 for both entry points.
- **PostgreSQL** (appended to `tests/integration/test_agent_definition_workbench_postgres.py`), 5 tests. No new file, so no CI guard or `test.yml` change:
  1. The plan's Step 3: two approvals of hash A, then a real save to hash B, gives `needs_test`. A hash B approval gives `approved`.
  2. Tied `now()` `run_at` inside one transaction: the higher id is reported.
  3. `draft_readiness` waits behind an L0 `FOR UPDATE` holder that is changing a hash (`pg_stat_activity` shows it waiting on a Lock). It then reads the committed hash and lock version.
  4. A supersede in flight is seen whole or not at all. This is C29 for readiness.
  5. Statement shape: exactly one `FOR SHARE OF graph_release, graph_draft`; one case-and-run statement with no `FOR`; no writes.
- Plan Step 3's ">20 runs" test was moved to Task 4, as C13 says.

## Mutation table
- **Driver:** `/tmp/t268-2/mutate.py`. Results are in `/tmp/t268-2/mut-all.log` (run at `eddf8cad0`) and in the re-run at `d3f64c3db`.
- **Where it ran:** a temporary detached worktree, `/tmp/t268-2/mut-wt`.
- **How each mutation ran:**
  - The anchor count is asserted to be 1.
  - The replacement carries the marker `MUT268_2_Mn`, and `grep -c` on the marker returned 1 each time.
  - The scope is the whole file: `pytest <file> -q -p no:randomly`.
  - The file is restored with `git show <SHA>:src/services/agent_test_workbench.py`, and `git diff --quiet <SHA>` confirms it is clean.
  - GREEN after every restore: 231 unit tests and 36 PostgreSQL tests.
- **Execution:** a RED shows the mutated line ran. For the SQL-term mutations, the compiled-statement tests read the statement that actually executes.

| # | Mutation | Scope | RED (failing tests) |
|---|---|---|---|
| M1 **(S2, controller)** | drop the hash term | unit, PG | unit 4: `test_an_approval_on_a_stale_hash_needs_a_test`, `…differs_in_one_identity_term…[stale-hash]`, `…clause_carries_every_term…`, `…shared_eligibility_clause_selects…`. PG 1: `test_postgres_readiness_ignores_old_hash_approvals_after_a_real_save` |
| M2 **(S2b, reviewer)** | drop `run_kind='candidate'` | unit | 4: `test_an_approved_baseline_on_an_unchanged_role_is_not_candidate_evidence`, `…[baseline-kind]`, `…carries_every_term…`, `…selects_exactly…` |
| M3 | drop the case-version term | unit, PG | unit 1: `…[other-case-version]`. PG GREEN: a supersede changes the case id, so the id term covers it there |
| M4 | drop `run.agent_key = case.agent_key` | unit | 1: `…[other-role]` |
| M5 | drop the case-id term | unit | 2: `test_a_run_of_another_case_does_not_count`, `test_only_active_required_cases_are_listed_in_id_order` |
| M6 | drop `verdict='approved'` | unit | 17, including every `awaiting_review` and `test_failed` test |
| M7 | drop `execution_status='completed'` | unit | at `eddf8cad0`: GREEN, because the DDL check enforces it. At `d3f64c3db`: 1, `…carries_every_term_including_the_ddl_backed_ones` |
| M8 | drop `checks_passed IS true` | unit | same as M7 |
| M9 | drop `draft_agent.agent_key = case.agent_key` | unit | at `eddf8cad0`: GREEN, because the readiness join implies it. At `d3f64c3db`: 1, `…carries_every_term…` |
| M10 | drop `id DESC` | unit, PG | at `eddf8cad0`: GREEN on both engines, because tie order follows the index scan. At `d3f64c3db`: unit 1, `test_both_run_lookups_break_run_at_ties_by_id_and_cases_are_in_id_order` |
| M11 | order by id only | unit | 2: `test_the_newest_eligible_approval_is_reported_by_run_at_then_id`, `test_without_an_approval_run_at_outranks_a_higher_id` |
| M12 | drop the `is_required` filter | unit | 2 |
| M13 | drop the `is_active` filter | unit, PG | unit 4. PG 1: `…in_flight_supersede_whole_or_not_at_all` |
| M14 | `blocking` ignores `changed` | unit | 9 |
| M15 | `missing = False` | unit | 1: `…retired_is_missing_a_required_case` |
| M16 | the newest run decides, not any approval | unit | 3: `test_an_older_approval_beats_a_newer_rerun_of_the_same_hash[*]` |
| M17 | disable the `rejected` branch | unit | **equivalent mutant**: `rejected` falls through to the `else` branch, which also gives `test_failed`. The branch is kept for readability |
| M18 | `awaiting_review` ignores checks | unit | 1: `…newest_candidate_run_decides[checks-failed]` |
| M19 | no parent lock | unit, PG | unit 1: `test_draft_readiness_takes_the_shared_parent_lock_once`. PG 2: `…waits_behind_an_exclusive_parent_holder…`, `…statements_lock_only_the_parents…` |
| M20 | exclusive lock instead of shared | unit | 1 (the lock-once test) |
| M21 | no `in_transaction` guard | unit | 1: `test_the_locked_entry_point_refuses_a_session_with_no_transaction` |
| M22 | no `_require_no_transaction` | unit | 1: `test_draft_readiness_refuses_a_session_already_in_a_transaction` |
| M23 | call `self._runtime()` | unit | 2: `test_readiness_never_touches_a_runtime[*]` |
| M24 | a second case read | unit | 1: `test_readiness_writes_nothing_and_reads_cases_and_runs_in_one_statement` |
| M25 **(C29)** | a filtered `FOR SHARE OF agent_test_case` | PG | 2: `…in_flight_supersede_whole_or_not_at_all` (it waits, then the re-check drops the retired row), `…statements_lock_only_the_parents…` |
| M26 | drop the case `ORDER BY` | unit | at `eddf8cad0`: GREEN (SQLite returns rows in id order anyway). At `d3f64c3db`: 1, the ordering test |
| M27 | invert `changed` | unit | 26 |

### Plan sabotage targets
- **Controller target S2** is M1. It REDs because the hash term sits in the one shared identity clause, so the stale approval cannot be found by either lookup. Under the plan's newest-run-only logic this would not be guaranteed; that is C12's point.
- **Reviewer target S2b** is M2. It REDs `test_an_approved_baseline_on_an_unchanged_role_is_not_candidate_evidence`.
- I have already run both targets. The reviewer should pick a fresh seam. Two suggestions:
  - drop the `.correlate(...)` in `_newest_run_id`;
  - swap `eligible_*` and `newest_*` in `_case_readiness`.

## Gates
- **Focused:** `tests/unit/test_agent_test_workbench.py`, 231 passed.
- **PostgreSQL**, with `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, one invocation per file, zero skips:
  - workbench file: 36 passed (31 before this task plus 5 new);
  - constraints: 66 passed.
- **Full unit** (in the real worktree at `d3f64c3db`): 6 failed, 6712 passed, 110 skipped. The six failures are exactly the baseline nodes and causes: `test_deploy_autoscaling` ×2, the chokepoint ×3 and the persistence boundary ×1.
  - An earlier full run inside the `/tmp` worktree had a seventh failure, `test_persisted_agent_runtime.py::test_runtime_logging_sink_success_record…`. It is a path artifact: `/tmp` resolves to `/private/tmp`, and the test asserts that `'private'` is not in the log record's `pathname`.
  - That file passes 114/114 in the real worktree.
- **`ruff check`:** clean on the three files, and clean on their TASK_BASE copies. `ruff format --check` fails on both base and head, so it is not a gate.
- `test ! -e .venv` held before and after. Nothing was installed. No frontend command was run. `ai_slide_generator` was not touched.

## Concerns

### 1. Correction-29 safety (the answer)
Readiness takes no case or run lock, and that is what makes it safe.

**Why C29 happens.** A `FOR SHARE` read that meets a row locked by the superseding writer waits. After the writer commits, READ COMMITTED's EvalPlanQual re-check re-evaluates only that locked row against the newly committed version. The retired v1 no longer matches `is_active`, so it is dropped. The v2 row is an INSERT the statement's snapshot cannot see. The locked set is then a hybrid that is neither the before state nor the after state.

**Why readiness avoids it.**
- A plain `SELECT` never waits on row locks and never goes through EvalPlanQual.
- In PostgreSQL it runs on one MVCC snapshot, taken at statement start, and that snapshot covers every correlated subquery in the statement.
- So the case rows and the runs paired with them come from the same instant. Readiness sees either the state before the supersede (v1 active, no v2) or the state after it (v1 retired, v2 active). It never sees half of it, and it never pairs an old case row with newer runs.
- The draft hashes and `lock_version` are read in separate statements, but L0 is held, so they cannot change. The case statement also joins `graph_draft_agent` itself.
- Proof: `test_postgres_readiness_sees_an_in_flight_supersede_whole_or_not_at_all` passes. Adding the filtered lock (M25) turns it RED.

**What it can miss.** Anything committed after its statement snapshot. Case writers take only L2 and the verdict writer takes only L3. Neither conflicts with L0 share, or even with #269's L0 exclusive. So these can commit while readiness runs and still not be reflected:
- a supersede;
- a deactivation or an `is_required` flip;
- a new required case;
- a verdict change.

The result is a consistent picture of one moment, but it can be out of date by the time it is returned.

**Consequence for #269.** Inside publication, `readiness_under_parent_lock` is informational only: the 409 body and the preview. It must not be the gate. #269's gate must still do its own C29 locking:
1. an L2 lock on the changed roles' case rows, unfiltered and in id order;
2. a fresh select of the active required cases;
3. an L3 lock on the run rows.

A preview can show "publishable" while a concurrent supersede makes the gate refuse. That disagreement is safe; the reverse cannot happen because the gate locks.

### 2. `missing_required_case` on an unchanged role
It is True only on a changed role, as C11 states. An unchanged role with no required case reports `cases=()`, `ready=True` and `missing=False`, and a test pins this.
- If #269 or the UI want to warn about an unchanged role that has no coverage, they must use `cases == ()`.
- The alternative is to set the flag to `not cases` on every role. That is a one-line change, but it would flip that test.

### 3. The `rejected` branch in `_case_readiness` is redundant (M17 is an equivalent mutant)
I kept it because it makes the status map explicit.

### 4. `draft_readiness` does not retry the parent-handoff diagnosis
It raises `GraphConfigurationIntegrityError("graph configuration parent snapshot is inconsistent")` if a publication commits while it waits. `_persist_run` retries this once; `read_workbench` does not. The PLAN-CORRECTIONS §10 table says #268 inherits #269's retry after the rebase. Task 3's route must map this error the same way as the workbench read.

### 5. Task 4 hand-off
- **What the clause takes:** `eligible_approval_clause(run, case, draft_agent)` needs all three entities correlated.
- **What it leaves to cleanup:** it tests neither the case's `is_active` nor `is_required`. Cleanup must add `atc.is_active AND atc.is_required` (C19c).
- **The C19e outer recheck:** it can reuse the clause with `AgentTestRun` as the target row.

### 6. Temporary worktrees
I created and then removed three temporary detached worktrees for the parallel full run, the mutation sweep and the base comparison:
- `/tmp/t268-2/full-wt`
- `/tmp/t268-2/mut-wt`
- `/tmp/t268-2/base-wt`

No other worktree was touched.
