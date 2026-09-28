# ws2a — plan-vs-code corrections

## Recorded deviations

### Deviation 1 — spec §4 step 5 moved to Task 9

**Plan reference:** spec §4 step 5 (prove OBO titles through the Gateway).

**Deviation:** Cannot run in Task 0, because titles only reach the Gateway after Task 6.
Moved to Task 9 Step 2, with the same stop condition.

---

## Plan-vs-code pre-pass

_Recorded after the origin/main merge on 2026-09-28._

### Pre-pass mismatch 1 — `test_model_endpoint_probe.py:561-660` (Task 1)

**Plan reference:** Task 1 says `tests/unit/test_model_endpoint_probe.py:561-660` for `MockTransportWorkspace` and `_assert_only_the_mock_was_reached`.

**Actual:** The section header comment starts at line 560. `MockTransportWorkspace` class starts at line **588** (not 561). `_assert_only_the_mock_was_reached` starts at line **650**. The range 561–660 correctly encloses both, but implementors should target 588 and 650 directly.

### Pre-pass mismatch 2 — `html_to_google_slides.py:993` (Task 5)

**Plan reference:** Task 5 says `_extract_text` is defined at `html_to_google_slides.py:993`.

**Actual:** `_extract_text` is at line **996** (3-line offset after the merge).

### Pre-pass mismatch 3 — `DefinitionEditor.tsx:526-541` (Task 7)

**Plan reference:** Task 7 says the "Advanced / Custom endpoint name" block is at `:526-541`.

**Actual:** The "Advanced" `<p>` element starts at line **528** (not 526). The block ends at approximately line 540. The range is approximately correct; start offset is 2 lines.

### Pre-pass mismatch 4 — `test_model_endpoint_catalog.py:74-160` (Task 2)

**Plan reference:** Task 2 says replace discovery tests at `:74-160`.

**Actual:** The last discovery test body (`test_list_system_models_keeps_forbidden_and_unavailable_observable`) ends at line **163** (not 160).

### Pre-pass note — `test_model_endpoint_catalog.py:375-480` (Tasks 2-3 bounded-client tests)

**Plan reference:** Task 2 says "keep the bounded-client tests at `:375-480` as they are."

**Actual:** The bounded-client tests span lines **375–480** (last assertion at 480). Confirmed correct.

### Pre-pass note — `graph_configuration_draft.py:444` and `:503` (Task 4)

**Plan reference:** Task 4 says call `_gateway_model_name_validator` after `:444` in `save_editable_model_draft` and after `:503` in `save_draft_content`.

**Actual:** Line 444 is `self._run_candidate_validators(self._save_local_validators(), content)` and line 503 is `self._run_candidate_validators(self._save_local_validators(), validated)`. Both confirmed correct.

### Pre-pass note — `agent_runtime.py:206-245` and `:321-325` (Task 1)

**Plan reference:** `bind_structured_output_model` at `:206-245`; `_default_model_factory` at `:321-325`.

**Actual:** `bind_structured_output_model` starts at line 206. The `@staticmethod` decorator for `_default_model_factory` is at line **321**, the `def` at line **322**. Both confirmed correct.

---

## Baseline failures (pre-bump, post-merge)

_All failures are pre-existing environment or known-baseline causes. None are ws2a regressions._

### Cause A — stale `databricks_tellr` installed package (cannot fix without `pip install`)

The `databricks_tellr` package is installed from `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/` (a different repo clone). That installed version predates the `main` branch additions of `secret_key.py` and the new `_write_app_yaml` parameters. Since `pip install` is prohibited, these tests fail in this environment.

Affected tests:
- `tests/unit/test_deploy_local_preflight.py` — 10 FAILED (all `TestCheckBranchingPreconditions` + 3 `test_fork_*`): `scripts/deploy_local.py` line 36 imports `databricks_tellr.secret_key` which is absent in the installed package.
- `tests/unit/test_deploy_autoscaling.py::TestUpdateDatabricks::test_update_retains_secret_resource_key_for_existing_secret_mode_app` — 1 FAILED: same `secret_key` import error.
- `tests/unit/test_deploy_app_yaml.py::test_app_yaml_has_no_databricks_token` — 1 FAILED: installed `_write_app_yaml` still puts `DATABRICKS_TOKEN` in app.yaml.
- `tests/unit/test_deploy_app_yaml.py::test_app_yaml_includes_secret_block_in_secret_mode` — 1 FAILED: installed `_write_app_yaml` missing `encryption_secret_resource_key` parameter.
- `tests/unit/test_deploy_app_yaml.py::test_app_yaml_never_contains_key_material` — 1 FAILED: same missing parameter.
- `tests/unit/test_deploy_local_secret_mode.py` — 1 ERROR (collection): direct `from databricks_tellr import secret_key` import fails.
- `tests/unit/test_deploy_secret_encryption_key.py` — 1 ERROR (collection): direct `from databricks_tellr import secret_key` import fails.

### Cause B — `TestGetOrCreateLakebase` known baseline (#276)

Autoscaling support not in the installed deploy script. Documented known cause.

- `tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available` — FAILED
- `tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails` — FAILED

### Cause C — xdist parallel worker crash (flaky, not real failures)

Five test files ERROR in the `-n auto` parallel run but pass (36 tests) when run without `-n auto`. These are xdist worker isolation issues, not test failures.

- `tests/unit/test_deploy_local_args.py` — ERROR (xdist only)
- `tests/unit/test_deploy_local_config_branching.py` — ERROR (xdist only)
- `tests/unit/test_deploy_local_instance.py` — ERROR (xdist only)
- `tests/unit/test_deploy_local_owner_grant.py` — ERROR (xdist only)
- `tests/unit/test_deploy_local_schema_setup_sp_only.py` — ERROR (xdist only)

---

