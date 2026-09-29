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

## Task 3 — Literal codes grep (frontend/src and src/api)

Grepped `frontend/src` and `src/api` for `endpoint_name_mismatch`, `endpoint_not_ready`, and `endpoint_update_*`. **Zero matches found** in either location. The codes are consumed only in Python test assertions (which are being replaced). Decision: keep all old codes in the `EndpointValidationCode` Literal — removing Literal members could break any future enum consumer or serialised payload that uses those string values.

Old codes kept (no active users found): `endpoint_name_mismatch`, `endpoint_not_ready`, `endpoint_update_in_progress`, `endpoint_update_failed`, `endpoint_update_canceled`.

---

## Task 3 — Deleted READY/NOT_UPDATING cases from `_remote_table_cases`

The following cases were removed from `_remote_table_cases` in `tests/unit/test_graph_configuration_draft.py` because the new Gateway lookup no longer checks endpoint state or name echo:

| id | old code | old message |
|---|---|---|
| `name-mismatch` | `endpoint_name_mismatch` | "Endpoint validation did not return the exact requested name." |
| `not-ready` | `endpoint_not_ready` | "Endpoint is not ready for invocation." |
| `update-in-progress` | `endpoint_update_in_progress` | "Endpoint configuration update is in progress." |
| `update-failed` | `endpoint_update_failed` | "Endpoint configuration update failed." |
| `update-canceled` | `endpoint_update_canceled` | "Endpoint configuration update was canceled." |

The deleted cases used `_endpoint_detail` (SDK serving-endpoint `SimpleNamespace` with `.state.ready` and `.state.config_update` fields) which is also deleted. The replacement `_remote_table_cases` covers four Gateway error mappings plus the non-chat-model case.

---

## Task 3 — Bounded-client transport test URL update

`test_bounded_endpoint_catalog_client_turns_a_transport_outage_into_endpoint_unavailable` in `tests/unit/test_model_endpoint_catalog.py` previously asserted:

```
("GET", "https://unit.invalid/api/2.0/serving-endpoints/exact endpoint name")
```

After Task 3 the implementation calls `api_client.do("GET", "/api/ai-gateway/v2/endpoints/exact endpoint name")` (since `"exact endpoint name"` is not a `system.ai.` name, `gateway_endpoint_name` returns it as-is). Updated assertion:

```
("GET", "https://unit.invalid/api/ai-gateway/v2/endpoints/exact endpoint name")
```

The pre-pass note "keep the bounded-client tests at :375-480 as they are" applied to Task 2 only; Task 3 necessarily changes the URL being validated.

---

## Task 4: service builder name

The brief's `_service()` placeholder does not exist in `tests/unit/test_graph_configuration_draft.py`. The real no-remote builder there is **`GraphConfiguration()`**. Its `remote_endpoint_validator` defaults to `None`, so `_validate_remote_endpoint` returns without making a remote call. The new tests use `GraphConfiguration()`.

## Task 4: `system.ai.a` is refused on purpose

`^system\.ai\.[a-z0-9][a-z0-9._-]*[a-z0-9]$` needs at least two characters after the prefix: one leading and one trailing alphanumeric. So `system.ai.a` is refused and `system.ai.a1` is accepted. This follows directly from the spec §5.2 regex and is kept deliberately. `test_validate_gateway_model_name_refuses_other_shapes` pins it.

## Task 4: precedence relative to the stale-lock check

> **SUPERSEDED by the controller ruling (Task 4, fix round 1, I-1) below.** The gateway check now runs after the lock comparison.

The brief says to call the gateway validator right after `_save_local_validators()`, and it is placed there. That position is before the lock-version comparison. A **stale** save that also changes the model to a non-`system.ai.*` name therefore returns 422 `endpoint_not_gateway_model` rather than a 409. This matches the existing precedence, where local validators (URL policy, overlay) already give 422 before 409. The "current" name it compares against is `locked.selected.draft.content`, the row under the lock, which is the latest committed value. Two stale-save fixtures needed a rename because of this ordering (see the table): the stale `loser` save in the Postgres workbench test, and `test_locally_valid_endpoint_plus_stale_lock_is_seven_role_409_with_zero_remote_calls`, which reuses `CUSTOM_ENDPOINT`. Without the rename, each would get a 422 where it asserts a 409.

## Task 4: rulings on tests with ambiguous intent

1. **`test_exact_five_field_save_preserves_every_server_owned_value_and_artifact`** (unit draft `:144`) and **`test_put_save_draft_returns_exact_changed_contract_and_preserves_release`** (routes `:681`) saved `" custom-endpoint-name "`, with leading and trailing spaces, to prove the name is stored byte-for-byte and never trimmed. The new regex refuses any padded name, so a padded changed name can no longer reach storage. **Ruling:** both tests intend to change the model, so the name becomes `"system.ai.custom-endpoint-name"`, and the stored-value assertions (`after.model.endpoint_name == ...` and the route's `definition["model"] == {...}`) are updated to that same literal. Exact storage is still asserted. The no-trim property is now covered by refusal instead: the padded input `" system.ai.claude"` is refused in `test_validate_gateway_model_name_refuses_other_shapes`.
2. **Routes `_CUSTOM_ENDPOINT = "Custom-Endpoint_266"`** (`:3479`): the mixed case proved the name is not case-normalised. Uppercase is now refused, so **ruling:** `"system.ai.custom-endpoint_266"`, which keeps the underscore. Every route assertion on this constant (`validated_names == [...]`, `not in response.text`, stored name) still runs against the new value.
3. **`graph_lifecycle_journey.py` `OPUS`/`SONNET`**: only `SONNET` is saved as a changed model (S06 changes the fixer to it). **Ruling:** rename `SONNET` only. `OPUS` appears only in the fake discovery list and is never a save target, so it is left as `databricks-claude-opus-4-6`.

## Task 4: fixture edits (old → new). No expected code changed and no assertion removed.

| File:line(s) | Old | New | Why |
|---|---|---|---|
| tests/unit/test_graph_configuration_draft.py:3153 | `CUSTOM_ENDPOINT = "custom endpoint name"` | `"system.ai.custom-endpoint-name"` | changed-model fixture shared by the remote-table, stale-409, remote-once, flush-rollback and default-facade tests |
| tests/unit/test_graph_configuration_draft.py:144, 172 | `" custom-endpoint-name "` | `"system.ai.custom-endpoint-name"` | ruling 1; :172 is the stored-name expected literal |
| tests/unit/test_graph_configuration_draft.py:193 | `{"endpoint_name": " changed endpoint "}` | `{"endpoint_name": "system.ai.changed-endpoint"}` | the endpoint-field hash case changes the model |
| tests/unit/test_graph_configuration_workbench.py:107, 111 | `"architect exact endpoint"` | `"system.ai.architect-exact-endpoint"` | save + expected snapshot |
| tests/unit/test_graph_configuration_workbench.py:108, 112 | `"fixer exact endpoint"` | `"system.ai.fixer-exact-endpoint"` | save + expected snapshot |
| tests/unit/test_graph_configuration_workbench.py:134, 144 | `"builder moved"` | `"system.ai.builder-moved"` | save + expected server name |
| tests/unit/test_graph_configuration_workbench.py:211 | `"fine"` | `"system.ai.fine"` | a valid changed name that seeds the lock |
| tests/unit/test_model_endpoint_probe.py:386 | `"architect exact endpoint"` | `"system.ai.architect-exact-endpoint"` | save |
| tests/unit/test_model_endpoint_probe.py:387, 399, 408 | `"builder exact endpoint"` | `"system.ai.builder-exact-endpoint"` | save + expected probe config + identity |
| tests/unit/test_model_endpoint_probe.py:443 | `"moved on"` | `"system.ai.moved-on"` | save |
| tests/unit/test_model_endpoint_probe.py:502 | `"saved mid-probe"` | `"system.ai.saved-mid-probe"` | save |
| tests/unit/test_graph_release_rollback.py:692, 697, 703 | `"databricks-other-endpoint"` | `"system.ai.other-endpoint"` | fixer changes model; the failing-set and expected-calls literals follow it |
| tests/unit/test_agent_definition_workbench_routes.py:681 | `" custom-endpoint-name "` | `"system.ai.custom-endpoint-name"` | ruling 1 |
| tests/unit/test_agent_definition_workbench_routes.py:3479 | `_CUSTOM_ENDPOINT = "Custom-Endpoint_266"` | `"system.ai.custom-endpoint_266"` | ruling 2 |
| tests/unit/test_agent_definition_workbench_routes.py:4190, 4198, 4205 | `"architect exact endpoint"` | `"system.ai.architect-exact-endpoint"` | save + expected |
| tests/unit/test_agent_definition_workbench_routes.py:4191, 4197, 4204 | `"builder exact endpoint"` | `"system.ai.builder-exact-endpoint"` | save + expected |
| tests/unit/test_agent_definition_workbench_routes.py:4356, 4369 | `"moved on"` | `"system.ai.moved-on"` | save + expected server name |
| tests/unit/test_agent_definition_workbench_routes.py:4503, 4516 | `"saved mid-probe"` | `"system.ai.saved-mid-probe"` | save + expected |
| tests/integration/test_agent_definition_workbench_postgres.py:1614 | `"loser endpoint name"` | `"system.ai.loser-endpoint-name"` | stale loser changes the model (precedence note above) |
| tests/integration/test_agent_definition_workbench_postgres.py:1633, 1651, 1665, 1678 | `"winner endpoint name"` | `"system.ai.winner-endpoint-name"` | save + remote-call/stored expected literals |
| tests/integration/test_agent_definition_workbench_postgres.py:1745, 1791 | `"saved while probing"` | `"system.ai.saved-while-probing"` | save + stored expected |
| tests/integration/graph_lifecycle_journey.py:125 | `SONNET = "databricks-claude-sonnet-4-5"` | `"system.ai.claude-sonnet-4-5"` | ruling 3 (S06 changes fixer to SONNET) |
| tests/integration/test_lakebase_contract_failures_postgres.py:565 | `SONNET == "databricks-claude-sonnet-4-5"` | `SONNET == "system.ai.claude-sonnet-4-5"` | stored/pinned-name expected literal follows the journey constant |

---

## Task 4 fix round 1: CONTROLLER RULING I-1 (overrides spec §5.2's "immediately afterwards")

In both `save_editable_model_draft` and `save_draft_content`, the `_gateway_model_name_validator` call now runs **after** the lock-version comparison, meaning after the `DraftSaveConflict` early return. It still runs before `post_stale_validators`, the remote check and the writer.

**Why:** the rule compares the candidate with `locked.selected.draft.content`. For a stale request, that row is another admin's newer value. Take a stale prompt-only save from an admin whose view still shows a `databricks-*` model, made after someone else has moved the draft to `system.ai.*`. Pre-lock, it got a false 422 `endpoint_not_gateway_model`. It must get the 409 conflict. After the lock check, the locked draft is the client's own base. So "changed" means "changed by this request".

**Consequences:**
- A stale save that really does change to a non-`system.ai` name now gets a 409. After reconciling, it gets the 422 on the next save.
- The URL and overlay checks stay pre-lock, and their ordering tests are unchanged. Those checks depend only on the candidate.
- The earlier stale-loser fixture renames are no longer strictly needed. They are kept as valid `system.ai.*` changes.

**Regression tests (both paths):**
- `test_stale_prompt_only_save_on_a_legacy_view_is_a_409_not_a_gateway_422` (I-1);
- `test_saving_the_published_legacy_name_back_over_a_gateway_draft_is_refused` (I-3: "changed" means differs from the draft, not from the published release).

**I-2 (save-path no-normalisation coverage):**
- `test_changing_the_model_to_a_non_gateway_name_is_refused_before_any_write` now also runs over `" system.ai.claude-opus-5-5 "` and `"System.AI.Claude-Opus-5-5"`. Refusing the raw input on both paths proves the save path does not trim or lowercase before validating.
- `test_changing_the_model_to_a_system_ai_name_saves` now also stores `"system.ai.m0.v_2-x.9"` and asserts it comes back byte-for-byte.

**Minor fixes:** M-1, the URL-first test now runs on both paths. M-2, E302 before `_save_model` in `test_graph_release_rollback.py`. The E501 from the rename at routes `:4503` is wrapped.

---

## Task 6 — Integration test retargets (three files, not in brief's git add)

**Brief reference:** Step 4 says "grep tests/ for other tests that patch ChatDatabricks in chat_service for titles. Retarget them to session_naming.build_session_title_model without removing assertions."

**Files retargeted (not in the brief's Step 6 git add list):**

| File | Old patches | New patch |
|---|---|---|
| `tests/unit/test_session_naming.py` (~line 263) | `patch("databricks_langchain.ChatDatabricks")` + `patch("src.core.databricks_client.get_user_client")` | `patch("src.api.services.session_naming.build_session_title_model")` |
| `tests/integration/test_graph_mode_turn.py` (~line 407) | `setattr("src.core.databricks_client.get_user_client", ...)` + `setattr("databricks_langchain.ChatDatabricks", MagicMock())` | `setattr("src.api.services.session_naming.build_session_title_model", MagicMock())` |
| `tests/integration/test_graph_lifecycle_runtime_postgres.py` (~line 385) | same two patches | same retarget |
| `tests/integration/test_architect_reply_is_persisted.py` (~line 227) | same two patches | same retarget |

**Ruling:** All four retargets were included in the Task 6 commit (1a13f5cf5) alongside the four brief-specified files. The old patches worked correctly after Task 6 (the global `databricks_langchain.ChatDatabricks` setattr still intercepted the lazy import in `build_session_title_model`), but the retarget is cleaner and matches the brief's intent.

---

## Task 6 — max_tokens=50 check confirmed safe

**Brief note:** "if one does [another legitimate max_tokens=50], narrow the assertion and record the ruling."

**Actual:** `grep -n "max_tokens=50" src/api/services/chat_service.py` returned exactly two occurrences (lines 1454 and 2009), both at the two title construction sites that Task 6 replaces. No other `max_tokens=50` exists in `chat_service.py`. The test assertion `assert "max_tokens=50" not in source` is safe as written.

---

## Task 7 — vitest now available via run-vitest.sh (Steps 2/5/6 complete)

**Brief reference:** Steps 2, 5, 6 require `npx vitest run`.

**Resolution:** The controller provided `.superpowers/sdd/2026-09-28-ws2a-ai-gateway/run-vitest.sh` which copies the frontend to a temp dir and symlinks `node_modules` from the other checkout. All Steps 2/5/6 were subsequently run and passed.

**Step 2 (new tests fail on old component):**
At 4fe06556d DefinitionEditor + Task 7 test file → 21 failed including:
- `offers no free-text endpoint field` ✗
- `shows the current model when it is not in the discovered list` ✗

**Step 5 (all Admin tests pass):**
Full Admin folder: 990 passed / 0 failed (11 test files). `npx tsc --noEmit` clean.

**Step 6 (sabotage):**
Custom field re-added to DefinitionEditor → `offers no free-text endpoint field` ✗ (2 failed / 222 passed).
Field removed (restored) → 224 passed / 0 failed.

---

## Task 7 — URL policy test deleted (behavior removed)

**Brief reference:** Step 4 says "Every test that typed into the custom field now selects a radio for the same name." The URL-shaped test values (`https://…`, `serving-endpoints/../secrets`, `x?token=abc`) cannot be radio names and the test's behavior (typing a URL into the custom endpoint field and getting a `URL_NOT_ALLOWED` error) is no longer possible since the text input is removed.

**Decision:** Deleted the `it.each(…)('a URL- or path-shaped custom name %j shows…')` test (3 parametrized cases). The `endpointNamePolicyError` function still exists and is unit-tested in `draftEditorState.test.ts`. No behavioral assertion about the UI field was moved to another element because no element accepts URL-shaped free-text entry.

---

## Task 7 — `syntheticSystemModelEndpoints` extended with two system.ai.* entries

**Brief reference:** Step 4 says it is acceptable (and preferable) to move `syntheticSystemModelEndpoints` entries to `system.ai.*` names. Instead of renaming existing entries (which would break many assertions tied to the `databricks-*` names), two new entries were added:

- `{ name: 'system.ai.endpoint-a2', ... }` — needed globally because `editArchitectFiveFields` uses the default catalog and clicks this radio.
- `{ name: 'system.ai.endpoint-b', ... }` — needed in "clears old result" test which uses `defaultCatalogResponse`.

Existing `databricks-*` fixture names are left unchanged. The `SEED_MODEL_ENDPOINT_NAME = 'databricks-claude-opus-4-6'` is still the first entry and is still found (checked) by default. The "current model not in list" test works by filtering it out via `syntheticSystemModelEndpoints.filter((item) => item.name !== SEED_MODEL_ENDPOINT_NAME)`.

---

## Task 7 — Migrated tests list

All tests that used `customEndpoint()` or directly referenced the `'Custom endpoint name'` textbox:

| Test description (abbreviated) | Old element | New element |
|---|---|---|
| `editArchitectFiveFields` helper | `fireEvent.change(textbox, 'endpoint-a2')` | `fireEvent.click(radio('system.ai.endpoint-a2'))` |
| "defaults deterministically to Prompt…" (keyboard nav) | `getByRole('textbox').toHaveValue('databricks-claude-opus-4-6')` | `getByText('Current model').parentElement.toHaveTextContent(…)` |
| "typing and navigation never save…" | `textbox.toHaveValue('endpoint-a2')` | `radio('system.ai.endpoint-a2').toBeChecked()` |
| "saves exactly the five-field candidate…" | `endpoint_name: 'endpoint-a2'` in body assertion | `endpoint_name: 'system.ai.endpoint-a2'` |
| "associates all five 422 messages…" (endpoint-error move) | `textbox.toHaveAccessibleDescription('Endpoint rejected.')` | `radiogroup.toHaveAccessibleDescription('Endpoint rejected.')` |
| "rejects %s as an invalid response…" | `textbox.toHaveValue('endpoint-a2')` | `radio('system.ai.endpoint-a2').toBeChecked()` |
| "exposes Refresh models…" (title + assertion) | title: "…a separate custom endpoint field"; `textbox.toHaveValue(SEED)` | title: "…the current model paragraph"; `getByText('Current model').parentElement.toHaveTextContent(SEED)` |
| "selection copies exactly the item name…" | `customEndpoint().toHaveValue(item.name)` | `getByText('Current model').parentElement.toHaveTextContent(item.name)` |
| "searches locally…" | `customEndpoint().toHaveValue(SEED)` | `getByText('Current model').parentElement.toHaveTextContent(SEED)` |
| "says exactly when no foundation-model endpoint…" | `customEndpoint().toHaveValue(SEED)` | same pattern |
| "a %i failure is an alert…" | `customEndpoint().toHaveValue(SEED)` | same pattern |
| "a newer discovered item never moves the seed…" | `customEndpoint().toHaveValue(SEED/newer)` | same pattern |
| "saves a selected model…" (renamed from "saves a manual exact name…") | `fireEvent.change(customEndpoint(), manual)` + `not.toContain(manual)` | `fireEvent.click(radio(manual))` + `toContain(manual)`; catalog extended locally |
| "binds a server endpoint issue…" (renamed from "binds a typed server endpoint…") | `customEndpoint()` for click, accessible description, identity, value | radiogroup for accessible description and identity; Current model for value; radio clicks |
| "is disabled while the local endpoint is unsaved…" | `fireEvent.change(customEndpoint(), 'Team Manual Endpoint')` | `fireEvent.click(radio('Team Shared Endpoint (EU)'))` |
| "clears an old result…" | `fireEvent.change(customEndpoint(), 'endpoint-b')` and `SEED` | `fireEvent.click(radio('system.ai.endpoint-b'))` and `radio(SEED)` |
| All probe tests with `customEndpoint().toHaveValue(SEED)` | `customEndpoint().toHaveValue(SEED_MODEL_ENDPOINT_NAME)` × 8 | `getByText('Current model').parentElement.toHaveTextContent(SEED_MODEL_ENDPOINT_NAME)` |
| `NAMES_266` label inventory | `'Custom endpoint name'` | `'Current model'` |

---

## Task 7 fix round 2 — I-1 + M-1 (endpoint error when discovery is empty)

**Review finding I-1:** Reviewer sabotage of moving `<FieldError>` back inside `{visibleModels.length > 0 && (...)}` produced 0 red tests. The spec §5.4 requirement "error shows even when discovery returns nothing" had no test guard.

**Fix (DefinitionEditor.tsx):** Added `aria-describedby={endpointMessage ? \`${agentKey}-endpoint-error\` : undefined}` to the "Current model" `<p>` element. This keeps the ARIA connection in place even when `visibleModels.length === 0` and no radiogroup is rendered (M-1 gap closed).

**Fix (AgentDefinitionWorkbench.test.tsx):** Added `'shows the endpoint error and its accessible description even when discovery returns nothing'` test in the Model-tab endpoint discovery section. The test: empty catalog (`catalogResponse([])`), save → 422 with `candidate.model.endpoint_name` error, asserts `role="alert"` visible in panel AND `within(panel).getByText('Current model').parentElement.toHaveAccessibleDescription('Endpoint name was not found.')`.

**Sabotage outputs:**
- (1) `<FieldError>` moved inside `visibleModels > 0` condition: `1 failed | 224 passed` (new test red) ✓
- (2) `aria-describedby` removed from `<p>`: `1 failed | 224 passed` (accessible-description assertion red) ✓
- Restored: `225 passed (225)` ✓

**Full Admin folder:** 991/991 passed (11 files). `tsc --noEmit` clean.

## Task 9 live acceptance

**Status: BLOCKED at step (a), the OBO-title stop condition (spec §4 step 5, brief Step 2).** I did not run steps b–h.

**Deploy (PASS).**
- `gh auth status`: `robertwhiffin` was the active account.
- Publish run 36473449785, `--ref feat/ws2a-ai-gateway`, built 0a4f904ab. Run log line: `Resolved version: version=0.4.3.dev33`. Log also shows `Uploading databricks_tellr_app-0.4.3.dev33-py3-none-any.whl`.
- Ran `./scripts/deploy_local.sh update --env devloop --instance ws2a --profile tellr-dev --from-pypi 0.4.3.dev33`. Deployment 01f1bb745ceb171e8ca53d76a49964a4.
- App state: `app_status.state=RUNNING`, active deployment `SUCCEEDED`. Pip lines name `databricks-tellr-app==0.4.3.dev33 -> -r requirements.txt`.
- The API returned 502 until 19:49:07Z while the startup slide backfill ran, then 200.

**Step (a): conversation L, before publish (FAIL, stop condition).**
- 2026-09-28T19:50:19Z: `POST /api/chat/async` with a first message containing `USE AGENT MODE` (no session_id).
  - Session: `wjLan_1qWaljBcnmbD_hXIik9_vjXhdsuxKlObgwtIQ`. Request: `PuZAVlIscaW3GWVLfSc8nqLGeoiPqlff`.
- Graph turn: it completed at 19:52:39Z with `metadata.engine_mode=graph` and 2 slides. The session has `graph_version=1` (the seeded release, whose model is `databricks-claude-opus-4-6` on every model node). The graph's calls to `.../ai-gateway/mlflow/v1/chat/completions` returned `200 OK`; they run as the service principal through `get_system_client`.
- **OBO title: FAILED.** At 19:50:21Z the title call `POST https://fevm-db-tellr-dev-workspace.cloud.databricks.com/ai-gateway/mlflow/v1/chat/completions` returned **`403 Forbidden`**. The error was `PermissionDeniedError: Error code: 403 - {'error_code': 403, 'message': 'Provided OAuth token does not have required scopes: ai-gateway [ReqId: 3ff8f85b-502c-45d1-b23f-d871afa77d4a]'}`. The app logged `WARNING Failed to generate session title` at `session_naming.py:145`.
- The session title does read "Why teams adopt code review", but the title generator did not produce it. It is the graph's DeckSpec title, written by `deck_level_writer.py:330`: the deck title is the same string. On the monolith path, and on any turn that writes no DeckSpec, the session would keep its default name.
- Cause: the app's `user_api_scopes` are `sql, dashboards.genie, catalog.tables:read, catalog.schemas:read, catalog.catalogs:read, serving.serving-endpoints`. That list comes from `packages/databricks-tellr/databricks_tellr/deploy.py:1677`, and it has no `ai-gateway` scope. So the user token that the Apps proxy forwards is refused by the Gateway. This disproves the spec §4 assumption that a `serving.serving-endpoints` user token is accepted by the Gateway route.
- Caveat: I authenticated to the app with the `tellr-dev-oauth` CLI token as Bearer, not through a browser. The token that reached the Gateway is the one the Apps proxy forwards, which is limited to the app's declared scopes. So a browser user is expected to see the same 403, but I did not check this through a browser.

**Steps b–h: SKIPPED.** The stop condition fired, so I made no draft edits, publishes or rollbacks. The workbench draft is unchanged (lock_version 0) and release v1 is still active.

**Decision needed (user, spec §4):**
1. accept silent title failures; or
2. move both title paths to the service-principal identity; or
3. (not listed in the spec) add the `ai-gateway` user API scope in `deploy.py` and redeploy.

After that decision, re-run Task 9 from step (a).

## Final fix wave

### FW-1: session titles run as the service principal (user decision, 2026-09-29)

- Task 9 step (a) proved the Gateway refuses the app's forwarded OBO user token (403 "Provided OAuth token does not have required scopes: ai-gateway"; `user_api_scopes` in `deploy.py` lack `ai-gateway`). The user chose spec §4 fallback 2.
- `src/api/services/session_naming.py::build_session_title_model` now passes `workspace_client=get_system_client()` (the same SP client as `DatabricksModelAdapter._default_client_factory`). Docstring says why.
- `tests/unit/test_session_naming.py`: the construction test is renamed `test_builds_the_gateway_title_model_as_the_service_principal`, asserts the SP client, and makes `get_user_client` raise if consulted. Both swallow tests are kept (docstring example changed from `UserClientRequiredError` to an SP auth error). Sabotage: `get_user_client()` restored → construction test red (`AssertionError: title model must not use the OBO user client`); restored → 21 passed.
- Docs: spec §1.1 item 4, §3 table, §4 step 5, §8 (code block + dated amendment), §10 (new 2b item: per-user identity on Gateway calls, needs the `ai-gateway` user scope + re-consent), §12 risk row; handover §2 T1/T2 identity cell → SP (ws2a); PRD 2b row gains the per-user-identity item (the PRD 2a row never said OBO). `docs/technical/backend-overview.md` does not mention title identity, so it is unchanged.

### FW-4: discovery filters through the save rule (final-review M-3)

- `list_system_models` now drops any mapped `system.ai.*` name that fails `_GATEWAY_MODEL_NAME` (the regex behind `validate_gateway_model_name`), so the picker never offers a name the save refuses with `endpoint_not_gateway_model`.
- New test `test_list_system_models_drops_names_the_save_rule_would_refuse` (`databricks-trailing_`, `databricks-trailing-`, `databricks-Claude-Upper` dropped; `gemma-3-12b` kept; every offered name passes the validator). Sabotage: filter removed → red (3 extra names); restored → 79 passed.

### FW-3: lifecycle contract re-recorded (final-review M-1)

- `frontend/tests/fixtures/graphLifecycleContract.json` re-recorded with `python -m tests.integration.graph_lifecycle_journey --write-contract …` against local Postgres (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`; `DATABASE_URL` set to a throwaway SQLite file because the module's import path loads `.env` before the conftest guard sees it). `recorded_at_commit` is now 8d68ae534. The diff is ids/timestamps/hashes plus S06's fixer model `databricks-claude-sonnet-4-5` → `system.ai.claude-sonnet-4-5` (10 occurrences, 0 of the old name left). OPUS stays `databricks-claude-opus-4-6` in the discovery list per ruling 3.
- `frontend/tests/e2e/graph-release-admin-journey.spec.ts:44` `SONNET` → `system.ai.claude-sonnet-4-5`, matching the journey constant.
- Consumers: `tests/unit/test_graph_lifecycle_playwright_contract.py` 145 passed; `tests/integration/test_graph_lifecycle_acceptance_postgres.py` 2 passed, 0 skipped; Playwright `graph-release-admin-journey.spec.ts` 8 passed and `graph-release-conversation-journey.spec.ts` 6 passed (run locally, see FW-2 for the runner). Sabotage: old `SONNET` constant against the new contract → admin journey test 4 red (`locator.check` timeout); restored → 8 passed.

### FW-2: e2e workbench spec migrated off the removed textbox (final-review I-1)

- `frontend/tests/e2e/agent-definition-workbench.spec.ts`: all 29 `Custom endpoint name` textbox uses replaced, mirroring the Task 7 vitest migration. New spec-local helpers: `discoveredModel`/`selectModel` (a radio scoped to the active Model tab panel's `Discovered models` group, `exact: true`), `expectCurrentModel` (the panel's "Current model" paragraph, exact text), `discoveryWith`, and `installSentinelCatalog`.
- Typed sentinels became discoverable `system.ai.*` models: `endpoint-a2` → `system.ai.endpoint-a2` (already in the shared fixture; the explicit-Save body literal follows), `endpoint-retained-A`/`-local-B`/`-unselected-A`/`-keep-A`/`-keep-B` → `SENTINEL_MODELS` (`system.ai.endpoint-retained-a`, …), served by `installSentinelCatalog` in the Upgrade-in-flight test and the three 409 families. Every value assertion is kept as a Current-model assertion (plus `toBeChecked` where the old test read a just-typed value).
- The #266 discovery test changes the model to `GATEWAY_NEWER_MODEL` (`system.ai.claude-opus-4-7`, spec-local; the shared `syntheticNewerModelEndpoint` stays `databricks-*` per ruling P2 because vitest uses it for the legacy display). The "manual custom name" test became "selected name": `system.ai.team-exact-endpoint-9` is added to discovery and selected; its five-leaf body, raw-body forbidden-substring sweep, retention, lock and probe assertions are unchanged. The server-validation test uses `system.ai.team-missing-endpoint`/`-found-endpoint` in discovery; the accessible-description and no-remount marker move from the textbox to the radiogroup (as vitest did).
- Removed: `model endpoint URL rejection shows the table message and sends zero PUT and zero probe` (no element accepts free text; the URL policy stays covered by vitest `endpointNamePolicyError` at `AgentDefinitionWorkbench.test.tsx:~2232`). `URL_NOT_ALLOWED` const removed with it. The sweep test's `textbox Custom endpoint name toHaveCount(1)` became `toHaveCount(0)` (the "no free-text field" assertion), plus one `Discovered models` radiogroup and one "Current model" paragraph in the active Model panel (unscoped `getByText` finds 7, one per mounted role editor).
- Run locally (no installs): `.superpowers/sdd/…/run-playwright.sh` (temp copy + symlink to the other checkout's `@playwright/test` 1.57.0; chromium-1200 already cached; refuses if :3000 is busy). Baseline at 3c2138e9f: 78/78. At a4acc95ec+FW-1/3/4: 32 failed / 46 passed (all textbox timeouts). After migration: 77/77 (78 − the removed URL test).
- Sabotage: (S1) `restoreRetained` keeps the current endpoint → 9 red (Upgrade-in-flight, selected-409 ×4, keep-local ×4; the unselected-409 family is not sensitive because its local endpoint already equals the restored one); (S2) a `Custom endpoint name` textbox re-added → sweep red (`Expected: 0 Received: 1`); (S3) radio `onChange` rewrites `system.ai.` → `databricks-` → 25 red including the explicit-Save, discovery, selected-name and server-validation body/Current-model assertions. Product code restored after each (git diff clean).

### Final fix wave verification

- Full `tests/unit` run (xdist, auto workers): 2 failed, 7549 passed, 110 skipped. The 2 failures are baseline Cause B only (`TestGetOrCreateLakebase` x2). Causes A and C did not appear in this run.
- Admin vitest (`run-vitest.sh WORKTREE src/components/Admin`): 991/991 with `--testTimeout=30000`. At the default 5 s it showed 2-3 `Test timed out in 5000ms`, and the set of failing tests changed between runs. Machine load average was about 29-39 (other agents were running). No commit in this wave touches `frontend/src`.
- `tsc --noEmit`: clean for `tsconfig.app.json`, `tsconfig.e2e.json` and `tsconfig.node.json`, checked against the full install.
- Full local e2e run (context only): the workbench spec had 0 failures. The 103 failures are in backend-integration and export specs that need a live API on :8000 or the export sidecar, none of them ws2a surfaces. The CI matrix entry `agent-definition-workbench` is 77/77.
