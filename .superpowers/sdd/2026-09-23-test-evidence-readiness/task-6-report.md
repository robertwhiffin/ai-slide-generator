# #268 Task 6 report: frontend verdicts and draft readiness

**Status: DONE_WITH_CONCERNS**

- TASK6_BASE: `2d127b7f1`. The controller's ledger commit `a3352e031` sits on top of it; I did not touch it.
- Commits:
  - `af3284ef3` feat: verdict and readiness clients, strict readiness parser and join (#268)
  - `c72625092` feat: status badges, Approve/Reject controls, and readiness overlay (#268)
  - `03e6a8e54` test: Playwright readiness mock and the Approve-run E2E (#268)
  - this report, force-added on top of those three
- No Review & Publish page, Publish button or publication code was added (C1). I did not touch `src/services/agent_test_workbench.py` or the cleanup tests.

## What landed

### Clients (`frontend/src/api/agentDefinitions.ts`, C17 and C22)

**`recordTestRunVerdict(runId, {verdict, notes})`**
- It POSTs to `/test-runs/{id}/verdict`.
- The body is built from `VERDICT_REQUEST_KEYS`, so it is exactly `{verdict, notes}`. `notes ?? null` means the `notes` key is always present, even when a caller omits it.
- A 200 is parsed strictly as evidence. The client also requires that the evidence's `run_id` and `verdict` equal what was sent; otherwise it throws `InvalidTestRunResponseError`.
- Refusals are typed as `TestRunVerdictApiError` with a `TestRunVerdictFailure`:
  - the exact 404 `Test run not found` becomes `test_run_not_found`;
  - a 403 with a `{detail}` body becomes `verdict_forbidden`;
  - a 422 becomes `ineligible_for_approval` (exact `{code, reason, message}`, with the reason from `INELIGIBILITY_REASONS`);
  - a 422 becomes `invalid_verdict` (exact `{code, errors}`, non-empty).
- A malformed 422 is `InvalidTestRunResponseError`. Any other status is `AgentDefinitionApiError`, which covers the C7 500 for an `IntegrityError`.

**`getDraftReadiness()` and `parseDraftReadinessResponse`**
- The parser checks exact keys at all three levels: `DRAFT_READINESS_KEYS`, `AGENT_READINESS_KEYS` and `TEST_CASE_READINESS_KEYS`.
- `status` must be one of the four snake_case codes in `READINESS_STATUSES`. A label such as `'Needs test'` is rejected.
- Hashes must be lowercase sha256. `run_id`, case id and case version must be positive integers.
- Each case must belong to its own role, and each role may appear at most once.

**Python join: `tests/unit/test_draft_readiness_client_join.py` (9 tests, new)**
- It follows the text-read style of `test_test_run_failure_contract_client_join.py`. It pins:
  - the three TS key lists against `DraftReadinessResponse`, `AgentReadinessResponse` and `TestCaseReadinessResponse` `.model_fields`;
  - strict, snake_case models on both sides;
  - the status codes against the `status` Literal;
  - `VERDICT_REQUEST_KEYS` against `VerdictRequest`, including that `notes` is required;
  - the ineligibility reasons against the response Literal and `_INELIGIBLE_MESSAGES`;
  - both refusal codes;
  - `TEST_RUN_NOT_FOUND_DETAIL`;
  - the messages in `mocks.ts` `syntheticVerdictIneligible`.
- The existing join formats are untouched. All four client-join files pass: 45 tests.

### Forbidden-action guard (C23)
- `ALLOWED_ACTION_NAMES` gains exactly `'Approve run'` and `'Reject run'`. The stems are unchanged.
- Both `toHaveLength` sites are now 7: `AgentDefinitionWorkbench.test.tsx:378` and `tests/e2e/agent-definition-workbench.spec.ts:1518`.
- Both sites also assert that these stay forbidden: `forbidsActionName('Approve run and publish')`, `'Approve all'` and `'Reject all'`. The Vitest site additionally checks `'Approve runs'`.

### One reducer, one counter, one gate (C24)
- `'verdict'` was added to `TestOperationKind` and `TEST_OPERATIONS`.
  - It starts through the shared `startTestOperation`, so it is blocked by `operationBlocked()` and by the reducer's `pendingSave !== null` backstop.
  - `PendingDraftSave` gains optional `runId` and `verdict`, so that only the verdict's own evidence can settle it.
- `testVerdictRecorded`:
  - The response replaces the candidate or baseline evidence whose `run_id` matches.
  - Any history read still in flight is dropped.
  - An incoherent response (another run, role or verdict) is contained as `Unable to record the verdict because the server response was invalid.`
- Readiness has one slot, `state.readiness`, holding `{status, data, requestId, refreshRequested}`.
  - `readinessLoaded` is dropped when its request id is not the latest.
  - It is also dropped when `draft_lock_version !== state.draft.lock_version`. The status then becomes `stale` and the last accepted data is kept.
  - It is an ungated read and never touches `pendingSave`.
- **Refresh.** `draftEditorReducer` now wraps the old switch, which is renamed `reduceDraftEditor`.
  - The wrapper increments `readiness.refreshRequested` exactly when a pending `save`, `upgrade`, `schemaUpgrade` or any test operation settles, whatever the outcome.
  - A dropped completion returns the same state, so it asks for nothing.
  - `WorkbenchContent` runs `useEffect(() => loadReadiness(), [loadReadiness, refreshRequested])`, so readiness is read on load and after every settled write.
  - `loadReadiness` is a stable `useCallback` that uses the one request counter.
- `mergeConflict` and `succeedWrite` now spread `...state`, so the new slot survives. Before this change they built the state object literally.

### Status (C25)
- `DraftStatus` has the six values.
- The signature is `draftStatus(entry, readiness: AgentReadiness | null)`, with this precedence:
  1. `Unsaved`, then `Clean`.
  2. `Needs test` when there is no item, the item has another `candidate_hash`, or `missing_required_case` is set.
  3. Otherwise the cases decide worst-first: `test_failed`, then `needs_test`, then `awaiting_review`, else `Approved`.
- The helper `agentReadinessFor(state, key)` supplies the item.
- Both callers pass it: the navigation in `AgentDefinitionWorkbench.tsx`, and `DefinitionEditor.tsx` through a new `readiness` prop.

### Verdict controls (C26, `TestRunPanel.tsx`)
- `VerdictControls` sits in the candidate evidence region (`Candidate run verdict`) and the published-baseline region (`Published baseline verdict`), which satisfies C9.
- Controls:
  - **Approve run** is disabled, with visible text and an `aria-describedby`, showing "Only completed runs can be reviewed" or "Deterministic checks did not pass".
  - **Reject run** is disabled when the run is not completed.
  - Both controls are also disabled while the gate is held.
  - An approved run offers only Reject run. A rejected run offers only Approve run, disabled with its reason if its checks failed.
- The notes textarea is optional and has `maxLength` 2000. Blank notes are sent as `null`, and the notes clear after the verdict settles.
- Reviewer, time and notes are rendered as text only.
- Both P1 labels are verdict-aware: "(approved)", "(rejected)" or "(not approved)".
- The pending text is "Recording the verdict…".

### Playwright
- `installWorkbenchMock` registers a default readiness route by URL, answering `syntheticDraftReadinessBody()`.
- `installAgentTestMock` routes the verdict POST.
- Two new specs:
  - Approve with notes gives the exact body, the badge turns `Approved`, and readiness is re-read exactly once more.
  - A readiness answer read at another lock never paints Approved.

### Fixtures (`frontend/tests/fixtures/mocks.ts`)
- `syntheticTestCaseReadiness`, `syntheticAgentReadiness`, `syntheticDraftReadinessBody` and `syntheticVerdictIneligible` were appended.
- None begins with an existing exported name.

## TDD
- **RED before implementation:**
  - client Vitest: 49/49 failed (missing exports);
  - Python join: 8/9 failed;
  - forbidden-guard test: 1 failed;
  - reducer and state: 31 failed;
  - `TestRunPanel` verdict controls: 14 failed.
- **Written after the wiring:** the `AgentDefinitionWorkbench.test.tsx` integration tests (12 new) and the 2 E2E specs. I proved they bite by mutation instead (M4, M6, M8, M10, M13, M14, M16, M20 and M23 below all RED them).

## Gates, with real numbers
- **Vitest** (`npm run test:unit`): 721 passed, 16 files. Base was 609 passed, 15 files, so this adds 112 tests.
- **typecheck** (`tsc -b`): clean.
- **ESLint** on every touched file: clean. Repo-wide `eslint .` still shows 2 existing errors in untouched files, `src/api/config.ts:675` and `tests/fixtures/base-test.ts:47`.
- **Playwright `agent-definition-workbench.spec.ts`** (chromium): 78 passed. Base was 76; the 2 new specs pass.
- **Playwright full suite** (chromium): 93 failed, 570 passed, 18 skipped, 11 did not run.
  - Base run at `2d127b7f1` in a temporary worktree, same way: 94 failed, 567 passed, 18 skipped, 11 did not run.
  - The failure sets differ only by 3 flaky, backend-dependent tests, each failing in one run but not the other:
    - `deck-integrity` Profiles vs Deck Prompts;
    - `export-ui` ExportButtons vs PresentButton;
    - one `slide-generator` test that failed only on base.
  - The cause of the failures is the missing backend: `ECONNREFUSED 127.0.0.1:8000`.
  - No `agent-definition` spec fails in either run.
  - The full suite rewrote 46 `docs/user-guide/images/*.png` screenshots. I restored them with `git checkout`.
- **Python joins** (4 client-join files): 45 passed.
- **Full `tests/unit`:** 6 failed, 6783 passed, 110 skipped, 136 warnings. The six failures are exactly the baseline nodes and causes:
  - `test_deploy_autoscaling::TestGetOrCreateLakebase` ×2 ("provisioned" / "called 0 times");
  - `test_style_exclusivity_chokepoint::TestModelDumpIsNotTheChokepoint` ×3 (`_FakeSession.execute`);
  - `test_style_exclusivity_persistence_boundary::…test_session_manager_create_session` ("no active Graph Release").
- `.venv` is absent. Port 3000 is free after the runs. No `npm install` was run. The temporary worktree is removed.

## Mutation table
- **Driver:** `/tmp/t268-6-mutate.py`. Results are in `/tmp/t268-6-mutations.json` and `/tmp/t268-6-mut.log`.
- **Per-row conditions:**
  - each anchor occurs exactly once;
  - the file changed;
  - the scoped Vitest file or files, or the Python join, went RED;
  - the file was restored with `git checkout 03e6a8e54 -- <file>`, and `git diff --quiet` was clean.
- **Totals:** 24 of 24 went RED. After the sweep the full Vitest run was 721 GREEN.

| # | Guard | Mutation | RED |
|---|---|---|---|
| M1 | parser top-level exact keys | drop `hasExactKeys(…DRAFT_READINESS_KEYS)` | extra top-level key; malformed 200 |
| M2 | parser case exact keys | drop `hasExactKeys(…TEST_CASE_READINESS_KEYS)` | extra case key |
| M3 | parser agent exact keys | drop `hasExactKeys(…AGENT_READINESS_KEYS)` | extra agent key |
| **M4 (controller S6)** | freshness by lock | the `draft_lock_version !== saved lock` branch set to `false` | re-run clean (marker `MUT_M4`), 4 failed: reducer "older lock" and "newer lock" drops; "a stale answer keeps the last accepted data"; workbench "drops a readiness answer read at another lock, so it cannot paint Approved" |
| M5 | freshness by request id | drop the `requestId !==` check | reducer "drops an answer whose request is not the latest one" |
| **M6 (reviewer S6)** | Approve disabled when checks failed | `approveReason` set to `null` for a completed run | re-run clean (marker `MUT_M6`), 3 failed: panel "disables Approve run … when the deterministic checks failed"; panel "a rejected run whose checks failed keeps Approve run disabled"; workbench "a run whose checks failed offers no enabled Approve run" |
| M7 | reducer gate | `testOperationStarted` lets a verdict start while the gate is held | "cannot start while any operation holds the gate …" |
| M8 | hook gate (`operationBlocked()`) | a verdict bypasses it | workbench held-verdict test: a second verdict POST |
| M9 | always send `notes` | `notes: request.notes` | "always sends notes, as null …" |
| M10 | stale-hash guard | drop the `candidate_hash !==` term | reducer hash-moved test; workbench "never shows Approved for readiness of another saved candidate" |
| M11 | `missing_required_case` guard | drop the term | the reducer `missing_required_case` test |
| M12 | worst-first order | swap `test_failed` and `needs_test` | the reducer aggregation test |
| M13 | refresh after a settled write | the wrapper returns `next` | 9 reducer "asks for a fresh readiness read after …" cases, plus workbench re-read tests |
| M14 | component re-reads | drop `readinessRefresh` from the effect's dependencies | workbench save, verdict and Upgrade re-read tests (8) |
| M15 | verdict coherence | always `true` | three "contains a verdict response for another …" tests |
| M16 | the response replaces the evidence | keep the old candidate evidence | reducer replace test; workbench Approve and Reject flows |
| M17 | drop in-flight history on a verdict | keep `historyRequestId` | "drops any history read still in flight …" |
| M18 | client `run_id` / verdict check | removed | three client "contains … evidence for another run / verdict / no verdict" tests |
| M19 | Reject disabled when not completed | `rejectReason = null` | three panel `*_error` / incomplete cases |
| M20 | the `'Reject run'` exemption | removed | guard length and `toContain` tests; the workbench sweep |
| M21 | TS key list vs server | add `'blocking'` to `AGENT_READINESS_KEYS` | Python `test_the_client_agent_readiness_keys_are_exactly_the_server_fields` |
| M22 | codes, not labels | add `'Approved'` to `READINESS_STATUSES` | Python `test_the_client_readiness_statuses_are_the_server_codes_not_labels` |
| M23 | verdict is a test operation | `'verdict'` removed from `TEST_OPERATIONS` | reducer "is one of the test operations" and the verdict flows (13) |
| M24 | verdict-aware label | `verdictLabel` always "not approved" | panel label cases (3) |

**Note on counts.** During the sweep a Playwright base run was using the CPU at the same time. Under that contention the workbench Vitest file reported extra timeout-driven failures: 10 failed for M4 and M10, where clean re-runs give 4. The RED verdicts stand. The two S6 targets were re-run clean with markers and their exact REDs are listed above.

## Deviations
1. **The client tests are in a new Vitest file,** `src/components/Admin/AgentDefinitionWorkbench/verdictReadinessClient.test.ts`. The brief's `frontend/tests/agent-definition-workbench/…` location is excluded by `vitest.config` (`include: src/**`).
2. **Readiness is refreshed after `upgrade` and `schemaUpgrade` too, not only after `save`.** Both are saves that change the candidate hash. Sources that write nothing (probe, source recovery) ask for no refresh.
3. **A readiness answer at a different lock is kept in the slot as `status: 'stale'`.** Its data is not adopted and the last accepted data stays. The UI shows nothing extra.
4. **The notes textarea is always visible** rather than opening on click. This follows C26 ("an optional textarea"), which overrides the brief's "open a notes textarea".
5. **Refusal copy is fixed client text.** A `verdict_forbidden` refusal shows "Unable to record the verdict (403)." `test_run_not_found` shows "This test run no longer exists. Refresh test cases." Server messages are never rendered.
6. **Harnesses route readiness by URL.** `mockWorkbenchApi` gained `readiness`, `verdict` and `workbench` options. `mockedResponse` and `mockWorkbenchWithPuts` answer readiness with the default body.
7. **The 8 GET-counting sites were updated deliberately,** each with a comment naming the readiness GET. Two more sites needed `await waitFor(readinessGets…)` so that a post-settle readiness GET lands on the right harness.
8. **`NAMES_267` gained the six #268 names,** under the same #266 disjointness rule.

## Concerns
1. **The browser guard sweep versus the "Approved" status label.** The navigation button renders its status inside the button, so an Approved role's button has the text content "ArchitectApproved".
   - The E2E sweep reads each control's `textContent` and flags that on the `approve` stem, even though the accessible name is "Architect". The Vitest sweep reads accessible names and is unaffected.
   - No existing sweep runs in an Approved state, so nothing is RED today. My new E2E sweeps only the testing aside, and asserts the accessible name `Architect`; I did not loosen any stem.
   - #269, or any future sweep in an Approved state, will hit this. The fix is either to move the status label out of the button (about 41 assertions read the status through the button) or to have the browser lane read accessible names. This is a controller or product decision.
2. **Which verdict labels the baseline inside a candidate run.** The heading at `TestRunPanel.tsx:129` ("Published baseline (…)") now follows the **candidate run's** verdict, because C26 says to make both labels verdict-aware. That section shows the baseline output recorded inside the candidate run, which has no verdict of its own. Approving the candidate run therefore makes it read "Published baseline (approved)". The heading at `:608` correctly follows the baseline run's own verdict. The alternative is to keep `:129` fixed at "(not approved)".
3. **StrictMode double-reads readiness on mount in dev.** The Vite dev build runs `<React.StrictMode>`, which runs effects twice, so load issues 2 readiness GETs. The reducer drops the older answer by request id. Production builds read once. My E2E asserts ≥1 on load and exactly +1 after the verdict.
4. **Two new React `act(...)` warnings in Vitest stderr,** from the post-save readiness read landing after the test body. They are in "retains A3 typed while A2 is pending …" and "edits custom blocks locally and sends them only on an explicit Save". The warning count went from 6 to 8. All tests pass.
5. **The integration and E2E tests were written after the wiring,** not RED-first. Their bite was proven by mutation (see above), not by a RED run before the code existed.
6. **The workbench Vitest file is timing-sensitive under CPU contention.** See the note on counts above.

## Exported names for #269 (C22), at `03e6a8e54`
`frontend/src/api/agentDefinitions.ts`:

| Name | Kind | Line |
|---|---|---|
| `TestRunVerdictRequest` | interface | :1665 |
| `TestRunIneligibilityReason` | type | :1670 |
| `TestRunVerdictFailure` | type | :1676 |
| `TestRunVerdictApiError` | class | :1683 |
| `TEST_RUN_NOT_FOUND_DETAIL` | const | :1696 |
| `recordTestRunVerdict(runId, {verdict, notes}): Promise<TestRunEvidence>` | function | :1744 |
| `ReadinessStatus` | type | :1766 |
| `TestCaseReadiness` | interface | :1769 |
| `AgentReadiness` | interface | :1783 |
| `DraftReadiness` | interface | :1797 |
| `parseDraftReadinessResponse(value): DraftReadiness \| null` | function | :1856 |
| `getDraftReadiness(): Promise<DraftReadiness>` | function | :1870 |

`frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`:

| Name | Kind | Line |
|---|---|---|
| `DraftStatus` | type (six values) | :40 |
| `TestOperationKind` | type | :227 |
| `TEST_OPERATIONS` | const (includes `'verdict'`) | :230 |
| `DraftReadinessState` | interface | :266 |
| `agentReadinessFor` | function | :685 |
| `draftStatus(entry, readiness)` | function | :696 |

`frontend/tests/fixtures/mocks.ts`:

| Name | Line |
|---|---|
| `syntheticTestCaseReadiness` | :1768 |
| `syntheticAgentReadiness` | :1784 |
| `syntheticDraftReadinessBody` | :1803 |
| `syntheticVerdictIneligible` | :1821 |

**Guard:** `frontend/tests/fixtures/forbiddenActionNames.ts:42-43` holds `'Approve run'` and `'Reject run'`, so `ALLOWED_ACTION_NAMES` now has 7 entries. #269's C7 becomes 8, at `AgentDefinitionWorkbench.test.tsx:378` and `tests/e2e/agent-definition-workbench.spec.ts:1518`.

**Join:** `tests/unit/test_draft_readiness_client_join.py`. Its text-read rules are in the module docstring.

## Fix round 1 (review: 2 Important, 5 Minor, plus Task 4 M2)

**Status: DONE.** The base is `6c489cbd8`; I left the controller's ledger commits alone.

**Commits:**
- `5c0a65c1b` fix: nav status beside the button, fixed candidate baseline label (#268)
- `bc5a177cd` test: cleanup's no-runtime test reaches the DELETE (#268)
- this report section, force-added on top

### What changed
- **I1: the status badge sits beside the nav button, not inside it.**
  - In `AgentDefinitionWorkbench.tsx`, each role renders a `<div>` wrapper holding the `<button>` and a sibling `<span id="node-status-<agent_key>">`. The button's text is only the display name, and it points at the badge with `aria-describedby`.
  - The guard, its stems and its text-content lane are untouched.
  - **Vitest:** 42 nav status assertions moved from `toHaveTextContent` to `toHaveAccessibleDescription`. That is 41 found by regex plus 1 `new RegExp(...)` site. The 8 `.textContent` status-before/after comparisons now use a `navStatus()` helper, which reads the element named by `aria-describedby`.
  - **E2E:** 15 nav `toContainText` status assertions became `toHaveAccessibleDescription`. `architectNavStatus` gained the companion `navStatusText()`, used by the probe test's before/after comparison.
  - **New Vitest test:** "keeps every status out of the nav button: its text is the name, its description the status". With Architect Approved it asserts:
    - the button's text is exactly `Architect`;
    - `forbidsActionName(textContent)` is false for every nav button;
    - the badge is not inside a `<button>`;
    - Foreman, which has no status, has no `aria-describedby`.
  - **E2E verdict spec:** it now asserts `toHaveText('Architect')` and that no nav button's text trips `forbidsActionName`. Its guard sweep is back to the whole Agent Definitions panel, text content included.
- **I2: the candidate run's baseline column heading is fixed.**
  - In `TestRunPanel.tsx`, the heading inside a candidate run always reads "Published baseline (not approved)". The baseline rerun's own heading is still verdict-aware.
  - The label cases for M24 were flipped: for a null, approved or rejected candidate, the heading is always "(not approved)". The workbench test and the E2E were flipped the same way.
  - New case: an approved candidate still shows "Published baseline (not approved)" while an approved baseline rerun shows "Published baseline rerun (approved)".
- **m1:** `onRecordVerdict` and `recordVerdict` now return `Promise<boolean>`. The notes clear only when the result is `true`. New panel test: a refused verdict keeps the notes. The workbench refused-verdict test now also asserts that the typed notes survive.
- **m2:** new workbench test, "Approve run on the published baseline replaces the baseline evidence and re-reads readiness". It checks:
  - the POST goes to `/test-runs/899/verdict` with notes `null`;
  - the baseline heading turns "(approved)";
  - the candidate's evidence is untouched;
  - readiness is read twice;
  - the role stays "Awaiting review", because readiness ignores baseline runs.
- **m3:** the two tests now wait for their readiness GETs to land. Those are "retains A3 typed while A2 is pending…" and "edits custom blocks locally…". The workbench `act` warning count is back to the base 6; the remaining ones are all in tests that already warned at base.
- **m4:** a new exported `InvalidReadinessResponseError` (`agentDefinitions.ts:1808`) with the message "Draft readiness response did not match the expected contract." `getDraftReadiness` throws it for a malformed 200. The test asserts it is not an `InvalidTestRunResponseError`.
- **m5:** `draftStatus` returns `Approved` only when `readiness.ready` is true, and `Needs test` otherwise. New test: empty `cases` with `ready: false` is Needs test, and all-approved cases with `ready: false` are too.
- **Task 4 M2:** `test_cleanup_never_touches_a_runtime` now makes two runs and calls cleanup with `per_case_limit=1`. It asserts the result is `1`, the older run is deleted and the newer run survives.

### Gates
- Vitest: 726 passed across 16 files.
- typecheck: clean.
- ESLint on the touched files: clean.
- Playwright `agent-definition-workbench.spec.ts`: 78 passed.
- The Python join tests plus `test_agent_test_workbench.py`: 290 passed.
- Full `tests/unit`: 6 failed, 6783 passed, 110 skipped, 136 warnings. These are exactly the baseline nodes and causes: autoscaling ×2, `_FakeSession.execute` ×3, "no active Graph Release" ×1.
- `.venv` is absent and port 3000 is free.

### Mutations
Each mutation was applied, run, and restored from `bc5a177cd` with `git checkout`. Every one had a marker count of 1, restored clean, and went RED.

| # | Fix | Mutation | RED |
|---|---|---|---|
| F1 | I1 | status `<span>` moved back inside the `<button>` | "keeps every status out of the nav button…" |
| F2 | I2 | the candidate's baseline heading uses `verdictLabel(evidence)` again | 3 panel cases (approved and rejected candidate, the approved-vs-approved case) and the workbench Approve flow |
| F3 | m1 | notes cleared unconditionally | the panel "keeps the typed notes…" test and the workbench refused-verdict test |
| F4 | m4 | a malformed readiness 200 throws `InvalidTestRunResponseError` | the readiness-specific client test |
| F5 | m5 | `return 'Approved'` whatever `ready` says | the `ready`-false `draftStatus` test |
| F6 | Task 4 M2 | `self._runtime()` inserted before cleanup's DELETE | `test_cleanup_never_touches_a_runtime` (1 of 245). The pre-fix version of the test (from `6c489cbd8`) stays GREEN under the same mutation, which confirms M2. |

F1 REDs only the new test. The `toHaveAccessibleDescription` assertions still pass when the badge is a child, since `aria-describedby` still resolves; the text-content test is the guard for that case.

### Per finding

| Finding | State |
|---|---|
| I1 | addressed |
| I2 | addressed |
| m1 | addressed |
| m2 | addressed |
| m3 | addressed |
| m4 | addressed |
| m5 | addressed |
| Task 4 M2 | addressed |

### Remaining notes
- In the hook, `recordVerdict` returns `true` when the verdict request succeeds, even if the reducer then rejects the response as incoherent. In that case the notes clear while the panel shows the invalid-response alert.
- The E2E still accepts one or more readiness reads on load, because the dev build runs under StrictMode.
