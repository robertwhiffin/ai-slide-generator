# #266 whole-branch fix wave: report

- Branch `plan/model-discovery-266`. FIX_BASE `1cece548c6b61fb1d7c7c6ef71dc74de91998c41`.
- Worktree `.worktrees/issue-266-plan` only. No subagents, no installs, no push, PR or merge. `.venv` was absent before and after.
- Scope: I1, m1, m2, m4, m5 from `whole-branch-review.md`. The other Minors (m3, m6, m7, m8, m9 and the optional items) are untouched.

## Commits (FIX_BASE..HEAD)

| SHA | Item | Summary |
| --- | --- | --- |
| `93655ac20f3e0af89fd29c690c7e7ec36f190aa7` | I1 | `fix:` the save PUT calls `save_editable_model_draft` through `await run_in_threadpool(...)`. Adds the PUT loop-observer route test. |
| `f23822f1211c1f1c9a589116fb09b0ea57434edc` | m1 | `test:` a catalog fixture where an external-model entity comes first and the foundation-model entity second, next to an external-only endpoint. |
| `9ac75597ab13869efea4c3447b5f81183c7d6666` | m4 | `test:` new `tests/unit/test_probe_failure_contract_client_join.py` (3 tests). |
| `7a514decd23eaa6b4f42b2615a23e8c401a8335d` | m2 | `fix:` the unsupported probe message becomes "The endpoint rejected the structured-output test request." in the server, the `mocks.ts` fixture and the probe unit expectation. |
| `2f5f8e5699333c1e681f360777a8bf4c69a2c7da` | m5 | `fix:` the catalog view carries `errorRetryable`. The Model-tab alert appends "Use Refresh models to try again." only when it is true. Adds a Vitest case. |

## Per item

### I1: save PUT off the event loop
- `src/api/routes/agent_definitions.py` `save_agent_definition_draft`: only the facade call changed. It is now `outcome = await run_in_threadpool(GraphConfiguration(remote_endpoint_validator=...).save_editable_model_draft, db, agent_key=..., expected_lock_version=..., candidate=..., actor=...)`, inside the same `try`, with the same `except` arms.
- The following are byte-identical: the dependency list (auth before body), JSON parsing, the unknown-key check, `DraftSaveRequest` validation, the overlay-only `ValidationError` catch with its prefix and order, the error mapping and the response shapes. The `schema-contract-upgrade` route is untouched.
- The `db` session is used sequentially by one worker thread, as in the probe route.
- TDD. The new test `test_draft_save_route_runs_remote_endpoint_validation_off_the_event_loop` injects a validator that records `asyncio.get_running_loop()` and the validated name. Before the fix it was RED for the right reason: `AssertionError: remote endpoint validation ran on the event loop: [True]`. After the fix it is GREEN and records `[False]`.
- The other `async` routes that reach the writer do **no network I/O**:
  - `upgrade_agent_definition_protected_assembly`, `upgrade_agent_definition_schema_contract` and `read_agent_definition_legacy_prompt_source` each construct `GraphConfiguration()` with no validator.
  - Their service methods (`graph_configuration_draft.py:488`, `:527`, `:581`) never call `_validate_remote_endpoint`, which is only at `:421` and `:480`.
  - The workbench GET is a sync `def`, so it already runs in the threadpool.
  - These routes still do their short synchronous DB transaction on the loop. That behaviour predates #266 and is outside this wave, so I did not widen the fix.

### m1: the any-served-entity rule
- New test `test_list_system_models_includes_an_endpoint_whose_foundation_entity_is_not_first` (`tests/unit/test_model_endpoint_catalog.py`). The fixture is `[external entity (foundation_model=None), foundation entity]` plus an external-only endpoint.
- Only the mixed endpoint may be discovered, with the second entity's metadata.
- This pins behaviour the production code already has, so it was GREEN from the start. Its RED comes from sabotage S2 (below).

### m4: Python join for the probe failure contract
- New sibling of `test_endpoint_name_policy_client_join.py`: `tests/unit/test_probe_failure_contract_client_join.py`.
- **Server side** (imported, not text-read): `model_endpoint_probe._UNSUPPORTED/_FORBIDDEN/_FAILED` (code, message, retryable) and `routes._PROBE_FAILURE_STATUS` (status). The join asserts that the code set equals `get_args(StructuredOutputProbeCode)` and equals the status-map keys.
- **Client side** (text-read):
  - `agentDefinitions.ts` `PROBE_FAILURE_CONTRACT`, checked per code as (status, retryable).
  - The `StructuredOutputProbeFailureCode` union, checked as the code set.
  - The parser's `if (status !== 403 && status !== 422 && status !== 503) return null;` guard, checked as the status set.
  - The `mocks.ts` fixture `STRUCTURED_OUTPUT_PROBE_FAILURES`, checked per code as (status, message, retryable).
- The client `PROBE_FAILURE_CONTRACT` carries no message: the UI renders the server's message. So only `mocks.ts` holds a message copy.
- **New text-read rules** (they are also in the module docstring):
  - `PROBE_FAILURE_CONTRACT`:
    - It stays `const PROBE_FAILURE_CONTRACT = {` closed by `} as const;`.
    - It has one entry per line, exactly `  NNN: { code: '<code>', retryable: <true|false> },`.
    - No comment may go inside the block.
  - `StructuredOutputProbeFailureCode`: one `  | '<code>'` member per line, and the last member ends in `;`.
  - The parser status-guard line stays byte-identical.
  - `STRUCTURED_OUTPUT_PROBE_FAILURES`:
    - It stays `export const STRUCTURED_OUTPUT_PROBE_FAILURES = {` closed by `} as const;`.
    - Each entry is exactly five lines: `  <code>: {` / `    status: NNN,` / `    message: '<text>',` / `    retryable: <bool>,` / `  },`.
    - Messages stay single-quoted, with no apostrophe or backslash.
    - Nothing else may go in the block. The join asserts that the matched entries concatenate to the whole block.
  - Each opening line must occur exactly once. It is matched with ` = {` attached, so a same-prefix constant cannot be matched first.
- The existing correction-19 files were not touched: `CUSTOM_ANCHORS`, `_LEGACY_SOURCE_ROLES`, the TS endpoint-policy regex lines and message, and the `mocks.ts` strict-JSON blocks.

### m2: probe 400/404/422 wording
- `_UNSUPPORTED` message: "This endpoint does not support structured output." becomes "The endpoint rejected the structured-output test request."
- The code `unsupported_structured_output`, status 422 and `retryable=False` are unchanged. The classifier comment now names the deleted-endpoint and refused-`max_tokens` cases.
- Copies updated: the server, `frontend/tests/fixtures/mocks.ts:1605`, and `tests/unit/test_model_endpoint_probe.py` `EXPECTED_FAILURES`. The client `PROBE_FAILURE_CONTRACT` has no message, so there was nothing to change there. Afterwards `git grep` finds no old-copy occurrence in `src`, `tests`, `frontend/src`, `frontend/tests` or `docs`.
- TDD:
  - Updating the unit expectation first gave RED 4 (`At index 1 diff: 'This endpoint does not support structured output.' != 'The endpoint rejected …'`).
  - The server change then left exactly the new m4 join RED on the stale fixture (`test_client_fixture_is_the_server_status_message_and_retryable_table`), which demonstrated the join live.
  - The `mocks.ts` update brought everything back to GREEN.
- Vitest and Playwright read the message from the fixture. The new text contains neither "Test structured output" nor "structured output", so no substring-name locator can collide with it.

### m5: forbidden catalog alert copy
- `AgentDefinitionWorkbench.tsx`: new `modelCatalogErrorRetryable(error)`. It is `false` only for a typed `ModelEndpointCatalogApiError` with `retryable === false`. Network failures, invalid responses and untyped statuses keep the retry copy.
- The view gains `errorRetryable: boolean`. It is set on every `setCatalog` call: `false` for idle, loading and success, and derived on error.
- `DefinitionEditor.tsx` appends " Use Refresh models to try again." only when `errorRetryable` is true. For the retryable path the rendered text is byte-identical to before.
- The existing single reducer, request token and gate are unchanged. The Refresh button is still shown and still recovers, as the existing it.each test confirms.
- TDD. The new it.each `a %s catalog alert offers a retry only when the failure is retryable` asserts the exact `textContent`. The forbidden case was RED (`Received: "… identity. Use Refresh models to try again."`), and the unavailable case was GREEN before and after.

## Clause-to-mutation table

Every mutation was applied by `/tmp/t266-wbfix/mut.py`, which asserts that the anchor occurs exactly once. Every restore was `git checkout <explicit SHA> -- <file>`, followed by a marker `grep -c` of 0 and an empty `git status --short --untracked-files=no`. Markers were placed so that they execute, or at least do not change parsing (see M4-A).

| # | Clause | File / mutation | Anchor | Marker (`grep -c` = 1) | Scope (command) | RED | Restore | GREEN |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| I1 | PUT remote check off the loop | `src/api/routes/agent_definitions.py`: `await run_in_threadpool(X.save_editable_model_draft, db, …)` is replaced by a direct `X.save_editable_model_draft(db, …)` call (the pre-fix shape) | 1 | `WBFIX266_I1_NO_THREADPOOL_SABOTAGE` at `:589`, on the executed call line | `pytest -q -p no:randomly -rf tests/unit/test_agent_definition_workbench_routes.py` | **1 failed / 234 passed**: `test_draft_save_route_runs_remote_endpoint_validation_off_the_event_loop` | `git checkout 93655ac20f3e0af89fd29c690c7e7ec36f190aa7 -- src/api/routes/agent_definitions.py`; md5 equals the pre-mutation value; marker 0 | 235 passed |
| m1 / S2 | any served entity | `src/services/model_endpoint_catalog.py`: `for entity in served_entities` becomes `for entity in list(served_entities)[:1]` | 1 | `WBFIX266_FIRST_ENTITY_ONLY_SABOTAGE` at `:185`, inside the executed generator | `pytest … tests/unit/test_model_endpoint_catalog.py tests/unit/test_agent_definition_workbench_routes.py` | **1 failed / 296 passed**: `test_list_system_models_includes_an_endpoint_whose_foundation_entity_is_not_first` (S2 had survived 295/295 in the review) | `git checkout HEAD -- …` with HEAD = `93655ac20f3e0af89fd29c690c7e7ec36f190aa7` at that moment; md5 equals; marker 0 | 297 passed |
| m4-A | client contract drift | `frontend/src/api/agentDefinitions.ts` `PROBE_FAILURE_CONTRACT` `422 … retryable: false` becomes `true` | 1 | `WBFIX266_M4_CLIENT_CONTRACT_SABOTAGE` as a `//` line **above** `const PROBE_FAILURE_CONTRACT` | join + probe + routes files (`/tmp/t266-wbfix/run_join.sh`) | **1 failed / 283**: `test_client_status_contract_is_the_server_status_and_retryable_table` (value mismatch) | `git checkout f23822f1211c1f1c9a589116fb09b0ea57434edc -- …`; marker 0 | 284 |
| m4-B | client fixture drift | `frontend/tests/fixtures/mocks.ts`: the forbidden message becomes "The app may not query this endpoint." | 1 | `WBFIX266_M4_CLIENT_FIXTURE_SABOTAGE` above the `export const` | same | **1 failed / 283**: `test_client_fixture_is_the_server_status_message_and_retryable_table` (`'The app may not query…' != 'The app is not permitted…'`) | `git checkout f23822f12… -- …`; marker 0 | 284 |
| m4-C | server status drift | `routes/agent_definitions.py` `_PROBE_FAILURE_STATUS["unsupported_structured_output"]` 422 becomes 400 | 1 | `WBFIX266_M4_SERVER_STATUS_SABOTAGE` (trailing comment on the dict line) | same | **7 failed / 277**: all 3 join tests plus 4 existing route tests (`…maps_each_typed_failure_exactly[unsupported…]`, `…real_provider_errors[400/404/422-…]`) | `git checkout f23822f12… -- …`; marker 0 | 284 |
| m4-D | server retryable drift | `model_endpoint_probe.py` `_FORBIDDEN` retryable False becomes True | 1 | `WBFIX266_M4_SERVER_RETRYABLE_SABOTAGE` | same | **8 failed / 276**: join `…status_contract…` and `…fixture…`, plus 6 existing probe and route forbidden tests | `git checkout f23822f12… -- …`; marker 0 | 284 |
| m2 | new copy | `model_endpoint_probe.py` `_UNSUPPORTED` message reverted to "This endpoint does not support structured output." | 1 | `WBFIX266_M2_OLD_COPY_SABOTAGE` | same | **5 failed / 279**: join `…fixture…`, plus `test_model_endpoint_probe_binding_rejection_is_unsupported[not-implemented]` and `…real_provider_errors_are_classified[400/404/422-unsupported_structured_output]` | `git checkout 7a514decd23eaa6b4f42b2615a23e8c401a8335d -- …`; marker 0 | 284 |
| m5-A | retryable derivation | `AgentDefinitionWorkbench.tsx` `modelCatalogErrorRetryable` returns `true \|\| …` | 1 | `WBFIX266_M5_ALWAYS_RETRYABLE_SABOTAGE` | `(cd frontend && npx vitest run src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)` | **1 failed / 178**: `a forbidden catalog alert offers a retry only when the failure is retryable` | `git checkout 2f5f8e5699333c1e681f360777a8bf4c69a2c7da -- …`; marker 0 | 179 |
| m5-B | editor ignores the flag | `DefinitionEditor.tsx`: `{modelCatalog.errorRetryable` becomes `{(modelCatalog.errorRetryable \|\| true)` | 1 | `WBFIX266_M5_EDITOR_IGNORES_RETRYABLE_SABOTAGE` | same | **1 failed / 178**: same test | `git checkout 2f5f8e569… -- …`; marker 0 | 179 |

**Discarded, mis-aimed attempt (recorded, not counted).** The first M4-A try put the `// marker` as a trailing comment on the contract line itself. It RED'd only because the strict line regex could not parse the comment (`unreadable PROBE_FAILURE_CONTRACT line`), not because of the value, so it was uninformative. I restored it and re-aimed it with the marker above the block. That re-aimed row is the one in the table.

## Gates

All gates ran at HEAD `2f5f8e5699333c1e681f360777a8bf4c69a2c7da`. `PY` below means `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python`.

| Gate | Exact command | Result (by cause) |
| --- | --- | --- |
| Full `tests/unit` | `DATABASE_URL=sqlite:////tmp/t266-wbfix/unit-default.sqlite PY -m pytest tests/unit -q -p no:randomly -rf` (see concern 1 for why `DATABASE_URL` is set) | **6 failed / 6175 passed / 110 skipped**, 136 warnings, 418 s. The 6 failures are exactly the baseline nodes and causes: `test_deploy_autoscaling.py` ×2 (`'provisioned' == 'autoscaling'`; `…provisioned' to have been called once. Called 0 times.`), `test_style_exclusivity_chokepoint.py` ×3 (`'_FakeSession' object has no attribute 'execute'` at `conversation_pins.py:79`), and `test_style_exclusivity_persistence_boundary.py` ×1 (`ConversationGraphReleaseIntegrityError: no active Graph Release` at `:83`). There are zero failures outside that set. 6175 is 6170 (review) plus the 5 new Python tests. |
| Backend matrix (the plan's 10 unit files, plus both join files) | `PY -m pytest -q -p no:randomly -rfs tests/unit/test_model_endpoint_catalog.py tests/unit/test_model_endpoint_probe.py tests/unit/test_graph_configuration_draft.py tests/unit/test_graph_configuration_workbench.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_agent_runtime.py tests/unit/test_persisted_agent_runtime.py tests/unit/test_prompt_assembler.py tests/unit/test_agent_schema_registry.py tests/unit/test_ci_collects_integration_tests.py tests/unit/test_endpoint_name_policy_client_join.py tests/unit/test_probe_failure_contract_client_join.py` | **868 passed**, 0 failed, 0 skipped. That is Task 6's 838, plus 25 for the existing endpoint join, plus 1 (I1), 1 (m1) and 3 (m4). Warnings come from pre-existing import-time deprecations only (`requests.py:53`, `responses.py:45`, `chat_service.py:19`, `toolkit.py:29`, `vector_search_retriever_tool.py:107`, and the `src/api/routes/settings|…` Pydantic class-config sites `contributors.py:49`, `deck_contributors.py:51`, `deck_prompts.py:47`, `images.py:22`, `slide_styles.py:50`, which the routes module import emits). The new join module emits none of its own. |
| PostgreSQL (the plan's 8 modules, one invocation each, `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres PY -m pytest -q -p no:randomly -rs tests/integration/<m>.py`) | — | `test_agent_definition_workbench_postgres` **17**, `test_agent_schema_overlay_postgres` **10**, `test_persisted_graph_runtime_failures_postgres` **7**, bootstrap 2, constraints 7, pin migration 1, pin creation 2, pin acceptance 1. **Zero skips and zero failures** in every module. The workbench suite exercises the PUT through the real route stack over PostgreSQL, now in the threadpool. |
| Vitest | `(cd frontend && npm run test:unit)` | **14 files, 488 passed** (486 baseline plus 2 new m5 cases), exit 0 |
| Typecheck | `(cd frontend && npm run typecheck)` | exit 0 |
| ESLint | `(cd frontend && npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts)` | exit 0, no findings |
| Playwright | `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)` | **69 passed** (baseline 69), 54.9 s. `lsof -i :3000` was empty before and after, and nothing was left running. |
| ruff vs base | `PY -m ruff check <file>` for each changed `.py` file at HEAD; the same for the FIX_BASE blob of the routes test (`git show 1cece548c…:tests/unit/test_agent_definition_workbench_routes.py`) | All clean at HEAD except `tests/unit/test_agent_definition_workbench_routes.py`: I001 at 1:1 and F401 `SCHEMA_CONTRACT_BUNDLES` at :65. These are the identical 2 findings at FIX_BASE, and neither was introduced here. The new `test_probe_failure_contract_client_join.py` is clean. |
| Hygiene | `test ! -e .venv` before and after; the triple check after the report commit (below) | `.venv` absent. The triple check is empty. |

## Concerns

1. **The prescribed full-unit command writes to the dev database `ai_slide_generator` (pre-existing; not caused by this wave).**
   - My first full-unit run used the exact prescribed command with no `DATABASE_URL`. At about 50% it held 4 connections to `ai_slide_generator` on localhost, each `idle` after `COMMIT` (seen in `pg_stat_activity`, client ports matched to the pytest PID via `lsof`). I killed it immediately.
   - Cause: some unit test reaches `src/core/database.get_engine()` un-overridden, and `_get_database_url()` falls back to `postgresql://localhost/ai_slide_generator` (`database.py:264`). This wave does not touch `src/core` or any test fixture outside the 5 listed files.
   - Every earlier full-unit gate on this branch (task implementers, controller, whole-branch reviewer) ran the same command, so they very likely did the same.
   - I re-ran with `DATABASE_URL` pointed at a throwaway SQLite file. A monitor polling `pg_stat_activity` saw zero `ai_slide_generator` connections for the whole run, and the failure set and causes are identical to the baseline.
   - I did not identify the specific test, and I did not inspect or clean the dev DB, because the constraint is to leave it untouched. Recommend making the unit harness default `DATABASE_URL` to SQLite, or refusing the fallback under pytest, and telling the user their dev DB may have received test commits.
2. **The full unit suite makes outbound HTTPS calls (pre-existing).** `tests/unit/test_dependencies_resolve.py` (`…on_proxy`) held several ESTABLISHED connections to `13.91.180.32:443` and stalled the run at about 27% for a few minutes. It is unrelated to #266, is not an API 401/403, and passed.
3. **m2 wording also covers the binding-step `NotImplementedError`.** That path, where the client refuses structured output locally, maps to the same code. "The endpoint rejected the structured-output test request." is slightly loose for it. The review already accepted that mapping as negligible (Task 5 M4), so I did not split the code.
4. **I1 scope.** Only the save PUT was moved to the threadpool. The two upgrades and the legacy-source read still run their short synchronous DB transaction on the loop, with no network I/O. That predates #266 and is left as is. The optional PostgreSQL second-worker lock-waiter test for I1 was not added.
5. The m1 restore used `git checkout HEAD --` while HEAD was `93655ac20f3e0af89fd29c690c7e7ec36f190aa7`, not the literal SHA. The md5 matched the pre-mutation value. Every other restore used an explicit SHA.
