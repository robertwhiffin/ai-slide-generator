# AI Gateway MCP connections — design

**Date:** 2026-11-02
**Status:** written for an overnight autonomous build. The owner set the direction (below) and asked
me to answer the brainstorm with my own defaults. Every call I made is listed under "Calls made
without the owner"; the overnight decision log is `~/tellr-loop/mcp-connections/DECISIONS.md`.
**Builds on:** Genie One in agent mode (`2026-10-29-genie-one-agent-mode-design.md`, PR #354), whose
gateway client, tool loop and scope handling this generalises.
**Background:** the LakeDraw integration doc ("Tellr × LakeDraw: Using LakeDraw as Tellr's diagram
backend (per-user U2M)", Jitesh Soni, 2026-10-30). Probe scripts: `~/tellr-loop/mcp-connections/probes/`.

## Why

Databricks AI Gateway serves MCP services at `{host}/ai-gateway/mcp-services/<catalog>.<schema>.<service>`.
Some are built in (`system.ai.web_search`, `system.ai.github`, `system.ai.genie_one_mcp`, …); admins
can register their own on top of a Unity Catalog HTTP connection. Tellr only knows one of them, Genie
One, and that one is hard-coded.

The deck's "MCP Server" picker lists only UC HTTP connections (legacy transport
`/api/2.0/mcp/external/{connection}`), and only legacy mode can use them. Tellr cannot list Gateway
services for the user: every MCP-service API lives under `/api/2.1/unity-catalog/` and needs the
`unity-catalog` scope, which Databricks Apps refuses. Calling a service with the user's token works,
needing only `ai-gateway`; that is how Genie One runs.

The first service to connect is **LakeDraw**, a diagram app. It is registered on Logfood as
`main.gtm_ai_tooling.lakedraw`, behind a per-user OAuth (U2M) connection. Its tools build an
architecture diagram from a node/edge spec, save it under the user's own LakeDraw account, and export
it as a PNG. It belongs to the **architect**: a diagram is part of planning a slide, not a data fetch.

## What the owner asked for

- An **admin-only page** for manually creating Gateway MCP connections: "a way of manually creating
  the Genie One–type connection". It must be **general-purpose and reusable**, not LakeDraw-specific.
- **Keep the current MCP Server button.** Its list becomes the union of today's UC connections and
  the Gateway connections the admin registered. *Superseded 2026-11-03:* the owner asked for
  "genie one, (any connections created by admin)" as pills, with "all other existing pills
  wrapped into an 'other tools' expandable button".
- LakeDraw goes **into the architect, not the data analyst**.
- Morning deliverable: a devloop instance link and instructions for creating a LakeDraw connection.

## Goals

- **Admin registers a service.** On a new "Connections" tab of the Admin page, an admin types a
  Gateway service's full name and gives it:
  - a display name and a user-facing description;
  - the agent that uses it (Architect or Data analyst);
  - optional instructions for that agent;
  - an optional allowlist of its tools.

  "Test connection" lists the service's tools as the admin, or says why it can't.
- **User adds it to a deck** from its own pill in the Tools row (owner's direction, 2026-11-03; this
  replaces the union in the MCP Server picker).
- **Agent mode uses it as the user.** The bound agent calls the service's tools in its tool loop with
  the signed-in user's token, never the service principal's.
- **Per-user sign-in is handled.** Services behind U2M connections (LakeDraw, GitHub, Slack, Google
  Drive) need each user to sign in once at `{host}/mcp-service-login?name=<service>`. Tellr detects
  "not signed in" and shows the user that link: on the deck's chip, and in chat when a turn needs it.
- **Images reach slides.** When a tool returns an image (MCP `ImageContent`, or a base64 field such as
  LakeDraw's `data_base64`), Tellr saves it as a Tellr image and gives the model a `{{image:TOKEN}}`
  reference. The architect puts that reference in the slide brief, and the builder's existing IMAGE
  RULES embed it.
- **Decks that don't use it don't change.** Genie One–only decks, legacy decks and decks with no
  Gateway connection behave exactly as today. No agent prompt changes.

## Non-goals

- Creating, editing or deleting UC connections or MCP services from Tellr. The admin does that in
  Databricks (SQL or Catalog Explorer). Tellr registers an existing service.
- Listing Gateway services automatically. The user token can't, so the admin types the name.
- Legacy mode. Legacy decks ignore Gateway connections, and the chip says "agent mode only".
- Binding to the builder, fixer or reviewers.
- Tellr-side per-connection permissions. Unity Catalog's `EXECUTE` grant on the service decides who
  can use it; Tellr reports a denial in plain words.
- A slide-level "refresh diagram" button, async progress UI for slow tools, or any LakeDraw-specific
  code. LakeDraw specifics live in the admin's instructions for that connection.
- Changing how the existing UC-connection MCP tool works.

## Anti-goals (failures even if it "works")

- A sign-in or permission failure that looks like "no diagram" or silence. The user must be told
  what happened and how to fix it.
- Base64 image data in the model's context.
- A slide with a broken image because a model mistyped an image token.
- A tool running as the service principal.
- Following instructions embedded in a tool's output.
- A deck turn killed by the job timeout because a tool was slow.
- Any behaviour change for a deck with no Gateway connection.

## How it works

### The registry

A new table, `gateway_mcp_connections`, one row per registered service:

| column | notes |
|---|---|
| `id` | integer PK |
| `service_name` | `catalog.schema.service`, unique, **immutable** after creation |
| `display_name` | e.g. "LakeDraw"; shown on chips, picker, progress and chat messages |
| `description` | user-facing, optional |
| `agent` | `architect` or `data_analyst` |
| `instructions` | optional, ≤ 4,000 chars; model-facing guidance (see "Guidance") |
| `tool_allowlist` | JSON list of tool names, or null for "all tools" |
| `enabled` | bool, default true |
| `created_by`, `created_at`, `updated_by`, `updated_at` | audit |

`service_name` must match three dot-separated UC identifier parts (letters, digits, `_`, `-`).
Saving does not require a passing test: the admin may not be signed in or granted.

### Admin API and page

- `/api/admin/gateway-mcp-connections`: list, create, update, delete, all behind the existing
  `require_admin` dependency (`src/api/routes/_authz.py`).
- `POST /api/admin/gateway-mcp-connections/test {service_name}` runs `tools/list` **as the admin**.
  It returns one of these states, plus the tool names and descriptions, the sign-in link, and a
  plain-words message:
  - `ready`
  - `sign_in_required`
  - `access_denied`
  - `missing_scope`
  - `not_found`
  - `unavailable`
- The Admin page (`frontend/src/components/Admin/AdminPage.tsx`) gains a **Connections** tab. It has:
  - a table of connections showing name, service, agent, enabled and allowlist count;
  - add and edit forms (the service name is read-only on edit);
  - enable/disable and delete, with a confirm on delete;
  - "Test connection", which shows the tool list as checkboxes for the allowlist, or the sign-in
    link or error;
  - a collapsed "How to create the service in Databricks" help panel, with the SQL template from
    "Rollout".

### Adding a connection to a deck

- **Tools row layout** (owner's direction, 2026-11-03):
  - **+ Genie One**, then one pill per enabled registered connection, then an **Other tools** toggle;
  - the toggle reveals the original pills: Genie Agent, Agent Bricks, Vector Index, MCP Server,
    Model Endpoint;
  - a vanilla install, with no connections, shows just two pills.
- `GET /api/tools/discover/gateway-mcp` returns `{"items": [...]}`:
  - the enabled registered connections, each `{service_name, display_name, description, agent}`;
  - it reads only the registry, so it needs no scope and never waits on the UC listing;
  - a registry failure gives `items: []`.
- `GET /api/tools/discover/mcp` and the MCP Server picker stay Unity Catalog only, as on main.
- **Clicking a connection pill** adds `{type: "gateway_mcp", service_name, display_name}` in one click,
  like Genie One.
  - The pill's tooltip is the description.
  - The pill is hidden while that connection is in the deck.
- Saving an agent config rejects (422) a `gateway_mcp` entry whose service is not registered or not
  enabled. Duplicates are keyed by `service_name`.
- The chip:
  - **Legacy decks:** it says "agent mode only", like Genie One's.
  - **Agent decks:** it checks the user's status with `GET /api/tools/gateway-mcp/status?service_name=…`,
    which runs `tools/list` as the user and returns the same states as the admin test. Each state
    shows differently:
    - `sign_in_required`: a **"Sign in to <name>"** link that opens the sign-in page in a new tab,
      and a "Check again" action.
    - `access_denied`, `missing_scope` or `unavailable`: a short reason.
    - `ready`: nothing extra.
  - If an admin removed or disabled the connection, the chip says "unavailable".
- Bindings are per actor, as with Genie One. Each user's own agent config holds their tools, so a
  contributor adds a connection themselves.

### The Gateway client

This is a generic client for `{host}/ai-gateway/mcp-services/<service_name>`, extracted from the
transport in `src/services/agent_tools/genie_one.py`. Genie One moves onto the shared transport with
its behaviour and tests unchanged.

- It is built from the user's host and token (`get_user_client()` in the request or node thread).
  There is **no service-principal fallback**.
- It uses `DatabricksMCPClient` with Tellr's own bearer `httpx.Auth` (`_UserBearerAuth`). The stock
  OAuth provider must never run. A Gateway 401 carries `WWW-Authenticate: Bearer resource_metadata=…`,
  and the stock provider turns it into an `OAuthFlowError` (measured on Logfood).
- Calls run in a clean worker thread, because `DatabricksMCPClient` calls `asyncio.run`.
- **Error mapping** (typed errors; the message strings are measured, see "Real shapes"):
  - **Sign-in required:** JSON-RPC `-32006` with an HTTP 401, or "not signed in" text.
    - The sign-in link is the URL in the message if there is one. Both Logfood's LakeDraw and the
      tellr-dev LakeDraw mirror include it, with `&o=<workspace id>`.
    - Otherwise it is built as `{host}/mcp-service-login?name=<service_name>`, with `&o=<id>` added
      when the workspace id is known from the response's `x-databricks-org-id` header.
    - On tellr-dev, `system.ai.github` answered `initialize` fine, then failed `tools/list` with
      `-32006` "The MCP service request was rejected (HTTP 401)…". That counts as sign-in required too.
  - **Missing scope:** the token lacks `ai-gateway`, or the existing `is_missing_scope_error` matches.
    The message is the existing consent message.
  - **Access denied:** a 403 or permission error. The message names the service and says to ask an
    admin for `EXECUTE` on it.
  - **Not found:** a 404 or "does not exist".
  - **Timeout,** and any other failure (unavailable).
- `list_tools()` has a 30 s timeout. `call_tool()` has a **90 s** per-call timeout, as the LakeDraw
  doc advises; the toolset's remaining budget bounds it further.
- Each call opens its own MCP session, as Genie One does.
  - LakeDraw's two-phase create passes its `validation_digest` explicitly, so per-call sessions are
    fine.
  - If live testing shows otherwise, the builder may hold one session per toolset. It must say so in
    the PR.

### Tools in the agent loop

- At the start of an architect or analyst run, Tellr reads the actor's `gateway_mcp` entries and
  joins each to its enabled registry row with the matching `agent`. It then lists each service's tools
  as the user, in parallel, and applies the allowlist.
  - A connection that fails here (sign-in, access, scope, not found, unavailable) is left out of the
    run.
  - The user gets one chat notice per connection per turn (see "Errors"). The rest of the turn goes on.
- Each MCP tool becomes an `AgentTool` (`src/services/agent_tools/toolset.py`) with:
  - **name:** the MCP tool's own name. If two bound connections share a name, both are prefixed with
    a slug of their service name. Names must be ≤ 64 chars and match `[A-Za-z0-9_-]`.
  - **description:** the connection's guidance, then the tool's own description (see "Guidance").
  - **parameters:** the MCP `inputSchema`, **passed to the model verbatim**. LakeDraw's nested
    `diagram_data` must not go through a lossy JSON-Schema → Pydantic conversion.
    - `_tool_definition` and the argument check in `_answer_tool_call` (`src/services/agent_runtime.py`)
      learn to take a raw JSON schema. Arguments get only a light check (an object); the service
      validates the rest and its error goes back to the model.
- **Architect** (`architect_node`, `src/services/graph/nodes.py`): when it has Gateway tools, the
  architect's call carries a toolset, so `AgentRuntime` runs `invoke_with_tools`.
  - Each attempt gets a fresh toolset (the edit-retry path makes a second attempt), as the builder
    does today.
  - With no Gateway tools, the call is exactly today's single structured-output call.
- **Data analyst:** Gateway tools join the existing toolset beside Genie One, so the analyst runs its
  loop when either is present.
  - A deck with only Genie One is unchanged: same tools, same 3-question / 300 s budget.
  - The analyst's synthesis carries what it learned. `AnalystOutput` is unchanged, and figures are
    code-built only for Genie One, as today.
- The tool loop answers only the first call in a model reply. The "not run" text is Genie-worded today
  ("ask one question at a time"); it becomes generic.

### Guidance

The admin's `instructions` reach the model in the **tool descriptions**. Each tool from a connection
gets this description: `"<display_name>: <instructions>\n\n<tool description>"`, where the
instructions part is omitted when empty.

No agent prompt changes. That follows #354's ruling that tool guidance lives in tool descriptions,
and the protected assembly stages are a digest-pinned bundle. The allowlist is how an admin keeps
this short.

### Results, and images onto slides

What the model sees from one tool call is text, built in code:

- Text content blocks, joined. If the result has no text blocks, its `structuredContent` as JSON.
- **Images:**
  - each `ImageContent` block (png, jpeg, gif, svg+xml) is decoded and saved;
  - any JSON field whose key ends in `base64` (case-insensitive) and decodes to one of those types is
    saved too, deduplicated by SHA-256, so LakeDraw's `ImageContent` plus `data_base64` saves once;
  - every such field is removed from the text either way.
  - **Saving:**
    - It goes through `image_service.upload_image`, as the acting user, with category `content`.
      `ephemeral` would hide the image from shared-deck viewers, because `substitute_image_placeholders`
      leaves another user's ephemeral image unresolved.
    - Filenames are unique (`<slug>-<UTC timestamp>-<short id>.<ext>`), so the library's dedupe never
      refuses one.
    - Tags record the service.
  - **The model gets** `Image saved: {{image:TOKEN}} (<mime>, <w>×<h>). To show it on a slide, put this
    exact reference in that slide's content_brief.`
  - An image over the 5 MB upload limit, or one that fails to decode, is reported to the model in one
    line and not saved.
- Other content types become `[<type> content omitted]`.
- `isError` results become `Tool error: …`.
- **All of it is spotlighted** (`src/utils/spotlight.py`) with the display name as the source, and
  capped. The cap is at least 32,000 characters; a truncated result says so.

**Image references are checked in code**, so a mistyped token can't break a slide. One helper covers
both places: (a) the text fields of the architect's output (`deck_spec` slide briefs and edit
operations) and (b) each built slide's HTML.

- A reference counts as known if it is an image saved by this turn's tools, or one already in the
  deck.
- An unknown reference is corrected when exactly one known token shares its first 12 characters.
  Otherwise it is removed.
- A removal is logged, and the user is told once ("A <name> image couldn't be placed on slide N").

### Time

- 90 s per tool call, clipped to the remaining budget, and 30 s per `tools/list`.
- **The architect's Gateway budget is per turn: 12 calls / 360 s.** Every architect invocation in
  the turn shares it, including the edit retry and the second architect pass after a data request.
  Each attempt still gets a fresh toolset object, but that object starts from the turn's remaining
  budget. LakeDraw takes about 4–5 calls per diagram, so that allows about two diagrams.
- The analyst's budget is **6 calls / 300 s** per run when Gateway tools are present. It is unchanged
  when only Genie One is (3 / 300 s).
- **Turn deadline guard:** no Gateway tool call (architect or analyst) starts once the turn has been
  running 700 s. This keeps building time inside the 1,200 s graph job limit
  (`GRAPH_JOB_HARD_TIMEOUT_SECONDS`).
  - The turn's start time comes from the job, or from a `turn_started_at` GraphState key the builder
    adds.
  - A refused call gets the budget-spent text.
- A spent budget tells the model, once, to finish without more calls (the existing loop behaviour).

### Progress and errors in chat

- Each Gateway tool call emits the existing `TOOL_CALL` progress event and row
  ("<display_name> · <tool name>"). It shows in the chat's tool activity bar, as Genie One's
  questions do.
- These failures each produce one `info` message per connection per turn, and the turn continues
  without that connection:
  - **Sign-in required:** "To use <name>, sign in here: <link> — then ask again." The link must be
    clickable in chat.
  - **Access denied:** "You don't have access to <name> (<service>). Ask an admin to grant EXECUTE on
    it."
  - **Missing scope:** the existing consent message.
  - **Removed or disabled by an admin:** "<name> is no longer available."
  - **Not found or unavailable:** a one-line reason.
- A sign-in or access error in the middle of a run is recorded on the toolset (`access_errors`, as for
  Genie One) and reported the same way after the run.

## Build order

1. Gateway client and error mapping, with Genie One moved onto the shared transport.
2. Registry table, admin API and test endpoint.
3. Tool-entry type, agent-config validation, discovery union, user status endpoint.
4. Generic Gateway agent tool: result shaping, image saving, raw-schema binding.
5. Architect and analyst binding, progress, chat notices, image-reference check.
6. Frontend: Connections tab, picker groups, chip states.
7. Admin how-to doc `docs/technical/gateway-mcp-connections.md`, with both the UC-side SQL and the
   Tellr steps.

## Rollout (after merge, by the owner)

No scope change in code: `ai-gateway` is already requested. But check that the app has it:
`databricks apps get <app>` must list `ai-gateway` in `user_api_scopes`. `tellr.update()` adds missing
scopes only on a best-effort basis, and it skipped them once on Logfood. Users whose consent predates
the scope must re-consent; the existing consent message says how.

On each workspace, the admin does two things.

**1. Creates the service in Databricks,** if it doesn't exist. This is what worked on tellr-dev on
2026-11-02 (`~/tellr-loop/mcp-connections/probes/create_lakedraw.py`); the LakeDraw doc's
`CREATE CONNECTION` SQL does not.
- The connection is schema-level. `POST /api/2.1/unity-catalog/connections` with:
  - `name`: a one-part name;
  - `parent`: `schemas/<catalog>.<schema>`;
  - `connection_type`: `HTTP`.

  The options are:
  - `host`: `https://lakedraw-stg-7474654280603666.aws.databricksapps.com`
  - `port`: `443`
  - `base_path`: `/mcp/`
  - `authorization_endpoint` and `token_endpoint`: `https://fevm-lakedraw.cloud.databricks.com/oidc/v1/{authorize,token}`
  - `client_id`: `9eb36248-4a77-415e-87b0-191d19060d95`
  - `oauth_scope`: `all-apis offline_access`
  - `oauth_credential_exchange_method`: `header_and_body`

  Leave out `credential_type` (UC infers `OAUTH_U2M_MAPPING` and refuses it if given) and
  `is_mcp_connection` (refused on schema-level connections).
- The service: `ai_gateway.create_mcp_service`, with:
  - parent `schemas/<catalog>.<schema>`;
  - id `<service>`;
  - config `source_connection.name = connections/<catalog>.<schema>.<conn>` and
    `include_tool_selectors = ["*"]`.
- Grants for users: `USE CATALOG` on the catalog, `USE SCHEMA` on the schema, `EXECUTE` on the service.
  The verified SQL is `GRANT EXECUTE ON MCP SERVICE <catalog>.<schema>.<service> TO <principal>`
  (`GRANT EXECUTE ON SERVICE …` is a parse error on DBSQL). The permissions API also works:
  `PATCH /api/2.1/unity-catalog/permissions/mcp_service/<service>` with
  `{"changes": [{"principal": "<principal>", "add": ["EXECUTE"]}]}`.

**2. Registers it on Tellr's Admin → Connections tab.**
- On Logfood: `main.gtm_ai_tooling.lakedraw` (it already exists there).
- On tellr-dev: `db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw`.

## Real shapes, and what counts as proven

- Parsing tests use recorded or doc-sourced responses, sanitised.
- Recorded on tellr-dev, 2026-11-02, in `~/tellr-loop/mcp-connections/fixtures/` (copy them into
  `tests/fixtures/gateway_mcp/`):
  - for `system.ai.web_search`: initialize, tools/list and a tools/call. The result is one text block;
    there is no `Mcp-Session-Id` header.
  - **Two different sign-in shapes:**
    - LakeDraw initialize returns **HTTP 401** with `WWW-Authenticate` and a JSON-RPC `-32006`
      "You're not signed in … Sign in at <url>".
    - `system.ai.github` tools/list returns **HTTP 200** with a JSON-RPC `-32006` "The MCP service
      request was rejected (HTTP 401)…" and no URL.

    The client must map both to sign-in required.
- LakeDraw tool results can't be recorded overnight, because signing in needs a browser. Their fixtures
  follow the doc's examples (`ImageContent` plus `data_base64`; `diagram_id` / `diagram_url` /
  `version` from persist) and are marked doc-sourced in the fixture file.

## Live verification (overnight, on devloop)

1. **Admin path:** register `system.ai.web_search` as an architect connection and run Test connection
   through the app API.
2. **A real deck turn:** an agent deck with web_search added, through the app API (token
   `tellr-dev-oauth`). It must log web_search progress rows and finish.
3. **LakeDraw on tellr-dev:**
   - the UC connection and service already exist (D12): `db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw`;
   - check `ai-gateway` is in the devloop app's `user_api_scopes`;
   - register the service on the devloop;
   - the status endpoint must report `sign_in_required` with a link;
   - a deck turn must post the sign-in notice and still build the deck.
4. **Owner's morning check:** sign in to LakeDraw from the chip, then ask for an architecture diagram.
   That check is the only live proof of the image path.

## Constraints

- **Environment and deploys:**
  - Per-worktree uv `.venv` (`uv sync --extra dev`, `uv run`).
  - Add dependencies via `packages/databricks-tellr-app/pyproject.toml`. None should be needed:
    `databricks-mcp` and `mcp==1.27.0` are already in the wheel.
  - Deploys go to devloop only.
- **Database:**
  - There is no Alembic. New tables come from `Base.metadata.create_all` in `init_db`
    (`src/core/database.py`). Postgres integration tests live in `tests/integration/`.
  - Startup must not get slower; keep any migration idempotent and cheap.
- **Frontend:** `frontend/src/types/agentConfig.ts` keeps its label and colour maps complete. Every
  tool-type switch must handle `gateway_mcp`.
- **Remove by key:** the remove path in `src/api/routes/agent_config.py` has its own key function, so
  `gateway_mcp` must be added there too.

## Calls made without the owner

- D4: register existing services; don't create UC objects from Tellr.
- D5: a new `gateway_mcp` type keyed by service name. It first shipped as a union in the MCP Server
  picker (the owner's first idea). On 2026-11-03 the owner replaced that with a pill per connection
  in the Tools row, and moved the other pills behind "Other tools".
- D6: agent mode only.
- D7: Architect or Data analyst only.
- D8: guidance in tool descriptions; no prompt changes.
- D9: images saved as `content` category, owned by the actor; code-checked references.
- D10: sign-in detection from `-32006`; links on the chip and in chat.
- D11: web_search for the live e2e; LakeDraw mirrored on tellr-dev for the sign-in path.
- **Budgets:** architect 12 calls / 360 s per turn; analyst 6 / 300 s per run when Gateway tools are
  present; 90 s per call; 30 s list; no new Gateway call after 700 s into a turn. These come from the
  spec review (D13).
- **Saving:** a connection needs no passing test, and the service name is immutable.

## Left to the builder

- Module layout, and whether Genie One's transport is moved or wrapped, provided Genie One's tests
  stay green.
- UI copy beyond the strings quoted here, and the layout of the Connections tab, following the
  existing Admin tab patterns.
- How the chip caches status (per mount is fine).
