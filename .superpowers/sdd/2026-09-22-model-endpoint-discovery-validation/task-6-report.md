# Task 6 report — probe UI, browser recovery, and complete verification (#266)

**Status:** DONE_WITH_CONCERNS (the concerns are notes for the controller; no gate is open)

- TASK_BASE `e55ca18521ecca06244d43a3c9ac41270f3646dc` (pinned; every restore used an explicit SHA)
- Implementation `c66c2623b2a1bfbc215c3c1480c7dfef216b05f7`, `test: prove exact endpoint discovery and probe (#266)`
- This report is the following commit.
- Step 5 (whole-branch review package, range proof, local merge) is **not** done here: the dispatch forbids merge and subagents. It belongs to the controller.

## What was built

Nine files, all frontend. No Python file changed in this task.

- **`frontend/src/api/agentDefinitions.ts`** (appended at the end; `CUSTOM_ANCHORS` untouched):
  - Types `StructuredOutputProbeIdentity`, `StructuredOutputProbeSuccessResponse`, `StructuredOutputProbeFailureCode`, `StructuredOutputProbeFailureResponse`.
  - `StructuredOutputProbeApiError` (status 403/422/503 plus the parsed failure).
  - Strict parsers `parseStructuredOutputProbeSuccess` and `parseStructuredOutputProbeFailure`. Exact keys, a non-empty endpoint, a lowercase 64-hex hash and a non-negative integer lock. The status fixes the code and `retryable`, per the Task 5 ruling: 403 `endpoint_probe_forbidden`/false, 422 `unsupported_structured_output`/false, 503 `structured_output_probe_failed`/true.
  - `probeDraftStructuredOutput(agentKey, {lock_version})` is one POST to `/draft/{agent_key}/model-endpoint-probe`. The body is built as `{ lock_version }` only, so no other field can pass through. Outcomes:
    - 200 is the exact success, or `InvalidDraftSaveResponseError`.
    - 409 is the existing null-candidate conflict (`parseDraftSaveConflictResponse(payload, 'null')`), or invalid.
    - 422 is the typed unsupported failure, or else the draft rejection envelope (the saved-name policy re-check), or else invalid.
    - 403 and 503 give the typed failure. Any other body at those statuses (an auth dependency's `{detail}`, a proxy page, a wrong pairing) is a plain `AgentDefinitionApiError`, so it is never offered as a typed Retry.
    - Any other status is `AgentDefinitionApiError`. A transport failure propagates unchanged.
- **`draftEditorState.ts`** (the one reducer). Probe joins it; there is no second machine.
  - `DraftOperationKind` gains `'probe'`, in the one `pendingSave` slot.
  - `DraftEditorEntry.probeResult: DraftProbeResult | null`, holding the outcome plus the exact reported identity.
  - Actions `probeStarted`, `probeSucceeded`, `probeUnsuccessful` (a typed failure), `probeRejected` (a draft 422), `probeConflicted` (409) and `probeFailed` (transport or untyped).
  - `probeStarted` is refused while anything is pending. It is also refused while the role's local endpoint differs from its saved endpoint; this is the reducer backstop, `probeEndpointUnsaved`. Unlike `startOperation`, it keeps local field errors, because a probe never writes.
  - `settleProbe` completes only the matching `'probe'` request ID, via `matchingPending`.
    - It requires the reported lock to equal the sent lock and the current lock, and the endpoint and hash to equal the saved candidate. Anything else is contained with `requestError` "Unable to test structured output because the server response was invalid." and no result.
    - It changes only `pendingSave` and that role's `probeResult`. The lock, saved entry, form and status are untouched, and tests assert this with `toBe`.
    - A result whose endpoint is no longer the local one is dropped.
  - `probeRejected` reuses `rejectOperation`. The one-line change is that `'probe'` binds field errors as `'save'` does, so the policy re-check lands on the endpoint field.
  - `probeConflicted` reuses `mergeConflict`, the seven-role recovery. `probeFailed` reuses `failOperation`.
  - Clearing the result:
    - Any `endpoint_name` edit clears it, even one back to the saved name.
    - `reloadServer` and `restoreRetained` (including the quarantined path) clear it when the local endpoint moves.
    - `succeedWrite` and `mergeConflict` clear it when the saved candidate's hash or endpoint changes.
    - `adoptAuthoritativeDefinition` itself was **not** touched.
  - `probeErrorMessage` never reads the server's `detail`, so an untyped error body cannot leak.
- **`useDraftEditor.ts`:** `probeStructuredOutput(agentKey)` uses the same `operationBlocked()`, `nextRequestIdRef` and `inFlightRequestIdRef`. While the endpoint is unsaved it returns before allocating a request ID. It sends `{lock_version: state.draft.lock_version}`, dispatches only after the client has parsed the response, and maps errors to the actions above.
- **`DefinitionEditor.tsx`** (Model tab, below "Custom endpoint name"):
  - A **Test structured output** button. It is disabled while any operation is pending or the local endpoint is unsaved, and the unsaved case shows the hint "Save the endpoint before testing structured output."
  - A "Testing the saved candidate…" line while this role's probe is pending.
  - A `region` named **Structured output test result**, with `aria-live=polite`.
    - Success reads "Structured output test succeeded for the saved candidate." / "This result does not change the draft or its status."
    - A failure shows the server's sanitized message as `role=alert`.
    - Both show the identity line `Endpoint … · Candidate hash … · Draft lock …`.
    - **Retry structured output test** is rendered only for `outcome: 'failed' && retryable`.
- **`AgentDefinitionWorkbench.tsx`:** passes `probePending` and `onProbeStructuredOutput`. The gate stays the one `pending !== null`.
- **`frontend/tests/fixtures/mocks.ts`:** appended at the end of the file, after `ENDPOINT_NAME_POLICY_CASES`: `SEED_CANDIDATE_HASH`, `STRUCTURED_OUTPUT_PROBE_FAILURES` (the server's messages verbatim, with status and retryable), `syntheticProbeSuccess` and `syntheticProbeFailure`. No new name has a joined name as a prefix, and the strict-JSON blocks are untouched.

The button calls only the Task 5 route. There is no `ServingEndpointsAPI.query`, OpenAPI inference, `run_candidate`, #267 route, or catalog call. Row M20 shows that a probe which also refreshes the catalog goes RED.

## Name and guard checks

- **Forbidden stems.** All seven new visible strings return `false` under `FORBIDDEN_ACTION_STEMS` (`/tmp/t266-6/names.mjs`). The Vitest and Playwright sweeps both pass with the result visible.
- **Substring collisions.** "Test structured output", "Retry structured output test" and "Structured output test result" are not substrings of one another in either direction. None contains, or is contained in, "Refresh models", "Search discovered models", "Discovered models", "Custom endpoint name", "Save Draft", "Schema Upgrade", "Description override", the provenance labels, "Needs test" or "Lock version".
  - The identity line deliberately avoids a `Lock version` label, because `getByText('Lock version')` is used exactly.
  - `grep -c "{ name: 'Endpoint' }"` is 0 in both harnesses.
- **Harness routing (C17).** `mockWorkbenchWithPuts` gains an optional `probe` responder. `mockWorkbenchApi` gains `probe`. Both route `/model-endpoint-probe` **by URL**, before the PUT fallback. An unrouted probe throws `unexpected probe POST` rather than being parsed as a PUT.
  - The e2e spec adds `PROBE_ENDPOINT = '**/draft/*/model-endpoint-probe'`. It cannot be matched by `SAVE_ENDPOINT`, because a glob `*` does not cross `/`.
  - Non-default catalogs register `installCatalogMock` after `installWorkbenchMock`.
- **C10.** Every five-leaf assertion is on Architect, a seed v1 role with no overlay edits.

## RED (before any production line)

Only the fixture and test files had been written.

- `npm run test:unit -- draftEditorState.test.ts AgentDefinitionWorkbench.test.tsx` gave **74 failed, 246 passed (320)**, with 14 uncaught errors (`/tmp/t266-6/red-vitest.txt`).
  - Every failure is a new probe test. The causes are `probeDraftStructuredOutput`/`StructuredOutputProbeApiError` undefined, no `probeResult`, no `'probe'` reducer cases, no "Test structured output" control, and `editor.probeStructuredOutput is not a function`. The last is the 14 errors from the gate-harness clicks.
  - All 246 pre-existing tests passed, including every Task 4 catalogue test.
- `npx playwright test … --project=chromium --workers=1 -g 'model endpoint'` gave **8 failed, 1 passed** (`/tmp/t266-6/red-pw.txt`).
  - Every failure waits on `getByRole('button', { name: 'Test structured output' })`, which does not exist.
  - The one pass is `model endpoint catalogue 503 … without remount`. It exercises existing Task 4 behaviour and is expected to pass.
  - At base, `-g 'model endpoint'` matched zero tests. Task 4 added no e2e test with that phrase.

## GREEN

- The same Vitest command gave **320 passed**.
- The same Playwright command gave **9 passed**.
- The first GREEN needed no production fix. One ESLint follow-up (two unused `_omit` bindings in the test) was fixed with `setAtPath` before the commit.

## Clause-to-mutation table

- **Driver:** `/tmp/t266-6/mutate.py`. Results are in `/tmp/t266-6/mut-*.json` and per-row output in `/tmp/t266-6/M*-red.txt`.
- **Per row:** the anchor count was exactly 1 before mutating. The marker `T266_6_Mn` had `grep -c` 1 while applied and 0 after restoring. Restore was `git checkout c66c2623b2a1bfbc215c3c1480c7dfef216b05f7 -- <file>`, and `git diff --stat <SHA> -- <file>` was empty after each restore. GREEN was then re-run in the same scope.
- **Scopes:**
  - **V** = `npx vitest run src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx -t probe`. GREEN is 79 passed. The "241 skipped" in V is Vitest's `-t` deselection, not real skips.
  - **P** = `npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1 -g 'model endpoint'`. GREEN is 9 passed.
- **Free rows:** none.

| ID | Clause | File | Mutation | Scope | RED (failing tests) | GREEN |
|---|---|---|---|---|---|---|
| M1 | one gate, hook | useDraftEditor | probe skips `operationBlocked()` | V | 8: gate harness `save architect then probe architect`, `upgrade architect then probe builder`, `schema upgrade architect then probe builder`, `recover data analyst then probe architect`, `probe architect then probe builder`, `probe architect then probe architect`, `double probe architect` (same tick), `save then probe architect` (same tick) | 79 |
| M2 | one gate, reducer | draftEditorState | `probeStarted` ignores `pendingSave` | V | 1: `joins the one pending slot: a pending probe refuses every other start…` | 79 |
| M3 | unsaved endpoint, hook (no request ID) | useDraftEditor | drop hook guard | V | 1: `a hook probe with an unsaved endpoint allocates no request…` | 79 |
| M4 | unsaved endpoint, reducer backstop | draftEditorState | drop backstop | V | 1: `refuses to start a probe while the role's local endpoint differs…` | 79 |
| M5 | unsaved endpoint, control | DefinitionEditor | `probeDisabled` ignores endpoint | V | 1: `is disabled while the local endpoint is unsaved…` | 79 |
| M6 | lock-only body | agentDefinitions | body adds `endpoint_name` | V | 7: transport `sends exactly the lock body…`, `Test structured output sends one lock-only POST…`, `a hook probe…`, `a probe 409 recovers…`, `is disabled while…`, `probes the saved endpoint, never a newer…`, `renders … structured_output_probe_failed … Retry…` | 79 |
| M7 | success never moves the lock | draftEditorState | settle bumps `draft.lock_version` | V | 8: `a success records the exact identity and changes no lock…`, `a typed …failure…`×3, `Test structured output sends…`, `a hook probe…`, `clears an old result…`, `…probe_failed … Retry…` | 79 |
| M8 | Retry only when retryable | DefinitionEditor | Retry for every failure | V | 2: `renders the sanitized endpoint_probe_forbidden…`, `…unsupported_structured_output…` | 79 |
| M9 | status fixes retryable | agentDefinitions | drop `retryable` check | V | 3: `a 403 that is not the exact typed envelope…`, `a 503 …`, `rejects a 422 carrying the unsupported code with retryable true…` | 79 |
| M10 | reported identity must be the saved candidate | draftEditorState | `coherent = true` | V | 3: `a success reporting another lock / endpoint / candidate hash…` | 79 |
| M11 | endpoint edit clears the result | draftEditorState | edit keeps `probeResult` | V | 2: reducer `clears an old probe result…`, component `clears an old result…even back to the saved name` | 79 |
| M12 | in-flight endpoint change drops the answer | draftEditorState | always store the result | V | 1: reducer `clears an old probe result…drops a result for an endpoint no longer local` | 79 |
| M13 | request-ID ordering | draftEditorState | settle on any pending | V | 2: `a late probe response after a newer save…`, `only the pending probe's own request ID…` | 79 |
| M14 | saved-candidate change clears the result | draftEditorState | adoption always keeps it | V | 1: `a later save that changes the saved candidate clears…` | 79 |
| M15 | no leak of untyped detail | draftEditorState | message = `error.detail` | V | 1: `an untyped 500 is a contained alert with no result, no leak…` | 79 |
| M16 | policy 422 binds to the endpoint field | draftEditorState | only `'save'` binds | V | 1: `a probe policy 422 binds to the endpoint field…` | 79 |
| M17 | 409 is the seven-role recovery | useDraftEditor | 409 → `probeFailed` | V | 1: `a probe 409 recovers all seven roles…` | 79 |
| M18 | sends the current lock | useDraftEditor | always `lock_version: 0` | V | 2: `a probe 409 recovers… adopted lock`, `is disabled while… probes the newly saved candidate` | 79 |
| M19 | never claims approval | DefinitionEditor | success text adds "Approved" | V | 1: `Test structured output sends one lock-only POST… without a write` | 79 |
| M20 | probe never reads the catalog | DefinitionEditor | probe also calls `onRefreshModels` | P | 1: `model endpoint discovery: first Model-tab read…then an explicit probe` | 9 |
| M21 | strict 200 keys | agentDefinitions | drop `hasExactKeys` on success | V | 1: `rejects a 200 with an extra key as an invalid response` | 79 |
| M22 | browser: lock-only probe body | agentDefinitions | body adds `endpoint_name` | P | 7: discovery, manual custom, manual server-validation, probe ×3, empty discovery | 9 |
| M23 | browser: Retry only when retryable | DefinitionEditor | Retry for every failure | P | 2: `model endpoint probe endpoint_probe_forbidden…`, `…unsupported_structured_output…` | 9 |
| M24 | browser: disabled while unsaved | DefinitionEditor | `probeDisabled` ignores endpoint | P | 3: discovery flow, manual server-validation flow, `URL rejection … zero PUT and zero probe` | 9 |

**Reserved plan targets.** I did not run these; I only built the guards they should hit.
- `TASK6_CONTROLLER_AUTO_ADVANCE_SABOTAGE` (assign the first refreshed item to the endpoint form) should turn RED:
  - Vitest `a newer discovered item never moves the seed until it is explicitly selected and saved` (Task 4) and `probes the saved endpoint, never a newer discovered family member…`;
  - Playwright `model endpoint discovery: …`, which asserts after Refresh that the newer radio is unchecked, the seed is checked, the custom field is the seed and the status is not Unsaved.
- The reviewer target "allow Probe while endpoint edits are unsaved" is guarded at three independent layers: control (M5/M24), hook (M3) and reducer (M4).

## Gates (the plan's whole #266 matrix, results by cause)

| Gate | Exact command | Result |
|---|---|---|
| Vitest (plan RED/GREEN pair) | `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)` | 2 files, 320 passed |
| Vitest full (includes the four workbench files) | `(cd frontend && npm run test:unit)` | **14 files, 486 passed**, 0 failed, 0 skipped. That is 407 plus 79 new. The workbench files are `draftEditorState` 143, `AgentDefinitionWorkbench` 177, `OutputSchemaEditor` 47 and `AssemblyEditor` 11. Stderr has only React act() warnings from two pre-existing, unmodified tests (`typing and navigation never save…`, `associates all five 422 messages…`); both are also present in the RED run. |
| Typecheck | `(cd frontend && npm run typecheck)` | exit 0 |
| ESLint (phase B command) | `(cd frontend && npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts)` | exit 0, no findings |
| Playwright workbench, full | `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)` | **69 passed**, 0 skipped, 0 flaky (60 plus 9 new), 55 s |
| Backend focused matrix (plan list) | `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly -rfs tests/unit/test_model_endpoint_catalog.py tests/unit/test_model_endpoint_probe.py tests/unit/test_graph_configuration_draft.py tests/unit/test_graph_configuration_workbench.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_agent_runtime.py tests/unit/test_persisted_agent_runtime.py tests/unit/test_prompt_assembler.py tests/unit/test_agent_schema_registry.py tests/unit/test_ci_collects_integration_tests.py` | **838 passed**, 0 failed, 0 skipped. Both C14 files are present. The warning locations are exactly the five baseline causes: `requests.py:53`, `responses.py:45`, `chat_service.py:19`, `unitycatalog…toolkit.py:29` and `databricks_ai_bridge…vector_search_retriever_tool.py:107`. |
| Text-read joins (pre-commit) | same interpreter, `tests/unit/test_prompt_assembler.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_endpoint_name_policy_client_join.py` | 338 passed |
| Full unit | `PYTHONPATH=… python -m pytest tests/unit -q -p no:randomly -rf` | **6 failed / 6143 passed / 110 skipped**, 136 warnings, 428 s. The run finished 23:35:30 UTC, so it was not near midnight, and there were no `test_usage_service` failures. The six failures are exactly the baseline nodes, confirmed by traceback: `test_deploy_autoscaling.py` ×2 (`'provisioned' == 'autoscaling'`; `Called 0 times`), `test_style_exclusivity_chokepoint.py` ×3 (`'_FakeSession' object has no attribute 'execute'`), and `test_style_exclusivity_persistence_boundary.py` ×1 (`no active Graph Release`). Task 6 changed no Python, so the counts equal Task 5's final run. |
| ruff | Task 6 range `e55ca1852..HEAD` has **zero** `.py` files. Each #266 Python file changed in `c040dbde0..HEAD` was checked at HEAD and at base. | All clean at HEAD, except `tests/unit/test_agent_definition_workbench_routes.py`: I001 at 1:1 and F401 `SCHEMA_CONTRACT_BUNDLES` at :65. Those are the identical two findings at base `c040dbde0`, and neither was introduced here. |

**PostgreSQL** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`). Each module was one invocation of `PYTHONPATH=… python -m pytest -q -p no:randomly -rs tests/integration/<module>.py`, and every one had **zero skips**:

| Module | Result | Warning causes |
|---|---|---|
| `test_graph_configuration_bootstrap_postgres` | 2 passed | the five baseline locations |
| `test_graph_configuration_constraints_postgres` | 7 passed | the five baseline locations |
| `test_persisted_graph_runtime_failures_postgres` | 7 passed | the five baseline locations |
| `test_conversation_pin_migration_postgres` | 1 passed | the five baseline locations |
| `test_conversation_pin_creation_postgres` | 2 passed | the five baseline locations |
| `test_agent_definition_workbench_postgres` | 17 passed | the five baseline locations |
| `test_agent_schema_overlay_postgres` | 10 passed | the five baseline locations |
| `test_conversation_pin_acceptance_postgres` (C20 addition) | 1 passed | the five baseline locations, plus 120 `pyspark/sql/pandas/utils.py:51/85…` distutils `LooseVersion` DeprecationWarnings from that module's own imports |

The module total is **47 passed**. Task 6 changed no Python and no fixture those modules import, so the pyspark warnings cannot be a Task 6 cause. C22 recorded no separate per-module warning set for the acceptance suite.

## Hygiene

- No installs.
- `.venv` was absent before and after every Python command.
- The dev database `ai_slide_generator` was untouched; the fixtures use throwaway databases.
- No other worktree was touched.
- No push, PR, merge or subagent.
- `lsof -i :3000` was empty before and after every Playwright run. No vite or playwright-test process was left running; the two `playwright-mcp` processes pre-exist and are not mine.
- `git grep "T266_6_\|TASK6_"` over `frontend src tests` gives 0.
- The diff audit over `e55ca1852..HEAD` found no `routes/tools`, `task.startswith`, `served_models`, `response_format`, `run_candidate`, `ServingEndpoints`, `.query(` or #267 route.
- Drivers and outputs are only in `/tmp/t266-6/`.

## Concerns

1. **Step 5 is not done** (whole-branch range proof, review package, local merge). It is controller work under this dispatch's no-merge and no-subagent constraints.
2. **The probe is enabled while non-endpoint fields are unsaved.** This is the brief's exact rule ("disabled while local endpoint edits are unsaved"). The probe always tests the saved sampling values (C12), and the result copy says "saved candidate". If the controller wants any unsaved edit to disable it, that is a one-condition change in `probeEndpointUnsaved` plus the component test.
3. **The client adds an identity check the backend does not declare** (the same class as `readDraftLegacyPromptSource`'s client-only contract). A probe 200 or typed failure whose lock, endpoint or hash differs from the client's saved candidate is shown as "server response was invalid". A future backend that reports, for example, the latest lock would surface that way, not as a parse error.
4. **A probe 409 marks the probed role with the conflict panel and keeps its local form**, as Upgrade does, by reusing `mergeConflict`. Save is then disabled until Keep local or Reload server, while Test structured output stays enabled with the adopted lock. The component test pins this behaviour.
5. **`STRUCTURED_OUTPUT_PROBE_FAILURES` in `mocks.ts` is a hand copy of the server's three messages.** No Python join test reads it. If the server copy changes, only the browser and component assertions drift. A join in the style of `test_endpoint_name_policy_client_join.py` could be added later.

## Triple check

`git status --porcelain`, `git diff HEAD` and `git diff --cached` were all empty after the implementation commit, all mutation rows and all gates, before this report was added.
