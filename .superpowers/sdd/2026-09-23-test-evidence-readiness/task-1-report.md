# #268 Task 1 report: the verdict write service

- **Status:** DONE_WITH_CONCERNS. The concerns are listed in §7.
- **Branch:** `feat/test-evidence-readiness-268`.
- **Worktree:** `.worktrees/issue-268-plan`.
- **TASK_BASE:** `f68635ea6bf210d16e89d0c66f44a3ac4030ff27`.

**Commits:**
- `1ea3daeb26355b035b1c8d582c38872069a184bd`: `feat: verdict write service with eligibility enforcement (#268)`
- `fcca6b4c44e631685c5a3d2680f45af0a6f10c04`: `test: make the verdict row-lock and no-runtime tests catch their sabotage (#268)`
- The commit that adds this report.

**Files changed** (`git diff --stat f68635ea6 HEAD`, excluding this report): 909 insertions, 1 deletion.
- `src/services/agent_test_workbench.py`
- `tests/unit/test_agent_test_workbench.py`
- `tests/integration/test_agent_definition_workbench_postgres.py`

## 1. What was built

`AgentTestWorkbench.record_verdict(self, session, *, run_id, verdict, reviewer, notes) -> TestRunEvidence`. It is a **method** on the workbench, not a free function, for three reasons:
- C4 writes the signature with `self`.
- Every other test-run operation, including #268's own `draft_readiness` and `cleanup_*`, is a workbench method. The route already builds `AgentTestWorkbench` per request.
- The method needs `self._require_no_transaction`. C27's runtime-isolation test is defined against `AgentTestWorkbench(runtime=...)`.

**New module names:**
- `VerdictChoice = Literal["approved","rejected"]`
- `IneligibleReason`
- `MAX_VERDICT_NOTES_LENGTH = 2000`
- `VerdictRejected(ValueError)`: ordered `TestCaseIssue`s, a sibling of `TestCaseRejected`.
- `IneligibleForApprovalError(ValueError)`: a real `__init__(run_id, reason)` with `.run_id` and `.reason`, taken verbatim from C5.
- `_verdict_lock_statement(run_id)`
- `_verdict_issues`, `_verdict_notes_issues`

**Order of operations:**
1. **Validate before any statement (C4).** Issues are reported in the order `actor` (the existing `_actor_issues` on `reviewer`), then `verdict`, then `notes`.
   - `verdict` must be exactly a `str` `approved`/`rejected`. `None` is refused, so there is no withdrawal (Q7).
   - `notes` is `None`, or a `str` that is non-blank after `strip()` and at most 2000 code points. It is stored verbatim.
2. `_require_no_transaction`, then `with session.begin():`.
3. **L3 only (C6):** `select(AgentTestRun).where(id==run_id).with_for_update().execution_options(populate_existing=True)`. There is no parent lock and no case lock.
4. **Refusals, in this order (C5):**
   - a missing row raises `TestRunNotFound`;
   - `execution_status != 'completed'` raises `not_completed` for **both** verdicts;
   - an approval with `not deterministic_checks_passed` raises `checks_failed`.
5. **Identical `(verdict, reviewer, notes)`:** no UPDATE, and the stored evidence is returned.
6. **Otherwise:** one Core `UPDATE agent_test_run SET verdict, verdict_reviewer, verdict_at=now(), verdict_notes WHERE id = :id`, then `refresh(row)`.
7. Return `_evidence_from_row` with the synthetic payload, read the same way `get_test_run` reads it.

No `IntegrityError` or `SQLAlchemyError` is caught (C7). The method never calls `_runtime()` or `get_agent_test_runtime` (C27).

**Plan and correction items that this report now pins down:**
- **Core UPDATE instead of assigning the ORM attributes (C6 wording).** The ORM leaves an unchanged value out of the SET list. A flip that keeps the same reviewer and notes would write only two columns, so the "SET list is exactly the four columns" proof would depend on the data. A Core `update().values(...)` always writes exactly the four. The unit test on the SQLite listener pins this for the first write and for a flip that keeps reviewer and notes.
- **The returned evidence carries no verdict fields.** C16 puts the new `TestRunEvidence` verdict fields in Task 3's single commit. `_test_run_response` does `TestRunEvidenceResponse.model_validate(dataclasses.asdict(evidence))` under `extra="forbid"`, so adding the fields now would break every run route. Task 1 tests therefore check the verdict through a fresh-session read of the row. The plan's "returns TestRunEvidence with verdict='approved'" becomes true in Task 3. See §7 concern 1.
- **A blank reviewer uses the existing actor issue verbatim:** `TestCaseIssue("actor","blank","Actor must not be blank.")`. C4 says to reuse `_actor_issues`. The route passes a principal, so this path is defensive.

## 2. RED evidence, before any implementation

- **RED 1** (`/tmp/t268-1/red-1-import.txt`): the file fails collection with `ImportError: cannot import name 'IneligibleForApprovalError' from 'src.services.agent_test_workbench'`.
- **RED 2** (`/tmp/t268-1/red-2-method.txt`): with only the types added (`VerdictChoice`, the two exceptions and `_verdict_lock_statement`) and no method, the result is `39 failed, 146 passed`. All 39 failures are `AttributeError: 'AgentTestWorkbench' object has no attribute 'record_verdict'`. The two tests that passed need only the types: `test_the_ineligibility_error_is_a_value_error_with_a_reason` and `test_the_verdict_lock_statement_is_for_update_of_the_run_row_only`.
- **GREEN:** after the method was added, the file ran 185 passed.
- **The PostgreSQL tests were written after the method.** Their ability to go RED is shown by M7, M8, M9 and M16 in §3, not by a pre-implementation run.

## 3. Clause-to-mutation table

- **Driver:** `/tmp/t268-1/mutate.py`.
- **Results:** `/tmp/t268-1/mutations-pass1.json` (all 17 mutations at `1ea3daeb2`) and `/tmp/t268-1/mutations-pass2.json` (M8 and M10 re-run at `fcca6b4c4`).
- **Procedure for each row:**
  1. Restore the file with `git checkout <SHA> -- <file>`, using explicit SHAs only.
  2. Assert that the anchor occurs exactly once.
  3. Apply the mutation. Check that `grep -cE "MUTATION <id>( |$)" <file>` is exactly 1.
  4. Where a probe applies, delete `/tmp/t268-1/exec-<id>`, run, and require that the mutated site touched it.
  5. Run the listed **whole files**, one pytest invocation per file.
  6. Restore from the SHA, run GREEN, and assert `git diff --quiet <SHA>` on src and models.
- **Command:** `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly -rfs --tb=no -W ignore <file>`, with `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/t268-1.sqlite` and `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`.
- **Files:** U is `tests/unit/test_agent_test_workbench.py`, P is `tests/integration/test_agent_definition_workbench_postgres.py`, and M is `tests/unit/test_graph_configuration_models.py`.
- **Anchor and marker counts** were exactly 1 and 1 for every row. The `grep` marker for M10 in pass 1 reads 0 because of a driver regex quirk (`MUTATION M10` followed by a newline inside a probe line), but the probe file proved that the site ran. In pass 2 the marker reads 1.
- **GREEN after restore** was 0 failures for every row: U 185 passed, P 31 passed with 0 skips, M 27 passed.

| id | clause | mutation | executed | files | RED (failing tests) |
|---|---|---|---|---|---|
| M1 (S1, controller) | C5 `not_completed` | delete the `execution_status != 'completed'` check | probe: yes | U | 4 failed: `test_a_run_that_did_not_complete_is_not_completed_for_either_verdict[approved-provider_unavailable-model_error]`, `[approved-invalid_optional_field-incomplete]`, `[rejected-provider_unavailable-model_error]`, `[rejected-invalid_optional_field-incomplete]` |
| M2 (S1b, reviewer) | C6 re-stamp | drop `verdict_reviewer=` and `verdict_at=` from the UPDATE | RED | U | 17 failed. They include `test_the_verdict_update_sets_exactly_the_four_columns_by_run_id[none]` and `[flip_same_reviewer_and_notes]`, `test_any_changed_field_restamps_all_four_columns[change0..3]` and `test_an_approval_writes_the_four_verdict_columns_and_nothing_else`. Every writing test fails on the pairing CHECK. |
| M3 | C5 rejection allowed with failed checks | apply `checks_failed` to both verdicts | probe: yes | U | `test_a_rejection_of_a_completed_run_with_failed_checks_is_allowed`, `test_a_rejected_failing_run_cannot_flip_to_approved` |
| M4 | C5 `checks_failed` | delete the checks check, leaving only the DDL | probe: yes | U | `test_an_approval_of_a_completed_run_with_failed_checks_is_checks_failed`, `test_a_rejected_failing_run_cannot_flip_to_approved`. The SQLite CHECK raises `IntegrityError`, not the reason. |
| M5 | C6 identical re-submit | always UPDATE | probe: yes | U | `test_an_identical_resubmit_writes_nothing_and_returns_the_stored_evidence` |
| M6 | C6 database clock | `verdict_at=datetime.now()` | RED | U | `test_the_verdict_update_sets_exactly_the_four_columns_by_run_id[none]` and `[flip_same_reviewer_and_notes]` |
| M7 | C6/C28 L3 only | add the L0 `_lock_current_parents(exclusive=False)` | probe: yes | U, P | U: `test_the_verdict_writer_reads_no_parent_or_case_lock_statement`. P: `test_postgres_verdict_takes_no_parent_or_case_lock`, a 10 s wait behind the holder's `FOR UPDATE`. |
| M8 | C6 run-row `FOR UPDATE` | remove `.with_for_update()` | RED | U, P | **Pass 1:** U `test_the_verdict_lock_statement_is_for_update_of_the_run_row_only`; P stayed **GREEN** (a defect, fixed in `fcca6b4c4`, see below). **Pass 2:** U the same test, and P `test_postgres_verdict_waits_on_the_run_row_lock_and_decides_on_the_fresh_row`. |
| M9 | C7 | wrap the UPDATE and re-raise `IntegrityError` as `IneligibleForApprovalError` | probe: yes | U, P | U: `test_an_integrity_error_from_the_update_propagates_unchanged`. P: `test_postgres_a_verdict_trigger_error_surfaces_as_the_integrity_error`. |
| M10 | C27 | call `self._runtime()` before the transaction | probe: yes | U | **Pass 1:** stayed **GREEN** (a defect, fixed in `fcca6b4c4`). **Pass 2:** `test_the_verdict_writer_never_touches_a_runtime`. |
| M11 | C4 blank notes | turn the blank check into `if False:` | RED | U | `test_invalid_arguments_are_refused_in_order_before_any_statement[overrides4-issues4]`, `[overrides5-issues5]`, `[overrides11-issues11]` |
| M12 | C4 validate before the transaction | raise `VerdictRejected` after the lock read | probe: yes | U | all 12 `test_invalid_arguments_are_refused_in_order_before_any_statement[...]` cases, on `captured.statements == []` |
| M13 | C4 owns its transaction | drop `_require_no_transaction` | probe: yes | U | `test_the_verdict_writer_refuses_a_session_already_in_a_transaction` |
| M14 | C5 not-found | raise `IneligibleForApprovalError` for a missing row | probe: yes | U | `test_a_missing_run_is_the_existing_not_found[approved]`, `[rejected]` |
| M15 | Q7 no withdrawal | accept `verdict=None` | RED | U | `test_invalid_arguments_are_refused_in_order_before_any_statement[overrides0-issues0]` |
| M16 | C8 DDL check | weaken `ck_agent_test_run_approved_only_if_completed_and_passing` to `execution_status = 'completed'` in the model | RED | P, M | P: `test_postgres_approved_check_refuses_a_direct_approval_of_an_ineligible_run[completed_checks_failed]`. M: `test_sqlite_rejects_each_agent_test_run_check_violation[ck_agent_test_run_approved_only_if_completed_and_passing-7]`. |
| M17 | C4 notes bound | `>=` instead of `>` | RED | U | `test_notes_of_exactly_2000_code_points_are_stored_verbatim` |

**"Executed" column:**
- "probe: yes" means the mutated site wrote its `/tmp/t268-1/exec-<id>` file during the RED run.
- "RED" means the mutation changes an expression in place, with no statement to probe, such as a keyword argument, a builder call, a DDL string or a condition. The listed RED is the evidence that it ran.

**Two sabotage targets that did not go RED at first, and were fixed:**
- **M8 on PostgreSQL.** `test_postgres_verdict_waits_on_the_run_row_lock...` read the holder's `verdict_at` in a fresh session **after** the waiter had finished. Without `FOR UPDATE` the waiter re-stamps the row, and the test then compared that re-stamped value against itself. The fix reads the holder's stamp inside the holder's transaction before starting the waiter. Without the lock the PostgreSQL test now fails, because either the waiter never waits or the stamp moves.
- **M10.** `_runtime()` returns the override without touching any attribute on it, so the "every attribute access raises" object alone cannot detect the call. The C27 test now also monkeypatches `isolated._runtime` to raise, alongside the object whose every attribute access raises and the patched `get_agent_test_runtime`.

## 4. Sabotage targets for the controller and reviewer (PLAN-CORRECTIONS §12)

- **S1 (controller):** remove the `execution_status != 'completed'` check. This is M1. It fails exactly the four `test_a_run_that_did_not_complete_is_not_completed_for_either_verdict[...]` cases.
  - The approved cases fail because the reason becomes `checks_failed`: a `model_error` or `incomplete` run has `deterministic_checks_passed=False`. The test asserts `reason == "not_completed"` exactly, as C12 of the pre-pass required.
  - The rejected cases fail because the rejection writes.
- **S1b (reviewer):** drop the `verdict_at` / `verdict_reviewer` assignment from the change branch. This is M2. It hits `test_the_verdict_update_sets_exactly_the_four_columns_by_run_id[*]`, `test_any_changed_field_restamps_all_four_columns[*]` and the 11 other writing tests.
- **Both targets were already run here.** Tell the reviewer that M1 to M17 exist, and pick a fresh reviewer target, for example dropping the `populate_existing` option, which no test pins at present (see §7 concern 3).

## 5. Tests added

**Unit** (`tests/unit/test_agent_test_workbench.py`; real SQLite `factory`; runs come from the executor with `DeterministicFakeModelAdapter`, or from an INSERT-only copy of a real run's row; never from an UPDATE):
- the write of the four columns, with the rest of the row unchanged and the evidence equal to `get_test_run`;
- the SET-list listener (first write, and a flip that keeps reviewer and notes);
- no parent-table statement is sent;
- the PostgreSQL compilation of the lock statement;
- a rejection of a passing run;
- a baseline approval (C9);
- `not_completed` for both verdicts, across `model_error` and `incomplete`;
- `checks_failed`;
- a rejection of a completed run with failing checks;
- the error class shape;
- not-found for both verdicts;
- an identical re-submit, with no UPDATE and the row byte-identical;
- a re-stamp for each changed field (a verdict_at inserted in 2020 moves);
- approve → reject → approve;
- a rejected failing run cannot be approved;
- the 12-case validation matrix: ordered issues, no statement, and a `None` verdict refused (Q7);
- 2000 code points stored verbatim;
- an open-transaction refusal;
- a stale-candidate run can be judged (Q3);
- a retired case version's run can be judged, and the case rows do not change;
- a SQLite `RAISE(ABORT)` trigger surfaces as `IntegrityError` (C7);
- no runtime is touched (C27).

**PostgreSQL** (`tests/integration/test_agent_definition_workbench_postgres.py`):
- **C8 identity:** the full row minus the four verdict columns is equal before and after a write, an identical re-submit and a flip. `verdict_at` is tz-aware and lies between `clock_timestamp()` readings taken before and after. A flip re-stamps it to a later value.
- **The DDL check:** a direct UPDATE that sets `verdict`, `verdict_reviewer` and `verdict_at` together, on a `model_error` run and on an INSERTed completed run whose checks failed. It asserts `pgcode == "23514"` **and** `diag.constraint_name == "ck_agent_test_run_approved_only_if_completed_and_passing"`.
- **No parent or case lock:** release, draft and every case row are held `FOR UPDATE` by another session, and the verdict still commits within 10 s.
- **Row-lock wait:** the verdict waits on the run row (observed through `pg_blocking_pids`), then decides on the fresh row. An identical submission is a no-op that keeps the holder's stamp.
- **C7:** a test-local stand-in for #269's linked-verdict trigger (23514) surfaces as `IntegrityError` with pgcode 23514. The trigger is created only in the fixture's throwaway database.

## 6. Gates

`.venv` was absent before and after every run. Nothing was installed, and the dev database `ai_slide_generator` was not touched. Every PostgreSQL run used fixture-owned throwaway databases.

| Gate | Result |
|---|---|
| Focused unit: `test_agent_test_workbench.py`, `test_graph_configuration_models.py`, `test_agent_definition_workbench_routes.py`, `test_test_run_failure_contract_client_join.py` | 611 passed |
| Full unit (`tests/unit -q -p no:randomly -rf`) | **6 failed**, 6666 passed, 110 skipped (412 s). The six are the baseline nodes and causes: `test_deploy_autoscaling` ×2 (`'provisioned' == 'autoscaling'`; `_get_or_create_lakebase_provisioned` called 0 times), the chokepoint `_FakeSession.execute` ×3, and the persistence boundary `no active Graph Release` ×1. 6666 = the baseline 6625 + the 41 new unit cases. |
| PostgreSQL `test_graph_configuration_constraints_postgres.py` | 66 passed, 0 skipped |
| PostgreSQL `test_agent_definition_workbench_postgres.py` | 31 passed (25 + 6 new), 0 skipped |
| `ruff check` on the three changed files | All checks passed. The base versions also pass. `ruff format --check` flags the base files too, so it was not treated as a gate. |
| Frontend | not run, as the brief requires |

Logs are in `/tmp/t268-1/`: `full-unit.txt`, `pg-*.txt`, `red-*.txt`, `mutations*.json` and `mutations*.log`.

## 7. Concerns

1. **The returned `TestRunEvidence` has no verdict fields until Task 3.** This is deliberate (C16's single commit, and `extra="forbid"`). Task 3 must add the four fields to the dataclass and `_evidence_from_row`, and then assert them on `record_verdict`'s return value. The Task 1 tests read the row instead.
2. **Core UPDATE instead of ORM assignment.** This is a deliberate deviation from C6's wording, made to keep C6's SET-list proof exact. `session.refresh(row)` then reloads the row, `verdict_at` included.
3. **`populate_existing=True` on the lock statement is required by C6 but no test pins it.** The PostgreSQL wait test uses a fresh session, so the identity map is empty anyway. A reviewer sabotage there would stay GREEN. Pinning it needs a session that has already loaded the row before the lock. This is a reviewer's call.
4. **Blank-reviewer issue field.** The issue for a blank reviewer is the reused `actor` issue, not a `reviewer` field. Task 3's route never produces one, because the principal is trusted, but a route mapper that keys on field names should know about it.
5. **Two sabotage targets initially stayed GREEN (M8 on PostgreSQL, and M10).** Both are fixed in `fcca6b4c4`. This is recorded so the reviewer re-runs them rather than trusting the first test shape.
6. **Hazard respected:** #269's linked-verdict rule is not pre-empted. There is no linkage check, and the stand-in trigger exists only in test databases.

## 8. Empty triple check

- `git status --short` after the report commit: clean.
- `git stash list`: none of mine. No stash was used.
- `test ! -e .venv`: it holds, and no install was made.
