# Task 3 report: session creation versus real publication

**Status:** DONE_WITH_CONCERNS (minor ones; see below)
**TASK_BASE:** `8a31338c6`. **Branch:** `plan/publish-release-269`.

## Commits
- `fd0d3ce76` test: prove session creation linearizes with real publication (#269)
  - creates `tests/integration/test_graph_release_session_ordering_postgres.py` (29 tests)
  - enrols it in `.github/workflows/test.yml` `integration-graph`, right after the Task 1/2 publication file
  - pins it in `tests/unit/test_ci_collects_integration_tests.py` (`test_graph_release_session_ordering_is_collected_by_integration_graph`)
- No production code changed: `git diff 8a31338c6 HEAD -- src` is empty.

## Tests (29)
| Test | Params | What it proves |
|---|---|---|
| `test_publication_first_each_creator_pins_exact_new_release` | 7 `CREATORS` | The publisher pauses after its first `FOR UPDATE` statement (C6: no table filter). Then the creator is observed blocked by the publisher's PID. Then the recorded statement has `GRAPH_RELEASE` and `GRAPH_DRAFT`. Scans are `[1, 1]`. The pin equals `PublishedRelease.release.release_id`, at version 2, `previous_release_id == v1`. The release rows are exactly `[(v1,1,closed),(v2,2,active)]`. The contributor/duplicate source still pins v1, with the parent/copy shape checked. |
| `test_creation_first_publisher_waits_and_creator_keeps_v1` | 7 | The creator pauses after `INSERT INTO user_sessions`. The publisher is observed blocked by the creator's PID. Its `pg_stat_activity.query` ends with `FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT` (C6 strengthening). The creator pins v1. The publisher returns v2 with `previous_release_id == v1`. `v1.effective_to == v2.effective_from`. `get_conversation_graph_version` == `(1, 2, True)`. |
| `test_creator_behind_fully_flushed_publication_never_sees_partial_release` | 7 × {rollback, commit} (C8-3) | The publisher pauses after `UPDATE GRAPH_DRAFT SET`, with every write flushed. The creator is observed blocked. **rollback:** the publisher raises the injected `RuntimeError` (identity-checked); the creator scans `[1]` and pins v1; v1 is the only release and is active. **commit:** the creator scans `[1, 1]` and pins v2. |
| `test_new_conversation_after_publication_pins_new_and_old_retains` | — | Sequential: root before publication, publish, root after. Pins are exactly `(v1.id, v2.id)`, and a fresh lock returns v2. |

Harness notes:
- **Creator PID (C5):** the `before_cursor_execute` recipe on `FROM graph_release … FOR UPDATE`, which is also the scan counter. In creation-first, the PID also comes from the INSERT pause (the `:309` recipe).
- **Lock bounds:** every statement on the `creator` and `publisher` threads is preceded by `SET LOCAL lock_timeout = '30s'`, issued on a raw DBAPI cursor.
- **Wait bounds:** every event wait and future is bounded. Both pauses are released in an inner `finally` before the executor joins.
- **Reuse:** `_await_blocked_by` is reused from the helpers, not copied. Only underscore names are imported, plus `CREATORS`: `_NoEvidenceGate` and `_save_prompt` from the Task 1 PG module (C24), and `_create`, `_creator_patches` and `_backend_pid` from the mixed-creation module. No test is re-collected (the file collects 29).

## RED
- The CI pin test went RED first: 1 failed / 15 passed. The cause was that the target was not in the `integration-graph` run block. It went GREEN after enrolment.
- The PG tests passed on their first run, as expected: this is a test-only task over already-correct ordering, and no ordering defect appeared. So their RED evidence is the mutation table below.

## Gates (all GREEN; PG run one invocation per file, `-rs`, zero skips)
| Gate | Result |
|---|---|
| `test_graph_release_session_ordering_postgres.py` | 29 passed |
| `test_graph_release_publication_postgres.py` | 21 passed |
| `test_mixed_release_creation_postgres.py` | 14 passed |
| `test_conversation_pin_creation_postgres.py` | 2 passed |
| `test_conversation_pin_acceptance_postgres.py` | 1 passed |
| `tests/unit/test_ci_collects_integration_tests.py` | 16 passed |
| Full unit | 10 failed / 6819 / 110. Six are the baseline nodes and causes (`TestGetOrCreateLakebase` ×2, `TestModelDumpIsNotTheChokepoint` ×3, `test_session_manager_create_session`). The other four are `tests/unit/test_usage_service.py` (TestDaily ×2, TestVisitCollapse ×1, TestWindowModes ×1); see Concerns. That file re-run alone: 20 passed. |
| ruff | The new file is clean. `test_ci_collects_integration_tests.py` has only the pre-existing I001 (verified identical at `8a31338c6`). |
| DB hygiene | `tellr_int_*` list is unchanged: the 4 older DBs only. Nothing leaked. |

## Mutation table (all restored from explicit SHA `fd0d3ce76`)
Each mutation followed the same discipline: anchor count 1, `grep -c` marker, RED run, `git checkout fd0d3ce76 -- <file>`, marker 0, `git diff --exit-code` clean. The final `git diff --exit-code fd0d3ce76 -- src` is clean, `grep -r SABOTAGE269 src tests` finds nothing, and the gates above are the post-restore GREEN.

| # | Mutation | Marker | Predicted | Observed |
|---|---|---|---|---|
| R1 (plan reviewer) | `MAX_ACTIVE_RELEASE_LOCK_SCANS = 1` (`conversation_pins.py:55`) | `SABOTAGE269_3_SCANS` | publication-first RED for every creator | **RED 14/29**: publication-first ×7 plus partial-`commit` ×7, all `ActiveGraphReleaseUnavailableError: no active Graph Release` at `conversation_pins.py:74`. Creation-first, rollback and sequential stay GREEN (correct: no handoff). |
| O1 | `publish_draft`'s `with session.begin()` replaced by begin/`finally: commit` | `SABOTAGE269_3_COMMIT` (3 lines) | partial-`rollback` ×7 RED | **RED 7/29** at `publisher_error is injected`: the error was `PendingRollbackError`. The flush-failed session refuses to commit, so nothing was committed. This is the same effect as Task 1's C8 M04 note. The mutation is weaker than intended, so O2 was added. |
| O2 | raw `COMMIT` right after the v2 INSERT flush in `_commit_locked_publication` (writes visible before publication finishes) | `SABOTAGE269_3_EARLY` | partial ×14 RED at the blocked assertion | **RED 14/29**: "`<creator>` was never blocked by the flushed publication", both outcomes, every creator. It took 440 s (each waits the bounded 30 s) and no hang. |
| O3 | creator lock `order_by(id).limit(1)` instead of `effective_to IS NULL` | `SABOTAGE269_3_FIRST` | publication-first ×7, partial-commit ×7, sequential RED | **RED 15/29**: `[1] == [1, 1]` ×14, and sequential `(1, 1) == (1, 2)`. |
| O4 | `publish_draft` L0 `exclusive=False` (FOR SHARE) | `SABOTAGE269_3_SHARE` | publication-first at the table assertion; creation-first at the `pg_stat_activity` assertion | **RED 14/29** as predicted: the first `FOR UPDATE` is the L1 `graph_draft_agent` lock, so `'GRAPH_RELEASE' in …` fails ×7, and `waiting_query(...).endswith(FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT)` fails ×7. |
| C6 (controller) | not run, as instructed; left for the controller | — | — | — |

## Deviations
1. **Publisher PID capture.** The publisher's PID is taken from `before_cursor_execute` on its first statement (`_backend_pid(conn)`), not from a `_lock_current_parents` override. Under C6's controller sabotage, `publish_draft` no longer calls `_lock_current_parents`, so an override would never record a PID. The test would then fail at a harness assertion instead of at `_await_blocked_by`. It is the same backend PID, and it is recorded before any blocking statement, as C5 requires.
2. **Creation-first: the publisher's pause only records.** The first-`FOR UPDATE` pause is armed but pre-released (`publisher_holds=False`). The order is still "creator released, then publisher completes". The reason: if the pause blocked, then under C6's sabotage the publisher would stop in Python after its draft-only lock and never wait on the release. The test would go RED at `_await_blocked_by` rather than at C6's predicted `pg_stat_activity` assertion. With the pause only recording, the publisher runs on, blocks at `UPDATE graph_release`, and fails at C6's secondary point as predicted. The recorded statement is still asserted afterwards to end with `FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT`.
3. **Stronger assertions than the brief.** The creation-first `pg_stat_activity` check uses `endswith(...)` on the normalized query, which is stricter than "contains". The rollback case also asserts scans `[1]`.
4. **The sequential test is not parametrized.** `_create` uses fixed per-creator session IDs, so one creator cannot create twice. Both roots come from `SessionManager.create_session(graph_capable=True)`.
5. **The CI pin went into `tests/unit/test_ci_collects_integration_tests.py`,** as the controller instructed. The brief's commit command named only the PG file and `test.yml`.
6. **The seed helper is re-implemented locally,** because `_seed` in the mixed-creation file inserts its own release, and bootstrap owns v1 here. The contributor/duplicate source rows are copied exactly from `:71–105`.

## Concerns
1. **Four transient `test_usage_service.py` failures in the full unit run.** Probable cause: the run crossed UTC midnight (00:07 UTC on finish), and the file freezes `NOW = datetime.utcnow()` at import (`:80`). The file passes 20/20 re-run alone, and this task touches no code it imports. The cause is not proven by a second full run.
2. **C6's secondary RED point depends on deviation 2.** If the controller's sabotage also drops the creation-first publisher's lock, record the RED location it actually observes.
3. **O1 shows that "commit on the exception path" cannot be produced by a flush-time injection.** The session refuses with `PendingRollbackError`. The real partial-visibility proof is O2, an early COMMIT.
