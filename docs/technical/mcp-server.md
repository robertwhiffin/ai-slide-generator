# MCP Server

**One-Line Summary:** Call tellr programmatically from other Databricks Apps or MCP-compatible agent tools over a FastMCP Streamable HTTP endpoint — create, poll, refine, and retrieve decks without touching the browser UI.

---

## 1. Overview

tellr exposes its deck-generation capabilities as a set of Model Context Protocol (MCP) tools. External callers — other Databricks Apps, agent runtimes such as Claude Code or Claude Desktop, or any client that speaks JSON-RPC — can drive the same agent pipeline that powers the tellr browser UI:

- `create_deck` — turn a natural-language prompt into a new deck
- `get_deck_status` — poll for completion and receive the deck payload
- `edit_deck` — refine an existing deck (whole-deck or contiguous slide range)
- `get_deck` — re-read the current state of a deck on demand

**When to use it.** Reach for the MCP endpoint when another app or agent needs to generate slides on a user's behalf — for example, a sales-enablement app that kicks off a deck from a CRM record, or an internal assistant that produces a briefing on request. Reach for the browser UI when a human wants to interactively compose, reorder, or export a deck.

**Relation to the browser UI.** The MCP endpoint is a *peer* of the HTTP + SSE API that the React frontend calls; both paths share `ChatService`, `SessionManager`, and `PermissionService`. A deck created via MCP is attributed to the calling user and shows up in their tellr UI exactly like a browser-created one. The canonical editor remains tellr: MCP returns both a structured deck and a standalone HTML document, so the caller can render a preview in its own surface *and* hand the user a `deck_url` when they need the full editor (presentation mode, Google Slides / PPTX export, Monaco HTML editor, save points).

---

## 2. Prerequisites

| Requirement | Notes |
|-------------|-------|
| Deployed tellr app URL | e.g., `https://<your-tellr-app-url>`; see section 3 for how to find it |
| Databricks user token | A user PAT, Databricks Apps-injected OBO token, or `databricks auth token` output |
| MCP client or HTTP library | Claude Code / Claude Desktop / Cursor / any MCP-compatible runtime, or a raw HTTP client (`httpx`, `curl`, etc.) |
| Python 3.10+ (for code recipes) | Only needed if you use the Python recipes in section 7 |

The caller does not need any tellr-specific configuration — no client credentials, no shared secret, no registered application. Authentication is entirely via a user-scoped Databricks token.

---

## 3. Endpoint & Protocol

| Item | Value |
|------|-------|
| URL | `https://<your-tellr-app-url>/mcp/` |
| Protocol | MCP Streamable HTTP, spec revision `2025-03-26` |
| Transport | JSON-RPC 2.0 over HTTP POST |
| Required `Accept` header | `application/json, text/event-stream` |
| Session header (after `initialize`) | `mcp-session-id: <server-issued>` |

**Mandatory trailing slash.** `POST /mcp` returns `307 Temporary Redirect` to `/mcp/`. Always POST to `/mcp/` directly — the redirect will strip `POST` semantics with some clients.

**Handshake sequence.** Every session must run through the standard MCP handshake before any `tools/*` call:

1. `initialize` (request/response) — server returns an `mcp-session-id` header the client echoes on every subsequent call.
2. `notifications/initialized` (notification, no response expected; 200/202 both acceptable).
3. `tools/list`, `tools/call` — one or more.

Skipping step 2 produces spec-compliant but inconsistent behaviour from FastMCP.

**Finding your tellr app URL.** The app URL is shown on the Databricks Apps UI page for the `tellr` app, or via the CLI:

```bash
databricks apps get <your-tellr-app-name> --output json | jq -r .url
```

Use the `https://...` URL as `TELLR_URL`; do not include a trailing slash.

**SSE vs. JSON responses.** FastMCP may respond with `text/event-stream` for requests whose completion is tied to session initialisation. Clients that send the required `Accept` header must be prepared to parse a single `data: {...}` frame as well as plain JSON. The bundled Python recipe (section 7) shows a minimal decoder.

---

## 4. Authentication

tellr's MCP endpoint accepts two token sources in priority order. This is the same dual-token model documented in `src/api/mcp_auth.py`.

### 4.1 Dual-Token Model

| Priority | Header | Who sets it | Trust level |
|----------|--------|-------------|-------------|
| 1 | `x-forwarded-access-token` | The Databricks Apps proxy | Highest — cannot be spoofed from outside the proxy |
| 2 | `Authorization: Bearer <token>` | The caller | Used for external callers (laptops, agent runtimes) |

The server resolves the token to a Databricks identity via `current_user.me()`. If neither header is present, or the token is invalid/expired, the server returns a JSON-RPC error that MCP clients render as `isError: true` on the tool result.

The resolved identity is bound to request-scoped ContextVars (`current_user`, `user_client`, `permission_context`) so all downstream services — session manager, permission service, MLflow, Google OAuth — see the caller's identity with no MCP-specific plumbing.

### 4.2 Caller Recipes

Three common setups. Pick the one that matches where your code runs.

#### A. In-workspace Databricks App (OBO forwarding)

When your app is itself a Databricks App running in the same workspace as tellr, the platform injects the end user's token into your app as `x-forwarded-access-token`. Extract that token and forward it as `Authorization: Bearer` on the outbound call to tellr. See section 7.3 for a complete code example.

> **Deliberately unsupported: using your own service-principal token.** Do *not* call tellr with the service principal token that Databricks Apps also exposes to your backend. Decks created that way will be attributed to the SP, which will not match any real user in the tellr UI — they will be invisible to the people who asked for them, and permission checks on subsequent `get_deck_status` / `edit_deck` calls from a different identity will fail. Always forward the end user's `x-forwarded-access-token`.

#### B. External MCP client (Claude Code, Claude Desktop, Cursor, etc.)

External MCP runtimes register tellr in their `mcp_servers.json`-style config. Put the user's Databricks token in an env var and reference it from the config:

```json
{
  "mcpServers": {
    "tellr": {
      "url": "https://<your-tellr-app-url>/mcp/",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer ${DATABRICKS_TOKEN}"
      }
    }
  }
}
```

Refresh the token when it expires (PATs last as configured by the workspace admin; `databricks auth token` output generally refreshes automatically).

#### C. Direct HTTP

For CI scripts, smoke tests, or notebooks, speak JSON-RPC to `/mcp/` directly. See the full recipe in section 7, or the reference implementation in `scripts/mcp_smoke/mcp_smoke_httpx.py`.

---

## 5. Tool Catalog

Each tool subsection below mirrors the `@mcp.tool` descriptions in `src/api/mcp_server.py`. Input schemas are documented as tables (field / type / required / description); output schemas as annotated JSON examples.

### 5.1 `create_deck`

**Description.** Generate a new slide deck from a natural-language prompt. Returns a `session_id` and a `request_id`; the caller polls `get_deck_status` for completion. The resulting deck is attributed to the calling user and appears in their tellr UI. v1 runs prompt-only: the agent does not invoke Genie, Vector Search, or other tools. Callers that want data-backed decks should gather the data themselves and include it in the prompt.

**Input schema**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | yes | Natural-language description of the deck. Any length; longer prompts with explicit slide-by-slide structure tend to work best. |
| `num_slides` | integer (1–50) | no | Target slide count. The agent is not strictly constrained; treat as a hint. |
| `slide_style_id` | integer | no | ID of a `SlideStyle` row in tellr's config. Omit for default. |
| `deck_prompt_id` | integer | no | ID of a `DeckPrompt` row. Omit for default. |
| `correlation_id` | string | no | Opaque ID echoed in server logs for cross-system trace correlation. |

**Output schema**

```jsonc
{
  "session_id": "c4d8e2f3-...",   // Opaque; pass to subsequent tool calls
  "request_id": "r9a1b2c3-...",   // Poll this via get_deck_status
  "status": "pending"             // Always "pending" immediately after submission
}
```

**Example request**

```json
{
  "jsonrpc": "2.0", "id": 1, "method": "tools/call",
  "params": {
    "name": "create_deck",
    "arguments": {
      "prompt": "a three-slide briefing on Q3 renewals with headline metrics and risk summary",
      "num_slides": 3,
      "correlation_id": "briefing-app-4f2e"
    }
  }
}
```

**Example response**

```json
{
  "jsonrpc": "2.0", "id": 1,
  "result": {
    "content": [{"type": "text", "text": "{\"session_id\":\"c4d8...\",\"request_id\":\"r9a1...\",\"status\":\"pending\"}"}],
    "isError": false
  }
}
```

**Common errors**

| Error message | Cause | Fix |
|---------------|-------|-----|
| `prompt must be a non-empty string` | Empty or whitespace-only prompt | Send a meaningful prompt |
| `num_slides must be between 1 and 50` | Out-of-range `num_slides` | Clamp at the caller |
| `Authentication failed: ...` | Missing/invalid token | See section 4 |
| `Session is currently processing another request` | Re-submit before previous job cleared the lock | Retry after a short backoff |

### 5.2 `get_deck_status`

**Description.** Poll the status of a deck generation or edit job. Returns lightweight status while pending/running; when ready, returns the complete deck as structured slide data, a standalone HTML document, and URLs into tellr's full editor and view-only surfaces.

**Input schema**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | From the originating `create_deck` / `edit_deck` response |
| `request_id` | string | yes | From the originating `create_deck` / `edit_deck` response |

**Output schema (pending/running)**

```jsonc
{
  "session_id": "c4d8...",
  "request_id": "r9a1...",
  "status": "running",             // one of "pending", "running"
  "progress": null                  // optional progress payload when available
}
```

**Output schema (ready)**

```jsonc
{
  "session_id": "c4d8...",
  "request_id": "r9a1...",
  "status": "ready",
  "slide_count": 3,
  "title": "Q3 renewals briefing",
  "deck": {
    "title": "...",
    "slides": [ { "html": "<div class='slide'>...</div>", "scripts": "...",
                   "slide_id": "...", "created_by": "..." } ],
    "css": "/* shared CSS */",
    "external_scripts": ["https://cdn.jsdelivr.net/.../chart.umd.min.js"],
    "head_meta": {}
  },
  "html_document": "<!doctype html>...</html>",       // complete, render-ready
  "deck_url": "https://<your-tellr-app-url>/sessions/c4d8.../edit",
  "deck_view_url": "https://<your-tellr-app-url>/sessions/c4d8.../view",
  "replacement_info": null,                              // populated for edit_deck
  "messages": [ { "role": "assistant", "content": "...",
                   "message_type": "reasoning", "created_at": "..." } ],
  "metadata": {
    "tool_calls": [ ... ],
    "latency_ms": 47213,
    "experiment_url": "https://.../mlflow/...",
    "session_title": "Q3 renewals briefing"
  }
}
```

**Output schema (failed)**

```jsonc
{
  "session_id": "c4d8...",
  "request_id": "r9a1...",
  "status": "failed",
  "error": "Generation failed: <reason>"
}
```

**Status values.** `pending` → `running` → `ready` is the happy path. A terminal `failed` is returned for agent errors, tool failures, or timeouts (see section 9). A running job that exceeds 10 minutes is swept to `failed` by the server-side timeout sweeper.

**Common errors**

| Error message | Cause | Fix |
|---------------|-------|-----|
| `Deck not found or you do not have permission to view it` | Session exists but the caller's identity does not hold view access | Check that the OBO / Bearer token resolves to the deck's creator or a shared viewer |
| `Unknown request_id: ...` | `request_id` does not match any chat request, or the `session_id` does not own it | Re-check IDs; a single stray request from another session is rejected |
| `Unknown job status: ...` | Server observed an unexpected terminal state | Rare; retry or inspect server logs |

### 5.3 `edit_deck`

**Description.** Refine an existing deck through a natural-language instruction. Optionally target specific contiguous slides via `slide_indices`. The edit is applied in-place; the `session_id` and `deck_url` stay stable across edits. Returns a `request_id`; the caller polls `get_deck_status` for completion and receives the updated deck plus `replacement_info` summarising what changed.

**Input schema**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | The deck to edit |
| `instruction` | string | yes | Natural-language change request |
| `slide_indices` | array of integers | no | Contiguous range (e.g., `[2, 3, 4]`); omit to target the whole deck |
| `correlation_id` | string | no | Echoed in server logs |

**Contiguity constraint.** `slide_indices` must be a single contiguous slice. `[2, 3, 4]` is valid; `[2, 4]` raises `slide_indices must be contiguous (e.g. [2, 3, 4], not [2, 4])`. For disjoint edits, issue one call per slice.

**Output schema.** Identical shape to `create_deck` — `{ session_id, request_id, status: "pending" }`. Poll `get_deck_status` to receive the updated deck. `replacement_info` on the ready response describes what changed (the same structure as `ChatResponse.replacement_info`).

**Example request**

```json
{
  "jsonrpc": "2.0", "id": 2, "method": "tools/call",
  "params": {
    "name": "edit_deck",
    "arguments": {
      "session_id": "c4d8...",
      "instruction": "Make the EMEA section more prominent and add Q3 vs Q2 deltas",
      "slide_indices": [1, 2],
      "correlation_id": "briefing-app-4f2e"
    }
  }
}
```

**Common errors**

| Error message | Cause | Fix |
|---------------|-------|-----|
| `Deck not found or you do not have permission to edit it` | Caller lacks `CAN_EDIT` on the deck | Use an identity that is the creator or a shared editor |
| `slide_indices must be contiguous ...` | Non-contiguous indices | Split into multiple calls |
| `slide_indices contains out-of-range index: ...` | Index ≥ `slide_count` or negative | Fetch `get_deck` first to confirm current count |

### 5.4 `get_deck`

**Description.** Retrieve the current state of a deck without submitting new work. Returns structured slide data, a standalone HTML document, and URLs into tellr's editor — same payload as a ready `get_deck_status` response, without `status` / `request_id` / `messages`. Idempotent; no job queue interaction. Use when you have a `session_id` from earlier and want to re-render without polling.

**Input schema**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | The deck to retrieve |

**Output schema**

```jsonc
{
  "session_id": "c4d8...",
  "slide_count": 3,
  "title": "Q3 renewals briefing",
  "deck": { ... },                                         // same shape as get_deck_status "ready"
  "html_document": "<!doctype html>...",
  "deck_url": "https://<your-tellr-app-url>/sessions/c4d8.../edit",
  "deck_view_url": "https://<your-tellr-app-url>/sessions/c4d8.../view"
}
```

**Common errors**

| Error message | Cause | Fix |
|---------------|-------|-----|
| `Deck not found: session_id=...` | No session with that ID | Verify `session_id` |
| `Deck not found or you do not have permission to view it` | Caller lacks view access | Share the deck, or call with the creator's identity |

---

## 6. Component Responsibilities

| File | Responsibility | Talks to |
|------|----------------|----------|
| `src/api/mcp_server.py` | Declares `FastMCP` instance; registers the four `@mcp.tool` handlers; builds request-scoped auth scope for each call. | `ChatService`, `SessionManager`, `PermissionService`, `job_queue` |
| `src/api/mcp_auth.py` | Dual-token resolution: reads `x-forwarded-access-token` or `Authorization: Bearer`, calls `current_user.me()`, binds `current_user` / `user_client` / `permission_context` ContextVars. | Databricks SDK (`WorkspaceClient`) |
| `src/api/main.py` | Mounts the FastMCP sub-app at `/mcp` with `streamable_http_path="/"`, so external POSTs to `/mcp/` route correctly. Starts the 10-minute timeout sweeper on lifespan. | `tellr_mcp.streamable_http_app()` |
| `src/api/services/job_queue.py` | In-process asyncio queue for chat jobs. Timeout sweeper flips stuck `running` jobs to `failed` after `JOB_HARD_TIMEOUT_SECONDS = 600`. | `chat_requests` table |
| `src/domain/slide_deck.py` | `SlideDeck.to_html_document()` emits the standalone HTML payload returned in `html_document`. CSS is sanitized; slide content is HTML-escaped to prevent XSS through MCP consumers. | — |
| `src/services/permission_service.py` | `can_view_deck` / `can_edit_deck` checks used before every tool that touches a deck. Creator short-circuit lets a freshly created session be viewed/edited before any `DeckContributor` row exists. | `user_sessions`, `deck_contributors` |

---

## 7. Client Recipes

All recipes assume you have already completed section 4 (authentication setup).

### 7.1 Python `httpx` — full `create → poll → ready`

Lightly edited from `scripts/mcp_smoke/mcp_smoke_httpx.py`; drop into any Python environment with `httpx` installed.

```python
import json, os, time, httpx

TELLR_URL = os.environ["TELLR_URL"].rstrip("/")
MCP_URL = f"{TELLR_URL}/mcp/"
HEADERS = {
    "Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

def decode(resp: httpx.Response) -> dict:
    """Handle both plain JSON and text/event-stream responses."""
    if "event-stream" in resp.headers.get("content-type", "").lower():
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise RuntimeError("SSE response without data frame")
    return resp.json()

# 1. initialize -> grab mcp-session-id
r = httpx.post(MCP_URL, headers=HEADERS, timeout=30, json={
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "my-app", "version": "1.0"}}})
r.raise_for_status()
mcp_headers = {**HEADERS, "mcp-session-id": r.headers["mcp-session-id"]}

# 2. notifications/initialized (required before tools/*)
httpx.post(MCP_URL, headers=mcp_headers, timeout=30, json={
    "jsonrpc": "2.0", "method": "notifications/initialized"})

# 3. create_deck
r = httpx.post(MCP_URL, headers=mcp_headers, timeout=60, json={
    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
    "params": {"name": "create_deck",
               "arguments": {"prompt": "a three-slide intro to our product",
                             "correlation_id": "demo-1"}}})
r.raise_for_status()
payload = json.loads(decode(r)["result"]["content"][0]["text"])
session_id, request_id = payload["session_id"], payload["request_id"]

# 4. poll get_deck_status (10-min deadline matches JOB_HARD_TIMEOUT_SECONDS)
deadline = time.time() + 600
while time.time() < deadline:
    r = httpx.post(MCP_URL, headers=mcp_headers, timeout=60, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_deck_status",
                   "arguments": {"session_id": session_id,
                                 "request_id": request_id}}})
    r.raise_for_status()
    payload = json.loads(decode(r)["result"]["content"][0]["text"])
    status = payload.get("status")
    if status == "ready":
        print("slides:", payload["slide_count"], "url:", payload["deck_url"])
        break
    if status == "failed":
        raise RuntimeError(payload.get("error"))
    time.sleep(2)
else:
    raise TimeoutError("generation did not complete within 10 minutes")
```

### 7.2 Claude Code / Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "tellr": {
      "url": "https://<your-tellr-app-url>/mcp/",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer ${DATABRICKS_TOKEN}"
      }
    }
  }
}
```

Put your token in `DATABRICKS_TOKEN` before starting the agent. All four tools (`create_deck`, `get_deck_status`, `edit_deck`, `get_deck`) become available to the agent automatically.

### 7.3 Databricks App backend (OBO forwarding, pseudocode)

```python
# FastAPI handler inside your own Databricks App.
@app.post("/generate-briefing")
async def generate_briefing(request: Request) -> dict:
    # The Databricks Apps proxy injects the end user's token here.
    user_token = request.headers.get("x-forwarded-access-token")
    if not user_token:
        raise HTTPException(status_code=401, detail="missing OBO token")

    # Forward it as Bearer on the outbound call to tellr; then drive the
    # initialize -> notifications/initialized -> tools/call -> poll flow
    # exactly as in recipe 7.1, substituting user_token for DATABRICKS_TOKEN.
    ...
```

Exchanging the PAT-derived `DATABRICKS_TOKEN` in recipe 7.1 for the request-scoped `user_token` is the entire delta. Do not cache or reuse `user_token` across requests — it is the end user's OBO token and belongs to that request only.

---

## 8. Rendering Recipes

`get_deck_status` and `get_deck` both return a ready-to-render `html_document` *and* the structured `deck` payload. Pick whichever matches your UI.

### 8.1 Minimal: iframe with `srcdoc`

```tsx
<iframe
  title="Deck preview"
  srcDoc={htmlDocument}  // the html_document field, rendered raw
  sandbox="allow-scripts"
  style={{ width: "100%", aspectRatio: "16 / 9", border: 0 }}
/>
```

> **HTML-escape the attribute value.** When you interpolate `html_document` into an HTML attribute (e.g., `srcdoc=`), escape it the way your framework normally escapes attribute content. React's `srcDoc` prop does this automatically. In hand-written HTML, make sure `"` in the document becomes `&quot;`.

### 8.2 Custom grid: iterate `deck.slides`

```tsx
export function SlideGrid({ deck }: { deck: Deck }) {
  return (
    <div className="slide-grid">
      <style>{deck.css}</style>
      {deck.external_scripts.map(src => <script key={src} src={src} />)}
      {deck.slides.map((slide, i) => (
        <article
          key={slide.slide_id ?? i}
          dangerouslySetInnerHTML={{ __html: slide.html }}
        />
      ))}
    </div>
  );
}
```

The `.slide` wrapper invariant is preserved — tellr never emits a slide without one — so your CSS can rely on `.slide { ... }` selectors.

### 8.3 Air-gapped environments

`html_document` embeds a Chart.js reference via a default CDN (`cdn.jsdelivr.net`). In environments where that CDN is unreachable:

- **v1 (current):** `SlideDeck.to_html_document(chart_js_cdn=…)` is *not* exposed as a parameter on `create_deck` / `edit_deck`. The caller can still serve the returned `html_document` through a proxy that rewrites the CDN URL (e.g., a reverse proxy that rewrites `cdn.jsdelivr.net/npm/chart.js/...` to an internal mirror). The `external_scripts` field on the structured deck makes this rewrite trivial for custom renderers.
- **v1.1 (planned):** a configurable `chart_js_cdn` argument on `create_deck` / `edit_deck`, surfaced as a tool parameter.

---

## 9. Integration Best Practices

| Topic | Practice |
|-------|----------|
| Polling cadence | Poll `get_deck_status` every 1–2 seconds with a small backoff if the server is under load. Do not poll faster than 500 ms — the endpoint is not optimised for sub-second polling and you will see the timeout sweeper cost in headroom. |
| Error retry | Respect any `retry_after_seconds` hint on rate-limit responses; otherwise back off exponentially. `isError: true` on a tool result is *application* failure, not transport failure — do not retry blindly. |
| Identity | Always forward the end user's OBO token (section 4.2 recipe A). Never call with a service-principal token if the deck should surface to a specific user. |
| Correlation IDs | Pass a `correlation_id` on every `create_deck` / `edit_deck` call. It flows through server logs, worker state, and the chat request row, making cross-system traces trivial. |
| Trailing slash | Always POST to `/mcp/`. `POST /mcp` returns `307 Temporary Redirect`, which some HTTP clients silently downgrade to `GET`. |
| Handshake | After `initialize`, send `notifications/initialized` before any `tools/*` call. |
| Hand-off vs. render | Prefer `deck_url` when the user needs the full tellr editor (presentation mode, Google Slides / PPTX export, Monaco HTML editing, save points). Render `html_document` / iterate `deck.slides` for passive previews or custom editing UIs. |
| Session lifetime | One session = one deck. Reuse the same `session_id` for subsequent `edit_deck` / `get_deck` calls so you benefit from the session lock and chat history. A new `create_deck` call starts a fresh session. |

---

## 10. Troubleshooting

| Symptom | Likely cause | What to try |
|---------|--------------|-------------|
| `401` / `Authentication failed` with a token that works elsewhere | Proxy or gateway stripped `Authorization` on the way in; or `x-forwarded-access-token` absent when the caller expected it | Log the exact headers the tellr process received; if you are running behind an extra proxy, ensure it preserves `Authorization` unmodified |
| `status: running` never transitions to `ready` | Worker stuck or generation truly slow | The timeout sweeper marks jobs `failed` after 10 minutes (`JOB_HARD_TIMEOUT_SECONDS`). If you reliably exceed that, inspect server logs for the MLflow experiment URL in the `metadata` field of a successful call to see where the agent stalls. |
| Deck generated via MCP does not appear in the tellr UI for the intended user | Caller forwarded a service-principal token instead of the user's OBO token | Switch to OBO forwarding (section 4.2 recipe A). Decks created under the SP identity are not visible to any workspace user. |
| `isError: true` with a "permission" message on `get_deck_status` / `edit_deck` / `get_deck` | Caller identity does not match the deck's `created_by` or any `DeckContributor` row | Check `created_by` on the session. Either call with that user's token or share the deck to the calling user via tellr's UI. |
| Chart.js fails to load in an air-gapped environment | Default CDN unreachable | See section 8.3 — rewrite the CDN URL through a proxy; v1.1 will expose `chart_js_cdn` as a tool parameter. |
| `initialize` returns no `mcp-session-id` header | Deployment did not pick up the MCP router | Redeploy tellr; check `/api/health`; confirm `app.mount("/mcp", ...)` ran by looking for `MCP server mounted at /mcp` in the app logs. |
| Client receives HTML instead of JSON on the first POST | Target URL is `/mcp` (no trailing slash) and the client followed the 307 to a GET | Always POST to `/mcp/` directly |

---

## 11. Versioning & Changelog

| Version | Tellr release | Notes |
|---------|---------------|-------|
| v1.0 | 0.3.0 | Initial release. Four tools: `create_deck`, `get_deck_status`, `edit_deck`, `get_deck`. Dual-token auth. Prompt-only generation (no Genie / Vector Search / other tools). 10-minute hard timeout. |
| v1.1 (planned) | TBD | Export tools (`export_pptx`, `export_google_slides`), structural edit tools (reorder / insert / delete at slide granularity), `chart_js_cdn` passthrough. See the design spec's "Deferred items" section for the full list. |

---

## 12. Cross-References

- [MCP server design spec](../superpowers/specs/2026-04-22-tellr-mcp-server-design.md) — architecture rationale, open verification items, and deferred feature list
- [Backend Overview](./backend-overview.md) — FastAPI entry points, `ChatService`, `SessionManager`, `PermissionService`
- [Real-Time Streaming](./real-time-streaming.md) — the polling + `chat_requests` infrastructure that MCP tools reuse
- [Permissions Model](./permissions-model.md) — `can_view_deck` / `can_edit_deck` semantics and the `DeckContributor` rows
- [Databricks App Deployment](./databricks-app-deployment.md) — deployment CLI, workspace URL discovery
