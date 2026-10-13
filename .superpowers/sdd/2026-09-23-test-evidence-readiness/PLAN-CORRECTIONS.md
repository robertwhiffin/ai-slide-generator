# PLAN-CORRECTIONS.md — this file overrides /Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/docs/superpowers/plans/2026-09-23-test-evidence-readiness.md wherever they differ.

- **Plan:** the user's untracked draft, 725 lines, read in the main worktree. It was not modified, moved or copied.
- **Earlier pass carried forward:** `docs/superpowers/plans/2026-09-23-agent-test-case-runs-CORRECTIONS.md` (main worktree, against `d72ad974d`). Its only #268 item is ADVISORY-4 (no publication method exists). It is re-verified at `b0c4d8aeb` and superseded by Correction 1 (scope): #268 does not need a publication method, because #269 owns it.
- **Code base:** `b0c4d8aeb` ("docs: record #267 whole-branch review and rulings"), branch `feat/test-evidence-readiness-268`, worktree `.worktrees/issue-268-plan`. That commit is #267's reviewed head, 57 commits above `e91fcd856` (Merge #266). `git status` was clean apart from this directory.
- **Not yet integrated:** #267 is finishing its token-usage fix wave (whole-branch I-1) in `.worktrees/issue-267-plan`. After it merges into `feat/langgraph-core`, this branch rebases onto that merge. Correction 3 lists what must be re-probed then.
- **Binding inputs:**
  - #269 ledger ruling Q1 and #269 `PLAN-CORRECTIONS.md` Corrections 1–30 (`.worktrees/issue-269-plan/.superpowers/sdd/2026-09-25-graph-release-publication/`).
  - #267 `PLAN-CORRECTIONS.md`, `progress.md` and `whole-branch-review.md` (`.worktrees/issue-267-plan/.superpowers/sdd/2026-09-23-agent-test-case-runs/`).
  - GitHub issue #268's acceptance criteria (read-only, `gh issue view 268`).
  - Every fact below was re-read from the code at `b0c4d8aeb`.
- **Blocking:** each correction is marked **BLOCKING (task)** or **Advisory**. A blocking correction goes into the brief of the task it names. Implementers are told the defect; they are not left to find it.
- **Task numbering:** the plan's Tasks 1–4 keep their numbers. The plan's Task 5 is **deleted** (Correction 1). The plan's Task 6 keeps its number but loses its Step 4 (Correction 1).

---

## 1. Scope and ownership

### Correction 1 — #268 owns verdicts, readiness and cleanup; #269 owns publication, evidence linking and the Review & Publish page — BLOCKING (all tasks)

- **Plan claims that are overridden:**
  - Goal (:5) "link approved run evidence to the publication record";
  - Architecture (:7) "Publication, owned by `GraphConfiguration`, is extended with a step that locks and links approved runs";
  - Global Constraint "Publication step" (:23);
  - the dependency-ledger rows for Task 5 (:56) and the Task 4→5 and 5→6 rows;
  - "Publication transaction extension" (:240-256);
  - the shared-file rows for `graph_configuration_bootstrap.py` and `graph_release_test_run` inserts (:285, :287);
  - all of Task 5 (:596-661);
  - Task 6's review question clause about the Review & Publish page, and Task 6 Step 4 (:708-714);
  - the "Review & Publish page shows `all_ready: true`" clause of Task 6 Step 5 (:723).
- **Evidence:**
  - #269 ledger ruling Q1: #269 owns the publication transaction, evidence links and the Review & Publish page.
  - #267 Correction 11 records the same split.
  - There is no publication method at `b0c4d8aeb`: `grep -rn "def publish" src/services/graph_configuration*.py` gives no output.
  - There is no Review & Publish page: `grep -rn "Review & Publish" frontend/src` gives no output. `forbiddenActionNames.ts:17-18` still forbids the stem.
  - `GraphReleaseTestRun` is defined (`models/graph_configuration.py:493-537`), but no `src/` code writes it.
- **Ruling:**
  - Delete Task 5.
  - Delete Task 6 Step 4 and the Review & Publish clauses.
  - #268 writes **no** `publish_draft`, no publication step, no `graph_release_test_run` INSERT, no Review & Publish page, link or allowed action name, and no Publish button.
  - The plan's concurrency test "cleanup cannot delete an approved run that publication just locked" (:615) moves to #269 Task 4, which already owns cleanup-versus-publication ordering.
  - Instead, #268 hands #269:
    - the locked readiness callable (Correction 10);
    - the readiness wire model and its TypeScript parser (Corrections 17 and 22);
    - the cleanup lock boundary (Correction 18);
    - the verdict writer's lock shape (Correction 6).
  - #269 Correction 10 makes finding any #268 publication code a **stop** at #269's Task 0-B.
- **Cost if wrong:** two tickets build halves of one transaction, and #269's Task 0-B stops.

### Correction 2 — the corrections file, the ledger and `IMPLEMENTATION_BASE` live in this directory — Advisory

- **Overrides:** plan :3 and :313-320, which create `.superpowers/issue-268-plan-corrections.md` and `.superpowers/issue-268/IMPLEMENTATION_BASE`.
- **Ruling:**
  - This file and `progress.md` are in `.superpowers/sdd/2026-09-23-test-evidence-readiness/`.
  - Record `IMPLEMENTATION_BASE` in `progress.md` after the rebase onto the #267 merge (Correction 3). Do not create a separate file.
  - Attach this file to every implementer and reviewer brief.
- **Cost if wrong:** briefs point at a file that does not exist.

### Correction 3 — the pre-pass facts, re-probed at `b0c4d8aeb`; the plan's own probe is partly obsolete — BLOCKING (Task 1 dispatch)

- **Overrides:** the perishable-facts table (:33-43) and the probe (:315-355).
- **Confirmed at `b0c4d8aeb`:**
  - **Tables:** `AgentTestRun.__tablename__ == "agent_test_run"` and `GraphReleaseTestRun.__tablename__ == "graph_release_test_run"`, both exported from `src/database/models/__init__.py`.
  - **Verdict columns:** `verdict String(16)`, `verdict_reviewer Text`, `verdict_at DateTime(tz)` and `verdict_notes Text`, all nullable and all NULL on insert (`models/graph_configuration.py:423-426`). #267 writes none of them. This is pinned by `test_agent_test_workbench.py:1128` `test_a_completed_run_persists_one_row_with_null_verdict_columns`.
  - **Checks:**
    - `ck_agent_test_run_verdict_enum` (`verdict IS NULL OR IN ('approved','rejected')`);
    - `ck_agent_test_run_verdict_reviewer_paired` and `ck_agent_test_run_verdict_at_paired` (`(verdict IS NULL) = (x IS NULL)`);
    - `ck_agent_test_run_approved_only_if_completed_and_passing` (`verdict != 'approved' OR (execution_status = 'completed' AND deterministic_checks_passed)`);
    - there is **no** pairing check on `verdict_notes`.
  - **`run_kind`:** `ck_agent_test_run_run_kind` allows `candidate` and `published_baseline`.
  - **C24 trigger:** `trg_agent_test_run_evidence_immutable` (`src/core/database.py:1075-1108`) is `BEFORE UPDATE FOR EACH ROW`. It compares `to_jsonb(NEW)` and `to_jsonb(OLD)` minus the four verdict columns and raises `23514` **with no constraint name**. DELETE is allowed.
  - **Index:** `ix_graph_release_test_run_run (agent_test_run_id)` exists for the cleanup `NOT EXISTS`, and `ix_agent_test_run_case_run_at (test_case_id, run_at)` exists.
  - **Workbench:** `AgentTestWorkbench` (`src/services/agent_test_workbench.py:655`) has these methods:
    - `list_test_cases`, `create_test_case`, `update_test_case`, `deactivate_test_case`;
    - `execute_candidate_run`, `execute_baseline_rerun`, `get_test_run`, `list_test_runs`.

    It has no `record_verdict`, `draft_readiness` or `cleanup_*`.
  - **Workbench construction:** `AgentTestWorkbench(*, runtime=None, graph_configuration=None)` resolves the runtime lazily (`:658-669`), so readiness needs no `AgentRuntime`. This answers #269 Q4's second half.
  - **Transactions:** every workbench method owns its transaction (`with session.begin()`).
  - **Parent lock:** `_lock_current_parents(session, *, exclusive)` is on `_GraphConfigurationWorkbench` (`graph_configuration_workbench.py:188-238`), which the workbench reaches through `self._graph_configuration`. With `exclusive=False` it takes `FOR SHARE OF graph_release, graph_draft` in one statement.
  - **Changed role:** `changed = draft_row.candidate_hash != revision.content_hash` (`graph_configuration_workbench.py:325`).
  - **Errors:** `TestRunNotFound` exists (`:476`). Its route mapping is `_test_run_not_found()` → 404 `{"detail":"Test run not found"}`.
  - **Router and response:** the router is `APIRouter(prefix="/api/admin/agent-definitions", dependencies=[Depends(require_admin)])` (`routes/agent_definitions.py:97-101`). `TestRunEvidenceResponse` is `extra="forbid"` with 26 keys and no verdict keys (`schemas/agent_definitions.py:626-664`).
  - **Frontend:**
    - `TEST_RUN_KEYS` has the same 26 names, and `parseTestRunEvidence` rejects any extra key (`frontend/src/api/agentDefinitions.ts:1296-1303`, `:1364-1365`).
    - `DraftStatus = 'Clean' | 'Unsaved' | 'Needs test'` (`draftEditorState.ts:32`), and `draftStatus(entry)` is at `:646`.
    - `TestOperationKind` has five members and forms the one gate (`draftEditorState.ts:218-222`).
    - `TestRunPanel.tsx` labels baselines "(not approved)" (`:129`, `:608`).
  - **Fake adapter:** `tests/fixtures/deterministic_model_adapter.py`.
- **Obsolete probe lines:**
  - :342-349 grep `graph_configuration_bootstrap.py` for a publication method and for `GraphReleaseTestRun`. Replace them with the Correction 1 probe: `grep -rn "GraphReleaseTestRun(" src/` and `grep -rn "def publish" src/services/` must stay empty on this branch.
  - :352 (`command -v python` equals the shim) is environment-specific. Use the explicit interpreter path instead.
- **Re-probe after the #267 merge (blocking for Task 1):**
  - `range-diff` clean;
  - the `TestRunEvidence` / `TestRunEvidenceResponse` / `TEST_RUN_KEYS` field sets. The token-usage wave may change how `input_tokens`/`output_tokens` are filled, and any new key changes Correction 16's list.
  - `_evidence_from_row`;
  - `_persist_run`;
  - the C24 trigger column array;
  - `_lock_current_parents`;
  - the six baseline failure causes.
- **Cost if wrong:** a brief built on a field set that the token-usage wave changed.

---

## 2. Task 1 — verdict writer

### Correction 4 — the signature has one principal, and the method owns its transaction — BLOCKING (Task 1)

- **Overrides:** plan :79-101 and :394, which take both `reviewer` and `actor`, and :404, which says the "request-body `actor` is recorded in the audit log".
- **Evidence:**
  - No audit-log table exists. The audit trail is carried by columns: `agent_test_case.created_by`/`updated_by`, `agent_test_run.run_by`, `verdict_reviewer`, `graph_draft.updated_by`, and #269's `graph_release.published_by`.
  - The request body has no actor: the verdict body is `{verdict, notes}` (plan :167-172).
- **Ruling:**
  - The signature is `record_verdict(self, session, *, run_id: int, verdict: VerdictChoice, reviewer: str, notes: str | None) -> TestRunEvidence`.
  - `reviewer` is the authenticated principal. The route passes `require_draft_write_principal`.
  - It calls `self._require_no_transaction(session)` and then does `with session.begin():`, like every other workbench method.
  - Validation happens **before** the transaction:
    - `reviewer` uses the existing `_actor_issues` rule (non-blank string);
    - `verdict` must be exactly the `str` `'approved'` or `'rejected'`;
    - `notes` must be `None`, or a `str` that is non-blank after `strip()` and at most 2000 code points. The 2000 matches #269 Q6's release-note cap. Store the notes verbatim; to omit notes, send `null`.
  - An invalid argument raises `VerdictRejected(*issues)`, a new sibling of `TestCaseRejected` that uses the same `TestCaseIssue` shape, in the order `verdict`, `notes`.
  - AC2 ("the audit trail records each action") is met by those columns. No new table is created.
- **Cost if wrong:** the implementer invents an audit sink, or accepts two identities for one action.

### Correction 5 — refusal codes: not-found is the existing 404, and `not_completed` covers both verdicts — BLOCKING (Task 1)

- **Overrides:**
  - :71-74 (`IneligibleForApprovalError` with bare `code: str` / `message: str` annotations and no `__init__`, so `.code` raises `AttributeError`);
  - :95 (`code='not_found'`);
  - :403 ("rejected on a completed run (regardless of checks)").
- **Evidence:**
  - The issue's AC1 says "approve or reject a **completed** Agent Test Run".
  - `TestRunNotFound` already exists, and `get_test_run` raises it. The route maps it to 404.
- **Ruling:**
  - Define it with the house naming convention:

    ```python
    class IneligibleForApprovalError(ValueError):  # noqa: N818 - stable public domain name
        def __init__(self, run_id: int, reason: Literal["not_completed", "checks_failed"]) -> None:
            super().__init__(f"agent test run {run_id} is ineligible: {reason}")
            self.run_id = run_id
            self.reason = reason
    ```

  - The order inside the locked transaction:
    1. A missing row raises `TestRunNotFound(run_id)`.
    2. `execution_status != 'completed'` raises `reason='not_completed'`, for **either** verdict.
    3. `verdict == 'approved' and not deterministic_checks_passed` raises `reason='checks_failed'`.
  - A rejection of a completed run with failing checks is allowed.
- **Cost if wrong:** a `model_error` run gets a "rejected" verdict that AC1 does not allow, or the not-found path returns the wrong status.

### Correction 6 — lock and write shape: L3 only, four columns, database clock, identical re-submit is a no-op — BLOCKING (Task 1; answers #269 Q9 for the verdict writer)

- **Overrides:** plan :97-99 and :410-412.
- **Ruling:**
  - **Lock:**
    - The first statement is `select(AgentTestRun).where(AgentTestRun.id == run_id).with_for_update().execution_options(populate_existing=True)`. This is L3 only.
    - **No** L0 parent lock and **no** case lock. It is a subsequence of #269's order L0 → L1 → L2 → L3, so #269's deadlock argument (#269 plan :212) holds unchanged.
    - #269's gate locks the same run rows `FOR UPDATE`, so a verdict flip either commits first or waits.
  - **Write:**
    - Assign exactly the four ORM attributes. `verdict_at = func.now()` is evaluated by the database.
    - `database_transaction_timestamp` does **not** exist at `b0c4d8aeb`; #269 adds it. Do not import it.
    - Then `flush()`, `refresh(row)`, and return `_evidence_from_row(...)` with the synthetic payload read the way `get_test_run` reads it.
  - **Identical re-submit:** the same `(verdict, reviewer, notes)` as stored means no UPDATE, `verdict_at` unchanged, and the stored evidence is returned. Any difference re-stamps all four columns: the new reviewer, a new `verdict_at` and the new notes.
  - **Transitions:**
    - approved → rejected is allowed;
    - rejected → approved is allowed when eligible;
    - a verdict can never be cleared back to NULL (see product question Q7).
  - **Proof that only the four columns are written** (plan :412 names no mechanism): in the SQLite unit test, capture the UPDATE with a `before_cursor_execute` listener. Assert that its SET column list is exactly `{verdict, verdict_reviewer, verdict_at, verdict_notes}` and that it has one `WHERE agent_test_run.id = ?`. On PostgreSQL the C24 trigger is the complement.
- **Cost if wrong:** a verdict writer that takes the draft lock creates a cycle risk. A Python clock produces naive/aware drift (#269 C3), and repeated clicks churn `verdict_at`.

### Correction 7 — never translate an `IntegrityError` into ineligibility; #269's linked-verdict trigger must surface — BLOCKING (Task 1)

- **Evidence:**
  - #269 ruling Q3 and Correction 14 add `trg_agent_test_run_linked_verdict_immutable`, which raises `23514` on a verdict change of a release-linked run.
  - #269 Correction 10 expects `record_verdict` to fail with that `IntegrityError` (SQLSTATE `23514`).
- **Ruling:**
  - `record_verdict` catches no `IntegrityError`. The DDL check is a last resort behind Correction 5's application checks.
  - The #268 route maps an unexpected `IntegrityError` to nothing. It propagates as a 500, and #269 owns any friendlier mapping for linked runs.
  - Do not pre-check linkage in #268. Before #269 no link row can exist.
- **Cost if wrong:** #269's Q3 test observes a misleading `ineligible_for_approval`.

### Correction 8 — Task 1 test rules — BLOCKING (Task 1)

- **Overrides:** plan :398 ("mocked session") and :416.
- **Ruling:**
  - **Unit tests** use the real SQLite `factory` fixture of `tests/unit/test_agent_test_workbench.py`, not a mock. A mock cannot exercise the UPDATE column set or the CHECK constraints (SQLite enforces CHECK).
  - **Run fixtures** are created through the executor with `DeterministicFakeModelAdapter` (`tests/fixtures/deterministic_model_adapter.py`). Alternatively, use an ORM **INSERT** that supplies every NOT NULL column: `run_kind`, `model_payload`, `compared_release_id`, `compared_definition_revision_id`, `deterministic_check_results` and `run_by` (#269 Correction 30).
  - **Never** UPDATE a run to set up a fixture. The C24 trigger raises 23514 on PostgreSQL, and a SQLite-only fixture that does so passes for the wrong reason.
  - **PostgreSQL constraint test:**
    - The direct SQL UPDATE must set `verdict`, `verdict_reviewer` **and** `verdict_at` together. Otherwise a pairing check fires first.
    - Assert both `exc.orig.pgcode == "23514"` **and** `exc.orig.diag.constraint_name == "ck_agent_test_run_approved_only_if_completed_and_passing"`. The C24 trigger also raises 23514, with no constraint name, so asserting `pgcode` alone is vacuous.
  - **Assert exact reasons:** use `pytest.raises(IneligibleForApprovalError)` and then `assert exc.value.reason == "not_completed"`. Without the exact reason the plan's sabotage cannot go RED (§7, S1).
  - **Rejection test:** a rejection of a `model_error` run must raise `not_completed` (Correction 5).
  - **PostgreSQL identity test:** after `record_verdict`, a fresh session's full-row tuple minus the four verdict columns equals the tuple before the verdict.
- **Cost if wrong:** constraint and sabotage tests that pass for the wrong reason.

### Correction 9 — published-baseline runs may be approved (user decision P1) — BLOCKING (Tasks 1, 2, 6)

- **Evidence:**
  - #267 user decision P1: "the published baseline is shown … labelled 'not approved' until approved".
  - #267's Task 0 ruling M1 added no check that forbids approving a `published_baseline` run.
- **Ruling:**
  - `record_verdict` accepts both run kinds.
  - Readiness and cleanup ignore baseline runs (Correction 12).
  - The UI offers the verdict controls on baseline evidence too (Correction 26).
- **Cost if wrong:** P1's "until approved" state is unreachable.

---

## 3. Task 2 — readiness

### Correction 10 — two entry points; the locked one is #269's binding (answers #269 Q4) — BLOCKING (Task 2)

- **Overrides:** plan :138-143 and :456-462 (one method whose locking is unspecified).
- **Evidence:** #269 plan :84 and Q4. #269 calls readiness **inside** its publication transaction (L0 exclusive) and inside `preview_release` (L0 share) through `Callable[[Session], object]`. Every #267 workbench method opens its own transaction and refuses one that is already open.
- **Ruling:**
  - **`draft_readiness(self, session) -> DraftReadinessResult`** is the route's entry point. It calls `_require_no_transaction`. Then, inside `with session.begin():`, it calls `self._graph_configuration._lock_current_parents(session, exclusive=False)` and returns `self.readiness_under_parent_lock(session)`.
  - **`readiness_under_parent_lock(self, session) -> DraftReadinessResult`** never begins or commits a transaction.
    - It raises `RuntimeError` unless `session.in_transaction()`.
    - It documents that the caller must already hold L0, shared or exclusive. #269 binds this method.
    - It re-reads `graph_draft` without a lock: L0 is held, so the row cannot change.
  - Neither entry point constructs or touches an `AgentRuntime` (Correction 27).
- **Cost if wrong:** #269 cannot call readiness inside its transaction, or it double-begins.

### Correction 11 — readiness semantics, consistent with #269's gate — BLOCKING (Task 2)

- **Overrides:** plan :145-156 and :464-467.
- **Defect in the plan:** :146 says a case is ready iff **at least one** eligible approval exists. But :464 maps status from **the most recent run only**. So an approved run followed by a newer, unreviewed rerun of the same hash reports `awaiting_review` and blocks. Meanwhile #269's gate (ruling Q5: "link the newest eligible approval") would publish. The preview and the gate would then disagree.
- **Ruling:**
  - **Cases:** the **active and required** `agent_test_case` rows of each of the seven editable roles, in `GRAPH_V1_AGENT_KEYS` order and then by `id`. Optional and inactive cases are not listed. A case is identified by its **row id**: a supersede creates a new row with a new id (#267 C22).
  - **Eligibility predicate:** define it once, as a SQL expression helper shared with cleanup (Correction 19c). It is true when all of the following hold:
    - `run.run_kind = 'candidate'`;
    - `run.test_case_id = case.id` and `run.test_case_version = case.version`;
    - `run.agent_key = case.agent_key`;
    - `run.candidate_hash = graph_draft_agent.candidate_hash` for that role;
    - `run.verdict = 'approved'`, `run.execution_status = 'completed'` and `run.deterministic_checks_passed`.
  - **Status per case:**
    - `approved` iff at least one eligible run exists. `run_id` is then the **newest** eligible run (`ORDER BY run_at DESC, id DESC`), which is the one #269 links.
    - Otherwise, take the newest `candidate` run with this case id and the current hash:
      - none → `needs_test`;
      - `verdict = 'rejected'` → `test_failed`;
      - `verdict IS NULL` and completed and passed → `awaiting_review`;
      - anything else (not completed, or checks failed) → `test_failed`.
    - A stale-hash or stale-case-version approval is never found, so it reads as `needs_test` (AC5).
  - **`blocking`** = the role is changed **and** the status is not `approved`. Unchanged roles are listed with `blocking=False` and `ready=True`. The plan's :152 would mark an unchanged role's cases as blocking while the role does not block.
  - **`is_changed_from_base`** = `graph_draft_agent.candidate_hash != <base release's mapped revision>.content_hash`. This is the same predicate as `ModelAgentNodeSnapshot.changed` (`graph_configuration_workbench.py:325`). Use it; do not invent a second one.
  - **A changed role with zero active required cases** is `ready=False`, appears in `blocking_agents`, and carries `missing_required_case=True` (a new `AgentReadinessItem` field). This is #269 Correction 1 / Q5 (`no_required_case`). It cannot be reached through #267's writers, because #267 C9 refuses to remove the last required case, but an ORM write can reach it.
  - **`all_ready`** = no changed role is blocking. It is `True` when nothing changed; #269 reports `nothing_to_publish` separately.
  - **One snapshot:** the case-and-run read is **one SQL statement**, using correlated scalar subqueries for "newest eligible" and "newest run" (portable to SQLite; no `LATERAL`). This gives one READ COMMITTED snapshot, so a supersede that commits mid-read cannot pair an old case row with new runs. The draft hashes come from separate reads under the held L0 lock, and they cannot change while it is held. This replaces the plan's per-pair `LIMIT 1` query loop (:467).
  - **No case lock:** readiness takes no lock on `agent_test_case`. If a later change adds one, it must lock the role's rows **unfiltered** in id order and then re-select active required rows in a new statement (#269 Correction 29).
- **Cost if wrong:** the preview says "not publishable" while publish succeeds, or the reverse; or an unchanged role blocks.

### Correction 12 — `run_kind = 'candidate'` is mandatory in readiness and cleanup — BLOCKING (Tasks 2 and 4)

- **Evidence:**
  - The DDL allows an approved `published_baseline` (Correction 9).
  - A baseline's `candidate_hash` is the published revision hash. That equals the draft hash exactly when a role is **unchanged**, so without the filter an unchanged role's case reports `approved` from a baseline approval.
  - The #267 whole-branch review (§5.3) and #269 Correction 30 require the filter.
- **Ruling:**
  - Filter both readiness lookups (Correction 11) and every cleanup predicate (Correction 19a) on it.
  - **Test (Task 2):** an unchanged role, whose draft hash equals the published hash, has an approved `published_baseline` run on its required case. Readiness reports that case as `needs_test`, with `blocking=False`.
- **Cost if wrong:** a query that forgets the filter counts a baseline approval as candidate evidence.

### Correction 13 — Task 2 fixture rules — BLOCKING (Task 2)

- **Overrides:** plan :471.
- **Ruling:**
  - **A new hash** comes from a real draft save (`GraphConfiguration.save_editable_model_draft` or the PUT route), or from inserting runs with a different `candidate_hash`.
  - **A stale case version** comes from #267's `update_test_case` supersede, which retires row *n* and inserts version+1 with a new id.
  - **Never** UPDATE `agent_test_run` (C24).
  - Set `run_at` at **INSERT** time to strictly increasing values.
  - Every ordering is `run_at DESC, id DESC`. On PostgreSQL, `now()` is the transaction start, so runs inserted in one transaction tie.
  - Plan :471's third test ("more than 20 runs … cleanup-safety proof") is a Task 4 test. Readiness does not delete anything. Move it there.
  - Add these tests:
    - an older approval plus a newer unreviewed rerun of the same hash is `approved`, and `run_id` is the approval (Correction 11);
    - approving v1 and then superseding it to v2 is `needs_test` for v2;
    - a changed role with its required case deactivated by ORM is `missing_required_case`.
- **Cost if wrong:** fixtures that the trigger rejects on PostgreSQL, or ordering that flakes on ties.

### Correction 14 — readiness types — Advisory (Task 2)

- **Ruling:**
  - Keep the plan's field names (:109-135). #269 plan :83 already transcribes them.
  - Add `missing_required_case: bool` to `AgentReadinessItem`.
  - `status` is the snake_case literal.
  - `TestCaseReadinessItem` begins with `Test`, so give it `__test__ = False`. This is the house pattern: `TestCaseVersion` and `TestRunEvidence` both carry it. Otherwise pytest tries to collect it wherever a test module imports it.
  - Use tuples, not lists, inside the frozen dataclasses, or document that the lists are never mutated.
- **Cost if wrong:** collection warnings, and a shape drift from what #269 recorded.

---

## 4. Task 3 — routes and the strict wire

### Correction 15 — routes stay on the one admin router — BLOCKING (Task 3)

- **Overrides:** plan :160-162, :54, :498 and :516 (`/api/admin/agent-test-runs/…` and `/api/admin/graph-draft/readiness`).
- **Evidence:** #267 C23 and C36 (one router, `require_admin` inherited); #269 Correction 30.
- **Ruling:**
  - **Paths:** `POST /api/admin/agent-definitions/test-runs/{run_id}/verdict` and `GET /api/admin/agent-definitions/readiness`. No GET route shares `/readiness`.
  - **Handlers** are plain `def`, because neither route makes a model call.
  - **Authorization:** the reviewer comes from `require_draft_write_principal`. The body is parsed **inside** the handler, after the dependencies, into a strict `VerdictRequest(_StrictDraftRequest)` whose keys are exactly `{verdict, notes}`. The pattern is `_parse_test_run_request`. Every new route gets a 403-before-parse test.
  - **Path guard:** `_is_storable_row_id(run_id)`, else 404.
  - **Responses:**
    - success: **200** `TestRunEvidenceResponse`, with the currency flags `null` as on GETs (#269 Q6: admin writes return 200);
    - missing run: 404 `_test_run_not_found()`;
    - ineligible: 422 `{"code":"ineligible_for_approval","reason":"not_completed"|"checks_failed","message":str}`, from a strict model;
    - invalid body or `VerdictRejected`: 422 `{"code":"invalid_verdict","errors":[DraftFieldErrorResponse…]}`, in the ordered issue shape;
    - a malformed JSON body: the same envelope as the existing parse helper.
- **Cost if wrong:** a second router that can be registered without the admin dependency, or paths that #269 Task 8 cannot call.

### Correction 16 — the strict evidence wire gains four required keys, both sides changing in the same commit — BLOCKING (Task 3; moves Task 6's parser work into Task 3)

- **Overrides:** plan :176, :289 and :508 ("four optional fields … backward-compatible").
- **Evidence:**
  - `TestRunEvidenceResponse` is `extra="forbid"`.
  - `parseTestRunEvidence` requires exact keys.
  - `tests/unit/test_test_run_failure_contract_client_join.py:64-66` asserts that `TEST_RUN_KEYS` equals `TestRunEvidenceResponse.model_fields`.
  - So a backend-only change REDs the full unit suite, and in production the UI would drop every run response. #267 whole-branch review m-1.
- **Ruling:**
  - **One commit changes, together:**
    - the `TestRunEvidence` dataclass: four required fields placed before the defaulted currency flags;
    - `_evidence_from_row`;
    - `TestRunEvidenceResponse`: `verdict: Literal["approved","rejected"] | None`, `verdict_reviewer: str | None`, `verdict_at: datetime | None`, `verdict_notes: str | None`. All are **required keys** with nullable values, so no field has a default and the wire stays exact-key;
    - the frontend `TEST_RUN_KEYS`, the `TestRunEvidence` TS interface and `parseTestRunEvidence`. The parser validates the types and the pairing: `verdict === null` ⇔ `verdict_reviewer === null` ⇔ `verdict_at === null`, and `verdict === null` ⇒ `verdict_notes === null`;
    - `frontend/tests/fixtures/mocks.ts` and the test helper `syntheticTestRunEvidence`.
  - **Flip the two #267 absence assertions:**
    - `tests/unit/test_agent_definition_workbench_routes.py:5569-5570` becomes "present and null";
    - `TestRunPanel.test.tsx:537` ("a verdict field #268 has not added") becomes an unknown-key case.
  - **Keep** `("verdict", "approved")` in `_FORBIDDEN_CLIENT_RUN_FIELDS` (`:5845`). A run body still cannot set a verdict.
  - Task 3 therefore runs `npx vitest run` on the `api` and workbench directories and `npm run typecheck`. The controller schedules this when no other agent is using the frontend.
- **Cost if wrong:** the UI rejects every run and history response between Task 3 and Task 6, and full unit goes RED on the join test.

### Correction 17 — the readiness wire is snake_case codes, not labels, with no aliases — BLOCKING (Task 3)

- **Overrides:** plan :512 (camelCase aliases; `status` mapped to display labels).
- **Evidence:** every admin wire is snake_case, including `TEST_RUN_KEYS` and `execution_status` codes. #269 embeds #268's readiness verbatim (#269 plan :193), and its page renders labels from the codes.
- **Ruling:**
  - `DraftReadinessResponse`, `AgentReadinessResponse` and `TestCaseReadinessResponse` are strict (`extra="forbid"`) and mirror Corrections 11 and 14 exactly.
  - `status` is one of `needs_test | test_failed | awaiting_review | approved`.
  - The frontend owns the labels "Needs test", "Test failed", "Awaiting review" and "Approved".
  - Add a Python client-join test, in the same style as `test_test_run_failure_contract_client_join.py`, pinning the TS readiness key lists and the status codes to the models.
- **Cost if wrong:** labels baked into the wire, and two sources of display text.

---

## 5. Task 4 — cleanup

### Correction 18 — signature and lock boundary (answers #269 Q2) — BLOCKING (Task 4)

- **Overrides:**
  - :222 (a module function) against :540 (a method);
  - :238 and :582 (a draft-only shared lock);
  - :538 ("Create or modify").
- **Ruling:**
  - **Signature:** `AgentTestWorkbench.cleanup_unpublished_test_runs(self, session, *, per_case_limit: int = 20) -> int`. #269 plan :86 consumes this name.
  - **Transaction:** the method owns its transaction (`_require_no_transaction`, then `with session.begin()`).
  - **First statement:** `self._graph_configuration._lock_current_parents(session, exclusive=False)`, which is release and draft `FOR SHARE`, not "draft only":
    - it keeps the global order L0 release → L0 draft;
    - it excludes a draft save or a publication, both of which need `FOR UPDATE`;
    - it lets #269 Correction 5 instrument cleanup as a waiter through the same override.
  - **`per_case_limit`:** a strict `int` ≥ 1. A `bool` is refused with `ValueError`.
  - **Result:** returns the number of rows deleted.
- **Cost if wrong:** an inverted lock order against the publisher, or #269 binding a name that does not exist.

### Correction 19 — cleanup SQL corrections — BLOCKING (Task 4)

- **Overrides:** the SQL at plan :557-580.
- **(a) Candidates only.** The deletable and ranked set is `run_kind = 'candidate'`. #268 never deletes a baseline run (Correction 12). See product question Q6.
- **(b) Deterministic ranking.** Use `ROW_NUMBER() OVER (PARTITION BY test_case_id ORDER BY run_at DESC, id DESC)`. The plan's `run_at DESC` alone ties.
- **(c) One eligibility predicate.** The eligible-approval exclusion is Correction 11's helper, the same expression readiness uses.
  - The plan's version requires `atc.is_active` but not `is_required`. Spec §5.5 says "an approved run still eligible for an active **required** case".
  - The plan's version also omits `run_kind`.
  - Join the case by `atc.id = run.test_case_id` and the draft agent by `agent_key`.
- **(d) Semantics kept.** Protected rows are removed **before** ranking, as in the plan's SQL. So the latest 20 *unprotected* candidate runs per case row are retained, plus every protected row. This matches the plan's tests (:545-549) and gives #269 Correction 19 outcome **(a)**: an unlinked eligible approval outside the window is retained. "Per case" means per case **version row**, which is the FK and the history route's identity.
- **(e) Recheck on the target row (new defect).**
  - Scenario: a verdict writer holds run *X* `FOR UPDATE` while it approves *X*. The DELETE's ranked subquery (its snapshot) sees *X* unapproved, so the DELETE then waits on *X*.
  - Under READ COMMITTED, PostgreSQL's EvalPlanQual recheck re-evaluates the **target row's** quals against the committed version. It does not re-evaluate the already-materialized `IN (subquery)` list. So *X* is deleted even though it is now an eligible approval.
  - **Fix:** repeat `NOT <linked>(agent_test_run)` and `NOT <eligible>(agent_test_run)` in the DELETE's **outer** `WHERE`, correlated on the target row.
  - **Status:** this is reasoned, not probed. Task 4's RED must reproduce it (see the test below). If it does not reproduce, record that and keep the outer predicate as a cheap defence.
- **(f) Linked exclusion.** `NOT EXISTS (SELECT 1 FROM graph_release_test_run g WHERE g.agent_test_run_id = agent_test_run.id)`, served by `ix_graph_release_test_run_run`.
- **(g) No case lock.** Cleanup takes no case lock.
  - A supersede racing cleanup either leaves the old approval eligible, so it is kept, or retires it, so it is deletable. That is correct, because the new version has no approval.
  - Correction 11's rule for any future case lock applies.
- **Cost if wrong:**
  - (c) and (e): the only approval for a required case is deleted, and readiness regresses to `needs_test`.
  - (a): a baseline approval shields runs.
  - (b): the tests flake.

### Correction 20 — Task 4 tests — BLOCKING (Task 4)

- **Overrides:** plan :542-549.
- **Ruling:**
  - Keep the plan's five tests, with exact ID sets.
  - **Fixture rules:**
    - `run_at` is set at INSERT;
    - linked rows are inserted by raw SQL `INSERT INTO graph_release_test_run` in the test only, following #267 C21's pattern, because #268 has no linker. Use `evidence_kind='approval'` and `source_release_id NULL`;
    - approvals are inserted with the verdict set at INSERT (the DDL allows it for a completed, passing run) or through `record_verdict`, never by UPDATE.
  - **Add these tests:**
    1. A stale-**case-version** approval outside the window (v1 approved, then superseded to v2) is deleted.
    2. A stale-**hash** approval outside the window (the draft was saved after the approval) is deleted.
    3. 25 `published_baseline` runs on one case are all retained (cleanup returns 0).
    4. An approval on an **optional** active case outside the window is deleted (Correction 19c).
    5. A PostgreSQL ordering test for Correction 19e:
       - the verdict writer approves *X* (rank 21 or higher among unprotected rows) and pauses before commit;
       - cleanup starts on another thread and is observed blocked, with `pg_blocking_pids(cleanup_pid)` containing the writer's PID;
       - the PID is captured with `SELECT pg_backend_pid()` before the blocking statement (#269 Correction 5);
       - the writer commits;
       - assert that *X* survives and that the count excludes *X*.
    6. A PostgreSQL ordering test: a draft save holding L0 exclusive blocks cleanup, observed by PID. After the save commits, the old-hash approval outside the window is deleted.
  - All of these go in `tests/integration/test_agent_definition_workbench_postgres.py`, which is already in `integration-graph` (`.github/workflows/test.yml`), so no CI edit is needed.
  - Add a SQLite unit test only for the argument validation.
- **Cost if wrong:** AC8 ("tested with protected evidence outside the window and stale hashes **and case versions**") is only half met, and the recheck defect ships unproved.

### Correction 21 — cleanup has no production caller in #268 — Advisory (Task 4; product question Q1)

- **Evidence:**
  - Plan :7 says "injected into the startup/maintenance path".
  - Plan :307 says "No automatic cleanup on every request — cleanup is a discrete administrative operation".
  - No task adds a caller.
  - A startup hook would turn a cleanup failure into `SystemExit(1)` (`packages/databricks-tellr-app/databricks_tellr_app/run.py:54-69`).
- **Ruling:**
  - #268 ships the method and its tests, with no startup hook, no per-request call and no route.
  - Where it is invoked is product question Q1.
  - If the user picks an admin route, it goes on the one router (`POST /api/admin/agent-definitions/test-runs/cleanup`), returns 200 `{"deleted": n}`, and needs a forbidden-name review for any UI control.
- **Cost if wrong:** the retention bound is never enforced in production until Q1 is answered.

---

## 6. Task 6 — frontend

### Correction 22 — Task 6 scope, and the client names #269 consumes — BLOCKING (Task 6)

- **Overrides:** plan :669-675 and :708-714.
- **Ruling:**
  - **Files:**
    - `draftEditorState.ts` and `useDraftEditor.ts`, which dispatch and fetch; the plan omits the second;
    - `TestRunPanel.tsx`;
    - `DefinitionEditor.tsx`, which renders `draftStatus(entry)` at `:301`; the plan omits it;
    - `AgentDefinitionWorkbench.tsx` (`:134`);
    - `frontend/src/api/agentDefinitions.ts`;
    - `frontend/tests/fixtures/forbiddenActionNames.ts`;
    - `frontend/tests/fixtures/mocks.ts`;
    - the workbench, panel and state Vitest files;
    - `frontend/tests/e2e/agent-definition-workbench.spec.ts`.
  - **Exported API (#269 "do not define a second readiness type"):**
    - `getDraftReadiness(): Promise<DraftReadiness>` and `parseDraftReadinessResponse`;
    - the types `DraftReadiness`, `AgentReadiness`, `TestCaseReadiness` and `ReadinessStatus`;
    - `recordTestRunVerdict(runId, {verdict, notes}): Promise<TestRunEvidence>`, with typed refusals for 404, 422 `ineligible_for_approval`, 422 `invalid_verdict` and 403.
  - The verdict parser changes are already in place from Task 3 (Correction 16).
- **Cost if wrong:** #269 defines a second readiness type, or Task 6 edits a file its brief does not list.

### Correction 23 — the forbidden-action guard: exact exemptions, stems unchanged — BLOCKING (Task 6)

- **Evidence:**
  - `FORBIDDEN_ACTION_STEMS` contains `approve|reject` (`forbiddenActionNames.ts:17-18`).
  - `ALLOWED_ACTION_NAMES` has five entries.
  - `toHaveLength(5)` is asserted at `AgentDefinitionWorkbench.test.tsx:351` and at `tests/e2e/agent-definition-workbench.spec.ts:1505`.
  - The plan never mentions the guard. Its Approve and Reject buttons would RED every workbench sweep.
- **Ruling:**
  - Append exactly `'Approve run'` and `'Reject run'`. These are whole-name exemptions, following #267 C25/C38.
  - Both lengths become 7.
  - Do not touch the stems.
  - Add an assertion that `forbidsActionName('Approve run and publish')` and `forbidsActionName('Approve all')` stay true.
  - **For #269:** its Correction 7 (`toHaveLength(4)`, citing `:243`/`:1462`) is stale. After #268 the count is 8, and the lines are wherever #268 leaves them. #269's Task 0-B must re-derive them.
- **Cost if wrong:** suite-wide RED, or a loosened stem.

### Correction 24 — the verdict joins the one gate; readiness is an ungated, counted, freshness-checked read — BLOCKING (Task 6)

- **Evidence:** #267 Task 6 fixed a single reducer with one gate (`TestOperationKind`, `TEST_OPERATIONS`). Its reads (history, cases) are ungated, counted reads with request ids.
- **Ruling:**
  - **Verdict:** add `'verdict'` to `TestOperationKind` and `TEST_OPERATIONS`.
  - **Readiness:**
    - one `readiness` slot on the editor state, not per role, holding `{status, data, requestId}`;
    - read on workbench load, and after every settled save, candidate run, baseline run, verdict, and case create, update or retire;
    - a response is dropped when its request id is not the latest one, **or** when its `draft_lock_version` differs from the current saved lock.
  - **Tests that count GETs** (`expect(allGets(fetchMock)).toHaveLength(n)`, 8 sites in `AgentDefinitionWorkbench.test.tsx`, including `:3665`) shift. Update each one deliberately, with a comment naming the readiness GET.
  - **Playwright:** its route mocks work by URL (#266 c17), so it needs a readiness mock in `mocks.ts`. Otherwise every spec hits an unmocked route.
- **Cost if wrong:** a second gate, or a stale readiness response painting "Approved" on a hash that has changed.

### Correction 25 — `DraftStatus` is per role, derived from the role's readiness item — BLOCKING (Task 6)

- **Overrides:** plan :262-272 and :693-695 (`draftStatus(entry, TestCaseReadinessItemResponse | null)`, which is per case).
- **Ruling:**
  - The six values are `'Clean' | 'Unsaved' | 'Needs test' | 'Test failed' | 'Awaiting review' | 'Approved'`.
  - The signature is `draftStatus(entry, readiness: AgentReadiness | null)`. The precedence is:
    1. `Unsaved` (local ≠ saved) and `Clean` (the saved hash equals `publishedHash`) are unchanged.
    2. If `readiness === null`, or `readiness.candidate_hash !== entry.saved.candidate_hash`, or `readiness.missing_required_case`, the status is `'Needs test'`. Stale data can never show Approved.
    3. Otherwise aggregate the role's cases. The **default** order, pending product question Q2, is worst-first: any `test_failed` → `Test failed`; else any `needs_test` → `Needs test`; else any `awaiting_review` → `Awaiting review`; else `Approved`.
  - Callers: `AgentDefinitionWorkbench.tsx:134` and `DefinitionEditor.tsx:301`.
  - The plan's six-case test list (:683-689) stays. Add a stale-readiness-hash case and a `missing_required_case` case.
- **Cost if wrong:** a per-case function cannot label the role in the navigation, or stale data shows Approved.

### Correction 26 — the verdict controls — BLOCKING (Task 6)

- **Overrides:** plan :697-706.
- **Ruling:**
  - **Where:** the controls appear on the candidate **and** the baseline evidence (P1, Correction 9).
  - **Approve run:** disabled, with visible reason text, when `execution_status !== 'completed'` ("Only completed runs can be reviewed") or when checks failed ("Deterministic checks did not pass"). Use text, not only a tooltip.
  - **Reject run:** disabled when the run is not completed (Correction 5).
  - **Notes:** an optional textarea, at most 2000 characters.
  - **After a verdict settles:**
    - replace the evidence with the verdict response. That response *is* the evidence, so do not issue a separate run GET;
    - refetch readiness.
  - **Labels:**
    - the P1 label ("Published baseline (not approved)", `TestRunPanel.tsx:129` and `:608`) becomes verdict-aware: "(approved)", "(rejected)" or "(not approved)";
    - an approved run shows reviewer, time and notes as **text only**, following #267's text-only rendering rule;
    - an approved run offers `Reject run`; a rejected, eligible run offers `Approve run`.
  - **E2E:** Task 6 Step 5's E2E is Approve → badge `Approved` → readiness refetched. It excludes the Review & Publish part (Correction 1).
- **Cost if wrong:** P1 is unreachable, or a control is offered that the server refuses.

---

## 7. Cross-cutting

### Correction 27 — no #268 path calls a model (#269 Correction 13) — BLOCKING (Tasks 1, 2, 4)

- **Ruling:**
  - `record_verdict`, `draft_readiness`, `readiness_under_parent_lock` and `cleanup_unpublished_test_runs` never call `self._runtime()`, `get_agent_test_runtime()` or any adapter. Each holds its transaction only for database work.
  - **Test (one per method, in `test_agent_test_workbench.py`):** construct `AgentTestWorkbench(runtime=<object whose every attribute access raises>)`, and monkeypatch `src.services.agent_test_workbench.get_agent_test_runtime` to raise. Each method must succeed.
  - The #267 AST call-site guards on `run_candidate` and `run_published_baseline` stay GREEN unchanged.
- **Cost if wrong:** a lock held across a model call, which is #269 C13's deadlock or stall.

### Correction 28 — the lock-order table for #268 — Advisory (the whole-branch review re-derives it)

The #269 global order is L0 release → L0 draft → L1 draft agents → L2 case rows → L3 run rows.

| #268 path | Locks, in order | Relation to #269 |
|---|---|---|
| `record_verdict` | L3 `FOR UPDATE` (one row) | a subsequence; serializes with #269's L3 gate lock |
| `draft_readiness` | L0 release+draft `FOR SHARE`, then plain reads | the same as `read_workbench`; waits behind publication and draft saves |
| `readiness_under_parent_lock` | none (the caller holds L0) | #269 binding |
| `cleanup_unpublished_test_runs` | L0 release+draft `FOR SHARE`, then DELETE row locks (L3) | a prefix-respecting subsequence; excludes publication at L0 |

- None of these touches L1 or L2.
- The #267 run insert (L0 share, then the implicit FK `KEY SHARE`, then its own new row) is compatible.
- Cleanup and a run insert can run concurrently, because both take L0 share. A run inserted during cleanup is outside the DELETE snapshot, and the window is off by at most one until the next cleanup.

### Correction 29 — baseline and gate commands — Advisory

- **Overrides:** plan :359-379.
- **Ruling:**
  - The plan mixes three PostgreSQL files into one pytest invocation, and it sets neither `DATABASE_URL` nor `TELLR_TEST_POSTGRES_URL`. Use the commands in §9, one invocation per PostgreSQL file, and demand zero skips.
  - Add `tests/unit/test_test_run_failure_contract_client_join.py` to the focused set (Correction 16), and the new readiness join test once it exists.
  - Run the frontend baseline at Task 3 or Task 6 dispatch. It was not run in this pass, because another agent may be using the frontend.
- **Cost if wrong:** a PostgreSQL file silently skips, or the dev database is touched.

### Correction 30 — the plan's no-DDL rule stands — Advisory

- **Evidence:** every column and check #268 needs exists (Correction 3). The only new database object in the epic for these columns is #269's linked-verdict trigger.
- **Ruling:**
  - #268 adds no DDL and no trigger, and it does not edit `src/core/database.py`.
  - The missing `verdict_notes` pairing check and the missing non-blank `verdict_reviewer` check (#267 Task 0 M2) are enforced in the service (Correction 4) and are not added to the DDL.
- **Cost if wrong:** a schema change that #269 must rebase over.

---

## 8. Per-task consistency (the plan's task against itself and the code)

| Task | Plan says | Inconsistency or defect at `b0c4d8aeb` | Corrections |
|---|---|---|---|
| 1 | `record_verdict(…, reviewer, notes, actor)`; `IneligibleForApprovalError(code=…)` including `not_found`; mocked session; "assert no other column" | a redundant `actor` and a nonexistent audit log; the class has no `__init__`; `TestRunNotFound`/404 already exists; rejection of an incomplete run conflicts with AC1; a mock cannot test the SET list; the PostgreSQL constraint test is vacuous without the constraint name and all three paired columns | 4, 5, 6, 7, 8 |
| 2 | "ready iff ≥1 approval", but status is taken from the newest run; per-pair `LIMIT 1` queries; blocking ignores changed; shared draft lock | an internal contradiction (it disagrees with #269's gate); multi-statement skew; unchanged roles marked blocking; no `run_kind` filter; no `no_required_case`; not callable inside #269's transaction; the >20-runs test belongs to Task 4 | 10, 11, 12, 13, 14 |
| 3 | `/api/admin/agent-test-runs/…`, `/api/admin/graph-draft/readiness`; "optional, backward-compatible" verdict fields; labels and camelCase on the wire; `require_admin` per route | outside the router's prefix; the strict model, strict parser and Python join test all REJECT the extension; the wire is snake_case; the router already carries `require_admin` | 15, 16, 17 |
| 4 | a module function in the interface section but a method under Produces; a draft-only share lock; SQL without `run_kind`, `is_required` or an id tie-break; subquery-only exclusions | the name conflicts; lock order; the baseline and optional cases; ties; the EPQ recheck gap; no stale-case-version test; no caller | 18, 19, 20, 21 |
| 5 | extend `_GraphConfigurationBootstrap.publish_draft` | no publication method exists, and #269 owns it | 1 (deleted) |
| 6 | per-case `draftStatus`; Approve/Reject; a Review & Publish overlay; four files | the guard forbids approve and reject; the one-gate reducer; GET counters; DefinitionEditor and useDraftEditor are unlisted; P1 labels; the page is #269's | 1, 22, 23, 24, 25, 26 |

## 9. Producer/consumer rows (every task pair that shares an interface)

| Producer → consumer | Interface | Status and binding correction |
|---|---|---|
| #267 → 1 | verdict columns, their checks, the C24 trigger, `TestRunNotFound`, `_evidence_from_row`, `_require_no_transaction`, `_actor_issues` | confirmed at `b0c4d8aeb`; re-probe after the #267 merge (3) |
| #267 → 2 | `_lock_current_parents(exclusive=False)`, `GraphDraftAgent.candidate_hash`, the changed predicate (`workbench.py:325`), case row identity per version (C22) | 10, 11 |
| #267 → 3 | the router, `require_draft_write_principal`, `_StrictDraftRequest`, `_test_run_response`, `TestRunEvidenceResponse`, `TEST_RUN_KEYS`, the join test | 15, 16 |
| #267 → 4 | `ix_graph_release_test_run_run`, the RESTRICT FK, `run_kind` | 18, 19 |
| #267 → 6 | the one gate (`TestOperationKind`), history-read pattern, `forbiddenActionNames.ts`, P1 labels | 23, 24, 26 |
| 1 → 2 | the verdict semantics: approved means completed and passed (DDL); verdicts are never NULLed | 6, 11 |
| 1 → 3 | `record_verdict`, `IneligibleForApprovalError.reason`, `VerdictRejected`, `TestRunNotFound` | 5, 15 |
| 1 → 4 | an approval by `record_verdict` is a protected row; the verdict writer's L3 lock against cleanup's DELETE | 19e, 20.5 |
| 1 → 6 | the verdict response is full evidence | 16, 26 |
| 2 → 3 | the `DraftReadinessResult` shape | 14, 17 |
| 2 → 4 | **one** eligibility SQL helper, used by both | 11, 19c |
| 2 → 6 | the readiness wire, `draft_lock_version` freshness | 17, 24, 25 |
| 3 → 6 | exact paths, the verdict and readiness envelopes; the evidence parser already landed | 15, 16, 22 |
| 4 → 6 | none (no caller) | 21 |
| 2 → #269 | `readiness_under_parent_lock(session)` (the Q4 binding); `DraftReadinessResponse` embedded verbatim; the TS readiness types | 10, 17, 22 |
| 1 → #269 | `record_verdict` L3-only lock (Q9), `IntegrityError` propagates (Q3 trigger) | 6, 7 |
| 4 → #269 | the cleanup name and signature; L0 share of both parents first (Q2); outcome (a) for #269 C19 | 18, 19d |
| 6 → #269 | `ALLOWED_ACTION_NAMES` count 7 (#269 C7 re-derives); the readiness client and parser | 22, 23 |

## 10. Files #268 shares with #267 and #269

The #267 set is `e91fcd856..b0c4d8aeb`. The #269 set comes from its plan's Files lists and its corrections, read only.

| File | #268 task | #267 | #269 | Rule |
|---|---|---|---|---|
| `src/services/agent_test_workbench.py` | 1, 2, 4 | created (Tasks 2–4) | consumes `readiness_under_parent_lock`, `record_verdict`, `cleanup_*` | append methods; do not touch the executors |
| `src/api/routes/agent_definitions.py` | 3 | Tasks 2, 5 routes | imports `require_draft_write_principal` and #268's readiness response; no change | append two routes |
| `src/api/schemas/agent_definitions.py` | 3 | the `TestRunEvidenceResponse` owner | imports the readiness response | extend the evidence model only per C16; add sibling models |
| `src/database/models/graph_configuration.py` | read only | created `AgentTestRun`/`GraphReleaseTestRun` | reads | no change (C30) |
| `src/core/database.py` | read only | C24 trigger | Task 4 C14 trigger | #268 does not touch it |
| `src/services/graph_configuration_workbench.py` | read only (`_lock_current_parents`, `:325`) | read only | Task 2 handoff retry | #268 inherits #269's retry after rebase |
| `tests/unit/test_agent_test_workbench.py` | 1, 2, 4, 27 | created | none listed | append |
| `tests/unit/test_agent_definition_workbench_routes.py` | 3 | created the run routes; `:5569` absence assert | none (own route file) | flip `:5569-5570`; keep `:5845` |
| `tests/unit/test_test_run_failure_contract_client_join.py` | 3 | created | — | key set grows by four |
| `tests/integration/test_agent_definition_workbench_postgres.py` | 1, 2, 4 | extended | Task 4 recorded #267/#268 PostgreSQL files | append; one invocation per file; zero skips |
| `.github/workflows/test.yml`, `tests/unit/test_ci_collects_integration_tests.py` | none (no new PostgreSQL file) | — | Tasks 1–4 add files | edit only if a new PostgreSQL file appears |
| `frontend/src/api/agentDefinitions.ts` | 3 (evidence parser), 6 (clients) | test-case and run clients | Task 6 consumes the readiness types | append |
| `frontend/.../draftEditorState.ts`, `useDraftEditor.ts` | 6 | the one gate | none | add one operation kind and one readiness slot |
| `frontend/.../TestRunPanel.tsx` (+ test) | 3 (test `:537`), 6 | created | none | append |
| `frontend/.../AgentDefinitionWorkbench.tsx` (+ test) | 6 | mounts the panel | Task 6 header link | status call only |
| `frontend/.../DefinitionEditor.tsx` | 6 | — | — | status call at `:301` |
| `frontend/tests/fixtures/forbiddenActionNames.ts` | 6 | +2 names | Task 6 +`'Review & Publish'` | #268 lands first; count 7 → #269 makes it 8 |
| `frontend/tests/fixtures/mocks.ts`, `tests/e2e/agent-definition-workbench.spec.ts` | 3, 6 | evidence mocks; `:1505` length | Task 7 | mock routes by URL |

## 11. Pre-briefs: the known defects each task must be dispatched against

- **Task 1:**
  - Corrections 4, 5, 6, 7, 8, 9, 27;
  - the `__test__ = False` pattern for any new class whose name begins with `Test`;
  - keep `test_a_completed_run_persists_one_row_with_null_verdict_columns` GREEN.
- **Task 2:** Corrections 10, 11 (every bullet, especially the any-approval rule and the single statement), 12, 13, 14, 27.
- **Task 3:**
  - Corrections 15, 16 (one commit across Python and TypeScript; flip `:5569-5570` and `TestRunPanel.test.tsx:537`), 17;
  - a 403-before-parse test for both routes;
  - a parametrized forbidden-body-field test for the verdict body, including `reviewer`, `verdict_reviewer`, `verdict_at` and `run_id` (needed for §12, S3).
- **Task 4:** Corrections 18, 19 (a–g; **e is new**), 20 (all six extra tests), 21, 27, 28.
- **Task 6:** Corrections 1 (no Review & Publish), 22, 23, 24, 25, 26. Route mocks by URL. Update the GET counters deliberately.

**Sabotage assignment:** the controller and reviewer targets in §12 differ for every task. Tell the reviewer which ones the controller already ran. The pytest sabotage runs happen from **inside** the temporary worktree (#267 ledger epic hazard).

## 12. Sabotage targets — can each go RED on the executed path?

| # | Task | Plan target | Can it go RED? | Condition, or its replacement |
|---|---|---|---|---|
| S1 | 1 | remove the `execution_status != 'completed'` check (plan :426) | **Only conditionally.** A `model_error` run always has `deterministic_checks_passed = False` (`_persist_run`), so with the check gone an approval raises `checks_failed`, not `not_completed`. | The test must assert `reason == "not_completed"` exactly (C8). The rejection-of-`model_error` test then goes RED too, because it writes. Controller target. |
| S1b | 1 | (new, reviewer) drop the `verdict_at` / `verdict_reviewer` assignment from the change branch of the idempotence check | yes: the SET-list assertion and the re-stamp test | — |
| S2 | 2 | remove the stale-hash term (plan :481) | **Yes**, under C11: the approval predicate loses the hash, so the stale approval becomes eligible, so `approved` → RED on the stale-hash test | Under the plan's newest-run-only logic, removing the hash from only one lookup could stay GREEN. That is another reason for C11's single predicate. Controller target. |
| S2b | 2 | (new, reviewer) drop the `run_kind = 'candidate'` term from the shared predicate | yes: the C12 unchanged-role baseline-approval test | — |
| S3 | 3 | take `reviewer` from the body (plan :524) | **Only conditionally.** The strict `extra="forbid"` model already 422s a `reviewer` key, and a test that sends only `{verdict, notes}` stays GREEN. | Needs Task 3's forbidden-body-field test (the `reviewer` key must give an exact 422) **plus** `verdict_reviewer == principal`. The sabotage adds `reviewer` to `VerdictRequest` and passes it through. Controller target. |
| S3b | 3 | (new, reviewer) drop the four verdict keys from `TEST_RUN_KEYS` only | yes: the Python join test `:64-66` and the Vitest parser cases | — |
| S4 | 4 | remove the second `NOT EXISTS` (plan :590) | **Yes, if** it is removed at **every** use site in cleanup (the ranked subquery **and** the C19e outer recheck). Removing one copy stays GREEN on the sequential test. | Sabotage the helper's use in cleanup only, not the helper itself, which readiness also uses. Controller target. |
| S4b | 4 | (new, reviewer) remove the C19e outer recheck only | yes: only the C20.5 ordering test (if 19e reproduces); the sequential tests stay GREEN | If the RED does not reproduce, record it (19e). |
| S4c | 4 | (new, spare) drop `id DESC` from the window order | RED only with tied `run_at`; add a tie fixture, or mark the target as non-RED | — |
| S5 | 5 | skip the re-verify loop (plan :659) | **N/A.** Task 5 is deleted (C1). This target is #269's (its Corrections 11 and 12 govern it). | — |
| S6 | 6 | (plan names none) | — | **Controller:** accept a readiness response whose `draft_lock_version` is stale, which REDs the C24 freshness test. **Reviewer:** enable `Approve run` when checks failed, which REDs the C26 disabled test. |

## 13. Cause baseline at `b0c4d8aeb`

Environment:
- `PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest`.
- `test ! -e .venv` held before and after. Nothing was installed.
- No frontend command was run.
- PostgreSQL was `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, with fixture-owned throwaway databases. `ai_slide_generator` was not touched.

**Full unit** (`DATABASE_URL=sqlite:////tmp/t268-base.sqlite … tests/unit -q -p no:randomly -rf`): **6 failed, 6616 passed, 110 skipped, 136 warnings** (400 s). These are the same totals as the #267 whole-branch review. The failures are exactly the known set, by node and by cause:
1. `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available`: `assert 'provisioned' == 'autoscaling'`.
2. `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails`: `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
3. `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict`: `AttributeError: '_FakeSession' object has no attribute 'execute'`.
4. `…::test_create_session_still_stores_a_single_authority_config_unchanged`: the same cause.
5. `…::test_create_session_still_accepts_no_agent_config`: the same cause.
6. `test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session`: `ConversationGraphReleaseIntegrityError: no active Graph Release`.

There is no failure outside this set, and none is in a #268 file.

**Focused (the plan's unit files), one invocation, `DATABASE_URL=sqlite:////tmp/t268-focus.sqlite`: 795 passed, 0 failed, 0 skipped.**
- `test_graph_definition_manifest` 101
- `test_graph_configuration_bootstrap` 27
- `test_graph_configuration_models` 27
- `test_agent_definition_workbench_routes` 392
- `test_agent_test_workbench` 140
- `test_agent_runtime` 108

**Focused extras**, one invocation: `test_test_run_failure_contract_client_join` 7, `test_graph_configuration_workbench` and `test_ci_collects_integration_tests`, 35 passed in total, 0 skipped.

**PostgreSQL**, one invocation per file, **zero skips in every file**:
- `test_graph_configuration_bootstrap_postgres`: 3 passed
- `test_graph_configuration_constraints_postgres`: 66 passed
- `test_agent_definition_workbench_postgres`: 25 passed
- (not named by the plan, run for the #267 comparison) `test_agent_schema_overlay_postgres`: 10 passed; `test_persisted_graph_runtime_failures_postgres`: 7 passed

These match the #267 whole-branch review's gates (workbench 25, constraints 66, bootstrap 3, overlay 10, runtime failures 7).

**Frontend:** not run in this pass. Record the Vitest, typecheck and Playwright causes at Task 3 dispatch (C16).

**Re-derive** the whole baseline after the rebase onto the #267 merge, and again after Task 3, which changes a wire model. Compare by node ID and cause. A new failure, skip or warning location is a regression even when the count matches.

## 14. Rulings on plan-versus-code conflicts, with the cost if wrong

| # | Conflict | Ruling | Cost if wrong |
|---|---|---|---|
| 1 | Task 5 and the Review & Publish page | deleted; they are #269's | two halves of one transaction |
| 4 | reviewer plus actor, and an audit log | one principal; the columns are the audit | an invented audit sink |
| 5 | not-found and incomplete rejection | 404 `TestRunNotFound`; `not_completed` for both verdicts | AC1 violated; the wrong status |
| 6 | lock and clock | L3 only; `func.now()`; identical is a no-op | a lock cycle; tz drift; churn |
| 7 | the IntegrityError mapping | propagate | #269's Q3 test misreads |
| 10 | the readiness transaction | two entry points | #269 cannot bind readiness |
| 11 | any-approval against newest-run | any eligible approval wins; one statement; changed-only blocking | preview and gate disagree |
| 12, 19a | the `run_kind` filter | mandatory | a baseline approval counts |
| 15 | route paths | on the one router | an unguarded router |
| 16 | "backward-compatible" fields | required nullable keys; one commit across Python and TypeScript | the UI drops every run |
| 17 | labels and camelCase | snake_case codes | two display-text sources |
| 18 | cleanup name and lock | method; L0 share of both parents | inverted order; wrong binding |
| 19c | eligibility predicate | shared; includes `is_required` | readiness and cleanup diverge |
| 19d | window semantics | exclude-then-rank (the plan's) | ±N retained rows |
| 19e | the EPQ recheck | an outer predicate on the target row | the only approval is deleted |
| 21 | the cleanup caller | none until Q1 | retention not enforced |
| 23 | the forbidden guard | two exact names; length 7 | suite RED or a loosened guard |
| 25 | per-case `draftStatus` | per role; stale data means Needs test | a false Approved |
| 27 | model calls | none on any #268 path | a lock across a model call |

## 15. Product questions (asked, not decided)

- **Q1.** When should unpublished-run cleanup run in production? The options are an explicit admin action (a route and a button), after each run insert, or a periodic job. The plan says both "startup/maintenance path" and "a discrete administrative operation", and names no caller. Until this is answered, #268 ships the method with no caller.
- **Q2.** When a changed role has several required cases in different states, which single status does the navigation badge show? The proposed default is worst-first: Test failed > Needs test > Awaiting review > Approved.
- **Q3.** May an administrator approve a run whose candidate is no longer the saved draft, or whose case version has since been retired? The default allows it: readiness simply ignores it, and the evidence is kept. The alternative refuses it with a 409.
- **Q5.** Now that baseline runs can be approved (P1), which stored baseline should the Compare view show when a newer, unapproved baseline rerun follows an approved one? Currently it shows the newest completed baseline, whatever its verdict (#267 C20).
- **Q6.** Should published-baseline runs also be bounded by the 20-run retention rule? Currently #268 never deletes them.
- **Q7.** Should an administrator be able to withdraw a verdict, returning it to "no verdict"? Currently a verdict can only be flipped between approved and rejected.

(Q4 was withdrawn. The issue's AC1 settles the rejection-eligibility question: only completed runs can be reviewed.)

## 16. GO/NO-GO for Task 1 once #267 merges

**Conditional GO.** Task 1 may dispatch as soon as all of the following hold:
1. #267's token-usage fix wave is reviewed and merged locally into `feat/langgraph-core`. This branch is then rebased onto that merge, with a clean `range-diff` against the ledger-only commit, and `IMPLEMENTATION_BASE` is recorded in `progress.md`.
2. §13's baseline is re-derived by cause at `IMPLEMENTATION_BASE`: the same 6 unit failures, and zero PostgreSQL skips.
3. Correction 3's re-probe list is re-run. In particular, if the token wave changed the `TestRunEvidence` / `TestRunEvidenceResponse` / `TEST_RUN_KEYS` field set or `_evidence_from_row`, refresh Correction 16's list.
4. Task 1's brief carries Corrections 4–9 and 27.

Task 1 depends on nothing else. Q1–Q7 do not block it.

- **Task 2:** GO after Task 1, on the same conditions.
- **Task 3:** needs a frontend slot (C16).
- **Task 4:** GO after Task 2, because it shares the eligibility helper.
- **Task 5:** deleted.
- **Task 6:** GO once a frontend slot is free. It can proceed on Q2's default if the user has not answered.
