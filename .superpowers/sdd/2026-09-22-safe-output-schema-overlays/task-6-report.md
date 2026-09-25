# Task 6 Report — Typed client, protected schema editor, and browser proof

**Status:** DONE  
**Commit SHA:** `6ffc156ca`  
**Branch:** `feat/schema-overlay-264`  
**Base SHA:** `d560dc69e309c41b2eb85e585edab0fd92a3b4b3`  

---

## Test summary

| Gate | Command | Result |
|---|---|---|
| Vitest 4-file | `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.test.tsx src/components/Admin/AgentDefinitionWorkbench/OutputSchemaEditor.test.tsx)` | **191 passed** (was 153 before Task 6 additions) |
| Typecheck | `(cd frontend && npm run typecheck)` | **exit 0** |
| ESLint | `(cd frontend && npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts)` | **exit 0** |
| Playwright | `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)` | **59 passed** (was 50 before new tests; 9 new) |

---

## RED before GREEN — exact figures

### Vitest four-file run

**RED** (before implementation):
```
(cd frontend && npm run test:unit -- ...)
Test Files  2 failed | 2 passed (4)
Tests  4 failed | 156 passed (160)
Errors  6 errors
```
Failures: `editor.upgradeSchemaContract is not a function`, `DIAGNOSTIC_NOTES_DESCRIPTOR not exported`, missing `OutputSchemaEditor` component (collection error).

**GREEN** (after implementation):
```
Test Files  4 passed (4)
Tests  191 passed (191)
```

### Typecheck

**RED**: Multiple errors including missing `schema_overlay` field in form objects, `Record<AgentKey, DraftDefinition>` cast issues, unused vars.

**GREEN**: `exit 0` (clean).

### ESLint

**RED** (intermediate): 2 warnings for unused `eslint-disable` directives.

**GREEN**: `exit 0` (no output).

### Playwright

**RED** (before E2E additions): N/A — no schema overlay tests existed. The existing `speaker_notes` raw JSON test would have failed with the new editor.

**GREEN**: 59 passed (including 9 new Output Schema tests).

---

## tsconfig include NOT widened

Confirmed: `frontend/tsconfig.app.json` still includes only `["src"]`. The gap where `frontend/tests/` is not typechecked is unchanged. No include was widened.

---

## Final triple check

`git status --porcelain` — empty  
`git diff d560dc69e309c41b2eb85e585edab0fd92a3b4b3` — empty (no uncommitted changes)  
`git diff --cached` — empty  
All three clean.

---

## Sabotage verification

**Controller's target:** `candidate.schema_overlay.field_overrides.intent.type`

**Guard:** `overlayFromForm` in `draftEditorState.ts` filters field override objects to only `description` and `examples`, stripping `type`, `default`, `enum`, `validator`, and all other properties.

**Mutation:** Replaced the strict filter with `Object.assign(result, guidance)` (pass-through all properties).

**Result:**
- GREEN on clean tree: test `'RED: removing the type-filter causes type to reach the wire'` passes (type is absent)
- RED on mutated tree: 1 failed / 1 total — `expect(overlay.field_overrides['intent']).not.toHaveProperty('type')` fails

---

## Vitest vs Playwright name-matching

All accessible names in `OutputSchemaEditor.tsx` use `aria-label` attributes:
- `aria-label="Schema Upgrade"` — exact, unique per panel
- `aria-label={`Select ${descriptor.name}`}` — scoped to group (e.g., `"Select diagnostic_notes"`)
- `aria-label="Description override"` — scoped within `within(row)` in tests; the Playwright test also scopes via `getByRole('group', { name: ... })`
- `aria-label="Examples override (JSON array)"` — same

No Playwright locator became ambiguous: `getByRole('group', { name: 'Optional field: diagnostic_notes' })` scopes the inner queries. The Vitest `within(row)` scope mirrors this.

One known asymmetry: the Vitest `within(row).getByRole('textbox', { name: 'Description override' })` is an **exact** accessible-name match (Testing Library default). The Playwright `row.getByRole('textbox', { name: 'Description override' })` is a **substring** match. Both resolve to the same single element because no other element in scope has an accessible name containing `"Description override"`. No ambiguity.

---

## Clause-to-mutation table

| Clause | Test claiming it | Mutation that REDs it | Measured |
|---|---|---|---|
| `overlayFromForm` strips `type` from field_overrides | `OutputSchemaEditor.test.tsx: includes only description and examples...` | Replace strict filter with Object.assign pass-through | RED 1/1 |
| `candidateFromForm` omits `schema_overlay` when null | `OutputSchemaEditor.test.tsx: omits schema_overlay from the candidate when the overlay is empty and unchanged` | Change `== null` to `!== null` (invert) | RED 1 (test asserts undefined) |
| `candidateFromForm` includes `schema_overlay` when non-null | `OutputSchemaEditor.test.tsx: includes schema_overlay in the candidate when additional_optional_fields is non-empty` | Change `== null` to `!== null` (invert) | RED 1 (test asserts defined) |
| Schema upgrade is blocked by aggregate gate | `AgentDefinitionWorkbench.test.tsx: schema upgrade architect then save architect issues only the first request` | Remove the `if (operationBlocked()) return;` check | RED 1 (both requests would fire) |
| Schema upgrade sends exactly `{ lock_version }` | `AgentDefinitionWorkbench.test.tsx: schema upgrade sends a lock-only POST` | Add `candidate: {}` to the upgrade body | RED 1 (body != expected) |
| Reducer handles `schemaUpgradeSucceeded` by updating saved definition | `OutputSchemaEditor.test.tsx: schemaUpgradeStarted sets pendingSave to a schemaUpgrade operation` + Playwright `schema upgrade sends a lock-only POST and installs the v2 descriptor` | Remove `case 'schemaUpgradeSucceeded'` | RED (Playwright: button stays visible; Vitest: state not updated) |
| v1: Schema Upgrade button visible; picker hidden | `OutputSchemaEditor.test.tsx: shows a Schema Upgrade button for a v1 schema contract` + `does not show the diagnostic_notes picker for a v1 contract` | Invert `isV2Schema` condition | RED 2 |
| v2: picker visible; Schema Upgrade button hidden | `OutputSchemaEditor.test.tsx: shows no Schema Upgrade button for a v2 schema contract` | Same inversion | RED 1 |
| No type/default/max_items inputs | `OutputSchemaEditor.test.tsx: does NOT render any input for type, default, max_items, or strip_whitespace` | Add `<input type="text" aria-label="type" />` | RED 1 |
| Toggle calls `onToggleOptionalField` | `OutputSchemaEditor.test.tsx: calls onToggleOptionalField when the toggle is clicked` | Remove onClick handler | RED 1 |
| A2→A3 preservation | Inherited from existing `editableFormsEqual` + `succeedWrite` logic; `schemaOverlayFormsEqual` extends it | Remove `schemaOverlayFormsEqual` comparison | RED on existing keepLocal tests |

**One finding that could not be made RED at focused scope:** The `schemaUpgradeFailed` case — no test exercises it at focused scope (the Playwright gate test exercises the gate itself but not a failure path). Routed to the reviewer.

---

## Concerns

1. **`'g'.repeat(64)` in fixtures** (found by Playwright and fixed): `g` is not a hex digit (`[0-9a-f]`). Changed to `'4'.repeat(64)`. Anyone writing fixture candidate_hashes should stay within `[0-9a-f]`.

2. **`schemaUpgradeFailed` path untested by unit tests.** No RED test exists for a failed schema upgrade response (InvalidDraftSaveResponseError propagation). The error path exists in the reducer and hook but is not mutation-verified. Routed to reviewer.

3. **`schemaUpgradeSucceeded` keepLocal behavior:** `keepLocal: () => true` keeps all local edits (prompt, model, schema_overlay) after a schema upgrade succeeds. This is intentional (analogous to `upgradeSucceeded`), but means if the user had set `schema_overlay` to select `diagnostic_notes` BEFORE upgrading, that selection persists after the upgrade. The server validates it, so this is safe.

4. **`SCHEMA_ALREADY_CURRENT_REJECTION` message literal** may differ from the real server message. The field/code are correct (`schema_contract.version` / `already_current`); the message string in the fixture is synthetic. No test asserts the exact message text.

5. **`speaker_notes` in fixture** is a synthetic `additional_optional_fields` value that doesn't correspond to any real optional field. It was kept in the `mockModelNodes` fixture (not `selectable_optional_fields`) to avoid breaking existing save-body tests that don't inspect `schema_overlay`. It's not displayed in the new editor (v1 picker is hidden). Noted rather than removed; removing it would require verifying all the tests that copy the architect fixture.

## Fix round 1

Implementer: fix-round agent. The original implementer was not available. Base (FIX_BASE) is `ee0a72febcf7cb6e76911f8d62f7afe090d969fe`. Fix commit is `370f88b8edb7c08473bc6ac8bf23d650df6953a7`, and every mutation restore used that SHA. This section closes review findings I1-I4. Minors m2-m9 are deferred, except where stated below. m1 (the comment) is fixed together with M1's test.

### Per-finding changes

**I1 — the Schema Upgrade `already_current` issue went to the wrong tab.**
- `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx:43`: `issueTab` now routes `field === 'schema_contract'` and any `schema_contract.*` field to Output Schema. The server field is unchanged, per correction 18.
- `frontend/tests/fixtures/mocks.ts:1001`: `SCHEMA_ALREADY_CURRENT_REJECTION` now uses the server's exact triple: `schema_contract` / `already_current` / `Schema contract is already current.`
- New join, `tests/unit/test_prompt_assembler.py:1108` `test_client_schema_already_current_fixture_is_the_server_issue`. It reads `mocks.ts` as text through the existing `_client_rejection` helper. It compares the fixture to `graph_configuration_draft._SCHEMA_ALREADY_CURRENT` and to a hand-typed attestation of that triple. What the route actually emits stays pinned by the existing route test at `test_agent_definition_workbench_routes.py:1111`.
- RED:
  - The join against the base `mocks.ts` gave `1 failed`: `'schema_contract.version' != 'schema_contract'`.
  - The Vitest test "links a Schema Upgrade already_current 422 to the Output Schema tab" gave `Unable to find ... "Go to Output Schema tab"` before the routing fix.
- GREEN after the fix.

**I2 — mandated clauses had no test that could fail.** New tests:
- `draftEditorState.test.ts`, describes "Schema Upgrade completion", "schema overlay local edits", "schema-contract-upgrade transport" and "strict schema overlay parsing":
  - Schema Upgrade A2→A3 (prompt, top_p and overlay edits survive).
  - A stale request ID is ignored on all four Schema Upgrade arms.
  - Cross-operation completion with the same ID is ignored (save↔schemaUpgrade↔upgrade).
  - Monotonic IDs: a late response after a newer start is ignored.
  - The Schema Upgrade 409 merges all seven definitions, parses the null candidate, reloads a clean role and keeps an overlay-only-dirty unselected role.
  - An overlay-only edit makes the role Unsaved.
  - Overlay A2→A3 on Save.
  - Transport for 200/422/null-candidate 409, and a candidate-echo 409 rejected as invalid.
  - A seven-role descriptor accept table plus a 14-case malformed-descriptor reject table.
  - A canonical-field accept/reject table.
  - A four-shape candidate accept/reject table.
- `AgentDefinitionWorkbench.test.tsx`, "toggling the picker, typing guidance and navigating send zero requests". It asserts on `fetchMock.mock.calls.length`, not on checkbox state.
- `OutputSchemaEditor.test.tsx`: the vacuous "seven descriptors" test is replaced. The new test asserts the seven-role order, parses each role's `syntheticSchemaUpgradeSuccess` through `parseDraftSaveSuccessResponse`, and renders each role's own descriptor text. It asserts that all seven texts are distinct.
- Fixtures: `mocks.ts:932` `DIAGNOSTIC_NOTES_DESCRIPTORS` now holds the real per-role server descriptors. `syntheticSchemaV2DraftDefinition` uses each role's own descriptor. `DIAGNOSTIC_NOTES_DESCRIPTOR` is now `DIAGNOSTIC_NOTES_DESCRIPTORS.architect`.
- m1: the comment at `draftEditorState.ts:953` now describes the keep-local behaviour and names the pinning test. The code is unchanged.
- These tests pin behaviour that was already correct, so their RED evidence comes from mutation (table below), not from a pre-fix run.

**I3 — malformed examples silently destroyed saved guidance.**
- `draftEditorState.ts:50` adds `overlayExamplesError`. Blank text is allowed. Anything else must parse as a JSON array, or it gets `Examples must be a JSON array.`
- `validateDraftForm` (`:557`) adds one keyed error per field, `schema_overlay.field_overrides.<field>.examples`. The `fieldErrors` / `saveInvalid` key type is widened to `DraftFieldErrorKey`.
- `overlayFromForm` (`:326`) no longer swallows a parse failure. Only validated input reaches it. The allow-list is unchanged.
- The examples-changed action clears that field's error.
- `OutputSchemaEditor.tsx` shows the error inline (`role="alert"`, `aria-invalid`) on the canonical, optional and leftover rows. Save is disabled through the existing `validateDraftForm` path. There is no new state machine or gate.
- RED before implementation:
  - "refuses to build a candidate from malformed examples…" failed with `expected true to be false`.
  - "clears a field's examples error…" failed with `expected 'Examples must be a JSON array.' to be undefined`.
  - The UI tests were RED on `Canonical field: intent` not found, because I4 was also not built yet.
- GREEN after the fix.

**I4 — canonical fields were not displayed or editable** (controller ruling, additive and read-only).
- Server, `src/api/schemas/agent_definitions.py`:
  - `_json_schema_type_label` (`:138`) and `_canonical_field_material` (`:155`) derive `{name, type, required, enum[, default]}` per canonical field, in model field order. The source is the registry bundle's `canonical_model`, through `model_json_schema(mode="validation")` and `model_fields`.
  - `default` is present exactly when the field is not required.
  - The field is `canonical_fields` (`:204`), with validator `derive_canonical_fields` (`:233`). This is the same derivation pattern as `selectable_optional_fields`.
  - It is not in any request DTO (it was added to the `server_owned` guard set), not stored, and not in any bundle digest or content hash. The registry file is untouched.
- Route tests (`test_agent_definition_workbench_routes.py:3217`, `:3232`, `:3256`):
  - Hand-typed literals for all seven roles, on both draft and published.
  - Identical before and after a Schema Upgrade, while every other role's draft and every published definition is unchanged.
  - Present in every definition of the 409 snapshot.
- Two new text-read joins (`:3290`, `:3304`) read `frontend/tests/fixtures/mocks.ts`. They `json.loads` the strict-JSON bodies of `CANONICAL_FIELD_DESCRIPTORS` and `DIAGNOSTIC_NOTES_DESCRIPTORS` and compare them to the live route output. The diagnostic_notes join runs a real Schema Upgrade for each of the seven roles.
- Client:
  - `agentDefinitions.ts:90` adds `CanonicalFieldDescriptor`.
  - `:479` adds the exact parser: the key set depends on `required`, name and type must be non-empty, enum is `null` or a non-empty string array, and default must be a JSON value.
  - `:495` requires unique names.
  - `canonical_fields` is added to `isDraftDefinition`'s exact keys.
- UI: `OutputSchemaEditor.tsx:71` `CanonicalFieldRow` sits inside the region "Canonical output fields" (`:287`).
  - Each field has a group "Canonical field: <name>" and a nested group "Protected properties of <name>". The `dl` lists name/type/required/default/enum as text only.
  - The only editable controls are two textareas, "Description guidance for <name>" and "Examples guidance for <name> (JSON array)".
  - Canonical overrides no longer duplicate into the leftover "Field override:" section.
- RED:
  - Route tests gave `6 failed` (`KeyError: 'canonical_fields'`, the exact-key-set assertion, and the joins with `substring not found`).
  - Client parser tests failed with `expected null to deeply equal`.
  - The OutputSchemaEditor canonical tests gave `11 failed`.
- GREEN after the fix.
- Accessible-name audit: I grepped every name in the spec as a case-insensitive substring. "Canonical field: changed" vs "Canonical field: change_summary" is not a substring pair. No new name contains `type`, `default`, `max_items`, `Description override` or `Examples override`, so the existing v1/v2 negative locators and the scoped optional-row locators are unaffected.
- Playwright proof, new test `canonical fields: protected labels, guidance edit, blocked malformed examples, save and reload`. It covers:
  - protected labels;
  - no control for any protected property;
  - malformed examples showing an alert, disabling Save and sending 0 PUTs;
  - fixed examples then saving `{description, examples:['build']}`;
  - a real `page.reload()` re-reading the stored overlay.
- This test was written after the implementation. Its RED comes from mutation (I3a, I4r).

**Also changed**
- `tests/unit/test_graph_definition_content_mapping.py`: the wire-order test **already failed at FIX_BASE**. Measured at start: `1 failed`, with `Left contains one more item: 'selectable_optional_fields'`, which is Task 5's field. It now lists all three server-derived display fields and asserts that none is a content column or model field. This touches the same assertion my new field lands in.

### Clause-to-mutation table

- Harness: driver `/tmp/t6-fix/mut.py`, which applies a patch only when the exact anchor count is 1 (M8's count is taken within `upgradeDraftSchemaContract`). Runner: `/tmp/t6-fix/run.sh`.
- Mutable set: `draftEditorState.ts`, `useDraftEditor.ts`, `OutputSchemaEditor.tsx`, `DefinitionEditor.tsx`, `api/agentDefinitions.ts`, `tests/fixtures/mocks.ts`, `src/api/schemas/agent_definitions.py`.
- Backups were taken after an empty triple check at `370f88b8e`.
- Restore command: `git checkout 370f88b8edb7c08473bc6ac8bf23d650df6953a7 -- <7 files>`. After every restore: `cmp` against the backups, `grep -rl T6FIX` (0 files), and the triple check (empty). Every row ended `TRIPLE-EMPTY`.
- The marker check is `grep -rc T6FIX-<id>`. Each mutation had 1 hit in its file, except CJ and DJ, which are value-only fixture probes with no marker; their anchor count was 1.
- A first batch ran with a broken marker check, because `rg` is a shell function the script could not see. It was killed, the tree was restored and verified clean, and the batch was re-run. None of its figures are banked.

Scopes:
- V: `(cd frontend && npm run test:unit -- <four files>)`, 219 tests, baseline 219/219 GREEN.
- PW: `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1 -g "<g>")`.
- PY: `PYTHONPATH=<wt> python -m pytest -q <files>`.

| ID | Clause | Mutation | RED (scope) | Failing tests (reason) |
| --- | --- | --- | --- | --- |
| M1 | Schema Upgrade keeps edits made after the request (A2→A3) | `schemaUpgradeSucceeded` keepLocal `() => false` | **1/219** V | "keeps prompt, model and overlay edits made while the Schema Upgrade was pending (A2 to A3)" — prompt reverted to the server value |
| M2 | `schemaOverlayFormsEqual` in keepLocal/dirty decisions | forced `return true` | **4/219** V | Schema Upgrade 409 overlay-only-dirty role (guidance lost); "an overlay-only edit makes the role Unsaved" (`Clean`); overlay A2→A3 on Save (`undefined`); zero-request UI test (Unsaved status) |
| M3 | Schema Upgrade honours its own request ID / monotonic IDs | success uses `state.pendingSave?.requestId ?? action.requestId` | **2/219** V | "ignores a Schema Upgrade completion whose request ID is not the pending one"; "ignores a late Schema Upgrade response… (monotonic IDs)" (state not `toBe` unchanged) |
| M5 | Zero requests from typing, toggling and navigation | picker toggle also calls `save()` | **2/219** V | "toggling the picker, typing guidance and navigating send zero requests" (`expected 2 to be 1`, a request count, the right reason); plus one timeout in "rejects eight-role 409…" (5411 ms), incidental and not banked |
| M5 (PW) | same | same | **3/9** PW (`-g "output schema tab\|v2 selection\|v2 removal\|schema upgrade\|malformed-API\|canonical fields:"`) | `toBeChecked`/`not.toBeChecked`/`toBe`. Wrong reason, as the review found; the right-reason pin is the Vitest row |
| M7 | Schema Upgrade 409 merges exactly seven | `schemaUpgradeConflicted` → `failOperation` | **1/219** V | "merges every one of the seven definitions from a Schema Upgrade 409…" (`draft` not adopted) |
| M8 | Schema Upgrade 409 parsed with the null candidate | parse mode `'null'`→`'editable'` in `upgradeDraftSchemaContract` | **1/219** V | "sends exactly the lock body and parses each contract status, including the null-candidate 409" (`InvalidDraftSaveResponseError`) |
| M10 | Exact descriptor parser | `isFieldDescriptor` → `true \|\| …` | **1/219** V | "accepts each of the seven roles' own descriptor and rejects every malformed descriptor" (`{"name":1…}` accepted) |
| P1 | I1 routing | `issueTab` reverted to `schema_contract.version` | **1/219** V; **1/1** PW (`-g "schema upgrade already_current 422 links"`) | V: "links a Schema Upgrade already_current 422 to the Output Schema tab". PW: `schema upgrade already_current 422 links to Output Schema tab`, failing on the `Go to Output Schema tab` locator (not found) |
| P1F | Fixture pinned to the server literal | fixture field back to `schema_contract.version` | **1/241** PY (`test_prompt_assembler.py test_agent_definition_workbench_routes.py`) | `test_client_schema_already_current_fixture_is_the_server_issue` |
| I3a | Malformed examples block Save visibly | `overlayExamplesError` → `return null` | **4/219** V; **1/1** PW (`-g "canonical fields:"`) | validation table; inline alert; UI Save-blocked; hook save (SyntaxError proves the parse is no longer swallowed). PW fails at the alert `toHaveText` |
| I3b | Save validation owns the error | validateDraftForm loop disabled | **3/219** V | validation table; UI Save-blocked; hook "allocates no request" |
| I4c | Exact canonical-field parser | `isCanonicalFieldDescriptor` → `isPlainRecord` | **1/219** V | "accepts every role's canonical fields and rejects every malformed canonical-field descriptor" |
| I4r | Canonical fields rendered | render list `.slice(0, 0)` | **13/219** V; **1/1** PW | 7 per-role canonical tests, the region, guidance edit, saved guidance, malformed alert, two UI tests; PW `Canonical output fields` region not found |
| I4s | Server `required` derived | `"required": True` | **4/178** PY (routes + mapping) | all three canonical route tests plus the fixture join |
| I4d | Server `default` presence derived | default omitted when it is `null` | **4/178** PY | same four |
| D7 | Seven per-role descriptors | `syntheticSchemaV2DraftDefinition` back to the architect-only descriptor | **2/219** V | seven-role parser table; "parses and renders each of the seven roles' own diagnostic_notes descriptor…" |
| CJ | Canonical fixture joined to the server | one `default` in `CANONICAL_FIELD_DESCRIPTORS` changed | **1/241** PY | `test_client_canonical_field_fixture_is_the_server_display_data` |
| DJ | Descriptor fixture joined to the server | one character in the builder example | **1/241** PY | `test_client_diagnostic_notes_fixture_is_the_server_descriptor_for_all_seven_roles` |

Each zero or count above holds only within the scope named in its row.

### Gates (final tree `370f88b8e`; the report commit changes no code)

| Gate | Command | Result |
| --- | --- | --- |
| Vitest four-file | `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.test.tsx src/components/Admin/AgentDefinitionWorkbench/OutputSchemaEditor.test.tsx)` | **219 passed** (4 files); baseline 191, +28 new |
| typecheck | `(cd frontend && npm run typecheck)` | exit 0 |
| ESLint | `(cd frontend && npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts)` | exit 0, no output |
| Playwright | `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)` | **60 passed**; baseline 59, +1 new. `lsof -ti :3000` was empty before and after |
| Routes | `PYTHONPATH=<wt> /Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_definition_workbench_routes.py` | **162 passed**; baseline 157, +5 new |
| Text-read joins | `… -m pytest -q tests/unit/test_prompt_assembler.py tests/unit/test_graph_configuration_draft.py` | **189 passed** |
| Content mapping (imports the schema) | `… -m pytest -q tests/unit/test_graph_definition_content_mapping.py` | **16 passed**. At FIX_BASE: 1 failed, cause `selectable_optional_fields` missing from the wire-order list (Task 5) |
| Task 7 unit matrix (all 17 files, as listed in the plan) | `PYTHONPATH=<wt> … -m pytest -q <17 files>` | **958 passed, 0 failed**. Not measured matrix-wide at FIX_BASE; the one known base failure is the mapping test above |
| `.venv` | `test ! -e .venv` before and after | absent both times |
| ruff | `ruff check src/api/schemas/agent_definitions.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_prompt_assembler.py tests/unit/test_graph_definition_content_mapping.py` | 2 findings, **identical to FIX_BASE**: I001 and F401 (unused `SCHEMA_CONTRACT_BUNDLES`) in the routes test's pre-existing import block. None are new. `ruff format --check` was not run and is not claimed |

### Concerns

1. **Reviewed Task 5 files changed.** `src/api/schemas/agent_definitions.py` gained a response field, as the controller ruled. The `type` label vocabulary is my own design choice: `string`, `integer`, `boolean`, `array<T>`, `$ref` name, `A | B`. It is display-only and pinned by literals, but the whole-branch review should confirm it.
2. **Pre-existing base failure fixed in scope.** `test_graph_definition_content_mapping.py` wire order was red at FIX_BASE, which the Task 5 and Task 6 gates did not run. My edit is in the same assertion my field needed.
3. **Tests that pin already-correct behaviour** (M1, M3, M7, M8, M10, and the D7 seven-role test) could not be RED before implementation. Their RED is mutation-only, recorded above. The new Playwright test was likewise written after the code. Its RED is from I3a and I4r.
4. **Deferred, but now more visible.** The m2 permanent-"Unsaved" state is untouched. A local overlay form still never compares equal to `formFromDefinition(saved)`, so any canonical-guidance edit leaves the role Unsaved after a successful save. The new Playwright test only asserts Save becomes enabled again. The m3 unselected-optional guidance is also untouched.
5. The mock architect's synthetic `title` override and `speaker_notes` remain, as correction 64 item 3 records. `title` now renders in the leftover "Field override:" section, because it is not a canonical field.
