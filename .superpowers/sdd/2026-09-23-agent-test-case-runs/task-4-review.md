# Task 4 review — test run execution and persistence (#267)

Reviewer: independent task reviewer. Range `b678b48fd..faed7772f` (HEAD `07d4cf874` adds one docs commit).
Temp worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-267-4` (detached at `faed7772f`). pytest was run from inside it. The worktree has been removed.

## Spec Compliance: ❌ (two controller rulings unimplemented) ⚠️

All of the brief, as corrected by C8, C10, C15–C17, C20, C27, C32, C33, C36, C37 and Task 3's M-1, is met in code and tests. Two exceptions are the controller's own Task 4 rulings, which `progress.md` records as not yet implemented. They are required changes (I-1, I-2).

| Clause | Status | Where |
|---|---|---|
| C8.1 RuntimeError if `in_transaction()` on entry | ✅ | `_require_no_transaction`; `test_an_executor_refuses_a_session_already_in_a_transaction[candidate/baseline]` |
| C8.2/C32 txn 1 = the probe read (lock-pinned, FOR SHARE, then commit) + a short case/baseline txn | ✅ | `read_draft_test_candidate` → `_read_saved_candidate`; `_read_case_and_baseline` |
| C8.3 model call with no open transaction | ✅ | explicit assert before the call; unit tests for both paths; PG in-flight test shows 0 `pg_locks` and not `idle in transaction` |
| C8.4 txn 2 = `_lock_current_parents(exclusive=False)` first, re-read hash/active, insert the txn-1 identity verbatim | ✅ | `_persist_run`. Nothing queries before the parent lock (`expire_all` issues no SQL) |
| C8.5 persisted even when state moved; `candidate_is_current` / `base_release_is_current` returned, not persisted | ✅ | `_currency`; the draft-saved, case-retired and publication-during-call tests |
| C8.6 one retry on the handoff diagnosis only; otherwise 503; model never re-invoked | ✅ | string-equality check; the model call is outside the retry loop by construction |
| C10/C37 all-role projection; `nodes.py` and the seed unedited; builder byte parity | ✅ | `agent_model_payload.py`; `nodes.py`, `graph_configuration_seed.py`, `agent_runtime.py` and `graph_configuration_workbench.py` have an empty diff over the range |
| C15 raw output: the observer for candidates; structured output = `model_dump` + `additional_fields` | ✅ | — |
| C16 status map, code-only `error_detail`, 503 with no row on a DB failure | ✅ | — |
| C17 one check derived from the runtime; no second `model_validate` | ✅ | — |
| C20 baseline filter and order; outputs copied at insert; no verdict read | ✅ | five dedicated tests |
| C27 / M-1 identity from the snapshot; no `-1` in the row or evidence | ✅ | `test_no_candidate_sentinel_reaches_the_evidence_or_its_row` |
| C33 default runtime is `get_agent_test_runtime()` | ✅ | — |
| Ruling (concern 1): public additive runtime hook in place of `copy.copy` and private imports | ❌ | I-1 |
| Ruling (concern 3): endpoint name policy re-checked before a baseline rerun | ❌ | I-2 |

⚠️ The executor lock-order proof against #269's publication is instrumentation-based (m-2). The real two-order proof is #269 Task 4's, as already carried.

## Strengths
- **The C8 shape is exact and easy to audit.**
  - The model call sits between two `with session.begin()` blocks, with nothing but frozen dataclasses crossing it.
  - The retry loop wraps only transaction 2, so no path can re-invoke the model. That holds even if #269's future `_lock_current_parents` retry composes with this one: at most 2×(inner) lock attempts, and one model call.
  - Transaction 2's first SQL is `_lock_current_parents`: one statement, `FOR SHARE OF graph_release, graph_draft`. That is #269's global order, release then draft.
  - FK `KEY SHARE` on `agent_test_case` is compatible with #269's L2 `FOR SHARE`. It can wait on a case writer's `FOR UPDATE`, but case writers take no L0, so there is no cycle.
- **#266's probe is unchanged.**
  - `_read_saved_candidate` returns the same `snapshot.nodes` draft that `_draft_aggregate_snapshot` builds `definitions` from, so the projected `DraftProbeCandidate` has identical values.
  - `git diff b678b48fd..faed7772f` over every probe test file (`test_model_endpoint_probe.py`, `test_probe_failure_contract_client_join.py`, `test_graph_configuration_workbench.py`) is empty. `test_model_endpoint_probe.py` was in my mutation scope and stayed green.
- **Payload parity is enforced as a chain.**
  - `test_graph_nodes.py` pins every production call's payload keys with `set(payload) == allowed`, against the fixture literals.
  - `test_agent_model_payload.py` pins `MODEL_PAYLOAD_KEYS[role]` to the per-role union of those literals, and the builder's set to `nodes._BUILDER_MODEL_PAYLOAD_KEYS`.
  - A new production key therefore REDs `test_graph_nodes` first. The fixture update then REDs the union test. Nothing can be dropped silently.
  - The fixture literals are byte-verbatim moves. The test_graph_nodes node-ID list is unchanged (166 → 166, plus one new test).
  - The `previous_deck_review` author-strip matches `architect_node` (`nodes.py:1430-1436`).
- **Evidence integrity.**
  - There is one INSERT and no UPDATE path; `refresh` is a read.
  - `error_detail` is always a code or `code:Class`. The unexpected-error test proves provider text reaches neither the row nor the evidence.
  - The 503 log carries `{agent_key, phase, error_class}` only.
  - `none_as_null` columns receive Python `None` for absent baseline and output fields.
- **Identity for #269.**
  - Candidate rows carry `run_kind='candidate'`, `candidate_hash` = the draft hash, and `compared_*` = the draft's base release and its mapped revision. `_lock_current_parents` enforces base == active, so base is the active release at transaction 1.
  - Baseline rows carry `published_baseline`, the revision `content_hash`, the active release and the revision. `test_a_baseline_rerun_records_the_published_revision_not_the_edited_draft` closes the equal-hash blind spot.
- **Baseline rerun.**
  - It goes through the real `run`, and the loader resolves historical releases (there is no `effective_to` filter). A publication racing the rerun therefore still runs, and records, v1 with `base_release_is_current=False`.
  - Raw output uses the same `_supplied_output_keys` + `to_jsonable_python(fallback=str)` as the candidate observer.
  - Currency for a baseline means "the active release still maps this revision, and the case is still active". Reads return `None`, which is what Task 5 needs (carried).
- **Implementer claims re-probed.** I re-ran the focused scope (378 passed) and PG workbench (24 passed, 0 skipped). My independent S1 measurement matches the implementer's M21 (RED 1).

## Issues

### Critical
None.

### Important
- **I-1 (controller ruling, concern 1): replace the per-run runtime copy with an additive public hook.** Not implemented.
  - `_observed()` does `copy.copy(runtime)` and assigns `observed._model_adapter = _ObservingModelAdapter(...)`. That monkey-wraps a private attribute on a shallow copy of an `lru_cache`d runtime.
  - The workbench imports the private `_classify_candidate_failure` and `_supplied_output_keys` from `agent_runtime`.
  - Any future runtime state derived from `_model_adapter` at construction time (a bound method, a wrapped client, `__slots__`) would bypass the observer silently.
  - The baseline path also re-implements classification outside the runtime.
  - **Required:** an additive public hook in `agent_runtime.py`, for example:
    - an optional observer argument on `run_candidate` that records the prompt, latency and raw keys;
    - a baseline entry that mirrors `run` with that observer and returns a classified outcome.
  - `run` and `get_agent_runtime` must stay AST-identical (extend the existing AST guard and call-site guards). The workbench must import no `_`-prefixed runtime name.
  - I agree with the ruling. The copy is not wrong today, because nothing else reads `_model_adapter`, but it is an unpinned coupling to Task 3's internals.
- **I-2 (controller ruling, concern 3): re-check the published endpoint name against the name policy before a baseline rerun.** Not implemented.
  - `execute_baseline_rerun` passes `node.published.content.model.endpoint_name` straight to `run`, and on failure stores it inside `error_detail = "endpoint_unavailable:<name>"`.
  - A URL- or path-shaped name in a restored, legacy or hand-seeded revision would reach the provider and be written into evidence. The candidate path refuses such a name before any call (`test_a_url_shaped_stored_endpoint_is_refused_before_any_call`).
  - **Required:** after transaction 1 commits and before the call, run `_endpoint_name_policy_validator` on the published content. On refusal, raise the same typed rejection with no call and no row.
  - Add the baseline twin of the URL-shaped test, and a sabotage (drop the re-check → RED).
  - I agree with the ruling (defence in depth, one cheap check, and #266's whole-branch m8 asks the same of publication).

### Minor
- **m-1 (S1b survivor):** nothing pins that a SQLAlchemy `IntegrityError` at the insert is *not* retried. Adding a retry branch for it left 378/378 unit and 24/24 PG green.
  - It is near-equivalent: an insert IntegrityError is deterministic here, so a retry fails again and gives the same 503, and the model is never re-invoked.
  - Suggest one unit test that injects an `IntegrityError` at flush and asserts a single transaction-2 attempt, `TestRunUnavailable` and no row.
- **m-2:** transaction 2's lock-order proof is instrumentation-based.
  - My S2 (draft `FOR SHARE` taken before `_lock_current_parents`) REDs the holder test only because the pid hook never sees the parent lock reached (`assert 1 == 2`, "transaction 2 never reached its parent lock"). It is not a deadlock detection.
  - The true release→draft versus draft→release proof is #269 Task 4's `test_test_run_insert_and_publication_serialize_without_deadlock`, already carried. It needs no action in #267, but the whole-branch review should not count the holder test as that proof.
- **m-3:** the baseline path has only the unit no-open-transaction proof, on the workbench session. There is no PG `pg_locks` probe while a baseline call is in flight.
  - `run`'s loader opens and closes its own session inside `resolve`, so the risk is low. A PG twin of the in-flight test for `execute_baseline_rerun` would close it.
- **m-4:** byte-identical prompt parity exists for the builder only, as C10.5 required. The other six roles are pinned at key-set level.
  - This is acceptable, because a stored case payload's values are admin input with no production value to compare against. Record it as the scope of the parity claim.
- **m-5 (Task 5 carry):**
  - `get_test_run` and `list_test_runs` open `session.begin()`, so the route must hand them a session with no autobegun transaction.
  - `TestRunUnavailable` is raised `from` the driver error. The route must not log it with `exc_info`, or driver or provider text reaches the log.

## Sabotage evidence

All mutations ran in `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-267-4` (a detached worktree at `faed7772f`), with pytest run from inside it.

- **Driver:** `/tmp/rev-267-4/mut.py <ID>`. It asserts that each anchor occurs exactly once, and prints the marker count.
- **Runner:** `/tmp/rev-267-4/run.sh`, which runs:
  - `PYTHONPATH=<tree>:<tree>/packages/databricks-tellr DATABASE_URL=sqlite:////tmp/rev-267-4.sqlite /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly -rf`;
  - **UNIT** = `tests/unit/test_agent_test_workbench.py tests/unit/test_agent_model_payload.py tests/unit/test_graph_nodes.py tests/unit/test_model_endpoint_probe.py` (bounded by `timeout 600`);
  - **PG** = `tests/integration/test_agent_definition_workbench_postgres.py` with `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres` (`timeout 300`, `faulthandler_timeout=120`), zero skips.
- **Restore:** `git checkout faed7772f -- <file>`, then `grep -c REV267_4 <file>` = 0 and `git status --short` empty.
- **GREEN before and after every row:** UNIT 378 passed, PG 24 passed.

| Id | Mutation | Anchor | Marker (`grep -c`) | RED |
|---|---|---|---|---|
| S1 (assigned: retry fires on ANY integrity error) | `if attempt == 1 and str(error) == _PARENT_HANDOFF_DIAGNOSIS:` → `if attempt == 1:` | 1 | `REV267_4_S1` = 1 | UNIT **1 failed** / 377 passed: `test_a_second_handoff_race_or_another_integrity_failure_is_unavailable[1-graph configuration must have exactly one active release]`. PG 0/24. The model was not re-invoked: the existing `len(adapter.calls) == 1` assertions held in the handoff tests. |
| S1b (variant: also retry a SQLAlchemy `IntegrityError`) | add `except IntegrityError: if attempt == 1: continue` before the `SQLAlchemyError` branch | 1 | `REV267_4_S1b` = 1 | **SURVIVED:** UNIT 378/378, PG 24/24 → m-1 (near-equivalent; no model re-invocation possible) |
| S2 (own: txn 2 locks draft before release) | `session.execute(select(GraphDraft).with_for_update(read=True)).all()` before `_lock_current_parents` in `_persist_run` | 1 | `REV267_4_S2` = 1 | PG **1 failed** / 23: `test_candidate_run_insert_waits_behind_an_exclusive_parent_holder_without_deadlock` (`AssertionError: transaction 2 never reached its parent lock`, `assert 1 == 2`). UNIT 0/378. See m-2. |
| S3 (own: insert uses the re-read identity) | `candidate_hash=` the current `GraphDraftAgent.candidate_hash` re-read in txn 2 (candidate runs) | 1 | `REV267_4_S3` = 1 | UNIT **1 failed**: `test_a_draft_saved_during_the_call_is_recorded_as_not_current`. PG **1 failed**: `test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight` |
| S4 (own: projection drops a genuine key) | `"build_reviewer": _SLIDE_REVIEW_KEYS` (drops the re-review's `deck_brief`) in `agent_model_payload.py` | 1 | `REV267_4_S4` = 1 | UNIT **2 failed**: `test_each_role_key_set_is_the_union_of_its_production_calls[build_reviewer]`, `test_the_seed_projection_drops_exactly_the_identifier_keys[build_reviewer]`. PG 0/24 |

No mutation hung. S2's PG run took 26 s, including the test's 10 s bounded wait.

**Full unit suite** at `faed7772f`, run from the temp worktree: **6 failed, 6477 passed, 110 skipped, 136 warnings**. The failures are exactly the baseline cause-set:
- `test_deploy_autoscaling` ×2;
- `test_style_exclusivity_chokepoint` ×3;
- `test_style_exclusivity_persistence_boundary` ×1.

`test ! -e .venv` held before and after.

**Leftover databases.** Listed via the `postgres` maintenance database only, with `pg_database` and `pg_stat_file(PG_VERSION)`. None were dropped.
- Older than today: `tellr_int_5a18c26f8a6d4b92` (2026-09-16 13:53), `tellr_int_0da9e060782d46f8` (2026-09-16 14:02), `tellr_int_ac9b0f3b9eeb4737` (2026-09-16 14:09).
- Today: `tellr_int_6f336988c6484306` (2026-09-26 07:57). This is probably the Task 4 implementer's killed M30 run.

## Task quality verdict: Needs fixes

The implementation is careful, and the C8 transaction shape, evidence identity and payload chain are sound. There are no Critical issues. Two Important required changes are outstanding, both the controller's rulings: I-1, the public runtime hook in place of `copy.copy` and the private imports; and I-2, the endpoint-policy re-check before a baseline rerun. Fix them in one round, with a sabotage for each. The Minors can be deferred; m-1 is a one-test addition worth taking in the same round.
