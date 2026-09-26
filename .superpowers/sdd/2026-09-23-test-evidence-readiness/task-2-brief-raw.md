### Task 2: Readiness Query Service

**Review question:** Does `draft_readiness` return per-role, per-case blocking detail that correctly identifies the current candidate hash, current active case version, and the most recent approved run for that pair — and does it hold a shared draft lock during the query to prevent a concurrent hash change?

**Files:**
- Modify: `src/services/agent_test_workbench.py` (add `draft_readiness`, `DraftReadinessResult`, `AgentReadinessItem`, `TestCaseReadinessItem`)
- Modify: `tests/unit/test_agent_test_workbench.py`
- Modify: `tests/integration/test_agent_definition_workbench_postgres.py`

**Interfaces:**
- Consumes: `GraphDraftAgent.candidate_hash` (current draft state, shared-locked), `AgentTestCase.version` (current active version), `GraphReleaseAgent` (base revision hashes for change detection), `AgentTestRun` (verdict, hash, version, checks).
- Produces: `DraftReadinessResult`, `AgentReadinessItem`, `TestCaseReadinessItem`, `AgentTestWorkbench.draft_readiness`.

- [ ] **Step 1: Write RED unit tests for readiness logic**

Test with in-memory state:
- A role with no runs returns status `needs_test` and `blocking=True` for its required case.
- A role with a completed+passing run but `verdict=None` returns `awaiting_review` and `blocking=True`.
- A role with `verdict='rejected'` returns `test_failed` and `blocking=True`.
- A role with `verdict='approved'` on the current hash and current case version returns `approved` and `blocking=False`.
- A role with `verdict='approved'` on a STALE hash (different from current draft candidate) returns `needs_test` and `blocking=True` (the approval is inapplicable).
- `DraftReadinessResult.all_ready` is `False` when any changed role is blocking.
- An unchanged role (candidate hash equals base revision hash) is reported with `is_changed_from_base=False` and its cases are listed but it does not block publication.

Run and confirm RED.

- [ ] **Step 2: Implement `draft_readiness`**

The query must:
1. Acquire a shared lock on `GraphDraft` and `GraphRelease` (the same shared-lock pattern used by `read_workbench`).
2. Load all seven `GraphDraftAgent` rows and the base-release `GraphReleaseAgent` rows.
3. For each role, load all active+required `AgentTestCase` rows.
4. For each `(agent_key, test_case_id)` pair, find the most recent `agent_test_run` with `candidate_hash == current_candidate_hash` and `test_case_version == current_case_version`. Apply status mapping.
5. Compute blocking and readiness. Build and return `DraftReadinessResult`.

The query for step 4 must be a single SQL statement with `ORDER BY run_at DESC LIMIT 1` for efficiency; do not load all runs and filter in Python.

- [ ] **Step 3: Write PostgreSQL integration tests with stale-hash and cleanup interactions**

Test: insert two approved runs for the same `(test_case_id, candidate_hash_A)` pair, then save a new draft (changing the hash to `candidate_hash_B`). Assert `draft_readiness` returns `needs_test` for that case. Test: insert an approved run for `candidate_hash_B` and assert `draft_readiness` returns `approved`. Test: run more than 20 runs for one case, assert `draft_readiness` still sees the approved eligible run (cleanup-safety proof).

- [ ] **Step 4: Run GREEN**

```bash
python -m pytest -q \
  tests/unit/test_agent_test_workbench.py \
  tests/integration/test_agent_definition_workbench_postgres.py
```

Sabotage: remove the stale-hash check so an `approved` verdict on any hash satisfies readiness; confirm RED on the stale-hash test; restore; confirm GREEN.

Commit: `feat: draft readiness query per role and case (#268)`

---

