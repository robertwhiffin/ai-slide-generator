# Task 6 independent review — typed client, protected schema editor, browser proof (#264)

Reviewer range: `d560dc69e..6ffc156ca` (package `review-d560dc69e..6ffc156ca.diff`). Restore SHA was pinned to
`307060538a243bcd81d4761334d1fe86f946487e`, and every restore used it. Paths are relative to `frontend/` unless
they are marked otherwise.

## Spec Compliance

Verdict: **❌ Not compliant.** One wire/routing defect, one clause of the display requirement unmet, and most of the
plan's mandated RED list has no test that can go red. Mutations below measure the missing tests.

| Clause (task-6-brief-raw.md) | Status | Evidence |
| --- | --- | --- |
| No second state machine, counter/ref, gate, conflict model or autosave path | ✅ | `useDraftEditor.ts:186-229` reuses `operationBlocked()`, `nextRequestIdRef` and `inFlightRequestIdRef`. The reducer adds only `schemaUpgrade*` arms that route through the shared `startOperation`/`succeedWrite`/`rejectOperation`/`mergeConflict`/`failOperation`. |
| `candidate`-prefixed wire content, `invalid_draft` family, no `invalid_definition`/`path` | ✅ | `agentDefinitions.ts` adds `candidate.schema_overlay` only. The 422 goes through the existing `parseDraftValidationErrorResponse`. |
| Schema Upgrade body exactly `{lock_version}` | ✅ | `agentDefinitions.ts:765-789`. Pinned by `AgentDefinitionWorkbench.test.tsx` "schema upgrade sends a lock-only POST…" and by Playwright. |
| One aggregate Save / Assembly Upgrade / Schema Upgrade gate | ✅ | M6 turns 3 cases red, for the right reason. |
| Only editable description/examples. No editable type/default/enum/validator | ✅ | `overlayFromForm` allow-list (`draftEditorState.ts:295`). The controller's mutation was already spent. `OutputSchemaEditor.tsx:94-96` renders only text labels. |
| Picker offers only `diagnostic_notes`, only on v2 | ✅ behaviour / ⚠️ pinning | The picker renders from the server's `selectable_optional_fields`, and the server sends `()` for v1. The client's own `isV2Schema` gate is unpinned: M9 RED 0. |
| Display code-owned name/type/**required**/default/**enums** | ❌ | `OutputSchemaEditor.tsx:94-96` shows type/default/max_items for the optional descriptor only. Nothing shows "required" or "enums". Canonical fields are never listed, so no canonical-field guidance can be written unless a saved override already exists (see I3). |
| Routing of `candidate.schema_overlay.*` issues to the Output Schema tab | ✅ | `DefinitionEditor.tsx:39` |
| Routing of the Schema Upgrade `already_current` issue to the Output Schema tab | ❌ | `DefinitionEditor.tsx:39` matches `schema_contract.version`. The server emits `schema_contract` (`src/services/graph_configuration_draft.py:127-132`). P1 below shows that the real field misroutes (I1). |
| Mandated RED tests: seven descriptors, exact parsers, ordered 422, ordinary/upgrade 409 incl. null candidate, exact-seven merge, A2→A3, monotonic IDs, zero requests from typing/navigation, cross-role persistence | ❌ | M1, M2, M3, M5, M7, M8, M10 are each RED 0/191 at four-file scope. See I2. |
| Playwright: edit/save/reload, v2 selection, absent protected controls, direct malformed-API 422, Save/Upgrade gate | ⚠️ partial | There is no *reload* step: "reload" is a tab switch, not a page reload or re-GET. The "direct malformed-API 422" test mocks the 422 itself, so it proves UI rendering only (m7). The gate test never clicks (m6). |

⚠️ **Cannot verify from the diff alone:**
- Whether the published-definition path is parsed anywhere strictly. `getAgentDefinitionWorkbench` is not a strict
  parser, and the server's `PublishedDefinitionResponse` also carries `selectable_optional_fields`. No regression
  was found, but no strict published parser exists to check.
- Whether the Assembly-tab `already_current` surface for the protected-assembly upgrade shares the unprefixed-field
  convention. The server comment at `graph_configuration_draft.py:123-126` says it does. That is consistent with I1.

## Strengths

- The single request path is respected exactly: one reducer, one counter, one gate. `upgradeSchemaContract` follows
  the other three operations line for line.
- M6 shows the gate is pinned by genuine new cases, including two same-tick pairs.
- The `overlayFromForm` allow-list builds the result by construction, not by rejection. That is the stronger design,
  and its test is named for the behaviour.
- The descriptor parser shape matches the server's `_descriptor_material` byte-for-byte on keys
  (`src/services/agent_schema_registry.py:261-277`): `name/description/examples/schema{type,default,max_items,items{type,strip_whitespace,min_length,max_length}}`.
- The four-shape `isEditableModelDraft` matches the server echo. `_client_candidate_response`
  (`src/api/routes/agent_definitions.py:308-350`) always emits both `assembly_rules` and `schema_overlay`, possibly
  as `null`, and the parser accepts that.
- The new accessible names are free of substring collisions. `Schema Upgrade` is not a substring of, and does not
  contain, any existing locator name. The `Description override` duplicates (canonical group and optional row) are
  always scoped by group in the specs.
- Implementer concern 3 — the ruling. `keepLocal: () => true` on `schemaUpgradeSucceeded` is the **correct**
  A2→A3 behaviour:
  - `upgrade_content_to_v2` (`src/services/agent_schema_registry.py:608-631`) preserves the overlay verbatim and
    changes only `schema_contract`.
  - The assembly format version does not move, so `adoptAuthoritativeDefinition` takes the same-version branch
    and keeps `entry.local` without quarantine.
  - Prompt and model are untouched by the server, so an A2 edit made during the request must survive.
  - A v1-era local overlay is a form of the same overlay the server kept, and the next save re-validates it.
  - Dirty and clean state stays consistent: local is compared against `formFromDefinition(new saved)`.

  It is not a defect. However, it is **unpinned** (M1 RED 0) and its comment says the opposite (m1).

## Issues

### Critical

None.

### Important

**I1 — The Schema Upgrade `already_current` issue links to the wrong tab in production. The fixture invents the
server's field, so the Playwright proof passes only for that reason.**
- **Where:** `DefinitionEditor.tsx:39` routes `field === 'schema_contract.version'`. `tests/fixtures/mocks.ts:949`
  (`SCHEMA_ALREADY_CURRENT_REJECTION`) uses the same invented field. The server's issue is
  `DraftValidationIssue("schema_contract", "already_current", "Schema contract is already current.")`
  (`src/services/graph_configuration_draft.py:127-132`, raised at `:471`).
- **Effect:** `issueTab('schema_contract')` falls through to `'assembly'`, so a real already-current Schema Upgrade
  offers "Go to Assembly tab".
- **Measured (P1):** with the fixture changed to the server's exact field and message, the Playwright test
  "schema upgrade already_current 422 links to Output Schema tab" goes RED at `spec.ts:1733`. That is the
  `Go to Output Schema tab` link assertion, so it is the right assertion.
- **Why it matters:** this is the cross-language literal-drift class again (corrections 51 and 64). Correction 64
  relays the implementer's statement that "field and code are correct (`schema_contract.version` /
  `already_current`)". **The field is not correct.** The whole-branch item routed as "message is synthetic"
  understates it.
- **Fix:** route `field === 'schema_contract'` (or `field === 'schema_contract' || field.startsWith('schema_contract.')`)
  to `output-schema`. Change the fixture to the server's exact field and message. Ideally, join
  `SCHEMA_ALREADY_CURRENT_REJECTION` to `_SCHEMA_ALREADY_CURRENT` in the existing text-read join
  (`test_prompt_assembler.py`), the same way the other fixtures are joined.

**I2 — Most of the plan's mandated RED list has no test that can fail. The implementer's table claims a measurement
it did not make.**

Measured at four-file Vitest scope (191 tests), each RED 0:
- **M1** — `schemaUpgradeSucceeded` keepLocal set to `false`. A2→A3 on Schema Upgrade is unpinned. Also 0/8 on the
  new Playwright tests.
- **M2** — `schemaOverlayFormsEqual` forced to `true`. This one breaks three things silently:
  - overlay A2→A3 on Save,
  - Unsaved status for overlay edits,
  - 409 merge of an overlay-only-dirty unselected role, whose overlay is now treated as clean and discarded.

  The implementer's row "RED on existing keepLocal tests" is **false**: 0/191 in Vitest and 0/8 in Playwright.
- **M3** — `schemaUpgradeSucceeded` ignores its request ID. Monotonic response IDs are unpinned for the new
  operation.
- **M5** — the picker toggle fires a Save request. "Zero requests from typing/navigation" is unpinned in Vitest.
  Playwright goes 3/8 RED, but on `toBeChecked`/`not.toBeChecked`, which is a side-effect assertion and not a
  request count — the wrong reason.
- **M7** — the Schema Upgrade 409 arm replaced by `failOperation`. Exact-seven merge on Schema Upgrade conflict is
  unpinned.
- **M8** — the Schema Upgrade 409 parser mode changed from `'null'` to `'editable'`. The null-candidate 409 is
  unpinned.
- **M10** — `isFieldDescriptor` forced to `true`. The exact descriptor parser is unpinned. The four-shape
  `isEditableModelDraft` has no new accepted/rejected cases either. The existing test is still titled
  "accepts exactly the two-key and three-key candidate shapes" (`draftEditorState.test.ts:748`).

Two further gaps:
- The "seven descriptors" test (`OutputSchemaEditor.test.tsx:238`) is vacuous. It is titled "each of the seven
  roles has … a unique description", but it asserts the shape of one architect constant and never touches seven
  roles or uniqueness.
- There is no cross-role persistence test and no overlay ordered-422 test.

Only M4, the shared operation-kind check, goes red, and only through a pre-existing #265 test.

**Fix:** add reducer-level tests, following the existing `draftEditorState.test.ts:486` and `:525` patterns, for:
- Schema Upgrade A2 (prompt/model edit) surviving A3,
- overlay A2 surviving Save A3,
- stale Schema Upgrade request ID ignored,
- Schema Upgrade 409 null candidate parsed and all seven merged, with an overlay-only-dirty unselected role kept,
- parser accept/reject tables for descriptors and the four candidate shapes,
- a `fetch`-not-called assertion after toggle and guidance typing,
- a real seven-role descriptor test, or a renamed test.

**I3 — Overlay input is silently lost on Save.**

Read from the code; not mutation-measured. `overlayFromForm` (`draftEditorState.ts:300-309`) drops examples text
that is not valid JSON without telling the user. For a canonical override saved as
`{description, examples:[…]}`, typing malformed examples sends `{description}`. The server then stores the
override **without its examples**: the save succeeds and the saved examples are gone. Afterwards the `saveSucceeded`
keepLocal comparison fails (round-trip ≠ local), so the form stays "Unsaved" and nothing explains why.

**Fix:** treat unparseable or non-array examples as a client validation error in `validateDraftForm`, blocking Save
with an inline message. Alternatively, send the raw value so the server returns an ordered 422. Never drop it.

**I4 — The display clause is only partly met.**

The plan requires the tab to show "code-owned name/type/required/default/enums". `OutputSchemaEditor.tsx:94-96`
renders type/default/max_items for the optional descriptor only. "Required" and "enums" appear nowhere
(`grep -n "required\|enum" OutputSchemaEditor.tsx` returns 0 lines). Canonical fields are not listed, because the
server exposes no canonical descriptors. An admin can therefore edit canonical guidance only for fields that already
have a saved override, and can never add new canonical-field guidance, which the global constraints allow.

**Fix:** either expose canonical-field display data from the server (a Task 5 contract gap) and render it, or
record an explicit scope correction. This must not pass silently as done.

### Minor

- **m1** `draftEditorState.ts:922-927`: the comment says "reset schema overlay to null", but the code keeps local
  (`() => true`). The code is correct (see Strengths). A reader who "fixes" the code to match the comment would
  introduce A2 loss, and M1 shows no test would catch it. Correct the comment.
- **m2** `draftStatus`: `formFromDefinition` always sets `schema_overlay: null`. Toggling `diagnostic_notes` on and
  then off therefore leaves a non-null overlay equal to the saved one, and the role reads "Unsaved" permanently
  until a save. Normalise equal-to-saved overlays back to `null`, or compare against
  `schemaOverlayFormFromDefinition(saved)`.
- **m3** `OutputSchemaEditor.tsx:56-133`: description/examples inputs are editable on an *unselected* optional
  field. That produces `field_overrides.diagnostic_notes` without the name in `additional_optional_fields`, which
  the server will reject. Disable guidance until the field is selected.
- **m4** `agentDefinitions.ts:750-763`: `upgradeDraftSchemaContract` was inserted between
  `readDraftLegacyPromptSource`'s JSDoc and that function. The legacy-source contract note now sits above the wrong
  function.
- **m5** `agentDefinitions.ts:408` `isEditableSchemaOverlay` has the same body as `isSchemaOverlay` (`:400`), and
  `EditableSchemaOverlay` duplicates `SchemaOverlay`. That is two sources for one shape. Reuse one.
- **m6** `spec.ts:1736-1763`: the gate test asserts only `toBeDisabled`. `expect(schemaUpgrades).toHaveLength(0)` at
  `:1759` is vacuous because nothing is clicked. The held save is released with body `{}`, which is invalid.
- **m7** `spec.ts:1765-1800`: the "direct malformed-API 422" test sends a valid candidate and mocks the 422 at the
  route. It proves rendering and routing, not server stability. Its comment claims it is "the guard the brief
  requires for the controller's sabotage", which is wrong: that guard is the Vitest allow-list test. The server-side
  stable 422 is pinned by Task 5's route tests. Rename it and correct the comment.
- **m8** `OutputSchemaEditor.tsx:172`: the client's `isV2Schema &&` picker gate is unpinned (M9 RED 0). The v1
  test passes because the v1 fixture list is empty, not because of the gate.
- **m9** `task-6-report.md`: the controller-target test name `'RED: removing the type-filter causes type to reach the wire'`
  does not exist. The A2→A3 row is unmeasured, and M2 shows it is false. Several other rows (the `== null`
  inversions, "Remove `case 'schemaUpgradeSucceeded'`") give no command or count. Treat the table as unmeasured
  except where this review or correction 64 re-measured it.

Confirmed, and not re-raised, from the routed list:
- The `speaker_notes` architect fixture is still present (`mocks.ts:1123`).
- `schemaUpgradeFailed` has no unit test.
- The message string is synthetic. I1 supersedes this: the field is wrong too.

## Sabotage evidence

Harness:
- Driver `/tmp/t6-review/mut.py` applies each patch only if the anchor count is exactly 1.
- Runner `/tmp/t6-review/run.sh` (Vitest) and `/tmp/t6-review/pw.sh` (Playwright) apply the patch, `rg` for
  `T6REV-<id>`, run, then restore with
  `git checkout 307060538a243bcd81d4761334d1fe86f946487e -- <five files>`. After each restore they `rg` for
  `T6REV` (none) and run the triple check.

Mutable set: `draftEditorState.ts`, `useDraftEditor.ts`, `OutputSchemaEditor.tsx`, `api/agentDefinitions.ts`,
`tests/fixtures/mocks.ts`. Byte backups were taken after a clean triple check, and all five files were `cmp`-identical
to them at the end.

Commands:
- **Vitest scope (four-file):**
  `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.test.tsx src/components/Admin/AgentDefinitionWorkbench/OutputSchemaEditor.test.tsx)`.
  Baseline GREEN **191/191**.
- **Playwright scope ("PW-8"):**
  `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1 -g "output schema tab|v2 selection|v2 removal|schema upgrade|malformed-API")`
  selects the 8 new Output Schema tests. Baseline GREEN **8/8**. Port 3000 was empty before and after every run.

| ID | Target (executed line) | Anchor | Marker `rg` | RED (scope) | Failing tests | Restore → GREEN |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | `draftEditorState.ts:927` `schemaUpgradeSucceeded` keepLocal `() => true` → `() => false` (A2→A3) | 1 | `:927` hit | **0/191** Vitest; **0/8** PW-8 | none | restored; `cmp` identical; triple empty |
| M2 | `draftEditorState.ts:339` `schemaOverlayFormsEqual` forced `true` (weakened A2→A3 / keepLocal equality) | 1 | `:339` hit | **0/191** Vitest; **0/8** PW-8 | none. The implementer's "RED on existing keepLocal tests" is falsified | restored; identical |
| M3 | `draftEditorState.ts:927` Schema Upgrade success uses the pending request ID instead of `action.requestId` (cross-op ordering / monotonic IDs) | 1 | `:927` hit | **0/191** Vitest | none | restored; identical |
| M4 | `draftEditorState.ts:588` `matchingPending` operation-kind check removed (shared cross-op ordering) | 1 | `:588` hit | **1/191** Vitest | `draftEditorState.test.ts > discriminated draft operations > only the matching operation identity may complete a pending operation` (pre-existing #265 test; no Task 6 test) | restored; identical |
| M5 | `useDraftEditor.ts:236` picker toggle also fires `save()` (zero requests from typing) | 1 | `:236` hit | **0/191** Vitest; **3/8** PW-8, wrong reason | PW: `v2 selection…`, `v2 removal…`, `direct malformed-API 422…`, all failing on `toBeChecked`/`not.toBeChecked`, not on a request count | restored; identical |
| M6 | `useDraftEditor.ts:187` `if (operationBlocked()) return;` removed from `upgradeSchemaContract` (gate) | 1 | `:187` hit | **3/191** Vitest, right reason | `useDraftEditor shared request gate >` `save architect then schema upgrade architect…`, `save architect then schema upgrade inside one tick…`, `upgrade architect then schema upgrade architect…` | restored; identical |
| M7 | `draftEditorState.ts:943` `schemaUpgradeConflicted` → `failOperation` (exact-seven merge) | 1 | `:943` hit | **0/191** Vitest | none | restored; identical |
| M8 | `agentDefinitions.ts:781` Schema Upgrade 409 parse mode `'null'` → `'editable'` (null-candidate 409) | 1 | `:781` hit | **0/191** Vitest | none | restored; identical |
| M9 | `OutputSchemaEditor.tsx:172` `isV2Schema &&` removed from the picker gate | 1 | `:172` hit | **0/191** Vitest | none | restored; identical |
| M10 | `agentDefinitions.ts:436` `isFieldDescriptor` forced `true` (exact parser) | 1 | `:436` hit | **0/191** Vitest | none | restored; identical |
| P1 (fixture probe, not a production seam) | `mocks.ts:949` `SCHEMA_ALREADY_CURRENT_REJECTION.field` → the server's real `schema_contract` and message | 1 | `:949` hit | **1/1** PW (`-g "schema upgrade already_current 422 links"`; baseline 1/1 GREEN) | `schema upgrade already_current 422 links to Output Schema tab`, failing at `spec.ts:1733`, the `Go to Output Schema tab` link | restored; identical |

Final state:
- `git rev-parse HEAD` = `307060538a243bcd81d4761334d1fe86f946487e`.
- `git status --porcelain`, `git diff HEAD` and `git diff --cached` are all empty.
- `rg T6REV frontend/src frontend/tests` returns nothing.
- `lsof -ti :3000` is empty.
- Driver scripts and logs are only under `/tmp/t6-review/`.

## Assessment

**Task quality: Needs fixes.**

The architecture respects the single-path discipline, and the gate and allow-list are genuinely pinned. However, the
Schema Upgrade `already_current` issue misroutes against the real server field (I1), and malformed examples silently
destroy saved guidance (I3). Seven of the ten measured mutations on the plan's mandated clauses go RED 0, including
the A2→A3 row the implementer reported as measured (I2), and the display clause is only partly met (I4).
