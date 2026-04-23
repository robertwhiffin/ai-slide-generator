# Tellr MCP Integration Guide

**One-line:** How to call tellr's deck-generation tools from another app or from an MCP-compatible agent, with the gotchas we learned the hard way.

This is a **how-to** for builders. For the protocol-level reference (tool schemas, JSON-RPC shapes, response payloads) see [`mcp-server.md`](./mcp-server.md).

---

## 1. Which integration pattern is yours?

Two distinct patterns, different auth, different code:

| Pattern | When to use | Auth source |
|---|---|---|
| **A. Databricks App → tellr** (in-workspace) | You're building another Databricks App that should create decks on behalf of the signed-in user. | Identity headers injected by the Databricks Apps proxy (`x-forwarded-email`, `x-forwarded-user`). No token — tellr trusts the proxy. |
| **B. External agent → tellr** (laptop / CI / CLI) | You're wiring tellr into an MCP client like Claude Code, Claude Desktop, or Cursor, or calling from a script outside Databricks Apps. | User-supplied Databricks PAT, sent as `Authorization: Bearer`. |

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
    """Run initialize + notifications/initialized; return mcp-session-id header.

    Each tool call should open its own session — see "Gotcha: MCP session
    lifetime" below for why.
    """
    init_resp, _ = _rpc(client, url, "initialize", params={
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "my-app", "version": "0.1"},
    }, id_=1)
    sid = init_resp.headers["mcp-session-id"]
    headers = {"mcp-session-id": sid}
    _rpc(client, url, "notifications/initialized", extra_headers=headers)
    return headers


def generate_deck(tellr_base: str, prompt_text: str, status) -> dict:
    """Submit create_deck → poll get_deck_status → return ready payload."""
    mcp = f"{tellr_base}/mcp/"
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

**Gotcha 2 — MCP transport sessions age out mid-poll.**
FastMCP (the MCP server library tellr uses) tracks sessions by the `mcp-session-id` returned from `initialize`. For reasons that aren't fully obvious, active polling on a session does not reset its lifetime; a 5+ minute generation will eventually hit HTTP 404 `"Session not found"` on a poll even if you're polling every 2 seconds.

Workaround: **open a fresh MCP session per tool call.** The helper `_open_session` in the example above does this. The server-side deck session (identified by `session_id` + `request_id` in the `create_deck` response) is separate from the MCP transport session and is fully persistent, so re-initialising the transport between polls is safe and cheap.

**Gotcha 3 — `deck_url` might be relative.**
If tellr's `DATABRICKS_APP_URL` env var is unset, `deck_url` comes back as a path-only string like `/sessions/.../edit`. Rendered in your app, the browser will resolve it against *your app's* origin, not tellr's. Databricks Apps sets `DATABRICKS_APP_URL` automatically on production deployments, so this should only bite during local dev or misconfigured environments.

**Gotcha 4 — Generation time.**
Single-slide prompts generate in ~10-30s, 10-slide decks take 3-8 minutes. The hard server-side timeout is 10 minutes (`JOB_HARD_TIMEOUT_SECONDS`). Match your client deadline to it or shorter.

**Gotcha 5 — `x-forwarded-email` is authoritative; you don't need to verify it.**
The proxy sets it, strips any caller-supplied version, and signs the whole interaction with TLS. Trusting it at face value is safe *only* when you're behind the Databricks Apps proxy. Don't copy this pattern to services that aren't.

---

## 3. Part B — External agent → tellr (Claude Code / Cursor / CLI)

When your MCP client is running *outside* Databricks Apps — on your laptop, in CI, or in a non-Databricks service — the proxy isn't in the way, and Databricks Apps is happy to accept an `Authorization: Bearer` header. So the integration is much simpler.

### 3.1 Auth: get a Databricks PAT

```bash
# Short-lived (auto-refreshed):
databricks auth token | jq -r .access_token

# Or create a long-lived PAT via workspace UI:
# User Settings → Developer → Access tokens → Generate new token
```

Export it:

```bash
export DATABRICKS_TOKEN=<your-token>
```

### 3.2 Wire it into your MCP client

**Claude Code / Claude Desktop:**

```bash
claude mcp add --transport http tellr "https://<tellr-app-url>/mcp/" \
  --header "Authorization: Bearer $DATABRICKS_TOKEN"
```

Then in a Claude session, run `/mcp` to confirm `tellr` shows `connected` with four tools (`create_deck`, `get_deck_status`, `edit_deck`, `get_deck`). Ask Claude to make a deck:

> Create a three-slide deck summarising our Q3 renewals, then give me the deck URL.

**Cursor / other streamable-HTTP clients:** same URL + header pattern in whatever config shape your client uses. Example shape:

```json
{
  "mcpServers": {
    "tellr": {
      "url": "https://<tellr-app-url>/mcp/",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer ${DATABRICKS_TOKEN}"
      }
    }
  }
}
```

### 3.3 Gotchas

**Token expiry.** `databricks auth token` tokens last ~1 hour. When Claude starts reporting "Authentication failed" mid-session, refresh and re-register the MCP server. PATs last as configured by the workspace admin.

**Trailing slash on the URL.** Always POST to `/mcp/` (with slash). `/mcp` (no slash) returns a 307 redirect that some clients silently downgrade to GET and break on. The `claude mcp add` command sometimes strips the trailing slash — double-check with `claude mcp list`.

**Handshake.** After `initialize`, MCP requires a `notifications/initialized` before any `tools/*`. The official MCP clients handle this for you; if you're writing raw HTTP, don't skip it.

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
| `HTTP 404 {"message": "Session not found"}` | The `mcp-session-id` you're reusing has expired. | Open a fresh MCP session (re-run `initialize` + `notifications/initialized`) per tool call in long-running poll loops. |
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
- Design spec: [`docs/superpowers/specs/2026-04-22-tellr-mcp-server-design.md`](../superpowers/specs/2026-04-22-tellr-mcp-server-design.md) — architecture rationale and v1.1 roadmap.

### 4.5 Getting help

- Something broken? Include the `correlation_id` from your tool error — server logs are keyed on it.
- Design question / feature request? Open a PR against the design spec v1.1 roadmap section.
