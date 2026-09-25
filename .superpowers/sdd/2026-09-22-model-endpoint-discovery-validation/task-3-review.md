# Task 3 review: discovery GET and the PUT's production validator wiring (#266)

- Reviewer: independent task reviewer
- Range: `e474e151d..17f4f343c` (HEAD `4667d5b16` adds the docs-only ledger commit)
- Temporary mutation worktree: `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-266-3` at `17f4f343c`. It has been removed; `git worktree list` no longer shows it.
- `test ! -e .venv` passed before and after, in both trees. The review worktree's `git status --porcelain` was empty at the end.

## Spec Compliance: ✅ (with one ⚠️)

| Requirement | Verdict | Evidence |
| --- | --- | --- |
| GET `/model-endpoints` sits beside `/workbench` on the admin router | ✅ | `routes/agent_definitions.py:452-482`; the router `dependencies=[Depends(require_admin)]` is at `:65` |
| The catalog is obtained through a dependency after `require_admin` | ✅ | `get_model_endpoint_catalog` `:121` is an endpoint parameter, so router dependencies resolve first. `test_non_admin_model_endpoints_is_denied_before_the_catalog_is_obtained` checks both the production and the injected dependency |
| Only `ModelEndpointCatalogFailure` is mapped, to the exact 403/503 envelope | ✅ | `:466-469`, `_catalog_failure_response` `:128-138`. An unexpected error stays a non-leaking 500 (tested) |
| Populated responses are exactly items-only; empty is `200 {"items":[]}`; the seed spelling is exact; the output is deterministic | ✅ | tests at `:3432+` |
| The item DTO carries no task, provider or ID | ✅ | `schemas/agent_definitions.py:448-460` |
| C9: strict sibling DTOs, no field added to the #263 DTOs | ✅ | All three classes subclass `BaseModel` directly with `extra="forbid"`. The diff touches only the end of the schemas file. `test_model_endpoints_dtos_are_strict_siblings_that_forbid_extra_keys` pins `__mro__[1] is BaseModel` |
| C7: the PUT validator comes through a dependency after `require_admin`, for `save_editable_model_draft` only | ✅ | `:490-492`, `:536-538`. The other four `GraphConfiguration()` sites are unchanged (`:442, :582, :622, :662`) |
| C7: a wiring test goes RED when `None` is passed | ✅ | The implementer's S01 (`remote_endpoint_validator=None`) gives 11 RED and S02 (dependency returns `None`) gives 2 RED. The guard is `test_endpoint_validation_production_dependency_supplies_the_remote_validator` (`tests:3941`), which runs the **real** dependency (`production_endpoint_validation=True`) with only the SDK seams stubbed |
| `_app_for` default fake | ✅ | `tests:150-185`. The accepting fake is the default, and the production path is reachable by an explicit flag used by 3 tests |
| Admin before body on the PUT; raw `await request.json()` parsing is kept | ✅ | Reviewer sabotage below |
| The overlay `ValidationError` prefix catch and the `schema-contract-upgrade` route are not reordered | ✅ | The diff hunks on the route file touch only the imports, the new helpers, the new GET, the PUT signature and the PUT's facade call. The overlay catch (`:514-519`) and the schema-upgrade route (`:604-643`) have no changed lines |
| Main-app route inventory | ✅ | `tests:610` adds exactly `{"GET"}` for `/model-endpoints`, and the prefix count assertion keeps the inventory closed |
| GET workbench and the generic tools routes never invoke this catalog | ✅ | `test_model_endpoints_catalog_is_never_invoked_by_workbench_or_tools_routes` |
| ⚠️ Controller ruling (progress.md, Task 3): discovery has its own finite bound (http 30 s, retry 30 s) | **Not implemented** | Discovery reuses the save path's 3 s/5 s client. See I1 |

## Strengths

- The C7 fail-open guard exercises the real dependency, not a fake. The call-chain assertion `system → bounded(system) → catalog(bounded)` plus a 422 means a forgotten wire, a `None` return or a bypass of the bounded client all go RED.
- The non-admin PUT test is strong. It sends a truncated body and a well-formed secret body, each under both the production dependency and a recording dependency. It asserts no dependency resolution, no system-client build, no writer call, and no echo of the secrets.
- Only the documented type is caught (`DatabricksClientError`), on both the GET and the PUT. Its text is never read, and a leak of `SECRET_TOKEN_266` is tested.
- The implementer's 15-row mutation table is anchored and restored byte-exactly. It also caught and fixed a real test gap (S07, `extra="allow"` was unobservable).
- The PostgreSQL `real_route_stack` override is necessary, and the test-only scope expansion was the right call. I proved the necessity below.

## Issues

### Critical

None.

### Important

**I1: Discovery uses the save path's lock-driven 3 s/5 s bound, not its own.** Location: `src/api/routes/agent_definitions.py:115-117` (`_SystemModelEndpointDiscovery.list_system_models` calls `bounded_catalog_workspace_client`) and `src/services/model_endpoint_catalog.py:110-126`.
- **What is wrong.** The 3 s/5 s bound exists because of C8, where remote I/O happens under the exclusive draft `FOR UPDATE` lock. The discovery GET holds no lock, so that justification does not apply to it. `serving_endpoints.list()` returns every serving endpoint in the workspace, not only foundation models, so it is the call most likely to exceed a 3 s per-request timeout on a large but healthy workspace. When it does, the user sees `503 catalog_unavailable` ("temporarily unavailable, retry"), which is false and does not clear on retry.
- **Controller ruling.** I **agree** with it. The bound must stay finite: the unbounded SDK default of 300 s would hold a threadpool worker for 5 minutes during an outage, and this route is a sync `def`. Deriving it from the same config keeps it at no new credential source. Note that the worst case is roughly the retry window plus one in-flight request (about 30–60 s), not 30 s. That is acceptable for an unlocked read, but the ledger should state it.
- **Fix (required).**
  1. Add `DISCOVERY_HTTP_TIMEOUT_SECONDS = 30` and `DISCOVERY_RETRY_TIMEOUT_SECONDS = 30` in `model_endpoint_catalog.py`.
  2. Give `bounded_catalog_workspace_client` keyword parameters (`retry_timeout_seconds`, `http_timeout_seconds`) whose defaults are the unchanged save constants, or add a sibling `discovery_catalog_workspace_client`.
  3. Make discovery pass the discovery bound.
  4. The save path and `test_model_endpoint_catalog.py:366-371, :413` stay unchanged.
- **Test gap to close with it.** Both production-wiring tests (`tests:3670`, `tests:3941`) stub `bounded_catalog_workspace_client` with `_bounded(client)`, so **neither test asserts which bound a path uses**. Assert the actual values reaching the derived client's config instead: 30/30 for discovery and 5/3 for the save. Otherwise a swap of the two bounds would stay GREEN. Sabotage for it: swap the constants between the two paths; both tests must RED.

### Minor

- **M1** (`routes/agent_definitions.py:96-98`). `_CATALOG_UNAVAILABLE_MESSAGE` duplicates the literal in `model_endpoint_catalog.py:145`, and `graph_configuration.py`'s factory duplicates `:201`. Tests pin both strings, so drift would go RED. Even so, export one constant per message from `model_endpoint_catalog.py` and import it. This is the implementer's concern 4.
- **M2** (`routes/agent_definitions.py:101-123`). Production discovery composition lives in the route module, while the save composition lives in `graph_configuration.py` (`build_remote_endpoint_draft_validator`). Doing I1 is a natural point to move it to a `build_system_model_discovery()` factory beside the validator factory. Then one module owns both bounds and both credential derivations, and Task 5's probe has one place to look.
- **M3** (`tests:~4040`, `test_endpoint_validation_dependency_is_resolved_only_by_the_draft_put`). This is the only guard against the validator being wired into the upgrade or legacy-source routes, and it is a dependency-resolution check. That is sufficient, because the service ignores the validator on those paths by design (`graph_configuration_draft.py:343-348`, `:406`, `:465`), so a mis-wire is not a behavioural or network change. Recording it so that nobody later expects a behavioural RED from that mutation. No change is needed.

## Named-risk rulings

- **Admin before body; no catalog before authorisation.** Both confirmed. FastAPI prepends router dependencies, both new dependencies are lazy, and both are proven by tests plus the implementer's S05/S15 and my sabotage R1.
- **Other `GraphConfiguration(...)` sites.** Upgrades (`:582`), the schema-contract upgrade (`:622`), the legacy source (`:662`) and the workbench read (`:442`) all still pass no validator. `bootstrap_v1` in `graph_configuration.py:84` does the same. The service consults the validator only in `_validate_remote_endpoint`, which is called by the two saves (`:406`, `:465`). `save_draft_content` has no route caller. So none of these routes makes a network call.
- **The `_app_for` fake does not mask a wiring gap.** Three tests opt into the real dependency (`production_endpoint_validation=True`), and S01/S02 RED through them.
- **The PostgreSQL `real_route_stack` override is needed.** Sabotage R3 below: with it replaced by a raising `get_system_client`, 3 PUT-driven tests RED.

## Sabotage evidence

All mutations ran in `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-266-3`, a detached worktree at `17f4f343c`; the path contains neither "private" nor "payload". Interpreter: `PYTHONPATH=$T:$T/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly -rf`.

Pre-mutation GREEN: routes + draft + catalog = **412 passed**.

### R1: plan reviewer target `TASK3_REVIEWER_BODY_BEFORE_AUTH_SABOTAGE`

- **Mutation.** Inserted `typed_body: DraftSaveRequest,  # TASK3_REVIEWER_BODY_BEFORE_AUTH_SABOTAGE` into the PUT signature (`:489`), after `agent_key` and before the principal and validator dependencies.
- **Checks.** Anchor count 1. `grep -c TASK3_REVIEWER_BODY_BEFORE_AUTH_SABOTAGE` = 1. `DraftSaveRequest` was already imported (`:21`), so the mutation sits on the executed path.
- **Scope.** `tests/unit/test_agent_definition_workbench_routes.py`.
- **RED: 46 failed / 145 passed (of 191).**
  - The target `test_non_admin_endpoint_validation_put_rejects_before_body_catalog_or_writer` failed with `assert 422 == 403`: FastAPI decoded the truncated body before any dependency ran.
  - The sibling `test_non_admin_put_rejects_before_body_or_writer_and_does_not_echo_secrets` also failed.
  - The other 44 failures are #263's PUT wire contract, now replaced by FastAPI's own 422 format:
    - `test_put_rejects_every_protected_or_server_owned_field` ×18
    - `test_put_malformed_json_has_stable_root_error`
    - `test_put_requires_nonblank_trusted_principal_before_write` ×2
    - `test_no_request_model_accepts_a_protected_stage_view_or_display_field`
    - `test_put_assembly_rules_parser_rows_are_exact_and_stop_before_domain_validation` ×16
    - `test_put_assembly_parser_errors_retain_request_traversal_order`
    - `test_put_schema_overlay_type_field_is_rejected_as_extra_forbidden`
    - `test_put_schema_overlay_wire_type_error_uses_owned_message` ×3
    - `test_a_dict_type_wire_error_is_strict_type_through_the_terminal_default`
- **Restore.** `git checkout 17f4f343c -- src/api/routes/agent_definitions.py`. The md5 equals the pre-mutation md5, the marker count is 0, and `git status --porcelain` is empty.
- **GREEN: 191 passed.**

### R2 (own mutation): the validator reaching only `save_editable_model_draft`

- **Mutation.** Wired the production validator into the **schema-contract-upgrade** route, which is distinct from the implementer's S13 on the protected-assembly upgrade. The route gains `rev_validator: Annotated[RemoteEndpointDraftValidator, Depends(get_remote_endpoint_draft_validator)]` (`:614`) and `GraphConfiguration(remote_endpoint_validator=rev_validator).upgrade_draft_schema_contract(` (`:623`), both marked `# REV266_3_SCHEMA_UPGRADE_VALIDATOR`.
- **Checks.** Anchor counts 1 and 1. `grep -c REV266_3_SCHEMA_UPGRADE_VALIDATOR` = 2, one marker per mutated line.
- **Scope.** The routes file.
- **RED: 1 failed / 190 passed:** `test_endpoint_validation_dependency_is_resolved_only_by_the_draft_put`.
- **Restore.** `git checkout 17f4f343c -- <file>`. md5 identical, marker 0, status clean.
- **GREEN: 191 passed.**

### R3 (own, necessity check): the PostgreSQL `real_route_stack` override

- **Mutation.** Replaced the override (`tests/integration/test_agent_definition_workbench_postgres.py:1297-1301`) with a monkeypatched `databricks_client.get_system_client` that raises `AssertionError`, marked `# REV266_3_PG_OVERRIDE_REMOVED`. This kept the run away from real credentials.
- **Checks.** Anchor count 1. Marker `grep -c` = 4 lines.
- **Scope.** `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres` on that one file.
- **RED: 3 failed / 13 passed:**
  - `test_real_route_sequence_from_persisted_v1_edit_to_authored_only_v2[data_analyst]`
  - `test_real_route_sequence_from_persisted_v1_edit_to_authored_only_v2[build_reviewer]`
  - `test_real_upgrade_route_rejects_a_stale_lock_with_a_null_candidate_conflict`
- **Restore.** `git checkout 17f4f343c -- <file>`. Marker 0, status clean.
- **GREEN: 16 passed, 0 skipped.**

### Gates at `17f4f343c` (review worktree)

- Focused: 412 passed.
- PostgreSQL: `test_agent_definition_workbench_postgres.py` 16 passed and `test_agent_schema_overlay_postgres.py` 10 passed. Both ran one file per invocation with `-rs`, and neither had a skip.
- Full `tests/unit`: **6 failed, 6008 passed, 110 skipped, 136 warnings**. The 6 failures are exactly the baseline nodes:
  - `test_deploy_autoscaling.py` ×2
  - `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint` ×3
  - `test_style_exclusivity_persistence_boundary.py::…::test_session_manager_create_session` ×1
- There were no new failure nodes. The skip and warning counts are unchanged from the implementer's run.

## Task quality: Needs fixes

One Important item (I1: implement the controller-ruled discovery bound, and make both production-wiring tests assert their bound values) and three Minors. The spec is otherwise met, and the core security properties (admin first, body after auth, fail-closed wiring, strict DTOs) are proven by sabotage.
