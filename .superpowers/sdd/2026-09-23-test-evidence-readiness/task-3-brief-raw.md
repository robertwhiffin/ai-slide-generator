### Task 3: Verdict and Readiness Routes

**Review question:** Does the verdict route enforce admin authorization before body parsing, reject ineligible approvals with a `422` carrying the exact reason code, and extend `TestRunEvidenceResponse` to include verdict fields — and does the readiness route return a response that precisely identifies every blocking role and case?

**Files:**
- Modify: `src/api/routes/agent_definitions.py` (add verdict POST, readiness GET)
- Modify: `src/api/schemas/agent_definitions.py` (extend `TestRunEvidenceResponse`; add verdict request/response, readiness response)
- Modify: `tests/unit/test_agent_definition_workbench_routes.py`

**Interfaces:**
- Consumes: `AgentTestWorkbench.record_verdict`, `AgentTestWorkbench.draft_readiness`, `require_admin`, `require_draft_write_principal` (for reviewer identity), `get_db`.
- Produces: `POST /api/admin/agent-test-runs/{run_id}/verdict`, `GET /api/admin/graph-draft/readiness`, `VerdictRequest`, `VerdictResponse`, `DraftReadinessResponse`.

- [ ] **Step 1: Write RED route tests**

Non-admin on verdict route: `403`. Valid approval on eligible run: `200` with `verdict_reviewer` matching authenticated admin, not body content. Ineligible approval (`checks_failed`): `422` with `{"code": "ineligible_for_approval", "reason": "checks_failed"}`. Readiness for a draft with one blocking case: `200` with `all_ready: false` and `blocking_agents` listing that role.

Run and confirm RED.

- [ ] **Step 2: Extend `TestRunEvidenceResponse` and add request/response schemas**

`TestRunEvidenceResponse` gains four optional fields: `verdict: str | None`, `verdict_reviewer: str | None`, `verdict_at: datetime | None`, `verdict_notes: str | None`. Existing #267 consumers receive `null` for these until a verdict is recorded; the schema change is backward-compatible.

`VerdictRequest`: `{"verdict": "approved" | "rejected", "notes": str | null}`.

`DraftReadinessResponse`: mirrors `DraftReadinessResult` with camelCase aliases where the frontend expects them. `status` in `TestCaseReadinessItemResponse` maps `needs_test → 'Needs test'`, `test_failed → 'Test failed'`, `awaiting_review → 'Awaiting review'`, `approved → 'Approved'`.

- [ ] **Step 3: Implement routes**

`POST /api/admin/agent-test-runs/{run_id}/verdict`: authenticate admin → extract reviewer from principal → call `record_verdict` → return extended `TestRunEvidenceResponse`. `GET /api/admin/graph-draft/readiness`: authenticate admin → call `draft_readiness` → return `DraftReadinessResponse`.

- [ ] **Step 4: Run GREEN**

```bash
python -m pytest -q tests/unit/test_agent_definition_workbench_routes.py
```

Sabotage: allow the verdict route to accept `reviewer` from the request body instead of the authenticated principal; confirm a test asserting `verdict_reviewer == authenticated_admin_identity` goes RED; restore; confirm GREEN.

Commit: `feat: verdict and readiness routes (#268)`

---

