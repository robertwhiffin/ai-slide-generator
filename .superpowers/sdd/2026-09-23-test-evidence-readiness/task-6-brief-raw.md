### Task 6: Frontend Status States and Readiness Overlay

**Review question:** Do the workbench status badges correctly render `Test failed`, `Awaiting review`, and `Approved` derived from the readiness endpoint — do the Approve/Reject controls call the verdict route and re-fetch evidence — and does the Review & Publish page show per-case blocking detail before allowing publication?

**Files:**
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/TestRunPanel.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx`
- Modify: `frontend/src/api/agentDefinitions.ts` (add verdict client, readiness client)
- Create: `frontend/tests/agent-definition-workbench/verdict-readiness.test.tsx` (or extend existing)
- Modify: `frontend/tests/e2e/agent-definition-workbench.spec.ts`

**Interfaces:**
- Consumes: `DraftStatus` (extended to six values), `DraftReadinessResponse`, `VerdictRequest`, `VerdictResponse`, readiness API client, verdict API client.
- Produces: six-value `DraftStatus`; `draftStatus` with readiness-derived logic; Approve/Reject controls; readiness overlay in Review & Publish header.

- [ ] **Step 1: Write RED unit tests for status logic**

Test `draftStatus` for all six states with mocked readiness data:
- No run → `Needs test`.
- Run exists, `verdict=null`, checks passed → `Awaiting review`.
- Run exists, `verdict=null`, checks failed → `Test failed`.
- `verdict='rejected'` → `Test failed`.
- `verdict='approved'` on current hash/version → `Approved`.
- Hash changed after approval → `Needs test`.

Run and confirm RED.

- [ ] **Step 2: Extend `draftEditorState.ts` and `draftStatus`**

Add the three new status values. Update `draftStatus` to accept a `TestCaseReadinessItemResponse | null` alongside the `DraftEditorEntry`. The `draftStatus` function derives status from readiness data, not from locally cached run data. Locally cached run data may be stale; only the readiness endpoint is authoritative for status.

- [ ] **Step 3: Add Approve/Reject controls to `TestRunPanel`**

When `evidence` is present and `evidence.verdict == null` and `evidence.execution_status == 'completed'`:
- Show `Approve` button and `Reject` button.
- `Approve` is disabled if `evidence.deterministic_checks_passed == false` (with tooltip "Deterministic checks did not pass").
- Both buttons open a notes textarea before submitting.
- After submission, re-fetch the run evidence and the readiness response.

When `evidence.verdict == 'approved'`: show a green badge; offer `Reject` to reverse.
When `evidence.verdict == 'rejected'`: show a red badge; offer `Approve` if eligible.

- [ ] **Step 4: Add readiness overlay to Review & Publish header**

In the existing Review & Publish page, add a readiness panel that:
- Lists every blocking role and case with status `Needs test`, `Test failed`, or `Awaiting review`.
- When `all_ready: false`, disables the Publish button with the message "N role(s) have unresolved required test cases."
- When `all_ready: true`, shows "All required test cases approved" and enables Publish.
- Refreshes when the admin navigates to the page.

- [ ] **Step 5: Run GREEN**

```bash
(cd frontend && npm run test:unit)
(cd frontend && npm run typecheck)
```

Run E2E smoke: confirm the Approve button triggers the verdict route mock, the status badge changes to `Approved`, and the Review & Publish page shows `all_ready: true` after all blocking cases resolve.

Commit: `feat: status badges, Approve/Reject controls, and readiness overlay (#268)`
