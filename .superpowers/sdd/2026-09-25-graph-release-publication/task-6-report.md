# Task 6 report: typed release client and the Review & Publish page

**Status:** DONE_WITH_CONCERNS (minor; see the end).
**TASK_BASE:** `d83ad95ce`. The controller's ledger commit `585d4366c` (progress.md only) is my parent and is untouched.
**Mutation pin:** `b46dde573`.

## Commits
| SHA | Summary |
|---|---|
| `b46dde573` | feat: review and publish graph releases in the admin UI (#269) |

No Task 5 Python file was modified. The only Python change is the new join test.

## Files
- **Modified:**
  - `frontend/src/api/agentDefinitions.ts` (appended, from :1888): release types, strict parsers, `getReleasePreview`, `publishRelease`.
  - `frontend/src/App.tsx:55`: route `/admin/agent-definitions/review` inside `RequireAdmin`.
  - `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx`: the header (`<header>` block, per C54, not `:31–48`) gains `Changed agents: N` (a `<dt>/<dd>` pair; the count is the roles whose saved `candidate_hash` differs from the published hash) and a plain `<a href="/admin/agent-definitions/review">Review & Publish</a>` outside any nav button.
  - `draftEditorState.ts`: C48's TS half. `testOperationFailure` now uses the `INELIGIBLE_VERDICT_MESSAGES` table, where `linked_to_release` maps to "This run is evidence for a published Graph Version; its verdict cannot change." `draftStatus` is unchanged.
  - `frontend/tests/fixtures/forbiddenActionNames.ts`: appends exactly `'Review & Publish'` with a doc-comment (C44). The stems are unchanged.
  - `AgentDefinitionWorkbench.test.tsx` and `tests/e2e/agent-definition-workbench.spec.ts`: `toHaveLength(8)`, `toContain('Review & Publish')`, and C44's three assertions (`'Review & Publish'` false, `'Review & Publish now'` true, `'Review & publish'` true). The workbench test also adds 2 header tests: the link is a plain anchor with the right href, its text is outside the node nav, the sweep stays clean, and `Changed agents` counts 0 and then 1.
  - `verdictReadinessClient.test.ts`: the reason `it.each` gains `linked_to_release`, plus 3 copy tests for `testOperationFailure`.
  - `frontend/tests/fixtures/mocks.ts`: release fixtures appended, for Task 7's Playwright to reuse (listed below).
- **Created:**
  - `frontend/src/components/Admin/GraphRelease/`:
    - `ReviewAndPublishPage.tsx`
    - `useReviewAndPublish.ts` (see deviation 1)
    - `reviewAndPublishState.ts`
    - `lineDiff.ts`
    - `index.ts`
    - tests: `lineDiff.test.ts`, `reviewAndPublishState.test.ts`, `ReviewAndPublishPage.test.tsx`, `releaseClient.test.ts` (see deviation 2)
  - `tests/unit/test_graph_release_client_join.py` (22 tests).

## Corrections applied
- **C7/C44:** the exact whole-name exemption; both length sites are now 8; near-misses stay forbidden (M11, M12 and M34 are RED).
- **C54:** `readinessStatusLabel` is typed `as const satisfies Record<ReadinessStatus, DraftStatus>`. A runtime Vitest checks each value, and a wrong label is also a tsc error (2 errors, probed).
- **C48:** TS label as above; the reason literal was already present from Task 4.
- **C1:**
  - The strict gap parser accepts exactly `agent_key, test_case_id, code`, and only the two codes.
  - `test_case_id` must be null exactly when the code is `no_required_case`.
  - `no_required_case` renders as `<Role>: no active required test case`.
  - `no_eligible_approval` renders as `<Role>: <case name from the 409's readiness, or "test case <id>"> has no eligible approval`.
- **C10:**
  - Publish expects 200; a 201 is not success (it becomes an `AgentDefinitionApiError`).
  - The note is capped at 2000 characters. The 422 is shown beside the textarea (`aria-invalid` and `aria-describedby="release-note-error …"`).
- **C22:** `canPublish = status==='ready' && preview.publishable && note.trim()!=='' && releaseNoteLength(note) <= 2000`.
- **C32:**
  - Readiness is shown, never used. A test proves Publish is enabled when `publishable: true` sits beside a blocking readiness (M16 is RED).
  - The 409 readiness is used only for case names in the gap labels.
- **C38:** consumes `parseDraftReadinessResponse`, `DraftReadiness`, `AgentReadiness` and `ReadinessStatus`. No second readiness type.
- **Codes, not messages:**
  - `publicationErrorMessage` keys on `(field, code)`. Structural issues (`$`, `strict_type`, `extra_forbidden`, `invalid_json`) get fixed copy: "The publish request was refused."
  - A test asserts that "PublishReleaseRequest" never renders (M23 is RED).
  - Only `definitions.<role>.*` issues show their message. Those are the service's own triples.

## Behaviour (for Task 7)
- **Page layout:**
  - Title: `h1` "Review & Publish".
  - Tabs, as `role=tab` buttons: `Changes & Approvals` (`release-changes-tab`) and `Definition Diff` (`release-diff-tab`).
  - Summary: `release-next-version` "Next Graph Version: N"; "Active: Graph Version N"; "Draft base: Graph Version N"; "Lock version: N".
  - Publish button: `release-publish-button`, labelled "Publish Graph Version {next}".
- **Changes & Approvals tab:** one `region` per changed role, named by its label. Each shows `Changed fields: …`, and either one `<case name>: <label>` line per required case or "No active required test case". An unchanged draft shows "No Agent Definitions changed since Graph Version N."
- **Definition Diff tab:**
  - one `region` per role, named "`<Role>` diff";
  - `prompt_text` renders as a `list` named `prompt_text`, one `li[data-kind=same|removed|added]` per line, prefixed "  ", "- " or "+ ";
  - other fields render in `pre[data-testid=release-diff-<field>]` as "`<json>` → `<json>`".
- **Note and Publish:**
  - The note field is `release-note-input` (`readonly` while publishing), with a "N / 2000" counter.
  - Hints: "Enter a release note to publish." and "This draft cannot be published yet."
- **Outcome panels:** the stale, not-ready, nothing-to-publish and error panels each carry a `Reload preview` button.
  - `release-stale-alert` (role alert) names the current lock version, the reviewed lock version, and "Graph Version N is active".
  - `release-not-ready-panel` lists the gaps as `li` elements.
  - Nothing-to-publish is `release-nothing-panel` (a testid I added).
  - `release-success-panel` (role status) shows "Published Graph Version N" and "The shared draft is now based on Graph Version N".
- **After success:** exactly one preview refetch. The success panel stays, and the refetched preview (for example "Draft base: Graph Version 2", no changed roles) shows beneath it.
- **Stale:** no automatic retry and no automatic GET. The note is kept, and `Reload preview` issues exactly one GET and zero POSTs.

## Gates (real numbers)
- **Vitest, full:** 20 files, **878 passed**, 0 failed. New or changed tests:
  - GraphRelease: 142 (lineDiff 5, reviewAndPublishState, releaseClient, page)
  - workbench: +2
  - verdict client: +4
- **Vitest GraphRelease + AgentDefinitionWorkbench:** 10 files, 770 passed.
- **Typecheck** (`npm run typecheck`, `tsc -b`): clean.
- **ESLint:** clean on every touched file:
  - `agentDefinitions.ts`
  - the `GraphRelease/` directory
  - `AgentDefinitionWorkbench.tsx`, `draftEditorState.ts`, and the two workbench test files
  - `App.tsx`
  - `mocks.ts`, `forbiddenActionNames.ts`
  - the e2e spec
- **Playwright** `agent-definition-workbench.spec.ts`: **78 passed**, 32 s. I started the dev server on :3000 through the config's `webServer`; it stopped with the run (`lsof :3000` was empty afterwards).
- **Python joins** (all 5 `*client_join*` files): **67 passed**. The new file has 22.
- **Full unit suite:** **6 failed / 6956 passed / 110 skipped**, 02:29–02:36 UTC (did not cross midnight). The 6 are exactly the baseline nodes, and I re-checked each cause:
  - deploy_autoscaling ×2: `provisioned` == `autoscaling`, `_get_or_create_lakebase_provisioned` called 0 times
  - chokepoint ×3: `'_FakeSession' object has no attribute 'execute'`
  - persistence_boundary: `no active Graph Release`

**RED evidence:**
- The 4 new Vitest files failed on the missing modules and exports (82 failed).
- The workbench suite failed 3: the length-8 guard and the 2 header tests.
- The verdict copy test failed on `linked_to_release`.
- The Python join failed 20 of 22 before any TS existed.

## Mutation sweep
Script: `/tmp/t269-6/mut.py`. Each mutation was restored with `git checkout b46dde573 -- <file>`, and `git diff --quiet b46dde573 -- frontend tests src` returned 0 after every one. All 34 went RED; M13's first form was a no-op (a type cast), so it was redone.

| # | Mutation | First RED |
|---|---|---|
| M01 | preview parser drops exact keys | `rejects extra keys at every level` (2) |
| M02 | field-diff drops exact keys | `rejects extra keys at every level` |
| M03 | mappings: count only, no order | `requires exactly the seven mappings, in Graph order` |
| M04 | gap null/code agreement dropped | `rejects a no_required_case gap with a case id` (+ the inverse) |
| M05 | sha256 is any string | 4 hash cases |
| M06 | diff-field order unchecked | out-of-order and repeated diff fields |
| M07 | superseded preview response not dropped | `drops a preview response from a superseded request` |
| M08 | publish outcome of another request id applied | `drops a publish outcome from another request id` |
| M09 | in-flight gate ref removed | `sends exactly one POST per click…` |
| **M10 (plan REVIEWER sabotage)** | stale handler automatically re-POSTs | `keeps the note on a stale 409 and never retries until Reload preview` |
| M11 | `'Review & Publish'` exemption removed | 11 workbench tests (guard, header link, sweeps) |
| M12 | exemption made case-insensitive | guard: `'Review & publish'` spared (2) |
| M13 | `awaiting_review` → "Awaiting approval" | label test + page readiness test; also 2 tsc errors |
| M14 | blank note allowed | 6 (canPublish blank cases, page blank-note) |
| M15 | note cap counted in UTF-16 units | `caps the note at 2000 code points` |
| M16 | readiness `all_ready` gates Publish (C32) | reducer C32 test + page C32 test |
| M17 | C48 label → the checks-failed text | `labels linked_to_release with its own client message` |
| M18 | no refetch after publish | `shows the success panel and refetches the preview exactly once` |
| M19 | two refetches after publish | the same test |
| M20 | stale drops the note | reducer stale test + page stale test |
| M21 | prompt line via `dangerouslySetInnerHTML` | `renders prompt text as text, never as markup` |
| M22 | `no_required_case` label drift | gap label test + page not-ready test |
| M23 | a structural 422 echoes the Pydantic message | label test + page Pydantic test |
| M24 | publish body spreads the request (an actor is smuggled through) | `sends no extra key a caller smuggles in` |
| M25 | 201 accepted as success | `treats a 201 as an invalid response` |
| M26 | TS `FIELD_DIFF_KEYS` reordered | join `[FieldDiffResponse]` |
| M27 | `ROLE_LABELS` drift | join `test_the_client_role_labels_are_the_workbench_display_names` |
| M28 | changed-agent count always 0 | `counts a role whose saved draft differs…` |
| M29 | no shared in-flight preview GET | `shares one in-flight read…` |
| M30 | reducer `publishStarted` unguarded | `starts publishing only when canPublish holds` |
| M31 | changed-role order unchecked | `rejects changed roles out of Graph order or repeated` |
| M32 | `invalid` does not return to `ready` on edit | reducer + page 422 test |
| M33 | gap-code list accepts anything | `rejects a gap code this client does not know` |
| M34 | exemption by prefix (near-miss) | guard: `'Review & Publish now'` spared |

I did **not** run the plan's CONTROLLER sabotage (drop `preview.publishable &&` from `canPublish`). Per C22, its predicted RED is `is disabled with blocking readiness (the server's publishable=false), whatever the note` in `ReviewAndPublishPage.test.tsx` and `is false when the server says the draft is not publishable` in the reducer test. The blank-note tests should stay GREEN under it.

## Deviations
1. **`useReviewAndPublish.ts` (an extra file).** The hook lives in its own module because ESLint's `react-refresh/only-export-components` rejects a component file that also exports a hook. The page file exports only the component.
2. **`releaseClient.test.ts` (an extra test file).** It holds the parser and client tests (for the preview, 200, 409 and 422 bodies, the body shape, the status codes and in-flight sharing), keeping the reducer test file about the reducer.
3. **`getReleasePreview` shares one in-flight GET,** like `getAgentDefinitionWorkbench`, so StrictMode's dev remount does not read the prompts twice. Stale-response dropping by request id still applies per dispatch (M07).
4. **The note cap counts code points** (`[...note].length`), mirroring Python `len`, not JS `.length` as C22's text says. 2000 astral characters are accepted, as the server would accept them.
5. **Strictness beyond the Pydantic models,** in the safe direction:
   - the 422 parser requires ≥1 issue (#268's pattern; the server always emits ≥1);
   - the preview parser requires changed roles strictly in `AGENT_KEYS` order and diff fields strictly in `RELEASE_DIFF_FIELDS` order (both are server guarantees);
   - the success parser requires the seven mapping keys in order (the server's validator does the same).
6. **`invalid` → `ready` on a note edit.** Editing the note after a 422 clears the refused issues and re-enables Publish. Every other refusal still needs an explicit `Reload preview`.
7. **Two extra testids:** `release-nothing-panel`, and `release-diff-<field>` on non-prompt diffs. There is also a `Back to Admin` link (`/admin`) in the page header.
8. **C54's placement:** the header link is inside the `<header>` block of `WorkbenchContent`, as C54 corrects (not `:31–48`).

## Exported names (for #270's Release History tab)
`frontend/src/api/agentDefinitions.ts`:

| Line | Name |
|---|---|
| :1900 | `RELEASE_NOTE_MAX_LENGTH` |
| :1903 | `RELEASE_DIFF_FIELDS` |
| :1918 | `ReleaseDiffField` |
| :1921 | `ReleaseFieldDiff` |
| :1928 | `ChangedDefinitionPreview` |
| :1941 | `ReleasePreviewResponse` |
| :1952 | `PublishReleaseRequest` |
| :1957 | `PublishedMapping` |
| :1963 | `ReleaseEvidence` (`evidence_kind: 'approval'` only; #270 must widen it for `historical_restore`, see Task 5 deviation 7) |
| :1971 | `PublishReleaseSuccessResponse` |
| :1981 | `ReleaseIdentity` |
| :1987 | `StalePublicationResponse` |
| :1996 | `NothingToPublishResponse` |
| :2003 | `PublicationGapCode` |
| :2006 | `PublicationGap` |
| :2013 | `PublicationNotReadyResponse` |
| :2020 | `PublicationValidationErrorResponse` |
| :2025 | `PublishReleaseFailure` |
| :2032 | `InvalidReleaseResponseError` |
| :2150 | `parseReleasePreviewResponse` |
| :2190 | `parsePublishReleaseSuccessResponse` |
| :2219 | `parsePublishReleaseFailure` |
| :2266 | `getReleasePreview` |
| :2292 | `publishRelease` |

Two private helpers can be exported if #270 needs to parse release lists: `isActiveRelease` and `ACTIVE_RELEASE_KEYS`. The join already pins `ACTIVE_RELEASE_KEYS`.

`frontend/src/components/Admin/GraphRelease/`:
- `index.ts`: re-exports everything below.
- `ReviewAndPublishPage.tsx:162`: `ReviewAndPublishPage`.
  - The tabs are a `([id, label, testId])` tuple list inside the page with `TabId = 'changes' | 'diff'`. #270 adds `'history'` there, plus a panel branch.
  - The tablist is `aria-label="Release review"`.
- `useReviewAndPublish.ts:16`: `useReviewAndPublish()`, which returns `{ state, setNote, publish, reloadPreview }`.
- `reviewAndPublishState.ts`:

  | Line | Name |
  |---|---|
  | :28 | `ReviewStatus` |
  | :39 | `ReviewAndPublishState` |
  | :58 | `ReviewAndPublishAction` |
  | :71 | `createReviewAndPublishState` |
  | :88 | `releaseNoteLength` |
  | :96 | `canPublish` |
  | :133 | `reviewAndPublishReducer` |
  | :176 | `publishFailureAction` |
  | :214 | `previewErrorMessage` |
  | :221 | `ROLE_LABELS` |
  | :239 | `readinessStatusLabel` |
  | :247 | `publicationGapLabel` |
  | :269 | `publicationErrorMessage` |

- `lineDiff.ts:2` `DiffLine` and `:8` `lineDiff`.

`frontend/tests/fixtures/mocks.ts`:

| Line | Name |
|---|---|
| :1857 | `RELEASE_ARCHITECT_CANDIDATE_HASH` |
| :1860 | `syntheticReleaseV1` |
| :1865 | `syntheticReleaseV2` |
| :1881 | `syntheticReleaseDraft` |
| :1894 | `syntheticArchitectFieldDiffs` |
| :1905 | `syntheticChangedDefinition` |
| :1923 | `syntheticReleasePreview` |
| :1947 | `syntheticPublishedReleasePreview` |
| :1960 | `syntheticPublishSuccess` |
| :1976 | `syntheticStalePublication` |
| :1987 | `syntheticNothingToPublish` |
| :1996 | `syntheticPublicationNotReady` |
| :2019 | `RELEASE_NOTE_BLANK_ERROR` (the service triple, pinned by the join) |
| :2025 | `syntheticPublicationInvalid` |

**Join text-read rules** (they are in the join module's docstring; keep them):
- each `const <NAME>_KEYS = [` list, `export const RELEASE_DIFF_FIELDS = [` and `const PUBLICATION_GAP_CODES: readonly PublicationGapCode[] = [` appear once, single-quoted;
- `export const RELEASE_NOTE_MAX_LENGTH = 2000;` is one line;
- `ROLE_LABELS` has one `key: 'Label',` pair per line;
- the route strings read `` `${AGENT_DEFINITIONS_URL}/release-preview` `` and `` `${AGENT_DEFINITIONS_URL}/releases` ``.

## Concerns
1. **Nothing renders the `/admin/agent-definitions/review` route in a test.** No Vitest renders `App` routes, so the route is typechecked only. Task 7's Playwright (`admin-route-gate.spec.ts` and scenario (d), "the workbench link from `/admin` reaches the page") is its first behavioural check.
2. **After the controller commit, `TASK_BASE` is not `HEAD~1`.** My commit's parent is `585d4366c`, not `d83ad95ce`, so a Task 6 diff should be `585d4366c..b46dde573`, or `d83ad95ce..b46dde573` minus progress.md.
3. **The 422 note-error scenario is only reachable when JS and Python whitespace rules disagree** (for example U+001F, which JS keeps and Python strips), or when the server's rules change. The page test uses exactly that note. Blank and too-long notes are otherwise blocked on the client, which is why Task 7's (e) needs a mocked 422.
4. **Pre-existing `act(...)` warnings** from `TestRunPanel` and `WorkbenchContent` appear in the workbench suite. None come from the GraphRelease tests.
