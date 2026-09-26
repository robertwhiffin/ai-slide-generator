# Task 5 review — saved-draft structured-output probe (#266)

Reviewer: independent task reviewer. Range `3c39e9c72..50b47d5c6` (HEAD `53825d608` adds docs only).
Mutations ran in a temporary detached worktree, `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-266-5` at `50b47d5c6`. That worktree has since been removed. `.venv` was absent before and after, nothing was installed, and the review worktree was not mutated apart from adding this file.

## Spec Compliance: ✅ (with ⚠️)

The implementation matches the plan's letter and corrections C9, C11–C15, C19 and C21–C23:

- **One helper (C11).** `bind_structured_output_model` in `agent_runtime.py` is the only `with_structured_output(` call site.
- **Probe input (C12).** The probe signature is `probe(configuration)`.
- **Lock release (C13).** The candidate is copied inside `with session.begin():`, and the policy is re-checked after the locks are released. A new PostgreSQL proof covers this.
- **New test file (C14).** `test_graph_configuration_workbench.py` was created.
- **Route contract (C9).** The route:
  - reuses `_parse_lock_request` and `DraftLockRequest`;
  - returns `_conflict_response(outcome, client_candidate=None)` for 409;
  - adds only new strict sibling DTOs.
- **Unchanged runtime surface.** `run` keeps its arity, and #264 composition, #265 assembly and identity-sink ordering are untouched.

⚠️ items:
- **⚠️1. Two plan-mandated classifications cannot happen on the real provider path** (see I1).
  - The plan maps databricks-sdk `PermissionDenied` → 403 and binding-step `NotImplementedError` → 422.
  - With the pinned `databricks-langchain==0.9.0` / `openai 1.105.0`, `ChatDatabricks` raises neither. An inference 403 arrives as `openai.PermissionDeniedError`. `with_structured_output` raises only `ValueError`.
  - So the letter is met under fakes, but the intent ("inference permission denial → 403") is not met in production.
- **⚠️2. C19 ledger claim is inaccurate.** The report says "Everything is below `_LEGACY_SOURCE_ROLES`". In fact `DraftProbeCandidate` sits at `graph_configuration_draft.py:96`, above `:158`. The name does not contain `_LEGACY_SOURCE_ROLES`, so the text-read join is unaffected; `test_prompt_assembler.py` is green. See M2.

## Strengths

**Runtime binding**
- The helper extraction preserves `DatabricksModelAdapter.invoke` behaviour:
  - the client factory is still evaluated inside the `try`, before the model factory;
  - the kwargs are identical, since `**{}` expands to nothing;
  - the provider tuple is byte-identical, so `PermissionDenied` still collapses to `ModelProviderUnavailableError`, pinned by a new test.
- The probe's transport bound really reaches the OpenAI client. I measured `get_open_ai_client(timeout=30.0, max_retries=0)` through the real `ChatDatabricks` constructor. The runtime path passes no transport options.

**Payload rule**
- I measured the exact wire body the real `ChatDatabricks` sends: one user message with the constant prompt, plus `model`, `temperature`, `max_tokens`, and a tool named `_StructuredOutputProbeResponse` whose description is the class docstring.
- Nothing session-, user-, role- or draft-specific reaches the model.
- A tool-call response was parsed to the exact `ok` instance, which is a real SUCCESS on the production binding path.

**Lock handling and route**
- `read_draft_probe_candidate` writes nothing and returns only after the transaction exits.
- The `_validate_common` split keeps the issue order (actor, then lock_version, then agent_key) for all four existing callers.
- The probe runs off the event loop via `run_in_threadpool`, and a test guards that.

**Classification and tests**
- The probe never reads exception text; messages are code-owned constants. I measured this across 400/403/404/429/500 with a secret-bearing provider body.
- The PostgreSQL C13 proof is strong: it checks lock count and `idle in transaction` state on the probe's backend pid, and that a concurrent save commits while the probe is blocked.

## Issues

### Critical
None.

### Important

**I1 — `src/services/model_endpoint_probe.py:148,154`: `endpoint_probe_forbidden` (403) is unreachable in production.**

- **What.**
  - The probe catches only `databricks.sdk.errors.PermissionDenied`.
  - `ChatDatabricks` 0.9.0 always calls the endpoint through the OpenAI client (`workspace_client.serving_endpoints.get_open_ai_client(...)`), so an HTTP 403 raises `openai.PermissionDeniedError`.
  - Measured through the real `ChatDatabricks` with an httpx `MockTransport` returning 403, the result was `structured_output_probe_failed`, `retryable=True`, "Retry the probe." (cause `PermissionDeniedError`).
  - Binding-time `PermissionDenied` cannot happen either: `ChatDatabricks.__init__` does no network work.
- **Why.**
  - The plan's "inference permission denial → 403 endpoint_probe_forbidden" is the admin's most actionable outcome: grant the app's service principal CAN_QUERY on the endpoint.
  - In production it becomes a retryable 503, so the Task 6 UI will invite endless retries of a permanent failure.
  - The tests pass only because they raise the databricks-sdk type, which the production provider never raises.
  - This is distinct from the routed openai-400 item, but it has the same root: the classification was specified against SDK types, not the provider's actual exception types.
- **Fix.**
  - Also map `openai.PermissionDeniedError` (and probably `openai.AuthenticationError`) from `bound.invoke` to `_FORBIDDEN`.
  - Add a probe test that raises `openai.PermissionDeniedError(SECRET, response=httpx.Response(403, ...), body=None)` at invoke and asserts 403, non-retryable, and no leak.
  - The runtime adapter keeps its collapse, which is already pinned.
  - Sabotage-verify by removing the new except clause.
  - Cost: two lines plus one parametrised case. This is a classification-table change, so the controller should confirm it as a ruling first.

### Minor

**M1 — `model_endpoint_probe.py:146`: `422 unsupported_structured_output` is also production-dead with `ChatDatabricks` 0.9.0.**
- Its `with_structured_output` raises only `ValueError`, and for this call it raises nothing.
- The real "cannot do function-calling" signal is the openai 400 at invoke, which is already routed to the whole-branch review.
- **Measurement for that routed item.** Through the real `ChatDatabricks`, all of the following classify as `structured_output_probe_failed`, retryable:

  | HTTP status | Exception |
  |---|---|
  | 400 | `BadRequestError` |
  | 403 | `PermissionDeniedError` |
  | 404 | `NotFoundError` |
  | 429 | `RateLimitError` |
  | 500 | `InternalServerError` |

- The practical consequence: with the pinned provider, the probe's only observable outcomes are 200 and 503.
- A 404 (endpoint deleted since save) is also non-retryable in reality.
- **Fix:** decide at the whole-branch review, together with I1 and the 400 item.

**M2 — `graph_configuration_draft.py:96`: `DraftProbeCandidate` is placed above `_LEGACY_SOURCE_ROLES` (`:158`).**
- C19's ruling says "All #266 additions go below it", and the report claims compliance.
- It is harmless, because the text-read matches the exact name and does not reflow it.
- **Fix:** move it below `:158`, or correct the ledger wording.

**M3 — `model_endpoint_probe.py:98`: the 30 s bound is an httpx per-phase timeout, not a wall-clock budget.**
- Connect and each read are each ≤30 s, and there are no retries.
- `get_system_client()` and OAuth refresh are outside the bound (C8 parked).
- This is acceptable as ruled, but the docstring's "one attempt with a finite timeout" should not be read as "≤30 s total".

**M4 — `model_endpoint_probe.py:146`: `NotImplementedError` from the model factory is classified as unsupported.**
- The binding helper wraps both construction and `with_structured_output`, so a `NotImplementedError` raised by the model factory (constructor) also becomes "unsupported" (422).
- The docstring says "from the binding step", which is technically true, but it is broader than "capability rejection".
- Negligible in practice.

## Sabotage evidence

All mutations were applied by a Python replace with an anchor-count assert, in the temporary worktree.

### S1 — plan reviewer target `TASK5_REVIEWER_STRUCTURED_BINDING_SABOTAGE`, probe side

- **Mutation:** replaced `bound = agent_runtime.bind_structured_output_model(...)` in `model_endpoint_probe.py` with a direct `self._model_factory(...same kwargs incl. timeout/max_retries...).with_structured_output(_StructuredOutputProbeResponse)`.
- **Anchor / marker:** anchor count 1; marker `grep -c` = 1 at `:136` on the executed path.
- **Scope:** `pytest -q -p no:randomly tests/unit/test_agent_runtime.py tests/unit/test_model_endpoint_probe.py`
- **RED 2/75:**
  - `test_structured_output_runtime_and_model_endpoint_probe_share_one_helper`
  - `test_structured_output_binding_has_one_call_site_and_the_probe_has_none`
- **Note:** all 38 behavioural probe tests stayed green. Only the helper-identity and AST/text guards catch this bypass, which is exactly what C11 predicted and required.
- **Restore:** `git checkout 50b47d5c6 -- src/services/model_endpoint_probe.py`; marker 0; `git status` clean.

### S1b — same marker, runtime-adapter side

- **Mutation:** `DatabricksModelAdapter.invoke` builds and binds inline instead of calling the helper.
- **Anchor / marker:** anchor 1; marker 1.
- **Scope:** same as S1.
- **RED 5/75:**
  - `test_runtime_and_nodes_have_no_prompt_serialization_or_binding_bypass`
  - `test_prompt_assembler_is_the_only_payload_serializer_and_adapter_the_only_binder`
  - `test_structured_output_runtime_adapter_binds_through_the_extracted_helper`
  - `…share_one_helper`
  - `…one_call_site_and_the_probe_has_none`
- **Restore:** `git checkout 50b47d5c6 -- src/services/agent_runtime.py`; marker 0; clean.
- **GREEN:** 75 passed.

### S2 — own mutation on C13: model call inside a lock-holding transaction (`REV5_CALL_UNDER_LOCK_SABOTAGE`)

- **Mutation:** in `ModelEndpointProbeService.probe_saved_candidate`, wrapped the adapter call as `with session.begin(): self._configuration_factory().read_workbench(session); self._adapter.probe(...)`. This takes the FOR SHARE parent locks and holds them across the call.
- **Anchor / marker:** anchor 1; marker 1.
- **Unit scope:** `tests/unit/test_model_endpoint_probe.py tests/unit/test_graph_configuration_workbench.py`
  - RED 1/52: `test_model_endpoint_probe_service_holds_no_transaction_during_the_call`
- **PostgreSQL scope:** `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres pytest tests/integration/test_agent_definition_workbench_postgres.py -k model_endpoint_probe`
  - RED 1/1: `test_model_endpoint_probe_holds_no_lock_while_the_model_call_is_in_flight`, with `assert 16 == 0` (16 locks held by the probe's backend).
- **Restore:** `git checkout 50b47d5c6 -- src/services/model_endpoint_probe.py`; marker 0; clean.
- **GREEN:** unit 52 passed; PostgreSQL 1 passed.

### Blast-radius gates (temporary worktree at `50b47d5c6`)

**Focused unit run: 993 passed, 0 failed.** Files: `test_agent_runtime`, `test_persisted_agent_runtime`, `test_graph_nodes`, `test_model_endpoint_probe`, `test_graph_configuration_workbench`, `test_agent_definition_workbench_routes`, `test_graph_configuration_draft`, `test_prompt_assembler`, `test_agent_schema_registry`, `test_model_endpoint_catalog`, `test_ci_collects_integration_tests`, `test_endpoint_name_policy_client_join`, `test_app_wheel_dependencies`.

**Full `tests/unit -p no:randomly`: 6 failed / 6127 passed / 110 skipped.** The six are exactly the baseline nodes:
- `test_deploy_autoscaling` ×2
- `test_style_exclusivity_chokepoint` ×3
- `test_style_exclusivity_persistence_boundary` ×1

**PostgreSQL, one file per invocation, zero skips:**

| File | Passed |
|---|---|
| `test_agent_definition_workbench_postgres` | 17 |
| `test_persisted_graph_runtime_failures_postgres` | 7 |
| `test_agent_schema_overlay_postgres` | 10 |

### Provider measurements

- Scripts are in `/tmp/rev2665/measure.py` and `measure2.py`.
- They use the real `ChatDatabricks` 0.9.0, with a stub workspace client whose `get_open_ai_client` returns an `openai.OpenAI` over an httpx `MockTransport`. There was no network access.

## Task quality: Needs fixes

I1 is the one blocking item. Without it, one of the probe's three typed failures can never be produced by the real provider, and a permanent permission failure is presented as retryable. The fix is small and testable. The Minors can ride with the whole-branch review alongside the routed openai-400 item.
