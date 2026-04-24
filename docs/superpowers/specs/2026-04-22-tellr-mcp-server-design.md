# Tellr MCP Server Design Spec

**Date:** 2026-04-22
**Branch:** `ty/feature/tellr-mcp-server`
**Status:** Draft

## Overview

Today tellr is reachable only via its own browser UI. This design exposes tellr as an **MCP (Model Context Protocol) server** so that external Databricks Apps and MCP-compatible agent tools (e.g., Claude Code and similar) can programmatically request deck generation and editing using the existing tellr agent pipeline, without forking or re-implementing it.

The design follows the guiding principle that **external callers handle research and data collection; tellr produces the presentation**. A caller assembles a prompt (optionally enriched with their own data, Genie output, knowledge-base results, etc.), sends it to tellr's MCP endpoint, and receives either the rendered deck (as structured slide data and standalone HTML) or a URL into tellr's own UI for full-featured editing. The same tellr deployment serves browser users and MCP callers from a single process; MCP is an additional entry point, not a parallel pipeline.

This v1 ships **prompt-only generation** — callers send natural-language prompts; tellr generates slides without invoking Genie, Vector Search, MCP-consumed servers, Model Serving endpoints, or Agent Bricks on the caller's behalf. Tool configurability, exports, and structural edit primitives are deferred to v1.1.

## Goals

- Expose a Streamable HTTP MCP endpoint at `/mcp` on the existing tellr Databricks App, using the 2025-03-26 MCP specification revision.
- Provide four tools: `create_deck`, `get_deck_status`, `edit_deck`, `get_deck`.
- Preserve tellr's existing permission and ownership model — the deck creator is the end user whose identity arrived on the MCP call.
- Accept two authentication paths transparently: proxy-injected `x-forwarded-access-token` (for in-workspace callers) and `Authorization: Bearer` (for external agent tools).
- Return deck content in multiple useful forms (structured slide data, renderable standalone HTML document, tellr UI URL) so each caller can choose how to present it.
- Reuse existing async job queue, worker, session manager, slide-deck domain, agent factory, and permission service — no new infrastructure, no parallel pipelines.
- Ship v1 with unit tests, integration tests, smoke test scripts, design spec, and caller-facing technical reference documentation.
- Ensure each MCP deployment works against the tellr Databricks App's own URL; callers parameterize on that URL with no additional infrastructure setup.

## Non-Goals

- Tool-level configurability over MCP (Genie Space, Vector Index, MCP consumer, Model Endpoint, Agent Bricks). Callers that need data-backed generation in v1 shape the relevant content into the prompt itself.
- Deck exports (PPTX, Google Slides) over MCP. Exports remain available in the tellr UI; MCP callers hand users to `deck_url` for export actions in v1.
- Structural edit primitives (reorder, delete, duplicate). Callers that need these in v1 direct the user to the tellr UI.
- Raw HTML slide replacement (caller supplying exact HTML for a slide).
- Cancellation of in-flight generation jobs.
- Server-sent progress events (SSE) during generation — v1 is polling-based.
- Unity Catalog HTTP Connection registration of tellr. This is a pure workspace-admin action that requires no tellr code change; documented as a later operational step.
- Python library extraction of tellr's core pipeline for in-process embedding.
- UI changes in the tellr frontend (no "created via MCP" badge, no MCP session listing, no new views).

## Design Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Protocol | Streamable HTTP MCP, spec revision 2025-03-26 | Native support in major MCP clients (Claude Code, Claude Desktop, Cursor) and in-workspace MCP proxy clients; the same protocol tellr already consumes for external MCP servers |
| 2 | Path | `/mcp` on the existing tellr Databricks App URL | Matches common MCP convention; inherits TLS, DNS, SSO, and deploy cadence from the existing app; no new infrastructure |
| 3 | Server SDK | Official `mcp` Python package (`FastMCP`) | Spec-compliant by construction; auto-derives tool schemas from Python type hints; handles `initialize`, `tools/list`, `tools/call`, `mcp-session-id`, and JSON-RPC error envelopes without hand-rolled protocol code |
| 4 | Auth model | Dual-token: `x-forwarded-access-token` first, `Authorization: Bearer` fallback | Supports in-workspace (proxy-injected) and external (laptop agent tools) callers through the same code path; priority order prevents spoofing |
| 5 | Identity propagation | Re-use existing `ContextVar`-based permission context | Tool handlers run under the same identity contract as browser API routes; every downstream service (session manager, permission service, Google Slides auth, MLflow) inherits identity without additional wiring |
| 6 | Job lifecycle | Async + polling, reusing existing `chat_requests` queue and background worker | Zero new worker, zero new queue; MCP-submitted jobs are indistinguishable from browser-submitted jobs from the worker's perspective |
| 7 | v1 tool scope | Prompt-only generation, no tool configuration on the MCP surface | Avoids the hardest unsolved problem for v1 (delegating Genie / Vector OBO through a non-browser auth path); tellr's existing empty-tools path already supports this mode |
| 8 | Response contract | Return structured `deck`, standalone `html_document`, and `deck_url`/`deck_view_url` together | Each caller chooses: render in their own UI (HTML), consume slide-by-slide (structured), or link users to tellr's full editor (URL). All three are cheap derivations of the same canonical `deck_json` |
| 9 | Identifier model | `session_id` (stable per deck) + `request_id` (per async call) | Decoupled semantics: multiple edits on one deck share `session_id` and `deck_url`; each call has its own `request_id` for polling |
| 10 | Hard job timeout | 10 minutes, enforced by a lifespan sweeper task | Gives callers a predictable upper bound on poll duration, independent of deploy cadence; belt-and-suspenders on top of lifespan startup recovery |
| 11 | Error taxonomy | Protocol errors via JSON-RPC envelope; tool-execution errors via `isError: true` in tool result; async states as normal status values | Conforms to MCP's tool-call error convention; LLM callers can reason over error text naturally |
| 12 | Clarification / refusal behavior | Returned as successful tool responses with `messages` carrying the LLM text, not as errors | Matches how the existing browser UI handles LLM clarifications; callers surface the message to their user and continue the conversation |
| 13 | MCP surface attack surface | Strictly a subset of existing user-facing operations; no admin, no lifecycle, no deployment endpoints exposed | Callers can only do what a browser user could do under the same identity |
| 14 | URL format for callers | `https://<tellr-app-url>/mcp` — no new hostnames created | The MCP endpoint lives on tellr's existing Databricks App URL; each deployment independently gets its own MCP endpoint by virtue of running the updated codebase |

---

## Architecture

### Component layout

```
┌─────────────────────────── tellr Databricks App (single process) ────────────────────────┐
│                                                                                           │
│   [lifespan startup/shutdown — triggered only by platform events, not by HTTP requests]  │
│     - Lakebase token refresh loop                                                         │
│     - DB init + profile migration                                                         │
│     - Chat job queue worker             ← same worker services MCP-submitted jobs         │
│     - Export job queue worker                                                             │
│     - Request log cleanup                                                                 │
│     - [NEW] Stuck-job timeout sweeper (mark_timed_out_jobs_loop)                          │
│     - recover_stuck_requests() on boot  ← inherited; MCP jobs recovered for free          │
│                                                                                           │
│   ┌─── FastAPI app ─────────────────────────────────────────────────────────────────┐     │
│   │                                                                                  │    │
│   │   [existing] /api/*                — browser-facing REST routes (unchanged)      │    │
│   │                                                                                  │    │
│   │   [NEW]      /mcp                  — FastMCP server mounted here                 │    │
│   │                                       must be registered before SPA catch-all    │    │
│   │                                                                                  │    │
│   │   [existing] /{full_path:path}     — SPA catch-all (last in precedence)          │    │
│   │                                                                                  │    │
│   └──────────────────────────────────────────────────────────────────────────────────┘    │
│                             │                                                             │
│                             ▼ /mcp tool handlers delegate to                              │
│                                                                                           │
│   ┌── existing services (unchanged) ────────────────────────────────────────────────┐     │
│   │  ChatService.submit_chat_async    SessionManager.create/get/update              │     │
│   │  SlideDeck.from_dict / to_dict    permission_service.can_view/edit_deck         │     │
│   │  job_queue.get_status             build_agent_for_request (agent_factory)       │     │
│   │  [NEW] SlideDeck.to_html_document — small, additive serializer method           │     │
│   └─────────────────────────────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

### Files added or touched

| File | Change type | Purpose |
|---|---|---|
| `src/api/mcp_server.py` | **New** | FastMCP instance; four tool handlers; thin wrappers over existing services |
| `src/api/mcp_auth.py` | **New** | Dual-token extraction + `ContextVar` wiring helper used by each tool handler |
| `src/api/main.py` | **Edited** | Register MCP router before `_mount_frontend`; start `mark_timed_out_jobs_loop` in lifespan |
| `src/api/services/job_queue.py` | **Edited** | Add `mark_timed_out_jobs_loop` coroutine with a single SQL sweep per tick |
| `src/domain/slide_deck.py` | **Edited** | Add `SlideDeck.to_html_document(chart_js_cdn: str = DEFAULT_CHART_JS_CDN) -> str` serializer |
| `pyproject.toml` | **Edited** | Add `mcp>=1.0.0` dependency |
| `tests/unit/test_mcp_server.py` | **New** | Unit tests for tool handlers, auth middleware, error mapping, timeout sweeper, HTML serializer |
| `tests/integration/test_mcp_endpoint.py` | **New** | End-to-end MCP protocol tests using FastAPI `TestClient` + mocked LLM |
| `scripts/mcp_smoke/mcp_smoke_httpx.py` | **New** | Copy-pasteable smoke script for post-deploy verification |
| `docs/technical/mcp-server.md` | **New** | Caller-facing integration reference (separate deliverable tracked in plan) |

### Registration order

The SPA catch-all (`/{full_path:path}`) in `src/api/main.py` currently serves `index.html` for any path not starting with `api/`. A request to `/mcp` would be swallowed by that catch-all unless the MCP router is registered earlier.

The MCP router is added at module-load time alongside existing `app.include_router(...)` calls, before any `_mount_frontend(...)` invocation. Production and local dev paths both rely on that ordering.

---

## Authentication & Identity Propagation

### Why dual-token

The existing `user_auth_middleware` in `src/api/main.py` reads only `x-forwarded-access-token`, which the Databricks Apps proxy injects for browser-originated requests. External callers (laptop agent tools) do not go through that injection path and must carry their own bearer token. In-workspace callers (other Databricks Apps calling directly) may or may not have the proxy inject a token depending on how the request is shaped.

A dedicated MCP auth helper accepts tokens from both sources in priority order:

1. `x-forwarded-access-token` header — highest trust; injected by the Databricks Apps proxy and cannot be spoofed from outside.
2. `Authorization: Bearer <token>` header — fallback for callers that are not behind the proxy (external agent tools) or where the proxy is not injecting.

If neither header is present, the request fails with `isError: true` and a clear authentication message.

### Identity resolution

The bearer token is passed to `get_or_create_user_client(token)` — the same factory the browser flow uses. Identity is resolved via `user_client.current_user.me()` and bound into the per-request `ContextVar`s:

- `set_current_user(user_name)`
- `set_user_client(user_client)`
- `set_permission_context(build_permission_context(user_id, user_name, fetch_groups=False))`

Each tool handler runs inside a scope that establishes and tears down these ContextVars — same discipline as the existing middleware. Once set, all downstream services (`session_manager.create_session`, `permission_service.can_edit_deck`, Google OAuth auth, MLflow span tagging) pick up identity transparently.

### Caller contracts

**In-workspace Databricks App callers.** A Databricks App that receives a user's OBO token via its own `x-forwarded-access-token` header must forward that token to tellr's `/mcp` as `Authorization: Bearer <token>`. Pseudocode:

```python
user_token = request.headers.get("x-forwarded-access-token")
async with httpx.AsyncClient() as client:
    await client.post(
        f"{TELLR_APP_URL}/mcp",
        headers={
            "Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
```

This ensures deck attribution flows to the end user and the deck appears in that user's tellr UI automatically.

**External MCP client callers (laptop agent tools).** Configure the MCP client to include an `Authorization` header carrying a Databricks user token (OAuth U2M or PAT):

```json
{
  "tellr": {
    "type": "streamable-http",
    "url": "https://<tellr-app-url>/mcp",
    "headers": {
      "Authorization": "Bearer ${DATABRICKS_TOKEN}"
    }
  }
}
```

The URL should be the tellr Databricks App URL the caller is targeting; each deployment has its own URL.

### Security posture

| Concern | Handling | Rationale |
|---|---|---|
| Transport | HTTPS-only (Databricks Apps enforced) | Bearer tokens never in plaintext |
| Token validation | `current_user.me()` on every JSON-RPC call | Short-circuit on expired or invalid tokens; no cross-request identity caching in v1 |
| Token logging | Never log token values; log `token_source` and resolved `user_name` | Prevent token leakage via structured logs |
| Authorization | Existing `permission_service` checks on every deck-touching operation | MCP inherits tellr's entire permission model (CAN_VIEW / CAN_EDIT / CAN_MANAGE) |
| Rate limiting | Inherits existing LLM backend rate limits | No new capacity or bypass added |
| CORS | Not configured for `/mcp` | MCP clients are server-side HTTP clients, never browsers; avoids widening origin surface |
| Shared secrets / API keys | Not supported | Would break "creator = end user" attribution |
| Service-principal callers | Accepted; deck is attributed to the SP | Honest behavior; callers should forward end-user tokens instead if the deck should surface to a user |
| Creator spoofing | Impossible | `created_by` derives from the resolved identity of the bearer token; no parameter accepts it |
| Admin / lifecycle operations | Not reachable from `/mcp` | MCP tool list is a strict subset of user-facing functionality; admin routes remain under `/api/admin/*` with their own auth |

### Permission context for MCP-initiated edits

When `edit_deck` is called:

1. The tool handler resolves the caller's identity from the bearer token.
2. `permission_service.can_edit_deck(session_id)` runs against that identity.
3. If the caller is neither the session creator nor a contributor with `CAN_EDIT` (including via group membership if enabled), the tool returns `isError: true` with a permission-denied message.
4. On success, the `edit_deck` call is recorded as a chat message on the session under the caller's identity, just as a browser-originated edit would be.

Cross-user deck access via MCP is therefore governed by the same rules as cross-user deck access via the browser UI. No new authorization surface is introduced.

---

## MCP Tool Catalog

All four tools are registered on a single `FastMCP("tellr")` instance mounted at `/mcp`. Input schemas are derived automatically from Python type hints; output shapes are documented below.

### 1. `create_deck`

Creates a new tellr session and submits a generate-mode job to the async chat queue.

**Input:**

| Field | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | yes | Natural-language description of the desired deck |
| `num_slides` | integer | no | Target slide count (1–50); LLM treats as guidance |
| `slide_style_id` | integer | no | Identifier of a slide style from the slide-style library; resolved server-side |
| `deck_prompt_id` | integer | no | Identifier of a deck prompt from the deck-prompt library; resolved server-side |
| `correlation_id` | string | no | Opaque caller-supplied string propagated into MLflow spans and logs |

**Output:**

```json
{
  "session_id":     "abc-123",
  "request_id":     "req-7f2",
  "status":         "pending"
}
```

**Semantics:**

- Creates a row in `user_sessions` with `created_by = <resolved caller identity>`, `agent_config.tools = []` (prompt-only), and optional `slide_style_id` / `deck_prompt_id` resolved from library references.
- Submits the generate job via `chat_service.submit_chat_async`. Returns immediately; the caller polls `get_deck_status` for completion.
- `slide_style_id` / `deck_prompt_id` resolve identically to how the browser flow resolves them; unknown identifiers log a warning and fall back to defaults (existing behavior).

### 2. `get_deck_status`

Polls the state of a submitted create or edit job; returns the current deck on completion.

**Input:**

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | yes | The deck's session identifier |
| `request_id` | string | yes | The async job identifier returned by `create_deck` / `edit_deck`. Callers that do not have a `request_id` (e.g., re-fetching a previously generated deck) should call `get_deck` instead |

**Output (status = `pending` or `running`):**

```json
{
  "session_id":  "abc-123",
  "request_id":  "req-7f2",
  "status":      "running",
  "progress":    null
}
```

**Output (status = `ready`):**

```json
{
  "session_id":      "abc-123",
  "request_id":      "req-7f2",
  "status":          "ready",
  "slide_count":     7,
  "title":           "Q3 Revenue Pitch",
  "deck": {
    "slides":           [ /* { html, scripts } per slide */ ],
    "css":              "...",
    "external_scripts": [ "https://cdn.jsdelivr.net/npm/chart.js" ]
  },
  "html_document":   "<!doctype html>…",
  "deck_url":        "https://<tellr-app-url>/sessions/abc-123/edit",
  "deck_view_url":   "https://<tellr-app-url>/sessions/abc-123/view",
  "replacement_info": null,
  "messages": [
    { "role": "user",      "content": "…the user prompt…" },
    { "role": "assistant", "content": "…the agent's summary or clarification…" }
  ],
  "metadata": {
    "mode":           "generate",
    "tool_calls":     0,
    "latency_ms":     27340,
    "correlation_id": "…"
  }
}
```

**Output (status = `failed`):**

```json
{
  "session_id": "abc-123",
  "request_id": "req-7f2",
  "status":     "failed",
  "error":      "Generation exceeded maximum duration (10 minutes)"
}
```

**Semantics:**

- While status is `pending` or `running`, the response is cheap (single SELECT on `chat_requests`). Callers are expected to poll at ≥ 1s intervals with backoff; no server-side rate limit is enforced in v1.
- On `ready`, the response contains both structured `deck` and standalone `html_document` — the caller chooses which (or both) to use.
- `messages` contains the current turn's exchange only, not full session history. Clarification questions from the LLM surface here for the caller to display.
- `replacement_info` is `null` for generate jobs and populated for edit jobs.

### 3. `edit_deck`

Submits an edit-mode job against an existing session.

**Input:**

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | yes | The deck to edit |
| `instruction` | string | yes | Natural-language edit instruction |
| `slide_indices` | array of int | no | Contiguous slide indices to target; if omitted, the LLM infers from the instruction |
| `correlation_id` | string | no | Opaque caller-supplied string |

**Output:**

```json
{
  "session_id": "abc-123",
  "request_id": "req-8a1",
  "status":     "pending"
}
```

**Semantics:**

- `permission_service.can_edit_deck(session_id)` runs before any side effects; unauthorized callers receive `isError: true`.
- If `slide_indices` is provided, a `slide_context` block is constructed from the deck's current HTML at those indices and attached to the agent prompt — exactly the same mechanism the browser UI uses for targeted edits. The existing slide-replacement pipeline (`_parse_slide_replacements` / `_apply_slide_replacements`) handles the merge, canvas deduplication, CSS merge, and script rewriting without change.
- On `get_deck_status` showing `ready`, the response contains the **updated** deck, updated `html_document`, unchanged `deck_url`, and a populated `replacement_info` summarizing what changed.
- A new save point is created automatically after deck persistence (existing `ChatService` behavior, capped at 40 per session, oldest deleted on overflow).

### 4. `get_deck`

Idempotent read of the current deck state for a session.

**Input:**

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | yes | The deck to retrieve |

**Output:**

```json
{
  "session_id":    "abc-123",
  "slide_count":   7,
  "title":         "Q3 Revenue Pitch",
  "deck": {
    "slides":           [ /* { html, scripts } per slide */ ],
    "css":              "...",
    "external_scripts": [ "https://cdn.jsdelivr.net/npm/chart.js" ]
  },
  "html_document": "<!doctype html>…",
  "deck_url":      "https://<tellr-app-url>/sessions/abc-123/edit",
  "deck_view_url": "https://<tellr-app-url>/sessions/abc-123/view"
}
```

Fields `status`, `request_id`, `messages`, `replacement_info`, and `metadata` (which are tied to an async job or turn) are omitted — this tool does not execute a job or advance a conversation turn.

**Semantics:**

- Runs `permission_service.can_view_deck(session_id)`; denies per existing rules.
- Single SELECT on `user_sessions`. No job queue interaction. No new save point.
- Intended for callers that already know a `session_id` (e.g., they're re-rendering a deck they generated earlier) and want to fetch the current state without triggering new work.

### Tool descriptions for agent consumers

Each tool carries a concise description attribute for LLM-driven callers:

- `create_deck`: "Generate a new slide deck from a natural-language prompt. Returns a session_id and a request_id for polling via get_deck_status. The resulting deck is attributed to the calling user and appears in their tellr UI."
- `get_deck_status`: "Poll the status of a deck generation or edit job. While running, returns lightweight status. When ready, returns the complete deck as structured data and standalone HTML, along with the tellr URL for full-featured editing."
- `edit_deck`: "Refine an existing deck through natural-language instructions. Optionally target specific slides via slide_indices. The edit is applied in-place; the session_id and deck_url remain stable across edits."
- `get_deck`: "Retrieve the current state of a deck without submitting new work. Returns the same rich payload as get_deck_status on a ready job."

---

## Data Flow & State Model

### Identifier semantics

- **`session_id`** identifies a deck. Stable from creation through every edit. Appears in `deck_url`. One session = one deck, visible in the creator's tellr UI.
- **`request_id`** identifies one async job. Transient; used only for polling the status of that specific job. Every `create_deck` or `edit_deck` call returns a new `request_id`.

A deck created by MCP can later be edited from the tellr browser UI, and vice versa; the `session_id` is the same across surfaces.

### `create_deck` end-to-end

```
Caller                            MCP tool handler                     Worker                             DB
──────                            ────────────────                     ──────                             ──
create_deck(prompt, …)            auth → permission_context            
                                  session_manager.create_session(             
                                    created_by = <caller identity>,         
                                    agent_config = {                         
                                      tools: [],              ← prompt-only       
                                      slide_style_id,                        
                                      deck_prompt_id                         
                                    })                                       ─────▶  INSERT user_sessions
                                  chat_service.submit_chat_async(                     
                                    session_id, prompt,                       
                                    mode="generate",                          
                                    correlation_id)                            ─────▶  INSERT chat_requests (pending)
                                  return {session_id, request_id,                     
                                          status: "pending"}                  
                                  
  (caller polls get_deck_status)                                  
                                                              [worker picks up]      
                                                              build_agent_for_request(config, mode="generate")
                                                              agent.run(prompt)
                                                              SlideDeck.from_html_string
                                                              session_manager.update_session          ─────▶  UPDATE user_sessions.deck_json
                                                              create_save_point                        ─────▶  INSERT slide_deck_versions
                                                              append_session_messages                   ─────▶  INSERT session_messages
                                                              mark request ready                       ─────▶  UPDATE chat_requests (ready)

  get_deck_status sees "ready":                                                       
                                  SELECT chat_requests (status)                  
                                  SELECT user_sessions (deck_json)               
                                  deck = SlideDeck.from_dict(...)                
                                  build response with deck,                      
                                    html_document (via to_html_document()),      
                                    deck_url, deck_view_url, messages            
```

### `edit_deck` end-to-end

```
edit_deck(session_id, instruction, slide_indices?)     auth → permission_context
                                                       permission_service.can_edit_deck(session_id)
                                                       deck = SlideDeck.from_dict(session.deck_json)
                                                       slide_context = {
                                                         indices: slide_indices,
                                                         slide_htmls: [deck.slides[i].html for i in slide_indices]
                                                       } if slide_indices else None
                                                       chat_service.submit_chat_async(
                                                         session_id, instruction,
                                                         mode="edit",
                                                         slide_context,
                                                         correlation_id)                 ─────▶  INSERT chat_requests (pending)
                                                       return {session_id, request_id, status: pending}

(worker)                                               build_agent_for_request(config, mode="edit")
                                                       agent.run(prompt_with_slide_context)
                                                       _parse_slide_replacements(llm_html)
                                                       _apply_slide_replacements(deck, parsed)
                                                       session_manager.update_session(deck)            ─────▶  UPDATE user_sessions.deck_json
                                                       create_save_point                              ─────▶  INSERT slide_deck_versions
                                                       mark request ready                             ─────▶  UPDATE chat_requests (ready)

get_deck_status response includes replacement_info = {
  start_index, original_count, replacement_count, net_change, message
}
```

Every behavior below this level — parsing replacement slides, canvas deduplication, CSS selector-level merge, script alignment, deck preservation guards, JS validation, clarification guards, unsupported-operation hints — is existing code unchanged.

### State ownership

| State | Owner | Durability | Visible to MCP caller? |
|---|---|---|---|
| `user_sessions` row | tellr Postgres | persistent | via `session_id` + title/slide_count |
| `session_messages` | tellr Postgres | persistent | current turn only, not full history |
| `chat_requests` | tellr Postgres | persistent with cleanup | yes, via `request_id` polling |
| `slide_deck_versions` | tellr Postgres | persistent, capped | not in v1 (available via tellr UI) |
| `replacement_info` | transient | one-shot per edit response | yes |
| `ChatService._deck_cache` | process memory | until eviction | no (internal) |
| `deck`, `html_document`, `deck_url` | derived | response-time | yes |

`session.deck_json` is canonical. All MCP responses are derived projections. Concurrent browser edits remain visible to subsequent MCP polls without any staleness management, because polls read fresh from DB.

### `html_document` serialization

A new method `SlideDeck.to_html_document(chart_js_cdn: str = DEFAULT_CHART_JS_CDN) -> str` is added to `src/domain/slide_deck.py`. It produces a complete standalone HTML page: `<!doctype html>` with `<head>` carrying deck-level CSS and external script references, `<body>` carrying all slide divs in order, and per-slide Chart.js initializers appended.

Properties:

- Single pass over `SlideDeck` state; no DB access; no agent invocation.
- Deterministic output given the same input deck.
- Default Chart.js CDN is documented and overridable via the method parameter for callers in air-gapped environments.
- Included in every `ready` response alongside the structured `deck` — cheap enough that no opt-in flag is warranted.

---

## Error Handling

Errors are partitioned into three layers:

| Layer | Examples | Transport |
|---|---|---|
| **Protocol** (JSON-RPC 2.0 level) | Malformed JSON, unknown method, unknown tool, missing required fields in the envelope | JSON-RPC `error` response with standard codes (-32600 to -32603); handled automatically by FastMCP |
| **Application** (tool execution) | Auth failure, permission denied, session missing, input validation, LLM rate limit, generation failure, stuck-job timeout | Successful JSON-RPC response with `result.isError = true` and text explanation |
| **Async state** (normal operation) | Job still running, not yet ready | Normal response with `status: "pending"` or `"running"` — not an error |

### Failure-mode table

| Failure | Layer | Caller sees |
|---|---|---|
| No credentials (no header present) | Application | `isError: true`, "Authentication required" |
| Invalid or expired token | Application | `isError: true`, "Invalid or expired credentials" |
| Caller lacks CAN_VIEW / CAN_EDIT on the deck | Application | `isError: true`, "Deck not found or you do not have permission" |
| Session does not exist or is soft-deleted | Application | `isError: true`, "Deck not found" |
| `slide_indices` out of range or non-contiguous | Application | `isError: true`, with offending index and reason |
| `num_slides` out of 1–50 | Application | `isError: true`, "num_slides must be between 1 and 50" |
| `slide_style_id` or `deck_prompt_id` not found | Application (warning, non-fatal) | Log warning and fall back to defaults (existing behavior) |
| LLM rate limited by Databricks model serving | Application | `isError: true`, "Generation temporarily rate-limited, retry shortly", with `retry_after_seconds` in metadata |
| LLM output malformed after existing retries | Application | `isError: true`, "Generation failed: invalid output; deck unchanged" (deck preservation guard enforced) |
| Canvas / JS validation failure | Application | `isError: true`, "Generated slides failed chart validation" |
| Worker crashed mid-job | Application | Poll eventually returns `status: "failed"` (via lifespan recovery or 10-minute sweeper) |
| Session lock contention | Application | `isError: true`, "Deck is being modified by another request, retry shortly" |
| Unknown tool name | Protocol | JSON-RPC `-32602` Invalid params |
| Malformed JSON-RPC envelope | Protocol | JSON-RPC `-32700` Parse error or `-32600` Invalid Request |
| Internal exception (uncaught) | Application | `isError: true`, sanitized message with `correlation_id` for log lookup |

### Stuck-request recovery

Two layers of recovery ensure that no job remains in `running` indefinitely:

1. **Lifespan startup recovery** — existing `recover_stuck_requests()` in the startup path marks orphaned `running` rows as `failed` when the app boots. MCP-submitted jobs inherit this behavior.
2. **Hard timeout sweeper** — new `mark_timed_out_jobs_loop` coroutine, started in the lifespan, ticks every 60 seconds and executes one SQL update:

   ```sql
   UPDATE chat_requests
   SET status = 'failed',
       error_message = 'Generation exceeded maximum duration (10 minutes)',
       ended_at = NOW()
   WHERE status = 'running'
     AND started_at < NOW() - INTERVAL '10 minutes'
   ```

The 10-minute constant lives in `src/api/services/job_queue.py` and is tunable. The sweeper updates the database row (so the caller's next poll sees `failed`); it does not itself cancel the worker coroutine. True worker-level cancellation is deferred to v1.1.

### LLM clarification and refusal (not errors)

When the agent responds with a clarifying question or refuses a request, the response shape is identical to a successful generation: `status: "ready"`, deck content (potentially unchanged), and the agent's text carried in `messages`. Callers display the assistant message to their user and continue the conversation via a follow-up `edit_deck` call. Matches the existing browser UI behavior; no new pattern.

---

## Observability

All MCP operations emit structured logs, MLflow spans, and request-log rows consistent with the existing browser flow.

| Signal | Field |
|---|---|
| Log `event` | `mcp_tool_invoked`, `mcp_tool_error`, `mcp_auth_missing`, `mcp_timeout_sweep` |
| Log includes | `tool_name`, `session_id`, `request_id`, `user_name`, `token_source`, `correlation_id`, error class, sanitized message |
| MLflow span | Existing `generate_slides` span wraps tool-invoked generation; new attribute `source="mcp"` for filtering |
| MLflow span (edits) | Inherits `replacement_count`, `original_count`, `net_change`, `mode="edit"` attributes |
| Request log middleware | Existing `RequestLoggingMiddleware` captures `/mcp` POSTs like any other request; `correlation_id` (if supplied) indexed for cross-app traceability |
| Token logging | Token values never logged; `token_source` indicates which header was used |

---

## Rollout

### Version bump

Tellr's current line is `0.2.x`. This change is additive (no breaking API modifications to existing `/api/*` routes, no schema migrations affecting existing tables) but significant enough to warrant a minor-version bump to **`0.3.0`**.

### Deployment order

1. Merge to main → PyPI release for `databricks-tellr-app`.
2. Deploy to a dev workspace first; run the smoke script (`scripts/mcp_smoke/mcp_smoke_httpx.py`) against it with a real Databricks token.
3. Validate with an MCP client configuration pointed at the dev deployment.
4. Deploy to production workspace(s).
5. Re-run smoke against production.
6. Announce availability to the caller-facing documentation audience.

### Caller onboarding sequence

- External MCP clients (laptop agent tools) can adopt immediately using `Authorization: Bearer` with a Databricks user token.
- In-workspace Databricks Apps adopt after confirming their OBO-forwarding logic (verify they forward `x-forwarded-access-token` as `Authorization: Bearer` on the outbound call).
- Unity Catalog HTTP Connection registration is a later operational step that does not require any tellr code change.

---

## Open Verification Items

Three empirical questions to resolve via smoke test against the running tellr app before closing this spec as final:

1. **Databricks Apps proxy behavior on `Authorization: Bearer`.** When an external caller sends an `Authorization: Bearer` header to `<tellr-app-url>/mcp`, does the proxy forward it unmodified, strip it, or substitute it with a proxy-issued token? If the proxy strips it, an alternate header (e.g., `X-Tellr-Auth`) may be needed for the external-caller path.
2. **`x-forwarded-access-token` on app-to-app calls.** When one Databricks App's backend calls `<tellr-app-url>/mcp` directly, does tellr's proxy inject an `x-forwarded-access-token` header, and if so, whose identity does it carry? This determines whether the dual-token priority order is correct as specified or needs adjustment for app-to-app traffic.
3. **Identity resolution latency under load.** `current_user.me()` on every JSON-RPC call adds one identity-resolution round trip per request. Under Vibe/Stride-class traffic patterns, this should be acceptable; if it becomes a bottleneck, a short-TTL (≤ 30s) per-token identity cache can be introduced without design-level changes.

These are smoke-test-and-adjust items rather than blockers; the design proceeds on the assumption that the behavior is as expected, with verification as part of the ship checklist.

---

## v1.1 Roadmap

Explicitly captured so scope cuts in v1 do not become scope losses:

1. **Export tools** — `export_deck_pptx` and `export_deck_google_slides`, each async with polling, reusing the existing export job queue and converters.
2. **Structural edit tools** — `reorder_slides(session_id, new_order)`, `delete_slide(session_id, index)`, `duplicate_slide(session_id, index)`; non-LLM operations so callers can present full deck control without redirecting to the tellr UI.
3. **Unity Catalog HTTP Connection registration** — documented operational procedure plus recommended `USE CONNECTION` grant patterns; no tellr code change required.
4. **Raw HTML slide replacement** — `update_slide_html(session_id, index, html)` for callers that want local slide editing with server-side persistence.
5. **Worker-level cancellation** — wrap generation in `asyncio.wait_for` for true in-flight cancellation, plus a `cancel_deck(session_id, request_id)` MCP tool.
6. **SSE streaming progress** — bridge existing `streaming_callback.py` events into MCP `notifications/progress` for faster perceived latency.
7. **Save point access** — `list_save_points(session_id)` and `restore_save_point(session_id, n)` to expose tellr's versioning to MCP callers.
8. **Agent tool configurability over MCP** — `set_session_tools(session_id, tools: [...])` to expose Genie Space / Vector Index / MCP consumer / Model Endpoint / Agent Bricks tool types; unblocks data-backed generation from callers.
9. **Python library extraction** — a `databricks_tellr_core` package exposing the agent and converters for in-process embedding in other Databricks Apps.
10. **Deck thumbnails** — `get_deck_thumbnail(session_id, slide_index)` for richer caller previews (terminal hyperlinks, grid views).
11. **Bulk edit syntax** — predicate-based edit targeting once usage patterns are observed.

---

## References

- MCP (Model Context Protocol) specification, revision **2025-03-26** — the Streamable HTTP transport used by `/mcp`.
- Tellr backend overview (`docs/technical/backend-overview.md`) — existing agent pipeline, session management, slide replacement, and permission model that MCP reuses.
- Tellr database configuration (`docs/technical/database-configuration.md`) — schema for `user_sessions`, `chat_requests`, `session_messages`, `slide_deck_versions`.
- Tellr slide parser and script management (`docs/technical/slide-parser-and-script-management.md`) — HTML/canvas/script integrity rules that govern `SlideDeck.to_html_document` output.
- Tellr caller-facing integration reference (`docs/technical/mcp-server.md`) — separate deliverable; companion document for teams integrating with the MCP endpoint.
