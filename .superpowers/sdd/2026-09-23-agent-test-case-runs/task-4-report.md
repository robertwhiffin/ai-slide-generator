# Task 4 report: test run execution and persistence (#267)

**Status:** DONE_WITH_CONCERNS. Nothing fails. The concerns are design choices the controller should rule on.
- TASK_BASE `b678b48fdeb2bc089454ac8144bc72e0f643f2f8`.
- Commits: `7e9882fa1` feat: test run execution and persistence (#267); `6b7325f90` test: pin newest-baseline order and overlay optional fields; `bfbdbc119` test: pin the baseline's revision hash and unblock the L0-holder test on failure. This report is committed on its own.
- Drivers and raw output are in `/tmp/t267-4/`: `red.txt`, `red-full.txt`, `red-collection.txt`, `mutate.py`, `mutate.log`, `mutate-rerun.log`, `table.md`, `full.txt`, `pg.txt`, `focused.txt`, `graph_nodes_ids_{before,after}.txt`, `ruff-{base,new}.txt`.

## What changed
- **`src/services/graph_configuration_draft.py`** (additive, C32): the body of `read_draft_probe_candidate` moved into the private `_read_saved_candidate`. That helper does the lock and role checks, one `session.begin()` `read_workbench` snapshot, the stale-lock null-candidate conflict, and the endpoint-policy re-check after the locks are released. `read_draft_probe_candidate` is now a projection of it, with the same signature, return type and behaviour. The new sibling `read_draft_test_candidate` returns the frozen `DraftTestCandidate` (the C32 field list). `DraftProbeCandidate`, `_write_locked_content` and the #266 probe tests are unchanged.
- **`src/services/agent_model_payload.py`** (new, C37): `MODEL_PAYLOAD_KEYS` for all seven roles, each the union of that role's production calls. `model_payload_for(agent_key, payload)` projects in payload order and returns a deep copy. A dict `previous_deck_review` becomes `{digest, findings}`, which drops `author`. An unknown role raises `UnknownAgentKeyError`, imported lazily. There are no module-level `src` imports. `nodes.py` and the seed are not edited.
- **`tests/fixtures/model_payload_keys.py`** (new): `_BUILDER_MODEL_KEYS`, `_BUILDER_RETRY_MODEL_KEYS`, `_SLIDE_REVIEW_MODEL_KEYS`, `_FIXER_MODEL_KEYS` and `_EVERY_MODEL_CALL` moved here verbatim under public names. `test_graph_nodes.py` imports them as the old names. **The node-ID list is identical: 166 before, 166 after (`diff` empty).** The file then gained one parity test, so it now has 167.
- **`src/services/agent_test_workbench.py`:**
  - New types: `TestRunEvidence`, `DeterministicCheckResult`/`Issue`, `TestRunUnavailable` (maps to 503), `TestRunCaseInactive` (409), `TestRunCaseRoleMismatch` (422) and `TestRunNotFound` (404).
  - `AgentTestWorkbench(*, runtime=None, graph_configuration=None)`. The runtime is lazily `get_agent_test_runtime()` (C33).
  - `execute_candidate_run(session, *, agent_key, test_case_id, expected_lock_version, actor) -> TestRunEvidence | DraftSaveConflict[None]`, `execute_baseline_rerun(session, *, agent_key, test_case_id, actor)`, `get_test_run` and `list_test_runs(limit 1..100)`.
  - **Shape (C8/C32):**
    1. Precondition: raise `RuntimeError` if `session.in_transaction()`.
    2. 1a: `read_draft_test_candidate` (probe read). A stale lock returns the conflict with no call and no row.
    3. 1b: `with session.begin()` reads the case (found → same role → active) and the C20 baseline, copied into frozen values.
    4. Assert there is no open transaction.
    5. `run_candidate(...)` (candidate) or `run(agent_key, active_release_id, …)` (baseline).
    6. Transaction 2: `expire_all`, then `_lock_current_parents(exclusive=False)` (release → draft FOR SHARE). Re-read the draft hash, case `is_active` and draft base with column selects. Insert with the transaction-1 identity verbatim, flush and refresh, and build the evidence from the row. `candidate_is_current` and `base_release_is_current` are returned, not persisted.
    7. If the handoff diagnosis arrives once, retry once. Any other integrity or SQLAlchemy failure is `TestRunUnavailable`, with no row and no second model call. A database failure in transaction 1 is also `TestRunUnavailable`, with no call.
  - **Status and checks (C15/C16/C17):**
    - The candidate status and `error_detail` come verbatim from Task 3's `CandidateRunOutcome`, and the raw output from Task 3's observer.
    - A `ValueError` or `UnknownAgentKeyError` raised by `run_candidate` becomes `assembly_error:invalid_candidate`.
    - The baseline goes through `run`. Its exceptions are classified with the same `_classify_candidate_failure`. `lakebase_unavailable` is 503, and a missing or incomplete release is `assembly_error:invalid_persisted_definition`.
    - There is one check: `output_contract` when `completed` or `incomplete` (with `AgentOutputValidationError.issues` as `{code, field}`), or `execution` for the other statuses. No second validation runs.
    - Structured output is `model_dump(mode="json")` plus the thawed `additional_fields`.
  - **Identity (M-1):** revision and release ids come from the transaction-1 snapshot. `candidate_hash` is the draft hash for a candidate run and the revision `content_hash` for a baseline. `compared_*` is the draft's base release and revision, or the active release and revision. `error_detail` is never `str()` of an error.
  - **Baseline (C20):** the newest row with `run_kind='published_baseline'`, the same `test_case_id`, the same `agent_key`, `compared_definition_revision_id` = the base revision, and `completed`, ordered by `run_at DESC, id DESC`. Its outputs are copied into `baseline_*`. No verdict is read (shown unapproved per P1).
- **Logging:** the executor logs one `agent_test_run_unavailable` record, with `{agent_key, phase, error_class}` only, on the 503 path. A DEBUG-root caplog test confirms that no payload, prompt or output reaches any record. Task 3's exact-set tests are green.

## RED (before implementation)
- Collection RED first: `ModuleNotFoundError: No module named 'src.services.agent_model_payload'` in both new test modules (`red-collection.txt`).
- The payload module was then written, and its 31 tests went GREEN.
- With names-only stubs in the workbench, the scope was **64 failed, 68 passed** (`red.txt`, `red-full.txt`). The causes were `'AgentTestWorkbench' object has no attribute 'execute_candidate_run'` ×41, `execute_baseline_rerun` ×15, `list_test_runs` ×4 and `get_test_run` ×1, plus one test-bug `UnboundLocalError`, fixed before GREEN.
- The draft sibling was written first, then set aside (restored to base with an explicit SHA) until after RED.

## Clause-to-mutation table
- **Driver:** `/tmp/t267-4/mutate.py <PIN>`, run from inside the worktree.
- **Anchors:** every edit's anchor count is asserted to be 1.
- **Marker:** `T267_4_Mnn` sits on the first mutated line. `grep`-count = number of edits, and the RED output proves the line executed.
- **Scopes:**
  - UNIT = `test_agent_test_workbench.py test_agent_model_payload.py test_graph_nodes.py test_model_endpoint_probe.py`.
  - PG = `test_agent_definition_workbench_postgres.py -k "persist_their_exact_identity or candidate_run_holds_no_lock or exclusive_parent_holder"`.
  - Both run with `-q -p no:randomly -rf`, `DATABASE_URL=sqlite:////tmp/t267-4-mut.sqlite` and the brief's PYTHONPATH and pyenv command.
- **Restore:** `git checkout <PIN> -- <file>`. The marker is 0 after restore, and `git diff --quiet <PIN>` is clean for every row.
- **Pins:** M01–M30 ran at `6b7325f90`. M16b, M29 and M30 were re-run at `bfbdbc119` after the test fixes.

| Id | Clause | File | Anchors | Marker | RED (failing tests) | Restore |
|---|---|---|---|---|---|---|
| M01 | plan sabotage: remove the AgentTestRun insert | `agent_test_workbench.py` | 1 | `T267_4_M01`=1 | UNIT: 19 failed, 358 passed, 125 warnings — test_a_baseline_rerun_goes_through_run_on_the_active_release, test_a_candidate_run_copies_the_newest_completed_baseline_outputs, test_a_case_retired_during_the_call_is_recorded_as_not_current, test_a_completed_run_persists_one_row_with_null_verdict_columns, test_a_database_failure_at_the_insert_is_unavailable_with_no_row, test_a_draft_saved_during_the_call_is_recorded_as_not_current (+13 more); PG: 2 failed, 1 passed, 21 deselected, 5 warnings — test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight, test_postgres_candidate_and_baseline_runs_persist_their_exact_identity | `git checkout 6b7325f90`; marker 0, clean=True |
| M02 | C8 controller: model call inside transaction 1 | `agent_test_workbench.py` | 1/1 | `T267_4_M02`=2 | UNIT: 1 failed, 376 passed, 125 warnings — test_the_model_is_called_with_no_open_transaction; PG: 1 failed, 2 passed, 21 deselected, 5 warnings — test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight | `git checkout 6b7325f90`; marker 0, clean=True |
| M03 | C8 reviewer: transaction 1b read under an implicit transaction (no commit), guard off | `agent_test_workbench.py` | 1/1/1 | `T267_4_M03`=3 | UNIT: 36 failed, 341 passed, 125 warnings — test_a_baseline_for_another_case_version_is_not_this_cases_baseline, test_a_baseline_for_another_revision_is_not_this_candidates_baseline, test_a_candidate_run_copies_the_newest_completed_baseline_outputs, test_a_candidate_run_hands_run_candidate_the_saved_draft_content_and_hash, test_a_case_retired_during_the_call_is_recorded_as_not_current, test_a_completed_candidate_run_returns_exact_evidence (+30 more); PG: 3 failed, 21 deselected, 5 warnings — test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight, test_candidate_run_insert_waits_behind_an_exclusive_parent_holder_without_deadlock, test_postgres_candidate_and_baseline_runs_persist_their_exact_identity | `git checkout 6b7325f90`; marker 0, clean=True |
| M04 | C37 controller: session_id in architect's key set | `agent_model_payload.py` | 1 | `T267_4_M04`=1 | UNIT: 6 failed, 371 passed, 125 warnings — test_each_role_key_set_is_the_union_of_its_production_calls[architect], test_no_seeded_identifier_value_survives_any_projection, test_the_previous_deck_review_loses_its_author_as_in_production, test_the_seed_projection_drops_exactly_the_identifier_keys[architect], test_every_role_baseline_model_sees_exactly_the_projected_seed_keys[architect], test_every_role_model_sees_exactly_the_projected_seed_keys[architect] | `git checkout 6b7325f90`; marker 0, clean=True |
| M05 | C37 reviewer: executor passes the stored payload unprojected | `agent_test_workbench.py` | 1 | `T267_4_M05`=1 | UNIT: 8 failed, 369 passed, 125 warnings — test_a_candidate_run_hands_run_candidate_the_saved_draft_content_and_hash, test_a_completed_candidate_run_returns_exact_evidence, test_every_role_model_sees_exactly_the_projected_seed_keys[architect], test_every_role_model_sees_exactly_the_projected_seed_keys[builder], test_every_role_model_sees_exactly_the_projected_seed_keys[data_analyst], test_every_role_model_sees_exactly_the_projected_seed_keys[deck_reviewer] (+2 more) | `git checkout 6b7325f90`; marker 0, clean=True |
| M06 | C10 reviewer: session_id in the builder allowlist | `agent_model_payload.py` | 1 | `T267_4_M06`=1 | UNIT: 8 failed, 369 passed, 125 warnings — test_each_role_key_set_is_the_union_of_its_production_calls[builder], test_no_seeded_identifier_value_survives_any_projection, test_the_builder_set_is_the_production_allowlist_plus_the_retry_instruction, test_the_seed_projection_drops_exactly_the_identifier_keys[builder], test_every_role_baseline_model_sees_exactly_the_projected_seed_keys[builder], test_every_role_model_sees_exactly_the_projected_seed_keys[builder] (+2 more) | `git checkout 6b7325f90`; marker 0, clean=True |
| M07 | C32 controller: drop the lock comparison in the shared helper | `graph_configuration_draft.py` | 1 | `T267_4_M07`=1 | UNIT: 2 failed, 375 passed, 125 warnings — test_a_stale_lock_is_the_null_candidate_conflict_with_no_call_and_no_row, test_model_endpoint_probe_service_stale_lock_conflicts_before_any_probe | `git checkout 6b7325f90`; marker 0, clean=True |
| M08 | C32: drop the post-release endpoint policy re-check | `graph_configuration_draft.py` | 1 | `T267_4_M08`=1 | UNIT: 2 failed, 375 passed, 125 warnings — test_a_url_shaped_stored_endpoint_is_refused_before_any_call, test_model_endpoint_probe_service_rechecks_the_saved_name_policy | `git checkout 6b7325f90`; marker 0, clean=True |
| M09 | C20: baseline may be a candidate row | `agent_test_workbench.py` | 1 | `T267_4_M09`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_no_baseline_is_shown_before_one_is_run | `git checkout 6b7325f90`; marker 0, clean=True |
| M10 | C20: baseline may be a failed run | `agent_test_workbench.py` | 1 | `T267_4_M10`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_failed_baseline_is_never_the_stored_baseline | `git checkout 6b7325f90`; marker 0, clean=True |
| M11 | C20: baseline keyed by agent only, not the case row | `agent_test_workbench.py` | 1 | `T267_4_M11`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_baseline_for_another_case_version_is_not_this_cases_baseline | `git checkout 6b7325f90`; marker 0, clean=True |
| M12 | C20: baseline not keyed by revision | `agent_test_workbench.py` | 1 | `T267_4_M12`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_baseline_for_another_revision_is_not_this_candidates_baseline | `git checkout 6b7325f90`; marker 0, clean=True |
| M13 | C20: oldest baseline instead of newest | `agent_test_workbench.py` | 1 | `T267_4_M13`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_candidate_run_copies_the_newest_completed_baseline_outputs | `git checkout 6b7325f90`; marker 0, clean=True |
| M14 | C16: exception text into error_detail | `agent_test_workbench.py` | 1 | `T267_4_M14`=1 | UNIT: 7 failed, 370 passed, 125 warnings — test_a_failed_baseline_rerun_is_persisted_with_the_same_status_map, test_a_model_failure_is_a_persisted_model_error_with_a_code_only[provider_unavailable-endpoint_unavailable:{endpoint}], test_a_model_failure_is_a_persisted_model_error_with_a_code_only[structured_output_unsupported-structured_output_unsupported:{endpoint}], test_a_provider_parse_failure_is_incomplete_without_raw_output, test_an_unassemblable_candidate_is_an_assembly_error_before_the_model, test_an_undeclared_output_field_is_incomplete_with_its_raw_keys_and_issue (+1 more) | `git checkout 6b7325f90`; marker 0, clean=True |
| M15 | C17: incomplete check drops the registry issues | `agent_test_workbench.py` | 1 | `T267_4_M15`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_an_undeclared_output_field_is_incomplete_with_its_raw_keys_and_issue | `git checkout 6b7325f90`; marker 0, clean=True |
| M16 | C17: checks_passed ignores the status | `agent_test_workbench.py` | 1 | `T267_4_M16`=1 | UNIT: 377 passed, 125 warnings | `git checkout 6b7325f90`; marker 0, clean=True |
| M16b | C17: checks_passed always true | `agent_test_workbench.py` | 1 | `T267_4_M16b`=1 | UNIT: 3 failed, 375 passed, 125 warnings — test_a_model_failure_is_a_persisted_model_error_with_a_code_only[provider_unavailable-endpoint_unavailable:{endpoint}], test_a_model_failure_is_a_persisted_model_error_with_a_code_only[structured_output_unsupported-structured_output_unsupported:{endpoint}], test_an_undeclared_output_field_is_incomplete_with_its_raw_keys_and_issue | `git checkout bfbdbc119`; marker 0, clean=True |
| M17 | C15: candidate raw output not taken from the observer | `agent_test_workbench.py` | 1 | `T267_4_M17`=1 | UNIT: 3 failed, 374 passed, 125 warnings — test_a_completed_candidate_run_returns_exact_evidence, test_a_v2_overlay_candidates_structured_output_keeps_its_optional_fields, test_an_undeclared_output_field_is_incomplete_with_its_raw_keys_and_issue | `git checkout 6b7325f90`; marker 0, clean=True |
| M18 | C8.5: candidate_is_current always true | `agent_test_workbench.py` | 1 | `T267_4_M18`=1 | UNIT: 2 failed, 375 passed, 125 warnings — test_a_case_retired_during_the_call_is_recorded_as_not_current, test_a_draft_saved_during_the_call_is_recorded_as_not_current; PG: 1 failed, 2 passed, 21 deselected, 5 warnings — test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight | `git checkout 6b7325f90`; marker 0, clean=True |
| M19 | C8.5: base_release_is_current always true | `agent_test_workbench.py` | 1 | `T267_4_M19`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_publication_during_the_call_keeps_the_run_on_its_base_release | `git checkout 6b7325f90`; marker 0, clean=True |
| M20 | C8.6: no retry of the handoff diagnosis | `agent_test_workbench.py` | 1 | `T267_4_M20`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_handoff_race_in_transaction_two_is_retried_once | `git checkout 6b7325f90`; marker 0, clean=True |
| M21 | C8.6: retry any integrity failure | `agent_test_workbench.py` | 1 | `T267_4_M21`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_second_handoff_race_or_another_integrity_failure_is_unavailable[1-graph | `git checkout 6b7325f90`; marker 0, clean=True |
| M22 | C16: a transaction-2 database failure is not 503 | `agent_test_workbench.py` | 1 | `T267_4_M22`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_database_failure_at_the_insert_is_unavailable_with_no_row | `git checkout 6b7325f90`; marker 0, clean=True |
| M23 | C16: a transaction-1 database failure is not 503 | `agent_test_workbench.py` | 1 | `T267_4_M23`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_database_failure_before_the_call_is_unavailable_with_no_call | `git checkout 6b7325f90`; marker 0, clean=True |
| M24 | M-1: sentinel revision id as compared revision | `agent_test_workbench.py` | 1 | `T267_4_M24`=1 | UNIT: 36 failed, 341 passed, 125 warnings — test_a_baseline_for_another_case_version_is_not_this_cases_baseline, test_a_baseline_for_another_revision_is_not_this_candidates_baseline, test_a_candidate_run_copies_the_newest_completed_baseline_outputs, test_a_candidate_run_hands_run_candidate_the_saved_draft_content_and_hash, test_a_case_retired_during_the_call_is_recorded_as_not_current, test_a_completed_candidate_run_returns_exact_evidence (+30 more) | `git checkout 6b7325f90`; marker 0, clean=True |
| M25 | C33: default runtime is the unbounded production runtime | `agent_test_workbench.py` | 1 | `T267_4_M25`=1 | UNIT: 1 failed, 376 passed, 126 warnings — test_the_default_executor_uses_the_bounded_test_runtime | `git checkout 6b7325f90`; marker 0, clean=True |
| M26 | C22/P5: an inactive case may be run | `agent_test_workbench.py` | 1 | `T267_4_M26`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_an_inactive_case_version_is_refused_with_no_call | `git checkout 6b7325f90`; marker 0, clean=True |
| M27 | C22: a case of another role may be run | `agent_test_workbench.py` | 1 | `T267_4_M27`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_case_of_another_role_is_refused_with_no_call | `git checkout 6b7325f90`; marker 0, clean=True |
| M28 | C15: structured output drops the validated optional fields | `agent_test_workbench.py` | 1 | `T267_4_M28`=1 | UNIT: 1 failed, 376 passed, 125 warnings — test_a_v2_overlay_candidates_structured_output_keeps_its_optional_fields | `git checkout 6b7325f90`; marker 0, clean=True |
| M29 | C19/C20: a baseline run records the draft hash, not the revision's | `agent_test_workbench.py` | 1 | `T267_4_M29`=1 | UNIT: 1 failed, 377 passed, 125 warnings — test_a_baseline_rerun_records_the_published_revision_not_the_edited_draft | `git checkout bfbdbc119`; marker 0, clean=True |
| M30 | C8: transaction 2 does not re-lock the parents | `agent_test_workbench.py` | 1 | `T267_4_M30`=1 | UNIT: 3 failed, 375 passed, 125 warnings — test_a_handoff_race_in_transaction_two_is_retried_once, test_a_second_handoff_race_or_another_integrity_failure_is_unavailable[1-graph, test_a_second_handoff_race_or_another_integrity_failure_is_unavailable[2-graph; PG: 1 failed, 2 passed, 21 deselected, 5 warnings — test_candidate_run_insert_waits_behind_an_exclusive_parent_holder_without_deadlock | `git checkout bfbdbc119`; marker 0, clean=True |

**Survivors and how each was resolved:**
- **M16** (`deterministic_checks_passed` drops the `status == 'completed'` term) is an **equivalent mutation**. Every non-completed run carries a failed check by construction, so `all(passed)` is already False. M16b (`checks_passed=True`) REDs 3.
- **M29** (a baseline records the draft hash) survived at `6b7325f90`, because a bootstrapped draft hash equals the revision hash. The fix was `test_a_baseline_rerun_records_the_published_revision_not_the_edited_draft` (`bfbdbc119`), and M29 then REDs 1.
- **M30 PG** first *hung*: the L0-holder test waited forever in pool shutdown. The test now rolls the holder back in an inner `finally`. On the re-run, M30 REDs the holder test (PG 1 failed) plus 3 unit retry tests.
- The killed hung run may have leaked one `tellr_int_*` throwaway database on localhost. I did not drop any, because I cannot tell mine from other agents'.

## Sabotage targets and the tests they hit
| Target | Mutation | Tests that RED |
|---|---|---|
| Plan Task 4: remove the insert | M01 | PG `test_postgres_candidate_and_baseline_runs_persist_their_exact_identity` (+ the in-flight proof), plus 19 unit tests including `test_a_completed_run_persists_one_row_with_null_verdict_columns` |
| C8 controller: model call inside transaction 1 | M02 | unit `test_the_model_is_called_with_no_open_transaction`; PG `test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight` |
| C8 reviewer: remove the transaction-1 commit | M03 | PG in-flight proof (the `pg_locks`/`idle in transaction` assertion), the holder test and the identity test; unit 36 |
| C37 controller: `session_id` in architect's set | M04 | `test_each_role_key_set_is_the_union_of_its_production_calls[architect]`, `test_every_role_model_sees_exactly_the_projected_seed_keys[architect]`, `test_no_seeded_identifier_value_survives_any_projection` (+3) |
| C37 reviewer: stored payload unprojected | M05 | `test_every_role_model_sees_exactly_the_projected_seed_keys[architect|data_analyst|builder|deck_reviewer]`, `test_a_builder_test_run_prompt_is_byte_identical_to_the_builder_nodes`, `test_the_builder_prompt_carries_no_seeded_session_identifier` (+2) |
| C10 reviewer: `session_id` in the builder allowlist | M06 | `test_the_builder_prompt_carries_no_seeded_session_identifier` ("synthetic-builder" not in prompt), `test_the_builder_set_is_the_production_allowlist_plus_the_retry_instruction`, the byte-identical parity (+5) |
| C32 controller: drop the helper's lock comparison | M07 | `test_a_stale_lock_is_the_null_candidate_conflict_with_no_call_and_no_row` **and** #266's `test_model_endpoint_probe_service_stale_lock_conflicts_before_any_probe` |

The C10 controller target ("executor passes unfiltered") is the same edit as M05. Suggested fresh reviewer targets: M13 (baseline order), M21 (retry any integrity failure) and M30 (transaction 2 without the parent lock).

## Gates
- **Focused** (the plan's Task 4 files plus `test_agent_runtime`, `test_persisted_agent_runtime`, `test_agent_test_workbench`, `test_graph_nodes`, `test_model_endpoint_probe`, `test_graph_configuration_draft`, `test_agent_definition_workbench_routes`, `test_graph_configuration_workbench`, `test_ci_collects_integration_tests` and `test_agent_model_payload`): **1053 passed** at `7e9882fa1`. The later commits added 3 unit tests, which are inside the full run.
- **Full `tests/unit -q -p no:randomly -rf`:** **6 failed, 6477 passed, 110 skipped, 136 warnings**. These are exactly the baseline six, with the same causes: autoscaling ×2 (`'provisioned' == 'autoscaling'`, called 0 times), chokepoint ×3 (`_FakeSession` has no `execute`), and persistence-boundary ×1 (no active Graph Release).
- **PostgreSQL** (one invocation per file, **zero skips**): workbench 24 (17 base + 4 Task 2 + 3 new), constraints 66, runtime failures 7, overlay 10, bootstrap 3. The new lock-release proof alone: 3 passed, 0 skipped. No new PostgreSQL file, so there is no CI-guard or `test.yml` change.
- **`ruff check`** over the touched and new files: identical to base by rule and count. The one F811 in `test_graph_nodes.py` is noqa'd in the file's own fixture convention.
- `test ! -e .venv` held before and after. Nothing was installed. `ai_slide_generator` was not touched.

## Concerns (for the controller)
1. **Observing adapter (private access).** The prompt a failed run sent (`model_error` or `incomplete`), and the raw output of a baseline run through `run` (which has no observer), are captured by `_observed()`. It takes a per-run `copy.copy` of the runtime and wraps its `_model_adapter` in a pass-through `_ObservingModelAdapter`. The inner adapter gets identical arguments, and results and exceptions pass through unchanged. Without it, `assembled_prompt` would be NULL on every non-completed run, and baseline `candidate_raw_output` would always be NULL.
   - The workbench also imports the private `_classify_candidate_failure` and `_supplied_output_keys` from `agent_runtime`, and calls `_lock_current_parents` as C8 prescribes.
   - The alternative is an additive public hook on `AgentRuntime`, which would touch Task 3's reviewed file.
   - Cost if wrong: a reviewer may prefer the hook; behaviour is identical.
2. **The baseline run logs through production's identity sink.** `run` uses `get_agent_test_runtime()`'s `LoggingAgentInvocationIdentitySink`, so a baseline rerun writes a real `persisted_agent_invocation` record: the active release, the real revision, and empty root and actor session ids. It is a genuine published invocation, so no sentinel is involved, but it is not a conversation. Rule whether that is acceptable, or whether baselines should also bypass the sink (that would need `run` changes).
3. **The published endpoint name is not re-checked** before a baseline run, unlike the candidate probe read. It was policy-checked when the draft that became the revision was saved.
4. **Currency flags are response-only.** `get_test_run` and `list_test_runs` return `None` for both flags. Task 5 must serialize them as nullable, or omit them on reads.
5. **Order of refusals for a candidate run:** actor → lock and role (`DraftContentRejected` 422) → stale lock (409) → stored endpoint policy (422) → case not found (404) → role mismatch (422) → inactive (409). Task 5 maps these types. `TestCaseRejected` is used for the actor and baseline-role issues.
6. **#269 fit:**
   - The rows carry `run_kind='candidate'` for candidate runs, `compared_release_id` = the draft's base release, `compared_definition_revision_id` = that release's mapped revision, and `candidate_hash` = the draft hash, with verdict columns NULL. That fits #269's gate predicate, as long as #269 and #268 add `run_kind='candidate'`, as already carried.
   - Transaction 2's lock statement is `_lock_current_parents(exclusive=False)`: `SELECT … FROM graph_release JOIN graph_draft ON true WHERE graph_release.effective_to IS NULL FOR SHARE OF graph_release, graph_draft`, then the insert.
   - A PostgreSQL test proves that transaction 2 waits behind an L0 `FOR UPDATE` holder without deadlock, and commits after it. #269 C13 item 3's two-order test against a *real* publication remains #269 Task 4's job, because no publication code exists yet.
   - After a publication, #269's `_lock_current_parents` retry, if it lands, composes with this executor's own single retry: at most two rounds, and the model is never re-invoked.
7. **Test infrastructure:** `_HookedFakeAdapter`'s hook runs inside the model call. An exception there becomes a persisted `unexpected_error` run instead of a test error. The hooks used only append to lists or perform committed writes.

## Fix round 1

Base: `07d4cf874`, pinned. Commits:
- `19d910ac5` refactor: give test runs a public runtime observer hook (#267)
- `913cdfe40` fix: check the published endpoint name before a baseline rerun (#267)

### I-1: a public observer hook in place of private-attribute wrapping (ADDRESSED)
- **Removed from `agent_test_workbench.py`:**
  - `_ObservingModelAdapter`;
  - `_observed()`, the per-run `copy.copy` that overwrote `_model_adapter`;
  - the imports of the private `_classify_candidate_failure` and `_supplied_output_keys`.
- **Added to `agent_runtime.py`** (additive only):
  - `RunObservation`, a public recorder of three values: `prompt` (the exact prompt passed to the adapter), `raw_output` (the supplied keys, observed before validation) and `model_latency_ms` (the adapter call's duration, recorded on both return and raise).
  - `run_candidate(..., *, observation=None)`.
  - `run_published_baseline(agent_key, graph_release_id, payload, assembly_context, *, observation=None) -> CandidateRunOutcome`:
    - Its role check and its loader `try/except` are pinned AST-equal to `run`'s by `test_run_published_baseline_resolves_exactly_as_run_does`.
    - A loader failure raises exactly as it does from `run`.
    - It then calls the same `_run_resolved`, with the production identity sink (concern-2 ruling), and classifies failures into the outcome.
  - A private `_run_observed`, shared by both public entries.
  - A private keyword-only `_observation` on `_run_resolved`. It sets the prompt before `invoke` and the latency in a `finally`. `run` passes nothing.
  - `_classify_candidate_failure` is renamed to the public `classify_test_run_failure`. It is used inside the runtime only.
- **The workbench** calls `run_candidate(..., observation=...)` and `run_published_baseline(..., observation=...)`. Resolution errors are mapped as before: `lakebase_unavailable` is a 503; any other code, or a missing or incomplete release, is `assembly_error`.
- **AST proof** (`/tmp/t267-4/ast_identity.py`, `ast_identity.txt`): `AgentRuntime.run`, `get_agent_runtime` and `get_agent_test_runtime` are IDENTICAL to `b678b48fd`, to `07d4cf874` and to Task 3's base `dec69b365`.
- **Other constraints held:**
  - There is still exactly one `with_structured_output(` in `src`.
  - The production adapter kwargs test (`:645-677`) passes unedited.
  - The prompt-parity tests (28 cases), the byte-identical builder parity and the log exact-set tests stay green.
  - `test_run_candidate_delegates_to_run_resolved_and_never_to_run` now follows `run_candidate` → `_run_observed` → `_run_resolved`, with the same forbidden-name set.
- **New guards in `test_agent_runtime.py`:**
  - `test_run_published_baseline_is_reachable_only_from_the_agent_test_workbench`
  - `test_no_module_outside_the_runtime_touches_its_model_adapter` (the `_model_adapter` attribute or name may appear only in `agent_runtime.py`)
  - `test_no_module_imports_a_private_name_from_the_runtime`
  - Hook tests: the baseline entry sends `run`'s prompt and records the real identity; an observation keeps the prompt and duration of a failed call; loader failures raise as they do from `run`.

### I-2: re-check the published endpoint name before a baseline rerun (ADDRESSED)
- **The check:** after transaction 1 and before the model call, `validate_endpoint_name_policy(endpoint_name)` runs on the published revision's endpoint name.
- **The refusal:** a URL- or path-shaped name raises `DraftContentRejected(DraftValidationIssue("published.model.endpoint_name", failure.code, failure.message))`. This is the candidate path's outcome family: 422 with the catalog-owned code `endpoint_url_not_allowed` and its fixed message.
- **What does not happen:** the stored name is never echoed, there is no model call, and no row is written, so nothing reaches `error_detail`.
- **Test:** `test_a_url_shaped_published_endpoint_is_refused_before_a_baseline_call`, the twin of the candidate URL test.
  - RED against `19d910ac5`: `DID NOT RAISE DraftContentRejected` (`/tmp/t267-4/fix1-red.txt`).
  - GREEN at `913cdfe40`.

### Sabotage (driver `/tmp/t267-4/fix1_mut.py`, pin `913cdfe40`)
- Scope: `tests/unit/test_agent_test_workbench.py tests/unit/test_agent_runtime.py`.
- Every row had anchor count 1, marker count 1 on the mutated line, marker 0 after restore, and a clean diff.

| Id | Clause | File | Anchors | Marker | RED | Restore |
|---|---|---|---|---|---|---|
| F1 | I-1 sabotage: private adapter override in the workbench | `agent_test_workbench.py` | 1 | 1 | 1 failed, 242 passed, 5 warnings — test_no_module_outside_the_runtime_touches_its_model_adapter | `git checkout 913cdfe40`; marker 0, clean=True |
| F2 | I-1 sabotage: private runtime import in the workbench | `agent_test_workbench.py` | 1 | 1 | 1 failed, 242 passed, 5 warnings — test_no_module_imports_a_private_name_from_the_runtime | `git checkout 913cdfe40`; marker 0, clean=True |
| F3 | I-2 sabotage: remove the published endpoint check | `agent_test_workbench.py` | 1 | 1 | 1 failed, 242 passed, 5 warnings — test_a_url_shaped_published_endpoint_is_refused_before_a_baseline_call | `git checkout 913cdfe40`; marker 0, clean=True |
| F4 | hook: prompt not recorded | `agent_runtime.py` | 1 | 1 | 4 failed, 239 passed, 5 warnings — test_a_model_failure_is_a_persisted_model_error_with_a_code_only[provider_unavailable-endpoint_unavailable:{endpoint}], test_a_model_failure_is_a_persisted_model_error_with_a_code_only[structured_output_unsupported-structured_output_unsupported:{endpoint}], test_run_published_baseline_hands_the_model_runs_prompt_and_records_the_real_identity, test_an_observation_keeps_the_prompt_and_duration_of_a_failed_model_call | `git checkout 913cdfe40`; marker 0, clean=True |
| F5 | hook: failed-call latency not recorded | `agent_runtime.py` | 1 | 1 | 2 failed, 241 passed, 5 warnings — test_run_published_baseline_hands_the_model_runs_prompt_and_records_the_real_identity, test_an_observation_keeps_the_prompt_and_duration_of_a_failed_model_call | `git checkout 913cdfe40`; marker 0, clean=True |
| F6 | hook: baseline resolution drifts from run (drops the SQLAlchemy mapping) | `agent_runtime.py` | 1 | 1 | 2 failed, 241 passed, 5 warnings — test_run_published_baseline_resolves_exactly_as_run_does, test_run_published_baseline_raises_loader_failures_as_run_does | `git checkout 913cdfe40`; marker 0, clean=True |
| F7 | hook: baseline uses the pass-through sink (not the production log) | `agent_runtime.py` | 1 | 1 | 1 failed, 242 passed, 5 warnings — test_run_published_baseline_hands_the_model_runs_prompt_and_records_the_real_identity | `git checkout 913cdfe40`; marker 0, clean=True |

### Gates
- **Focused** (the Task 4 files plus `test_agent_runtime`, `test_persisted_agent_runtime`, `test_agent_test_workbench`, `test_graph_nodes`, `test_model_endpoint_probe`, `test_graph_configuration_draft`, the routes, the workbench and the CI collector): **1063 passed**.
- **Full `tests/unit`** (`DATABASE_URL=sqlite:////tmp/t267-4.sqlite`): **6 failed, 6485 passed, 110 skipped**. These are exactly the baseline six nodes with the same causes.
- **PostgreSQL**, zero skips: workbench **24**, runtime failures **7**.
- **Ruff:** clean on the touched files.
- `.venv` was absent before and after, and nothing was installed.

### Deferred
- **m-1:** transaction 2 retries only the `_lock_current_parents` handoff diagnosis, not a SQLAlchemy `IntegrityError`. A run insert racing a publication either waits on the lock or sees the handoff, so the two are near-equivalent. This is recorded here and not changed.
