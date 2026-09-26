# #269 Task 1 report: publication core, shared helpers, atomic single publisher

**Status:** DONE_WITH_CONCERNS (all gates GREEN; three defensive guards have no killing test, see Mutations; one lock-order finding, see Concerns).

- TASK_BASE `2322a4291`, TASK_HEAD `256f2233c`.
- Commit: `256f2233c feat: atomic graph release publication core (#269)`, one commit. The report is force-added separately.

## What was built
- `src/services/graph_configuration_content.py`: `as_utc_aware` (C3), `database_transaction_timestamp`, `materialize_or_reuse_revision` (docstring per C25).
- `src/services/graph_configuration_bootstrap.py`: `_database_timestamp` delegates to the helper. The v1 revision loop calls `materialize_or_reuse_revision`. `datetime` stays imported because the bootstrap tests monkeypatch `graph_configuration_bootstrap.datetime`.
- `src/services/graph_configuration_draft.py`:
  - `_advance_locked_draft` (staticmethod, the one parent-audit write).
  - `_write_locked_content` uses `database_transaction_timestamp` plus `_advance_locked_draft`. The statement text is still `SELECT CURRENT_TIMESTAMP`.
  - C36: `_actor_issues` and `_lock_version_issues` are extracted. `_validate_common` = actor + `_lock_and_agent_key_issues`, and `_lock_and_agent_key_issues` = `_lock_version_issues` + the unchanged agent-key check. Issues and order are byte-identical.
- `src/services/graph_configuration_publication.py` (new):
  - The Stable-interface dataclasses, plus C1's `PublicationGap` / `PublicationGapCode` and the `PublicationNotReady.__post_init__` shape checks.
  - `PublicationRejected`, `publish_draft`, `_validate_publication_request` (C17/C36/C10: `strict_type` → `blank` → `too_long` at 2000), `_lock_all_draft_agents` (L1), `_validate_changed_candidates` (C37: `_save_local_validators()` then `post_stale_validators`, never the remote check), `_commit_locked_publication`, and `_link_evidence` (Phase A refuses any evidence).
- `src/services/graph_configuration.py`: the MRO becomes `(Publication, Draft, Workbench, Bootstrap)`. The new names are exported, and the docstring notes the MRO dependency (C2 4c's note).
- Tests:
  - `tests/unit/test_graph_release_publication.py`: 34 tests.
  - `tests/integration/test_graph_release_publication_postgres.py`: 9 tests. `_NoEvidenceGate` and `_save_prompt` are defined here per C24; `_save_prompt` has an extra optional `prompt_text=`.
  - `tests/integration/postgres_concurrency_helpers.py`: `_await_blocked_by`.
- CI: `.github/workflows/test.yml` enrols the new PostgreSQL file in `integration-graph`, pinned by `tests/unit/test_ci_collects_integration_tests.py::test_graph_release_publication_is_collected_by_integration_graph`.

## RED evidence
- Step 2 unit RED: `ModuleNotFoundError: No module named 'src.services.graph_configuration_publication'`, which is the expected cause.
- The PostgreSQL tests were written after the core existed, so they were GREEN on their first run. Their RED is proved by mutation (table below): M02, M04, M11, M25 and M27 each turn PostgreSQL tests RED.

## Gates (real numbers; `test ! -e .venv` held before and after every run)
- **Focused unit:** 937 passed, 0 failed, 0 skipped. Files: `test_graph_release_publication`, `test_graph_configuration_bootstrap`, `test_graph_configuration_draft`, `test_graph_definition_content_mapping`, `test_agent_definition_workbench_routes`, `test_agent_test_workbench` (C52), `test_ci_collects_integration_tests`.
- **Full unit:** 6 failed / 6819 passed / 110 skipped. That is baseline 6784 + 35 new (34 new publication tests + 1 CI pin).
  - The failures are the same six nodes with the same first lines: (A) `test_deploy_autoscaling` ×2 (the mock); (B) chokepoint `'_FakeSession' object has no attribute 'execute'` ×3; (C) persistence boundary `ConversationGraphReleaseIntegrityError: no active Graph Release` ×1.
  - No new cause.
- **PostgreSQL**, one invocation per file, zero skips in each:

  | File | Passed | Failed | Skipped |
  |---|---|---|---|
  | `test_graph_release_publication_postgres` | 9 | 0 | 0 |
  | `test_graph_configuration_bootstrap_postgres` | 3 | 0 | 0 |
  | `test_agent_definition_workbench_postgres` | 49 | 0 | 0 |
  | `test_agent_schema_overlay_postgres` | 10 | 0 | 0 |
  | `test_graph_configuration_constraints_postgres` | 66 | 0 | 0 |

  The `tellr_int_*` list is identical before and after (the same 4 older databases), so none were leaked or dropped.
- **Ruff:** clean on every changed file except `tests/unit/test_ci_collects_integration_tests.py`. That file has a pre-existing I001 (import order at :19), which also appears at TASK_BASE. I only appended a test at the end and did not fix it.

## Mutation table
Each mutation was restored with `git checkout 256f2233c -- src .github tests`, then checked with `git diff --exit-code` and a clean `grep MUTANT-` (verified after every run). The script is at `/tmp/t269-1-mutate.py`.

| # | Mutation | Result | Killing test(s) / observed cause |
|---|---|---|---|
| M01 | delete `draft_row.base_release_id = new_release.id` (brief controller) | RED | `test_publish_two_changed_roles…` (rebase / boot assertions) |
| M02 | `materialize_or_reuse_revision` always inserts (brief reviewer) | RED, 20 | Unique violation (autoflush) in the unit happy path, restore, bootstrap reuse ×2, PostgreSQL exact/reverted/stages/lock-sequence, etc. |
| M03 | bare `release_row.effective_from` (C3 reviewer) | RED | 10× `TypeError: can't compare offset-naive and offset-aware datetimes` on every SQLite test that reaches the core |
| M04 | explicit `session.begin()` + `finally: session.commit()` (C8 reviewer) | RED | `[mappings_read_back]`: after≠before (v2 committed), as predicted. `[commit]`: GREEN, as predicted (it fails at COMMIT either way). **Deviation:** `[interval_closed]` and `[draft_rebased]` observe `PendingRollbackError`, not C8's predicted trigger `IntegrityError` / after≠before. The injected error is raised inside a flush, which marks the transaction rolled back, so the mutant's `commit()` cannot commit. Also RED: 3 unit tests (after≠before). |
| M05 | `local_candidate_validators` in place of `_save_local_validators()` (C37 reviewer) | RED | `test_url_shaped_endpoint_written_past_the_save…` |
| M06 | `<=` → `<` (C4 optional) | RED | `test_same_second_timestamp…[same]` |
| M07 | delete the stale branch | RED | `test_stale_lock_version_returns_conflict…` |
| M08 | delete the nothing-to-publish branch | RED | `test_nothing_changed_returns_nothing_to_publish` |
| M09 | drop request validation | RED | `…reject_before_any_lock[note-empty]` (reached the DB CHECK) |
| M10 | drop the 2000 cap | RED | `…[note-2001]` |
| M11 | drop the L1 draft-agent lock | RED | PostgreSQL `test_publication_lock_statement_sequence` |
| M12 | drop the close-before-insert flush | **SURVIVED** | An equivalent mutant: SQLAlchemy's unit of work emits the `graph_release` UPDATE before the INSERT within one mapper flush. The flush is kept as the explicit ordering the non-deferrable index needs, with no dependency on UoW ordering. |
| M13 | drop the mapping read-back check | **SURVIVED** | Defensive. It is unreachable without a DB or ORM defect. |
| M14 | drop the latest-version guard | RED | `test_an_active_release_that_is_not_the_latest_version…` |
| M15 | drop the unchanged-reuse guard | RED | `test_an_unchanged_role_that_does_not_reuse…` (becomes an FK IntegrityError) |
| M16 | drop the Phase A evidence refusal | RED | `test_evidence_from_a_phase_a_gate…` |
| M17 | drop the `no_required_case` id check | RED | `test_publication_not_ready_rejects_malformed_gaps[no-required-case-with-id]` |
| M18 | drop the `PublicationNotReady` early return | RED | `test_gate_not_ready_writes_nothing` |
| M19 | drop candidate validation | RED | `test_invalid_changed_candidate…` |
| M20 | `changed_agent_keys` = all keys | RED | happy path |
| M21 | drop `_advance_locked_draft` in the core | RED | happy path (lock 3 / `updated_by`) |
| M22 | `_advance_locked_draft` without the increment | RED | `test_graph_configuration_draft.py::test_exact_five_field_save…` |
| M23 | drop the `canonical_payload` equality in reuse | **SURVIVED** | Defensive against a SHA-256 collision. `validate_definition_hash` already rejects any tampered row, so it cannot be reached. |
| M24 | remove the CI enrolment line | RED | `test_graph_release_publication_is_collected_by_integration_graph` and `test_every_integration_file_is_collected_or_excluded_with_reason` |
| M25 | L0 statement written `select_from(GraphDraft).join(GraphRelease)` | RED (text only) | `test_publication_lock_statement_sequence`. `test_parent_lock_statement_takes_release_before_draft` stayed **GREEN** (see Concerns). |
| M26 | allow empty `locked_gaps` | RED | `…malformed_gaps[empty]` |
| M27 | L1 lock after the snapshot | RED | PostgreSQL lock-sequence test |
| M28 | Python clock in place of the DB transaction timestamp | RED | `test_same_second_timestamp…[same]` (patched callable never invoked) |
| M29 | drop the actor check in the publication request | RED | `…[actor-blank]` |

The brief's controller (M01) and reviewer (M02) targets and the corrections' Task 1 reviewer targets (C3 → M03, C8 → M04, C37 → M05) have all been run. The controller and the reviewer should pick different seams.

## Deviations from the brief and corrections
1. **`_await_blocked_by` is written in Task 1, not Task 2** (C53 places it in Task 2). C13-2's Task 1 test needs it. It lives in `postgres_concurrency_helpers.py` with the producer/consumer signature `(engine, *, waiter_pid, blocker_pid) -> bool`. It checks `wait_event_type='Lock'` and the blocker in `pg_blocking_pids`, in one observation, bounded by `_WAIT_SECONDS`. Task 2 must reuse it and not add a second one.
2. **C8 `commit` stage.** The test-only constraint trigger raises with `ERRCODE '23514'` so the error surfaces as `IntegrityError`, as C8 asserts. Its function bumps a sequence (`nextval`, which is non-transactional) to prove it fired exactly once. It is installed and dropped per parametrization.
3. **`_save_prompt` gains an optional `prompt_text=` keyword** in both files (for the reverted-content test). The C24 positional signature is unchanged.
4. **Extra tests beyond the brief:**
   - `as_utc_aware` ×2;
   - the 2000-character note is accepted;
   - `PublicationNotReady` shape checks (C1);
   - the Phase A evidence refusal;
   - the core's incomplete content set;
   - the latest-version guard;
   - the unchanged-reuse guard;
   - the reuse tamper check;
   - the C37 remote-validator spy.
5. **C4:** the gate-call assertion is `len(gate.calls) <= 1`, per C4's wording. It is actually 1, because the guard runs after the gate.
6. **Not implemented here, because they bind other tasks:** C2 (Task 2 steps 4a–4d), C5/C6/C9 (Tasks 2–3), C8 part 3 (Task 3), and C22 (Task 5). No readiness is used. `_link_evidence` is the Task 4 seam.

## Interfaces Task 2+ consume (file:line at `256f2233c`)
- `src/services/graph_configuration_publication.py`:

  | Name | Line |
  |---|---|
  | `EvidenceLink` | :75 |
  | `PublicationGap` | :84 |
  | `PublicationNotReady` | :92 |
  | `PublicationEvidenceGate` | :112 |
  | `PublishedMapping` | :123 |
  | `PublishedRelease` | :132 |
  | `PublicationConflict` | :142 |
  | `NothingToPublish` | :151 |
  | `PublicationRejected` | :157 |
  | `_GraphConfigurationPublication` | :174 |
  | `publish_draft` | :177 |
  | `_validate_publication_request` | :228 |
  | `_lock_all_draft_agents` | :244 |
  | `_validate_changed_candidates` | :262 |
  | `_commit_locked_publication` | :288 (the #270 seam) |
  | `_link_evidence` | :414 (Task 4 replaces the body) |

  Also `RELEASE_NOTE_MAX_LENGTH = 2000` and the literals `EvidenceKind` / `PublicationGapCode`. Everything is re-exported from `src/services/graph_configuration.py`.
- `src/services/graph_configuration_content.py`: `as_utc_aware` :154, `database_transaction_timestamp` :165, `materialize_or_reuse_revision` :177.
- `src/services/graph_configuration_draft.py`: `_actor_issues` :775, `_lock_version_issues` :812, `_advance_locked_draft` :1004.
- Tests:
  - `tests/integration/postgres_concurrency_helpers.py:215` `_await_blocked_by`;
  - `tests/integration/test_graph_release_publication_postgres.py`: `_NoEvidenceGate` :45, `_save_prompt` :56, plus local `_artifacts`, `_publish`, `_run_named` and `_fresh_active_pin`, which Task 2 may reuse in the same file.
- Stage-injection matchers: `_STAGE_MATCHERS` in the PostgreSQL file. Task 4 adds `evidence_linked` there.

## Concerns
1. **The L0 rowmark order is a planner choice, not a property of the statement text (M25).** Rewriting the L0 statement as draft-first `FROM` left `test_parent_lock_statement_takes_release_before_draft` GREEN: PostgreSQL still held the release while it waited on the draft. So C13-2's test pins the observed behaviour (release held while waiting) under today's plan, but it cannot detect a regression that changes only the SQL text. `test_publication_lock_statement_sequence` catches the text change. Whole-branch reviewers should not treat "release-before-draft" as statement-guaranteed. A plan change on a larger data set could invert it, which matters for the C13 deadlock argument.
2. **Three surviving mutants (M12, M13, M23)** are equivalent or defensive guards with no reachable input. I kept them as belt-and-braces and did not write tests that fake impossible states.
3. **C8's reviewer prediction is partly wrong (M04):** `[interval_closed]` and `[draft_rebased]` RED with `PendingRollbackError`, not the predicted causes. It is still RED, but the recorded cause differs.
4. The unit and PostgreSQL gate runs overlapped in time, with distinct `DATABASE_URL` files. Results are as listed above.
