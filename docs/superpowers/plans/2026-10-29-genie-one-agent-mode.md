# Genie One in Agent Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, together with the repo's `executing-plans-tellr` skill. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In agent-mode decks, the data analyst can ask Genie One questions as the signed-in user. Genie One's figures reach the slides verbatim, with a "Source: Genie One" line. The app gains the `ai-gateway` and `catalog.connections` scopes through code, and users with stale consent see a clear message.

**Architecture:**
- **Tool loop:** a tool-calling loop inside `DatabricksModelAdapter` (`invoke_with_tools`). It runs only when `AgentAssemblyContext.toolset` is set, which only `data_analyst_node` does.
- **Genie One client:** `src/services/agent_tools/genie_one.py` runs ask/poll/result against the AI Gateway MCP as the user. It converts result rows into `ResolvedFigure`s deterministically.
- **Figures:** they travel on a new turn-scoped graph state key, and the architect node writes them into `deck_spec.resolved_data.figures`. No model retypes a number, and `AnalystOutput` is unchanged.
- **Prompts:** the only prompt change is the builder's source line, promoted through the eval harness.

**Tech Stack:** Python 3.11, LangChain/LangGraph, `databricks-mcp` 0.9.0, FastAPI, pytest, React + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-genie-one-agent-mode-design.md`. Read its "Rulings made during planning" section: it overrides earlier sections of the spec where they conflict.

**Base:** branch `feat/genie-one-agent`, in the worktree `/Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/genie-one`. It is rebased onto `feat/prompt-shipping`'s final head before the PR is opened.

## Global Constraints

- **Run everything via `uv run`** in this worktree's `.venv`. Never `pip install`.
- **Genie One identity:** calls run only with the signed-in user's token, from `get_user_client()`'s `config.host` and `config.token`, captured in the node thread. Never use the service principal, and never fall back to it.
- **Schema and prompt:** don't touch `AnalystOutput` or any output schema or digest. Don't change the data analyst prompt; it is promote-locked by `LegacyV1PromptTransition`.
- **Exact values:**
  - Tool name bound for the model: `genie`.
  - Figure `source` string: `Genie One`.
  - MCP server path: `/ai-gateway/mcp-services/system.ai.genie_one_mcp`. The URL is `f"{host}{path}"`, with no `?o=`.
- **Budgets:**
  - At most 3 Genie One questions and 300 s per analyst run.
  - At most 2 analyst rounds per turn.
  - Poll every 3 s.
  - At most 60 figures per answer and 50 rows per result shown to the model.
- **Job limits:** graph-mode jobs get 1200 s. Monolith jobs keep `JOB_HARD_TIMEOUT_SECONDS = 600`.
- **Untrusted output:** everything Genie One returns reaches the model only through `spotlight("genie_one", …)`. HTML comments (`<!-- … -->`) and `narration_instruction` are stripped first.
- **Scopes in code,** in this order: `sql`, `dashboards.genie`, `catalog.tables:read`, `catalog.schemas:read`, `catalog.catalogs:read`, `serving.serving-endpoints`, `ai-gateway`, `catalog.connections`. Update adds the missing scopes and never removes one.
- **Real fixtures:** `tests/fixtures/genie_one/*.json` are real recorded responses, sanitised. Tests that parse Genie One responses load these files. Don't hand-write response shapes.

## Review Focus

1. **Genie One fails or finds nothing** (`failed` / `incomplete`, zero rows, or an `isError` result). The analyst reports a gap, no figures are written, and the turn still builds. Pinned in Task 4 (`test_failed_answer_yields_no_figures`) and Task 6 (`test_analyst_with_failed_genie_answer_still_returns_message`).
2. **A big result** (1,000 rows, `truncated: true`). Figures are capped at 60 and the model sees 50 rows plus a truncation note. Pinned in Task 4 (`test_large_result_is_capped_for_figures_and_model_text`).
3. **A legacy deck whose config holds a `genie_one` entry.** The legacy agent builds and runs and ignores the entry. Pinned in Task 3 (`test_legacy_build_tools_skips_genie_one`).
4. **A later edit turn where the architect re-emits `resolved_data` and retypes or drops Genie figures.** The code re-applies the prior spec's `Genie One` figures verbatim. Pinned in Task 6 (`test_later_turn_reapplies_prior_genie_figures_verbatim`).
5. **A contributor on a shared deck,** whose actor row has no Genie One entry. Today's behaviour holds: no tools and no error. Pinned in Task 6 (`test_contributor_without_genie_one_runs_without_tools`).

---

### Task 1: App scopes in code

**Models:** test=sonnet impl=haiku

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py`: `_create_app` (`:1677-1684`) and `_update_databricks` (`:523`).
- Test: `tests/unit/test_deploy_app_scopes.py`. Mirror the fake-`ws` style of `tests/unit/test_deploy_secret_encryption_key.py:352-390`.

**Interfaces:**
- Produces:
  ```python
  REQUIRED_USER_API_SCOPES: tuple[str, ...] = ("sql", "dashboards.genie", "catalog.tables:read",
      "catalog.schemas:read", "catalog.catalogs:read", "serving.serving-endpoints",
      "ai-gateway", "catalog.connections")
  def _ensure_app_user_api_scopes(ws: WorkspaceClient, app_name: str,
                                  required: Sequence[str] = REQUIRED_USER_API_SCOPES) -> list[str]
      # returns the scopes it added (in `required` order); [] means no apps.update call was made
  ```
- `_create_app` passes `user_api_scopes=list(REQUIRED_USER_API_SCOPES)`.
- `_ensure_app_user_api_scopes` does `cur = ws.apps.get(name=app_name)`, then `missing = [s for s in required if s not in (cur.user_api_scopes or [])]`. If anything is missing, it calls `ws.apps.update(name=app_name, app=App(name=app_name, description=cur.description, default_source_code_path=cur.default_source_code_path, user_api_scopes=list(cur.user_api_scopes or []) + missing, resources=cur.resources))`, with no `compute_size`. It prints `   Scopes added: <comma list>`.
- `_update_databricks` calls it once, before `ws.apps.deploy_and_wait`.

- [ ] **Step 1: Write the failing tests:**
  - `test_create_app_requests_the_full_scope_list_in_order`
  - `test_ensure_adds_only_missing_scopes_after_existing_ones`, with existing scopes `["sql", "genie", "dashboards.genie"]`: the new list keeps `genie` and appends the missing scopes in `REQUIRED` order.
  - `test_ensure_makes_no_update_call_when_nothing_is_missing`
  - `test_ensure_carries_description_source_path_and_resources_and_omits_compute_size`
  - `test_update_ensures_scopes_before_deploying`, which spies call order on the fake `ws`.
- [ ] **Step 2: Run them and confirm they fail.**
  Run: `uv run pytest tests/unit/test_deploy_app_scopes.py -q`
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run the tests, plus `tests/unit/test_deploy_secret_encryption_key.py` and `tests/unit/test_deploy_autoscaling.py`. All should pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat(deploy): ai-gateway and catalog.connections scopes; update adds missing scopes"`

### Task 2: Missing-scope detection, the consent message, and the MCP picker

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/core/scope_errors.py`
- Modify: `src/api/routes/tools.py`, where `_discover_mcp_connections` (`:236-259`) currently returns `{"items": []}` on any exception.
- Modify: `frontend/src/types/agentConfig.ts`. `DiscoveryResponse` (`:91-93`) gains `error?: string; error_code?: string`.
- Modify: `frontend/src/services/api.ts`. `discoverMCPConnections` (`:2307-2311`) returns the parsed JSON body when there is one, else `{ items: [], error: \`Could not list MCP connections (${response.status}).\` }`.
- Modify: `frontend/src/components/AgentConfigBar/tools/MCPDiscovery.tsx`. When the result has `error`, render it in place of `No MCP connections available.` (`:146`), with `whitespace-pre-line`.
- Tests: `tests/unit/test_scope_errors.py`, `tests/unit/test_tools_discovery_mcp_errors.py`, and `frontend/src/components/AgentConfigBar/tools/MCPDiscovery.test.tsx`.

**Interfaces:**
- Produces, in `src/core/scope_errors.py`:
  ```python
  def is_missing_scope_error(exc: BaseException) -> bool
  def oauth_client_id_from_token(token: str | None) -> str | None
  def consent_message(*, oauth_client_id: str | None) -> str
  ```
- `is_missing_scope_error` walks `exc`, its `__cause__` and `__context__`, and any `BaseExceptionGroup.exceptions`. It returns True when any message matches `re.compile(r"(required scopes|invalid scope)", re.I)`. Both real texts must match:
  - the fixture `tests/fixtures/genie_one/error_missing_scope_sdk.json` (`…Invalid scope, required scopes: unity-catalog…`);
  - the staging log text `Provided OAuth token does not have required scopes: unity-catalog`.

  A plain `PermissionDenied("User does not have USE CONNECTION on connection x")` returns False.
- `oauth_client_id_from_token` base64url-decodes the JWT payload without verifying it, and returns `client_id`, else `azp`, else None. It also returns None for a non-JWT, and never raises.
- `consent_message` gives exactly this text, with `{client_id}` filled in or `<this app's OAuth client ID>`:
  ```
  Tellr can't do this on your behalf yet: your sign-in to this app is missing a permission it needs.

  There are two possible causes:
  1. The app itself hasn't been given the permission. A workspace admin fixes this by running tellr.update() for this app.
  2. You approved this app before it needed this permission. To approve it again:
     a. Run: databricks api delete /api/2.0/oauth-app-integrations/{client_id}/user-consent/me
     b. Clear this site's data in your browser, or open the app in a private window.
     c. Reload the app and approve the new permissions when asked.
  ```
- `_discover_mcp_connections` returns:
  - on a missing-scope error, `{"items": [], "error": consent_message(oauth_client_id=oauth_client_id_from_token(get_user_client().config.token)), "error_code": "missing_scope"}`;
  - on any other exception, `{"items": [], "error": f"Could not list MCP connections: {type(exc).__name__}", "error_code": "discovery_failed"}`.

  Log both at WARNING.

- [ ] **Step 1: Write the failing tests:**
  - the scope detector's positives (fixture text, staging text, wrapped in `__cause__`, inside an `ExceptionGroup`) and negatives;
  - client id from a hand-built JWT, plus None for `"dapi123"` and for `None`;
  - the exact consent copy, with and without an id;
  - the route returns `missing_scope` and the message when `connections.list` raises the fixture's error;
  - the route returns `discovery_failed` on `RuntimeError`;
  - vitest: MCPDiscovery renders the `error` text and not the empty-state copy, and the empty state still shows when there is no error.
- [ ] **Step 2: Run them and confirm they fail.**
  Run: `uv run pytest tests/unit/test_scope_errors.py tests/unit/test_tools_discovery_mcp_errors.py -q`, then `cd frontend && npx vitest run src/components/AgentConfigBar/tools/MCPDiscovery.test.tsx`
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run the tests above, plus `cd frontend && npx tsc --noEmit`. All should pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat: typed missing-scope detection; MCP picker shows the consent message"`

### Task 3: The `genie_one` tool type, end to end

**Models:** test=sonnet impl=sonnet

**Files:**
- Backend:
  - `src/api/schemas/agent_config.py`: a new `GenieOneTool` added to `ToolEntry` (`:68-71`), a `no_duplicate_tools` key (`:105-116`), and the `sanitize_agent_config_for_persist` strip (`:324-326`).
  - `src/api/routes/agent_config.py`: the `patch_tools` `_key` (`:283-294`).
  - `src/services/agent_resolution.py`: an explicit skip in `_build_tools` (`:444-500`), logged at DEBUG as `genie_one is agent-mode only; skipped for the legacy agent`.
- Frontend:
  - `frontend/src/types/agentConfig.ts`: the interface, `ToolType`, `ToolEntry`, and all three `Record<ToolType, …>` maps (`:135-157`).
  - `frontend/src/components/AgentConfigBar/ToolPicker.tsx`: the button.
  - `frontend/src/components/AgentConfigBar/AgentConfigBar.tsx`: the chip.
  - `frontend/src/contexts/AgentConfigContext.tsx`: the `removeTool` branch (`:955-977`).
  - `frontend/src/components/config/ProfileList.tsx`: the union and counts.
- Tests: `tests/unit/test_agent_config_genie_one.py`, and `frontend/src/components/AgentConfigBar/ToolPicker.test.tsx`.

**Interfaces:**
- Produces:
  ```python
  class GenieOneTool(BaseModel):
      type: Literal["genie_one"] = "genie_one"
      conversation_id: Optional[str] = None
  ```
  `no_duplicate_tools` key: `"genie_one"`. The persist strip sets `conversation_id = None`.
- TS:
  ```ts
  export interface GenieOneTool { type: 'genie_one'; conversation_id?: string | null }
  ```
  - Labels: `TOOL_TYPE_LABELS.genie_one = 'Genie One'`, and the badge label is `'Genie One'`.
  - `TOOL_CATEGORIES` gets `{ type: 'genie_one', label: '+ Genie One' }` as its **first** entry. Clicking it calls `onSelect({ type: 'genie_one' })` directly, with no discovery panel. The button isn't rendered while `existingTools` already contains a `genie_one` entry. Test id: `add-tool-genie_one`.
  - The chip label is `Genie One`. When the deck is legacy (`(storedDeckMode ?? selectedDeckMode) === 'legacy'` from `useSession()`), the chip has `title="Genie One works in agent mode only"` and shows the muted suffix ` · agent mode only`.

- [ ] **Step 1: Write the failing tests:**
  - schema round-trip;
  - a duplicate `genie_one` is rejected with `Duplicate tool: genie_one`;
  - the persist strip clears `conversation_id`;
  - `PATCH /tools` with action remove deletes the entry;
  - `test_legacy_build_tools_skips_genie_one`: `_build_tools` with a config holding `genie_one` returns the same tool names as without it;
  - vitest: Genie One is the first picker button, clicking it calls `onSelect` with `{type:'genie_one'}`, and it is hidden when the entry exists.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run the tests, plus `uv run pytest tests/unit -q -k "agent_config or tool"` and `cd frontend && npx tsc --noEmit && npx vitest run src/components/AgentConfigBar`. All should pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat: genie_one tool type and '+ Genie One' button"`

### Task 4: Genie One client, figures and model text

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/services/agent_tools/__init__.py` (empty) and `src/services/agent_tools/genie_one.py`
- Test: `tests/unit/test_genie_one_client.py`

**Interfaces:**
- Consumes: `ResolvedFigure` (`src/domain/deck_spec.py:59`), `spotlight` (`src/utils/spotlight.py:22`), `is_missing_scope_error` (Task 2), and `DatabricksMCPClient`. Copy the clean-thread pattern of `src/services/tools/mcp_tool.py:40-76`, but don't use `with ThreadPoolExecutor(...)`, because its exit waits on a timed-out thread. Use `executor.shutdown(wait=False)`.
- Produces:
  ```python
  GENIE_ONE_SERVICE_PATH: Final = "/ai-gateway/mcp-services/system.ai.genie_one_mcp"
  GENIE_ONE_SOURCE: Final = "Genie One"
  class GenieOneError(Exception): ...
  class GenieOneAccessError(GenieOneError):
      kind: Literal["missing_scope", "access_denied"]
  @dataclass(frozen=True)
  class GenieOneQueryResult:
      item_id: str; sql: str | None; columns: tuple[str, ...]
      rows: tuple[tuple[str | None, ...], ...]; total_row_count: int | None; truncated: bool
  @dataclass(frozen=True)
  class GenieOneAnswer:
      conversation_id: str; response_id: str
      status: Literal["completed", "incomplete", "failed", "timed_out"]
      final_answer: str | None; deep_link: str | None
      query_results: tuple[GenieOneQueryResult, ...]
  CallTool = Callable[[str, dict[str, Any]], Any]   # returns an mcp CallToolResult-like object
  class GenieOneClient:
      def __init__(self, *, host: str, token: str, call_tool: CallTool | None = None,
                   sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic,
                   poll_interval_seconds: float = 3.0) -> None
      def ask(self, question: str, *, conversation_id: str | None, timeout_seconds: float) -> GenieOneAnswer
  def figures_from_answer(answer: GenieOneAnswer, *, max_figures: int = 60) -> list[ResolvedFigure]
  def render_answer_for_model(answer: GenieOneAnswer, *, max_rows: int = 50) -> str   # pre-spotlight text
  ```

**Behaviour:**
- **`ask`:**
  1. Calls `genie_ask`. It passes `conversation_id` only when one is given.
  2. Calls `genie_poll_response` every `poll_interval_seconds` until `status != "in_progress"`. If `clock` passes the deadline first, it calls `genie_cancel_response` (best effort) and returns `status="timed_out"`.
  3. On `completed`, calls `genie_get_query_result` for each `query_items[].item_id`. A failed item is skipped and logged.
- **`isError` results:** a text containing `403`, `Forbidden` or `PERMISSION_DENIED` raises `GenieOneAccessError(kind="access_denied")`. Any other text raises `GenieOneError(text)`.
- **Exceptions:** `is_missing_scope_error` gives `GenieOneAccessError(kind="missing_scope")`; `403`, `Forbidden` or `PERMISSION_DENIED` in the text gives `access_denied`; anything else gives `GenieOneError`.
- **`figures_from_answer`:**
  - Works per query result, in order, skipping empty ones.
  - **1 row:** `key=<column>` for each column.
  - **≥2 columns, n rows:** for each row and each column after the first, `key=f"{col} ({first_col}={row[0]})"`.
  - **1 column, n rows:** `key=f"{col} [{i+1}]"`.
  - `value` is the cell, or `"null"`. `source="Genie One"`.
  - A key already taken by an earlier result gets the suffix ` (query {n})`, where n is the 1-based result index.
  - Stops at `max_figures`.
- **`render_answer_for_model`:**
  - It contains `Status: <status>`, the `final_answer` with every `<!--…-->` removed, and per result its `SQL: <sql>` plus a pipe table of at most `max_rows` rows, followed by `(showing N of M rows)` when cut.
  - It never contains `narration_instruction`.

- [ ] **Step 1: Write the failing tests.**

  Use a fake `call_tool` that replays the fixtures (`q1_ask` → `q1_poll_in_progress` → `q1_poll_final` → `q1_query_result_0`):
  - `test_ask_polls_until_completed_and_fetches_results`: the answer's `conversation_id`, `deep_link`, one query result with columns `("pickup_zip","trip_count")` and 3 rows, and the call sequence.
  - `test_follow_up_passes_conversation_id`
  - `test_q1_figures`: exactly `[("trip_count (pickup_zip=10001)","1227","Genie One"), ("trip_count (pickup_zip=10003)","1181",…), ("trip_count (pickup_zip=10011)","1129",…)]`.
  - `test_q2_figures_include_the_combined_row`, using `q2` fixtures: includes `("avg_fare_amount (pickup_zip=All 3 combined)","10.83")`.
  - `test_single_row_result_uses_column_names_as_keys`
  - `test_large_result_is_capped_for_figures_and_model_text`: 1000 synthetic rows, `truncated` true, gives 60 figures, and the text contains `(showing 50 of 1000 rows)`.
  - `test_render_strips_agent_comments`: the q1 final text contains no `<!--`, `MUST include` or `Tool-call IDs`, but still contains `10001`.
  - `test_timeout_cancels_and_returns_timed_out`: a fake clock; `genie_cancel_response` is called with the conversation id.
  - `test_failed_answer_yields_no_figures`
  - `test_is_error_result_raises_genie_one_error`, using the fixture `error_bad_response_id`.
  - `test_missing_scope_exception_becomes_access_error`, using the fixture message.
  - `test_403_text_becomes_access_denied`
- [ ] **Step 2: Run them and confirm they fail.**
  Run: `uv run pytest tests/unit/test_genie_one_client.py -q`
- [ ] **Step 3: Implement `src/services/agent_tools/genie_one.py`.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat(agent-tools): Genie One client, deterministic figures, model text"`

### Task 5: The runtime tool loop

**Models:** test=opus impl=opus

**Files:**
- Create: `src/services/agent_tools/toolset.py`
- Modify: `src/services/agent_runtime.py`:
  - `AgentAssemblyContext` (`:138-154`) gains `toolset` (`compare=False`);
  - `bind_structured_output_model` (`:214`);
  - `DatabricksModelAdapter` (`:395-466`);
  - `_run_resolved` (`:957-994`);
  - `run_candidate` (`:731`) and `run_published_baseline` (`:791`) refuse a toolset.
- Tests: `tests/unit/test_agent_runtime_tool_loop.py`. Also update the pins in `tests/unit/test_agent_runtime.py` (see the rules below).

**Interfaces:**
- Produces, in `toolset.py`:
  ```python
  class ToolAccessError(Exception):
      def __init__(self, kind: Literal["missing_scope", "access_denied"], tool_name: str, message: str)
  class AgentTool(Protocol):
      name: str; description: str; args_schema: type[BaseModel]
      def run(self, args: BaseModel, *, remaining_seconds: float) -> str
  @dataclass
  class AgentToolset:
      tools: tuple[AgentTool, ...]
      max_calls: int = 3
      budget_seconds: float = 300.0
      clock: Callable[[], float] = time.monotonic
      calls_made: int = field(default=0, init=False)
      access_errors: list[ToolAccessError] = field(default_factory=list, init=False)
      def start(self) -> None
      def remaining_seconds(self) -> float
      def exhausted(self) -> bool          # calls_made >= max_calls or remaining_seconds() <= 0
  ```
- In `agent_runtime.py`:
  - `AgentAssemblyContext.toolset: AgentToolset | None = field(default=None, compare=False)`.
  - `DatabricksModelAdapter.invoke_with_tools(self, *, agent_key, configuration, schema, prompt, toolset) -> BaseModel`.
  - `run`'s positional arity is unchanged, and production run calls still pass four positional arguments with zero keywords.

**Rules:**
- There is still **exactly one** `bind_tools` call in `src/`. Factor a private `_bind_tools(model, schema, extra_tools)` that both the structured-output path and the tool loop use. Pass the tools as LangChain tool dicts built from each `AgentTool`'s `name`, `description` and `args_schema`.
- **The loop:**
  1. `messages = [HumanMessage(prompt)]` and `toolset.start()`.
  2. Each round: invoke the bound model. If any tool call names the schema, validate it with `schema.model_validate(args)` and return it.
  3. If there are no tool calls, add one `HumanMessage(f"Respond by calling {schema.__name__}.")`. A second empty reply raises `OutputParserException`.
  4. Otherwise answer each tool call with a `ToolMessage`:
     - if `toolset.exhausted()`: `Tool budget exhausted. Call {schema.__name__} now with what you have.`;
     - otherwise `calls_made += 1` and `tool.run(args_schema.model_validate(call["args"]), remaining_seconds=…)`;
     - a `ToolAccessError` is appended to `toolset.access_errors` and answered with `Access denied: {message}`;
     - any other `Exception` is answered with `Tool error: {type}: {str(exc)[:300]}`;
     - an unknown tool name is answered with `Unknown tool: {name}`.
  5. Stop after `max_calls + 3` rounds, then raise `OutputParserException`.
- **Error mapping:**
  - The model call's provider errors map to `ModelProviderUnavailableError` exactly as `invoke` does today. Factor the existing tuple; don't duplicate it.
  - Tool errors **never** become provider errors.
- `_run_resolved` calls `invoke_with_tools` when `assembly_context.toolset is not None`. If the adapter lacks the method, it raises `TypeError("model adapter cannot run tools")`.
- **Updating existing pins (deliberate; give each its reason in the test docstring):**
  - Keep `test_databricks_model_adapter_never_binds_legacy_tool_grants` green. `tool_grants` is still never read, which `tests/unit/test_lakebase_only_runtime_contract.py:189` also checks.
  - The single-`bind_tools` pin stays at 1.
  - Any AST pin on `_run_resolved`'s adapter call must allow the `invoke_with_tools` branch.

- [ ] **Step 1: Write the failing tests.** Use a fake chat model whose `bind_tools` records the tool list and whose `invoke` returns scripted `AIMessage`s with `tool_calls`.
  - `test_schema_call_first_returns_without_running_tools`
  - `test_tool_call_then_schema_runs_the_tool_once_and_returns`: the `ToolMessage` content equals the tool's return value.
  - `test_fourth_call_is_refused_when_max_calls_is_3`
  - `test_time_budget_exhaustion_refuses_further_calls`, with a fake clock.
  - `test_access_error_is_recorded_and_the_loop_continues`
  - `test_tool_exception_becomes_a_tool_message`
  - `test_two_empty_replies_raise_output_parser_exception`
  - `test_provider_error_maps_to_model_provider_unavailable`
  - `test_no_toolset_keeps_the_single_call_path`: the adapter's `invoke` is used and `invoke_with_tools` is not.
  - `test_run_candidate_refuses_a_toolset`
  - `test_bound_tools_are_schema_plus_toolset_tools_in_one_bind_call`
- [ ] **Step 2: Run them and confirm they fail.**
  Run: `uv run pytest tests/unit/test_agent_runtime_tool_loop.py -q`
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run `uv run pytest tests/unit/test_agent_runtime_tool_loop.py tests/unit/test_agent_runtime.py tests/unit/test_persisted_agent_runtime.py tests/unit/test_lakebase_only_runtime_contract.py tests/unit/evals -q`. All should pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat(runtime): tool-calling loop for an invocation that carries a toolset"`

### Task 6: Graph wiring (analyst toolset, figures, progress, conversation, consent)

**Models:** test=opus impl=opus

**Files:**
- Create: `src/services/agent_tools/registry.py`. This holds `GenieOneAgentTool`, which adapts `GenieOneClient` to `AgentTool` under the name `genie`, and `build_analyst_toolset`.
- Modify:
  - `src/services/graph/state.py`: two new turn-scoped keys, plus their `_EMPTY_FOR` entries (`:59`).
  - `src/services/graph/nodes.py`: `_assembly_context` (`:178`) gains a keyword-only `toolset=None`; `data_analyst_node` (`:3584-3664`); `architect_node` (the merge, around `:3111-3123`); and the docstrings at `:3595-3606` and in `src/core/skills/data_analyst.py:3-7`.
  - `src/api/services/session_manager.py`: a helper to persist the Genie One conversation id on the actor row.
- Tests: `tests/unit/test_data_analyst_genie_one.py`, plus updates to `tests/unit/test_graph_nodes.py`:
  - `_EXPECTED_NODE_WRITES` at `:5050`: data_analyst writes `{"architect_message", "analyst_figures", "analyst_rounds"}`;
  - the read-side and declared-key tests;
  - `tests/integration/test_graph_mode_turn.py:855`.

**Interfaces:**
- Consumes: Task 4's `GenieOneClient`, `figures_from_answer`, `render_answer_for_model`, `GenieOneAccessError`, `GENIE_ONE_SOURCE`; Task 5's `AgentToolset`, `ToolAccessError` and `AgentAssemblyContext.toolset`; Task 3's `GenieOneTool`; Task 2's `consent_message` and `oauth_client_id_from_token`; and `spotlight`.
- Produces:
  ```python
  # registry.py
  GENIE_TOOL_NAME: Final = "genie"
  class GenieOneAgentTool:          # implements AgentTool
      name = "genie"; args_schema = GenieQuestion  # pydantic: question: str
      def __init__(self, client: GenieOneClient, *, conversation_id: str | None,
                   on_question: Callable[[str], None], session_id: str | None) -> None
      answers: list[GenieOneAnswer]     # every answer this run, in order
      conversation_id: str | None       # latest, after each answer
      def run(self, args, *, remaining_seconds: float) -> str   # spotlight("genie_one", render_answer_for_model(a), session_id=...)
                                                                # GenieOneAccessError -> raise ToolAccessError(kind, "genie", str)
  def build_analyst_toolset(agent_config: AgentConfig, *, host: str, token: str,
                            on_question: Callable[[str], None], session_id: str | None
                            ) -> tuple[AgentToolset, GenieOneAgentTool] | None   # None when no GenieOneTool entry
  # state.py (both Annotated[Any, turn_scoped_concat], written as scoped(turn_id, [...]))
  analyst_figures   # list of ResolvedFigure dicts gathered this turn
  analyst_rounds    # one marker per data_analyst run this turn
  MAX_ANALYST_ROUNDS_PER_TURN: Final = 2   # nodes.py
  def _with_genie_figures(spec: DeckSpec, figures: list[ResolvedFigure]) -> DeckSpec   # nodes.py, pure
  # session_manager
  def set_genie_one_conversation_id(self, session_id: str, conversation_id: str) -> None
      # targeted read-modify-write of that row's agent_config genie_one entry only
  ```

**`GenieOneAgentTool` description (exact):**

> `Ask Genie One, the Databricks data agent, a natural-language question about the user's data. It writes and runs SQL on the user's behalf and returns an answer with result tables. Each question takes one to four minutes, and you may ask at most 3 per request, so ask a few broad questions that cover what the data request needs rather than many narrow ones. Figures from its results are recorded automatically with source "Genie One"; list "Genie One" in sources when you use them.`

**`data_analyst_node` behaviour:**
1. If `len(scoped_vals(state, "analyst_rounds")) >= MAX_ANALYST_ROUNDS_PER_TURN`, don't call the runtime. Message: `Data gathering for this turn is complete. Plan the deck with the data already gathered.` The node still writes the round marker.
2. Read the actor row's agent config: `resolve_agent_config(get_session_manager().get_session(state["actor_session_id"]).get("agent_config"))`. Any exception counts as no config.
3. With a Genie One entry:
   - Capture `client = get_user_client()`, and `host`/`token` from `client.config`.
   - Build the toolset. `on_question` does `_emit(StreamEventType.TOOL_CALL, content=f"Asking Genie One: {q}", metadata={"node": "data_analyst", "tool_name": "genie_one"})` and `_say(state, f"Asking Genie One: {q}", message_type="tool_call", metadata={"tool_name": "genie_one", "tool_input": {"question": q}})`.
   - Pass the toolset through `_assembly_context(..., toolset=toolset)`.
4. After the run:
   - `figures = [f for a in tool.answers for f in figures_from_answer(a)]`.
   - If `tool.conversation_id` changed, persist it with `set_genie_one_conversation_id(state["actor_session_id"], …)`.
   - The message is today's outcome prose, plus `\nFigures from Genie One (use these keys in data_references):\n- {key}: {value}` (one line per figure), plus `\nExplore in Databricks: {deep_link}`, once per distinct link.
5. **Access errors:**
   - If any is `missing_scope`: `_say(state, consent_message(oauth_client_id=oauth_client_id_from_token(token)), message_type="info")`.
   - If any is `access_denied`: `_say(state, "Genie One refused the request. You may need EXECUTE permission on system.ai.genie_one_mcp; ask a workspace admin to grant it.", message_type="info")`.
6. **Without a Genie One entry,** or when it can't get a user client: exactly today's call, with no toolset.

**`architect_node` merge:**
- After the refusal return and before `_apply_edit_plan`, compute the code-owned Genie figures:
  - the figures gathered this turn (`scoped_vals(state, "analyst_figures")`), if any;
  - else the prior persisted spec's figures whose `source == "Genie One"`.
- If that list is non-empty, set `spec = _with_genie_figures(spec, those)`, and the same on `plan.spec` when there is a plan.
- `_with_genie_figures` keeps the architect's figures whose source isn't `Genie One` and whose key isn't among the code figures, then appends the code figures in order, through `model_copy`.

- [ ] **Step 1: Write the failing tests:**
  - `test_analyst_without_genie_one_runs_exactly_as_today`: the runtime's `run` gets a context with `toolset is None`.
  - `test_contributor_without_genie_one_runs_without_tools`
  - `test_analyst_with_genie_one_passes_a_toolset_and_writes_figures`: a fake runtime calls the tool once with a fake client replaying the q1 fixtures. `analyst_figures` equals `figures_from_answer(q1)`. The message contains `Explore in Databricks:` and `trip_count (pickup_zip=10001): 1227`.
  - `test_progress_line_is_emitted_and_persisted_per_question`
  - `test_conversation_id_is_persisted_on_the_actor_row_only`
  - `test_missing_scope_access_error_says_the_consent_message`
  - `test_access_denied_says_the_grant_message`
  - `test_analyst_with_failed_genie_answer_still_returns_message`
  - `test_third_round_in_a_turn_is_refused_without_calling_the_runtime`
  - `test_architect_writes_genie_figures_verbatim_into_resolved_data`
  - `test_later_turn_reapplies_prior_genie_figures_verbatim`: the architect output retypes a value. The committed spec keeps the prior value.
  - `test_architect_keeps_its_own_non_genie_figures`
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run `uv run pytest tests/unit/test_data_analyst_genie_one.py tests/unit/test_graph_nodes.py tests/unit/test_graph_state.py -q` and `uv run pytest tests/integration/test_graph_mode_turn.py -q`. All should pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat(graph): analyst asks Genie One; figures reach resolved_data verbatim"`

### Task 7: The 20-minute limit for agent-mode jobs

**Models:** test=sonnet impl=haiku

**Files:**
- Modify: `src/api/services/job_queue.py`:
  - `enqueue_job` (`:62-82`) stores `engine_mode` from the payload;
  - `mark_timed_out_jobs_once` (`:350-395`) applies a per-job limit;
  - `recover_stuck_requests` (`:326`) uses `timedelta(seconds=GRAPH_JOB_HARD_TIMEOUT_SECONDS)`.
- Test: `tests/unit/test_job_queue_timeout_sweeper.py`. Keep `JOB_HARD_TIMEOUT_SECONDS == 600`, and add the new constant's tests.

**Interfaces:**
- Produces: `GRAPH_JOB_HARD_TIMEOUT_SECONDS = 1200`, and `def job_hard_timeout_seconds(engine_mode: str | None) -> int`, which returns 1200 for `"graph"` and 600 otherwise.

- [ ] **Step 1: Write the failing tests:**
  - a graph job running 700 s is not failed, and at 1300 s it is;
  - a monolith job at 700 s is failed;
  - `recover_stuck_requests` leaves a 15-minute-old running request alone and fails a 25-minute-old one.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat(jobs): 20-minute limit for agent-mode turns"`

### Task 8: The builder source line (prompt, measure, promote)

**Models:** test=opus impl=opus

Run this task following `.claude/skills/optimise-agent-prompt/SKILL.md`'s measurement discipline. The prompt text is fixed here, so this is not a search.

**Files:**
- Create: `evals/configs/builder/source-line.yaml` (with `base: v1`, `prompt_file: source-line.md`) and `evals/configs/builder/source-line.md`.
- Modified by `promote`: `src/services/agent_definition_manifest_v1.py` and the `PACKAGED_V1_CONTENT_HASHES` pins.
- Modify by hand:
  - `src/core/skills/builder.py` `INSTRUCTIONS`, to match the promoted text;
  - `tests/unit/test_architect_edit_prompt.py` `HEAD_OTHER_ROLE_CONTENT_HASHES` (the builder entry);
  - re-record `frontend/tests/fixtures/graphLifecycleContract.json`.

**The prompt change (exact).** Insert this block into the packaged builder `prompt_text`, directly before the line `SLIDE CONTENT RULES:`:
```
SOURCE LINE (only when the slide shows figures from resolved_data.figures):
  - Add one line at the bottom of the slide, inside the safe area, in a small muted font: "Source: " followed by the distinct source of each figure shown, for example "Source: Genie One"
  - Use only the source field of the figures you show; never invent a source

```
No other text changes. The existing `Do not add a note, callout or caption about missing data…` rule stays as it is. It governs the no-data branch, and `tests/unit/test_skill_prose.py:197` pins it.

- [ ] **Step 1: Write the failing test.**

  In `tests/unit/test_skill_prose.py`, add `test_builder_adds_a_source_line_for_sourced_figures`. It asserts that `load_skill("builder").instructions` contains `SOURCE LINE (only when the slide shows figures from resolved_data.figures):` and `never invent a source`. Do the same against the packaged manifest's builder `prompt_text`.
- [ ] **Step 2: Measure.**
  - `uv run python -m evals.run_eval --agent builder --calibrate`
  - The baseline: `--config v1-baseline --repeats 3`
  - The candidate: `--config evals/configs/builder/source-line.yaml --repeats 3`, all with `--profile tellr-dev`.

  The candidate passes when no case drops by more than one repeat against the baseline. Then run held-out once (`--split heldout --repeats 3`) on the candidate, and record both results in the task report.
- [ ] **Step 3: Promote.**
  - `uv run python -m evals.harness.promote --config builder=evals/configs/builder/source-line.yaml --run-id builder=<id> --dry-run`, then for real.
  - Update `builder.py` `INSTRUCTIONS` and `HEAD_OTHER_ROLE_CONTENT_HASHES`.
  - Re-record the lifecycle contract with the command `promote` prints.
- [ ] **Step 4: Run `uv run pytest tests/unit -q -n auto`. It should be green, measured against the baseline's cause set.**
- [ ] **Step 5: Commit.** `git commit -m "feat(builder): Source line for sourced figures (measured, promoted)"`

### Task 9: Rebase, review, PR, CI, devloop, live check (controller)

**Models:** test=opus impl=opus

The controller runs this; the whole-branch reviewer is Opus.

- [ ] **Step 1:** Rebase `feat/genie-one-agent` onto the final `feat/prompt-shipping`. Run the full unit and frontend suites.
- [ ] **Step 2:** Whole-branch Opus review. Ask for:
  - a writer-by-writer check of who writes `resolved_data.figures`;
  - a check of the identity used on each Genie One call path;
  - merge/no-merge.
- [ ] **Step 3:** Push and open a PR with base `feat/prompt-shipping`. Iterate until CI is green.
- [ ] **Step 4:** Publish a `.devN` from this branch and deploy devloop instance `genie-one` (`deploy-tellr-dev`).
- [ ] **Step 5: Live check** in the owner's Chrome over DevTools, following the spec's "Live verification":
  - give consent;
  - in an agent-mode deck, add Genie One and ask for a deck on `samples.nyctaxi.trips`;
  - check the progress lines, the figures, the "Source: Genie One" line, and the "Explore in Databricks" link.

  Record the four open questions' answers in the PR.
