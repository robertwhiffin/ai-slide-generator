# #270 Task 4 report: rollback forced orderings on PostgreSQL

**Status:** DONE. The change is test-only: `src/` has no diff against `0230e685c`, and I found no production defect.

- **TASK_BASE:** `0230e685c`. The controller's ledger commit `ad8950c9f` (`progress.md` only) sits on top of it and was left alone.
- **Files:**
  - `tests/integration/test_graph_release_rollback_ordering_postgres.py` (new)
  - `.github/workflows/test.yml` (+1 line in `integration-graph`)
  - `tests/unit/test_ci_collects_integration_tests.py` (+1 pin)

## Commits

| SHA | Message |
|---|---|
| `9d7a079b9` | test: force rollback orderings against publication, saves and verdicts (#270) |

## Harness

All helpers are imported by underscore name from #269's merged files (#269 C24). Nothing comes from `test_agent_definition_workbench_postgres.py`, and nothing comes from the Task 3b file that is under review.

**From `test_graph_release_evidence_postgres.py`:**
- `_setup`: sets the throwaway database's `lock_timeout` to `_WAIT_SECONDS`.
- `_Pids` and `_ObservedGraphConfiguration`: capture `pg_backend_pid()` before the L0 statement (C5).
- `_record_statement_pids`: captures the verdict writer's PID in `before_cursor_execute`.
- `_race`: bounded futures; the holder is released in an inner `finally`; asserts `_await_blocked_by(waiter_pid=, blocker_pid=)`; the `waiting_on` fragment check matches the waiter's `pg_stat_activity` query.
- Run and verdict helpers: `_run`, `_approve`, `_verdict_fn`, `_verdicts`.
- Link and cleanup helpers: `_links`, `_cleanup_fn`, `_insert_like`, `_full_row`, `_run_ids_of_case`, `_seed_case_id`, `_lock`, `_publish`.

**From `test_graph_release_publication_postgres.py`:**
- `_save_prompt`
- `_publish_as` (with `_NoEvidenceGate`)
- `_release_set`
- `_install_commit_failure` / `_drop_commit_failure`

**Seed.** Releases v1 to v4 change architect each time. Each is approved by its own run R&lt;v&gt; through #267's `execute_candidate_run` and #268's `record_verdict`, and published through the real `ApprovalEvidenceGate`. Before v2, one publication is rolled back at commit, which burns id 2. The (id, version) pairs are therefore (1,1), (3,2), (4,3), (5,4), and the next release is (6,5). Every assertion uses those literal pairs, and nothing resolves a version by id.

**Matchers:**
- **C6:** the pause is keyed on the both-parents L0 in any lock mode (`FROM GRAPH_RELEASE`, `GRAPH_DRAFT`, not `GRAPH_DRAFT_AGENT`, plus a `FOR …` row-lock clause). A `_Recorder` keeps the statement the pause fired on. Each test asserts `_await_blocked_by` first (inside `_race`), then that the recorded text contains `FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT`, or `FOR SHARE …` where the blocker is cleanup.
- **C28:** the verdict test pauses on the first `FROM AGENT_TEST_RUN JOIN GRAPH_RELEASE_TEST_RUN` statement, in any mode, then asserts that the statement contains `FOR UPDATE OF AGENT_TEST_RUN`. A shared-mode or unlocked L3 therefore still pauses, and goes RED at `_await_blocked_by`, which is C28's predicted point.
- **L0 scan count:** a separate `after_cursor_execute` counter records L0 statements per thread. It proves the handoff rescan: the waiter is scanned twice.

## Tests (12, all passed, 0 skips, about 10 s)

1. **`test_rollback_first_then_publication_is_stale`**
   - The publisher is blocked by the rollback PID.
   - The rollback returns (6,5), restored from 3, with effect `{architect: reset, builder: kept, others: unchanged}`. A pending builder edit gives the publisher something to publish.
   - The publisher returns exactly `PublicationConflict(L, L+1, 6, 5, draft)`.
   - The scan counts are rollback 1 and publisher 2.
   - The release set is (1..5) with only v5 active; v5's mapping equals v2's; the builder edit is kept.
2. **`test_publication_first_then_rollback_is_stale_and_not_v6`**
   - The rollback is blocked by the publisher.
   - The publisher returns (6,5) with `restored_from None`.
   - The rollback returns exactly the conflict naming (6,5), after 2 L0 scans.
   - There is no v6, only builder differs between v5 and v4, and no link is added.
3. **`test_two_rollbacks_one_winner_one_exact_stale_conflict[alpha|beta]`**
   - The winner produces (6,5) with the winner's actor and note.
   - The loser returns exactly the conflict after 2 scans.
   - Exactly five releases exist, and exactly one `historical_restore` link (6, R2, 3) was added.
4. **`test_sequential_rollback_retry_is_stale`** (Review Focus 3): the retry with the same lock gets the exact conflict naming v5; there is no v6 and no new link.
5. **`test_draft_save_first_then_rollback_is_stale`**
   - The rollback is blocked by the saver.
   - The rollback returns the conflict `(L, L+1, 5, 4)`, and no release or link is written.
   - The draft's builder is exactly the saver's hash, and architect is still v4's.
6. **`test_rollback_first_then_draft_save_is_stale_not_500`**
   - The saver is blocked by the rollback.
   - The saver gets `DraftSaveConflict` (no exception of any kind, so no `GraphConfigurationIntegrityError`) with `server.draft` = base (6, v5) and lock L+1.
   - The reset role (architect) carries v2's hash.
   - Every draft hash equals v5's mapped hash.
7. **`test_workbench_read_during_rollback_sees_coherent_new_release`**
   - The reader (`FOR SHARE`) is blocked by the rollback.
   - It sees active (6,5), with draft base 6 and lock L+1.
   - The reset role is architect only; it has `changed is False` and v2's hash, and every node is `changed False`.
8. **`test_verdict_change_on_source_linked_run_waits_then_is_refused[change_refused|identical_noop]`** (C28, C41, C48)
   - `record_verdict(R2)` is blocked by the rollback's L3.
   - The writer holds the `AccessExclusiveLock` tuple lock of a `FOR UPDATE` wait.
   - The rollback returns (6,5) with evidence `[(R2, historical_restore, 3)]`.
   - For `rejected`: exactly `IneligibleForApprovalError`, with `(run_id, reason) == (R2, "linked_to_release")`.
   - For an identical `approved` re-submit: it waits, then returns `TestRunEvidence(R2, approved)` as a no-op.
   - In both cases R2's four verdict columns are unchanged, and R2's links are exactly `[(3, R2, approval, NULL), (6, R2, historical_restore, 3)]`.
9. **`test_rollback_and_cleanup_serialize_with_exact_deletions[cleanup|rollback]`** (C9, C45)
   - The seed adds 22 unreviewed, stale-hash copies of R4 after it.
   - **Cleanup first:** cleanup is paused on `FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT`, and the rollback waits on `FOR UPDATE …`.
   - **Rollback first:** the reverse.
   - In both orders, cleanup returns 2, the case's runs are exactly `[R2, R3, R4, copies[2:]]`, the rollback links R2 only, and there are five releases.

## Gates

Every run used `PYTHONPATH=<W>:<W>/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/t270-4.sqlite`, `TELLR_TEST_POSTGRES_URL=…/postgres` and the pyenv python, with one PostgreSQL file per invocation and `-rs`.

| Gate | Result |
|---|---|
| New ordering file | 12 passed, 0 skips |
| `test_graph_release_rollback_postgres.py` | 12 passed |
| `test_graph_release_history_postgres.py` | 5 passed |
| `test_graph_release_publication_postgres.py` | 21 passed |
| `test_graph_release_evidence_postgres.py` | 18 passed |
| `test_graph_release_session_ordering_postgres.py` | 29 passed |
| `test_agent_definition_workbench_postgres.py` | 49 passed |
| CI collection test | 21 passed. It was RED first (the new pin failed before the `test.yml` line existed). |
| Full `tests/unit` (07:30–07:38 UTC, no midnight crossing) | 6 failed / 7034 passed / 110 skipped. The failures are the baseline six with the baseline causes: `'provisioned' == 'autoscaling'` and the provisioned mock not called (×2); `_FakeSession` has no `execute` (×3); `no active Graph Release` (×1). The +1 pass is the new pin. |
| ruff check | New file clean. The new file is `ruff format`ted. The CI test file's `I001` is pre-existing. |

## TDD

- **RED:** the CI pin failed first, because the file was not yet in `test.yml`.
- **Behaviour:** every ordering test passed on its first run against the existing production code, which is what the plan expects ("no production code unless a real ordering defect appears"). The mutation sweep below is what shows the tests can fail.

## Mutation table

- **Driver:** `/tmp/t270-4/mutate.py 0230e685c <ids>`. Logs are in `/tmp/t270-4/mut/`.
- **For each mutation, the driver:**
  1. asserts each touched file equals `git show SHA:path`;
  2. asserts each anchor occurs exactly once;
  3. asserts the `MUT-<id>` marker count equals the number of edits;
  4. runs the whole new file;
  5. restores with `git checkout SHA -- path`, then asserts `git diff --quiet SHA -- src` and a marker count of 0.
- **Afterwards:** `src` is clean against `0230e685c`, and a grep for `MUT-M` finds nothing.

| ID | Seam | Mutation | RED (observed cause) |
|---|---|---|---|
| M01 | rollback L0 mode (this is the plan's controller target; I ran it as my own too, and the controller may still run its own) | `exclusive=False` | **9/12.** Mode assertion, where the rollback is the blocker: rollback-first vs publisher and vs saver. Waiter paused on `FOR SHARE`, not `FOR UPDATE` (`waiting_on`): publication-first and save-first. `reader was never blocked` and `cleanup was never blocked` (rollback-first). **Two rollbacks [alpha, beta]:** the loser's `FOR SHARE` L0 is *granted*, and the loser then waits on `UPDATE GRAPH_RELEASE SET EFFECTIVE_TO` behind the winner's share lock. `_await_blocked_by` is therefore **True**, and the RED comes from the `waiting_on` L0-UPDATE fragment check. That is a different point from C6's prediction ("`_await_blocked_by` False"). After release this pair would deadlock. Cleanup-first REDs the same way. |
| M02 | stale check (plan reviewer target) | `if False and expected_lock_version != …` | **5/12.** Publication-first observes `RestoredRelease` (7, **6**), which is v6 as predicted. Two rollbacks ×2 and the sequential retry get `RollbackMatchesActive(active (6,5), source (3,2))`. Save-first observes `RestoredRelease` (6,5), restoring over the saver's edit. |
| M03 | rollback L3 lock (C28 reviewer addition) | `_historical_evidence(lock=False)` | 2/12: both verdict cases, with `verdict was never blocked by rollback`. |
| M04 | L3 taken after the link | `lock=False` in place, plus a locking re-read after `_commit_locked_publication` | 2/12: both verdict cases, never blocked (the pause fires on the unlocked read). |
| M05 | #268/#269 C48 re-check in `record_verdict` | `if False and session.scalar(exists link)` | 1/12: `change_refused`; the writer reaches the `trg_agent_test_run_linked_verdict_immutable` backstop (`IntegrityError`), not the typed refusal. `identical_noop` stays GREEN, which is correct. |
| M06 | #268 verdict L3 | drop `.with_for_update()` from `_verdict_lock_statement` | 2/12: both verdict cases, never blocked. |
| M07 | handoff rescan | `_MAX_PARENT_LOCK_SCANS = 1` | 7/12: every waiter queued behind a committed release change raises `parent snapshot is inconsistent` (rollback-first vs publisher, saver, reader, cleanup; publication-first; two rollbacks ×2). The tests where only the draft moved (save-first) or where no release is created stay GREEN, which is correct. |

M05's first attempt used a wrong anchor (`session.scalar(False)` raised `ArgumentError` in the seed, 12/12 RED for a harness reason). It was re-anchored on the `if`, and the result above is from the corrected run.

## Production defects

None.

## Deviations

1. **The verdict test is parametrized** into `change_refused` and `identical_noop` (C41's "identical re-submit"). The two runs are separate: C41 asks for the re-submit "during the same pause", but #269's `_race` takes one waiter, and the parametrized form proves the same wait and outcome for each writer.
2. **The rollback-vs-cleanup test is included**, as the dispatch listed it. Plan/C45 place the cleanup scenario in Task 5; Task 5 can drop or reuse it.
3. **The plan's `IntegrityError 23514` outcome is replaced** by C41's `IneligibleForApprovalError("linked_to_release")`. The `IntegrityError` path is what M05 exposes.
4. **Publication tests add a pending builder edit** so the publisher has something to publish. As a result the rollback-first case also covers a `kept` effect.
5. **The seed is local to this file** (about 20 lines, built from #269 helpers) rather than imported from Task 3b's file, which is under review.

## Concerns

1. **M01's two-rollbacks RED point differs from C6's prediction.** It REDs at the `waiting_on` statement check, not at `_await_blocked_by`, because the loser's shared L0 is granted and it blocks later on the UPDATE. It is still RED at a named assertion before any deadlock. The ledger's prediction should be amended.
2. **Mutations that leave the waiter unblocked cost about 30 s** (`_WAIT_SECONDS`) per test before going RED. The GREEN run takes about 10 s.
3. **A fifth throwaway database, `tellr_int_f7551cc43d7846bc`, is not provably mine, so I did not drop it.**
   - It was created at 07:08:04 UTC.
   - It already appeared in the listing I took *before* my first PostgreSQL invocation.
   - It holds only the v1 bootstrap row, with none of my seed's releases or notes.
   - It has no active connections.
   - It is probably the concurrent Task 3b reviewer's. The four older `tellr_int_*` databases are unchanged.
4. **The literal ids assume sequence cache 1 on a fresh database per test**, as in Task 3b.
