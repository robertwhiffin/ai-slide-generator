# Task 7 report: browser proof for graph release review and publish

**Status:** DONE
**TASK_BASE:** `f611c2a88`
**Commit:** `523a64489`

## Commits

| SHA | Summary |
|---|---|
| `523a64489` | test: browser proof for graph release review and publish (#269) |

## Files

- **Created:** `frontend/tests/e2e/graph-release-review.spec.ts` (9 tests)
- **Modified:** `frontend/tests/e2e/admin-route-gate.spec.ts` (1 new test added)

## Tests

| # | Test name |
|---|---|
| (a) | `(a) Publish is disabled when the server says the draft is not publishable` |
| (a) | `(a) preview with two changed roles shows both sections; diff tab shows added and removed prompt lines` |
| (b) | `(b) 409 not-ready with no_eligible_approval disables Publish and names the role and case` |
| (b) | `(b) 409 not-ready with no_required_case shows "no active required test case" label` |
| (c) | `(c) stale 409 keeps the note; Reload preview issues exactly one GET and zero POSTs` |
| (d) | `(d) success 200 shows success panel; refetched preview shows Draft base: Graph Version 2 and no changes` |
| (d) | `(d) the Review & Publish link in the workbench navigates to the review page` |
| (e) | `(e) 422 blank-note response is rendered beside the note input; note is kept` |
| (f) | `(f) the forbidden sweep still flags Publish draft, Release history, and Rollback release` |

**Admin route gate (new):**
| `non-admin visiting /admin/agent-definitions/review is redirected with no review content` |

## Corrections applied

- **C7/C44:** `'Review & Publish'` was already in `ALLOWED_ACTION_NAMES` (length 8) from Task 6. Task 7 does not edit `forbiddenActionNames.ts`. Verified present; sweep (f) still passes.
- **C10/Q6:** Publish success mocked as 200 (not 201). Test (d) uses `syntheticPublishSuccess()` and asserts the success panel.
- **C1:** Scenario (b) tests both `no_eligible_approval` and `no_required_case` gaps. The `no_required_case` label "Architect: no active required test case" is asserted.
- **C32:** Scenario (b) uses `publishable: true` so the button is enabled before the POST. Readiness is informational only.
- **C22:** Added a separate publishable=false test to prove the `preview.publishable` check is load-bearing (the `(a) Publish is disabled when the server says the draft is not publishable` test).
- Scenario (e): the server's 422 is mocked directly (brief and task-6 deviation 3 note). The error text is keyed on `code: 'blank'` rendering as "Enter a release note.", not the server message.

## Gates

| Gate | Result |
|---|---|
| `graph-release-review.spec.ts` (9 tests, chromium) | **9 passed** |
| `admin-route-gate.spec.ts` (6 tests, chromium) | **6 passed** |
| `agent-definition-workbench.spec.ts` (78 tests, chromium) | **78 passed** |
| All three specs together (93 tests, chromium) | **93 passed** |
| Vitest full | **886 passed** (unchanged from Task 6 baseline) |
| Typecheck (`npm run typecheck`) | clean |
| Python join tests (`test_graph_release_client_join.py`, `test_draft_readiness_client_join.py`) | **31 passed** |

Initial run of the new spec: all 9 tests passed immediately (page already correctly implemented in Task 6).

## Mutation table

Each sabotage was applied, observed RED, restored with `git checkout 523a64489 -- <file>`, and confirmed clean with `git diff --exit-code`.

| # | Target | Mutation | First RED | Restored clean? |
|---|---|---|---|---|
| S1 (min) | `reviewAndPublishState.ts:99` | Replace `&& state.preview.publishable` with `&& true` | `(a) Publish is disabled when the server says the draft is not publishable` | yes |
| S2 (min) | `useReviewAndPublish.ts:26` | Add extra `await getReleasePreview()` before the real call | `(c)` getCount assertion; `(d)` getCount assertion | yes |
| S3 (min) | `App.tsx:55` | Remove `<RequireAdmin>` wrapper from the review route | `admin-route-gate.spec.ts:141` new test | yes |
| S4 (reviewer) | `useReviewAndPublish.ts:59` | Remove `if (published) await reloadPreview()` | `(d) success 200 shows success panel…` at the `getCount` poll | yes |
| S5 (controller) | `AgentDefinitionWorkbench.tsx:141` | Change link text to `Publish draft` | `agent-definition-workbench.spec.ts` browser sweep (`no control in the panel…`) | yes |

Note: S5 (controller) goes RED in `agent-definition-workbench.spec.ts` (the browser sweep), not in `(f)` of my spec. Test `(f)` is a static assertion that does not walk production code; it proves the fixture is correct but is not the browser sweep. This matches the brief's prediction.

## Deviations

1. **`publishable=false` test added as an extra (a) scenario.** The brief's minimum sabotages include "make the page publish when `publishable=false`". None of the original (a)–(f) scenarios directly tested this case (all scenarios except the new one use `publishable: true` or arrive at states where the button is disabled for other reasons). A concise extra test was added so S1 is provable.

2. **Reviewer sabotage file is `useReviewAndPublish.ts`, not `ReviewAndPublishPage.tsx`.** The brief names `ReviewAndPublishPage.tsx` for the post-success refetch. The actual refetch code is in `useReviewAndPublish.ts:59`. The sabotage was applied there and went RED as predicted on (d).

3. **Scenario (e) note value.** The brief says the 422 is reachable via a JS/Python whitespace mismatch (U+001F). The test uses `'\u001f'` as the note. This passes the client's `note.trim() !== ''` check (U+001F is not stripped by JS `trim`) but the server mock returns 422. The note value is retained and the error is shown beside the input.

4. **`syntheticPublishedReleasePreview` for publishable=false test.** This fixture returns `publishable: false` with no changed roles. The test verifies the button is disabled when `publishable: false` even with a non-blank note.

## Concerns

1. **Test (f) is a static test.** `(f)` proves the fixture is correct (the stems still flag the named actions) but does not walk production controls. The production sweep is in `agent-definition-workbench.spec.ts`. This is the same approach as the existing static rule test in that spec.

2. **The admin-route-gate test does not mock `/api/admin/agent-definitions/release-preview`.** The `failAdminSubresources` call in `beforeEach` catches `**/api/admin/**` and returns 500, so any preview fetch is answered 500 before the route renders. The test confirms the URL changes to `/` before any admin content appears.

---

## Fix round 1

**Finding I-1 (Important):** the no-flash assertion in `admin-route-gate.spec.ts` was trivially true. The original test checked `toHaveCount(0)` only AFTER `toHaveURL` had resolved the redirect, and the identity was resolved immediately via `mockIdentity(page, false)`. No flash could ever be detected.

**Root cause:** `page.goto` returns after `load` (before React's `useEffect` for setup status fires). Immediately after goto, the app is in "Loading..." state; routes have not rendered. `toHaveCount(0)` passed trivially because no routes were rendered yet, not because RequireAdmin was protecting correctly.

**Fix (commits `ed8e05dd8` and `64c2e9fcb`):**
1. Replaced `mockIdentity(page, false)` with an identity-hold route (mirrors `:106-139`).
2. Added a route counter for `/release-preview` to assert 0 GETs fired.
3. Navigated to `/admin/agent-definitions/review`.
4. Waited for the app's own setup-status "Loading..." div to disappear (`waitForFunction(() => !document.querySelector('div[style*="background: #1a1a2e"]')`). After this, RequireAdmin has been evaluated with `loading=true` (identity still held).
5. Asserted: heading `{ level: 1, name: 'Review & Publish' }` has count 0, `previewGets === 0`, URL is still `/admin/agent-definitions/review`.
6. Released identity as non-admin; asserted URL → `/`, heading still absent, landing page visible.

**Mutation and proof:** applied `if (loading) return <>{children}</>;` to `RequireAdmin` in `App.tsx` (MUT_T7_F1). The test goes RED: `toHaveCount` finds 1 element (the heading is in the DOM after the setup check clears and RequireAdmin renders the review page). Restored from `ed8e05dd8`, clean, marker 0.

**Gates after fix:**
| Gate | Result |
|---|---|
| `admin-route-gate.spec.ts` (6 tests, chromium) | **6 passed** |
| `graph-release-review.spec.ts` (9 tests, chromium) | **9 passed** |
| `agent-definition-workbench.spec.ts` (78 tests, chromium) | **78 passed** |
| Vitest full | **886 passed** |
| Typecheck | clean |
