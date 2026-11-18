# Chat concurrency: every turn starts on Enter — design

Date: 2026-11-17. Status: draft for review.

Decisions are marked **(decided)** when the user made them, and **(my call)** when the
designer made them and the user has not yet confirmed them. Unmarked text describes the
code as it stands.

## Intent

Users see "Waiting for another request to finish…" more and more. The owner's definition of
fixed, in their words: **"press enter - generation starts"**. A turn should start the moment
it is sent, whoever else is using Tellr at the time.

The waiting is caused by how chat turns are scheduled, not by a lack of machine capacity.
The obvious fix (run more turns at once) was held back on 2026-11-02 because a load test
with more turns at once drew 118 model rate-limit errors (429s) and failed 6 of 8 turns. So
this design does two things together: it lets every turn start at once, and it stops the
extra simultaneous turns from turning into extra failures.

## What we measured (logfood, 5–17 Nov 2026, 2,570 turns)

Queries against `app_data_prod` on the logfood Lakebase, run in read-only transactions
(`default_transaction_read_only=on`) on its primary endpoint. SQL and raw output are in
`~/tellr-loop/concurrency-runners/`.

- **Overlap is about the same as on old prod.** Weekdays run 186–388 turns. One turn is
  running 77% of the busy time, two 17%, three 4%, four or more about 2%. The peak was 8 at
  once.
- **Turns got longer.** 85% of turns are Agent turns. An Agent turn takes a median of 106 s
  when nothing else is running, a Legacy turn 26 s, and the old-prod median was 44 s. So
  each turn holds its runner far longer than before.
- **About 10% of turns waited for a runner**, with a median wait of about 2 min and a p90
  of 5 min. This is an estimate: the table has no start time, so it counts turns whose first
  reply came late and landed just after another turn ended.
- **6.5% of all turns (7.2% of Agent turns, 0 Legacy) failed** with "Pinned graph
  configuration is unavailable". The rate rises with overlap: 5.7% with nothing else
  running, about 8% with one or two others, 15.9% with three or more. Most failed 2–5 min
  into the turn. That message is what *any* failed model call in an Agent turn becomes
  (429, 5xx, timeout, dropped connection: see below). The database does not record which
  kind it was, and the app log keeps only a few minutes.

## How it works today

- **Runners.** The app runs 4 uvicorn processes (`UVICORN_WORKERS`, default 4,
  `packages/databricks-tellr-app/databricks_tellr_app/run.py`). Each has
  `TELLR_CHAT_JOB_CONCURRENCY` job runners, default 1 (`src/api/services/job_queue.py`).
  Neither variable is in `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template`,
  and `tellr.update` regenerates `app.yaml` from it, so a deployed app always gets the code
  defaults: 4 runners app-wide.
- **Placement.** A turn runs on the process that received its `POST /chat/async`. The
  queue lives in that process's memory. POSTs land unevenly (in the 31 Oct load test, 5 of
  8 landed on one process), so a turn can wait while other processes sit idle.
- **Safety of several runners per process** was built and reviewed in #357 (MLflow
  experiment isolation, verify off the loop, a session-lock heartbeat, the `chat-job`
  thread pool, the queued UI state). It shipped switched off at 1.
- **Fan-out inside one turn.** An Agent turn builds up to `CAP = 15` slides at once
  (`src/services/foreman_service.py`, `src/services/graph/builder.py`). Each slide makes
  builder, reviewer and sometimes fixer and fix-reviewer calls. Fix rounds are capped at
  `FIX_CONCURRENCY = 5` per turn. So one process with one runner can already have about 15
  model calls in flight, and the app about 60.
- **Model calls.** Every Agent-graph model call goes through `DatabricksModelAdapter` in
  `src/services/agent_runtime.py`: `invoke` (one call) and `invoke_with_tools` (one call per
  tool-loop round). Both build a `ChatDatabricks` via `gateway_chat_model`
  (`src/services/gateway_clients.py`) with no `max_retries` or timeout. That means the
  OpenAI SDK defaults apply: 2 quick retries, then failure.
- **Failure collapsing.** Any provider error is collapsed into
  `ModelProviderUnavailableError` (`_model_provider_errors_collapsed`), then into
  `PinnedInvocationEndpointError`. The turn ends with "Pinned graph configuration is
  unavailable" and, since #385, is rolled back as a whole. `is_transient_model_failure`
  can still read the original cause off the exception chain.
- **Existing transient fallbacks** (`src/services/graph/nodes.py`, `slide_pipeline_node`).
  A transient fault during a slide's review keeps its draft unreviewed, but only when a
  draft was written (`drafted`). On an edit or rebuild of a real slide no draft is written
  (`_write_draft_row` returns False), so a transient review fault fails the whole turn. A
  transient fault during a fix round lands the original slide. Only 4 logfood turns took
  either fallback in 12 days.

## Goals

1. **A turn starts when Enter is pressed.** In normal use nobody sees "Waiting for another
   request to finish…", including at the observed peak of 8 turns at once with uneven
   placement. **(decided)**
2. **Each process caps how many model calls it has in flight, and shares them fairly
   between the turns running there.** Under a burst every turn starts, and each runs a bit
   slower; no turn waits minutes while another runs at full speed. **(decided)**
3. **Rate limits and other transient model faults are retried properly.** The backoff is
   longer, respects `Retry-After`, and turns a busy minute into a slower turn rather than a
   failed one. **(decided)**
4. **Failed turns must not rise. Fewer is the expected result.** **(my call.)** In
   particular, a transient fault during an edited slide's review must no longer fail the
   whole turn (section 4b). **(decided 2026-11-17)**
5. **The result can be measured** after release, without the 20-minute log window. For
   each turn we can tell how long it waited before starting, and, for a failed Agent turn,
   which kind of model fault ended it. **(my call)**
6. **The runner count and the model-call cap are set by a devloop load test, not picked
   from the armchair.** **(decided)**

## Non-goals

- **Changing `UVICORN_WORKERS`.** **(my call)** Every process adds about 350 MB, its own
  database pool (80 + 20 connections) and its own background loops. It doesn't fix uneven
  placement and loads the models the same as more runners do. Runners are threads inside
  a process and cost far less.
- **A shared, database-backed queue** that lets any process run any turn. It would fix
  placement and the loss of queued turns on restart. But each job carries the sender's own
  Databricks client (`_user_client_var`, `src/core/databricks_client.py`), so running it in
  another process means storing the user's token. That needs its own design and a security
  review. Later, if needed.
- **Legacy decks and Tellr MCP jobs.** **(decided 2026-11-12: Legacy is frozen.)** Their
  model calls go through the monolith, not `DatabricksModelAdapter`. They are not capped or
  retried by this work, though they do benefit from the extra runners. Running several
  Legacy turns in one process was covered by the #357 concurrency audit
  (`~/tellr-loop/job-concurrency/audit.md`). Its fixes shipped in #357: MLflow experiment
  isolation, the judge off the event loop, and the session-lock heartbeat that guards the
  shared per-session deck cache.
- **Image generation** (`generate_image`, #379) keeps its own client and its own 429
  handling. It is a different model with different capacity. **(my call)**
- **Session-title calls** (`src/api/services/session_naming.py`) stay outside the cap: one
  small call per deck. **(my call)**
- **One budget for the whole app** across processes. **(my call)** A per-process cap with
  4 processes gives a known app-wide ceiling. Coordinating processes needs shared state,
  which is the same problem as the shared queue.
- **More workspace model capacity** or Gateway rate limits.

## Anti-goals (a failure even if it technically works)

- More failed Agent turns than today's 7.2%.
- A higher peak load on the models than the app can already put on them today (about 60
  calls in flight).
- One turn starving another. For example, a new turn's first (planning) call stuck behind
  another turn's 15 slide builds until they all finish.
- Retries that multiply: SDK retries inside Tellr's retries, or every slide of a turn
  hammering the Gateway in lockstep after a 429.
- A stop that no longer stops promptly. A turn waiting for a model-call slot, or sleeping
  in a backoff, must notice a stop as quickly as it does today.
- A turn pushed into the 20-minute Agent hard timeout (`GRAPH_JOB_HARD_TIMEOUT_SECONDS`) by
  backoff it could not have survived anyway.
- Postgres pool exhaustion or memory pressure from the extra simultaneous turns, showing up
  as new errors.

## Design

### 1. More runners per process

Raise `DEFAULT_CHAT_JOB_CONCURRENCY` in `src/api/services/job_queue.py`. It must be the
code default, because `app.yaml` is regenerated on every `tellr.update`. The
`TELLR_CHAT_JOB_CONCURRENCY` override and `MAX_CHAT_JOB_CONCURRENCY = 16` stay. The value
comes from the load test (goal 6). **The starting point is 8 per process (my call)**:
32 runners app-wide against an observed peak of 8, so a turn queues only if 9 land on one
process.

The "Waiting for another request to finish…" state and its client logic stay as they are,
as the safety net for extreme load.

### 2. A per-process model-call limiter

One limiter per process covers every `DatabricksModelAdapter` model call: the call in
`invoke`, and each round's call in `invoke_with_tools`. It is a thread-level primitive,
because graph slide pipelines run on threads.

- **The cap defaults to 15 per process (my call)**, the same as `CAP`. With 4 processes,
  the app-wide ceiling stays at about 60 calls in flight: today's ceiling with one runner
  per process. More runners therefore can't raise the peak load on the models; they only
  change who gets the calls. It can be overridden by an environment variable and is tuned
  by the load test. This deliberately doesn't depend on the workspace's model quotas, which
  the app can't see. On tellr-dev on 31 Oct no Gateway rate limits were configured, so the
  429s came from the workspace's shared model capacity; logfood's limits are unknown. The cap keeps today's
  ceiling, the retries absorb the 429s that remain, and the fault-kind column (section 5)
  shows what's left.
- **Fair sharing (decided in principle, mechanism my call).** When a slot frees, it goes to
  the waiting caller whose turn has the fewest calls in flight; ties go first-come,
  first-served. A new turn's planning call therefore goes next instead of waiting behind
  another turn's slide builds. The turn is read from the chat request id already in
  context (`get_chat_request_id`). Callers with no turn (the arc-review sweeper, slide-style
  previews) form their own group.
- **A slot is held only for the HTTP call itself.** It is released during backoff sleeps
  and while a tool runs between tool-loop rounds.
- **Waiting for a slot checks for a stop** (`raise_if_turn_ended`), so a stopped turn
  leaves the line straight away.

### 3. Retries owned in one place

The adapter owns retries for these calls. The SDK's own retries are switched off for them
(`max_retries=0` on the graph's `ChatDatabricks`), so retries don't multiply.

- **What is retried:** the faults `is_transient_model_failure` already recognises (408,
  409, 429, 5xx, timeouts, dropped connections), judged on the raw provider error before it
  is collapsed. Everything else fails at once, as today.
- **Backoff (starting numbers, my call, tuned by the load test):** exponential with full
  jitter, starting around 2 s, capped around 30 s per wait. When a `Retry-After` is present
  it is used instead, jittered upwards, so slides don't retry in lockstep. The total
  retry budget for one call is about 2–3 min.
- **Bounded by the turn.** No wait starts that would run past the turn's hard timeout.
  Every attempt and every wait checks for a stop. **The clock (my call)** is the one the
  timeout sweeper enforces (`job_queue.py:700-712`): the job entry's `started_at` (set when
  a runner takes the job) plus `job_hard_timeout_seconds(engine_mode)`. The runner puts
  that deadline in a context variable. It reaches slide pipelines the same way
  `chat_request_id_var` and `_fix_slots_var` already do (`Send` payloads can't carry it,
  see `checkpointer.py:52`). Calls with no turn have no deadline beyond their own retry
  budget.
- **When the budget is spent**, the error is raised exactly as today, so the existing
  collapsing, fallbacks and rollback all still apply.
- **Each retry writes one log line** with the agent, the fault kind, the attempt number and
  the wait. The fields go in the message text, because the production root logger formats
  the message alone (see `_surface_failure_notice`).

### 4. Fallbacks after retries are spent

**4a.** The review and fix-round fallbacks in `slide_pipeline_node` stay as they are.

**4b. An edited slide whose review fails transiently lands as built, unreviewed
(decided 2026-11-17).** It gets the existing `kept_unreviewed` notice instead of failing
the turn.
Today, when the position held a real slide, the whole turn fails and #385 rolls back
every other slide's work. Landing the user's requested edit, marked unchecked, is closer
to what they asked for. A non-transient fault (a removed or forbidden endpoint) still fails
the turn, so the user's good slide is never overwritten by a turn that cannot work. This
narrows the rule in `_write_draft_row`'s docstring ("a draft never overwrites a committed
REAL slide"). That rule still governs the draft write itself; only the transient-review
fallback may now land the build over a real slide, and the docstring must say so.

### 5. Measurement

- **`chat_requests.started_at`:** a new nullable column, set when a runner starts the
  request (`start_chat_request` for Agent turns, the move to `running` for others). It is
  added through the existing startup-migration pattern in `src/core/database.py` (see
  `_migrate_chat_request_progress`). Wait time is then `started_at - created_at`.
- **The fault kind of a failed Agent turn** goes in a new nullable column on
  `chat_requests`: rate-limited, server error, timeout, connection, or not transient. The
  user-facing message and `PINNED_GRAPH_CONFIGURATION_METADATA` stay as they are, because
  the poll and client contract depend on them.

## Verification

- **Unit tests:**
  - the limiter: the cap holds across threads; fair hand-off favours the turn with the
    fewest calls in flight; slots are released during backoff and tool runs; a stop ends a
    wait;
  - the retry policy: `Retry-After` is honoured; the budget is bounded; it never waits past
    the turn deadline; non-transient errors aren't retried; a stop during a wait ends it;
    SDK retries are off;
  - 4b: an edited slide whose review fails transiently lands unreviewed with the notice,
    and a non-transient fault still fails the turn;
  - 5: both columns are written.
- **A devloop load test** (reuse `~/tellr-loop/job-concurrency/load_test.py`) with at least
  8 decks at once, including skewed placement (several turns on one process) and edit turns
  as well as new decks. Watch:
  - wait times from `started_at`;
  - 429 counts and retries in the app log;
  - failed turns and their fault kind;
  - Postgres connections, against the 80 + 20 pool per process;
  - process memory and CPU;
  - how quickly a stop takes effect during a backoff.

  Tune the runner count and the cap from this. The devloop runs in the tellr-dev workspace,
  whose model capacity differs from logfood's. That is why the cap defaults to today's
  ceiling rather than a number tuned on tellr-dev.
- **After release, re-run the logfood measurement** once the owner has updated logfood and
  a week has passed:
  - the share of turns with `started_at - created_at` over a few seconds should be near
    zero;
  - the Agent failure rate should be at or below 7.2%, with the fault kinds now visible.

## Rollout

Ships in a normal release (`release-tellr`). Updating logfood and prod with `tellr.update`
is the owner's step after publishing. No configuration change is needed on the apps: the
new values are code defaults.

## Approaches considered

- **More uvicorn workers.** Rejected: see Non-goals.
- **Two runners per process** (the original option 1). Too small for "press enter,
  generation starts". With uneven placement, 3 turns on one process still queue, and 8 at
  once is already observed.
- **Runners without a model-call cap.** Rejected. It multiplies the peak load on the
  models by the runner count (up to 8 × 15 per process), which is what the 31 Oct load test
  punished.
- **A shared queue.** Deferred: see Non-goals.

## Left to the builder

- Names of the new environment variables, columns and fault kinds.
- The exact numbers within the bounds above, after the load test.
- The limiter's mechanism, provided it meets the fairness rule and the stop rule.
- How evals and admin test runs (`get_agent_test_runtime`, the offline eval harness)
  relate to the limiter and retries. They must keep their current bounded, no-retry
  behaviour.
- Test layout, and whether the load-test script needs changes.

## Still open

- **Whether the 167 failures were 429s.** On 2026-11-17 the owner asked for this to be
  checked before planning. What was tried:
  - `system.ai_gateway.usage` and `system.serving.endpoint_usage` on logfood: refused (the
    owner's account has no `USE SCHEMA` on `system.ai_gateway` or `system.serving`).
  - MLflow traces: Agent turns write none. Production uses the logging identity sink
    (`agent_runtime.py:1315`), and only Legacy turns trace into an experiment.
  - What does work: the app log records every Gateway HTTP call with its status (httpx
    INFO lines), and the OpenAI SDK logs each of its retries. A one-hour capture of the
    logfood log during weekday traffic was parsed
    (`~/tellr-loop/concurrency-runners/parse_log.py`).
  - **Result: inconclusive.** The capture covered 14:30–15:33 UTC on 2026-11-17, a quiet
    hour. Only 10 turns ran: 9 Agent turns averaging 12 s, and 1 Legacy turn. All
    completed, so there were no failures to attribute. Every one of the 31 Gateway calls
    returned 200 (25 `chat.completions`, 3 image `responses`, 3 others), and the OpenAI
    SDK logged no retries.

  The fault-kind column (section 5) answers it after release, and the devloop load test
  shows how retries behave under a burst.

- **Devloop load test (2026-11-18): results, and the cap.** The test ran 8 runs on
  `db-tellr-dev-chat-conc` (tellr-dev, MEDIUM), builds `0.5.8.dev2`–`dev4`. Each burst
  POSTed within about 1 s. Full results are in `~/tellr-loop/chat-concurrency/results.md`.
  - **Passes in every run.**
    - Every turn started within 0.8 s of its POST.
    - Nothing hung.
    - Peak Postgres connections for the app role were 44, against 400.
    - The longest turn took 870 s. No turn reached the hard timeout.
    - Every failure carried `model_fault_kind`.
    - No `wait_s` fell below 1 s, and the OpenAI SDK logged no retries.
    - A stop 1.4 s into a 7.8 s backoff freed the runner within about 1 s.
  - **Scenario (b) and the one-process runs pass in full.**
    - (b), 4 new decks and 4 edits on 4 processes: 0 failures, and 56 × 429, all retried.
    - (c), one process: 0 failures and 0 × 429 for 8 new decks (max 518 s), and for
      4 × 16-slide decks plus 4 heavy edits (max 870 s, 72 % of the clock).
  - **The 8-new-deck burst on 4 processes fails the "at most 1 failure" bar at every cap.**
    - Cap 15 gave 4 of 7 failures (290 × 429), cap 10 gave 5 of 8 (368), and cap 6 gave
      3 of 8 (274).
    - Every failure was a builder `model_call_gave_up … fault=rate_limited` at the 150 s
      budget.
    - Successes were flat at about 210 per burst. The limit is tellr-dev's shared model
      throughput. The cap bounds attempts in flight, not callers in backoff, so lowering
      it barely changed the outcome.
  - **The tuning rule moved the default to 6 (commits 256f5a7e, d30dc8e4); both are
    reverted.** Moving it contradicted the Verification section's own reasoning, that the
    cap should default to today's ceiling "rather than a number tuned on tellr-dev".
    - At cap 6, a lone 16-slide deck took 287 s, against 190 s at 15 (one sample each).
    - On one process, cap 6 is what pushes 8 long turns to 870 s.
  - **Decision (owner, 2026-11-18): the cap stays at 15 (decided).** The burst limit is
    the workspace's model throughput, which Tellr can't easily influence. So an 8-new-deck
    burst failing on a busy workspace is accepted as a known limit rather than tuned
    around. The app log records only the 429 status, not which limit it hit, so whether
    that throughput is counted in tokens or requests is unknown. After release,
    `model_fault_kind` measures how often rate limits actually end turns on logfood.
    Possible follow-ups, if that number warrants one: a longer per-call retry budget, or a
    cap that adapts to 429s.
