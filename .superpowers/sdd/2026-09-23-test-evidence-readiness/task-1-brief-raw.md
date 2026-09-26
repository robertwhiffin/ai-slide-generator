### Task 1: Verdict Write Service

**Review question:** Does `record_verdict` write exactly the four verdict fields, enforce the application-level eligibility checks before reaching the database constraint, raise `IneligibleForApprovalError` with the exact code and message for each ineligible case, and record the authenticated reviewer identity rather than accepting it from the request body?

**Files:**
- Modify: `src/services/agent_test_workbench.py` (add `record_verdict`, `IneligibleForApprovalError`, `VerdictChoice`)
- Modify: `tests/unit/test_agent_test_workbench.py`
- Modify: `tests/integration/test_agent_definition_workbench_postgres.py`

**Interfaces:**
- Consumes: `AgentTestRun` ORM columns `execution_status`, `deterministic_checks_passed`, `verdict`, `verdict_reviewer`, `verdict_at`, `verdict_notes`; the check constraint `ck_agent_test_run_approved_only_if_completed_and_passing`.
- Produces: `IneligibleForApprovalError`; `VerdictChoice`; `AgentTestWorkbench.record_verdict`.

- [ ] **Step 1: Write RED unit tests**

Test with a mocked session:
- `record_verdict(run_id=1, verdict='approved', ...)` on a run with `execution_status='model_error'` raises `IneligibleForApprovalError(code='not_completed')`.
- Same on a run with `execution_status='completed'` but `deterministic_checks_passed=False` raises `IneligibleForApprovalError(code='checks_failed')`.
- `record_verdict(run_id=999, ...)` on a missing run raises `IneligibleForApprovalError(code='not_found')`.
- A valid approval on a `completed` + `checks_passed` run returns `TestRunEvidence` with `verdict='approved'` and `verdict_reviewer` equal to the `reviewer` argument.
- `record_verdict` with `verdict='rejected'` on a completed run (regardless of checks) returns `TestRunEvidence` with `verdict='rejected'`.
- `reviewer` from the argument appears in the returned evidence; the request-body `actor` is recorded in the audit log, but `reviewer` is the authenticated principal passed by the route.

Run and confirm RED.

- [ ] **Step 2: Implement `record_verdict`**

Acquire a `SELECT ... FOR UPDATE` row lock on the `agent_test_run` row. Apply eligibility checks in this order: existence (`not_found`), completion (`not_completed`), checks-passed (for approval only; `checks_failed`). Update the four verdict fields within the transaction. Return the updated `TestRunEvidence`.

The update is the ONLY allowed mutation to an `agent_test_run` row. Enforce this by only touching the four verdict columns; assert no other column is included in the `UPDATE` statement.

- [ ] **Step 3: Write PostgreSQL integration tests**

Insert a completed, checks-passing `agent_test_run` row. Call `record_verdict` with `verdict='approved'`. Assert the row's `verdict`, `verdict_reviewer`, and `verdict_at` are set and `verdict_notes` matches the argument. Assert the `ck_agent_test_run_approved_only_if_completed_and_passing` constraint independently by attempting a direct SQL `UPDATE` that sets `verdict='approved'` on a row with `deterministic_checks_passed=False`; confirm IntegrityError.

- [ ] **Step 4: Run GREEN**

```bash
python -m pytest -q \
  tests/unit/test_agent_test_workbench.py \
  tests/integration/test_agent_definition_workbench_postgres.py
```

Sabotage: remove the `execution_status != 'completed'` check in `record_verdict`, confirm RED on the `not_completed` test, restore, confirm GREEN.

Commit: `feat: verdict write service with eligibility enforcement (#268)`

---

