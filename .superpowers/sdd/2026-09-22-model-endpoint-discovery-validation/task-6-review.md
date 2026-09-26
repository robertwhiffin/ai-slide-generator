# Task 6 review — probe UI, browser recovery, complete verification (#266)

Reviewer: independent task reviewer. Range `e55ca1852..6a7fe0ec0` (implementation `c66c2623b` + report). HEAD `0ee136637` (docs-only ledger commit on top) used as `PIN`.

## Spec Compliance: ✅

Every brief clause has code and a test that I either read or sabotaged:

- Explicit **Test structured output** action; only route `POST /draft/{agent_key}/model-endpoint-probe`; body built as `{ lock_version }` only (`agentDefinitions.ts` `probeDraftStructuredOutput`). No `ServingEndpointsAPI.query`, OpenAPI inference, `run_candidate`, #267 route or catalog call in the diff.
- Probe joins the one gate: `DraftOperationKind` gains `'probe'` in the one `pendingSave` slot; the hook uses the same `operationBlocked()`, `nextRequestIdRef`, `inFlightRequestIdRef`; the render gate stays `pending !== null`. No second reducer/ref/gate (C15). Catalog Refresh stays outside the gate (`DefinitionEditor.tsx` Refresh button has no `disabled`, and a test asserts Refresh while a probe is pending).
- Disabled while the local endpoint is unsaved (button, hook and reducer) or any operation is pending.
- Result handling: `settleProbe` changes only `pendingSave` and the role's `probeResult`; lock/saved/form/status asserted with `toBe`. 409 reuses `mergeConflict` (seven-role). 422 reuses `rejectOperation` (binds the endpoint field). `adoptAuthoritativeDefinition` has no hunk in the diff.
- Stale result clearing: any `endpoint_name` edit, `reloadServer`, `restoreRetained` (both paths), and `succeedWrite`/`mergeConflict` when the saved hash or endpoint changes.
- Strict client mapping: exact keys, lowercase 64-hex hash, non-negative lock; status fixes code and `retryable` per the Task 5 override table (403 forbidden/false, 422 unsupported/false, 503 failed/true). A malformed body at 403/503 is a plain `AgentDefinitionApiError` → contained "Unable to test structured output (N)." with no Retry. Matches the server DTOs (`schemas/agent_definitions.py:480-509`, `extra="forbid"`) and status map (`routes/agent_definitions.py:147-151`).
- Retry rendered only for `outcome: 'failed' && retryable`.
- Harness (C17): both Vitest harnesses route the probe by URL before the PUT fallback and throw `unexpected probe POST` when unrouted; Playwright uses a distinct `PROBE_ENDPOINT` glob. `allGets()` backstops at `AgentDefinitionWorkbench.test.tsx:888/1182/1500` survive unchanged. The only removed test lines are five e2e `toContainText('1')` → `toContainText('Lock version1')`: strictly stronger, not weaker.
- Browser flows present: discovery→search→refresh-with-newer→explicit save→probe; manual custom name (five leaves on Architect, C10; raw-body forbidden-key sweep); manual server-validation failure/correction/retry without remount; probe ×3 codes; empty discovery; URL rejection zero PUT/zero probe; catalogue 503 recovery; bare catalog GETs.
- Accessible names: "Test structured output", "Retry structured output test", "Structured output test result" are not substrings of each other or of any existing workbench name (checked against Refresh models, Search discovered models, Discovered models, Custom endpoint name, Save Draft, Needs test, Lock version, Draft base, the restore buttons); `getByText('Lock version')` does not match "Draft lock". None trips `FORBIDDEN_ACTION_STEMS` (`\brun\b|approve|reject|…|publish|history|rollback`).

⚠️ items (accepted, no change required):
- ⚠️ Probe stays enabled while non-endpoint fields are unsaved (implementer concern 2). This is the brief's literal rule, the copy says "saved candidate", and a test pins it.
- ⚠️ The client-only identity check (concern 3) is consistent with today's server: the server's reported lock is the current lock only when it equals the expected lock (otherwise a 409). A future server reporting a different lock would fail closed as "invalid response".
- ⚠️ A probe 409 opens the conflict panel and keeps local values, like Upgrade (concern 4). This reuses the seven-role merge as required.
- ⚠️ Step 5 (range proof, whole-branch package, local merge) is controller work and is not in this range.

## Strengths

- One-gate discipline is exact. The hook guard returns *before* allocating a request ID, and the reducer backstop exists for the stale-closure case. Each layer has its own dedicated test, and all three went RED independently (below).
- The status→code→retryable table is enforced in the parser, so the UI cannot offer Retry for an untyped 403/503 (an auth dependency's `{detail}` or a proxy page).
- `probeErrorMessage` never reads server `detail`.
- The mutation table is broad (24 rows), and my independent re-runs matched its layer claims in a wider scope (the full two-file Vitest suite, not `-t probe`).
- Fixtures are appended after `ENDPOINT_NAME_POLICY_CASES`. The strict-JSON blocks are untouched and there are no same-prefix names. The text-read joins pass (338).

## Issues

### Critical
None.

### Important
None.

### Minor

**m1 — Two unjoined copies of the probe failure contract**
- Where: `frontend/src/api/agentDefinitions.ts:1023` (`PROBE_FAILURE_CONTRACT`, production) and `frontend/tests/fixtures/mocks.ts:1602` (`STRUCTURED_OUTPUT_PROBE_FAILURES`, fixture). Both hand-copy `src/api/routes/agent_definitions.py:147-151` and `src/services/model_endpoint_probe.py:65-78`.
- What: implementer concern 5 names only the fixture's messages. The more consequential copy is the production status/code/retryable table.
- Why Minor, not Important:
  - Drift fails closed. A reclassified typed failure becomes a contained generic "Unable to test structured output (N)." with no Retry. It never becomes a wrong typed Retry.
  - The UI renders the server's message, not the copied one.
  - This is not a security policy. The Task 4 policy join was ruled necessary because a stricter client copy would silently block legitimate saves. Nothing here blocks a write.
- Fix: one Python text-read test that asserts, for each code, the triple (status, retryable, message) from `_PROBE_FAILURE_STATUS` and `_UNSUPPORTED`/`_FORBIDDEN`/`_FAILED` against both TS literals. Write it in the style of `test_endpoint_name_policy_client_join.py`, and keep the literals single-line and strict so they parse. This is cheap and can go in the whole-branch fix wave.

**m2 — The unrouted-probe tripwire exists only in Vitest**
- Where: `frontend/tests/e2e/agent-definition-workbench.spec.ts:2031`.
- What: the report's claim that "an unrouted probe throws" holds for both Vitest harnesses. The Playwright spec has no default probe route or catch-all. The pre-existing 60 tests never click the button, so the risk is low, but an unrouted probe there would reach the dev proxy and surface as a contained alert rather than a test failure.
- Fix (optional): add a default probe route in `installWorkbenchMock` that fails the test, which tests override with `installProbeMock`.

**m3 — A retained result on another role shows a historical lock**
- Where: `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx:158`.
- What: role B keeps its probe result across role A's save, correctly, because B's candidate is unchanged (`probeResultAfterAdoption`, `draftEditorState.ts:674`). But its identity line still reads the lock at probe time, while "Lock version" shows the new one. The line is truthful but could be read as current.
- Fix (optional): label it "Tested at draft lock N".

## Sabotage evidence

Environment:
- `PIN=0ee136637acf1b12ce1b00eb201e09657b9439cf`.
- `lsof -i :3000` was empty before and after every Playwright run.
- The triple check (`git status --porcelain`, `git diff HEAD --stat`, `git diff --cached --stat`) was empty before the first mutation and after every restore.
- Each marker's anchor count was 1, and the marker's `grep -c` was 1 applied and 0 restored.
- Restore was `git checkout $PIN -- <file>`.
- Scope V2 = `(cd frontend && npx vitest run src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)` (GREEN 320).
- Scope P = `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1 -g 'model endpoint')` (GREEN 9).

### Reviewer target: allow Probe while the endpoint is unsaved, one layer at a time

| # | Layer | Mutation (marker) | V2 | P |
|---|---|---|---|---|
| R1 | button | `DefinitionEditor.tsx` `probeDisabled = operationsDisabled` (`REVIEW266_6_R1_BUTTON`) | **RED 1/320**: `…structured-output probe > is disabled while the local endpoint is unsaved, and probes the newly saved candidate once it is saved` | **RED 3/9**: `model endpoint discovery: first Model-tab read…`, `model endpoint manual server-validation failure…`, `model endpoint URL rejection … zero PUT and zero probe` (all `toBeDisabled`) |
| R2 | hook | `useDraftEditor.ts` guard → `if (false && probeEndpointUnsaved(...)) return;` (`REVIEW266_6_R2_HOOK`) | **RED 1/320**: `…structured-output probe > a hook probe with an unsaved endpoint allocates no request, and a saved one sends only the lock` | 0/9. Expected and not a gap: the button masks the hook in the browser. |
| R3 | reducer | `draftEditorState.ts` `probeStarted` backstop → `if (false && …) return state;` (`REVIEW266_6_R3_REDUCER`) | **RED 1/320**: `structured-output probe in the one draft gate > refuses to start a probe while the role's local endpoint differs from its saved endpoint` | 0/9. Expected; the button and hook mask it. |

Every layer is independently guarded, and no layer is free within its own scope. GREEN after each restore: V2 320 and P 9.

### Own mutations: cross-operation ordering

| # | Mutation (marker) | V2 |
|---|---|---|
| R4 | `settleProbe`: on a non-matching (stale) request ID, instead of `return state`, write the stale result into the current `pendingSave` role's `probeResult` and keep the newer pending save (`REVIEW266_6_R4_STALE_OVERWRITE`). This differs from implementer M13, which also settled the pending slot. The anchor was the two-line `matchingPending(state, 'probe', …)` + return, which is unique. The mutation executed: the RED is an `Object.is` failure on a changed state. | **RED 2/320**: `…one draft gate > only the pending probe's own request ID may complete it, and a probe ID never completes another operation`, and `…one draft gate > a late probe response after a newer save has started never clobbers state (monotonic IDs)` |
| R5 | Hook probe drops `inFlightRequestIdRef.current = requestId` (`REVIEW266_6_R5_NO_INFLIGHT_REF`). The render-time `pendingSave` is then the only guard, which a same-tick second operation cannot see. | **RED 3/320**: `useDraftEditor shared request gate > double probe architect inside one tick…`, `…probe then save architect inside one tick…`, `…probe then schema upgrade builder inside one tick issues only the first request` |

GREEN after each restore: V2 320.

## Final gates (reviewer re-run at PIN, clean tree)

- V2: 320 passed. Full `npm run test:unit`: 14 files, 486 passed. `npm run typecheck`: exit 0.
- Playwright full workbench spec: 69 passed.
- Text-read joins: `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr python -m pytest -q -p no:randomly tests/unit/test_prompt_assembler.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_endpoint_name_policy_client_join.py` gave 338 passed.
- `git grep REVIEW266_6 -- frontend` gives 0. The triple check is empty.
- Not re-run: the backend focused matrix, full `tests/unit` and PostgreSQL. Task 6 changes no Python, so the implementer's figures stand for the whole-branch review to confirm.

## Task quality: Approved

No Critical or Important findings. The three Minors can go to the whole-branch fix wave; m1 is the one worth doing.
