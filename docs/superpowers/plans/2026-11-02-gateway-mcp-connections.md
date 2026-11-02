# AI Gateway MCP connections — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, together with `.claude/skills/executing-plans-tellr`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admins register any AI Gateway MCP service; users add it to a deck from the MCP Server picker. In agent mode the architect or data analyst then calls its tools as the user. Sign-in is handled, and tool images land on slides.

**Architecture:**
- A generic Gateway MCP client (Genie One's transport, shared) plus a DB registry with an admin API and tab.
- A new `gateway_mcp` tool entry. The architect and analyst get a per-turn toolset built from the actor's entries.
- Tool results are shaped in code: images are saved as Tellr images and only `{{image:TOKEN}}` reaches the model. Image references are reconciled in code.

**Tech Stack:** FastAPI, SQLAlchemy (no Alembic: `Base.metadata.create_all`), LangGraph, `databricks-mcp` 0.9.0, `mcp` 1.27.0, React + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-11-02-gateway-mcp-connections-design.md`. Read it first: it carries the why, the exact copy and the measured shapes. Overnight decision log: `~/tellr-loop/mcp-connections/DECISIONS.md`.

## Global Constraints

- **Environment:** each worktree has its own uv venv. Run `uv sync --extra dev` once, and run every command through `uv run`.
  - Never `pip install`.
  - No new dependency (`databricks-mcp` and `mcp==1.27.0` are already in `packages/databricks-tellr-app/pyproject.toml`).
- **Identity:** every Gateway call runs as the signed-in user (`get_user_client()` host and token). There is no service-principal fallback.
- **Gateway URL:** `{host}/ai-gateway/mcp-services/<catalog>.<schema>.<service>`.
- **Timeouts and budgets:**
  - per-call timeout `CALL_TIMEOUT_SECONDS = 90`, clipped to the remaining budget; `tools/list` timeout `LIST_TIMEOUT_SECONDS = 30`;
  - architect: per turn `ARCHITECT_GATEWAY_MAX_CALLS = 12`, `ARCHITECT_GATEWAY_BUDGET_SECONDS = 360.0`;
  - analyst with Gateway tools: `ANALYST_GATEWAY_MAX_CALLS = 6`, `ANALYST_GATEWAY_BUDGET_SECONDS = 300.0` per run. Genie One alone stays 3 / 300.
  - `GATEWAY_TURN_DEADLINE_SECONDS = 700`: no Gateway call starts after 700 s into a turn.
- **Unchanged behaviour:**
  - No agent prompt text changes (`src/core/skills/*.py`, `src/services/agent_definition_manifest_v1.py`, prompt assembler stages).
  - A deck with no `gateway_mcp` entry behaves exactly as today. Genie One–only decks keep their tools and budget.
  - Legacy mode ignores `gateway_mcp`.
  - Genie One's tests (`tests/unit/test_genie_one_client.py`, `tests/unit/test_data_analyst_genie_one.py`, `tests/unit/test_agent_runtime_tool_loop.py`) pass **without edits**. The single exception is the `_NOT_RUN_TEXT` string in Task 4.
- **No base64 in the model's context.** Image data never reaches a `ToolMessage`.
- **Image saving:** `image_service.upload_image(..., category="content")`. Never `ephemeral`.
- **Spotlighting:** every tool output that reaches a model goes through `spotlight()` (`src/utils/spotlight.py`), with the connection's `display_name` as the source.
- **Exact copy** (from the spec; `{name}` = display name, `{service}` = service name):
  - progress: `"{name} · {tool}"`
  - sign-in: `"To use {name}, sign in here: {url} — then ask again."`
  - access: `"You don't have access to {name} ({service}). Ask an admin to grant EXECUTE on it."`
  - removed: `"{name} is no longer available."`
  - not found: `"{name} ({service}) was not found on this workspace. Ask an admin to check the connection."`
  - unavailable: `"{name} is unavailable right now ({reason}). The deck was built without it."`
  - missing scope: the existing `consent_message(...)`
  - image not placed: `"An image from a connected tool couldn't be placed on slide {n}."`
  - image note to the model: `"Image saved: {{image:TOKEN}} (<mime>, <w>×<h>). To show it on a slide, put this exact reference in that slide's content_brief."`. Omit `, <w>×<h>` when the size is unknown (SVG).
- **Commits:** end every commit message with `Co-authored-by: Isaac <no-reply@databricks.com>`. Subagents never push.
- **Fixtures:** recorded responses live in `~/tellr-loop/mcp-connections/fixtures/`. Copy the ones a task uses into `tests/fixtures/gateway_mcp/` unchanged (they contain no secrets). Doc-sourced LakeDraw fixtures carry `"_source": "doc"` at the top level.

## Review Focus

1. **An admin removes or disables a connection that a deck still has.**
   - Expected: the deck's agent config stays saveable. The frontend PUTs the whole config on every change, so a 422 here would block every later edit.
   - A turn runs without the connection and says `"{name} is no longer available."`.
   - Test owner: Task 3 (save) and Task 6 (turn).
2. **A user not signed in to a U2M service asks for a deck.**
   - Expected: the deck is still built, and chat carries one sign-in notice with a clickable link.
   - Both measured shapes count: the HTTP 401 + `-32006` and the HTTP 200 + JSON-RPC `-32006`.
   - Test owner: Task 1 (mapping), Task 6 (turn), Task 7 (link rendering).
3. **One result carries LakeDraw's `ImageContent` plus `data_base64` of the same PNG.**
   - Expected: exactly one image is saved, and the model text has one reference and no base64.
   - Test owner: Task 4.
4. **A model mistypes an image token's tail, or invents one.**
   - A tail typo is corrected via the unique 12-character-prefix match.
   - An invented token is removed (in HTML, its `<img>` element), and the user is told once.
   - Test owner: Task 5 (helper), Task 6 (wiring).
5. **Two bound connections both expose a tool called `search`.**
   - Expected: both are renamed with a service-slug prefix. Names stay unique, ≤ 64 chars, and match `^[A-Za-z0-9_-]+$`, and calls route to the right service.
   - Test owner: Task 5.

---

### Task 1: Shared MCP transport and the Gateway client

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/services/agent_tools/mcp_transport.py`
- Create: `src/services/agent_tools/gateway_mcp.py`
- Modify: `src/services/agent_tools/genie_one.py`. Import `_UserBearerAuth` and the client builder from `mcp_transport` under their current private names, so the module's public and private surface used by tests is unchanged.
- Create: `tests/fixtures/gateway_mcp/` (copy `web_search_tools_list.json`, `web_search_call.json`, `github_tools_list_rejected.json`, `lakedraw_initialize_not_signed_in.json`)
- Test: `tests/unit/test_gateway_mcp_client.py`

**Interfaces:**
- Produces in `mcp_transport.py`:
  - `class UserBearerAuth(httpx.Auth)`, moved verbatim from `genie_one._UserBearerAuth`.
  - `build_user_mcp_client(host: str, token: str, service_path: str) -> Any`
    - It returns a `DatabricksMCPClient` subclass whose `_call_tools_async` **and** `_get_tools_async` open the session with `UserBearerAuth`. `DatabricksMCPClient` and `WorkspaceClient` are imported inside the function, so tests can monkeypatch the modules.
    - The sync wrappers (`list_tools`/`call_tool`) carry `_handle_mcp_errors`, which re-sends an `initialize` to diagnose errors. Call `asyncio.run(client._get_tools_async())` / `asyncio.run(client._call_tools_async(...))` directly to skip it.
  - `run_with_timeout(fn: Callable[[], T], *, timeout_seconds: float, on_timeout: Callable[[], Exception]) -> T`. It runs in a clean single-worker thread with `shutdown(wait=False)`, Genie One's pattern.
- Produces in `gateway_mcp.py`:
  - `GatewayErrorKind = Literal["sign_in_required", "missing_scope", "access_denied", "not_found", "timeout", "unavailable"]`
  - `class GatewayMcpError(Exception)`, with `__init__(self, kind: GatewayErrorKind, message: str, *, sign_in_url: str | None = None)` and attributes `kind`, `message`, `sign_in_url`.
  - `@dataclass(frozen=True) class GatewayToolSpec`, with `name: str`, `description: str`, `input_schema: dict[str, Any]`.
  - `@dataclass(frozen=True) class GatewayProbe`, with `state: Literal["ready", "sign_in_required", "missing_scope", "access_denied", "not_found", "unavailable"]`, `tools: tuple[GatewayToolSpec, ...]`, `sign_in_url: str | None`, `detail: str | None`.
  - `LIST_TIMEOUT_SECONDS: Final = 30`, `CALL_TIMEOUT_SECONDS: Final = 90`
  - `validate_service_name(name: str) -> str`. It strips and lowercases, matches `^[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+$`, and raises `ValueError` otherwise.
  - `gateway_service_url(host: str, service_name: str) -> str`
  - `sign_in_url(host: str, service_name: str, *, message: str | None = None, workspace_id: str | None = None) -> str`
  - `map_gateway_error(exc: BaseException, *, host: str, service_name: str, lacks_gateway_scope: bool) -> GatewayMcpError`
  - `class GatewayMcpClient`, with:
    - `__init__(self, *, host: str, token: str, service_name: str, token_scopes: frozenset[str] | None = None)`
    - `list_tools(self, *, timeout_seconds: float = LIST_TIMEOUT_SECONDS) -> list[GatewayToolSpec]`
    - `call_tool(self, name: str, arguments: dict[str, Any], *, timeout_seconds: float = CALL_TIMEOUT_SECONDS) -> Any`, which returns the `mcp.types.CallToolResult`. Both raise only `GatewayMcpError`.
  - `probe_service(client: GatewayMcpClient) -> GatewayProbe`, which runs `list_tools` and turns a `GatewayMcpError` into the matching state (`timeout` → `unavailable`).

- [ ] **Step 1: Write the failing tests** (`tests/unit/test_gateway_mcp_client.py`). The error cases build exceptions shaped like the recorded fixtures: an `httpx.HTTPStatusError` with a 401 response whose body is `lakedraw_initialize_not_signed_in.json`'s `body_json`, and an `mcp.shared.exceptions.McpError(ErrorData(code=-32006, message=<github message>))` wrapped in nested `BaseExceptionGroup`s, as the probe saw.
  - `test_validate_service_name_normalises_and_rejects`: `" Main.GTM_ai_tooling.LakeDraw "` gives `"main.gtm_ai_tooling.lakedraw"`; `"a.b"`, `"a.b.c.d"`, `"a.b/c.d"` and `"a b.c.d"` raise `ValueError`.
  - `test_not_signed_in_401_maps_to_sign_in_with_url_from_message`: `kind == "sign_in_required"`, and `sign_in_url` is exactly the URL in the fixture message (`…mcp-service-login?name=db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw&o=7474645249186749`) with no trailing `,`.
  - `test_jsonrpc_32006_in_200_maps_to_sign_in_with_built_url`: the github shape gives `kind == "sign_in_required"` and `sign_in_url == "https://h.example/mcp-service-login?name=system.ai.github"`.
  - `test_sign_in_url_adds_workspace_id_when_known`: `sign_in_url("https://h", "a.b.c", workspace_id="42")` gives `"https://h/mcp-service-login?name=a.b.c&o=42"`.
  - `test_scope_message_maps_to_missing_scope`: an exception whose text is "Provided OAuth token does not have required scopes: ai-gateway" gives `missing_scope`.
  - `test_403_maps_to_access_denied_unless_scopes_lack_gateway`: 403 with `lacks_gateway_scope=False` gives `access_denied`; with `True` it gives `missing_scope`.
  - `test_404_and_server_not_found_map_to_not_found`.
  - `test_timeout_maps_to_timeout`: `call_tool` with a stub that sleeps past `timeout_seconds=0.05` raises `GatewayMcpError(kind="timeout")` within 1 s.
  - `test_list_tools_parses_recorded_web_search`: a fake MCP client returns tools built from `web_search_tools_list.json` and gives one `GatewayToolSpec(name="web_search", input_schema={... "required": ["query"]})`.
  - `test_client_uses_user_bearer_not_oauth_provider`: monkeypatch `databricks_mcp.DatabricksMCPClient` and `databricks.sdk.WorkspaceClient` as `tests/unit/test_genie_one_client.py:808` does. Assert the httpx client was built with `UserBearerAuth` and that the URL is `gateway_service_url(host, service)`.
  - `test_probe_service_states`: each `GatewayMcpError` kind maps to its probe state, and success gives `ready` with the tools.
- [ ] **Step 2: Run, and confirm they fail.** `uv run pytest tests/unit/test_gateway_mcp_client.py -q` → errors (module missing).
- [ ] **Step 3: Implement `mcp_transport.py`,** then point `genie_one.py` at it (keep `_UserBearerAuth`, `_build_mcp_client(host, token)` and `_CALL_TIMEOUT_SECONDS` as names in `genie_one`).
- [ ] **Step 4: Implement `gateway_mcp.py`.** `map_gateway_error` checks these rules in order, over the whole cause/context/group walk; reuse `genie_one`'s `_walk`/`_http_status`/`_error_body` by moving them into `mcp_transport`.
  1. JSON-RPC code `-32006` (an `McpError.error.code`, or `error.code` in a JSON error body) → `sign_in_required`.
  2. A scope message (`is_missing_scope_error` / `mentions_missing_scope`) → `missing_scope`.
  3. Any other 401 → `missing_scope`.
  4. 403 / `PermissionDenied` / denied marker → `missing_scope` if `lacks_gateway_scope`, else `access_denied`.
  5. 404 / `NotFound` / "not found" / "does not exist" → `not_found`.
  6. Else `unavailable`.

  The URL is `re.search(r"https://\S+/mcp-service-login\?\S+", message)` with trailing `.,;)` stripped. `lacks_gateway_scope` is computed in the client from `token_scopes`, with `scopes_grant(scopes, "ai-gateway")` (`src/core/scope_errors.py`).
- [ ] **Step 5: Run the new tests and Genie One's unchanged tests:** `uv run pytest tests/unit/test_gateway_mcp_client.py tests/unit/test_genie_one_client.py tests/unit/test_data_analyst_genie_one.py -q` → all pass.
- [ ] **Step 6: Commit:** `feat(gateway-mcp): shared MCP transport and generic Gateway client with typed errors`.

### Task 2: Registry table, admin API and connection test

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/database/models/gateway_mcp_connection.py`, and export `GatewayMcpConnection` from `src/database/models/__init__.py`.
- Create: `src/services/gateway_mcp_registry.py`
- Create: `src/api/schemas/gateway_mcp.py`
- Create: `src/api/routes/admin_gateway_mcp.py`, and include the router in the app wherever the other `/api/admin` routers are included (`src/api/main.py`).
- Test: `tests/unit/test_gateway_mcp_registry_routes.py`, `tests/integration/test_gateway_mcp_registry_postgres.py`

**Interfaces:**
- Consumes: Task 1's `validate_service_name`, `GatewayMcpClient` and `probe_service`.
- Produces:
  - **Model.** `GatewayMcpConnection` (`__tablename__ = "gateway_mcp_connections"`):
    - `id` Integer PK
    - `service_name` String(255), unique, not null
    - `display_name` String(120), not null
    - `description` Text, null
    - `agent` String(32), not null
    - `instructions` Text, null
    - `tool_allowlist` JSON, null
    - `enabled` Boolean, default True, not null
    - `created_by`, `updated_by` String(255)
    - `created_at`, `updated_at` DateTime (utcnow; `onupdate` on `updated_at`)

    Do **not** put both `index=True` and an `Index(...)` on one column.
  - **Registry** (`gateway_mcp_registry.py`):
    - `@dataclass(frozen=True) class GatewayConnection`, with `id: int`, `service_name: str`, `display_name: str`, `description: str | None`, `agent: Literal["architect", "data_analyst"]`, `instructions: str | None`, `tool_allowlist: tuple[str, ...] | None`, `enabled: bool`, `created_by`, `created_at`, `updated_by`, `updated_at`.
    - `list_connections(db) -> list[GatewayConnection]`
    - `get_by_service(db, service_name: str) -> GatewayConnection | None`
    - `enabled_by_service(db, service_names: Iterable[str]) -> dict[str, GatewayConnection]`
    - `create_connection(db, *, service_name, display_name, description, agent, instructions, tool_allowlist, enabled, user) -> GatewayConnection`, which raises `DuplicateServiceError`.
    - `update_connection(db, connection_id: int, *, display_name, description, agent, instructions, tool_allowlist, enabled, user) -> GatewayConnection`, which raises `ConnectionNotFoundError`.
    - `delete_connection(db, connection_id: int) -> None`, which raises `ConnectionNotFoundError`.
    - `INSTRUCTIONS_MAX_CHARS: Final = 4000`
  - **Schemas** (`src/api/schemas/gateway_mcp.py`):
    - `GatewayConnectionCreate(service_name, display_name, description=None, agent, instructions=None, tool_allowlist=None, enabled=True)`
    - `GatewayConnectionUpdate`: the same fields minus `service_name`, which is rejected if sent (`extra="forbid"`).
    - `GatewayConnectionOut`: every column.
    - `GatewayTestRequest(service_name)`
    - `GatewayStatusOut(state: Literal["ready", "sign_in_required", "missing_scope", "access_denied", "not_found", "unavailable", "not_registered"], message: str | None, sign_in_url: str | None, tools: list[GatewayToolOut])`
    - `GatewayToolOut(name, description)`
    - Validation: `display_name` 1–120 chars after strip; `instructions` ≤ 4000; `tool_allowlist` entries non-empty, deduplicated, order kept; `agent` a Literal.
  - **Routes** (router prefix `/api/admin/gateway-mcp-connections`, `dependencies=[Depends(require_admin)]` from `src/api/routes/_authz.py`):
    - `GET ""` → `list[GatewayConnectionOut]`
    - `POST ""` → 201, or 409 on a duplicate, or 422 on a bad name
    - `PUT "/{connection_id}"` → 404 when the id is missing
    - `DELETE "/{connection_id}"` → 204 / 404
    - `POST "/test"` → `GatewayStatusOut`. It probes **as the calling admin** (`get_user_client()` host and token, `token_scopes=oauth_scopes_from_token(token)`).
    - `created_by`/`updated_by` are the request's user, recorded the way `admin.py`'s Google credentials upload records `uploaded_by`.
- `status_message(state: str, *, display_name: str, service_name: str, detail: str | None, sign_in_url: str | None) -> str | None` is shared with Task 3; put it in `gateway_mcp_registry.py`.

- [ ] **Step 1: Write the failing route tests.** Use FastAPI `TestClient` and the repo's unit DB fixture; check how `tests/unit/test_agent_definition_workbench_routes.py` builds its app and DB. Patch `GatewayMcpClient.list_tools`.
  - `test_create_list_update_delete_round_trip`: names are normalised (`"Main.X.Y"` is stored as `"main.x.y"`); `created_by` is set; an update changes `agent` and `tool_allowlist`, and `updated_at` advances; delete gives 204, and then the connection is absent from `GET`.
  - `test_duplicate_service_is_409`, `test_bad_service_name_is_422`, `test_update_rejects_service_name_field_422`, `test_instructions_over_4000_chars_is_422`.
  - `test_non_admin_gets_403`: override `require_admin` to raise 403; every route answers 403.
  - `test_connection_test_reports_sign_in_with_link`: a patched `list_tools` raising `GatewayMcpError("sign_in_required", ..., sign_in_url=U)` gives `state == "sign_in_required"` and `sign_in_url == U`.
  - `test_connection_test_ready_lists_tools`.
- [ ] **Step 2: Write the failing Postgres test** (`tests/integration/test_gateway_mcp_registry_postgres.py`, using `tests/integration/conftest.py`'s fixtures):
  - `test_table_created_by_init_db_and_unique_service`: after `init_db()` the table exists, and inserting a duplicate `service_name` raises `IntegrityError`.
  - `test_init_db_twice_is_idempotent`.
- [ ] **Step 3: Run, and confirm they fail.** `uv run pytest tests/unit/test_gateway_mcp_registry_routes.py -q`; for the Postgres test, see the `local-postgres-tests` memory: `pg_ctl` start, default URL.
- [ ] **Step 4: Implement** the model, registry, schemas and routes.
- [ ] **Step 5: Run Task 2's tests plus `tests/unit/test_agent_definition_workbench_routes.py`** (it pins route counts; only its own router's routes must be unaffected) → pass.
- [ ] **Step 6: Commit:** `feat(gateway-mcp): connection registry table and admin API with connection test`.

### Task 3: The `gateway_mcp` tool entry, saving, discovery union and user status

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/api/schemas/agent_config.py`: add a `GatewayMcpTool` model, add it to the `ToolEntry` union, and give `no_duplicate_tools` the key `f"gateway_mcp:{service_name}"`.
- Modify: `src/api/routes/agent_config.py`: the remove-by-key `_key` in `patch_tools` (around lines 275–298), and the gateway check in the save paths (below).
- Modify: `src/api/routes/tools.py`: add `gateway_items` to `_discover_mcp_connections`, and the new status route.
- Test: `tests/unit/test_agent_config_gateway_mcp.py`, `tests/unit/test_tools_discovery_gateway_mcp.py`

**Interfaces:**
- Consumes: Task 2's registry (`enabled_by_service`, `get_by_service`, `status_message`) and Task 1's `probe_service`.
- Produces:
  - `class GatewayMcpTool(BaseModel)`: `type: Literal["gateway_mcp"]`, `service_name: str` (validated with `validate_service_name`), `display_name: str` (1–120).
  - `GET /api/tools/discover/mcp`. The response is unchanged, plus `gateway_items: list[{service_name, display_name, description, agent}]` holding the enabled rows only. It is present even when UC listing fails, in which case `error` and `error_code` are kept.
  - `GET /api/tools/gateway-mcp/status?service_name=...` → `GatewayStatusOut`. It returns `not_registered` when the service is missing or disabled. Otherwise it probes as the calling user and applies the allowlist to `tools`; `message` comes from `status_message`.
- **Save rule:** in `put_agent_config` and `patch_tools`, a `gateway_mcp` entry is refused with 422 (`"gateway connection <service> is not available"`) **only if it is not already in the stored config** and its service is not registered and enabled. Entries already stored are kept, even if their connection is gone.

- [ ] **Step 1: Write the failing tests.**
  - `test_gateway_entry_round_trips_and_duplicates_rejected`: two entries with the same service fail `AgentConfig.model_validate`; one entry round-trips through `sanitize_agent_config_for_persist` unchanged.
  - `test_put_rejects_new_unregistered_gateway_entry_422`.
  - `test_put_keeps_already_stored_entry_after_connection_deleted`: store an entry while it is registered, delete the registry row, then PUT the same config plus an unrelated change → 200, and the entry is still stored. (Review Focus 1.)
  - `test_patch_remove_gateway_entry_by_key`: PATCH-removing the entry removes it. A wrong `_key` would leave it, which is what this guards.
  - `test_discover_mcp_includes_enabled_gateway_items_only`: a disabled row is absent; the `items` shape is unchanged.
  - `test_discover_mcp_gateway_items_survive_uc_scope_error`: `connections.list` raises the missing-scope error, and the response has `error_code == "missing_scope"` **and** a non-empty `gateway_items`.
  - `test_status_not_registered_for_disabled`, `test_status_sign_in_required_has_link_and_message`, `test_status_ready_applies_allowlist`.
  - `test_legacy_build_tools_ignores_gateway_entry`: `src/services/agent_resolution.py` `_build_tools` with a `gateway_mcp` entry builds no tool and raises nothing.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** Task 3's tests and `tests/unit/test_agent_config_genie_one.py tests/unit/test_tools_discovery_mcp_errors.py -q` → pass.
- [ ] **Step 5: Commit:** `feat(gateway-mcp): gateway_mcp tool entry, discovery union and per-user status`.

### Task 4: The Gateway agent tool: result shaping, image saving, raw-schema binding

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/services/agent_tools/gateway_tool.py`
- Modify: `src/services/agent_runtime.py`: in `_tool_definition`, use `tool.parameters_json_schema` when the tool has one; make `_NOT_RUN_TEXT` generic.
- Test: `tests/unit/test_gateway_agent_tool.py`. Add one test to `tests/unit/test_agent_runtime_tool_loop.py`, and update its pinned `_NOT_RUN_TEXT` assertion if there is one, which is the only permitted edit there.
- Fixtures: `tests/fixtures/gateway_mcp/lakedraw_export_doc.json` and `lakedraw_persist_doc.json`, doc-sourced and marked `"_source": "doc"`.
  - **Export:** a `CallToolResult` with one `image` block (a real 4×3 PNG, base64) and one `text` block. The text is JSON with `diagram_id`, `format: "png"` and `data_base64` set to the same PNG.
  - **Persist:** a text block, JSON with `diagram_id`, `diagram_url`, `version`.

**Interfaces:**
- Consumes: Task 1's `GatewayMcpClient`, `GatewayToolSpec`, `GatewayMcpError`, `CALL_TIMEOUT_SECONDS`; the `AgentTool` protocol and `ToolAccessError` (`src/services/agent_tools/toolset.py`); `spotlight`.
- Produces:
  - `ImageSaver = Callable[[bytes, str], str]`: `(data, mime) -> token`.
  - `@dataclass(frozen=True) class GatewayToolContext`, with `display_name: str`, `service_name: str`, `client: GatewayMcpClient`, `save_image: ImageSaver`, `on_call: Callable[[str], None]`, `session_id: str | None`.
  - `class GatewayMcpAgentTool`:
    - `__init__(self, spec: GatewayToolSpec, ctx: GatewayToolContext, *, model_name: str, description_prefix: str | None)`
    - attributes `name` (= `model_name`), `description`, `args_schema` (= `GatewayArgs`, a `BaseModel` with `model_config = ConfigDict(extra="allow")`), `parameters_json_schema: dict`, `saved_tokens: list[str]`
    - `run(self, args, *, remaining_seconds: float) -> str`
  - `shape_result(result: Any, *, save_image: ImageSaver) -> tuple[str, list[str]]`: the model text (unspotlighted) and the saved tokens.
  - `make_image_saver(*, user: str, service_name: str, display_name: str) -> ImageSaver`. It saves through `image_service.upload_image(db, data, filename, mime, user, tags=["gateway_mcp", service_name], category="content")` inside `get_db_session()`. The filename is `f"{slug(display_name)}-{UTC %Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.{ext}"`.
  - `GATEWAY_OUTPUT_CAP_CHARS: Final = 32000`
- **Behaviour** (from the spec):
  - **Description:** `f"{display_name}: {instructions}\n\n{tool description}"`, or `f"{display_name}: {tool description}"` when there are no instructions.
  - **`parameters_json_schema`:** the MCP `inputSchema` verbatim, minus a top-level `$schema`. A missing `type` defaults to `"object"`.
  - **`run`:**
    1. Call `on_call(f"{display_name} · {spec.name}")` first; a failure there is logged and ignored.
    2. Call `client.call_tool(spec.name, args.model_dump(), timeout_seconds=min(CALL_TIMEOUT_SECONDS, remaining_seconds))`.
    3. `GatewayMcpError` kinds `sign_in_required`, `missing_scope` and `access_denied` raise `ToolAccessError(kind, name, message, sign_in_url=...)`.
       - Extend `ToolAccessKind` (`src/services/agent_tools/toolset.py`) with `"sign_in_required"`.
       - Change `ToolAccessError.__init__` to `(self, kind, tool_name, message, *, sign_in_url: str | None = None)`. Genie One's callers are unchanged.
    4. Other kinds return `spotlight(display_name, f"{display_name} could not run {spec.name}: {message}")`.
    5. On success, return `spotlight(display_name, capped(shape_result(...)[0]))`, where the cap is `GATEWAY_OUTPUT_CAP_CHARS` and a truncated result ends `"\n[truncated: N more characters]"`.
  - **`shape_result`:**
    - Join the text blocks; if there are none and `structuredContent` is set, use `json.dumps(structuredContent)`.
    - `image` blocks with mime `image/png|jpeg|gif|svg+xml` are decoded and saved.
    - In any JSON text or `structuredContent`, every key ending in `base64` (case-insensitive) is removed. If its value decodes to one of those image types (check magic bytes, or `<svg`), it is saved, unless its SHA-256 matches an image already saved from this result.
    - Each saved image appends the exact "Image saved: …" line.
    - An image over 5 MB, or one that fails to decode, appends `"[image not saved: <reason>]"`.
    - Other block types append `"[<type> content omitted]"`.
    - `isError` prefixes `"Tool error: "`.
- `_NOT_RUN_TEXT` becomes `"Not run: call one tool at a time. Read the previous result first, then call again if you still need this."`

- [ ] **Step 1: Write the failing tests.**
  - `test_lakedraw_export_saves_one_image_and_strips_base64`: using the export fixture and a recording saver, exactly one save; the model text contains `{{image:TOK}}` once and does not contain the fixture's base64 string or the substring `"data_base64"`. (Review Focus 3.)
  - `test_persist_result_text_keeps_diagram_url`: the persist fixture text keeps `diagram_url`.
  - `test_structured_only_result_is_dumped`, `test_other_block_types_are_noted`, `test_is_error_prefix`, `test_oversize_image_not_saved_and_reported` (a 6 MB fake PNG header plus padding).
  - `test_output_is_spotlighted_and_capped`: a 50,000-character text result is wrapped in `<untrusted-data source="LakeDraw">`, its body is ≤ 32,000 + trailer, and it ends with the truncation note.
  - `test_sign_in_error_raises_tool_access_error_with_url`, `test_unavailable_error_answers_in_band`.
  - `test_progress_line_called_before_call_and_failure_ignored`.
  - `test_description_prefix_and_raw_schema`: `parameters_json_schema` equals the input schema minus `$schema`, with nested `diagram_data` intact.
  - `test_tool_definition_uses_raw_schema` (in `test_agent_runtime_tool_loop.py`): `_tool_definition(GatewayMcpAgentTool(...))["function"]["parameters"]` is the raw schema; a Genie One tool's definition is unchanged.
  - `test_extra_allow_args_reach_the_service`: `_answer_tool_call` with nested args passes them to `call_tool` unchanged.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** Task 4's tests and `tests/unit/test_agent_runtime_tool_loop.py tests/unit/test_agent_runtime.py -q` → pass.
- [ ] **Step 5: Commit:** `feat(gateway-mcp): generic Gateway agent tool with image capture and raw-schema binding`.

### Task 5: Toolset building, name collisions, per-turn budget, and image-reference reconciliation

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/services/agent_tools/gateway_toolset.py`
- Create: `src/utils/image_refs.py`
- Test: `tests/unit/test_gateway_toolset.py`, `tests/unit/test_image_refs.py`

**Interfaces:**
- Consumes: Tasks 1, 2 and 4.
- Produces in `gateway_toolset.py`:
  - `@dataclass(frozen=True) class GatewayFailure`, with `display_name: str`, `service_name: str`, `kind: Literal["sign_in_required", "missing_scope", "access_denied", "not_found", "unavailable", "removed"]`, `message: str | None`, `sign_in_url: str | None`.
  - `@dataclass class GatewayToolsetBuild`, with `tools: tuple[GatewayMcpAgentTool, ...]`, `failures: tuple[GatewayFailure, ...]`.
    - `saved_tokens(self) -> list[str]` (the union over its tools)
    - `access_failures(self, toolset: AgentToolset) -> list[GatewayFailure]`, which converts the `ToolAccessError`s recorded during the run.
  - `build_gateway_tools(entries: Sequence[GatewayMcpTool], *, agent: Literal["architect", "data_analyst"], registry: Mapping[str, GatewayConnection], host: str, token: str, user: str, on_call: Callable[[str], None], session_id: str | None, client_factory: Callable[..., GatewayMcpClient] = GatewayMcpClient) -> GatewayToolsetBuild`
    - It lists the services in parallel (a `ThreadPoolExecutor` with one worker per connection) and applies each connection's allowlist.
    - An entry whose registry row is missing or disabled is a `removed` failure, but **only for its own agent**: an entry whose row exists with a different `agent` is silently skipped. A row-less entry is reported by the architect pass only, so the user isn't told twice.
  - `model_tool_names(specs_by_service: Mapping[str, Sequence[str]]) -> dict[tuple[str, str], str]`
    - A tool keeps its own name if it is unique across the bound services. Otherwise it becomes `f"{slug}__{tool}"`, where `slug` is the service's last part, made unique by adding the schema part when needed.
    - Every name is truncated to 64 characters and sanitised to `[A-Za-z0-9_-]`. A post-truncation clash is resolved by suffixing `_2`, `_3` and so on.
  - `turn_budget(*, used_calls: int, used_seconds: float, max_calls: int, budget_seconds: float, turn_started_at: float | None, now: float, deadline_seconds: float = GATEWAY_TURN_DEADLINE_SECONDS) -> tuple[int, float]`, returning (calls left, seconds left), never negative. With no `turn_started_at` the deadline doesn't apply.
  - The constants `ARCHITECT_GATEWAY_MAX_CALLS = 12`, `ARCHITECT_GATEWAY_BUDGET_SECONDS = 360.0`, `ANALYST_GATEWAY_MAX_CALLS = 6`, `ANALYST_GATEWAY_BUDGET_SECONDS = 300.0`, `GATEWAY_TURN_DEADLINE_SECONDS = 700.0`.
  - `failure_notice(failure: GatewayFailure, *, oauth_client_id: str | None) -> str`, which returns the exact Global Constraints copy for each kind (`missing_scope` → `consent_message(...)`).
- Produces in `image_refs.py`:
  - `IMAGE_REF_RE` (`\{\{image:([A-Za-z0-9_-]+)\}\}`)
  - `reconcile_text(text: str, known: Collection[str]) -> tuple[str, list[str]]`: the fixed text and the removed refs. Known refs are kept. An unknown ref with exactly one known token sharing its first 12 characters is replaced by that token. Otherwise the placeholder is removed.
  - `reconcile_html(html: str, known: Collection[str]) -> tuple[str, list[str]]`: the same, except a removed ref takes its whole `<img …>` element with it, or, inside a `url('…')`, the whole `background-image` declaration.
  - `refs_in(obj: Any) -> set[str]`: every ref in any string inside a nested dict/list.
  - `reconcile_model_strings(obj: Any, known: Collection[str]) -> tuple[Any, list[str]]`: walks dicts and lists and applies `reconcile_text` to every string.

- [ ] **Step 1: Write the failing tests.**
  - `test_two_connections_both_exposing_search_are_prefixed_and_route_correctly`: two fake services each list `search`; the model names differ, both match `^[A-Za-z0-9_-]{1,64}$`, and calling each runs the right fake client. (Review Focus 5.)
  - `test_unique_names_are_kept`, `test_long_names_truncated_and_deduplicated`.
  - `test_allowlist_filters_tools`, `test_wrong_agent_entries_skipped`.
  - `test_removed_connection_reported_once_by_architect`.
  - `test_sign_in_at_list_time_becomes_failure_with_url_and_other_connection_still_binds`.
  - `test_turn_budget_shares_calls_and_clips_to_deadline`:
    - `turn_budget(used_calls=10, used_seconds=100, max_calls=12, budget_seconds=360, turn_started_at=0, now=650)` → `(2, 50.0)`;
    - with `now=710` → `(2, 0.0)`;
    - with `turn_started_at=None` → `(2, 260.0)`.
  - `test_failure_notice_copy_exact`: each kind gives the exact copy string.
  - `test_reconcile_keeps_known_fixes_tail_typo_removes_invented`: for a known 43-character token T, `{{image:T}}` is kept; `{{image:T[:40]+"xyz"}}` becomes T; `{{image:ZZZZ…}}` is removed and reported. (Review Focus 4.)
  - `test_reconcile_ambiguous_prefix_removes`: two known tokens share a 12-character prefix, and an unknown ref with that prefix is removed.
  - `test_reconcile_html_drops_img_element_and_background_decl`.
  - `test_reconcile_model_strings_walks_nested`.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit:** `feat(gateway-mcp): toolset building, name collisions, per-turn budget, image-reference reconciliation`.

### Task 6: Wire it into the graph: architect, analyst, builder, chat

**Models:** test=opus impl=opus

**Files:**
- Modify: `src/services/graph/state.py`: add `gateway_usage` and `gateway_images` as `Annotated[Any, turn_scoped_concat]`, registered in `_EMPTY_FOR` as `[]`; add `turn_started_at: float`, a plain replace key.
- Modify: `src/services/graph/builder.py`: `invoke_graph` writes `"turn_started_at": time.time()` into both input dicts that set `turn_id` (around lines 355 and 376).
- Modify: `src/services/graph/nodes.py`:
  - `architect_node` (around 3417; the runtime call around 3618)
  - `data_analyst_node` / `_genie_one_run` (around 4288–4610)
  - `builder_node` (around 4895, right after `strip_inter_tag_escapes`)
- Modify: `src/services/agent_tools/registry.py`: `build_analyst_toolset(..., extra_tools: Sequence[AgentTool] = ())`. With extra tools, the toolset uses `ANALYST_GATEWAY_MAX_CALLS` / `ANALYST_GATEWAY_BUDGET_SECONDS`; without them, the Genie One values exactly as today.
- Test: `tests/unit/test_graph_gateway_mcp.py`

**Interfaces:**
- Consumes: everything above. `_say(state, text, message_type="info")` and `_emit(...)` for progress; copy `on_question` in `_genie_one_run` (around 4330–4355) for the progress row shape.
- **Behaviour:**
  - **Inputs, captured in the node thread:**
    - the actor's `agent_config` (from `state["actor_session_id"]`, as `_genie_one_run` reads it);
    - the user's host and token (`get_user_client()`; no client means no Gateway tools);
    - the user name (`image_service.resolve_requesting_user()`);
    - the registry, `enabled_by_service` over the entries' service names (rows for disabled services are absent).
  - **Architect:**
    - With at least one architect Gateway tool and a budget left (`turn_budget` over this turn's `gateway_usage` entries where `agent == "architect"`), every attempt passes `_assembly_context(..., toolset=AgentToolset(tools, max_calls=calls_left, budget_seconds=seconds_left))`. The retry attempt gets a new `AgentToolset` built from the remaining budget after attempt 1.
    - Otherwise the call is exactly today's (no toolset).
    - After the run:
      1. Reconcile image refs in the output (`reconcile_model_strings` over the `ArchitectOutput` dict). Known refs are the tokens saved this turn (this run plus `gateway_images`) and `refs_in(current deck spec)`. Re-validate the output.
      2. Say one notice per failure (list-time and run-time, once per service per turn), and one "couldn't be placed on slide {n}" per affected slide position.
      3. Return `gateway_usage: scoped(turn_id, [{"agent": "architect", "calls": n, "seconds": s}])` and `gateway_images: scoped(turn_id, saved_tokens)`.
  - **Analyst:**
    - Analyst Gateway tools are built the same way and passed as `extra_tools`.
    - With Gateway tools but no Genie One entry, the analyst runs a loop over the Gateway tools alone (`AgentToolset(tools, ANALYST_GATEWAY_MAX_CALLS, ANALYST_GATEWAY_BUDGET_SECONDS)`, clipped by the deadline). Figures stay code-built from Genie One only.
    - Failures get the same notices.
  - **Builder:** `reconcile_html(html, refs_in(<this slide's spec dict from the payload>))`. A removal says the "couldn't be placed on slide {n}" notice, once per slide.
  - **Chat:** progress uses the same `tool_call` row/event mechanism as Genie One, with `metadata.tool_name = "gateway_mcp"`.

- [ ] **Step 1: Write the failing tests** (`tests/unit/test_graph_gateway_mcp.py`). Stub `get_agent_runtime().run`, the registry and `GatewayMcpClient`, following `tests/unit/test_data_analyst_genie_one.py`'s fixtures.
  - `test_architect_without_gateway_entries_runs_without_toolset`: the assembly context's `toolset is None`, byte-identical to today's call.
  - `test_architect_binds_gateway_tools_and_records_usage`.
  - `test_architect_retry_shares_turn_budget`: attempt 1 uses 10 calls, so attempt 2's toolset has `max_calls == 2`.
  - `test_second_architect_pass_in_turn_sees_prior_usage`: `gateway_usage` already holds 12 architect calls, so there is no toolset.
  - `test_deadline_guard_no_toolset_after_700s`: `turn_started_at = now - 701`.
  - `test_sign_in_failure_says_notice_and_turn_continues`: the info message equals `"To use LakeDraw, sign in here: <url> — then ask again."` and the architect still returns its output. (Review Focus 2.)
  - `test_removed_connection_says_no_longer_available`. (Review Focus 1.)
  - `test_architect_output_image_refs_reconciled_and_user_told`: an output brief with a tail-typo token is corrected; an invented one is removed, with exactly one notice naming the slide position.
  - `test_builder_html_unknown_image_removed_and_known_kept`.
  - `test_analyst_with_genie_only_unchanged_budget`: `max_calls == 3`.
  - `test_analyst_with_gateway_tools_uses_6_calls`.
  - `test_analyst_gateway_only_runs_loop`.
  - `test_turn_started_at_written_by_invoke_graph`.
  - `test_progress_row_written_per_call`: the row text is `"LakeDraw · lakedraw_create_from_spec"`.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the graph and Genie suites:**
  `uv run pytest tests/unit/test_graph_gateway_mcp.py tests/unit/test_data_analyst_genie_one.py tests/unit/test_graph_nodes.py tests/unit/test_graph_state.py tests/unit/test_agent_runtime_tool_loop.py -q` → pass.
- [ ] **Step 5: Commit:** `feat(gateway-mcp): bind Gateway tools to the architect and analyst, reconcile image refs, chat notices`.

### Task 7: Frontend — deck picker, chip states, chat links

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `frontend/src/types/agentConfig.ts`: add `GatewayMcpTool` to `ToolEntry`/`ToolType`, and to `TOOL_TYPE_LABELS` (`'AI Gateway MCP'`), `TOOL_TYPE_BADGE_LABELS` (`'Gateway'`) and `TOOL_TYPE_COLORS`.
- Modify: `frontend/src/services/api.ts`: `discoverMCPConnections()` also returns `gateway_items`; add `getGatewayMcpStatus(serviceName: string): Promise<GatewayMcpStatus>`.
- Modify: `frontend/src/components/AgentConfigBar/tools/MCPDiscovery.tsx`: an "AI Gateway" group first, then the UC group. The search filters both. A Gateway item's preview has `toolType: 'gateway_mcp'`.
- Modify: `frontend/src/components/AgentConfigBar/ToolDetailPanel.tsx`: a `gateway_mcp` preview (display name, service name, agent, description).
- Modify: `frontend/src/components/AgentConfigBar/toolUtils.ts`, `AgentConfigBar.tsx` (`ToolChip`, `handleEditChip`) and `frontend/src/contexts/AgentConfigContext.tsx` (the `addTool`/`removeTool`/`updateToolEntry` switches, around 945–1010): handle `gateway_mcp` in every switch.
- Create: `frontend/src/utils/linkify.tsx`, then use it in `frontend/src/components/ChatPanel/Message.tsx` wherever assistant or info text is rendered as plain text.
- Test: `frontend/src/components/AgentConfigBar/tools/MCPDiscovery.gateway.test.tsx`, `frontend/src/components/AgentConfigBar/GatewayChip.test.tsx`, `frontend/src/utils/linkify.test.tsx`

**Interfaces:**
- Consumes: Task 3's response shapes.
- Produces:
  - `interface GatewayMcpTool { type: 'gateway_mcp'; service_name: string; display_name: string }`
  - `interface GatewayItem { service_name: string; display_name: string; description: string | null; agent: 'architect' | 'data_analyst' }`
  - `type GatewayMcpState = 'ready' | 'sign_in_required' | 'missing_scope' | 'access_denied' | 'not_found' | 'unavailable' | 'not_registered'`
  - `interface GatewayMcpStatus { state: GatewayMcpState; message: string | null; sign_in_url: string | null; tools: { name: string; description: string }[] }`
  - `linkifyText(text: string): React.ReactNode[]`. It turns `https://` URLs into `<a href target="_blank" rel="noopener noreferrer">`. Trailing `.,;)` is not part of the link. No other HTML is produced.
- **Chip:**
  - The label is the display name.
  - Legacy decks get the suffix `" · agent mode only"`, as `genie_one` does.
  - Agent decks fetch the status on mount:
    - `sign_in_required` shows a `"Sign in to {name}"` link (new tab), plus a `"Check again"` button that re-fetches;
    - `access_denied`, `missing_scope`, `not_found` and `unavailable` show the `message` in a tooltip and a muted style;
    - `not_registered` shows `"unavailable"`.

- [ ] **Step 1: Write the failing vitest tests.**
  - `MCPDiscovery.gateway.test.tsx`:
    - Gateway items render under "AI Gateway" before the UC items.
    - The search filters both groups.
    - Picking a Gateway item calls `onPreview` with `toolType: 'gateway_mcp'` and the service name.
    - The UC `error` message still renders while Gateway items show.
  - `GatewayChip.test.tsx`:
    - a mocked `sign_in_required` status renders a link to `sign_in_url` with `target="_blank"`;
    - "Check again" re-fetches;
    - a legacy deck shows "agent mode only" and makes no status call.
  - `linkify.test.tsx`: the sign-in sentence becomes one anchor whose href ends `&o=7474645249186749`; trailing punctuation stays outside the link; `javascript:` and `http://` stay plain text.
  - `Message.test.tsx`: add `info message with a URL renders an anchor`.
- [ ] **Step 2: Run, and confirm they fail.** `cd frontend && npx vitest run <files>`. Node 26 breaks some unrelated SlideViewer tests locally; CI uses Node 20, so judge only these files.
- [ ] **Step 3: Implement.** `npx tsc --noEmit` must pass, since the exhaustive switches catch a missing case.
- [ ] **Step 4: Run these tests plus `ToolPicker.test.tsx MCPDiscovery.test.tsx Message.test.tsx`** → pass; `npx tsc --noEmit` → clean.
- [ ] **Step 5: Commit:** `feat(gateway-mcp): deck picker AI Gateway group, chip sign-in state, chat links`.

### Task 8: Frontend — Admin "Connections" tab

**Models:** test=sonnet impl=sonnet

**Files:**
- Create: `frontend/src/components/Admin/AdminConnections.tsx`
- Modify: `frontend/src/components/Admin/AdminPage.tsx`: add `'connections'` to `TabId`, a tab button "Connections", and a `role="tabpanel"` panel, following the existing tab pattern there.
- Modify: `frontend/src/services/api.ts`: `listGatewayConnections()`, `createGatewayConnection(body)`, `updateGatewayConnection(id, body)`, `deleteGatewayConnection(id)`, `testGatewayConnection(serviceName): Promise<GatewayMcpStatus>`.
- Test: `frontend/src/components/Admin/AdminConnections.test.tsx`

**Interfaces:**
- Consumes: Task 2's routes and schemas, and Task 7's `GatewayMcpStatus`.
- **Behaviour:**
  - **The table** shows display name, service name, agent ("Architect" / "Data analyst"), enabled, and an allowlist summary ("All tools" or "N tools").
  - **"Add connection"** opens the form:
    - service name (read-only when editing), display name, description;
    - agent (radio, default Architect);
    - instructions (textarea, with a 4,000-character counter).
  - **"Test connection"** shows:
    - the tools as checkboxes, all checked by default, where unchecking builds `tool_allowlist` (all checked means `null`);
    - or the sign-in link, opening in a new tab, with the message;
    - or the error message.
  - **Save:** 409 and 422 errors show inline. Saving is allowed without a passing test.
  - **Enable toggle and Delete:** Delete asks for confirmation first.
  - **Help panel:** a collapsed "How to create the service in Databricks" panel, holding the spec's "Rollout" step 1 as text (API body and grants), with the LakeDraw values as the example.

- [ ] **Step 1: Write the failing tests:**
  - the list renders the rows;
  - an add-with-test flow posts `tool_allowlist` equal to the checked subset;
  - all checked posts `null`;
  - a 409 shows inline;
  - delete asks for confirmation;
  - editing disables the service name;
  - a sign-in test result renders a link.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these tests plus the existing `AdminPage` tests → pass; `npx tsc --noEmit` clean.
- [ ] **Step 5: Commit:** `feat(gateway-mcp): Admin Connections tab`.

### Task 9: Admin how-to doc and the full-suite check

**Models:** test=sonnet impl=sonnet

**Files:**
- Create: `docs/technical/gateway-mcp-connections.md`. It covers:
  - what a Gateway connection is;
  - the UC-side steps (the spec's Rollout step 1, verbatim values) and the scope check;
  - the Tellr Admin → Connections steps;
  - user sign-in;
  - the LakeDraw example, with the recommended instructions below.
- Modify: add a link from `docs/technical/` index or README, if one lists technical docs.

**Recommended LakeDraw instructions** (copy into the doc; the morning hand-over uses them too):

> Use LakeDraw when the user asks for an architecture, data-flow or system diagram, or a slide clearly needs one. Steps: call lakedraw_list_node_types once (mode "architecture") to learn valid node types; call lakedraw_create_from_spec with phase "validate"; fix any issues and validate again; then call it with phase "persist", the validation_digest, a new client_create_id (a fresh UUID), and response_detail "compact"; then call lakedraw_export_diagram with format "png". Put the returned {{image:…}} reference in that slide's content_brief, and add "Edit in LakeDraw: <diagram_url>" to the brief so the slide links to it. Record "LakeDraw diagram_id: <id>" in the slide's hands_off so later turns can re-export it. At most 100 nodes and 100 edges. Do not use lakedraw_edit_diagram; to change a diagram, create a new one from an updated spec.

Recommended allowlist: `lakedraw_list_node_types`, `lakedraw_create_from_spec`, `lakedraw_export_diagram`, `lakedraw_get_diagram`.

- [ ] **Step 1: Write the doc.**
- [ ] **Step 2: Run the whole Python unit suite:** `uv run pytest tests/unit -q -p no:cacheprovider`. Compare failure **causes** with the baseline recorded before Task 1 (executing-plans-tellr §3). New causes are a defect; fix them, or ledger them with the reason.
- [ ] **Step 3: Run the frontend checks:** `cd frontend && npx tsc --noEmit && npx vitest run` (judge Node-26 SlideViewer failures against the baseline).
- [ ] **Step 4: Commit:** `docs(gateway-mcp): admin how-to for AI Gateway MCP connections (LakeDraw example)`.
