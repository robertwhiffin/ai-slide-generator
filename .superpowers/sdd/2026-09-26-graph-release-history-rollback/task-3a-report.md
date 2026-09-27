# #270 Task 3a report: restore a historical release as the next Graph Version

**Status:** DONE_WITH_CONCERNS. The concerns are minor; see the end of this report.

- **TASK_BASE:** `6dbd051c7`
- **Scope:** Correction 16's 3a only: the `_assign_locked_candidate` extraction, `restore_release`, `_validate_rollback_request`, `_verify_rebased_draft`, and the SQLite unit tests. No PostgreSQL file, no `test.yml` change, and no CI pin; those belong to 3b.

## Commits

| SHA | Message | Files |
|---|---|---|
| `d64ba5ce0` | feat: restore a historical graph release as the next version (#270) | `src/services/graph_configuration_rollback.py`, `src/services/graph_configuration_draft.py`, `src/services/graph_configuration.py` (5 exports), `tests/unit/test_graph_release_rollback.py` |
| `5e15d5cf2` | refactor: one post-condition per draft effect in the rebase check (#270) | rollback module (`_verify_rebased_draft` only) and the unit file (+1 case) |

`git diff --stat 6dbd051c7 HEAD` covers 4 files, +868/−7. No #269 file is touched: `graph_configuration_publication.py`, `graph_release_evidence.py` and the #269 tests are all unchanged.

## Corrections applied

| Correction | How it was applied |
|---|---|
| C16 | 3a scope only. This commit has no PostgreSQL work, and the 3b controller seam was not run. |
| C18 | `_publish_v8_matching_v5`: after v2–v7, architect is saved back to its v5 text and v8 is published. The test asserts v8's mapping equals v5's and `preview_rollback(5).blocked == "matches_active"`. `restore_release(5)` then returns `RollbackMatchesActive(active=Ref(v8), source=Ref(v5))` and writes nothing. |
| C19 | A non-`int` (including `bool` and `3.0`) gives `strict_type` with the message "version_number must be an integer.". An `int` ≤ 0 gives `out_of_range` with "version_number must be a positive integer.". Both messages are C19's text verbatim. The cases `0`, `-1`, `True`, `"3"` and `3.0` are parametrized, and each asserts its exact code. |
| C21 | `new_release_row = session.get(GraphRelease, published.release.release_id)`. A `None` raises `GraphConfigurationIntegrityError`. `_verify_rebased_draft(session, *, release_row, draft_row, effect, before, restored)`. |
| C26 | Rollback owns every refusal. The check order is: request shape (before any lock), L0, L1, snapshot, source, stale, `source_is_active`, `matches_active`, `incompatible`. Only then come L3 and the core. The core's `reused` post-check is kept. |
| C27 | `RestoredRelease(published: PublishedRelease, source, draft_effect)`. `PublicationConflict` is returned with keyword fields. Rollback never returns `NothingToPublish`. |
| C28 | `_historical_evidence(..., lock=True)` is Task 2's `FOR UPDATE OF agent_test_run` statement, in id order, with `populate_existing`. It is called after L1 and before the core links the runs. The link count that follows is a new statement. |
| C29 | The first statement of the fresh `session.begin()` is `_lock_current_parents(exclusive=True)`. The L1 lock is #269's `_lock_all_draft_agents`. No new `with_for_update` names `GraphRelease` and `GraphDraft` together, and the AST scanner is GREEN and unedited. The module still has no module-scope import of `graph_release_evidence`, `agent_test_workbench` or `agent_runtime`; the existing Task 2 hygiene test is GREEN. `GraphDraft` is imported under `TYPE_CHECKING` only. |
| C30 | Rollback runs no approval gate and no readiness check. |
| C31 | `_validate_rollback_request` builds the version issue first, then calls `self._validate_publication_request(actor, lock_version, release_note)`, catches its `PublicationRejected`, and appends that exception's issues. So there is one copy of #269's rules, and the order is `version_number, actor, lock_version, release_note`. Two combined cases prove the order. |
| C35 / Q7 | The rebase is PROCEED ON DEFAULT, three-way. Resets are applied after the core, through `_assign_locked_candidate` on the L1-locked rows, and then flushed. `_advance_locked_draft` is never called by rollback, so the core advances the lock exactly once. |
| C36 | `_GraphConfigurationDraft._assign_locked_candidate(row, content)` is a `@staticmethod` that holds exactly the column loop and `row.candidate_hash = definition_content_hash(content)`. `_write_locked_content` still computes `new_hash` before the call and passes it to `changed`. The draft save's behaviour is unchanged, and the draft, runtime and two PostgreSQL draft suites are all GREEN. |
| C48 | `test_a_verdict_change_on_a_linked_run_is_refused_after_rollback`: after the rollback, `record_verdict(R3, "rejected")` raises `IneligibleForApprovalError(reason="linked_to_release")`, and the artefacts are unchanged. |
| C15 / C42 | These are 3b's (injection stages). They are not in scope for 3a. |

## TDD

- **RED 1 (collection):** `ImportError: cannot import name 'RestoredRelease'`. The result types and facade exports were then added alone.
- **RED 2 (behavioural):** 31 failed / 25 passed.
  - 27 failed with `AttributeError: 'GraphConfiguration' object has no attribute 'restore_release'`.
  - 3 failed with `... no attribute '_verify_rebased_draft'`.
  - 1 was the structural pin: `_write_locked_content` did not yet call `_assign_locked_candidate`.
- **GREEN:** 1 failure remained after implementing, and it was a test-design error. The `builder_reset` case was a *self-consistent* wrong effect: builder marked `reset` and architect marked `kept`. That effect produces a draft that satisfies its own claims, so verification correctly cannot detect it. The effect itself is `_draft_effect`, which Task 2 pins. The case was replaced by `builder_unchanged` (a pending role claimed clean), which verification must catch.

## Tests added (32; `tests/unit/test_graph_release_rollback.py` now has 57)

Every fixture goes through `build_v2_to_v7`, which uses `offset_release_ids`, so ids are version + 10. It publishes v2–v7 through #269's real `publish_draft` with `_NoEvidenceGate`, under `install_release_clock` with `call_count == 6` pinned.

| Test | Covers |
|---|---|
| `test_restore_v3_while_v7_active_produces_v8_restoring_v3` | The plan's full list: version 8 (id 18), previous, `restored_from`, source; the mappings equal v3's; all `reused`; `changed == ("architect",)`; revision id set unchanged; v7 `effective_to == v8.effective_from`; v3 interval unchanged; versions 1..8 once each; draft base v8 with lock L+1; history `[0]` is v8 restoring v3, and v3 `restored_by == (Ref(v8),)`. Also: `published.evidence` and the stored v8 links are exactly `{(R3, historical_restore, v3.id)}`, and the run linked only to v5 is not carried. |
| `test_restore_resets_clean_roles_and_keeps_pending_edits` | Effect `{architect: reset, builder: kept, others: unchanged}` in key order. Architect is clean at v3's hash. Builder is `changed` with its exact prior hash and content. The other roles are untouched. The lock advances once. |
| `test_stale_lock_returns_conflict_and_writes_nothing` | The exact `PublicationConflict`. It also holds for version 7, so stale precedes `source_is_active`. The artefacts (including links and the runs' verdict columns) are identical. |
| `test_refusals_write_nothing[unknown, source_active, matches_active, incompatible, matches_first]` | `GraphVersionNotFound(99)`; `RollbackSourceActive(Ref(v7))`; the C18 fixture; `RollbackIncompatible` whose source is v3, whose `issues[0]` is Task 2's exact issue, and whose issues run in all-roles order. `matches_first` shows `matches_active` beats `incompatible`. Every case leaves the artefacts identical. |
| `test_request_issues_are_rejected_before_any_lock` (×12) | The C19 codes, the note cases (`""`, `"   "`, `None`, 2001 characters), actor `""`, and two combined-order cases. A spy on `_lock_current_parents` records zero calls. |
| `test_note_is_stored_verbatim` | `"  keep  "` is stored exactly, and a 2000-character note is accepted (as v9). |
| `test_rollback_calls_no_model_or_remote_validator` | `_MustNotRun` validator. `AgentRuntime.__init__`, `AgentTestWorkbench.__init__` and `CatalogRemoteEndpointDraftValidator.validate` each raise if called. |
| `test_rollback_lock_order_is_l0_then_l1_then_l3_before_any_write` | Addition. The ORM statements are compiled for PostgreSQL: [0] ends `FOR UPDATE OF graph_release, graph_draft`; [1] is `graph_draft_agent … ORDER BY agent_key FOR UPDATE`; exactly one L3 statement uses `populate_existing`; there are no other `FOR` clauses. At cursor level, L3 precedes the first write. |
| `test_a_materialized_revision_is_an_integrity_error_and_writes_nothing` | Addition, for the `reused` post-check. |
| `test_a_wrong_draft_effect_is_caught_by_the_rebase_verification[architect_unchanged, builder_unchanged]` | Addition: end-to-end rollback when `_verify_rebased_draft` fails. Both cases roll back fully. |
| `test_verify_rebased_draft_checks_each_effect[reset_not_clean, unchanged_moved, kept_moved, not_based]` | Addition: direct post-conditions, including the base-release guard. |
| `test_a_verdict_change_on_a_linked_run_is_refused_after_rollback` | C48. |
| `test_assign_locked_candidate_is_the_only_content_writer` | The structural pin: `inspect.getsource` shows the call and no `setattr` in `_write_locked_content`. Plus an AST scan of `src/`: the only function that assigns `.candidate_hash` is `_assign_locked_candidate`. |

## Gates

All runs use `PYTHONPATH=<W>:<W>/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/t270-3a.sqlite`, and the pyenv python.

| Gate | Result |
|---|---|
| Named unit gate (at `5e15d5cf2`): rollback, history, #269 publication/evidence/preview/routes/client-join, draft, workbench, `test_agent_definition_workbench_routes.py`, `test_agent_runtime.py`, the AST scanner `test_graph_parent_lock_is_single_sourced.py` | **970 passed** |
| Full `tests/unit` (at `d64ba5ce0`; run 06:09–06:15 UTC, no midnight crossing) | **6 failed / 7031 passed / 110 skipped**. The baseline was 7000 passed; the +31 are the new tests. The 6 failures are exactly the baseline nodes with the same causes: `'provisioned' == 'autoscaling'` and provisioned mock not called (×2); `'_FakeSession' object has no attribute 'execute'` (×3); `ConversationGraphReleaseIntegrityError: no active Graph Release` (×1). |
| PostgreSQL regression (at `d64ba5ce0`), `-rs`, zero skips | `test_graph_release_publication_postgres.py` 21; `test_graph_release_evidence_postgres.py` 18; `test_agent_definition_workbench_postgres.py` 49; `test_agent_schema_overlay_postgres.py` 10; `test_graph_release_history_postgres.py` 5. All passed. |
| `tellr_int_*` databases | The same 4 older ones before and after. None leaked. |
| ruff check (4 changed files) | clean. `ruff format --check` also fails on the base versions of these files, so formatting is not enforced and was not applied. |

**Refactor coverage.** The refactor `5e15d5cf2` changes only `_verify_rebased_draft` plus one test case. The named gate and the verify-related mutations were re-run on it. The full suite and the PostgreSQL files were not re-run, because none of them reaches `_verify_rebased_draft`.

## Mutation table

- **Driver:** `/tmp/t270-3a/mutate.py <SHA> [ids]`. Logs are in `/tmp/t270-3a/mut/`.
- **Per mutation, the driver:**
  1. asserts the file equals `git show <SHA>:<path>`;
  2. asserts the anchor occurs exactly once;
  3. applies the mutation with a `MUT-<id>` marker (count 1);
  4. runs the rollback unit file, plus `test_graph_configuration_draft.py` for draft mutations;
  5. restores the SHA's bytes, asserts `git diff --quiet <SHA> -- <path>`, and asserts the marker count is 0.
- **After the sweep:** `git status` is clean (tracked files).
- **SHAs:** the sweep ran at `d64ba5ce0`. R1, M19–M23, M26–M28, M31, M32 and the new M36 were re-run at `5e15d5cf2`; the results below are from the latest run of each.
- **Not run:**
  - the plan's controller sabotage (`restored_from_release_id=None`, plan line 766);
  - C16's 3b controller seam (`source_release_id=release_row.id`).

| ID | Clause | Mutation | Result: RED tests |
|---|---|---|---|
| **R1** | plan reviewer sabotage (line 767) | delete the `reset` loop (parent-only rebase) | RED 6, including the predicted `test_restore_resets_clean_roles_and_keeps_pending_edits`, with `GraphConfigurationIntegrityError: rebased draft role 'architect' does not match its effect 'reset'`, as predicted |
| M01 | `bool` is not an int | drop the `bool` test | RED `request_issues[True]` |
| M02 | `< 1` | `< 0` | RED `[0]`, combined |
| M03 | the `out_of_range` code (C19) | emit `strict_type` for ≤ 0 | RED `[0]`, `[-1]`, combined |
| M04 | #269's actor, lock and note rules are merged in | dropped | RED 7 (note/actor/combined) |
| M05 | the version issue comes first | appended after | RED 7 (every note/actor/combined case) |
| M06 | validation happens before any lock | moved under L0 | RED 12 (spy sees a lock call) |
| M07 | L0 is exclusive | `exclusive=False` | RED lock-order |
| M08 | L1 `_lock_all_draft_agents` | unlocked select | RED lock-order |
| M09 | L3 `lock=True` | `lock=False` | RED lock-order |
| M10 | the stale check | `if False` | RED stale |
| M11 | `source_is_active` | `if False` | RED `refusals[source_active]` (it gets `matches_active` instead) |
| M12 | `matches_active` return | `pass` | RED `refusals[matches_active, matches_first]` |
| M13 | matches means all seven are equal | `any` | RED 10 |
| M14 | `incompatible` raise | `if False` | RED `refusals[incompatible]` |
| M15 | `matches_active` precedes `incompatible` | structural check first | RED `refusals[matches_first]` |
| M18 | the `reused` post-check | `if False` | RED `materialized_revision` |
| M19 | only `reset` roles are written | `!= "unchanged"` (kept roles are reset too) | RED `resets_clean_roles_and_keeps_pending_edits` |
| M20 | reset to the *restored* content | reset to the active (v7) content | RED 6 |
| M21 | `_verify_rebased_draft` is called | skipped | RED `wrong_draft_effect[×2]` |
| M22 | `kept` keeps the prior hash | `holds = True` | RED `verify[kept_moved]` |
| M23 | `reset`/`unchanged` hold the restored content | `holds = True` | RED 4 |
| M36 | …the *restored* content, not the prior one | compare with `prior_hash` | RED 8 |
| M26 | the draft is based on the restored release | `if False` | RED `verify[not_based]` (the test was added in `5e15d5cf2`; this mutation survived at `d64ba5ce0`) |
| M27 | `session.get(...) is None` guard | `if False` | **survives, equivalent:** the core just flushed that row into the identity map, so `get` cannot return `None`. Kept because C21 step 2 mandates it. |
| M28 | explicit `session.flush()` before verification | removed | **survives, equivalent:** the snapshot's first `select` autoflushes (the default session config). Kept so correctness does not depend on autoflush. |
| M29 | evidence is passed to the core | `evidence=()` | RED happy path |
| M30 | historical contents are passed to the core | the draft's contents | RED 8 |
| M31 | the returned `draft_effect` | all `unchanged` | RED `resets_clean_roles…` |
| M32 | `unchanged` roles are verified clean | only `reset` is checked | RED 10 (`unchanged` falls to the `else` branch, which raises) |
| M33 | `_assign_locked_candidate` sets the hash | dropped | RED 130 (draft file + rollback) |
| M34 | `_write_locked_content` calls the extraction | `pass` | RED 120 |
| M35 | `_assign_locked_candidate` sets the columns | dropped | RED 132 |
| (M24, M25) | the old `changed is False` / restored-hash clauses | each dropped | Both survived at `d64ba5ce0`: they were equivalent to each other. `5e15d5cf2` removed the redundancy, leaving one clause (killed by M23 and M36). |

## Deviations

1. **`RollbackIncompatible(source, issues)` gets a real `__init__`.** It refuses an empty `issues`, stores `issues` as a tuple, and builds its message from the version number. The plan only declared the attributes. It follows the style of #269's `PublicationRejected`.
2. **`RollbackOutcome` is exported from the facade.** This is in addition to the plan's four names.
3. **`_verify_rebased_draft` checks one post-condition per effect, and adds a base-release check.**
   - `reset`/`unchanged`: the candidate hash equals the restored content's hash. This is equivalent to `changed is False` because the core reads back a mapping of exactly these revisions. It replaces the plan's wording, whose two clauses were mutually redundant (M24/M25).
   - `kept`: the exact prior hash.
   - Plus a check that `draft_row.base_release_id == release_row.id`.
   - The error message always starts "rebased draft …".
4. **The matches-active comparison uses `source.definitions[k].agent_definition_revision_id` against the locked snapshot's `published.revision_id`.** It does not use the plan's `active_ids` built from `snapshot.nodes`. The result is the same, and it goes through `_model_nodes`, which checks the key set.
5. **`_load_source` runs *before* the stale check**, per the plan template (check 3 before 4). So a stale request for an unknown version is `GraphVersionNotFound`, not a conflict. This is documented here; no test pins the unknown-plus-stale combination.
6. **Tests added beyond the brief:**
   - the lock-order statement test;
   - the `reused` post-check;
   - verification (end to end and direct);
   - C48;
   - `3.0` and combined-order request cases;
   - `matches_first`;
   - stale-beats-`source_active`;
   - an AST scan that `_assign_locked_candidate` is the only `candidate_hash` writer in `src/`.
7. **The brief's `test_refusals_write_nothing` request-issue cases are a separate test**, `test_request_issues_are_rejected_before_any_lock`, so the lock spy wraps only those cases.

## Interfaces for 3b and Task 6

**`src/services/graph_configuration_rollback.py`** (at `5e15d5cf2`):

| Line | Interface |
|---|---|
| :82 / :85 | `_VERSION_NOT_INT` / `_VERSION_OUT_OF_RANGE` (field `version_number`) |
| :138 | `RestoredRelease(published: PublishedRelease, source: ReleaseRef, draft_effect)` |
| :148 | `RollbackSourceActive(active)` → 409 `rollback_source_active` |
| :153 | `RollbackMatchesActive(active, source)` → 409 `rollback_matches_active` |
| :158 | `RollbackIncompatible(source, issues)`, a raised `ValueError` → 422 `rollback_incompatible` |
| :177 | `RollbackOutcome = RestoredRelease \| PublicationConflict \| RollbackSourceActive \| RollbackMatchesActive` |
| :311 | `restore_release(session, *, version_number, expected_lock_version, release_note, actor) -> RollbackOutcome`. It raises `PublicationRejected`, before any lock; the route maps an `actor` issue to 403 and every other issue to 422 `invalid_rollback` (C31). It also raises `GraphVersionNotFound`, `RollbackIncompatible` and `GraphConfigurationIntegrityError`. It requires a session with no open transaction. |
| :410 | `_validate_rollback_request(version_number, actor, lock_version, release_note)` |
| :434 | `_verify_rebased_draft(session, *, release_row, draft_row, effect, before, restored)` |
| :548 | `_historical_evidence(..., lock=True)`: the L3 matcher for Task 4 is `FROM AGENT_TEST_RUN JOIN GRAPH_RELEASE_TEST_RUN … FOR UPDATE OF AGENT_TEST_RUN` |

**Other files:**

| Location | Interface |
|---|---|
| `src/services/graph_configuration_draft.py:1013` | `_GraphConfigurationDraft._assign_locked_candidate(row, content)` |
| `src/services/graph_configuration_draft.py:1032` | the call from `_write_locked_content` |
| `src/services/graph_configuration.py` | exports `RestoredRelease`, `RollbackIncompatible`, `RollbackMatchesActive`, `RollbackOutcome`, `RollbackSourceActive` |

**Where the draft-agent write sits (for 3b's `draft_reset` stage).** The draft-agent `UPDATE GRAPH_DRAFT_AGENT SET` is flushed by the explicit `session.flush()` after the reset loop. That is after the core's `UPDATE GRAPH_DRAFT SET` (`draft_rebased`) and after `INSERT INTO GRAPH_RELEASE_TEST_RUN`. It fires only when some role is `reset`; restoring v3 over v7 resets architect.

**Test harness** (`tests/unit/test_graph_release_rollback.py`, for Task 6):

| Line | Helper |
|---|---|
| :869 | `build_v2_to_v7`, with `clock.call_count == 6` and ids = version + 10 |
| :886 | `restore(factory, version, *, lock, note, actor, service)` |
| :906 | `rollback_artifacts`: #269's `_artifacts` plus links and the runs' verdict columns |
| :940 | `link_v3_evidence`: R3 is linked to v3, and R5 to v5 only |
| :950 | `workbench_nodes` |
| :957 | `fresh_release` |
| :1096 | `_incompatible_bundles` |
| :1108 | `_publish_v8_matching_v5` (C18) |

## Concerns

1. **Q7 caveat (C20(a)/C35) still stands.** A kept edit that already has an approved run stays approved after the rollback. Nothing in 3a changes that; it is the disclosed default.
2. **M27 and M28 survive as equivalent** (see the table). Both guards are kept deliberately.
3. **Unknown version plus a stale lock.** A request with both returns `GraphVersionNotFound`, not a conflict, following the plan's check order (Deviation 5). Task 6's route order follows from this.
4. **An environment note, not a defect.** The first full-unit attempt appeared to stall at 32% on `tests/unit/test_dependencies_resolve.py::test_dependencies_resolve_on_proxy`, which makes a real network resolve. The verbose re-run showed it completes, only slowly. Anyone re-running the gate should expect that pause.
