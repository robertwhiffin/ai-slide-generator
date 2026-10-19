# Plain-language slide-failure notices (#321) — Implementation Plan

**Date:** 2026-10-19. Revised the same day after the plan review; see "Revision log".
**Branch:** `feat/321-plain-language-failure-notice` (off `origin/main` `679d2f21`), worktree
`.claude/worktrees/issue-321`. Implementers do not commit; the supervisor commits.
**Issue:** robertwhiffin/ai-slide-generator#321. Related: #316 (findings too technical).

## Goal

When part of an agent-mode turn fails, the chat should say three things in plain language:

- which slide was affected
- what happened
- what the user can do

Slide numbers match the UI (1-based), including the related chat lines that print slide numbers today.

The technical detail stays out of the headline: graph stage, exception class or failure code, and
chat request id. That detail goes to a log line every time, with its fields inside the message
text. It also goes into a collapsed **Details** disclosure under the chat message.

Constraints:

- no migration
- no prompt or output-schema change
- no new `StreamEventType`

## Acceptance criteria (from the issue) and how each is met

**AC1.** "The notice says in plain language what happened and what the user can do (e.g. "Slide 1 couldn't be checked, so it's shown as a placeholder — ask me to regenerate slide 1"), mapped from the failure class/stage rather than exposing exception names."

- **How it is met:**
  - Task 1 adds a pure catalogue, `src/services/graph/user_notices.py`. It maps stage and failure
    class to a `headline` (short) and a `text` (the row).
  - Task 3 routes all ten notice sites through it. It also fixes three adjacent 0-based chat
    lines.
- **How it is tested:**
  - Task 1 checks every kind × position × error. Each `text` and `headline` contains:
    - no exception class or internal stage name
    - no snake_case or CamelCase token
    - no `[` or `(`

    Each is also 1-based, carries its action phrase, and is distinct from every other kind.
  - Task 3 checks that each **persisted** row the real node functions produce equals the
    catalogue's own output exactly.

**AC2.** "The technical detail (stage, exception, request id) stays available for debugging — logs and, optionally, a details disclosure — without being the headline."

- **How it is met:**
  - Task 3 writes one `graph_failure_notice` WARNING per notice. The fields are inside the message
    text, because production logs only `%(message)s`.
  - Task 2 persists `metadata={"details": …}` on the existing `info` row and forwards it on the
    polling projection.
  - Task 4 renders it as a collapsed disclosure on assistant messages.
- **How it is tested:**
  - Task 3: `record.getMessage()` carries the kind, the error and the request id. Every site test
    finds exactly one such record. An AST check stops any site from bypassing the helper.
  - Tasks 2 and 3: persisted `metadata.details`; request-id stamping, checked via
    `get_messages_for_request`.
  - Task 3 integration: the poll event carries `metadata.details` end to end.
  - Task 4 vitest: the disclosure renders closed, and only for an assistant message that has
    details. Old rows render without one.
  - Task 4 Playwright: the disclosure toggles in a real browser.

**AC3.** "Optionally, a one-click "regenerate this slide" from the placeholder."

- **How it is met:** deferred to a follow-up (Decision D4). The notice tells the user to type the
  request that the architect already handles.
- **How it is tested:** not applicable. It is recorded under Out of scope / follow-ups.

---

## Findings from the code (verified 2026-10-19 on `679d2f21`)

### F1. Failure-site inventory

**What the placeholder helper shows today.** `_placehold_failed_position`
(`src/services/graph/nodes.py:1209-1296`) produces two user-visible strings:

- an `ERROR` stream event, emitted before the commit at `nodes.py:1263-1267`:
  `"Slide {position} could not be generated."`
- a durable `info` row, written via `_surface_notice` at `nodes.py:1291-1295`:
  `"Slide {position} could not be generated and has been left as a placeholder ({node}: {reason}). The rest of the deck is unaffected."`

`reason` is `type(exc).__name__`, or `_STALL_REASON` (`nodes.py:195`). It is also the row marker
passed to `commit_placeholder(error_message=…)` (`slide_repository.py:326-383`).

**What every pipeline stage does with a persisted-runtime error.** Every pipeline stage calls
`_raise_if_persisted_runtime_failure(exc)` (`nodes.py:169-171`) **before** it placeholds. So a
`PersistedRuntimeError` is never noticed at sites 1-3; it fails the turn. That is true whether the
error is transient or not, and it covers `PinnedInvocationEndpointError` and every
`PersistedConfigurationUnavailableError`. Sites 5-6 are the only transient carve-out.

| # | Site | Node / stage | Failure class (how it arises) | Current user text | New kind |
|---|---|---|---|---|---|
| 1 | `nodes.py:2315-2326` | `builder` (pipeline stage) | `UnsafeContentError`: the safety gate rejected the output twice. The gate already retried once with `_SAFETY_CORRECTION` (`nodes.py:2287-2300`). Patterns are in `src/utils/html_safety.py:74-108`; exception in `src/services/agent.py:83` | template above, `(builder: UnsafeContentError)` | `blocked_unsafe` |
| 1b | same | `builder` | Unusable output: `ValidationError` / `OutputParserException` (`is_provider_parse_error`, `agent_runtime.py:615-627`) or `AgentOutputValidationError` (`agent_schema_registry.py:357`). Also any other non-`PersistedRuntimeError` | `(builder: ValidationError)` etc. | `build_failed` |
| 2 | `nodes.py:2487-2503` | `build_reviewer` | A parse error left after the one retry (`nodes.py:2427-2440`), a findings-stamping error, or a row-write failure | `(build_reviewer: ValidationError)` (the issue's example) | `check_failed` |
| 3 | `nodes.py:2894-2934` | `fix_reviewer` | The row could not be delivered: a prior `Finding` failed `model_validate`, or the write failed | `(fix_reviewer: …)` | `save_failed` |
| 4 | `nodes.py:3276-3284` | `placeholder` node (stall reconciliation) | The branch never returned (`stalled_positions`) | `(placeholder: Slide generation did not complete)` | `stalled` |
| — | any other `node` value | — | A future stage | — | `slide_failed` (safe generic fallback) |
| 5 | `nodes.py:3146-3168`, which calls `_transient_failure_notice` at `nodes.py:3000-3006` | `slide_pipeline` review step | A transient fault while reviewing, **and a draft was written**. "Transient" is `is_transient_model_failure` (`agent_runtime.py:474-512`): 408/409/429/5xx, timeouts or dropped connections, read off the `raise … from` chain. The draft is kept. | `"Slide {position}: the model was briefly unavailable while it was being reviewed, so it is shown as built."` | `kept_unreviewed` |
| 6 | `nodes.py:3189-3214`, which calls the same helper | `slide_pipeline` fix round | A transient fault from the fixer or fix_reviewer. These re-raise at `2716`, `2877` and `2895`, and the pipeline catches the error at `3189`. The original is landed with its findings surfaced. | `"… being fixed, so it is shown as built."` | `kept_unfixed` |
| 7 | `nodes.py:2171-2193` | `foreman` END with work outstanding | Positions that are neither landed nor placeheld (a bug path) | info + `ERROR`: `"Some slides could not be completed and could not be reconciled: positions [1, 3]."` | `slides_unfinished` |
| 8 | `nodes.py:3435-3447` | `deck_reviewer` deck-level write | `write_deck_level_columns` raised | `"The deck's slides were saved, but the deck's own record of them could not be updated this turn (deck_reviewer: RuntimeError)."` | `deck_not_updated` |
| 9 | `nodes.py:3396-3403`, `3449-3459` | `deck_reviewer` derivation | Reading or knitting the deck raised, so the review is skipped | `"Your slides were saved, but … so the deck-level review was skipped (deck_reviewer: RuntimeError)."` | `deck_not_updated_review_skipped` |
| 10 | `nodes.py:3500-3511` | `deck_reviewer` review | The review model call, its findings, or the save raised a **non**-`PersistedRuntimeError`. A `PersistedRuntimeError`, transient or not, is re-raised at `nodes.py:3501` and fails the turn instead; see the transient inventory below. | `"The deck is complete, but the deck-level review could not be completed this turn."` This has no technical text, but also no details and no log record. | `deck_review_failed` |

**Transient or typed runtime faults that fail the turn instead.** Out of scope; see D8 and
follow-ups 2a/2b. In each of these cases the user sees "Pinned graph configuration is unavailable",
which comes from `chat_service.py:321-327` (`1976-2005`) and `job_queue.py:36`, `46-51` and
`260-265`.

- **Builder.** `nodes.py:2316`. `slide_pipeline_node` calls `builder_node` unguarded
  (`nodes.py:3131`).
- **Build review on an edit/regenerate turn.** `_write_draft_row` writes no draft when the position
  already has a row (`nodes.py:3049`), so the pipeline re-raises (`nodes.py:3153`). This is the turn
  that "ask me to regenerate slide N" leads users into: the placeholder row exists, so no draft is
  written.
- **Deck review** (`nodes.py:3501`). This fires after every slide has landed. The turn fails with
  no `COMPLETE` and no save point, because `chat_service.py:2084-2085` raises before the save point.
- **Architect deck-level re-review** (`nodes.py:708`).
- **Architect and data_analyst model calls.** There is no catch at all.

The contract is pinned by:

- `test_persisted_graph_runtime_failures_postgres.py:44`, `270`
- `test_architect_reply_is_persisted.py:298-361`
- `test_streaming.py:465-502`
- `test_graph_mode_turn.py:649-668`
- `test_slide_pipeline.py:491-505`
- `test_lakebase_contract_failures_postgres.py:389-403`

**Other non-notice paths.** None of these changes.

- **`fixer_node` failure** (`nodes.py:2715-2730`) and a failed fix re-review (`nodes.py:2876-2881`)
  keep the original silently. The findings stay open in the AI feedback drawer. This is deliberate.
- **The architect's pre-fan-out deck-level write failure** (`nodes.py:~1978-1985`) sets
  `error_state` only.
- **Any other turn failure** shows `GRAPH_TURN_FAILED_MESSAGE` (`chat_service.py:308`), which is
  already plain.
- **`error_state`** (`state.py:264`) has no consumer outside `nodes.py` (grep). It stays technical
  and unchanged.
- **The sweeper** (`spec_sync.py`) writes no chat rows.
- **`tour.py`** writes scripted `info` rows with `metadata={"tour_stage", "node"}` only.

### F2. Slide numbering: today's notices are off by one

`position` is 0-based everywhere in data:

- `architect.py:85` ("`position: 0-indexed integer`")
- `architect.py:116-118` ("In `message` only, speak about slides 1-indexed, matching the UI. `position` and `target_positions` stay 0-indexed.")
- `slide_repository.py:127`
- `StreamEvent.position` (`streaming.py:66`)
- the poll docstring, `chat.py:861-863`

The UI numbers slides 1-based:

- `ThumbnailRibbon.tsx:133` and `SlideTile.tsx:181`: `Slide {index + 1}`
- `SpecView.tsx:214`: `Slide {slide.position + 1}`
- `AppLayout.tsx:1066`: `slide ${finding.slideIndex + 1}`

The notices print the raw position (`nodes.py:1265`, `1293`, `3004`). A test pins this:
`test_graph_nodes.py:2799` asserts `"Slide 0"` for the deck's first slide. The issue's own example,
"Slide 1 … (build_reviewer: …)", was actually the **second** slide. A user who typed
"regenerate slide 1" after that notice would get position 0 rebuilt, which is the wrong slide.

Rows are contiguous from 0, because the reorder buffer's prefix starts at 0
(`session_manager.py:2197-2215`). So `position + 1` is the number the ribbon shows.

**Three more 0-based chat lines, all fixed in Task 3:**

- **`"Rebuilding {len(rebuild)}: {rebuild}."`** (`nodes.py:1873`), part of the architect's
  deck-level re-review summary (`nodes.py:1869-1876`).
  - It is **persisted** via `_say(state, message)` (`nodes.py:1909`), as `llm_response` with a
    request id.
  - So it is shown on polling and on reload, and it is replayed to the architect as its own words
    (`_AI_TYPES`, `nodes.py:200-201`). That contradicts the architect's 1-indexed rule.
  - Pinned by `tests/integration/test_deck_spec_change_turn.py:485`
    (`"Rebuilding 1: [2]"`), whose docstring (`:449-457`) explains that the row is persisted on
    purpose.
  - `tests/unit/test_deck_level_spec_change.py:944` pins `metadata["rebuilding"] == [2]`, which
    stays 0-based. `:955` pins only `"re-checked all 3"`.
- **`"Slide {position} reviewed: {verdict}."`** (`nodes.py:2462`) and
  **`"Slide {position} fix reviewed: {verdict}."`** (`nodes.py:2938`).
  - These are `_emit`-only, so they reach SSE/dev only. `job_queue` keeps only
    `COMPLETE`/`SESSION_TITLE`, and `test_tour_staged_demo.py:101-103` notes this.
  - No test pins the number. The tour's regex `^Slide \d+ (fix )?reviewed:`
    (`test_tour_staged_demo.py:96`) does not care which number appears.
  - #319's plan uses its own progress tracker, not these strings.

No other 0-based slide number exists in graph chat text. The binding-degrade text is already 1-based
(`template_sections.py:481`).

### F3. Message model and transports

**Row.** `_surface_notice` (`nodes.py:1162-1206`) calls
`add_message(role="assistant", message_type="info", request_id=get_chat_request_id())`.

- It passes no `metadata`, although `add_message` accepts one (`session_manager.py:1462-1493`).
- Metadata would be stored in the existing `session_messages.metadata_json` TEXT column
  (`models/session.py:284`). **No migration is needed.**
- `info` is excluded from the architect's replay by `_conversation` (`nodes.py:965-988`, types at
  `nodes.py:200-201`) and by `chat_service._hydrate_chat_history`.

**Polling** (production; `api.ts:35-58` forces it in prod and on `*.databricks.com`):

1. `poll_chat` (`chat.py:900-913`) calls `get_messages_for_request`, which returns `metadata`
   (`session_manager.py:3332-3368`).
2. `msg_to_stream_event` (`session_manager.py:3370-3398`) **drops all metadata** except
   `tool_name`/`tool_input`.
3. `startPolling` (`api.ts:1110-1117`) passes the event to `onEvent`.
4. ChatPanel's `case 'assistant'` (`ChatPanel.tsx:211-222`) keeps only role, content and timestamp.

**SSE** (local dev):

- The route yields emitter events only (`chat.py:620-631`), so **`info` rows are not streamed**.
- The placeholder's `ERROR` event reaches ChatPanel's `case 'error'` (`ChatPanel.tsx:271-276`). That
  shows the red `ErrorDisplay` banner and ends the loading state while the turn is still running.
  The second effect is a pre-existing SSE-only defect (follow-up).
- The transient and deck-write notices have no SSE event at all.
- The deck-review advisory is emitted as `ASSISTANT` (`nodes.py:3523-3527`).

**Reload** (both transports):

- `GET /api/sessions/{id}` (`sessions.py:539-554`) calls `get_messages`, which includes `metadata`
  (`session_manager.py:1508-1538`).
- `loadSessionMessages` (`ChatPanel.tsx:97-124`) maps only tool metadata.

**Two more readers drop metadata, by design.** The save-point preview maps role and content only
(`AppLayout.tsx:742-746`). The MCP transcript does the same (`mcp_server.py:818-826`).

**Rendering.** `Message.tsx` looks only at `role` and the shape of the content. It never reads
`message_type` (`nodes.py:3355-3359`).

**Safety.**

- `chat_service.py:301-306` says exception text can carry model output, so no detail may contain
  it.
- #271's identity-safe contract forbids typed runtime-failure names in anything client-facing:
  - `test_architect_reply_is_persisted.py:301`
  - `test_streaming.py:502`
  - `test_graph_mode_turn.py:659-668`
  - `test_persisted_graph_runtime_failures_postgres.py:275`
- Chat rows are visible only to their creator (`sessions.py:536-541`). The poll requires the owner
  of the request (`chat.py:883-890`).

### F4. Logging in production

- The app boots on `logging.basicConfig` with a `"%(message)s"` format, so **`extra=` fields never
  reach the log** (`src/core/databricks_client.py:306-310`).
- `setup_logging()` and its `JSONFormatter` (`src/utils/logging_config.py`) have no caller in `src/`
  or `packages/` (grep). The root logger stays at WARNING
  (`tests/unit/test_logging_extra_reserved_keys.py:11-17`).
- So a field is only visible if it is inside the message text.
- Repo convention for the chat request id in `extra` is the key `request_id`:
  - `job_queue.py:82`, `207`, `285`
  - `session_manager.py:3211`

### F5. Tests that pin current text (all must be updated; none may lose an invariant)

**`tests/unit/test_graph_nodes.py`:**

- **`:1620-1624`.** Today the foreman notice contains `"positions [1]"`.
  - Change: content `== unfinished_slides_notice([1]).text`.
  - Keep the `error_state` code and positions assertions.
- **`:2083-2093`.** Today `"Slide 2"` and `"build_reviewer"` appear in the content (position 2).
  - Change: content `== placeholder_notice(2, stage="build_reviewer", error="RuntimeError").text`.
  - Change: `metadata.details == {"stage": "build_reviewer", "error": "RuntimeError"}`.
  - Keep `len(info) == 1`.
- **`:2783-2799`.** Today `"Slide 0"` and `"fix_reviewer"`.
  - Change: content `== placeholder_notice(0, stage="fix_reviewer", error="RuntimeError").text`.
  - Change: `details.stage == "fix_reviewer"`.
  - Keep the `error_state` assertions and `len(info) == 1`.
- **`:2944-2951`.** Today `"Slide 1"`, `"Slide 2"` and `"(placeholder: Slide generation did not complete)"`.
  - Change: contents `== [placeholder_notice(p, stage="placeholder", error=_STALL_REASON).text for p in (1, 2)]`.
  - Change: `details.error == _STALL_REASON`.
  - Keep the two-rows, role and order assertions.
- **`:3207-3210`.** Today `"could not be updated this turn"`.
  - Change: content `== deck_not_updated_notice(review_skipped=True, error="RuntimeError").text`.
  - Keep `len(info) == 1`, the `"no narrative issues" not in` check, and the no-model-call check.
- **`:3255-3257`.** Today `"could not be updated this turn"`.
  - Change: `deck_not_updated_notice(review_skipped=False, error="RuntimeError").text in contents`.
- **`:3337-3338`.** Today `"could not be completed"`.
  - Change: content `== deck_review_failed_notice(error="RuntimeError").text`.

**`tests/unit/test_slide_pipeline.py`:**

- **`:450-468`.** The transient **review** fails at position 1, and the test asserts `"Slide 1"`.
  - Change: the info row equals `unreviewed_slide_notice(1, during="review").text` ("Slide 2").
  - Change: `details.error == "model_temporarily_unavailable"`.
  - Change: `"PinnedInvocation" not in json.dumps(row)` and `"system.ai" not in json.dumps(row)`.
- **`:470-489`.** The transient **fix** fails at **position 0**, and there is no info assertion
  today.
  - **Add** an info-row assertion: content `== unreviewed_slide_notice(0, during="fix").text`.
  - Also assert `assert_numbered(text, 0)` and apply the same two `json.dumps` checks.

**`tests/unit/test_graph_builder.py:700-701`.** Today `"Slide 1"` (position 1).

- Change: `"Slide 2"`, plus `details.stage == "build_reviewer"`.

**`tests/unit/test_deck_level_spec_change.py:955`.** Today `"re-checked all 3"`. Keep that, and add:

- `"Rebuilding slide 3." in notices[0].content`
- `"[" not in notices[0].content`
- `:944` (`metadata["rebuilding"] == [2]`) stays unchanged.

**`tests/integration/test_graph_orchestration.py:404-407`, `481-489`.** Today they match `"(builder:"`
in the content and `"Slide 1"`.

- Change: select rows by `(m.get("metadata") or {}).get("details", {}).get("stage") == "builder"`.
- The position-1 text equals `placeholder_notice(1, stage="builder", error="RuntimeError").text`.
- Keep both counts (2 and 1).

**`tests/integration/test_architect_reply_is_persisted.py:543-566`.** Today it finds the poll event
containing `"left as a placeholder"` and `"Slide 1"`.

- Change: select the poll event whose `metadata.details.stage == "builder"`.
- Assert `"Slide 2"` and `"regenerate slide 2"`.
- Assert `details.request_id ==` the turn's request id. This is the end-to-end proof that the
  request id survives the `Send` fan-out.

**`tests/integration/test_deck_spec_change_turn.py:485`.** Today `"Rebuilding 1: [2]"`.

- Change: `"Rebuilding slide 3." in summaries[0]` and `"[" not in summaries[0]`.

Tests that are **unchanged and must stay green:**

- **`test_graph_orchestration.py:611-657`.** It pins the `error_message` values `RuntimeError` and
  `"Slide generation did not complete"`. Row-marker semantics stay.
- **`test_mixed_release_collaboration_acceptance_postgres.py:472-487` and `1458-1490`.**
  - They require that `mutation` stays REQUIRED.
  - They require **exactly 4** lines containing `_placehold_failed_position(` outside its `def`,
    each with `mutation=` within 9 lines.
  - This file is postgres-marked and self-skips without `TELLR_TEST_POSTGRES_URL`.
- **`test_graph_nodes.py:194-213`, `1680-1745` and `2850-2880`.** These call the helper or
  monkeypatch it with `**kwargs`.
- **`test_tour_staged_demo.py:94-97`.** Its regex does not care which number appears.

No frontend test or Playwright spec asserts any of these strings (grep of `frontend/` is empty).

### F6. Docs describing these surfaces

No doc describes the graph failure notices today. The docs that touch the surrounding behaviour:

- `docs/technical/real-time-streaming.md`:
  - documents `metadata_json` as "JSON with `tool_name`, `tool_input`" (line ~508)
  - documents the poll response shape (lines ~293-307)
- `docs/technical/frontend-overview.md:324` describes `Message.tsx`.
- `docs/user-guide/01-generating-slides.md`, "Iterating on Your Slides" (lines 54-64), has no row for
  regenerating a single slide.

---

## Decisions

**D1 — Wording style.**

- Second person, at most two sentences.
- Order: the 1-based slide number, what happened in plain words, the slide's state, then **one**
  concrete action the system supports.
- The text never contains:
  - an exception or class name
  - a node or stage identifier
  - a 0-based position or a Python list
  - "position" or "reconcile"
  - a `(stage: Error)` suffix
- Contractions follow the issue's own example.
- Each kind also has a short **headline** with no claim about the slide's state. The headline is
  used where the state is not yet known (D2).
- Tests pin the catalogue's invariants. Site tests compare each row with the catalogue's own output.
  So a later copy edit touches only Task 1's key-phrase assertions.

**D2 — Numbering and the pre-commit event.**

- Every user-facing number is `position + 1`, via `slide_number`. Lists of slides use
  `slides_phrase`.
- This applies to the notices and to the three lines in F2:
  - "Rebuilding slide 3." (and "Rebuilding slides 2 and 4." for several)
  - "Slide 3 reviewed: clean."
  - "Slide 1 fix reviewed: fixed."
- Data stays 0-based: event `metadata.position`/`positions`/`rebuilding`, `error_state`, the log
  `positions=` field, and the row marker.
- **The placeholder `ERROR` event uses `notice.headline`** (for example "Slide 3 couldn't be
  built."), because it is emitted **before** the commit (`nodes.py:1262-1267`). If the commit or
  read-back fails (`nodes.py:1276-1289`), no placeholder exists, so the event must not claim one.
  Today's pre-commit text deliberately makes no such claim either.
- **The foreman `ERROR` event uses `notice.text`.** It is emitted in the same synchronous block as
  the row, with no commit in between, and its claim ("may be missing or out of date … send your
  request again") holds whether or not the row write succeeds.

**D3 — Details disclosure: yes, with no migration.**

- **Payload.** The row is written with
  `metadata={"details": {"stage": …, "error": …, "request_id": …}}`. Keys whose value is `None` are
  omitted.
- **What `error` may hold.** Either an exception **class name** that is not a
  `PersistedRuntimeError` subclass, or a fixed code: `_STALL_REASON`,
  `"model_temporarily_unavailable"` or `"end_with_outstanding_positions"`.
  - It never holds `str(exc)`, because that can echo model output (F3).
  - **It never holds a `PersistedRuntimeError` subclass name** (#271).
- **Why that rule holds at each site:**
  - Placeholder sites re-raise those errors before noticing (`nodes.py:2316`, `2488`, `2895`), and
    so does the deck review (`nodes.py:3501`).
  - The deck write and derivation paths call database and CSS code only, never the agent runtime.
  - Transient notices always carry the code `MODEL_TEMPORARILY_UNAVAILABLE`, never the caught
    exception. The useful cause (429, 5xx, timeout) is on the `raise … from` chain, which the
    existing `logger.warning(..., exc_info=True)` at `nodes.py:3154-3158` and `3195-3199` already
    logs.
- **No positions in details.** The headline already numbers the slide, and a 0-based number in a
  user-visible disclosure would bring back F2.
- **Polling.** `msg_to_stream_event` adds `"metadata": {"details": …}` only when the row has a dict
  of details; otherwise `"metadata": None`. It never forwards a row's whole metadata, because a tool
  row's metadata carries the tool's input.
- **Reload** already returns `metadata`.
- **SSE.** The placeholder and foreman `ERROR` events, and the deck-reviewer failure `ASSISTANT`
  event, carry `metadata.details`.
- **Frontend.** ChatPanel reads `event.metadata?.details` on both transports, and
  `msg.metadata?.details` on reload. `Message.tsx` renders a closed native `<details>` only when
  `message.role === 'assistant'`.
- **Old rows.** They have `metadata_json` NULL or tool/tour metadata only, so they render exactly as
  today and keep their old (0-based) text.
- **Accepted gap.** On SSE (dev-only) the banner shows the headline without a disclosure.
  `case 'error'` stays unchanged.

**D4 — One-click "regenerate this slide": not in this PR; follow-up.**

- The issue asks for it "from the placeholder". The placeholder is backend-authored iframe HTML
  (`slide_repository.py:366-368`), and the frontend has no way to detect it (grep of `frontend/src`
  is empty).
- Building it means a new `SlideViewer` affordance with:
  - the "Optimize layout" double-spend guard (`SlideViewer.tsx:359-391`)
  - lock and read-only gating
  - an agreed message text
- A button on a chat notice would re-fire from stale history after the slide was already
  regenerated.
- Most importantly, no eval pins the model behaviour it depends on: whether the architect
  classifies a bare "Regenerate slide N" as `edit` with `target_positions=[N-1]`. That is #313's
  territory. A user can rephrase a typed request that gets misclassified; a button cannot be
  rephrased.
- The typed path works today:
  - `edit` intent (`architect.py:20-21`)
  - the 1-indexed rule (`architect.py:116-118`)
  - named and changed positions are rebuilt (`nodes.py:1758-1769`)
  - a placeholder row is a committed row, so `_persisted_spec_describes_these_rows` passes
    (`nodes.py:1006-1040`)
- **Caveat.** A transient review fault on that regenerate turn still fails the turn (F1, D8).

**D5 — Where the helper lives.** `src/services/graph/user_notices.py`.

- It is pure and imports stdlib only. A test pins this.
- The one class-dependent decision is the safety gate. It is made in `nodes.py` with
  `isinstance(error, UnsafeContentError)` and passed in as `unsafe=`.
- #316 can reuse `slide_number`, `slides_phrase`, and the `metadata.details` payload with the
  disclosure for finding detail.

**D6 — What is logged.** One WARNING per failure notice, written from `_surface_failure_notice` only.
The fields go **in the message**, because of F4:

```python
logger.warning(
    "graph_failure_notice kind=%s stage=%s error=%s positions=%s request_id=%s session_id=%s",
    notice.kind, notice.stage, notice.error, list(notice.positions),
    notice.details.get("request_id"), session_id,
    extra={"notice_kind": …, "graph_stage": …, "error_class": …, "positions": …,
           "request_id": …, "session_id": …},
)
```

- `extra` is kept for any structured handler wired later.
- `positions=` is labelled as positions because the values are **0-based**; nobody should read them
  as slide numbers.
- `request_id` is the repo's own key for this id (F4).
- WARNING is the lowest level the production root logger emits.
- The existing `logger.exception` tracebacks at each site stay.
- An AST test stops a site from calling `_surface_notice(..., details=...)` directly and skipping the
  log.

**D7 — Unchanged on purpose.**

- `reason`: the row marker passed to `commit_placeholder(error_message=)`.
- `error_state` contents.
- The `info` type, request-id stamping, and ungated writing on describe-only turns.
- The `ERROR` type of the placeholder and foreman events.
- `_advisory_text` (#316).
- Agent definitions, prompts and output schemas. **No digest moves.**

**D8 — Transient and typed runtime faults that fail the turn are out of scope.** The F1 inventory
lists them. Changing them alters #271's fail-closed contract and needs two separate decisions
(follow-ups 2a and 2b). Neither is implemented here.

---

## Global constraints

- **Environment and process:**
  - Run `uv sync --extra dev` once in the worktree root, then run everything via `uv run`.
  - Never use `pip install`.
  - Do not commit; the supervisor commits.
  - Do not deploy.
  - Never use `git stash`.
- **Baselines are cause-sets** (recorded in `~/tellr-loop/issues/issue-321/`):
  - **Backend.** `uv run pytest tests/unit -n 4 -q` gives 9166 passed and 0 failed: the cause-set
    is empty. Before Task 1, record the integration cause-set for the files named in Task 6.
  - **Frontend vitest** (Node 26 locally) has two known causes:
    - **C-FE1:** `localStorage` is undefined under Node 26 in `FindingsE2.test.tsx`,
      `SlideViewer.test.tsx` and `TourViewerBridge.test.tsx`.
    - **C-FE2:** a 5000 ms timeout in `AgentDefinitionWorkbench.test.tsx` ("fetches the catalog
      once … Refresh models").

    The rule: **no new causes**.
  - **Frontend lint.** `baseline-lint.txt` has 63 errors and 9 warnings on main; CI does not run
    lint. The rule for each touched file: the set of (rule id, message) pairs it reports must be a
    subset of that file's baseline entries. Compare ignoring line numbers, because the edits shift
    them. New files must be lint-clean.
- **Do not touch:**
  - `src/core/skills/*`
  - `src/services/agent_definition_manifest_v1.py`, or any schema digest
  - `_advisory_text` (#316)
  - `case 'error'` and `ErrorDisplay`
  - `clear_context` (#323)
  - the turn-failure contract (D8)
- **Literal-text rule.** The text `_placehold_failed_position(` may appear only on its `def` line and
  its four call sites. That includes comments and docstrings.
- **`mutation`** stays keyword-only with no default.
- **Sabotage.** Every new test gets one, recorded in the task report: break the production line, see
  it go red, restore it, see it go green.
- **ContextVars.** Any test that sets `set_chat_request_id` (`event_emitter.py:89`) or
  `set_event_emitter` (`event_emitter.py:113`) must reset it to `None` in a `finally`.

## File map

**Catalogue (Task 1):**

- `src/services/graph/user_notices.py` (new)
- `tests/unit/test_graph_user_notices.py` (new)
- `tests/fixtures/notice_assertions.py` (new shared assertions; it sits beside
  `tests/fixtures/model_payload_keys.py`)

**Row and projection (Task 2):**

- `src/services/graph/nodes.py`: `_surface_notice` only
- `src/api/services/session_manager.py`: `msg_to_stream_event`
- `src/api/routes/chat.py`: one docstring sentence
- `tests/unit/test_graph_nodes.py`
- `tests/unit/test_poll_notice_details.py` (new)

**Wiring (Task 3):**

- `src/services/graph/nodes.py`
- `tests/unit/test_graph_nodes.py`, `tests/unit/test_slide_pipeline.py`,
  `tests/unit/test_graph_builder.py`, `tests/unit/test_deck_level_spec_change.py`
- `tests/integration/test_graph_orchestration.py`,
  `tests/integration/test_architect_reply_is_persisted.py`,
  `tests/integration/test_deck_spec_change_turn.py`

**Frontend (Task 4):**

- `frontend/src/types/message.ts`
- `frontend/src/utils/messageDetails.ts` (new)
- `frontend/src/components/ChatPanel/ChatPanel.tsx`
- `frontend/src/components/ChatPanel/Message.tsx`
- new vitest files:
  - `frontend/src/utils/messageDetails.test.ts`
  - `frontend/src/components/ChatPanel/Message.test.tsx`
  - `frontend/src/components/ChatPanel/ChatPanel.noticeDetails.test.tsx`
- `frontend/tests/e2e/chat-ui.spec.ts`

**Docs (Task 5):**

- `docs/technical/real-time-streaming.md`
- `docs/technical/frontend-overview.md`
- `docs/user-guide/01-generating-slides.md`

**Order.**

1. Task 1.
2. Task 2 (it is the first to touch `nodes.py`).
3. Task 3 (`nodes.py` again, plus test files Task 2 also touches).
4. Task 4 touches only the frontend and may run in parallel with Tasks 2 and 3.
5. Task 5 after Tasks 3 and 4.
6. Task 6 last.

---

## Task 1: The plain-language catalogue (`user_notices.py`)

**Models:** test=opus impl=sonnet

**Files:**

- `src/services/graph/user_notices.py` (new)
- `tests/unit/test_graph_user_notices.py` (new)
- `tests/fixtures/notice_assertions.py` (new)

Interface (introduced here; nothing else may be invented):

```python
# src/services/graph/user_notices.py — stdlib only (dataclasses, typing, __future__)
NoticeKind = Literal[
    "build_failed", "blocked_unsafe", "check_failed", "save_failed", "stalled", "slide_failed",
    "kept_unreviewed", "kept_unfixed", "slides_unfinished",
    "deck_not_updated", "deck_not_updated_review_skipped", "deck_review_failed",
]

#: The error code every transient notice carries — never the caught exception's class,
#: which for a transient fault is always a PersistedRuntimeError subclass (#271).
MODEL_TEMPORARILY_UNAVAILABLE: Final = "model_temporarily_unavailable"

#: Stage -> kind for a placeholder. Any stage not listed maps to "slide_failed".
PLACEHOLDER_STAGE_KINDS: Mapping[str, NoticeKind] = {
    "builder": "build_failed", "build_reviewer": "check_failed",
    "fix_reviewer": "save_failed", "placeholder": "stalled",
}

@dataclass(frozen=True)
class FailureNotice:
    kind: NoticeKind
    headline: str                  # short; no claim about the slide's state (pre-commit events)
    text: str                      # the full message the chat row carries
    stage: str                     # technical: graph node / pipeline stage
    error: Optional[str]           # technical: exception class name or a fixed code
    positions: Tuple[int, ...]     # technical, 0-based, for logs only
    details: Dict[str, str]        # what the chat disclosure shows

def slide_number(position: int) -> int                     # position + 1
def slides_phrase(positions: Iterable[int]) -> str         # sorted, de-duplicated, lowercase; ValueError if empty
def placeholder_notice(position: int, *, stage: str, error: Optional[str],
                       unsafe: bool = False, request_id: Optional[str] = None) -> FailureNotice
def unreviewed_slide_notice(position: int, *, during: Literal["review", "fix"],
                            request_id: Optional[str] = None) -> FailureNotice
def unfinished_slides_notice(positions: Iterable[int], *,
                             request_id: Optional[str] = None) -> FailureNotice
def deck_not_updated_notice(*, review_skipped: bool, error: Optional[str],
                            request_id: Optional[str] = None) -> FailureNotice
def deck_review_failed_notice(*, error: Optional[str],
                              request_id: Optional[str] = None) -> FailureNotice
```

Behaviour:

- **`slides_phrase`:**
  - `slides_phrase([3]) == "slide 4"`
  - `slides_phrase([3, 1]) == "slides 2 and 4"`
  - `slides_phrase([4, 1, 3, 3]) == "slides 2, 4 and 5"`

  At the start of a sentence the first letter is capitalised.
- **`placeholder_notice` kind:** `"blocked_unsafe"` when `unsafe` is true, whatever the stage.
  Otherwise `PLACEHOLDER_STAGE_KINDS.get(stage, "slide_failed")`.
- **`unreviewed_slide_notice`:**
  - kind `kept_unreviewed` for `during="review"`, with stage `"build_reviewer"`
  - kind `kept_unfixed` for `during="fix"`, with stage `"fix_round"`
  - `error` is always `MODEL_TEMPORARILY_UNAVAILABLE`; there is no parameter for it
- **`unfinished_slides_notice`:** stage `"foreman"`, error `"end_with_outstanding_positions"`.
- **Deck builders:** stage `"deck_reviewer"`.
- **`positions`:**
  - `(position,)` for slide notices
  - the sorted outstanding tuple for the foreman
  - `()` for deck notices
- **`details`:** `{"stage": stage, "error": error, "request_id": request_id}` with `None` values
  removed. Every value is a `str`.

**Catalogue.** `{n}` is `slide_number(position)`. `{Slides}` is `slides_phrase(...)` capitalised.
Transcribe exactly. Each text is at most two sentences and contains no `(` or `[`.

**`build_failed`**
- headline: `Slide {n} couldn't be built.`
- text: `Slide {n} couldn't be built, so it's shown as a placeholder — ask me to regenerate slide {n}.`

**`blocked_unsafe`**
- headline: `Slide {n} was blocked by a safety check.`
- text: `Slide {n} was blocked by a safety check because it included something a deck can't contain, such as content loaded from the web. It's shown as a placeholder — ask me to regenerate slide {n} without it, for example without external images, videos or links.`

**`check_failed`**
- headline: `Slide {n} was built but couldn't be checked.`
- text: `Slide {n} was built but couldn't be checked, so it's shown as a placeholder — ask me to regenerate slide {n}.`

**`save_failed`**
- headline: `Slide {n} couldn't be saved after its automatic fix.`
- text: `Slide {n} couldn't be saved after its automatic fix, so it's shown as a placeholder — ask me to regenerate slide {n}.`

**`stalled`**
- headline: `Slide {n} didn't finish building.`
- text: `Slide {n} didn't finish building, so it's shown as a placeholder — ask me to regenerate slide {n}.`

**`slide_failed`**
- headline: `Slide {n} couldn't be generated.`
- text: `Slide {n} couldn't be generated, so it's shown as a placeholder — ask me to regenerate slide {n}.`

**`kept_unreviewed`**
- headline: `Slide {n} hasn't been checked.`
- text: `Slide {n} is shown as first built: the AI service was briefly unavailable, so it hasn't been checked. If it doesn't look right, ask me to regenerate slide {n}.`

**`kept_unfixed`**
- headline: `Slide {n} is shown without its automatic fix.`
- text: `Slide {n} is shown without its automatic fix because the AI service was briefly unavailable. The issues found are in the slide's AI feedback — choose Apply there to try the fix again, or ask me to regenerate slide {n}.`

**`slides_unfinished`**
- headline: `{Slides} couldn't be finished.`
- text: `{Slides} couldn't be finished this time and may be missing or out of date. Please send your request again.`

**`deck_not_updated`**
- headline: `The deck couldn't be fully updated.`
- text: `Your slides were saved, but the deck couldn't be fully updated, so its slide count and exports may be out of date. They'll refresh the next time I build or edit slides.`

**`deck_not_updated_review_skipped`**
- headline: `The deck couldn't be fully updated, and its review was skipped.`
- text: `Your slides were saved, but the deck couldn't be fully updated, so its slide count and exports may be out of date, and the review of the deck as a whole was skipped. Both will run again the next time I build or edit slides.`

**`deck_review_failed`**
- headline: `The review of the deck as a whole couldn't run.`
- text: `The deck is ready, but the review of the deck as a whole couldn't run this time. It will run again the next time I build or edit slides.`

Where the wording comes from:

- **`blocked_unsafe`.** The gate blocks more than web loads: `eval`, inline handlers, `javascript:`
  URIs and navigation (`html_safety.py:74-108`). It has already retried once, so the action asks the
  user to drop the offending content.
- **`kept_unfixed`.** It points at the drawer's **Apply** button (`FeedbackDrawer.tsx:80`,
  `142-144`, `AppLayout.tsx:1062-1068`), which retries exactly the skipped fix.
- **`slides_unfinished`.** It says "send your request again" rather than "regenerate slide N". On a
  first-build turn the outstanding positions have no rows, so an edit would degrade with
  `spec_positions_stale` (`nodes.py:1654`). A resent request works on build and edit turns alike.

Steps:

- [ ] **Step 1 (test author).** Write `tests/fixtures/notice_assertions.py`. Tasks 1 and 3 reuse it.
  - `assert_plain_language(text)` fails on any of the following:
    - a token matching `\b[a-z]+_[a-z_]+\b`
    - a CamelCase token `\b[A-Z][a-z]+[A-Z]\w*\b`
    - `[` or `(`
    - `"position"`, case-insensitive
    - `"reconcile"`
    - any of the identifiers `builder`, `build_reviewer`, `fixer`, `fix_reviewer`, `foreman`,
      `deck_reviewer`, `slide_pipeline`, `architect`, `data_analyst`
    - any of the class names `ValidationError`, `OutputParserException`,
      `AgentOutputValidationError`, `UnsafeContentError`, `RuntimeError`,
      `PinnedInvocationEndpointError`, `PersistedRuntimeError`, `ModelProviderUnavailableError`,
      `KeyError`, `Exception`
  - `assert_numbered(text, position)` requires `[Ss]lide {position+1}` to be present and
    `\bslide {position}\b` (case-insensitive) to be absent.
  - `failure_notice_records(caplog)` returns the records whose `getMessage()` starts with
    `"graph_failure_notice "`.

  Then write `tests/unit/test_graph_user_notices.py`:

  1. Parametrise every builder over:
     - positions `{0, 1, 9}`
     - every stage in `PLACEHOLDER_STAGE_KINDS` plus `"some_future_stage"`
     - error names drawn from the class list above

     Assert `assert_plain_language` on **both** `text` and `headline`. For slide notices, also
     assert `assert_numbered` on both.
  2. Check the action phrase in `text`:
     - every placeholder kind, `kept_unreviewed` and `kept_unfixed` contain `regenerate slide {n}`
     - `kept_unfixed` also contains `Apply`
     - `slides_unfinished` contains `send your request again`
     - both deck-not-updated kinds and `deck_review_failed` contain `next time I build or edit`
     - no `headline` contains "placeholder"
  3. Check the kind mapping:
     - the stage table holds
     - an unknown stage gives `slide_failed`
     - `unsafe=True` gives `blocked_unsafe` for every stage
     - `during="review"` gives `kept_unreviewed`, and `"fix"` gives `kept_unfixed`
  4. For the same position, all 12 kinds produce pairwise-distinct `text`s and pairwise-distinct
     `headline`s.
  5. Check `details`:
     - `set(details) <= {"stage", "error", "request_id"}`
     - every value is a `str`
     - `request_id` is present if and only if it was passed
     - for slide kinds, no value equals `str(position)` or `str(slide_number(position))`
     - both `kept_*` kinds have `details["error"] == MODEL_TEMPORARILY_UNAVAILABLE`
  6. Check the `slides_phrase` examples above, and that `slides_phrase([])` raises `ValueError`.
  7. Purity: an `ast` walk of the module source shows imports only from `__future__`, `dataclasses`
     and `typing`.

  Sabotages to run:
  - Use `position` instead of `position + 1`: tests 1 and 6 go red.
  - Map `build_reviewer` to `build_failed`: test 3 goes red.
  - Append `f" ({stage}: {error})"` to the text: test 1 goes red.
  - Put "placeholder" in a headline: test 2 goes red.
  - Add `import json`: test 7 goes red.

  Confirm the tests are red (the module does not exist yet). Leave them uncommitted.
- [ ] **Step 2 (implementer).** Implement the module. Its docstring must state:
  - the purpose (#321)
  - "pure and stdlib-only so #316 can reuse it"
  - "1-based numbers in text, 0-based everywhere else"
  - "details never carry exception text or a `PersistedRuntimeError` subclass name"

  Do not edit tests.
- [ ] **Step 3.** `uv run pytest tests/unit/test_graph_user_notices.py -q` passes. Optionally run
  `uv run ruff check src/services/graph/user_notices.py`.

---

## Task 2: The notice row carries details; the poll projection forwards them

**Models:** test=opus impl=sonnet

**Files:**

- `src/services/graph/nodes.py`: `_surface_notice` only.
- `src/api/services/session_manager.py`: `msg_to_stream_event`.
- `src/api/routes/chat.py`: in the `poll_chat` docstring (`chat.py:848-851`), change "that converter
  returns a fixed six-key dict with nowhere to put …" to "that converter returns a fixed message
  projection that carries no slide payload, with nowhere to put …". Nothing else in the file.
- `tests/unit/test_graph_nodes.py`: a new class. Place it **after `TestDeckReviewerReview`** (which
  starts at `:3260`) and **immediately before** the `# The standing exhaustiveness check (DoD)`
  banner (`:3341-3343`).
- `tests/unit/test_poll_notice_details.py` (new).

Behaviour of `_surface_notice`:

```python
def _surface_notice(
    session_id: str, message: str, *, details: Optional[Dict[str, str]] = None
) -> None:
    # unchanged except:  metadata={"details": dict(details)} if details else None,
```

- Everything else stays the same: role `assistant`, type `info`, `request_id=get_chat_request_id()`,
  never raises, never gated.
- Add one paragraph to the docstring: `details` is the technical half of a plain-language notice
  (#321) and is shown behind a disclosure.

Behaviour of `SessionManager.msg_to_stream_event`: it gains one key and every other key is
unchanged.

```python
details = metadata.get("details")
...
# Only a failure notice's technical detail (#321) — never the row's whole metadata,
# which for a tool row carries its input. None on every other row, including every
# row persisted before notices had details.
"metadata": {"details": details} if isinstance(details, dict) and details else None,
```

Steps:

- [ ] **Step 1 (test author).**

  In `test_graph_nodes.py`, add `TestSurfaceNoticeCarriesDetails`. It uses `graph_env`.

  1. Set `set_chat_request_id("req-321")`. Then call:

     ```python
     nodes._surface_notice(
         graph_env.session_id,
         "x",
         details={"stage": "builder", "error": "RuntimeError", "request_id": "req-321"},
     )
     ```

     `get_session_manager().get_messages_for_request("req-321")` returns exactly one row, with
     `message_type == "info"`, `role == "assistant"` and `metadata == {"details": {...}}`.
  2. Without `details`, the row's `metadata is None`. This is today's shape.
  3. If `add_message` raises (monkeypatched), the call still returns `None`.

  In `tests/unit/test_poll_notice_details.py`, call `SessionManager().msg_to_stream_event(row)`
  directly on dicts shaped like `get_messages_for_request` output. The constructor has no side
  effects (`session_manager.py:694-700`).

  1. An info row with details gives `event["type"] == "assistant"` and
     `event["metadata"] == {"details": …}`.
  2. An old row (`metadata: None`) gives `event["metadata"] is None`.
  3. A `tool_call` row with `{"tool_name": "q", "tool_input": {"query": "secret"}}` gives
     `event["metadata"] is None`. `tool_name` and `tool_input` are still mapped.
  4. `{"details": "not-a-dict"}` and `{"details": {}}` both give `None`.

  Sabotages to run:
  - Drop the `metadata=` kwarg: unit test 1 goes red.
  - Forward `metadata` wholesale: projection test 3 goes red.

  Confirm the tests are red.
- [ ] **Step 2 (implementer).** Implement. Do not touch any other `nodes.py` code in this task.
- [ ] **Step 3.** Both of these pass:
  - `uv run pytest tests/unit/test_graph_nodes.py tests/unit/test_poll_notice_details.py -n 4 -q`
  - `uv run pytest tests/integration/test_api_routes.py -q`
    (`test_chat_poll_does_not_echo_user_message` stays green)

---

## Task 3: Route every failure site through the catalogue, log it, and fix the 0-based chat lines

**Models:** test=opus impl=sonnet

**Files:**

- `src/services/graph/nodes.py`
- `tests/unit/test_graph_nodes.py`, `tests/unit/test_slide_pipeline.py`,
  `tests/unit/test_graph_builder.py`, `tests/unit/test_deck_level_spec_change.py`
- `tests/integration/test_graph_orchestration.py`,
  `tests/integration/test_architect_reply_is_persisted.py`,
  `tests/integration/test_deck_spec_change_turn.py`

Behaviour (site numbers are from F1):

1. **Imports.**
   - Change the existing import to
     `from src.services.agent import SAFETY_RETRY_NOTICE, UnsafeContentError`.
   - Import `FailureNotice`, `slide_number`, `slides_phrase` and the five builders from
     `src.services.graph.user_notices`.
2. **New helper `_surface_failure_notice(session_id: str, notice: FailureNotice) -> None`**, placed
   after `_surface_notice`.
   - It writes the D6 `logger.warning(...)`, with the fields in the message and in `extra`.
   - Then it calls `_surface_notice(session_id, notice.text, details=notice.details)`.
   - It never raises.
   - Its docstring says it is the only sanctioned way to write a details-bearing notice.
3. **`_placehold_failed_position(position, *, session_id, node, reason, mutation, error: Optional[BaseException] = None)`.**
   - Build the notice once:
     `placeholder_notice(position, stage=node, error=reason, unsafe=isinstance(error, UnsafeContentError), request_id=get_chat_request_id())`.
   - The `ERROR` event is still emitted **before** the commit, with `error=notice.headline` (D2)
     and `metadata={"node": node, "position": position, "details": dict(notice.details)}`.
   - Commit and read-back logic are unchanged. `reason` is still passed verbatim to
     `commit_placeholder`.
   - On success, call `_surface_failure_notice(session_id, notice)` in place of the old f-string.
   - Update the docstring: the surfaces are now plain-language and carry details; mention
     numbering. Do not write the literal call text.
4. **Call sites.**
   - builder (`nodes.py:2318`), build_reviewer (`2490`) and fix_reviewer (`2926`) each add `error=exc,`
     on its own line **before** `mutation=`.
   - `placeholder_node` (`3277`) passes nothing.
   - There are still exactly four call expressions.
5. **`_transient_failure_notice(session_id: str, position: int, *, during: str) -> None`.**
   - It calls
     `_surface_failure_notice(session_id, unreviewed_slide_notice(position, during=during, request_id=get_chat_request_id()))`.
   - Callers: `nodes.py:3160` becomes `(session_id, position, during="review")`, and `3201` becomes
     `during="fix"`.
   - The caught exception is never passed in (D3).
6. **Foreman END (`nodes.py:2175-2193`).**
   - Keep the technical `message` string for `logger.error` and `error_state["message"]`.
   - Build `notice = unfinished_slides_notice(outstanding, request_id=get_chat_request_id())`.
   - Emit
     `_emit(StreamEventType.ERROR, error=notice.text, metadata={"node": "foreman", "positions": outstanding, "details": dict(notice.details)})`.
     It uses `text`, not `headline`, per D2.
   - Call `_surface_failure_notice(state["session_id"], notice)`.
   - Keep the existing comment, edited to name the new helper.
7. **`deck_reviewer_node`.** Declare `advisory_notice: Optional[FailureNotice] = None` before the
   derivation `try`.
   - **Write failure (`3442-3447`):** call
     `_surface_failure_notice(session_id, deck_not_updated_notice(review_skipped=False, error=type(exc).__name__, request_id=get_chat_request_id()))`.
   - **Derivation path:** `advisory_notice = deck_not_updated_notice(review_skipped=True, error=derivation_error, …)`
     and `advisory = advisory_notice.text`.
   - **Review failure, the non-`PersistedRuntimeError` branch after `3501`:**
     `advisory_notice = deck_review_failed_notice(error=type(exc).__name__, …)` and
     `advisory = advisory_notice.text`.
   - **Final surface.** When `advisory_notice` is set, call
     `_surface_failure_notice(session_id, advisory_notice)`; otherwise the unchanged
     `_surface_notice(session_id, advisory)`. Then emit the `ASSISTANT` event with
     `metadata={"node": "deck_reviewer", **({"details": dict(advisory_notice.details)} if advisory_notice else {})}`.
   - Keep the long comment block about `_surface_notice` and describe-only turns.
   - The success path through `_advisory_text` stays byte-for-byte unchanged (#316).
8. **Exactly the same number of `info` rows** as today on every path.
9. **The 0-based chat lines (F2, D2).**
   - **`nodes.py:1873`:** `f"Rebuilding {slides_phrase(rebuild)}."`. The full summary now reads
     "The deck's brief changed, so I re-checked all 3 slide(s) against it. Rebuilding slide 3."
     `metadata["rebuilding"]`, the `logger.info` call and `error_state` stay 0-based.
   - **`nodes.py:2462`:** `content=f"Slide {slide_number(position)} reviewed: {verdict}."`.
   - **`nodes.py:2938`:** `content=f"Slide {slide_number(position)} fix reviewed: {verdict}."`.
   - In both emits `metadata["position"]` stays 0-based.

Steps:

- [ ] **Step 1 (test author).** Update the F5 tests exactly as specified there, keeping every
  non-text invariant.

  Then add `TestFailureNoticesArePlainLanguage` to `test_graph_nodes.py`, placed after Task 2's
  class and before the exhaustiveness banner.

  - It drives the **real** node functions with `graph_env`.
  - Every case asserts four things about the persisted `info` row:
    - `content == <builder>(...).text`, compared exactly against the catalogue's own output
    - `assert_plain_language` and `assert_numbered` on the content
    - its `metadata.details`
    - `failure_notice_records(caplog)` has **exactly one** record, whose `notice_kind` is the
      expected kind
  - Use `caplog.set_level(logging.WARNING, logger="src.services.graph.nodes")`.
  - The helpers `_boom` (`:1986`), `_row_write_explodes` (`:2747`) and `_state` (`:2737-2745`) are
    **instance methods** of other classes. Copy their monkeypatch and state set-up into this class;
    do not call across classes.

  1. **Builder.** A skill raises `RuntimeError("provider said SECRET-123")` at position 2.
     - The text equals `placeholder_notice(2, stage="builder", error="RuntimeError").text`.
     - `details == {"stage": "builder", "error": "RuntimeError"}`.
     - `"SECRET-123"` is nowhere in `json.dumps(row)`.
  2. **Builder, real safety gate.** The skill returns `UNSAFE_HTML` (`test_graph_nodes.py:3747`) on
     both attempts. Expect the `blocked_unsafe` text and `details.error == "UnsafeContentError"`.
  3. **Build reviewer.** The skill raises a real pydantic `ValidationError` on both attempts, for
     example from `Finding.model_validate({})`. Expect the `check_failed` text and two reviewer
     calls, so the retry is preserved.
  4. **Fix reviewer delivery failure.** Expect the `save_failed` text and
     `details.stage == "fix_reviewer"`.
  5. **`placeholder_node` stall.** Expect the `stalled` text for each position and
     `details.error == _STALL_REASON`.
  6. **Foreman END** (the corner case at `test_graph_nodes.py:1600-1624`).
     - Content equals `unfinished_slides_notice([1]).text` and contains no `[`.
     - `error_state` is unchanged.
     - With an emitter installed, the `ERROR` event's `error` equals the persisted content, and its
       `metadata["positions"] == [1]`.
  7. **Deck reviewer.**
     - Each of the three failure paths equals its own builder's text: `review_skipped=False`,
       `review_skipped=True`, and `deck_review_failed`. If the flag were swapped, this goes red.
     - Each has `details == {"stage": "deck_reviewer", "error": "RuntimeError"}`.
     - The success path's row has `metadata is None` and produces no `graph_failure_notice`
       record.
  8. **Request id and log text.** Set `set_chat_request_id("req-321")`.
     - The builder failure row is returned by `get_messages_for_request("req-321")`, with
       `details.request_id == "req-321"`.
     - The single record's `getMessage()` contains `kind=build_failed`, `error=RuntimeError`,
       `positions=[2]` and `request_id=req-321`.
     - `record.request_id == "req-321"` and `record.graph_stage == "builder"`.
  9. **SSE events.** Install an emitter (pattern at `test_graph_nodes.py:944-952`).
     - The builder failure's `ERROR` event has `error ==` that notice's **`headline`**, which is
       not the row text and does not contain "placeholder".
     - Its `metadata["node"] == "builder"`, `metadata["position"] == 2` and
       `metadata["details"]["stage"] == "builder"`.
  10. **Progress lines are 1-based.** With an emitter installed:
      - A clean build review at position 2 emits an `ASSISTANT` event with content
        `"Slide 3 reviewed: clean."` and `metadata["position"] == 2`.
      - A fix review at position 0 emits content starting with `"Slide 1 fix reviewed: "`.
  11. **AST guard (bypass check).** Parse `inspect.getsource(nodes)`. Every `Call` to
      `_surface_notice` that has a `details` keyword sits inside the top-level `FunctionDef`
      `_surface_failure_notice`, and there is at least one such call.
  12. **Durable with `emitter=None`.** The existing tests already cover this. Keep them.

  In `test_slide_pipeline.py`, change the two transient tests as F5 specifies, and add the
  `failure_notice_records` count (exactly one, of the right kind).

  Sabotages to run, one per claim:
  - Restore the old f-string in `_placehold_failed_position`: tests 1-5 go red.
  - Emit `notice.text` on the pre-commit `ERROR` event: test 9 goes red.
  - Drop `error=exc` at the builder call site: test 2 goes red.
  - Remove the request id from the log message's args: test 8 goes red.
  - Call `_surface_notice(..., details=...)` directly at the foreman site: test 11 goes red, and so
    does test 6's record count.
  - Pass `type(error).__name__` into the transient notice: the `test_slide_pipeline` `json.dumps`
    checks go red.
  - Swap `review_skipped=` at the write site: test 7 goes red.
  - Revert `Rebuilding …`: the `test_deck_level_spec_change.py` assertion goes red.
  - Revert `slide_number(position)` in the review emit: test 10 goes red.

  Confirm the tests are red.
- [ ] **Step 2 (implementer).** Implement items 1-9. Then check the literal-text rule:
  `grep -n "_placehold_failed_position(" src/services/graph/nodes.py | grep -v "def "` must print
  exactly 4 lines, each with `mutation=` within the next 8 lines.
- [ ] **Step 3.** Run these:

  ```bash
  uv run pytest tests/unit/test_graph_nodes.py tests/unit/test_slide_pipeline.py tests/unit/test_graph_builder.py tests/unit/test_deck_level_spec_change.py tests/unit/test_graph_user_notices.py tests/unit/test_tour_staged_demo.py tests/unit/test_logging_extra_reserved_keys.py -n 4 -q
  uv run pytest tests/integration/test_architect_reply_is_persisted.py tests/integration/test_graph_orchestration.py tests/integration/test_deck_spec_change_turn.py -n 4 -q
  ```

  If Postgres is reachable, also run the following; otherwise it self-skips and CI runs it:

  ```bash
  uv run pytest tests/integration/test_mixed_release_collaboration_acceptance_postgres.py -q -k "placeholder or seams"
  ```

---

## Task 4: Frontend — carry `details` and render a collapsed disclosure

**Models:** test=opus impl=sonnet

**Files:**

- `frontend/src/types/message.ts`
- `frontend/src/utils/messageDetails.ts` (new)
- `frontend/src/components/ChatPanel/ChatPanel.tsx`
- `frontend/src/components/ChatPanel/Message.tsx`
- new tests:
  - `frontend/src/utils/messageDetails.test.ts`
  - `frontend/src/components/ChatPanel/Message.test.tsx`
  - `frontend/src/components/ChatPanel/ChatPanel.noticeDetails.test.tsx`
- `frontend/tests/e2e/chat-ui.spec.ts`

Behaviour:

- **`types/message.ts`.** Add `export type MessageDetails = Record<string, string>;` and an
  optional `details?: MessageDetails` on `Message`, documented as "technical detail behind a
  plain-language notice; never the headline".
- **`utils/messageDetails.ts`.** This must be a `.ts` file, because react-refresh's
  `only-export-components` rule forbids non-component exports from a `.tsx`.

  ```ts
  export function readMessageDetails(value: unknown): MessageDetails | undefined {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
    const entries = Object.entries(value as Record<string, unknown>).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1] !== '',
    );
    return entries.length > 0 ? Object.fromEntries(entries) : undefined;
  }
  ```

- **`ChatPanel.tsx`.** Exactly two one-property additions:
  - `loadSessionMessages`' map (`ChatPanel.tsx:103-111`) gets
    `details: readMessageDetails(msg.metadata?.details)`.
  - `case 'assistant'` (`ChatPanel.tsx:211-222`) gets
    `details: readMessageDetails(event.metadata?.details)`.

  No other change. `case 'error'` stays untouched.
- **`Message.tsx`.** In the regular branch, after the content `<div>`, render the disclosure **only
  when `message.role === 'assistant'`** and `message.details` has at least one entry. Use a
  module-level `const DETAIL_LABELS: Record<string, string> = { stage: 'Stage', error: 'Error', request_id: 'Request ID' };`.
  The element starts closed (no `open` attribute).

  ```tsx
  <details className="mt-2 text-xs text-muted-foreground" data-testid="message-details">
    <summary className="cursor-pointer select-none">Details</summary>
    <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 font-mono">
      {Object.entries(message.details).map(([key, value]) => (
        <React.Fragment key={key}>
          <dt>{DETAIL_LABELS[key] ?? key}</dt>
          <dd className="break-all">{value}</dd>
        </React.Fragment>
      ))}
    </dl>
  </details>
  ```

Steps:

- [ ] **Step 1 (test author).**
  - **`messageDetails.test.ts`:**
    - returns `undefined` for `null`, `undefined`, `'x'`, `[]`, `{}` and `{a: 1}`
    - keeps only non-empty string values
    - returns a copy: mutating the result leaves the input unchanged
  - **`Message.test.tsx`:**
    - An assistant message with details renders its content and one
      `[data-testid="message-details"]`. That element has `open === false` and the summary text
      "Details". Its `dd` values are inside it, and `toBeVisible()` is false until
      `details.open = true` is set.
    - A **user** message **with** details renders no disclosure.
    - An assistant message with no `details` renders none (the old-row case).
    - An assistant message with `details: {}` renders none either.
  - **`ChatPanel.noticeDetails.test.tsx`.** Follow the mock pattern of
    `ChatPanel.tourRefresh.test.tsx`, but use the **real** `MessageList`/`Message` and mock only
    `ChatInput`.
    - **Reload.** `api.getSession` resolves these messages:

      ```ts
      [
        { content: 'old notice', metadata: null },
        { content: 'tool row', metadata: { tool_name: 'q', tool_input: {} } },
        {
          content: 'new notice',
          metadata: { details: { stage: 'builder', error: 'RuntimeError', request_id: 'req-1' } },
        },
      ]
      ```

      All three render. There is exactly one `[data-testid="message-details"]`, and it is inside the
      'new notice' bubble.
    - **Stream.** Mock `api.sendChatMessage` to call its `onEvent` argument with
      `{type:'assistant', content:'streamed notice', metadata:{details:{stage:'foreman'}}}` and to
      return a no-op canceller. Trigger it through the forwarded ref's `sendMessage('hi')`. The
      streamed notice shows a disclosure.

  Sabotages to run:
  - Remove `details:` from `loadSessionMessages`: the reload test goes red.
  - Remove it from `case 'assistant'`: the stream test goes red.
  - Drop the role check: the user-message test goes red.
  - Render the disclosure unconditionally: the old-row tests go red.

  Confirm the tests are red.
- [ ] **Step 1b (test author, Playwright).** In `chat-ui.spec.ts`, add a
  `test.describe('Failure notice details', …)`.
  - The `beforeEach` calls `setupMocks(page)` and then registers a later, higher-priority
    `page.route`.
  - That route matches **only** `GET` requests whose path matches `/\/api\/sessions\/[^/?]+$/`
    (`api.getSession`, `api.ts:549-550`). Everything else, including `/slides`, `/lock`,
    `/agent-config` and non-GET requests, goes to `route.fallback()`.
  - It answers with the existing individual-session body (`my_permission: 'CAN_MANAGE'`) plus two
    messages: a notice with `metadata.details`, and an old notice with `metadata: null`.
  - ChatPanel calls `getSession` even for the new deck that `goToGenerator` creates
    (`ChatPanel.tsx:131-135`, `helpers/new-ui.ts:22-29`).

  After `goToGenerator(page)`:
  - both notice texts are visible
  - `page.getByTestId('message-details')` has count 1
  - the text `Request ID` is not visible until
    `page.locator('summary', { hasText: /^Details$/ })` is clicked, and is visible afterwards

  This is a **new test inside an existing spec**. `chat-ui` is already in the e2e matrix
  (`.github/workflows/test.yml:697`), so neither the matrix nor `test_e2e_matrix_covers_specs.py`
  changes. Do not create a new spec file.
- [ ] **Step 2 (implementer).** Implement. Do not edit the tests.
- [ ] **Step 3.** All three checks pass:
  1. The touched and new test files pass:

     ```bash
     cd frontend
     npm run test:unit -- src/utils/messageDetails.test.ts src/components/ChatPanel/Message.test.tsx src/components/ChatPanel/ChatPanel.noticeDetails.test.tsx src/components/ChatPanel/ChatPanel.tourRefresh.test.tsx src/components/ChatPanel/slideReadyEvent.test.ts
     ```

  2. Run `npx eslint` on every touched or new file. Each touched file's (rule, message) set is a
     subset of its baseline entries (see Global constraints). New files are clean.
  3. `npm run build` (`tsc -b` and `vite build`) passes.

  If the executor may run Playwright, also run
  `npx playwright test tests/e2e/chat-ui.spec.ts -g "Failure notice details"`. Otherwise CI's
  `chat-ui` leg runs it.

---

## Task 5: Docs

**Models:** test=sonnet impl=haiku

There is no automated test. The test-tier agent checks every sentence against the merged code from
Tasks 1-4.

**Files:** `docs/technical/real-time-streaming.md`, `docs/technical/frontend-overview.md`,
`docs/user-guide/01-generating-slides.md`.

**`real-time-streaming.md`:**

- **Database schema table.** The `metadata_json` row gains: "`details` (`stage`, `error`,
  `request_id`) on graph failure notices (#321)."
- **Poll response.** An event may carry `metadata: {"details": {...}}` for a failure notice, and
  `metadata: null` otherwise.
- **New short section, "Graph failure notices (agent mode)".** It covers:
  - the catalogue in `src/services/graph/user_notices.py`
  - notices are `info` rows: stamped with the request id and excluded from the architect's replay
  - numbers are 1-based in text and 0-based in metadata and logs
  - the three transports:
    - polling: an `assistant` event with `metadata.details`
    - SSE: the `ERROR` banner shows the headline, and its `metadata.details` is not rendered
    - reload: `messages[].metadata.details`
  - the `graph_failure_notice` log line: its fields are in the message, and `positions=` is 0-based
  - details never carry exception text or a `PersistedRuntimeError` subclass name; transient faults
    carry `model_temporarily_unavailable`
  - the save-point preview and the MCP transcript deliberately drop details
  - rows written before this change keep their old text

**`frontend-overview.md:324`.** The `Message.tsx` row reads: "… collapses HTML/tool outputs, and
shows a collapsed **Details** disclosure when an assistant message carries `details`."

**`01-generating-slides.md`:**

- Add an "Iterating" table row: `Regenerate one slide | "Regenerate slide 3"`.
- Add a short "If a slide can't be generated" subsection:
  - the chat names the slide and says what to do
  - the slide shows as a placeholder
  - ask "regenerate slide N"
  - if the slide's automatic fix was skipped, use **Apply** in its AI feedback
  - **Details** under the message holds technical information to share with support

Steps:

- [ ] **Step 1 (test tier).** List the claims to verify, with file:line evidence.
- [ ] **Step 2 (implementer).** Write the edits.
- [ ] **Step 3.** The test tier re-reads the edits against the code. Do not edit the README.

---

## Task 6: Verification (controller)

**Models:** test=opus impl=sonnet

- [ ] **Backend unit tests.** Run `uv run pytest tests/unit -n 4 -q`. The failing-cause set must
  still be empty. The only differences from the baseline are the tests this plan updates or adds.
- [ ] **Integration tests.** Compare causes with the pre-Task-1 baseline after running:

  ```bash
  uv run pytest tests/integration/test_architect_reply_is_persisted.py tests/integration/test_graph_orchestration.py tests/integration/test_deck_spec_change_turn.py tests/integration/test_api_routes.py tests/integration/test_streaming.py tests/integration/test_graph_mode_turn.py -n 4 -q
  ```

- [ ] **Frontend.**
  - Run `npm run test:unit`. The cause-set must be {C-FE1, C-FE2} and nothing else.
  - Run the per-file lint comparison from the Global constraints.
  - Run `npm run build`.
- [ ] **Sabotage.** Re-run one sabotage per task, picking a different one from the reviewer's.
  Paste the red and the green output.
- [ ] **`git diff --stat` must show none of:**
  - any file under `src/core/skills/`
  - `src/services/agent_definition_manifest_v1.py`
  - `src/services/agent_schema_registry.py`
  - a migration
  - a `.github/workflows/test.yml` change
- [ ] **Old strings are gone.** Run:

  ```bash
  grep -rn "could not be generated\|left as a placeholder\|shown as built\|could not be reconciled\|(deck_reviewer: \|Rebuilding {len" src/ tests/
  ```

  Expect no hits. These are the old strings. The new `kept_*` texts legitimately say "briefly
  unavailable", so that phrase is deliberately left out of the grep.

---

## Out of scope (sibling issues named) and follow-ups

- **#316, plain-language review findings.**
  - `_advisory_text`, the feedback drawer and finding messages stay untouched.
  - #316 can reuse `slide_number`/`slides_phrase` and the `metadata.details` plus `Message`
    disclosure for a finding's technical detail.
- **#319, the stage placeholder.**
  - This PR changes the **content** of the two SSE-only progress emits (`nodes.py:2462`, `2938`)
    to 1-based numbers. Their metadata is unchanged.
  - Supervisor: tell #319 in the PR body, in case its tracker hooks sit next to those lines.
  - A small merge in ChatPanel `case 'assistant'`, and possibly in `msg_to_stream_event`, is
    possible.
- **#323, clear chat.** `clear_context` deletes notice rows and their details with them. There is no
  interaction.
- **#318 and #313:** untouched.
  - **Recommend that #313 add an architect intent case:** "Regenerate slide 3" maps to
    `intent="edit"` with `target_positions=[2]`. This PR's notices tell users to type exactly that.
- **Follow-up issues to open** (supervisor or orchestrator):
  1. **One-click "Regenerate slide" on placeholder slides** (D4), after the #313 case exists.
  - **2a. Product decision.** On a transient or typed runtime fault, should the turn placehold or
    keep the existing row, instead of failing? This applies to:
    - a transient builder fault (`nodes.py:2316`)
    - a transient build review with no draft, which covers every **edit/regenerate** turn
      (`nodes.py:3049`, `3153`)
    - a transient deck review after every slide has landed (`nodes.py:3501`; no `COMPLETE`, no
      save point)
    - the architect's deck-level re-review (`nodes.py:708`)
    - architect and data_analyst calls

    Doing this changes the mixed-release "LITERAL 4 call sites" count
    (`test_mixed_release_collaboration_acceptance_postgres.py:1474-1487`).
  - **2b. Transport decision.** Show plain-language turn-failure text for transient faults instead
    of "Pinned graph configuration is unavailable".
    - This needs a backend classification plus a second typed terminal envelope, recognised at four
      sites under #271's fail-closed contract: `job_queue.py:46-51`, `chat.py:914-918`,
      `chat.py:626-627` and `chat.py:645-649`.
    - A frontend-only remap cannot tell a transient fault from a removed endpoint.
    - Pinned by:
      - `test_persisted_graph_runtime_failures_postgres.py:44`, `270`, `285`
      - `test_architect_reply_is_persisted.py:298-361`
      - `test_streaming.py:465-502`
      - `test_graph_mode_turn.py:649-668`
      - `test_lakebase_contract_failures_postgres.py:389-403`
      - `test_slide_pipeline.py:491-505`
  3. **SSE only.** ChatPanel `case 'error'` (`ChatPanel.tsx:271-276`) ends the loading state while
     the turn is still running, whenever a slide fails.
  4. **Placeholder slide body.** It still reads "Slide generation failed."
     (`slide_repository.py:366-368`). It could carry the same plain text.
  5. **Architect binding-degrade reply.** It exposes
     `slide_type=… template_section_index=…` (`template_sections.py:481-497`, `nodes.py:1713-1728`).
     Its slide number is already 1-based.

## Self-review (plan author)

1. **Coverage.**
   - Every one of the ten notice sites in F1 has a kind, a task and an exact-equality test.
   - The three 0-based chat lines in F2 have a task and a test each.
   - Both transports and reload are covered.
   - Numbering, headline vs text, details, log text, the bypass guard, the #271 name rule and old
     rows are each tested.
   - AC3 is deferred, with reasons.
2. **Symbols.** Every symbol either was grepped and exists at the cited line, or is introduced by a
   task: `user_notices.*`, `MODEL_TEMPORARILY_UNAVAILABLE`, `_surface_failure_notice`,
   `readMessageDetails`, `MessageDetails`, `failure_notice_records`, and the `details`/`error`
   kwargs.
3. **Invariants kept.**
   - The `info` type and its exclusion from the architect's replay.
   - Request-id stamping, with the end-to-end poll test strengthened.
   - Durability with `emitter=None`.
   - Ungated writes on describe-only turns.
   - The row-marker `reason`.
   - `mutation` stays required, with exactly four call sites.
   - `error_state`.
   - One notice per path.
   - 0-based metadata.
4. **No pinned artefact moves.** No prompt, schema or manifest change, no migration, and no change
   to the turn-failure contract.

## Revision log

All 20 plan-review findings were accepted (`~/tellr-loop/issues/issue-321/PLAN-REVIEW.md`).

**MAJOR**

- **F1.** The architect's `"Rebuilding {n}: {rebuild}."` is persisted and replayed. It is now in
  scope (Task 3 item 9). Its tests at `test_deck_spec_change_turn.py:485` and
  `test_deck_level_spec_change.py:955` are updated, and both files are added to the Task 3 and
  Task 6 runs.
- **Q1.** The two SSE progress emits are fixed with `slide_number`, and Task 3 test 10 pins them.
  They are removed from "Do not touch", and #319 is noted.
- **F2.** The log fields now go in the message via %-args (F4, D6). The extra key is `request_id`;
  the false collision rationale is dropped. The message labels the field `positions=` (0-based).
  Test 8 asserts `getMessage()`.
- **F3.** Transient notices always carry `MODEL_TEMPORARILY_UNAVAILABLE`, and
  `unreviewed_slide_notice` has no `error` parameter. D3 states the no-`PersistedRuntimeError`-name
  rule and why it holds at each site. The tests assert `"PinnedInvocation" not in json.dumps(row)`.
- **F4.** F1 #10 is corrected. The full turn-failure inventory is added to F1, with the tests that
  pin it. The old follow-up 2 is split into 2a (product) and 2b (transport). Neither is implemented.

**MINOR and NIT**

- **F5.** Site tests assert exact equality with the catalogue's output.
- **F6.** The `test_slide_pipeline.py` instructions are corrected: review at position 1, and fix at
  position 0 with a new assertion.
- **F7.** `FailureNotice.headline` is added. The pre-commit placeholder `ERROR` event uses it. The
  foreman `ERROR` event uses `text`, with the reason given in D2.
- **F8, F9.** `blocked_unsafe` and `kept_unfixed` are reworded.
- **F10.** Every site test asserts one record of the right kind, and an AST bypass guard is added.
- **F11.** The disclosure is gated on `role === 'assistant'`, and a test covers a user message that
  has details.
- **F12.** Frontend lint and vitest are compared as per-file cause-sets (C-FE1, C-FE2).
- **F13.** The helpers are copied, not called across classes. Task 2's test class has a concrete
  anchor.
- **F14.** The details-key and position assertions are made precise.
- **F16.** Directories are given for the logging citations.
- **F17.** The shared assertions move to `tests/fixtures/notice_assertions.py`.
- **F18.** The Playwright test uses a test-id or summary locator, and its route matches GET
  `/api/sessions/<id>` only.
- **F19.** The docs mention that the save-point preview and the MCP transcript drop details, and
  that old rows keep their old text.
- **F20.** The `chat.py` docstring rewording is specified.

**Deviations from the reviewer's suggested wording**

- **F8.** The parentheses in the reviewer's `blocked_unsafe` text are replaced with a comma
  ("…without it, for example without external images, videos or links."). The plain-language check
  bans `(` because it is how a `(stage: Error)` suffix would leak.
- **F3.** Rather than passing a code into `unreviewed_slide_notice`, the parameter is removed, so the
  leak is impossible by construction.
- **F2.** The `extra` key for positions is `positions`, to match the message label.
