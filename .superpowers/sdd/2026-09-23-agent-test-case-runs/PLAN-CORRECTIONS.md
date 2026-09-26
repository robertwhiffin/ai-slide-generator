# PLAN-CORRECTIONS.md — this file overrides /Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/docs/superpowers/plans/2026-09-23-agent-test-case-runs.md wherever they differ.

- **Plan:** the user's untracked draft, 1010 lines, read in the main worktree. It was not modified, moved or copied.
- **Earlier pass carried forward:** `docs/superpowers/plans/2026-09-23-agent-test-case-runs-CORRECTIONS.md`, 7 corrections, run against `d72ad974d`. Every item was re-verified below with fresh evidence. Old line numbers are not reused.
- **Code base:** `c040dbde0` (Merge #264), branch `feat/agent-test-case-runs-267`, worktree `.worktrees/issue-267-plan`. `git status` was clean apart from this directory.
- **Not yet integrated:**
  - #266 is on `plan/model-discovery-266`, at `18b0f8cd3`, Task 2.
  - The builder payload fix is on `fix/builder-owner-session-id` (`9894e55a5`), and it is **not** an ancestor of HEAD.
- **Rebased 2026-09-26:** onto `e91fcd856` (Merge #266, with the builder fix `6cbab388a` and the all-roles payload fix `50c8cbf35`). §12 (Corrections 29–40) re-probes this file against that head and **overrides §1–§11 where they differ**. `IMPLEMENTATION_BASE=e91fcd856`.
- **Phase:** this is Task 0 phase A. Task 1 may dispatch only after the Phase-A-at-dispatch re-probe in §7.
- **Numbering:**
  - Corrections 1–7 are the user's seven: U-B1..U-B3 and U-A1..U-A4.
  - Corrections 8–12 are the five binding carry-forwards.
  - Corrections 13 onwards are new.
- **Blocking:** every correction is marked **BLOCKING (task)** or **Advisory**. A blocking correction must be in the brief of the task it names. The implementer must be told the defect, not left to find it.

---

## 1. The user's seven corrections, re-verified at `c040dbde0`

### Correction 1 (U-B1) — `Float` is not imported — BLOCKING (Task 0)
- **Evidence:** `src/database/models/graph_configuration.py:7-24`, the one `from sqlalchemy import (...)` block, is `JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKeyConstraint, Index, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func, text, true`. `grep Float` finds nothing in the file. The plan's DDL uses `latency_ms = Column(Float)` (plan :115).
- **Ruling:** add `Float` to the import block, and use it for `latency_ms`. The runtime already reports this value as a Python `float` (`AgentInvocationDiagnostics.latency_ms`, `src/services/agent_runtime.py:185`). `Numeric` is kept for hashed decimals only, such as temperature and top_p, and latency is not hashed.
- **Cost if wrong:** a `NameError` when the models module imports. That breaks every import of `src.database.models`, so the whole suite fails to collect.

### Correction 2 (U-B2) — `ForeignKey` is not imported — BLOCKING (Task 0)
- **Evidence:** the same import block (`:7-24`) has only `ForeignKeyConstraint`. Every existing FK is a named `ForeignKeyConstraint` in `__table_args__`:
  - `GraphRelease` `:202-213`;
  - `GraphReleaseAgent` `:251-262`, including the composite role-compatible FK `fk_graph_release_agent_compatible_revision`;
  - `GraphDraft` `:282-287`;
  - `GraphDraftAgent` `:311-316`.

  The plan's DDL uses a column-level `ForeignKey(...)` six times (plan :83-96 and :171-179).
- **Ruling:** use the file's own style. Express every FK as a named `ForeignKeyConstraint(..., ondelete="RESTRICT")` in `__table_args__`, and do not import `ForeignKey`. This is required anyway for the composite FK in Correction 19.
- **Cost if wrong:** the same `NameError` collapse as Correction 1.

### Correction 3 (U-B3) — Task 1's sabotage target is in the first-boot method — BLOCKING (Task 1)
- **Evidence** (`src/services/graph_configuration_bootstrap.py`):
  - `bootstrap_v1` `:53-74` calls `_validate_current_graph` (`:121`) whenever a release exists (`:61-65`).
  - The ongoing AC1 guard is `:187-198`. It is a subset check `_EXPECTED_AGENT_KEYS.issubset(required_case_keys)` at `:195`. Its `raise GraphConfigurationIntegrityError(` is at **`:196`**, with the message `"active required Agent Test Cases do not cover every graph role"` at `:197`.
  - The plan's target `:353` is in `_insert_draft_and_cases` (`:290`). That runs only when no release exists, and checks equality against `REQUIRED_SMOKE_PAYLOADS` (`:341-355`).
  - The existing `tests/unit/test_graph_configuration_bootstrap.py:619-700` `test_existing_state_detects_corruption_across_complete_aggregate[required_case]` deactivates architect's case (`:679-683`). But it asserts only `pytest.raises(GraphConfigurationIntegrityError)`, with **no `match`** (`:696`).
- **Ruling:**
  - The Task 1 unit test uses the real SQLite `session_factory` fixture, as the existing test does, not a "faked session". It bootstraps, deactivates one role's only required case, and asserts `pytest.raises(GraphConfigurationIntegrityError, match="active required Agent Test Cases do not cover every graph role")`.
  - The **controller sabotage** deletes the `raise` at `:196-198`. Predicted RED: the new test returns a `BootstrapResult` instead of raising.
  - The **reviewer sabotage** is different: change `issubset` at `:195` to a check that one role's key is present. The new test must RED, because it removes a role other than the one kept.
  - The `match=` is mandatory, because any other integrity error would otherwise satisfy the test.
- **Cost if wrong:** a sabotage at `:353` stays GREEN, and the AC1 guard goes unproven.

### Correction 4 (U-A1) — `AgentInvocationIdentity` has seven fields — Advisory
- **Evidence:** `src/services/agent_runtime_identity.py:13-36` holds `graph_version`, `graph_release_id`, `agent_key`, `agent_definition_revision_id`, `content_hash`, `root_session_id: str = ""` and `actor_session_id: str = ""`. `grep test_run_id` finds nothing in `src/`. The log allowlist `_LOGGED_IDENTITY_FIELDS` is at `:123`.
- **Ruling:**
  - Replace the plan's "exactly five fields" (plan :371 and :448) with "seven; no `test_run_id`".
  - `run_candidate` passes `AgentAssemblyContext(design_system_active=<case>, root_session_id="", actor_session_id="")`, because a test run has no conversation. `_run_resolved` copies both into the identity (`agent_runtime.py:637-646`).
  - Do not add `test_run_id`: #262 is merged and chose not to.
- **Cost if wrong:** none at runtime. At worst an implementer could add a field #262 deliberately left out.

### Correction 5 (U-A2) — the plan's Global Constraints cite the first-boot guard as the AC1 guard — Advisory
- **Evidence:** as in Correction 3. Plan :18 cites `:341–355`, which is the first-boot equality check. The ongoing guard is `:187-198`.
- **Ruling:** AC1 is satisfied by both together:
  - seeding at `:311-326` (`name=f"{key}_required_smoke_v1"` `:314`, `is_required=True` `:317`, `synthetic_payload=REQUIRED_SMOKE_PAYLOADS[key]` `:318`, `assembly_context={"design_system_active": False}` `:319`);
  - the first-boot check at `:341-355`;
  - the every-boot check at `:187-198`.

  From #267 onward, AC1 must also be *kept*, by Correction 9.

### Correction 6 (U-A3) — Phase B gate SHAs are not ancestors — Advisory (binds at the Phase B gate)
- **Evidence** (probed at `c040dbde0`):
  - `cf9fa4c39` (#262): a commit, **not an ancestor**.
  - `ac69f62b6` (#264 "base"): a commit, **not an ancestor**, even though #264 is merged (`c040dbde0`).
  - `ce05e163e` (#265): an ancestor.
  - `ce10838ac` (#266): not an ancestor, which is expected.
  - `795262c16` (the plan's :487 pre-pass anchor, Merge #261): an ancestor.
- **Ruling:** the Phase B gate proves each predecessor by **content probes and the reviewed merge commits**, not by mid-PR SHAs:
  - #262: `root_session_id` and `actor_session_id` present, `test_run_id` absent.
  - #264: `AgentSchemaRegistry.compose` (`agent_schema_registry.py:451`) and `upgrade_draft_schema_contract` (`graph_configuration_draft.py:428`) present.
  - #265: `PromptAssembler.assemble` (`prompt_assembler.py:628`) is called from `_run_resolved` (`agent_runtime.py:599`).
  - #266: its local merge commit on `feat/langgraph-core` is an ancestor of HEAD, and `src/services/model_endpoint_catalog.py` exists.
- **Cost if wrong:** the gate refuses a correctly integrated head, or passes a head proved only by a stale SHA.

### Correction 7 (U-A4) — no publication method exists, and #269 owns it — Advisory
- **Evidence:** `grep "def publish|def publish_draft|def create_release|def commit_release" src/services/*.py` finds nothing at `c040dbde0`. #269's ledger ruling Q1 (`.worktrees/issue-269-plan/.superpowers/sdd/2026-09-25-graph-release-publication/progress.md:5`) gives #269 the publication transaction, evidence linking and the Review & Publish page.
- **Ruling:** see Correction 11. Neither #267 nor #268 writes publication code.

---

## 2. Binding carry-forwards

### Correction 8 — the test-run executor holds no transaction or lock across a model call — BLOCKING (Task 4, with a Phase B proof)
- **Source:** #269 PLAN-CORRECTIONS Correction 13 (I11) and plan-review-1 I11, read only.
- **Evidence:**
  - Plan :805-812 (`execute_candidate_run`): step 1 "Lock the singleton draft … (same lock pattern as draft write)", step 3 `run_candidate`, then step 6 "Insert … in the same transaction". That holds L0 across the model call.
  - The draft-write lock is `_lock_current_parents(exclusive=True)` (`graph_configuration_workbench.py:188-238`, `FOR UPDATE OF graph_release, graph_draft` at `:200-203`). Holding it blocks every conversation creation and publication for the whole model call.
  - Locking only the draft and then inserting a row whose FK takes `KEY SHARE` on `graph_release` takes draft → release. #269's reviewer probe measured that this **deadlocks** against publication's release → draft L0 statement.
  - Routes get a SQLAlchemy 2 autobegin session from `get_db`. As #266's Correction 13 showed, a `read_workbench` in the caller's implicit transaction holds FOR SHARE for the life of the request.
- **Ruling (binding):** `execute_candidate_run` and `execute_baseline_rerun` have this exact shape.
  1. **Precondition:** `session.in_transaction()` is False on entry. If it is True, raise `RuntimeError` (a programming error).
  2. **Transaction 1:** `with session.begin():`
     - `GraphConfiguration().read_workbench(session)` (FOR SHARE, `workbench.py:179-186`).
     - Load the `AgentTestCase` row.
     - Copy into plain frozen values: the selected role's draft `content` and `candidate_hash`, `draft.base_release_id`, the published `revision_id` and `content_hash`, the case `id`, `version`, `synthetic_payload` and `assembly_context`, and `active_release.release_id`.
     - Commit by leaving the block.
  3. **The model call** runs with **no open transaction**. Assert `not session.in_transaction()` immediately before it.
  4. **Transaction 2:** `with session.begin():`
     - `self._lock_current_parents(session, exclusive=False)` (release → draft, FOR SHARE).
     - Re-read the selected draft hash, and whether the case row is still active.
     - Insert the `AgentTestRun` with **the transaction-1 identity verbatim**, then flush.
  5. **Outcome when state moved between transactions 1 and 2:** the run is **still persisted**, because it records exactly what ran. The returned evidence carries `candidate_is_current: bool` (draft hash and active case both unchanged) and `base_release_is_current: bool`. They are computed in transaction 2 and are not persisted. This is the outcome #269 Correction 13 item 3 asks #267 to specify:
     - **publication-first:** the run records the transaction-1 `compared_release_id` (v1), and `base_release_is_current=False`;
     - **run-first:** the run records v1, and publication then proceeds.
  6. If transaction 2's `_lock_current_parents` raises `GraphConfigurationIntegrityError("graph configuration parent snapshot is inconsistent")`, because it was queued behind a committing publication, apply #269's one-retry pattern (#269 Task 2) once. Otherwise return 503. Never re-invoke the model.
- **Tests:**
  - **Unit (SQLite):** a fake adapter whose `invoke` asserts `not session.in_transaction()`. Controller sabotage: move the model call inside transaction 1, which must RED.
  - **PostgreSQL** (`test_agent_definition_workbench_postgres.py`):
    - With the fake adapter paused inside `invoke` (a threading.Event), assert that the executor's backend PID is not `idle in transaction` in `pg_stat_activity`, and holds no `pg_locks` row on `graph_release`, `graph_draft`, `agent_test_case` or `agent_test_run`.
    - While paused, a concurrent `save_editable_model_draft` commits unblocked. The run then persists the pre-save hash with `candidate_is_current=False`.
  - **Reviewer sabotage:** remove the transaction-1 commit (read under an implicit transaction), which must RED on the `pg_locks` assertion.
- **Cost if wrong:** production deadlocks between test runs and publication, or tens of seconds of stalled conversation creation and draft saves for every test run.

### Correction 9 — the case writer refuses to remove a role's last active required case (ordered 422) — BLOCKING (Task 2)
- **Source:** #269 ledger ruling (`progress.md:51`) and #269 Correction 1's carry-forward.
- **Evidence:**
  - `_validate_current_graph` raises at `graph_configuration_bootstrap.py:195-198` when any role lacks an active required case. `packages/databricks-tellr-app/databricks_tellr_app/run.py` turns any bootstrap exception into `SystemExit(1)` (`run.py:57-69`, re-verified: `raise SystemExit(1)` at `:69`).
  - The plan's `deactivate_test_case` (plan :283-289) and `update_test_case(is_required=...)` (plan :269-281) have no such guard.
- **Ruling:**
  - Every case write that could leave a role with zero active required cases is refused with **422** before any row changes:
    - `deactivate_test_case` of the last active required case;
    - `update_test_case(is_required=False)` on it;
    - any supersede (Correction 22) that would do the same.
  - The body is `{"code": "invalid_test_case", "issues": [{"field": "is_active" | "is_required", "code": "last_required_case", "message": ...}]}`. It is ordered by field in this order: `name`, `synthetic_payload`, `assembly_context`, `is_required`, `is_active`. Other validation issues from the same request come first, in that order, in the one 422.
  - **Locking (answers #269 Q9 for case writers):** the writer takes `SELECT … FROM agent_test_case WHERE agent_key = :k ORDER BY id FOR UPDATE`, **with no is_active filter**. It counts active required rows from the locked, re-read rows, then writes. That is L2 only. It takes no L0 and no remote call. Two concurrent retirements of a role's two required cases therefore serialize, and exactly one is refused.
- **Tests:**
  - A unit test for each of the three refusals, with exact body equality.
  - A PostgreSQL two-session test: cases A and B are architect's only two required cases. Deactivate A on one session and B on another. Assert that one commits and the other gets `last_required_case`, and that `bootstrap_v1` then returns `BootstrapResult(False, …)`.
  - **Sabotage:** drop `FOR UPDATE`, which must RED in the two-session test (both commit, and bootstrap raises).
- **Cost if wrong:** one admin click makes the next restart of every replica exit.

### Correction 10 — test runs hand the builder the production-filtered payload, and the seed is not edited — BLOCKING (Task 4; gated on the builder fix integrating)
- **Evidence:**
  - `src/services/graph_configuration_seed.py:23-41`, the builder smoke payload, still carries `session_id` (`:24`), `turn_id` (`:25`), `initiated_by` (`:26`) and `design_contract` (`:35`).
  - `git show fix/builder-owner-session-id:src/services/graph/nodes.py:2057-2069` defines `_BUILDER_MODEL_PAYLOAD_KEYS = frozenset({position, slide_spec, assumes, hands_off, resolved_data, section_html, section_css, resolved_style, design_system_active})`, and `builder_node` filters with it before `get_agent_runtime().run` (`:2110-2119` there).
  - At `c040dbde0`, `nodes.py` still passes `dict(payload)`. The fix branch is not an ancestor of HEAD.
  - `PromptAssembler` serializes the whole payload into the prompt (`tests/unit/test_agent_runtime.py:127-140`, `_expected_prompt` → `json.dumps(payload…)`). So an unfiltered test run would put `session_id` and `design_contract` into a builder prompt that production no longer sends.
- **Re-probe of the ledger's "bootstrap-hashed" claim:** it is **false as worded**.
  - Nothing hashes `synthetic_payload`. `grep synthetic_payload src` finds only the model column (`models :332`), the seed write (`bootstrap :318`) and the first-boot equality (`:350`).
  - The seed is **pinned**, by `tests/unit/test_graph_configuration_bootstrap.py:45` `EXPECTED_REQUIRED_SMOKE_PAYLOADS` and `:337-343`.
  - It is **first-boot-verified** (`:350-355`).
  - It is **already persisted** as rows in every bootstrapped database, and `_validate_current_graph` never re-reads payloads.
  - The conclusion stands for a different reason: editing the seed changes only fresh databases, and existing environments diverge.
- **Ruling:**
  1. #267 **does not edit** `graph_configuration_seed.py` or any persisted case row.
  2. **Gate:** `fix/builder-owner-session-id` must be reviewed and merged locally before #267 Task 4 dispatches. The Task 4 pre-brief re-probes `_BUILDER_MODEL_PAYLOAD_KEYS` at the integrated head.
  3. **One projection:** Task 4 promotes the allowlist into one public, import-light function, for example `src/services/agent_model_payload.py: model_payload_for(agent_key, payload) -> dict`. It returns the builder allowlist projection in payload order, and a shallow copy for every other role. `builder_node` and the test-run executor both call it. This is a small edit to `nodes.py`, which is shared with the fix branch; it lands after that branch.
     - The workbench must not import the private name from `nodes.py`, because that pulls in the graph module.
     - The runtime must not filter either. That would change `run`, which the pending fix does not do.
  4. **Evidence:** the persisted and displayed input is the **stored synthetic payload plus the projected model payload**. The Input view shows the projected one as "sent to the model".
  5. **Parity test:** with the fake adapter, the seeded builder case run through `execute_candidate_run` and the same payload through `builder_node` (the existing stub harness) produce **byte-identical assembled prompts**.
     - Controller sabotage: make the executor pass the unfiltered payload, which must RED.
     - Reviewer sabotage: add `"session_id"` to the allowlist, which must RED on a test asserting `"synthetic-builder" not in prompt`.
- **Cost if wrong:** approved evidence certifies a builder prompt that production never sends, and a session-shaped identifier leaks into a test prompt against the user's decision.

### Correction 11 — ownership: #269 owns publication, linking and the page; #268 owns readiness, verdicts and cleanup; the verdict DDL is #267's — BLOCKING (all tasks)
- **Evidence:**
  - #267's draft: Global Constraints :20 and DDL :123-160 put `verdict`, `verdict_reviewer`, `verdict_at` and `verdict_notes`, with their three pairing and eligibility checks, in #267.
  - #268's draft: :19 and :298 ("No DDL migration").
  - #269's draft: :80-82 consumes `AgentTestRun` and `GraphReleaseTestRun` from #267.
  - The handoff: `docs/superpowers/ISSUE-258-HANDOFF.md:159`.

  All four agree, so this is **confirmed**.
- **Conflict found inside #267's draft:**
  - The baseline rule (plan :787-789) reads `verdict = 'approved'`, but the no-scope list (:466) forbids verdict reads.
  - Task 5 (:849, :855) hides verdict fields from the response. That is consistent with #268 adding them.
- **Ruling:**
  - #267 builds no readiness query, verdict write, cleanup, publication step, `graph_release_test_run` insert, or Review & Publish UI. #267 owns only the **DDL** of `graph_release_test_run`.
  - The baseline rule is replaced by Correction 20, which reads no verdict.
  - #268's draft Tasks 5 and 6-step-4 are #269's (Q1). This is recorded here for #268's pre-pass and does not bind #267.
- **Cost if wrong:** two tickets build halves of one transaction, or #267 ships a verdict read it cannot test before #268.

### Correction 12 — run against a draft through the shared private path, never `run` — BLOCKING (Task 3)
- **Evidence:**
  - `AgentRuntime.run(agent_key, graph_release_id, payload, assembly_context)` (`agent_runtime.py:551-568`) resolves through `PersistedGraphReleaseLoader.resolve(graph_release_id, agent_key)`, which reads published releases only (`persisted_graph_release.py:98`). A draft is not a release.
  - The shared binding path is `_run_resolved(definition: ResolvedDefinition, payload, assembly_context)` (`:570-686`). Inside it:
    - `DefinitionContent` is revalidated (`:577`);
    - the v1-contract empty-overlay rule applies (`:583-589`, **conditional on schema contract v1**);
    - the bundle is resolved (`:590`);
    - `AgentSchemaRegistry.compose` runs (`:595-598`);
    - `PromptAssembler.assemble` runs (`:599-603`);
    - the identity is built (`:637-646`) and the adapter invoked inside the identity-sink callback (`:650-667`);
    - `validate_output` runs (`:664`), and latency is taken (`:668-670`).
  - `ResolvedDefinition` is at `persisted_graph_release.py:75-81`.
  - #266 Correction 11 (read only) confirms the same finding for its probe, and that `test_agent_runtime.py:435` (`count("with_structured_output(") == 1`) and the AST guard `:489-553` pin exactly one binding in `agent_runtime.py`.
  - The four-positional arity of `run` is pinned by `tests/unit/test_graph_nodes.py:222-233`.
  - The draft writer is `_GraphConfigurationDraft` (`graph_configuration_draft.py:242`), whose one locked writer is `_write_locked_content` (`:755-793`). It has two validator tuples: `local_candidate_validators` (`:250-253`) runs before the stale check, and `post_stale_validators` (`:256`, `()`) runs after it. It has four entry points:
    - `save_editable_model_draft` `:270`
    - `save_draft_content` `:331`
    - `upgrade_draft_protected_assembly` `:389`
    - `upgrade_draft_schema_contract` `:428` (#264)
- **Ruling:**
  - Add `AgentRuntime.run_candidate(agent_key, candidate_content, candidate_hash, payload, assembly_context)`. Its checks, in order:
    1. `agent_key in _MODEL_DRIVEN_AGENT_KEY_SET`, else `UnknownAgentKeyError`. This matches the fix branch's `run` (see Correction 14).
    2. `candidate_content.agent_key == agent_key`, else `ValueError`.
    3. `definition_content_hash(candidate_content) == candidate_hash` (`graph_definition_manifest.py:348`), else `ValueError("candidate_hash does not match candidate_content")`.
  - It then builds a `ResolvedDefinition` with the candidate sentinels (Correction 27) and returns `self._run_resolved(...)`.
  - `run`'s signature and body are untouched.
  - `run_candidate` does **not** run the draft writer's validator tuples. The candidate was already validated when saved, and `_run_resolved` revalidates the content and every contract. It never calls `_write_locked_content`.
  - There is no second `with_structured_output(`.
  - After #266 integrates, #266's structured-binding helper sits in `agent_runtime.py` below `DatabricksModelAdapter.invoke`'s catch (#266 Correction 11). `run_candidate` does not call it directly; it reaches the model only through `_run_resolved` → adapter.
  - Add an AST guard: `run_candidate` is called from exactly one module, `src/services/agent_test_workbench.py`, never from `src/services/graph/`. This is spec §7.1: "cannot be used by a production conversation".
- **Cost if wrong:** either a second invocation path that drifts from production, which violates AC10, or a draft masquerading as a release through `run`.

---

## 3. New corrections

### Correction 13 — the Phase A/B split is largely stale: #264 and #265 are integrated — BLOCKING (Task 3's brief; replaces Task 7)
- **Evidence:**
  - `_assemble_v1_prompt` does not exist (`grep` finds nothing in `src/`).
  - `_run_resolved` already assembles through `PromptAssembler` (`:599`) and composes through `AgentSchemaRegistry.compose` (`:595`). `compose` exists at `agent_schema_registry.py:451`, beside `identity_for` `:378`, `validate_overlay` `:389` and `validate_output` `:511`. The plan's "no compose_overlay" is true, but `compose` is the real method, and its cited lines `:358`/`:369` are stale.
  - The overlay restriction is `IncompatibleSchemaContractError("Schema contract version 1 requires an empty schema overlay")` (`:583-589`). It applies only to schema contract v1. #264's `upgrade_draft_schema_contract` makes v2 overlays reachable **now**, so the plan's "draft cannot carry overlays until #264" (:369, :728) is false.
  - `PromptAssembler.assemble` `:628`, `resolve_bundle` `:412` and `validate` `:428` still match the plan.
- **Ruling:**
  - Task 3's `run_candidate` is the final, generalized path.
  - **Task 7 is deleted.** Its checks become Task 3 tests: a v2-contract overlay candidate runs through `run_candidate` with the composed schema (the adapter receives `schema is not canonical` with `diagnostic_notes`, per `test_agent_runtime.py:108-121`), and a v1-contract candidate with an overlay maps to `assembly_error`.
  - Do not remove the v1-overlay check. It is correct, version-scoped behaviour.
- **Cost if wrong:** an implementer "lifts" a live, correct guard, or ships Phase A that fails on the first v2 draft.

### Correction 14 — `run_candidate` inherits the fix branch's unknown-role check — Advisory (Task 3, after the fix integrates)
- **Evidence:** `git diff c040dbde0...fix/builder-owner-session-id -- src/services/agent_runtime.py` adds `if agent_key not in _MODEL_DRIVEN_AGENT_KEY_SET: raise UnknownAgentKeyError(...)` at the top of `run`.
- **Ruling:** `run_candidate` performs the same check first (Correction 12 step 1). Test this with `"foreman"` and `"nope"`.
- **Cost if wrong:** asymmetric error types on the two public entry points.

### Correction 15 — raw output is not retained, and output-validation failures escape unclassified — BLOCKING (Tasks 3–4; AC5 and AC8)
- **Evidence:**
  - `AgentInvocationResult` is `output` plus `diagnostics` (`agent_runtime.py:202-205`). The provider's raw keys (`_supplied_output_keys`, `:502-512`) exist only inside `callback` (`:650-665`).
  - `AgentOutputValidationError` (`agent_schema_registry.py:338`, raised at `:521/:536/:563`) is caught by no `except` in `_run_resolved`, so it propagates through the identity sink.
  - Provider parse errors raised by `structured_model.invoke` (`:452-453`), such as a pydantic `ValidationError`, are not in the `provider_errors` tuple (`:425-443`), so they also propagate raw.
  - AC5 requires "raw and structured outputs" and AC8 requires failed runs to be persisted.
- **Ruling:**
  - Add a **private, keyword-only** `_raw_output_observer: Callable[[Mapping[str, Any]], None] | None = None` to `_run_resolved`. It is called with `_supplied_output_keys(provider_output)` immediately before `validate_output`.
  - `run` passes `None`, so production behaviour, error types and the four-argument arity are unchanged. `run_candidate` passes a recorder and returns `CandidateRunOutcome(result: AgentInvocationResult | None, raw_output: Mapping | None, error: BaseException | None)`. Alternatively it raises, with the workbench holding the recorder; the implementer chooses one, and the reviewer checks that `run` is byte-identical.
  - **Structured output** is `result.output.model_dump(mode="json")` merged with `diagnostics.additional_fields`.
  - **Raw output** is the observed keys, JSON-serialized.
  - Unit tests: an invalid-optional-field output persists the raw keys, with `execution_status='incomplete'`, `candidate_structured_output IS NULL` and the issue codes in the checks.
  - **Sabotage:** drop the observer call, which must RED.
- **Cost if wrong:** "failed" runs carry no evidence, and structurally invalid runs surface as unhandled 500s instead of persisted runs.

### Correction 16 — execution-status taxonomy and error mapping — BLOCKING (Task 4)
- **Evidence:** the plan's CHECK allows `completed | model_error | assembly_error | incomplete` (:133) but maps only two exception types (:796-797). `_run_resolved` turns every pre-invocation failure into `PersistedConfigurationUnavailableError(code=…)` (`:604-627`; codes at `persisted_graph_release.py:41-48`). An adapter failure becomes `PinnedInvocationEndpointError` (`:658-663`).
- **Ruling:** keep the four statuses. The mapping is exact:
  - **`completed`:** a validated result.
  - **`assembly_error`:** `PersistedConfigurationUnavailableError` with code `invalid_persisted_definition`, `protected_bundle_unavailable` or `schema_contract_unavailable`, or the `ValueError` from `run_candidate`'s own checks.
  - **`model_error`:** `PinnedInvocationEndpointError` or `ModelProviderUnavailableError`. `error_detail = "endpoint_unavailable:<endpoint_name>"`, which gives spec §15 its "clear endpoint error".
  - **`incomplete`:** `AgentOutputValidationError`, or a provider parse or validation exception.
  - **Any other `Exception`:** `model_error` with `error_detail="unexpected_error:<ExceptionClassName>"`, logged with its traceback server-side.
  - `error_detail` never stores exception text or provider payloads; it stores codes and class names only.
  - `lakebase_unavailable`, and a failure of transaction 1 or 2, do **not** persist a run. They return 503.
- **Cost if wrong:** unknown failures 500 instead of being persisted, or provider text (which can echo prompt content) is stored.

### Correction 17 — deterministic checks come from the runtime's single validation — BLOCKING (Task 4)
- **Evidence:** plan :781-783 defines `schema_valid`, `required_fields_present` and `closed_enums_valid` by re-validating with `schema.model_validate(raw_output)`. `_run_resolved` already validates every output through `validate_output` (`:664`). A `completed` run therefore passes all three by construction, and a second validation path could disagree with the first.
- **Ruling:**
  - `deterministic_check_results` is `[{"name": "output_contract", "passed": bool, "message": str | null, "issues": [{"code", "field"}…]}]`, derived from the runtime outcome:
    - pass when `completed`;
    - fail with `AgentOutputValidationError.issues` when `incomplete`;
    - a single failed `"execution"` check for `model_error` and `assembly_error`.
  - `deterministic_checks_passed` is True iff `execution_status == 'completed'` and every check passed.
  - There is no second `model_validate`.
  - Role-specific checks are Product question P4.
- **Cost if wrong:** tautological checks give false confidence, and two validators diverge.

### Correction 18 — token usage belongs to #267, not #266 — Advisory (Phase B Task 8)
- **Evidence:**
  - The plan (:50) says "#266 owns model invocation token-usage capture". But `grep -i "token|usage|include_raw"` over #266's plan (`.worktrees/issue-266-plan/docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`) finds no usage capture. Its only "token" hits are credential tokens.
  - `agent_runtime.py` has no usage capture. `with_structured_output(schema)` (`:452`) discards the message and its `usage_metadata`.
- **Ruling:**
  - #267 Task 8 owns token capture. Design it after #266 lands its structured-binding helper (#266 Task 5), and extend **that one helper** so there is still one `with_structured_output(`.
  - `input_tokens` and `output_tokens` stay nullable, and Phase A writes NULL.
  - The `AgentModelAdapter` protocol (`:212-220`) has many test doubles. Any widening is additive and optional, for example a side-channel usage observer mirroring Correction 15. No existing fake may need to change.
- **Cost if wrong:** Task 8 waits for work #266 will never do, or a second binding call breaks `test_agent_runtime.py:435`.

### Correction 19 — DDL corrections for `agent_test_run` and `graph_release_test_run` — BLOCKING (Task 0)
- **Evidence:**
  - Existing JSON documents use `_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")` (`models :34`), which `test_graph_configuration_models.py:176-186` pins for content tables.
  - Revision FKs are role-compatible through `(id, agent_key)` against `uq_agent_definition_revision_id_agent` (`:178-182`, used at `:257-262`).
  - Models are exported through `src/database/models/__init__.py:21-56`. The models module has no `__all__`, so plan :593 is wrong.
  - `test_graph_configuration_models.py` pins `EXPECTED_TABLES` (`:27-34`), `EXPECTED_CHECKS` and `len(foreign_keys) == 6` over those tables (`:202-209`). The plan's `compared_*` columns are "nullable — absent for v1 first-runs" (:92). But Graph V1 **has** a release and revisions; only its baseline *output* is absent.
- **Ruling (supersedes plan :72-191 where they differ):**
  - All JSON columns (`candidate_raw_output`, `candidate_structured_output`, `baseline_raw_output`, `baseline_structured_output`, `deterministic_check_results`) use `_JSON_DOCUMENT`.
  - `deterministic_check_results` is `nullable=False` with **no** server default, because the service always writes it. This drops the plan's `server_default="[]"`.
  - Add `run_kind = Column(String(24), nullable=False)` with `CheckConstraint("run_kind IN ('candidate', 'published_baseline')", name="ck_agent_test_run_run_kind")`.
  - Add `model_payload = Column(_JSON_DOCUMENT, nullable=False)`, the projected payload actually sent (Correction 10), and `assembled_prompt = Column(Text)`, nullable because it is absent on `assembly_error`. The Input view needs both (AC9).
  - `compared_release_id` and `compared_definition_revision_id` are **NOT NULL**. For a candidate run they are the draft's base release and that role's mapped revision. For a baseline run they are the active release and its revision, and `candidate_hash` equals that revision's `content_hash`.
  - FKs, all named `ForeignKeyConstraint` with `ondelete="RESTRICT"`:
    - `fk_agent_test_run_test_case` `(test_case_id) → agent_test_case.id`;
    - `fk_agent_test_run_release` `(compared_release_id) → graph_release.id`;
    - `fk_agent_test_run_compatible_revision` `(compared_definition_revision_id, agent_key) → agent_definition_revision(id, agent_key)`;
    - and the three `graph_release_test_run` FKs as named in the plan.
  - Case-to-run `agent_key` equality is enforced **in the service**, with a test. A composite FK would need a new unique constraint on the existing `agent_test_case` table, and `create_all` does not add it to existing databases. The plan also forbids existing-table changes (:19).
  - Add `CheckConstraint("execution_status <> 'completed' OR candidate_structured_output IS NOT NULL", name="ck_agent_test_run_completed_has_output")`.
  - Keep the plan's other checks. `ck_agent_test_run_approved_only_if_completed_and_passing` and the two verdict pairings are #268's and #269's contract; keep those names exactly.
  - Indexes: `Index("ix_agent_test_run_case_run_at", "test_case_id", "run_at")` and `Index("ix_graph_release_test_run_run", "agent_test_run_id")`, the latter for #268's `NOT EXISTS` and #269's trigger lookup. Never combine them with `index=True` on the same column.
  - Export `AgentTestRun` and `GraphReleaseTestRun` from `src/database/models/__init__.py`. Extend `EXPECTED_TABLES`, `ROLE_TABLES` (`agent_test_run` has an `agent_key` check), `EXPECTED_CHECKS`, the FK count (6 + 3 + 3 = **12**) and the timestamp list (`run_at`, `verdict_at`; `verdict_at` has no server default).
- **Cost if wrong:**
  - a plain JSON column on PostgreSQL where every sibling is JSONB;
  - a run pointing at another role's revision;
  - baselines indistinguishable from candidate runs;
  - the pinned models test going RED for the wrong reason.

### Correction 20 — the baseline rule — BLOCKING (Task 4)
- **Evidence:** plan :787-789 uses the "most recent row where `compared_release_id` = active release and `verdict = 'approved'`". Three problems:
  1. It reads a verdict (Correction 11), so in #267 the baseline is always absent.
  2. It would select approved *candidate* runs as "baseline", because they also carry `compared_release_id`.
  3. Keying on release discards a still-valid baseline for an unchanged role after every publication.
- **Ruling:**
  - The stored baseline shown beside a candidate run is the newest row with:
    - `run_kind = 'published_baseline'`;
    - `test_case_id = <this case version row>`;
    - `agent_key` matching;
    - `compared_definition_revision_id = <the base release's mapped revision for the role>`;
    - `execution_status = 'completed'`.

    Order by `run_at DESC, id DESC` and take one.
  - Its outputs are **copied** into the candidate row's `baseline_*` columns at insert time. This is spec §5.5, "candidate and stored-baseline raw/structured outputs". It is read in transaction 1, so the lock rules still hold.
  - No verdict is read. Whether a baseline must also be approved is Product question P1.
  - `execute_baseline_rerun` goes through `runtime.run(agent_key, active_release_id, payload, context)`, the real published path.
  - Its evidence stores the output in `candidate_*`. `run_kind='published_baseline'` and `candidate_hash` = the revision `content_hash`, and its own `baseline_*` are NULL.
  - With no row, the response and UI say "Baseline not recorded" (AC7), and checks still run.
- **Cost if wrong:** a candidate is compared against itself, or baselines silently vanish after each publication.

### Correction 21 — the Task 0 FK and delete tests would pass vacuously, and its sabotage breaks `create_all` — BLOCKING (Task 0)
- **Evidence:**
  - `src/core/database.py:935-1081` installs `BEFORE UPDATE OR DELETE` triggers on `graph_release` (`:1056-1066`), `graph_release_agent` and `agent_definition_revision` (`:1038-1054`). They raise `USING ERRCODE = '23514'` (`:969-971`, `:1030-1031`), which is `check_violation`, which SQLAlchemy raises as `IntegrityError`.
  - The plan's "delete a `graph_release` referenced by `graph_release_test_run` raises IntegrityError" (:583) is therefore GREEN with **no FK at all**. The existing `test_postgres_restricts_deletion_of_referenced_release_and_revision` (`test_graph_configuration_constraints_postgres.py:231-255`) already has this weakness. It is out of #267's scope, but note it for the whole-branch review.
  - The plan's sabotage (:603), "change the approved-only constraint to reference a different column name", makes `create_all` fail for every PostgreSQL fixture. That is RED for the wrong reason.
- **Ruling:**
  - FK tests assert **`exc.orig.pgcode == "23503"`** and `exc.orig.diag.constraint_name == "<fk name>"`.
    - Deleting a referenced `agent_test_case` goes through the real FK, because no trigger guards that table.
    - For deleting a linked `agent_test_run`, insert a `graph_release_test_run` row by raw SQL in the test only.
    - For the `graph_release` targets, assert through `pg_constraint`: `confdeltype = 'r'` for each named FK.
  - **Controller sabotage:** remove `AND deterministic_checks_passed` from the approved-only check. Predicted RED: only the "approved on a failing run" insert, with all other tests GREEN.
  - **Reviewer sabotage:** set `fk_agent_test_run_test_case` to `ondelete="CASCADE"`. Predicted RED: the unit restrictive-FK test and the 23503 PostgreSQL test.
- **Cost if wrong:** the RESTRICT that #268's cleanup and #269's retention depend on is never actually proved.

### Correction 22 — test-case versioning semantics — BLOCKING (Task 2)
- **Evidence:**
  - `uq_agent_test_case_agent_name_version` `(agent_key, name, version)` (`models :356-361`); there is no lineage column.
  - The plan's `update_test_case` inserts `version = max + 1` "for that name" (:678) but never retires the old row. Two **active** versions of one case would then both block readiness.
  - The plan allows `name` in an update (:274), which would start a new lineage at version 1.
  - The plan's "non-synthetic payloads missing the expected sentinel" (:656) names a sentinel that is defined nowhere.
- **Ruling:**
  - An update is a **supersede**, in one transaction under Correction 9's L2 lock: set the old row's `is_active=False` (and `updated_by`/`updated_at`), and insert the new row with `version = old.version + 1`, the same `name`, and `is_active=True`.
  - A concurrent supersede loses on the unique constraint, which maps to **409** `stale_test_case`.
  - `name` is the immutable lineage key, and a rename is 422 `name_immutable` (see P2). A new case with a new `name` starts at version 1.
  - A historical row is never modified except by its own retirement. Test this with an exact tuple comparison before and after.
  - **No sentinel.** Validation is:
    - `synthetic_payload` is a JSON object of at most 64 KiB serialized;
    - `assembly_context` is strictly `{"design_system_active": bool}` (`extra="forbid"`), because the runtime reads only that field (`agent_runtime.py:146-160`);
    - `name` is non-blank, trimmed, and at most 200 characters.
  - The synthetic-data warning is display only (spec §16; see P7).
  - Running a case requires the row to be active and `case.agent_key == path agent_key`. Otherwise return 409 `test_case_inactive` or 422 `test_case_role_mismatch`.
- **Cost if wrong:** readiness demands approvals for superseded versions, lineage is lost on rename, or a sentinel is invented.

### Correction 23 — routes stay in the one existing admin router — BLOCKING (Tasks 2 and 5)
- **Evidence:**
  - `router = APIRouter(prefix="/api/admin/agent-definitions", …, dependencies=[Depends(require_admin)])` (`src/api/routes/agent_definitions.py:51-55`). The plan's `/api/admin/agent-test-cases…` and `/api/admin/agent-test-runs/…` (:399-407) sit **outside** that prefix, so they would need a second router plus a `src/api/main.py` edit (`:484`), neither of which the plan lists.
  - `require_draft_write_principal` (`:58-66`) supplies the actor.
- **Ruling:** all #267 routes go on the existing router, which inherits `require_admin`:
  - `POST|GET /test-cases`
  - `PUT|DELETE /test-cases/{test_case_id}`
  - `GET /test-cases/{test_case_id}/runs?limit=`
  - `GET /test-runs/{run_id}`
  - `POST /draft/{agent_key}/test-runs`
  - `POST /published/{agent_key}/test-runs`

  Other rules:
  - Bodies are parsed inside the handler after authorization, as in the PUT (`:380-453`), with strict `extra="forbid"` DTOs that are new sibling classes (#266 c9).
  - Run bodies are exactly `{"test_case_id": int}`.
  - `run_by` and `actor` come from `require_draft_write_principal`.
  - Tests cover 403-before-parse for every new route.
  - **Consequence for #268:** its verdict route becomes `POST /api/admin/agent-definitions/test-runs/{run_id}/verdict`. #269 Task 8's use of `POST …/draft/{agent_key}/test-runs` is unchanged.
- **Cost if wrong:** a second router that can be registered without the admin dependency. Path churn in #268 before it exists is cheap.

### Correction 24 — evidence immutability is enforced in PostgreSQL — Advisory (Task 0; shares `database.py` with #269)
- **Evidence:** the plan enforces "immutable after insert" in service code only (:812). Every other immutable graph artifact has a trigger (`database.py:1038-1081`). #269 Correction 14 adds `reject_linked_agent_test_run_verdict_change` in the same `_install_graph_configuration_mutation_guards`.
- **Ruling:** add `trg_agent_test_run_evidence_immutable`, a `BEFORE UPDATE ON agent_test_run FOR EACH ROW` trigger. Its plpgsql body raises `23514` when any column other than the four verdict columns `IS DISTINCT FROM` its old value.
  - DELETE stays allowed, for #268's cleanup.
  - Use the idempotent `DROP TRIGGER IF EXISTS` / `CREATE OR REPLACE FUNCTION` pattern, and extend `test_postgres_mutation_guard_migration_is_idempotent_and_schema_objects_are_active` (`constraints_postgres.py:324`).
  - Hand #269 the verdict column list in its Task 0-B probe.
- **Cost if wrong:** evidence can be silently rewritten, so the approval gate certifies a mutable row.

### Correction 25 — the frontend's forbidden-action guard currently forbids "run" — BLOCKING (Task 6)
- **Evidence:**
  - `frontend/tests/fixtures/forbiddenActionNames.ts:18-19` is `/\brun\b|approve|reject|review\s*&\s*publish|publish|history|rollback/i`, shared by Vitest (`AgentDefinitionWorkbench.test.tsx:229-238`, `:371-378`) and Playwright (`agent-definition-workbench.spec.ts:1449-1464`, `:1466-1482`).
  - Both assert the text "Isolated testing is not available in this release." (`test.tsx:377`, `spec.ts:1482`).
  - The right pane already exists as `<aside aria-label="Isolated testing">` (`AgentDefinitionWorkbench.tsx:139-144`).
  - `DraftStatus` is already `'Clean' | 'Unsaved' | 'Needs test'` (`draftEditorState.ts:23`).
  - #269 also edits `forbiddenActionNames.ts` and `spec.ts:1462` (its plan :887-888).
- **Ruling:**
  - Task 6 removes **only** the `\brun\b` stem, and adds exact exempt names for the controls it renders: `"Run test case"` and `"Run published baseline"`. The second contains "publish", so it needs an exemption by name, following the existing mechanism (`:28-41`).
  - `approve`, `reject`, `publish`, `history` and `rollback` stay forbidden: those are #268's, #269's and #270's.
  - Replace the "not available" assertions with the new panel's assertions, and update `ALLOWED_ACTION_NAMES` `toHaveLength(3)` (`spec.ts:1462`) to 5.
  - Mount the panel in the existing `<aside>`. Do not add a new column.
  - Do not add a `DraftStatus` value: that is #268's.
- **Cost if wrong:** every existing workbench test goes RED on the new Run button, or the guard gets weakened wholesale.

### Correction 26 — where the fake adapter lives — Advisory (Task 3)
- **Evidence:** the plan offers `tests/fake_adapters.py` or `src/services/testing/…` (:375, :720). `tests/unit/test_agent_runtime.py:59-106` already has `RecordingModelAdapter` and `VALID_OUTPUT_VALUES` for all seven roles (`deck_reviewer: {}`). `tests/fixtures/` is a package that integration tests already import (`tests/fixtures/__init__.py`).
- **Ruling:**
  - Create `tests/fixtures/deterministic_model_adapter.py` holding `DeterministicFakeModelAdapter`, plus `FAKE_OUTPUTS`, moved from `VALID_OUTPUT_VALUES`, which `test_agent_runtime.py` then imports.
  - It records `(agent_key, schema, prompt)`. It has modes for success, provider unavailable, invalid optional field, and pause-on-event (for Correction 8).
  - Never put it in `src/`.
  - Record this location for #269's Task 0-B probe.
- **Cost if wrong:** a test double ships in the product, or two fixture tables drift.

### Correction 27 — sentinel identity for candidate runs — Advisory (Task 3)
- **Evidence:**
  - The identity is built from `ResolvedDefinition` (`:637-646`).
  - `diagnostics.definition_version = definition.agent_definition_revision_id` (`:676`), a pre-existing naming quirk, so a candidate reports `-1` there.
  - `PinnedInvocationEndpointError` carries `graph_release_id` (`:658-663`).
  - `LoggingAgentInvocationIdentitySink` logs the allowlisted fields (`agent_runtime_identity.py:123-140`).
- **Ruling:**
  - Keep the plan's sentinels (`-1`). Define them in `src/services/agent_runtime.py` next to `run_candidate`, because they are runtime identity and not loader state. Do not put them in `persisted_graph_release.py` as plan :361 says.
  - The evidence row records identity from the workbench's transaction-1 snapshot, never from `diagnostics.definition_version`.
  - A unit test asserts the recording sink's identity is `(-1, -1, agent_key, -1, candidate_hash, "", "")`.
  - `run(-1, …)` must still raise `GraphReleaseNotFoundError`. Test that too.
- **Cost if wrong:** misleading version numbers stored as evidence.

### Correction 28 — the pre-pass paths and the cause-baseline file list — Advisory
- **Evidence:**
  - The plan writes `.superpowers/issue-267-plan-corrections.md` and `.superpowers/issue-267/IMPLEMENTATION_BASE` (:3, :478-486). Its focused list (:524-536) omits `test_graph_configuration_draft.py`, `test_graph_nodes.py` (the arity and binding guards), `test_ci_collects_integration_tests.py`, and the PostgreSQL overlay and runtime-failure suites the runtime change touches.
  - The plan's repo-wide pre-pass grep for `run_candidate` hits `_run_candidate_validators` (`graph_configuration_draft.py:258`). Scope the grep to `def run_candidate` in `agent_runtime.py`.
- **Ruling:**
  - This file and `progress.md` replace those paths.
  - `IMPLEMENTATION_BASE` is the local integration head that contains the reviewed #266 merge **and** the builder fix, recorded at Task 1 dispatch. It is not `c040dbde0`.
  - The focused matrix is the one in §6.

---

## 4. Per-task internal consistency (plan task vs itself and the code)

| Task | Plan says | Inconsistency / defect | Correction |
|---|---|---|---|
| 0 | Append DDL; `__all__`; column-name sabotage; delete tests | `Float`/`ForeignKey` imports; no `__all__` in module; sabotage breaks `create_all`; `graph_release` delete test vacuous (23514 trigger); plain `JSON`; nullable `compared_*`; no `run_kind`; FK count test pinned at 6 | 1, 2, 19, 21, 24 |
| 1 | Fake session; sabotage `:353` | first-boot method; existing test has no `match`; real SQLite fixture exists | 3, 5 |
| 2 | CRUD with "sentinel"; update keeps old row active; rename allowed; routes outside prefix | undefined sentinel; two active versions; lineage loss; no last-required guard; second router + `main.py` not listed | 9, 22, 23 |
| 3 | Phase A v1 path; sentinels in loader module; fake location ambiguous; "do not relax v1 overlay check" | assembler/registry already integrated; v2 overlays reachable now; unknown-role parity; raw output lost; no call-site guard | 12, 13, 14, 15, 26, 27 |
| 4 | Lock draft → model → insert same txn; approved-verdict baseline; re-validating checks; "catch AgentRuntimeError" | lock across model call (deadlock/stall); verdict read vs no-scope; candidate rows pick themselves as baseline; tautological checks; `AgentOutputValidationError` is not an `AgentRuntimeError`; unfiltered builder payload | 8, 10, 15, 16, 17, 20 |
| 5 | Routes under `/api/admin/agent-test-runs`; verdict fields absent | prefix; otherwise consistent with #268 | 23 |
| 6 | New right-pane panels; `executeTestRun(agentKey, testCaseId, isCandidateRun)` | forbidden-action guard REDs every test on "Run"; pane exists as `<aside>`; `DraftStatus` untouched | 25 |
| 7 (B) | Remove v1 assembly/overlay guards | obsolete — both integrated; overlay guard is correct v1-scoped behaviour | 13 (Task deleted) |
| 8 (B) | tokens from #266 | #266 does not capture usage | 18 |
| 9 (B) | E2E generalized path | stands; add parity test from 10 and PG lock proof from 8 | 8, 10 |

## 5. Producer/consumer rows (every task pair that shares an interface)

| Producer → Consumer | Interface | Status / binding correction |
|---|---|---|
| 0 → 1 | none (Task 1 is bootstrap-only) | independent; sequence by file (`test_graph_configuration_bootstrap*.py` untouched by 0) |
| 0 → 2 | `AgentTestCase` unchanged; `src/database/models/__init__.py` exports | 19 |
| 0 → 3 | none | independent (3 touches runtime only) |
| 0 → 4 | `AgentTestRun` columns incl. `run_kind`, `model_payload`, `assembled_prompt`, NOT NULL `compared_*`, `_JSON_DOCUMENT` | 19, 20 |
| 0 → 5 | column set serialized (verdict excluded) | 11, 19 |
| 0 → 6 | wire fields via 5 only | — |
| 1 → others | none | — |
| 2 → 4 | `TestCaseVersion`; active-row rule; `assembly_context` shape `{design_system_active}` | 22 |
| 2 → 5 | router + DTO style + `_parse_*` helpers on the same router | 23 |
| 2 → 6 | `GET /test-cases?agent_key=&include_inactive=` list shape | 23 |
| 3 → 4 | `run_candidate(agent_key, content, hash, payload, ctx)` + raw observer outcome; `DeterministicFakeModelAdapter` in `tests/fixtures/` | 12, 15, 26 |
| 3 → 5 | route dependency builds workbench with `get_agent_runtime()` | 12 |
| 4 → 5 | `TestRunEvidence` + `candidate_is_current`, `base_release_is_current`; status taxonomy; 503 cases | 8, 16 |
| 4 → 6 | baseline "not recorded" semantics; projected payload + assembled prompt for Input view | 10, 19, 20 |
| 5 → 6 | exact paths under `/api/admin/agent-definitions/…` | 23 |
| 3/4 → 8 | adapter usage side channel on #266's helper | 18 |
| #267 → #268 | DDL (verdict cols + checks), `run_kind`, route path for verdict, `TestRunEvidenceResponse` extension point | 11, 19, 23 — #268 readiness should filter `run_kind='candidate'` (recommend; #268's call) |
| #267 → #269 | `GraphReleaseTestRun` DDL; run-executor two-txn shape; case-writer L2-only lock (Q9); fake location; verdict column list for trigger | 8, 9, 19, 24, 26 |
| #266 → #267 | extracted structured-binding helper in `agent_runtime.py`; `GraphConfiguration(*, remote_endpoint_validator=None)` ctor; possible aside/probe UI | 12, 18; re-probe at Task 1 dispatch |
| builder-fix → #267 | `_BUILDER_MODEL_PAYLOAD_KEYS`; `run` unknown-role check | 10, 14 — gate Task 4 |

## 6. Files #267 shares with #264, #265, #266 or #269

The #264 and #265 sets are measured with `git diff --name-only` over their merge commits (`c040dbde0^1..c040dbde0`, `3ed8f9b6a^1..3ed8f9b6a`). The #266 set comes from `c040dbde0...plan/model-discovery-266` plus its plan's Files lists. The #269 set comes from its plan's Files lists (read only).

| File | #267 task | #264 | #265 | #266 | #269 | Rule |
|---|---|---|---|---|---|---|
| `src/database/models/graph_configuration.py` | 0 | — | — | — | consumes | append-only |
| `src/database/models/__init__.py` | 0 | — | — | — | — | exports |
| `src/core/database.py` | 0 (C24) | — | — | — | Task 4 trigger | same function; #267 lands first, #269 rebases |
| `src/services/agent_runtime.py` | 3, 8 | ✓ | ✓ | Task 5 helper | — | after #266 merge; one binding call; `run` byte-identical |
| `src/services/graph/nodes.py` | 4 (C10 helper call) | ✓(tests) | ✓(tests) | — | — | after builder fix |
| `src/services/graph_configuration.py` | read-only (compose facade) | — | ✓ | Task 2 ctor | Task 1-4 | do not modify |
| `src/services/graph_configuration_draft.py` | read-only | ✓ | ✓ | Task 2 | Task 1 (`:754-793`) | do not modify |
| `src/services/graph_configuration_workbench.py` | read-only (`read_workbench`, `_lock_current_parents`) | — | — | — | Task 2 retry | consume #269's retry if landed, else own one retry (C8.6) |
| `src/services/graph_configuration_bootstrap.py` | read-only | — | — | — | Task 2 C2 lock | do not modify |
| `src/api/routes/agent_definitions.py` | 2, 5 | ✓ | ✓ | Tasks 3, 5 | — | append routes; keep overlay prefix catch `:409-418` |
| `src/api/schemas/agent_definitions.py` | 2, 5 | ✓ | ✓ | Tasks 3, 5 | — | sibling DTOs only |
| `tests/unit/test_agent_runtime.py` | 3 | ✓ | ✓ | Task 5 | — | keep `:435` and AST guard |
| `tests/unit/test_persisted_agent_runtime.py` | 3 | ✓ | ✓ | — | — | — |
| `tests/unit/test_graph_nodes.py` | 4 (parity) | ✓ | ✓ | — | — | after builder fix |
| `tests/unit/test_graph_configuration_models.py` | 0 | — | — | — | — | — |
| `tests/unit/test_graph_configuration_bootstrap.py` | 1 | ✓ | — | — | (SQLite matrix) | — |
| `tests/unit/test_agent_definition_workbench_routes.py` | 2, 5 | ✓ | ✓ | Tasks 3, 5 | — | `_app_for` fakes (#266 c7) |
| `tests/unit/test_ci_collects_integration_tests.py`, `.github/workflows/test.yml` | only if new PG file | ✓ | — | maybe | Tasks 1-4 | no new PG file planned |
| `tests/integration/test_graph_configuration_constraints_postgres.py` | 0 | — | — | — | Task 4 (C14) | append |
| `tests/integration/test_graph_configuration_bootstrap_postgres.py` | 1 | — | — | — | Task 2 | append |
| `tests/integration/test_agent_definition_workbench_postgres.py` | 2, 4 | — | ✓ | Tasks 2, 5 | — | append |
| `frontend/src/api/agentDefinitions.ts` | 6 | ✓ | — | Tasks 4, 6 | Task 6 | append clients |
| `frontend/.../AgentDefinitionWorkbench.tsx` (+`.test.tsx`) | 6 | ✓ | ✓ | Tasks 4, 6 | `:31-48` | mount in `<aside>` only |
| `frontend/.../draftEditorState.ts` | none (read) | ✓ | ✓ | Task 4 | — | no `DraftStatus` change |
| `frontend/tests/fixtures/forbiddenActionNames.ts` | 6 | — | ✓ | — | Task 7 | C25 |
| `frontend/tests/fixtures/mocks.ts`, `tests/e2e/agent-definition-workbench.spec.ts` | 6 | ✓ | ✓ | Tasks 4, 6 | `:1462` | route mocks by URL (#266 c17) |

---

## 7. Cause baseline at `c040dbde0`

Environment: `PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest` (Python 3.11.0). `databricks_tellr` resolved to the worktree's own copy. `test ! -e .venv` held before and after. Nothing was installed. No frontend was run, and port 3000 was not used.

**Full unit suite** (`tests/unit -q -p no:randomly -rf`): **6 failed, 5881 passed, 110 skipped, 135 warnings** (405 s). The failures are exactly the known set:
1. `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available`: `:124 assert 'provisioned' == 'autoscaling'`.
2. `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails`: `:152 Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
3. `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict`: `AttributeError: '_FakeSession' object has no attribute 'execute'`.
4. `…::test_create_session_still_stores_a_single_authority_config_unchanged`: the same cause.
5. `…::test_create_session_still_accepts_no_agent_config`: the same cause.
6. `test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session`: `ConversationGraphReleaseIntegrityError("no active Graph Release")`.

There are zero failures outside this set, and none is in #267's matrix. The skip count matches #266's recorded 110.

**Focused unit matrix:** **724 passed, 0 failed, 0 skipped** (one invocation):
- `test_graph_definition_manifest` 101
- `test_graph_configuration_models` 8
- `test_graph_configuration_bootstrap` 19
- `test_graph_definition_content_mapping` 16
- `test_agent_definition_workbench_routes` 164
- `test_agent_runtime` 31
- `test_persisted_agent_runtime` 108
- `test_graph_configuration_draft` 121
- `test_ci_collects_integration_tests` 14
- `test_graph_nodes` 142

**PostgreSQL** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, one invocation per file, **zero skips in every file**; the fixtures own throwaway databases, and `ai_slide_generator` was not touched):
- `test_graph_configuration_bootstrap_postgres` 2 passed
- `test_graph_configuration_constraints_postgres` 7 passed
- `test_agent_definition_workbench_postgres` 15 passed
- `test_agent_schema_overlay_postgres` 10 passed
- `test_persisted_graph_runtime_failures_postgres` 7 passed

**Frontend:** not run (brief). Task 1's dispatch pre-pass records `npm run test:unit`/`typecheck` causes at the post-#266 head. #266 recorded 333 Vitest and 60 Playwright workbench tests at its own head.

**Re-derive** this baseline at the post-#266 plus builder-fix head, before Task 1 (Correction 28). Compare by node ID and cause. A new failure, skip or warning location is a regression even when the count matches. Task 0 changes the ORM, so re-derive after it too.

## 8. Pre-briefs: the known defects each task must be dispatched against

- **Task 0:** 1, 2, 19 (all bullets), 21 (the 23503 assertions, the pg_constraint check, and both sabotages), 24. Also: no `index=True` together with an explicit `Index`. Export from `src/database/models/__init__.py`. Update `EXPECTED_TABLES`, the checks, the FK count (12) and the timestamp lists.
- **Task 1:** 3 (the SQLite fixture, `match=`, controller at `:196-198`, reviewer at `:195`), 5.
- **Task 2:** 9 (the ordered 422 and the L2 `FOR UPDATE` without an is_active filter, plus the two-session PostgreSQL test and its sabotage), 22 (supersede, immutable name, no sentinel, strict `assembly_context`), 23 (one router, parse after authorization, principal as actor).
- **Task 3:** 12 (check order, `_run_resolved`, one binding, the call-site AST guard, `run` byte-identical), 13 (Task 7 deleted; v2 overlay test; keep the v1 guard), 14, 15 (the private observer), 26, 27.
- **Task 4:** 8 (two transactions; `in_transaction` asserts; the paused-adapter `pg_locks` proof; the moved-state outcome; one retry), 10 (the builder-fix gate, the shared projection, prompt parity and its two sabotages), 15, 16 (the exact mapping and no exception text), 17, 20 (the baseline predicate and copy; baseline rerun through `run`).
- **Task 5:** 11 (verdict fields excluded), 16 (503 and 409 cases), 23.
- **Task 6:** 25 (guard narrowing, exempt names, length 5, mount in `<aside>`), 10 (show the projected payload), 20 ("Baseline not recorded"). Route mocks by URL (#266 c17).
- **Task 8:** 18.

Sabotage assignment: the controller and reviewer targets named above differ for every task. Tell the reviewer which ones the controller already ran.

## 9. Rulings on plan-versus-code conflicts, with the cost if wrong

| # | Conflict | Ruling | Cost if wrong |
|---|---|---|---|
| 1, 2 | DDL imports | `Float` import; `ForeignKeyConstraint` style | suite import collapse |
| 3, 5 | guard location | `:196`, `match=` | vacuous AC1 proof |
| 8 | lock across model call | two txns, persist verbatim + currency flags | deadlock / stalls |
| 9 | last required case | ordered 422, L2 lock | boot exit |
| 10 | builder payload | shared projection; seed untouched; gated | evidence for a prompt production never sends |
| 11 | verdict read in baseline | removed | untestable baseline; scope bleed |
| 12, 13 | draft vs release; stale Phase B | `run_candidate` → `_run_resolved`; Task 7 deleted | drift from production; lifting a correct guard |
| 15, 16, 17 | raw output, error mapping, checks | observer; exact taxonomy; single validation | unpersisted failures; leaked provider text; tautological checks |
| 18 | token owner | #267 Task 8 on #266's helper | Task 8 blocked forever |
| 19, 20 | DDL shape; baseline predicate | `run_kind`, JSONB, composite FK, NOT NULL compared; revision-keyed baseline | self-comparison; cross-role FK |
| 21 | vacuous FK tests | 23503 + pg_constraint | RESTRICT unproven |
| 22 | versioning | supersede, immutable name | double-active cases |
| 23 | route prefix | one router | an unguarded second router |
| 24 | immutability | PostgreSQL trigger | mutable evidence |
| 25 | forbidden "run" | narrow by one stem plus exemptions | suite-wide RED, or a weakened guard |

## 10. Product-owner questions (asked, not decided)

- **P1.** Must a published-baseline run be **approved** (#268) before it is shown as the stored baseline? Spec §11.2 says "stored approved output". AC7 says "baseline not recorded until an administrator *runs* it". This file currently shows the newest completed baseline run without approval.
- **P2.** Is a test case's `name` its immutable identity, or do admins need an editable display name separate from the lineage key?
- **P3.** To replace a role's only required case, is "add the new case, then retire the old one" acceptable, or is a single "swap" operation wanted?
- **P4.** Beyond the runtime's schema validation, which role-specific deterministic checks, if any, should gate approval? For example, the builder's echoed `position` matching the input.
- **P5.** Should admins be able to run a superseded (inactive) case version to reproduce old evidence, or only active versions?
- **P6.** Production still sends `session_id` to the architect, data-analyst and deck-reviewer models (`nodes.py:1461`, `:1864`, `:2973`). Should they get the same "nothing session-specific reaches the model" treatment as the builder? This decides what their smoke cases should contain.
- **P7.** Is the synthetic-data rule a UI warning only (spec §16), or should the server reject payloads by some rule, such as size or forbidden key names?
- **P8.** Should concurrent or repeated live test runs be limited per admin or per role, for model cost and latency? Nothing in the spec bounds them.
- **P9.** When a model endpoint reports no token usage, is NULL acceptable evidence, or must the run be marked incomplete?

## 11. GO/NO-GO for Task 1 once #266 integrates

**Conditional GO.** Task 1 is test-only and bootstrap-only. It depends on nothing here except Correction 3, so it may dispatch as soon as all of the following hold:
1. #266's reviewed local merge is on `feat/langgraph-core`, and this branch is rebased onto it.
2. `IMPLEMENTATION_BASE` is recorded.
3. §7's baseline is re-derived by cause with no new cause.
4. Corrections 3, 12, 15 and 23 are re-probed against #266's final `agent_runtime.py`, routes and `graph_configuration.py`.

Task 0 has no external gate beyond those four. **Task 4 is NO-GO** until `fix/builder-owner-session-id` is reviewed and merged locally (Correction 10). Phase B Task 8 waits for #266's helper (Correction 18).

---

## 12. Conditional-GO discharge at `e91fcd856` (2026-09-26)

Every line number in this section was measured at the rebased HEAD (`c7cb587c7`, whose code equals `e91fcd856`). Where §1–§11 cite an older line, this section wins. Each item is **CONFIRMED** (the earlier correction stands, sometimes with refreshed lines), **CORRECTED** (the earlier ruling changes) or **NEW DEFECT** (the plan or an earlier correction missed it).

### Correction 29 — `IMPLEMENTATION_BASE=e91fcd856`, and the rebase — CONFIRMED — BLOCKING (all tasks)
- **Evidence:**
  - Triple check (`git status --porcelain`, `git diff HEAD`, `git diff --cached`) was empty. Backup tag `backup/267-pre-rebase-e06f78241`.
  - `git rebase --onto e91fcd856 c040dbde0 feat/agent-test-case-runs-267` took `e06f78241` to `c7cb587c7`. `git range-diff c040dbde0..backup/267-pre-rebase-e06f78241 e91fcd856..HEAD` shows `1: e6bb42ff0 = 1: ac1168242` and `2: e06f78241 = 2: c7cb587c7`. `git rev-list --count HEAD..e91fcd856` is 0. The name-only diff is the same two ledger files before and after.
  - `6cbab388a`, `50c8cbf35`, `e91fcd856` and `c040dbde0` are all ancestors of HEAD. `src/services/model_endpoint_catalog.py` exists.
- **Ruling:**
  - `IMPLEMENTATION_BASE=e91fcd856`. This replaces Correction 28's "recorded at Task 1 dispatch" placeholder.
  - Correction 6's Phase B gate for #266 is now met: #266's merge is an ancestor, and the catalog module exists.
  - Correction 10's Task 4 gate is now met (see Correction 37). No external gate is left on any #267 task. Phase B Task 8's dependency on #266's helper is also met (see Correction 31).
- **Unchanged since `c040dbde0`:** `git diff --quiet c040dbde0 e91fcd856` is clean for these paths:
  - `graph_configuration_bootstrap.py` and its unit test
  - `graph_configuration_seed.py`
  - `graph_configuration_workbench.py`
  - `src/database/`
  - `src/core/database.py`
  - `agent_schema_registry.py`
  - `prompt_assembler.py`
  - `agent_runtime_identity.py`
  - `persisted_graph_release.py`
  - `frontend/tests/fixtures/forbiddenActionNames.ts`

  So Corrections 1, 2, 4, 19, 21, 22 and 24 keep their line citations.

### Correction 30 — re-probe of Correction 3 (the Task 1 guard) — CONFIRMED — BLOCKING (Task 1)
- **Evidence:** the bootstrap module and its test are byte-unchanged (Correction 29). `graph_configuration_bootstrap.py:187-198` is still the every-boot guard:
  - the subset check `_EXPECTED_AGENT_KEYS.issubset(required_case_keys)` is at `:195`;
  - `raise GraphConfigurationIntegrityError(` is at `:196`;
  - the message `"active required Agent Test Cases do not cover every graph role"` is at `:197`.

  #266 touched nothing on this path.
- **Ruling:** Correction 3 stands verbatim: the real SQLite `session_factory`, the mandatory `match=`, the controller sabotage deleting `:196-198`, and the reviewer sabotage at `:195`.

### Correction 31 — re-probe of Correction 12 (`run_candidate` through `_run_resolved`) against #266's runtime — CONFIRMED, with refreshed lines — BLOCKING (Task 3)
- **Evidence** (`src/services/agent_runtime.py`):
  - **`run` (`:593-619`):**
    - It now begins with `if agent_key not in _MODEL_DRIVEN_AGENT_KEY_SET: raise UnknownAgentKeyError(...)` at `:604-608`, before the loader. So Correction 14 is integrated, not pending.
    - The loader error mapping is at `:609-619`.
    - The four-positional arity is still pinned by `tests/unit/test_graph_nodes.py:222` (`test_every_production_runtime_call_passes_all_four_pinned_arguments`).
  - **`_run_resolved` (`:621-731`):**
    - content revalidation `:628`;
    - the v1-overlay guard `:634-641`;
    - `compose` `:646`;
    - `assemble` `:649`;
    - `configuration = saved_model_configuration(content.model)` `:681` (new with #266);
    - identity `:683-694`;
    - `callback` `:696-713`, with the adapter at `:698` and `PinnedInvocationEndpointError` at `:705`;
    - `validate_output` `:710`;
    - the sink `:715`;
    - latency `:716`.
  - **#266's helpers:**
    - `saved_model_configuration` is at `:391-402`.
    - `bind_structured_output_model` is at `:405-431`. It contains the one `with_structured_output(` in `src/` (`:431`; `grep -rn` finds no other).
    - `DatabricksModelAdapter.invoke` (`:458-503`) binds through the helper at `:489-494` inside its `provider_errors` catch (`:469-487`, `:496-503`).
  - **Pins that now include the probe module:**
    - `test_agent_runtime.py:435` (count == 1);
    - the AST guard `:489-553`;
    - `:751-780` `test_structured_output_binding_has_one_call_site_and_the_probe_has_none`;
    - `:645-677`, which pins the runtime adapter's exact `model_factory` kwargs: no `timeout` and no `max_retries`.
- **Ruling:**
  - Correction 12 stands: `run_candidate` → `_run_resolved`, with the same three checks in order, the `-1` sentinels (Correction 27) and `run` byte-identical.
  - `run_candidate` reaches #266's helper only transitively, through the adapter. It calls neither `bind_structured_output_model` nor `saved_model_configuration` itself, because `_run_resolved` `:681` already does the conversion.
  - The Correction 12 AST guard is extended. `src/services/agent_test_workbench.py` must contain no `with_structured_output`, no `bind_structured_output_model(` and no `ChatDatabricks`. Mirror `:751-780`.
- **Phase B Task 8 (Correction 18):** the helper now exists. Usage capture extends `bind_structured_output_model` or the adapter around it, and must keep `:431` the only binding and `:645-677`'s kwargs unchanged for the production adapter.

### Correction 32 — the executor's candidate read reuses #266's probe read path; it does not build a parallel one — CORRECTED (Corrections 8 and 23) — BLOCKING (Task 4)
- **Evidence:**
  - `read_draft_probe_candidate` (`graph_configuration_draft.py:605-642`) is exactly Correction 8's transaction-1 pattern. In order it:
    1. validates the lock and agent key before any transaction (`:621`, `_validate_lock_and_agent_key` `:702-708` over `_lock_and_agent_key_issues` `:710-738`);
    2. runs `with session.begin(): read_workbench → _draft_aggregate_snapshot` (`:622-624`);
    3. returns the null-candidate `DraftSaveConflict` on a stale lock (`:625-631`);
    4. copies into a frozen value (`:632-638`);
    5. leaves the transaction;
    6. re-checks the stored endpoint name against `_endpoint_name_policy_validator` after the locks are released (`:639-641`), so a URL- or path-shaped stored name never reaches a provider.
  - #266 proves the lock release in PostgreSQL (`test_agent_definition_workbench_postgres.py:1683` `test_model_endpoint_probe_holds_no_lock_while_the_model_call_is_in_flight`, which reads `pg_locks` and `pg_stat_activity` at `:1767-1771`).
  - It **cannot be called as-is**. `DraftProbeCandidate` (`:95-107`) carries only `agent_key`, `lock_version`, `candidate_hash` and `model`. The executor also needs the full `DefinitionContent`, `draft.base_release_id`, the role's `base_revision_id` and the published `revision_id`/`content_hash`. All of these are on `GraphWorkbenchSnapshot` (`graph_configuration_workbench.py:40-138`).
- **Ruling:**
  - **Do not widen `DraftProbeCandidate`,** and do not change `read_draft_probe_candidate`'s signature or return type. They are #266's pinned contract.
  - Task 4 extracts the probe method's body into one private helper on `_GraphConfigurationDraft`, which returns the post-transaction copy (snapshot-derived values) or the conflict:
    - the lock and agent-key check;
    - the `session.begin()` read of `read_workbench` plus the aggregate;
    - the stale-lock conflict;
    - the post-release endpoint-policy re-check.
  - `read_draft_probe_candidate` becomes a projection of that helper, with its behaviour unchanged.
  - Add a public sibling, `read_draft_test_candidate(session, *, agent_key, expected_lock_version) -> DraftTestCandidate | DraftSaveConflict[None]`. `DraftTestCandidate` is frozen: `agent_key`, `lock_version`, `candidate_hash`, `content`, `base_release_id`, `base_revision_id`, `published_revision_id`, `published_content_hash`, `active_release_id`.
  - This is the only edit #267 makes to `graph_configuration_draft.py`. §6's "read-only / do not modify" row for that file is replaced by "additive: one extraction, one sibling; #266's probe tests unchanged".
  - **Correction 8's transaction 1 becomes two short read transactions,** both before the model call and both closed before it:
    - **1a** is `read_draft_test_candidate`.
    - **1b** is `with session.begin():` loading the `AgentTestCase` row (id, version, agent_key, is_active, synthetic_payload, assembly_context) and the Correction 20 baseline row.

    The split is safe. Every value read in 1b is immutable: case versions (Correction 22), baseline evidence (the Correction 24 trigger) and the published revision. The one exception is `is_active`, which transaction 2 re-checks. The rest of Correction 8 stands: the `in_transaction()` assert before the call, transaction 2 under `_lock_current_parents(exclusive=False)` (`workbench.py:188-238`, unchanged), persisting verbatim, the currency flags and the one retry.
  - **Candidate runs carry the lock** (this corrects Correction 23's body), exactly as the probe does. The body is `{"test_case_id": int, "lock_version": int}`, strict, with `lock_version` `ge=0`. A stale lock returns the route's existing `_conflict_response(outcome, client_candidate=None)` 409. That is the same body as the probe's and upgrade's, and it comes with no model call and no row.
  - The baseline run (`POST /published/{agent_key}/test-runs`) reads no draft. Its body stays `{"test_case_id": int}`.
  - **Tests:**
    - #266's probe suites stay green, unedited, as the refactor's regression proof: `test_model_endpoint_probe.py`, the `-k probe` route tests, and PostgreSQL `:1683`.
    - #267's PostgreSQL lock proof reuses `:1683`'s harness shape.
    - Unit: a stale-lock run gives a 409 with zero adapter calls and zero `agent_test_run` rows.
    - Unit: a URL-shaped stored endpoint name gives a 422 with zero adapter calls.
    - **Controller sabotage:** drop the lock comparison in the shared helper. Predicted RED: #267's stale-lock test **and** #266's probe stale-lock test.
- **Cost if wrong:** a parallel read path drifts from the probe's lock and name-policy rules. Or an admin runs, and later approves, a candidate other than the one on their screen.

### Correction 33 — the test-run model call must be request-bounded, and must not borrow the probe's classification — NEW DEFECT — BLOCKING (Tasks 3 and 4)
- **Evidence:**
  - #266 ruled that the probe runs inside one admin request, so it must not inherit the provider client's default window of ten minutes per attempt with retries. It binds with `transport_options={"timeout": 30.0, "max_retries": 0}` (`model_endpoint_probe.py:99-100`, `:160-169`). The #266 ledger's Task 5 records this as "probe model call bounded to 30 s with no retries … Accepted".
  - The helper's contract says `transport_options` "is for the probe's call bound only; the runtime passes none" (`agent_runtime.py:420-421`).
  - The plan's executor (and Corrections 8 and 12) run a real role prompt through the production `DatabricksModelAdapter()` (`get_agent_runtime` `:735-743`). That adapter passes no transport options (pinned at `test_agent_runtime.py:645-677`). So a #267 run inherits the unbounded window inside an admin HTTP request. This is the defect #266 closed for the probe.
  - The adapter collapses **every** provider failure into `ModelProviderUnavailableError` (`:496-503`). `test_structured_output_runtime_adapter_still_collapses_permission_denied` (`test_agent_runtime.py:807`) pins that the runtime keeps collapsing. The probe's 403/422/503 table (`model_endpoint_probe.py:112-120`, `:170-185`: openai PermissionDenied/Authentication → forbidden, BadRequest/NotFound/Unprocessable → unsupported, everything else → retryable) is **only** reachable through the probe adapter.
- **Ruling:**
  - **Bound, same binding:**
    - Add a keyword-only `transport_options: Mapping[str, Any] | None = None` to `DatabricksModelAdapter.__init__`. `invoke` forwards it to `bind_structured_output_model`. The default `None` keeps the production adapter's kwargs byte-identical, so `:645-677` stays green unedited.
    - Update the helper docstring (`:420-421`) to name both bounded callers.
    - Add `get_agent_test_runtime()`, `lru_cache`d, beside `get_agent_runtime`: the same `PersistedGraphReleaseLoader` and `LoggingAgentInvocationIdentitySink`, with `DatabricksModelAdapter(transport_options={"timeout": TEST_RUN_TIMEOUT_SECONDS, "max_retries": TEST_RUN_MAX_RETRIES})`, where the constants are `120.0` and `0`.
    - Both `execute_candidate_run` and `execute_baseline_rerun` use it. Sampling values, prompt and schema are unchanged, and transport bounds are not model configuration (#266's own ruling).
    - The Correction 12 call-site guard extends to it: `get_agent_test_runtime` is referenced only from `agent_test_workbench.py` and the route dependency, never from `src/services/graph/`.
  - **Classification (honouring #266 without copying it):**
    - #267 does **not** reuse the probe adapter, its codes or its 403/422/503 statuses. A second, classifying invocation path would diverge from what production does (AC10).
    - A provider failure, including a timeout, is a **persisted** `model_error` run with `error_detail="endpoint_unavailable:<endpoint_name>"` (Correction 16), returned as a successful evidence write. It is never an HTTP 403/422/503, because the run did happen.
    - The UI may point the admin to "Test structured output" to diagnose a failure.
    - Correction 16 gains one row: `NotImplementedError` raised from the binding step (the type the probe classifies as unsupported, `:170`) is `model_error` with `error_detail="structured_output_unsupported:<endpoint_name>"`, not `unexpected_error`.
  - **Tests:**
    - The test runtime's adapter hands `model_factory` `timeout=120.0, max_retries=0` (mirror `:645-677` with recording factories).
    - The production `get_agent_runtime()` adapter still hands neither.
    - **Controller sabotage:** build the test runtime with the default adapter. Predicted RED: the kwargs test.
    - **Reviewer sabotage:** have `DatabricksModelAdapter` pass `transport_options or {}` into the kwargs pinned at `:645-677` for the default too, with a non-empty default. Predicted RED: `:645-677`.
- **Cost if wrong:** an admin request hangs for up to about ten minutes per attempt, with retries, on a slow endpoint (the exact defect #266 fixed for the probe). Or #267 grows a second classifying invocation path that reports failures production never distinguishes.
- **Product note (not blocking):** 120 s is a controller value. A healthy builder call slower than that is persisted as `model_error`, and the admin can run it again.

### Correction 34 — re-probe of Correction 15 (raw output, unclassified escapes) — CONFIRMED, with refreshed lines — BLOCKING (Tasks 3 and 4)
- **Evidence:**
  - `AgentInvocationResult` is still only `output` and `diagnostics` (`agent_runtime.py:204-206`).
  - `_supplied_output_keys` is at `:544-554`, and is called only inside `callback` (`:710-712`).
  - `AgentOutputValidationError` (`agent_schema_registry.py:338`, raised `:521`/`:536`/`:563`) is still caught by nothing in `_run_resolved`.
  - The adapter's `provider_errors` (`:469-487`) still exclude pydantic `ValidationError` from `structured_model.invoke` (`:495`), and `NotImplementedError` from the binding (`:489`). Both still escape raw through the sink.
- **Ruling:** Correction 15 stands. The private keyword-only `_raw_output_observer` is called immediately before `validate_output` at `:710`. `run` passes `None`. Correction 33 adds the `NotImplementedError` mapping.

### Correction 35 — re-probe of Correction 17 (deterministic checks from the runtime's one validation) — CONFIRMED — BLOCKING (Task 4)
- **Evidence:** `AgentSchemaRegistry.validate_output` (`agent_schema_registry.py:511`, the #264 registry, byte-unchanged) is the only output validation. It is called once, from `_run_resolved`'s callback (`agent_runtime.py:710`), on the composed model from `compose` (`:646`). There is no `model_validate` of provider output anywhere else in the runtime.
- **Ruling:** Correction 17 stands. `output_contract` passes iff the run is `completed`, and fails with `AgentOutputValidationError.issues` when it is `incomplete`. There is no second `model_validate`.

### Correction 36 — re-probe of Correction 23 (routes on the one admin router) against #266's routes — CORRECTED — BLOCKING (Tasks 2 and 5)
- **Evidence** (`src/api/routes/agent_definitions.py`):
  - The router is `:71-75` (prefix `/api/admin/agent-definitions`, `Depends(require_admin)`). `require_draft_write_principal` is `:78-86`.
  - #266 added three things:
    - `GET /model-endpoints` `:503-533`;
    - `POST /draft/{agent_key}/model-endpoint-probe` `:740-790`, which is async, parses the body after authorization with `_parse_lock_request` (`:392-405`), and runs the service via `await run_in_threadpool(...)` `:770`;
    - the PUT `:536-617`, which now also runs `save_editable_model_draft` through `run_in_threadpool` (`:589`) because it makes a remote call.
  - Loop-observer tests pin both (`test_agent_definition_workbench_routes.py:4406`, `:4431`).
  - The probe DTOs are strict siblings (`src/api/schemas/agent_definitions.py:391-394` `DraftLockRequest`, `:481-510`).
- **Ruling:**
  - Correction 23's path list stands. None of #267's paths collides with `/workbench`, `/model-endpoints` or `/draft/{agent_key}/model-endpoint-probe`.
  - **Every #267 route that reaches a model** (`POST /draft/{agent_key}/test-runs` and `POST /published/{agent_key}/test-runs`) is `async def`. It parses after authorization, as `_parse_lock_request` does: malformed JSON first, then unknown agent, then a strict DTO. It then runs the executor with `await run_in_threadpool(...)`.
  - Each gets a loop-observer test copied from `:4406`. **Sabotage:** call the executor directly. Predicted RED: that test.
  - The case CRUD routes make no model call and may stay `def`.
  - Run request DTOs are new `_StrictDraftRequest` siblings. The candidate body has `lock_version` (Correction 32).
- **Cost if wrong:** a live model call blocks the event loop for every admin and user request. This is the Important defect #266's whole-branch review found in its own PUT.

### Correction 37 — builder-and-every-role payload parity, re-ruled after `6cbab388a` and `50c8cbf35` — CORRECTED (Correction 10) — BLOCKING (Task 4)
- **Evidence:**
  - Only the builder has a named allowlist: `_BUILDER_MODEL_PAYLOAD_KEYS` (`src/services/graph/nodes.py:2063-2075`), filtered in payload order at `:2121-2125`. The builder retry adds `corrective_instruction` **after** filtering (`:2140-2143`).
  - Every other role's model payload is a literal dict built for the model (architect `:1466`ff, with the nested `previous_deck_review` reduced to `{digest, findings}` at `:1430-1436`; data analyst `:1870`ff; deck reviewer `:3015`ff).
  - The exact per-call key sets are pinned only in the test: `tests/unit/test_graph_nodes.py:3406-3419` and `:3516-3573` (`_EVERY_MODEL_CALL`). `TestNoRolesModelPromptCarriesSessionIdentifiers` (`:3724-3784`) asserts the exact key set for all ten calls and that no session ID, turn ID or email appears anywhere in the prompt.
  - The seed (`graph_configuration_seed.py`, unchanged) projected onto those sets drops exactly these keys:
    - architect: `session_id`;
    - data_analyst: `session_id`;
    - builder: `session_id`, `turn_id`, `initiated_by`, `design_contract`;
    - deck_reviewer: `session_id`.

    Every remaining key of all seven seeds is inside its role's production union. build_reviewer's seed is the deck-level re-review shape (`+ deck_brief`), and fix_reviewer's is `_FIXER_MODEL_KEYS + change_summary`.
- **Ruling (replaces Correction 10 items 3 and 5; items 1, 2 and 4 stand, and the gate in item 2 is discharged):**
  1. **The seed stays unedited.** It is test-pinned (`test_graph_configuration_bootstrap.py:45`), first-boot-verified, and persisted in every database, so editing it would leave existing environments diverged. The executor filters.
  2. **One projection for every role:**
     - `src/services/agent_model_payload.py` (import-light, with no graph import) holds `MODEL_PAYLOAD_KEYS: Mapping[AgentKey, frozenset[str]]` for all seven roles. Each is the **union of that role's production calls**:
       - builder: the 9 keys plus `corrective_instruction`;
       - build_reviewer: 7 keys plus `deck_brief`;
       - fixer: 7 keys plus `corrective_instruction`;
       - fix_reviewer: 7 keys plus `change_summary`;
       - architect: 9 keys;
       - data_analyst: 2 keys;
       - deck_reviewer: 4 keys.
     - It also holds `model_payload_for(agent_key, payload) -> dict`. That function projects top-level keys in payload order, and applies the one nested rule production has: a dict `previous_deck_review` is reduced to `{digest, findings}`.
     - An unknown role raises `UnknownAgentKeyError`.
  3. **`nodes.py` is not edited by #267.** This reverses Correction 10 item 3. Routing `builder_node` through a union that includes `corrective_instruction` would widen production's pre-retry filter, and the other nodes are already literal allowlists.
  4. **Parity is proved by one source of truth for the key sets:**
     - Task 4 moves `_BUILDER_MODEL_KEYS`, `_BUILDER_RETRY_MODEL_KEYS`, `_SLIDE_REVIEW_MODEL_KEYS`, `_FIXER_MODEL_KEYS` and `_EVERY_MODEL_CALL` verbatim into `tests/fixtures/model_payload_keys.py`, and `test_graph_nodes.py` imports them. This is a pure move: the node-ID list of `test_graph_nodes.py` must be identical before and after, and must be recorded.
     - A new unit test asserts two things:
       - for every role, the union of that role's `EVERY_MODEL_CALL` sets `== MODEL_PAYLOAD_KEYS[role]`;
       - `MODEL_PAYLOAD_KEYS["builder"] - {"corrective_instruction"} == nodes._BUILDER_MODEL_PAYLOAD_KEYS`.

       Production equals the fixture (pinned by `:3724`), and the fixture equals #267's table (pinned here).
  5. **Executor tests (all seven roles):**
     - Run each role's seeded case through `execute_candidate_run` with the fake adapter. Assert that the prompt's payload object has exactly `set(seed) & MODEL_PAYLOAD_KEYS[role]` as its keys.
     - Assert that none of `synthetic-architect`, `synthetic-data-analyst`, `synthetic-builder`, `synthetic-turn`, `system:bootstrap` or `synthetic-deck-reviewer` appears in any prompt.
     - Keep the builder byte-identical prompt parity against `builder_node` from Correction 10.
     - **Controller sabotage:** add `"session_id"` to `MODEL_PAYLOAD_KEYS["architect"]`. Predicted RED: the union-equality test and the architect no-identifier test.
     - **Reviewer sabotage:** have the executor pass the stored payload unprojected. Predicted RED: the per-role key-set tests for architect, data_analyst, builder and deck_reviewer.
  6. **Evidence:** `model_payload` (Correction 19) stores the projection. The Input view shows the stored synthetic payload and the projection "sent to the model", so an admin sees which keys were dropped.
- **Cost if wrong:** approved evidence certifies prompts production never sends, or a session, turn or email value reaches a test prompt, against the user's P6 decision for every role.

### Correction 38 — frontend pre-brief refresh for #266's UI — CORRECTED (Correction 25) — BLOCKING (Task 6)
- **Evidence:**
  - `forbiddenActionNames.ts` is byte-unchanged. `FORBIDDEN_ACTION_STEMS` (`:18-19`) still includes `\brun\b`, and `ALLOWED_ACTION_NAMES` (`:28-32`) has 3 entries. It strips exempt names before testing (`:35-41`).
  - Both lanes assert `'Run isolated test'` **is** forbidden: `AgentDefinitionWorkbench.test.tsx:308` (list) and `:474` (the `<img alt>` name-source case), and `agent-definition-workbench.spec.ts:1470`. So Correction 25's "remove only the `\brun\b` stem" would turn three existing guard tests RED, and weaken the guard.
  - `toHaveLength(3)` is at `test.tsx:320` and `spec.ts:1480`, not at `:1462`. "Isolated testing is not available in this release." is asserted at `test.tsx:455` and `spec.ts:1500`. The pane is `<aside aria-label="Isolated testing">` at `AgentDefinitionWorkbench.tsx:210-215`.
  - #266's accessible names in the definition editor: button `Test structured output` (`DefinitionEditor.tsx:539-546`), button `Retry structured output test` (`:163-165`), region `Structured output test result` (`:144-145`), status text `Testing the saved candidate…` (`:548`), button `Refresh models`, radiogroup `Discovered models` (`:492`). They are pinned as constants at `test.tsx:2575-2580`.
- **Ruling:**
  - **Keep `\brun\b`.** Exempt exactly `'Run test case'` and `'Run published baseline'` in `ALLOWED_ACTION_NAMES`, change `toHaveLength(3)` to `5` at `test.tsx:320` and `spec.ts:1480`, and add the shield cases `'Run test case and publish'` → forbidden and `'Run published baseline, then approve'` → forbidden in both lanes.
  - No other #267 control may contain a whole-word "run" (for example, a "View run 12" link). Headings and status text are not swept.
  - **No accessible-name collision with #266.** Playwright's `getByRole(..., { name: '<string>' })` is a case-insensitive **substring** match. So no #267 accessible name may contain, or be contained in, any #266 name above. In particular, no #267 name may contain "structured output", "test result" or "Retry". Use:
    - buttons `Run test case` and `Run published baseline`;
    - regions `Test case evidence` and `Published baseline evidence`;
    - the case list `Agent Test Cases`.
  - Mount in the existing `<aside>` at `:210`.
  - **Candidate runs send `lock_version`** (Correction 32). The run is disabled while a Save is pending, as the probe is (`test.tsx:2832`), and it runs the **saved** candidate.
  - **`mocks.ts` text-read rules** (the Python joins read it as text):
    - Append #267 fixtures at the end of the file.
    - No new `export const` name may begin with an existing exported name, because `_client_rejection_triple` (`test_agent_definition_workbench_postgres.py:1132-1136`) uses `index("export const NAME")` with no colon. This is also #266 Task 4's rule for `ENDPOINT_NAME_POLICY_CASES`.
    - Blocks read by `_client_json_fixture` (`test_agent_definition_workbench_routes.py:3330-3341`) stay `export const NAME: T = {` … `\n};` in strict JSON.
    - `STRUCTURED_OUTPUT_PROBE_FAILURES` keeps its five-line entries (`test_probe_failure_contract_client_join.py:21-24`, `:48-55`).
  - **`agentDefinitions.ts` rules:**
    - `const PROBE_FAILURE_CONTRACT = {` and `export type StructuredOutputProbeFailureCode =` must each appear exactly once.
    - The exact line `  if (status !== 403 && status !== 422 && status !== 503) return null;` must appear exactly once (`test_probe_failure_contract_client_join.py:65`, `:126`). #267's own response parser must not repeat that line.
    - If #267 adds a client failure contract, it gets its own Python join in a new file, in the same style.
  - **Routing:** route the test-run POSTs by URL in both Vitest harnesses and in Playwright (#266 c17). Add an unrouted-POST tripwire, which is #266's deferred m2.
- **Cost if wrong:** three guard tests go RED, or the guard is weakened. A Playwright locator from #266 or #267 resolves two controls (a strict-mode violation). Or a Python text-read join goes RED on a frontend-only edit.

### Correction 39 — cause baseline re-derived at `e91fcd856` — CONFIRMED (no new cause) — BLOCKING (the reference for every task)
- **Environment:** `DATABASE_URL=sqlite:////tmp/t267-base.sqlite` (the full suite otherwise commits to the dev database, per #266's fix-wave finding) with `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr` and the pyenv shim. `test ! -e .venv` held before and after. Nothing was installed, no frontend was run, and `ai_slide_generator` was untouched.
- **Full unit suite** (`tests/unit -q -p no:randomly -rf`): **6 failed, 6175 passed, 110 skipped, 136 warnings** (417 s). The same six node IDs and causes as §7:
  - `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available`: `:124 'provisioned' == 'autoscaling'`.
  - `…::test_falls_back_when_autoscaling_creation_fails`: `:152 _get_or_create_lakebase_provisioned called 0 times`.
  - `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::{test_create_session_normalizes_a_raw_both_set_dict, test_create_session_still_stores_a_single_authority_config_unchanged, test_create_session_still_accepts_no_agent_config}`: `AttributeError: '_FakeSession' object has no attribute 'execute'` (`conversation_pins.py:79`, via `session_manager.py:780`).
  - `test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session`: `ConversationGraphReleaseIntegrityError: no active Graph Release` (`conversation_pins.py:83`).

  The passed count moved from 5881 to 6175: that is #266's tests plus the payload fixes, and it equals #266's fix-wave count. The warning count moved from 135 to 136. Every warning location in the summary is in a module that neither #266 nor #267 touches. This is noted, not a cause.
- **Focused unit matrix** (the §7 ten files, one invocation): **865 passed, 0 failed, 0 skipped** (was 724).
- **#266 files #267 now shares** (one invocation): **167 passed, 0 skipped**. The files are `test_model_endpoint_probe`, `test_graph_configuration_workbench`, `test_probe_failure_contract_client_join`, `test_endpoint_name_policy_client_join` and `test_prompt_assembler`. They are added to the focused matrix from Task 3 on, because Tasks 3, 4 and 6 touch their subjects.
- **PostgreSQL** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, one invocation per file, **zero skips each**):
  - bootstrap 2;
  - constraints 7;
  - workbench **17** (was 15; +2 are #266's);
  - overlay 10;
  - runtime failures 7.

### Correction 40 — §6 shared-file table, refreshed for the post-#266 head — CORRECTED — Advisory
Rows that change (all others stand):

| File | #267 task | Rule now |
|---|---|---|
| `src/services/agent_runtime.py` | 3 (`run_candidate`, observer, sentinels), 3/4 (`DatabricksModelAdapter(transport_options=)`, `get_agent_test_runtime`), 8 | one binding at `:431`; `run` byte-identical; production adapter kwargs unchanged (`test_agent_runtime.py:645-677`) — C31, C33 |
| `src/services/graph_configuration_draft.py` | 4 | additive: extract the probe read body, add `read_draft_test_candidate`; #266 probe tests unedited — C32. #269 Task 1 edits `_write_locked_content` (now `:911-948`): sequence by file |
| `src/services/graph/nodes.py` | **none** | not edited by #267 — C37 |
| `src/services/agent_model_payload.py` | 4 (new) | all-role projection — C37 |
| `tests/fixtures/model_payload_keys.py` (new), `tests/unit/test_graph_nodes.py` | 4 | pure move of the key sets; node-ID list identical — C37 |
| `src/services/model_endpoint_probe.py` | read-only | never imported by #267's executor — C33 |
| `src/api/routes/agent_definitions.py` | 2, 5 | async + `run_in_threadpool` for model-calling routes; loop-observer tests — C36 |
| `frontend/.../AgentDefinitionWorkbench.tsx` | 6 | aside at `:210`; names per C38 |
| `frontend/src/api/agentDefinitions.ts`, `frontend/tests/fixtures/mocks.ts` | 6 | text-read rules per C38 |

### §12 summary: GO/NO-GO for Task 1

**GO.** All four conditions from §11 are discharged:
1. #266's reviewed merge `e91fcd856` is on `feat/langgraph-core`, and this branch is rebased onto it (C29).
2. `IMPLEMENTATION_BASE=e91fcd856` is recorded (C29).
3. The cause baseline was re-derived, with the same six nodes and causes and no new cause (C39).
4. Corrections 3, 12, 15 and 23 were re-probed (C30, C31, C34, C36).

Task 1 touches only `tests/unit/test_graph_configuration_bootstrap.py`, which is byte-unchanged since `c040dbde0`, and its guard (`bootstrap.py:187-198`) is unchanged. None of Corrections 32–38 binds Task 1.

The Task 4 external gate (Correction 10) is also discharged by `6cbab388a` and `50c8cbf35`. Its brief must now carry Corrections 32, 33, 36 and 37.

Pre-brief additions to §8:
- **Task 3:** 31, 33 (adapter `transport_options`, `get_agent_test_runtime`, the `NotImplementedError` row), 34.
- **Task 4:** 32, 33, 35, 37.
- **Tasks 2 and 5:** 36.
- **Task 6:** 38.
