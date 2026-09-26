# #270 Task 1 report — immutable Graph Release history read model

**Status:** DONE. Phase A (Task 0-A + Task 1) is complete. Task 2 waits for Task 0 Step 4 (phase B).

- **TASK1_BASE:** `dbbea85e10beb04d30efaee4c184417ab41069f6`
- **Task 1 commit:** `d0e4d693a` "feat: immutable graph release history read model (#270)". The pre-mutation commit `957358cf6` was amended once to add the `lock_timeout` hardening described below; it is not in the branch.
- **Diff `dbbea85e1..d0e4d693a`:** five files, all new or append-only. Nothing is owned by #268 or #269, and there is no facade change.
  - `src/services/graph_release_history.py` (new)
  - `tests/unit/test_graph_release_history.py` (new)
  - `tests/integration/test_graph_release_history_postgres.py` (new)
  - `.github/workflows/test.yml` (+1 line in `integration-graph`)
  - `tests/unit/test_ci_collects_integration_tests.py` (+1 pin test)
- **Corrections applied:**
  - C11: `populate_existing=True` on the first statement.
  - C14: the corrected baseline loop.
  - OQ7: no log record at all.
  - No model call: no runtime or model import.
  - Evidence: only #267's tables are read, filtered to `run_kind='candidate'`.

## RED before implementation

`tests/unit/test_graph_release_history.py` was written first. Run with `DATABASE_URL=sqlite:////tmp/t270-1/unit.sqlite … -m pytest -q -p no:randomly tests/unit/test_graph_release_history.py`:

```
ImportError while importing test module '.../tests/unit/test_graph_release_history.py'.
E   ModuleNotFoundError: No module named 'src.services.graph_release_history'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

This is the plan's predicted RED. The full output is in `/tmp/t270-1/red-unit.txt`.

The CI-enrollment RED came before the `test.yml` edit, with the new PostgreSQL file present and the pin test added (`/tmp/t270-1/red-ci-guard.txt`):

```
FAILED tests/unit/test_ci_collects_integration_tests.py::test_every_integration_file_is_collected_or_excluded_with_reason
FAILED tests/unit/test_ci_collects_integration_tests.py::test_graph_release_history_is_collected_by_integration_graph
2 failed, 13 passed
```

GREEN after implementation: the unit file had 17 passed. After the workflow edit, the CI guard had 15 passed.

## Clause-to-mutation table

**Driver:** `/tmp/t270-1/mutate.py`. Per-run logs are in `/tmp/t270-1/mutations/`, and the results are in `results.json`. For each mutation, the driver does the following:

1. Asserts the anchor occurs **exactly once** in `src/services/graph_release_history.py`.
2. Applies the mutation with a `# MUT-<id>` marker, then checks that `grep -c MUT-<id> src/services/graph_release_history.py` returns 1.
3. Inserts an execution probe directly before the mutated statement: `Path("/tmp/t270-1/mutations/hit-<id>").touch()`.
4. Runs **both whole files**:
   - `DATABASE_URL=sqlite:////tmp/t270-1/mut.sqlite PYTHONPATH=<W>:<W>/packages/databricks-tellr python -m pytest -q -p no:randomly -rfE tests/unit/test_graph_release_history.py`
   - `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres … tests/integration/test_graph_release_history_postgres.py`
5. Restores the original bytes, then checks marker `grep -c` = 0, `PROBE` `grep -c` = 0, and byte-identity. `git diff --exit-code` was clean after the run.

`pytest-cov` could not serve as the execution proof. Under its tracer, the shared env fails to import `langchain_core`, raising a pydantic `discriminator-no-field` error at conftest import. The hit-file probe replaces it.

**Every row has:** anchor 1, marker `grep -c` 1, executed yes, restore `grep -c` 0 and byte-identical, and GREEN after restore. The final GREEN is 17 unit and 4 PostgreSQL tests, plus the gates below.

| ID | Clause | Mutation | RED tests (U = SQLite unit, P = PostgreSQL) |
|---|---|---|---|
| M01 | First statement uses `populate_existing` (C11) | drop `.execution_options(populate_existing=True)` | U `test_history_refreshes_a_release_already_loaded_in_the_session` ("exactly one active") |
| M02 | Newest first | `.desc()` → `.asc()` | U `…exact_lineage`, U `…refreshes…`; P `…coherent…[list]`, `[detail]`, `…restored_lineage_is_exact`, `…takes_no_row_lock` |
| M03 | Later reads filter to the first statement's id set | drop `.where(graph_release_id.in_(ids))` on the mapping read | P `test_history_is_coherent_when_a_release_commits_between_statements[list]` and `[detail]` (`KeyError: 3`). SQLite is green, as expected: the race needs a concurrent commit. |
| M04 | Incomplete mapping check | `if False:` | U `test_incomplete_mapping_is_an_integrity_error` |
| M05 | Exactly one active release | `if False:` | U `test_no_active_release_is_an_integrity_error` |
| M06 | A lineage reference outside the set is an integrity error | `if False:` | U `test_restored_from_outside_the_release_set_is_an_integrity_error` |
| M07 | `restored_by` collects later restorers | `pass` | U `…exact_lineage`; P `…restored_lineage_is_exact` |
| M08 | **Plan controller sabotage:** `changed` computed against own mapping | `prior = mappings[release.id]` | U `test_history_lists_every_version_newest_first_with_exact_lineage`; P `…coherent…[list]`, `…restored_lineage_is_exact` |
| M09 | **Plan reviewer sabotage:** `restored_from` read from the wrong column | `restored_from=ref(release.previous_release_id)` | U `…exact_lineage`; P `…restored_lineage_is_exact`. Both assert `ReleaseRef(…version_number=3) == ReleaseRef(…version_number=2)`. |
| M10 | v1 lists all seven roles | `prior is not None and …` | U `…exact_lineage`; P `…restored_lineage_is_exact` |
| M11 | Unknown version raises `GraphVersionNotFound` | `raise LookupError(...)` | U `test_unknown_version_raises_not_found[0]`, `[99]`, `test_history_reads_emit_no_application_log_record` |
| M12 | A mapping names its own role's revision | `if False:` | U `test_mapping_to_another_roles_revision_is_an_integrity_error` |
| M13 | Revision content is checked against the persisted hash | `expected_hash=` recomputed from the row | U `test_tampered_revision_content_is_an_integrity_error` |
| M14 | Evidence read filtered to `run_kind='candidate'` | drop the filter | U `test_linked_non_candidate_run_is_an_integrity_error` |
| M15 | Filtered and unfiltered link counts compared (no silent drop) | `if False:` | U `test_linked_non_candidate_run_is_an_integrity_error` |
| M16 | A restore-link source outside the set is an integrity error | `if False:` | U `test_restore_link_source_outside_the_release_set_is_an_integrity_error` |
| M17 | Evidence order (role index, case id, run id) | order by run id only | U `test_detail_orders_evidence_by_role_then_case_then_run` |
| M18 | No row lock | add `.with_for_update(read=True)` to the first statement | P `test_history_takes_no_row_lock`, `…coherent…[list]`, `[detail]` (`LockNotAvailable`, fast) |
| M19 | An empty release set is an integrity error | `if False:` | U `test_history_with_no_release_is_an_integrity_error` |
| M20 | Evidence kind comes from the link | hard-code `'approval'` | U `test_detail_has_exact_seven_definitions_and_ordered_evidence`; P `…restored_lineage_is_exact` |
| M21 | `is_active` comes from the first statement | `is_active=True` | U `…exact_lineage`, `…refreshes…`; P `…coherent…[list]`, `[detail]`, `…restored_lineage_is_exact` |
| M22 | No application log record (OQ7) | add `logger.info(...)` in the detail read | U `test_history_reads_emit_no_application_log_record` |
| M23 | No model or runtime collaborator | add `from src.services.agent_runtime import AgentRuntime` | U `test_history_module_has_no_model_or_runtime_collaborator` |

**Named plan sabotage targets (Step 6):**
- **Controller (M08).** It hits the predicted test, `test_history_lists_every_version_newest_first_with_exact_lineage`. The first failing assertion is v4's `changed_agent_keys == ("builder",)`, which observes `()`; `assert_lineage` checks v4 before v2. The plan's predicted observation, v2's `()`, is never reached, but it has the same root cause. The sabotage also REDs PostgreSQL `…coherent…[list]` (v2 `()` vs `("architect",)`) and `…restored_lineage_is_exact`.
- **Reviewer (M09).** It hits the prediction exactly: v4 `restored_from` observes `Ref(v3)`, on SQLite (`…exact_lineage`) and on PostgreSQL (`…restored_lineage_is_exact`).

Both are covered, and a reviewer can re-run them with `python /tmp/t270-1/mutate.py M08 M09`.

## Coherence proof (PostgreSQL, READ COMMITTED)

`test_history_is_coherent_when_a_release_commits_between_statements[list|detail]` works as follows:
- It asserts `SHOW transaction_isolation` = `read committed`.
- An `after_cursor_execute` listener on the history connection matches the first statement (`FROM GRAPH_RELEASE ORDER BY GRAPH_RELEASE.VERSION_NUMBER DESC`). Exactly once, it commits v3 on another pooled connection, using the guarded first-close-then-insert recipe.
- The test asserts that a `GRAPH_RELEASE_AGENT` statement ran after that commit. It also asserts that a later statement in the *same* history transaction sees 3 releases. Together these prove the commit really landed between the history read's statements.
- The result is still exactly `[v2 (active, effective_to None), v1]`, with v2's builder still v1's revision.
- A fresh read afterwards returns `[v3 active, v2, v1]`.

M03 proves this test detects a later read that is not filtered to the set.

## Gates (final commit `d0e4d693a`)

- **Focused files:**
  - Unit history file, CI guard and `test_persisted_graph_release.py`: 56 passed.
  - PostgreSQL history file: 4 passed, 0 skipped.
- **Full `tests/unit`** (`DATABASE_URL=sqlite:////tmp/t270-1/gate2.sqlite -q -p no:randomly -rf`): 6 failed, 6643 passed, 110 skipped.
  - The 6 failures are exactly the baseline nodes, and a `diff` of their `E` lines against the baseline is empty.
  - Baseline was 6 / 6625 / 110. The +18 passes are the 17 history tests and 1 CI pin.
- **PostgreSQL, one invocation per file, 12 files:** the 11 files in Correction 14's corrected loop plus the new file. 163 passed, 0 skipped.
- **CI enrollment:** the file is in `integration-graph`'s run block, and `tests/unit/test_ci_collects_integration_tests.py` is green with a dedicated pin test.
- **Ruff:** the new files are clean. A whole-tree `ruff check src tests` shows no finding at HEAD that is absent at base. The only base-vs-HEAD differences are 3 I001 findings that appear only in the `/tmp` base extraction, because first-party detection depends on location. `test_ci_collects_integration_tests.py`'s I001 predates this change.
- `test ! -e .venv` passed before and after every run. No installs.

## Deviations from the plan text (for the reviewer to rule on)

1. **The plan's two-active scenario cannot be built.** The `uq_graph_release_one_active` partial unique index rejects a second active row on SQLite too. The unit test instead covers **zero** active rows (`test_no_active_release_is_an_integrity_error`); two active rows can arise only as a stale identity map, which the C11 test covers. This test was rewritten after implementation, so its RED comes from M05, not from a pre-implementation run.
2. **The PostgreSQL tests were written after the implementation**, following the plan's step order (Step 4 comes after Step 3). Their RED comes from mutations M02, M03, M07–M10, M18, M20 and M21, and from the CI-guard RED before enrollment.
3. **The check is stricter than the plan's sketch.** If a predecessor, restored-from or evidence source id is outside the first-statement set, the read raises `GraphConfigurationIntegrityError`. The sketch would either `KeyError` or silently treat the release as v1.
4. **A sixth file was touched:** a pin test in `test_ci_collects_integration_tests.py`, which the brief requires. It is append-only; #268 and #269 may also append there, so expect a trivial merge.
5. **The PostgreSQL file imports its builders from `tests.unit.test_graph_release_history`** (`append_release`, `seed_*`, `link_run`, `lineage_fixture`, `assert_lineage`). This avoids a second copy, because the plan allows no shared helper file.
6. **Test-harness hardening from mutation M18.** A lock regression initially **hung** the coherence test forever. The history connection's `FOR SHARE` blocked the in-listener publisher, which waited on the history thread: an in-process deadlock that PostgreSQL cannot detect. The publisher now runs `SET LOCAL lock_timeout = '5s'` (`append_release(lock_timeout=…)`), so the regression fails in about 13s with `LockNotAvailable`. The feat commit was amended for this.

## Concerns

- **Leaked database.** Killing the hung M18 run leaked one throwaway database, `tellr_int_e17103e7d3d64c34`. It was identified as mine by the test's unique actor, `release-history@example.com`, and dropped; the drop is proven (count 0). Four other `tellr_int_*` databases exist. They are not mine, and I left them untouched. `ai_slide_generator` was never touched.
- **Datetimes.** They are returned exactly as stored: naive on SQLite, aware on PostgreSQL. Task 6's wire layer should normalise them to aware UTC.
- **Unrepresentable failure modes.** `read_release_detail` keeps two defensive checks that the schema's constraints make unreachable: a missing revision row (FK) and the `agent_key` check. The unit test reaches the `agent_key` check only with `PRAGMA foreign_keys=OFF`.
