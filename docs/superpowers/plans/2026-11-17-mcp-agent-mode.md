# Tellr MCP on Agent mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, with `executing-plans-tellr` loaded alongside (repo `CLAUDE.md`). Steps use checkbox (`- [ ]`) syntax for tracking.

Execution: chained

(Task 7, the devloop verification, needs a deploy, so it is outside the chain: the
top-level session runs it after the handover.)

**Goal:** Run the Tellr MCP tools (`create_deck`, `edit_deck`, `get_deck_status`) on the
Agent engine instead of the Legacy monolith, as specified in the design.

**Architecture:** The async chat route's Agent-turn Enter (lock binding, generation
snapshot, deck-mode lock, engine resolution, rollback) is extracted into one function,
`enter_chat_turn`, in `src/api/routes/chat.py`. The route and the MCP both call it. The
MCP creates `deck_mode="agent"` sessions seeded with the app's tool defaults, refuses
Legacy decks and non-owners on `edit_deck`, and reads the architect's intent (now on the
graph's COMPLETE metadata) to report `reply` and `deck_changed`.

**Tech Stack:** Python 3, FastAPI, FastMCP (`mcp` package), LangGraph, SQLAlchemy,
pytest (+ `pytest.mark.postgres` against local Postgres 15).

**Spec:** `docs/superpowers/specs/2026-11-17-mcp-agent-mode-design.md` (committed
7bb2eb40). Executors read both.

## Global Constraints

- Agent mode only. No change to any Legacy (monolith) code path's behaviour.
- `enter_chat_turn` lives in `src/api/routes/chat.py`, **not** a new module. Tests patch
  `src.api.routes.chat.get_session_manager` (19×), `.enqueue_job` (9× plus
  `monkeypatch.setattr(chat_routes, "enqueue_job", …)`), `.get_current_user` and
  `.resolve_engine_mode_or_unavailable`. Those patches must keep intercepting, so the
  function resolves those names from the `chat` module namespace at call time.
- Every existing test under `tests/unit` and `tests/integration` that touches
  `submit_chat_async` passes **unchanged**. The only existing tests a task may edit are
  the ones it names.
- The HTTP answers of `POST /api/chat/async` (status codes and `detail` bodies) are
  unchanged.
- FastMCP ignores undeclared tool arguments (`ArgModelBase`, extra keys ignored;
  verified 2026-11-17). Removed parameters therefore need no shim and must not get one.
- MCP error copy, exact (used by Tasks 3–5):
  - `MCP_LEGACY_DECK_ERROR = "This deck was made in Legacy mode and can't be edited over MCP. Open it in Tellr to keep working on it: {deck_url}"`
  - `MCP_OWNER_ONLY_ERROR = "Only the deck's owner can edit it over MCP. Open it in Tellr to keep working on it: {deck_url}"`
  - `MCP_SESSION_BUSY_ERROR = "This deck is busy with another request. Try again when it finishes."`
  - `MCP_DECK_LOCKED_ERROR = "This deck is locked by {name}."`
  - `MCP_NO_GRAPH_RELEASE_ERROR = "Tellr can't generate decks right now: no active Graph Release. An admin needs to publish one."`
  - `MCP_UNAVAILABLE_ERROR = "Tellr is temporarily unavailable. Please retry."`
  - `MCP_ENGINE_RACE_ERROR = ENGINE_RACE_DETAIL` (reuse the route's constant)
  - `MCP_STOPPED_ERROR = "This generation was stopped in Tellr. The deck is unchanged."`
  - Generation refusals reuse the route's `_GENERATION_REFUSED_DETAILS[reason]`.
- `deck_url` in error copy is `f"{_public_app_url()}/sessions/{session_id}/edit"` (the
  same URL `_render_deck_response` returns; relative when the base is empty).
- Run Python only through `uv run` in this worktree's `.venv`. Never `pip install`.
- Postgres-marked tests need the local cluster:
  `LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@15/bin/pg_ctl -D /opt/homebrew/var/postgresql@15 -l /tmp/pg.log start`.
  Stop it when the run is done.
- Commits end with `Co-authored-by: Isaac <no-reply@databricks.com>`.

## Review Focus

1. **A caller still sending `num_slides`, `deck_prompt_id` or `slide_indices`.** The call
   succeeds and the value has no effect. Pinned in Task 3 (`create_deck`) and Task 4
   (`edit_deck`) through the FastMCP tool-call path, not the `_impl` function.
2. **An MCP poll of a request that a stop in the Tellr app ended (`cancelled`).** The
   poll terminates with `failed` and the stopped copy, never "Unknown job status".
   Pinned in Task 5.
3. **`edit_deck` from the owner while someone else's live generation holds the deck.**
   It is refused with "locked by `<name>`" and nothing is written. Pinned in Task 4.
4. **A `create_deck` whose Enter fails after the session was created** (no graph
   release at Enter, enqueue failure). It returns a tool error, and no session lock or
   live chat request is left behind. Pinned in Task 6 (Postgres).
5. **`get_deck_status` on a request made before this change** (a Legacy MCP turn's
   result with no `engine_mode`). It still reports exactly what it reports today, plus
   `reply` and `deck_changed = not clarification_needed`. Pinned in Task 5.

---

### Task 1: Extract the Agent-turn Enter into `enter_chat_turn`

Models: test=opus impl=opus

**Files:**
- Modify: `src/api/routes/chat.py` (`submit_chat_async`, ~lines 776–1053; exception
  classes ~87–95)
- Test: `tests/unit/test_enter_chat_turn.py` (create)

**Interfaces:**
- Produces (all in `src/api/routes/chat.py`):
  - `@dataclass(frozen=True) class EnteredTurn: request_id: str; engine_mode: str` —
    `engine_mode` is `"graph"` or `"monolith"`.
  - `class SessionBusyError(Exception)`: the session lock is held; nothing was written.
  - `class EngineRaceError(Exception)`: renamed from `_EngineRaceError` (no external
    references exist).
  - `class EngineModeUnresolvedError(Exception)`: renamed from
    `_EngineModeUnresolvedError`; `__cause__` is the resolver's error.
  - `async def enter_chat_turn(*, session_id: str, message: str, requested_deck_mode: Optional[str], slide_context: Optional[dict] = None, image_ids: Optional[list[str]] = None, stage_slide: Optional[dict] = None, extra_payload: Optional[dict] = None) -> EnteredTurn`
- Behaviour contract of `enter_chat_turn`: it runs the steps `submit_chat_async` runs
  today, in today's order, from `acquire_session_lock` through `enqueue_job`. It
  resolves `get_session_manager`, `get_current_user`, `enqueue_job` and
  `resolve_engine_mode_or_unavailable` from the module namespace. The job payload is
  `{**(extra_payload or {}), <today's core keys>}`, so core keys win over
  `extra_payload`. It does every cleanup today's `except` clauses do (lock release
  respecting `keep_lock`, `_mark_chat_request_error`, rollback or discard), then
  re-raises:
  `SessionBusyError` | `GenerationRefusedError` | `EngineRaceError` |
  `SessionNotFoundError` | `EngineModeUnresolvedError` | `DeckModeLockedError` |
  `ActiveGraphReleaseUnavailableError` | the original exception for anything else.
- `submit_chat_async` keeps the permission check, the injection check and
  `_maybe_create_session` before the call. It maps each exception to exactly today's
  `HTTPException` (`SessionBusyError` → 409 `"Session is already processing a request"`).
  It builds the same `{"request_id", "status": "pending", "session_id"?}` result.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_enter_chat_turn.py`, with a
  `MagicMock` session manager patched at `src.api.routes.chat.get_session_manager`,
  `AsyncMock` at `src.api.routes.chat.enqueue_job`, and
  `src.api.routes.chat.resolve_engine_mode_or_unavailable` patched:
  - `test_busy_session_raises_and_writes_nothing`: `acquire_session_lock → False` raises
    `SessionBusyError`. `create_chat_request`, `add_user_message` and `enqueue_job` are
    never called.
  - `test_agent_turn_snapshots_before_the_user_message_and_enqueues_graph`:
    `get_deck_mode → "agent"`, resolver `→ "graph"`. Use a shared `Mock()` parent to
    record call order; assert `begin_generation` precedes `add_user_message`, that
    `add_user_message` got `requested_deck_mode="agent"`, that the payload has
    `engine_mode == "graph"`, and that the return value equals
    `EnteredTurn(request_id=<create_chat_request's value>, engine_mode="graph")`.
  - `test_extra_payload_reaches_the_job_but_never_overrides_core_keys`:
    `extra_payload={"correlation_id": "c-1", "message": "other", "engine_mode": "monolith"}`
    leaves the payload with `correlation_id == "c-1"`, `message ==` the real message, and
    `engine_mode == "graph"`.
  - `test_enqueue_failure_on_a_graph_turn_rolls_back_releases_and_reraises`:
    `enqueue_job` raises `RuntimeError("boom")`. `roll_back_generation` (patched at
    `src.api.routes.chat.roll_back_generation`, returning `RollbackResult.RESTORED`) is
    called with that request id, `release_session_lock` is called, and the same
    `RuntimeError` propagates.
  - `test_deck_mode_locked_marks_the_request_and_releases_the_lock`:
    `add_user_message` raises `DeckModeLockedError("legacy")`. That error propagates,
    `update_chat_request_status` was called with `(request_id, "error", "deck_mode_locked")`,
    and the lock was released.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/unit/test_enter_chat_turn.py -v`
Expected: FAIL with `ImportError: cannot import name 'enter_chat_turn'`

- [ ] **Step 3: Implement `enter_chat_turn` and slim `submit_chat_async`** per the
  Interfaces block. Move code; don't rewrite it. The cleanup branches keep their
  comments.

- [ ] **Step 4: Run the new tests and the unchanged route suites**

Run: `uv run pytest tests/unit/test_enter_chat_turn.py -v` → PASS.
Run: `uv run pytest tests/unit -q -p no:randomly` → same pass/fail cause-set as on
`main` (record main's baseline first, per `executing-plans-tellr` §3).
Run (Postgres up): `uv run pytest tests/integration/test_generation_stop_routes.py tests/integration/test_generation_lock_postgres.py tests/integration/test_generation_rollback_postgres.py tests/integration/test_lakebase_contract_failures_postgres.py tests/integration/test_api_routes.py -q` → PASS, with none of these files modified.

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/chat.py tests/unit/test_enter_chat_turn.py
git commit -m "refactor(chat): extract the Agent-turn Enter into enter_chat_turn"
```

---

### Task 2: The graph's COMPLETE event carries the architect's intent

Models: test=opus impl=sonnet

**Files:**
- Modify: `src/api/services/chat_service.py` (`_send_message_streaming_graph`: `run_graph`
  ~1988, the COMPLETE yield ~2211)
- Modify: `tests/integration/test_graph_mode_turn.py:1154`
  (`test_complete_declares_which_engine_ran`; its exact-equality assert gains the new key)
- Test: `tests/unit/test_graph_complete_intent.py` (create)

**Interfaces:**
- Produces: a graph turn's COMPLETE `metadata` is
  `{"engine_mode": "graph", "architect_intent": <str | None>}`, where the value is
  `invoke_graph(...)`'s returned state's `"architect_intent"` (`None` if the state lacks
  it). `job_queue.process_chat_request` already copies `event.metadata` into the chat
  request's `result["metadata"]`, so Task 5 reads `result["metadata"]["architect_intent"]`.

- [ ] **Step 1: Write the failing test** `test_complete_metadata_carries_the_final_architect_intent`,
  parametrized over `"build"`, `"discuss"` and `"confirm_design_contract"`. Patch
  `src.services.graph.builder.invoke_graph` with a fake that returns
  `{"architect_intent": intent}`. Use the session-manager and seal patches that
  `tests/unit/test_generation_runner_release.py` uses to drive
  `_send_message_streaming_graph`. Assert the last COMPLETE event's
  `metadata == {"engine_mode": "graph", "architect_intent": intent}`. Add a case where
  the fake returns `{}`, asserting `architect_intent is None`.

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/test_graph_complete_intent.py -v`
Expected: FAIL (`metadata == {"engine_mode": "graph"}`)

- [ ] **Step 3: Implement.** In `run_graph`, store `invoke_graph`'s return value in a
  container next to `error_container`. Read `architect_intent` from it at the COMPLETE
  yield. Update the integration assert at `test_graph_mode_turn.py:1154` to
  `{"engine_mode": "graph", "architect_intent": "build"}`.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_graph_complete_intent.py tests/unit/test_job_queue_rollback.py tests/unit/test_generation_runner_release.py -v` → PASS.
Run (Postgres up): `uv run pytest tests/integration/test_graph_mode_turn.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/services/chat_service.py tests/unit/test_graph_complete_intent.py tests/integration/test_graph_mode_turn.py
git commit -m "feat(graph): COMPLETE metadata carries the turn's architect intent"
```

---

### Task 3: `create_deck` creates and enters an Agent deck

Models: test=opus impl=sonnet

**Files:**
- Modify: `src/api/routes/chat.py` (add `apply_new_deck_tool_defaults`;
  `_seeded_for_new_session` calls it)
- Modify: `src/api/mcp_server.py` (`create_deck`, `_create_deck_impl`; delete
  `enqueue_create_job`; add `_enter_turn_or_tool_error`, `_deck_edit_url`, and the error
  constants from Global Constraints)
- Modify: `src/api/services/job_queue.py` (the comments at ~208–245 and ~398–400 that
  say MCP jobs run on the monolith)
- Modify: `docs/technical/generation-atomicity.md` (the "MCP jobs | No" row at line 15;
  the "monolith (Legacy decks, MCP)" section ~364)
- Modify: `docs/technical/mcp-server.md` (the `create_deck` section: parameters, Agent
  mode, tools)
- Modify: `tests/unit/test_mcp_server.py`. Every `create_deck` test that patches
  `src.api.mcp_server.enqueue_create_job` patches `src.api.mcp_server.enter_chat_turn`
  instead. `test_create_deck_creates_session_and_submits_job` drops its `num_slides` and
  `deck_prompt_id` arguments and asserts. Delete
  `test_create_deck_rejects_num_slides_out_of_range`,
  `test_mcp_create_deck_is_legacy_unpinned_and_persists_the_prompt_verbatim`,
  `_drive_enqueue_create_job` and `test_every_enqueued_prompt_is_persisted_verbatim`
  (their subject is deleted). The style, template and validation tests keep their
  assertions.
- Test: new tests in `tests/unit/test_mcp_server.py`, plus
  `tests/integration/test_mcp_endpoint.py` for the tool-call path

**Interfaces:**
- Consumes: `enter_chat_turn`, `EnteredTurn`, `SessionBusyError`, `EngineRaceError`,
  `EngineModeUnresolvedError` (Task 1), imported into `mcp_server` by name
  (`from src.api.routes.chat import enter_chat_turn, …`). The same goes for
  `resolve_display_name` (`src.services.identity_provider`) and, in Task 4,
  `resolve_engine_mode_or_unavailable` (`src.api.services.chat_service`). Tests patch
  all three at `src.api.mcp_server.<name>`.
- Produces:
  - `src/api/routes/chat.py`: `def apply_new_deck_tool_defaults(agent_config_data: dict, *, client_set_fields: frozenset[str] = frozenset()) -> None`.
    It calls `_apply_genie_one_default` today, and it is the one place a future
    new-deck tool default goes.
  - `src/api/mcp_server.py`: `def _deck_edit_url(session_id: str) -> str`.
  - `src/api/mcp_server.py`: `async def _enter_turn_or_tool_error(*, session_id: str, message: str, correlation_id: Optional[str]) -> str`.
    It calls `enter_chat_turn(session_id=…, message=…, requested_deck_mode="agent", extra_payload={"correlation_id": correlation_id})`
    and returns the request id. It maps `SessionBusyError` → `MCP_SESSION_BUSY_ERROR`;
    `GenerationRefusedError` → `MCP_DECK_LOCKED_ERROR` (name via `resolve_display_name`)
    for `GENERATION_IN_FLIGHT`, else `_GENERATION_REFUSED_DETAILS[reason]`;
    `EngineRaceError` → `MCP_ENGINE_RACE_ERROR`; `EngineModeUnresolvedError` →
    `MCP_UNAVAILABLE_ERROR`; `ActiveGraphReleaseUnavailableError` →
    `MCP_NO_GRAPH_RELEASE_ERROR`; `DeckModeLockedError` → `MCP_LEGACY_DECK_ERROR` when
    `e.deck_mode == "legacy"`. Everything else propagates to the tool's existing
    `except Exception` → `"Internal error: …"`. Task 4 reuses it.
  - `create_deck(ctx, prompt, slide_style_id=None, design_system_id=None, template_name=None, correlation_id=None) -> dict`.
    The response shape is unchanged.

- [ ] **Step 1: Write the failing tests** (`tests/unit/test_mcp_server.py`, with
  `mcp_auth_scope`, `get_session_manager` and `enter_chat_turn` patched as the existing
  tests patch them):
  - `test_create_deck_creates_an_agent_deck_and_enters_it`: `create_session` is called
    with `deck_mode="agent"` and `created_by="alice@example.com"`. `enter_chat_turn` is
    awaited once with `session_id="sess-123"`, `message=` the prompt verbatim,
    `requested_deck_mode="agent"` and `extra_payload={"correlation_id": "vibe-xyz"}`. The
    result is `{"session_id": "sess-123", "request_id": "req-777", "status": "pending"}`.
  - `test_create_deck_seeds_genie_one_when_the_admin_default_is_on`: patch
    `src.api.routes.chat.get_genie_one_default → True`. The stored
    `agent_config["tools"] == [GenieOneTool().model_dump()]`.
  - `test_create_deck_seeds_no_tools_for_a_token_less_caller`: same patch, with an
    identity of `token=None, source="x-forwarded-identity"`. The stored
    `agent_config["tools"] == []`.
  - `test_create_deck_no_longer_stores_num_slides_or_deck_prompt_id`: the stored
    `agent_config` has neither key, and `inspect.signature(mcp_server._create_deck_impl)`
    has neither parameter.
  - `test_create_deck_maps_a_missing_graph_release_to_a_tool_error`: `create_session`
    raises `ActiveGraphReleaseUnavailableError`. `MCPToolError` is raised with
    `MCP_NO_GRAPH_RELEASE_ERROR`, and `enter_chat_turn` is never awaited.
  - `test_enter_turn_maps_every_refusal_to_its_copy`: parametrized over the mapping in
    the Interfaces block. `_enter_turn_or_tool_error` raises `MCPToolError` whose message
    equals the exact constant (for `GENERATION_IN_FLIGHT`, patch `resolve_display_name`
    → `"Bob"` and expect `"This deck is locked by Bob."`).
  - In `tests/integration/test_mcp_endpoint.py`, `test_create_deck_ignores_a_removed_num_slides_argument`:
    a JSON-RPC `tools/call` for `create_deck` with `{"prompt": "...", "num_slides": 4, "deck_prompt_id": 2}`
    succeeds (`isError` false, `status: "pending"`). Follow that file's existing harness;
    patch `enter_chat_turn` and the session manager.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/unit/test_mcp_server.py -k "agent_deck or genie_one or token_less or num_slides_or_deck_prompt or graph_release or every_refusal" tests/integration/test_mcp_endpoint.py -k removed_num_slides -v`
Expected: FAIL. The new names don't exist, and `deck_mode="legacy"` is still passed.

- [ ] **Step 3: Implement** per the Interfaces block:
  - The style-source block in `_create_deck_impl` stays as it is.
  - Tools: `agent_config = {"tools": []}` plus `apply_new_deck_tool_defaults(agent_config, client_set_fields=frozenset({"tools"}) if identity.token is None else frozenset())`.
  - Then `create_session(created_by=identity.user_name, agent_config=agent_config, deck_mode="agent")`.
  - Then `_enter_turn_or_tool_error(...)`.
  - Delete `enqueue_create_job` and the "MCP stays on the legacy monolith" comment
    block.
  - Rewrite the tool description: no "v1 runs prompt-only…" claim. Say the deck uses the
    user's default tools, and that any slide count belongs in the prompt.
  - Update the `job_queue.py` comments and the two docs to say MCP turns run on the
    graph through `enter_chat_turn`.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_mcp_server.py tests/unit/test_mcp_auth.py tests/integration/test_mcp_endpoint.py tests/unit/test_chat_session_creation.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/chat.py src/api/mcp_server.py src/api/services/job_queue.py docs/technical/generation-atomicity.md docs/technical/mcp-server.md tests/unit/test_mcp_server.py tests/integration/test_mcp_endpoint.py
git commit -m "feat(mcp): create_deck builds an Agent deck with the app's tool defaults"
```

---

### Task 4: `edit_deck` is owner-only and Agent-only

Models: test=opus impl=sonnet

**Files:**
- Modify: `src/api/mcp_server.py` (`edit_deck`, `_edit_deck_impl`; delete
  `_check_contiguous`; add `_require_agent_deck_owner`)
- Modify: `docs/technical/mcp-server.md` (the `edit_deck` section)
- Modify: `tests/unit/test_mcp_server.py`. Delete
  `test_edit_deck_submits_with_slide_context`,
  `test_edit_deck_submits_without_slide_context_when_indices_omitted` and
  `test_edit_deck_rejects_non_contiguous_indices` (their subject is deleted). Keep
  `test_edit_deck_denies_without_edit_permission`,
  `test_edit_deck_blocks_injection` and `test_edit_deck_length_guard_when_enabled`, and
  update their patches from `enqueue_create_job` to `enter_chat_turn`.
- Test: new tests in `tests/unit/test_mcp_server.py` and
  `tests/integration/test_mcp_endpoint.py`

**Interfaces:**
- Consumes: `_enter_turn_or_tool_error`, `_deck_edit_url`, error constants (Task 3).
- Produces:
  - `def _require_agent_deck_owner(session_id: str, user_name: str) -> None` in
    `mcp_server.py`. It runs these checks in order, each raising `MCPToolError`:
    1. `get_session(session_id)`: `created_by != user_name` or
       `is_contributor_session` → `MCP_OWNER_ONLY_ERROR`.
    2. `resolve_engine_mode_or_unavailable(session_id) == "monolith"` →
       `MCP_LEGACY_DECK_ERROR`. `PersistedConfigurationUnavailableError` →
       `MCP_UNAVAILABLE_ERROR`.
    3. `live_generation_holder(session_id, live_only=True)` is set and `!= user_name` →
       `MCP_DECK_LOCKED_ERROR` with `resolve_display_name(holder)`.
  - `edit_deck(ctx, session_id, instruction, correlation_id=None) -> dict`. The response
    shape is unchanged.
- Order in `_edit_deck_impl`: validation (empty, length, injection) →
  `can_edit_deck` → `_require_agent_deck_owner` → `_enter_turn_or_tool_error(message=instruction verbatim)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_edit_deck_enters_an_agent_turn_with_the_instruction_verbatim`: the owner's
    Agent deck. `enter_chat_turn` is awaited with `message="On slides 1 and 4, shorten the titles"`
    and `requested_deck_mode="agent"`.
  - `test_edit_deck_refuses_a_legacy_deck_and_writes_nothing`: resolver →
    `"monolith"`. `MCPToolError` is raised and its message equals
    `MCP_LEGACY_DECK_ERROR.format(deck_url="/sessions/sess-1/edit")` (empty public URL).
    `enter_chat_turn` and every session-manager write method are never called.
  - `test_edit_deck_refuses_a_collaborator`: parametrized over (a) `created_by="bob@example.com"`
    and (b) `created_by=` the caller with `is_contributor_session=True`. Both raise
    `MCP_OWNER_ONLY_ERROR` with the link, and nothing is entered.
  - `test_edit_deck_refuses_the_owner_while_someone_else_generates`: `live_generation_holder → "bob@example.com"`,
    `resolve_display_name → "Bob"`. The error is `"This deck is locked by Bob."`, and
    nothing is entered.
  - `test_edit_deck_proceeds_while_the_owner_holds_the_generation`:
    `live_generation_holder →` the caller. It enters (the session lock then decides).
  - In `tests/integration/test_mcp_endpoint.py`, `test_edit_deck_ignores_a_removed_slide_indices_argument`:
    a `tools/call` for `edit_deck` with `slide_indices: [0, 2]` succeeds, and the patched
    `enter_chat_turn` got the instruction unchanged.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/unit/test_mcp_server.py -k "edit_deck" tests/integration/test_mcp_endpoint.py -k slide_indices -v`
Expected: FAIL (no `_require_agent_deck_owner`; `slide_indices` still declared).

- [ ] **Step 3: Implement** per the Interfaces block. Rewrite the tool description: a
  change **or** a question for the architect; name slides by number in the instruction;
  show the user `reply` from `get_deck_status`; the deck owner only; Agent decks only.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_mcp_server.py tests/integration/test_mcp_endpoint.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/mcp_server.py docs/technical/mcp-server.md tests/unit/test_mcp_server.py tests/integration/test_mcp_endpoint.py
git commit -m "feat(mcp): edit_deck is owner-only on Agent decks; slide_indices removed"
```

---

### Task 5: `get_deck_status` reports `reply`, `deck_changed` and stopped turns

Models: test=opus impl=sonnet

**Files:**
- Modify: `src/api/mcp_server.py` (`get_deck_status` description,
  `_get_deck_status_impl`)
- Modify: `docs/technical/mcp-server.md` (the status payload) and
  `docs/technical/mcp-integration-guide.md` (the tool table at ~513–515: `create_deck`
  inputs `prompt, design_system_id?, template_name?, slide_style_id?`; `edit_deck` inputs
  `session_id, instruction`)
- Test: new tests in `tests/unit/test_mcp_server.py` (reuse the `_ready_status` helper
  at ~1152)

**Interfaces:**
- Consumes: `result["metadata"]["engine_mode"]` and `["architect_intent"]` (Task 2).
- Produces: in the `ready` payload, two new top-level keys:
  - `reply: Optional[str]`: the `content` of the last message in this turn's `messages`
    with `role == "assistant"` and `message_type == "llm_response"`, else `None`.
  - `deck_changed: bool`: on a graph result (`metadata.engine_mode == "graph"`),
    `architect_intent in {"build", "edit"}`. On any other result, `not clarification_needed`.
  - On a graph result, `metadata.clarification_needed = not deck_changed` and
    `metadata.clarification = reply if not deck_changed else None`. A non-graph result
    computes both exactly as today.
  - A DB status of `"cancelled"` returns `{"session_id", "request_id", "status": "failed", "error": MCP_STOPPED_ERROR}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_status_of_an_agent_build_reports_the_reply_and_a_changed_deck`: result metadata
    `{"engine_mode": "graph", "architect_intent": "build"}`. The turn's messages are a
    user row, an `info` row and an `llm_response` row `"Here's a starter…"`. Expect
    `reply == "Here's a starter…"`, `deck_changed is True`, and
    `metadata.clarification_needed is False`.
  - `test_status_of_an_agent_discussion_reports_an_unchanged_deck`: parametrized over
    `"discuss"` and `"confirm_design_contract"`. Expect `deck_changed is False`,
    `clarification_needed is True`, and `clarification == reply`.
  - `test_reply_is_the_last_architect_message_of_the_turn`: an `ask_data` turn with two
    `llm_response` rows ("Let me fetch…", then "Built it…"). `reply == "Built it…"`.
  - `test_a_stopped_turn_reports_failed_with_the_stopped_copy`: in-memory job entry
    absent, DB status `"cancelled"`. The payload is exactly
    `{"session_id": "s", "request_id": "r", "status": "failed", "error": MCP_STOPPED_ERROR}`.
  - `test_a_pre_existing_legacy_result_reports_as_before_plus_the_new_keys`: reuse
    `_clarification_status` and `_applied_edit_status` (no `engine_mode` in metadata).
    Their existing fields are unchanged. `deck_changed` is `False` and `True`
    respectively, and `reply` is the last `llm_response` row or `None`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/unit/test_mcp_server.py -k "status" -v`
Expected: FAIL (`KeyError: 'reply'`; `cancelled` reports "Unknown job status").

- [ ] **Step 3: Implement** per the Interfaces block. Rewrite the tool description: a
  `ready` turn may leave the deck unchanged; show `reply` to the user; `deck_changed`
  says whether anything changed.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_mcp_server.py -v` → PASS (all of it, including the
WG2-01 clarification tests at ~1270–1340, unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/api/mcp_server.py docs/technical/mcp-server.md docs/technical/mcp-integration-guide.md tests/unit/test_mcp_server.py
git commit -m "feat(mcp): get_deck_status reports reply, deck_changed and stopped turns"
```

---

### Task 6: MCP turns through the real Enter, on Postgres

Models: test=opus impl=sonnet

**Files:**
- Test: `tests/integration/test_mcp_agent_mode_postgres.py` (create;
  `pytestmark = pytest.mark.postgres`)
- Modify: only if a test exposes a defect: the file the defect is in, fixed within the
  owning task's Interfaces

**Interfaces:**
- Consumes: `tests.unit.test_generation_rollback.build_env` / `RollbackEnv` / `OWNER`,
  the `postgres_engine` fixture (`tests/integration/conftest.py:290`), and
  `_create_deck_impl` / `_edit_deck_impl` with only `mcp_auth_scope` patched (yielding an
  `MCPIdentity` for `OWNER`), `enqueue_job` patched at `src.api.routes.chat.enqueue_job`
  (recording), and the real session manager, snapshot and rollback.
- Produces: no code. The tests are the deliverable.

- [ ] **Step 1: Write the tests:**
  - `test_create_deck_leaves_an_agent_deck_with_a_live_snapshotted_request`: after
    `_create_deck_impl`, the session row has `deck_mode == "agent"` and a non-null
    `graph_release_id`. The chat request is `pending` and has a generation snapshot
    (`has_generation_snapshot(request_id)`). The session lock is bound to that request.
    The recorded payload has `engine_mode == "graph"` and the user message is the prompt
    verbatim.
  - `test_create_deck_enqueue_failure_leaves_no_lock_and_no_live_request`: recording
    `enqueue_job` raises. `MCPToolError` is raised; the request status is `error`; no
    snapshot survives; `acquire_session_lock(session_id)` succeeds again.
  - `test_edit_deck_on_a_legacy_deck_writes_nothing`: a session created with
    `deck_mode="legacy"`. `_edit_deck_impl` raises `MCP_LEGACY_DECK_ERROR`, and the
    `chat_requests` and `session_messages` row counts for that session are unchanged.
  - `test_edit_deck_on_an_app_made_agent_deck_enters`: a session created the way
    `_maybe_create_session` creates one (`graph_capable=True`, `deck_mode` None), then
    `_edit_deck_impl` as its creator. The deck mode is now `"agent"` and the payload has
    `engine_mode == "graph"`.

- [ ] **Step 2: Run (Postgres up)**

Run: `uv run pytest tests/integration/test_mcp_agent_mode_postgres.py -v`
Expected: PASS. Sabotage-verify each test (`executing-plans-tellr` §1). For example,
temporarily pass `requested_deck_mode=None` in `_enter_turn_or_tool_error` and confirm
the app-made-deck test fails, then revert. A test that can't be made red this way is
rewritten.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_mcp_agent_mode_postgres.py
git commit -m "test(mcp): MCP Agent turns through the real Enter on Postgres"
```

---

### Task 7: Verify on a devloop

Models: test=opus impl=opus (run by the orchestrator, not dispatched)

**Files:** none; findings go in the ledger and the PR body.

**Interfaces:**
- Consumes: the branch with Tasks 1–6, renamed `feat/mcp-agent-mode` (already its
  name). Deploy through the `deploy-tellr-dev` skill to a `devloop` instance named
  `mcp-agent` (≤17 chars; check with ListAgents that no peer session owns it).
- Produces: a checked-off copy of the spec's "How we'll know it works" list in the PR
  body.

- [ ] **Step 1: Publish and deploy** per `deploy-tellr-dev`: push as `robertwhiffin`,
  run `gh workflow run publish-dev.yml --ref feat/mcp-agent-mode`, then run
  `./scripts/deploy_local.sh create --env devloop --instance mcp-agent --profile tellr-dev --from-pypi <version>`.
  Re-run the adoption probes afterwards (devloop forks inherit prod releases; see memory).

- [ ] **Step 2: Drive the MCP.** Use `scripts/mcp_smoke/mcp_smoke_httpx.py` (extended
  locally, not committed, for `edit_deck` and repeated polls) against the devloop URL.
  The script needs a user token: **ask the user before using one** (session policy).
  Check every bullet of the spec's "How we'll know it works" that a token caller can
  reach:
  - the topic build (`reply`, `deck_changed: true`, the deck opens as an Agent deck with
    the default design system and template);
  - the no-topic prompt;
  - an edit by slide number;
  - a question;
  - a Legacy deck refused;
  - an app-made Agent deck edited;
  - a collaborator refused (needs a second user, or record it as covered by Task 4's
    unit test);
  - a turn stopped from the Tellr UI reporting `failed` with the stopped copy;
  - with Genie One default on, a data prompt making a successful Genie One call.

- [ ] **Step 3: Record.** Record the results in the ledger and the PR body. The
  token-less (`x-forwarded-identity`) bullet is covered by Task 3's unit test; say so
  explicitly in the PR body rather than claiming it was live-verified.

- [ ] **Step 4: Tear down** the devloop instance once the PR is merged or abandoned.

---

## PR body must carry

- **Breaking for MCP callers:** `edit_deck` refuses Legacy decks (every deck made over
  MCP before this release) and non-owners. `create_deck` no longer takes `num_slides`
  or `deck_prompt_id`, and `edit_deck` no longer takes `slide_indices`. Callers that
  still send them aren't errored; the values are ignored. Name slide counts and slides
  in the prompt or instruction instead.
- For the release-tellr "After deploying" notes: known MCP callers (fe-tellr plugin,
  TAP builder, DAIS agenda curator, KPMG pricing skills) should be told about the
  breaking changes.
