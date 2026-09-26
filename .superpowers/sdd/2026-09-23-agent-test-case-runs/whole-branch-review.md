# #267 whole-branch review — `e91fcd856..095ba2f4e1f2da3a66185f4598b5d1ae06c0d56e`

Reviewer: final whole-branch gate (Opus). Branch `feat/agent-test-case-runs-267`, 56 commits ahead and 0 behind `feat/langgraph-core` (`e91fcd856`). GitHub was used read-only as `robertwhiffin`. Temp worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/wbr-267` was detached at HEAD, used for all runs and sabotage, and then removed. `.venv` was absent before and after.

## 0. Gates re-measured at HEAD (temp worktree, pytest run from inside it)

- **Full `tests/unit`** (`DATABASE_URL=sqlite:////tmp/wbr-267.sqlite`): 6 failed, 6616 passed, 110 skipped, 136 warnings.
  - The failures match the baseline by cause: `test_deploy_autoscaling` ×2, `test_style_exclusivity_chokepoint` ×3 and `test_style_exclusivity_persistence_boundary` ×1.
  - There is no new cause.
- **PostgreSQL**, one file per run, all with zero skips:
  - workbench 25
  - constraints 66
  - bootstrap 3
  - overlay 10
  - runtime failures 7
- **Frontend:** not re-run by me. I made no frontend mutation. The Task 6 fix-round gates were Vitest 597, typecheck 0, ESLint 0 and Playwright 76.

## 1. Ticket-level spec review (#267 acceptance criteria)

| # | Criterion | Ruling | Evidence |
|---|---|---|---|
| AC1 | Each editable role has ≥1 active required smoke case after bootstrap | PASS | Seeding: `graph_configuration_bootstrap.py:314-318`. Boot guard: `:187-197`. Tests: `test_graph_configuration_bootstrap.py:732` (parametrised over all seven roles) and `:767`; PG bootstrap 3. The case writer refuses to remove the last required case (`agent_test_workbench.py:797-803`, `:860-861`), with a PG two-session test at `test_agent_definition_workbench_postgres.py:1948`. |
| AC2 | Create, update, version, deactivate and mark required, retaining history | PASS | Service: `agent_test_workbench.py:697` (create), `:758` (supersede = retire + `version+1` in one transaction), `:845` (deactivate); `include_inactive` at `:671`. Routes: `routes/agent_definitions.py` `/test-cases` GET/POST/PUT/DELETE. UI: the Edit, Add and Retire controls in `TestRunPanel.tsx`. |
| AC3 | Synthetic payload plus declarative context only; UI warning | PASS (warning; not server-enforced per P7) | The assembly context is exactly `{design_system_active}` (`agent_test_workbench.py:313-327`, `schemas:517`). The warning appears at `TestRunPanel.tsx:13,269,352`. The `is_synthetic_data_warning` flag is on the case DTO. |
| AC4 | Isolated run executes the saved immutable candidate and hash through AgentRuntime; no graph, deck or chat write | PASS | `agent_runtime.py:759-816`: role, then content role, then hash (`:790`), then no session ids (`:794`), then `_run_resolved`. The executor writes only `agent_test_run` (`agent_test_workbench.py:1214-1284`). The AST call-site guards confirm `run_candidate` and `run_published_baseline` are reachable only from the workbench. |
| AC5 | Evidence records identities, raw and structured outputs, checks, errors, latency, **and token usage when available** | **FAIL (partial)** | Identities, outputs, checks, errors and latency are all persisted (`:1241-1268`). But `input_tokens=None, output_tokens=None` is hard-coded (`:1265-1266`), so usage is never captured even when an endpoint reports it. See **I-1**. |
| AC6 | Baseline is stored evidence; reruns only on an explicit request | PASS | A candidate run copies the newest completed `published_baseline` output of the same case row and revision (`:1187-1204`, C20). The only rerun path is `POST /published/{agent_key}/test-runs`. Tests are at `test_agent_test_workbench.py:1828-1890`. |
| AC7 | Graph Version 1 shows "baseline not recorded" until run; checks are not waived | PASS | `TestRunPanel.tsx:24,136`; `test_no_baseline_is_shown_before_one_is_run`. The candidate's checks are computed independently of the baseline (`:529-550`). |
| AC8 | Failed model calls are persisted; invalid or incomplete runs cannot be approved | PASS | A `model_error` or `incomplete` result is persisted with status 201 (`classify_test_run_failure`, `agent_runtime.py`). The DDL enforces `ck_agent_test_run_approved_only_if_completed_and_passing` (`models/graph_configuration.py`). A PG sabotage of that check went RED in Task 0. |
| AC9 | The Input, Compare and Checks views render the prompt, field errors, diagnostics, and candidate against baseline | PASS | See the `TestRunPanel.tsx` Input section (prompt and model payload sent), Compare (candidate against stored baseline, plus the baseline rerun), and Checks (issue code and field). History is read on case selection (Task 6 fix I-2). |
| AC10 | Fake adapters prove the candidate and published paths share assembly, schema, validation, model **and tracing** | PASS with a declared deviation | `tests/fixtures/deterministic_model_adapter.py`. Prompt, schema and configuration equality with `run` is tested at `test_agent_runtime.py:1040`; the one binding helper at `:698`. Tracing deliberately diverges by ruling R1: candidate runs use a pass-through sink and their own record (see **m-2**). |

Design clauses:
- **§5.5 `agent_test_run` fields:** PASS except token usage (I-1). Verdict columns exist, and `graph_release_test_run` has RESTRICT FKs, closed `evidence_kind` and the paired `source_release_id`.
- **§7.1 "the same private resolved-definition execution path":** PASS. `run_candidate` returns `CandidateRunOutcome`, not `AgentInvocationResult`; C15/C16 accept that.
- **§11.2:** PASS. The design's "stored approved output" is superseded by P1 (the newest completed baseline, labelled "not approved").
- **§13.1 right pane Input/Compare/Checks:** PASS.
- **§14 "create, update, version, and deactivate … execute an isolated Agent Test Run":** PASS.
- **§15 "Unknown model endpoint during test → failed test run with clear endpoint error":** PASS. It is recorded as `model_error` with `endpoint_unavailable:<name>`. A URL-shaped name is a 422 before any call, which is stricter.
- **§16:** PASS. Every route is behind the router's `require_admin` (`routes/agent_definitions.py:97-101`), and every write records `actor`.

## 2. Model-call path table

There is exactly one `with_structured_output(` in `src/`: `agent_runtime.py:436` in `bind_structured_output_model`. It is pinned by `test_structured_output_runtime_and_model_endpoint_probe_share_one_helper` (`test_agent_runtime.py:698`).

| Path | Binding | Transport bound | DB lock during the call | Identity sink / log record | Payload projection | Pinning tests |
|---|---|---|---|---|---|---|
| Production `run` (graph nodes) | `DatabricksModelAdapter()` → the helper | None (the provider default). `transport_options=None` passes exactly the old kwargs. | Unchanged by this branch (out of scope) | `LoggingAgentInvocationIdentitySink`, `persisted_agent_invocation`: 5 identity fields, `outcome` and `error_class`, plus `additional_field_names` (names only) | Built in `nodes.py`. The P6 fix strips session ids for every role. | `run`/`get_agent_runtime` AST-identical guards; `test_graph_nodes.py` fixture-equality against `tests/fixtures/model_payload_keys.py` |
| `run_candidate` | `get_agent_test_runtime()` adapter → the helper | 120 s, 0 retries (`agent_runtime.py:1048-1070`, C33) | None. Transactions 1a and 1b have committed, and `session.in_transaction()` is guarded (`agent_test_workbench.py:937`). | `_PASS_THROUGH_IDENTITY_SINK` (nothing recorded). One `agent_candidate_run` record with exactly `{agent_key, status, error_code, error_class}` (`:679`). No exc_info. | `model_payload_for` (`agent_model_payload.py`): the per-role union allow-list plus `previous_deck_review` minus `author`. Session ids are refused, not stripped. | `test_run_candidate_runs_every_role_through_the_fake_and_bypasses_the_identity_sink`, `test_candidate_prompt_schema_and_configuration_equal_the_production_path`, `test_run_candidate_refuses_a_session_identity`; PG `test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight` (`:2272`) |
| `run_published_baseline` | Same test runtime | 120 s, 0 retries | None. Its own transactions have committed. The loader opens and closes its own short session inside `resolve` before the call. | Production `LoggingAgentInvocationIdentitySink` (real release and revision ids, empty sessions) — ruling concern 2 | Same projection. `validate_endpoint_name_policy` runs before the call. | `test_run_published_baseline_resolves_exactly_as_run_does`, `…_hands_the_model_runs_prompt_and_records_the_real_identity`, `test_the_baseline_model_is_called_with_no_open_transaction`, `test_every_role_baseline_model_sees_exactly_the_projected_seed_keys`. **No PG `pg_locks` proof for this path** (m-5). |
| #266 probe | `DatabricksStructuredOutputProbe` → the helper | 30 s, 0 retries (`model_endpoint_probe.py:99,160-168`) | None (C13). The read goes through the shared `_read_saved_candidate`. | No identity sink. `structured output probe outcome %s (%s)` logs the code and the class. | The code-owned `_PROBE_PROMPT`; no payload | PG `test_model_endpoint_probe_holds_no_lock_while_the_model_call_is_in_flight` (`:1683`) |

## 3. Writer table

The #269 global order is: L0 release → L0 draft → L1 draft agents → L2 case rows → L3 run rows.

| Writer | Transaction shape | Locks, in order (vs #269) | Rollback / no-write on every refusal | Pinning tests |
|---|---|---|---|---|
| Case create (`:697`) | Validation (actor, then key, then name and content) runs **before** the transaction. Then one `session.begin()`: L2 lock, INSERT, flush, refresh. | L2 `FOR UPDATE` on every row of the role, in id order. It is an L2-only subsequence, so it respects the order. | Validation 422 writes nothing. A duplicate name raises IntegrityError inside the transaction, which rolls back to a 422 `duplicate_name`. | `test_create_rejects_a_name_already_used_by_the_role_even_when_retired`; the role-lock statement test; my sabotage S1 (below) |
| Case supersede (`:758`) | One transaction: unlocked `agent_key` read (the column is immutable), L2 lock, re-read (fresh READ COMMITTED snapshot), then the checks, retire flush and INSERT `version+1` | L2 `FOR UPDATE` (all role rows) | A 422 (content, name, last-required) or 409 inactive raises before any row change, and the transaction rolls back. A no-op returns 200 with no write. A version collision raises IntegrityError, which becomes a 409 stale. An injected insert or retire failure leaves the old row intact and no successor. | `test_an_identical_update_is_a_no_op…`, `test_update_of_a_superseded_or_retired_version_is_stale`, `test_a_failed_retirement_leaves_no_successor_behind`, `test_an_identical_save_to_an_inactive_version_is_still_stale` |
| Case deactivate (`:845`) | One transaction: L2, re-read, then UPDATE `is_active` | L2 `FOR UPDATE` | Already inactive is a no-op. Last required is a 422 with no write. | `test_deactivate_retires_without_deleting_and_is_idempotent`; PG `:1948` two-session (S1 went RED here) |
| Run insert (`_persist_run`, `:1214`) | Transaction 1a (the #266 probe read, `FOR SHARE`) commits. Transaction 1b (case and stored baseline) commits. Then the model is called with no transaction. Transaction 2: `_lock_current_parents(exclusive=False)`, unlocked currency reads, INSERT. It retries once on the publication-handoff diagnosis. | L0 release+draft `FOR SHARE` (one statement), then the implicit FK `KEY SHARE` on the `agent_test_case` row (L2 domain), the `agent_definition_revision` and the (already held) release, then its own new L3 row. This is a prefix-respecting subsequence, so there is no cycle with the case writers (L2 only), the #269 publisher (L0 exclusive first) or the #268 verdict writer (L3). | A refusal before the call (lock/role 422, stale 409, endpoint 422, case 404, role mismatch 422, inactive 409) makes no call and writes no row. After the call, `SQLAlchemyError` or `GraphConfigurationIntegrityError` rolls back, writes no row and returns a 503 `test_run_unavailable`. | PG `test_candidate_run_insert_waits_behind_an_exclusive_parent_holder_without_deadlock` (`:2373`) and `:2272`; unit tests for draft-saved and case-retired during the call |
| C24 evidence trigger (`database.py`) | `BEFORE UPDATE FOR EACH ROW`, installed in the migration transaction with an idempotent DROP/CREATE. It compares `to_jsonb(NEW) - verdict[4]` with `to_jsonb(OLD) - verdict[4]`. DELETE is allowed. | n/a | Any non-verdict change raises 23514 and the statement is aborted. | Metadata-driven per-column PG immutability test (Task 0 fix; every column RED when exempted); idempotence test |

**Rollback ruling:** every refusal on every writer is either raised before `session.begin()` or raised inside it, so the context manager rolls back. No partial write is reachable. I found no counter-example.

## 4. Privacy table

User decisions:
- no session, user, turn or release identifier reaches any model;
- the log carries optional-field key names only;
- no model prose appears in the log;
- `run_by` is accepted in admin responses.

| Surface | Identifiers / free text reaching it | Ruling |
|---|---|---|
| Model prompt (candidate and baseline) | The role's projected payload keys only. The seed's `session_id`, `turn_id` and `initiated_by`, the builder's `design_contract`, and `previous_deck_review.author` are dropped (my sabotage S2 went RED on the author). The assembly context is `design_system_active` only. Session ids are refused (`agent_runtime.py:794`). The prompt text is admin-authored draft or published content. No `run_by`, release, revision or case id. | PASS. An admin can still type an identifier into a synthetic payload's allowed key; P7 accepts this as a UI warning. |
| Model prompt (probe) | A fixed code string | PASS |
| Application log | `agent_candidate_run {agent_key, status, error_code, error_class}`; `agent_test_run_unavailable {agent_key, phase, error_class}`; the baseline's `persisted_agent_invocation {graph_version, graph_release_id, agent_key, agent_definition_revision_id, content_hash, outcome, error_class, additional_field_names}`; probe code and class. No exception text, no traceback, no payload, prompt or output. | PASS. The pre-existing route `logger.exception` on `GraphConfigurationIntegrityError` carries only code-owned messages. |
| API response | Evidence: `run_by`, `run_at`, case, release and revision ids, `candidate_hash`, `synthetic_payload`, `model_payload`, `assembled_prompt`, raw and structured outputs, `error_detail` (the code plus the endpoint name or class name). Cases: `created_by`, `updated_by`. No session ids; `-1` is impossible (`ge=1`). | PASS (admin-only surface) |
| UI | The same evidence, rendered only as text in `<pre>` or plain nodes; `run_by` in RunFacts; the synthetic-data warning | PASS |

## 5. Consumer-fit ruling (#268, #269)

1. **#269 L2 gate statement vs #267 supersede — BROKEN (I-2, new).**
   - #269's plan (`2026-09-25-graph-release-publication.md:721-725`) locks `agent_test_case WHERE agent_key IN changed AND is_active AND is_required … FOR SHARE` and uses **that result set** as the list of cases to gate.
   - #267's supersede locks the role's rows `FOR UPDATE`, retires the old version row, and INSERTs the new version.
   - Under READ COMMITTED, a publisher that queues behind a supersede re-evaluates the retired row (now `is_active=false`), so it is **dropped**. The new version row is outside the statement snapshot, so it is **not returned** either.
   - The superseded lineage therefore vanishes from `cases`, and publication links the other cases and succeeds with **no approval for that required lineage**. Neither serial order allows this.
   - **Probed** in a throwaway database (`wbr267_probe`, created and dropped):
     - two required cases, A and B;
     - the writer runs the #267 shape (lock all, retire B v1, insert B v2) and is left uncommitted;
     - the publisher runs #269's statement and is observed blocked;
     - the writer commits;
     - the publisher's locked set is `[(1,'A',1)]`, while a fresh re-read gives `[(1,'A',1),(3,'B',2)]`.
   - #267's ledger entry (Task 2 residual: "a supersede racing #269's gate yields a false `no_required_case` (refuses, retry clears)") is true only for a one-case role. #269's Correction 20 ("covered by the `test_case_version == case.version` predicate against the locked row") is wrong, because the lineage is not among the locked rows at all.
   - **Fix, in #269's corrections:** lock the changed roles' rows **unfiltered** `FOR SHARE` in id order (mirroring `_role_lock_statement`), then re-select the active required rows in a **new statement**, which is #267's own `_lock_role_of` pattern. A brand-new case INSERT is then serialized too: create takes `FOR UPDATE` on the same role rows, so it waits behind the publisher, or the publisher's re-read sees it.
2. **Verdict route path — BROKEN (known; carried).** #268's plan uses `POST /api/admin/agent-test-runs/{run_id}/verdict` (`:54,161,498,516`), and #269's plan copies it (`:88`). The branch's single router gives `/api/admin/agent-definitions/test-runs/{run_id}/verdict`. #268's readiness path `/api/admin/graph-draft/readiness` is likewise outside the router.
3. **`run_kind='candidate'` filters — MISSING in both plans (known; carried).** They are absent from #268's readiness (`:146,:464`) and cleanup-retention (`:570-575`) queries, and from #269's L3 query (`:727-735`). The DDL allows an approved `published_baseline` (M1 ruling). In practice a baseline's `candidate_hash` is the published hash, which a *changed* role's draft cannot equal, so this is hygiene rather than an exploitable gap. It is still required so that the gate is not relying on that coincidence.
4. **#268's "backward-compatible" response extension — BROKEN (m-1).** #268 `:508` adds four verdict fields to `TestRunEvidenceResponse`. The response model is `extra="forbid"`, and the frontend parser is exact-keys (`agentDefinitions.ts:1296-1303`, `parseTestRunEvidence` returns null on any extra key). So every run and history response would be rejected by the UI until `TEST_RUN_KEYS` changes in the same commit.
5. **Trigger coexistence — OK, with conditions.**
   - #269's `trg_agent_test_run_linked_verdict_immutable` and #267's `trg_agent_test_run_evidence_immutable` are both `BEFORE UPDATE`, and PostgreSQL fires them alphabetically (evidence first). Both use 23514.
   - #269's idempotence test must expect **both** triggers.
   - #268/#269 fixtures must not "stale" a run by UPDATE-ing it, because the trigger rejects that.
   - #269's ORM fallback must supply `run_kind`, `model_payload`, both `compared_*` columns and `deterministic_check_results`.
6. **Residual race from a new case INSERT** — after fix 1 it is closed, as argued in item 1. With #269's current statement, a create that commits while the publisher waits is serializable-equivalent to "publish then create", so it is benign. The supersede case is the harmful one.
7. **Lock order** — #267's writers are all prefix-respecting subsequences of #269's order (§3). #269's C13 (no lock across a model call) is met and PG-proved for the candidate path.
8. **#269 Task 8 E2E** — `POST …/draft/{agent_key}/test-runs` matches, but the body must include `lock_version`. The fake adapter is at `tests/fixtures/deterministic_model_adapter.py`.

## 6. Reviewer sabotage (seams not in the ledger)

Ledger check: no controller or reviewer removed the L2 `with_for_update()` itself (Task 2's reviewer mutated the `is_required` count), and none mutated the `previous_deck_review` author stripping.

**S1 — case-writer L2 lock removed** (`agent_test_workbench.py` `_role_lock_statement`)
- The anchor `.order_by(AgentTestCase.id)\n        .with_for_update()\n    )` matched 1 time and was replaced by `.order_by(AgentTestCase.id)  # WBR267_NO_L2_LOCK`. `grep -c WBR267_NO_L2_LOCK` gave 1, and `with_for_update` then had 0 hits in the file.
- **RED:**
  - PG `tests/integration/test_agent_definition_workbench_postgres.py` went to 2 failed / 23 passed. Both failures were `test_two_sessions_retiring_a_roles_last_two_required_cases_serialize_and_one_is_refused[seed]` and `[second]`, with "both committed; bootstrap afterwards = GraphConfigurationIntegrityError('active required Agent Test Cases do not cover every graph role')".
  - Unit `tests/unit/test_agent_test_workbench.py tests/unit/test_agent_definition_workbench_routes.py` went to 1 failed / 531 passed, on `test_the_role_lock_statement_is_for_update_over_every_row_of_the_role`.
- **Restore:** `git checkout --` from the pinned HEAD; the marker count went to 0 and the worktree was clean.
- **GREEN:** PG 25 passed, unit 532 passed.

**S2 — `previous_deck_review.author` reaches the model** (`agent_model_payload.py` `_previous_deck_review`)
- The anchor matched 1 time. I inserted `return dict(value)  # WBR267_KEEP_AUTHOR`; the marker count was 1.
- Scope: `tests/unit/test_agent_model_payload.py tests/unit/test_agent_test_workbench.py tests/unit/test_graph_nodes.py`.
- **RED:** 1 failed / 337 passed, on `test_the_previous_deck_review_loses_its_author_as_in_production`.
- **Restore:** `git checkout --`; clean.
- **GREEN:** 338 passed.

## 7. Findings

- **I-1 (Important, MUST-FIX before merge: implement or get an explicit user deferral).** AC5 and spec §5.5 require "token usage when available", but usage is never captured: `input_tokens`/`output_tokens` are hard-coded to NULL at `agent_test_workbench.py:1265-1266`.
  - The plan's Phase B Tasks 8 and 9 (token enrichment, then the full-path smoke) were silently dropped. The ledger deletes only Task 7 and ends with "all tasks 0-6 complete". Correction 31 itself records that Task 8's dependency (#266's helper) is now met.
  - P9 accepts NULL for endpoints that *omit* usage; it does not cover never reading usage that is reported. The UI therefore shows "not reported" for every run.
  - The fix keeps the one `with_structured_output(` by using a usage callback (for example `UsageMetadataCallbackHandler` passed through the invoke config) or `include_raw` inside the helper, on the test runtime only.
- **I-2 (Important, MUST-FIX as a consumer carry-forward before #269 Task 4; no #267 code change).** #269's L2 gate statement lets a concurrent supersede remove a required lineage from the gate, which silently bypasses readiness. It is proven on PostgreSQL (§5.1). Correct the #267 ledger's residual note and #269's Correction 20, and add a #269 PG ordering test with two required cases.
- **m-1 (Minor, carry to #268).** The verdict fields break the strict frontend evidence parser (§5.4). #268 must update `TEST_RUN_KEYS` and the response model atomically.
- **m-2 (Minor, record for the user).** AC10 and §7.1 ask for a shared tracing seam, but ruling R1 gives candidate runs a pass-through sink plus their own record. This is a sound privacy choice, but it is a controller ruling on a ticket AC, not a user decision.
- **m-3 (Minor).** A baseline rerun logs as a production `persisted_agent_invocation`, indistinguishable from a conversation turn, which inflates invocation metrics. This is accepted by ruling concern 2. Consider a marker field.
- **m-4 (Minor).** The UI history shows the newest completed baseline rerun of *any* revision without flagging a revision change, because currency flags read back null.
- **m-5 (Minor).** The baseline path's "no lock during the call" is proved only by a unit test (`in_transaction`). There is no PG `pg_locks` probe like the candidate's `:2272`.
- **Carried, still deferred and acceptable:**
  - Task 0: M2–M4.
  - Task 2: m1–m4.
  - Task 3: M-2..M-5.
  - Task 4: m-1 (IntegrityError not retried).
  - Task 6: the 100-run history cap and the history read with no auto-retry.
  - The leftover `tellr_int_*` PG databases (reported, not dropped).
  - The `JSON(none_as_null=True)` deviation is ruled sound. I checked that the evidence writers rely on SQL NULL, and the other tables are unaffected.

Counts: Critical 0 · Important 2 · Minor 5.

## 8. Declined to judge

- Production `run`'s lock state during graph-node model calls is pre-existing and not touched here.
- Third-party `openai`/`httpx` DEBUG loggers can emit request bodies. This is pre-existing and depends on the process log level.
- Whether `ChatDatabricks` honours `timeout`/`max_retries` rests on #266's probe precedent; I did not re-probe it live.
- I did not probe whether a NaN float in provider output (which JSONB rejects) can arise. If it can, the result is a 503 with no evidence row.
- The Task 2 concern-4 pre-existing async routes waiting on locks on the event loop are out of scope.
- The ledger note that `test_postgres_restricts_deletion_of_referenced_release_and_revision` passes via the 23514 trigger rather than the FK predates #267.
- The UI's visual and a11y quality beyond the recorded Vitest and Playwright gates.
- The P1–P9 product decisions themselves.

## 9. Verdict

**MERGE WITH LISTED FIXES.** The code on the branch is sound:
- the writers are atomic and correctly ordered;
- no lock is held across any model call;
- there is exactly one binding;
- the privacy rules hold on every surface;
- the baseline holds by cause, and PG passes with zero skips.

Two fixes are required before the local merge:
1. **I-1:** implement token capture, or record an explicit user decision that defers AC5's token clause, with an issue.
2. **I-2:** write the #269 L2 correction into the consumer carry-forwards, together with the corrected #267 residual note.

m-1 goes to #268's pre-pass. The other Minors are optional.
