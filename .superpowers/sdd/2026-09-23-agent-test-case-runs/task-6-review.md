# #267 Task 6 review: workbench Input / Compare / Checks panels

- **Reviewer:** independent task reviewer (Opus).
- **Range:** `5bb5a8874..e18a14910`. HEAD is `e1e85ff60`, which adds a docs commit only.
- **Worktree:** `.worktrees/issue-267-plan`. The tree was clean before and after the review, and the only file added is this review.

## Verdicts
- **Spec compliance:** ✅ ⚠️
  - The Task 6 brief is met, along with C25, C38 and the Task 5 carry-forwards.
  - Two acceptance-criterion gaps remain at the product surface: I-1 (criterion 2) and I-2 (P1 and criteria 6 and 9 across a reload). They come from the plan's scope, not from the implementer departing from the brief.
- **Task quality:** Approved with follow-ups. There are 0 Critical, 2 Important and 6 Minor findings.

## Spec Compliance

### Task 6 brief, corrections and rulings
| Item | Result | Evidence |
|---|---|---|
| Panel is in the existing `<aside aria-label="Isolated testing">`, with no new column and no `DraftStatus` change (C25/C40) | ✅ | `AgentDefinitionWorkbench.tsx` diff: `min-w-0` is added only to the aside. `DraftStatus` is untouched. |
| Input, Compare and Checks sub-tabs | ✅ | `TestRunPanel.tsx:470-550`. Input shows the synthetic payload, the assembled prompt (or "No run yet"), and `Model payload sent` (C37 §6). Compare shows the candidate's structured and raw output next to the copied baseline, or "Baseline not recorded", plus the rerun region. Checks is a table with `data-check-state`. |
| "Published baseline (not approved)" label (P1) | ✅ | `:117`. The controller's sabotage turned 1/472 RED. |
| Synthetic-data warning shown unconditionally, and beside the payload editor through `aria-describedby` (P7) | ✅ | `:316-318` and `:240-246` |
| "not reported" for NULL tokens (P9) | ✅ | `:71-73` |
| Only active versions are listed or run (P5) | ✅ | `listTestCases` rejects any inactive or foreign-role item. A stale version returns a typed `stale_test_case`. |
| Add, then retire (P3), with the order stated and a confirm step | ✅ | `:412` and `:435-455` |
| `\brun\b` stem kept; exactly two names exempted; length 5; the shield cases in both lanes (C38) | ✅ | `forbiddenActionNames.ts`; `test.tsx:344-359`. `Run isolated test` and `View run 12` are still forbidden. |
| Candidate body is `{test_case_id, lock_version}` and baseline body is `{test_case_id}` (C32) | ✅ | Pinned by M05 and M06 |
| Refusal mapping from the Task 5 carry: 201 `model_error` is evidence; the two 409 and two 422 codes; the exact 404 and 503 | ✅ | `testRunRefusal` and `testCaseRefusal`. Only the exact bodies are typed; a proxy body is a plain API error. |
| `agentDefinitions.ts` text-read rules | ✅ | The Python joins give 35 passed at my scope: the probe join, the endpoint-policy join, and the new join. The appended code has no probe status-guard line. |
| Own Python join for the new contract (C38) | ✅ ⚠️ | `tests/unit/test_test_run_failure_contract_client_join.py`, 7 tests. It is weak in places (see m-4). |
| Unrouted `/test-run` and `/test-case` tripwires; routing by URL (#266 c17) | ✅ | See the report's M21: 27 Vitest and 70 Playwright tests go RED when the case list loads on mount. |
| No live model call in Vitest | ✅ | Every harness throws on an unrouted test URL. |
| Plan signature deviation (two named execute clients) | ✅ accepted | Only the candidate client sends a lock, so one boolean-flag client would be the worse design. |

### Explicit objectives

**1. Criterion 2 in the UI.**
- P3 is about *replacing* one case with a different one: add the new case, then retire the old. The last-required guard makes that order matter.
- A supersede is a different operation: the same `name` (the P2 lineage key), version + 1, and the old row retired atomically under the L2 lock (C22). The last-required guard never bites a supersede, because it is atomic.
- P3 therefore does not cover content edits. The UI has no update control, so an admin cannot:
  - **version** a case: every UI case is v1 of a new lineage;
  - edit its payload or context;
  - toggle `is_required` on an existing case.
- An admin can only create, deactivate, and mark a case required at creation.
- The issue text says "Let administrators manage synthetic Agent Test Cases", and the workbench is the only admin surface. Criterion 2 is therefore met by the API (Task 2) but only partly in the product.
- **Graded Important (I-1)**, as a plan-scope gap. The Task 6 brief lists `listTestCases` and the run clients only, so the implementer followed the plan.

**2. Stored evidence.**
- Candidate and baseline evidence live only in reducer state. After a reload, or after running a different case of the same role, the panel shows "No run yet". `getTestRun` and `listTestCaseRuns` are parser-tested but never called.
- **AC7 still holds.**
  - After a reload the panel never says "Baseline not recorded". It says "No run yet", which is true for the session.
  - The first candidate run copies the stored baseline server-side (C20), so the panel shows it, labelled not approved.
  - A row that exists is never reported as absent.
- **AC6 holds.** The candidate run reads the stored baseline, and no rerun happens without the explicit button.
- **P1 is not fully met across sessions.** P1 says the published baseline is "shown as soon as it exists". A baseline rerun from an earlier session stays invisible until the admin spends another candidate model call.
- **AC9 is met only while the session lasts.** Prior failed or completed evidence, which is what "stored evidence" exists for, cannot be viewed.
- #268 (verdicts on stored runs) will need a history read in any case.
- **Graded Important (I-2).** It is not Critical, because no criterion is falsified: every render is truthful.

**3. One of each.**
- There is one reducer: ten new actions sit on `draftEditorReducer`.
- There is one counter: `nextRequestIdRef`, used by `loadTestCases` and `startTestOperation`.
- There is one gate: `operationBlocked()` plus the single `pendingSave` slot. `TestOperationKind` extends `DraftOperationKind`, and `testCaseId` is optional on the one slot.
- The rulings are confirmed in the code:
  - the candidate run, the baseline rerun, and case create and retire all go through `startTestOperation` and `operationBlocked()`;
  - the case-list read takes only a counter ID. `testCasesLoaded` and `testCasesLoadFailed` drop a mismatched ID, and a case write nulls `casesRequestId`, which invalidates a read already in flight (pinned by M19).
- **A late response cannot clobber state.** `matchingTestPending` requires a test-operation kind and the exact request ID, and `testRunSucceeded` checks the run kind again. The gate refuses a Save while a run is pending, so "a late run response after a newer save" can only arrive as an ID and kind mismatch. It is then a no-op. My sabotage 1 proves the ID check.
- **Coherence.** `runEvidenceIsCoherent` checks role, case and kind, and for a candidate also the lock and the saved `candidate_hash`.

**4. Name collisions.** Playwright matches a string name as a case-insensitive substring, so I compared every new accessible name that way.
- The new names checked:
  - buttons: `Run test case`, `Run published baseline`, `Load Agent Test Cases`, `Refresh test cases`, `Add test case`, `Retire test case`, `Confirm retire`, `Keep test case`, `Save test case`, `Cancel`;
  - tabs: `Input`, `Compare`, `Checks`;
  - regions: `Synthetic payload`, `Assembled prompt`, `Model payload sent`, `Test case evidence`, `Published baseline evidence`;
  - combobox `Agent Test Cases`, textboxes `Test case name` and `Synthetic payload (JSON)`, checkboxes `Required test case` and `Design system active`.
- They were checked against every string name the spec uses (`Save Draft`, `Keep local`, `Reload server`, tabs `Model` and `Prompt`, `Refresh models`, `Test structured output`, `Retry structured output test`, `Structured output test result`, `Discovered models`, and others) and against the `/retry/i` regex at `spec.ts:2373`.
- **No collision found.** `Retire` does not match `/retry/i`. `Save Draft` is not a substring of `Save test case`. None of the new names contains "structured output", "test result" or "Retry".
- **The exemptions are the exact strings**, but they are stripped as case-sensitive *substrings* (the pre-existing #260 mechanism). So `Run test cases` or `Run test case now` would pass the guard. See m-5.
- The tablist `Test run views` and the status text `Running…` contain "run", but neither is swept (buttons and links only), per C38.

**5. Rendering.**
- All server evidence reaches the DOM as React text children: `JSON.stringify` in `<pre>`, plus `error_detail`, `check.message`, issue codes and `run_by`.
- There is no `dangerouslySetInnerHTML` or `innerHTML` anywhere under `src/components/Admin` outside tests. `testOperationFailure` maps typed refusals to fixed client copy and never reads untyped server text.
- ✅. Pinned by M14.

### Acceptance criteria, whole branch
| # | Criterion | Verdict | Basis |
|---|---|---|---|
| 1 | Every editable role has at least one active required smoke case after bootstrap | ✅ | Task 1: first-boot guard tests plus PG seeding identity (reviewed and fixed) |
| 2 | Create, update, version, deactivate and mark required, keeping history | ⚠️ | API complete (Task 2 supersede, C22). UI offers only create, retire, and required at creation (I-1). |
| 3 | Inputs are only a synthetic payload plus declarative context; the UI warning is shown | ✅ | C22 validation (Task 2); warning shown unconditionally and beside the editor (Task 6) |
| 4 | Isolated run of the saved immutable candidate and hash through AgentRuntime, with no graph, deck or chat | ✅ | Tasks 3–5: `run_candidate` via `_run_resolved`, lock-read saved candidate, hash coherence (also checked client-side here) |
| 5 | Evidence records identities, raw and structured outputs, checks, errors, latency and tokens | ✅ | Task 0 DDL, Task 4 executor, Task 5 DTO. The Task 6 parser requires all 26 fields, and the join pins them to the server. |
| 6 | Baseline is stored evidence and reruns only on an explicit request | ✅ ⚠️ | C20 copy at insert; explicit button only. Stored runs are not readable in the UI (I-2). |
| 7 | Graph Version 1 says baseline not recorded until run; checks not waived | ✅ | C20. "Baseline not recorded" is shown only from a run whose copied baseline is NULL, so it holds after a reload too. Checks always render. |
| 8 | Failed calls persisted; invalid or incomplete runs cannot be approved | ✅ | 201 `model_error` is evidence (client test). `ck_agent_test_run_approved_only_if_completed_and_passing` (Task 0). No approve control (C11). |
| 9 | Input, Compare and Checks render prompts, field errors, diagnostics and candidate vs baseline | ✅ ⚠️ | All rendered for runs in this session. Field errors: `invalid_draft` binds to editor fields, `invalid_test_case` shows as an ordered list. Not rendered for prior sessions (I-2). |
| 10 | Deterministic fakes prove the candidate and published paths share assembly, schema, validation, model and tracing | ✅ | Tasks 3–4 (fake adapter per C26; `run_published_baseline` AST-equal to `run`). Task 6 does not touch it. |

I did not re-derive criteria 1, 4, 5, 8 and 10 beyond the ledger's reviewed task records. Those criteria are outside the Task 6 diff.

## Strengths
- **One of each, strictly.** No second counter, gate, conflict model or autosave was added. The `stale_draft` 409 reuses `mergeConflict` and the probe's Reload server and Keep local recovery.
- **The candidate-run refusal has two layers:**
  - the hook refuses with no request ID;
  - the reducer's `testOperationStarted` refuses as a backstop.
  - It is also stricter than the probe's endpoint-only rule, correctly: the run assembles the whole saved candidate.
- **Evidence coherence** checks the lock and the saved hash, like `settleProbe`, and skips the hash deliberately for a baseline rerun.
- **The strict exact-key parser** has no verdict fields (M07 pins that #268 must extend it), no `-1` sentinel (M08), and accepts currency flags that are boolean or null.
- **The case list stays lazy**, which keeps every "exactly one read on mount" backstop intact. M21 proves both tripwires fire.
- **The 25-row mutation table**, with 0 survivors, is unusually complete. It includes the gate-mask case the implementer found (M01, closed by a hook-level test).

## Issues

### Critical
None.

### Important
- **I-1: criterion 2 is only partly reachable in the product.**
  - The UI cannot supersede (version) a case, edit its content, or toggle `is_required`, and every UI-created case is v1 of a new lineage.
  - P3 covers replacing with a different case. It does not cover editing one: a same-name supersede is atomic, so the last-required guard never bites it.
  - The API supports all of it.
  - **Action:** route to the user. Either add an "Edit test case" control that PUTs a supersede (a same-name form, with a C38 name check against `Save Draft` and the other existing names), or record that criterion 2 is API-only for #267, with a follow-up.
- **I-2: stored evidence is session-local.**
  - After a reload, or after switching to another case of the same role, the panel shows "No run yet", even when stored candidate or baseline runs exist.
  - P1 ("shown as soon as it exists") is therefore unmet across sessions, and a prior baseline rerun costs another model call to see again.
  - AC7 is not falsified: "Baseline not recorded" is only ever derived from a run's copied baseline.
  - **Action:** on case selection, read `listTestCaseRuns(caseId)` once as an ungated counted read, like the case list. Show the newest candidate run and the newest completed `published_baseline` run. The clients already exist.
  - This also serves #268, which puts verdicts on stored runs.

### Minor
- **m-1: no reducer test for a late run response after a newer Save**, unlike the probe's `a late probe response after a newer save has started never clobbers state` (`draftEditorState.test.ts:2425`). The generic ID-mismatch test catches my sabotage, but the kind-mismatch layer (a pending Save) is not pinned for test operations.
- **m-2: `createAgentTestCase` returns the created case even when the reducer contained it as invalid** (wrong role, or `is_active=false`). The form then closes and selects an ID that is not in the list. The fallback to `cases[0]` hides this, but the form should stay open. Make the hook return `null` when the response is incoherent.
- **m-3: Checks shows only candidate evidence.** A published-baseline rerun's own checks are never rendered, and after a baseline-only run Checks says "No run yet".
- **m-4: parts of the Python join are weak.**
  - `test_the_client_refusal_codes_are_the_servers` only checks `'<code>'` anywhere in the source.
  - The nested shapes are not joined: `assembly_context` keys, the `DeterministicCheckIssue` keys `{code, field}`, and the `DeterministicCheckResult` keys.
- **m-5: guard exemptions are substring-stripped.** `Run test cases` or `Run test case now` would pass. This is the pre-existing #260 mechanism and C38 accepted it; consider whole-name matching when #269 next edits the file.
- **m-6: the Playwright lane does not pin the unsaved-edit refusal on its own.** My sabotage 2 was caught in Playwright only indirectly, through the stale_draft recovery test's `toBeDisabled`. Vitest pins it directly (2 tests).

## Sabotage evidence
The pin was `e1e85ff60e8b23471d3fa8e3c9f91f516e4517b2` throughout. Each triple check (`git rev-parse HEAD`, `git status --porcelain`, and the marker `grep -c`) was run before and after every mutation. Before each mutation the tree was clean and the baseline was 5 files / 472 passed.

Scope: `(cd frontend && npx vitest run src/components/Admin/AgentDefinitionWorkbench/)`, the whole directory with no `-k`.

**S1: a late candidate-run response overwrites the panel.**
- **File:** `draftEditorState.ts`, case `testRunSucceeded`.
- **Anchor** (count 1): `if (pending === null || (pending.operation !== 'testRun' && pending.operation !== 'baselineRun')) return state;`
- **Mutation:** the unmatched branch returned `withTesting(state, action.evidence.agent_key, t => ({...t, candidateEvidence: action.evidence}))`. That is, any late or unmatched response is stored.
- **Marker:** `REV267_6_LATE`, count 1. HEAD unchanged; only that file modified.
- **RED: 1 failed / 471 passed (472).** `Agent Test Case and test run reducer > only the pending test operation's own request ID may settle it`.
- **Restore:** `git checkout $PIN -- <file>`. Marker 0, status clean.

**S2: the run button is enabled while the role is unsaved, and the hook's refusal is removed.**
- **Files:** `TestRunPanel.tsx`, anchor `disabled={operationsDisabled || candidateUnsaved}` (count 1), and `useDraftEditor.ts`, anchor `    if (testRunCandidateUnsaved(state.byAgent[agentKey])) return;` (count 1). The reducer backstop was left in place.
- **Markers:** `REV267_6_UNSAVED_BTN` = 1 and `REV267_6_UNSAVED_HOOK` = 1. HEAD unchanged; only those two files modified.
- **Vitest RED: 3 failed / 469 passed (472).**
  - `AgentDefinitionWorkbench isolated testing > an unsaved role refuses the candidate run without a request, and the hook allocates nothing`
  - `AgentDefinitionWorkbench isolated testing > a stale_draft 409 adopts the server draft; Reload server, then an explicit run, sends the adopted lock`
  - `TestRunPanel > refuses a candidate run while the role has unsaved edits and explains why`
- **Playwright RED:** the whole `tests/e2e/agent-definition-workbench.spec.ts`, `--project=chromium --workers=1`. Port 3000 was free before and after. **1 failed / 73 passed.** The failing test was `Agent Test Cases: a stale_draft 409 reconciles through Reload server, and the explicit rerun sends the adopted lock` (`toBeDisabled` failed).
- **Restore:** `git checkout $PIN --` both files. Markers 0, status clean.
- **GREEN after restore:** 5 files / 472 passed.

Both mutations executed: each marker sat on the executed path and turned tests RED.

**Other runs:** the Python joins, `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr DATABASE_URL=sqlite:////tmp/rev-267-6.sqlite`, over the new join plus the probe join plus the endpoint-policy join: 35 passed.

## Task quality
- The code is small for its scope and follows the existing patterns: parser guards, fixed-copy failure mapping, and one pending slot.
- The one-of-each invariants hold, and they are proven by 25 mutations of the implementer's plus the controller's 1 and my 2.
- The two Important findings are scope gaps inherited from the plan's Task 6 brief. Neither is an implementation defect, and both need a user or controller decision: an update UI, and a history read.
- The Minors can be deferred.
- **Verdict:** Approved with follow-ups. Rule on I-1 and I-2 before #267 is treated as meeting criteria 2, 6 and 9 in the product.
