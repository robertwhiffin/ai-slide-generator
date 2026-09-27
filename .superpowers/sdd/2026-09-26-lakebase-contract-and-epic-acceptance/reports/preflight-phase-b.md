# #271 Task 0 phase B — preflight (cause baseline at HEAD)

- **HEAD:** `9a63ab1b7` (`plan/lakebase-contract-acceptance-271`). **INTEGRATION_BASE:** `12a521dc7`. Code-wise, `INTEGRATION_BASE..HEAD` is the three rebased Phase A code commits (`predecessor-heads.md`).
- **Interpreter:** `/Users/robert.whiffin/.pyenv/shims/python` (3.11.0), `PYTHONPATH=<tree>:<tree>/packages/databricks-tellr`, run from inside the worktree. `.venv` was absent before and after. Nothing was installed.
- **Logs:** everything is under `reports/logs/`. They are local evidence and are not committed.

## 1. Full unit suite

**Command:**
```
DATABASE_URL=sqlite:////tmp/t271-0b.sqlite PYTHONPATH=… python -m pytest tests/unit -q -p no:randomly -rfs
```
- It was run from the worktree root, with #271 Task 1's conftest active.
- It ran 15:44:03 → 15:51:38 UTC, so it did not cross midnight.

**Result: 2 failed / 7169 passed / 110 skipped** (445 s).

**Failures by node and first causal assertion.** This is exactly the expected Phase B set, the deploy pair:

| Node | Cause |
|---|---|
| `tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available` | `AssertionError: assert 'provisioned' == 'autoscaling'` |
| `tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails` | `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.` |

- These are the pre-epic baseline: they fail on `main` `f6b1506c5` (P2 / Step A5), and #271 does not touch `deploy.py`.
- The four style-exclusivity nodes from Phase A (the `_FakeSession has no execute` ×3 and `no active Graph Release` ×1) are **absent**, as expected after Task 1.
- No other cause appeared.

**Skips: 110, by cause.** This is the same set as Phase A.

| Cause | Count |
|---|---|
| The huashu PPTX-export tests need node, `services/pptx-emit-huashu/node_modules` and a local Chrome: `test_export_slide_root_depth` 40, `…_slide_root_hostile_realm` 15, `…_accessor_hostile_realm` 15, `…_collection_iteration_hostile_realm` 13, `…_canvas_preflight_hostile_realm` 11, `…_slide_root_background` 7, `test_export_svg_raster` 3, `test_export_inline_svg` 1 | 105 |
| `test_rc_graph_ci.py`: the documented non-applicable RC3, RC6 and RC14 | 3 |
| `test_otel_logging.py`: no `opentelemetry.exporter` | 1 |
| `test_converter_jail.py`: RLIMIT_AS is not enforced on macOS | 1 |

**Deltas since the upstream gates:**
- #270's gate had 6 failed / 7149 passed.
- Here there are 2 failed / 7169 passed. That is +20 passed, which splits into:
  - the 4 style nodes, which now pass;
  - Task 1's and Task 5's new tests;
  - the #270 fix-wave tests.
- The count moved, so the causes were diffed rather than the counts. The only surviving causes are the two deploy causes.

**Live tests are not deselected locally.** There is no `addopts -m "not live"`. `test_dependencies_resolve_on_proxy` (`@live`, `@slow`, network) ran and passed.

## 2. `integration-graph` PostgreSQL files

- **Run:** one invocation per file.
- **Environment:** `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, a per-file SQLite `DATABASE_URL`, `-q -rs -p no:randomly`.
- **Timeouts:** `timeout 900` per file, and `timeout 120` for `test_shared_deck_mutation_attribution.py`.
- **Files:** the 33 files at `test.yml:448-480`.
- **Result:** every file exited 0 with **0 skips**, **549 passed** in total, plus 1 documented xfail.

| File | Passed |
|---|---|
| test_graph_orchestration | 19 |
| test_graph_mode_turn | 39 |
| test_graph_configuration_bootstrap_postgres | 3 |
| test_graph_configuration_constraints_postgres | 66 |
| test_conversation_pin_migration_postgres | 1 |
| test_shared_deck_mutation_migration_postgres | 3 |
| test_shared_deck_mutation_lifecycle_postgres | 4 |
| test_collaboration_history_api_postgres | 30 |
| test_mixed_release_collaboration_acceptance_postgres | 26 |
| test_shared_deck_mutation_attribution (under `timeout 120`; 17.3 s, no hang) | 60 |
| test_conversation_pin_creation_postgres | 2 |
| test_mixed_release_creation_postgres | 14 |
| test_conversation_creator_exclusions_postgres | 4 |
| test_persisted_graph_runtime_failures_postgres | 7 |
| test_conversation_pin_acceptance_postgres | 1 |
| test_agent_definition_workbench_postgres | 49 |
| test_agent_schema_overlay_postgres | 10 |
| test_graph_release_publication_postgres (#269) | 21 |
| test_graph_release_session_ordering_postgres (#269 + #270 T5) | 57 |
| test_graph_release_evidence_postgres (#269) | 18 |
| test_graph_release_publication_acceptance_postgres (#269) | 3 |
| test_graph_release_history_postgres (#270) | 5 |
| test_graph_release_rollback_postgres (#270) | 12 |
| test_graph_release_rollback_ordering_postgres (#270) | 12 |
| test_graph_release_rollback_acceptance_postgres (#270) | 1 |
| test_spec_dirty_marker_routes | 11 |
| test_sweeper_describe_only | 18 |
| test_architect_reply_is_persisted | 9 |
| test_insert_slide_route | 8 |
| test_slide_id_is_durable | 14 |
| test_deck_spec_change_turn | 9 |
| test_spec_row_alignment | 10 |
| test_claim_exclusivity_postgres | 3 (+1 xfailed, pre-existing marker) |

**Databases:**
- The `tellr_int_*` list was identical before and after: the same 5 older databases (`0da9e060…`, `5a18c26f…`, `6f336988…`, `ac9b0f3b…`, `f7551cc4…`).
- Nothing leaked and nothing was dropped.
- `ai_slide_generator` was not touched.

## 3. Frontend

`frontend/node_modules` is the required symlink to `.worktrees/issue-260-bootstrap/frontend/node_modules`. It was present, and I did not create it.

- **Vitest** (`./node_modules/.bin/vitest run`): **21 files / 1099 passed**, exit 0. #270's gate had 1090; the difference is the #270 fix-wave tests.
- **Typecheck:**
  - `tsc --noEmit -p tsconfig.app.json` exits 0, and so does `tsc --noEmit -p tsconfig.node.json`.
  - I did **not** use `tsc -b` or `npm run typecheck`, because either would write tsbuildinfo into the shared `node_modules/.tmp`. The `.tmp` mtimes were unchanged (16:26 local, which predates this run).
  - `tsc --noEmit -p tsconfig.json` checks 0 files (`--listFilesOnly` gives 0). That is Correction 25.
- **`frontend/tests` typecheck (B5, P1 recipe in `/tmp/t271-0b-ts`, TS 5.9.3):**
  - with the C3 config: 10 errors (1 × TS2740 at `findings-drawer.spec.ts:87`, 9 × TS2307);
  - adding the `/src/*` d.ts: **1 error** (the TS2740);
  - adding back `verbatimModuleSyntax`: 35 errors (34 × TS1484, in 29 files).
  - The full list is in Correction 27.
- **ESLint on `frontend/tests`:** 25 errors, 0 warnings, in 12 files, none in the #268–#270 specs (Correction 27). CI has no ESLint job.
- **Playwright was not run**, per the brief. Port 3000 had no listener.

## 4. Re-probe summary

- **Verified code facts.** Every row was re-verified at HEAD.
  - `agent_runtime.py`, `persisted_graph_release.py`, `prompt_assembler.py`, `agent_schema_registry.py`, `agent_runtime_identity.py`, `conversation_pins.py`, `graph/`, `chat.py`, `chat_service.py`, `sessions.py` and `session_manager.py` are byte-unchanged since `a08389ec3`, so their citations stand.
  - These citations moved:
    - the bootstrap manifest read, now `:75-78`;
    - the admin router, now `agent_definitions.py:161-165`;
    - the test-run routes, now `:1183`, `:1214`, `:1243`, `:1263`;
    - `get_agent_test_workbench`, now `:1080`;
    - discovery, now `:179`, `:220`, `:601`;
    - the workbench log site, now `test_agent_test_workbench.py:2010`;
    - `PACKAGED_V1_CONTENT_HASHES`, now `:744`;
    - `integration-graph`, now `test.yml:448-480`.
- **Consumed interfaces.** C268-1 … C270-4 were recorded as built (Correction 35), with five contradictions.
- **Removal inventory.** There is no new caller (Correction 29).
- **Invariant owners.** Recorded in Correction 41.
- **Corrections 24–46** are appended to `PLAN-CORRECTIONS.md`.
