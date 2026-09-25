# Task 5 report — saved-candidate structured-output probe (#266)

**Status:** DONE_WITH_CONCERNS (the concerns are rulings for the controller to confirm; no gate is open)

- TASK_BASE `3c39e9c726dbed5f216f1312dd54d81620910c46`
- Implementation `a602c985776e8e0ec4f24fbcc07596b8cd76ad47`, `feat: probe saved endpoint structured output (#266)`
- This report is the following commit.

## What was built

- **`agent_runtime.py`** adds `bind_structured_output_model(*, model_factory, workspace_client, configuration, schema, transport_options=None)`. It is the only `with_structured_output(` call site. It also adds `saved_model_configuration(ModelConfiguration)`.
  - `DatabricksModelAdapter.invoke` calls the helper inside its unchanged provider catch, so it still collapses `PermissionDenied`.
  - `_run_resolved` uses `saved_model_configuration`, which is a byte-equivalent conversion.
  - `run`'s arity, release selection, #264 composition, #265 assembly and identity-sink ordering are untouched.
- **`model_endpoint_probe.py`** (new) exports the plan's types plus:
  - `DatabricksStructuredOutputProbe`, whose defaults are `DatabricksModelAdapter`'s own factories.
  - `FakeStructuredOutputProbe` and `SavedEndpointProbeResult`.
  - `PROBE_TIMEOUT_SECONDS` and `PROBE_MAX_RETRIES`.
  - It calls `agent_runtime.bind_structured_output_model(...)` and contains no `with_structured_output` or `ChatDatabricks` text.
- **`graph_configuration_draft.py`** gains `read_draft_probe_candidate` and `DraftProbeCandidate`. The method copies the selected role's saved model, hash and lock under `read_workbench`'s FOR SHARE locks inside `with session.begin():`. A stale lock returns the null-candidate `DraftSaveConflict` (it uses `_draft_aggregate_snapshot`). After the transaction ends, it re-runs the policy on the saved name through `_endpoint_name_policy_validator` (C4). It writes nothing, and `_write_locked_content` is not touched. `_validate_common` has its lock and agent-key half split out, with identical issue order. Everything is below `_LEGACY_SOURCE_ROLES` (C19).
- **`graph_configuration.py`** exports `DraftProbeCandidate`.
- **`schemas/agent_definitions.py`** adds `StructuredOutputProbeSuccessResponse` and `StructuredOutputProbeFailureResponse`, strict siblings of `BaseModel` (C9).
- **`routes/agent_definitions.py`** adds `POST /draft/{agent_key}/model-endpoint-probe`:
  - It keeps the router's `require_admin`, adds `require_draft_write_principal`, and resolves the `get_structured_output_probe` dependency.
  - It parses the body with `_parse_lock_request` (strict `DraftLockRequest`).
  - It maps outcomes to 200/403/422/503 and returns 409 through `_conflict_response(outcome, client_candidate=None)`, with a 422 via `_rejection_response`.
  - The service runs in `run_in_threadpool`.

`graph_configuration_workbench.py` is in the plan's list but needed **no change**. The read reuses `read_workbench` as is, and the new method lives in `graph_configuration_draft.py`, where C14 says it naturally belongs.

## Rulings and corrections applied (cost if wrong)

1. **The probe schema and prompt are code-owned (plan wins over the brief's loose wording).** The dispatch described the probe as running "against the role's structured output schema" and asked me to reuse "AgentSchemaRegistry composition and the identity sink". The plan's exact values say the schema is only `result: Literal["ok"]` and the prompt contains no draft content. I followed the plan. So the probe binds `_StructuredOutputProbeResponse`, not the role's composed schema. *Cost if wrong:* the probe would not catch a role schema that one endpoint's function-calling rejects. That would need a follow-up that composes via `AgentSchemaRegistry`, and it would require a prompt able to satisfy that schema.
2. **No identity sink.** `AgentInvocationIdentity` requires a published `graph_release_id` and revision id, and a draft probe has neither. Fabricating them would put fake release rows into the production identity log. The probe logs only its code and the exception class name. *Cost if wrong:* probe attempts are absent from the release-identity trace.
3. **The payload rule (#258) was applied.** `_PROBE_PROMPT` is one constant: `'Reply with the single field result set to the string "ok".'`. The model receives nothing else. A test pins the exact prompt and asserts it carries no role, endpoint, session, turn, release, `@`, lock, hash or user value. There was no conflict with the plan.
4. **The probe's model call is bounded: `timeout=30.0`, `max_retries=0`.** It holds no lock, so C8's convoy reason does not apply. But it runs inside one admin HTTP request, and the openai client's default is 600 s per attempt with retries. Without a bound, a hung endpoint pins a worker thread for tens of minutes. These are transport options passed to the same factory through the helper. The saved sampling values are unchanged, and the runtime passes none (M13 pins that). A timeout is the retryable 503. *Cost if wrong:* a cold scale-to-zero custom endpoint that takes more than 30 s reads as retryable unavailable.
5. **The model call runs off the event loop.** The route is `async` (so it can `await request.json()`), so a synchronous remote call would block every request on that worker. The service therefore runs through `run_in_threadpool`, and a test (M18) guards it. *Cost if wrong:* none known. The SQLAlchemy session is used sequentially from one worker thread.
6. **Classification.**
   - `NotImplementedError` from the **binding step only** is 422 `unsupported_structured_output`.
   - `PermissionDenied` from binding or invocation is 403 `endpoint_probe_forbidden`.
   - Everything else is 503 `structured_output_probe_failed` with `retryable:true`. That covers client-factory failures (including `PermissionDenied` and `NotImplementedError` raised there), every provider or transport error, invoke-time `NotImplementedError`, openai 400, and any output that is not the exact `ok` instance.
   - Messages are code-owned, and exception text is never read.
7. **The saved-name policy re-check (C4) returns the draft 422 envelope, not a probe code.** The response is `candidate.model.endpoint_name` / `endpoint_url_not_allowed`, because the plan's three probe codes don't cover it. Stale takes precedence over the re-check, so a stale request still gets 409.
8. **Route-test harness.** `_app_for` installs a succeeding `FakeStructuredOutputProbe` by default (`probe=`, `production_probe=`), mirroring Task 3's validator default, so no route test reaches Databricks. The existing route-inventory guard `test_main_app_registers_the_dedicated_workbench_route` gained the new path.

## RED (before implementation)

- Both plan commands failed at collection, for the right reason:
  - `ModuleNotFoundError: No module named 'src.services.model_endpoint_probe'`
  - `ImportError: cannot import name 'DraftProbeCandidate'`
- Runtime `-k structured_output` gave 5 failed and 1 passed. The failures were `AttributeError: ... no attribute 'bind_structured_output_model'` and `cannot import name 'saved_model_configuration'`. The one pass is the PermissionDenied-collapse pin, which describes existing behaviour.

## GREEN

- `pytest -q tests/unit/test_model_endpoint_probe.py tests/unit/test_agent_runtime.py -k 'structured_output or model_endpoint_probe'` gave **44 passed**.
- `pytest -q tests/unit/test_graph_configuration_workbench.py tests/unit/test_agent_definition_workbench_routes.py -k 'model_endpoint_probe or auth_before_probe_body'` gave **49 passed**.

## Clause-to-mutation table

- Driver: `/tmp/t266-5/mutate.py`. Raw output is in `/tmp/t266-5/mut-a.txt` and `mut-b.txt`.
- Every row applied to an anchor with count exactly 1, and its marker had `grep -c` = 1 while applied.
- Every file was restored with `git checkout a602c985776e8e0ec4f24fbcc07596b8cd76ad47 -- <file>`. After each restore the marker `grep -c` was 0 and `git status` was clean, and GREEN was re-run.
- No row is free.
- Scope key: **R** = `test_agent_definition_workbench_routes.py -k 'model_endpoint_probe or auth_before_probe_body'`. **PG** = `test_agent_definition_workbench_postgres.py -k model_endpoint_probe`.

| ID / marker | Clause | File | Scope | RED (failing tests) | GREEN after restore |
|---|---|---|---|---|---|
| M1 `T5M1_HOLD_TRANSACTION` | C13: the snapshot transaction ends before the call | draft | wb+probe; PG | 2/52: `…snapshot_releases_its_transaction`, `…service_holds_no_transaction_during_the_call`. PG 1/1: `test_model_endpoint_probe_holds_no_lock_while_the_model_call_is_in_flight` | 52; PG 1 |
| M2 `T5M2_SKIP_STALE` | stale returns 409 before any probe | draft | wb+probe+R | 4/87: route `…stale_lock_is_the_coherent_null_candidate_409`, wb `…stale_lock_is_the_null_candidate_conflict`, wb `…stale_precedes_the_policy_recheck`, service `…stale_lock_conflicts_before_any_probe` | 87 |
| M3 `T5M3_SKIP_POLICY` | saved-name policy re-check (C4) | draft | wb+probe+R | 6/87: route `…policy_recheck_is_the_ordered_422`, wb `…rechecks_the_saved_name_policy[×4]`, service `…rechecks_the_saved_name_policy` | 87 |
| M4 `T5M4_WRONG_ROLE` | the selected role's candidate | draft | wb+probe+R | 3/87: route `…probes_each_selected_roles_saved_candidate`, wb `…exact_saved_candidate`, service `…probes_the_selected_roles_saved_candidate` | 87 |
| M5 `T5M5_REREAD` | identity copied before the call, not re-read | probe | probe+R; PG | 2/73: route `…later_save_cannot_change_the_reported_identity`, service `…copied_identity_after_a_later_save`. PG 1/1 | 73; PG 1 |
| M6 `T5M6_LOOSE_SCHEMA` | schema is only `Literal["ok"]` | probe | probe | 1/38 `…schema_is_only_the_literal_ok_result` | 38 |
| M7 `T5M7_PROMPT_LEAK` | code-owned, identity-free prompt (#258) | probe | probe | 2/38 `…prompt_is_code_owned_and_identity_free`, `…success_constructs_binds_then_invokes_exactly` | 38 |
| M8 `T5M8_UNSUPPORTED_AS_FAILED` | binding `NotImplementedError` → unsupported | probe | probe | 1/38 `…binding_rejection_is_unsupported[not-implemented]` | 38 |
| M9 `T5M9_FORBIDDEN_AS_FAILED` | invoke `PermissionDenied` → forbidden | probe | probe | 1/38 `…permission_denial_is_forbidden[invoke]` | 38 |
| M10 `T5M10_LEAK` | no raw exception text | probe | probe | 20/38, every failure-path case | 38 |
| M11 `T5M11_ANY_OUTPUT_OK` | success only for the exact `ok` instance | probe | probe | 3/38 `…unparsed_output_is_ambiguous_failure[dict,string,wrong-literal]` | 38 |
| M12 `T5M12_UNBOUNDED` | the probe call is bounded | probe | probe | 1/38 `…success_constructs_binds_then_invokes_exactly` | 38 |
| M13 `T5M13_RUNTIME_DRIFT` | the runtime passes no transport options | runtime | test_agent_runtime | 2/37 `test_databricks_model_adapter_never_binds_legacy_tool_grants`, `…runtime_adapter_binds_through_the_extracted_helper` | 37 |
| M14 `T5M14_NO_FLOAT` | the shared saved-configuration conversion | runtime | runtime `-k structured_output` | 1/6 `…saved_configuration_is_the_runtime_conversion` | 6 |
| M15 `T5M15_LAX_BODY` | strict `DraftLockRequest` via `_parse_lock_request` | routes | R | 14/35: `…rejects_every_client_field_but_the_lock[×11]`, `…malformed_bodies…[{not json, {}, []]` | 35 |
| M17 `T5M17_STATUS` | forbidden is 403 | routes | R | 1/35 `…maps_each_typed_failure_exactly[endpoint_probe_forbidden]` | 35 |
| M18 `T5M18_ON_LOOP` | model call off the event loop | routes | R | 1/35 `…calls_the_model_off_the_event_loop` | 35 |
| M20 `T5M20_FAKE_WIRED` | the production dependency is the Databricks probe | routes | R | 1/35 `…production_dependency_is_the_databricks_probe` | 35 |
| M21 `T5M21_SECOND_FACTORY` | no second model factory | probe | runtime `-k structured_output`; R | 1/6 `…probe_defaults_are_the_runtime_adapters_factories`; 1/35 `…production_dependency_is_the_databricks_probe` | 6; 35 |
| M22 `T5M22_WRITE` | the probe writes nothing | draft | wb+probe+R | 4/87: route `…writes_no_row_of_any_kind[success,failure]`, wb `…snapshot_writes_nothing`, service `…writes_nothing_on_success_or_failure` | 87 |
| M23 `T5M23_LIFO` | the fake replays in order | probe | probe | 1/38 `…fake_needs_no_sdk_and_replays_outcomes` | 38 |

**Reserved plan targets.** I did not run these; I only built the guards they should hit.
- `TASK5_CONTROLLER_ENDPOINT_OVERRIDE_SABOTAGE` should hit `test_model_endpoint_probe_route_rejects_every_client_field_but_the_lock[endpoint_name|endpoint]` and the saved-candidate tests.
- `TASK5_REVIEWER_STRUCTURED_BINDING_SABOTAGE` should hit `test_structured_output_runtime_and_model_endpoint_probe_share_one_helper` (a recording monkeypatch of `agent_runtime.bind_structured_output_model`) and the AST and text guard `test_structured_output_binding_has_one_call_site_and_the_probe_has_none`. These are the new probe-side guards C11 asked for.

**Not mutated:** authorization before the body. It is structural, because the router-level `require_admin` resolves before any endpoint dependency. `test_auth_before_probe_body_non_admin_is_denied_without_parsing` pins the observable behaviour (403, `Request.json` never called, probe dependency never resolved, no echo).

## Gates

- **Focused unit set:** probe, runtime, new workbench, routes, draft, catalog, persisted runtime, prompt assembler, schema registry, CI-collects, client join and graph nodes. **989 passed, 0 failed.** One mid-run failure (the route-inventory guard, `assert 7 == 6`) had the expected cause and was fixed in the commit. The routes file alone gives 226 passed.
- **Full `tests/unit -q -p no:randomly -rf`**, started 2026-09-25 about 21:50 UTC: **6 failed / 6127 passed / 110 skipped.** The failures are exactly the baseline nodes and causes: autoscaling ×2 (`'provisioned' == 'autoscaling'`, `Called 0 times`); chokepoint ×3 (`'_FakeSession' object has no attribute 'execute'`); persistence boundary ×1 (`no active Graph Release`). There are no usage-service failures.
- **PostgreSQL** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`), one invocation each, zero skips:
  - `test_agent_definition_workbench_postgres.py`: **17 passed**. That is baseline 16 plus the new C13 proof.
  - `test_persisted_graph_runtime_failures_postgres.py`: **7 passed** (runtime touched).
  - `test_agent_schema_overlay_postgres.py`: **10 passed**.
  - The C13 proof failed once while I wrote it. The observer connection had been handed the probe's released pooled connection, so it counted its own 2 locks. The fix checks out the observer connection first and asserts `probe_pid != observer_pid`. M1 then shows the proof bites.
- **Ruff**, compared with base per file:
  - All six changed `src` files: 0, and 0 at base.
  - `test_agent_runtime.py` and the PG suite: 0, and 0 at base.
  - The two new test files: 0.
  - `test_agent_definition_workbench_routes.py`: 2 (I001 at 1:1 and F401 `SCHEMA_CONTRACT_BUNDLES` at :65), the identical 2 at base. Both pre-exist, and I left them alone.
- **Frontend:** not touched (the probe UI is Task 6). Port 3000 was not used, and `lsof -i :3000` is empty.
- **Hygiene:** `.venv` was absent before and after. There were no installs. The dev database was untouched, because fixtures use throwaway databases. No other worktree was touched. The `T5M` marker count across `src` and `tests` is 0.

## Concerns

1. Rulings 1 and 2 above, on the schema and the identity sink, depart from the dispatch's wording in favour of the plan's exact values. They need the controller's confirmation.
2. An openai 400 on invoke (a likely real-world "this endpoint can't do tools/function-calling" signal) is classified as 503 retryable, as the plan mandates. Task 6's UI will show "Retry" for it. That is plan-correct but may mislead. The whole-branch review may want a user decision on it.
3. The probe bound (30 s, no retry) is my choice, per ruling 4.
4. The facade method validates lock and agent key but takes no `actor`, per the plan's service signature. The route still requires the principal.

## Triple check

`git status --porcelain`, `git diff HEAD` and `git diff --cached` were all empty after the implementation commit and before this report was added.
