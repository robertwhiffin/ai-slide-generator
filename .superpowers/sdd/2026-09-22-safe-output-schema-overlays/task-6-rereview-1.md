# Task 6 re-review, fix round 1 (#264)

Range: `ee0a72feb..b28dba188` (fix commit `370f88b8e`, docs commit `b28dba188`). Every restore was pinned to
`b28dba1883d04e5dedb97a5d60499ce50da32ea6`. Paths are relative to the worktree root.

Scopes used for every figure below:
- **V** (four-file Vitest): `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.test.tsx src/components/Admin/AgentDefinitionWorkbench/OutputSchemaEditor.test.tsx)`. Baseline at HEAD **219/219 GREEN**.
- **PW-P1**: `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1 -g "schema upgrade already_current 422 links")`. Baseline **1/1 GREEN**.
- **PW-full**: the same file with no `-g`. **60/60 GREEN** at HEAD.
- **PY**: `PYTHONPATH=<wt> /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_graph_definition_content_mapping.py`. Baseline **178/178 GREEN**.
- **PY4**: PY plus `tests/unit/test_graph_definition_manifest.py tests/unit/test_prompt_assembler.py`. **358 passed** at HEAD.
- Static gates at HEAD: `npm run typecheck` exit 0; the plan's exact ESLint command exit 0, no output.

## Finding Verdicts

### I1: ADDRESSED
- `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx:44-48`: `issueTab` now routes
  `field === 'schema_contract' || field.startsWith('schema_contract.')` to `output-schema`.
- The server literal is unchanged. The fix diff touches no `src/services` file, and `_SCHEMA_ALREADY_CURRENT` is still
  `("schema_contract", "already_current", "Schema contract is already current.")`, as correction 18 requires.
- The fixture at `frontend/tests/fixtures/mocks.ts` (`SCHEMA_ALREADY_CURRENT_REJECTION`) now carries the server's exact
  triple.
- New join `tests/unit/test_prompt_assembler.py:1108`:
  - It uses the existing `_client_rejection`, which hard-asserts a non-empty field, code and message
    (`:1020-1024`), so it cannot pass vacuously.
  - It compares against the live `_SCHEMA_ALREADY_CURRENT` and against a hand-typed triple.
- **Measured (P1):** `issueTab` reverted to `field === 'schema_contract.version'`.
  - **RED 1/219 (V):** `AgentDefinitionWorkbench Output Schema tab > links a Schema Upgrade already_current 422 to
    the Output Schema tab` fails with `Unable to find ... button "Go to Output Schema tab"`. That is the guard.
  - **RED 1/1 (PW-P1):** it fails at `spec.ts:1733`, the `Go to Output Schema tab` `toBeVisible`. That is the guard.
  - Restored, then GREEN.

### I2: ADDRESSED
Tests now exist for every clause the review listed, and the ones I re-measured go RED on the guarding assertion:
- **M1** (Schema Upgrade keepLocal `() => true` → `() => false`): **RED 1/219 (V)**.
  - Failing test: `Schema Upgrade completion > keeps prompt, model and overlay edits made while the Schema Upgrade was
    pending (A2 to A3)`.
  - It fails on `expected 'Synthetic Architect prompt…' to be 'Architect A3'`. That is the A3 prompt assertion, the
    guard.
- **M3** (success uses `state.pendingSave?.requestId ?? action.requestId`): **RED 2/219 (V)**.
  - Failing tests: `ignores a Schema Upgrade completion whose request ID is not the pending one` and
    `ignores a late Schema Upgrade response after a newer request has started (monotonic IDs)`.
  - Both fail on `expect(next).toBe(state)`, the unchanged-state identity. That is the guard.
- **M7** (`schemaUpgradeConflicted` → `failOperation`): **RED 1/219 (V)**.
  - Failing test: `merges every one of the seven definitions from a Schema Upgrade 409 and keeps an overlay-only-dirty
    role`.
  - It fails on `state.draft` toEqual `body.server.draft`, the merge assertion.
- **M2, M5, M8, M10** were not re-run by me. The implementer reports 4, 2, 1 and 1 of 219. I read each test:
  - M5's test (`AgentDefinitionWorkbench.test.tsx`, "toggling the picker, typing guidance and navigating send zero
    requests") asserts `fetchMock.mock.calls.length` after every step, a request count as the review asked. It is not a
    checkbox side effect.
  - M8's test explicitly asserts that a candidate-echo 409 is rejected as `InvalidDraftSaveResponseError`.
  - M10's table has 14 malformed descriptors.
  - Parser accept/reject tables were added for descriptors, canonical fields and the four candidate shapes.
- **"Seven descriptors"**: the vacuous test is replaced (`OutputSchemaEditor.test.tsx`). The new test parses all seven
  roles' Schema Upgrade bodies, renders each role's own descriptor and asserts 7 distinct texts. The fixture is joined
  to the live server for all seven roles by `test_client_diagnostic_notes_fixture_is_the_server_descriptor_for_all_seven_roles`.
- **m1**: the comment at `draftEditorState.ts:954-960` now describes keep-local and names the pinning test. The code,
  `() => true` at `:961`, is unchanged, as ruled.

### I3: ADDRESSED
- `draftEditorState.ts:50-57` adds `overlayExamplesError`: blank is allowed, and anything else must be a JSON array.
- `validateDraftForm` (`:556-559`) adds one keyed error per override, so Save is refused.
- `overlayFromForm` (`:326-345`) no longer swallows the parse failure. Its only caller is `validateDraftForm:579`, after
  the error check, so the new throw is unreachable in practice.
  - I checked the other callers: `candidateFromForm` and the render-time `saveDisabled={... !validateDraftForm(entry.local).ok}`
    (`AgentDefinitionWorkbench.tsx:112`) both go through `validateDraftForm`, so nothing throws during render.
- The inline alert is rendered on all three row kinds (`OutputSchemaEditor.tsx`).
- **Own mutation (I3x):** `overlayExamplesError` accepts any parseable JSON, with the `Array.isArray` check dropped.
  - **RED 1/219 (V)**: `schema overlay local edits > refuses to build a candidate from malformed examples instead of
    silently dropping them`, failing with `"not an array": expected true to be false`. That is the guard.
  - The implementer's I3a and I3b cover the parse and loop legs.

### I4: ADDRESSED
**Server** (`src/api/schemas/agent_definitions.py:138-178, 201-207, 233-244`):
- `canonical_fields` is response-only, derived in a `mode="before"` validator from
  `SCHEMA_CONTRACT_BUNDLES[(agent_key, version)].canonical_model`. That is the same pattern as
  `selectable_optional_fields`.
- It is not on any request DTO. It was added to the `server_owned` guard set at
  `test_agent_definition_workbench_routes.py:1397`.

**Client cannot send it.** A live probe (`/tmp/t6-rereview/test_probe_canonical_request.py`, SQLite in-memory, route
helpers imported) got `422` with `{"code":"invalid_draft","errors":[{field, "extra_forbidden", "Extra inputs are not
permitted"}]}`, and a workbench unchanged afterwards, in all four positions:
- `candidate.canonical_fields`
- top-level `canonical_fields` on the Save PUT
- `candidate.schema_overlay.canonical_fields`
- `canonical_fields` on the Schema Upgrade POST

**Not persisted or hashed:**
- The fix diff touches no `src/services`, `src/domain` or manifest file.
- PY4 is 358 passed, including `test_graph_definition_manifest.py`, whose `PACKAGED_V1_CONTENT_HASHES` and
  `V1_SCHEMA_CONTRACT_DIGESTS` literals (`:744-760`) equal PLAN-CORRECTIONS.md's first table character for character.
- The route test `test_canonical_fields_survive_schema_upgrade_and_change_no_stored_identity` shows that every published
  node, and every non-upgraded draft node, is byte-equal before and after.

**Route tests:**
- Hand-typed literals for all seven roles, on draft and published.
- The list survives a Schema Upgrade.
- It is present in the 409 snapshot.
- A strict-JSON text join to `CANONICAL_FIELD_DESCRIPTORS`.

**Type-label wording** was checked against the live `model_fields` of the six canonical models (`skill_io.py`,
`finding.py`). Every label is correct:
- `Literal[...]` → `string` plus enum.
- `str` → `string`, `int` → `integer`, `bool` → `boolean`.
- `List[int]` → `array<integer>`.
- `Optional[List[str]]` → `array<string> | null`.
- `Optional[DeckSpec]` → `DeckSpec | null`.
- `List[Finding]` → `array<Finding>`.
- `required` equals `is_required()`, and every default matches (`None`, `[]`, `""`).
- Two latent limits are recorded under Out-of-Scope Observations. Neither applies to any current field.

**Rendering** (`OutputSchemaEditor.tsx:71-145, 279-309`):
- A region "Canonical output fields" holds one group per field, "Canonical field: <name>".
- Each has a nested group "Protected properties of <name>": a `dl` of name, type, required, default and enum, as text
  only.
- The only editable controls are two textareas, "Description guidance for <name>" and "Examples guidance for <name>
  (JSON array)".
- There is no client write path: `overlayFromForm` still builds only `field_overrides` and
  `additional_optional_fields`.

**Own mutations:**
- **S1**, `"enum"` forced to `None`: **RED 4/178 (PY)**. All three canonical route tests, plus the fixture join.
- **S2**, `canonical_fields: list[object]` added to `EditableSchemaOverlayRequest` (a leak into a request DTO):
  **RED 3/178 (PY)**.
  - `test_no_request_model_accepts_a_protected_stage_view_or_display_field` fails at
    `assert set(model.model_fields) & server_owned == set()` with `{'canonical_fields'}`. That is the guard.
  - The two overlay-echo 409 tests also fail, incidentally: the new default field now appears in the echo.

**Accessible names:**
- I grepped every `name:` literal in the spec and every `aria-label` in the workbench.
- "Canonical field:", "Protected properties of", "Description guidance for" and "Examples guidance for" are neither
  substrings of, nor superstrings of, "Description override", "Examples override (JSON array)", "Select
  diagnostic_notes", "Protected stage:", "Protected assembly identity", "Change provenance" or "Who changed this deck".
- Within the fixer role, "changed" is not a substring of "change_summary" (`changed` versus `change_`).
- PW-full is 60/60 GREEN, so there is no strict-mode ambiguity.

### Implementer concern 2 (wire order)
`tests/unit/test_graph_definition_content_mapping.py:224-247` is **strengthened, not weakened**:
- It still asserts the exact ordered key list of both bodies. It now includes `protected_stage_view`,
  `selectable_optional_fields` and `canonical_fields`, in class declaration order.
- The "not a content column / not a model field" check now loops over all three instead of only one.
- GREEN at HEAD (inside PY).

### New text-read joins: not vacuous
- `_client_json_fixture` (`routes test`) `json.loads` the literal body and then asserts `list(fixture) == <seven
  roles from the route>`. An empty or truncated block fails loudly.
- `_client_rejection` asserts a non-empty triple.

## New Breakage in the fix diff

Critical: none. Important: none.

Minor:
- **n1** — the new canonical UI makes the deferred m2 permanent-"Unsaved" state much easier to reach.
  - After a successful Save of canonical guidance, `local.schema_overlay` stays non-null, while
    `formFromDefinition(saved)` sets it to `null`. The role therefore stays "Unsaved" (implementer concern 4).
  - The new Playwright test (`spec.ts` "canonical fields: …") asserts only that Save is enabled after the save, so it
    does not surface this.
  - Not a regression of this diff: m2's cause is untouched. Route it with m2 to the whole-branch review; it is more
    visible now that every role has editable guidance.
- **n2** — `overlayFromForm` (exported) now throws on unparseable examples. Only `validateDraftForm` calls it, after
  the guard, so this is correct today. A future direct caller would get a throw instead of a drop, which is the safer
  failure, and the JSDoc says so. Informational.
- I found no second reducer, request counter, pending gate or state machine.
  - The only reducer change is the `fieldErrors` key widening plus one clearing line in the existing examples-changed
    arm.
  - `CUSTOM_ANCHORS` and `_LEGACY_SOURCE_ROLES` are untouched by the diff.
  - No behaviour changed outside I1-I4, except the fixture swap of per-role descriptors (D7), which is test data.

## Out-of-Scope Observations
- `_canonical_field_material` (`agent_definitions.py:155-178`) has two latent limits. Neither affects any current
  canonical field:
  - It reads `enum` only at the top level of the JSON-schema node, so an `Optional[Literal[...]]` field would display
    `enum: null`.
  - It reads `default` from the JSON schema, so a field with a `default_factory` (which has no JSON-schema default)
    would display `default: null`.
  - Worth a note for the whole-branch review, because the label vocabulary is the implementer's own (their concern 1).
- `ruff` I001/F401 in the routes test import block are pre-existing, per the implementer. I did not re-measure them.

## Sabotage evidence

Harness:
- Driver `/tmp/t6-rereview/mut.py` exits unless the anchor count is exactly 1.
- Runner `/tmp/t6-rereview/run.sh`:
  1. Refuses to start unless the triple check is empty.
  2. Applies the patch and greps the marker `T6RR-<id>` (it aborts if the marker is absent).
  3. Runs the scope.
  4. Restores with `git checkout b28dba1883d04e5dedb97a5d60499ce50da32ea6 -- draftEditorState.ts DefinitionEditor.tsx src/api/schemas/agent_definitions.py`.
  5. Greps `T6RR` (none) and prints the triple check.
- Mutable set: `frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`, `.../DefinitionEditor.tsx`
  and `src/api/schemas/agent_definitions.py`.
- Markers were placed inside inline comments or string literals, or, for Python, on their own line. None produced a
  parse or collection error.

| ID | Target | Anchor | Marker hit | Scope | RED | Failing tests (assertion) | Restore / triple |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M1 | `draftEditorState.ts:961` keepLocal → `() => false` | 1 | `:961` | V | **1/219** | Schema Upgrade A2→A3 (`local.prompt_text` 'Architect A3') | none / empty |
| M3 | `:961` requestId → `state.pendingSave?.requestId ?? action.requestId` | 1 | `:961` | V | **2/219** | stale-ID ignored; monotonic late response (`toBe(state)`) | none / empty |
| M7 | `:977` `mergeConflict` → `failOperation` | 1 | `:977` | V | **1/219** | seven-definition merge (`state.draft` toEqual server draft) | none / empty |
| P1 | `DefinitionEditor.tsx:46` → `schema_contract.version` | 1 | `:46` | V | **1/219** | already_current links to Output Schema (button not found) | none / empty |
| P1 | same | 1 | `:46` | PW-P1 | **1/1** | `spec.ts:1733` `Go to Output Schema tab` toBeVisible. Port 3000 empty before and after | none / empty |
| I3x | `draftEditorState.ts:53` drop `Array.isArray` | 1 | `:53` | V | **1/219** | malformed-examples table (`"not an array"`) | none / empty |
| S1 | `agent_definitions.py:172` `"enum": None` | 1 | `:172` | PY | **4/178** | 3 canonical route tests plus the canonical fixture join | none / empty |
| S2 | `EditableSchemaOverlayRequest` gains `canonical_fields` | 1 | `:370` | PY | **3/178** | `test_no_request_model_…` (`{'canonical_fields'}` ∩ server_owned), plus 2 overlay-echo 409 tests (incidental) | none / empty |

After the restores:
- V was 219/219 again.
- PY4 was 358 passed.
- PW-full was 60/60, with port 3000 empty before and after.
- typecheck and ESLint exit 0.

Final state:
- HEAD `b28dba1883d04e5dedb97a5d60499ce50da32ea6`.
- `git status --porcelain`, `git diff HEAD` and `git diff --cached` are all empty. This report is under the ignored
  `.superpowers/`.
- `grep -rn T6RR frontend src tests` returns nothing.
- `.venv` is absent.
- `lsof -ti :3000` is empty.
- Drivers are only under `/tmp/t6-rereview/`.

## Verdict: all findings addressed
