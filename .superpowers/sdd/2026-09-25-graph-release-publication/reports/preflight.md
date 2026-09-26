# #269 Task 0 preflight — cause baselines at `cd63aa09b` (2026-09-26)

- **HEAD:** `cd63aa09b` = `16aa02b76` (Merge #268) + plan/ledger docs only (no src/tests/frontend diff).
- **Interpreter:** `/Users/robert.whiffin/.pyenv/shims/python` → Python 3.11.0. `PYTHONPATH=<tree>:<tree>/packages/databricks-tellr`.
- **`test ! -e .venv`:** true before and after every backend command below.
- **Unit runs:** `DATABASE_URL=sqlite:////tmp/t269-0.sqlite`, `-p no:randomly -rfEs` (file removed before each run).
- **PostgreSQL:** `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`; each file its own command; the `postgres_engine` fixture creates and drops `tellr_int_<hex>`. The four pre-existing `tellr_int_*` databases (`0da9e060…`, `5a18c26f…`, `6f336988…`, `ac9b0f3b…`) were listed before the runs and **not** touched; `ai_slide_generator` was never connected to.
- **Frontend:** `frontend/node_modules` was absent in this worktree; symlinked to `.worktrees/issue-260-bootstrap/frontend/node_modules`, exactly as the #267/#268 worktrees do (same `package-lock.json` hash as #268's tree). No `npm install`. The link path is gitignored (`.gitignore:98`). No Playwright.

## 1. Focused unit (plan Step 3 list + #266/#267/#268 unit files, C52)

Files: `test_graph_configuration_bootstrap.py test_graph_configuration_draft.py test_graph_configuration_models.py test_graph_definition_content_mapping.py test_agent_definition_workbench_routes.py test_conversation_pin_creation.py test_persisted_graph_release.py test_ci_collects_integration_tests.py test_agent_test_workbench.py test_draft_readiness_client_join.py test_test_run_failure_contract_client_join.py test_endpoint_name_policy_client_join.py`

**Result: 1009 passed, 0 failed, 0 skipped.** Cause set: ∅.

## 2. PostgreSQL, one command per file (plan Step 3 + C27 additions)

| File | Result | Skips |
|---|---|---|
| `test_graph_configuration_bootstrap_postgres.py` | 3 passed | 0 |
| `test_graph_configuration_constraints_postgres.py` | 66 passed | 0 |
| `test_agent_definition_workbench_postgres.py` (hosts #263–#268 PG tests, incl. C13's `test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight` :2272) | 49 passed | 0 |
| `test_agent_schema_overlay_postgres.py` | 10 passed | 0 |
| `test_conversation_pin_creation_postgres.py` | 2 passed | 0 |
| `test_mixed_release_creation_postgres.py` | 14 passed | 0 |
| `test_conversation_pin_acceptance_postgres.py` | 1 passed | 0 |
| `test_persisted_graph_runtime_failures_postgres.py` | 7 passed | 0 |
| `test_conversation_pin_migration_postgres.py` (C27) | 1 passed | 0 |
| `test_conversation_creator_exclusions_postgres.py` (C27) | 4 passed | 0 |
| `test_mixed_release_collaboration_acceptance_postgres.py` (C27) | 26 passed | 0 |

**Zero skips in every file; no blocker.** Cause set: ∅. (#268's final gate recorded workbench 49, constraints 66, runtime failures 7, mixed-release 26, bootstrap 3, overlay 10 — identical.)

## 3. Full unit suite (once)

**6 failed, 6784 passed, 110 skipped, 136 warnings (490 s).** Identical totals to #268's whole-branch gate (6 / 6784 / 110).

Failing nodes and first causal line — **the known integration baseline of 6, same nodes, same causes:**

| Node | First causal line |
|---|---|
| `tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available` | `AssertionError: assert 'provisioned' == 'autoscaling'` |
| `tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails` | `AssertionError: Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.` |
| `tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict` | `AttributeError: '_FakeSession' object has no attribute 'execute'` |
| `…::test_create_session_still_stores_a_single_authority_config_unchanged` | `AttributeError: '_FakeSession' object has no attribute 'execute'` |
| `…::test_create_session_still_accepts_no_agent_config` | `AttributeError: '_FakeSession' object has no attribute 'execute'` |
| `tests/unit/test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session` | `src.services.conversation_pins.ConversationGraphReleaseIntegrityError: no active Graph Release` |

Causes: (A) autoscaling-deploy mock ×2; (B) chokepoint `_FakeSession.execute` ×3 (fake predates #261's pin lock); (C) persistence boundary "no active Graph Release" ×1. **No new cause.** Any #269 regression check diffs against {A×2, B×3, C×1} by node **and** first line.

Skips by reason (110 total — none in any file #269 touches):

| Count | Reason |
|---|---|
| 105 | requires node, `services/pptx-emit-huashu/node_modules` (run setup.sh) and a local Chrome/Chromium |
| 1 | RLIMIT_AS not enforced on macOS; verified on Linux Apps runtime |
| 1 | RC6 subsumed by row-per-slide persistence on the graph path (monolith coverage in `test_slide_editing_robustness.py`) |
| 1 | RC3 has no graph-path counterpart (monolith coverage in `test_slide_editing_robustness.py`) |
| 1 | RC14 has no graph-path counterpart (monolith coverage in `test_add_position_bug.py`) |
| 1 | could not import `opentelemetry.exporter.otlp.proto.grpc._log_exporter` |

## 4. Frontend

- `npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench`: **6 files, 622 passed**, 0 failed.
- `npm run typecheck` (`tsc -b`): **exit 0**, clean.
- `git status --short` clean afterwards (the symlink and tsc output are ignored).

## Verdict

Baseline cause set = the known 6 (A×2, B×3, C×1); every focused, PostgreSQL and frontend gate is GREEN with zero skips. Re-derive after Task 4 (C14 trigger DDL) and after any ORM change.
