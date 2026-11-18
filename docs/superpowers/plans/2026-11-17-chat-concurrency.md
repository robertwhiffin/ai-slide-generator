# Chat Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, together with the repo's `executing-plans-tellr` skill (CLAUDE.md). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat turn starts the moment it is sent. To get there, there are more job runners per process, a fair per-process cap on in-flight model calls, and Tellr-owned retries, so the extra simultaneous turns don't become extra failures.

**Architecture:** A new module, `src/services/model_calls.py`, owns four things: the classification of model faults; a fair per-process call limiter (thread-level); a turn-deadline context variable; and `call_model`, which retries transient faults with jittered backoff around a limiter slot. `DatabricksModelAdapter` wraps its two model-call sites in `call_model` and turns the OpenAI SDK's own retries off. The job queue installs the turn deadline and records `started_at` and the fault kind on `chat_requests`. The slide pipeline lands an edited slide unreviewed after a transient review fault. The runner default rises to 8.

**Tech Stack:** Python 3, FastAPI, LangGraph/LangChain (`ChatDatabricks`, OpenAI SDK 3.x), SQLAlchemy (PostgreSQL in prod, SQLite in unit tests), pytest via `uv run`.

**Spec:** `docs/superpowers/specs/2026-11-17-chat-concurrency-design.md`

## Global Constraints

- Values are **code defaults** only. Don't touch `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template` or `UVICORN_WORKERS`.
- Runners: `DEFAULT_CHAT_JOB_CONCURRENCY = 8`. `TELLR_CHAT_JOB_CONCURRENCY` and `MAX_CHAT_JOB_CONCURRENCY = 16` are unchanged.
- Model-call cap: `TELLR_MODEL_CALL_CONCURRENCY`, default `15`, max `64`. An unusable value falls back to the default, as `chat_job_concurrency()` does.
- Retry starting numbers:
  - waits start at `2.0` s and are capped at `30.0` s each;
  - the budget is `150.0` s per call;
  - `Retry-After` is honoured;
  - the SDK's `max_retries` is `0` on production graph calls.
- Adapters built with `transport_options` (admin test runs, `evals/harness/runner.py`) keep today's behaviour: no Tellr retries, no limiter.
- Out of scope, with model calls unchanged: Legacy/monolith (frozen), MCP jobs, image generation (`generate_image`), session titles.
- The user-facing error text and `PINNED_GRAPH_CONFIGURATION_METADATA` are unchanged.
- Log fields go in the **message text**, because the production root logger formats the message alone.
- Python env: `uv sync --extra dev` in the worktree, commands via `uv run`; never `pip install`.
- Baseline before Task 1: 146 passed across `test_transient_model_failure`, `test_job_queue_concurrency`, `test_slide_pipeline`, `test_chat_request_progress`, `test_slide_style_preview` and `test_graph_tool_fallback_transient` (2026-11-17, `b11fde39` + spec commit).

## Review Focus

1. **A `Retry-After` far beyond the budget (for example 600 s)** must fail the call at once, not park the turn. Pinned in Task 3: `test_a_retry_after_past_the_budget_fails_at_once`.
2. **A stop while many of a turn's calls wait for slots:** every waiter leaves and no slot leaks, including a stop that races a grant. Pinned in Task 2: `test_a_stop_ends_a_wait_and_leaves_no_trace`, `test_a_stop_racing_a_grant_returns_the_slot`.
3. **A parse error or bug inside a held slot** must release it. Fifteen leaked slots would freeze every Agent turn in the process. Pinned in Task 2 (`test_a_slot_is_released_when_the_call_raises`) and Task 4 (`test_a_parse_failure_is_not_retried_and_frees_its_slot`).
4. **The recovery path** (`process_chat_request` called directly, with no job entry or no captured context) still runs under a deadline. Pinned in Task 5: `test_a_direct_call_without_a_job_entry_gets_the_full_limit`.
5. **Callers with no turn** (arc-review sweeper, slide-style previews) are capped as one group but never query the database for a stop. Pinned in Task 2: `test_calls_with_no_turn_share_one_group`, `test_no_request_id_means_no_stop_query`.

---

### Task 1: Model fault classification

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/services/model_calls.py`
- Modify: `src/services/agent_runtime.py:740-784` (`_TRANSIENT_HTTP_STATUSES`, `is_transient_model_failure`)
- Test: `tests/unit/test_model_fault_kind.py`; `tests/unit/test_transient_model_failure.py` must stay green unchanged

**Interfaces:**
- Produces:
  - `ModelFaultKind = Literal["rate_limited", "server_error", "timeout", "connection", "not_transient"]`
  - `TRANSIENT_FAULT_KINDS: frozenset[str]`, the first four
  - `model_fault_kind(error: BaseException) -> ModelFaultKind`
- `agent_runtime.is_transient_model_failure(error)` becomes `model_fault_kind(error) in TRANSIENT_FAULT_KINDS`. Every existing importer keeps working.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_model_fault_kind.py`, reusing the `_status` / `_chained` helpers' shape from `tests/unit/test_transient_model_failure.py`:
  - `test_status_codes_map_to_kinds`, parametrised:
    - 429 → `rate_limited`
    - 408 → `timeout`
    - 409, 500, 502, 503, 529 → `server_error`
    - 400, 401, 403, 404, 422 → `not_transient`
  - `test_timeouts_are_timeouts`: `openai.APITimeoutError`, `httpx.ReadTimeout`, `requests.exceptions.ReadTimeout()`, `TimeoutError()` and `databricks.sdk.errors.DeadlineExceeded("x")` → `timeout`. The timeout check precedes the connection check; `APITimeoutError` subclasses `APIConnectionError`.
  - `test_dropped_connections_are_connection`: `openai.APIConnectionError(request=…)`, `httpx.ConnectError("x", request=…)`, `requests.exceptions.ConnectionError()`, `ConnectionResetError()` and `Aborted("x")` → `connection`.
  - `test_internal_error_is_server_error`: `InternalError("x")` → `server_error`.
  - `test_no_cause_or_a_parse_error_is_not_transient`: `ModelProviderUnavailableError("gone")`, and an `OutputParserException` chained under it.
  - `test_the_outermost_status_decides`: an `APIStatusError(400)` raised `from` an `APIStatusError(429)` → `not_transient`. This is today's first-status-wins walk.
  - `test_a_cyclic_chain_terminates`: `a.__cause__ = b`, `b.__context__ = a` → `not_transient`.
  - `test_is_transient_agrees_with_the_kind`: for every error above, `is_transient_model_failure(e) == (model_fault_kind(e) in TRANSIENT_FAULT_KINDS)`.
- [ ] **Step 2: Run them and confirm they fail.** `uv run pytest tests/unit/test_model_fault_kind.py -q` should fail with an ImportError (`src.services.model_calls`).
- [ ] **Step 3: Implement `model_fault_kind`** in `src/services/model_calls.py`:
  - Walk `__cause__ or __context__` with a seen-set, exactly as `is_transient_model_failure` does today (`agent_runtime.py:745-784`), with the same exception classes from the same modules.
  - The first match decides. An `openai.APIStatusError` decides by status, and any other status is `not_transient`.
  - Replace the body of `is_transient_model_failure` with the delegation, keep its docstring, and drop `_TRANSIENT_HTTP_STATUSES` if nothing else uses it (`grep`).
  - Module docstring: what the module owns (fault kinds now; limiter and retries in Tasks 2–3).
- [ ] **Step 4: Run them and confirm they pass,** together with the existing classifier tests: `uv run pytest tests/unit/test_model_fault_kind.py tests/unit/test_transient_model_failure.py tests/unit/test_graph_tool_fallback_transient.py -q` should pass.
- [ ] **Step 5: Commit:** `git add src/services/model_calls.py src/services/agent_runtime.py tests/unit/test_model_fault_kind.py && git commit -m "feat(model-calls): name the kind of a model fault"` (with the repo's attribution trailer).

### Task 2: Fair per-process limiter, stop check, turn deadline

**Models:** test=opus impl=opus

**Files:**
- Modify: `src/services/model_calls.py`
- Test: `tests/unit/test_model_call_limiter.py`

**Interfaces:**
- Consumes: `src.services.generation_fence.raise_if_turn_ended(request_id)` (raises `TurnFencedError`) and `src.services.graph.event_emitter.get_chat_request_id()`. Import both **lazily inside functions**, as `agent_runtime` does for the database layer.
- Produces:
  - `MODEL_CALL_CONCURRENCY_ENV = "TELLR_MODEL_CALL_CONCURRENCY"`, `DEFAULT_MODEL_CALL_CONCURRENCY = 15`, `MAX_MODEL_CALL_CONCURRENCY = 64`
  - `model_call_concurrency() -> int`
  - `class FairCallLimiter`:
    - `__init__(self, capacity: int, *, wait_slice_seconds: float = 1.0)`
    - `slot(self, group: str | None, *, check_stop: Callable[[], None] | None = None)`, a context manager
    - `in_flight(self) -> dict[str | None, int]`, which has no zero entries
    - `waiting(self) -> int`
  - `get_model_call_limiter() -> FairCallLimiter`, `lru_cache(maxsize=1)`, sized by `model_call_concurrency()`
  - `current_call_group() -> str | None`, which is `get_chat_request_id()`
  - `STOP_CHECK_INTERVAL_SECONDS = 2.0`
  - `check_turn_stopped(request_id: str | None = None, *, clock: Callable[[], float] = time.monotonic) -> None`. It defaults to `current_call_group()`. A `None` request id does no query. It reuses a result per request id for `STOP_CHECK_INTERVAL_SECONDS`, and prunes entries older than 60 s on insert.
  - `set_turn_deadline(deadline: float | None) -> None` and `turn_deadline() -> float | None`. The deadline is a `time.monotonic()` value held in a `ContextVar`, default `None`.

**Fairness rule** (the algorithm the tests pin):
- A caller takes a slot at once if one is free and nobody waits.
- Otherwise it queues with an arrival sequence number.
- Whenever a slot frees, the slot goes to the waiter whose group has the fewest calls in flight, ties to the lowest sequence. Grants continue while slots are free.
- A waiter blocks on a `threading.Condition` in `wait_slice_seconds` slices. Between slices it calls `check_stop` **outside the lock**.
- If `check_stop` raises, the waiter leaves the queue. If it was granted meanwhile, it returns that slot (which may grant the next waiter). Then it re-raises.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_model_call_limiter.py`. Use real threads with `threading.Event` handshakes and `wait_slice_seconds=0.01`, and no sleeps that the assertions rely on:
  - `test_default_cap_is_fifteen` (env unset → 15); `test_cap_comes_from_the_environment` (`"6"` → 6, `" 3 "` → 3); `test_an_unusable_value_falls_back` (`"0"`, `"-1"`, `"x"`, `""`, `"2.5"` → 15); `test_a_huge_value_is_capped` (`"500"` → 64); `test_the_env_var_name_is_stable`.
  - `test_the_cap_holds_across_threads`: capacity 3, 12 threads. The observed peak concurrent count is ≤ 3, and all 12 finish.
  - `test_a_freed_slot_goes_to_the_turn_with_fewest_calls_in_flight`: capacity 2, group `"A"` holds both slots. `"A"` queues `A3`, then `"B"` queues `B1`. Releasing one `"A"` slot grants `B1` first, with `"A"` still holding one; the grant order starts `["B1"]`.
  - `test_ties_go_first_come_first_served`: capacity 1 held by `"X"`; `C1` (group `"C"`) queues before `D1` (group `"D"`). Release → `C1` first.
  - `test_calls_with_no_turn_share_one_group`: two `slot(None)` holders → `in_flight() == {None: 2}`.
  - `test_a_slot_is_released_when_the_call_raises`: a `ValueError` inside `slot("A")` propagates, and `in_flight() == {}` afterwards.
  - `test_a_stop_ends_a_wait_and_leaves_no_trace`: capacity 1 held. A waiter's `check_stop` raises `TurnFencedError`, so the waiter raises `TurnFencedError`, and `waiting() == 0`. After the holder releases, `in_flight() == {}`.
  - `test_a_stop_racing_a_grant_returns_the_slot`: capacity 1 held. The waiter's `check_stop` first releases the holder's slot (so a grant lands), then raises `TurnFencedError`. The waiter raises, and `in_flight() == {}`.
  - `test_no_request_id_means_no_stop_query`: patch `raise_if_turn_ended` to fail if called; `check_turn_stopped(None)` returns.
  - `test_a_stop_check_is_reused_within_the_interval`: a counting patch and a fake clock. Two calls at t=0 and t=1.9 → 1 underlying call; at t=2.1 → 2. A patch that raises `TurnFencedError` makes both calls inside the interval raise.
  - `test_the_turn_deadline_is_per_context`: the default is `None`, and a value set inside `contextvars.copy_context().run(...)` is not visible outside it.
- [ ] **Step 2: Run them and confirm they fail.** `uv run pytest tests/unit/test_model_call_limiter.py -q` should fail with an ImportError or AttributeError.
- [ ] **Step 3: Implement the interfaces above** in `src/services/model_calls.py`. The environment parsing mirrors `job_queue.chat_job_concurrency()`, including its warning log.
- [ ] **Step 4: Run them and confirm they pass,** ten times to shake out ordering: `uv run pytest tests/unit/test_model_call_limiter.py -q --count=10` if `pytest-repeat` is present, otherwise a shell loop. Every run should pass.
- [ ] **Step 5: Commit:** `feat(model-calls): fair per-process model-call limiter, stop check, turn deadline`.

### Task 3: `call_model`, retries owned in one place

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/services/model_calls.py`
- Test: `tests/unit/test_model_call_retry.py`

**Interfaces:**
- Consumes: `model_fault_kind` and `TRANSIENT_FAULT_KINDS` (Task 1); `FairCallLimiter`, `current_call_group`, `check_turn_stopped` and `turn_deadline` (Task 2).
- Produces:
  - `@dataclass(frozen=True) class RetryPolicy`, with `base_seconds: float = 2.0`, `max_wait_seconds: float = 30.0` and `budget_seconds: float = 150.0`
  - `DEFAULT_RETRY_POLICY = RetryPolicy()`
  - `retry_after_seconds(error: BaseException, *, now: Callable[[], float] = time.time) -> float | None`. It reads the first `openai.APIStatusError` on the chain: `retry-after-ms` in milliseconds, else `retry-after` as seconds or an HTTP-date. It returns `None` when the header is absent, unparseable or negative.
  - `call_model(fn: Callable[[], T], *, agent_key: str, policy: RetryPolicy | None = DEFAULT_RETRY_POLICY, limiter: FairCallLimiter | None = None, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic, rand: Callable[[], float] = random.random) -> T`

**Behaviour:**
- Before every attempt, call `check_turn_stopped()`. Run `fn()` inside `limiter.slot(current_call_group(), check_stop=check_turn_stopped)` when a limiter is given.
- `TurnFencedError` and non-transient errors propagate at once, as does every error when `policy is None`.
- After the n-th transient failure, the wait is:
  - with a hint: `hint * (1 + 0.25 * rand())`;
  - otherwise: `cap * (0.5 + 0.5 * rand())`, where `cap = min(max_wait_seconds, base_seconds * 2 ** (n - 1))`.
- Re-raise the **original** error when either holds:
  - `clock() - start + wait > budget_seconds`;
  - `turn_deadline()` is set and `clock() + wait >= turn_deadline()`.
- Sleep in slices of at most 1 s, calling `check_turn_stopped()` after each. The slot is not held while sleeping.
- Log at WARNING:
  - each retry: `"model_call_retry agent=%s fault=%s attempt=%d wait_s=%.1f request_id=%s"`;
  - giving up: `"model_call_gave_up agent=%s fault=%s attempts=%d elapsed_s=%.1f request_id=%s"`.

- [ ] **Step 1: Write the failing tests.** Use a fake clock whose `sleep` advances it, `rand` injected, and errors built as in Task 1, with headers passed via `httpx.Response(code, headers=…)`:
  - `test_a_success_is_returned_without_waiting`: `sleep` is never called.
  - `test_a_rate_limit_is_retried_until_it_succeeds`: 429, 429, then `"ok"` → returns `"ok"` after 3 calls.
  - `test_the_backoff_grows_and_is_capped`: `rand=lambda: 1.0`, always 503. The gaps between calls are `[2, 4, 8, 16, 30, 30, …]`, the last call is at or before t=150, and the final error is the 503.
  - `test_retry_after_is_honoured`: `rand=lambda: 0.0`. `retry-after: 7` → first gap 7.0; `retry-after-ms: 1500` → 1.5.
  - `test_a_retry_after_past_the_budget_fails_at_once`: `retry-after: 600` → 1 call, no sleep.
  - `test_it_never_waits_past_the_turn_deadline`: `set_turn_deadline(clock() + 5)`, `rand=1.0`, always 503 → 2 calls, then the error.
  - `test_a_non_transient_error_is_raised_at_once`: 400 → 1 call; so is an `OutputParserException`.
  - `test_no_policy_means_one_attempt`: `policy=None`, 429 → 1 call.
  - `test_a_stop_during_a_backoff_ends_the_call`: `check_turn_stopped` patched to raise `TurnFencedError` once the clock passes the first slice → `TurnFencedError`, `fn` called once.
  - `test_the_slot_is_not_held_while_waiting`: a capacity-1 limiter. The fake `sleep` asserts `limiter.in_flight() == {}`.
  - `test_each_retry_logs_one_line_with_its_fields_in_the_message`: caplog on `src.services.model_calls`. The message contains `"model_call_retry agent=builder fault=rate_limited attempt=1"`.
  - `test_retry_after_parsing`: seconds, ms, an HTTP-date 10 s after an injected `now` → 10.0, garbage → `None`, `-3` → `None`, and a header on a chained cause is still found.
- [ ] **Step 2: Run them and confirm they fail.** `uv run pytest tests/unit/test_model_call_retry.py -q` should fail.
- [ ] **Step 3: Implement `RetryPolicy`, `retry_after_seconds` and `call_model`** per the behaviour above. For the HTTP-date parse, use `email.utils.parsedate_to_datetime`.
- [ ] **Step 4: Run them and confirm they pass,** with the limiter tests: `uv run pytest tests/unit/test_model_call_retry.py tests/unit/test_model_call_limiter.py -q` should pass.
- [ ] **Step 5: Commit:** `feat(model-calls): retry transient model faults with jittered, Retry-After-aware backoff`.

### Task 4: Wire the adapter; stop previews retrying on top

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/services/agent_runtime.py:510-640` (`DatabricksModelAdapter.__init__`, `invoke`, `invoke_with_tools`)
- Modify: `src/api/services/slide_style_preview_queue.py:66` (`PREVIEW_MAX_RETRIES`)
- Test: `tests/unit/test_model_adapter_retries.py`; update `tests/unit/test_slide_style_preview.py::test_transient_provider_failure_is_retried`

**Interfaces:**
- Consumes: `call_model`, `DEFAULT_RETRY_POLICY`, `RetryPolicy`, `FairCallLimiter` and `get_model_call_limiter` (Tasks 2–3).
- Produces: `DatabricksModelAdapter.__init__(self, *, model_factory=None, client_factory=None, transport_options=None, retry_policy=_MANAGED, limiter=_MANAGED)`, where `_MANAGED` is a module-private sentinel.
  - When `transport_options is None` (production), the sentinels resolve to `DEFAULT_RETRY_POLICY` and `get_model_call_limiter()`. The transport options handed to `bind_structured_output_model` become `{"max_retries": 0}`.
  - Otherwise they resolve to `None`, `None`, and the given options, so behaviour is unchanged.
  - Explicit arguments always win, which is what the tests use.
- `invoke` and each round of `invoke_with_tools` call the model as `call_model(lambda: <model>.invoke(<arg>), agent_key=agent_key, policy=self._retry_policy, limiter=self._limiter)`. The call stays **inside** `_model_provider_errors_collapsed()`, so a spent retry collapses exactly as today. Stop deleting `agent_key`, since it now names the log line. Tools still run between rounds, outside `call_model`.
- Update the docstrings that say production passes no transport options (`bind_structured_output_model`, `__init__`).

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_model_adapter_retries.py`. The fake `model_factory` records its kwargs and returns a model whose `bind_tools(...)` gives a runnable with scripted `invoke` results: raise, or return an `AIMessage` carrying a tool call to the schema. Inject `retry_policy=RetryPolicy(base_seconds=0.001, max_wait_seconds=0.002, budget_seconds=1.0)` and `limiter=FairCallLimiter(2)`.
  - `test_the_production_adapter_retries_a_rate_limit`: `invoke` with 429 then a valid schema call returns the parsed schema after 2 model invocations.
  - `test_the_production_adapter_turns_off_the_sdk_retries`: `DatabricksModelAdapter(model_factory=fake)` → the factory kwargs include `max_retries=0`.
  - `test_an_adapter_with_transport_options_is_unchanged`: `transport_options={"timeout": 120.0, "max_retries": 0}`. A 429 raises `ModelProviderUnavailableError` after 1 invocation. The factory kwargs carry exactly those options, and `get_model_call_limiter` is patched to raise if called.
  - `test_spent_retries_still_collapse_with_the_cause`: always 429 → `ModelProviderUnavailableError` whose chain gives `model_fault_kind(...) == "rate_limited"`.
  - `test_a_parse_failure_is_not_retried_and_frees_its_slot`: a reply with no tool call twice → `OutputParserException` via the nudge path, with no extra invocations from retries and `limiter.in_flight() == {}`.
  - `test_each_tool_loop_round_is_retried_on_its_own`: in `invoke_with_tools`, round 1 calls a tool, round 2 raises 429 once and then calls the schema. The result validates and the tool ran exactly once.
  - `test_no_slot_is_held_while_a_tool_runs`: the tool's `run` asserts `limiter.in_flight() == {}`.
  - `test_a_stop_inside_a_model_call_is_not_collapsed`: `check_turn_stopped` patched to raise `TurnFencedError` before the first attempt → `invoke` raises `TurnFencedError`, not `ModelProviderUnavailableError`. `TurnFencedError` is a `RuntimeError` and isn't in `_MODEL_PROVIDER_ERRORS`; this test keeps it that way.
  - In `tests/unit/test_slide_style_preview.py`, rename `test_transient_provider_failure_is_retried` to `test_a_transient_failure_is_not_retried_again_by_the_queue`. It asserts one runtime call and the persisted `generation_error`. The adapter now owns transient retries.
- [ ] **Step 2: Run them and confirm they fail.** `uv run pytest tests/unit/test_model_adapter_retries.py tests/unit/test_slide_style_preview.py -q` should fail.
- [ ] **Step 3: Implement the wiring above.** Set `PREVIEW_MAX_RETRIES = 0`, with its comment saying why: the adapter retries transient faults, and the queue retrying again would multiply them.
- [ ] **Step 4: Run them and confirm they pass,** with the graph suites that exercise the adapter: `uv run pytest tests/unit/test_model_adapter_retries.py tests/unit/test_slide_style_preview.py tests/unit/test_graph_tool_fallback_transient.py tests/unit/test_slide_pipeline.py -q` should pass. Then run `uv run pytest tests/unit -q -x -k "agent_runtime or adapter or tool_loop"`, which should pass.
- [ ] **Step 5: Commit:** `feat(agent-runtime): production model calls go through the limiter and Tellr's retries`.

### Task 5: The turn's deadline, from the runner

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/api/services/job_queue.py` (`process_chat_request`, `_run_streaming_generator`)
- Test: `tests/unit/test_job_queue_turn_deadline.py`

**Interfaces:**
- Consumes: `model_calls.set_turn_deadline` (Task 2).
- Produces:
  - `_turn_deadline(request_id: str, engine_mode: str | None) -> float`, which returns `time.monotonic() + job_hard_timeout_seconds(engine_mode) - elapsed`. `elapsed` comes from `jobs[request_id]["started_at"]` (`datetime.utcnow()` clock), or is 0 when there's no entry or no `started_at`.
  - `_run_streaming_generator` gains a trailing `turn_deadline: Optional[float] = None` parameter, passed positionally by both call sites per its docstring's convention. It calls `set_turn_deadline(turn_deadline)` first, inside the job's context.
  - Both branches of `process_chat_request` compute and pass it (with `ctx`, and the no-context fallback).

- [ ] **Step 1: Write the failing tests,** using `tests/unit/test_job_queue_concurrency.py`'s fake chat service pattern. The fake's `send_message_streaming` records `model_calls.turn_deadline() - time.monotonic()`.
  - `test_a_graph_turn_runs_with_the_hard_timeout_as_its_deadline`: `started_at` is 100 s ago → recorded ≈ 1100 (± 5).
  - `test_a_monolith_turn_gets_its_own_limit`: `engine_mode` `"monolith"`, started now → ≈ 600.
  - `test_a_direct_call_without_a_job_entry_gets_the_full_limit`: no `jobs` entry, graph → ≈ 1200.
  - `test_the_no_context_fallback_also_gets_a_deadline`: a payload without `_context` → ≈ the limit.
  - `test_the_deadline_does_not_leak_between_jobs`: two sequential jobs record their own values, and `turn_deadline()` in the test's own context stays `None`.
- [ ] **Step 2: Run them and confirm they fail.** `uv run pytest tests/unit/test_job_queue_turn_deadline.py -q` should fail.
- [ ] **Step 3: Implement it** as described above.
- [ ] **Step 4: Run them and confirm they pass,** with the job-queue suites: `uv run pytest tests/unit/test_job_queue_turn_deadline.py tests/unit/test_job_queue_concurrency.py tests/unit/test_job_queue_rollback.py tests/unit/test_job_queue_timeout_sweeper.py tests/unit/test_engine_mode_wiring.py tests/unit/test_stage_slide_wiring.py -q` should pass.
- [ ] **Step 5: Commit:** `feat(chat): each turn's model calls know its hard-timeout deadline`.

### Task 6: Measurement: `started_at` and the fault kind

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/database/models/session.py` (`ChatRequest`); `src/core/database.py` (new `_migrate_chat_request_measurement`, called right after `_migrate_chat_request_progress` at `:664`); `src/services/generation_fence.py:81-90` (`start_chat_request`); `src/api/services/session_manager.py` (`update_chat_request_status`, new `set_chat_request_fault_kind`); `src/api/services/job_queue.py` (the failure branches of `process_chat_request`)
- Test: `tests/unit/test_chat_request_measurement.py`; extend `tests/unit/test_job_queue_rollback.py`

**Interfaces:**
- Consumes: `model_fault_kind` (Task 1).
- Produces:
  - `ChatRequest.started_at = Column(DateTime, nullable=True)` and `ChatRequest.model_fault_kind = Column(String(32), nullable=True)`
  - `_migrate_chat_request_measurement(conn, inspector, schema, _qual, is_sqlite) -> None`, which adds `started_at TIMESTAMP NULL` and `model_fault_kind VARCHAR(32) NULL` when missing, mirroring `_migrate_chat_request_progress`
  - `generation_fence.start_chat_request` sets `started_at = :now` (`datetime.utcnow()`) in the same `UPDATE`
  - `update_chat_request_status(..., "running")` sets `started_at` only when it is NULL
  - `SessionManager.set_chat_request_fault_kind(request_id: str, kind: str) -> None`, an `UPDATE … SET model_fault_kind = :kind WHERE request_id = :rid AND status = 'error'`
- In `process_chat_request`, the `_PinnedGraphConfigurationTerminalError` branch (now `as exc`) and the `except Exception as e` branch call `set_chat_request_fault_kind(request_id, model_fault_kind(exc))` after their status writes, **for graph turns only**. The call is best-effort: a failure is logged as a warning and never masks the original error.

- [ ] **Step 1: Write the failing tests:**
  - `test_the_migration_adds_both_columns` and `test_the_migration_is_idempotent`, on a SQLite table created without them. This is the `tests/unit/test_chat_request_progress.py:116` pattern.
  - `test_start_sets_started_at`: the `db` fixture pattern of `tests/unit/test_generation_fence.py`.
  - `test_running_sets_started_at_once`: a second `"running"` leaves it unchanged.
  - In `tests/unit/test_job_queue_rollback.py`:
    - `test_a_rate_limited_failure_records_its_kind`: the body raises a `PinnedInvocationEndpointError` raised `from` a 429 `APIStatusError` → `request_row(rid)["model_fault_kind"] == "rate_limited"` and `error_message` unchanged.
    - `test_a_crash_records_not_transient`: `RuntimeError` → `"not_transient"`.
    - `test_a_stopped_turn_records_no_kind`: the `test_failure_after_cancel_does_not_overwrite_cancelled` flow → `None`.
    - `test_a_monolith_failure_records_no_kind`.
    - Also assert `started_at` is set on a started graph request.
- [ ] **Step 2: Run them and confirm they fail.** `uv run pytest tests/unit/test_chat_request_measurement.py tests/unit/test_job_queue_rollback.py -q` should fail.
- [ ] **Step 3: Implement the interfaces above.**
- [ ] **Step 4: Run them and confirm they pass,** with the fence, rollback and progress suites: `uv run pytest tests/unit/test_chat_request_measurement.py tests/unit/test_job_queue_rollback.py tests/unit/test_generation_fence.py tests/unit/test_generation_rollback.py tests/unit/test_chat_request_progress.py -q` should pass. If local Postgres is running, also run `uv run pytest tests/integration -q -k "chat_request or claim or rollback"`, which should pass.
- [ ] **Step 5: Commit:** `feat(chat): record when a turn started and what kind of model fault ended it`.

### Task 7: An edited slide whose review fails transiently lands unreviewed

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/services/graph/nodes.py:7576-7640` (`_write_draft_row`), `:7723-7750` (the transient-review branch of `slide_pipeline_node`)
- Test: `tests/unit/test_slide_pipeline.py` (class `TestATransientModelFaultKeepsTheDraft`)

**Interfaces:**
- Produces: `_write_draft_row(record: dict, mutation: DeckMutationContext, *, replace_real: bool = False) -> bool`. With `replace_real=True`, it writes even over a committed real slide. Everything else is unchanged: the fence check, `write_slide` without a verification record, and best-effort `False` on a write failure.
- In the review branch: when the fault is transient and `drafted` is False, call `_write_draft_row(record, mutation, replace_real=True)`. When that returns True, take the existing kept-unreviewed fallback (`_transient_failure_notice(..., during="review")` and the same fold). Otherwise re-raise. Non-transient faults re-raise as today.
- Update `_write_draft_row`'s docstring: "a draft never overwrites a committed REAL slide" still governs the draft write, and only the transient-review fallback may land the build over a real slide (decided 2026-11-17).

- [ ] **Step 1: Write the failing tests:**
  - Replace `test_without_a_draft_a_transient_review_failure_still_fails_the_turn` with `test_an_edits_transient_review_failure_lands_the_build_unreviewed`. Set up with `env.seed_slides(["<div class='slide'>existing 0</div>"])`, `_wire(env, (0,))` and `build_reviewer` = `_transient("opus")`. Then `_run(env)` doesn't raise, `_rows(env)[0].html == "<div class='slide'>slide 0</div>"`, and `verification_record in (None, "", "{}", "null")`. Also call `self._the_one_notice(env, caplog, unreviewed_slide_notice(0, during="review"), position=0)`.
  - `test_an_edits_permanent_review_failure_still_keeps_the_users_slide`: seeded, `_permanent("opus")` → `PinnedInvocationEndpointError`, and the row html is still `"<div class='slide'>existing 0</div>"`.
  - `test_an_edit_whose_build_cannot_be_written_still_fails`: seeded, transient review, and `SlideWriter.write_slide` patched to raise for this write → `PinnedInvocationEndpointError`, existing html unchanged.
- [ ] **Step 2: Run them and confirm they fail.** `uv run pytest tests/unit/test_slide_pipeline.py -q -k "edit"`: the first test should fail with a raised `PinnedInvocationEndpointError`.
- [ ] **Step 3: Implement it** as described above.
- [ ] **Step 4: Run them and confirm they pass,** with the neighbouring suites: `uv run pytest tests/unit/test_slide_pipeline.py tests/unit/test_pending_slide_is_fillable.py tests/unit/test_turn_progress_graph.py tests/unit/test_graph_user_notices.py -q` should pass.
- [ ] **Step 5: Commit:** `fix(graph): a transient review fault on an edited slide lands it unreviewed, not a failed turn`.

### Task 8: Eight runners per process, and the docs

**Models:** test=sonnet impl=haiku

**Files:**
- Modify: `src/api/services/job_queue.py:39-46` (comment and `DEFAULT_CHAT_JOB_CONCURRENCY`), `src/api/main.py:157` (comment)
- Modify: `docs/technical/multi-user-concurrency.md` ("Chat Job Runners"), `docs/technical/backend-overview.md:12,347`, plus any line in `docs/technical/real-time-streaming.md` that states the runner default (`grep -n "runner" docs/technical/real-time-streaming.md`)
- Test: `tests/unit/test_job_queue_concurrency.py:135-138`

- [ ] **Step 1: Update the test:** rename `test_default_concurrency_is_one` to `test_default_concurrency_is_eight`, with docstring "Enough runners that a turn practically never waits; model load is capped per process by the model-call limiter", and assert `job_queue.chat_job_concurrency() == 8`.
- [ ] **Step 2: Run it and confirm it fails.** `uv run pytest tests/unit/test_job_queue_concurrency.py -q -k default` should fail (`1 != 8`).
- [ ] **Step 3: Set `DEFAULT_CHAT_JOB_CONCURRENCY = 8`** and rewrite the comment above it. It should say that runners only decide which turns start, and that model load is capped by `TELLR_MODEL_CALL_CONCURRENCY` (default 15) in `src/services/model_calls.py`.
  - Rewrite the "Chat Job Runners" doc section, replacing the "default stays 1" paragraph:
    - the default is 8 per worker (32 with 4 workers);
    - the per-process model-call cap of 15 and its fairness rule;
    - Tellr-owned retries (2 s → 30 s, 150 s budget, `Retry-After`, SDK retries off);
    - the `started_at` and `model_fault_kind` columns;
    - a pointer to the spec.
  - Fix the defaults in `backend-overview.md`.
- [ ] **Step 4: Run the tests and confirm they pass:** `uv run pytest tests/unit/test_job_queue_concurrency.py -q` should pass.
- [ ] **Step 5: Commit:** `feat(chat): eight job runners per process`.

### Task 9: Devloop load test and tuning

**Models:** test=opus impl=opus. Run by the orchestrator, not dispatched; there is no test-writing step.

**Files:**
- Create: `~/tellr-loop/chat-concurrency/load_test.py` (adapted from `~/tellr-loop/job-concurrency/load_test.py`) and `~/tellr-loop/chat-concurrency/results.md`
- Modify, only if tuning says so: the defaults in `src/services/model_calls.py` / `src/api/services/job_queue.py`, plus the spec's "Still open" section

- [ ] **Step 1: Check the shared state with peers** (`ListAgents`) before deploying: devloop instances and the `.devN` counter.
- [ ] **Step 2: Deploy with the `deploy-tellr-dev` skill.**
  - Push the branch as the personal gh account.
  - Run `gh workflow run publish-dev.yml --ref feat/chat-concurrency`.
  - Run `./scripts/deploy_local.sh create --env devloop --instance chat-conc --profile tellr-dev --from-pypi <version>`. The instance name must be at most 17 characters.
  - If the create fails with `RESOURCE_EXHAUSTED`, see the account SP limit note in memory.
- [ ] **Step 3: Run the scenarios,** each submitting all decks within 2 s:
  - (a) 8 new decks of 8 slides;
  - (b) 8 mixed turns: 4 new decks and 4 edits of existing decks;
  - (c) worst placement: set `UVICORN_WORKERS=1` in the devloop's deployed `app.yaml` env, redeploy that source (`databricks apps deploy`, not `deploy_local update`, which re-forks the database), and run 8 new decks, so all 8 land on one process.
  - During one run, stop one deck while its log shows `model_call_retry`.
- [ ] **Step 4: Measure each scenario and write it to `results.md`:**
  - per turn, `started_at - created_at` (SQL on the devloop branch);
  - from the app log via `~/tellr-loop/concurrency-runners/parse_log.py` (extend it to count `model_call_retry` / `model_call_gave_up`): `model_call_retry`, `model_call_gave_up` and Gateway status counts;
  - failed turns and their `model_fault_kind`;
  - peak `pg_stat_activity` connections for the app role;
  - the time from the stop to `cancelled`.
- [ ] **Step 5: Judge against the pass bar:**
  - every turn starts within 5 s;
  - at most 1 failed turn per scenario (baseline: 6 of 8 on 2026-10-31), and every failure carries a fault kind;
  - no turn hangs (all slots return);
  - connections stay under the 80 + 20 pool per process;
  - a stop during a backoff lands within about 5 s.
- [ ] **Step 6: Tune if the bar is missed.**
  - If failures come from `model_call_gave_up … fault=rate_limited`, lower `DEFAULT_MODEL_CALL_CONCURRENCY` (15 → 10 → 6) and re-run (b).
  - If turns wait in (c), raise `DEFAULT_CHAT_JOB_CONCURRENCY` toward 16.
  - Commit any default change with the measurement in the commit message.
- [ ] **Step 7: Record the outcome** in the spec's "Still open" section, together with the result of the logfood log capture (`~/tellr-loop/concurrency-runners/applog-follow-2026-11-17.txt`). Commit: `docs(spec): load-test results for chat concurrency`.
