# Task 12 — AC10 gate (Step 1)

SHA: `a2793d8feaa8e52a33a726d1696013fec519920d` (TASK_BASE), run in a clean detached worktree `t271-12-gate` (2026-09-27).

Env: PYTHONPATH=<tree>:<tree>/packages/databricks-tellr DATABASE_URL=sqlite:////tmp/t271-12.sqlite TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres, pyenv python, one file per invocation, `-m 'not live'`; test_shared_deck_mutation_attribution.py under `timeout 120`.

## integration-graph (every file in test.yml's job; zero skips, zero failures)

```
tests/integration/test_graph_orchestration.py rc=0 :: 19 passed, 5 warnings in 7.11s
tests/integration/test_graph_mode_turn.py rc=0 :: 39 passed, 5 warnings in 8.19s
tests/integration/test_graph_configuration_bootstrap_postgres.py rc=0 :: 3 passed, 5 warnings in 2.22s
tests/integration/test_graph_configuration_constraints_postgres.py rc=0 :: 66 passed, 5 warnings in 29.26s
tests/integration/test_conversation_pin_migration_postgres.py rc=0 :: 1 passed, 5 warnings in 0.75s
tests/integration/test_shared_deck_mutation_migration_postgres.py rc=0 :: 3 passed, 5 warnings in 1.67s
tests/integration/test_shared_deck_mutation_lifecycle_postgres.py rc=0 :: 4 passed, 5 warnings in 1.74s
tests/integration/test_collaboration_history_api_postgres.py rc=0 :: 30 passed, 10 warnings in 16.16s
tests/integration/test_mixed_release_collaboration_acceptance_postgres.py rc=0 :: 26 passed, 10 warnings in 14.13s
tests/integration/test_shared_deck_mutation_attribution.py rc=0 :: 60 passed, 5 warnings in 14.13s
tests/integration/test_conversation_pin_creation_postgres.py rc=0 :: 2 passed, 5 warnings in 1.07s
tests/integration/test_mixed_release_creation_postgres.py rc=0 :: 14 passed, 5 warnings in 8.09s
tests/integration/test_conversation_creator_exclusions_postgres.py rc=0 :: 4 passed, 5 warnings in 1.76s
tests/integration/test_persisted_graph_runtime_failures_postgres.py rc=0 :: 7 passed, 5 warnings in 3.76s
tests/integration/test_conversation_pin_acceptance_postgres.py rc=0 :: 1 passed, 125 warnings in 2.52s
tests/integration/test_agent_definition_workbench_postgres.py rc=0 :: 49 passed, 5 warnings in 25.05s
tests/integration/test_agent_schema_overlay_postgres.py rc=0 :: 10 passed, 5 warnings in 7.20s
tests/integration/test_graph_release_publication_postgres.py rc=0 :: 21 passed, 5 warnings in 12.79s
tests/integration/test_graph_release_session_ordering_postgres.py rc=0 :: 57 passed, 5 warnings in 31.75s
tests/integration/test_graph_release_evidence_postgres.py rc=0 :: 18 passed, 5 warnings in 64.66s (0:01:04)
tests/integration/test_graph_release_publication_acceptance_postgres.py rc=0 :: 3 passed, 5 warnings in 11.13s
tests/integration/test_graph_release_history_postgres.py rc=0 :: 5 passed, 5 warnings in 2.54s
tests/integration/test_graph_release_rollback_postgres.py rc=0 :: 12 passed, 5 warnings in 11.20s
tests/integration/test_graph_release_rollback_ordering_postgres.py rc=0 :: 12 passed, 5 warnings in 8.09s
tests/integration/test_graph_release_rollback_acceptance_postgres.py rc=0 :: 1 passed, 5 warnings in 1.68s
tests/integration/test_spec_dirty_marker_routes.py rc=0 :: 11 passed, 10 warnings in 2.01s
tests/integration/test_sweeper_describe_only.py rc=0 :: 18 passed, 5 warnings in 4.37s
tests/integration/test_architect_reply_is_persisted.py rc=0 :: 9 passed, 5 warnings in 1.99s
tests/integration/test_insert_slide_route.py rc=0 :: 8 passed, 10 warnings in 1.70s
tests/integration/test_slide_id_is_durable.py rc=0 :: 14 passed, 10 warnings in 2.11s
tests/integration/test_deck_spec_change_turn.py rc=0 :: 9 passed, 5 warnings in 1.99s
tests/integration/test_spec_row_alignment.py rc=0 :: 10 passed, 5 warnings in 3.18s
tests/integration/test_claim_exclusivity_postgres.py rc=0 :: 3 passed, 1 xfailed, 5 warnings in 2.41s
tests/integration/test_graph_lifecycle_acceptance_postgres.py rc=0 :: 2 passed, 5 warnings in 4.24s
tests/integration/test_graph_lifecycle_runtime_postgres.py rc=0 :: 2 passed, 125 warnings in 5.90s
tests/integration/test_lakebase_contract_failures_postgres.py rc=0 :: 22 passed, 125 warnings in 33.31s
```

`grep -l skipped` over all 37 logs: no match. (test_claim_exclusivity_postgres.py: 1 xfailed, pre-existing, not a skip.)

## Tasks 6–10 unit/Python joins at base

```
test_admin_route_authorization_inventory.py (Task 9): 28 passed
test_graph_lifecycle_playwright_contract.py (Task 10 Python join): 145 passed
test_graph_lifecycle_stage_attribution.py (Task 6 tripwire): 17 passed
test_packaged_release_loader.py (Task 3): 30 passed
test_app_wheel_dependencies.py (Task 5): 5 passed
test_graph_definition_manifest.py generator tests (-k generat): 5 passed (3 generator tests + 2 unrelated 'generated' names)
```

## Playwright journeys: NOT run by the Task 12 implementer

Task 11's conversation journey is being built concurrently (not present at TASK_BASE), and C11 serialises Playwright on port 3000; a parallel run would collide with the Task 11 agent. Task 10's admin journey is frontend-only (page.route replay of a recorded contract) and this task changes no frontend file or recorded contract. The controller must run both journeys serially before accepting Task 12.

Verdict: GREEN on everything run; no RED or skip.
