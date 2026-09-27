# #270 Task 0 phase A — preflight (2026-09-26)

- TASK1_BASE = dbbea85e10beb04d30efaee4c184417ab41069f6 (file `TASK1_BASE`, immutable). `a08389ec3` is an ancestor; `git diff a08389ec3 HEAD -- src tests frontend packages .github` is empty. Python 3.11.0. `test ! -e .venv` before/after every run.

## Unit baseline (full tests/unit, DATABASE_URL=sqlite:////tmp/t270-0.sqlite -q -p no:randomly -rf)
6 failed, 6625 passed, 110 skipped (479s). Exactly the expected six, by cause:
| node | first causal line |
|---|---|
| test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available | `AssertionError: assert 'provisioned' == 'autoscaling'` |
| test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails | `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.` |
| test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict | `AttributeError: '_FakeSession' object has no attribute 'execute'` |
| …::test_create_session_still_stores_a_single_authority_config_unchanged | same |
| …::test_create_session_still_accepts_no_agent_config | same |
| test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session | `ConversationGraphReleaseIntegrityError: no active Graph Release` |
The run includes Correction 14's unit addition `test_graph_definition_content_mapping.py` (full directory).

## PostgreSQL baseline (Correction 14's corrected loop, one invocation each, TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres, -rs)
| file | result | skips |
|---|---|---|
| test_graph_configuration_bootstrap_postgres | 3 passed | 0 |
| test_graph_configuration_constraints_postgres | 66 passed | 0 |
| test_agent_definition_workbench_postgres | 25 passed | 0 |
| test_conversation_pin_creation_postgres | 2 passed | 0 |
| test_mixed_release_creation_postgres | 14 passed | 0 |
| test_conversation_creator_exclusions_postgres | 4 passed | 0 |
| test_conversation_pin_acceptance_postgres | 1 passed | 0 |
| test_persisted_graph_runtime_failures_postgres | 7 passed | 0 |
| test_agent_schema_overlay_postgres (C14) | 10 passed | 0 |
| test_conversation_pin_migration_postgres (C14) | 1 passed | 0 |
| test_mixed_release_collaboration_acceptance_postgres (C14) | 26 passed | 0 |

## Symbols Task 1 cites, re-verified at a08389ec3 (all match the plan's lines)
AgentDefinitionRevision models:159; GraphRelease :193 (interval check, one-active partial unique index); GraphReleaseAgent :248; AgentTestCase :328; AgentTestRun :373, run_kind check :453–454; GraphReleaseTestRun :493, source-paired check :530–533; guards database.py:935, first-close-only :1019–1020, trg_agent_test_run_evidence_immutable :1098, deferred exactly-one :1110; validate_definition_hash graph_configuration_content.py:128; GraphConfigurationIntegrityError :27; GRAPH_V1_AGENT_KEYS / AgentKey graph_definition_manifest.py:66 / :57; PersistedGraphReleaseLoader persisted_graph_release.py:91, _validate_complete_snapshot :167; _publish_v2 test_conversation_pin_acceptance_postgres.py:125; postgres_engine conftest.py:235; integration-graph job test.yml:410 (run block ends before `-v --tb=short`). `graph_release_history` / `restore_release` absent (expected).
