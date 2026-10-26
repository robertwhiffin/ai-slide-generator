### Task 4: Retention Cleanup

**Review question:** Does `cleanup_unpublished_test_runs` delete at most `n - per_case_limit` rows per case while unconditionally retaining (a) any run linked in `graph_release_test_run` and (b) any approved run still eligible for the current draft — and does it use SQL `NOT EXISTS` subqueries rather than Python filtering for both exclusions?

**Files:**
- Create or modify: `src/services/agent_test_workbench.py` (add `cleanup_unpublished_test_runs`)
- Modify: `tests/integration/test_agent_definition_workbench_postgres.py`

**Interfaces:**
- Consumes: `AgentTestRun`, `GraphReleaseTestRun`, `GraphDraftAgent` (for current candidate hash), `AgentTestCase` (for current active version).
- Produces: `AgentTestWorkbench.cleanup_unpublished_test_runs(session, *, per_case_limit=20) -> int`.

- [ ] **Step 1: Write RED PostgreSQL integration tests**

The tests must be concrete, not count-based:
- Insert 25 runs for one test case, all unpublished and non-eligible for the current draft. Assert cleanup deletes exactly 5 (the oldest by `run_at`). Assert the exact run IDs of the 20 retained rows.
- Insert 25 runs; the oldest run is linked in `graph_release_test_run`. Assert cleanup deletes 4, not 5 — the linked run is always retained. Assert its ID is in the retained set.
- Insert 25 runs; one run outside the latest 20 is an approved eligible approval (matching current draft hash and current case version). Assert cleanup deletes 4, not 5. Assert its ID is in the retained set.
- Both protections simultaneously: one linked run AND one eligible approval outside the latest 20. Assert cleanup deletes 3.
- Second cleanup call on the same data is idempotent: returns 0.

Run and confirm RED.

- [ ] **Step 2: Implement `cleanup_unpublished_test_runs`**

The SQL must express:

```sql
DELETE FROM agent_test_run
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (PARTITION BY test_case_id ORDER BY run_at DESC) AS rn
        FROM agent_test_run
        WHERE NOT EXISTS (
            SELECT 1 FROM graph_release_test_run grtr
            WHERE grtr.agent_test_run_id = agent_test_run.id
        )
        AND NOT EXISTS (
            SELECT 1 FROM graph_draft_agent gda
            JOIN agent_test_case atc ON atc.id = agent_test_run.test_case_id
                AND atc.is_active = TRUE
            WHERE gda.agent_key = agent_test_run.agent_key
              AND gda.candidate_hash = agent_test_run.candidate_hash
              AND atc.version = agent_test_run.test_case_version
              AND agent_test_run.verdict = 'approved'
        )
    ) ranked
    WHERE rn > :per_case_limit
)
```

The function acquires a shared lock on the singleton draft before executing this statement so that a concurrent save (which changes `candidate_hash`) cannot make an eligible run ineligible between the lock and the delete.

- [ ] **Step 3: Run GREEN**

```bash
python -m pytest -q -m postgres tests/integration/test_agent_definition_workbench_postgres.py
```

Sabotage: remove the second `NOT EXISTS` clause (the eligible-approval exclusion), confirm RED on the test asserting the eligible approved run is retained; restore; confirm GREEN.

Commit: `feat: bounded cleanup with release-link and eligible-approval exclusions (#268)`

---

