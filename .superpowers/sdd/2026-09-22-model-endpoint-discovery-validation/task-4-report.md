# Task 4 report: typed discovery client and Model-tab endpoint controls (#266)

**Status:** DONE_WITH_CONCERNS (see the end).

- `TASK_BASE=95b867c2cba9c391d4872a65fbf94edb5cffebb5` (pinned)
- `b6c1ae2bdfe076adb517bb86188739c8945a0718` `feat: add model endpoint editor discovery (#266)`: implementation, tests, harness migration
- `TASK_HEAD` is the commit that adds this report.

## Files (base..b6c1ae2bd)

| File | Change |
| --- | --- |
| `frontend/src/api/agentDefinitions.ts` | Appended at the end, with `CUSTOM_ANCHORS` untouched (C19). Adds `SystemModelEndpoint`, `ModelEndpointCatalogApiError` (`status` 403\|503, `code`, `retryable`, server `message`), `InvalidModelEndpointCatalogResponseError`, and `getSystemModelEndpoints()`. The function reuses `isPlainRecord`/`hasExactKeys`. It enforces exact `{items}` and exact item keys, a non-empty string `name`, `string\|null` for the other three fields, and unique names. It reads the JSON once and does no caching or coalescing. A 200 that fails parsing, or any other 2xx, is Invalid. A 403 or 503 that carries exactly the paired code and `retryable` (forbidden/false, unavailable/true) is typed. Any other non-2xx is `AgentDefinitionApiError`. A transport failure propagates unchanged. |
| `AgentDefinitionWorkbench.tsx` | Adds `useModelEndpointCatalog()`, owned **once** per workbench (C16). Its state is `idle\|loading\|ready\|empty\|error`, the last good list, and the error message. `catalogRequestTokenRef` only drops out-of-order responses (C15). `open()` fetches only while the token is 0, so the first Model-tab opening of any role triggers one GET, and **Refresh models** always triggers one. The hook is not wired to `pendingSave` or `useDraftEditor`. Errors map to the server's message for a typed error, or to fixed local copy for invalid, other-status and network failures. |
| `DefinitionEditor.tsx` | Adds the props `modelCatalog`, `onOpenModelTab` (called from `selectTab('model')`) and `onRefreshModels`. The Model panel gains: **Refresh models** (always enabled); **Search discovered models** (`type=search`, local, per role, case-insensitive over name, display name and description); a polite live line for loading, the exact empty copy, and no-match; `role="alert"` on failure; and a **Discovered models** radiogroup. Each radio's accessible name is the exact `name`, and its display name and description are its accessible description. A radio is `checked` iff `local.endpoint_name === name`, and its `onChange` is only `onEdit(agentKey, 'endpoint_name', item.name)`. The #263 input keeps its id and setter and is relabelled **Custom endpoint name** under an "Advanced" caption. Its message is the server field error if present, otherwise the local policy message. |
| `draftEditorState.ts` | This file is outside the brief's list. C18 places the policy here. Adds `endpointNamePolicyError()` and `ENDPOINT_URL_NOT_ALLOWED_MESSAGE`, which mirror `validate_endpoint_name_policy` (the URL prefix regex, `/ \ ? # %`, ASCII controls 0x00–0x1f and 0x7f, and `.`/`..`). `validateDraftForm` applies it after the blank check. Accepted candidates are byte-identical (C10). The reducer, counter and gate are untouched. |
| `AgentDefinitionWorkbench.test.tsx` | Every harness now routes by URL (C17): `mockFetchResponse`, `mockWorkbenchWithPuts` (new optional `catalog` responder), `mockWorkbenchApi`, `mockForSchemaUpgrade`, and the two inline Output Schema mocks. Each has a default accepting catalog. GET-count assertions (`:404`, `:806`, `:1091`, `:1408`, `:1657`) now count `workbenchGets` and add `catalogGets(...) == 0`, and `:404` keeps its total `toHaveBeenCalledTimes(1)`. All 5 `{ name: 'Endpoint' }` locators become `Custom endpoint name`, with 0 remaining and no assertion deleted. "Refresh models" is added to the forbidden-name spare list. There are 74 new tests. |
| `frontend/tests/fixtures/mocks.ts` | The only edits are one type added to the import and fixtures appended at the end: `SEED_MODEL_ENDPOINT_NAME`, `syntheticSystemModelEndpoints`, `syntheticNewerModelEndpoint`, `syntheticModelEndpointDiscovery()`, `MODEL_ENDPOINT_DISCOVERY_FORBIDDEN` and `MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE`. None of the new names is a prefix of the five joined names, and the strict-JSON blocks are untouched (C19). |
| `frontend/tests/e2e/agent-definition-workbench.spec.ts` | This file is outside the brief's list; C17 requires it. `installWorkbenchMock` registers one default `**/model-endpoints` route next to the workbench route. All 19 `{ name: 'Endpoint' }` locators become `Custom endpoint name`, with 0 remaining. |

## Accessible-name collision check (Playwright substring vs Testing Library exact)

- **Custom endpoint name.** It is a textbox. No other textbox name contains it, and it contains no other locator's name, so the old `'Endpoint'` substring hazard is gone because that locator no longer exists.
- **Search discovered models.** It is a searchbox, not a textbox, and contains neither "Endpoint" nor any provenance label.
- **Refresh models.** It is the only button containing "Refresh" or "models".
- **Discovered models.** It is a radiogroup, not a group or region, so the `/^Custom block/`, `Retained …` and `Protected stage:` group regexes and the region names cannot match it.
- **Radio names.** These are the fixture endpoint names. `databricks-claude-opus-4-6` is not a substring of `…-4-7`.
- **Forbidden stems.** "Refresh models" and the fixture names do not trip `FORBIDDEN_ACTION_STEMS`, and the sweep test inside the Model tab passes.
- **Live copy.** I avoided `role="status"`, so the existing `getByRole('status')` queries are unaffected.

## RED (before implementation; tests and fixtures written, no production code)

The raw output is `/tmp/t266-4/red-vitest.txt` and `/tmp/t266-4/red-typecheck.txt`.

- **Vitest:** `npm run test:unit -- …/AgentDefinitionWorkbench.test.tsx` gave **75 failed, 74 passed (149)**. Causes, deduplicated:
  - `getSystemModelEndpoints is not a function`: every client test.
  - `expected { ok: true … } to deeply equal { ok: false … }`: the 15 policy rejections, because there was no local policy.
  - `Unable to find role="radiogroup" and name "Discovered models"`, `…textbox "Custom endpoint name"`, `…button "Refresh models"`, the empty text, and `role="alert"`: the controls were absent. The 9 migrated pre-existing tests failed only on the missing "Custom endpoint name".
- **Typecheck:** `npm run typecheck` exited **2**, with 4 × TS2305 (no exported `ModelEndpointCatalogApiError`, `getSystemModelEndpoints`, `InvalidModelEndpointCatalogResponseError` or `SystemModelEndpoint`).
  - Correction to the brief's hazard note: `*.test.tsx` under `src/` **is** typechecked, and `tests/fixtures/mocks.ts` is typechecked transitively through its import. The e2e spec is not.
- **Two test bugs** were fixed between RED and GREEN. Neither was a product issue.
  1. An `it.each` table built `apiResponse` objects at module load, so `vi.restoreAllMocks()` had reset their `json` mocks. The table now builds the response per test.
  2. The manual-save leak check looked for the substring `token`, which matches `max_tokens`. It now checks for quoted key names such as `"token"` and `"host"`, plus `http` and `://`.

## GREEN gates (all run from `frontend` at the tree of `b6c1ae2bd`)

| Gate | Command | Result |
| --- | --- | --- |
| Plan Task 4 Vitest | `npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx` | 149 passed |
| The four workbench files | `npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/{draftEditorState.test.ts,AgentDefinitionWorkbench.test.tsx,AssemblyEditor.test.tsx,OutputSchemaEditor.test.tsx}` | 4 files, 299 passed |
| Whole unit suite (phase-B baseline 14 files / 333) | `npm run test:unit` | **14 files, 407 passed**, 0 failed, 0 skipped. That is 333 + 74 new; no pre-existing test was removed |
| Typecheck | `npm run typecheck` | exit 0 |
| ESLint | `npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts` (phase B's command; the plan names no ESLint command) | exit 0, no findings |
| Playwright (baseline 60) | `npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1` | **60 passed**. `lsof -i :3000` was empty before and after |
| Backend text-read joins | `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly tests/unit/test_prompt_assembler.py tests/unit/test_agent_definition_workbench_routes.py` | **270 passed** (79 + 191), 10 warnings, which are the pre-existing Pydantic and langchain causes. `test ! -e .venv` passed before and after |

## Clause-to-mutation table

- **Driver:** `/tmp/t266-4/sab.py`. Specs are in `/tmp/t266-4/specs.json` (built by `mkspecs.py`), and the outputs are in `sab-v.out` and `sab-p.out`.
- **Per row:**
  1. The anchor count must be exactly 1.
  2. The mutation is applied with its `T266_4_Snn` marker, and `grep -c` must count 1.
  3. The scope is run.
  4. The file is restored with `git checkout b6c1ae2bdfe076adb517bb86188739c8945a0718 -- <file>`, and `git diff <SHA> -- <file>` must be 0 lines.
  5. `grep -c` on the marker must count 0.
  6. The scope is re-run for GREEN.
- **Scopes:**
  - V = `npx vitest run src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx` (149).
  - P = `npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1` (60).
- **Result:** every row had anchor 1, marker 1 then 0, a 0-line restore diff, RED ≥ 1, and a full GREEN. No row was free within its scope.
- **Marker check at HEAD:** `grep -rc T266_4_S frontend/src frontend/tests` found no non-zero file.

| # | Clause | File | Mutation (marker) | Anchor | Marker after / restored | Scope | RED (failing tests) | Restore diff | GREEN |
|---|---|---|---|---|---|---|---|---|---|
| S01 | selection copies exactly item.name | `DefinitionEditor.tsx` | `onChange={() => onEdit(agentKey, 'endpoint_name', item.name.toLowerCase() /* T266_4_S01 */)}` | 1 | 1 / 0 | V | 1: selection copies exactly the item name into the endpoint form value and nothing else | 0 | Tests  149 passed (149) |
| S02 | selection leaves numeric values unchanged | `DefinitionEditor.tsx` | `onChange={() => { onEdit(agentKey, 'endpoint_name', item.name); onEdit(agentKey, 'temperature', '0.5'); /* …` | 1 | 1 / 0 | V | 2: a newer discovered item never moves the seed until it is explicitly selected and saved; selection copies exactly the item name into the endpoint form value and nothing else | 0 | Tests  149 passed (149) |
| S03 | entry checked state reflects the local endpoint only | `DefinitionEditor.tsx` | `checked={entry.saved.model.endpoint_name === item.name /* T266_4_S03 */}` | 1 | 1 / 0 | V | 5: a URL- or path-shaped custom name "https://example.cloud.databricks.com/serving-endpoints/x/invocations" shows the local table message and sends zero PUT; a URL- or path-shaped custom name "serving-endpoints/../secrets" shows the local table message and sends zero PUT; a URL- or path-shaped custom name "x?token=abc" shows the local table message and sends zero PUT; saves a manual exact name as only the lock plus the five editable leaves and retains it; +1 more | 0 | Tests  149 passed (149) |
| S04 | catalog read only on Model-tab opening | `DefinitionEditor.tsx` | `if (tab !== 'prompt') onOpenModelTab(); // T266_4_S04` | 1 | 1 / 0 | V | 4: fetches the catalog once on the first Model-tab opening of any role and again only on Refresh models; toggling the picker, typing guidance and navigating send zero requests; links an already_current 422 to the Assembly tab and changes no local byte; persists role, tab, and Admin-tab state across an upgrade without another GET | 0 | Tests  149 passed (149) |
| S05 | one GET per workbench; later openings do not refetch | `AgentDefinitionWorkbench.tsx` | `refresh(); // T266_4_S05` | 1 | 1 / 0 | V | 2: binds a typed server endpoint issue to the custom field, keeps every unsaved value, and retries without remount; fetches the catalog once on the first Model-tab opening of any role and again only on Refresh models | 0 | Tests  149 passed (149) |
| S06 | older success never overwrites newest | `AgentDefinitionWorkbench.tsx` | `// T266_4_S06 ⏎         setCatalog({ status:` | 1 | 1 / 0 | V | 1: an older refresh response never overwrites the newest one | 0 | Tests  149 passed (149) |
| S07 | older failure never overwrites newest | `AgentDefinitionWorkbench.tsx` | `// T266_4_S07 ⏎         setCatalog((current) => ({ ⏎           status: 'error',` | 1 | 1 / 0 | V | 1: an older refresh response never overwrites the newest one | 0 | Tests  149 passed (149) |
| S08 | failure keeps the last good list | `AgentDefinitionWorkbench.tsx` | `items: [], // T266_4_S08` | 1 | 1 / 0 | V | 1: refresh replaces the prior list only after a success and keeps it through loading and failure | 0 | Tests  149 passed (149) |
| S09 | loading keeps the last good list | `AgentDefinitionWorkbench.tsx` | `setCatalog({ status: 'loading', items: [], errorMessage: null }); // T266_4_S09` | 1 | 1 / 0 | V | 1: refresh replaces the prior list only after a success and keeps it through loading and failure | 0 | Tests  149 passed (149) |
| S10 | empty success is the empty state | `AgentDefinitionWorkbench.tsx` | `'ready' /* T266_4_S10 */` | 1 | 1 / 0 | V | 1: says exactly when no foundation-model endpoint is available and keeps the saved endpoint | 0 | Tests  149 passed (149) |
| S11 | catalog refresh is outside the pending gate | `DefinitionEditor.tsx` | `onClick={onRefreshModels} disabled={operationsDisabled} /* T266_4_S11 */` | 1 | 1 / 0 | V | 1: the catalog read stays outside the one pending gate in both directions | 0 | Tests  149 passed (149) |
| S12 | search is case-insensitive | `DefinitionEditor.tsx` | `const needle = search.trim(); // T266_4_S12` | 1 | 1 / 0 | V | 1: searches locally and case-insensitively and reports no match without changing the selection | 0 | Tests  149 passed (149) |
| S13 | search covers description | `DefinitionEditor.tsx` | `[item.name, item.display_name /* T266_4_S13 */]` | 1 | 1 / 0 | V | 1: searches locally and case-insensitively and reports no match without changing the selection | 0 | Tests  149 passed (149) |
| S14 | no-match is reported | `DefinitionEditor.tsx` | `modelCatalogStatus = ''; // T266_4_S14` | 1 | 1 / 0 | V | 1: searches locally and case-insensitively and reports no match without changing the selection | 0 | Tests  149 passed (149) |
| S15 | failure is a role=alert | `DefinitionEditor.tsx` | `{false /* T266_4_S15 */ && modelCatalog.errorMessage !== null && (` | 1 | 1 / 0 | V | 6: a 200 failure is an alert that preserves the saved endpoint and recovers through Refresh models; a 403 failure is an alert that preserves the saved endpoint and recovers through Refresh models; a 500 failure is an alert that preserves the saved endpoint and recovers through Refresh models; a 503 failure is an alert that preserves the saved endpoint and recovers through Refresh models; +2 more | 0 | Tests  149 passed (149) |
| S16 | local URL message shown on the custom field | `DefinitionEditor.tsx` | `    /* T266_4_S16 */ ⏎ ` | 1 | 1 / 0 | V | 3: a URL- or path-shaped custom name "https://example.cloud.databricks.com/serving-endpoints/x/invocations" shows the local table message and sends zero PUT; a URL- or path-shaped custom name "serving-endpoints/../secrets" shows the local table message and sends zero PUT; a URL- or path-shaped custom name "x?token=abc" shows the local table message and sends zero PUT | 0 | Tests  149 passed (149) |
| S17 | server endpoint issue binds to the custom field | `DefinitionEditor.tsx` | `const endpointMessage = /* T266_4_S17 */` | 1 | 1 / 0 | V | 2: associates all five 422 messages with their labelled inputs without an opaque request alert; binds a typed server endpoint issue to the custom field, keeps every unsaved value, and retries without remount | 0 | Tests  149 passed (149) |
| S18 | policy rejects % | `draftEditorState.ts` | `const ENDPOINT_PATH_METACHARACTERS = /[/\\?#]/; // T266_4_S18` | 1 | 1 / 0 | V | 1: rejects URL- or path-shaped "a%2Fb" with the table message and no candidate | 0 | Tests  149 passed (149) |
| S19 | policy rejects every ASCII control character incl. 0x1f | `draftEditorState.ts` | `if (code < 0x1f \|\| code === 0x7f) return true; // T266_4_S19` | 1 | 1 / 0 | V | 1: rejects URL- or path-shaped "unit\u001fsep" with the table message and no candidate | 0 | Tests  149 passed (149) |
| S20 | policy rejects .. | `draftEditorState.ts` | `    /* T266_4_S20 */) {` | 1 | 1 / 0 | V | 1: rejects URL- or path-shaped ".." with the table message and no candidate | 0 | Tests  149 passed (149) |
| S21 | validateDraftForm applies the policy | `draftEditorState.ts` | `    if (endpointPolicyError === 'T266_4_S21') errors.endpoint_name = endpointPolicyError;` | 1 | 1 / 0 | V | 18: a URL- or path-shaped custom name "https://example.cloud.databricks.com/serving-endpoints/x/invocations" shows the local table message and sends zero PUT; a URL- or path-shaped custom name "serving-endpoints/../secrets" shows the local table message and sends zero PUT; a URL- or path-shaped custom name "x?token=abc" shows the local table message and sends zero PUT; rejects URL- or path-shaped "  http://example.invalid" with the table message and no candidate; +14 more | 0 | Tests  149 passed (149) |
| S22 | serializer closed to the five leaves | `draftEditorState.ts` | `        endpoint_name: form.endpoint_name, ⏎         source: 'discovery', // T266_4_S22 ⏎ ` | 1 | 1 / 0 | V | 17: allows explicit same-content save and adopts its incremented lock without claiming Clean; dismisses only the recovery copy after Reload server without writing; keeps local conflict values without writing and retries with the refreshed global lock; rejects eight-role 409 as an invalid response, preserves every form, and permits explicit retry; +13 more | 0 | Tests  149 passed (149) |
| S23 | item keys are exact | `agentDefinitions.ts` | `    // T266_4_S23 ⏎ ` | 1 | 1 / 0 | V | 1: rejects a malformed 200 with an item with a task field as an invalid catalog response | 0 | Tests  149 passed (149) |
| S24 | items must be plain records | `agentDefinitions.ts` | `  return (typeof value === 'object' && value !== null && !Array.isArray(value)) // T266_4_S24 ⏎     && hasE…` | 1 | 1 / 0 | V | 1: rejects a malformed 200 with a class-instance item as an invalid catalog response | 0 | Tests  149 passed (149) |
| S25 | names are unique | `agentDefinitions.ts` | `  // T266_4_S25 ⏎ ` | 1 | 1 / 0 | V | 1: rejects a malformed 200 with duplicate names as an invalid catalog response | 0 | Tests  149 passed (149) |
| S26 | names are non-empty | `agentDefinitions.ts` | `typeof value.name === 'string' /* T266_4_S26 */ ⏎     && isNullableString(value.display_name)` | 1 | 1 / 0 | V | 1: rejects a malformed 200 with an empty name as an invalid catalog response | 0 | Tests  149 passed (149) |
| S27 | 403/503 code-retryable pairing | `agentDefinitions.ts` | `    // T266_4_S27 ⏎ ` | 1 | 1 / 0 | V | 1: does not type a 503 that is not retryable as a catalog envelope | 0 | Tests  149 passed (149) |
| S28 | non-200 2xx is invalid | `agentDefinitions.ts` | `  // T266_4_S28 ⏎ ` | 1 | 1 / 0 | V | 1: does not type a 200-range but not 200 as a catalog envelope | 0 | Tests  149 passed (149) |
| S29 | body read once | `agentDefinitions.ts` | `    const items = parseSystemModelDiscovery(await response.json()); // T266_4_S29` | 1 | 1 / 0 | V | 2: reads the discovery list once with a bare GET and returns the exact items in server order; rejects an unparseable 200 body as an invalid catalog response | 0 | Tests  149 passed (149) |
| S30 | never cache or coalesce | `agentDefinitions.ts` | `let coalescedCatalog: Promise<SystemModelEndpoint[]> \| null = null; // T266_4_S30 ⏎ export function getSys…` | 1 | 1 / 0 | V | 10: a URL- or path-shaped custom name "https://example.cloud.databricks.com/serving-endpoints/x/invocations" shows the local table message and sends zero PUT; a URL- or path-shaped custom name "serving-endpoints/../secrets" shows the local table message and sends zero PUT; a URL- or path-shaped custom name "x?token=abc" shows the local table message and sends zero PUT; a newer discovered item never moves the seed until it is explicitly selected and saved; +6 more | 0 | Tests  149 passed (149) |
| S31 | e2e default catalog route (c17) | `agent-definition-workbench.spec.ts` | `  await page.route('**/T266_4_S31-unused', (route) => route.fulfill({` | 1 | 1 / 0 | P | 7: tests/e2e/agent-definition-workbench.spec.ts:398:3 › eight-role 409 is contained, write-stable, lossless, and explicitly retryable; tests/e2e/agent-definition-workbench.spec.ts:398:3 › malformed 200 is contained, write-stable, lossless, and explicitly retryable; tests/e2e/agent-definition-workbench.spec.ts:398:3 › mistyped 422 is contained, write-stable, lossless, and explicitly retryable; tests/e2e/agent-definition-workbench.spec.ts:398:3 › network error is contained, write-stable, lossless, and explicitly retryable; +3 more | 0 | 60 passed (47.4s) |

Notes on the table:
- **S30 (coalescing) also turned 9 component tests RED.** The module-level coalesced promise outlived a held response in an earlier test, which shows exactly why nothing may be shared. The target test `never caches or coalesces` is among the failures.
- **S31 turned 7 Playwright tests RED:** the save-failure matrix at `:398`. Without the default route, the catalog GET reaches the dev proxy, fails, and adds a `role="alert"` that the tests' `page.getByRole('alert')` assertions then count.
- **S04 turned 3 pre-existing tests RED as well as the target.** With eager fetching, an Assembly or Output Schema click reads the catalog, and those tests' narrowed `catalogGets == 0` and total-request assertions catch it.

**Not exercised, as instructed:** `TASK4_CONTROLLER_DISPLAY_NAME_SABOTAGE` and `TASK4_REVIEWER_SELECTION_AUTOSAVE_SABOTAGE`. The guards they will hit:
- **Controller target (`item.display_name ?? item.name`).** `selection copies exactly the item name into the endpoint form value and nothing else` selects `databricks-gpt-oss-120b`, whose display name is "GPT OSS 120B", and asserts the exact value. `a newer discovered item never moves the seed until it is explicitly selected and saved` asserts the exact PUT name. S01 (`.toLowerCase()`) proved that the same line is on the executed path.
- **Reviewer target (`onSave(agentKey)` from the selection handler).** `selection never saves: no PUT after the selection settles, and Save stays an explicit action` returns a normal 200 for any PUT. After a macrotask flush it asserts 0 PUT, `Unsaved` and lock 0. The selection test (0 PUT) and the newer-item test (0 PUT before the explicit Save) also cover it. S02 proved that extra calls from the handler are observable.

## Design rulings

- **Radios, not buttons, for selectable entries.** A radio's checked state is exactly "local endpoint equals this name". A manual name therefore checks nothing, and re-clicking the checked seed makes no edit (tested). Radio names are the exact endpoint names. `docs` is not rendered, so no link appears and no link name enters the forbidden sweep.
- **The local URL message is shown live** on the custom field. Save is disabled while the policy fails, because `saveDisabled` already derives from `validateDraftForm`. Without a live message, a user would see a disabled Save with no reason. A server field error takes precedence over it.
- **The policy mirror is exact.** `\s` differs slightly between Python and JS (for example U+FEFF). This cannot change a verdict: every URL-prefix match contains `/`, so the metacharacter check rejects it anyway, under the same code and message.
- **Error copy.**
  - Typed 403/503: the server's own message.
  - Malformed 200: "Model discovery returned an invalid response."
  - Other status: "Unable to load discovered models (N)."
  - Network: "Unable to load discovered models. Check your connection and try again."
  - Every alert ends with "Use Refresh models to try again." None of this copy contains an endpoint name or payload text.
- **Refresh during loading.** Refresh stays enabled while a load is in flight, and each click is one GET. The newest response wins.

## Concerns

1. **Two files beyond the brief's list:** `draftEditorState.ts` (C18) and the e2e spec (C17). `AgentDefinitionWorkbench.tsx` is C16's addition. `draftEditorState.test.ts` was not modified: the policy table lives in `AgentDefinitionWorkbench.test.tsx` beside the component flows.
2. **No automated join between the TS policy mirror and the Python policy.** C18 recommends one. The TS table uses the same case classes as C4, and S18–S21 prove each clause. A true join would need a Python test to read `draftEditorState.ts` as text, which adds another C19-style text-read file, so I left it for the controller to decide.
3. **The accepted-name side of the mirror is not mutation-tested for over-rejection.** For example, a mutation that also rejects spaces would go RED only through `accepts "Team Shared Endpoint (EU)" verbatim` and the exotic-selection test. I did not run that as a row.
4. **Task 6 inheritance.** Any Task 6 test that needs a non-default catalog must register its own `**/model-endpoints` route after `installWorkbenchMock`, because later routes win. `mockWorkbenchApi` still parses every unmatched non-GET as a PUT, so the probe POST must be routed by URL (C17).
5. **The discovery GET's 30–90 s worst case** (Task 3) shows as "Loading discovered models…" with Refresh enabled. Clicking Refresh supersedes the view but cannot cancel the in-flight request. There is no `AbortController`, by design, to keep the change small.

## Triple check

`git status --porcelain`, `git diff HEAD` and `git diff --cached` were all empty after the sabotage runs and gates (before this report was added).

## Fix round 1

- **Base (pinned):** `1b08498f4c4dee5a1fb75ff1ffe072c665e2d9f7`, the controller ledger commit.
- **Fix commit:** `03002d6693e847acea2fb919b80d4d3057eba451` `test: join the client and server endpoint name policies (#266)`. This commit is test and fixture changes only; no production line changed.

### I-1: TS/Python endpoint-policy join

I made a **new small module**, `tests/unit/test_endpoint_name_policy_client_join.py`, with 25 tests. Adding it to the 1,300-line `test_prompt_assembler.py` would have widened that file's text-read surface for an unrelated concern.

- **Shared case table.** The TS reject/accept arrays moved into a strict-JSON block, `ENDPOINT_NAME_POLICY_CASES: Record<'rejected' | 'accepted', string[]>`, appended at the end of `frontend/tests/fixtures/mocks.ts`.
  - The Vitest policy table now uses `it.each(ENDPOINT_NAME_POLICY_CASES.rejected / .accepted)`.
  - The Python module parses the block the same way `_client_json_fixture` does (`export const NAME:`, then `= {`, then `\n};`).
  - Every case is decided three ways: by `validate_endpoint_name_policy`, by the client's pinned rules evaluated in Python, and by the table's verdict. All three must agree.
  - The table asserts that the rejected and accepted lists are non-empty and disjoint.
- **Pins.** Each is a text read of `draftEditorState.ts`:
  - `const ENDPOINT_URL_PREFIX = /…/i;`. The line must match `^const ENDPOINT_URL_PREFIX = /(.*)/([a-z]*);$` exactly once. Its source with `\/` replaced by `/` must equal `_URL_PREFIX.pattern`, and the flag must be `i`.
  - `const ENDPOINT_PATH_METACHARACTERS = /[/\\?#%]/;`. Its class plus `\x00-\x1f\x7f` must equal `_PATH_METACHARACTERS.pattern`, with no flags.
  - The control rule: the exact line `if (code <= 0x1f || code === 0x7f) return true;`, exactly once.
  - The `endpointNamePolicyError` condition block, including `name === '.'` and `name === '..'`, exactly once, plus `_DOT_SEGMENTS == {".", ".."}`.
  - The `validateDraftForm` call `endpointNamePolicyError(form.endpoint_name)`, exactly once.
  - The message: `export const ENDPOINT_URL_NOT_ALLOWED_MESSAGE = '<single-quoted>';` must equal the server failure's `message`, with `retryable` False.
- **Newly text-read lines** (C19-style hazards):
  - In `draftEditorState.ts`: the two regex `const` lines, the control line, the six-line condition block, the call site, and the message `const`.
  - In `mocks.ts`: the `ENDPOINT_NAME_POLICY_CASES` block, which must stay strict JSON.
  - Rules that follow from these reads:
    - No trailing comment on the two regex lines. The `;$` anchor refuses one, as F1/F2 below show.
    - The message stays single-quoted and on one line.
    - The condition block is not to be reflowed.
    - No new constant whose name has `ENDPOINT_NAME_POLICY_CASES` as a prefix may be placed above that block.

### Minor 2: all-GETs backstop

`allGets()` counts every GET to any URL. `expect(allGets(fetchMock)).toHaveLength(1)` was added beside the narrowed workbench and catalog counts at the three sites (now `:863`, `:1151`, `:1469`).

### Sabotage

- **Drivers:** `/tmp/t266-4/sab2.py` and `sab2b.py`. Outputs are in `fr1-sab.out` and `fr1-sab-b.out`.
- **Per row:** anchor count 1; the `T266_4_Fn` marker counted with `grep -c` (1 after mutating, 0 after restoring); restore with `git checkout 03002d6693e847acea2fb919b80d4d3057eba451 -- <file>` and a 0-line diff; then GREEN.
- **Scopes:**
  - J = `pytest -q -p no:randomly tests/unit/test_endpoint_name_policy_client_join.py` (25)
  - C = J plus `tests/unit/test_model_endpoint_catalog.py` (86)
  - V = the Vitest workbench file (149)

| # | Mutation | Scope | RED | GREEN |
| --- | --- | --- | --- | --- |
| F1 | Loosen TS: drop `%` from `ENDPOINT_PATH_METACHARACTERS`. The marker is a trailing comment. | J, V | J 23/25: the trailing comment also breaks the `;$` line anchor, so every case test fails, along with the class pin. V 1: `rejects … "a%2Fb"` | J 25, V 149 |
| F1b | The same mutation, with the marker on its own line | J | **2**: `…metacharacter_literal_plus_control_rule_is_the_server_class`, `…rejected…[a%2Fb]` | 25 |
| F2 | Tighten TS: add a space to the class. The marker is a trailing comment. | J, V | J 23/25 (anchor cause, as in F1). V 4: `accepts "Team Shared Endpoint (EU)"`, `accepts " leading and trailing "`, and the manual-save and 422-correction flows | J 25, V 149 |
| F2b | The same mutation, with the marker on its own line | J | **3**: the class pin, `…accepted…[Team Shared Endpoint (EU)]`, `…accepted…[ leading and trailing ]` | 25 |
| F3 | Loosen Python: drop `%` from `_PATH_METACHARACTERS` | C | 4: the class pin, `…rejected…[a%2Fb]`, and 2 × `test_model_endpoint_catalog` `[percent-escape]` | 86 |
| F4 | Loosen the TS control rule: `code < 0x1f` | J | 1: the class-and-control-rule pin. The table has `unit\u001fsep`, but the Python emulation evaluates the pinned rule rather than the mutated text, so only the pin catches this | 25 |
| F5 | Loosen the TS dot rule: drop `\|\| name === '..'` | J | 1: the dot-segment, condition and message pin | 25 |
| F6 | Drift the TS message | J | 1: the same pin | 25 |
| F7 | Loosen Python: `_DOT_SEGMENTS = {"."}` | C | 4: the dot pin, `…rejected…[..]`, and 2 × catalog `[dot-dot]` | 86 |
| F8 | Minor 2: a third-URL GET at the start of `upgradeProtectedAssembly` | V | 14. These are the two restored backstops at `:1151` and `:1469` plus 12 shared-gate tests, whose `requestCount` also counts every fetch | 149 |

### Gates (at `03002d669`)

- **Python:** `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly tests/unit/test_endpoint_name_policy_client_join.py tests/unit/test_prompt_assembler.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_model_endpoint_catalog.py` gave **356 passed** (25 + 79 + 191 + 61), with 10 warnings from the pre-existing causes. `test ! -e .venv` passed. `ruff check` on the new module is clean.
- **Vitest:** `(cd frontend && npx vitest run src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)` gave **149 passed**.
- **Typecheck:** `npm run typecheck` exit 0.
- **ESLint:** `npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts` exit 0.
- **Playwright** was not run, because the spec is untouched.

### Residual

- **The emulation reads the pinned rule, not the literal TS code.** `_client_rejects` evaluates the control and dot rules as Python code, not by reading their TS text. Those two clauses are guarded by the text pins (F4, F5) rather than case-by-case, while the two regexes are compiled from the TS source and so are guarded both ways.
- **The review's other Minors stay deferred, as instructed:** M-1 (retry copy for non-retryable errors), M-3 and M-4.
