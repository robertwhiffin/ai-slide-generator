# #267 whole-branch fix wave — report

- FIX_BASE: `b0c4d8aebc7f275b04d7158334964a120b6c081d`
- Fix commit: `9f63281bec7cfe9232e2e5e9510a534b20934865` — `feat: record provider token usage on test runs (#267)`
- Status: DONE (I-1 fixed; no frontend change)

## I-1 — token usage when available (AC5, spec §5.5)

### Measurement (databricks-langchain 0.9.0, langchain-core 1.5.3, real `ChatDatabricks` over `httpx.MockTransport`)
- Body WITH `usage`: the AIMessage has `usage_metadata = None`; the counts are in
  `response_metadata["usage"] = {"prompt_tokens", "completion_tokens", "total_tokens"}`
  (also flattened into `response_metadata` and `LLMResult.llm_output`). There is no `token_usage` key.
- Body WITHOUT `usage`: none of these keys is present.
- LangChain's `UsageMetadataCallbackHandler` records `{}` in both cases, because it reads only `usage_metadata`. So a stock usage callback would silently never capture anything.
- `include_raw=True` also exposes the same `response_metadata`. It was not used because it turns a parse failure into a `parsing_error` value instead of raising, which would change the test path's `incomplete` classification.

### Change
- `bind_structured_output_model` (the one helper) still makes the single `model.with_structured_output(schema)` call. It then:
  - returns that object unchanged unless a test run is being observed;
  - when one is observed, returns `.with_config(callbacks=[_TokenUsageCallback])`. The callback's `on_llm_end` reads `usage_metadata` first, then `response_metadata["usage"]`, then `["token_usage"]`, and accepts only non-negative non-bool ints.
- "Observed" means the private `ContextVar` `_OBSERVED_TEST_RUN`. `_run_resolved`'s callback sets it only when `_observation is not None` (test runs only), and only around the one adapter call. It is reset in the `finally`.
- `RunObservation` gains `input_tokens` / `output_tokens` (default `None`).
- There is a public `report_model_token_usage(...)` seam, which is a no-op outside an observed call. The deterministic fake adapter uses it (`usage=(in, out)`).
- `agent_test_workbench`:
  - `_Execution` carries the tokens from the observation;
  - `_persist_run` writes them instead of the hard-coded `None`.
- Both run kinds get the tokens through the same `_run_observed` path.
- Usage is also persisted for an `incomplete` run: the tokens were spent before validation rejected the output.

### Constraints checked
- `run`, `get_agent_runtime`, `get_agent_test_runtime` and `DatabricksModelAdapter.invoke`: `ast.dump` is identical to FIX_BASE.
- The production adapter's `model_factory` kwargs are unchanged (the existing `:645-677` pins are green and unedited). Production binds with no `include_raw` and no wrapper (new guard).
- There is exactly one `with_structured_output(` in `src` (`agent_runtime.py:444`). All the existing count and AST guards are green.
- The #266 probe files are untouched and `test_model_endpoint_probe.py` is green.
- Neither log record changed. Usage is not added to `persisted_agent_invocation` or to `agent_candidate_run`.
- The prompt-parity and structured-output tests are unedited and green.

### Tests added
- `tests/fixtures/mock_chat_completions.py` (new): a MockTransport workspace in the style of #266. It echoes the bound tool name and adds `usage` only when given (123/45).
- `tests/unit/test_agent_runtime.py`:
  - the real provider records usage for a candidate run and a baseline run;
  - with no usage, both counts are None;
  - a fresh observation starts at None;
  - **production-unchanged guard** `test_production_run_binds_exactly_as_before_and_reads_no_usage`: under production `run` against a usage-reporting endpoint, `with_structured_output` gets only `(schema,)` and the helper returns exactly that object;
  - a fake-adapter usage report fills only an observed run.
- `tests/unit/test_agent_test_workbench.py`:
  - the real provider persists 123/45 for the candidate and the baseline rerun (evidence and row);
  - with no usage, both runs persist NULL;
  - the fake adapter's `(11, 7)` is persisted for both kinds;
  - usage is kept on an `incomplete` run.
- Frontend: the existing Vitest `displays missing token usage as "not reported" and reported usage as numbers (P9)` passes (1200/340 shown). No frontend change.

### Sabotage
Each run: anchor count 1, `grep -c` marker 1, full-file scope, then restored with `git checkout 9f63281be… -- <file>` (marker 0), GREEN.

| # | Sabotage | RED |
|---|---|---|
| S1a | helper returns the bound model without the usage callback | runtime `…records_the_reported_token_usage`, workbench `…persist_the_reported_tokens` (2/257) |
| S1b | `_persist_run` writes `input_tokens=None` | workbench real-provider, fake-adapter and incomplete-run tests (3/144) |
| S2a | helper gate removed (always attaches the callback) | the production guard, plus 9 recording-double tests (10/470) |
| S2b | `_run_resolved` observes every call, production `run` included | the production guard (`RunnableBinding != bound`), plus 7 `test_persisted_agent_runtime` tests (8/584) |

## Gates
- `test ! -e .venv` before and after.
- Focused (the 6 files): 976 passed.
- Full `tests/unit`: 6 failed / 6625 passed / 110 skipped. The 6 failures are exactly the baseline: deploy_autoscaling ×2, style_exclusivity_chokepoint ×3, persistence_boundary ×1, all with their baseline causes.
- PostgreSQL (workbench + runtime failures): 32 passed, 0 skipped.
- Vitest token test: 1 passed.
- `ruff check` on every changed file: clean (and clean at base).

## Concerns
- The tokens are what the provider reports for the one call (`max_retries=0`). If a future provider streams, or fires more than one `on_llm_end`, the first generation that reports usage wins.
- A test-path model that is not a LangChain `Runnable` (and so has no `.with_config`) would fail on an observed run and be recorded as `unexpected_error`. The real `ChatDatabricks` is always a Runnable. The recording doubles are used only on production-shaped paths, and S2 shows they would break if the gate were removed.
- The `ContextVar` is scoped to the one adapter call and reset in `finally`. `run_in_threadpool` copies the context per request, so concurrent runs cannot cross-contaminate.

## Triple check

