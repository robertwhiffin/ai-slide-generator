# Tellr MCP — accept `/mcp` and `/mcp/` interchangeably

**Date:** 2026-04-29
**Status:** Design (pending implementation)

## Problem

Tellr's MCP endpoint is mounted at `/mcp` via FastAPI's `app.mount`. Today
clients that send `POST /mcp` (no trailing slash) receive
`HTTP 405 Method Not Allowed, allow: GET` instead of either a successful
JSON-RPC response or a redirect to `/mcp/`. Clients that send `POST /mcp/`
(with the slash) work as expected.

This has bitten at least one production user (Claude Code v2.1.123 invoked
via a stdio→HTTP proxy using `databricks-sdk` external-browser OAuth and
`urllib.request`). The user's stdio→HTTP layer surfaces the 405 as a
JSON-RPC connection error and stops; there is no Location header to
follow. The user worked around it by adding the trailing slash to their
`--server-url`. Other clients (Cursor, Databricks UC HTTP-connection
proxy, Genie clients) have not been tested by us against this endpoint
but are at risk of the same failure.

## Root cause

When `_mount_frontend` runs during lifespan startup (production builds
only), it registers a SPA catch-all:

```python
@app.get("/{full_path:path}")
async def serve_spa(full_path: str): ...
```

This route claims every URL — including `/mcp` — for `GET` only. When a
`POST /mcp` arrives:

1. FastAPI's router considers the Mount at `/mcp`. Starlette's `Mount`
   matches the path (the prefix matches), strips the prefix, and forwards
   `path=""` to FastMCP's sub-app, whose only route is `/`. The empty
   path does not match `/`, so the sub-app does not handle the request.
2. The router then considers the SPA catch-all. Path matches, but the
   route is `GET`-only.
3. With at least one path-matching candidate registered for `GET`, the
   router returns `405 Method Not Allowed, allow: GET` rather than `404`.

Because the redirect-on-trailing-slash behavior in Starlette's `Mount` is
only emitted when no other route matches the path at all, the SPA
catch-all suppresses it. There is no 307 for clients to follow.

This also explains why the existing integration test
(`tests/integration/test_mcp_endpoint.py`) uses `MCP_PATH = "/mcp/"`
directly — the comment at lines 22-23 claims the bare path "returns a
307 redirect"; that comment was written before the SPA catch-all started
intercepting and is now stale.

## Decision

Add a small ASGI-level path-rewrite middleware that, when it sees a
non-`GET` request to exactly `/mcp`, rewrites the request scope's path
to `/mcp/` before route resolution runs. Routing then proceeds as if
the client had sent the slash from the start. The Mount forwards
`path="/"` to FastMCP, which handles the request normally. The client
receives a single `200` JSON-RPC response, no redirect, no method
downgrade, no header re-attachment.

This was chosen over two alternatives:

- **Return a 307 redirect for the bare path.** Still a redirect; clients
  that drop `Authorization` on redirect (a known HTTP-library
  misbehavior) or downgrade `307`→`303` (a known HTTP/1.0 fallback)
  would still fail. Doesn't fix the brittleness, just documents it.
- **Re-mount FastMCP at the root with `streamable_http_path = "/mcp"`.**
  Pulls FastMCP into the top-level app namespace, increases collision
  risk with other routes, and is a much bigger refactor for the same
  end-state.

The middleware approach is the smallest change that produces a single
round-trip success path for both URL forms.

## Implementation

### Component 1 — middleware in `src/api/main.py`

Registered immediately after the `FastAPI(...)` constructor, before any
routers or `app.mount(...)` calls. Keeping it adjacent to app
construction makes it easy to find on a future read; for an `http`
middleware the registration order versus routes does not matter
functionally.

```python
@app.middleware("http")
async def normalize_mcp_path(request: Request, call_next):
    """Make POST /mcp behave like POST /mcp/.

    The SPA catch-all (`@app.get("/{full_path:path}")` added by
    `_mount_frontend`) intercepts non-GET requests to /mcp and causes
    Starlette to return 405 instead of routing to the FastMCP Mount.
    Rewriting the ASGI scope path before route resolution sidesteps
    that interaction and avoids emitting a 307 the client has to
    follow (which can drop Authorization or method-downgrade in
    misbehaving HTTP clients).

    GET is left alone so /mcp continues to render the SPA in a browser.
    """
    if request.url.path == "/mcp" and request.method != "GET":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"
    return await call_next(request)
```

The match is exact (`== "/mcp"`), so `/mcp/`, `/mcp/anything`, and
`/mcp-something` are all unaffected. Query strings live in
`scope["query_string"]` and pass through untouched.

### Component 2 — regression test in `tests/integration/test_mcp_endpoint.py`

One new test, plus correcting the stale comment at lines 22-23. The
test runs through the existing `TestClient` fixture and uses the
existing `_mcp_headers` and `_decode_mcp_response` helpers.

```python
def test_mcp_endpoint_accepts_both_slash_forms(client):
    """Regression guard: POST /mcp and POST /mcp/ behave identically.

    The SPA catch-all (`@app.get("/{full_path:path}")`) used to make POST
    /mcp return 405 with allow: GET, since Starlette's Mount can't tell
    the outer router which methods FastMCP accepts. The normalize_mcp_path
    middleware in main.py rewrites /mcp -> /mcp/ in the ASGI scope so both
    forms reach the FastMCP sub-app's POST handler.
    """
    init = client.post(
        "/mcp/", headers=_mcp_headers(), json=_init_payload(),
        follow_redirects=False,
    )
    assert init.status_code == 200

    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}

    no_slash = client.post(
        "/mcp", headers=_mcp_headers(), json=body,
        follow_redirects=False,
    )
    with_slash = client.post(
        "/mcp/", headers=_mcp_headers(), json=body,
        follow_redirects=False,
    )

    assert no_slash.status_code == 200
    assert with_slash.status_code == 200
    no_slash_tools = {
        t["name"]
        for t in _decode_mcp_response(no_slash)["result"]["tools"]
    }
    with_slash_tools = {
        t["name"]
        for t in _decode_mcp_response(with_slash)["result"]["tools"]
    }
    assert no_slash_tools == with_slash_tools
    assert {
        "create_deck", "get_deck_status", "edit_deck", "get_deck"
    } <= no_slash_tools
```

Two things make this test load-bearing:

- `follow_redirects=False` — if a future change reintroduces a `307`,
  `308`, or `405` for the bare path, the status assertion fails loudly
  rather than silently following a redirect.
- Asserting equality of the two tool sets (not just non-empty) catches
  the case where one path resolves to a different handler than the
  other.

### Component 3 — documentation updates

Two doc files reference the trailing slash today:

- `docs/technical/mcp-server.md`
- `docs/technical/mcp-integration-guide.md`

Both should be updated to:

- State that **both `/mcp` and `/mcp/` are accepted**, either form works.
- Pick `/mcp` (no slash) as the documented canonical URL going forward,
  since it is the form most CLIs and SDKs default to. Existing client
  code that hard-codes `/mcp/` keeps working — no breaking change.

The smoke script (`scripts/mcp_smoke/mcp_smoke_httpx.py`) and the
test-client app (`mcp-test-client/app.py`) keep using `/mcp/` for now,
since both deliberately exercise the path the historical clients used.
Their docstrings get a one-line note that the slash is no longer
required.

## What this fix does NOT change

- FastMCP itself (no version bump, no monkey-patch).
- The Mount path, prefix, or `streamable_http_path` setting.
- Authentication (`mcp_auth.mcp_auth_scope`, OBO/PAT flows).
- Stateless-vs-stateful HTTP transport (still stateless per
  `mcp_server.py:141`).
- Behavior of the SPA catch-all for browser GETs to `/mcp`.

The blast radius is: requests with method ≠ `GET` and path exactly
`/mcp` (no slash). Everything else is byte-identical to current
behavior.

## Verification plan

Pre-merge (CI):

1. `pytest tests/integration/test_mcp_endpoint.py -v` passes locally
   and in CI.

Post-deploy (manual, one-time):

1. Run `mcp_smoke_httpx.py` against staging with `MCP_PATH_SUFFIX`
   temporarily set to `"/mcp"` (no slash). Expect success identical to
   the current `"/mcp/"` run.
2. Revert the smoke script change so it continues to exercise the
   historical path. The CI test now covers the new path.

## Open questions

None — the failure mode is reproduced and explained, the fix is
targeted, and the test asserts equivalence of both URL forms.
