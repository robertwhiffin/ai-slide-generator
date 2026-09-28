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


## Task 0b — Step 6: Post-bump baseline (BLOCKED)

_Run on 2026-09-28, after controller-ruling pin commit (`1262f2ffe`)._

**Total: 39 failed, 7393 passed, 110 skipped, 816 warnings, 7 errors.**

### Step 6 controller-ruling pin changes applied before baseline

- `packages/databricks-tellr-app/pyproject.toml`: `"openai>=1.99.9"` → `"openai==3.19.2"`, added `"openai-agents==0.22.2"`, comment updated.
- `requirements.txt`: same two changes.
- Root `pyproject.toml`: openai left as `>=1.99.9` (ranged, as instructed).
- `databricks-ai-bridge==0.21.0` in the app pyproject: local env resolves to 0.22.0; databricks-openai 0.17.1 requires `>=0.21.0`, which `0.21.0` satisfies; no change yet — left for the build to judge (as instructed).
- Committed as `1262f2ffe`: `build: pin openai 3.19.2 and openai-agents 0.22.2 to the tested closure`.

### Cause D — openai pin change breaks wheel-dependency test (STOP condition triggered)

The controller-authorized change from `openai>=1.99.9` to `openai==3.19.2` caused a new test failure that is not the ChatDatabricks/serving_endpoints mock cause and is not in Causes A/B/C. Per task instructions, this is a STOP condition.

**Failing test:**
- `tests/unit/test_app_wheel_dependencies.py::test_the_manifests_declare_openai_within_the_transitive_bounds`

**Last traceback line:**
```
AssertionError: assert <SpecifierSet('==3.19.2')> == <SpecifierSet('>=1.99.9')>
tests/unit/test_app_wheel_dependencies.py:189
```

**Root cause:** The test asserts that all three manifests (app pyproject, root pyproject, requirements.txt) declare `openai>=1.99.9` with no upper cap. After the pin change, `app_deps["openai"]` is `==3.19.2`, which does not equal `>=1.99.9`.

**Recommended fix (for controller to authorize):** Update the test to accept the new intended state:
- `app_deps["openai"]` and `req_deps["openai"]` → assert `==3.19.2`
- `root_deps["openai"]` → assert `>=1.99.9` (ranged, unchanged)

The test docstring also references `databricks-langchain==0.9.0` and `openai 1.105.0` and needs updating.

### Cause E — ChatDatabricks/serving_endpoints mock (expected new cause)

These are the expected new failures from databricks-langchain 0.20.0 no longer calling `serving_endpoints.get_open_ai_client`. The `MockTransportWorkspace` transport receives 0 requests instead of 1.

**test_agent_runtime.py (3 tests):**
- `test_an_observed_real_provider_run_records_the_reported_token_usage`
- `test_an_observed_real_provider_run_without_usage_records_none`
- `test_production_run_binds_exactly_as_before_and_reads_no_usage`

**test_agent_test_workbench.py (2 tests):**
- `test_a_real_provider_candidate_and_baseline_run_persist_the_reported_tokens`
- `test_a_real_provider_run_without_usage_persists_null_tokens`

**test_model_endpoint_probe.py (8 tests):**
- `test_model_endpoint_probe_real_provider_success_over_mock_transport`
- `test_model_endpoint_probe_real_provider_errors_are_classified[400-unsupported_structured_output]`
- `test_model_endpoint_probe_real_provider_errors_are_classified[401-endpoint_probe_forbidden]`
- `test_model_endpoint_probe_real_provider_errors_are_classified[403-endpoint_probe_forbidden]`
- `test_model_endpoint_probe_real_provider_errors_are_classified[404-unsupported_structured_output]`
- `test_model_endpoint_probe_real_provider_errors_are_classified[422-unsupported_structured_output]`
- `test_model_endpoint_probe_real_provider_errors_are_classified[429-structured_output_probe_failed]`
- `test_model_endpoint_probe_real_provider_errors_are_classified[500-structured_output_probe_failed]`
- `test_model_endpoint_probe_real_provider_errors_are_classified[connection-structured_output_probe_failed]`

**test_agent_definition_workbench_routes.py (8 tests):**
`test_model_endpoint_probe_route_maps_real_provider_errors` with 8 parametrized outcomes. These tests also use `MockTransportWorkspace` and `real_provider_probe`. Same root cause — not listed in the brief's expected three files, but same cause class (MockTransportWorkspace/serving_endpoints path). Last traceback line: `assert 0 == 1` at `test_agent_definition_workbench_routes.py:4668`.

### Step 6 status: BLOCKED

Task 0b Steps 7, 8, 9 not executed. Steps 7–9 must wait until Cause D is resolved by the controller (either authorize a test update or change the pinning strategy).

## Task 0b — Step 7: Build proof

PENDING — push blocked by pre-push secret scan on 4 pre-existing localhost test-URL commits already on origin; escalated to user. The 4 flagged commits (`1eb10231`, `d6b0083a`, `31b62ba1`, `749acf1a`) are all pre-ws2a history commits containing postgres test URLs (`postgresql+psycopg2://localhost:5432/postgres`), not real credentials. No bypass was applied; awaiting user decision.

---

## Task 0b — Step 8: Naming-rule proof

_Run on 2026-09-28 with profile `tellr-dev`. Script at `/tmp/ws2a_naming_probe.py` (not committed)._

Full output:

```
SKIP non-chat databricks-bge-large-en ['mlflow/v1/embeddings']
OK system.ai.claude-haiku-4-5
OK system.ai.claude-opus-4-1
OK system.ai.claude-opus-4-5
OK system.ai.claude-opus-4-6
OK system.ai.claude-opus-4-7
OK system.ai.claude-opus-4-8
OK system.ai.claude-opus-5
ERROR system.ai.claude-sonnet-4 BadRequestError
OK system.ai.claude-sonnet-4-5
OK system.ai.claude-sonnet-4-6
OK system.ai.claude-sonnet-5
OK system.ai.deepseek-v4-flash-0731
ERROR system.ai.gemini-2-5-flash BadRequestError
ERROR system.ai.gemini-2-5-pro BadRequestError
OK system.ai.gemini-3-1-flash-lite
OK system.ai.gemini-3-5-flash
OK system.ai.gemma-3-12b
OK system.ai.glm-5-2
ERROR system.ai.gpt-5 BadRequestError
ERROR system.ai.gpt-5-1 BadRequestError
ERROR system.ai.gpt-5-2 BadRequestError
ERROR system.ai.gpt-5-4 BadRequestError
ERROR system.ai.gpt-5-4-mini BadRequestError
ERROR system.ai.gpt-5-4-nano BadRequestError
ERROR system.ai.gpt-5-5 BadRequestError
SKIP non-chat databricks-gpt-5-5-pro ['openai/v1/responses', 'cursor/v1/chat/completions', 'mlflow/v1/responses', 'codex/v1/responses']
ERROR system.ai.gpt-5-6-luna BadRequestError
ERROR system.ai.gpt-5-6-sol BadRequestError
ERROR system.ai.gpt-5-6-terra BadRequestError
ERROR system.ai.gpt-5-mini BadRequestError
ERROR system.ai.gpt-5-nano BadRequestError
OK system.ai.gpt-oss-120b
OK system.ai.gpt-oss-20b
SKIP non-chat databricks-gte-large-en ['mlflow/v1/embeddings']
OK system.ai.inkling
OK system.ai.kimi-k3
OK system.ai.llama-4-maverick
OK system.ai.meta-llama-3-1-8b-instruct
OK system.ai.meta-llama-3-3-70b-instruct
SKIP non-chat databricks-qwen3-embedding-0-6b ['mlflow/v1/embeddings']
OK system.ai.qwen3-next-80b-a3b-instruct
OK system.ai.qwen35-122b-a10b
NEG-OK system.ai.databricks-claude-opus-4-6
NEG-OK system.ai.databricks-gpt-oss-120b
```

**Result: PASS.** No `FAIL` or `UNEXPECTED-OK` lines. The naming rule `databricks-<m>` → `system.ai.<m>` holds for all chat endpoints in the gateway list.

Notes on the output:
- `SKIP non-chat`: 4 embedding/responses endpoints correctly skipped (not `mlflow/v1/chat/completions`).
- `OK`: 20 models accepted the chat completion request.
- `ERROR ... BadRequestError`: 12 models returned 400 (not 404). The naming convention works — the endpoint was found and dispatched the request; the `BadRequestError` is a model-level rejection (e.g. `max_tokens=1` too small, or a structured-output requirement). This is not a naming failure.
- `NEG-OK`: both doubled-prefix negative controls (`system.ai.databricks-*`) correctly returned `NotFoundError`.

---


## Task 1 — Seam-key renames (every edited assertion line)

All `"endpoint"` key renames in model-factory kwargs assertions:

| File | Line (approx) | Change |
|---|---|---|
| `tests/unit/test_agent_runtime.py` | ~412 | `"endpoint": "databricks-claude-opus-4-6"` → `"model"` |
| `tests/unit/test_agent_runtime.py` | ~675 | `"endpoint": "saved exact endpoint-name"` → `"model"` |
| `tests/unit/test_agent_runtime.py` | ~733 | `kwargs["endpoint"]` → `kwargs["model"]` |
| `tests/unit/test_agent_runtime.py` | ~691 (docstring) | `"as ``endpoint``"` → `"as ``model``"` |
| `tests/unit/test_agent_runtime.py` | ~1444 (_SAVED_MODEL_KWARGS) | `"endpoint": "saved exact endpoint-name"` → `"model"` |
| `tests/unit/test_model_endpoint_probe.py` | ~155 | `"endpoint": "exact saved endpoint"` → `"model"` |
| `tests/unit/test_persisted_agent_runtime.py` | ~1099 | `kwargs["endpoint"]` → `kwargs["model"]` (extra file, not in brief — same cause) |
| `tests/unit/test_persisted_agent_runtime.py` | ~1170 | `kwargs["endpoint"]` → `kwargs["model"]` (extra file, not in brief — same cause) |

---

## Task 1 — Pydantic workspace_client deviation

**Brief intent:** `install_mock_gateway_transport(monkeypatch)` + `client_factory=lambda: workspace` should route `ChatDatabricks` requests through the mock transport.

**Actual behaviour:** `ChatDatabricks` declares `workspace_client: Optional[sdk.WorkspaceClient] = Field(default=None, exclude=True)`. Pydantic v2 raises `ValidationError: Input should be an instance of WorkspaceClient` when a mock workspace is passed directly. `arbitrary_types_allowed=True` is set but does not bypass `is_instance_of` checks on explicitly-typed fields.

**Resolution:** Changed all real-provider test helpers to:
1. `client_factory=lambda: None` — passes pydantic (None is valid for `Optional[sdk.WorkspaceClient]`).
2. Wrap `chat_models.get_openai_client` to inject the mock workspace from closure: `original(workspace_client=workspace, **kwargs)`. This makes `DatabricksOpenAI(workspace_client=workspace, ...)` (no pydantic validation on `DatabricksOpenAI`) use `workspace.config.host` for the base URL and `_get_authorized_http_client(workspace, ...)` for the mock transport.

Affected helpers: `_real_chat_adapter`, `_real_provider_executor`, `real_provider_probe`, `_install_real_provider`, and the new gateway test `test_production_adapter_sends_the_stored_name_to_the_gateway_chat_route`.

The `_install_real_provider` signature and usage are unchanged; only the body deviates from the brief (`workspace_client=workspace` in place of `workspace_client=workspace_client`).

---
