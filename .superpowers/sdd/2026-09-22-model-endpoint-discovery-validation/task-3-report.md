# Task 3 report: model endpoint discovery route and production PUT wiring (#266)

**Status:** DONE_WITH_CONCERNS (see the end).

- `TASK_BASE=e474e151d40065efc86a0cd9fcd62259f20542b4` (pinned)
- `6332f427d` `fix: map a system client failure to typed endpoint unavailability (#266)`. This is the deferred Task 2 Minor, at the factory.
- `73e5324a2028f6e48c7d8047dd3bee6302d98ab0` `feat: expose model endpoint discovery (#266)`. This is the plan's Task 3 plus the C7 wiring.
- `ae19643fe24fd4580ad0ca925d1e2b92fe0809e0` `test: pin the discovery DTOs as strict siblings (#266)`. It closes the gap that sabotage row S07 found.
- `TASK_HEAD` is the commit that adds this report.

## Files (base..ae19643fe)

| File | Change |
| --- | --- |
| `src/api/schemas/agent_definitions.py` | These are new sibling DTOs, appended at the end of the file (C9). Each subclasses `BaseModel` directly with `extra="forbid"`, and none extends a #263 DTO. `SystemModelEndpointResponse` has `name`, `display_name`, `description` and `docs`. `SystemModelDiscoveryResponse` has `items`. `ModelEndpointCatalogErrorResponse` has `code: Literal["catalog_forbidden","catalog_unavailable"]`, `message` and `retryable`. |
| `src/api/routes/agent_definitions.py` | `get_remote_endpoint_draft_validator()` returns `build_remote_endpoint_draft_validator()`. `get_model_endpoint_catalog()` returns a lazy `_SystemModelEndpointDiscovery`. `GET /model-endpoints` sits directly beneath `/workbench` on the existing admin router. The PUT gains `remote_endpoint_validator: Annotated[RemoteEndpointDraftValidator, Depends(get_remote_endpoint_draft_validator)]` and passes it to `GraphConfiguration(remote_endpoint_validator=...)` for `save_editable_model_draft` only. The only removed lines are the `typing` import and the old facade call. The overlay `ValidationError` prefix catch and the `schema-contract-upgrade` route are byte-identical; only their line numbers moved. |
| `src/services/graph_configuration.py` | Inside `build_remote_endpoint_draft_validator`, a `DatabricksClientError` from `get_system_client()` becomes `EndpointValidationFailure("endpoint_unavailable", "Endpoint validation is temporarily unavailable. Retry the save.", True)` with `from error`. No catalog is built. |
| `tests/unit/test_agent_definition_workbench_routes.py` | `_app_for` installs an accepting `CatalogRemoteEndpointDraftValidator(FakeModelEndpointCatalog)` by default. It also accepts `catalog=`, `remote_endpoint_validator=` and `production_endpoint_validation=`. The main-app route inventory gains the one GET. There are 27 new tests, taking the file from 164 to 191. |
| `tests/unit/test_graph_configuration_draft.py` | One factory-level test for the system-client failure (160 to 161). |
| `tests/integration/test_agent_definition_workbench_postgres.py` | `real_route_stack` installs the same accepting validator override. **This file is outside the plan's list; see concern 1.** |

`mocks.ts` and all frontend files are untouched. Task 3 was backend only. No file joined by C19's text reads or strict-JSON parsing was edited.

## Design rulings

- **Admin before catalog, and admin before body.** Both new dependencies are endpoint parameters, so FastAPI resolves them after the router-level `require_admin`. Neither dependency does any work on its own: the production catalog and the validator build clients only when they are used. The PUT still parses `await request.json()` inside the handler.
- **Only `ModelEndpointCatalogFailure` is mapped.** `catalog_forbidden` maps to 403 and `catalog_unavailable` to 503, each with the exact envelope and a message of `str(failure)`, which is the catalog-owned text. Any other exception propagates as FastAPI's non-leaking 500. OpenAPI documents exactly 200, 403 and 503.
- **Deferred Minor: `get_system_client()` failure.** `get_system_client` documents and wraps every failure as `DatabricksClientError`, so I catch exactly that type and never read its text.
  - **GET → 503 `catalog_unavailable`, retryable, with the catalog's own unavailable message.** The discovery contract has only 403 and 503. A client-construction failure is not a permission verdict from the workspace, and calling it forbidden would require parsing the text. 503 is also what a transport failure already produces.
  - **PUT → 422 `invalid_draft` with one `candidate.model.endpoint_name` / `endpoint_unavailable` issue, using the table's "SDK/transport failure" message and retryable.** The plan says every table result becomes this one ordered 422, and "SDK/transport failure" is the row that describes a client that cannot be built.
  - I made the PUT mapping in the factory rather than the route. A route-level catch around `validate()` would have had to be broad.
- **The discovery client is the bounded one.** I reused `bounded_catalog_workspace_client` (5 s retry window, 3 s per request): it uses the same config and adds no credential source. That keeps an outage-time GET at about 13 s instead of the SDK's 300 s. Cost if wrong: a very slow but healthy `list` call over 3 s would report 503. See concern 2.

## RED (before implementation)

`/tmp/t266-3/red.txt`, plan command `-k 'model_endpoints or endpoint_validation or non_admin'`: **31 failed, 157 deselected**.
- 28 × `AttributeError: module 'src.api.routes.agent_definitions' has no attribute 'get_remote_endpoint_draft_validator'`. The dependency was absent, and `_app_for` references it, so the 7 pre-existing `non_admin` tests are in this group for the same reason.
- 1 × `KeyError: '/api/admin/agent-definitions/model-endpoints'` from the OpenAPI test: the route was absent.
- 2 × `assert 200 == 422`, from `test_endpoint_validation_production_dependency_supplies_the_remote_validator` and `test_endpoint_validation_system_client_failure_is_typed_endpoint_unavailable`. This is the real fail-open state: the production PUT did no remote validation.
- An earlier run also hit 11 × `AgentDefinitionRevision has no attribute revision_id`. That was a bug in my test helper (the column is `id`); I fixed it and re-ran the RED above.

Retroactive RED for the factory fix (`/tmp/t266-3/red-factory.txt`). I swapped in the base `graph_configuration.py`, then restored it byte-exact (md5 `ec4a4f76…` before and after). Result: 2 failed. The draft unit test failed with a raw `DatabricksClientError: SECRET_TOKEN_266`, and the route PUT failed with `assert 500 == 422`. These are exactly the deferred Minor.

GREEN: 31 passed. The full route file is 188, and 191 after `ae19643fe`.

## Clause-to-mutation table

- **Driver:** `/tmp/t266-3/sab.py`, with specs in `/tmp/t266-3/specs.json` and `specs2.json`. Output is in `sab.out` and `sab2.out`.
- **Per row:**
  1. The anchor count is asserted to be exactly 1.
  2. The mutation is applied with its marker, and the marker count is 1.
  3. `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr python -m pytest -q -p no:randomly -rf <scope>` runs.
  4. The file is restored with `git checkout <SHA> -- <file>`, and `git diff <SHA> -- <file>` is 0 lines.
  5. The marker count is 0.
  6. The scope is re-run for GREEN.
- **Marker check:** `grep -c`, not `rg -c`. In this environment `rg` is a shell function wrapping the Claude binary, not a binary on PATH. The count semantics are the same.
- **Restore SHAs:** `73e5324a2028f6e48c7d8047dd3bee6302d98ab0` for S01–S15, and `ae19643fe24fd4580ad0ca925d1e2b92fe0809e0` for the S06/S07 re-run.
- **Scopes:**
  - R is `tests/unit/test_agent_definition_workbench_routes.py`: 188 at 73e5324, 191 at ae19643.
  - D is R plus `tests/unit/test_graph_configuration_draft.py`: 349.
- Every row had anchor count 1, marker 1 after mutation and 0 after restore, 0 restore-diff lines, and a fully GREEN re-run.

| # | Clause | Mutation (marker) | Scope | RED | GREEN |
| --- | --- | --- | --- | --- | --- |
| S01 | C7: the PUT passes the dependency's validator to the facade | `remote_endpoint_validator=None` (`T266_3_S01`) | R | 11: `…production_dependency_supplies_the_remote_validator`, `…system_client_failure_is_typed_endpoint_unavailable`, `…accepted_save_validates_the_exact_submitted_name`, table ×8 (every remote row) | 188 |
| S02 | C7: the production dependency supplies a non-`None` validator | dependency `return None` (`T266_3_S02`) | R | 2: `test_endpoint_validation_production_dependency_supplies_the_remote_validator`, `test_endpoint_validation_system_client_failure_is_typed_endpoint_unavailable` | 188 |
| S03 | Only `ModelEndpointCatalogFailure` is mapped | `except Exception`, which synthesises `catalog_unavailable` (`T266_3_S03`) | R | 1: `test_model_endpoints_unexpected_catalog_error_is_a_nonleaking_500` | 188 |
| S04 | forbidden → 403 exactly | status map forbidden → 503 (`T266_3_S04`) | R | 1: `…catalog_failure_is_only_the_documented_envelope[forbidden]` | 188 |
| S05 | Admin before catalog, body and writer | router `dependencies=[]` (`T266_3_S05`) | R | 9: `test_non_admin_model_endpoints_is_denied_before_the_catalog_is_obtained`, `test_non_admin_endpoint_validation_put_rejects_before_body_catalog_or_writer`, plus 7 pre-existing non-admin tests | 188 |
| S06 | Item has exactly name, display_name, description and docs; no ID | add `id: str \| None = None` to the item DTO (`T266_3_S06`) | R | 2: `…populated_response_is_exact_items_only_and_deterministic`, `…production_dependency_lists_through_the_bounded_system_catalog` (re-run at ae19643: same 2) | 188 / 191 |
| S07 | Envelope DTO `extra="forbid"` | `extra="allow"` on `SystemModelDiscoveryResponse` (`T266_3_S07`) | R | **At 73e5324: 0, free within R.** The route builds DTOs from explicit fields, so this was unobservable. Fixed by `ae19643fe`: 1 failure, `test_model_endpoints_dtos_are_strict_siblings_that_forbid_extra_keys[SystemModelDiscoveryResponse-valid1]` | 191 |
| S08 | Seed and exotic spelling kept exactly | `name=endpoint.name.lower()` (`T266_3_S08`) | R | 2: populated, production-list | 188 |
| S09 | Empty is `200 {"items":[]}` | empty becomes a 503 (`T266_3_S09`) | R | 1: `test_model_endpoints_empty_catalog_is_200_empty_items` | 188 |
| S10 | Discovery uses the bounded system client | pass `system_client` unbounded (`T266_3_S10`) | R | 1: `…production_dependency_lists_through_the_bounded_system_catalog` | 188 |
| S11 | GET: system-client failure becomes a typed 503 | `except LookupError` (`T266_3_S11`) | R | 1: `test_model_endpoints_system_client_failure_is_the_typed_503` | 188 |
| S12 | PUT: system-client failure becomes a typed `endpoint_unavailable` | same, in `graph_configuration.py` (`T266_3_S12`) | D | 2: `test_production_remote_endpoint_validator_maps_a_system_client_failure_to_unavailable`, `test_endpoint_validation_system_client_failure_is_typed_endpoint_unavailable` | 349 |
| S13 | The validator is resolved only by the draft PUT (C6: upgrades do no remote work) | the protected-assembly upgrade resolves the validator (`T266_3_S13`) | R | 1: `test_endpoint_validation_dependency_is_resolved_only_by_the_draft_put` | 188 |
| S14 | The envelope message is the catalog-owned text, with no cause leak | message plus `__cause__` (`T266_3_S14`) | R | 3: envelope `[forbidden]`, `[unavailable]`, `…system_client_failure_is_the_typed_503` | 188 |
| S15 | The discovery dependency is lazy (no client work at resolution) | `__init__` calls `get_system_client()` (`T266_3_S15`) | R | 2: production-list, typed-503 | 188 |

**Not exercised, as instructed.** These are the plan targets `TASK3_CONTROLLER_EMPTY_ON_ERROR_SABOTAGE` and `TASK3_REVIEWER_BODY_BEFORE_AUTH_SABOTAGE`. The guards they will hit are these:
- **Controller target (unavailable returns empty `items`):** `test_model_endpoints_catalog_failure_is_only_the_documented_envelope[unavailable]` asserts 503 and the exact envelope, with no `items`.
- **Reviewer target (typed Pydantic body in the PUT signature):** `test_non_admin_endpoint_validation_put_rejects_before_body_catalog_or_writer`. It sends a truncated, malformed body containing a secret URL, prompt and token, and asserts `403 {"detail":"Admin access required"}`. With a typed body, FastAPI decodes the JSON before dependencies run and returns 422. The pre-existing `test_non_admin_put_rejects_before_body_or_writer_and_does_not_echo_secrets` also applies.

**Deliberately not mutated:**
- **The `_app_for` default override and the PostgreSQL `real_route_stack` override.** Removing either sends PUTs to the real `get_system_client()` under `ENVIRONMENT=production`. That could build a real `WorkspaceClient`, read `~/.tellr/config.yaml` (external-browser OAuth), or call `current_user.me()` over the network. Their necessity follows from S01/S02: the production path is live.

## Gates

`test ! -e .venv` passed before and after every run. The interpreter was `/Users/robert.whiffin/.pyenv/shims/python` with `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr`.

- **Focused.** Command: `pytest -q -p no:randomly -rf tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_graph_configuration_draft.py tests/unit/test_model_endpoint_catalog.py`.
  - Result: **412 passed, 0 failed, 0 skipped**. That is 191 + 161 + 60.
  - The plan's Task 3 files are the routes test (plus the schema and route modules it covers).
- **Full unit.** Command: `pytest tests/unit -q -p no:randomly -rf`, started 19:11 UTC, which is not near midnight.
  - Result: **6 failed, 6008 passed, 110 skipped, 136 warnings**.
  - The 6 failures are exactly the baseline nodes and causes:
    - `test_deploy_autoscaling.py::TestGetOrCreateLakebase` ×2: `assert 'provisioned' == 'autoscaling'` and `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
    - `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint` ×3: `'_FakeSession' object has no attribute 'execute'` at `conversation_pins.py:79`.
    - `test_style_exclusivity_persistence_boundary.py::…::test_session_manager_create_session`: `no active Graph Release` at `:83`.
  - Passed is 5980 plus 28 new tests. Skips and warning count are unchanged.
- **PostgreSQL.** `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, with one `-rfs` invocation per file:
  - `test_agent_definition_workbench_postgres.py`: **16 passed, 0 skipped**.
  - `test_agent_schema_overlay_postgres.py`: **10 passed, 0 skipped**, run as an extra check of the shared route stack.
  - The plan names no other PostgreSQL file for Task 3. The dev database was untouched.
- **ruff check** on each of the 6 changed files at HEAD versus base (`git show e474e151d…:<f> | ruff check --stdin-filename <f> -`):
  - 5 files are clean on both sides.
  - `tests/unit/test_agent_definition_workbench_routes.py` has the identical pre-existing pair on both sides: I001 at `:1` and F401 `SCHEMA_CONTRACT_BUNDLES`, which moved from line 64 to 65.
  - No new finding. `ruff format` was not run and is not claimed.
- **Triple check:** `git status --porcelain`, `git diff HEAD` and `git diff --cached` were all empty after the sabotage runs and the gates.

## Concerns

1. **Scope: one file outside the plan's list.** The C7 wiring makes every shipped-router PUT validate remotely, and the PostgreSQL `real_route_stack` builds the shipped router with `ENVIRONMENT=production`. Without an override its PUTs would reach the real system client. I added the same accepting fake override, which is 8 lines, test-only. The alternative was to leave the PostgreSQL suite depending on live workspace credentials.
2. **The discovery GET uses the bounded client** (3 s per request, 5 s retry window), by my ruling above. The ruling that justified these values (C8) was about the draft lock, which a GET does not hold. If `serving_endpoints.list()` on a large workspace can take more than 3 s, discovery will report 503 while the workspace is healthy. The one-line change is to pass `get_system_client()` directly, which is what the S10 mutation does; the production-list test would need its expected call list updated.
3. **Construction failures are caught narrowly, as `DatabricksClientError` only.** That is `get_system_client`'s documented wrapper. A failure raised inside `bounded_catalog_workspace_client` or the `WorkspaceClient(config=…)` constructor would still be a 500. Neither does I/O or auth, and I measured nothing that raises there.
4. **`_SystemModelEndpointDiscovery` repeats the unavailable message literal** from `model_endpoint_catalog.py`, and the factory repeats the `endpoint_unavailable` literal. I did this so as not to refactor the Task 1/2 module. Tests pin both strings exactly, so drift would go RED.
5. **Carried forward, not addressed:** the Retry-After and OAuth-refresh windows (C8), and the broad `RuntimeError` in `_TRANSPORT_FAILURES`, both from Task 2's review.

## Fix round 1

**Base:** `4667d5b16f964c5fc2e9681f50dfba78795bbefb`, pinned. It is the controller's docs ledger commit.

**Fix commit:** `9a75d86fbd6f8befcaf35660f6499354b50ceb5d`, "fix: give endpoint discovery its own finite client bound (#266)".

**I1: discovery reused the save path's 3 s / 5 s bound.**

This was implemented as ruled:
- `model_endpoint_catalog.py` adds `DISCOVERY_RETRY_TIMEOUT_SECONDS = 30`, `DISCOVERY_HTTP_TIMEOUT_SECONDS = 30` and `bounded_discovery_workspace_client`.
- `bounded_catalog_workspace_client` (the save path, still 5 s / 3 s) and the new function now share one private `_derived_workspace_client`. It does `config.copy()`, re-dicts `_inner`, then sets the two timeouts. No credential source is added and the system client is never modified.
- The discovery route now calls `bounded_discovery_workspace_client`.
- The factory in `graph_configuration.py` is unchanged and still uses the save bound.

The test gap is closed:
- Both production-wiring route tests no longer stub the bound:
  - `test_model_endpoints_production_dependency_lists_through_the_bounded_system_catalog`
  - `test_endpoint_validation_production_dependency_supplies_the_remote_validator`
- Each one now does the following:
  - derives the client from a real offline PAT `WorkspaceClient`, stubbing only `Config._resolve_host_metadata`, as the catalog tests already do;
  - records the workspace client passed to `DatabricksModelEndpointCatalog`;
  - asserts its own bound through `_assert_bounded_derivation`: 30/30 for discovery and 5/3 for the save;
  - asserts the same host and the same `_header_factory`;
  - asserts the system client's `_inner` is unchanged and its `retry_timeout_seconds` and `http_timeout_seconds` are still `None`.
- A new catalog test pins both bounds side by side, with separate `_inner` mappings: `test_bounded_discovery_client_has_its_own_finite_bound_and_leaves_the_system_client_unchanged`.
- `test_graph_configuration_draft.py::test_production_remote_endpoint_validator_uses_a_bounded_system_client` still stubs the bound, which was not in the ruling's scope. The save bound's values are now pinned at route level and catalog level.

**RED before the fix.** I ran the new tests with the base sources swapped in, then restored them byte-exact (md5 `4d395152…` and `24315acb…` before and after).
- `test_model_endpoints_production_dependency_lists_through_the_bounded_system_catalog` failed with `AssertionError: assert 5 == 30`.
- The save-wiring test passed, which is correct: the save bound was already right.
- `test_model_endpoint_catalog.py` failed at collection with `ImportError` on `bounded_discovery_workspace_client`, because the symbol did not exist yet.

**Sabotage: swap the two paths' constants.** Driver `/tmp/t266-3/sab.py`, spec `/tmp/t266-3/fr1.json`, output `/tmp/t266-3/fr1-sab.out`.

| Step | Result |
| --- | --- |
| Mutation | In `src/services/model_endpoint_catalog.py`, the save helper passes `DISCOVERY_*` and the discovery helper passes `CATALOG_*`. One anchor spans both bodies, with the marker `T266_3_FR1_SWAP`. |
| Anchor count | exactly 1 |
| Marker count (`grep -c`) | 1 after the mutation, 0 after the restore |
| Scope | the routes, catalog and draft test files (413 tests) |
| RED | **5 failed**: both route tests (`test_endpoint_validation_production_dependency_supplies_the_remote_validator`, `test_model_endpoints_production_dependency_lists_through_the_bounded_system_catalog`), plus `test_bounded_discovery_client_has_its_own_finite_bound_and_leaves_the_system_client_unchanged`, `test_bounded_endpoint_catalog_client_reuses_system_credentials_and_leaves_it_unchanged` and `test_bounded_endpoint_catalog_client_turns_a_transport_outage_into_endpoint_unavailable` |
| Restore | `git checkout 9a75d86fbd6f8befcaf35660f6499354b50ceb5d -- src/services/model_endpoint_catalog.py`, then a 0-line diff |
| GREEN | 413 passed |

**Worst-case wall clock for discovery.** This is arithmetic from the SDK 0.112 `retried` loop and was not measured. The loop starts a new attempt only while `clock.time() < deadline`, where the deadline is 30 s. Between attempts it sleeps `min(10, attempt) + random()`, and that sleep is counted inside the deadline. `requests`' `timeout=30` applies separately to the connect and to each read gap.

| Scenario | Wall clock |
| --- | --- |
| Refused connections (fast failures) | about 30 s, plus at most one final fast attempt |
| One hung read | about 30 s. The next attempt starts at about 31–32 s, after the deadline, so it never starts. |
| Worst case: an attempt starts just before 30 s, then its connect and read both hang to their 30 s timeouts | about 30 + 30 + 30 ≈ 90 s |
| The same, with a connect that succeeds quickly | about 60 s |

The reviewer's estimate of about 30–60 s covers every case except the connect-plus-read double hang.

Two things remain unbounded by configuration, as for the save path (C8):
- a server-supplied `Retry-After` sleep;
- a response that keeps trickling bytes, which resets the read timeout on each gap.

**Gates:**
- **Environment:** `.venv` was absent before and after.
- **Focused.** Command: `pytest -q -p no:randomly -rf tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_model_endpoint_catalog.py tests/unit/test_graph_configuration_draft.py`. Result: **413 passed**, which is 191 + 61 + 161.
- **Full unit.** Command: `tests/unit -q -p no:randomly -rf`, started at 19:41 UTC. Result: **6 failed, 6009 passed, 110 skipped, 136 warnings**. The 6 failures are exactly the baseline nodes and causes:
  - autoscaling ×2: `'provisioned' == 'autoscaling'` and `…provisioned to have been called once. Called 0 times.`
  - `_FakeSession.execute` ×3, at `conversation_pins.py:79`
  - no active Graph Release ×1, at `:83`
- **ruff check**, HEAD against base `4667d5b16` on the 4 changed files:
  - 3 files are clean on both sides.
  - The routes test file shows the same pre-existing I001/F401 pair on both sides.
  - One new E501 that I introduced was fixed before the commit.
  - `ruff format` was not run and is not claimed.
- **PostgreSQL:** not re-run. No PostgreSQL-exercised code path changed, because `real_route_stack` overrides the validator and the PostgreSQL suites do not call discovery.
