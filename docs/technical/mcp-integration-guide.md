# Tellr MCP Integration Guide

**One-line:** How to call tellr's deck-generation tools from another app or from an MCP-compatible agent, with the gotchas we learned the hard way.

This is a **how-to** for builders. For the protocol-level reference (tool schemas, JSON-RPC shapes, response payloads) see [`mcp-server.md`](./mcp-server.md).

---

## 1. Which integration pattern is yours?

Two distinct patterns, different auth, different code:

| Pattern | When to use | Auth source |
|---|---|---|
| **A. Databricks App → tellr** (in-workspace) | You're building another Databricks App that should create decks on behalf of the signed-in user. | Identity headers injected by the Databricks Apps proxy (`x-forwarded-email`, `x-forwarded-user`). No token — tellr trusts the proxy. |
| **B. External agent → tellr** (laptop / CI / CLI) | You're wiring tellr into an MCP client like Claude Code, Claude Desktop, or Cursor, or calling from a script outside Databricks Apps. | User OAuth (U2M) access token from a `databricks-cli` profile, sent as `Authorization: Bearer`. **PATs do not work against Databricks Apps** — see §3.1. |

Pick one and jump to its section. If you need both (e.g., a tool that runs in an app but also has a local-dev mode), build each path separately rather than trying to unify them — the auth models are fundamentally different.

---

## 2. Part A — Databricks App → tellr

### 2.1 Why this path looks different

When Databricks App A calls Databricks App B (both in the same workspace), the Databricks Apps proxy sits between them and **re-writes the auth layer**:

- Any `Authorization: Bearer <token>` header the caller sends is **stripped on ingress** (security: prevents a malicious app from replaying tokens it shouldn't have).
- Any caller-supplied `x-forwarded-access-token` is also **stripped**.
- Instead, the proxy **injects** `x-forwarded-email`, `x-forwarded-user`, `x-forwarded-preferred-username` based on the signed-in user who hit app A.

Net result: **the receiving app cannot get a user token; it only gets a proxy-attested identity.** Any Databricks SDK calls the receiving app needs to make use the receiving app's own service principal credentials. User attribution (who created the deck, whose name shows in tellr's UI) still comes from the forwarded identity headers.

Tellr supports this explicitly. When the `TELLR_TRUST_FORWARDED_IDENTITY` env var is set on tellr's deployment (it is, by default), `x-forwarded-email` + `x-forwarded-user` are accepted as identity — *only* from the Databricks Apps proxy, because the proxy strips any caller-supplied versions first.

### 2.2 Minimal working integration (Streamlit example)

The harness below is a complete Databricks App that creates a deck on tellr via MCP and renders it inline. Drop it into a workspace folder, deploy as a Databricks App, done.

**`app.py`:**

```python
"""Minimum viable tellr MCP integration for a Databricks App."""

from __future__ import annotations
import json, time, uuid
import httpx
import streamlit as st

st.set_page_config(page_title="Tellr integration", layout="centered")
st.title("Tellr integration")

# ---- Identity: read forwarded identity from the proxy ---------------------
# The Databricks Apps proxy sets these on every inbound request. If they're
# absent, you're running locally — stop and explain.
email = st.context.headers.get("x-forwarded-email")
if not email:
    st.error(
        "Not running behind the Databricks Apps proxy. "
        "Deploy this app to a Databricks workspace to test the integration."
    )
    st.stop()

st.caption(f"Signed in as: {email}")

# ---- Inputs ---------------------------------------------------------------
tellr_url = st.text_input(
    "Tellr app URL",
    placeholder="https://<tellr-app>.databricksapps.com",
).rstrip("/")
prompt = st.text_area("Prompt", height=120)
generate = st.button(
    "Generate",
    disabled=not (tellr_url and prompt.strip()),
    type="primary",
)


# ---- MCP helpers ----------------------------------------------------------
def _decode(resp: httpx.Response) -> dict:
    """MCP may respond with JSON or SSE; handle both."""
    if "event-stream" in resp.headers.get("content-type", "").lower():
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise RuntimeError("SSE response without data frame")
    return resp.json()


def _rpc(
    client: httpx.Client, url: str, method: str,
    params: dict | None = None, id_: int | None = None,
    extra_headers: dict | None = None,
) -> tuple[httpx.Response, dict | None]:
    body = {"jsonrpc": "2.0", "method": method}
    if id_ is not None: body["id"] = id_
    if params is not None: body["params"] = params
    resp = client.post(url, json=body, headers=extra_headers or {})
    resp.raise_for_status()
    return resp, (_decode(resp) if id_ is not None else None)


def _open_session(client: httpx.Client, url: str) -> dict:
    """Run initialize + notifications/initialized; return any session header.

    tellr runs FastMCP stateless, so the server does not emit
    ``mcp-session-id``. We still run the handshake shape real clients
    send, and forward a session id if the server does return one.
    """
    init_resp, _ = _rpc(client, url, "initialize", params={
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "my-app", "version": "0.1"},
    }, id_=1)
    sid = init_resp.headers.get("mcp-session-id")
    headers = {"mcp-session-id": sid} if sid else {}
    _rpc(client, url, "notifications/initialized", extra_headers=headers)
    return headers


def generate_deck(tellr_base: str, prompt_text: str, status) -> dict:
    """Submit create_deck → poll get_deck_status → return ready payload."""
    mcp = f"{tellr_base}/mcp"
    correlation = f"my-app-{uuid.uuid4().hex[:8]}"

    # No Authorization header, no x-forwarded-access-token — the proxy
    # will strip them. Tellr identifies the user via the forwarded headers
    # that *its own* inbound proxy sets.
    base_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    with httpx.Client(timeout=60, headers=base_headers) as c:
        # Submit
        status.info(f"Submitting… correlation_id={correlation}")
        sess_hdrs = _open_session(c, mcp)
        _, payload = _rpc(c, mcp, "tools/call", params={
            "name": "create_deck",
            "arguments": {"prompt": prompt_text, "correlation_id": correlation},
        }, id_=2, extra_headers=sess_hdrs)
        if payload["result"].get("isError"):
            raise RuntimeError(payload["result"]["content"][0]["text"])
        submit = json.loads(payload["result"]["content"][0]["text"])

        # Poll — fresh MCP session per iteration; see gotcha below
        deadline = time.time() + 600
        n = 100
        while time.time() < deadline:
            time.sleep(2)
            poll_hdrs = _open_session(c, mcp)
            _, payload = _rpc(c, mcp, "tools/call", params={
                "name": "get_deck_status",
                "arguments": {
                    "session_id": submit["session_id"],
                    "request_id": submit["request_id"],
                },
            }, id_=n, extra_headers=poll_hdrs)
            n += 1
            if payload["result"].get("isError"):
                raise RuntimeError(payload["result"]["content"][0]["text"])
            data = json.loads(payload["result"]["content"][0]["text"])
            status.info(
                f"status={data['status']} "
                f"elapsed={int(time.time() - (deadline - 600))}s"
            )
            if data["status"] == "ready":
                return data
            if data["status"] == "failed":
                raise RuntimeError(data.get("error", "generation failed"))

    raise TimeoutError("Generation did not complete within 10 minutes")


# ---- Wire it up -----------------------------------------------------------
if generate:
    slot = st.empty()
    try:
        result = generate_deck(tellr_url, prompt.strip(), slot)
    except Exception as e:
        slot.error(f"Failed: {e}")
    else:
        slot.success(f"Ready — {result['slide_count']} slides, "
                     f"title: {result['title']!r}")
        st.link_button("Open in tellr", result["deck_url"])
        st.components.v1.html(
            result["html_document"], height=600, scrolling=True
        )
```

**`app.yaml`:**

```yaml
command:
  - "sh"
  - "-c"
  - |
    pip install -r requirements.txt && streamlit run app.py \
      --server.port=$DATABRICKS_APP_PORT \
      --server.address=0.0.0.0 \
      --server.headless=true
```

**`requirements.txt`:**

```
streamlit>=1.32
httpx>=0.27
```

### 2.3 Deploy

```bash
databricks apps create my-tellr-integration
databricks apps deploy my-tellr-integration \
  --source-code-path /Workspace/Users/<you>@databricks.com/<folder>
```

Open the deployed app's URL, paste your tellr app URL, enter a prompt, click Generate. The resulting deck appears both in-app (iframe) and in the tellr UI attributed to you.

### 2.4 Gotchas we learned

**Gotcha 1 — Don't send `Authorization: Bearer` or forward the OBO token.**
It gets stripped by the proxy. Tellr sees nothing and returns "Authentication required: no credentials presented." The correct pattern is to send no auth headers at all from your app and rely on the proxy's identity headers.

**Gotcha 2 — Tellr's MCP endpoint is stateless; don't require `mcp-session-id`.**
Tellr runs FastMCP with `stateless_http=True` because the app is served by multiple uvicorn workers and the Databricks Apps proxy does not guarantee session affinity — a stateful handshake's three requests (`initialize` → `notifications/initialized` → `tools/call`) can otherwise split across workers and produce HTTP 404 `"Session not found"`. In stateless mode the server doesn't emit `mcp-session-id` at all; read it with `.get()` rather than `[…]` and only echo it on follow-ups if it's present. The server-side deck session (identified by `session_id` + `request_id` in the `create_deck` response) is a separate app-level concept and is fully persistent.

**Gotcha 3 — `deck_url` might be relative.**
If tellr's `DATABRICKS_APP_URL` env var is unset, `deck_url` comes back as a path-only string like `/sessions/.../edit`. Rendered in your app, the browser will resolve it against *your app's* origin, not tellr's. Databricks Apps sets `DATABRICKS_APP_URL` automatically on production deployments, so this should only bite during local dev or misconfigured environments.

**Gotcha 4 — Generation time.**
Single-slide prompts generate in ~10-30s, 10-slide decks take 3-8 minutes. The hard server-side timeout is 10 minutes (`JOB_HARD_TIMEOUT_SECONDS`). Match your client deadline to it or shorter.

**Gotcha 5 — `x-forwarded-email` is authoritative; you don't need to verify it.**
The proxy sets it, strips any caller-supplied version, and signs the whole interaction with TLS. Trusting it at face value is safe *only* when you're behind the Databricks Apps proxy. Don't copy this pattern to services that aren't.

---

## 3. Part B — External agent → tellr (Claude Code / Cursor / CLI)

When your MCP client is running *outside* Databricks Apps — on your laptop, in CI, or in a non-Databricks service — the proxy isn't in the way and Databricks Apps will accept a user bearer token in the `Authorization` header. Two ways to get that token in place:

1. **§3.2 Auto-discovered OAuth (recommended).** Your MCP client does the full OAuth dance itself: browser consent once, refresh token cached, silent renewal thereafter. Works with any MCP-spec-compliant client.
2. **§3.3 Static OAuth token (fallback).** You mint the token yourself with the Databricks CLI and paste it into the client's header config. Simple; requires manual refresh every ~1 hour.

Whichever path you pick, the one thing you **can't** do is use a PAT — see §3.1.

### 3.1 Auth constraint: OAuth U2M only, not PATs

**Verified gotcha:** even a PAT that works against workspace APIs returns HTTP 401 from an app's `/mcp` endpoint. The Apps proxy has its own authorization layer and only accepts OAuth U2M tokens for app-scoped access. Concretely:

```bash
# PAT against workspace API — works:
curl -sS -o /dev/null -w "%{http_code}\n" \
  "https://<workspace>/api/2.0/preview/scim/v2/Me" \
  -H "Authorization: Bearer dapi<...>"
# → 200

# Same PAT against the tellr app's MCP endpoint — rejected:
curl -sS -o /dev/null -w "%{http_code}\n" -X POST \
  "https://<tellr-app-url>/mcp" \
  -H "Authorization: Bearer dapi<...>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
# → 401
```

Save PATs for workspace REST APIs; for Databricks Apps (including tellr), always use an OAuth user access token.

### 3.2 Auto-discovered OAuth (recommended, general-purpose)

This is a spec-level feature — not Claude Code specific. The [MCP authorization spec](https://modelcontextprotocol.io/specification/) uses [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) *OAuth 2.0 Protected Resource Metadata* plus OAuth 2.1 with Dynamic Client Registration. Any spec-compliant MCP client (Claude Code, Claude Desktop, Cursor, VS Code MCP, Continue, etc.) can auto-discover the OAuth server and run the flow on your behalf.

How it works end-to-end:

1. You register the MCP server in your client with a URL and **no** bearer header.
2. First tool call goes unauthenticated → server returns HTTP 401 with a `WWW-Authenticate` header pointing at `/.well-known/oauth-protected-resource`.
3. Client fetches that metadata — for a Databricks App it looks like:
   ```json
   {
     "resource": "https://<tellr-app-url>",
     "authorization_servers": ["https://<workspace>/oidc"],
     "scopes_supported": ["sql", "iam.current-user:read", ...]
   }
   ```
4. Client performs Dynamic Client Registration against the authorization server, opens a browser for user consent, receives an access token + refresh token, and caches them.
5. Subsequent calls use the access token; when it expires, the client uses the refresh token to mint a new one silently. **No manual refresh ever.**

First-tool-call UX: a browser tab pops open for consent. Afterwards, invisible.

**Client-specific wiring:**

*Claude Code:*

```bash
claude mcp add --transport http tellr "https://<tellr-app-url>/mcp"
# (no --header flag — that's what triggers the OAuth flow on first use)
```

Then in a Claude session, invoke any tellr tool (or run `/mcp`); a browser window opens for consent, you sign in, done.

*Cursor / other streamable-HTTP clients:* drop the `headers` block from your config:

```json
{
  "mcpServers": {
    "tellr": {
      "url": "https://<tellr-app-url>/mcp",
      "transport": "streamable-http"
    }
  }
}
```

*Generic:* any client that claims MCP authorization support needs only the URL; it will handle discovery + browser consent + refresh token storage itself.

**When auto-discovery won't work:**

- Your MCP client hasn't implemented the MCP authorization spec yet (check its release notes).
- You're running headless / in CI / on a box with no browser — the OAuth consent step can't complete interactively. Use §3.3.
- You need to pin a specific identity (e.g., a service principal) rather than the interactive user who runs the consent flow.

### 3.3 Static OAuth token (fallback)

When your client doesn't support MCP OAuth discovery, or you're running headless, you can mint an OAuth U2M token via the Databricks CLI and paste it into the client's header config yourself.

One-time profile setup in `~/.databrickscfg`:

```ini
[tellr-dev-oauth]
host      = https://<tellr-workspace>.cloud.databricks.com/
auth_type = databricks-cli
```

One-time OAuth handshake (opens a browser, caches the refresh token locally under `~/.databricks/`):

```bash
databricks auth login -p tellr-dev-oauth
```

Then `databricks auth token -p tellr-dev-oauth` silently mints a fresh ~1-hour access token on demand (using the cached refresh token — no browser round-trip):

```bash
databricks auth token -p tellr-dev-oauth | jq -r .access_token
```

Wire it up:

*Claude Code:*

```bash
claude mcp add --transport http tellr "https://<tellr-app-url>/mcp" \
  --header "Authorization: Bearer $(databricks auth token -p tellr-dev-oauth | jq -r .access_token)"

claude mcp list | grep tellr
# → tellr: https://<tellr-app-url>/mcp (HTTP) - ✓ Connected
```

*Cursor / generic:*

```json
{
  "mcpServers": {
    "tellr": {
      "url": "https://<tellr-app-url>/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer <paste output of `databricks auth token -p tellr-dev-oauth | jq -r .access_token` here>"
      }
    }
  }
}
```

### 3.4 Refreshing a static token

Only applies to §3.3 — §3.2 handles refresh automatically.

`claude mcp add` captures `--header` as a **static string**; it is not re-evaluated per call. OAuth access tokens expire after ~1 hour; once expired, every tool call returns 401 and the client reports "Authentication failed."

Re-register with a fresh token. Keep it as a shell function:

```bash
tellr-refresh() {
  claude mcp remove tellr 2>/dev/null
  claude mcp add --transport http tellr "https://<tellr-app-url>/mcp" \
    --header "Authorization: Bearer $(databricks auth token -p tellr-dev-oauth | jq -r .access_token)"
}
```

Run `tellr-refresh` whenever you see 401s, or at the start of any session that's been idle for more than an hour. Refresh completes in under a second.

For unattended runs longer than an hour (CI, background agents):

- Re-run `tellr-refresh` on a timer (cron, `launchd`, `systemd` timer) every ~45 minutes, **or**
- Wrap tellr in a tiny local stdio→HTTP MCP proxy that reads a fresh token per request — equivalent behaviour to §3.2 for clients that don't yet speak MCP OAuth.

### 3.5 Gotchas

**PATs → 401 from the Apps proxy.** Don't use long-lived PATs for app access; see §3.1.

**App-level access is a separate check.** OAuth authenticates *who you are*; the Apps proxy additionally checks you're on the app's user list. If sign-in succeeds but `/mcp` still returns 403, ask the app owner to grant your user access.

**Trailing slash on the URL.** Both `/mcp` and `/mcp/` work; a path-rewrite middleware in tellr accepts either. The `claude mcp add` command sometimes strips the slash — that's fine. (Older builds returned `405 Method Not Allowed` for `/mcp` without a slash; if you're hitting that against a pinned-old deployment, add the slash.)

**Handshake.** After `initialize`, MCP requires a `notifications/initialized` before any `tools/*`. Official MCP clients handle this for you; if you're writing raw HTTP, don't skip it.

---

## 4. Reference appendix

### 4.1 Tool catalog summary

| Tool | Purpose | Key inputs | Key outputs |
|---|---|---|---|
| `create_deck` | Generate a new deck from a prompt | `prompt`, `num_slides?` | `session_id`, `request_id`, `status: pending` |
| `get_deck_status` | Poll for completion and retrieve ready deck | `session_id`, `request_id` | `status`, plus (on ready) `deck`, `html_document`, `deck_url`, `deck_view_url` |
| `edit_deck` | Refine an existing deck via instruction | `session_id`, `instruction`, `slide_indices?` | `request_id` (poll via `get_deck_status`) |
| `get_deck` | Re-read current deck state without submitting work | `session_id` | Same shape as `get_deck_status` ready response, minus `status`/`messages` |

Full schemas and examples: [`mcp-server.md`](./mcp-server.md) section 5.

### 4.2 Common errors

| Error text | Cause | Fix |
|---|---|---|
| `Authentication required: no credentials presented` | No auth headers arrived (proxy stripped them, or external caller didn't send a Bearer). | App-to-app: confirm `x-forwarded-email` is set on your app's inbound requests. External: check your Bearer header is reaching tellr (curl the `/api/health` endpoint with the same token). |
| `HTTP 401` (empty body `{}`) on external `/mcp` calls | You're using a PAT (`dapi...`); the Apps proxy rejects PATs for app access. | Switch to an OAuth U2M token via a `databricks-cli` auth profile — see §3.1. |
| `HTTP 401` mid-session after working fine earlier | OAuth access token (~1-hour lifetime) has expired; `claude mcp add` stored it as a static header. | Re-register the MCP server with a fresh token — see §3.3 (`tellr-refresh` one-liner). |
| `HTTP 404 {"message": "Session not found"}` | Your client is echoing an `mcp-session-id` against tellr's stateless endpoint while the request is routed to a different worker than the one that (historically) issued the id. Should not occur with current tellr builds. | Treat `mcp-session-id` as optional — read with `.get()`, only echo when present. Upgrade to a current tellr build if calls against a prior deployment produce this error. |
| `create_deck tool error: ...` | Tool execution failed after auth succeeded (LLM error, input validation, etc.). | Read the error text — it's the underlying reason. |
| `Deck not found or you do not have permission to view it` | Your identity doesn't match the deck's creator and you're not a contributor. | Check `created_by` on the deck; use the creator's identity or share the deck. |

### 4.3 v1 limitations

- **Prompt-only generation.** The agent does not call Genie, Vector Search, or other data tools on your behalf. If you want data-backed decks, gather the data yourself and include it in the prompt.
- **No exports over MCP.** `export_pptx` / `export_google_slides` are v1.1; for now, hand users to `deck_url` for exports in the tellr UI.
- **No structural edits.** Reorder / delete / duplicate slides are v1.1.
- **No cancellation.** There's a 10-minute hard timeout but no way to abort an in-flight generation.
- **No streaming progress.** Status transitions are polling-based; `notifications/progress` is v1.1.

### 4.4 Further reading

- [`mcp-server.md`](./mcp-server.md) — protocol-level reference, full tool schemas, transport details.
- [`permissions-model.md`](./permissions-model.md) — `can_view_deck` / `can_edit_deck` semantics.

### 4.5 Getting help

- Something broken? Include the `correlation_id` from your tool error — server logs are keyed on it.
- Design question / feature request? Open a PR against the design spec v1.1 roadmap section.
