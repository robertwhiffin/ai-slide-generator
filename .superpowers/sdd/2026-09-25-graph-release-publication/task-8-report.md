# Task 8 report: real-PostgreSQL HTTP acceptance flow (the #271 AC7 seam)

**Status:** DONE_WITH_CONCERNS. The concern is not caused by Task 8; see Concerns.
**TASK_BASE:** `d3ec80bcf`. **Mutation pin:** `5224f8a4b`.
**Scope:** test-only. `git diff d3ec80bcf 5224f8a4b -- src frontend` is empty.

## Commits
| SHA | Summary |
|---|---|
| `5224f8a4b` | test: end-to-end graph release publication acceptance (#269) |

The controller and reviewer committed concurrently on this branch: Task 7's `a97b024d2`, `ed8e05dd8`, `64c2e9fcb`, `ae3b0a8fb` and `365b4fc83` are interleaved with mine. None of them touch the files below.

## Files
- **Created:** `tests/integration/test_graph_release_publication_acceptance_postgres.py`, with 3 tests.
- **Modified:**
  - `.github/workflows/test.yml`: the new file is enrolled in the `integration-graph` run block, after the evidence file.
  - `tests/unit/test_ci_collects_integration_tests.py`: adds `test_graph_release_publication_acceptance_is_collected_by_integration_graph`.

## Harness (C53, C38)
- The `acceptance_stack` fixture is a copy of `real_route_stack` (`test_agent_definition_workbench_postgres.py:1283–1310`), not an import. It covers:
  - `bootstrap_v1`
  - the one shipped `agent_definitions.router`
  - `get_db` pointed at the throwaway database
  - the remote endpoint validator set to accept
  - a trusted admin
- It also overrides `get_agent_test_workbench` with the `_pg_executor` recipe (`AgentRuntime(PersistedGraphReleaseLoader, DeterministicFakeModelAdapter, RecordingAgentInvocationIdentitySink)`).
  - Runs, verdicts, readiness, preview and publish therefore all resolve through that one dependency (C39).
  - There is no second `_await_blocked_by`: it is imported from `postgres_concurrency_helpers.py`.
  - Nothing is imported from `test_agent_definition_workbench_postgres.py`.
- `SessionManager` is driven for real, with only `session_manager.get_db_session` patched to the throwaway factory.

## Tests
1. **`test_edit_test_approve_preview_publish_pin_flow`** runs in this order:
   1. Bootstrap. `create_session("old-root", graph_capable=True)` pins v1 (graph_version 1, not older).
   2. PUT architect, then builder (lock 0→2).
   3. Run builder's required case and approve it. Run it **again** and approve that run too (C12 item 1). Run architect's case but do not approve it.
      - Every run is `completed` with `deterministic_checks_passed = true`.
      - The adapter calls are exactly builder, builder, architect.
      - Neither the runs nor the verdicts move the lock (C41).
   4. POST with the current lock returns **409 `publication_not_ready`** (C12 item 2):
      - `gaps == [{"agent_key":"architect","test_case_id":<architect case>,"code":"no_eligible_approval"}]`
      - readiness: `blocking_agents == ["architect"]`, and architect's case is `awaiting_review` and blocking, with `run_id` = architect's run
      - builder's case is `approved`, with `run_id` = builder's **second** run
      - the body equals `GET /readiness`
      - no release is written
   5. Approve architect. The preview then shows:
      - changed roles exactly `["architect","builder"]`
      - for each role, `field_diffs == [{"field":"prompt_text","published":…,"candidate":…}]` (exact)
      - `published_revision_id` equal to the v1 mapping
      - `next_version_number == 2`, `publishable is True`, no validation issues, no blocking agents
   6. POST with lock−1 returns an exact 409 `stale_publication` body, and no release is written.
   7. POST with the current lock returns an exact **200** (C10):
      - v2, whose `previous_release_id` is v1, and whose publisher and note are as sent
      - `changed_agents == ["architect","builder"]`
      - 7 mappings in `GRAPH_V1_AGENT_KEYS` order: 5 have `reused: true`, each equal to its v1 id; 2 are new ids that appear in no v1 mapping
      - the DB mapping rows equal the wire mappings
      - evidence is exactly `{architect run, builder SECOND run}` (C12 item 3)
      - draft base v2, lock+1
      - release rows `[(v1,1,closed),(v2,2,active)]`
   8. The workbench GET shows base v2, lock+1, and no changed nodes.
   9. Conversations:
      - `create_session("new-root")` pins v2 (2, not older).
      - `old-root` still pins v1 in the DB. Its idempotent `create_session` returns `(1, 2, True)`, and `get_conversation_graph_version` returns `ConversationGraphVersion(1, 2, True)`.
   10. `PersistedGraphReleaseLoader.resolve(v2, "builder")` returns the mapped revision id, content hash, version 2 and the tuned prompt. The same call for v1 still returns v1's revision.
   11. Second POST, both branches:
       - the spent lock returns an exact 409 `stale_publication` (lock → lock+1, active v2)
       - the current lock returns an exact 409 `nothing_to_publish`
       - release rows are unchanged
2. **`test_preview_takes_the_shared_parent_lock_first_and_writes_nothing`** (Task 5 m4). Over the route with an approved changed role:
   - every statement is a `SELECT`
   - exactly one locking statement is sent, at index 0, and it ends `FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT` with `WHERE GRAPH_RELEASE.EFFECTIVE_TO IS NULL`
   - every graph table (release, draft, draft agents, release agents, revisions, cases, runs, evidence links) is identical before and after, **including `xmin`**, so even a no-op UPDATE would show
3. **`test_preview_shares_the_parents_with_a_reader_and_waits_for_a_writer`** tests two cases:
   - **Shared holder.** A concurrent `FOR SHARE OF graph_release, graph_draft` holder does not delay the preview (bounded 30 s result). An exclusive preview would wait here.
   - **Exclusive holder.** A `graph_draft FOR UPDATE` holder makes the preview wait. The wait is proved with `_await_blocked_by`: the preview's PID is captured on its L0 statement, and the holder's PID appears in `pg_blocking_pids`. After the holder rolls back, the preview returns 200.
   - Afterwards, no row or `xmin` has changed.
   - Holders are released in inner `finally` blocks, and every wait is bounded.
   - The worker-thread requests run in `contextvars.copy_context()`: the admin user is a contextvar, so a bare thread got 403.

## Builder approvability (Task 0 concern 3, re-probed): PROVEN
Under `DeterministicFakeModelAdapter(mode="success")`, builder's `builder_required_smoke_v1` run through `POST /draft/builder/test-runs` on real PostgreSQL returns `execution_status == "completed"` with `deterministic_checks_passed == true`. This was asserted twice, and #268's verdict route approved both runs (200).
- **Why it passes:** `_checks` (`agent_test_workbench.py:859`) yields one `output_contract` check, which passes if and only if the runtime's single validation completed. The fake returns `schema.model_validate(FAKE_OUTPUTS["builder"])`. The registry accepts it even though its `position` is 3 while the seed payload's is 1: no position-equality check exists.
- No fixture setting was needed and no check was weakened.

## Gates
Each PostgreSQL file was run in its own invocation, with zero skips:

| Gate | Result |
|---|---|
| new acceptance file | 3 passed |
| publication | 21 passed |
| evidence | 18 passed |
| session ordering | 29 passed |
| workbench | 49 passed |
| CI collection | 18 passed |
| full unit | 7 failed / 6956 passed / 110 skipped |
| ruff (new file) | clean |

- **Full unit, by node and cause:**
  - 6 failures match the baseline: `test_deploy_autoscaling::TestGetOrCreateLakebase` ×2, `test_style_exclusivity_chokepoint::TestModelDumpIsNotTheChokepoint` ×3, and `test_style_exclusivity_persistence_boundary::…test_session_manager_create_session`.
  - The 7th is `test_e2e_matrix_covers_specs.py::test_every_spec_is_in_matrix_or_excluded_with_reason` (see Concerns). `test_usage_service` did not flake.
- **Ruff:** `test_ci_collects_integration_tests.py` still has its I001 at `:19`, which was there before this task (Task 1 report).
- **Databases:** none leaked. The `tellr_int_*` list is back to the 4 older databases.

## Mutation table
Each mutation was applied to `src/`, the new file was run, and the change was restored with `git checkout 5224f8a4b -- <file>`. The tree was clean after every restore.

| # | Mutation | Result | Observed at |
|---|---|---|---|
| M1 | publish reports `reused=False` for every role (`graph_configuration_publication.py`, PublishedMapping) | RED 1/3 | `reused == set()` vs the 5 unchanged roles |
| M2 | publish re-pins every session: `UPDATE user_sessions SET graph_release_id = v2` after linking | RED 1/3 | `_pin_of("old-root") == 2`, expected 1 |
| M3 | gate evidence drops the last case (`graph_release_evidence.py` return `[:-1]`) | RED 1/3 | exact evidence list is missing `('builder', <second run>, …)` |
| M5 | preview takes the exclusive L0 (`exclusive=True`) | RED 2/3 | the statement ends `FOR UPDATE OF …`; the shared-holder half times out |
| M6 | preview issues `UPDATE graph_draft SET lock_version = lock_version` | RED 2/3 | SELECT-only assertion (the UPDATE is listed); the shared-holder half times out |
| M7 | publish skips the stale-lock check | RED 1/3 | the lock−1 POST returned 200, expected 409 |
| M8 | publish does not advance the draft lock | RED 1/3 | `lock_version 2 == 2 + 1` |
| M9 | the shared L0 path takes no row lock at all (`_lock_current_parents` else-branch) | RED 2/3 | no locking statement; "preview never sent L0" (harness-level: the PID capture keys on the FOR SHARE text) |
| M10 | publish route `status_code=201` | RED 1/3 | `201 == 200` |
| M11 | route readiness binding reports nothing blocking (`_readiness_callable` wraps `blocking_agents=()`) | RED 1/3 | `[] == ["architect"]` in the not-ready 409 readiness |
| M12 | `test.yml` enrolment line removed | RED 2/18 | the CI collection guard and the new pin |

Not run, because they are reserved:
- **C12's reviewer sabotage.** In `lock_and_verify`, flip `>` to `<`. Its predicted RED is the exact-evidence assertion, observing builder's first run.
- **The brief's controller sabotage.** `get_conversation_graph_version` reports the active version for pinned sessions. Its predicted RED is the `old_again` / `_projected_version` assertions.

## Deviations
- **Step 2 RED.** The flow was GREEN on its first run, because every production piece already existed; the plan says "no production change expected". Its discriminating power is shown by M1–M11 instead.
- **Extra coverage.** The second POST covers both branches, and the not-ready body is cross-checked against `GET /readiness`. Both go beyond the brief.
- **Unit run database path.** The full unit run used `DATABASE_URL=sqlite:////tmp/t269-8u.sqlite` so that it would not share a file with the PostgreSQL runs going on at the same time.
- **Concurrency harness.** The concurrency test copies the context into its worker threads (`contextvars.copy_context`). This is a harness necessity, not a behaviour change.

## Concerns
1. **This is a real CI defect, but not a Task 8 one.** Task 7's `frontend/tests/e2e/graph-release-review.spec.ts` (`523a64489`) is in neither the e2e matrix in `.github/workflows/test.yml` nor `DELIBERATE_EXCLUSIONS`. As a result, `tests/unit/test_e2e_matrix_covers_specs.py::test_every_spec_is_in_matrix_or_excluded_with_reason` fails on the branch.
   - It already fails at TASK_BASE: `d3ec80bcf`'s `test.yml` has 0 mentions of the spec.
   - I did not fix it, because it is outside Task 8's scope and Task 7 is under concurrent review. It needs a matrix entry for Task 7 or the whole-branch fix wave.
2. **M9 detection is harness-level.** When no lock is sent, the writer-wait half fails at the PID capture ("preview never sent L0") rather than at `_await_blocked_by`. It is still RED, and the shape test also catches it.
