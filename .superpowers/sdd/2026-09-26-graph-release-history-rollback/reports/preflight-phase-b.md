# #270 Task 0 phase B — preflight (2026-09-27)

- **HEAD:** `7465854f4` on `plan/release-history-rollback-270`. **INTEGRATION_BASE:** `c7ea1d943` (Merge #269). Code-wise `c7ea1d943..HEAD` is exactly the rebased Task 1 `29df4c318` (see `predecessor-heads.md`).
- **Environment:** Python 3.11.0 via `/Users/robert.whiffin/.pyenv/shims/python`, `PYTHONPATH=<tree>:<tree>/packages/databricks-tellr`, every env var set on the command line. `test ! -e .venv` held before and after every backend run. No pip, no npm install. `frontend/node_modules` is the symlink to `.worktrees/issue-260-bootstrap/frontend/node_modules` (already present).
- **PostgreSQL databases:** the `tellr_int_*` list was exactly the 4 older databases before and after (`0da9e060…`, `5a18c26f…`, `6f336988…`, `ac9b0f3b…`). None leaked; none dropped. `ai_slide_generator` was not touched.

## 1. Full unit suite

Command: `DATABASE_URL=sqlite:////tmp/t270-0.sqlite PYTHONPATH=… python -m pytest -q -p no:randomly -rf tests/unit` (04:46:54–04:54:20 UTC; did not cross midnight, so the `test_usage_service.py` flake could not fire).

**Result: 6 failed / 6975 passed / 110 skipped (437.6 s).** Exactly the known six, by node and first causal line:

| Node | First causal line | Same as phase A / #269 |
|---|---|---|
| `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available` | `AssertionError: assert 'provisioned' == 'autoscaling'` | yes |
| `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails` | `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.` | yes |
| `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict` | `AttributeError: '_FakeSession' object has no attribute 'execute'` | yes |
| `…::test_create_session_still_stores_a_single_authority_config_unchanged` | same | yes |
| `…::test_create_session_still_accepts_no_agent_config` | same | yes |
| `test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session` | `ConversationGraphReleaseIntegrityError: no active Graph Release` | yes |

No new cause. Passes rose 6643 → 6975 (+332) from #269's tests plus Task 1's; #269's own final gate at `8666939de` was 6957 passed, and +18 is Task 1's 17 unit tests plus its CI pin.

Focused re-run (plan Task 0 Step 4 asks for it by name): `test_graph_release_publication.py::test_core_writes_restored_from_verbatim`, `test_graph_release_history.py` (17), `test_graph_parent_lock_is_single_sourced.py` (2), `test_graph_release_client_join.py`, `test_ci_collects_integration_tests.py` → **61 passed**.

## 2. PostgreSQL — every `integration-graph` file, one invocation each

Command per file: `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres DATABASE_URL=sqlite:////tmp/t270b/pg-<file>.sqlite PYTHONPATH=… python -m pytest -q -p no:randomly -rs tests/integration/<file>.py`. The file list is the `integration-graph` `run:` block (`.github/workflows/test.yml:448–477`, 30 files). **Zero skips in every file.**

| # | File | Result |
|---|---|---|
| 1 | test_graph_orchestration | 19 passed |
| 2 | test_graph_mode_turn | 39 passed |
| 3 | test_graph_configuration_bootstrap_postgres | 3 passed |
| 4 | test_graph_configuration_constraints_postgres | 66 passed |
| 5 | test_conversation_pin_migration_postgres | 1 passed |
| 6 | test_shared_deck_mutation_migration_postgres | 3 passed |
| 7 | test_shared_deck_mutation_lifecycle_postgres | 4 passed |
| 8 | test_collaboration_history_api_postgres | 30 passed |
| 9 | test_mixed_release_collaboration_acceptance_postgres | 26 passed |
| 10 | test_shared_deck_mutation_attribution (under `timeout 120`) | **60 passed in 17 s, exit 0** — the pre-existing local hang did NOT reproduce this run. It is still recorded as a pre-existing, intermittent hang (#269 whole-branch §9 reproduced it at base `16aa02b76`); #270 touches no file on its path. |
| 11 | test_conversation_pin_creation_postgres | 2 passed |
| 12 | test_mixed_release_creation_postgres | 14 passed |
| 13 | test_conversation_creator_exclusions_postgres | 4 passed |
| 14 | test_persisted_graph_runtime_failures_postgres | 7 passed |
| 15 | test_conversation_pin_acceptance_postgres | 1 passed |
| 16 | test_agent_definition_workbench_postgres | 49 passed |
| 17 | test_agent_schema_overlay_postgres | 10 passed |
| 18 | test_graph_release_publication_postgres (#269) | 21 passed |
| 19 | test_graph_release_session_ordering_postgres (#269) | 29 passed |
| 20 | test_graph_release_evidence_postgres (#269) | 18 passed |
| 21 | test_graph_release_publication_acceptance_postgres (#269) | 3 passed |
| 22 | test_graph_release_history_postgres (#270 Task 1) | 4 passed |
| 23 | test_spec_dirty_marker_routes | 11 passed |
| 24 | test_sweeper_describe_only | 18 passed |
| 25 | test_architect_reply_is_persisted | 9 passed |
| 26 | test_insert_slide_route | 8 passed |
| 27 | test_slide_id_is_durable | 14 passed |
| 28 | test_deck_spec_change_turn | 9 passed |
| 29 | test_spec_row_alignment | 10 passed |
| 30 | test_claim_exclusivity_postgres | 3 passed, 1 xfailed (pre-existing xfail, as in #269's gate) |

Counts equal #269's whole-branch gate for every shared file. No failing node, so there is no cause to record.

## 3. Frontend

- `npx vitest run src/components/Admin/GraphRelease src/components/Admin/AgentDefinitionWorkbench` → **10 files, 778 passed** (GraphRelease alone: 4 files, 150 passed — `lineDiff` 5, `releaseClient` 81, `reviewAndPublishState` 42, `ReviewAndPublishPage` 22).
- `npm run typecheck` (`tsc -b`) → **exit 0**, no output.
- Playwright not run (instruction).

## 4. Probes run for the corrections (throwaway, no product code)

- `/tmp/t270b/probe_restore.py` (SQLite in-memory, C1-style patched clock on `src.services.graph_configuration_publication.database_transaction_timestamp`): bootstrap → publish v2, v3 (architect) with `_NoEvidenceGate` → seed an approved candidate run linked to v2 as `approval` → inside one `session.begin()`: `_lock_current_parents(exclusive=True)`, `_lock_all_draft_agents`, snapshot, L3 `FOR UPDATE OF agent_test_run` on v2's linked runs, then `_commit_locked_publication(contents=<v2 definitions from read_release_detail>, evidence=(EvidenceLink(run, "architect", case, "historical_restore", v2.id),), restored_from_release_id=v2.id)`. Output:
  - `version 4`, `restored_from == v2`, previous = v3, `changed ('architect',)`, all seven `reused`, draft `lock_version` 5, clock called 3 times;
  - links `[(2, 1, 'approval', None), (4, 1, 'historical_restore', 2)]` — the CHECK constraints accept the pairing; no new revision; v4 mapping == v2's;
  - `list_release_history`: `(4, restored_from 2)`, v2 `restored_by [4]`;
  - `read_workbench` after: base v4, **architect `changed is True`** — the core's parent-only rebase leaves the clean role holding v3 content (the Q7 rationale, observed).
- MRO at HEAD: `GraphConfiguration → _GraphConfigurationPublication → _GraphConfigurationDraft → _GraphConfigurationWorkbench → _GraphConfigurationBootstrap → object`.
