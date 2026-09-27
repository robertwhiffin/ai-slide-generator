# #270 Task 2 report: compare, structural validation, rollback preview

**Status:** DONE. Task 2 writes nothing to the database.

- **TASK_BASE:** `e4385f487`
- **Commit:** `624385f08` "feat: compare graph releases and preview a rollback (#270)"
- **Diff `e4385f487..624385f08`:** 4 files, +~1060 lines. No #269 file is touched: no change to `graph_configuration_publication.py`, `graph_release_evidence.py`, the draft module, or any #269 test.

| File | Change |
|---|---|
| `src/services/graph_configuration_rollback.py` | new |
| `src/services/graph_configuration.py` | `_GraphConfigurationRollback` is now the first base; `__all__` gains 5 names |
| `src/services/graph_release_history.py` | behaviour-preserving extraction of `_release_definitions` (C33) |
| `tests/unit/test_graph_release_rollback.py` | new, 21 tests |

## Corrections applied

| Correction | How it was applied |
|---|---|
| C1 / C42 | Added `ReleaseClock` and `install_release_clock`, which patch `graph_configuration_publication.database_transaction_timestamp` to return `v1_from + n h`. Every setup pins `clock.call_count`. The GREEN demonstration `test_release_clock_publishes_v2_to_v8_in_sequence_on_sqlite` runs 7 publishes and checks versions `[1..8]`. No sleep and no backdating. |
| C2 + C34 | `RollbackPreview.warnings` holds the remote check's results. The check runs **after** `with session.begin()` exits, through `_validate_remote_endpoint`, once per distinct endpoint. Every role that uses a failing endpoint gets a warning, in `GRAPH_V1_AGENT_KEYS` order. Warnings never set `blocked`. A `restorable` property (`blocked is None`) was added. Plan line 536's test is replaced by the two C2 tests plus a de-dup test. |
| C12 via C33 | Option B. `_load_source` = `_read_history` + `_release_definitions`, with no private loader import. The TypeError test monkeypatches `graph_configuration_content.definition_content_from_row`. The result is `GraphConfigurationIntegrityError("… has invalid semantic content")` with a `TypeError` cause. |
| C20(b) via C32 | `_structural_issues` runs `_save_local_validators()` (which includes #266's endpoint-name policy) then `post_stale_validators`, in one `try` per role, with the `definitions.<key>.` prefix. C32's endpoint test was added. |
| C22 via C33 | `compare_with_active` is lock-free. It opens `with session.begin()`, runs one `_read_history` (the first statement), then `_release_definitions` for the active and historical mappings. |
| C26 | Rollback owns the three refusals: `blocked` in `source_is_active`, `matches_active`, `incompatible` order. Issues are computed even when an earlier check blocks. |
| C27 | `EvidenceLink(run_id, agent_key, test_case_id, "historical_restore", source_release_id)`. |
| C28 | `_historical_evidence(lock=True)` = `… ORDER BY agent_test_run.id FOR UPDATE OF agent_test_run`, plus `populate_existing`. `lock=False` takes no lock. The link count that follows is a new statement. |
| C29 | `preview_rollback`'s first statement in its fresh transaction is `_lock_current_parents(exclusive=False)`. No rollback function names `GraphRelease` or `GraphDraft` together with `with_for_update`, and the AST scanner is green and unedited. The module imports neither `graph_release_evidence`, `agent_test_workbench` nor `agent_runtime` at module scope; a test pins this. |
| C35 | `_draft_effect` is the three-way default: pending → `kept`, clean and different → `reset`, clean and identical → `unchanged`. |

## RED

With the implementation moved aside, `tests/unit/test_graph_release_rollback.py` failed at collection:

`ImportError: cannot import name 'AgentComparison' from 'src.services.graph_configuration'`

The tests import through the facade, so collection fails on the missing export. That is the plan's predicted `ModuleNotFoundError` seen one hop earlier. The implementation was then restored, and the first GREEN run had one test-side failure: the compiled PostgreSQL SQL contained a newline. The test now normalises whitespace.

## Gates (all at `624385f08`)

All Python runs used `PYTHONPATH=<W>:<W>/packages/databricks-tellr` and `DATABASE_URL=sqlite:////tmp/t270-2.sqlite`.

| Gate | Result |
|---|---|
| New unit file, history unit file, #269 publication and preview unit files, draft, workbench, and the AST scanner | 281 passed |
| Full `tests/unit` | 6 failed / 6996 passed / 110 skipped (baseline 6975 passed, plus the 21 new tests) |
| The 6 failures | Exactly the baseline nodes, with the same causes, re-run and checked: `'provisioned' == 'autoscaling'` and a provisioned mock not called (×2); `'_FakeSession' object has no attribute 'execute'` (×3); `ConversationGraphReleaseIntegrityError: no active Graph Release` (×1). The run started 05:12 UTC, so no midnight crossing. |
| ruff on the 4 changed files | clean |
| PostgreSQL (no file is named by the brief; run as a check on the extraction and the MRO) | `test_graph_release_history_postgres.py` 4 passed, 0 skips; `test_graph_release_publication_postgres.py` 21 passed, 0 skips |
| `tellr_int_*` databases | the same 4 older ones before and after; none leaked |

## Mutation table

- **Driver:** `/tmp/t270-2/mutate.py`. Logs are in `/tmp/t270-2/mut/`.
- **Per mutation, the driver:**
  1. asserts the file equals `git show 624385f08:<path>`;
  2. asserts the anchor occurs exactly once;
  3. applies the mutation with a `MUT-<id>` marker (count 1);
  4. runs `tests/unit/test_graph_release_rollback.py` and `tests/unit/test_graph_release_history.py`;
  5. restores the SHA's bytes and asserts `git diff --quiet 624385f08 -- <path>`.
- **After the sweep:** `git status` is clean.
- **Reviewer targets:** R1 is the plan's reviewer sabotage. R2 is C32's reviewer addition.
- **Controller target:** `_structural_issues → ()` is not mine and was not run. M04 and M20 cover the same seam.

| ID | Clause | Mutation | RED tests |
|---|---|---|---|
| R1 | `_draft_effect` "pending" is relative to the active release | `candidate_hash != restored_hashes[key]` | `test_preview_draft_effect_is_three_way` |
| R2 | structural validation includes #266's endpoint policy (C32) | `_save_local_validators()` → `local_candidate_validators` | `test_endpoint_name_policy_makes_a_historical_release_incompatible` |
| M01 | `blocked` order | `incompatible` checked first | `test_blocked_is_the_first_applicable_check_and_issues_are_still_reported` |
| M02 | `source_is_active` | `if False` | `…blocks_source_active_then_matches_active`, `…first_applicable_check…` |
| M03 | `matches_active` | `elif False` | `…blocks_source_active_then_matches_active` |
| M04 | `incompatible` | `elif False` | `…incompatible…per_role`, `…endpoint_name_policy…`, `…failed_local_phase…` |
| M05 | `unchanged` branch | `elif False` | `test_preview_draft_effect_is_three_way` |
| M06 | compare is lock-free (C22) | add `_lock_current_parents(exclusive=False)` | `test_compare_takes_no_parent_lock_and_does_no_remote_work` |
| M07 | remote check after commit (C2/C34) | move `_endpoint_warnings` inside the transaction | `…remote_check_after_the_locked_transaction`, `…each_distinct_endpoint_once…` |
| M08 | one call per distinct endpoint (C34) | drop the de-dup `continue` | `…remote_check_after…`, `…each_distinct_endpoint_once…` |
| M09 | every role using a failing endpoint is warned | only the first role | `…failures_are_warnings_that_never_block`, `…each_distinct_endpoint_once…` |
| M10 | evidence `run_kind='candidate'` filter | drop it | `test_preview_source_linked_to_a_non_candidate_run_is_an_integrity_error` |
| M11 | filtered vs unfiltered link count | `if False` | same |
| M12 | evidence order (role, case, run) | sort by run id | `…historical_restore_in_role_order`, `…l3_for_update_in_id_order` |
| M13 | kind is `historical_restore` | `"approval"` | `…historical_restore_in_role_order` |
| M14 | `source_release_id` = source | `None` | `…historical_restore_in_role_order` |
| M15 | L3 `FOR UPDATE OF agent_test_run` (C28) | drop `with_for_update` | `test_locked_historical_evidence_is_l3_for_update_in_id_order` |
| M16 | L3 `populate_existing` | `False` | same |
| M17 | L3 id order | drop `order_by` | same |
| M18 | evidence filtered to the source release | drop the `graph_release_id` filter | `…historical_restore_in_role_order` (v3 preview gains v2's runs) |
| M19 | a failed local phase skips post-stale (one `try`) | two separate `try`s | `…incompatible…per_role`, `…endpoint_name_policy…`, `…failed_local_phase…` |
| M20 | `definitions.<key>.` prefix on issues | unprefixed | the same 3 |
| M21 | unknown version raises `GraphVersionNotFound` | `LookupError` | `test_unknown_version_is_not_found` |
| M22 | `next_version_number = active + 1` | `active` | `…next_version_lineage_evidence_and_default_note` |
| M23 | default note uses the version number | `source.ref.release_id` | **survived (equivalent in fixture):** SQLite ids equal the version numbers |
| M24 | diff sides (`published` = active) | arguments swapped | `test_compare_active_with_historical_lists_seven_roles_with_exact_diffs` |
| M25 | `lock_version` from the draft row | `+ 1` | `…next_version_lineage_evidence_and_default_note` |
| M26 | `same_revision` by revision id | by content equality | **survived (equivalent):** `(agent_key, content_hash)` reuse makes equal content imply the same revision (#269's reuse guard) |
| M27 | warning field prefix | unprefixed | `…failures_are_warnings…`, `…each_distinct_endpoint_once…` |
| M28 | `read_release_detail` passes its own entry's mapping to `_release_definitions` | the newest entry's mapping | `test_graph_release_history.py::test_mapping_to_another_roles_revision_is_an_integrity_error` |

## Deviations

1. **`_load_source` returns a `_HistoricalSource(ref, definitions)`, not `(release, {k: resolved[k]})`.** It has a `contents` property holding the seven `DefinitionContent`s. This follows C33: the history read model returns `ReleaseDefinition`s (revision id, hash, content). Task 3a needs all three, for the matches-active ids, the hashes for `_draft_effect`, and the contents for the core.
2. **`_historical_evidence` and `_draft_effect` are `@staticmethod`s.** Both are called through `self`, so the signatures match the brief apart from `self`.
3. **There is a private `_source_from_history(session, history, *, version_number)` helper.** `compare_with_active` needs the source from the same single `_read_history` as its active side (C33 point 4, no two-snapshot skew). `_load_source` wraps it with its own `_read_history`.
4. **The preview's comparison takes the active side from the locked workbench snapshot's `published` nodes.** It does not do a second `_release_definitions` read. The historical side comes from `_load_source`. `test_preview_names_…` asserts `preview.comparison == compare_with_active(2)`.
5. **Warnings are computed whenever a validator is composed, even when `blocked` is set.** This parallels "issues are computed even when an earlier check blocks". It costs at most (distinct endpoints) × ~15 s. With no validator (`None`), no warnings are computed.
6. **Tests added beyond the brief:**
   - blocked order plus issues when blocked;
   - one `try` per role;
   - de-dup and per-role warning mapping;
   - evidence order and kind;
   - the non-candidate link;
   - the L3 statement compiled for PostgreSQL;
   - the exact seven from `_load_source`;
   - the module import hygiene (C29);
   - the facade's first base.
7. **The brief's `_MustNotRun` preview test** is replaced per C2. `_MustNotRun` is still used to prove `compare_with_active` does no remote work, and the `AgentRuntime.__init__`-raises monkeypatch lives in the after-commit test.
8. **The incompatible test's exact field is `protected_assembly.version`.** Every v1-lineage role uses bundle `(1, e4ff…)`. Removing it leaves only version 2, so version 1 is unknown (`prompt_assembler.py:413–416`). As a result all seven roles report the issue, and the test asserts issues[0] exactly and the role order of all of them.
9. **The fixture factory** is #269's `factory`, imported by assignment (`factory = publication_tests.factory`) so ruff raises no F811. `_NoEvidenceGate`, `_save_prompt` and `_artifacts` are imported by underscore name, and `seed_case`, `seed_run` and `link_run` come from Task 1's unit file. None is redefined.

## Interfaces for Task 3a and later

**`src/services/graph_configuration_rollback.py`:**

| Line | Interface |
|---|---|
| :64 | `DraftEffect` |
| :65 | `RollbackBlock` |
| :71 | `AgentComparison` |
| :82 | `ReleaseComparison` |
| :90 | `RollbackPreview`, with fields `source, active, next_version_number, lock_version, default_release_note, comparison, evidence, draft_effect, issues, warnings, blocked` and the `restorable` property at :113 |
| :118 | `_HistoricalSource(ref, definitions)`, with `.contents` at :124 |
| :130 | `_compare(...)` |
| :153 | `_GraphConfigurationRollback(_GraphConfigurationPublication)` |
| :156 | `compare_with_active(session, *, version_number)` |
| :183 | `preview_rollback(session, *, version_number)` |
| :246 | `_load_source(session, *, version_number) -> _HistoricalSource`, called inside the caller's L0 transaction |
| :258 | `_source_from_history` |
| :271 | `_structural_issues(contents)` |
| :295 | `_draft_effect(snapshot, restored_hashes)` → a seven-entry `MappingProxyType` |
| :317 | `_historical_evidence(session, *, source_release_id, lock)`; Task 3a calls it with `lock=True` after L1 |
| :361 | `_endpoint_warnings(contents)`, preview only; `restore_release` must not call it |

**Other files:**

| Location | Interface |
|---|---|
| `src/services/graph_release_history.py:202` | `_release_definitions(session, mapping)` |
| `src/services/graph_release_history.py:119` | `_read_history` |
| `src/services/graph_configuration.py` | exports `AgentComparison`, `DraftEffect`, `ReleaseComparison`, `RollbackBlock`, `RollbackPreview` |

**Test harness in `tests/unit/test_graph_release_rollback.py`** (for Tasks 3a and 6):

| Line | Helper |
|---|---|
| :78 | `ReleaseClock` |
| :90 | `install_release_clock(monkeypatch, factory)` |
| :103 | `current_lock` |
| :117 | `publish` |
| :130 | `save_prompt_text` |
| :134 | `save_endpoint` |
| :153 | `refs` |
| :159 | `build_v2_v3_v4(factory, monkeypatch)`; `clock.call_count == 3` |
| :197 | `mapping` |
| :209 | `_MustNotRun` |
| :214 | `_RecordingValidator` |

## Concerns

1. **Two mutations survive as equivalent.**
   - M23 (note text from the release id): SQLite and PostgreSQL ids are sequential and equal the version numbers in every fixture. It is killable only on a database where ids and versions diverge, which happens in production after a rolled-back PostgreSQL sequence use. Low risk, since the code reads `version_number`.
   - M26 (`same_revision` by content): equivalent while #269's `(agent_key, content_hash)` revision reuse holds.
2. **The preview's warnings run even for a blocked source.** See Deviation 5. If the controller prefers to skip the remote check when `blocked` is set, the change is one `if` in `preview_rollback`, and one test would need a non-blocked source (all current warning tests already use one).
3. **The C35/Q7 disclosure still stands for Task 3a:** a kept edit with an approved run stays approved after rollback, as C20(a) records. Task 2 only reports `draft_effect`.
4. **The RED was an `ImportError` on the facade export, not a `ModuleNotFoundError`.** The cause is the same: the module was absent.
