# Task 7 report: typed client and the Release History tab

**Status:** DONE_WITH_CONCERNS (minor; see the end).
**TASK_BASE:** `4ed72a984`. The controller's ledger-only commit `3f03752bd` sits on top and is untouched. **Mutation pin:** `7a2d094ee`.

## Commits
| SHA | Summary |
|---|---|
| `f13b1d82a` | feat: release history, inspection and rollback in the admin UI (#270) |
| `7a2d094ee` | test: pin the rollback m4 guard at the hook, where a stale render is reachable (#270) |
| (this report) | docs: record #270 Task 7 |

`git diff 4ed72a984 HEAD -- src` is empty: no Python production change.

### Files
- **Created:**
  - `frontend/src/components/Admin/GraphRelease/ReleaseHistoryTab.tsx`
  - `ReleaseHistoryTab.test.tsx` (21 tests)
  - `FieldDiffView.tsx`: #269's diff view, extracted and shared. It is behaviour-identical, and #269's tests are green.
  - `releaseText.ts`: `jsonText` and `formatInstant`. They are split out so ESLint's `react-refresh/only-export-components` passes.
- **Modified:**
  - `frontend/src/api/agentDefinitions.ts`: appended the #270 section with its types, key lists, literals, `parseInstant`, the strict parsers, and the five clients. No existing parser changed.
  - `reviewAndPublishState.ts`: gains the history, inspection and rollback slices of #269's **one** reducer, plus `canConfirmRollback`, `rollbackFailureAction` and the labels.
  - `useReviewAndPublish.ts`: the one counter and the one write ref, with the rollback flows added.
  - `ReviewAndPublishPage.tsx`: the third tab. The tab row now sits outside `preview !== null`, and the tab list is a map over three tabs.
  - `index.ts`: exports.
  - `releaseClient.test.ts`, `reviewAndPublishState.test.ts`: tests appended.
  - `ReviewAndPublishPage.test.tsx`: the one deliberate #269 test edit (C4). The absence assertion became exactly three tabs in order, and still asserts no rollback control before the history tab opens and zero history GETs.
  - `frontend/tests/fixtures/mocks.ts`: #270 fixtures, reusable by Task 8.
  - `tests/unit/test_graph_release_history_client_join.py`: Task 6's file, extended. Nothing was loosened.

## Design (the rules, as built)
- **One reducer, one counter, one gate (C39).**
  - `ReviewAndPublishState` gains `history`, `inspection` and `rollback` slices. There is no second `useReducer`, counter or ref.
  - `publishInFlightRef` is renamed `writeInFlightRef`, which C39 allows. `publish`, `reloadPreview`, `openRollback`, `reloadRollback` and `confirmRollback` all check it.
  - The reducer refuses `publishStarted` and `reloadPreview` while `rollback.status === 'rollingBack'`. `canPublish` gains that term.
  - It refuses `rollbackOpened`, `rollbackReloaded` and `rollbackStarted` while `status === 'publishing'`. `canConfirmRollback` has `state.status !== 'publishing'`.
  - `ReleaseHistoryTab` is props-only.
- **m4 not copied.** `useReviewAndPublish` keeps a `stateRef` that mirrors the reducer synchronously. Every action goes through a `dispatch` wrapper that applies `reviewAndPublishReducer` to the ref, then calls React's dispatch.
  - `confirmRollback` sends its POST only if `stateRef.current.rollback.postRequestId === requestId` after it dispatches `rollbackStarted`. That is, the reducer itself accepted the start.
  - `openRollback` and `reloadRollback` use the same check for their GET.
  - `publish()` keeps #269's parked m4, which is out of scope.
- **Stale drops.** Every read and write carries a request id from `nextRequestIdRef`, and each slice drops a non-current id:
  - history (`history.requestId`)
  - inspection (`inspection.requestId`)
  - rollback preview (`rollback.previewRequestId`, which must also be `previewLoading`)
  - rollback outcome (`rollback.postRequestId`, which must also be `rollingBack`)
- **Phases.**
  - History: `idle | loading | ready | error`.
  - Inspection: `none | loading | shown`. A failed read returns to `none` with `errorMessage`.
  - Rollback: `closed | previewLoading | confirming | rollingBack | stale | blocked | invalid | restored | error`.
- **The confirm guard** (`canConfirmRollback`):
  - `confirming`
  - not `publishing`
  - `preview.restorable`
  - `note.trim() !== ''`
  - `releaseNoteLength(note) <= 2000`
- **Note.**
  - It starts as `default_release_note`. `noteEdited` keeps an edited note through a stale reload; an unedited note takes the reloaded default.
  - Editing an `invalid` note returns the rollback to `confirming`.
  - `restored` clears the note.
- **After `restored`:** the hook calls `Promise.all([loadHistory(), reloadPreview()])` exactly once each.
  - Addition: a successful **publish** also refetches the history once, but only if it has already been loaded (`history.status !== 'idle'`). Otherwise a loaded list would show a stale active row.
- **Blocked.** `rollback-blocked-panel` covers:
  - a preview whose `blocked !== null`
  - POST 422 `rollback_incompatible`
  - 409 `rollback_source_active` and 409 `rollback_matches_active`

  Each shows the reason (keyed on the code), its issues, and `The active release is unchanged.`
- **Stale.** `rollback-stale-alert` names the current lock version, the expected lock version and the active Graph Version.
  - Its `Reload preview` button is the page's existing reload name. It re-reads only the rollback preview: exactly one GET, no automatic retry, and the note is kept.
- **Warnings (C2).** A non-blocking `rollback-warnings` panel. Confirm stays enabled.
- **Codes, not messages.** `rollbackFailureAction` switches on `failure.code`.
  - `rollbackErrorMessage` shows fixed copy for `release_note` (`blank`, `too_long`), for `lock_version`, and for anything structural.
  - Only a `definitions.<role>.*` issue shows its (service-owned) message.
  - A Pydantic `$` / `strict_type` message is never shown.
- **Instants, not strings.** `parseInstant` reads a zoneless ISO value as UTC and a zoned one with its zone, truncating the fraction to milliseconds.
  - The history parsers require every timestamp to be an instant.
  - `formatInstant` renders `YYYY-MM-DD HH:MM:SS UTC`, so a SQLite `…Z` and a naive `/workbench` spelling of one instant render the same.
  - Nothing compares timestamp strings.
- **Text only.** No `innerHTML` or `dangerouslySetInnerHTML`. Prompt diffs go through #269's `lineDiff` via the shared `FieldDiffView`, as `lineDiff(active, historical)`.
- **ids ≠ versions.** Every client takes a `versionNumber`. `releaseVersionUrl` rejects anything that is not a positive integer with a `RangeError` before any fetch. The fixtures use id = version + 40.
- **Strict parsers.** Every new response is exact-key at every level. Beyond keys they enforce:
  - **History list:** newest first, and exactly one `is_active` row, equal to `active_release`.
  - **Entry:** `restored_by` ascending, and `changed_agents` non-empty, unique and in Graph order.
  - **Detail:** exactly seven definitions, in Graph order, whose `content` is a JSON object. History evidence pairs kind and source, and each literal is checked.
  - **Comparison:** exactly seven agents, in Graph order. `field_diffs` are in `RELEASE_DIFF_FIELDS` order and may be empty; its keys are `active` and `historical`, and #269's `published` and `candidate` are refused.
  - **Preview:** `restorable === (blocked === null)`, `blocked` in its three values, and `draft_effect` exactly seven keys in Graph order with values in `reset|kept|unchanged`. Its evidence items have three keys.
  - **Success:** seven mappings, all `reused === true`. Every evidence item is `historical_restore` with a source, via `isReleaseEvidence`. `draft_effect` is checked as in the preview.
  - **Failures:** 422 is `invalid_rollback` or `rollback_incompatible`, each with at least one error. 409 is `stale_rollback`, `rollback_source_active` or `rollback_matches_active`.
  - A malformed 200, 409 or 422 raises `InvalidReleaseResponseError`. A 403, 404 or 500 is a plain `AgentDefinitionApiError`.

## Gates (all at HEAD `7a2d094ee`)
- **Vitest, full:** 21 files, **1084 passed**, 0 failed.
  - GraphRelease: 348, previously 152.
  - `src/components/Admin/AgentDefinitionWorkbench`: 628 passed and unchanged, including `ALLOWED_ACTION_NAMES` `toHaveLength(8)` at `AgentDefinitionWorkbench.test.tsx:378`.
  - `forbiddenActionNames.ts` and the workbench are unchanged (`git diff 4ed72a984 HEAD` is empty for both).
- **Typecheck:** `npm run typecheck` (`tsc -b`) is clean.
- **ESLint:** clean on `src/api/agentDefinitions.ts`, `src/components/Admin/GraphRelease` and `tests/fixtures/mocks.ts`.
- **Join tests:** every `tests/unit/test_*client_join*.py` (6 files) passes, **112 in all**. The #270 join has 67, previously 20.
- **Full unit suite** (run from the real worktree, not `/tmp`): **6 failed / 7148 passed / 110 skipped**. The 6 are the baseline nodes with the baseline causes:
  - deploy_autoscaling ×2: `'provisioned' == 'autoscaling'`
  - chokepoint ×3: `_FakeSession.execute`
  - persistence_boundary ×1: `ConversationGraphReleaseIntegrityError: no active Graph Release`

  The failures match by cause, not just by count. I did not reconcile the pass count against Task 6's 7122 (+26 here, while the join file alone added 47). Task 6's run was from `/tmp`, with one extra environment failure, so its pass count is not a clean baseline.
- **RED evidence:** I ran the tests at `f13b1d82a` against base production code. I checked out `4ed72a984`'s `agentDefinitions.ts`, state, hook, page and `index.ts`, and removed the three new production files.
  - GraphRelease Vitest: 172 failed and 155 passed. The passes are #269's and Task 6's existing tests.
  - The #270 join: 24 failed and 21 passed. The passes are Task 6's own.
  - Restored with `git checkout f13b1d82a -- frontend tests`. `git diff --quiet f13b1d82a` was clean.
- **No `npm install`, no Playwright, no `pip`.** `package.json` and the lockfile are untouched.

## Mutation sweep
- **Method:** `/tmp/t270-7/mutate.py`. Every row uses anchor count 1 (asserted), and a `MUT270_7` marker where the syntax allows.
- **Suites run on each mutation:** the GraphRelease Vitest (348), plus the #270 and #269 join files (67 + 26).
- **Restore:** each mutation was restored with `git checkout 7a2d094ee -- <file>`. After each, `git diff --quiet 7a2d094ee -- frontend tests src` was clean and the marker count was 0 (37/37).

| # | Mutation | Result (first RED) |
|---|---|---|
| M01 | preview parser skips exact keys | RED 2: `parseRollbackPreviewResponse rejects an extra top-level key` |
| M02 | TS `RELEASE_HISTORY_ENTRY_KEYS` drops `restored_by` | RED 23 Vitest + join `test_each_client_key_list_is_exactly_the_server_model[ReleaseHistoryEntryResponse]` |
| M03 | success parser skips exact keys | RED 2: `parseRollbackSuccessResponse rejects a 200 with an extra top-level key` |
| M04 | history stale drop removed | RED `drops an out-of-order history answer by the one request counter` |
| M05 | inspection stale drop removed | RED `inspection goes none -> loading -> shown for the current request only` |
| M06 | rollback-preview stale drop removed | RED `drops an out-of-order rollback preview by the one request counter` |
| M07 | rollback-outcome stale drop removed | RED `rollback outcomes drops an outcome from another request id` |
| **M08 (plan REVIEWER sabotage)** | rollback gets its own in-flight flag instead of the page gate (reducer `canPublish` term + hook `rollbackInFlightRef`) | RED 2 **as predicted**: reducer `the one write gate … publish is refused while rollingBack`, plus component `refuses a publish while a rollback is in flight` |
| M08a | reducer only: `canPublish` ignores `rollingBack` | RED 2 (same two) |
| M08b | hook only: `confirmRollback` skips the shared ref | **survives, equivalent** (concern 1) |
| M08c | hook only: `publish` skips the shared ref | RED 2: `refuses a publish while a rollback is in flight` + #269 `sends exactly one POST per click` |
| M09 | reducer: `rollbackOpened` allowed while publishing | RED 2: `openRollback and confirm are refused while publishing` |
| M09b | hook: `openRollback` skips the shared ref | **survives, equivalent** (concern 1) |
| M10 | `canConfirmRollback` ignores `publishing` | RED 2: component `refuses to open or confirm a rollback while a publish is in flight` |
| M11 | m4: POST sent without the reducer-acceptance check | RED `sends no POST when the reducer refuses the start, though the last render allowed it (m4)` |
| M11b | m4 copied literally: check `canConfirmRollback(state)` (render state), POST regardless | RED (same) |
| M12 | confirm cap `<= 2001` | RED `caps the note at 2000 code points` |
| M13 | confirm allowed from `blocked` | RED `lists the issues of a 422 rollback_incompatible and sends nothing further` |
| M14 | draft-effect labels `reset`/`kept` swapped | RED 2 Vitest (component mappings + `labels the three draft effects (Q7)`) + join `test_the_client_draft_effect_labels_cover_exactly_the_server_vocabulary` |
| M15 | `draft_effect` values unchecked | RED 3 (preview label and value rows, and success) |
| M16 | `blocked` vocabulary unchecked | RED `rejects blocked outside its three values` |
| M17 | `restorable === (blocked === null)` unchecked | RED 3 |
| M18 | success accepts a non-reused mapping | RED `rejects a 200 with a mapping that is not reused` |
| M19 | success accepts approval evidence | RED `rejects a 200 with approval evidence` |
| M20 | history evidence: approval source unchecked | RED `rejects an approval with a source` |
| M21 | `parseInstant` reads a zoneless value as local time | RED 2, on a BST host only (concern 2) |
| M22 | stale reload resets an edited note | RED 2 (reducer + component stale test) |
| M23 | no history refetch after restore | RED `shows the success, then refetches the history and the release preview exactly once each` |
| M24 | no release-preview refetch after restore | RED (same) |
| M25 | `stale_rollback` mapped to `rollbackFailed` | RED 2 |
| M26 | tab row back inside `preview !== null` (C39) | RED `is reachable when the release preview fails (Correction 39)` |
| M27 | the active row offers a rollback control | RED `marks the active row Active, with no rollback control; every other row has exactly one (C3)` |
| M28 | release note via `dangerouslySetInnerHTML` | RED `renders history text as text, never as markup` |
| M29 | rollback addressed by `release_id` (ids ≠ versions) | RED 2 (URL `/releases/42/rollback-preview`) |
| M30 | TS `DRAFT_EFFECTS` reordered | RED join `test_each_client_literal_is_the_server_literal[draft_effect]` |
| M31 | rollback-preview GET while publishing (reducer + hook) | RED 3 |
| M32 | confirm guard drops `.trim()` | RED 4 (`disables Confirm rollback with the blank note "   "`, reducer, m4) |

**Not run:** the plan's **CONTROLLER** sabotage (drop `note.trim() !== ''` from the confirm guard, predicted RED "a blank note disables confirm"). M32 is the same line, so if the controller runs it, it should see the same four REDs.

**One finding the sweep produced, fixed in `7a2d094ee`:** the first m4 test was vacuous. M11 survived at `f13b1d82a`.
- A controlled textarea's `change` re-renders synchronously even inside `act`; I probed this, and `disabled` was already `true` before the click. So the rendered Confirm was disabled and never clicked.
- The replacement test drives `useReviewAndPublish` through `renderHook`. It calls `setRollbackNote('  ')` and `confirmRollback()` from one render's closures, then checks zero POSTs. A positive control in the same test sends exactly one POST.

## Deviations
1. **C3's fixed accessible names, not the brief's numbered ones.** The row buttons are `Inspect this version` and `Roll back to this version`, scoped by `release-history-row-<version>`. Each has `aria-describedby` pointing at the row heading `Graph Version N`. The corrections override the brief.
2. **`Confirm rollback` and `Cancel rollback` are kept verbatim, although both match the `rollback` stem.** `Release History` (the `history` stem) is kept too. **Raised for a ruling, not exempted.**
   - Per C40, `FORBIDDEN_ACTION_STEMS` is swept only over the workbench panel. #269's review page has no rendered-control sweep, and none of these controls renders in the workbench.
   - No exemption was added, and the count stays 8.
   - The actual row rollback control, `Roll back to this version`, does not match any stem (`roll back` ≠ `rollback`).
   - If the controller wants the page's confirm and cancel names to clear the stems too, one alternative is `Confirm roll back` / `Cancel roll back`, which Task 8 would then use.
   - The names are collision-safe for Task 8 (f): none is a case-insensitive substring of another.
3. **The note cap counts code points** (`releaseNoteLength`, #269 C10), not the brief's `note.length`. The server counts with Python `len`.
4. **Extra files and edits beyond the brief's file list.**
   - `FieldDiffView.tsx` and `releaseText.ts` are extracted.
   - `mocks.ts` gains the #270 fixtures, following #269's pattern (for Task 8).
   - The hook and `index.ts` change; C39's table already lists them.
5. **The history is read lazily,** on the first click of the Release History tab. A publish success refetches the history only if it has already been loaded.
6. **Blocked covers five paths:** the preview's own `blocked`, 422 `rollback_incompatible`, and both typed 409s.
7. **An inspection failure returns to `none`** with an `errorMessage`, so the brief's three inspection phases are kept.
8. **Extra testids:** `rollback-lineage`, `rollback-warnings`, `release-definition-<agentKey>`, `release-evidence-<runId>` and `release-comparison-diff-<field>`. The brief's set is all present.
9. **The history-list parser is stricter than keys.** It requires newest first and exactly one active row matching `active_release`, which mirrors the server's contract.

## For Task 8
**`data-testid`s:**
- From the brief:
  - `release-history-tab`
  - `release-history-row-<version>`
  - `release-history-detail`
  - `release-comparison`
  - `rollback-preview`
  - `rollback-note-input`
  - `rollback-confirm-button`
  - `rollback-cancel-button`
  - `rollback-blocked-panel`
  - `rollback-stale-alert`
  - `rollback-success-panel`
- Additional:
  - `rollback-lineage`
  - `rollback-warnings`
  - `release-definition-<agentKey>`
  - `release-evidence-<runId>`
  - `release-comparison-diff-<field>` (non-prompt fields; `prompt_text` is a `list` named `prompt_text`)
- #269's `release-changes-tab`, `release-diff-tab`, `release-next-version`, `release-note-input`, `release-publish-button` and `release-success-panel` are unchanged.

**Accessible names:**

| Kind | Names |
|---|---|
| Tabs | `Changes & Approvals`, `Definition Diff`, `Release History` |
| Row buttons | `Inspect this version`, `Roll back to this version` (none on the active row) |
| Rollback panel buttons | `Confirm rollback`, `Cancel rollback` |
| Stale-alert button | `Reload preview` (re-reads the rollback preview) |
| History-error button | `Reload versions` |
| Textarea | `Rollback note` |

- Row badges are text: `Active` and `Restores Graph Version M`.
- The lineage sentence is `Graph Version N will restore Graph Version S (predecessor Graph Version A).`
- The success panel reads `Graph Version N restores Graph Version S` and `The shared draft is now based on Graph Version N`.
- Draft-effect copy is `Reset to restored content`, `Pending edit kept` and `Unchanged`.

**Exported names.**
- **`agentDefinitions.ts`:**
  - Clients: `listGraphReleases`, `getGraphRelease`, `compareGraphRelease`, `getRollbackPreview`, `rollbackGraphRelease`.
  - Parsers: `parseReleaseHistoryListResponse`, `parseReleaseDetailResponse`, `parseReleaseComparisonResponse`, `parseRollbackPreviewResponse`, `parseRollbackSuccessResponse`, `parseRollbackFailure`, `parseInstant`.
  - Literals: `DRAFT_EFFECTS`, `ROLLBACK_BLOCKS`.
  - Types: `ReleaseHistoryEntry`, `ReleaseHistoryListResponse`, `ReleaseDetailResponse`, `ReleaseDefinition`, `ReleaseHistoryEvidence`, `ReleaseComparisonResponse`, `AgentComparison`, `ReleaseComparisonFieldDiff`, `RollbackPreviewResponse`, `RollbackPreviewEvidence`, `RollbackRequest`, `RollbackSuccessResponse`, `RollbackFailure` and its five members, `DraftEffect`, `RollbackBlock`, `ReleaseEvidenceKind`, `ReleaseRunVerdict`, `ReleaseRunExecutionStatus`.
- **`GraphRelease/index.ts`:**
  - #269's names, plus `DRAFT_EFFECT_LABELS`, `EVIDENCE_KIND_LABELS`, `canConfirmRollback`, `historyReadErrorMessage`, `rollbackBlockedMessage`, `rollbackErrorMessage`, `rollbackFailureAction`, `runVerdictLabel`.
  - Slice and status types: `HistorySlice`, `HistoryStatus`, `InspectionSlice`, `InspectionStatus`, `RollbackBlocked`, `RollbackSlice`, `RollbackStatus`.
  - Components and helpers: `FieldDiffView`, `formatInstant`, `jsonText`, `ReleaseHistoryTab`, `ReleaseHistoryTabProps`, `INSPECT_VERSION_NAME`, `ROLL_BACK_VERSION_NAME`.
- **`useReviewAndPublish()`** now returns `state`, `setNote`, `publish`, `reloadPreview`, `loadHistory`, `inspectRelease`, `openRollback`, `reloadRollback`, `setRollbackNote`, `cancelRollback` and `confirmRollback`.

**Fixtures in `tests/fixtures/mocks.ts`:**
- `releaseRef(v)` (id = v + 40)
- `syntheticHistoryEntry`
- `syntheticReleaseHistory` (v4 active; v3 restores v1)
- `syntheticRestoredReleaseHistory` (v5 active; restores v2)
- `syntheticReleaseDetail` (v2)
- `syntheticAgentComparisons`, `syntheticReleaseComparison`
- `syntheticDraftEffect` (architect `reset`, builder `kept`, the rest `unchanged`)
- `syntheticRollbackPreview` (v2 → v5 at lock 3), `syntheticBlockedRollbackPreview`
- `syntheticRollbackSuccess`, `syntheticRolledBackReleasePreview` (draft base v5)
- `syntheticStaleRollback` (current lock 5; v4 active)
- `syntheticRollbackIncompatible`, `syntheticRollbackInvalid`
- `HISTORY_ACTIVE_ARCHITECT_PROMPT`, `HISTORY_V2_ARCHITECT_PROMPT`

Task 8's plan scenario (v1–v8, v3 restored as v8) needs its own route mocks. These fixtures are the v1–v5 scenario.

## Concerns
1. **M08b and M09b are equivalent.** The shared-ref checks at the top of `confirmRollback` and `openRollback` are subsumed by the reducer-acceptance check through `stateRef`: a publishing or rolling-back state already makes the reducer refuse. I kept them deliberately as defence in depth.
   - The ref is load-bearing on the publish side. M08c goes RED when `publish` skips it.
   - The plan's reviewer sabotage (M08) goes RED as predicted.
2. **M21 depends on the host time zone.** The zoneless-as-UTC tests go RED because this host runs BST. On a UTC CI runner, `Date.parse` of a zoneless value is already UTC, so that mutation would be invisible there. It only matters for non-UTC browsers, which is the real target. There is no in-test time-zone control in Vitest/jsdom without a config change.
3. **The `stateRef` mirror** runs the pure reducer once more per action, and it relies on every action going through the hook's `dispatch` wrapper. React's raw dispatch is not exposed.
4. **`Confirm rollback`, `Cancel rollback` and `Release History` match the forbidden stems.** This is deviation 2, and it needs a controller ruling if the stems are ever meant to apply beyond the workbench.
5. **#269's parked m4 remains in `publish()`.** It still checks `canPublish` against render state. I did not fix it, because it is out of scope.
6. **The Publish section still renders below every tab, History included,** because it is tied to the release preview as C39 says. It is disabled while a rollback is in flight.
