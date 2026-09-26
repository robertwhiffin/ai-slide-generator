# Task 5 report: test run routes (#267)

**Status:** DONE_WITH_CONCERNS
**TASK_BASE:** `e52c0a3d78949739bfb15233f8343ec038028ccd`
**Commits:**
- `71650243c`: `feat: test run execute and read routes (#267)`. It adds the routes, the DTOs, a one-guard service change and the RED-first unit tests.
- `d140e644d`: `test: pin the test run routes end to end over PostgreSQL (#267)`.

## Routes

All four routes are on the existing router, `/api/admin/agent-definitions` (C23, C36). `main.py` is untouched.

| Method and path | Handler | Body | Success |
|---|---|---|---|
| `POST /draft/{agent_key}/test-runs` | async, `run_in_threadpool` | exactly `{"test_case_id": int, "lock_version": int}`. Strict; id 1..2^31-1, lock >= 0 | 201 `TestRunEvidenceResponse` |
| `POST /published/{agent_key}/test-runs` | async, `run_in_threadpool` | exactly `{"test_case_id": int}`, with no `lock_version` | 201 `TestRunEvidenceResponse` |
| `GET /test-runs/{run_id}` | def | none | 200 `TestRunEvidenceResponse` |
| `GET /test-cases/{test_case_id}/runs?limit=20` | def | none | 200 `{"items": [TestRunEvidenceResponse, ...]}`, newest first, limit 1..100 |

- **#268's path:** its verdict route extends the run path as `POST /test-runs/{run_id}/verdict`. The plan's `/api/admin/agent-test-runs/...` shape is superseded.
- **Collisions (C38):** no new path contains `model-endpoints`, `model-endpoint-probe` or `structured`, and no (method, path) pair appears twice. Both are pinned.
- **Workbench dependency:** `get_agent_test_workbench()` returns `AgentTestWorkbench()` and builds nothing. The first run resolves the bounded `get_agent_test_runtime()` (C33). The plan's `get_agent_runtime()` is overridden by C33.

## Response shape

`TestRunEvidenceResponse` is a strict sibling DTO (`extra="forbid"`) that extends no other class. Its fields:
- `run_id`
- `run_kind`: `candidate` or `published_baseline`
- `test_case_id`, `test_case_version`, `agent_key`
- `candidate_hash`: sha256
- `compared_release_id`, `compared_definition_revision_id`
- `synthetic_payload`, `model_payload`
- `assembled_prompt`: nullable
- `execution_status`: `completed`, `model_error`, `assembly_error` or `incomplete`
- `error_detail`: nullable
- `deterministic_checks_passed`
- `deterministic_check_results`: a list of `{name, passed, message, issues}`
  - `name` is `output_contract` or `execution`;
  - `message` is nullable;
  - each issue is `{code, field}`, with `field` nullable.
- `candidate_raw_output`, `candidate_structured_output`, `baseline_raw_output`, `baseline_structured_output`: each nullable
- `latency_ms`, `input_tokens`, `output_tokens`: each nullable
- `run_by`, `run_at`
- `candidate_is_current`, `base_release_is_current`: `bool` or `null`

Rules:
- **Verdict fields are absent,** not null.
- **The currency flags are nullable, not omitted.** An execute response carries booleans. GET run and GET list return `null`. This keeps one DTO for all four routes.
- **Release and revision ids are bounded `ge=1`.** A forged `-1` evidence fails to serialize, so the response is a 500 that contains no `-1`. `test_a_sentinel_identity_never_serializes` pins this.
- **Only evidence-row data goes out.** The one exception is `synthetic_payload`, which comes from the run's own immutable case version.
  - The assembled prompt and the raw and structured outputs are included, because the Input and Compare views need them.
  - No exception, provider or driver text is returned, and no phase name.
  - `error_detail` is a code only.

## Refusals, in the executor's order

| Refusal | HTTP | Body |
|---|---|---|
| missing or blank principal | 403 | `{"detail": "Authenticated principal required"}`, before any body read or service call |
| non-admin | 403 | `{"detail": "Admin access required"}`, on all 4 routes, before any body read or service call |
| malformed JSON, unknown or deterministic role, or strict-DTO failure | 422 | `invalid_draft` envelope, in `_parse_lock_request` order |
| stale lock (candidate) | 409 | `_conflict_response(outcome, client_candidate=None)`, code `stale_draft` |
| URL-shaped endpoint | 422 | `invalid_draft`, field `candidate.model.endpoint_name` or `published.model.endpoint_name`, via `_rejection_response` |
| unknown case | 404 | `{"detail": "Test case not found"}` |
| case of another role | 422 | `invalid_test_case`, with field `test_case_id` and code `agent_key_mismatch` |
| inactive case version | 409 | `stale_test_case`, the same body as Task 2's |
| `TestRunUnavailable` (database outage, no row written) | 503 | `{"code": "test_run_unavailable", "message": "Test run storage is temporarily unavailable. Retry the request.", "retryable": true}` |
| `GraphConfigurationIntegrityError` | 500 | `{"detail": "Graph configuration is incomplete"}` |
| model or provider failure | 201 | a persisted `model_error` evidence row (C33) |
| GET of an unknown or out-of-range run id | 404 | `{"detail": "Test run not found"}` |
| GET runs of an unknown case | 404 | `{"detail": "Test case not found"}` |
| GET runs with a `limit` out of range | 422 | `invalid_test_case`, field `limit`, code `out_of_range`. A non-integer `limit` gets FastAPI's default 422, as in Task 2's m1. |

**Service change:** one guard in Task 4's file. `list_test_runs` now raises `TestCaseNotFound` for an unknown case; before, it returned `[]`. It has a new service test, plus one that an existing case with no runs lists empty.

## RED evidence, before implementation

- **Route scope:** 113 failed.
  - 112 failed with `AttributeError: module 'src.api.routes.agent_definitions' has no attribute 'get_agent_test_workbench'`.
  - The path test failed because the routes did not exist.
- **Service scope:** 1 failed, `test_list_test_runs_of_an_unknown_case_is_not_found`, because no `TestCaseNotFound` was raised.
- **Raw output:** `/tmp/t267-5/red.txt`.

## Clause-to-mutation table

- **Driver:** `/tmp/t267-5/mutate.py`. **Log:** `/tmp/t267-5/mutations.log`.
- **Pin:** `71650243c2fda0c820ebbad4b71efb3f205e0656`.
- **Scope:** `tests/unit/test_agent_definition_workbench_routes.py` and `tests/unit/test_agent_test_workbench.py`, 523 tests.
- **Every row held these invariants:**
  - anchor count 1;
  - marker `MUT267_5_<id>` count 1 while mutated;
  - restored with `git checkout <pin> -- <file>`, leaving marker count 0 and a clean status;
  - GREEN 523 afterwards.

| id | clause | mutation | RED (failing tests) |
|---|---|---|---|
| M1 | admin gate (the plan's controller sabotage) | router `dependencies=[]` | 20, every non-admin test, including `test_test_run_routes_deny_non_admins_before_body_or_service[candidate/baseline/get_run/list_runs]` |
| M2 | principal on the candidate route | actor dependency replaced by a constant | 3: `test_test_run_executes_require_a_trusted_principal_before_body_or_service` for both principals on candidate, and `test_candidate_run_returns_201_with_the_exact_evidence_row` |
| M3 | off the event loop (the C36 sabotage) | call the executor directly | 2: `test_test_run_routes_call_the_model_off_the_event_loop[candidate/baseline]` |
| M5 | strict candidate body | `CandidateTestRunRequest(BaseModel)` | 28: the 24 candidate cases of `test_a_run_body_cannot_choose_any_server_owned_input`, and `test_a_candidate_body_is_strictly_typed[id-string/id-bool/id-float/lock-string]` |
| M6 | baseline body takes no lock | add an optional `lock_version` | 1: `test_a_baseline_body_does_not_accept_a_lock_version` |
| M7 | unknown role refused before the DTO | drop the check | 4: all four cases of `test_a_run_of_an_unknown_or_deterministic_role_is_the_unknown_agent_422` |
| M8 | stale lock maps to `_conflict_response` 409 | return the stale-case 409 instead | 2: `test_a_stale_lock_is_the_probes_409_with_no_model_call_or_row` and `test_a_stale_lock_is_refused_before_an_unknown_case` |
| M9 | role mismatch is a 422 | map it to 404 | 2: both cases of `test_a_run_of_another_roles_case_is_the_ordered_case_422` |
| M10 | inactive case is a 409 | map it to 404 | 2: both cases of `test_a_run_of_a_superseded_case_version_is_409_stale` |
| M11 | `TestRunUnavailable` maps to 503 | change the clause to `except KeyError` | 4: both cases of `test_a_database_failure_after_the_model_call_is_503_with_no_row` and both of `test_test_run_unavailable_from_any_phase_is_the_503` |
| M12 | no `-1` serializes | make the compared ids plain `int` | 1: `test_a_sentinel_identity_never_serializes` |
| M13 | verdict fields absent | add a `verdict` field | 5: `test_candidate_run_returns_201_with_the_exact_evidence_row`, `test_baseline_rerun_returns_201_with_published_identity`, both cases of `test_a_model_failure_is_201_evidence_with_a_code_and_no_provider_text`, and `test_an_incomplete_run_serializes_its_check_issues` |
| M14 | reads return null currency flags | force both flags True | 2: `test_get_test_run_returns_the_stored_evidence_with_null_currency` and `test_list_case_runs_returns_newest_first_bounded_by_limit` |
| M15 | unknown case lists as 404 (service) | drop the guard | 2: `test_list_case_runs_of_an_unknown_case_is_404[424242]` and `test_list_test_runs_of_an_unknown_case_is_not_found` |
| M16 | GET run-id bound | `if False` | 1: `test_get_test_run_of_an_unknown_or_unstorable_id_is_404[9223372036854775808]`, from SQLite's overflow |
| M17 | `limit` range check | `if False` | 3: `test_list_case_runs_rejects_an_out_of_range_limit[0/-1/101]` |
| M18 | body id at most 2^31-1 | drop `le` | 1: `test_a_candidate_body_is_strictly_typed[id-over-int32]` |
| M19 | candidate route returns 201 | drop `status_code=201` | 7, including `test_candidate_run_returns_201_with_the_exact_evidence_row` |
| M20 | endpoint policy is a 422 | drop the `DraftContentRejected` mapping | 2: `test_a_url_shaped_saved_endpoint_is_the_422_with_no_model_call` and `test_a_url_shaped_published_endpoint_is_the_422_with_no_model_call` |
| M21 | lazy, bounded runtime dependency | build the runtime eagerly | 1: `test_the_production_workbench_dependency_uses_the_bounded_test_runtime` |
| M23 | model failure is 201 evidence | map `model_error` to 503 | 2: both cases of `test_a_model_failure_is_201_evidence_with_a_code_and_no_provider_text` |
| PG-a | body bound on PostgreSQL | drop `le` in the schema | PostgreSQL RED 1: `test_run_routes_over_postgres_serve_evidence_and_refuse_unstorable_ids` |
| PG-b | route run-id bound on PostgreSQL | `if False` | Survived on PostgreSQL, as expected. See the note below. |

**Why PG-b survives:** PostgreSQL compares an out-of-range literal against an integer column without error. So the route-level bound is defence in depth, and only SQLite's 2^63 overflow exposes it (M16). The test's docstring says this.

**Plan sabotage targets:**
- **Controller** ("remove require_admin from the execute route"): the routes inherit the router's gate, so the single-anchor equivalent is M1. It turns `test_test_run_routes_deny_non_admins_before_body_or_service[candidate]` RED, and its three siblings.
- **C36** ("call the executor directly"): this is M3. It turns both loop-observer tests RED.
- **Suggested fresh reviewer target:** make `_execute_test_run` return `_test_case_stale_response` for a `DraftSaveConflict`. The predicted RED is `test_a_stale_lock_is_the_probes_409_with_no_model_call_or_row`.

## Gates

- **Focused:** 677 passed. The files were the routes file, `test_agent_test_workbench`, `test_agent_runtime` and `test_model_endpoint_probe`. The routes, workbench and runtime files alone: 631 passed.
- **Full unit suite** (`tests/unit -q -p no:randomly -rf`, SQLite `DATABASE_URL`): 6 failed, 6600 passed, 110 skipped, 136 warnings. The six failures are exactly the baseline, with the same causes:
  - autoscaling ×2;
  - chokepoint `_FakeSession.execute` ×3;
  - persistence-boundary "no active Graph Release" ×1.
- **PostgreSQL** (`postgresql+psycopg2://localhost:5432/postgres`), one invocation each, zero skips:
  - workbench file: 25 passed. That is the previous 24 plus the new route test, which is enrolled in this file.
  - runtime failures: 7 passed.
- **ruff:** the same as base on every touched file.
  - The routes, schemas and service files and the PostgreSQL test file are clean.
  - The routes test file keeps its two findings that were already there at base: I001 at line 1 and F401 `SCHEMA_CONTRACT_BUNDLES`.
- **Environment:** `test ! -e .venv` held before and after. Nothing was installed. The frontend, `main.py` and the dev database were not touched.

## Concerns

1. **`run_by` is in the response.**
   - The plan says the DTO serializes every field of `TestRunEvidence`, and `TestCaseResponse` already returns `created_by` and `updated_by`.
   - The brief says "no session or user identifiers". I read that as: no session ids, and no user identity except the audit actor.
   - `test_a_run_body_carries_no_sentinel_session_or_extra_user_identifier` pins two things. The actor appears only in `run_by`. And no seeded session identifier reaches `model_payload` or `assembled_prompt`, for architect, data_analyst, builder or deck_reviewer.
   - `synthetic_payload` still holds the seed's synthetic `session_id` values by design (C37.6: the Input view shows what was dropped).
   - If the controller disagrees, drop `run_by`.
2. **The run routes use two envelopes.**
   - Body, lock, role and endpoint errors use `invalid_draft`, as the probe does.
   - Case-level errors use Task 2's `invalid_test_case` and `stale_test_case`.
   - So Task 6 must handle two 422 codes and two 409 codes: `stale_draft` and `stale_test_case`.
3. **A 503 after the model call means a retry calls the model again.** The response says `retryable: true`.
4. **The run history is per case version,** not per lineage. A superseded id still lists its own runs and is not a 404, because those runs are evidence for that version.
5. **The GET routes do not catch `SQLAlchemyError`.** A database outage on a read is a 500, as on Task 2's list route.
6. **The plan's review question says stale is a 404.** I followed the brief's order instead: an inactive version is a 409 `stale_test_case`, and a missing one is a 404.
