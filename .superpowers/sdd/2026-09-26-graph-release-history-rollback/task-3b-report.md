# #270 Task 3b report: restoring a historical release, on PostgreSQL

**Status:** DONE. Test-only. No production defect found, and `src/` is untouched.

- **TASK_BASE:** `51a9f6120`. The controller's ledger commit `e6864276f` (`progress.md` only) sits on top of it and was left alone.
- **Scope (C16 3b):** `tests/integration/test_graph_release_rollback_postgres.py`, the `integration-graph` enrolment in `.github/workflows/test.yml`, and a CI pin in `tests/unit/test_ci_collects_integration_tests.py`.

## Commits

| SHA | Message | Files |
|---|---|---|
| `8f9c1eca1` | test: restore a historical graph release on PostgreSQL (#270) | the new PG file (+~570), `test.yml` (+1), CI pin test (+17) |

## Harness

**Real writers only (C45).** Releases v2 to v7 go through #269's real `publish_draft` with the real `ApprovalEvidenceGate`, using the production readiness callable `AgentTestWorkbench().readiness_under_parent_lock`. Each architect change is approved by its own run `R<v>`, which comes from #267's `execute_candidate_run` with `DeterministicFakeModelAdapter` and is approved through #268's `record_verdict`. Nothing is seeded through the ORM. The real clock is used throughout.

**ids differ from versions.** Before v2, one publication is rolled back by #269's deferred commit trigger, which burns `graph_release.id` 2. The releases are therefore (1,1), (3,2), (4,3) … (8,7). Every assertion names the exact literal (id, version) pair: v3 is id 4, v7 is id 8, v8 is id 9, or id 10 after a stage that burned an id.

**Helpers are imported by underscore name, never copied:**
- from #269's `test_graph_release_publication_postgres.py`: `_STAGE_MATCHERS`, `_install_commit_failure`/`_drop_commit_failure`, `_fresh_active_pin`, `_mappings`, `_normalized`, `_release`, `_run_named`, `_save_prompt`;
- from #269's `test_graph_release_evidence_postgres.py`: `_setup` (bounds the database's `lock_timeout` to `_WAIT_SECONDS`), `_run`, `_approve`, `_publish`, `_lock`, `_links`, `_everything`, `_seed_case_id`;
- from `test_conversation_pin_acceptance_postgres.py`: `_database_context`, for the managed-session patches.

Nothing is imported from `test_agent_definition_workbench_postgres.py`. `_await_blocked_by` is not needed: this file has no ordering test, since those are Task 4's. Every call still runs on a bounded future (`_run_named`), and every lock wait is bounded.

## Tests (12, all on PostgreSQL, zero skips)

**`test_v8_restores_v3_with_exact_intervals_mappings_and_evidence`** (the headline test). It adds a pending builder edit, so the draft rebase has all three effects. It asserts:
- the source is `Ref(4,3)` and the new release is (9, 8), with `previous` 8 and `restored_from_release_id` 4, and the note and actor stored;
- the mappings equal v3's, every mapping has `reused`, and `changed == ("architect",)`;
- `published.evidence == (EvidenceLink(R3, architect, case, "historical_restore", 4),)`;
- the draft effect is `{architect: reset, builder: kept, others: unchanged}`;
- the pairs are exactly `[..., (9,8)]`, and the revision id list is unchanged;
- the aware datetimes satisfy `v7.effective_to == v8.effective_from == v8.published_at == draft.updated_at`, v3's interval is unchanged, and the fresh active pin is 9;
- the link list is exactly the before-list plus `(9, R3, 'historical_restore', 4)`, and v3's `(4, R3, 'approval', NULL)` link is still present;
- every `agent_test_run` row, in every column, is identical before and after, and no run was added;
- the draft is `(base 9, lock L+1, oncall)`; architect's hash equals v3's architect revision hash; builder's hash and prompt are unchanged; the others are untouched; and `read_workbench` shows `changed` only for builder;
- in the history, v8 comes first with `restored_from == Ref(4,3)`, and v3 has `restored_by == (Ref(9,8),)`.

**`test_injected_failure_rolls_back_every_row[×6]`** covers the six C42 stages: `interval_closed`, `mappings_read_back`, `evidence_linked`, `draft_rebased`, `draft_reset` and `commit`.
- **How it injects:** #269 C8's listener, filtered to the `rollback` thread. The deferred trigger is used for `commit`.
- **Arming:** every stage except `interval_closed` is armed only after `UPDATE GRAPH_RELEASE SET EFFECTIVE_TO` has run. This stops a pre-write read that happens to match a stage (for example a `GRAPH_RELEASE_AGENT.AGENT_KEY` read in `_load_source`) from firing the injection before any write.
- **Assertions for each stage:**
  - the exact injected error is raised, and it fired exactly once;
  - `_everything` (revisions, releases with intervals, mappings, draft, draft agents, links, verdicts and cases) equals the before-state, and so do all run rows;
  - the `historical_restore` link count is 0, which covers C15's parts 1 and 2;
  - a fresh `lock_active_graph_release` returns (8, v7).
- **Retry:** an un-injected retry with the same lock returns version 8. Its id is 9 for `interval_closed` and 10 for every stage after the INSERT, which proves those failures really happened after the INSERT. Its links are exactly `{(id, R3, 'historical_restore', 4)}` (C15 part 3).

**`test_restore_a_restoration_links_its_links_with_the_selected_source`** (Review Focus 1):
- v8 restores v3, then v9 is published with architect `+9` and approval R9;
- restoring v8 gives (11, 10) with `restored_from` 9 and v8's mapping;
- the new links are exactly `{(11, R3, 'historical_restore', 9)}`;
- in the history, v10 has `restored_from Ref(9,8)`, v8 has `restored_by (Ref(11,10),)`, and v3 has `restored_by (Ref(9,8),)`.

**`test_restore_v1_links_no_evidence`** (Review Focus 2): the result is (9, 8), restored from 1, with evidence `()` and zero link rows for id 9. The mapping equals v1's, every mapping is reused, and no revision was added.

**`test_pinned_historical_releases_remain_readable_and_executable`:**
- `SessionManager().create_session("pinned-v7")` pins id 8, using the managed-session patches.
- After the restore:
  - the pin is still 8;
  - `get_conversation_graph_version` returns `(7, 8, True)`;
  - a new `pinned-v8` conversation pins 9 at version 8.
- `AgentRuntime(PersistedGraphReleaseLoader, DeterministicFakeModelAdapter, RecordingAgentInvocationIdentitySink)` runs architect with the seeded smoke case's payload and `AgentAssemblyContext(design_system_active=…)` (C25's constructor) against closed v7 (8), closed v3 (4) and active v8 (9).
- The sink's `successes` carry `(release_id, graph_version, architect revision)` = `[(8,7,…),(4,3,…),(9,8,…)]`. v8's revision equals v3's and differs from v7's. There are no error classes.

**`test_historical_restore_evidence_never_satisfies_readiness[new_edit_after_rollback, kept_edit_from_before]`** (Review Focus 4, C30). The docstring states that the refusal comes from the hash key, not from a link filter.
- v3 also changes builder (run B3). v8 links both R3 and B3 as `historical_restore` from 4, and the test asserts this.
- **New-edit variant:** architect is changed to H after the rollback. The builder effect is `unchanged`, `draft_readiness` blocks `("architect",)`, and `publish_draft` with the real gate returns exactly `PublicationNotReady(locked_gaps=(PublicationGap("architect", case, "no_eligible_approval"),))`.
- **Kept-edit variant:** a builder edit is made before the rollback. The builder effect is `kept`, readiness blocks `("builder",)`, and the gap is builder's.
- Both variants write nothing (`_everything` equals the before-state), and the active release stays (9, 8).

## Gates

Every run used `PYTHONPATH=<W>:<W>/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/t270-3b.sqlite`, `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres` and the pyenv python, with one PostgreSQL file per invocation and `-rs`.

| Gate | Result |
|---|---|
| `test_graph_release_rollback_postgres.py` (new) | **12 passed**, 0 skips (about 11 s) |
| `test_graph_release_history_postgres.py` | 5 passed, 0 skips |
| `test_graph_release_publication_postgres.py` | 21 passed, 0 skips |
| `test_graph_release_evidence_postgres.py` | 18 passed, 0 skips |
| `tests/unit/test_ci_collects_integration_tests.py` | 20 passed. Sabotage: deleting the `test.yml` line makes the new pin (and one other existing guard) RED; the line was then restored. |
| Full `tests/unit` (06:47–06:54 UTC, no midnight crossing) | **6 failed / 7033 passed / 110 skipped**. The 6 failures are the baseline nodes with the baseline causes: `'provisioned' == 'autoscaling'` and provisioned mock not called (×2); `'_FakeSession' object has no attribute 'execute'` (×3); `ConversationGraphReleaseIntegrityError: no active Graph Release` (×1). There are 2 more passes than Task 3a's d64ba5ce0 run: 3a's refactor case and the new CI pin. |
| ruff check | The new file is clean. The new file is `ruff format`ted, because it is new; the format was applied before the commit and the gates were re-run. The CI test file's `I001` is pre-existing (it is present at base) and was not touched. |
| `tellr_int_*` | The same 4 older databases before and after. None leaked. |

## Mutation table

- **Driver:** `/tmp/t270-3b/mutate.py <SHA> [ids]`. Logs are in `/tmp/t270-3b/mut/`.
- **For each mutation, the driver:**
  1. asserts every touched file equals `git show <SHA>:<path>`;
  2. asserts each anchor occurs exactly once;
  3. asserts the `MUT-<id>` marker count equals the number of edits;
  4. runs the whole new PG file;
  5. restores the SHA's bytes, asserts `git diff --quiet <SHA>`, and asserts the marker is gone.
- **Runs:** the sweep ran first at `51a9f6120` and again at the committed `8f9c1eca1`, with identical counts. `git status` (tracked files) was clean afterwards.
- **Not run:** C16's controller seam (`source_release_id=release_row.id`).

| ID | Seam (file) | Mutation | RED |
|---|---|---|---|
| M01 | rollback, core call | `restored_from_release_id=None` (the plan's 3a controller target; not C16's) | 3: the headline test, restoration-of-restoration, v1 |
| M02 | rollback, core call | `evidence=()` | 10: the headline test; all 6 stages (the retry link set; `evidence_linked` gives DID NOT RAISE); restoration-of-restoration; both readiness variants. v1 and pinned stay GREEN, correctly. |
| M03 | rollback `_historical_evidence` | the link becomes `"approval", None` | 10 (the same set as M02) |
| M04 | rollback reset loop | `if False` (a parent-only rebase; the plan's reviewer target) | 12, every test (`rebased draft role 'architect' does not match its effect 'reset'`) |
| M05 | rollback reset loop | reset every role that is not `unchanged` (kept edits are reset too) | 2: the headline test, readiness `kept_edit` |
| M06 | rollback `_source_from_history` | resolve by `release_id` instead of `version_number` | 11. Only `restore_v1` survives, because id 1 equals version 1 there. This is the ids-differ-from-versions proof. |
| M07 | rollback, atomicity | a raw `COMMIT` on the connection after the core, before the reset | 1: `[draft_reset]`, where the committed release survives the failure. `[commit]` stays GREEN correctly, because the deferred trigger fires at that raw COMMIT and rolls everything back. |
| M08 | #268 `_current_candidate_evidence_clause` plus the #269 gate L3 | drop the candidate-hash term | 2: both readiness variants (the readiness assertion) |
| M08b | #269 gate only (L3 hash plus re-verify eligibility) | the gate accepts any approved run of the case | 2: both readiness variants, at the `publish_draft` assertion (it returns `PublishedRelease` v9). This proves the gate half of the negative proof on its own. |
| M09 | rollback `_draft_effect` | never `kept` | 2: the headline test, readiness `kept_edit` |
| M10 | draft `_advance_locked_draft` | `lock_version += 2` | 1: the headline test (`lock L+1`) |

**Assertions without a dedicated production seam:**
- **Pin immutability and the history lineage.** Pins are immutability properties: no #270 code touches `user_sessions`. The history lineage (`restored_by`) is Task 1's seam and is mutated there. M01 and M06 do reach the history assertions.

## Production defects

None found.

## Deviations

1. **Six injection stages, not five (C42).** Stages other than `interval_closed` are armed only after the interval close, so that a read sharing a matcher cannot fire before any write. This is an addition to #269's recipe.
2. **The headline test adds a pending builder edit.** This lets the "draft rebased per the Q7 default" check cover `reset`, `kept` and `unchanged` in one test.
3. **The readiness test is parametrized into its two variants** (a new edit, and a kept edit), rather than saving both edits in one test. As a result, each `locked_gaps` is a single, exact gap.
4. **No ordering test, so no use of `_await_blocked_by`.** Ordering is Task 4's scope. Lock waits are still bounded through #269's `_setup`, which sets the database's `lock_timeout`, and every call runs on a bounded future.
5. **The CI pin was added to `test_ci_collects_integration_tests.py`.** The plan omits this, and the self-consistency table adds it.

## Concerns

1. **M07 is a proxy for atomicity.** It shows that the stage tests detect an early commit only at `draft_reset`, the one write after the core. The earlier stages fail before that point, so an early commit at any other seam would need a mutation inside #269's core. #269's own suite already covers that.
2. **The id arithmetic relies on sequence behaviour.** The literal ids (9 and 10) assume `graph_release_id_seq` uses the default cache of 1 on a fresh per-test database. This holds for `postgres_engine`, which creates a new database for each test.
