# #269 Task 2 report — publication handoff retry, C2 boot lock, race tests

**Status:** DONE_WITH_CONCERNS (minor; see Concerns). TASK_BASE `5c3cfd827`. Opus implementer, no subagents, no push.

## Commits (`5c3cfd827..672d49734`)
| SHA | What |
|---|---|
| `ccd77756d` | fix: `_lock_current_parents` rescans once on a zero-row L0 scan (`_MAX_PARENT_LOCK_SCANS = 2`), diagnosis unchanged; 6 race tests (7 nodes) + C9 test |
| `7abacf86d` | fix: C2 — `_validate_current_graph` starts with `self._lock_current_parents(session, exclusive=False)`; bootstrap class docstring notes the facade-MRO dependency; 2 C2 race tests |
| `3f8cc4191` | test: boot takes exactly one lock, `FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT`, before the release list read (closes surviving M6/M7) |
| `672d49734` | test: C49 pin — with the rescan disabled, a queued reader raises exactly `agent_test_workbench._PARENT_HANDOFF_DIAGNOSIS` (closes surviving M9) |

Files: `src/services/graph_configuration_workbench.py`, `src/services/graph_configuration_bootstrap.py`, `tests/integration/test_graph_release_publication_postgres.py`. `postgres_concurrency_helpers.py` is **unchanged**: Task 1's `_await_blocked_by` was reused.

## Step 2 RED (against Task 1 code, retry absent), exact
The PG publication file ran **4 failed, 13 passed**. All 4 failures were `GraphConfigurationIntegrityError: graph configuration parent snapshot is inconsistent` at `graph_configuration_workbench.py:225`:
- `test_publication_first_then_draft_save_gets_stale_not_500`
- `test_publication_first_then_workbench_read_sees_new_release`
- `test_two_publishers_one_winner_one_exact_stale_conflict[alpha]` and `[beta]`

GREEN at RED, as C18 predicts: `test_draft_save_first_then_publication_is_stale`, `test_sequential_retry_after_success_is_stale` and `test_stale_publisher_after_intervening_save_is_conflict_not_v3`. This matches the plan's reasoning and the reviewer's probe, so no PLAN-CORRECTIONS entry was needed.

## C2 Step 4b RED (retry present, boot lock absent), exact
- `test_boot_validation_queued_behind_publication_sees_new_release` failed with `AssertionError: boot was never blocked by publisher`, meaning `_await_blocked_by` returned False.
- `test_publication_during_boot_validation_waits_for_boot` failed with `GraphConfigurationIntegrityError('release mapping rows do not belong to the complete release history')`, as probe A predicted.

## Gates (at `672d49734` unless noted; one invocation per file; zero skips everywhere)
- **PG `test_graph_release_publication_postgres.py`:** 21 passed. That is 10 from Task 1, plus 7 race nodes, the C9 test, 2 C2 tests, the boot-lock-shape test and the C49 pin.
- **PG bootstrap:** 3 passed, including the two-bootstrap advisory test at `:105`.
- **PG workbench (#266/#267/#268, incl. the C49 tests at :2373/:2868/:3466):** 49 passed.
- **PG overlay:** 10 passed.
- **PG constraints:** 66 passed.
- **Extra check:** the other `*_postgres` files in the CI integration-graph job all passed with 0 skips, because bootstrap now takes L0 on every start:
  - pin_migration 1, shared_deck_mutation_migration 3, lifecycle 4, collaboration_history_api 30
  - mixed_release_collaboration_acceptance 26, pin_creation 2, mixed_release_creation 14
  - creator_exclusions 4, persisted_graph_runtime_failures 7, pin_acceptance 1
- **Focused unit** (`test_agent_definition_workbench_routes`, `test_graph_configuration_draft`, `test_agent_test_workbench`, `test_graph_configuration_bootstrap` incl. the corrupt-state parametrization, `test_graph_parent_lock_is_single_sourced`, `test_graph_release_publication`): 909 passed at `ccd77756d`. The bootstrap unit file alone was 27 passed after C2.
- **Full unit:** 6 failed / 6822 passed / 110 skipped. These are the baseline six by node and first line:
  - A×2: autoscaling mock
  - B×3: `_FakeSession` has no `execute`
  - C×1: "no active Graph Release"
- **ruff check** on the 3 changed files: clean. `ruff format --check` would reformat all 3, but it also would at base (`5c3cfd827`'s bootstrap), so the repo does not enforce it and I left it alone.
- **Leaked DBs:** none. The `tellr_int_*` list is still the 4 older ones. `ai_slide_generator` was never touched.

## Mutation table (restored from explicit SHA each time: M1–M8 from `7abacf86d`, M5b/M6b/M7b from `3f8cc4191`-era HEAD, M9 from `672d49734`; `git diff` empty after each)
| # | Mutation | Result |
|---|---|---|
| M1 (plan controller sabotage, run by me) | `_MAX_PARENT_LOCK_SCANS = 1` | **RED** 5: the C18 set (draft-save, reader, two-publisher ×2) + boot-queued, all with the parent-snapshot diagnosis |
| M2 (plan reviewer sabotage, run by me) | stale branch `if expected_lock_version != draft_row.lock_version` → `if False` | **RED** 5, exactly as C9 predicts: C9 test observes `PublishedRelease(version 3)`; two-publisher ×2 and sequential retry observe `NothingToPublish`. It also REDs draft-save-first, whose stale publisher publishes v2 |
| M3 | drop `parent_rows or` (always rescan) | **RED** 2: lock-statement-sequence and FOR SHARE-shape tests (an extra L0 statement) |
| M4 | retry condition `len(parent_rows) == 1` (so a multi-row result also rescans) | **SURVIVED**, equivalent: the rescan returns the same multi-row set and raises the same diagnosis. A multi-row L0 result is unreachable anyway (the one-active unique index, the singleton draft) |
| M8 | invert to `not parent_rows` | **RED** 7 |
| M5 (C2 controller sabotage; **I ran it**) | delete the boot lock line | **RED** 2, exactly as C2 predicts: boot-queued at `_await_blocked_by`, and publication-during-boot with "release mapping rows do not belong to the complete release history" |
| M5b | same, after `3f8cc4191` | **RED** at the boot-lock-shape test too |
| M6 | boot lock `exclusive=True` | first **SURVIVED**, so I added `3f8cc4191`; re-run **RED** at the boot-lock-shape test |
| M7 | boot lock moved after the release list read | **RED** 2 (both C2 race tests); re-run after `3f8cc4191` also **RED** at the shape test |
| M9 | diagnosis text gets a trailing `.` | first **SURVIVED** (907 unit, incl. `test_agent_test_workbench`, all GREEN), so I added `672d49734`; re-run **RED** at `test_a_double_handoff_keeps_the_diagnosis_267_retries_on` |

## Deviations
1. **`_await_blocked_by` was reused, not appended.** It already existed from Task 1, as ruled. Its code differs from the brief's, but the behaviour is equivalent:
   - it holds one observer connection and rolls back between polls;
   - it checks `wait_event_type = 'Lock'` and `blocker = ANY(pg_blocking_pids(pid))` for the waiter's row;
   - it has no `datname = current_database()` filter, which is harmless because the waiter PID is exact.
   Signature `(engine, *, waiter_pid, blocker_pid) -> bool`, the same. I did not fork it.
2. **PIDs are recorded per C5,** not by the brief's `after_cursor_execute` recipe. A test subclass `_RaceObservedGraphConfiguration` overrides `_lock_current_parents` and `_take_bootstrap_lock`. Each override runs `SET LOCAL lock_timeout = '30s'`, runs `SELECT pg_backend_pid()` and sets a per-thread "attempted" event, all before `super()`. `after_cursor_execute` is used only to pause the blocker. Holders are released in an inner `finally` before the executor joins, and every future is bounded.
3. **Two-publisher parametrization.** The winner is `alpha` or `beta`, as a distinct actor and note. The winner always runs on thread `publisher-winner`, and the test asserts the winning release's `published_by` and `release_note`.
4. **"Draft content unchanged" is asserted as `(candidate_hash, prompt_text)`** of the saver's role. `graph_draft_agent` has no base-revision column.
5. **C2's lock is a bare call.** C2 writes `release_row, draft_row = self._lock_current_parents(...)`, but the rows are unused, so I dropped the unpacking. No second both-parents lock, and the AST scanner stays GREEN.
6. **Two extra tests** came out of the mutation sweep: `3f8cc4191` and `672d49734`.

## Concerns
1. **M4 is equivalent.** "Never retry a multi-row result" is not behaviourally pinned. The only difference is one extra read on an unreachable path. I accepted this rather than adding a fake-session unit test.
2. **C49's and C51's table edits were not made.** C49 asks to add the handoff consumers to the seam table, and C51 to add #266's remote check to the L0 row. Both edit plan-level documentation (the seam and lock-order tables, owned by the whole-branch review). This task produced no doc change for them; the consumers are now covered by gate runs and the M9 pin.
3. **ruff format is not enforced** (see Gates).
4. **The C2 share lock means conversation creation waits for the length of boot validation.** C2 accepts this cost; no test measures it.
