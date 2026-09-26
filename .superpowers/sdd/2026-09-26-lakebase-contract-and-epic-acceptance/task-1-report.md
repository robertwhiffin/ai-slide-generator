# Task 1 report: unit-suite database isolation, and the epic-caused style-exclusivity baseline (#271, Phase A)

- **TASK1_BASE / TASK_BASE:** `0500629354d504315c0e4e6acf44102f8372b8d4`. **TASK_HEAD (code):** `d92eae76d`.
- **Files:** `tests/conftest.py`, `tests/unit/test_unit_suite_database_isolation.py` (new), `tests/unit/test_style_exclusivity_chokepoint.py`, `tests/unit/test_style_exclusivity_persistence_boundary.py`. **No `src/` change.** No production defect found.
- **Drivers and raw output:** `/tmp/t271-1/` (`mutate.py`, `gates.sh`, `pg_files.sh`, `*-RED.txt`, `*-GREEN.txt`, `G*.txt`, `pg-before/`, `pg-after/`).

## (a) Unit runs never reach `ai_slide_generator`

**The conftest (before the first `src` import):**
- It raises `pytest.UsageError("refusing to run tests against the ai_slide_generator dev database (DATABASE_URL=…); unset DATABASE_URL to use a throwaway SQLite database, or point it at a disposable one")` when `DATABASE_URL` contains `ai_slide_generator` (OQ1). Measured: exit 4 with that message.
- When `DATABASE_URL` is unset, **or** is inherited with `TELLR_TESTS_DATABASE_URL_DEFAULTED=1`, it sets `sqlite:///<mkdtemp(prefix=f"tellr-tests-{PYTEST_XDIST_WORKER or 'main'}-")>/tellr-tests.sqlite` and the flag, and registers `atexit` removal. After the gates, 0 `tellr-tests-*` dirs were left.
- Any other explicit `DATABASE_URL` is left untouched.

**Deviations from Correction 4, with measured reasons:**
1. **Correction 4's code does not isolate workers.** xdist workers inherit the controller's environment, so `if "DATABASE_URL" not in os.environ` is false in every worker. Mutation M9 (below) removes the inherited-flag re-derivation, which is exactly Correction 4's shape. gw0 and gw1 then report the **same** file. The re-derive-on-flag clause is what makes the `-n 2` probe pass.
2. `mkdtemp` is used instead of the fixed `/tmp/tellr-tests-{worker}.sqlite`. The worker id stays in the name. A fixed path would be shared by concurrent runs in the other worktrees (#268/#270 agents run now) and would carry a stale schema between runs.
3. `pytest.UsageError` is used instead of `SystemExit`, so pytest reports the reason and exits 4.

**`.env` is a second route to the dev DB.** `src/core/database.py:28` `load_dotenv()` finds the main checkout's `.env`, which contains `DATABASE_URL=postgresql://localhost:5432/ai_slide_generator`. RED showed `_get_database_url()` returning that `:5432` URL, not the code default. Because the conftest always sets `DATABASE_URL`, `load_dotenv` (non-overriding) can no longer apply it.

**Other `DATABASE_URL` setters (grep):**
- `patch.dict(..., clear=True)` in `test_database_autoscaling.py`, `test_lakebase.py`, `test_setup.py` and `test_config_loader.py` restores on exit.
- `test_graph_live_real_model.py:149` uses `monkeypatch.setenv` (live only).
- `test_layer4_multi_worker.py` passes explicit child URLs.
- `test_ws4b_fixture_contracts.py:68`: the child's `setdefault` now inherits the SQLite URL. The file still passes (16 passed).
- No test deletes `DATABASE_URL` to test `_get_database_url` except under `patch.dict(clear=True)`, which restores it.
- CI's unit job is unchanged: it still sets no `DATABASE_URL`.

**Dev-DB dependence confirmed, before and after.** With `DATABASE_URL=postgresql://t271probe@127.0.0.1:1/unreachable_probe`:
- before: 6 failed, the baseline nodes and causes;
- after: 2 failed, the deploy pair only.

Everything else passed. No unit test needs a reachable database. The dev-DB writes came only from best-effort request/usage logging (`request_logging.py:112`, `usage_events.py:47`).

**New tests** (`test_unit_suite_database_isolation.py`). The subprocess tests load the real `tests/conftest.py` via `-p tests.conftest` against a throwaway probe file:
- `test_a_unit_run_never_resolves_the_operator_dev_database` (plan)
- `test_the_default_is_installed_before_any_src_import` (plan)
- `test_each_xdist_worker_gets_its_own_sqlite_file`: `-n 2 --dist each`, both workers report, two distinct `sqlite:///` paths
- `test_an_explicit_database_url_is_left_alone`
- `test_a_database_url_naming_the_dev_database_is_refused`

**RED** (`env -u DATABASE_URL`, before the conftest change): 4 failed, 1 passed.
- `test_a_unit_run_never…`: `'ai_slide_generator' is contained here: postgresql://localhost:5432/ai_slide_generator`
- `test_the_default_is_installed…`: `ValueError: substring not found`
- `test_each_xdist_worker…`: `{'defaulted': None, 'url': 'postgresql://localhost:5432/ai_slide_generator', 'worker': 'gw0'}`
- `test_a_database_url_naming…`: `assert 0 != 0` (the probe ran, 4 passed)
- `test_an_explicit_database_url_is_left_alone` passed: it is the preserved behaviour, green by design.

**GREEN:** 5 passed with `DATABASE_URL` unset, and 5 passed with `DATABASE_URL=sqlite:////tmp/t271-1.sqlite`.

## (b) Style-exclusivity ×4 restored to their original meaning

**RED (baseline, before any change):**
- `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::{test_create_session_normalizes_a_raw_both_set_dict, test_create_session_still_stores_a_single_authority_config_unchanged, test_create_session_still_accepts_no_agent_config}`: `AttributeError: '_FakeSession' object has no attribute 'execute'`. The source is `get_conversation_graph_version` → `_require_active_graph_release`, called by `create_session` after flush (#261).
- `test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session`: `ConversationGraphReleaseIntegrityError: no active Graph Release`.

**Fixes:**
- **Chokepoint.** `_capturing_db` is now a real in-memory SQLite session (`StaticPool`, `create_all`, `GraphConfiguration().bootstrap_v1`). It records `row.agent_config` **as handed to the session**, captured on the session's `before_attach` event. That is the same value the `_FakeSession.add` recorded. The assertions are byte-identical.
- **Persistence boundary.** `GraphConfiguration().bootstrap_v1(session_local)` is added before `create_session`. The assertions are byte-identical.

**Deviation from Correction 17 (read back committed rows).** A read-back would make the chokepoint tests vacuous for their stated subject, `create_session`'s own normalisation. The column's `NormalizedAgentConfig` bind hook heals the stored bytes whatever `create_session` does. Mutation M1 shows this: with `create_session`'s normalisation deleted, the persistence-boundary `create_session` test (which reads bytes back) stays **GREEN**, and only the attach-captured chokepoint test goes RED. So the chokepoint tests capture pre-bind, and the stored-bytes guarantee stays pinned in the persistence-boundary file.

**Cause mapping (Correction 17):**
- All three chokepoint tests failed on the missing `execute`, before reaching any assertion.
- After the fix, each is killed by a distinct mutation: M1, M3 and M2 respectively.
- The persistence test failed on the missing release. After the fix it is killed only when both normalisation layers are removed (M5). Its meaning is "the stored bytes carry one authority when written through `create_session`", and either layer satisfies that.

**GREEN:** both style files give 37 passed.

## Clause-to-mutation table

Every row was run by `/tmp/t271-1/mutate.py <ID>`:
- anchor count 1;
- the `grep -c` of the marker is 1 in each mutated file;
- the whole-file command:
  - STYLE = `DATABASE_URL=sqlite:////tmp/t271-1.sqlite python -m pytest -q -p no:randomly -rf tests/unit/test_style_exclusivity_chokepoint.py tests/unit/test_style_exclusivity_persistence_boundary.py`;
  - ISO = `env -u DATABASE_URL python -m pytest -q -p no:randomly -rf tests/unit/test_unit_suite_database_isolation.py`;
- RED;
- a byte-exact restore (`identical=True`, marker count 0, `git diff --stat -- src` EMPTY);
- GREEN (37 passed / 5 passed).

| ID | Clause guarded | Mutation (marker `T271-MUT-<ID>`) | Cmd | RED: failing tests (cause) | GREEN |
|---|---|---|---|---|---|
| M1 | `create_session` normalises its raw dict (`session_manager.py:733`) | `agent_config = agent_config` | STYLE | 1 failed: chokepoint `test_create_session_normalizes_a_raw_both_set_dict` (`persisted a RAW both-set dict…`; `['slide_style_id','design_system_id'] == ['design_system_id']`) | 37 passed |
| M2 | no config stays `None` (`agent_config.py:300-301`) | `return {}` | STYLE | 1 failed: chokepoint `test_create_session_still_accepts_no_agent_config` (`assert {} is None`) | 37 passed |
| M3 | a single authority is untouched (`agent_config.py:303`) | force `slide_style_id: None` into the dump | STYLE | 1 failed: chokepoint `test_create_session_still_stores_a_single_authority_config_unchanged` (`a style-only config must be persisted untouched`; `[] == ['slide_style_id']`) | 37 passed |
| M4 | column bind hook normalises (`types.py:113`) | `return value` at the top of `process_bind_param` | STYLE | 5 failed: boundary `test_dict_of_model`, `test_raw_orm_attribute_assignment`, `test_bulk_update`, `test_profile_column_is_normalized_too`, `TestNormalizationIsSurgical::test_unknown_keys_survive`. `test_session_manager_create_session` stays green because `create_session` normalises first | 37 passed |
| M5 | both layers (M1 + M4) | both of the above | STYLE | 7 failed: M1's test, M4's 5, and **boundary `test_session_manager_create_session`** | 37 passed |
| M6 | *plan reviewer sabotage*: the boundary fixture's `bootstrap_v1` | `pass` | STYLE | 1 failed: boundary `test_session_manager_create_session` (`ConversationGraphReleaseIntegrityError: no active Graph Release`) | 37 passed |
| M7 | the chokepoint fixture's `bootstrap_v1` | `pass` | STYLE | 3 failed: the three chokepoint `create_session` tests (`no active Graph Release`) | 37 passed |
| M8 | *plan controller sabotage*: the `os.environ["DATABASE_URL"] = …` line | `pass` | ISO | 3 failed: `test_a_unit_run_never_resolves_the_operator_dev_database` (`postgresql://localhost:5432/ai_slide_generator`, via `.env`), `test_the_default_is_installed_before_any_src_import` (`ValueError`), `test_each_xdist_worker_gets_its_own_sqlite_file` | 5 passed |
| M9 | worker re-derivation on the inherited flag | `or False` | ISO | 1 failed: `test_each_xdist_worker_gets_its_own_sqlite_file` (`xdist workers share one SQLite file: gw0 and gw1 → …/tellr-tests-main-5j3u8gmu/tellr-tests.sqlite`) | 5 passed |
| M10 | refusal of `ai_slide_generator` | guard substring → `T271-MUT-M10` | ISO | 1 failed: `test_a_database_url_naming_the_dev_database_is_refused` (the probe ran, exit 0) | 5 passed |

**The plan's corrected sabotage targets:**
- **Controller (M8)** hits `test_a_unit_run_never_resolves_the_operator_dev_database`, as predicted, plus `test_the_default_is_installed_before_any_src_import` and `test_each_xdist_worker_gets_its_own_sqlite_file`.
- **Reviewer (M6)** hits `test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session` with `ConversationGraphReleaseIntegrityError: no active Graph Release`, as predicted.

**Reviewer: targets not yet run by me.** Examples: the `before_attach` capture itself (e.g. capture `{}` instead of `instance.agent_config`); the `mkdtemp` worker prefix (the prefix is cosmetic; the distinctness comes from per-process `mkdtemp`, so a constant prefix alone would stay green by design); and the `-p tests.conftest` load in the probe.

## Gates
`.venv` was absent before and after.

| Gate | Result |
|---|---|
| Full `tests/unit`, `DATABASE_URL` unset, sequential, `-p no:randomly -rfs` | **2 failed** (the deploy_autoscaling pair, same causes), 6634 passed, 110 skipped. Skip set identical to the baseline by file and reason. 6634 = 6625 + 4 restored + 5 new |
| `tests/unit -n 2`, whole tree | **collection ERROR, pre-existing** (see Concerns): "Different tests were collected between gw1 and gw0" |
| `tests/unit -n 2 --ignore=test_agent_definition_workbench_routes.py` + that file alone | 2 failed (deploy pair), 6242 passed, 110 skipped; routes 392 passed. 6242 + 392 = 6634 |
| Unreachable `DATABASE_URL`, after (`-n 4`, same split) | 2 failed (deploy pair), 6242 passed; routes 392 passed |
| 25 `integration-graph` files, one invocation each, `TELLR_TEST_POSTGRES_URL`, `DATABASE_URL` unset (conftest default) | per-file counts identical to the baseline (`progress.md`), **zero skips**; claim_exclusivity keeps its 1 documented xfail |
| 6 unit PostgreSQL modules, one invocation each | brand_text_migration 6, checkpointer 27, ci_exports_postgres_test_url 15, design_system_name_index_limit 11, design_system_partial_name_index 6, spec_dirty_marker 15: zero skips |
| `test_ws4b_fixture_contracts.py` | 16 passed |
| `ruff check` on the 4 files | base (HEAD versions via stdin) clean; after: clean. The new file is `ruff format`ted |

## Concerns
1. **Pre-existing CI breaker, out of Task 1 scope.** It is epic-caused, from #267 `6358cf392`. `tests/unit/test_agent_definition_workbench_routes.py:4797` and `:4829` use `ids=lambda v: str(v)` over function params, so the ids embed `0x…` addresses. Every `pytest -n` run, including CI's `pytest tests/unit -n auto` (`test.yml:137`), errors at collection. It was measured at TASK1_BASE, before this task's changes. The fix is test-only (stable ids) and needs a controller ruling on where it lands.
2. Deviations from Corrections 4 and 17 are deliberate and backed by measurement (M9, M1/M4/M5). The controller should ratify them in `PLAN-CORRECTIONS.md`.
3. The refusal is a substring match, so any `DATABASE_URL` containing `ai_slide_generator` (e.g. `ai_slide_generator_test`) is refused. This is intended by OQ1.
